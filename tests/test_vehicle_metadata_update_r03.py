from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "src" / "organizer" / "vehicle_metadata_update.py"
BUNDLED_METADATA = REPO_ROOT / "src" / "organizer" / "fh6-vehicle-metadata.json"
BUNDLED_MANIFEST = REPO_ROOT / "src" / "organizer" / "fh6-vehicle-metadata-manifest.json"

spec = importlib.util.spec_from_file_location("vehicle_metadata_update_r03_target", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def metadata_bytes(*, revision: int | None, display_name: str = "2022 Subaru BRZ", updated: str = "2026-08-13") -> bytes:
    payload = {
        "schema_version": 1,
        "dataset": "fh6-official-vehicle-metadata",
        "source": {
            "name": "Forza official car list",
            "url": "https://forza.net/fh6cars",
            "updated": updated,
        },
        "generated_from": "r03-test",
        "records": {
            "3735": {
                "year": 2022,
                "make": "Subaru",
                "model": "BRZ",
                "display_name": display_name,
            }
        },
    }
    if revision is not None:
        payload["package_revision"] = revision
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def manifest_bytes(data: bytes, *, revision: int | None) -> bytes:
    state = mod.inspect_metadata_bytes(data, label="test metadata")
    metadata = {
        "dataset": "fh6-official-vehicle-metadata",
        "schema_version": 1,
        "source_updated": state["source_updated"],
        "record_count": state["record_count"],
        "records_sha256": state["records_sha256"],
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "file_size": len(data),
        "generated_from": "r03-test",
        "url": "https://example.invalid/fh6-vehicle-metadata.json",
    }
    if revision is not None:
        metadata["package_revision"] = revision
    payload = {
        "schema_version": 1,
        "dataset": "fh6-vehicle-metadata-manifest",
        "metadata": metadata,
        "compatibility": {"metadata_schema_version": 1},
        "update_policy": {"mode": "optional"},
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class PackageRevisionTests(unittest.TestCase):
    def test_bundled_pair_uses_current_package_revision(self) -> None:
        metadata = BUNDLED_METADATA.read_bytes()
        manifest = BUNDLED_MANIFEST.read_bytes()
        metadata_state = mod.inspect_metadata_bytes(metadata, label="bundled metadata")
        manifest_state = mod.validate_manifest_bytes(manifest)
        self.assertEqual(metadata_state["package_revision"], 2)
        self.assertEqual(manifest_state["package_revision"], 2)
        mod.validate_metadata_bytes_against_manifest(metadata, manifest_state)

    def test_same_source_date_higher_package_revision_is_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "local.json"
            local_path.write_bytes(metadata_bytes(revision=1))
            remote = metadata_bytes(revision=2, display_name="2022 Subaru BRZS")
            result = mod.check_vehicle_metadata_update_from_bytes(
                local_path,
                manifest_bytes(remote, revision=2),
            )
            self.assertEqual(result.status, mod.STATUS_UPDATE_AVAILABLE)
            self.assertEqual(result.local_package_revision, 1)
            self.assertEqual(result.remote_package_revision, 2)

    def test_legacy_remote_is_older_than_revisioned_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "local.json"
            local_path.write_bytes(metadata_bytes(revision=1))
            remote = metadata_bytes(revision=None)
            result = mod.check_vehicle_metadata_update_from_bytes(
                local_path,
                manifest_bytes(remote, revision=None),
            )
            self.assertEqual(result.status, mod.STATUS_REMOTE_OLDER)
            self.assertEqual(result.remote_package_revision, 0)

    def test_same_package_revision_different_content_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "local.json"
            local_path.write_bytes(metadata_bytes(revision=1))
            remote = metadata_bytes(revision=1, display_name="2022 Subaru BRZS")
            result = mod.check_vehicle_metadata_update_from_bytes(
                local_path,
                manifest_bytes(remote, revision=1),
            )
            self.assertEqual(result.status, mod.STATUS_REVIEW_REQUIRED)
            self.assertIn("same package revision", result.detail or "")

    def test_legacy_same_date_behavior_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "local.json"
            local_path.write_bytes(metadata_bytes(revision=None))
            remote = metadata_bytes(revision=None, display_name="2022 Subaru BRZS")
            result = mod.check_vehicle_metadata_update_from_bytes(
                local_path,
                manifest_bytes(remote, revision=None),
            )
            self.assertEqual(result.status, mod.STATUS_REVIEW_REQUIRED)
            self.assertIn("same source date", result.detail or "")

    def test_runtime_prefers_higher_revision_even_with_same_source_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled.json"
            cache = root / "cache" / "fh6-vehicle-metadata.json"
            bundled.write_bytes(metadata_bytes(revision=1))
            remote = metadata_bytes(revision=2, display_name="2022 Subaru BRZS")
            mod.cache_validated_metadata_package(
                cache,
                remote,
                manifest_bytes(remote, revision=2),
            )
            selected = mod.select_runtime_vehicle_metadata_path(
                cache,
                bundled_path=bundled,
            )
            self.assertEqual(selected, cache)


class TransactionTests(unittest.TestCase):
    def test_second_replace_failure_restores_previous_valid_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache" / "fh6-vehicle-metadata.json"
            old_metadata = metadata_bytes(revision=1)
            old_manifest = manifest_bytes(old_metadata, revision=1)
            mod.cache_validated_metadata_package(cache, old_metadata, old_manifest)

            new_metadata = metadata_bytes(revision=2, display_name="2022 Subaru BRZS")
            new_manifest = manifest_bytes(new_metadata, revision=2)
            calls = 0

            def fail_second_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("intentional second replace failure")
                os.replace(src, dst)

            with self.assertRaises(mod.VehicleMetadataUpdateError):
                mod.cache_validated_metadata_package(
                    cache,
                    new_metadata,
                    new_manifest,
                    replace_func=fail_second_replace,
                )

            manifest_path = mod.cached_vehicle_metadata_manifest_path(cache)
            self.assertEqual(cache.read_bytes(), old_metadata)
            self.assertEqual(manifest_path.read_bytes(), old_manifest)
            self.assertIsNotNone(mod._read_valid_cached_pair(cache, manifest_path))
            self.assertFalse(list(cache.parent.glob("*.stage-*")))
            self.assertFalse(list(cache.parent.glob("*.rollback-*")))

    def test_second_replace_failure_without_old_pair_leaves_no_live_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache" / "fh6-vehicle-metadata.json"
            new_metadata = metadata_bytes(revision=2, display_name="2022 Subaru BRZS")
            new_manifest = manifest_bytes(new_metadata, revision=2)
            calls = 0

            def fail_second_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("intentional second replace failure")
                os.replace(src, dst)

            with self.assertRaises(mod.VehicleMetadataUpdateError):
                mod.cache_validated_metadata_package(
                    cache,
                    new_metadata,
                    new_manifest,
                    replace_func=fail_second_replace,
                )

            manifest_path = mod.cached_vehicle_metadata_manifest_path(cache)
            self.assertFalse(cache.exists())
            self.assertFalse(manifest_path.exists())
            self.assertFalse(list(cache.parent.glob("*.stage-*")))
            self.assertFalse(list(cache.parent.glob("*.rollback-*")))

    def test_user_agent_is_not_tied_to_old_development_revision(self) -> None:
        self.assertEqual(
            mod.USER_AGENT,
            "Livery-Organizer-for-FH6/vehicle-metadata-updater",
        )
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn('User-Agent": "Livery-Organizer-for-FH6/0.4.59-r06', source)


if __name__ == "__main__":
    unittest.main()
