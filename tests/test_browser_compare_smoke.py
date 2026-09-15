from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SMOKE_PATH = ROOT / "tests" / "browser_compare_smoke.py"

spec = importlib.util.spec_from_file_location("lo4fh6_browser_compare_smoke_tests", SMOKE_PATH)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


class BrowserCompareSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.organizer = smoke.load_organizer()

    def test_fixture_has_independent_first_slot_and_two_exact_duplicates(self) -> None:
        records = smoke.smoke_records(self.organizer)
        self.assertEqual(len(records), 3)
        self.assertNotEqual(records[0].fingerprint, records[1].fingerprint)
        self.assertEqual(records[1].fingerprint, records[2].fingerprint)
        self.assertEqual(len({record.ui_key for record in records}), 3)

    def test_harness_exercises_r01_r02_r03_runtime_paths(self) -> None:
        required = [
            'renderCompareMembers([first, second]',
            'getState(first) === "delete"',
            'tempDeleteButton.click()',
            'fh6LocationForCard(second)?.slotNumber === 1',
            'exactDuplicateGroupEntries()',
            'renderExactDuplicateModal(group)',
            'duplicateDeleteButton.click()',
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, smoke.SMOKE_SCRIPT)

    def test_harness_injection_preserves_single_body_close(self) -> None:
        source = "<html><body><p>fixture</p></body></html>"
        injected = smoke.inject_smoke_harness(source)
        self.assertEqual(injected.count('id="lo4fh6BrowserSmokeHarness"'), 1)
        self.assertEqual(injected.count("</body>"), 1)
        self.assertLess(injected.index("lo4fh6BrowserSmokeHarness"), injected.index("</body>"))

    def test_generated_smoke_report_contains_current_compare_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = smoke.build_smoke_report(Path(tmp))
            text = path.read_text(encoding="utf-8")
        self.assertIn('data-compare-state="keep"', text)
        self.assertIn('data-compare-temp-delete=', text)
        self.assertIn("function exactDuplicateGroupEntries()", text)
        self.assertIn('id="lo4fh6BrowserSmokeHarness"', text)


    def test_browser_profile_cleanup_retries_transient_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            profile.mkdir()
            (profile / "cache.bin").write_bytes(b"fixture")
            real_rmtree = smoke.shutil.rmtree
            calls = 0

            def flaky_rmtree(path, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise PermissionError(5, "simulated Windows cache lock")
                return real_rmtree(path, *args, **kwargs)

            with mock.patch.object(smoke.shutil, "rmtree", side_effect=flaky_rmtree), mock.patch.object(smoke.time, "sleep"):
                self.assertTrue(smoke.cleanup_browser_profile(profile, attempts=3, delay=0))
            self.assertEqual(calls, 3)
            self.assertFalse(profile.exists())

    def test_browser_profile_is_separate_from_report_temp_directory(self) -> None:
        source = SMOKE_PATH.read_text(encoding="utf-8")
        self.assertIn('tempfile.mkdtemp(prefix="lo4fh6-browser-profile-")', source)
        self.assertIn("cleanup_browser_profile(profile)", source)
        self.assertNotIn('profile = html_path.parent / "browser-profile"', source)

    def test_windows_edge_candidates_are_preferred_before_generic_browsers(self) -> None:
        source = SMOKE_PATH.read_text(encoding="utf-8")
        self.assertLess(source.index('"Microsoft" / "Edge"'), source.index('"chromium"'))
        self.assertIn('"--headless=new"', source)
        self.assertIn('"--dump-dom"', source)
        self.assertIn('"--virtual-time-budget=2000"', source)


if __name__ == "__main__":
    unittest.main()
