from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class Fh6MoveTargetVisibilityR05Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_current_version_is_r08_while_r05_feature_remains(self) -> None:
        self.assertIn('VERSION = "0.4.60-r08"', self.text)
        self.assertIn("Livery Organizer for FH6 v0.4.60-r08", self.text)
        self.assertNotIn('VERSION = "0.4.60-r04"', self.text)

    def test_r05_affordance_block_is_present_once(self) -> None:
        marker = "v0.4.60-r05 — FH6位置番号のクリック視認性改善"
        self.assertEqual(self.text.count(marker), 1)

    def test_slot_and_position_controls_are_real_buttons(self) -> None:
        self.assertIn(
            '<button class="pill my-design-index fh6-move-target-trigger" type="button"',
            self.text,
        )
        self.assertIn(
            '<button class="pill fh6-my-design-position fh6-move-target-trigger" type="button"',
            self.text,
        )
        self.assertIn('class="fh6-location-button"', self.text)

    def test_clickable_segments_have_persistent_button_affordance(self) -> None:
        required = [
            ".pill.fh6-move-target-trigger:not(:disabled)",
            ".fh6-location-button:not(:disabled)",
            "cursor:pointer;",
            "box-shadow:inset 0 -2px 0",
            "transition:",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_fh6_position_segment_gets_stronger_visual_cue(self) -> None:
        required = [
            ".pill.fh6-my-design-position:not(:disabled)",
            ".fh6-location-button:last-child:not(:disabled)",
            'content:"›";',
            "font-weight:900;",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_hover_active_and_focus_feedback_are_explicit(self) -> None:
        self.assertIn("transform:translateY(-1px);", self.text)
        self.assertIn(":active:not(:disabled)", self.text)
        self.assertIn(":focus-visible", self.text)
        self.assertIn("outline-offset:2px;", self.text)

    def test_r05_position_color_uses_defined_canvas_text_reference(self) -> None:
        r05_start = self.text.index("v0.4.60-r05 — FH6位置番号のクリック視認性改善")
        r05_end = self.text.index("</style>", r05_start)
        block = self.text[r05_start:r05_end]
        self.assertNotIn("var(--text)", block)
        self.assertIn("color:color-mix(in srgb, var(--accent) 82%, CanvasText);", block)

    def test_selected_group_remains_visually_coherent(self) -> None:
        pattern = re.compile(
            r"\.fh6-move-target-group:has\(\.fh6-move-target-trigger\[aria-pressed=\"true\"\]\)"
            r".*?background:transparent;.*?color:white;.*?box-shadow:none;.*?transform:none;",
            re.S,
        )
        self.assertRegex(self.text, pattern)

    def test_compact_view_keeps_position_cue_without_extra_wording(self) -> None:
        self.assertIn("@media (max-width:540px)", self.text)
        self.assertIn("margin-left:2px;", self.text)
        # r05 must not add a translated label solely to explain clickability.
        r05_start = self.text.index("v0.4.60-r05 — FH6位置番号のクリック視認性改善")
        r05_end = self.text.index("</style>", r05_start)
        block = self.text[r05_start:r05_end]
        self.assertNotIn("クリックできます", block)
        self.assertNotIn("Click", block)


if __name__ == "__main__":
    unittest.main()
