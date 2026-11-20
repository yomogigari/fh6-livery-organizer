"""原本Skin/Morphの復号済みバイト由来情報を、非描画GLB accessorへ保全する。

GLB標準のSkin、JOINTS_0、WEIGHTS_0、mesh.targetsには接続しない。
ゲーム内のBind Pose、Morph係数、損傷/装着状態が未確定のため、
この保全データを表示変形に適用してはならない。原本由来GLBはPRIVATEのみ。
"""
from __future__ import annotations
import re
import numpy as np


class DeformationPayloadError(ValueError):
    """元データとの対応を証明できないため出力を拒否する。"""


def _sha_valid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _finite_matrix(values: object, shape: tuple[int, ...], name: str) -> np.ndarray:
    arr = np.asarray(values)
    if arr.shape != shape or not np.issubdtype(arr.dtype, np.number):
        raise DeformationPayloadError(f"{name} の元形状が一致しません")
    if not np.isfinite(arr).all():
        raise DeformationPayloadError(f"{name} に非有限値があります")
    return arr


def append_source_deformation_accessors(writer, *, skin=None, morph=None, vertex_count: int) -> dict:
    """元頂点順で非描画accessorを追加し、参照先をextras用辞書で返す。

    各accessorはglTFの通常要素で、参照先は第一者独自extrasのみ。
    Skin/Morphの実GPU/Windows/Xboxでの受入を意味しない。
    """
    if type(vertex_count) is not int or vertex_count < 1:
        raise DeformationPayloadError("元頂点数が不正です")
    if skin is None and morph is None:
        return {}
    result = {'schema': 'lo4fh6.original-deformation-accessors.research.v1',
              'applied_to_positions': False, 'release_approved': False,
              'vertex_count': vertex_count}
    if skin is not None:
        n = vertex_count
        k = np.asarray(skin.bone_indices).shape[-1]
        if k not in (1, 2) or skin.vertex_count != n or skin.skeleton_bone_count < 1:
            raise DeformationPayloadError("Skin元頂点数または骨格数が不正です")
        joints = _finite_matrix(skin.bone_indices, (n, k), 'Skin骨')
        weights = _finite_matrix(skin.weights, (n, k), 'Skin重み')
        if (np.any(joints < 0) or np.any(joints >= skin.skeleton_bone_count) or
            np.any(joints != np.floor(joints)) or np.any(joints > 65535) or
            np.any(weights < 0) or np.any(weights > 1) or
            np.any(np.abs(weights.sum(axis=1) - 1) > 0.002) or
            not _sha_valid(skin.buffer_sha256) or skin.original_record_start < 0 or
            skin.original_buffer_id < 0):
            raise DeformationPayloadError("Skinの元バッファ参照・値が検証不能です")
        joint_data = np.zeros((n, 4), dtype='<u2')
        weight_data = np.zeros((n, 4), dtype='<f4')
        joint_data[:, :k] = joints
        weight_data[:, :k] = weights
        result['skin'] = {
            'buffer_id': skin.original_buffer_id,
            'record_start': skin.original_record_start,
            'source_buffer_sha256': skin.buffer_sha256,
            'skeleton_bone_count': skin.skeleton_bone_count,
            'source_influences_per_vertex': k,
            'padded_zero_influences': 4 - k,
            'joint_accessor': writer.accessor(joint_data, 'VEC4', 5123, None),
            'weight_accessor': writer.accessor(weight_data, 'VEC4', 5126, None),
        }
    if morph is not None:
        n = vertex_count
        t = morph.target_count
        if not 1 <= t <= 32 or morph.vertex_count != n:
            raise DeformationPayloadError("Morphターゲット数・元頂点数が不正です")
        position = _finite_matrix(morph.position_deltas, (n, t, 3), 'Morph位置')
        normal = _finite_matrix(morph.normal_deltas, (n, t, 3), 'Morph法線')
        pslots = _finite_matrix(morph.position_weight_indices, (n, t), 'Morph位置スロット')
        nslots = _finite_matrix(morph.normal_weight_indices, (n, t), 'Morph法線スロット')
        if (any(np.any(v < 0) or np.any(v >= 32) or np.any(v != np.floor(v))
                for v in (pslots, nslots)) or not _sha_valid(morph.buffer_sha256) or
            morph.original_record_start < 0 or morph.original_buffer_id < 0):
            raise DeformationPayloadError("Morphの元バッファ参照・スロットが検証不能です")
        result['morph'] = {
            'buffer_id': morph.original_buffer_id,
            'record_start': morph.original_record_start,
            'source_buffer_sha256': morph.buffer_sha256,
            'target_count': t,
            'layout': 'vertex_major_target_minor',
            'damage_or_fitment_coefficient': 'UNKNOWN_NOT_APPLIED',
            'position_delta_accessor': writer.accessor(position.reshape(n*t, 3).astype('<f4'), 'VEC3', 5126, None),
            'normal_delta_accessor': writer.accessor(normal.reshape(n*t, 3).astype('<f4'), 'VEC3', 5126, None),
            'position_weight_slot_accessor': writer.accessor(pslots.reshape(n*t).astype('u1'), 'SCALAR', 5121, None),
            'normal_weight_slot_accessor': writer.accessor(nslots.reshape(n*t).astype('u1'), 'SCALAR', 5121, None),
        }
    return result
