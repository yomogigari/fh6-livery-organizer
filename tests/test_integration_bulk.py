"""Viewer と Navigator Bridge の Organizer 連携を、Organizer でまとめて登録・解除する（2026-11-21）の確認。

本物の Windows の登録（レジストリ）は書き換えない（登録を読み書きする所と、命令を動かす所は差し替える）。

- Bridge：--register-integration / --unregister-integration で、窓を出さずに登録・解除して終わる
  （二重起動の確かめより前。画面の「連携を登録」「解除」と同じ register_protocol・unregister_protocol）。
- Organizer：配布の EXE では同じフォルダーの EXE、ソースでは同じリポジトリの台本（Viewer は uv、Bridge は今の Python）
  を、登録・解除の引数で動かす。今の登録の状態（この Organizer と同じ配布の物か）を出す。
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
BRIDGE_SOURCE = ROOT / "src" / "navigator_bridge" / "navigator-bridge-for-fh6.py"


def load_module(name: str, path: Path):
    folder = str(path.parent)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


organizer = load_module("livery_organizer_integration_test", ORGANIZER_SOURCE)
bridge = load_module("navigator_bridge_integration_test", BRIDGE_SOURCE)


class BridgeIntegrationCommandTests(unittest.TestCase):
    def run_command(self, unregister: bool, **patches):
        output = io.StringIO()
        with mock.patch.object(bridge.sys, "stdout", output), \
                mock.patch.object(bridge, "register_protocol", **patches.get("register", {})) as register, \
                mock.patch.object(bridge, "unregister_protocol", **patches.get("unregister", {})) as unregister_call:
            code = bridge.run_integration_command(unregister)
        return code, output.getvalue(), register, unregister_call

    def test_register(self) -> None:
        code, text, register, unregister = self.run_command(False)
        self.assertEqual(code, 0)
        register.assert_called_once_with()
        unregister.assert_not_called()
        self.assertIn("registered: navigatorbridgeforfh6://", text)
        self.assertIn("command: ", text)

    def test_unregister(self) -> None:
        code, text, register, unregister = self.run_command(True)
        self.assertEqual(code, 0)
        unregister.assert_called_once_with()
        register.assert_not_called()
        self.assertIn("unregistered: navigatorbridgeforfh6://", text)

    def test_failure_returns_one_with_reason(self) -> None:
        code, text, _register, _unregister = self.run_command(False, register={"side_effect": RuntimeError("denied")})
        self.assertEqual(code, 1)
        self.assertIn("error: denied", text)

    def test_main_handles_flags_before_single_instance_check(self) -> None:
        source = BRIDGE_SOURCE.read_text(encoding="utf-8")
        main = source[source.index("def main() -> None:"):]
        self.assertLess(main.index('getattr(args, "register_integration", False)'), main.index("mutex_handle = None"))
        self.assertIn('p.add_argument("--register-integration", action="store_true", help=argparse.SUPPRESS)', source)
        self.assertIn('p.add_argument("--unregister-integration", action="store_true", help=argparse.SUPPRESS)', source)


class OrganizerIntegrationTargetsTests(unittest.TestCase):
    def test_source_mode_uses_repository_scripts(self) -> None:
        with mock.patch.object(organizer, "running_as_packaged_organizer", return_value=False), \
                mock.patch.object(organizer.shutil, "which", return_value="C:/tools/uv.exe"):
            targets = organizer.integration_targets()
        viewer, bridge_target = targets["viewer"], targets["bridge"]
        self.assertEqual(viewer["path"], ROOT / "src" / "viewer" / "organizer_preview_bridge.py")
        self.assertEqual(viewer["command"][:7], ["C:/tools/uv.exe", "run", "--no-project", "--python", "3.12", "--script",
                                                 str(ROOT / "src" / "viewer" / "organizer_preview_bridge.py")])
        self.assertEqual((viewer["register"], viewer["unregister"]), ("--register-uri-scheme", "--unregister-uri-scheme"))
        self.assertEqual(bridge_target["command"], [sys.executable, str(BRIDGE_SOURCE)])
        self.assertEqual((bridge_target["register"], bridge_target["unregister"]),
                         ("--register-integration", "--unregister-integration"))

    def test_source_mode_without_uv_has_no_viewer_command(self) -> None:
        with mock.patch.object(organizer, "running_as_packaged_organizer", return_value=False), \
                mock.patch.object(organizer.shutil, "which", return_value=None):
            self.assertEqual(organizer.integration_targets()["viewer"]["command"], [])

    def test_packaged_mode_uses_executables_next_to_organizer(self) -> None:
        base = Path("C:/dist")
        with mock.patch.object(organizer, "running_as_packaged_organizer", return_value=True), \
                mock.patch.object(organizer.sys, "executable", str(base / "Livery-Organizer-for-FH6.exe")):
            targets = organizer.integration_targets()
        viewer_exe = (base / "Livery-Viewer-for-FH6" / "Livery-Viewer-for-FH6.exe").resolve()
        bridge_exe = (base / "Navigator-Bridge-for-FH6.exe").resolve()
        self.assertEqual(targets["viewer"]["command"], [str(viewer_exe), "--lo4fh6-run=bridge"])
        self.assertEqual(targets["bridge"]["command"], [str(bridge_exe)])


class OrganizerIntegrationStateTests(unittest.TestCase):
    def target(self, path: Path) -> dict:
        return {"name": "X", "scheme": "x", "path": path, "command": ["x"], "register": "--r", "unregister": "--u"}

    def test_states(self) -> None:
        here = ROOT / "src" / "navigator_bridge" / "navigator-bridge-for-fh6.py"
        cases = [
            (f'"C:/Python/pythonw.exe" "{here}" --uri "%1"', ("here", str(here))),
            ('"D:/old/Navigator-Bridge-for-FH6.exe" --uri "%1"', ("elsewhere", "D:/old/Navigator-Bridge-for-FH6.exe")),
            ('"C:/Python/pythonw.exe" "D:/other/navigator-bridge-for-fh6.py" --uri "%1"',
             ("elsewhere", "D:/other/navigator-bridge-for-fh6.py")),
            ("", ("none", str(here))),
        ]
        for command, expected in cases:
            with self.subTest(command=command), \
                    mock.patch.object(organizer, "registered_integration_command", return_value=command):
                self.assertEqual(organizer.integration_state(self.target(here)), expected)
        with mock.patch.object(organizer, "registered_integration_command", return_value=""):
            self.assertEqual(organizer.integration_state(self.target(Path("C:/gone/tool.exe")))[0], "missing")


class OrganizerRunIntegrationTests(unittest.TestCase):
    def targets(self) -> dict:
        exists = BRIDGE_SOURCE
        return {
            "viewer": {"name": "V", "scheme": "v", "path": exists, "command": ["viewer.exe", "--lo4fh6-run=bridge"],
                       "register": "--register-uri-scheme", "unregister": "--unregister-uri-scheme"},
            "bridge": {"name": "B", "scheme": "b", "path": exists, "command": ["bridge.exe"],
                       "register": "--register-integration", "unregister": "--unregister-integration"},
        }

    def test_runs_both_with_action_flags(self) -> None:
        completed = [subprocess.CompletedProcess([], 0, "registered: v://\n", ""),
                     subprocess.CompletedProcess([], 1, "", "error: denied\n")]
        with mock.patch.object(subprocess, "run", side_effect=completed) as run:
            results = organizer.run_integration("register", self.targets())
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["viewer.exe", "--lo4fh6-run=bridge", "--register-uri-scheme"], ["bridge.exe", "--register-integration"]])
        self.assertEqual([(r["key"], r["ok"]) for r in results], [("viewer", True), ("bridge", False)])
        self.assertEqual(results[1]["detail"], "error: denied")
        self.assertEqual(run.call_args_list[0].kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_unregister_flags(self) -> None:
        ok = subprocess.CompletedProcess([], 0, "unregistered\n", "")
        with mock.patch.object(subprocess, "run", side_effect=[ok, ok]) as run:
            organizer.run_integration("unregister", self.targets())
        self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                         ["--unregister-uri-scheme", "--unregister-integration"])

    def test_missing_command_or_file_is_reported_without_running(self) -> None:
        targets = self.targets()
        targets["viewer"]["command"] = []
        targets["bridge"]["path"] = Path("C:/gone/Navigator-Bridge-for-FH6.exe")
        with mock.patch.object(subprocess, "run") as run:
            results = organizer.run_integration("register", targets)
        run.assert_not_called()
        self.assertEqual([r["ok"] for r in results], [False, False])


class OrganizerIntegrationUiTests(unittest.TestCase):
    def test_button_and_words(self) -> None:
        source = ORGANIZER_SOURCE.read_text(encoding="utf-8")
        self.assertIn('ttk.Button(language_row, text=tr("button.integration"), command=self.show_integration_dialog)',
                      source)
        self.assertIn("def show_integration_dialog(self):", source)
        import locales.en as en
        import locales.ja as ja
        for key in ("button.integration", "integration.title", "integration.intro", "integration.state.here",
                    "integration.state.elsewhere", "integration.state.none", "integration.state.missing",
                    "integration.register_all", "integration.unregister_all", "integration.running",
                    "integration.result.register", "integration.result.unregister", "integration.result.failed",
                    "integration.moved_note", "integration.uv_missing"):
            with self.subTest(key=key):
                self.assertIn(key, ja.STRINGS if hasattr(ja, "STRINGS") else ja.TEXT)
                self.assertIn(key, en.STRINGS if hasattr(en, "STRINGS") else en.TEXT)


if __name__ == "__main__":
    unittest.main()
