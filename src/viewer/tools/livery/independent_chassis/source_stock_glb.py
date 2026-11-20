"""
全Stock原本幾何を用いる研究用GLB。ゲーム内部Pose／Shaderと同等なViewerではない。
原本で確認したShadow専用Meshを除き、幾何を無告知で省略しない。
剛体Bone・Carbin原作者行列を各Primitiveへ適用する。
Skin／Morph／非Root Attachment／原本Material／Shader／Glass／Mask画素は未適用・未検証と明示し、標準製品へ自動採用しない。
FH6原本バイトはPRIVATEとして保持する。
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from pathlib import PurePosixPath
import stat
import struct
import sys
import zipfile
import numpy as np
from .carbin_reader import parse_carbin
from .modelbin_geometry_decoder import parse_bundle,mesh_decode,extract_raw_geometry,DecodeError
from .source_skeleton_pose import read_bones,world_bone_matrices,transform_source_geometry,original_modelbin_attachment_matrix,presentation_brake_matrices,presentation_control_arm_matrices
from .source_surface_stage import read_source_masks,source_uv_affine,original_shadow_only,native_uv3_side_allowance
from .source_material_stage import original_materials,resolve_mesh_material
from .source_deformation_stage import decode_original_skin,decode_original_morph
from .source_deformation_glb import append_source_deformation_accessors
from .original_shader_role_audit import OriginalShaderReferenceIndex,research_role_from_verified_family,research_shader_livery_permission
from .source_stock_scene import _source_entry,_highest_detail_lod
from .source_static_preview_selection import (select_static_stock_instances,select_part_option_overlay,select_static_model_meshes,
    original_part_type_from_carbin,original_static_instance_identity,
    source_static_hidden_surface_reason,clean_original_static_triangle_indices,
    original_material_binding_hash)
from .source_wheel_identity_bridge import source_wheel_or_brake_identity
from .source_static_role import static_mesh_role, static_livery_sides
from .source_runtime_deformation import apply_verified_source_deformation
from .source_pose_input_contract import validate_original_deformation_input

MAX_RESEARCH_GLB_BYTES=256*1024*1024

class StockGlbResearchError(ValueError):pass

class _Writer:
    def __init__(self):
        self.binary=bytearray()
        self.views=[]
        self.accessors=[]
        self.nodes=[]
        self.meshes=[]

    def accessor(self,values,kind,component,target,bounds=False):
        source=np.ascontiguousarray(values)
        if source.size==0 or source.nbytes>MAX_RESEARCH_GLB_BYTES:
            raise StockGlbResearchError('source mesh has unsupported vertex/index buffer size')
        while len(self.binary)%4:self.binary.append(0)
        offset=len(self.binary)
        if offset+source.nbytes>MAX_RESEARCH_GLB_BYTES:
            raise StockGlbResearchError('research full-stock GLB would exceed safety limit')
        self.binary.extend(source.tobytes())
        view={'buffer':0,'byteOffset':offset,'byteLength':source.nbytes}
        if target is not None: view['target']=target
        self.views.append(view)
        accessor={'bufferView':len(self.views)-1,'componentType':component,'count':len(source),'type':kind}
        if bounds:
            if source.ndim==1:
                accessor['min']=[int(source.min())];accessor['max']=[int(source.max())]
            else:
                accessor['min']=[float(x) for x in source.min(axis=0)]
                accessor['max']=[float(x) for x in source.max(axis=0)]
        self.accessors.append(accessor)
        return len(self.accessors)-1

    def append(self,positions,normals,indices,uvs,extras):
        xyz=np.asarray(positions,dtype='<f4');norm=np.asarray(normals,dtype='<f4')
        idx=np.asarray(indices,dtype='<u2' if len(xyz)<65536 else '<u4').reshape(-1)
        if xyz.ndim!=2 or xyz.shape[1]!=3 or norm.shape!=xyz.shape or len(xyz)==0 or len(idx)%3 or not len(idx) or int(idx.max())>=len(xyz):
            raise StockGlbResearchError('invalid source-authored mesh shape/indices')
        if not np.isfinite(xyz).all() or not np.isfinite(norm).all():
            raise StockGlbResearchError('nonfinite source geometry')
        attributes={'POSITION':self.accessor(xyz,'VEC3',5126,34962,True),
                    'NORMAL':self.accessor(norm,'VEC3',5126,34962)}
        for channel,raw in sorted(uvs.items()):
            uv=np.asarray(raw,dtype='<f4')
            if channel<0 or channel>4 or uv.shape!=(len(xyz),2) or not np.isfinite(uv).all():
                raise StockGlbResearchError('native UV source dropped or incompatible')
            attributes[f'TEXCOORD_{channel}']=self.accessor(uv,'VEC2',5126,34962)
        index=self.accessor(idx,'SCALAR',5123 if idx.dtype.itemsize==2 else 5125,34963,True)
        ordinal=len(self.nodes)
        if extras.get('lo4fh6_source_static_instance_verified') is True:
            # 元参照製品 Program.AppendMeshes: ModelBin basename + 生Mesh名。
            # NodeとMeshの両名称を保ち、製品側が車輪名/パネル名を認識可能にする。
            # 参照製品はModelBin原本ZIPエントリの大文字小文字を保持して命名する。
            # 検索用casefoldパスを表示名に転用すると車輪・外板の名前が退化する。
            source_name=extras.get('lo4fh6_original_modelbin_basename')
            mesh_label=extras['lo4fh6_source_mesh_name']
            if not isinstance(source_name,str) or not source_name or not mesh_label:
                raise StockGlbResearchError('original static mesh name is unavailable')
            mesh_name=f'{source_name} :: {mesh_label}'
        else:
            mesh_name=extras['lo4fh6_source_mesh_name'] if extras.get('lo4fh6_part_type')=='WheelStyle' else extras['lo4fh6_instance_identity']
        node_name=mesh_name if extras.get('lo4fh6_source_static_instance_verified') is True else extras['lo4fh6_instance_identity']
        self.nodes.append({'mesh':ordinal,'name':node_name,'extras':extras})
        self.meshes.append({'name':mesh_name,'primitives':[{'attributes':attributes,'indices':index,'mode':4}],'extras':extras})

    def attach_original_deformation(self, skin, morph, vertex_count):
        """元Skin/Morph参照を非描画accessorとして保全する。GLB画素・製品経路は変えない。"""
        if not self.meshes or len(self.meshes)!=len(self.nodes):
            raise StockGlbResearchError('deformation binding has no matching source mesh')
        refs=append_source_deformation_accessors(self,skin=skin,morph=morph,vertex_count=vertex_count)
        if refs:
            self.meshes[-1]['extras']['lo4fh6_original_deformation_accessors']=refs
            self.nodes[-1]['extras']['lo4fh6_original_deformation_accessors']=refs

    def pack(self,scene_options,*,original_source_options=None,static_undeformed=False,part_option_overlay=None):
        if not self.meshes:
            raise StockGlbResearchError('no original Stock meshes to assemble')
        while len(self.binary)%4:self.binary.append(0)
        extras={'lo4fh6_format':'lo4fh6_source_chassis_scene_v1',
                'lo4fh6_part_options':scene_options,
                **({'lo4fh6_original_carbin_part_options':original_source_options}
                   if original_source_options is not None else {}),
                # 部品の選択肢の重ね合わせ（その選択肢で加わる部品だけ）。Viewerは置き換える純正の部品を隠す。
                **({'lo4fh6_part_option_overlay':part_option_overlay}
                   if part_option_overlay is not None else {}),
                'lo4fh6_research_only':'SOURCE_GEOMETRY_COVERAGE__NOT_GAME_RUNTIME_POSE_OR_SHADER',
                'lo4fh6_deformations':('Original Skin/Morph declarations kept; the static preview needs no runtime pose, source payload NOT DECODED' if static_undeformed else 'Skin/Morph source-linked, coefficients/pose UNAPPLIED'),
                'lo4fh6_original_masks':'Resource presence only, NOT native mask pixels',
                'lo4fh6_release_approval':False}
        doc={'asset':{'version':'2.0','generator':'LO4FH6 firstparty source-geometry coverage research'},
             'buffers':[{'byteLength':len(self.binary)}],'bufferViews':self.views,'accessors':self.accessors,
             'scene':0,'scenes':[{'nodes':list(range(len(self.nodes))),'extras':extras}],
             'nodes':self.nodes,'meshes':self.meshes}
        js=json.dumps(doc,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
        js+=b' '*(-len(js)%4)
        if len(js)+len(self.binary)+28>MAX_RESEARCH_GLB_BYTES:
            raise StockGlbResearchError('GLB including metadata exceeds research limit')
        return struct.pack('<4sII',b'glTF',2,28+len(js)+len(self.binary))+struct.pack('<I4s',len(js),b'JSON')+js+struct.pack('<I4s',len(self.binary),b'BIN\0')+self.binary


# 原本で地面（車の座標の Y=0 付近）より 2 m 以上下に置かれた部品は、ゲームでは見えない（カメラは地面より上）。
# 静止プレビューで描くとカメラの範囲が広がり、車が画面の外に出る（NIS_Patrol_72 の trunkCustom_a の低詳細版
# （Carbin の lod_flags は LODS のみ）は頂点が 10 m 下。2026-11-18 の全車体の撮影で車が写らなかった）。
STATIC_PARKED_BELOW_GROUND_Y = -2.0


def build_research_stock_geometry_glb(original:Path|str, *, preserve_original_deformation:bool=False, source_shader_reference:bytes|None=None, shader_role_trial:bool=False, source_wheel_identity_trial:bool=False, verified_deformation_inputs:dict|None=None,
                                      source_original_static_selection:bool=False, source_part_selection:dict[str,int]|None=None,
                                      source_loose_entries:list[str]|None=None,
                                      source_part_overlay_only:bool=False)->tuple[bytes,dict]:
    """
    原本照合済みの表示Stock幾何をすべて対象とする。
    描画・Windows実機の受入を主張しない。
    """
    writer=_Writer();c=Counter()
    if verified_deformation_inputs is not None and not isinstance(verified_deformation_inputs,dict):
        raise StockGlbResearchError('source deformation evidence must be an explicit mesh-keyed dictionary')
    used_deformation_keys=set();wheel_corners=set();deformation_requirements=[]
    wheel_source_identities=set();unmapped_source_wheel_bones=set()
    skipped_nondrawable_source_meshes=[]
    if source_loose_entries is not None and (not source_original_static_selection or source_part_selection):
        raise StockGlbResearchError('loose ModelBin preview cannot mix with Carbin part selection')
    if source_part_selection and not source_original_static_selection:
        raise StockGlbResearchError('explicit Carbin upgrade selection requires original static source mode')
    if source_part_overlay_only and (not source_original_static_selection or source_loose_entries is not None
                                     or not isinstance(source_part_selection,dict) or len(source_part_selection)!=1):
        raise StockGlbResearchError('part option overlay requires exactly one Carbin part selection')
    part_option_overlay=None
    shader_index=OriginalShaderReferenceIndex(source_shader_reference) if source_shader_reference is not None else None
    if shader_role_trial and shader_index is None:
        raise StockGlbResearchError('source Shader role trial requires exact PRIVATE ModelBin/MaterialBin reference')
    with zipfile.ZipFile(original) as z:
        names={}
        for info in z.infolist():
            if info.is_dir():continue
            key=info.filename.casefold()
            if (key in names or info.filename != info.filename.replace('\\','/') or
                info.filename.startswith('/') or ':' in info.filename or
                '.' in PurePosixPath(info.filename).parts or
                '..' in PurePosixPath(info.filename).parts or
                stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK or
                info.flag_bits&1 or info.file_size>512*1024*1024):
                raise StockGlbResearchError('unsafe/ambiguous original vehicle archive')
            names[key]=info
        carbins=[x for x in names if x.endswith('.carbin') and '/' not in x]
        if len(carbins)!=1:raise StockGlbResearchError('original ZIP must contain exactly one source Carbin')
        scene=parse_carbin(z.read(names[carbins[0]]));lod=_highest_detail_lod(scene['lod'])
        if source_loose_entries is not None:
            # 参照製品 ExtractLooseMeshes: CarBody / Identity / BoneId -1 / no options.
            # 元Carbinの姿勢を流用せず、既存Mesh decoderとGLB encoderだけを共有。
            from .carbin_reader import ModelRef
            if (not isinstance(source_loose_entries, list) or not source_loose_entries
                    or any(not isinstance(name, str) or not name for name in source_loose_entries)):
                raise StockGlbResearchError('loose ModelBin selection must be a nonempty list')
            normalized = [name.casefold() for name in source_loose_entries]
            if (len(normalized) != len(set(normalized))
                    or any(not name.startswith('scene/') or not name.endswith('.modelbin')
                           or name not in names or '..' in PurePosixPath(name).parts
                           for name in normalized)):
                raise StockGlbResearchError('loose original ModelBin entries missing or ambiguous')
            identity = (1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)
            loose_models = [
                ModelRef(path='game:/media/cars/'+scene['media']+'/'+entry,
                    matrix=identity,bone='',bone_id=-1,lod_flags=0,draw_groups=1,
                    material_bindings=(),part_group=0,stock=True,option_ids=(),
                    snap_to_parent=False,model_version=0,part_type_raw=2,window_hint=False)
                for entry in normalized
            ]
            scene = {**scene,
                'models': loose_models,
                'parts': [{'kind':'base','group':0,'part_type_raw':2}],
                'options': []}
        def _source_mesh_lod_masks(path):
            # 通常版ModelBinの描画可能なMeshのLODビット（__slod版を補う部品として使うかの判定用）。
            raw=z.read(names[path.casefold()])
            masks=[]
            for blob in parse_bundle(raw):
                if blob.tag!='Mesh':continue
                mesh=mesh_decode(raw,blob)
                if mesh.index_count:masks.append(mesh.lod)
            return masks
        if source_part_overlay_only:
            # 部品の選択肢の重ね合わせ：その選択肢で加わる部品だけを、Carbinの配置のまま描く。
            (overlay_family,overlay_option),=source_part_selection.items()
            overlay_added,overlay_replaced=select_part_option_overlay(
                scene,_source_entry,family=overlay_family,option_id=overlay_option,
                modelbin_lod_masks=_source_mesh_lod_masks)
            original_static_by_identity={original_static_instance_identity(instance): instance
                                         for instance,_ in overlay_added}
            part_option_overlay={'schema':'lo4fh6.part-option-overlay.v1','family':overlay_family,
                                 'option_id':overlay_option,'added_instances':len(overlay_added),
                                 'replaced_instance_identities':overlay_replaced}
        else:
            original_static_by_identity=(
                {original_static_instance_identity(instance): instance
                 for instance,_ in select_static_stock_instances(scene,_source_entry,selected_part_ids=source_part_selection,
                    allow_source_slod=source_loose_entries is not None,
                    modelbin_lod_masks=_source_mesh_lod_masks if source_loose_entries is None else None)}
                if source_original_static_selection else {}
            )
        processed_static_keys=set()
        # ブレーキのディスク・キャリパーと足回りのコントロールアームは、ゲームの表示と同じくホイールの位置から置く
        # （presentation_brake_matrices・presentation_control_arm_matrices）。
        skeleton_cache={}
        def _skeleton_bones(path):
            if path not in skeleton_cache:
                raw_bytes=z.read(names[path.casefold()]) if path.casefold() in names else None
                skels=[b for b in parse_bundle(raw_bytes) if b.tag=='Skel'] if raw_bytes else []
                skeleton_cache[path]=read_bones(raw_bytes,skels[0]) if len(skels)==1 else []
            return skeleton_cache[path]
        presentation_records=[(key,instance,_source_entry(instance.path,scene['media']))
                              for key,instance in original_static_by_identity.items()]
        def _presentation_part_type(raw_type):
            return original_part_type_from_carbin(raw_type)[0] if type(raw_type) is int else ''
        brake_matrices=(
            presentation_brake_matrices(presentation_records,_presentation_part_type,_skeleton_bones)
            if source_original_static_selection else {}
        )
        control_arm_matrices=(
            presentation_control_arm_matrices(presentation_records,_presentation_part_type,_skeleton_bones)
            if source_original_static_selection else {}
        )
        if shader_index is not None and shader_index.car_id!=scene['ordinal']:
            raise StockGlbResearchError('Shader reference belongs to a different original car source')
        mask=read_source_masks(z)
        source_option_keys={(f'original_part_{o["part_type_raw"]}',o['id']) for o in scene['options']}
        if len(source_option_keys)!=len(scene['options']):
            raise StockGlbResearchError('duplicate source Stock/Upgrade part option')
        part_options=[{'part_type':original_part_type_from_carbin(o['part_type_raw'])[0] if source_original_static_selection else f'original_part_{o["part_type_raw"]}',
            'part_type_value':original_part_type_from_carbin(o['part_type_raw'])[1] if source_original_static_selection else o['part_type_raw'],
            'id':o['id'],'level':o['level'],
            'is_stock':o['stock'],'car_body_id':o['body_id'],'parent_is_stock':o['parent_stock']}
            for o in scene['options']]
        cache={}
        # 同じ ModelBin を使う置き場所ごとに、全部の Mesh の見出しを読み直していた（4212 で 926 個を約 4 回ずつ）。
        # 見出し（Mesh）は書き換えられない値なので、ModelBin と位置ごとに覚えて使い回す。読む順は同じ（2026-11-20）。
        mesh_memo={}
        def _decoded_mesh(path,raw,blob):
            key=(path,blob.offset)
            mesh=mesh_memo.get(key)
            if mesh is None:mesh=mesh_memo[key]=mesh_decode(raw,blob)
            return mesh
        for ordinal,instance in enumerate(scene['models']):
            c['declared_source_instances']+=1
            p=_source_entry(instance.path,scene['media'])
            if source_original_static_selection:
                # 参照製品は同一InstanceKeyの複数原本記録からPartOptionIdsを統合する場合がある。
                # 統合後の不変ModelRefは別Pythonオブジェクトのためid(instance)を選択キーに使わない。
                # 描画するのは最初の原本記録だけだが、Option情報は統合済みの完全な値を使用する。
                key=original_static_instance_identity(instance)
                if key not in original_static_by_identity or key in processed_static_keys:
                    c['lo4_static_instances_not_selected']+=1;continue
                processed_static_keys.add(key)
                instance=original_static_by_identity[key]
            else:
                if not instance.stock:
                    c['non_stock_source_instances_not_selected']+=1;continue
                if instance.lod_flags and not instance.lod_flags&lod:
                    c['stock_instances_other_lod']+=1;continue
            # 未選択の任意Variant ModelBinがなくてもStock Previewを拒否しない。
            # 選択された原本バイトだけは必須とし、参照製品のRecordUnresolvedに対応する。
            # 欠落の事実を隠さず報告する。
            if p not in names:
                raise StockGlbResearchError('selected original Carbin ModelBin referenced file missing')
            for option_id in instance.option_ids:
                if (f'original_part_{instance.part_type_raw}',option_id) not in source_option_keys:
                    raise StockGlbResearchError('source Stock instance has unknown part option')
            c['stock_instances']+=1
            if p not in cache:
                raw=z.read(names[p]);blobs=parse_bundle(raw)
                skels=[b for b in blobs if b.tag=='Skel']
                if len(skels)!=1:raise StockGlbResearchError('Stock ModelBin has ambiguous original skeleton')
                source_bones=read_bones(raw,skels[0])
                bones=world_bone_matrices(source_bones)
                mats=original_materials(raw,blobs)
                original_static_offsets = (
                    {m.blob.offset for m in select_static_model_meshes(
                        [_decoded_mesh(p,raw,b) for b in blobs if b.tag=='Mesh']
                    )} if source_original_static_selection else None
                )
                cache[p]=(raw,blobs,bones,mats,source_bones,original_static_offsets)
            raw,blobs,bones,mats,source_bones,original_static_offsets=cache[p]
            attachment = (
                original_modelbin_attachment_matrix(source_bones,bones,
                    instance.bone,instance.bone_id)
                if source_original_static_selection else None
            )
            instance_matrix=np.array(instance.matrix,dtype=np.float64).reshape((4,4))
            if source_original_static_selection and key in brake_matrices:
                instance_matrix=brake_matrices[key]
                c['lo4_static_brake_presentation_transform']+=1
            elif source_original_static_selection and key in control_arm_matrices:
                instance_matrix=control_arm_matrices[key]
                c['lo4_static_control_arm_presentation_transform']+=1
            if source_original_static_selection:
                if attachment is None:
                    c['lo4_static_modelbin_attachment_no_match_kept_carbin']+=1
                else:
                    # 参照製品: instance.Transform * FindBoneWorld(ModelBin)
                    instance_matrix=instance_matrix@attachment
                    c['lo4_static_modelbin_attachment_bound']+=1
                    if not np.allclose(attachment,np.eye(4),atol=1e-7,rtol=0.):
                        c['lo4_static_modelbin_attachment_nonidentity']+=1
            # 参照製品が選択した原本Meshは、生成GLBへ1対1で収録する。
            # 欠落・全縮退を暗黙に成功扱いせず、車種共通で安全停止する。
            if source_original_static_selection:
                c['lo4_static_source_selected_mesh_records']+=len(original_static_offsets)
                c['lo4_static_expected_source_meshes']+=len(original_static_offsets)
            represented=0
            skipped_this_instance=0
            for b in blobs:
                if b.tag!='Mesh':continue
                m=_decoded_mesh(p,raw,b)
                if not m.index_count:continue
                if source_original_static_selection:
                    if b.offset not in original_static_offsets:continue
                elif not(m.lod&lod):continue
                decoded=extract_raw_geometry(raw,m,blobs)
                shadow_only=original_shadow_only(m,decoded)
                if shadow_only:
                    if not source_original_static_selection:
                        c['original_verified_shadow_only_meshes_not_rendered']+=1;continue
                    # MeshにNORMAL Semanticがない場合、参照製品 ModelImporterはNormal=0を返す。
                    # 参照製品 TransformNormalsはUnitYに置換し、ClassifyRoleは原本ShadowをHiddenとする。
                    # Static PreviewのMesh網羅性のため幾何は保持するが、欠落Normalを可視面の証拠にしない。
                    decoded={**decoded,'missing_source_normal':False,
                        'arrays':{**decoded['arrays'],('NORMAL',0):
                            np.zeros_like(decoded['arrays'][('POSITION',0)])}}
                    c['lo4_static_hidden_shadow_meshes']+=1
                if m.bone<0 or m.bone>=len(bones):
                    raise StockGlbResearchError('original Mesh has unresolved rigid bone')
                material=None if shadow_only else resolve_mesh_material(m,mats)
                if not shadow_only and material is None:
                    raise StockGlbResearchError('visible original surface has no source MatI identity')
                if not shadow_only and not material.source_blob_bytes:
                    # 原本MatIが存在しID・名前が解決されても、Shaderペイロードが空の場合がある。
                    # 参照製品はそのMeshも描画するが、PBR・Texture・Materialを捏造せず、欠落バイトを明記する。
                    c['original_visible_matI_empty_payload_meshes']+=1
                # Hidden Shadowには原本NORMALがなく、表示対象にもならない。
                # 参照製品はメタデータとTriangleを出力するがStatic表示用には変形しない。
                # Skin／Morphの宣言はすべて記録し、実行時Pose検証済みとはみなさない。
                if shadow_only:
                    skin=morph=None
                    c['lo4_static_hidden_shadow_skin_source_unapplied']+=int(m.skin_count>0)
                    c['lo4_static_hidden_shadow_morph_source_unapplied']+=int(m.morph_count>0)
                    if source_original_static_selection:
                        # Hidden Shadowも参照製品に選択された元Meshである。
                        # Static出力には実行時Skin／Morphが不要でも、原本の宣言を欠落・検証済みと誤認しない。
                        c['lo4_static_skin_declared_payload_not_decoded']+=int(m.skin_count>0)
                        c['lo4_static_morph_declared_payload_not_decoded']+=int(m.morph_count>0)
                elif (source_original_static_selection and not preserve_original_deformation
                      and verified_deformation_inputs is None):
                    # 参照製品 AppendMeshesは元RawPositions/NormalとModelBin剛体行列
                    # のみを静止GLBに使う。実行時Skin/Morphを推測・適用しない。
                    # 原本宣言値はMetaに保存し、未解析を成功済みと偽らない。
                    skin=morph=None
                    c['lo4_static_skin_declared_payload_not_decoded']+=int(m.skin_count>0)
                    c['lo4_static_morph_declared_payload_not_decoded']+=int(m.morph_count>0)
                else:
                    skin=decode_original_skin(raw,m,blobs,bone_count=len(bones))
                    morph=decode_original_morph(raw,m,blobs)
                if skin and skin.vertex_count!=decoded['vertices']:
                    raise StockGlbResearchError('Skin source vertex count differs from geometry')
                if morph and morph.vertex_count!=decoded['vertices']:
                    raise StockGlbResearchError('Morph source vertex count differs from geometry')
                uv=source_uv_affine(decoded,m)
                hidden_reason = (
                    source_static_hidden_surface_reason(b.name or '',
                        material.name if material is not None else '',p)
                    if source_original_static_selection and not shadow_only else None
                )
                if hidden_reason is not None:
                    c['lo4_static_hidden_'+hidden_reason+'_meshes']+=1
                role='hidden' if shadow_only or hidden_reason else 'trim'
                if role!='hidden' and material is not None and material.name.casefold().startswith('carpaint'):
                    if not source_original_static_selection and (3 not in uv or not(mask.available_sides&0x3f)):
                        raise StockGlbResearchError('known carPaint requires original UV3+11-side mask; not silently downgraded')
                    role='paint'
                c['original_paint_matI_uv3_meshes']+=role=='paint'
                original_shader=shader_index.bind(p,raw,material.name) if shader_index is not None and material is not None else None
                if shader_index is not None:
                    c['original_shader_reference_resolved_meshes']+=original_shader is not None
                    c['original_shader_reference_unresolved_meshes']+=original_shader is None and not shadow_only
                    if shader_role_trial and role!='hidden':
                        previous_role=role
                        role=research_role_from_verified_family(role,original_shader,
                            has_uv3=3 in uv,source_mask_sides=mask.available_sides)
                        if role!=previous_role:
                            c['source_shader_role_trial_'+role+'_meshes']+=1
                # 参照製品静止GLB互換は製品用の原本Shader分類と別契約。
                # 実原本Maskの存在だけでRoleや許可11面を縮小しない。
                if source_original_static_selection:
                    # 参照製品 ModelImporterのMatI未解決時の既定名はUnknown。
                    # Shadowは通常非表示だが互換Meshメタデータも一致させる。
                    native_material_name = material.name if material is not None else 'Unknown'
                    original_part_name = original_part_type_from_carbin(instance.part_type_raw)[0]
                    native_binding = (original_material_binding_hash(
                        native_material_name, instance.material_bindings) if material is not None else 0)
                    static_role = static_mesh_role(
                        p, b.name or '', native_material_name,
                        material_binding_hash=native_binding, has_uv3=3 in uv,
                        window_hint=instance.window_hint,
                        parent_materialbin=material.parent_materialbin if material is not None else '',
                        part_type=original_part_name)
                    role = 'hidden' if shadow_only or hidden_reason else static_role
                    original_static_sides = static_livery_sides(role, b.name or '', original_part_name)
                else:
                    original_static_sides = None
                # CarPaint以外の原本Shaderをゲーム準拠のGlass／PBRと断定しない。
                c['unverified_native_shader_visible_meshes']+=role not in ('paint','hidden')
                mesh_key=f'{p} / instance{ordinal} / Mesh{b.offset}'
                deform_report={}
                if skin is not None or morph is not None:
                    deformation_requirements.append({
                        'mesh_key':mesh_key,
                        'original_modelbin_sha256':sha256(raw).hexdigest(),
                        'original_mesh_offset':b.offset,
                        'source_skin':skin is not None,
                        'source_morph':morph is not None,
                        'original_skin_sha256':skin.buffer_sha256 if skin else None,
                        'original_morph_sha256':morph.buffer_sha256 if morph else None,
                        'source_bone_count':len(bones),
                    })
                if verified_deformation_inputs is not None:
                    runtime=verified_deformation_inputs.get(mesh_key)
                    if (skin is not None or morph is not None) and runtime is None:
                        raise StockGlbResearchError('原本Skin/MorphがあるMeshに実係数/Bind Pose証拠がありません: '+mesh_key)
                    if runtime is not None:
                        if (not isinstance(runtime,dict) or runtime.get('original_modelbin_sha256')!=sha256(raw).hexdigest()
                                or runtime.get('original_mesh_offset')!=b.offset):
                            raise StockGlbResearchError('原本Mesh/ModelBin署名と実変形証拠の対応が不一致')
                        matched_source=validate_original_deformation_input(
                            raw,b.offset,source_bones,skin,morph,runtime)
                        xyz,norm,deform_report=apply_verified_source_deformation(
                            decoded['arrays'][('POSITION',0)],decoded['arrays'][('NORMAL',0)],
                            skin=skin,morph=morph,source_bind_world=runtime.get('source_bind_world'),
                            source_pose_world=runtime.get('source_pose_world'),
                            original_morph_slot_weights=runtime.get('original_morph_slot_weights'),
                            original_morph_slot_semantics=runtime.get('original_morph_slot_semantics'),
                            original_morph_higher_slot_modulation=runtime.get('original_morph_higher_slot_modulation'))
                        decoded={**decoded,'arrays':{**decoded['arrays'],('POSITION',0):xyz,('NORMAL',0):norm}}
                        used_deformation_keys.add(mesh_key)
                        c['source_bind_candidate_matched_meshes']+=int(matched_source['source_bind_candidate_matches_bytes'])
                        c['source_morph_sha_matched_meshes']+=int(morph is not None)
                        c['verified_skin_runtime_meshes']+=bool(deform_report.get('skin_applied_vertices'))
                        c['verified_morph_runtime_meshes']+=bool(deform_report.get('morph_applied_vertices'))
                wheel_binding=source_wheel_or_brake_identity(instance,p,b.offset) if source_wheel_identity_trial else None
                if wheel_binding is not None and wheel_binding['part_type']=='WheelStyle':
                    wheel_source_identities.add(wheel_binding['instance_identity'])
                    if wheel_binding['original_corner'] is None:
                        unmapped_source_wheel_bones.add(wheel_binding['original_bone'])
                    else:
                        wheel_corners.add(wheel_binding['original_corner'])
                    c['source_wheelstyle_mesh_bindings']+=1
                pose=transform_source_geometry(decoded,bone_matrix=bones[m.bone],
                    instance_matrix=instance_matrix,
                    source_position_scale=m.scale)
                idx=np.asarray(decoded['indices'],dtype=np.int64).reshape((-1,3)).copy()
                if source_original_static_selection:
                    native_triangle_count=len(idx)
                    idx=clean_original_static_triangle_indices(idx)
                    c['lo4_static_source_triangles']+=native_triangle_count
                    c['lo4_static_triangles_degenerate_or_duplicate_removed']+=native_triangle_count-len(idx)
                    if not len(idx):
                        # 参照製品のCleanTriangleIndices／AppendMeshesは有効TriangleのないPrimitiveを除外する。
                        # 幾何欠損ではないため、元Meshの識別子と除外Triangle数を根拠として保持し、面を捏造しない。
                        c['lo4_static_wholly_invalid_meshes_skipped']+=1
                        c['lo4_static_expected_source_meshes']-=1
                        skipped_this_instance+=1
                        skipped_nondrawable_source_meshes.append({
                            'modelbin_entry':p,'mesh_offset':b.offset,
                            'mesh_name':b.name or '',
                            'source_triangle_count':native_triangle_count,
                            'reason':'ALL_TRIANGLES_DEGENERATE_AFTER_LO4FH6_CLEAN',
                        })
                        continue
                elif pose['winding_reversed']:
                    idx[:,[1,2]]=idx[:,[2,1]]
                if (source_original_static_selection and role in ('trim','dark','glass')
                        and len(pose['positions'])
                        and float(np.max(np.asarray(pose['positions'])[:,1])) < STATIC_PARKED_BELOW_GROUND_Y):
                    role='hidden';hidden_reason='parked_below_ground'
                    c['lo4_static_hidden_parked_below_ground_meshes']+=1
                if source_original_static_selection:
                    c['lo4_static_classified_'+role+'_meshes']+=1
                nonroot=bool(instance.snap_to_parent or instance.bone_id>1)
                extras={'lo4fh6_role':role,'lo4fh6_source_entry':(names[p].filename if source_original_static_selection else p),
                    'lo4fh6_instance_identity':('legacy:'+names[p].filename if source_loose_entries is not None else original_static_instance_identity(instance)) if source_original_static_selection else wheel_binding['instance_identity'] if wheel_binding else mesh_key,
                    'lo4fh6_source_mesh_name':b.name or '',
                    **({'lo4fh6_original_modelbin_basename':PurePosixPath(names[p].filename).stem}
                       if source_original_static_selection else {}),
                    'lo4fh6_material_name':material.name if material is not None else ('Unknown' if source_original_static_selection else 'Shadow'),
                    **({'lo4fh6_material_binding_hash':f'{original_material_binding_hash(material.name,instance.material_bindings):016X}' if material is not None else '0000000000000000'} if source_original_static_selection else {}),
                    'lo4fh6_stock_part':True,'lo4fh6_part_type':original_part_type_from_carbin(instance.part_type_raw)[0] if source_original_static_selection else wheel_binding['part_type'] if wheel_binding else f'original_part_{instance.part_type_raw}',
                    **({'lo4fh6_original_part_type_raw':instance.part_type_raw, 'lo4fh6_original_source_mesh_offset':b.offset} if wheel_binding else {}),
                    'lo4fh6_part_option_ids':[] if source_original_static_selection else list(instance.option_ids),
                    **({'lo4fh6_original_carbin_selected_option_ids':list(instance.option_ids)}
                       if source_original_static_selection else {}),
                    'lo4fh6_draw_groups':instance.draw_groups,
                    'lo4fh6_allowed_sides':(original_static_sides[0] if original_static_sides is not None else
                        research_shader_livery_permission(role, original_shader, has_uv3=3 in uv, mask_available_sides=mask.available_sides) if shader_role_trial else native_uv3_side_allowance(role,uv,mask)),
                    'lo4fh6_projection_sides':original_static_sides[1] if original_static_sides is not None else 0,
                    'lo4fh6_original_material_sha256':material.source_blob_sha256 if material is not None else '',
                    'lo4fh6_original_material_payload_unavailable':bool(
                        material is not None and not material.source_blob_bytes),
                    'lo4fh6_source_shadow_only_hidden':bool(shadow_only),
                    'lo4fh6_source_static_hidden_reason':hidden_reason or '',
                    'lo4fh6_original_hidden_shadow_skin_elements':m.skin_count if shadow_only else 0,
                    'lo4fh6_original_hidden_shadow_morph_targets':m.morph_count if shadow_only else 0,
                    'lo4fh6_source_static_instance_verified':bool(source_original_static_selection),
                    'lo4fh6_original_loose_modelbin_verified':bool(source_loose_entries is not None),
                    'lo4fh6_source_static_modelbin_attachment_bound':attachment is not None,
                    'lo4fh6_source_static_modelbin_attachment_nonidentity':(
                        attachment is not None and not np.allclose(
                            attachment,np.eye(4),atol=1e-7,rtol=0.)
                    ),
                    'lo4fh6_original_matI_id':material.id if material is not None else -1,
                    'lo4fh6_original_mask_xml_sha256':mask.xml_sha256,
                    'lo4fh6_original_bucket_bits':m.bucket,
                    'lo4fh6_original_bucket_order':m.bucket_order,
                    'lo4fh6_original_rigid_bone_id':m.bone,
                    'lo4fh6_original_mesh_lod':m.lod,
                    **({'lo4fh6_original_skin_declared':bool(m.skin_count),
                        'lo4fh6_original_morph_declared':bool(m.morph_count),
                        'lo4fh6_static_deformation_payload_not_decoded':bool(
                            source_original_static_selection and not preserve_original_deformation
                            and verified_deformation_inputs is None)}
                       if source_original_static_selection else {}),
                    'lo4fh6_skin_source_verified':skin is not None,
                    'lo4fh6_original_skin_sha256':skin.buffer_sha256 if skin else '',
                    'lo4fh6_skin_runtime_transform_applied':bool(deform_report.get('skin_applied_vertices')),
                    'lo4fh6_morph_source_verified':morph is not None,
                    'lo4fh6_original_morph_sha256':morph.buffer_sha256 if morph else '',
                    'lo4fh6_morph_runtime_transform_applied':bool(deform_report.get('morph_applied_vertices')),
                    'lo4fh6_nonroot_attachment_unverified':nonroot,
                    'lo4fh6_original_material_shader_gpu_unverified':True,
                    'lo4fh6_original_shader_source_evidence':original_shader if shader_index is not None else None,
                    'lo4fh6_shader_role_trial_unapproved':bool(shader_role_trial),
                    'lo4fh6_original_glass_livery_pixel_verified':False,
                    'lo4fh6_original_wheel_fitment_unverified':True,
                    'lo4fh6_not_game_runtime_appearance':True,
                }
                # 明示的な検証条件：このGLBは原本構造の網羅性確認専用。
                writer.append(pose['positions'],pose['normals'],idx.ravel(),uv,extras)
                if preserve_original_deformation:
                    writer.attach_original_deformation(skin,morph,decoded['vertices'])
                    c['source_skin_payload_staged_meshes']+=skin is not None
                    c['source_morph_payload_staged_meshes']+=morph is not None
                c['source_stock_visible_meshes']+=1
                c['source_stock_visible_vertices']+=len(pose['positions'])
                c['source_stock_visible_triangles']+=len(idx)
                c['original_skin_data_unapplied_meshes']+=(bool(m.skin_count) if source_original_static_selection else skin is not None) and not bool(deform_report.get('skin_applied_vertices'))
                c['original_morph_data_unapplied_meshes']+=(bool(m.morph_count) if source_original_static_selection else morph is not None) and not bool(deform_report.get('morph_applied_vertices'))
                c['original_nonroot_attachment_unverified_meshes']+=nonroot
                represented+=1
            if source_original_static_selection and represented+skipped_this_instance!=len(original_static_offsets):
                raise StockGlbResearchError(
                    'Static preview original Mesh coverage incomplete: '
                    f'{p}: selected {len(original_static_offsets)}, emitted {represented}, '
                    f'non-drawable {skipped_this_instance}')
            if not represented:
                raise StockGlbResearchError('stock instance has no renderable original surface')
    if verified_deformation_inputs is not None and used_deformation_keys!=set(verified_deformation_inputs):
        raise StockGlbResearchError('未使用の原本Skin/Morph実変形証拠があります')
    standard_four_corners=bool(
        source_wheel_identity_trial and len(wheel_source_identities)==4
        and not unmapped_source_wheel_bones
        and wheel_corners=={'front_left','front_right','rear_left','rear_right'}
    )
    if source_wheel_identity_trial:
        # 参照製品のStatic幾何はWheelの装着Topologyと独立している。
        # 3輪・6輪の元幾何を保全し、原本識別が異なる場合に4輪FEOW配置の一致を主張しない。
        c['source_wheelstyle_unique_instance_count']=len(wheel_source_identities)
        c['source_wheelstyle_unmapped_corner_bone_count']=len(unmapped_source_wheel_bones)
        c['source_wheelstyle_four_corner_fitment_eligible']=int(standard_four_corners)
        for entry in writer.meshes:
            if entry['extras'].get('lo4fh6_part_type')=='WheelStyle':
                entry['extras']['lo4fh6_feow_standard_four_corner_eligible']=standard_four_corners
    if source_original_static_selection and (
            c['stock_instances']!=len(original_static_by_identity)
            or c['source_stock_visible_meshes']!=c['lo4_static_expected_source_meshes']):
        raise StockGlbResearchError('Static preview original Stock/Mesh coverage mismatch')
    # 参照製品原著ではpartOptionsを初期化した後、選択オプションを追加しない。
    # 古い互換APIへCarbinの選択情報を偽装せず、原本は研究専用で別保持。
    glb=writer.pack([] if source_original_static_selection else part_options,
                    original_source_options=part_options if source_original_static_selection else None,
                    static_undeformed=bool(source_original_static_selection and
                        not preserve_original_deformation and verified_deformation_inputs is None),
                    part_option_overlay=part_option_overlay)
    report={'schema':'lo4fh6.firstparty-stock-geometry-glb-research.v1',
        'source_car_id':scene['ordinal'],'source_lod':lod,
        'source_mask_xml_sha256':mask.xml_sha256,
        'original_skeleton_blobs_and_matI_used':True,
        'original_matI_empty_source_payload_count':c.get('original_visible_matI_empty_payload_meshes',0),
        'source_option_reference_issues':scene.get('option_reference_issues',[]),
        'source_nondrawable_triangle_meshes':skipped_nondrawable_source_meshes,
        'wheel_topology':{
            'standard_four_corner_eligible':standard_four_corners,
            'original_unique_wheelstyle_instances':len(wheel_source_identities),
            'original_verified_standard_corners':sorted(wheel_corners),
            'source_bones_without_standard_corner':sorted(unmapped_source_wheel_bones),
            'feow_assembly_applied':False,
        },
        'counts':dict(sorted(c.items())),
        'source_deformation_requirements':deformation_requirements,
        'glb_bytes':len(glb),'glb_sha256':sha256(glb).hexdigest(),
        'GLB_COVERAGE':'LO4FH6_STATIC_PREVIEW_MESH_LOD_AND_HIDDEN_SHADOW__NOT_XBOX'
            if source_original_static_selection else 'ALL_VISIBLE_SOURCE_STOCK_GEOMETRY__STATIC_RIGID_POSE_NOT_XBOX',
        'Skin_Morph_runtime':('ORIGINAL_DECLARATIONS_PRESERVED__PAYLOAD_NOT_DECODED__NOT_APPLIED' if source_original_static_selection and not preserve_original_deformation and verified_deformation_inputs is None else 'EXPLICIT_SOURCE_POSE_AND_SLOT_WEIGHTS_APPLIED' if c.get('verified_skin_runtime_meshes',0) or c.get('verified_morph_runtime_meshes',0) else 'NOT_APPLIED__ORIGINAL_SOURCE_VERIFIED'),
        'Materials_Shader_glass':'NOT_VERIFIED',
        'Original_wheel_tire_FEOW':(
            'FOUR_SOURCE_WHEELSTYLE_IDENTITIES_ONLY__MORPH_TIRE_FEOW_STAGE_NOT_APPLIED'
            if standard_four_corners else
            'NONSTANDARD_OR_INCOMPLETE_WHEEL_TOPOLOGY__FEOW_NOT_VERIFIED'
            if source_wheel_identity_trial else
            'NOT_ACCEPTED_IN_THIS_RESEARCH_GLB'
        ),
        'GPU_Windows_Xbox':'NOT_PERFORMED','release_status':'REVIEW_REQUIRED',
        'lo4_static_preview_selection':bool(source_original_static_selection),
        'source_loose_entry_mode':bool(source_loose_entries is not None),
        'source_loose_entry_count':len(source_loose_entries or []),
        'lo4_static_preview_is_xbox_match':False}
    if preserve_original_deformation:
        report['deformation_payload']='SOURCE_ACCESSORS_ONLY__NOT_RUNTIME_APPLIED'
    if shader_index is not None:
        report['original_shader_family_reference']='SOURCE_MODELBIN_SHA_AND_MATI__RESEARCH_ONLY_NOT_GPU_CLASSIFICATION'
    if shader_role_trial:
        report['original_shader_role_trial']='SOURCE_UV3_MASK_AVAILABILITY_ONLY__NOT_NATIVE_BLEND_PIXELS_GPU'
        report['glass_livery_permission']='DENY_UNTIL_SOURCE_PIXEL_EVIDENCE__NOT_PRODUCT_APPROVED'
    return glb,report


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description='研究用：原本Stock静止ジオメトリGLB（製品へは使用不可）')
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--research-static-stock-unverified',action='store_true',required=True)
    parser.add_argument('--research-original-static-preview-selection','--research-lo4fh6-static-preview-selection',dest='research_original_static_preview_selection',action='store_true',
                        help='参照製品のStock/LOD/非表示Shadow選択だけを独自実装（研究未承認）')
    parser.add_argument('--research-source-shader-role-trial',action='store_true',
                        help='原本Shader族＋UV3＋Mask存在で研究用paint/glass候補を生成（未承認）')
    parser.add_argument('--research-original-shader-reference',type=Path,
                        help='元ModelBin SHA照合済みPRIVATE Shader族索引。製品ロールには未接続')
    parser.add_argument('--research-preserve-original-deformation-data',action='store_true',
                        help='原本Skin/Morphを非描画アクセサへ保全（PRIVATE研究のみ）')
    args=parser.parse_args(argv)
    try:
        if not args.research_static_stock_unverified:
            raise StockGlbResearchError('explicit unverified research-only flag required')
        out=args.output.resolve();report=args.report.resolve()
        if out.suffix.casefold()!='.glb' or report.suffix.casefold()!='.json' or out==report or out.exists() or report.exists() or out.is_symlink() or report.is_symlink():
            raise StockGlbResearchError('new distinct GLB and JSON output paths required; overwrite prohibited')
        glb,evidence=build_research_stock_geometry_glb(args.archive,preserve_original_deformation=args.research_preserve_original_deformation_data,
            source_shader_reference=args.research_original_shader_reference.read_bytes() if args.research_original_shader_reference is not None else None,
            shader_role_trial=args.research_source_shader_role_trial,
            source_original_static_selection=args.research_original_static_preview_selection)
        out.parent.mkdir(parents=True,exist_ok=True);report.parent.mkdir(parents=True,exist_ok=True)
        with out.open('xb') as f:f.write(glb)
        with report.open('x',encoding='utf-8-sig') as f:
            json.dump(evidence,f,ensure_ascii=True,sort_keys=True,indent=2);f.write('\n')
        sys.stdout.write(json.dumps(evidence,ensure_ascii=True,sort_keys=True)+'\n')
        return 0
    except (OSError,ValueError,zipfile.BadZipFile,DecodeError) as exc:
        sys.stderr.write(('Research full-source GLB refused: '+str(exc)).encode('ascii','backslashreplace').decode('ascii')+'\n')
        return 2

if __name__=='__main__':raise SystemExit(main())
