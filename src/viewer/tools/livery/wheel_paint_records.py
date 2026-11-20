from __future__ import annotations

"""Resolve source-backed FH6 wheel paint records from decoded C_livery YRVL data."""

from typing import Any

GENERIC_WHEEL_BINDING_HASHES: dict[str, int] = {
    "Rims": 0xDCE6592BFA0DFA78,
    "Wheel1": 0xE20AAE21D70536F7,
    "Wheel2": 0xE20AAF21D70538AA,
    "Rims2": 0x6963CFB9E5C04BBE,
    "Rims3": 0x6963D0B9E5C04D71,
    "RimsInner": 0xA11BBB5668440C18,
    "RimsLip": 0xC3F4EEFF7A11DBCD,
}

FRONT_WHEEL_PAINT_HASHES: tuple[int, ...] = (
    0xB8925E450764DE78,
    0x15EDB6869EFC7F22,
    0x2407D33BE191E83D,
    0x564DF80BF320D318,
    0x818BB1EF6C704F11,
)
REAR_WHEEL_PAINT_HASHES: tuple[int, ...] = (
    0x6613B1E8FA7AE743,
    0x3A3CBDA8CF17E711,
    0xC338EA21477FD950,
    0x0F1580E714EA9063,
    0x874E9585EAB6EF64,
)

WHEEL_PAINTABLE_GROUPS: dict[str, dict[str, Any]] = {
    **{
        name: {"hash": value, "kind": "generic_binding", "axle": None, "channel_index": None}
        for name, value in GENERIC_WHEEL_BINDING_HASHES.items()
    },
    **{
        f"FrontWheelPaint{index}": {
            "hash": value, "kind": "axle_paint", "axle": "front", "channel_index": index
        }
        for index, value in enumerate(FRONT_WHEEL_PAINT_HASHES, start=1)
    },
    **{
        f"RearWheelPaint{index}": {
            "hash": value, "kind": "axle_paint", "axle": "rear", "channel_index": index
        }
        for index, value in enumerate(REAR_WHEEL_PAINT_HASHES, start=1)
    },
}


def canonical_hash_match(raw_hex: str) -> tuple[str | None, int | None, str | None, dict[str, Any] | None]:
    try:
        raw = bytes.fromhex(str(raw_hex))
    except ValueError:
        return None, None, None, None
    if len(raw) != 8:
        return None, None, None, None
    values = (("little", int.from_bytes(raw, "little")), ("big", int.from_bytes(raw, "big")))
    for byte_order, value in values:
        for name, metadata in WHEEL_PAINTABLE_GROUPS.items():
            if value == int(metadata["hash"]):
                return name, value, byte_order, metadata
    return None, None, None, None


def resolve_wheel_color_records_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    records = candidate.get("records") if isinstance(candidate, dict) else None
    if not isinstance(records, list):
        return []
    result: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name, value, byte_order, metadata = canonical_hash_match(str(record.get("material_identifier_hex") or ""))
        if not name or value is None or metadata is None:
            continue
        primary = record.get("primary_color") if isinstance(record.get("primary_color"), dict) else {}
        secondary = record.get("secondary_color") if isinstance(record.get("secondary_color"), dict) else {}
        result.append({
            "paintable_group": name,
            "paintable_group_hash_hex": f"0x{value:016X}",
            "group_kind": metadata.get("kind"),
            "axle": metadata.get("axle"),
            "channel_index": metadata.get("channel_index"),
            "material_identifier_byte_order": byte_order,
            "value_type_raw": record.get("value_type_raw"),
            "primary_color_enabled": bool(record.get("primary_color_enabled")),
            "primary_color_rgba_hex": primary.get("rgba_hex"),
            "secondary_color_enabled": bool(record.get("secondary_color_enabled")),
            "secondary_color_rgba_hex": secondary.get("rgba_hex"),
            "manufacturer_color_selector_raw": record.get("manufacturer_color_selector_raw"),
            "finish_code_raw": record.get("finish_code_raw"),
        })
    return result


def wheel_paint_contract(candidate: dict[str, Any]) -> dict[str, Any]:
    records = resolve_wheel_color_records_from_candidate(candidate)
    by_group: dict[str, dict[str, Any]] = {}
    duplicate_groups: list[str] = []
    for record in records:
        name = str(record.get("paintable_group") or "")
        if not name:
            continue
        if name in by_group:
            duplicate_groups.append(name)
            continue
        by_group[name] = dict(record)
    enabled = {
        name: row for name, row in by_group.items()
        if row.get("primary_color_enabled") and row.get("primary_color_rgba_hex")
    }
    return {
        "format": "lo4fh6_wheel_paint_contract_v1",
        "read_only": True,
        "record_count": len(records),
        "group_count": len(by_group),
        "enabled_primary_group_count": len(enabled),
        "duplicate_groups": sorted(set(duplicate_groups)),
        "groups": by_group,
        "boundary": (
            "Only exact known wheel paintable-group hashes are exposed. Disabled or missing primary colours remain fail-closed; "
            "finish/shader response is not promoted by this contract."
        ),
    }
