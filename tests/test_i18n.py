from __future__ import annotations

from pathlib import Path
from string import Formatter
import ast
import importlib.util
import re
import sys
import unittest

ORGANIZER_DIR = Path(__file__).resolve().parents[1] / "src" / "organizer"
ORGANIZER_SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"
sys.path.insert(0, str(ORGANIZER_DIR))

import i18n  # noqa: E402
from locales.en import STRINGS as EN_STRINGS  # noqa: E402
from locales.ja import STRINGS as JA_STRINGS  # noqa: E402


def placeholders(text: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in Formatter().parse(text)
        if field_name
    }


def japanese_text(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龯]", text))


class LocalizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_language_keys_match(self) -> None:
        self.assertEqual(set(JA_STRINGS), set(EN_STRINGS))

    def test_format_placeholders_match(self) -> None:
        for key in JA_STRINGS:
            with self.subTest(key=key):
                self.assertEqual(placeholders(JA_STRINGS[key]), placeholders(EN_STRINGS[key]))

    def test_language_normalization(self) -> None:
        self.assertEqual(i18n.normalize_language("ja-JP"), "ja")
        self.assertEqual(i18n.normalize_language("en_US"), "en")
        self.assertEqual(i18n.normalize_language("de-DE"), "ja")

    def test_translation_and_japanese_fallback(self) -> None:
        i18n.set_language("en")
        self.assertEqual(i18n.tr("button.scan"), "Check Paint Data")
        self.assertEqual(i18n.tr("missing.key"), "missing.key")

    def test_formatting(self) -> None:
        i18n.set_language("en")
        text = i18n.tr("log.settings_file", path=r"C:\example\settings.json")
        self.assertIn("settings.json", text)


class OrganizerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("fh6_organizer_r03", ORGANIZER_SOURCE)
        assert spec is not None and spec.loader is not None
        cls.organizer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.organizer
        spec.loader.exec_module(cls.organizer)

    def tearDown(self) -> None:
        self.organizer.set_language(self.organizer.DEFAULT_LANGUAGE)

    def test_version_is_r03(self) -> None:
        self.assertEqual(self.organizer.VERSION, "0.4.58-r03")

    def test_display_path_changes_with_language(self) -> None:
        self.organizer.set_language("ja")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), "C:¥Temp¥File.txt")
        self.organizer.set_language("en")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), r"C:\Temp\File.txt")

    def test_environment_override_is_not_a_persisted_preference(self) -> None:
        self.assertEqual(self.organizer.normalize_language("en-US"), "en")
        self.assertEqual(self.organizer.normalize_language("ja-JP"), "ja")

    def test_preflight_is_localized(self) -> None:
        self.organizer.set_language("en")
        result = self.organizer.generator_preflight(None, None, None)
        self.assertEqual(result["summary"], "Fix the settings before running")
        self.assertEqual(result["items"][0]["label"], "Save data")
        self.assertEqual(result["items"][0]["detail"], "Not set")
        self.organizer.set_language("ja")
        result = self.organizer.generator_preflight(None, None, None)
        self.assertEqual(result["items"][0]["label"], "保存領域")

    def test_output_bundle_is_localized(self) -> None:
        self.organizer.set_language("en")
        self.assertEqual(
            self.organizer.output_bundle_label(embed_images=True, export_analysis_data=False),
            "HTML (images embedded) + Excel",
        )
        self.organizer.set_language("ja")
        self.assertEqual(
            self.organizer.output_bundle_label(embed_images=True, export_analysis_data=False),
            "HTML（画像込み） + Excel",
        )

    def test_support_information_is_localized(self) -> None:
        self.organizer.set_language("en")
        info = self.organizer.support_environment_info(None, None, None)
        text = self.organizer.format_support_environment_text(info)
        self.assertIn("Save data:", text)
        self.assertIn("Pre-run check:", text)
        self.assertNotIn("保存領域", text)


class GuiLocalizationAuditTests(unittest.TestCase):
    def test_app_user_visible_literals_do_not_contain_japanese(self) -> None:
        """Appクラス内の表示文字列がtr()を迂回して日本語固定へ戻るのを防ぎます。"""
        tree = ast.parse(ORGANIZER_SOURCE.read_text(encoding="utf-8"))
        app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "App")
        docstring_nodes: set[int] = set()
        for node in ast.walk(app):
            body = getattr(node, "body", None)
            if body and isinstance(body, list):
                first = body[0]
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstring_nodes.add(id(first.value))

        offenders: list[tuple[int, str]] = []
        for node in ast.walk(app):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstring_nodes
                and japanese_text(node.value)
            ):
                offenders.append((node.lineno, node.value))
        self.assertEqual(offenders, [], msg=f"日本語固定のGUI文字列があります: {offenders[:10]}")


if __name__ == "__main__":
    unittest.main()
