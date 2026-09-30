from __future__ import annotations

"""Build the report-side preview manifest planned for Organizer integration.

This module deliberately depends only on the stable handoff contract in
``organizer_preview_handoff.py``.  The production Organizer patch can therefore
stay small: pass the report records plus its already-resolved FH6 game root,
write one sibling JSON manifest, and place the generated launch URI on the
matching HTML card.
"""

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from organizer_preview_handoff import (
    build_launch_uri,
    build_manifest,
    request_record,
    write_manifest,
)

DEFAULT_MANIFEST_NAME = "livery-organizer-preview-manifest.json"
DEFAULT_CACHE_DIR_NAME = "preview-cache"


def _record_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    if is_dataclass(record):
        return asdict(record)
    data: dict[str, Any] = {}
    for name in (
        "ui_key",
        "fingerprint",
        "source_dir",
        "c_livery_path",
        "car_id",
        "vehicle_display_name",
        "title",
        "creator",
        "livery_id",
    ):
        if hasattr(record, name):
            data[name] = getattr(record, name)
    return data


def _text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


def _source_path(data: Mapping[str, Any]) -> Path:
    source_dir = _text(data.get("source_dir"))
    if source_dir:
        return Path(source_dir)
    c_livery = _text(data.get("c_livery_path"))
    if c_livery:
        return Path(c_livery)
    raise ValueError("Preview record is missing source_dir/c_livery_path.")


def _ui_key(data: Mapping[str, Any]) -> str:
    key = _text(data.get("ui_key")) or _text(data.get("fingerprint"))
    if not key:
        raise ValueError("Preview record is missing ui_key/fingerprint.")
    return key


def _instance_by_ui_key(instances: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for instance in instances:
        key = _text(instance.get("ui_key")) or _text(instance.get("fingerprint"))
        if not key or key in result:
            continue
        result[key] = instance
    return result


def resolve_preview_game_folder(game_root: str | Path) -> Path:
    """Return the FH6 asset root expected by the research Preview Bridge.

    Organizer's normal vehicle-asset scan may receive the installation root
    (for example an installation root ending in ``Forza Horizon 6``), while the Preview Viewer resolves
    ``media/livery/Vinyls.zip`` relative to the asset root under ``Content``.
    Preserve an already-resolved Content path and only descend once when the
    installation root actually contains a Content directory.
    """

    root = Path(game_root).resolve()
    if root.name.casefold() == "content":
        return root
    content = root / "Content"
    if content.is_dir():
        return content.resolve()
    return root


def build_report_preview_manifest(
    *,
    records: Iterable[Any],
    game_root: str | Path,
    report_path: str | Path,
    manifest_path: str | Path | None = None,
    preview_output_root: str | Path | None = None,
    fh6_instances: Iterable[Mapping[str, Any]] = (),
    quality: str = "4",
) -> tuple[Path, dict[str, str]]:
    """Write one preview manifest and return launch URIs indexed by Organizer UI key.

    ``fh6_instances`` is the same current-instance payload the Organizer report
    already builds for Navigator Bridge.  When present, its current slot label is
    copied into the preview request without re-deriving FH6 ordering.
    """

    report = Path(report_path).resolve()
    game = resolve_preview_game_folder(game_root)
    if not _text(game_root):
        raise ValueError("game_root is required for 3D preview integration.")

    destination = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else report.with_name(DEFAULT_MANIFEST_NAME)
    )
    cache_root = (
        Path(preview_output_root).resolve()
        if preview_output_root is not None
        else report.parent / DEFAULT_CACHE_DIR_NAME
    )

    instance_map = _instance_by_ui_key(fh6_instances)
    request_records: list[dict[str, Any]] = []
    ui_to_record_id: dict[str, str] = {}

    for record in records:
        data = _record_mapping(record)
        key = _ui_key(data)
        car_id = int(data.get("car_id") or 0)
        if car_id <= 0:
            raise ValueError(f"Preview record {key!r} has invalid car_id.")
        instance = instance_map.get(key) or {}
        slot_label = _text(instance.get("position")) or (
            f"#{int(instance.get('slot_number')):03d}"
            if str(instance.get("slot_number") or "").isdigit() and int(instance.get("slot_number") or 0) > 0
            else ""
        )
        request = request_record(
            source=_source_path(data),
            car_id=car_id,
            record_id=key,
            title=_text(data.get("title")),
            creator_name=_text(data.get("creator")),
            vehicle_name=_text(data.get("vehicle_display_name")),
            slot_label=slot_label,
            list_name="Livery Organizer for FH6 report",
            output_key=key,
            quality=quality,
        )
        request_records.append(request)
        ui_to_record_id[key] = request["record_id"]

    manifest = build_manifest(
        game_folder=game,
        records=request_records,
        report_path=report,
        output_root=cache_root,
    )
    write_manifest(destination, manifest)

    launch_uris = {
        key: build_launch_uri(destination, record_id)
        for key, record_id in ui_to_record_id.items()
    }
    return destination, launch_uris
