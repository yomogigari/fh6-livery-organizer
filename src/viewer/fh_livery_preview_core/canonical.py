"""ペイント原本（C_livery）を、面（前・後・上・左右・窓・ウイング）ごとの図形の一覧にする入口。

解析は native_canonical_layers（独自実装）だけを使う。解析できない入力は推測で補わず、例外で止める。
出力の形式は SURFACE_DESIGN_FORMAT。図形 1 つの項目：
  type（0x100000＋図形番号。ラスター画像のロゴは 0x0065）、type_word、type_word_hex、data（変換値）、
  color（RGBA）、mask・mask_source・mask_group_depth・group_depth・record_mask_authoritative、
  source_offset・source_marker（原本内の位置）、is_raster_logo・raster_id、source_raw_type_word（原本の図形番号）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

SURFACE_DESIGN_FORMAT = "lo4fh6_surface_layers_v2"
RASTER_LOGO_WORD = 0x0065

# 原本の面の名前 → 出力の面の名前
SURFACE_NAMES = {
    "Front": "front",
    "Back": "back",
    "Top": "top",
    "Left": "left",
    "Right": "right",
    "Spoiler": "wing",
    "FrontWindshield": "front_windscreen",
    "BackWindshield": "rear_windscreen",
    "TopWindow": "top_window",
    "LeftWindow": "left_window",
    "RightWindow": "right_window",
}


class NativeOnlyDecoderError(ValueError):
    pass


def _shape_entry(layer: dict[str, Any]) -> tuple[dict[str, Any], bool, int | None]:
    """解析結果の 1 層を、出力の図形 1 つにする。（図形, ラスター画像か, ラスター番号）を返す。"""
    raw_word = int(layer.get("shape_id") or 0) & 0xFFFF
    raster = bool(layer.get("is_raster_logo"))
    word = RASTER_LOGO_WORD if raster else raw_word
    raster_id = int(layer.get("raster_id") or (raw_word & 0x7FFF)) if raster else None
    entry = {
        "type": 0x100000 + word,
        "type_word": word,
        "type_word_hex": f"0x{word:04x}",
        "data": [float(value) for value in list(layer.get("data") or [])],
        "color": [int(value) for value in list(layer.get("color_rgba") or [255, 255, 255, 255])],
        "mask": bool(layer.get("mask")),
        "mask_source": layer.get("mask_source", "none"),
        "mask_group_depth": int(layer.get("mask_group_depth") or 0),
        "group_depth": int(layer.get("group_depth") or 0),
        "record_mask_authoritative": bool(layer.get("record_mask_authoritative")),
        "source_offset": layer.get("source_offset"),
        "source_marker": layer.get("marker_hex"),
        "is_raster_logo": raster,
        "raster_id": raster_id,
        "source_raw_type_word": raw_word,
    }
    return entry, raster, raster_id


def build_surface_design(section_labels: tuple[str, ...] | list[str], payload: bytes,
                         layers: list[dict[str, Any]], report: dict[str, Any], *, decoder: str) -> dict[str, Any]:
    """解析した層を、面ごとの図形の一覧（SURFACE_DESIGN_FORMAT）にまとめる。

    原本の面に属さない層は含めない。面の並びは section_labels の順。
    """
    shapes_by_section: dict[str, list[dict[str, Any]]] = {label: [] for label in section_labels}
    raster_logos = 0
    raster_ids: set[int] = set()
    for layer in layers:
        section = str(layer.get("section") or "")
        if section not in shapes_by_section:
            continue
        entry, raster, raster_id = _shape_entry(layer)
        if raster:
            raster_logos += 1
            if raster_id:
                raster_ids.add(raster_id)
        shapes_by_section[section].append(entry)
    return surface_design_from_shapes(section_labels, payload, [shapes_by_section[label] for label in section_labels],
                                      len(layers), raster_logos, raster_ids, report, decoder=decoder)


def surface_design_from_shapes(section_labels: tuple[str, ...] | list[str], payload: bytes,
                               shapes_per_section: list[list[dict[str, Any]]], shape_count: int, raster_logos: int,
                               raster_ids: set[int], report: dict[str, Any], *, decoder: str) -> dict[str, Any]:
    """面ごとの図形の一覧（_shape_entry の形、section_labels の順）を、出力（SURFACE_DESIGN_FORMAT）にまとめる。

    build_surface_design と、自前の部品で解読する速い道（native_canonical_layers）の両方が使う（2026-11-20）。
    """
    surfaces = []
    for index, (label, shapes) in enumerate(zip(section_labels, shapes_per_section)):
        surfaces.append({
            "index": index,
            "name": SURFACE_NAMES[label],
            "source_section": label,
            "shape_count": len(shapes),
            "nested_group_count": None,
            "coordinate_space": "surface_local_unclipped",
            "requires_vehicle_mesh_clipping_for_final_preview": True,
            "shapes": shapes,
        })
    car_id = int.from_bytes(payload[0x10:0x14], "little") if len(payload) >= 0x14 else None
    return {
        "format": SURFACE_DESIGN_FORMAT,
        "source": "fh6_c_livery",
        "decoder": decoder,
        "decoder_report": report,
        "surface_count": len(surfaces),
        "shape_count": shape_count,
        "group_count": None,
        "raster_logo_count": raster_logos,
        "raster_ids": sorted(raster_ids),
        "car_id": car_id,
        "surfaces": surfaces,
        "preview_scope": "unclipped 2D surface-local geometry; final vehicle appearance requires car-specific mesh masks",
    }


def _require_native(decoder: str) -> None:
    if decoder == "canonical" and os.environ.get("LO4FH6_RM044_REFERENCE_RECOVERY") == "1":
        # 通常製品を旧描画・旧Stageへ環境変数で黙って後退させない。
        raise NativeOnlyDecoderError(
            "旧RM044_REFERENCE_RECOVERYは製品標準入口で使用できません。"
            "原本GroupMaskの未対応は現在の独立デコーダーで明示停止します"
        )
    if decoder not in {"canonical", "native"}:
        raise NativeOnlyDecoderError(f"unsupported decoder: {decoder}（独自の解析だけを使います）")


def livery_to_surface_json(path: Path, *, decoder: str = "canonical") -> dict[str, Any]:
    _require_native(decoder)
    from .native_canonical_layers import native_surface_json
    return native_surface_json(path)[0]


def livery_to_surface_json_with_privacy(path: Path, *, decoder: str = "canonical") -> tuple[dict[str, Any], dict[str, Any], dict[str, float]]:
    _require_native(decoder)
    from .native_canonical_layers import native_surface_json
    started = time.perf_counter()
    design, privacy = native_surface_json(path)
    elapsed = time.perf_counter() - started
    return design, privacy, {"structural_parse_seconds": elapsed,
                             "privacy_candidate_scan_seconds": 0.0, "total_seconds": elapsed}
