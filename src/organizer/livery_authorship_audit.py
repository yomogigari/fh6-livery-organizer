"""Read-only FH6 C_livery authorship-audit heuristics used by Organizer.

This module evaluates structural signals that may indicate that a paint includes
algorithmically generated artwork.  It is an audit aid, not proof of authorship.
It deliberately never returns a positive "manual" classification.
"""
from __future__ import annotations

import collections
import math
import struct
from typing import Iterable, Sequence

CALIBRATION_ID = "lo4fh6-2026-09-provisional-v1"
AUDIT_RULES = (
    ("dominant_shape_ratio_ge_0_90", "dominant_shape_ratio", ">=", 0.90, "単一形状の占有率が90%以上"),
    ("shape_entropy_bits_le_1_0", "shape_entropy_bits", "<=", 1.0, "形状の多様性が1.0以下"),
    ("color_entropy_bits_ge_11_0", "color_entropy_bits", ">=", 11.0, "色の多様性が11.0以上"),
    ("dominant_color_ratio_le_0_05", "dominant_color_ratio", "<=", 0.05, "最多色の占有率が5%以下"),
    ("mantissa_low8_zero_ratio_ge_0_28", "mantissa_low8_zero_ratio", ">=", 0.28, "変形値の量子化傾向が28%以上"),
)
AUDIT_BAND_TEXT = {
    "automation-likely": "自動生成を含む可能性が高い",
    "review": "要確認",
    "inconclusive": "判定困難",
    "not-assessable": "判定材料不足",
}


class AuditError(RuntimeError):
    pass


def _reasonable_float(value: float) -> bool:
    return math.isfinite(value) and abs(value) <= 10_000_000.0


def _parse_shape_at(blob: bytes, offset: int, end: int):
    if offset + 32 <= end and blob[offset:offset + 2] in (b"\x00\x02", b"\x01\x02"):
        prefix_len = 2
    elif offset + 31 <= end and blob[offset:offset + 1] == b"\x02":
        if offset > 0 and blob[offset - 1] in (0x00, 0x01):
            return None
        prefix_len = 1
    else:
        return None

    payload_off = offset + prefix_len
    if payload_off + 30 > end:
        return None
    shape_id = struct.unpack_from("<H", blob, payload_off)[0]
    values = struct.unpack_from("<6f", blob, payload_off + 2)
    if not all(_reasonable_float(v) for v in values):
        return None
    for scale in (values[3], values[4]):
        if scale != 0.0 and abs(scale) < 1e-12:
            return None
    color = struct.unpack_from("<4B", blob, payload_off + 26)
    return int(shape_id), tuple(float(v) for v in values), tuple(int(v) for v in color), (32 if prefix_len == 2 else 31)


def _scan_records(decompressed: bytes, artwork_start: int, artwork_end: int):
    records = []
    offset = max(0, artwork_start)
    end = min(len(decompressed), artwork_end)
    while offset < end:
        parsed = _parse_shape_at(decompressed, offset, end)
        if parsed is None:
            offset += 1
            continue
        records.append(parsed[:3])
        offset += parsed[3]
    return records


def _entropy(values: Sequence[object]) -> float:
    if not values:
        return 0.0
    counter = collections.Counter(values)
    total = len(values)
    return -sum((count / total) * math.log2(count / total) for count in counter.values())


def _dominant_ratio(values: Sequence[object]) -> float:
    if not values:
        return 0.0
    return max(collections.Counter(values).values()) / len(values)


def _mantissa_low8_zero_ratio(values: Iterable[float]) -> float:
    hits = 0
    total = 0
    for value in values:
        if not math.isfinite(value) or value == 0.0:
            continue
        bits = struct.unpack("<I", struct.pack("<f", float(value)))[0]
        mantissa = bits & 0x7FFFFF
        total += 1
        if mantissa & 0xFF == 0:
            hits += 1
    return hits / total if total else 0.0


def _extract_features(records) -> dict[str, float | int]:
    if not records:
        return {
            "record_count": 0,
            "dominant_shape_ratio": 0.0,
            "shape_entropy_bits": 0.0,
            "color_entropy_bits": 0.0,
            "dominant_color_ratio": 0.0,
            "mantissa_low8_zero_ratio": 0.0,
        }
    shape_ids = [record[0] for record in records]
    transforms = [value for record in records for value in record[1]]
    colors = [record[2] for record in records]
    return {
        "record_count": len(records),
        "dominant_shape_ratio": round(_dominant_ratio(shape_ids), 6),
        "shape_entropy_bits": round(_entropy(shape_ids), 6),
        "color_entropy_bits": round(_entropy(colors), 6),
        "dominant_color_ratio": round(_dominant_ratio(colors), 6),
        "mantissa_low8_zero_ratio": round(_mantissa_low8_zero_ratio(transforms), 6),
    }


def _scan_quality(declared: int | None, recovered: int) -> tuple[str, float | None]:
    if declared is None or declared <= 0:
        return "unvalidated", None
    ratio = recovered / declared
    if ratio > 1.10:
        return "low", ratio
    if ratio >= 0.90:
        return "high", ratio
    if ratio >= 0.50:
        return "medium", ratio
    return "low", ratio


def _rule_details(features: dict[str, float | int]) -> tuple[list[str], list[str], list[dict[str, object]]]:
    matched: list[str] = []
    missed: list[str] = []
    details: list[dict[str, object]] = []
    for rule_id, feature_name, operator, threshold, label in AUDIT_RULES:
        raw = features.get(feature_name)
        number = float(raw) if isinstance(raw, (int, float)) and math.isfinite(float(raw)) else None
        ok = bool(number is not None and ((number >= threshold) if operator == ">=" else (number <= threshold)))
        (matched if ok else missed).append(rule_id)
        details.append({
            "id": rule_id,
            "label": label,
            "feature": feature_name,
            "operator": operator,
            "threshold": threshold,
            "value": number,
            "matched": ok,
        })
    return matched, missed, details


def empty_assessment(note: str = "監査に必要な解析情報がありません") -> dict[str, object]:
    return {
        "calibration": CALIBRATION_ID,
        "eligible": False,
        "score": None,
        "max_score": len(AUDIT_RULES),
        "band": "not-assessable",
        "display": AUDIT_BAND_TEXT["not-assessable"],
        "scan_quality": "unvalidated",
        "scan_ratio_vs_declared": None,
        "recovered_direct_records": 0,
        "matched_rules": [],
        "missed_rules": [item[0] for item in AUDIT_RULES],
        "rule_details": [],
        "features": _extract_features([]),
        "note": note,
    }


def assess_decompressed_c_livery(
    decompressed: bytes,
    *,
    gyvl_offset: int | None,
    counters_offset: int | None,
    section_counts: Sequence[int] | None,
) -> dict[str, object]:
    """Assess already-decompressed C_livery bytes without additional file I/O."""
    if gyvl_offset is None or counters_offset is None or section_counts is None:
        return empty_assessment("C_liveryのアートワーク範囲またはセクション数を検証できませんでした")
    artwork_start = gyvl_offset + 0x15
    if artwork_start > counters_offset:
        artwork_start = gyvl_offset + 4
    records = _scan_records(decompressed, artwork_start, counters_offset)
    features = _extract_features(records)
    declared = int(sum(section_counts))
    quality, ratio = _scan_quality(declared, len(records))
    matched, missed, details = _rule_details(features)
    eligible = quality in {"high", "medium"} and int(features.get("record_count") or 0) > 0
    if not eligible:
        band = "not-assessable"
        score = None
        note = "暫定監査スコアに必要な解析品質または復元レコード数が不足しています"
    else:
        score = len(matched)
        band = "automation-likely" if score >= 3 else ("review" if score == 2 else "inconclusive")
        note = "暫定的な構造監査シグナルです。制作方法を事実認定するものではありません"
    return {
        "calibration": CALIBRATION_ID,
        "eligible": eligible,
        "score": score,
        "max_score": len(AUDIT_RULES),
        "band": band,
        "display": AUDIT_BAND_TEXT[band],
        "scan_quality": quality,
        "scan_ratio_vs_declared": round(ratio, 6) if ratio is not None else None,
        "recovered_direct_records": len(records),
        "matched_rules": matched,
        "missed_rules": missed,
        "rule_details": details,
        "features": features,
        "note": note,
    }
