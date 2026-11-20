"""第一者FH6 Carbin v7リーダー (原本参照。ゲームデータ非同梱)。

未定義versionやフィールドは絶対に推測しない。Stockとアップグレードの経路を保全する。
出力は変換器入力用の構造であり、3D/GLBの完成を表明しない。
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import struct

class CarbinFormatError(ValueError): pass

@dataclass(frozen=True)
class ModelRef:
    path: str
    matrix: tuple[float, ...]
    bone: str
    bone_id: int
    lod_flags: int
    draw_groups: int
    material_bindings: tuple[tuple[str,int], ...]
    part_group: int
    stock: bool
    option_ids: tuple[int, ...]
    snap_to_parent: bool
    model_version: int
    part_type_raw: int
    # Horizon v15+のCarRenderModel.IsInteriorWindshield (元bool)。
    # 参照製品 ClassifyRole の WindowHint に接続する静止プレビュー情報。
    window_hint: bool = False

class _Reader:
    def __init__(self, raw: bytes): self.raw=raw; self.pos=0
    def take(self, n:int):
        if n<0 or n>len(self.raw)-self.pos: raise CarbinFormatError(f'Carbin truncated at {self.pos} reading {n}')
        b=self.raw[self.pos:self.pos+n];self.pos+=n;return b
    def val(self,fmt:str): return struct.unpack('<'+fmt,self.take(struct.calcsize('<'+fmt)))[0]
    def b(self): return self.val('B')
    def h(self): return self.val('H')
    def u(self): return self.val('I')
    def i(self): return self.val('i')
    def f(self): return self.val('f')
    def boolean(self):
        v=self.b()
        if v not in (0,1):raise CarbinFormatError('invalid Boolean value')
        return bool(v)
    def text(self):
        n=self.i()
        if n<0 or n>8192:raise CarbinFormatError('invalid Carbin string length')
        return self.take(n).decode('latin-1')
    def count(self,lim=10000):
        n=self.u()
        if n>lim: raise CarbinFormatError('count too large')
        return n
    def bounds(self):return tuple(self.f() for _ in range(8))

def _model(r:_Reader,group:int,stock:bool,option_ids:tuple[int,...], part_type:int)->ModelRef:
    version=r.h()
    if version<15 or version>21:raise CarbinFormatError(f'unsupported FH6 render model version {version}')
    path=r.text()
    transform=tuple(r.f() for _ in range(16))
    if not all(math.isfinite(v) for v in transform):raise CarbinFormatError('invalid transform')
    lod=r.h() if version>=5 else r.u()
    bone=r.text();bone_id=r.val('h');snap=r.boolean();draw_groups=r.i()
    if version<9:r.text()
    for _ in range(r.count(10000) if version>=2 else 0):
        r.text();r.take(r.count(1024*1024))
    material=[]
    if version>=3:
        for _ in range(r.count(10000)):
            name=r.text(); val=r.val('Q') if version>=21 else r.i()&0xffffffff
            material.append((name,val))
    if version>=6 and r.boolean():r.f();r.i()
    if version>=8:r.f()
    if version>=9:
        for _ in range(r.count(10000)):
            ao_ver=r.h();r.text();r.u();r.i()
            if ao_ver>=2:r.take(16)
            else:r.take(3)
            r.boolean()
            if ao_ver>=3:r.take(2)
    window_hint = r.boolean() if version>=10 else False
    if version>=11:r.take(2+16)
    if version>=12:r.text()
    if version>=13:r.take(16)
    if version>=14:r.take(16+4)
    if version>=15:r.i()
    if version>=16:
        for _ in range(r.count(10000)):r.take(16)
    if version>=17:r.b()
    if version>=18:r.u()
    if version>=21:r.u();r.text()
    if not path or not path.lower().endswith('.modelbin'):raise CarbinFormatError('model entry is invalid')
    return ModelRef(path,transform,bone,bone_id,lod,draw_groups,tuple(material),group,stock,option_ids,snap,version,part_type,window_hint)

def parse_carbin(raw:bytes)->dict:
    if not isinstance(raw,bytes) or len(raw)>16*1024*1024:raise CarbinFormatError('bad Carbin bytes')
    r=_Reader(raw);scene_version=r.h()
    if scene_version!=7:raise CarbinFormatError(f'unsupported FH6 Carbin version {scene_version}')
    r.take(16);r.boolean();ordinal=r.u();media=r.text();skeleton=r.text();lod=r.h()
    models=[];parts=[];options=[];option_reference_issues=[]
    base_count=r.count(500)
    for index in range(base_count):
        part_marker=r.b();part_version=r.h();part_type=r.u()
        if not 1<=part_version<=3:raise CarbinFormatError(f'unsupported base part {part_version}')
        count=r.count(300)
        for _ in range(count):models.append(_model(r,index,True,(),part_type))
        if part_version>=2:r.bounds()
        parts.append({'kind':'base','group':index,'marker':part_marker,'part_type_raw':part_type,'models':count})
    upgrade_count=r.count(100)
    for group_idx in range(upgrade_count):
        group=base_count+group_idx;ver=r.h();part_type=r.u()
        if not 1<=ver<=4:raise CarbinFormatError('unsupported upgrade part')
        ids=[];group_options=[]
        for _ in range(r.count(100)):
            up_ver=r.h();level=r.b();stock=r.boolean();option_id=r.i();body_id=r.i();parent_stock=r.boolean()
            if not 1<=up_ver<=4:raise CarbinFormatError('unsupported upgrade version')
            if up_ver<3:
                for _ in range(r.count(200)):models.append(_model(r,group,stock,(option_id,),part_type))
            if up_ver>=2:r.bounds()
            ids.append(option_id)
            option={'part_type_raw':part_type,'group':group,'level':level,'stock':stock,'id':option_id,'body_id':body_id,'parent_stock':parent_stock}
            group_options.append(option);options.append(option)
        if ver>=3:
            for _ in range(r.count(500)):
                chosen=tuple(r.i() for _ in range(r.count(100)))
                # 参照製品 SceneModelInstancesは元の参照問題を記録し、このPart Groupに属するOptionだけを結び付ける。
                # 参照製品 CarbinParserは共有IDを原本通りに読む。
                # 共有リストが本当に空なら全Upgrade候補を意味するが、未知IDだけの非空リストを全候補へ拡大しない。
                known=set(ids)
                valid=tuple(dict.fromkeys(x for x in chosen if x in known))
                unknown=tuple(dict.fromkeys(x for x in chosen if x not in known))
                shared=_model(r,group,any(o['stock'] and o['id'] in valid for o in group_options),valid,part_type)
                if unknown:
                    option_reference_issues.append({
                        'group':group,'part_type_raw':part_type,
                        'source_modelbin_path':shared.path,
                        'unknown_option_ids':list(unknown),
                    })
                if chosen and not valid:
                    continue
                models.append(shared)
        parts.append({'kind':'upgrade','group':group,'part_type_raw':part_type,'options':len(group_options)})
    r.boolean();r.boolean()
    if r.pos!=len(raw):raise CarbinFormatError(f'unknown trailing Carbin bytes ({len(raw)-r.pos})')
    if not models:raise CarbinFormatError('empty Carbin')
    return {'version':scene_version,'ordinal':ordinal,'media':media,'skeleton':skeleton,'lod':lod,
            'parts':parts,'options':options,'models':models,
            'option_reference_issues':option_reference_issues,'bytes_consumed':r.pos}
