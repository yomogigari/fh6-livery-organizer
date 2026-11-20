from __future__ import annotations

"""Build a compact, renderer-neutral vector stream from canonical FH6 livery data.

This is an independent research format for a future Viewer WebGL paint path. It does
not copy external implementations and does not contain FH6 asset bytes. Geometry is
referenced by FH6 shape word; the Viewer/runtime may resolve that geometry from the
user's local Vinyls cache.
"""

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fh_livery_preview_core.canonical import livery_to_surface_json

MAGIC = b"LO4GPVS1"
VERSION = 1
# 図形 1 つの記録（40 バイト）。_shape_record と同じ書式。
_RECORD = struct.Struct("<BBHI6f4B4x")
SECTION_NAMES = (
    "front", "back", "top", "left", "right", "wing",
    "front_windscreen", "rear_windscreen", "top_window", "left_window", "right_window",
)


def _rgba(shape: dict[str, Any]) -> tuple[int, int, int, int]:
    value = shape.get("color")
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return tuple(max(0, min(255, int(v))) for v in value[:4])  # type: ignore[return-value]
    if isinstance(value, str) and value.startswith("#") and len(value) in (7, 9):
        raw = value[1:]
        if len(raw) == 6:
            raw += "ff"
        return tuple(int(raw[i:i+2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]
    return (255, 255, 255, 255)


def _shape_word(shape: dict[str, Any]) -> int:
    for key in ("shape_word", "type_word", "type"):
        value = shape.get(key)
        if isinstance(value, int):
            return value & 0xFFFF
        if isinstance(value, str):
            try:
                return int(value, 0) & 0xFFFF
            except ValueError:
                pass
    return 0


def _validate_source_shape_for_product(shape: dict[str, Any], section: str) -> None:
    """原本色や形状IDの破損を白色代用・16bit丸めとして表示しない。"""
    color = shape.get("color")
    if isinstance(color, (list, tuple)):
        if (len(color) < 4 or any(
            isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 255
            for x in color[:4]
        )):
            raise ValueError(f"GPU製品図形の原本RGBAが不正です: {section}")
    elif isinstance(color, str):
        if (len(color) not in (7, 9) or not color.startswith("#") or
                any(ch not in "0123456789abcdefABCDEF" for ch in color[1:])):
            raise ValueError(f"GPU製品図形の原本RGBAが不正です: {section}")
    else:
        raise ValueError(f"GPU製品図形の原本RGBAが欠落しています: {section}")
    # canonicalにはtype_wordがあり、研究系shape_word/typeだけの入力も既存対応。
    for key in ("shape_word", "type_word", "type"):
        if key not in shape:
            continue
        value = shape[key]
        if isinstance(value, bool):
            break
        try:
            word = int(value, 0) if isinstance(value, str) else value
        except ValueError:
            break
        if isinstance(word, int) and 0 <= word <= 0xFFFF:
            return
        break
    raise ValueError(f"GPU製品図形の原本Shape IDが不正です: {section}")


def _shape_record(shape: dict[str, Any], section_index: int) -> bytes | None:
    data = list(shape.get("data") or [])
    if len(data) < 6:
        return None
    try:
        x, y, sx, sy, rotation, memory_skew = (float(v) for v in data[:6])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, sx, sy, rotation, memory_skew)):
        return None
    rgba = _rgba(shape)
    flags = 0
    if bool(shape.get("mask") or (len(data) >= 7 and data[6])):
        flags |= 0x01
    if bool(shape.get("is_raster_logo")):
        flags |= 0x02
    raster_id = int(shape.get("raster_id") or 0) if flags & 0x02 else 0
    # 40 bytes/placement: section, flags, shape id, raster id, affine source params, RGBA.
    return struct.pack(
        "<BBHI6f4B4x",
        section_index, flags, _shape_word(shape), raster_id,
        x, y, sx, sy, rotation, memory_skew,
        *rgba,
    )


def build_gpu_vector_stream_from_design(
    design: dict[str, Any],
    *,
    source_bytes: int | None = None,
    strict_complete: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    # 通常製品のGPU描画では、全11面の原本レイヤーを無告知で捨てない。
    # 既存研究用の部分Surface入力は strict_complete=False で互換保持する。
    surfaces = design.get("surfaces") or []
    if strict_complete:
        if not isinstance(surfaces, list) or len(surfaces) != len(SECTION_NAMES):
            raise ValueError("GPU製品入力の11面が欠損または重複しています")
        names = [s.get("name") if isinstance(s, dict) else None for s in surfaces]
        if (not all(isinstance(name, str) for name in names) or
                len(set(names)) != len(SECTION_NAMES) or set(names) != set(SECTION_NAMES)):
            raise ValueError("GPU製品入力の面名が不正または重複しています")
        if any(not isinstance(s.get("shapes"), list) for s in surfaces):
            raise ValueError("GPU製品入力の図形配列が不正です")
        count = sum(len(s["shapes"]) for s in surfaces)
        expected = design.get("shape_count")
        if expected is not None and (type(expected) is not int or expected != count):
            raise ValueError("GPU製品入力の原本図形件数が不一致です")
    by_name = {str(s.get("name") or ""): s for s in surfaces if isinstance(s, dict)}
    records: list[bytes] = []
    counts: dict[str, int] = {}
    masks = 0
    rasters = 0
    words: set[int] = set()
    pack = _RECORD.pack
    isfinite = math.isfinite
    for section_index, section in enumerate(SECTION_NAMES):
        surface = by_name.get(section) or {}
        count_before = len(records)
        for shape in surface.get("shapes") or []:
            # 近道：解読の部品が作る形の図形（色が 0〜255 の int 4 つ・data が有限の float 7 つ・図形番号が int）は、
            # 下の確かめ・_shape_record・_shape_word と同じ値を 1 回の流れで求める（2026-11-20。図形ごとに同じ値を
            # 2〜3 回ずつ求め直していた）。条件に合わなければ、下の今までの処理に任せる（例外とその文言も同じ）。
            if type(shape) is dict and "shape_word" not in shape:
                data = shape.get("data")
                color = shape.get("color")
                word = shape.get("type_word")
                if (type(data) is list and len(data) == 7 and type(color) is list and len(color) == 4
                        and type(word) is int and 0 <= word <= 0xFFFF):
                    x, y, sx, sy, rotation, skew, mask_value = data
                    red, green, blue, alpha = color
                    raster = bool(shape.get("is_raster_logo"))
                    raster_id = shape.get("raster_id")
                    if (type(x) is float and type(y) is float and type(sx) is float and type(sy) is float
                            and type(rotation) is float and type(skew) is float
                            and isfinite(x) and isfinite(y) and isfinite(sx) and isfinite(sy)
                            and isfinite(rotation) and isfinite(skew)
                            and type(red) is int and type(green) is int and type(blue) is int and type(alpha) is int
                            and 0 <= red <= 255 and 0 <= green <= 255 and 0 <= blue <= 255 and 0 <= alpha <= 255
                            and (not raster or (type(raster_id) is int and 0 < raster_id <= 0xffffffff))):
                        mask = bool(shape.get("mask") or mask_value)
                        flags = (0x01 if mask else 0) | (0x02 if raster else 0)
                        records.append(pack(section_index, flags, word, raster_id if raster else 0,
                                            x, y, sx, sy, rotation, skew, red, green, blue, alpha))
                        if word and not raster:
                            words.add(word)
                        if mask:
                            masks += 1
                        if raster:
                            rasters += 1
                        continue
            if not isinstance(shape, dict):
                if strict_complete:
                    raise ValueError(f"GPU製品入力の図形型が不正です: {section}")
                continue
            if strict_complete:
                _validate_source_shape_for_product(shape, section)
            if strict_complete and shape.get("is_raster_logo"):
                raster_id = shape.get("raster_id")
                if not isinstance(raster_id, int) or isinstance(raster_id, bool) or not 0 < raster_id <= 0xffffffff:
                    raise ValueError(f"GPU製品Raster Logoの原本IDが不正です: {section}")
            record = _shape_record(shape, section_index)
            if record is None:
                if strict_complete:
                    raise ValueError(f"GPU製品図形のアフィン値が不正です: {section}")
                continue
            records.append(record)
            # Raster LogoはDecals.zipの独立RGBA入力で描画する。
            # preview用shape_word(0x0065)をVinyls.zip必須ジオメトリに加えない。
            # これを要求すると正しいRaster画像だけのLiveryでも準備が失敗し得る。
            word = _shape_word(shape)
            if word and not bool(shape.get("is_raster_logo")):
                words.add(word)
            data = list(shape.get("data") or [])
            if bool(shape.get("mask") or (len(data) >= 7 and data[6])):
                masks += 1
            if bool(shape.get("is_raster_logo")):
                rasters += 1
        counts[section] = len(records) - count_before
    header = struct.pack("<8sIIII", MAGIC, VERSION, len(records), len(SECTION_NAMES), 40)
    payload = header + b"".join(records)
    summary = {
        "format": "lo4fh6_gpu_vector_stream_probe_v1",
        "read_only": True,
        "source_bytes": int(source_bytes) if source_bytes is not None else None,
        "canonical_shape_count": int(design.get("shape_count") or 0),
        "stream_record_count": len(records),
        "record_bytes": 40,
        "stream_bytes": len(payload),
        "section_counts": counts,
        "mask_record_count": masks,
        "raster_record_count": rasters,
        "unique_shape_word_count": len(words),
        "unique_shape_words": sorted(words),
        "architecture": {
            "intended_consumer": "Viewer WebGL offscreen paint texture",
            "geometry_policy": "shape words reference user-local FH6 Vinyls geometry; no FH6 geometry is embedded",
            "cache_policy": "content-addressed stream may replace multi-megabyte per-livery PNG atlas after GPU parity is proven",
            "renderer_changed": False,
        },
    }
    return payload, summary


def build_gpu_vector_stream(source: Path | str) -> tuple[bytes, dict[str, Any]]:
    source_path = Path(source)
    design = livery_to_surface_json(source_path, decoder="canonical")
    return build_gpu_vector_stream_from_design(design, source_bytes=source_path.stat().st_size)


def write_gpu_vector_stream(source: Path | str, output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payload, summary = build_gpu_vector_stream(source)
    (output / "livery-vector-stream.bin").write_bytes(payload)
    (output / "livery-vector-stream-probe.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
