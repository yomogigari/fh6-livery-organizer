#!/usr/bin/env python3
"""FH6 ModelBin MeshBlobのUV affineをrM既存GLBの原本Sidewall4面にだけ研究適用する。

参照：参照製品 MeshBlob.cs v1.5+ は後尾5xVector4
( u_offset, u_scale, v_offset, v_scale )、参照製品 Program.cs はnative UVで
(uv.x*scale+offset, uv.y*scale+offset)。出典は原本 ModelBin と GLB
生UVが頂点数・バイト数・値で一致した場合のみ研究用 KHR_texture_transformを作る。
**ゲームShaderが文字Textureにどのチャネルを使うかは未確定**。
原本GLBのBIN、全Mesh/Node、元素材、既定Viewerを一切変更しない。
第三者コードは含まない。MITの参照製品の処理を参照して独自に実装。
"""
from __future__ import annotations
import argparse,copy,hashlib,json,math,struct,zipfile,sys
from pathlib import Path
import numpy as np
from tools.livery import wheel_morph_internal as wm
from tools.livery.source_tire_uv_bridge import _attrs

WHEELS={'front_left','front_right','rear_left','rear_right'}
ROLES={'sidewall','tread','scaling_text'}
KHR='KHR_texture_transform'

def sha(v:bytes)->str:return hashlib.sha256(v).hexdigest()
def unpack_glb(data:bytes):
    if data[:4]!=b'glTF' or struct.unpack_from('<II',data,4)!=(2,len(data)):
        raise ValueError('GLB header/version/length mismatch')
    n,typ=struct.unpack_from('<I4s',data,12)
    if typ!=b'JSON':raise ValueError('GLB JSON chunk missing')
    doc=json.loads(data[20:20+n]);off=20+n;ln,typ=struct.unpack_from('<I4s',data,off)
    if typ!=b'BIN\0' or off+8+ln!=len(data):raise ValueError('GLB BIN chunk missing')
    return doc,data[off+8:]
def pack_glb(doc,original_bin):
    js=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode('utf8');js+=b' '*(-len(js)%4)
    return struct.pack('<4sII',b'glTF',2,12+8+len(js)+8+len(original_bin))+struct.pack('<I4s',len(js),b'JSON')+js+struct.pack('<I4s',len(original_bin),b'BIN\0')+original_bin

def uv_array(doc,original_bin,accessor_id):
    ac=doc['accessors'][accessor_id];bv=doc['bufferViews'][ac['bufferView']]
    if ac['type']!='VEC2' or ac['componentType']!=5126 or ac.get('sparse'):
        raise ValueError('Source GLB UV accessor unsupported type')
    off=bv.get('byteOffset',0)+ac.get('byteOffset',0)
    stride=bv.get('byteStride',8)
    if stride<8 or off<0 or off+(ac['count']-1)*stride+8>len(original_bin):
        raise ValueError('GLB UV bufferView out of bounds')
    return np.ndarray((ac['count'],2),dtype='<f4',buffer=original_bin,offset=off,strides=(stride,4)).copy()

def mesh_affines(blobs,sidewall_material_id,glb_prim,doc,binary,*,source_meshblob_index=None):
    expected_uvs={channel:uv_array(doc,binary,glb_prim['attributes'][f'TEXCOORD_{channel}']) for channel in range(4)}
    candidates=[]
    for blob in blobs:
        if blob.tag!=wm._TAG_MESH:continue
        # 原本Tireは同じMatIを複数のLOD0 MeshBlobで共有できる。
        # 出力GLB側に保持した実Blob indexがあるときは、それだけを照合する。
        # indexのない旧キャッシュで複数候補なら従来どおり曖昧として拒否する。
        if source_meshblob_index is not None and blob.index!=source_meshblob_index:
            continue
        mesh=wm._parse_mesh(blob)
        if mesh.material_id!=sidewall_material_id:continue
        if blob.major!=1 or blob.minor<8:raise ValueError('Unsupported MeshBlob affine version')
        # 元MeshBlob後尾は source_mesh_idx, 5xVector4 affine, 2xVector4 position。
        data=bytes(blob.data)
        if len(data)<116:raise ValueError('MeshBlob affine truncated')
        tail=struct.unpack_from('<8f',data,len(data)-32)
        if any(abs(x-y)>1e-6 for x,y in zip(tail,(*mesh.position_scale,*mesh.position_translate))):
            raise ValueError('MeshBlob UV affine tail positioning inconsistency')
        affine=np.frombuffer(data,dtype='<f4',count=20,offset=len(data)-112).reshape(5,4).copy()
        if not np.isfinite(affine).all() or np.abs(affine).max()>=1e6:
            raise ValueError('Nonfinite/native affine unsafe')
        try:
            indices,first,count,chans=_attrs(blobs,mesh,blob.index)
        except Exception:continue
        if count!=len(expected_uvs[0]):continue
        if not all(np.allclose(chans[ch],expected_uvs[ch],atol=1e-6,rtol=0) for ch in range(4)):
            continue
        candidates.append((blob,affine))
    if len(candidates)!=1:raise ValueError(f'原本Sidewall LOD0 MeshBlob crosswalk not unique: {len(candidates)}')
    return candidates[0]

def build(src_glb:bytes,model_zip:bytes,channel:int,expected_glb_sha256:str):
    if sha(src_glb)!=expected_glb_sha256:raise ValueError('Signed source GLB SHA differs')
    if channel not in (0,1,2):raise ValueError('Native Sidewall UV3 is not accepted for image research')
    doc,bb=unpack_glb(src_glb);orig=copy.deepcopy(doc)
    with zipfile.ZipFile(__import__('io').BytesIO(model_zip)) as z:
        if z.testzip():raise ValueError('Original ModelBin archive CRC mismatch')
        originals={name.lower():z.read(name) for name in z.namelist() if name.lower().endswith('.modelbin')}
    if len(originals)!=2:raise ValueError('Original source left/right ModelBin not unique')
    checks={};copies=[];roles={};original_materials=[]
    for mesh in doc['meshes']:
        x=mesh.get('extras',{})
        if x.get('lo4_part_type')!='Tire' or x.get('lo4_role')=='hidden':continue
        wheel=x.get('lo4_tire_source_wheel');role=x.get('lo4_tire_original_material_name')
        if wheel not in WHEELS or role not in ROLES:raise ValueError('Unverified original wheel or material')
        key=wheel+'/'+role;roles[key]=roles.get(key,0)+1
        if role!='sidewall':continue
        name=x.get('lo4_source_entry','').replace('\\','/').split('/')[-1].lower()
        raw=originals.get(name)
        if raw is None or sha(raw)!=x.get('lo4_tire_original_modelbin_sha256'):
            raise ValueError('Original source ModelBin SHA mismatch')
        if len(mesh.get('primitives',[]))!=1:raise ValueError('Non-unique glTF primitive')
        prim=mesh['primitives'][0];matidx=prim.get('material')
        if not isinstance(matidx,int) or matidx not in range(len(doc['materials'])):
            raise ValueError('Invalid source material ID')
        material=doc['materials'][matidx];extras=material.get('extras',{})
        if extras.get('original_mati_id')!=x.get('lo4_tire_original_material_id') or extras.get('lo4fh6_source_tire_sidewall_text_research') is not True:
            raise ValueError('Not a verified Sidewall research material')
        tx=material.get('pbrMetallicRoughness',{}).get('baseColorTexture',{})
        if tx.get('texCoord',0)!=0 or 'extensions' in tx:raise ValueError('Existing transform or unexpected base channel')
        oldimage=doc['textures'][tx['index']]['source']
        if doc['images'][oldimage]['extras']['original_swatch_sha256']!=extras.get('source_swatch_sha256'):
            raise ValueError('Original image Swatch SHA does not match Sidewall material')
        if len([k for k in prim['attributes'] if k.startswith('TEXCOORD_')])!=4:
            raise ValueError('Source tire must retain all original four UVs')
        blob,aff=mesh_affines(wm._parse_blobs(raw),x['lo4_tire_original_material_id'],prim,doc,bb)
        o_u,s_u,o_v,s_v=map(float,aff[channel]);
        if abs(s_u)<1e-10 or abs(s_v)<1e-10:raise ValueError('Native affine degenerates')
        tx['texCoord']=channel
        tx['extensions']={KHR:{'offset':[o_u,o_v],'scale':[s_u,s_v]}}
        extras['lo4fh6_original_mesh_uv_affine_research_only']={
            'native_channel':channel,'source_meshblob_index':blob.index,
            'offset_scale_uv':[o_u,s_u,o_v,s_v],'source_mati_parameter':extras['original_mati_parameter'],
            'pipeline':'reference_native_unflipped_then_MeshBlob_affine','game_shader_equivalent':False}
        copies.append({'wheel':wheel,'source_meshblob_index':blob.index,'source_modelbin_sha256':sha(raw),
            'native_channel':channel,'affine':[o_u,s_u,o_v,s_v],
            'raw_uv_sha256':sha(uv_array(orig,bb,prim['attributes'][f'TEXCOORD_{channel}']).tobytes())})
        original_materials.append(matidx)
    expected={w+'/'+r for w in WHEELS for r in ROLES}
    if len(copies)!=4 or set(roles)!=expected or any(x!=1 for x in roles.values()) or len(set(original_materials))!=4:
        raise ValueError('Source four wheel by three roles invalid')
    if not all(x['native_channel']==channel for x in copies):raise ValueError('Crosswheel UV channel mismatch')
    # 不変契約：元メッシュ、マテリアル割当、ノード、位置、原本画像・BINはそのまま
    for key in ('meshes','nodes','accessors','bufferViews','buffers','images','textures'):
        if doc.get(key)!=orig.get(key):raise ValueError('Source GLB geometry/scene/image changed: '+key)
    doc.setdefault('extensionsUsed',[])
    if KHR not in doc['extensionsUsed']:doc['extensionsUsed'].append(KHR)
    output=pack_glb(doc,bb);check,bin2=unpack_glb(output)
    if bin2!=bb or any(check.get(k)!=orig.get(k) for k in ('meshes','nodes','accessors','bufferViews','buffers','images','textures')):
        raise ValueError('Source GLB preservation failed')
    proof={'schema':'lo4fh6.private.feow.meshblob-affine-source-uv-research.v1',
        'source_glb_sha256':sha(src_glb),'source_model_archive_sha256':sha(model_zip),'output_glb_sha256':sha(output),
        'original_bin_sha256':sha(bb),'output_bin_sha256':sha(bin2),'native_channel':channel,
        'four_sidewall_meshes_verified':len(copies),'tire_roles_verified':len(roles),
        'mesh_count':len(doc['meshes']),'source_affines':copies,
        'source_image_bytes_modified':False,'wheelstyle_position_modified':False,'tire_fitment_modified':False,
        'game_shader_equivalent':False,'xbox_approved':False,'product_default_changed':False}
    return output,proof

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-research-glb',type=Path,required=True)
    ap.add_argument('--source-glb-sha256',required=True)
    ap.add_argument('--original-tire-model-zip',type=Path,required=True)
    ap.add_argument('--channel',type=int,choices=(0,1,2),required=True)
    ap.add_argument('--output-glb',type=Path,required=True)
    ap.add_argument('--output-json',type=Path,required=True)
    a=ap.parse_args()
    if a.output_glb.exists() or a.output_json.exists():raise ValueError('Do not overwrite existing trial GLB or evidence')
    raw=a.source_research_glb.read_bytes()
    out,proof=build(raw,a.original_tire_model_zip.read_bytes(),a.channel,a.source_glb_sha256)
    a.output_glb.parent.mkdir(parents=True,exist_ok=True)
    a.output_glb.write_bytes(out)
    a.output_json.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'updated_meshes':proof['four_sidewall_meshes_verified'], 'source_glb_sha256':proof['source_glb_sha256'],
        'output_glb_sha256':proof['output_glb_sha256'],'channel':proof['native_channel'],
        'game_shader_equivalent':False},ensure_ascii=False))
if __name__=='__main__':main()
