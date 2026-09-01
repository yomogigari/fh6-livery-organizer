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


def load_module():
    spec = importlib.util.spec_from_file_location("fh6_gui_smoke_r03", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def collect_visible_text(widget):
    items: list[tuple[str, str]] = []
    try:
        text = widget.cget("text")
        if isinstance(text, str) and text:
            items.append((widget.winfo_class(), text))
    except Exception:
        pass
    if widget.winfo_class() == "Text":
        try:
            text = widget.get("1.0", "end-1c")
            if text:
                items.append(("Text", text))
        except Exception:
            pass
    for child in widget.winfo_children():
        items.extend(collect_visible_text(child))
    return items


def main() -> int:
    os.environ["FH6_ORGANIZER_LANG"] = "en"
    with tempfile.TemporaryDirectory() as temp_home:
        os.environ["HOME"] = temp_home
        os.environ.pop("APPDATA", None)
        organizer = load_module()
        organizer.initialize_ui_language({"language": "ja"})
        organizer.save_settings({"language": "ja"})

        root = organizer.tk.Tk()
        root.withdraw()
        app = organizer.App(root)
        root.update_idletasks()
        app.show_quick_start_guide()
        app.show_support_info()
        root.update_idletasks()

        offenders: list[tuple[str, str]] = []
        for cls, text in collect_visible_text(root):
            if JAPANESE_RE.search(text):
                offenders.append((cls, text))

        if offenders:
            print("Japanese visible text found:")
            for cls, text in offenders[:20]:
                print(cls, repr(text[:250]))
            root.destroy()
            return 1

        print("English GUI smoke test: OK")
        print("Checked main window, Quick Start Guide, and Environment / Support Information.")
        root.destroy()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
