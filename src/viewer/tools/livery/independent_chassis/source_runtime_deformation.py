"""原本照合済みのSkin/Morphを実頂点へ適用する第一者Stage。

Skinには元Bindと元Poseの両方、Morphには32-slot係数を要求する。
FH6の係数や装着を推測して0/identityで補完しない。
"""
from __future__ import annotations
import numpy as np

class SourceRuntimeDeformationError(ValueError):
    pass

def _positions(data,n,label):
    a=np.asarray(data,dtype=np.float64)
    if a.shape!=(n,3) or not np.isfinite(a).all():
        raise SourceRuntimeDeformationError(label+'の頂点形状または数値が不正')
    return a.copy()

def _normals(data,n):
    a=_positions(data,n,'法線')
    length=np.linalg.norm(a,axis=1)
    if np.any(length<=1e-12):
        raise SourceRuntimeDeformationError('零長法線を正規化できません')
    return a/length[:,None]

def _matrix_series(value,count,label):
    a=np.asarray(value,dtype=np.float64)
    if a.shape!=(count,4,4) or not np.isfinite(a).all():
        raise SourceRuntimeDeformationError(label+'の4x4行列数が原本骨数と不一致')
    if (not np.allclose(a[:,:3,3],0.,rtol=0.,atol=1e-6)
            or not np.allclose(a[:,3,3],1.,rtol=0.,atol=1e-6)
            or np.any(np.abs(np.linalg.det(a[:,:3,:3]))<1e-10)):
        raise SourceRuntimeDeformationError(label+'に非affine/特異行列があります')
    return a

def apply_verified_source_deformation(positions,normals,*,skin=None,morph=None,
                                      source_bind_world=None,source_pose_world=None,
                                      original_morph_slot_weights=None,
                                      original_morph_slot_semantics=None,
                                      original_morph_higher_slot_modulation=None):
    """原本頂点座標系でMorph（スロット別）→Skin LBSの順に実適用する。

    モデルごとのGameDB適用係数/正規Bind Poseは呼び元で検証して渡す。
    source_worldは行ベクトル方式の配列。未知なら必ずエラーにする。
    """
    n=len(positions)
    if n<1:raise SourceRuntimeDeformationError('空頂点は変形不可')
    xyz=_positions(positions,n,'元位置')
    nr=_normals(normals,n)
    result={'skin_applied_vertices':0,'morph_applied_vertices':0,
            'runtime_default_pose_assumed':False,'runtime_zero_morph_assumed':False}
    if morph is not None:
        if getattr(morph,'is_damage',None) is not False:
            raise SourceRuntimeDeformationError('損傷Morphは通常Morphの係数経路へ適用できません')
        t=getattr(morph,'target_count',None)
        if type(t) is not int or not 1<=t<=32 or morph.vertex_count!=n:
            raise SourceRuntimeDeformationError('原本Morph頂点数/ターゲット数不一致')
        if original_morph_slot_weights is None:
            raise SourceRuntimeDeformationError('Morphの原本係数32-slotが未確認です')
        w=np.asarray(original_morph_slot_weights,dtype=np.float64)
        if w.shape!=(32,) or not np.isfinite(w).all():
            raise SourceRuntimeDeformationError('Morphの原本係数32-slotが不正です')
        # 参照製品 Studio NativeMorphs.cs car_tires_pg: slots > 1 multiply by
        # an explicitly supplied higherSlotModulation. No default is inferred.
        if original_morph_slot_semantics == 'verified_effective_slots':
            if original_morph_higher_slot_modulation is not None:
                raise SourceRuntimeDeformationError('実効slot係数に二重modulationを適用できません')
        elif original_morph_slot_semantics == 'car_tires_pg_raw_slots':
            mod=original_morph_higher_slot_modulation
            if (type(mod) not in (int,float) or not np.isfinite(mod) or not 0<=mod<=1):
                raise SourceRuntimeDeformationError('car_tires_pgの原本higherSlotModulationが未確認です')
            w=w.copy()
            w[2:]*=float(mod)
        else:
            raise SourceRuntimeDeformationError('Morph係数のslot意味が原本で確定していません')
        dp=np.asarray(morph.position_deltas,dtype=np.float64)
        dn=np.asarray(morph.normal_deltas,dtype=np.float64)
        ps=np.asarray(morph.position_weight_indices)
        ns=np.asarray(morph.normal_weight_indices)
        if (dp.shape!=(n,t,3) or dn.shape!=(n,t,3)
                or ps.shape!=(n,t) or ns.shape!=(n,t)
                or not np.isfinite(dp).all() or not np.isfinite(dn).all()
                or not np.issubdtype(ps.dtype,np.integer)
                or not np.issubdtype(ns.dtype,np.integer)
                or np.any(ps<0) or np.any(ns<0)
                or np.any(ps>=32) or np.any(ns>=32)):
            raise SourceRuntimeDeformationError('原本Morphデルタ/重みスロットが不正です')
        xyz+=(dp*w[ps][:,:,None]).sum(axis=1)
        nr+=(dn*w[ns][:,:,None]).sum(axis=1)
        nr=_normals(nr,n)
        result['morph_applied_vertices']=n
    elif (original_morph_slot_weights is not None or original_morph_slot_semantics is not None
          or original_morph_higher_slot_modulation is not None):
        raise SourceRuntimeDeformationError('Morphのない元Meshへ係数を適用できません')
    if skin is not None:
        if source_bind_world is None or source_pose_world is None:
            raise SourceRuntimeDeformationError('Skinの原本Bind Pose/現在姿勢が未確認です')
        count=getattr(skin,'skeleton_bone_count',None)
        if type(count) is not int or not 1<=count<=2048 or skin.vertex_count!=n:
            raise SourceRuntimeDeformationError('Skin骨数/元頂点数が不正です')
        bind=_matrix_series(source_bind_world,count,'原本Bind Pose')
        pose=_matrix_series(source_pose_world,count,'元Bone Pose')
        joints=np.asarray(skin.bone_indices)
        weights=np.asarray(skin.weights,dtype=np.float64)
        if (joints.ndim!=2 or joints.shape!=weights.shape or joints.shape[0]!=n
                or joints.shape[1] not in (1,2) or not np.issubdtype(joints.dtype,np.integer)
                or np.any(joints<0) or np.any(joints>=count)
                or not np.isfinite(weights).all() or np.any(weights<0) or np.any(weights>1)
                or np.any(np.abs(weights.sum(axis=1)-1)>0.002)):
            raise SourceRuntimeDeformationError('原本SkinボーンID/重みが不正です')
        transforms=np.linalg.inv(bind)@pose
        coords=np.column_stack((xyz,np.ones(n)))
        res=np.zeros((n,3),dtype=np.float64)
        nres=np.zeros((n,3),dtype=np.float64)
        for k in range(joints.shape[1]):
            ix=joints[:,k];amount=weights[:,k,None]
            part=np.einsum('ni,nij->nj',coords,transforms[ix])
            if np.any(np.abs(part[:,3])<1e-12):
                raise SourceRuntimeDeformationError('Skin後の同次座標wが不正です')
            res+=(part[:,:3]/part[:,3,None])*amount
            normal_mat=np.linalg.inv(transforms[ix,:3,:3]).transpose(0,2,1)
            nres+=np.einsum('ni,nij->nj',nr,normal_mat)*amount
        xyz,nr=res,_normals(nres,n)
        result['skin_applied_vertices']=n
    elif source_bind_world is not None or source_pose_world is not None:
        raise SourceRuntimeDeformationError('Skinがない元MeshのBind/Pose入力は不正です')
    if not np.isfinite(xyz).all():
        raise SourceRuntimeDeformationError('実変形結果に非有限値があります')
    return xyz.astype('<f4'),nr.astype('<f4'),result
