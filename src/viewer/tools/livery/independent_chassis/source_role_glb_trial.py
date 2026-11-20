"""元Stock-GLBを変更せず、同一元ModelBin/MatI/Shaderを照合して研究用roleを複製する。

既に完成した独自GLBの元バイナリを保持。原本Maskの存在をガラスのLivery
許可と取り違えない。製品標準入口とは未接続、配布するのはソースのみ。
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import stat
import struct
import zipfile
from xml.etree import ElementTree as ET

from .original_shader_role_audit import (
    OriginalShaderReferenceIndex, research_role_from_verified_family,
    research_shader_livery_permission,
)
SECTIONS = {'Front':1,'Back':2,'Top':4,'Left':8,'Right':16,'Wing':32,
            'Glass_Front':64,'Glass_Back':128,'Glass_Top':256,
            'Glass_Left':512,'Glass_Right':1024}

def original_mask_presence(z: zipfile.ZipFile,entries:dict)->tuple[int,str]:
    """11面Masks.xmlの原本presenceのみ検証。pixel coverageは証明しない。"""
    info=entries.get('liverymasks/masks.xml')
    if info is None or not 0<info.file_size<=1_048_576:
        raise ValueError('original Masks.xml invalid')
    payload=z.read(info)
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('original XML entity refused')
    root=ET.fromstring(payload)
    if root.tag!='LiveryMasks' or root.attrib:raise ValueError('unknown original mask root')
    bits=0;seen=set()
    for node in root:
        if node.tag not in SECTIONS or node.tag in seen or list(node):
            raise ValueError('original mask section invalid or repeated')
        seen.add(node.tag)
        if node.attrib.get('valid') not in ('true','false'):
            raise ValueError('original mask validity invalid')
        if node.attrib['valid']=='true':
            ref=entries.get('liverymasks/'+node.tag.lower()+'.swatchbin')
            if ref is None or not 0<ref.file_size<=32*1024*1024 or ref.flag_bits&1:
                raise ValueError('required original source Mask unavailable')
            bits|=SECTIONS[node.tag]
    return bits,_sha(payload)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _doc(raw: bytes):
    if len(raw)<32 or raw[:4]!=b'glTF' or struct.unpack_from('<II',raw,4)!=(2,len(raw)):
        raise ValueError('GLB2: invalid header')
    size,kind=struct.unpack_from('<I4s',raw,12)
    if kind!=b'JSON' or size<100 or size>32*1024*1024 or size%4:
        raise ValueError('GLB2: JSON invalid')
    start=20+size
    if start+8>len(raw):raise ValueError('GLB2: no BIN chunk')
    binary_length,binary_tag=struct.unpack_from('<I4s',raw,start)
    if binary_tag!=b'BIN\x00' or start+8+binary_length!=len(raw):
        raise ValueError('GLB2: binary content invalid')
    doc=json.loads(raw[20:start])
    if doc.get('scenes',[{}])[0].get('extras',{}).get('lo4fh6_release_approval') is not False:
        raise ValueError('GLB2: unapproved input not explicitly research-only')
    if doc.get('asset',{}).get('version')!='2.0':raise ValueError('GLB2: asset mismatch')
    return doc,raw[start+8:]


def _pack(doc: dict, body: bytes) -> bytes:
    js=json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    js+=b' '*(-len(js)%4)
    result=(struct.pack('<4sII',b'glTF',2,28+len(js)+len(body))+
            struct.pack('<I4s',len(js),b'JSON')+js+struct.pack('<I4s',len(body),b'BIN\x00')+body)
    if len(result)>256*1024*1024:raise ValueError('GLB2 exceeds safe memory budget')
    return result


def _safe_archive(z: zipfile.ZipFile):
    out={}
    for info in z.infolist():
        if info.is_dir():continue
        name=info.filename.replace('\\','/')
        if (name.startswith('/') or ':' in name or '..' in name.split('/') or
            '.' in name.split('/') or info.flag_bits&1 or
            stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK or info.file_size>128*1024*1024):
            raise ValueError('original ZIP invalid or ambiguous')
        key=name.casefold()
        if key in out:raise ValueError('original ZIP duplicate entries')
        out[key]=info
    return out


def build_original_shader_glb_trial(glb:bytes,original_archive:Path,reference:bytes,*,glass_paint_evidence:dict|None=None,historical_private_paint_archive:Path|None=None,accepted_viewer_source:Path|None=None,glass_source_2d_overlap_evidence:dict|None=None)->tuple[bytes,dict]:
    doc,body=_doc(glb)
    index=OriginalShaderReferenceIndex(reference)
    counts=Counter();relations=Counter();source_hashes={}
    with zipfile.ZipFile(original_archive) as archive:
        entries=_safe_archive(archive)
        mask_bits,mask_sha=original_mask_presence(archive,entries)
        permitted_glass_sides=0
        if glass_paint_evidence is not None:
            proof=glass_paint_evidence
            if (not isinstance(proof,dict) or
                proof.get('schema')!='lo4fh6.firstparty.saved-source-glass-paint-alpha-gate.v1' or
                proof.get('car_id')!=index.car_id or
                proof.get('original_vehicle_zip_sha256')!=_sha(original_archive.read_bytes()) or
                proof.get('native_masks_xml_sha256')!=mask_sha or
                proof.get('release_approved') is not False or
                proof.get('cross_uv_pixel_mask_intersection_verified') is not False):
                raise ValueError('glass-paint proof is missing matching PRIVATE source identity')
            if historical_private_paint_archive is None or accepted_viewer_source is None:
                raise ValueError('glass-paint proof requires rechecking PRIVATE paint and accepted native decoder')
            # 外部提供JSONをそのまま信頼せず、元車両ZIPと旧PRIVATE実アトラスを
            # 第一者完了済みBC4デコーダーで毎回実測。対応byte-SHA/数値が完全一致すること。
            from .source_native_mask_alpha import audit_original_mask_pixels,audit_saved_paint_alpha
            actual=audit_saved_paint_alpha(
                audit_original_mask_pixels(original_archive,accepted_viewer_source,car_id=index.car_id),
                historical_private_paint_archive,car_id=index.car_id)
            if actual!=proof:
                raise ValueError('glass-paint proof differs from revalidated original BC4 and saved private atlas')
            permitted_glass_sides=proof.get('eligible_glass_sides_for_source_uv3_pixel_shader')
            if (type(permitted_glass_sides) is not int or permitted_glass_sides&~mask_bits or
                permitted_glass_sides&~0x7c0 or permitted_glass_sides==0):
                raise ValueError('glass-paint proof lacks original native permitted sections')
        if glass_source_2d_overlap_evidence is not None:
            if glass_paint_evidence is None or historical_private_paint_archive is None or accepted_viewer_source is None:
                raise ValueError('pixelwise source glass proof requires original Mask, atlas and native decoder')
            from .source_mask_paint_overlap import audit_original_glass_paint_pixel_overlap
            actual_overlap=audit_original_glass_paint_pixel_overlap(
                original_archive,historical_private_paint_archive,accepted_viewer_source,car_id=index.car_id)
            if (not isinstance(glass_source_2d_overlap_evidence,dict) or
                glass_source_2d_overlap_evidence.get('release_approved') is not False or
                glass_source_2d_overlap_evidence.get('source_2d_pixel_overlap_verified') is not True or
                actual_overlap!=glass_source_2d_overlap_evidence):
                raise ValueError('pixelwise glass proof does not match first-party original BC4 and paint bytes')
            positive=actual_overlap['original_source_sections_2d_pixel_overlap_candidate_bits']
            if type(positive) is not int or positive&~0x7c0 or positive&~permitted_glass_sides:
                raise ValueError('pixelwise source glass proof has unsupported Mask sections')
            permitted_glass_sides&=positive
        if not doc.get('meshes') or len(doc['meshes'])!=len(doc.get('nodes',[])):
            raise ValueError('GLB original mesh/node count mismatch')
        for mesh,node in zip(doc['meshes'],doc['nodes']):
            ex=mesh.get('extras')
            if not isinstance(ex,dict) or ex.get('lo4_instance_identity')!=node.get('extras',{}).get('lo4_instance_identity'):
                raise ValueError('original GLB mesh identity mismatch')
            path=ex.get('lo4_source_entry')
            if not isinstance(path,str) or path.casefold() not in entries:
                raise ValueError('original ModelBin missing')
            key=path.casefold()
            if key not in source_hashes: source_hashes[key]=archive.read(entries[key])
            binding=index.bind(key,source_hashes[key],ex.get('lo4_material_name'))
            attr=mesh['primitives'][0]['attributes']
            if not isinstance(attr,dict):raise ValueError('GLB attributes invalid')
            has_uv3='TEXCOORD_3' in attr
            previous=ex.get('lo4_role')
            role=research_role_from_verified_family(previous,binding,
                has_uv3=has_uv3,source_mask_sides=mask_bits)
            ex['lo4_role']=role
            ex['lo4_allowed_sides']=research_shader_livery_permission(role,binding,
                has_uv3=has_uv3,mask_available_sides=mask_bits,
                glass_source_mask_alpha_sides=permitted_glass_sides)
            ex['lo4_projection_sides']=0
            ex['lo4fh6_original_shader_source_evidence']=binding
            ex['lo4fh6_original_glass_livery_pixel_verified']=False
            if role=='glass':
                family=binding.get('source_shader_family') if binding else None
                ex['lo4fh6_glass_livery_source_gate']=(
                    'original_window_mask_savedpaint_candidate_research_only'
                    if family=='car_window' and ex['lo4_allowed_sides']
                    else 'generic_translucent_glass_window_livery_unverified'
                    if family=='car_glass'
                    else 'original_window_livery_permission_unverified')
                counts['generic_glass_livery_candidate_denied']+=family=='car_glass'
                counts['window_shader_livery_candidate']+=family=='car_window' and bool(ex['lo4_allowed_sides'])
            ex['lo4fh6_source_mask_and_saved_alpha_sections_present']=bool(glass_paint_evidence is not None and role=='glass' and ex['lo4_allowed_sides'])
            ex['lo4fh6_source_per_fragment_mask_and_alpha_sampling_required']=role=='glass'
            ex['lo4fh6_shader_role_trial_unapproved']=True
            node['extras']=ex
            counts['total']+=1
            counts['shader_resolved' if binding else 'shader_unresolved']+=1
            counts['classified_'+role]+=1
            counts['glass_livery_permission_deferred']+=role=='glass' and not ex['lo4_allowed_sides']
            counts['glass_livery_source_mask_alpha_candidate']+=role=='glass' and bool(ex['lo4_allowed_sides'])
            relations[previous+'__'+role]+=1
        doc['scenes'][0]['extras']['lo4fh6_source_shader_role_trial']='RESEARCH_ONLY_NOT_GAME_SHADER_OR_MASK_PIXELS'
        doc['scenes'][0]['extras']['lo4fh6_original_mask_xml_sha256']=mask_sha
        doc['scenes'][0]['extras']['lo4fh6_release_approval']=False
    result=_pack(doc,body)
    _,checkbody=_doc(result)
    if _sha(body)!=_sha(checkbody):raise ValueError('GLB original binary geometry modified')
    return result,{'schema':'lo4fh6.private.original-shader-glass-livery-guard.v1',
        'car_id':index.car_id,'original_stock_glb_sha256':_sha(glb),
        'trial_glb_sha256':_sha(result),'source_original_archive_sha256':_sha(original_archive.read_bytes()),
        'original_shader_reference_sha256':_sha(reference),'original_geometry_binary_sha256':_sha(body),
        'original_models_verified':len(source_hashes),'original_mask_xml_sha256':mask_sha,
        'counts':dict(sorted(counts.items())),'role_changes':dict(sorted(relations.items())),
        'mask_pixel_blending_gpu_verified':False,'glass_candidate_evidence_used':glass_paint_evidence is not None,
        'glass_candidate_render_requires_per_fragment_native_mask_and_paint_alpha':True,
        'glass_candidate_allowed_sides':permitted_glass_sides,
        'source_2d_mask_paint_pixel_overlap_verified':glass_source_2d_overlap_evidence is not None,
        'source_mesh_uv3_facing_pixel_overlap_verified':False,
        'release_approved':False,
        'product_default_modified':False,'original_wheel_tire_included':False}


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description='元Shader分類研究GLB（製品利用不可）')
    for k in ('glb','archive','reference','output','report'):
        p.add_argument('--'+k,required=True,type=Path)
    p.add_argument('--research-glass-livery-denied',action='store_true',
                   help='旧研究：証拠未提示時のみガラス図柄禁止で比較する')
    p.add_argument('--research-source-uv3-mask-alpha-candidate',action='store_true',
                   help='元BC4 11面+旧PRIVATE画素実測証拠を毎回再照合して条件付きガラス研究候補を作る')
    p.add_argument('--research-private-glass-paint-evidence',type=Path,
                   help='元マスクSHA一致/旧PRIVATE alpha実画素検証証拠（研究表示専用）')
    p.add_argument('--research-private-glass-overlap-evidence',type=Path,
                   help='元Mask source rectと旧PRIVATE paint tileの原本画素交差を再実測して許可候補を絞る')
    p.add_argument('--research-private-paint-archive',type=Path,
                   help='元保全r735ペイントZIP。指定時は毎回Maskとアトラスを再解析')
    p.add_argument('--accepted-viewer-source',type=Path,
                   help='元第一者render_contractの実BC4デコーダー所在')
    opt=p.parse_args(argv)
    try:
        if bool(opt.research_private_glass_paint_evidence):
            if not opt.research_source_uv3_mask_alpha_candidate or opt.research_glass_livery_denied:
                raise ValueError('conditional glass research requires the matching explicit source UV3/Mask/alpha flag')
        elif not opt.research_glass_livery_denied or opt.research_source_uv3_mask_alpha_candidate:
            raise ValueError('unapproved research GLB trial requires explicit glass-denied opt-in')
        if (opt.output.exists() or opt.report.exists() or opt.output==opt.report or
            opt.output.suffix.lower()!='.glb' or opt.report.suffix.lower()!='.json'):
            raise ValueError('new .glb/.json output paths required; overwrite prohibited')
        glass_source=json.loads(opt.research_private_glass_paint_evidence.read_bytes()) if opt.research_private_glass_paint_evidence else None
        source_overlap=json.loads(opt.research_private_glass_overlap_evidence.read_bytes()) if opt.research_private_glass_overlap_evidence else None
        trial,evidence=build_original_shader_glb_trial(opt.glb.read_bytes(),opt.archive,opt.reference.read_bytes(),
            glass_paint_evidence=glass_source,historical_private_paint_archive=opt.research_private_paint_archive,
            accepted_viewer_source=opt.accepted_viewer_source,glass_source_2d_overlap_evidence=source_overlap)
        opt.output.parent.mkdir(parents=True,exist_ok=True)
        opt.report.parent.mkdir(parents=True,exist_ok=True)
        with opt.output.open('xb') as f:f.write(trial)
        with opt.report.open('x',encoding='utf-8-sig') as f:json.dump(evidence,f,ensure_ascii=True,sort_keys=True,indent=2)
        print(json.dumps(evidence,ensure_ascii=True,sort_keys=True))
        return 0
    except (OSError,ValueError,zipfile.BadZipFile) as exc:
        import sys
        print(('Research original Shader role trial refused: '+str(exc)).encode('ascii','backslashreplace').decode('ascii'),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
