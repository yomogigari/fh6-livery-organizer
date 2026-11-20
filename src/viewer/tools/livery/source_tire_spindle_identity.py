#!/usr/bin/env python3
"""原本ModelBinのSpindle行列とタイヤ位置を照合する車種共通・非描画監査。

メッシュの外側装飾面からタイヤ中心を推定しない。原本のWheelStyle
インスタンス行列（hex float32）と元タイヤ頂点中心の一致を検証してから、
出典付きGameDB平行移動を適用できるか判定する。
ゲームのShader/装着挙動の正解を主張せず、原本/PRIVATEを配布しない。
"""
from __future__ import annotations
from collections import defaultdict
import math
import numbers
import struct

ROLES = ('front_left','front_right','rear_left','rear_right')

class SpindleIdentityError(ValueError):
    """ModelBin/GLB/タイヤが同一の出典と証明できない。"""


def _spindle_from_identity(record: str):
    """形式 |spindleLF|ordinal|partType|HEX32×16 のModelBin行列を読み取る。"""
    if not isinstance(record,str):
        raise SpindleIdentityError('原本WheelStyleのinstance identityがありません')
    fields=record.split('|')
    if len(fields)!=5 or not fields[0].startswith('game:/') or not fields[1].lower().startswith('spindle') or fields[3]!='44':
        raise SpindleIdentityError('原本ModelBinのWheelStyle identity形式不正')
    words=fields[4].split(',')
    if len(words)!=16 or any(len(w)!=8 or any(c not in '0123456789ABCDEFabcdef' for c in w) for w in words):
        raise SpindleIdentityError('原本ModelBin行列の生ビット形式不正')
    try:
        m=[struct.unpack('>f',bytes.fromhex(w))[0] for w in words]
    except (ValueError,struct.error) as ex:
        raise SpindleIdentityError('原本ModelBin行列の復号に失敗') from ex
    if not all(math.isfinite(x) for x in m) or abs(m[15]-1)>1e-6:
        raise SpindleIdentityError('原本ModelBin行列に非有限/非アフィン成分があります')
    return fields[1],m[12:15]


def audit_original_spindle_mount(doc: dict, original_tire_centres: dict,
                                game_db_translations: dict, visual_wheel_centres: dict) -> dict:
    """元タイヤ重心の3軸がModelBin spindle原点か、配置後のYZが元WheelStyleかを照合。

    Xは装飾ホイールのBBox重心を使用しない。ビード座・装備の意味は未証明。
    既存メッシュと頂点には一切書き込まない。
    """
    if any(set(x)!=set(ROLES) for x in (original_tire_centres,game_db_translations,visual_wheel_centres)):
        raise SpindleIdentityError('署名元の四輪が不足/重複')
    groups=defaultdict(list)
    for m in doc.get('meshes',[]):
        ex=m.get('extras',{})
        if ex.get('lo4_part_type')!='WheelStyle':continue
        role=ex.get('lo4_wheel_morph_wheel')
        if role not in ROLES:continue
        spindle,origin=_spindle_from_identity(ex.get('lo4_instance_identity'))
        expected='spindle'+('LF' if role=='front_left' else 'RF' if role=='front_right' else 'LR' if role=='rear_left' else 'RR')
        if spindle.lower()!=expected.lower() or not str(ex.get('lo4_wheel_morph_source','')).startswith('internal-modelbin-'):
            raise SpindleIdentityError('原本WheelStyleのSpindleロール/出典が不一致')
        groups[role].append(tuple(origin))
    result={}
    for role in ROLES:
        values=groups.get(role,[])
        if len(values)<2 or any(any(abs(v[i]-values[0][i])>1e-5 for i in range(3)) for v in values[1:]):
            raise SpindleIdentityError('原本ModelBinの同一Spindle行列が一意でありません')
        source=values[0]
        orig=original_tire_centres[role]
        t=game_db_translations[role]
        wheel=visual_wheel_centres[role]
        if any(len(v)!=3 or any(not isinstance(x,numbers.Real) or isinstance(x,bool) or not math.isfinite(x) for x in v) for v in (source,orig,t,wheel)):
            raise SpindleIdentityError('原本座標が非有限/次元不一致')
        orig_err=[(float(orig[i])-source[i])*1000 for i in range(3)]
        if max(abs(x) for x in orig_err)>1.5:
            raise SpindleIdentityError('元Tire中心が原本Spindle原点ではありません（二重変換/別パケット）')
        # 原本WheelStyleのBBox幾何中心はX軸でタイヤと一致する必要はない。
        # Y/Zは回転対称ジオメトリで元Spindle+GameDB移動を確認できる。
        yz_err=[(float(wheel[i])-source[i]-float(t[i]))*1000 for i in (1,2)]
        if max(abs(x) for x in yz_err)>2.5:
            raise SpindleIdentityError('原本WheelStyleのYZ中心がGameDB配置と不一致')
        result[role]={
            'source_spindle_xyz_m':[round(v,7) for v in source],
            'original_tire_center_xyz_m':[round(float(v),7) for v in orig],
            'gamedb_translation_xyz_m':[round(float(v),7) for v in t],
            'source_center_residual_mm':[round(v,4) for v in orig_err],
            'visual_wheel_yz_residual_mm':[round(v,4) for v in yz_err],
            'nominal_postplacement_tire_center_xyz_m':[round(float(orig[i])+float(t[i]),7) for i in range(3)],
            'visual_wheel_x_used_to_scale_tire':False,
        }
    return {'schema':'lo4fh6.firstparty.original-spindle-3axis-fit-gate.v1',
            'source_modelbin_instance_identity_unique':True,
            'source_spindle_origin_matched_to_original_tire':True,
            'modelbin_gamedb_yz_verified':True,
            'wheel_visual_face_is_not_tire_bead_width':True,
            'tire_mesh_geometry_changed':False,
            'car_specific_correction':False,
            'xbox_appearance_approved':False,
            'roles':result}

SPINDLE_TO_ROLE={
    'spindleLF':'front_left','spindleRF':'front_right',
    'spindleLR':'rear_left','spindleRR':'rear_right',
}


def determine_source_axis_mapping(doc:dict, tire_centres_by_spindle:dict, visual_wheel_centres:dict):
    """原本Spindle識別子から車輪の左右軸反転を判定し、最近傍誤割当を防ぐ。

    glTF側が原本のX符号を反転済みか、ModelBinの原本行列とGLBの左右分離から判断。
    出典が欠ける場合は名前/車種で推定せず明示拒否する。
    """
    if set(tire_centres_by_spindle)!=set(SPINDLE_TO_ROLE) or set(visual_wheel_centres)!=set(ROLES):
        raise SpindleIdentityError('原本4輪/Spindleの実体数が不一致')
    originals={};source_rows=defaultdict(list)
    for mesh in doc.get('meshes',[]):
        ex=mesh.get('extras',{})
        role=ex.get('lo4_wheel_morph_wheel')
        if ex.get('lo4_part_type')!='WheelStyle' or role not in ROLES:continue
        spindle, origin = _spindle_from_identity(ex.get('lo4_instance_identity'))
        if {k.casefold():v for k,v in SPINDLE_TO_ROLE.items()}.get(spindle.casefold())!=role:
            raise SpindleIdentityError('元SpindleとWheelStyleの所属が不一致')
        source_rows[role].append(origin)
    for spindle,role in SPINDLE_TO_ROLE.items():
        sources=source_rows.get(role,[])
        if len(sources)<2 or any(any(abs(x-y)>1e-5 for x,y in zip(sources[0],p)) for p in sources[1:]):
            raise SpindleIdentityError('同一輪の原本Spindle座標が一意ではありません')
        o=sources[0]
        tire=tire_centres_by_spindle[spindle]
        if len(tire)!=3 or any(not math.isfinite(float(x)) for x in tire):
            raise SpindleIdentityError('元タイヤ座標が不正')
        if max(abs(float(tire[i])-o[i]) for i in range(3))>.0015:
            raise SpindleIdentityError('元タイヤの座標は同じSpindleのModelBin行列ではありません')
        originals[role]=o
    def side_sep(values,axle):
        return float(values[f'{axle}_left'][0])-float(values[f'{axle}_right'][0])
    signs=[]
    for axle in ('front','rear'):
        src=side_sep(originals,axle);view=side_sep(visual_wheel_centres,axle)
        if min(abs(src),abs(view))<.15:
            raise SpindleIdentityError('左右車輪の元位置が近すぎて座標系を判定できません')
        signs.append(1 if src*view>0 else -1)
    if signs[0]!=signs[1]:
        raise SpindleIdentityError('前後軸で左右座標系が不一致')
    sign=signs[0]
    # 既存の車体/WheelStyleに合わせてX座標の符号のみをノード変換する。
    # タイヤの生POSITION/NORMAL/INDEXは一切変更しない。
    for spindle,role in SPINDLE_TO_ROLE.items():
        orig=tire_centres_by_spindle[spindle]
        ref=visual_wheel_centres[role]
        aligned=[sign*float(orig[0]),float(orig[1]),float(orig[2])]
        alt=min((math.dist(aligned,ref2),r) for r,ref2 in visual_wheel_centres.items() if r!=role)
        score=math.dist(aligned,ref)
        if score>=alt[0]*.55:
            raise SpindleIdentityError('元Spindleからの軸変換で対応輪を一意に選べません')
    return sign,dict(SPINDLE_TO_ROLE)
