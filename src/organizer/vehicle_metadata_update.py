#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Livery Organizer for FH6 - optional vehicle metadata update checker.

v0.4.59-r12:
- Explicit/manual check and optional verified cache download remain unchanged.
- Public vehicle metadata may include audited FH6 in-game display-name curation.
- Metadata and manifest curation provenance must agree exactly.
- Network/manifest errors never modify bundled metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
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

CURATION_OVERRIDE_KEY = "in_game_vehicle_name_overrides"
CURATION_OVERRIDE_SCOPE = "display_name"
CURATION_OVERRIDE_BASIS = "FH6 in-game vehicle UI"

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



def validate_vehicle_metadata_curation(
    curation: object,
    *,
    label: str,
) -> dict[str, Any] | None:
    """
    Validate optional public-safe FH6 in-game vehicle-name curation provenance.

    Older metadata/manifest files without curation remain compatible.
    """
    if curation is None:
        return None
    if not isinstance(curation, dict):
        raise VehicleMetadataUpdateError(
            f"{label}: curation must be an object"
        )
    if set(curation) != {CURATION_OVERRIDE_KEY}:
        raise VehicleMetadataUpdateError(
            f"{label}: curation has unsupported keys"
        )

    override = curation.get(CURATION_OVERRIDE_KEY)
    if not isinstance(override, dict):
        raise VehicleMetadataUpdateError(
            f"{label}: curation.{CURATION_OVERRIDE_KEY} must be an object"
        )

    expected_fields = {"record_count", "records_sha256", "scope", "basis"}
    if set(override) != expected_fields:
        raise VehicleMetadataUpdateError(
            f"{label}: curation.{CURATION_OVERRIDE_KEY} has invalid fields"
        )

    record_count = override.get("record_count")
    if (
        isinstance(record_count, bool)
        or not isinstance(record_count, int)
        or record_count < 1
    ):
        raise VehicleMetadataUpdateError(
            f"{label}: curation.{CURATION_OVERRIDE_KEY}.record_count "
            "must be a positive integer"
        )

    records_sha256 = _require_sha256(
        override.get("records_sha256"),
        label=(
            f"{label}: curation.{CURATION_OVERRIDE_KEY}.records_sha256"
        ),
    )
    if override.get("scope") != CURATION_OVERRIDE_SCOPE:
        raise VehicleMetadataUpdateError(
            f"{label}: curation.{CURATION_OVERRIDE_KEY}.scope "
            f"must be {CURATION_OVERRIDE_SCOPE!r}"
        )
    if override.get("basis") != CURATION_OVERRIDE_BASIS:
        raise VehicleMetadataUpdateError(
            f"{label}: curation.{CURATION_OVERRIDE_KEY}.basis "
            f"must be {CURATION_OVERRIDE_BASIS!r}"
        )

    return {
        CURATION_OVERRIDE_KEY: {
            "record_count": record_count,
            "records_sha256": records_sha256,
            "scope": CURATION_OVERRIDE_SCOPE,
            "basis": CURATION_OVERRIDE_BASIS,
        }
    }


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
    curation = validate_vehicle_metadata_curation(
        payload.get("curation"),
        label="local metadata",
    )
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
        "curation": curation,
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
            "r06 accepts optional only"
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

    curation = validate_vehicle_metadata_curation(
        metadata.get("curation"),
        label="manifest metadata",
    )

    return {
        "source_updated": source_updated,
        "record_count": record_count,
        "records_sha256": records_sha256,
        "file_sha256": file_sha256,
        "file_size": file_size,
        "metadata_url": metadata_url,
        "curation": curation,
    }



MAX_METADATA_BYTES = 2 * 1024 * 1024
CACHED_METADATA_FILENAME = "fh6-vehicle-metadata.json"


def default_vehicle_metadata_cache_path(
    *,
    local_appdata: Path | None = None,
) -> Path:
    if local_appdata is not None:
        base = Path(local_appdata)
        return (
            base
            / "Livery-Organizer-for-FH6"
            / "cache"
            / CACHED_METADATA_FILENAME
        )

    if os.name == "nt":
        base_text = os.environ.get("LOCALAPPDATA")
        if base_text:
            return (
                Path(base_text)
                / "Livery-Organizer-for-FH6"
                / "cache"
                / CACHED_METADATA_FILENAME
            )

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return (
            Path(xdg)
            / "Livery-Organizer-for-FH6"
            / CACHED_METADATA_FILENAME
        )

    return (
        Path.home()
        / ".cache"
        / "Livery-Organizer-for-FH6"
        / CACHED_METADATA_FILENAME
    )


def inspect_metadata_bytes(data: bytes, *, label: str = "metadata") -> dict[str, Any]:
    payload = _json_load_no_duplicates(data, label=label)
    if not isinstance(payload, dict):
        raise VehicleMetadataUpdateError(f"{label}: root must be an object")
    if payload.get("schema_version") != METADATA_SCHEMA_VERSION:
        raise VehicleMetadataUpdateError(
            f"{label}: schema_version is unsupported"
        )
    if payload.get("dataset") != METADATA_DATASET:
        raise VehicleMetadataUpdateError(
            f"{label}: dataset is unexpected"
        )

    source = payload.get("source")
    records = payload.get("records")
    curation = validate_vehicle_metadata_curation(
        payload.get("curation"),
        label=label,
    )
    if not isinstance(source, dict):
        raise VehicleMetadataUpdateError(
            f"{label}: source must be an object"
        )
    if not isinstance(records, dict) or not records:
        raise VehicleMetadataUpdateError(
            f"{label}: records must be a non-empty object"
        )

    source_updated = _require_iso_date(
        source.get("updated"),
        label=f"{label} source.updated",
    )

    expected_fields = {"year", "make", "model", "display_name"}
    for key, raw in records.items():
        if not isinstance(key, str) or not key.isdecimal():
            raise VehicleMetadataUpdateError(
                f"{label}: invalid Car ID key: {key!r}"
            )
        car_id = int(key)
        if car_id <= 0 or str(car_id) != key:
            raise VehicleMetadataUpdateError(
                f"{label}: non-canonical Car ID key: {key!r}"
            )
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise VehicleMetadataUpdateError(
                f"{label}: Car ID {car_id}: invalid fields"
            )

        year = raw.get("year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise VehicleMetadataUpdateError(
                f"{label}: Car ID {car_id}: year must be an integer"
            )

        for field in ("make", "model", "display_name"):
            value = raw.get(field)
            if not isinstance(value, str) or not value:
                raise VehicleMetadataUpdateError(
                    f"{label}: Car ID {car_id}: invalid {field}"
                )

    return {
        "source_updated": source_updated,
        "record_count": len(records),
        "records_sha256": _metadata_records_fingerprint(records),
        "file_sha256": _sha256_bytes(data),
        "file_size": len(data),
        "curation": curation,
    }


def validate_metadata_bytes_against_manifest(
    data: bytes,
    manifest_state: dict[str, Any],
) -> dict[str, Any]:
    state = inspect_metadata_bytes(
        data,
        label="downloaded metadata",
    )

    expected = {
        "source_updated": manifest_state["source_updated"],
        "record_count": manifest_state["record_count"],
        "records_sha256": manifest_state["records_sha256"],
        "file_sha256": manifest_state["file_sha256"],
        "file_size": manifest_state["file_size"],
        "curation": manifest_state.get("curation"),
    }
    for key, expected_value in expected.items():
        if state[key] != expected_value:
            raise VehicleMetadataUpdateError(
                "downloaded metadata does not match manifest: "
                f"{key}: expected {expected_value!r}, found {state[key]!r}"
            )
    return state


def fetch_metadata_bytes(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = MAX_METADATA_BYTES,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> bytes:
    if not isinstance(url, str) or not _is_https_url(url):
        raise VehicleMetadataUpdateError(
            "metadata URL must use https:// and must not include credentials"
        )
    if timeout <= 0:
        raise VehicleMetadataUpdateError("timeout must be positive")
    if max_bytes < 1:
        raise VehicleMetadataUpdateError("max_bytes must be positive")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Livery-Organizer-for-FH6/0.4.59-r06",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not isinstance(final_url, str) or not _is_https_url(final_url):
                raise VehicleMetadataUpdateError(
                    "metadata redirect/final URL is not HTTPS"
                )
            data = response.read(max_bytes + 1)
    except VehicleMetadataUpdateError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise VehicleMetadataUpdateError(
            f"metadata fetch failed: {type(exc).__name__}: {exc}"
        ) from exc

    if len(data) > max_bytes:
        raise VehicleMetadataUpdateError(
            f"metadata exceeds {max_bytes} bytes"
        )
    return data


def cache_validated_metadata_bytes(
    destination: Path,
    data: bytes,
    manifest_state: dict[str, Any],
    *,
    replace_func: Callable[[str | bytes | Path, str | bytes | Path], None] = os.replace,
) -> dict[str, Any]:
    state = validate_metadata_bytes_against_manifest(
        data,
        manifest_state,
    )

    destination = Path(destination)
    if destination.exists() and destination.is_symlink():
        raise VehicleMetadataUpdateError(
            "metadata cache destination must not be a symbolic link"
        )

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VehicleMetadataUpdateError(
            f"metadata cache directory cannot be created: {exc}"
        ) from exc

    temp_path = destination.with_name(
        destination.name + f".tmp-{os.getpid()}"
    )
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError as exc:
            raise VehicleMetadataUpdateError(
                f"stale metadata cache temp file cannot be removed: {exc}"
            ) from exc

    try:
        with temp_path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        temp_data = temp_path.read_bytes()
        validate_metadata_bytes_against_manifest(
            temp_data,
            manifest_state,
        )

        replace_func(temp_path, destination)

        installed = destination.read_bytes()
        validate_metadata_bytes_against_manifest(
            installed,
            manifest_state,
        )
    except VehicleMetadataUpdateError:
        raise
    except OSError as exc:
        raise VehicleMetadataUpdateError(
            f"metadata cache write failed: {exc}"
        ) from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

    return state



CACHED_MANIFEST_FILENAME = "fh6-vehicle-metadata-manifest.json"


def cached_vehicle_metadata_manifest_path(
    metadata_path: Path,
) -> Path:
    metadata_path = Path(metadata_path)
    return metadata_path.with_name(CACHED_MANIFEST_FILENAME)


def _cache_manifest_bytes(
    destination: Path,
    manifest_bytes: bytes,
) -> None:
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise VehicleMetadataUpdateError(
            f"manifest exceeds {MAX_MANIFEST_BYTES} bytes"
        )
    validate_manifest_bytes(manifest_bytes)

    destination = Path(destination)
    if destination.exists() and destination.is_symlink():
        raise VehicleMetadataUpdateError(
            "metadata cache manifest destination must not be a symbolic link"
        )

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VehicleMetadataUpdateError(
            f"metadata cache manifest directory cannot be created: {exc}"
        ) from exc

    temp_path = destination.with_name(
        destination.name + f".tmp-{os.getpid()}"
    )
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError as exc:
            raise VehicleMetadataUpdateError(
                "stale metadata cache manifest temp file cannot be removed: "
                f"{exc}"
            ) from exc

    try:
        with temp_path.open("xb") as handle:
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        validate_manifest_bytes(temp_path.read_bytes())
        os.replace(temp_path, destination)
        validate_manifest_bytes(destination.read_bytes())
    except VehicleMetadataUpdateError:
        raise
    except OSError as exc:
        raise VehicleMetadataUpdateError(
            f"metadata cache manifest write failed: {exc}"
        ) from exc
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def cache_validated_metadata_package(
    destination: Path,
    metadata_bytes: bytes,
    manifest_bytes: bytes,
) -> dict[str, Any]:
    manifest_state = validate_manifest_bytes(manifest_bytes)
    metadata_url = manifest_state.get("metadata_url")
    if not isinstance(metadata_url, str) or not metadata_url:
        raise VehicleMetadataUpdateError(
            "manifest metadata.url is required for a cached metadata package"
        )

    state = cache_validated_metadata_bytes(
        destination,
        metadata_bytes,
        manifest_state,
    )

    manifest_path = cached_vehicle_metadata_manifest_path(destination)
    _cache_manifest_bytes(
        manifest_path,
        manifest_bytes,
    )

    selected = select_runtime_vehicle_metadata_path(
        destination,
        bundled_path=None,
        require_newer_than_bundled=False,
    )
    if selected != Path(destination):
        raise VehicleMetadataUpdateError(
            "cached metadata package could not be revalidated after installation"
        )

    return state


def select_runtime_vehicle_metadata_path(
    cache_path: Path | None = None,
    *,
    bundled_path: Path | None,
    require_newer_than_bundled: bool = True,
) -> Path:
    """
    Select a local runtime metadata file without network access.

    A cache is eligible only when both the metadata JSON and its cached manifest
    exist, neither path is a symbolic link, and the metadata exactly matches the
    cached manifest. When a bundled file is supplied, the cache must also have a
    strictly newer source date; same-date/different-content and older caches
    fall back to the bundled file.
    """
    bundled = None if bundled_path is None else Path(bundled_path)
    cache = (
        Path(cache_path)
        if cache_path is not None
        else default_vehicle_metadata_cache_path()
    )
    manifest_path = cached_vehicle_metadata_manifest_path(cache)
    fallback = bundled if bundled is not None else cache

    try:
        if not cache.is_file() or not manifest_path.is_file():
            return fallback
        if cache.is_symlink() or manifest_path.is_symlink():
            return fallback

        metadata_bytes = cache.read_bytes()
        manifest_bytes = manifest_path.read_bytes()

        if len(metadata_bytes) > MAX_METADATA_BYTES:
            return fallback
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            return fallback

        manifest_state = validate_manifest_bytes(manifest_bytes)
        metadata_url = manifest_state.get("metadata_url")
        if not isinstance(metadata_url, str) or not metadata_url:
            return fallback

        cache_state = validate_metadata_bytes_against_manifest(
            metadata_bytes,
            manifest_state,
        )

        if bundled is None or not require_newer_than_bundled:
            return cache

        bundled_state = inspect_metadata_bytes(
            bundled.read_bytes(),
            label="bundled metadata",
        )

        cache_date = date.fromisoformat(cache_state["source_updated"])
        bundled_date = date.fromisoformat(
            bundled_state["source_updated"]
        )

        if cache_date <= bundled_date:
            return bundled

        return cache
    except (
        OSError,
        ValueError,
        VehicleMetadataUpdateError,
    ):
        return fallback


def download_and_cache_vehicle_metadata(
    manifest_bytes: bytes,
    destination: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    metadata_fetcher: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    manifest_state = validate_manifest_bytes(manifest_bytes)
    metadata_url = manifest_state.get("metadata_url")
    if not isinstance(metadata_url, str) or not metadata_url:
        raise VehicleMetadataUpdateError(
            "manifest metadata.url is required to download metadata"
        )

    if metadata_fetcher is None:
        data = fetch_metadata_bytes(
            metadata_url,
            timeout=timeout,
        )
    else:
        data = metadata_fetcher(
            metadata_url,
            timeout=timeout,
        )

    return cache_validated_metadata_package(
        destination,
        data,
        manifest_bytes,
    )

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
            "User-Agent": "Livery-Organizer-for-FH6/0.4.59-r06",
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


def check_vehicle_metadata_update_with_manifest(
    local_metadata_path: Path,
    manifest_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[..., bytes] | None = None,
) -> tuple[VehicleMetadataUpdateResult, bytes | None]:
    """
    Check for an update and retain the exact manifest bytes that were checked.

    Retaining the bytes lets an explicit follow-up download validate against
    the same manifest the user approved. A later metadata change at the URL is
    therefore rejected by the manifest hashes instead of being silently used.
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
        return (
            VehicleMetadataUpdateResult(
                STATUS_CHECK_FAILED,
                manifest_url=manifest_url,
                detail=str(exc),
            ),
            None,
        )
    except Exception as exc:
        return (
            VehicleMetadataUpdateResult(
                STATUS_CHECK_FAILED,
                manifest_url=manifest_url,
                detail=f"manifest fetch failed: {type(exc).__name__}: {exc}",
            ),
            None,
        )

    result = check_vehicle_metadata_update_from_bytes(
        local_metadata_path,
        manifest_bytes,
        manifest_url=manifest_url,
    )
    return result, manifest_bytes


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
    result, _manifest_bytes = check_vehicle_metadata_update_with_manifest(
        local_metadata_path,
        manifest_url,
        timeout=timeout,
        fetcher=fetcher,
    )
    return result



_GUI_TEXT = {
    "ja": {
        "button": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d",
        "checking": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u306e\u66f4\u65b0\u3092\u78ba\u8a8d\u3057\u3066\u3044\u307e\u3059\u2026",
        "title": "\u8eca\u7a2e\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d",
        "update_note": (
            "\u66f4\u65b0\u30c7\u30fc\u30bf\u306f\u78ba\u8a8d\u5f8c\u306b\u3060\u3051\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u3057\u3001"
            "\u73fe\u5728\u5b9f\u884c\u4e2d\u306e\u8eca\u7a2e\u30c7\u30fc\u30bf\u306f\u5909\u66f4\u3057\u307e\u305b\u3093\u3002"
        ),
        "download_question": (
            "\u65b0\u3057\u3044\u8eca\u7a2e\u30c7\u30fc\u30bf\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u3057\u3001"
            "\u6b21\u56de\u8d77\u52d5\u304b\u3089\u4f7f\u7528\u3057\u307e\u3059\u304b\uff1f"
        ),
        "downloading": (
            "\u8eca\u7a2e\u30c7\u30fc\u30bf\u3092\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u3057\u3066\u691c\u8a3c\u3057\u3066\u3044\u307e\u3059\u2026"
        ),
        "download_success": (
            "\u8eca\u7a2e\u30c7\u30fc\u30bf\u3092\u691c\u8a3c\u3057\u3066\u4fdd\u5b58\u3057\u307e\u3057\u305f\u3002"
            "\u6b21\u56de\u8d77\u52d5\u304b\u3089\u65b0\u3057\u3044\u30c7\u30fc\u30bf\u3092\u4f7f\u7528\u3057\u307e\u3059\u3002"
        ),
        "download_failed": (
            "\u8eca\u7a2e\u30c7\u30fc\u30bf\u306e\u66f4\u65b0\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002"
            "\u73fe\u5728\u306e\u30c7\u30fc\u30bf\u306f\u5909\u66f4\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002"
        ),
    },
    "en": {
        "button": "Check vehicle data update",
        "checking": "Checking for a vehicle data update...",
        "title": "Vehicle data update check",
        "update_note": (
            "Update data is downloaded only after confirmation. "
            "The vehicle data used by the current process is not changed."
        ),
        "download_question": (
            "Download the new vehicle data and use it from the next startup?"
        ),
        "downloading": (
            "Downloading and validating the vehicle data..."
        ),
        "download_success": (
            "The vehicle data was validated and saved. "
            "The new data will be used from the next startup."
        ),
        "download_failed": (
            "The vehicle data update failed. "
            "The current data was not changed."
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
