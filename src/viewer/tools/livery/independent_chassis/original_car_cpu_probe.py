"""独立コンバーターCPU原本検査：CLIはゲーム原本を出力しない。

    python -m independent_chassis.original_car_cpu_probe --archive "<private-car>.zip" \
       --output "<evidence>.json"

先にCarbin ZIP全参照照合を実施する source_inventory と別入口。
製品既定のGLB出力機能ではなく、性能測定用の研究Stage。
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import zipfile
from .modelbin_geometry_decoder import DecodeError, parse_bundle, mesh_decode, extract_raw_geometry
from .source_skeleton_pose import read_bones, world_bone_matrices
from .source_deformation_stage import decode_original_skin, decode_original_morph

MAX_ARCHIVE_BYTES=2*1024*1024*1024
MAX_MODEL_BYTES=512*1024*1024
MAX_MODELS=10000

class SourceProbeError(ValueError): pass


def _sha256(path:Path)->str:
    h=sha256()
    with path.open('rb') as f:
        for buf in iter(lambda:f.read(1024*1024),b''):h.update(buf)
    return h.hexdigest()


def probe_archive(path:Path|str)->dict:
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>MAX_ARCHIVE_BYTES:
        raise SourceProbeError('local original vehicle ZIP is missing, symlink, or exceeds safe size')
    start=time.perf_counter()
    counts=Counter()
    with zipfile.ZipFile(path) as z:
        model_entries=[]
        visited=set()
        for entry in z.infolist():
            name=entry.filename.replace('\\','/')
            relative=PurePosixPath(name)
            if name!=entry.filename or name.startswith('/') or '..' in relative.parts or '\x00' in name or ':' in name:
                raise SourceProbeError('unsafe original vehicle ZIP path')
            if entry.is_dir():continue
            canonical=name.casefold()
            if canonical in visited or stat.S_IFMT(entry.external_attr>>16)==stat.S_IFLNK:
                raise SourceProbeError('archive contains ambiguous file or symlink')
            visited.add(canonical)
            if entry.flag_bits & 1:raise SourceProbeError('encrypted original vehicle ZIP entry')
            if canonical.endswith('.modelbin'):
                if entry.file_size>MAX_MODEL_BYTES or entry.compress_type not in (0,8):
                    raise SourceProbeError('source model asset size or compression unsupported')
                model_entries.append(entry)
        if not model_entries or len(model_entries)>MAX_MODELS:
            raise SourceProbeError('no ModelBin or unsafe model count')
        for entry in model_entries:
            raw=z.read(entry)
            blobs=parse_bundle(raw)
            skels=[blob for blob in blobs if blob.tag=='Skel']
            if len(skels)!=1:
                raise SourceProbeError('source model has missing or ambiguous Skeleton')
            bones=read_bones(raw,skels[0]);world=world_bone_matrices(bones)
            counts['modelbin_files']+=1
            counts['skeleton_bones_total']+=len(bones)
            counts['source_bundle_blobs_total']+=len(blobs)
            for blob in blobs:
                if blob.tag!='Mesh':continue
                mesh=mesh_decode(raw,blob)
                counts['mesh_records_total']+=1
                if mesh.bone>=0 and mesh.bone>=len(world):
                    raise SourceProbeError('source Mesh references missing Bone')
                if mesh.index_count==0:continue
                geom=extract_raw_geometry(raw,mesh,blobs)
                counts['decoded_meshes']+=1
                counts['vertices_all_meshes']+=geom['vertices']
                counts['triangles_all_meshes']+=geom['triangles']
                counts['meshes_with_uv3']+=('TEXCOORD',3) in geom['arrays']
                counts['meshes_with_uv4']+=('TEXCOORD',4) in geom['arrays']
                counts['meshes_without_source_normal']+=geom['missing_source_normal']
                counts['meshes_with_multiple_material_groups']+=len(mesh.material_groups)>1
                if mesh.skin_count:
                    skin=decode_original_skin(raw,mesh,blobs,bone_count=len(bones))
                    if skin is None or skin.vertex_count!=geom['vertices']:
                        raise SourceProbeError('original Skin does not map exact source vertex span')
                    counts['source_skin_buffers_exactly_bound']+=1
                    counts['source_skin_vertices_verified']+=skin.vertex_count
                if mesh.morph_count:
                    morph=decode_original_morph(raw,mesh,blobs)
                    if morph is None or morph.vertex_count!=geom['vertices']:
                        raise SourceProbeError('original Morph does not map exact source vertex span')
                    counts['source_morph_buffers_exactly_bound']+=1
                    counts['source_morph_vertices_verified']+=morph.vertex_count
                    counts['source_damage_morph_records']+=bool(mesh.is_morph_damage)
                    counts['source_non_damage_morph_records']+=not mesh.is_morph_damage
    if counts['decoded_meshes']==0:raise SourceProbeError('no source geometry decoded')
    duration=time.perf_counter()-start
    return {'schema':'lo4fh6.firstparty-original-modelbin-cpu-probe.v1',
            'captured_at_jst':datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST'),
            'source_zip_basename':path.name,
            'source_zip_size_bytes':path.stat().st_size,
            'source_zip_sha256':_sha256(path),
            'source_stage':'REAL_VERTEX_UV_SKELETON_ONLY_NOT_COMPLETE_GLB',
            'source_deformation_stage':'ORIGINAL_SKIN_HALF_WEIGHTS_AND_MORPH_DELTAS_BOUND_NOT_RUNTIME_EVALUATED',
            'counts':dict(sorted(counts.items())),
            'source_decode_seconds':round(duration,6),
            'source_normal_absence_fabricated':False,
            'not_performed':['runtime Skin bind pose/inverse bind matrices','runtime Morph coefficients/damage fitment','Carbin fitted stock scene','native material/shader/mask/uv-affine',
                             'complete car GLB output','real GPU','Windows','Xbox'],
            'public_release_status':'REVIEW_REQUIRED'}


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description='FH6 original car ModelBin read-only CPU evidence probe')
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=False)
    args=parser.parse_args(argv)
    try:
        report=probe_archive(args.archive)
        body=json.dumps(report,sort_keys=True,ensure_ascii=True,indent=2)+'\n'
        if args.output is not None:
            target=args.output.resolve()
            if target.exists():raise SourceProbeError('output already exists; no overwrite of evidence')
            if target.suffix.casefold()!='.json':raise SourceProbeError('output must be a JSON file')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x',encoding='utf-8-sig',newline='\n') as stream:stream.write(body)
        sys.stdout.write(body)
        return 0
    except (OSError,ValueError,zipfile.BadZipFile,DecodeError) as exc:
        # ASCII-safe stderr on CP932 consoles, without leaking personal/full paths.
        sys.stderr.write('Independent source probe failed: '+str(exc).encode('ascii','backslashreplace').decode('ascii')+'\n')
        return 2

if __name__=='__main__':raise SystemExit(main())
