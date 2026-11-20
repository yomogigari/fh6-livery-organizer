"""第一者全Stock GLBと旧PRIVATE原本MaterialBin索引のSHA結合。

元ModelBin SHA/MatI名/元MaterialBin SHA/Shader族を検査し、車種共通の
材質候補を報告する。コードと出力にPRIVATE原本の実バイトは含めない。
ShaderBinのGPU実動作、元11面BC4、リバリー許可は本モジュールでは判定しない。
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import sys
import zipfile
from .legacy_role_crosswalk import _checked_glb,RoleCrosswalkError

MAX_SOURCE_ZIP_FILES=25000
MAX_SOURCE_MODELBIN=128*1024*1024
MAX_REFERENCE_BYTES=8*1024*1024

class ShaderRoleAuditError(ValueError):pass


def _sha(v):return isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) is not None

def shader_category(family):
    """原本ShaderBin族のみを分類。表面がペイント可能かは別ゲート。"""
    if family in ('car_livery','car_livery_transmissive'):
        return 'original_livery_shader_candidate'
    if family in ('car_window','car_glass'):
        return 'original_glass_shader_candidate'
    if family=='car_automotive_paint':
        return 'original_automotive_basepaint_shader_candidate'
    return 'original_other_shader_candidate'


def audit_shader_role_sources(original_zip:Path|str,stock_glb:bytes,reference_crosswalk:bytes)->dict:
    if len(reference_crosswalk)>MAX_REFERENCE_BYTES:raise ShaderRoleAuditError('oversized source Shader crosswalk')
    try:reference=json.loads(reference_crosswalk)
    except (ValueError,UnicodeError) as exc:raise ShaderRoleAuditError('source shader crosswalk invalid') from exc
    if not isinstance(reference,dict) or reference.get('schema')!='lo4fh6.independent.private.cross-vehicle-mati-shader-reference.v1':
        raise ShaderRoleAuditError('incorrect source Shader crosswalk schema')
    if not isinstance(reference.get('car_id'),int) or not isinstance(reference.get('models'),list):
        raise ShaderRoleAuditError('crosswalk source identity missing')
    models={}
    for r in reference['models']:
        if not isinstance(r,dict):raise ShaderRoleAuditError('crosswalk model record invalid')
        path=r.get('model')
        if not isinstance(path,str) or not path.lower().endswith('.modelbin') or not _sha(r.get('source_sha256')):
            raise ShaderRoleAuditError('crosswalk source path/SHA absent')
        key=path.casefold()
        if key in models:raise ShaderRoleAuditError('duplicate source model in Shader crosswalk')
        mats=r.get('material_instances')
        if not isinstance(mats,list):raise ShaderRoleAuditError('missing material instance index')
        matches={}
        for mat in mats:
            if not isinstance(mat,dict):raise ShaderRoleAuditError('source material record invalid')
            name=mat.get('source_name');family=mat.get('shader_family');material_sha=mat.get('materialbin_sha256')
            if not isinstance(name,str) or not name or not isinstance(family,str) or not family or not _sha(material_sha):
                raise ShaderRoleAuditError('source material/Shader identity incomplete')
            matches.setdefault(name.casefold(),set()).add((family,material_sha))
        models[key]=(r['source_sha256'],matches)
    stock=_checked_glb(stock_glb)
    scene=stock[0].get('scenes',[{}])[0].get('extras',{})
    if scene.get('lo4fh6_release_approval') is not False or not str(scene.get('lo4fh6_research_only','')).startswith('SOURCE_GEOMETRY_COVERAGE'):
        raise ShaderRoleAuditError('input is not an explicit research-only Stock GLB')
    counts=Counter();family_counts=Counter();role_cross=Counter()
    with zipfile.ZipFile(original_zip) as z:
        available={}
        for info in z.infolist():
            if info.is_dir():continue
            n=info.filename.replace('\\','/')
            if (n.startswith('/') or '..' in n.split('/') or ':' in n or info.flag_bits&1 or
                stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK or info.file_size>MAX_SOURCE_MODELBIN):
                raise ShaderRoleAuditError('unsafe original vehicle source archive')
            key=n.casefold()
            if key in available:raise ShaderRoleAuditError('ambiguous case-insensitive source archive')
            available[key]=info
        if len(available)>MAX_SOURCE_ZIP_FILES:raise ShaderRoleAuditError('source ZIP file count exceeds safety budget')
        checksum_cache={}
        for m in stock[0]['meshes']:
            if not isinstance(m,dict) or not isinstance(m.get('extras'),dict):raise ShaderRoleAuditError('stock Mesh extras absent')
            e=m['extras'];path=e.get('lo4_source_entry');material=e.get('lo4_material_name')
            if not isinstance(path,str) or not isinstance(material,str):raise ShaderRoleAuditError('stock Mesh source MatI origin absent')
            k=path.casefold()
            if k not in models or k not in available:
                raise ShaderRoleAuditError('source ModelBin cannot be bound to reference crosswalk')
            expected,materials=models[k]
            if k not in checksum_cache:
                checksum_cache[k]=sha256(z.read(available[k])).hexdigest()
            if checksum_cache[k]!=expected:
                raise ShaderRoleAuditError('original ModelBin SHA mismatches Shader crosswalk')
            counts['source_model_sha_verified_meshes']+=1
            matches=materials.get(material.casefold())
            if not matches:
                counts['material_name_unresolved_meshes']+=1
                continue
            if len(matches)!=1:
                raise ShaderRoleAuditError('same MatI name maps to conflicting Shader/MaterialBin sources')
            family,materialbin_sha=next(iter(matches))
            family_counts[family]+=1
            category=shader_category(family)
            role_cross[(category,e.get('lo4_role','unknown'))]+=1
            counts['materialbin_shader_reference_resolved_meshes']+=1
    if counts['source_model_sha_verified_meshes']!=len(stock[0]['meshes']):
        raise ShaderRoleAuditError('not every visible Stock mesh source ModelBin verified')
    return {'schema':'lo4fh6.firstparty-original-shader-role-audit.v1',
        'source_car_id_from_reference':reference['car_id'],
        'source_zip_model_sha_count':len(checksum_cache),
        'input_stock_glb_sha256':stock[2],
        'source_crosswalk_sha256':sha256(reference_crosswalk).hexdigest(),
        'stock_visible_meshes':len(stock[0]['meshes']),
        'counts':dict(sorted(counts.items())),
        'shader_families':dict(sorted(family_counts.items())),
        'candidate_groups':{f'{k[0]}__current_{k[1]}':v for k,v in sorted(role_cross.items())},
        'native_shader_binary_and_11side_mask_pixel_verified':False,
        'mismatched_mati_names_fallback_without_notification':False,
        'product_roles_modified':False,
        'release_approved':False}


def main(argv=None):
    p=argparse.ArgumentParser(description='研究専用: FH6原本ModelBin SHA→MaterialBin Shader族照合')
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--stock-glb',type=Path,required=True)
    p.add_argument('--reference-shader-crosswalk',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--research-only',action='store_true')
    a=p.parse_args(argv)
    try:
        if not a.research_only:raise ShaderRoleAuditError('explicit PRIVATE research-only flag required')
        path=a.report.resolve()
        if a.report.is_symlink() or path.exists() or path.suffix.lower()!='.json':
            raise ShaderRoleAuditError('new JSON output required; overwrite prohibited')
        proof=audit_shader_role_sources(a.archive,a.stock_glb.read_bytes(),a.reference_shader_crosswalk.read_bytes())
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(proof,ensure_ascii=True,sort_keys=True,indent=2)+'\n',encoding='utf-8-sig')
        print(json.dumps(proof,ensure_ascii=True,sort_keys=True))
        return 0
    except (OSError,ValueError,zipfile.BadZipFile,RoleCrosswalkError) as exc:
        print(('PRIVATE original Shader audit rejected: '+str(exc)).encode('ascii','backslashreplace').decode('ascii'),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())

class OriginalShaderReferenceIndex:
    """元車両バイトと第一者Shader族索引を厳密に結合する研究用アダプター。

    モデルSHA不一致・同名MatIの矛盾は停止する。MatI参照がないときは
    未解決を返し、unknownをpaint/glassへ勝手に昇格しない。
    """
    def __init__(self,reference_crosswalk:bytes):
        if len(reference_crosswalk)>MAX_REFERENCE_BYTES:raise ShaderRoleAuditError('oversized source Shader crosswalk')
        try:ref=json.loads(reference_crosswalk)
        except (ValueError,UnicodeError) as exc:raise ShaderRoleAuditError('source Shader crosswalk JSON invalid') from exc
        if not isinstance(ref,dict) or ref.get('schema')!='lo4fh6.independent.private.cross-vehicle-mati-shader-reference.v1':
            raise ShaderRoleAuditError('source Shader crosswalk schema invalid')
        self.models={}
        self.car_id=ref.get('car_id')
        if type(self.car_id) is not int:raise ShaderRoleAuditError('original reference car identity missing')
        for m in ref.get('models',[]):
            if not isinstance(m,dict) or not isinstance(m.get('model'),str) or not _sha(m.get('source_sha256')):
                raise ShaderRoleAuditError('original reference ModelBin identity invalid')
            key=m['model'].replace('\\','/').casefold()
            if key in self.models:raise ShaderRoleAuditError('original reference duplicate ModelBin')
            mats={}
            for row in m.get('material_instances',[]):
                if not isinstance(row,dict) or not isinstance(row.get('source_name'),str) or not _sha(row.get('materialbin_sha256')) or not isinstance(row.get('shader_family'),str):
                    raise ShaderRoleAuditError('original reference material / Shader binding incomplete')
                matkey=row['source_name'].casefold()
                val=(row['shader_family'],row['materialbin_sha256'])
                if matkey in mats and mats[matkey]!=val:
                    raise ShaderRoleAuditError('original reference conflicting material identity')
                mats[matkey]=val
            self.models[key]=(m['source_sha256'],mats)

    def bind(self,model_entry:str,model_bytes:bytes,material_name:str):
        key=model_entry.replace('\\','/').casefold()
        if key not in self.models:
            raise ShaderRoleAuditError('reference does not cover the original source ModelBin')
        expected,mats=self.models[key]
        if sha256(model_bytes).hexdigest()!=expected:
            raise ShaderRoleAuditError('original ModelBin SHA mismatch; Shader binding rejected')
        if not isinstance(material_name,str) or not material_name:
            raise ShaderRoleAuditError('source MatI name missing')
        value=mats.get(material_name.casefold())
        if value is None:return None
        family,material_sha=value
        return {'source_shader_family':family,'source_materialbin_sha256':material_sha,
                'source_shader_candidate':shader_category(family),
                'game_shader_gpu_verified':False,
                'original_mask_pixels_verified':False}

def research_role_from_verified_family(current_role:str,binding:dict|None, *, has_uv3:bool,source_mask_sides:int)->str:
    """明示的な研究画面だけで用いる元Shader族ロール候補。

    元原本のMask有無/UV3とShader族が一致しない場合は停止する。
    依然としてMaskピクセル・Facing・Blend・Glass透明度は未証明。
    """
    if current_role not in {'trim','paint','glass','dark','hidden'}:
        raise ShaderRoleAuditError('unknown source role')
    if binding is None:return current_role
    if binding.get('game_shader_gpu_verified') is not False or binding.get('original_mask_pixels_verified') is not False:
        raise ShaderRoleAuditError('research source Shader evidence flags inconsistent')
    family=binding.get('source_shader_family')
    # car_glass is also used by lamp lenses and gauge covers; it is not
    # evidence of a paintable/window-translucent surface. Native window shader
    # is the only source-backed generic window candidate here.
    role='paint' if family=='car_livery' else 'glass' if family=='car_window' else None
    if role is None:return current_role
    domain=0x3f if role=='paint' else 0x7c0
    if not has_uv3 or type(source_mask_sides) is not int or not source_mask_sides&domain:
        raise ShaderRoleAuditError('source Shader role requires real native UV3 and original mask section')
    if current_role not in ('trim',role):
        raise ShaderRoleAuditError('source Shader role contradicts existing original role')
    return role


def research_shader_livery_permission(role:str,binding:dict|None,*,has_uv3:bool,mask_available_sides:int,glass_source_mask_alpha_sides:int=0)->int:
    """元Maskの存在を無条件の描画許可に読み替えない研究用ゲート。

    元car_window/car_glassが示すのは材質分類であり、原本ガラスへの図柄
    重ね合わせの許可ではない。元C_livery/ガラス専用Mask pixelの照合が
    完成するまではガラス図柄を禁止し、外板の原本UV3候補だけを保持する。
    """
    if role not in {'trim','paint','glass','dark','hidden'} or type(mask_available_sides) is not int or not 0<=mask_available_sides<2048:
        raise ShaderRoleAuditError('unverified role or source mask flags')
    if role=='glass':
        if binding is None or binding.get('source_shader_family') not in ('car_window','car_glass'):
            raise ShaderRoleAuditError('glass research requires exact original Shader family')
        # 原本Shader族は材質を示すだけ。画素が存在するMaskと実ペイントの
        # 対応面が確定し、さらにGLSLが両画素をフラグメント毎にサンプルする
        # 研究表示だけで、元ガラス面を検査候補とする。既定は0を維持。
        if not has_uv3:
            raise ShaderRoleAuditError('native glass shader requires original UV3')
        if type(glass_source_mask_alpha_sides) is not int or glass_source_mask_alpha_sides<0 or glass_source_mask_alpha_sides&~0x7c0:
            raise ShaderRoleAuditError('glass source Mask/paint section proof has invalid bits')
        if glass_source_mask_alpha_sides&~mask_available_sides:
            raise ShaderRoleAuditError('glass paint proof cannot authorize absent original Mask section')
        # car_glassは原本ヘッドライト/テール灯/内装レンズにも共通する。
        # ガラスShaderという材質分類だけで窓用Liveryの許可としない。
        # 本研究候補はcar_windowが元Mask+旧PRIVATE paintと一致した場合のみ。
        # car_glassの透明/深度上の役割は別途そのまま保全する。
        if binding['source_shader_family']=='car_glass':
            return 0
        return glass_source_mask_alpha_sides&0x7c0
    if role=='paint':
        if not has_uv3 or mask_available_sides&0x3f==0:
            raise ShaderRoleAuditError('original paint UV3 or native mask presence missing')
        return mask_available_sides&0x3f
    return 0
