# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=10,<13", "numpy>=1.26,<3", "psutil>=5.9,<8"]
# ///
from __future__ import annotations

import argparse
import hashlib
import gzip
import io
import json
import math
import os
import re
import struct
import zlib
import sys
from console_text_safety import configure_console_text_streams
import zipfile
import xml.etree.ElementTree as ET
import time
import tempfile
import threading
import webbrowser
from pathlib import Path

import psutil
import numpy as np
from PIL import Image

from fh_livery_preview_core.canonical import (
    SURFACE_DESIGN_FORMAT,
    livery_to_surface_json,
    livery_to_surface_json_with_privacy,
)
from fh_livery_preview_core.livery_preview import (
    configure_vinyl_resource_root, default_vinyl_resource_root, shape_is_raster, shape_word,
)
from fh_livery_preview_core.raster_decals import decode_fh6_decal_swatch
from fh_livery_preview_core.parser import ParseError
from fh_livery_preview_core.yrvl import parse_livery_yrvl_diagnostics, probe_livery_yrvl_variant

from tools.livery.first_party_package_source import inspect_clivery_privacy
from fh_livery_preview_core.source_envelope import unpack_source_file as unwrap_forza_container
from fh6_vinyl_runtime import ensure_local_vinyl_geometry, extract_selected_vinyl_geometry_for_design
from tools.livery.inspector_server import LiveryInspectorServer
from tools.livery.fh6_swatch import extract_swatch_preview_from_zip
from tools.livery.named_paint_groups import (
    named_paint_group_cluster,
    paint_group_binding_hex,
    paint_group_identifier_hex,
)
from tools.livery.package import (
    FullLiveryPackageError,
    create_local_livery_preview,
    validate_livery_inspection_artifact,
)
from tools.livery.portable_mesh_converter import (
    BODY_KIT_OVERLAY_FORMAT_REVISION,
    LOCAL_CHASSIS_FORMAT_REVISION,
    PortableMeshConverterError,
    convert_vehicle_model_to_glb,
    reuse_converter_validation,
    validate_local_chassis_glb,
)
from tools.livery.render_contract import RENDER_CONTRACT_REVISION, SECTION_TO_SLOT, build_local_livery_atlases
from tools.livery.fh6_gamedb import Fh6GameDbError, assembly_variants as gamedb_assembly_variants
from tools.livery.wheel_morph_internal import (
    WheelMorphInternalError,
    apply_wheelstyle_morph_to_glb,
    cache_identity as wheel_morph_internal_cache_identity,
    morph_inputs_from_assembly as wheel_morph_internal_inputs,
)
from tools.livery.default_paint import resolve_vehicle_default_paint
from tools.livery.livery_material_catalog import resolve_finish_only_material
from tools.livery.material_runtime import external_user_color_contract, extract_material_texture_preview, inspect_game_material_runtime, material_defined_paint_color, release_safe_viewer_candidate, texture_binding_evidence, weave_semantic_evidence
from tools.livery.wheel_material_binding import inspect_wheelstyle_bindings
from tools.livery.wheel_paint_routing import build_report as build_wheel_paint_routing_report
from tools.livery.wheel_paint_records import wheel_paint_contract
from tools.livery.wheel_routing_cache import cached_wheel_paint_routing
from tools.livery.manufacturer_colors import ManufacturerColorError, resolve_vehicle_manufacturer_color
from tools.livery.vehicle_assets import (
    VehicleAsset,
    inspect_vehicle_archive,
    inspection_model_entries,
    list_body_kit_part_ids,
    load_or_build_vehicle_asset_index,
    read_projection_metadata,
    read_vehicle_assembly_metadata,
    resolve_body_kit_overlay_plan,
    resolve_body_kit_part_selection,
    normalize_fh6_game_folder,
    sha256_file,
)


ROOT = Path(__file__).resolve().parent
VIEWER_ROOT = ROOT / "tools" / "livery-inspector"
LIVERY_MATERIAL_CATALOG_PATH = ROOT / "tools" / "livery" / "fh6-livery-material-catalog.json"

CANONICAL_DESIGN_CACHE_FORMAT = "lo4fh6_canonical_design_cache_v1"
# 通常Mask/Groupの意味論を変更したため既存r1キャッシュを再利用しない。
# 元ゲーム・保存済みデータは不変更。r2へ初回だけ再計算して以後再利用する。
CANONICAL_DESIGN_CACHE_REVISION = 2
CANONICAL_DESIGN_CACHE_DIRECTORY = "canonical-designs"
# 解読したペイントは同じプロセスのメモリーだけで持つ（2026-11-20。以前は _fh6-livery-cache に保存）
CANONICAL_DESIGN_MEMORY_KIND = "canonical-design-memory"
CANONICAL_DESIGN_MEMORY_LIMIT = 8
CLIVERY_PRIVACY_MEMORY_KIND = "clivery-privacy-memory"
CLIVERY_PRIVACY_MEMORY_LIMIT = 32
# 最近開いたペイントの解読結果だけを、ディスクに少し残す（2026-11-20、②の補い）。Viewer を起動し直した後に同じ
# ペイントを開くとき、解読し直さない（4212 で 1 件 約 0.2 秒 → 約 0.03 秒）。最近の 30 件まで（1 件 約 1 MB）。
# 形：marshal（同じ Python の版だけで読む）を zlib（強さ 1）で縮めたもの。名前に C_livery の SHA・車の ID・解読の版・
# Python の版を入れ、中身でも SHA と車の ID を確かめる。書き込みは裏で行い、表示を待たせない。
RECENT_DESIGN_DIRECTORY = "canonical-designs-recent"
RECENT_DESIGN_LIMIT = 30
RECENT_DESIGN_MAGIC = b"LO4DSGN1"

USER_PAINT_AUDIT_PATH = ROOT / "reference-results" / "r53-user-paint-shader-audit.json"
_WORKER_LOG_HANDLE = None


def _load_embedded_livery_material_catalog() -> dict[int, dict]:
    try:
        payload = json.loads(LIVERY_MATERIAL_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {int(item["id"]): item for item in payload.get("records", []) if item.get("id") is not None}


def _load_embedded_user_paint_audit() -> dict[str, dict]:
    try:
        payload = json.loads(USER_PAINT_AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(item.get("material") or "").casefold(): item for item in payload.get("materials", [])}


def _load_yrvl_diagnostics_for_preview(source: Path, *, viewer_fast_path: bool) -> dict:
    """
    任意のMaterialメタデータを復号する。対話型Viewerの起動を妨げない。
    """
    try:
        return parse_livery_yrvl_diagnostics(source)
    except ParseError as exc:
        if not viewer_fast_path:
            raise
        message = str(exc)
        return {
            "format": "lo4fh6_yrvl_research_v1",
            "status": "unsupported_variant_fallback",
            "warning": message,
            "candidate_material_yrvl": {
                "record_count": 0,
                "records": [],
                "reference_count": 0,
                "references": [],
                "finish_code_histogram": {},
                "material_code_histogram": {},
            },
            "viewer_fallback": {
                "used": True,
                "reason": message,
                "effect": "material/panel paint bindings are unavailable; canonical livery artwork and vehicle reconstruction continue",
            },
        }


def _wheel_paint_routing_diagnostics(game_folder: Path, asset: VehicleAsset, mesh_path: Path) -> dict[str, object]:
    """
    プレビュー1件について、Mesh別Wheel Paintのルーティング証拠を収集する。
    """

    try:
        content_root = normalize_fh6_game_folder(game_folder)
        binding = inspect_wheelstyle_bindings(content_root, asset, mesh_path)
        routing = build_wheel_paint_routing_report({
            "format": binding.get("format"),
            "cars": [{
                "car_id": int(binding.get("car_id") or 0),
                "model_code": str(binding.get("model_code") or ""),
                "sources": binding.get("sources") or [],
            }],
        })
        routing_summary = dict(routing.get("summary") or {})
        summary = {
            "available": True,
            "status": str(routing_summary.get("status") or "FAIL"),
            "source_count": int(binding.get("source_count") or 0),
            "mesh_count": int(binding.get("mesh_count") or 0),
            "mesh_external_user_color_count": int(binding.get("mesh_external_user_color_count") or 0),
            "mesh_g_CarUserColor0_count": int(binding.get("mesh_g_CarUserColor0_count") or 0),
            "routed_g_CarUserColor0_mesh_count": int(routing_summary.get("routed_g_CarUserColor0_mesh_count") or 0),
            "axle_paint_mesh_count": int(routing_summary.get("axle_paint_mesh_count") or 0),
            "generic_binding_mesh_count": int(routing_summary.get("generic_binding_mesh_count") or 0),
            "unresolved_g_CarUserColor0_mesh_count": int(routing_summary.get("unresolved_g_CarUserColor0_mesh_count") or 0),
        }
        return {
            "format": "lo4fh6_wheel_paint_routing_diagnostics_v1",
            "read_only": True,
            "available": True,
            "binding_summary": {
                "car_id": int(binding.get("car_id") or 0),
                "model_code": str(binding.get("model_code") or ""),
                "source_count": int(binding.get("source_count") or 0),
                "mesh_count": int(binding.get("mesh_count") or 0),
                "mesh_external_user_color_count": int(binding.get("mesh_external_user_color_count") or 0),
                "mesh_g_CarUserColor0_count": int(binding.get("mesh_g_CarUserColor0_count") or 0),
            },
            "summary": summary,
            "routing": routing,
            "boundary": (
                "Diagnostic-only per-mesh wheel paint routing evidence. Viewer wheel colour rendering remains unchanged; "
                "compiled constant-buffer offsets and instruction-level shader equations remain unresolved."
            ),
        }
    except Exception as exc:
        return {
            "format": "lo4fh6_wheel_paint_routing_diagnostics_v1",
            "read_only": True,
            "available": False,
            "summary": {
                "available": False,
                "status": "FAIL",
                "source_count": 0,
                "mesh_count": 0,
                "mesh_external_user_color_count": 0,
                "mesh_g_CarUserColor0_count": 0,
                "routed_g_CarUserColor0_mesh_count": 0,
                "axle_paint_mesh_count": 0,
                "generic_binding_mesh_count": 0,
                "unresolved_g_CarUserColor0_mesh_count": 0,
            },
            "error": f"{type(exc).__name__}: {exc}",
            "boundary": (
                "Diagnostic-only per-mesh wheel paint routing evidence. Viewer wheel colour rendering remains unchanged; "
                "compiled constant-buffer offsets and instruction-level shader equations remain unresolved."
            ),
        }


def _audit_number(effective: dict, name: str) -> float | None:
    value = ((effective.get(name) or {}).get("value"))
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _audit_bool(effective: dict, name: str) -> bool | None:
    value = ((effective.get(name) or {}).get("value"))
    return bool(value) if isinstance(value, bool) else None


def _bounded_unit(value: float, fallback: float) -> float:
    if not math.isfinite(float(value)):
        return fallback
    return max(0.0, min(1.0, float(value)))


def _roughness_from_fh6_shift(shift: float | None, *, fallback: float = 0.42) -> float:
    """
    FH6の離散的なRoughness Shift系統を、保守的なPBR値へ対応付ける。
    """
    if shift is None:
        return fallback
    if shift <= -0.95:
        return 0.08
    if shift <= -0.75:
        return 0.20
    if shift <= -0.55:
        return 0.32
    if shift <= -0.35:
        return 0.50
    return fallback


def _release_safe_material_candidate(entry: dict, audit: dict) -> tuple[dict, dict]:
    """
    FH6のMaterial証拠に基づく、上限下限付きViewer用PBR値を返す。
    """
    material_name = str(entry.get("material_name") or "")
    candidate, game_parameters = release_safe_viewer_candidate(
        material_name,
        str(audit.get("shader_family") or ""),
        dict(audit.get("effective_focus") or {}),
        source="embedded_fh6_material_catalog+r53_shader_audit",
    )
    if material_name.casefold() == "aluminumbrushed":
        candidate["basis"] = (
            "GameDB finish ID 14 -> AluminumBrushed; car_standard_user material audit has "
            "Roughness_Shift=-0.600000024 plus dtl_brushed_001 normal detail. R 0.32 is the "
            "r142 Windows/Xbox comparison checkpoint; renderer values remain bounded release-safe "
            "approximations, not exact 参照ツール shader equations."
        )
    return candidate, game_parameters


def _unknown_finish_viewer_candidate() -> dict:
    return {
        "roughness": 0.42,
        "metalness": 0.04,
        "env_map_intensity": 1.0,
        "clearcoat": 0.35,
        "clearcoat_roughness": 0.25,
        "base_clearcoat_scale_home_soft": 0.22,
        "source": "unknown_finish_safe_fallback",
        "release_safe_fallback": True,
        "basis": "No embedded FH6 finish mapping is available; conservative bounded PBR fallback avoids extreme glossy/metallic output.",
    }


def _resolve_base_paint_material(dominant_finish: dict) -> dict:
    finish_id = dominant_finish.get("finish_code_raw")
    if finish_id is None:
        return {}
    catalog = _load_embedded_livery_material_catalog()
    entry = catalog.get(int(finish_id))
    if not entry:
        return {
            "finish_id": int(finish_id),
            "primary_color_rgba_hex": (
                dominant_finish.get("primary_color_rgba_hex")
                if bool(dominant_finish.get("primary_color_enabled"))
                and _valid_explicit_paint_color(dominant_finish.get("primary_color_rgba_hex"))
                else None
            ),
            "secondary_color_rgba_hex": (
                dominant_finish.get("secondary_color_rgba_hex")
                if bool(dominant_finish.get("secondary_color_enabled"))
                and _valid_explicit_paint_color(dominant_finish.get("secondary_color_rgba_hex"))
                else None
            ),
            "catalog_match": False,
            "viewer_candidate": _unknown_finish_viewer_candidate(),
        }
    material_filename = Path(str(entry.get("material_path") or "").replace("\\", "/")).name.casefold()
    audit = _load_embedded_user_paint_audit().get(material_filename, {})
    effective = audit.get("effective_focus") or {}
    roughness_shift = ((effective.get("Roughness_Shift_floatVal") or {}).get("value"))
    viewer_candidate, game_parameters = _release_safe_material_candidate(entry, audit)
    return {
        "finish_id": int(finish_id),
        "material_name": entry.get("material_name"),
        "material_path": entry.get("material_path"),
        "preview_texture": entry.get("preview_texture"),
        "compatibility": entry.get("compatibility"),
        "num_input_colors": entry.get("num_input_colors"),
        "shader_family": audit.get("shader_family"),
        "roughness_shift": roughness_shift,
        "game_material_parameters": game_parameters,
        "primary_color_rgba_hex": (
            dominant_finish.get("primary_color_rgba_hex")
            if bool(dominant_finish.get("primary_color_enabled"))
            and _valid_explicit_paint_color(dominant_finish.get("primary_color_rgba_hex"))
            else None
        ),
        "secondary_color_rgba_hex": (
            dominant_finish.get("secondary_color_rgba_hex")
            if bool(dominant_finish.get("secondary_color_enabled"))
            and _valid_explicit_paint_color(dominant_finish.get("secondary_color_rgba_hex"))
            else None
        ),
        "catalog_match": True,
        "viewer_candidate": viewer_candidate,
    }


def _wheel_paint_contract_with_materials(
    candidate: dict,
    *,
    game_folder: Path | None = None,
    asset: VehicleAsset | None = None,
) -> dict:
    """
    Wheelの塗装色・仕上げを独立解決。車体Paintが既に使用するFH6原本監査を再利用。
    1プレビュー中、同一GameDB仕上げのMaterialBin/ShaderBin読込は1回のみ。
    原本がなくても見た目の代替材質を捏造しない。
    """
    contract = wheel_paint_contract(candidate)
    resolved_count = 0
    installed_audit_count = 0
    material_names: dict[str, int] = {}
    # 1つのLiveryには同じ仕上げを複数の前/後Wheelグループに指定できる。
    # C_liveryのグループ別RGBは共有せず、原本Material/Shaderの監査部分だけ共有。
    finish_cache: dict[tuple[int, str], dict] = {}
    # 通常Viewerでも既存の第一者MaterialBin/ShaderBin照合を実行し、
    # ブラウザー側の署名済みWheelStyleだけが仕上げを自動採用できる証拠を渡す。
    # 照合不能なら原本画像を保持し、推測した仕上げを追加しない。
    research_finish_enabled = game_folder is not None and asset is not None
    for row in (contract.get("groups") or {}).values():
        if not isinstance(row, dict):
            continue
        finish_material = _resolve_base_paint_material(row)
        if finish_material:
            finish_id = finish_material.get("finish_id")
            material_path = str(finish_material.get("material_path") or "")
            if (research_finish_enabled and finish_material.get("catalog_match") is True
                    and game_folder is not None and asset is not None and material_path):
                cache_key = (int(finish_id), material_path.casefold())
                if cache_key not in finish_cache:
                    # 車体で使用中の既知の原本検査経路でMaterialBin/ShaderBinを照合。
                    enriched = _enrich_material_contract_from_runtime(
                        dict(finish_material), game_folder=game_folder, asset=asset,
                    )
                    runtime = enriched.get("runtime_material") or {}
                    if runtime.get("available"):
                        defined_hex, defined_method = _finish_material_defined_rgba(
                            enriched, runtime, game_folder=game_folder, asset=asset,
                        )
                        finish_cache[cache_key] = {
                            "shader_family": enriched.get("shader_family"),
                            "viewer_candidate": enriched.get("viewer_candidate"),
                            "source_material_sha256": runtime.get("material_sha256"),
                            "source_shader_sha256": runtime.get("shader_sha256"),
                            "game_material_parameters": enriched.get("game_material_parameters") or {},
                            "finish_origin": "installed_fh6_materialbin_shaderbin",
                            "material_defined_rgba_hex": defined_hex,
                            "material_defined_color_method": defined_method,
                        }
                    else:
                        finish_cache[cache_key] = {}
                if finish_cache[cache_key]:
                    # 原本ファイルパスや巨大なruntime辞書はbrowserに配信しない。
                    finish_material.update(finish_cache[cache_key])
                    installed_audit_count += 1
            row["finish_material"] = finish_material
            if finish_material.get("catalog_match") is True:
                resolved_count += 1
                name = str(finish_material.get("material_name") or "")
                if name:
                    material_names[name] = material_names.get(name, 0) + 1
    contract["finish_material_resolved_group_count"] = resolved_count
    contract["finish_material_installed_audit_group_count"] = installed_audit_count
    contract["finish_material_name_histogram"] = material_names
    contract["boundary"] = (
        "Only exact known wheel paintable-group hashes are exposed. Disabled or missing primary colours remain fail-closed. "
        "Finish response is promoted only through the embedded FH6 material catalog and installed FH6 MaterialBin/ShaderBin audit; "
        "the Viewer does not reinterpret raw finish codes directly. PBR values are bounded approximations, not exact FH6 DXIL BRDF."
    )
    return contract


def _valid_explicit_paint_color(value: object) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{8}", value) is None:
        return False
    return value[-2:].casefold() != "00"


def _base_paint_cluster_from_diagnostics(diagnostics: dict) -> tuple[dict, str]:
    """
    描画器へ渡すBase PaintのDescriptor群を選択する。

    車体の地の色は、塗る場所の名前が Body の記録（named_paint_groups）を使う。以前は数の最も多い
    記録の集まりを選んでいたため、ホイールの塗装 10 件（色は無効）などを地の色と取り違えていた
    （Car 2468：ゲームは白、Viewer はメーカー指定色の赤）。Body の記録が無い場合だけ従来の推測。
    """
    body = named_paint_group_cluster(diagnostics, "Body")
    if body:
        return body, "named_body_paint_record"
    descriptor = dict(diagnostics.get("dominant_repeated_non_panel_descriptor_cluster") or {})
    if descriptor:
        return descriptor, "dominant_repeated_non_panel_descriptor_cluster"
    special = dict(diagnostics.get("dominant_repeated_non_panel_special_finish_cluster") or {})
    if special:
        return special, "dominant_repeated_non_panel_special_finish_cluster"
    colored = dict(diagnostics.get("dominant_repeated_non_panel_colored_cluster") or {})
    if colored:
        return colored, "dominant_repeated_non_panel_colored_cluster"
    return {}, "none"


def _base_paint_selection(dominant_finish: dict, *, source: str = "dominant_repeated_non_panel_special_finish_cluster") -> dict:
    """
    描画器へ渡すBase Paint色の判定結果を明示的に返す。
    """
    finish_id = dominant_finish.get("finish_code_raw")
    color = dominant_finish.get("primary_color_rgba_hex")
    enabled = bool(dominant_finish.get("primary_color_enabled"))
    valid_color = _valid_explicit_paint_color(color)
    return {
        "source": source,
        "available": finish_id is not None and enabled and valid_color,
        "finish_code_raw": int(finish_id) if finish_id is not None else None,
        "primary_color_enabled": enabled,
        "primary_color_rgba_hex": color if valid_color else None,
        "cluster_count": int(dominant_finish.get("count") or 0),
        "record_indices": [int(value) for value in (dominant_finish.get("record_indices") or [])],
        "semantics_status": (
            "descriptor-table primary color is renderer-authoritative; "
            "finish name/material enrichment remains independently mapped"
        ),
    }


def _renderer_base_paint_descriptor_from_diagnostics(diagnostics: dict) -> tuple[dict, str]:
    return _base_paint_cluster_from_diagnostics(diagnostics)


def _manufacturer_selector_from_cluster(cluster: dict) -> int | None:
    raw_hex = str(cluster.get("manufacturer_color_selector_hex") or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{8}", raw_hex) is None:
        return None
    return int.from_bytes(bytes.fromhex(raw_hex), "little")


def _descriptor_mode_from_cluster(cluster: dict) -> str:
    finish = int(cluster.get("finish_code_raw") or 0)
    primary_enabled = bool(cluster.get("primary_color_enabled"))
    secondary_enabled = bool(cluster.get("secondary_color_enabled"))
    primary = cluster.get("primary_color_rgba_hex")
    secondary = cluster.get("secondary_color_rgba_hex")
    selector = _manufacturer_selector_from_cluster(cluster)
    # メーカー指定色が選ばれている（0xFFFFFFFF 以外）記録は、残っている独自の色・仕上げより指定色を
    # 優先する（参照製品 docs/CLIVERY.md「An active manufacturer selector takes precedence over
    # retained custom color bytes. Custom paint uses selector 0xffffffff.」、参照のみ）。
    if selector is not None and selector != 0xFFFFFFFF:
        return "manufacturer_selector"
    if primary_enabled and _valid_explicit_paint_color(primary):
        return "explicit_primary_color"
    if finish != 0:
        return "finish_without_explicit_color"
    if secondary_enabled and _valid_explicit_paint_color(secondary):
        return "secondary_only_explicit_color"
    return "implicit_or_default"


def _unit_rgb_hex_to_rgba(value: object) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text) is None:
        return None
    return text.lower() + "ff"


def _manufacturer_material_contract(
    resolution: dict,
    *,
    source_kind: str,
    primary_rgba: str | None,
) -> dict:
    color = dict(resolution.get("color") or {})
    material_path = str(color.get("material_path") or "")
    material_name = Path(material_path.replace("\\", "/")).stem if material_path else ""
    return {
        "source_kind": source_kind,
        "resolution_source": resolution.get("resolution_source") or "vehicle_manufacturer_palette",
        "color_source": "vehicle_manufacturer_palette",
        "manufacturer_selector": resolution.get("selector"),
        "material_name": material_name,
        "material_path": material_path,
        "material_slots": list(color.get("material_slots") or []),
        "material_index_mask": color.get("material_index_mask"),
        "primary_color_rgba_hex": primary_rgba,
        "secondary_color_rgba_hex": _unit_rgb_hex_to_rgba(color.get("secondary_unit_rgb_hex")),
        "catalog_match": False,
        "viewer_candidate": _unknown_finish_viewer_candidate(),
    }


def _runtime_content_root(game_folder: Path) -> Path:
    root = Path(game_folder).expanduser().resolve()
    if (root / "media").is_dir():
        return root
    if (root / "Content" / "media").is_dir():
        return (root / "Content").resolve()
    return root


def _enrich_material_contract_from_runtime(
    material: dict,
    *,
    game_folder: Path | None,
    asset: VehicleAsset,
) -> dict:
    """
    ゲーム原本の実バイトを複製せず、インストール済みFH6のMaterial／Shader証拠を関連付ける。
    """
    if not material or game_folder is None:
        return material
    material_path = str(material.get("material_path") or "")
    if not material_path:
        return material
    runtime = inspect_game_material_runtime(
        _runtime_content_root(game_folder),
        material_path,
        vehicle_archive=asset.archive_path,
    )
    material["runtime_material"] = runtime
    if not runtime.get("available"):
        return material
    external_inputs = external_user_color_contract(runtime, material.get("num_input_colors"))
    if int(external_inputs.get("expected_input_count") or 0) > 0:
        material["external_color_inputs"] = external_inputs
    effective = dict(runtime.get("effective_focus") or {})
    material_color = material_defined_paint_color(effective, str(runtime.get("shader_family") or ""))
    material["material_defined_color"] = material_color
    candidate, game_parameters = release_safe_viewer_candidate(
        str(material.get("material_name") or Path(material_path.replace("\\", "/")).stem),
        str(runtime.get("shader_family") or ""),
        effective,
        source="installed_fh6_material_runtime+r176",
    )
    material["shader_family"] = runtime.get("shader_family")
    material["roughness_shift"] = ((effective.get("Roughness_Shift_floatVal") or {}).get("value"))
    material["game_material_parameters"] = game_parameters
    material["viewer_candidate"] = candidate
    return material


def _linear_unit_to_srgb_hex(rgb: list[float]) -> str:
    def encode(value: float) -> int:
        value = max(0.0, min(1.0, float(value)))
        srgb = value * 12.92 if value <= 0.0031308 else 1.055 * (value ** (1.0 / 2.4)) - 0.055
        return int(round(max(0.0, min(1.0, srgb)) * 255))
    return "#" + "".join(f"{encode(v):02x}" for v in rgb[:3]) + "ff"


FINISH_BASE_COLOR_TINT_CRC32 = zlib.crc32(b"BaseColor_TintColorParam") & 0xFFFFFFFF


def _finish_material_defined_rgba(
    material: dict,
    runtime: dict,
    *,
    game_folder: Path,
    asset: VehicleAsset,
) -> tuple[str | None, str]:
    """色の入力の無い仕上げ（金・スチール・白・カーボン等）が、材質自体で持つ色（sRGB の #RRGGBBAA）。

    ペイントの記録で色が無効・仕上げだけが指定された場合（ホイールの GoldPolished 等）、ゲームは
    仕上げの材質の色で描く（Car 3645・4313 のサムネイルは金のホイール）。
    - 塗装系（car_automotive_paint 等）：PaintColorColorParam（material_defined_paint_color）。
    - カーボン：織り目の 2 色（WeaveColorTintA/B）の平均（部品の色付けと同じ）。
    - 標準系（car_standard_user：GoldPolished・SteelPolished・ChromiumPolished 等）：MaterialBin の
      MTPR の BaseColor_TintColorParam（CRC32 0x53A946B6）。シェーダーの名前の表に無く、従来の読取では
      落ちていた（参照製品 model_material.cpp もこのハッシュをベースカラーとして読む。参照のみ）。
      ベースカラーの Texture は白の無地（flat_texture_white）。
    分からなければ (None, 理由)。
    """
    family = str(material.get("shader_family") or runtime.get("shader_family") or "").casefold()
    effective = dict(runtime.get("effective_focus") or {})
    if family.startswith("car_carbonfiber"):
        tints = []
        for key in ("WeaveColorTintAColorParam", "WeaveColorTintBColorParam"):
            value = (effective.get(key) or {}).get("value")
            if isinstance(value, list) and len(value) >= 3 and all(
                    type(v) in (int, float) and math.isfinite(v) for v in value[:3]):
                tints.append([max(0.0, float(v)) for v in value[:3]])
        if not tints:
            return None, "carbon-weave-color-unavailable"
        return _linear_unit_to_srgb_hex([sum(t[c] for t in tints) / len(tints) for c in range(3)]), "carbon-weave-tint-mean"
    paint = material_defined_paint_color(effective, family)
    if paint.get("available") and paint.get("rgba_hex"):
        return str(paint["rgba_hex"]).lower(), "material-paint-color"
    material_path = str(material.get("material_path") or "")
    if not material_path:
        return None, "material-path-unavailable"
    try:
        from tools.livery.body_trim_default_color import _read_parameters_tolerant
        from tools.livery.material_runtime import _material_source
        from tools.livery.wheel_default_paint import _mtpr_blobs
        data, _ = _material_source(_runtime_content_root(game_folder), material_path, Path(asset.archive_path))
        tint = None
        for blob in _mtpr_blobs(data):
            for row in _read_parameters_tolerant(blob):
                if int(row["parameter_crc32"], 16) == FINISH_BASE_COLOR_TINT_CRC32 and isinstance(row.get("value"), list):
                    tint = row["value"]
    except Exception as exc:  # noqa: BLE001  原本を読めなければ色を補わない（推測しない）
        return None, f"materialbin-unreadable: {type(exc).__name__}"
    if (not isinstance(tint, list) or len(tint) < 3
            or not all(type(v) in (int, float) and math.isfinite(v) for v in tint[:3])):
        return None, "base-color-tint-unavailable"
    return _linear_unit_to_srgb_hex([max(0.0, float(v)) for v in tint[:3]]), "materialbin-base-color-tint"


def _source_paint_binding_palette_color(asset: VehicleAsset, selector: int) -> dict | None:
    """塗装部品の記録で選ばれたメーカー指定色（車種の ManufacturerColors.bin）の色と材質名。"""
    try:
        resolved = resolve_vehicle_manufacturer_color(asset, int(selector))
    except (ManufacturerColorError, TypeError, ValueError):
        return None
    color = dict(resolved.get("color") or {})
    rgba = _unit_rgb_hex_to_rgba(color.get("primary_unit_rgb_hex"))
    path = str(color.get("material_path") or "")
    name = Path(path.replace("\\", "/")).stem if path else ""
    if not resolved.get("resolved") or rgba is None or not name:
        return None
    return {"rgba_hex": rgba, "material_name": name}


def _source_paint_binding_display_color(
    catalog: dict[int, dict], code: object, *, game_folder: Path, asset: VehicleAsset, cache: dict,
) -> str | None:
    """塗装部品の仕上げがカーボン・色の入力の無い仕上げなら、描画用の色（_finish_material_defined_rgba）。"""
    if type(code) is not int or code not in catalog:
        return None
    if code not in cache:
        finish = dict(catalog[code])
        cache[code] = None
        if finish.get("material_path"):
            enriched = _enrich_material_contract_from_runtime(finish, game_folder=game_folder, asset=asset)
            runtime = dict(enriched.get("runtime_material") or {})
            family = str(enriched.get("shader_family") or "").casefold()
            if runtime.get("available") and (family.startswith("car_carbonfiber")
                                               or finish.get("num_input_colors") == 0):
                cache[code] = _finish_material_defined_rgba(enriched, runtime, game_folder=game_folder, asset=asset)[0]
    return cache[code]


# 名前で引いて描画に使う塗る場所（ミラーのカバー・キャリパー）。Body は base_paint_selection で使う。
NAMED_PAINT_GROUPS_FOR_RENDER = ("Mirror", "Brakes")


def _factory_livery_sticker_contract(diagnostics: dict) -> dict:
    """純正の模様の板（原本の材質 livery_sticker）を見せるかを、ペイントの記録から決める（2026-11-22）。

    ゲームでは、デザインに層が無く（形の数 0）、板に結び付く記録がメーカー指定（selector≠0xFFFFFFFF）のとき、
    板の模様（Car 1477 の Ford のロゴ・文字・市松模様）が見える。層のあるデザインでは見えない
    （セーブデータの 1477 の 6 件・4212 の 7 件で、サムネイルと記録が一致）。見せる板の結び付きは、記録の識別子の
    バイトを逆にした GLB の形（大文字）で渡す。
    """
    counts = diagnostics.get("section_count_yrvl") if isinstance(diagnostics, dict) else None
    shape_count = counts.get("sum") if isinstance(counts, dict) else None
    records = ((diagnostics.get("candidate_material_yrvl") or {}).get("records") or []
               if isinstance(diagnostics, dict) else [])
    selected = set()
    for record in records:
        selector = record.get("manufacturer_color_selector_raw")
        identifier = str(record.get("material_identifier_hex") or "")
        if type(selector) is int and selector != 0xFFFFFFFF and re.fullmatch(r"[0-9a-fA-F]{16}", identifier):
            selected.add(bytes.fromhex(identifier)[::-1].hex().upper())
    valid_count = type(shape_count) is int and shape_count >= 0
    return {
        "schema": "lo4fh6.factory-livery-sticker.v1",
        "shape_count": shape_count if valid_count else None,
        "visible": valid_count and shape_count == 0,
        "selected_bindings": sorted(selected),
    }


def _named_paint_groups_contract(
    diagnostics: dict,
    *,
    asset: VehicleAsset,
    game_folder: Path | None,
) -> dict:
    """ミラーのカバー（Mirror）とキャリパー（Brakes）の記録の色と仕上げを、描画器向けにまとめる。

    色の決め方は車体の地の色と同じ（_resolve_renderer_base_paint：メーカー指定色・独自の色・仕上げの色）。
    カーボン仕上げは、部品の色付け（body_trim_default_color）と同じく織り目の 2 色
    （WeaveColorTintA/B）の平均で描く（サムネイルではカーボンのミラーはほぼ黒。織り目は描かない）。
    """
    groups: dict[str, dict] = {}
    for name in NAMED_PAINT_GROUPS_FOR_RENDER:
        cluster = named_paint_group_cluster(diagnostics, name)
        if not cluster:
            continue
        selection, material = _resolve_renderer_base_paint(
            cluster, descriptor_source=f"named_paint_record:{name}", asset=asset, game_folder=game_folder,
        )
        family = str(material.get("shader_family") or "").casefold()
        display, method = None, "unavailable"
        if family.startswith("car_carbonfiber"):
            effective = dict((material.get("runtime_material") or {}).get("effective_focus") or {})
            tints = []
            for key in ("WeaveColorTintAColorParam", "WeaveColorTintBColorParam"):
                value = (effective.get(key) or {}).get("value")
                if isinstance(value, list) and len(value) >= 3 and all(
                        type(v) in (int, float) and math.isfinite(v) for v in value[:3]):
                    tints.append([max(0.0, float(v)) for v in value[:3]])
            if tints:
                display = _linear_unit_to_srgb_hex([sum(t[c] for t in tints) / len(tints) for c in range(3)])
                method = "carbon-weave-tint-mean"
        elif selection.get("color_available") and _valid_explicit_paint_color(selection.get("primary_color_rgba_hex")):
            display = str(selection["primary_color_rgba_hex"]).lower()
            method = "record-color"
        groups[name] = {
            "identifier_hex": paint_group_identifier_hex(name),
            "binding_hash_hex": paint_group_binding_hex(name),
            "record_indices": [int(v) for v in cluster.get("record_indices") or []],
            "descriptor_mode": selection.get("descriptor_mode"),
            "finish_code_raw": selection.get("finish_code_raw"),
            "manufacturer_selector": selection.get("manufacturer_selector"),
            "display_rgba_hex": display,
            "display_method": method,
            "material_name": material.get("material_name"),
            "shader_family": material.get("shader_family"),
            "viewer_candidate": dict(material.get("viewer_candidate") or {}),
        }
    return {
        "schema": "lo4fh6.named-paint-groups.v1",
        "identifier": "fnv1a64-of-paint-group-name (C_livery little-endian bytes / GLB binding numeric hex)",
        "groups": groups,
        "game_shader_gpu_verified": False,
    }


def _resolve_renderer_base_paint(
    descriptor: dict,
    *,
    descriptor_source: str,
    asset: VehicleAsset,
    game_folder: Path | None = None,
) -> tuple[dict, dict]:
    """
    無効化されたRGBフィールドを参照せず、描画器用Base Paintを決定する。
    """
    if not descriptor:
        return (
            {
                "source": "none",
                "source_kind": "unresolved",
                "available": False,
                "color_available": False,
                "material_available": False,
                "primary_color_rgba_hex": None,
            },
            {},
        )

    mode = _descriptor_mode_from_cluster(descriptor)
    finish_id = int(descriptor.get("finish_code_raw") or 0)
    common = {
        "source": descriptor_source,
        "source_kind": mode,
        "descriptor_mode": mode,
        "finish_code_raw": finish_id,
        "cluster_count": int(descriptor.get("count") or 0),
        "record_indices": [int(value) for value in (descriptor.get("record_indices") or [])],
    }

    if mode == "explicit_primary_color":
        selection = {
            **common,
            "available": True,
            "color_available": True,
            "material_available": True,
            "primary_color_enabled": True,
            "primary_color_rgba_hex": descriptor.get("primary_color_rgba_hex"),
            "color_source": "descriptor_explicit_primary",
            "semantics_status": "explicit descriptor primary color is renderer-authoritative",
        }
        material = _resolve_base_paint_material(descriptor)
        material.update({
            "source_kind": mode,
            "resolution_source": "descriptor_explicit_primary",
            "color_source": "descriptor_explicit_primary",
        })
        return selection, _enrich_material_contract_from_runtime(
            material, game_folder=game_folder, asset=asset
        )

    if mode == "finish_without_explicit_color":
        resolved = resolve_finish_only_material(finish_id)
        material = _resolve_base_paint_material(descriptor)
        material.update({
            "source_kind": mode,
            "resolution_source": resolved.get("resolution_source"),
            "color_source": "material_defined",
            "primary_color_rgba_hex": None,
            "secondary_color_rgba_hex": None,
        })
        selection = {
            **common,
            "available": bool(resolved.get("resolved")),
            "color_available": False,
            "material_available": bool(resolved.get("resolved")),
            "primary_color_enabled": False,
            "primary_color_rgba_hex": None,
            "color_source": "material_defined",
            "material_path": resolved.get("material_path"),
            "material_name": resolved.get("material_name"),
            "semantics_status": "finish material is self-contained; disabled descriptor RGB is not renderer input",
        }
        material = _enrich_material_contract_from_runtime(
            material, game_folder=game_folder, asset=asset
        )
        runtime_color = dict(material.get("material_defined_color") or {})
        if not (runtime_color.get("available") and runtime_color.get("rgba_hex")) and game_folder is not None:
            # 標準系の仕上げ（GoldPolished・SteelPolished 等）は PaintColorColorParam を持たず、
            # MaterialBin の BaseColor_TintColorParam が色（_finish_material_defined_rgba）。
            defined_hex, defined_method = _finish_material_defined_rgba(
                material, dict(material.get("runtime_material") or {}), game_folder=game_folder, asset=asset,
            )
            if defined_hex:
                runtime_color = {"available": True, "rgba_hex": defined_hex, "method": defined_method}
        if runtime_color.get("available") and runtime_color.get("rgba_hex"):
            rgba_hex = str(runtime_color["rgba_hex"])
            selection.update({
                "color_available": True,
                "primary_color_rgba_hex": rgba_hex,
                "color_source": runtime_color.get("method") or "material_runtime_paint_color_param",
                "semantics_status": (
                    "finish material is self-contained; installed FH6 material PaintColorColorParam "
                    "supplies the renderer colour without descriptor RGB"
                ),
            })
            material.update({
                "primary_color_rgba_hex": rgba_hex,
                "color_source": runtime_color.get("method") or "material_runtime_paint_color_param",
            })
        return selection, material

    if mode == "manufacturer_selector":
        selector = _manufacturer_selector_from_cluster(descriptor)
        try:
            resolved = resolve_vehicle_manufacturer_color(asset, int(selector))
        except (ManufacturerColorError, TypeError, ValueError) as exc:
            return (
                {
                    **common,
                    "available": False,
                    "color_available": False,
                    "material_available": False,
                    "manufacturer_selector": selector,
                    "primary_color_rgba_hex": None,
                    "color_source": "vehicle_manufacturer_palette",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                {},
            )
        primary = _unit_rgb_hex_to_rgba((resolved.get("color") or {}).get("primary_unit_rgb_hex"))
        available = bool(resolved.get("resolved")) and primary is not None
        selection = {
            **common,
            "available": available,
            "color_available": available,
            "material_available": bool(resolved.get("resolved")),
            "manufacturer_selector": selector,
            "primary_color_enabled": False,
            "primary_color_rgba_hex": primary,
            "color_source": "vehicle_manufacturer_palette",
            "semantics_status": "descriptor selector resolves through the matching vehicle ManufacturerColors palette",
        }
        material = _manufacturer_material_contract(
            resolved,
            source_kind=mode,
            primary_rgba=primary,
        )
        return selection, _enrich_material_contract_from_runtime(
            material, game_folder=game_folder, asset=asset
        )

    if mode == "implicit_or_default":
        resolved = resolve_vehicle_default_paint(asset)
        color = dict(resolved.get("color") or {})
        primary = _unit_rgb_hex_to_rgba(color.get("primary_unit_rgb_hex"))
        available = bool(resolved.get("resolved")) and primary is not None
        selection = {
            **common,
            "available": available,
            "color_available": available,
            "material_available": bool(resolved.get("resolved")),
            "manufacturer_selector": 0 if resolved.get("resolved") else None,
            "primary_color_enabled": False,
            "primary_color_rgba_hex": primary,
            "color_source": "implicit_default_manufacturer_selector_zero",
            "semantics_status": "generic vehicle carpaint with no referenced BaseLivery resolves to ManufacturerColors selector 0",
            "evidence": dict(resolved.get("evidence") or {}),
        }
        material = _manufacturer_material_contract(
            resolved,
            source_kind=mode,
            primary_rgba=primary,
        )
        return selection, _enrich_material_contract_from_runtime(
            material, game_folder=game_folder, asset=asset
        )

    return (
        {
            **common,
            "available": False,
            "color_available": False,
            "material_available": False,
            "primary_color_rgba_hex": None,
            "color_source": "unresolved",
            "semantics_status": "descriptor mode is not renderer-authoritative yet",
        },
        {},
    )


def _canonical_json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _canonical_design_cache_entry_root(cache_root: Path, source_sha256: str) -> Path:
    return (cache_root / CANONICAL_DESIGN_CACHE_DIRECTORY / f"r{CANONICAL_DESIGN_CACHE_REVISION}" / source_sha256).resolve()


def _recent_design_path(cache_root: Path, source_sha256: str, embedded_car_id: int) -> Path:
    tag = f"r{CANONICAL_DESIGN_CACHE_REVISION}-py{sys.version_info[0]}{sys.version_info[1]}"
    return Path(cache_root) / RECENT_DESIGN_DIRECTORY / f"{source_sha256}-{int(embedded_car_id)}-{tag}.bin"


def _read_recent_design(cache_root: Path, source_sha256: str, embedded_car_id: int) -> tuple[dict, dict | None] | None:
    """最近の解読結果をディスクから読む（無い・壊れている・合わなければ None）。読んだら最近使った印を付ける。"""
    import marshal
    target = _recent_design_path(cache_root, source_sha256, embedded_car_id)
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if not raw.startswith(RECENT_DESIGN_MAGIC):
        return None
    try:
        payload = marshal.loads(zlib.decompress(raw[len(RECENT_DESIGN_MAGIC):]))
    except (ValueError, EOFError, TypeError, zlib.error):
        return None
    if (not isinstance(payload, dict) or payload.get("source_sha256") != str(source_sha256)
            or payload.get("embedded_car_id") != int(embedded_car_id)):
        return None
    design = payload.get("design")
    privacy = payload.get("privacy")
    if not isinstance(design, dict) or str(design.get("format") or "") != SURFACE_DESIGN_FORMAT:
        return None
    try:
        os.utime(target)
    except OSError:
        pass
    return design, privacy if isinstance(privacy, dict) else None


def _write_recent_design_later(cache_root: Path, source_sha256: str, embedded_car_id: int, design: dict,
                               privacy: dict | None) -> None:
    """最近の解読結果を裏でディスクに書き、最近の RECENT_DESIGN_LIMIT 件を超えた古いものを消す。"""
    import marshal
    try:
        data = marshal.dumps({"source_sha256": str(source_sha256), "embedded_car_id": int(embedded_car_id),
                              "design": design, "privacy": dict(privacy) if privacy is not None else None})
    except ValueError:
        return
    target = _recent_design_path(cache_root, source_sha256, embedded_car_id)

    def work() -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f"{target.name}.{os.getpid()}-{threading.get_ident()}.tmp")
            temporary.write_bytes(RECENT_DESIGN_MAGIC + zlib.compress(data, 1))
            os.replace(temporary, target)
            entries = []
            for item in target.parent.iterdir():
                try:
                    if item.is_symlink() or not item.is_file():
                        continue
                    stat = item.stat()
                except OSError:
                    continue
                if item.suffix == ".tmp" and time.time() - stat.st_mtime > 3600:
                    entries.append((-1.0, item))  # 途中で止まった書き込みの残り
                elif item.suffix == ".bin":
                    entries.append((stat.st_mtime, item))
            entries.sort(key=lambda row: row[0], reverse=True)
            kept = 0
            for used, item in entries:
                if used >= 0 and kept < RECENT_DESIGN_LIMIT:
                    kept += 1
                    continue
                try:
                    item.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    threading.Thread(target=work, name="lo4fh6-recent-design", daemon=True).start()


def _read_cached_canonical_design(cache_root: Path, source_sha256: str, embedded_car_id: int) -> tuple[dict | None, Path]:
    """同じプロセスで解読した結果を返す（無ければ None）。ディスクには書かず、読まない（2026-11-20）。

    以前は C_livery の中身の SHA ごとに _fh6-livery-cache へ gzip で保存していた（1 件 約 0.6 MB、書き込みに
    約 0.2 秒）。FH6 と同じく、ペイントは読み込むたびに解読し、同じプロセスの中だけで使い回す
    （準備の前半と後半の GPU の入力・同じペイントの開き直し）。覚えた結果は marshal で持ち、毎回作り直して渡す。
    返す 2 つ目の値は記録用の識別の場所で、作らない。
    """
    from tools.livery.process_file_memo import remembered
    entry = _canonical_design_cache_entry_root(cache_root, source_sha256)
    design = remembered(
        CANONICAL_DESIGN_MEMORY_KIND, [], (str(source_sha256), int(embedded_car_id)), lambda: None,
        copy="marshal", limit=CANONICAL_DESIGN_MEMORY_LIMIT, keep=lambda value: value is not None)
    if not isinstance(design, dict) or str(design.get("format") or "") != SURFACE_DESIGN_FORMAT:
        # 同じプロセスに無ければ、最近の解読結果をディスクから読む（②の補い）
        recent = _read_recent_design(cache_root, source_sha256, embedded_car_id)
        if recent is None:
            return None, entry
        from tools.livery.process_file_memo import put
        design, privacy = recent
        put(CANONICAL_DESIGN_MEMORY_KIND, [], (str(source_sha256), int(embedded_car_id)), design,
            copy="marshal", limit=CANONICAL_DESIGN_MEMORY_LIMIT)
        if privacy is not None:
            put(CLIVERY_PRIVACY_MEMORY_KIND, [], str(source_sha256), dict(privacy), copy="deep",
                limit=CLIVERY_PRIVACY_MEMORY_LIMIT)
    return design, entry


def _write_cached_canonical_design(
    cache_root: Path, source_sha256: str, embedded_car_id: int, design: dict, privacy: dict | None = None
) -> Path:
    """解読した結果（とプライバシーの判定）を同じプロセスのメモリーに覚える。ディスクには書かない（2026-11-20）。"""
    from tools.livery.process_file_memo import put
    put(CANONICAL_DESIGN_MEMORY_KIND, [], (str(source_sha256), int(embedded_car_id)), design,
        copy="marshal", limit=CANONICAL_DESIGN_MEMORY_LIMIT)
    if privacy is not None:
        put(CLIVERY_PRIVACY_MEMORY_KIND, [], str(source_sha256), dict(privacy), copy="deep",
            limit=CLIVERY_PRIVACY_MEMORY_LIMIT)
    _write_recent_design_later(cache_root, source_sha256, embedded_car_id, design, privacy)
    return _canonical_design_cache_entry_root(cache_root, source_sha256)


_RETIRED_DESIGN_CACHE_ROOTS: set[str] = set()


def _retire_disk_canonical_designs(cache_root: Path) -> None:
    """以前ディスクに保存していた解読結果（_fh6-livery-cache/canonical-designs）を、裏で消す（プロセスごとに 1 回）。

    先に「削除中」の名前へ変えてから消す。途中で止まった残りは、次に動いたときに消す。リンク（シンボリック
    リンク・ジャンクション）は辿らず、消さない。消せなかったもの（使用中など）はそのままにする（2026-11-20）。
    """
    base = Path(cache_root)
    key = os.path.normcase(str(base))
    if key in _RETIRED_DESIGN_CACHE_ROOTS:
        return
    _RETIRED_DESIGN_CACHE_ROOTS.add(key)

    def is_link(path: Path) -> bool:
        try:
            return path.is_symlink() or path.is_junction()
        except OSError:
            return True

    def work() -> None:
        import shutil
        try:
            if not base.is_dir() or is_link(base):
                return
            targets = [path for path in base.iterdir()
                       if path.name.startswith(f"{CANONICAL_DESIGN_CACHE_DIRECTORY}.lo4fh6-deleting-")]
            current = base / CANONICAL_DESIGN_CACHE_DIRECTORY
            if current.is_dir() and not is_link(current):
                renamed = current.with_name(
                    f"{current.name}.lo4fh6-deleting-{os.getpid()}-{time.time_ns()}")
                current.rename(renamed)
                targets.append(renamed)
            for target in targets:
                if target.is_dir() and not is_link(target):
                    shutil.rmtree(target, ignore_errors=True)
            try:
                base.rmdir()  # 空になったら _fh6-livery-cache も消す
            except OSError:
                pass
        except OSError:
            pass

    threading.Thread(target=work, name="lo4fh6-retire-design-cache", daemon=True).start()


def _load_or_build_canonical_design(
    source: Path, cache_root: Path, source_sha256: str, embedded_car_id: int
) -> tuple[dict, dict]:
    started = time.perf_counter()
    cached, entry = _read_cached_canonical_design(cache_root, source_sha256, embedded_car_id)
    lookup_seconds = time.perf_counter() - started
    if cached is not None:
        return cached, {
            "scope": "process-memory-by-c-livery-content",
            "root": str(entry),
            "cache_hit": True,
            "decode_skipped": True,
            "lookup_seconds": lookup_seconds,
            "decode_seconds": 0.0,
        }
    decode_started = time.perf_counter()
    design = livery_to_surface_json(source, decoder="canonical")
    decode_seconds = time.perf_counter() - decode_started
    entry = _write_cached_canonical_design(cache_root, source_sha256, embedded_car_id, design)
    return design, {
        "scope": "process-memory-by-c-livery-content",
        "root": str(entry),
        "cache_hit": False,
        "decode_skipped": False,
        "lookup_seconds": lookup_seconds,
        "decode_seconds": decode_seconds,
    }


def _validated_cached_clivery_privacy(entry: Path, source_sha256: str) -> dict | None:
    """同じプロセスで求めた C_livery のプライバシーの判定（無い・形が違えば None）。entry は記録用で読まない。"""
    del entry
    from tools.livery.process_file_memo import remembered
    privacy = remembered(
        CLIVERY_PRIVACY_MEMORY_KIND, [], str(source_sha256), lambda: None, copy="deep",
        limit=CLIVERY_PRIVACY_MEMORY_LIMIT, keep=lambda value: value is not None)
    try:
        if (
            isinstance(privacy, dict)
            and isinstance(privacy.get("source_owned"), bool)
            and isinstance(privacy.get("contains_foreign_groups"), bool)
            and isinstance(privacy.get("foreign_group_count"), int)
            and not isinstance(privacy.get("foreign_group_count"), bool)
            and int(privacy.get("foreign_group_count")) >= 0
            and isinstance(privacy.get("protected_group_offsets"), list)
            and all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in privacy.get("protected_group_offsets")
            )
            and bool(privacy.get("contains_foreign_groups"))
            == bool(int(privacy.get("foreign_group_count")) > 0)
        ):
            return dict(privacy)
    except (ValueError, TypeError):
        pass
    return None


def _load_or_build_canonical_design_with_privacy(
    source: Path, cache_root: Path, source_sha256: str, embedded_car_id: int,
    *, private_context_mask_visual_check: bool = False,
) -> tuple[dict, dict | None, dict]:
    """
    Content Addressで識別したDesignを読み、プライバシー判定と最新の正規構造解析を組み合わせる。
    Group/Maskの標準復号はすべての入口で同一。旧CLIフラグは互換エイリアス。
    """
    # 旧研究CLIの値は互換入力としてのみ受理。Mask復号・保存キャッシュは
    # GUI/Organizer/CLIの通常製品入口で完全に同一。元r1はr2世代で無効化。
    del private_context_mask_visual_check
    started = time.perf_counter()
    cached, entry = _read_cached_canonical_design(cache_root, source_sha256, embedded_car_id)
    lookup_seconds = time.perf_counter() - started
    if cached is not None:
        privacy = _validated_cached_clivery_privacy(entry, source_sha256)
        return cached, privacy, {
            "scope": "process-memory-by-c-livery-content",
            "root": str(entry),
            "cache_hit": True,
            "decode_skipped": True,
            "lookup_seconds": lookup_seconds,
            "decode_seconds": 0.0,
            "privacy_integrated": False,
            "privacy_candidate_scan_seconds": 0.0,
            "privacy_from_cache": privacy is not None,
        }

    decode_started = time.perf_counter()
    design, privacy, decode_metrics = livery_to_surface_json_with_privacy(source)
    decode_seconds = time.perf_counter() - decode_started
    entry = _write_cached_canonical_design(
        cache_root, source_sha256, embedded_car_id, design, privacy=privacy
    )
    return design, privacy, {
        "scope": "process-memory-by-c-livery-content",
        "root": str(entry),
        "cache_hit": False,
        "decode_skipped": False,
        "lookup_seconds": lookup_seconds,
        "decode_seconds": decode_seconds,
        "privacy_integrated": True,
        "privacy_candidate_scan_seconds": float(decode_metrics.get("privacy_candidate_scan_seconds") or 0.0),
        "privacy_structural_parse_seconds": float(decode_metrics.get("structural_parse_seconds") or 0.0),
        "privacy_from_cache": False,
    }

def _load_or_build_clivery_privacy(
    payload: bytes, cache_root: Path, source_sha256: str, *, allow_cache: bool = True
) -> tuple[dict, dict]:
    entry = _canonical_design_cache_entry_root(cache_root, source_sha256)
    lookup_started = time.perf_counter()
    if allow_cache:
        privacy = _validated_cached_clivery_privacy(entry, source_sha256)
        if privacy is not None:
            return privacy, {
                "scope": "process-memory-by-c-livery-content",
                "cache_hit": True,
                "scan_skipped": True,
                "lookup_seconds": time.perf_counter() - lookup_started,
                "scan_seconds": 0.0,
            }
    lookup_seconds = time.perf_counter() - lookup_started
    scan_started = time.perf_counter()
    privacy = inspect_clivery_privacy(payload)
    scan_seconds = time.perf_counter() - scan_started
    from tools.livery.process_file_memo import put
    put(CLIVERY_PRIVACY_MEMORY_KIND, [], str(source_sha256), dict(privacy), copy="deep",
        limit=CLIVERY_PRIVACY_MEMORY_LIMIT)
    return dict(privacy), {
        "scope": "process-memory-by-c-livery-content",
        "cache_hit": False,
        "scan_skipped": False,
        "lookup_seconds": lookup_seconds,
        "scan_seconds": scan_seconds,
    }


def resolve_c_livery(value: Path) -> Path:
    path = value.expanduser().resolve()
    if path.is_dir() and (path / "C_livery").is_file():
        return path / "C_livery"
    if path.is_file() and path.name.casefold() == "c_livery":
        return path
    raise argparse.ArgumentTypeError(f"C_livery not found: {path}")


def _safe_tree_bytes(path: Path | str | None) -> int:
    """
    Directory Symlinkをたどらず、現在の生成物バイトを取得する。
    """
    if path is None:
        return 0
    target = Path(path)
    try:
        if target.is_file():
            return int(target.stat().st_size)
        if not target.is_dir():
            return 0
        total = 0
        for child in target.rglob("*"):
            try:
                if child.is_file() and not child.is_symlink():
                    total += int(child.stat().st_size)
            except OSError:
                continue
        return total
    except OSError:
        return 0


def _current_cache_footprint(
    *,
    output: Path,
    contract: dict,
    mesh_path: Path,
    wheel_morph_sidecar: Path | None,
    body_kit_variants: list[dict],
    canonical_design_cache_root: Path | None = None,
) -> dict[str, int]:
    paint_cache = contract.get("paint_cache") if isinstance(contract.get("paint_cache"), dict) else {}
    mask_cache = contract.get("mask_cache") if isinstance(contract.get("mask_cache"), dict) else {}
    paint_root = Path(str(paint_cache.get("root") or "")) if paint_cache.get("root") else None
    mask_root = Path(str(mask_cache.get("root") or "")) if mask_cache.get("root") else None
    overlay_paths = {
        Path(str(item.get("overlay_mesh")))
        for item in body_kit_variants
        if isinstance(item, dict) and str(item.get("overlay_mesh") or "").strip()
    }
    return {
        "per_livery_output_bytes": _safe_tree_bytes(output),
        "shared_mesh_bytes": _safe_tree_bytes(mesh_path) + _safe_tree_bytes(wheel_morph_sidecar),
        "shared_body_kit_overlay_bytes": sum(_safe_tree_bytes(path) for path in overlay_paths),
        "shared_paint_entry_bytes": _safe_tree_bytes(paint_root),
        "shared_projection_mask_entry_bytes": _safe_tree_bytes(mask_root),
        "shared_canonical_design_entry_bytes": _safe_tree_bytes(canonical_design_cache_root),
    }


def source_folder_id(source: Path) -> int | None:
    """
    存在する場合にLivery_／SoulBoundLivery_コンテナーの数値識別子を返す。
    """
    match = re.match(r"^(?:SoulBoundLivery|Livery)_(\d+)(?:_|$)", source.parent.name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def choose_target_car_id(*, embedded_car_id: int, override_car_id: int | None) -> tuple[int, str]:
    if override_car_id is not None:
        if int(override_car_id) <= 0:
            raise FullLiveryPackageError("--car-id must be a positive FH6 Car ID.")
        return int(override_car_id), "explicit_override"
    if int(embedded_car_id) <= 0:
        raise FullLiveryPackageError("No usable C_livery embedded ID was decoded; pass --car-id explicitly.")
    return int(embedded_car_id), "c_livery_embedded_id_legacy_fallback"

def _binary_mask_component_metrics(mask: np.ndarray) -> dict:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=np.bool_)
    component_sizes: list[int] = []
    component_boxes: list[tuple[int, int, int, int]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            size = 0
            min_y = max_y = y
            min_x = max_x = x
            while stack:
                cy, cx = stack.pop()
                size += 1
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            component_sizes.append(size)
            component_boxes.append((min_x, min_y, max_x + 1, max_y + 1))
    component_sizes.sort(reverse=True)
    bbox_area = max(1, height * width)
    filled = int(np.count_nonzero(mask))
    largest_component = int(component_sizes[0]) if component_sizes else 0
    small_components = int(sum(1 for size in component_sizes if size <= 16))
    component_count = len(component_sizes)
    return {
        "component_count": component_count,
        "largest_component_pixels": largest_component,
        "largest_component_ratio": float(largest_component / max(1, filled)),
        "small_component_count": small_components,
        "small_component_ratio": float(small_components / max(1, component_count)),
        "fill_ratio": float(filled / bbox_area),
        "aspect_ratio": float(width / max(1, height)),
        "width": int(width),
        "height": int(height),
        "pixel_count": filled,
    }


def _classify_mask_owner_semantic_group(metrics: dict) -> tuple[str, str]:
    pixel_count = int(metrics.get("pixel_count") or 0)
    component_count = int(metrics.get("component_count") or 0)
    fill_ratio = float(metrics.get("fill_ratio") or 0.0)
    aspect_ratio = float(metrics.get("aspect_ratio") or 0.0)
    width = int(metrics.get("width") or 0)
    height = int(metrics.get("height") or 0)
    largest_ratio = float(metrics.get("largest_component_ratio") or 0.0)
    small_ratio = float(metrics.get("small_component_ratio") or 0.0)

    if pixel_count <= 48 or (
        component_count <= 2 and max(width, height) <= 32 and fill_ratio <= 0.08
    ):
        return (
            "micro-fragment",
            "very small isolate; likely punctuation, tiny cutout, or residual fragment",
        )

    # r31：細い切出し領域の判定より先に、多数の小さな非連結領域が支配的かを調べる。
    # 広い切出し範囲でも原作者の寄与が線状でなく飛沫状の図形を正しく分類するためである。
    if component_count >= 20 and largest_ratio < 0.20 and small_ratio >= 0.85:
        return (
            "splatter",
            "many tiny disconnected components with no dominant island; likely splatter / spray",
        )

    # 意味のある連結した芯を持つ長く疎なOwnerは線・筋構造とする。
    # 単に外接矩形が広いだけの飛沫をこの分類へ入れない。
    if aspect_ratio >= 2.0 and fill_ratio <= 0.04 and largest_ratio >= 0.25:
        return (
            "stroke-line",
            "elongated low-fill isolate with a dominant connected stroke; likely speed line / streak / outline",
        )
    if width >= 120 and fill_ratio <= 0.03 and largest_ratio >= 0.25:
        return (
            "stroke-line",
            "wide sparse isolate with a meaningful connected backbone; likely line / streak element",
        )

    if component_count >= 6 and small_ratio >= 0.75 and largest_ratio < 0.25:
        return (
            "splatter",
            "fragment-dominated isolate; likely splatter / spray / decorative noise",
        )

    return (
        "glyph-main",
        "compact dominant component; likely a main glyph or readable logo fragment",
    )


def _mask_owner_group_display_name(group_key: str) -> str:
    return {
        "glyph-main": "glyph-main",
        "stroke-line": "stroke-line",
        "splatter": "splatter",
        "micro-fragment": "micro-fragment",
    }.get(group_key, group_key)


def _binary_iou(left_mask: np.ndarray, right_mask: np.ndarray) -> tuple[int, int, float]:
    left_bool = left_mask > 0
    right_bool = right_mask > 0
    intersection = int(np.count_nonzero(left_bool & right_bool))
    union = int(np.count_nonzero(left_bool | right_bool))
    return intersection, union, float(intersection / max(1, union))


def _normalize_binary_shape(mask: np.ndarray, *, size: int = 96, margin: int = 8) -> np.ndarray:
    """
    配置と独立した形状比較のため、Ownerの二値Cropを正規化する。
    """
    source = np.asarray(mask) > 0
    ys, xs = np.nonzero(source)
    result = np.zeros((size, size), dtype=np.uint8)
    if not len(xs):
        return result
    crop = source[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]
    height, width = crop.shape
    usable = max(1, int(size) - int(margin) * 2)
    scale = min(usable / max(1, width), usable / max(1, height))
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    image = Image.fromarray((crop.astype(np.uint8) * 255), "L").resize(
        (resized_width, resized_height), Image.Resampling.NEAREST
    )
    x0 = (size - resized_width) // 2
    y0 = (size - resized_height) // 2
    result[y0:y0 + resized_height, x0:x0 + resized_width] = (
        np.asarray(image, dtype=np.uint8) > 0
    ).astype(np.uint8) * 255
    return result


def _rotate_binary_shape(mask: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(float(angle_deg)) <= 1e-12:
        return mask.copy()
    image = Image.fromarray(np.asarray(mask, dtype=np.uint8), "L")
    rotated = image.rotate(
        float(angle_deg),
        resample=Image.Resampling.NEAREST,
        expand=False,
        fillcolor=0,
    )
    return np.asarray(rotated, dtype=np.uint8)


def _intrinsic_shape_similarity(
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    *,
    angles: tuple[float, ...] = (-6.0, -3.0, 0.0, 3.0, 6.0),
) -> dict:
    """
    配置と大きさの情報を除去したOwner輪郭を比較する。
    """
    left = _normalize_binary_shape(left_mask)
    right = _normalize_binary_shape(right_mask)
    left_bool = left > 0
    best: dict | None = None
    for mode, oriented in (("direct", right), ("mirror-x", np.fliplr(right))):
        for angle in angles:
            candidate = _rotate_binary_shape(oriented, angle)
            intersection, union, iou = _binary_iou(left_bool, candidate > 0)
            record = {
                "iou": round(float(iou), 6),
                "intersection_pixels": int(intersection),
                "union_pixels": int(union),
                "orientation": mode,
                "angle_deg": float(angle),
            }
            if best is None:
                best = record
                continue
            ciou = float(record["iou"])
            biou = float(best["iou"])
            cmotion = abs(float(angle)) + (2.0 if mode == "mirror-x" else 0.0)
            bmotion = abs(float(best["angle_deg"])) + (2.0 if best["orientation"] == "mirror-x" else 0.0)
            if ciou > biou + 1e-12 or (abs(ciou - biou) <= 1e-12 and cmotion < bmotion):
                best = record
    if best is None:
        best = {
            "iou": 0.0,
            "intersection_pixels": 0,
            "union_pixels": 0,
            "orientation": "direct",
            "angle_deg": 0.0,
        }
    best["left_normalized_mask"] = left
    right_oriented = np.fliplr(right) if best["orientation"] == "mirror-x" else right
    best["right_normalized_mask"] = _rotate_binary_shape(right_oriented, float(best["angle_deg"]))
    return best


def _maximum_similarity_assignment(similarities: list[list[float]]) -> list[tuple[int, int]]:
    """Return a global one-to-one maximum-similarity assignment.

    Uses the rectangular Hungarian algorithm in O(n^2 m), avoiding the
    exponential bitmask DP used by the earlier small unmatched-owner matcher.
    """
    if not similarities or not similarities[0]:
        return []
    row_count = len(similarities)
    col_count = len(similarities[0])
    if any(len(row) != col_count for row in similarities):
        raise ValueError("similarity matrix must be rectangular")
    if row_count > col_count:
        transposed = [list(values) for values in zip(*similarities)]
        swapped = _maximum_similarity_assignment(transposed)
        return [(col, row) for row, col in swapped]

    # 最小費用のHungarian Algorithmを使用し、類似度に負符号を付けて最大化へ変換する。
    n, m = row_count, col_count
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = -float(similarities[i0 - 1][j - 1]) - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(0, m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]
    return sorted(pairs)


def _similarity_confidence(value: float) -> str:
    value = float(value)
    if value >= 0.72:
        return "high"
    if value >= 0.50:
        return "medium"
    return "low"


def _translate_binary_mask(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    height, width = mask.shape
    result = np.zeros_like(mask)
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(width, width - dx)
    src_y1 = min(height, height - dy)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return result
    dst_x0 = src_x0 + dx
    dst_y0 = src_y0 + dy
    dst_x1 = src_x1 + dx
    dst_y1 = src_y1 + dy
    result[dst_y0:dst_y1, dst_x0:dst_x1] = mask[src_y0:src_y1, src_x0:src_x1]
    return result


def _best_local_binary_translation(
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    *,
    max_center_shift: int = 96,
    refine_radius: int = 12,
) -> dict:
    """
    対応するOwner同士の二値IoUを最大化する小さな平行移動を探索する。
    """
    left_bool = left_mask > 0
    right_bool = right_mask > 0
    left_yx = np.argwhere(left_bool)
    right_yx = np.argwhere(right_bool)
    initial_intersection, initial_union, initial_iou = _binary_iou(left_bool, right_bool)
    if not len(left_yx) or not len(right_yx):
        return {
            "dx": 0, "dy": 0,
            "initial_intersection": initial_intersection,
            "initial_union": initial_union,
            "initial_iou": round(initial_iou, 6),
            "aligned_intersection": initial_intersection,
            "aligned_union": initial_union,
            "aligned_iou": round(initial_iou, 6),
            "iou_gain": 0.0,
            "aligned_mask": right_mask.copy(),
        }

    left_cx = (float(left_yx[:, 1].min()) + float(left_yx[:, 1].max())) * 0.5
    left_cy = (float(left_yx[:, 0].min()) + float(left_yx[:, 0].max())) * 0.5
    right_cx = (float(right_yx[:, 1].min()) + float(right_yx[:, 1].max())) * 0.5
    right_cy = (float(right_yx[:, 0].min()) + float(right_yx[:, 0].max())) * 0.5
    centre_dx = int(round(left_cx - right_cx))
    centre_dy = int(round(left_cy - right_cy))
    centre_dx = max(-max_center_shift, min(max_center_shift, centre_dx))
    centre_dy = max(-max_center_shift, min(max_center_shift, centre_dy))

    left_width = left_mask.shape[1]
    left_set = {int(y) * left_width + int(x) for y, x in left_yx}
    right_points = [(int(y), int(x)) for y, x in right_yx]
    right_count = len(right_points)
    left_count = len(left_set)
    height, width = left_mask.shape

    candidate_centres = {(0, 0), (centre_dx, centre_dy)}
    best = (initial_iou, initial_intersection, 0, 0)
    seen: set[tuple[int, int]] = set()
    for base_dx, base_dy in candidate_centres:
        for dy in range(base_dy - refine_radius, base_dy + refine_radius + 1):
            for dx in range(base_dx - refine_radius, base_dx + refine_radius + 1):
                if (dx, dy) in seen:
                    continue
                seen.add((dx, dy))
                intersection = 0
                valid_right = 0
                for y, x in right_points:
                    yy = y + dy
                    xx = x + dx
                    if 0 <= yy < height and 0 <= xx < width:
                        valid_right += 1
                        if yy * width + xx in left_set:
                            intersection += 1
                union = left_count + valid_right - intersection
                iou = intersection / max(1, union)
                # IoUが同率なら移動量の小さい候補を優先する。
                if iou > best[0] + 1e-12 or (abs(iou - best[0]) <= 1e-12 and abs(dx) + abs(dy) < abs(best[2]) + abs(best[3])):
                    best = (iou, intersection, dx, dy)

    best_iou, best_intersection, best_dx, best_dy = best
    aligned = _translate_binary_mask(right_mask, best_dx, best_dy)
    aligned_intersection, aligned_union, checked_iou = _binary_iou(left_mask, aligned)
    return {
        "dx": int(best_dx),
        "dy": int(best_dy),
        "initial_intersection": initial_intersection,
        "initial_union": initial_union,
        "initial_iou": round(initial_iou, 6),
        "aligned_intersection": aligned_intersection,
        "aligned_union": aligned_union,
        "aligned_iou": round(checked_iou, 6),
        "iou_gain": round(checked_iou - initial_iou, 6),
        "aligned_mask": aligned,
    }


def _fast_binary_translation_alignment(
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    *,
    max_center_shift: int = 128,
) -> dict:
    """
    点ごとのループではなく重なりSliceを使い、範囲を限定して高速に平行移動を探索する。
    """
    left = left_mask > 0
    right = right_mask > 0
    initial_intersection, initial_union, initial_iou = _binary_iou(left, right)
    lb = _binary_mask_bbox(left)
    rb = _binary_mask_bbox(right)
    if lb is None or rb is None:
        return {
            "dx": 0, "dy": 0, "aligned_intersection": initial_intersection,
            "aligned_union": initial_union, "aligned_iou": round(initial_iou, 6),
            "aligned_mask": right_mask.copy(),
        }
    lcx = (lb[0] + lb[2] - 1) * 0.5
    lcy = (lb[1] + lb[3] - 1) * 0.5
    rcx = (rb[0] + rb[2] - 1) * 0.5
    rcy = (rb[1] + rb[3] - 1) * 0.5
    centre_dx = max(-max_center_shift, min(max_center_shift, int(round(lcx - rcx))))
    centre_dy = max(-max_center_shift, min(max_center_shift, int(round(lcy - rcy))))
    height, width = left.shape
    left_count = int(np.count_nonzero(left))

    def score(dx: int, dy: int) -> tuple[float, int, int]:
        lx0 = max(0, dx)
        ly0 = max(0, dy)
        lx1 = min(width, width + dx)
        ly1 = min(height, height + dy)
        if lx0 >= lx1 or ly0 >= ly1:
            return 0.0, 0, left_count
        rx0 = lx0 - dx
        ry0 = ly0 - dy
        rx1 = lx1 - dx
        ry1 = ly1 - dy
        right_view = right[ry0:ry1, rx0:rx1]
        valid_right = int(np.count_nonzero(right_view))
        intersection = int(np.count_nonzero(left[ly0:ly1, lx0:lx1] & right_view))
        union = left_count + valid_right - intersection
        return intersection / max(1, union), intersection, union

    best = (initial_iou, initial_intersection, initial_union, 0, 0)
    seen: set[tuple[int, int]] = set()
    for base_dx, base_dy in ((0, 0), (centre_dx, centre_dy)):
        for dy in range(base_dy - 12, base_dy + 13, 4):
            for dx in range(base_dx - 12, base_dx + 13, 4):
                if (dx, dy) in seen:
                    continue
                seen.add((dx, dy))
                iou, inter, union = score(dx, dy)
                if iou > best[0] + 1e-12 or (abs(iou - best[0]) <= 1e-12 and abs(dx) + abs(dy) < abs(best[3]) + abs(best[4])):
                    best = (iou, inter, union, dx, dy)
    coarse_dx, coarse_dy = best[3], best[4]
    for dy in range(coarse_dy - 3, coarse_dy + 4):
        for dx in range(coarse_dx - 3, coarse_dx + 4):
            iou, inter, union = score(dx, dy)
            if iou > best[0] + 1e-12 or (abs(iou - best[0]) <= 1e-12 and abs(dx) + abs(dy) < abs(best[3]) + abs(best[4])):
                best = (iou, inter, union, dx, dy)
    aligned = _translate_binary_mask(right_mask, best[3], best[4])
    inter, union, iou = _binary_iou(left_mask, aligned)
    return {
        "dx": int(best[3]), "dy": int(best[4]),
        "aligned_intersection": inter, "aligned_union": union,
        "aligned_iou": round(iou, 6), "aligned_mask": aligned,
    }


def _binary_mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask > 0)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _bbox_gap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    gap_x = max(0, bx0 - ax1, ax0 - bx1)
    gap_y = max(0, by0 - ay1, ay0 - by1)
    return float(math.hypot(gap_x, gap_y))


def _cluster_binary_owner_masks(items: list[dict], *, gap_threshold: float = 72.0) -> list[list[int]]:
    """
    Left面上で空間的に近い文字図形のOwner Maskをグループ化する。
    """
    bboxes = [_binary_mask_bbox(item["left_mask"]) for item in items]
    adjacency: list[set[int]] = [set() for _ in items]
    for i in range(len(items)):
        if bboxes[i] is None:
            continue
        for j in range(i + 1, len(items)):
            if bboxes[j] is None:
                continue
            if _bbox_gap(bboxes[i], bboxes[j]) <= gap_threshold:
                adjacency[i].add(j)
                adjacency[j].add(i)
    clusters: list[list[int]] = []
    visited: set[int] = set()
    for start in range(len(items)):
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        cluster: list[int] = []
        while stack:
            current = stack.pop()
            cluster.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        clusters.append(sorted(cluster))
    clusters.sort(key=lambda values: min(values) if values else 10**9)
    return clusters


def _affine_binary_about_center(mask: np.ndarray, *, angle_deg: float, scale: float) -> np.ndarray:
    """
    同じCanvas上でMask外接矩形の中心を基準に拡縮・回転する。
    """
    bbox = _binary_mask_bbox(mask)
    if bbox is None:
        return mask.copy()
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1 - 1) * 0.5
    cy = (y0 + y1 - 1) * 0.5
    theta = math.radians(float(angle_deg))
    inv_scale = 1.0 / max(1e-6, float(scale))
    cos_t = math.cos(theta) * inv_scale
    sin_t = math.sin(theta) * inv_scale
    # PillowのAFFINE係数は出力座標から入力座標への逆写像を表す。
    a = cos_t
    b = sin_t
    d = -sin_t
    e = cos_t
    c = cx - a * cx - b * cy
    f = cy - d * cx - e * cy
    image = Image.fromarray((mask > 0).astype(np.uint8) * 255, "L")
    transformed = image.transform(
        image.size,
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.NEAREST,
        fillcolor=0,
    )
    return (np.asarray(transformed, dtype=np.uint8) > 0).astype(np.uint8) * 255


def _full_affine_binary_about_center(
    mask: np.ndarray,
    *,
    angle_deg: float,
    scale_x: float,
    scale_y: float,
    shear_x: float = 0.0,
    shear_y: float = 0.0,
) -> np.ndarray:
    """
    Mask外接矩形の中心を基準に小さな一般アフィン変換を適用する。
    """
    bbox = _binary_mask_bbox(mask)
    if bbox is None:
        return mask.copy()
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1 - 1) * 0.5
    cy = (y0 + y1 - 1) * 0.5
    theta = math.radians(float(angle_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    sx = max(1e-6, float(scale_x))
    sy = max(1e-6, float(scale_y))
    scale = np.array([[sx, 0.0], [0.0, sy]], dtype=float)
    shear = np.array([[1.0, float(shear_x)], [float(shear_y), 1.0]], dtype=float)
    rotation = np.array([[cos_t, -sin_t], [sin_t, cos_t]], dtype=float)
    forward = rotation @ shear @ scale
    if abs(float(np.linalg.det(forward))) < 1e-8:
        return mask.copy()
    inv = np.linalg.inv(forward)
    a, b = float(inv[0, 0]), float(inv[0, 1])
    d, e = float(inv[1, 0]), float(inv[1, 1])
    c = cx - a * cx - b * cy
    f = cy - d * cx - e * cy
    image = Image.fromarray((mask > 0).astype(np.uint8) * 255, "L")
    transformed = image.transform(
        image.size, Image.Transform.AFFINE, (a, b, c, d, e, f),
        resample=Image.Resampling.NEAREST, fillcolor=0,
    )
    return (np.asarray(transformed, dtype=np.uint8) > 0).astype(np.uint8) * 255


def _best_cluster_full_affine_alignment(left_mask: np.ndarray, right_mask: np.ndarray) -> dict:
    """
    非等方拡縮と小さなShearでr37のCluster位置合わせを精密化する。
    """
    left_bbox = _binary_mask_bbox(left_mask)
    right_bbox = _binary_mask_bbox(right_mask)
    if left_bbox is None or right_bbox is None:
        inter, union, iou = _binary_iou(left_mask, right_mask)
        return {
            "angle_deg": 0.0, "scale_x": 1.0, "scale_y": 1.0,
            "shear_x": 0.0, "shear_y": 0.0, "dx": 0, "dy": 0,
            "aligned_iou": round(iou, 6), "aligned_intersection": inter,
            "aligned_union": union, "aligned_mask": right_mask.copy(),
            "initial_iou": round(iou, 6), "r37_iou": round(iou, 6),
            "iou_gain_vs_r35": 0.0, "iou_gain_vs_r37": 0.0,
        }

    height, width = left_mask.shape
    pad = 144
    x0 = max(0, min(left_bbox[0], right_bbox[0]) - pad)
    y0 = max(0, min(left_bbox[1], right_bbox[1]) - pad)
    x1 = min(width, max(left_bbox[2], right_bbox[2]) + pad)
    y1 = min(height, max(left_bbox[3], right_bbox[3]) + pad)
    left_work = left_mask[y0:y1, x0:x1]
    right_work = right_mask[y0:y1, x0:x1]

    baseline = _best_cluster_affine_alignment(left_work, right_work)
    baseline_iou = float(baseline.get("aligned_iou") or 0.0)
    base_angle = float(baseline.get("angle_deg") or 0.0)
    base_scale = float(baseline.get("scale") or 1.0)
    best = {
        "angle_deg": base_angle, "scale_x": base_scale, "scale_y": base_scale,
        "shear_x": 0.0, "shear_y": 0.0,
        "dx": int(baseline.get("dx") or 0), "dy": int(baseline.get("dy") or 0),
        "aligned_iou": baseline_iou,
        "aligned_intersection": int(baseline.get("aligned_intersection") or 0),
        "aligned_union": int(baseline.get("aligned_union") or 0),
    }

    def consider(angle: float, sx: float, sy: float, shx: float, shy: float) -> None:
        nonlocal best
        transformed = _full_affine_binary_about_center(
            right_work, angle_deg=angle, scale_x=sx, scale_y=sy, shear_x=shx, shear_y=shy
        )
        translation = _fast_binary_translation_alignment(
            left_work, transformed, max_center_shift=128
        )
        translation.pop("aligned_mask", None)
        candidate = {
            "angle_deg": float(angle), "scale_x": float(sx), "scale_y": float(sy),
            "shear_x": float(shx), "shear_y": float(shy), **translation,
        }
        ciou = float(candidate.get("aligned_iou") or 0.0)
        biou = float(best.get("aligned_iou") or 0.0)
        cmotion = abs(angle) + abs(sx - 1.0) * 100 + abs(sy - 1.0) * 100 + (abs(shx) + abs(shy)) * 100 + abs(int(candidate.get("dx") or 0)) + abs(int(candidate.get("dy") or 0))
        bmotion = abs(float(best.get("angle_deg") or 0.0)) + abs(float(best.get("scale_x") or 1.0) - 1.0) * 100 + abs(float(best.get("scale_y") or 1.0) - 1.0) * 100 + (abs(float(best.get("shear_x") or 0.0)) + abs(float(best.get("shear_y") or 0.0))) * 100 + abs(int(best.get("dx") or 0)) + abs(int(best.get("dy") or 0))
        if ciou > biou + 1e-12 or (abs(ciou - biou) <= 1e-12 and cmotion < bmotion):
            best = candidate

    for angle in (base_angle - 3.0, base_angle, base_angle + 3.0):
        for fx in (0.94, 1.0, 1.06):
            for fy in (0.94, 1.0, 1.06):
                consider(angle, base_scale * fx, base_scale * fy, 0.0, 0.0)

    anchor_angle = float(best.get("angle_deg") or 0.0)
    anchor_sx = float(best.get("scale_x") or 1.0)
    anchor_sy = float(best.get("scale_y") or 1.0)
    for shx in (-0.04, 0.0, 0.04):
        for shy in (-0.04, 0.0, 0.04):
            consider(anchor_angle, anchor_sx, anchor_sy, shx, shy)

    # 最良候補の変換だけを元解像度の原本Maskへ適用する。
    full_transformed = _full_affine_binary_about_center(
        right_mask,
        angle_deg=float(best.get("angle_deg") or 0.0),
        scale_x=float(best.get("scale_x") or 1.0),
        scale_y=float(best.get("scale_y") or 1.0),
        shear_x=float(best.get("shear_x") or 0.0),
        shear_y=float(best.get("shear_y") or 0.0),
    )
    full_aligned = _translate_binary_mask(
        full_transformed, int(best.get("dx") or 0), int(best.get("dy") or 0)
    )
    aligned_intersection, aligned_union, aligned_iou = _binary_iou(left_mask, full_aligned)
    initial_intersection, initial_union, initial_iou = _binary_iou(left_mask, right_mask)
    best["aligned_mask"] = full_aligned
    best["aligned_intersection"] = aligned_intersection
    best["aligned_union"] = aligned_union
    best["aligned_iou"] = round(aligned_iou, 6)
    best["initial_intersection"] = initial_intersection
    best["initial_union"] = initial_union
    best["initial_iou"] = round(initial_iou, 6)
    best["r37_iou"] = round(baseline_iou, 6)
    best["iou_gain_vs_r35"] = round(aligned_iou - initial_iou, 6)
    best["iou_gain_vs_r37"] = round(aligned_iou - baseline_iou, 6)
    return best


def _best_cluster_affine_alignment(
    left_mask: np.ndarray,
    right_mask: np.ndarray,
    *,
    angles: tuple[float, ...] = (-6.0, -3.0, 0.0, 3.0, 6.0),
    scales: tuple[float, ...] = (0.94, 1.0, 1.06),
) -> dict:
    """
    Cluster全体の保守的なアフィン位置合わせを探索する。
    """
    initial_intersection, initial_union, initial_iou = _binary_iou(left_mask, right_mask)
    best: dict | None = None
    for angle in angles:
        for scale in scales:
            affine_mask = _affine_binary_about_center(right_mask, angle_deg=angle, scale=scale)
            translation = _best_local_binary_translation(
                left_mask,
                affine_mask,
                max_center_shift=96,
                refine_radius=10,
            )
            aligned_mask = translation.pop("aligned_mask")
            candidate = {
                "angle_deg": float(angle),
                "scale": float(scale),
                **translation,
                "aligned_mask": aligned_mask,
            }
            if best is None:
                best = candidate
                continue
            candidate_iou = float(candidate.get("aligned_iou") or 0.0)
            best_iou = float(best.get("aligned_iou") or 0.0)
            candidate_motion = abs(float(angle)) + abs(float(scale) - 1.0) * 100.0 + abs(int(candidate["dx"])) + abs(int(candidate["dy"]))
            best_motion = abs(float(best["angle_deg"])) + abs(float(best["scale"]) - 1.0) * 100.0 + abs(int(best["dx"])) + abs(int(best["dy"]))
            if candidate_iou > best_iou + 1e-12 or (abs(candidate_iou - best_iou) <= 1e-12 and candidate_motion < best_motion):
                best = candidate
    if best is None:
        best = {
            "angle_deg": 0.0,
            "scale": 1.0,
            "dx": 0,
            "dy": 0,
            "aligned_intersection": initial_intersection,
            "aligned_union": initial_union,
            "aligned_iou": round(initial_iou, 6),
            "aligned_mask": right_mask.copy(),
        }
    best["initial_intersection"] = initial_intersection
    best["initial_union"] = initial_union
    best["initial_iou"] = round(initial_iou, 6)
    best["iou_gain"] = round(float(best.get("aligned_iou") or 0.0) - initial_iou, 6)
    return best


def _owner_pair_cost(left: dict, right: dict, canvas_size: tuple[int, int]) -> dict:
    width, height = (float(canvas_size[0]), float(canvas_size[1]))
    lb = list(left.get("bbox_pixels") or [0, 0, 0, 0])
    rb = list(right.get("bbox_pixels") or [0, 0, 0, 0])
    lcx = ((float(lb[0]) + float(lb[2])) * 0.5) / max(1.0, width)
    lcy = ((float(lb[1]) + float(lb[3])) * 0.5) / max(1.0, height)
    rcx = ((float(rb[0]) + float(rb[2])) * 0.5) / max(1.0, width)
    rcy = ((float(rb[1]) + float(rb[3])) * 0.5) / max(1.0, height)
    direct_distance = math.hypot(lcx - rcx, lcy - rcy)
    mirrored_distance = math.hypot((1.0 - lcx) - rcx, lcy - rcy)
    spatial_mode = "mirror-x" if mirrored_distance <= direct_distance else "direct"
    spatial_distance = min(direct_distance, mirrored_distance)

    lp = max(1.0, float(left.get("final_mask_exposed_pixel_count") or 0))
    rp = max(1.0, float(right.get("final_mask_exposed_pixel_count") or 0))
    pixel_log_delta = abs(math.log(rp / lp))
    la = max(1e-6, float(left.get("aspect_ratio") or 0.0))
    ra = max(1e-6, float(right.get("aspect_ratio") or 0.0))
    aspect_log_delta = abs(math.log(ra / la))
    fill_delta = abs(float(left.get("fill_ratio") or 0.0) - float(right.get("fill_ratio") or 0.0))
    lc = max(1.0, float(left.get("component_count") or 0))
    rc = max(1.0, float(right.get("component_count") or 0))
    component_log_delta = abs(math.log(rc / lc))
    ll = max(1.0, float(left.get("largest_component_pixels") or 0))
    rl = max(1.0, float(right.get("largest_component_pixels") or 0))
    largest_log_delta = abs(math.log(rl / ll))

    left_group = str(left.get("semantic_group") or "")
    right_group = str(right.get("semantic_group") or "")
    group_penalty = 0.0 if left_group == right_group else 3.0
    left_type = str(left.get("type_word_hex") or "")
    right_type = str(right.get("type_word_hex") or "")
    type_penalty = 0.0 if left_type == right_type else 0.65
    mask_source_penalty = 0.0 if left.get("mask_source") == right.get("mask_source") else 0.30
    depth_penalty = 0.12 * abs(int(left.get("mask_group_depth") or 0) - int(right.get("mask_group_depth") or 0))

    cost = (
        group_penalty
        + type_penalty
        + mask_source_penalty
        + depth_penalty
        + 1.35 * pixel_log_delta
        + 0.85 * aspect_log_delta
        + 4.0 * fill_delta
        + 0.55 * component_log_delta
        + 0.55 * largest_log_delta
        + 1.75 * spatial_distance
    )
    return {
        "cost": round(float(cost), 6),
        "spatial_mode": spatial_mode,
        "spatial_distance": round(float(spatial_distance), 6),
        "direct_distance": round(float(direct_distance), 6),
        "mirrored_distance": round(float(mirrored_distance), 6),
        "pixel_log_delta": round(float(pixel_log_delta), 6),
        "aspect_log_delta": round(float(aspect_log_delta), 6),
        "fill_delta": round(float(fill_delta), 6),
        "component_log_delta": round(float(component_log_delta), 6),
        "largest_component_log_delta": round(float(largest_log_delta), 6),
        "semantic_group_match": left_group == right_group,
        "type_word_match": left_type == right_type,
    }


def _owner_pair_confidence(cost: float) -> str:
    if float(cost) <= 1.25:
        return "high"
    if float(cost) <= 2.25:
        return "medium"
    return "low"


def _owner_pair_is_accepted(cost: float) -> bool:
    return _owner_pair_confidence(cost) in {"high", "medium"}


def _minimum_cost_owner_assignment(
    left_items: list[dict], right_items: list[dict], canvas_size: tuple[int, int]
) -> list[dict]:
    if not left_items or not right_items:
        return []
    # 現行診断は上位24 Ownerを保持するため、未対応集合は小さい。
    # Greedy対応ではなくBitmask DPで全体最小費用の対応を解く。
    swap = len(left_items) > len(right_items)
    rows = right_items if swap else left_items
    cols = left_items if swap else right_items
    costs = [[_owner_pair_cost(row, col, canvas_size) for col in cols] for row in rows]
    states: dict[int, tuple[float, list[tuple[int, int]]]] = {0: (0.0, [])}
    for row_index in range(len(rows)):
        next_states: dict[int, tuple[float, list[tuple[int, int]]]] = {}
        for mask, (total, pairs) in states.items():
            for col_index in range(len(cols)):
                if mask & (1 << col_index):
                    continue
                new_mask = mask | (1 << col_index)
                new_total = total + float(costs[row_index][col_index]["cost"])
                existing = next_states.get(new_mask)
                if existing is None or new_total < existing[0]:
                    next_states[new_mask] = (new_total, pairs + [(row_index, col_index)])
        states = next_states
    if not states:
        return []
    _, best_pairs = min(states.values(), key=lambda value: value[0])
    result: list[dict] = []
    for row_index, col_index in best_pairs:
        if swap:
            left = cols[col_index]
            right = rows[row_index]
            detail = _owner_pair_cost(left, right, canvas_size)
        else:
            left = rows[row_index]
            right = cols[col_index]
            detail = costs[row_index][col_index]
        result.append({
            "left_shape_index": int(left.get("shape_index")),
            "right_shape_index": int(right.get("shape_index")),
            "left_source_offset": left.get("source_offset"),
            "right_source_offset": right.get("source_offset"),
            "left_group": left.get("semantic_group"),
            "right_group": right.get("semantic_group"),
            "left_type_word_hex": left.get("type_word_hex"),
            "right_type_word_hex": right.get("type_word_hex"),
            "left_pixels": int(left.get("final_mask_exposed_pixel_count") or 0),
            "right_pixels": int(right.get("final_mask_exposed_pixel_count") or 0),
            **detail,
        })
    return sorted(result, key=lambda item: (float(item["cost"]), int(item["left_shape_index"])))


def _read_printable_ascii_refs(data: bytes) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(rb"[ -~]{12,}", data):
        text = match.group(0).decode("ascii", errors="ignore").strip()
        if text.lower().startswith("game:\\") or text.lower().startswith("game:/"):
            refs.append(text)
    return sorted(set(refs), key=str.casefold)


def _manifest_model_record(root: ET.Element, suffix: str) -> dict:
    wanted = suffix.replace("\\", "/").casefold()
    for model in root.findall(".//Model"):
        path = str(model.attrib.get("path") or "").replace("\\", "/")
        if not path.casefold().endswith(wanted):
            continue
        return {
            "path": path,
            "lods": model.attrib.get("LODs"),
            "materials": [str(x.attrib.get("path") or "") for x in model.findall("Material")],
            "swatchbins": [str(x.attrib.get("path") or "") for x in model.findall("Swatchbin")],
        }
    return {}


def _vehicle_asset_zip_diagnostics(archive_path: Path, expected_car_id: int | None = None) -> dict:
    archive = archive_path.expanduser().resolve()
    if not archive.is_file():
        raise FullLiveryPackageError(f"Vehicle asset ZIP not found: {archive}")
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = [name.replace("\\", "/") for name in bundle.namelist()]
            clip_matches: list[tuple[int, str]] = []
            for name in names:
                match = re.search(r"(?:^|/)carclips_(\d+)\.clipd$", name, re.IGNORECASE)
                if match:
                    clip_matches.append((int(match.group(1)), name))
            if not clip_matches:
                raise FullLiveryPackageError(f"No carclips_<id>.clipd entry found in {archive.name}.")
            unique_ids = sorted({item[0] for item in clip_matches})
            if len(unique_ids) != 1:
                raise FullLiveryPackageError(f"Ambiguous car IDs in {archive.name}: {unique_ids}")
            car_id = unique_ids[0]
            if expected_car_id is not None and car_id != int(expected_car_id):
                raise FullLiveryPackageError(
                    f"Vehicle asset ZIP Car ID {car_id} does not match requested Car ID {expected_car_id}."
                )
            manifest_name = next((n for n in names if n.casefold() == "manifest.xml"), None)
            if not manifest_name:
                raise FullLiveryPackageError(f"Manifest.xml not found in {archive.name}.")
            manifest_root = ET.fromstring(bundle.read(manifest_name))
            body_record = _manifest_model_record(manifest_root, "/scene/exterior/platform/body_a.modelbin")
            livery_record = _manifest_model_record(manifest_root, "/scene/exterior/platform/bodylivery_a.modelbin")
            body_entry = next((n for n in names if n.casefold().endswith("scene/exterior/platform/body_a.modelbin")), None)
            livery_entry = next((n for n in names if n.casefold().endswith("scene/exterior/platform/bodylivery_a.modelbin")), None)
            body_embedded_refs = _read_printable_ascii_refs(bundle.read(body_entry)) if body_entry else []
            livery_embedded_refs = _read_printable_ascii_refs(bundle.read(livery_entry)) if livery_entry else []
    except (zipfile.BadZipFile, OSError, ET.ParseError) as exc:
        raise FullLiveryPackageError(f"Unable to inspect vehicle asset ZIP {archive}: {exc}") from exc

    stat = archive.stat()
    asset = VehicleAsset(
        car_id=car_id,
        model_code=archive.stem,
        archive_path=str(archive),
        archive_name=archive.name,
        archive_size=stat.st_size,
        archive_mtime_ns=stat.st_mtime_ns,
        clip_entry=clip_matches[0][1],
    )
    archive_inventory = inspect_vehicle_archive(asset)
    projection = read_projection_metadata(asset)
    try:
        inspection_models = inspection_model_entries(asset)
    except Exception as exc:
        inspection_models = []
        inspection_model_error = str(exc)
    else:
        inspection_model_error = None
    assembly = read_vehicle_assembly_metadata(asset)

    body_materials = list(body_record.get("materials") or [])
    livery_materials = list(livery_record.get("materials") or [])
    body_swatches = list(body_record.get("swatchbins") or [])
    livery_swatches = list(livery_record.get("swatchbins") or [])
    livery_sticker_refs = [x for x in livery_materials + livery_embedded_refs if "livery_sticker.materialbin" in x.casefold()]
    carpaint_refs = [x for x in body_materials + body_embedded_refs if x.casefold().endswith("/carpaint.materialbin") or x.casefold().endswith("\\carpaint.materialbin")]
    paint_livery_rmao_refs = [x for x in livery_swatches + livery_embedded_refs if "defaultrmao_paintlivery" in x.casefold()]

    followup = []
    for value in livery_sticker_refs + carpaint_refs + paint_livery_rmao_refs:
        if value and value not in followup:
            followup.append(value)

    return {
        "format": "lo4fh6_vehicle_asset_material_diagnostics_v1",
        "archive": archive_inventory,
        "projection": projection,
        "assembly": assembly,
        "inspection_model_entries": inspection_models,
        "inspection_model_error": inspection_model_error,
        "body": {
            "manifest": body_record,
            "model_entry": body_entry,
            "embedded_game_refs": body_embedded_refs,
        },
        "body_livery": {
            "manifest": livery_record,
            "model_entry": livery_entry,
            "embedded_game_refs": livery_embedded_refs,
        },
        "material_evidence": {
            "base_body_carpaint_refs": carpaint_refs,
            "livery_sticker_refs": livery_sticker_refs,
            "paint_livery_rmao_refs": paint_livery_rmao_refs,
            "separate_base_and_livery_material_paths": bool(carpaint_refs and livery_sticker_refs),
            "interpretation": (
                "The stock body and body-livery overlay resolve to different FH6 material paths. "
                "This proves separate material routing, but not the numeric roughness/clearcoat values inside those external material assets."
            ),
        },
        "followup_external_game_assets": followup,
    }


def _zip_read_suffix_casefold(archive: Path, suffix: str) -> tuple[str, bytes]:
    suffix_cf = suffix.replace("\\", "/").casefold()
    with zipfile.ZipFile(archive) as bundle:
        matches = [name for name in bundle.namelist() if name.replace("\\", "/").casefold().endswith(suffix_cf)]
        if not matches:
            raise FullLiveryPackageError(f"Required asset {suffix!r} was not found in {archive}.")
        matches.sort(key=lambda value: (len(value), value.casefold()))
        member = matches[0]
        return member, bundle.read(member)


def _printable_ascii_strings(data: bytes, minimum: int = 4) -> list[str]:
    return [match.group(0).decode("ascii", errors="replace") for match in re.finditer(rb"[ -~]{%d,}" % minimum, data)]


def _shader_path_from_material(data: bytes) -> str | None:
    candidates = [value for value in _printable_ascii_strings(data) if ".shaderbin" in value.casefold()]
    if not candidates:
        return None
    # パスのGame:直前にBundleの1バイト接頭辞が入る場合が多い。
    value = max(candidates, key=len)
    game_pos = value.casefold().find("game:")
    return value[game_pos:] if game_pos >= 0 else value


def _plausible_float4_defaults(data: bytes) -> list[dict]:
    found: list[dict] = []
    for offset in range(0, max(0, len(data) - 15)):
        values = struct.unpack_from("<4f", data, offset)
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            continue
        if not (0.999 <= values[3] <= 1.001):
            continue
        if max(values[:3]) - min(values[:3]) > 1e-7:
            continue
        if not (1e-6 < values[0] < 0.999):
            continue
        if found and offset - int(found[-1]["offset"]) < 4:
            continue
        found.append({
            "offset": offset,
            "rgba": [round(float(value), 9) for value in values],
        })
    return found


def _material_record_diagnostics(member: str, data: bytes) -> dict:
    shader = _shader_path_from_material(data)
    shader_end = -1
    if shader:
        encoded = shader.encode("ascii", errors="ignore")
        pos = data.find(encoded)
        if pos >= 0:
            shader_end = pos + len(encoded)
    trailing = data[shader_end:] if shader_end >= 0 else b""
    return {
        "member": member,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "shader_path": shader,
        "printable_ascii": _printable_ascii_strings(data),
        "plausible_float4_defaults": _plausible_float4_defaults(data),
        "bytes_after_shader_path": len(trailing),
        "nonzero_bytes_after_shader_path": sum(1 for value in trailing if value != 0),
    }


def _shader_xml_from_zip(shader_zip: Path, expected_suffix: str) -> tuple[str, ET.Element]:
    member, data = _zip_read_suffix_casefold(shader_zip, expected_suffix)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FullLiveryPackageError(f"Invalid shader XML {member!r} in {shader_zip}: {exc}") from exc
    return member, root


def _shader_xml_inventory(root: ET.Element) -> dict:
    params = []
    for elem in root.findall('.//Parameter'):
        params.append({
            'parametername': elem.attrib.get('parametername'),
            'size': int(elem.attrib.get('size', '0') or 0),
            'referenced': str(elem.attrib.get('referenced', '')).casefold() == 'true',
        })
    textures = []
    for elem in root.findall('.//Texture'):
        textures.append({
            'parametername': elem.attrib.get('parametername'),
            'referenced': str(elem.attrib.get('referenced', '')).casefold() == 'true',
        })
    variants = []
    for elem in root.findall('.//ExportVariant'):
        variants.append({
            'name': elem.attrib.get('name'),
            'vertexinputs': elem.attrib.get('vertexinputs'),
            'textureusage': elem.attrib.get('textureusage'),
            'constantsusagecount': int(elem.attrib.get('constantsusagecount', '0') or 0),
            'constantsusagesize': int(elem.attrib.get('constantsusagesize', '0') or 0),
        })
    return {
        'parameter_count': len(params),
        'parameters': params,
        'texture_count': len(textures),
        'textures': textures,
        'variant_count': len(variants),
        'variants': variants,
    }


def _shader_library_diagnostics(carpaint_shader_zip: Path, livery_shader_zip: Path) -> dict:
    carpaint_shader_zip = carpaint_shader_zip.expanduser().resolve()
    livery_shader_zip = livery_shader_zip.expanduser().resolve()
    car_member, car_root = _shader_xml_from_zip(carpaint_shader_zip, 'car_automotive_paint.shaderbin.xml')
    liv_member, liv_root = _shader_xml_from_zip(livery_shader_zip, 'car_livery.shaderbin.xml')
    car = _shader_xml_inventory(car_root)
    liv = _shader_xml_inventory(liv_root)
    car_params = {x['parametername'] for x in car['parameters'] if x.get('parametername')}
    liv_params = {x['parametername'] for x in liv['parameters'] if x.get('parametername')}
    car_tex = {x['parametername'] for x in car['textures'] if x.get('parametername')}
    liv_tex = {x['parametername'] for x in liv['textures'] if x.get('parametername')}

    clearcoat_params = sorted(x for x in car_params if 'clearcoat' in x.casefold())
    livery_switch_params = sorted(x for x in car_params if 'livery' in x.casefold())
    livery_clearcoat_params = sorted(x for x in liv_params if 'clearcoat' in x.casefold())
    roughness_params_car = sorted(x for x in car_params if 'rough' in x.casefold())
    roughness_params_liv = sorted(x for x in liv_params if 'rough' in x.casefold())
    shared_params = sorted(car_params & liv_params)
    shared_textures = sorted(car_tex & liv_tex)

    return {
        'format': 'lo4fh6_shader_library_diagnostics_v1',
        'carpaint_shader_zip': str(carpaint_shader_zip),
        'livery_shader_zip': str(livery_shader_zip),
        'carpaint_shader_xml_member': car_member,
        'livery_shader_xml_member': liv_member,
        'carpaint': car,
        'livery': liv,
        'comparison': {
            'shared_parameters': shared_params,
            'carpaint_only_parameters': sorted(car_params - liv_params),
            'livery_only_parameters': sorted(liv_params - car_params),
            'shared_textures': shared_textures,
            'carpaint_only_textures': sorted(car_tex - liv_tex),
            'livery_only_textures': sorted(liv_tex - car_tex),
        },
        'evidence': {
            'carpaint_clearcoat_parameters': clearcoat_params,
            'carpaint_livery_switch_parameters': livery_switch_params,
            'livery_shader_clearcoat_parameters': livery_clearcoat_params,
            'carpaint_roughness_parameters': roughness_params_car,
            'livery_roughness_parameters': roughness_params_liv,
            'carpaint_has_clearcoat_on_livery': 'ClearCoatOnLiveryBool' in car_params,
            'carpaint_has_masked_livery': 'MaskedLiveryBool' in car_params,
            'carpaint_has_user_livery_switch': 'UserLiverySwitchBool' in car_params,
            'livery_shader_has_clearcoat_parameter': bool(livery_clearcoat_params),
            'both_use_rough_metal_ao_texture': 'RoughMetalAO_Texture' in car_tex and 'RoughMetalAO_Texture' in liv_tex,
            'interpretation': (
                'The automotive-paint shader explicitly exposes livery-state switches together with clear-coat coverage/roughness controls, '
                'including ClearCoatOnLiveryBool. The separate car-livery shader exposes RoughMetalAO_Texture and roughness-shift controls but no '
                'named clear-coat parameter in the exported XML. This supports a two-path model: the base automotive-paint path owns clear-coat '
                'behaviour and can condition it on livery state, while the livery overlay has its own PBR/RMAO response. The XML proves parameter '
                'availability, not runtime values or branch equations, so it does not by itself establish the exact numeric clear-coat response.'
            ),
        },
    }


def _dxbc_chunk_inventory(data: bytes) -> dict:
    if len(data) < 32 or data[:4] != b"DXBC":
        return {"is_dxbc": False, "size": len(data), "chunks": []}
    total_size = struct.unpack_from("<I", data, 24)[0]
    chunk_count = struct.unpack_from("<I", data, 28)[0]
    if 32 + chunk_count * 4 > len(data):
        return {"is_dxbc": False, "size": len(data), "chunks": [], "error": "truncated chunk table"}
    offsets = struct.unpack_from("<" + "I" * chunk_count, data, 32) if chunk_count else ()
    chunks = []
    for offset in offsets:
        if offset + 8 > len(data):
            continue
        fourcc = data[offset:offset + 4].decode("ascii", errors="replace")
        size = struct.unpack_from("<I", data, offset + 4)[0]
        end = min(len(data), offset + 8 + size)
        payload = data[offset + 8:end]
        item = {
            "fourcc": fourcc,
            "offset": int(offset),
            "payload_size": int(size),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        }
        if fourcc == "DXIL" and len(payload) >= 24:
            program_version, program_type, size_u32 = struct.unpack_from("<HHI", payload, 0)
            magic = payload[8:12].decode("ascii", errors="replace")
            dxil_version, bitcode_offset, bitcode_size = struct.unpack_from("<III", payload, 12)
            bitcode_start = 8 + int(bitcode_offset)
            bitcode_end = min(len(payload), bitcode_start + int(bitcode_size))
            bitcode = payload[bitcode_start:bitcode_end]
            item["dxil"] = {
                "program_version_raw": int(program_version),
                "program_type_raw": int(program_type),
                "program_size_u32": int(size_u32),
                "inner_magic": magic,
                "dxil_version_raw": int(dxil_version),
                "bitcode_offset": int(bitcode_offset),
                "bitcode_size": int(bitcode_size),
                "bitcode_magic_hex": bitcode[:4].hex(),
                "bitcode_sha256": hashlib.sha256(bitcode).hexdigest(),
            }
        chunks.append(item)
    return {
        "is_dxbc": True,
        "size": len(data),
        "declared_total_size": int(total_size),
        "chunk_count": int(chunk_count),
        "chunks": chunks,
    }


def _compiled_shader_zip_inventory(shader_zip: Path, parameter_names: list[str]) -> dict:
    shader_zip = shader_zip.expanduser().resolve()
    artifacts = []
    readable_hits = {name: [] for name in parameter_names}
    with zipfile.ZipFile(shader_zip) as zf:
        for member in sorted(zf.namelist()):
            lower = member.casefold()
            if not lower.endswith((".pcdxil.pso", ".pcdxil.vso", ".pcdxil.lso")):
                continue
            data = zf.read(member)
            for name in parameter_names:
                if name.encode("ascii", errors="ignore") in data:
                    readable_hits[name].append(member)
            ascii_strings = _printable_ascii_strings(data)
            entry_candidates = [
                text for text in ascii_strings
                if text.endswith(("MainPS", "MainVS", "MainCS", "MainHS", "MainDS", "MainGS"))
                or "RayTracing" in text
            ]
            artifacts.append({
                "member": member,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "kind": member.rsplit(".", 1)[-1],
                "entry_candidates": entry_candidates[:8],
                "container": _dxbc_chunk_inventory(data),
            })
    return {
        "zip": str(shader_zip),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "readable_parameter_name_hits": readable_hits,
    }


def _compiled_shader_diagnostics(carpaint_shader_zip: Path, livery_shader_zip: Path) -> dict:
    car_member, car_root = _shader_xml_from_zip(carpaint_shader_zip, "car_automotive_paint.shaderbin.xml")
    liv_member, liv_root = _shader_xml_from_zip(livery_shader_zip, "car_livery.shaderbin.xml")
    focus_names = [
        "ClearCoatRoughness_floatVal",
        "ClearCoatCoverage_floatVal",
        "ClearCoatOnLiveryBool",
        "MaskedLiveryBool",
        "UserLiverySwitchBool",
        "Roughness_Shift_floatVal",
    ]
    car_params = {
        elem.attrib.get("parametername"): str(elem.attrib.get("referenced", "")).casefold() == "true"
        for elem in car_root.findall(".//Parameter")
    }
    liv_params = {
        elem.attrib.get("parametername"): str(elem.attrib.get("referenced", "")).casefold() == "true"
        for elem in liv_root.findall(".//Parameter")
    }
    car = _compiled_shader_zip_inventory(carpaint_shader_zip, focus_names)
    liv = _compiled_shader_zip_inventory(livery_shader_zip, focus_names)
    car_hits = {k: v for k, v in car["readable_parameter_name_hits"].items() if v}
    liv_hits = {k: v for k, v in liv["readable_parameter_name_hits"].items() if v}
    def dxil_sizes(block: dict) -> list[int]:
        out = []
        for artifact in block["artifacts"]:
            for chunk in artifact["container"].get("chunks", []):
                dxil = chunk.get("dxil")
                if dxil:
                    out.append(int(dxil.get("bitcode_size", 0)))
        return out
    return {
        "format": "lo4fh6_compiled_shader_diagnostics_v1",
        "sources": {
            "carpaint_shader_zip": str(Path(carpaint_shader_zip).expanduser().resolve()),
            "livery_shader_zip": str(Path(livery_shader_zip).expanduser().resolve()),
            "carpaint_shader_xml_member": car_member,
            "livery_shader_xml_member": liv_member,
        },
        "carpaint": car,
        "livery": liv,
        "focus_parameter_referenced_flags": {
            "carpaint": {name: car_params.get(name) for name in focus_names if name in car_params},
            "livery": {name: liv_params.get(name) for name in focus_names if name in liv_params},
        },
        "evidence": {
            "carpaint_compiled_artifact_count": car["artifact_count"],
            "livery_compiled_artifact_count": liv["artifact_count"],
            "carpaint_dxil_bitcode_sizes": dxil_sizes(car),
            "livery_dxil_bitcode_sizes": dxil_sizes(liv),
            "carpaint_readable_focus_parameter_hits": car_hits,
            "livery_readable_focus_parameter_hits": liv_hits,
            "focus_names_stripped_from_compiled_artifacts": not car_hits and not liv_hits,
            "carpaint_clearcoat_on_livery_export_referenced": car_params.get("ClearCoatOnLiveryBool"),
            "carpaint_roughness_shift_export_referenced": car_params.get("Roughness_Shift_floatVal"),
            "livery_roughness_shift_export_referenced": liv_params.get("Roughness_Shift_floatVal"),
            "interpretation": (
                "The shipped PSO/VSO/LSO artifacts are DXBC containers carrying optimized DXIL bitcode. "
                "The exported shader XML marks ClearCoatOnLiveryBool and Roughness_Shift_floatVal as referenced, "
                "but their readable parameter names are stripped from the compiled artifacts. Therefore the supplied "
                "runtime binaries confirm separate compiled car-paint and livery paths, while direct name-to-instruction "
                "tracing is not justified from these optimized payloads alone. The next controlled viewer experiment "
                "should use the verified export/default configuration rather than inventing an unproven DXIL equation."
            ),
        },
    }

def _shader_export_base_name(parameter_name: str) -> str:
    """
    エクスポートXMLのParameter名をShaderBin内の短縮名へ対応付ける。
    """
    name = str(parameter_name or "")
    suffixes = (
        "ColorParam", "CarLightParam", "Vector2", "Vector3", "Vector4",
        "_floatVal", "floatVal", "Bool", "_Texture", "Texture",
        "_Value", "Value", "_HeightScale", "HeightScale",
    )
    changed = True
    while changed and name:
        changed = False
        for suffix in suffixes:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[:-len(suffix)]
                changed = True
                break
    return name.rstrip("_")


def _shader_parameter_ids(shader_data: bytes, root: ET.Element) -> dict[str, dict]:
    """
    XMLの名前とShaderBinの短縮名テーブルを照合してParameter IDを特定する。
    """
    resolved: dict[str, dict] = {}
    for elem in root.findall('.//Parameter'):
        xml_name = elem.attrib.get('parametername') or ''
        base_name = _shader_export_base_name(xml_name)
        encoded = base_name.encode('ascii', errors='ignore')
        if not encoded:
            continue
        candidates = []
        start = 0
        while True:
            pos = shader_data.find(encoded, start)
            if pos < 0:
                break
            end = pos + len(encoded)
            if end + 4 <= len(shader_data):
                param_id = shader_data[end:end + 4]
                record_prefix = b'\x03\x04' + param_id + b'\x01'
                record_pos = shader_data.find(record_prefix)
                if record_pos >= 0:
                    candidates.append((pos, param_id, record_pos))
            start = pos + 1
        if candidates:
            # The compact parameter-name table is late in shaderbin; choose the
            # 同じ可読名が複数存在するときは、末尾に最も近い出現位置を使う。
            name_pos, param_id, record_pos = max(candidates, key=lambda item: item[0])
            resolved[xml_name] = {
                'xml_name': xml_name,
                'base_name': base_name,
                'parameter_id_hex': param_id.hex(),
                'name_table_offset': name_pos,
                'default_record_offset': record_pos,
                'size': int(elem.attrib.get('size', '0') or 0),
                'referenced': str(elem.attrib.get('referenced', '')).casefold() == 'true',
            }
    return resolved


def _decode_shader_default_record(shader_data: bytes, record_offset: int, parameter_size: int) -> dict | None:
    # prefix: 03 04 + param-id(4) + 01 + binding-id(4) + type(1) + guid(16) + value
    pos = int(record_offset)
    if pos < 0 or pos + 28 > len(shader_data) or shader_data[pos:pos + 2] != b'\x03\x04':
        return None
    param_id = shader_data[pos + 2:pos + 6]
    if shader_data[pos + 6] != 0x01:
        return None
    binding_id = shader_data[pos + 7:pos + 11]
    type_code = shader_data[pos + 11]
    guid = shader_data[pos + 12:pos + 28]
    value_pos = pos + 28
    value_size = 16 if int(parameter_size) == 4 else 4
    if value_pos + value_size > len(shader_data):
        return None
    raw = shader_data[value_pos:value_pos + value_size]
    decoded: object
    semantic_type = 'raw'
    if int(parameter_size) == 4 and len(raw) == 16:
        decoded = [round(float(v), 9) for v in struct.unpack('<4f', raw)]
        semantic_type = 'float4'
    elif type_code == 0x03 and len(raw) == 4:
        decoded = bool(struct.unpack('<I', raw)[0])
        semantic_type = 'bool'
    elif len(raw) == 4:
        decoded = round(float(struct.unpack('<f', raw)[0]), 9)
        semantic_type = 'float'
    else:
        decoded = raw.hex()
    return {
        'parameter_id_hex': param_id.hex(),
        'binding_id_hex': binding_id.hex(),
        'type_code': int(type_code),
        'guid_hex': guid.hex(),
        'value_offset': value_pos,
        'value_size': value_size,
        'raw_value_hex': raw.hex(),
        'decoded_type': semantic_type,
        'decoded_value': decoded,
    }


def _decode_material_override(material_data: bytes, parameter_id_hex: str, parameter_size: int) -> dict | None:
    param_id = bytes.fromhex(parameter_id_hex)
    prefix = b'\x03\x04' + param_id + b'\x00'
    pos = material_data.find(prefix)
    if pos < 0:
        return None
    # override: 03 04 + param-id(4) + 00 + type(1) + guid(16) + value
    type_pos = pos + 7
    guid_pos = pos + 8
    value_pos = pos + 24
    if value_pos > len(material_data):
        return None
    type_code = material_data[type_pos]
    guid = material_data[guid_pos:guid_pos + 16]
    value_size = 16 if int(parameter_size) == 4 else 4
    if value_pos + value_size > len(material_data):
        return None
    raw = material_data[value_pos:value_pos + value_size]
    if int(parameter_size) == 4:
        decoded = [round(float(v), 9) for v in struct.unpack('<4f', raw)]
        semantic_type = 'float4'
    elif type_code == 0x03:
        decoded = bool(struct.unpack('<I', raw)[0])
        semantic_type = 'bool'
    else:
        decoded = round(float(struct.unpack('<f', raw)[0]), 9)
        semantic_type = 'float'
    return {
        'record_offset': pos,
        'type_code': int(type_code),
        'guid_hex': guid.hex(),
        'raw_value_hex': raw.hex(),
        'decoded_type': semantic_type,
        'decoded_value': decoded,
    }


def _material_default_binding_diagnostics(
    materials_zip: Path,
    carpaint_shader_zip: Path,
    livery_shader_zip: Path,
) -> dict:
    materials_zip = materials_zip.expanduser().resolve()
    carpaint_shader_zip = carpaint_shader_zip.expanduser().resolve()
    livery_shader_zip = livery_shader_zip.expanduser().resolve()

    car_mat_member, car_mat = _zip_read_suffix_casefold(materials_zip, '_fmnext/carpaint_default/carpaint.materialbin')
    liv_mat_member, liv_mat = _zip_read_suffix_casefold(materials_zip, '_fmnext/carpaint_default/livery_sticker.materialbin')
    car_bin_member, car_bin = _zip_read_suffix_casefold(carpaint_shader_zip, 'car_automotive_paint.shaderbin')
    liv_bin_member, liv_bin = _zip_read_suffix_casefold(livery_shader_zip, 'car_livery.shaderbin')
    car_xml_member, car_root = _shader_xml_from_zip(carpaint_shader_zip, 'car_automotive_paint.shaderbin.xml')
    liv_xml_member, liv_root = _shader_xml_from_zip(livery_shader_zip, 'car_livery.shaderbin.xml')

    def build(shader_data: bytes, root: ET.Element, material_data: bytes) -> dict:
        ids = _shader_parameter_ids(shader_data, root)
        params = []
        for xml_name, meta in ids.items():
            default = _decode_shader_default_record(shader_data, meta['default_record_offset'], meta['size'])
            override = _decode_material_override(material_data, meta['parameter_id_hex'], meta['size'])
            if default is None:
                continue
            params.append({
                **meta,
                'shader_default': default,
                'material_override': override,
                'effective_value_source': 'material_override' if override is not None else 'shader_default',
                'effective_value': (override or default).get('decoded_value'),
            })
        return {'resolved_parameter_count': len(params), 'parameters': params}

    car = build(car_bin, car_root, car_mat)
    liv = build(liv_bin, liv_root, liv_mat)

    def pick(block: dict, names: list[str]) -> dict[str, dict]:
        by_name = {p['xml_name']: p for p in block['parameters']}
        return {name: by_name[name] for name in names if name in by_name}

    car_focus = pick(car, [
        'Roughness_Shift_floatVal',
        'MaskedLiveryBool',
        'UniqueLiverySwitchBool',
        'UserLiverySwitchBool',
        'ClearCoatRoughness_floatVal',
        'ClearCoatCoverage_floatVal',
        'ClearCoatOnLiveryBool',
        'ClearCoatTintColorParam',
        'PaintColorColorParam',
        'FlakeColorColorParam',
    ])
    liv_focus = pick(liv, [
        'Roughness_Shift_floatVal',
        'BaseColorColorParam',
        'BaseColorTextureSwitchBool',
    ])

    car_overrides = [p['xml_name'] for p in car['parameters'] if p.get('material_override') is not None]
    liv_overrides = [p['xml_name'] for p in liv['parameters'] if p.get('material_override') is not None]

    return {
        'format': 'lo4fh6_material_default_binding_diagnostics_v1',
        'sources': {
            'materials_zip': str(materials_zip),
            'carpaint_shader_zip': str(carpaint_shader_zip),
            'livery_shader_zip': str(livery_shader_zip),
            'carpaint_material_member': car_mat_member,
            'livery_material_member': liv_mat_member,
            'carpaint_shader_member': car_bin_member,
            'livery_shader_member': liv_bin_member,
            'carpaint_shader_xml_member': car_xml_member,
            'livery_shader_xml_member': liv_xml_member,
        },
        'carpaint': car,
        'livery': liv,
        'focus': {
            'carpaint': car_focus,
            'livery': liv_focus,
        },
        'material_override_parameters': {
            'carpaint': car_overrides,
            'livery': liv_overrides,
        },
        'evidence': {
            'carpaint_clearcoat_roughness': (car_focus.get('ClearCoatRoughness_floatVal') or {}).get('effective_value'),
            'carpaint_clearcoat_coverage': (car_focus.get('ClearCoatCoverage_floatVal') or {}).get('effective_value'),
            'carpaint_clearcoat_on_livery': (car_focus.get('ClearCoatOnLiveryBool') or {}).get('effective_value'),
            'carpaint_masked_livery': (car_focus.get('MaskedLiveryBool') or {}).get('effective_value'),
            'carpaint_unique_livery_switch': (car_focus.get('UniqueLiverySwitchBool') or {}).get('effective_value'),
            'carpaint_user_livery_switch': (car_focus.get('UserLiverySwitchBool') or {}).get('effective_value'),
            'carpaint_roughness_shift': (car_focus.get('Roughness_Shift_floatVal') or {}).get('effective_value'),
            'livery_roughness_shift': (liv_focus.get('Roughness_Shift_floatVal') or {}).get('effective_value'),
            'carpaint_material_overrides_clearcoat': any('ClearCoat' in name for name in car_overrides),
            'livery_material_override_count': len(liv_overrides),
            'interpretation': (
                'The shaderbin default table can be joined to materialbin overrides by the 32-bit parameter id embedded after each compact '
                'parameter name. For the stock carpaint material, the clear-coat controls are not overridden by materialbin and therefore use '
                'shader defaults. The decoded defaults are ClearCoatRoughness=0.0, ClearCoatCoverage=1.0, and ClearCoatOnLivery=True. '
                'The stock livery_sticker material has no decoded parameter overrides and uses the car_livery shader Roughness_Shift default. '
                'This establishes configured defaults, not the exact runtime branch equation or the final framebuffer response.'
            ),
        },
    }


def _material_library_diagnostics(materials_zip: Path, swatches_zip: Path) -> dict:
    materials_zip = materials_zip.expanduser().resolve()
    swatches_zip = swatches_zip.expanduser().resolve()
    carpaint_member, carpaint_data = _zip_read_suffix_casefold(materials_zip, "_fmnext/carpaint_default/carpaint.materialbin")
    livery_member, livery_data = _zip_read_suffix_casefold(materials_zip, "_fmnext/carpaint_default/livery_sticker.materialbin")
    swatch_member, swatch_data = _zip_read_suffix_casefold(
        swatches_zip, "flat_texture_defaultrmao_paintlivery_074dynv.swatchbin"
    )

    image = decode_fh6_decal_swatch(swatch_data)
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    unique = np.unique(rgba.reshape(-1, 4), axis=0)
    constant_rgba = unique[0].tolist() if len(unique) == 1 else None
    normalized = [round(float(value) / 255.0, 6) for value in constant_rgba] if constant_rgba else None

    carpaint = _material_record_diagnostics(carpaint_member, carpaint_data)
    livery = _material_record_diagnostics(livery_member, livery_data)
    rmao_interpretation = None
    if constant_rgba is not None:
        rmao_interpretation = {
            "basis": (
                "candidate channel semantics inferred from the asset name 'RMAO'; "
                "the swatch decoder proves the stored RGBA values but not the semantic labels"
            ),
            "roughness_candidate_r": normalized[0],
            "metalness_candidate_g": normalized[1],
            "ambient_occlusion_candidate_b": normalized[2],
            "alpha_or_reserved_a": normalized[3],
        }

    different_shaders = (carpaint.get("shader_path") or "").casefold() != (livery.get("shader_path") or "").casefold()
    return {
        "format": "lo4fh6_material_library_diagnostics_v1",
        "materials_zip": str(materials_zip),
        "swatches_zip": str(swatches_zip),
        "materials": {
            "carpaint": carpaint,
            "livery_sticker": livery,
        },
        "paint_livery_rmao": {
            "member": swatch_member,
            "size": len(swatch_data),
            "sha256": hashlib.sha256(swatch_data).hexdigest(),
            "decoded_size": list(image.size),
            "unique_rgba_count": int(len(unique)),
            "constant_rgba": constant_rgba,
            "constant_rgba_normalized": normalized,
            "candidate_channel_interpretation": rmao_interpretation,
        },
        "evidence": {
            "different_shader_paths": different_shaders,
            "carpaint_shader": carpaint.get("shader_path"),
            "livery_shader": livery.get("shader_path"),
            "livery_rmao_is_constant": constant_rgba is not None,
            "livery_rmao_is_dielectric_candidate": bool(constant_rgba is not None and constant_rgba[1] <= 1),
            "livery_rmao_is_high_roughness_candidate": bool(constant_rgba is not None and constant_rgba[0] >= 250),
            "interpretation": (
                "FH6 routes the stock automotive paint and livery sticker through different shaders. "
                "The paint-livery RMAO swatch decodes to a single constant pixel value. If the literal RMAO name maps "
                "R/G/B to roughness/metalness/AO, that default is almost fully rough and non-metallic. This is consistent "
                "with mask-cut negative space exposing the more reflective base-paint path, but the materialbin parameter "
                "hashes are not decoded here, so numeric car-paint clearcoat/roughness values are not claimed."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only FH6 game-facing 3D livery preview. Reads the local FH6 installation, "
            "converts the exact target car to a local GLB cache, and projects decoded C_livery artwork "
            "through FH6 TEXCOORD_3 / Masks.xml semantics in a local Three.js viewer."
        )
    )
    parser.add_argument("source", type=Path, nargs="?", default=None, help="Livery_* folder or C_livery file; omitted with --material-library-audit-only")
    parser.add_argument(
        "--game-folder",
        type=Path,
        required=False,
        default=None,
        help=(
            r'FH6 install or Content folder, e.g. "C:\XboxGames\Forza Horizon 6\Content". '
            "Required for the 3D viewer path; optional with --diagnostics-only."
        ),
    )
    parser.add_argument(
        "--vehicle-asset-zip",
        type=Path,
        default=None,
        help=(
            "optional exact FH6 vehicle ZIP for cross-platform asset/material diagnostics; "
            "works with --diagnostics-only and avoids requiring a full local FH6 installation"
        ),
    )
    parser.add_argument(
        "--vehicle-asset-audit-only",
        action="store_true",
        help=(
            "inspect --vehicle-asset-zip material/projection routing and stop before the heavier C_livery pixel diagnostics; "
            "requires --vehicle-asset-zip"
        ),
    )
    parser.add_argument(
        "--materials-zip",
        type=Path,
        default=None,
        help="optional FH6 shared Materials.zip used by --material-library-audit-only",
    )
    parser.add_argument(
        "--swatches-zip",
        type=Path,
        default=None,
        help="optional FH6 shared swatches.zip used by --material-library-audit-only",
    )
    parser.add_argument(
        "--material-library-audit-only",
        action="store_true",
        help=(
            "compare carpaint.materialbin, livery_sticker.materialbin, and the paint-livery RMAO swatch, then stop; "
            "requires --materials-zip and --swatches-zip"
        ),
    )
    parser.add_argument(
        "--carpaint-shader-zip",
        type=Path,
        default=None,
        help="FH6 car_automotive_paint.zip used by --shader-library-audit-only",
    )
    parser.add_argument(
        "--livery-shader-zip",
        type=Path,
        default=None,
        help="FH6 car_livery.zip used by --shader-library-audit-only",
    )
    parser.add_argument(
        "--shader-library-audit-only",
        action="store_true",
        help=(
            "compare exported car_automotive_paint/car_livery shader XML parameter and texture routing, then stop; "
            "requires --carpaint-shader-zip and --livery-shader-zip"
        ),
    )
    parser.add_argument(
        "--compiled-shader-audit-only",
        action="store_true",
        help=(
            "inspect shipped PCDXIL/DXBC containers and correlate stripped compiled artifacts with exported parameter references; "
            "requires --carpaint-shader-zip and --livery-shader-zip"
        ),
    )
    parser.add_argument(
        "--material-default-binding-audit-only",
        action="store_true",
        help=(
            "join shaderbin parameter defaults to materialbin overrides for carpaint/livery materials, then stop; "
            "requires --materials-zip, --carpaint-shader-zip, and --livery-shader-zip"
        ),
    )
    parser.add_argument(
        "--diagnostics-only",
        action="store_true",
        help=(
            "run C_livery decode/mask/provenance diagnostics only, without converting a car mesh or starting the browser viewer; "
            "this mode is cross-platform and does not require --game-folder unless the livery uses built-in raster decals"
        ),
    )
    parser.add_argument(
        "--private-context-mask-visual-check", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--viewer-fast-path",
        action="store_true",
        help=(
            "skip research-only mask/provenance diagnostic image generation during the interactive 3D Viewer path; "
            "the canonical decoder, paint bindings, mesh conversion, and 3D atlas generation are unchanged"
        ),
    )
    parser.add_argument(
        "--gpu-shadow-policy",
        choices=("gpu-only",),
        default="gpu-only",
        help=(
            "GPU専用ペイント描画（CPUアトラス描画・フォールバック禁止）。C_liveryデコードとMask準備はCPUで実行します"
        ),
    )
    parser.add_argument(
        "--paint-finish-audit-only",
        action="store_true",
        help=(
            "decode the C_livery descriptor table, separate panel-reference records from material paint bindings, "
            "summarize finish/color clusters, then stop before pixel diagnostics or the browser viewer"
        ),
    )
    parser.add_argument(
        "--paint-finish-reference-zip",
        type=Path,
        default=None,
        help=(
            "optional controlled-reference Livery_*.zip used with --paint-finish-audit-only to map a known authored finish "
            "against the target C_livery descriptor table"
        ),
    )
    parser.add_argument(
        "--paint-finish-known-reference",
        action="append",
        default=[],
        metavar="LABEL=ZIP",
        help=(
            "repeatable controlled finish reference used with --paint-finish-audit-only; "
            "format LABEL=path-to-Livery_*.zip (for example Chrome=...zip)"
        ),
    )
    parser.add_argument("--output", "-o", type=Path, default=Path("vehicle-preview-output"))
    parser.add_argument(
        "--vinyl-resource-root",
        type=Path,
        default=None,
        help=(
            "optional local Vinyls geometry root; when omitted with --game-folder, only shapes referenced "
            "by the selected C_livery are decoded transiently from installed Vinyls.zip"
        ),
    )
    parser.add_argument(
        "--vinyl-cache-root",
        type=Path,
        default=None,
        help=(
            "optional compatibility/debug directory for the legacy full 1,400-shape Vinyl cache; "
            "normal Viewer preparation does not create it"
        ),
    )
    parser.add_argument(
        "--vehicle-cache-root",
        type=Path,
        default=None,
        help=(
            "shared cache directory for vehicle index and converted chassis GLBs; "
            "default is <output-parent>/_fh6-vehicle-cache"
        ),
    )
    parser.add_argument(
        "--car-id",
        type=int,
        default=None,
        help=(
            "resolved FH6 vehicle Car ID to use for the 3D mesh/projection. "
            "Use this when Livery Organizer for FH6 resolves a different vehicle ID than the "
            "folder/C_livery embedded identifier (for example --car-id 3960)."
        ),
    )
    parser.add_argument(
        "--body-kit-part-id",
        type=int,
        default=None,
        help=(
            "research-only explicit CarBody PartId. Matching exterior upgrade families with the same PartId "
            "are selected for local chassis conversion; this is not inferred from the player's save state"
        ),
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "optional decrypted local FH6 GameDB SQLite. When supplied, exact CarBody wheel centers and "
            "front/rear tire/rim dimensions replace wheelbase-relative neutral assembly sizing; this does not "
            "resolve the player's save-state wheel or body-kit selection"
        ),
    )
    parser.add_argument(
        "--gamedb-car-body-id",
        type=int,
        default=None,
        help=(
            "research-only explicit GameDB CarBodyID used for exact wheel/tire assembly selection; "
            "independent of Manifest CarBody PartId / --body-kit-part-id"
        ),
    )
    parser.add_argument(
        "--wheel-placement",
        choices=("gamedb", "carbin"),
        default="gamedb",
        help=(
            "research-only WheelStyle/Brakes placement after independent morph: "
            "gamedb aligns exact carbin WheelStyle instances to GameDB wheel centers (default); "
            "carbin preserves the original converted carbin placement for A/B visual verification"
        ),
    )
    parser.add_argument(
        "--wheel-morph-reference-helper",
        type=Path,
        default=None,
        help=(
            "deprecated external EXE oracle input (refused). "
            "The existing first-party WheelStyle morph uses the local GameDB automatically."
        ),
    )
    parser.add_argument(
        "--quality",
        choices=("auto", "1", "2", "3", "4"),
        default="1",
        help="livery texture quality; default 1x. 2x is high, 3x is ultra, 4x is Xbox-reference research quality/slower; auto selects up to 2x by available RAM",
    )
    parser.add_argument(
        "--strict-owned-only",
        action="store_true",
        help="reject downloaded/unowned C_livery records; default allows source-free local comparison previews",
    )
    parser.add_argument("--private-source-facing-proof", type=Path, default=None,
                        help="PRIVATE: SHA照合済み左右UV3+Mask+法線の研究用証拠JSON")
    parser.add_argument("--private-source-facing-contract", type=Path, default=None,
                        help="PRIVATE: 証拠を生成した元local-render-contract.json")
    parser.add_argument("--private-wheel-symbol-png", type=Path, default=None,
        help="PRIVATE比較専用: FH6元Wheel_DIFF/OPAC結合PNG（既定OFF）")
    parser.add_argument("--private-wheel-symbol-proof", type=Path, default=None,
        help="PRIVATE比較専用: ModelBin/GameDB/PNG出典の既存署名JSON")
    parser.add_argument("--private-wheel-material-proof", type=Path, default=None,
        help="PRIVATE比較専用: MaterialBin/ShaderBin/GLB材質の既存署名JSON")
    parser.add_argument("--no-open", action="store_true", help="do not open the local viewer URL automatically")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="build package/mesh/atlas caches but do not start the local web viewer",
    )
    parser.add_argument(
        "--worker-log",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()



SOURCE_SECTION_MAP = {
    "front": "Front",
    "back": "Back",
    "top": "Top",
    "left": "Left",
    "right": "Right",
    "wing": "Spoiler",
    "front_windscreen": "FrontWindshield",
    "rear_windscreen": "BackWindshield",
    "top_window": "TopWindow",
    "left_window": "LeftWindow",
    "right_window": "RightWindow",
}


SECTION_COMPOSITE_SUPERSAMPLE = 2


def _paint_finish_candidate_diagnostics(yrvl_candidate: dict) -> dict:
    records = list(yrvl_candidate.get("records") or [])
    references = list(yrvl_candidate.get("references") or [])
    panel_indices = {
        int(item.get("record_index"))
        for item in references
        if item.get("record_index") is not None
    }

    def record_key(record: dict) -> tuple:
        primary = record.get("primary_color") or {}
        secondary = record.get("secondary_color") or {}
        return (
            int(record.get("finish_code_raw") or 0),
            bool(record.get("primary_color_enabled")),
            str(primary.get("rgba_hex") or "#00000000"),
            bool(record.get("secondary_color_enabled")),
            str(secondary.get("rgba_hex") or "#00000000"),
            str(record.get("manufacturer_color_selector_hex") or "00000000"),
        )

    def build_clusters(selected: list[dict]) -> list[dict]:
        grouped: dict[tuple, list[dict]] = {}
        for record in selected:
            grouped.setdefault(record_key(record), []).append(record)
        result = []
        for key, items in grouped.items():
            finish, p_enabled, p_color, s_enabled, s_color, manufacturer = key
            result.append({
                "count": len(items),
                "record_indices": [int(item.get("index")) for item in items],
                "material_identifiers": [str(item.get("material_identifier_hex") or "") for item in items],
                "finish_code_raw": finish,
                "primary_color_enabled": p_enabled,
                "primary_color_rgba_hex": p_color,
                "secondary_color_enabled": s_enabled,
                "secondary_color_rgba_hex": s_color,
                "manufacturer_color_selector_hex": manufacturer,
            })
        result.sort(key=lambda item: (-int(item["count"]), int(item["finish_code_raw"]), str(item["primary_color_rgba_hex"])))
        return result

    panel_records = [record for record in records if int(record.get("index")) in panel_indices]
    non_panel_records = [record for record in records if int(record.get("index")) not in panel_indices]
    non_panel_clusters = build_clusters(non_panel_records)
    repeated_colored = [
        item for item in non_panel_clusters
        if int(item.get("count") or 0) >= 2
        and bool(item.get("primary_color_enabled"))
        and _valid_explicit_paint_color(item.get("primary_color_rgba_hex"))
    ]
    repeated_special = [
        item for item in repeated_colored
        if int(item.get("finish_code_raw") or 0) != 0
    ]
    repeated_descriptors = [
        item for item in non_panel_clusters
        if int(item.get("count") or 0) >= 2
    ]
    dominant = repeated_special[0] if repeated_special else None
    dominant_colored = repeated_colored[0] if repeated_colored else None
    dominant_descriptor = repeated_descriptors[0] if repeated_descriptors else None

    return {
        "format": "lo4fh6_paint_finish_candidate_diagnostics_v1",
        "record_count": len(records),
        "panel_reference_count": len(references),
        "panel_record_count": len(panel_records),
        "non_panel_record_count": len(non_panel_records),
        "panel_record_indices": sorted(panel_indices),
        "panel_clusters": build_clusters(panel_records),
        "non_panel_clusters": non_panel_clusters,
        "repeated_non_panel_descriptor_clusters": repeated_descriptors,
        "dominant_repeated_non_panel_descriptor_cluster": dominant_descriptor,
        "repeated_non_panel_colored_clusters": repeated_colored,
        "dominant_repeated_non_panel_colored_cluster": dominant_colored,
        "repeated_non_panel_special_finish_clusters": repeated_special,
        "dominant_repeated_non_panel_special_finish_cluster": dominant,
        "evidence": {
            "panel_records_are_finish_zero": bool(panel_records) and all(int(item.get("finish_code_raw") or 0) == 0 for item in panel_records),
            "dominant_colored_cluster_present": dominant_colored is not None,
            "dominant_special_cluster_present": dominant is not None,
            "interpretation": (
                "The descriptor table contains material paint bindings in addition to the 11 panel references. "
                "A repeated non-panel explicit-colour cluster is strong evidence for an authored body-paint treatment shared across multiple car materials, "
                "including normal paint records whose raw finish code is 0. Non-zero repeated finish clusters remain preferred when present. "
                "The numeric finish code is intentionally kept raw: this diagnostic does not name code 16 as Chrome, Metallic, Gloss, or another finish without an independent mapping sample."
            ),
        },
    }


def _paint_finish_reference_comparison(target: dict, reference: dict, reference_label: str = "reference") -> dict:
    target_dom = target.get("dominant_repeated_non_panel_special_finish_cluster") or {}
    ref_dom = reference.get("dominant_repeated_non_panel_special_finish_cluster") or {}
    target_ids = set(target_dom.get("material_identifiers") or [])
    ref_ids = set(ref_dom.get("material_identifiers") or [])
    same_finish = (target_dom.get("finish_code_raw") == ref_dom.get("finish_code_raw"))
    return {
        "format": "lo4fh6_paint_finish_reference_comparison_v1",
        "reference_label": reference_label,
        "target": {
            "finish_code_raw": target_dom.get("finish_code_raw"),
            "primary_color_rgba_hex": target_dom.get("primary_color_rgba_hex"),
            "count": target_dom.get("count", 0),
        },
        "reference": {
            "finish_code_raw": ref_dom.get("finish_code_raw"),
            "primary_color_rgba_hex": ref_dom.get("primary_color_rgba_hex"),
            "count": ref_dom.get("count", 0),
        },
        "same_finish_code": same_finish,
        "shared_material_identifier_count": len(target_ids & ref_ids),
        "target_only_material_identifier_count": len(target_ids - ref_ids),
        "reference_only_material_identifier_count": len(ref_ids - target_ids),
        "shared_material_identifiers": sorted(target_ids & ref_ids),
        "evidence": {
            "controlled_reference_distinguishes_target_finish": bool(target_dom and ref_dom and not same_finish),
            "interpretation": (
                "The controlled reference is an authored known-finish sample. When its dominant raw finish code differs from the target, "
                "the target dominant finish must not be labelled as that known finish solely from visual similarity."
            ),
        },
    }


def _paint_finish_reference_summary(comp: dict) -> str:
    t = comp.get("target") or {}
    r = comp.get("reference") or {}
    lines = [
        "Livery Organizer for FH6 - controlled paint finish reference comparison",
        "",
        f"reference_label={comp.get('reference_label', 'reference')}",
        f"target_finish={t.get('finish_code_raw')} target_color={t.get('primary_color_rgba_hex')} target_count={t.get('count', 0)}",
        f"reference_finish={r.get('finish_code_raw')} reference_color={r.get('primary_color_rgba_hex')} reference_count={r.get('count', 0)}",
        f"same_finish_code={comp.get('same_finish_code')}",
        f"shared_material_identifier_count={comp.get('shared_material_identifier_count', 0)}",
        f"target_only_material_identifier_count={comp.get('target_only_material_identifier_count', 0)}",
        f"reference_only_material_identifier_count={comp.get('reference_only_material_identifier_count', 0)}",
        "",
        "interpretation:",
        (comp.get("evidence") or {}).get("interpretation", ""),
        "",
    ]
    return "\n".join(lines)


def _parse_known_finish_reference(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise ValueError("known finish reference must use LABEL=ZIP syntax")
    label, raw_path = spec.split("=", 1)
    label = label.strip()
    raw_path = raw_path.strip()
    if not label or not raw_path:
        raise ValueError("known finish reference must use non-empty LABEL=ZIP syntax")
    return label, Path(raw_path)


def _paint_finish_reference_matrix(target: dict, known_references: list[tuple[str, dict]]) -> dict:
    target_dom = target.get("dominant_repeated_non_panel_special_finish_cluster") or {}
    target_ids = set(target_dom.get("material_identifiers") or [])
    rows = []
    for label, diag in known_references:
        dom = diag.get("dominant_repeated_non_panel_special_finish_cluster") or {}
        ref_ids = set(dom.get("material_identifiers") or [])
        rows.append({
            "label": label,
            "finish_code_raw": dom.get("finish_code_raw"),
            "primary_color_rgba_hex": dom.get("primary_color_rgba_hex"),
            "count": dom.get("count", 0),
            "same_finish_code_as_target": dom.get("finish_code_raw") == target_dom.get("finish_code_raw"),
            "shared_material_identifier_count": len(target_ids & ref_ids),
        })
    code_to_labels = {}
    for row in rows:
        code_to_labels.setdefault(str(row.get("finish_code_raw")), []).append(row["label"])
    matching = [row["label"] for row in rows if row["same_finish_code_as_target"]]
    return {
        "format": "lo4fh6_paint_finish_reference_matrix_v1",
        "target": {
            "finish_code_raw": target_dom.get("finish_code_raw"),
            "primary_color_rgba_hex": target_dom.get("primary_color_rgba_hex"),
            "count": target_dom.get("count", 0),
        },
        "references": rows,
        "finish_code_to_labels": code_to_labels,
        "matching_known_labels": matching,
        "target_finish_identified": len(matching) > 0,
    }


def _paint_finish_reference_matrix_summary(matrix: dict) -> str:
    lines = [
        "Livery Organizer for FH6 - controlled paint finish reference matrix",
        "",
        f"target_finish={matrix.get('target', {}).get('finish_code_raw')}",
        f"target_color={matrix.get('target', {}).get('primary_color_rgba_hex')}",
        f"target_finish_identified={matrix.get('target_finish_identified')}",
        f"matching_known_labels={matrix.get('matching_known_labels', [])}",
        "",
        "[known references]",
    ]
    for row in matrix.get("references") or []:
        lines.append(
            f"label={row.get('label')} finish={row.get('finish_code_raw')} color={row.get('primary_color_rgba_hex')} "
            f"count={row.get('count')} same_as_target={row.get('same_finish_code_as_target')} "
            f"shared_materials={row.get('shared_material_identifier_count')}"
        )
    lines += [
        "",
        "interpretation:",
        "Only controlled samples should assign UI finish names to raw finish codes. Visual similarity alone is not treated as a mapping.",
        "",
    ]
    return "\n".join(lines)


def _paint_finish_diagnostics_from_livery_zip(path: Path) -> dict:
    path = path.expanduser().resolve()
    with zipfile.ZipFile(path) as zf:
        candidates = [n for n in zf.namelist() if n.replace('\\', '/').endswith('/C_livery') or n == 'C_livery']
        if len(candidates) != 1:
            raise FullLiveryPackageError(
                f"Expected exactly one C_livery in controlled-reference ZIP, found {len(candidates)}: {path}"
            )
        payload = zf.read(candidates[0])
    with tempfile.TemporaryDirectory(prefix="lo4fh6-finish-reference-") as td:
        tmp = Path(td) / "C_livery"
        tmp.write_bytes(payload)
        yrvl = parse_livery_yrvl_diagnostics(tmp)
    return _paint_finish_candidate_diagnostics(yrvl.get("candidate_material_yrvl") or {})


def _paint_finish_candidate_summary(diagnostics: dict) -> str:
    lines = [
        "Livery Organizer for FH6 - paint finish candidate audit",
        "",
        f"record_count={diagnostics.get('record_count', 0)}",
        f"panel_record_count={diagnostics.get('panel_record_count', 0)}",
        f"non_panel_record_count={diagnostics.get('non_panel_record_count', 0)}",
        f"panel_record_indices={diagnostics.get('panel_record_indices', [])}",
        "",
        "[panel clusters]",
    ]
    for item in diagnostics.get("panel_clusters") or []:
        lines.append(
            f"count={item.get('count')} finish={item.get('finish_code_raw')} "
            f"primary={item.get('primary_color_rgba_hex')} enabled={item.get('primary_color_enabled')} "
            f"indices={item.get('record_indices')}"
        )
    lines += ["", "[non-panel material paint clusters]"]
    for item in diagnostics.get("non_panel_clusters") or []:
        lines.append(
            f"count={item.get('count')} finish={item.get('finish_code_raw')} "
            f"primary={item.get('primary_color_rgba_hex')} enabled={item.get('primary_color_enabled')} "
            f"secondary={item.get('secondary_color_rgba_hex')} indices={item.get('record_indices')}"
        )
    dominant_colored = diagnostics.get("dominant_repeated_non_panel_colored_cluster")
    lines += ["", "[dominant repeated explicit-colour candidate]"]
    lines.append(json.dumps(dominant_colored, ensure_ascii=False, sort_keys=True) if dominant_colored else "none")
    dominant = diagnostics.get("dominant_repeated_non_panel_special_finish_cluster")
    lines += ["", "[dominant repeated special-finish candidate]"]
    lines.append(json.dumps(dominant, ensure_ascii=False, sort_keys=True) if dominant else "none")
    lines += ["", "interpretation:", str((diagnostics.get("evidence") or {}).get("interpretation") or "")]
    return "\n".join(lines) + "\n"


def _paint_layer_counts_fast(shapes: list) -> tuple | None:
    """_paint_layer_diagnostics の面ごとの数を、色・図形番号・覆いの出どころごとにまとめて数える（2026-11-20）。

    以前は図形 1 つずつに、色の変換・度数の更新・明るさ・色の文字列づくりをしていた（1 件 約 30〜40 ms）。数は
    色ごと・番号ごとの数で決まるので、collections.Counter でまとめ、明るさと文字列は違う色ごとに 1 回求める。
    解読の部品が作る形の図形（辞書・色が int 4 つの一覧・type_word_hex が空でない文字列・mask_source が空でない
    文字列）だけの面に使い、ほかの形が 1 つでもあれば None（今までの数え方に任せる。例外もそのまま）。
    """
    from collections import Counter
    if any(type(shape) is not dict for shape in shapes):
        return None
    colors = [shape.get("color") for shape in shapes]
    if any(type(color) is not list or len(color) != 4 for color in colors):
        return None
    if any(type(value) is not int for color in colors for value in color):
        return None
    words = [shape.get("type_word_hex") for shape in shapes]
    sources = [shape.get("mask_source") for shape in shapes]
    if any(type(word) is not str or not word for word in words):
        return None
    if any(type(source) is not str or not source for source in sources):
        return None
    alpha_hist: dict[str, int] = {}
    color_hist: dict[str, int] = {}
    opaque = semi = transparent = near_white_opaque = 0
    dark = mid = light = 0
    for (r, g, b, a), count in Counter(map(tuple, colors)).items():
        key = str(a)
        alpha_hist[key] = alpha_hist.get(key, 0) + count
        if a <= 0:
            transparent += count
        elif a >= 255:
            opaque += count
        else:
            semi += count
        if a >= 250 and min(r, g, b) >= 224:
            near_white_opaque += count
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        if luma < 64:
            dark += count
        elif luma < 192:
            mid += count
        else:
            light += count
        rgba = f"#{r:02x}{g:02x}{b:02x}{a:02x}"
        color_hist[rgba] = color_hist.get(rgba, 0) + count
    return (alpha_hist, dict(Counter(sources)), dict(Counter(words)), color_hist,
            opaque, semi, transparent, near_white_opaque, dark, mid, light)


def _paint_layer_diagnostics(design: dict) -> dict:
    surfaces = {}
    for surface in design.get("surfaces", []):
        name = str(surface.get("name") or "")
        shapes = list(surface.get("shapes") or [])
        alpha_hist: dict[str, int] = {}
        mask_sources: dict[str, int] = {}
        type_hist: dict[str, int] = {}
        color_hist: dict[str, int] = {}
        opaque = semi = transparent = near_white_opaque = 0
        dark = mid = light = 0
        fast = _paint_layer_counts_fast(shapes)
        if fast is not None:
            (alpha_hist, mask_sources, type_hist, color_hist,
             opaque, semi, transparent, near_white_opaque, dark, mid, light) = fast
            shapes_to_count = []
        else:
            shapes_to_count = shapes
        for shape in shapes_to_count:
            color = [int(v) for v in list(shape.get("color") or [255, 255, 255, 255])[:4]]
            while len(color) < 4:
                color.append(255)
            r, g, b, a = color
            alpha_hist[str(a)] = alpha_hist.get(str(a), 0) + 1
            if a <= 0:
                transparent += 1
            elif a >= 255:
                opaque += 1
            else:
                semi += 1
            if a >= 250 and min(r, g, b) >= 224:
                near_white_opaque += 1
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luma < 64:
                dark += 1
            elif luma < 192:
                mid += 1
            else:
                light += 1
            source = str(shape.get("mask_source") or "none")
            mask_sources[source] = mask_sources.get(source, 0) + 1
            type_word = str(shape.get("type_word_hex") or f"0x{int(shape.get('type_word') or 0):04x}")
            type_hist[type_word] = type_hist.get(type_word, 0) + 1
            rgba = f"#{r:02x}{g:02x}{b:02x}{a:02x}"
            color_hist[rgba] = color_hist.get(rgba, 0) + 1

        top_colors = sorted(color_hist.items(), key=lambda item: (-item[1], item[0]))[:16]
        top_types = sorted(type_hist.items(), key=lambda item: (-item[1], item[0]))[:16]
        surfaces[name] = {
            "source_section": surface.get("source_section"),
            "shape_count": len(shapes),
            "alpha": {
                "opaque_255": opaque,
                "semtransparent_1_254": semi,
                "transparent_0": transparent,
                "histogram": dict(sorted(alpha_hist.items(), key=lambda item: int(item[0]))),
            },
            "luminance_buckets": {"dark_lt64": dark, "mid_64_191": mid, "light_ge192": light},
            "near_white_opaque_count": near_white_opaque,
            "mask_source_histogram": dict(sorted(mask_sources.items())),
            "top_colors_rgba": [{"rgba": rgba, "count": count} for rgba, count in top_colors],
            "top_shape_words": [{"type_word_hex": word, "count": count} for word, count in top_types],
        }
    return {
        "format": "lo4fh6_paint_layer_diagnostics_v1",
        "scope": "canonical placement records; no per-placement finish field is decoded",
        "shape_count": int(design.get("shape_count") or 0),
        "surfaces": surfaces,
    }


def _redirect_worker_stdio(path: Path | None) -> None:
    """
    pythonw Workerの標準出力を明示的なUTF-8ログへ転送する。
    """
    global _WORKER_LOG_HANDLE
    if path is None:
        return
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("w", encoding="utf-8", errors="replace", buffering=1)
    _WORKER_LOG_HANDLE = handle
    sys.stdout = handle
    sys.stderr = handle


def _serialize_timing_value(value):
    """
    構造化Telemetryを維持しつつ、Timingの数値を丸める。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return {key: _serialize_timing_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_timing_value(item) for item in value]
    return value


def main() -> int:
    # 準備の間、同じ ZIP（車両・材質・テクスチャ・シェーダー）を開き直さずに使い回す。
    # 読むだけの ZIP なので結果は変わらず、目次の読み直し（1 台で約 40 回）を省く（2026-11-18）。
    from tools.livery.material_runtime import shared_archive_reads
    with shared_archive_reads():
        return _main()


def _main() -> int:
    configure_console_text_streams()
    args = parse_args()
    _redirect_worker_stdio(args.worker_log)
    if args.private_context_mask_visual_check and not (
        args.viewer_fast_path and args.prepare_only and args.no_open
    ):
        raise ValueError("GroupMask研究デコーダーは3D Viewer準備専用CLI経由のみ許可")
    if args.compiled_shader_audit_only and (args.carpaint_shader_zip is None or args.livery_shader_zip is None):
        print("--compiled-shader-audit-only requires --carpaint-shader-zip and --livery-shader-zip.", file=sys.stderr)
        return 2
    if args.compiled_shader_audit_only:
        output = args.output.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        diagnostics = _compiled_shader_diagnostics(args.carpaint_shader_zip, args.livery_shader_zip)
        diagnostics_path = output / "compiled-shader-diagnostics.json"
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ev = diagnostics.get("evidence") or {}
        refs = diagnostics.get("focus_parameter_referenced_flags") or {}
        summary = [
            "Livery Organizer for FH6 - compiled shader audit",
            "",
            f"carpaint_compiled_artifact_count={ev.get('carpaint_compiled_artifact_count')}",
            f"livery_compiled_artifact_count={ev.get('livery_compiled_artifact_count')}",
            f"focus_names_stripped_from_compiled_artifacts={ev.get('focus_names_stripped_from_compiled_artifacts')}",
            f"carpaint_clearcoat_on_livery_export_referenced={ev.get('carpaint_clearcoat_on_livery_export_referenced')}",
            f"carpaint_roughness_shift_export_referenced={ev.get('carpaint_roughness_shift_export_referenced')}",
            f"livery_roughness_shift_export_referenced={ev.get('livery_roughness_shift_export_referenced')}",
            f"carpaint_focus_references={refs.get('carpaint')}",
            f"livery_focus_references={refs.get('livery')}",
            "",
            "interpretation:",
            str(ev.get("interpretation") or ""),
        ]
        summary_path = output / "compiled-shader-audit.txt"
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"compiled shader diagnostics: {diagnostics_path}")
        print(f"compiled shader summary: {summary_path}")
        print("COMPILED SHADER AUDIT PASS — browser viewer and C_livery were not required.")
        return 0
    if args.material_default_binding_audit_only and (
        args.materials_zip is None or args.carpaint_shader_zip is None or args.livery_shader_zip is None
    ):
        print(
            "--material-default-binding-audit-only requires --materials-zip, --carpaint-shader-zip, and --livery-shader-zip.",
            file=sys.stderr,
        )
        return 2
    if args.material_default_binding_audit_only:
        output = args.output.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        diagnostics = _material_default_binding_diagnostics(
            args.materials_zip,
            args.carpaint_shader_zip,
            args.livery_shader_zip,
        )
        diagnostics_path = output / "material-default-binding-diagnostics.json"
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ev = diagnostics.get("evidence") or {}
        overrides = diagnostics.get("material_override_parameters") or {}
        summary = [
            "Livery Organizer for FH6 - material default binding audit",
            "",
            f"carpaint_clearcoat_roughness={ev.get('carpaint_clearcoat_roughness')}",
            f"carpaint_clearcoat_coverage={ev.get('carpaint_clearcoat_coverage')}",
            f"carpaint_clearcoat_on_livery={ev.get('carpaint_clearcoat_on_livery')}",
            f"carpaint_masked_livery={ev.get('carpaint_masked_livery')}",
            f"carpaint_unique_livery_switch={ev.get('carpaint_unique_livery_switch')}",
            f"carpaint_user_livery_switch={ev.get('carpaint_user_livery_switch')}",
            f"carpaint_roughness_shift={ev.get('carpaint_roughness_shift')}",
            f"livery_roughness_shift={ev.get('livery_roughness_shift')}",
            f"carpaint_material_overrides={overrides.get('carpaint')}",
            f"livery_material_overrides={overrides.get('livery')}",
            "",
            "interpretation:",
            str(ev.get("interpretation") or ""),
        ]
        summary_path = output / "material-default-binding-audit.txt"
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"material default binding diagnostics: {diagnostics_path}")
        print(f"material default binding summary: {summary_path}")
        print("MATERIAL DEFAULT BINDING AUDIT PASS — C_livery, vehicle mesh, and browser viewer were not required.")
        return 0
    if args.shader_library_audit_only and (args.carpaint_shader_zip is None or args.livery_shader_zip is None):
        print("--shader-library-audit-only requires --carpaint-shader-zip and --livery-shader-zip.", file=sys.stderr)
        return 2
    if args.shader_library_audit_only:
        output = args.output.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        diagnostics = _shader_library_diagnostics(args.carpaint_shader_zip, args.livery_shader_zip)
        diagnostics_path = output / "shader-library-diagnostics.json"
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ev = diagnostics.get("evidence") or {}
        summary = [
            "Livery Organizer for FH6 - FH6 shader library audit",
            "",
            f"carpaint_clearcoat_parameters={ev.get('carpaint_clearcoat_parameters')}",
            f"carpaint_livery_switch_parameters={ev.get('carpaint_livery_switch_parameters')}",
            f"livery_shader_clearcoat_parameters={ev.get('livery_shader_clearcoat_parameters')}",
            f"carpaint_has_clearcoat_on_livery={ev.get('carpaint_has_clearcoat_on_livery')}",
            f"carpaint_has_masked_livery={ev.get('carpaint_has_masked_livery')}",
            f"carpaint_has_user_livery_switch={ev.get('carpaint_has_user_livery_switch')}",
            f"both_use_rough_metal_ao_texture={ev.get('both_use_rough_metal_ao_texture')}",
            "",
            "interpretation:",
            str(ev.get("interpretation") or ""),
        ]
        summary_path = output / "shader-library-audit.txt"
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"shader library diagnostics: {diagnostics_path}")
        print(f"shader library summary: {summary_path}")
        print("SHADER LIBRARY AUDIT PASS — C_livery, vehicle mesh, and browser viewer were not required.")
        return 0
    if args.material_library_audit_only and (args.materials_zip is None or args.swatches_zip is None):
        print("--material-library-audit-only requires --materials-zip and --swatches-zip.", file=sys.stderr)
        return 2
    if args.material_library_audit_only:
        output = args.output.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        diagnostics = _material_library_diagnostics(args.materials_zip, args.swatches_zip)
        diagnostics_path = output / "material-library-diagnostics.json"
        diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence = diagnostics.get("evidence") or {}
        rmao = diagnostics.get("paint_livery_rmao") or {}
        summary = [
            "Livery Organizer for FH6 - FH6 material library audit",
            "",
            f"carpaint_shader={evidence.get('carpaint_shader')}",
            f"livery_shader={evidence.get('livery_shader')}",
            f"different_shader_paths={evidence.get('different_shader_paths')}",
            f"paint_livery_rmao_constant_rgba={rmao.get('constant_rgba')}",
            f"paint_livery_rmao_normalized={rmao.get('constant_rgba_normalized')}",
            f"high_roughness_candidate={evidence.get('livery_rmao_is_high_roughness_candidate')}",
            f"dielectric_candidate={evidence.get('livery_rmao_is_dielectric_candidate')}",
            "",
            "interpretation:",
            str(evidence.get("interpretation") or ""),
        ]
        summary_path = output / "material-library-audit.txt"
        summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"material library diagnostics: {diagnostics_path}")
        print(f"material library summary: {summary_path}")
        print("MATERIAL LIBRARY AUDIT PASS — C_livery and browser viewer were not required.")
        return 0
    if args.wheel_morph_reference_helper is not None:
        print(
            "External WheelStyle morph EXE is not permitted in the product Viewer. "
            "Omit --wheel-morph-reference-helper to use the existing independent WheelStyle morph.",
            file=sys.stderr,
        )
        return 2
    if args.source is None:
        print("source is required unless an audit-only mode is used.", file=sys.stderr)
        return 2
    if args.vehicle_asset_audit_only and args.vehicle_asset_zip is None:
        print("--vehicle-asset-audit-only requires --vehicle-asset-zip.", file=sys.stderr)
        return 2
    if args.vehicle_asset_audit_only:
        args.diagnostics_only = True
    if args.paint_finish_audit_only:
        args.diagnostics_only = True
    # 2026-11-10: 車両GLB生成は独自Python Carbin/ModelBin変換器へ接続済み。
    # 以前の参照製品 Windows x64 EXE前提のOS一律拒否を解除する。
    # FH6原本とGPUランタイムの欠落は各既存検証ゲートで明示エラーにする。
    # Windows GUI・Organizer実機受入と、Linux上の3D描画受入は別に記録する。
    if not args.diagnostics_only and args.game_folder is None:
        print("--game-folder is required unless --diagnostics-only is used.", file=sys.stderr)
        return 2

    source = resolve_c_livery(args.source)
    game_folder = (
        args.game_folder.expanduser().resolve()
        if args.game_folder is not None
        else (Path.cwd() / "__lo4fh6_no_game_assets__").resolve()
    )
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    vinyl_resource_source = ""
    vinyl_resource_root: Path | None = None
    transient_vinyl_resource_root: Path | None = None
    selected_vinyl_resource_summary: dict[str, object] = {}
    if args.vinyl_resource_root is not None:
        configure_vinyl_resource_root(args.vinyl_resource_root)
        vinyl_resource_root = default_vinyl_resource_root().expanduser().resolve()
        vinyl_resource_source = "explicit_local_resource_root"
    elif args.game_folder is not None and args.vinyl_cache_root is not None:
        # 旧1400種Vinyl全体Cacheを使う明示的な互換・診断要求。
        vinyl_cache_root = args.vinyl_cache_root.expanduser().resolve()
        configure_vinyl_resource_root(ensure_local_vinyl_geometry(game_folder, vinyl_cache_root))
        vinyl_resource_root = default_vinyl_resource_root().expanduser().resolve()
        vinyl_resource_source = "explicit_full_local_fh6_cache"
    elif args.game_folder is not None:
        # r373：正規C_livery復号で参照図形が確定するまで通常の素材準備を遅延する。
        configure_vinyl_resource_root(None)
        vinyl_resource_source = "selected_installed_vinyls_zip_transient"
    else:
        raise FullLiveryPackageError(
            "Vinyl geometry is not bundled. Supply --game-folder so referenced shapes can be "
            "reconstructed from local FH6 Vinyls.zip, or pass --vinyl-resource-root explicitly."
        )
    if vinyl_resource_root is not None and not vinyl_resource_root.is_dir():
        raise FullLiveryPackageError(f"Vinyl geometry root does not exist: {vinyl_resource_root}")
    cache = output / "cache"
    cache.mkdir(exist_ok=True)
    vehicle_cache_root = (
        args.vehicle_cache_root.expanduser().resolve()
        if args.vehicle_cache_root is not None
        else (output.parent / "_fh6-vehicle-cache").resolve()
    )
    vehicle_cache_root.mkdir(parents=True, exist_ok=True)
    preview_path = output / "source.lo4preview"
    vehicle_index_cache = vehicle_cache_root / "vehicle-index.json"

    timings: dict[str, float] = {}
    total_started = time.perf_counter()

    print("Livery Organizer for FH6 — game-facing 3D preview research")
    print(f"source: {source}")
    if args.game_folder is None:
        print("game:   (not supplied; local FH6 raster/vehicle assets unavailable)")
    else:
        print(f"game:   {game_folder}")
    print(f"output: {output}")
    if vinyl_resource_root is not None:
        print(f"vinyl:  {vinyl_resource_root} ({vinyl_resource_source})")
    else:
        print("vinyl:  selected shapes will be decoded transiently from installed Vinyls.zip")
    if args.diagnostics_only:
        print("mode:   DIAGNOSTICS ONLY / READ ONLY")
    else:
        print("mode:   READ ONLY (FH6 game/save files are never modified)")

    source_c_livery_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    payload_for_identity = unwrap_forza_container(source)
    if len(payload_for_identity) < 0x14 or payload_for_identity[:4] != b"vlrc":
        raise FullLiveryPackageError("The selected file is not an FH6 C_livery container.")
    embedded_car_id = int(struct.unpack_from("<I", payload_for_identity, 0x10)[0])
    folder_id = source_folder_id(source)
    car_id, car_id_source = choose_target_car_id(
        embedded_car_id=embedded_car_id, override_car_id=args.car_id
    )

    vehicle_asset_diagnostics = None
    vehicle_asset_diagnostics_path = None
    if args.vehicle_asset_zip is not None:
        vehicle_asset_diagnostics = _vehicle_asset_zip_diagnostics(args.vehicle_asset_zip, expected_car_id=car_id)
        vehicle_asset_diagnostics_path = output / "vehicle-asset-material-diagnostics.json"
        vehicle_asset_diagnostics_path.write_text(
            json.dumps(vehicle_asset_diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        evidence = vehicle_asset_diagnostics.get("material_evidence") or {}
        print(
            "vehicle asset: "
            f"model={((vehicle_asset_diagnostics.get('archive') or {}).get('model_code') or args.vehicle_asset_zip.stem)} "
            f"separate-base-livery-materials={evidence.get('separate_base_and_livery_material_paths', False)}"
        )
        if args.vehicle_asset_audit_only:
            audit_summary = {
                "format": "lo4fh6_vehicle_asset_audit_summary_v1",
                "source": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "resolved_car_id": car_id,
                "resolved_car_id_source": car_id_source,
                "vehicle_asset_zip": str(args.vehicle_asset_zip.expanduser().resolve()),
                "vehicle_asset_material_diagnostics": str(vehicle_asset_diagnostics_path),
                "material_evidence": evidence,
                "followup_external_game_assets": vehicle_asset_diagnostics.get("followup_external_game_assets") or [],
            }
            audit_summary_path = output / "vehicle-asset-audit-summary.json"
            audit_summary_path.write_text(
                json.dumps(audit_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"asset audit summary: {audit_summary_path}")
            print("ASSET AUDIT PASS — heavy C_livery pixel diagnostics and browser viewer were skipped.")
            return 0

    yrvl_diagnostics = _load_yrvl_diagnostics_for_preview(
        source, viewer_fast_path=bool(args.viewer_fast_path and not args.diagnostics_only)
    )
    yrvl_diagnostics_path = output / "yrvl-material-diagnostics.json"
    yrvl_diagnostics_path.write_text(
        json.dumps(yrvl_diagnostics, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    yrvl_candidate = yrvl_diagnostics.get("candidate_material_yrvl") or {}
    if yrvl_diagnostics.get("status") == "unsupported_variant_fallback":
        print(
            "WARNING: yrvl material metadata uses an unsupported tail variant; "
            "interactive Viewer will continue without material/panel paint bindings: "
            f"{yrvl_diagnostics.get('warning', 'unknown yrvl parse error')}"
        )
        try:
            variant_probe, variant_tail = probe_livery_yrvl_variant(source)
            variant_probe_path = output / "yrvl-variant-diagnostics.json"
            variant_tail_path = output / "yrvl-variant-tail.bin"
            variant_probe_path.write_text(
                json.dumps(variant_probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            variant_tail_path.write_bytes(variant_tail)
            yrvl_diagnostics["variant_probe"] = {
                "diagnostics": str(variant_probe_path),
                "raw_tail": str(variant_tail_path),
                "raw_tail_sha256": variant_probe["variant_tail"]["sha256"],
                "raw_tail_length": variant_probe["variant_tail"]["length"],
            }
            yrvl_diagnostics_path.write_text(
                json.dumps(yrvl_diagnostics, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"yrvl variant probe: {variant_probe_path}")
            print(f"yrvl variant tail:  {variant_tail_path}")
        except Exception as probe_exc:
            print(f"WARNING: yrvl variant probe could not be exported: {probe_exc}")
    else:
        print(
            "yrvl:   "
            f"records={yrvl_candidate.get('record_count', 0)} "
            f"references={yrvl_candidate.get('reference_count', 0)} "
            f"finish-codes={','.join((yrvl_candidate.get('finish_code_histogram') or {}).keys()) or 'none'}"
        )

    paint_finish_diagnostics = _paint_finish_candidate_diagnostics(yrvl_candidate)
    paint_finish_diagnostics_path = output / "paint-finish-candidate-diagnostics.json"
    paint_finish_diagnostics_path.write_text(
        json.dumps(paint_finish_diagnostics, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    paint_finish_summary_path = output / "paint-finish-candidate-audit.txt"
    paint_finish_summary_path.write_text(_paint_finish_candidate_summary(paint_finish_diagnostics), encoding="utf-8")
    dominant_finish = paint_finish_diagnostics.get("dominant_repeated_non_panel_special_finish_cluster") or {}
    base_paint_cluster, base_paint_cluster_source = _base_paint_cluster_from_diagnostics(paint_finish_diagnostics)
    print(
        "paint:  "
        f"panel={paint_finish_diagnostics.get('panel_record_count', 0)} "
        f"non-panel={paint_finish_diagnostics.get('non_panel_record_count', 0)} "
        f"dominant-finish={dominant_finish.get('finish_code_raw', 'none')} "
        f"dominant-color={dominant_finish.get('primary_color_rgba_hex', 'none')} "
        f"dominant-count={dominant_finish.get('count', 0)}"
    )
    if args.paint_finish_audit_only:
        print(f"paint finish diagnostics: {paint_finish_diagnostics_path}")
        print(f"paint finish summary: {paint_finish_summary_path}")
        if args.paint_finish_reference_zip is not None:
            reference_diag = _paint_finish_diagnostics_from_livery_zip(args.paint_finish_reference_zip)
            comparison = _paint_finish_reference_comparison(
                paint_finish_diagnostics, reference_diag, reference_label=args.paint_finish_reference_zip.name
            )
            comparison_json = output / "paint-finish-reference-comparison.json"
            comparison_txt = output / "paint-finish-reference-comparison.txt"
            comparison_json.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            comparison_txt.write_text(_paint_finish_reference_summary(comparison), encoding="utf-8")
            ref = comparison.get("reference") or {}
            print(
                "finish reference: "
                f"target={comparison.get('target', {}).get('finish_code_raw')} "
                f"reference={ref.get('finish_code_raw')} "
                f"same={comparison.get('same_finish_code')} "
                f"shared-materials={comparison.get('shared_material_identifier_count', 0)}"
            )
            print(f"paint finish reference comparison: {comparison_txt}")
        if args.paint_finish_known_reference:
            known = []
            for spec in args.paint_finish_known_reference:
                label, ref_path = _parse_known_finish_reference(spec)
                known.append((label, _paint_finish_diagnostics_from_livery_zip(ref_path)))
            matrix = _paint_finish_reference_matrix(paint_finish_diagnostics, known)
            matrix_json = output / "paint-finish-reference-matrix.json"
            matrix_txt = output / "paint-finish-reference-matrix.txt"
            matrix_json.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            matrix_txt.write_text(_paint_finish_reference_matrix_summary(matrix), encoding="utf-8")
            print(
                "finish matrix: "
                f"references={len(matrix.get('references') or [])} "
                f"identified={matrix.get('target_finish_identified')} "
                f"matches={','.join(matrix.get('matching_known_labels') or []) or 'none'}"
            )
            print(f"paint finish reference matrix: {matrix_txt}")
        print("PAINT FINISH AUDIT PASS — pixel diagnostics and browser viewer were skipped.")
        return 0

    phase = time.perf_counter()
    _retire_disk_canonical_designs(output.parent / "_fh6-livery-cache")
    canonical_design, integrated_privacy, canonical_design_cache = _load_or_build_canonical_design_with_privacy(
        source, output.parent / "_fh6-livery-cache", source_c_livery_sha256, embedded_car_id,
        private_context_mask_visual_check=args.private_context_mask_visual_check,
    )
    if args.private_context_mask_visual_check:
        print("MASK_SOURCE_STANDARD_PREPARE=LEGACY_CLI_ALIAS_USES_SAME_PRODUCT_DECODER")
    timings["canonical_design_cache_lookup_seconds"] = float(canonical_design_cache["lookup_seconds"])
    timings["canonical_design_decode_seconds"] = float(canonical_design_cache["decode_seconds"])
    timings["canonical_structural_parse_seconds"] = float(
        canonical_design_cache.get("privacy_structural_parse_seconds") or 0.0
    )

    if not args.strict_owned_only and integrated_privacy is not None:
        clivery_privacy = dict(integrated_privacy)
        privacy_from_cache = bool(canonical_design_cache.get("privacy_from_cache"))
        privacy_integrated = bool(canonical_design_cache.get("privacy_integrated"))
        privacy_cache = {
            "scope": "process-memory-by-c-livery-content",
            "cache_hit": privacy_from_cache,
            "scan_skipped": privacy_from_cache,
            "lookup_seconds": 0.0,
            "scan_seconds": float(canonical_design_cache.get("privacy_candidate_scan_seconds") or 0.0),
            "scan_mode": "canonical-decode-integrated" if privacy_integrated else "canonical-manifest-cache",
            "shared_structural_parse": privacy_integrated,
        }
    else:
        clivery_privacy, privacy_cache = _load_or_build_clivery_privacy(
            payload_for_identity, output.parent / "_fh6-livery-cache", source_c_livery_sha256,
            allow_cache=not args.strict_owned_only,
        )
        privacy_cache["scan_mode"] = "independent-strict" if args.strict_owned_only else "independent-fallback"
        privacy_cache["shared_structural_parse"] = False

    timings["clivery_privacy_cache_lookup_seconds"] = float(privacy_cache["lookup_seconds"])
    timings["clivery_privacy_scan_seconds"] = float(privacy_cache["scan_seconds"])
    timings["clivery_privacy_scan_mode"] = str(privacy_cache.get("scan_mode") or "")
    timings["clivery_privacy_shared_structural_parse"] = bool(privacy_cache.get("shared_structural_parse"))
    selected_vinyl_runtime_prepared = vinyl_resource_root is not None
    selected_vinyl_runtime_lock = threading.Lock()

    def ensure_selected_vinyl_resources() -> None:
        nonlocal vinyl_resource_root, transient_vinyl_resource_root, selected_vinyl_resource_summary
        nonlocal selected_vinyl_runtime_prepared
        if selected_vinyl_runtime_prepared:
            return
        with selected_vinyl_runtime_lock:
            if selected_vinyl_runtime_prepared:
                return
            selected_root = output / "cache" / "selected-vinyl-runtime-r376"
            if selected_root.exists():
                import shutil as _shutil
                _shutil.rmtree(selected_root)
            phase_vinyl = time.perf_counter()
            vinyl_resource_root, selected_vinyl_resource_summary = extract_selected_vinyl_geometry_for_design(
                game_folder, selected_root, canonical_design
            )
            transient_vinyl_resource_root = selected_root
            configure_vinyl_resource_root(vinyl_resource_root)
            timings["selected_vinyl_extract_seconds"] = time.perf_counter() - phase_vinyl
            selected_vinyl_runtime_prepared = True
            print(
                "vinyl:  selected installed resources "
                f"{selected_vinyl_resource_summary.get('selected_resource_count', 0)} "
                f"({vinyl_resource_source})"
            )

    # GPU専用：正規レコードから後でWebGL2 Vector Streamを構築する。
    # Pillow描画、面PNG、Package Monkey Patchは使用しない。
    fast_renderer_info = {
        "renderer": "webgl2-only",
        "section_count": sum(bool(row.get("shapes")) for row in canonical_design.get("surfaces") or []),
        "source": "original-c-livery-canonical-records",
    }
    raster_placement_count = sum(
        1
        for surface in (canonical_design.get("surfaces") or [])
        for shape in (surface.get("shapes") or [])
        if shape_is_raster(shape)
    )
    if args.diagnostics_only and args.game_folder is None and raster_placement_count:
        print(
            f"WARNING: {raster_placement_count} built-in raster-logo placement(s) are present, but --game-folder was not supplied; "
            "raster-dependent diagnostic pixels may be incomplete.",
            file=sys.stderr,
        )
    paint_layer_diagnostics = _paint_layer_diagnostics(canonical_design)
    paint_layer_diagnostics_path = output / "paint-layer-diagnostics.json"
    paint_layer_diagnostics_path.write_text(
        json.dumps(paint_layer_diagnostics, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    timings["viewer_core_decode_seconds"] = time.perf_counter() - phase
    # CPUによるMask／由来比較画像生成は削除済み。
    # 図形数とMaterialメタデータはラスタライズなしで保持する。
    negative_space_diagnostics_path = None
    pixel_provenance_diagnostics_path = None
    mask_owner_summary_path = None
    side_consistency_path = None
    side_matching_path = None
    paired_reconstruction_path = None
    final_reconstruction_path = None
    glyph_alignment_path = None
    glyph_cluster_path = None
    glyph_full_affine_path = None
    glyph_intrinsic_path = None
    timings["diagnostics_seconds"] = 0.0
    if args.diagnostics_only:
        summary = {
            "format": "lo4fh6_gpu_only_metadata_diagnostics_v1",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "resolved_car_id": car_id,
            "shape_count": int(canonical_design.get("shape_count") or 0),
            "cpu_paint_removed": True,
            "gpu_rendered": False,
            "note": "Metadata-only; GPU rendering requires the 3D Viewer.",
        }
        (output / "diagnostics-only-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return 0

    vehicle_asset_started = time.perf_counter()
    index = load_or_build_vehicle_asset_index(game_folder, vehicle_index_cache)
    asset = index.get(car_id)
    if asset is None:
        raise FullLiveryPackageError(f"The local FH6 installation has no car archive for resolved target ID {car_id}.")
    timings["vehicle_asset_lookup_seconds"] = time.perf_counter() - vehicle_asset_started

    phase = time.perf_counter()
    manifest = create_local_livery_preview(
        source,
        preview_path,
        game_folder=None,
        model_code_override=asset.model_code,
        target_car_id_override=car_id,
        _allow_unowned_private_preview=not args.strict_owned_only,
        render_sections=False,
        predecoded_surface_design=canonical_design,
        predecoded_privacy=clivery_privacy,
    )
    validate_livery_inspection_artifact(preview_path)
    timings["private_preview_seconds"] = time.perf_counter() - phase
    vehicle_setup_started = time.perf_counter()

    print(
        "source ids: "
        f"folder_id={folder_id if folder_id is not None else 'unknown'} "
        f"c_livery_embedded_id={embedded_car_id or 'unknown'}"
    )
    print(f"3D target: car_id={car_id} source={car_id_source}")
    if args.car_id is None:
        print(
            "WARNING: no resolved --car-id was supplied. The C_livery embedded ID is being used only "
            "as a legacy research fallback. If Livery Organizer for FH6 reports a different Car ID, "
            "rerun with --car-id <resolved-id> before judging 3D placement."
        )
    elif embedded_car_id and car_id != embedded_car_id:
        print(
            "NOTE: resolved 3D target differs from the C_livery embedded ID; "
            "the explicit --car-id value controls mesh/mask/projection selection."
        )

    preview_target_car_id = int((manifest.get("livery") or {}).get("target_car_id") or 0)
    if preview_target_car_id != car_id:
        raise FullLiveryPackageError(
            f"Private preview target ID {preview_target_car_id} disagrees with resolved 3D target ID {car_id}."
        )

    print(f"vehicle: car_id={car_id} model={asset.model_code}")
    print(f"archive: {asset.archive_path}")

    body_kit_part_id = int(args.body_kit_part_id) if args.body_kit_part_id is not None else None
    body_kit_part_ids = list_body_kit_part_ids(asset)
    body_kit_baseline_part_id = body_kit_part_ids[0] if body_kit_part_ids else None
    if body_kit_part_id is not None and body_kit_part_id not in body_kit_part_ids:
        available = ", ".join(str(value) for value in body_kit_part_ids) or "(none)"
        raise FullLiveryPackageError(
            f"The local vehicle Manifest has no CarBody PartId {body_kit_part_id}; available: {available}."
        )
    active_body_kit_part_id = body_kit_part_id if body_kit_part_id is not None else body_kit_baseline_part_id

    gamedb_path = Path(args.database).resolve() if args.database is not None else None
    exact_assembly_variants: dict[str, dict] = {}
    gamedb_stat = None
    if gamedb_path is not None:
        try:
            exact_assembly_variants = gamedb_assembly_variants(gamedb_path, car_id)
        except Fh6GameDbError as exc:
            raise FullLiveryPackageError(f"Unable to read --database wheel/tire truth: {exc}") from exc
        gamedb_stat = gamedb_path.stat()
        ids = ", ".join(sorted(exact_assembly_variants, key=int))
        print(f"GameDB assembly: exact local wheel/tire dimensions available for CarBodyID {ids}")

    requested_gamedb_car_body_id = (
        int(args.gamedb_car_body_id) if args.gamedb_car_body_id is not None else None
    )
    selected_gamedb_car_body_id: int | None = None
    if exact_assembly_variants:
        if requested_gamedb_car_body_id is not None:
            if str(requested_gamedb_car_body_id) not in exact_assembly_variants:
                available = ", ".join(sorted(exact_assembly_variants, key=int)) or "(none)"
                raise FullLiveryPackageError(
                    f"GameDB has no CarBodyID {requested_gamedb_car_body_id}; available: {available}. "
                    "GameDB CarBodyID is independent of Manifest CarBody PartId."
                )
            selected_gamedb_car_body_id = requested_gamedb_car_body_id
        elif active_body_kit_part_id is not None and str(active_body_kit_part_id) in exact_assembly_variants:
            # 一部の車種は異なるNamespaceで同じ数値IDを使う。
            # 正確なGameDB行が存在する場合だけ従来互換経路を維持する。
            selected_gamedb_car_body_id = int(active_body_kit_part_id)
        else:
            selected_gamedb_car_body_id = int(next(iter(exact_assembly_variants)))
        print(f"GameDB assembly selected: CarBodyID {selected_gamedb_car_body_id}")

    wheel_morph_internal: dict | None = None
    wheel_morph_internal_cache_key = ""
    if gamedb_path is not None and exact_assembly_variants:
        internal_body_id = int(selected_gamedb_car_body_id)
        internal_assembly = exact_assembly_variants[str(internal_body_id)]
        try:
            internal_inputs = wheel_morph_internal_inputs(internal_assembly)
        except WheelMorphInternalError as exc:
            raise FullLiveryPackageError(f"Unable to prepare independent WheelStyle morph: {exc}") from exc
        wheel_morph_internal_cache_key = wheel_morph_internal_cache_identity(
            car_body_id=internal_body_id,
            database_size=int(gamedb_stat.st_size),
            database_mtime_ns=int(gamedb_stat.st_mtime_ns),
            morph_inputs=internal_inputs,
            wheel_centers=dict(internal_assembly.get("wheel_centers") or {}),
            wheel_placement=str(args.wheel_placement),
        )
        wheel_morph_internal = {
            "format": "lo4fh6_internal_wheel_morph_v1",
            "car_body_id": internal_body_id,
            "morph_inputs": internal_inputs,
            "cache_identity": wheel_morph_internal_cache_key,
            "wheel_placement": str(args.wheel_placement),
            "production_dependency": False,
            "external_helper_required": False,
        }
        print(
            "WheelStyle morph independent path: "
            f"Body {internal_body_id} / cache {wheel_morph_internal_cache_key}"
        )

    # 過去の比較用参照製品 helperはGit履歴にのみ保持。
    # 通常Viewerは既存の独自WheelStyle Morphだけを標準接続する。
    body_kit_overlay_plan = (
        resolve_body_kit_overlay_plan(asset, active_body_kit_part_id)
        if active_body_kit_part_id is not None
        else None
    )
    part_selection = dict((body_kit_overlay_plan or {}).get("part_selection") or {})
    if part_selection:
        selection_text = ", ".join(f"{family}={part_id}" for family, part_id in sorted(part_selection.items()))
        print(f"body-kit: initial manifest selection / {selection_text}")
        print("body-kit: baseline carbin scene + selected-only loose geometry overlay (experimental)")
        print(
            f"body-kit delta: +{len((body_kit_overlay_plan or {}).get('added_entries') or [])} "
            f"/ -{len((body_kit_overlay_plan or {}).get('removed_entries') or [])} model entries"
        )
        print("body-kit: player save-state selection is NOT resolved by this research option")

    # FH6原本の実バイトSHAと独自Converter版をキャッシュ名へ固定。
    # 旧参照製品作成v12キャッシュはそのまま保護し、自動流用・上書きしない。
    firstparty_original_sha256 = sha256_file(Path(asset.archive_path))
    firstparty_cache_id = firstparty_original_sha256
    mesh_dir = vehicle_cache_root / "meshes"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    # 同梱ConverterのCarbin経路は再現可能なStock／既定Upgradeだけを構成する。
    # BodyKit研究にも同じ変換安全なSceneを使い、選択部品だけの幾何は別のLoose Entry経路で準備する。
    if wheel_morph_internal is not None:
        mesh_path = mesh_dir / (
            f"{asset.model_code}-{asset.archive_mtime_ns}-{firstparty_cache_id}.local-chassis-v{LOCAL_CHASSIS_FORMAT_REVISION}"
            f"-wheelmorph-internal-{wheel_morph_internal_cache_key}.glb"
        )
        wheel_morph_sidecar = mesh_path.with_suffix(mesh_path.suffix + ".wheel-morph-internal.json")
    else:
        mesh_path = mesh_dir / (
            f"{asset.model_code}-{asset.archive_mtime_ns}-{firstparty_cache_id}.local-chassis-v{LOCAL_CHASSIS_FORMAT_REVISION}.glb"
        )
        wheel_morph_sidecar = None
    # 最近使っていない車の車体の GLB は、消して、消した印だけを残している（tools/livery/chassis_store.py。2026-11-21）。
    # 以前の版の圧縮した写しがあれば元の場所・元の更新日時で戻してから使い、最後に使った印を付ける。
    # 無ければ下で作り直し、中身が消す前と同じなら更新日時を戻す（adopt_evicted_identity）。
    from tools.livery import chassis_store
    chassis_store.prepare_for_use(mesh_path)
    mesh_cache_hit = mesh_path.is_file()
    mesh_preparation_profile = {
        "converter_input_selection_seconds": 0.0,
        "converter_process_seconds": 0.0,
        "converter_validation_seconds": 0.0,
        "conversion_call_seconds": 0.0,
        "wheel_morph_seconds": 0.0,
        "final_validation_seconds": 0.0,
        "cache_validation_seconds": 0.0,
        "validated_glb_reused": False,
        "morph_input_validation_reused": False,
        "morph_final_validation_reused": False,
    }
    timings["vehicle_setup_seconds"] = time.perf_counter() - vehicle_setup_started
    phase = time.perf_counter()
    try:
        cache_validation_started = time.perf_counter()
        mesh_validation = validate_local_chassis_glb(
            mesh_path, require_product_accepted=True,
            required_firstparty_scope="ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE"
        ) if mesh_cache_hit else None
        if mesh_cache_hit:
            mesh_preparation_profile["cache_validation_seconds"] = round(time.perf_counter() - cache_validation_started, 6)
    except (OSError, PortableMeshConverterError):
        mesh_cache_hit = False
        mesh_path.unlink(missing_ok=True)
        mesh_validation = None
    if mesh_cache_hit and wheel_morph_internal is not None:
        try:
            sidecar = json.loads(wheel_morph_sidecar.read_text(encoding="utf-8")) if wheel_morph_sidecar and wheel_morph_sidecar.is_file() else {}
            if sidecar.get("cache_identity") != wheel_morph_internal_cache_key:
                raise ValueError("internal wheel morph cache identity mismatch")
            report = dict(sidecar.get("morph_report") or {})
            if (
                str(report.get("wheel_morph_mode") or "").casefold() != "combined"
                or str(report.get("wheel_morph_source") or "").casefold() != "independent-local-modelbin"
                or int(report.get("wheel_morph_applied_meshes") or 0) <= 0
                or int(report.get("wheel_morph_applied_vertices") or 0) <= 0
            ):
                raise ValueError("internal wheel morph evidence missing")
            wheel_morph_internal["morph_report"] = report
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            mesh_cache_hit = False
            mesh_path.unlink(missing_ok=True)
            if wheel_morph_sidecar:
                wheel_morph_sidecar.unlink(missing_ok=True)
            mesh_validation = None

    if not mesh_cache_hit:
        converter_diagnostics: dict = {}
        if wheel_morph_internal is not None:
            print("mesh: converting exact local FH6 chassis for independent WheelStyle morph...")
            conversion_started = time.perf_counter()
            convert_vehicle_model_to_glb(asset, mesh_path, diagnostics=converter_diagnostics)
            mesh_preparation_profile["conversion_call_seconds"] = round(time.perf_counter() - conversion_started, 6)
            morph_started = time.perf_counter()
            morph_final_validation: dict = {}
            morph_validation_status: dict = {}
            try:
                report = apply_wheelstyle_morph_to_glb(
                    asset,
                    mesh_path,
                    assembly=exact_assembly_variants[str(wheel_morph_internal["car_body_id"])],
                    car_body_id=int(wheel_morph_internal["car_body_id"]),
                    wheel_placement=str(wheel_morph_internal.get("wheel_placement") or "gamedb"),
                    _converter_validation=converter_diagnostics,
                    _final_validation_out=morph_final_validation,
                    _validation_reuse_status_out=morph_validation_status,
                )
            except WheelMorphInternalError as exc:
                mesh_path.unlink(missing_ok=True)
                raise FullLiveryPackageError(f"Independent WheelStyle morph failed closed: {exc}") from exc
            mesh_preparation_profile["wheel_morph_seconds"] = round(time.perf_counter() - morph_started, 6)
            mesh_preparation_profile["morph_input_validation_reused"] = bool(
                morph_validation_status.get("input_validation_reused")
            )
            wheel_morph_internal["morph_report"] = report
            if wheel_morph_sidecar:
                wheel_morph_sidecar.write_text(
                    json.dumps(
                        {
                            "format": "lo4fh6_internal_wheel_morph_cache_v1",
                            "cache_identity": wheel_morph_internal_cache_key,
                            "morph_report": report,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
            placement_text = ""
            if report.get("wheel_gamedb_placement_applied"):
                placement_text = (
                    f" / GameDB placement {report.get('wheel_gamedb_placement_wheels', 0)} wheels"
                    f" / {report.get('wheel_gamedb_placement_meshes', 0)} meshes"
                    f" / max shift {float(report.get('wheel_gamedb_placement_max_distance_m') or 0.0):.3f} m"
                )
            elif report.get("wheel_gamedb_placement_guard_fallback"):
                placement_text = (
                    " / GameDB placement guarded -> carbin"
                    f" / max shift {float(report.get('wheel_gamedb_placement_max_distance_m') or 0.0):.3f} m"
                    f" > {float(report.get('wheel_gamedb_placement_guard_threshold_m') or 0.0):.3f} m"
                )
            elif str(report.get("wheel_placement") or "").casefold() == "carbin":
                placement_text = " / carbin placement preserved"
            print(
                "mesh: independent WheelStyle morph applied / "
                f"{report['wheel_morph_applied_meshes']} meshes / "
                f"{report['wheel_morph_applied_vertices']} vertices / "
                f"transparent static-pass hidden {report.get('wheel_render_pass_filtered_meshes', 0)} meshes"
                f" / dense face hidden {report.get('wheel_face_occluder_filtered_meshes', 0)} meshes"
                f"{' / morph wheel identity reassigned' if report.get('wheel_morph_identity_assignment_changed') else ''}"
                f"{placement_text}"
            )
        else:
            print("mesh: converting exact local FH6 baseline chassis (first run may take time)...")
            conversion_started = time.perf_counter()
            convert_vehicle_model_to_glb(asset, mesh_path, diagnostics=converter_diagnostics)
            mesh_preparation_profile["conversion_call_seconds"] = round(time.perf_counter() - conversion_started, 6)
            # 表示しないメッシュは描かないので除く（ホイールの位置合わせをするときは、その書き出しの前に除く）。
            from tools.livery.glb_compact import drop_hidden_meshes_in_file
            hidden_compact = drop_hidden_meshes_in_file(mesh_path)
            mesh_preparation_profile["hidden_meshes_removed"] = int(hidden_compact["removed_meshes"])
        for profile_key, source_key in (
            ("converter_input_selection_seconds", "input_selection_seconds"),
            ("converter_process_seconds", "converter_process_seconds"),
            ("converter_validation_seconds", "glb_validation_seconds"),
        ):
            mesh_preparation_profile[profile_key] = float(converter_diagnostics.get(source_key) or 0.0)
        final_validation_started = time.perf_counter()
        if wheel_morph_internal is not None and morph_final_validation:
            # Morph段階では変更後GLBを既に厳密検証している。
            # この同期呼出しと一致するメモリ上の検証結果だけを再利用する。
            mesh_validation, validation_reused = reuse_converter_validation(
                mesh_path, {"validated_glb": morph_final_validation},
            )
            mesh_preparation_profile["morph_final_validation_reused"] = validation_reused
        else:
            mesh_validation, validation_reused = reuse_converter_validation(
                mesh_path, converter_diagnostics,
                modified_after_conversion=(wheel_morph_internal is not None
                                           or bool(mesh_preparation_profile.get("hidden_meshes_removed"))),
            )
        mesh_preparation_profile["validated_glb_reused"] = validation_reused and wheel_morph_internal is None
        if not validation_reused:
            mesh_preparation_profile["final_validation_seconds"] = round(time.perf_counter() - final_validation_started, 6)
        # 使っていない間に消した車体の GLB を作り直したときは、大きさと SHA-256 が消す前と同じなら更新日時を戻す。
        # 場所・大きさ・更新日時で決まる他のキャッシュ（部品の色付けの解析・タイヤの GLB など）がそのまま使える
        # （tools/livery/chassis_store.py。2026-11-21、FH6 に近づける案 ④）。
        mesh_preparation_profile["evicted_identity_restored"] = chassis_store.adopt_evicted_identity(mesh_path)
    else:
        if wheel_morph_internal is not None:
            print("mesh: independent WheelStyle morph cache hit")
        else:
            print("mesh: baseline cache hit")

    # r209：ManifestのCarBody候補を一度に準備し、ViewerのUIだけでBodyKitを切り替えられるようにする。
    # Livery Packageの再生成や別Bridgeを要求せず、各記録は手動Manifest研究状態として扱う。
    # 2026-11-21：変換するのは、表示する部品（active_body_kit_part_id）だけ。ほかの部品は、変換済みならそのまま使い、
    # 無ければ変換を後回しにする（overlay_deferred。変換に要る計画と保存先を残し、Viewer で選ばれたときにサーバーが
    # 同じ処理で変換する）。以前は全部を変換していて、部品の多い車で 1〜3 秒かかっていた。
    from tools.livery.body_kit_overlay_mesh import cached_body_kit_overlay, convert_body_kit_overlay
    body_kit_variants: list[dict] = []
    for variant_part_id in body_kit_part_ids:
        plan = resolve_body_kit_overlay_plan(asset, variant_part_id)
        added_entries = list(plan.get("added_entries") or [])
        overlay_mesh: Path | None = None
        overlay_validation: dict | None = None
        overlay_cache_hit = False
        overlay_deferred = False
        if added_entries:
            overlay_mesh = mesh_dir / (
                f"{asset.model_code}-{asset.archive_mtime_ns}-{firstparty_cache_id}-bodykit-{variant_part_id}.overlay-firstparty-v{BODY_KIT_OVERLAY_FORMAT_REVISION}.glb"
            )
            overlay_validation = cached_body_kit_overlay(overlay_mesh)
            overlay_cache_hit = overlay_validation is not None
            if not overlay_cache_hit and variant_part_id == active_body_kit_part_id:
                print(f"body-kit catalog: converting PartId {variant_part_id} / {len(added_entries)} selected-only local model(s)...")
                overlay_validation = convert_body_kit_overlay(asset, overlay_mesh, added_entries)
            elif not overlay_cache_hit:
                overlay_deferred = True
            if overlay_cache_hit:
                print(f"body-kit catalog: PartId {variant_part_id} overlay cache hit")
            elif overlay_deferred:
                print(f"body-kit catalog: PartId {variant_part_id} deferred until selected in the Viewer")
        lowered_added = [entry.casefold() for entry in added_entries]
        if variant_part_id == body_kit_baseline_part_id:
            variant_hint = "stock"
        elif any("wide" in entry for entry in lowered_added):
            variant_hint = "wide"
        elif any("custom" in entry for entry in lowered_added):
            variant_hint = "custom"
        else:
            variant_hint = "variant"
        body_kit_variants.append(
            {
                **plan,
                "variant_hint": variant_hint,
                "overlay_mesh": str(overlay_mesh) if overlay_mesh and not overlay_deferred else "",
                "overlay_cache_hit": overlay_cache_hit,
                "overlay_validation": overlay_validation,
                # 後回しにした部品の保存先（Viewer で選ばれたときに、サーバーがここへ変換する）
                "overlay_deferred": overlay_deferred,
                "overlay_mesh_planned": str(overlay_mesh) if overlay_deferred else "",
            }
        )
    if len(body_kit_variants) > 1:
        print(
            "body-kit catalog: "
            + ", ".join(f"{item['body_kit_part_id']}:{item['variant_hint']}" for item in body_kit_variants)
        )

    active_variant = next(
        (item for item in body_kit_variants if int(item.get("body_kit_part_id") or -1) == int(active_body_kit_part_id or -1)),
        None,
    )
    body_kit_overlay_mesh = Path(active_variant["overlay_mesh"]).resolve() if active_variant and active_variant.get("overlay_mesh") else None
    body_kit_overlay_validation = active_variant.get("overlay_validation") if active_variant else None
    body_kit_overlay_cache_hit = bool(active_variant.get("overlay_cache_hit")) if active_variant else False
    timings["mesh_seconds"] = time.perf_counter() - phase
    # 今の車と最近の数台のほか、しばらく使っていない車の車体の GLB を、裏の糸で消して消した印だけにする。
    chassis_store.schedule_maintenance(mesh_dir, keep=mesh_path)

    available_ram = psutil.virtual_memory().available
    if args.quality == "auto":
        quality_scale = 2 if available_ram >= 2 * 1024**3 else 1
    else:
        quality_scale = int(args.quality)
    if quality_scale == 4 and available_ram < 10 * 1024**3:
        print("quality: falling back to 3x because less than 10 GiB RAM is available for Xbox-reference atlas rendering")
        quality_scale = 3
    if quality_scale == 3 and available_ram < 6 * 1024**3:
        print("quality: falling back to 2x because less than 6 GiB RAM is available for reference atlas rendering")
        quality_scale = 2
    if quality_scale == 2 and available_ram < 2 * 1024**3:
        print("quality: falling back to 1x because less than 2 GiB RAM is available")
        quality_scale = 1
    print(f"quality: {quality_scale}x")

    # 画質2／3／4はFlat Previewと同じ正規Decoder・合成意味論を維持する。
    # 旧Type Code別描画器では複雑なLiveryのTransform／Layer合成が変わっていた。

    render_key = f"car{car_id}-{preview_path.stat().st_size}-{asset.archive_mtime_ns}-r{RENDER_CONTRACT_REVISION}-q{quality_scale}"
    render_root = cache / "renders" / render_key
    phase = time.perf_counter()
    atlas_contract_started = time.perf_counter()
    # 11面のMask／projection数値のみCPUでデコードする。
    # ペイントの画素生成・CPUアトラス・CPU再生成処理は存在しない。
    contract = build_local_livery_atlases(
        preview_path, asset, render_root,
        mesh_path=mesh_path, mesh_validation=mesh_validation,
        quality_scale=quality_scale,
        shared_mask_cache_root=vehicle_cache_root / "projection-masks",
        cpu_shadow_policy="gpu-only",
    )
    timings["atlas_contract_seconds"] = time.perf_counter() - atlas_contract_started
    timings["gpu_only_paint_contract"] = True
    if vinyl_resource_source == "selected_installed_vinyls_zip_transient" and not selected_vinyl_runtime_prepared:
        timings.setdefault("selected_vinyl_extract_seconds", 0.0)
        selected_vinyl_resource_summary = {
            "selected_resource_count": 0,
            "extraction_skipped": True,
            "reason": (
                "shared-paint-atlas-cache-hit"
                if bool((contract.get("paint_cache") or {}).get("cache_hit"))
                else "cpu-section-render-not-required"
            ),
        }
    if exact_assembly_variants:
        contract["assembly_variants"] = exact_assembly_variants
        selected_assembly = exact_assembly_variants[str(selected_gamedb_car_body_id)]
        # GameDBの車輪中心へのホイールの移動が安全上限（wheel_morph_internal）で取りやめになり、
        # ホイールがcarbinの位置に残った場合は、Tire・Viewerも実際のホイールと同じ車軸を使う。
        # GameDBの値は gamedb_wheel_centers に残す（例：BMW_Isetta_62はGameDBの車高0.26mでは
        # carbinより車輪中心が約0.16m下になり、ホイールがアーチの下に出るため上限で止まる）。
        placement_report = (wheel_morph_internal or {}).get("morph_report") or {}
        carbin_centers = placement_report.get("wheel_gamedb_placement_guard_carbin_centers")
        wheel_roles = ("front_left", "front_right", "rear_left", "rear_right")

        def _valid_center(value) -> bool:
            return (isinstance(value, list) and len(value) == 3
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value))

        same_body = bool(wheel_morph_internal
                         and int(wheel_morph_internal.get("car_body_id") or -1) == int(selected_gamedb_car_body_id))
        # 3 輪の車（角が 3 つ）は、ある角だけを書き換える（無い角は GameDB の値のまま、タイヤの段階は使わない）。
        present_roles = tuple(role for role in wheel_roles
                              if isinstance(carbin_centers, dict) and role in carbin_centers)
        if (placement_report.get("wheel_gamedb_placement_guard_fallback") is True
                and same_body and len(present_roles) >= 3
                and all(_valid_center(carbin_centers.get(role)) for role in present_roles)):
            selected_assembly = {
                **selected_assembly,
                "gamedb_wheel_centers": selected_assembly.get("wheel_centers"),
                "wheel_centers": {**(selected_assembly.get("wheel_centers") or {}),
                                  **{role: [float(v) for v in carbin_centers[role]] for role in present_roles}},
                "wheel_centers_source": "carbin-wheelstyle-after-gamedb-placement-guard",
            }
        # 3 輪・6 輪の車で GameDB の配置の前後（Z）を Carbin のまま保ったときは、配置した中心を使う。
        applied_centers = placement_report.get("wheel_gamedb_placement_centers_fh6")
        if (placement_report.get("wheel_gamedb_placement_applied") is True
                and placement_report.get("wheel_gamedb_placement_carbin_z_kept") is True
                and same_body and isinstance(applied_centers, dict)
                and all(_valid_center(value) for value in applied_centers.values())):
            selected_assembly = {
                **selected_assembly,
                "gamedb_wheel_centers": selected_assembly.get("wheel_centers"),
                "wheel_centers": {**(selected_assembly.get("wheel_centers") or {}),
                                  **{role: [float(v) for v in value] for role, value in applied_centers.items()}},
                "wheel_centers_source": "gamedb-xy-carbin-z-non-four-wheel",
            }
        contract["assembly"] = selected_assembly
        contract["assembly_truth"] = {
            "source": "local-fh6-gamedb",
            "database": str(gamedb_path),
            "database_size": gamedb_stat.st_size if gamedb_stat else None,
            "database_mtime_ns": gamedb_stat.st_mtime_ns if gamedb_stat else None,
            "save_state_resolved": False,
            "wheelstyle_morph_applied": bool(wheel_morph_internal),
            "wheelstyle_morph_source": "independent-local-modelbin" if wheel_morph_internal else "",
            "wheelstyle_morph_car_body_id": (
                int(wheel_morph_internal["car_body_id"]) if wheel_morph_internal else None
            ),
            "wheelstyle_morph_reference": None,
            "wheelstyle_morph_internal": wheel_morph_internal,
        }
    # 図柄後のDescriptor Tableから取得する診断専用Paint／Panel Binding。
    # Finishの数値コードと名前の対応が独立検証されるまで原本値を保つ。
    contract["paint_bindings"] = yrvl_candidate.get("references", [])
    contract["wheel_paint_colors"] = _wheel_paint_contract_with_materials(
        yrvl_candidate, game_folder=game_folder, asset=asset,
    )
    contract["paint_layer_diagnostics"] = paint_layer_diagnostics.get("surfaces", {})
    # 元Carbin素材hash→C_livery Yrvlの車種共通関係は標準準備で常時監査。
    # 現行lo4fh6_*と歴史参照製品由来lo4_*の原本値を確認し、未割当と不一致を分離。
    # Shader計算式未確定のため、監査結果を描画入力へ自動転用せず診断だけ出力。
    # 研究モード/URL/環境変数を追加せず、描画は単一の既受入入口を保持。
    if (yrvl_diagnostics.get("format") == "lo4fh6_yrvl_research_v1"
            and int(yrvl_candidate.get("record_count") or 0) > 0):
        from tools.livery.independent_chassis.source_paint_mesh_descriptor_stage import (
            OriginalPaintMeshBindingError,
            apply_finish_display_colors,
            audit_source_mesh_finish_bindings_for_file,
            resolve_manufacturer_carpaint_groups,
        )
        try:
            finish_catalog = _load_embedded_livery_material_catalog()
            # 同じ GLB のファイルの事実（目次・SHA）は同じプロセスで覚えて使い回す（2026-11-20）
            finish_source_proof = audit_source_mesh_finish_bindings_for_file(
                mesh_path, yrvl_diagnostics, finish_catalog,
            )
            # メーカー指定色の記録に結び付いた塗装部品は車種の工場出荷色で補い、カーボン・色の入力の
            # 無い仕上げの部品には描画用の色を付ける（_source_paint_binding_palette_color・_display_color）。
            if asset is not None:
                finish_source_proof = resolve_manufacturer_carpaint_groups(
                    finish_source_proof, lambda selector: _source_paint_binding_palette_color(asset, selector))
                if game_folder is not None:
                    display_cache: dict = {}
                    finish_source_proof = apply_finish_display_colors(
                        finish_source_proof,
                        lambda code: _source_paint_binding_display_color(
                            finish_catalog, code, game_folder=game_folder, asset=asset, cache=display_cache))
        except (OriginalPaintMeshBindingError, OSError, ValueError) as exc:
            # 署名矛盾は研究契約へ昇格させず診断だけ残す。通常3Dの
            # 確認済みLivery/UV3/Wheel/Tireを巻き戻さない。
            contract["source_paint_binding_diagnostics_unavailable"] = str(exc)
        else:
            # 全体が未確定でも部分一致・元Hash=0・未対応件数を正確に残す。
            # 一致した一部分を完成Shaderとして利用しない。
            contract["source_paint_binding_diagnostics"] = finish_source_proof
            if finish_source_proof.get("carpaint_binding_complete_for_research") is not True:
                unresolved = finish_source_proof["counts"].get(
                    "carpaint_mesh_unresolved_for_research", 0)
                contract["source_paint_binding_diagnostics_unavailable"] = (
                    f"元carPaint全MeshとC_livery材質IDの対応が未確定（未対応{unresolved}件）。"
                    "全原本IDとShader根拠が揃うまで自動材質変更は行いません"
                )
    base_paint_started = time.perf_counter()
    base_paint_descriptor, base_paint_descriptor_source = _renderer_base_paint_descriptor_from_diagnostics(
        paint_finish_diagnostics
    )
    base_paint_selection, base_paint_material = _resolve_renderer_base_paint(
        base_paint_descriptor,
        descriptor_source=base_paint_descriptor_source,
        asset=asset,
        game_folder=game_folder,
    )
    contract["base_paint_selection"] = base_paint_selection
    contract["base_paint_color_rgba_hex"] = (
        base_paint_selection.get("primary_color_rgba_hex")
        if base_paint_selection.get("color_available")
        else None
    )
    contract["base_paint_material"] = base_paint_material
    # 純正の模様の板を見せるか（層の無いデザインで、記録がメーカー指定のときだけ。2026-11-22）。
    contract["factory_livery_stickers"] = _factory_livery_sticker_contract(yrvl_diagnostics)
    # ミラーのカバー・キャリパーは、ペイントの Mirror・Brakes の記録の色で描く（記録が無い車は従来どおり）。
    if asset is not None:
        contract["named_paint_groups"] = _named_paint_groups_contract(
            paint_finish_diagnostics, asset=asset, game_folder=game_folder,
        )
    # 原本ManufacturerColors Mirror slot0の署名済み色契約を通常入口へ渡す。
    # ミラーへの適用はWebGL側で元ModelBin/MatI/UV3を照合した場合のみ。
    # OEM factory候補とC_livery最終選択・Xbox Shader同値を区別する。
    # 適合原本がない車種ではこの時点で他部品のPrepareを止めず、
    # 実際に署名ミラーカバーの色が必要ならViewerで明示エラーとする。
    if asset is not None:
        from tools.livery.source_accessory_oem_preview import (
            OriginalAccessoryPaletteError,
            source_original_mirror_preview,
        )
        try:
            contract["original_accessory_research"] = source_original_mirror_preview(asset)
        except OriginalAccessoryPaletteError as exc:
            contract["original_accessory_research"] = {
                "schema": "lo4fh6.source-original-accessory-mirror-oem-preview.v1",
                "source_color_available": False,
                "unavailable_reason": str(exc),
                "selected_game_color_approved": False,
                "game_shader_rgb_equivalent": False,
                "xbox_approved": False,
            }
    base_material = contract.get("base_paint_material", {})
    base_material_name = str(base_material.get("material_name") or "").casefold()
    if base_material_name == "aluminumbrushed":
        detail_result = extract_swatch_preview_from_zip(
            game_folder / "media" / "cars" / "_library" / "Textures.zip",
            "roughness/swatches/dtl_brushed_001_nrml_e3dfa281-81b4-4c87-a031-c17e72d551dd.swatchbin",
            render_root / "base-detail-normal.png",
        )
        base_material["detail_normal"] = {
            **{k: v for k, v in detail_result.items() if k != "output"},
            "local_render_endpoint": "api/local-render/base-detail-normal" if detail_result.get("available") else None,
        }
    elif str(base_material.get("shader_family") or "").casefold() in {"car_carbonfiber", "car_carbonfiber_user"}:
        candidate = dict(base_material.get("viewer_candidate") or {})
        runtime = dict(base_material.get("runtime_material") or {})
        normal_assets = [
            dict(row) for row in (runtime.get("material_texture_assets") or [])
            if isinstance(row, dict) and row.get("available") and row.get("role_candidate") == "normal_candidate"
        ]
        # r184：ファイル名で明示されたNormal SwatchとShaderのU／V Tilingから診断Normalを準備できる。
        # 製品で有効化するにはUVChoiceの独立証拠が必須で、それまではUV0／UV1をProbeとして扱う。
        if (
            len(normal_assets) == 1
            and "detail_normal_u_tiling" in candidate
            and "detail_normal_v_tiling" in candidate
        ):
            detail_result = extract_material_texture_preview(
                normal_assets[0], render_root / "base-detail-normal.png"
            )
            normal_binding = texture_binding_evidence(
                runtime, str(normal_assets[0].get("reference") or "")
            )
            detail_common = {
                **{k: v for k, v in detail_result.items() if k != "output"},
                "u_tiling": candidate.get("detail_normal_u_tiling"),
                "v_tiling": candidate.get("detail_normal_v_tiling"),
                "scope": "exposed_base_paint_only",
                "local_render_endpoint": "api/local-render/base-detail-normal" if detail_result.get("available") else None,
                "shader_texture_binding": normal_binding,
            }
            if "detail_normal_three_uv_channel" in candidate:
                base_material["detail_normal"] = {
                    **detail_common,
                    "production_enabled": True,
                    "three_uv_channel": candidate.get("detail_normal_three_uv_channel"),
                    "uv_choice_on_ch1_off_ch2": candidate.get("detail_normal_uv_choice_on_ch1_off_ch2"),
                    "uv_resolution": candidate.get("detail_normal_uv_resolution", "shader_parameter"),
                    "uv_evidence": candidate.get("detail_normal_uv_evidence"),
                }
                if candidate.get("detail_normal_uv_candidates"):
                    base_material["detail_normal_probe"] = {
                        **detail_common,
                        "production_enabled": False,
                        "production_uv_channel": candidate.get("detail_normal_three_uv_channel"),
                        "uv_resolution": candidate.get("detail_normal_uv_resolution", "audited_fixed_shader_path_uv0"),
                        "uv_candidates": list(candidate.get("detail_normal_uv_candidates") or [0, 1]),
                        "reason": "production UV channel is audited; alternate channel retained for diagnostics",
                    }
            else:
                # 固定Shader経路が未解明な間は証拠を保全し、候補となる両Channelを診断モードだけで表示する。
                base_material["detail_normal_probe"] = {
                    **detail_common,
                    "production_enabled": False,
                    "uv_resolution": candidate.get("detail_normal_uv_resolution", "fixed_shader_path_unresolved"),
                    "uv_candidates": list(candidate.get("detail_normal_uv_candidates") or [0, 1]),
                    "reason": "installed carbon shader exposes tiling but no audited production UV channel",
                }
        mask_assets = [
            dict(row) for row in (runtime.get("material_texture_assets") or [])
            if isinstance(row, dict) and row.get("available") and row.get("role_candidate") == "mask_candidate"
        ]
        # r187：原本のTwin Twill材質は名前が明示されたMask Swatchも参照する。
        # Shader上の正確な意味が未証明なので、派生したUV0／UV1の読取専用プレビューだけを診断に提供し、製品Materialには適用しない。
        if (
            len(mask_assets) == 1
            and "detail_normal_u_tiling" in candidate
            and "detail_normal_v_tiling" in candidate
        ):
            mask_result = extract_material_texture_preview(
                mask_assets[0], render_root / "base-detail-mask.png"
            )
            mask_binding = texture_binding_evidence(
                runtime, str(mask_assets[0].get("reference") or "")
            )
            weave_evidence = weave_semantic_evidence(runtime)
            bound_names = {str(name).casefold() for name in mask_binding.get("parameter_names") or []}
            mask_is_weave = "weavemask_texture" in bound_names
            base_material["detail_mask_probe"] = {
                **{k: v for k, v in mask_result.items() if k != "output"},
                "u_tiling": candidate.get("detail_normal_u_tiling"),
                "v_tiling": candidate.get("detail_normal_v_tiling"),
                "scope": "diagnostic_only",
                "local_render_endpoint": "api/local-render/base-detail-mask" if mask_result.get("available") else None,
                "production_enabled": False,
                "shader_texture_binding": mask_binding,
                "weave_semantic_evidence": weave_evidence,
                "semantic_resolution": "audited_weave_mask_binding" if mask_is_weave else "unresolved_texture_binding",
                "uv_resolution": "unresolved_weave_mask_semantics",
                "uv_candidates": [0, 1],
                "reason": (
                    "installed material Texture2D record binds this swatch to WeaveMask_Texture; exact downstream shader equation and UV semantics remain diagnostic"
                    if mask_is_weave else
                    "filename-explicit carbon weave mask; exact shader binding was not resolved"
                ),
            }
    contract["section_composite_supersample"] = int(
        fast_renderer_info.get("section_composite_supersample", 1)
    )
    timings["base_paint_material_seconds"] = time.perf_counter() - base_paint_started
    wheel_routing_started = time.perf_counter()
    wheel_paint_routing, wheel_paint_routing_cache_hit = cached_wheel_paint_routing(
        cache_root=vehicle_cache_root / "wheel-routing",
        content_root=normalize_fh6_game_folder(game_folder),
        vehicle_archive=asset.archive_path,
        mesh_path=mesh_path,
        build=lambda: _wheel_paint_routing_diagnostics(game_folder, asset, mesh_path),
    )
    wheel_paint_routing_path = output / "wheel-paint-routing-diagnostics.json"
    wheel_paint_routing_path.write_text(
        json.dumps(wheel_paint_routing, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    contract["wheel_paint_routing"] = wheel_paint_routing
    # ペイントに有効なホイール記録が無いグループは、原本ホイールMatIの既定色で補う
    # （緑一色のSwatchを色として使わない）。補えないグループは従来どおり停止する。
    from tools.livery.wheel_default_paint import add_original_wheel_default_paint
    contract["wheel_paint_colors"] = add_original_wheel_default_paint(
        contract.get("wheel_paint_colors") or {}, wheel_paint_routing,
        content_root=normalize_fh6_game_folder(game_folder), vehicle_archive=asset.archive_path,
        cache_root=vehicle_cache_root / "vehicle-analysis",
    )
    timings["wheel_paint_routing_seconds"] = time.perf_counter() - wheel_routing_started
    # 車体の非塗装部品（樹脂・ゴム・内装・金属部品等）は、中立の灰色ではなく原本MatIの色で描く。
    # 求められない材質は記録せず（Viewerは従来の中立色）、失敗も契約に残して黙って省略しない。
    # 結果はペイントに依存しないため、車種ごとのキャッシュ（無ければ作る）から使う。Textureは原本SHA256の
    # 名前で車種をまたいで共有のフォルダーに置き、契約の body_trim_texture_cache で配信元を伝える。
    body_trim_started = time.perf_counter()
    body_trim_cache_hit = False
    body_trim_texture_root = vehicle_cache_root / "body-trim-textures"
    body_trim_location: dict = {}
    from tools.livery.body_trim_default_color import SCHEMA as BODY_TRIM_SCHEMA, cached_body_trim_colors
    try:
        contract["body_trim_colors"], body_trim_cache_hit = cached_body_trim_colors(
            mesh_path, content_root=normalize_fh6_game_folder(game_folder),
            vehicle_archive=asset.archive_path,
            cache_root=vehicle_cache_root / "vehicle-analysis",
            texture_dir=body_trim_texture_root,
            location=body_trim_location,
        )
        contract["body_trim_texture_cache"] = {"root": str(body_trim_texture_root),
                                               "scope": "per-vehicle-shared", "cache_hit": body_trim_cache_hit}
    except Exception as exc:  # noqa: BLE001  追加の色の計算で準備全体を止めない（従来の中立色）。理由は契約に残す。
        contract["body_trim_colors"] = {"schema": BODY_TRIM_SCHEMA, "groups": {},
                                        "error": f"{type(exc).__name__}: {exc}"}
    timings["body_trim_colors_seconds"] = time.perf_counter() - body_trim_started
    timings["atlas_seconds"] = time.perf_counter() - phase

    timings["prepare_total_seconds"] = time.perf_counter() - total_started
    render_contract_path = output / "local-render-contract.json"
    # 車ごとに同じ解析の結果（内装・トリムの色）はペイントごとに写さず、車のキャッシュの結果のファイルを指す
    # （tools/livery/shared_contract_results.py）。字下げもしない（4212 で 1 件 約 750 KB → 約 150 KB。2026-11-20）。
    from tools.livery import shared_contract_results
    render_contract_path.write_text(
        json.dumps(shared_contract_results.for_disk(
            contract, {"body_trim_colors": body_trim_location.get("path")}, vehicle_cache_root),
            ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    atlas_prepare_profile = {
        key: round(float(value), 4)
        for key, value in dict(contract.get("prepare_profile") or {}).items()
        if isinstance(value, (int, float))
    }
    cache_state = {
        "canonical_design_cache_hit": bool(canonical_design_cache.get("cache_hit")),
        "canonical_design_decode_skipped": bool(canonical_design_cache.get("decode_skipped")),
        "clivery_privacy_cache_hit": bool(privacy_cache.get("cache_hit")),
        "clivery_privacy_scan_skipped": bool(privacy_cache.get("scan_skipped")),
        "mesh_cache_hit": bool(mesh_cache_hit),
        "render_contract_cache_hit": bool(contract.get("cache_hit")),
        "paint_cache_hit": bool((contract.get("paint_cache") or {}).get("cache_hit")),
        "paint_render_skipped": bool((contract.get("paint_cache") or {}).get("render_skipped")),
        "projection_mask_cache_hit": bool((contract.get("mask_cache") or {}).get("cache_hit")),
        "projection_mask_decode_skipped": bool((contract.get("mask_cache") or {}).get("decode_skipped")),
    }
    cache_footprint = _current_cache_footprint(
        output=output,
        contract=contract,
        mesh_path=mesh_path,
        wheel_morph_sidecar=wheel_morph_sidecar,
        body_kit_variants=body_kit_variants,
        canonical_design_cache_root=Path(str(canonical_design_cache.get("root") or "")) if canonical_design_cache.get("root") else None,
    )
    summary = {
        "format": "lo4fh6_game_facing_preview_research_v1",
        "source": str(source),
        "game_folder": str(game_folder),
        "folder_id": folder_id,
        "c_livery_embedded_id": embedded_car_id,
        "source_c_livery_sha256": source_c_livery_sha256,
        "car_id": car_id,
        "resolved_car_id": car_id,
        "resolved_car_id_source": car_id_source,
        "source_id_differs_from_resolved_car_id": bool(embedded_car_id and embedded_car_id != car_id),
        "model_code": asset.model_code,
        "vehicle_archive": str(asset.archive_path),
        "vehicle_archive_sha256": firstparty_original_sha256,
        "body_kit_part_id": active_body_kit_part_id,
        "body_kit_baseline_part_id": body_kit_baseline_part_id,
        "body_kit_variants": body_kit_variants,
        "part_selection": part_selection or {},
        "part_selection_source": "manual_manifest_body_kit_part_id" if body_kit_part_id is not None else "deterministic_converter_baseline",
        "installed_save_state_resolved": False,
        "body_kit_overlay_plan": body_kit_overlay_plan or {},
        "body_kit_overlay_mesh": str(body_kit_overlay_mesh) if body_kit_overlay_mesh else "",
        "body_kit_overlay_cache_hit": body_kit_overlay_cache_hit,
        "body_kit_overlay_validation": body_kit_overlay_validation,
        "game_database": str(gamedb_path) if gamedb_path is not None else "",
        "game_database_size": gamedb_stat.st_size if gamedb_stat else 0,
        "game_database_mtime_ns": gamedb_stat.st_mtime_ns if gamedb_stat else 0,
        "game_database_assembly_car_body_ids": [int(key) for key in exact_assembly_variants],
        "game_database_requested_car_body_id": requested_gamedb_car_body_id,
        "game_database_selected_car_body_id": selected_gamedb_car_body_id,
        "wheel_morph_reference_helper": "",
        "wheel_morph_reference_helper_sha256": "",
        "wheel_morph_reference_car_body_id": None,
        "wheel_morph_reference_cache_identity": "",
        "private_preview": str(preview_path),
        "mesh": str(mesh_path),
        "mesh_cache_hit": mesh_cache_hit,
        "mesh_preparation_profile_seconds": mesh_preparation_profile,
        "vehicle_cache_root": str(vehicle_cache_root),
        "canonical_design_cache_scope": str(canonical_design_cache.get("scope") or ""),
        "canonical_design_cache_root": str(canonical_design_cache.get("root") or ""),
        "canonical_design_cache_hit": bool(canonical_design_cache.get("cache_hit")),
        "canonical_design_decode_skipped": bool(canonical_design_cache.get("decode_skipped")),
        "clivery_privacy_cache_hit": bool(privacy_cache.get("cache_hit")),
        "clivery_privacy_scan_skipped": bool(privacy_cache.get("scan_skipped")),
        "vehicle_mesh_cache_scope": "shared-by-model-archive-revision",
        "paint_atlas_cache_scope": str((contract.get("paint_cache") or {}).get("scope") or "per-livery"),
        "paint_atlas_cache_root": str((contract.get("paint_cache") or {}).get("root") or render_root),
        "paint_atlas_cache_hit": bool((contract.get("paint_cache") or {}).get("cache_hit")),
        "paint_atlas_render_skipped": bool((contract.get("paint_cache") or {}).get("render_skipped")),
        "projection_mask_cache_scope": str((contract.get("mask_cache") or {}).get("scope") or "per-livery"),
        "projection_mask_cache_root": str((contract.get("mask_cache") or {}).get("root") or render_root),
        "projection_mask_cache_hit": bool((contract.get("mask_cache") or {}).get("cache_hit")),
        "projection_mask_decode_skipped": bool((contract.get("mask_cache") or {}).get("decode_skipped")),
        "vehicle_mesh_cache_variant_scope": "baseline-plus-manifest-delta-overlay-catalog-v1" if len(body_kit_variants) > 1 else "baseline",
        "mesh_validation": mesh_validation,
        "render_root": str(render_root),
        "render_contract": str(render_contract_path),
        "render_contract_format": contract.get("format"),
        "render_contract_revision": int((contract.get("signature") or {}).get("contract_revision") or 0),
        "projection_bounds_source": contract.get("projection_bounds_source"),
        "quality_scale": quality_scale,
        "section_renderer": fast_renderer_info,
        "vinyl_resource_root": None if transient_vinyl_resource_root is not None else str(vinyl_resource_root),
        "vinyl_resource_source": vinyl_resource_source,
        "vinyl_selected_resource_summary": selected_vinyl_resource_summary,
        "sections": contract.get("sections", []),
        "yrvl_material_diagnostics": str(yrvl_diagnostics_path),
        "yrvl_candidate_material_record_count": yrvl_candidate.get("record_count", 0),
        "yrvl_finish_code_histogram": yrvl_candidate.get("finish_code_histogram", {}),
        "yrvl_material_code_histogram": yrvl_candidate.get("material_code_histogram", {}),
        "yrvl_surface_bindings": yrvl_candidate.get("references", []),
        "wheel_paint_colors": contract.get("wheel_paint_colors", {}),
        "yrvl_status": yrvl_diagnostics.get("status", "decoded"),
        "yrvl_warning": yrvl_diagnostics.get("warning"),
        "base_paint_selection": base_paint_selection,
        "base_paint_material": contract.get("base_paint_material", {}),
        "wheel_paint_routing": wheel_paint_routing.get("summary", {}),
        "wheel_paint_routing_cache_hit": wheel_paint_routing_cache_hit,
        "body_trim_colors_cache_hit": body_trim_cache_hit,
        "wheel_paint_routing_diagnostics": str(wheel_paint_routing_path),
        "paint_layer_diagnostics": str(paint_layer_diagnostics_path),
        "viewer_fast_path": bool(args.viewer_fast_path),
        "negative_space_diagnostics": None,
        "negative_space_diagnostic_directory": None,
        "pixel_provenance_diagnostics": None,
        "pixel_provenance_diagnostic_directory": None,
        "mask_owner_summary": None,
        "mask_owner_side_consistency": None,
        "mask_owner_side_matching": None,
        "mask_owner_paired_reconstruction": None,
        "mask_owner_final_reconstruction": None,
        "mask_owner_glyph_local_alignment": None,
        "mask_owner_glyph_cluster_affine": None,
        "mask_owner_glyph_cluster_full_affine": None,
        "mask_owner_glyph_intrinsic_shape": None,
        "performance_target": {
            "goal": "paint-download-complete-to-viewer-ready",
            "target_seconds": 5.0,
            "authoritative_metric": "viewer-startup-metrics.json.bridge_ready_seconds",
            "note": "vehicle-preview prepare timing excludes bridge/UI startup and is a diagnostic phase breakdown",
        },
        "cache_state": cache_state,
        "cache_footprint": cache_footprint,
        "atlas_prepare_profile_seconds": atlas_prepare_profile,
        "timings_seconds": {key: _serialize_timing_value(value) for key, value in timings.items()},
        "read_only": True,
        "limitations": [
            "This viewer targets livery placement/mask/curvature, not pixel-identical FH6 lighting/materials.",
            "The post-artwork yrvl descriptor table is decoded as material/panel paint bindings with enabled BGRA colors, manufacturer selector, and raw finish code. Renderer routing now distinguishes explicit descriptor color, vehicle ManufacturerColors, self-contained finish materials, and the conservative implicit/default selector-0 rule.",
            "Canonical C_livery shape records contain transform, shape ID, BGRA color, alpha, and mask/control framing; no per-placement finish field is present in the decoded 31/32-byte shape payload. paint-layer-diagnostics.json summarizes these authored fields by surface.",
            "negative-space-diagnostics.json replays canonical composition and records only mask operations that actually remove previously painted alpha; it does not assign material semantics to those masks.",
            "The Viewer can switch among Manifest CarBody variants prepared as stock-scene removals plus selected-only loose-model overlays. The initial --body-kit-part-id remains a manual research selection; no variant is evidence of the player's installed save-state body kit.",
            "Exact installed wheel/tire/brake state and FH6 post-processing are not reproduced.",
            "wheel-paint-routing-diagnostics.json joins local WheelStyle material/runtime evidence to per-mesh paint-group routing, but Viewer wheel colour rendering is still diagnostic-only and not yet promoted.",
            "Derived GLB/atlas files come from the user's local FH6 installation and should not be redistributed.",
            "folder_id and C_livery embedded ID are diagnostic identifiers and are not assumed to equal the resolved vehicle Car ID.",
        ],
    }
    (output / "vehicle-preview-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if transient_vinyl_resource_root is not None and transient_vinyl_resource_root.exists():
        import shutil as _shutil
        _shutil.rmtree(transient_vinyl_resource_root, ignore_errors=True)
        configure_vinyl_resource_root(None)

    print(
        "prepared: "
        f"package={timings['private_preview_seconds']:.2f}s "
        f"setup={timings['vehicle_setup_seconds']:.2f}s "
        f"mesh={timings['mesh_seconds']:.2f}s "
        f"atlas={timings['atlas_seconds']:.2f}s"
    )
    print(
        "cache:   "
        f"decode={'skip' if cache_state['canonical_design_decode_skipped'] else 'miss'} "
        f"privacy={'skip' if cache_state['clivery_privacy_scan_skipped'] else 'miss'} "
        f"mesh={'hit' if cache_state['mesh_cache_hit'] else 'miss'} "
        f"paint={'skip' if cache_state['paint_render_skipped'] else ('hit' if cache_state['paint_cache_hit'] else 'miss')} "
        f"mask={'skip' if cache_state['projection_mask_decode_skipped'] else ('hit' if cache_state['projection_mask_cache_hit'] else 'miss')} "
        f"per-livery={cache_footprint['per_livery_output_bytes'] / (1024 * 1024):.2f}MiB"
    )
    print(f"mesh:   {mesh_path}")
    print(f"atlas:  {render_root}")
    print(f"report: {output / 'vehicle-preview-summary.json'}")
    print(f"yrvl:   {yrvl_diagnostics_path}")
    print(f"layers: {paint_layer_diagnostics_path}")
    print(f"wheel:  {wheel_paint_routing_path}")
    if args.viewer_fast_path:
        print("diagnostics: research-only mask/provenance outputs skipped for interactive Viewer")
    else:
        print(f"masks:  {negative_space_diagnostics_path}")
        print(f"pixels: {pixel_provenance_diagnostics_path}")
        print(f"masks+: {mask_owner_summary_path}")
        print(f"sides:  {side_consistency_path}")
        print(f"pairs:  {side_matching_path}")
        print(f"paired: {paired_reconstruction_path}")
        print(f"final:  {final_reconstruction_path}")
        print(f"glyph+: {glyph_alignment_path}")
        print(f"pairimg:{output / 'pixel-provenance-diagnostics' / 'mask-owner-side-pairs'}")
        print(f"pairmap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-paired-reconstruction'}")
        print(f"finalmap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-final-reconstruction'}")
        print(f"glyphs: {output / 'pixel-provenance-diagnostics' / 'mask-owner-glyph-reconstruction'}")
        print(f"glyphmap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-glyph-local-alignment'}")
        print(f"cluster:{glyph_cluster_path}")
        print(f"clustermap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-glyph-cluster-affine'}")
        print(f"fullaff:{glyph_full_affine_path}")
        print(f"fullmap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-glyph-cluster-full-affine'}")
        print(f"shapeid:{glyph_intrinsic_path}")
        print(f"shapemap:{output / 'pixel-provenance-diagnostics' / 'mask-owner-glyph-intrinsic-shape'}")

    if args.prepare_only:
        print("PREPARE PASS — viewer was not started.")
        return 0

    server = LiveryInspectorServer(VIEWER_ROOT)
    try:
        server.set_package(preview_path)
        server.set_local_mesh(mesh_path)
        wheel_private_inputs = (
            args.private_wheel_symbol_png,
            args.private_wheel_symbol_proof,
            args.private_wheel_material_proof,
        )
        if any(wheel_private_inputs):
            if not all(wheel_private_inputs):
                raise FullLiveryPackageError("PRIVATE Wheel研究入力はPNGと2つの証明JSONがすべて必要です")
            server.set_private_source_wheel_research(*wheel_private_inputs)
        overlay_descriptor = dict(body_kit_overlay_plan or {})
        if overlay_descriptor:
            overlay_descriptor["body_kit_part_id"] = active_body_kit_part_id
            overlay_descriptor["part_selection"] = part_selection or {}
            overlay_descriptor["player_save_state_resolved"] = False
        server.set_local_body_kit_overlay(body_kit_overlay_mesh, overlay_descriptor)
        # 後回しにした部品は、Viewer で選ばれたときに同じ処理で変換する（2026-11-21）
        from tools.livery.body_kit_overlay_mesh import ensure_body_kit_overlay
        server.set_local_body_kit_variants(
            body_kit_variants, convert=lambda planned, added: ensure_body_kit_overlay(asset, planned, added))
        server.set_local_render_contract(render_root, contract)
        if args.private_source_facing_proof is not None or args.private_source_facing_contract is not None:
            if args.private_source_facing_proof is None or args.private_source_facing_contract is None:
                raise FullLiveryPackageError("PRIVATE Facing研究には証明JSONと元契約JSONが両方必要です")
            server.set_private_source_facing_research(
                args.private_source_facing_proof, args.private_source_facing_contract,
            )
        url = server.start()
        (output / "viewer-url.txt").write_text(url + "\n", encoding="utf-8")
        print(f"viewer: {url}")
        print("Drag to rotate, mouse wheel to zoom, right-drag to pan.")
        print("Use All / Top / Left / Right / Front / Back in the viewer to isolate sections.")
        print("Press Ctrl+C in this terminal to stop the local viewer.")
        if not args.no_open:
            webbrowser.open(url, new=2)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nviewer stopped")
        return 0
    finally:
        server.close()


def run_as_program() -> None:
    """プログラムとして動かす（ソースの直接起動と、EXE の入口 livery_viewer_for_fh6 の両方から呼ぶ）。"""
    try:
        raise SystemExit(main())
    except (FullLiveryPackageError, PortableMeshConverterError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    run_as_program()
