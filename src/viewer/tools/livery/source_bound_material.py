#!/usr/bin/env python3
"""原本GameDB→Wheel ModelBin MatI ID→MaterialBin→ShaderBin→GLB UV検証。

既存の第一者 wheel_morph_internal/material_runtime と rM024 由来の署名付き
Wheel_DIFF/OPAC 証拠を再利用する。紛らわしい MatI のファイル格納順は ID ではない。
原本コード・ゲームデータの再頒布を禁止。初期OFFの比較証拠だけを返す。
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, struct, zipfile
from pathlib import Path
from tools.livery.wheel_morph_internal import wheelstyle_material_payloads
from tools.livery.material_runtime import inspect_embedded_material_instance_runtime


def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


def canonical_path(path: str) -> str:
    return path.replace('\\','/').casefold().strip('/')


def glb_source_primitives(data: bytes, source_entry: str, material_id: int) -> list[dict]:
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<I',data,8)[0] != len(data):
        raise ValueError('原本GLBのヘッダー・長さが不正')
    json_size,tag=struct.unpack_from('<II',data,12)
    if tag != 0x4E4F534A:raise ValueError('原本GLBのJSON chunkがありません')
    doc=json.loads(data[20:20+json_size])
    matched=[]
    for m in doc.get('meshes',[]):
        e=m.get('extras',{})
        if canonical_path(str(e.get('lo4_source_entry',''))) != canonical_path(source_entry):continue
        if e.get('lo4_part_type')!='WheelStyle' or e.get('lo4_wheel_material_id')!=material_id:continue
        for prim in m.get('primitives',[]):
            pe=prim.get('extras',{})
            if pe.get('lo4_wheel_material_id')!=material_id:raise ValueError('GLBのメッシュ・Primitive材質IDが不一致')
            a=prim.get('attributes',{})
            uvs=sorted(int(k.split('_')[1]) for k in a if k.startswith('TEXCOORD_') and k.split('_')[1].isdecimal())
            if 0 not in uvs:raise ValueError('装飾面にUV0がありません')
            pos=doc['accessors'][a['POSITION']]
            matched.append({'name':m.get('name'),'material_id':material_id,'material_name':e.get('lo4_wheel_material_name'),
              'wheel':pe.get('lo4_wheel_morph_identity_wheel'),'bucket':pe.get('lo4_wheel_render_pass_bucket_flags'),
              'vertex_count':pos['count'],'uv_channels':uvs})
    if not matched:raise ValueError('ModelBinの材質IDに合致するGLB meshが見つかりません')
    return matched


def verify(vehicle_zip: Path, gamedb: Path, content_root: Path, vehicle_glb: Path, wheel_source_proof: Path) -> dict:
    proof=json.loads(wheel_source_proof.read_text(encoding='utf-8'))
    if proof.get('schema')!='lo4fh6.first_party.source_bound_wheel_symbol.v1' or proof.get('standard_enabled') is not False:
        raise ValueError('署名付きWheel source proof・初期OFFが必要')
    if sha(vehicle_zip.read_bytes())!=proof.get('vehicle_zip_sha256') or sha(gamedb.read_bytes())!=proof.get('gamedb_sha256'):
        raise ValueError('GameDB/車両原本のSHAが一致しません')
    with sqlite3.connect(gamedb) as db:
        row=db.execute('SELECT MediaName,StockWheelID FROM Data_Car WHERE MediaName=?',(proof['game_media_name'],)).fetchone()
        if not row or row!=(proof['game_media_name'],proof['game_stock_wheel_id']):raise ValueError('純正WheelID原本と一致しません')
        stocked=db.execute('SELECT MediaName,IsStock FROM List_Wheels WHERE ID=?',(row[1],)).fetchone()
        if stocked is None or stocked[1]!=1 or stocked[0].casefold()!=row[0].casefold():raise ValueError('原本Stock Wheel参照不一致')
    with zipfile.ZipFile(vehicle_zip) as z:
        names={canonical_path(n):n for n in z.namelist()}
        member=names.get(canonical_path(proof['source_entry']))
        if not member:raise ValueError('Wheel ModelBin原本欠落')
        data=z.read(member)
        if sha(data)!=proof['modelbin_sha256']:raise ValueError('Wheel ModelBin SHA不一致')
        match=[]
        for rec in wheelstyle_material_payloads(data):
            mat_id=rec['material_id'];payload=rec['payload']
            runtime=inspect_embedded_material_instance_runtime(content_root,payload,material_label=rec['material_name'],vehicle_archive=vehicle_zip)
            if not runtime.get('available'):continue
            bindings={b['parameter_name']:b['path'] for b in runtime.get('material_texture_bindings',[]) if b.get('parameter_name')}
            image=bindings.get('BaseColorAlpha_Texture');alpha=bindings.get('Alpha_Texture')
            if not image or not alpha:continue
            source=proof['source_textures']
            if not canonical_path(image).endswith(canonical_path(source['diff']['entry'])):continue
            if not canonical_path(alpha).endswith(canonical_path(source['opac']['entry'])):continue
            assets={x['reference'].casefold():x for x in runtime['material_texture_assets']}
            if assets.get(image.casefold(),{}).get('sha256')!=source['diff']['sha256'] or assets.get(alpha.casefold(),{}).get('sha256')!=source['opac']['sha256']:
                raise ValueError('ShaderのTexture bindingが原本Swatch SHAと一致しません')
            match.append((rec,runtime,bindings))
        if len(match)!=1:raise ValueError(f'原本ModelBin内の装飾MatI一意性違反: {len(match)}')
        record,runtime,bindings=match[0]
    meshes=glb_source_primitives(vehicle_glb.read_bytes(),proof['source_entry'],record['material_id'])
    if len({x['wheel'] for x in meshes if x['wheel']}) < 2:raise ValueError('前輪の左右双方が認証できません')
    uv=runtime.get('effective_focus',{}).get('UVChoice_OnCh1_OffCh2Bool',{}).get('value')
    if type(uv) is not bool:raise ValueError('UVチャンネル選択の原本Shader parameterが確認できません')
    return {'schema':'lo4fh6.source_bound_wheel_material_crosswalk.v1',
     'source_entry':proof['source_entry'],'modelbin_sha256':proof['modelbin_sha256'],
     'wheel_material_id':record['material_id'],'wheel_material_name':record['material_name'],
     'material_instance_sha256':sha(record['payload']),
     'material_path':runtime['resolved_material_path'],
     'resolved_material_sha256':runtime['resolved_material_sha256'],
     'shader_family':runtime['shader_family'],'shader_sha256':runtime['shader_sha256'],
     'shader_xml_sha256':runtime['shader_xml_sha256'],
     'texture_binding':{k:bindings[k] for k in ('BaseColorAlpha_Texture','Alpha_Texture')},
     'source_texture_sha256':{k:proof['source_textures'][k]['sha256'] for k in ('diff','opac')},
     'uv_choice_parameter':'UVChoice_OnCh1_OffCh2Bool',
     'uv_choice_value':uv,
     'glb_matched_primitive_count':len(meshes),'glb_source_primitives':meshes,
     'visible_material_slot_verified':True,'render_bucket_requires_source_depth_test':True,
     'render_depth_and_polygon_bias_source_approved':False,
     'original_geometry_unchanged':True,'stock_wheel_xbox_verified':False,
     'windows_verified':False,'standard_enabled':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--vehicle-zip',type=Path,required=True);p.add_argument('--gamedb',type=Path,required=True)
    p.add_argument('--content-root',type=Path,required=True);p.add_argument('--base-glb',type=Path,required=True)
    p.add_argument('--wheel-source-proof',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();v=verify(a.vehicle_zip,a.gamedb,a.content_root,a.base_glb,a.wheel_source_proof)
    if a.output.exists():raise SystemExit('上書き拒否: 出力先ファイルが存在します')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(v,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
