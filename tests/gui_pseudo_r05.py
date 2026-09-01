from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_DIR = ROOT / "src" / "organizer"
MODULE_PATH = ORGANIZER_DIR / "livery-organizer-for-fh6.py"
sys.path.insert(0, str(ORGANIZER_DIR))

JAPANESE_RE = re.compile(r"[ぁ-んァ-ヶ一-龯]")
PSEUDO_MARKER = "⟦"


def load_module():
    spec = importlib.util.spec_from_file_location("fh6_gui_pseudo_r05", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def collect_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from collect_widgets(child)


def widget_text(widget) -> str:
    try:
        value = widget.cget("text")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def clipped_controls(top) -> list[tuple[str, int, int, str]]:
    offenders: list[tuple[str, int, int, str]] = []
    checked_classes = {"TLabel", "TButton", "TCheckbutton", "TLabelframe"}
    for widget in collect_widgets(top):
        try:
            if widget.winfo_class() not in checked_classes:
                continue
            requested = widget.winfo_reqwidth()
            actual = widget.winfo_width()
            if requested > actual + 4:
                offenders.append((widget.winfo_class(), requested, actual, widget_text(widget)[:180]))
        except Exception:
            continue
    return offenders


def main() -> int:
    os.environ["FH6_ORGANIZER_LANG"] = "qps"
    with tempfile.TemporaryDirectory() as temp_home:
        os.environ["HOME"] = temp_home
        os.environ.pop("APPDATA", None)
        organizer = load_module()
        organizer.initialize_ui_language({"language": "ja"})
        organizer.save_settings({"language": "ja"})

        root = organizer.tk.Tk()
        app = organizer.App(root)
        root.update_idletasks()
        root.update()

        app.show_quick_start_guide()
        app.show_support_info()
        root.update_idletasks()
        root.update()

        failures: list[str] = []
        if organizer.get_language() != "qps":
            failures.append(f"effective language is {organizer.get_language()!r}, expected 'qps'")

        selectable = dict(organizer.available_languages())
        if set(selectable) != {"ja", "en"}:
            failures.append(f"qps leaked into normal language selection: {selectable!r}")

        visible_texts = [widget_text(w) for w in collect_widgets(root)]
        if not any(PSEUDO_MARKER in text for text in visible_texts):
            failures.append("pseudo-localized GUI text was not found")
        japanese = [text for text in visible_texts if JAPANESE_RE.search(text)]
        if japanese:
            failures.append(f"Japanese GUI text remained in pseudo mode: {japanese[:5]!r}")

        if root.winfo_reqwidth() > root.winfo_width() + 4:
            failures.append(
                f"main window horizontal request exceeds actual size: req={root.winfo_reqwidth()} actual={root.winfo_width()}"
            )
        if app.status.winfo_height() < 55:
            failures.append(f"log area is too short for about three lines: {app.status.winfo_height()}px")
        if root.winfo_height() > root.winfo_screenheight() - 70:
            failures.append(
                f"main window is too tall for the test screen: {root.winfo_height()} / {root.winfo_screenheight()}"
            )

        tops = [root]
        for child in root.winfo_children():
            if child.winfo_class() == "Toplevel":
                tops.append(child)
        for top in tops:
            top.update_idletasks()
            if top.winfo_reqwidth() > top.winfo_width() + 4:
                failures.append(
                    f"{top.title()!r} requires more width than allocated: req={top.winfo_reqwidth()} actual={top.winfo_width()}"
                )
            if top.winfo_reqheight() > top.winfo_height() + 4:
                failures.append(
                    f"{top.title()!r} requires more height than allocated: req={top.winfo_reqheight()} actual={top.winfo_height()}"
                )
            clips = clipped_controls(top)
            if clips:
                failures.append(f"clipped controls in {top.title()!r}: {clips[:5]!r}")

        if failures:
            print("Pseudo GUI layout test: FAILED")
            for failure in failures:
                print("-", failure)
            root.destroy()
            return 1

        print("Pseudo GUI layout test: OK")
        print(
            f"Main window {root.winfo_width()}x{root.winfo_height()} / "
            f"requested {root.winfo_reqwidth()}x{root.winfo_reqheight()} / "
            f"log {app.status.winfo_height()}px"
        )
        for top in tops[1:]:
            print(
                f"Dialog {top.winfo_width()}x{top.winfo_height()} / "
                f"requested {top.winfo_reqwidth()}x{top.winfo_reqheight()}"
            )
        root.destroy()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
