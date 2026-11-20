"""車体の GLB から、表示しないメッシュ（役割 hidden）を除く（キャッシュの容量を減らす。2026-11-20）。

- 役割 hidden のメッシュ（影だけの面・静止表示で隠す面・地面の下の部品・回るホイールの透明の面など）は、Viewer が
  読み込んだ後に visible=false にするだけで描かない（viewer.js の meshCategory → hidden）。全 689 車種の車体の
  GLB で、バイトの 26.7% を占めていた。除いても見た目は変わらず、ページの読み込みも軽くなる。
- 除くのは、変換とホイールの位置合わせ（隠す面を決める）が終わった後の、最後の書き出しの直前だけ。
- 除いたメッシュだけが使うアクセサー・bufferView も除き、BIN を詰め直す（残るデータのバイトは変えない）。
  ノードは、子を持つものはメッシュの参照だけを外して残す。シーンと子の番号は付け替える。
- 骨組み（skins）・動き（animations）・疎なアクセサー（sparse）がある GLB は、番号の付け替えが広がるので触らない。
- 除いた数をシーンの付加情報（lo4fh6_hidden_meshes_removed など）に残す。
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

HIDDEN_ROLE = "hidden"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class GlbCompactError(ValueError):
    pass


def _role(extras: object) -> str:
    if not isinstance(extras, dict):
        return ""
    return str(extras.get("lo4fh6_role") or extras.get("lo4_role") or "")


def drop_hidden_meshes(document: dict, binary: bytes | bytearray) -> tuple[bytearray, dict]:
    """document（GLB の JSON）と binary（BIN）から、役割 hidden のメッシュを除く。document はその場で書き換える。

    詰め直した BIN と、記録（除いた数・バイト数・古いメッシュの番号 → 新しい番号）を返す。
    """
    meshes = document.get("meshes") or []
    identity = {index: index for index in range(len(meshes))}
    if document.get("skins") or document.get("animations") or any(
            isinstance(a, dict) and a.get("sparse") for a in document.get("accessors") or []):
        return bytearray(binary), {"removed_meshes": 0, "removed_bytes": 0, "mesh_map": identity,
                                   "skipped": "skins-animations-or-sparse"}
    hidden = {index for index, mesh in enumerate(meshes) if _role(mesh.get("extras")) == HIDDEN_ROLE}
    if not hidden or len(hidden) == len(meshes):
        return bytearray(binary), {"removed_meshes": 0, "removed_bytes": 0, "mesh_map": identity}

    # メッシュ
    mesh_map: dict[int, int] = {}
    kept_meshes = []
    for index, mesh in enumerate(meshes):
        if index not in hidden:
            mesh_map[index] = len(kept_meshes)
            kept_meshes.append(mesh)

    # ノード（子を持つノードはメッシュの参照だけを外して残す）
    nodes = document.get("nodes") or []
    node_map: dict[int, int] = {}
    kept_nodes = []
    for index, node in enumerate(nodes):
        if "mesh" in node and node["mesh"] in hidden:
            if node.get("children"):
                node = {key: value for key, value in node.items() if key != "mesh"}
            else:
                continue
        node_map[index] = len(kept_nodes)
        kept_nodes.append(node)
    for node in kept_nodes:
        if "mesh" in node:
            node["mesh"] = mesh_map[node["mesh"]]
        if "children" in node:
            node["children"] = [node_map[child] for child in node["children"] if child in node_map]
            if not node["children"]:
                del node["children"]
    for scene in document.get("scenes") or []:
        if "nodes" in scene:
            scene["nodes"] = [node_map[n] for n in scene["nodes"] if n in node_map]

    # アクセサー（残るメッシュが使うものだけ）
    accessors = document.get("accessors") or []
    used_accessors: set[int] = set()
    for mesh in kept_meshes:
        for primitive in mesh.get("primitives") or []:
            used_accessors.update(int(v) for v in (primitive.get("attributes") or {}).values())
            if "indices" in primitive:
                used_accessors.add(int(primitive["indices"]))
            for target in primitive.get("targets") or []:
                used_accessors.update(int(v) for v in target.values())
    accessor_map: dict[int, int] = {}
    kept_accessors = []
    for index, accessor in enumerate(accessors):
        if index in used_accessors:
            accessor_map[index] = len(kept_accessors)
            kept_accessors.append(accessor)
    for mesh in kept_meshes:
        for primitive in mesh.get("primitives") or []:
            primitive["attributes"] = {k: accessor_map[int(v)] for k, v in (primitive.get("attributes") or {}).items()}
            if "indices" in primitive:
                primitive["indices"] = accessor_map[int(primitive["indices"])]
            if primitive.get("targets"):
                primitive["targets"] = [{k: accessor_map[int(v)] for k, v in t.items()} for t in primitive["targets"]]

    # bufferView（残るアクセサーと画像が使うものだけ）。BIN を元の順で詰め直す。
    views = document.get("bufferViews") or []
    used_views = {int(a["bufferView"]) for a in kept_accessors if "bufferView" in a}
    used_views |= {int(i["bufferView"]) for i in document.get("images") or [] if "bufferView" in i}
    if any(int(views[v].get("buffer", 0)) != 0 for v in used_views):
        raise GlbCompactError("GLB の bufferView が BIN 以外を参照している")
    view_map: dict[int, int] = {}
    kept_views = []
    packed = bytearray()
    for index, view in enumerate(views):
        if index not in used_views:
            continue
        start = int(view.get("byteOffset", 0))
        length = int(view["byteLength"])
        if start < 0 or start + length > len(binary):
            raise GlbCompactError("GLB の bufferView が BIN の範囲の外")
        while len(packed) % 4:
            packed.append(0)
        view = dict(view)
        view["byteOffset"] = len(packed)
        packed += binary[start:start + length]
        view_map[index] = len(kept_views)
        kept_views.append(view)
    while len(packed) % 4:
        packed.append(0)
    for accessor in kept_accessors:
        if "bufferView" in accessor:
            accessor["bufferView"] = view_map[int(accessor["bufferView"])]
    for image in document.get("images") or []:
        if "bufferView" in image:
            image["bufferView"] = view_map[int(image["bufferView"])]

    document["meshes"] = kept_meshes
    document["nodes"] = kept_nodes
    document["accessors"] = kept_accessors
    document["bufferViews"] = kept_views
    if document.get("buffers"):
        document["buffers"][0]["byteLength"] = len(packed)
    removed_bytes = len(binary) - len(packed)
    info = {"removed_meshes": len(hidden), "removed_nodes": len(nodes) - len(kept_nodes),
            "removed_accessors": len(accessors) - len(kept_accessors), "removed_bytes": removed_bytes,
            "mesh_map": {**mesh_map, **{index: None for index in hidden}}}
    for scene in document.get("scenes") or []:
        extras = scene.setdefault("extras", {})
        if isinstance(extras, dict):
            extras["lo4fh6_hidden_meshes_removed"] = len(hidden) + int(extras.get("lo4fh6_hidden_meshes_removed") or 0)
            extras["lo4fh6_hidden_mesh_bytes_removed"] = (
                removed_bytes + int(extras.get("lo4fh6_hidden_mesh_bytes_removed") or 0))
    return packed, info


def read_glb(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise GlbCompactError("GLB ではない")
    _, version, length = struct.unpack_from("<4sII", data, 0)
    if version != 2 or length != len(data):
        raise GlbCompactError("GLB の見出しが不正")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != _JSON_CHUNK:
        raise GlbCompactError("GLB の最初のチャンクが JSON ではない")
    document = json.loads(data[20:20 + json_length])
    offset = 20 + json_length
    binary = b""
    if offset < length:
        bin_length, bin_type = struct.unpack_from("<II", data, offset)
        if bin_type != _BIN_CHUNK or offset + 8 + bin_length != length:
            raise GlbCompactError("GLB の BIN チャンクが不正（後ろに別のチャンクがある）")
        binary = data[offset + 8:offset + 8 + bin_length]
    return document, binary


def write_glb(document: dict, binary: bytes | bytearray) -> bytes:
    raw_json = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_json += b" " * ((-len(raw_json)) % 4)
    raw_bin = bytes(binary) + b"\x00" * ((-len(binary)) % 4)
    total = 12 + 8 + len(raw_json) + (8 + len(raw_bin) if raw_bin else 0)
    out = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    out += struct.pack("<II", len(raw_json), _JSON_CHUNK) + raw_json
    if raw_bin:
        out += struct.pack("<II", len(raw_bin), _BIN_CHUNK) + raw_bin
    return bytes(out)


def drop_hidden_meshes_in_file(path: Path | str) -> dict:
    """GLB のファイルから役割 hidden のメッシュを除いて書き直す（除くものが無ければ書かない）。記録を返す。"""
    path = Path(path)
    document, binary = read_glb(path.read_bytes())
    packed, info = drop_hidden_meshes(document, binary)
    if info["removed_meshes"]:
        partial = path.with_name(f"{path.name}.{os.getpid()}.compact.partial")
        try:
            partial.write_bytes(write_glb(document, packed))
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return info
