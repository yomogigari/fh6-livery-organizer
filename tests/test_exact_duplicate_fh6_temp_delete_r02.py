from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class ExactDuplicateFh6TempDeleteR02Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_r02_feature_marker_is_present_once(self) -> None:
        marker = "v0.4.61-r02 — 再DL重複整理画面からFH6削除済み反映"
        self.assertEqual(self.text.count(marker), 1)

    def test_duplicate_groups_exclude_temp_deleted_and_singletons(self) -> None:
        start = self.text.index("function exactDuplicateGroupEntries()")
        end = self.text.index("function renderExactDuplicateModal(groupId)", start)
        block = self.text[start:end]
        self.assertIn('card.dataset.exactDuplicate !== "1" || fh6CardIsTempDeleted(card)', block)
        self.assertIn('.filter(([, members]) => members.length >= 2)', block)

    def test_duplicate_modal_renders_fh6_temp_delete_action(self) -> None:
        start = self.text.index("function renderExactDuplicateModal(groupId)")
        end = self.text.index("function chooseExactDuplicateKeeper", start)
        block = self.text[start:end]
        self.assertIn("const tempDeleteHtml = fh6CompareTempDeleteButtonHtml(member);", block)
        self.assertIn("${{tempDeleteHtml}}", block)
        self.assertIn('grid.querySelectorAll("[data-compare-temp-delete]")', block)

    def test_duplicate_delete_delegates_to_existing_temp_delete_path(self) -> None:
        start = self.text.index("function renderExactDuplicateModal(groupId)")
        end = self.text.index("function chooseExactDuplicateKeeper", start)
        block = self.text[start:end]
        self.assertIn("markFh6InstanceTempDeleted(instanceId)", block)
        self.assertIn("const remainingEntries = exactDuplicateGroupEntries();", block)

    def test_resolved_group_advances_or_closes(self) -> None:
        start = self.text.index("function renderExactDuplicateModal(groupId)")
        end = self.text.index("function chooseExactDuplicateKeeper", start)
        block = self.text[start:end]
        required = [
            'closeModal("exactDuplicateModal", false)',
            "remainingEntries.some(([entryGroup]) => entryGroup === group)",
            "renderExactDuplicateModal(group)",
            "const nextIndex = Math.min(index, remainingEntries.length - 1);",
            "renderExactDuplicateModal(remainingEntries[nextIndex][0])",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, block)

    def test_help_explains_duplicate_temp_delete_flow(self) -> None:
        self.assertIn(
            "1件だけ残ったグループは整理済みとして専用画面から外れます。",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
