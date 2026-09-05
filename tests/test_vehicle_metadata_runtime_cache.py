from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile



HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "src" / "organizer" / "vehicle_metadata_update.py"

spec = importlib.util.spec_from_file_location(
    "vehicle_metadata_runtime_cache_test_target",
    MODULE_PATH,
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def payload(updated: str, *, extra: bool = False) -> dict:
    records = {
        "100": {
            "year": 2020,
            "make": "Toyota",
            "model": "GR Supra",
            "display_name": "2020 Toyota GR Supra",
        },
        "2574": {
            "year": 2554,
            "make": "AMG Transport Dynamics",
            "model": "M12S Warthog CST",
            "display_name": "2554 AMG Transport Dynamics M12S Warthog CST",
        },
    }
    if extra:
        records["5000"] = {
            "year": 2026,
            "make": "Example",
            "model": "New Car",
            "display_name": "2026 Example New Car",
        }
    return {
        "schema_version": 1,
        "dataset": "fh6-official-vehicle-metadata",
        "source": {
            "name": "Forza official car list",
            "url": "https://forza.net/fh6cars",
            "updated": updated,
        },
        "generated_from": "test",
        "records": records,
    }


def write_payload(path: Path, value: dict) -> bytes:
    data = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def fingerprint(records: dict) -> str:
    rows = [
        [
            int(car_id),
            item["year"],
            item["make"],
            item["model"],
            item["display_name"],
        ]
        for car_id, item in records.items()
    ]
    rows.sort(key=lambda row: row[0])
    canonical = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def manifest_for(data: bytes, value: dict) -> bytes:
    records = value["records"]
    manifest = {
        "schema_version": 1,
        "dataset": "fh6-vehicle-metadata-manifest",
        "metadata": {
            "dataset": "fh6-official-vehicle-metadata",
            "schema_version": 1,
            "source_updated": value["source"]["updated"],
            "record_count": len(records),
            "records_sha256": fingerprint(records),
            "file_sha256": hashlib.sha256(data).hexdigest(),
            "file_size": len(data),
            "url": "https://example.test/fh6-vehicle-metadata.json",
        },
        "compatibility": {
            "metadata_schema_version": 1,
        },
        "update_policy": {
            "mode": "optional",
        },
    }
    if value.get("curation") is not None:
        manifest["metadata"]["curation"] = value["curation"]
    return (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def install_cache(
    cache: Path,
    updated: str,
    *,
    extra: bool = False,
) -> bytes:
    value = payload(updated, extra=extra)
    data = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest = manifest_for(data, value)
    mod.cache_validated_metadata_package(
        cache,
        data,
        manifest,
    )
    return data


def test_newer_valid_cache_is_selected_without_network():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))
        install_cache(cache, "2026-09-01", extra=True)

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == cache


def test_missing_cache_manifest_falls_back_to_bundled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))
        write_payload(cache, payload("2026-09-01", extra=True))

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled


def test_tampered_cache_falls_back_to_bundled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))
        install_cache(cache, "2026-09-01", extra=True)
        cache.write_bytes(cache.read_bytes() + b" ")

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled


def test_older_valid_cache_falls_back_to_bundled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-09-01", extra=True))
        install_cache(cache, "2026-08-13")

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled


def test_same_date_different_cache_falls_back_to_bundled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))
        install_cache(cache, "2026-08-13", extra=True)

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled


def test_download_and_cache_persists_manifest_receipt():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        remote = root / "remote.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        value = payload("2026-09-01", extra=True)
        data = write_payload(remote, value)
        manifest = manifest_for(data, value)

        state = mod.download_and_cache_vehicle_metadata(
            manifest,
            cache,
            metadata_fetcher=lambda _url, *, timeout: data,
        )

        receipt = mod.cached_vehicle_metadata_manifest_path(cache)
        assert cache.read_bytes() == data
        assert receipt.read_bytes() == manifest
        assert state["file_sha256"] == hashlib.sha256(data).hexdigest()


def test_curated_cache_manifest_curation_must_match_metadata():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))

        value = payload("2026-09-01", extra=True)
        value["curation"] = {
            "in_game_vehicle_name_overrides": {
                "record_count": 1,
                "records_sha256": "1" * 64,
                "scope": "display_name",
                "basis": "FH6 in-game vehicle UI",
            }
        }
        data = (
            json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        manifest = manifest_for(data, value)

        mod.cache_validated_metadata_package(cache, data, manifest)
        receipt = mod.cached_vehicle_metadata_manifest_path(cache)
        receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_payload["metadata"]["curation"][
            "in_game_vehicle_name_overrides"
        ]["records_sha256"] = "2" * 64
        receipt.write_text(
            json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled


def test_invalid_receipt_falls_back_to_bundled():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundled = root / "bundled.json"
        cache = root / "cache" / "fh6-vehicle-metadata.json"

        write_payload(bundled, payload("2026-08-13"))
        install_cache(cache, "2026-09-01", extra=True)
        receipt = mod.cached_vehicle_metadata_manifest_path(cache)
        receipt.write_text("{}", encoding="utf-8")

        selected = mod.select_runtime_vehicle_metadata_path(
            cache,
            bundled_path=bundled,
        )
        assert selected == bundled
