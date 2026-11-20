"""原本Carbin Bone参照と車両Scene Skeletonを一意に照合する独立研究用剛体装着。

参照製品のCarbinモデル行列→Skeleton行列経路を仕様比較し、独自実装する。
ModelBinのMesh固有Rigid Boneとは別物。ゲーム内Bind Pose、Skin/Morph係数、
車輪の最終装着、Xbox画質の完全一致は証明しない。
"""
from __future__ import annotations
import numpy as np

class SourceSceneAttachmentError(ValueError):
    """原本から姿勢参照を特定できない場合は無言で補正せず拒否する。"""

def source_scene_attached_matrix(instance, scene_bones, scene_world):
    """元Carbinモデル行列の後に元Scene Bone world行列を適用（行ベクトル方式）。

    Scene側のBone名・IDが一意に一致する研究用途のみに使用。
    """
    if getattr(instance, 'snap_to_parent', None) is not False:
        raise SourceSceneAttachmentError('元SnapToParentは独立した親装着契約が必要です')
    authored=np.asarray(instance.matrix,dtype=np.float64)
    if authored.size!=16 or not np.isfinite(authored).all():
        raise SourceSceneAttachmentError('元Carbin行列が不正です')
    authored=authored.reshape(4,4)
    bone_id=instance.bone_id
    bone_name=instance.bone
    if type(bone_id) is not int or not isinstance(bone_name,str):
        raise SourceSceneAttachmentError('元Carbin Bone参照の型が不正です')
    if bone_id==-1 and not bone_name:
        return authored, None
    if bone_id<0 or bone_id>=len(scene_bones) or len(scene_world)!=len(scene_bones) or not bone_name:
        raise SourceSceneAttachmentError('元Scene SkeletonのBone参照を解決できません')
    matches=[i for i,b in enumerate(scene_bones) if b.name.casefold()==bone_name.casefold()]
    if len(matches)!=1 or matches[0]!=bone_id:
        raise SourceSceneAttachmentError('元Scene SkeletonのBone名とIDが一致しません')
    attachment=np.asarray(scene_world[bone_id],dtype=np.float64)
    if attachment.shape!=(4,4) or not np.isfinite(attachment).all():
        raise SourceSceneAttachmentError('元Scene Bone行列が無効です')
    result=authored@attachment
    if (not np.isfinite(result).all() or
        abs(float(np.linalg.det(result[:3,:3])))<1e-12):
        raise SourceSceneAttachmentError('元Scene Bone装着行列が特異です')
    return result,bone_id
