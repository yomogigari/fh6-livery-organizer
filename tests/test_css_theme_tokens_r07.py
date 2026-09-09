from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class CssThemeTokensR07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_r07_css_cleanup_marker_is_present_once(self) -> None:
        self.assertEqual(self.text.count("v0.4.60-r07 — CSSテーマ参照の整理"), 1)

    def test_undefined_text_custom_property_is_fully_removed(self) -> None:
        self.assertNotIn("var(--text)", self.text)

    def test_navigator_reset_option_uses_canvas_text(self) -> None:
        match = re.search(r"\.fh6-navigator-reset-option\s*\{(.*?)\}", self.text, re.S)
        self.assertIsNotNone(match)
        self.assertIn("color:CanvasText;", match.group(1))

    def test_temp_delete_review_uses_canvas_text_mix(self) -> None:
        match = re.search(r"#fh6TempDeletedReview\s*\{(.*?)\}", self.text, re.S)
        self.assertIsNotNone(match)
        self.assertIn("color:color-mix(in srgb, #b42318 85%, CanvasText);", match.group(1))

    def test_temp_delete_action_uses_canvas_text_mix(self) -> None:
        match = re.search(r"\.fh6-temp-delete-action\s*\{(.*?)\}", self.text, re.S)
        self.assertIsNotNone(match)
        self.assertIn("color:color-mix(in srgb, #b42318 82%, CanvasText) !important;", match.group(1))


if __name__ == "__main__":
    unittest.main()
