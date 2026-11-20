from __future__ import annotations

"""Shared WheelStyle mesh/material/runtime binding helpers.

These helpers inspect local FH6 game assets only.  They do not read GameSave or
Livery data and do not persist raw embedded material bytes.
"""

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from .material_runtime import inspect_embedded_material_instance_runtime
from .portable_mesh_converter import _glb_payloads
from .wheel_morph_internal import wheelstyle_material_bindings, wheelstyle_material_payloads


def source_entries_from_glb(glb: Path) -> list[str]:
    """Read signed first-party WheelStyle source paths without discarding legacy GLBs.

    原本出典を曖昧な旧名だけで判定しない。新旧のPartType/パス宣言が矛盾する
    GLBは推測補完せず、原本ModelBinを開く前に停止する。
    """
    document, _ = _glb_payloads(glb)
    result: list[str] = []
    seen: set[str] = set()
    for index, mesh in enumerate(document.get("meshes") or []):
        if not isinstance(mesh, dict):
            continue
        extras = mesh.get("extras") if isinstance(mesh.get("extras"), dict) else {}
        first_type = extras.get("lo4fh6_part_type")
        legacy_type = extras.get("lo4_part_type")
        first_kind = str(first_type).casefold() if first_type is not None else None
        legacy_kind = str(legacy_type).casefold() if legacy_type is not None else None
        if first_kind is not None and legacy_kind is not None and first_kind != legacy_kind:
            raise ValueError(f"Wheel source mesh {index}: inconsistent first-party/legacy PartType")
        if first_kind != "wheelstyle" and legacy_kind != "wheelstyle":
            continue
        first_source = str(extras.get("lo4fh6_source_entry") or "").replace("\\", "/").strip()
        legacy_source = str(extras.get("lo4_source_entry") or "").replace("\\", "/").strip()
        if first_source and legacy_source and first_source.casefold() != legacy_source.casefold():
            raise ValueError(f"Wheel source mesh {index}: inconsistent first-party/legacy source entry")
        source = first_source or legacy_source
        if not source:
            raise ValueError(f"Wheel source mesh {index}: signed WheelStyle source entry missing")
        key = source.casefold()
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def archive_entry(source: str, model_code: str, names: dict[str, str]) -> str | None:
    normalized = source.replace("\\", "/").strip()
    folded = normalized.casefold()
    direct = names.get(folded)
    if direct:
        return direct
    prefixes = (
        f"game:/media/cars/{model_code}/".casefold(),
        f"game:\\media\\cars\\{model_code}\\".casefold(),
    )
    for prefix in prefixes:
        if folded.startswith(prefix):
            relative = normalized[len(prefix):].lstrip("/\\")
            return names.get(relative.casefold())
    marker = f"/{model_code.casefold()}/"
    pos = folded.find(marker)
    if pos >= 0:
        relative = normalized[pos + len(marker):].lstrip("/\\")
        return names.get(relative.casefold())
    return None


def material_semantic_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    evidence = runtime.get("semantic_external_user_color_inputs") or {}
    inputs = [dict(row) for row in (evidence.get("inputs") or []) if isinstance(row, dict)]
    return {
        "runtime_available": bool(runtime.get("available")),
        "shader_family": str(runtime.get("shader_family") or ""),
        "resolved_material_path": str(runtime.get("resolved_material_path") or ""),
        # 同じModelBin内でMaterial Instanceの原本実バイトが同一であることを照合する。
        # 画像色やShader式ではなく、MatI／解決済みMaterial／ShaderのSHAを保持。
        "material_instance_sha256": str(runtime.get("material_sha256") or ""),
        "resolved_material_sha256": str(runtime.get("resolved_material_sha256") or ""),
        "shader_sha256": str(runtime.get("shader_sha256") or ""),
        "external_user_color_resolved": bool(evidence.get("resolved")),
        "external_user_color_inputs": [
            {
                "index": int(row.get("index") or 0),
                "name": str(row.get("name") or ""),
                "size": int(row.get("size") or 0),
                "referenced": bool(row.get("referenced")),
                "classification": str(row.get("classification") or ""),
            }
            for row in inputs
        ],
        "material_default_record_parameter_count": int(evidence.get("material_default_record_parameter_count") or 0),
        "compiled_constant_buffer_offset_resolved": bool(evidence.get("compiled_constant_buffer_offset_resolved")),
        "compiled_shader_equation_resolved": bool(evidence.get("compiled_shader_equation_resolved")),
        "basis": str(evidence.get("basis") or ""),
        "error": runtime.get("error"),
    }


def join_mesh_material_runtime(bindings: list[dict[str, Any]], material_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {int(row["material_id"]): row for row in material_rows if isinstance(row.get("material_id"), int)}
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        # Material-ID 0 は有効な原本ID。truthinessで -1 に変換しない。
        raw_material_id = binding.get("material_id")
        material_id = int(raw_material_id) if raw_material_id is not None else -1
        material = by_id.get(material_id)
        semantic = material_semantic_summary(material.get("runtime") or {}) if material else {
            "runtime_available": False,
            "shader_family": "",
            "resolved_material_path": "",
            "external_user_color_resolved": False,
            "external_user_color_inputs": [],
            "material_default_record_parameter_count": 0,
            "compiled_constant_buffer_offset_resolved": False,
            "compiled_shader_equation_resolved": False,
            "basis": "referenced material runtime was not decoded",
            "error": None,
        }
        rows.append({
            "mesh_name": str(binding.get("mesh_name") or ""),
            "bucket_flags_hex": str(binding.get("bucket_flags_hex") or ""),
            "material_id": material_id,
            "material_name": str(binding.get("material_name") or ""),
            "material_nested_names": list(binding.get("material_nested_names") or []),
            **semantic,
        })
    return rows


def inspect_wheelstyle_bindings(content_root: Path, asset: Any, glb: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    source_entries = source_entries_from_glb(glb)
    with zipfile.ZipFile(asset.archive_path) as archive:
        # 同名/大小文字衝突をdictの後勝ちで隠さず、元ModelBin出典を確定する。
        names = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw_name = info.filename
            normalized = raw_name.replace(chr(92), "/")
            if (not normalized or normalized.startswith("/")
                    or any(part in ("", ".", "..") for part in normalized.split("/"))):
                raise ValueError("Wheel元車両ZIP内部パスが不正")
            key = normalized.casefold()
            if key in names:
                raise ValueError("Wheel元車両ZIP内ModelBinパスが大小文字違いで重複")
            names[key] = normalized
        for source in source_entries:
            actual = archive_entry(source, asset.model_code, names)
            if not actual:
                sources.append({"source_entry": source, "status": "FAIL", "error": "source modelbin was not found in vehicle archive"})
                continue
            modelbin = archive.read(actual)
            source_modelbin_sha256 = hashlib.sha256(modelbin).hexdigest()
            bindings = wheelstyle_material_bindings(modelbin)
            payloads = wheelstyle_material_payloads(modelbin)
            material_rows: list[dict[str, Any]] = []
            for material in payloads:
                runtime = inspect_embedded_material_instance_runtime(
                    content_root,
                    material["payload"],
                    material_label=f"WheelStyle material {material['material_id']}:{material.get('material_name') or '-'}",
                    material_source={"kind": "embedded-wheelstyle-modelbin", "source_entry": actual},
                    vehicle_archive=asset.archive_path,
                )
                material_rows.append({
                    "material_id": int(material["material_id"]),
                    "material_name": str(material.get("material_name") or ""),
                    "runtime": runtime,
                })
            mesh_rows = join_mesh_material_runtime(bindings, material_rows)
            external_rows = [row for row in mesh_rows if row.get("external_user_color_inputs")]
            user_color0_rows = [
                row for row in external_rows
                if any(str(item.get("name")) == "g_CarUserColor0" for item in row.get("external_user_color_inputs") or [])
            ]
            sources.append({
                "source_entry": actual,
                "source_modelbin_sha256": source_modelbin_sha256,
                "status": "PASS" if bindings else "FAIL",
                "mesh_count": len(mesh_rows),
                "mesh_external_user_color_count": len(external_rows),
                "mesh_g_CarUserColor0_count": len(user_color0_rows),
                "mesh_material_bindings": mesh_rows,
            })
    return {
        "format": "lo4fh6_wheel_material_user_color_binding_v1",
        "read_only": True,
        "privacy": {"reads_game_assets": True, "reads_livery_data": False, "reads_gamesave": False},
        "car_id": int(getattr(asset, "car_id", 0) or 0),
        "model_code": str(getattr(asset, "model_code", "") or ""),
        "source_count": len(sources),
        "mesh_count": sum(int(row.get("mesh_count") or 0) for row in sources),
        "mesh_external_user_color_count": sum(int(row.get("mesh_external_user_color_count") or 0) for row in sources),
        "mesh_g_CarUserColor0_count": sum(int(row.get("mesh_g_CarUserColor0_count") or 0) for row in sources),
        "sources": sources,
    }
