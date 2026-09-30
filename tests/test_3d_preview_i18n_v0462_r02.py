from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
sys.path.insert(0, str(ORGANIZER_DIR))

import locales.en as en_locale  # noqa: E402

SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"

HELP_HEADING = "3Dプレビュー（実験）"
HELP_BODY = (
    "FH6本体パスを確認できたレポートでは、各カードから研究用3D Viewerを起動できます。"
    "この機能は研究段階で、研究プロトタイプ側のPreview Bridgeを事前登録した環境だけで動作します。"
    "GameSaveやFH6本体へ書き込みません。"
)


class Experimental3DPreviewI18nR02Tests(unittest.TestCase):
    def test_preview_help_uses_static_japanese_html_for_report_i18n(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn(f'<b class="fh6-foot-label">{HELP_HEADING}</b>{HELP_BODY}', source)
        self.assertNotIn(
            '{html.escape(report_text("3Dプレビュー（実験）", "3D Preview (Experimental)"))}',
            source,
        )
        self.assertNotIn(
            '{html.escape(report_text("FH6本体パスを確認できたレポートでは、各カードから研究用3D Viewerを起動できます。',
            source,
        )

    def test_preview_help_has_english_report_text_entries(self):
        self.assertEqual(en_locale.REPORT_TEXT.get(HELP_HEADING), "3D Preview (Experimental)")
        self.assertEqual(
            en_locale.REPORT_TEXT.get(HELP_BODY),
            "When the FH6 installation path is available, each card can launch the research 3D Viewer. "
            "This experimental feature requires the Preview Bridge from the research prototype to be registered first. "
            "It does not write to GameSave or the FH6 installation.",
        )


if __name__ == "__main__":
    unittest.main()
