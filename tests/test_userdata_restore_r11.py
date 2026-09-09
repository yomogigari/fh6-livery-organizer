from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORGANIZER = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EN_LOCALE = ROOT / "src" / "organizer" / "locales" / "en.py"


class UserDataRestoreR11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ORGANIZER.read_text(encoding="utf-8")
        cls.en = EN_LOCALE.read_text(encoding="utf-8")

    def block(self, start: str, end: str) -> str:
        begin = self.source.index(start)
        finish = self.source.index(end, begin)
        return self.source[begin:finish]

    def test_r11_marker_is_present(self) -> None:
        self.assertIn(
            "v0.4.60-r11 — レポート外ユーザーデータの復元保持",
            self.source,
        )

    def test_full_restore_writes_backup_entries_without_requiring_current_cards(self) -> None:
        decisions = self.block(
            "function restoreDecisionBackupData(decisions)",
            "function restoreMetadataBackupData(metadata)",
        )
        self.assertIn("Object.entries(decisions).forEach", decisions)
        self.assertIn("const currentKey = STORAGE_PREFIX + key;", decisions)
        self.assertIn("storageSet(currentKey, state);", decisions)
        self.assertNotIn("cards.forEach", decisions)

        metadata = self.block(
            "function restoreMetadataBackupData(metadata)",
            "function loadScanStateForBackup()",
        )
        self.assertIn("Object.entries(metadata).forEach", metadata)
        self.assertIn("storageSet(META_PREFIX + key, JSON.stringify(rawMeta));", metadata)
        self.assertNotIn("cards.forEach", metadata)

    def test_full_backup_reexports_off_report_entries_from_browser_storage(self) -> None:
        decisions = self.block(
            "function buildDecisionBackupData()",
            "function buildMetadataBackupData()",
        )
        for token in (
            "storageKeysWithPrefixes([prefix])",
            "LEGACY_STORAGE_PREFIXES.forEach(collectPrefix);",
            "collectPrefix(STORAGE_PREFIX);",
            "storageGet(storageKey)",
        ):
            self.assertIn(token, decisions)
        self.assertIn("else delete decisions[key];", decisions)

        metadata = self.block(
            "function buildMetadataBackupData()",
            "function buildCreatorColorBackupData()",
        )
        for token in (
            "storageKeysWithPrefixes([prefix])",
            "LEGACY_META_PREFIXES.forEach(collectPrefix);",
            "collectPrefix(META_PREFIX);",
            "JSON.parse(storageGet(storageKey)",
        ):
            self.assertIn(token, metadata)
        self.assertIn("else delete metadata[key];", metadata)

    def test_full_restore_repaints_current_cards_after_storage_restore(self) -> None:
        method = self.block(
            "function applyUserDataPayload(payload, replaceExisting = false)",
            'document.getElementById("importUserDataFile")',
        )
        decisions_pos = method.index("restoreDecisionBackupData(decisions);")
        metadata_pos = method.index("restoreMetadataBackupData(metadata);")
        cards_pos = method.index("cards.forEach(card =>")
        self.assertLess(decisions_pos, cards_pos)
        self.assertLess(metadata_pos, cards_pos)
        self.assertNotIn("const state = decisions[card.dataset.key];", method)

    def test_complete_replace_clears_off_report_current_and_legacy_namespaces(self) -> None:
        clear = self.block(
            "function clearStoredPaintUserData()",
            "function restoreDecisionBackupData(decisions)",
        )
        for token in (
            "STORAGE_PREFIX",
            "...LEGACY_STORAGE_PREFIXES",
            "META_PREFIX",
            "...LEGACY_META_PREFIXES",
            "storageKeysWithPrefixes(prefixes)",
        ):
            self.assertIn(token, clear)

        method = self.block(
            "function applyUserDataPayload(payload, replaceExisting = false)",
            'document.getElementById("importUserDataFile")',
        )
        self.assertIn("clearStoredPaintUserData();", method)
        self.assertIn("storageRemove(UI_STATE_KEY);", method)
        self.assertIn("LEGACY_UI_STATE_KEYS.forEach", method)
        self.assertIn("storageRemove(SCAN_STATE_KEY);", method)
        self.assertIn("LEGACY_SCAN_STATE_KEYS.forEach", method)

    def test_decision_only_restore_also_preserves_off_report_entries(self) -> None:
        handler = self.block(
            'document.getElementById("importDecisionsFile").addEventListener',
            "function csvEscape(v)",
        )
        self.assertIn("const restored = restoreDecisionBackupData(decisions);", handler)
        self.assertIn("cards.forEach(card => paintState(card));", handler)
        self.assertNotIn("const state = decisions[card.dataset.key];", handler)

    def test_restore_preview_explains_off_report_preservation(self) -> None:
        self.assertIn("現在レポート外のペイントデータ", self.source)
        self.assertIn(
            "レポートに現在表示されていないペイントの整理データも保存領域へ復元します。",
            self.source,
        )
        self.assertIn(
            "現在表示されていないペイントを含む保存済みの整理状態・タグ・メモ・作成者カラー等を消去",
            self.source,
        )

    def test_new_restore_text_is_covered_by_english_report_i18n(self) -> None:
        self.assertIn(
            '"現在レポート外のペイントデータ": "Paint data outside the current report"',
            self.en,
        )
        self.assertIn(
            "Organization data for paints not shown in the current report is also restored to browser storage.",
            self.en,
        )
        self.assertIn(
            "including paints outside the current report, before restoring.",
            self.en,
        )


if __name__ == "__main__":
    unittest.main()
