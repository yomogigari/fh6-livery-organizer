"""原本CarbinのWheelStyle/Brakes識別を既存GLB契約へ正規化する第一者アダプター。

旧成功済みwheel_morph_internal/タイヤStageの再利用を目的とする。
車種ID固有の補正、推測ベースの4輪配置は行わない。
"""
from __future__ import annotations

import math
import re
import struct

class SourceWheelIdentityError(ValueError):
    pass

_SOURCE_WHEEL_STYLE_PART = 43  # Jaguar/Vivio原本Carbinで同一PartTypeを検証
_SOURCE_BRAKE_PART = 4
_CORNER = re.compile(r'(lf|rf|lr|rr)$', re.I)
_CORNER_NAME = {'lf':'front_left','rf':'front_right','lr':'rear_left','rr':'rear_right'}

def source_wheel_or_brake_identity(instance, source_entry: str, mesh_offset: int):
    """既存r235のCarbin原本行列パーサーへ渡せる非改変float32 IDを生成。

    非Wheel/BrakeならNone。原本のPartType/モデルパス/Boneが不一致なら失敗する。
    """
    raw = instance.part_type_raw
    if type(raw) is not int:
        raise SourceWheelIdentityError('原本PartTypeの型が不正です')
    if raw not in (_SOURCE_WHEEL_STYLE_PART, _SOURCE_BRAKE_PART):
        return None
    name = 'WheelStyle' if raw == _SOURCE_WHEEL_STYLE_PART else 'Brakes'
    expected = '/wheels/' if raw == _SOURCE_WHEEL_STYLE_PART else '/brakes/'
    if not isinstance(source_entry, str) or expected not in source_entry.casefold():
        raise SourceWheelIdentityError('原本PartTypeと元ModelBinパスが不一致です')
    bone = instance.bone
    if not isinstance(bone, str) or not bone.strip():
        raise SourceWheelIdentityError('原本Wheel/Brake Bone名が欠落しています')
    match = _CORNER.search(bone)
    # 原本の車軸はLF／RF／LR／RRの4輪に限定されない。
    # 3輪・6輪原本は標準4輪の装着識別を捏造せず、元Boneと行列を保持する。
    # Noneは標準4輪位置が未検証であることを明示する。
    # 参照製品／参照製品はSpindle／Hub接頭辞の有無によらず原本Name／IDでAttachment Boneを解決する。
    # 原本の輪位置SuffixとCarbin Float32行列を維持し、WheelStyle／Brake原本Pathゲートも守る。
    # GLB原本ゲートでは4つの異なる輪位置を必須とする。
    matrix = tuple(instance.matrix)
    if (len(matrix) != 16 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in matrix)
            or type(mesh_offset) is not int or mesh_offset < 0):
        raise SourceWheelIdentityError('原本Carbin行列/mesh offsetが不正です')
    matrix_hex = ','.join(struct.pack('>f', float(v)).hex() for v in matrix)
    # 全meshが同じCarbinモデルinstanceの識別子を共有する。Mesh offsetは別属性に保持。
    identity=f'{source_entry}|{bone}|{name}|{matrix_hex}'
    return {'part_type':name,'instance_identity':identity,
            'original_corner':(_CORNER_NAME[match.group(1).lower()] if match else None),
            'original_bone':bone,'standard_corner_verified':match is not None}
