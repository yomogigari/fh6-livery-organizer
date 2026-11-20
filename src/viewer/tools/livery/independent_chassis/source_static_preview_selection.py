"""Carbin/ModelBin to 参照製品-style static GLB preview selection, source based.

Reference implementation (behavior only, not copied):
参照製品 Program.SceneModelInstances / ExtractSceneMeshes / AppendMeshes;
参照製品 MeshBlob.LOD_LODS; original FH6 ModelBin Mesh LOD flags.

参照製品 does not use the Carbin instance's LOD flags to discard stock instances;
it chooses each ModelBin's LODS Mesh cohort when present, otherwise all meshes.
Proxy SLOD model paths are not part of the regular preview when the regular
model of the same part is selected (__slod版は通常版が無い部品に限り使う). No game data here.
All output remains RESEARCH-ONLY pending GLB/GPU/Windows acceptance.
"""
from __future__ import annotations
import functools


class SourceStaticSelectionError(ValueError):
    pass


def source_lods_cohort_incomplete(lod_masks: list[int]) -> bool:
    """通常版ModelBinのLODS（bit0）のMeshが、LOD0（bit1）の部品をそろえていないか。

    静止選択は各ModelBinでLODSのMeshがあればそれだけを使う。LODSのMeshを持ちながら、LOD0の
    Meshの一部にLODSビットが無い場合、その部分のLODS版は__slod版にある（ゲームはLODS段階で
    通常版のLODSのMeshと__slod版の両方を描く）。LODSのMeshが無い通常版は全Meshを使うため対象外。
    """
    masks=[int(m) for m in lod_masks]
    return any(m&1 for m in masks) and any((m&2) and not (m&1) for m in masks)


def select_static_stock_instances(scene: dict, source_entry_resolver, *, selected_part_ids: dict[str, int] | None = None, allow_source_slod: bool = False, modelbin_lod_masks=None, include_far_lod_only: bool = False) -> list[tuple[object, str]]:
    """Keep Stock Carbin models, without assuming one car/part-specific LOD.

    The caller supplies the existing exact original source path resolver.
    The native Carbin parser preserves *all* options and shared upgrade
    models. Select 参照製品's default upgrade (IsStock, Level, Id ordering) per
    part group, then include that option's inline and shared instances.
    This also includes a shared model with zero UpgradeIds, which 参照製品
    includes regardless of the Stock bit. Repeated ModelBin paths with
    different Carbin instances remain distinct.

    遠くからの表示用だけの部品（Carbin の lod_flags が 0 でなく、LODS＝bit0 と LOD0＝bit1 の
    どちらも含まない部品）は選ばない。ゲームは段階ごとに lod_flags & 段階 で部品を描くため、
    LODS・LOD0 で描く静止プレビューにそれらを重ねると、同じ部位が二重に描かれる
    （例：低詳細の室内 InteriorLOD の interior_a は 1111100 で、詳細な室内の部品は 0000011。
    2026-11-17 の全 691 車種の走査で 677 車種、室内 675 車種）。include_far_lod_only=True は
    参照製品と部品数を比べる研究用で、標準の変換は使わない。
    """
    if not isinstance(scene,dict) or not isinstance(scene.get('models'),list):
        raise SourceStaticSelectionError('original Carbin model list is invalid')
    if selected_part_ids is not None and not isinstance(selected_part_ids, dict):
        raise SourceStaticSelectionError('explicit original Carbin selections must be a dictionary')
    selections = {}
    for key, value in (selected_part_ids or {}).items():
        if (not isinstance(key, str) or not key.strip()
                or type(value) is not int or value < 0
                or key.casefold() in selections):
            raise SourceStaticSelectionError('invalid explicit original Carbin part selection')
        selections[key.casefold()] = value
    matched_selections = set()
    has_parts='parts' in scene or 'options' in scene
    if selections and not has_parts:
        raise SourceStaticSelectionError('explicit part selection requires original Carbin parts/options')
    kinds={}
    default_upgrade={}
    if has_parts:
        if not isinstance(scene.get('parts'),list) or not isinstance(scene.get('options'),list):
            raise SourceStaticSelectionError('original Carbin parts/options are missing')
        for part in scene['parts']:
            if not isinstance(part,dict) or type(part.get('group')) is not int or part.get('kind') not in ('base','upgrade'):
                raise SourceStaticSelectionError('invalid Carbin part group')
            group=part['group']
            if group in kinds:
                raise SourceStaticSelectionError('duplicate Carbin part group')
            kinds[group]=part['kind']
        options={}
        for option in scene['options']:
            if (not isinstance(option,dict) or type(option.get('group')) is not int
                    or kinds.get(option['group'])!='upgrade'
                    or type(option.get('id')) is not int or type(option.get('stock')) is not bool
                    or type(option.get('level')) is not int):
                raise SourceStaticSelectionError('invalid original Carbin upgrade option')
            options.setdefault(option['group'],[]).append(option)
        for group, rows in options.items():
            ids=[item['id'] for item in rows]
            if len(ids)!=len(set(ids)):
                raise SourceStaticSelectionError('duplicate upgrade option id for part group')
            chosen=min(rows,key=lambda x:(not x['stock'],x['level'],x['id']))
            if selections:
                definition = next(part for part in scene['parts'] if part['group'] == group)
                raw_type = definition.get('part_type_raw')
                if type(raw_type) is not int:
                    raise SourceStaticSelectionError('explicit part selection requires original Carbin part enum')
                family = original_part_type_from_carbin(raw_type)[0].casefold()
                if family in selections:
                    wanted = selections[family]
                    matches = [row for row in rows if row['id'] == wanted]
                    if len(matches) != 1:
                        raise SourceStaticSelectionError('specified original Carbin part option is unavailable')
                    chosen = matches[0]
                    matched_selections.add(family)
            default_upgrade[group]=chosen['id']
    if matched_selections != set(selections):
        raise SourceStaticSelectionError('specified original Carbin part family is unavailable')
    selected=[]
    for instance in scene['models']:
        if not isinstance(getattr(instance,'stock',None),bool):
            raise SourceStaticSelectionError('Stock part declaration missing from Carbin')
        if has_parts:
            group=getattr(instance,'part_group',None)
            if type(group) is not int or group not in kinds:
                raise SourceStaticSelectionError('original ModelBin references unknown Carbin group')
            part_kind=kinds[group]
            if part_kind=='base':
                if not instance.stock or getattr(instance,'option_ids',()):
                    raise SourceStaticSelectionError('original base part has inconsistent Stock metadata')
            else:
                if group not in default_upgrade:
                    continue
                allowed=getattr(instance,'option_ids',None)
                if not isinstance(allowed,tuple) or any(type(i) is not int for i in allowed):
                    raise SourceStaticSelectionError('original upgrade ModelBin has invalid option references')
                if allowed and default_upgrade[group] not in allowed:
                    continue
        elif not instance.stock:
            # Backward-compatible synthetic fixtures with only model records.
            # Actual FH6 Carbin parse always provides parts and options.
            continue
        flags=int(getattr(instance,'lod_flags',0) or 0)
        if not include_far_lod_only and flags and not flags & 0b11:
            continue
        path=source_entry_resolver(instance.path,scene['media'])
        if not isinstance(path,str) or not path.casefold().endswith('.modelbin'):
            raise SourceStaticSelectionError('invalid original ModelBin entry')
        selected.append((instance,path))
    if not allow_source_slod:
        # __slod版は、同じ部品の通常版（__slodを除いた同じパス）が選択済みなら除外する（参照製品と同じ）。
        # 通常版が無い部品（例：FER_488Pista_19の外側のドア doorLF_a__SLOD、他車のグリル・
        # エンブレム・ハニカム等。2026-11-17の全691車種の走査で221車種）は、__slod版が唯一の
        # 原本であり、除外すると部品ごと描画されない。参照ツール（参照のみ）は
        # LODS（LOD bit0）を要求して__slod版を読み込む。通常版が無い場合に限り__slod版を使う。
        #
        # 例外：ゲームは段階ごとに「Carbinの lod_flags & 段階」かつ「Mesh.lod & 段階」で描く
        # （参照ツール carbin_importer.py の requested_level_of_detail、参照のみ）。
        # 通常版もLODS段階に描画される指定（lod_flags bit0）で__slod版とLODの指定が異なり、かつ
        # 通常版のLODSのMeshが部品をそろえていない（source_lods_cohort_incomplete）場合、__slod版は
        # 通常版を補う部品として併せて使う（FER_488Pista_19 の body_a は127でLODSのMeshが給油口だけ、
        # 外板のLODS版は body_a__SLOD（1）。除外するとドア後方の側面が欠けていた）。
        # LODの指定が同じ組（ホイールの127と127等）や、通常版のLODSのMeshがそろっている組は、
        # 同じ部品の別版として従来どおり除外する。Mesh情報が無い呼出し（modelbin_lod_masks=None）も従来どおり。
        flags={}
        original_path={}
        for instance,path in selected:
            key=path.casefold()
            flags[key]=flags.get(key,0)|int(getattr(instance,'lod_flags',0) or 0)
            original_path.setdefault(key,path)
        def keep_slod(path):
            key=path.casefold()
            partner=key.replace('__slod','')
            if partner not in flags:
                return True
            if modelbin_lod_masks is None or not flags[partner]&1 or flags[partner]==flags[key]:
                return False
            return source_lods_cohort_incomplete(modelbin_lod_masks(original_path[partner]))
        selected=[(instance,path) for instance,path in selected
                  if '__slod' not in path.casefold() or keep_slod(path)]
    if not selected:
        raise SourceStaticSelectionError('original Carbin contains no drawable Stock instances')
    if not has_parts:
        # Minimal synthetic fixtures without the original Carbin part and
        # authored transform cannot prove 参照製品 identity; do not invent one.
        return selected
    # 参照製品 SceneModelInstances.Add indexes by InstanceKey and only creates
    # a new instance for an unseen (Path, Bone, BoneId, PartType, float32
    # authored matrix) tuple. Keep the *first* source record, as 参照製品 does;
    # two copies of one true instance do not require duplicate GLB meshes.
    # A shared ModelBin with a different Bone or transform remains separate.
    from dataclasses import replace
    unique={}
    for instance,path in selected:
        identity=original_static_instance_identity(instance)
        if identity not in unique:
            unique[identity]=(instance,path)
            continue
        previous,previous_path=unique[identity]
        if previous_path!=path:
            raise SourceStaticSelectionError('same source instance identity has conflicting ModelBin')
        # 参照製品 SceneModelInstances.Add does not simply drop duplicate
        # instances: it unions PartOptionIds, and preserves StockPart when
        # either input belongs to the selected Stock cohort. Keeping only
        # the first ModelRef silently loses shared upgrade availability.
        first=getattr(previous,'option_ids',None)
        second=getattr(instance,'option_ids',None)
        if not isinstance(first,tuple) or not isinstance(second,tuple):
            raise SourceStaticSelectionError('duplicate source instance has invalid option ids')
        combined=tuple(sorted(set(first)|set(second)))
        if any(type(option_id) is not int for option_id in combined):
            raise SourceStaticSelectionError('duplicate source instance has invalid option id type')
        merged_stock=bool(previous.stock or instance.stock)
        if combined!=first or merged_stock!=previous.stock:
            previous=replace(previous,option_ids=combined,stock=merged_stock)
        unique[identity]=(previous,previous_path)
    return list(unique.values())


def select_static_model_meshes(meshes: list) -> list:
    """参照製品 ModelImporter LOD_LODS: bit0 wins, otherwise use all meshes.

    Meshes are the parsed original ModelBin objects in source directory order.
    Do not add missing normals or choose LOD1/LOD2 by name. Meshes with no
    index data cannot become drawable geometry and are explicitly omitted.
    """
    if not isinstance(meshes,list):
        raise SourceStaticSelectionError('original ModelBin mesh list required')
    drawable=[]
    for m in meshes:
        if type(getattr(m,'lod',None)) is not int or type(getattr(m,'index_count',None)) is not int:
            raise SourceStaticSelectionError('source Mesh LOD or indices absent')
        if m.lod<0 or m.lod>0xffff or m.index_count<0:
            raise SourceStaticSelectionError('invalid original Mesh LOD/index count')
        if m.index_count:
            drawable.append(m)
    primary=[m for m in drawable if m.lod & 1]
    return primary if primary else drawable

# The serialized FH6 Horizon v7 Carbin stores pre-Ballast V1 part codes.
# 参照製品 CCarPartsHelper.FromV1 increases codes >=42 by one.
# Numeric keys and public part names are format identifiers, not car-specific
# rendering rules. Never guess a missing/new enum value.
_ORIGINAL_PART_TYPES=(
    'Engine','Drivetrain','CarBody','Motor','Brakes','SpringDamper',
    'AntiSwayFront','AntiSwayRear','TireCompound','RearWing','RimSizeFront',
    'RimSizeRear','Camshaft','Valves','Displacement','PistonsCompression',
    'FuelSystem','Ignition','Exhaust','Intake','Flywheel','Manifold',
    'RestrictorPlate','OilCooling','SingleTurbo','TwinTurbo','QuadTurbo',
    'SuperchargerCSC','SuperchargerDSC','Intercooler','Clutch',
    'Transmission','Driveline','Differential','FrontBumper','RearBumper',
    'Hood','SideSkirts','TireWidthFront','TireWidthRear',
    'WeightReduction','ChassisStiffness','Ballast','MotorParts',
    'WheelStyle','Aspiration',
)


def original_part_type_from_carbin(raw_part_type: int) -> tuple[str,int]:
    """Resolve original Carbin V1 part enum to the 参照製品 GLB contract."""
    if type(raw_part_type) is not int or not 0 <= raw_part_type <= 44:
        raise SourceStaticSelectionError('unknown Carbin V1 part enum')
    current=raw_part_type+(1 if raw_part_type>=42 else 0)
    return _ORIGINAL_PART_TYPES[current],current


def original_static_instance_identity(instance: object) -> str:
    """Reconstruct 参照製品 InstanceKey from original path, Bone and raw matrix.

    The Source is Carbin, not per-vehicle cosmetic corrections or Mesh name.
    Same ModelBin used by two wheels must remain two distinct identities.
    """
    import math
    import struct
    name=instance.path
    bone=instance.bone
    bone_id=instance.bone_id
    matrix=instance.matrix
    if (not isinstance(name,str) or not name or not isinstance(bone,str)
            or type(bone_id) is not int or not isinstance(matrix,tuple)
            or len(matrix)!=16):
        raise SourceStaticSelectionError('invalid native Carbin static instance identity')
    _,part=original_part_type_from_carbin(instance.part_type_raw)
    words=[]
    for component in matrix:
        if not isinstance(component,(int,float)) or not math.isfinite(component):
            raise SourceStaticSelectionError('nonfinite Carbin instance transform')
        words.append(f'{struct.unpack("<I",struct.pack("<f",component))[0]:08X}')
    return '|'.join((name.replace('\\','/').lower(),bone.lower(),str(bone_id),
                     str(part),','.join(words)))



def source_static_hidden_surface_reason(source_mesh_name: str, material_name: str,
                                        source_entry: str) -> str | None:
    """Static 参照製品 source geometry which is not a visible body surface.

    Source-backed rules rather than Car ID or cosmetic guesses:
    - 参照製品 Program.IsInteriorWindowShell: glass*Int source mesh names are hidden
      even if the original Shader declares car_window or car_livery.
    - Source Wheel/blur* meshes with blur_* MatI are motion-blur proxies,
      not physically visible in a parked/static car preview. The accepted
      PRIVATE static GLB excludes their visibility. Both fields must match.
    Shadow-only geometry is handled separately by original Bucket/MatI.
    """
    if not all(isinstance(s,str) for s in (source_mesh_name,material_name,source_entry)):
        raise SourceStaticSelectionError('native static source material/mesh identity missing')
    mesh=source_mesh_name.split('|',1)[0].casefold()
    mat=material_name.casefold()
    path=source_entry.replace('\\','/').casefold()
    if mesh.startswith('glass') and 'int' in mesh:
        return 'interior_window_shell'
    if '/wheels/' in path and mesh.startswith('blur') and mat.startswith('blur_'):
        return 'stationary_wheel_blur_proxy'
    return None


def clean_original_static_triangle_indices(indices):
    """参照製品 CleanTriangleIndices: remove degenerate/repeated faces; reverse winding.

    Use only original ModelBin indexed triangles. Keep first source triangle
    for each unordered vertex triple and preserve declaration order, as 参照製品
    HashSet<(sorted A,B,C)> does. The source importer applies X handedness
    reflection to POSITION/NORMAL, so its GLB index order is (A,C,B).
    """
    import numpy as np
    tri=np.asarray(indices)
    if (tri.ndim!=2 or tri.shape[1]!=3 or tri.dtype.kind not in 'iu'
            or np.any(tri<0) or not np.isfinite(tri).all()):
        raise SourceStaticSelectionError('original static triangle indices invalid')
    if len(tri)==0:
        return np.empty((0,3),dtype=np.int64)
    valid=(tri[:,0]!=tri[:,1])&(tri[:,0]!=tri[:,2])&(tri[:,1]!=tri[:,2])
    source=np.asarray(tri[valid],dtype=np.int64)
    if not len(source):
        return source
    # np.unique returns sorted keys, but the *source order* is required.
    ordered=np.sort(source,axis=1)
    if int(ordered[:,2].max())<(1<<21):
        # 並べた 3 つの番号を 1 つの 64 ビットの整数に詰める（番号が 2^21 未満なら 1 対 1）。行ごとの
        # np.unique（axis=0）より約 4 倍速く、最初に現れた位置は同じ（どちらも安定な並べ替え。2026-11-20）。
        keys=(ordered[:,0]<<42)|(ordered[:,1]<<21)|ordered[:,2]
        _,first=np.unique(keys,return_index=True)
    else:
        _,first=np.unique(ordered,axis=0,return_index=True)
    source=source[np.sort(first)]
    result=source[:,[0,2,1]]
    return result


def _binding_token(raw: str) -> str:
    normalized=raw.replace('\\','/').rsplit('/',1)[-1].split('|',1)[0]
    if normalized.casefold().endswith('.materialbin'):
        normalized=normalized[:-12]
    return normalized.strip().casefold()


@functools.lru_cache(maxsize=256)
def _original_binding_table(original_model_bindings: tuple) -> dict:
    """結び付けの組（名前・番号）から、正規化した名前→番号の表（最初の名前を採る）。

    1 台の部品ごと（約 1600 回）に同じ組の表を作り直していた。同じ組（同じタプル）の表は覚えて使い回す
    （表は読むだけ。2026-11-20）。形の違う組は今までどおり止める（止めた結果は覚えない）。
    """
    bindings={}
    for pair in original_model_bindings:
        if (not isinstance(pair,tuple) or len(pair)!=2
                or not isinstance(pair[0],str)
                or type(pair[1]) is not int or not 0<=pair[1]<=0xffffffffffffffff):
            raise SourceStaticSelectionError('invalid original Carbin MaterialIndexes')
        name=_binding_token(pair[0])
        if name and name not in bindings:
            bindings[name]=pair[1]
    return bindings


def original_material_binding_hash(material_name: str,
                                        original_model_bindings: tuple[tuple[str,int], ...]) -> int:
    """Source Carbin material override → 参照製品 GLB binding hash.

    The first original binding per normalized material token wins. 参照製品 uses
    exact token lookup first, then the first case-insensitive substring
    match when both tokens have at least six characters. Source material
    override hashes are unsigned 64-bit; missing binding is exactly zero.
    This preserves original livery panel and window surface classification.
    """
    if not isinstance(material_name,str) or not isinstance(original_model_bindings,tuple):
        raise SourceStaticSelectionError('original Carbin material bindings are invalid')
    try:
        bindings=_original_binding_table(original_model_bindings)
    except TypeError:
        # 組の中にハッシュできない値がある（形が違う）。覚えずに今までどおり確かめて止める。
        bindings=_original_binding_table.__wrapped__(original_model_bindings)
    candidate=_binding_token(material_name)
    if not candidate:
        return 0
    if candidate in bindings:
        return bindings[candidate]
    for name, value in bindings.items():
        if len(name)>=6 and len(candidate)>=6 and (
            candidate in name or name in candidate
        ):
            return value
    return 0


def select_part_option_overlay(scene: dict, source_entry_resolver, *, family: str, option_id: int,
                               allow_source_slod: bool = False, modelbin_lod_masks=None) -> tuple[list, list[str]]:
    """部品の選択肢を 1 つ選んだときに「加わる部品」と「置き換えられる純正の部品の識別子」を返す。

    純正の選択（select_static_stock_instances の既定）と、family に option_id を指定した選択を比べる。
    加わる部品は、指定した選択にあって純正の選択に無い部品（配置・骨・部品の種類は Carbin のまま）。
    置き換えられる部品は、純正の選択にあって指定した選択に無い部品の識別子
    （original_static_instance_identity）。両方に含まれる共有の部品は、どちらにも入れない。
    """
    if not isinstance(family, str) or not family or type(option_id) is not int:
        raise SourceStaticSelectionError('invalid original Carbin part option for an overlay')
    stock = select_static_stock_instances(scene, source_entry_resolver, allow_source_slod=allow_source_slod,
                                          modelbin_lod_masks=modelbin_lod_masks)
    chosen = select_static_stock_instances(scene, source_entry_resolver, selected_part_ids={family: option_id},
                                           allow_source_slod=allow_source_slod,
                                           modelbin_lod_masks=modelbin_lod_masks)
    stock_ids = {original_static_instance_identity(instance) for instance, _ in stock}
    chosen_ids = {original_static_instance_identity(instance) for instance, _ in chosen}
    added = [(instance, path) for instance, path in chosen
             if original_static_instance_identity(instance) not in stock_ids]
    return added, sorted(stock_ids - chosen_ids)
