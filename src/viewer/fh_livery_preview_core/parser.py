from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path
from typing import Any


LIVERY_VLRC_LAYOUTS: dict[int, dict[str, int | str]] = {
    1: {
        "name": "legacy_v1_6_surface",
        "yrvl_offset": 0x019,
        "yrvl_version_offset": 0x01D,
        "owner_offset": 0x021,
        "state_offset": 0x029,
        "gyvl_size_offset": 0x02E,
        "gyvl_offset": 0x032,
        "surface_count": 6,
    },
    2: {
        "name": "fh6_v2_11_surface",
        "yrvl_offset": 0x01A,
        "yrvl_version_offset": 0x01E,
        "owner_offset": 0x022,
        "state_offset": 0x02A,
        "gyvl_size_offset": 0x02F,
        "gyvl_offset": 0x033,
        "surface_count": 11,
    },
}


class ParseError(ValueError):
    """Raised when a selected file does not match a supported save container."""


def read_u32le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ParseError(f"cannot read u32 at 0x{offset:X}; file has {len(data)} bytes")
    return struct.unpack_from("<I", data, offset)[0]


def livery_vlrc_layout(format_version: int) -> dict[str, int | str] | None:
    return LIVERY_VLRC_LAYOUTS.get(format_version)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_save_resource(
    path: Path,
    core_name: str,
    companions: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Resolve folder-based FH6 resources and flat FH4/FH5 file bundles."""
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        folder = resolved
        resource_name = folder.name
        core = find_case_insensitive_file(folder, core_name) or folder / core_name
        flat_bundle = False
    else:
        folder = resolved.parent
        core = resolved
        suffix = f".{core_name}"
        if resolved.name.lower().endswith(suffix.lower()):
            resource_name = resolved.name[: -len(suffix)]
            flat_bundle = True
        else:
            resource_name = folder.name
            flat_bundle = False

    result: dict[str, Any] = {
        "input": resolved,
        "folder": folder,
        "core": core,
        "resource_name": resource_name,
        "flat_bundle": flat_bundle,
    }
    for key, names in (companions or {}).items():
        candidates = [f"{resource_name}.{name}" if flat_bundle else name for name in names]
        result[key] = find_case_insensitive_file(folder, *candidates)
    return result


def find_case_insensitive_file(folder: Path, *names: str) -> Path | None:
    for name in names:
        direct = folder / name
        if direct.is_file():
            return direct
    try:
        files = {child.name.lower(): child for child in folder.iterdir() if child.is_file()}
    except OSError:
        return None
    return next((files[name.lower()] for name in names if name.lower() in files), None)


def parse_length_prefixed_utf16le_strings(data: bytes) -> list[dict[str, Any]]:
    strings: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for offset in range(0, max(0, len(data) - 4)):
        char_count = read_u32le(data, offset)
        byte_count = char_count * 2
        data_offset = offset + 4
        end = data_offset + byte_count
        if char_count <= 0 or char_count > 128 or end > len(data):
            continue
        try:
            text = data[data_offset:end].decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if not _looks_like_header_text(text) or (offset, char_count) in seen:
            continue
        seen.add((offset, char_count))
        strings.append(
            {
                "length_offset": f"0x{offset:03X}",
                "text_offset": f"0x{data_offset:03X}",
                "char_count": char_count,
                "byte_count": byte_count,
                "text": text,
            }
        )
    return strings


def _looks_like_header_text(text: str) -> bool:
    if not text or "\x00" in text:
        return False
    if any(ord(char) < 0x20 and char not in "\t\r\n" for char in text):
        return False
    return any(not char.isspace() for char in text)


def parse_header_file(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    strings = parse_length_prefixed_utf16le_strings(data)
    result: dict[str, Any] = {
        "size": len(data),
        "sha256": sha256_hex(data),
        "strings": strings,
    }
    if len(data) >= 4:
        result["format_version"] = read_u32le(data, 0)
    if strings:
        result["candidate_name"] = strings[0]["text"]
    if len(strings) >= 2:
        result["candidate_description_or_share_text"] = strings[1]["text"]
    if len(strings) >= 3:
        result["candidate_creator_gamertag"] = strings[-1]["text"]
    return result


def parse_layergroup_header_tail(data: bytes) -> dict[str, Any]:
    candidates = [
        offset
        for offset in range(max(0, len(data) - 28))
        if data[offset : offset + 2] == b"\x01\x02"
        and data[offset + 2 : offset + 9] == b"\x00" * 7
        and offset + 29 <= len(data)
    ]
    if not candidates:
        return {"state": "marker_not_found"}
    marker = candidates[-1]
    count_offset = marker + 9
    guid_offset = marker + 13
    if count_offset >= len(data) or guid_offset + 16 > len(data):
        return {"state": "truncated", "marker_offset": f"0x{marker:X}"}
    return {
        "state": "parsed",
        "layer_count": data[count_offset],
        "guid_offset": guid_offset,
        "guid_size": 16,
    }


def parse_vlrc_metadata(data: bytes) -> dict[str, Any]:
    if len(data) < 8 or data[:4] != b"vlrc":
        return {"state": "invalid_or_truncated"}
    format_version = read_u32le(data, 0x004)
    layout = livery_vlrc_layout(format_version)
    if layout is None:
        return {"state": "unsupported_format_version", "format_version": format_version}
    gyvl_offset = int(layout["gyvl_offset"])
    if len(data) < gyvl_offset + 4:
        return {"state": "invalid_or_truncated", "format_version": format_version}
    lock_state = read_u32le(data, 0x008)
    return {
        "state": "parsed",
        "format_version": format_version,
        "layout": layout["name"],
        "surface_count": layout["surface_count"],
        "origin_or_edit_lock_state": lock_state,
        "editability": {0: "editable", 1: "locked_or_external"}.get(lock_state, "unknown"),
        "car_id": read_u32le(data, 0x010),
        "gyvl_size": read_u32le(data, int(layout["gyvl_size_offset"])),
        "gyvl_magic_ok": data[gyvl_offset : gyvl_offset + 4] == b"gyvl",
    }


def parse_gyvl_metadata(data: bytes) -> dict[str, Any]:
    if len(data) < 0x024 or data[:4] != b"gyvl":
        return {"state": "invalid_or_truncated"}
    node_offset = 0x00C
    flags_offset = node_offset + 0x11
    flags = data[flags_offset]
    owner_present = bool(flags & 0x01)
    cursor = flags_offset + 1 + (4 if flags & 0x10 else 0) + (8 if owner_present else 0)
    if cursor + 6 > len(data):
        return {"state": "truncated_root_node", "format_version": read_u32le(data, 0x004)}
    return {
        "state": "parsed_root_only",
        "format_version": read_u32le(data, 0x004),
        "owner_field_present": owner_present,
        "editability": "locked_or_external" if owner_present else "editable",
        "direct_child_count": int.from_bytes(data[cursor : cursor + 2], "little"),
        "node_state": read_u32le(data, cursor + 2),
    }


def decompress_c_livery(path: Path) -> bytes:
    return decompress_zlib_wrapped_file(path, b"vlrc")


def decompress_c_group(path: Path) -> bytes:
    return decompress_zlib_wrapped_file(path, b"gyvl")


def decompress_zlib_wrapped_file(path: Path, expected_magic: bytes) -> bytes:
    data = path.read_bytes()
    if len(data) < 8:
        raise ParseError(f"{path.name} must be at least 8 bytes; got {len(data)} bytes")
    compressed_size = read_u32le(data, 0)
    decompressed_size = read_u32le(data, 4)
    if compressed_size != len(data) - 8:
        raise ParseError(f"{path.name} compressed size does not match its wrapper")
    try:
        payload = zlib.decompress(data[8:])
    except zlib.error as exc:
        raise ParseError(f"invalid {path.name} zlib payload: {exc}") from exc
    if len(payload) != decompressed_size:
        raise ParseError(f"{path.name} decompressed size does not match its wrapper")
    if payload[:4] != expected_magic:
        raise ParseError(f"{path.name} does not contain the expected {expected_magic!r} payload")
    return payload
