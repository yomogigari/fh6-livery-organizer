#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Livery Organizer for FH6 - optional vehicle metadata update checker.

v0.4.59-r03:
- Explicit/manual check only.
- The local fh6-vehicle-metadata.json always remains the runtime source.
- No metadata download or replacement is performed.
- Network/manifest errors never modify local metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
import urllib.request


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_DATASET = "fh6-vehicle-metadata-manifest"
METADATA_SCHEMA_VERSION = 1
METADATA_DATASET = "fh6-official-vehicle-metadata"
SUPPORTED_UPDATE_POLICY = "optional"

DEFAULT_METADATA_URL = (
    "https://raw.githubusercontent.com/yomogigari/"
    "fh6-livery-organizer/main/src/organizer/fh6-vehicle-metadata.json"
)
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/yomogigari/"
    "fh6-livery-organizer/main/src/organizer/"
    "fh6-vehicle-metadata-manifest.json"
)

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_MANIFEST_BYTES = 256 * 1024

STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_REVIEW_REQUIRED = "review_required"
STATUS_REMOTE_OLDER = "remote_older"
STATUS_INCOMPATIBLE = "incompatible"
STATUS_CHECK_FAILED = "check_failed"


class VehicleMetadataUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class VehicleMetadataUpdateResult:
    status: str
    local_source_updated: str | None = None
    remote_source_updated: str | None = None
    local_file_sha256: str | None = None
    remote_file_sha256: str | None = None
    local_record_count: int | None = None
    remote_record_count: int | None = None
    manifest_url: str | None = None
    detail: str | None = None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_load_no_duplicates(data: bytes, *, label: str) -> Any:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise VehicleMetadataUpdateError(
                    f"{label}: duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VehicleMetadataUpdateError(
            f"{label}: JSON is not valid UTF-8"
        ) from exc

    try:
        return json.loads(text, object_pairs_hook=hook)
    except VehicleMetadataUpdateError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VehicleMetadataUpdateError(
            f"{label}: invalid JSON: {exc}"
        ) from exc


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise VehicleMetadataUpdateError(
            f"{label}: expected lowercase SHA-256"
        )
    return value


def _require_iso_date(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise VehicleMetadataUpdateError(f"{label}: expected YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise VehicleMetadataUpdateError(
            f"{label}: expected YYYY-MM-DD"
        ) from exc
    if parsed.isoformat() != value:
        raise VehicleMetadataUpdateError(f"{label}: expected YYYY-MM-DD")
    return value


def _metadata_records_fingerprint(records: dict[str, Any]) -> str:
    rows: list[list[object]] = []
    for key in sorted(records, key=lambda item: int(item)):
        raw = records[key]
        rows.append([
            int(key),
            raw["year"],
            raw["make"],
            raw["model"],
            raw["display_name"],
        ])
    canonical = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def inspect_local_metadata(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise VehicleMetadataUpdateError(
            f"local metadata cannot be read: {path}: {exc}"
        ) from exc

    payload = _json_load_no_duplicates(data, label="local metadata")
    if not isinstance(payload, dict):
        raise VehicleMetadataUpdateError("local metadata root must be an object")
    if payload.get("schema_version") != METADATA_SCHEMA_VERSION:
        raise VehicleMetadataUpdateError(
            "local metadata schema_version is unsupported"
        )
    if payload.get("dataset") != METADATA_DATASET:
        raise VehicleMetadataUpdateError(
            "local metadata dataset is unexpected"
        )

    source = payload.get("source")
    records = payload.get("records")
    if not isinstance(source, dict):
        raise VehicleMetadataUpdateError(
            "local metadata source must be an object"
        )
    if not isinstance(records, dict) or not records:
        raise VehicleMetadataUpdateError(
            "local metadata records must be a non-empty object"
        )

    source_updated = _require_iso_date(
        source.get("updated"),
        label="local metadata source.updated",
    )

    expected_fields = {"year", "make", "model", "display_name"}
    for key, raw in records.items():
        if not isinstance(key, str) or not key.isdecimal():
            raise VehicleMetadataUpdateError(
                f"local metadata invalid Car ID key: {key!r}"
            )
        car_id = int(key)
        if car_id <= 0 or str(car_id) != key:
            raise VehicleMetadataUpdateError(
                f"local metadata non-canonical Car ID key: {key!r}"
            )
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise VehicleMetadataUpdateError(
                f"local metadata Car ID {car_id}: invalid fields"
            )
        year = raw.get("year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise VehicleMetadataUpdateError(
                f"local metadata Car ID {car_id}: year must be an integer"
            )
        for field in ("make", "model", "display_name"):
            value = raw.get(field)
            if not isinstance(value, str) or not value:
                raise VehicleMetadataUpdateError(
                    f"local metadata Car ID {car_id}: invalid {field}"
                )

    return {
        "source_updated": source_updated,
        "record_count": len(records),
        "records_sha256": _metadata_records_fingerprint(records),
        "file_sha256": _sha256_bytes(data),
        "file_size": len(data),
    }


def _is_https_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def validate_manifest_bytes(data: bytes) -> dict[str, Any]:
    payload = _json_load_no_duplicates(data, label="manifest")
    if not isinstance(payload, dict):
        raise VehicleMetadataUpdateError("manifest root must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise VehicleMetadataUpdateError(
            "manifest schema_version is unsupported"
        )
    if payload.get("dataset") != MANIFEST_DATASET:
        raise VehicleMetadataUpdateError("manifest dataset is unexpected")

    metadata = payload.get("metadata")
    compatibility = payload.get("compatibility")
    policy = payload.get("update_policy")
    if not isinstance(metadata, dict):
        raise VehicleMetadataUpdateError(
            "manifest metadata must be an object"
        )
    if not isinstance(compatibility, dict):
        raise VehicleMetadataUpdateError(
            "manifest compatibility must be an object"
        )
    if not isinstance(policy, dict):
        raise VehicleMetadataUpdateError(
            "manifest update_policy must be an object"
        )

    if metadata.get("dataset") != METADATA_DATASET:
        raise VehicleMetadataUpdateError(
            "manifest metadata.dataset is unsupported"
        )
    if metadata.get("schema_version") != METADATA_SCHEMA_VERSION:
        raise VehicleMetadataUpdateError(
            "manifest metadata.schema_version is unsupported"
        )
    if compatibility.get("metadata_schema_version") != METADATA_SCHEMA_VERSION:
        raise VehicleMetadataUpdateError(
            "manifest compatibility metadata schema is unsupported"
        )
    if policy.get("mode") != SUPPORTED_UPDATE_POLICY:
        raise VehicleMetadataUpdateError(
            "manifest update_policy.mode is unsupported; "
            "r03 accepts optional only"
        )

    source_updated = _require_iso_date(
        metadata.get("source_updated"),
        label="manifest metadata.source_updated",
    )
    record_count = metadata.get("record_count")
    file_size = metadata.get("file_size")
    if (
        isinstance(record_count, bool)
        or not isinstance(record_count, int)
        or record_count < 1
    ):
        raise VehicleMetadataUpdateError(
            "manifest metadata.record_count must be a positive integer"
        )
    if (
        isinstance(file_size, bool)
        or not isinstance(file_size, int)
        or file_size < 1
    ):
        raise VehicleMetadataUpdateError(
            "manifest metadata.file_size must be a positive integer"
        )

    records_sha256 = _require_sha256(
        metadata.get("records_sha256"),
        label="manifest metadata.records_sha256",
    )
    file_sha256 = _require_sha256(
        metadata.get("file_sha256"),
        label="manifest metadata.file_sha256",
    )

    metadata_url = metadata.get("url")
    if metadata_url is not None:
        if not isinstance(metadata_url, str) or not _is_https_url(metadata_url):
            raise VehicleMetadataUpdateError(
                "manifest metadata.url must use https://"
            )

    return {
        "source_updated": source_updated,
        "record_count": record_count,
        "records_sha256": records_sha256,
        "file_sha256": file_sha256,
        "file_size": file_size,
        "metadata_url": metadata_url,
    }


def fetch_manifest_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_MANIFEST_BYTES,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> bytes:
    if not isinstance(url, str) or not _is_https_url(url):
        raise VehicleMetadataUpdateError(
            "manifest URL must use https:// and must not include credentials"
        )
    if timeout <= 0:
        raise VehicleMetadataUpdateError("timeout must be positive")
    if max_bytes < 1:
        raise VehicleMetadataUpdateError("max_bytes must be positive")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Livery-Organizer-for-FH6/0.4.59-r03",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not isinstance(final_url, str) or not _is_https_url(final_url):
                raise VehicleMetadataUpdateError(
                    "manifest redirect/final URL is not HTTPS"
                )
            data = response.read(max_bytes + 1)
    except VehicleMetadataUpdateError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise VehicleMetadataUpdateError(
            f"manifest fetch failed: {type(exc).__name__}: {exc}"
        ) from exc

    if len(data) > max_bytes:
        raise VehicleMetadataUpdateError(
            f"manifest exceeds {max_bytes} bytes"
        )
    return data


def compare_local_metadata_with_manifest(
    local_state: dict[str, Any],
    manifest_state: dict[str, Any],
    *,
    manifest_url: str | None = None,
) -> VehicleMetadataUpdateResult:
    common = dict(
        local_source_updated=local_state["source_updated"],
        remote_source_updated=manifest_state["source_updated"],
        local_file_sha256=local_state["file_sha256"],
        remote_file_sha256=manifest_state["file_sha256"],
        local_record_count=local_state["record_count"],
        remote_record_count=manifest_state["record_count"],
        manifest_url=manifest_url,
    )

    if manifest_state["file_sha256"] == local_state["file_sha256"]:
        if (
            manifest_state["source_updated"] != local_state["source_updated"]
            or manifest_state["record_count"] != local_state["record_count"]
            or manifest_state["records_sha256"] != local_state["records_sha256"]
            or manifest_state["file_size"] != local_state["file_size"]
        ):
            return VehicleMetadataUpdateResult(
                STATUS_REVIEW_REQUIRED,
                detail="manifest fields conflict with identical file SHA-256",
                **common,
            )
        return VehicleMetadataUpdateResult(
            STATUS_UP_TO_DATE,
            **common,
        )

    local_date = date.fromisoformat(local_state["source_updated"])
    remote_date = date.fromisoformat(manifest_state["source_updated"])

    if remote_date > local_date:
        return VehicleMetadataUpdateResult(
            STATUS_UPDATE_AVAILABLE,
            **common,
        )
    if remote_date < local_date:
        return VehicleMetadataUpdateResult(
            STATUS_REMOTE_OLDER,
            **common,
        )

    return VehicleMetadataUpdateResult(
        STATUS_REVIEW_REQUIRED,
        detail="same source date but metadata file SHA-256 differs",
        **common,
    )


def check_vehicle_metadata_update_from_bytes(
    local_metadata_path: Path,
    manifest_bytes: bytes,
    *,
    manifest_url: str | None = None,
) -> VehicleMetadataUpdateResult:
    try:
        local_state = inspect_local_metadata(local_metadata_path)
        manifest_state = validate_manifest_bytes(manifest_bytes)
        return compare_local_metadata_with_manifest(
            local_state,
            manifest_state,
            manifest_url=manifest_url,
        )
    except VehicleMetadataUpdateError as exc:
        return VehicleMetadataUpdateResult(
            STATUS_INCOMPATIBLE,
            manifest_url=manifest_url,
            detail=str(exc),
        )


def check_vehicle_metadata_update_from_file(
    local_metadata_path: Path,
    manifest_path: Path,
) -> VehicleMetadataUpdateResult:
    try:
        data = manifest_path.read_bytes()
    except OSError as exc:
        return VehicleMetadataUpdateResult(
            STATUS_CHECK_FAILED,
            detail=f"manifest file cannot be read: {exc}",
        )
    return check_vehicle_metadata_update_from_bytes(
        local_metadata_path,
        data,
        manifest_url=None,
    )


def check_vehicle_metadata_update(
    local_metadata_path: Path,
    manifest_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[..., bytes] | None = None,
) -> VehicleMetadataUpdateResult:
    """
    Check-only network path.

    This function never writes local_metadata_path and never downloads the
    metadata JSON described by the manifest.
    """
    try:
        if fetcher is None:
            manifest_bytes = fetch_manifest_bytes(
                manifest_url,
                timeout=timeout,
            )
        else:
            manifest_bytes = fetcher(
                manifest_url,
                timeout=timeout,
            )
    except VehicleMetadataUpdateError as exc:
        return VehicleMetadataUpdateResult(
            STATUS_CHECK_FAILED,
            manifest_url=manifest_url,
            detail=str(exc),
        )
    except Exception as exc:
        return VehicleMetadataUpdateResult(
            STATUS_CHECK_FAILED,
            manifest_url=manifest_url,
            detail=f"manifest fetch failed: {type(exc).__name__}: {exc}",
        )

    return check_vehicle_metadata_update_from_bytes(
        local_metadata_path,
        manifest_bytes,
        manifest_url=manifest_url,
    )



_GUI_TEXT = {
    "ja": {
        "button": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d",
        "checking": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u306e\u66f4\u65b0\u3092\u78ba\u8a8d\u3057\u3066\u3044\u307e\u3059\u2026",
        "title": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d",
        "update_note": (
            "\u3053\u306e\u958b\u767a\u7248\u3067\u306f\u66f4\u65b0\u306e\u901a\u77e5\u306e\u307f\u884c\u3044\u3001"
            "\u30c7\u30fc\u30bf\u306e\u81ea\u52d5\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u30fb\u7f6e\u63db\u306f\u884c\u3044\u307e\u305b\u3093\u3002"
        ),
    },
    "en": {
        "button": "Check vehicle data update",
        "checking": "Checking for a vehicle data update...",
        "title": "Vehicle data update check",
        "update_note": (
            "This development revision only reports the update. "
            "It does not automatically download or replace vehicle metadata."
        ),
    },
}


def update_gui_text(key: str, language: str | None) -> str:
    lang = "ja" if str(language or "").lower().startswith("ja") else "en"
    return _GUI_TEXT[lang].get(key, key)


def gui_update_presentation(
    result: VehicleMetadataUpdateResult,
    language: str | None = "ja",
) -> tuple[str, str, str]:
    kind = "info" if result.status == STATUS_UP_TO_DATE else "warning"
    title = update_gui_text("title", language)
    body = format_update_check_result(result, language)
    if result.status == STATUS_UPDATE_AVAILABLE:
        body += "\n\n" + update_gui_text("update_note", language)
    return kind, title, body


_CLI_TEXT = {
    "ja": {
        "check_help": (
            "\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u306e\u66f4\u65b0\u6709\u7121\u3092manifest\u3067\u78ba\u8a8d\u3057\u3066\u7d42\u4e86"
            "\uff08\u78ba\u8a8d\u306e\u307f\u3002\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u30fb\u7f6e\u63db\u306f\u884c\u308f\u306a\u3044\uff09"
        ),
        "url_help": (
            "\u66f4\u65b0\u78ba\u8a8d\u306b\u4f7f\u7528\u3059\u308bHTTPS manifest URL\u3002"
            "--check-vehicle-metadata-update \u3068\u4e00\u7dd2\u306b\u6307\u5b9a"
        ),
        "url_required": (
            "--check-vehicle-metadata-update \u306b\u306f "
            "--vehicle-metadata-manifest-url https://... \u306e\u6307\u5b9a\u304c\u5fc5\u8981\u3067\u3059\u3002"
        ),
    },
    "en": {
        "check_help": (
            "Check the vehicle metadata manifest and exit "
            "(check only; no metadata download or replacement)"
        ),
        "url_help": (
            "HTTPS manifest URL for --check-vehicle-metadata-update"
        ),
        "url_required": (
            "--check-vehicle-metadata-update requires "
            "--vehicle-metadata-manifest-url https://..."
        ),
    },
}


def update_cli_text(key: str, language: str | None) -> str:
    lang = "ja" if str(language or "").lower().startswith("ja") else "en"
    return _CLI_TEXT[lang].get(key, key)


def format_update_check_result(
    result: VehicleMetadataUpdateResult,
    language: str | None = "ja",
) -> str:
    japanese = str(language or "").lower().startswith("ja")

    if japanese:
        labels = {
            STATUS_UP_TO_DATE: "\u6700\u65b0\u3067\u3059",
            STATUS_UPDATE_AVAILABLE: "\u66f4\u65b0\u304c\u3042\u308a\u307e\u3059",
            STATUS_REVIEW_REQUIRED: "\u8981\u78ba\u8a8d",
            STATUS_REMOTE_OLDER: "\u53d6\u5f97\u5148\u304c\u30ed\u30fc\u30ab\u30eb\u3088\u308a\u53e4\u3044\u72b6\u614b\u3067\u3059",
            STATUS_INCOMPATIBLE: "manifest\u3092\u5b89\u5168\u306b\u5229\u7528\u3067\u304d\u307e\u305b\u3093",
            STATUS_CHECK_FAILED: "\u66f4\u65b0\u78ba\u8a8d\u306b\u5931\u6557\u3057\u307e\u3057\u305f",
        }
        lines = [
            f"\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d: "
            f"{labels.get(result.status, result.status)}"
        ]
        if result.local_source_updated:
            lines.append(
                f"\u30ed\u30fc\u30ab\u30eb\u57fa\u6e96\u65e5: {result.local_source_updated}"
            )
        if result.remote_source_updated:
            lines.append(
                f"\u53d6\u5f97\u5148\u57fa\u6e96\u65e5:   {result.remote_source_updated}"
            )
        if result.local_record_count is not None:
            lines.append(
                f"\u30ed\u30fc\u30ab\u30eb\u4ef6\u6570:   {result.local_record_count}"
            )
        if result.remote_record_count is not None:
            lines.append(
                f"\u53d6\u5f97\u5148\u4ef6\u6570:     {result.remote_record_count}"
            )
        if result.local_file_sha256:
            lines.append(
                f"\u30ed\u30fc\u30ab\u30ebSHA-256: {result.local_file_sha256}"
            )
        if result.remote_file_sha256:
            lines.append(
                f"\u53d6\u5f97\u5148SHA-256:   {result.remote_file_sha256}"
            )
        if result.detail:
            lines.append(f"\u8a73\u7d30: {result.detail}")
        lines.append(
            "\u3053\u306e\u78ba\u8a8d\u3067\u306f\u30ed\u30fc\u30ab\u30eb\u306e"
            "\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u3092\u5909\u66f4\u3057\u3066\u3044\u307e\u305b\u3093\u3002"
        )
        return "\n".join(lines)

    labels = {
        STATUS_UP_TO_DATE: "up to date",
        STATUS_UPDATE_AVAILABLE: "update available",
        STATUS_REVIEW_REQUIRED: "review required",
        STATUS_REMOTE_OLDER: "remote manifest is older than local metadata",
        STATUS_INCOMPATIBLE: "manifest cannot be used safely",
        STATUS_CHECK_FAILED: "update check failed",
    }
    lines = [
        f"Vehicle metadata update check: "
        f"{labels.get(result.status, result.status)}"
    ]
    if result.local_source_updated:
        lines.append(f"Local source date:  {result.local_source_updated}")
    if result.remote_source_updated:
        lines.append(f"Remote source date: {result.remote_source_updated}")
    if result.local_record_count is not None:
        lines.append(f"Local records:      {result.local_record_count}")
    if result.remote_record_count is not None:
        lines.append(f"Remote records:     {result.remote_record_count}")
    if result.local_file_sha256:
        lines.append(f"Local SHA-256:      {result.local_file_sha256}")
    if result.remote_file_sha256:
        lines.append(f"Remote SHA-256:     {result.remote_file_sha256}")
    if result.detail:
        lines.append(f"Detail: {result.detail}")
    lines.append("This check did not modify the local vehicle metadata.")
    return "\n".join(lines)
