"""FH6原本BC4 Maskと保全ペイントの画素証拠を、既存第一者デコーダーで照合。

本モジュールはゲーム原本バイト/第三者コードを複製しない。公開用GLBの
描画可否を設定せず、原本SHAと同一性が証明された旧PRIVATE証拠だけを
研究用glass候補へ供給する。Maskとpaintが重なるかはGPUで判定する。
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

MASK_BITS={'Front':1,'Back':2,'Top':4,'Left':8,'Right':16,'Wing':32,
           'Glass_Front':64,'Glass_Back':128,'Glass_Top':256,
           'Glass_Left':512,'Glass_Right':1024}
GLASS_MASK_TO_SECTION={'Glass_Front':'FrontWindshield','Glass_Back':'BackWindshield',
                       'Glass_Top':'TopWindow','Glass_Left':'LeftWindow','Glass_Right':'RightWindow'}

class NativeMaskEvidenceError(ValueError):pass


def _sha(data:bytes)->str:return sha256(data).hexdigest()


def _reader(viewer_source:Path):
    """契約を明示された受入済みViewerのdecoderへ接続。再実装はしない。"""
    path=viewer_source.resolve()
    if not (path/'tools/livery/render_contract.py').is_file():
        raise NativeMaskEvidenceError('accepted first-party render_contract.py unavailable')
    if str(path) not in sys.path:sys.path.insert(0,str(path))
    from tools.livery import render_contract as contract
    return contract


def _original_masks(z:zipfile.ZipFile,contract):
    entries={}
    for info in z.infolist():
        n=info.filename.replace('\\','/').casefold()
        if n in entries:raise NativeMaskEvidenceError('ambiguous original ZIP entry')
        if info.is_dir():continue
        if '..' in n.split('/') or n.startswith('/') or info.flag_bits&1:
            raise NativeMaskEvidenceError('unsafe original archive path')
        entries[n]=info
    xml=entries.get('liverymasks/masks.xml')
    if xml is None or xml.file_size<40 or xml.file_size>1048576:
        raise NativeMaskEvidenceError('original Masks.xml absent')
    raw=z.read(xml)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise NativeMaskEvidenceError('original mask XML external entities forbidden')
    try:root=ET.fromstring(raw)
    except ET.ParseError as exc:raise NativeMaskEvidenceError('original mask XML parsing failed') from exc
    if root.tag!='LiveryMasks':raise NativeMaskEvidenceError('original mask XML unexpected root')
    rows={};bits=0
    for element in root:
        name=element.tag
        if name not in MASK_BITS or name in rows or list(element):
            raise NativeMaskEvidenceError('duplicate or invalid native mask section')
        flag=element.get('valid')
        if flag not in ('true','false'):raise NativeMaskEvidenceError('native mask flag invalid')
        info=entries.get('liverymasks/'+name.casefold()+'.swatchbin')
        if flag=='true' and (info is None or info.file_size>32*1024*1024):
            raise NativeMaskEvidenceError('declared valid Mask source missing')
        row={'name':name,'bit':MASK_BITS[name],'declared_valid':flag=='true',
             'mask_swath_sha256':None,'mask_width':None,'mask_height':None,
             'source_mask_positive_pixels':0,'source_mask_threshold':127,
             'source_mask_positive_fraction':0.0}
        if flag=='true':
            raw_bin=z.read(info)
            texture=contract._parse_pc_texture_bundle(raw_bin)
            if texture['encoding']!=contract.UNSIGNED_BC4:
                raise NativeMaskEvidenceError('native source Mask is not unsigned BC4')
            width,height=texture['width'],texture['height']
            if width not in (1024,2048) or height!=1024:
                raise NativeMaskEvidenceError('native Mask size unsupported by accepted viewer')
            s=texture['payload_offset'];size=texture['payload_size']
            arr=contract._decode_unsigned_bc4(raw_bin[s:s+size],width,height)
            mask_count=int(np.count_nonzero(arr>127))
            row.update(mask_swath_sha256=_sha(raw_bin),mask_width=width,mask_height=height,
                       source_mask_positive_pixels=mask_count,
                       source_mask_positive_fraction=round(mask_count/arr.size,8))
            if mask_count:bits|=MASK_BITS[name]
        rows[name]=row
    if len(rows)!=11:raise NativeMaskEvidenceError('original Masks.xml must declare all 11 sections')
    return rows,bits,_sha(raw)


def audit_original_mask_pixels(original_archive:Path,viewer_source:Path,*,car_id:int)->dict:
    """原本11面Swatchbinの実ピクセルを確認（source SHA証拠付き）。"""
    if type(car_id) is not int or car_id<=0:raise NativeMaskEvidenceError('car_id required')
    c=_reader(viewer_source)
    with zipfile.ZipFile(original_archive) as z:
        rows,bits,xml_sha=_original_masks(z,c)
    return {'schema':'lo4fh6.firstparty.original-native-mask-pixels.v1',
        'car_id':car_id,'original_vehicle_zip_sha256':_sha(original_archive.read_bytes()),
        'source_masks_xml_sha256':xml_sha,'eligible_positive_mask_bits':bits,
        'sections':[rows[n] for n in MASK_BITS],
        'mask_pixel_decoder_source_sha256':_sha((viewer_source/'tools/livery/render_contract.py').read_bytes()),
        'pixel_coverage_is_glass_livery_permission':False,'glass_blend_gpu_approved':False,
        'product_default_modified':False,'xbox_parity_verified':False}


def audit_saved_paint_alpha(original:dict,source_archive:Path,*,car_id:int,
                            run:str='r735-live-bundle')->dict:
    """旧PRIVATE保存paintとsource Maskとの出典SHAの一致のみを確認。

    旧r735 atlasは現在の本人GameSaveとの原本C_livery一致が未確認。
    ペイント正規座標のUV/facing/pixel交差はここでは推定しない。
    """
    if original.get('schema')!='lo4fh6.firstparty.original-native-mask-pixels.v1' or original.get('car_id')!=car_id:
        raise NativeMaskEvidenceError('native 11-section pixel audit identity invalid')
    with zipfile.ZipFile(source_archive) as z:
        names={n.casefold():n for n in z.namelist()}
        prefix=next((n.rsplit('/',1)[0] for n in z.namelist() if n.endswith('/'+run+'/render.json')),None)
        if prefix is None:raise NativeMaskEvidenceError('saved PRIVATE paint bundle is absent')
        rendered=z.read(prefix+'/render.json')
        record=json.loads(rendered)
        if record.get('schema')!='lo4fh6.r735.private.source_windows_v1':
            raise NativeMaskEvidenceError('saved paint renderer schema is not proven r735')
        png=z.read(prefix+'/section-paint.png')
        if _sha(png)!=record.get('imageSha256',{}).get('section-paint.png'):
            raise NativeMaskEvidenceError('saved paint image SHA mismatch')
        proofpath=next((n for n in z.namelist() if n.endswith(f'/car-{car_id}/original-masks.proof.json')),None)
        if proofpath is None:raise NativeMaskEvidenceError('no car-specific original Mask SHA evidence')
        source_proof=json.loads(z.read(proofpath))
        if source_proof.get('car_id')!=car_id or source_proof.get('source_masks_xml_sha256')!=original['source_masks_xml_sha256']:
            raise NativeMaskEvidenceError('saved paint mask proof does not belong to original vehicle')
        for section in original['sections']:
            if not section['declared_valid']:continue
            if source_proof['source_mask_sha256'].get(section['name'])!=section['mask_swath_sha256']:
                raise NativeMaskEvidenceError('saved painted source Mask SHA differs from original vehicle')
        with Image.open(BytesIO(png)) as opened:
            opened.load()
            if opened.mode!='RGBA' or opened.size!=tuple(record.get('paintDimensions',[])) or opened.width*opened.height>48*1024*1024:
                raise NativeMaskEvidenceError('saved original paint RGBA dimensions invalid')
            rgba=opened
            sections={x['name']:x for x in record.get('sections',[]) if isinstance(x,dict) and isinstance(x.get('name'),str)}
            if len(sections)!=len(record.get('sections',[])):
                raise NativeMaskEvidenceError('saved paint duplicate or invalid sections')
            hits={};rows=[]
            for mask_name,section_name in GLASS_MASK_TO_SECTION.items():
                source_mask=next(x for x in original['sections'] if x['name']==mask_name)
                item=sections.get(section_name)
                if item is None:
                    if source_mask['declared_valid']:
                        raise NativeMaskEvidenceError('saved paint missing a native glass section')
                    continue
                rect=item.get('paint')
                if not isinstance(rect,list) or len(rect)!=4 or any(type(x) not in (float,int) or not 0<=x<=1 for x in rect):
                    raise NativeMaskEvidenceError('saved paint section rectangle invalid')
                l,t,r,b=[round(rect[j]*(rgba.width if j%2==0 else rgba.height)) for j in range(4)]
                if not (0<=l<r<=rgba.width and 0<=t<b<=rgba.height):
                    raise NativeMaskEvidenceError('saved paint section rectangle empty or invalid')
                alpha=np.asarray(rgba.crop((l,t,r,b)).getchannel('A'),dtype=np.uint8)
                nonzero=int(np.count_nonzero(alpha>0))
                mask_pixels=source_mask['source_mask_positive_pixels']
                active=bool(source_mask['declared_valid'] and mask_pixels>0 and nonzero>0)
                rows.append({'native_mask_section':mask_name,'paint_section':section_name,
                    'native_mask_positive_pixels':mask_pixels,'saved_paint_alpha_positive_pixels':nonzero,
                    'saved_paint_alpha_positive_fraction':round(nonzero/alpha.size,8),
                    'mask_pixel_and_paint_alpha_both_nonzero':active,
                    'mask_and_paint_pixelwise_intersection_verified':False})
                hits[mask_name]=active
    eligible=sum(MASK_BITS[s] for s,active in hits.items() if active)
    return {'schema':'lo4fh6.firstparty.saved-source-glass-paint-alpha-gate.v1',
        'car_id':car_id,'original_vehicle_zip_sha256':original['original_vehicle_zip_sha256'],
        'native_masks_xml_sha256':original['source_masks_xml_sha256'],
        'mask_source_sha_by_section':{x['name']:x['mask_swath_sha256'] for x in original['sections'] if x['declared_valid']},
        'historical_paint_archive_sha256':_sha(source_archive.read_bytes()),
        'historical_paint_render_json_sha256':_sha(rendered),
        'historical_paint_image_sha256':_sha(png),
        'eligible_glass_sides_for_source_uv3_pixel_shader':eligible,
        'sections':rows,'cross_uv_pixel_mask_intersection_verified':False,
        'render_method':'candidate_sides_only__real_mask_and_paint_alpha_must_be_sampled_per_fragment',
        'owner_current_livery_byte_identical':False,'game_glass_shader_verified':False,
        'release_approved':False,'product_default_modified':False}
