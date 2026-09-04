from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "src" / "organizer" / "vehicle_metadata_update.py"

spec = importlib.util.spec_from_file_location(
    "vehicle_metadata_update_test_target",
    MODULE_PATH,
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def metadata_payload(*, updated: str = "2026-08-13", extra: bool = False) -> dict:
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


def write_json(path: Path, payload: dict) -> bytes:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(data)
    return data


def manifest_for_metadata(path: Path, *, policy: str = "optional") -> dict:
    local = mod.inspect_local_metadata(path)
    return {
        "schema_version": 1,
        "dataset": "fh6-vehicle-metadata-manifest",
        "metadata": {
            "dataset": "fh6-official-vehicle-metadata",
            "schema_version": 1,
            "source_updated": local["source_updated"],
            "record_count": local["record_count"],
            "records_sha256": local["records_sha256"],
            "file_sha256": local["file_sha256"],
            "file_size": local["file_size"],
        },
        "compatibility": {
            "metadata_schema_version": 1,
        },
        "update_policy": {
            "mode": policy,
        },
    }


def manifest_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


class VehicleMetadataUpdateTests(unittest.TestCase):
    def test_same_metadata_is_up_to_date_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "metadata.json"
            original = write_json(local, metadata_payload())
            before = hashlib.sha256(original).hexdigest()

            manifest = manifest_for_metadata(local)
            result = mod.check_vehicle_metadata_update_from_bytes(
                local, manifest_bytes(manifest)
            )

            self.assertEqual(result.status, mod.STATUS_UP_TO_DATE)
            self.assertEqual(hashlib.sha256(local.read_bytes()).hexdigest(), before)

    def test_newer_source_date_is_update_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            remote = root / "remote.json"
            write_json(local, metadata_payload(updated="2026-08-13"))
            write_json(remote, metadata_payload(updated="2026-09-01", extra=True))
            manifest = manifest_for_metadata(remote)

            result = mod.check_vehicle_metadata_update_from_bytes(
                local, manifest_bytes(manifest)
            )
            self.assertEqual(result.status, mod.STATUS_UPDATE_AVAILABLE)

    def test_same_date_different_sha_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            remote = root / "remote.json"
            write_json(local, metadata_payload(updated="2026-08-13"))
            write_json(remote, metadata_payload(updated="2026-08-13", extra=True))

            result = mod.check_vehicle_metadata_update_from_bytes(
                local,
                manifest_bytes(manifest_for_metadata(remote)),
            )
            self.assertEqual(result.status, mod.STATUS_REVIEW_REQUIRED)

    def test_older_remote_is_reported_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            remote = root / "remote.json"
            write_json(local, metadata_payload(updated="2026-09-01", extra=True))
            original = local.read_bytes()
            write_json(remote, metadata_payload(updated="2026-08-13"))

            result = mod.check_vehicle_metadata_update_from_bytes(
                local,
                manifest_bytes(manifest_for_metadata(remote)),
            )
            self.assertEqual(result.status, mod.STATUS_REMOTE_OLDER)
            self.assertEqual(local.read_bytes(), original)

    def test_required_policy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            write_json(local, metadata_payload())
            manifest = manifest_for_metadata(local, policy="required")

            result = mod.check_vehicle_metadata_update_from_bytes(
                local, manifest_bytes(manifest)
            )
            self.assertEqual(result.status, mod.STATUS_INCOMPATIBLE)

    def test_http_manifest_url_is_rejected_before_network(self) -> None:
        calls = []

        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("network must not be called")

        with self.assertRaises(mod.VehicleMetadataUpdateError):
            mod.fetch_manifest_bytes(
                "http://example.test/manifest.json",
                urlopen=forbidden,
            )
        self.assertEqual(calls, [])

    def test_network_failure_returns_check_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "local.json"
            original = write_json(local, metadata_payload())

            def fail(_url: str, *, timeout: float) -> bytes:
                raise mod.VehicleMetadataUpdateError("offline")

            result = mod.check_vehicle_metadata_update(
                local,
                "https://example.test/manifest.json",
                fetcher=fail,
            )
            self.assertEqual(result.status, mod.STATUS_CHECK_FAILED)
            self.assertEqual(local.read_bytes(), original)

    def test_manifest_over_maximum_is_rejected(self) -> None:
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return "https://example.test/manifest.json"
            def read(self, size):
                return b"x" * size

        def opener(_request, timeout):
            return Response()

        with self.assertRaises(mod.VehicleMetadataUpdateError):
            mod.fetch_manifest_bytes(
                "https://example.test/manifest.json",
                max_bytes=32,
                urlopen=opener,
            )

    def test_redirect_to_http_is_rejected(self) -> None:
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return "http://example.test/manifest.json"
            def read(self, size):
                return b"{}"

        def opener(_request, timeout):
            return Response()

        with self.assertRaises(mod.VehicleMetadataUpdateError):
            mod.fetch_manifest_bytes(
                "https://example.test/manifest.json",
                urlopen=opener,
            )

    def test_manifest_claiming_same_sha_with_conflicting_fields_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            write_json(local, metadata_payload())
            manifest = manifest_for_metadata(local)
            manifest["metadata"]["source_updated"] = "2026-09-01"

            result = mod.check_vehicle_metadata_update_from_bytes(
                local, manifest_bytes(manifest)
            )
            self.assertEqual(result.status, mod.STATUS_REVIEW_REQUIRED)

    def test_offline_manifest_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local.json"
            manifest_path = root / "manifest.json"
            write_json(local, metadata_payload())
            manifest_path.write_bytes(
                manifest_bytes(manifest_for_metadata(local))
            )

            result = mod.check_vehicle_metadata_update_from_file(
                local, manifest_path
            )
            self.assertEqual(result.status, mod.STATUS_UP_TO_DATE)


    def test_japanese_cli_text_is_readable(self) -> None:
        self.assertEqual(
            mod.update_cli_text("check_help", "ja"),
            "\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u306e\u66f4\u65b0\u6709\u7121\u3092manifest\u3067\u78ba\u8a8d\u3057\u3066\u7d42\u4e86"
            "\uff08\u78ba\u8a8d\u306e\u307f\u3002\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u30fb\u7f6e\u63db\u306f\u884c\u308f\u306a\u3044\uff09",
        )
        self.assertIn(
            "\u6307\u5b9a\u304c\u5fc5\u8981\u3067\u3059\u3002",
            mod.update_cli_text("url_required", "ja"),
        )

    def test_japanese_result_text_is_readable(self) -> None:
        result = mod.VehicleMetadataUpdateResult(
            mod.STATUS_UP_TO_DATE,
            local_source_updated="2026-08-13",
            remote_source_updated="2026-08-13",
            local_record_count=636,
            remote_record_count=636,
        )
        text = mod.format_update_check_result(result, "ja")
        self.assertIn(
            "\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u66f4\u65b0\u78ba\u8a8d: \u6700\u65b0\u3067\u3059",
            text,
        )
        self.assertIn(
            "\u30ed\u30fc\u30ab\u30eb\u57fa\u6e96\u65e5: 2026-08-13",
            text,
        )
        self.assertIn(
            "\u53d6\u5f97\u5148\u4ef6\u6570:     636",
            text,
        )
        self.assertIn(
            "\u3053\u306e\u78ba\u8a8d\u3067\u306f\u30ed\u30fc\u30ab\u30eb\u306e"
            "\u8eca\u7a2e\u30e1\u30bf\u30c7\u30fc\u30bf\u3092\u5909\u66f4\u3057\u3066\u3044\u307e\u305b\u3093\u3002",
            text,
        )

if __name__ == "__main__":
    unittest.main()
