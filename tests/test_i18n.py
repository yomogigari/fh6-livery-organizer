from __future__ import annotations

from pathlib import Path
from string import Formatter
import sys
import importlib.util
import os
import unittest

ORGANIZER_DIR = Path(__file__).resolve().parents[1] / "src" / "organizer"
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
        text = i18n.tr("log.settings_file", path=r"C:\\example\\settings.json")
        self.assertIn("settings.json", text)


class OrganizerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        module_path = ORGANIZER_DIR / "livery-organizer-for-fh6.py"
        spec = importlib.util.spec_from_file_location("fh6_organizer_r02", module_path)
        assert spec is not None and spec.loader is not None
        cls.organizer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.organizer
        spec.loader.exec_module(cls.organizer)

    def tearDown(self) -> None:
        self.organizer.set_language(self.organizer.DEFAULT_LANGUAGE)

    def test_version_is_r02(self) -> None:
        self.assertEqual(self.organizer.VERSION, "0.4.58-r02")

    def test_display_path_changes_with_language(self) -> None:
        self.organizer.set_language("ja")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), "C:¥Temp¥File.txt")
        self.organizer.set_language("en")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), r"C:\Temp\File.txt")

    def test_environment_override_is_not_a_persisted_preference(self) -> None:
        self.assertEqual(self.organizer.normalize_language("en-US"), "en")
        self.assertEqual(self.organizer.normalize_language("ja-JP"), "ja")


if __name__ == "__main__":
    unittest.main()
