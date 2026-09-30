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

from organizer_preview_report_integration import (  # noqa: E402
    build_report_preview_manifest,
    resolve_preview_game_folder,
)


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


class Experimental3DPreviewGameRootR04Tests(unittest.TestCase):
    def test_install_root_descends_to_existing_content_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp) / "Forza Horizon 6"
            content = install / "Content"
            content.mkdir(parents=True)
            self.assertEqual(resolve_preview_game_folder(install), content.resolve())

    def test_existing_content_root_is_not_doubled(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "Content"
            content.mkdir()
            self.assertEqual(resolve_preview_game_folder(content), content.resolve())
            self.assertNotIn("Content\\Content", str(resolve_preview_game_folder(content)))

    def test_manifest_writes_content_asset_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "Forza Horizon 6"
            content = install / "Content"
            (content / "media" / "livery").mkdir(parents=True)
            # The real Preview Bridge reads this path relative to game_folder.
            (content / "media" / "livery" / "Vinyls.zip").write_bytes(b"fixture")
            source = root / "Livery_2542_20260823132127"
            source.mkdir()
            record = FakeRecord(
                "record-2542", "fingerprint-2542", str(source), str(source / "C_livery"),
                2542, "2017 Alfa Romeo Giulia Quadrifoglio", "kita ikuyo", "Vvynda", "livery-2542",
            )
            manifest_path, _ = build_report_preview_manifest(
                records=[record],
                game_root=install,
                report_path=root / "out" / "livery-organizer-for-fh6.html",
            )
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(data["environment"]["game_folder"]), content.resolve())
            self.assertTrue((Path(data["environment"]["game_folder"]) / "media" / "livery" / "Vinyls.zip").is_file())

    def test_missing_content_keeps_original_root_for_fail_soft_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "custom-game-root"
            root.mkdir()
            self.assertEqual(resolve_preview_game_folder(root), root.resolve())


if __name__ == "__main__":
    unittest.main()
