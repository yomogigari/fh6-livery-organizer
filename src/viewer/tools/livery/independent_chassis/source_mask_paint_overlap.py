"""真正BC4 11面Maskと保全r735ペイント矩形の実画素交差（研究専用）。

旧正常Viewerの原本BC4デコーダーを再利用し、原本Maskのsource region
と元paint regionを同一ローカル座標として読み取る。UV3形状/Facing・
FH6 ShaderBin・現在の本人C_livery一致は検証しない。製品描画経路を変更しない。
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image

from .source_native_mask_alpha import (
    NativeMaskEvidenceError, GLASS_MASK_TO_SECTION, MASK_BITS,
    _reader, _sha, audit_original_mask_pixels, audit_saved_paint_alpha,
)


def pixelwise_mask_alpha_overlap(mask: np.ndarray, alpha: np.ndarray,
                                 source_region: list, paint_region: list,
                                 *, reverse_paint_v: bool = False) -> dict:
    """1面の元Mask正画素を、元paint atlasへAffine-nearest対応で標本化。

    画素センターの軸順は上からの行。reverse_paint_vはGPU Y反転の未承認
    A/Bであり、どちらかを勝手にXbox基準に選択しない。
    """
    m=np.asarray(mask)
    a=np.asarray(alpha)
    if (m.ndim!=2 or a.ndim!=2 or m.dtype!=np.uint8 or a.dtype!=np.uint8
        or min(m.shape)<=0 or min(a.shape)<=0 or
        m.size>16*1024*1024 or a.size>48*1024*1024):
        raise NativeMaskEvidenceError('original mask/paint alpha pixels invalid')
    rects=[]
    for rect in (source_region,paint_region):
        if (not isinstance(rect,(list,tuple)) or len(rect)!=4 or
            any(type(v) not in (float,int) or not np.isfinite(v) or v<0 or v>1 for v in rect) or
            rect[0]>=rect[2] or rect[1]>=rect[3]):
            raise NativeMaskEvidenceError('original mask/paint source rectangle invalid')
        rects.append(rect)
    src,tile=rects
    yy,xx=np.nonzero(m>127)
    if not len(xx):
        return {'positive_native_mask_pixels':0,'mask_pixels_inside_source_region':0,
                'mask_alpha_intersection_pixels':0,'overlap_fraction':0.,
                'paint_v_flipped_for_trial':reverse_paint_v}
    mh,mw=m.shape;ah,aw=a.shape
    keep=((xx+.5>=src[0]*mw)&(xx+.5<src[2]*mw)&
          (yy+.5>=src[1]*mh)&(yy+.5<src[3]*mh))
    n=int(np.count_nonzero(keep))
    if n==0:return {'positive_native_mask_pixels':int(len(xx)),
                    'mask_pixels_inside_source_region':0,
                    'mask_alpha_intersection_pixels':0,'overlap_fraction':0.,
                    'paint_v_flipped_for_trial':reverse_paint_v}
    x=(xx[keep]+.5-mw*src[0])/(mw*(src[2]-src[0]))
    y=(yy[keep]+.5-mh*src[1])/(mh*(src[3]-src[1]))
    if reverse_paint_v:y=1.-y
    # Nearest texel selection of original PNG samples in the declared paint tile.
    px=np.clip(np.floor((tile[0]+x*(tile[2]-tile[0]))*aw).astype(np.intp),0,aw-1)
    py=np.clip(np.floor((tile[1]+y*(tile[3]-tile[1]))*ah).astype(np.intp),0,ah-1)
    overlap=int(np.count_nonzero(a[py,px]>0))
    return {'positive_native_mask_pixels':int(len(xx)),
            'mask_pixels_inside_source_region':n,
            'mask_alpha_intersection_pixels':overlap,
            'overlap_fraction':round(overlap/n,8),
            'paint_v_flipped_for_trial':reverse_paint_v}


def audit_original_glass_paint_pixel_overlap(original_archive:Path,
                                             saved_private_archive:Path,
                                             accepted_viewer_source:Path,
                                             *, car_id:int)->dict:
    """元SHAを毎回再照合し、ガラス4方向の2Dピクセル交差を実測。"""
    original=audit_original_mask_pixels(original_archive,accepted_viewer_source,car_id=car_id)
    old=audit_saved_paint_alpha(original,saved_private_archive,car_id=car_id)
    contract=_reader(accepted_viewer_source)
    with zipfile.ZipFile(saved_private_archive) as saved, zipfile.ZipFile(original_archive) as game:
        renders=[n for n in saved.namelist() if n.endswith('/r735-live-bundle/render.json')]
        if len(renders)!=1:raise NativeMaskEvidenceError('one signed r735 paint render manifest required')
        entry=renders[0];raw_json=saved.read(entry)
        if _sha(raw_json)!=old['historical_paint_render_json_sha256']:
            raise NativeMaskEvidenceError('r735 paint manifest differs from verified original')
        doc=json.loads(raw_json)
        atlas_name=entry.rsplit('/',1)[0]+'/section-paint.png'
        png=saved.read(atlas_name)
        if _sha(png)!=old['historical_paint_image_sha256']:
            raise NativeMaskEvidenceError('r735 PNG hash changed')
        with Image.open(BytesIO(png)) as im:
            im.load()
            if im.mode!='RGBA' or im.width*im.height>48*1024*1024:
                raise NativeMaskEvidenceError('signed paint atlas format unsupported')
            alpha=np.asarray(im.getchannel('A'),dtype=np.uint8)
        sections={s['name']:s for s in doc['sections']}
        if len(sections)!=len(doc['sections']):raise NativeMaskEvidenceError('duplicate old paint sections')
        available={n.replace('\\','/').casefold():n for n in game.namelist()}
        rows=[];both=0
        for mask_name,paint_name in GLASS_MASK_TO_SECTION.items():
            mask_row=next(s for s in original['sections'] if s['name']==mask_name)
            if not mask_row['declared_valid']:
                rows.append({'native_mask_section':mask_name,'reason':'native original section invalid',
                             'pixelwise_intersection_verified':False,'candidate':False})
                continue
            source_key='liverymasks/'+mask_name.casefold()+'.swatchbin'
            if source_key not in available:raise NativeMaskEvidenceError('signed source glass Mask missing')
            raw=game.read(available[source_key])
            if _sha(raw)!=mask_row['mask_swath_sha256']:
                raise NativeMaskEvidenceError('original native Mask SHA changed')
            tex=contract._parse_pc_texture_bundle(raw)
            if tex['encoding']!=contract.UNSIGNED_BC4 or tex['width']!=mask_row['mask_width'] or tex['height']!=mask_row['mask_height']:
                raise NativeMaskEvidenceError('native mask encoding or size changed')
            img=contract._decode_unsigned_bc4(raw[tex['payload_offset']:tex['payload_offset']+tex['payload_size']],tex['width'],tex['height'])
            if int(np.count_nonzero(img>127))!=mask_row['source_mask_positive_pixels']:
                raise NativeMaskEvidenceError('native pixel mask count mismatches signed audit')
            section=sections.get(paint_name)
            if section is None:raise NativeMaskEvidenceError('missing original paint section')
            top=pixelwise_mask_alpha_overlap(img,alpha,section.get('source'),section.get('paint'))
            bottom=pixelwise_mask_alpha_overlap(img,alpha,section.get('source'),section.get('paint'),reverse_paint_v=True)
            if top['mask_pixels_inside_source_region']!=mask_row['source_mask_positive_pixels']:
                raise NativeMaskEvidenceError('native positive mask pixels not covered by signed source region')
            candidate=top['mask_alpha_intersection_pixels']>0 or bottom['mask_alpha_intersection_pixels']>0
            if candidate:both|=MASK_BITS[mask_name]
            rows.append({'native_mask_section':mask_name,'paint_section':paint_name,
                'source_region':section['source'],'paint_region':section['paint'],
                'original_mask_sha256':mask_row['mask_swath_sha256'],
                'source_positive_mask_pixels':top['positive_native_mask_pixels'],
                'forward_v_mask_paint_intersection_pixels':top['mask_alpha_intersection_pixels'],
                'reverse_v_mask_paint_intersection_pixels':bottom['mask_alpha_intersection_pixels'],
                'source_2d_pixel_overlap_candidate':candidate,
                'pixelwise_intersection_verified':True,
                'native_mesh_uv3_facing_verified':False})
    return {'schema':'lo4fh6.firstparty.native-mask-paint-source-rect-overlap.v1',
        'car_id':car_id,'original_vehicle_zip_sha256':original['original_vehicle_zip_sha256'],
        'original_masks_xml_sha256':original['source_masks_xml_sha256'],
        'saved_private_paint_zip_sha256':old['historical_paint_archive_sha256'],
        'saved_private_paint_sha256':old['historical_paint_image_sha256'],
        'original_source_sections_2d_pixel_overlap_candidate_bits':both,
        'sections':rows,'source_2d_pixel_overlap_verified':True,
        'native_mesh_uv3_facing_covered_verified':False,
        'glass_shader_material_depth_xbox_verified':False,
        'owner_current_c_livery_byte_identical':False,
        'product_default_modified':False,'release_approved':False}
