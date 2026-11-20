from __future__ import annotations

from pathlib import Path
import hashlib
import math
import tempfile
import time
from typing import Any, Hashable

from fh_livery_preview_core.canonical import livery_to_surface_json
from fh6_gpu_livery_parity_input import resolve_readable_c_livery
from fh6_vinyl_local_geometry import extract_selected_zip, resource_key_for_shape_word
from fh_livery_preview_core.livery_preview import resource_location_key
from tools.livery.gpu_vector_geometry import build_gpu_geometry_pack, remember_geometry, remembered_geometry
from tools.livery.process_file_memo import file_identity
from tools.livery.gpu_vector_stream import SECTION_NAMES, build_gpu_vector_stream_from_design
from tools.livery.gpu_section_coverage import require_gpu_source_contract_sections

RUNTIME_FORMAT = "lo4fh6_gpu_livery_production_runtime_v1"


def _extract_selected_vinyls(
    vinyl_zip_path: Path, scratch_root: Path, shape_words: list[int]
) -> tuple[Path, int, dict[tuple[str, int], dict[str, Any]], dict[tuple[str, int], tuple], Hashable | None]:
    """extract_selected_zip(vinyl_zip_path, scratch_root, shape_words, payloads_out=…, write_files=False) の代わり。

    前のペイントで同じ Vinyls.zip から作った資源の部品（remembered_geometry）があれば、その資源は解かず、
    残りの図形だけを extract_selected_zip で解く（2026-11-20）。覚えた部品は前に同じファイルから解いて作った物で、
    できる形の束と要約は全部を解いたときと同じ。例外も同じ（覚えた資源は解けた物だけなので、図形番号の不正・
    資源の欠け・解けない資源は、残りの図形の中にある）。

    返り値：(図形の場所, 選んだ資源の数, 解いた結果, 覚えていた部品, Vinyls.zip の識別)。識別が None なら、
    この回に作った部品を覚えない（途中でファイルが変わったときなど）。
    """
    scope: Hashable | None = file_identity(vinyl_zip_path)
    requested_words = sorted({int(value) & 0xFFFF for value in shape_words if int(value) & 0xFFFF})
    requested_keys = [resource_key_for_shape_word(word) for word in requested_words]
    # 形の束を作る側（resource_location_key）と同じ資源を指すときだけ使う（今は全部の番号で同じ）。
    usable = (scope is not None and bool(requested_keys)
              and all(key is not None and key == resource_location_key(word)
                      for word, key in zip(requested_words, requested_keys)))
    remembered = remembered_geometry(scope, set(requested_keys)) if usable else {}
    if remembered:
        missing_words = [word for word, key in zip(requested_words, requested_keys) if key not in remembered]
        payloads: dict[tuple[str, int], dict[str, Any]] = {}
        if missing_words:
            vinyl_root, _summary = extract_selected_zip(
                vinyl_zip_path, scratch_root, missing_words, payloads_out=payloads, write_files=False
            )
        else:
            # 全部覚えていた：Vinyls.zip を開かない（場所は extract_selected_zip が返す物と同じ）。
            vinyl_root = scratch_root.expanduser().resolve() / "Vinyls"
        if file_identity(vinyl_zip_path) == scope:
            return vinyl_root, len(set(requested_keys)), payloads, remembered, scope
        # 途中で Vinyls.zip が変わった：覚えた部品を使わずに、全部の図形を解き直す。
        scope = None
    payloads = {}
    vinyl_root, summary = extract_selected_zip(
        vinyl_zip_path, scratch_root, shape_words, payloads_out=payloads, write_files=False
    )
    if scope is not None and file_identity(vinyl_zip_path) != scope:
        scope = None
    return vinyl_root, int(summary.get("selected_resource_count") or 0), payloads, {}, scope


def _geometry_pack_with_remembered(
    vinyl_root: Path,
    shape_words: list[int],
    payloads: dict[tuple[str, int], dict[str, Any]] | None,
    remembered: dict[tuple[str, int], tuple],
    scope: Hashable | None,
) -> tuple[bytes, dict[str, Any]]:
    """build_gpu_geometry_pack(vinyl_root, shape_words, strict_assets=True, payloads=payloads or None) と同じ結果。

    remembered（_extract_selected_vinyls の返り値）の資源は覚えた部品を使い、この回に解いた資源の部品を scope で
    覚える（2026-11-20）。
    """
    new_pieces: dict[tuple[str, int], tuple] | None = {} if scope is not None else None
    geometry_pack, geometry = build_gpu_geometry_pack(
        vinyl_root,
        shape_words,
        strict_assets=True,
        # 覚えた部品を使うときは、解いた結果が空でも（全部覚えていたとき）辞書のまま渡す。
        payloads=payloads if remembered else (payloads or None),
        remembered=remembered or None,
        pieces_out=new_pieces,
    )
    if new_pieces:
        remember_geometry(scope, new_pieces)
    return geometry_pack, geometry

# render_contract.py はFH6原本の面名を維持する一方、GPUストリームでは
# 描画器用に正規化した名前を使う。窓の面名は単純な小文字変換ではないため、
# 対応関係を明示的に定義する。
CONTRACT_SECTION_TO_STREAM_SECTION = {
    "Front": "front",
    "Back": "back",
    "Top": "top",
    "Left": "left",
    "Right": "right",
    "Spoiler": "wing",
    "FrontWindshield": "front_windscreen",
    "BackWindshield": "rear_windscreen",
    "TopWindow": "top_window",
    "LeftWindow": "left_window",
    "RightWindow": "right_window",
}


def _canonical_section_profile(surface: dict[str, Any], stream_record_count: int) -> dict[str, Any]:
    shapes = [item for item in (surface.get("shapes") or []) if isinstance(item, dict)]
    mask_count = 0
    raster_count = 0
    valid_affine_count = 0
    opaque = 0
    semitransparent = 0
    transparent = 0
    isfinite = math.isfinite
    for shape in shapes:
        # 近道：解読の部品が作る形の図形（data が float 6 つと覆いの印、色が int 4 つ）は、下と同じ数え方を 1 回の
        # 流れで行う（2026-11-20）。条件を全部確かめてから数えるので、合わなければ下の今までの数え方だけに任せる。
        fast_data = shape.get("data")
        fast_color = shape.get("color")
        if (type(fast_data) is list and len(fast_data) == 7 and type(fast_color) is list and len(fast_color) == 4
                and type(fast_color[3]) is int):
            x, y, sx, sy, rotation, skew, mask_value = fast_data
            if (type(x) is float and type(y) is float and type(sx) is float and type(sy) is float
                    and type(rotation) is float and type(skew) is float):
                if shape.get("mask") or mask_value:
                    mask_count += 1
                if shape.get("is_raster_logo"):
                    raster_count += 1
                if (isfinite(x) and isfinite(y) and isfinite(sx) and isfinite(sy) and isfinite(rotation)
                        and isfinite(skew)):
                    valid_affine_count += 1
                alpha = max(0, min(255, fast_color[3]))
                if alpha <= 0:
                    transparent += 1
                elif alpha >= 255:
                    opaque += 1
                else:
                    semitransparent += 1
                continue
        data = list(shape.get("data") or [])
        if bool(shape.get("mask") or (len(data) >= 7 and data[6])):
            mask_count += 1
        if bool(shape.get("is_raster_logo")):
            raster_count += 1
        if len(data) >= 6:
            try:
                values = [float(value) for value in data[:6]]
            except (TypeError, ValueError):
                values = []
            if len(values) == 6 and all(math.isfinite(value) for value in values):
                valid_affine_count += 1
        color = shape.get("color")
        alpha = 255
        if isinstance(color, (list, tuple)) and len(color) >= 4:
            try:
                alpha = max(0, min(255, int(color[3])))
            except (TypeError, ValueError):
                alpha = 255
        if alpha <= 0:
            transparent += 1
        elif alpha >= 255:
            opaque += 1
        else:
            semitransparent += 1
    return {
        "canonical_shape_count": len(shapes),
        "valid_affine_shape_count": valid_affine_count,
        "stream_record_count": int(stream_record_count),
        "dropped_before_stream_count": max(0, valid_affine_count - int(stream_record_count)),
        "paint_shape_count": len(shapes) - mask_count,
        "mask_shape_count": mask_count,
        "raster_shape_count": raster_count,
        "opaque_color_shape_count": opaque,
        "semitransparent_color_shape_count": semitransparent,
        "transparent_color_shape_count": transparent,
    }



def build_gpu_livery_production_runtime(
    source_path: Path | str,
    *,
    vinyl_resource_root: Path | str | None = None,
    vinyl_zip_path: Path | str | None = None,
    decals_zip_path: Path | str | None = None,
    gamedb_path: Path | str | None = None,
    render_contract: dict[str, Any],
    source_context_mask_research: bool = False,
    canonical_design: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Production Viewer 用の GPU runtime input をメモリ上で組み立てる。

    r364 では通常 Viewer が ``Vinyls.zip`` から利用中 shape だけを一時復号できる。
    既存の ``vinyl_resource_root`` は回帰診断と CPU fallback 用に互換維持する。
    geometry pack はどちらの経路でも session-local とし、永続保存しない。
    """
    if (vinyl_resource_root is None) == (vinyl_zip_path is None):
        raise ValueError("vinyl_resource_root と vinyl_zip_path はどちらか一方だけ指定してください")

    runtime_started = time.perf_counter()
    profile: dict[str, float] = {}

    phase = time.perf_counter()
    source = resolve_readable_c_livery(Path(source_path))
    profile["source_resolve_seconds"] = time.perf_counter() - phase

    phase = time.perf_counter()
    # 通常Viewer・Organizer・監査と同じC_livery製品デコーダーを使う。
    # 研究用ON/OFFで元Mask/11面/Rasterの復号結果を切り替えない。
    # 未解決のGroup末尾意味論は正規デコーダー自身が明示拒否する。
    # 準備の前半が同じ C_livery（中身の SHA で照合済み）を同じデコーダーで解読したキャッシュがあれば、それを使う。
    if canonical_design is not None:
        design = canonical_design
    else:
        design = livery_to_surface_json(source, decoder="canonical")
    profile["canonical_decode_seconds"] = time.perf_counter() - phase
    try:
        source_bytes = source.stat().st_size
    except OSError:
        source_bytes = len(source.read_bytes())

    phase = time.perf_counter()
    # 原本11面の図形欠落を診断扱いにせず、通常入口では明示エラーにする。
    vector_stream, stream = build_gpu_vector_stream_from_design(
        design, source_bytes=source_bytes, strict_complete=True
    )
    profile["vector_stream_seconds"] = time.perf_counter() - phase

    surfaces = {
        str(item.get("name") or ""): item
        for item in (design.get("surfaces") or [])
        if isinstance(item, dict)
    }
    stream_section_counts = dict(stream.get("section_counts") or {})
    canonical_section_profiles = {
        contract_name: _canonical_section_profile(
            surfaces.get(stream_name) or {}, int(stream_section_counts.get(stream_name) or 0)
        )
        for contract_name, stream_name in CONTRACT_SECTION_TO_STREAM_SECTION.items()
    }
    contract_section_records = {
        str(item.get("section") or ""): item
        for item in (render_contract.get("sections") or [])
        if isinstance(item, dict) and str(item.get("section") or "")
    }
    # 元C_liveryに図形がある面が車両Mask契約から消えていたら、
    # JSが存在する面だけを描いて成功とするより先に明示停止する。
    # 形状0面は原本に適合する場合に限り、通常どおり省略可。
    source_coverage = require_gpu_source_contract_sections(design, render_contract)

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    selected_resource_count = 0
    # 使う図形だけを Vinyls.zip から復号し、一時ファイルに書いて読み直さずにメモリで受け渡す（2026-11-19。
    # r364 の「常駐の図形のキャッシュを使わず、使った後は捨てる」はそのまま）。
    # 2026-11-20：前のペイントで同じ Vinyls.zip から作った資源の部品は、同じプロセスの中で使い回す
    # （_extract_selected_vinyls。ディスクには書かない）。
    selected_payloads: dict[tuple[str, int], dict[str, Any]] | None = None
    remembered_pieces: dict[tuple[str, int], tuple] = {}
    vinyl_scope: Hashable | None = None
    if vinyl_zip_path is not None:
        phase = time.perf_counter()
        temporary_directory = tempfile.TemporaryDirectory(prefix="lo4fh6-gpu-vinyl-")
        runtime_vinyl_root, selected_resource_count, selected_payloads, remembered_pieces, vinyl_scope = (
            _extract_selected_vinyls(
                Path(vinyl_zip_path),
                Path(temporary_directory.name),
                stream.get("unique_shape_words") or [],
            )
        )
        profile["selected_vinyl_extract_seconds"] = time.perf_counter() - phase
        geometry_source_mode = "selected-vinyls-zip"
    else:
        runtime_vinyl_root = Path(vinyl_resource_root).expanduser().resolve()
        geometry_source_mode = "local-vinyl-cache"

    try:
        phase = time.perf_counter()
        raster_sections: list[str] = []
        # 実C_liveryのsurface名はleft等、契約のSection名はLeft等。
        # この対応を使わないとraster-logo未対応入力を黙って欠落させる。
        # RenderContractに含まれないSectionも無告知で省略しない。
        for section, stream_section in CONTRACT_SECTION_TO_STREAM_SECTION.items():
            surface = surfaces.get(stream_section) or {}
            if any(bool(shape.get("is_raster_logo")) for shape in (surface.get("shapes") or []) if isinstance(shape, dict)):
                raster_sections.append(section)

        profile["raster_logo_gate_seconds"] = time.perf_counter() - phase
        raster_decal_pack = None
        raster_decal_summary: dict[str, Any] = {"count": 0, "bytes": 0}
        source_decals_sha256 = None
        if raster_sections:
            # 原本Rasterを製品GPUへ標準自動接続。未インストールなら描画を省略せず停止。
            if decals_zip_path is None:
                raise RuntimeError("原本Raster Logoを通常描画するには署名確認可能なDecals.zipが必要です")
            # GameDB が無いときは、ゲームのロゴのステッカーを止めずに省く（build_gpu_raster_decal_pack、
            # 理由 gamedb-unavailable。画面の注意の帯に出す。2026-11-21 利用者の決定）。
            from tools.livery.gpu_raster_decal_pack import build_gpu_raster_decal_pack
            raster_ids = {
                int(shape.get("raster_id") or 0)
                for name in CONTRACT_SECTION_TO_STREAM_SECTION.values()
                for shape in ((surfaces.get(name) or {}).get("shapes") or [])
                if isinstance(shape, dict) and bool(shape.get("is_raster_logo"))
            }
            decals_archive = Path(decals_zip_path).expanduser().resolve(strict=True)
            if not decals_archive.is_file() or decals_archive.name.casefold() != "decals.zip":
                raise ValueError("Raster Logoの原本アーカイブ名・所在が不正です")
            with decals_archive.open("rb") as original_decal_zip:
                source_decals_sha256 = hashlib.file_digest(
                    original_decal_zip, "sha256"
                ).hexdigest()
            # ゲームに無いステッカー（他のツールで取り込んだペイントなど）は、透明にして省き、目録に記録する
            # （2026-11-18 利用者の決定。黙って省かず、画面と撮影の記録に出す）。
            raster_decal_pack, raster_decal_summary = build_gpu_raster_decal_pack(
                decals_archive, raster_ids, gamedb_path=gamedb_path, omit_missing=True
            )
            if int(raster_decal_summary.get("count") or 0) != len(raster_ids):
                raise RuntimeError("Raster Logoの原本IDとRGBAパック件数が不一致です")
        profile["raster_logo_source_seconds"] = time.perf_counter() - phase

        phase = time.perf_counter()
        geometry_pack, geometry = _geometry_pack_with_remembered(
            runtime_vinyl_root,
            stream.get("unique_shape_words") or [],
            selected_payloads,
            remembered_pieces,
            vinyl_scope,
        )
        profile["geometry_pack_seconds"] = time.perf_counter() - phase
    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()
    profile["total_seconds"] = time.perf_counter() - runtime_started

    if (render_contract.get("cpu_shadow_policy") != "gpu-only"
            or render_contract.get("paint_rasterizer") != "webgl2-only"
            or (render_contract.get("files") or {}).get("paint")):
        raise RuntimeError("CPU livery paint removed; exact GPU-only contract required")
    shadow_policy = "gpu-only"
    section_index = {name: index for index, name in enumerate(SECTION_NAMES)}
    contract_section_index = {
        contract_name: section_index[stream_name]
        for contract_name, stream_name in CONTRACT_SECTION_TO_STREAM_SECTION.items()
    }
    manifest = {
        "format": RUNTIME_FORMAT,
        "read_only": True,
        "source_label": source.parent.name,
        # 研究フラグは受け取っても描画意味論を変更しない（旧CLI互換入力）。
        "source_context_mask_research": False,
        "source_context_mask_xbox_approved": False,
        "source_context_mask_policy": "native-source-standard-candidate__xbox-unverified",
        "raster_decals": {
            "count": raster_decal_summary["count"],
            "pack_bytes": raster_decal_summary["bytes"],
            "source_verified": bool(raster_sections and raster_decal_pack is not None
                                    and source_decals_sha256),
            "source_archive_sha256": source_decals_sha256,
            "gamedb_sha256": raster_decal_summary.get("gamedb_sha256"),
            "source_binding_contract": raster_decal_summary.get("source_binding_contract"),
            "source_asset_ids": raster_decal_summary.get("source_asset_ids", {}),
            "research_only": False,
            "omission_policy": raster_decal_summary.get("omission_policy", "reject"),
            "omitted": list(raster_decal_summary.get("omitted") or []),
            "omitted_layer_count": sum(
                1
                for name in CONTRACT_SECTION_TO_STREAM_SECTION.values()
                for shape in ((surfaces.get(name) or {}).get("shapes") or [])
                if isinstance(shape, dict) and bool(shape.get("is_raster_logo"))
                and int(shape.get("raster_id") or 0) in {
                    int(item.get("raster_id") or 0) for item in (raster_decal_summary.get("omitted") or [])
                }
            ),
        },
        "section_index": section_index,
        "contract_section_index": contract_section_index,
        "section_counts": dict(stream.get("section_counts") or {}),
        "source_section_coverage": source_coverage,
        "canonical_section_profiles": canonical_section_profiles,
        "stream": {
            "record_count": int(stream.get("stream_record_count") or 0),
            "stream_bytes": len(vector_stream),
            "unique_shape_word_count": int(stream.get("unique_shape_word_count") or 0),
        },
        "geometry": {
            "entry_count": int(geometry.get("entry_count") or 0),
            "pack_bytes": len(geometry_pack),
            "local_asset_entry_count": int(geometry.get("local_asset_entry_count") or 0),
            "fallback_entry_count": int(geometry.get("fallback_entry_count") or 0),
            "source_mode": geometry_source_mode,
            "selected_resource_count": int(selected_resource_count),
            "geometry_contract": str(geometry.get("geometry_contract") or ""),
            "reverse_or_degenerate_triangles_skipped": int(
                geometry.get("reverse_or_degenerate_triangles_skipped") or 0
            ),
            "transparent_triangles_skipped": int(geometry.get("transparent_triangles_skipped") or 0),
            "invalid_triangles_skipped": int(geometry.get("invalid_triangles_skipped") or 0),
            "persistent_bytes": 0,
        },
        "preparation_profile_seconds": {
            key: round(float(value), 6) for key, value in profile.items()
        },
        "runtime_memory_footprint": {
            "vector_stream_bytes": len(vector_stream),
            "geometry_pack_bytes": len(geometry_pack),
            "session_input_bytes": len(vector_stream) + len(geometry_pack),
            "persistent_geometry_cache_bytes": 0,
        },
        "adapter": {
            "revision": "r379",
            "solid_raster_mode": "pillow-grid-centers",
            "solid_mask_raster_mode": "pillow-grid-centers",
            "solid_mask_placement_alpha_mode": "placement-alpha",
            "shadow_policy": shadow_policy,
            "section_composite_supersample": 2,
            "section_resolve": "browser-high-quality-premultiplied",
            "projection_resample_diagnostic": "alpha-gradient-boundary-v1",
            "projection_resample_acceptance": "strict-1px-gradient-only-v1",
            "side_orientation_diagnostic": "rgba-alpha-dihedral-v1",
            "side_source_coverage_diagnostic": "canonical-stream-draw-plan-v1",
            "persistent_geometry_cache": False,
        },
        "privacy": "runtime manifest contains no hardware/vendor/renderer names",
        "redistribution_policy": "geometry pack is session-local and generated from user-local FH6 Vinyl geometry",
    }
    return {
        "manifest": manifest,
        "vector_stream": vector_stream,
        "geometry_pack": geometry_pack,
        "raster_decal_pack": raster_decal_pack,
    }
