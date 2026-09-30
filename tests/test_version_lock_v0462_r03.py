from __future__ import annotations

from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
EXPECTED = "0.4.62-r04"


class VersionLockR03Tests(unittest.TestCase):
    def test_source_pyproject_and_uv_lock_share_version(self):
        source = SOURCE.read_text(encoding="utf-8")
        source_match = re.search(r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']\s*$', source)
        self.assertIsNotNone(source_match)
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        lock = UV_LOCK.read_text(encoding="utf-8")
        lock_match = re.search(
            r'\[\[package\]\]\s*\nname = "fh6-livery-organizer"\s*\nversion = "([^"]+)"',
            lock,
        )
        self.assertIsNotNone(lock_match)
        self.assertEqual(source_match.group(1), EXPECTED)
        self.assertEqual(project["project"]["version"], EXPECTED)
        self.assertEqual(lock_match.group(1), EXPECTED)


if __name__ == "__main__":
    unittest.main()
