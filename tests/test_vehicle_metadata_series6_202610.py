from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORGANIZER = ROOT / "src" / "organizer"
METADATA = ORGANIZER / "fh6-vehicle-metadata.json"
CURRENT_MANIFEST = ORGANIZER / "fh6-vehicle-metadata-manifest-current.json"
LEGACY_MANIFEST = ORGANIZER / "fh6-vehicle-metadata-manifest.json"
LEGACY_METADATA = ORGANIZER / "fh6-vehicle-metadata-rev2.json"

EXPECTED_OCTOBER_2026 = {
    "432": "2004 Saleen S7",
    "1511": "1968 Holden Monaro GTS 327",
    "2157": "1970 Citroën 2CV",
    "2817": "2000 Honda Prelude Type SH",
    "3085": "2018 DeBerti Ford Mustang GT",
    "3593": "2024 Ferrari Purosangue",
    "3839": "2024 Mercedes-AMG GT 63 4Matic+",
    "3857": "1990 Eunos Cosmos",
    "4122": "2025 BMW M4 CS",
    "4188": "1972 Datsun 240Z #5 Rallye",
}


class Series6OctoberMetadataTests(unittest.TestCase):
    def test_current_package_identity_and_rows(self) -> None:
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        manifest = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(metadata["package_revision"], 3)
        self.assertEqual(metadata["source"]["updated"], "2026-10")
        self.assertEqual(metadata["generated_from"], "Vehicle DB Generator for FH6 0.6.3")
        self.assertEqual(len(metadata["records"]), 657)
        self.assertEqual(manifest["metadata"]["package_revision"], 3)
        self.assertEqual(manifest["metadata"]["source_updated"], "2026-10")
        self.assertEqual(manifest["metadata"]["record_count"], 657)
        self.assertEqual(
            manifest["metadata"]["records_sha256"],
            "0d4b201f4949e34407f32af073bc9245413ca858d6e515948178dafe3c1c7a6c",
        )
        for car_id, display_name in EXPECTED_OCTOBER_2026.items():
            self.assertEqual(metadata["records"][car_id]["display_name"], display_name)
        self.assertEqual(
            metadata["records"]["335"]["display_name"],
            "2002 Lotus Esprit V8",
        )
        self.assertEqual(
            metadata["records"]["3132"]["display_name"],
            "2018 MINI X-Raid John Cooper Works Buggy",
        )
        self.assertEqual(
            metadata["records"]["3735"]["display_name"],
            "2022 Subaru BRZS",
        )
        self.assertNotIn("3191", metadata["records"])

    def test_legacy_revision2_channel_remains_usable_by_old_clients(self) -> None:
        legacy_metadata_bytes = LEGACY_METADATA.read_bytes()
        legacy_metadata = json.loads(legacy_metadata_bytes.decode("utf-8"))
        legacy_manifest = json.loads(LEGACY_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(legacy_metadata_bytes).hexdigest(),
            "e86fabd9e07fda7074f88f47227028de99e60ce3b3634bb259add516e912a7c0",
        )
        self.assertEqual(legacy_metadata["package_revision"], 2)
        self.assertEqual(legacy_metadata["source"]["updated"], "2026-09-08")
        self.assertEqual(len(legacy_metadata["records"]), 647)
        self.assertEqual(legacy_manifest["metadata"]["package_revision"], 2)
        self.assertEqual(legacy_manifest["metadata"]["source_updated"], "2026-09-08")
        self.assertEqual(legacy_manifest["metadata"]["record_count"], 647)
        self.assertTrue(
            legacy_manifest["metadata"]["url"].endswith(
                "/src/organizer/fh6-vehicle-metadata-rev2.json"
            )
        )


if __name__ == "__main__":
    unittest.main()
