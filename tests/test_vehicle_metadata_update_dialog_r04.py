from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZER = REPO_ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


class VehicleMetadataUpdateDialogR04Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ORGANIZER.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.app = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "App"
        )

    def method_node(self, name: str):
        return next(
            item
            for item in self.app.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        )

    def method_source(self, name: str) -> str:
        node = self.method_node(name)
        segment = ast.get_source_segment(self.source, node)
        self.assertIsNotNone(segment)
        return str(segment)

    def test_version_is_r04(self) -> None:
        self.assertIn('VERSION = "0.4.60-r06"', self.source)
        self.assertIn("Livery Organizer for FH6 v0.4.60-r06", self.source[:300])
        self.assertNotIn('VERSION = "0.4.60-r03"', self.source)

    def test_result_dialog_uses_selectable_text(self) -> None:
        method = self.method_source("_show_vehicle_metadata_update_result_dialog")
        self.assertIn("tk.Toplevel", method)
        self.assertIn("tk.Text", method)
        self.assertIn('text.configure(state="disabled")', method)
        self.assertIn('tr("button.copy_clipboard")', method)
        self.assertIn('tr("button.close")', method)
        self.assertIn("clipboard_append", method)

    def test_result_dialog_supports_ctrl_a_and_ctrl_c(self) -> None:
        method = self.method_source("_show_vehicle_metadata_update_result_dialog")
        for binding in (
            '"<Control-a>"',
            '"<Control-A>"',
            '"<Control-c>"',
            '"<Control-C>"',
        ):
            self.assertIn(binding, method)
        self.assertIn('text.tag_add("sel", "1.0", "end-1c")', method)
        self.assertIn('text.get("sel.first", "sel.last")', method)

    def test_result_dialog_has_no_hardcoded_japanese_user_text(self) -> None:
        node = self.method_node("_show_vehicle_metadata_update_result_dialog")
        offenders: list[str] = []
        docstring_node = None
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            docstring_node = node.body[0].value
        for item in ast.walk(node):
            if item is docstring_node:
                continue
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                if JAPANESE_RE.search(item.value):
                    offenders.append(item.value)
        self.assertEqual(offenders, [])

    def test_update_available_keeps_existing_localized_confirmation(self) -> None:
        method = self.method_source("_finish_vehicle_metadata_update_check")
        self.assertIn("self._show_vehicle_metadata_update_result_dialog", method)
        self.assertIn("messagebox.askyesno", method)
        self.assertIn('update_gui_text("download_question", language)', method)
        self.assertIn("parent=self.master", method)
        self.assertNotIn("download_prompt=", method)

    def test_non_update_result_is_copyable(self) -> None:
        method = self.method_source("_finish_vehicle_metadata_update_check")
        self.assertIn("self._show_vehicle_metadata_update_result_dialog", method)
        self.assertNotIn("messagebox.showinfo(title, body", method)
        self.assertNotIn("messagebox.showwarning(title, body", method)

    def test_result_dialog_is_modal_and_escape_closes(self) -> None:
        method = self.method_source("_show_vehicle_metadata_update_result_dialog")
        self.assertIn("win.grab_set()", method)
        self.assertIn("win.wait_window()", method)
        self.assertIn('win.bind("<Escape>"', method)


if __name__ == "__main__":
    unittest.main()
