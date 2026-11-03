from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "organizer" / "vehicle-metadata-update.py"
METADATA = ROOT / "src" / "organizer" / "fh6-vehicle-metadata.json"
CURRENT_MANIFEST = (
    ROOT / "src" / "organizer" / "fh6-vehicle-metadata-manifest-current.json"
)

spec = importlib.util.spec_from_file_location(
    "vehicle_metadata_month_precision_202610_target",
    MODULE,
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _state(updated: str, sha: str) -> dict[str, object]:
    return {
        "package_revision": 0,
        "source_updated": updated,
        "record_count": 1,
        "records_sha256": "a" * 64,
        "file_sha256": sha,
        "file_size": 100,
        "curation": None,
    }


class MonthPrecisionTests(unittest.TestCase):
    def test_bundled_metadata_accepts_month_precision(self) -> None:
        state = mod.inspect_local_metadata(METADATA)
        self.assertEqual(state["source_updated"], "2026-11")
        self.assertEqual(state["package_revision"], 4)
        self.assertEqual(state["record_count"], 667)

    def test_current_manifest_accepts_month_precision(self) -> None:
        state = mod.validate_manifest_bytes(CURRENT_MANIFEST.read_bytes())
        self.assertEqual(state["source_updated"], "2026-11")
        self.assertEqual(state["package_revision"], 4)
        self.assertEqual(state["record_count"], 667)

    def test_invalid_month_is_rejected(self) -> None:
        payload = json.loads(METADATA.read_text(encoding="utf-8"))
        payload["source"]["updated"] = "2026-13"
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        with self.assertRaises(mod.VehicleMetadataUpdateError):
            mod.inspect_metadata_bytes(data, label="invalid month metadata")

    def test_legacy_month_after_previous_day_is_newer(self) -> None:
        result = mod.compare_local_metadata_with_manifest(
            _state("2026-09-30", "1" * 64),
            _state("2026-10", "2" * 64),
        )
        self.assertEqual(result.status, mod.STATUS_UPDATE_AVAILABLE)

    def test_legacy_mixed_precision_same_month_requires_review(self) -> None:
        result = mod.compare_local_metadata_with_manifest(
            _state("2026-10-15", "1" * 64),
            _state("2026-10", "2" * 64),
        )
        self.assertEqual(result.status, mod.STATUS_REVIEW_REQUIRED)
        self.assertIn("same source period", result.detail or "")

    def test_day_precision_order_is_preserved(self) -> None:
        result = mod.compare_local_metadata_with_manifest(
            _state("2026-10-14", "1" * 64),
            _state("2026-10-15", "2" * 64),
        )
        self.assertEqual(result.status, mod.STATUS_UPDATE_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
