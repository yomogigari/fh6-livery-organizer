from __future__ import annotations

import importlib.util
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
AUDIT_SOURCE = ROOT / "src" / "organizer" / "livery-authorship-audit.py"


def load_module(name: str, path: Path):
    organizer_dir = str(path.parent)
    if organizer_dir not in sys.path:
        sys.path.insert(0, organizer_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def shape_record(shape_id: int, i: int, *, color: tuple[int, int, int, int]) -> bytes:
    # Integer-valued float32 transforms intentionally provide the quantization
    # signal observed in the calibrated automation-involved corpus.
    return b"\x00\x02" + struct.pack(
        "<H6f4B",
        shape_id,
        float(i + 1),
        float(i + 10),
        float(i + 20),
        float((i % 17) + 1),
        float((i % 19) + 1),
        float((i % 7) + 1),
        *color,
    )


def make_c_livery(records: list[bytes], *, section_total: int | None = None, car_id: int = 1234) -> bytes:
    root = bytearray(b"vlrc" + b"\x00" * 0x40)
    struct.pack_into("<I", root, 0x10, car_id)
    gyvl = bytearray(b"gyvl" + b"\x00" * 0x11)
    gyvl.extend(b"".join(records))
    total = len(records) if section_total is None else section_total
    counters = b"yrvl" + struct.pack("<12I", total, *([0] * 11))
    descriptor = b"yrvl" + b"\x00" * 16
    dec = bytes(root + gyvl + counters + descriptor)
    payload = zlib.compress(dec)
    return struct.pack("<II", len(payload), len(dec)) + payload


class AuthorshipAuditR05Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_module("fh6_authorship_audit_r05", AUDIT_SOURCE)
        cls.organizer = load_module("fh6_organizer_r05", ORGANIZER_SOURCE)

    def test_five_of_five_synthetic_signal(self):
        records = []
        for i in range(3000):
            color = (i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF, 255)
            records.append(shape_record(7, i, color=color))
        raw = make_c_livery(records)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "C_livery"
            path.write_bytes(raw)
            comp, uncomp, car_id, valid, vinyl_count, assessment, warnings = self.organizer.inspect_c_livery_with_audit(path)
        self.assertTrue(valid)
        self.assertEqual(car_id, 1234)
        self.assertEqual(vinyl_count, 3000)
        self.assertEqual(assessment["scan_quality"], "high")
        self.assertEqual(assessment["score"], 5)
        self.assertEqual(assessment["band"], "automation-likely")
        self.assertEqual(assessment["display"], "5/5")
        self.assertEqual(len(assessment["matched_rules"]), 5)
        self.assertFalse(warnings)

    def test_low_recovery_fails_closed(self):
        records = [shape_record(7, i, color=(1, 2, 3, 255)) for i in range(10)]
        raw = make_c_livery(records, section_total=1000)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "C_livery"
            path.write_bytes(raw)
            *_, assessment, _warnings = self.organizer.inspect_c_livery_with_audit(path)
        self.assertFalse(assessment["eligible"])
        self.assertIsNone(assessment["score"])
        self.assertEqual(assessment["band"], "not-assessable")
        self.assertEqual(assessment["display"], "—")

    def test_user_facing_display_is_numeric_only_but_internal_band_is_stable(self):
        assessment = {"band": "automation-likely", "score": 5, "max_score": 5}
        self.organizer.set_language("ja")
        self.assertEqual(self.organizer.localized_authorship_audit_display(assessment), "5/5")
        self.organizer.set_language("en")
        self.assertEqual(self.organizer.localized_authorship_audit_display(assessment), "5/5")
        self.assertEqual(assessment["band"], "automation-likely")
        self.organizer.set_language("ja")

    def test_audit_rule_labels_are_japanese_user_facing_text(self):
        labels = [rule[4] for rule in self.audit.AUDIT_RULES]
        self.assertEqual(len(labels), 5)
        self.assertTrue(all(any("ぁ" <= ch <= "ん" or "ァ" <= ch <= "ン" or "一" <= ch <= "龯" for ch in label) for label in labels))

    def test_organizer_source_contains_audit_ui_and_exports(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        for marker in (
            'data-authorship-audit-band=',
            '作成方法監査:',
            '一致した条件',
            '外れた条件',
            'record.authorship_audit',
            'record.authorship_audit_score',
            'tr("excel.header.authorship_audit")',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("手作業です", source)
        self.assertIn('return f"{score}/{max_score}"', source)

    def _reset_audit_cache_state(self):
        organizer = self.organizer
        with organizer._AUTHORSHIP_AUDIT_CACHE_LOCK:
            organizer._AUTHORSHIP_AUDIT_CACHE.clear()
            organizer._AUTHORSHIP_AUDIT_CACHE_LOADED = False
            organizer._AUTHORSHIP_AUDIT_CACHE_DIRTY = False

    def test_r06_second_run_uses_persistent_content_hash_cache(self):
        raw = make_c_livery([
            shape_record(7, i, color=(i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF, 255))
            for i in range(200)
        ])
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            c_livery = tmp_path / "C_livery"
            c_livery.write_bytes(raw)
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp_path / "cache")}, clear=False):
                self._reset_audit_cache_state()
                first = self.organizer.inspect_c_livery_with_audit(c_livery)
                self.organizer._save_authorship_audit_cache()
                self.assertTrue(self.organizer._authorship_audit_cache_path().is_file())

                self._reset_audit_cache_state()
                with mock.patch.object(
                    self.organizer,
                    "assess_decompressed_c_livery",
                    side_effect=AssertionError("persistent cache was not used"),
                ):
                    second = self.organizer.inspect_c_livery_with_audit(c_livery)
                self.assertEqual(second, first)

    def test_r06_cache_rejects_old_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp_path)}, clear=False):
                cache_path = self.organizer._authorship_audit_cache_path()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    '{"schema_version":1,"calibration":"old","entries":{}}',
                    encoding="utf-8",
                )
                self._reset_audit_cache_state()
                self.organizer._load_authorship_audit_cache()
                self.assertEqual(self.organizer._AUTHORSHIP_AUDIT_CACHE, {})


if __name__ == "__main__":
    unittest.main()
