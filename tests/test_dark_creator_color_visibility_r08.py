from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class DarkCreatorColorVisibilityR08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_r08_dark_creator_color_marker_is_present_once(self) -> None:
        self.assertEqual(self.text.count("v0.4.60-r08 — ダークテーマの作成者カラー視認性"), 1)

    def test_light_theme_creator_badge_mix_is_unchanged(self) -> None:
        self.assertEqual(
            self.text.count(
                "background:color-mix(in srgb, var(--creator-color) 15%, var(--surface));"
            ),
            1,
        )

    def test_dark_theme_creator_badge_has_stronger_background_mix(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        rule = re.search(
            r"body\.dark-theme \.creator-color-badge\.creator-colored\s*\{\{(.*?)\}\}",
            css,
            re.S,
        )
        self.assertIsNotNone(rule)
        self.assertIn(
            "background:color-mix(in srgb, var(--creator-color) 28%, var(--surface));",
            rule.group(1),
        )

    def test_r08_override_changes_background_only(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        rule = re.search(
            r"body\.dark-theme \.creator-color-badge\.creator-colored\s*\{\{(.*?)\}\}",
            css,
            re.S,
        )
        self.assertIsNotNone(rule)
        body = rule.group(1)
        self.assertEqual(body.count("background:"), 1)
        self.assertNotIn("border", body)
        self.assertNotIn("box-shadow", body)
        self.assertNotIn("color:", body.replace("background:color-mix", "background:mix"))

    def test_creator_color_badge_remains_main_visual_signal(self) -> None:
        self.assertIn(".creator-color-badge.creator-colored {{", self.text)
        self.assertIn("box-shadow:inset 3px 0 0 var(--creator-color);", self.text)
        self.assertIn(".card.creator-colored::after {{", self.text)
        self.assertIn("height:3px;", self.text)


    def test_creator_name_button_does_not_mask_badge_background(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        self.assertIn(".creator-color-badge .creator-name-button,", css)
        self.assertIn(".creator-color-badge .creator-name-button:hover:not(:disabled),", css)
        self.assertIn(".creator-color-badge .creator-name-button:active:not(:disabled) {{", css)
        self.assertIn("background:transparent;", css)
        self.assertIn("box-shadow:none;", css)
        self.assertIn("transform:none;", css)

    def test_creator_name_button_fix_is_theme_consistent(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        # 親バッジの色を子buttonが塗り潰さないよう、ライト/ダーク共通で透明化する。
        self.assertNotIn("body.dark-theme .creator-color-badge .creator-name-button", css)
        name_rule = re.search(
            r"\.creator-color-badge \.creator-name-button,.*?\{\{(.*?)\}\}",
            css,
            re.S,
        )
        self.assertIsNotNone(name_rule)
        self.assertIn("background:transparent;", name_rule.group(1))

    def test_dark_color_control_does_not_mask_badge_background(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        self.assertIn("body.dark-theme .creator-color-badge .creator-color-button {{", css)
        self.assertIn("background:transparent;", css)
        self.assertIn("body.dark-theme .creator-color-badge .creator-color-button:hover:not(:disabled) {{", css)
        self.assertIn("background:color-mix(in srgb, var(--creator-color) 12%, transparent);", css)
        self.assertIn('body.dark-theme .creator-color-badge .creator-color-button[aria-expanded="true"] {{', css)
        self.assertIn("background:color-mix(in srgb, var(--creator-color) 14%, transparent);", css)

    def test_dark_color_control_override_is_specific_enough_for_generic_dark_buttons(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        # body.dark-theme button の共通背景より高い詳細度を持つ selector にする。
        self.assertNotIn("body.dark-theme .creator-color-button {{", css)
        self.assertIn("body.dark-theme .creator-color-badge .creator-color-button {{", css)

    def test_dark_override_does_not_reintroduce_whole_card_tint(self) -> None:
        marker = "v0.4.60-r08 — ダークテーマの作成者カラー視認性"
        start = self.text.index(marker)
        end = self.text.index("v0.4.60-r07 — CSSテーマ参照の整理", start)
        css = self.text[start:end]
        self.assertNotIn(".card.creator-colored", css)


if __name__ == "__main__":
    unittest.main()
