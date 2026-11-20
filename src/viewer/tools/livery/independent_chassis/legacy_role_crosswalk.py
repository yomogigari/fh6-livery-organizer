"""旧正常GLBと独自Stock GLBの実プリミティブ交差確認（研究専用）。

旧r485のroleは外観比較の証拠に限る。MaterialBin/Shader/BC4・Mask
のFH6ランタイム証明ではないため、このモジュールは製品ロールを書き換えない。
SHA・実頂点・Index・UV3が一致しないものを一致と扱わない。
ゲーム原本のバイトを出力JSONへ含めない。
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import stat
import struct
import sys
import zipfile
import numpy as np

MAX_GLB = 256 * 1024 * 1024
MAX_JSON = 48 * 1024 * 1024
MAX_ZIP_MEMBERS = 1024
KNOWN = {'paint', 'glass', 'dark', 'hidden', 'trim'}

class RoleCrosswalkError(ValueError): pass


def _checked_glb(data: bytes):
    if len(data) < 28 or len(data) > MAX_GLB or data[:4] != b'glTF':
        raise RoleCrosswalkError('GLB signature/size invalid')
    magic, version, total = struct.unpack_from('<4sII', data)
    if version != 2 or total != len(data):
        raise RoleCrosswalkError('GLB version/declared size mismatch')
    jl, jt = struct.unpack_from('<I4s', data, 12)
    if jl < 2 or jl > MAX_JSON or jl % 4 or jt != b'JSON' or 20+jl+8 > len(data):
        raise RoleCrosswalkError('GLB JSON chunk invalid')
    bl, bt = struct.unpack_from('<I4s', data, 20+jl)
    if bt != b'BIN\0' or bl % 4 or 28+jl+bl != len(data):
        raise RoleCrosswalkError('GLB BIN chunk invalid')
    try:
        doc = json.loads(data[20:20+jl])
    except (UnicodeError, ValueError) as exc:
        raise RoleCrosswalkError('GLB JSON failed to decode') from exc
    if not isinstance(doc,dict) or not isinstance(doc.get('meshes'),list) or not isinstance(doc.get('bufferViews'),list) or not isinstance(doc.get('accessors'),list):
        raise RoleCrosswalkError('GLB mesh/buffer layout missing')
    if len(doc['meshes']) > 25000 or len(doc['accessors']) > 500000:
        raise RoleCrosswalkError('GLB metadata exceeds analysis budget')
    if doc.get('buffers') != [{'byteLength':bl}]:
        raise RoleCrosswalkError('GLB buffer refers to nonlocal or incomplete bytes')
    return doc, memoryview(data)[28+jl:], sha256(data).hexdigest()


def _accessor(scene, value, kind, count=None):
    doc, binary, _ = scene
    a = doc['accessors']
    if type(value) is not int or not 0 <= value < len(a):
        raise RoleCrosswalkError('invalid accessor index')
    ac = a[value]
    if not isinstance(ac,dict) or ac.get('sparse') is not None or ac.get('type') != kind:
        raise RoleCrosswalkError('unsupported/missing/sparse accessor')
    typ = ac.get('componentType')
    if typ not in (5123, 5125, 5126):
        raise RoleCrosswalkError('unrecognized accessor component type')
    if kind == 'VEC3' and typ != 5126 or kind == 'VEC2' and typ != 5126 or kind == 'SCALAR' and typ not in (5123,5125):
        raise RoleCrosswalkError('unexpected source geometry accessor encoding')
    width = {'SCALAR':1,'VEC2':2,'VEC3':3}[kind]
    dtype = {5123:'<u2',5125:'<u4',5126:'<f4'}[typ]
    views = doc['bufferViews']
    vindex = ac.get('bufferView')
    n=ac.get('count')
    if type(vindex) is not int or not 0 <= vindex < len(views) or type(n) is not int or n<1 or n>4_000_000 or count is not None and n != count:
        raise RoleCrosswalkError('invalid accessor vertex/index count')
    v=views[vindex]
    if not isinstance(v,dict) or v.get('buffer') != 0:
        raise RoleCrosswalkError('accessor references nonlocal buffer')
    row=width*np.dtype(dtype).itemsize
    stride=v.get('byteStride',row)
    off=v.get('byteOffset',0);local=ac.get('byteOffset',0);length=v.get('byteLength')
    if not all(type(x) is int for x in (stride,off,local,length)) or stride<row or stride%np.dtype(dtype).itemsize or min(off,local,length)<0:
        raise RoleCrosswalkError('accessor offsets/stride invalid')
    size=(n-1)*stride+row
    if local+size>length or off+local+size>len(binary):
        raise RoleCrosswalkError('accessor data exceeds original GLB BIN')
    arr=np.ndarray((n,width),dtype=dtype,buffer=binary,offset=off+local,strides=(stride,np.dtype(dtype).itemsize))
    if kind!='SCALAR' and not np.isfinite(arr).all():
        raise RoleCrosswalkError('nonfinite native vertex/UV')
    return arr


def _meshes(src):
    doc,_,_=src
    for m in doc['meshes']:
        if not isinstance(m,dict) or not isinstance(m.get('extras'),dict) or len(m.get('primitives',[]))!=1:
            raise RoleCrosswalkError('source mesh has unsupported primitive/extras layout')
        prim=m['primitives'][0]
        attrs=prim.get('attributes')
        if not isinstance(attrs,dict) or prim.get('mode',4)!=4:
            raise RoleCrosswalkError('source mesh primitive unsupported')
        pos=_accessor(src,attrs.get('POSITION'),'VEC3')
        idx=_accessor(src,prim.get('indices'),'SCALAR')
        if len(idx)%3 or int(idx.max())>=len(pos):
            raise RoleCrosswalkError('source mesh triangles invalid')
        uv3=None
        if 'TEXCOORD_3' in attrs:
            uv3=_accessor(src,attrs['TEXCOORD_3'],'VEC2',len(pos))
        e=m['extras']
        origin=e.get('lo4_source_entry');material=e.get('lo4_material_name');role=e.get('lo4_role')
        if not isinstance(origin,str) or not origin.lower().endswith('.modelbin') or not isinstance(material,str) or role not in KNOWN:
            raise RoleCrosswalkError('source mesh role/MatI identity absent')
        key=(origin.replace('\\','/').casefold(), material.casefold(),len(pos),len(idx))
        yield key, role, pos, idx, uv3


def compare_original_role_source(original_glb: bytes, independent_glb: bytes)->dict:
    """比較報告のみ返す。結果から描画用 role を自動更新してはならない。"""
    original=_checked_glb(original_glb);fresh=_checked_glb(independent_glb)
    doc=fresh[0];flags=doc.get('scenes',[{}])[0].get('extras',{})
    if flags.get('lo4fh6_release_approval') is not False or not str(flags.get('lo4fh6_research_only','')).startswith('SOURCE_GEOMETRY_COVERAGE'):
        raise RoleCrosswalkError('right-hand GLB is not an explicit independent research candidate')
    index=defaultdict(list)
    for key,role,pos,tri,uv in _meshes(original):
        index[key].append((role,pos,tri,uv))
    result=Counter(); differences=Counter(); matched=0; strict_uv3=0
    for key,role,pos,tri,uv in _meshes(fresh):
        matched_roles=[];uv_matches=[]
        for oldrole,oldpos,oldtri,olduv in index.get(key,[]):
            if not np.array_equal(tri,oldtri): continue
            if np.max(np.abs(pos.astype('f8')-oldpos.astype('f8'))) > 5e-6:continue
            matched_roles.append(oldrole)
            uv_matches.append(olduv is not None and uv is not None and np.max(np.abs(olduv.astype('f8')-uv.astype('f8'))) <= 5e-6)
        role_set=set(matched_roles)
        if len(role_set)!=1:
            result['no_strict_original_match' if not role_set else 'ambiguous_original_roles']+=1
            continue
        matched+=1
        oldrole=next(iter(role_set))
        if oldrole!=role:
            differences[f'{role}_versus_{oldrole}']+=1
            if oldrole in ('paint','glass'):
                if not all(uv_matches):
                    result['paint_or_glass_role_conflict_without_exact_uv3']+=1
                else:
                    strict_uv3+=1
        else:result['role_same_'+role]+=1
    out={'schema':'lo4fh6.r485-independent-original-role-source-crosswalk.v1',
         'legacy_glb_sha256':original[2],'independent_glb_sha256':fresh[2],
         'legacy_meshes':len(original[0]['meshes']),'independent_meshes':len(fresh[0]['meshes']),
         'matched_meshes_source_matI_vertices_indices':matched,
         'role_difference_counts':dict(sorted(differences.items())),
         'comparison_counts':dict(sorted(result.items())),
         'role_mismatches_with_exact_original_UV3_paint_or_glass':strict_uv3,
         'game_materialbin_shader_mask_verified':False,
         'role_candidates_applied_to_product':False,
         'validity':'RESEARCH_ONLY__NOT_SHADER_OR_XBOX_ACCEPTANCE'}
    return out


def _glb_from_preview_cache(zip_path: Path)->bytes:
    with zipfile.ZipFile(zip_path) as z:
        infos=z.infolist()
        if len(infos)>MAX_ZIP_MEMBERS:raise RoleCrosswalkError('untrusted/massive archive index')
        for i in infos:
            if ('..' in i.filename.replace('\\','/').split('/') or i.filename.startswith('/') or i.flag_bits&1 or
                stat.S_IFMT(i.external_attr>>16)==stat.S_IFLNK or i.file_size>MAX_GLB):
                raise RoleCrosswalkError('unsafe preview cache member')
        names=[i for i in infos if i.filename.lower().endswith('.glb')]
        if len(names)!=1:raise RoleCrosswalkError('old baseline must contain exactly one GLB')
        return z.read(names[0])


def main(argv=None)->int:
    p=argparse.ArgumentParser(description='研究専用：正常r485/独自Stock GLBの原本ロール照合')
    p.add_argument('--r485-preview-cache',required=True,type=Path)
    p.add_argument('--independent-glb',required=True,type=Path)
    p.add_argument('--report',required=True,type=Path)
    p.add_argument('--research-only',action='store_true')
    a=p.parse_args(argv)
    try:
        if not a.research_only:raise RoleCrosswalkError('explicit research-only acknowledgement required')
        report=a.report.resolve()
        if a.report.is_symlink() or report.exists() or a.report.suffix.lower()!='.json':
            raise RoleCrosswalkError('new JSON report path required; overwrite prohibited')
        src=_glb_from_preview_cache(a.r485_preview_cache)
        candidate=a.independent_glb.read_bytes()
        proof=compare_original_role_source(src,candidate)
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(proof,ensure_ascii=True,indent=2,sort_keys=True)+'\n',encoding='utf-8-sig')
        print(json.dumps(proof,ensure_ascii=True,sort_keys=True))
        return 0
    except (OSError,ValueError,zipfile.BadZipFile) as exc:
        print(('Research source role crosswalk rejected: '+str(exc)).encode('ascii','backslashreplace').decode('ascii'),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
