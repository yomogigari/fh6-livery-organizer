#!/usr/bin/env python3
"""Read-only FH6 Vinyls.zip modelbin geometry extractor.

This module intentionally does not depend on the bundled 1,400 JSON resources to
parse the game data.  The bundled resources may be supplied separately only as a
validation oracle while the research prototype is being hardened.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import struct
import threading
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

TYPE_CODE_BASE = 0x100000
MODEL_NAME_RE = re.compile(r"^([A-Z]{1,2})[_-](\d+)\.modelbin$", re.IGNORECASE)

# Native resource family base words.  Info.Type in the historic geometry JSON is
# TYPE_CODE_BASE + the first slot word for the family; TypeIndex identifies slot.
FAMILY_BASE_WORD = {
    "Primitives": 101,
    "Gradient_Shapes": 201,
    "Stripes": 301,
    "Tears": 401,
    "Racing_Icons": 501,
    "Flames": 601,
    "Paint_Splats": 701,
    "Tribal": 801,
    "Nature": 901,
    "Upper_Letters_2": 1301,
    "Lower_Letters_2": 1401,
    "Upper_Letters_3": 1501,
    "Lower_Letters_3": 1601,
    "Upper_Letters_4": 1701,
    "Lower_Letters_4": 1801,
    "Upper_Letters_1": 1901,
    "Lower_Letters_1": 2001,
    "Community_Vinyls_1": 2101,
    "Community_Vinyls_2": 2201,
    "Community_Vinyls_3": 2301,
    "Community_Vinyls_4": 2401,
    "Upper_Letters_5": 2501,
    "Lower_Letters_5": 2601,
    "Upper_Letters_6": 2701,
    "Lower_Letters_6": 2801,
    "Upper_Letters_7": 2901,
    "Lower_Letters_7": 3001,
    "Upper_Letters_8": 3101,
    "Lower_Letters_8": 3201,
    "Upper_Letters_9": 3301,
    "Lower_Letters_9": 3401,
    "Upper_Letters_10": 3501,
    "Lower_Letters_10": 3601,
    "Upper_Letters_11": 3701,
    "Lower_Letters_11": 3801,
}

# Filename-family identity documented by the original game asset layout.  K/L
# single-letter sets were present in the legacy archive but were not user-visible
# vinyl families.  They are reported, not converted.
PREFIX_FAMILY = {
    "A": "Primitives",
    "B": "Gradient_Shapes",
    "C": "Stripes",
    "D": "Tears",
    "E": "Racing_Icons",
    "F": "Flames",
    "G": "Paint_Splats",
    "H": "Tribal",
    "I": "Nature",
    "M": "Upper_Letters_2",
    "N": "Lower_Letters_2",
    "O": "Upper_Letters_3",
    "P": "Lower_Letters_3",
    "Q": "Upper_Letters_4",
    "R": "Lower_Letters_4",
    "S": "Upper_Letters_1",
    "T": "Lower_Letters_1",
    "KK": "Upper_Letters_5",
    "LL": "Lower_Letters_5",
    "MM": "Upper_Letters_6",
    "NN": "Lower_Letters_6",
    "OO": "Upper_Letters_7",
    "PP": "Lower_Letters_7",
    "QQ": "Upper_Letters_8",
    "RR": "Lower_Letters_8",
    "SS": "Upper_Letters_9",
    "TT": "Lower_Letters_9",
    "UU": "Upper_Letters_10",
    "VV": "Lower_Letters_10",
    "WW": "Upper_Letters_11",
    "XX": "Lower_Letters_11",
}
RESERVED_PREFIXES = {"K", "L"}


SPECIAL_SHAPE_RESOURCES = {
    0x07D0: ("Lower_Letters_1", 1),
    0x0BB8: ("Lower_Letters_7", 1),
}

FACES_MARKER = bytes((0x02, 0x00, 0x01, 0x00, 0x39, 0x00, 0x00, 0x00))
VERTICES_MARKER = bytes((0x01, 0x00, 0x0D, 0x00, 0x00, 0x00))
UV_MARKER = bytes((0x04, 0x00, 0x25, 0x00, 0x00, 0x00))
VERTEX_DIVISOR = 510.0


class ModelbinGeometryError(ValueError):
    pass


@dataclass(frozen=True)
class ResourceIdentity:
    source_name: str
    prefix: str
    source_index: int
    family: str | None
    resource_index: int | None
    status: str


@dataclass(frozen=True)
class GeometryComparison:
    family: str
    resource_index: int
    reference_found: bool
    indices_equal: bool
    alpha_equal: bool
    vertex_count_equal: bool
    max_vertex_delta: float | None
    within_tolerance: bool
    triangle_equivalent: bool = False
    triangle_max_delta: float | None = None
    semantic_equivalent: bool = False
    classification: str = "unclassified"


def _f32(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or abs(value) > 3.402823466e38:
        raise ModelbinGeometryError(f"value is outside float32 range: {value!r}")
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError as exc:
        raise ModelbinGeometryError(f"value is outside float32 range: {value!r}") from exc


def _f32_array(values: "np.ndarray") -> "np.ndarray":
    """_f32 の配列版：同じ範囲の確かめと、同じ float32 への丸め（C の丸め）をした float64 の配列を返す。"""
    bad = ~np.isfinite(values) | (np.abs(values) > 3.402823466e38)
    if bad.any():
        raise ModelbinGeometryError(f"value is outside float32 range: {float(values[bad][0])!r}")
    return values.astype(np.float32).astype(np.float64)


def _need(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ModelbinGeometryError(f"{label} is outside modelbin bounds")


def _i32(data: bytes, offset: int, label: str) -> int:
    _need(data, offset, 4, label)
    return struct.unpack_from("<i", data, offset)[0]


def _u16(data: bytes, offset: int, label: str) -> int:
    _need(data, offset, 2, label)
    return struct.unpack_from("<H", data, offset)[0]


def _i16(data: bytes, offset: int, label: str) -> int:
    _need(data, offset, 2, label)
    return struct.unpack_from("<h", data, offset)[0]


def _float(data: bytes, offset: int, label: str) -> float:
    _need(data, offset, 4, label)
    return struct.unpack_from("<f", data, offset)[0]


def resolve_resource_identity(name: str) -> ResourceIdentity:
    base = Path(name.replace("\\", "/")).name
    m = MODEL_NAME_RE.match(base)
    if not m:
        return ResourceIdentity(base, "", 0, None, None, "unrecognized_name")
    prefix = m.group(1).upper()
    source_index = int(m.group(2))
    if prefix in RESERVED_PREFIXES:
        return ResourceIdentity(base, prefix, source_index, None, None, "reserved_legacy_family")
    if prefix == "U":
        if 1 <= source_index <= 40:
            return ResourceIdentity(base, prefix, source_index, "Community_Vinyls_1", source_index, "mapped")
        if 41 <= source_index <= 80:
            return ResourceIdentity(base, prefix, source_index, "Community_Vinyls_2", source_index - 40, "mapped")
        return ResourceIdentity(base, prefix, source_index, None, None, "unsupported_index")
    if prefix == "V":
        if 1 <= source_index <= 40:
            return ResourceIdentity(base, prefix, source_index, "Community_Vinyls_3", source_index, "mapped")
        if 51 <= source_index <= 90:
            return ResourceIdentity(base, prefix, source_index, "Community_Vinyls_4", source_index - 50, "mapped")
        return ResourceIdentity(base, prefix, source_index, None, None, "unsupported_index")
    family = PREFIX_FAMILY.get(prefix)
    if family is None:
        return ResourceIdentity(base, prefix, source_index, None, None, "unknown_prefix")
    if not 1 <= source_index <= 40:
        return ResourceIdentity(base, prefix, source_index, family, None, "unsupported_index")
    return ResourceIdentity(base, prefix, source_index, family, source_index, "mapped")


def _find_all(data: bytes, marker: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        at = data.find(marker, start)
        if at < 0:
            return offsets
        offsets.append(at)
        start = at + 1


def _candidate_face_blocks(data: bytes) -> list[tuple[int, int, float, float]]:
    candidates: list[tuple[int, int, float, float]] = []
    for faces_at in _find_all(data, FACES_MARKER):
        try:
            face_count = _i32(data, faces_at - 8, "face count")
            if face_count < 3 or face_count > 65535 or face_count % 3:
                continue
            index_at = faces_at + len(FACES_MARKER)
            _need(data, index_at, face_count * 2, "face indices")
            raw_scale_x = _float(data, faces_at - 41, "scale x")
            raw_scale_y = _float(data, faces_at - 37, "scale y")
            # The original Forza Vinyl Studio parser documents model scale in
            # the practical range (0, 2).  Reject implausible marker collisions
            # instead of allowing them to overflow float32 later.
            if not (math.isfinite(raw_scale_x) and math.isfinite(raw_scale_y)):
                continue
            if not (0.0 < raw_scale_x < 2.0 and 0.0 < raw_scale_y < 2.0):
                continue
            candidates.append((faces_at, face_count, raw_scale_x, raw_scale_y))
        except ModelbinGeometryError:
            continue
    return candidates


def _candidate_vertex_blocks(data: bytes) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for vertices_at in _find_all(data, VERTICES_MARKER):
        try:
            vertex_count = _i32(data, vertices_at - 10, "vertex count")
            if vertex_count < 3 or vertex_count > 65535:
                continue
            vertex_data_at = vertices_at + len(VERTICES_MARKER)
            _need(data, vertex_data_at, vertex_count * 8, "vertices")
            candidates.append((vertices_at, vertex_count))
        except ModelbinGeometryError:
            continue
    return candidates


def _candidate_uv_blocks(data: bytes) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for uv_at in _find_all(data, UV_MARKER):
        try:
            uv_count = _i32(data, uv_at - 10, "UV count")
            if uv_count < 3 or uv_count > 65535:
                continue
            alpha_at = uv_at + len(UV_MARKER) + 15
            _need(data, alpha_at, (uv_count - 1) * 16 + 1, "vertex alpha")
            candidates.append((uv_at, uv_count))
        except ModelbinGeometryError:
            continue
    return candidates


def _select_modelbin_layout(data: bytes) -> tuple[int, int, float, float, int, int, int]:
    faces = _candidate_face_blocks(data)
    vertices = _candidate_vertex_blocks(data)
    uvs = _candidate_uv_blocks(data)
    if not faces:
        raise ModelbinGeometryError("no plausible faces block found")
    if not vertices:
        raise ModelbinGeometryError("no plausible vertices block found")
    if not uvs:
        raise ModelbinGeometryError("no plausible UV block found")

    ranked: list[tuple[tuple[int, int, int, int], tuple[int, int, float, float, int, int, int]]] = []
    for faces_at, face_count, raw_scale_x, raw_scale_y in faces:
        index_at = faces_at + len(FACES_MARKER)
        for vertices_at, vertex_count in vertices:
            try:
                indices = [_u16(data, index_at + i * 2, f"face index {i}") for i in range(face_count)]
            except ModelbinGeometryError:
                continue
            if not indices or max(indices) >= vertex_count:
                continue
            for uv_at, uv_count in uvs:
                if uv_count != vertex_count:
                    continue
                # Prefer the natural FH5/FH6 vinyl layout ordering and nearby
                # blocks, while still accepting format padding differences.
                ordered_penalty = 0 if faces_at < vertices_at < uv_at else 1
                span = max(faces_at, vertices_at, uv_at) - min(faces_at, vertices_at, uv_at)
                marker_sum = faces_at + vertices_at + uv_at
                rank = (ordered_penalty, span, marker_sum, face_count)
                ranked.append((rank, (faces_at, face_count, raw_scale_x, raw_scale_y, vertices_at, vertex_count, uv_at)))
    if not ranked:
        raise ModelbinGeometryError(
            f"no self-consistent geometry layout found (faces={len(faces)}, vertices={len(vertices)}, uv={len(uvs)})"
        )
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]



def _burg_fourcc(data: bytes, off: int) -> str:
    _need(data, off, 4, "burG FourCC")
    return data[off:off + 4][::-1].decode("ascii", errors="replace")


def _parse_burg_chunks(data: bytes) -> list[dict[str, int | str]]:
    if len(data) < 20 or data[:4] != b"burG":
        raise ModelbinGeometryError("not an FH6 burG modelbin")
    count = struct.unpack_from("<I", data, 16)[0]
    if count <= 0 or count > 1024:
        raise ModelbinGeometryError(f"implausible burG chunk count: {count}")
    _need(data, 0x14, count * 24, "burG chunk table")
    chunks: list[dict[str, int | str]] = []
    pos = 0x14
    for _ in range(count):
        chunk = {
            "id": _burg_fourcc(data, pos),
            "flags": struct.unpack_from("<I", data, pos + 4)[0],
            "unk": struct.unpack_from("<I", data, pos + 8)[0],
            "off": struct.unpack_from("<I", data, pos + 12)[0],
            "size": struct.unpack_from("<I", data, pos + 16)[0],
            "usize": struct.unpack_from("<I", data, pos + 20)[0],
        }
        _need(data, int(chunk["off"]), int(chunk["size"]), f"{chunk['id']} chunk")
        chunks.append(chunk)
        pos += 24
    return chunks


def _read_burg_name_bbox(data: bytes, offset: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    _need(data, offset, 40, "Name+BBox metadata")
    if data[offset:offset + 4] != b"emaN" or data[offset + 8:offset + 12] != b"xoBB":
        raise ModelbinGeometryError("Mesh metadata does not point to Name+BBox")
    n = struct.unpack_from("<H", data, offset + 14)[0]
    if n < 8:
        raise ModelbinGeometryError(f"invalid Name+BBox size: {n}")
    bbox_off = offset + 8 + n
    _need(data, bbox_off, 24, "Name+BBox bounds")
    vals = struct.unpack_from("<6f", data, bbox_off)
    if not all(math.isfinite(v) for v in vals):
        raise ModelbinGeometryError("non-finite Name+BBox bounds")
    lo = (float(vals[0]), float(vals[1]), float(vals[2]))
    hi = (float(vals[3]), float(vals[4]), float(vals[5]))
    if hi[0] < lo[0] or hi[1] < lo[1] or hi[2] < lo[2]:
        raise ModelbinGeometryError("inverted Name+BBox bounds")
    return lo, hi


def parse_fh6_burg_geometry(data: bytes, identity: ResourceIdentity) -> dict[str, Any]:
    """Decode a vinyl mesh from FH6's native burG container.

    This path consumes only the user's local ``media/livery/Vinyls.zip``
    modelbin bytes.  Historic JSON resources are not an input.

    The two VerB chunks observed across the FH6 vinyl corpus are:
    - VerB[0], stride 8: quantized POSITION (x, y, z, w as int16)
    - VerB[1], stride 36: attributes; COLOR alpha is byte 35

    IndB stores uint16 triangle indices after its 16-byte header.  To preserve
    the historic preview coordinate convention, X/Y are reconstructed from the
    raw int16 position and the Mesh bounding-box span.  This is algebraically
    equivalent to the older ``raw / 510 * scale * 4`` convention when the old
    model scale is half the bounding-box span.
    """
    if identity.status != "mapped" or not identity.family or not identity.resource_index:
        raise ModelbinGeometryError(f"cannot parse unmapped resource identity: {identity}")

    chunks = _parse_burg_chunks(data)
    by_id: dict[str, list[dict[str, int | str]]] = {}
    for chunk in chunks:
        by_id.setdefault(str(chunk["id"]), []).append(chunk)
    for required in ("Mesh", "IndB", "VerB"):
        if required not in by_id:
            raise ModelbinGeometryError(f"FH6 modelbin has no {required} chunk")
    if len(by_id["VerB"]) < 2:
        raise ModelbinGeometryError("FH6 vinyl modelbin has fewer than two VerB chunks")

    mesh = by_id["Mesh"][0]
    bbox_min, bbox_max = _read_burg_name_bbox(data, int(mesh["unk"]))
    span_x = _f32(bbox_max[0] - bbox_min[0])
    span_y = _f32(bbox_max[1] - bbox_min[1])
    if span_x <= 0.0 or span_y <= 0.0:
        raise ModelbinGeometryError(f"degenerate vinyl bounding box: span=({span_x}, {span_y})")

    position_chunk = by_id["VerB"][0]
    poff = int(position_chunk["off"])
    _need(data, poff, 16, "position VerB header")
    vertex_count, data_size, stride, element_count, first_format = struct.unpack_from("<IIHHI", data, poff)
    if stride != 8 or element_count != 1 or first_format != 13:
        raise ModelbinGeometryError(
            f"unexpected position VerB layout: count={vertex_count}, stride={stride}, elements={element_count}, format={first_format}"
        )
    if data_size < vertex_count * stride:
        raise ModelbinGeometryError("position VerB data is shorter than declared vertex count")
    _need(data, poff + 16, vertex_count * stride, "position VerB data")

    attr_chunk = by_id["VerB"][1]
    aoff = int(attr_chunk["off"])
    _need(data, aoff, 16, "attribute VerB header")
    attr_count, attr_size, attr_stride, attr_elements, attr_format = struct.unpack_from("<IIHHI", data, aoff)
    if attr_count != vertex_count:
        raise ModelbinGeometryError(f"VerB vertex-count mismatch: position={vertex_count}, attributes={attr_count}")
    if attr_stride < 36 or attr_elements < 1:
        raise ModelbinGeometryError(f"unexpected attribute VerB layout: stride={attr_stride}, elements={attr_elements}")
    if attr_size < attr_count * attr_stride:
        raise ModelbinGeometryError("attribute VerB data is shorter than declared vertex count")
    _need(data, aoff + 16, attr_count * attr_stride, "attribute VerB data")

    ind_chunk = by_id["IndB"][0]
    ioff = int(ind_chunk["off"])
    _need(data, ioff, 16, "IndB header")
    index_count = struct.unpack_from("<I", data, ioff)[0]
    _need(data, ioff + 16, index_count * 2, "IndB indices")
    indices = list(struct.unpack_from(f"<{index_count}H", data, ioff + 16)) if index_count else []
    if indices and max(indices) >= vertex_count:
        raise ModelbinGeometryError(f"IndB references vertex {max(indices)} but VerB has {vertex_count}")

    # Match the established flat-preview coordinate convention, including
    # the Y inversion used by the historic extractor.
    # 全頂点をまとめて numpy で求める（2026-11-19）。式・演算の順・float32 への丸め（_f32 と同じ C の丸め）は
    # 以前の 1 頂点ずつの x = _f32(_f32(raw_x * span_x) / 255.0)、y = _f32(-_f32(raw_y * span_y) / 255.0) と同じ。
    if vertex_count:
        positions = np.frombuffer(data, dtype="<i2", count=vertex_count * 4, offset=poff + 16).reshape(vertex_count, 4)
        raw_x = positions[:, 0].astype(np.float64)
        raw_y = positions[:, 1].astype(np.float64)
        xs = _f32_array(_f32_array(raw_x * span_x) / 255.0)
        ys = _f32_array(-_f32_array(raw_y * span_y) / 255.0)
        vertices = [{"X": x, "Y": y} for x, y in zip(xs.tolist(), ys.tolist())]
        alpha = np.frombuffer(data, dtype=np.uint8, count=vertex_count * attr_stride,
                              offset=aoff + 16)[attr_stride - 1::attr_stride].tobytes()
    else:
        vertices = []
        alpha = b""

    return {
        "Info": {
            "Type": TYPE_CODE_BASE + FAMILY_BASE_WORD[identity.family],
            "TypeIndex": identity.resource_index,
        },
        "Vertices": vertices,
        "Indices": indices,
        "VerticesAlpha": base64.b64encode(bytes(alpha)).decode("ascii"),
    }


def parse_modelbin_geometry(data: bytes, identity: ResourceIdentity) -> dict[str, Any]:
    if data[:4] == b"burG":
        return parse_fh6_burg_geometry(data, identity)
    if identity.status != "mapped" or not identity.family or not identity.resource_index:
        raise ModelbinGeometryError(f"cannot parse unmapped resource identity: {identity}")

    faces_at, face_count, raw_scale_x, raw_scale_y, vertices_at, vertex_count, uv_at = _select_modelbin_layout(data)
    index_at = faces_at + len(FACES_MARKER)
    indices = [_u16(data, index_at + i * 2, f"face index {i}") for i in range(face_count)]

    vertex_data_at = vertices_at + len(VERTICES_MARKER)
    scale_x = _f32(raw_scale_x * 4.0)
    scale_y = _f32(raw_scale_y * 4.0)

    vertices: list[dict[str, float]] = []
    for i in range(vertex_count):
        at = vertex_data_at + i * 8
        raw_x = _i16(data, at, f"vertex {i} x")
        raw_y = _i16(data, at + 2, f"vertex {i} y")
        x = _f32(_f32(raw_x / VERTEX_DIVISOR) * scale_x)
        y = _f32(_f32(-(raw_y / VERTEX_DIVISOR)) * scale_y)
        vertices.append({"X": x, "Y": y})

    alpha_at = uv_at + len(UV_MARKER) + 15
    alpha = bytes(data[alpha_at + i * 16] for i in range(vertex_count))

    return {
        "Info": {
            "Type": TYPE_CODE_BASE + FAMILY_BASE_WORD[identity.family],
            "TypeIndex": identity.resource_index,
        },
        "Vertices": vertices,
        "Indices": indices,
        "VerticesAlpha": base64.b64encode(alpha).decode("ascii"),
    }


def compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decoded_alpha(payload: dict[str, Any], vertex_count: int) -> bytes:
    encoded = payload.get("VerticesAlpha")
    try:
        data = base64.b64decode(encoded, validate=True) if encoded else b""
    except (TypeError, ValueError):
        data = b""
    return data if len(data) == vertex_count else bytes([255]) * vertex_count


def _triangle_records(payload: dict[str, Any]) -> list[tuple[tuple[float, float, int], ...]]:
    vertices = list(payload.get("Vertices") or [])
    indices = [int(value) for value in (payload.get("Indices") or [])]
    alpha = _decoded_alpha(payload, len(vertices))
    triangles: list[tuple[tuple[float, float, int], ...]] = []
    for offset in range(0, len(indices) - 2, 3):
        tri: list[tuple[float, float, int]] = []
        valid = True
        for index in indices[offset:offset + 3]:
            if index < 0 or index >= len(vertices):
                valid = False
                break
            vertex = vertices[index]
            tri.append((float(vertex["X"]), float(vertex["Y"]), int(alpha[index])))
        if valid and len(tri) == 3:
            triangles.append(tuple(tri))
    return triangles


_TRIANGLE_PERMUTATIONS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))


def _triangle_pair_delta(
    actual: tuple[tuple[float, float, int], ...],
    expected: tuple[tuple[float, float, int], ...],
) -> float:
    best = math.inf
    for permutation in _TRIANGLE_PERMUTATIONS:
        if any(actual[i][2] != expected[permutation[i]][2] for i in range(3)):
            continue
        delta = 0.0
        for i in range(3):
            other = expected[permutation[i]]
            delta = max(delta, abs(actual[i][0] - other[0]), abs(actual[i][1] - other[1]))
        best = min(best, delta)
    return best


def triangle_geometry_equivalent(
    payload: dict[str, Any],
    reference: dict[str, Any],
    *,
    tolerance: float = 1e-4,
) -> tuple[bool, float | None]:
    """Compare rendered triangle soup independent of vertex/index ordering.

    FH6 can repack or reorder otherwise identical vertices and triangles.  The
    historic FH5-derived JSON therefore is not a reliable byte/order oracle.
    This comparison keeps per-corner alpha authoritative but ignores vertex
    numbering, triangle ordering, and winding.
    """
    actual_triangles = _triangle_records(payload)
    expected_triangles = _triangle_records(reference)
    if len(actual_triangles) != len(expected_triangles):
        return False, None
    if not actual_triangles:
        return True, 0.0

    cell = max(float(tolerance) * 8.0, 1e-12)
    buckets: dict[tuple[int, int, tuple[int, int, int]], list[int]] = {}
    for index, triangle in enumerate(expected_triangles):
        center_x = sum(vertex[0] for vertex in triangle) / 3.0
        center_y = sum(vertex[1] for vertex in triangle) / 3.0
        key = (
            math.floor(center_x / cell),
            math.floor(center_y / cell),
            tuple(sorted(vertex[2] for vertex in triangle)),
        )
        buckets.setdefault(key, []).append(index)

    work: list[tuple[int, tuple[tuple[float, float, int], ...], list[int]]] = []
    for triangle in actual_triangles:
        center_x = sum(vertex[0] for vertex in triangle) / 3.0
        center_y = sum(vertex[1] for vertex in triangle) / 3.0
        bx = math.floor(center_x / cell)
        by = math.floor(center_y / cell)
        alpha_key = tuple(sorted(vertex[2] for vertex in triangle))
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(buckets.get((bx + dx, by + dy, alpha_key), ()))
        work.append((len(candidates), triangle, candidates))

    # Match constrained triangles first; this avoids duplicate/coincident
    # vertices making a greedy assignment choose a visually equivalent but
    # multiplicity-wrong triangle too early.
    work.sort(key=lambda item: item[0])
    unused = set(range(len(expected_triangles)))
    maximum_delta = 0.0
    for _candidate_count, triangle, candidates in work:
        best_index = None
        best_delta = math.inf
        for candidate in candidates:
            if candidate not in unused:
                continue
            delta = _triangle_pair_delta(triangle, expected_triangles[candidate])
            if delta < best_delta:
                best_delta = delta
                best_index = candidate
        if best_index is None or best_delta > tolerance:
            return False, best_delta if math.isfinite(best_delta) else None
        unused.remove(best_index)
        maximum_delta = max(maximum_delta, best_delta)
    return not unused, maximum_delta


def compare_geometry(
    payload: dict[str, Any],
    reference_path: Path,
    *,
    tolerance: float = 1e-4,
    minor_delta_threshold: float = 0.01,
) -> GeometryComparison:
    family = next((name for name, word in FAMILY_BASE_WORD.items() if TYPE_CODE_BASE + word == int(payload["Info"]["Type"])), "")
    index = int(payload["Info"]["TypeIndex"])
    if not reference_path.is_file():
        return GeometryComparison(family, index, False, False, False, False, None, False, classification="reference_missing")
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    indices_equal = list(payload.get("Indices", [])) == list(reference.get("Indices", []))
    alpha_equal = payload.get("VerticesAlpha") == reference.get("VerticesAlpha")
    actual_vertices = payload.get("Vertices", [])
    expected_vertices = reference.get("Vertices", [])
    vertex_count_equal = len(actual_vertices) == len(expected_vertices)
    max_delta = None
    if vertex_count_equal:
        max_delta = 0.0
        for a, b in zip(actual_vertices, expected_vertices):
            max_delta = max(max_delta, abs(float(a["X"]) - float(b["X"])), abs(float(a["Y"]) - float(b["Y"])))
    within = bool(indices_equal and alpha_equal and vertex_count_equal and max_delta is not None and max_delta <= tolerance)
    if within:
        return GeometryComparison(
            family, index, True, indices_equal, alpha_equal, vertex_count_equal, max_delta, True,
            triangle_equivalent=True, triangle_max_delta=max_delta, semantic_equivalent=True, classification="exact",
        )

    triangle_equivalent, triangle_delta = triangle_geometry_equivalent(payload, reference, tolerance=tolerance)
    if triangle_equivalent:
        classification = "representation_equivalent"
        semantic_equivalent = True
    elif indices_equal and alpha_equal and vertex_count_equal and max_delta is not None and max_delta <= minor_delta_threshold:
        classification = "minor_source_delta"
        semantic_equivalent = False
    else:
        classification = "source_geometry_delta"
        semantic_equivalent = False
    return GeometryComparison(
        family, index, True, indices_equal, alpha_equal, vertex_count_equal, max_delta, False,
        triangle_equivalent=triangle_equivalent, triangle_max_delta=triangle_delta,
        semantic_equivalent=semantic_equivalent, classification=classification,
    )



def resource_key_for_shape_word(word: int) -> tuple[str, int] | None:
    """FH6 の shape word をローカル Vinyls resource の family/index へ変換する。"""
    value = int(word) & 0xFFFF
    special = SPECIAL_SHAPE_RESOURCES.get(value)
    if special is not None:
        return special
    candidates: list[tuple[int, str, int]] = []
    for family, base in FAMILY_BASE_WORD.items():
        index = value - int(base) + 1
        if 1 <= index <= 80:
            candidates.append((int(base), family, index))
    if not candidates:
        return None
    _base, family, index = max(candidates, key=lambda item: item[0])
    return family, index


def extract_selected_zip(
    zip_path: Path,
    output_root: Path,
    shape_words: Iterable[int],
    *,
    payloads_out: dict[tuple[str, int], dict[str, Any]] | None = None,
    write_files: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """必要な shape だけを FH6 Vinyls.zip から一時 resource root へ展開する。

    全 1,400 resource の永続 cache は作らない。GPU parity 診断など、
    利用中の C_livery が参照する shape だけを read-only で復号する。
    payloads_out を渡すと、復号した結果を (family, index) ごとにそこへも入れる。write_files=False なら
    ファイルに書かない（製品の GPU の入力は、一時ファイルに書いて読み直さずにメモリで受け渡す。2026-11-19）。
    """
    zip_path = zip_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"FH6 Vinyls.zip が見つかりません: {zip_path}")

    requested_words = sorted({int(value) & 0xFFFF for value in shape_words if int(value) & 0xFFFF})
    requested: dict[tuple[str, int], list[int]] = {}
    unsupported: list[int] = []
    for word in requested_words:
        key = resource_key_for_shape_word(word)
        if key is None:
            unsupported.append(word)
            continue
        requested.setdefault(key, []).append(word)
    if unsupported:
        values = ", ".join(f"0x{word:04X}" for word in unsupported[:16])
        raise ModelbinGeometryError(f"Vinyls.zip の resource へ対応付けできない shape word があります: {values}")

    vinyl_root = output_root / "Vinyls"
    vinyl_root.mkdir(parents=True, exist_ok=True)
    selected: dict[tuple[str, int], tuple[str, ResourceIdentity]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        mapped = _mapped_modelbins(zf)
        for key in requested:
            if key in mapped:
                selected[key] = mapped[key]
        missing = [key for key in requested if key not in selected]
        if missing:
            values = ", ".join(f"{family}/{index}" for family, index in missing[:16])
            raise FileNotFoundError(f"FH6 Vinyls.zip に必要な vinyl geometry がありません: {values}")

        parsed = 0
        for key in sorted(requested):
            name, identity = selected[key]
            try:
                payload = parse_modelbin_geometry(zf.read(name), identity)
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, ModelbinGeometryError) as exc:
                raise ModelbinGeometryError(f"vinyl geometry を復号できません: {name}: {exc}") from exc
            if payloads_out is not None:
                payloads_out[(str(identity.family), int(identity.resource_index))] = payload
            if write_files:
                family_dir = vinyl_root / str(identity.family)
                family_dir.mkdir(parents=True, exist_ok=True)
                (family_dir / str(identity.resource_index)).write_text(compact_json(payload), encoding="utf-8")
            parsed += 1

    report = {
        "format": "lo4fh6_fh6_vinyl_selected_geometry_v1",
        "read_only": True,
        "source_archive": str(zip_path),
        "requested_shape_word_count": len(requested_words),
        "selected_resource_count": len(requested),
        "parsed_resource_count": parsed,
        "shape_words": requested_words,
        "persistent_cache_created": False,
    }
    return vinyl_root, report

def iter_modelbin_names(zf: zipfile.ZipFile) -> Iterable[str]:
    return sorted((n for n in zf.namelist() if n.casefold().endswith(".modelbin")), key=str.casefold)


# 開いた Vinyls.zip ごとの、(family, index) から名前への対応（同じプロセスの中だけ。2026-11-20）。
_MAPPED_MODELBINS: OrderedDict[tuple[int, int, int, int], dict[tuple[str, int], tuple[str, ResourceIdentity]]] = OrderedDict()
_MAPPED_MODELBINS_LIMIT = 4
_MAPPED_MODELBINS_LOCK = threading.Lock()


def _mapped_modelbins(zf: zipfile.ZipFile) -> dict[tuple[str, int], tuple[str, ResourceIdentity]]:
    """ZIP の中の modelbin を iter_modelbin_names の順に見て、(family, index) ごとに最初の名前を選ぶ。

    以前の extract_selected_zip の選び方と同じ（名前を大文字・小文字を区別せずに並べ、mapped の資源の最初の物）。
    開いた ZIP の識別（機器・番号・大きさ・更新日時。開いたファイルから読む）が同じなら、同じプロセスの中で
    覚えた対応を返す（差し替えのたびに約 1,400 個の名前を並べ直して解いていた）。返す辞書は変えないこと。
    """
    identity: tuple[int, int, int, int] | None = None
    try:
        stat = os.fstat(zf.fp.fileno())
        if stat.st_ino:
            identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except (AttributeError, OSError, ValueError):
        identity = None
    if identity is not None:
        with _MAPPED_MODELBINS_LOCK:
            found = _MAPPED_MODELBINS.get(identity)
            if found is not None:
                _MAPPED_MODELBINS.move_to_end(identity)
                return found
    mapped: dict[tuple[str, int], tuple[str, ResourceIdentity]] = {}
    for name in iter_modelbin_names(zf):
        resource = resolve_resource_identity(name)
        if resource.status != "mapped" or resource.family is None or resource.resource_index is None:
            continue
        mapped.setdefault((resource.family, int(resource.resource_index)), (name, resource))
    if identity is not None:
        with _MAPPED_MODELBINS_LOCK:
            _MAPPED_MODELBINS[identity] = mapped
            while len(_MAPPED_MODELBINS) > _MAPPED_MODELBINS_LIMIT:
                _MAPPED_MODELBINS.popitem(last=False)
    return mapped


def extract_zip(
    zip_path: Path,
    output_root: Path,
    *,
    reference_root: Path | None = None,
    tolerance: float = 1e-4,
) -> dict[str, Any]:
    zip_path = zip_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    vinyl_root = output_root / "Vinyls"
    vinyl_root.mkdir(parents=True, exist_ok=True)

    mapped = 0
    written = 0
    status_counts: dict[str, int] = {}
    prefix_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    comparisons: list[GeometryComparison] = []

    with zipfile.ZipFile(zip_path) as zf:
        names = list(iter_modelbin_names(zf))
        for name in names:
            identity = resolve_resource_identity(name)
            status_counts[identity.status] = status_counts.get(identity.status, 0) + 1
            prefix_counts[identity.prefix or "(unrecognized)"] = prefix_counts.get(identity.prefix or "(unrecognized)", 0) + 1
            if identity.status != "mapped":
                skipped.append(asdict(identity))
                continue
            mapped += 1
            try:
                payload = parse_modelbin_geometry(zf.read(name), identity)
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, ModelbinGeometryError) as exc:
                errors.append({"source_name": name, "error": str(exc)})
                continue
            family_dir = vinyl_root / str(identity.family)
            family_dir.mkdir(parents=True, exist_ok=True)
            target = family_dir / str(identity.resource_index)
            target.write_text(compact_json(payload), encoding="utf-8")
            written += 1
            if reference_root is not None:
                comparisons.append(compare_geometry(payload, reference_root / str(identity.family) / str(identity.resource_index), tolerance=tolerance))

    comparison_summary: dict[str, Any] | None = None
    if reference_root is not None:
        found = [c for c in comparisons if c.reference_found]
        classification_counts: dict[str, int] = {}
        for comparison in comparisons:
            classification_counts[comparison.classification] = classification_counts.get(comparison.classification, 0) + 1
        semantic_matches = sum(c.semantic_equivalent for c in comparisons)
        comparison_summary = {
            "reference_root": str(reference_root),
            "compared": len(comparisons),
            "reference_found": len(found),
            "within_tolerance": sum(c.within_tolerance for c in comparisons),
            "representation_equivalent": sum(c.classification == "representation_equivalent" for c in comparisons),
            "semantic_equivalent": semantic_matches,
            "semantic_mismatch_count": len(comparisons) - semantic_matches,
            "classification_counts": dict(sorted(classification_counts.items())),
            "mismatch_count": sum(not c.within_tolerance for c in comparisons),
            "max_vertex_delta": max((c.max_vertex_delta or 0.0 for c in found), default=None),
            "max_equivalent_triangle_delta": max((c.triangle_max_delta or 0.0 for c in comparisons if c.semantic_equivalent), default=None),
            "mismatches": [asdict(c) for c in comparisons if not c.semantic_equivalent][:200],
        }

    report = {
        "format": "lo4fh6_fh6_vinyl_local_geometry_v1",
        "mode": "READ ONLY GAME SOURCE / LOCAL OUTPUT ONLY",
        "source_zip": str(zip_path),
        "modelbin_count": sum(status_counts.values()),
        "mapped_count": mapped,
        "written_count": written,
        "status_counts": dict(sorted(status_counts.items())),
        "prefix_counts": dict(sorted(prefix_counts.items())),
        "parse_error_count": len(errors),
        "parse_errors": errors[:200],
        "skipped_count": len(skipped),
        "skipped_sample": skipped[:200],
        "comparison": comparison_summary,
    }
    (output_root / "fh6-vinyl-local-geometry-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
