from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
sys.path.insert(0, str(ORGANIZER_DIR))

import locales.en as en_locale  # noqa: E402

SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"

HELP_HEADING = "プレビュー"
HELP_BODY = (
    "FH6本体パスを確認できたレポートでは、各カードからLivery Viewer for FH6でペイントを3D表示できます。"
    "この機能は実験的なもので、表示はゲーム内の見た目と完全には一致しません。"
    "初回だけ、Livery Viewer for FH6の設定画面で「Organizer連携を登録」を実行してください。"
    "GameSaveやFH6本体へ書き込みません。"
)


class Experimental3DPreviewI18nR02Tests(unittest.TestCase):
    def test_preview_help_uses_static_japanese_html_for_report_i18n(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn(f'<b class="fh6-foot-label">{HELP_HEADING}</b>{HELP_BODY}', source)
        self.assertNotIn(
            '{html.escape(report_text("プレビュー", "Preview"))}',
            source,
        )
        self.assertNotIn(
            '{html.escape(report_text("FH6本体パスを確認できたレポートでは、各カードからLivery Viewer for FH6でペイントを3D表示できます。',
            source,
        )

    def test_preview_help_has_english_report_text_entries(self):
        self.assertEqual(en_locale.REPORT_TEXT.get(HELP_HEADING), "Preview")
        self.assertEqual(
            en_locale.REPORT_TEXT.get(HELP_BODY),
            "When the FH6 installation path is available, each card can show the paint in 3D with Livery Viewer for FH6. "
            "This experimental feature does not exactly match the in-game appearance. "
            "On first use, run 'Register Organizer integration' in the Livery Viewer for FH6 settings window. "
            "It does not write to GameSave or the FH6 installation.",
        )


if __name__ == "__main__":
    unittest.main()
