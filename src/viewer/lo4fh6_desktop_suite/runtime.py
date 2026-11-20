"""Viewer をソースから動かすときと、EXE（Livery-Viewer-for-FH6.exe）で動かすときの違いを 1 か所にまとめる。

Viewer は、設定画面・3D プレビューの準備（Organizer 連携）・車両の変換・デモ用の準備を、それぞれ別のプロセスで動かす。
- ソース：今までどおり `python <スクリプト> 引数…` で起動する。
- EXE：EXE 自身を `--lo4fh6-run=<役割> 引数…` で起動し直す（入口 livery_viewer_for_fh6.py が役割ごとに振り分ける）。
"""
from __future__ import annotations

from pathlib import Path
import sys

VIEWER_ROOT = Path(__file__).resolve().parents[1]
ROLE_ARGUMENT = '--lo4fh6-run'
# 役割と、ソースから動かすときのスクリプト（src/viewer からのパス）
ROLE_SCRIPTS = {
    'gui': 'viewer_gui.py',
    'bridge': 'organizer_preview_bridge.py',
    'vehicle-preview': 'vehicle_preview.py',
    'demo-bridge': 'original_demo_preview_bridge.py',
}


def is_packaged() -> bool:
    """EXE で動いているか。Nuitka は各モジュールに __compiled__ を置き、PyInstaller などは sys.frozen を置く。"""
    return bool(getattr(sys, 'frozen', False)) or '__compiled__' in globals()


# 起動したときの sys.argv[0]（配布した EXE）を控える。同じプロセスで別の処理を動かすために sys.argv を一時的に
# 置き換えることがあるので、その間も EXE の場所を取り違えないよう、置き換える前の値を使う（2026-11-20、EXE の
# 窓の流れで準備が止まっていた）。この部品は入口（livery_viewer_for_fh6.py）が最初に読み込む。
_PROGRAM_AT_START = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None


def packaged_executable() -> Path:
    """配布した EXE のパス。Nuitka の onefile では sys.argv[0] が配布した EXE（sys.executable は展開先）。"""
    return _PROGRAM_AT_START if _PROGRAM_AT_START is not None else Path(sys.argv[0]).resolve()


def role_script(role: str) -> Path:
    if role not in ROLE_SCRIPTS:
        raise ValueError(f'未対応の役割です: {role}')
    return VIEWER_ROOT / ROLE_SCRIPTS[role]


def self_command(role: str, *args: str, python: str | Path | None = None) -> list[str]:
    """役割を別のプロセスで動かす命令。ソースでは python（省略時は今の Python）とスクリプト、EXE では EXE 自身。"""
    script = role_script(role)
    if is_packaged():
        return [str(packaged_executable()), f'{ROLE_ARGUMENT}={role}', *args]
    return [str(python or sys.executable), str(script), *args]


def split_role(argv: list[str]) -> tuple[str, list[str]]:
    """EXE の引数から役割を取り出す。役割の指定が無ければ、--uri は連携、それ以外は設定画面。"""
    rest = list(argv)
    if rest and rest[0].startswith(ROLE_ARGUMENT + '='):
        role = rest.pop(0).split('=', 1)[1]
        role_script(role)
        return role, rest
    if rest and rest[0] == '--uri':
        return 'bridge', rest
    return 'gui', rest
