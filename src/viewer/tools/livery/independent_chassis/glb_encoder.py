"""第一者GLB 2.0 Encoder。Carbin/ModelBinで検証済みのジオメトリを受けるStage。

原本モデルの解読処理ではない。未知のUV、Bone、Stock、Roleを推測・省略しない。
Viewer/既存コンバーターの実行入口には未接続。
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
import re
import struct
from typing import Mapping, Sequence

class IndependentGlbError(ValueError): pass

VALID_ROLES={'paint','glass','dark','trim','hidden'}

@dataclass(frozen=True)
class DecodedMesh:
    name: str
    positions: tuple[tuple[float,float,float], ...]
    normals: tuple[tuple[float,float,float], ...]
    indices: tuple[int, ...]
    uv_channels: Mapping[int,tuple[tuple[float,float], ...]]
    role: str
    source_entry: str
    material_name: str
    part_type: str
    part_option_ids: tuple[int, ...]
    stock_part: bool
    draw_groups: int
    allowed_sides: int
    projection_sides: int
    material_binding_hash: str
    instance_identity: str
    space_proof: str


def _finite_vector(value:Sequence, width:int)->tuple[float,...]:
    if not isinstance(value,(tuple,list)) or len(value)!=width:
        raise IndependentGlbError('source vertex width invalid')
    values=tuple(float(v) for v in value)
    if not all(math.isfinite(v) and abs(v)<1e9 for v in values):
        raise IndependentGlbError('non-finite/out-of-range vertex')
    return values


def _check_mesh(mesh:DecodedMesh)->None:
    if mesh.space_proof!='BONE_AND_INSTANCE_TRANSFORM_APPLIED':
        raise IndependentGlbError('mesh Bone/Bind Pose or instance transform not source-verified')
    if mesh.role not in VALID_ROLES or not mesh.name or not mesh.source_entry.endswith('.modelbin'):
        raise IndependentGlbError('mesh material/source role unverified')
    n=len(mesh.positions)
    if n<3 or n>5_000_000 or len(mesh.normals)!=n or not mesh.indices or len(mesh.indices)%3:
        raise IndependentGlbError('mesh topology invalid')
    for v in mesh.positions:_finite_vector(v,3)
    for v in mesh.normals:_finite_vector(v,3)
    for value in mesh.indices:
        if type(value) is not int or not 0<=value<n:
            raise IndependentGlbError('mesh index out of source range')
    if not isinstance(mesh.uv_channels,dict) or not all(type(k) is int and 0<=k<=4 for k in mesh.uv_channels):
        raise IndependentGlbError('unrecognized UV channel (do not drop)')
    for channel,values in mesh.uv_channels.items():
        if len(values)!=n:raise IndependentGlbError(f'UV{channel} source count mismatch')
        for uv in values:_finite_vector(uv,2)
    if type(mesh.allowed_sides) is not int or type(mesh.projection_sides) is not int:
        raise IndependentGlbError('11-side flags invalid')
    role_mask=0x3F if mesh.role=='paint' else 0x7c0 if mesh.role=='glass' else 0
    if mesh.allowed_sides & ~role_mask or mesh.projection_sides & ~role_mask:
        raise IndependentGlbError('Mask/Facing side set is not source-valid')
    if mesh.role in ('paint','glass'):
        if not mesh.allowed_sides or (3 not in mesh.uv_channels and not mesh.projection_sides):
            raise IndependentGlbError('paint/glass requires source UV3 or verified projection side')
    elif mesh.allowed_sides or mesh.projection_sides:
        raise IndependentGlbError('nonpaint mesh advertises livery sides')
    if not isinstance(mesh.stock_part,bool) or any(type(v) is not int for v in mesh.part_option_ids):
        raise IndependentGlbError('stock/options not proven')
    if not re.fullmatch('[0-9a-fA-F]{16}',mesh.material_binding_hash):
        raise IndependentGlbError('source material binding hash invalid')


def encode_glb(meshes:Sequence[DecodedMesh],part_options:Sequence[dict]=())->bytes:
    if not meshes or len(meshes)>25000:
        raise IndependentGlbError('empty/oversized source scene')
    for m in meshes:_check_mesh(m)
    if not any(m.role=='paint' for m in meshes):
        raise IndependentGlbError('required original paint scene is missing')
    option_keys=set()
    for option in part_options:
        if not isinstance(option,dict):raise IndependentGlbError('option is not source object')
        for key in ('part_type','part_type_value','id','level','car_body_id','stock','parent_is_stock'):
            if key not in option:raise IndependentGlbError('incomplete source part option')
        key=(option['part_type'],option['id'])
        if key in option_keys:raise IndependentGlbError('duplicate part option')
        option_keys.add(key)
    for mesh in meshes:
        if mesh.part_option_ids:
            if not mesh.part_type or any((mesh.part_type,vid) not in option_keys for vid in mesh.part_option_ids):
                raise IndependentGlbError('unresolved source part option')

    binary=bytearray(); views=[]; accessors=[]; nodes=[]; records=[]
    def add(values:Sequence[tuple],fmt:str,components:int,gl_type:str,component_type:int,target:int,bounds:bool=False)->int:
        while len(binary)%4:binary.append(0)
        offset=len(binary)
        flatten=[v for row in values for v in row]
        if not flatten:raise IndependentGlbError('empty accessor')
        binary.extend(struct.pack('<'+fmt*len(flatten),*flatten))
        view_id=len(views)
        views.append({'buffer':0,'byteOffset':offset,'byteLength':len(binary)-offset,'target':target})
        acc={'bufferView':view_id,'componentType':component_type,'count':len(values),'type':gl_type}
        if bounds:
            acc['min']=[min(row[i] for row in values) for i in range(components)]
            acc['max']=[max(row[i] for row in values) for i in range(components)]
        accessors.append(acc)
        return len(accessors)-1
    for mesh in meshes:
        attrs={'POSITION':add(mesh.positions,'f',3,'VEC3',5126,34962,bounds=True),
               'NORMAL':add(mesh.normals,'f',3,'VEC3',5126,34962)}
        for channel,uvs in sorted(mesh.uv_channels.items()):
            attrs[f'TEXCOORD_{channel}']=add(uvs,'f',2,'VEC2',5126,34962)
        width='H' if max(mesh.indices)<65536 else 'I'
        index_id=add(tuple((v,) for v in mesh.indices),width,1,'SCALAR',5123 if width=='H' else 5125,34963,bounds=True)
        extras={'lo4fh6_role':mesh.role,'lo4fh6_source_entry':mesh.source_entry,
                'lo4fh6_material_name':mesh.material_name,'lo4fh6_part_type':mesh.part_type,
                'lo4fh6_instance_identity':mesh.instance_identity,
                'lo4fh6_stock_part':mesh.stock_part,'lo4fh6_part_option_ids':list(mesh.part_option_ids),
                'lo4fh6_draw_groups':mesh.draw_groups,'lo4fh6_allowed_sides':mesh.allowed_sides,
                'lo4fh6_projection_sides':mesh.projection_sides,
                'lo4fh6_material_binding_hash':mesh.material_binding_hash.upper()}
        records.append({'name':mesh.name,'primitives':[{'attributes':attrs,'indices':index_id,'mode':4}], 'extras':extras})
        nodes.append({'name':mesh.name,'mesh':len(records)-1,'extras':extras})
    while len(binary)%4:binary.append(0)
    if len(binary)>256*1024*1024:raise IndependentGlbError('exceeds accepted chassis GLB memory limit')
    doc={'asset':{'version':'2.0','generator':'LO4FH6 first-party independent chassis encoder'},
         'scene':0,'scenes':[{'nodes':list(range(len(nodes))),
             'extras':{'lo4fh6_format':'lo4fh6_source_chassis_scene_v1','lo4fh6_part_options':list(part_options)}}],
         'nodes':nodes,'meshes':records,'accessors':accessors,'bufferViews':views,
         'buffers':[{'byteLength':len(binary)}]}
    js=json.dumps(doc,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    js+=b' '*((-len(js))%4)
    total=12+8+len(js)+8+len(binary)
    return (struct.pack('<4sII',b'glTF',2,total)+
            struct.pack('<I4s',len(js),b'JSON')+js+
            struct.pack('<I4s',len(binary),b'BIN\0')+binary)
