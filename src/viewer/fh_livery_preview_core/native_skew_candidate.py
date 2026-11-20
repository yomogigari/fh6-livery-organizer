"""
明示指定でのみ使用する、描画未承認のFH6水平Shearアフィン候補。
原本由来の数値を研究比較に限って扱い、通常製品の描画既定には接続しない。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .native_affine_trial import Affine, AffineTrialError, group_basis
from .native_structure import ParsedLivery, ShapeField


class SkewCandidateError(ValueError):
    pass


MAX_RELATIVE_SHEAR = 200.0
# C_liveryの原本Leafを独立構造Parserが検証する上限。外部任意Shapeへは適用しない。
SOURCE_RECORD_MAX_RELATIVE_SHEAR = 1_000_000.0
MAX_ABS_TRANSFORM = 1.0e12


def shape_shear_candidate(shape: ShapeField, *, rotation_sign: int, source_bound_research: bool = False) -> Affine:
    """Hypothesis: translate, rotate, horizontal shear, then scale.

    The local X axis is rotated (scale_x,0). The Y axis is rotated
    (skew * scale_y, scale_y). Negative scales and mirrors stay signed.
    This is *not* a release-approved geometry transform.
    """
    if type(rotation_sign) is not int or rotation_sign not in (-1, 1):
        raise SkewCandidateError('explicit rotation sign required')
    sx, sy, k = shape.scale_x, shape.scale_y, shape.skew
    px, py, rotation = shape.position_x, shape.position_y, shape.rotation
    # 参照製品 source decoderと参照製品の形状行列、実FH6 C_livery 1085 uniqueの
    # 8件を突き合わせた。高skewは小さな原本scale_yと相殺して有限行列に
    # なる。独立Leaf ParserがShapeFieldとして読んだ原本だけwire上限を
    # 適用し、任意入力には従来200を保持。Matrix/Finite/scale安全性は維持。
    # Shader/Xbox外観の承認とは無関係な原本数値の欠落防止。
    allowed_shear = (SOURCE_RECORD_MAX_RELATIVE_SHEAR
                     if (isinstance(shape, ShapeField) or source_bound_research)
                     else MAX_RELATIVE_SHEAR)
    # 図形ごとに動くので、生成式を使わずに並べて比べる（2026-11-20。判定は以前の all/any と同じ）。
    isfinite = math.isfinite
    if (not (isfinite(px) and isfinite(py) and isfinite(rotation) and isfinite(sx) and isfinite(sy)
             and isfinite(k))
        or abs(px) > MAX_ABS_TRANSFORM or abs(py) > MAX_ABS_TRANSFORM or abs(rotation) > MAX_ABS_TRANSFORM
        or abs(sx) > MAX_ABS_TRANSFORM or abs(sy) > MAX_ABS_TRANSFORM or abs(k) > MAX_ABS_TRANSFORM
        or not 1e-7 < abs(sx) <= 5000 or not 1e-7 < abs(sy) <= 5000
        or abs(k) > allowed_shear):
        raise SkewCandidateError('invalid or out-of-bounds native shape placement')
    angle = math.radians(rotation_sign * shape.rotation)
    c, s = math.cos(angle), math.sin(angle)
    a, b, cc, d = c*sx, s*sx, (c*k-s)*sy, (s*k+c)*sy
    for v in (a, b, cc, d, px, py):
        if not (isfinite(v) and abs(v) <= MAX_ABS_TRANSFORM):
            raise SkewCandidateError('candidate matrix exceeds numeric budget')
    return Affine(a, b, cc, d, px, py)


def source_shear_matrices(parsed: ParsedLivery, *, rotation_sign: int,
                          prefixed_group_rotation_sign: int = 1):
    """
    原本の図形位置を公開せず、図形と変換の組を順に返す。
    """
    if not isinstance(parsed, ParsedLivery):
        raise SkewCandidateError('parsed FH6 livery required')
    if type(rotation_sign) is not int or rotation_sign not in (-1, 1):
        raise SkewCandidateError('explicit rotation sign required')
    if type(prefixed_group_rotation_sign) is not int or prefixed_group_rotation_sign not in (-1, 1):
        raise SkewCandidateError('invalid prefixed group rotation polarity')
    for section in parsed.sections:
        groups = {g.start: g for g in section.groups}
        if len(groups) != len(section.groups):
            raise SkewCandidateError('group offset collision')
        worlds: dict[tuple[int, ...], Affine] = {(): Affine()}
        for shape in section.shapes:
            chain = shape.group_chain
            if not chain:
                raise SkewCandidateError('shape lacks root group')
            if chain not in worlds:
                current = Affine()
                for offset in chain:
                    group = groups.get(offset)
                    if group is None:
                        raise SkewCandidateError('missing group in native ancestry')
                    try:
                        current = current.then_local(group_basis(
                            replace(group, rotation=-group.rotation)
                            if prefixed_group_rotation_sign == -1 and group.prefix == 1 and group.depth > 0 else group,
                            rotation_sign=rotation_sign))
                    except AffineTrialError as exc:
                        raise SkewCandidateError('invalid group basis') from exc
                    if not all(math.isfinite(v) and abs(v) <= MAX_ABS_TRANSFORM
                               for v in (current.a,current.b,current.c,current.d,current.tx,current.ty)):
                        raise SkewCandidateError('group world matrix outside numeric budget')
                worlds[chain] = current
            matrix = worlds[chain].then_local(shape_shear_candidate(shape, rotation_sign=rotation_sign))
            terms = (matrix.a,matrix.b,matrix.c,matrix.d,matrix.tx,matrix.ty)
            if not all(math.isfinite(v) and abs(v) <= MAX_ABS_TRANSFORM for v in terms):
                raise SkewCandidateError('world matrix outside numeric budget')
            if not math.isfinite(matrix.determinant) or abs(matrix.determinant) < 1e-20:
                raise SkewCandidateError('non-invertible candidate')
            yield shape, matrix


def safe_shear_candidate_metrics(parsed: ParsedLivery) -> dict:
    """
    原本幾何・座標・パス・色を含めず、集約した指標だけを取得する。
    """
    out = {'schema':'lo4fh6.private.paint-shear-candidate.v1'}
    source_count = sum(s.declared_shapes for s in parsed.sections)
    for sign, key in ((1,'positive_rotation'),(-1,'negative_rotation')):
        count = shear = mirrors = 0
        max_depth = 0
        max_abs_k = 0.0
        for shape, matrix in source_shear_matrices(parsed, rotation_sign=sign):
            count += 1
            shear += abs(shape.skew) > 1e-6
            mirrors += matrix.determinant < 0
            max_depth = max(max_depth, len(shape.group_chain))
            max_abs_k = max(max_abs_k, abs(shape.skew))
        if count != source_count:
            raise SkewCandidateError('source count mismatch')
        out[key] = {
            'candidate_shape_count':count,
            'nonzero_shear_shapes':shear,
            'zero_shear_shapes':count-shear,
            'signed_determinant_mirrors':mirrors,
            'max_group_depth':max_depth,
            'max_abs_native_shear_coefficient':round(max_abs_k,6),
        }
    out.update({'source_shape_count':source_count,
                'calculation':'translate_rotate_horizontal_shear_scale_candidate',
                'geometry_render_approved':False,
                'rotation_polarity_verified':False,
                'native_projection_verified':False,
                'mask_alpha_verified':False,
                'render_safe':False,
                'release_approved':False})
    return out
