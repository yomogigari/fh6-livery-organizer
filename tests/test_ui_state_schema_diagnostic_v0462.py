from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"


class UiStateSchemaDiagnosticV0462Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_ui_state_version_is_v4(self):
        self.assertIn("const UI_STATE_VERSION = 4;", self.text)

    def test_integrity_diagnostic_expects_v4(self):
        self.assertRegex(
            self.text,
            re.compile(
                r"UI state schema.*?UI_STATE_VERSION\s*===\s*4",
                re.DOTALL,
            ),
        )

    def test_integrity_diagnostic_does_not_expect_v3(self):
        self.assertNotRegex(
            self.text,
            re.compile(
                r"UI state schema.*?UI_STATE_VERSION\s*===\s*3",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main()
