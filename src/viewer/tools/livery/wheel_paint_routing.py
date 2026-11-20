from __future__ import annotations

"""Declarative FH6 wheel paint routing evidence helpers.

This module keeps the mesh/material-token -> paint-group routing separate from
any renderer adoption.  It is grounded in external format/behavior evidence and
local LO4FH6-owned regression fixtures only.
"""

from typing import Any

REFERENCE_PROJECT = "参照製品（外部の公開実装。形式・挙動の裏付けだけに使用）"
REFERENCE_COMMIT = "2c54a63ddc6a687eb18cde8e7a01a259093d4bc4"
REFERENCE_LICENSE = "AGPL-3.0"

# 1-based indices match the C_livery paintable-group names.
AXLE_CHANNEL_BY_MATERIAL_TOKEN: dict[str, int] = {
    "rim": 1,
    "rim2": 2,
    "inner_rim": 3,
    "hub": 4,
    "lug": 5,
}
GENERIC_GROUP_BY_MATERIAL_TOKEN: dict[str, str] = {
    "rim3": "Rims3",
    "lip": "RimsLip",
    "detail": "Wheel1",
    "detail2": "Wheel2",
}


# 原本car_automotive_paintとg_CarUserColor0が両方確認できる場合に限り、
# ホイール補助材質を軸別primaryへ結線する。名前だけでは採用しない。
SIGNED_PRIMARY_WHEEL_AUX_TOKENS = frozenset({"black", "wheel_badge", "valve_cap"})


def material_token(value: str) -> str:
    text = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip().casefold()
    if "|" in text:
        text = text.split("|", 1)[0]
    if text.endswith(".materialbin"):
        text = text[:-12]
    return text


def route_for_material(
    material_name: str, *, shader_family: str = "", has_user_color0: bool = False
) -> dict[str, Any]:
    token = material_token(material_name)
    if token in AXLE_CHANNEL_BY_MATERIAL_TOKEN:
        channel = AXLE_CHANNEL_BY_MATERIAL_TOKEN[token]
        return {
            "material_token": token,
            "route_kind": "axle_paint",
            "channel_index": channel,
            "front_group": f"FrontWheelPaint{channel}",
            "rear_group": f"RearWheelPaint{channel}",
            "generic_group": None,
        }
    if token in GENERIC_GROUP_BY_MATERIAL_TOKEN:
        return {
            "material_token": token,
            "route_kind": "generic_binding",
            "channel_index": None,
            "front_group": None,
            "rear_group": None,
            "generic_group": GENERIC_GROUP_BY_MATERIAL_TOKEN[token],
        }
    # FH6原本MatIのShader外部入力と、他製品の軸別primary観測を併用する。
    # 同名の非塗装材質や未知Shaderは自動着色しない。
    if (token in SIGNED_PRIMARY_WHEEL_AUX_TOKENS
            and str(shader_family).casefold() == "car_automotive_paint"
            and has_user_color0 is True):
        return {
            "material_token": token,
            "route_kind": "axle_paint",
            "channel_index": 1,
            "front_group": "FrontWheelPaint1",
            "rear_group": "RearWheelPaint1",
            "generic_group": None,
        }
    return {
        "material_token": token,
        "route_kind": "unresolved",
        "channel_index": None,
        "front_group": None,
        "rear_group": None,
        "generic_group": None,
    }


def build_report(binding: dict[str, Any], *, include_rows_without_user_color0: bool = False) -> dict[str, Any]:
    """Build a per-mesh routing report from a wheel material-binding report.

    ``binding`` should follow the structural output of the r260 wheel material /
    user-colour binding audit.  Only meshes that expose ``g_CarUserColor0`` are
    routed unless ``include_rows_without_user_color0`` is set.
    """

    cars_out: list[dict[str, Any]] = []
    total_external = 0
    total_routed_external = 0
    total_axle = 0
    total_generic = 0
    total_unresolved_external = 0

    for car in binding.get("cars") or []:
        car_rows: list[dict[str, Any]] = []
        for source in car.get("sources") or []:
            source_entry = str(source.get("source_entry") or "")
            source_sha = str(source.get("source_modelbin_sha256") or "")
            for row in source.get("mesh_material_bindings") or []:
                inputs = [item for item in row.get("external_user_color_inputs") or [] if isinstance(item, dict)]
                has_user0 = any(str(item.get("name") or "") == "g_CarUserColor0" for item in inputs)
                if not has_user0 and not include_rows_without_user_color0:
                    continue
                if has_user0:
                    total_external += 1
                route = route_for_material(
                    str(row.get("material_name") or ""),
                    shader_family=str(row.get("shader_family") or ""),
                    has_user_color0=has_user0,
                )
                if has_user0:
                    if route["route_kind"] == "axle_paint":
                        total_axle += 1
                        total_routed_external += 1
                    elif route["route_kind"] == "generic_binding":
                        total_generic += 1
                        total_routed_external += 1
                    else:
                        total_unresolved_external += 1
                car_rows.append({
                    "source_entry": source_entry,
                    "source_modelbin_sha256": source_sha,
                    "material_instance_sha256": str(row.get("material_instance_sha256") or ""),
                    "mesh_name": str(row.get("mesh_name") or ""),
                    "material_id": int(row["material_id"]) if row.get("material_id") is not None else -1,
                    "material_name": str(row.get("material_name") or ""),
                    "shader_family": str(row.get("shader_family") or ""),
                    "external_input": "g_CarUserColor0" if has_user0 else None,
                    **route,
                })
        cars_out.append({
            "car_id": int(car.get("car_id") or 0),
            "model_code": str(car.get("model_code") or ""),
            "g_CarUserColor0_mesh_count": sum(row["external_input"] == "g_CarUserColor0" for row in car_rows),
            "axle_routed_mesh_count": sum(row["route_kind"] == "axle_paint" and row["external_input"] == "g_CarUserColor0" for row in car_rows),
            "generic_routed_mesh_count": sum(row["route_kind"] == "generic_binding" and row["external_input"] == "g_CarUserColor0" for row in car_rows),
            "unresolved_mesh_count": sum(row["route_kind"] == "unresolved" and row["external_input"] == "g_CarUserColor0" for row in car_rows),
            "rows": car_rows,
        })

    return {
        "format": "lo4fh6_wheel_mesh_paint_routing_v1",
        "read_only": True,
        "source_binding_format": str(binding.get("format") or ""),
        "reference": {
            "project": REFERENCE_PROJECT,
            "commit": REFERENCE_COMMIT,
            "license": REFERENCE_LICENSE,
            "use": "external format/behavior evidence only; no source code copied, vendored, linked, translated, or required at runtime",
        },
        "summary": {
            "status": "PASS" if cars_out and total_external else "FAIL",
            "car_count": len(cars_out),
            "g_CarUserColor0_mesh_count": total_external,
            "routed_g_CarUserColor0_mesh_count": total_routed_external,
            "axle_paint_mesh_count": total_axle,
            "generic_binding_mesh_count": total_generic,
            "unresolved_g_CarUserColor0_mesh_count": total_unresolved_external,
        },
        "interpretation": {
            "resolved_concept": (
                "g_CarUserColor0 is an external input of each material instance, not one globally fixed C_livery wheel channel. "
                "For recognized wheel material tokens, the supplying paint group is selected per mesh and per axle."
            ),
            "axle_channel_mapping": {
                token: {
                    "channel_index": channel,
                    "front_group": f"FrontWheelPaint{channel}",
                    "rear_group": f"RearWheelPaint{channel}",
                }
                for token, channel in AXLE_CHANNEL_BY_MATERIAL_TOKEN.items()
            },
            "generic_fallback_mapping": dict(GENERIC_GROUP_BY_MATERIAL_TOKEN),
            "boundary": (
                "This report validates routing behavior against the supplied local WheelStyle binding evidence. "
                "It does not prove compiled constant-buffer offsets/instruction equations and does not itself change Viewer rendering."
            ),
        },
        "cars": cars_out,
    }
