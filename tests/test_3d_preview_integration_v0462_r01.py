from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
sys.path.insert(0, str(ORGANIZER_DIR))

from organizer_preview_handoff import request_from_manifest  # noqa: E402
from organizer_preview_report_integration import build_report_preview_manifest  # noqa: E402

SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"


@dataclass
class FakeRecord:
    ui_key: str
    fingerprint: str
    source_dir: str
    c_livery_path: str
    car_id: int
    vehicle_display_name: str
    title: str
    creator: str
    livery_id: str


class Experimental3DPreviewIntegrationR01Tests(unittest.TestCase):
    def test_report_manifest_round_trip_uses_existing_ui_key_and_fh6_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Livery_3960_20260517131003"
            source.mkdir()
            report = root / "out" / "livery-organizer-for-fh6.html"
            report.parent.mkdir()
            game = root / "Content"
            game.mkdir()
            record = FakeRecord(
                "paint-key-1", "fingerprint-1", str(source), str(source / "C_livery"),
                3960, "1994 Subaru Vivio RX-R", "Preview Test", "Creator", "livery-1",
            )
            instance = {"ui_key": "paint-key-1", "position": "#001U", "slot_number": 1}

            manifest_path, uris = build_report_preview_manifest(
                records=[record],
                game_root=game,
                report_path=report,
                fh6_instances=[instance],
            )

            self.assertEqual(manifest_path.name, "livery-organizer-preview-manifest.json")
            parsed = urlparse(uris["paint-key-1"])
            self.assertEqual(parsed.scheme, "liveryorganizerpreviewforfh6")
            query = parse_qs(parsed.query)
            self.assertEqual(query["record"], ["paint-key-1"])

            request, manifest = request_from_manifest(manifest_path, "paint-key-1")
            self.assertEqual(request["vehicle"]["car_id"], 3960)
            self.assertEqual(request["organizer"]["slot_label"], "#001U")
            self.assertEqual(request["source"]["path"], str(source))
            self.assertEqual(Path(manifest["report"]["path"]), report.resolve())

    def test_duplicate_content_records_remain_distinct_by_ui_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "Content"
            game.mkdir()
            source_a = root / "Livery_A"
            source_b = root / "Livery_B"
            source_a.mkdir(); source_b.mkdir()
            records = [
                FakeRecord("same--a", "same", str(source_a), "", 3960, "Vivio", "A", "X", "A"),
                FakeRecord("same--b", "same", str(source_b), "", 3960, "Vivio", "B", "X", "B"),
            ]
            manifest_path, uris = build_report_preview_manifest(
                records=records,
                game_root=game,
                report_path=root / "report.html",
            )
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual([item["record_id"] for item in data["records"]], ["same--a", "same--b"])
            self.assertEqual(set(uris), {"same--a", "same--b"})

    def test_organizer_source_has_fail_soft_card_and_modal_preview_path(self):
        source = SOURCE.read_text(encoding="utf-8")
        for marker in (
            "experimental_3d_preview_enabled",
            "experimental_3d_preview_error",
            "preview_launch_uris.get(record_key",
            "data-preview-uri=",
            "3Dプレビュー（実験）",
            "preview3dLinkHtml",
            "REPORT_PREVIEW_3D_LABEL",
        ):
            self.assertIn(marker, source)
        self.assertGreaterEqual(source.count("${{preview3dHtml}}"), 2)


if __name__ == "__main__":
    unittest.main()
