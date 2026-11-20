"""LO4FH6 rM018：参照製品実行コードを読み込まない独立C_liveryレイヤー解析。

解析入力は本プロジェクトの原本エンベロープ、厳密なGroupビットマップ走査、
葉レコード読取器、原本由来のアフィン幾何だけに限定する。
未対応入力は明示拒否するプレビュー候補であり、保護Groupの意味、
XboxのShader外観、リリース可否を保証しない。
車種・作者・図形に固有のハードコードを設けない。
"""
from __future__ import annotations

from dataclasses import replace
import math
import struct
from typing import Any

from .native_structure import decode_livery_structure, SemanticLiveryError
from .source_envelope import unpack_source_bytes
from .source_structure import read_section_envelope, SECTION_LABELS
from .source_leaf_records import reference_word_alias
from .native_affine_trial import Affine, group_basis
from .native_skew_candidate import shape_shear_candidate
from .first_party_affine_bridge import _candidate_components, SECTION_QUARTER_TURNS
from .first_party_privacy_absence import inspect_absent_protected_groups

# 覆いの文脈の件数の並び（native_layers の source_contextual_mask_evidence と、自前の部品の出力の並び）
_MASK_EVIDENCE_KEYS = (
    'attribute_0x40_groups',
    'attribute_0x50_groups',
    'counted_0x60_groups',
    'contextual_descendant_shapes',
    'contextual_masked_shapes',
    'contextual_unmasked_shapes',
    'counted_0x60_descendant_shapes',
)


class NativeCanonicalRejected(ValueError):
    """他製品のデコーダーを呼ばず、未対応の原本文法を明示的に拒否する。"""


def _signed_y(group):
    if group.flags & 0x10:
        if len(group.optional_four) != 4:
            raise NativeCanonicalRejected('invalid signed Y extension')
        return struct.unpack('<f', group.optional_four)[0]
    return group.scale


def _group_parents(section):
    parents = {}
    for leaf in section.shapes:
        for parent, child in zip(leaf.group_chain, leaf.group_chain[1:]):
            if child in parents and parents[child] != parent:
                raise NativeCanonicalRejected('ambiguous parent group')
            parents[child] = parent
    return parents


def _validated_odd_transform_before_group(body: bytes, after: int, next_group) -> bool:
    """Group境界の奇数Transformを属性・子ビットマップで検証する。

    任意の奇数バイトをMask制御とはみなさず、Transform 16-byteと
    後続の1-byte-framed Groupを構造解析済みcount/bitmapへ照合する。
    """
    if next_group is None or next_group.prefix != 0 or next_group.flags != 0x10:
        return False
    marker = after + 4
    if marker + 18 > len(body) or not (body[marker] & 1):
        return False
    x, y, sx, rotation = struct.unpack_from('<4f', body, marker + 1)
    if not (all(math.isfinite(v) for v in (x, y, sx, rotation))
            and 0.0001 <= abs(sx) <= 200 and abs(rotation) <= 10000):
        return False
    header = marker + 17
    if header + 7 > len(body) or body[header] != 0x3F:
        return False
    count, blocks = struct.unpack_from('<HH', body, header + 1)
    if not (2 <= count <= 15000 and blocks == (count + 7) // 8
            and header + 7 + blocks <= len(body)
            and count == next_group.child_count):
        return False
    return body[header + 7:header + 7 + blocks] == next_group.child_bitmap


def native_layers(payload: bytes, *, allow_source_verified_signed_y: bool = True,
                  allow_contextual_mask_candidate: bool = True,
                  allow_source_skew_range_research: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """参照製品を読み込まず実行せず、FH6の11面を復号する。

    値は原本バイト列とGroupビットマップ境界から再構成する。
    未知のGroupフラグ、保護情報のあるラッパー、不完全なレイアウトは
    図柄を欠損させたまま表示せず、明示的に拒否する。
    """
    if not isinstance(payload, bytes):
        raise NativeCanonicalRejected('vlrc payload bytes required')
    parsed = decode_livery_structure(payload)
    env = read_section_envelope(payload)
    # 検証済みツリーを再利用し、大型C_liveryの二重構造解析を避ける。
    # 保護Groupの判定規則・fail-closed動作は変更しない。
    privacy = inspect_absent_protected_groups(payload, parsed=parsed)
    if privacy is None:
        raise NativeCanonicalRejected('positive/ambiguous protected group is not yet supported')
    if len(parsed.sections) != len(SECTION_LABELS):
        raise NativeCanonicalRejected('unexpected section schema')
    layers = []
    # 描画を一切変更せず、元Group/Mask所有の匿名件数だけを診断する。
    # この件数はXbox外観やMask画素同値の承認ではない。
    source_mask_evidence = dict.fromkeys(_MASK_EVIDENCE_KEYS, 0)
    for sec in parsed.sections:
        groups = {g.start: g for g in sec.groups}
        if len(groups) != len(sec.groups):
            raise NativeCanonicalRejected('duplicate group offset')
        # 以下のフラグ組合せには原本・旧描画器の一致証拠がある。
        # 未観測の組合せは推測で解釈しない。
        approved = (0x00, 0x20, 0x30, 0x60, 0x70)
        for group in sec.groups:
            if group.flags == 0x40:
                source_mask_evidence['attribute_0x40_groups'] += 1
            elif group.flags == 0x50:
                source_mask_evidence['attribute_0x50_groups'] += 1
            elif group.flags == 0x60:
                source_mask_evidence['counted_0x60_groups'] += 1
            # 作業branch: 元0x60 Count付きMaskと後続trailing状態の所有を
            # 原本文法から判定。0x40/0x50を無条件Mask扱いせず、未確定は拒否。
            # 通常入口でこの実装を利用するが、Xbox/Windows合格前はmainへ入れない。
            if group.flags in approved or (
                allow_contextual_mask_candidate and group.flags in (0x40, 0x50)
            ):
                continue
            # 参照製品のCGROUP.mdではビット0x10に独立格納されたsigned-Yのf32を確認。
            # 既存の0x30/0x70のGroup座標基底は同じフィールドを既に消費する。
            # 妥当性を確認できた単独0x10のみ受け入れ、0x11/0x50/0x71の
            # Mask・本人識別の意味を推測しない。
            if not allow_source_verified_signed_y or group.flags != 0x10:
                raise NativeCanonicalRejected(
                    f'unvalidated group-flag combination 0x{group.flags:02X}')
            if len(group.optional_four) != 4 or group.optional_eight:
                raise NativeCanonicalRejected('signed-Y descriptor incomplete')
            signed_y = struct.unpack('<f', group.optional_four)[0]
            if not math.isfinite(signed_y) or not 1.e-7 < abs(signed_y) < 5000:
                raise NativeCanonicalRejected('signed-Y field invalid')

        parents = _group_parents(sec)
        # 先頭子がインライン拡張変換（0x30）で始まり子が複数ある場合、
        # 面ルート自体を描画ツリーのルートとする。別のラッパーノードは数えない。
        # これは原本構造の規則であり、車種名・面名による特例ではない。
        direct_section_root = (
            bool(sec.groups) and sec.groups[0].child_count > 1
            and len(sec.groups) > 1
            and sec.groups[1].start == sec.groups[0].start + sec.groups[0].byte_length
            and sec.groups[1].prefix is None
            and sec.groups[1].flags == 0x30
        )
        worlds: dict[tuple[int, ...], Affine] = {(): Affine()}
        # 同じ祖先の並びの図形が多いので、祖先のグループの印から決まる値を並びごとに 1 回だけ求める
        # （2026-11-20。値は以前の図形ごとの計算と同じ）。
        chain_flags: dict[tuple[int, ...], tuple] = {}
        for leaf in sec.shapes:
            chain = leaf.group_chain
            if not chain:
                raise NativeCanonicalRejected('orphan shape')
            if chain not in worlds:
                current = Affine()
                for position in chain:
                    group = groups.get(position)
                    if group is None:
                        raise NativeCanonicalRejected('missing ancestor')
                    # グループの回転は保存された向きのまま使う（2026-11-18）。以前は、前置 1 の入れ子のグループが倍率つきの
                    # 子グループから始まるとき向きを反転していた（10 月の研究で以前の自作の描画 r806 に合わせた決まりで、
                    # ゲームでの確認は無かった）。PC 版・Xbox 版 FH6 の画面（Car 3414 の BOMBERGIRL PINE のロゴが水平）と、
                    # 反転に当たるペイント 21 件のゲームの見本の画像の比較で、反転しない形だけが一致した。
                    current = current.then_local(group_basis(group, rotation_sign=1))
                worlds[chain] = current
            world = worlds[chain].then_local(shape_shear_candidate(
                leaf, rotation_sign=1, source_bound_research=allow_source_skew_range_research
            ))
            if not math.isfinite(world.determinant) or abs(world.determinant) < 1e-20:
                raise NativeCanonicalRejected('invalid leaf transform')
            _, components = _candidate_components(world, sec.name)
            flags_info = chain_flags.get(chain)
            if flags_info is None:
                ancestor_flags = tuple(groups[g].flags for g in chain)
                flags_info = (ancestor_flags,
                              sum(flag == 0x60 for flag in ancestor_flags),
                              any(flag in (0x40, 0x50) for flag in ancestor_flags),
                              any(flag == 0x60 for flag in ancestor_flags))
                chain_flags[chain] = flags_info
            ancestor_flags, chain_mask_depth, has_context_group, has_counted_group = flags_info
            if not all(math.isfinite(v) for v in components):
                raise NativeCanonicalRejected('invalid projected transform')
            after = leaf.source_offset + leaf.byte_length
            achromatic = leaf.color_rgba[0] == leaf.color_rgba[1] == leaf.color_rgba[2]
            if allow_contextual_mask_candidate:
                # 参照製品と元C_liveryのoffset/bitmapsに基づく源レコード意味判定。
                # 明示されたcounted 0x60 Groupだけを強制Mask祖先とする。
                # 0x40/0x50/0x70の高位bitを無条件Mask継承とみなさない。
                group_mask_depth = chain_mask_depth
                next_group = groups.get(after)
                if not group_mask_depth and achromatic and 0x50 in ancestor_flags:
                    raise NativeCanonicalRejected(
                        'contextual 0x50 achromatic mask semantics unresolved')
                # 0x10 Group先頭01と直前図形のtrailing stateを区別。
                # 0x70祖先の末尾ではGroup境界を越えるMask継承を避ける。
                group_boundary_control = bool(
                    next_group is not None and next_group.prefix == 1
                    and next_group.flags == 0x10 and leaf.control_byte == 1
                    and 0x70 in ancestor_flags
                )
                raw_record_state = (
                    after < len(env.body) and env.body[after] == 1
                    and not group_boundary_control
                )
                transform_state = _validated_odd_transform_before_group(
                    env.body, after, next_group
                ) if achromatic and not group_mask_depth else False
                # 記録の直後の 01（記録の状態）は、色を問わずマスクにする（2026-11-18）。
                # 根拠：PC 版 FH6 の画面（利用者の撮影）。Car 3173・3434 の前の窓ガラス（最後のピンクの層が下地ごと消え、
                # 窓が透明）、Car 3414（黒い X が見え、赤いテープは見えない）、Car 302（輪と文字が青緑）が、
                # 色付きの層もマスクにしたときだけ一致する。ゲームの見本の画像（bigThumb）との比較 48 件でも一致が増える。
                # 参照製品は色付きの層の記録の状態をマスクにしないが、FH6 の画面と合わないので採らない。
                # グループの種類（0x40・0x70）や変換の状態によるマスクは、今までどおり灰色（R=G=B）の層だけ。
                record_mask = bool(raw_record_state) or bool(achromatic and (
                    transform_state
                    or 0x40 in ancestor_flags
                    or (0x70 in ancestor_flags and not group_boundary_control)
                ))
            else:
                # 開発用比較の既存経路。製品は上の源レコード意味判定を使う。
                group_mask_depth = sum(
                    bool(groups[g].flags & 0x40) and not bool(groups[g].flags & 0x10)
                    for g in chain
                )
                record_mask = (after < len(env.body) and env.body[after] == 1
                               and achromatic)
            is_mask = bool(group_mask_depth or record_mask)
            if has_context_group:
                source_mask_evidence['contextual_descendant_shapes'] += 1
                source_mask_evidence[
                    'contextual_masked_shapes' if is_mask else 'contextual_unmasked_shapes'
                ] += 1
            if has_counted_group:
                source_mask_evidence['counted_0x60_descendant_shapes'] += 1
            mask_source = ('group+record' if group_mask_depth and record_mask else
                           'group' if group_mask_depth else 'record' if record_mask else 'none')
            raster = bool(leaf.shape_word & 0x8000)
            marker = env.body[leaf.source_offset:leaf.source_offset + (2 if leaf.control_byte is not None else 1)]
            if len(marker) != (2 if leaf.control_byte is not None else 1):
                raise NativeCanonicalRejected('truncated leaf marker')
            layers.append({
                'shape_id': reference_word_alias(leaf.shape_word),
                'data': [*components, int(is_mask)],
                'color_rgba': list(leaf.color_rgba),
                'mask': is_mask,
                'mask_source': mask_source,
                'mask_group_depth': group_mask_depth,
                'group_depth': len(chain) - int(direct_section_root),
                'record_mask_authoritative': False,
                'source_offset': leaf.source_offset,
                'section': sec.name,
                'marker_hex': marker.hex(),
                'is_raster_logo': raster,
                'raster_id': leaf.shape_word & 0x7fff if raster else None,
                'flags': leaf.control_byte or 0,
                'section_start': sec.groups[0].start if sec.groups else None,
            })
    if len(layers) != sum(sec.declared_shapes for sec in parsed.sections):
        raise NativeCanonicalRejected('lost shape')
    report = _decoder_report(
        payload, env, [(sec.name, sec.declared_shapes, len(sec.shapes)) for sec in parsed.sections],
        len(layers), source_mask_evidence, allow_contextual_mask_candidate,
    )
    return layers, report, privacy


def _decoder_report(payload: bytes, env, sections, decoded_layers: int, source_mask_evidence: dict[str, int],
                    contextual: bool) -> dict[str, Any]:
    """解読の報告（decoder_report）。sections は（面の名前, 宣言の数, 読めた数）の並び。"""
    return {
        'source_kind': 'clivery', 'payload_size': len(payload),
        'section_counts': {name: declared for name, declared, _ in sections},
        'decoded_layers': decoded_layers, 'warnings': [],
        'section_reports': [{'section': name, 'target': declared,
            'decoded': decoded, 'boundary_reason': 'complete_strict_structure',
            'clean_counter_residual': False, 'incomplete_counted_groups': 0,
            'missing_counted_children': 0} for name, declared, decoded in sections],
        'clean_counter_residuals': [],
        'source_contextual_mask_evidence': source_mask_evidence,
        'native_canonical': {'mode': 'first_party_complete_tree_and_layers',
            'vendor_decoder_called': False, 'xbox_parity_verified': False,
            'protected_group_positive_verified': False,
            'render_output_approved': False,
            'contextual_mask_candidate': contextual},
        'gyvl_offset': env.gyvl_offset, 'body_start': env.body_start,
        'body_end': env.body_end,
    }


# 自前の部品の出力の印（bit1-2 覆いの出どころ、bit3-4 図形の先頭の印のバイト）
_FAST_MASK_SOURCES = ('none', 'record', 'group', 'group+record')
_FAST_MARKERS = ('02', '0002', '0102')


def _native_surface_json_fast(payload: bytes, decoder: str):
    """自前の部品（Rust）で解読する速い道（2026-11-20、FH6 に近づける案 ④）。

    通常の入口（覆いの文脈の候補あり・研究の範囲なし）の native_layers と build_surface_design と同じ出力を作る。
    木の読み取り・図形ごとの変換と覆いの判定・保護の印が無いことの確かめは部品が行い、出力の組み立ては Python が行う。
    部品が無い・使えない・扱わない入力のときは None を返し、呼び出し側は今までの処理で解読する
    （例外とその文言も今までどおり）。
    """
    try:
        from tools.livery import native_kernels
    except ImportError:
        return None
    from .canonical import RASTER_LOGO_WORD, surface_design_from_shapes
    try:
        # native_layers と同じ入力の確かめ（decode_livery_structure は解いた本文をもう一度 unpack する）
        if unpack_source_bytes(payload) is not payload or len(payload) < 20:
            return None
        env = read_section_envelope(payload)
        counts = tuple(env.section_counts)
        if len(counts) != len(SECTION_LABELS):
            return None
        turns = bytes(SECTION_QUARTER_TURNS.get(label, 0) for label in SECTION_LABELS)
        decoded = native_kernels.decode_livery_layers(env.body, counts, turns)
    except Exception:  # noqa: BLE001  速い道で扱えない入力は、今までの処理に任せる
        return None
    if decoded is None:
        return None
    records, evidence = decoded
    shapes_per_section: list[list[dict[str, Any]]] = [[] for _ in SECTION_LABELS]
    raster_logos = 0
    raster_ids: set[int] = set()
    aliases: dict[int, int] = {}
    # canonical._shape_entry と同じ項目・同じ並び
    for (x, y, sx, sy, angle, shear, offset, mask_depth, depth, word, section, bits,
         red, green, blue, alpha) in native_kernels.LIVERY_RECORD.iter_unpack(records):
        raw = aliases.get(word)
        if raw is None:
            raw = aliases[word] = reference_word_alias(word) & 0xFFFF
        if word & 0x8000:
            type_word = RASTER_LOGO_WORD
            raster_id = (word & 0x7FFF) or (raw & 0x7FFF)
            raster = True
            raster_logos += 1
            if raster_id:
                raster_ids.add(raster_id)
        else:
            type_word = raw
            raster_id = None
            raster = False
        mask = bool(bits & 1)
        shapes_per_section[section].append({
            "type": 0x100000 + type_word,
            "type_word": type_word,
            "type_word_hex": f"0x{type_word:04x}",
            "data": [x, y, sx, sy, angle, shear, 1.0 if mask else 0.0],
            "color": [red, green, blue, alpha],
            "mask": mask,
            "mask_source": _FAST_MASK_SOURCES[(bits >> 1) & 3],
            "mask_group_depth": mask_depth,
            "group_depth": depth,
            "record_mask_authoritative": False,
            "source_offset": offset,
            "source_marker": _FAST_MARKERS[(bits >> 3) & 3],
            "is_raster_logo": raster,
            "raster_id": raster_id,
            "source_raw_type_word": raw,
        })
    shape_count = sum(len(shapes) for shapes in shapes_per_section)
    report = _decoder_report(
        payload, env, [(label, count, count) for label, count in zip(SECTION_LABELS, counts)],
        shape_count, dict(zip(_MASK_EVIDENCE_KEYS, evidence)), True,
    )
    privacy = {
        'source_owned': struct.unpack_from('<I', payload, 8)[0] != 1,
        'foreign_group_count': 0,
        'contains_foreign_groups': False,
        'protected_group_offsets': [],
    }
    result = surface_design_from_shapes(SECTION_LABELS, payload, shapes_per_section, shape_count,
                                        raster_logos, raster_ids, report, decoder=decoder)
    return result, privacy


def native_surface_json(path, *, allow_contextual_mask_candidate: bool = True,
                        allow_source_skew_range_research: bool = False):
    """通常製品入口の面表現を源C_liveryから生成。外部コード実行・不明入力の代用禁止。"""
    from pathlib import Path
    from .canonical import build_surface_design
    source = Path(path) / 'C_livery' if Path(path).is_dir() else Path(path)
    payload = unpack_source_bytes(source.read_bytes())
    if allow_contextual_mask_candidate and not allow_source_skew_range_research:
        # 自前の部品で解読できれば、それを使う（結果は下の処理と同じ）。
        fast = _native_surface_json_fast(
            payload, 'lo4fh6-independent-native-contextual-source-standard-candidate')
        if fast is not None:
            return fast
    layers, report, privacy = native_layers(
        payload, allow_contextual_mask_candidate=allow_contextual_mask_candidate,
        allow_source_skew_range_research=allow_source_skew_range_research,
    )
    result = build_surface_design(
        SECTION_LABELS, payload, layers, report,
        decoder=('lo4fh6-independent-native-contextual-source-standard-candidate'
                 if allow_contextual_mask_candidate else 'lo4fh6-independent-native-provisional'),
    )
    return result, privacy
