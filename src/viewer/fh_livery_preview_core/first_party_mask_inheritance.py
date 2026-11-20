"""
rM011：C_livery原本のGroupフラグから独自実装したMask継承処理。
旧r485で確定した動作を維持し、意味が確定した差分のみ比較する。
"""
from __future__ import annotations

from .native_structure import decode_livery_structure


def bind_native_mask_inheritance(payload: bytes, layers: list[dict],
                                 leaf_report: dict) -> tuple[list[dict], dict]:
    """
    同等性が原本で証明されたMask継承深さだけを置き換え、それ以外はr485の結果を保持する。
    """
    base = {'mode': 'r485_mask_inheritance_fallback',
            'mask_inheritance_source': 'r485', 'mask_depth_candidates': 0,
            'native_adopted_leaves': 0, 'r485_fallback_leaves': len(layers),
            'native_group_depth_leaves': 0, 'r485_group_depth_fallback_leaves': len(layers),
            'record_mask_migrated': False, 'final_mask_migrated': False,
            'privacy_migrated': False, 'xbox_parity_verified': False}
    if not isinstance(leaf_report, dict) or leaf_report.get('mode') != 'native_leaf_fields' or not leaf_report.get('all_ordered_leaves_verified'):
        return layers, {**base, 'reason': 'unverified_ordered_leaves'}
    try:
        tree = decode_livery_structure(payload)
        own = [shape for section in tree.sections for shape in section.shapes]
        if len(own) != len(layers):
            return layers, {**base, 'reason': 'shape_count_mismatch'}
        groups = {group.start: group for section in tree.sections for group in section.groups}
        if sum(len(s.groups) for s in tree.sections) != len(groups):
            return layers, {**base, 'reason': 'duplicate_group_offsets'}
        output: list[dict] = []
        adopted, negative = 0, 0
        group_adopted, group_negative = 0, 0
        contextual_fallback = 0
        for shape, item in zip(own, layers):
            if shape.section != item.get('section') or shape.source_offset != item.get('source_offset'):
                return layers, {**base, 'reason': 'leaf_order_mismatch'}
            try:
                ancestors = [groups[g] for g in shape.group_chain]
            except KeyError:
                return layers, {**base, 'reason': 'missing_group_ancestor'}
            # 原本属性0x40／0x50だけではMask Groupと証明できない。
            # 参照製品では明示的な0x60のCount付きGroup Markerと区別し、参照製品でも末尾のShape／Transform状態を使う。
            # 数値上の深さが偶然一致した場合も、この経路では受入済みr485のMask深さを維持する。
            contextual_mask_unapproved = any(
                ancestor.flags in (0x40, 0x50) for ancestor in ancestors
            )
            if contextual_mask_unapproved:
                contextual_fallback += 1
            inherited = sum(bool(ancestor.flags & 0x40) for ancestor in ancestors)
            # 制御バイト0x01や末尾Record Maskの遷移を推測しない。
            # 独立DecoderのGroup Chain長は比較のみに利用できる。
            native_depth = len(shape.group_chain)
            mask_same = (not contextual_mask_unapproved
                         and inherited == item.get('mask_group_depth'))
            depth_same = (native_depth == item.get('group_depth'))
            copied = dict(item) if mask_same or depth_same else item
            if mask_same:
                copied['mask_group_depth'] = inherited
                adopted += 1
            else:
                negative += 1
            if depth_same:
                copied['group_depth'] = native_depth
                group_adopted += 1
            else:
                group_negative += 1
            output.append(copied)
        return output, {**base, 'mode': 'first_party_group_mask_depth_partial',
                        'mask_inheritance_source': 'rL-independent-structural-groups',
                        'mask_depth_candidates': len(layers),
                        'native_adopted_leaves': adopted,
                        'r485_fallback_leaves': negative,
                        'contextual_group_mask_unapproved_leaves': contextual_fallback,
                        'native_group_depth_leaves': group_adopted,
                        'r485_group_depth_fallback_leaves': group_negative,
                        'record_mask_migrated': False,
                        'final_mask_migrated': False}
    except (ValueError, TypeError, RecursionError, IndexError, KeyError, OverflowError) as exc:
        return layers, {**base, 'reason': 'native_mask_tree_rejected',
                        'error_type': type(exc).__name__}
