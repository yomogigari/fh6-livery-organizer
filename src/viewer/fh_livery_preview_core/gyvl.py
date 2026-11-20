from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parser import ParseError, decompress_c_group, livery_vlrc_layout


TYPE_CODE_BASE = 0x100000
LIVERY_SURFACE_NAMES = (
    "front",
    "back",
    "top",
    "left",
    "right",
    "wing",
    "front_windscreen",
    "rear_windscreen",
    "top_window",
    "left_window",
    "right_window",
)
LEGACY_LIVERY_SURFACE_NAMES = LIVERY_SURFACE_NAMES[:6]
FH6_GROUP_ROTATION_APPLICATION = "metadata_only_descendant_layers_already_baked"
LEGACY_GROUP_ROTATION_APPLICATION = "mixed_parent_rotation_and_split_leaf_segment_transform"


@dataclass(frozen=True)
class Affine:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def then(self, child: "Affine") -> "Affine":
        return Affine(
            a=self.a * child.a + self.b * child.c,
            b=self.a * child.b + self.b * child.d,
            c=self.c * child.a + self.d * child.c,
            d=self.c * child.b + self.d * child.d,
            tx=self.a * child.tx + self.b * child.ty + self.tx,
            ty=self.c * child.tx + self.d * child.ty + self.ty,
        )

    def point(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.b * y + self.tx, self.c * x + self.d * y + self.ty


@dataclass(frozen=True)
class LiveryTransform:
    position: Affine = Affine()
    basis: Affine = Affine()

    def then(self, position: Affine, basis: Affine | None = None) -> "LiveryTransform":
        return LiveryTransform(
            position=self.position.then(position),
            basis=self.basis.then(basis or position),
        )


def transform_matrix(x: float, y: float, sx: float, sy: float, rotation: float, skew: float = 0.0) -> Affine:
    theta = math.radians(-rotation)
    cosine = math.cos(theta)
    sine = math.sin(theta)
    return Affine(
        a=cosine * sx,
        b=(cosine * skew - sine) * sy,
        c=sine * sx,
        d=(sine * skew + cosine) * sy,
        tx=x,
        ty=y,
    )


def livery_group_transform_matrix(x: float, y: float, sx: float, sy: float, rotation: float) -> Affine:
    """Return the transform that a livery group contributes to flattened leaves.

    Livery streams retain a group rotation for editor selection, but the rotation
    is already baked into the descendant layer coordinates and angles. Applying it
    again while flattening double-rotates complex grouped artwork. Translation and
    scale, including mirrored scale signs, still contribute to child geometry.
    """
    del rotation
    return transform_matrix(x, y, sx, sy, 0.0)


def legacy_livery_group_transform_matrix(
    x: float,
    y: float,
    sx: float,
    sy: float,
    rotation: float,
    *,
    depth: int,
    node_state: int,
    has_group_children: bool,
    has_leaf_children: bool = True,
) -> Affine:
    """Return the legacy basis transform retained for compatibility callers."""
    _position, basis = legacy_livery_group_transform_matrices(
        x,
        y,
        sx,
        sy,
        rotation,
        depth=depth,
        node_state=node_state,
        has_group_children=has_group_children,
        has_leaf_children=has_leaf_children,
    )
    return basis


def legacy_livery_group_transform_matrices(
    x: float,
    y: float,
    sx: float,
    sy: float,
    rotation: float,
    *,
    depth: int,
    node_state: int,
    has_group_children: bool,
    has_leaf_children: bool,
) -> tuple[Affine, Affine]:
    """Return separate position and basis transforms for legacy v1 groups.

    Group-only artwork trees already bake their editor rotation into descendant
    leaves. Mixed top-level groups still move direct leaves. Leaf-only segment
    groups in the controlled FH5 sample rotate child centers with the opposite
    sign from the orientation retained in each leaf. A single affine transform
    cannot represent that final case.
    """
    normalized_rotation = (rotation + 180.0) % 360.0 - 180.0
    normalized_half_turn = (rotation + 90.0) % 180.0 - 90.0
    leaf_segment_rotation = (
        depth > 1
        and node_state == 1
        and not has_group_children
        and abs(normalized_rotation) > 45.0
    )
    movable_parent_rotation = depth == 1 and node_state == 1 and has_leaf_children
    if leaf_segment_rotation:
        return (
            transform_matrix(x, y, sx, sy, -normalized_half_turn),
            transform_matrix(x, y, sx, sy, rotation),
        )
    applied_rotation = rotation if movable_parent_rotation else 0.0
    transform = transform_matrix(x, y, sx, sy, applied_rotation)
    return transform, transform


def livery_painter_type_word(word: int) -> tuple[int, int]:
    """Split the observed livery resource flag from its Painter shape word."""
    flags = word & 0xF000
    if flags in (0x8000, 0xA000):
        return word & 0x0FFF, flags
    return word, 0


def decompose_for_painter(matrix: Affine) -> tuple[float, float, float, float]:
    sx = math.hypot(matrix.a, matrix.c)
    if sx < 1e-12:
        raise ParseError("gyvl layer has a degenerate X scale")
    qx = matrix.a / sx
    qy = matrix.c / sx
    sy = -qy * matrix.b + qx * matrix.d
    if abs(sy) < 1e-12:
        raise ParseError("gyvl layer has a degenerate Y scale")
    skew = (qx * matrix.b + qy * matrix.d) / sy
    rotation = (-math.degrees(math.atan2(qy, qx))) % 360.0
    if math.isclose(rotation, 360.0, abs_tol=1e-6):
        rotation = 0.0
    return sx, sy, rotation, skew


class GyvlTreeParser:
    def __init__(self, data: bytes):
        self.data = data
        self.shapes: list[dict[str, Any]] = []
        self.group_count = 0
        self.owner_records: list[dict[str, Any]] = []

    def parse_painter_json(self) -> dict[str, Any]:
        if len(self.data) < 12 or self.data[:4] != b"gyvl":
            raise ParseError("payload is not a gyvl stream")
        end = self._parse_node(12, Affine())
        if end != len(self.data):
            raise ParseError(f"unparsed gyvl tail at 0x{end:X}: {len(self.data) - end} bytes")
        return {
            "format": "fh6_typecode_json_export_v1",
            "source": "fh6_layergroup_gyvl",
            "group_count": self.group_count,
            "shape_count": len(self.shapes),
            "shapes": self.shapes,
        }

    def _parse_node(self, offset: int, parent: Affine) -> int:
        if offset >= len(self.data):
            raise ParseError("gyvl node starts beyond end of stream")
        if self.data[offset] == 3:
            return self._parse_group(offset, parent)
        return self._parse_leaf(offset, parent)

    def _parse_group(self, offset: int, parent: Affine) -> int:
        start = offset
        if offset + 24 > len(self.data):
            raise ParseError(f"truncated gyvl group at 0x{start:X}")
        self.group_count += 1
        x, y, sx, rotation = struct.unpack_from("<4f", self.data, offset + 1)
        flags = self.data[offset + 17]
        offset += 18
        sy = sx
        if flags & 0x10:
            sy = struct.unpack_from("<f", self.data, offset)[0]
            offset += 4
        if flags & 0x01:
            owner = struct.unpack_from("<Q", self.data, offset)[0]
            self.owner_records.append(
                {
                    "group_offset": f"0x{start:X}",
                    "xuid_offset": f"0x{offset:X}",
                    "xuid": str(owner),
                    "xuid_hex": f"0x{owner:016X}",
                }
            )
            offset += 8
        if offset + 6 > len(self.data):
            raise ParseError(f"truncated gyvl group header at 0x{start:X}")
        child_count = struct.unpack_from("<H", self.data, offset)[0]
        offset += 6  # child_count plus node_state
        bitmap_size = (child_count + 7) // 8
        bitmap = self.data[offset : offset + bitmap_size]
        if len(bitmap) != bitmap_size:
            raise ParseError(f"truncated gyvl child bitmap at 0x{start:X}")
        offset += bitmap_size
        current = parent.then(transform_matrix(x, y, sx, sy, rotation))
        for index in range(child_count):
            expected_group = bool(bitmap[index // 8] & (1 << (index % 8)))
            actual_group = offset < len(self.data) and self.data[offset] == 3
            if expected_group != actual_group:
                raise ParseError(f"gyvl child bitmap mismatch at 0x{offset:X}")
            offset = self._parse_node(offset, current)
        if offset >= len(self.data) or self.data[offset] != 1:
            raise ParseError(f"gyvl group at 0x{start:X} has no 0x01 terminator")
        return offset + 1

    def _parse_leaf(self, offset: int, parent: Affine) -> int:
        if offset + 32 > len(self.data) or self.data[offset] != 2:
            value = self.data[offset] if offset < len(self.data) else -1
            raise ParseError(f"unsupported gyvl node type 0x{value:02X} at 0x{offset:X}")
        word = struct.unpack_from("<H", self.data, offset + 1)[0]
        rotation, x, y, sx, sy, saved_skew = struct.unpack_from("<6f", self.data, offset + 3)
        blue, green, red, alpha = self.data[offset + 27 : offset + 31]
        mask = bool(self.data[offset + 31])

        # Compose in visual coordinates, then expose the game-memory skew sign.
        visual_layer = transform_matrix(x, y, sx, sy, rotation, -saved_skew)
        world = parent.then(visual_layer)
        world_x, world_y = world.point(0.0, 0.0)
        world_sx, world_sy, world_rotation, visual_skew = decompose_for_painter(world)
        memory_skew = -visual_skew
        painter_word, word_flags = self._painter_type_word(word)
        shape = {
            "type": TYPE_CODE_BASE + painter_word,
            "type_word": painter_word,
            "type_word_hex": f"0x{painter_word:04x}",
            "data": [world_x, world_y, world_sx, world_sy, world_rotation, memory_skew, int(mask)],
            "color": [red, green, blue, alpha],
            "mask": mask,
            "mask_source": "group" if inherited_mask else ("record" if record_mask else "none"),
            "raw_trailing_mask": raw_trailing_mask,
            "score": 0,
            "gyvl_offset": f"0x{offset:X}",
        }
        if word_flags:
            shape.update(
                {
                    "gyvl_type_word": word,
                    "gyvl_type_word_hex": f"0x{word:04x}",
                    "gyvl_type_word_flags": f"0x{word_flags:04x}",
                }
            )
        self.shapes.append(shape)
        return offset + 32

    def _painter_type_word(self, word: int) -> tuple[int, int]:
        return word, 0


class LiveryGyvlParser(GyvlTreeParser):
    def __init__(
        self,
        data: bytes,
        *,
        nested_group_rotation_application: str = FH6_GROUP_ROTATION_APPLICATION,
        group_rotation_policy: str = "metadata_only",
    ):
        super().__init__(data)
        self.nested_group_rotation_application = nested_group_rotation_application
        self.group_rotation_policy = group_rotation_policy

    def _painter_type_word(self, word: int) -> tuple[int, int]:
        return livery_painter_type_word(word)

    def parse_surfaces(
        self,
        surface_names: tuple[str, ...] = LIVERY_SURFACE_NAMES,
        *,
        surface_name_source: str | None = None,
    ) -> dict[str, Any]:
        if len(self.data) < 4 or self.data[:4] != b"gyvl":
            raise ParseError("payload is not a livery gyvl stream")
        offset = 4
        surfaces: list[dict[str, Any]] = []
        for index, name in enumerate(surface_names):
            shape_start = len(self.shapes)
            group_start = self.group_count
            offset, root = self._parse_group_body(
                offset,
                LiveryTransform(),
                nested=False,
                depth=0,
                apply_transform=False,
            )
            surface_shapes = self.shapes[shape_start:]
            for shape in surface_shapes:
                shape["surface_index"] = index
                shape["surface_name"] = name
            surfaces.append(
                {
                    "index": index,
                    "name": name,
                    "gyvl_offset": f"0x{root['start']:X}",
                    "direct_child_count": root["child_count"],
                    "node_state": root["node_state"],
                    "flags": root["flags"],
                    "nested_group_count": self.group_count - group_start,
                    "shape_count": len(surface_shapes),
                    "coordinate_space": "surface_local_unclipped",
                    "requires_vehicle_mesh_clipping_for_final_preview": True,
                    "nested_group_rotation_application": self.nested_group_rotation_application,
                    "transform": root["transform"],
                    "shapes": surface_shapes,
                }
            )
        if offset != len(self.data):
            raise ParseError(f"unparsed livery gyvl tail at 0x{offset:X}: {len(self.data) - offset} bytes")
        return {
            "format": "fh6_livery_surface_json_v1",
            "source": "fh6_livery_gyvl",
            "surface_name_source": surface_name_source
            or "FH6 projection slot order validated by paired left/right surface data",
            "nested_group_rotation_application": self.nested_group_rotation_application,
            "surface_count": len(surfaces),
            "group_count": self.group_count,
            "shape_count": len(self.shapes),
            "surfaces": surfaces,
        }

    def _parse_group_body(
        self,
        start: int,
        parent: LiveryTransform,
        *,
        nested: bool,
        depth: int,
        apply_transform: bool = True,
        inherited_mask: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        if depth > 64 or start + 23 > len(self.data):
            raise ParseError(f"truncated livery group body at 0x{start:X}")
        x, y, sx, rotation = struct.unpack_from("<4f", self.data, start)
        flags = self.data[start + 16]
        # Counted 0x60/0x70-family groups are mask groups. Mask ancestry is
        # authoritative and propagates to every descendant (Forza generation 3).
        group_mask = inherited_mask or bool(flags & 0x40)
        if flags & ~0x71:
            raise ParseError(f"unsupported livery group flags 0x{flags:02X} at 0x{start:X}")
        offset = start + 17
        sy = sx
        if flags & 0x10:
            sy = struct.unpack_from("<f", self.data, offset)[0]
            offset += 4
        if flags & 0x01:
            owner = struct.unpack_from("<Q", self.data, offset)[0]
            self.owner_records.append(
                {
                    "group_offset": f"0x{start:X}",
                    "xuid_offset": f"0x{offset:X}",
                    "xuid": str(owner),
                    "xuid_hex": f"0x{owner:016X}",
                }
            )
            offset += 8
        if offset + 6 > len(self.data):
            raise ParseError(f"truncated livery group fields at 0x{start:X}")
        child_count = struct.unpack_from("<H", self.data, offset)[0]
        node_state = struct.unpack_from("<I", self.data, offset + 2)[0]
        if child_count > 3000:
            raise ParseError(f"implausible livery child count {child_count} at 0x{start:X}")
        offset += 6
        bitmap_size = (child_count + 7) // 8
        bitmap = self.data[offset : offset + bitmap_size]
        if len(bitmap) != bitmap_size:
            raise ParseError(f"truncated livery child bitmap at 0x{start:X}")
        offset += bitmap_size
        if apply_transform:
            if self.group_rotation_policy == "legacy_selective":
                group_position, group_basis = legacy_livery_group_transform_matrices(
                    x,
                    y,
                    sx,
                    sy,
                    rotation,
                    depth=depth,
                    node_state=node_state,
                    has_group_children=any(bitmap),
                    has_leaf_children=child_count > sum(byte.bit_count() for byte in bitmap),
                )
            else:
                group_position = livery_group_transform_matrix(x, y, sx, sy, rotation)
                group_basis = group_position
            current = parent.then(group_position, group_basis)
        else:
            current = parent

        shape_checkpoint = len(self.shapes)
        owner_checkpoint = len(self.owner_records)
        group_checkpoint = self.group_count
        prefixes = (0,) if not nested or child_count == 0 else (0, 1)
        last_error: ParseError | None = None
        for prefix_size in prefixes:
            del self.shapes[shape_checkpoint:]
            del self.owner_records[owner_checkpoint:]
            self.group_count = group_checkpoint
            cursor = offset + prefix_size
            try:
                for index in range(child_count):
                    is_group = bool(bitmap[index // 8] & (1 << (index % 8)))
                    if is_group:
                        self.group_count += 1
                        cursor, _ = self._parse_group_body(
                            cursor, current, nested=True, depth=depth + 1, inherited_mask=group_mask
                        )
                    else:
                        cursor = self._parse_leaf(cursor, current, inherited_mask=group_mask)
                return cursor, {
                    "start": start,
                    "flags": flags,
                    "child_count": child_count,
                    "node_state": node_state,
                    "transform": {
                        "x": x,
                        "y": y,
                        "scale_x": sx,
                        "scale_y": sy,
                        "rotation": rotation,
                        "rotation_application": self.nested_group_rotation_application,
                    },
                    "child_prefix_size": prefix_size,
                    "mask_group": bool(flags & 0x40),
                    "inherited_mask": group_mask,
                }
            except ParseError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _parse_leaf(self, offset: int, parent: LiveryTransform, *, inherited_mask: bool = False) -> int:
        if offset + 32 > len(self.data) or self.data[offset] != 2:
            value = self.data[offset] if offset < len(self.data) else -1
            raise ParseError(f"unsupported gyvl node type 0x{value:02X} at 0x{offset:X}")
        word = struct.unpack_from("<H", self.data, offset + 1)[0]
        rotation, x, y, sx, sy, saved_skew = struct.unpack_from("<6f", self.data, offset + 3)
        blue, green, red, alpha = self.data[offset + 27 : offset + 31]
        raw_trailing_mask = bool(self.data[offset + 31])
        # In generation 3, an odd record lead is trailing mask state for the
        # preceding direct shape. Outside an explicit mask group, chromatic
        # color clears this otherwise-ambiguous state.
        chromatic = blue != green or green != red
        record_mask = raw_trailing_mask and not chromatic
        mask = inherited_mask or record_mask

        world_x, world_y = parent.position.point(x, y)
        visual_layer_basis = transform_matrix(0.0, 0.0, sx, sy, rotation, -saved_skew)
        world_basis = parent.basis.then(visual_layer_basis)
        world_sx, world_sy, world_rotation, visual_skew = decompose_for_painter(world_basis)
        memory_skew = -visual_skew
        painter_word, word_flags = self._painter_type_word(word)
        shape = {
            "type": TYPE_CODE_BASE + painter_word,
            "type_word": painter_word,
            "type_word_hex": f"0x{painter_word:04x}",
            "data": [world_x, world_y, world_sx, world_sy, world_rotation, memory_skew, int(mask)],
            "color": [red, green, blue, alpha],
            "mask": mask,
            "mask_source": "group" if inherited_mask else ("record" if record_mask else "none"),
            "raw_trailing_mask": raw_trailing_mask,
            "score": 0,
            "gyvl_offset": f"0x{offset:X}",
        }
        if word_flags:
            shape.update(
                {
                    "gyvl_type_word": word,
                    "gyvl_type_word_hex": f"0x{word:04x}",
                    "gyvl_type_word_flags": f"0x{word_flags:04x}",
                }
            )
        self.shapes.append(shape)
        return offset + 32


def gyvl_to_painter_json(data: bytes) -> dict[str, Any]:
    return GyvlTreeParser(data).parse_painter_json()


def layergroup_to_painter_json(path: Path) -> dict[str, Any]:
    source = path / "C_group" if path.is_dir() else path
    if not source.exists():
        raise ParseError(f"LayerGroup C_group file not found: {source}")
    return gyvl_to_painter_json(decompress_c_group(source))


def read_livery_payload(path: Path) -> bytes:
    source = path / "C_livery" if path.is_dir() else path
    if not source.exists():
        raise ParseError(f"Livery C_livery file not found: {source}")
    wrapped = source.read_bytes()
    if len(wrapped) < 8:
        raise ParseError("C_livery is shorter than its wrapper")
    try:
        payload = zlib.decompress(wrapped[8:])
    except zlib.error as exc:
        raise ParseError(f"invalid C_livery zlib payload: {exc}") from exc
    if len(payload) < 0x33 or payload[:4] != b"vlrc":
        raise ParseError("C_livery payload is not a vlrc stream")
    return payload


def extract_livery_gyvl(path: Path) -> bytes:
    payload = read_livery_payload(path)
    format_version = struct.unpack_from("<I", payload, 0x004)[0]
    layout = livery_vlrc_layout(format_version)
    if layout is None:
        raise ParseError(f"unsupported vlrc format version {format_version}")
    gyvl_size_offset = int(layout["gyvl_size_offset"])
    gyvl_offset = int(layout["gyvl_offset"])
    gyvl_size = struct.unpack_from("<I", payload, gyvl_size_offset)[0]
    end = gyvl_offset + gyvl_size
    gyvl = payload[gyvl_offset:end]
    if len(gyvl) != gyvl_size or gyvl[:4] != b"gyvl":
        raise ParseError("invalid or truncated livery gyvl section")
    return gyvl


def livery_to_surface_json(path: Path) -> dict[str, Any]:
    payload = read_livery_payload(path)
    format_version = struct.unpack_from("<I", payload, 0x004)[0]
    layout = livery_vlrc_layout(format_version)
    if layout is None:
        raise ParseError(f"unsupported vlrc format version {format_version}")
    gyvl_size_offset = int(layout["gyvl_size_offset"])
    gyvl_offset = int(layout["gyvl_offset"])
    gyvl_size = struct.unpack_from("<I", payload, gyvl_size_offset)[0]
    if format_version == 1:
        surface_names = LEGACY_LIVERY_SURFACE_NAMES
        rotation_application = LEGACY_GROUP_ROTATION_APPLICATION
        group_rotation_policy = "legacy_selective"
        surface_name_source = (
            "legacy six-slot order inferred from root order, paired side geometry, and root transforms"
        )
    else:
        surface_names = LIVERY_SURFACE_NAMES
        rotation_application = FH6_GROUP_ROTATION_APPLICATION
        group_rotation_policy = "metadata_only"
        surface_name_source = "FH6 projection slot order validated by paired left/right surface data"
    design = LiveryGyvlParser(
        payload[gyvl_offset : gyvl_offset + gyvl_size],
        nested_group_rotation_application=rotation_application,
        group_rotation_policy=group_rotation_policy,
    ).parse_surfaces(surface_names, surface_name_source=surface_name_source)
    design.update(
        {
            "vlrc_format_version": format_version,
            "vlrc_layout": layout["name"],
            "lock_state": struct.unpack_from("<I", payload, 0x008)[0],
            "car_id": struct.unpack_from("<I", payload, 0x010)[0],
            "scope": "vinyl/decal geometry by projection surface",
            "preview_scope": "unclipped 2D surface-local geometry; final vehicle appearance requires car-specific mesh masks",
            "not_decoded": ["exact paint/material yrvl semantics; structural diagnostics are decoded separately"],
        }
    )
    return design
