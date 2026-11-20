"""Independent fail-closed *absence-only* FH6 protected-group detection.

This is not an implementation of the protected-group wrapper grammar. A true
protected group or any uncertain grammar returns None, causing the caller to
use the previously working r485 inspection. No guessed privacy=false result.
"""
from __future__ import annotations
import struct
from .native_structure import decode_livery_structure, ParsedLivery
from .source_structure import read_section_envelope


# (lead & ~0x50) == 0x21 となる 1 バイト（0x50 のビットを除いて 0x21 と同じ）。
_PROTECTED_LEADS = tuple(bytes([value]) for value in range(256) if (value & ~0x50) == 0x21)


def _lead_outside_intervals(body: bytes, intervals: list[tuple[int, int]]) -> bool:
    """検証済みの区間（並べ済み・重なりなし）の外に、保護ラッパーの先頭のバイトがあるか。

    以前は本体を 1 バイトずつ Python で回していた（4212 で約 38 万回・1 件 約 0.1 秒）。区間の外（すき間）ごとに
    C の bytes.find で探す（同じ判定。2026-11-20）。長さ 0 の区間は何も覆わない。
    """
    position = 0
    for start, end in intervals:
        if start > position and any(body.find(lead, position, start) >= 0 for lead in _PROTECTED_LEADS):
            return True
        position = max(position, end)
    return position < len(body) and any(body.find(lead, position) >= 0 for lead in _PROTECTED_LEADS)


def inspect_absent_protected_groups(payload: bytes, *, parsed: ParsedLivery | None = None) -> dict | None:
    """Prove that no group-wrapper header signatures remain outside leaf records.

    This proof only establishes *absence*. Source ownership is the source header
    u32 field; no external decoder, license-controlled code, or car-specific rule.
    The structural parser must consume all eleven sections first.
    """
    if type(payload) is not bytes or len(payload) < 20 or payload[:4] != b'vlrc':
        return None
    try:
        tree = parsed if parsed is not None else decode_livery_structure(payload)
        env = read_section_envelope(payload)
        if tree.drawing_body_bytes != len(env.body) or tree.drawing_bytes_consumed < 0:
            return None
        shapes = [shape for section in tree.sections for shape in section.shapes]
        if len(shapes) != sum(env.section_counts):
            return None
        intervals = [(shape.source_offset, shape.source_offset + shape.byte_length) for shape in shapes]
        # Every group header, including its metadata and child bitmap, has
        # already been consumed by the independent structural grammar. A
        # protected wrapper lead on a *new* node boundary cannot be inside
        # one of these validated headers. Unparsed body bytes remain suspect.
        intervals += [(g.start, g.start + g.byte_length)
                      for section in tree.sections for g in section.groups]
        intervals.sort()
        if any(a < 0 or b > len(env.body) or (i and a < intervals[i-1][1]) for i,(a,b) in enumerate(intervals)):
            return None
        # The FH6 protected wrapper family uses a lead byte whose non-0x50
        # bits equal 0x21. Such a byte *inside a validated complete drawable*
        # is numeric/artwork data, not a group boundary. Anything elsewhere
        # requires the old verifier rather than inferring a negative.
        if _lead_outside_intervals(env.body, intervals):
            return None
        return {
            'source_owned': struct.unpack_from('<I', payload, 8)[0] != 1,
            'foreign_group_count': 0,
            'contains_foreign_groups': False,
            'protected_group_offsets': [],
        }
    except (ValueError, TypeError, IndexError, RecursionError, OverflowError, struct.error):
        return None
