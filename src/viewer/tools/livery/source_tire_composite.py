# -*- coding: utf-8 -*-
"""Source-verified Tire compound *research*, never Xbox-verified FH6 shader.

Reads signed FH6 ModelBin MatI / car_tires_pg XML / installed Swatch.
Embeds original RGBA of UniqueMasks/blur/CH3AO/text into isolated Tire-GLB.
Three glTF PBR's AO R and roughness G are visualization hypotheses only.
No source ModelBin, Wheel, FEOW, GUI, GLB geometry, GameSave is changed.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import struct
import threading
import zipfile
from pathlib import Path
from collections import Counter, OrderedDict

from .material_runtime import _open_zip, zip_crc_failure, zip_infos_ending_with
from .png_settings import PNG_COMPRESS_LEVEL
from .swatch_png_store import remembered_swatch_png
from .json_tree_copy import json_tree_deepcopy  # GLB の中身まるごとの複製（deepcopy と同じ結果で約 3 倍速い）
from PIL import Image

from . import wheel_morph_internal as wm
from .fh6_swatch import read_swatch_surface, _dx10_dds
from .source_tire_glb_bridge import read_glb
from .source_tire_shader_binding import (
    TireUniqueNormMissingError, mati_bindings, _read_parameters, shader_xml_ids,
)
from .source_tire_texture_bridge import _texture_member

MESH_ROLE = ('sidewall', 'tread', 'scaling_text')
WHEELS = ('front_left', 'front_right', 'rear_left', 'rear_right')
EXTRA = 'UnqiueMasks_Tires_PGTexture'  # FH6 original misspelling
BLUR_EXTRA = 'UnqiueMasksBlur_Tires_PGTexture'
BLUR_NORMAL = 'UniqueNormBlur_Tires_PGTexture'
AO = 'CH3AOTextureTexture'
TEXT0 = 'TextTexture0_TyreSideWallTextTexture'
TEXT1 = 'TextTexture_TyreSideWallTextTexture'
TEXT_SWITCH = 'TextSwitch_TyreSideWallTextBool'
SOURCE = 'lo4fh6.source-tire-rgba-compound-gltf-pbr-research.v1'
MAX_SOURCE_SWATCH=32*1024*1024

class SourceTireCompositeError(ValueError):
    pass

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def original_shader_xml(shader_library: Path) -> tuple[bytes, str]:
    family = shader_library / 'shaders' / 'car_tires_pg.zip'
    outer = shader_library / 'shaders.zip'
    if family.is_file():
        z=zipfile.ZipFile(family)
    elif outer.is_file():
        with zipfile.ZipFile(outer) as source:
            z=zipfile.ZipFile(io.BytesIO(source.read('shaders/car_tires_pg.zip')))
    else:
        raise SourceTireCompositeError('原本car_tires_pg ShaderBinがありません')
    with z:
        xml=z.read('car_tires_pg.shaderbin.xml')
        sha=digest(z.read('car_tires_pg.shaderbin'))
    shader_xml_ids(xml)  # every declared ID must be unique
    return xml,sha

def source_matis(tire_zip: Path) -> dict[str,dict[int,tuple[str,bytes]]]:
    """FH6原本Tireの1/2/4 ModelBinを既存Normal経路と同じ名義で読む。

    これは原本MatIの出典確認であり、未承認の複合Shader自動採用とは分離。
    従来の左右L/R原本2つだけが既存署名済み複合材質の対象となる。
    """
    from .source_tire_local_runtime import (
        _original_tire_model_entries, LocalTireSourceError, tire_archive_model_name,
    )
    try:
        source_model = tire_archive_model_name(tire_zip)
    except LocalTireSourceError as exc:
        raise SourceTireCompositeError('Tire原本ZIP名にtire_接頭辞またはtireR_接頭辞がありません') from exc
    output = {}
    with zipfile.ZipFile(tire_zip) as z:
        if zip_crc_failure(tire_zip) is not None:  # 同じファイルなら同じプロセスで 1 回だけ全部を読む
            raise SourceTireCompositeError('元Tire ModelBin ZIP CRC failure')
        try:
            role_entries = _original_tire_model_entries(z, source_model)
        except LocalTireSourceError as exc:
            # 不明構造は単なる非適合として隠さず、原本とViewerの不一致を失敗とする。
            raise SourceTireCompositeError(
                'original Tire archive integrity failure: ' + str(exc)) from exc
        members = tuple(dict.fromkeys(item.filename for item in role_entries.values()))
        if len(members) not in (1, 2, 4):
            raise SourceTireCompositeError('signed Tire source model count is not 1/2/4')
        for name in members:
            raw = z.read(name)
            blobs = wm._parse_blobs(raw)
            material_blobs = [b for b in blobs
                              if b.tag == 0x4d617449 and b.identifier is not None]
            if (len(material_blobs) != len(MESH_ROLE)
                    or len({b.identifier for b in material_blobs}) != len(MESH_ROLE)):
                raise SourceTireCompositeError('Tire material names/IDs are not the signed 3-role shape')
            mats = {b.identifier: (b.name, bytes(b.data)) for b in material_blobs}
            if set(name for name, _ in mats.values()) != set(MESH_ROLE):
                raise SourceTireCompositeError('Tire material names/IDs are not the signed 3-role shape')
            h = digest(raw)
            if h in output:
                raise SourceTireCompositeError('duplicate source ModelBin sha')
            output[h] = mats
    return output


def material_tiling(materials_zip: Path, xml: bytes) -> dict[str, tuple[float,float]]:
    names={f'{h:08x}':name for h,(name,_type) in shader_xml_ids(xml).items()}
    output={}
    # Materials.zip の全項目の CRC の確かめは、同じファイルなら同じプロセスで 1 回だけ（約 0.15 秒。2026-11-21）
    if zip_crc_failure(materials_zip) is not None:raise SourceTireCompositeError('MaterialBin ZIP CRC failure')
    with _open_zip(materials_zip) as z:
        for role,member in (('sidewall','_fmnext/tires/tires_pg_sidewall.materialbin'),
                            ('tread','_fmnext/tires/tires_pg_tread.materialbin')):
            raw=z.read(member)
            if b'car_tires_pg.shaderbin' not in raw:
                raise SourceTireCompositeError('MaterialBin Shader family mismatch')
            rp=[bytes(b.data) for b in wm._parse_blobs(raw) if b.tag==0x4d545052]
            if len(rp)!=1:raise SourceTireCompositeError('MaterialBin MTPR not unique')
            matches=[r for r in _read_parameters(rp[0]) if names.get(r['parameter_crc32'])=='UniqueMapTilingVector2']
            if len(matches)!=1 or matches[0]['type']!=11:
                raise SourceTireCompositeError('MaterialBin native UniqueMapTiling missing')
            xy=matches[0]['value']
            if len(xy)!=2 or any(not math.isfinite(x) or not .001 <= x <= 100 for x in xy):
                raise SourceTireCompositeError('MaterialBin native UniqueMapTiling invalid')
            output[role]=(float(xy[0]),float(xy[1]))
    return output

def decode_swatch_rgba(raw:bytes) -> tuple[bytes,dict]:
    surface=read_swatch_surface(raw)
    pixels=surface.get('pixels')
    if (not pixels or surface.get('tiled_flag') or not surface.get('pixel_range_valid')
            or surface.get('encoding') not in (0,3,4,5,6,9,13)):
        raise SourceTireCompositeError('Original Swatch encoding/tile/extent unsupported')
    w,h=surface['width'],surface['height'];encoding=surface['encoding']
    if not (0<w<=8192 and 0<h<=8192):raise SourceTireCompositeError('swatch dimensions unsafe')
    fmt={0:80,3:80,4:81,5:83,6:84,9:98,13:28}[encoding]
    try:
        with Image.open(io.BytesIO(_dx10_dds(w,h,pixels,fmt))) as img:
            rgba=img.convert('RGBA')
            if rgba.size!=(w,h):raise SourceTireCompositeError('DDS swatch dimensions altered')
            data=io.BytesIO();rgba.save(data,format='PNG',compress_level=PNG_COMPRESS_LEVEL)
    except Exception as exc:
        raise SourceTireCompositeError('Original Swatch RGBA decode error: '+str(exc)) from exc
    return data.getvalue(),{'width':w,'height':h,'encoding':encoding,'rgba_preserved':True}

def raw_swatches(textures_zip:Path, refs:set[str]) -> dict[str,tuple[bytes,dict]]:
    if not textures_zip.is_file() or textures_zip.name.casefold()!='textures.zip':
        raise SourceTireCompositeError('installed original Textures.zip missing')
    result={}
    with _open_zip(textures_zip) as z:
        # Installed Textures.zip may contain tens of thousands of unrelated originals.
        # Reading selected members validates their ZIP CRC; do not decompress all game assets.
        # 名前の索引は ZIP ごとに 1 回だけ作る（以前は呼ぶたびに数万項目を見ていた。2026-11-21）
        for ref in sorted(refs):
            matches=zip_infos_ending_with(z, ref)
            if len(matches)!=1:raise SourceTireCompositeError('Original texture member ambiguous: '+ref)
            info=matches[0]
            if info.flag_bits&1 or not 0<info.file_size<=MAX_SOURCE_SWATCH:
                raise SourceTireCompositeError('Original Swatch size/encryption invalid')
            def compute(info=info):
                raw=z.read(info)
                png,meta=_decoded_swatch_rgba(raw)
                return png,dict(meta,sha256=digest(raw),bytes=len(raw))
            # 標準タイヤの GLB を作る範囲では、前に作った PNG を共有の置き場から使い回す（swatch_png_store。2026-11-21）
            result[ref]=remembered_swatch_png('tire-compound-rgba',info,compute)
    return result


# 同じ原本の Swatch（中身の SHA が同じ）を RGBA の PNG にした結果は、同じプロセスの中で使い回す
# （同じタイヤの車が続くと、毎回同じ画像を復号して PNG に書いていた。2026-11-21）。失敗は覚えない。
_DECODED_SWATCHES: 'OrderedDict[tuple, tuple[bytes, dict]]' = OrderedDict()
_DECODED_SWATCHES_LIMIT = 16
_DECODED_SWATCHES_LOCK = threading.Lock()


def _decoded_swatch_rgba(raw: bytes) -> tuple[bytes, dict]:
    key = (digest(raw), decode_swatch_rgba)  # 同じ中身を同じ復号で作った結果だけを使い回す
    with _DECODED_SWATCHES_LOCK:
        found = _DECODED_SWATCHES.get(key)
        if found is not None:
            _DECODED_SWATCHES.move_to_end(key)
    if found is None:
        found = decode_swatch_rgba(raw)
        with _DECODED_SWATCHES_LOCK:
            _DECODED_SWATCHES[key] = found
            while len(_DECODED_SWATCHES) > _DECODED_SWATCHES_LIMIT:
                _DECODED_SWATCHES.popitem(last=False)
    return found[0], dict(found[1])

def pack_glb(doc:dict,bin_data:bytearray)->bytes:
    bin_data.extend(b'\0'*(-len(bin_data)%4))
    doc['buffers'][0]['byteLength']=len(bin_data)
    j=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    j+=b' '*(-len(j)%4)
    return (struct.pack('<4sII',b'glTF',2,12+8+len(j)+8+len(bin_data))
            +struct.pack('<I4s',len(j),b'JSON')+j
            +struct.pack('<I4s',len(bin_data),b'BIN\0')+bin_data)

def source_tire_sidewall_text_research_contract(bindings: dict) -> dict:
    """原本側面MatIの文字入力を厳密に分類し、未取得テクスチャを生成しない。

    TextSwitch=0と原本Text0/1が揃う形式は既存研究比較。
    TextSwitch/Text0/1自体を持たずVariantConstant_Legacy=0の形式は
    新たに確認した原本構造。通常自動採用せず明示研究だけで使用する。
    VariantConstantをTextSwitchと同義に捏造しない。
    """
    sw = bindings.get(TEXT_SWITCH)
    if sw is not None:
        if sw.get('type') not in (3, 4) or sw.get('value') != 0:
            raise SourceTireCompositeError('既存FEOW TextSwitch=1等の側面文字を研究合成で上書きできません')
        if any(bindings.get(k, {}).get('type') != 6 for k in (TEXT0, TEXT1)):
            raise SourceTireCompositeError('元Tire TextSwitchのTexture2D原本署名が不足')
        return {'route':'explicit-switch-zero','text_switch':0,'draw_text':False}
    # 文字スロットが一部しかない場合は欠けた値をゼロと仮定しない。
    if TEXT0 in bindings or TEXT1 in bindings:
        raise SourceTireCompositeError('Tire側面TextSwitchなしの文字テクスチャが曖昧です')
    legacy = bindings.get('VariantConstant_Legacy')
    if legacy is None or legacy.get('type') != 4 or legacy.get('value') != 0:
        raise SourceTireCompositeError('Tire側面Legacy原本variant0の署名が不足')
    return {'route':'legacy-variant-zero-no-text-params-research-only',
            'text_switch':None,'draw_text':False}


def original_tire_compound_signed_eligible(tire_zip: Path, shader_library: Path) -> bool:
    """原本署名の複合Tireの判定（中身は _original_tire_compound_signed_eligible_uncached）。"""
    # 同じプロセスの中で、同じ原本（タイヤの ZIP と _library の材質・画像・シェーダーの大きさ・更新日時）なら
    # 前の判定を使う（tire_input_memo。ペイントに依らない判定で、窓の使い回し・撮影の係で毎回繰り返していた）。
    from .tire_input_memo import exists, file_identity, library_identity, remembered
    tire = file_identity(tire_zip)
    key = (tire, library_identity(shader_library))
    return remembered("original_tire_compound_signed_eligible", key,
                      lambda: _original_tire_compound_signed_eligible_uncached(tire_zip, shader_library),
                      enabled=exists(tire))

def _original_tire_compound_signed_eligible_uncached(tire_zip: Path, shader_library: Path) -> bool:
    """原本署名が揃った3役割のTire（左右各1）だけを複合材質の自動適用対象とする。

    TextSwitch=0：3役割すべてに複合を適用する。TextSwitch=1（FEOW等の側面文字）：
    トレッドと刻印（scaling_text）だけに適用し、文字の側面はNormalのみとして
    文字は実績のあるFEOW経路で描画する。

    対象外の材質構成はFalseを返し、FEOWやWheelを無効化しない。役割は判別できても
    パラメーターIDが欠けていれば対応扱いにしない。条件に合っても必要なTextureを
    後で読めない場合は、実際の複合生成の段階で明示的にエラーとする。
    """
    try:
        mats_by_sha = source_matis(tire_zip)
    except SourceTireCompositeError as exc:
        if 'not the signed 3-role shape' in str(exc):
            return False
        raise
    # 従来受入済みの複合材質は正確な左右1本ずつの原本だけに限定する。
    # 単一・前後ペア・四隅は原本Normalへ接続し、複合PBRを推測自動ONにしない。
    if len(mats_by_sha) != 2:
        return False
    xml, _shader_sha = original_shader_xml(shader_library)
    required = {'UniqueNorm_Tires_PGTexture', EXTRA, BLUR_EXTRA, BLUR_NORMAL}
    sidewall_verified = 0
    for mats in mats_by_sha.values():
        for _material_id, (role, raw) in mats.items():
            try:
                bindings = mati_bindings(raw, xml)['bindings']
            except TireUniqueNormMissingError:
                # 適用判定に必要な元Textureが未設定＝この複合材質署名の対象外。
                # 破損CRC/Shader参照異常を含む他のTireBindingErrorは隠さない。
                return False
            if not required.issubset(bindings):
                return False
            if any(bindings[k]['type'] != 6 for k in required):
                return False
            if role == 'sidewall':
                flag = bindings.get(TEXT_SWITCH)
                # TextSwitch=0 は従来どおり3役割すべてへ複合を適用する。
                # TextSwitch=1（FEOW等の側面文字あり）は、文字の側面MatIだけを
                # 複合の対象外（Normalのみ）とし、トレッドと刻印の2役割へ適用する。
                # 側面文字の描画は従来どおりFEOWの確定経路が担当する。
                if not flag or flag['type'] not in (3, 4) or flag['value'] not in (0, 1):
                    return False
                if TEXT0 not in bindings or TEXT1 not in bindings:
                    return False
                sidewall_verified += 1
    # 全必要MatIが揃った場合のみ、従来受入済みのL/R形式を原本名で確定。
    if sidewall_verified != 2:
        return False
    from .source_tire_local_runtime import _original_tire_model_entries, tire_archive_model_name
    with zipfile.ZipFile(tire_zip) as archive:
        chosen = _original_tire_model_entries(archive, tire_archive_model_name(tire_zip))
    left = {chosen[role].filename.casefold()
            for role in WHEELS if role.endswith('left')}
    right = {chosen[role].filename.casefold()
             for role in WHEELS if role.endswith('right')}
    base_name = tire_archive_model_name(tire_zip)
    # 1原本・前後2原本・四隅4原本へ未承認のBlur/Mask合成を自動採用しない。
    return (left == {f'tireL_{base_name}.modelbin'.casefold()}
            and right == {f'tireR_{base_name}.modelbin'.casefold()})


def source_tire_dual_namespace_identity(ex: dict) -> tuple:
    """参照製品/第一者Converterの元ModelBin署名を同じ4輪Tireとして照合する。

    中立GLBの生成元はlo4_*、新第一者Converterはlo4fh6_*を保持する。
    両方が存在する場合は必ず値が一致し、異なるwheel/materialは拒否する。
    """
    if not isinstance(ex, dict):
        raise SourceTireCompositeError('Original Tire mesh extras missing')
    # 非タイヤ(Body/Glass/Wheel)に二名前空間の旧converter固有値があっても、
    # Tire研究の範囲外なら既存の完成メッシュには干渉しない。
    tire_roles=(ex.get('lo4_part_type'),ex.get('lo4fh6_part_type'))
    if 'Tire' not in tire_roles:
        return (tire_roles[0] or tire_roles[1], None, None, None, None)
    keys=('part_type', 'tire_source_wheel', 'tire_original_material_name',
          'tire_original_material_id', 'tire_original_modelbin_sha256')
    result=[]
    for key in keys:
        candidates=[ex[prefix+key] for prefix in ('lo4_', 'lo4fh6_')
                    if prefix+key in ex and ex[prefix+key] is not None]
        if len(candidates)==2 and candidates[0]!=candidates[1]:
            raise SourceTireCompositeError('Original Tire metadata namespaces conflict: '+key)
        result.append(candidates[0] if candidates else None)
    return tuple(result)


def build_original_tire_compound_research(source_glb: bytes, model_zip: Path,
                                          materials_zip: Path, shader_library: Path,
                                          textures_zip: Path) -> tuple[bytes,dict]:
    """Adds 4-wheel-source signed native RGBA textures to already validated Normal GLB.

    Extra R as AO / G as roughness is *hypothesis* for visual comparison, not FH6 Shader.
    Text texture is kept in metadata only when TextSwitch=0; don't draw it.
    """
    before,src_bin=read_glb(source_glb);doc=json_tree_deepcopy(before);binary=bytearray(src_bin)
    xml,shader_sha=original_shader_xml(shader_library)
    matis=source_matis(model_zip);tiling=material_tiling(materials_zip,xml)
    if not doc.get('meshes') or not doc.get('materials'):raise SourceTireCompositeError('GLB no mesh/material')
    originals=[];refs=set();roles=Counter()
    for mesh in doc['meshes']:
        ex=mesh.get('extras',{})
        part_type,wh,role,id_,sha=source_tire_dual_namespace_identity(ex)
        if part_type!='Tire':continue
        if wh not in WHEELS or role not in MESH_ROLE or sha not in matis:
            raise SourceTireCompositeError('source Tire wheel/role/ModelBin SHA mismatch')
        name,raw=matis[sha][id_]
        if name!=role:raise SourceTireCompositeError('source MatI role mismatch')
        mt=mati_bindings(raw,xml)['bindings']
        if EXTRA not in mt or BLUR_EXTRA not in mt or BLUR_NORMAL not in mt:
            raise SourceTireCompositeError('Native Tire masked/blur texture family incomplete')
        prim=mesh['primitives'][0];material=doc['materials'][prim['material']]
        proof=material.get('extras',{})
        if proof.get('lo4fh6_original_tire_normal_research') is not True or proof.get('source_shaderbin_sha256')!=shader_sha:
            raise SourceTireCompositeError('Original Tire Normal source material not signed')
        if proof.get('source_modelbin_sha256')!=sha or proof.get('source_original_mati_id')!=id_:
            raise SourceTireCompositeError('Original tire material SHA or ID mismatch')
        if not material.get('normalTexture') or 'KHR_texture_transform' not in material['normalTexture'].get('extensions',{}):
            raise SourceTireCompositeError('Signed original Normal UV0 affine missing')
        if any(x not in prim.get('attributes',{}) for x in ('TEXCOORD_0','TEXCOORD_1','TEXCOORD_2','TEXCOORD_3')):
            raise SourceTireCompositeError('Native four tire UV attributes missing')
        normal_sha=proof['source_swatch_sha256']
        if not isinstance(normal_sha,str) or len(normal_sha)!=64 or any(c not in '0123456789abcdef' for c in normal_sha):
            raise SourceTireCompositeError('source normal sha invalid')
        for k,row in mt.items():
            if row['type']==6:refs.add(_texture_member(row['value']))
        originals.append((wh,role,material,mt,proof,prim))
        roles[(wh,role)]+=1
    if len(originals)!=12 or set(roles)!={(w,r) for w in WHEELS for r in MESH_ROLE} or any(v!=1 for v in roles.values()):
        raise SourceTireCompositeError('Expected 4 wheels by 3 original Tire roles')
    images=raw_swatches(textures_zip,refs)
    doc.setdefault('images',[]);doc.setdefault('textures',[]);doc.setdefault('bufferViews',[])
    doc.setdefault('extensionsUsed',[])
    if 'KHR_texture_transform' not in doc['extensionsUsed']:doc['extensionsUsed'].append('KHR_texture_transform')
    refs_to_tex={}
    for ref,(image,meta) in sorted(images.items()):
        binary.extend(b'\0'*(-len(binary)%4));off=len(binary);binary.extend(image)
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':len(image)})
        im=len(doc['images']);doc['images'].append({'bufferView':view,'mimeType':'image/png','extras':{'original_swatch_sha256':meta['sha256'],'original_texture_reference':ref,'original_rgba':True}})
        tex=len(doc['textures']);doc['textures'].append({'source':im});refs_to_tex[ref]=tex
    counts=Counter();text_switch={}
    for wh,role,mat,mt,proof,prim in originals:
        # UniqueMapTilingはNormalの段階（原本MatI→親MaterialBinの順）で適用済み。
        # ここでは再適用せず、Normalと同じUV変換をExtra/Blurにも使う（二重適用の防止）。
        applied=proof.get('source_unique_map_tiling')
        origin=proof.get('source_unique_map_tiling_origin')
        if not isinstance(applied,list) or len(applied)!=2 or not isinstance(origin,str):
            raise SourceTireCompositeError('Normal段階のUniqueMapTiling記録がありません')
        if role in tiling and origin!='modelbin_mati' and tuple(applied)!=tuple(tiling[role]):
            raise SourceTireCompositeError('Normal段階と親MaterialBinのUniqueMapTilingが不一致')
        tx=copy.deepcopy(mat['normalTexture'].get('extensions',{}))
        proof['research_materialbin_unique_tiling']=(
            list(applied) if not origin.startswith('pending-') else 'unresolved-scaling-text')
        def tex(k):
            v=mt.get(k)
            if v is None:return None
            if v['type']!=6:raise SourceTireCompositeError(k+' must be Texture2D')
            ref=_texture_member(v['value'])
            return {'index':refs_to_tex[ref],'texCoord':0,'extensions':copy.deepcopy(tx)}
        if role=='sidewall' and (mt.get(TEXT_SWITCH) or {}).get('value')==1:
            # 側面文字あり（TextSwitch=1）の側面MatIはNormalのみのまま残す。
            # 2026-11-17 Jaguar4354（FEOW）の同一条件GPU比較で、この材質へ
            # UnqiueMasks由来のAOを掛けると、Windows受入済みのFEOW側面文字が
            # 暗く読めなくなった。文字の描画はFEOWの確定経路に任せる。
            if any(mt.get(k,{}).get('type')!=6 for k in (TEXT0,TEXT1)):
                raise SourceTireCompositeError('元Tire TextSwitchのTexture2D原本署名が不足')
            proof['original_text_switch']=1
            proof['source_text_sidewall_compound_skipped']=True
            text_switch[wh]=1
            counts['sidewall_text_normal_only']+=1
            continue
        candidate=tex(EXTRA)
        # Native Shader's parameter name is UniqueMasks, NOT AO/Roughness.
        # These two PBR slots are explicitly visualization candidates and never product-default.
        mat['occlusionTexture']={**copy.deepcopy(candidate),'strength':1.0}
        mat.setdefault('pbrMetallicRoughness',{})['metallicRoughnessTexture']=copy.deepcopy(candidate)
        mat['pbrMetallicRoughness']['metallicFactor']=0
        proof['lo4fh6_tire_source_rgba_compound_research']=True
        proof['source_extra_swatch_sha256']=images[_texture_member(mt[EXTRA]['value'])][1]['sha256']
        proof['source_blur_extra_swatch_sha256']=images[_texture_member(mt[BLUR_EXTRA]['value'])][1]['sha256']
        proof['source_blur_normal_swatch_sha256']=images[_texture_member(mt[BLUR_NORMAL]['value'])][1]['sha256']
        proof['shader_parameter_roles']={'occlusionTexture':EXTRA+' R hypothesis',
                                         'metallicRoughnessTexture':EXTRA+' G roughness hypothesis',
                                         'normalTexture':'UniqueNorm_Tires_PGTexture original',
                                         'embedded_blur_texture':'original RGBA retained/not GPU composed'}
        if AO in mt:proof['source_ao_swatch_sha256']=images[_texture_member(mt[AO]['value'])][1]['sha256']
        if role=='sidewall':
            sidewall_text=source_tire_sidewall_text_research_contract(mt)
            # 元ModelBinにTextSwitchがない形式を0だと捏造せずNoneで保全。
            proof['original_text_switch']=sidewall_text['text_switch']
            proof['original_text_routed']=False
            proof['original_text_contract']=sidewall_text['route']
            if 'baseColorTexture' in mat.get('pbrMetallicRoughness',{}):
                raise SourceTireCompositeError('sidewall must not override existing color map')
            text_switch[wh]=sidewall_text['text_switch']
            # Text0/Text1原本は既存switch=0型のみ存在。描画せず参照のみ保持。
            proof['original_text_texture_refs']={k:_texture_member(mt[k]['value']) for k in (TEXT0,TEXT1) if k in mt}
        proof['rgba_blur_channel_shader_equivalent']=False
        proof['extra_channel_mapping_shader_equivalent']=False
        proof['xbox_approved']=False
        proof['product_default_changed']=False
        counts[role]+=1
    after_bin_prefix=bytes(binary[:len(src_bin)])
    if after_bin_prefix!=bytes(src_bin):raise SourceTireCompositeError('Original binary prefix changed')
    output=pack_glb(doc,binary)
    decoded,check_bin=read_glb(output)
    if not all(decoded.get(k)==before.get(k) for k in ('meshes','nodes','accessors')):
        raise SourceTireCompositeError('Original mesh/node/accessor changed')
    if bytes(check_bin[:len(src_bin)])!=bytes(src_bin):raise SourceTireCompositeError('Original GLB binary changed')
    if any(decoded['materials'][i]!=before['materials'][i] for i in range(len(before['materials'])) if not before['materials'][i].get('extras',{}).get('lo4fh6_original_tire_normal_research')):
        raise SourceTireCompositeError('Non-Tire material changed')
    evidence={'schema':SOURCE,'original_normal_glb_sha256':digest(source_glb),'result_sha256':digest(output),
        'original_glb_binary_prefix_sha256':digest(src_bin),'model_zip_sha256':digest(model_zip.read_bytes()),
        'materials_zip_sha256':digest(materials_zip.read_bytes()),'source_shader_sha256':shader_sha,
        'source_rgba_images':{k:dict(meta) for k,(_png,meta) in images.items()},
        'native_rgba_image_count':len(images),'four_wheel_roles':dict(counts),
        'original_text_switches':text_switch,
        'legacy_variant_zero_sidewall_research_only':any(
            item[3].get('VariantConstant_Legacy',{}).get('value')==0
            and TEXT_SWITCH not in item[3]
            for item in originals if item[1]=='sidewall'),
        'matbin_tiling':tiling,
        'mesh_geometry_unchanged':True,'normal_original_unchanged_except_native_tiling_hypothesis':True,
        'game_shader_equivalent':False,'extra_channel_mapping_xbox_approved':False,
        'color_reflectance_xbox_approved':False,'windows_product_accepted':False,'research_only':True}
    return output,evidence