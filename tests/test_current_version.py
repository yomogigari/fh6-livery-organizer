from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
EXPECTED_VERSION = "0.4.60-r15"
REVISION_FEATURE_TESTS = tuple(sorted((ROOT / "tests").glob("test_*_r[0-9][0-9].py")))
VERSION_AUDIT_TESTS = tuple(
    sorted(
        path
        for path in (ROOT / "tests").glob("test_*.py")
        if path.name != "test_current_version.py"
    )
)
VERSION_CONSTANT_RE = re.compile(
    r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']\s*$'
)
ORGANIZER_VERSION_PIN_RE = re.compile(
    r'(?:\bVERSION\s*=\s*["\']\d+\.\d+\.\d+(?:-r\d+)?["\']|'
    r'Livery Organizer for FH6 v\d+\.\d+\.\d+(?:-r\d+)?)'
)
LOCALE_COUNT_PIN_RE = re.compile(
    r"assertEqual\(len\([^\n]*REPORT_(?:TEXT|ATTR)[^\n]*\),\s*\d+\)"
)


class CurrentVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SOURCE.read_text(encoding="utf-8")

    def test_current_version_constant_is_centralized_here(self) -> None:
        self.assertEqual(VERSION_CONSTANT_RE.findall(self.text), [EXPECTED_VERSION])

    def test_source_header_matches_current_version(self) -> None:
        header = self.text.splitlines()[:8]
        self.assertIn(f"Livery Organizer for FH6 v{EXPECTED_VERSION}", header)

    def test_other_tests_do_not_pin_organizer_version(self) -> None:
        offenders: list[str] = []
        for path in VERSION_AUDIT_TESTS:
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "assert" not in line:
                    continue
                if ORGANIZER_VERSION_PIN_RE.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_version_audit_covers_non_revision_test_modules(self) -> None:
        self.assertIn(ROOT / "tests" / "test_vehicle_metadata_external.py", VERSION_AUDIT_TESTS)

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
