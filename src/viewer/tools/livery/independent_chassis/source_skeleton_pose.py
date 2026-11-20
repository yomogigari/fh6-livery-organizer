"""First-party source skeleton and explicit rigid pose stage.

Known ModelBin Skeleton v1.0+; no approximations of Carbin part selection or
MaterialBin interpretation. Geometry appearance tests remain mandatory.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .modelbin_geometry_decoder import Read, Blob, DecodeError, data

@dataclass(frozen=True)
class Bone:
    name:str
    parent:int
    first_child:int
    next_bone:int
    local:np.ndarray


def read_bones(raw: bytes,blob: Blob):
    if blob.tag!='Skel' or blob.v[0]!=1:
        raise DecodeError('unsupported source Skeleton format')
    r=Read(data(raw,blob))
    count=r.value('H')
    if not 1<=count<=32767:
        raise DecodeError('unsafe bone count')
    bones=[]
    for _ in range(count):
        name=r.text()
        parent,first,next_bone=r.value('hhh')
        matrix=np.asarray(r.value('f'*16),dtype=np.float64).reshape(4,4)
        if not np.isfinite(matrix).all() or not name:
            raise DecodeError('invalid bone transform/name')
        bones.append(Bone(name,parent,first,next_bone,matrix))
    if r.pos<len(r.data):
        # FH6 source contains attributes; preserve information, don't assume undocumented sidecar values.
        if len(r.data)-r.pos<4:
            raise DecodeError('incomplete source bone sidecar')
        length=r.value('I')
        if length>len(r.data)-r.pos:raise DecodeError('source skeleton sidecar length invalid')
        r.take(length)
        # Original source may carry alignment; never claim all unknown trailing bytes are parsed.
        if r.pos<len(r.data) and any(r.data[r.pos:]):
            raise DecodeError('unknown nonzero source skeleton trailing bytes')
    return bones


def world_bone_matrices(bones: list[Bone]):
    world=[None]*len(bones)
    states=[0]*len(bones)
    for first in range(len(bones)):
        if states[first]==2:continue
        chain=[]; idx=first
        while idx!=-1 and states[idx]!=2:
            if idx<0 or idx>=len(bones):raise DecodeError('skeleton parent outside source range')
            if states[idx]==1:raise DecodeError('source Skeleton parent cycle')
            states[idx]=1
            chain.append(idx)
            idx=bones[idx].parent
        for i in reversed(chain):
            bone=bones[i]
            world[i]=bone.local if bone.parent==-1 else bone.local@world[bone.parent]
            states[i]=2
    return world


def original_modelbin_attachment_matrix(source_bones: list[Bone],
                                    source_world_bones: list[np.ndarray],
                                    bone_name: str, bone_id: int) -> np.ndarray | None:
    """参照製品 FindBoneWorld applies a *ModelBin* skeleton to a Carbin instance.

    This is NOT the separate Carbin Scene Skeleton. 参照製品 resolves the local
    ModelBin bone by case-insensitive name first, then falls back to bone Id;
    here the Id fallback is used only when the Carbin bone name is empty
    (骨名がModelBinに無い場合は番号で代用しない。下記コメント参照).
    missing source attachment means the original instance matrix is kept.
    The returned matrix is post-multiplied after the Carbin authored transform
    (row-vector order). No car-specific offset or double Scene transform.
    """
    if (not isinstance(source_bones,list) or not isinstance(source_world_bones,list)
            or not source_bones or len(source_bones)!=len(source_world_bones)
            or not isinstance(bone_name,str) or type(bone_id) is not int):
        raise DecodeError('invalid source ModelBin attachment binding')
    names=[bone.name.casefold() for bone in source_bones]
    if any(not name for name in names) or len(names)!=len(set(names)):
        raise DecodeError('ambiguous original ModelBin attachment bone names')
    target=names.index(bone_name.casefold()) if bone_name and bone_name.casefold() in names else -1
    # 骨名があるのに部品ModelBinの骨格に無い場合は、番号で代用しない（Carbinの配置行列のまま）。
    # Carbinの骨番号は車全体の骨格（<車名>_skeleton.modelbin）の番号で、部品ModelBinの骨格の
    # 番号ではない（参照ツール carbin_importer.py：
    # skeleton_modelbin.skeleton.bones[model.bone_index]、参照のみ）。代用すると別の骨を拾い、
    # GIN_G40_19の左側のローター・キャリパー・ホイールがボンネット／トランクのヒンジの骨
    # （root_boneHood、boneHood、boneTrunk）の位置まで動いて車体から離れていた。
    # 骨名が空の場合だけ、従来（参照製品 FindBoneWorld）どおり番号を使う。
    if target<0 and not bone_name and 0<=bone_id<len(source_bones):
        target=bone_id
    if target<0:
        return None
    matrix=np.asarray(source_world_bones[target],dtype=np.float64)
    if matrix.shape!=(4,4) or not np.isfinite(matrix).all():
        raise DecodeError('invalid ModelBin attachment World Bone matrix')
    return matrix


def _side_code(bone: object, prefix: str) -> str | None:
    if isinstance(bone, str) and bone.startswith(prefix) and len(bone) > len(prefix):
        return bone[len(prefix):]
    return None


def _first_bone_x(bones: list[Bone], names: tuple[str, ...]) -> float | None:
    for bone in bones:
        if bone.name in names:
            value = float(np.asarray(bone.local, dtype=np.float64)[3, 0])
            return value if np.isfinite(value) else None
    return None


BRAKE_AXLE_MATCH_TOLERANCE_M = 0.05


def presentation_brake_matrices(records, part_type_of, bones_of) -> dict:
    """ブレーキのディスク・キャリパーを、ゲームの表示と同じくホイールの行列から置く配置の行列を返す。

    Carbin のディスクの配置の行列は、ゲームの表示に使われない。ゲームはディスクを「ホイールの
    ModelBin の spindle 骨の X のずれ」×「同じ車軸（spindleXX）のホイールの位置と、左右で決まる向き」で置き、キャリパーを
    「ディスクの ModelBin の rotorXX_center 骨（無ければ rotor_center、rotorLF_center）の X のずれと、
    Carbin でのディスクとの相対位置（Y・Z）、Carbin のキャリパーの回転（右側は Y 軸周りに 180°）」で
    ディスクに対して置く（参照ツール carbin_importer.py の CarScene::BrakePart::InitLocalTransforms・
    SetWheelAndTireTransforms の解析、参照のみ。2026-11-17 に SUB_WRXSTi_05 と POR_3_917LHFE_70 の
    原本で、左右対称・ディスクがキャリパーの間とホイールの内側に収まることを確認）。
    Carbin の行列のままだと、右側のディスクが反転しない車（SUB_WRXSTi_05）や、ディスクがホイールの
    表面の位置に来る車（POR_3_917LHFE_70）で、ディスクがホイールの前に出る。

    records：(キー, Carbin の部品の記録, ModelBin のパス) の並び。part_type_of(番号)→部品の種類の名前。
    bones_of(パス)→その ModelBin の骨の並び。返り値：{キー: 4×4 の行列（行ベクトル、平行移動は行 3）}。
    同じ車軸にホイール・ディスクが 1 つずつ無い場合、ホイールに spindle 骨が無い場合、Carbin での
    ホイールとディスクの高さ・前後位置が BRAKE_AXLE_MATCH_TOLERANCE_M より離れている場合は差し替えない。
    """
    wheels: dict[str, list] = {}
    rotors: dict[str, list] = {}
    calipers: dict[str, list] = {}
    for key, instance, path in records:
        kind = part_type_of(getattr(instance, 'part_type_raw', None))
        bone = getattr(instance, 'bone', '')
        if kind == 'WheelStyle':
            code, target = _side_code(bone, 'spindle'), wheels
        elif kind == 'Brakes':
            code, target = _side_code(bone, 'spindle'), rotors
            if code is None:
                code, target = _side_code(bone, 'hub'), calipers
        else:
            continue
        if code is not None:
            target.setdefault(code, []).append((key, instance, path))
    result = {}
    for code, rotor_rows in rotors.items():
        wheel_rows = wheels.get(code, [])
        if len(rotor_rows) != 1 or len(wheel_rows) != 1:
            continue
        _, wheel, wheel_path = wheel_rows[0]
        rotor_key, rotor, rotor_path = rotor_rows[0]
        spindle = _first_bone_x(bones_of(wheel_path), ('spindle',))
        if spindle is None:
            continue
        wheel_matrix = np.asarray(wheel.matrix, dtype=np.float64).reshape(4, 4)
        rotor_matrix = np.asarray(rotor.matrix, dtype=np.float64).reshape(4, 4)
        # Carbin のホイールとディスクの車軸の高さ・前後位置が食い違う記録（例：MER_G65AMG_13 は右の
        # spindleRF・spindleRR のホイールの位置が前後入れ替わっている）は、取り違えを避けて差し替えない。
        if np.abs(wheel_matrix[3, 1:3] - rotor_matrix[3, 1:3]).max() > BRAKE_AXLE_MATCH_TOLERANCE_M:
            continue
        right = code.startswith('R')
        # ゲームのホイールの配置は、左は回転なし、右は Y 軸周りに 180° で、位置だけが車ごとに決まる。
        # Carbin のホイールの回転は右側が Z 軸周りに 180° の車もある（例：BMW_M2Comp_20）ため使わない
        # （回転対称のホイールでは見た目が同じだが、キャリパーを置くと上下・前後が逆になる）。
        placement = np.eye(4)
        if right:
            placement[:3, :3] = np.diag((-1., 1., -1.))
        placement[3, :3] = wheel_matrix[3, :3]
        translate = np.eye(4)
        translate[3, 0] = spindle
        brake = translate @ placement
        result[rotor_key] = brake
        caliper_rows = calipers.get(code, [])
        if len(caliper_rows) != 1:
            continue
        caliper_key, caliper, _ = caliper_rows[0]
        center = _first_bone_x(bones_of(rotor_path), (f'rotor{code}_center', 'rotor_center', 'rotorLF_center'))
        caliper_matrix = np.asarray(caliper.matrix, dtype=np.float64).reshape(4, 4)
        local = np.eye(4)
        local[:3, :3] = caliper_matrix[:3, :3] @ np.diag((-1., 1., -1.)) if right else caliper_matrix[:3, :3]
        local[3, 0] = center if center is not None else 0.0
        local[3, 1] = caliper_matrix[3, 1] - rotor_matrix[3, 1]
        local[3, 2] = (caliper_matrix[3, 2] - rotor_matrix[3, 2]) * (-1. if right else 1.)
        result[caliper_key] = local @ brake
    for matrix in result.values():
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise DecodeError('invalid brake presentation matrix')
    return result


# ディスクの ModelBin に controlArm 骨が無いときの、ゲームの既定のずれ（12 インチ、float32 の 0x3E9C0EC0）。
CONTROL_ARM_DEFAULT_OFFSET_M = 0.30480003
_CORNER_CODES = ('LF', 'RF', 'LR', 'RR', 'LM', 'RM')


def _control_arm_corner(bone: object) -> str | None:
    """コントロールアームの骨の名前（controlArm_LF・controlArmLF 等）から車輪の位置（LF 等）を取る。"""
    if not isinstance(bone, str) or not bone.casefold().startswith('controlarm'):
        return None
    code = bone[len('controlArm'):].lstrip('_').upper()
    return code if code in _CORNER_CODES else None


def presentation_control_arm_matrices(records, part_type_of, bones_of) -> dict:
    """足回りのコントロールアームを、ゲームの表示と同じくホイールの位置から置く配置の行列を返す。

    Carbin のコントロールアームの配置の行列（多くの車で車の中央、原点付近）は、ゲームの表示に使われない。
    ゲームはコントロールアームを、回転なしで「同じ車輪のホイールの位置」から横（X）に
    「ホイールの ModelBin の spindle 骨の X のずれ」＋「同じ車輪のディスクの ModelBin の controlArm 骨の X
    （無ければ 12 インチ）」だけずらして置く（右側は符号を反転）（参照ツール carbin_importer.py の
    CarScene::BrakePart::InitLocalTransforms・Presentation11::CarPresentation::SetWheelAndTireTransforms の
    解析、参照のみ）。Carbin の行列のままだと、4 つのコントロールアームが車の中央に集まり、車高の高い車
    （NIS_Fairlady432Z_69 等）でサイドシルの下に浮いて見える。

    records：(キー, Carbin の部品の記録, ModelBin のパス) の並び。part_type_of(番号)→部品の種類の名前。
    bones_of(パス)→その ModelBin の骨の並び。返り値：{キー: 4×4 の行列（行ベクトル、平行移動は行 3）}。
    同じ車輪にホイールが 1 つでない場合、ホイールに spindle 骨が無い場合は差し替えない。
    """
    wheels: dict[str, list] = {}
    rotors: dict[str, list] = {}
    arms: dict[str, list] = {}
    for key, instance, path in records:
        kind = part_type_of(getattr(instance, 'part_type_raw', None))
        bone = getattr(instance, 'bone', '')
        if kind == 'WheelStyle':
            code, target = _side_code(bone, 'spindle'), wheels
        elif kind == 'Brakes':
            code, target = _side_code(bone, 'spindle'), rotors
        else:
            code, target = _control_arm_corner(bone), arms
        if code is not None:
            target.setdefault(code, []).append((key, instance, path))
    result = {}
    for code, arm_rows in arms.items():
        wheel_rows = wheels.get(code, [])
        if len(wheel_rows) != 1:
            continue
        _, wheel, wheel_path = wheel_rows[0]
        spindle = _first_bone_x(bones_of(wheel_path), ('spindle',))
        if spindle is None:
            continue
        offset = CONTROL_ARM_DEFAULT_OFFSET_M
        rotor_rows = rotors.get(code, [])
        if len(rotor_rows) == 1:
            value = _first_bone_x(bones_of(rotor_rows[0][2]), ('controlArm',))
            if value is not None:
                offset = value
        shift = spindle + offset
        if code.startswith('R'):
            shift = -shift
        wheel_matrix = np.asarray(wheel.matrix, dtype=np.float64).reshape(4, 4)
        matrix = np.eye(4)
        matrix[3, :3] = wheel_matrix[3, :3]
        matrix[3, 0] += shift
        if not np.isfinite(matrix).all():
            raise DecodeError('invalid control arm presentation matrix')
        for key, _instance, _path in arm_rows:
            result[key] = matrix.copy()
    return result


def transform_source_geometry(decoded, *, bone_matrix: np.ndarray, instance_matrix: np.ndarray,
                              source_position_scale: tuple[float, float, float, float]):
    """Apply source scale-correct normals, rigid bone & Carbin instance.

    参照製品 ModelImporter.ReadNormal decodes the packed normal into raw
    model space; 参照製品 Program.TransformNormals applies inverse source Mesh
    PositionScale per nonzero component *before* the rigid inverse transpose.
    PositionScale is the original Mesh source value, not a vehicle-specific fix.
    This stage remains RESEARCH ONLY until GPU/Windows/Xbox acceptance.
    """
    if decoded['space_proof']!='SOURCE_VERTEX_ONLY_NOT_BONE_INSTANCED':
        raise DecodeError('only original-source raw geometry accepted')
    if decoded['missing_source_normal']:
        raise DecodeError('original source normal missing; explicit mesh policy required')
    positions=np.asarray(decoded['arrays'][('POSITION',0)],dtype=np.float64)
    normals=np.asarray(decoded['arrays'][('NORMAL',0)],dtype=np.float64)
    try:
        scale=np.asarray(source_position_scale,dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise DecodeError('missing or invalid original ModelBin PositionScale') from exc
    if scale.shape!=(4,) or not np.isfinite(scale).all():
        raise DecodeError('missing or invalid original ModelBin PositionScale')
    # The source importer normal is still in *unscaled* packed mesh space.
    # The POSITION buffer was expanded using mesh.scale in extract_raw_geometry.
    # Keep the reference converter's tolerance for zero PositionScale axes;
    # values near zero mean no division, never fabricate an arbitrary normal.
    normals=normals.copy()
    for axis in range(3):
        if abs(scale[axis]) > 1.e-6:
            normals[:,axis] /= scale[axis]
    if not np.isfinite(normals).all():
        raise DecodeError('original Mesh PositionScale produced invalid normal')
    matrices=[np.asarray(m,dtype=np.float64) for m in (bone_matrix,instance_matrix)]
    if any(m.shape!=(4,4) or not np.isfinite(m).all() for m in matrices):
        raise DecodeError('invalid source pose matrix')
    bone,instance=matrices
    composite=bone@instance
    det=np.linalg.det(composite[:3,:3])
    if not np.isfinite(det) or abs(det)<1.e-12:
        raise DecodeError('source rigid pose noninvertible')
    hom=np.column_stack((positions,np.ones(len(positions))))
    transformed=hom@composite
    if np.any(np.abs(transformed[:,3])<1.e-12):raise DecodeError('invalid projective source pose')
    xyz=transformed[:,:3]/transformed[:,3:4]
    # C# System.Numerics uses an inverse transpose for normals, then flips handedness.
    # Normal is row-vector; inverse transpose of combined 3x3 is the corresponding row matrix.
    normal_matrix=np.linalg.inv(composite[:3,:3]).T
    final_normals=normals@normal_matrix
    lengths=np.linalg.norm(final_normals,axis=1)
    # 参照製品 TransformNormals: degenerate or too-small normals become UnitY.
    # Missing source NORMAL, in contrast, remains a hard error upstream.
    valid=lengths>1.e-3
    final_normals[valid]/=lengths[valid,None]
    final_normals[~valid]=[0.,1.,0.]
    xyz[:,0]*=-1
    final_normals[:,0]*=-1
    # Reflection is baked into model origin; preserve explicit winding decision.
    reflected_composite=composite@np.diag((-1.,1.,1.,1.))
    winding_flip=np.linalg.det(reflected_composite[:3,:3])<0
    if not (np.isfinite(xyz).all() and np.isfinite(final_normals).all()):
        raise DecodeError('source rigid pose nonfinite')
    return {'positions':xyz.astype(np.float32),'normals':final_normals.astype(np.float32),
            'winding_reversed':bool(winding_flip),'space_proof':'SOURCE_RIGID_BONE_AND_INSTANCE_APPLIED',
            'basis':'LO4FH6_CSHARP_ROW_VECTOR_X_REFLECTION'}
