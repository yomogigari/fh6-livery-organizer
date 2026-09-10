#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Navigator Bridge for FH6 v0.0.27-r01

非公式・非営利のファンメイド操作支援ツールです。
Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を
受けた公式ソフトウェアではありません。

このツールは、Forza Horizon 6 の「マイデザイン」画面内で、利用者が指定した位置まで
カーソルを移動しやすくするための補助Bridgeです。Organizer連携のBridgeモードでは、
(1) 前後の空白を除いたウィンドウタイトルが Forza Horizon 6 と完全一致し、
    ウィンドウ所有プロセスが forzahorizon6.exe で、候補が1つだけの場合にFH6として
    検出し、フォアグラウンドへ切り替えること、
(2) 位置移動に必要なカーソルキーを送ること、の2点だけを担当します。

【固定された安全境界】
- 通常の位置移動でFH6へ送信可能なキーは、カーソル「左」「右」「下」の3種類だけです。
- 任意設定の「#001Uへ戻す」がONの場合に限り、移動開始前の固定シーケンスとして
  Escを1回、Return(RET/Enter)を1回、この順序で送信します。
- 初期位置リセットの標準待ち時間は、Esc後 500ms / Return後 800ms です。
- 「上」、文字キー、ファンクションキー、その他のキーはFH6へ送信しません。
- 移動キーは1回送るごとに、対象HWNDが現在も前面・タイトル完全一致・
  forzahorizon6.exe 所有かを直前確認します。
- 外部連携URIから任意のキーコード・任意のキー名・任意のキー順序を指定する機能はありません。
- 標準のWindows入力APIを使用しますが、ゲームのメモリ・実行コード・ゲームファイル・
  セーブデータを変更しません。
- FH6の画面内容を画像認識・解析したり、ゲーム内部のペイント位置・カーソル位置を読み取ったりはしません。
- Organizerから渡された移動先と設定値に従い、指定された間隔で固定キー入力を送信するだけです。
  そのためPCやFH6の処理負荷等で入力が取りこぼされると、指定位置からずれる場合があります。
  必要に応じてキー間隔や各待ち時間を長めに調整してください。
- ゲーム進行・経済・報酬・ランキング・競争行為・削除確定などの自動化を目的としません。
  最終的な確認・選択・削除などの操作は利用者自身が行います。

BridgeモードではOrganizerから呼び出された際にGUIを表示せず、既存インスタンスがあれば
そこへ移動指示だけを渡します。単独起動した場合は、連携登録・手動テスト用GUIを表示します。

Microsoft、Xbox、Forzaおよび関連する名称・商標・著作物は、それぞれの権利者に帰属します。
利用者は、Microsoft / Xbox / Forzaの各利用規約および適用される法令を確認し、
自己の責任で本ツールを利用してください。

参考: Xbox ゲーム コンテンツ利用規約
https://www.xbox.com/ja-JP/developers/rules

前提:
- 「#001Uへ戻す」がOFFの場合、FH6「マイデザイン」画面を開いた直後のカーソル位置が 001U。
- 「#001Uへ戻す」がONの場合、Bridgeが Esc → RET でマイデザインを開き直してから移動します。
- 1列につき U/D の2スロット。
- 001列で左カーソルを押すと最終列へ循環する。
- 最終実スロット番号から最終列数を計算する。

標準ライブラリのみ使用:
- tkinter
- ctypes
"""

from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
from ctypes import wintypes
import re
import sys
import urllib.parse
from pathlib import Path
import threading
import uuid
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
import tkinter.font as tkfont

try:
    import winreg
except Exception:
    winreg = None

APP_NAME = "Navigator Bridge for FH6"
PACKAGED_EXE_FILENAME = "Navigator-Bridge-for-FH6.exe"
APP_VERSION = "v0.0.27-r01"
FH6_WINDOW_TITLE = "Forza Horizon 6"
FH6_PROCESS_IMAGE_NAME = "forzahorizon6.exe"
APP_USER_MODEL_ID = "LiveryTools.NavigatorBridgeForFH6"
PROTOCOL_SCHEME = "navigatorbridgeforfh6"
PROTOCOL_ROOT = rf"Software\Classes\{PROTOCOL_SCHEME}"
LEGACY_PROTOCOL_SCHEMES = ("fh6navigator",)
SINGLE_INSTANCE_MUTEX = r"Local\NavigatorBridgeForFH6.SingleInstance.v2"
IPC_DIR_NAME = "ipc-v2"
IPC_COMMAND_PREFIX = "command-"
IPC_POLL_MS = 180

# Livery Organizer for FH6 のデスクトップGUIと同じ可読性基準を使います。
# Windows 11では Segoe UI Variable を優先し、利用できない環境では
# Segoe UI / Yu Gothic UI / Tk既定フォントへ順にフォールバックします。
GUI_FONT_CANDIDATES = ("Segoe UI Variable", "Segoe UI", "Yu Gothic UI")
GUI_FONT_FAMILY = GUI_FONT_CANDIDATES[0]
GUI_FONT_SIZE = 11
GUI_SMALL_FONT_SIZE = 10


def _preferred_tk_font_family(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    try:
        available = {str(name).casefold(): str(name) for name in tkfont.families(root)}
        for candidate in candidates:
            match = available.get(candidate.casefold())
            if match:
                return match
    except Exception:
        pass
    return fallback


def configure_gui_fonts(root: tk.Misc) -> None:
    """Organizerと同等のSegoe UI Variable系・11ptをBridge GUIへ適用します。"""
    global GUI_FONT_FAMILY
    try:
        default_family = str(tkfont.nametofont("TkDefaultFont", root=root).actual("family"))
    except Exception:
        default_family = GUI_FONT_CANDIDATES[-1]
    GUI_FONT_FAMILY = _preferred_tk_font_family(root, GUI_FONT_CANDIDATES, default_family)

    specs = {
        "TkDefaultFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkTextFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkMenuFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkHeadingFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold"),
        "TkCaptionFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold"),
        "TkSmallCaptionFont": (GUI_FONT_FAMILY, GUI_SMALL_FONT_SIZE, "normal"),
        "TkIconFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkTooltipFont": (GUI_FONT_FAMILY, GUI_SMALL_FONT_SIZE, "normal"),
    }
    for name, (family, size, weight) in specs.items():
        try:
            tkfont.nametofont(name, root=root).configure(family=family, size=size, weight=weight)
        except Exception:
            pass

    try:
        style = ttk.Style(root)
        style.configure(".", font="TkDefaultFont")
        style.configure("TEntry", font="TkTextFont")
        style.configure("TButton", font="TkDefaultFont", padding=(9, 6))
        style.configure("TCheckbutton", font="TkDefaultFont")
        style.configure("TLabelframe.Label", font="TkDefaultFont")
    except Exception:
        pass


def position_app_dialog(win: tk.Toplevel, parent: tk.Misc | None, width: int, height: int) -> None:
    """Place a dialog near the parent window instead of letting Tk map it at the top-left.

    The dialog is kept withdrawn until this positioning is complete, which also prevents
    the brief top-left flash that can otherwise occur on Windows. Headless Bridge errors
    have no visible parent, so they are centered on the screen instead.
    """
    try:
        win.update_idletasks()
        screen_w = max(width + 48, int(win.winfo_screenwidth()))
        screen_h = max(height + 48, int(win.winfo_screenheight()))

        use_parent = False
        if parent is not None:
            try:
                parent.update_idletasks()
                parent_x = int(parent.winfo_rootx())
                parent_y = int(parent.winfo_rooty())
                parent_w = int(parent.winfo_width())
                parent_h = int(parent.winfo_height())
                # A withdrawn/hidden Tk root is commonly 1x1 at the screen origin.
                # Do not use that as an anchor for headless Bridge dialogs.
                use_parent = parent_w > 1 and parent_h > 1 and parent.winfo_viewable()
            except Exception:
                use_parent = False

        if use_parent:
            x = parent_x + (parent_w - width) // 2
            y = parent_y + (parent_h - height) // 2
        else:
            x = (screen_w - width) // 2
            y = (screen_h - height) // 2

        x = max(24, min(x, screen_w - width - 24))
        y = max(24, min(y, screen_h - height - 24))
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        # Even the fallback is intentionally away from the screen origin.
        win.geometry(f"{width}x{height}+80+60")


def show_app_dialog(parent: tk.Misc | None, title: str, text: str, *, kind: str = "error") -> None:
    """Large-font modal positioned naturally relative to the Bridge window.

    The Toplevel remains withdrawn until its size and position have been calculated, so
    registration/info/error dialogs do not briefly appear at the upper-left of the screen.
    Headless Bridge errors are centered on the screen. A Windows MessageBox remains only
    as a last-resort fallback if Tk itself cannot create the custom dialog.
    """
    owns_root = False
    root = parent
    try:
        if root is None:
            root = tk.Tk()
            owns_root = True
            root.withdraw()
        configure_gui_fonts(root)

        win = tk.Toplevel(root)
        # Prevent Windows/Tk from showing the new Toplevel at its default top-left
        # position before we can calculate the final geometry.
        win.withdraw()
        win.title(title)
        win.resizable(False, False)
        set_app_icon(win)
        try:
            if parent is not None:
                win.transient(parent)
        except Exception:
            pass

        frame = ttk.Frame(win, padding=(18, 16, 18, 14))
        frame.grid(sticky="nsew")
        heading = "エラー" if kind == "error" else "お知らせ"
        ttk.Label(
            frame,
            text=heading,
            font=(GUI_FONT_FAMILY, 14, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(
            frame,
            text=str(text),
            justify="left",
            wraplength=620,
            font=(GUI_FONT_FAMILY, GUI_FONT_SIZE),
        ).grid(row=1, column=0, sticky="w")
        button = ttk.Button(frame, text="OK", command=win.destroy)
        button.grid(row=2, column=0, sticky="e", pady=(15, 0))

        win.bind("<Return>", lambda _event: win.destroy())
        win.bind("<Escape>", lambda _event: win.destroy())
        win.update_idletasks()
        width = max(430, min(720, win.winfo_reqwidth()))
        height = max(170, win.winfo_reqheight())
        position_app_dialog(win, parent, width, height)

        win.deiconify()
        win.lift()
        try:
            win.attributes("-topmost", True)
            win.after(120, lambda: win.attributes("-topmost", False))
        except Exception:
            pass
        button.focus_set()
        win.grab_set()
        win.wait_window()
    except Exception:
        # Last-resort fallback for environments where Tk cannot create the custom dialog.
        if IS_WINDOWS:
            try:
                flags = 0x00000010 if kind == "error" else 0x00000040
                ctypes.windll.user32.MessageBoxW(None, str(text), title, flags | 0x00040000)
            except Exception:
                pass
    finally:
        if owns_root and root is not None:
            try:
                root.destroy()
            except Exception:
                pass

def show_app_error(parent: tk.Misc | None, text: str, title: str = APP_NAME) -> None:
    show_app_dialog(parent, title, text, kind="error")


def show_app_info(parent: tk.Misc | None, text: str, title: str = APP_NAME) -> None:
    show_app_dialog(parent, title, text, kind="info")

SHARED_MOVE_SETTINGS_DEFAULTS = {
    "interval_ms": 50.0,
    "switch_delay_ms": 500.0,
    "turn_delay_ms": 200.0,
    "wrap_delay_ms": 400.0,
    "reset_origin": False,
    "reset_esc_delay_ms": 500.0,
    "reset_ret_delay_ms": 800.0,
}

def shared_move_settings_path() -> Path:
    """OrganizerとBridgeが共通利用する移動設定ファイル。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Livery-Organizer-for-FH6" / "navigator-bridge-settings.json"
    return Path.home() / ".livery-organizer-for-fh6" / "navigator-bridge-settings.json"

def load_shared_move_settings() -> dict:
    settings = dict(SHARED_MOVE_SETTINGS_DEFAULTS)
    path = shared_move_settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        return settings

    def number(name: str, minimum: float, maximum: float) -> None:
        try:
            value = float(raw.get(name, settings[name]))
        except (TypeError, ValueError):
            return
        if minimum <= value <= maximum:
            settings[name] = value

    number("interval_ms", 10.0, 2000.0)
    number("switch_delay_ms", 0.0, 5000.0)
    number("turn_delay_ms", 0.0, 5000.0)
    number("wrap_delay_ms", 0.0, 5000.0)
    number("reset_esc_delay_ms", 0.0, 5000.0)
    number("reset_ret_delay_ms", 0.0, 5000.0)
    if isinstance(raw.get("reset_origin"), bool):
        settings["reset_origin"] = raw["reset_origin"]
    return settings

def save_shared_move_settings(settings: dict) -> None:
    clean = dict(SHARED_MOVE_SETTINGS_DEFAULTS)
    clean.update(settings or {})
    # 保存直前にも許容範囲を固定し、壊れた設定を共通ファイルへ残しません。
    validators = {
        "interval_ms": (10.0, 2000.0),
        "switch_delay_ms": (0.0, 5000.0),
        "turn_delay_ms": (0.0, 5000.0),
        "wrap_delay_ms": (0.0, 5000.0),
        "reset_esc_delay_ms": (0.0, 5000.0),
        "reset_ret_delay_ms": (0.0, 5000.0),
    }
    for name, (minimum, maximum) in validators.items():
        value = float(clean[name])
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} が許容範囲外です。")
        clean[name] = value
    clean["reset_origin"] = bool(clean["reset_origin"])

    path = shared_move_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": 1,
        "app": "Livery Organizer for FH6 / Navigator Bridge for FH6",
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        **clean,
    }
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)

def move_settings_from_args(args: argparse.Namespace) -> dict:
    return {
        "interval_ms": float(getattr(args, "interval_ms", 50.0)),
        "switch_delay_ms": float(getattr(args, "switch_delay_ms", 500.0)),
        "turn_delay_ms": float(getattr(args, "turn_delay_ms", 200.0)),
        "wrap_delay_ms": float(getattr(args, "wrap_delay_ms", 400.0)),
        "reset_origin": bool(getattr(args, "reset_origin", False)),
        "reset_esc_delay_ms": float(getattr(args, "reset_esc_delay_ms", 500.0)),
        "reset_ret_delay_ms": float(getattr(args, "reset_ret_delay_ms", 800.0)),
    }

APP_ICON_B64 = """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"""

# Windows virtual-key codes
VK_ESCAPE = 0x1B
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_RETURN = 0x0D

# Safety boundary:
# - movement requests can resolve ONLY to LEFT / RIGHT / DOWN.
# - the optional origin reset is a fixed ESC -> RETURN sequence; neither key is accepted
#   as an arbitrary movement command or external key parameter.
ALLOWED_MOVEMENT_VKS = frozenset({VK_LEFT, VK_RIGHT, VK_DOWN})
ALLOWED_MOVEMENT_KEY_NAMES = frozenset({"LEFT", "RIGHT", "DOWN"})
ALLOWED_INTERNAL_SEND_VKS = frozenset({VK_ESCAPE, VK_LEFT, VK_RIGHT, VK_DOWN, VK_RETURN})

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0
SW_RESTORE = 9


IS_WINDOWS = sys.platform == "win32"

# ULONG_PTR は 32/64bit でサイズが変わる。
ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    # SendInput の cbSize は Win32 INPUT 構造体全体のサイズを要求する。
    # KEYBDINPUT だけのUnionにすると x64 で32 bytesとなり、
    # 正しい40 bytesにならないため ERROR_INVALID_PARAMETER (87) になる。
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]


if IS_WINDOWS:
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
else:
    WNDENUMPROC = None
    user32 = None
    kernel32 = None



def set_windows_app_identity() -> None:
    if not IS_WINDOWS:
        return
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        fn = shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = [wintypes.LPCWSTR]
        fn.restype = ctypes.HRESULT
        fn(APP_USER_MODEL_ID)
    except Exception:
        pass


def set_app_icon(root: tk.Tk) -> None:
    try:
        icon = tk.PhotoImage(data=APP_ICON_B64)
        root.iconphoto(True, icon)
        root._fh6_navigator_icon = icon  # keep a reference
    except Exception:
        pass


def get_window_title(hwnd: int) -> str:
    if not IS_WINDOWS or user32 is None or not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value.strip(" ")


def is_fh6_window_title(title: str) -> bool:
    """FH6の既知タイトルと、前後空白を除いて完全一致する場合だけTrue。"""
    return str(title or "").strip(" ") == FH6_WINDOW_TITLE


def is_fh6_process_image_path(path: Path | str | None) -> bool:
    """Return True only for the public FH6 game executable name.

    Both the Steam public launch configuration and Xbox/Microsoft Store installs
    use forzahorizon6.exe.  Only the basename is checked so install-directory
    differences do not matter.
    """
    if path is None:
        return False
    basename = ntpath.basename(str(path).strip()).casefold()
    return basename == FH6_PROCESS_IMAGE_NAME.casefold()


def get_window_process_id(hwnd: int) -> int:
    """Best-effort owning process id for a top-level window."""
    if not IS_WINDOWS or user32 is None or not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not thread_id:
        return 0
    return int(pid.value or 0)


def get_window_process_image_path(hwnd: int) -> Path | None:
    """Best-effort image path of the process that owns hwnd."""
    return _windows_process_image_path(get_window_process_id(hwnd))


def is_fh6_window_identity(hwnd: int) -> bool:
    """Require both the exact FH6 title and the known FH6 process image name."""
    return is_fh6_window_title(get_window_title(hwnd)) and is_fh6_process_image_path(
        get_window_process_image_path(hwnd)
    )


def find_fh6_windows() -> list[tuple[int, str]]:
    """Return visible top-level windows that pass title + process identity checks."""
    if not IS_WINDOWS or user32 is None:
        return []

    found: list[tuple[int, str]] = []
    callback_type = WNDENUMPROC
    if callback_type is None:
        return []

    @callback_type
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = get_window_title(hwnd)
        if is_fh6_window_title(title) and is_fh6_process_image_path(
            get_window_process_image_path(hwnd)
        ):
            found.append((int(hwnd), title))
        return True

    user32.EnumWindows(enum_proc, 0)
    found.sort(key=lambda x: x[0])
    return found


def select_unique_fh6_window(windows: list[tuple[int, str]]) -> tuple[int, str]:
    """Require exactly one exact-title FH6 candidate before any foreground activation.

    v0.0.27 already rejects partial title matches.  r01 also refuses to choose an
    arbitrary HWND when more than one exact-title candidate exists, because doing so
    would make the key-input destination ambiguous.
    """
    candidates = list(windows or [])
    if not candidates:
        raise RuntimeError(
            "タイトルが「Forza Horizon 6」と完全一致し、所有プロセスが "
            "forzahorizon6.exe のウィンドウが見つかりません。\n"
            "FH6を起動し、「マイデザイン」画面を開いてから再実行してください。"
        )
    if len(candidates) != 1:
        raise RuntimeError(
            "FH6のタイトルとプロセス条件に一致するウィンドウが複数見つかりました。\n"
            "誤送信防止のため、Bridgeは移動先を自動選択しません。\n"
            "FH6以外の同名ウィンドウを閉じてから再実行してください。"
        )
    return candidates[0]


def activate_fh6_window(hwnd: int) -> None:
    """Best-effort foreground activation. Caller must verify foreground before SendInput."""
    if not IS_WINDOWS or user32 is None or kernel32 is None:
        raise RuntimeError("FH6ウィンドウの切り替えはWindows上でのみ利用できます。")
    if not hwnd:
        raise RuntimeError("FH6ウィンドウのハンドルが無効です。")

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    current_tid = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_tid = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached: list[int] = []

    try:
        # Foreground-lock restrictions are easier to clear by temporarily joining input queues.
        for tid in (foreground_tid, target_tid):
            if tid and tid != current_tid and tid not in attached:
                if user32.AttachThreadInput(current_tid, tid, True):
                    attached.append(tid)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for tid in reversed(attached):
            user32.AttachThreadInput(current_tid, tid, False)


def is_foreground_window(hwnd: int) -> bool:
    if not IS_WINDOWS or user32 is None:
        return False
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def is_foreground_fh6_window(hwnd: int) -> bool:
    """Foreground handle, exact title, and owning process must still identify FH6."""
    return is_foreground_window(hwnd) and is_fh6_window_identity(hwnd)

@dataclass(frozen=True)
class TargetPosition:
    slot: int
    column: int
    row: str  # U / D


@dataclass(frozen=True)
class MovePlan:
    target: TargetPosition
    last_slot: int
    last_column: int
    horizontal_key: str | None
    horizontal_presses: int
    vertical_key: str | None
    vertical_presses: int

    @property
    def total_presses(self) -> int:
        return self.horizontal_presses + self.vertical_presses


def slot_to_position(slot: int) -> TargetPosition:
    if slot < 1:
        raise ValueError("実スロット番号は1以上で指定してください。")
    column = (slot + 1) // 2
    row = "U" if slot % 2 == 1 else "D"
    return TargetPosition(slot=slot, column=column, row=row)


def position_to_slot(column: int, row: str) -> int:
    if column < 1:
        raise ValueError("列番号は1以上で指定してください。")
    row = row.upper()
    if row not in {"U", "D"}:
        raise ValueError("行は U または D で指定してください。")
    return column * 2 - (1 if row == "U" else 0)


def format_last_position(slot: int) -> str:
    """Format a real slot number as the FH6 column/row position used by the preview.

    Keep this as a thin wrapper around slot_to_position() so the GUI preview and
    movement calculation always use the same slot-to-position rule.
    """
    position = slot_to_position(slot)
    return f"#{position.column:03d}{position.row}"


def running_as_packaged_executable() -> bool:
    """Return True for PyInstaller-style frozen apps and Nuitka-compiled modules.

    Nuitka intentionally does not set sys.frozen.  Its documented runtime
    marker is the module-level __compiled__ attribute.
    """
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__") is not None)


def _windows_process_image_path(pid: int) -> Path | None:
    """Read a process image path through the Windows Unicode API."""
    if os.name != "nt" or pid <= 0:
        return None

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE

    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_image.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None

    try:
        capacity = 32768
        buffer = ctypes.create_unicode_buffer(capacity)
        size = wintypes.DWORD(capacity)
        if not query_image(handle, 0, buffer, ctypes.byref(size)):
            return None
        value = buffer.value.strip()
        return Path(value) if value else None
    finally:
        close_handle(handle)


def _windows_process_parent_map() -> dict[int, int]:
    """Return {pid: parent_pid} from the Windows Unicode Toolhelp snapshot."""
    if os.name != "nt":
        return {}

    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    snapshot_fn = kernel32.CreateToolhelp32Snapshot
    snapshot_fn.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snapshot_fn.restype = wintypes.HANDLE

    first_fn = kernel32.Process32FirstW
    first_fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    first_fn.restype = wintypes.BOOL

    next_fn = kernel32.Process32NextW
    next_fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    next_fn.restype = wintypes.BOOL

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    snapshot = snapshot_fn(TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    snapshot_value = ctypes.cast(snapshot, ctypes.c_void_p).value
    if snapshot_value == invalid_handle:
        return {}

    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = bool(first_fn(snapshot, ctypes.byref(entry)))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = bool(next_fn(snapshot, ctypes.byref(entry)))
    finally:
        close_handle(snapshot)

    return parents


def _windows_process_ancestry(max_depth: int = 8) -> list[dict[str, object]]:
    """Return parent-process ancestry using only Win32 process APIs."""
    if os.name != "nt":
        return []

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD

    parents = _windows_process_parent_map()
    pid = int(kernel32.GetCurrentProcessId())
    result: list[dict[str, object]] = []

    seen: set[int] = set()
    for _ in range(max(1, int(max_depth))):
        if pid in seen:
            break
        seen.add(pid)

        parent_pid = int(parents.get(pid, 0) or 0)
        if parent_pid <= 0 or parent_pid == pid:
            break

        image = _windows_process_image_path(parent_pid)
        result.append(
            {
                "pid": parent_pid,
                "image": str(image) if image is not None else "",
            }
        )
        pid = parent_pid

    return result


def _windows_find_packaged_executable_from_ancestry() -> Path | None:
    """Find the original onefile bootstrap EXE by walking parent processes."""
    wanted = PACKAGED_EXE_FILENAME.casefold()
    for item in _windows_process_ancestry():
        image_text = str(item.get("image", "") or "")
        if not image_text:
            continue
        image = Path(image_text)
        if image.name.casefold() == wanted:
            return image
    return None


def packaged_executable_path() -> Path:
    """Return the original packaged executable path.

    Official Windows builds use Nuitka onefile.  The unpacked executable is
    a child of the original onefile bootstrap.  Prefer a Win32 process-tree
    walk and QueryFullProcessImageNameW so the original path is recovered as
    Unicode directly from Windows, independent of Nuitka/Python argv/path
    conversions.

    Nuitka-specific values are only fallback paths.
    """
    ancestry_path = _windows_find_packaged_executable_from_ancestry()
    if ancestry_path is not None:
        return ancestry_path

    parent_pid_text = str(os.environ.get("NUITKA_ONEFILE_PARENT", "") or "").strip()
    if parent_pid_text:
        try:
            parent_path = _windows_process_image_path(int(parent_pid_text))
        except (TypeError, ValueError, OSError):
            parent_path = None
        if parent_path is not None and parent_path.name.casefold() == PACKAGED_EXE_FILENAME.casefold():
            return parent_path

    compiled = globals().get("__compiled__")
    containing_dir = getattr(compiled, "containing_dir", None) if compiled is not None else None
    if containing_dir:
        return Path(str(containing_dir)) / PACKAGED_EXE_FILENAME

    argv0 = str(sys.argv[0] if sys.argv else "").strip()
    if argv0:
        return Path(argv0).resolve()
    return Path(sys.executable).resolve()


def protocol_self_test_diagnostics() -> dict[str, object]:
    """Return detailed non-destructive protocol path diagnostics."""
    compiled = globals().get("__compiled__")
    containing_dir = getattr(compiled, "containing_dir", None) if compiled is not None else None
    original_argv0 = getattr(compiled, "original_argv0", None) if compiled is not None else None

    ancestry = []
    try:
        ancestry = _windows_process_ancestry()
    except Exception as exc:
        ancestry = [{"error": f"{type(exc).__name__}: {exc}"}]

    parent_env = str(os.environ.get("NUITKA_ONEFILE_PARENT", "") or "")
    env_parent_image = ""
    if parent_env:
        try:
            env_image = _windows_process_image_path(int(parent_env))
            env_parent_image = str(env_image) if env_image is not None else ""
        except Exception as exc:
            env_parent_image = f"<error {type(exc).__name__}: {exc}>"

    try:
        packaged = str(packaged_executable_path())
    except Exception as exc:
        packaged = f"<error {type(exc).__name__}: {exc}>"

    return {
        "app_version": APP_VERSION,
        "os_name": os.name,
        "sys_executable": str(sys.executable),
        "argv0": str(sys.argv[0] if sys.argv else ""),
        "nuitka_onefile_parent": parent_env,
        "nuitka_parent_image": env_parent_image,
        "compiled_containing_dir": "" if containing_dir is None else str(containing_dir),
        "compiled_original_argv0": "" if original_argv0 is None else str(original_argv0),
        "process_ancestry": ancestry,
        "packaged_executable_path": packaged,
        "protocol_command": protocol_handler_command(),
    }


def protocol_handler_command() -> str:
    """Return the per-user custom URL protocol command for this build."""
    if running_as_packaged_executable():
        return f'"{packaged_executable_path()}" --uri "%1"'

    script = Path(__file__).resolve()
    python_exe = Path(sys.executable).resolve()
    if python_exe.name.lower() == "python.exe":
        pythonw = python_exe.with_name("pythonw.exe")
        if pythonw.exists():
            python_exe = pythonw
    return f'"{python_exe}" "{script}" --uri "%1"'


def protocol_root_for_scheme(scheme: str) -> str:
    return rf"Software\Classes\{scheme}"


def read_registered_protocol_command(scheme: str = PROTOCOL_SCHEME) -> str:
    if not IS_WINDOWS or winreg is None:
        return ""
    try:
        root = protocol_root_for_scheme(scheme)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + r"\shell\open\command") as key:
            value, _ = winreg.QueryValueEx(key, None)
            return str(value or "")
    except OSError:
        return ""


def protocol_command_looks_like_our_legacy_tool(command: str) -> bool:
    """旧スキームを削除してよいのは、当ツール系列を指している場合だけです。"""
    text = str(command or "").casefold()
    if not text:
        return False
    markers = (
        "navigator-bridge-for-fh6",
        "fh6-my-designs-navigator",
    )
    return any(marker in text for marker in markers)


def protocol_is_registered_for_this_build() -> bool:
    actual = read_registered_protocol_command().strip()
    expected = protocol_handler_command().strip()
    return bool(actual and actual.casefold() == expected.casefold())


def execution_format_label() -> str:
    """Return a short GUI label for the current launch form."""
    return "Windows EXE" if running_as_packaged_executable() else "Python"


def protocol_registration_target_display(command: str) -> str:
    """Extract the Bridge file target from a registered protocol command."""
    text = str(command or "").strip()
    if not text:
        return "未登録"

    quoted = re.findall(r'"([^"]+)"', text)

    # Prefer our actual Bridge file.  Python mode has pythonw.exe first and
    # the Bridge .py file second, so simply showing argv[0] would be misleading.
    for candidate in quoted:
        lowered = candidate.casefold()
        if "navigator-bridge-for-fh6" in lowered and lowered.endswith((".exe", ".py")):
            return candidate

    # Fallback to the first quoted executable/path, then the raw command.
    if quoted:
        return quoted[0]
    return text


def register_protocol() -> None:
    if not IS_WINDOWS or winreg is None:
        raise RuntimeError("Organizer連携の登録はWindows専用です。")
    command = protocol_handler_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROTOCOL_ROOT) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f"URL:{APP_NAME} Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROTOCOL_ROOT + r"\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)

    # 開発中の旧スキームは、当ツール系列を指していると確認できた場合だけ削除します。
    for legacy_scheme in LEGACY_PROTOCOL_SCHEMES:
        legacy_command = read_registered_protocol_command(legacy_scheme)
        if protocol_command_looks_like_our_legacy_tool(legacy_command):
            _delete_registry_tree(winreg.HKEY_CURRENT_USER, protocol_root_for_scheme(legacy_scheme))


def _delete_registry_tree(root, subkey: str) -> None:
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
        for child in children:
            _delete_registry_tree(root, subkey + "\\" + child)
        winreg.DeleteKey(root, subkey)
    except FileNotFoundError:
        return


def unregister_protocol() -> None:
    if not IS_WINDOWS or winreg is None:
        raise RuntimeError("Organizer連携の解除はWindows専用です。")
    _delete_registry_tree(winreg.HKEY_CURRENT_USER, PROTOCOL_ROOT)
    for legacy_scheme in LEGACY_PROTOCOL_SCHEMES:
        legacy_command = read_registered_protocol_command(legacy_scheme)
        if protocol_command_looks_like_our_legacy_tool(legacy_command):
            _delete_registry_tree(winreg.HKEY_CURRENT_USER, protocol_root_for_scheme(legacy_scheme))


def apply_protocol_uri(args: argparse.Namespace) -> argparse.Namespace:
    uri = str(getattr(args, "uri", "") or "").strip()
    if not uri:
        return args
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.casefold() != PROTOCOL_SCHEME:
        raise ValueError(f"未対応の連携URIです: {parsed.scheme or 'schemeなし'}")
    action = (parsed.netloc or parsed.path.lstrip("/")).casefold()
    if action not in {"move", "open", "settings"}:
        raise ValueError(f"未対応の連携操作です: {action or 'なし'}")
    args.protocol_action = action
    query = urllib.parse.parse_qs(parsed.query)
    target = (query.get("target") or [""])[0].strip()
    last_slot_raw = (query.get("last_slot") or query.get("last-slot") or [""])[0].strip()
    if target:
        args.target = target
    if last_slot_raw:
        args.last_slot = int(normalize_ascii_digits(last_slot_raw))
    timing_fields = {
        "interval_ms": ("interval_ms", "interval-ms"),
        "switch_delay_ms": ("switch_delay_ms", "switch-delay-ms"),
        "turn_delay_ms": ("turn_delay_ms", "turn-delay-ms"),
        "wrap_delay_ms": ("wrap_delay_ms", "wrap-delay-ms"),
        "reset_esc_delay_ms": ("reset_esc_delay_ms", "reset-esc-delay-ms"),
        "reset_ret_delay_ms": ("reset_ret_delay_ms", "reset-ret-delay-ms"),
    }
    for attr, keys in timing_fields.items():
        raw = ""
        for key in keys:
            raw = (query.get(key) or [""])[0].strip()
            if raw:
                break
        if raw:
            setattr(args, attr, float(normalize_ascii_digits(raw)))

    auto_raw = (query.get("autostart") or query.get("auto") or ["0"])[0].strip().casefold()
    args.autostart = auto_raw in {"1", "true", "yes", "on"}
    reset_raw = (query.get("reset_origin") or query.get("reset-origin") or ["0"])[0].strip().casefold()
    args.reset_origin = reset_raw in {"1", "true", "yes", "on"}
    args.from_protocol = True

    # The URI deliberately accepts positions/timings plus a boolean request for the fixed
    # ESC -> RETURN origin-reset sequence. It has no key/keycode/key-sequence parameter.
    # Move planning can resolve only to LEFT / RIGHT / DOWN.
    return args



def navigator_local_data_dir() -> Path:
    """Per-user writable directory used only for same-PC instance handoff."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Navigator-Bridge-for-FH6"
    return Path.home() / ".navigator-bridge-for-fh6"


def ipc_queue_dir() -> Path:
    return navigator_local_data_dir() / IPC_DIR_NAME


def clear_stale_ipc_commands(max_age_s: float = 60.0) -> None:
    """Delete only genuinely stale handoff files so a just-enqueued request is never lost."""
    queue = ipc_queue_dir()
    now = time.time()
    try:
        queue.mkdir(parents=True, exist_ok=True)
        for path in queue.glob(f"{IPC_COMMAND_PREFIX}*.json"):
            try:
                age = now - path.stat().st_mtime
                if age >= max_age_s:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _args_to_ipc_payload(args: argparse.Namespace) -> dict:
    has_move = bool(str(getattr(args, "target", "") or "").strip()) or bool(getattr(args, "autostart", False))
    return {
        "action": "move" if has_move else "activate",
        "target": str(getattr(args, "target", "") or ""),
        "last_slot": getattr(args, "last_slot", None),
        "interval_ms": float(getattr(args, "interval_ms", 50.0)),
        "switch_delay_ms": float(getattr(args, "switch_delay_ms", 500.0)),
        "turn_delay_ms": float(getattr(args, "turn_delay_ms", 200.0)),
        "wrap_delay_ms": float(getattr(args, "wrap_delay_ms", 400.0)),
        "reset_origin": bool(getattr(args, "reset_origin", False)),
        "reset_esc_delay_ms": float(getattr(args, "reset_esc_delay_ms", 500.0)),
        "reset_ret_delay_ms": float(getattr(args, "reset_ret_delay_ms", 800.0)),
        "autostart": bool(getattr(args, "autostart", False)),
        "created_at": time.time(),
    }


def enqueue_ipc_command(args: argparse.Namespace) -> Path:
    queue = ipc_queue_dir()
    queue.mkdir(parents=True, exist_ok=True)
    target = queue / f"{IPC_COMMAND_PREFIX}{time.time_ns()}-{uuid.uuid4().hex}.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(_args_to_ipc_payload(args), ensure_ascii=False), encoding="utf-8")
    temp.replace(target)
    return target


def acquire_single_instance_mutex():
    """Return (handle, already_exists). Windows only; no-op elsewhere."""
    if not IS_WINDOWS:
        return None, False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    # ERROR_ALREADY_EXISTS = 183. ctypes' last-error value is captured because use_last_error=True.
    already_exists = ctypes.get_last_error() == 183
    return handle, already_exists


def close_mutex_handle(handle) -> None:
    if not IS_WINDOWS or not handle:
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)

def normalize_ascii_digits(text: str) -> str:
    # 全角数字・全角#も入力しやすいようASCIIへ寄せる。
    trans = str.maketrans("０１２３４５６７８９＃ｕｄＵＤ", "0123456789#udUD")
    return text.translate(trans)


def parse_target(text: str) -> TargetPosition:
    s = normalize_ascii_digits(text).strip().upper()
    s = re.sub(r"\s+", "", s)
    if not s:
        raise ValueError("移動先を入力してください。")

    # 537 / #537 = 実スロット番号
    m = re.fullmatch(r"#?(\d+)", s)
    if m:
        return slot_to_position(int(m.group(1)))

    # 269U / #269D = FH6位置
    m = re.fullmatch(r"#?(\d+)([UD])", s)
    if m:
        column = int(m.group(1))
        row = m.group(2)
        slot = position_to_slot(column, row)
        return TargetPosition(slot=slot, column=column, row=row)

    raise ValueError("移動先は 537 / #537 / 269U / #269D の形式で入力してください。")


def build_plan(target_text: str, last_slot: int) -> MovePlan:
    if not 1 <= last_slot <= 1000:
        raise ValueError("最終実スロット番号は 1～1000 の範囲で指定してください。")

    target = parse_target(target_text)
    if target.slot > last_slot:
        raise ValueError(
            f"移動先 #{target.slot} / #{target.column:03d}{target.row} は、"
            f"最終実スロット #{last_slot} を超えています。"
        )

    last_column = (last_slot + 1) // 2

    # 開始位置は 001U。
    # 右方向: 001 -> 002 -> ... -> target
    right_presses = target.column - 1

    # 左方向: 001 -> 最終列（1回）-> ... -> target
    # target が001列なら移動不要なので0。
    left_presses = 0 if target.column == 1 else (last_column - target.column + 1)

    if right_presses <= left_presses:
        horizontal_key = "RIGHT" if right_presses else None
        horizontal_presses = right_presses
    else:
        horizontal_key = "LEFT"
        horizontal_presses = left_presses

    # 起点がUなのでDだけ1回下へ。
    vertical_key = "DOWN" if target.row == "D" else None
    vertical_presses = 1 if target.row == "D" else 0

    return MovePlan(
        target=target,
        last_slot=last_slot,
        last_column=last_column,
        horizontal_key=horizontal_key,
        horizontal_presses=horizontal_presses,
        vertical_key=vertical_key,
        vertical_presses=vertical_presses,
    )


def key_name_to_vk(name: str) -> int:
    """Map only the three explicitly permitted FH6 movement keys."""
    key = str(name or "").upper()
    if key not in ALLOWED_MOVEMENT_KEY_NAMES:
        raise ValueError(f"安全境界により移動キーとして送信できません: {key or '未指定'}")
    return {
        "LEFT": VK_LEFT,
        "RIGHT": VK_RIGHT,
        "DOWN": VK_DOWN,
    }[key]


def _send_allowed_vk(vk: int) -> None:
    """Low-level sender restricted to the five internally permitted VKs."""
    if vk not in ALLOWED_INTERNAL_SEND_VKS:
        raise ValueError(f"安全境界により送信できない仮想キーです: 0x{int(vk):02X}")
    if not IS_WINDOWS or user32 is None:
        raise RuntimeError("キー送信はWindows上でのみ利用できます。")

    expected_input_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    actual_input_size = ctypes.sizeof(INPUT)
    if actual_input_size != expected_input_size:
        raise RuntimeError(
            f"内部エラー: INPUT構造体サイズが不正です "
            f"({actual_input_size} bytes / expected {expected_input_size} bytes)。"
        )

    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    if not scan:
        raise RuntimeError(f"仮想キー 0x{vk:02X} のスキャンコードを取得できませんでした。")

    extended = KEYEVENTF_EXTENDEDKEY if vk in ALLOWED_MOVEMENT_VKS else 0
    down = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=0,
            wScan=scan,
            dwFlags=KEYEVENTF_SCANCODE | extended,
            time=0,
            dwExtraInfo=0,
        ),
    )
    up = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=0,
            wScan=scan,
            dwFlags=KEYEVENTF_SCANCODE | extended | KEYEVENTF_KEYUP,
            time=0,
            dwExtraInfo=0,
        ),
    )

    inputs = (INPUT * 2)(down, up)
    ctypes.set_last_error(0)
    sent = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
    if sent != 2:
        err = ctypes.get_last_error()
        if err:
            raise ctypes.WinError(err)
        raise RuntimeError(f"SendInput が {sent}/2 イベントしか送信できませんでした。")


def send_movement_key(vk: int) -> None:
    """Send only LEFT / RIGHT / DOWN as a position-movement key."""
    if vk not in ALLOWED_MOVEMENT_VKS:
        raise ValueError(f"安全境界により移動キーとして送信できません: 0x{int(vk):02X}")
    _send_allowed_vk(vk)


def send_fh6_movement_key(hwnd: int, vk: int) -> None:
    """Re-confirm foreground + exact title + FH6 process immediately before SendInput."""
    if not is_foreground_fh6_window(hwnd):
        raise RuntimeError(
            "FH6として前面確認できないため、安全のため移動キーを送信しません。"
        )
    send_movement_key(vk)


def send_origin_reset_step(step: str) -> None:
    """Send exactly one step of the fixed ESC -> RETURN origin reset sequence."""
    key = str(step or "").upper()
    mapping = {"ESC": VK_ESCAPE, "RET": VK_RETURN}
    if key not in mapping:
        raise ValueError(f"安全境界により初期位置リセットでは送信できないキーです: {key or '未指定'}")
    _send_allowed_vk(mapping[key])



class NavigatorApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.resizable(False, False)

        self.running = False
        self.abort_requested = False
        self.pending_ipc_payload = None
        self._shared_settings_save_job = None

        self.target_var = tk.StringVar(value=args.target or "")
        self.last_slot_var = tk.StringVar(value=str(args.last_slot) if args.last_slot else "")
        self.interval_var = tk.StringVar(value=str(args.interval_ms))
        self.switch_delay_var = tk.StringVar(value=str(args.switch_delay_ms))
        self.turn_delay_var = tk.StringVar(value=str(args.turn_delay_ms))
        self.wrap_delay_var = tk.StringVar(value=str(args.wrap_delay_ms))
        self.reset_origin_var = tk.BooleanVar(value=bool(getattr(args, "reset_origin", False)))
        self.reset_esc_delay_var = tk.StringVar(value=str(getattr(args, "reset_esc_delay_ms", 500.0)))
        self.reset_ret_delay_var = tk.StringVar(value=str(getattr(args, "reset_ret_delay_ms", 800.0)))
        self.plan_var = tk.StringVar(value="移動先と最終実スロット番号を入力してください。")
        self.operation_var = tk.StringVar(value="操作: —")
        self.status_var = tk.StringVar(value="待機中（タイトルが「Forza Horizon 6」と完全一致するウィンドウだけを検出します）")
        # Organizer連携欄で _build_ui() 中に参照するため、UI構築前に初期化する。
        self.protocol_status_var = tk.StringVar(value="Organizer連携: 確認中")
        self.execution_format_var = tk.StringVar(value=f"実行形式: {execution_format_label()}")
        self.protocol_target_var = tk.StringVar(value="連携登録先: 確認中")

        self._build_ui()
        self._bind_events()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._center_window()
        self.refresh_protocol_status()
        self.update_preview()
        self.root.after(IPC_POLL_MS, self._poll_ipc_commands)
        if bool(getattr(args, "autostart", False)):
            self.root.after(350, self.start_move)

    def _poll_ipc_commands(self) -> None:
        """Consume commands written by short-lived secondary instances."""
        try:
            queue = ipc_queue_dir()
            if queue.exists():
                commands = sorted(queue.glob(f"{IPC_COMMAND_PREFIX}*.json"), key=lambda p: p.name)
                for path in commands[:20]:
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        payload = None
                    finally:
                        try:
                            path.unlink()
                        except OSError:
                            pass
                    if isinstance(payload, dict):
                        self._handle_ipc_payload(payload)
        finally:
            try:
                self.root.after(IPC_POLL_MS, self._poll_ipc_commands)
            except tk.TclError:
                pass

    def _handle_ipc_payload(self, payload: dict) -> None:
        action = str(payload.get("action") or "move").casefold()
        if action == "activate":
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except tk.TclError:
                pass
            return

        if self.running:
            # Do not interrupt a sequence already being sent to FH6. Keep only the newest request.
            self.pending_ipc_payload = payload
            self.status_var.set("Organizerから新しい移動指示を受信しました。現在の移動完了後に実行します。")
            return
        self._apply_ipc_move_payload(payload)

    def _apply_ipc_move_payload(self, payload: dict) -> None:
        target = str(payload.get("target") or "").strip()
        last_slot = payload.get("last_slot")
        if target:
            self.target_var.set(target)
        if last_slot not in (None, ""):
            self.last_slot_var.set(str(last_slot))
        self.reset_origin_var.set(bool(payload.get("reset_origin", False)))
        for key, variable in (
            ("interval_ms", self.interval_var),
            ("switch_delay_ms", self.switch_delay_var),
            ("turn_delay_ms", self.turn_delay_var),
            ("wrap_delay_ms", self.wrap_delay_var),
            ("reset_esc_delay_ms", self.reset_esc_delay_var),
            ("reset_ret_delay_ms", self.reset_ret_delay_var),
        ):
            value = payload.get(key)
            if value not in (None, ""):
                variable.set(f"{float(value):g}")
        self.update_preview()
        if bool(payload.get("autostart", True)):
            self.root.after(80, self.start_move)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.grid(sticky="nsew")

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        try:
            small_icon = tk.PhotoImage(data=APP_ICON_B64).subsample(3, 3)
            self._header_icon = small_icon
            ttk.Label(header, image=small_icon).pack(side="left", padx=(0, 8))
        except Exception:
            pass
        header_text = ttk.Frame(header)
        header_text.pack(side="left", fill="x", expand=True)
        ttk.Label(
            header_text,
            text=f"{APP_NAME} {APP_VERSION}",
            font=(GUI_FONT_FAMILY, 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header_text,
            text="リセットOFF時はFH6「マイデザイン」のカーソルを 001U にしてから実行してください。",
        ).pack(anchor="w", pady=(2, 0))

        settings = ttk.LabelFrame(outer, text="入力・共通移動設定", padding=10)
        settings.grid(row=1, column=0, sticky="ew")

        def setting_row(row: int, label: str, variable: tk.StringVar, width: int, unit: str, note: str):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="e", padx=(0, 10), pady=4)
            group = ttk.Frame(settings)
            group.grid(row=row, column=1, sticky="w", pady=4)
            entry = ttk.Entry(group, textvariable=variable, width=width)
            entry.pack(side="left")
            if unit:
                ttk.Label(group, text=unit).pack(side="left", padx=(6, 0))
            if note:
                ttk.Label(group, text=note, foreground="#555555").pack(side="left", padx=(8, 0))
            return entry

        self.target_entry = setting_row(0, "移動先", self.target_var, 18, "", "537 / #269U")
        setting_row(1, "最終実スロット番号", self.last_slot_var, 18, "", "例: 810（最大1000）")
        ttk.Separator(settings, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=8
        )
        setting_row(3, "FH6切替後の待ち時間", self.switch_delay_var, 10, "ms", "前面化後に待機。初期値500")
        setting_row(4, "キー間隔", self.interval_var, 10, "ms", "安定性を優先した初期値50")
        setting_row(5, "横→上下の待ち時間", self.turn_delay_var, 10, "ms", "例: 200")
        setting_row(6, "左循環後の追加待ち", self.wrap_delay_var, 10, "ms", "001→最終列の直後だけ。初期値400")
        ttk.Separator(settings, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=8
        )
        reset_group = ttk.Frame(settings)
        reset_group.grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 3))
        ttk.Checkbutton(
            reset_group,
            text="移動前にマイデザインを開き直して #001U へ戻す（ESC → RET）",
            variable=self.reset_origin_var,
        ).pack(side="left")
        setting_row(9, "ESC後の待ち時間", self.reset_esc_delay_var, 10, "ms", "初期値500")
        setting_row(10, "RET後の待ち時間", self.reset_ret_delay_var, 10, "ms", "初期値800。再入場後の待機")

        ttk.Label(
            settings,
            text=(
                "「FH6へ移動」でFH6を前面化します。通常移動は左・右・下のみ、リセットON時だけ固定の ESC → RET を移動前に1回実行します。\n"
                "FH6の画面内容や内部のカーソル位置は読み取らず、設定された間隔でキー入力を送るだけです。\n"
                "PCやFH6の負荷などで入力が取りこぼされると指定位置からずれる場合があります。ずれる場合は待ち時間を長めにしてください。\n"
                f"共通設定は自動保存されます: {shared_move_settings_path()}"
            ),
            foreground="#555555",
            wraplength=650,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))

        integration = ttk.LabelFrame(outer, text="Livery Organizer for FH6 連携", padding=9)
        integration.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        integration.columnconfigure(0, weight=1)
        ttk.Label(integration, textvariable=self.protocol_status_var).grid(row=0, column=0, sticky="w")
        integration_buttons = ttk.Frame(integration)
        integration_buttons.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.protocol_register_button = ttk.Button(integration_buttons, text="連携を登録", command=self.register_organizer_integration)
        self.protocol_register_button.pack(side="left")
        self.protocol_unregister_button = ttk.Button(integration_buttons, text="解除", command=self.unregister_organizer_integration)
        self.protocol_unregister_button.pack(side="left", padx=(6, 0))
        ttk.Label(
            integration,
            textvariable=self.execution_format_var,
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            integration,
            textvariable=self.protocol_target_var,
            foreground="#555555",
            wraplength=650,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        ttk.Label(
            integration,
            text=(
                "一度登録すると、Organizerの「FH6で選択デザインへ移動」から現在位置と最終実スロット数を受け取れます。\n"
                "Bridge本体を別フォルダへ移動・ファイル名変更した場合は、移動後の場所から「連携を登録」を再実行してください。"
            ),
            foreground="#555555",
            wraplength=650,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))

        plan_frame = ttk.LabelFrame(outer, text="移動計画", padding=10)
        plan_frame.grid(row=3, column=0, sticky="ew", pady=(12, 8))
        ttk.Label(plan_frame, textvariable=self.plan_var, justify="left", wraplength=650).grid(row=0, column=0, sticky="w")
        ttk.Label(
            plan_frame,
            textvariable=self.operation_var,
            justify="left",
            font=(GUI_FONT_FAMILY, 14, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        btns = ttk.Frame(outer)
        btns.grid(row=4, column=0, sticky="ew", pady=(6, 6))
        btns.columnconfigure(0, weight=1)

        self.preview_button = ttk.Button(btns, text="移動計画を確認", command=self.update_preview)
        self.preview_button.grid(row=0, column=0, sticky="w")
        self.start_button = ttk.Button(btns, text="FH6へ移動", command=self.start_move)
        self.start_button.grid(row=0, column=1, padx=(8, 0))
        self.abort_button = ttk.Button(btns, text="中止", command=self.request_abort, state="disabled")
        self.abort_button.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(
            outer,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=(6, 4),
        ).grid(row=5, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(
            outer,
            text="通常移動は左・右・下だけです。画面内容や内部位置は読み取らず、指定間隔でキー入力を送るため、PC/FH6の負荷で位置がずれる場合があります。",
            foreground="#555555",
        ).grid(row=6, column=0, sticky="w", pady=(8, 0))

    def refresh_protocol_status(self) -> None:
        self.execution_format_var.set(f"実行形式: {execution_format_label()}")

        if not IS_WINDOWS:
            self.protocol_status_var.set("Organizer連携: Windows専用")
            self.protocol_target_var.set("連携登録先: Windows専用")
            self.protocol_register_button.configure(state="disabled")
            self.protocol_unregister_button.configure(state="disabled")
            return

        current = read_registered_protocol_command()
        self.protocol_target_var.set(
            f"連携登録先: {protocol_registration_target_display(current)}"
        )

        if protocol_is_registered_for_this_build():
            self.protocol_status_var.set("Organizer連携: 登録済み")
            self.protocol_register_button.configure(state="disabled")
            self.protocol_unregister_button.configure(state="normal")
        else:
            legacy_owned = any(
                protocol_command_looks_like_our_legacy_tool(read_registered_protocol_command(scheme))
                for scheme in LEGACY_PROTOCOL_SCHEMES
            )
            if current:
                status = "Organizer連携: 再登録が必要"
            elif legacy_owned:
                status = "Organizer連携: 旧スキーム登録あり（再登録が必要）"
            else:
                status = "Organizer連携: 未登録"
            self.protocol_status_var.set(status)
            self.protocol_register_button.configure(state="normal")
            self.protocol_unregister_button.configure(state="normal" if (current or legacy_owned) else "disabled")

    def register_organizer_integration(self) -> None:
        try:
            register_protocol()
        except Exception as exc:
            show_app_error(self.root, f"Organizer連携を登録できませんでした。\n{exc}")
            return
        self.refresh_protocol_status()
        show_app_info(
            self.root,
            "Organizer連携を登録しました。\n"
            "Livery Organizer for FH6 のHTMLで「FH6で選択デザインへ移動」を実行すると、このBridgeへ位置を渡せます。\n\n"
            "Bridge本体を別フォルダへ移動・ファイル名変更した場合は、移動後の場所から再度「連携を登録」してください。",
        )

    def unregister_organizer_integration(self) -> None:
        try:
            unregister_protocol()
        except Exception as exc:
            show_app_error(self.root, f"Organizer連携を解除できませんでした。\n{exc}")
            return
        self.refresh_protocol_status()

    def _bind_events(self) -> None:
        for var in (
            self.target_var,
            self.last_slot_var,
            self.interval_var,
            self.switch_delay_var,
            self.turn_delay_var,
            self.wrap_delay_var,
            self.reset_origin_var,
            self.reset_esc_delay_var,
            self.reset_ret_delay_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_preview())
        for var in (
            self.interval_var,
            self.switch_delay_var,
            self.turn_delay_var,
            self.wrap_delay_var,
            self.reset_origin_var,
            self.reset_esc_delay_var,
            self.reset_ret_delay_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_shared_settings_save())

    def _schedule_preview(self) -> None:
        self.root.after_idle(self.update_preview)

    def _schedule_shared_settings_save(self) -> None:
        if self._shared_settings_save_job is not None:
            try:
                self.root.after_cancel(self._shared_settings_save_job)
            except tk.TclError:
                pass
        self._shared_settings_save_job = self.root.after(350, self._save_shared_settings_now)

    def _save_shared_settings_now(self) -> None:
        self._shared_settings_save_job = None
        try:
            settings = {
                "interval_ms": float(normalize_ascii_digits(self.interval_var.get()).strip()),
                "switch_delay_ms": float(normalize_ascii_digits(self.switch_delay_var.get()).strip()),
                "turn_delay_ms": float(normalize_ascii_digits(self.turn_delay_var.get()).strip()),
                "wrap_delay_ms": float(normalize_ascii_digits(self.wrap_delay_var.get()).strip()),
                "reset_origin": bool(self.reset_origin_var.get()),
                "reset_esc_delay_ms": float(normalize_ascii_digits(self.reset_esc_delay_var.get()).strip()),
                "reset_ret_delay_ms": float(normalize_ascii_digits(self.reset_ret_delay_var.get()).strip()),
            }
            save_shared_move_settings(settings)
        except (ValueError, OSError):
            # 入力途中の一時的な空欄・範囲外は保存せず、確定後の次回traceで再試行します。
            return

    def on_close(self) -> None:
        self._save_shared_settings_now()
        self.root.destroy()

    def _center_window(self) -> None:
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry(f"+{x}+{y}")

    def read_settings(self):
        try:
            last_slot = int(normalize_ascii_digits(self.last_slot_var.get()).strip())
        except ValueError:
            raise ValueError("最終実スロット番号は整数で入力してください。")

        try:
            interval_ms = float(normalize_ascii_digits(self.interval_var.get()).strip())
        except ValueError:
            raise ValueError("キー間隔は数値で入力してください。")

        try:
            switch_delay_ms = float(normalize_ascii_digits(self.switch_delay_var.get()).strip())
        except ValueError:
            raise ValueError("FH6切替後の待ち時間は数値で入力してください。")

        try:
            turn_delay_ms = float(normalize_ascii_digits(self.turn_delay_var.get()).strip())
        except ValueError:
            raise ValueError("横→上下の待ち時間は数値で入力してください。")

        try:
            wrap_delay_ms = float(normalize_ascii_digits(self.wrap_delay_var.get()).strip())
        except ValueError:
            raise ValueError("左循環後の追加待ちは数値で入力してください。")
        try:
            reset_esc_delay_ms = float(normalize_ascii_digits(self.reset_esc_delay_var.get()).strip())
        except ValueError:
            raise ValueError("ESC後の待ち時間は数値で入力してください。")
        try:
            reset_ret_delay_ms = float(normalize_ascii_digits(self.reset_ret_delay_var.get()).strip())
        except ValueError:
            raise ValueError("RET後の待ち時間は数値で入力してください。")

        if not 10 <= interval_ms <= 2000:
            raise ValueError("キー間隔は 10～2000 ms の範囲で指定してください。")
        if not 0 <= switch_delay_ms <= 5000:
            raise ValueError("FH6切替後の待ち時間は 0～5000 ms の範囲で指定してください。")
        if not 0 <= turn_delay_ms <= 5000:
            raise ValueError("横→上下の待ち時間は 0～5000 ms の範囲で指定してください。")
        if not 0 <= wrap_delay_ms <= 5000:
            raise ValueError("左循環後の追加待ちは 0～5000 ms の範囲で指定してください。")
        if not 0 <= reset_esc_delay_ms <= 5000:
            raise ValueError("ESC後の待ち時間は 0～5000 ms の範囲で指定してください。")
        if not 0 <= reset_ret_delay_ms <= 5000:
            raise ValueError("RET後の待ち時間は 0～5000 ms の範囲で指定してください。")

        plan = build_plan(self.target_var.get(), last_slot)
        return (plan, interval_ms, switch_delay_ms, turn_delay_ms, wrap_delay_ms,
                bool(self.reset_origin_var.get()), reset_esc_delay_ms, reset_ret_delay_ms)

    def update_preview(self) -> None:
        if self.running:
            return
        try:
            plan, interval_ms, _switch_delay_ms, turn_delay_ms, wrap_delay_ms, reset_origin, reset_esc_delay_ms, reset_ret_delay_ms = self.read_settings()
        except Exception as exc:
            self.plan_var.set(str(exc))
            self.operation_var.set("操作: —")
            return

        direction = {
            None: "横移動なし",
            "LEFT": f"◀ × {plan.horizontal_presses}",
            "RIGHT": f"▶ × {plan.horizontal_presses}",
        }[plan.horizontal_key]
        vertical = "　▼ × 1" if plan.vertical_presses else ""

        estimated_ms = 0.0
        if plan.horizontal_presses > 1:
            estimated_ms += (plan.horizontal_presses - 1) * interval_ms
        # 001列からLEFTを選ぶ場合、最初の1回は必ず最終列への循環。
        # 実機ではこの遷移だけ通常より時間がかかるため追加待ちを入れる。
        uses_left_wrap = plan.horizontal_key == "LEFT" and plan.horizontal_presses > 0
        if uses_left_wrap and plan.horizontal_presses > 1:
            estimated_ms += wrap_delay_ms
        if plan.horizontal_presses and plan.vertical_presses:
            estimated_ms += turn_delay_ms
        if reset_origin:
            estimated_ms += reset_esc_delay_ms + reset_ret_delay_ms

        wrap_note = f" / 左循環後 +{wrap_delay_ms:g}ms" if uses_left_wrap and plan.horizontal_presses > 1 else ""
        reset_note = (
            f" / 初期位置リセット ESC→RET（{reset_esc_delay_ms:g}ms / {reset_ret_delay_ms:g}ms）"
            if reset_origin else " / 初期位置リセット OFF"
        )
        reset_keys = 2 if reset_origin else 0
        self.plan_var.set(
            f"移動先: #{plan.target.slot} / #{plan.target.column:03d}{plan.target.row}\n"
            f"最終位置: #{plan.last_slot} / {format_last_position(plan.last_slot)}\n"
            f"送信キー数: {plan.total_presses + reset_keys}回 / 推定入力時間: 約 {estimated_ms / 1000:.2f} 秒{wrap_note}{reset_note}"
        )
        prefix = "ESC → RET　" if reset_origin else ""
        self.operation_var.set(f"操作: {prefix}{direction}{vertical}")

    def set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.preview_button.configure(state=state)
        self.abort_button.configure(state="normal" if running else "disabled")

    def request_abort(self) -> None:
        if self.running:
            self.abort_requested = True
            self.status_var.set("中止要求を受け付けました…")

    def start_move(self) -> None:
        if self.running:
            return
        if not IS_WINDOWS:
            show_app_error(self.root, "このユーティリティはWindows専用です。")
            return

        try:
            plan, interval_ms, switch_delay_ms, turn_delay_ms, wrap_delay_ms, reset_origin, reset_esc_delay_ms, reset_ret_delay_ms = self.read_settings()
            save_shared_move_settings({
                "interval_ms": interval_ms,
                "switch_delay_ms": switch_delay_ms,
                "turn_delay_ms": turn_delay_ms,
                "wrap_delay_ms": wrap_delay_ms,
                "reset_origin": reset_origin,
                "reset_esc_delay_ms": reset_esc_delay_ms,
                "reset_ret_delay_ms": reset_ret_delay_ms,
            })
        except Exception as exc:
            show_app_error(self.root, str(exc))
            return

        windows = find_fh6_windows()
        try:
            hwnd, title = select_unique_fh6_window(windows)
        except RuntimeError as exc:
            show_app_error(self.root, str(exc))
            self.status_var.set("FH6ウィンドウを一意に確認できなかったため、キー入力は行いませんでした。")
            return
        self.abort_requested = False
        self.set_running(True)
        self.status_var.set(f"FH6を検出: {title}。前面へ切り替えています…")

        try:
            activate_fh6_window(hwnd)
        except Exception as exc:
            self.set_running(False)
            show_app_error(self.root, f"FH6を前面へ切り替えられませんでした。\n{exc}")
            self.status_var.set("FH6の前面化に失敗したため、キー入力は行いませんでした。")
            return

        threading.Thread(
            target=self._move_worker,
            args=(
                hwnd,
                title,
                plan,
                interval_ms / 1000.0,
                switch_delay_ms / 1000.0,
                turn_delay_ms / 1000.0,
                wrap_delay_ms / 1000.0,
                reset_origin,
                reset_esc_delay_ms / 1000.0,
                reset_ret_delay_ms / 1000.0,
            ),
            daemon=True,
        ).start()

    def _should_abort(self) -> bool:
        return self.abort_requested

    def _sleep_abortable(self, seconds: float, chunk: float = 0.02) -> bool:
        end = time.perf_counter() + max(0.0, seconds)
        while time.perf_counter() < end:
            if self._should_abort():
                return False
            time.sleep(min(chunk, max(0.0, end - time.perf_counter())))
        return not self._should_abort()

    def _move_worker(
        self,
        hwnd: int,
        title: str,
        plan: MovePlan,
        interval_s: float,
        switch_delay_s: float,
        turn_delay_s: float,
        wrap_delay_s: float,
        reset_origin: bool,
        reset_esc_delay_s: float,
        reset_ret_delay_s: float,
    ) -> None:
        try:
            if switch_delay_s > 0:
                self._set_status_threadsafe(
                    f"FH6を前面化しました。{switch_delay_s * 1000:.0f}ms 待機しています…"
                )
                if not self._sleep_abortable(switch_delay_s):
                    self._finish("中止しました。")
                    return

            # Safety check: never send keys if FH6 did not actually become foreground.
            if not is_foreground_fh6_window(hwnd):
                self._finish(
                    f"安全のため中止: 「{title}」をFH6として前面確認できないためキー入力を送信しませんでした。",
                    error=True,
                )
                return

            if self._should_abort():
                self._finish("中止しました。")
                return

            done = 0
            total = plan.total_presses + (2 if reset_origin else 0)

            if reset_origin:
                if not is_foreground_fh6_window(hwnd):
                    self._finish("安全のため中止: 初期位置リセット前にFH6として前面確認できなくなりました。", error=True)
                    return
                self._set_status_threadsafe("初期位置リセット: ESC を送信…")
                send_origin_reset_step("ESC")
                done += 1
                if not self._sleep_abortable(reset_esc_delay_s):
                    self._finish(f"中止しました。{done}/{total}キー送信済み。")
                    return
                if not is_foreground_fh6_window(hwnd):
                    self._finish("安全のため中止: RET送信前にFH6として前面確認できなくなりました。", error=True)
                    return
                self._set_status_threadsafe("初期位置リセット: RET を送信…")
                send_origin_reset_step("RET")
                done += 1
                if not self._sleep_abortable(reset_ret_delay_s):
                    self._finish(f"中止しました。{done}/{total}キー送信済み。")
                    return
                if not is_foreground_fh6_window(hwnd):
                    self._finish("安全のため中止: マイデザイン再入場後にFH6として前面確認できなくなりました。", error=True)
                    return

            if plan.horizontal_key and plan.horizontal_presses:
                vk = key_name_to_vk(plan.horizontal_key)
                symbol = "◀" if plan.horizontal_key == "LEFT" else "▶"
                for i in range(plan.horizontal_presses):
                    if self._should_abort():
                        self._finish(f"中止しました。{done}/{total}キー送信済み。")
                        return

                    send_fh6_movement_key(hwnd, vk)
                    done += 1
                    self._set_status_threadsafe(
                        f"{symbol} {i + 1}/{plan.horizontal_presses}（全体 {done}/{total}）"
                    )

                    if i + 1 < plan.horizontal_presses:
                        delay_s = interval_s
                        if plan.horizontal_key == "LEFT" and i == 0:
                            delay_s += wrap_delay_s
                            if wrap_delay_s > 0:
                                self._set_status_threadsafe(
                                    f"◀ 1/{plan.horizontal_presses}：最終列への循環後 {wrap_delay_s * 1000:.0f}ms 追加待機"
                                )
                        if not self._sleep_abortable(delay_s):
                            self._finish(f"中止しました。{done}/{total}キー送信済み。")
                            return

            if plan.horizontal_presses and plan.vertical_presses and turn_delay_s > 0:
                self._set_status_threadsafe("横移動完了。上下移動まで待機中…")
                if not self._sleep_abortable(turn_delay_s):
                    self._finish(f"中止しました。{done}/{total}キー送信済み。")
                    return

            if plan.vertical_key and plan.vertical_presses:
                if self._should_abort():
                    self._finish(f"中止しました。{done}/{total}キー送信済み。")
                    return
                send_fh6_movement_key(hwnd, key_name_to_vk(plan.vertical_key))
                done += 1

            self._finish(
                f"完了: #{plan.target.slot} / #{plan.target.column:03d}{plan.target.row}（{done}キー送信）"
            )

        except Exception as exc:
            self._finish(f"エラー: {exc}", error=True)

    def _set_status_threadsafe(self, text: str) -> None:
        self.root.after(0, self.status_var.set, text)

    def _finish(self, text: str, error: bool = False) -> None:
        def finish_ui() -> None:
            self.status_var.set(text)
            self.set_running(False)
            if error:
                show_app_error(self.root, text)
            pending = self.pending_ipc_payload
            self.pending_ipc_payload = None
            if pending:
                self.root.after(120, lambda payload=pending: self._apply_ipc_move_payload(payload))
        self.root.after(0, finish_ui)



def bridge_log_path() -> Path:
    return navigator_local_data_dir() / "navigator-bridge-for-fh6.log"


def bridge_log(text: str) -> None:
    """Best-effort diagnostic log for headless Organizer launches."""
    try:
        path = bridge_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as fp:
            fp.write(f"[{stamp}] {text}\n")
    except Exception:
        pass


def show_bridge_error(text: str) -> None:
    """Show a readable large-font error when headless Bridge mode cannot safely move."""
    bridge_log("ERROR: " + text.replace("\n", " / "))
    show_app_error(None, text)


def validate_headless_args(args: argparse.Namespace) -> tuple[MovePlan, float, float, float, float, bool, float, float]:
    if getattr(args, "last_slot", None) is None:
        raise ValueError("最終実スロット番号が指定されていません。")
    plan = build_plan(str(getattr(args, "target", "") or ""), int(args.last_slot))
    interval_ms = float(getattr(args, "interval_ms", 50.0))
    switch_delay_ms = float(getattr(args, "switch_delay_ms", 500.0))
    turn_delay_ms = float(getattr(args, "turn_delay_ms", 200.0))
    wrap_delay_ms = float(getattr(args, "wrap_delay_ms", 400.0))
    reset_origin = bool(getattr(args, "reset_origin", False))
    reset_esc_delay_ms = float(getattr(args, "reset_esc_delay_ms", 500.0))
    reset_ret_delay_ms = float(getattr(args, "reset_ret_delay_ms", 800.0))
    if not 10 <= interval_ms <= 2000:
        raise ValueError("キー間隔は 10～2000 ms の範囲で指定してください。")
    if not 0 <= switch_delay_ms <= 5000:
        raise ValueError("FH6切替後の待ち時間は 0～5000 ms の範囲で指定してください。")
    if not 0 <= turn_delay_ms <= 5000:
        raise ValueError("横→上下の待ち時間は 0～5000 ms の範囲で指定してください。")
    if not 0 <= wrap_delay_ms <= 5000:
        raise ValueError("左循環後の追加待ちは 0～5000 ms の範囲で指定してください。")
    if not 0 <= reset_esc_delay_ms <= 5000:
        raise ValueError("ESC後の待ち時間は 0～5000 ms の範囲で指定してください。")
    if not 0 <= reset_ret_delay_ms <= 5000:
        raise ValueError("RET後の待ち時間は 0～5000 ms の範囲で指定してください。")
    return (plan, interval_ms / 1000.0, switch_delay_ms / 1000.0, turn_delay_ms / 1000.0,
            wrap_delay_ms / 1000.0, reset_origin, reset_esc_delay_ms / 1000.0, reset_ret_delay_ms / 1000.0)


def activate_fh6_window_confirmed(hwnd: int, timeout_s: float = 1.2) -> bool:
    """Retry Win32 foreground activation without synthesizing any extra keyboard input."""
    deadline = time.perf_counter() + max(0.2, timeout_s)
    while True:
        activate_fh6_window(hwnd)
        if is_foreground_fh6_window(hwnd):
            return True
        if time.perf_counter() >= deadline:
            return False
        time.sleep(0.08)


def execute_headless_move(args: argparse.Namespace) -> str:
    """Execute one Organizer request without creating or hiding a Tk application window."""
    if not IS_WINDOWS:
        raise RuntimeError("Navigator BridgeはWindows専用です。")
    plan, interval_s, switch_delay_s, turn_delay_s, wrap_delay_s, reset_origin, reset_esc_delay_s, reset_ret_delay_s = validate_headless_args(args)
    save_shared_move_settings(move_settings_from_args(args))
    windows = find_fh6_windows()
    hwnd, title = select_unique_fh6_window(windows)
    bridge_log(
        f"request target={plan.target.slot} position={plan.target.column:03d}{plan.target.row} "
        f"last_slot={plan.last_slot} interval_ms={interval_s*1000:g} reset_origin={int(reset_origin)} title={title!r}"
    )
    if not activate_fh6_window_confirmed(hwnd):
        raise RuntimeError(
            f"Forza Horizon 6 をフォアグラウンドへ切り替えられませんでした。\n"
            f"安全のためキー入力は送信していません。\n\n診断ログ: {bridge_log_path()}"
        )
    bridge_log("FH6 foreground confirmed")
    if switch_delay_s > 0:
        time.sleep(switch_delay_s)
    if not is_foreground_fh6_window(hwnd):
        raise RuntimeError(
            "FH6切替後の待機中にFH6として前面確認できなくなりました。\n"
            "安全のためキー入力は送信していません。"
        )

    done = 0
    if reset_origin:
        if not is_foreground_fh6_window(hwnd):
            raise RuntimeError("初期位置リセット前にFH6として前面確認できなくなったため、安全のため中止しました。")
        bridge_log("origin reset: ESC")
        send_origin_reset_step("ESC")
        done += 1
        if reset_esc_delay_s > 0:
            time.sleep(reset_esc_delay_s)
        if not is_foreground_fh6_window(hwnd):
            raise RuntimeError("RET送信前にFH6として前面確認できなくなったため、安全のため中止しました。")
        bridge_log("origin reset: RET")
        send_origin_reset_step("RET")
        done += 1
        if reset_ret_delay_s > 0:
            time.sleep(reset_ret_delay_s)
        if not is_foreground_fh6_window(hwnd):
            raise RuntimeError("マイデザイン再入場後にFH6として前面確認できなくなったため、安全のため中止しました。")

    if plan.horizontal_key and plan.horizontal_presses:
        vk = key_name_to_vk(plan.horizontal_key)
        for i in range(plan.horizontal_presses):
            if not is_foreground_fh6_window(hwnd):
                raise RuntimeError("移動中にFH6として前面確認できなくなったため、安全のため中止しました。")
            send_fh6_movement_key(hwnd, vk)
            done += 1
            if i + 1 < plan.horizontal_presses:
                delay_s = interval_s
                if plan.horizontal_key == "LEFT" and i == 0:
                    delay_s += wrap_delay_s
                if delay_s > 0:
                    time.sleep(delay_s)

    if plan.horizontal_presses and plan.vertical_presses and turn_delay_s > 0:
        time.sleep(turn_delay_s)

    if plan.vertical_key and plan.vertical_presses:
        if not is_foreground_fh6_window(hwnd):
            raise RuntimeError("上下移動前にFH6として前面確認できなくなったため、安全のため中止しました。")
        # key_name_to_vk() + send_fh6_movement_key() both enforce LEFT / RIGHT / DOWN only.
        send_fh6_movement_key(hwnd, key_name_to_vk(plan.vertical_key))
        done += 1

    result = f"complete target=#{plan.target.slot}/#{plan.target.column:03d}{plan.target.row} keys={done}"
    bridge_log(result)
    return result


def payload_to_args(payload: dict) -> argparse.Namespace:
    return argparse.Namespace(
        target=str(payload.get("target") or ""),
        last_slot=payload.get("last_slot"),
        interval_ms=float(payload.get("interval_ms", 50.0)),
        switch_delay_ms=float(payload.get("switch_delay_ms", 500.0)),
        turn_delay_ms=float(payload.get("turn_delay_ms", 200.0)),
        wrap_delay_ms=float(payload.get("wrap_delay_ms", 400.0)),
        reset_origin=bool(payload.get("reset_origin", False)),
        reset_esc_delay_ms=float(payload.get("reset_esc_delay_ms", 500.0)),
        reset_ret_delay_ms=float(payload.get("reset_ret_delay_ms", 800.0)),
        autostart=bool(payload.get("autostart", True)),
        from_protocol=True,
        uri=None,
    )


def pop_latest_ipc_move() -> argparse.Namespace | None:
    """Consume queued handoffs and return only the newest move request."""
    queue = ipc_queue_dir()
    if not queue.exists():
        return None
    newest = None
    for path in sorted(queue.glob(f"{IPC_COMMAND_PREFIX}*.json"), key=lambda p: p.name):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and str(payload.get("action") or "").casefold() == "move":
                newest = payload
        except Exception:
            pass
        finally:
            try:
                path.unlink()
            except OSError:
                pass
    return payload_to_args(newest) if isinstance(newest, dict) else None


def run_headless_bridge(args: argparse.Namespace) -> None:
    """Run Organizer Bridge mode directly, then service any request queued during the move."""
    current = args
    while current is not None:
        try:
            execute_headless_move(current)
        except Exception as exc:
            show_bridge_error(f"FH6への移動を実行できませんでした。\n\n{exc}")
        # A short grace period lets a near-simultaneous browser launch finish its queue write.
        time.sleep(0.18)
        current = pop_latest_ipc_move()

def parse_args() -> argparse.Namespace:
    shared = load_shared_move_settings()
    p = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    p.add_argument("--target", help="移動先。例: 537 / 269U")
    p.add_argument("--last-slot", type=int, help="最終実スロット番号（最大1000）")
    p.add_argument("--interval-ms", type=float, default=shared["interval_ms"], help=f"キー間隔ms（default: {shared['interval_ms']:g}）")
    p.add_argument("--switch-delay-ms", type=float, default=shared["switch_delay_ms"], help=f"FH6前面化後の待ち時間ms（default: {shared['switch_delay_ms']:g}）")
    p.add_argument("--turn-delay-ms", type=float, default=shared["turn_delay_ms"], help=f"横→上下の待ち時間ms（default: {shared['turn_delay_ms']:g}）")
    p.add_argument("--wrap-delay-ms", type=float, default=shared["wrap_delay_ms"], help=f"001→最終列の左循環後追加待ちms（default: {shared['wrap_delay_ms']:g}）")
    reset_group = p.add_mutually_exclusive_group()
    reset_group.add_argument("--reset-origin", dest="reset_origin", action="store_true", help="移動前に固定の ESC → RET でマイデザインを開き直し #001U へ戻す")
    reset_group.add_argument("--no-reset-origin", dest="reset_origin", action="store_false", help="初期位置リセットを行わない")
    p.set_defaults(reset_origin=bool(shared["reset_origin"]))
    p.add_argument("--reset-esc-delay-ms", type=float, default=shared["reset_esc_delay_ms"], help=f"初期位置リセットのESC後待ち時間ms（default: {shared['reset_esc_delay_ms']:g}）")
    p.add_argument("--reset-ret-delay-ms", type=float, default=shared["reset_ret_delay_ms"], help=f"初期位置リセットのRET後待ち時間ms（default: {shared['reset_ret_delay_ms']:g}）")
    p.add_argument("--uri", help="Livery Organizer for FH6 連携URI")
    p.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--protocol-self-test-output", help=argparse.SUPPRESS)
    p.add_argument("--protocol-self-test-diagnostics-output", help=argparse.SUPPRESS)
    args = p.parse_args()
    args.from_protocol = False
    args.protocol_action = ""
    return apply_protocol_uri(args)


def main() -> None:
    try:
        args = parse_args()
    except Exception as exc:
        show_bridge_error(f"Organizer連携の引数を読み取れませんでした。\n{exc}")
        return

    # Build-kit regression check: exercise the exact protocol command construction
    # from the compiled EXE without touching the registry or starting Tk.
    self_test_output = str(getattr(args, "protocol_self_test_output", "") or "").strip()
    self_test_diag_output = str(getattr(args, "protocol_self_test_diagnostics_output", "") or "").strip()
    if self_test_output or self_test_diag_output:
        try:
            if self_test_output:
                Path(self_test_output).write_text(protocol_handler_command(), encoding="utf-8")
            if self_test_diag_output:
                Path(self_test_diag_output).write_text(
                    json.dumps(protocol_self_test_diagnostics(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as exc:
            raise RuntimeError(f"protocol self-test output failed: {exc}") from exc
        return

    mutex_handle = None
    try:
        mutex_handle, already_exists = acquire_single_instance_mutex()
        if already_exists:
            # A running manual GUI or headless Bridge owns the mutex. Pass only validated
            # position/timing data through the local queue and terminate this short-lived process.
            try:
                enqueue_ipc_command(args)
            except Exception as exc:
                show_bridge_error(f"起動中のNavigator Bridgeへ指示を渡せませんでした。\n{exc}")
            return

        clear_stale_ipc_commands()
        set_windows_app_identity()

        if bool(getattr(args, "from_protocol", False)) and getattr(args, "protocol_action", "") == "settings":
            # HTMLからの明示的な共通設定保存。任意キーや移動先は受け付けず、
            # 許容範囲を検証したタイミング設定だけを永続化して終了します。
            save_shared_move_settings(move_settings_from_args(args))
            bridge_log(f"{APP_NAME} {APP_VERSION} shared settings synced from Organizer")
            return

        bridge_mode = bool(getattr(args, "from_protocol", False) and getattr(args, "autostart", False))
        if bridge_mode:
            # Important: Organizer launches do NOT create a Tk window at all. This avoids the
            # withdrawn-window/foreground-activation interaction that made v0.0.10 failures opaque.
            bridge_log(f"{APP_NAME} {APP_VERSION} headless start")
            run_headless_bridge(args)
            return

        root = tk.Tk()
        configure_gui_fonts(root)
        set_app_icon(root)
        app = NavigatorApp(root, args)
        app.target_entry.focus_set()
        root.mainloop()
    finally:
        close_mutex_handle(mutex_handle)


if __name__ == "__main__":
    main()
