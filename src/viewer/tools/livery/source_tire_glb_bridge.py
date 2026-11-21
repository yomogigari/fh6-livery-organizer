#!/usr/bin/env python3
"""署名済みの真正Viewer GLBと実ModelBin由来タイヤパケットを非破壊結合する。

ゲーム由来バイト列はPRIVATEローカルだけに置き、この第一者ソースは一切同梱しない。
元車輪/タイヤのPOSITION・NORMAL・INDEXを補正・移動・鏡映しない。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import marshal
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from . import bytes_memo
from .portable_mesh_converter import adopt_firstparty_chassis_metadata, seal_firstparty_chassis_metadata

KEYS = ('front_left', 'front_right', 'rear_left', 'rear_right')
# 6 輪の車の中央の車輪（骨 LM・RM）。タイヤの ModelBin・寸法・車幅・高さは同じ側の後輪の値を使う。
MIDDLE_KEYS = ('middle_left', 'middle_right')
ALL_WHEEL_ROLES = KEYS + MIDDLE_KEYS
REAR_FOR_MIDDLE = {'middle_left': 'rear_left', 'middle_right': 'rear_right'}


def _standard_four_corner_flags(doc) -> set:
    """変換の段階が WheelStyle に付けた「原本の車輪がちょうど 4 つの角」の印の値の集合。"""
    flags = set()
    for mesh in doc.get('meshes', []):
        ex = mesh.get('extras', {})
        if ex.get('lo4_part_type') != 'WheelStyle' and ex.get('lo4fh6_part_type') != 'WheelStyle':
            continue
        for key in ('lo4fh6_feow_standard_four_corner_eligible', 'lo4_feow_standard_four_corner_eligible'):
            if key in ex:
                flags.add(ex[key])
    return flags


def digest(b: bytes) -> str:
    # 同じ bytes のオブジェクトの SHA は覚えた値を使う（bytes_memo、2026-11-21）
    return bytes_memo.sha256_hex(b)


def release_tire_stage_memos() -> None:
    """タイヤの段で覚えた GLB（解析の結果・SHA・書いたばかりのファイル）を捨てる（2026-11-21）。

    Viewer は窓を閉じても残るので、段が終わったら持ち続けない（次の車の GLB は中身が違うので、覚えても使わない）。
    """
    with _READ_GLB_LOCK:
        _READ_GLB_MEMO.clear()
    bytes_memo.release()


# 同じ中身の GLB を続けて読むとき（法線の GLB を作った直後の確かめと、次の段の入力など）、JSON の解析と旧名の
# 取り込み（タイヤの GLB で約 0.3 秒）をやり直さない。中身の SHA ごとに直近の数件を覚え、読むたびに新しい木を
# 作って渡す（呼ぶ側が書き換えても、覚えた物は変わらない）。marshal で書き出せない木は覚えない（2026-11-21）。
_READ_GLB_MEMO: "OrderedDict[bytes, tuple[bytes, bytes]]" = OrderedDict()
_READ_GLB_LIMIT = 2
_READ_GLB_LOCK = threading.Lock()


def read_glb(data: bytes):
    key = bytes_memo.sha256_digest(data)
    with _READ_GLB_LOCK:
        found = _READ_GLB_MEMO.get(key)
        if found is not None:
            _READ_GLB_MEMO.move_to_end(key)
    if found is not None:
        return marshal.loads(found[0]), bytearray(found[1])
    document, binary = _read_glb_uncached(data)
    try:
        stored = (marshal.dumps(document), bytes(binary))
    except ValueError:
        return document, binary
    with _READ_GLB_LOCK:
        _READ_GLB_MEMO[key] = stored
        while len(_READ_GLB_MEMO) > _READ_GLB_LIMIT:
            _READ_GLB_MEMO.popitem(last=False)
    return document, binary


def _read_glb_uncached(data: bytes):
    if len(data) < 28 or data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
        raise ValueError('GLB 2.0以外は拒否')
    if struct.unpack_from('<I', data, 8)[0] != len(data):
        raise ValueError('GLB length不正')
    jlen, jtype = struct.unpack_from('<I4s', data, 12)
    if jtype != b'JSON' or jlen % 4:
        raise ValueError('JSON chunk不正')
    j = json.loads(data[20:20+jlen]); p = 20+jlen
    blen, btype = struct.unpack_from('<I4s',data,p)
    if btype != b'BIN\0' or p+8+blen != len(data):
        raise ValueError('GLB BIN chunk不正')
    if len(j.get('buffers',[])) != 1 or j['buffers'][0]['byteLength'] > blen:
        raise ValueError('単一バッファ以外は明示拒否')
    return adopt_firstparty_chassis_metadata(j), bytearray(data[p+8:])


def vertex_world_bounds(doc, buf, node, mesh):
    prim=mesh['primitives'][0]; acc=doc['accessors'][prim['attributes']['POSITION']]
    view=doc['bufferViews'][acc['bufferView']]
    if acc['componentType'] != 5126 or acc['type']!='VEC3' or view.get('byteStride') not in (None,12):
        raise ValueError('元GLBのPOSITIONが想定外')
    off=view.get('byteOffset',0)+acc.get('byteOffset',0)
    verts=np.frombuffer(buf,dtype='<f4',count=3*acc['count'],offset=off).reshape(-1,3)
    if 'matrix' not in node and any(k in node for k in ('rotation','translation','scale')):
        raise ValueError('元GLBノードのTRS座標変換を未解釈のまま使用しない')
    m=np.asarray(node.get('matrix',[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]),dtype=np.float64).reshape(4,4).T
    world=(np.c_[verts,np.ones(len(verts))] @ m.T)[:,:3]
    return world.min(0),world.max(0)


def wheel_centres(doc,buf):
    """変形済みの WheelStyle の、車輪の役割ごとの中心。

    原本の車輪がちょうど 4 つの角の車（変換の段階の印が真）は、従来どおり 4 つの角がそろうこと。
    原本が 3 輪（角が 3 つ）・6 輪（中央の 2 輪）の車（印が偽）は、ある役割だけを返す。
    """
    grouped={k:[] for k in ALL_WHEEL_ROLES}
    for node in doc.get('nodes',[]):
        if 'mesh' not in node:continue
        mesh=doc['meshes'][node['mesh']]; ex=mesh.get('extras',{})
        if ex.get('lo4_part_type')!='WheelStyle':continue
        name=ex.get('lo4_wheel_morph_wheel')
        if name in grouped and ex.get('lo4_wheel_morph_source','').startswith('internal-modelbin-'):
            grouped[name].append(vertex_world_bounds(doc,buf,node,mesh))
    corners=[k for k in KEYS if grouped[k]]
    middles=[k for k in MIDDLE_KEYS if grouped[k]]
    non_standard = _standard_four_corner_flags(doc) == {False}
    if non_standard:
        if len(corners) < 3 or len(middles) not in (0, 2) or (middles and len(corners) != 4):
            raise ValueError('GLBの車輪の元モーフ出典が欠ける（3 輪・6 輪の形が不正）')
    elif len(corners) != 4 or middles:
        raise ValueError('GLBの4輪元モーフ出典が欠ける')
    return {k:(np.min([x[0] for x in v],axis=0)+np.max([x[1] for x in v],axis=0))/2
            for k,v in grouped.items() if v}



def source_gamedb_tire_placement(doc, wheel_centers, tire_centers):
    """原本GameDBの4輪配置をタイヤノードに適用可能か確認（研究モード専用）。

    既存WheelStyleは配置済み、r125由来Tire頂点は未配置、という両方の原本証拠が
    数値でも一致したときに限り許可する。原本頂点/UV/車輪Shaderは変更しない。
    未知の元データ・混在Stage・曖昧な出典は例外として安全拒否する。
    """
    rows = {k: [] for k in KEYS}
    for mesh in doc.get('meshes', []):
        ex = mesh.get('extras', {})
        if ex.get('lo4_part_type') != 'WheelStyle':
            continue
        wheel = ex.get('lo4_wheel_morph_wheel')
        if wheel not in rows:
            continue
        translation = ex.get('lo4_wheel_gamedb_placement_translation_glb')
        if (ex.get('lo4_wheel_gamedb_placement_source') != 'local-fh6-gamedb'
                or type(ex.get('lo4_wheel_gamedb_placement_revision')) is not int
                or ex['lo4_wheel_gamedb_placement_revision'] < 1
                or ex.get('lo4_wheel_gamedb_placement_wheel') != wheel
                or not str(ex.get('lo4_wheel_morph_source', '')).startswith('internal-modelbin-')
                or not isinstance(translation, list) or len(translation) != 3
                or any(type(v) not in (int, float) or not np.isfinite(v) or abs(v) > 0.25
                       for v in translation)):
            raise ValueError('WheelStyleの原本GameDB配置の出典が不足・不一致')
        rows[wheel].append(tuple(float(v) for v in translation))
    if set(wheel_centers) != set(KEYS) or set(tire_centers) != set(KEYS):
        raise ValueError('原本4輪配置・タイヤ中心が欠ける')
    placements = {}
    for wheel in KEYS:
        # 全WheelStyle primitiveで一意に確定していること。1件の推測値だけでは採用しない。
        values = rows[wheel]
        if len(values) < 2 or any(any(abs(a-b) > 1e-5 for a, b in zip(values[0], t)) for t in values[1:]):
            raise ValueError('WheelStyleの原本GameDB配置が不完全・複数候補')
        t = np.asarray(values[0], dtype=np.float64)
        w = np.asarray(wheel_centers[wheel], dtype=np.float64)
        r = np.asarray(tire_centers[wheel], dtype=np.float64)
        if w.shape != (3,) or r.shape != (3,) or not np.isfinite(w).all() or not np.isfinite(r).all():
            raise ValueError('4輪中心座標が無効')
        # XはWheelStyleのハブ/スポークまで含むためgeom中心はタイヤ中心と非一致になりうる。
        # Y/Zは元WheelStyle配置済み対元Tire未配置の差に一致する必要がある。
        diff = w - r
        if max(abs(diff[1]-t[1]), abs(diff[2]-t[2])) > 0.0025:
            raise ValueError('元タイヤが未配置と確認できない（再適用/異版/原本不一致）')
        placements[wheel] = [float(v) for v in t]
    for axle in ('front', 'rear'):
        left = placements[f'{axle}_left']
        right = placements[f'{axle}_right']
        if (abs(left[0] + right[0]) > 1e-4
                or abs(left[1] - right[1]) > 1e-4
                or abs(left[2] - right[2]) > 1e-4):
            raise ValueError('左右の原本GameDB配置の鏡像関係が不一致')
    return placements

def add_aligned(raw: bytearray, add: bytes) -> int:
    raw.extend(b'\0' * (-len(raw)%4))
    off=len(raw)
    raw.extend(add)
    return off


def append_primitive(doc, binary, row, source_zip_sha, packet_sha, source_entry, wheel, node_translation=None, source_axis_x_scale=1):
    vo=int(row['vertexOffset']); nv=int(row['vertexCount']); ni=int(row['indexCount']); io=int(row['indexOffset'])
    if nv<=2 or nv>65536 or ni<=2 or ni%3 or vo<0 or io<0 or vo+nv*24>len(packet_data) or io+ni*2>len(packet_data):
        raise ValueError('元タイヤprimitive境界不正')
    vertex=packet_data[vo:vo+nv*24]; index=packet_data[io:io+ni*2]
    verts=np.frombuffer(vertex,dtype='<f4').reshape(-1,6)
    if not np.isfinite(verts).all():raise ValueError('元タイヤ頂点NaN/Inf')
    ids=np.frombuffer(index,dtype='<u2')
    if int(ids.max())>=nv:raise ValueError('元タイヤindex範囲外')
    startV=add_aligned(binary,vertex)
    viewV=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':startV,'byteLength':len(vertex),'byteStride':24,'target':34962})
    startI=add_aligned(binary,index)
    viewI=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':startI,'byteLength':len(index),'target':34963})
    aPos=len(doc['accessors']); doc['accessors'].append({'bufferView':viewV,'byteOffset':0,'componentType':5126,'count':nv,'type':'VEC3','min':verts[:,:3].min(0).tolist(),'max':verts[:,:3].max(0).tolist()})
    aNorm=len(doc['accessors']);doc['accessors'].append({'bufferView':viewV,'byteOffset':12,'componentType':5126,'count':nv,'type':'VEC3'})
    aIndex=len(doc['accessors']);doc['accessors'].append({'bufferView':viewI,'componentType':5123,'count':ni,'type':'SCALAR'})
    ex={'lo4_part_type':'Tire', 'lo4_role':'trim', 'lo4_source_entry':source_entry,
        'lo4_tire_source_wheel':wheel, 'lo4_tire_original_archive_sha256':source_zip_sha,
        'lo4_tire_source_packet_sha256':packet_sha,'lo4_tire_private_origin':'verified-original-archive-packet',
        'lo4_tire_game_mounting_verified':False,'lo4_tire_xbox_parity_verified':False,
        'lo4_stock_part':True,'lo4_base_visible':True}
    name=f"OriginalTire/{wheel}/{row['sourceMesh']}"
    meshIndex=len(doc['meshes']);doc['meshes'].append({'name':name,'primitives':[{'attributes':{'POSITION':aPos,'NORMAL':aNorm},'indices':aIndex,'material':tire_material_index,'mode':4}],'extras':ex})
    node={'name':name,'mesh':meshIndex,'extras':dict(ex)}
    if source_axis_x_scale not in (-1,1):raise ValueError('原本軸変換が不正')
    if source_axis_x_scale == -1:
        node['scale']=[-1,1,1] # glTFシーングラフで左右系を変換。頂点/INDEX原本は不変。
        node['extras']['lo4_tire_source_axis_conversion']='modelbin-x-to-glb-negative'

    if node_translation is not None:
        # glTF nodeの出典付き変換だけ追加。タイヤの元POSITION/NORMAL/UVは1byteも変更しない。
        node['translation'] = list(node_translation)
        node['extras']['lo4_tire_gamedb_placement_source'] = 'local-fh6-gamedb'
        node['extras']['lo4_tire_gamedb_placement_research'] = True
    nodeIndex=len(doc['nodes']);doc['nodes'].append(node)
    doc['scenes'][doc.get('scene',0)]['nodes'].append(nodeIndex)


def build(glb_path,meta_path,bin_path,tire_archive,output,proof_file,apply=False, source_gamedb_placement_research=False, game_db_dimension_audit=None, source_axis_role_research=False, source_stock_wheel_tire_fitment=False):
    """原本署名付き取付け契約を一括実行する。従来の個別スイッチは互換維持する。

    幾何寸法・元Spindle・左右軸・GameDB取付けを一つの経路で照合する。
    ただしゲーム内の最終装着選択とXbox外観の証明にはならず、通常入口は不変。
    """
    if source_stock_wheel_tire_fitment:
        if game_db_dimension_audit is None:
            raise ValueError('一括原本取付けではGameDB原本が必須です')
        source_gamedb_placement_research=True
        source_axis_role_research=True
    global packet_data,tire_material_index
    source_bytes=glb_path.read_bytes(); doc,bin_chunk=read_glb(source_bytes)
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    if meta.get('schema')!='lo4fh6.private.verified-wheel-candidate.v1' or meta.get('game_mounting_verified') is not False:
        raise ValueError('署名済みの旧研究Wheelパケット以外拒否')
    src_sha=digest(source_bytes)
    if src_sha != meta.get('r485_full_wheel_comparison',{}).get('source_glb_sha256'):
        raise ValueError('元GLBのSHAはパケット比較元と不一致')
    packet_data=bin_path.read_bytes(); packet_sha=digest(packet_data)
    if packet_sha!=meta.get('geometry_sha256') or len(packet_data)!=meta.get('geometry_bytes'):
        raise ValueError('元Wheel packetのSHA/サイズ不一致')
    original_tire_sha=digest(tire_archive.read_bytes())
    if original_tire_sha!=meta.get('r125_source_proof',{}).get('source_tire_sha256'):
        raise ValueError('元タイヤZIPのSHA不一致')
    if doc.get('meshes') is None or doc.get('accessors') is None or doc.get('bufferViews') is None or not doc.get('scenes'):
        raise ValueError('完成glTFの必要要素欠落')
    if any('tire' in str(x.get('name','')).lower() for x in doc['meshes']):
        raise ValueError('タイヤ追加済みのGLBには重複投入しない')
    centres=wheel_centres(doc,bin_chunk)
    tires=[x for x in meta['meshes'] if x.get('kind')=='tire']
    groups={}
    for row in tires:groups.setdefault(row['spindle'],[]).append(row)
    if len(groups)!=4 or any(not v for v in groups.values()) or sum(map(len,groups.values()))!=len(tires):
        raise ValueError('元パケットに4輪すべてのタイヤがありません')
    source_names={}
    with ZipFile(tire_archive) as z:
        source_names={x.filename.lower():x.filename for x in z.infolist() if x.filename.lower().endswith('.modelbin')}
    if not source_names:raise ValueError('原本タイヤZIPにModelBinなし')
    axis_x_scale=1
    role_map=None
    if source_axis_role_research:
        if not source_gamedb_placement_research or game_db_dimension_audit is None:
            raise ValueError('原本軸変換の研究にはGameDB配置と純正寸法の両監査が必須')
        from tools.livery.source_tire_spindle_identity import determine_source_axis_mapping
        tire_origins={}
        for spindle,rows in groups.items():
            verts=np.concatenate([np.frombuffer(packet_data[r['vertexOffset']:r['indexOffset']],dtype='<f4').reshape(-1,6)[:,:3] for r in rows])
            tire_origins[spindle]=(verts.min(0)+verts.max(0))/2
        axis_x_scale,role_map=determine_source_axis_mapping(doc,tire_origins,centres)
    pending=[]
    for spindle,rows in groups.items():
        mats=[]
        for row in rows:
            vb=packet_data[row['vertexOffset']:row['vertexOffset']+row['vertexCount']*24]
            if len(vb)!=row['vertexCount']*24:raise ValueError('packet vertex不足')
            vv=np.frombuffer(vb,dtype='<f4').reshape(-1,6)[:,:3]
            mats.append(vv)
        a=np.concatenate(mats);center=(a.min(0)+a.max(0))/2
        aligned=center*np.asarray([axis_x_scale,1,1])
        ranking=sorted((float(np.linalg.norm(aligned-c)),name) for name,c in centres.items())
        if role_map is not None and ranking[0][1]!=role_map[spindle]:
            raise ValueError('原本Spindle識別子と左右軸変換後の最近傍輪が不一致')
        pending.append((spindle,rows,ranking,center))
    if len({x[2][0][1] for x in pending})!=4:raise ValueError('元タイヤの4輪最近傍が重複/座標不一致')
    source_placements = None
    spindle_fit_evidence = None
    if source_gamedb_placement_research:
        # 研究ONでも元ModelBin/原本GameDB/タイヤ寸法が揃わなければ推測で続けない。
        if game_db_dimension_audit is None:
            raise ValueError('原本GameDBの寸法監査はGameDB配置研究で必須です')
        tire_centres = {ranking[0][1]: center for _,_,ranking,center in pending}
        source_placements = source_gamedb_tire_placement(doc, centres, tire_centres)
        if source_axis_role_research:
            from tools.livery.source_tire_spindle_identity import audit_original_spindle_mount
            spindle_fit_evidence = audit_original_spindle_mount(doc,tire_centres,source_placements,centres)
    # wheel IDはspindleの文字列L/Rでなく、元GLBの四輪位置から実測で対応付ける。
    doc.setdefault('materials',[])
    tire_material_index=len(doc['materials']);doc['materials'].append({'name':'PRIVATE-diagnostic-original-tire-not-game-shader','pbrMetallicRoughness':{'baseColorFactor':[0.12,0.13,0.14,1],'metallicFactor':0,'roughnessFactor':0.85},'doubleSided':False})
    # 署名済み元Tireの幅・内外径が純正GameDBと一致することを、明示オプション時だけ照合。
    # 半径/幅の目測補正は一切行わず、未知寸法は拒否する。標準描画入口は変えない。
    stock_dimension_evidence = None
    if game_db_dimension_audit is not None:
        from tools.livery.source_tire_gamedb_dimensions import audit_stock_tire_dimensions
        stock_dimension_evidence = audit_stock_tire_dimensions(meta, packet_data, Path(game_db_dimension_audit))
    proof={'schema':'lo4fh6.private.source-tire-glb-adapter.v1','car_id':meta.get('car_id'),'source_glb_sha256':src_sha,'source_packet_sha256':packet_sha,'source_tire_archive_sha256':original_tire_sha,'original_wheel_mesh_count':sum(1 for m in doc['meshes'] if m.get('extras',{}).get('lo4_part_type')=='WheelStyle'),'original_vehicle_mesh_count':len(doc['meshes']),'wheels':{},'game_mounting_verified':False,'xbox_parity_verified':False,'release_approved':False}
    if stock_dimension_evidence is not None:
        proof['stock_tire_dimension_evidence'] = stock_dimension_evidence
    if spindle_fit_evidence is not None:
        proof['original_spindle_3axis_fit_evidence'] = spindle_fit_evidence
        proof['source_axis_x_scale'] = axis_x_scale
        proof['source_axis_role_from_modelbin'] = True
    for spindle,rows,ranking,centre in pending:
        wheel=ranking[0][1]
        if ranking[1][0]<=ranking[0][0]*1.5:
            raise ValueError('タイヤ位置の割当が曖昧で同定できません')
        dest=[]
        for row in rows:
            source_name=str(row['sourceMesh']).split('_LODS0')[0]+'.modelbin'
            if source_name.lower() not in source_names:raise ValueError('タイヤModelBin元実体なし '+source_name)
            source_entry='PRIVATE-Archive/Tires/'+source_names[source_name.lower()]
            append_primitive(doc,bin_chunk,row,original_tire_sha,packet_sha,source_entry,wheel, None if source_placements is None else source_placements[wheel],source_axis_x_scale=axis_x_scale)
            dest.append(source_entry)
        proof['wheels'][wheel]={'spindle_label':spindle,'tire_meshes':len(rows),'source_entries':sorted(set(dest)),'tire_wheel_world_centre_m':centre.tolist(),'wheel_world_centre_m':centres[wheel].tolist(),'tire_wheel_centre_distance_m':ranking[0][0],'next_nearest_distance_m':ranking[1][0],'geometry_translation_applied_m':[0,0,0], 'node_translation_applied_m':[0,0,0] if source_placements is None else source_placements[wheel]}
    bin_chunk.extend(b'\0'*(-len(bin_chunk)%4))
    doc['buffers'][0]['byteLength']=len(bin_chunk)
    seal_firstparty_chassis_metadata(doc)
    jb=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    jb+=b' '*(-len(jb)%4)
    total=12+8+len(jb)+8+len(bin_chunk)
    raw=struct.pack('<4sII',b'glTF',2,total)+struct.pack('<I4s',len(jb),b'JSON')+jb+struct.pack('<I4s',len(bin_chunk),b'BIN\0')+bin_chunk
    if output.exists() or proof_file.exists():raise ValueError('既存出力GLB/証明書を上書きしない')
    if apply:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(raw)
    proof['result_glb_sha256']=digest(raw)
    proof['result_mesh_count']=len(doc['meshes'])
    proof['result_added_tire_meshes']=len(tires)
    if apply:
        proof_file.write_text(json.dumps(proof,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('glb','packet-meta','packet-bin','tire-archive','output','proof'):
        parser.add_argument('--'+arg,required=True,type=Path)
    parser.add_argument('--apply',action='store_true',help='指定時だけ新規PRIVATE GLBと証明書を保存。通常はDRY RUN')
    parser.add_argument('--game-db-dimension-audit', type=Path,
                        help='研究用：署名済タイヤの幅・内外径をGameDB純正値に照合（描画変更なし）')
    parser.add_argument('--source-axis-role-research',action='store_true',
                        help='研究専用：元ModelBinのSpindleとglTFの左右座標系を照合しタイヤノードX反転を選択。既定OFF')
    parser.add_argument('--source-gamedb-tire-placement-research', action='store_true',
                        help='研究用: 元4輪GameDB配置の署名/座標一致時のみタイヤノードへ反映。既定OFF')
    parser.add_argument('--source-stock-wheel-tire-fitment', action='store_true',
                        help='一括原本取付け：寸法/Spindle/左右軸/GameDB配置を署名付きで検証。既定OFF（外観未承認）')
    args=parser.parse_args()
    report=build(args.glb,args.packet_meta,args.packet_bin,args.tire_archive,args.output,args.proof,apply=args.apply,source_gamedb_placement_research=args.source_gamedb_tire_placement_research,game_db_dimension_audit=args.game_db_dimension_audit,source_axis_role_research=args.source_axis_role_research,source_stock_wheel_tire_fitment=args.source_stock_wheel_tire_fitment)
    print('APPLY PASS' if args.apply else 'DRY RUN PASS')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
