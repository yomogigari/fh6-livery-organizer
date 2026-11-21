"""ローカルFH6原本ModelBinの描画用LOD0実メッシュを製品Viewerへ接続する。

元ゲームを読み取り専用で扱う。ソースModelBin、GameDB由来の寸法・座標、
元GLBの車輪同定が一致する場合だけ、ユーザーのPC内に非破壊の比較GLBを作る。
ゲームのMorph係数/Shaderが未証明のためXbox一致を主張しない。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import zipfile
from pathlib import Path, PurePath

import numpy as np

from . import wheel_morph_internal as wm
from .source_tire_glb_bridge import KEYS, REAR_FOR_MIDDLE, add_aligned, read_glb, wheel_centres, vertex_world_bounds
from .portable_mesh_converter import seal_firstparty_chassis_metadata

ORIGIN = 'local-FH6-ModelBin-dimensions-research-v1'
UV_ORIGIN = 'ModelBin/TEXCOORD_UNORM16_4channels_no_geometry_edit'
MAX_TIRE_ZIP_BYTES = 32 * 1024 * 1024
# UV0基準の独立解像度DIFF/OPAC合成へ変更したため旧プレビューキャッシュを再利用しない。
# WheelStyleのcar_automotive_paint Texture2D対応を既存未署名キャッシュから隔離する。
# PR68: 元GLBのWheelPaint shader最終色未合成フラグと原本材質ID署名の
# 追加を、旧v6の派生GLB（同じ元ModelBin/Materials/Shader）から隔離する。
# preview-cache全体の削除は不要。原本出典変更時は版付き派生GLBを生成する。
# Carbin XYZ実配置署名と原本非描画UV0ゲートを旧v7派生GLBから分離。
# 本人の元ゲームや既存JPEGは保持し、現在の派生GLBはv12へ隔離。
# 原本MaterialBin単位でWheelStyle Shader/XMLを選別する修正を、
# 古いfamily単位のShaderキャッシュで生成したv11 Wheel/Tire GLBと隔離する。
# 元の保存済みGLBは削除せず、正規入口からv12を再生成する。
# 元Tireの1/2/4形式とWheel取付け変換を反映したGLBは旧v12と混ぜない。
# 19: car_standard 系の原本ホイールの材質に色合い・金属度・粗さを付ける（_standard_wheel_surface）。
# 20: 原本の Texture を持たないカーボン等のホイールの部品に、材質の値から求めた色を付ける。
LOCAL_TIRE_CACHE_REVISION = 20
# 左右のタイヤの幅中心の対称の許容（X の和）。原本の Carbin のホイール位置が左右で少し非対称な車がある
# （FER_250GTO_64 の後輪は 13.1 mm）。この検査の目的は左右の取り違え（数十 cm の差）の検出なので、
# 原本由来の小さな非対称は許す（2026-11-18。以前は 1 cm で、この車のタイヤの準備が止まっていた）。
# 2026-11-18 の全車体の撮影：SUN_Imp_66 は GameDB の配置が安全上限で Carbin に戻り、Carbin の前輪が
# 左右で 4 cm 非対称（左 -0.708 m・右 +0.748 m）だった。取り違えの検出には十分小さいので 5 cm にする。
TIRE_CENTER_LATERAL_SYMMETRY_M = 0.05


class LocalTireSourceError(ValueError):
    """原本の出典・サイズ・形状のいずれかが曖昧なため描画を拒否する。"""


def _sha(raw: bytes) -> str:
    # 同じ bytes のオブジェクトの SHA は覚えた値を使う（bytes_memo、2026-11-21）
    from .bytes_memo import sha256_hex
    return sha256_hex(raw)


def _file_sha(path: Path) -> str:
    """ファイル全体の SHA-256。同じファイル（場所・大きさ・更新日時）のあいだ、プロセスで覚えて使い回す。

    タイヤの段階の鍵（local_tire_cache_paths）が、ペイントの差し替えのたびに車体の GLB（4212 で 33 MB）を
    読み直して SHA を求めていた（1 回 約 0.04 秒。2026-11-20）。ファイルが変われば大きさか更新日時が変わるので、
    求め直す。ファイルが無いときは覚えない（今までどおり読んで例外になる）。
    """
    from .process_file_memo import remembered
    target = Path(path)
    return remembered("whole-file-sha256", [target], (), lambda: _sha(target.read_bytes()), copy="none", limit=32)


def tire_archive_model_name(path: Path) -> str:
    """通常TireとR原本専用TireRのZIP型名を出典どおり区別する。"""
    stem = path.stem
    if stem.startswith("tireR_"):
        name = "R_" + stem[6:]
    elif stem.startswith("tire_"):
        name = stem[5:]
    else:
        raise LocalTireSourceError("Tire原本ZIP名が不正: " + path.name)
    if not name or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in name):
        raise LocalTireSourceError("Tire原本ZIP型名が不正")
    return name


def resolve_installed_tire_archive(game_folder: Path, model: str) -> Path:
    """原本のタイヤ ZIP の場所（中身は _resolve_installed_tire_archive_uncached）。

    同じプロセスの中で、同じゲームのフォルダー・同じモデル名・タイヤのフォルダーの更新日時（ファイルが増減すると変わる）
    なら、前の結果を使う（tire_input_memo。準備 1 件で 3 回、タイヤのフォルダーの全部の名前を見ていた）。
    """
    from .tire_input_memo import file_identity, remembered
    from .vehicle_assets import resolve_fh6_cars_dir
    try:
        folder = file_identity(Path(resolve_fh6_cars_dir(game_folder)) / '_library' / 'scene' / 'tires')
    except Exception:  # noqa: BLE001  場所を決められないときは覚えずに従来どおり探す（同じ理由で止まる）
        return _resolve_installed_tire_archive_uncached(game_folder, model)
    return remembered("resolve_installed_tire_archive", (folder, str(model)),
                      lambda: _resolve_installed_tire_archive_uncached(game_folder, model),
                      enabled=folder[1] is not None)

def _resolve_installed_tire_archive_uncached(game_folder: Path, model: str) -> Path:
    """FH6の原本参照先 _library/scene/tires から共有タイヤZIPを特定。"""
    if not model or any(c in model for c in '/\\:\0') or model in ('.', '..'):
        raise LocalTireSourceError('GameDB純正TireModelNameが不正')
    from .vehicle_assets import resolve_fh6_cars_dir
    root = resolve_fh6_cars_dir(game_folder)
    # 元Carbinの Game:/Media/Cars/_library/scene/tires を根拠とする。
    # 旧実装の _library/Tires は階層不足の誤パスだったため候補に含めない。
    scene_tires = root / '_library' / 'scene' / 'tires'
    # R_*は「元の右側専用TireRアーカイブ」の明示的な研究モデル名。
    # tire_R_*.zipを自動代用しない。GameDB Stock書換えも行わない。
    archive_name = 'tire'+model+'.zip' if model.startswith('R_') else 'tire_'+model+'.zip'
    matches = ([p for p in scene_tires.iterdir()
                if p.is_file() and p.name.casefold() == archive_name.casefold()]
               if scene_tires.is_dir() else [])
    # 同名の大文字小文字違いも曖昧さとして拒否する（Linux fixture/移植先も安全）。
    if len(matches) != 1:
        raise LocalTireSourceError(
            f'ゲーム原本タイヤZIPが一意に見つかりません: media/cars/_library/scene/tires/tire_{model}.zip。'
            '元のフォルダーを変更せず、インストール済みFH6の原本構成を確認してください。'
        )
    path = matches[0]
    if not 0 < path.stat().st_size <= MAX_TIRE_ZIP_BYTES:
        raise LocalTireSourceError('ゲーム原本タイヤZIPが不正サイズ')
    return path



def _original_tire_model_entries(archive: zipfile.ZipFile, model: str) -> dict[str, zipfile.ZipInfo]:
    """原本の1/2/4 ModelBinを署名付きsourceとして4輪へ結び付ける。

    原本が片側1個の場合も欠損ではない。同じTire sourceを各Wheelに
    指定し、座標変換のみ既存Wheel側の取付け回転に従う。
    """
    if not isinstance(model, str) or not model or any(
            ch in model for ch in ('/', chr(92), ':', chr(0))):
        raise LocalTireSourceError('原本タイヤ型名が不正')
    entries = [info for info in archive.infolist()
               if not info.is_dir() and info.filename.casefold().endswith('.modelbin')]
    index: dict[str, zipfile.ZipInfo] = {}
    for entry in entries:
        name = entry.filename
        if '/' in name or chr(92) in name or ':' in name:
            raise LocalTireSourceError('原本Tire ModelBinのZIP内部パスが未対応')
        key = name.casefold()
        if key in index:
            raise LocalTireSourceError('原本Tire ModelBin名が大小文字違いで重複')
        index[key] = entry
    if not index or len(index) > 4:
        raise LocalTireSourceError('原本Tire ModelBin件数が空または未対応の多重定義')
    keys = ('front_left', 'front_right', 'rear_left', 'rear_right')
    if model.startswith('R_'):
        # 右専用原本は実際のR側ModelBin 1個を保持。主撮影は右前輪のみ。
        right_name = ('tire'+model+'.modelbin').casefold()
        if len(index) != 1 or right_name not in index:
            raise LocalTireSourceError('右側専用TireRの元ModelBin名称・件数が不一致')
        return {role: index[right_name] for role in keys}
    corners = {
        'front_left': f'tireLF_{model}.modelbin',
        'front_right': f'tireRF_{model}.modelbin',
        'rear_left': f'tireLR_{model}.modelbin',
        'rear_right': f'tireRR_{model}.modelbin',
    }
    pairs = {'L': f'tireL_{model}.modelbin',
             'R': f'tireR_{model}.modelbin'}

    def matches(names: list[str]) -> bool:
        return all(name.casefold() in index for name in names)

    if len(index) == 4 and matches(list(corners.values())):
        return {role: index[name.casefold()] for role, name in corners.items()}
    if len(index) == 2 and matches(list(pairs.values())):
        return {role: index[pairs['L' if role.endswith('left') else 'R'].casefold()]
                for role in keys}
    # DUALLYの片側前後2本は、Wheelの実取付け回転で反対側へ配置する。
    if len(index) == 2:
        for side in ('left', 'right'):
            front, rear = corners['front_' + side], corners['rear_' + side]
            if matches([front, rear]):
                return {role: index[(front if role.startswith('front') else rear).casefold()]
                        for role in keys}
    # ZIP内に補助white/alternateがあれば、ModelName厳密一致を優先する。
    # 未選択ModelBin名はGLB証拠に明示し、黙ったデータ削除は行わない。
    if len(index) <= 2:
        for name in (*pairs.values(), f'tire_{model}.modelbin'):
            if name.casefold() in index:
                return {role: index[name.casefold()] for role in keys}
    if len(index) == 1:
        # 旧原本にはZIPの型名とModelBin名が異なる1個構成もある。
        only = next(iter(index.values()))
        return {role: only for role in keys}
    raise LocalTireSourceError(
        f'原本Tire {model!r} のModelBin役割が一意に判定できません'
        f' (ModelBin実数={len(entries)})。推測ModelBin代用は禁止'
    )


def _source_tire_side(member_name: str) -> str | None:
    """ModelBinのL/R命名から側を識別。無印は未特定のまま扱う。"""
    stem = member_name.casefold()
    if stem.startswith(('tirelf_', 'tirelr_', 'tirel_')):
        return 'L'
    if stem.startswith(('tirerf_', 'tirerr_', 'tirer_')):
        return 'R'
    return None


def _wheel_tire_source_to_role(
        positions: np.ndarray, source_member: str, role: str) -> tuple[np.ndarray, bool]:
    """原本の同一Tireを使い、反対側Wheelの180度Y回転を継承する。

    参照ツール carbin_importerのwheel transform X/Z反転→Tire set_transform
    と同じ剛体変換。Xのみの鏡像は原本側面文字が反転するため禁止。
    """
    side = _source_tire_side(source_member)
    target = 'L' if role.endswith('left') else 'R'
    if side is None or side == target:
        return positions, False
    adjusted = positions.copy()
    adjusted[:, 0] *= -1
    adjusted[:, 2] *= -1
    return adjusted, True


def _validated_assembly(contract: dict) -> tuple[str, dict[str, dict], dict[str, np.ndarray]]:
    assembly = contract.get('assembly')
    if not isinstance(assembly, dict) or assembly.get('format') != 'lo4fh6_local_vehicle_assembly_v2':
        raise LocalTireSourceError('FH6原本GameDB由来の車輪アセンブリが不足')
    model = assembly.get('tire_model_name')
    if not isinstance(model, str) or not model:
        raise LocalTireSourceError('原本タイヤ型名が不足')
    dims = assembly.get('wheel_dimensions')
    centers = assembly.get('wheel_centers')
    if not isinstance(dims, dict) or not isinstance(centers, dict) or set(KEYS)-set(dims) or set(KEYS)-set(centers):
        raise LocalTireSourceError('4輪の原本GameDB寸法・位置が不足')
    truth = {}
    points = {}
    for role in KEYS:
        item = dims[role]
        if not isinstance(item, dict): raise LocalTireSourceError('タイヤサイズが不正')
        width = item.get('tire_width'); rim=item.get('rim_radius'); radius=item.get('tire_radius')
        if not all(type(v) in (float,int) and math.isfinite(v) for v in (width,rim,radius)):
            raise LocalTireSourceError('タイヤ寸法NaN/型不正')
        if not (0.0 < width < .6 and 0.0 < rim < .6 and rim < radius < 1.0):
            raise LocalTireSourceError('GameDB純正タイヤ寸法が範囲外')
        pos = centers[role]
        if not isinstance(pos,(list,tuple)) or len(pos)!=3 or not all(type(v) in (float,int) and math.isfinite(v) and abs(v)<30 for v in pos):
            raise LocalTireSourceError('GameDB車軸中心が不正')
        points[role]=np.asarray(pos,dtype=np.float64)
        truth[role]={'width':float(width),'inner':float(rim),'outer':float(radius)}
    for axle in ('front','rear'):
        l,r = axle+'_left',axle+'_right'
        if any(abs(truth[l][k]-truth[r][k])>1e-5 for k in ('width','inner','outer')):
            raise LocalTireSourceError('左右のGameDB純正寸法が一致しません')
        # 左右の X（車幅の方向）は 5 cm まで許す。GameDB の配置が安全上限で Carbin に戻った車では、原本の
        # Carbin の左右の非対称がそのまま残る（2026-11-18：SUN_Imp_66 の前輪は左 -0.708 m・右 +0.748 m）。
        # タイヤは車輪ごとの中心に置くため、X の非対称は配置に影響しない。高さ・前後（Y・Z）は 2 cm のまま。
        # 3 輪・6 輪の車（GameDB の配置で前後を Carbin のまま保ったもの）は、無い側の角が GameDB の値のまま
        # 残るため、ここでは比べない。ある車輪どうしの左右の対称は _validate_original_wheels で確かめる。
        if (assembly.get('wheel_centers_source') != NON_FOUR_WHEEL_CENTERS_SOURCE
                and (abs(points[l][0]+points[r][0])>AXLE_CENTER_X_SYMMETRY_TOLERANCE_M
                     or np.linalg.norm(points[l][1:]-points[r][1:])>0.02)):
            raise LocalTireSourceError('左右のGameDB車軸中心が一致しません')
    return model, truth, points


def _original_tire_lod0_mesh_blobs(blobs: list) -> list:
    """原本ModelBinの描画用LOD0。影専用LODSとは分離する。

    通常名 _LOD0 と、従来の成功原本で使う互換名 _LODS0 は別々に扱う。
    両方が存在するときは無断統合・選択せず安全停止する。
    """
    # FH6原本の一部はLOD0名末尾へ |AndOthers を付けている。
    # 末尾Tokenの任意除去は誤LOD選択になるためこの実原本Tokenだけを認可。
    # LOD0名称だけでなくMeshバイナリのLOD0フラグ(bit1)も必ず照合する。
    def source_lod0_role(blob):
        if blob.tag != wm._TAG_MESH:
            return None
        name = blob.name
        if name.endswith('|AndOthers'):
            name = name[:-len('|AndOthers')]
        if name.endswith('_LOD0'):
            return 'detailed'
        if name.endswith('_LODS0'):
            return 'compatible'
        return None

    candidates = [(b, source_lod0_role(b)) for b in blobs]
    detailed = [b for b, role in candidates if role == 'detailed']
    compatible = [b for b, role in candidates if role == 'compatible']
    if detailed and compatible:
        raise LocalTireSourceError('原本タイヤLOD0に二つの異なる描画用命名規約が混在')
    chosen = detailed or compatible
    # 名前だけが一致してもLOD1/影Passを採用しない。符号付き原本MeshのLOD0を要求。
    for blob in chosen:
        data = getattr(blob, 'data', None)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            # 名称だけの合成fixture。本番はwm._parse_blobsが実Mesh dataを提供。
            continue
        parsed = wm._parse_mesh(blob)
        if parsed.index_count <= 0:
            raise LocalTireSourceError('原本Tire LOD0描画Indexが空')
        # Mesh v1.12/1.13で、MaterialGroup直後のrigid bone2byteに続くLOD flag。
        offset = 4 + 8 * struct.unpack_from('<i', data, 0)[0] if (blob.major, blob.minor) >= (1, 13) else 8
        if offset + 4 > len(data) or not (struct.unpack_from('<H', data, offset + 2)[0] & 2):
            raise LocalTireSourceError('原本Tire LOD0名称とMesh LODフラグが不一致')
    if not chosen:
        raise LocalTireSourceError('原本LOD0タイヤメッシュが欠けています')
    return chosen


def _verify_tire_morph_slot_provenance(records: np.ndarray, *, meshblob_index: int,
                                        vertex_offset: int, stride: int) -> np.ndarray:
    """原本5chの識別値(0～4)で実頂点ごとのMorph配列順を確定する。

    元ModelBinには [4,3,2,1,0] と [3,4,2,1,0] の両配置が実在。
    固定逆順で並べると後者の3/4 Morphが入れ替わり、原本Tireを誤拒否・
    誤変形する。各頂点の識別値を照合し、重複/欠落/不明を安全停止する。
    """
    if records.ndim != 3 or records.shape[1:] != (5, 4) or not np.isfinite(records).all():
        raise LocalTireSourceError(
            f'ModelBin Morphチャンネルの出典が不明: MeshBlob={meshblob_index} '
            f'MBUFstride={stride} 非有限値または5ch構造不一致')
    identifiers = records[:, :, 3]
    valid = (identifiers >= 0) & (identifiers <= 4) & (identifiers == np.floor(identifiers))
    invalid = np.argwhere(~valid)
    if len(invalid):
        vertex, slot = (int(v) for v in invalid[0])
        raise LocalTireSourceError(
            f'ModelBin Morphチャンネルの出典が不明: MeshBlob={meshblob_index} '
            f'MBUFstride={stride} VertexIndex={vertex_offset + vertex} Slot={slot} '
            f'観測={identifiers[vertex].tolist()} 期待=重複なしの0～4')
    order = np.argsort(identifiers, axis=1)
    sorted_ids = np.take_along_axis(identifiers, order, axis=1)
    mismatch = np.argwhere(sorted_ids != np.arange(5, dtype=np.float64)[None, :])
    if len(mismatch):
        vertex, channel = (int(v) for v in mismatch[0])
        slot = int(order[vertex, channel])
        raise LocalTireSourceError(
            f'ModelBin Morphチャンネルの出典が不明: MeshBlob={meshblob_index} '
            f'MBUFstride={stride} VertexIndex={vertex_offset + vertex} Slot={slot} '
            f'観測={identifiers[vertex].tolist()} 期待=0～4全件一意')
    return order



def original_static_tire_lod0_proof(raw: bytes) -> dict | None:
    """元Morph=0/MBuf無しの実LOD0を原本署名。描画用ダミーMorphは生成しない。

    通常5chソースの変換・材質に触れず、静的タイヤは研究未接続として
    元ModelBinのLOD flag/Index/MaterialIDだけを確認する。
    """
    blobs = wm._parse_blobs(raw)
    if any(b.tag == wm._TAG_MBUF for b in blobs):
        return None
    lod0 = _original_tire_lod0_mesh_blobs(blobs)
    mat_ids = {int(b.identifier) for b in blobs
               if b.tag == 0x4d617449 and b.identifier is not None}
    if not mat_ids:
        raise LocalTireSourceError('静的Tire原本のMatI出典が欠けています')
    rows = []
    for blob in lod0:
        mesh = wm._parse_mesh(blob)
        if mesh.morph_count != 0:
            return None
        if mesh.index_count <= 0 or mesh.material_id not in mat_ids:
            raise LocalTireSourceError('静的Tire原本のLOD0 Index/MatI参照が不一致')
        rows.append({
            'meshblob_index': int(blob.index),
            'material_id': int(mesh.material_id),
            'index_count': int(mesh.index_count),
        })
    if not rows or len(rows) != len({item['meshblob_index'] for item in rows}):
        raise LocalTireSourceError('静的Tire原本LOD0が不足または重複')
    return {
        'schema': 'lo4fh6.original-static-tire-lod0-provenance.v1',
        'modelbin_sha256': _sha(raw),
        'source_lod0_mesh_count': len(rows),
        'source_lod0_meshes': rows,
        'morph_count': 0,
        'has_morph_buffer': False,
        'dimension_fitment_proven': False,
        'shader_equivalent': False,
        'xbox_appearance_approved': False,
    }


# 元のタイヤの形の読み取りの結果（ModelBin の中身の SHA-256 → 結果）。準備 1 回で同じタイヤを 3 つの段階が
# 4 回ずつ読んでいた（初めての車で 14 回）。結果は ModelBin の中身だけで決まる（side は使わない）ので、
# 1 回だけ読んで覚え、呼ばれるたびに配列の写しを返す（呼び出し側が書き換えても覚えた値は変わらない。2026-11-20）。
_SOURCE_MESH_MEMO: dict[bytes, list[dict]] = {}
_SOURCE_MESH_MEMO_LIMIT = 8


def _load_source_meshes(raw: bytes, side: str):
    """ModelBinの既存第一者デコーダーを共有し、LOD0の実索引・4UV・5Morphのみ読む。"""
    key = hashlib.sha256(raw).digest()
    found = _SOURCE_MESH_MEMO.get(key)
    if found is None:
        found = _load_source_meshes_uncached(raw)
        while len(_SOURCE_MESH_MEMO) >= _SOURCE_MESH_MEMO_LIMIT:
            _SOURCE_MESH_MEMO.pop(next(iter(_SOURCE_MESH_MEMO)))
        _SOURCE_MESH_MEMO[key] = found
    return [{name: (value.copy() if isinstance(value, np.ndarray) else value) for name, value in item.items()}
            for item in found]


def _load_source_meshes_uncached(raw: bytes):
    blobs=wm._parse_blobs(raw)
    indices = [wm._parse_buffer(b) for b in blobs if b.tag==wm._TAG_INDB]
    if len(indices)!=1: raise LocalTireSourceError('原本Tire IndBが一意でありません')
    by_layout={int(b.identifier):wm._parse_layout(b) for b in blobs if b.tag in (wm._TAG_VLAY,wm._TAG_ILAY) and b.identifier is not None}
    all_layouts=[wm._parse_layout(b) for b in blobs if b.tag in (wm._TAG_VLAY,wm._TAG_ILAY)]
    vb={int(b.identifier):wm._parse_buffer(b) for b in blobs if b.tag==wm._TAG_VERB and b.identifier is not None}
    mbuf=[wm._parse_buffer(b) for b in blobs if b.tag==wm._TAG_MBUF]
    if len(mbuf)!=1 or mbuf[0].fmt!=10 or mbuf[0].stride!=80:
        # 実ModelBinの形を推測して読まず、個数/形式/stride/バイト数を記録する。
        # 原本データ自体をレポートへ出力しない。入力からの決め打ち補正も禁止。
        received = [(entry.fmt, entry.stride, len(entry.raw)) for entry in mbuf]
        raise LocalTireSourceError(
            '元タイヤ5ch Morphの原本レイアウト不一致'
            f' / MBUF件数={len(mbuf)} / (format,stride,bytes)={received}')
    result=[]
    for blob in _original_tire_lod0_mesh_blobs(blobs):
        mesh=wm._parse_mesh(blob)
        if mesh.morph_count!=5 or mesh.is_morph_damage:raise LocalTireSourceError('元タイヤMorphの意味が未解析')
        layout=by_layout.get(mesh.vertex_layout_index)
        if layout is None and 0<=mesh.vertex_layout_index<len(all_layouts):layout=all_layouts[mesh.vertex_layout_index]
        if not layout:raise LocalTireSourceError('元タイヤ頂点layoutなし')
        pos=next((e for e in layout if e.semantic=='POSITION' and e.fmt==13),None)
        uv=[next((e for e in layout if e.semantic=='TEXCOORD' and e.semantic_index==i and e.fmt==35),None) for i in range(4)]
        # 元TireのNORMAL.RG(SNORM16)はPOSITION.WをX成分として使用する。
        # 原本LOD0のNormalを三角形の平均面法線で置換しない。
        normal=next((e for e in layout if e.semantic=='NORMAL'
                     and e.semantic_index==0 and e.fmt==37), None)
        if pos is None or normal is None or any(x is None for x in uv):
            raise LocalTireSourceError('原本POSITION/NORMAL/UV0〜3が未解決')
        global_indices=wm._read_indices(indices[0],mesh)
        lo=int(global_indices.min());hi=int(global_indices.max());n=hi-lo+1
        if n<3 or n>65535 or len(global_indices)%3:raise LocalTireSourceError('原本タイヤ頂点・三角形が不正')
        ids=(global_indices-lo).astype('<u2')
        pp=np.empty((n,3),dtype=np.float64)
        source_normal_x=np.empty(n,dtype=np.int16)
        # 頂点ごとに Python で読んでいた値を、同じ式・同じ順でまとめて求める（2026-11-20。結果は同じ）。
        packed_positions=wm._vertex_array(blobs,vb,mesh,pos,lo,n)
        if packed_positions is not None:
            pp[:]=packed_positions[:,:3].astype(np.float64)/32767.0*\
                np.asarray(mesh.position_scale[:3])+np.asarray(mesh.position_translate[:3],dtype=np.float64)
            source_normal_x[:]=packed_positions[:,3]
        else:
            for i,b in enumerate(wm._read_vertex_components(blobs,vb,mesh,pos,lo,n)):
                packed=struct.unpack_from('<hhhh',b,0)
                pp[i]=np.asarray(packed[:3],dtype=np.float64)/32767.0*\
                    np.asarray(mesh.position_scale[:3])+mesh.position_translate[:3]
                source_normal_x[i]=packed[3]
        pp[:,2]*=-1 # 原本ModelBin/GLB座標規約（既存デコーダーと同じ）
        source_normal_yz=np.empty((n,2),dtype=np.int16)
        packed_normals=wm._vertex_array(blobs,vb,mesh,normal,lo,n)
        if packed_normals is not None:
            source_normal_yz[:]=packed_normals
        else:
            for i,b in enumerate(wm._read_vertex_components(blobs,vb,mesh,normal,lo,n)):
                source_normal_yz[i]=struct.unpack_from('<hh',b,0)
        source_normals=_original_tire_normals_from_packed(source_normal_x,source_normal_yz)
        coords=np.empty((n,4,2),dtype=np.float32)
        for ch,elem in enumerate(uv):
            packed_uv=wm._vertex_array(blobs,vb,mesh,elem,lo,n)
            if packed_uv is not None:
                coords[:,ch]=packed_uv.astype(np.float64)/65535.0
            else:
                for i,b in enumerate(wm._read_vertex_components(blobs,vb,mesh,elem,lo,n)):
                    coords[i,ch]=np.asarray(struct.unpack_from('<HH',b,0),dtype=np.float64)/65535.0
        first=lo+mesh.indexed_vertex_offset
        m=mbuf[0]
        if first<0 or (first+n)*m.stride>len(m.raw):raise LocalTireSourceError('原本Morph頂点offset外')
        # 元MBuf stride80 = positionの5xRGBA16F(40B) + normalの5xRGBA16F(40B)。
        # 他プロダクトも両方の5chを読み、原本IDで同じMorph係数を適用する。
        # 原本が現在normal delta=0でも、次のゲーム資産で非ゼロなら黙って省略しない。
        records=np.ndarray(shape=(n,5,4),dtype='<f2',buffer=m.raw,
                           offset=first*m.stride,strides=(m.stride,8,2)).astype(np.float64)
        normal_records=np.ndarray(shape=(n,5,4),dtype='<f2',buffer=m.raw,
                                  offset=first*m.stride+40,strides=(m.stride,8,2)).astype(np.float64)
        source_morph_order = _verify_tire_morph_slot_provenance(
            records, meshblob_index=int(blob.index), vertex_offset=first, stride=m.stride)
        normal_morph_order = _verify_tire_morph_slot_provenance(
            normal_records, meshblob_index=int(blob.index), vertex_offset=first, stride=m.stride)
        # 原本の各レコードが実ID0～4を持つ。位置/法線は独立のID並びで復元。
        delta=np.take_along_axis(records[:,:,:3],source_morph_order[:,:,None],axis=1).copy()
        normal_delta=np.take_along_axis(
            normal_records[:,:,:3],normal_morph_order[:,:,None],axis=1).copy()
        delta[:,:,2]*=-1
        normal_delta[:,:,2]*=-1
        # ModelBinの元三角形をglTFへ座標変換する際だけwindを反転する。
        face=ids.reshape(-1,3).copy();face[:,[1,2]]=face[:,[2,1]]
        result.append({'name':mesh.name+'__tag-'+format(blob.index,'04x')+'__mesh-'+str(blob.index),
            'meshblob_index': int(blob.index),
            'positions':pp,'source_normals':source_normals,'uv':coords,'delta':delta,
            'normal_delta':normal_delta,'indices':face.reshape(-1),
            'material_id':mesh.material_id,'material_name':next((b.name for b in blobs if b.tag==0x4d617449 and b.identifier==mesh.material_id),'')})
    if not result:
        raise LocalTireSourceError('原本LOD0タイヤメッシュが欠けています')
    return result


# 目標の寸法がMorphの重み0〜1で届かないときだけ、重みをこの幅まで範囲外へ延ばして解く。
# 2026-11-17：HON_N600_70（10インチ）は「Road」Tireのビード半径の下限0.140mに届かず停止していた。
# 参照ツール（参照のみ）の式（リムの重み=(リム径-10)/14等）でも、10インチは
# Morphの端（重み0）でビード半径0.140mとなり、小径リムでは範囲の端に当たる。線形Morphの延長は小さく限定する。
# 2026-11-18：MER_Unimog_17（395/85 R20、外径の半径 0.590 m）は外径の重みが 1.25 を超えて停止していた。
# 参照ツールの式（タイヤの重み=(幅×偏平率/100-225+リム径×12.7)/275）では 1.326 で、ゲームも同じ線形の
# Morphを 1 を超えて使う。GameDB の全車の純正タイヤの式の値は、タイヤ -0.293（3 輪の PEE_P50_62）〜1.326、
# リム（(リム径-10)/14）-0.357（PEE_P50_62 の 5 インチ）〜1.0。ただし寸法に合わせて解く重みは式の値と少し違い、
# PEE_P50_62（Vintage_Race、90/90 R5、ビード半径 0.0635 m・外径の半径 0.1445 m）は、ビードに約 -0.42、
# 外径に約 -0.6 が要る。全車が解ける ±0.70 にする（以前の範囲で解けた車の結果は変わらない。2026-11-18 に
# 3 輪の車を扱うため 0.35 から広げた）。
TIRE_MORPH_WEIGHT_EXTRAPOLATION = 0.70
AXLE_CENTER_X_SYMMETRY_TOLERANCE_M = TIRE_CENTER_LATERAL_SYMMETRY_M


def _morph_weight_bracket(value_at, target: float) -> tuple[float, float] | None:
    """目標を挟む重みの区間。通常は[0,1]、範囲外のときだけ±TIRE_MORPH_WEIGHT_EXTRAPOLATIONまで。"""
    ext = TIRE_MORPH_WEIGHT_EXTRAPOLATION
    if value_at(0.) <= target <= value_at(1.):
        return 0., 1.
    if value_at(-ext) <= target < value_at(0.):
        return -ext, 0.
    if value_at(1.) < target <= value_at(1. + ext):
        return 1., 1. + ext
    return None


def _source_morph_profile(meshes: list[dict],dim:dict) -> tuple[list[np.ndarray],dict]:
    p=np.concatenate([x['positions'] for x in meshes]); d=np.concatenate([x['delta'] for x in meshes]);
    if len(p)!=len(d): raise LocalTireSourceError('Morph頂点参照の不整合')
    target_inner,target_outer=dim['inner'],dim['outer']
    def profile(a,b):
        v=p+d[:,0,:]*a+d[:,1,:]*b
        rr=np.hypot(v[:,1],v[:,2]);return float(np.min(rr)),float(np.max(rr))
    a,b=.3,.5
    for _ in range(5):
        bracket=_morph_weight_bracket(lambda w: profile(a,w)[0], target_inner)
        if bracket is None:raise LocalTireSourceError('原本MorphでGameDBビード径を再現できません')
        lo,hi=bracket
        for _ in range(24):
            mid=(lo+hi)/2
            if profile(a,mid)[0]<target_inner:lo=mid
            else:hi=mid
        b=(lo+hi)/2
        bracket=_morph_weight_bracket(lambda w: profile(w,b)[1], target_outer)
        if bracket is None:raise LocalTireSourceError('原本MorphでGameDBタイヤ外径を再現できません')
        lo,hi=bracket
        for _ in range(24):
            mid=(lo+hi)/2
            if profile(mid,b)[1]<target_outer:lo=mid
            else:hi=mid
        a=(lo+hi)/2
    adjusted=p+d[:,0,:]*a+d[:,1,:]*b
    rin,rout=profile(a,b)
    if max(abs(rin-target_inner),abs(rout-target_outer))>.00015:
        raise LocalTireSourceError('タイヤMorph寸法の残差が過大')
    bead_x=adjusted[np.abs(np.hypot(adjusted[:,1],adjusted[:,2])-target_inner)<.005,0]
    if len(bead_x)<100:raise LocalTireSourceError('ビード元形状が欠落')
    low,high=float(bead_x.min()),float(bead_x.max())
    if not .9<high-low<1.1:raise LocalTireSourceError('元タイヤビード座幅が未確認')
    adjusted[:,0]=(adjusted[:,0]-(low+high)/2)*(dim['width']/(high-low))
    # ビード座で実測した幅を使い、元ModelBinのトレッドと側面の非対称な
    # 原本外形を維持する。全外形AABBの左右対称は原本タイヤの必要条件ではない。
    # 形状を中央へ追加移動したり頂点を切り落としたりしない。
    source_axial_min=float(adjusted[:,0].min())
    source_axial_max=float(adjusted[:,0].max())
    if not (math.isfinite(source_axial_min) and math.isfinite(source_axial_max)):
        raise LocalTireSourceError('原本タイヤMorph後の外形が非有限')
    output=[];start=0
    for mesh in meshes:
        n=len(mesh['positions']);output.append(adjusted[start:start+n].copy().astype('<f4'));start+=n
    return output, {'profile_weights_research_only':[float(a),float(b)],'source_bead_span_m':float(high-low),
        'nominal_width_m':dim['width'],'nominal_inner_m':target_inner,'nominal_outer_m':target_outer,
        'source_axial_envelope_m':[source_axial_min,source_axial_max],
        'source_axial_envelope_asymmetry_m':source_axial_min+source_axial_max,
        'game_morph_weights_proven':False}


def _morphed_tire_source_normals(source_normals: np.ndarray, normal_delta: np.ndarray,
                                 weights: list[float], axial_scale: float) -> np.ndarray:
    """元MBufの法線5chと、タイヤ幅のX拡縮に対する逆転置行列を適用。

    ModelBinの実Normal XYZとMorphの5ch実IDは既存デコーダーから取得。
    補間係数は位置Morphと同じものだけを使い、推測の法線再計算はしない。
    """
    base=np.asarray(source_normals,dtype=np.float64)
    changes=np.asarray(normal_delta,dtype=np.float64)
    weight=np.asarray(weights,dtype=np.float64)
    if (base.ndim!=2 or base.shape[1]!=3 or changes.shape!=(len(base),5,3)
            or weight.shape!=(5,) or len(base)==0 or not np.isfinite(base).all()
            or not np.isfinite(changes).all() or not np.isfinite(weight).all()
            # 寸法合わせで範囲外へ延ばした重み（±TIRE_MORPH_WEIGHT_EXTRAPOLATION）と同じ範囲を受け付ける。
            or np.any(weight<-TIRE_MORPH_WEIGHT_EXTRAPOLATION)
            or np.any(weight>1+TIRE_MORPH_WEIGHT_EXTRAPOLATION)
            or not math.isfinite(axial_scale) or axial_scale<=0):
        raise LocalTireSourceError('元タイヤMorph法線/幅スケールの出典が不正')
    blended=base+np.einsum('nci,c->ni',changes,weight)
    # 位置変換 X *= axial_scale に対し法線は X /= axial_scale。
    blended[:,0] /= axial_scale
    length=np.linalg.norm(blended,axis=1)
    if not np.isfinite(length).all() or np.any(length<1.e-8):
        raise LocalTireSourceError('元タイヤMorph後の法線が零/非有限')
    return (blended/length[:,None]).astype('<f4')


def _original_tire_normals_from_packed(source_w:np.ndarray,source_yz:np.ndarray)->np.ndarray:
    """原本VLayのPOSITION.WとNORMAL.RG(SNORM16)からXYZを復号する。

    ModelBin→GLBのZ軸反転だけを適用。元頂点Normalを面平均で再生成しない。
    """
    x=np.asarray(source_w,dtype=np.float64)
    yz=np.asarray(source_yz,dtype=np.float64)
    if x.ndim!=1 or yz.shape!=(len(x),2) or len(x)==0:
        raise LocalTireSourceError('元Tire NORMALの頂点・チャンネル数が不一致')
    normals=np.column_stack((x,yz))/32767.0
    normals[:,2]*=-1
    lengths=np.linalg.norm(normals,axis=1)
    if not np.isfinite(normals).all() or not np.isfinite(lengths).all() or np.any(lengths<1.e-8):
        raise LocalTireSourceError('原本Tire NORMALが非有限または零ベクトル')
    return (normals/lengths[:,None]).astype('<f4')



# 契約の車輪中心が、GameDB配置の安全上限で取りやめになった後のcarbinの車軸位置であることを示す値
# （vehicle-preview が assembly.wheel_centers_source に入れる）。
CARBIN_AXIS_AFTER_PLACEMENT_GUARD = 'carbin-wheelstyle-after-gamedb-placement-guard'
# 3 輪・6 輪の車で、GameDB の配置の X・Y と Carbin の Z（前後）を使った車輪の中心（vehicle-preview）。
NON_FOUR_WHEEL_CENTERS_SOURCE = 'gamedb-xy-carbin-z-non-four-wheel'


def _verified_carbin_wheel_yz(doc: dict, role: str, hub: np.ndarray, *, carbin_axis: bool = False):
    """Carbinの原本Bone行列＋署名付きGameDB配置から車軸Y/Zだけを検証する。

    WheelStyleの描画用Meshはblur/装飾面を含むため、そのAABB中心は
    物理的な車軸とは限らない。原本Carbin行列を再解釈して新たに配置せず、
    先行する第一者Morph Stageが保存した**実適用済み**移動量を厳格照合する。
    一部Meshだけの証拠や大きな移動は安全停止する。
    """
    rows = []
    total = 0
    for mesh in doc.get('meshes', []):
        if not isinstance(mesh, dict):
            continue
        ex = mesh.get('extras')
        if not isinstance(ex, dict) or ex.get('lo4_part_type') != 'WheelStyle':
            continue
        if ex.get('lo4_wheel_morph_wheel') != role or not str(
                ex.get('lo4_wheel_morph_source', '')).startswith('internal-modelbin-'):
            continue
        total += 1
        source = ex.get('lo4_wheel_gamedb_placement_source')
        if source is None and carbin_axis:
            # GameDBの移動が安全上限で取りやめになり、ホイールはcarbinの位置のまま。契約の車軸も
            # carbinの位置なので、Carbin取付け行列の位置（X反転のみ）と厳密に一致することを確認する。
            parsed = wm._parse_carbin_instance_identity(ex.get('lo4_instance_identity'))
            if parsed is None:
                raise LocalTireSourceError('原本WheelStyleのCarbin取付け情報が不足')
            authored = np.asarray(parsed['translation_fh6'], dtype=np.float64)
            if authored.shape != (3,) or not np.isfinite(authored).all():
                raise LocalTireSourceError('原本Carbinの車軸位置が不正')
            if float(np.linalg.norm(authored - hub)) > 0.0025:
                raise LocalTireSourceError('原本Carbin車軸と安全上限後の車輪中心が不一致')
            rows.append((str(parsed['identity']), (authored * np.asarray([-1., 1., 1.]))[1:]))
            continue
        if source is None:
            continue  # 旧GLBは従来AABBゲートを維持（混在は禁止）
        parsed = wm._parse_carbin_instance_identity(ex.get('lo4_instance_identity'))
        delta = ex.get('lo4_wheel_gamedb_placement_translation_glb')
        if (source != 'local-fh6-gamedb'
                or type(ex.get('lo4_wheel_gamedb_placement_revision')) is not int
                or ex['lo4_wheel_gamedb_placement_revision'] < 1
                or parsed is None
                or ex.get('lo4_wheel_gamedb_placement_source_wheel') != parsed.get('wheel')
                or ex.get('lo4_wheel_gamedb_placement_wheel') != role
                or not isinstance(delta, list) or len(delta) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in delta)):
            raise LocalTireSourceError('元WheelStyleのCarbin/GameDB配置署名が不一致')
        shift = np.asarray(delta, dtype=np.float64)
        if float(np.linalg.norm(shift)) > wm.WHEEL_GAMEDB_PLACEMENT_MAX_SAFE_SHIFT_M + 1e-6:
            raise LocalTireSourceError('元WheelStyleのGameDB配置移動量が安全閾値を超えています')
        authored = np.asarray(parsed['translation_fh6'], dtype=np.float64)
        if authored.shape != (3,) or not np.isfinite(authored).all():
            raise LocalTireSourceError('原本Carbinの車軸位置が不正')
        # 既存Converterと同じFH6→GLBのX反転規約も検証。
        # GameDBのXはハブ位置でありタイヤ幅中心ではないが、
        # Carbin取付け行列＋先に適用済みの剛体移動はGameDBハブXYZに厳密一致する。
        mapped_glb = authored * np.asarray([-1., 1., 1.]) + shift
        target_glb = hub * np.asarray([-1., 1., 1.])
        if float(np.linalg.norm(mapped_glb - target_glb)) > 0.0025:
            raise LocalTireSourceError('原本Carbin変換済み車軸とGameDB XYZが不一致')
        rows.append((str(parsed['identity']), mapped_glb[1:]))
    if not rows:
        return None
    if len(rows) < 2 or len(rows) != total or len({x[0] for x in rows}) != 1:
        raise LocalTireSourceError('原本WheelStyleのCarbin/GameDB配置証拠が一意・完全ではありません')
    if any(float(np.linalg.norm(yz - rows[0][1])) > 1e-5 for _, yz in rows[1:]):
        raise LocalTireSourceError('原本WheelStyleの車軸Y/Zに複数の候補')
    if carbin_axis:
        return {'source': 'original-Carbin-float32-instance-after-GameDB-placement-guard',
                'source_meshes': len(rows),
                'source_yz_m': [float(x) for x in rows[0][1]],
                'source_yz_matches_gamedb': False}
    return {'source': 'original-Carbin-float32-instance-plus-validated-GameDB-rigid-shift',
            'source_meshes': len(rows),
            'source_yz_m': [float(x) for x in rows[0][1]],
            'source_yz_matches_gamedb': True}


def _validate_original_wheels(doc:dict, geo:bytearray, axis:dict,
                              dimensions:dict, *, carbin_axis: bool = False) -> tuple[dict[str,np.ndarray],dict]:
    """元WheelStyle実形状とGameDB車軸基準を照合して原本タイヤ中心を選ぶ。

    GameDBのwheel_centers Xはハブの取付け面側であり、タイヤの**幅中心**とは限らない。
    以前の実装はそのXをそのままタイヤ中心にしたため、Jaguarで約12–13cm外へ張り出した。
    原本WheelStyleのバウンディングX中央を使用する。リムの軸方向幅は
    タイヤの公称幅とは別の原本量であり、等幅性を必須としない。
    不一致時は原本ModelBin Morph＋Carbin配置の署名を完全照合し、
    証拠欠落・混在・左右非対称の場合は従来どおり安全停止する。
    """
    centers=wheel_centres(doc,geo)
    roles=tuple(centers)
    # 中央の車輪（6 輪の車）の車軸の基準：X・Y は同じ側の後輪の GameDB の値、Z（前後）は自分の形の中心。
    axis=dict(axis)
    for role in roles:
        if role in REAR_FOR_MIDDLE:
            rear=np.asarray(axis[REAR_FOR_MIDDLE[role]],dtype=np.float64)
            axis[role]=np.asarray([rear[0],rear[1],float(centers[role][2])],dtype=np.float64)
            dimensions[role]=dimensions[REAR_FOR_MIDDLE[role]]
    # 片側にしか車輪が無い車軸（3 輪の車の 1 輪）は、中心が車の中央（X ≈ 0）になる。
    def axle_of(role):
        return role.split('_')[0]
    single_axles={axle_of(role) for role in roles
                  if sum(1 for other in roles if axle_of(other)==axle_of(role))==1}
    grouped={role:[] for role in roles}
    for node in doc.get('nodes',[]):
        if 'mesh' not in node:continue
        mesh=doc['meshes'][node['mesh']]
        ex=mesh.get('extras',{})
        role=ex.get('lo4_wheel_morph_wheel')
        if (ex.get('lo4_part_type')!='WheelStyle' or role not in grouped
                or not str(ex.get('lo4_wheel_morph_source','')).startswith('internal-modelbin-')):
            continue
        grouped[role].append(vertex_world_bounds(doc,geo,node,mesh))
    results={};basis={};signs=[]
    for role in roles:
        wheel=centers[role];hub=axis[role];part=grouped[role]
        if len(part)<2 or role not in dimensions:
            raise LocalTireSourceError('元WheelStyle実形状/幅出典が不足')
        wheel_geometry_yz_error = float(np.linalg.norm(wheel[1:]-hub[1:]))
        wheel_axis_proof = None
        if wheel_geometry_yz_error > .06:
            # 装飾用/BlurメッシュのAABB中心を車軸中心に誤用しない。
            # 署名済みCarbin行列＋適用済みGameDB移動の完全一致がある場合だけ通す。
            wheel_axis_proof = _verified_carbin_wheel_yz(doc, role, hub, carbin_axis=carbin_axis)
            if wheel_axis_proof is None:
                raise LocalTireSourceError('GameDBと元WheelStyleのY/Z中心が一致しない')
        # GameDB の車軸の X はハブの外側の面で、ホイールの形の中心はタイヤの幅のおよそ半分だけ内側にある。
        # 2026-11-18：FOR_F450DRWFE_20 の後ろのダブルタイヤ（幅 535 mm）は差が 0.267 m で、0.23 m を超えていた。
        # 普通の車は従来どおり 0.23 m（タイヤの幅の半分 + 0.03 m が 0.23 m を超える車だけ広げる）。
        x_limit = max(.23, float(dimensions[role]['width']) / 2 + .03)
        if abs(abs(wheel[0])-abs(hub[0]))>x_limit:
            raise LocalTireSourceError('GameDBと元WheelStyleのX基準が一致しない')
        if axle_of(role) in single_axles:
            # 1 輪の車軸は車の中央にあり、左右の向きの検査をしない（GameDB の車幅がタイヤの幅とほぼ同じ）。
            if abs(hub[0])>.10 or abs(wheel[0])>.10:
                raise LocalTireSourceError('1輪の車軸の中心が車の中央にありません')
        else:
            if abs(hub[0])<.05 or abs(wheel[0])<.05:
                raise LocalTireSourceError('原本車輪X軸が未確定')
            signs.append(int(math.copysign(1,wheel[0]*hub[0])))
        low=min(float(bounds[0][0]) for bounds in part)
        high=max(float(bounds[1][0]) for bounds in part)
        actual_width=high-low;nominal_width=float(dimensions[role]['width'])
        if (not all(math.isfinite(v) for v in (low,high,nominal_width))
                or nominal_width<=0 or actual_width<=0):
            raise LocalTireSourceError('原本WheelStyle幅と純正タイヤ幅が不正')
        axial_width_source = 'nominal-tread-width-crosscheck'
        if abs(actual_width-nominal_width)>max(.025,nominal_width*.10):
            # WheelStyleはRim/Spokeを含み、タイヤ公称幅とは別の量。
            # 元ModelBinのMorphとCarbin/GameDB配置の全Mesh署名が揃う場合だけ、
            # 元WheelStyleの実形状中心を保ったまま通過させる。
            if wheel_axis_proof is None:
                wheel_axis_proof = _verified_carbin_wheel_yz(doc, role, hub, carbin_axis=carbin_axis)
            if wheel_axis_proof is None:
                raise LocalTireSourceError(
                    '原本WheelStyle幅と純正タイヤ幅が不一致（Carbin署名不足）')
            axial_width_source = 'source-ModelBin-rim-and-verified-Carbin-axle'
        # Xは原本WheelStyleの実形状中心。Y/Zは既に車体座標で一致するGameDB元車軸。
        target=np.asarray([wheel[0],hub[1],hub[2]],dtype=np.float64)
        results[role]=target
        basis[role]={'wheelstyle_x_min_m':round(low,7),'wheelstyle_x_max_m':round(high,7),
                     'wheelstyle_axial_width_m':round(actual_width,7),
                     'wheelstyle_axial_width_basis':axial_width_source,
                     'source_tire_nominal_width_m':round(nominal_width,7),
                     'gamedb_hub_x_m':round(float(hub[0]*(signs[-1] if signs else 1)),7),
                     'tire_axial_center_x_m':round(float(wheel[0]),7),
                     'hub_to_seat_axial_delta_m':round(float(wheel[0]-hub[0]*(signs[-1] if signs else 1)),7),
                     'wheel_aabb_yz_vs_gamedb_offset_m':round(wheel_geometry_yz_error,7),
                     'carbin_game_axis_yz_proof':wheel_axis_proof}
    if len(set(signs))!=1:
        raise LocalTireSourceError('元GLBとGameDBで左右軸の基準が不整合')
    for axle in ('front','middle','rear'):
        if axle+'_left' not in results or axle+'_right' not in results:
            continue
        left,right=results[axle+'_left'],results[axle+'_right']
        if abs(left[0]+right[0])>TIRE_CENTER_LATERAL_SYMMETRY_M or np.linalg.norm(left[1:]-right[1:])>.02:
            raise LocalTireSourceError('純正タイヤ幅中心の左右原本対称性が不一致')
    return results,{'method':'signed-original-WheelStyle-axial-bounds-midpoint-v2',
                    'gamedb_hub_not_tire_center':True,'source_roles':basis,
                    'xbox_appearance_approved':False}


def _append_mesh(doc,buf,role,source_name,source_archive_stem,archive_sha,modelbin_sha,geometry,source_normals,uv,idx,material_id,material_name,source_meshblob_index,center):
    normals=np.asarray(source_normals,dtype='<f4')
    if normals.shape!=geometry.shape or not np.isfinite(normals).all():
        raise LocalTireSourceError('原本Tire NORMALの頂点数・有限値が不正')
    normal_length=np.linalg.norm(normals,axis=1)
    if np.any(np.abs(normal_length-1)>1.e-3):
        raise LocalTireSourceError('原本Tire NORMALの単位長が不正')
    vert=np.column_stack((geometry,normals)).astype('<f4').tobytes()
    u=uv.reshape(len(geometry),8).astype('<f4').tobytes()
    vi=add_aligned(buf,vert); ii=add_aligned(buf,idx.astype('<u2').tobytes()); ui=add_aligned(buf,u)
    viewV=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':vi,'byteLength':len(vert),'byteStride':24,'target':34962})
    viewI=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':ii,'byteLength':idx.size*2,'target':34963})
    viewU=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':ui,'byteLength':len(u),'byteStride':32,'target':34962})
    pos=len(doc['accessors']);doc['accessors'].append({'bufferView':viewV,'byteOffset':0,'componentType':5126,'count':len(geometry),'type':'VEC3','min':geometry.min(0).astype(float).tolist(),'max':geometry.max(0).astype(float).tolist()})
    normal=len(doc['accessors']);doc['accessors'].append({'bufferView':viewV,'byteOffset':12,'componentType':5126,'count':len(geometry),'type':'VEC3'})
    ind=len(doc['accessors']);doc['accessors'].append({'bufferView':viewI,'componentType':5123,'count':idx.size,'type':'SCALAR'})
    attrs={'POSITION':pos,'NORMAL':normal}
    for i in range(4):
        uvacc=len(doc['accessors']);doc['accessors'].append({'bufferView':viewU,'byteOffset':i*8,'componentType':5126,'count':len(geometry),'type':'VEC2'})
        attrs['TEXCOORD_'+str(i)]=uvacc
    ex={'lo4_part_type':'Tire','lo4_role':'trim','lo4_source_entry':'Game:/Media/Cars/_library/scene/tires/'+source_archive_stem+'/'+source_name,
        'lo4_tire_source_wheel':role,'lo4_tire_original_archive_sha256':archive_sha,
        'lo4_tire_source_packet_sha256':modelbin_sha,
        'lo4_tire_original_modelbin_sha256':modelbin_sha,
        'lo4_tire_source_digest_kind':'local-original-modelbin',
        'lo4_tire_private_origin':ORIGIN,'lo4_tire_uv_origin':UV_ORIGIN,
        'lo4_tire_original_material_id':material_id,'lo4_tire_original_material_name':material_name,
        'lo4_tire_source_meshblob_index':source_meshblob_index,
        'lo4_tire_normal_origin':'ModelBin-POSITION.W-NORMAL.RG-SNORM16',
        'lo4_base_visible':True,'lo4_stock_part':True,'lo4_tire_xbox_parity_verified':False,
        'lo4_tire_runtime_morph_approved':False}
    name='OriginalTire/'+role+'/'+source_name.replace('.modelbin','')
    mesh=len(doc['meshes']);doc['meshes'].append({'name':name,'primitives':[{'attributes':attrs,'indices':ind,'material':_get_tire_material(doc),'mode':4}], 'extras':ex})
    node=len(doc['nodes']);doc['nodes'].append({'name':name,'mesh':mesh,'translation':[float(v) for v in center], 'extras':dict(ex)})
    doc['scenes'][doc.get('scene',0)]['nodes'].append(node)


def _get_tire_material(doc):
    # PBR原本Shaderの証明とは分離。研究表示用に既存Viewerの暗色ラバーを使用。
    for i,m in enumerate(doc.setdefault('materials',[])):
        if m.get('name')=='Local-source-tire-research-neutral':return i
    i=len(doc['materials']);doc['materials'].append({'name':'Local-source-tire-research-neutral',
        'pbrMetallicRoughness':{'baseColorFactor':[.12,.13,.14,1.0],'metallicFactor':0,'roughnessFactor':.85},'doubleSided':False})
    return i


def build_local_tire_glb(source_glb:Path, contract:dict, game_folder:Path, output_glb:Path, output_proof:Path, *, vehicle_archive:Path|None=None) -> dict:
    """原本ソースは読み取りのみ。出力はユーザーのプレビューキャッシュに限定。"""
    if output_glb.exists() or output_proof.exists():raise LocalTireSourceError('元GLB/生成物を上書きしません')
    model,dimensions,game_centers=_validated_assembly(contract)
    archive=resolve_installed_tire_archive(Path(game_folder),model)
    raw=source_glb.read_bytes();doc,bin_data=read_glb(raw)
    # 元の BIN は、元のファイルの末尾（BIN チャンクは最後で、read_glb が長さを確かめている）。最後の先頭の比べに使う
    # （read_glb で読み直すと、25 MB の SHA と写しが走る。2026-11-21）
    source_bin_length=len(bin_data)
    if any(x.get('extras',{}).get('lo4_part_type')=='Tire' for x in doc.get('meshes',[])):
        raise LocalTireSourceError('元GLBにTireが存在し二重追加となります')
    doc.setdefault('materials',[])
    for key in ('meshes','nodes','materials','accessors','bufferViews','scenes','buffers'):
        if not isinstance(doc.get(key),list):raise LocalTireSourceError('元GLB構造が不足')
    carbin_axis=(contract.get('assembly') or {}).get('wheel_centers_source')==CARBIN_AXIS_AFTER_PLACEMENT_GUARD
    centers,axial_fitment=_validate_original_wheels(doc,bin_data,game_centers,dimensions,carbin_axis=carbin_axis)
    arch_bytes=archive.read_bytes();arch_sha=_sha(arch_bytes)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise LocalTireSourceError('ゲーム原本Tire ZIP CRC不正')
        role_entries=_original_tire_model_entries(z,model)
        roles=tuple(centers)
        for role in roles:
            if role in REAR_FOR_MIDDLE:
                role_entries[role]=role_entries[REAR_FOR_MIDDLE[role]]
        models={}
        for role in roles:
            side='L' if role.endswith('left') else 'R'
            entry=role_entries[role]
            if not 0<entry.file_size<16_000_000:
                raise LocalTireSourceError('元タイヤ'+role+' ModelBinサイズ不正')
            data=z.read(entry)
            models[role]=(data,_load_source_meshes(data,side),entry.filename)
    report={'schema':'lo4fh6.private.local_original_tire_runtime.v1','source_glb_sha256':_sha(raw),
        'source_tire_archive_sha256':arch_sha,'source_tire_archive_name':archive.name,
        'profile_source':'prepared-local-FH6-GameDB-assembly','modelbin_source':model,
        'tire_primitive_count':0,'wheels':{},'original_mesh_count':len(doc['meshes']),
        'source_tire_axial_fitment':axial_fitment,
        'game_runtime_morph_coefficients_approved':False,'xbox_appearance_approved':False,
        'original_game_file_modified':False}
    member_count = len({models[role][2].casefold() for role in roles})
    report['source_tire_modelbin_layout'] = {
        1: 'single_source_1', 2: 'two_sources_2', 4: 'per_corner_4'
    }.get(member_count, f'sources_{member_count}')
    report['source_tire_wheel_roles'] = list(roles)
    with zipfile.ZipFile(archive) as source_catalog:
        all_modelbin_names = sorted(
            entry.filename for entry in source_catalog.infolist()
            if not entry.is_dir() and entry.filename.casefold().endswith('.modelbin'))
    used_names = {models[role][2].casefold() for role in roles}
    report['source_tire_unused_modelbin_members'] = [
        name for name in all_modelbin_names if name.casefold() not in used_names]
    cached_profiles={}
    for role in roles:
        axis='front' if role.startswith('front') else 'rear'
        original,meshes,source_member=models[role]
        profile_key=(_sha(original),axis)
        if profile_key not in cached_profiles:
            cached_profiles[profile_key]=_source_morph_profile(meshes,dimensions[role])
        vertices,profile=cached_profiles[profile_key]
        applied_rotation = False
        for info,p in zip(meshes,vertices):
            positioned, rotated = _wheel_tire_source_to_role(p, source_member, role)
            applied_rotation = applied_rotation or rotated
            # 左右の180° Y回転は頂点Normalにも同じ剛体変換を適用。
            # Xだけの鏡像・再計算面法線は使用しない。
            axial_scale=profile['nominal_width_m']/profile['source_bead_span_m']
            source_normals=_morphed_tire_source_normals(
                info['source_normals'],info['normal_delta'],
                [*profile['profile_weights_research_only'],0.,0.,0.],
                axial_scale)
            if rotated:
                source_normals=source_normals.copy()
                source_normals[:,0]*=-1
                source_normals[:,2]*=-1
            _append_mesh(doc,bin_data,role,source_member,archive.stem,arch_sha,_sha(original),positioned,
                source_normals,info['uv'],info['indices'],info['material_id'],info['material_name'],info['meshblob_index'],centers[role])
            report['tire_primitive_count']+=1
        report['wheels'][role]={**profile,'modelbin_sha256':_sha(original),
            'source_modelbin_member':source_member,'source_meshes':len(meshes),
            'source_modelbin_side':_source_tire_side(source_member),
            'source_to_wheel_180_y_rotation':applied_rotation,
            'glb_center_m':[float(v) for v in centers[role]]}
    expected=sum(len(models[role][1]) for role in roles)
    if report['tire_primitive_count']!=expected or expected<len(roles):raise LocalTireSourceError('全車輪分の原本Tireメッシュが完全ではありません')
    report['source_tire_vertex_normal_proof']={
        'origin':'ModelBin-POSITION.W-NORMAL.RG-SNORM16',
        'signed_lod0_meshes':expected,
        'source_normals_retained':True,
        'source_morph_normal_deltas_applied':True,
        'axial_normal_inverse_transpose_applied':True,
        'triangle_recomputed_normals':False,
        'coordinate_conversion':'source-Z-flip-and-source-side-180Y-rigid-rotation',
        'shader_equivalent':False,
        'xbox_appearance_approved':False,
    }
    # 原本WheelStyleのImage/MaterialはGameDBや車種名で推測せず、
    # 元ModelBin MatI→MaterialBin→ShaderBinのTexture2D parameter名から追加する。
    # 同じゲーム原本アーカイブにだけ読み取りアクセス。Shader相当のPBRは未承認。
    if vehicle_archive is not None:
        from .source_wheel_local_textures import attach_original_wheel_textures
        report['original_wheel_texture_proof'] = attach_original_wheel_textures(
            doc, bin_data, content=Path(game_folder), vehicle_archive=Path(vehicle_archive))
    doc['buffers'][0]['byteLength']=len(bin_data)
    # 受入済みFEOW／Wheelアダプターにはメモリ上でのみ旧名を提示する。
    seal_firstparty_chassis_metadata(doc)
    jb=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode('utf8');jb+=b' '*(-len(jb)%4)
    bin_data.extend(b'\x00'*(-len(bin_data)%4))
    glb=struct.pack('<4sII',b'glTF',2,12+8+len(jb)+8+len(bin_data))+struct.pack('<I4s',len(jb),b'JSON')+jb+struct.pack('<I4s',len(bin_data),b'BIN\0')+bin_data
    report['wheel_glb_integrity'] = verify_local_original_wheel_material_proof(
        glb, report, require_source=vehicle_archive is not None)
    report['result_glb_sha256']=_sha(glb)
    report['original_bin_prefix_identical']=bytes(bin_data[:source_bin_length])==raw[len(raw)-source_bin_length:]
    if not report['original_bin_prefix_identical']:raise LocalTireSourceError('元の車体GLB BINプレフィクス変更を拒否')
    output_glb.parent.mkdir(parents=True,exist_ok=True)
    output_glb.write_bytes(glb)
    # 次の段（標準タイヤ）がこの GLB を読み直さないよう、書いた中身を同じプロセスで覚える（bytes_memo、2026-11-21）
    from .bytes_memo import remember_file
    remember_file(output_glb, glb)
    output_proof.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report



def verify_local_original_wheel_material_proof(glb: bytes, proof: dict, *, require_source: bool) -> dict:
    """キャッシュGLB内の実Material／Primitive構造と生成側の証明書を照合する。

    件数は申告された証明書からではなく実バイナリから計数する。
    材質を欠く旧キャッシュを原本Texture生成成功と誤認しない。
    これは由来の検証ゲートであり、GPU画素やShader画質の合格認定ではない。
    """
    # 文書と BIN を 1 回で読む（2 回読むと、25 MB の SHA と写しが 2 回走る。2026-11-21）
    document, binary = read_glb(glb)
    origin = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1'
    materials = document.get('materials', [])
    meshes = document.get('meshes', [])
    signed = {i for i, mat in enumerate(materials)
              if mat.get('extras', {}).get('lo4fh6_original_source_wheel_texture') == origin}
    # 署名済みMaterialが有効なのは、primitive → material → texture → image →
    # bufferView → GLB BINを順にたどって実画像バイトに到達できる場合だけ。
    # material.extrasに値があるだけではGLTFLoaderは画像を表示できない。
    textures = document.get('textures', [])
    images = document.get('images', [])
    views = document.get('bufferViews', [])
    buffers = document.get('buffers', [])
    referenced = 0
    for mesh in meshes:
        if mesh.get('extras', {}).get('lo4_part_type') != 'WheelStyle':
            continue
        for primitive in mesh.get('primitives', []):
            if primitive.get('material') not in signed:
                continue
            uv = primitive.get('attributes', {}).get('TEXCOORD_0')
            mat = materials[primitive['material']]
            tex = mat.get('pbrMetallicRoughness', {}).get('baseColorTexture', {})
            index = tex.get('index')
            if (not isinstance(uv, int) or isinstance(uv, bool)
                    or not isinstance(index, int) or isinstance(index, bool)
                    or not 0 <= index < len(textures)):
                raise LocalTireSourceError('原本Wheel署名材質のUV0/Textureが欠落')
            texture = textures[index]
            image_index = texture.get('source')
            if not isinstance(image_index, int) or isinstance(image_index, bool) or not 0 <= image_index < len(images):
                raise LocalTireSourceError('原本Wheel署名材質のTexture→Image参照が不正')
            image = images[image_index]
            view_index = image.get('bufferView')
            if (not isinstance(view_index, int) or isinstance(view_index, bool)
                    or not 0 <= view_index < len(views) or image.get('mimeType') != 'image/png'):
                raise LocalTireSourceError('原本Wheel署名材質のImage→PNG BufferView参照が不正')
            view = views[view_index]
            offset, length = view.get('byteOffset', 0), view.get('byteLength')
            if (view.get('buffer') != 0 or not isinstance(offset, int) or isinstance(offset, bool)
                    or not isinstance(length, int) or isinstance(length, bool)
                    or offset < 0 or length < 24 or offset + length > len(binary)
                    or not buffers or buffers[0].get('byteLength', -1) < offset + length):
                raise LocalTireSourceError('原本Wheel署名PNGのGLB BIN領域が不正')
            payload = binary[offset:offset + length]
            if payload[:8] != b'\x89PNG\r\n\x1a\n' or payload[-12:-8] != b'\x00\x00\x00\x00' or payload[-8:-4] != b'IEND':
                raise LocalTireSourceError('原本Wheel署名PNGの実体が不正')
            referenced += 1
    receipt = proof.get('original_wheel_texture_proof')
    if require_source:
        if not isinstance(receipt, dict) or receipt.get('origin') != origin:
            raise LocalTireSourceError('原本Wheel材質の生成証拠が欠落')
        # 配信GLBの検証条件と揃え、署名材質ゼロをキャッシュ成功にしない。
        # Browserが3D表示を開始してから止まる欠落を生成時点で特定する。
        if not signed or referenced == 0:
            raise LocalTireSourceError('原本Wheelの署名付き実材質がありません（原本Texture2D未接続）')
        expected_mesh = receipt.get('textured_wheel_meshes')
        expected_material = receipt.get('source_materials')
        if not isinstance(expected_mesh, int) or expected_mesh != referenced:
            raise LocalTireSourceError('原本Wheel材質のGLB実体と生成証拠の件数が不一致')
        if not isinstance(expected_material, int) or expected_material != len(signed):
            raise LocalTireSourceError('原本Wheel材質の署名数が生成証拠と不一致')
    return {'signed_wheel_primitives': referenced, 'signed_materials': len(signed),
            'xbox_appearance_approved': False}


def prepared_local_tire_mesh(source_glb:Path,contract:dict,game_folder:Path,output_root:Path,*,vehicle_archive:Path|None=None)->Path:
    """同一入力の完全署名済み派生GLBを再利用。旧ファイルと原本は変更しない。"""
    final,proof,original_sha,archive_sha=local_tire_cache_paths(
        source_glb,contract,game_folder,output_root,vehicle_archive=vehicle_archive)
    key=final.name[len('original-tire-'):-len('.glb')]
    cache=final.parent
    if final.is_file() and proof.is_file():
        j=json.loads(proof.read_text(encoding='utf8'))
        if j.get('source_glb_sha256')==original_sha and j.get('source_tire_archive_sha256')==archive_sha and j.get('result_glb_sha256')==_sha(final.read_bytes()):
            verify_local_original_wheel_material_proof(final.read_bytes(), j, require_source=vehicle_archive is not None)
            return final
        raise LocalTireSourceError('ローカル原本タイヤキャッシュの署名が不一致')
    if final.exists()!=proof.exists():raise LocalTireSourceError('ローカル原本タイヤキャッシュが不完全')
    # 生成中にWindows GUIが停止しても完成済みキャッシュを破損させない。
    cache.mkdir(parents=True,exist_ok=True)
    temp_glb=cache/('.partial-'+key+'-'+str(os.getpid())+'.glb')
    temp_proof=cache/('.partial-'+key+'-'+str(os.getpid())+'.json')
    try:
        build_local_tire_glb(source_glb,contract,game_folder,temp_glb,temp_proof,vehicle_archive=vehicle_archive)
        temp_glb.replace(final)
        from .bytes_memo import moved
        moved(temp_glb, final)
        temp_proof.replace(proof)
    finally:
        temp_glb.unlink(missing_ok=True)
        temp_proof.unlink(missing_ok=True)
    return final


def local_tire_cache_paths(source_glb:Path,contract:dict,game_folder:Path,output_root:Path,*,vehicle_archive:Path|None=None)->tuple[Path,Path,str,str]:
    """元の車体＋原本タイヤの GLB の保存先（入力から決まる鍵の名前）と、鍵に使った元の GLB・タイヤ原本の SHA。

    作りも照合もしない。標準Tireの索引に当たるか（作り直しが要らないか）を先に調べるのに使う。
    """
    original_sha=_file_sha(source_glb)
    model,dim,centers=_validated_assembly(contract)
    archive=resolve_installed_tire_archive(Path(game_folder),model)
    archive_sha=_file_sha(archive)
    # 原本材質の更新もキャッシュキーに含める。OS上のFH6を読み取り専用。
    material_archive_ids = {}
    if vehicle_archive is not None:
        # 実ゲームではShaderはfamily別ZIPであり、_library/Shaders.zip は存在しない。
        shader_dir=Path(game_folder)/'media/cars/_library/shaders'
        if not shader_dir.is_dir():
            raise LocalTireSourceError('FH6原本Shaderフォルダーがありません: '+str(shader_dir))
        for label, path in (
            ('vehicle', Path(vehicle_archive)),
            ('materials', Path(game_folder)/'media/cars/_library/Materials.zip'),
            ('textures', Path(game_folder)/'media/cars/_library/Textures.zip'),
        ):
            if label != 'textures' and not path.is_file():
                raise LocalTireSourceError('FH6原本材質アーカイブがありません: '+str(path))
            if path.is_file():
                st=path.stat()
                material_archive_ids[label]=[str(path.resolve()),st.st_size,st.st_mtime_ns]
        # Shader更新時のキャッシュ誤再利用を防止し、ゲーム原本は読み取りのみ。
        # フォルダーの一覧（os.scandir）から大きさと更新日時を得る（Windows ではファイルごとに問い合わせない。
        # 以前は 1 つにつき is_file と stat を 3 回。値と並びは同じ。2026-11-20）。
        with os.scandir(shader_dir) as shader_entries:
            listed=sorted(shader_entries,key=lambda x:x.name.casefold())
        material_archive_ids['shader_archives']=[
            [entry.name,entry.stat().st_size,entry.stat().st_mtime_ns]
            for entry in listed
            if entry.is_file() and PurePath(entry.name).suffix.casefold()=='.zip'
        ]
        # 展開済みShaderBin/XML構成でもキャッシュ追従できるよう元パスを記録。
        material_archive_ids['shader_direct_files'] = [
            [str(p.relative_to(shader_dir)).replace('\\','/'),p.stat().st_size,p.stat().st_mtime_ns]
            for family in ('car_standard','car_standard_coated','car_automotive_paint')
            for p in (shader_dir/family/(family+'.shaderbin'),shader_dir/family/(family+'.shaderbin.xml'))
            if p.is_file()
        ]
        if not material_archive_ids['shader_archives'] and not material_archive_ids['shader_direct_files']:
            raise LocalTireSourceError('FH6原本ShaderのZIP/展開済みファイルがありません: '+str(shader_dir))
    key=_sha(json.dumps({'base':original_sha,'archive':archive_sha,'model':model,'dimensions':dim,
        'centers':{k:v.tolist() for k,v in centers.items()},'revision':LOCAL_TIRE_CACHE_REVISION,
        'material_inputs':material_archive_ids},sort_keys=True).encode('utf8'))[:24]
    cache=Path(output_root)/'_original_tire_local_source'
    final=cache/('original-tire-'+key+'.glb');proof=cache/('original-tire-'+key+'.json')
    # 標準タイヤの段は、この名前から差分の土台（元の車体の形の GLB）を引いて、差分で保存する（glb_delta）。
    from .glb_delta import register_delta_base
    register_delta_base(final.name,source_glb)
    return final,proof,original_sha,archive_sha
