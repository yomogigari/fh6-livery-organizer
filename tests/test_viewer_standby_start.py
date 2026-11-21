"""Organizer の起動で Livery Viewer for FH6 の 3D プレビューを温めておく（2026-11-21）の確認。

- Viewer の設定（preview-settings.json の viewer_standby_with_organizer）がオン（既定）で、Organizer連携（URI）が
  登録されているときだけ、liveryorganizerpreviewforfh6://standby?pid=<この Organizer の番号> を開く。
- 設定がオフ・未登録・開けないときは何もしない（Organizer の動きは変えない）。
- 画面を出した後に、少し待ってから裏の糸で依頼を出す。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


def load_module(name: str, path: Path):
    organizer_dir = str(path.parent)
    if organizer_dir not in sys.path:
        sys.path.insert(0, organizer_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


organizer = load_module("livery_organizer_viewer_standby_test", ORGANIZER_SOURCE)


class ViewerStandbyStartTests(unittest.TestCase):
    def test_opens_standby_uri_when_enabled_and_registered(self) -> None:
        with (mock.patch.object(organizer, "_viewer_standby_enabled", return_value=True),
              mock.patch.object(organizer, "_viewer_uri_registered", return_value=True) as registered,
              mock.patch.object(organizer.os, "startfile", create=True) as startfile):
            self.assertTrue(organizer.start_viewer_standby())
        registered.assert_called_once_with("liveryorganizerpreviewforfh6")
        startfile.assert_called_once_with(f"liveryorganizerpreviewforfh6://standby?pid={os.getpid()}")

    def test_does_nothing_when_off_unregistered_or_failing(self) -> None:
        cases = [(False, True, None), (True, False, None), (True, True, OSError("no handler"))]
        for enabled, registered, error in cases:
            with (mock.patch.object(organizer, "_viewer_standby_enabled", return_value=enabled),
                  mock.patch.object(organizer, "_viewer_uri_registered", return_value=registered),
                  mock.patch.object(organizer.os, "startfile", create=True, side_effect=error) as startfile):
                self.assertFalse(organizer.start_viewer_standby())
            if not (enabled and registered):
                startfile.assert_not_called()

    def test_setting_defaults_to_on(self) -> None:
        import organizer_preview_database
        for stored, expected in (({}, True), ({"viewer_standby_with_organizer": False}, False),
                                 ({"viewer_standby_with_organizer": True}, True),
                                 ({"viewer_standby_with_organizer": "no"}, True)):
            with mock.patch.object(organizer_preview_database, "load_shared_settings", return_value=stored):
                self.assertEqual(organizer._viewer_standby_enabled(), expected, stored)

    def test_scheduled_after_the_window_without_blocking(self) -> None:
        calls = []

        class FakeRoot:
            def after(self, delay, callback):
                calls.append(delay)
                callback()

        with mock.patch.object(organizer, "start_viewer_standby") as start:
            organizer.schedule_viewer_standby(FakeRoot())
            for thread in list(organizer.threading.enumerate()):
                if thread.name == "viewer-standby":
                    thread.join(5)
        self.assertEqual(calls, [organizer.VIEWER_STANDBY_DELAY_MS])
        start.assert_called_once_with()
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        main = source[source.index("def main() -> int:"):]
        self.assertLess(main.index("App(root)"), main.index("schedule_viewer_standby(root)"))
        self.assertLess(main.index("schedule_viewer_standby(root)"), main.index("root.mainloop()"))


if __name__ == "__main__":
    unittest.main()
