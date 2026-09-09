from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EXPECTED_VERSION = "0.4.60-r10"
REVISION_FEATURE_TESTS = tuple(sorted((ROOT / "tests").glob("test_*_r[0-9][0-9].py")))
HISTORICAL_FEATURE_TESTS = (
    ROOT / "tests" / "test_i18n.py",
    *REVISION_FEATURE_TESTS,
)
REVISION_PIN_RE = re.compile(
    r'(?:VERSION\s*=\s*["\']0\.4\.60-r\d+["\']|'
    r'Livery Organizer for FH6 v0\.4\.60-r\d+)'
)
LOCALE_COUNT_PIN_RE = re.compile(
    r"assertEqual\(len\([^\n]*REPORT_(?:TEXT|ATTR)[^\n]*\),\s*\d+\)"
)


class CurrentVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_current_version_constant_is_centralized_here(self) -> None:
        self.assertEqual(self.text.count(f'VERSION = "{EXPECTED_VERSION}"'), 1)

    def test_source_header_matches_current_version(self) -> None:
        header = self.text.splitlines()[:8]
        self.assertIn(f"Livery Organizer for FH6 v{EXPECTED_VERSION}", header)

    def test_previous_revision_is_not_still_current(self) -> None:
        self.assertNotIn('VERSION = "0.4.60-r09"', self.text[:10000])
        self.assertNotIn("Livery Organizer for FH6 v0.4.60-r09", self.text[:400])

    def test_historical_feature_tests_do_not_pin_current_revision(self) -> None:
        offenders: list[str] = []
        for path in HISTORICAL_FEATURE_TESTS:
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "assert" not in line:
                    continue
                if REVISION_PIN_RE.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_revision_feature_tests_do_not_pin_global_locale_counts(self) -> None:
        offenders: list[str] = []
        for path in REVISION_FEATURE_TESTS:
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if LOCALE_COUNT_PIN_RE.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
