#!/usr/bin/env python3
"""原本Tireの側面文字（TextTexture 2枚）を、受入済みGLBの文字MatIへ接続する。

受入済みGLB・原本・製品既定は変更しない。Texture 2枚とMeshBlobごとのUV affineは
原本ModelBinから照合する。実行時のCarParametersDataは推定値であり、ゲーム値と称さない。
当初はstreet_FE_OW（FEOW）1原本専用だった。原本MatIのTextSwitch=1から作った証拠で
同じ処理を全Tireへ一般化した（Texture SHAは証拠から、件数は4輪×文字MatI数）。
"""
from __future__ import annotations
import hashlib, io, json, os, struct, zipfile
from pathlib import Path
from .source_tire_mati_sidewall_preview import (
    read_glb, source_manifest, read_original_text_extract, attach_variant, TEXT_PARAMS,
    SourceTextError, sha, _glb, verify_original_shader
)
from .source_tire_mesh_uv_affine import mesh_affines
from . import wheel_morph_internal as wm

ROLE_WHEELS=('front_left','front_right','rear_left','rear_right')
# FEOW（street_FE_OW）の文字Texture 2枚。回帰テストの照合用で、処理の条件には使わない。
T30_SHA='d56d24584af7dc779a2a51a825d9f673f092807e12d97891bbeb6d74a2d9d72c'
T29_SHA='d6e93c32f243dfe6de2ad651e6635ddac14b8ded3e0e032cbe8484ab3f2a53d4'


def build_from_originals(glb_path:Path, model_zip:Path, source_report_path,
                         extracted_zip:Path,shader_source_zip:Path) -> tuple[bytes,dict]:
    report,lookup=source_manifest(model_zip,source_report_path)
    verify_original_shader(shader_source_zip,report)
    requested=set(report['unique_sidewall_mati_text_swatch_paths'])
    textures=read_original_text_extract(extracted_zip,requested)
    original=glb_path.read_bytes()
    baseline_doc,baseline_bin=read_glb(original)
    preview,ab=attach_variant(original,report,lookup,textures,TEXT_PARAMS[0])
    doc,bb=read_glb(preview)
    if ab['sidewall_mesh_count']<4:
        raise SourceTextError('原本の文字MatIが4輪分ありません')
    material_rows=[]
    bywheel={}
    original_models={}
    with zipfile.ZipFile(model_zip) as z:
        for m in report['source_mati_entries']:
            original_models[m['modelbin_sha256']]=z.read(m['source_member'])
    index_for_29={}
    for mesh in doc.get('meshes',[]):
        x=mesh.get('extras',{})
        if x.get('lo4_part_type')!='Tire' or x.get('lo4_role')=='hidden':
            continue
        model_sha=x.get('lo4_tire_original_modelbin_sha256')
        if model_sha not in lookup:
            raise SourceTextError('Tire original ModelBin SHA invalid')
        record=lookup[model_sha]['texts'].get(x.get('lo4_tire_original_material_id'))
        if record is None:
            continue
        wheel=x.get('lo4_tire_source_wheel')
        if wheel not in ROLE_WHEELS:
            raise SourceTextError('Unverified original wheel')
        if model_sha not in original_models or sha(original_models[model_sha])!=model_sha:
            raise SourceTextError('Tire original ModelBin SHA invalid')
        t29_path=record['slots'][TEXT_PARAMS[1]]['source_relative'].casefold()
        t30_path=record['slots'][TEXT_PARAMS[0]]['source_relative'].casefold()
        t29_sha=textures[t29_path]['sha256'];t30_sha=textures[t30_path]['sha256']
        if t29_path not in index_for_29:
            image=textures[t29_path]['rgba_png']
            bb.extend(b'\0'*(-len(bb)%4))
            offset=len(bb);bb.extend(image)
            v=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(image)})
            i=len(doc['images']);doc['images'].append({'bufferView':v,'mimeType':'image/png',
                'extras':{'original_swatch_sha256':t29_sha,'original_mati_parameter':TEXT_PARAMS[1]}})
            t=len(doc['textures']);doc['textures'].append({'source':i})
            index_for_29[t29_path]=t
        if len(mesh.get('primitives',[]))!=1:
            raise SourceTextError('Multiple sidewall primitives are not supported without evidence')
        prim=mesh['primitives'][0]
        if 'TEXCOORD_0' not in prim.get('attributes',{}):
            raise SourceTextError('Original sidewall UV0 absent')
        blob,affine=mesh_affines(wm._parse_blobs(original_models[model_sha]),
                                record['material_id'],prim,doc,bb)
        uv=[float(v) for v in affine[0]]
        if any(abs(v)>16 for v in uv):raise SourceTextError('Unbounded source affine')
        mat=doc['materials'][prim['material']]
        extras=mat.setdefault('extras',{})
        if extras.get('source_swatch_sha256')!=t30_sha or extras.get('original_modelbin_sha256')!=model_sha:
            raise SourceTextError('Signed t30 material proof lost')
        tiling=[float(v) for v in record['text_uv_tiling']]
        slide=float(record['text_slide'])
        if (len(tiling)!=2 or any(not 0.001<=v<=100 for v in tiling)
                or not -16<=slide<=16):
            raise SourceTextError('原本MatIの文字繰り返し数/ずらし量が範囲外')
        mat['emissiveTexture']={'index':index_for_29[t29_path],'texCoord':0}
        mat['emissiveFactor']=[0,0,0]
        extras.update({'lo4fh6_original_feow_two_textures':True,
           'feow_dxil_t30_swatch_sha256':t30_sha,'feow_dxil_t29_swatch_sha256':t29_sha,
           # 原本MatI→親MaterialBin→ShaderBin DFPRで解決した文字の繰り返し数とずらし量。
           'lo4fh6_source_text_uv_tiling':tiling,'lo4fh6_source_text_slide':slide,
           'lo4fh6_source_text_mati_role':record['role'],
           'feow_dxil_original_mesh_affine_uv0':uv,
           'feow_dxil_source_meshblob_index':int(blob.index),
           'feow_dxil_original_texcoord':'TEXCOORD_0',
           'feow_dxil_shader_pso_sha256':'a320f94b94ba20631e89c3a0108a6032c39afd8646272dd3feb11e93b6f7d59f',
           'feow_dxil_shader_vso_sha256':'096800d7498a51dc453295af36d1bc963ed62cee3da5ff2c8bae51a66b273dda',
           'feow_dxil_runtime_source':'UNKNOWN_NOT_IN_MODEL_ASSETS',
           'feow_dxil_shader_equivalent':False,
           'feow_dxil_product_default_on':False})
        material_rows.append({'wheel':wheel,'original_meshblob_index':blob.index,
            'modelbin_sha256':model_sha,'material_id':record['material_id'],
            'source_affine_uv0':uv,'source_images':[t30_sha,t29_sha],
            'text_uv_tiling':tiling,'text_slide':slide})
        bywheel.setdefault(wheel,[]).append(mat)
    if set(bywheel)!=set(ROLE_WHEELS) or len({len(v) for v in bywheel.values()})!=1:
        raise SourceTextError('原本の文字MatIが4輪で揃っていません')
    out=_glb(doc,bb)
    post,post_bin=read_glb(out)
    if bytes(post_bin[:len(baseline_bin)])!=bytes(baseline_bin):
        raise SourceTextError('Original accepted geometry BIN modified')
    if post['nodes']!=baseline_doc['nodes'] or post['accessors']!=baseline_doc['accessors']:
        raise SourceTextError('Accepted node pose or accessors modified')
    text_keys={(k,mid) for k in lookup for mid in lookup[k]['texts']}
    for before,after in zip(baseline_doc['meshes'],post['meshes']):
        bx=before.get('extras',{})
        if (bx.get('lo4_part_type')!='Tire'
                or (bx.get('lo4_tire_original_modelbin_sha256'),bx.get('lo4_tire_original_material_id')) not in text_keys):
            if before!=after:raise SourceTextError('Unrelated geometry or materials modified')
    proof={'schema':'lo4fh6.original-feow-dxil-sidewall-two-textures-glb.v1',
      'original_glb_sha256':sha(original),'research_glb_sha256':sha(out),
      'source_original2_zip_sha256':sha(extracted_zip.read_bytes()),
      'source_tire_modelbin_zip_sha256':sha(model_zip.read_bytes()),
      'original_shaderbin_sha256':report['shaderbin_sha256'],
      'shader_source_archive_sha256':sha(shader_source_zip.read_bytes()),
      'original_wheelstyle_mesh_count':sum(m.get('extras',{}).get('lo4_part_type')=='WheelStyle' for m in doc['meshes']),
      'tire_mesh_count':sum(m.get('extras',{}).get('lo4_part_type')=='Tire' for m in doc['meshes']),
      'sidewall_count':len(material_rows),
      'source_texture_sha256':sorted({x for row in material_rows for x in row['source_images']}),
      'source_mesh_affine':material_rows,'original_geometry_bin_prefix_identical':True,
      'runtime_carparameters_proven':False,'default_off':True,'xbox_approved':False,'windows_verified':False}
    return out,proof


def cached_original2_research_glb(source_glb:Path, source_model_zip:Path,
                                  source_report,source_extracted_zip:Path,
                                  output_root:Path,shader_source_zip:Path)->Path:
    paths=[source_glb,source_model_zip,source_extracted_zip,shader_source_zip]
    if not isinstance(source_report,dict):paths.append(source_report)
    if not all(p.is_file() and not p.is_symlink() for p in paths):
        raise SourceTextError('Original source paths are missing or links')
    signature=sha(source_glb.read_bytes())[:16]+'-'+sha(source_extracted_zip.read_bytes())[:16]+'-'+sha(shader_source_zip.read_bytes())[:12]
    # r2: 原本MatIの文字繰り返し数・ずらし量をextrasへ記録（それ以前のcacheは再利用しない）。
    result=output_root/'FEOW-DXIL-Research-r2'/signature
    target=result/'feow-original2-dxil-sidewall-RESEARCH.glb'
    proof_file=result/'feow-original2-dxil-sidewall-RESEARCH.json'
    # 差分で保存する（車体の形の GLB と同じ中身を持たない。組み立てた GLB は元と 1 バイトも違わない。2026-11-20）。
    # 土台は、入力の GLB（組み立てた標準タイヤ）の名前から引く。分からなければ従来どおり丸ごと保存する。
    from .glb_delta import (MATERIALIZED_DIR, GlbDeltaBaseMismatch, GlbDeltaError, delta_base_for, materialize,
                            place_materialized, write_delta_file)
    delta_file=result/'feow-original2-dxil-sidewall-RESEARCH.glbdelta'
    store=output_root/MATERIALIZED_DIR
    base=delta_base_for(source_glb.name)
    if result.exists():
        if not (proof_file.is_file() and (target.is_file() or delta_file.is_file())):
            raise SourceTextError('Incomplete research cache; no overwrite')
        proof=json.loads(proof_file.read_text(encoding='utf-8'))
        if proof.get('original_glb_sha256')!=sha(source_glb.read_bytes()):
            raise SourceTextError('Research cache signature mismatch; no overwrite')
        if target.is_file():
            if proof.get('research_glb_sha256')!=sha(target.read_bytes()):
                raise SourceTextError('Research cache signature mismatch; no overwrite')
            return target
        if base is not None:
            try:
                return materialize(delta_file,base,store,str(proof.get('research_glb_sha256') or ''))
            except GlbDeltaBaseMismatch:
                pass
            except (GlbDeltaError,OSError,ValueError) as exc:
                raise SourceTextError('Research cache delta mismatch; no overwrite') from exc
        # 土台が無い・作り直された：同じ入力から作り直す（出来上がりは記録の SHA と同じでなければ止める）
        payload,_=build_from_originals(source_glb,source_model_zip,source_report,source_extracted_zip,shader_source_zip)
        if sha(payload)!=proof.get('research_glb_sha256'):
            raise SourceTextError('Research cache signature mismatch; no overwrite')
        if base is not None:
            write_delta_file(delta_file,payload,base.read_bytes())
            return place_materialized(store,payload,sha(payload),base)
        target.write_bytes(payload)
        return target
    payload,evidence=build_from_originals(source_glb,source_model_zip,source_report,source_extracted_zip,shader_source_zip)
    result.mkdir(parents=True,exist_ok=False)
    if base is not None:
        manifest=write_delta_file(delta_file,payload,base.read_bytes())
        evidence=dict(evidence,stored_as_glb_delta=True,glb_delta_base_sha256=manifest['base_sha256'])
        proof_file.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return place_materialized(store,payload,sha(payload),base)
    target.write_bytes(payload)
    proof_file.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return target
