from __future__ import annotations

import importlib.util
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
    def test_revision_is_first_post_release_revision(self):
        self.assertEqual(BRIDGE.APP_VERSION, "v0.0.26-r01")

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

    def test_foreground_safety_rechecks_current_title(self):
        with mock.patch.object(BRIDGE, "is_foreground_window", return_value=True), mock.patch.object(
            BRIDGE, "get_window_title", return_value="Forza Horizon 6"
        ):
            self.assertTrue(BRIDGE.is_foreground_fh6_window(123))

        with mock.patch.object(BRIDGE, "is_foreground_window", return_value=True), mock.patch.object(
            BRIDGE,
            "get_window_title",
            return_value="GitHub - yomogigari/fh6-livery-organizer: Forza Horizon 6",
        ):
            self.assertFalse(BRIDGE.is_foreground_fh6_window(123))

    def test_send_paths_use_strict_foreground_check(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("if not is_foreground_window(hwnd):", source)
        self.assertIn("if not is_foreground_fh6_window(hwnd):", source)
        self.assertIn("if is_foreground_fh6_window(hwnd):", source)

    def test_window_discovery_no_longer_uses_substring_match(self):
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("FH6_WINDOW_TITLE.casefold() in title.casefold()", source)
        self.assertIn("if is_fh6_window_title(title):", source)


if __name__ == "__main__":
    unittest.main()
