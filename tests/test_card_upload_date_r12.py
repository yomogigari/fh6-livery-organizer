from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EN = ROOT / "src" / "organizer" / "locales" / "en.py"


class CardUploadDateR12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.en = EN.read_text(encoding="utf-8")

    def test_standard_card_shows_creator_upload_date(self) -> None:
        self.assertIn(
            '<dt class="fh6-normal-upload-date-row">アップロード日</dt><dd class="fh6-normal-upload-date-row fh6-upload-date-value" title="FH6画面の日付">{html.escape(r.fh6_date_display or "—")}</dd>',
            self.source,
        )

    def test_upload_date_uses_same_fh6_display_date_as_dedicated_layout(self) -> None:
        self.assertIn(
            '<div class="fh6-display-date{\' hidden\' if not r.fh6_date_display else \'\'}" title="FH6画面の日付">{html.escape(r.fh6_date_display or "")}</div>',
            self.source,
        )
        self.assertGreaterEqual(self.source.count("r.fh6_date_display"), 4)

    def test_dedicated_fh6_layout_does_not_duplicate_normal_upload_date_row(self) -> None:
        css = re.search(
            r"body\.fh6-my-design-view-mode \.fh6-my-design-column \.fh6-normal-creator-row,\s*"
            r"body\.fh6-my-design-view-mode \.fh6-my-design-column \.fh6-normal-upload-date-row \{\{(.*?)\}\}",
            self.source,
            re.S,
        )
        self.assertIsNotNone(css)
        self.assertIn("display:none !important;", css.group(1))

    def test_creator_first_glyph_alignment_preserves_badge_internal_spacing(self) -> None:
        css = re.search(
            r"body:not\(\.compact\):not\(\.fh6-my-design-view-mode\) \.card dl dd\.fh6-normal-creator-row \.creator-color-badge,\s*"
            r"body\.fh6-my-design-view-mode \.fh6-my-design-column \.fh6-creator-display \.creator-color-badge \{\{(.*?)\}\}",
            self.source,
            re.S,
        )
        self.assertIsNotNone(css)
        self.assertIn("margin-left:-7px;", css.group(1))
        self.assertIn("padding:1px 2px 1px 6px;", self.source)
        self.assertIn("box-shadow:inset 3px 0 0 var(--creator-color);", self.source)

    def test_compact_cards_keep_upload_date_visible_with_short_prefix(self) -> None:
        self.assertIn(
            'body.compact:not(.fh6-my-design-view-mode) .card dl dd.fh6-normal-upload-date-row::before {{',
            self.source,
        )
        self.assertIn('content:"UP ";', self.source)
        hidden_block = self.source.split(
            "body.compact:not(.fh6-my-design-view-mode) .compact-optional-selection,",
            1,
        )[1].split("{{", 1)[0]
        self.assertNotIn("fh6-normal-upload-date-row", hidden_block)

    def test_english_report_translates_upload_date_label(self) -> None:
        self.assertIn('"アップロード日": "Upload date"', self.en)

    def test_help_mentions_upload_date_in_both_languages(self) -> None:
        ja = "各カードにはサムネイル、車両情報、タイトル、説明、作成者、アップロード日、取得日時、バイナル数などを表示します。"
        self.assertIn(ja, self.source)
        self.assertIn(ja, self.en)
        self.assertIn("creator, upload date, acquired time, vinyl count", self.en)


if __name__ == "__main__":
    unittest.main()
