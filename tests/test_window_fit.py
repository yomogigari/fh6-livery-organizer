"""窓の大きさを中身に合わせる（2026-11-21）の確認。窓は出さない（窓の代わりの物で確かめる）。

- Organizer の fit_window_to_content：中身が求める大きさ（reqwidth・reqheight）に合わせる。幅の下限・作業領域の上限。
  小さくできる下限（minsize）は中身の大きさ（作業領域を超えない）。
- Navigator Bridge の fit_window_to_content：中身の大きさに合わせ、作業領域の中に置く（大きさは変えられない窓）。
"""
from __future__ import annotations

import importlib.util
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


organizer = load_module("livery_organizer_window_fit_test", ORGANIZER_SOURCE)
bridge = load_module("navigator_bridge_window_fit_test", BRIDGE_SOURCE)


class FakeWindow:
    def __init__(self, req_width: int, req_height: int, *, width: int = 0, height: int = 0) -> None:
        self.req = (req_width, req_height)
        self.size = (width or req_width, height or req_height)
        self.calls: list[tuple] = []

    def update_idletasks(self) -> None:
        self.calls.append(("update_idletasks",))

    def winfo_reqwidth(self) -> int:
        return self.req[0]

    def winfo_reqheight(self) -> int:
        return self.req[1]

    def winfo_width(self) -> int:
        return self.size[0]

    def winfo_height(self) -> int:
        return self.size[1]

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def minsize(self, width: int, height: int) -> None:
        self.calls.append(("minsize", width, height))

    def geometry(self, value: str) -> None:
        self.calls.append(("geometry", value))


class OrganizerFitTests(unittest.TestCase):
    def test_fits_to_required_size_with_minimum_width(self) -> None:
        win = FakeWindow(880, 760)
        with mock.patch.object(organizer, "_work_area_size", return_value=(1920, 1040)):
            self.assertEqual(organizer.fit_window_to_content(win, min_width=1000), (1000, 760))
        self.assertIn(("minsize", 880, 760), win.calls)
        self.assertIn(("geometry", "1000x760"), win.calls)
        self.assertEqual(win.calls[0], ("update_idletasks",))

    def test_wider_content_and_work_area_limit(self) -> None:
        win = FakeWindow(1200, 1500)
        with mock.patch.object(organizer, "_work_area_size", return_value=(1920, 1040)):
            self.assertEqual(organizer.fit_window_to_content(win, min_width=1000), (1200, 1040))
        self.assertIn(("minsize", 1200, 1040), win.calls)

    def test_work_area_falls_back_to_screen(self) -> None:
        win = FakeWindow(100, 100)
        with mock.patch.object(organizer.sys, "platform", "linux"):
            self.assertEqual(organizer._work_area_size(win), (1920, 1080))


class BridgeFitTests(unittest.TestCase):
    def test_fits_and_places_inside_work_area(self) -> None:
        # 収まるときは位置だけを決める（大きさは Tk に任せ、文の長さが変わっても自動で合う）
        win = FakeWindow(820, 1000)
        with mock.patch.object(bridge, "_work_area_rect", return_value=(0, 0, 1920, 1040)):
            self.assertEqual(bridge.fit_window_to_content(win), (820, 1000))
        geometry = [call[1] for call in win.calls if call[0] == "geometry"][-1]
        self.assertEqual(geometry, "+550+13")

    def test_too_tall_content_is_clamped_and_kept_on_screen(self) -> None:
        win = FakeWindow(820, 1300)
        with mock.patch.object(bridge, "_work_area_rect", return_value=(0, 0, 1920, 1040)):
            self.assertEqual(bridge.fit_window_to_content(win), (820, 1040))
        geometry = [call[1] for call in win.calls if call[0] == "geometry"][-1]
        self.assertEqual(geometry, "820x1040+550+0")


class FakeTk:
    @staticmethod
    def splitlist(value):
        if isinstance(value, tuple):
            return value
        return tuple(str(value).split())


class FakeLabel:
    def __init__(self, wraplength="650", padding="") -> None:
        self.options = {"wraplength": wraplength, "padding": padding}
        self.tk = FakeTk()
        self.configured: list[dict] = []

    def cget(self, name):
        return self.options[name]

    def configure(self, **kwargs) -> None:
        self.configured.append(kwargs)
        self.options.update(kwargs)


class BridgeWrapLengthTests(unittest.TestCase):
    """説明の文の折り返し幅を、置かれた幅（枠の幅）に合わせる（2026-11-21）。"""

    def test_wrap_length_is_width_minus_padding_and_margin(self) -> None:
        label = FakeLabel()
        bridge.NavigatorApp._set_wrap_length(label, 770)
        self.assertEqual(label.configured, [{"wraplength": 770 - bridge.WRAP_MARGIN}])
        padded = FakeLabel(padding=(6, 4))
        bridge.NavigatorApp._set_wrap_length(padded, 792)
        self.assertEqual(padded.configured, [{"wraplength": 792 - 12 - bridge.WRAP_MARGIN}])

    def test_small_change_and_narrow_width_are_ignored(self) -> None:
        label = FakeLabel(wraplength=str(770 - bridge.WRAP_MARGIN - 1))
        bridge.NavigatorApp._set_wrap_length(label, 770)
        self.assertEqual(label.configured, [])
        narrow = FakeLabel()
        bridge.NavigatorApp._set_wrap_length(narrow, bridge.WRAP_MIN)
        self.assertEqual(narrow.configured, [])

    def test_horizontal_padding_forms(self) -> None:
        self.assertEqual(bridge.NavigatorApp._horizontal_padding(FakeLabel(padding="")), 0)
        self.assertEqual(bridge.NavigatorApp._horizontal_padding(FakeLabel(padding="3")), 6)
        self.assertEqual(bridge.NavigatorApp._horizontal_padding(FakeLabel(padding=(6, 4))), 12)
        self.assertEqual(bridge.NavigatorApp._horizontal_padding(FakeLabel(padding=(1, 2, 3, 4))), 4)

    def test_wrapping_labels_follow_the_frame_width(self) -> None:
        source = BRIDGE_SOURCE.read_text(encoding="utf-8")
        build = source[source.index("    def _build_ui(self) -> None:"):source.index("    def _on_language_selected(")]
        # 説明の文 4 つ・移動計画・状態の行が、置かれた幅で折り返す
        self.assertEqual(build.count("self._follow_width("), 6)
        self.assertIn("settings.columnconfigure(1, weight=1)", build)
        self.assertIn("plan_frame.columnconfigure(0, weight=1)", build)
        center = source[source.index("    def _center_window(self) -> None:"):]
        center = center[:center.index("\n    def ", 10)]
        self.assertLess(center.index("_set_wrap_length(label, label.winfo_width())"),
                        center.index("fit_window_to_content(self.root)"))


if __name__ == "__main__":
    unittest.main()
