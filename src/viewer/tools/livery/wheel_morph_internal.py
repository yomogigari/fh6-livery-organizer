"""FH6 WheelStyle Morphをローカル車体GLBへ適用する独立最終処理。
Converterが保全した原本Entry・Instance識別子、利用者のWheelStyle ModelBin Morph Buffer、GameDBのRim係数を組み合わせる。
POSITION／NORMALを書き換え、検証済みGameDBのWheel中心へWheelStyleとBrakesを剛体配置できる。
外部比較Helperは実行せず、MIT 参照製品の固定済み出典を参照する。GPL公開研究は動作の裏付けのみに使用する。
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .portable_mesh_converter import _accessor_array, _glb_payloads, validate_local_chassis_glb, seal_firstparty_chassis_metadata
from .glb_compact import drop_hidden_meshes
from .vehicle_assets import VehicleAsset
from .independent_chassis.source_static_preview_selection import clean_original_static_triangle_indices

# 参照製品 cleaned-index + 原本Mesh offset/Bone識別の製品仕様を旧v5キャッシュから分離。
# 旧キャッシュ/履歴は削除せず、標準入口で新規v6を署名付き生成。
INTERNAL_WHEEL_MORPH_REVISION = 8
WHEEL_RENDER_PASS_FILTER_REVISION = 4
# 3: 左右対称のトレッド幅の差だけの移動を0.30mまで許容（2026-11-17）。旧キャッシュは作り直す。
# 4: 安全上限で移動をやめてcarbinの位置に戻すとき、各車輪のcarbinの車軸位置を報告へ残す（2026-11-17）。
WHEEL_GAMEDB_PLACEMENT_REVISION = 9
WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M = 0.15
# carbinのホイール位置とGameDBの車輪中心の差が、左右（X）だけの対称な移動のとき（トレッド幅の差）の上限。
# 2026-11-17 抜き取り撮影：LAM_Temerario_24は前16/後12cm、FER_488Pista_19は前後21cm、いずれも外側への
# 左右対称の移動（上下≦5cm、前後≦4mm）。carbinの位置のままではホイールがアーチ奥へ沈み（純正車体の
# 画像で確認）、Tireの車軸照合でも停止していた。対応付けの誤りを防ぐ0.15mの上限は、この形に限り広げる。
WHEEL_GAMEDB_PLACEMENT_MAX_LATERAL_SHIFT_M = 0.30
WHEEL_GAMEDB_PLACEMENT_LATERAL_MAX_Y_M = 0.06
WHEEL_GAMEDB_PLACEMENT_LATERAL_MAX_Z_M = 0.02
WHEEL_GAMEDB_PLACEMENT_LATERAL_SYMMETRY_M = 0.01

_TAG_GRUB = 0x47727562
_TAG_MESH = 0x4D657368
_TAG_INDB = 0x496E6442
_TAG_VLAY = 0x564C6179
_TAG_ILAY = 0x494C6179
_TAG_VERB = 0x56657242
_TAG_MBUF = 0x4D427566
_META_NAME = 0x4E616D65
_META_ID = 0x49642020
_FORMAT_SIZES = {6: 12, 10: 8, 13: 8, 16: 8, 24: 4, 28: 4, 35: 4, 37: 4}
_WHEEL_BONE_RE = re.compile(r"\|(spindle(?:lf|rf|lr|rr|lm|rm))\|", re.IGNORECASE)
_IDENTITY_MATRIX_RE = re.compile(r"^(?:[0-9a-fA-F]{8},){15}[0-9a-fA-F]{8}$")
_WHEEL_SUFFIX_RE = re.compile(r"(lf|rf|lr|rr|lm|rm)$", re.IGNORECASE)
_WHEEL_NAME_BY_BONE = {
    "spindlelf": "front_left",
    "spindlerf": "front_right",
    "spindlelr": "rear_left",
    "spindlerr": "rear_right",
    "spindlelm": "middle_left",
    "spindlerm": "middle_right",
}
_WHEEL_NAME_BY_SUFFIX = {
    "lf": "front_left",
    "rf": "front_right",
    "lr": "rear_left",
    "rr": "rear_right",
    "lm": "middle_left",
    "rm": "middle_right",
}
# 6 輪の車（MER_G63AMG6x6_14・HEN_Velociraptor6x6_18）の中央の車輪。GameDB には前・後ろの車軸しか無いため、
# 変形とタイヤの寸法は後輪の値を使い、GameDB の配置では同じ側の後輪と同じだけ動かす（車輪どうしの間隔は
# Carbin のまま）。参照製品の 1 つも中央の車輪は Carbin の位置のまま描く（参照のみ）。
MIDDLE_WHEEL_FOLLOWS = {"middle_left": "rear_left", "middle_right": "rear_right"}
_WHEEL_PLACEMENT_PART_TYPES = {"wheelstyle", "brakes"}
# 足回りのコントロールアーム（骨 controlArm_LF 等。部品の種類は CarBody）も、ゲームではホイールの位置から
# 置かれる（source_skeleton_pose.presentation_control_arm_matrices）ため、同じ車輪の移動に合わせて動かす。
CONTROL_ARM_PART_LABEL = "ControlArm"


def _follows_wheel_placement(part_type: str, parsed: dict[str, Any]) -> str | None:
    """GameDB の車輪の配置で一緒に動かす部品なら、記録の名前（部品の種類）を返す。"""
    if part_type.casefold() in _WHEEL_PLACEMENT_PART_TYPES:
        return part_type
    if str(parsed.get("attachment_bone") or "").casefold().startswith("controlarm"):
        return CONTROL_ARM_PART_LABEL
    return None


class WheelMorphInternalError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Blob:
    index: int
    tag: int
    major: int
    minor: int
    metadata: dict[int, bytes]
    data: memoryview
    offset: int

    @property
    def name(self) -> str:
        raw = self.metadata.get(_META_NAME, b"")
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")

    @property
    def identifier(self) -> int | None:
        raw = self.metadata.get(_META_ID)
        return struct.unpack_from("<I", raw, 0)[0] if raw and len(raw) >= 4 else None


@dataclass(frozen=True)
class _Buffer:
    blob: _Blob
    length: int
    size: int
    stride: int
    fmt: int
    raw: memoryview


@dataclass(frozen=True)
class _Element:
    semantic: str
    semantic_index: int
    input_slot: int
    fmt: int
    offset: int


@dataclass(frozen=True)
class _Usage:
    index: int
    input_slot: int
    stride: int
    offset: int


@dataclass(frozen=True)
class _Mesh:
    blob: _Blob
    name: str
    material_groups: tuple[tuple[int, ...], ...]
    material_id: int
    bucket_flags: int
    is_morph_damage: bool
    morph_count: int
    index_buffer_offset: int
    index_draw_offset: int
    indexed_vertex_offset: int
    index_count: int
    is_32bit_indices: bool
    vertex_layout_index: int
    usages: tuple[_Usage, ...]
    morph_buffer_index: int
    position_scale: tuple[float, float, float, float]
    position_translate: tuple[float, float, float, float]


@dataclass(frozen=True)
class _MorphGeometry:
    name: str
    vertex_count: int
    triangle_count: int
    source_mesh_offset: int
    source_clean_indices: np.ndarray
    bucket_flags: int
    material_id: int
    material_name: str
    base_positions: np.ndarray
    base_normals: np.ndarray | None
    diameter_position_delta: np.ndarray
    width_position_delta: np.ndarray
    diameter_normal_delta: np.ndarray | None
    width_normal_delta: np.ndarray | None


def _version_at_least(major: int, minor: int, wanted_major: int, wanted_minor: int) -> bool:
    return major > wanted_major or (major == wanted_major and minor >= wanted_minor)


def _read_metadata(data: memoryview, count: int, offset: int) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    for i in range(count):
        base = offset + i * 8
        if base < 0 or base + 8 > len(data):
            raise WheelMorphInternalError("modelbin metadata header is out of bounds")
        tag, flags, relative = struct.unpack_from("<IHH", data, base)
        size = flags >> 4
        start = base + relative
        if start < 0 or start + size > len(data):
            raise WheelMorphInternalError("modelbin metadata payload is out of bounds")
        result[tag] = bytes(data[start : start + size])
    return result


def _parse_blobs(payload: bytes) -> list[_Blob]:
    data = memoryview(payload)
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != _TAG_GRUB:
        raise WheelMorphInternalError("WheelStyle source is not a supported modelbin bundle")
    major, minor = int(data[4]), int(data[5])
    if _version_at_least(major, minor, 1, 1):
        if len(data) < 20:
            raise WheelMorphInternalError("modelbin header is truncated")
        blob_count = struct.unpack_from("<I", data, 16)[0]
        headers_start = 20
    else:
        blob_count = struct.unpack_from("<H", data, 6)[0]
        headers_start = 16
    if blob_count > 20000 or headers_start + blob_count * 24 > len(data):
        raise WheelMorphInternalError("modelbin blob table is invalid")
    blobs: list[_Blob] = []
    for index in range(blob_count):
        base = headers_start + index * 24
        tag, bmaj, bmin, meta_count, meta_offset, data_offset, compressed, uncompressed = struct.unpack_from(
            "<IBBHIIII", data, base
        )
        size = int(uncompressed or compressed)
        if compressed != uncompressed and uncompressed:
            raise WheelMorphInternalError("compressed modelbin blobs are not supported by the independent morph path")
        if data_offset < 0 or data_offset + size > len(data):
            raise WheelMorphInternalError("modelbin blob payload is out of bounds")
        blobs.append(
            _Blob(
                index=index,
                tag=tag,
                major=bmaj,
                minor=bmin,
                metadata=_read_metadata(data, meta_count, meta_offset),
                data=data[data_offset : data_offset + size],
                offset=int(data_offset),
            )
        )
    return blobs


def _parse_buffer(blob: _Blob) -> _Buffer:
    if len(blob.data) < 12:
        raise WheelMorphInternalError("model buffer header is truncated")
    length, size, stride = struct.unpack_from("<iiH", blob.data, 0)
    header_size = 16 if blob.major >= 1 else 12
    fmt = struct.unpack_from("<i", blob.data, 12)[0] if blob.major >= 1 else 0
    if length < 0 or size < 0 or stride < 0 or header_size + size > len(blob.data):
        raise WheelMorphInternalError("model buffer header is invalid")
    raw_size = size if size else length * stride
    if header_size + raw_size > len(blob.data):
        raise WheelMorphInternalError("model buffer data is truncated")
    return _Buffer(blob, length, size, stride, fmt, blob.data[header_size : header_size + raw_size])


def _read_counted_ascii(data: memoryview, offset: int) -> tuple[str, int]:
    if offset + 4 > len(data):
        raise WheelMorphInternalError("vertex-layout string length is truncated")
    count = struct.unpack_from("<i", data, offset)[0]
    offset += 4
    if count < 0 or offset + count > len(data):
        raise WheelMorphInternalError("vertex-layout string is invalid")
    return bytes(data[offset : offset + count]).decode("utf-8", errors="replace"), offset + count


def _parse_layout(blob: _Blob) -> list[_Element]:
    data = blob.data
    if len(data) < 2:
        raise WheelMorphInternalError("vertex layout is truncated")
    offset = 0
    semantic_count = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    semantics: list[str] = []
    for _ in range(semantic_count):
        value, offset = _read_counted_ascii(data, offset)
        semantics.append(value)
    if offset + 2 > len(data):
        raise WheelMorphInternalError("vertex-layout element count is truncated")
    element_count = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    raw_elements: list[tuple[int, int, int, int]] = []
    for _ in range(element_count):
        if offset + 20 > len(data):
            raise WheelMorphInternalError("vertex-layout element is truncated")
        semantic_name, semantic_index, input_slot, _slot_class, fmt, _aligned, _step = struct.unpack_from(
            "<hhhhiii", data, offset
        )
        offset += 20
        raw_elements.append((semantic_name, semantic_index, input_slot, fmt))
    slot_offsets: dict[int, int] = {}
    elements: list[_Element] = []
    for semantic_name, semantic_index, input_slot, fmt in raw_elements:
        if fmt not in _FORMAT_SIZES:
            size = 4
        else:
            size = _FORMAT_SIZES[fmt]
        item_offset = slot_offsets.get(input_slot, 0)
        slot_offsets[input_slot] = item_offset + size
        semantic = semantics[semantic_name] if 0 <= semantic_name < len(semantics) else "UNKNOWN"
        elements.append(_Element(semantic, semantic_index, input_slot, fmt, item_offset))
    return elements


def _parse_mesh(blob: _Blob) -> _Mesh:
    data = blob.data
    off = 0
    groups = struct.unpack_from("<i", data, off)[0] if _version_at_least(blob.major, blob.minor, 1, 13) else 1
    if _version_at_least(blob.major, blob.minor, 1, 13):
        off += 4
    if groups <= 0 or groups > 1000:
        raise WheelMorphInternalError("mesh material-group count is invalid")
    material_groups: list[tuple[int, ...]] = []
    for _ in range(groups):
        if _version_at_least(blob.major, blob.minor, 1, 9):
            if off + 8 > len(data):
                raise WheelMorphInternalError("mesh material group is truncated")
            material_groups.append(tuple(int(value) for value in struct.unpack_from("<4h", data, off)))
            off += 8
        else:
            if off + 2 > len(data):
                raise WheelMorphInternalError("mesh material group is truncated")
            material_groups.append((int(struct.unpack_from("<h", data, off)[0]),))
            off += 2
    primary_material_group = material_groups[0] if material_groups else ()
    material_id = (
        int(primary_material_group[1])
        if len(primary_material_group) >= 2
        else int(primary_material_group[0]) if primary_material_group else -1
    )
    if off + 2 + 2 + 1 + 1 + 2 + 1 > len(data):
        raise WheelMorphInternalError("mesh header is truncated")
    off += 2  # rigid bone
    off += 2  # LOD flags
    off += 2  # min/max LOD bytes
    bucket_flags = struct.unpack_from("<H", data, off)[0]
    off += 2
    off += 1  # bucket order
    morph_count = 0
    if _version_at_least(blob.major, blob.minor, 1, 2):
        off += 1  # Skinning要素数
        if _version_at_least(blob.major, blob.minor, 1, 10):
            morph_count = struct.unpack_from("<I", data, off)[0]
            off += 4
        else:
            morph_count = int(data[off])
            off += 1
    is_morph_damage = True
    if _version_at_least(blob.major, blob.minor, 1, 3):
        is_morph_damage = bool(data[off])
        off += 1
    is_32 = bool(data[off])
    off += 1
    off += 2  # topology
    if off + 24 > len(data):
        raise WheelMorphInternalError("mesh index fields are truncated")
    _index_buffer_index, index_buffer_offset, index_draw_offset, indexed_vertex_offset, index_count, _prim_count = struct.unpack_from(
        "<iiiiii", data, off
    )
    off += 24
    if _version_at_least(blob.major, blob.minor, 1, 6):
        off += 8
    if _version_at_least(blob.major, blob.minor, 1, 11):
        if off + 4 > len(data):
            raise WheelMorphInternalError("mesh referenced-vertex list is truncated")
        referenced_count = struct.unpack_from("<I", data, off)[0]
        off += 4 + referenced_count * 4
    if off + 8 > len(data):
        raise WheelMorphInternalError("mesh vertex-layout fields are truncated")
    vertex_layout_index, usage_count = struct.unpack_from("<ii", data, off)
    off += 8
    usages: list[_Usage] = []
    for _ in range(usage_count):
        record_size = 20 if _version_at_least(blob.major, blob.minor, 1, 12) else 16
        if off + record_size > len(data):
            raise WheelMorphInternalError("mesh vertex-buffer usage is truncated")
        index, slot, stride, usage_offset = struct.unpack_from("<iIII", data, off)
        off += record_size
        usages.append(_Usage(index, int(slot), int(stride), int(usage_offset)))
    morph_buffer_index = -1
    if _version_at_least(blob.major, blob.minor, 1, 4):
        if off + 8 > len(data):
            raise WheelMorphInternalError("mesh morph-buffer fields are truncated")
        morph_buffer_index, _skin = struct.unpack_from("<ii", data, off)
        off += 8
    if off + 4 > len(data):
        raise WheelMorphInternalError("mesh constant-buffer count is truncated")
    cb_count = struct.unpack_from("<i", data, off)[0]
    off += 4 + max(0, cb_count) * 4
    if _version_at_least(blob.major, blob.minor, 1, 1):
        off += 4
    if _version_at_least(blob.major, blob.minor, 1, 5):
        off += 80
    scale = (1.0, 1.0, 1.0, 1.0)
    translate = (0.0, 0.0, 0.0, 0.0)
    if _version_at_least(blob.major, blob.minor, 1, 8):
        if off + 32 > len(data):
            raise WheelMorphInternalError("mesh position transform is truncated")
        scale = struct.unpack_from("<4f", data, off)
        translate = struct.unpack_from("<4f", data, off + 16)
    return _Mesh(
        blob=blob,
        name=blob.name or "Mesh",
        material_groups=tuple(material_groups),
        material_id=int(material_id),
        bucket_flags=int(bucket_flags),
        is_morph_damage=is_morph_damage,
        morph_count=int(morph_count),
        index_buffer_offset=int(index_buffer_offset),
        index_draw_offset=int(index_draw_offset),
        indexed_vertex_offset=int(indexed_vertex_offset),
        index_count=int(index_count),
        is_32bit_indices=is_32,
        vertex_layout_index=int(vertex_layout_index),
        usages=tuple(usages),
        morph_buffer_index=int(morph_buffer_index),
        position_scale=tuple(float(v) for v in scale),
        position_translate=tuple(float(v) for v in translate),
    )


def _snorm16(value: int) -> float:
    return max(-1.0, min(1.0, value / 32767.0))


def _snorm16_array(values: np.ndarray) -> np.ndarray:
    """_snorm16 を配列でまとめて（int16 → float64 の割り算と、-1〜1 への切り詰め。値は同じ）。"""
    return np.maximum(-1.0, np.minimum(1.0, values.astype(np.float64) / 32767.0))


# 頂点の要素の形式 → （numpy の型、要素の数）。_extract_morph_geometries と、元のタイヤの形の読み取り
# （source_tire_local_runtime._load_source_meshes、UV の 35）が読む形式だけ。
_VERTEX_ARRAY_TYPES = {13: ("<i2", 4), 6: ("<f4", 3), 37: ("<i2", 2), 10: ("<f2", 3), 35: ("<u2", 2)}


def _vertex_array(
    blobs: list[_Blob],
    vb_by_id: dict[int, _Buffer],
    mesh: _Mesh,
    element: _Element,
    minimum: int,
    count: int,
) -> np.ndarray | None:
    """頂点の要素を（count, 要素の数）の配列で読む（_read_vertex_components と同じ場所・同じ範囲の確かめ・同じ例外）。

    頂点の間隔が負のときは None（呼び出し側は 1 つずつ読む）。
    """
    shape = _VERTEX_ARRAY_TYPES.get(element.fmt)
    usage = next((u for u in mesh.usages if u.input_slot == element.input_slot), None)
    if usage is None:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} has no vertex buffer for slot {element.input_slot}")
    buffer = vb_by_id.get(usage.index)
    if buffer is None and 0 <= usage.index < len(blobs) and blobs[usage.index].tag == _TAG_VERB:
        buffer = _parse_buffer(blobs[usage.index])
    if buffer is None:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} cannot resolve vertex buffer {usage.index}")
    stride = buffer.stride or usage.stride
    if shape is None or stride < 0 or count <= 0:
        return None
    first = usage.offset + (minimum + mesh.indexed_vertex_offset) * stride + element.offset
    last = first + (count - 1) * stride
    # 場所は頂点ごとに同じ間隔で増えるので、最初と最後の頂点を確かめれば全部を確かめたのと同じ。
    if first < 0 or last + _FORMAT_SIZES.get(element.fmt, 4) > len(buffer.raw):
        raise WheelMorphInternalError(f"mesh {mesh.name!r} vertex buffer is out of bounds")
    dtype, components = shape
    item = np.dtype(dtype).itemsize
    return np.ndarray((count, components), dtype=dtype, buffer=buffer.raw, offset=first, strides=(stride, item))


_ROW_DOTS_MATCH: bool | None = None


def _row_dots_match() -> bool:
    """matmul で求めた各行の dot が、1 行ずつの value.dot(value)（np.linalg.norm の中身）と同じか（プロセスで 1 回）。

    numpy の版や BLAS の選び方で違えば、法線は今までどおり 1 行ずつ np.linalg.norm で求める。
    """
    global _ROW_DOTS_MATCH
    if _ROW_DOTS_MATCH is None:
        rng = np.random.default_rng(20261120)
        sample = _snorm16_array(rng.integers(-32768, 32768, size=(512, 3)).astype(np.int16))
        sample[:64] *= 1e-7
        expected = np.array([row.dot(row) for row in sample], dtype=np.float64)
        got = np.matmul(sample[:, None, :], sample[:, :, None])[:, 0, 0]
        _ROW_DOTS_MATCH = bool(np.array_equal(got.view(np.uint64), expected.view(np.uint64)))
    return _ROW_DOTS_MATCH


def _row_dots(values: np.ndarray) -> np.ndarray:
    """各行の value.dot(value)。matmul のベクトルどうしの積は、1 行ずつの dot と同じ関数を通す。"""
    values = np.ascontiguousarray(values, dtype=np.float64)
    return np.matmul(values[:, None, :], values[:, :, None])[:, 0, 0]


def _half(data: memoryview, offset: int) -> float:
    return float(struct.unpack_from("<e", data, offset)[0])


def _resolve_by_id_or_index(blobs: list[_Blob], tagged: list[_Blob], wanted: int) -> _Blob | None:
    for blob in tagged:
        if blob.identifier is not None and int(blob.identifier) == wanted:
            return blob
    if 0 <= wanted < len(blobs) and blobs[wanted].tag in {blob.tag for blob in tagged}:
        return blobs[wanted]
    return None


def _read_indices(index_buffer: _Buffer, mesh: _Mesh) -> np.ndarray:
    stride = 4 if mesh.is_32bit_indices else 2
    start = mesh.index_buffer_offset + mesh.index_draw_offset * stride
    end = start + mesh.index_count * stride
    if mesh.index_count <= 0 or start < 0 or end > len(index_buffer.raw):
        raise WheelMorphInternalError(f"mesh {mesh.name!r} has invalid index bounds")
    dtype = np.dtype("<u4" if stride == 4 else "<u2")
    return np.frombuffer(index_buffer.raw, dtype=dtype, count=mesh.index_count, offset=start).astype(np.int64)


def _read_vertex_components(
    blobs: list[_Blob],
    vb_by_id: dict[int, _Buffer],
    mesh: _Mesh,
    element: _Element,
    minimum: int,
    count: int,
) -> list[memoryview]:
    usage = next((u for u in mesh.usages if u.input_slot == element.input_slot), None)
    if usage is None:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} has no vertex buffer for slot {element.input_slot}")
    buffer = vb_by_id.get(usage.index)
    if buffer is None and 0 <= usage.index < len(blobs) and blobs[usage.index].tag == _TAG_VERB:
        buffer = _parse_buffer(blobs[usage.index])
    if buffer is None:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} cannot resolve vertex buffer {usage.index}")
    stride = buffer.stride or usage.stride
    result: list[memoryview] = []
    for row in range(count):
        vertex_id = minimum + row + mesh.indexed_vertex_offset
        addr = usage.offset + vertex_id * stride + element.offset
        if addr < 0 or addr + _FORMAT_SIZES.get(element.fmt, 4) > len(buffer.raw):
            raise WheelMorphInternalError(f"mesh {mesh.name!r} vertex buffer is out of bounds")
        result.append(buffer.raw[addr:])
    return result


def _selector_delta_records(
    morph: _Buffer,
    mesh: _Mesh,
    minimum: int,
    count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if morph.fmt != 10:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} uses unsupported morph format {morph.fmt}")
    if mesh.morph_count <= 0 or mesh.morph_count > 16:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} has unsupported morph target count {mesh.morph_count}")
    required_stride = mesh.morph_count * 16
    if morph.stride < required_stride:
        raise WheelMorphInternalError(
            f"mesh {mesh.name!r} morph stride {morph.stride} is smaller than {required_stride}"
        )
    p0 = np.zeros((count, 3), dtype=np.float64)
    p1 = np.zeros((count, 3), dtype=np.float64)
    n0 = np.zeros((count, 3), dtype=np.float64)
    n1 = np.zeros((count, 3), dtype=np.float64)
    # r388：頂点ごとに小さなNumPy配列を作らず、Half Float記録をStride付きの単一配列で復号する。
    # 蓄積前に読み取り範囲全体とSelectorを検証する。
    first_vertex = minimum + mesh.indexed_vertex_offset
    if count < 0 or first_vertex < 0 or morph.stride <= 0:
        raise WheelMorphInternalError(f"mesh {mesh.name!r} morph buffer is out of bounds")
    last_end = (first_vertex + count - 1) * morph.stride + required_stride if count else 0
    if last_end > len(morph.raw):
        raise WheelMorphInternalError(f"mesh {mesh.name!r} morph buffer is out of bounds")
    if count:
        records = np.ndarray(
            shape=(count, 2, mesh.morph_count, 4),
            dtype=np.dtype("<f2"),
            buffer=morph.raw,
            offset=first_vertex * morph.stride,
            strides=(morph.stride, mesh.morph_count * 8, 8, 2),
        ).astype(np.float64)
        selectors = records[:, :, :, 3]
        rounded = np.rint(selectors)
        with np.errstate(invalid="ignore"):
            valid = (
                np.isfinite(selectors)
                & (np.abs(selectors - rounded) <= 1e-3)
                & ((rounded == 0) | (rounded == 1))
            )
        if not bool(np.all(valid)):
            bad = float(selectors[~valid][0])
            raise WheelMorphInternalError(
                f"mesh {mesh.name!r} has unsupported WheelStyle morph selector {bad!r}"
            )
        # Morph記録が同じSelectorを参照しても、対象ごとの原本加算順を維持する。
        # これにより丸め誤差のずれも避ける。
        for normal_pass in range(2):
            for target in range(mesh.morph_count):
                values = records[:, normal_pass, target, :3]
                is_zero = rounded[:, normal_pass, target] == 0
                zero_target, one_target = (n0, n1) if normal_pass else (p0, p1)
                if bool(np.any(is_zero)):
                    zero_target[is_zero] += values[is_zero]
                is_one = ~is_zero
                if bool(np.any(is_one)):
                    one_target[is_one] += values[is_one]
    return p0, p1, n0, n1


def _extract_morph_geometries(payload: bytes) -> list[_MorphGeometry]:
    blobs = _parse_blobs(payload)
    mesh_blobs = [b for b in blobs if b.tag == _TAG_MESH]
    index_blobs = [b for b in blobs if b.tag == _TAG_INDB]
    layout_blobs = [b for b in blobs if b.tag in {_TAG_VLAY, _TAG_ILAY}]
    vb_blobs = [b for b in blobs if b.tag == _TAG_VERB]
    morph_blobs = [b for b in blobs if b.tag == _TAG_MBUF]
    if not index_blobs:
        return []
    index_buffer = _parse_buffer(index_blobs[0])
    layouts = [_parse_layout(b) for b in layout_blobs]
    layout_by_id = {int(b.identifier): _parse_layout(b) for b in layout_blobs if b.identifier is not None}
    vb_by_id = {int(b.identifier): _parse_buffer(b) for b in vb_blobs if b.identifier is not None}
    morph_by_id = {int(b.identifier): _parse_buffer(b) for b in morph_blobs if b.identifier is not None}
    parsed_morphs = [_parse_buffer(b) for b in morph_blobs]
    material_name_by_id = {
        int(blob.identifier): blob.name
        for blob in blobs
        if blob.identifier is not None and blob.name
    }
    output: list[_MorphGeometry] = []
    for mesh_blob in mesh_blobs:
        mesh = _parse_mesh(mesh_blob)
        if mesh.morph_count <= 0 or mesh.is_morph_damage or mesh.morph_buffer_index < 0:
            continue
        layout = layout_by_id.get(mesh.vertex_layout_index)
        if layout is None and 0 <= mesh.vertex_layout_index < len(layouts):
            layout = layouts[mesh.vertex_layout_index]
        if not layout:
            continue
        position = next((e for e in layout if e.semantic == "POSITION"), None)
        normal = next((e for e in layout if e.semantic == "NORMAL"), None)
        if position is None or position.fmt not in {6, 13}:
            continue
        indices = _read_indices(index_buffer, mesh)
        minimum, maximum = int(indices.min()), int(indices.max())
        if len(indices) % 3:
            raise WheelMorphInternalError(f"mesh {mesh.name!r} has non-triangle index data")
        # First-party Converterは参照製品 CleanTriangleIndicesを使って重複・退化面を
        # 整理し winding を反転する。元Meshから同じ結果を再計算して厳密照合する。
        source_clean_indices = clean_original_static_triangle_indices(
            (indices - minimum).reshape(-1, 3)
        ).reshape(-1)
        count = maximum - minimum + 1
        if count <= 0:
            continue
        sx, sy, sz, _ = mesh.position_scale
        tx, ty, tz, _ = mesh.position_translate
        use_scale = any(abs(v) > 0.0 for v in (sx, sy, sz))
        # 頂点ごとに Python で戻していた値を、同じ式・同じ順でまとめて求める（2026-11-20。結果は同じ）。
        pos_array = _vertex_array(blobs, vb_by_id, mesh, position, minimum, count)
        if pos_array is not None:
            if position.fmt == 13:
                raw4 = _snorm16_array(pos_array)
                if use_scale:
                    base_positions = raw4[:, :3] * np.array((sx, sy, sz)) + np.array((tx, ty, tz))
                else:
                    base_positions = np.ascontiguousarray(raw4[:, :3])
                pos_w = np.ascontiguousarray(raw4[:, 3])
            else:
                base_positions = pos_array.astype(np.float64)
                pos_w = np.ones(count, dtype=np.float64)
        else:
            pos_views = _read_vertex_components(blobs, vb_by_id, mesh, position, minimum, count)
            base_positions = np.empty((count, 3), dtype=np.float64)
            pos_w = np.ones(count, dtype=np.float64)
            for row, view in enumerate(pos_views):
                if position.fmt == 13:
                    x, y, z, w = struct.unpack_from("<hhhh", view, 0)
                    raw = (_snorm16(x), _snorm16(y), _snorm16(z))
                    base_positions[row] = (
                        raw[0] * sx + tx if use_scale else raw[0],
                        raw[1] * sy + ty if use_scale else raw[1],
                        raw[2] * sz + tz if use_scale else raw[2],
                    )
                    pos_w[row] = _snorm16(w)
                else:
                    base_positions[row] = struct.unpack_from("<fff", view, 0)
        base_normals: np.ndarray | None = None
        if normal is not None and normal.fmt in {10, 37}:
            normal_array = _vertex_array(blobs, vb_by_id, mesh, normal, minimum, count)
            if normal_array is not None and _row_dots_match():
                values = np.empty((count, 3), dtype=np.float64)
                if normal.fmt == 37:
                    values[:, 0] = pos_w
                    values[:, 1:] = _snorm16_array(normal_array)
                else:
                    values[:] = normal_array.astype(np.float64)
                # np.linalg.norm(value) は sqrt(value.dot(value))。各行の dot は matmul で同じ関数（BLAS の ddot）を通す。
                lengths = np.sqrt(_row_dots(values))
                with np.errstate(divide="ignore", invalid="ignore"):
                    normalized = values / lengths[:, None]
                base_normals = np.where((lengths > 1e-12)[:, None], normalized, np.array((1.0, 0.0, 0.0)))
            else:
                normal_views = _read_vertex_components(blobs, vb_by_id, mesh, normal, minimum, count)
                base_normals = np.empty((count, 3), dtype=np.float64)
                for row, view in enumerate(normal_views):
                    if normal.fmt == 37:
                        ny, nz = struct.unpack_from("<hh", view, 0)
                        value = np.asarray((pos_w[row], _snorm16(ny), _snorm16(nz)), dtype=np.float64)
                    else:
                        value = np.asarray((_half(view, 0), _half(view, 2), _half(view, 4)), dtype=np.float64)
                    length = float(np.linalg.norm(value))
                    base_normals[row] = value / length if length > 1e-12 else (1.0, 0.0, 0.0)
        morph = morph_by_id.get(mesh.morph_buffer_index)
        if morph is None and 0 <= mesh.morph_buffer_index < len(parsed_morphs):
            morph = parsed_morphs[mesh.morph_buffer_index]
        if morph is None:
            continue
        p0, p1, n0, n1 = _selector_delta_records(morph, mesh, minimum, count)
        output.append(
            _MorphGeometry(
                name=mesh.name,
                vertex_count=count,
                triangle_count=mesh.index_count // 3,
                source_mesh_offset=int(mesh.blob.offset),
                source_clean_indices=source_clean_indices,
                bucket_flags=mesh.bucket_flags,
                material_id=mesh.material_id,
                material_name=str(material_name_by_id.get(mesh.material_id) or ""),
                base_positions=base_positions,
                base_normals=base_normals,
                diameter_position_delta=p0,
                width_position_delta=p1,
                diameter_normal_delta=n0 if base_normals is not None else None,
                width_normal_delta=n1 if base_normals is not None else None,
            )
        )
    return output



def _wheel_material_instances_by_identifier(blobs: list[_Blob]) -> dict[int, _Blob]:
    """Use only MatI namespaced identifiers; vertex/index buffers reuse small IDs.

    同じ識別番号のVerB等が後続しても原本MatIを上書きさせない。
    同一IDで異なるMatIが重複するときは安全停止する。
    """
    instances: dict[int, _Blob] = {}
    for blob in blobs:
        if blob.tag != 0x4D617449 or blob.identifier is None:
            continue
        key = int(blob.identifier)
        previous = instances.get(key)
        if previous is not None:
            if previous.name != blob.name or bytes(previous.data) != bytes(blob.data):
                raise WheelMorphInternalError(f"conflicting WheelStyle MatI identifier {key}")
            continue
        instances[key] = blob
    return instances


def wheelstyle_material_bindings(payload: bytes) -> list[dict[str, Any]]:
    """ローカルWheelStyle ModelBinから原本Material識別の根拠を取得する。
FH6 MeshBlob v1.9以降はGroupごとにMaterial IDを4つ格納し、要素[1]を主Bindingとする。
参照製品と同じIdentifierMetadata／NameMetadataで解決する。
PBRの推測やViewer材質の変更はしない。
    """

    blobs = _parse_blobs(payload)
    by_identifier = _wheel_material_instances_by_identifier(blobs)
    rows: list[dict[str, Any]] = []
    for blob in blobs:
        if blob.tag != _TAG_MESH:
            continue
        mesh = _parse_mesh(blob)
        material_blob = by_identifier.get(mesh.material_id)
        nested_names: list[str] = []
        nested_tags: list[str] = []
        if material_blob is not None and len(material_blob.data) >= 4:
            try:
                nested = _parse_blobs(bytes(material_blob.data))
            except WheelMorphInternalError:
                nested = []
            for child in nested:
                if child.name and child.name not in nested_names:
                    nested_names.append(child.name)
                tag = f"0x{int(child.tag):08X}"
                if tag not in nested_tags:
                    nested_tags.append(tag)
        rows.append({
            "mesh_name": mesh.name,
            "bucket_flags": int(mesh.bucket_flags),
            "bucket_flags_hex": f"0x{int(mesh.bucket_flags):04X}",
            "material_groups": [list(group) for group in mesh.material_groups],
            "material_id": int(mesh.material_id),
            "material_name": str(material_blob.name if material_blob is not None else ""),
            "material_blob_tag_hex": f"0x{int(material_blob.tag):08X}" if material_blob is not None else "",
            "material_nested_names": nested_names,
            "material_nested_tags": nested_tags,
        })
    return rows


def wheelstyle_material_payloads(payload: bytes) -> list[dict[str, Any]]:
    """Meshが実際に参照するWheelStyleのMaterial Instanceを取得する。
MeshBlob.material_idから到達可能なBlobだけを返す。
原本バイトはメモリ内の診断用とし、保存・配布しない。
未対応Bindingはwheelstyle_material_bindingsで報告し、再解釈せず除外する。
    """
    blobs = _parse_blobs(payload)
    by_identifier = _wheel_material_instances_by_identifier(blobs)
    referenced: list[int] = []
    for blob in blobs:
        if blob.tag != _TAG_MESH:
            continue
        material_id = int(_parse_mesh(blob).material_id)
        if material_id >= 0 and material_id not in referenced:
            referenced.append(material_id)

    rows: list[dict[str, Any]] = []
    for material_id in referenced:
        blob = by_identifier.get(material_id)
        if blob is None or int(blob.tag) != 0x4D617449:  # MatI / MaterialInstance
            continue
        rows.append({
            "material_id": int(material_id),
            "material_name": str(blob.name or ""),
            "material_blob_tag_hex": f"0x{int(blob.tag):08X}",
            "payload": bytes(blob.data),
        })
    return rows

def morph_inputs_from_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    """GameDBのAssembly契約からWheelStyle Rim係数を取得する。
現在の輪別寸法はwheel_dimensionsに格納される。
旧研究Fixtureのfront_*／rear_*平坦キーは研究用の互換入力として残す。
    """

    def axle(prefix: str) -> dict[str, float]:
        dimensions = assembly.get("wheel_dimensions")
        per_wheel = None
        if isinstance(dimensions, dict):
            candidate = dimensions.get(f"{prefix}_left")
            if isinstance(candidate, dict):
                per_wheel = candidate

        try:
            if per_wheel is not None:
                diameter = float(per_wheel["wheel_diameter_in"])
                if "tire_width_mm" in per_wheel:
                    width = float(per_wheel["tire_width_mm"])
                else:
                    width = float(per_wheel["tire_width"]) * 1000.0
            else:
                diameter = float(assembly[f"{prefix}_wheel_diameter_in"])
                width = float(assembly[f"{prefix}_tire_width_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WheelMorphInternalError(
                f"{prefix} WheelStyle morph dimensions are missing from the GameDB assembly contract"
            ) from exc

        values = {
            "wheel_diameter_in": diameter,
            "tire_width_mm": width,
            "diameter_weight": (diameter - 10.0) / 14.0,
            "width_weight": (1.0 - width / 1000.0) / 0.9,
        }
        if not all(math.isfinite(value) for value in values.values()):
            raise WheelMorphInternalError(f"{prefix} WheelStyle morph inputs are not finite")
        return values

    return {"front": axle("front"), "rear": axle("rear")}


# Carbin の 4 輪の中心の高さがすべて 0（未設定）の車（HOL_HSVGTS_14 等）は、GameDB の高さを使う。
# 前後・左右の差は安全上限以内、高さの差は 4 輪でそろい、この値以内のときだけ。
CARBIN_UNSET_HEIGHT_EPSILON_M = 1e-4
WHEEL_GAMEDB_PLACEMENT_MAX_UNSET_HEIGHT_SHIFT_M = 0.40
CARBIN_UNSET_HEIGHT_SPREAD_M = 0.05


def _carbin_unset_height_shift(per_wheel: dict[str, Any]) -> bool:
    """Carbin の車輪の高さが未設定（4 輪とも 0）で、GameDB との差が高さだけなら True。

    2026-11-18 の全車体の撮影で、HOL_HSVGTS_14 の Carbin の 4 輪の高さが 0.0 で、GameDB の 0.212 m との差が
    安全上限（0.15 m）を超え、車輪が車体から 21 cm 下に離れていた（前後・左右の差は 2 cm 以内）。
    高さが実際に設定されている車（MIN_XRaidCountryman_13 等、GameDB より Carbin が正しい）は対象外。
    """
    if len(per_wheel) != 4:
        return False
    lifts = []
    for row in per_wheel.values():
        source = row.get("wheelstyle_instance_translation_glb") or []
        delta = row.get("translation_glb") or []
        if len(source) != 3 or len(delta) != 3:
            return False
        if abs(float(source[1])) > CARBIN_UNSET_HEIGHT_EPSILON_M:
            return False
        if max(abs(float(delta[0])), abs(float(delta[2]))) > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M:
            return False
        lifts.append(float(delta[1]))
    return (min(lifts) > 0.0 and max(lifts) <= WHEEL_GAMEDB_PLACEMENT_MAX_UNSET_HEIGHT_SHIFT_M
            and max(lifts) - min(lifts) <= CARBIN_UNSET_HEIGHT_SPREAD_M)


SINGLE_AXLE_CENTER_MAX_X_M = 0.10
SINGLE_AXLE_CENTERING_MAX_SHIFT_X_M = 0.60


def _single_axle_centering_shift(per_wheel: dict[str, Any], present: tuple[str, ...]) -> bool:
    """3 輪の車で、1 輪の車軸の車輪を GameDB の車の中央へ動かす横の移動だけが安全上限を超えるとき True。

    2026-11-18：REL_SupervanIII_72 の前の 1 輪（骨 LF）は、Carbin では片側（X 約 0.43 m）にあり、GameDB の
    前の車幅 0.146 m（タイヤの幅 140 mm とほぼ同じ）では車の中央（X -0.003 m）になる。実車も前は中央の 1 輪。
    参照製品の 1 つも「Carbin の車輪の X・Y は仮の値の車がある」として GameDB の値を使う。
    1 輪の車軸の目標が中央（|X| ≤ 0.10 m）、横の移動が 0.60 m 以内、上下・前後は安全上限以内で、
    ほかの車輪の移動はすべて安全上限以内のときだけ。
    """
    if len(present) != 3:
        return False
    axles: dict[str, list[str]] = {}
    for wheel in present:
        axles.setdefault(wheel.split("_")[0], []).append(wheel)
    singles = [wheels[0] for wheels in axles.values() if len(wheels) == 1]
    if len(singles) != 1:
        return False
    for wheel in present:
        row = per_wheel.get(wheel)
        delta = row.get("translation_glb") if isinstance(row, dict) else None
        target = row.get("gamedb_target_center_glb") if isinstance(row, dict) else None
        if not isinstance(delta, list) or len(delta) != 3 or not isinstance(target, list) or len(target) != 3:
            return False
        if wheel == singles[0]:
            if (abs(float(target[0])) > SINGLE_AXLE_CENTER_MAX_X_M
                    or abs(float(delta[0])) > SINGLE_AXLE_CENTERING_MAX_SHIFT_X_M
                    or abs(float(delta[1])) > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M
                    or abs(float(delta[2])) > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M):
                return False
        elif float(np.linalg.norm(np.asarray(delta, dtype=np.float64))) > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M:
            return False
    return True


def _lateral_symmetric_track_shift(per_wheel: dict[str, Any]) -> bool:
    """carbin→GameDBの移動が、左右対称の純粋なトレッド幅の差（X方向）だけかを判定する。

    4輪とも上下（Y）・前後（Z）の成分が小さく、各車軸の左右でX成分が反対符号で同じ大きさ、
    Y/Zが同じであるときだけTrue。対応付けの誤り（前後や左右の取り違え）はこの形にならない。
    """
    axles = (("front_left", "front_right"), ("rear_left", "rear_right"))
    vectors = {}
    for left, right in axles:
        for wheel in (left, right):
            row = per_wheel.get(wheel)
            delta = row.get("translation_glb") if isinstance(row, dict) else None
            if not isinstance(delta, list) or len(delta) != 3:
                return False
            vector = np.asarray(delta, dtype=np.float64)
            if (not np.all(np.isfinite(vector))
                    or abs(vector[1]) > WHEEL_GAMEDB_PLACEMENT_LATERAL_MAX_Y_M
                    or abs(vector[2]) > WHEEL_GAMEDB_PLACEMENT_LATERAL_MAX_Z_M):
                return False
            vectors[wheel] = vector
        a, b = vectors[left], vectors[right]
        if (abs(a[0] + b[0]) > WHEEL_GAMEDB_PLACEMENT_LATERAL_SYMMETRY_M
                or abs(a[1] - b[1]) > WHEEL_GAMEDB_PLACEMENT_LATERAL_SYMMETRY_M
                or abs(a[2] - b[2]) > WHEEL_GAMEDB_PLACEMENT_LATERAL_SYMMETRY_M):
            return False
    return True


def cache_identity(
    *,
    car_body_id: int,
    database_size: int,
    database_mtime_ns: int,
    morph_inputs: dict[str, Any],
    wheel_centers: dict[str, Any] | None = None,
    wheel_placement: str = "gamedb",
) -> str:
    payload = json.dumps(
        {
            "implementation_revision": INTERNAL_WHEEL_MORPH_REVISION,
            "wheel_render_pass_filter_revision": WHEEL_RENDER_PASS_FILTER_REVISION,
            "wheel_gamedb_placement_revision": WHEEL_GAMEDB_PLACEMENT_REVISION,
            "wheel_placement": str(wheel_placement),
            "car_body_id": int(car_body_id),
            "database_size": int(database_size),
            "database_mtime_ns": int(database_mtime_ns),
            "morph_inputs": morph_inputs,
            "wheel_centers": wheel_centers or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _float32_from_hex_word(word: str) -> float:
    if not re.fullmatch(r"[0-9a-fA-F]{8}", word):
        raise ValueError(f"invalid float32 hex word: {word!r}")
    return float(struct.unpack(">f", bytes.fromhex(word))[0])


def _parse_carbin_instance_identity(identity: str) -> dict[str, Any] | None:
    """Converterが保全したCarbin Instance行列を復号する。
行列はRow Major順のFloat32 Hex 16要素。
診断フィールドが増えても対応できるよう、固定項目数を仮定せず末尾から行列を探す。
    """

    raw = str(identity or "").strip()
    if not raw:
        return None
    fields = raw.split("|")
    if len(fields) < 4:
        return None
    matrix_token = next((token for token in reversed(fields) if _IDENTITY_MATRIX_RE.fullmatch(token)), None)
    if matrix_token is None:
        return None
    try:
        matrix = [_float32_from_hex_word(word) for word in matrix_token.split(",")]
    except (ValueError, struct.error):
        return None
    if len(matrix) != 16 or not np.isfinite(np.asarray(matrix, dtype=np.float64)).all():
        return None
    bone = fields[1].strip() if len(fields) > 1 else ""
    suffix = _WHEEL_SUFFIX_RE.search(bone)
    wheel = _WHEEL_NAME_BY_SUFFIX.get(suffix.group(1).casefold()) if suffix else None
    return {
        "identity": raw,
        "attachment_bone": bone,
        "wheel": wheel,
        "matrix_row_major": matrix,
        "translation_fh6": np.asarray([matrix[12], matrix[13], matrix[14]], dtype=np.float64),
    }




def optimal_wheel_assignment(instances: dict[str, dict[str, Any]], assembly: dict[str, Any]) -> dict[str, str]:
    """原本WheelStyle識別ラベルを物理的なGameDBの4輪位置へ対応付ける。
Attachment Boneの輪位置ラベルだけが入れ替わる原本があるため、4!通りの一対一割当を比較し二乗距離最小を求める。
ラベル入替えを実変位と誤認しない決定的な処理である。
    """

    required = ("front_left", "front_right", "rear_left", "rear_right")
    centers = assembly.get("wheel_centers") if isinstance(assembly.get("wheel_centers"), dict) else {}
    sources: dict[str, np.ndarray] = {}
    targets: dict[str, np.ndarray] = {}
    for wheel in required:
        parsed = instances.get(wheel)
        raw_target = centers.get(wheel)
        if parsed is None or not isinstance(raw_target, (list, tuple)) or len(raw_target) != 3:
            raise WheelMorphInternalError(f"wheel placement evidence is incomplete for {wheel}")
        source = np.asarray(parsed.get("translation_fh6"), dtype=np.float64)
        try:
            target = np.asarray([float(value) for value in raw_target], dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise WheelMorphInternalError(f"GameDB wheel center for {wheel} is invalid") from exc
        if source.shape != (3,) or target.shape != (3,) or not np.isfinite(source).all() or not np.isfinite(target).all():
            raise WheelMorphInternalError(f"wheel placement contains a non-finite vector for {wheel}")
        sources[wheel] = source
        targets[wheel] = target

    best: tuple[float, tuple[str, ...]] | None = None
    for targets_for_sources in itertools.permutations(required):
        score = 0.0
        for source_wheel, target_wheel in zip(required, targets_for_sources):
            delta = targets[target_wheel] - sources[source_wheel]
            score += float(np.dot(delta, delta))
        candidate = (score, targets_for_sources)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise WheelMorphInternalError("wheel placement assignment could not be resolved")
    return {source_wheel: target_wheel for source_wheel, target_wheel in zip(required, best[1])}

def _placement_target_glb(assembly: dict[str, Any], wheel: str) -> np.ndarray | None:
    centers = assembly.get("wheel_centers") if isinstance(assembly.get("wheel_centers"), dict) else {}
    raw = centers.get(wheel)
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        target = np.asarray([float(raw[0]), float(raw[1]), float(raw[2])], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(target).all():
        return None
    # r232／r234の実原本照合により、ConverterはFH6のXを反転しY／Zを維持すると確認した。
    # 対応関係を明示して適用範囲を限定する。
    target[0] *= -1.0
    return target


def _apply_gamedb_wheel_placement(
    document: dict[str, Any],
    binary: bytearray,
    *,
    assembly: dict[str, Any],
) -> dict[str, Any]:
    """WheelStyleとBrakesをGameDBの検証済みWheel中心へ剛体配置する。
r239では稀なAttachment Boneラベル入替えを確認したため、r240は4輪の最小費用割当を先に行う。
1輪でも必要移動量が0.15mを超える場合、元のCarbin配置を維持する。
各輪の移動量を装着先Brakesと、同じ車輪のコントロールアーム（版 5 から。ゲームはホイールの位置から置く）と共有する。
    """

    centers = assembly.get("wheel_centers") if isinstance(assembly.get("wheel_centers"), dict) else {}
    required = ("front_left", "front_right", "rear_left", "rear_right")

    def no_apply(reason: str, *, identity_counts: dict[str, int] | None = None, assignment: dict[str, str] | None = None, max_distance: float = 0.0, excluded: dict[str, int] | None = None, guard_fallback: bool = False, carbin_centers: dict[str, list[float]] | None = None) -> dict[str, Any]:
        mapping = dict(assignment or {})
        return {
            # 安全上限でGameDBの移動をやめたとき、ホイールはcarbinの位置に残る。各車輪（GameDBの
            # 車輪名）のcarbinの車軸位置（FH6座標、契約のwheel_centersと同じ座標系）を残し、
            # Tire等の後段が実際のホイールと同じ車軸を使えるようにする。
            "wheel_gamedb_placement_guard_carbin_centers": dict(carbin_centers or {}),
            "wheel_gamedb_placement_revision": WHEEL_GAMEDB_PLACEMENT_REVISION,
            "wheel_gamedb_placement_applied": False,
            "wheel_gamedb_placement_reason": reason,
            "wheel_gamedb_placement_guard_threshold_m": WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M,
            "wheel_gamedb_placement_guard_fallback": bool(guard_fallback),
            "wheel_gamedb_placement_identity_counts": dict(identity_counts or {}),
            "wheel_gamedb_placement_identity_assignment": mapping,
            "wheel_gamedb_placement_identity_assignment_changed": any(source != target for source, target in mapping.items()),
            "wheel_gamedb_placement_wheels": 0,
            "wheel_gamedb_placement_meshes": 0,
            "wheel_gamedb_placement_vertices": 0,
            "wheel_gamedb_placement_part_types": {},
            "wheel_gamedb_placement_excluded_part_types": dict(sorted((excluded or {}).items())),
            "wheel_gamedb_placement_max_distance_m": float(max_distance),
            "wheel_gamedb_placement": {},
        }

    if not all(name in centers for name in required):
        return no_apply("assembly-has-no-four-wheel-centers")

    meshes = document.get("meshes") if isinstance(document.get("meshes"), list) else []
    wheelstyle_identities: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in required}
    parsed_by_mesh: dict[int, dict[str, Any]] = {}
    excluded_part_types: dict[str, int] = {}
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            continue
        extras = mesh.get("extras") if isinstance(mesh.get("extras"), dict) else {}
        parsed = _parse_carbin_instance_identity(str(extras.get("lo4_instance_identity") or ""))
        if parsed is None or (parsed.get("wheel") not in wheelstyle_identities
                              and parsed.get("wheel") not in MIDDLE_WHEEL_FOLLOWS):
            continue
        parsed_by_mesh[mesh_index] = parsed
        if parsed.get("wheel") in MIDDLE_WHEEL_FOLLOWS:
            continue
        part_type = str(extras.get("lo4_part_type") or "")
        folded = part_type.casefold()
        if folded == "wheelstyle":
            wheelstyle_identities[str(parsed["wheel"])][str(parsed["identity"])] = parsed
        elif _follows_wheel_placement(part_type, parsed) is None:
            label = part_type or "<unknown>"
            excluded_part_types[label] = excluded_part_types.get(label, 0) + 1

    identity_counts = {wheel: len(wheelstyle_identities[wheel]) for wheel in required}
    # 3 輪の車（REL_SupervanIII_72 は前が 1 輪で骨 LF、PEE_P50_62 は後ろが 1 輪で骨 LR）は角が 3 つ。
    # ある角だけで配置する（GameDB の車幅が狭く、1 輪の車軸の中心はほぼ車の中央になる）。
    # 同じ角の重複や、2 つ以上の欠けは従来どおり配置しない。
    present = tuple(wheel for wheel in required if identity_counts[wheel] == 1)
    if any(count > 1 for count in identity_counts.values()) or len(present) < 3:
        return no_apply(
            "exact-wheelstyle-identity-incomplete",
            identity_counts=identity_counts,
            excluded=excluded_part_types,
        )

    instances = {wheel: next(iter(wheelstyle_identities[wheel].values())) for wheel in present}
    assignment = (optimal_wheel_assignment(instances, assembly) if len(present) == len(required)
                  else {wheel: wheel for wheel in present})
    # 3 輪・6 輪の車は、前後（Z）を Carbin の位置のまま保つ。GameDB はホイールベースを車の原点の前後に
    # 等分して置くが、PEE_P50_62 は Carbin（前 0.534 m・後ろ -0.629 m）と GameDB（±0.635 m）で前輪が
    # 10 cm ずれ、車輪が車体の前に出ていた。参照製品の 1 つも「Carbin の Z は
    # ホイールベースと合う」として X・Y だけを GameDB に置き換える（参照のみ）。4 輪の車は変えない。
    keep_carbin_z = (len(present) < len(required)
                     or any(row.get("wheel") in MIDDLE_WHEEL_FOLLOWS for row in parsed_by_mesh.values()))
    target_to_source = {target: source for source, target in assignment.items()}
    if set(target_to_source) != set(present):
        raise WheelMorphInternalError("wheel placement assignment is not one-to-one")

    shifts_by_source: dict[str, np.ndarray] = {}
    per_wheel: dict[str, Any] = {}
    max_distance = 0.0
    for target_wheel in present:
        source_wheel = target_to_source[target_wheel]
        parsed = instances[source_wheel]
        target = _placement_target_glb(assembly, target_wheel)
        if target is None:
            raise WheelMorphInternalError(f"GameDB wheel center for {target_wheel} is invalid")
        source_fh6 = np.asarray(parsed["translation_fh6"], dtype=np.float64)
        source_glb = source_fh6.copy()
        source_glb[0] *= -1.0
        if keep_carbin_z:
            target = target.copy()
            target[2] = source_glb[2]
        delta = target - source_glb
        distance = float(np.linalg.norm(delta))
        if not math.isfinite(distance):
            raise WheelMorphInternalError(f"GameDB wheel placement shift for {target_wheel} is not finite")
        max_distance = max(max_distance, distance)
        shifts_by_source[source_wheel] = delta
        per_wheel[target_wheel] = {
            "carbin_identity_wheel": source_wheel,
            "carbin_attachment_bone": str(parsed.get("attachment_bone") or ""),
            "wheelstyle_instance_translation_glb": [float(value) for value in source_glb],
            "gamedb_target_center_glb": [float(value) for value in target],
            "translation_glb": [float(value) for value in delta],
            "distance_m": distance,
        }

    lateral_track_shift = False
    unset_height_shift = False
    single_axle_centering = False
    if max_distance > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M:
        lateral_track_shift = (max_distance <= WHEEL_GAMEDB_PLACEMENT_MAX_LATERAL_SHIFT_M
                               and _lateral_symmetric_track_shift(per_wheel))
        unset_height_shift = not lateral_track_shift and _carbin_unset_height_shift(per_wheel)
        single_axle_centering = (not lateral_track_shift and not unset_height_shift
                                 and _single_axle_centering_shift(per_wheel, present))
    if (max_distance > WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M and not lateral_track_shift
            and not unset_height_shift and not single_axle_centering):
        return no_apply(
            "max-shift-exceeds-validated-threshold",
            identity_counts=identity_counts,
            assignment=assignment,
            max_distance=max_distance,
            excluded=excluded_part_types,
            guard_fallback=True,
            carbin_centers={
                target_wheel: [float(value) for value in instances[target_to_source[target_wheel]]["translation_fh6"]]
                for target_wheel in present
            },
        )

    shifted_accessors: dict[int, np.ndarray] = {}
    shifted_meshes = 0
    shifted_vertices = 0
    part_type_meshes: dict[str, int] = {}
    part_type_vertices: dict[str, int] = {}
    # 中央の車輪は、同じ側の後輪と同じだけ動かす。
    for middle, rear in MIDDLE_WHEEL_FOLLOWS.items():
        if rear in target_to_source and target_to_source[rear] in shifts_by_source:
            shifts_by_source[middle] = shifts_by_source[target_to_source[rear]]
    source_wheel_meshes: dict[str, int] = {name: 0 for name in (*required, *MIDDLE_WHEEL_FOLLOWS)}
    source_wheel_vertices: dict[str, int] = {name: 0 for name in (*required, *MIDDLE_WHEEL_FOLLOWS)}
    for mesh_index, parsed in parsed_by_mesh.items():
        mesh = meshes[mesh_index]
        extras = mesh.get("extras") if isinstance(mesh.get("extras"), dict) else {}
        part_type = str(extras.get("lo4_part_type") or "")
        follow_label = _follows_wheel_placement(part_type, parsed)
        if follow_label is None:
            continue
        source_wheel = str(parsed.get("wheel") or "")
        delta = shifts_by_source.get(source_wheel)
        if delta is None:
            continue
        target_wheel = assignment.get(source_wheel, source_wheel)
        primitives = mesh.get("primitives") if isinstance(mesh.get("primitives"), list) else []
        mesh_vertices = 0
        changed = False
        for primitive in primitives:
            attrs = primitive.get("attributes") if isinstance(primitive, dict) and isinstance(primitive.get("attributes"), dict) else {}
            if "POSITION" not in attrs:
                continue
            accessor_index = int(attrs["POSITION"])
            previous = shifted_accessors.get(accessor_index)
            if previous is not None:
                if not np.allclose(previous, delta, atol=1e-12, rtol=0.0):
                    raise WheelMorphInternalError(
                        f"POSITION accessor {accessor_index} is shared across conflicting wheel placement shifts"
                    )
                continue
            positions = _accessor_array(
                document, binary, accessor_index, component_type=5126, value_type="VEC3"
            ).astype(np.float64, copy=True)
            _write_vec3(document, binary, accessor_index, positions + delta)
            shifted_accessors[accessor_index] = delta.copy()
            mesh_vertices += len(positions)
            shifted_vertices += len(positions)
            changed = True
        if not changed:
            continue
        shifted_meshes += 1
        source_wheel_meshes[source_wheel] += 1
        source_wheel_vertices[source_wheel] += mesh_vertices
        label = follow_label or "<unknown>"
        part_type_meshes[label] = part_type_meshes.get(label, 0) + 1
        part_type_vertices[label] = part_type_vertices.get(label, 0) + mesh_vertices
        mesh_extras = mesh.setdefault("extras", {})
        mesh_extras["lo4_wheel_gamedb_placement_revision"] = WHEEL_GAMEDB_PLACEMENT_REVISION
        mesh_extras["lo4_wheel_gamedb_placement_source"] = "local-fh6-gamedb"
        mesh_extras["lo4_wheel_gamedb_placement_source_wheel"] = source_wheel
        mesh_extras["lo4_wheel_gamedb_placement_wheel"] = target_wheel
        mesh_extras["lo4_wheel_gamedb_placement_translation_glb"] = [float(value) for value in delta]

    for target_wheel in present:
        source_wheel = target_to_source[target_wheel]
        if source_wheel_meshes[source_wheel] <= 0:
            raise WheelMorphInternalError(f"GameDB wheel placement shifted no WheelStyle/Brakes geometry for: {target_wheel}")
        per_wheel[target_wheel]["shifted_meshes"] = int(source_wheel_meshes[source_wheel])
        per_wheel[target_wheel]["shifted_vertices"] = int(source_wheel_vertices[source_wheel])

    return {
        "wheel_gamedb_placement_revision": WHEEL_GAMEDB_PLACEMENT_REVISION,
        "wheel_gamedb_placement_applied": True,
        "wheel_gamedb_placement_reason": ("applied-with-lateral-symmetric-track-shift" if lateral_track_shift
                                          else "applied-with-carbin-unset-height" if unset_height_shift
                                          else "applied-with-single-axle-centering" if single_axle_centering
                                          else "applied-with-validated-shift"),
        "wheel_gamedb_placement_single_axle_centering": bool(single_axle_centering),
        "wheel_gamedb_placement_carbin_z_kept": bool(keep_carbin_z),
        # 最終の車輪の中心（FH6 の座標、契約の wheel_centers と同じ）。3 輪・6 輪の車の契約に使う。
        "wheel_gamedb_placement_centers_fh6": {
            wheel: [-float(row["gamedb_target_center_glb"][0]), float(row["gamedb_target_center_glb"][1]),
                    float(row["gamedb_target_center_glb"][2])]
            for wheel, row in per_wheel.items()},
        "wheel_gamedb_placement_carbin_unset_height": bool(unset_height_shift),
        "wheel_gamedb_placement_guard_threshold_m": WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M,
        "wheel_gamedb_placement_lateral_track_shift": bool(lateral_track_shift),
        "wheel_gamedb_placement_guard_fallback": False,
        "wheel_gamedb_placement_source": "minimum-cost-exact-carbin-wheelstyle-instance-to-local-fh6-gamedb-center",
        "wheel_gamedb_placement_mode": "rigid-wheelstyle-brakes-and-control-arms",
        "wheel_gamedb_placement_identity_counts": identity_counts,
        "wheel_gamedb_placement_identity_assignment": assignment,
        "wheel_gamedb_placement_identity_assignment_changed": any(source != target for source, target in assignment.items()),
        "wheel_gamedb_placement_wheels": len(present) + sum(
            1 for middle in MIDDLE_WHEEL_FOLLOWS if source_wheel_meshes.get(middle, 0) > 0),
        "wheel_gamedb_placement_corners": list(present),
        "wheel_gamedb_placement_middle_wheels": [
            middle for middle in MIDDLE_WHEEL_FOLLOWS if source_wheel_meshes.get(middle, 0) > 0],
        "wheel_gamedb_placement_meshes": int(shifted_meshes),
        "wheel_gamedb_placement_vertices": int(shifted_vertices),
        "wheel_gamedb_placement_part_types": dict(sorted(part_type_meshes.items())),
        "wheel_gamedb_placement_part_type_vertices": dict(sorted(part_type_vertices.items())),
        "wheel_gamedb_placement_excluded_part_types": dict(sorted(excluded_part_types.items())),
        "wheel_gamedb_placement_max_distance_m": float(max_distance),
        "wheel_gamedb_placement": per_wheel,
    }


def _archive_entry(source_entry: str, model_code: str, names: dict[str, str]) -> str | None:
    normalized = str(source_entry or "").replace("\\", "/").lstrip("/")
    prefix = f"game:/media/cars/{model_code}/"
    if normalized.casefold().startswith(prefix.casefold()):
        normalized = normalized[len(prefix) :]
    exact = names.get(normalized.casefold())
    if exact:
        return exact
    suffix = "/" + normalized.casefold().lstrip("/")
    matches = [actual for folded, actual in names.items() if folded.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def _wheel_from_identity(identity: str) -> str | None:
    """既存の原本Carbin Bone/行列Decoderと同じ4輪識別を使う。

    Carbinはspindle以外にもaxleLF/wheelHubRR等のBone名を保存する。
    第一者source_wheel_identity_bridgeと同じ末尾Suffix検証を優先し、
    旧Converterが出すspindle名だけの履歴形式も維持する。
    4輪不明・曖昧なIdentityは推測で割り当てない。
    """
    parsed = _parse_carbin_instance_identity(identity)
    if parsed is not None:
        return parsed["wheel"]
    match = _WHEEL_BONE_RE.search(identity or "")
    if not match:
        return None
    return _WHEEL_NAME_BY_BONE.get(match.group(1).casefold())


def _axle_from_identity(identity: str) -> str | None:
    wheel = _wheel_from_identity(identity)
    if wheel is None:
        return None
    return "front" if wheel.startswith("front_") else "rear"


def _affine_fit(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float, float]:
    count = source.shape[0]
    if count != target.shape[0] or count < 4:
        raise WheelMorphInternalError("WheelStyle affine fit has incompatible vertex counts")
    sample_count = min(count, 512)
    sample = np.linspace(0, count - 1, sample_count, dtype=np.int64)
    design = np.concatenate((source[sample], np.ones((sample_count, 1), dtype=np.float64)), axis=1)
    matrix, *_ = np.linalg.lstsq(design, target[sample], rcond=None)
    predicted = np.concatenate((source, np.ones((count, 1), dtype=np.float64)), axis=1) @ matrix
    errors = np.linalg.norm(predicted - target, axis=1)
    return matrix, float(np.sqrt(np.mean(errors * errors))), float(errors.max(initial=0.0))


def _affine_errors(matrix: np.ndarray, source: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    predicted = np.concatenate((source, np.ones((len(source), 1), dtype=np.float64)), axis=1) @ matrix
    errors = np.linalg.norm(predicted - target, axis=1)
    return float(np.sqrt(np.mean(errors * errors))), float(errors.max(initial=0.0))


def _affine_source_degenerate(source: np.ndarray) -> bool:
    """原本の基準の位置が平面・直線・1 点か（アフィン変換のある方向の係数が決まらない）。"""
    if len(source) < 4:
        return True
    centred = source - source.mean(axis=0)
    singular = np.linalg.svd(centred, compute_uv=False)
    return bool(singular[-1] <= max(1e-9, singular[0] * 1e-6))


def _write_vec3(document: dict, binary: bytearray, accessor_index: int, values: np.ndarray) -> None:
    accessor = document["accessors"][int(accessor_index)]
    view = document["bufferViews"][int(accessor["bufferView"])]
    if int(accessor["componentType"]) != 5126 or accessor["type"] != "VEC3" or int(accessor["count"]) != len(values):
        raise WheelMorphInternalError("WheelStyle GLB accessor type changed unexpectedly")
    stride = int(view.get("byteStride") or 12)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    packed = np.asarray(values, dtype="<f4")
    if stride == 12:
        binary[start : start + len(values) * 12] = packed.tobytes()
    else:
        for row in range(len(values)):
            binary[start + row * stride : start + row * stride + 12] = packed[row].tobytes()
    accessor["min"] = [float(v) for v in packed.min(axis=0)]
    accessor["max"] = [float(v) for v in packed.max(axis=0)]


def _write_glb(path: Path, document: dict, binary: bytearray) -> None:
    # 既存Morph／描画処理にはメモリ内だけで互換名を渡す。新GLBにはLO4FH6キーのみ保存する。
    seal_firstparty_chassis_metadata(document)
    raw_json = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_json += b" " * ((-len(raw_json)) % 4)
    raw_bin = bytes(binary)
    raw_bin += b"\x00" * ((-len(raw_bin)) % 4)
    total = 12 + 8 + len(raw_json) + 8 + len(raw_bin)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    output += struct.pack("<II", len(raw_json), 0x4E4F534A) + raw_json
    output += struct.pack("<II", len(raw_bin), 0x004E4942) + raw_bin
    temporary = path.with_suffix(path.suffix + ".wheel-morph.tmp")
    temporary.write_bytes(output)
    temporary.replace(path)


def _is_original_shadow_only_wheel_geometry(candidate: _MorphGeometry) -> bool:
    """原本NORMAL欠落のShadow専用メッシュだけを識別。

    source_surface_stage.original_shadow_onlyと同じModelBin原本署名。
    Morph側のoffset/cleaned-index照合を通過した候補にだけ使用する。
    """
    return (
        candidate.name == "Shadow"
        and type(candidate.material_id) is int and candidate.material_id == -1
        and type(candidate.bucket_flags) is int
        and (candidate.bucket_flags & 0x08) != 0
        and (candidate.bucket_flags & 0x10) == 0
        and candidate.base_normals is None
    )


def _hide_wheelstyle_render_pass(
    document: dict[str, Any],
    mesh_index: int,
    mesh: dict[str, Any],
    *,
    filter_name: str,
) -> None:
    """GLB Indexを消さず、WheelStyleのStatic描画Passを1つ非表示にする。
監査のため幾何は残し、lo4_role=hiddenの理由と以前のRole／Sidesを保存する。
後の診断で表示状態を再構成できるようにする。
    """

    primitives = mesh.get("primitives") if isinstance(mesh.get("primitives"), list) else []
    if len(primitives) != 1:
        raise WheelMorphInternalError(
            f"WheelStyle render-pass mesh {mesh.get('name')!r} has {len(primitives)} primitives; "
            "cannot hide a render pass without suppressing unrelated geometry"
        )
    extras = mesh.setdefault("extras", {})
    if not isinstance(extras, dict):
        raise WheelMorphInternalError("WheelStyle mesh extras changed unexpectedly")
    previous_role = str(extras.get("lo4_role") or "")
    extras["lo4_wheel_render_pass_filter"] = str(filter_name)
    extras["lo4_wheel_render_pass_bucket_flags"] = int(extras.get("lo4_wheel_render_pass_bucket_flags") or 0)
    extras["lo4_wheel_render_pass_original_role"] = previous_role
    if "lo4_allowed_sides" in extras:
        extras["lo4_wheel_render_pass_original_allowed_sides"] = extras.get("lo4_allowed_sides")
        extras["lo4_allowed_sides"] = 0
    if "lo4_projection_sides" in extras:
        extras["lo4_wheel_render_pass_original_projection_sides"] = extras.get("lo4_projection_sides")
        extras["lo4_projection_sides"] = 0
    extras["lo4_role"] = "hidden"

    nodes = document.get("nodes") if isinstance(document.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict) or node.get("mesh") != mesh_index:
            continue
        node_extras = node.setdefault("extras", {})
        if not isinstance(node_extras, dict):
            raise WheelMorphInternalError("WheelStyle node extras changed unexpectedly")
        if "lo4_wheel_render_pass_original_role" not in node_extras:
            node_extras["lo4_wheel_render_pass_original_role"] = str(node_extras.get("lo4_role") or previous_role)
        node_extras["lo4_wheel_render_pass_filter"] = str(filter_name)
        if "lo4_allowed_sides" in node_extras:
            node_extras["lo4_wheel_render_pass_original_allowed_sides"] = node_extras.get("lo4_allowed_sides")
            node_extras["lo4_allowed_sides"] = 0
        if "lo4_projection_sides" in node_extras:
            node_extras["lo4_wheel_render_pass_original_projection_sides"] = node_extras.get("lo4_projection_sides")
            node_extras["lo4_projection_sides"] = 0
        node_extras["lo4_role"] = "hidden"


def _hide_wheelstyle_transparent_pass(document: dict[str, Any], mesh_index: int, mesh: dict[str, Any]) -> None:
    """Hide the FH6 rotating-wheel transparent/blur pass in static view."""

    _hide_wheelstyle_render_pass(
        document, mesh_index, mesh, filter_name="transparent-static-view"
    )


def _morph_geometry_candidates(
    geometries: list[_MorphGeometry],
    *,
    original_mesh_offset: object,
    original_mesh_name: str,
    display_mesh_name: str,
    vertex_count: int,
    triangle_count: int,
    glb_indices: np.ndarray | None,
) -> list[_MorphGeometry]:
    """原本ModelBin Meshのバイト位置を優先し、GLBの参照製品面整理を厳密照合。

    一部原本Meshは重複三角形を含み、ConverterのCleanTriangleIndices後は
    原本triangle_count != GLB triangle_countになる。件数の閾値を緩めず、
    source offset + cleaned index配列 + 頂点数の一致でだけ同一Meshと認める。
    旧出典にオフセットが無い場合は従来の頂点/三角形一致で安全停止を維持。
    """
    if original_mesh_offset is not None:
        if type(original_mesh_offset) is not int or original_mesh_offset < 0:
            raise WheelMorphInternalError(
                f"WheelStyle mesh {display_mesh_name!r} has invalid original ModelBin mesh offset"
            )
        selected = [item for item in geometries
                    if item.source_mesh_offset == original_mesh_offset]
        if len(selected) != 1:
            raise WheelMorphInternalError(
                f"WheelStyle mesh {display_mesh_name!r} has no unique original ModelBin mesh offset match"
            )
        candidate = selected[0]
        if (original_mesh_name and candidate.name.casefold() != original_mesh_name.casefold()
                or candidate.vertex_count != vertex_count
                or glb_indices is None
                or len(candidate.source_clean_indices) != len(glb_indices)
                or not np.array_equal(candidate.source_clean_indices, glb_indices)):
            raise WheelMorphInternalError(
                f"WheelStyle mesh {display_mesh_name!r} original ModelBin mesh index/vertex proof differs from GLB"
            )
        return selected

    # 過去に受け入れられたGLB形式を変更しない。正本でない推測や
    # 同じvertex_countだけのMorph対応は行わない。
    selected = [item for item in geometries
                if item.vertex_count == vertex_count and item.triangle_count == triangle_count]
    name = original_mesh_name or display_mesh_name.rsplit(" :: ", 1)[-1]
    named = [item for item in selected if item.name.casefold() == name.casefold()]
    return named or selected


def apply_wheelstyle_morph_to_glb(
    asset: VehicleAsset,
    glb_path: Path | str,
    *,
    assembly: dict[str, Any],
    car_body_id: int,
    wheel_placement: str = "gamedb",
    _converter_validation: dict[str, Any] | None = None,
    _final_validation_out: dict[str, Any] | None = None,
    _validation_reuse_status_out: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """変換済み車体GLBへローカルWheelStyle Morphを適用する。
各Primitiveに原本ModelBin、非Damage Morph Mesh、車軸、原本→GLBのアフィン対応が必要。
GameDBの4輪中心とCarbinの4つの一意な識別が揃えば、WheelStyleとBrakesを輪別に剛体移動する。
不完全な識別証拠では配置を変更しない。
    """

    path = Path(glb_path).resolve()
    # 直前のConverter呼出しで同一GLBが厳密検証済みの場合がある。
    # その検証結果と実ファイル同一性が一致するときだけ再検証を省略する。
    # 直接呼出しや欠落・古い記録の場合は必ず検証する。
    prevalidated = False
    if isinstance(_converter_validation, dict):
        evidence = _converter_validation.get("validated_glb")
        identity = _converter_validation.get("validated_glb_file_identity")
        required = (
            "mesh_count", "paint_meshes", "glass_meshes", "triangle_count",
            "direct_uv3_meshes", "projected_livery_meshes", "part_option_count",
        )
        if (
            isinstance(evidence, dict)
            and all(type(evidence.get(key)) is int and evidence[key] >= 0 for key in required)
            and evidence["mesh_count"] > 0
            and evidence["paint_meshes"] > 0
            and isinstance(identity, dict)
        ):
            try:
                stat = path.stat()
                current_identity = {
                    "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                    "inode": int(stat.st_ino),
                    "device": int(stat.st_dev),
                }
                prevalidated = current_identity == identity
            except OSError:
                prevalidated = False
    if not prevalidated:
        validate_local_chassis_glb(path)
    if _validation_reuse_status_out is not None:
        _validation_reuse_status_out["input_validation_reused"] = prevalidated
    document, binary_bytes = _glb_payloads(path)
    binary = bytearray(binary_bytes)
    inputs = morph_inputs_from_assembly(assembly)
    meshes = document.get("meshes") if isinstance(document.get("meshes"), list) else []
    targets: list[tuple[int, dict, dict, dict]] = []
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            continue
        extras = mesh.get("extras") if isinstance(mesh.get("extras"), dict) else {}
        if str(extras.get("lo4_part_type") or "").casefold() != "wheelstyle":
            continue
        primitives = mesh.get("primitives") if isinstance(mesh.get("primitives"), list) else []
        for primitive in primitives:
            attrs = primitive.get("attributes") if isinstance(primitive, dict) and isinstance(primitive.get("attributes"), dict) else {}
            if "POSITION" in attrs:
                targets.append((mesh_index, mesh, extras, primitive))
    if not targets:
        raise WheelMorphInternalError("converted chassis exposes no WheelStyle geometry")

    # 前後Morph係数を選ぶ前に、稀なAttachment Bone輪ラベルの入替えを解決する。
    # r239では正確な4輪行列とLF／RF／LR／RRラベルが異なるStock原本を3台確認した。
    # 一意な4識別とGameDBの4中心が揃えば配置段階と同じ最小費用割当を使い、そうでなければ従来のラベル規則を維持する。
    morph_identity_buckets: dict[str, dict[str, dict[str, Any]]] = {
        wheel: {} for wheel in ("front_left", "front_right", "rear_left", "rear_right")
    }
    for _mesh_index, _mesh, extras, _primitive in targets:
        parsed = _parse_carbin_instance_identity(str(extras.get("lo4_instance_identity") or ""))
        if parsed is None or parsed.get("wheel") not in morph_identity_buckets:
            continue
        morph_identity_buckets[str(parsed["wheel"])][str(parsed["identity"])] = parsed
    morph_identity_counts = {wheel: len(items) for wheel, items in morph_identity_buckets.items()}
    morph_assignment = {wheel: wheel for wheel in morph_identity_buckets}
    centers = assembly.get("wheel_centers") if isinstance(assembly.get("wheel_centers"), dict) else {}
    if all(count == 1 for count in morph_identity_counts.values()) and all(wheel in centers for wheel in morph_identity_buckets):
        morph_instances = {wheel: next(iter(items.values())) for wheel, items in morph_identity_buckets.items()}
        morph_assignment = optimal_wheel_assignment(morph_instances, assembly)
    morph_assignment_changed = any(source != target for source, target in morph_assignment.items())

    model_cache: dict[str, list[_MorphGeometry]] = {}
    applied_meshes = 0
    applied_vertices = 0
    normal_meshes = 0
    filtered_transparent_meshes = 0
    filtered_transparent_vertices = 0
    filtered_original_shadow_meshes = 0
    filtered_original_shadow_vertices = 0
    max_fit_error = 0.0
    degenerate_reference_meshes = 0
    matches: list[dict[str, Any]] = []
    with zipfile.ZipFile(asset.archive_path) as archive:
        names = {name.replace("\\", "/").casefold(): name.replace("\\", "/") for name in archive.namelist()}
        fit_cache: dict[tuple[int, int], tuple[Any, ...]] = {}

        def fit_target(item: tuple[int, dict, dict, dict]) -> tuple[Any, ...]:
            """原本の形の候補を選び、原本の基準の位置→GLB の位置のアフィン変換を当てはめる（結果を覚える）。"""
            mesh_index, mesh, extras, primitive = item
            cache_key = (mesh_index, id(primitive))
            if cache_key in fit_cache:
                return fit_cache[cache_key]
            source_entry = _archive_entry(str(extras.get("lo4_source_entry") or ""), asset.model_code, names)
            identity = str(extras.get("lo4_instance_identity") or "")
            identity_wheel = _wheel_from_identity(identity)
            wheel = morph_assignment.get(identity_wheel, identity_wheel) if identity_wheel else None
            axle = ("front" if str(wheel).startswith("front_") else "rear") if wheel else None
            if not source_entry or not axle or not wheel or not identity_wheel:
                raise WheelMorphInternalError(
                    f"WheelStyle mesh {mesh.get('name')!r} lost source/axle identity required for independent morphing"
                )
            if source_entry not in model_cache:
                model_cache[source_entry] = _extract_morph_geometries(archive.read(source_entry))
            attrs = primitive["attributes"]
            baseline = _accessor_array(document, binary, attrs["POSITION"], component_type=5126, value_type="VEC3").astype(np.float64, copy=True)
            triangle_count = 0
            if primitive.get("indices") is not None:
                triangle_count = int(document["accessors"][int(primitive["indices"])].get("count") or 0) // 3
            mesh_name = str(mesh.get("name") or "")
            original_mesh_offset = extras.get("lo4fh6_original_source_mesh_offset")
            glb_indices = None
            if original_mesh_offset is not None:
                # 厳密な原本offset証拠があるGLBのみ、指数配列を読んで面整理を照合。
                idx_ref = primitive.get("indices")
                if idx_ref is None:
                    raise WheelMorphInternalError(
                        f"WheelStyle mesh {mesh_name!r} lacks original indexed geometry"
                    )
                component_type = int(document["accessors"][int(idx_ref)]["componentType"])
                if component_type not in (5123, 5125):
                    raise WheelMorphInternalError(
                        f"WheelStyle mesh {mesh_name!r} has unsupported GLB index type"
                    )
                glb_indices = _accessor_array(
                    document, binary, idx_ref, component_type=component_type, value_type="SCALAR"
                ).astype(np.int64, copy=False)
            candidates = _morph_geometry_candidates(
                model_cache[source_entry],
                original_mesh_offset=original_mesh_offset,
                original_mesh_name=str(extras.get("lo4fh6_source_mesh_name") or ""),
                display_mesh_name=mesh_name,
                vertex_count=len(baseline),
                triangle_count=triangle_count,
                glb_indices=glb_indices,
            )
            if not candidates:
                raise WheelMorphInternalError(
                    f"WheelStyle mesh {mesh_name!r} has no matching non-damage morph geometry in {source_entry}"
                )
            scored: list[tuple[float, float, np.ndarray, _MorphGeometry]] = []
            for candidate in candidates:
                affine, rms, maximum = _affine_fit(candidate.base_positions, baseline)
                scored.append((rms, maximum, affine, candidate))
            rms, maximum, affine, candidate = min(scored, key=lambda row: (row[0], row[1]))
            result = (source_entry, identity, identity_wheel, wheel, axle, baseline, mesh_name,
                      rms, maximum, affine, candidate)
            fit_cache[cache_key] = result
            return result

        def instance_affine(identity: str) -> np.ndarray | None:
            """同じホイールの配置（同じ Carbin の記録）で、形が平面・直線でないメッシュの当てはめ（誤差が最小のもの）。"""
            best = None
            for item in targets:
                if str(item[2].get("lo4_instance_identity") or "") != identity:
                    continue
                fit = fit_target(item)
                if _affine_source_degenerate(fit[10].base_positions):
                    continue
                if best is None or (fit[7], fit[8]) < (best[7], best[8]):
                    best = fit
            return None if best is None else best[9]

        for item in targets:
            mesh_index, mesh, extras, primitive = item
            attrs = primitive["attributes"]
            (source_entry, identity, identity_wheel, wheel, axle, baseline, mesh_name,
             rms, maximum, affine, candidate) = fit_target(item)
            if _affine_source_degenerate(candidate.base_positions):
                # 原本の基準の位置が平面・直線（例：FOR_Mustang_65 の wheel_dish_rearLip は 80 頂点がすべて X = 1.0）
                # だと、そのメッシュだけではその方向の係数が決まらず、最小ノルムの解で変形の移動が縮む。
                # 同じホイールの配置のメッシュは同じ変換で置かれるので、形の決まるメッシュの当てはめを使う。
                reference = instance_affine(identity)
                if reference is not None:
                    ref_rms, ref_max = _affine_errors(reference, candidate.base_positions, baseline)
                    if ref_rms <= 5e-4 and ref_max <= 2e-3:
                        affine, rms, maximum = reference, ref_rms, ref_max
                        degenerate_reference_meshes += 1
            mesh_extras = mesh.setdefault("extras", {})
            primitive_extras = primitive.setdefault("extras", {})
            # WheelStyle ModelBinのMaterial識別はPrimitive単位である。
            # 変換glTF Meshは複数のPrimitive／Materialを持ち得るため、Mesh単位だけでは後の情報で上書きされる。
            # 正確な識別をGLTFLoaderのgeometry.userDataへ渡るPrimitive側へ保全し、Mesh側は互換用とする。
            primitive_extras["lo4_wheel_material_id"] = int(candidate.material_id)
            primitive_extras["lo4_wheel_material_name"] = str(candidate.material_name or "")
            mesh_extras["lo4_wheel_material_id"] = int(candidate.material_id)
            mesh_extras["lo4_wheel_material_name"] = str(candidate.material_name or "")
            if rms > 5e-4 or maximum > 2e-3:
                raise WheelMorphInternalError(
                    f"WheelStyle source-to-GLB correspondence failed for {mesh_name!r}: rms={rms:.6g} max={maximum:.6g}"
                )
            if _is_original_shadow_only_wheel_geometry(candidate):
                # 原本で署名一致したShadowだけを非描画化。幾何や原本は削除しない。
                mesh_extras["lo4_wheel_render_pass_bucket_flags"] = int(candidate.bucket_flags)
                mesh_extras["lo4_wheel_render_pass_original_mesh_name"] = candidate.name
                _hide_wheelstyle_render_pass(
                    document, mesh_index, mesh, filter_name="original-shadow-only"
                )
                filtered_original_shadow_meshes += 1
                filtered_original_shadow_vertices += len(baseline)
                max_fit_error = max(max_fit_error, maximum)
                matches.append({
                    "mesh_index": mesh_index, "name": mesh_name,
                    "source_entry": source_entry, "identity_wheel": identity_wheel,
                    "wheel": wheel, "axle": axle,
                    "affine_translation_glb": [float(value) for value in affine[3]],
                    "vertex_count": len(baseline), "changed_vertices": 0,
                    "fit_rms": rms, "fit_max": maximum,
                    "bucket_flags": int(candidate.bucket_flags),
                    "render_pass_filtered": "original-shadow-only",
                    "normal_updated": False,
                })
                continue
            if candidate.bucket_flags & 0x04:
                mesh_extras = mesh.setdefault("extras", {})
                mesh_extras["lo4_wheel_render_pass_bucket_flags"] = int(candidate.bucket_flags)
                _hide_wheelstyle_transparent_pass(document, mesh_index, mesh)
                filtered_transparent_meshes += 1
                filtered_transparent_vertices += len(baseline)
                max_fit_error = max(max_fit_error, maximum)
                matches.append(
                    {
                        "mesh_index": mesh_index,
                        "name": mesh_name,
                        "source_entry": source_entry,
                        "identity_wheel": identity_wheel,
                        "wheel": wheel,
                        "axle": axle,
                        "affine_translation_glb": [float(value) for value in affine[3]],
                        "vertex_count": len(baseline),
                        "changed_vertices": 0,
                        "fit_rms": rms,
                        "fit_max": maximum,
                        "bucket_flags": int(candidate.bucket_flags),
                        "render_pass_filtered": "transparent-static-view",
                        "normal_updated": False,
                    }
                )
                continue
            weights = inputs[axle]
            morphed_local = (
                candidate.base_positions
                + candidate.diameter_position_delta * float(weights["diameter_weight"])
                + candidate.width_position_delta * float(weights["width_weight"])
            )
            design = np.concatenate((morphed_local, np.ones((len(morphed_local), 1), dtype=np.float64)), axis=1)
            morphed_glb = design @ affine
            changed = np.linalg.norm(morphed_glb - baseline, axis=1) > 1e-8
            changed_vertices = int(np.count_nonzero(changed))
            if changed_vertices <= 0:
                raise WheelMorphInternalError(f"WheelStyle morph produced no POSITION change for {mesh_name!r}")
            _write_vec3(document, binary, int(attrs["POSITION"]), morphed_glb)

            normal_updated = False
            if (
                "NORMAL" in attrs
                and candidate.base_normals is not None
                and candidate.diameter_normal_delta is not None
                and candidate.width_normal_delta is not None
            ):
                baseline_normals = _accessor_array(document, binary, attrs["NORMAL"], component_type=5126, value_type="VEC3").astype(np.float64, copy=True)
                normal_map, *_ = np.linalg.lstsq(candidate.base_normals, baseline_normals, rcond=None)
                predicted = candidate.base_normals @ normal_map
                lengths = np.linalg.norm(predicted, axis=1)
                good = lengths > 1e-12
                predicted[good] /= lengths[good, None]
                mean_dot = float(np.mean(np.sum(predicted * baseline_normals, axis=1)))
                if mean_dot >= 0.95:
                    morphed_normals = (
                        candidate.base_normals
                        + candidate.diameter_normal_delta * float(weights["diameter_weight"])
                        + candidate.width_normal_delta * float(weights["width_weight"])
                    )
                    source_lengths = np.linalg.norm(morphed_normals, axis=1)
                    valid = source_lengths > 1e-12
                    morphed_normals[valid] /= source_lengths[valid, None]
                    mapped = morphed_normals @ normal_map
                    mapped_lengths = np.linalg.norm(mapped, axis=1)
                    valid = mapped_lengths > 1e-12
                    mapped[valid] /= mapped_lengths[valid, None]
                    _write_vec3(document, binary, int(attrs["NORMAL"]), mapped)
                    normal_updated = True
                    normal_meshes += 1
            mesh_extras = mesh.setdefault("extras", {})
            primitive_extras = primitive.setdefault("extras", {})
            mesh_extras["lo4_wheel_morph_source"] = f"internal-modelbin-v{INTERNAL_WHEEL_MORPH_REVISION}"
            mesh_extras["lo4_wheel_morph_identity_wheel"] = identity_wheel
            mesh_extras["lo4_wheel_morph_wheel"] = wheel
            mesh_extras["lo4_wheel_morph_axle"] = axle
            mesh_extras["lo4_wheel_render_pass_bucket_flags"] = int(candidate.bucket_flags)
            primitive_extras["lo4_wheel_morph_source"] = f"internal-modelbin-v{INTERNAL_WHEEL_MORPH_REVISION}"
            primitive_extras["lo4_wheel_morph_identity_wheel"] = identity_wheel
            primitive_extras["lo4_wheel_morph_wheel"] = wheel
            primitive_extras["lo4_wheel_morph_axle"] = axle
            primitive_extras["lo4_wheel_render_pass_bucket_flags"] = int(candidate.bucket_flags)
            applied_meshes += 1
            applied_vertices += changed_vertices
            max_fit_error = max(max_fit_error, maximum)
            match_record = {
                "mesh_index": mesh_index,
                "name": mesh_name,
                "source_entry": source_entry,
                "identity_wheel": identity_wheel,
                "wheel": wheel,
                "axle": axle,
                "affine_translation_glb": [float(value) for value in affine[3]],
                "vertex_count": len(baseline),
                "changed_vertices": changed_vertices,
                "fit_rms": rms,
                "fit_max": maximum,
                "bucket_flags": int(candidate.bucket_flags),
                "render_pass_filtered": "",
                "normal_updated": normal_updated,
            }
            matches.append(match_record)

    # 2026-11-17：以前の「dense-static-face-occluder」判定（r245）は削除した。rim と rim2 は同じ原本材質
    # （ホイールの塗装やアルミ）の 2 つの部位で、投影面積の比率では本物のスポークを隠す車があった
    # （SUB_WRXSTi_05 の 10 本スポーク、ALF_4C_14 の丸穴の面、HON_S660_16 のスポーク面）。ゲームがどちらかを
    # 隠す根拠は見つかっていないため、両方を描く。
    placement_mode = str(wheel_placement or "gamedb").casefold()
    if placement_mode not in {"gamedb", "carbin"}:
        raise WheelMorphInternalError(f"Unsupported wheel placement mode: {wheel_placement!r}")
    if placement_mode == "gamedb":
        placement_report = _apply_gamedb_wheel_placement(document, binary, assembly=assembly)
    else:
        placement_report = {
            "wheel_gamedb_placement_revision": WHEEL_GAMEDB_PLACEMENT_REVISION,
            "wheel_gamedb_placement_applied": False,
            "wheel_gamedb_placement_reason": "disabled-by-request",
            "wheel_gamedb_placement_wheels": 0,
            "wheel_gamedb_placement_meshes": 0,
            "wheel_gamedb_placement_vertices": 0,
            "wheel_gamedb_placement_part_types": {},
            "wheel_gamedb_placement_max_distance_m": 0.0,
            "wheel_gamedb_placement": {},
        }
    # 表示しないメッシュ（隠した透明の面・影だけの面・変換で隠した面）は、描かないので最後の書き出しの前に除く
    # （glb_compact。2026-11-20）。報告のメッシュの番号は、除いた後の番号に付け替える（除いたものは None）。
    binary, compact = drop_hidden_meshes(document, binary)
    for match in matches:
        match["mesh_index"] = compact["mesh_map"].get(match["mesh_index"])
    _write_glb(path, document, binary)
    # 変更後GLBは採用前に必ず1回厳密検証する。
    # 呼出元はこの検証結果を再利用できるが、未検証データは外部へ出さない。
    final_validation = validate_local_chassis_glb(path)
    if _final_validation_out is not None:
        _final_validation_out.update(final_validation)
    return {
        "format": "lo4fh6_internal_wheel_morph_v1",
        "implementation_revision": INTERNAL_WHEEL_MORPH_REVISION,
        "wheel_render_pass_filter_revision": WHEEL_RENDER_PASS_FILTER_REVISION,
        "wheel_gamedb_placement_revision": WHEEL_GAMEDB_PLACEMENT_REVISION,
        "wheel_placement": placement_mode,
        "car_body_id": int(car_body_id),
        "morph_inputs": inputs,
        "wheel_morph_mode": "combined",
        "wheel_morph_source": "independent-local-modelbin",
        "wheel_morph_identity_counts": morph_identity_counts,
        "wheel_morph_identity_assignment": morph_assignment,
        "wheel_morph_identity_assignment_changed": morph_assignment_changed,
        "wheel_morph_applied_meshes": applied_meshes,
        "wheel_morph_applied_vertices": applied_vertices,
        "wheel_morph_normal_meshes": normal_meshes,
        "wheel_render_pass_filtered_meshes": filtered_transparent_meshes,
        "wheel_render_pass_filtered_vertices": filtered_transparent_vertices,
        "wheel_original_shadow_filtered_meshes": filtered_original_shadow_meshes,
        "wheel_original_shadow_filtered_vertices": filtered_original_shadow_vertices,
        "wheel_render_pass_filter": "wheelstyle-static-view-v4",
        "wheel_morph_max_affine_error": max_fit_error,
        "wheel_morph_degenerate_shape_reference_affine_meshes": int(degenerate_reference_meshes),
        **placement_report,
        "hidden_meshes_removed": int(compact["removed_meshes"]),
        "hidden_mesh_bytes_removed": int(compact["removed_bytes"]),
        "matches": matches,
    }
