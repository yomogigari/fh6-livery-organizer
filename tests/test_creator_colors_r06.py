from __future__ import annotations

from pathlib import Path
import re
import runpy
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EN = ROOT / "src" / "organizer" / "locales" / "en.py"


class CreatorColorsR06Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.en = EN.read_text(encoding="utf-8")

    def test_fixed_creator_color_ids_are_persisted_not_arbitrary_rgb(self) -> None:
        self.assertIn(
            'const CREATOR_COLOR_STORAGE_KEY = "livery-organizer-for-fh6-creator-colors-v1";',
            self.text,
        )
        match = re.search(r"const CREATOR_COLOR_DEFS = Object\.freeze\(\{\{(.*?)\}\}\);", self.text, re.S)
        self.assertIsNotNone(match)
        block = match.group(1)
        for color_id in ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"):
            self.assertRegex(block, rf"\b{color_id}:\"#[0-9a-fA-F]{{6}}\"")
        self.assertNotIn("input type=\"color\"", self.text)

    def test_creator_identity_uses_exact_display_name(self) -> None:
        self.assertIn('return String(card?.dataset?.creatorDisplay || "").trim();', self.text)
        creator_fn = self.text[
            self.text.index("function creatorColorNameForCard"):
            self.text.index("function applyCreatorColorToCard")
        ]
        self.assertNotIn("toLowerCase", creator_fn)
        self.assertNotIn("casefold", creator_fn.lower())

    def test_creator_name_filter_remains_and_color_button_is_separate(self) -> None:
        self.assertIn('class="link-filter creator-name-button"', self.text)
        self.assertIn('class="creator-color-button"', self.text)
        self.assertIn('data-filter-type="creator"', self.text)
        self.assertIn('aria-label="作成者カラーを設定"', self.text)

    def test_creator_color_control_is_subtle_split_dot_and_chevron(self) -> None:
        self.assertIn('class="creator-color-dot" aria-hidden="true"></span>', self.text)
        self.assertIn('class="creator-color-chevron" aria-hidden="true">▾</span>', self.text)
        self.assertIn('aria-haspopup="dialog" aria-expanded="false"', self.text)
        marker = "v0.4.60-r06 — 作成者カラーの永続管理"
        start = self.text.index(marker)
        end = self.text.index("</style>", start)
        css = self.text[start:end]
        button_rule = re.search(r"\.creator-color-button\s*\{(.*?)\}", css, re.S)
        self.assertIsNotNone(button_rule)
        button_css = button_rule.group(1)
        self.assertIn("border:0;", button_css)
        self.assertIn("background:transparent;", button_css)
        self.assertIn("height:18px;", button_css)
        self.assertNotIn("border-radius:999px", button_css)
        dot_rule = re.search(r"\.creator-color-dot\s*\{(.*?)\}", css, re.S)
        self.assertIsNotNone(dot_rule)
        self.assertIn("width:8px;", dot_rule.group(1))
        self.assertIn("height:8px;", dot_rule.group(1))
        self.assertIn(".creator-color-chevron", css)

    def test_palette_expanded_state_tracks_open_and_close(self) -> None:
        self.assertIn('creatorColorPaletteOpener.setAttribute("aria-expanded", "true")', self.text)
        self.assertIn('opener.setAttribute("aria-expanded", "false")', self.text)

    def test_both_creator_display_locations_use_same_color_control(self) -> None:
        self.assertIn('<div class="fh6-creator-display" title="FH6画面の作成者">{creator_color_control_html}</div>', self.text)
        self.assertIn('<dd class="fh6-normal-creator-row">{creator_color_control_html}</dd>', self.text)

    def test_palette_has_clear_and_eight_fixed_choices(self) -> None:
        self.assertIn('id="creatorColorPalette"', self.text)
        self.assertIn('data-creator-color=""', self.text)
        for color_id in ("red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"):
            self.assertEqual(self.text.count(f'<button class="creator-color-option" type="button" data-creator-color="{color_id}"'), 1)
        self.assertIn('event.key !== "Escape"', self.text)
        self.assertIn('target?.closest?.(".creator-color-button")', self.text)

    def test_color_applies_to_all_cards_for_exact_creator(self) -> None:
        self.assertIn("cards.forEach(applyCreatorColorToCard);", self.text)
        self.assertIn("const name = creatorColorNameForCard(card);", self.text)
        self.assertIn("const colorId = name ? String(creatorColors[name] || \"\") : \"\";", self.text)

    def test_absent_creator_colors_are_not_pruned_against_current_cards(self) -> None:
        sanitizer = self.text[
            self.text.index("function sanitizeCreatorColorMap"):
            self.text.index("function loadCreatorColorMap")
        ]
        self.assertIn("Object.entries(value).forEach", sanitizer)
        self.assertNotIn("cards", sanitizer)
        self.assertNotIn("creatorFilter", sanitizer)
        self.assertIn("result[name] = colorId;", sanitizer)

    def test_visual_design_uses_creator_badge_and_thin_card_line_only(self) -> None:
        marker = "v0.4.60-r06 — 作成者カラーの永続管理"
        self.assertEqual(self.text.count(marker), 1)
        start = self.text.index(marker)
        end = self.text.index("</style>", start)
        css = self.text[start:end]
        self.assertIn(".card.creator-colored::after", css)
        self.assertIn("height:3px;", css)
        self.assertIn("background:var(--creator-color);", css)
        self.assertIn(".creator-color-badge.creator-colored", css)
        card_rule = re.search(r"\.card\.creator-colored\s*\{(.*?)\}", css, re.S)
        self.assertIsNotNone(card_rule)
        self.assertNotIn("background:", card_rule.group(1))

    def test_user_data_and_backup_schema_include_creator_colors(self) -> None:
        self.assertIn("const USERDATA_VERSION = 3;", self.text)
        self.assertIn("const BACKUP_STATUS_VERSION = 3;", self.text)
        self.assertGreaterEqual(self.text.count("creatorColors:buildCreatorColorBackupData()"), 2)
        self.assertIn("backupChangeCreatorColorCount", self.text)
        self.assertIn("summary.creatorColors", self.text)

    def test_restore_supports_merge_replace_and_legacy_missing_field(self) -> None:
        self.assertIn("const importedCreatorColors = sanitizeCreatorColorMap(payload?.creatorColors || {{}});", self.text)
        self.assertIn("? importedCreatorColors", self.text)
        self.assertIn("sanitizeCreatorColorMap({{...creatorColors, ...importedCreatorColors}})", self.text)
        self.assertIn("saveCreatorColorMap();", self.text)
        self.assertIn("applyCreatorColors();", self.text)

    def test_backup_diff_counts_creator_assignment_changes(self) -> None:
        self.assertIn("const previousCreatorColors = sanitizeCreatorColorMap(previousSnapshot.creatorColors || {{}});", self.text)
        self.assertIn("const currentCreatorColors = sanitizeCreatorColorMap(current.creatorColors || {{}});", self.text)
        self.assertIn("let creatorColors = 0;", self.text)
        self.assertIn("total = decisions + tagNote + favorites + review + creatorColors + scanState + other", self.text)

    def test_english_locale_resource_counts_match_i18n_audit(self) -> None:
        locale = runpy.run_path(str(EN))
        self.assertEqual(len(locale["REPORT_TEXT"]), 729)
        self.assertEqual(len(locale["REPORT_ATTR"]), 100)

    def test_english_resources_cover_palette_and_attribute(self) -> None:
        expected = {
            '"作成者カラー": "Creator color"',
            '"色なし": "No color"',
            '"赤": "Red"',
            '"オレンジ": "Orange"',
            '"黄": "Yellow"',
            '"緑": "Green"',
            '"シアン": "Cyan"',
            '"青": "Blue"',
            '"紫": "Purple"',
            '"ピンク": "Pink"',
            '"作成者カラーを設定": "Set creator color"',
        }
        for marker in expected:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.en)

    def test_help_documents_zero_paint_retention_and_backup(self) -> None:
        self.assertIn("現在のペイントが0件になっても設定は保持されます", self.text)
        self.assertIn("判定・メタデータ・作成者カラーに加えてUI状態とスキャン状態をJSONへ保存します", self.text)

    def test_no_creator_color_whole_card_background_rule(self) -> None:
        marker = "v0.4.60-r06 — 作成者カラーの永続管理"
        start = self.text.index(marker)
        end = self.text.index("</style>", start)
        css = self.text[start:end]
        self.assertNotRegex(css, r"\.card\.creator-colored\s*\{[^}]*background\s*:")


if __name__ == "__main__":
    unittest.main()
