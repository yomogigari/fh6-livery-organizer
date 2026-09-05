from __future__ import annotations

from pathlib import Path
from string import Formatter
import ast
import importlib.util
import json
import re
import sys
import unittest
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ORGANIZER_DIR = Path(__file__).resolve().parents[1] / "src" / "organizer"
ORGANIZER_SOURCE = ORGANIZER_DIR / "livery-organizer-for-fh6.py"
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

    def test_all_tr_calls_use_known_literal_keys_and_no_locale_keys_are_orphaned(self) -> None:
        tree = ast.parse(ORGANIZER_SOURCE.read_text(encoding="utf-8"))
        used: set[str] = set()
        dynamic_calls: list[int] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
            ):
                continue
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                used.add(node.args[0].value)
            else:
                dynamic_calls.append(node.lineno)
        self.assertEqual(dynamic_calls, [], msg=f"動的tr()キーがあります: {dynamic_calls}")
        self.assertEqual(used - set(JA_STRINGS), set())
        self.assertEqual(used - set(EN_STRINGS), set())
        self.assertEqual(set(JA_STRINGS) - used, set(), msg="未使用の翻訳キーがあります")

    def test_language_normalization(self) -> None:
        self.assertEqual(i18n.normalize_language("ja-JP"), "ja")
        self.assertEqual(i18n.normalize_language("en_US"), "en")
        self.assertEqual(i18n.normalize_language("qps-ploc"), "qps")
        self.assertEqual(i18n.normalize_language("de-DE"), "ja")

    def test_pseudo_locale_is_development_only(self) -> None:
        self.assertNotIn("qps", dict(i18n.available_languages()))
        self.assertTrue(i18n.language_display_name("qps").startswith("⟦"))

    def test_pseudo_locale_expands_english_and_preserves_placeholders(self) -> None:
        source = "Open {path} and review the selected design"
        pseudo = i18n.pseudo_localize(source)
        self.assertTrue(pseudo.startswith("⟦"))
        self.assertTrue(pseudo.endswith("⟧"))
        self.assertIn("{path}", pseudo)
        self.assertGreaterEqual(len(pseudo), int(len(source) * 1.30))
        rendered = pseudo.format(path=r"C:\UserData\Paint")
        self.assertIn(r"C:\UserData\Paint", rendered)

    def test_pseudo_translation_uses_english_base_without_translating_values(self) -> None:
        i18n.set_language("qps")
        path = r"C:\Example\settings.json"
        text = i18n.tr("log.settings_file", path=path)
        self.assertIn(path, text)
        self.assertIn("⟦", text)
        self.assertFalse(japanese_text(text))

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
        spec = importlib.util.spec_from_file_location("fh6_organizer_r10", ORGANIZER_SOURCE)
        assert spec is not None and spec.loader is not None
        cls.organizer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.organizer
        spec.loader.exec_module(cls.organizer)

    def tearDown(self) -> None:
        self.organizer.set_language(self.organizer.DEFAULT_LANGUAGE)

    def test_version_is_v0459_r10(self) -> None:
        self.assertEqual(self.organizer.VERSION, "0.4.59-r10")

    def test_source_header_matches_version(self) -> None:
        header = ORGANIZER_SOURCE.read_text(encoding="utf-8").splitlines()[:8]
        self.assertIn(f"Livery Organizer for FH6 v{self.organizer.VERSION}", header)

    def test_display_path_changes_with_language(self) -> None:
        self.organizer.set_language("ja")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), "C:¥Temp¥File.txt")
        self.organizer.set_language("en")
        self.assertEqual(self.organizer.display_path_text(r"C:\Temp\File.txt"), r"C:\Temp\File.txt")

    def test_environment_override_is_not_a_persisted_preference(self) -> None:
        self.assertEqual(self.organizer.normalize_language("en-US"), "en")
        self.assertEqual(self.organizer.normalize_language("ja-JP"), "ja")
        self.assertEqual(self.organizer.normalize_language("qps"), "qps")

    def test_pseudo_locale_cannot_be_enabled_by_saved_settings(self) -> None:
        import os
        previous = os.environ.pop("FH6_ORGANIZER_LANG", None)
        try:
            self.assertEqual(self.organizer.initialize_ui_language({"language": "qps"}), "ja")
        finally:
            if previous is not None:
                os.environ["FH6_ORGANIZER_LANG"] = previous

    def test_saved_language_and_environment_override_precedence(self) -> None:
        import os
        previous = os.environ.pop("FH6_ORGANIZER_LANG", None)
        try:
            self.assertEqual(self.organizer.initialize_ui_language({"language": "en"}), "en")
            os.environ["FH6_ORGANIZER_LANG"] = "qps"
            self.assertEqual(self.organizer.initialize_ui_language({"language": "ja"}), "qps")
        finally:
            if previous is None:
                os.environ.pop("FH6_ORGANIZER_LANG", None)
            else:
                os.environ["FH6_ORGANIZER_LANG"] = previous

    def test_cli_help_is_localized_for_english_and_pseudo(self) -> None:
        for language in ("en", "qps"):
            with self.subTest(language=language):
                self.organizer.set_language(language)
                help_text = self.organizer.build_parser().format_help()
                self.assertIn("--inspect-vehicle-assets", help_text)
                self.assertFalse(japanese_text(help_text))
                if language == "qps":
                    self.assertIn("⟦", help_text)

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

    def test_vehicle_asset_diagnostics_are_localized(self) -> None:
        vehicle_db = {1: object()}
        empty_archives = [{"path": "media/Cars/empty.zip"}]
        problems = [{
            "path": "media/Cars/broken.zip",
            "exception_type": "BadZipFile",
            "exception": "sample technical error",
            "size": 123,
            "prefix_hex": "00112233",
            "standard_zip_signature": False,
            "signature_error": "",
        }]
        self.organizer.set_language("en")
        text = self.organizer.format_vehicle_asset_problems(
            Path("C:/FH6"), vehicle_db, empty_archives, problems
        )
        self.assertIn("FH6 vehicle asset ZIP diagnostics:", text)
        self.assertIn("Detected Car IDs: 1", text)
        self.assertIn("Unreadable ZIPs: 1", text)
        self.assertIn("Exception summary: BadZipFile 1", text)
        self.assertIn("Size: 123 bytes", text)
        self.assertIn("sample technical error", text)
        self.assertFalse(japanese_text(text))

    def test_vehicle_asset_diagnostics_support_pseudo_locale_without_touching_technical_values(self) -> None:
        self.organizer.set_language("qps")
        technical_path = "media/Cars/日本語-user-data.zip"
        problems = [{
            "path": technical_path,
            "exception_type": "BadZipFile",
            "exception": "technical-value",
            "size": None,
            "prefix_hex": "",
            "standard_zip_signature": False,
            "signature_error": "signature-value",
        }]
        text = self.organizer.format_vehicle_asset_problems(Path("FH6"), {}, [], problems)
        self.assertIn("⟦", text)
        self.assertIn(technical_path, text)
        self.assertIn("technical-value", text)
        self.assertIn("signature-value", text)


class ReportLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("fh6_organizer_report_r06", ORGANIZER_SOURCE)
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

    def test_pseudo_report_embeds_development_translation_layer(self) -> None:
        self.organizer.set_language("qps")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            out = Path(tmp) / "out"
            root.mkdir()
            record = self._record()
            html_path = self.organizer.write_report(
                root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
            )
            text = html_path.read_text(encoding="utf-8")
        self.assertIn('<html lang="qps">', text)
        self.assertIn('const REPORT_LANGUAGE = "qps"', text)
        self.assertIn('data-pseudo-locale', text)
        self.assertIn('const REPORT_LOCALE = "en-US";', text)
        self.assertIn("⟦", text)
        self.assertIn("Sample Title", text)
        self.assertIn("Sample Creator", text)

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

    def test_report_scopes_fh6_move_target_to_generated_html(self) -> None:
        self.organizer.set_language("ja")
        scopes = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            record = self._record()
            for index in range(2):
                out = Path(tmp) / f"out{index}"
                html_path = self.organizer.write_report(
                    root, [record], self._stats(), out, embed_images=True, fh6_records=[record]
                )
                text = html_path.read_text(encoding="utf-8")
                move_match = re.search(
                    r'FH6_NAVIGATOR_TARGET_STORAGE_KEY = "livery-organizer-for-fh6-move-target:([0-9a-f]{20})"',
                    text,
                )
                temp_match = re.search(
                    r'FH6_TEMP_DELETE_STORAGE_KEY = "livery-organizer-for-fh6-temp-deleted:([0-9a-f]{20})"',
                    text,
                )
                self.assertIsNotNone(move_match)
                self.assertIsNotNone(temp_match)
                assert move_match is not None and temp_match is not None
                self.assertEqual(move_match.group(1), temp_match.group(1))
                scopes.append(move_match.group(1))
        self.assertNotEqual(scopes[0], scopes[1])

    def test_report_persists_and_cleans_fh6_move_target(self) -> None:
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
        self.assertIn("function loadFh6NavigatorTargetInstanceId()", text)
        self.assertIn("function saveFh6NavigatorTargetInstanceId()", text)
        self.assertIn("fh6NavigatorTargetInstanceId = loadFh6NavigatorTargetInstanceId();", text)
        self.assertIn("fh6NavigatorTargetInstanceId = location.instanceId;\n  saveFh6NavigatorTargetInstanceId();", text)
        self.assertIn('fh6NavigatorTargetInstanceId = "";\n  saveFh6NavigatorTargetInstanceId();', text)

    def test_report_groups_fh6_move_target_controls(self) -> None:
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
        self.assertIn('class="fh6-move-target-group" role="group" aria-label="FH6移動位置"', text)
        self.assertIn('<span class="fh6-move-target-caption">FH6移動:</span>', text)
        self.assertIn('<span class="fh6-location-caption">FH6移動:</span>', text)
        self.assertIn('.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"])', text)
        self.assertIn('.fh6-location-button:focus-visible', text)
        self.assertIn('content:none !important;', text)
        self.assertIn('flex-wrap:nowrap;', text)
        self.assertNotIn('content:"移動対象";\n  display:inline-flex;', text)

    def test_english_report_localizes_fh6_move_target_caption(self) -> None:
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
        self.assertIn('<span class="fh6-move-target-caption">FH6移動:</span>', text)
        self.assertIn('"FH6移動:":"FH6 move:"', text)
        self.assertIn('reportI18nEnglishOverrides', text)

    def test_report_translation_script_has_user_data_protection(self) -> None:
        script = i18n.build_report_i18n_script("en")
        self.assertIn("protectedSelectors", script)
        self.assertIn("MutationObserver", script)
        self.assertIn("compare-title-user-data", script)
        self.assertIn("compare-user-data", script)
        self.assertEqual(i18n.build_report_i18n_script("ja"), "")
        self.assertIn('const REPORT_LANGUAGE = "qps"', i18n.build_report_i18n_script("qps"))

    def test_report_translation_script_covers_dynamic_attributes(self) -> None:
        script = i18n.build_report_i18n_script("en")
        self.assertIn('"label"', script)
        self.assertIn('"data-closed-label"', script)
        self.assertIn('"data-base-label"', script)
        self.assertIn("Close Report Information", script)
        self.assertIn("Basic", script)

    def test_report_translation_script_covers_real_count_fh6_help(self) -> None:
        script = i18n.build_report_i18n_script("en")
        self.assertIn("Exact re-downloads: $1 groups / $2 items ($3 extra)", script)
        self.assertIn("Re-download duplicates: $1 items", script)

    def test_report_translation_script_covers_dynamic_navigator_plan(self) -> None:
        script = i18n.build_report_i18n_script("en")
        self.assertIn('["最終実スロット", "Final actual slot"]', script)
        self.assertIn('["初期位置", "origin"]', script)
        self.assertIn('["初期位置リセット", "origin reset"]', script)

    def test_report_translation_script_covers_similar_compare_summary(self) -> None:
        script = i18n.build_report_i18n_script("en")
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
        script = i18n.build_report_i18n_script("en")
        for expected in [
            "Manufacturer unavailable", "Vehicle asset unavailable", "(Title unavailable)",
            "No creator information", "No livery folders were found.", "Unknown date",
            "Unknown vehicle", "No title", "Unknown error", "Promise error",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, script)


    def test_r12_rev2_generated_report_uses_toggle_without_dedicated_move_clear_buttons(self) -> None:
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
        self.assertNotIn('id="fh6GlobalMoveClear"', text)
        self.assertNotIn('id="fh6NavigatorClear"', text)
        self.assertIn('function clearFh6NavigatorTarget()', text)
        self.assertIn('updateFh6NavigatorUi(false);', text)
        self.assertIn('r12 rev2では専用の「選択解除」ボタンを廃止', text)

    def test_r12_rev2_english_report_drops_dedicated_move_clear_button_translation(self) -> None:
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
        self.assertNotIn('"FH6移動対象の選択を解除します":"Clear the FH6 move target selection"', text)
        self.assertIn('"クリックしてFH6移動対象の選択を解除":"Click to clear the FH6 move target selection"', text)

    def test_r12_generated_report_toggles_selected_fh6_move_number(self) -> None:
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
        self.assertIn('v0.4.58-r12 — FH6移動対象番号をトグル操作に統一', text)
        self.assertIn('if (String(instance.instance_id || "") === fh6NavigatorTargetInstanceId)', text)
        self.assertIn('button.title = active ? "クリックしてFH6移動対象の選択を解除" : "クリックしてFH6移動対象に設定";', text)

    def test_r12_english_report_embeds_move_target_toggle_titles(self) -> None:
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
        self.assertIn('"クリックしてFH6移動対象に設定":"Click to set as the FH6 move target"', text)
        self.assertIn('"クリックしてFH6移動対象の選択を解除":"Click to clear the FH6 move target selection"', text)


    def test_r07_compact_view_is_dense_and_field_selectable(self) -> None:
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
        self.assertIn("v0.4.59-r07 — 高密度コンパクト表示 + 表示項目選択", text)
        self.assertIn("minmax(150px,1fr)", text)
        self.assertIn('id="compactDisplaySettings"', text)
        self.assertIn('data-compact-field="acquired"', text)
        self.assertIn('data-compact-field="vinyl"', text)
        self.assertIn("compactFields: selectedCompactFields()", text)
        self.assertIn('const UI_STATE_KEY = "livery-organizer-for-fh6-ui-v4";', text)
        self.assertIn("applyCompactFields(state.compactFields);", text)
        self.assertIn("常に表示: サムネイル・車種・タイトル・作成者・整理状態", text)


class ExcelLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("fh6_organizer_excel_r06", ORGANIZER_SOURCE)
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
            fh6_date_display="01/01/2026", title="お気に入り Sample Title",
            description="作成者 Sample Description", creator="メーカー Sample Creator", header_strings=[],
            vehicle_display_name="2020 日本語 Sample Car", vehicle_make="日本語 Sample Make",
            vehicle_model="日本語 Sample Model", vehicle_year=2020, vehicle_asset="sample_asset",
            vehicle_source="sample", source_dir=r"C:\UserData\Livery_0001_20260101000000",
            relative_source_dir="Livery_0001_20260101000000", snapshot_name="sample",
            preferred_copy=True, header_path="", c_livery_path="", image_path="",
            report_image="", header_size=1, c_livery_size=1, image_size=0,
            header_sha256_16="a" * 16, c_livery_sha256_16="b" * 16,
            image_sha256_16="", fingerprint="f" * 32, c_livery_compressed_size=1,
            c_livery_uncompressed_size=1, c_livery_zlib_valid=True, vinyl_count=123,
            duplicate_copies=1, duplicate_sources=[], livery_reference_id="ref1",
            applied_state="unknown", applied_reference_paths=[], parse_warnings=["technical warning"], ui_key="key1",
        )

    @staticmethod
    def _xlsx_snapshot(path: Path) -> dict:
        main_ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        dc_ns = "{http://purl.org/dc/elements/1.1/}"
        with zipfile.ZipFile(path, "r") as zf:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            sheet = workbook.find(".//" + main_ns + "sheet")
            worksheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
            core = ET.fromstring(zf.read("docProps/core.xml"))
            app = ET.fromstring(zf.read("docProps/app.xml"))

        values: dict[str, str] = {}
        for cell in worksheet.findall(".//" + main_ns + "c"):
            ref = cell.get("r") or ""
            text_node = cell.find(".//" + main_ns + "t")
            value_node = cell.find(main_ns + "v")
            if text_node is not None:
                values[ref] = text_node.text or ""
            elif value_node is not None:
                values[ref] = value_node.text or ""
            else:
                values[ref] = ""
        cols = [float(col.get("width", "0")) for col in worksheet.findall(".//" + main_ns + "col")]
        header_row = worksheet.find(".//" + main_ns + "row[@r='1']")
        title = core.find(dc_ns + "title")
        language = core.find(dc_ns + "language")
        app_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
        app_version = app.find(app_ns + "AppVersion")
        return {
            "sheet_name": "" if sheet is None else sheet.get("name", ""),
            "values": values,
            "widths": cols,
            "header_height": 0.0 if header_row is None else float(header_row.get("ht", "0")),
            "title": "" if title is None else (title.text or ""),
            "language": "" if language is None else (language.text or ""),
            "app_version": "" if app_version is None else (app_version.text or ""),
        }

    def _generate(self, language: str) -> dict:
        self.organizer.set_language(language)
        with tempfile.TemporaryDirectory() as tmp:
            path, image_count = self.organizer.write_excel_report([self._record()], Path(tmp))
            self.assertEqual(image_count, 0)
            return self._xlsx_snapshot(path)

    def test_japanese_excel_keeps_existing_labels(self) -> None:
        snap = self._generate("ja")
        self.assertEqual(snap["sheet_name"], "ペイント一覧")
        self.assertEqual(snap["title"], "Livery Organizer for FH6 ペイント一覧")
        self.assertEqual(snap["language"], "ja-JP")
        self.assertEqual(snap["values"]["A1"], "サムネイル")
        self.assertEqual(snap["values"]["B1"], "整理状態")
        self.assertEqual(snap["values"]["W1"], "解析メモ")
        self.assertEqual(snap["values"]["A2"], "なし")
        self.assertEqual(snap["values"]["B2"], "未決定")
        self.assertEqual(snap["header_height"], 24.0)
        self.assertEqual(snap["app_version"], "")

    def test_english_excel_localizes_system_text_and_preserves_user_data(self) -> None:
        snap = self._generate("en")
        self.assertEqual(snap["sheet_name"], "Paint List")
        self.assertEqual(snap["title"], "Livery Organizer for FH6 Paint List")
        self.assertEqual(snap["language"], "en-US")
        expected_headers = [
            "Thumbnail", "Decision Status", "Car ID", "Vehicle Name", "Manufacturer", "Model",
            "Year", "Vehicle Asset", "Creator", "Vinyl Count", "Title", "Description",
            "Acquired At", "Tags", "Notes", "Favorite", "Review Later", "Livery Reference ID",
            "Paint ID", "Fingerprint", "Thumbnail Source", "Source Folder", "Analysis Notes",
        ]
        actual_headers = [snap["values"][f"{self.organizer._xlsx_col_name(i)}1"] for i in range(1, 24)]
        self.assertEqual(actual_headers, expected_headers)
        self.assertEqual(snap["values"]["A2"], "No")
        self.assertEqual(snap["values"]["B2"], "Undecided")
        self.assertEqual(snap["values"]["D2"], "2020 日本語 Sample Car")
        self.assertEqual(snap["values"]["E2"], "日本語 Sample Make")
        self.assertEqual(snap["values"]["I2"], "メーカー Sample Creator")
        self.assertEqual(snap["values"]["K2"], "お気に入り Sample Title")
        self.assertEqual(snap["values"]["L2"], "作成者 Sample Description")
        self.assertFalse(any(japanese_text(value) for value in actual_headers))
        self.assertEqual(snap["app_version"], "")

    def test_excel_appversion_validator_rejects_semver(self) -> None:
        self.organizer.set_language("en")
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self.organizer.write_excel_report([self._record()], Path(tmp))
            broken = Path(tmp) / "broken-appversion.xlsx"
            with zipfile.ZipFile(path, "r") as src, zipfile.ZipFile(broken, "w", compression=zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    if info.filename == "docProps/app.xml":
                        text = data.decode("utf-8")
                        text = text.replace(
                            "</Properties>",
                            "<AppVersion>0.4.58-r06</AppVersion></Properties>",
                        )
                        data = text.encode("utf-8")
                    dst.writestr(info, data)
            with self.assertRaisesRegex(ValueError, "Invalid XLSX AppVersion"):
                self.organizer._validate_xlsx_package(broken, expected_rows=2, expected_cols=23)

    def test_pseudo_excel_expands_headers_without_touching_user_data(self) -> None:
        english = self._generate("en")
        pseudo = self._generate("qps")
        self.assertTrue(pseudo["sheet_name"].startswith("⟦"))
        self.assertEqual(pseudo["language"], "en-US")
        self.assertTrue(pseudo["values"]["A1"].startswith("⟦"))
        self.assertTrue(pseudo["values"]["B2"].startswith("⟦"))
        self.assertEqual(pseudo["values"]["D2"], "2020 日本語 Sample Car")
        self.assertEqual(pseudo["values"]["K2"], "お気に入り Sample Title")
        self.assertGreaterEqual(max(pseudo["widths"]), max(english["widths"]))
        self.assertGreater(pseudo["widths"][1], english["widths"][1])
        self.assertGreaterEqual(pseudo["header_height"], english["header_height"])

    def test_excel_sheet_name_is_sanitized_and_bounded(self) -> None:
        self.assertEqual(self.organizer._xlsx_sheet_name("A/B:C*D?E[Z]\\F"), "A-B-C-D-E-Z--F")
        self.assertLessEqual(len(self.organizer._xlsx_sheet_name("x" * 80)), 31)


class GuiLocalizationAuditTests(unittest.TestCase):
    def test_log_area_reserves_about_three_lines(self) -> None:
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('self.master.geometry("1000x840")', source)
        self.assertIn('self.status = tk.Text(frm, height=3, wrap="word")', source)
        self.assertIn('requested_height = self.master.winfo_reqheight()', source)

    def test_long_translation_layout_has_wrapping_and_adaptive_buttons(self) -> None:
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('text=tr("app.subtitle"),\n            wraplength=930', source)
        self.assertIn('required_button_width = sum(button.winfo_reqwidth()', source)
        self.assertIn('guide_height = max(650, min(win.winfo_reqheight()', source)
        self.assertIn('@media (max-width:1100px) and (min-width:541px)', source)
        self.assertIn('white-space:normal;', source)

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

    def test_non_report_python_display_literals_do_not_bypass_i18n(self) -> None:
        """write_reportの日本語テンプレートとApp以外で日本語固定表示へ戻るのを防ぎます。"""
        tree = ast.parse(ORGANIZER_SOURCE.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        def nearest(node: ast.AST, node_type):
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, node_type):
                    return current
            return None

        def is_docstring(node: ast.Constant) -> bool:
            expr = parents.get(node)
            owner = parents.get(expr) if expr is not None else None
            return bool(
                isinstance(expr, ast.Expr)
                and owner is not None
                and hasattr(owner, "body")
                and getattr(owner, "body")
                and getattr(owner, "body")[0] is expr
            )

        offenders: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and japanese_text(node.value)
                and not is_docstring(node)
            ):
                continue
            function = nearest(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            owner_class = nearest(node, ast.ClassDef)
            if function is not None and function.name == "write_report":
                continue
            if owner_class is not None and owner_class.name == "App":
                continue
            offenders.append((node.lineno, node.value))
        self.assertEqual(offenders, [], msg=f"tr()を迂回した日本語固定文字列があります: {offenders[:10]}")


    def test_r10_report_i18n_is_consolidated(self):
        self.assertFalse((ORGANIZER_DIR / "report_i18n.py").exists())
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("from report_i18n", source)
        self.assertNotIn("from .report_i18n", source)
        self.assertIn("build_report_i18n_script", source)

    def test_r10_report_resources_live_in_locale_module(self):
        import locales.en as en_locale
        import locales.ja as ja_locale
        self.assertEqual(ja_locale.REPORT_LOCALE, "ja-JP")
        self.assertEqual(en_locale.REPORT_LOCALE, "en-US")
        self.assertEqual(len(en_locale.REPORT_TEXT), 712)
        self.assertEqual(len(en_locale.REPORT_ATTR), 99)
        self.assertGreaterEqual(en_locale.REPORT_DYNAMIC_RULES_JS.count("[/^"), 100)
        self.assertIn("FH6移動:", en_locale.REPORT_TEXT)
        self.assertIn("FH6 move:", en_locale.REPORT_TEXT.values())
        self.assertIn("const rules", i18n.build_report_i18n_script("en"))

    def test_v0459_english_flat_sort_runtime_headings_are_localized(self):
        import locales.en as en_locale
        expected = {
            "タイトル": "Title",
            "取得日時:降順": "Acquired: newest first",
            "取得日時:昇順": "Acquired: oldest first",
            "バイナル数:降順": "Vinyl count: most first",
            "バイナル数:昇順": "Vinyl count: fewest first",
        }
        for source, translated in expected.items():
            self.assertEqual(en_locale.REPORT_TEXT.get(source), translated)

        script = i18n.build_report_i18n_script("en")
        for source, translated in expected.items():
            self.assertIn(json.dumps(source, ensure_ascii=False), script)
            self.assertIn(json.dumps(translated, ensure_ascii=False), script)
        self.assertIn("MutationObserver", script)
        self.assertIn("characterData:true", script)

    def test_r12_dynamic_report_translation_data_is_not_duplicated_in_i18n(self):
        i18n_source = (ORGANIZER_DIR / "i18n.py").read_text(encoding="utf-8")
        en_source = (ORGANIZER_DIR / "locales" / "en.py").read_text(encoding="utf-8")
        self.assertIn("{EN_REPORT_DYNAMIC_RULES_JS}", i18n_source)
        self.assertIn("{EN_REPORT_FRAGMENTS_JS}", i18n_source)
        self.assertNotIn('[/^残り (\\d+)人を表示$/', i18n_source)
        self.assertIn('[/^残り (\\d+)人を表示$/', en_source)

    def test_r10_report_locale_helper(self):
        self.assertEqual(i18n.locale_for_language("ja"), "ja-JP")
        self.assertEqual(i18n.locale_for_language("en"), "en-US")
        self.assertEqual(i18n.locale_for_language("qps"), "en-US")

    def test_r10_r09_move_target_does_not_reintroduce_per_button_label(self):
        script = i18n.build_report_i18n_script("en")
        self.assertNotIn('content:"Move target"', script)
        self.assertNotIn('fh6-move-target-trigger[aria-pressed="true"]::after', script)

    def test_r10_english_locale_translation_entries_use_one_physical_line(self):
        source_path = ORGANIZER_DIR / "locales" / "en.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    continue
                if not (key.lineno == value.lineno == value.end_lineno):
                    offenders.append((key.lineno, key.value))
        self.assertEqual(
            offenders,
            [],
            msg=f"locales/en.py の翻訳エントリが複数行に分割されています: {offenders[:10]}",
        )

    def test_r12_rev2_fh6_move_target_clear_helper_is_toggle_only(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('id="fh6GlobalMoveClear"', source)
        self.assertNotIn('id="fh6NavigatorClear"', source)
        self.assertIn('function clearFh6NavigatorTarget()', source)
        self.assertIn('fh6NavigatorTargetInstanceId = "";', source)
        self.assertIn('saveFh6NavigatorTargetInstanceId();', source)
        self.assertIn('updateFh6NavigatorUi(false);', source)
        self.assertIn('function updateFh6NavigatorUi(allowAutoSelect = true)', source)
        self.assertNotIn('document.getElementById("fh6GlobalMoveClear")', source)
        self.assertNotIn('document.getElementById("fh6NavigatorClear")', source)

    def test_r12_rev2_removed_move_clear_button_title_is_not_in_report_locale(self):
        import locales.en as en_locale
        self.assertIsNone(en_locale.REPORT_TEXT.get("FH6移動対象の選択を解除します"))
        self.assertEqual(en_locale.REPORT_TEXT.get("選択解除"), "Clear selection")

    def test_r12_rev2_selected_fh6_move_group_uses_full_accent_fill(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        marker = 'v0.4.58-r12 rev2 — FH6移動対象の選択表示をグループ全体へ統一'
        self.assertIn(marker, source)
        block = source[source.index(marker):source.index('v0.4.57-r09 — Navigator Bridge for FH6連携', source.index(marker))]
        self.assertIn('background:var(--accent);', block)
        self.assertIn('color:white;', block)
        self.assertIn('.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"])', block)
        self.assertIn('.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"])', block)

    def test_r12_fh6_move_target_number_click_is_toggle(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('v0.4.58-r12 — FH6移動対象番号をトグル操作に統一', source)
        self.assertIn('if (String(instance.instance_id || "") === fh6NavigatorTargetInstanceId)', source)
        self.assertIn('clearFh6NavigatorTarget();\n    return;', source)
        self.assertIn('setFh6NavigatorTargetInstance(instance);', source)

    def test_r12_fh6_move_target_toggle_titles_are_localized(self):
        import locales.en as en_locale
        self.assertEqual(
            en_locale.REPORT_ATTR.get("クリックしてFH6移動対象に設定"),
            "Click to set as the FH6 move target",
        )
        self.assertEqual(
            en_locale.REPORT_ATTR.get("クリックしてFH6移動対象の選択を解除"),
            "Click to clear the FH6 move target selection",
        )
        script = i18n.build_report_i18n_script("en")
        self.assertIn("Click to clear the FH6 move target selection", script)
        self.assertIn("Clear FH6 move target $1", script)

    def test_r13_search_shortcut_focuses_query_and_escape_clears_it(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('v0.4.58-r14 — 検索 / ヘルプへすぐ移動するキーボードショートカット', source)
        self.assertIn('event.key === "/"', source)
        self.assertIn('q.focus();', source)
        self.assertIn('q.select();', source)
        self.assertIn('q.addEventListener("keydown", event => {', source)
        self.assertIn('if (event.key !== "Escape") return;', source)
        self.assertIn('q.value = "";', source)
        self.assertIn('q.blur();', source)

    def test_r13_search_shortcut_is_documented_in_generated_report(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('<span>/ 検索</span>', source)
        self.assertIn('<span><kbd>/</kbd> 検索欄へ移動</span>', source)

    def test_r13_search_shortcut_labels_are_localized(self):
        import locales.en as en_locale
        self.assertEqual(en_locale.REPORT_TEXT.get('/ 検索'), '/ Search')
        self.assertEqual(en_locale.REPORT_TEXT.get('検索欄へ移動'), 'Focus search')
        script = i18n.build_report_i18n_script('en')
        self.assertIn('/ Search', script)
        self.assertIn('Focus search', script)

    def test_r14_help_shortcut_opens_help_without_hijacking_inputs(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('v0.4.58-r14 — 検索 / ヘルプへすぐ移動するキーボードショートカット', source)
        self.assertIn('event.key === "?"', source)
        self.assertIn('openHelpDialog(activeHelpTab);', source)
        self.assertIn('!["INPUT","TEXTAREA","SELECT"].includes(activeTag)', source)
        self.assertIn('function openHelpDialog(tab = activeHelpTab, opener = null)', source)

    def test_r14_help_shortcut_is_documented_in_generated_report(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('<span>? ヘルプ</span>', source)
        self.assertIn('<span><kbd>?</kbd> ヘルプを開く</span>', source)

    def test_r14_help_shortcut_labels_are_localized(self):
        import locales.en as en_locale
        self.assertEqual(en_locale.REPORT_TEXT.get('? ヘルプ'), '? Help')
        self.assertEqual(en_locale.REPORT_TEXT.get('ヘルプを開く'), 'Open help')
        script = i18n.build_report_i18n_script('en')
        self.assertIn('? Help', script)
        self.assertIn('Open help', script)

    def test_r15_fh6_my_design_jump_shortcuts_are_discoverable(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('<label for="fh6MyDesignJumpInput">位置・車種ジャンプ <kbd>J</kbd></label>', source)
        self.assertIn('aria-keyshortcuts="J"', source)
        self.assertIn('<span><kbd>J</kbd> FH6マイデザイン順の位置・車種ジャンプへ移動</span>', source)
        self.assertIn('<span><kbd>Shift</kbd> + <kbd>← / →</kbd> 車種検索を確定した後、前 / 次の一致へ巡回</span>', source)
        self.assertIn('event.key.toLowerCase() === "j"', source)
        self.assertIn('["ArrowLeft","ArrowRight"].includes(event.key)', source)

    def test_r15_fh6_my_design_jump_shortcut_labels_are_localized(self):
        import locales.en as en_locale
        self.assertEqual(
            en_locale.REPORT_TEXT.get("FH6マイデザイン順の位置・車種ジャンプへ移動"),
            "Focus the position / vehicle jump in FH6 My Designs order",
        )
        self.assertEqual(
            en_locale.REPORT_TEXT.get("車種検索を確定した後、前 / 次の一致へ巡回"),
            "After confirming a vehicle search, cycle to the previous / next match",
        )
        self.assertEqual(
            en_locale.REPORT_ATTR.get("537 / #537、#269U / #269D、または車種名を入力して移動します。Jキーでこの入力欄へ移動できます"),
            "Enter 537 / #537, #269U / #269D, or a vehicle name to jump. Press J to focus this field",
        )
        script = i18n.build_report_i18n_script("en")
        self.assertIn("Focus the position / vehicle jump in FH6 My Designs order", script)
        self.assertIn("After confirming a vehicle search, cycle to the previous / next match", script)
        self.assertIn("Press J to focus this field", script)


    def test_r15_live_search_reuses_compiled_criteria_and_defers_secondary_work(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("function buildCardCriteriaContext(overrides = {{}})", source)
        self.assertIn("const criteria = buildCardCriteriaContext();", source)
        self.assertIn("cardMatchesCriteria(card, {{}}, criteria)", source)
        self.assertIn("const LIVE_SEARCH_REFRESH_DELAY_MS = 70;", source)
        self.assertIn("const LIVE_SEARCH_SECONDARY_DELAY_MS = 240;", source)
        self.assertIn('q.addEventListener("input", scheduleLiveSearchRefresh);', source)
        self.assertIn("refreshLiveSearchView();", source)
        self.assertIn("updateDynamicFilterCounts();", source)
        self.assertIn("updateVehicleNavigationUi();", source)
        self.assertIn("saveUiState();", source)

    def test_r15_rev3_live_search_skips_full_sort_and_state_refresh(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("v0.4.58-r15 rev3 — 検索文字の変更だけでは並び順", source)
        self.assertIn("function refreshLiveSearchView()", source)
        scheduler_start = source.index("function scheduleLiveSearchRefresh()")
        scheduler_end = source.index('q.addEventListener("input", scheduleLiveSearchRefresh);', scheduler_start)
        scheduler = source[scheduler_start:scheduler_end]
        self.assertIn("refreshLiveSearchView();", scheduler)
        self.assertNotIn("refreshOrganizerUi", scheduler)
        self.assertNotIn("applySort", scheduler)
        self.assertNotIn("collectCardStateSummary", scheduler)
        self.assertIn("function syncLiveSearchLayout()", source)
        self.assertIn("updateGroupedLiveSearchVisibility();", source)
        self.assertIn("updateCreatorLiveSearchVisibility();", source)
        self.assertIn("updateFlatLiveSearchVisibility(mode);", source)
        self.assertIn("updateFh6LiveSearchVisibility();", source)

    def test_r15_rev3_search_uses_in_memory_static_and_meta_caches(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("const CARD_META_CACHE = new WeakMap();", source)
        self.assertIn("const CARD_SEARCH_STATIC_CACHE = new WeakMap();", source)
        self.assertIn("function loadCardMeta(card, forceReload = false)", source)
        self.assertIn("CARD_META_CACHE.set(card, meta);", source)
        self.assertIn("const meta = loadCardMeta(card, true);", source)
        self.assertIn("function staticCardSearchData(card)", source)
        self.assertIn("CARD_SEARCH_STATIC_CACHE.set(card, value);", source)
        self.assertIn("const staticSearch = staticCardSearchData(card);", source)

    def test_r15_rev3_flat_sort_reuses_precomputed_order_during_search(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('let flatSortOrderCache = [];', source)
        self.assertIn('let flatSortOrderMode = "";', source)
        self.assertIn("flatSortOrderCache = sortedCards;", source)
        self.assertIn("flatSortOrderMode = mode;", source)
        self.assertIn("const ordered = flatSortOrderMode === mode && flatSortOrderCache.length", source)
        self.assertIn("flatGrid.replaceChildren(...visibleCards);", source)

    def test_r15_vehicle_match_help_explains_both_cycle_modes(self):
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("一致した各車種を1車種1位置ずつ巡回します", source)
        self.assertIn("その1車種に属する実スロットを巡回します", source)
        self.assertIn("末尾では先頭へ循環します", source)


    def test_r10_navigator_settings_are_shared_across_sort_modes(self) -> None:
        source_path = ORGANIZER_SOURCE
        source = source_path.read_text(encoding="utf-8")
        self.assertEqual(source.count('id="fh6NavigatorSettings"'), 1)
        self.assertIn('id="fh6NavigatorSettingsGlobalHost"', source)
        self.assertIn('id="fh6NavigatorSettingsMyDesignHost"', source)
        self.assertIn('function placeFh6NavigatorSettings()', source)
        self.assertIn('placeFh6NavigatorSettings();', source)
        self.assertIn('body.compact #fh6NavigatorSettings', source)
        self.assertIn('"fh6NavigatorSettingsMyDesignHost"', source)
        self.assertIn('"fh6NavigatorSettingsGlobalHost"', source)
        self.assertIn('カーソル移動回数をプレビュー', source)

if __name__ == "__main__":
    unittest.main()
