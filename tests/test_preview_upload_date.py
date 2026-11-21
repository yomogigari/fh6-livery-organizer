"""プレビューで保存する画像の帯に書く、アップロード日の受け渡し（2026-11-21）。

レポートの記録の fh6_date_display（FH6 の画面・カードと同じ「日/月/年」）を、プレビューのマニフェストの
display.upload_date に入れ、Viewer が読む依頼にもそのまま渡る。日付の無い記録・古いマニフェストは空のまま。
合成のデータだけを使う。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
sys.path.insert(0, str(ORGANIZER_DIR))

from organizer_preview_handoff import request_from_manifest, request_record  # noqa: E402
from organizer_preview_report_integration import _record_mapping, build_report_preview_manifest  # noqa: E402


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
    fh6_date_display: str = ""


class PreviewUploadDateTests(unittest.TestCase):
    def build(self, date: str) -> tuple[dict, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Livery_3960_20260517131003"
            source.mkdir()
            game = root / "Content"
            game.mkdir()
            record = FakeRecord("paint-key-1", "fingerprint-1", str(source), str(source / "C_livery"), 3960,
                                "Synthetic Car", "Synthetic", "Creator", "livery-1", date)
            manifest_path, _uris = build_report_preview_manifest(
                records=[record], game_root=game, report_path=root / "out" / "report.html",
                fh6_instances=[{"ui_key": "paint-key-1", "position": "#001U", "slot_number": 1}],
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            request, _manifest = request_from_manifest(manifest_path, "paint-key-1")
        return manifest, request

    def test_report_record_date_reaches_viewer_request(self) -> None:
        manifest, request = self.build("20/11/2026")
        self.assertEqual(manifest["records"][0]["display"]["upload_date"], "20/11/2026")
        self.assertEqual(request["display"]["upload_date"], "20/11/2026")
        self.assertEqual(request["display"]["creator_name"], "Creator")

    def test_record_without_date_gives_empty_text(self) -> None:
        manifest, request = self.build("")
        self.assertEqual(manifest["records"][0]["display"]["upload_date"], "")
        self.assertEqual(request["display"]["upload_date"], "")

    def test_request_record_and_plain_record_mapping(self) -> None:
        self.assertEqual(request_record(source="C:/synthetic/Livery_1", car_id=1, upload_date=" 21/11/2026 ")
                         ["display"]["upload_date"], "21/11/2026")

        class Plain:
            ui_key = "k"
            fh6_date_display = "22/11/2026"

        self.assertEqual(_record_mapping(Plain())["fh6_date_display"], "22/11/2026")


if __name__ == "__main__":
    unittest.main()
