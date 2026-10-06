from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
sys.path.insert(0, str(ORGANIZER_DIR))

import organizer_preview_database as dbresolver  # noqa: E402
from organizer_preview_handoff import request_from_manifest  # noqa: E402
from organizer_preview_report_integration import (  # noqa: E402
    build_report_preview_manifest,
    resolve_preview_game_folder,
)

REQUIRED_TABLE_NAMES = (
    "Data_Car",
    "Data_CarBody",
    "List_UpgradeCarBody",
    "List_UpgradeTireCompound",
)


def make_database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        for table in REQUIRED_TABLE_NAMES:
            connection.execute(f'CREATE TABLE "{table}" (Id INTEGER)')
        connection.commit()
    finally:
        connection.close()
    return path


class Experimental3DPreviewGameDbR05Tests(unittest.TestCase):
    def test_shared_database_is_added_without_making_it_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "LocalAppData"
            settings = local / "Livery Organizer for FH6" / "PreviewBridge" / "preview-settings.json"
            database = make_database(root / "vehicle-data.sqlite")
            dbresolver.remember_database(database, settings_file=settings)
            source = root / "source-reference"
            source.mkdir()
            content = root / "Content"
            content.mkdir()
            report = root / "report.html"
            record = {"ui_key": "record-reference", "source_dir": str(source), "car_id": 1000}

            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=False):
                manifest_path, _ = build_report_preview_manifest(
                    records=[record],
                    game_root=content,
                    report_path=report,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["environment"]["database"], str(database.resolve()))
            self.assertEqual(manifest["preview"]["wheel_placement"], "gamedb")

            empty_local = root / "EmptyLocalAppData"
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(empty_local), dbresolver.GAMEDB_ENV_VAR: ""},
                clear=False,
            ):
                manifest_path, _ = build_report_preview_manifest(
                    records=[record],
                    game_root=content,
                    report_path=root / "report-no-db.html",
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("database", manifest["environment"])

    def test_r04_content_root_resolution_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            install = Path(td) / "Forza Horizon 6"
            content = install / "Content"
            content.mkdir(parents=True)
            self.assertEqual(resolve_preview_game_folder(install), content.resolve())
            self.assertEqual(resolve_preview_game_folder(content), content.resolve())

    def test_request_round_trip_carries_database_and_guarded_placement_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            database = make_database(root / "vehicle-data.sqlite")
            source = root / "source-reference"
            source.mkdir()
            content = root / "Content"
            content.mkdir()
            manifest_path, _ = build_report_preview_manifest(
                records=[{"ui_key": "record-reference", "source_dir": str(source), "car_id": 1000}],
                game_root=content,
                report_path=root / "report.html",
                database_path=database,
                gamedb_car_body_ids={1000: 1000000},
                wheel_placement="gamedb",
                resolve_saved_database=False,
            )
            request, _ = request_from_manifest(manifest_path, "record-reference")
            self.assertEqual(request["environment"]["database"], str(database.resolve()))
            self.assertEqual(request["viewer"]["wheel_placement"], "gamedb")
            self.assertEqual(request["viewer"]["gamedb_car_body_id"], 1000000)

    def test_documentation_contains_no_specific_paint_identifier(self):
        text = (ROOT / "docs" / "3D-PREVIEW-GAMEDB.md").read_text(encoding="utf-8")
        import re
        self.assertIsNone(re.search(r"Livery_\d{3,4}_\d{14}", text))
        self.assertIsNone(re.search(r"\b\d{14}\b", text))
        self.assertNotIn("share code:", text.casefold())


if __name__ == "__main__":
    unittest.main()
