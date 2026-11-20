"""PRIVATE-only, opt-in FH6 C_livery 2-D placement affine research.

Independent project implementation; 参照製品 documentation is an
external *format reference*, NOT code reused here. This interprets the bytes
already structurally decoded by semantic_livery without changing that decoder.

Explicit hypotheses needing Xbox comparison: the sign of group/shape rotation,
local skew basis, the game's section projection, group mask ancestry, color
compositing and raster logos. No result from this module is render-approved.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from collections import Counter

from .native_structure import ParsedLivery, GroupField, ShapeField


class AffineTrialError(ValueError):
    """Reject missing hierarchy, unsupported attributes and nonfinite matrices."""


@dataclass(frozen=True)
class Affine:
    # (a c tx; b d ty; 0 0 1) acts on 2D column vectors.
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def then_local(self, other: 'Affine') -> 'Affine':
        """Parent * child (child acts first)."""
        return Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.tx + self.c * other.ty + self.tx,
            self.b * other.tx + self.d * other.ty + self.ty,
        )

    def point(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.tx,
                self.b * x + self.d * y + self.ty)

    @property
    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c


def _checked(vals: tuple[float, ...]):
    if not all(math.isfinite(x) and abs(x) <= 1.0e12 for x in vals):
        raise AffineTrialError('nonfinite or out-of-budget transform')


def _placement(x: float, y: float, sx: float, sy: float,
               rotation_degrees: float, *, rotation_sign: int) -> Affine:
    if rotation_sign not in (-1, 1):
        raise AffineTrialError('rotation sign must be explicit')
    _checked((x, y, sx, sy, rotation_degrees))
    if abs(sx) < 1.e-7 or abs(sy) < 1.e-7 or max(abs(sx), abs(sy)) > 5000:
        raise AffineTrialError('degenerate or unbounded scale')
    rad = math.radians(rotation_degrees * rotation_sign)
    co, si = math.cos(rad), math.sin(rad)
    return Affine(co*sx, si*sx, -si*sy, co*sy, x, y)


def group_basis(group: GroupField, *, rotation_sign: int) -> Affine:
    """Use separately encoded signed Y when flag 0x10 is present.

    The field is decoded as little-endian f32, NOT assumed to be the X scale.
    This is a transform hypothesis; the source reader itself stays unchanged.
    """
    if group.flags & 0x10:
        if len(group.optional_four) != 4:
            raise AffineTrialError('group Y field missing')
        sy = struct.unpack('<f', group.optional_four)[0]
    elif group.optional_four:
        raise AffineTrialError('unexpected group Y extension')
    else:
        sy = group.scale
    return _placement(group.position_x, group.position_y, group.scale, sy,
                      group.rotation, rotation_sign=rotation_sign)


def _shape_basis(shape: ShapeField, *, rotation_sign: int) -> Affine:
    # Skew is *not* interpreted until its source semantics are separately proven.
    if abs(shape.skew) > 1.e-6:
        raise AffineTrialError('skewed shape is not geometry-transform approved')
    return _placement(shape.position_x, shape.position_y,
                      shape.scale_x, shape.scale_y, shape.rotation,
                      rotation_sign=rotation_sign)


def affine_trials(parsed: ParsedLivery, *, rotation_sign: int,
                  sample_limit: int = 0):
    """Yield (shape, group_world, shape_world) for no-skew samples only.

    sample_limit=0 includes every structurally parsed shape; skewed shapes yield
    shape_world=None, but always retain group_world for center diagnostics.
    Unresolved shape skew or mask never silently becomes a drawable triangle.
    """
    if not isinstance(parsed, ParsedLivery):
        raise AffineTrialError('expected decoded native livery')
    if type(sample_limit) is not int or sample_limit < 0:
        raise AffineTrialError('invalid limit')
    emitted = 0
    for section in parsed.sections:
        groups = {g.start:g for g in section.groups}
        cached: dict[int, Affine] = {}
        for shape in section.shapes:
            world = Affine()
            for offset in shape.group_chain:
                g = groups.get(offset)
                if g is None:
                    raise AffineTrialError('shape references unknown group in section')
                world = world.then_local(group_basis(g, rotation_sign=rotation_sign))
            try:
                full = world.then_local(_shape_basis(shape, rotation_sign=rotation_sign))
            except AffineTrialError as exc:
                if 'skewed shape' not in str(exc):
                    raise
                full = None
            center = world.point(shape.position_x, shape.position_y)
            _checked(center)
            if full is not None:
                _checked((full.a, full.b, full.c, full.d, full.tx, full.ty))
            yield shape, world, full
            emitted += 1
            if sample_limit and emitted >= sample_limit:
                return


def safe_affine_metrics(parsed: ParsedLivery) -> dict:
    """Counts-only private diagnostics; do not expose paint placement details."""
    metrics: dict[str, object] = {'schema':'lo4fh6.private.paint-affine-trial.v1'}
    for sign, key in ((1,'positive_degrees'),(-1,'negative_degrees')):
        total = safe = skewed = reflected = 0
        max_depth = 0
        for shape, group_world, shape_world in affine_trials(parsed, rotation_sign=sign):
            total += 1
            max_depth = max(max_depth,len(shape.group_chain))
            if shape_world is None:
                skewed += 1
            else:
                safe += 1
                reflected += shape_world.determinant < 0
        metrics[key] = {'total_shapes':total,'no_skew_transform_candidates':safe,
                        'skew_unresolved_shapes':skewed,
                        'candidate_reflections':reflected,'max_group_depth':max_depth}
    metrics.update({'signed_y_group_fields':sum(bool(g.flags&0x10) for s in parsed.sections for g in s.groups),
                    'source_group_count':sum(len(s.groups) for s in parsed.sections),
                    'rotation_sign_verified':False,'skew_verified':False,
                    'mask_inheritance_verified':False,'projection_verified':False,
                    'render_safe':False,'release_approved':False})
    return metrics
