from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "src" / "navigator_bridge" / "navigator-bridge-for-fh6.py"


def load_bridge_module():
    name = "navigator_bridge_for_fh6_test"
    spec = importlib.util.spec_from_file_location(name, BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Bridge module could not be loaded: {BRIDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BRIDGE = load_bridge_module()


class NavigatorBridgeWindowDetectionTests(unittest.TestCase):
    def test_version_is_v0028(self):
        self.assertEqual(BRIDGE.APP_VERSION, "v0.0.28")

    def test_fh6_title_requires_exact_text_after_outer_whitespace(self):
        accepted = (
            "Forza Horizon 6",
            " Forza Horizon 6",
            "Forza Horizon 6 ",
            "   Forza Horizon 6   ",
        )
        for title in accepted:
            with self.subTest(title=title):
                self.assertTrue(BRIDGE.is_fh6_window_title(title))

    def test_fh6_title_rejects_partial_matches_and_other_windows(self):
        rejected = (
            "",
            "Forza Horizon 6 - Microsoft Edge",
            "GitHub - yomogigari/fh6-livery-organizer: PC版 Forza Horizon 6 のツールです。",
            "Livery Organizer for Forza Horizon 6",
            "Navigator Bridge for FH6 - Forza Horizon 6",
            "Forza Horizon 6 Settings",
            "Forza Horizon 60",
            "forza horizon 6",
            "\tForza Horizon 6",
            "Forza Horizon 6\n",
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertFalse(BRIDGE.is_fh6_window_title(title))


    def test_fh6_process_image_requires_known_game_executable(self):
        accepted = (
            r"C:\Program Files (x86)\Steam\steamapps\common\ForzaHorizon6\forzahorizon6.exe",
            r"C:\XboxGames\Forza Horizon 6\Content\ForzaHorizon6.exe",
            "forzahorizon6.exe",
        )
        for path in accepted:
            with self.subTest(path=path):
                self.assertTrue(BRIDGE.is_fh6_process_image_path(path))

        rejected = (
            None,
            "",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Windows\System32\notepad.exe",
            r"C:\Games\ForzaHorizon6\gamelaunchhelper.exe",
            r"C:\Games\ForzaHorizon6\forzahorizon60.exe",
        )
        for path in rejected:
            with self.subTest(path=path):
                self.assertFalse(BRIDGE.is_fh6_process_image_path(path))

    def test_combined_window_identity_requires_title_and_process(self):
        with mock.patch.object(BRIDGE, "get_window_title", return_value="Forza Horizon 6"), mock.patch.object(
            BRIDGE, "get_window_process_image_path", return_value=Path(r"C:\Games\ForzaHorizon6\forzahorizon6.exe")
        ):
            self.assertTrue(BRIDGE.is_fh6_window_identity(123))

        with mock.patch.object(BRIDGE, "get_window_title", return_value="Forza Horizon 6"), mock.patch.object(
            BRIDGE, "get_window_process_image_path", return_value=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        ):
            self.assertFalse(BRIDGE.is_fh6_window_identity(123))

        with mock.patch.object(BRIDGE, "get_window_title", return_value="Forza Horizon 6 - Microsoft Edge"), mock.patch.object(
            BRIDGE, "get_window_process_image_path", return_value=Path(r"C:\Games\ForzaHorizon6\forzahorizon6.exe")
        ):
            self.assertFalse(BRIDGE.is_fh6_window_identity(123))

    def test_unique_fh6_window_selector_requires_exactly_one_candidate(self):
        with self.assertRaisesRegex(RuntimeError, "見つかりません"):
            BRIDGE.select_unique_fh6_window([])

        self.assertEqual(
            BRIDGE.select_unique_fh6_window([(123, "Forza Horizon 6")]),
            (123, "Forza Horizon 6"),
        )

        with self.assertRaisesRegex(RuntimeError, "複数"):
            BRIDGE.select_unique_fh6_window(
                [(123, "Forza Horizon 6"), (456, "Forza Horizon 6")]
            )

    def test_guarded_movement_sender_rechecks_foreground_before_sendinput(self):
        with mock.patch.object(
            BRIDGE, "is_foreground_fh6_window", return_value=False
        ), mock.patch.object(BRIDGE, "send_movement_key") as sender:
            with self.assertRaisesRegex(RuntimeError, "移動キーを送信しません"):
                BRIDGE.send_fh6_movement_key(123, BRIDGE.VK_LEFT)
            sender.assert_not_called()

        with mock.patch.object(
            BRIDGE, "is_foreground_fh6_window", return_value=True
        ), mock.patch.object(BRIDGE, "send_movement_key") as sender:
            BRIDGE.send_fh6_movement_key(123, BRIDGE.VK_RIGHT)
            sender.assert_called_once_with(BRIDGE.VK_RIGHT)

    def test_all_runtime_movement_send_paths_use_foreground_guard(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        # One definition + one internal call in send_fh6_movement_key().
        # Runtime movement paths must not bypass the foreground guard.
        self.assertEqual(len(re.findall(r"(?<!fh6_)send_movement_key\(", source)), 2)
        self.assertGreaterEqual(source.count("send_fh6_movement_key(hwnd,"), 4)

    def test_gui_and_headless_paths_refuse_ambiguous_exact_title_candidates(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("select_unique_fh6_window(windows)"), 2)
        self.assertNotIn("hwnd, title = windows[0]", source)

    def test_foreground_safety_rechecks_current_identity(self):
        with mock.patch.object(BRIDGE, "is_foreground_window", return_value=True), mock.patch.object(
            BRIDGE, "is_fh6_window_identity", return_value=True
        ):
            self.assertTrue(BRIDGE.is_foreground_fh6_window(123))

        with mock.patch.object(BRIDGE, "is_foreground_window", return_value=True), mock.patch.object(
            BRIDGE, "is_fh6_window_identity", return_value=False
        ):
            self.assertFalse(BRIDGE.is_foreground_fh6_window(123))

    def test_send_paths_use_strict_foreground_check(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("if not is_foreground_window(hwnd):", source)
        self.assertIn("if not is_foreground_fh6_window(hwnd):", source)
        self.assertIn("if is_foreground_fh6_window(hwnd):", source)

    def test_window_discovery_requires_exact_title_and_process_image(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("FH6_WINDOW_TITLE.casefold() in title.casefold()", source)
        self.assertIn("if is_fh6_window_title(title) and is_fh6_process_image_path(", source)
        self.assertIn("get_window_process_image_path(hwnd)", source)


if __name__ == "__main__":
    unittest.main()
