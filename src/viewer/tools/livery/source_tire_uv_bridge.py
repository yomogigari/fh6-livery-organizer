#!/usr/bin/env python3
"""FH6元ModelBinのTEXCOORD0..3/MatIを、既存rM032原本タイヤGLBへ非破壊接続する。

既存wheel_morph_internalの構造デコーダーを再利用し、POSITION/NORMAL/INDEX、
ノード、四輪の装着座標を変更しない。研究専用・ゲーム原本は一切同梱しない。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path
import numpy as np
from tools.livery import wheel_morph_internal as wm

_WHEELS = {'front_left','front_right','rear_left','rear_right'}
_NAME = re.compile(r'^OriginalTire/([^/]+)/([^/]+)__tag-[0-9a-fA-F]{4}__mesh-(\d+)$')

def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def load_glb(payload: bytes):
    if len(payload)<28 or payload[:4]!=b'glTF' or struct.unpack_from('<II',payload,4)!=(2,len(payload)):
        raise ValueError('GLBヘッダー不正')
    jlen, magic=struct.unpack_from('<I4s',payload,12)
    if magic!=b'JSON' or jlen%4: raise ValueError('GLB JSON不正')
    doc=json.loads(payload[20:20+jlen]); offset=20+jlen
    if offset+8>len(payload):raise ValueError('GLB BIN欠落')
    binlen, magic=struct.unpack_from('<I4s',payload,offset)
    if magic!=b'BIN\0' or offset+8+binlen!=len(payload):raise ValueError('GLB BIN不正')
    if len(doc.get('buffers',[]))!=1 or doc['buffers'][0]['byteLength']>binlen:
        raise ValueError('GLB単一BIN契約不正')
    return doc,bytearray(payload[offset+8:])

def glb_indices(doc, binary, prim):
    a=doc['accessors'][prim['indices']];v=doc['bufferViews'][a['bufferView']]
    if a['type']!='SCALAR' or a['componentType'] not in (5123,5125):raise ValueError('GLB索引型不一致')
    dtype='<u2' if a['componentType']==5123 else '<u4'
    off=int(v.get('byteOffset',0))+int(a.get('byteOffset',0))
    if off<0 or off+a['count']*np.dtype(dtype).itemsize>len(binary):raise ValueError('GLB索引範囲外')
    return np.frombuffer(binary,dtype=dtype,count=a['count'],offset=off).copy()

def _attrs(blobs, mesh, index):
    index_blobs=[b for b in blobs if b.tag==wm._TAG_INDB]
    if len(index_blobs)!=1:raise ValueError('ModelBin IndexBufferが一意でありません')
    ib=wm._parse_buffer(index_blobs[0]);idx=wm._read_indices(ib,mesh)
    if idx.size==0:raise ValueError('元ModelBinのIndexが空です')
    first=int(idx.min());count=int(idx.max())-first+1
    layouts=[b for b in blobs if b.tag in {wm._TAG_VLAY,wm._TAG_ILAY}]
    layout_by_id={int(b.identifier):wm._parse_layout(b) for b in layouts if b.identifier is not None}
    layout=layout_by_id.get(mesh.vertex_layout_index)
    if layout is None and 0<=mesh.vertex_layout_index<len(layouts):layout=wm._parse_layout(layouts[mesh.vertex_layout_index])
    if layout is None:raise ValueError('ModelBin頂点レイアウト未解決')
    vbs={int(b.identifier):wm._parse_buffer(b) for b in blobs if b.tag==wm._TAG_VERB and b.identifier is not None}
    channels={}
    for channel in range(4):
        elements=[e for e in layout if e.semantic=='TEXCOORD' and e.semantic_index==channel]
        if len(elements)!=1 or elements[0].fmt!=35:raise ValueError('原本TEXCOORDの形式が未解析です')
        views=wm._read_vertex_components(blobs,vbs,mesh,elements[0],first,count)
        # DXGI 35 = R16G16_UNORM。f16と解釈すると0xffffをNaNと誤認する。
        values=np.array([struct.unpack_from('<HH',view,0) for view in views],dtype=np.float32)/65535.0
        if not np.isfinite(values).all():raise ValueError('原本TEXCOORDが非有限値です')
        channels[channel]=values
    return idx,first,count,channels

def _put(binary,data):
    binary.extend(b'\0'*(-len(binary)%4));off=len(binary);binary.extend(data);return off

def build(base_glb:Path,tire_archive:Path,base_proof:Path,output:Path,proof_out:Path,apply=False):
    if output.exists() or proof_out.exists():raise ValueError('既存のGLB/証拠は上書きしません')
    raw=base_glb.read_bytes();doc,binary=load_glb(raw)
    reference=json.loads(base_proof.read_text(encoding='utf-8'))
    if reference.get('schema')!='lo4fh6.private.source-tire-glb-adapter.v1' or reference.get('source_tire_archive_sha256')!=sha(tire_archive.read_bytes()):
        raise ValueError('原本タイヤアーカイブ署名がrM032と不一致')
    if reference.get('source_glb_sha256')==sha(raw):raise ValueError('rM032結合前のGLBが指定されています')
    if reference.get('original_wheel_mesh_count',0)<4 or len(reference.get('wheels',{}))!=4:
        raise ValueError('rM032実4輪の原本証拠がありません')
    archive_sha=reference['source_tire_archive_sha256']
    with zipfile.ZipFile(tire_archive) as z:
        if z.testzip() is not None:raise ValueError('タイヤZIPのCRC不一致')
        names={n.casefold():n for n in z.namelist() if n.lower().endswith('.modelbin')}
        cache={}
        changed=[];wheels=set();source_materials={};original_geometry_len=len(binary)
        for mesh in doc['meshes']:
            ex=mesh.get('extras',{})
            if ex.get('lo4_part_type')!='Tire':continue
            match=_NAME.fullmatch(mesh.get('name',''))
            if not match:raise ValueError('元タイヤGLBメッシュに原本同定名がありません')
            wheel,_,blob_index=match.groups();blob_index=int(blob_index)
            if wheel not in _WHEELS or ex.get('lo4_tire_source_wheel')!=wheel:raise ValueError('元タイヤ四輪割当不正')
            source=ex.get('lo4_source_entry','').replace('\\','/').split('/')[-1]
            if source.casefold() not in names or ex.get('lo4_tire_original_archive_sha256')!=archive_sha or ex.get('lo4_tire_source_packet_sha256')!=reference.get('source_packet_sha256'):
                raise ValueError('元タイヤModelBin/Packet出典が不正')
            orig_name=names[source.casefold()];wheels.add(wheel)
            if orig_name not in cache:cache[orig_name]=wm._parse_blobs(z.read(orig_name))
            blobs=cache[orig_name]
            if blob_index<0 or blob_index>=len(blobs) or blobs[blob_index].tag!=wm._TAG_MESH:
                raise ValueError('元ModelBin mesh blob番号不一致')
            source_mesh=wm._parse_mesh(blobs[blob_index]);source_indices,first,count,channels=_attrs(blobs,source_mesh,blob_index)
            prim=mesh['primitives'][0]
            if any(f'TEXCOORD_{ch}' in prim['attributes'] for ch in range(4)):
                raise ValueError('UV追加済みGLBには重複適用しません')
            indices=glb_indices(doc,binary,prim)
            if indices.size!=source_indices.size or indices.size%3:
                raise ValueError('元ModelBinとGLBのINDEX数が違います')
            # rM032の左右系変換は三角形の[1,2]を反転。頂点順序は変更していない。
            expected=(source_indices-first).reshape(-1,3).copy();expected[:,[1,2]]=expected[:,[2,1]]
            if not np.array_equal(indices.reshape(-1,3),expected):
                raise ValueError('ModelBinとGLB頂点順序・indexが異なり、UVを安全に対応付けられません')
            pos=doc['accessors'][prim['attributes']['POSITION']]
            if pos['count']!=count:raise ValueError('元ModelBin/GLBの頂点数が一致しません')
            mat_blob=next((blob for blob in blobs if blob.tag==0x4d617449 and blob.identifier==source_mesh.material_id),None)
            if mat_blob is None or not mat_blob.name:raise ValueError('原本ModelBin MatIの材質IDを照合できません')
            uv_interleaved=np.concatenate([channels[i] for i in range(4)],axis=1).astype('<f4',copy=False)
            off=_put(binary,uv_interleaved.tobytes());view_index=len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':uv_interleaved.nbytes,'byteStride':32,'target':34962})
            for channel in range(4):
                access=len(doc['accessors']);doc['accessors'].append({'bufferView':view_index,'byteOffset':channel*8,'componentType':5126,'count':count,'type':'VEC2'})
                prim['attributes'][f'TEXCOORD_{channel}']=access
            for target in (ex,prim.setdefault('extras',{})):
                target['lo4_tire_original_material_id']=source_mesh.material_id
                target['lo4_tire_original_material_name']=mat_blob.name
                target['lo4_tire_original_matI_sha256']=sha(mat_blob.data)
                target['lo4_tire_uv_origin']='ModelBin/TEXCOORD_UNORM16_4channels_no_geometry_edit'
            changed.append({'wheel':wheel,'material_id':source_mesh.material_id,'material_name':mat_blob.name,'vertex_count':count,'uv_channels':4,'source_modelbin_sha256':sha(z.read(orig_name))})
            source_materials.setdefault(mat_blob.name,set()).add(sha(mat_blob.data))
    if wheels!=_WHEELS or not changed:
        raise ValueError('4輪の元タイヤUVがそろいません')
    doc['buffers'][0]['byteLength']=len(binary)
    json_chunk=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode('utf-8');json_chunk+=b' '*(-len(json_chunk)%4)
    binary.extend(b'\0'*(-len(binary)%4))
    out=struct.pack('<4sII',b'glTF',2,12+8+len(json_chunk)+8+len(binary))+struct.pack('<I4s',len(json_chunk),b'JSON')+json_chunk+struct.pack('<I4s',len(binary),b'BIN\0')+binary
    proof={'schema':'lo4fh6.first_party.source_tire_uv4.v1','status':'RESEARCH_ONLY','source_glb_sha256':sha(raw),'original_tire_archive_sha256':archive_sha,'output_glb_sha256':sha(out),
           'four_wheels':sorted(wheels),'tire_meshes':len(changed),'uv_channels_per_mesh':4,'materials':{k:sorted(v) for k,v in sorted(source_materials.items())},
           'position_normal_index_original_bytes_preserved':True,'original_binary_prefix_sha256':sha(bytes(binary[:original_geometry_len])),
           'source_input_sha256':sha(raw),'source_unchanged':True,'no_vertex_or_index_transform':True,'game_material_shader_approved':False,'xbox_appearance_approved':False}
    if apply:
        output.parent.mkdir(parents=True,exist_ok=True);proof_out.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(out);proof_out.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    return proof

def main():
    p=argparse.ArgumentParser();p.add_argument('--base-glb',type=Path,required=True);p.add_argument('--source-tires',type=Path,required=True);p.add_argument('--base-proof',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--proof-output',type=Path,required=True);p.add_argument('--apply',action='store_true')
    x=p.parse_args();build(x.base_glb,x.source_tires,x.base_proof,x.output,x.proof_output,x.apply)
if __name__=='__main__':main()
