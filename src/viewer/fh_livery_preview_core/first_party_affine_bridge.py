"""rM004: rL独自グループ行列を、真正r485との全レコード照合後に限定採用する。

未知のMask/Skew/画面座標はr485の正常な描画出力に戻す。
旧r485のUI、URI、材質、ガラス、車輪、描画器を変更しない。
Xboxゲームと完全一致すると認定するものではない。
"""
from __future__ import annotations

import math

from .native_structure import decode_livery_structure
from .native_skew_candidate import source_shear_matrices
from .surface_tree_flatten import _components

# r485の元描画へ戻せることを前提とした厳密な数値ゲート。
MATRIX_EPS = 1e-5
COMPONENT_EPS = 1e-12
# r485 canonical 2D section coordinate bases, derived by exact 6-component
# comparisons on independent Vivio/Jaguar C_livery leaves. This is a section
# projection only: no car-ID, paint-ID or group-flag special casing.
# Degrees are counterclockwise in the column-vector 2D affine convention.
SECTION_QUARTER_TURNS = {
    'Right': 2,
    'RightWindow': 2,
    'Spoiler': 1,
    'FrontWindshield': 1,
    'BackWindshield': 3,
}



def _render_matrix(data):
    x, y, sx, sy, degrees, skew = data[:6]
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return (c*sx, s*sx, (c*skew-s)*sy, (s*skew+c)*sy, x, y)


def _candidate_components(affine, section):
    # Apply the section projection to both linear axes AND translation.
    # In particular, front glass and spoiler use +90 degrees, rear glass
    # -90 degrees; the older bridge only handled right-side 180 degrees.
    # Other sections are identity. Unknown sections are never approved.
    if section not in (
        'Front', 'Back', 'Top', 'Left', 'Right', 'Spoiler',
        'FrontWindshield', 'BackWindshield', 'TopWindow',
        'LeftWindow', 'RightWindow',
    ):
        raise ValueError('unknown C_livery section')
    a, b, c, d, x, y = (
        affine.a, affine.b, affine.c, affine.d, affine.tx, affine.ty
    )
    turns = SECTION_QUARTER_TURNS.get(section, 0)
    if turns == 1:
        a, b, c, d, x, y = -b, a, -d, c, -y, x
    elif turns == 2:
        a, b, c, d, x, y = -a, -b, -c, -d, -x, -y
    elif turns == 3:
        a, b, c, d, x, y = b, -a, d, -c, y, -x
    return (a,b,c,d,x,y), _components((a,c,b,d,x,y))


def bind_native_affine_transform(payload: bytes, layers: list[dict], native_report: dict) -> tuple[list[dict], dict]:
    """元配列は変更せず、一致する図形だけ独自行列値を出力へ採用する。"""
    report = {'mode':'r485_safe_fallback', 'transform_source':'r485',
              'native_transform_parity_verified':False, 'xbox_parity_verified':False,
              'native_converted_leaves':0, 'r485_fallback_leaves':len(layers)}
    if native_report.get('mode') != 'native_leaf_fields' or not native_report.get('all_ordered_leaves_verified'):
        return layers,{**report,'reason':'leaf_identity_not_verified'}
    try:
        parsed=decode_livery_structure(payload)
        shapes=[shape for section in parsed.sections for shape in section.shapes]
        if len(shapes)!=len(layers) or any(
            shape.section != layer.get('section') or shape.source_offset != layer.get('source_offset')
            for shape,layer in zip(shapes,layers)
        ):
            return layers,{**report,'reason':'ordered_leaf_mismatch'}
        matrices=list(source_shear_matrices(parsed,rotation_sign=1))
        # Second, independently computed candidate for a nested, one-byte-prefixed
        # group rotation. This is a hypothesis only: the canonical numeric
        # placement remains the authority and all nonmatching leaves fall back.
        flipped=list(source_shear_matrices(
            parsed,rotation_sign=1,prefixed_group_rotation_sign=-1))
        if len(matrices)!=len(layers) or len(flipped)!=len(layers) or any(
            shape.section != layer.get('section') or shape.source_offset != layer.get('source_offset')
            for (shape,_),layer in zip(matrices,layers)
        ):
            return layers,{**report,'reason':'affine_order_mismatch'}
        if any(a.section != b.section or a.source_offset != b.source_offset
               for (a,_),(b,_) in zip(matrices,flipped)):
            return layers,{**report,'reason':'alternate_affine_order_mismatch'}
        copied=[]
        approved=0
        alternate_approved=0
        fallback_by_section={}
        for (shape,affine),(_,alternate_affine),layer in zip(matrices,flipped,layers):
            original=list(layer.get('data') or [])
            section=shape.section
            if len(original)<7:
                copied.append(layer)
                fallback_by_section[section]=fallback_by_section.get(section,0)+1
                continue
            selected=None
            for candidate_name,candidate in (
                ('regular',affine),
                ('prefixed_group_rotation',alternate_affine),
            ):
                try:
                    matrix, components=_candidate_components(candidate,section)
                    current=_render_matrix(original)
                    matrix_ok=max(abs(a-b) for a,b in zip(matrix,current))<MATRIX_EPS
                    component_ok=max(abs(a-b) for a,b in zip(components,original[:6]))<COMPONENT_EPS
                    finite=all(math.isfinite(v) for v in components)
                except (OverflowError,ValueError,ZeroDivisionError):
                    continue
                if matrix_ok and component_ok and finite:
                    selected=(candidate_name,components)
                    break
            if selected is None:
                copied.append(layer)
                fallback_by_section[section]=fallback_by_section.get(section,0)+1
                continue
            candidate_name,components=selected
            alternate_approved+=candidate_name=='prefixed_group_rotation'
            # `data[6]` は旧r485のMask状態。行列置換では絶対に変更しない。
            item=dict(layer)
            item['data']=[*components,*original[6:]]
            copied.append(item)
            approved+=1
        return copied, {
            **report, 'mode':'partial_first_party_affine',
            'transform_source':'rL-verified-first-party-for-matching-leaves',
            'native_converted_leaves':approved,
            'prefixed_group_rotation_converted_leaves':alternate_approved,
            'r485_fallback_leaves':len(layers)-approved,
            'r485_fallback_by_section':fallback_by_section,
            'matrix_threshold':MATRIX_EPS, 'component_threshold':COMPONENT_EPS,
            'section_projection':'quarter_turns_derived_from_r485_numeric_parity',
            'nested_prefixed_group_rotation':'numeric_gate_only_no_automatic_approval',
            # これはr485数値同等の範囲であり、Xbox投影正解の証明ではない。
            'native_transform_parity_verified':approved>0,
            'xbox_parity_verified':False,
        }
    except (ValueError,TypeError,IndexError,OverflowError,RecursionError,AttributeError) as error:
        return layers,{**report,'reason':'native_affine_rejected','error_type':type(error).__name__}
