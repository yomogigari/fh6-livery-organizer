from __future__ import annotations

from pathlib import Path
from string import Formatter
import ast
import importlib.util
import re
import sys
import unittest
import tempfile

ORGANIZER_DIR = Path(__file__).resolve().parents[1] / "src" / "organizer"
ORGANIZER_SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"
sys.path.insert(0, str(ORGANIZER_DIR))

import i18n  # noqa: E402
from locales.en import STRINGS as EN_STRINGS  # noqa: E402
from locales.ja import STRINGS as JA_STRINGS  # noqa: E402
import report_i18n  # noqa: E402


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
        spec = importlib.util.spec_from_file_location("fh6_organizer_r04", ORGANIZER_SOURCE)
        assert spec is not None and spec.loader is not None
        cls.organizer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.organizer
        spec.loader.exec_module(cls.organizer)

    def tearDown(self) -> None:
        self.organizer.set_language(self.organizer.DEFAULT_LANGUAGE)

    def test_version_is_r04(self) -> None:
        self.assertEqual(self.organizer.VERSION, "0.4.58-r04")

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


class ReportLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("fh6_organizer_report_r04", ORGANIZER_SOURCE)
        assert spec is not None and spec.loader is not None
        cls.organizer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.organizer
        spec.loader.exec_module(cls.organizer)

    def tearDown(self) -> None:
        self.organizer.set_language(self.organizer.DEFAULT_LANGUAGE)

    def _record(self):
        o = self.organizer
        return o.LiveryRecord(
            livery_id="Livery_0001_20260101000000", car_id=1, car_id_folder=1,
            car_id_c_livery=1, car_id_verified=True, timestamp_raw="20260101000000",
            timestamp_local_guess="2026-01-01 09:00:00 JST", fh6_date_raw="01012026",
            fh6_date_display="01/01/2026", title="Sample Title",
            description="Sample Description", creator="Sample Creator", header_strings=[],
            vehicle_display_name="2020 Sample Car", vehicle_make="Sample Make",
            vehicle_model="Sample Model", vehicle_year=2020, vehicle_asset="sample_asset",
            vehicle_source="sample", source_dir="Livery_0001_20260101000000",
            relative_source_dir="Livery_0001_20260101000000", snapshot_name="sample",
            preferred_copy=True, header_path="", c_livery_path="", image_path="",
            report_image="", header_size=1, c_livery_size=1, image_size=0,
            header_sha256_16="a" * 16, c_livery_sha256_16="b" * 16,
            image_sha256_16="", fingerprint="f" * 32, c_livery_compressed_size=1,
            c_livery_uncompressed_size=1, c_livery_zlib_valid=True, vinyl_count=123,
            duplicate_copies=1, duplicate_sources=[], livery_reference_id="ref1",
            applied_state="unknown", applied_reference_paths=[], parse_warnings=[], ui_key="key1",
        )

    @staticmethod
    def _stats() -> dict:
        return {
            "livery_folders": 1, "unique_liveries": 1, "unique_car_ids": 1,
            "historical_duplicate_copies": 0, "fh6_exact_duplicate_groups": 0,
            "fh6_exact_duplicate_cards": 0, "fh6_exact_duplicate_instances": 0,
            "vehicle_db_size": 0, "scan_finished_local": "2026-01-01 09:00:00 JST",
        }

    def test_english_report_embeds_self_contained_i18n_layer(self) -> None:
        self.organizer.set_language("en")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            record = self._record()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', text)
        self.assertIn('id="reportI18nEnglishOverrides"', text)
        self.assertIn('const REPORT_LANGUAGE = "en"', text)

    def test_japanese_report_does_not_embed_english_translation_layer(self) -> None:
        self.organizer.set_language("ja")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            record = self._record()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="ja">', text)
        self.assertNotIn('reportI18nEnglishOverrides', text)

    def test_report_translation_script_has_user_data_protection(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        self.assertIn("protectedSelectors", script)
        self.assertIn("MutationObserver", script)
        self.assertIn("Move target", script)
        self.assertIn("compare-title-user-data", script)
        self.assertIn("compare-user-data", script)
        self.assertEqual(report_i18n.build_report_i18n_script("ja"), "")

    def test_report_translation_script_covers_dynamic_attributes(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        self.assertIn('"label"', script)
        self.assertIn('"data-closed-label"', script)
        self.assertIn('"data-base-label"', script)
        self.assertIn("Close Report Information", script)
        self.assertIn("Basic", script)

    def test_report_translation_script_covers_real_count_fh6_help(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        self.assertIn("Exact re-downloads: $1 groups / $2 items ($3 extra)", script)
        self.assertIn("Re-download duplicates: $1 items", script)

    def test_report_translation_script_covers_dynamic_navigator_plan(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        self.assertIn('["最終実スロット", "Final actual slot"]', script)
        self.assertIn('["初期位置", "origin"]', script)
        self.assertIn('["初期位置リセット", "origin reset"]', script)

    def test_report_translation_script_covers_similar_compare_summary(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        self.assertIn("Sorted by acquisition time, newest first.", script)
        self.assertIn('["サムネイル完全一致", "Exact thumbnail match"]', script)

    def test_english_report_localizes_protected_card_fallbacks(self) -> None:
        self.organizer.set_language("en")
        record = self._record()
        record.vehicle_make = ""
        record.vehicle_asset = ""
        record.title = ""
        record.creator = ""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn("Manufacturer unavailable", text)
        self.assertIn("Vehicle asset unavailable", text)
        self.assertIn("(Title unavailable)", text)
        self.assertIn("No creator information", text)

    def test_english_empty_report_localizes_no_data_fallback(self) -> None:
        self.organizer.set_language("en")
        stats = self._stats()
        stats.update({"livery_folders": 0, "unique_liveries": 0, "unique_car_ids": 0})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            html_path = self.organizer.write_report(
                root, [], stats, out, embed_images=True, fh6_records=[]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn("No livery folders were found.", text)
        self.assertIn("No creator information", text)

    def test_english_report_uses_english_locale_and_edge_case_constants(self) -> None:
        self.organizer.set_language("en")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            record = self._record()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn('const REPORT_LOCALE = "en-US";', text)
        self.assertIn('const REPORT_FALLBACK_UNKNOWN_ERROR = "Unknown error";', text)
        self.assertIn('const REPORT_FALLBACK_PROMISE_ERROR = "Promise error";', text)
        self.assertIn('const REPORT_FALLBACK_UNKNOWN_DATE = "Unknown date";', text)
        self.assertIn('const REPORT_FALLBACK_UNKNOWN_VEHICLE = "Unknown vehicle";', text)
        self.assertIn('const REPORT_FALLBACK_NO_TITLE = "No title";', text)
        self.assertIn('const REPORT_LABEL_NEWEST = "Newest";', text)
        self.assertIn('const REPORT_LABEL_OLDEST = "Oldest";', text)
        self.assertIn('const REPORT_BASELINE_PREFIX = "New-item baseline:";', text)
        self.assertIn('toLocaleString(REPORT_LOCALE)', text)
        self.assertNotIn('toLocaleString("ja-JP")', text)
        self.assertIn('vehicle || REPORT_FALLBACK_UNKNOWN_VEHICLE', text)
        self.assertIn('title || REPORT_FALLBACK_NO_TITLE', text)
        self.assertIn('return REPORT_FALLBACK_UNKNOWN_DATE;', text)

    def test_japanese_report_keeps_japanese_locale_constant(self) -> None:
        self.organizer.set_language("ja")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            record = self._record()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn('const REPORT_LOCALE = "ja-JP";', text)
        self.assertIn('const REPORT_FALLBACK_UNKNOWN_DATE = "日時不明";', text)

    def test_translation_layer_has_edge_case_fallback_safety_net(self) -> None:
        script = report_i18n.build_report_i18n_script("en")
        for expected in [
            "Manufacturer unavailable", "Vehicle asset unavailable", "(Title unavailable)",
            "No creator information", "No livery folders were found.", "Unknown date",
            "Unknown vehicle", "No title", "Unknown error", "Promise error",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, script)


class GuiLocalizationAuditTests(unittest.TestCase):
    def test_log_area_reserves_about_three_lines(self) -> None:
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.master.geometry("1000x840")', source)
        self.assertIn('self.status = tk.Text(frm, height=3, wrap="word")', source)

    def test_compare_user_data_regions_are_marked(self) -> None:
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('class="compare-vehicle-user-data"', source)
        self.assertIn('class="compare-title-user-data"', source)
        self.assertIn('class="compare-description compare-user-data"', source)

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
