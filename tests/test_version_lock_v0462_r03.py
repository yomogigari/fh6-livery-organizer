from __future__ import annotations

from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
# 版の番号そのものは tests/test_current_version.py の1か所で固める。ここでは Organizer の VERSION とそろっているかだけを見る。


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
        version = source_match.group(1)
        self.assertEqual(project["project"]["version"], version)
        self.assertEqual(lock_match.group(1), version)


if __name__ == "__main__":
    unittest.main()
