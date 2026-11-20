#!/usr/bin/env python3
"""原本TireパケットとGameDB公称寸法の車種共通監査（PRIVATE原本の公開は禁止）。

このコードは描画やメッシュを変更しない。ホイールの見える装飾面はビード座幅ではない。
既知の純正形状が違う場合、勝手な幅補正を作らず明示的に拒否する。
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct

ROLES = ('spindleLF', 'spindleRF', 'spindleLR', 'spindleRR')


class StockTireDimensionError(ValueError):
    """署名・GameDB・幾何のいずれかが不一致。"""


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _stock_spec(db_path: Path, car_id: int) -> dict:
    if not db_path.is_file():
        raise StockTireDimensionError('GameDBファイルなし')
    # READ ONLY: source database must never be modified by audit.
    try:
        with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as con:
            rows = con.execute('''
                SELECT c.MediaName,c.FrontTireWidthMM,c.FrontTireAspect,c.FrontWheelDiameterIN,
                       c.RearTireWidthMM,c.RearTireAspect,c.RearWheelDiameterIN,
                       t.TireModelName
                  FROM Data_Car AS c
                  JOIN List_UpgradeTireCompound AS t
                    ON t.Ordinal=c.Id AND t.IsStock=1
                 WHERE c.Id=?
            ''', (car_id,)).fetchall()
    except sqlite3.DatabaseError as ex:
        raise StockTireDimensionError('GameDB構造またはSQL不正') from ex
    if len(rows)!=1:
        raise StockTireDimensionError('原本GameDBの純正タイヤが一意でない')
    media,fw,fa,fd,rw,ra,rd,model = rows[0]
    if (not isinstance(media,str) or not media or not isinstance(model,str) or not model
        or any(type(v) is not int for v in (fw,fa,fd,rw,ra,rd))
        or not all(100<=w<=500 and 15<=a<=100 and 10<=d<=30
                   for w,a,d in ((fw,fa,fd),(rw,ra,rd)))):
        raise StockTireDimensionError('GameDBに未知の寸法またはタイヤ名あり')
    return {'media_name':media,'tire_model_name':model,
            'front':{'width_mm':fw,'aspect_percent':fa,'rim_inches':fd},
            'rear':{'width_mm':rw,'aspect_percent':ra,'rim_inches':rd}}


def audit_stock_tire_dimensions(meta:dict, blob:bytes, db_path:Path) -> dict:
    """符号付きパケット＋原本GameDBの4輪寸法を照合。原本/描画状態には書き込まない。"""
    if meta.get('schema')!='lo4fh6.private.verified-wheel-candidate.v1':
        raise StockTireDimensionError('署名済Wheelパケットの型ではない')
    if (meta.get('vertex_stride')!=24 or type(meta.get('car_id')) is not int
        or not 1<=meta['car_id']<=1000000 or meta.get('geometry_bytes')!=len(blob)
        or meta.get('geometry_sha256')!=_digest(blob)):
        raise StockTireDimensionError('パケットSHA/バイト数/頂点形式/CarID不一致')
    source_db_sha=meta.get('r125_source_proof',{}).get('source_gamedb_sha256')
    data_db=Path(db_path).read_bytes()
    if not isinstance(source_db_sha,str) or _digest(data_db)!=source_db_sha:
        raise StockTireDimensionError('パケットとGameDBの原本SHAが不一致')
    spec=_stock_spec(Path(db_path),meta['car_id'])
    source_names=[r for r in meta.get('meshes',[]) if r.get('kind')=='tire']
    if len(source_names)!=12 or meta.get('mesh_count')!=len(meta.get('meshes',[])):
        raise StockTireDimensionError('原本12タイヤ・全メッシュ件数が不一致')
    result={}
    for role in ROLES:
        parts=[r for r in source_names if r.get('spindle')==role]
        if len(parts)!=3:raise StockTireDimensionError('4輪の元Tire primitive分布が不正')
        axle='front' if role in ROLES[:2] else 'rear'; nominal=spec[axle]
        xx=[]; yy=[]; zz=[]
        for r in parts:
            name=r.get('sourceMesh','').lower()
            if not name.startswith('tire') or ('_'+spec['tire_model_name'].lower()+'_lods0') not in name:
                raise StockTireDimensionError('元ModelBinのTireModelNameが純正GameDBと異なる')
            vo=r.get('vertexOffset');io=r.get('indexOffset');vc=r.get('vertexCount');ic=r.get('indexCount')
            if (any(type(v) is not int for v in (vo,io,vc,ic)) or vo<0 or vc<100
                or vc>65536 or io!=vo+vc*24 or ic<3 or ic%3 or io+ic*2>len(blob)):
                raise StockTireDimensionError('タイヤ頂点/索引の区間が不正')
            for x,y,z,nx,ny,nz in struct.iter_unpack('<6f',blob[vo:io]):
                if not all(math.isfinite(v) for v in (x,y,z,nx,ny,nz)):
                    raise StockTireDimensionError('原本タイヤ頂点にNaN/Inf')
                xx.append(x);yy.append(y);zz.append(z)
        if len(xx)<1000:raise StockTireDimensionError('原本タイヤ頂点不足')
        ym=(min(yy)+max(yy))/2;zm=(min(zz)+max(zz))/2
        radii=(math.hypot(y-ym,z-zm) for y,z in zip(yy,zz))
        radii=list(radii)
        observed_width=(max(xx)-min(xx))*1000
        observed_inner=min(radii)*2*1000
        observed_outer=max(radii)*2*1000
        expected_inner=nominal['rim_inches']*25.4
        expected_outer=expected_inner+2*nominal['width_mm']*nominal['aspect_percent']/100
        # 量子化・float32の余地だけを許容する。車種別の見た目補正ではない。
        width_tol=max(1.5,nominal['width_mm']*.005)
        if (abs(observed_width-nominal['width_mm'])>width_tol
            or abs(observed_inner-expected_inner)>1.5
            or abs(observed_outer-expected_outer)>1.5):
            raise StockTireDimensionError('原本Tire幅/内径/外径がGameDB純正値と異なる')
        result[role]={
          'source_model_meshes':len(parts),'vertex_count':len(xx),
          'nominal_width_mm':nominal['width_mm'],
          'measured_width_mm':round(observed_width,4),
          'nominal_inner_diameter_mm':round(expected_inner,4),
          'measured_inner_diameter_mm':round(observed_inner,4),
          'nominal_outer_diameter_mm':round(expected_outer,4),
          'measured_outer_diameter_mm':round(observed_outer,4),
          'tire_axial_center_m':round((min(xx)+max(xx))/2,7),
          'source_tire_center_yz_m':[round(ym,7),round(zm,7)]}
    for front,rear in (('spindleLF','spindleRF'),('spindleLR','spindleRR')):
        if (abs(result[front]['tire_axial_center_m']+result[rear]['tire_axial_center_m'])>0.002
            or abs(result[front]['measured_width_mm']-result[rear]['measured_width_mm'])>1):
            raise StockTireDimensionError('左右タイヤ形状の鏡像関係が崩れている')
    return {'schema':'lo4fh6.firstparty.stock-tire-dimension-source-audit.v1',
       'car_id':meta['car_id'],'source_media_name':spec['media_name'],
       'source_tire_model_name':spec['tire_model_name'],
       'source_packet_sha256':meta['geometry_sha256'],
       'source_gamedb_sha256':source_db_sha,'roles':result,
       'source_geometry_matches_stock_size':True,
       'visual_wheel_face_is_not_proven_bead_seat_width':True,
       'axial_fh6_mounting_verified':False,'game_runtime_morph_verified':False,
       'gpu_visual_xbox_approved':False,'production_default_changed':False}


def main() -> None:
    import argparse
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--packet-meta',required=True,type=Path)
    a.add_argument('--packet-bin',required=True,type=Path)
    a.add_argument('--gamedb',required=True,type=Path)
    a.add_argument('--evidence-output',type=Path,help='任意：既存ファイルは上書きしない')
    args=a.parse_args()
    result=audit_stock_tire_dimensions(json.loads(args.packet_meta.read_text('utf-8')),
                                       args.packet_bin.read_bytes(),args.gamedb)
    result_text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.evidence_output:
        with args.evidence_output.open('x',encoding='utf-8') as f:f.write(result_text)
    print(result_text)


if __name__=='__main__':main()
