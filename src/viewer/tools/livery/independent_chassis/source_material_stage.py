"""Exact FH6 source material ID -> MatI Bundle, without invented shader/PBR color.

Material visual equivalence is not claimed; this stage preserves original source
payload SHA and material identity until shader/texture binding is verified.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from hashlib import sha256
from .modelbin_geometry_decoder import Blob,Mesh,parse_bundle,data,DecodeError

@dataclass(frozen=True)
class MaterialRef:
    id:int
    name:str
    source_blob_sha256:str
    source_blob_bytes:int
    nested_blob_tags:tuple[str,...]
    pbr_verified:bool=False
    # MatI の中の最初の Game:\...\*.materialbin の参照（親の材質）。無ければ空。
    parent_materialbin:str=''


_PARENT_MATERIALBIN=re.compile(rb'(?i)game:\\[^\x00\r\n]*?\.materialbin')


def original_materials(raw:bytes,blobs:list[Blob])->dict[int,MaterialRef]:
    result={}
    for b in blobs:
        if b.tag!='MatI':continue
        if b.meta_id is None or not b.name or b.meta_id in result:
            raise DecodeError('source material identity is missing or duplicated')
        payload=bytes(data(raw,b))
        if payload and not payload.startswith(b'burG'):
            raise DecodeError('original material payload lacks Forza Bundle signature')
        nested=parse_bundle(payload) if payload else []
        # 親の MaterialBin の参照（material_runtime._game_refs_from_material と同じ形の文字列）。
        parent=_PARENT_MATERIALBIN.search(payload) if payload else None
        result[b.meta_id]=MaterialRef(b.meta_id,b.name,sha256(payload).hexdigest(),len(payload),
                                      tuple(item.tag for item in nested),
                                      parent_materialbin=parent.group(0).decode('ascii','replace') if parent else '')
    return result


def resolve_mesh_material(mesh:Mesh,materials:dict[int,MaterialRef])->MaterialRef|None:
    if len(mesh.material_groups)<1:
        raise DecodeError('source Mesh has no MaterialGroup')
    # 参照製品 MeshBlob v1.9+ uses element [1]. Reject unsupported group heterogeneity
    # until per-submesh material mapping is established.
    source_ids=set()
    for group in mesh.material_groups:
        if len(group)!=4:raise DecodeError('unexpected material group width')
        source_ids.add(group[1])
    if len(source_ids)!=1:
        raise DecodeError('multiple mesh MaterialGroup bindings require submesh association')
    material_id=next(iter(source_ids))
    if material_id<0:
        if mesh.blob.name=='Shadow' and mesh.bucket & 8 and not(mesh.bucket & 16):
            return None
        raise DecodeError('unresolved negative source material ID on visible surface')
    if material_id not in materials:
        raise DecodeError('visible mesh source MatI reference absent')
    # Some ProxyLOD material records are empty. Preserve their missing shader
    # evidence instead of inventing a PBR value or silently dropping the mesh.
    return materials[material_id]
