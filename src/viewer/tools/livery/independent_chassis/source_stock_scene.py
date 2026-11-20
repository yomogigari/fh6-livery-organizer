"""Read-only original Carbin default stock/LOD->ModelBin source scene preflight.

Only validates native membership and geometry. No material role, shader, glass,
Mask/Facing projection or GPU integration is asserted by this Stage.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import zipfile
from .carbin_reader import parse_carbin,CarbinFormatError
from .modelbin_geometry_decoder import parse_bundle,mesh_decode,extract_raw_geometry,DecodeError
from .source_skeleton_pose import read_bones,world_bone_matrices
from .source_surface_stage import read_source_masks,source_uv_affine,original_shadow_only
from .source_deformation_stage import decode_original_skin,decode_original_morph
from .source_material_stage import original_materials,resolve_mesh_material

class StockSceneError(ValueError):pass

def _source_entry(game_path:str, media:str)->str:
    source=game_path.replace('\\','/').casefold()
    prefix='game:/media/cars/'+media.casefold()+'/'
    if not source.startswith(prefix):raise StockSceneError('unverifiable original model path')
    part=source[len(prefix):]
    if not part.startswith('scene/') or not part.endswith('.modelbin') or '/../' in part:
        raise StockSceneError('unverifiable original model path')
    return part

def _highest_detail_lod(mask:int)->int:
    for i in range(7):
        if mask & (1<<i):return 1<<i
    raise StockSceneError('no source scene LOD declaration')

def inspect_stock_original(path:Path|str)->dict:
    """Fail closed on missing selected baseline references or unsupported geometry.

    Optional upgrade model sources are parsed by Carbin but do not affect baseline.
    Complete livery Mask pixels/material classification remain downstream gates.
    """
    counts=Counter()
    with zipfile.ZipFile(path) as z:
        available={}
        for info in z.infolist():
            if info.is_dir():continue
            k=info.filename.casefold()
            if k in available:raise StockSceneError('duplicate original ZIP names')
            available[k]=info
        carbin=[x for x in available if x.endswith('.carbin') and '/' not in x]
        if len(carbin)!=1:raise StockSceneError('exactly one original Carbin required')
        scene=parse_carbin(z.read(available[carbin[0]]))
        media=scene['media'] or carbin[0][:-7]
        lod=_highest_detail_lod(scene['lod'])
        masks=read_source_masks(z)
        cache={}
        for ref in scene['models']:
            counts['declared_model_instances']+=1
            entry=_source_entry(ref.path,media)
            if entry not in available:raise StockSceneError('missing original instance source '+entry)
            if not ref.stock:
                counts['optional_instances_unselected']+=1
                continue
            if ref.lod_flags and not (ref.lod_flags & lod):
                counts['baseline_instances_without_selected_lod']+=1
                continue
            if entry not in cache:
                raw=z.read(available[entry]);blobs=parse_bundle(raw)
                skeletons=[b for b in blobs if b.tag=='Skel']
                if len(skeletons)!=1:raise StockSceneError('source model has no exact skeleton')
                world=world_bone_matrices(read_bones(raw,skeletons[0]))
                materials=original_materials(raw,blobs)
                cache[entry]=(raw,blobs,world,materials)
            raw,blobs,world,materials=cache[entry]
            counts['selected_stock_instances']+=1
            accepted_for_instance=0
            for blob in blobs:
                if blob.tag!='Mesh':continue
                m=mesh_decode(raw,blob)
                if not (m.lod & lod) or not m.index_count:continue
                data=extract_raw_geometry(raw,m,blobs)
                if m.bone<0 or m.bone>=len(world):raise StockSceneError('mesh rigid Bone reference unresolved')
                if original_shadow_only(m,data):
                    counts['excluded_verified_shadow_only_meshes']+=1
                    continue
                uv=source_uv_affine(data,m)
                material=resolve_mesh_material(m,materials)
                if material is None:
                    raise StockSceneError('source visible mesh lacks exact material association')
                counts['original_material_id_resolved_visible_meshes']+=1
                if not material.source_blob_bytes:
                    counts['original_material_shader_payload_unresolved_meshes']+=1
                if m.skin_count:
                    resolved_skin=decode_original_skin(raw,m,blobs,bone_count=len(world))
                    if resolved_skin is None or resolved_skin.vertex_count!=data['vertices']:
                        raise StockSceneError('visible Skin source vertex span not exactly resolved')
                    counts['original_skin_binding_verified_meshes']+=1
                    counts['original_skin_binding_verified_vertices']+=resolved_skin.vertex_count
                    counts['original_skin_weight_pairs']+=resolved_skin.weights.size
                elif m.skin_id!=-1:
                    raise StockSceneError('unmapped Skin reference with no declared elements')
                if m.morph_count:
                    resolved_morph=decode_original_morph(raw,m,blobs)
                    if resolved_morph is None or resolved_morph.vertex_count!=data['vertices']:
                        raise StockSceneError('visible Morph source vertex span not exactly resolved')
                    counts['original_morph_binding_verified_meshes']+=1
                    counts['original_morph_binding_verified_vertices']+=resolved_morph.vertex_count
                    counts['original_morph_delta_vectors']+=resolved_morph.vertex_count*resolved_morph.target_count*2
                elif m.morph_id!=-1:
                    raise StockSceneError('unmapped Morph reference with no declared targets')
                counts['selected_stock_visible_meshes']+=1
                counts['selected_stock_visible_triangles']+=data['triangles']
                counts['selected_stock_visible_vertices']+=data['vertices']
                counts['selected_stock_visible_uv3_meshes']+=3 in uv
                counts['selected_stock_visible_uv4_meshes']+=4 in uv
                counts['selected_meshes_with_morph']+=m.morph_count>0
                counts['selected_meshes_with_skin']+=m.skin_count>0
                accepted_for_instance+=1
            if not accepted_for_instance:
                raise StockSceneError('baseline source instance selected but has no visible model at original scene LOD')
    if not counts['selected_stock_visible_meshes']:
        raise StockSceneError('no source default stock geometry')
    return {'car_id':scene['ordinal'],'scene_lod':lod,'source_mask_available_sides':masks.available_sides,
            'source_mask_xml_sha256':masks.xml_sha256, 'counts':dict(sorted(counts.items())),
            'source_stage':'CARBIN_STOCK_LOD0_VISIBLE_GEOMETRY_PREFLIGHT__NO_COMPLETE_GLB',
            'unverified':['runtime skin joint pose and inverse bind matrices', 'morph coefficients and damage/fitment selection', 'material/shader','full Native Mask pixel coverage',
                          'glass depth/reflection', 'native original tire/wheel assembly', 'GPU/Windows/Xbox']}
