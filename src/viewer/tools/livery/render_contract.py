from __future__ import annotations
from .png_settings import PNG_COMPRESS_LEVEL

import hashlib
import io
import json
import math
import os
import struct
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .portable_mesh_converter import read_local_chassis_projection_meshes
from .projection_alignment import build_aligned_projection_bounds
from .vehicle_assets import VehicleAsset, read_vehicle_assembly_metadata
from .derived_cache import file_sha256
from .process_file_memo import remembered


GRUB_TAG = 0x47727562
TXCB_TAG = 0x54584342
TXCH_TAG = 0x54584348
UNSIGNED_BC4 = 3
ATLAS_SIZE = (2048, 1024)
RENDER_CONTRACT_FORMAT = "lo4fh6_section_render_contract_v3"
# 38: ペイントにホイール記録が無いグループへ原本ホイールMatIの既定色を補う（wheel_default_paint）。
# 39: 車体の非塗装部品へ原本MatIの色（body_trim_colors）を渡す。__slod版の補い・骨の番号の代用廃止で車体GLBも変わる。
# 40: 車体の非塗装部品の原本色にランプの発光部（色・数値だけを読む）とナンバープレートの地の色を追加。
# 41: MTPRの型12（3成分ベクトル）を読み、ランプのガラスの色合い（GlassColorColorParam）を渡す。
# 42: 車種固有Texture、ラベル（半透明）・カーボン・反射板・窓ガラス系の原本色を追加。
# 43: 車体の非塗装部品へ原本のベースカラーTexture（PNG書き出し・UVの番号・繰り返し）を渡す。
# 46: 車体の地の色を Body の記録から、ミラー・キャリパーを Mirror・Brakes の記録から（named_paint_groups）。
# 47: ホイールの記録で色が無効・仕上げだけの場合に、仕上げの材質の色（金・スチール等）を渡す。
# 48: 車体の部品ごとの色にメーカー指定色の部品を含め、カーボン・色の無い仕上げの部品に描画用の色を付ける。
# 49: 純正の模様の板（原本の材質 livery_sticker）の画像（部品の色の記録）と、見せるか（factory_livery_stickers）を渡す。
RENDER_CONTRACT_REVISION = 49
MASK_PAGE_COUNT = 3
MASK_CHANNELS = 4
PROJECTION_MASK_CACHE_FORMAT = "lo4fh6_projection_mask_cache_v2"
PROJECTION_MASK_CACHE_REVISION = 3
PROJECTION_MASK_METADATA_FORMAT = "lo4fh6_projection_mask_metadata_v1"
PAINT_ATLAS_WIDTH = 2048
PAINT_PADDING = 8

SECTION_TO_SLOT = {
    "Front": "front",
    "Back": "back",
    "Top": "top",
    # 可搬GLB変換ではゲームのX軸を反転する。
    # 左右Maskの直接ルーティングで座標基底の差を補正し、ゲーム内の左右を維持する。
    "Left": "left",
    "Right": "right",
    "Spoiler": "wing",
    "FrontWindshield": "glass_front",
    "BackWindshield": "glass_back",
    "TopWindow": "glass_top",
    "LeftWindow": "glass_left",
    "RightWindow": "glass_right",
}
SECTION_FILTER = {
    "Front": "front",
    "FrontWindshield": "front",
    "Back": "back",
    "BackWindshield": "back",
    "Top": "top",
    "TopWindow": "top",
    "Spoiler": "top",
    "Left": "left",
    "LeftWindow": "left",
    "Right": "right",
    "RightWindow": "right",
}
SECTION_FACING = {
    "Front": (0.0, 0.0, 1.0),
    "Back": (0.0, 0.0, -1.0),
    "Top": (0.0, 1.0, 0.0),
    "Left": (1.0, 0.0, 0.0),
    "Right": (-1.0, 0.0, 0.0),
    "Spoiler": (0.0, 1.0, 0.0),
    "FrontWindshield": (0.0, 0.0, 1.0),
    "BackWindshield": (0.0, 0.0, -1.0),
    "TopWindow": (0.0, 1.0, 0.0),
    "LeftWindow": (1.0, 0.0, 0.0),
    "RightWindow": (-1.0, 0.0, 0.0),
}
SECTION_SLOT_INDEX = {section: index for index, section in enumerate(SECTION_TO_SLOT)}
TRANSPOSED_SLOTS = {"wing", "glass_front", "glass_back"}
FLIP_X_SLOTS = {"wing", "right", "glass_front", "glass_right"}
FLIP_Y_SLOTS = {"right", "glass_back", "glass_right"}
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


class LiveryRenderContractError(RuntimeError):
    pass


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _parse_pc_texture_bundle(data: bytes) -> dict[str, int]:
    if len(data) < 0x8C or _u32(data, 0) != GRUB_TAG:
        raise LiveryRenderContractError("The livery mask is not a supported Grub texture bundle.")
    major, minor = data[4], data[5]
    if major > 1 or (major == 1 and minor >= 1):
        blob_count = _u32(data, 0x10)
        blob_headers = 0x14
    else:
        blob_count = _u16(data, 0x06)
        blob_headers = 0x10

    for blob_index in range(blob_count):
        blob = blob_headers + blob_index * 0x18
        if blob + 0x18 > len(data) or _u32(data, blob) != TXCB_TAG:
            continue
        metadata_count = _u16(data, blob + 0x06)
        metadata_offset = _u32(data, blob + 0x08)
        payload_offset = _u32(data, blob + 0x0C)
        compressed_size = _u32(data, blob + 0x10)
        uncompressed_size = _u32(data, blob + 0x14)
        for metadata_index in range(metadata_count):
            metadata = metadata_offset + metadata_index * 8
            if metadata + 8 > len(data) or _u32(data, metadata) != TXCH_TAG:
                continue
            flags = _u16(data, metadata + 4)
            metadata_size = flags >> 4
            header_offset = metadata + _u16(data, metadata + 6)
            header = data[header_offset : header_offset + metadata_size]
            if len(header) < 0x40:
                raise LiveryRenderContractError("The livery mask texture header is truncated.")
            width = _u32(header, 0x18)
            height = _u32(header, 0x1C)
            depth = _u32(header, 0x20)
            slices = _u16(header, 0x24) & 0x3FFF
            mips = header[0x26]
            slices_offset = _u32(header, 0x38)
            if slices != 1 or mips != 1 or depth != 1 or slices_offset == 0:
                raise LiveryRenderContractError(
                    f"Unsupported livery mask layout: {slices} slices, {mips} mips, depth {depth}."
                )
            encoding = _u32(header, slices_offset)
            mip_array_offset = _u32(header, slices_offset + 4)
            mip_size = _u32(header, mip_array_offset)
            mip_payload_offset = _u32(header, mip_array_offset + 4)
            payload_size = uncompressed_size or compressed_size
            start = payload_offset + mip_payload_offset
            if payload_offset + payload_size > len(data) or start + mip_size > len(data):
                raise LiveryRenderContractError("The livery mask texture payload is truncated.")
            return {
                "width": width,
                "height": height,
                "encoding": encoding,
                "payload_offset": start,
                "payload_size": mip_size,
            }
    raise LiveryRenderContractError("The livery mask bundle has no supported texture payload.")


def _decode_unsigned_bc4(payload: bytes, width: int, height: int) -> np.ndarray:
    if width % 4 or height % 4:
        raise LiveryRenderContractError("BC4 livery mask dimensions must be divisible by four.")
    block_width = width // 4
    block_height = height // 4
    expected = block_width * block_height * 8
    if len(payload) != expected:
        raise LiveryRenderContractError(
            f"BC4 livery mask payload is {len(payload)} bytes; expected {expected}."
        )
    # 自前の部品（Rust）があればそれで戻す（下の numpy の計算と同じ結果。1 台の覆いで約 0.3 秒 → 約 0.015 秒。
    # 2026-11-20、FH6 に近づける案 ④）。使えなければ下の計算。
    from .native_kernels import decode_bc4_unorm
    fast = decode_bc4_unorm(payload, width, height)
    if fast is not None:
        return fast
    return _decode_unsigned_bc4_numpy(payload, width, height)


def _decode_unsigned_bc4_numpy(payload: bytes, width: int, height: int) -> np.ndarray:
    block_width = width // 4
    block_height = height // 4
    blocks = np.frombuffer(payload, dtype=np.uint8).reshape(block_height, block_width, 8)
    endpoint_0 = blocks[..., 0].astype(np.uint16)
    endpoint_1 = blocks[..., 1].astype(np.uint16)
    palette = np.empty((block_height, block_width, 8), dtype=np.uint8)
    palette[..., 0] = endpoint_0
    palette[..., 1] = endpoint_1
    eight_value = endpoint_0 > endpoint_1
    for index in range(2, 8):
        seven_step = ((8 - index) * endpoint_0 + (index - 1) * endpoint_1) // 7
        if index <= 5:
            five_step = ((6 - index) * endpoint_0 + (index - 1) * endpoint_1) // 5
        elif index == 6:
            five_step = np.zeros_like(endpoint_0)
        else:
            five_step = np.full_like(endpoint_0, 255)
        palette[..., index] = np.where(eight_value, seven_step, five_step).astype(np.uint8)
    packed_indices = np.zeros((block_height, block_width), dtype=np.uint64)
    for byte_index in range(6):
        packed_indices |= blocks[..., 2 + byte_index].astype(np.uint64) << (8 * byte_index)
    image = np.empty((height, width), dtype=np.uint8)
    for pixel_index in range(16):
        selector = ((packed_indices >> (3 * pixel_index)) & 7).astype(np.intp)
        values = np.take_along_axis(palette, selector[..., None], axis=2)[..., 0]
        image[pixel_index // 4 :: 4, pixel_index % 4 :: 4] = values
    return image


def _atlas_to_local_affine(
    slot: str,
    width: int,
    height: int,
    x_origin: float,
    y_origin: float,
) -> tuple[float, float, float, float, float, float]:
    slot = slot.casefold()
    flip_x = -1.0 if slot in FLIP_X_SLOTS else 1.0
    flip_y = -1.0 if slot in FLIP_Y_SLOTS else 1.0
    center_x = width / 2.0
    center_y = height / 2.0
    if slot in TRANSPOSED_SLOTS:
        return (
            0.0,
            -flip_x,
            center_x + flip_x * (center_y - y_origin),
            -flip_y,
            0.0,
            center_y + flip_y * (center_x + x_origin),
        )
    return (
        flip_x,
        0.0,
        center_x - flip_x * (center_x + x_origin),
        0.0,
        flip_y,
        center_y - flip_y * (center_y - y_origin),
    )


def _projection_pixel_bounds(projection: dict[str, Any]) -> tuple[int, int, int, int]:
    """FH6原本の投影矩形をAtlasの画素座標で厳密に返す。"""

    try:
        canvas_left = min(float(projection["left"]), float(projection["right"]))
        canvas_right = max(float(projection["left"]), float(projection["right"]))
        canvas_top = max(float(projection["top"]), float(projection["bottom"]))
        canvas_bottom = min(float(projection["top"]), float(projection["bottom"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveryRenderContractError("The livery projection rectangle is incomplete.") from exc

    left = int(round(ATLAS_SIZE[0] / 2.0 + canvas_left))
    right_inclusive = int(round(ATLAS_SIZE[0] / 2.0 + canvas_right))
    top = int(round(ATLAS_SIZE[1] / 2.0 - canvas_top))
    bottom_inclusive = int(round(ATLAS_SIZE[1] / 2.0 - canvas_bottom))
    if not (
        0 <= left <= right_inclusive < ATLAS_SIZE[0]
        and 0 <= top <= bottom_inclusive < ATLAS_SIZE[1]
    ):
        raise LiveryRenderContractError(
            f"The livery projection rectangle {(left, top, right_inclusive, bottom_inclusive)} is outside {ATLAS_SIZE}."
        )
    # Masks.xmlの右端・下端は終端画素を含む。
    # PILのcropと正規化Texture領域は右端・下端を含まない境界を使う。
    return left, top, right_inclusive + 1, bottom_inclusive + 1


def _projection_axis(projection: dict[str, Any], key: str, scale_key: str) -> tuple[int, float]:
    value = str(projection.get(key) or "").strip().casefold()
    axis_name = value[-1:] if value else ""
    if axis_name not in AXIS_INDEX:
        raise LiveryRenderContractError(f"The livery projection axis {key} is invalid.")
    try:
        scale = float(projection.get(scale_key, 1.0))
    except (TypeError, ValueError) as exc:
        raise LiveryRenderContractError(f"The livery projection scale {scale_key} is invalid.") from exc
    if not np.isfinite(scale) or abs(scale) < 0.000001:
        raise LiveryRenderContractError(f"The livery projection scale {scale_key} is invalid.")
    sign = -1.0 if value.startswith("-") else 1.0
    return AXIS_INDEX[axis_name], sign * scale


def _projection_mask_region(projection: dict[str, Any]) -> list[float]:
    left, top, right, bottom = _projection_pixel_bounds(projection)
    return [
        left / ATLAS_SIZE[0],
        right / ATLAS_SIZE[0],
        top / ATLAS_SIZE[1],
        bottom / ATLAS_SIZE[1],
    ]


def _archive_masks(asset: VehicleAsset) -> dict[str, tuple[Image.Image, dict[str, Any], str]]:
    with zipfile.ZipFile(asset.archive_path) as bundle:
        available = {name.casefold(): name for name in bundle.namelist()}
        xml_name = available.get("liverymasks/masks.xml")
        if not xml_name:
            raise LiveryRenderContractError(f"{asset.archive_name} has no LiveryMasks/Masks.xml.")
        projections = {
            element.tag.casefold(): dict(element.attrib)
            for element in ET.fromstring(bundle.read(xml_name))
            if element.attrib.get("valid", "false").casefold() == "true"
        }
        result: dict[str, tuple[Image.Image, dict[str, Any], str]] = {}
        for slot in sorted(set(SECTION_TO_SLOT.values())):
            name = available.get(f"liverymasks/{slot}.swatchbin")
            projection = projections.get(slot)
            if not name or projection is None:
                continue
            data = bundle.read(name)
            texture = _parse_pc_texture_bundle(data)
            if texture["encoding"] != UNSIGNED_BC4:
                raise LiveryRenderContractError(
                    f"{name} uses texture encoding {texture['encoding']}; unsigned BC4 was expected."
                )
            start = texture["payload_offset"]
            mask = _decode_unsigned_bc4(
                data[start : start + texture["payload_size"]],
                texture["width"],
                texture["height"],
            )
            runtime_mask, runtime_projection = _normalize_source_mask_to_runtime(
                Image.fromarray(mask), projection
            )
            result[slot] = (
                runtime_mask,
                runtime_projection,
                hashlib.sha256(data).hexdigest(),
            )
        return result




def _normalize_source_mask_to_runtime(
    mask: Image.Image, projection: dict[str, Any]
) -> tuple[Image.Image, dict[str, Any]]:
    """対応するFH6原本Mask配置を実行用2048×1024 Atlasへ正規化する。

    2048×1024の原本Maskは既に実行時の座標系を使用する。
    1024×1024の原本Maskは原本中央を基準とした横方向座標系なので、
    再サンプリングせず実行用ページ左半分へコピーする。
    同時に横方向の投影原点と境界を512画素左へ移し、後段のペイント切出しと
    ワールド投影が実行時中央基準の座標を引き続き使えるようにする。
    """
    source = mask.convert("L")
    width, height = source.size
    if height != ATLAS_SIZE[1] or width not in (1024, ATLAS_SIZE[0]):
        raise LiveryRenderContractError(
            f"Unsupported livery mask size {source.size}; expected 1024x1024 or {ATLAS_SIZE[0]}x{ATLAS_SIZE[1]}."
        )
    normalized_projection = dict(projection)
    if width == ATLAS_SIZE[0]:
        return source, normalized_projection

    runtime = Image.new("L", ATLAS_SIZE, 0)
    runtime.paste(source, (0, 0))
    horizontal_shift = width / 2.0 - ATLAS_SIZE[0] / 2.0
    for key in ("left", "right", "xorigin"):
        if key not in normalized_projection:
            continue
        try:
            value = float(normalized_projection[key]) + horizontal_shift
        except (TypeError, ValueError) as exc:
            raise LiveryRenderContractError(f"The livery projection value {key} is invalid.") from exc
        normalized_projection[key] = f"{value:.12g}"
    return runtime, normalized_projection

def _save_png(image: Image.Image, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    image.save(temporary, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
    os.replace(temporary, path)



def _projection_mask_cache_signature(asset: VehicleAsset) -> dict[str, Any]:
    return {
        "format_revision": PROJECTION_MASK_CACHE_REVISION,
        "archive_size": int(asset.archive_size),
        "archive_mtime_ns": int(asset.archive_mtime_ns),
        "model_code": str(asset.model_code),
        "mask_size": list(ATLAS_SIZE),
        "mask_page_count": MASK_PAGE_COUNT,
        "mask_channels": MASK_CHANNELS,
    }


def _projection_mask_cache_directory(root: Path, asset: VehicleAsset) -> Path:
    signature = _projection_mask_cache_signature(asset)
    digest = hashlib.sha256(
        json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    safe_model = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(asset.model_code))
    return root / f"{safe_model}-{digest}"


def _projection_mask_cache_manifest(cache_dir: Path) -> Path:
    return cache_dir / "projection-mask-cache.json"


def _projection_mask_cache_is_current(cache_dir: Path, signature: dict[str, Any]) -> tuple[bool, list[str], dict[str, str]]:
    manifest_path = _projection_mask_cache_manifest(cache_dir)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False, [], {}
    if not isinstance(manifest, dict) or manifest.get("format") != PROJECTION_MASK_CACHE_FORMAT:
        return False, [], {}
    if manifest.get("signature") != signature:
        return False, [], {}
    names = [str(name or "") for name in (manifest.get("files") or [])]
    hashes = manifest.get("file_sha256") if isinstance(manifest.get("file_sha256"), dict) else {}
    if len(names) != MASK_PAGE_COUNT:
        return False, [], {}
    for name in names:
        path = cache_dir / name
        if not name or Path(name).name != name or not path.is_file():
            return False, [], {}
        if file_sha256(path) != hashes.get(name):
            return False, [], {}
    return True, names, {str(key): str(value) for key, value in hashes.items()}


def _projection_mask_metadata(masks: dict[str, tuple[Image.Image, dict[str, Any], str]]) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    for slot in sorted(masks):
        _mask, projection, mask_hash = masks[slot]
        slots[slot] = {
            "projection": {str(key): str(value) for key, value in sorted(projection.items())},
            "mask_sha256": str(mask_hash),
        }
    return {"format": PROJECTION_MASK_METADATA_FORMAT, "slots": slots}


def _projection_mask_metadata_sha256(metadata: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _full_projection_mask_pages(
    masks: dict[str, tuple[Image.Image, dict[str, Any], str]]
) -> list[np.ndarray]:
    pages = [
        np.zeros((ATLAS_SIZE[1], ATLAS_SIZE[0], MASK_CHANNELS), dtype=np.uint8)
        for _ in range(MASK_PAGE_COUNT)
    ]
    for section, slot in SECTION_TO_SLOT.items():
        mask_record = masks.get(slot)
        if mask_record is None:
            continue
        mask = mask_record[0]
        if mask.size != ATLAS_SIZE:
            raise LiveryRenderContractError(
                f"{slot} mask is {mask.size}; expected {ATLAS_SIZE}."
            )
        slot_index = SECTION_SLOT_INDEX[section]
        pages[slot_index // MASK_CHANNELS][..., slot_index % MASK_CHANNELS] = np.asarray(
            mask.convert("L"), dtype=np.uint8
        )
    return pages


def _write_or_reuse_projection_mask_cache(
    root: Path,
    asset: VehicleAsset,
    mask_pages: list[np.ndarray],
    *,
    projection_metadata: dict[str, Any] | None = None,
) -> tuple[Path, list[str], dict[str, str], bool, dict[str, Any]]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    signature = _projection_mask_cache_signature(asset)
    cache_dir = _projection_mask_cache_directory(root, asset)
    cache_dir.mkdir(parents=True, exist_ok=True)
    current, names, hashes = _projection_mask_cache_is_current(cache_dir, signature)

    metadata_hash = _projection_mask_metadata_sha256(projection_metadata) if projection_metadata is not None else None
    if current and projection_metadata is None:
        return cache_dir, names, hashes, True, signature
    if not current:
        names = []
        for page_index, page in enumerate(mask_pages):
            filename = f"section-masks-{page_index}.png"
            _save_png(Image.fromarray(page), cache_dir / filename)
            names.append(filename)
        hashes = {name: file_sha256(cache_dir / name) for name in names}

    manifest = {
        "format": PROJECTION_MASK_CACHE_FORMAT,
        "signature": signature,
        "files": names,
        "file_sha256": hashes,
    }
    if projection_metadata is not None:
        manifest["projection_metadata"] = projection_metadata
        manifest["projection_metadata_sha256"] = metadata_hash
    manifest_path = _projection_mask_cache_manifest(cache_dir)
    temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return cache_dir, names, hashes, current, signature


def _read_reusable_projection_mask_cache(
    root: Path,
    asset: VehicleAsset,
) -> tuple[Path, list[str], dict[str, str], dict[str, Any], dict[str, tuple[Image.Image, dict[str, Any], str]], list[np.ndarray]] | None:
    signature = _projection_mask_cache_signature(asset)
    cache_dir = _projection_mask_cache_directory(root.resolve(), asset)
    current, names, hashes = _projection_mask_cache_is_current(cache_dir, signature)
    if not current:
        return None
    try:
        manifest = json.loads(_projection_mask_cache_manifest(cache_dir).read_text(encoding="utf-8"))
        metadata = manifest.get("projection_metadata")
        metadata_hash = str(manifest.get("projection_metadata_sha256") or "")
        if not isinstance(metadata, dict) or metadata.get("format") != PROJECTION_MASK_METADATA_FORMAT:
            return None
        if _projection_mask_metadata_sha256(metadata) != metadata_hash:
            return None
        slots = metadata.get("slots")
        if not isinstance(slots, dict):
            return None

        pages: list[np.ndarray] = []
        for name in names:
            with Image.open(cache_dir / name) as source:
                rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8).copy()
            if rgba.shape != (ATLAS_SIZE[1], ATLAS_SIZE[0], MASK_CHANNELS):
                return None
            pages.append(rgba)

        masks: dict[str, tuple[Image.Image, dict[str, Any], str]] = {}
        for section, slot in SECTION_TO_SLOT.items():
            record = slots.get(slot)
            if record is None:
                continue
            if not isinstance(record, dict) or not isinstance(record.get("projection"), dict):
                return None
            mask_hash = str(record.get("mask_sha256") or "")
            if len(mask_hash) != 64 or any(ch not in "0123456789abcdef" for ch in mask_hash.casefold()):
                return None
            slot_index = SECTION_SLOT_INDEX[section]
            values = pages[slot_index // MASK_CHANNELS][..., slot_index % MASK_CHANNELS].copy()
            masks[slot] = (Image.fromarray(values), dict(record["projection"]), mask_hash)
        if not masks:
            return None
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None
    return cache_dir, names, hashes, signature, masks, pages

def _pack_paint_layout_only(tiles: list[dict[str, Any]], *, width: int = PAINT_ATLAS_WIDTH):
    """再現可能なGPU Atlas配置だけを決め、CPU上にペイント画像を生成しない。

    GPU専用経路からのみ呼び出され、実際のAtlasフレームバッファはGPUが構築する。
    """
    ordered = sorted(tiles, key=lambda item: (-item["size"][1], -item["size"][0], int(item["slot_index"])))
    placements: dict[str, tuple[int, int, int, int]] = {}
    x = y = PAINT_PADDING
    row_height = 0
    max_bottom = PAINT_PADDING
    for item in ordered:
        w, h = item["size"]
        if not isinstance(w, int) or not isinstance(h, int) or w < 1 or h < 1:
            raise LiveryRenderContractError("GPU-only section paint bounds are invalid")
        if w + PAINT_PADDING * 2 > width:
            raise LiveryRenderContractError(f"The {item['section']} paint region is too wide for the local texture atlas.")
        if x + w + PAINT_PADDING > width:
            x = PAINT_PADDING
            y += row_height + PAINT_PADDING * 2
            row_height = 0
        placements[item["section"]] = (x, y, w, h)
        x += w + PAINT_PADDING * 2
        row_height = max(row_height, h)
        max_bottom = max(max_bottom, y + h + PAINT_PADDING)
    height = max(1, max_bottom)
    reference_atlas = width > PAINT_ATLAS_WIDTH * 2
    max_height = 16384 if reference_atlas else 8192
    max_pixels = (72 if reference_atlas else 24) * 1024 * 1024
    if height > max_height or width * height > max_pixels:
        raise LiveryRenderContractError(
            f"The local section paint atlas would be {width} x {height} pixels; use a lower --quality value."
        )
    return (width, height), placements


def _gpu_paint_adapter_metadata(
    slot: str, projection: dict[str, Any], bounds: tuple[int, int, int, int], scale: int
) -> dict[str, Any]:
    """実行時GPUアダプターに正規面の投影条件を渡す。

    メタデータに含めるのはローカル車両Maskから算出した数値投影情報だけであり、
    FH6 Vinylの幾何やLiveryペイロードは埋め込まない。
    """
    left, top, right, bottom = bounds
    a, b, c, d, e, f = _atlas_to_local_affine(
        slot, *ATLAS_SIZE, float(projection.get("xorigin", 0)), float(projection.get("yorigin", 0))
    )
    corners = [(a*x+b*y+c, d*x+e*y+f) for x in (left, right) for y in (top, bottom)]
    min_x, max_x = min(point[0] for point in corners), max(point[0] for point in corners)
    min_y, max_y = min(point[1] for point in corners), max(point[1] for point in corners)
    source_size = [round((max_x-min_x)*scale), round((max_y-min_y)*scale)]
    tile_size = [(right-left)*scale, (bottom-top)*scale]
    transform = [
        a, b, (a*left+b*top+c-min_x)*scale,
        d, e, (d*left+e*top+f-min_y)*scale,
    ]
    clear_rects = []
    width, height = source_size
    left_clip = max(0, round(-min_x*scale))
    right_start = min(width, round((2048-min_x)*scale))
    top_clip = max(0, round(-min_y*scale))
    bottom_start = min(height, round((1024-min_y)*scale))
    if left_clip > 0:
        clear_rects.append([0, 0, left_clip, height])
    if right_start < width:
        clear_rects.append([right_start, 0, width-right_start, height])
    if top_clip > 0:
        clear_rects.append([0, 0, width, top_clip])
    if bottom_start < height:
        clear_rects.append([0, bottom_start, width, height-bottom_start])
    return {
        "format": "lo4fh6_gpu_paint_adapter_section_v1",
        "source_size": source_size,
        "tile_size": tile_size,
        "world_bounds": [min_x-1024, 512-max_y, max_x-1024, 512-min_y],
        "pillow_output_to_input_affine": transform,
        "source_clear_rects": clear_rects,
        "padding_pixels": PAINT_PADDING,
    }



CAR_ATLAS_PARTS_MEMORY_KIND = "render-contract-car-atlas-parts-v1"
CAR_ATLAS_PARTS_MEMORY_LIMIT = 4


def _car_atlas_parts_key(
    asset: VehicleAsset,
    mesh_identity: tuple[str, int, int] | None,
    mesh_validation: dict | None,
    scale: int,
    shared_mask_cache_root: str | Path | None,
) -> tuple | None:
    """車ごとの部分を覚える鍵：読むファイルの識別（共有の覆いのキャッシュの全部のファイル・車の ZIP・車体の GLB）と引数。

    共有の覆いのキャッシュを使わないとき・識別を読めないときは None（覚えずに毎回求める）。
    """
    if shared_mask_cache_root is None:
        return None
    try:
        cache_dir = _projection_mask_cache_directory(Path(shared_mask_cache_root).resolve(), asset)
        files = []
        for name in sorted(os.listdir(cache_dir)):
            stat = os.stat(cache_dir / name)
            files.append((name, stat.st_size, stat.st_mtime_ns, stat.st_ino))
        archive = os.stat(asset.archive_path)
        use_projection_meshes = mesh_identity is not None and (
            mesh_validation is None or mesh_validation.get("projected_livery_meshes", 1) > 0)
        key = (str(cache_dir), tuple(files), asset, (archive.st_size, archive.st_mtime_ns, archive.st_ino),
               mesh_identity, bool(use_projection_meshes), int(scale))
        hash(key)
    except (OSError, TypeError, ValueError, AttributeError):
        return None
    return key


def _car_atlas_parts(
    asset: VehicleAsset,
    output: Path,
    local_mesh: Path | None,
    mesh_identity: tuple[str, int, int] | None,
    mesh_validation: dict | None,
    scale: int,
    shared_mask_cache_root: str | Path | None,
    cancel_event,
    progress,
) -> dict[str, Any]:
    """アトラスの組み立てのうち、ペイントに依らない車ごとの部分（覆いの読み込み・面ごとの判定・配置・合わせ込み）。

    2026-11-20：同じ車のペイントを差し替えるたびに、共有の覆いのキャッシュ（PNG 3 枚）を解いて面ごとの覆いに分け、
    同じ判定・配置・合わせ込みをやり直していた（差し替えの準備の約 14%）。共有の覆いのキャッシュから読めたときの
    結果を、_car_atlas_parts_key の鍵で同じプロセスの中だけ覚える（写しを返す。ディスクには書かない）。
    覚えた結果を使うときも、中止の確かめと進み具合の知らせは、求めたときと同じ順に行う。
    """
    key = _car_atlas_parts_key(asset, mesh_identity, mesh_validation, scale, shared_mask_cache_root)
    computed = False

    def compute() -> tuple[dict[str, Any], bool]:
        nonlocal computed
        computed = True
        return _compute_car_atlas_parts(
            asset, output, local_mesh, mesh_validation, scale, shared_mask_cache_root, cancel_event, progress)

    if key is None:
        return compute()[0]
    parts, _memoizable = remembered(
        CAR_ATLAS_PARTS_MEMORY_KIND, [], key, compute, copy="deep", limit=CAR_ATLAS_PARTS_MEMORY_LIMIT,
        keep=lambda value: bool(value[1]))
    if not computed:
        replayed = set(parts["progress_sections"])
        for section in SECTION_TO_SLOT:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("GPU paint contract preparation was cancelled")
            if section in replayed and progress:
                progress(f"Preparing GPU {section.lower()} projection")
    return parts


def _compute_car_atlas_parts(
    asset: VehicleAsset,
    output: Path,
    local_mesh: Path | None,
    mesh_validation: dict | None,
    scale: int,
    shared_mask_cache_root: str | Path | None,
    cancel_event,
    progress,
) -> tuple[dict[str, Any], bool]:
    """_car_atlas_parts の中身（以前の build_local_livery_atlases の途中をそのまま移した）。

    返り値：(車ごとの部分, 覚えてよいか)。覚えてよいのは、共有の覆いのキャッシュから読めたときだけ
    （初めて覆いを解いた回は、キャッシュの当たり・外れの印が次の回と違うため）。
    """
    shared_mask_reuse = (
        _read_reusable_projection_mask_cache(Path(shared_mask_cache_root), asset)
        if shared_mask_cache_root is not None else None
    )
    if shared_mask_reuse is not None:
        _mask_root, _names, _hashes, _sig, masks, pages = shared_mask_reuse
        mask_decode_skipped = True
    else:
        masks = _archive_masks(asset)
        pages = _full_projection_mask_pages(masks) if shared_mask_cache_root is not None else [
            np.zeros((ATLAS_SIZE[1], ATLAS_SIZE[0], MASK_CHANNELS), dtype=np.uint8)
            for _ in range(MASK_PAGE_COUNT)
        ]
        mask_decode_skipped = False

    assembly = read_vehicle_assembly_metadata(asset)
    projection_meshes = (
        read_local_chassis_projection_meshes(local_mesh)
        if local_mesh is not None
        and (mesh_validation is None or mesh_validation.get("projected_livery_meshes", 1) > 0)
        else []
    )
    tiles: list[dict[str, Any]] = []
    progress_sections: list[str] = []
    records: list[dict[str, Any]] = []
    alignment_masks: dict[int, np.ndarray] = {}
    for section, slot in SECTION_TO_SLOT.items():
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("GPU paint contract preparation was cancelled")
        record = masks.get(slot)
        if record is None:
            continue
        mask, projection, mask_hash = record
        if mask.size != ATLAS_SIZE:
            raise LiveryRenderContractError(
                f"{slot} original mask size {mask.size} != {ATLAS_SIZE}"
            )
        slot_index = SECTION_SLOT_INDEX[section]
        page, channel = divmod(slot_index, MASK_CHANNELS)
        mask_values = np.asarray(mask.convert("L"), dtype=np.uint8)
        if shared_mask_cache_root is None:
            pages[page][..., channel] = mask_values
        if mask.getbbox() is None:
            continue
        alignment_masks[slot_index] = mask_values
        bounds = _projection_pixel_bounds(projection)
        axis_x, xs = _projection_axis(projection, "xAxis", "xScale")
        axis_y, ys = _projection_axis(projection, "yAxis", "yScale")
        tiles.append({
            "section": section,
            "slot_index": slot_index,
            "size": ((bounds[2] - bounds[0]) * scale,
                     (bounds[3] - bounds[1]) * scale),
        })
        records.append({
            "section": section, "slot": slot, "slot_index": slot_index,
            "kind": "glass" if slot.startswith("glass_") else "body",
            "filter": SECTION_FILTER[section],
            "facing": list(SECTION_FACING[section]),
            "mask_page": page, "mask_channel": channel,
            "mask_sha256": mask_hash, "source_bounds": list(bounds),
            "projection_axis": [axis_x, axis_y, xs, ys],
            "projection_mask_region": _projection_mask_region(projection),
            "gpu_paint_adapter": _gpu_paint_adapter_metadata(slot, projection, bounds, scale),
            "gpu_only_required": True,
            "cpu_shadow_compare": False,  # 既存通信契約との互換のため残すGPU専用フラグ
            "visible_pixels": 0,  # 実WebGL2描画前は画素数を確定できない
        })
        progress_sections.append(section)
        if progress:
            progress(f"Preparing GPU {section.lower()} projection")

    if not tiles:
        raise LiveryRenderContractError("No original vehicle mask sections for GPU livery")
    aligned = (build_aligned_projection_bounds(
        projection_meshes, records, alignment_masks, assembly
    ) if projection_meshes else {})
    atlas_width = max(
        PAINT_ATLAS_WIDTH * scale,
        max(item["size"][0] + PAINT_PADDING * 2 for item in tiles),
    )
    paint_size, placements = _pack_paint_layout_only(tiles, width=atlas_width)

    mask_names: list[str] = []
    mask_hashes: dict[str, str] = {}
    mask_cache = {
        "scope": "per-livery", "root": str(output),
        "cache_hit": False, "decode_skipped": False,
    }
    if shared_mask_cache_root is not None:
        if shared_mask_reuse is not None:
            mask_root, mask_names, mask_hashes, mask_signature, _masks, _pages = shared_mask_reuse
            mask_cache_hit = True
        else:
            root = Path(shared_mask_cache_root).resolve()
            metadata = _projection_mask_metadata(masks)
            mask_root, mask_names, mask_hashes, mask_cache_hit, mask_signature = (
                _write_or_reuse_projection_mask_cache(
                    root, asset, pages, projection_metadata=metadata
                )
            )
        mask_cache = {
            "scope": "shared-by-model-archive",
            "format": PROJECTION_MASK_CACHE_FORMAT,
            "root": str(mask_root),
            "cache_hit": mask_cache_hit,
            "decode_skipped": mask_decode_skipped,
            "signature": mask_signature,
        }
    else:
        for page, mask_pixels in enumerate(pages):
            name = f"section-masks-{page}.png"
            _save_png(Image.fromarray(mask_pixels), output / name)
            mask_names.append(name)
        mask_hashes = {name: file_sha256(output / name) for name in mask_names}

    for record in records:
        placement = aligned.get(record["slot_index"])
        if placement is not None:
            record["projection_minimum"] = placement["minimum"]
            record["projection_maximum"] = placement["maximum"]
            record["projection_alignment"] = placement["alignment"]
        left, top, width, height = placements[record["section"]]
        sl, st, sr, sb = record.pop("source_bounds")
        record["source_region"] = [
            sl / ATLAS_SIZE[0], st / ATLAS_SIZE[1],
            sr / ATLAS_SIZE[0], sb / ATLAS_SIZE[1],
        ]
        record["paint_region"] = [
            left / paint_size[0], top / paint_size[1],
            (left + width) / paint_size[0], (top + height) / paint_size[1],
        ]
    records.sort(key=lambda item: item["slot_index"])
    parts = {
        "assembly": assembly,
        "projection_bounds_source": (
            "local-chassis-mask-alignment-v1" if projection_meshes
            else "direct-uv-only" if local_mesh is not None else "viewer-legacy-bounds"
        ),
        "paint_size": list(paint_size),
        "filters": [
            name for name in ("all", "top", "left", "right", "front", "back")
            if name == "all" or any(r["filter"] == name for r in records)
        ],
        "mask_names": mask_names,
        "mask_hashes": mask_hashes,
        "mask_cache": mask_cache,
        "records": records,
        "progress_sections": progress_sections,
    }
    return parts, shared_mask_reuse is not None


def build_local_livery_atlases(
    package_path: Path | str,
    asset: VehicleAsset,
    output_dir: Path | str,
    *,
    mesh_path: Path | str | None = None,
    mesh_validation: dict | None = None,
    cancel_event=None,
    progress=None,
    quality_scale: int = 1,
    shared_mask_cache_root: str | Path | None = None,
    cpu_shadow_policy: str = "gpu-only",
) -> dict[str, Any]:
    """GPUペイント配置と原本車両Mask契約だけを構築する。

    削除したCPUペイントはPillowで図形を描画し、埋込み面PNGを受け付け、
    section-paint.pngとCPU Atlasキャッシュを作成していた。
    これらの経路はすべて非対応とし、旧ペイント処理へ無告知で戻さない。
    """
    if cpu_shadow_policy != "gpu-only":
        raise LiveryRenderContractError("CPU livery paint is removed; WebGL2-only is required")
    if quality_scale not in (1, 2, 3, 4):
        raise LiveryRenderContractError(f"Unsupported paint quality: {quality_scale}")
    started = time.perf_counter()
    package = Path(package_path).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    scale = int(quality_scale)
    signature = {
        "contract_revision": RENDER_CONTRACT_REVISION,
        "package_sha256": file_sha256(package),
        "archive_size": asset.archive_size,
        "archive_mtime_ns": asset.archive_mtime_ns,
        "model_code": asset.model_code,
        "quality_scale": scale,
        "cpu_shadow_policy": "gpu-only",
        "paint_rasterizer": "webgl2-only",
    }
    local_mesh = Path(mesh_path).resolve() if mesh_path else None
    mesh_identity: tuple[str, int, int] | None = None
    if local_mesh is not None:
        stat = local_mesh.stat()
        signature.update(mesh_size=stat.st_size, mesh_mtime_ns=stat.st_mtime_ns)
        mesh_identity = (str(local_mesh), stat.st_size, stat.st_mtime_ns)
    index_path = output / "index.json"
    if index_path.is_file():
        try:
            cached = json.loads(index_path.read_text(encoding="utf-8"))
            files = cached.get("files") or {}
            masks = list(files.get("masks") or [])
            cached_mask = cached.get("mask_cache") or {}
            root = Path(cached_mask.get("root") or output).resolve()
            hashes = cached.get("file_sha256") or {}
            if (cached.get("format") == RENDER_CONTRACT_FORMAT
                    and cached.get("signature") == signature
                    and cached.get("paint_rasterizer") == "webgl2-only"
                    and not files.get("paint")
                    and len(masks) == MASK_PAGE_COUNT
                    and all(isinstance(n, str) and Path(n).name == n
                            and (root / n).is_file()
                            and file_sha256(root / n) == hashes.get(n)
                            for n in masks)):
                return {**cached, "root": str(output), "cache_hit": True,
                        "prepare_profile": {"total_seconds": time.perf_counter() - started}}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    parts = _car_atlas_parts(
        asset, output, local_mesh, mesh_identity, mesh_validation, scale, shared_mask_cache_root,
        cancel_event, progress,
    )
    result = {
        "format": RENDER_CONTRACT_FORMAT,
        "signature": signature,
        "uv_contract": {
            "attribute": "TEXCOORD_3", "u_scale": 0.5,
            "flip_u": False, "flip_v": False, "world_projection_fallback": True,
        },
        "assembly": parts["assembly"],
        "projection_bounds_source": parts["projection_bounds_source"],
        "paint_size": parts["paint_size"],
        "quality_scale": scale,
        "quality_source": "webgl2-direct-atlas-only",
        "quality_notes": [],
        "cpu_shadow_policy": "gpu-only",  # 既存ブラウザー契約名を維持
        "paint_rasterizer": "webgl2-only",
        "mask_size": list(ATLAS_SIZE),
        "filters": parts["filters"],
        "files": {"paint": None, "masks": parts["mask_names"]},
        "file_sha256": parts["mask_hashes"],
        "paint_cache": {
            "scope": "gpu-session-only", "root": str(output),
            "cache_hit": False, "render_skipped": True,
        },
        "mask_cache": parts["mask_cache"],
        "sections": parts["records"],
    }
    temporary = index_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, index_path)
    return {
        **result, "root": str(output), "cache_hit": False,
        "prepare_profile": {"total_seconds": time.perf_counter() - started},
    }
