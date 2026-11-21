#!/usr/bin/env python3
"""原本Tire MatI文字Texture2枚から、明示的なUV0研究A/B GLBを作る。

Game original SWATCh images are never distributed by this script, and the source
viewer / successful Wheel+Tire GLB is never overwritten. The resulting UV0 PBR
preview does NOT represent the FH6 multilayer shader or Xbox parity.
"""
from __future__ import annotations
from .png_settings import PNG_COMPRESS_LEVEL

import argparse
import copy
import hashlib
import io
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

from tools.livery.fh6_swatch import decode_swatch_image
from tools.livery.source_tire_glb_bridge import read_glb
from tools.livery.portable_mesh_converter import seal_firstparty_chassis_metadata

SCHEMA = 'lo4fh6.private.tire-source-mati-texture-override-graph.v1'
TEXT_PARAMS = ('TextTexture0_TyreSideWallTextTexture', 'TextTexture_TyreSideWallTextTexture')
SOURCE_IMAGE_MAX = 32*1024*1024
SHA = re.compile(r'^[0-9a-f]{64}$')
# 側面文字の原本パラメーター（car_tires_pg.shaderbin.xmlの完全名）。
TEXT_SWITCH_PARAM = 'TextSwitch_TyreSideWallTextBool'
TEXT_UV_TILING_PARAM = 'TextUVTiling_TyreSideWallTextVector2'
TEXT_SLIDE_PARAM = 'TextSlideAmount_TyreSideWallText_floatVal'


class SourceTextError(ValueError):
    """原本同定・Texture参照の根拠が揃わない場合は出力を拒否する。"""


class SourceTextTextureMissingError(SourceTextError):
    """原本MatIが参照する文字Textureが原本Textures.zipに無い（原本アセット側の参照不整合）。

    例：GYWhite/OW_GYWhiteの tire_gy_white_letters_diff1_a57754b1 は原本に無く、
    同じGUIDは tire_gy_yellow_letters_diff1 が持つ。ゲームの解決方法（名前/GUID）は
    根拠が無いため推測で別Textureを当てず、呼出し側は文字なしの表示を明示して続行する。
    """


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _crc_hex(name: str) -> str:
    """証拠JSONと同じ表記（CRC32のリトルエンディアン16進）。"""
    return zlib.crc32(name.encode('ascii')).to_bytes(4, 'little').hex()


def _text_value(rows: dict, name: str, kind: int):
    row = rows.get(f'{zlib.crc32(name.encode("ascii")):08x}')
    if row is None:
        return None
    if row['type'] != kind:
        raise SourceTextError('原本MatIの側面文字パラメーター型が不一致: ' + name)
    return row['value']


def derive_text_sidewall_report(model_zip: Path, shader_zip: Path,
                                materials_zip: Path) -> dict | None:
    """原本Tire ZIPの側面MatIから、側面文字の出典証拠を原本だけで作る。

    以前はstreet_FE_OW 1原本の固定証拠JSON（feow_mati_original_evidence.json）だけを
    受け付けていた。同じ項目（ModelBin・MatI・MTPRのSHA、TextSwitch、文字Texture2枚）を
    原本から求めるため、street_FE_OWでは固定JSONと同じ値になる（テストで照合）。
    文字MatIは役割名（sidewall/whitewall等）でなく原本MatIのTextSwitch=1で判定する。
    判定はLOD0メッシュが実際に使うMatIに限る（OW_offroadMT_Dually等は、TextSwitch=1の
    MatIをLOD0が使わず、LOD0はTextSwitch=0の別MatIを使う。表示上は文字なし）。
    使用する全ModelBinに文字MatIが無ければNone（文字なしTire）。一部のModelBinだけにある、
    文字Textureの欠落・型不一致は停止する。1つのModelBinに文字MatIが2件ある原本
    （OW_b_Horizon等）もあるため、件数はModelBin間で一致することだけを要求する。
    文字の繰り返し数とずらし量はMatI→親MaterialBin→ShaderBin DFPRの順に解決する。
    """
    from .material_runtime import _game_refs_from_material
    from .source_tire_local_runtime import (
        LocalTireSourceError, _load_source_meshes, _original_tire_model_entries,
        tire_archive_model_name,
    )
    from .source_tire_original_normal import (
        OriginalTireNormalError, _parent_materialbin_param,
    )
    from .source_tire_shader_binding import (
        TireBindingError, _read_parameters, shader_dfpr_scalar_default,
    )
    from .source_tire_texture_bridge import _texture_member
    from . import wheel_morph_internal as wm
    raw = model_zip.read_bytes()
    with zipfile.ZipFile(shader_zip) as z:
        shader = z.read('car_tires_pg.shaderbin')
        shader_xml = z.read('car_tires_pg.shaderbin.xml')
    # GLBへ変換される原本ModelBin（1/2/4件）と同じ選び方でMatIを読む。
    mats, members, lod0_ids = {}, {}, {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if z.testzip() is not None:
                raise SourceTextError('原本Tire ZIP CRC不一致')
            entries_by_role = _original_tire_model_entries(z, tire_archive_model_name(model_zip))
            for name in dict.fromkeys(item.filename for item in entries_by_role.values()):
                data = z.read(name)
                blobs = [b for b in wm._parse_blobs(data)
                         if b.tag == 0x4D617449 and b.identifier is not None]
                if len(blobs) != len({int(b.identifier) for b in blobs}):
                    raise SourceTextError('原本Tire MatIのIDが重複しています')
                digest = sha(data)
                if digest in mats:
                    raise SourceTextError('原本Tire ModelBinのSHAが重複しています')
                mats[digest] = {int(b.identifier): (b.name, bytes(b.data)) for b in blobs}
                members[digest] = name
                # GLBへ変換されるLOD0メッシュ（同じ第一者デコーダー）が使うMatIだけを文字の対象にする。
                lod0_ids[digest] = {int(m['material_id']) for m in _load_source_meshes(data, 'L')}
    except LocalTireSourceError as exc:
        raise SourceTextError('原本Tire ModelBinの構成を特定できません: ' + str(exc)) from exc
    entries, per_model, unique = [], [], set()
    try:
        switch_default = shader_dfpr_scalar_default(shader, shader_xml, TEXT_SWITCH_PARAM, 3)
        for digest in sorted(mats):
            if digest not in members:
                raise SourceTextError('原本Tire ModelBinの名前を特定できません')
            materials, text_count = [], 0
            for mid, (role, data) in sorted(mats[digest].items()):
                mtpr = [bytes(b.data) for b in wm._parse_blobs(data) if b.tag == 0x4D545052]
                if len(mtpr) != 1:
                    raise SourceTextError('原本MatIのMTPRが一意ではありません')
                rows = {r['parameter_crc32']: r for r in _read_parameters(mtpr[0])}
                switch = _text_value(rows, TEXT_SWITCH_PARAM, 3)
                record = {'original_mati_name': role, 'original_mati_id': int(mid),
                          'mati_sha256': sha(data), 'text_switch': switch,
                          'text_texture_overrides': []}
                if switch == 1 and int(mid) not in lod0_ids[digest]:
                    # LOD0で使われない文字MatIは描画されないため、文字の対象にしない。
                    switch = None
                    record['text_switch'] = None
                    record['text_switch_unused_by_lod0'] = True
                if switch == 1:
                    text_count += 1
                    for param in TEXT_PARAMS:
                        value = _text_value(rows, param, 6)
                        if not isinstance(value, str) or not value:
                            raise SourceTextError('原本側面文字Texture入力が2件ではありません')
                        relative = _texture_member(value).casefold()
                        unique.add(relative)
                        record['text_texture_overrides'].append({
                            'parameter_name': param, 'source_path': value,
                            'parameter_id_hex': _crc_hex(param),
                            'override_record_sha256': sha(mtpr[0]),
                            'source_relative': relative})
                    refs = _game_refs_from_material(data, '.materialbin')
                    if len(refs) != 1:
                        raise SourceTextError('原本側面MatIの親MaterialBinが一意ではありません')
                    leaf = refs[0].replace(chr(92), '/').casefold().rsplit('/', 1)[-1]
                    member = '_fmnext/tires/' + leaf
                    for key, param, kind in (('text_uv_tiling', TEXT_UV_TILING_PARAM, 11),
                                             ('text_slide', TEXT_SLIDE_PARAM, 2)):
                        value, origin = _text_value(rows, param, kind), 'modelbin_mati'
                        if value is None:
                            value, _ = _parent_materialbin_param(
                                materials_zip, member, param, shader_xml, kind)
                            origin = 'parent_materialbin'
                        if value is None:
                            value = shader_dfpr_scalar_default(shader, shader_xml, param, kind)
                            origin = 'shaderbin_dfpr_default'
                        record[key] = list(value) if kind == 11 else float(value)
                        record[key + '_origin'] = origin
                materials.append(record)
            per_model.append(text_count)
            entries.append({'source_member': members[digest], 'modelbin_sha256': digest,
                            'materials': materials})
    except (TireBindingError, OriginalTireNormalError) as exc:
        raise SourceTextError('原本側面文字の出典照合に失敗: ' + str(exc)) from exc
    if not per_model or all(n == 0 for n in per_model):
        return None
    if any(n == 0 or n != per_model[0] for n in per_model):
        raise SourceTextError('原本Tireの文字MatI（TextSwitch=1）の件数がModelBinごとに異なります: '
                              + repr(per_model))
    return {'schema': SCHEMA, 'model_archive_sha256': sha(raw),
            'shaderbin_sha256': sha(shader),
            'text_switch_shader_default': bool(switch_default),
            'text_switch_parameter_hash': _crc_hex(TEXT_SWITCH_PARAM),
            'shader_text_param_names': list(TEXT_PARAMS),
            'shader_text_param_hashes': [_crc_hex(x) for x in TEXT_PARAMS],
            'source_mati_entries': entries,
            'unique_sidewall_mati_text_swatch_paths': sorted(unique),
            'source_derivation': 'original-modelbin-mati-shaderbin-dynamic-v1',
            'game_shader_pixel_equivalence': False, 'viewer_default_changed': False,
            'third_party_code_included': False}


def source_manifest(source_model_zip: Path, report_path) -> tuple[dict, dict]:
    """側面文字の出典証拠（固定JSONのパス、または原本から作った辞書）を原本と照合する。"""
    if isinstance(report_path, dict):
        report = report_path
    else:
        report=json.loads(report_path.read_text(encoding='utf-8-sig'))
    if report.get('schema')!=SCHEMA or report.get('text_switch_shader_default') is not False:
        raise SourceTextError('原本MatI側面文字の証拠形式/Shader既定OFFが不正')
    for key in ('shaderbin_sha256','model_archive_sha256'):
        if not SHA.fullmatch(str(report.get(key,''))):raise SourceTextError('出典SHAが不正: '+key)
    raw=source_model_zip.read_bytes()
    if sha(raw)!=report['model_archive_sha256']:
        raise SourceTextError('原本Tire ModelBin ZIPのSHAが出典証拠と異なります')
    models=report.get('source_mati_entries')
    # 原本Tireは1/2/4 ModelBin構成（単一・左右・四輪別）がある。
    if not isinstance(models,list) or len(models) not in (1,2,4):
        raise SourceTextError('原本TireのModelBinが1/2/4件ではありません')
    lookup={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:raise SourceTextError('原本Tire ZIP CRC不一致')
        names=z.namelist()
        for model in models:
            member=model.get('source_member')
            digest=model.get('modelbin_sha256')
            if not member or member not in names or not SHA.fullmatch(str(digest or '')):
                raise SourceTextError('原本Tire ModelBin出典に欠落があります')
            if sha(z.read(member))!=digest:
                raise SourceTextError('原本Tire ModelBin実バイトSHA不一致: '+str(member))
            mats=model.get('materials')
            if not isinstance(mats,list):raise SourceTextError('原本MatI記録が欠落')
            side=[m for m in mats if m.get('text_switch')==1]
            if not side:
                raise SourceTextError('原本の文字MatI（TextSwitch=1）がありません')
            texts={}
            for item in side:
              by={t['parameter_name']:t for t in item.get('text_texture_overrides',[])}
              if set(by)!=set(TEXT_PARAMS):raise SourceTextError('原本側面文字Texture入力が2件ではありません')
              for param in TEXT_PARAMS:
                t=by[param]
                if not SHA.fullmatch(str(t.get('override_record_sha256',''))):
                    raise SourceTextError('原本MatI Textureパラメーター署名不正')
                relative=t.get('source_relative','')
                # 文字Textureはtires/swatches以外（globaltextures等）にもある。Textures内の安全な相対パスのみ。
                if (not isinstance(relative,str) or relative.startswith('/')
                        or '..' in relative.split('/') or not relative.endswith('.swatchbin')):
                    raise SourceTextError('原本MatI SwatchBin参照が不正')
              mid=int(item['original_mati_id'])
              if mid in texts:raise SourceTextError('原本の文字MatI IDが重複')
              texts[mid]={'material_id':mid,'slots':by,'role':item.get('original_mati_name'),
                          'mati_sha256':item['mati_sha256'],
                          # 固定JSON（street_FE_OW）には無い。原本MatIの値（0.25,1.2/-0.28）と同じ。
                          'text_uv_tiling':item.get('text_uv_tiling',[0.25,1.2]),
                          'text_slide':item.get('text_slide',-0.28)}
            if digest in lookup:raise SourceTextError('左右Tire ModelBin SHA重複')
            lookup[digest]={'member':member,'texts':texts}
    expected={rec['slots'][p]['source_relative'].casefold()
              for k in lookup for rec in lookup[k]['texts'].values() for p in TEXT_PARAMS}
    if set(report.get('unique_sidewall_mati_text_swatch_paths',[]))!=expected or not expected:
        raise SourceTextError('Shader/MatIの原本文字Textureと証拠一覧が不一致')
    return report,lookup


def verify_original_shader(source_shader_zip:Path, report:dict) -> str:
    """元car_tires_pg ShaderBinを保存済み原本ZIP実バイトから照合。"""
    with zipfile.ZipFile(source_shader_zip) as outer:
        if outer.testzip() is not None:raise SourceTextError('FH6原本Shader ZIP CRC不一致')
        if 'shaders/car_tires_pg.zip' in outer.namelist():
            with zipfile.ZipFile(io.BytesIO(outer.read('shaders/car_tires_pg.zip'))) as inner:
                if inner.testzip() is not None:raise SourceTextError('car_tires_pg family ZIP CRC不一致')
                raw=inner.read('car_tires_pg.shaderbin')
        else:
            raw=outer.read('car_tires_pg.shaderbin')
    digest=sha(raw)
    if digest!=report['shaderbin_sha256']:
        raise SourceTextError('原本ShaderBin実バイトSHA不一致')
    return digest


def read_original_text_extract(extracted_zip:Path, expected: set[str]) -> dict[str,dict]:
    """13:28版既存r02選択抽出器の PRIVATE-EXTRACTION-MANIFEST を検証。"""
    out={}
    with zipfile.ZipFile(extracted_zip) as z:
        if z.testzip() is not None:raise SourceTextError('原本文字2件の抽出ZIP CRC不一致')
        try: proof=json.loads(z.read('PRIVATE-EXTRACTION-MANIFEST.json'))
        except (KeyError,ValueError) as exc:raise SourceTextError('既存r02抽出証拠がありません') from exc
        if (proof.get('schema')!='lo4fh6.private.selective_texture_extract.v1'
            or proof.get('source_archive_name','').casefold()!='textures.zip'
            or proof.get('requested_count')!=len(expected)
            or proof.get('extracted_count')!=len(expected)
            or proof.get('missing') or len(proof.get('files',[]))!=len(expected)):
            raise SourceTextError('FH6原本Textures.zipの文字Texture選択抽出が全件ではありません')
        if {str(x.get('requested','')).casefold() for x in proof['files']}!=expected:
            raise SourceTextError('原本抽出文字2件の参照がMatIと一致しません')
        for row in proof['files']:
            path=row.get('requested','').casefold()
            member=row.get('output_member','')
            digest=row.get('sha256','')
            if (path not in expected or path in out or not member.startswith('assets/')
                    or member[7:].casefold()!=path or not SHA.fullmatch(digest)
                    or row.get('match_method')!='path-suffix'):
                raise SourceTextError('原本抽出した文字画像のpath/shaがMatIと一致しません')
            info=z.getinfo(member)
            if not 0<info.file_size<=SOURCE_IMAGE_MAX or info.file_size!=row.get('size_bytes'):
                raise SourceTextError('原本文字SwatchBinサイズが不正')
            data=z.read(info)
            if sha(data)!=digest:raise SourceTextError('抽出証拠とSwatchBin実SHA不一致')
            img,detail=decode_swatch_image(data)
            if img is None:raise SourceTextError('元SwatchBinが画像として復号できません')
            if not 16<=img.width<=8192 or not 16<=img.height<=8192:
                img.close();raise SourceTextError('元SwatchBin画像寸法が不正')
            png_stream=io.BytesIO()
            img.convert('RGBA').save(png_stream,format='PNG',compress_level=PNG_COMPRESS_LEVEL)
            dim=[img.width,img.height];img.close()
            out[path]={'sha256':digest,'size':len(data),'rgba_png':png_stream.getvalue(),
                       'source_dimensions':dim}
    if set(out)!=expected:raise SourceTextError('左右MatI原本文字画像に欠落があります')
    return out


def _glb(doc:dict,buf:bytearray) -> bytes:
    buf.extend(b'\0'*(-len(buf)%4))
    doc['buffers'][0]['byteLength']=len(buf)
    # 第一者GLBは中立メタデータを永続化。旧名はFEOW検証中のメモリ内互換だけ。
    # 出力後の回帰照合がdocを使うため、作業用GLB辞書は変更しない。
    serializable=seal_firstparty_chassis_metadata(copy.deepcopy(doc))
    jb=json.dumps(serializable,ensure_ascii=False,separators=(',',':')).encode('utf8')
    jb+=b' '*(-len(jb)%4)
    return b'glTF'+struct.pack('<II',2,12+8+len(jb)+8+len(buf))+struct.pack('<I4s',len(jb),b'JSON')+jb+struct.pack('<I4s',len(buf),b'BIN\0')+buf


def attach_variant(original_glb:bytes, source_report:dict, lookups:dict,
                   textures:dict, parameter:str) -> tuple[bytes,dict]:
    """原本Tire sidewallの材質4枚だけを別GLB上で比較変更。"""
    if parameter not in TEXT_PARAMS:raise SourceTextError('研究Textureパラメーターが未対応')
    doc,binary=read_glb(original_glb)
    before=copy.deepcopy(doc)
    if not isinstance(doc.get('materials'),list) or not isinstance(doc.get('meshes'),list):
        raise SourceTextError('元GLB構造が不正')
    buffer=bytearray(binary)
    doc.setdefault('images',[]);doc.setdefault('textures',[]);doc.setdefault('bufferViews',[])
    image_map={};updated=0;kept_wheels=0;kept_other_tires=0
    sidewall_slots=[]
    for mesh_index,mesh in enumerate(doc['meshes']):
        ex=mesh.get('extras',{})
        part=ex.get('lo4_part_type')
        if part=='WheelStyle':kept_wheels+=1
        if part!='Tire' or ex.get('lo4_role')=='hidden':continue
        source_hash=ex.get('lo4_tire_original_modelbin_sha256')
        role=ex.get('lo4_tire_original_material_name')
        material_id=ex.get('lo4_tire_original_material_id')
        if source_hash not in lookups:raise SourceTextError('GLB元TireのModelBin SHAが出典にありません')
        expected=lookups[source_hash]['texts'].get(material_id)
        if expected is None:
            kept_other_tires+=1
            continue
        if role!=expected['role']:
            raise SourceTextError('GLB元Tireの文字MatIの役割名が出典と異なります')
        image_path=expected['slots'][parameter]['source_relative'].casefold()
        if image_path not in textures:raise SourceTextError('原本MatI由来文字SwatchBinが不在')
        img_data=textures[image_path]
        if image_path not in image_map:
            start=(len(buffer)+3)//4*4;buffer.extend(b'\0'*(start-len(buffer)))
            buffer.extend(img_data['rgba_png'])
            view=len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':len(img_data['rgba_png'])})
            im_idx=len(doc['images'])
            doc['images'].append({'bufferView':view,'mimeType':'image/png',
                'extras':{'original_swatch_sha256':img_data['sha256'],
                          'original_mat_i_parameter':parameter,'research_only':True}})
            tex_idx=len(doc['textures'])
            doc['textures'].append({'source':im_idx})
            image_map[image_path]=tex_idx
        for prim in mesh.get('primitives',[]):
            if not isinstance(prim.get('attributes',{}).get('TEXCOORD_0'),int):
                raise SourceTextError('sidewall元Tire UV0が存在しません')
            old_id=prim.get('material')
            if not isinstance(old_id,int) or not 0<=old_id<len(before['materials']):
                raise SourceTextError('sidewall元材質が不正')
            mat=copy.deepcopy(before['materials'][old_id])
            mat['name']='Research-only MatI Sidewall '+parameter
            pbr=mat.setdefault('pbrMetallicRoughness',{})
            pbr['baseColorTexture']={'index':image_map[image_path],'texCoord':0}
            pbr['baseColorFactor']=[1,1,1,1]
            mat['extras']={'lo4fh6_source_tire_sidewall_text_research':True,
                  'original_mati_parameter':parameter,
                  'original_mati_id':material_id,
                  'original_modelbin_sha256':source_hash,
                  'source_shaderbin_sha256':source_report['shaderbin_sha256'],
                  'source_swatch_sha256':img_data['sha256'],
                  'source_mati_text_switch':1,'source_texcoord':'UV0_RESEARCH_UNVERIFIED',
                  'shader_equivalent':False,'xbox_approved':False}
            prim['material']=len(doc['materials']);doc['materials'].append(mat)
            updated+=1
            sidewall_slots.append({'mesh':mesh_index,'member':lookups[source_hash]['member'],
                                   'sha256':img_data['sha256']})
    # 4輪×文字MatI数。FEOW（street_FE_OW）は側面4＋その他8。
    if updated < 4 or kept_wheels<1:
        raise SourceTextError(f'4輪sidewall一致数が不正: sidewall={updated}, other_tires={kept_other_tires}, wheels={kept_wheels}')
    out=_glb(doc,buffer)
    post,post_bin=read_glb(out)
    if bytes(post_bin[:len(binary)])!=bytes(binary):raise SourceTextError('入力GLB BINが改変されました')
    if post['meshes'][:len(before['meshes'])]!=doc['meshes']:
        raise SourceTextError('出力GLBのメッシュ構造が不一致')
    # 文字MatIは役割名でなく(ModelBin SHA, MatI ID)で判定する（whitewall等、ModelBin内2件）。
    text_keys={(k,mid) for k in lookups for mid in lookups[k]['texts']}
    for original,changed in zip(before['meshes'],post['meshes']):
        ox=original.get('extras',{})
        if (ox.get('lo4_part_type')!='Tire'
            or (ox.get('lo4_tire_original_modelbin_sha256'),ox.get('lo4_tire_original_material_id')) not in text_keys):
            if original!=changed:raise SourceTextError('Wheel・車体・Treadの元GLBメッシュが変更されました')
    proof={'schema':'lo4fh6.private.tire-sidewall-mati-text-uv0-research.v1',
           'status':'RESEARCH_ONLY_NOT_DEFAULT','original_glb_sha256':sha(original_glb),
           'research_glb_sha256':sha(out),'source_model_zip_sha256':source_report['model_archive_sha256'],
           'source_shaderbin_sha256':source_report['shaderbin_sha256'],
           'text_parameter':parameter,'sidewall_mesh_count':updated,
           'other_tire_unchanged':kept_other_tires,'wheel_meshes_unchanged':kept_wheels,
           'original_binary_prefix_identical':True,'original_uv0_source_kept':True,
           'image_count':len(image_map),'image_source_sha256':[x['sha256'] for x in textures.values()],
           'source_variants':sidewall_slots,'xbox_material_equivalent':False,
           'shader_text_composite_verified':False,'product_default_changed':False,
           'mat_i_texture_paths_verified':True,'windows_gpu_verified':False}
    return out,proof


def build(source_glb:Path, source_model_zip:Path, source_report:Path,
          source_extracted_zip:Path, output_dir:Path) -> list[dict]:
    if output_dir.exists():raise SourceTextError('研究A/B出力フォルダーを上書きしません')
    report,lookup=source_manifest(source_model_zip,source_report)
    expected=set(report['unique_sidewall_mati_text_swatch_paths'])
    image_data=read_original_text_extract(source_extracted_zip,expected)
    original=source_glb.read_bytes()
    result=[]
    # 先に両方をメモリー上で完全生成し、片側だけの成功状態を作らない。
    for index,param in enumerate(TEXT_PARAMS):
        data,proof=attach_variant(original,report,lookup,image_data,param)
        result.append({'name':f'source-tire-sidewall-mati-text-slot{index}-UV0-research.glb',
                       'data':data,'proof':proof})
    output_dir.mkdir(parents=True,exist_ok=False)
    for item in result:
        path=output_dir/item['name'];path.write_bytes(item['data'])
        path.with_suffix('.json').write_text(json.dumps(item['proof'],ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return [x['proof'] for x in result]


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source-glb','source-model-zip','source-report','source-extracted-zip','output-dir'):
        ap.add_argument('--'+name,required=True,type=Path)
    ap.add_argument('--research-only',action='store_true',help='ゲームShader互換でないUV0研究を明示承認する')
    opt=ap.parse_args()
    if not opt.research_only:ap.error('--research-only を明示してください。製品既定は変更しません。')
    try:print(json.dumps(build(opt.source_glb,opt.source_model_zip,opt.source_report,
                               opt.source_extracted_zip,opt.output_dir),ensure_ascii=False,indent=2))
    except (OSError,SourceTextError,zipfile.BadZipFile,KeyError,ValueError) as e:
        ap.exit(2,'原本MatI Sidewall研究A/B生成を拒否: '+str(e)+'\n')
