"""C_livery の外側構造だけを読み取る、依存のないプロジェクト実装。

対象: 展開済み vlrc から gyvl の描画領域と yrvl の 11 部位件数を特定する。
図形レコード、入れ子のグループ、マスク、作者情報は解析しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from struct import unpack_from

SECTION_LABELS = (
    'Front', 'Back', 'Top', 'Left', 'Right', 'Spoiler',
    'FrontWindshield', 'BackWindshield', 'TopWindow', 'LeftWindow', 'RightWindow',
)
MAX_STREAM_BYTES = 128 * 1024 * 1024
MARKER = b'gyvl'
COUNTER_MARKER = b'yrvl'
BODY_HEADER_BYTES = 21
COUNTER_BYTES = len(SECTION_LABELS) * 4


class StructureError(ValueError):
    """不正な外側の描画領域構造。"""


@dataclass(frozen=True)
class SectionEnvelope:
    body: bytes
    section_counts: tuple[int, ...]
    gyvl_offset: int
    body_start: int
    body_end: int
    trailer_present: bool


def read_section_envelope(payload: bytes) -> SectionEnvelope:
    """読み取り専用で本文と配置数を抽出する（図形本体は解釈しない）。"""
    if type(payload) is not bytes:
        raise TypeError('unpacked payload must be bytes')
    if len(payload) > MAX_STREAM_BYTES:
        raise StructureError('unpacked payload exceeds size limit')
    if not payload.startswith(b'vlrc') or len(payload) < 20:
        raise StructureError('invalid livery signature or header')
    gyvl = payload.find(MARKER, 20)
    if gyvl < 0:
        raise StructureError('no drawing section marker')
    begin = gyvl + BODY_HEADER_BYTES
    if begin > len(payload):
        raise StructureError('truncated drawing section header')
    trailer = payload.find(COUNTER_MARKER, gyvl + len(MARKER))
    if trailer < 0:
        stop = len(payload)
        counts = (0,) * len(SECTION_LABELS)
        return SectionEnvelope(payload[begin:stop], counts, gyvl, begin, stop, False)
    if begin > trailer:
        raise StructureError('drawing header intersects section counters')
    if trailer + 4 + COUNTER_BYTES > len(payload):
        raise StructureError('truncated section counters')
    counts = tuple(unpack_from('<' + 'I' * len(SECTION_LABELS), payload, trailer + 4))
    # A record requires at least one byte, and cannot outnumber the entire stream.
    if sum(counts) > len(payload):
        raise StructureError('impossible section placement counts')
    return SectionEnvelope(payload[begin:trailer], counts, gyvl, begin, trailer, True)


def extract_livery_sections(payload: bytes) -> tuple[bytes, list[int], dict[str, int]]:
    """従来の解析呼び出しと同じデータ形へ変換する。"""
    record = read_section_envelope(payload)
    return record.body, list(record.section_counts), {
        'gyvl_offset': record.gyvl_offset,
        'body_start': record.body_start,
        'body_end': record.body_end,
    }
