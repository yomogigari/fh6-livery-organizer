from __future__ import annotations

"""Build a compact shared geometry pack for the experimental GPU livery path.

The pack contains only geometry reconstructed from a user-local Vinyls cache at
runtime. No game-derived geometry is bundled with the research ZIP. r291 also
allows deterministic fallback geometry for unit tests and architecture probes;
normal game-facing use should request strict local assets.
"""

import base64
import json
import math
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Hashable, Iterable, Mapping

import numpy as np

from fh_livery_preview_core.livery_preview import resource_location, resource_location_key

MAGIC = b"LO4GVG1\0"
VERSION = 1
ENTRY_BYTES = 24
VERTEX_BYTES = 12
FLAG_FALLBACK = 0x0001
FLAG_VERTEX_ALPHA = 0x0002
FLAG_LOCAL_ASSET = 0x0004

# 同じプロセスの中で、Vinyls.zip の資源 1 つから作った形の束の部品を覚える（2026-11-20）。
# - 鍵は (Vinyls.zip の識別, (family, index))。部品は (flags, 頂点の数, 索引の数, 頂点のバイト列, 索引のバイト列,
#   落とした三角形の数 3 つ) で、変えられない値だけ。形の束の 1 資源あたり平均 約 11 KB（解いた途中の Python の形は
#   約 150 KB あるので、そちらは覚えない）。
# - ペイントを切り替えると、使う資源の約 9 割は前のペイントで使った物（実際のペイント 77 件を順に切り替えたとき）。
# - 合計のバイト数に上限を置き、古く使った物から捨てる。ディスクには書かない。r364 の「常駐の Vinyl 全 1,400 種の
#   キャッシュを使わない・形の束を永続保存しない」はそのまま（使った資源だけ・このプロセスの中だけ）。
REMEMBERED_GEOMETRY_LIMIT_BYTES = 32 * 1024 * 1024
_REMEMBERED_GEOMETRY: OrderedDict[tuple[Hashable, tuple[str, int]], tuple] = OrderedDict()
_REMEMBERED_GEOMETRY_BYTES = 0
_REMEMBERED_GEOMETRY_LOCK = threading.Lock()


def _pieces_bytes(pieces: tuple) -> int:
    return len(pieces[3]) + len(pieces[4]) + 256


def remembered_geometry(scope: Hashable, keys: Iterable[tuple[str, int]]) -> dict[tuple[str, int], tuple]:
    """scope（Vinyls.zip の識別）で覚えた部品のうち、keys にある資源の物。"""
    found: dict[tuple[str, int], tuple] = {}
    with _REMEMBERED_GEOMETRY_LOCK:
        for key in keys:
            memo_key = (scope, key)
            pieces = _REMEMBERED_GEOMETRY.get(memo_key)
            if pieces is not None:
                _REMEMBERED_GEOMETRY.move_to_end(memo_key)
                found[key] = pieces
    return found


def remember_geometry(scope: Hashable, pieces_by_key: Mapping[tuple[str, int], tuple]) -> None:
    """build_gpu_geometry_pack の pieces_out を、scope（Vinyls.zip の識別）で覚える。"""
    global _REMEMBERED_GEOMETRY_BYTES
    with _REMEMBERED_GEOMETRY_LOCK:
        for key, pieces in pieces_by_key.items():
            memo_key = (scope, key)
            previous = _REMEMBERED_GEOMETRY.pop(memo_key, None)
            if previous is not None:
                _REMEMBERED_GEOMETRY_BYTES -= _pieces_bytes(previous)
            _REMEMBERED_GEOMETRY[memo_key] = pieces
            _REMEMBERED_GEOMETRY_BYTES += _pieces_bytes(pieces)
        while _REMEMBERED_GEOMETRY_BYTES > REMEMBERED_GEOMETRY_LIMIT_BYTES and _REMEMBERED_GEOMETRY:
            _memo_key, previous = _REMEMBERED_GEOMETRY.popitem(last=False)
            _REMEMBERED_GEOMETRY_BYTES -= _pieces_bytes(previous)


def forget_geometry() -> None:
    """覚えた部品を全部捨てる（試験用）。"""
    global _REMEMBERED_GEOMETRY_BYTES
    with _REMEMBERED_GEOMETRY_LOCK:
        _REMEMBERED_GEOMETRY.clear()
        _REMEMBERED_GEOMETRY_BYTES = 0


def _fan_indices(count: int) -> list[int]:
    if count < 3:
        return []
    out: list[int] = []
    for index in range(1, count - 1):
        out.extend((0, index, index + 1))
    return out


def _fallback_shape(word: int) -> tuple[list[tuple[float, float, int]], list[int]]:
    # Match json_preview_renderer._fallback_triangles used by the current
    # canonical section renderer: the first primitive is a rectangle; unknown
    # words use the deterministic 32-point circle fallback.
    if (int(word) & 0xFFFF) == 0x0065:
        points = [(-64.0, -64.0), (64.0, -64.0), (64.0, 64.0), (-64.0, 64.0)]
    else:
        points = [
            (math.cos(math.tau * step / 32.0) * 64.0, math.sin(math.tau * step / 32.0) * 64.0)
            for step in range(32)
        ]
    return [(x, y, 255) for x, y in points], _fan_indices(len(points))


def _local_shape(path: Path) -> tuple[dict[str, Any], list[int], dict[str, int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_vertices = payload.get("Vertices") or []
        raw_indices = payload.get("Indices") or []
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"cannot read vinyl geometry {path}: {exc}") from exc
    return _shape_from_payload(payload, raw_vertices, raw_indices, path)


def _payload_shape(payload: dict[str, Any], label: object) -> tuple[dict[str, Any], list[int], dict[str, int]]:
    """メモリで受け取った復号の結果（extract_selected_zip の payloads_out）から、_local_shape と同じものを作る。"""
    try:
        raw_vertices = payload.get("Vertices") or []
        raw_indices = payload.get("Indices") or []
    except TypeError as exc:
        raise ValueError(f"cannot read vinyl geometry {label}: {exc}") from exc
    return _shape_from_payload(payload, raw_vertices, raw_indices, label)


def _shape_from_payload(payload: dict[str, Any], raw_vertices: object, raw_indices: object,
                        label: object) -> tuple[dict[str, Any], list[int], dict[str, int]]:
    """頂点（中心へ寄せた x・y と不透明度の配列）と、描く三角形の索引を作る。

    2026-11-19：頂点と三角形の 1 つずつの Python の繰り返しを numpy の配列の計算にした。
    中心の求め方・三角形の符号付き面積の式と演算の順・判定の順（索引の範囲外 → 面積 ≤ 1e-9 →
    3 頂点とも透明）は以前と同じで、同じ値・同じ件数になる。
    """
    path = label
    if not isinstance(raw_vertices, list) or not raw_vertices:
        raise ValueError(f"vinyl geometry has no vertices: {path}")
    try:
        encoded_alpha = payload.get("VerticesAlpha")
        alpha = base64.b64decode(encoded_alpha, validate=True) if encoded_alpha else b""
    except (TypeError, ValueError) as exc:
        raise ValueError(f"vinyl geometry has invalid VerticesAlpha: {path}") from exc
    if len(alpha) != len(raw_vertices):
        alpha = bytes([255]) * len(raw_vertices)

    try:
        xs = np.array([float(raw["X"]) for raw in raw_vertices], dtype=np.float64)
        ys = np.array([float(raw["Y"]) for raw in raw_vertices], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"vinyl geometry has an invalid vertex: {path}") from exc
    if not (np.isfinite(xs).all() and np.isfinite(ys).all()):
        raise ValueError(f"vinyl geometry has a non-finite vertex: {path}")
    alphas = np.frombuffer(bytes(alpha), dtype=np.uint8)

    # r367: match the installed-Vinyl front-face contract used by the canonical
    # renderer.  FH6 resources can contain reverse/degenerate triangles that are
    # not part of the drawable face set.  Feeding those triangles to WebGL with
    # culling disabled can overwrite otherwise-opaque artwork without producing
    # a large alpha difference, which is exactly the failure seen on dense side
    # liveries.  Centre the resource exactly once before placement, then keep only
    # positive-area triangles with at least one non-zero-alpha vertex.
    center_x = (float(xs.min()) + float(xs.max())) / 2.0
    center_y = (float(ys.min()) + float(ys.max())) / 2.0
    vx = xs - center_x
    vy = ys - center_y
    vertex_count = len(xs)

    indices: list[int]
    reverse_or_degenerate = 0
    transparent_triangles = 0
    invalid_triangles = 0
    if isinstance(raw_indices, list) and raw_indices:
        triangle_count = len(range(0, len(raw_indices) - 2, 3))
        try:
            flat = np.array([int(value) for value in raw_indices[:triangle_count * 3]], dtype=np.int64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"vinyl geometry has an invalid triangle index: {path}") from exc
        tris = flat.reshape(triangle_count, 3)
        valid = ((tris >= 0) & (tris < vertex_count)).all(axis=1)
        invalid_triangles = int((~valid).sum())
        safe = np.where(valid[:, None], tris, 0)
        x0, x1, x2 = vx[safe[:, 0]], vx[safe[:, 1]], vx[safe[:, 2]]
        y0, y1, y2 = vy[safe[:, 0]], vy[safe[:, 1]], vy[safe[:, 2]]
        area2 = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        degenerate = valid & (area2 <= 1e-9)
        reverse_or_degenerate = int(degenerate.sum())
        opaque = alphas[safe].max(axis=1) > 0
        transparent = valid & ~degenerate & ~opaque
        transparent_triangles = int(transparent.sum())
        keep = valid & ~degenerate & opaque
        indices = tris[keep].reshape(-1).tolist()
    else:
        indices = _fan_indices(vertex_count)
    if not indices:
        raise ValueError(f"vinyl geometry has no drawable triangles: {path}")
    return {"x": vx, "y": vy, "alpha": alphas}, indices, {
        "reverse_or_degenerate_triangles_skipped": reverse_or_degenerate,
        "transparent_triangles_skipped": transparent_triangles,
        "invalid_triangles_skipped": invalid_triangles,
    }


_VERTEX_DTYPE = np.dtype([("x", "<f4"), ("y", "<f4"), ("alpha", "u1"), ("pad", "V3")])


def _vertex_bytes(vertices: dict[str, Any]) -> bytes:
    """struct.pack("<ffB3x", x, y, alpha) を全頂点つなげたものと同じバイト列。"""
    packed = np.zeros(len(vertices["x"]), dtype=_VERTEX_DTYPE)
    packed["x"] = vertices["x"]
    packed["y"] = vertices["y"]
    packed["alpha"] = vertices["alpha"]
    return packed.tobytes()


def build_gpu_geometry_pack(
    resource_root: Path | str,
    shape_words: Iterable[int],
    *,
    strict_assets: bool = True,
    payloads: dict[tuple[str, int], dict[str, Any]] | None = None,
    remembered: Mapping[tuple[str, int], tuple] | None = None,
    pieces_out: dict[tuple[str, int], tuple] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """payloads（extract_selected_zip の payloads_out）を渡すと、resource_root のファイルを読まずにそれを使う。

    どの図形の番号がどの (family, index) を使うかは、ファイルのときと同じ resource_location の決まりで引く。
    remembered（remembered_geometry の結果）にある資源は、復号の結果の代わりに覚えた部品を使う。pieces_out を
    渡すと、payloads から作った資源の部品をそこへ入れる（remember_geometry に渡す）。どちらも、できるバイト列と
    要約を変えない（2026-11-20）。
    """
    root = Path(resource_root).expanduser().resolve()
    if strict_assets and payloads is None and not root.is_dir():
        raise FileNotFoundError(f"vinyl resource root not found: {root}")

    entries: list[dict[str, Any]] = []
    for raw_word in sorted({int(value) & 0xFFFF for value in shape_words if int(value) & 0xFFFF}):
        if remembered:
            remembered_key = resource_location_key(raw_word)
            pieces = remembered.get(remembered_key) if remembered_key is not None else None
            if pieces is not None:
                flags, vertex_count, index_count, vertex_data, index_data, skipped = pieces
                entries.append({
                    "word": raw_word,
                    "flags": flags,
                    "vertex_count": vertex_count,
                    "index_count": index_count,
                    "vertex_data": vertex_data,
                    "index_data": index_data,
                    "triangle_filter": {
                        "reverse_or_degenerate_triangles_skipped": skipped[0],
                        "transparent_triangles_skipped": skipped[1],
                        "invalid_triangles_skipped": skipped[2],
                    },
                })
                continue
        payload = None
        path = None
        if payloads is not None:
            key = resource_location_key(raw_word)
            payload = payloads.get(key) if key is not None else None
        else:
            path = resource_location(root, raw_word) if root.is_dir() else None
        if payload is None and path is None:
            if strict_assets:
                raise FileNotFoundError(f"local FH6 vinyl geometry is missing for shape word 0x{raw_word:04X}")
            points, indices = _fallback_shape(raw_word)
            vertices = {"x": np.array([x for x, _y, _a in points], dtype=np.float64),
                        "y": np.array([y for _x, y, _a in points], dtype=np.float64),
                        "alpha": np.array([a for _x, _y, a in points], dtype=np.uint8)}
            triangle_filter = {
                "reverse_or_degenerate_triangles_skipped": 0,
                "transparent_triangles_skipped": 0,
                "invalid_triangles_skipped": 0,
            }
            flags = FLAG_FALLBACK
        else:
            if payload is not None:
                key = resource_location_key(raw_word)
                vertices, indices, triangle_filter = _payload_shape(payload, root / key[0] / str(key[1]))
            else:
                vertices, indices, triangle_filter = _local_shape(path)
            flags = FLAG_LOCAL_ASSET
        if bool((vertices["alpha"] != 255).any()):
            flags |= FLAG_VERTEX_ALPHA
        vertex_data = _vertex_bytes(vertices)
        index_data = np.asarray(indices, dtype="<u4").tobytes() if indices else b""
        entries.append({
            "word": raw_word,
            "flags": flags,
            "vertex_count": len(vertices["x"]),
            "index_count": len(indices),
            "vertex_data": vertex_data,
            "index_data": index_data,
            "triangle_filter": triangle_filter,
        })
        if pieces_out is not None and payload is not None:
            pieces_out[key] = (flags, len(vertices["x"]), len(indices), vertex_data, index_data, (
                int(triangle_filter["reverse_or_degenerate_triangles_skipped"]),
                int(triangle_filter["transparent_triangles_skipped"]),
                int(triangle_filter["invalid_triangles_skipped"]),
            ))

    header_size = struct.calcsize("<8sIII")
    directory_size = len(entries) * ENTRY_BYTES
    cursor = header_size + directory_size
    vertex_blocks: list[bytes] = []
    index_blocks: list[bytes] = []
    for entry in entries:
        vertex_data = entry["vertex_data"]
        entry["vertex_offset"] = cursor
        entry["vertex_bytes"] = len(vertex_data)
        cursor += len(vertex_data)
        vertex_blocks.append(vertex_data)
    for entry in entries:
        index_data = entry["index_data"]
        entry["index_offset"] = cursor
        entry["index_bytes"] = len(index_data)
        cursor += len(index_data)
        index_blocks.append(index_data)

    header = struct.pack("<8sIII", MAGIC, VERSION, len(entries), ENTRY_BYTES)
    directory = b"".join(
        struct.pack(
            "<HHIIIII",
            int(entry["word"]),
            int(entry["flags"]),
            int(entry["vertex_count"]),
            int(entry["index_count"]),
            int(entry["vertex_offset"]),
            int(entry["index_offset"]),
            0,
        )
        for entry in entries
    )
    payload = header + directory + b"".join(vertex_blocks) + b"".join(index_blocks)
    summary = {
        "format": "lo4fh6_gpu_vector_geometry_probe_v1",
        "read_only": True,
        "version": VERSION,
        "entry_count": len(entries),
        "pack_bytes": len(payload),
        "vertex_count": sum(int(entry["vertex_count"]) for entry in entries),
        "index_count": sum(int(entry["index_count"]) for entry in entries),
        "local_asset_entry_count": sum(bool(entry["flags"] & FLAG_LOCAL_ASSET) for entry in entries),
        "fallback_entry_count": sum(bool(entry["flags"] & FLAG_FALLBACK) for entry in entries),
        "vertex_alpha_entry_count": sum(bool(entry["flags"] & FLAG_VERTEX_ALPHA) for entry in entries),
        "reverse_or_degenerate_triangles_skipped": sum(
            int(entry["triangle_filter"].get("reverse_or_degenerate_triangles_skipped") or 0) for entry in entries
        ),
        "transparent_triangles_skipped": sum(
            int(entry["triangle_filter"].get("transparent_triangles_skipped") or 0) for entry in entries
        ),
        "invalid_triangles_skipped": sum(
            int(entry["triangle_filter"].get("invalid_triangles_skipped") or 0) for entry in entries
        ),
        "geometry_contract": "centered-positive-front-face-v1",
        "shape_words": [int(entry["word"]) for entry in entries],
        "redistribution_policy": "pack is generated from user-local FH6 Vinyls geometry and must not be bundled or redistributed",
    }
    return payload, summary


def parse_gpu_geometry_pack(payload: bytes) -> dict[int, dict[str, Any]]:
    """Reference parser used by tests/probes; Viewer has an independent JS parser."""
    header_size = struct.calcsize("<8sIII")
    if len(payload) < header_size:
        raise ValueError("GPU geometry pack is truncated")
    magic, version, count, entry_bytes = struct.unpack_from("<8sIII", payload, 0)
    if magic != MAGIC or version != VERSION or entry_bytes != ENTRY_BYTES:
        raise ValueError("GPU geometry pack header is unsupported")
    directory_end = header_size + count * entry_bytes
    if directory_end > len(payload):
        raise ValueError("GPU geometry pack directory is truncated")
    result: dict[int, dict[str, Any]] = {}
    for index in range(count):
        offset = header_size + index * entry_bytes
        word, flags, vertex_count, index_count, vertex_offset, index_offset, _reserved = struct.unpack_from(
            "<HHIIIII", payload, offset
        )
        vertex_end = vertex_offset + vertex_count * VERTEX_BYTES
        index_end = index_offset + index_count * 4
        if vertex_offset < directory_end or index_offset < directory_end or vertex_end > len(payload) or index_end > len(payload):
            raise ValueError("GPU geometry pack payload range is invalid")
        vertices = [struct.unpack_from("<ffB3x", payload, vertex_offset + item * VERTEX_BYTES) for item in range(vertex_count)]
        indices = list(struct.unpack_from(f"<{index_count}I", payload, index_offset)) if index_count else []
        if any(value >= vertex_count for value in indices):
            raise ValueError("GPU geometry pack index is outside its vertex array")
        result[int(word)] = {
            "flags": int(flags),
            "vertices": [(float(x), float(y), int(alpha)) for x, y, alpha in vertices],
            "indices": indices,
        }
    return result
