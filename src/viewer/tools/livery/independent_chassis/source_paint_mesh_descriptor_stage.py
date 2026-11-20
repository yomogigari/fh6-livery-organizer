"""FH6 source-bound per-mesh original Livery finish contract (research only).

Uses existing 参照製品-r485 GLB material binding (16 hexadecimal bytes as a numeric
big-endian label) and the first-party Yrvl 27-byte descriptor parser, without
inventing a shader/final color or putting any game bytes into the repository.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
from pathlib import Path
import copy
import json
import os
import re
import struct

class OriginalPaintMeshBindingError(ValueError):
    pass

_HASH = re.compile(r'[0-9a-fA-F]{16}\Z')
_COLOR = re.compile(r'#[0-9a-fA-F]{8}\Z')

def binding_hash_to_yrvl_id(binding_hash: str) -> str | None:
    """Convert original Carbin uint64 / r485 mesh binding to Yrvl record byte order."""
    if not isinstance(binding_hash, str) or not _HASH.fullmatch(binding_hash):
        raise OriginalPaintMeshBindingError('source material binding hash invalid')
    numeric = int(binding_hash, 16)
    return numeric.to_bytes(8, 'little').hex() if numeric else None

def _glb_json(raw: bytes):
    if len(raw) < 40 or len(raw) > 256 * 1024 * 1024:
        raise OriginalPaintMeshBindingError('source GLB size invalid')
    if raw[:4] != b'glTF' or struct.unpack_from('<II', raw, 4) != (2, len(raw)):
        raise OriginalPaintMeshBindingError('source GLB header mismatch')
    size, kind = struct.unpack_from('<I4s', raw, 12)
    if kind != b'JSON' or size % 4 or size > 32 * 1024 * 1024 or 20 + size + 8 > len(raw):
        raise OriginalPaintMeshBindingError('source GLB JSON invalid')
    length, kind = struct.unpack_from('<I4s', raw, 20 + size)
    if kind != b'BIN\x00' or 28 + size + length != len(raw):
        raise OriginalPaintMeshBindingError('source GLB geometry boundary mismatch')
    return json.loads(raw[20:20 + size]), sha256(raw[28 + size:]).hexdigest()

# 照合が GLB の部品から使うのは、extras のこの 4 つ（材質の名前と結び付けの番号）だけ。
_FINISH_EXTRAS_KEYS = ('lo4_material_name', 'lo4fh6_material_name',
                       'lo4_material_binding_hash', 'lo4fh6_material_binding_hash')


def _finish_mesh_facts(mesh):
    """部品のうち照合に使う部分（extras の _FINISH_EXTRAS_KEYS）だけ。形の違う部品はそのまま返す（照合が止める）。"""
    if not isinstance(mesh, dict):
        return mesh
    extras = mesh.get('extras')
    if not isinstance(extras, dict):
        return {'extras': extras}
    return {'extras': {name: extras[name] for name in _FINISH_EXTRAS_KEYS if name in extras}}


def _glb_finish_facts(raw: bytes) -> tuple:
    """照合が GLB から使う事実：部品の一覧（照合に使う部分だけ）・形の区画の SHA-256・GLB 全体の SHA-256。"""
    doc, bin_sha = _glb_json(raw)
    meshes = doc.get('meshes')
    if isinstance(meshes, list):
        meshes = [_finish_mesh_facts(mesh) for mesh in meshes]
    return meshes, bin_sha, sha256(raw).hexdigest()


# 同じプロセスの中で、同じ GLB のファイル（場所・大きさ・更新日時が同じ）の事実を覚える（2026-11-20）。
# 同じ車のペイントを続けて開くたびに、約 35 MB の GLB を読み、目次を解析し、SHA-256 を 2 回計算していた
# （前半の車体と後半の組み立て後の 2 つで約 0.15 秒）。ファイルが変われば大きさか更新日時が変わるので計算し直す。
_FILE_FACTS: dict = {}
_FILE_FACTS_LIMIT = 4


def _file_facts(path) -> tuple:
    target = Path(path)
    stat = target.stat()  # 識別は読む前に取る（読む間に変わっても、古い識別に付くだけで次からは外れる）
    # 場所は resolve せず（Windows ではファイルを開いて閉じ、さらに stat する）abspath にし、どのファイルかは
    # stat の機器と番号で見分ける（2026-11-20）。
    identity = (os.path.normcase(os.path.abspath(target)), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns)
    facts = _FILE_FACTS.get(identity)
    if facts is None:
        facts = _glb_finish_facts(target.read_bytes())
        while len(_FILE_FACTS) >= _FILE_FACTS_LIMIT:
            _FILE_FACTS.pop(next(iter(_FILE_FACTS)))
        _FILE_FACTS[identity] = facts
    return facts


def glb_finish_facts_for_file(path) -> tuple:
    """_glb_finish_facts を GLB のファイルから（覚えた事実の写しを返す）。"""
    meshes, bin_sha, glb_sha = _file_facts(path)
    return copy.deepcopy(meshes), bin_sha, glb_sha


def glb_sha256_for_file(path) -> str:
    """GLB のファイル全体の SHA-256（glb_finish_facts_for_file と同じく覚えて使い回す）。"""
    return _file_facts(path)[2]


def audit_source_mesh_finish_bindings(glb: bytes, yrvl: dict, catalog: dict[int, dict]) -> dict:
    """Source-proof report only. Never changes mesh bytes, product default, or shader.

    Missing/unknown material bindings are reported and never replaced by the
    dominant finish. Different Carbin bindings on one vehicle remain separate.
    """
    return _audit_finish_bindings(lambda: _glb_finish_facts(glb), yrvl, catalog)


def audit_source_mesh_finish_bindings_for_file(path, yrvl: dict, catalog: dict[int, dict]) -> dict:
    """audit_source_mesh_finish_bindings と同じ照合を GLB のファイルで行う（同じファイルの事実は覚えて使い回す）。

    照合（_audit_finish_bindings）は事実を読むだけで、結果には事実の中の変えられる物（一覧・辞書）を入れない。
    そのため覚えた事実を写さずに渡す（以前は照合のたびに copy.deepcopy していた。差し替えの準備で 2 回。
    2026-11-20）。照合を変えるときも、事実を書き換えないこと。
    """
    return _audit_finish_bindings(lambda: _file_facts(path), yrvl, catalog)


def _audit_finish_bindings(glb_facts, yrvl: dict, catalog: dict[int, dict]) -> dict:
    descriptor = yrvl.get('candidate_material_yrvl')
    if yrvl.get('format') != 'lo4fh6_yrvl_research_v1' or not isinstance(descriptor, dict):
        raise OriginalPaintMeshBindingError('FH6 source Yrvl parser result required')
    records = descriptor.get('records')
    if not isinstance(records, list) or descriptor.get('record_count') != len(records):
        raise OriginalPaintMeshBindingError('source Yrvl descriptor count mismatch')
    by_id = {}
    for record in records:
        if not isinstance(record, dict):
            raise OriginalPaintMeshBindingError('invalid original Yrvl record')
        identity = record.get('material_identifier_hex')
        if not isinstance(identity, str) or not _HASH.fullmatch(identity) or identity.lower() in by_id:
            raise OriginalPaintMeshBindingError('duplicate / invalid original Yrvl material ID')
        by_id[identity.lower()] = record
    meshes, bin_sha, glb_sha = glb_facts()
    if not isinstance(meshes, list) or not meshes:
        raise OriginalPaintMeshBindingError('no source GLB meshes')
    count = Counter()
    carpaint_groups = {}
    carpaint_materials = {}
    manufacturer_palette_groups = {}
    manufacturer_carpaint_counts = {}
    for mesh in meshes:
        extras = mesh.get('extras') if isinstance(mesh, dict) else None
        if not isinstance(extras, dict):
            raise OriginalPaintMeshBindingError('original GLB mesh material proof absent')
        # ブラウザーが辿る全CarPaintを「一部だけ一致」の成功と区別する。
        # 機能OFF時の原本材質・通常描画は触らない。
        names = [
            str(extras[name]) for name in ('lo4_material_name', 'lo4fh6_material_name')
            if isinstance(extras.get(name), str) and extras[name].strip()
        ]
        if len(names) == 2 and names[0].strip().casefold() != names[1].strip().casefold():
            raise OriginalPaintMeshBindingError('conflicting original GLB material names')
        is_carpaint = bool(names and names[0].strip().casefold() == 'carpaint')
        # carPaint の仲間（carpaint_secondary・carPaint|doorLF_a・ID01_carpaint 等）。ペイントの板・nolivery・内装は除く。
        family_base = re.sub(r'^id\d+_', '', names[0].strip().casefold().split('|')[0]) if names else ''
        is_carpaint_family = (not is_carpaint and family_base.startswith('carpaint')
                              and 'livery' not in family_base and 'interior' not in family_base)
        if is_carpaint:
            count['carpaint_mesh_total'] += 1
        # 元実車GLBには参照製品由来のlo4_*と第一者Converterのlo4fh6_*
        # という別のextras名前空間がある。どちらも元Carbinの同じ64-bit
        # binding IDを保持する。混在時に不一致を隠して片側を採用しない。
        available = [
            (name, extras[name]) for name in
            ('lo4_material_binding_hash', 'lo4fh6_material_binding_hash')
            if name in extras and extras[name] is not None
        ]
        if not available:
            count['mesh_source_binding_absent'] += 1
            continue
        if len(available) == 2 and str(available[0][1]).upper() != str(available[1][1]).upper():
            raise OriginalPaintMeshBindingError('conflicting original GLB material binding namespaces')
        binding = available[0][1]
        key = binding_hash_to_yrvl_id(binding)
        if key is None:
            count['mesh_binding_unassigned'] += 1
            if is_carpaint:
                # 元Hash=0はJSでも未割当として既定表示を維持する。
                count['carpaint_mesh_zero_unassigned'] += 1
            continue
        record = by_id.get(key)
        if record is None:
            count['mesh_binding_no_yrvl_record'] += 1
            continue
        code = record.get('finish_code_raw')
        if type(code) is not int or code < 0:
            raise OriginalPaintMeshBindingError('original finish code invalid')
        # Yrvlの0xFFFFFFFFはメーカー色未選択。0は有効候補であり、
        # 原本GLBのLivery面にも実際に存在する。色なし/finish0と同義にしない。
        selector = record.get('manufacturer_color_selector_raw')
        if selector is not None and (type(selector) is not int or not 0 <= selector <= 0xffffffff):
            raise OriginalPaintMeshBindingError('original manufacturer selector invalid')
        if selector is not None and selector != 0xffffffff:
            # メーカー指定色が選ばれている記録は、残っている独自の色・仕上げより指定色を優先する
            # （参照製品 docs/CLIVERY.md「An active manufacturer selector takes precedence over retained
            # custom color bytes.」、参照のみ。2026-11-17 に Car 634 のサムネイルの黒で確認）。
            # 独自の色・仕上げが残っている記録は、その旨を数えて区別する。
            if (record.get('primary_color_enabled') is not False
                    or record.get('secondary_color_enabled') is not False or code != 0):
                count['mesh_manufacturer_selector_over_retained_custom_color'] += 1
            group_key = binding.upper()
            candidate = {'manufacturer_selector_raw': selector,
                         'source_finish_code_raw': code,
                         'manufacturer_palette_resolved': False,
                         'research_only': True}
            if group_key in manufacturer_palette_groups and manufacturer_palette_groups[group_key] != candidate:
                raise OriginalPaintMeshBindingError('conflicting original manufacturer selector')
            manufacturer_palette_groups[group_key] = candidate
            count['mesh_manufacturer_selector_reference_preserved'] += 1
            if is_carpaint:
                manufacturer_carpaint_counts[group_key] = manufacturer_carpaint_counts.get(group_key, 0) + 1
            continue
        if code == 0 and (
                record.get('primary_color_enabled') is True
                or record.get('secondary_color_enabled') is True):
            # 原本RGBはあるが元Shader finish=0をGameDBの別仕上げへ置換しない。
            count['mesh_explicit_rgb_with_unresolved_zero_finish'] += 1
            continue
        if code == 0 and record.get('primary_color_enabled') is False and record.get('secondary_color_enabled') is False:
            count['mesh_no_explicit_color_or_finish'] += 1
            continue
        finish = catalog.get(code)
        if not isinstance(finish, dict) or int(finish.get('id', -1)) != code:
            count['mesh_known_binding_unknown_finish'] += 1
            continue
        required = finish.get('num_input_colors')
        if type(required) is not int or required < 0 or required > 2:
            raise OriginalPaintMeshBindingError('unsupported original finish input color count')
        primary = record.get('primary_color', {})
        secondary = record.get('secondary_color', {})
        if not isinstance(primary, dict) or not isinstance(secondary, dict):
            raise OriginalPaintMeshBindingError('original descriptor color shape invalid')
        first = primary.get('rgba_hex') if record.get('primary_color_enabled') is True else None
        second = secondary.get('rgba_hex') if record.get('secondary_color_enabled') is True else None
        if first is not None and not _COLOR.fullmatch(first):
            raise OriginalPaintMeshBindingError('original primary RGBA invalid')
        if second is not None and not _COLOR.fullmatch(second):
            raise OriginalPaintMeshBindingError('original secondary RGBA invalid')
        # Do not invent an absent shader input even if the finish is mapped.
        if required >= 1 and first is None or required >= 2 and second is None:
            count['mesh_finish_color_inputs_missing'] += 1
            continue
        count['mesh_original_finish_bound'] += 1
        if not is_carpaint and not is_carpaint_family:
            continue
        if is_carpaint_family:
            count['carpaint_family_mesh_original_finish_bound'] += 1
        material_name = names[0]
        if is_carpaint:
            count['carpaint_mesh_original_finish_bound'] += 1
        row = {'finish_code_raw': code, 'finish_material_name': str(finish.get('material_name') or ''),
               'required_input_colors': required, 'primary_color_rgba_hex': first,
               'secondary_color_rgba_hex': second, 'research_only': True,
               'game_shader_gpu_verified': False}
        group_key = binding.upper()
        if group_key in carpaint_groups and carpaint_groups[group_key] != row:
            raise OriginalPaintMeshBindingError('conflicting original carPaint group assignment')
        carpaint_groups[group_key] = row
        carpaint_materials[group_key] = material_name
    count['carpaint_distinct_original_binding_groups'] = len(carpaint_groups)
    count['manufacturer_distinct_original_binding_groups'] = len(manufacturer_palette_groups)
    count['carpaint_mesh_unresolved_for_research'] = (
        count['carpaint_mesh_total'] - count['carpaint_mesh_original_finish_bound']
        - count['carpaint_mesh_zero_unassigned']
    )
    # 元C_liveryと対応するメッシュだけを研究用に送ると、
    # 残りのcarPaintでブラウザーが起動後に停止する。ここで全件検査する。
    complete = bool(carpaint_groups) and count['carpaint_mesh_unresolved_for_research'] == 0
    return {'schema': 'lo4fh6.firstparty.source-mesh-paint-group-binding.v1',
            'source_glb_sha256': glb_sha,
            'source_geometry_bin_sha256': bin_sha,
            'counts': dict(sorted(count.items())),
            'carpaint_binding_complete_for_research': complete,
            'carpaint_groups': dict(sorted(carpaint_groups.items())),
            'manufacturer_palette_groups_unresolved': dict(sorted(manufacturer_palette_groups.items())),
            'manufacturer_palette_carpaint_mesh_counts': dict(sorted(manufacturer_carpaint_counts.items())),
            'manufacturer_palette_rgb_substituted': False,
            'original_glb_modified': False,
            'shader_or_finish_equations_approximated': False,
            'product_default_modified': False,
            'windows_xbox_approved': False}


def resolve_manufacturer_carpaint_groups(report: dict, palette_color) -> dict:
    """メーカー指定色の記録に結び付いた塗装部品（carPaint）を、車種の工場出荷色で補う。

    palette_color(選択番号) は {'rgba_hex': '#RRGGBBAA', 'material_name': 名前} か None を返す。
    解決できた集まりは carpaint_groups に加え（manufacturer_selector_raw 付き）、その部品を
    対応済みに数え直す。全部品が対応済みになれば carpaint_binding_complete_for_research を真にする。
    """
    result = dict(report)
    groups = dict(result.get('carpaint_groups') or {})
    counts = dict(result.get('counts') or {})
    resolved_meshes = 0
    for key, mesh_count in sorted((result.get('manufacturer_palette_carpaint_mesh_counts') or {}).items()):
        candidate = (result.get('manufacturer_palette_groups_unresolved') or {}).get(key) or {}
        selector = candidate.get('manufacturer_selector_raw')
        if type(selector) is not int or type(mesh_count) is not int or mesh_count <= 0:
            continue
        color = palette_color(selector)
        if not isinstance(color, dict) or not _COLOR.fullmatch(str(color.get('rgba_hex') or '')) \
                or not isinstance(color.get('material_name'), str) or not color['material_name']:
            continue
        row = {'finish_code_raw': 0, 'finish_material_name': color['material_name'],
               'required_input_colors': 1, 'primary_color_rgba_hex': color['rgba_hex'].lower(),
               'secondary_color_rgba_hex': None, 'research_only': True,
               'game_shader_gpu_verified': False, 'manufacturer_selector_raw': selector,
               'color_source': 'vehicle-manufacturer-palette'}
        if key in groups and groups[key] != row:
            raise OriginalPaintMeshBindingError('conflicting original carPaint group assignment')
        groups[key] = row
        resolved_meshes += mesh_count
    counts['carpaint_mesh_manufacturer_palette_resolved'] = resolved_meshes
    counts['carpaint_mesh_original_finish_bound'] = counts.get('carpaint_mesh_original_finish_bound', 0) + resolved_meshes
    counts['carpaint_distinct_original_binding_groups'] = len(groups)
    counts['carpaint_mesh_unresolved_for_research'] = (
        counts.get('carpaint_mesh_total', 0) - counts['carpaint_mesh_original_finish_bound']
        - counts.get('carpaint_mesh_zero_unassigned', 0))
    result['counts'] = dict(sorted(counts.items()))
    result['carpaint_groups'] = dict(sorted(groups.items()))
    result['carpaint_binding_complete_for_research'] = bool(groups) and counts['carpaint_mesh_unresolved_for_research'] == 0
    result['manufacturer_palette_rgb_substituted'] = resolved_meshes > 0
    return result


def apply_finish_display_colors(report: dict, display_color) -> dict:
    """カーボン・色の入力の無い仕上げの塗装部品に、描画用の色（display_rgba_hex）を付ける。

    display_color(仕上げの番号) は '#RRGGBBAA' か None。カーボンは織り目の 2 色の平均（記録の色は
    使わない。サムネイルのカーボンはほぼ黒）、色の入力の無い仕上げ（金・スチール等）は材質自体の色。
    メーカー指定色の集まりは対象外。
    """
    result = dict(report)
    groups = {}
    for key, row in (result.get('carpaint_groups') or {}).items():
        row = dict(row)
        if 'manufacturer_selector_raw' not in row:
            value = display_color(row.get('finish_code_raw'))
            if isinstance(value, str) and _COLOR.fullmatch(value):
                row['display_rgba_hex'] = value.lower()
        groups[key] = row
    result['carpaint_groups'] = dict(sorted(groups.items()))
    return result
