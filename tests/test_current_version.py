from __future__ import annotations

from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
PYPROJECT = ROOT / "pyproject.toml"
# 3つのツール（Organizer・Livery Viewer for FH6・Navigator Bridge）の共通の版（v0.5.0 から、3つを一緒に上げる）。
# 版の元は Organizer の VERSION の1か所。版を上げるときは、ここと Organizer の VERSION を直してから試験を動かし、
# 失敗した試験が示す所（Bridge の APP_VERSION・pyproject・文書の題と配布ZIPの名前）を直す。
# Viewer の EXE の版は、作るときに Organizer の VERSION から付ける。
EXPECTED_VERSION = "0.5.0"
BRIDGE_SOURCE = ROOT / "src" / "navigator_bridge" / "navigator-bridge-for-fh6.py"
RELEASES = ROOT / "docs" / "releases"
CHANGELOG = RELEASES / "CHANGELOG.md"
# 今の版と、今の配布ZIPの名前を書く文書（CHANGELOG は、いちばん上の今の版の節だけを見る）
CURRENT_VERSION_DOCS = (
    ROOT / "README.md",
    ROOT / "README_EN.md",
    RELEASES / "README.txt",
    RELEASES / "README_EN.txt",
    RELEASES / "NAVIGATOR-BRIDGE-README.txt",
    RELEASES / "NAVIGATOR-BRIDGE-README_EN.txt",
)
RELEASE_ZIP_RE = re.compile(r"Livery-Organizer-for-FH6-v(\d+\.\d+\.\d+)-preview")
BRIDGE_VERSION_MENTION_RE = re.compile(r"Navigator Bridge(?: for FH6)? v(\d+\.\d+\.\d+)")
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
    r'Livery Organizer for FH6 v\d+\.\d+\.\d+(?:-r\d+)?|'
    r'Navigator Bridge for FH6 v\d+\.\d+\.\d+|'
    r'APP_VERSION\s*,\s*["\']v?\d+\.\d+\.\d+)'
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

    def test_pyproject_matches_current_version(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["version"], EXPECTED_VERSION)

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


def changelog_current_section() -> str:
    """CHANGELOG のいちばん上の版の節（次の「## v」の見出しの前まで）。"""
    text = CHANGELOG.read_text(encoding="utf-8")
    start = text.index("\n## v") + 1
    end = text.find("\n## v", start)
    return text[start:] if end < 0 else text[start:end]


class SuiteVersionTests(unittest.TestCase):
    """3つのツールの版が、Organizer の VERSION（版の元）とそろっているか。"""

    def test_bridge_version_matches_organizer(self) -> None:
        text = BRIDGE_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'(?m)^APP_VERSION\s*=\s*"([^"]+)"\s*$', text), [f"v{EXPECTED_VERSION}"])
        self.assertIn(f"Navigator Bridge for FH6 v{EXPECTED_VERSION}", "\n".join(text.splitlines()[:6]))

    def test_release_text_titles_use_current_version(self) -> None:
        titles = {
            RELEASES / "README.txt": f"Livery Organizer for FH6 v{EXPECTED_VERSION} Preview",
            RELEASES / "README_EN.txt": f"Livery Organizer for FH6 v{EXPECTED_VERSION} Preview",
            RELEASES / "NAVIGATOR-BRIDGE-README.txt": f"Navigator Bridge for FH6 v{EXPECTED_VERSION}",
            RELEASES / "NAVIGATOR-BRIDGE-README_EN.txt": f"Navigator Bridge for FH6 v{EXPECTED_VERSION}",
        }
        for path, title in titles.items():
            with self.subTest(path=path.name):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[0], title)
                if lines[1].startswith("="):  # 題の下線は、題と同じ長さにする
                    self.assertEqual(lines[1], "=" * len(title))

    def test_readme_current_release_headings(self) -> None:
        expected = {
            ROOT / "README.md": (f"**v{EXPECTED_VERSION} Preview**", f"## v{EXPECTED_VERSION} Previewの主な更新"),
            ROOT / "README_EN.md": (f"**v{EXPECTED_VERSION} Preview**", f"## What's new in v{EXPECTED_VERSION} Preview"),
        }
        for path, needles in expected.items():
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                with self.subTest(path=path.name, needle=needle):
                    self.assertIn(needle, text)

    def test_changelog_top_section_is_current_version(self) -> None:
        self.assertTrue(changelog_current_section().startswith(f"## v{EXPECTED_VERSION} Preview"))

    def test_release_zip_names_and_bridge_mentions_use_current_version(self) -> None:
        sources = [(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
                   for path in (*CURRENT_VERSION_DOCS, SOURCE, ROOT / "src" / "organizer" / "locales" / "en.py")]
        sources.append(("docs/releases/CHANGELOG.md（今の版の節）", changelog_current_section()))
        offenders = []
        for name, text in sources:
            for pattern in (RELEASE_ZIP_RE, BRIDGE_VERSION_MENTION_RE):
                for match in pattern.finditer(text):
                    if match.group(1) != EXPECTED_VERSION:
                        line = text.count("\n", 0, match.start()) + 1
                        offenders.append(f"{name}:{line}: {match.group(0)}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
