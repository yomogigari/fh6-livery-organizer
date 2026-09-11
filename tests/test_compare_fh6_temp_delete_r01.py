from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class CompareFh6TempDeleteR01Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_r01_feature_marker_is_present_once(self) -> None:
        marker = "v0.4.61-r01 — 比較画面からFH6削除済み反映"
        self.assertEqual(self.text.count(marker), 1)

    def test_compare_delete_button_reuses_current_fh6_instance(self) -> None:
        pattern = re.compile(
            r"function fh6CompareTempDeleteButtonHtml\(card\) \{\{"
            r".*?const location = fh6LocationForCard\(card\);"
            r".*?if \(!location\) return \"\";"
            r".*?data-compare-temp-delete=\"\$\{\{escapeCompareHtml\(location\.instanceId\)\}\}\""
            r".*?>FH6で削除済み</button>`;",
            re.S,
        )
        self.assertRegex(self.text, pattern)

    def test_both_shared_compare_modes_render_the_delete_action(self) -> None:
        self.assertIn("const tempDeleteHtml = fh6CompareTempDeleteButtonHtml(member);", self.text)
        self.assertIn("${tempDeleteHtml}", self.text.replace("{{", "{").replace("}}", "}"))
        self.assertIn('mode:"similar"', self.text)
        self.assertIn('mode:"selected"', self.text)

    def test_compare_delete_delegates_to_existing_temp_delete_path(self) -> None:
        handler = re.search(
            r'grid\.querySelectorAll\("\[data-compare-temp-delete\]"\).*?'
            r'renderCompareMembers\(remaining, options\);\n  \}\}\)\);',
            self.text,
            re.S,
        )
        self.assertIsNotNone(handler)
        block = handler.group(0)
        self.assertIn("markFh6InstanceTempDeleted(instanceId)", block)
        self.assertIn("selectedKeys.delete(member.dataset.key)", block)
        self.assertIn("card !== member && !fh6CardIsTempDeleted(card)", block)

    def test_compare_view_is_redrawn_or_closed_after_delete(self) -> None:
        required = [
            'closeModal("compareModal", false)',
            "renderCompareMembers(remaining, options)",
            "activeCompareOptions = {{...options, mode:activeCompareMode}};",
            "比較対象 ${{activeCompareMembers.length}}件中",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_redownload_duplicate_modal_is_not_changed_by_this_revision(self) -> None:
        start = self.text.index("function renderExactDuplicateModal(groupId)")
        end = self.text.index("function chooseExactDuplicateKeeper", start)
        block = self.text[start:end]
        self.assertNotIn("data-compare-temp-delete", block)
        self.assertNotIn("fh6CompareTempDeleteButtonHtml", block)


if __name__ == "__main__":
    unittest.main()
