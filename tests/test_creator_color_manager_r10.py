from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EN_LOCALE = ROOT / "src" / "organizer" / "locales" / "en.py"


class CreatorColorManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location("lo4fh6_r10_en", EN_LOCALE)
        assert spec and spec.loader
        cls.en = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.en)

    def test_manager_entry_point_and_modal_exist_once(self) -> None:
        self.assertEqual(self.text.count('id="creatorColorManagerAction"'), 1)
        self.assertEqual(self.text.count('id="creatorColorManagerModal"'), 1)
        self.assertIn('id="creatorColorManagerSearch"', self.text)
        self.assertIn('id="creatorColorManagerColoredOnly"', self.text)

    def test_manager_union_keeps_saved_zero_paint_creators(self) -> None:
        self.assertIn(
            'const names = new Set([...counts.keys(), ...Object.keys(creatorColors)]);',
            self.text,
        )
        self.assertIn('currentCount:Number(counts.get(name) || 0)', self.text)
        self.assertIn('entry.currentCount === 0 && Boolean(entry.colorId)', self.text)
        self.assertIn('"現在のペイントなし"', self.text)

    def test_manager_counts_current_report_cards_by_exact_creator_name(self) -> None:
        self.assertIn('const name = creatorColorNameForCard(card);', self.text)
        self.assertIn('counts.set(name, (counts.get(name) || 0) + 1);', self.text)
        self.assertIn('.sort((a,b) => a.localeCompare(b, REPORT_LOCALE))', self.text)

    def test_manager_search_and_colored_only_filter_are_independent(self) -> None:
        self.assertIn('const needle = normFilterValue(creatorColorManagerSearch?.value || "");', self.text)
        self.assertIn('if (coloredOnly && !entry.colorId) return false;', self.text)
        self.assertIn('return !needle || normFilterValue(entry.name).includes(needle);', self.text)
        self.assertIn('creatorColorManagerSearch?.addEventListener("input", renderCreatorColorManager);', self.text)

    def test_manager_exposes_none_plus_eight_fixed_colors(self) -> None:
        expected = ["", "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"]
        block = self.text.split('const CREATOR_COLOR_MANAGER_OPTIONS = Object.freeze([', 1)[1].split(']);', 1)[0]
        for color_id in expected:
            self.assertIn(f'["{color_id}",', block)
        self.assertEqual(block.count('["'), len(expected))

    def test_manager_uses_existing_persistence_function(self) -> None:
        self.assertIn('button.addEventListener("click", () => setCreatorColor(name, colorId));', self.text)
        self.assertIn('refreshCreatorColorManagerIfOpen();', self.text)
        self.assertIn('saveCreatorColorMap();', self.text)
        self.assertIn('applyCreatorColors();', self.text)
        self.assertIn('refreshBackupUi();', self.text)

    def test_manager_does_not_add_a_bulk_clear_action(self) -> None:
        manager_html = self.text.split('id="creatorColorManagerModal"', 1)[1].split('id="creatorColorPalette"', 1)[0]
        self.assertNotIn('全消去', manager_html)
        self.assertNotIn('clearAllCreator', self.text)

    def test_manager_has_responsive_and_dark_theme_styles(self) -> None:
        self.assertIn('.creator-color-manager-panel {{', self.text)
        self.assertIn('body.dark-theme .creator-color-manager-row.creator-colored {{', self.text)
        self.assertIn('@media (max-width:620px) {{', self.text)
        self.assertIn('grid-template-columns:1fr;', self.text)

    def test_manager_returns_modal_focus_to_visible_secondary_actions_toggle(self) -> None:
        self.assertIn(
            'openModal("creatorColorManagerModal", document.getElementById("secondaryActionsToggle") || event.currentTarget);',
            self.text,
        )

    def test_help_documents_manager_route_and_zero_paint_retention(self) -> None:
        self.assertIn('<b>作成者カラー管理</b>：', self.text)
        self.assertIn('<span class="help-path"><span>その他の操作</span> → <span>作成者カラー管理</span></span>', self.text)
        self.assertIn('作成者カラーを一覧から検索・変更・解除できます。', self.text)
        self.assertIn('「設定済みのみ」で色を設定した作成者だけに絞り込め', self.text)
        self.assertIn('「現在0件で保持」として確認できます。', self.text)

    def test_english_resources_cover_manager_ui(self) -> None:
        expected = {
            "作成者カラー管理": "Manage creator colors",
            "設定済みのみ": "Colored only",
            "現在の作成者": "Current creators",
            "カラー設定済み": "Colored creators",
            "現在0件で保持": "Saved with 0 current paints",
            "作成者カラー設定": "Creator color settings",
            "現在のペイントなし": "No current paints",
            "条件に一致する作成者がいません。": "No creators match the current conditions.",
            "では、作成者カラーを一覧から検索・変更・解除できます。「設定済みのみ」で色を設定した作成者だけに絞り込め、現在のペイントが0件でも保存済みの色設定があれば「現在0件で保持」として確認できます。": "From here, you can search, change, or remove creator colors in one list. Use Colored only to show creators with a saved color, and creators with no current paints remain visible under Saved with 0 current paints when a color setting is stored.",
        }
        for source, translated in expected.items():
            self.assertEqual(self.en.REPORT_TEXT.get(source), translated)


if __name__ == "__main__":
    unittest.main()
