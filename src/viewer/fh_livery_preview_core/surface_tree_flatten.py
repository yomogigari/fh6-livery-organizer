"""解析後のグループ木を配置順序どおりに展開するプロジェクト実装。

入力ノードをどの形式で復号するかとは分離した変形処理であり、
外部デコーダーの行列計算・型・定数を必要としない。
"""
from __future__ import annotations

import math

MAX_DEPTH = 128
MAX_PLACEMENTS = 150_000


def _multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    """2x3 のアフィン変換を 6 要素 (a,b,c,d,tx,ty) として合成する。"""
    a,b,c,d,x,y = left
    e,f,g,h,u,v = right
    return (a*e+b*g, a*f+b*h, c*e+d*g, c*f+d*h, a*u+b*v+x, c*u+d*v+y)


def _group_transform(value) -> tuple[float, ...]:
    rad = math.radians(value.rotation)
    cs,sn = math.cos(rad),math.sin(rad)
    return (cs*value.sx,-sn*value.sy,sn*value.sx,cs*value.sy,value.x,value.y)


def _shape_transform(value) -> tuple[float, ...]:
    """移動→回転→水平方向のせん断→拡大縮小を順に合成した値。"""
    rad = math.radians(value.rotation)
    cs,sn = math.cos(rad),math.sin(rad)
    return (cs*value.sx,(cs*value.skew-sn)*value.sy,
            sn*value.sx,(sn*value.skew+cs)*value.sy,value.x,value.y)


def _components(matrix: tuple[float, ...]) -> tuple[float, ...]:
    a,b,c,d,x,y = matrix
    magnitude = math.hypot(a,c)
    if magnitude < 1e-8:
        return (x,y,0.0,math.hypot(b,d),0.0,0.0)
    # 反射を含むときはX方向の縮尺を負として保持する。
    mirrored = a*d-b*c < 0
    theta = math.atan2(-c,-a) if mirrored else math.atan2(c,a)
    sx = -magnitude if mirrored else magnitude
    cs,sn=math.cos(theta),math.sin(theta)
    sy=-sn*b+cs*d
    shear=(cs*b+sn*d)/sy if abs(sy)>1e-8 else 0.0
    angle=(math.degrees(theta)%360.0)
    return (x,y,sx,sy,0.0 if abs(angle-360.0)<1e-9 else angle,shear)


def flatten_decoded_tree(root, *, layer_start: int = 0, section: str | None = None) -> list[dict]:
    """入力の親子構造・配置順・マスク継承を尊重して配置リストを返す。

    この関数はファイルのバイト列や参照製品実装を参照せず、解析済みノードのみを読む。
    """
    layers: list[dict] = []
    identity=(1.0,0.0,0.0,1.0,0.0,0.0)

    def walk(group, world, mask_depth: int, inherited_section: str | None, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ValueError('group nesting depth limit exceeded')
        name=group.section or inherited_section
        mask_depth += bool(group.mask)
        world=_multiply(world,_group_transform(group.transform))
        for child in group.items:
            if hasattr(child,'items'):
                walk(child,world,mask_depth,name,depth+1)
                continue
            if len(layers)>=MAX_PLACEMENTS:
                raise ValueError('placement limit exceeded')
            coords=_components(_multiply(world,_shape_transform(child)))
            record_mask=bool(child.mask and (child.mask_authoritative or child.color_rgba[0]==child.color_rgba[1]==child.color_rgba[2]))
            is_mask=bool(mask_depth or record_mask)
            mask_source=('group+record' if mask_depth and record_mask else
                         'group' if mask_depth else 'record' if record_mask else 'none')
            layers.append({
                'shape_id':child.shape_id,
                'data':[*coords,1 if is_mask else 0],
                'color_rgba':list(child.color_rgba),
                'mask':is_mask,
                'flags':child.flags,
                'marker_hex':child.marker.hex(),
                'source_offset':layer_start+child.offset,
                'section':child.section or name or section,
                'is_raster_logo':child.is_raster_logo,
                'raster_id':child.raster_id,
                'mask_source':mask_source,
                'mask_group_depth':mask_depth,
                'group_depth':depth,
                'record_mask_authoritative':bool(child.mask_authoritative),
            })
    walk(root,identity,0,section,0)
    return layers
