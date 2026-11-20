from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().with_name("fh6-livery-material-catalog.json")
EXPECTED_FORMAT = "lo4fh6_fh6_livery_material_catalog_v1"


class LiveryMaterialCatalogError(RuntimeError):
    pass


def load_livery_material_catalog(path: Path = CATALOG_PATH) -> dict[int, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveryMaterialCatalogError(f"livery material catalog could not be read: {exc}") from exc

    if payload.get("format") != EXPECTED_FORMAT:
        raise LiveryMaterialCatalogError(
            f"unexpected livery material catalog format: {payload.get('format')!r}"
        )

    records = payload.get("records")
    if not isinstance(records, list):
        raise LiveryMaterialCatalogError("livery material catalog records are missing")

    by_id: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("id") is None:
            continue
        material_id = int(record["id"])
        if material_id in by_id:
            raise LiveryMaterialCatalogError(f"duplicate livery material id: {material_id}")
        by_id[material_id] = dict(record)
    return by_id


def resolve_finish_only_material(
    finish_code_raw: int,
    *,
    catalog: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a finish-only descriptor when the GameDB material needs no input colour.

    A material with ``num_input_colors == 0`` is self-contained from the base-paint
    source point of view.  The resolver intentionally does not manufacture an RGB
    value for such a material; the material path/texture remains the source of truth.
    """

    finish_id = int(finish_code_raw)
    records = catalog if catalog is not None else load_livery_material_catalog()
    record = records.get(finish_id)
    if record is None:
        return {
            "finish_code_raw": finish_id,
            "resolved": False,
            "reason": "finish code is not present in the embedded FH6 GameDB material catalog",
        }

    num_input_colors = int(record.get("num_input_colors") or 0)
    base = {
        "finish_code_raw": finish_id,
        "material_id": int(record.get("id", finish_id)),
        "material_name": str(record.get("material_name") or ""),
        "material_path": str(record.get("material_path") or ""),
        "preview_texture": str(record.get("preview_texture") or ""),
        "is_special_material": bool(record.get("is_special_material")),
        "num_input_colors": num_input_colors,
        "compatibility": str(record.get("compatibility") or ""),
        "resolution_source": "embedded_gamedb_livery_material_catalog",
    }
    if num_input_colors != 0:
        return {
            **base,
            "resolved": False,
            "reason": "finish material still requires explicit input colour data",
        }

    return {
        **base,
        "resolved": True,
        "color_source": "material_defined",
        "reason": "finish material accepts no input colours; no synthetic RGB is required",
    }
