"""原本ModelBin・GLB・Maskの独立検証に基づく左右Facing接続（研究時のみ）。

rM027の確定済み第一者 source UV3+Mask+normal計測器の証明だけを検証して
既存Viewer契約のFacingを切り替える。車種ID・Livery名による見た目補正禁止。
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
from pathlib import Path

from .package import FullLiveryPackageError

PROOF_SCHEMA = 'lo4fh6.rm027.source_uv3_mask_facing_evidence.v1'
MIN_COVERED = 500
MIN_CONSENSUS = .78
MAX_CONTRADICTION = .18


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Path | str, suffix: str) -> Path:
    result = Path(path).resolve()
    if not result.is_file() or Path(path).is_symlink() or result.suffix.lower() != suffix:
        raise FullLiveryPackageError('PRIVATE Facing照合入力ファイルが見つからないか形式が不正です')
    return result


def _verify_original_uv3_viewer_identity(mesh: Path) -> int:
    """実原本ModelBin照合済みTEXCOORD_3が元UV0 accessorを共有している場合だけ受理。

    r485/Viewer GLSLは `uv3.x * 0.5` であり、研究用の×2 accessorを
    重ねるとGPU-only実アトラスで二重拡大になる。車種・ペイント固有補正なし。
    PRIVATE研究用の安全ゲートのみ。Shader/Xboxの画質受入は別途必要。
    """
    size = mesh.stat().st_size
    with mesh.open('rb') as src:
        header = src.read(20)
        if (len(header) != 20 or header[:4] != b'glTF' or
            struct.unpack_from('<I', header, 4)[0] != 2 or
            struct.unpack_from('<I', header, 8)[0] != size or
            header[16:20] != b'JSON'):
            raise FullLiveryPackageError('原本UV3 GLB v2/JSON構造が不正です')
        json_len = struct.unpack_from('<I', header, 12)[0]
        if not 32 <= json_len <= 32 * 1024 * 1024 or json_len + 28 > size:
            raise FullLiveryPackageError('原本UV3 GLB JSONサイズが不正です')
        try:
            document = json.loads(src.read(json_len))
        except (UnicodeError, ValueError) as exc:
            raise FullLiveryPackageError('原本UV3 GLB JSONを解釈できません') from exc
        bin_header = src.read(8)
        if len(bin_header) != 8 or bin_header[4:] != b'BIN\x00':
            raise FullLiveryPackageError('原本UV3 GLB BIN構造が不正です')
        bin_len = struct.unpack_from('<I', bin_header, 0)[0]
        if 28 + json_len + bin_len != size:
            raise FullLiveryPackageError('原本UV3 GLB BIN長と実サイズが一致しません')
    meshes = document.get('meshes')
    accessors = document.get('accessors')
    views = document.get('bufferViews')
    if not isinstance(meshes, list) or not isinstance(accessors, list) or not isinstance(views, list):
        raise FullLiveryPackageError('原本UV3 GLBメッシュ・accessor構造が不正です')

    def checked_accessor(value: object, purpose: str) -> dict:
        if type(value) is not int or not 0 <= value < len(accessors):
            raise FullLiveryPackageError('原本UV3 ' + purpose + ' accessor参照が不正です')
        row = accessors[value]
        if not isinstance(row, dict) or type(row.get('bufferView')) is not int or \
           not 0 <= row['bufferView'] < len(views) or row.get('sparse') is not None:
            raise FullLiveryPackageError('原本UV3 accessor/BufferViewが不正です')
        return row

    count = 0
    paint_count = 0
    for record in meshes:
        if not isinstance(record, dict):
            raise FullLiveryPackageError('原本UV3 mesh記録が不正です')
        entry = (record.get('extras') or {}).get('lo4fh6_rm027_source_bound_uv3')
        primitives = record.get('primitives') or []
        if entry is None:
            # Paintメッシュが原本照合を通っていない場合、
            # 比較専用Facing権限を無告知で付与しない。
            continue
        if (not isinstance(entry, dict) or entry.get('glb_uv0_original_as_uv3') is not True
            or entry.get('viewer_default_enabled') is not False
            or type(entry.get('source_mesh_chunk_index')) is not int
            or entry['source_mesh_chunk_index'] < 0
            or not isinstance(entry.get('source_member_sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', entry['source_member_sha256'])
            or type(entry.get('max_abs_diff_float32')) not in (float, int)
            or not math.isfinite(entry['max_abs_diff_float32'])
            or entry['max_abs_diff_float32'] < 0 or entry['max_abs_diff_float32'] > 5e-6):
            raise FullLiveryPackageError('原本ModelBinのUV3照合記録が不正です')
        scale = entry.get('viewer_uv3_x_scale', 1.0)
        if type(scale) not in (int, float) or scale != 1.0:
            raise FullLiveryPackageError('原本UV3に2倍のU倍率が追加されています。旧r485同条件の未拡大属性が必要です')
        if len(primitives) != 1 or not isinstance(primitives[0], dict):
            raise FullLiveryPackageError('原本UV3 mesh primitive構造が不正です')
        attrs = primitives[0].get('attributes') or {}
        if (not isinstance(attrs, dict) or 'TEXCOORD_0' not in attrs or
            attrs.get('TEXCOORD_3') != attrs['TEXCOORD_0']):
            raise FullLiveryPackageError('元ModelBinのUV3とGLB UV0 accessor identityが一致しません')
        uv = checked_accessor(attrs['TEXCOORD_0'], 'UV0/UV3')
        pos = checked_accessor(attrs.get('POSITION'), 'POSITION')
        if (uv.get('componentType') != 5126 or uv.get('type') != 'VEC2' or
            type(uv.get('count')) is not int or uv['count'] < 1 or uv['count'] != pos.get('count')):
            raise FullLiveryPackageError('原本UV3 UV0/UV3の頂点数・型が一致しません')
        view = views[uv['bufferView']]
        if (not isinstance(view, dict) or type(view.get('byteOffset',0)) is not int
            or type(view.get('byteLength')) is not int or view['byteLength'] < 8
            or type(uv.get('byteOffset',0)) is not int or type(view.get('byteStride',8)) is not int):
            raise FullLiveryPackageError('原本UV3 bufferViewが不正です')
        stride = view.get('byteStride', 8)
        start = view.get('byteOffset', 0) + uv.get('byteOffset', 0)
        end = start + (uv['count'] - 1) * stride + 8
        if (stride < 8 or start < 0 or end > bin_len or
            uv.get('byteOffset',0) + (uv['count']-1)*stride+8 > view['byteLength']):
            raise FullLiveryPackageError('原本UV3 buffer範囲が不正です')
        count += 1
        if (record.get('extras') or {}).get('lo4fh6_role',
            (record.get('extras') or {}).get('lo4_role')) == 'paint':
            paint_count += 1
    if count < 1 or paint_count < 1:
        raise FullLiveryPackageError('原本ModelBin照合済みのUV3塗装メッシュがありません')
    return count


def validated_facing_metadata(
    metadata: dict, original_contract_file: Path | str, proof_file: Path | str,
    source_glb: Path | str, source_mask_files: list[Path] | tuple[Path, ...],
) -> dict:
    """確定済みの原本双方のFacing多数決を検証して契約コピーのみ返す。

    一致しない場合は明示例外。製品標準セッションの元metadataを更新しない。
    """
    original = _file(original_contract_file, '.json')
    proof_path = _file(proof_file, '.json')
    mesh = _file(source_glb, '.glb')
    try:
        source = json.loads(original.read_text(encoding='utf-8'))
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise FullLiveryPackageError('PRIVATE Facing証明JSONを解釈できません') from exc
    if not isinstance(proof, dict) or not isinstance(source, dict):
        raise FullLiveryPackageError('PRIVATE Facing証明形式が不正です')
    if (proof.get('schema') != PROOF_SCHEMA
        or proof.get('source_driven_not_car_id') is not True
        or proof.get('standard_enabled') is not False
        or proof.get('xbox_visual_approved') is not False
        or proof.get('original_glb_sha256') != _sha(mesh)
        or proof.get('render_contract_sha256') != _sha(original)
        or len(source_mask_files) != 3
        or proof.get('mask_sha256') != [_sha(_file(p, '.png')) for p in source_mask_files]
    ):
        raise FullLiveryPackageError('原本GLB・描画契約・3ページMaskのSHA照合に失敗しました')
    _verify_original_uv3_viewer_identity(mesh)
    rows = proof.get('side_counts')
    selection = proof.get('selection')
    if not isinstance(rows, dict) or not isinstance(selection, dict):
        raise FullLiveryPackageError('元GLBの左右Facing証拠が欠けています')
    if (selection.get('approved_for_comparison') is not True
        or selection.get('reason') != 'dual_side_original_uv3_mask_normal_consensus'
        or selection.get('product_default_enabled') is not False
        or selection.get('xbox_visual_approved') is not False
        or selection.get('reverse_both_sides') not in (True, False)):
        raise FullLiveryPackageError('未承認のFacingを通常設定へ接続できません')
    signs = selection.get('signs')
    if not isinstance(signs, dict):
        raise FullLiveryPackageError('原本左右の符号証明がありません')
    dominant = 'inverse' if selection['reverse_both_sides'] else 'same'
    for side in ('Left', 'Right'):
        row, sign = rows.get(side), signs.get(side)
        if not isinstance(row, dict) or not isinstance(sign, dict):
            raise FullLiveryPackageError('原本左右の証明が不足しています')
        positive, negative, neutral = (row.get(k) for k in ('positive', 'negative', 'neutral'))
        if any(type(v) is not int or v < 0 for v in (positive, negative, neutral)):
            raise FullLiveryPackageError('原本法線の標本数が不正です')
        total = positive + negative + neutral
        if total < MIN_COVERED or row.get('mask_covered') != total or sign.get('dominant') != dominant:
            raise FullLiveryPackageError('原本左右のMask実標本と符号が不足しています')
        consensus = (negative if dominant == 'inverse' else positive) / total
        contradiction = (positive if dominant == 'inverse' else negative) / total
        if consensus < MIN_CONSENSUS or contradiction > MAX_CONTRADICTION:
            raise FullLiveryPackageError('原本法線の左右多数決が確定していません')
        if not isinstance(sign.get('fraction'), (float, int)) or abs(sign['fraction'] - consensus) > 0.000002:
            raise FullLiveryPackageError('左右の多数決記録が実標本と不一致です')
    if not isinstance(metadata.get('sections'), list) or source.get('format') != metadata.get('format'):
        raise FullLiveryPackageError('既存Viewer描画契約が不正です')
    # 根拠のない既定ON化、面欠落、原本契約の変更を認めない。
    if len(source.get('sections', [])) != len(metadata['sections']):
        raise FullLiveryPackageError('元契約の11面構造が変更されています')
    for existing, expected in zip(metadata['sections'], source['sections']):
        if existing != expected:
            raise FullLiveryPackageError('元原本契約とViewer送信契約が異なります')
    candidate = copy.deepcopy(metadata)
    seen = set()
    for section in candidate['sections']:
        side = section.get('section')
        if side not in ('Left', 'Right'):
            continue
        expected_slot = {'Left': 3, 'Right': 4}[side]
        expected_facing = {'Left': [1., 0., 0.], 'Right': [-1., 0., 0.]}[side]
        if (side in seen or section.get('slot_index') != expected_slot
            or section.get('facing') != expected_facing):
            raise FullLiveryPackageError('左右ソースFacingの原本契約が一意ではありません')
        if selection['reverse_both_sides']:
            section['facing'][0] *= -1
        seen.add(side)
    if seen != {'Left', 'Right'}:
        raise FullLiveryPackageError('元GLBの左右双方が描画契約にありません')
    return candidate
