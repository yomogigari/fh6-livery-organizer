"""車体の変換のメッシュ 1 つ分の数値の処理を、自前の Rust の部品で行う（2026-11-21）。

source_stock_glb の静止の部品の変換（製品の道：source_original_static_selection・変形の入力なし）で、次の処理を
Rust の部品（native/lo4fh6_native/src/mesh.rs の lo4_mesh_geometry）。independent_chassis（研究の写しと同じバイトに保つ
32 のモジュール）の外に置き、source_stock_glb からは読み込めるときだけ使うの 1 回の呼び出しにまとめる。
- extract_raw_geometry（頂点の解読）・source_uv_affine（UV）・transform_source_geometry（姿勢）・
  clean_original_static_triangle_indices（三角形の整理）・_Writer.append の範囲の計算
ここでは、今の Python の処理と同じ検査と解決（IndB・VerB・VLay を meta の番号か並びの番号で探す、
VLay の要素の位置の確かめ、バッファーの見出しの確かめ）を ModelBin ごとに 1 回だけ行って覚え、Rust へ渡す値を作る。
いつもと違う所が 1 つでもあれば None を返す。呼び出し側は、そのメッシュを今までの Python の処理で作る
（エラーとその文言は、今までどおり Python の処理が出す）。部品が無いとき（公開のソースだけの配布など）も None。
利用者の決定（2026-11-21）：出来上がりは目で見て同じ程度でよい（Rust の行列の積の足し算の順などで、最後の桁がまれにずれる）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import native_kernels
from .independent_chassis.modelbin_geometry_decoder import FORMAT_BYTES, DecodeError, Mesh, buffer_header, layout_decode

_SEMANTICS = {"POSITION": 0, "NORMAL": 1, "TEXCOORD": 2, "COLOR": 3}
_UV_CHANNELS = (0, 1, 2, 3, 4)
_MAX_VERTICES = 2_000_000
_FLAG_STATIC_CLEAN = 1


@dataclass(frozen=True)
class NativeMeshGeometry:
    """Rust の部品の結果。配列は GLB へそのまま詰められる 32 ビットの小数・番号（小さい端から）のバイト列。"""
    vertex_count: int
    index_count: int
    source_triangle_count: int
    missing_normal: bool
    positions: memoryview
    normals: memoryview
    uvs: dict
    indices: memoryview
    index_width: int
    position_min: tuple
    position_max: tuple
    index_min: int
    index_max: int


def available() -> bool:
    return native_kernels.library() is not None


class NativeMeshPlanner:
    """1 つの ModelBin の中の場所の解決と検査を覚え、メッシュごとに Rust の部品を呼ぶ。"""

    def __init__(self, raw: bytes, blobs: list) -> None:
        self.raw = raw
        self.blobs = blobs
        self._lists: dict[str, list] = {}
        self._by_id: dict[str, dict] = {}
        for tag in ("IndB", "VerB", "VLay"):
            items = [b for b in blobs if b.tag == tag]
            by_id: dict = {}
            for blob in items:
                # next((b for b in items if b.meta_id == x), None) と同じく、同じ番号なら最初の物
                if blob.meta_id is not None:
                    by_id.setdefault(blob.meta_id, blob)
            self._lists[tag] = items
            self._by_id[tag] = by_id
        self._headers: dict[int, tuple | None] = {}
        self._layouts: dict[int, tuple | None] = {}

    def _resolve(self, tag: str, key: int):
        found = self._by_id[tag].get(key)
        if found is not None:
            return found
        items = self._lists[tag]
        return items[key] if 0 <= key < len(items) else None

    def _header(self, blob) -> tuple | None:
        if blob.offset not in self._headers:
            try:
                self._headers[blob.offset] = buffer_header(self.raw, blob)
            except DecodeError:
                self._headers[blob.offset] = None
        return self._headers[blob.offset]

    def _layout(self, blob) -> tuple | None:
        """VLay の要素と、slot ごとの詰めた位置（extract_raw_geometry と同じ確かめ）。合わなければ None。"""
        if blob.offset not in self._layouts:
            layout = None
            try:
                elements, _packed, _flags = layout_decode(self.raw, blob)
                by_slot: dict[int, list] = {}
                ok = True
                for element in elements:
                    if element[4] not in FORMAT_BYTES:
                        ok = False
                        break
                    by_slot.setdefault(element[2], []).append(element)
                offsets: dict = {}
                if ok:
                    for slot, entries in by_slot.items():
                        offset = 0
                        for semantic, semantic_index, _slot, _klass, fmt, aligned, _step in entries:
                            if aligned >= 0 and aligned != offset:
                                ok = False
                                break
                            offsets[(semantic, semantic_index, slot)] = offset
                            offset += FORMAT_BYTES[fmt]
                        if not ok:
                            break
                if ok:
                    layout = (elements, offsets)
            except DecodeError:
                layout = None
            self._layouts[blob.offset] = layout
        return self._layouts[blob.offset]

    def geometry(self, mesh: Mesh, *, bone_matrix, instance_matrix) -> NativeMeshGeometry | None:
        """メッシュ 1 つ分を Rust の部品で処理する。扱えないときは None（今までの Python の処理で作る）。"""
        raw = self.raw
        if not mesh.index_count or mesh.index_width not in (2, 4):
            return None
        # 番号（mesh_index_range と同じ解決と確かめ）
        index_blob = self._resolve("IndB", mesh.index_buffer_id)
        if index_blob is None or self._header(index_blob) is None:
            return None
        start = 16 + mesh.index_byte_offset + mesh.index_draw_offset * mesh.index_width
        end = start + mesh.index_count * mesh.index_width
        if start < 16 or end > index_blob.length:
            return None
        values = np.frombuffer(raw, dtype="<u4" if mesh.index_width == 4 else "<u2", count=mesh.index_count,
                               offset=index_blob.offset + start)
        imin, imax = int(values.min()), int(values.max())
        vertex_count = imax - imin + 1
        if not 0 < vertex_count <= _MAX_VERTICES:
            return None
        # 頂点の要素（extract_raw_geometry と同じ解決と確かめ）
        layout_blob = self._resolve("VLay", mesh.layout_id)
        if layout_blob is None:
            return None
        layout = self._layout(layout_blob)
        if layout is None:
            return None
        elements, offsets = layout
        slots: dict[int, tuple] = {}
        for usage in mesh.usages:
            vertex_blob = self._resolve("VerB", usage.index)
            if vertex_blob is None:
                return None
            header = self._header(vertex_blob)
            if header is None or header[2] <= 0 or usage.slot in slots:
                return None
            slots[usage.slot] = (vertex_blob, header[2], usage.offset)
        descriptors = []
        uv_channels = set()
        for semantic, semantic_index, slot, _klass, fmt, _aligned, _step in elements:
            code = _SEMANTICS.get(semantic)
            if code is None:
                continue
            if semantic == "TEXCOORD":
                if semantic_index not in _UV_CHANNELS:
                    continue
                uv_channels.add(semantic_index)
            if slot not in slots:
                return None
            vertex_blob, stride, usage_offset = slots[slot]
            base = 16 + usage_offset + mesh.vertex_offset * stride + offsets[(semantic, semantic_index, slot)]
            descriptors.append(native_kernels.MeshElement(code, semantic_index, fmt, stride, base,
                                                          vertex_blob.offset, vertex_blob.length))
        if len(descriptors) > 64 or len(mesh.uv_xforms) < 5 or len(mesh.scale) != 4 or len(mesh.translate) != 4:
            return None
        params = native_kernels.MeshParams()
        params.index_offset = index_blob.offset + start
        params.index_count = mesh.index_count
        params.index_width = mesh.index_width
        params.flags = _FLAG_STATIC_CLEAN
        params.scale[:] = [float(v) for v in mesh.scale]
        params.translate[:] = [float(v) for v in mesh.translate]
        params.bone[:] = [float(v) for v in np.asarray(bone_matrix, dtype=np.float64).reshape(16)]
        params.instance[:] = [float(v) for v in np.asarray(instance_matrix, dtype=np.float64).reshape(16)]
        params.uv_affine[:] = [float(v) for row in mesh.uv_xforms[:5] for v in row]
        capacity = (native_kernels.MESH_HEADER.size + vertex_count * (24 + 8 * len(uv_channels))
                    + mesh.index_count * 4)
        out = native_kernels.mesh_geometry(raw, params, descriptors, capacity)
        if out is None:
            return None
        return _parse(out)


def _parse(out: bytearray) -> NativeMeshGeometry | None:
    header = native_kernels.MESH_HEADER.unpack_from(out, 0)
    (magic, vertex_count, index_count, source_triangles, flags, uv_mask, index_width, _reserved,
     min_x, min_y, min_z, max_x, max_y, max_z, index_min, index_max) = header
    if magic != 0x474D4F4C or index_width not in (2, 4):
        return None
    view = memoryview(out)
    at = native_kernels.MESH_HEADER.size
    positions = view[at:at + vertex_count * 12]
    at += vertex_count * 12
    normals = view[at:at + vertex_count * 12]
    at += vertex_count * 12
    uvs = {}
    for channel in range(5):
        if uv_mask & (1 << channel):
            uvs[channel] = view[at:at + vertex_count * 8]
            at += vertex_count * 8
    indices = view[at:at + index_count * index_width]
    return NativeMeshGeometry(vertex_count=vertex_count, index_count=index_count,
                              source_triangle_count=source_triangles, missing_normal=bool(flags & 1),
                              positions=positions, normals=normals, uvs=uvs, indices=indices, index_width=index_width,
                              position_min=(min_x, min_y, min_z), position_max=(max_x, max_y, max_z),
                              index_min=index_min, index_max=index_max)
