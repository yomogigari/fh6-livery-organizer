"""FH6 C_livery の図形レコードを読み取るプロジェクト側の独立実装。

既知の 31/32 バイト配置を、呼び出し側が確定した開始位置で解釈する。
セクション位置やグループ階層の探索、作者情報、マスク継承は扱わない。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass


MAX_BODY_BYTES = 128 * 1024 * 1024
# 0x02 は FH6 の描画レコード識別子。先頭の0x00/0x01は制御バイト。
DRAWABLE_TAG = 2
# 図形ごとに書式を解釈し直さないよう、作り置く（2026-11-20。値は struct.unpack_from と同じ）。
_WORD = struct.Struct('<H')
_TRANSFORM = struct.Struct('<6f')
_COLOR = struct.Struct('<4B')
_isfinite = math.isfinite


class LeafRecordError(ValueError):
    """未知の形式、破損、または不合理な図形配置を拒否する。"""


@dataclass(frozen=True)
class LeafRecord:
    offset: int
    byte_length: int
    wire_word: int
    position_x: float
    position_y: float
    scale_x: float
    scale_y: float
    rotation: float
    skew: float
    rgba: tuple[int, int, int, int]
    control_byte: int | None


def read_leaf_record(body: bytes, offset: int) -> LeafRecord:
    """既知の図形レコードだけを1件解釈する。開始オフセットは推測しない。"""
    if type(body) is not bytes:
        raise TypeError('body must be bytes')
    if type(offset) is not int or offset < 0:
        raise LeafRecordError('invalid leaf offset')
    if len(body) > MAX_BODY_BYTES:
        raise LeafRecordError('drawing body exceeds size budget')
    if offset >= len(body):
        raise LeafRecordError('leaf offset outside drawing body')
    # 31-byte bare leaf or 32-byte control-byte + leaf.
    if body[offset] == DRAWABLE_TAG:
        head = offset + 1
        size = 31
        control = None
    elif body[offset] in (0, 1) and offset + 1 < len(body) and body[offset + 1] == DRAWABLE_TAG:
        head = offset + 2
        size = 32
        control = body[offset]
    else:
        raise LeafRecordError('unsupported leaf marker')
    if offset + size > len(body):
        raise LeafRecordError('truncated leaf record')
    word = _WORD.unpack_from(body, head)[0]
    # A zero shape word cannot be a drawable; no vendor-specific identity table is consulted.
    if word == 0:
        raise LeafRecordError('zero shape word')
    rotation, x, y, sx, sy, skew = _TRANSFORM.unpack_from(body, head + 2)
    if not (_isfinite(rotation) and _isfinite(x) and _isfinite(y) and _isfinite(sx) and _isfinite(sy)
            and _isfinite(skew)):
        raise LeafRecordError('non-finite leaf transform')
    if not (-10000 <= rotation <= 10000 and abs(x) < 50000 and abs(y) < 50000
            and 0 < abs(sx) < 5000 and 0 < abs(sy) < 5000 and abs(skew) < 1000000):
        raise LeafRecordError('leaf transform outside supported range')
    b, g, r, a = _COLOR.unpack_from(body, head + 26)
    return LeafRecord(offset, size, word, x, y, sx, sy, rotation, skew, (r, g, b, a), control)


def reference_word_alias(raw: int) -> int:
    """比較専用：実測済みのゲーム上の2種類の旧番号を標準番号へ寄せる。"""
    return {0x07D0: 0x07D1, 0x0BB8: 0x0BB9}.get(raw, raw)


def check_decoded_placements(body: bytes, placements: list[dict]) -> dict[str, int | bool]:
    """既存デコーダーが指した各オフセットを独立読取し、基本属性だけを照合する。

    旧デコーダーにオフセット探索を委ねるため、この関数は独立した木パーサーではない。
    """
    if type(placements) is not list:
        raise TypeError('placements must be list')
    framed = bare = invalid = word_difference = color_difference = 0
    for placement in placements:
        offset = placement.get('source_offset')
        try:
            record = read_leaf_record(body, offset)
        except (TypeError, ValueError, IndexError, struct.error):
            invalid += 1
            continue
        if record.control_byte is None:
            bare += 1
        else:
            framed += 1
        if reference_word_alias(record.wire_word) != (int(placement['shape_id']) & 0xFFFF):
            word_difference += 1
        if list(record.rgba) != list(placement['color_rgba']):
            color_difference += 1
    return {
        'placements_checked': len(placements),
        'framed_32_byte_records': framed,
        'bare_31_byte_records': bare,
        'unreadable_records': invalid,
        'shape_word_mismatches': word_difference,
        'rgba_mismatches': color_difference,
        'all_fields_covered': framed + bare == len(placements),
        'matching_basic_fields': invalid == 0 and word_difference == 0 and color_difference == 0,
    }
