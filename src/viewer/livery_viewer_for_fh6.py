"""Livery Viewer for FH6 の EXE の入口。引数の役割ごとに、各部品の処理へ振り分ける。

- 引数なし：設定画面（viewer_gui）
- `--uri <URI>`：Organizer 連携（organizer_preview_bridge。Windows に登録する URI の起動）
- `--lo4fh6-run=<役割> 引数…`：Viewer 自身が別のプロセスで動かす処理（lo4fh6_desktop_suite.runtime.self_command）

ソースから動かすときは、今までどおり各スクリプトを直接起動してもよい。
"""
from __future__ import annotations

import sys

from lo4fh6_desktop_suite.runtime import split_role


def main(argv: list[str] | None = None) -> int:
    role, rest = split_role(sys.argv[1:] if argv is None else argv)
    sys.argv = [sys.argv[0], *rest]
    if role == 'gui':
        import viewer_gui
        return viewer_gui.main()
    if role == 'bridge':
        # Organizer からの起動（--uri）は、重い部品を読み込む前に、開いている Viewer の窓へ依頼を渡せたら終わる。
        import viewer_window_reuse
        if viewer_window_reuse.forward_early(rest):
            return 0
        import organizer_preview_bridge
        organizer_preview_bridge.run_as_program()
    elif role == 'vehicle-preview':
        import vehicle_preview
        vehicle_preview.run_as_program()
    elif role == 'demo-bridge':
        import original_demo_preview_bridge
        original_demo_preview_bridge.run_as_program()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
