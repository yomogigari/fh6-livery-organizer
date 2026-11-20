"""PRIVATE original single-surface GLB structural proof; NOT a complete car scene.

The only user-visible output is a small *original-source* geometry proof. This
stage deliberately selects ONE eligible Carbin Stock paint primitive; all
nonselected original surfaces are explicitly counted as unrepresented.
It is never a product fallback or a replacement for the accepted converter.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import struct
import zipfile
import numpy as np
from .carbin_reader import parse_carbin
from .modelbin_geometry_decoder import parse_bundle,mesh_decode,extract_raw_geometry,DecodeError
from .source_skeleton_pose import read_bones,world_bone_matrices,transform_source_geometry
from .source_surface_stage import read_source_masks,source_uv_affine,original_shadow_only
from .source_material_stage import original_materials,resolve_mesh_material
from .source_stock_scene import _source_entry,_highest_detail_lod

class ProofError(ValueError):pass


def _stream_glb(positions:np.ndarray,normals:np.ndarray,indices:np.ndarray,uvs:dict,extras:dict)->bytes:
    """Emit a native v2.0 GLB using contiguous Numpy views without per-vertex loops."""
    binary=bytearray();views=[];accessors=[]
    def accessor(values,*,kind,component_type,target,bounds=False):
        while len(binary)%4:binary.append(0)
        array=np.ascontiguousarray(values)
        offset=len(binary)
        binary.extend(array.tobytes())
        views.append({'buffer':0,'byteOffset':offset,'byteLength':array.nbytes,'target':target})
        a={'bufferView':len(views)-1,'componentType':component_type,'count':len(array),'type':kind}
        if bounds:
            if array.ndim==1:a['min']=[int(array.min())];a['max']=[int(array.max())]
            else:
                a['min']=[float(v) for v in array.min(axis=0)]
                a['max']=[float(v) for v in array.max(axis=0)]
        accessors.append(a)
        return len(accessors)-1
    xyz=np.asarray(positions,dtype='<f4');norm=np.asarray(normals,dtype='<f4')
    faces=np.asarray(indices,dtype='<u4' if len(positions)>65535 else '<u2')
    if (xyz.ndim!=2 or xyz.shape[1]!=3 or norm.shape!=xyz.shape or faces.ndim!=1
            or len(faces)%3 or len(faces)==0 or int(faces.max())>=len(xyz)):
        raise ProofError('invalid original source geometry')
    if not np.isfinite(xyz).all() or not np.isfinite(norm).all():
        raise ProofError('invalid original position or NORMAL')
    attrs={'POSITION':accessor(xyz,kind='VEC3',component_type=5126,target=34962,bounds=True),
           'NORMAL':accessor(norm,kind='VEC3',component_type=5126,target=34962)}
    for channel,values in sorted(uvs.items()):
        a=np.asarray(values,dtype='<f4')
        if a.shape!=(len(xyz),2) or not np.isfinite(a).all():
            raise ProofError('native UV attribute count mismatch')
        attrs[f'TEXCOORD_{channel}']=accessor(a,kind='VEC2',component_type=5126,target=34962)
    idx=accessor(faces,kind='SCALAR',component_type=5125 if faces.dtype.itemsize==4 else 5123,target=34963,bounds=True)
    while len(binary)%4:binary.append(0)
    doc={'asset':{'version':'2.0','generator':'LO4FH6 independent original single-source proof'},
         'buffers':[{'byteLength':len(binary)}],'bufferViews':views,'accessors':accessors,
         'scene':0,'scenes':[{'nodes':[0],'extras':{'lo4_format':'lo4_local_chassis_scene_v3','lo4_part_options':[],
           'lo4fh6_diagnostic_scope':'SINGLE_ORIGINAL_MESH_NOT_COMPLETE_CAR'}}],
         'nodes':[{'name':extras['lo4_instance_identity'],'mesh':0,'extras':extras}],
         'meshes':[{'name':extras['lo4_instance_identity'],
             'primitives':[{'attributes':attrs,'indices':idx,'mode':4}], 'extras':extras}]}
    js=json.dumps(doc,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
    js+=b' '*(-len(js)%4)
    return struct.pack('<4sII',b'glTF',2,12+8+len(js)+8+len(binary))+struct.pack('<I4s',len(js),b'JSON')+js+struct.pack('<I4s',len(binary),b'BIN\0')+binary


def produce_single_source_proof(original:Path|str)->tuple[bytes,dict]:
    """Find one real verified Stock paint surface without assuming a car-specific name.

    This proves the complete per-primitive source->native UV->pose->GLB path only.
    It does *not* prove complete original vehicle assembly, materials or GPU parity.
    """
    with zipfile.ZipFile(original) as z:
        names={info.filename.casefold():info for info in z.infolist()}
        if len(names)!=len(z.infolist()):raise ProofError('duplicate case-insensitive archive entries')
        entries=[p for p in names if p.endswith('.carbin') and '/' not in p]
        if len(entries)!=1:raise ProofError('not exactly one source carbin')
        scene=parse_carbin(z.read(names[entries[0]]));lod=_highest_detail_lod(scene['lod'])
        mask=read_source_masks(z)
        attempts=0
        for model in scene['models']:
            if not model.stock or not model.lod_flags&lod or model.option_ids or model.snap_to_parent or model.bone_id not in (0,1):
                continue
            p=_source_entry(model.path,scene['media'])
            if p not in names:raise ProofError('missing requested original ModelBin')
            raw=z.read(names[p]);blobs=parse_bundle(raw)
            skel=[b for b in blobs if b.tag=='Skel']
            if len(skel)!=1:raise ProofError('ambiguous source skeleton')
            bones=world_bone_matrices(read_bones(raw,skel[0]))
            materials=original_materials(raw,blobs)
            for blob in blobs:
                if blob.tag!='Mesh':continue
                mesh=mesh_decode(raw,blob)
                if not mesh.index_count or not mesh.lod&lod:continue
                attempts+=1
                material=resolve_mesh_material(mesh,materials)
                if material is None:continue
                # Strict intentionally narrow source-based CarPaint role; no glass/wheel/material guessing.
                if not material.name.casefold().startswith('carpaint') or mesh.skin_count:
                    continue
                source=extract_raw_geometry(raw,mesh,blobs)
                if original_shadow_only(mesh,source):continue
                if source['missing_source_normal'] or 3 not in source_uv_affine(source,mesh):continue
                if mesh.bone<0 or mesh.bone>=len(bones):raise ProofError('rigid Bone not source-verified')
                pose=transform_source_geometry(source,bone_matrix=bones[mesh.bone],
                                                instance_matrix=np.array(model.matrix,dtype=np.float64).reshape(4,4),
                                                source_position_scale=mesh.scale)
                uv=source_uv_affine(source,mesh)
                ids=np.asarray(source['indices'],dtype=np.int64).reshape(-1,3)
                valid=(ids[:,0]!=ids[:,1])&(ids[:,1]!=ids[:,2])&(ids[:,0]!=ids[:,2])
                ids=ids[valid].copy()
                if pose['winding_reversed']:ids[:,[1,2]]=ids[:,[2,1]]
                if not len(ids):raise ProofError('all original faces degenerate')
                extras={
                   'lo4_role':'paint','lo4_source_entry':p,'lo4_material_name':material.name,
                   'lo4_part_type':'','lo4_instance_identity':p+' / '+(blob.name or 'original surface'),
                   'lo4_stock_part':True,'lo4_part_option_ids':[],'lo4_draw_groups':model.draw_groups,
                   'lo4_allowed_sides':(mask.available_sides&0x3f),'lo4_projection_sides':0,
                   'lo4_material_binding_hash':'0000000000000000',
                   'lo4fh6_original_mask_xml_sha256':mask.xml_sha256,
                   'lo4fh6_original_MatI_blob_sha256':material.source_blob_sha256,
                   'lo4fh6_incomplete_vehicle':True,'lo4fh6_skin_morph_material_shader_gpu_unverified':True,
                }
                data=_stream_glb(pose['positions'],pose['normals'],ids.flatten(),uv,extras)
                return data,{'schema':'lo4fh6.firstparty-one-original-mesh-glb-proof.v1',
                  'source_car_id':scene['ordinal'],'model_entry':p,'mesh_name':blob.name or '',
                  'source_matI_name':material.name,'source_matI_sha256':material.source_blob_sha256,
                  'original_mask_xml_sha256':mask.xml_sha256,
                  'source_mask_available_sides':mask.available_sides,
                  'original_vertices':int(source['vertices']),'source_indices':int(len(ids)*3),
                  'original_uv_channels':sorted(uv),'selected_original_lod':lod,
                  'glb_bytes':len(data),'glb_sha256':sha256(data).hexdigest(),
                  'original_primitive_candidates_inspected':attempts,
                  'GLB_COVERAGE':'ONE_ORIGINAL_MESH_ONLY_NOT_FULL_CAR',
                  'gpu_validation':'NOT_PERFORMED','windows_validation':'NOT_PERFORMED',
                  'xbox_validation':'NOT_PERFORMED','release_status':'REVIEW_REQUIRED'}
    raise ProofError('no safely verified default Stock paint source primitive')


def main(argv:list[str]|None=None)->int:
    """Explicit research-only single-mesh CLI. Never silently replace product converter."""
    import argparse
    import sys
    parser=argparse.ArgumentParser(description='原本FH6の単一メッシュGLB構造証拠（車両全体ではありません）')
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--research-single-mesh-only',action='store_true',required=True)
    args=parser.parse_args(argv)
    try:
        if not args.research_single_mesh_only:
            raise ProofError('explicit research-single-mesh-only acceptance is required')
        output=args.output.resolve()
        report_path=args.report.resolve() if args.report is not None else None
        if output.suffix.casefold()!='.glb' or output.exists() or output.is_symlink():
            raise ProofError('research output must be a new .glb file')
        if report_path is not None and (report_path.suffix.casefold()!='.json' or report_path.exists() or report_path.is_symlink() or report_path==output):
            raise ProofError('research report must be a new .json file')
        payload,record=produce_single_source_proof(args.archive)
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as fp:fp.write(payload)
        if report_path is not None:
            report_path.parent.mkdir(parents=True,exist_ok=True)
            with report_path.open('x',encoding='utf-8-sig') as fp:
                fp.write(json.dumps(record,ensure_ascii=True,indent=2,sort_keys=True)+'\n')
        sys.stdout.write(json.dumps(record,ensure_ascii=True,sort_keys=True)+'\n')
        return 0
    except (OSError,ValueError,zipfile.BadZipFile,DecodeError) as exc:
        sys.stderr.write('Research single-source GLB refused: '+str(exc).encode('ascii','backslashreplace').decode('ascii')+'\n')
        return 2

if __name__=='__main__':
    raise SystemExit(main())
