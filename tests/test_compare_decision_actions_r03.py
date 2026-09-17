from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class CompareDecisionActionsR03Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_r03_feature_marker_is_present_once(self) -> None:
        marker = "v0.4.61-r03 — 比較画面から整理状態を直接変更"
        self.assertEqual(self.text.count(marker), 1)

    def test_compare_decision_controls_offer_all_three_states(self) -> None:
        start = self.text.index("function compareDecisionButtonsHtml(card)")
        end = self.text.index("function compareCreatorLabel(card)", start)
        block = self.text[start:end]
        for state, label in (("keep", "残す"), ("delete", "削除候補"), ("undecided", "未決定")):
            with self.subTest(state=state):
                self.assertIn(f'data-compare-state="{state}"', block)
                self.assertIn(f'>{label}</button>', block)
        self.assertIn('aria-pressed=', block)
        self.assertIn('state === "keep" ? "active"', block)

    def test_shared_compare_renderer_includes_decision_controls(self) -> None:
        start = self.text.index("function renderCompareMembers(members, options = {{}})")
        end = self.text.index("function renderCompareModal(sourceCard)", start)
        block = self.text[start:end]
        self.assertIn("const decisionButtonsHtml = compareDecisionButtonsHtml(member);", block)
        self.assertIn("${{decisionButtonsHtml}}", block)
        self.assertIn('mode:"similar"', self.text)
        self.assertIn('mode:"selected"', self.text)

    def test_compare_decision_handler_reuses_set_state(self) -> None:
        start = self.text.index('grid.querySelectorAll("[data-compare-state]")')
        end = self.text.index('grid.querySelectorAll("[data-compare-temp-delete]")', start)
        block = self.text[start:end]
        self.assertIn('const state = String(button.dataset.compareState || "");', block)
        self.assertIn('["keep", "delete", "undecided"].includes(state)', block)
        self.assertIn("setState(member, state);", block)

    def test_compare_decision_change_redraws_same_compare_context(self) -> None:
        start = self.text.index('grid.querySelectorAll("[data-compare-state]")')
        end = self.text.index('grid.querySelectorAll("[data-compare-temp-delete]")', start)
        block = self.text[start:end]
        self.assertRegex(block, re.compile(r"const members = \[\.\.\.activeCompareMembers\];.*?const options = \{\{\.\.\.activeCompareOptions\}\};", re.S))
        self.assertIn("renderCompareMembers(members, options);", block)

    def test_exact_duplicate_keeper_flow_remains_separate(self) -> None:
        start = self.text.index("function renderExactDuplicateModal(groupId)")
        end = self.text.index("function chooseExactDuplicateKeeper", start)
        block = self.text[start:end]
        self.assertNotIn("compareDecisionButtonsHtml(member)", block)
        self.assertIn("data-exact-duplicate-keeper", block)

    def test_help_explains_direct_decision_change_and_shared_persistence_path(self) -> None:
        self.assertIn(
            "各ペイントの <b>残す / 削除候補 / 未決定</b> をその場で変更できます。",
            self.text,
        )
        self.assertIn(
            "比較画面の変更は一覧カードと同じ保存・Undo 経路を使うため、閉じた後の一覧にも反映します。",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
