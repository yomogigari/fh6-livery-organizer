from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from typing import Any

from .gyvl import LIVERY_SURFACE_NAMES
from .parser import ParseError, decompress_c_livery, livery_vlrc_layout, read_u32le


TAIL_COUNT_CHUNK_SIZE = 4 + len(LIVERY_SURFACE_NAMES) * 4 + 4
MATERIAL_HEADER_SIZE = 14
MATERIAL_RECORD_SIZE = 27
SENTINEL = b"yrvl\x00\x00\x00\x00"
FINAL_TRAILER_SIZE = 8


def _bgra(data: bytes) -> dict[str, Any]:
    if len(data) != 4:
        raise ParseError("BGRA field must be exactly four bytes")
    b, g, r, a = data
    return {
        "bgra": [b, g, r, a],
        "bgra_hex": data.hex(),
        "rgba": [r, g, b, a],
        "rgba_hex": f"#{r:02x}{g:02x}{b:02x}{a:02x}",
    }



def probe_livery_yrvl_variant(path: Path) -> tuple[dict[str, Any], bytes]:
    """Return a read-only structural probe of the post-gyvl yrvl tail.

    This does not guess an unknown material-table layout.  It exports the exact
    tail bytes and stable offsets so a new FH6 variant can be studied without
    sharing the complete C_livery payload.
    """
    payload = decompress_c_livery(path)
    if len(payload) < 8 or payload[:4] != b"vlrc":
        raise ParseError("C_livery payload is not vlrc")

    format_version = read_u32le(payload, 0x004)
    layout = livery_vlrc_layout(format_version)
    if layout is None:
        raise ParseError(f"unsupported vlrc format version {format_version}")

    gyvl_size_offset = int(layout["gyvl_size_offset"])
    gyvl_offset = int(layout["gyvl_offset"])
    gyvl_size = read_u32le(payload, gyvl_size_offset)
    gyvl_end = gyvl_offset + gyvl_size
    counts_offset = gyvl_end
    counts_end = counts_offset + TAIL_COUNT_CHUNK_SIZE
    if counts_end > len(payload) or payload[counts_offset : counts_offset + 4] != b"yrvl":
        raise ParseError("expected post-gyvl yrvl section-count chunk is missing")

    tail = payload[counts_end:]
    marker_offsets: list[int] = []
    cursor = 0
    while True:
        found = tail.find(b"yrvl", cursor)
        if found < 0:
            break
        marker_offsets.append(found)
        cursor = found + 1

    first = tail[:64]
    probe = {
        "format": "lo4fh6_yrvl_variant_probe_v1",
        "vlrc_format_version": format_version,
        "payload_size": len(payload),
        "gyvl": {"offset": gyvl_offset, "size": gyvl_size, "end": gyvl_end},
        "section_count_chunk": {"offset": counts_offset, "size": TAIL_COUNT_CHUNK_SIZE, "end": counts_end},
        "variant_tail": {
            "offset": counts_end,
            "length": len(tail),
            "sha256": hashlib.sha256(tail).hexdigest(),
            "first_64_hex": first.hex(),
            "yrvl_marker_offsets_relative": marker_offsets,
            "yrvl_marker_offsets_absolute": [counts_end + item for item in marker_offsets],
            "u16_at_plus_6_if_present": int.from_bytes(tail[6:8], "little") if len(tail) >= 8 else None,
            "u32_at_plus_6_if_present": int.from_bytes(tail[6:10], "little") if len(tail) >= 10 else None,
        },
        "note": "Raw tail is exported separately; no unknown field semantics are guessed.",
    }
    return probe, tail

def parse_livery_yrvl_diagnostics(path: Path) -> dict[str, Any]:
    """Structurally decode the FH6 C_livery yrvl regions used in this research.

    The descriptor-table envelope is structurally stable across the current
    fixtures.  Public reverse-engineering documentation now confirms the 27-byte
    paint-record field layout (material identifier, enabled colors, manufacturer
    selector, finish code).  Exact finish-code names are still kept raw here
    unless independently verified.
    """
    payload = decompress_c_livery(path)
    if len(payload) < 8 or payload[:4] != b"vlrc":
        raise ParseError("C_livery payload is not vlrc")

    format_version = read_u32le(payload, 0x004)
    layout = livery_vlrc_layout(format_version)
    if layout is None:
        raise ParseError(f"unsupported vlrc format version {format_version}")
    if format_version != 2:
        raise ParseError("yrvl research diagnostics currently target FH6 vlrc v2 only")

    header_yrvl_offset = int(layout["yrvl_offset"])
    header_version_offset = int(layout["yrvl_version_offset"])
    owner_offset = int(layout["owner_offset"])
    state_offset = int(layout["state_offset"])
    gyvl_size_offset = int(layout["gyvl_size_offset"])
    gyvl_offset = int(layout["gyvl_offset"])
    gyvl_size = read_u32le(payload, gyvl_size_offset)
    gyvl_end = gyvl_offset + gyvl_size

    if payload[header_yrvl_offset : header_yrvl_offset + 4] != b"yrvl":
        raise ParseError("vlrc header yrvl marker is missing")
    if gyvl_end > len(payload):
        raise ParseError("gyvl extends beyond the vlrc payload")

    header = {
        "offset": header_yrvl_offset,
        "version": read_u32le(payload, header_version_offset),
        "owner_token_hex": payload[owner_offset : owner_offset + 8].hex(),
        "state_raw": read_u32le(payload, state_offset),
        "note": "vlrc header identity/state region; do not treat as paint material data",
    }

    counts_offset = gyvl_end
    counts_end = counts_offset + TAIL_COUNT_CHUNK_SIZE
    if counts_end > len(payload) or payload[counts_offset : counts_offset + 4] != b"yrvl":
        raise ParseError("expected post-gyvl yrvl section-count chunk is missing")
    section_counts = [
        read_u32le(payload, counts_offset + 4 + index * 4)
        for index in range(len(LIVERY_SURFACE_NAMES))
    ]
    count_reserved = read_u32le(payload, counts_offset + 4 + len(LIVERY_SURFACE_NAMES) * 4)

    material_offset = counts_end
    if material_offset + MATERIAL_HEADER_SIZE > len(payload):
        raise ParseError("candidate material yrvl chunk is truncated")
    if payload[material_offset : material_offset + 4] != b"yrvl":
        raise ParseError("candidate material yrvl marker is missing")

    format_marker = payload[material_offset + 4 : material_offset + 6]
    record_count = int.from_bytes(payload[material_offset + 6 : material_offset + 8], "little")
    header_reserved = payload[material_offset + 8 : material_offset + MATERIAL_HEADER_SIZE]
    records_offset = material_offset + MATERIAL_HEADER_SIZE
    records_end = records_offset + record_count * MATERIAL_RECORD_SIZE
    if records_end + 4 > len(payload):
        raise ParseError("candidate material record table is truncated")

    records: list[dict[str, Any]] = []
    for index in range(record_count):
        start = records_offset + index * MATERIAL_RECORD_SIZE
        raw = payload[start : start + MATERIAL_RECORD_SIZE]
        finish_code = int.from_bytes(raw[23:27], "little")
        records.append(
            {
                "index": index,
                "offset": start,
                "material_identifier_hex": raw[0:8].hex(),
                "value_type_raw": raw[8],
                "primary_color_enabled_raw": raw[9],
                "primary_color_enabled": bool(raw[9]),
                "primary_color": _bgra(raw[10:14]),
                "secondary_color_enabled_raw": raw[14],
                "secondary_color_enabled": bool(raw[14]),
                "secondary_color": _bgra(raw[15:19]),
                "manufacturer_color_selector_raw": int.from_bytes(raw[19:23], "little"),
                "manufacturer_color_selector_hex": raw[19:23].hex(),
                "finish_code_raw": finish_code,
                # Compatibility aliases retained for existing research reports.
                "record_id_hex": raw[0:8].hex(),
                "record_type_raw": raw[8],
                "material_code_raw": finish_code,
            }
        )

    reference_count = read_u32le(payload, records_end)
    references_offset = records_end + 4
    references_end = references_offset + reference_count * 8
    if references_end > len(payload):
        raise ParseError("candidate material reference table is truncated")

    by_id = {record["record_id_hex"]: record for record in records}
    references: list[dict[str, Any]] = []
    for index in range(reference_count):
        start = references_offset + index * 8
        record_id = payload[start : start + 8].hex()
        record = by_id.get(record_id)
        references.append(
            {
                "index": index,
                "surface": LIVERY_SURFACE_NAMES[index] if index < len(LIVERY_SURFACE_NAMES) else None,
                "record_id_hex": record_id,
                "record_index": record["index"] if record else None,
                "finish_code_raw": record["finish_code_raw"] if record else None,
                "primary_color_enabled": record["primary_color_enabled"] if record else None,
                "primary_color_rgba_hex": record["primary_color"]["rgba_hex"] if record else None,
                "secondary_color_enabled": record["secondary_color_enabled"] if record else None,
                "secondary_color_rgba_hex": record["secondary_color"]["rgba_hex"] if record else None,
                "manufacturer_color_selector_raw": record["manufacturer_color_selector_raw"] if record else None,
            }
        )

    sentinel_offset = references_end
    final_trailer = payload[sentinel_offset : sentinel_offset + FINAL_TRAILER_SIZE]
    if len(final_trailer) != FINAL_TRAILER_SIZE or final_trailer[:4] != b"yrvl":
        raise ParseError("candidate material yrvl chunk is not followed by the expected final yrvl trailer")
    trailing = payload[sentinel_offset + FINAL_TRAILER_SIZE :]
    if trailing:
        raise ParseError(f"unexpected {len(trailing)} bytes after final yrvl trailer")
    trailer_value = final_trailer[4:8]
    trailer_value_u32 = int.from_bytes(trailer_value, "little")
    # Keep this as a diagnostic view only.  The exact gameplay meaning of the
    # final four bytes is not yet proven, so the parser must not infer material
    # semantics from the float interpretation.
    import struct
    trailer_value_f32 = struct.unpack("<f", trailer_value)[0]

    finish_code_histogram = Counter(record["finish_code_raw"] for record in records)
    primary_color_histogram = Counter(record["primary_color"]["rgba_hex"] for record in records)
    secondary_color_histogram = Counter(record["secondary_color"]["rgba_hex"] for record in records)

    return {
        "format": "lo4fh6_yrvl_research_v1",
        "vlrc_format_version": format_version,
        "header_yrvl": header,
        "gyvl": {
            "offset": gyvl_offset,
            "size": gyvl_size,
            "end": gyvl_end,
        },
        "section_count_yrvl": {
            "offset": counts_offset,
            "size": TAIL_COUNT_CHUNK_SIZE,
            "counts": [
                {"slot": index, "surface": name, "count": section_counts[index]}
                for index, name in enumerate(LIVERY_SURFACE_NAMES)
            ],
            "sum": sum(section_counts),
            "reserved_u32": count_reserved,
        },
        "candidate_material_yrvl": {
            "offset": material_offset,
            "format_marker_hex": format_marker.hex(),
            "record_count": record_count,
            "header_reserved_hex": header_reserved.hex(),
            "record_size": MATERIAL_RECORD_SIZE,
            "records": records,
            "reference_count": reference_count,
            "references": references,
            "finish_code_histogram": {str(key): value for key, value in sorted(finish_code_histogram.items())},
            "primary_color_histogram": dict(sorted(primary_color_histogram.items())),
            "secondary_color_histogram": dict(sorted(secondary_color_histogram.items())),
            # Compatibility alias for r16-r19 diagnostics/readers.
            "material_code_histogram": {str(key): value for key, value in sorted(finish_code_histogram.items())},
            "semantics_status": (
                "paint-record field layout confirmed; finish-code numeric-to-name mapping remains raw unless independently verified"
            ),
            "record_layout": {
                "0x00": "material identifier (8 bytes)",
                "0x08": "value type (u8)",
                "0x09": "primary color enabled (u8)",
                "0x0a": "primary BGRA color (4 bytes)",
                "0x0e": "secondary color enabled (u8)",
                "0x0f": "secondary BGRA color (4 bytes)",
                "0x13": "manufacturer color selector (u32)",
                "0x17": "finish code (u32)",
            },
        },
        "final_sentinel": {
            "offset": sentinel_offset,
            "size": FINAL_TRAILER_SIZE,
            "marker_hex": final_trailer[:4].hex(),
            "value_hex": trailer_value.hex(),
            "value_u32_raw": trailer_value_u32,
            "value_f32_diagnostic": trailer_value_f32,
            "zero_value": trailer_value == b"\x00\x00\x00\x00",
            "semantics_status": "opaque final yrvl trailer value; u32/f32 views are diagnostic only",
        },
    }
