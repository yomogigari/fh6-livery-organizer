from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlparse

URI_SCHEME = "liveryorganizerpreviewforfh6"
URI_HOST = "open"
MANIFEST_FORMAT = "lo4fh6_organizer_preview_manifest_v1"
REQUEST_FORMAT = "lo4fh6_organizer_preview_request_v2"


def _text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


def stable_record_id(*, source: str | Path, car_id: int, explicit: str = "") -> str:
    explicit_text = _text(explicit)
    if explicit_text:
        return explicit_text
    canonical = f"{int(car_id)}\n{Path(source)}".encode("utf-8", errors="surrogatepass")
    return "preview-" + hashlib.sha256(canonical).hexdigest()[:20]


def request_record(
    *,
    source: str | Path,
    car_id: int,
    record_id: str = "",
    title: str = "",
    creator_name: str = "",
    vehicle_name: str = "",
    share_code: str = "",
    slot_label: str = "",
    list_name: str = "",
    output_key: str = "",
    quality: str = "4",
) -> dict[str, Any]:
    source_path = str(Path(source))
    resolved_record_id = stable_record_id(source=source_path, car_id=car_id, explicit=record_id)
    stable_output_key = _text(output_key) or resolved_record_id
    return {
        "record_id": resolved_record_id,
        "source": {"path": source_path},
        "vehicle": {
            "car_id": int(car_id),
            "vehicle_name": _text(vehicle_name),
        },
        "display": {
            "title": _text(title),
            "creator_name": _text(creator_name),
            "vehicle_name": _text(vehicle_name),
            "share_code": _text(share_code),
        },
        "organizer": {
            "record_id": resolved_record_id,
            "slot_label": _text(slot_label),
            "list_name": _text(list_name),
            "output_key": stable_output_key,
        },
        "viewer": {"quality": _text(quality) or "4"},
    }


def build_manifest(
    *,
    game_folder: str | Path,
    records: Iterable[dict[str, Any]],
    report_path: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    normalized_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        record_id = _text(record.get("record_id")) or _text(record.get("organizer", {}).get("record_id") if isinstance(record.get("organizer"), dict) else "")
        if not record_id:
            raise ValueError("Every preview manifest record requires record_id.")
        if record_id in seen:
            raise ValueError(f"Duplicate preview record_id: {record_id}")
        seen.add(record_id)
        normalized_records.append(record)
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT,
        "environment": {"game_folder": str(Path(game_folder))},
        "records": normalized_records,
    }
    if report_path:
        manifest["report"] = {"path": str(Path(report_path))}
    if output_root:
        manifest["preview"] = {"output_root": str(Path(output_root))}
    return manifest


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != MANIFEST_FORMAT:
        raise ValueError("Unsupported Organizer preview manifest.")
    if not isinstance(data.get("environment"), dict) or not _text(data["environment"].get("game_folder")):
        raise ValueError("Organizer preview manifest is missing environment.game_folder.")
    if not isinstance(data.get("records"), list):
        raise ValueError("Organizer preview manifest is missing records.")
    return data


def request_from_manifest(path: str | Path, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_manifest(path)
    requested_id = _text(record_id)
    for record in manifest["records"]:
        if not isinstance(record, dict):
            continue
        candidate = _text(record.get("record_id")) or _text(record.get("organizer", {}).get("record_id") if isinstance(record.get("organizer"), dict) else "")
        if candidate != requested_id:
            continue
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        vehicle = record.get("vehicle") if isinstance(record.get("vehicle"), dict) else {}
        display = record.get("display") if isinstance(record.get("display"), dict) else {}
        organizer = record.get("organizer") if isinstance(record.get("organizer"), dict) else {}
        viewer = record.get("viewer") if isinstance(record.get("viewer"), dict) else {}
        request = {
            "format": REQUEST_FORMAT,
            "source": {"path": _text(source.get("path"))},
            "environment": {"game_folder": _text(manifest["environment"].get("game_folder"))},
            "vehicle": {
                "car_id": int(vehicle.get("car_id")),
                "vehicle_name": _text(vehicle.get("vehicle_name")),
            },
            "viewer": {"quality": _text(viewer.get("quality")) or "4"},
            "display": {
                "title": _text(display.get("title")),
                "creator_name": _text(display.get("creator_name")),
                "vehicle_name": _text(display.get("vehicle_name")) or _text(vehicle.get("vehicle_name")),
                "share_code": _text(display.get("share_code")),
            },
            "organizer": {
                "record_id": requested_id,
                "slot_label": _text(organizer.get("slot_label")),
                "list_name": _text(organizer.get("list_name")),
                "output_key": _text(organizer.get("output_key")) or requested_id,
            },
        }
        return request, manifest
    raise ValueError(f"Preview record not found in manifest: {record_id}")


def build_launch_uri(manifest_path: str | Path, record_id: str) -> str:
    query = urlencode({
        "manifest": str(Path(manifest_path).resolve()),
        "record": _text(record_id),
    })
    return f"{URI_SCHEME}://{URI_HOST}?{query}"


def parse_launch_uri(uri: str) -> tuple[Path, str]:
    parsed = urlparse(uri)
    if parsed.scheme.casefold() != URI_SCHEME.casefold() or parsed.netloc.casefold() != URI_HOST:
        raise ValueError("Unsupported Organizer preview URI.")
    query = parse_qs(parsed.query, keep_blank_values=False)
    manifest_values = query.get("manifest") or []
    record_values = query.get("record") or []
    if len(manifest_values) != 1 or len(record_values) != 1:
        raise ValueError("Organizer preview URI requires one manifest and one record value.")
    manifest = Path(manifest_values[0])
    record = _text(record_values[0])
    if not record:
        raise ValueError("Organizer preview URI record is empty.")
    return manifest, record
