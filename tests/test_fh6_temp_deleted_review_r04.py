from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
BROWSER_SMOKE = ROOT / "tests" / "browser_compare_smoke.py"


class Fh6TempDeletedReviewR04Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.smoke = BROWSER_SMOKE.read_text(encoding="utf-8")

    def test_restore_modal_has_search_controls(self) -> None:
        for marker in (
            'id="fh6TempDeletedSearch"',
            'id="fh6TempDeletedSearchStatus"',
            'id="fh6TempDeletedSearchClear"',
            'placeholder="車種・タイトル・作成者・#001・#001U で検索"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_search_covers_identity_and_original_fh6_position(self) -> None:
        self.assertIn("function fh6TempDeletedSearchText(instance, width)", self.text)
        for field in (
            "instance.vehicle_label",
            "instance.vehicle_make",
            "instance.vehicle_model",
            "instance.vehicle_year",
            "instance.title",
            "instance.creator",
            "instance.car_id",
            "instance.position",
            "instance.fh6_date_display",
            "instance.timestamp_display",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.text)
        self.assertIn("tokens.every(token => haystack.includes(token))", self.text)

    def test_modal_reports_filtered_and_total_counts(self) -> None:
        self.assertIn('searchStatus.textContent = `表示 ${{items.length}} / ${{allItems.length}}件`', self.text)
        self.assertIn("検索条件に一致するFH6削除済み（仮）はありません。", self.text)
        self.assertIn('clearSearch.disabled = !hasQuery', self.text)

    def test_restore_rows_show_original_location_creator_and_dates(self) -> None:
        self.assertIn("`元の位置 #${{String(instance.slot_number || 0).padStart(width, \"0\")}} / ${{String(instance.position || \"—\")}}", self.text)
        self.assertIn("`FH6表示日付 ${{fh6Date}}`", self.text)
        self.assertIn("`取得日時 ${{acquired}}`", self.text)
        self.assertIn("` · 作成者 ${{creator}}`", self.text)

    def test_search_input_and_clear_redraw_without_new_storage_format(self) -> None:
        self.assertIn('document.getElementById("fh6TempDeletedSearch")?.addEventListener("input", renderFh6TempDeletedModal)', self.text)
        self.assertIn('document.getElementById("fh6TempDeletedSearchClear")?.addEventListener("click", () => {{', self.text)
        self.assertIn('storageSet(FH6_TEMP_DELETE_STORAGE_KEY, JSON.stringify([...fh6TempDeletedInstanceIds]))', self.text)
        self.assertNotIn("fh6TempDeletedSearchQuery", self.text)

    def test_help_mentions_searchable_restore_details(self) -> None:
        self.assertIn("復元画面では車種・タイトル・作成者・元の実スロット番号 / FH6位置で検索でき", self.text)
        self.assertIn("FH6表示日付と取得日時も確認できます", self.text)


    def test_english_report_locale_covers_r04_search_ui(self) -> None:
        english = (ROOT / "src" / "organizer" / "locales" / "en.py").read_text(encoding="utf-8")
        for marker in (
            '"検索をクリア": "Clear search"',
            '"車種・タイトル・作成者・#001・#001U で検索": "Search vehicle, title, creator, #001, or #001U"',
            '"FH6削除済みを検索": "Search temporarily deleted-in-FH6 items"',
            '"Original position #$1 / $2 · Creator $3"',
            '"Showing $1 / $2 items"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, english)

    def test_browser_smoke_exercises_search_and_clear(self) -> None:
        for marker in (
            'deletedSearch.value = "Browser Smoke 1 #001U"',
            'deletedSearch.value = "no-such-design"',
            'document.getElementById("fh6TempDeletedSearchClear")?.click()',
            '"表示 1 / 1件"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.smoke)


if __name__ == "__main__":
    unittest.main()
