from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EN = ROOT / "src" / "organizer" / "locales" / "en.py"


class UploadDateSortR14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.en = EN.read_text(encoding="utf-8")

    def test_sort_menu_has_upload_date_both_directions(self) -> None:
        self.assertIn('<option value="upload-desc">アップロード日:新しい順</option>', self.source)
        self.assertIn('<option value="upload-asc">アップロード日:古い順</option>', self.source)

    def test_upload_date_sort_uses_fh6_date_dataset(self) -> None:
        self.assertIn('mode === "upload-asc" || mode === "upload-desc"', self.source)
        self.assertIn('mode.startsWith("upload-")', self.source)
        self.assertIn('const av = String(a.dataset.fh6Date || "").trim();', self.source)
        self.assertIn('const bv = String(b.dataset.fh6Date || "").trim();', self.source)

    def test_missing_upload_dates_are_always_last(self) -> None:
        self.assertIn('if (!av && bv) return 1;', self.source)
        self.assertIn('if (!bv && av) return -1;', self.source)

    def test_upload_date_sort_has_deterministic_tie_breakers(self) -> None:
        self.assertIn('const timestampResult = String(a.dataset.timestamp || "").localeCompare(String(b.dataset.timestamp || ""));', self.source)
        self.assertIn('const carResult = Number(a.dataset.car || 0) - Number(b.dataset.car || 0);', self.source)
        self.assertIn('return String(a.dataset.key || "").localeCompare(String(b.dataset.key || ""));', self.source)

    def test_flat_heading_reports_upload_date_direction(self) -> None:
        self.assertIn('direction === "desc" ? "アップロード日:降順" : "アップロード日:昇順";', self.source)

    def test_help_explains_missing_date_behavior(self) -> None:
        text = "作成者がFH6へアップロードした日付でカード単位に並び替えます。日付を取得できなかったカードは昇順 / 降順のどちらでも最後に表示します。"
        self.assertIn(text, self.source)
        self.assertIn(text, self.en)

    def test_english_report_translates_upload_date_sort(self) -> None:
        self.assertIn('"アップロード日:新しい順": "Upload date: newest first"', self.en)
        self.assertIn('"アップロード日:古い順": "Upload date: oldest first"', self.en)
        self.assertIn('"アップロード日順": "Upload date"', self.en)


if __name__ == "__main__":
    unittest.main()
