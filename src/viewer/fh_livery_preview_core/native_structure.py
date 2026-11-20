"""未対応入力を拒否する独立FH6 C_livery構造デコーダー。

本プロジェクト独自の実装で、参照用Converterや権利保護された実行物は
読み込まず実行もしない。原本の幾何と階層化されたGroup属性をすべて保全し、
意味を別途検証した後の変換処理へ渡す。

制限：プライバシーの解釈、Mask継承、正規レイヤー投影は未確定。
本出力を公開用エクスポートに使用したり、製品の正規デコーダーに
無条件で置き換えたりしない。
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Literal

from fh_livery_preview_core.source_envelope import unpack_source_bytes
from fh_livery_preview_core.source_structure import SECTION_LABELS, read_section_envelope
from fh_livery_preview_core.source_leaf_records import read_leaf_record, LeafRecordError

MAX_NODES = 200_000
MAX_DEPTH = 120
MAX_CHILDREN = 15_000
MAX_SECTION_LEAVES = 100_000
SUPPORTED_FLAGS = 0x71


class SemanticLiveryError(ValueError):
    """推測なしでは原本を独立解析できない。"""


@dataclass(frozen=True)
class GroupField:
    start: int
    prefix: int | None
    position_x: float
    position_y: float
    scale: float
    rotation: float
    flags: int
    metadata_word: int
    child_count: int
    child_bitmap: bytes
    optional_four: bytes
    optional_eight: bytes
    byte_length: int
    depth: int


@dataclass(frozen=True)
class ShapeField:
    section: str
    source_offset: int
    byte_length: int
    shape_word: int
    position_x: float
    position_y: float
    scale_x: float
    scale_y: float
    rotation: float
    skew: float
    color_rgba: tuple[int, int, int, int]
    control_byte: int | None
    group_chain: tuple[int, ...]  # 描画本体内のバイトオフセット。面をまたいでも同じ基準を使う。
    child_slot: int
    next_sibling_is_group: bool


@dataclass(frozen=True)
class ParsedSection:
    name: str
    declared_shapes: int
    groups: tuple[GroupField, ...]
    shapes: tuple[ShapeField, ...]


@dataclass(frozen=True)
class ParsedLivery:
    car_id: int
    sections: tuple[ParsedSection, ...]
    drawing_body_bytes: int
    drawing_bytes_consumed: int
    terminator_present: bool
    opaque_header: bytes
    opaque_trailer: bytes
    # 安全条件：この構造解析だけでは完全なプライバシー意味論を証明できない。
    privacy_verified: Literal[False] = False
    canonical_parity_verified: Literal[False] = False


class _Parser:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.node_count = 0
        self.groups: list[GroupField] = []
        self.shapes: list[ShapeField] = []
        self.max_depth = 0

    def _group_fields(self, start: int, depth: int, *, root: bool, shift: int = 0):
        b = self.body
        p = start + shift
        if root:
            if p + 6 > len(b):
                raise SemanticLiveryError('truncated root')
            count, metadata = struct.unpack_from('<HI', b, p)
            bitmap_start = p + 6
            flags = 0
            x = y = rotation = 0.0
            scale = 1.0
            optional_four = optional_eight = b''
        else:
            if p + 23 > len(b):
                raise SemanticLiveryError('truncated group header')
            x, y, scale, rotation = struct.unpack_from('<4f', b, p)
            if not all(map(math.isfinite, (x, y, scale, rotation))):
                raise SemanticLiveryError('nonfinite group transform')
            if max(abs(x), abs(y), abs(rotation)) > 50000 or not 0.001 < abs(scale) < 5000:
                raise SemanticLiveryError('out-of-range group transform')
            flags = b[p + 16]
            if flags & ~SUPPORTED_FLAGS:
                raise SemanticLiveryError('unknown group flags')
            cursor = p + 17
            # 参照製品 CGROUP.md：共通Group属性ではidentityのu64がsigned-Yのf32に先行する。
            # 両フィールドを原本通り保持し、上位の本人識別・Mask意味論は
            # 別の検証ゲートに委ねる。
            optional_eight = b[cursor:cursor + 8] if flags & 0x01 else b''
            cursor += len(optional_eight)
            optional_four = b[cursor:cursor + 4] if flags & 0x10 else b''
            cursor += len(optional_four)
            if cursor + 6 > len(b):
                raise SemanticLiveryError('truncated group metadata')
            count, metadata = struct.unpack_from('<HI', b, cursor)
            bitmap_start = cursor + 6
        if count > MAX_CHILDREN or metadata > 65535:
            raise SemanticLiveryError('group count/metadata exceeds established dialect')
        bitmap_length = (count + 7) // 8
        end = bitmap_start + bitmap_length
        if end > len(b):
            raise SemanticLiveryError('truncated child bitmap')
        bitmap = b[bitmap_start:end]
        if count % 8 and bitmap and bitmap[-1] >> (count % 8):
            raise SemanticLiveryError('unused child bitmap bits not cleared')
        group = GroupField(
            start, b[start] if shift else None, x, y, scale, rotation,
            flags, metadata, count, bitmap, optional_four, optional_eight,
            end - start, depth,
        )
        return end, group

    def _children(self, cursor: int, group: GroupField, section: str, chain: tuple[int, ...], depth: int) -> int:
        if depth > MAX_DEPTH:
            raise SemanticLiveryError('group nesting exceeds depth limit')
        for index in range(group.child_count):
            if self.node_count >= MAX_NODES:
                raise SemanticLiveryError('node budget exceeded')
            self.node_count += 1
            child_is_group = bool(group.child_bitmap[index // 8] & (1 << (index % 8)))
            if child_is_group:
                cursor = self._read_group(cursor, section, chain, depth + 1)
            else:
                try:
                    leaf = read_leaf_record(self.body, cursor)
                except (LeafRecordError, IndexError, struct.error) as error:
                    raise SemanticLiveryError('invalid drawable at specified child boundary') from error
                self.shapes.append(ShapeField(
                    section, leaf.offset, leaf.byte_length, leaf.wire_word,
                    leaf.position_x, leaf.position_y, leaf.scale_x, leaf.scale_y,
                    leaf.rotation, leaf.skew, leaf.rgba, leaf.control_byte, chain,
                    index, (index + 1 < group.child_count and bool(
                        group.child_bitmap[(index+1)//8] & (1 << ((index+1)%8)))),
                ))
                if len(self.shapes) > MAX_SECTION_LEAVES * len(SECTION_LABELS):
                    raise SemanticLiveryError('too many drawable nodes')
                cursor += leaf.byte_length
        return cursor

    def _read_group(self, cursor: int, section: str, chain: tuple[int, ...], depth: int, *, root: bool = False) -> int:
        if depth > MAX_DEPTH:
            raise SemanticLiveryError('maximum nesting exceeded')
        # FH6原本には接頭辞なし・1バイト接頭辞ありの両Group形式が存在する。
        # 全バイトを消費できない経路はデータを返さず失敗とする。
        # FH6実原本の制御付きGroupには、先頭0x00と直後の16-byte
        # affine + metadataが共存する。無制御を先に試すと、先頭制御と
        # floatの一部を空Groupとして誤採用し、後続の子ビットマップを
        # 破壊する場合がある。参照製品の有効Group境界と照合し、
        # 構造が成立する1-byte framingを先に試す（無制御も保持）。
        shifts = (0,) if root else (1, 0)
        for shift in shifts:
            if shift and (cursor >= len(self.body) or self.body[cursor] not in (0, 1)):
                continue
            old_groups = len(self.groups)
            old_shapes = len(self.shapes)
            old_nodes = self.node_count
            try:
                next_pos, field = self._group_fields(cursor, depth, root=root, shift=shift)
                self.groups.append(field)
                self.max_depth = max(self.max_depth, depth)
                return self._children(next_pos, field, section, chain + (field.start,), depth)
            except SemanticLiveryError:
                del self.groups[old_groups:]
                del self.shapes[old_shapes:]
                self.node_count = old_nodes
        raise SemanticLiveryError(f'no unambiguous group dialect at offset {cursor}')

    def decode(self, counts: tuple[int, ...]):
        if len(counts) != len(SECTION_LABELS):
            raise SemanticLiveryError('unexpected section count')
        cursor = 0
        sections = []
        for index, (label, expected) in enumerate(zip(SECTION_LABELS, counts)):
            old_sh = len(self.shapes)
            old_gr = len(self.groups)
            cursor = self._read_group(cursor, label, (), 0, root=(index == 0))
            count = len(self.shapes) - old_sh
            if count != expected:
                raise SemanticLiveryError(f'section {label} has {count} drawable nodes, expected {expected}')
            sections.append(ParsedSection(label, expected,
                                          tuple(self.groups[old_gr:]), tuple(self.shapes[old_sh:])))
        remaining = self.body[cursor:]
        # 参照製品 CGROUP.md（FH4/5/6第3世代）：末尾の単独0x01は
        # 最後の図形のMask状態を閉じる原本文法の一部である。
        # 無視可能な余剰バイトではなく、追加Padding・拡張・未知制御は認めない。
        if remaining not in (b'', b'\x00', b'\x01'):
            raise SemanticLiveryError('unrecognized drawing trailer')
        return cursor, tuple(sections), bool(remaining)


def decode_livery_structure(source: bytes) -> ParsedLivery:
    """11面の整合を厳密に照合し、ツリーと図形ごとの原本属性を読み取る。

    この関数は画像描画、エクスポート、ゲームデータへの書込み、
    外部Converter実行、本人所有・プライバシーの確定判定を行わない。
    """
    payload = unpack_source_bytes(source)
    env = read_section_envelope(payload)
    if len(payload) < 20:
        raise SemanticLiveryError('truncated source header')
    parser = _Parser(env.body)
    consumed, sections, terminal = parser.decode(env.section_counts)
    return ParsedLivery(
        struct.unpack_from('<I', payload, 0x10)[0], sections, len(env.body), consumed,
        terminal, payload[:env.gyvl_offset], payload[env.body_end:],
    )


def group_context_evidence(parsed: ParsedLivery) -> dict[str, object]:
    """構造確定済みGroupの属性・祖先を集計する。Maskの意味を認定しない。

    参照製品では0x60 counted markerがMask Groupを表す一方、参照製品の
    attribute byteに現れる0x40は文脈依存であり同一視できない。
    この集計は図形・作者・位置・原本バイトを出力しない。
    """
    flags: dict[int, int] = {}
    contextual_groups = 0
    contextual_descendant_shapes = 0
    for section in parsed.sections:
        local = {group.start: group.flags for group in section.groups}
        if len(local) != len(section.groups):
            raise SemanticLiveryError('duplicate structural group offsets')
        for group in section.groups:
            flags[group.flags] = flags.get(group.flags, 0) + 1
            if group.flags in (0x40, 0x50):
                contextual_groups += 1
        for shape in section.shapes:
            try:
                chain_flags = (local[offset] for offset in shape.group_chain)
                if any(value in (0x40, 0x50) for value in chain_flags):
                    contextual_descendant_shapes += 1
            except KeyError as exc:
                raise SemanticLiveryError('missing structural group ancestor') from exc
    return {
        'group_flags_hex_counts': {f'0x{key:02X}': flags[key] for key in sorted(flags)},
        'contextual_group_40_count': flags.get(0x40, 0),
        'contextual_group_50_count': flags.get(0x50, 0),
        'contextual_group_total': contextual_groups,
        'contextual_group_descendant_shapes': contextual_descendant_shapes,
        'source_group_structure': 'PASS',
        'source_group_mask_semantics': (
            'UNAPPROVED_CONTEXTUAL_GROUPS' if contextual_groups else 'NOT_EVALUATED'
        ),
        'group_mask_render_approved': False,
        'xbox_visual_approved': False,
    }


def safe_structural_metrics(parsed: ParsedLivery) -> dict[str, object]:
    """件数とGroup属性のみの構造監査。Mask描画の承認とは切り離す。"""
    return {
        'car_id': parsed.car_id,
        'section_counts': {s.name: len(s.shapes) for s in parsed.sections},
        'total_shapes': sum(len(s.shapes) for s in parsed.sections),
        'total_groups': sum(len(s.groups) for s in parsed.sections),
        'drawing_body_bytes': parsed.drawing_body_bytes,
        'drawing_bytes_consumed': parsed.drawing_bytes_consumed,
        'drawing_terminator_present': parsed.terminator_present,
        'privacy_verified': parsed.privacy_verified,
        'canonical_parity_verified': parsed.canonical_parity_verified,
        **group_context_evidence(parsed),
    }
