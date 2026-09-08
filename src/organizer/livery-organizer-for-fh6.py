#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Livery Organizer for FH6 v0.4.60-r04
================================

非公式・非営利のファンメイド整理支援ツールです。
Microsoft、Xbox、Turn 10 Studios、Playground Games、Forzaとの提携・承認・後援を
受けた公式ソフトウェアではありません。

このツールは、利用者自身のFH6 Liveryデータを整理・確認しやすくすることを目的とします。
FH6 / Xbox GameSaveおよびゲーム本体の参照対象は読み取り専用で扱い、ゲームデータや
セーブデータへの書き込み、ゲーム進行・経済・報酬・ランキング・競争行為の自動化を
目的としません。

Microsoft、Xbox、Forzaおよび関連する名称・商標・著作物は、それぞれの権利者に帰属します。
利用者は、Microsoft / Xbox / Forzaの各利用規約および適用される法令を確認し、
自己の責任で本ツールを利用してください。

参考: Xbox ゲーム コンテンツ利用規約
https://www.xbox.com/ja-JP/developers/rules

任意の「Navigator Bridge for FH6」連携では、BridgeはForza Horizon 6を
フォアグラウンドへ切り替え、通常のマイデザイン位置移動ではカーソル「左」「右」「下」だけを
送信します。さらに利用者が「#001Uへ戻す」をONにした場合に限り、移動開始前の固定操作として
Escを1回、Return（RET/Enter）を1回、この順序で送信します。任意のキーコード・キー名・
キー順序を外部から指定する機能は持たせません。上・文字キー・ファンクションキーなどは
送信せず、最終的な確認・選択・削除は利用者が行います。

BridgeはFH6の画面内容を画像認識・解析したり、ゲーム内部のペイント位置やカーソル位置を
読み取ったりはせず、Organizerから渡された移動先と設定値に従って、指定された間隔で
固定されたキー入力を送信する方式です。FH6ウィンドウの検出・前面化と入力前の前面状態確認は
行います。そのため、PCやFH6の処理負荷などでキー入力が取りこぼされると、指定位置から
カーソルがずれる場合があります。必要に応じてキー間隔や各待ち時間を長めに調整してください。

PC版 Forza Horizon 6 のLivery整理ツール。
外部Pythonパッケージは不要です。

通常生成では、解析結果を変えない範囲でI/Oと待ち時間を抑えます。
適用Livery参照探索はセーブデータ復号・構造解析の進展まで一時停止し、
FH6車両情報はGameSave外のVehicle DBキャッシュを利用し、Car IDが公式リストにある場合は公式のメーカー・車名・年式を表示します。
Livery構成ファイルは各フォルダーにつき1回だけ読み込み、4 workerで解析します。
HTMLはExcelより先に保存し、一覧を早く利用できるようにします。
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import io
import json
import math
import os
import platform
import re
import shutil
import struct
import sys
import threading
import traceback
import unicodedata
import webbrowser
import zlib
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from typing import Callable, Iterable, Optional

try:
    from .i18n import (
        DEFAULT_LANGUAGE,
        get_language,
        available_languages,
        language_display_name,
        normalize_language,
        pseudo_localize,
        set_language,
        tr,
        build_report_i18n_script,
        locale_for_language,
    )
except ImportError:
    from i18n import (
        DEFAULT_LANGUAGE, available_languages, get_language, language_display_name,
        normalize_language, pseudo_localize, set_language, tr, build_report_i18n_script, locale_for_language,
    )


try:
    from .vehicle_metadata_update import (
        STATUS_CHECK_FAILED,
        STATUS_INCOMPATIBLE,
        STATUS_UPDATE_AVAILABLE,
        DEFAULT_MANIFEST_URL,
        check_vehicle_metadata_update,
        check_vehicle_metadata_update_with_manifest,
        default_vehicle_metadata_cache_path,
        download_and_cache_vehicle_metadata,
        format_update_check_result,
        gui_update_presentation,
        select_runtime_vehicle_metadata_path,
        validate_vehicle_metadata_curation,
        update_cli_text,
        update_gui_text,
    )
except ImportError:
    from vehicle_metadata_update import (
        STATUS_CHECK_FAILED,
        STATUS_INCOMPATIBLE,
        STATUS_UPDATE_AVAILABLE,
        DEFAULT_MANIFEST_URL,
        check_vehicle_metadata_update,
        check_vehicle_metadata_update_with_manifest,
        default_vehicle_metadata_cache_path,
        download_and_cache_vehicle_metadata,
        format_update_check_result,
        gui_update_presentation,
        select_runtime_vehicle_metadata_path,
        validate_vehicle_metadata_curation,
        update_cli_text,
        update_gui_text,
    )


try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
except Exception:
    tk = None
    filedialog = messagebox = ttk = tkfont = None


APP_NAME = "Livery Organizer for FH6"
VERSION = "0.4.60-r04"

DEFAULT_REPORT_DIR_NAME = "Livery-Organizer-for-FH6"
LEGACY_REPORT_DIR_RE = re.compile(r"FH6-Livery-Report(?:-v\d+)?", re.IGNORECASE)

NAVIGATOR_SHARED_SETTINGS_DEFAULTS = {
    "interval_ms": 50.0,
    "switch_delay_ms": 500.0,
    "turn_delay_ms": 200.0,
    "wrap_delay_ms": 400.0,
    "reset_origin": False,
    "reset_esc_delay_ms": 500.0,
    "reset_ret_delay_ms": 800.0,
}

def navigator_shared_settings_path() -> Path:
    """Organizer/Bridgeで共通利用する移動設定。GameSave内には保存しません。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Livery-Organizer-for-FH6" / "navigator-bridge-settings.json"
    return Path.home() / ".livery-organizer-for-fh6" / "navigator-bridge-settings.json"

def load_shared_navigator_settings() -> dict:
    settings = dict(NAVIGATOR_SHARED_SETTINGS_DEFAULTS)
    path = navigator_shared_settings_path()
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

def normalize_legacy_output_root(value: str | Path | None) -> str:
    """開発中の旧既定出力フォルダ名だけを新名称へ読み替えます。"""
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text)
    if LEGACY_REPORT_DIR_RE.fullmatch(path.name):
        return str(path.with_name(DEFAULT_REPORT_DIR_NAME))
    return text

LIVERY_SCAN_WORKERS = 4

# アプリケーションアイコン。配布物に外部画像ファイルを追加せず、
# Python版とEXE版のGUIで同じアイコンを使用できるよう256×256 PNGを埋め込みます。
APP_ICON_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAYAAABccqhmAADhVUlEQVR42uz9d7glV3Xmj3/WrqqTw819OwdlFE0GASJHG5OxjcEY"
    "bAYcMDZ4DE4YgzFjG4xnCLYxYIINY4LIGQWCAAlJSCiHVufum9PJVbXX74+qc07VOecKf3/zzCONdffztNR974lVe6/wrne9C7bW"
    "1tpaW2trba2ttbW21tbaWltra22trbW1ttbW2lpba2ttra21tbbW1tpaW2trba2ttbW21tbaWltra22trbW1ttbW2lpba2ttra21"
    "tbbW1tpaW2trba2ttbW21tbaWltra22trbW1ttbW2lpba2ttra21tbbW1tpaW2trba2ttbW21tbaWltra22trbW1ttbW2lpba2tt"
    "ra21tbbW1tpaW2trba2ttbW21tbaWltra22trbW1ttbW2lpba2ttra21tbbW1tpaW2trba2t9bOWPEC+oxn4vpr4vW5tg/8y91n/"
    "/3yObLI/7H/1/SH/hQ+8AKGIKCLRP1UTp17Tt1b+7+y2//yulE3sUfoVJP6v/ide9d7eW/5T76T/BzdBulf5P/non/VY+b9zFuOX"
    "lJ4JSGwEVVTVxPtJ/ysahP9KBiC6USKBiICCqgWYBs4EdgNniDjbxDE71WqmZywUcESxqqh1FEVEFIuqIKAIotEWFRFUiP8tOKpY"
    "BERRBSfeLDZ5gRVxDKpo9HMlenJ8mmMbhSiY+ClhvNGcxD2yRL+3vaBGe3uy+0FNfJasoKoqYsFIdHysJrZ4fKJMvNUxAkL0mPiy"
    "2L5Zir68iiCqijHRBcP2r0rPtCrR9UNFNbZXiESXNboziiNgJbpuiECY2JOi8R3sPjv+b8+wxF9DI5uugsRPid5Co5dAFXXil9Xe"
    "6/evvUZfVK24znENgpNAANwBHIr/vyzGJPeTS/RZdcsA3H8OPiJio7NkM8CjgWdWJnc9tjy5/azS2PbxQmWKTGEML1fEdXNYGwAG"
    "Y0x0jF2Jj5AFke6B7O2W+E2wKKj0jqmNo4ooyDCgFiOmtzu6ByPaPBL9W6JtHHuYaBeaxD7X6F1VBWP6e1aR2BxI/L7SPRf96MZI"
    "dB6wkdmS6HtZtdEpd7qmQtHYUHY/j/aeFxmb6F/Ra/cOePx3a23aW0bv1jtZxH+LD2jve6va3ntGdjf+Btamjm/3ehnTvX6JCKH7"
    "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"
    "dDPwDRnabbfd+vPuptbLrMZt2ojN6Ky7/HpUL2cWmwHtSUGum11c9bq3lT+XXmT3LdnIHHSD0tvjIWxmPUEjjY3n1X0e3RmDOntr"
    "PBY6wb3hVHeeexQjsUXLauNvrsB74mD0WgceY3vvs1i/+ccHYz73h/4UaT7m4uQu3/j1X/a67gDrKX/0X/43+dZv/lJ5evf1SKz5"
    "f6lb/1uoZnhbl10A8M/jIynPV8L7j/4b1PxzyeSoOvz4H7D3v/1l1MSIGLSYc/Dip5hc/yigPL7zPc7v3/HWX5eAwC7xZevRdnkf"
    "b4sNm7jA5i7vcg8u/b1sv1+56u420v6uDNrmBpDvJwuhf0pf+WvdkuXoJt5xud161eNcut+Njc9GebX1Bbk267h0/3pFVrP5Hujl"
    "53UVkawp67qmHjVJq9O9UW3bkIsLDm7d4LN/8E8QpUPmFw95+Tf+S4rKu0+76UN+7E/+jylXU/edL/wiYuJTTfSnWX7+Dvxe9YNO"
    "/z9MAaAuRyps+qdw9h+hlKNnP22z/Vs8+s7viKQjX7euFxx99DPs3fwEaMXp/Xc5ufMWmASxcZsN9JxFefLMxaYs9baZo61Hu2wJ"
    "Bt2UXq4ITGwRPd2yGbZRcrf/sBPwdMvY9JZjvxsQtrpV6wdkR/V7665+/t9XoFWulMfXjUAkUs8XPyFYdRymNjGUre/ttjFeLmcD"
    "HXBSqwqWFzz7yU/z8R//I0RxxvziEd/49f+cVaGYdIC7eMSLP/4Hef5TP84X/8FfKcXYSFn879Hq30E1D3URuwDQXznIAon+CjL6"
    "X+BW5cEnfzpCIn38+ssi2RjU+Uzg+U9w+PxnMDZifvqQR+++xmoxhzhDTNRqyPeygCd8yLLtaN48+eTqoLH1buUD3uoNzv+2220t"
    "J7b93ZM+Wu3IhdPpMkiPkKFb9+gG7+BS4NItjyW9++/Fxc34qtooZG4GDKlHkGuyT80bUt2ecWwLXrrZ0r2qHJSN7KJ/X2KCVsB8"
    "SpJGfPIn/iC3PvIZkIjHD97lW1/4hxSlYLIcd/GYax/5GD/6x/4MX/zFv1Ktl6VFl7/HrcOfwznh/v05HwJB0A9jADBwfcDB2HL6"
    "/m9A9lPourr+2T9qy/WKx29+C7Kxf+tWM0bXb3DjYz9OMtijKhac3X+Hk3u3KVeFt+yJonDhaJ93v3WjbTnF5Kqa4Krse6MVublJ"
    "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"
    "+Tzox8EOROzk8snZ9If6bkCXxDs+IBZc2uTuCW/zVRe2dDLIK8botjF0tsqjXcXv/X7I/htYRJOrs70LsXUU9xKxYAMb6T6f2pln"
    "8+2QLfCL42qW4VUjnbI9M6+1DVXPVYs5Im+j1ZuIfhORr1HxJsSn4CLSKmcF/hqLF7C/hHfWPywp/++3ANDBBm6msEihyMFl4Sor"
    "IJ77nVxkUO2D5iDPelAR4/0ZLb7347S15am2PI7V1siv9RLuHIFX7aLwt9XGsWhl43E6V23tq3XJs2yLIfrmNrC0qjtBJ9A5Os9B"
    "O89py7Eb/t7/nbaPY0PmVNskV09KJepWRufnFhoHkSfNKl+KgHJF66R7rJuN/2v//ag6j9e8bvVfo9h0gYnvIYsFUXSGMRVT8Fml"
    "S0N0WjGKFkzTFeQl3G68in+YNw+/T4JAsLi8GcMyhiqCKg1igFEQ/q+9dtcdOLljCyR6OW9V6f+uaRe4FpPYKilzRZ4rV423ycbF"
    "7j4gT77is9T6GN3k3Navw20POB0W0PZGn7ni7zqvS+UJ6cGWjX/pbzrPV9z2FoDaK65ffcLxv/G5NtJDnc9DbfhXW6XSXiumAFNC"
    "XMB4De+UP+wb//dbANgACREggmcs3DX+61HssQI1Gxtf+heh6JZN2dk4lzbSVafTFWydrRubLQHnCbVDr2e5KdBntgebzQv++51z"
    "bgKlbAleV72ubm/VXfE+XAUcdO5va1CRLYHziuC9FYzQ7QEA9c9VnD8ojANbQVTBwyps+IrLWmO7APBDEAxsmyXcNHAfOLSXb34C"
    "HHQuqBPgcOPnAI/DBVP/7hA4CRfFUbgou98fKxwJHG+894fhcY7DfR9u2eD1BW7CRqrvY/Nxris8BA7N5b9/UtZh3OXN9KQNJhqe"
    "g8J1oNp4vPr/zvRPedHL3x+H13HV6zoM/z/qPJ/jzm26z+9xyMLq33Wfd31fm++FqFdsfQjcDF/frTf45v/5/bTxn5YA8KTXKx+Q"
    "Trsr0u8nUfr+uzyvD2pF6H/Lz1S/D2j8v839XCVlpP+Mz+P7eV++n9erH/DzD3q9+v+D57tbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vb"
    "u7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vb"
    "u7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vb"
    "u7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7Vbu7VbP6Tr/wuC573Gw9Rz2AAAAABJRU5ErkJggg=="
)


def apply_app_icon(root) -> None:
    """Tkのメインウィンドウと今後作成される子ウィンドウへアプリアイコンを設定します。"""
    if tk is None:
        return
    try:
        icon = tk.PhotoImage(data=APP_ICON_PNG_BASE64)
        root.iconphoto(True, icon)
        # PhotoImageがGCされないようルートウィンドウに保持します。
        root._fh6_app_icon = icon
    except Exception:
        # アイコン設定に失敗しても本体機能は継続します。
        pass

# デスクトップGUIの可読性を優先した既定フォント設定。Windows 11ではSegoe UI Variableを優先します。
# 利用できない場合はSegoe UI、さらにTkの既定フォントへフォールバックします。
# Tkの名前付きフォントを使うことでWindowsのDPIスケーリングに追従しつつ、
# Python側GUIを通常の表示倍率でも読みやすくします。
GUI_FONT_CANDIDATES = ("Segoe UI Variable", "Segoe UI", "Yu Gothic UI")
GUI_FONT_FAMILY = GUI_FONT_CANDIDATES[0]
GUI_FONT_SIZE = 11
GUI_SMALL_FONT_SIZE = 10
GUI_MONO_FONT_CANDIDATES = ("Cascadia Mono", "Consolas")
GUI_MONO_FONT_FAMILY = GUI_MONO_FONT_CANDIDATES[-1]
GUI_MONO_FONT_SIZE = 11


def _preferred_tk_font_family(root, candidates: tuple[str, ...], fallback: str) -> str:
    if tkfont is None:
        return fallback
    try:
        available = {str(name).casefold(): str(name) for name in tkfont.families(root)}
        for candidate in candidates:
            match = available.get(candidate.casefold())
            if match:
                return match
    except Exception:
        pass
    return fallback


def configure_gui_fonts(root) -> None:
    """HTMLへ影響を与えず、Windows 11らしい読みやすいGUIフォントを設定します。"""
    global GUI_FONT_FAMILY, GUI_MONO_FONT_FAMILY
    if tkfont is None:
        return

    try:
        default_family = str(tkfont.nametofont("TkDefaultFont", root=root).actual("family"))
    except Exception:
        default_family = GUI_FONT_CANDIDATES[-1]
    try:
        fixed_family = str(tkfont.nametofont("TkFixedFont", root=root).actual("family"))
    except Exception:
        fixed_family = GUI_MONO_FONT_CANDIDATES[-1]

    GUI_FONT_FAMILY = _preferred_tk_font_family(root, GUI_FONT_CANDIDATES, default_family)
    GUI_MONO_FONT_FAMILY = _preferred_tk_font_family(root, GUI_MONO_FONT_CANDIDATES, fixed_family)

    font_specs = {
        "TkDefaultFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkTextFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkMenuFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkHeadingFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold"),
        "TkCaptionFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold"),
        "TkSmallCaptionFont": (GUI_FONT_FAMILY, GUI_SMALL_FONT_SIZE, "normal"),
        "TkIconFont": (GUI_FONT_FAMILY, GUI_FONT_SIZE, "normal"),
        "TkTooltipFont": (GUI_FONT_FAMILY, GUI_SMALL_FONT_SIZE, "normal"),
        "TkFixedFont": (GUI_MONO_FONT_FAMILY, GUI_MONO_FONT_SIZE, "normal"),
    }
    for name, (family, size, weight) in font_specs.items():
        try:
            font = tkfont.nametofont(name, root=root)
            font.configure(family=family, size=size, weight=weight)
        except Exception:
            pass

    try:
        style = ttk.Style(root)
        style.configure(".", font="TkDefaultFont")
        style.configure("TEntry", font="TkTextFont")
        style.configure("TButton", font="TkDefaultFont")
        style.configure("TCheckbutton", font="TkDefaultFont")
        style.configure("TLabelframe.Label", font="TkDefaultFont")
    except Exception:
        pass


def position_child_window(win, parent, width: int, height: int) -> None:
    """子ウィンドウを画面原点ではなく、親ウィンドウ中央付近へ配置します。"""
    try:
        parent.update_idletasks()
        win.update_idletasks()
        parent_x = int(parent.winfo_rootx())
        parent_y = int(parent.winfo_rooty())
        parent_w = max(1, int(parent.winfo_width()))
        parent_h = max(1, int(parent.winfo_height()))
        screen_w = max(width + 48, int(win.winfo_screenwidth()))
        screen_h = max(height + 48, int(win.winfo_screenheight()))

        x = parent_x + (parent_w - width) // 2
        y = parent_y + (parent_h - height) // 2
        x = max(24, min(x, screen_w - width - 24))
        y = max(24, min(y, screen_h - height - 24))
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        win.geometry(f"{width}x{height}+80+60")

LIVERY_DIR_RE = re.compile(r"^Livery_(\d{4})_(\d{14})$", re.IGNORECASE)
CONTAINERS_ROOT_NAME = "ContainersRoot"


@dataclass
class LiveryRecord:
    livery_id: str
    car_id: int
    car_id_folder: int
    car_id_c_livery: Optional[int]
    car_id_verified: bool

    timestamp_raw: str
    timestamp_local_guess: str
    fh6_date_raw: str
    fh6_date_display: str

    title: str
    description: str
    creator: str
    header_strings: list[str]

    vehicle_display_name: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: Optional[int]
    vehicle_asset: str
    vehicle_source: str

    source_dir: str
    relative_source_dir: str
    snapshot_name: str
    preferred_copy: bool

    header_path: str
    c_livery_path: str
    image_path: str
    report_image: str

    header_size: int
    c_livery_size: int
    image_size: int

    header_sha256_16: str
    c_livery_sha256_16: str
    image_sha256_16: str
    fingerprint: str

    c_livery_compressed_size: Optional[int]
    c_livery_uncompressed_size: Optional[int]
    c_livery_zlib_valid: bool
    vinyl_count: Optional[int]

    duplicate_copies: int
    duplicate_sources: list[str]

    livery_reference_id: str
    applied_state: str
    applied_reference_paths: list[str]

    parse_warnings: list[str]

    # HTML/ブラウザ上で1件の物理Liveryスロットを一意に扱うための安定キー。
    # 通常は内容fingerprintをそのまま使い、同一内容の再ダウンロードだけ
    # Livery ID由来の接尾辞を付けて別カードとして保持します。
    ui_key: str = ""


@dataclass
class VehicleInfo:
    car_id: int
    display_name: str
    year: Optional[int]
    make: str
    model: str
    asset: str
    source_zip: str
    internal_path: str
    source: str = "FH6 installed game asset ZIP"
    name_source: str = "FH6 asset-derived metadata"
    asset_display_name: str = ""
    asset_year: Optional[int] = None
    asset_make: str = ""
    asset_model: str = ""


CARCLIP_RE = re.compile(r"(?:^|/)carclips_(\d+)\.clipd$", re.IGNORECASE)

MANUFACTURER_CODES = {
    "TOY":"Toyota","FER":"Ferrari","MER":"Mercedes-Benz","POR":"Porsche",
    "PLY":"Plymouth","CHE":"Chevrolet","TVR":"TVR","HON":"Honda",
    "SHE":"Shelby","VW":"Volkswagen","LAM":"Lamborghini","LAN":"Lancia",
    "MIT":"Mitsubishi","JAG":"Jaguar","MCL":"McLaren","NIS":"Nissan",
    "FOR":"Ford","SUB":"Subaru","ACU":"Acura","BMW":"BMW","MAS":"Maserati",
    "BUI":"Buick","AUD":"Audi","MAZ":"Mazda","DOD":"Dodge","PEU":"Peugeot",
    "REN":"Renault","KOE":"Koenigsegg","ALF":"Alfa Romeo","PON":"Pontiac",
    "AST":"Aston Martin","FIA":"Fiat","PAG":"Pagani","NUL":"Nissan",
    "NOB":"Noble","LEX":"Lexus","DEL":"DeLorean","CHR":"Chrysler","GMC":"GMC",
    "VOL":"Volvo","LOT":"Lotus","AH":"Austin-Healey","JEE":"Jeep",
    "HEN":"Hennessey","HOL":"Holden","VIP":"Viper","LIN":"Lincoln",
    "ARI":"Ariel","MIN":"MINI","BAC":"BAC","CAD":"Cadillac","MG":"MG",
    "DAT":"Datsun","MEY":"Meyers","OPE":"Opel","RAD":"Radical","LR":"Land Rover",
    "PEN":"Penske","AC":"Ariel","REL":"Reliant","ULT":"Ultima",
    "343":"343 Industries","BEN":"Bentley","RJ":"RJ Anderson",
    "PG":"Playground Games","CAN":"Can-Am","HYU":"Hyundai","FUN":"Funco",
    "PEE":"Peel","KTM":"KTM","APO":"Apollo","ZEN":"Zenvo","SAL":"Saleen",
    "SIE":"Sierra Cars","WUL":"Wuling","GMA":"Gordon Murray Automotive",
    "JIM":"Jimco","RIM":"Rimac","RIV":"Rivian","POL":"Polaris","LUC":"Lucid",
    "AZM":"ATS","RAM":"Ram",
}

MODEL_REPLACEMENTS = [
    (r"(?i)\bgt\s*2\b", "GT2"),
    (r"(?i)\bgt\s*3\b", "GT3"),
    (r"(?i)\bgt\s*4\b", "GT4"),
    (r"(?i)\bgt\s*-?\s*r\b", "GT-R"),
    (r"(?i)\bsti\b", "STi"),
    (r"(?i)\bwrx\b", "WRX"),
    (r"(?i)\bz\s*06\b", "Z06"),
    (r"(?i)\bzr\s*1\b", "ZR1"),
    (r"(?i)\brx\s*7\b", "RX-7"),
    (r"(?i)\brx\s*8\b", "RX-8"),
    (r"(?i)\bs\s*2000\b", "S2000"),
    (r"(?i)\bmr\s*2\b", "MR2"),
]


def default_game_roots() -> list[Path]:
    """Xbox App版FH6のインストール先を可能な範囲で自動検出します。"""
    roots: list[Path] = []
    drives = [os.environ.get("SystemDrive", "C:")]
    if os.name == "nt":
        drives += [f"{c}:" for c in "DEFGHIJKLMNOPQRSTUVWXYZ"]

    seen = set()
    for drive in drives:
        xbox = Path(drive) / "XboxGames"
        if not xbox.is_dir():
            continue
        try:
            children = list(xbox.iterdir())
        except OSError:
            continue

        for child in children:
            if not child.is_dir():
                continue
            low = child.name.lower()
            looks_like_fh6 = (
                ("forza" in low and ("horizon" in low or "forte" in low))
                or "horizon 6" in low
                or "horizon6" in low
            )
            if not looks_like_fh6:
                continue

            try:
                key = str(child.resolve()).lower()
            except OSError:
                key = str(child).lower()
            if key not in seen:
                seen.add(key)
                roots.append(child)

    return roots


def _split_camel_and_digits(s: str) -> str:
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    for pattern, replacement in MODEL_REPLACEMENTS:
        s = re.sub(pattern, replacement, s)

    return s


def pretty_vehicle_from_asset(asset: str) -> tuple[str, Optional[int], str, str]:
    """
    por_911gt2_95のような内部アセット名を、読める代替車名へ変換します。
    IDを正とし、表示名は推定値として扱います。
    """
    parts = asset.split("_")
    code = parts[0].upper() if parts else ""
    make = MANUFACTURER_CODES.get(code, parts[0] if parts else "")
    year = None
    model_parts = parts[1:]

    if len(parts) >= 3 and re.fullmatch(r"\d{2}", parts[-1]):
        yy = int(parts[-1])
        year = 2000 + yy if yy <= 30 else 1900 + yy
        model_parts = parts[1:-1]
    elif len(parts) >= 3 and re.fullmatch(r"\d{4}", parts[-1]):
        year = int(parts[-1])
        model_parts = parts[1:-1]

    model = _split_camel_and_digits("_".join(model_parts))
    display = " ".join(
        x for x in (str(year) if year else "", make, model) if x
    ).strip()
    return display or asset, year, make, model


VEHICLE_METADATA_FILENAME = "fh6-vehicle-metadata.json"
VEHICLE_METADATA_SCHEMA = 1
VEHICLE_METADATA_DATASET = "fh6-official-vehicle-metadata"
VEHICLE_METADATA_SOURCE_NAME = "Forza official car list"


def vehicle_metadata_resource_path() -> Path:
    '''Bundled vehicle-display metadata. No network access is performed.'''
    return Path(__file__).resolve().with_name(VEHICLE_METADATA_FILENAME)



def vehicle_metadata_runtime_path() -> Path:
    """
    Prefer a fully validated, strictly newer local cache.

    This performs no network access. Missing, stale, damaged, or incompatible
    cache files fall back to the bundled metadata resource.
    """
    bundled = vehicle_metadata_resource_path()
    try:
        return select_runtime_vehicle_metadata_path(
            bundled_path=bundled,
        )
    except Exception:
        return bundled


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_official_vehicle_metadata(
    path: Optional[Path] = None,
) -> tuple[str, str, dict[int, tuple[int, str, str, str]]]:
    '''
    Load bundled FH6 vehicle-display metadata from local JSON.

    r01 intentionally performs no network update/check. Missing or malformed bundled
    metadata is an error instead of silently changing vehicle display names.
    '''
    metadata_path = Path(path) if path is not None else vehicle_metadata_runtime_path()

    try:
        raw_text = metadata_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"vehicle metadata file could not be read: {metadata_path}: {exc}"
        ) from exc

    try:
        payload = json.loads(
            raw_text,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(
            f"vehicle metadata JSON is invalid: {metadata_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError("vehicle metadata root must be a JSON object")
    if payload.get("schema_version") != VEHICLE_METADATA_SCHEMA:
        raise RuntimeError(
            f"unsupported vehicle metadata schema: {payload.get('schema_version')!r}"
        )
    if payload.get("dataset") != VEHICLE_METADATA_DATASET:
        raise RuntimeError(
            f"unexpected vehicle metadata dataset: {payload.get('dataset')!r}"
        )

    source = payload.get("source")
    records = payload.get("records")
    try:
        validate_vehicle_metadata_curation(
            payload.get("curation"),
            label="vehicle metadata",
        )
    except Exception as exc:
        raise RuntimeError(
            f"vehicle metadata curation is invalid: {metadata_path}: {exc}"
        ) from exc
    if not isinstance(source, dict):
        raise RuntimeError("vehicle metadata source must be a JSON object")
    if not isinstance(records, dict):
        raise RuntimeError("vehicle metadata records must be a JSON object")
    if source.get("name") != VEHICLE_METADATA_SOURCE_NAME:
        raise RuntimeError(
            f"unexpected vehicle metadata source: {source.get('name')!r}"
        )

    source_url = source.get("url")
    source_updated = source.get("updated")
    if not isinstance(source_url, str) or not source_url:
        raise RuntimeError("vehicle metadata source.url must be a non-empty string")
    if not isinstance(source_updated, str) or not source_updated:
        raise RuntimeError("vehicle metadata source.updated must be a non-empty string")

    metadata: dict[int, tuple[int, str, str, str]] = {}
    expected_fields = {"year", "make", "model", "display_name"}

    for car_id_text, raw in records.items():
        if not isinstance(car_id_text, str) or not car_id_text.isdecimal():
            raise RuntimeError(f"invalid vehicle metadata Car ID: {car_id_text!r}")
        car_id = int(car_id_text)
        if car_id <= 0 or str(car_id) != car_id_text:
            raise RuntimeError(
                f"non-canonical vehicle metadata Car ID: {car_id_text!r}"
            )
        if car_id in metadata:
            raise RuntimeError(f"duplicate vehicle metadata Car ID: {car_id}")
        if not isinstance(raw, dict):
            raise RuntimeError(f"Car ID {car_id}: metadata must be a JSON object")
        if set(raw) != expected_fields:
            raise RuntimeError(
                f"Car ID {car_id}: unexpected metadata fields: "
                f"{sorted(set(raw) ^ expected_fields)}"
            )

        year = raw.get("year")
        make = raw.get("make")
        model = raw.get("model")
        display_name = raw.get("display_name")

        # r01 validates representation, not real-world plausibility.
        if isinstance(year, bool) or not isinstance(year, int):
            raise RuntimeError(f"Car ID {car_id}: year is not an integer: {year!r}")
        for field_name, value in (
            ("make", make),
            ("model", model),
            ("display_name", display_name),
        ):
            if not isinstance(value, str) or not value:
                raise RuntimeError(
                    f"Car ID {car_id}: {field_name} must be a non-empty string"
                )

        metadata[car_id] = (year, make, model, display_name)

    return source_url, source_updated, metadata


(
    OFFICIAL_VEHICLE_LIST_URL,
    OFFICIAL_VEHICLE_LIST_UPDATED,
    OFFICIAL_VEHICLE_METADATA,
) = load_official_vehicle_metadata()

def apply_official_vehicle_metadata(vehicle_db: dict[int, VehicleInfo]) -> int:
    """
    Car IDをキーにForza公式車種リストのメーカー・車名・年式を優先します。

    FH6アセット名から推定した値はasset_*へ保持し、診断・照合用途で失わないようにします。
    公式リスト対象外（Traffic/内部車両など）は従来のアセット推定値を表示に使用します。
    実行時のネットワークアクセスは行いません。
    """
    applied = 0
    for car_id, info in vehicle_db.items():
        # キャッシュや旧形式データから復元した場合にも、内部アセット由来の値を確保します。
        if not info.asset_display_name:
            raw_display, raw_year, raw_make, raw_model = pretty_vehicle_from_asset(info.asset)
            info.asset_display_name = raw_display
            info.asset_year = raw_year
            info.asset_make = raw_make
            info.asset_model = raw_model

        official = OFFICIAL_VEHICLE_METADATA.get(int(car_id))
        if official is None:
            info.display_name = info.asset_display_name or info.display_name
            info.year = info.asset_year
            info.make = info.asset_make
            info.model = info.asset_model
            info.name_source = "FH6 asset-derived metadata"
            continue

        year, make, model, display_name = official
        info.display_name = display_name
        info.year = year
        info.make = make
        info.model = model
        info.name_source = f"Forza official car list ({OFFICIAL_VEHICLE_LIST_UPDATED})"
        applied += 1

    return applied


def _vehicle_asset_problem_detail(zip_path: Path, game_root: Path, exc: BaseException) -> dict[str, object]:
    """読み取り不可ZIPの原因調査に必要な最小情報を、読み取り専用で収集します。"""
    try:
        relative_path = str(zip_path.resolve().relative_to(game_root.resolve()))
    except Exception:
        relative_path = str(zip_path)

    size = None
    prefix = b""
    signature_error = ""
    try:
        size = zip_path.stat().st_size
        with zip_path.open("rb") as fh:
            prefix = fh.read(8)
    except OSError as sig_exc:
        signature_error = f"{type(sig_exc).__name__}: {sig_exc}"

    standard_zip_signature = prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    return {
        "path": relative_path,
        "exception_type": type(exc).__name__,
        "exception": str(exc) or repr(exc),
        "size": size,
        "prefix_hex": prefix.hex(" ").upper(),
        "standard_zip_signature": standard_zip_signature,
        "signature_error": signature_error,
    }


VEHICLE_DATABASE_CACHE_SCHEMA = 3
VEHICLE_DATABASE_CACHE_FILENAME = "vehicle-database-v3.json"


def _vehicle_database_cache_path() -> Path:
    """GameSave外に保持するVehicle DB全体キャッシュの現在の保存先を返します。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Livery-Organizer-for-FH6" / "cache" / VEHICLE_DATABASE_CACHE_FILENAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "Livery-Organizer-for-FH6" / VEHICLE_DATABASE_CACHE_FILENAME
    return Path.home() / ".cache" / "Livery-Organizer-for-FH6" / VEHICLE_DATABASE_CACHE_FILENAME


def _legacy_vehicle_database_cache_paths() -> list[Path]:
    """旧FH6 Livery Organizer名で保存されたキャッシュ候補を返します。"""
    paths: list[Path] = []
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            paths.append(Path(base) / "FH6-Livery-Organizer" / "cache" / VEHICLE_DATABASE_CACHE_FILENAME)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        paths.append(Path(xdg) / "FH6-Livery-Organizer" / VEHICLE_DATABASE_CACHE_FILENAME)
    paths.append(Path.home() / ".cache" / "FH6-Livery-Organizer" / VEHICLE_DATABASE_CACHE_FILENAME)
    return paths


def _migrate_legacy_file_if_needed(current: Path, legacy_paths: Iterable[Path]) -> Path:
    """現在パスが未作成なら旧名称のファイルをコピーして移行します。旧ファイルは残します。"""
    if current.exists():
        return current
    for legacy in legacy_paths:
        try:
            if not legacy.exists() or not legacy.is_file():
                continue
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, current)
            return current
        except OSError:
            continue
    return current


def _normalize_cache_root(path: Path | str) -> str:
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(str(path))


def _load_vehicle_database_cache(
    game_root: Path,
    *,
    required_car_ids: Optional[set[int]] = None,
) -> tuple[Optional[dict[int, VehicleInfo]], dict[str, object], str]:
    """Vehicle DB全体キャッシュを読み込みます。FH6本体のファイル走査は行いません。"""
    path = _migrate_legacy_file_if_needed(
        _vehicle_database_cache_path(),
        _legacy_vehicle_database_cache_paths(),
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {}, "cache file not found"
    except (OSError, ValueError, TypeError) as exc:
        return None, {}, f"cache read error: {type(exc).__name__}"

    if not isinstance(payload, dict):
        return None, {}, "invalid cache payload"
    if payload.get("schema") != VEHICLE_DATABASE_CACHE_SCHEMA:
        return None, {}, "cache schema mismatch"
    if _normalize_cache_root(payload.get("game_root", "")) != _normalize_cache_root(game_root):
        return None, {}, "game root changed"

    raw_records = payload.get("records")
    if not isinstance(raw_records, dict):
        return None, {}, "cache records missing"

    result: dict[int, VehicleInfo] = {}
    try:
        for key, raw in raw_records.items():
            if not isinstance(raw, dict):
                raise TypeError("record is not an object")
            car_id = int(raw.get("car_id", key))
            result[car_id] = VehicleInfo(
                car_id=car_id,
                display_name=str(raw.get("display_name", "")),
                year=(int(raw["year"]) if raw.get("year") is not None else None),
                make=str(raw.get("make", "")),
                model=str(raw.get("model", "")),
                asset=str(raw.get("asset", "")),
                source_zip=str(raw.get("source_zip", "")),
                internal_path=str(raw.get("internal_path", "")),
                source=str(raw.get("source", "FH6 installed game asset ZIP")),
                name_source=str(raw.get("name_source", "FH6 asset-derived metadata")),
                asset_display_name=str(raw.get("asset_display_name", "")),
                asset_year=(int(raw["asset_year"]) if raw.get("asset_year") is not None else None),
                asset_make=str(raw.get("asset_make", "")),
                asset_model=str(raw.get("asset_model", "")),
            )
    except (TypeError, ValueError, KeyError) as exc:
        return None, {}, f"cache record decode error: {type(exc).__name__}"

    required = {int(x) for x in (required_car_ids or set())}
    missing = sorted(required.difference(result))
    if missing:
        preview = ", ".join(str(x) for x in missing[:8])
        suffix = " ..." if len(missing) > 8 else ""
        return None, {}, f"required Car ID missing: {preview}{suffix}"

    raw_stats = payload.get("scan_stats")
    stats = dict(raw_stats) if isinstance(raw_stats, dict) else {}
    return result, stats, "cache valid"


def _save_vehicle_database_cache(
    game_root: Path,
    vehicle_db: dict[int, VehicleInfo],
    scan_stats: dict[str, object],
) -> bool:
    path = _vehicle_database_cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema": VEHICLE_DATABASE_CACHE_SCHEMA,
        "app": APP_NAME,
        "version": VERSION,
        "game_root": str(game_root.resolve()),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scan_stats": scan_stats,
        "records": {
            str(car_id): asdict(item)
            for car_id, item in sorted(vehicle_db.items())
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _scan_vehicle_assets_uncached(
    game_root: Path,
    progress: Optional[Callable[[str], None]] = None,
    *,
    unreadable_problems: Optional[list[dict[str, object]]] = None,
    empty_archives: Optional[list[dict[str, object]]] = None,
) -> tuple[dict[int, VehicleInfo], dict[str, object]]:
    """従来方式の全ZIP走査を実行し、Vehicle DBと走査統計を返します。"""
    game_root = game_root.resolve()
    result: dict[int, VehicleInfo] = {}
    zip_count = 0
    bad_zip_count = 0
    empty_zip_count = 0
    zip_files_opened = 0
    bad_zip_reasons: dict[str, int] = {}

    for dirpath, _, filenames in os.walk(game_root):
        for filename in filenames:
            if not filename.lower().endswith(".zip"):
                continue

            zip_count += 1
            if progress and zip_count % 100 == 0:
                progress(tr("progress.vehicle.scan", zip_count=zip_count, car_ids=len(result)))

            zip_path = Path(dirpath) / filename

            # FH6には未使用言語のstring tableなど、0バイトの .zip が
            # プレースホルダーとして存在することがあります。これらは異常ではなく、
            # ZipFileへ渡す前に正常スキップします。
            try:
                if zip_path.stat().st_size == 0:
                    empty_zip_count += 1
                    if empty_archives is not None:
                        try:
                            relative_path = str(zip_path.resolve().relative_to(game_root))
                        except Exception:
                            relative_path = str(zip_path)
                        empty_archives.append({"path": relative_path, "size": 0})
                    continue
            except OSError:
                # statに失敗した場合は下のZipFile処理へ進み、
                # 読み取り不可ZIPとして原因を収集します。
                pass

            try:
                zip_files_opened += 1
                with zipfile.ZipFile(zip_path, "r") as zf:
                    found = None
                    for member in zf.namelist():
                        match = CARCLIP_RE.search(member.replace("\\", "/"))
                        if match:
                            found = (int(match.group(1)), member)
                            break
                    if found is None:
                        continue
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                bad_zip_count += 1
                reason = type(exc).__name__
                bad_zip_reasons[reason] = bad_zip_reasons.get(reason, 0) + 1
                if unreadable_problems is not None:
                    unreadable_problems.append(
                        _vehicle_asset_problem_detail(zip_path, game_root, exc)
                    )
                continue

            car_id, internal_path = found
            asset = zip_path.stem
            display_name, year, make, model = pretty_vehicle_from_asset(asset)
            result.setdefault(
                car_id,
                VehicleInfo(
                    car_id=car_id,
                    display_name=display_name,
                    year=year,
                    make=make,
                    model=model,
                    asset=asset,
                    source_zip=normpath(zip_path),
                    internal_path=internal_path,
                    name_source="FH6 asset-derived metadata",
                    asset_display_name=display_name,
                    asset_year=year,
                    asset_make=make,
                    asset_model=model,
                ),
            )

    scan_stats: dict[str, object] = {
        "zip_files_seen": zip_count,
        "empty_zip_files": empty_zip_count,
        "unreadable_zip_files": bad_zip_count,
        "zip_files_opened": zip_files_opened,
        "car_ids_found": len(result),
    }

    if progress:
        completion = tr("progress.vehicle.complete", zip_count=zip_count, car_ids=len(result))
        # 通常利用では空プレースホルダーを異常として表示しません。
        # 0バイト以外で実際に開けなかったZIPがある場合だけ注意情報を追加します。
        if bad_zip_count:
            reason_text = ", ".join(
                f"{name} {count:,}"
                for name, count in sorted(bad_zip_reasons.items())
            )
            unreadable_text = tr(
                "progress.vehicle.unreadable",
                count=bad_zip_count,
                reasons=f" ({reason_text})" if reason_text else "",
            )
            completion += f" / {unreadable_text}"
        progress(completion)

    return result, scan_stats


def scan_vehicle_assets(
    game_root: Path,
    progress: Optional[Callable[[str], None]] = None,
    *,
    unreadable_problems: Optional[list[dict[str, object]]] = None,
    empty_archives: Optional[list[dict[str, object]]] = None,
    required_car_ids: Optional[set[int]] = None,
    force_rebuild: bool = False,
) -> dict[int, VehicleInfo]:
    """
    Vehicle DB全体キャッシュが有効なら、FH6本体のos.walkやZIP列挙を一切行わず
    キャッシュ済みVehicleInfoを返します。

    キャッシュ無効条件:
    - キャッシュなし / schema不一致
    - FH6本体パス変更
    - 現在のLiveryで必要なCar IDがキャッシュに存在しない
    - force_rebuild=True（診断時の手動再構築相当）
    """
    game_root = game_root.resolve()
    cache_path = _vehicle_database_cache_path()

    if force_rebuild:
        cached_db = None
        cached_stats: dict[str, object] = {}
        cache_reason = "force rebuild"
    else:
        cached_db, cached_stats, cache_reason = _load_vehicle_database_cache(
            game_root,
            required_car_ids=required_car_ids,
        )

    if cached_db is not None:
        official_count = apply_official_vehicle_metadata(cached_db)
        if progress:
            progress(tr(
                "progress.cache.used",
                car_ids=len(cached_db),
                official=official_count,
                path=display_path_text(cache_path),
            ))
        return cached_db
    if progress:
        progress(tr("progress.cache.rebuild", reason=cache_reason))

    result, scan_stats = _scan_vehicle_assets_uncached(
        game_root,
        progress=progress,
        unreadable_problems=unreadable_problems,
        empty_archives=empty_archives,
    )
    official_count = apply_official_vehicle_metadata(result)
    scan_stats["official_metadata_applied"] = official_count
    scan_stats["official_metadata_source"] = OFFICIAL_VEHICLE_LIST_URL
    scan_stats["official_metadata_updated"] = OFFICIAL_VEHICLE_LIST_UPDATED
    cache_saved = _save_vehicle_database_cache(game_root, result, scan_stats)

    if progress:
        if cache_saved:
            progress(tr("progress.cache.saved", path=display_path_text(cache_path)))
        else:
            progress(tr("progress.cache.save_failed"))
    return result


def inspect_vehicle_asset_archives(
    game_root: Path,
    progress: Optional[Callable[[str], None]] = None,
) -> tuple[dict[int, VehicleInfo], list[dict[str, object]], list[dict[str, object]]]:
    """FH6本体のZIPを読み取り専用で検査し、空ZIPと読み取り不可ZIPを返します。"""
    problems: list[dict[str, object]] = []
    empty_archives: list[dict[str, object]] = []
    vehicle_db = scan_vehicle_assets(
        game_root,
        progress=progress,
        unreadable_problems=problems,
        empty_archives=empty_archives,
        force_rebuild=True,
    )
    problems.sort(
        key=lambda item: (
            str(item.get("exception_type", "")),
            str(item.get("path", "")).casefold(),
        )
    )
    empty_archives.sort(key=lambda item: str(item.get("path", "")).casefold())
    return vehicle_db, empty_archives, problems


def format_vehicle_asset_problems(
    game_root: Path,
    vehicle_db: dict[int, VehicleInfo],
    empty_archives: list[dict[str, object]],
    problems: list[dict[str, object]],
) -> str:
    """車両アセット診断結果を、現在のUI言語で原因切り分け用テキストへ整形します。"""
    lines = [
        tr("asset_diag.title", path=display_path_text(game_root)),
        tr("asset_diag.detected_car_ids", count=len(vehicle_db)),
        tr("asset_diag.empty_archives", count=len(empty_archives)),
        tr("asset_diag.unreadable_archives", count=len(problems)),
    ]

    if empty_archives:
        lines.append(tr("asset_diag.empty_note"))
        lines.append(tr("asset_diag.empty_list"))
        for index, item in enumerate(empty_archives, 1):
            lines.append(
                f"{index:02d}. {display_path_text(item.get('path', ''))} / 0 bytes"
            )

    if not problems:
        if empty_archives:
            lines.append("")
        lines.append(tr("asset_diag.no_unreadable"))
        return "\n".join(lines)

    if empty_archives:
        lines.append("")

    reason_counts: dict[str, int] = {}
    signature_counts = {"standard": 0, "nonstandard": 0, "unknown": 0}
    for item in problems:
        reason = str(item.get("exception_type") or tr("asset_diag.unknown"))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if item.get("signature_error"):
            signature_counts["unknown"] += 1
        elif item.get("standard_zip_signature"):
            signature_counts["standard"] += 1
        else:
            signature_counts["nonstandard"] += 1

    reason_details = ", ".join(
        f"{name} {count:,}" for name, count in sorted(reason_counts.items())
    )
    lines.append(tr("asset_diag.reason_summary", details=reason_details))
    lines.append(
        tr(
            "asset_diag.signature_summary",
            standard=signature_counts["standard"],
            nonstandard=signature_counts["nonstandard"],
            unknown=signature_counts["unknown"],
        )
    )
    lines.append(tr("asset_diag.readonly_note"))
    lines.append("")
    lines.append(tr("asset_diag.unreadable_list"))

    for index, item in enumerate(problems, 1):
        size = item.get("size")
        size_text = f"{int(size):,} bytes" if isinstance(size, int) else tr("asset_diag.unknown")
        prefix = str(item.get("prefix_hex") or tr("asset_diag.prefix_unavailable"))
        signature = (
            tr("asset_diag.signature_standard")
            if item.get("standard_zip_signature")
            else tr("asset_diag.signature_unknown")
            if item.get("signature_error")
            else tr("asset_diag.signature_nonstandard")
        )
        lines.append(
            f"{index:02d}. [{item.get('exception_type', 'Error')}] "
            f"{display_path_text(item.get('path', ''))}"
        )
        lines.append(
            tr(
                "asset_diag.item_size",
                size=size_text,
                prefix=prefix,
                signature=signature,
            )
        )
        lines.append(tr("asset_diag.item_exception", error=item.get("exception", "")))
        if item.get("signature_error"):
            lines.append(
                tr("asset_diag.item_signature_error", error=item.get("signature_error"))
            )

    return "\n".join(lines)


def enrich_records_with_vehicle_info(
    records: list[LiveryRecord],
    vehicle_db: dict[int, VehicleInfo],
) -> None:
    for record in records:
        info = vehicle_db.get(record.car_id)
        if info is None:
            continue

        record.vehicle_display_name = info.display_name
        record.vehicle_make = info.make
        record.vehicle_model = info.model
        record.vehicle_year = info.year
        record.vehicle_asset = info.asset
        record.vehicle_source = info.source


def write_vehicle_database(
    vehicle_db: dict[int, VehicleInfo],
    outdir: Path,
) -> None:
    if not vehicle_db:
        return

    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "fh6-vehicle-database.json"
    csv_path = outdir / "fh6-vehicle-database.csv"

    payload = {
        "app": APP_NAME,
        "version": VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "installed FH6 game asset ZIP scan",
        "official_metadata_source": OFFICIAL_VEHICLE_LIST_URL,
        "official_metadata_updated": OFFICIAL_VEHICLE_LIST_UPDATED,
        "official_metadata_records": sum(
            1 for item in vehicle_db.values()
            if item.name_source.startswith("Forza official car list")
        ),
        "records": {
            str(car_id): asdict(item)
            for car_id, item in sorted(vehicle_db.items())
        },
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def csv_cell(value) -> str:
        text = "" if value is None else str(value)
        text = text.replace("\x00", "")
        return '"' + text.replace('"', '""') + '"'

    fields = [
        "car_id",
        "display_name",
        "year",
        "make",
        "model",
        "name_source",
        "asset_display_name",
        "asset_year",
        "asset_make",
        "asset_model",
        "asset",
        "source_zip",
        "internal_path",
        "source",
    ]
    rows = [fields]
    for _, item in sorted(vehicle_db.items()):
        data = asdict(item)
        rows.append([data.get(field, "") for field in fields])

    csv_path.write_text(
        "\ufeff"
        + "\r\n".join(
            ",".join(csv_cell(value) for value in row)
            for row in rows
        )
        + "\r\n",
        encoding="utf-8",
    )


def default_roots() -> list[Path]:
    roots: list[Path] = []
    system_drive = os.environ.get("SystemDrive", "C:")
    candidates = [
        Path(system_drive) / "XboxGames" / "GameSave" / "pgs",
        Path(system_drive) / "XboxGames" / "GameSave",
    ]
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.extend([
                Path(f"{letter}:\\XboxGames\\GameSave\\pgs"),
                Path(f"{letter}:\\XboxGames\\GameSave"),
            ])

    seen = set()
    for p in candidates:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if p.exists() and p.is_dir() and key not in seen:
            seen.add(key)
            roots.append(p)
    return roots



def settings_path() -> Path:
    """ユーザーごとの現在の設定ファイル保存先です。FH6/GameSave内には保存しません。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Livery-Organizer-for-FH6" / "settings.json"
    return Path.home() / ".livery-organizer-for-fh6" / "settings.json"


def legacy_settings_paths() -> list[Path]:
    """旧FH6 Livery Organizer名で保存された設定候補を返します。"""
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "FH6-Livery-Organizer" / "settings.json")
    paths.append(Path.home() / ".fh6-livery-organizer" / "settings.json")
    return paths


def load_settings() -> dict:
    path = _migrate_legacy_file_if_needed(settings_path(), legacy_settings_paths())
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "app": APP_NAME,
        "version": VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        **settings,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def initialize_ui_language(settings: Optional[dict] = None) -> str:
    """環境変数または設定からUI言語を初期化し、日本語へフォールバックします。

    開発専用の ``qps`` は環境変数からだけ有効化し、settings.jsonへ手動で
    書かれていても通常利用では選択されないようにします。
    """
    saved = settings if isinstance(settings, dict) else load_settings()
    env_language = os.environ.get("FH6_ORGANIZER_LANG")
    if env_language:
        return set_language(env_language)
    requested = normalize_language(saved.get("language") or DEFAULT_LANGUAGE)
    if requested == "qps":
        requested = DEFAULT_LANGUAGE
    return set_language(requested)


def normpath(p: Path) -> str:
    try:
        return str(p.resolve())
    except OSError:
        return str(p.absolute())


def display_path_text(value: object) -> str:
    """現在のUI言語に合わせてWindowsパス区切りを表示用に整形します。"""
    separator = "¥" if get_language() == "ja" else "\\"
    text = str(value).replace("\\", separator)

    # ドライブパス内のスラッシュだけを変換し、JSON / CSVのような
    # ラベル内のスラッシュはそのまま保持します。
    def _drive_path(match: re.Match[str]) -> str:
        return match.group(0).replace("/", separator)

    return re.sub(r"(?i)(?<![A-Za-z0-9])[A-Z]:/[^\r\n]*", _drive_path, text)


def native_path_text(value: object) -> str:
    """表示用の円サイン区切りをWindows本来のバックスラッシュへ戻します。"""
    return str(value).replace("¥", "\\").replace("￥", "\\")


def _resolved_path_for_safety(path: Path) -> Path:
    """パスの存在を必須にせず、可能な範囲まで解決します。"""
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        try:
            return path.expanduser().absolute()
        except (OSError, RuntimeError):
            return path


def protected_gamesave_root(scan_root: Path) -> Path:
    """読み取り専用として保護するGameSaveコンテナを返します。

    選択した走査ルートがC:/.../GameSave/pgsの場合は、pgsだけでなくGameSave全体を保護します。
    GameSaveというパス要素を含まない独自構成では、選択した走査ルート自体を保護します。
    """
    resolved = _resolved_path_for_safety(scan_root)
    for candidate in (resolved, *resolved.parents):
        if candidate.name.casefold() == "gamesave":
            return candidate
    return resolved


def path_is_within(path: Path, parent: Path) -> bool:
    child = _resolved_path_for_safety(path)
    base = _resolved_path_for_safety(parent)
    try:
        return child == base or base in child.parents
    except (OSError, RuntimeError):
        return False


def output_location_error(scan_root: Path, outdir: Path) -> str:
    """レポート出力がGameSaveへ触れる場合の説明付きエラーを返します。"""
    protected = protected_gamesave_root(scan_root)
    if path_is_within(outdir, protected):
        return tr("output.location_forbidden", path=display_path_text(protected))
    return ""


def ensure_safe_output_directory(scan_root: Path, outdir: Path) -> None:
    error = output_location_error(scan_root, outdir)
    if error:
        raise ValueError(error)


def output_bundle_label(
    *,
    embed_images: bool = True,
    export_analysis_data: bool = False,
) -> str:
    """1回の実行で作成されるファイル・フォルダ構成を表示用に説明します。"""
    parts = [tr("output.embedded_html") if embed_images else "HTML", "Excel"]
    if not embed_images:
        parts.insert(1, "thumbnails/")
    if export_analysis_data:
        parts.append("data/")
    return " + ".join(parts)


def output_bundle_entries(
    outdir: Path,
    *,
    embed_images: bool = True,
    export_analysis_data: bool = False,
) -> list[tuple[str, Path]]:
    """想定される出力物を、利用者向けの一定した順序で返します。"""
    entries: list[tuple[str, Path]] = [
        ("HTML", outdir / "livery-organizer-for-fh6.html"),
    ]
    if not embed_images:
        entries.append((tr("output.thumbnails"), outdir / "thumbnails"))
    entries.append(("Excel", outdir / "livery-organizer-for-fh6.xlsx"))
    if export_analysis_data:
        entries.append((tr("output.analysis_data"), outdir / "data"))
    return entries


def generator_preflight(
    scan_root: Optional[Path],
    game_root: Optional[Path],
    outdir: Optional[Path],
    *,
    embed_images: bool = True,
    export_analysis_data: bool = False,
) -> dict:
    """GameSaveや出力先へ書き込まずに、ジェネレーターの実行準備状態を評価します。"""
    items: list[dict[str, str]] = []

    if scan_root is None:
        items.append({"key": "save", "state": "error", "label": tr("path.save_root"), "detail": tr("preflight.save.not_set")})
    elif not scan_root.exists() or not scan_root.is_dir():
        items.append({"key": "save", "state": "error", "label": tr("path.save_root"), "detail": tr("preflight.save.not_found")})
    else:
        items.append({"key": "save", "state": "ok", "label": tr("path.save_root"), "detail": tr("preflight.save.ready")})

    if game_root is None:
        items.append({"key": "game", "state": "warning", "label": tr("path.game_root"), "detail": tr("preflight.game.not_set")})
    elif not game_root.exists() or not game_root.is_dir():
        items.append({"key": "game", "state": "warning", "label": tr("path.game_root"), "detail": tr("preflight.game.not_found")})
    else:
        items.append({"key": "game", "state": "ok", "label": tr("path.game_root"), "detail": tr("preflight.game.ready")})

    if outdir is None:
        items.append({"key": "output", "state": "error", "label": tr("path.output_root"), "detail": tr("preflight.output.not_set")})
    elif scan_root is not None and output_location_error(scan_root, outdir):
        items.append({"key": "output", "state": "error", "label": tr("path.output_root"), "detail": tr("preflight.output.forbidden")})
    else:
        items.append({"key": "output", "state": "ok", "label": tr("path.output_root"), "detail": tr("preflight.output.ready")})

    delivery = output_bundle_label(
        embed_images=embed_images,
        export_analysis_data=export_analysis_data,
    )
    items.append({"key": "delivery", "state": "ok", "label": tr("path.output_bundle"), "detail": delivery})

    has_error = any(item["state"] == "error" for item in items)
    has_warning = any(item["state"] == "warning" for item in items)
    state = "error" if has_error else "warning" if has_warning else "ready"
    summary = tr("preflight.summary.fix") if has_error else tr("preflight.summary.warning") if has_warning else tr("preflight.summary.ready")
    return {"state": state, "summary": summary, "items": items}


def support_environment_info(
    scan_root: Optional[Path],
    game_root: Optional[Path],
    outdir: Optional[Path],
    *,
    embed_images: bool = True,
    export_analysis_data: bool = False,
) -> dict:
    """GameSaveや出力先へ触れず、コピー可能なトラブルシューティング情報を収集します。"""
    preflight = generator_preflight(
        scan_root,
        game_root,
        outdir,
        embed_images=embed_images,
        export_analysis_data=export_analysis_data,
    )
    not_set = tr("support.not_set")
    return {
        "app": APP_NAME,
        "version": VERSION,
        "os": platform.platform(),
        "python": platform.python_version(),
        "python_executable": sys.executable or "",
        "tkinter": tr("support.tk_available") if tk is not None else tr("support.tk_unavailable"),
        "settings_path": str(settings_path()),
        "scan_root": str(scan_root) if scan_root is not None else not_set,
        "game_root": str(game_root) if game_root is not None else not_set,
        "output_root": str(outdir) if outdir is not None else not_set,
        "output_bundle": output_bundle_label(
            embed_images=embed_images,
            export_analysis_data=export_analysis_data,
        ),
        "preflight": preflight,
    }


def format_support_environment_text(info: dict) -> str:
    """環境情報をクリップボードやターミナルでのサポート利用向けに整形します。"""
    preflight = info.get("preflight") or {}
    state_labels = {
        "ready": tr("marker.ready"),
        "ok": tr("marker.ready"),
        "warning": tr("marker.warning"),
        "error": tr("marker.error"),
    }
    lines = [
        f"{info.get('app', APP_NAME)} v{info.get('version', VERSION)}",
        f"OS: {info.get('os', '')}",
        f"Python: {info.get('python', '')}",
        f"{tr('support.field.python_executable')}: {info.get('python_executable', '')}",
        f"{tr('support.field.tkinter')}: {info.get('tkinter', '')}",
        f"{tr('support.field.settings')}: {info.get('settings_path', '')}",
        f"{tr('support.field.save_root')}: {info.get('scan_root', '')}",
        f"{tr('support.field.fh6_root')}: {info.get('game_root', '')}",
        f"{tr('support.field.output_root')}: {info.get('output_root', '')}",
        f"{tr('support.field.output_bundle')}: {info.get('output_bundle', '')}",
        f"{tr('support.field.preflight')}: {state_labels.get(preflight.get('state', ''), preflight.get('state', ''))} / {preflight.get('summary', '')}",
    ]
    for item in preflight.get("items", []):
        lines.append(
            f"- {item.get('label', item.get('key', ''))}: "
            f"{state_labels.get(item.get('state', ''), item.get('state', ''))} / {item.get('detail', '')}"
        )
    lines.extend(["", tr("support.safety"), tr("support.note")])
    return "\n".join(lines)


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for unit in units:
        if f < 1024 or unit == units[-1]:
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return str(n)


class _CachedReadOnlyFile:
    """既存Pathベース解析関数へ、1回だけ読み込んだ内容をPath風に渡す読み取り専用ラッパー。"""

    __slots__ = ("path", "_data", "_exists", "_is_file", "_error", "size")

    def __init__(
        self,
        path: Path,
        data: bytes,
        *,
        exists: bool,
        is_file: bool,
        error: Optional[OSError],
        size: int,
    ) -> None:
        self.path = path
        self._data = data
        self._exists = exists
        self._is_file = is_file
        self._error = error
        self.size = int(size)

    def exists(self) -> bool:
        return self._exists

    def is_file(self) -> bool:
        return self._is_file

    def read_bytes(self) -> bytes:
        if self._error is not None:
            raise self._error
        if not self._exists:
            raise FileNotFoundError(str(self.path))
        return self._data

    def open(self, mode: str = "rb", *args, **kwargs):
        if mode not in {"rb", "br"}:
            raise ValueError("_CachedReadOnlyFile supports binary read mode only")
        if self._error is not None:
            raise self._error
        if not self._exists:
            raise FileNotFoundError(str(self.path))
        return io.BytesIO(self._data)


def _read_livery_file_once(path: Path) -> _CachedReadOnlyFile:
    """Livery構成ファイルを物理ディスクから1回だけ読み込み、以後の解析で再利用します。"""
    try:
        st = path.stat()
    except FileNotFoundError:
        return _CachedReadOnlyFile(
            path, b"", exists=False, is_file=False, error=None, size=0
        )
    except OSError as exc:
        return _CachedReadOnlyFile(
            path, b"", exists=True, is_file=False, error=exc, size=0
        )

    if not path.is_file():
        return _CachedReadOnlyFile(
            path, b"", exists=True, is_file=False, error=None, size=st.st_size
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        return _CachedReadOnlyFile(
            path, b"", exists=True, is_file=True, error=exc, size=st.st_size
        )
    return _CachedReadOnlyFile(
        path, data, exists=True, is_file=True, error=None, size=len(data)
    )


def sha256_short(path: Path, length: int = 16) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()[:length]
    except OSError:
        return ""


def hash_record_parts(header: Path, c_livery: Path, image: Path) -> str:
    """
    スナップショット複製の判定と、同一内容の再ダウンロード検出に使う
    安定した内容フィンガープリントです。
    """
    h = hashlib.sha256()
    for label, path in (("header", header), ("c_livery", c_livery), ("image", image)):
        h.update(label.encode("ascii"))
        if path.exists() and path.is_file():
            try:
                with path.open("rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
            except OSError:
                h.update(b"<read-error>")
        else:
            h.update(b"<missing>")
    return h.hexdigest()[:24]


def plausible_unicode_text(s: str) -> bool:
    if not s:
        return False
    # 制御文字や私用領域文字が大半を占める文字列は除外します。
    printable = sum(ch.isprintable() and ch not in "\x00\r\n\t" for ch in s)
    if printable / max(1, len(s)) < 0.85:
        return False
    # 英数字またはCJK系の表示可能文字を少なくとも1文字含むことを必須にします。
    return any(ch.isalnum() or ord(ch) >= 0x3000 for ch in s)


def find_length_prefixed_utf16_strings(data: bytes) -> list[tuple[int, int, str]]:
    """
    次の形式のフィールドを探索します。
        uint32 char_count
        wchar_t[char_count] UTF-16LE text

    FH6が既知文字列の間へ未知フィールドを挿入する可能性があるため、
    固定オフセットへ依存せず走査して検出します。
    """
    found: list[tuple[int, int, str]] = []
    i = 0
    while i + 4 <= len(data):
        n = struct.unpack_from("<I", data, i)[0]
        if 1 <= n <= 512 and i + 4 + n * 2 <= len(data):
            raw = data[i + 4:i + 4 + n * 2]
            try:
                s = raw.decode("utf-16le")
            except UnicodeDecodeError:
                s = ""
            if plausible_unicode_text(s):
                found.append((i, n, s))
                i += 4 + n * 2
                continue
        i += 1

    # 重なりや、明らかに重複する入れ子の検出結果を除外します。
    clean: list[tuple[int, int, str]] = []
    last_end = -1
    for off, n, s in sorted(found):
        end = off + 4 + n * 2
        if off < last_end:
            continue
        clean.append((off, n, s))
        last_end = end
    return clean



def extract_livery_reference_id(path: Path) -> tuple[str, list[str]]:
    """
    Liveryごとの識別子と考えられる16バイト値をヒューリスティックに抽出します。

    確認したFH6のheaderサンプルでは、同じ非0の16バイト値がheader末尾付近に2回現れます。
    この反復値を安定した相互参照候補として使いますが、公式に文書化されたXbox IDとは仮定しません。
    """
    warnings: list[str] = []
    if not path.exists():
        return "", ["reference-id: header missing"]

    try:
        data = path.read_bytes()
    except OSError as e:
        return "", [f"reference-id: header read failed: {e}"]

    positions: dict[bytes, list[int]] = {}
    for offset in range(0, max(0, len(data) - 15)):
        value = data[offset:offset + 16]
        if len(value) != 16:
            continue
        # 0が過度に多い値や単純な反復パターンは除外します。
        if value.count(0) >= 8:
            continue
        if len(set(value)) < 8:
            continue
        positions.setdefault(value, []).append(offset)

    candidates = [
        (value, offsets)
        for value, offsets in positions.items()
        if len(offsets) >= 2
    ]
    if not candidates:
        warnings.append("reference-id: no repeated 16-byte candidate found")
        return "", warnings

    # 観測上の識別子はメタデータ末尾付近にあるため、header内で最初の出現位置が
    # より後ろにある候補を優先します。
    candidates.sort(key=lambda item: item[1][0], reverse=True)
    value, offsets = candidates[0]
    warnings.append(
        "reference-id: heuristic repeated 16-byte candidate at "
        + ",".join(f"0x{x:X}" for x in offsets[:4])
    )
    return value.hex(), warnings


def _preferred_containers_root(save_root: Path) -> Optional[Path]:
    """
    古い履歴スナップショットによって削除済み・適用済みLiveryを現行と誤認しないよう、
    <...>/current/ContainersRootを優先します。currentがない場合だけ最大番号の
    数値スナップショットへフォールバックします。
    """
    current_candidates: list[Path] = []
    numeric_candidates: list[tuple[int, Path]] = []

    for dirpath, dirnames, _ in os.walk(save_root):
        for name in dirnames:
            if name.lower() != "containersroot":
                continue
            p = Path(dirpath) / name
            parent = p.parent.name
            if parent.lower() == "current":
                current_candidates.append(p)
            elif parent.isdigit():
                numeric_candidates.append((int(parent), p))

    if current_candidates:
        return sorted(current_candidates, key=lambda p: str(p).lower())[0]
    if numeric_candidates:
        numeric_candidates.sort(key=lambda x: x[0], reverse=True)
        return numeric_candidates[0][1]
    return None


def skip_applied_livery_reference_scan(
    records: list[LiveryRecord],
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """通常生成では未確定の適用Livery参照探索を一時停止します。"""
    for record in records:
        record.applied_state = "unknown"
        record.applied_reference_paths.clear()
    stats = {
        "enabled": False,
        "paused": True,
        "reason": "save-data decryption/structure analysis pending",
        "containers_root": "",
        "reference_ids": 0,
        "applied": 0,
        "not_found": 0,
        "unknown": len(records),
        "files_scanned": 0,
    }
    if progress:
        progress(tr("progress.applied.paused"))
    return stats


def detect_applied_livery_references(
    save_root: Path,
    records: list[LiveryRecord],
    progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    現在のセーブスナップショットから、各Liveryの推定16バイト参照IDが
    Livery_*フォルダ外に完全一致で存在するか検索します。

    状態の意味:
      applied    : Livery_*フォルダ外で参照を検出
      not_found  : IDは抽出できたが現行スナップショット外部に参照なし
      unknown    : 利用可能な参照IDがない、またはcurrent ContainersRootがない

    appliedは強い推定結果ですが、FH6の公式なシリアライズ仕様として確定したものではありません。
    検証用に参照元パスを保持します。
    """
    containers_root = _preferred_containers_root(save_root)
    stats = {
        "containers_root": normpath(containers_root) if containers_root else "",
        "reference_ids": 0,
        "applied": 0,
        "not_found": 0,
        "unknown": 0,
        "files_scanned": 0,
    }

    token_to_records: dict[bytes, list[LiveryRecord]] = {}
    for record in records:
        if not record.livery_reference_id:
            record.applied_state = "unknown"
            stats["unknown"] += 1
            continue
        try:
            token = bytes.fromhex(record.livery_reference_id)
        except ValueError:
            record.applied_state = "unknown"
            stats["unknown"] += 1
            continue
        if len(token) != 16:
            record.applied_state = "unknown"
            stats["unknown"] += 1
            continue
        token_to_records.setdefault(token, []).append(record)

    stats["reference_ids"] = sum(len(v) for v in token_to_records.values())

    if containers_root is None:
        for records_for_token in token_to_records.values():
            for record in records_for_token:
                record.applied_state = "unknown"
                stats["unknown"] += 1
        return stats

    if not token_to_records:
        return stats

    # 1つの正規表現でファイル内の候補トークンをまとめて探し、候補数×ファイル数の走査を避けます。
    token_pattern = re.compile(
        b"|".join(re.escape(token) for token in token_to_records)
    )

    for dirpath, dirnames, filenames in os.walk(containers_root):
        # 保存済みLiveryフォルダ内には自己参照が想定されるため、内部へは降りません。
        dirnames[:] = [
            d for d in dirnames
            if not d.lower().startswith("livery_")
        ]

        for filename in filenames:
            path = Path(dirpath) / filename
            stats["files_scanned"] += 1
            if progress and stats["files_scanned"] % 250 == 0:
                progress(tr("progress.applied.files", files=stats["files_scanned"]))

            try:
                # セーブデータは大きい場合があります。mmapも候補ですが、可搬性を優先して
                # 上限付きの通常読込を使い、256 MiBを超えるファイルはスキップします。
                size = path.stat().st_size
                if size > 256 * 1024 * 1024:
                    continue
                data = path.read_bytes()
            except OSError:
                continue

            seen_in_file: set[bytes] = set()
            for match in token_pattern.finditer(data):
                token = match.group(0)
                if token in seen_in_file:
                    continue
                seen_in_file.add(token)
                try:
                    rel = str(path.relative_to(containers_root))
                except ValueError:
                    rel = str(path)
                for record in token_to_records[token]:
                    if rel not in record.applied_reference_paths:
                        record.applied_reference_paths.append(rel)

    # 最終状態を確定します。
    stats["applied"] = stats["not_found"] = stats["unknown"] = 0
    for record in records:
        if not record.livery_reference_id:
            record.applied_state = "unknown"
            stats["unknown"] += 1
        elif record.applied_reference_paths:
            record.applied_state = "applied"
            stats["applied"] += 1
        else:
            record.applied_state = "not_found"
            stats["not_found"] += 1

    if progress:
        progress(tr(
            "progress.applied.complete",
            applied=stats["applied"],
            not_found=stats["not_found"],
            unknown=stats["unknown"],
        ))

    return stats


def parse_header(path: Path) -> tuple[str, str, str, str, str, list[str], list[str]]:
    """
    確認済みのFH6 ``header`` レイアウトからタイトル・説明・作成者と
    FH6「マイデザイン」画面の日付を読み取ります。

    基本レイアウト:
        u32 format_version
        u32 name_length_utf16
        UTF-16LE name
        u32 description_length_utf16
        UTF-16LE description（長さ > 0 の場合）
        u16 year
        u8  month
        u8  legacy_day        # 現行ダウンロードデータでは0
        byte[16] metadata field block
            byte[0:2] reserved/metadata
            u16 display_day   # byte[2:4] little-endian
        byte[8] creator identity tag
        u32 creator_name_length_utf16
        UTF-16LE creator name
        ...

    display_dayは実データ799件とFH6画面の複数の既知例で照合し、
    実画面との一致を確認済みです。表示形式はDD/MM/YYYYです。

    構造解析に失敗した場合は、旧形式・特殊形式でもタイトル等を拾えるよう
    保守的なUTF-16文字列走査へフォールバックします。日付は推測しません。
    """
    warnings: list[str] = []
    if not path.exists():
        return "", "", "", "", "", [], ["header missing"]

    try:
        data = path.read_bytes()
    except OSError as e:
        return "", "", "", "", "", [], [f"header read failed: {e}"]

    def read_u32(off: int) -> tuple[int, int]:
        if off + 4 > len(data):
            raise ValueError(f"u32 out of bounds at 0x{off:X}")
        return struct.unpack_from("<I", data, off)[0], off + 4

    def read_utf16(off: int, units: int, label: str) -> tuple[str, int]:
        if units < 0 or units > 4096:
            raise ValueError(f"{label} UTF-16 length looks implausible: {units}")
        end = off + units * 2
        if end > len(data):
            raise ValueError(
                f"{label} UTF-16 data out of bounds: units={units}, off=0x{off:X}"
            )
        raw = data[off:end]
        try:
            value = raw.decode("utf-16le")
        except UnicodeDecodeError as e:
            raise ValueError(f"{label} UTF-16 decode failed: {e}") from e
        return value, end

    try:
        off = 0
        format_version, off = read_u32(off)

        name_units, off = read_u32(off)
        title, off = read_utf16(off, name_units, "name")

        desc_units, off = read_u32(off)
        description, off = read_utf16(off, desc_units, "description")

        fixed_size = 2 + 1 + 1 + 16 + 8
        if off + fixed_size + 4 > len(data):
            raise ValueError("header fixed metadata/creator identity block is truncated")

        date_off = off
        year = struct.unpack_from("<H", data, date_off)[0]
        month = data[date_off + 2]
        legacy_day = data[date_off + 3]
        field_block = data[date_off + 4:date_off + 20]
        display_day = struct.unpack_from("<H", field_block, 2)[0]

        fh6_date_raw = ""
        fh6_date_display = ""
        try:
            parsed_fh6_date = datetime(year, month, display_day)
            fh6_date_raw = parsed_fh6_date.strftime("%Y-%m-%d")
            fh6_date_display = parsed_fh6_date.strftime("%d/%m/%Y")
        except ValueError:
            if year or month or legacy_day or display_day:
                warnings.append(
                    "FH6 display date metadata is unusual: "
                    f"year={year}, month={month}, legacy_day={legacy_day}, "
                    f"field_day={display_day}"
                )

        off += fixed_size
        creator_units, off = read_u32(off)
        creator, off = read_utf16(off, creator_units, "creator")
        texts = [title, description, creator]

        if not plausible_unicode_text(title):
            warnings.append("header structured name contains unusual text")
        if description and not plausible_unicode_text(description):
            warnings.append("header structured description contains unusual text")
        if creator and not plausible_unicode_text(creator):
            warnings.append("header structured creator contains unusual text")
        if not (1 <= format_version <= 100):
            warnings.append(f"header format version looks unusual: {format_version}")
        if year and not (2000 <= year <= 2200):
            warnings.append(f"header metadata year looks unusual: {year}")

        return title, description, creator, fh6_date_raw, fh6_date_display, texts, warnings

    except (ValueError, struct.error) as e:
        warnings.append(f"header structured parse failed; using fallback scan: {e}")

    fields = find_length_prefixed_utf16_strings(data)
    texts = [text for _, _, text in fields]
    title = texts[0] if len(texts) >= 1 else ""
    description = texts[1] if len(texts) >= 2 else ""
    creator = texts[2] if len(texts) >= 3 else ""
    if len(texts) < 3:
        warnings.append(
            f"header fallback: expected at least 3 length-prefixed UTF-16 strings; "
            f"found {len(texts)}"
        )
    return title, description, creator, "", "", texts, warnings

def inspect_c_livery(
    path: Path,
) -> tuple[
    Optional[int], Optional[int], Optional[int], bool, Optional[int], list[str]
]:
    """
    C_liveryコンテナ:
        uint32 compressed_size
        uint32 uncompressed_size
        zlib payload

    展開後ストリーム:
        vlrc ... yrvl ... gyvl ... yrvl（section counters） ...

    Car IDは展開後オフセット0x10に格納されています。

    バイナル数:
    ``gyvl``アートワーク直後にある最初の``yrvl``がセクションカウンタレコードです。
    Front / Back / Top / Left / Right / Spoiler / 5つのwindow sectionに対応する11個のu32占有数と、
    末尾のu32カウンタ1個を含みます。表示するバイナル数は先頭11カウンタの合計です。

    ForzaLiveryStudioで公開されているFH6 C_livery形式の情報に沿って解析します。
    誤推定を避けるため厳密に検証し、レコード形状を確認できない場合はvinyl_countを不明のままにします。
    """
    warnings: list[str] = []
    if not path.exists():
        return None, None, None, False, None, ["C_livery missing"]

    try:
        data = path.read_bytes()
    except OSError as e:
        return None, None, None, False, None, [f"C_livery read failed: {e}"]

    if len(data) < 8:
        return None, None, None, False, None, ["C_livery shorter than 8-byte size header"]

    compressed_size, uncompressed_size = struct.unpack_from("<II", data, 0)
    payload = data[8:]

    if compressed_size != len(payload):
        warnings.append(
            f"C_livery compressed size mismatch: header={compressed_size}, actual={len(payload)}"
        )

    try:
        dec = zlib.decompress(payload)
    except zlib.error as e:
        warnings.append(f"C_livery zlib decode failed: {e}")
        return compressed_size, uncompressed_size, None, False, None, warnings

    valid = True
    if len(dec) != uncompressed_size:
        valid = False
        warnings.append(
            f"C_livery uncompressed size mismatch: header={uncompressed_size}, actual={len(dec)}"
        )

    car_id = None
    if len(dec) >= 0x14:
        car_id = struct.unpack_from("<I", dec, 0x10)[0]
        if not (0 < car_id < 100000):
            warnings.append(f"C_livery offset 0x10 value looks implausible as Car ID: {car_id}")
            car_id = None
    else:
        warnings.append("C_livery decompressed data is too short for Car ID at 0x10")

    vinyl_count: Optional[int] = None
    gyvl_off = dec.find(b"gyvl")
    if gyvl_off < 0:
        warnings.append("C_livery artwork tag gyvl not found")
    else:
        counters_off = dec.find(b"yrvl", gyvl_off + 4)
        if counters_off < 0:
            warnings.append("C_livery section-counter yrvl not found after gyvl")
        elif counters_off + 52 > len(dec):
            warnings.append("C_livery section-counter record is truncated")
        else:
            # 4バイトのyrvlタグ + リトルエンディアンu32値×12です。
            values = struct.unpack_from("<12I", dec, counters_off + 4)
            next_tag_off = counters_off + 52

            # 確認済みのFH6レイアウトでは、descriptor-tableのyrvlは
            # この固定長カウンタレコードの直後に続きます。
            if dec[next_tag_off:next_tag_off + 4] != b"yrvl":
                warnings.append(
                    "C_livery section-counter record failed next-yrvl validation"
                )
            else:
                section_counts = values[:11]
                trailing_counter = values[11]

                # 破損や誤解析で極端に大きな値を表示しないよう、
                # 防御的な妥当性上限を設けます。
                if any(v > 1_000_000 for v in section_counts):
                    warnings.append(
                        "C_livery section counters contain implausibly large values"
                    )
                else:
                    vinyl_count = int(sum(section_counts))
                    if trailing_counter > 1_000_000:
                        warnings.append(
                            "C_livery trailing section counter looks implausible"
                        )

    return (
        compressed_size,
        uncompressed_size,
        car_id,
        valid,
        vinyl_count,
        warnings,
    )


JST = timezone(timedelta(hours=9), name="JST")


def parse_timestamp(raw: str) -> str:
    """Liveryフォルダ名に埋め込まれたUTC時刻を日本時間へ変換します。

    14桁の生値は識別・並び替え・出典追跡用に``timestamp_raw``として別途保持し、
    利用者向け表示はJST（UTC+9）を既定とします。
    """
    try:
        utc_dt = datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return utc_dt.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    except ValueError:
        return raw


def snapshot_name_for_livery_dir(livery_dir: Path) -> str:
    """
    .../<snapshot>/ContainersRoot/Livery_x から <snapshot> を返します。
    """
    try:
        parent = livery_dir.parent
        if parent.name.lower() == CONTAINERS_ROOT_NAME.lower():
            return parent.parent.name
    except Exception:
        pass
    return ""


def snapshot_preference(snapshot: str) -> tuple[int, int]:
    """
    タプル値が大きいものを優先します。
      current > 数値スナップショット > その他
    """
    s = snapshot.lower()
    if s == "current":
        return (3, 0)
    if snapshot.isdigit():
        return (2, int(snapshot))
    return (1, 0)


def find_livery_dirs(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, _ in os.walk(root):
        # 探索中の除外処理で一覧が変化するため、名前一覧をコピーしてから処理します。
        for name in list(dirnames):
            if LIVERY_DIR_RE.match(name):
                yield Path(dirpath) / name
                # Liveryディレクトリ内部へ降りる必要はありません。
                try:
                    dirnames.remove(name)
                except ValueError:
                    pass


def _parse_livery_dir(root: Path, livery_dir: Path) -> Optional[LiveryRecord]:
    """1つのLiveryフォルダーを独立して解析します。並列workerから呼び出せる純粋な単位です。"""
    m = LIVERY_DIR_RE.match(livery_dir.name)
    if not m:
        return None

    folder_car_id = int(m.group(1))
    timestamp_raw = m.group(2)
    header_path = livery_dir / "header"
    c_livery_path = livery_dir / "C_livery"
    image_path = livery_dir / "bigThumb.webp"

    # 3ファイルは物理ディスクから各1回だけ読み込みます。
    header = _read_livery_file_once(header_path)
    c_livery = _read_livery_file_once(c_livery_path)
    image = _read_livery_file_once(image_path)

    (
        title, description, creator, fh6_date_raw, fh6_date_display, strings, hw,
    ) = parse_header(header)
    reference_id, rw = extract_livery_reference_id(header)
    c_comp, c_uncomp, c_car_id, zvalid, vinyl_count, cw = inspect_c_livery(c_livery)
    warnings = hw + rw + cw

    verified = c_car_id == folder_car_id if c_car_id is not None else False
    if c_car_id is not None and c_car_id != folder_car_id:
        warnings.append(
            f"Car ID mismatch: folder={folder_car_id}, C_livery={c_car_id}"
        )

    try:
        rel_dir = str(livery_dir.relative_to(root))
    except ValueError:
        rel_dir = str(livery_dir)

    fp = hash_record_parts(header, c_livery, image)

    return LiveryRecord(
        livery_id=livery_dir.name,
        car_id=folder_car_id,
        car_id_folder=folder_car_id,
        car_id_c_livery=c_car_id,
        car_id_verified=verified,
        timestamp_raw=timestamp_raw,
        timestamp_local_guess=parse_timestamp(timestamp_raw),
        fh6_date_raw=fh6_date_raw,
        fh6_date_display=fh6_date_display,
        title=title,
        description=description,
        creator=creator,
        header_strings=strings,
        vehicle_display_name="",
        vehicle_make="",
        vehicle_model="",
        vehicle_year=None,
        vehicle_asset="",
        vehicle_source="",
        source_dir=normpath(livery_dir),
        relative_source_dir=rel_dir,
        snapshot_name=snapshot_name_for_livery_dir(livery_dir),
        preferred_copy=False,
        header_path=normpath(header_path) if header.exists() else "",
        c_livery_path=normpath(c_livery_path) if c_livery.exists() else "",
        image_path=normpath(image_path) if image.exists() else "",
        report_image="",
        header_size=header.size if header.exists() else 0,
        c_livery_size=c_livery.size if c_livery.exists() else 0,
        image_size=image.size if image.exists() else 0,
        header_sha256_16=sha256_short(header) if header.exists() else "",
        c_livery_sha256_16=sha256_short(c_livery) if c_livery.exists() else "",
        image_sha256_16=sha256_short(image) if image.exists() else "",
        fingerprint=fp,
        c_livery_compressed_size=c_comp,
        c_livery_uncompressed_size=c_uncomp,
        c_livery_zlib_valid=zvalid,
        vinyl_count=vinyl_count,
        duplicate_copies=1,
        duplicate_sources=[],
        livery_reference_id=reference_id,
        applied_state="unknown",
        applied_reference_paths=[],
        parse_warnings=warnings,
    )


def scan_liveries(
    root: Path,
    progress: Optional[Callable[[str], None]] = None,
) -> tuple[list[LiveryRecord], list[LiveryRecord], dict]:
    root = root.resolve()
    raw_records: list[LiveryRecord] = []
    livery_dirs = list(find_livery_dirs(root))
    worker_count = LIVERY_SCAN_WORKERS

    if worker_count == 1:
        for idx, livery_dir in enumerate(livery_dirs, 1):
            if progress and idx % 25 == 0:
                progress(tr("progress.livery.parse", current=idx, total=len(livery_dirs)))
            record = _parse_livery_dir(root, livery_dir)
            if record is not None:
                raw_records.append(record)
    else:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="fh6-livery",
        ) as executor:
            futures = [
                executor.submit(_parse_livery_dir, root, livery_dir)
                for livery_dir in livery_dirs
            ]
            for idx, future in enumerate(as_completed(futures), 1):
                record = future.result()
                if record is not None:
                    raw_records.append(record)
                if progress and idx % 25 == 0:
                    progress(tr("progress.livery.parse", current=idx, total=len(livery_dirs)))

    # FH6本体の「マイデザイン」は、同じペイントを複数回ダウンロードした場合でも
    # Livery_* フォルダー単位の別スロットとして表示します。Organizerでも整理対象として
    # 現在（または最新）の1スナップショット内に実在する再ダウンロード重複は別件で保持します。
    # 過去/別スナップショットに残る同一コピーだけを履歴コピーとして除外します。
    snapshot_names = {r.snapshot_name for r in raw_records if r.snapshot_name}
    if any(name.lower() == "current" for name in snapshot_names):
        preferred_snapshot = next(name for name in snapshot_names if name.lower() == "current")
    else:
        numeric_snapshots = [name for name in snapshot_names if name.isdigit()]
        if numeric_snapshots:
            preferred_snapshot = max(numeric_snapshots, key=lambda value: int(value))
        elif snapshot_names:
            preferred_snapshot = max(snapshot_names, key=snapshot_preference)
        else:
            preferred_snapshot = ""

    fh6_instances = [
        r for r in raw_records
        if (r.snapshot_name == preferred_snapshot if preferred_snapshot else True)
    ]
    fh6_instances.sort(
        key=lambda r: (r.car_id, r.timestamp_raw, r.fingerprint, r.livery_id)
    )

    # Organizerでは、過去/別スナップショットにある同じLivery_*のコピーは
    # これまでどおり1件へまとめます。一方、現在（または最新）スナップショット内で
    # 同じ内容を別Livery_*として再ダウンロードしている場合は、整理対象として
    # 個別に残します。これにより通常一覧を含むすべての並び順で実スロットを扱えます。
    groups: dict[str, list[LiveryRecord]] = {}
    for r in raw_records:
        groups.setdefault(r.fingerprint, []).append(r)

    records: list[LiveryRecord] = []
    for fingerprint, copies in groups.items():
        copies.sort(
            key=lambda r: (
                snapshot_preference(r.snapshot_name),
                r.timestamp_raw,
                r.relative_source_dir,
            ),
            reverse=True,
        )
        chosen = copies[0]
        current_copies = [
            r for r in copies
            if (r.snapshot_name == preferred_snapshot if preferred_snapshot else True)
        ]
        visible_copies = current_copies if current_copies else [chosen]

        # 既存localStorageとの互換性のため、従来選ばれていた代表コピーには
        # fingerprintそのものをUIキーとして残します。追加の実スロットだけ
        # Livery ID由来の安定した接尾辞を付けます。
        canonical = next((r for r in visible_copies if r is chosen), None)
        if canonical is None:
            canonical = max(
                visible_copies,
                key=lambda r: (r.timestamp_raw, r.relative_source_dir, r.livery_id),
            )

        duplicate_sources = [r.relative_source_dir for r in copies]
        for record in visible_copies:
            record.preferred_copy = record is canonical
            record.duplicate_copies = len(copies)
            record.duplicate_sources = duplicate_sources
            if record is canonical:
                record.ui_key = fingerprint
            else:
                instance_suffix = hashlib.sha1(
                    record.livery_id.encode("utf-8", errors="replace")
                ).hexdigest()[:10]
                record.ui_key = f"{fingerprint}-{instance_suffix}"
            records.append(record)

    records.sort(
        key=lambda r: (r.car_id, r.timestamp_raw, r.fingerprint, r.livery_id)
    )

    fh6_fingerprint_counts: dict[str, int] = {}
    for record in fh6_instances:
        fh6_fingerprint_counts[record.fingerprint] = fh6_fingerprint_counts.get(record.fingerprint, 0) + 1
    exact_duplicate_counts = [count for count in fh6_fingerprint_counts.values() if count >= 2]
    exact_redownload_groups = len(exact_duplicate_counts)
    exact_redownload_cards = sum(exact_duplicate_counts)
    exact_redownload_instances = sum(count - 1 for count in exact_duplicate_counts)
    stats = {
        "raw_livery_folders": len(raw_records),
        # 画面上で整理できる物理ペイント件数。現在スナップショット内の
        # 完全一致再ダウンロードは別件として数えます。
        "unique_liveries": len(records),
        "distinct_livery_contents": len(groups),
        "duplicate_snapshot_copies_removed": len(raw_records) - len(records),
        "unique_car_ids": len({r.car_id for r in records}),
        "with_thumbnail": sum(bool(r.image_path) for r in records),
        "with_title": sum(bool(r.title) for r in records),
        "with_creator": sum(bool(r.creator) for r in records),
        "car_id_verified": sum(r.car_id_verified for r in records),
        "parse_warning_records": sum(bool(r.parse_warnings) for r in records),
        "fh6_snapshot_name": preferred_snapshot,
        "fh6_my_design_instances": len(fh6_instances),
        "fh6_exact_duplicate_groups": exact_redownload_groups,
        "fh6_exact_duplicate_cards": exact_redownload_cards,
        "fh6_exact_duplicate_instances": exact_redownload_instances,
    }

    if progress:
        progress(tr(
            "progress.livery.complete",
            folders=stats["raw_livery_folders"],
            paints=stats["unique_liveries"],
            vehicles=stats["unique_car_ids"],
            duplicates=stats["fh6_exact_duplicate_instances"],
        ))
    return records, fh6_instances, stats


def safe_filename(s: str, maxlen: int = 100) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")
    return (s or "item")[:maxlen]



_XML_INVALID_RE = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF]"
)


def _xlsx_clean_text(value, max_length: int = 32767) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    text = _XML_INVALID_RE.sub("", text)
    return text[:max_length]


def _xlsx_col_name(index_1based: int) -> str:
    n = int(index_1based)
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result or "A"


def _xlsx_display_units(value: object) -> int:
    """Excel列幅の概算用に、全角文字を2、その他を1として数えます。"""
    text = _xlsx_clean_text(value)
    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _xlsx_localized_column_widths(headers: list[str]) -> tuple[list[float], int]:
    """翻訳後の見出しに合わせて列幅とヘッダー行高を安全な範囲で調整します。

    日本語は従来幅を維持します。英語 / qpsでは狭い列だけ必要に応じて広げ、
    qpsのような長い見出しは無制限に列を広げず、ヘッダーの折り返しも利用します。
    """
    base_widths = [
        24, 12, 10, 34, 18, 24, 9, 24, 20, 12, 26, 40,
        20, 22, 36, 12, 12, 20, 30, 24, 32, 48, 40,
    ]
    if len(headers) != len(base_widths):
        raise ValueError("Excel header/column width count mismatch")
    if get_language() == "ja":
        return [float(width) for width in base_widths], 24

    widths: list[float] = []
    line_counts: list[int] = []
    for header, base in zip(headers, base_widths):
        units = max(1, _xlsx_display_units(header))
        # 既存幅 + 10文字程度を上限にし、横長になりすぎないようにします。
        cap = min(42.0, float(base) + 10.0)
        width = max(float(base), min(cap, 4.0 + units * 0.92))
        width = round(width, 1)
        widths.append(width)
        usable = max(8.0, width - 2.0)
        line_counts.append(max(1, math.ceil(units / usable)))

    max_lines = max(line_counts, default=1)
    header_height = min(60, max(24, 18 * max_lines + 6))
    return widths, header_height


def _xlsx_sheet_name(value: object) -> str:
    """Excelのシート名制約に合わせてローカライズ済み名称を安全化します。"""
    text = _xlsx_clean_text(value, max_length=64).strip()
    text = re.sub(r"[\[\]:*?/\\]", "-", text).strip(" '")
    return (text or "Sheet1")[:31]


def _xlsx_cell_xml(ref: str, value, style: int = 2, numeric: bool = False) -> str:
    if numeric and value is not None and value != "":
        try:
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            number_text = str(int(number)) if number.is_integer() else repr(number)
            return f'<c r="{ref}" s="{style}"><v>{number_text}</v></c>'
        except (TypeError, ValueError):
            pass

    text = _xlsx_clean_text(value)
    return (
        f'<c r="{ref}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{xml_escape(text)}</t></is></c>'
    )


def _xlsx_image_info(path: Path) -> Optional[tuple[str, str]]:
    ext = path.suffix.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    content_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "ico": "image/x-icon",
    }
    content_type = content_types.get(ext)
    return (ext, content_type) if content_type else None


def _validate_xlsx_package(path: Path, expected_rows: int, expected_cols: int) -> None:
    """生成したXLSXを利用者へ提示する前に検証します。"""
    required_parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        "xl/worksheets/sheet1.xml",
    }
    with zipfile.ZipFile(path, "r") as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise ValueError(f"XLSX ZIP CRC error: {bad_member}")

        names = set(zf.namelist())
        missing = sorted(required_parts - names)
        if missing:
            raise ValueError("XLSX required parts missing: " + ", ".join(missing))

        for name in sorted(names):
            if name.endswith(".xml") or name.endswith(".rels"):
                try:
                    ET.fromstring(zf.read(name))
                except ET.ParseError as exc:
                    raise ValueError(f"Invalid XLSX XML: {name}: {exc}") from exc

        # OOXML Extended Properties の AppVersion は、存在する場合 XX.YYYY 形式のみ有効です。
        # 将来の変更で SemVer を直接書き戻してExcel修復警告を再発させないよう検査します。
        if "docProps/app.xml" in names:
            app_root = ET.fromstring(zf.read("docProps/app.xml"))
            app_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"
            app_version = app_root.find(app_ns + "AppVersion")
            if app_version is not None:
                app_version_text = (app_version.text or "").strip()
                if not re.fullmatch(r"\d{2}\.\d{4}", app_version_text):
                    raise ValueError(
                        f"Invalid XLSX AppVersion: {app_version_text!r}; expected XX.YYYY"
                    )

        sheet_root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        children = [child.tag.rsplit("}", 1)[-1] for child in list(sheet_root)]

        if "drawing" in children and "pageMargins" in children:
            if children.index("pageMargins") > children.index("drawing"):
                raise ValueError("Invalid worksheet element order: pageMargins must precede drawing")

        last_col = _xlsx_col_name(expected_cols)
        expected_ref = f"A1:{last_col}{max(1, expected_rows)}"
        auto_filter = sheet_root.find(ns + "autoFilter")
        if auto_filter is None or auto_filter.get("ref") != expected_ref:
            actual = None if auto_filter is None else auto_filter.get("ref")
            raise ValueError(f"Invalid Excel AutoFilter range: {actual!r}, expected {expected_ref!r}")

        pane = sheet_root.find(".//" + ns + "pane")
        if pane is None or pane.get("state") != "frozen" or pane.get("ySplit") != "1":
            raise ValueError("Excel header freeze pane is missing or invalid")

        if "xl/drawings/drawing1.xml" in names:
            if "xl/worksheets/_rels/sheet1.xml.rels" not in names:
                raise ValueError("Worksheet drawing relationship is missing")
            if "xl/drawings/_rels/drawing1.xml.rels" not in names:
                raise ValueError("Drawing image relationships are missing")


def write_excel_report(
    records: list[LiveryRecord],
    outdir: Path,
) -> tuple[Path, int]:
    """サムネイル埋め込みとヘッダーフィルター付きのlivery-organizer-for-fh6.xlsxを作成します。

    XLSXパッケージはPython標準ライブラリだけで生成します。サムネイルは読み取り専用で開き、
    ワークブックへ埋め込みます。GameSaveデータは変更しません。
    """
    xlsx_path = outdir / "livery-organizer-for-fh6.xlsx"
    tmp_path = outdir / "livery-organizer-for-fh6.xlsx.tmp"

    headers = [
        tr("excel.header.thumbnail"), tr("excel.header.decision"), tr("excel.header.car_id"),
        tr("excel.header.vehicle"), tr("excel.header.make"), tr("excel.header.model"),
        tr("excel.header.year"), tr("excel.header.vehicle_asset"), tr("excel.header.creator"),
        tr("excel.header.vinyl_count"), tr("excel.header.title"), tr("excel.header.description"),
        tr("excel.header.acquired_at"), tr("excel.header.tags"), tr("excel.header.notes"),
        tr("excel.header.favorite"), tr("excel.header.review_later"),
        tr("excel.header.livery_reference_id"), tr("excel.header.paint_id"),
        tr("excel.header.fingerprint"), tr("excel.header.thumbnail_source"),
        tr("excel.header.source_folder"), tr("excel.header.analysis_notes"),
    ]

    rows: list[list] = []
    image_sources: list[Optional[Path]] = []
    for r in records:
        image_source: Optional[Path] = None
        if r.image_path:
            candidate = Path(r.image_path)
            if candidate.exists() and candidate.is_file():
                image_source = candidate
        image_sources.append(image_source)
        rows.append([
            tr("excel.value.thumbnail_yes") if image_source else tr("excel.value.thumbnail_no"),
            tr("excel.value.decision_undecided"),
            r.car_id,
            r.vehicle_display_name,
            r.vehicle_make,
            r.vehicle_model,
            r.vehicle_year or "",
            r.vehicle_asset,
            r.creator,
            r.vinyl_count if r.vinyl_count is not None else "",
            r.title,
            r.description,
            r.timestamp_local_guess,
            "",
            "",
            "",
            "",
            r.livery_reference_id,
            r.livery_id,
            r.fingerprint,
            r.image_path,
            r.source_dir,
            " | ".join(r.parse_warnings),
        ])

    row_count = len(rows) + 1
    col_count = len(headers)
    last_col = _xlsx_col_name(col_count)
    filter_ref = f"A1:{last_col}{row_count}"

    column_widths, header_row_height = _xlsx_localized_column_widths(headers)

    media_by_source: dict[str, dict] = {}
    image_row_refs: list[tuple[int, str]] = []
    media_counter = 0
    for excel_row, image_source in enumerate(image_sources, start=2):
        if not image_source:
            continue
        info = _xlsx_image_info(image_source)
        if not info:
            continue
        ext, content_type = info
        try:
            source_key = str(image_source.resolve())
        except OSError:
            source_key = str(image_source)
        media = media_by_source.get(source_key)
        if media is None:
            media_counter += 1
            media = {
                "index": media_counter,
                "ext": ext,
                "content_type": content_type,
                "source": image_source,
                "filename": f"image{media_counter}.{ext}",
                "rid": f"rId{media_counter}",
            }
            media_by_source[source_key] = media
        image_row_refs.append((excel_row, source_key))

    cols_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(column_widths, start=1)
    )

    header_cells = "".join(
        _xlsx_cell_xml(f"{_xlsx_col_name(col)}1", value, style=1)
        for col, value in enumerate(headers, start=1)
    )
    sheet_rows = [
        f'<row r="1" ht="{header_row_height}" customHeight="1">{header_cells}</row>'
    ]

    numeric_columns = {3, 7, 10}
    centered_columns = {2, 3, 7, 10, 16, 17}
    for row_index, values in enumerate(rows, start=2):
        cells = []
        for col_index, value in enumerate(values, start=1):
            ref = f"{_xlsx_col_name(col_index)}{row_index}"
            numeric = col_index in numeric_columns
            style = 3 if col_index in centered_columns else 2
            cells.append(_xlsx_cell_xml(ref, value, style=style, numeric=numeric))
        sheet_rows.append(
            f'<row r="{row_index}" ht="78" customHeight="1">'
            + "".join(cells)
            + "</row>"
        )

    drawing_ref_xml = '<drawing r:id="rId1"/>' if image_row_refs else ""
    worksheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{filter_ref}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
      <selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>{cols_xml}</cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
  <autoFilter ref="{filter_ref}"/>
  <pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
  {drawing_ref_xml}
</worksheet>'''

    styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD9E2F3"/></left>
      <right style="thin"><color rgb="FFD9E2F3"/></right>
      <top style="thin"><color rgb="FFD9E2F3"/></top>
      <bottom style="thin"><color rgb="FFD9E2F3"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

    sheet_name = _xlsx_sheet_name(tr("excel.sheet_name"))
    sheet_name_xml = xml_escape(sheet_name, {'"': '&quot;'})
    workbook_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView xWindow="0" yWindow="0" windowWidth="24000" windowHeight="12000"/></bookViews>
  <sheets><sheet name="{sheet_name_xml}" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''

    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    workbook_title = xml_escape(tr("excel.workbook_title"))
    workbook_language = locale_for_language()
    core_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Livery Organizer for FH6</dc:creator>
  <cp:lastModifiedBy>Livery Organizer for FH6</cp:lastModifiedBy>
  <dc:title>{workbook_title}</dc:title>
  <dc:language>{workbook_language}</dc:language>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now_utc}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now_utc}</dcterms:modified>
</cp:coreProperties>'''

    # AppVersion は OOXML 仕様上 XX.YYYY の数値形式に制限されます。
    # Organizer の SemVer / 開発リビジョン（例: 0.4.58-r06）をそのまま書くと
    # Excel が修復対象として扱うため、任意要素である AppVersion は出力しません。
    app_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Livery Organizer for FH6</Application>
</Properties>'''

    drawing_xml = ""
    drawing_rels = ""
    sheet_rels = ""
    if image_row_refs:
        picture_xml = []
        cx = 160 * 9525
        cy = 90 * 9525
        for picture_id, (excel_row, source_key) in enumerate(image_row_refs, start=1):
            media = media_by_source[source_key]
            row0 = excel_row - 1
            picture_xml.append(f'''
  <xdr:oneCellAnchor>
    <xdr:from><xdr:col>0</xdr:col><xdr:colOff>38100</xdr:colOff><xdr:row>{row0}</xdr:row><xdr:rowOff>38100</xdr:rowOff></xdr:from>
    <xdr:ext cx="{cx}" cy="{cy}"/>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="{picture_id}" name="Thumbnail {picture_id}"/><xdr:cNvPicPr/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="{media['rid']}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>
      <xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>
    </xdr:pic>
    <xdr:clientData/>
  </xdr:oneCellAnchor>''')
        drawing_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">''' + "".join(picture_xml) + "\n</xdr:wsDr>"

        drawing_rel_items = []
        for media in sorted(media_by_source.values(), key=lambda item: item['index']):
            drawing_rel_items.append(
                f'<Relationship Id="{media["rid"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{media["filename"]}"/>'
            )
        drawing_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">''' + "".join(drawing_rel_items) + "</Relationships>"
        sheet_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>'''

    image_content_types: dict[str, str] = {}
    for media in media_by_source.values():
        image_content_types[media['ext']] = media['content_type']
    defaults_xml = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    for ext, content_type in sorted(image_content_types.items()):
        defaults_xml.append(f'<Default Extension="{ext}" ContentType="{content_type}"/>')
    drawing_override = (
        '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        if image_row_refs else ""
    )
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">''' + "".join(defaults_xml) + '''
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>''' + drawing_override + "</Types>"

    outdir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr('[Content_Types].xml', content_types)
            zf.writestr('_rels/.rels', root_rels)
            zf.writestr('docProps/core.xml', core_xml)
            zf.writestr('docProps/app.xml', app_xml)
            zf.writestr('xl/workbook.xml', workbook_xml)
            zf.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
            zf.writestr('xl/styles.xml', styles_xml)
            zf.writestr('xl/worksheets/sheet1.xml', worksheet_xml)
            if image_row_refs:
                zf.writestr('xl/worksheets/_rels/sheet1.xml.rels', sheet_rels)
                zf.writestr('xl/drawings/drawing1.xml', drawing_xml)
                zf.writestr('xl/drawings/_rels/drawing1.xml.rels', drawing_rels)
                for media in media_by_source.values():
                    zf.write(media['source'], f'xl/media/{media["filename"]}')
        _validate_xlsx_package(
            tmp_path,
            expected_rows=len(rows) + 1,
            expected_cols=len(headers),
        )
        tmp_path.replace(xlsx_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

    return xlsx_path, len(image_row_refs)


def write_report(
    root: Path,
    records: list[LiveryRecord],
    stats: dict,
    outdir: Path,
    embed_images: bool = True,
    game_root: Optional[Path] = None,
    vehicle_db: Optional[dict[int, VehicleInfo]] = None,
    export_analysis_data: bool = False,
    fh6_records: Optional[list[LiveryRecord]] = None,
) -> Path:
    # v0.4.40: レポート書込層でも読み取り専用境界を強制し、
    # 直接関数呼び出しでGUI/CLIのチェックを迂回できないようにします。
    ensure_safe_output_directory(root, outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 生成レポートの表示言語はHTML構築の最初に確定します。
    # 英語レポートでは利用者データそのものは変更せず、Organizerが生成する
    # 欠損時のフォールバック文言とJavaScriptのロケール依存表示だけを英語化します。
    report_language = get_language()
    report_english_like = report_language in {"en", "qps"}
    report_locale = locale_for_language(report_language)

    def report_text(ja: str, en: str) -> str:
        if report_language == "qps":
            return pseudo_localize(en)
        return en if report_language == "en" else ja

    report_fallback_manufacturer = report_text("メーカー未取得", "Manufacturer unavailable")
    report_fallback_asset = report_text("車両アセット未取得", "Vehicle asset unavailable")
    report_fallback_title = report_text("(タイトル未取得)", "(Title unavailable)")
    report_fallback_creator = report_text("作成者情報なし", "No creator information")
    report_fallback_no_liveries = report_text("リバリーフォルダが見つかりませんでした。", "No livery folders were found.")
    report_fallback_unknown_error = report_text("不明なエラー", "Unknown error")
    report_fallback_promise_error = report_text("Promiseエラー", "Promise error")
    report_fallback_unknown_date = report_text("日時不明", "Unknown date")
    report_fallback_unknown_vehicle = report_text("車種不明", "Unknown vehicle")
    report_fallback_no_title = report_text("タイトルなし", "No title")
    report_label_newest = report_text("最新", "Newest")
    report_label_oldest = report_text("最古", "Oldest")
    report_baseline_not_set = report_text(
        "新規判定基準: 未設定（現在のカードは新規扱いしません）",
        "New-item baseline: not set (current cards are not treated as new)",
    )
    report_baseline_prefix = report_text("新規判定基準:", "New-item baseline:")
    report_item_suffix = report_text("件", " items")

    # Navigator Bridgeとの共通移動設定をHTML生成時の初期値へ反映します。
    # 静的HTML側の変更はlocalStorageに保持し、「FH6で選択デザインへ移動」実行時にBridgeへ同期されます。
    navigator_settings = load_shared_navigator_settings()
    nav_interval_ms = navigator_settings["interval_ms"]
    nav_switch_delay_ms = navigator_settings["switch_delay_ms"]
    nav_turn_delay_ms = navigator_settings["turn_delay_ms"]
    nav_wrap_delay_ms = navigator_settings["wrap_delay_ms"]
    nav_reset_origin = bool(navigator_settings["reset_origin"])
    nav_reset_esc_delay_ms = navigator_settings["reset_esc_delay_ms"]
    nav_reset_ret_delay_ms = navigator_settings["reset_ret_delay_ms"]
    # recordsは、スナップショット複製だけを除外し、現在/最新スナップショット内の
    # 完全一致再ダウンロードは別カードとして保持します。FH6マイデザイン順では
    # fh6_recordsを使って本体の実スロット配置もそのまま再現します。
    fh6_records = list(fh6_records or records)

    # v0.4.8:
    # サムネイルは2方式に対応します。
    #   embed_images=True  -> 単体HTML内へdata: URIとして埋め込みます。
    #   embed_images=False -> 読み取り専用の元画像をthumbnails/へコピーし、
    #                         HTMLから相対パスで参照します。
    #                         HTML埋め込み導入前と同じ外部参照方式です。
    #
    # GameSave内の画像ファイルは開いて読み取るだけで、変更しません。
    report_images: dict[str, str] = {}
    embedded_source_bytes = 0
    embedded_count = 0
    external_count = 0
    image_mime_types = {
        ".webp": "image/webp",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }
    thumbnails_dir = outdir / "thumbnails"

    if not embed_images and any(r.image_path for r in records):
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
    for r in records:
        if not r.image_path:
            continue
        src = Path(r.image_path)
        if not src.is_file():
            continue

        if embed_images:
            try:
                raw_image = src.read_bytes()
                mime_type = image_mime_types.get(
                    src.suffix.lower(),
                    "application/octet-stream",
                )
                encoded = base64.b64encode(raw_image).decode("ascii")
                report_images[r.fingerprint] = (
                    f"data:{mime_type};base64,{encoded}"
                )
                embedded_source_bytes += len(raw_image)
                embedded_count += 1
            except OSError as e:
                r.parse_warnings.append(f"thumbnail embed failed: {e}")
            continue

        suffix = src.suffix.lower() or ".webp"
        dest_name = safe_filename(
            f"{r.car_id:04d}_{r.timestamp_raw}_{r.image_sha256_16}{suffix}"
        )
        dest = thumbnails_dir / dest_name
        try:
            if not dest.exists():
                shutil.copy2(src, dest)
            relative_image = f"thumbnails/{dest.name}"
            report_images[r.fingerprint] = relative_image
            r.report_image = relative_image
            external_count += 1
        except OSError as e:
            r.parse_warnings.append(f"thumbnail copy failed: {e}")

    stats["html_thumbnail_mode"] = "embedded" if embed_images else "external"
    stats["html_images_embedded"] = embedded_count
    stats["html_images_external"] = external_count
    stats["html_image_source_bytes"] = embedded_source_bytes
    data_dir = outdir / "data"
    json_path = data_dir / "livery-organizer-for-fh6.json"
    csv_path = data_dir / "livery-organizer-for-fh6.csv"
    html_path = outdir / "livery-organizer-for-fh6.html"

    stats["analysis_data_exported"] = bool(export_analysis_data)
    stats["analysis_data_dir"] = normpath(data_dir) if export_analysis_data else ""

    payload = {
        "app": APP_NAME,
        "version": VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": normpath(root),
        "read_only_source": True,
        "game_asset_root": normpath(game_root) if game_root else "",
        "vehicle_database_count": len(vehicle_db or {}),
        "applied_detection": stats.get("applied_detection", {}),
        "stats": stats,
        "format_notes": {
            "livery_folder": "Livery_<4-digit Car ID>_<YYYYMMDDhhmmss>",
            "timestamp": (
                "The 14-digit Livery folder timestamp is treated as UTC for source data; "
                "human-facing acquisition time is converted to Japan Standard Time (JST, UTC+9)."
            ),
            "html_report": (
                "When thumbnail embedding is enabled, thumbnails are stored in the HTML as "
                "data URIs and livery-organizer-for-fh6.html is portable by itself. When embedding "
                "is disabled, thumbnails are copied read-only to the sibling thumbnails/ "
                "directory and the HTML references those relative files. Excel remains separate."
            ),
            "analysis_data": (
                "Normal output contains only the standalone HTML and Excel workbook. "
                "When analysis-data export is enabled, livery JSON/CSV and the vehicle "
                "database JSON/CSV are written under the data directory."
            ),
            "header": (
                "Title/description/creator are parsed from the structured length-prefixed "
                "UTF-16LE header layout, with string discovery as fallback."
            ),
            "c_livery": (
                "uint32 compressed size, uint32 uncompressed size, zlib payload; "
                "decompressed uint32 at 0x10 is Car ID. Vinyl count is the sum "
                "of the 11 logical section occupancy counters in the yrvl "
                "section-counter record immediately following gyvl artwork."
            ),
            "decisions": (
                "Keep/Delete candidate/Undecided marks are stored in browser "
                "localStorage using stable fingerprint keys and can be exported/"
                "imported as a JSON backup. Tags, notes, favorites, review-later flags, "
                "theme and previous-scan state are browser-local and can be exported/imported together. "
                "They are never written into FH6 GameSave."
            ),
        },
        "records": [asdict(r) for r in records],
    }
    if export_analysis_data:
        data_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    csv_headers = [
        "整理状態", "Car ID", "車両名", "メーカー", "モデル", "年式",
        "車両アセット", "作成者", "バイナル数", "タイトル", "説明", "取得日時",
        "タグ", "メモ", "お気に入り", "後で確認", "Livery参照ID", "ペイントID",
        "フィンガープリント", "サムネイル元", "保存元", "解析メモ",
    ]
    # v0.2.3: ここではPython標準のcsvモジュールを使いません。実データのLivery
    # メタデータでcsv.Error("need to escape, but no escapechar set")が発生したため、
    # RFC-4180相当のCSVを独自に直列化します。
    # 全フィールドを引用符で囲み、内部の引用符は二重化することで、
    # カンマ、CR/LF、引用符、タブ、絵文字、CJK、任意のUnicodeを安全に扱います。
    def csv_cell(value) -> str:
        if value is None:
            text = ""
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        # NULは表計算テキストでは不要で、後続アプリの問題要因になるため正規化します。
        # 引用済みセル内のCR/LFは保持します。
        text = text.replace("\x00", "")
        return '"' + text.replace('"', '""') + '"'

    csv_rows = [csv_headers]
    for r in records:
        csv_rows.append([
            "未決定",
            r.car_id,
            r.vehicle_display_name,
            r.vehicle_make,
            r.vehicle_model,
            r.vehicle_year or "",
            r.vehicle_asset,
            r.creator,
            r.vinyl_count if r.vinyl_count is not None else "",
            r.title,
            r.description,
            r.timestamp_local_guess,
            "",
            "",
            "",
            "",
            r.livery_reference_id,
            r.livery_id,
            r.fingerprint,
            r.image_path,
            r.source_dir,
            " | ".join(r.parse_warnings),
        ])

    csv_text = "\r\n".join(
        ",".join(csv_cell(value) for value in row)
        for row in csv_rows
    ) + "\r\n"
    if export_analysis_data:
        data_dir.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("\ufeff" + csv_text, encoding="utf-8")
    # HTMLレポート上部に表示する統計値です。
    unique_makes = sorted({r.vehicle_make for r in records if r.vehicle_make})
    unique_creators = sorted({r.creator for r in records if r.creator})

    creator_counts: dict[str, int] = {}
    for r in records:
        if r.creator:
            creator_counts[r.creator] = creator_counts.get(r.creator, 0) + 1

    creator_ranked = sorted(
        creator_counts.items(),
        key=lambda kv: (-kv[1], kv[0].casefold()),
    )
    creator_top = creator_ranked[:10]
    creator_rest = creator_ranked[10:]

    creator_top_html = "".join(
        f'<button class="creator-chip" type="button" '
        f'data-creator="{html.escape(name.lower())}">'
        f'{html.escape(name)} <b>{count}</b></button>'
        for name, count in creator_top
    )
    creator_rest_html = "".join(
        f'<button class="creator-chip" type="button" '
        f'data-creator="{html.escape(name.lower())}">'
        f'{html.escape(name)} <b>{count}</b></button>'
        for name, count in creator_rest
    )

    if creator_rest_html:
        remaining = len(creator_rest)
        creator_summary_html = (
            f'<div class="creator-top-list">{creator_top_html}</div>'
            f'<button id="creatorMoreToggle" class="creator-more-toggle" '
            f'type="button" aria-expanded="false" '
            f'data-closed-label="残り {remaining}人を表示">'
            f'残り {remaining}人を表示</button>'
            f'<div id="creatorMoreList" class="creator-more-list hidden">'
            f'{creator_rest_html}</div>'
        )
    else:
        creator_summary_html = (
            f'<div class="creator-top-list">{creator_top_html}</div>'
        )

    # 類似候補のグループ化は誤判定を避けるため保守的に行い、
    # 同一Car ID内に限定します。v0.4.23では既存の検出条件を維持しつつ、
    # 比較UIで説明できるようグループ化理由も記録します。
    similarity_groups: dict[tuple, list[LiveryRecord]] = {}
    for r in records:
        if r.image_sha256_16:
            similarity_groups.setdefault(
                ("image", r.car_id, r.image_sha256_16), []
            ).append(r)
        title_key = (r.title or "").strip().casefold()
        creator_key = (r.creator or "").strip().casefold()
        if title_key and creator_key:
            similarity_groups.setdefault(
                ("creator-title", r.car_id, creator_key, title_key), []
            ).append(r)

    similar_count_by_key: dict[str, int] = {}
    similar_group_by_key: dict[str, str] = {}
    similar_kind_by_key: dict[str, str] = {}
    similar_reason_by_key: dict[str, str] = {}
    similar_rank_by_key: dict[str, tuple[int, int]] = {}
    similarity_reason_labels = {
        "image": "サムネイル完全一致",
        "creator-title": "作成者＋タイトル一致",
    }
    # まず候補数が多いグループを優先し、同数なら
    # より強い理由としてメタデータ一致よりサムネイル完全一致を優先します。
    similarity_reason_priority = {"image": 2, "creator-title": 1}
    for group_key, members in similarity_groups.items():
        if len(members) < 2:
            continue
        kind = str(group_key[0])
        group_id = hashlib.sha1(repr(group_key).encode("utf-8")).hexdigest()[:12]
        candidate_rank = (len(members), similarity_reason_priority.get(kind, 0))
        for member in members:
            member_key = member.ui_key or member.fingerprint
            current_rank = similar_rank_by_key.get(member_key, (0, 0))
            if candidate_rank > current_rank:
                similar_rank_by_key[member_key] = candidate_rank
                similar_count_by_key[member_key] = len(members)
                similar_group_by_key[member_key] = group_id
                similar_kind_by_key[member_key] = kind
                similar_reason_by_key[member_key] = similarity_reason_labels.get(kind, "類似条件一致")

    # 現在スナップショット内で同一fingerprintが複数スロットに存在するものを、
    # 「再DL完全一致」として通常の類似候補とは別軸でも識別します。
    exact_duplicate_counts_by_fingerprint: dict[str, int] = {}
    for r in records:
        exact_duplicate_counts_by_fingerprint[r.fingerprint] = exact_duplicate_counts_by_fingerprint.get(r.fingerprint, 0) + 1
    exact_duplicate_count_by_key: dict[str, int] = {}
    exact_duplicate_group_by_key: dict[str, str] = {}
    for r in records:
        count = exact_duplicate_counts_by_fingerprint.get(r.fingerprint, 0)
        if count < 2:
            continue
        record_key = r.ui_key or r.fingerprint
        exact_duplicate_count_by_key[record_key] = count
        exact_duplicate_group_by_key[record_key] = hashlib.sha1(
            f"exact-redownload:{r.car_id}:{r.fingerprint}".encode("utf-8")
        ).hexdigest()[:12]

    known_years = [r.vehicle_year for r in records if r.vehicle_year]
    oldest_year = min(known_years) if known_years else None
    newest_year = max(known_years) if known_years else None

    # FH6「マイデザイン」画面と同じ固定順（Car ID昇順 → 同一Car ID内は取得日時昇順）で
    # 各ペイントの絶対位置を保持します。絞り込み中も番号は詰め直さず、FH6画面との照合位置を維持します。
    my_design_order = sorted(
        records,
        key=lambda r: (r.car_id, r.timestamp_raw, r.fingerprint, r.livery_id),
    )
    my_design_index_by_key = {
        (r.ui_key or r.fingerprint): index
        for index, r in enumerate(my_design_order, start=1)
    }
    my_design_index_width = max(3, len(str(max(1, len(my_design_order)))))

    # FH6マイデザイン順では、通常一覧で隠している「同じペイントの再ダウンロード」も
    # FH6本体と同じ物理スロットとして復元します。
    fh6_my_design_order = sorted(
        fh6_records,
        key=lambda r: (r.car_id, r.timestamp_raw, r.fingerprint, r.livery_id),
    )
    fh6_my_design_column_count = max(1, (len(fh6_my_design_order) + 1) // 2)
    fh6_my_design_column_width = max(3, len(str(fh6_my_design_column_count)))
    fh6_instance_counts: dict[str, int] = {}
    for record in fh6_my_design_order:
        fh6_instance_counts[record.fingerprint] = fh6_instance_counts.get(record.fingerprint, 0) + 1
    fh6_instance_payload = []
    for index, record in enumerate(fh6_my_design_order, start=1):
        column = (index + 1) // 2
        row = "U" if index % 2 == 1 else "D"
        instance_id = hashlib.sha1(
            (
                f"fh6-slot:{index}|{record.ui_key or record.fingerprint}|"
                f"{record.livery_id}|{record.timestamp_raw}|{record.fingerprint}"
            ).encode("utf-8")
        ).hexdigest()[:20]
        fh6_instance_payload.append({
            "instance_id": instance_id,
            "ui_key": record.ui_key or record.fingerprint,
            "fingerprint": record.fingerprint,
            "livery_id": record.livery_id,
            "timestamp_raw": record.timestamp_raw,
            "timestamp_display": record.timestamp_local_guess,
            "fh6_date_raw": record.fh6_date_raw,
            "fh6_date_display": record.fh6_date_display,
            "car_id": record.car_id,
            "vehicle_label": record.vehicle_display_name or f"Car ID {record.car_id:04d}",
            "vehicle_make": record.vehicle_make or "",
            "vehicle_model": record.vehicle_model or "",
            "vehicle_year": record.vehicle_year or 0,
            "title": record.title or "",
            "creator": record.creator or "",
            "column": column,
            "row": row,
            "slot_number": index,
            "position": f"#{column:0{fh6_my_design_column_width}d}{row}",
            "duplicate_instance": fh6_instance_counts.get(record.fingerprint, 0) >= 2,
        })
    fh6_instance_json = json.dumps(
        fh6_instance_payload, ensure_ascii=False, separators=(",", ":")
    ).replace("<", "\\u003c")
    # 仮削除状態は生成したHTML単位で分離します。新しくHTMLを生成すれば別スコープになり、
    # 古い仮削除状態を意図せず引き継ぎません。同じHTMLの再読込ではlocalStorageから復元します。
    fh6_temp_delete_scope = os.urandom(10).hex()

    # HTMLをCar ID単位でグループ化します。
    by_car: dict[int, list[LiveryRecord]] = {}
    for r in records:
        by_car.setdefault(r.car_id, []).append(r)

    # ペイント件数フィルターの候補は実際のレポートデータから生成し、
    # このレポートに存在する件数だけを表示します。
    paint_count_values = sorted({len(rs) for rs in by_car.values() if rs})
    paint_count_options_html = "".join(
        f'<option value="{count}">ペイント件数: {count}件</option>'
        for count in paint_count_values
    )
    groups_html: list[str] = []
    for car_id in sorted(by_car):
        rs = sorted(by_car[car_id], key=lambda x: x.timestamp_raw, reverse=True)
        cards: list[str] = []

        for r in rs:
            search_text = " ".join([
                str(r.car_id), r.vehicle_display_name, r.vehicle_make,
                r.vehicle_model, r.vehicle_asset, r.title, r.description,
                r.creator, r.applied_state, r.timestamp_raw,
                str(r.vinyl_count or ""), r.livery_id, r.source_dir
            ]).lower()

            report_image = report_images.get(r.fingerprint, "")
            image_html = (
                f'<img loading="lazy" decoding="async" class="livery-image" '
                f'src="{html.escape(report_image)}" '
                f'data-full="{html.escape(report_image)}" '
                f'alt="{html.escape(r.title or r.livery_id)}" '
                f'title="クリックで拡大">'
                if report_image
                else '<div class="noimg">No thumbnail</div>'
            )

            # Car IDの検証結果はレポート内部データに保持しますが、
            # コンパクトなHTMLカードには意図的に表示しません。
            # スナップショットのコピー数も生データ・技術データには保持しますが、
            # 通常のカードUIからは省略します。
            dup = ""
            record_key = r.ui_key or r.fingerprint
            similar_count = similar_count_by_key.get(record_key, 0)
            similar_group = similar_group_by_key.get(record_key, "")
            similar_kind = similar_kind_by_key.get(record_key, "")
            similar_reason = similar_reason_by_key.get(record_key, "")
            exact_duplicate_count = exact_duplicate_count_by_key.get(record_key, 0)
            exact_duplicate_group = exact_duplicate_group_by_key.get(record_key, "")
            similar_badge_label = {
                "image": "画像一致",
                "creator-title": "同一作者・同名",
            }.get(similar_kind, "類似候補")
            my_design_index = my_design_index_by_key.get(record_key, 0)
            my_design_index_label = f"#{my_design_index:0{my_design_index_width}d}" if my_design_index else "#---"
            fh6_my_design_column = (my_design_index + 1) // 2 if my_design_index else 0
            fh6_my_design_row = "U" if my_design_index and my_design_index % 2 == 1 else ("D" if my_design_index else "")
            fh6_my_design_position_label = (
                f"#{fh6_my_design_column:0{fh6_my_design_column_width}d}{fh6_my_design_row}"
                if fh6_my_design_column else "#---"
            )
            vinyl_level = (
                "extreme" if (r.vinyl_count or 0) >= 10000 else
                "high" if (r.vinyl_count or 0) >= 5000 else
                "medium" if (r.vinyl_count or 0) >= 1000 else
                "normal"
            )

            cards.append(f"""
<article class="card" data-key="{html.escape(record_key)}"
         data-search="{html.escape(search_text)}"
         data-car="{r.car_id}"
         data-vehicle="{html.escape((r.vehicle_display_name or "").lower())}"
         data-make="{html.escape((r.vehicle_make or "").lower())}"
         data-model="{html.escape((r.vehicle_model or r.vehicle_display_name or "").lower())}"
         data-year="{r.vehicle_year or 0}"
         data-creator="{html.escape((r.creator or "").lower())}"
         data-creator-display="{html.escape(r.creator or "")}"
         data-timestamp="{html.escape(r.timestamp_raw)}"
         data-timestamp-display="{html.escape(r.timestamp_local_guess or "")}"
         data-fh6-date="{html.escape(r.fh6_date_raw or "")}"
         data-fh6-date-display="{html.escape(r.fh6_date_display or "")}"
         data-my-design-index="{my_design_index}"
         data-fh6-my-design-column="{fh6_my_design_column}"
         data-fh6-my-design-row="{html.escape(fh6_my_design_row)}"
         data-title="{html.escape((r.title or "").lower())}"
         data-title-display="{html.escape(r.title or "")}"
         data-description="{html.escape(r.description or "")}"
         data-livery-id="{html.escape(r.livery_id)}"
         data-paint-count="{len(rs)}"
         data-vinyl-count="{r.vinyl_count if r.vinyl_count is not None else -1}"
         data-vinyl-level="{vinyl_level}"
         data-similar-count="{similar_count}"
         data-similar-group="{html.escape(similar_group)}"
         data-similar-kind="{html.escape(similar_kind)}"
         data-similar-reason="{html.escape(similar_reason)}"
         data-exact-duplicate="{1 if exact_duplicate_count >= 2 else 0}"
         data-exact-duplicate-count="{exact_duplicate_count}"
         data-exact-duplicate-group="{html.escape(exact_duplicate_group)}"
         data-is-new="0"
         data-tags=""
         data-applied="{html.escape(r.applied_state)}">
  {image_html}
  <div class="body">
    <div class="topline">
      <label class="select-box compact-optional-selection" title="一括操作の対象"><input class="card-select" type="checkbox"></label>
      <span class="fh6-move-target-group" role="group" aria-label="FH6移動位置">
        <span class="fh6-move-target-caption">FH6移動:</span>
        <button class="pill my-design-index fh6-move-target-trigger" type="button" title="クリックしてFH6移動対象に設定">{my_design_index_label}</button>
        <button class="pill fh6-my-design-position fh6-move-target-trigger" type="button" title="クリックしてFH6移動対象に設定">{fh6_my_design_position_label}</button>
      </span>
      <span class="fh6-secondary-badges">
        <span class="pill new-badge hidden">新規</span>
        <button class="pill flag-toggle favorite-toggle compact-optional-flags" type="button">☆ お気に入り</button>
        <button class="pill flag-toggle review-toggle compact-optional-flags" type="button">後で確認</button>
        {f'<button class="pill exact-duplicate open-exact-duplicate" type="button" title="再DL重複グループを比較して残す1件を選択">再DL重複 {exact_duplicate_count}件</button>' if exact_duplicate_count >= 2 else ''}
        {f'<button class="pill similar compare-similar" type="button" title="類似候補: {html.escape(similar_reason)}">{html.escape(similar_badge_label)} {similar_count}件</button>' if similar_count >= 2 else ''}
        {dup}
      </span>
    </div>

    <h3 class="vehicle quick-filter card-vehicle-sort-only"
        data-filter-type="car" data-filter-value="{r.car_id}"
        title="クリックしてこの車種だけ表示">{html.escape(r.vehicle_display_name or f"Car ID {r.car_id:04d}")}</h3>
    <div class="vehicle-meta compact-optional-make-year">{
      (f'<button class="link-filter" type="button" data-filter-type="make" data-filter-value="{html.escape((r.vehicle_make or "").lower())}">{html.escape(r.vehicle_make)}</button>' if r.vehicle_make else html.escape(report_fallback_manufacturer))
      + (" / " + str(r.vehicle_year) if r.vehicle_year else "")
    }</div>
    <div class="asset compact-optional-asset">{html.escape(r.vehicle_asset or report_fallback_asset)}</div>
    <h4>{
      f'<button class="link-filter title-filter" type="button" data-filter-type="title" data-filter-value="{html.escape(r.title)}" title="クリックしてこのタイトルで検索">{html.escape(r.title)}</button>'
      if r.title else html.escape(report_fallback_title)
    }</h4>
    <p class="desc compact-optional-description">{html.escape(r.description or "—")}</p>

    <div class="fh6-creator-display" title="FH6画面の作成者">{
      f'<button class="link-filter" type="button" data-filter-type="creator" data-filter-value="{html.escape((r.creator or "").lower())}">{html.escape(r.creator)}</button>'
      if r.creator else "—"
    }</div>
    <div class="fh6-display-date{' hidden' if not r.fh6_date_display else ''}" title="FH6画面の日付">{html.escape(r.fh6_date_display or "")}</div>

    <dl>
      <dt class="fh6-normal-creator-row">作成者</dt><dd class="fh6-normal-creator-row">{
        f'<button class="link-filter" type="button" data-filter-type="creator" data-filter-value="{html.escape((r.creator or "").lower())}">{html.escape(r.creator)}</button>'
        if r.creator else "—"
      }</dd>
      <dt class="compact-optional-acquired compact-detail-label">取得日時</dt><dd class="compact-optional-acquired compact-detail-value" title="{html.escape(r.timestamp_local_guess)}">{html.escape(r.timestamp_local_guess)}</dd>
      <dt class="compact-optional-vinyl compact-detail-label">バイナル数</dt><dd class="compact-optional-vinyl compact-detail-value">{f"{r.vinyl_count:,}" if r.vinyl_count is not None else "—"}</dd>
    </dl>

    <details class="personal-meta compact-optional-personal">
      <summary>タグ・メモ</summary>
      <label>タグ<input class="tag-input" type="text" placeholder="例: 痛車, レーシング"></label>
      <label>メモ<textarea class="note-input" rows="2" placeholder="このペイントについてのメモ"></textarea></label>
    </details>
    <div class="decision" role="group" aria-label="整理状態">
      <button type="button" data-state="keep">残す</button>
      <button type="button" data-state="delete">削除候補</button>
      <button type="button" data-state="undecided">未決定</button>
    </div>

  </div>
</article>""")

        group_vehicle = next(
            (x.vehicle_display_name for x in rs if x.vehicle_display_name),
            "",
        )
        group_title = (
            f"{group_vehicle} · Car ID {car_id:04d}"
            if group_vehicle else f"Car ID {car_id:04d}"
        )
        groups_html.append(f"""
<section class="car-group" data-car-group="{car_id}" data-paint-count="{len(rs)}">
  <div class="group-heading">
    <h2>{html.escape(group_title)}</h2>
    <span class="group-count-badge">{len(rs)}件</span>
    <button type="button" class="group-progress-badge" data-group-progress data-progress-state="none"
            data-progress-car="{car_id}" title="クリックしてこの車種だけ表示">
      <progress class="group-progress-bar" max="{len(rs)}" value="0"></progress>
      <span class="group-progress-text" data-group-progress-text>整理 — / {len(rs)}</span>
    </button>
  </div>
  <div class="grid">
    {''.join(cards)}
  </div>
</section>""")
    # CSV出力用メタデータは解析済みレコードから直接埋め込みます。
    # ブラウザのレイアウトや描画結果をCSVのデータ源にはしません。
    csv_export_map = {
        (r.ui_key or r.fingerprint): {
            "ui_key": r.ui_key or r.fingerprint,
            "car_id": str(r.car_id),
            "vehicle": r.vehicle_display_name or "",
            "manufacturer": r.vehicle_make or "",
            "model": r.vehicle_model or "",
            "year": str(r.vehicle_year) if r.vehicle_year else "",
            "vehicle_asset": r.vehicle_asset or "",
            "creator": r.creator or "",
            "vinyl_count": str(r.vinyl_count) if r.vinyl_count is not None else "",
            "title": r.title or "",
            "description": r.description or "",
            "timestamp": r.timestamp_local_guess or "",
            "livery_reference_id": r.livery_reference_id or "",
            "livery_id": r.livery_id,
            "fingerprint": r.fingerprint,
            "image_path": r.image_path or "",
            "source_dir": r.source_dir or "",
            "analysis_notes": " | ".join(r.parse_warnings),
        }
        for r in records
    }
    csv_export_json = json.dumps(
        csv_export_map,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    doc = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Livery Organizer for FH6 v{VERSION}</title>
<style>
:root {{
  color-scheme: light dark;
  --gap: 14px;
}}
* {{ box-sizing:border-box; }}
body {{
  font-family: system-ui,-apple-system,"Segoe UI","Yu Gothic UI",sans-serif;
  margin:0;
  background:Canvas;
  color:CanvasText;
}}
header {{
  position:sticky; top:0; z-index:10;
  background:Canvas; border-bottom:1px solid color-mix(in srgb, CanvasText 25%, transparent);
  padding:14px 20px;
}}
header h1 {{ margin:0 0 8px; font-size:22px; }}
.toolbar {{
  display:flex; gap:8px; flex-wrap:wrap; align-items:center;
}}
input[type=search] {{
  min-width:280px; flex:1; padding:9px 11px; font-size:15px;
}}
select, .toolbar button {{
  padding:9px 11px; font-size:14px;
}}
.secondary-actions {{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  align-items:center;
  flex-basis:100%;
  width:100%;
  padding:8px;
  border:1px dashed color-mix(in srgb, CanvasText 25%, transparent);
  border-radius:10px;
  background:color-mix(in srgb, CanvasText 3%, transparent);
}}
.secondary-actions button {{
  flex:0 0 auto;
}}
#secondaryActionsToggle[aria-expanded="true"] {{
  font-weight:700;
}}
main {{ padding:20px; width:100%; max-width:none; margin:0; }}
.summary {{
  padding:12px 14px; border:1px solid color-mix(in srgb, CanvasText 25%, transparent);
  border-radius:10px; margin-bottom:18px;
}}
.group-heading {{
  display:flex; align-items:baseline; gap:10px; margin-top:28px;
}}
.group-heading h2 {{ margin:0; }}
.group-heading span {{ opacity:.65; }}
.grid {{
  display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:var(--gap); margin-top:10px;
}}
.card {{
  border:1px solid color-mix(in srgb, CanvasText 25%, transparent);
  border-radius:12px; overflow:hidden; background:Canvas;
}}
.card[data-decision="keep"] {{ outline:3px solid #2d9b54; }}
.card[data-decision="delete"] {{ outline:3px solid #c94b4b; opacity:.72; }}
.card img, .noimg {{
  width:100%; aspect-ratio:16/9; object-fit:cover; display:block; background:#222;
}}
.noimg {{ display:grid; place-items:center; color:#ddd; }}
.body {{ padding:12px; }}
.topline {{ display:flex; gap:6px; flex-wrap:wrap; }}
.pill {{
  font-size:11px; padding:3px 7px; border-radius:999px;
  border:1px solid color-mix(in srgb, CanvasText 30%, transparent);
}}
.applied-applied {{ font-weight:800; }}
.applied-unknown {{ opacity:.65; }}
h3.vehicle {{ margin:10px 0 2px; font-size:19px; }}
h4 {{ margin:10px 0 4px; font-size:16px; }}
.vehicle-meta {{ font-size:12px; opacity:.78; margin-top:2px; }}
.asset {{ font-size:11px; opacity:.58; overflow-wrap:anywhere; }}
.counterbar {{
  display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; font-size:12px;
}}
.counter {{
  border:1px solid color-mix(in srgb, CanvasText 25%, transparent);
  border-radius:999px; padding:4px 9px;
}}
body.compact .grid {{ grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); }}
body.compact .card img, body.compact .noimg {{ aspect-ratio:2/1; }}
body.compact .body {{ padding:9px; }}
body.compact .desc {{ display:none; }}
body.compact details {{ display:none; }}
.desc {{ margin:0 0 10px; min-height:1.4em; opacity:.8; }}
dl {{
  display:grid; grid-template-columns:80px 1fr; gap:4px 8px;
  font-size:13px; margin:10px 0;
}}
dt {{ font-weight:700; }}
dd {{ margin:0; overflow-wrap:anywhere; }}
code {{ overflow-wrap:anywhere; }}
.decision {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin:12px 0; }}
.decision button {{ padding:8px 4px; cursor:pointer; }}
.decision button.active {{ font-weight:800; border-width:2px; }}
details {{ font-size:12px; margin-top:8px; }}
.hidden {{ display:none !important; }}
.small {{ font-size:12px; opacity:.72; }}
@media (max-width:600px) {{
  main {{ padding:12px; }}
  header {{ padding:10px 12px; }}
  .grid {{ grid-template-columns:1fr; }}
}}

:root {{
  --accent:#5b7cfa;
  --accent2:#8b5cf6;
  --good:#1f9d61;
  --bad:#d84a4a;
  --muted:#7b8497;
  --panel:color-mix(in srgb, Canvas 94%, CanvasText 6%);
  --line:color-mix(in srgb, CanvasText 16%, transparent);
}}
body {{
  background:
    radial-gradient(circle at 10% 0%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 32rem),
    radial-gradient(circle at 90% 0%, color-mix(in srgb, var(--accent2) 10%, transparent), transparent 30rem),
    Canvas;
}}
header {{ background:transparent; border:0; }}
.hero {{
  border:1px solid var(--line);
  border-radius:20px;
  padding:20px;
  background:color-mix(in srgb, Canvas 92%, transparent);
  box-shadow:0 14px 40px color-mix(in srgb, CanvasText 8%, transparent);
}}
.hero h1 {{ margin:0 0 5px; letter-spacing:-.02em; }}
.hero-sub {{ opacity:.72; }}
.stats-grid {{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
  gap:10px;
  margin-top:16px;
}}
.stat-card {{
  border:1px solid var(--line);
  border-radius:15px;
  padding:13px 14px;
  background:var(--panel);
}}
.stat-value {{ font-size:25px; font-weight:750; line-height:1.05; }}
.stat-label {{ font-size:11px; opacity:.65; margin-top:5px; }}
.toolbar {{
  position:sticky;
  top:8px;
  z-index:30;
  margin-top:12px;
  backdrop-filter:blur(18px);
  background:color-mix(in srgb, Canvas 82%, transparent);
  border:1px solid var(--line);
  box-shadow:0 8px 25px color-mix(in srgb, CanvasText 7%, transparent);
}}
.summary {{
  border:1px solid var(--line);
  border-radius:15px;
  background:var(--panel);
}}
.card {{
  border:1px solid var(--line);
  transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease;
  overflow:hidden;
}}
.card:hover {{
  transform:translateY(-2px);
  box-shadow:0 12px 28px color-mix(in srgb, CanvasText 10%, transparent);
}}
.card[data-decision="keep"] {{
  border-color:color-mix(in srgb, var(--good) 65%, var(--line));
  box-shadow:inset 4px 0 0 var(--good);
}}
.card[data-decision="delete"] {{
  border-color:color-mix(in srgb, var(--bad) 65%, var(--line));
  box-shadow:inset 4px 0 0 var(--bad);
}}
.card[data-decision="undecided"] {{
  box-shadow:inset 4px 0 0 color-mix(in srgb, var(--muted) 55%, transparent);
}}
.card img.livery-image {{
  cursor:zoom-in;
  transition:transform .2s ease;
}}
.card:hover img.livery-image {{ transform:scale(1.01); }}
.pill.strong {{
  background:color-mix(in srgb, var(--accent) 18%, Canvas);
  border-color:color-mix(in srgb, var(--accent) 42%, transparent);
}}
.pill.year {{ font-variant-numeric:tabular-nums; }}
.pill.vinyl {{
  background:color-mix(in srgb, var(--accent2) 13%, Canvas);
  border-color:color-mix(in srgb, var(--accent2) 28%, transparent);
  font-variant-numeric:tabular-nums;
}}
.group-heading {{ position:relative; padding-left:11px; }}
.group-count-badge {{
  display:inline-block;
  margin-left:8px;
  padding:3px 8px;
  border-radius:999px;
  font-size:11px;
  font-weight:650;
  background:color-mix(in srgb, var(--accent) 12%, Canvas);
  border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);
}}
.group-heading::before {{
  content:"";
  position:absolute; left:0; top:.25em; bottom:.25em; width:3px;
  border-radius:2px;
  background:linear-gradient(var(--accent),var(--accent2));
}}
.flat-sort-section {{
  margin-top:12px;
}}
body.flat-sort-mode #groupedSections,
body.flat-sort-mode #creatorGroupedSections {{
  display:none;
}}
body.flat-sort-mode #flatSortSection {{
  display:block !important;
}}
.creator-grouped-sections {{
  display:none;
}}
body.creator-sort-mode #groupedSections,
body.creator-sort-mode #flatSortSection {{
  display:none !important;
}}
body.creator-sort-mode #creatorGroupedSections {{
  display:block;
}}
.empty-state {{
  display:none; text-align:center; padding:45px 20px; opacity:.65;
}}
.empty-state.show {{ display:block; }}
.lightbox {{
  position:fixed; inset:0; z-index:1000; display:none;
  align-items:center; justify-content:center;
  background:rgba(0,0,0,.82); padding:3vw;
}}
.lightbox.open {{ display:flex; }}
.lightbox img {{
  max-width:94vw; max-height:90vh; object-fit:contain;
  border-radius:12px; box-shadow:0 24px 80px rgba(0,0,0,.55);
}}
.lightbox button {{
  position:absolute; top:18px; right:22px;
  font-size:28px; line-height:1; border:0; border-radius:999px;
  width:44px; height:44px; cursor:pointer;
  background:rgba(255,255,255,.15); color:white;
}}


@media (max-width: 900px) {{
  body {{
    margin: 0;
    padding: 0;
  }}

  header,
  main {{
    width: auto;
    max-width: none;
    margin: 0;
    padding-left: 12px;
    padding-right: 12px;
  }}

  .hero {{
    border-radius: 0 0 18px 18px;
    padding: 16px 14px;
    margin-left: -12px;
    margin-right: -12px;
  }}

  .hero h1 {{
    font-size: 24px;
    line-height: 1.15;
  }}

  .hero-sub {{
    font-size: 13px;
    line-height: 1.45;
  }}

  .stats-grid {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }}

  .stat-card {{
    padding: 10px 11px;
  }}

  .stat-value {{
    font-size: 21px;
  }}

  .toolbar {{
    position: static;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding: 10px;
    margin: 10px 0 12px;
    border-radius: 14px;
    backdrop-filter: none;
  }}

  .toolbar input,
  .toolbar select,
  .toolbar button {{
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    min-height: 42px;
    font-size: 14px;
  }}

  .toolbar input[type="search"],
  .toolbar .search,
  #q {{
    grid-column: 1 / -1;
  }}

  .secondary-actions {{
    grid-column:1 / -1;
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:8px;
    width:100%;
  }}
  .secondary-actions button {{
    width:100%;
  }}

  #clearFilters,
  #compactToggle,
  #exportCsv,
  #downloadExcel,
  #resetStates {{
    min-height: 40px;
  }}

  .summary {{
    padding: 10px 12px;
    font-size: 12px;
  }}

  .counterbar {{
    gap: 6px;
  }}

  .counter {{
    flex: 1 1 calc(50% - 6px);
    text-align: center;
    box-sizing: border-box;
  }}

  .group-heading {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    padding-left: 10px;
  }}

  .group-heading h2 {{
    font-size: 18px;
    line-height: 1.25;
    margin: 10px 0 8px;
  }}

  .group-count-badge {{
    flex: 0 0 auto;
    white-space: nowrap;
    font-size: 10px;
  }}

  .grid,
  body.compact .grid {{
    grid-template-columns: 1fr;
    gap: 12px;
  }}

  .card {{
    border-radius: 14px;
  }}

  .card img,
  .card img.livery-image,
  .noimg,
  body.compact .card img,
  body.compact .noimg {{
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
  }}

  .body,
  body.compact .body {{
    padding: 11px 12px 12px;
  }}

  .vehicle {{
    font-size: 17px;
    line-height: 1.3;
  }}

  .vehicle-meta {{
    font-size: 12px;
  }}

  .asset {{
    display: none;
  }}

  .topline {{
    gap: 5px;
  }}

  .pill {{
    font-size: 10px;
    padding: 3px 7px;
  }}

  .card h4 {{
    font-size: 15px;
    margin: 8px 0 5px;
  }}

  .desc {{
    font-size: 12px;
    line-height: 1.45;
  }}

  dl {{
    grid-template-columns: minmax(76px, auto) 1fr;
    gap: 5px 9px;
    font-size: 12px;
  }}

  .decision-row {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
  }}

  .decision-row button {{
    min-width: 0;
    width: 100%;
    padding: 9px 6px;
    font-size: 12px;
  }}

  .flat-sort-section {{
    margin-top: 6px;
  }}

  .lightbox {{
    padding: 10px;
  }}

  .lightbox img {{
    max-width: 100%;
    max-height: 85vh;
    border-radius: 8px;
  }}

  .lightbox button {{
    top: max(12px, env(safe-area-inset-top));
    right: 12px;
  }}
}}

@media (max-width: 540px) {{
  header,
  main {{
    padding-left: 8px;
    padding-right: 8px;
  }}

  .hero {{
    margin-left: -8px;
    margin-right: -8px;
    padding: 14px 10px;
  }}

  .hero h1 {{
    font-size: 21px;
  }}

  .stats-grid {{
    grid-template-columns: 1fr 1fr;
  }}

  .toolbar {{
    grid-template-columns: 1fr;
    padding: 8px;
  }}

  .toolbar input[type="search"],
  .toolbar .search,
  #q {{
    grid-column: auto;
  }}

  .counter {{
    flex-basis: 100%;
  }}

  .group-heading {{
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }}

  .group-heading h2 {{
    font-size: 17px;
    margin-bottom: 2px;
  }}

  .group-count-badge {{
    margin-left: 0;
    margin-bottom: 7px;
  }}

  .decision-row {{
    grid-template-columns: 1fr;
  }}

  .decision-row button {{
    font-size: 13px;
    min-height: 40px;
  }}
}}


.mobile-actions,
.mobile-stats-summary {{
  display:none;
}}

@media (max-width: 540px) {{
  .hero {{
    padding:10px 10px 9px;
    border-radius:0 0 14px 14px;
  }}

  .hero h1 {{
    font-size:20px;
    margin-bottom:2px;
  }}

  .hero-sub,
  .hero .stats-grid {{
    display:none;
  }}

  .mobile-stats-summary {{
    display:block;
    margin:6px 0 8px;
    padding:0 2px;
    font-size:12px;
    opacity:.75;
  }}

  .mobile-actions {{
    display:flex;
    align-items:center;
    gap:8px;
    margin:0 0 8px;
  }}

  #mobileFilterToggle {{
    flex:0 0 auto;
    min-height:38px;
    padding:8px 12px;
    border-radius:10px;
    font-size:13px;
    font-weight:650;
  }}

  #mobileFilterSummary {{
    flex:1 1 auto;
    min-width:0;
    font-size:11px;
    line-height:1.3;
    opacity:.7;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
  }}

  .toolbar {{
    display:none;
    grid-template-columns:1fr;
    position:static;
    margin:0 0 10px;
    padding:8px;
    border-radius:12px;
    box-shadow:none;
  }}

  .toolbar.mobile-open {{
    display:grid;
  }}

  .toolbar input,
  .toolbar select,
  .toolbar button {{
    min-height:40px;
  }}

  .summary {{
    margin:0 0 8px;
    padding:8px 10px;
  }}

  .summary .small {{
    display:none;
  }}

  .counterbar {{
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:5px;
  }}

  .counter {{
    padding:5px 6px;
    font-size:11px;
  }}

  main {{
    padding-top:0;
  }}
}}


.counter-filter,
.creator-chip,
.link-filter {{
  font:inherit;
  color:inherit;
  cursor:pointer;
}}
.counter-filter {{ background:transparent; }}
.counter-filter.active {{
  border-color:var(--accent);
  background:color-mix(in srgb, var(--accent) 13%, Canvas);
  font-weight:750;
}}
.creator-summary {{
  display:flex; gap:8px; align-items:flex-start; margin-top:9px;
}}

.filter-panel .creator-filter-summary {{
  grid-column:1 / -1;
  width:100%;
  margin:0;
  padding:9px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, Canvas 96%, CanvasText 4%);
}}

.filter-panel .creator-filter-summary .detail-filter-head {{
  margin-bottom:7px;
}}

.filter-panel .creator-filter-summary .creator-search-row {{
  margin-bottom:7px;
}}
.creator-summary-label {{
  flex:0 0 auto;
  font-size:12px;
  opacity:.7;
  padding-top:5px;
}}
.creator-summary-content {{
  min-width:0;
  flex:1 1 auto;
}}
.creator-top-list,
.creator-more-list {{
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  align-items:center;
}}
.creator-more-toggle {{
  display:inline-flex;
  align-items:center;
  min-height:28px;
  margin-top:7px;
  padding:3px 10px;
  border:1px solid var(--accent);
  border-radius:999px;
  background:color-mix(in srgb, var(--accent) 8%, Canvas);
  color:inherit;
  font:inherit;
  font-size:11px;
  font-weight:700;
  cursor:pointer;
}}
.creator-more-toggle:hover {{
  background:color-mix(in srgb, var(--accent) 14%, Canvas);
}}
.creator-more-list {{
  margin-top:7px;
}}
.creator-chip {{
  border:1px solid var(--line); border-radius:999px; padding:4px 8px;
  background:Canvas; font-size:11px;
}}
.creator-chip:hover, .link-filter:hover, .quick-filter:hover {{ text-decoration:underline; }}
.link-filter {{
  appearance:none;
  min-height:0;
  padding:0;
  border:0;
  border-radius:0;
  background:transparent;
  box-shadow:none;
  color:inherit;
  font:inherit;
  font-weight:inherit;
  line-height:inherit;
  text-align:left;
  vertical-align:baseline;
}}
.link-filter:hover:not(:disabled),
.link-filter:active:not(:disabled) {{
  transform:none;
  border-color:transparent;
  background:transparent;
  box-shadow:none;
}}
.title-filter {{
  display:inline; max-width:100%;
}}
.quick-filter {{ cursor:pointer; }}
.pill.similar {{
  border-color:color-mix(in srgb, #d97706 45%, transparent);
  background:color-mix(in srgb, #d97706 13%, Canvas);
}}
.pill.my-design-index {{
  display:none;
  min-width:4.6em;
  justify-content:center;
  border-color:color-mix(in srgb, var(--accent) 38%, transparent);
  background:color-mix(in srgb, var(--accent) 10%, Canvas);
  font-variant-numeric:tabular-nums;
  font-weight:850;
}}
body.my-design-sort-mode .pill.my-design-index {{
  display:inline-flex;
}}
.pill.vinyl-medium {{ font-weight:650; }}
.pill.vinyl-high {{ font-weight:750; border-width:2px; }}
.pill.vinyl-extreme {{
  font-weight:850; border-width:2px;
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent2) 12%, transparent);
}}
.mobile-bottom-nav {{ display:none; }}
@media (max-width:540px) {{
  body {{ padding-bottom:70px; }}
  .mobile-bottom-nav {{
    position:fixed; left:8px; right:8px;
    bottom:max(8px, env(safe-area-inset-bottom)); z-index:90;
    display:grid; grid-template-columns:repeat(4,1fr); gap:5px;
    padding:6px; border:1px solid var(--line); border-radius:15px;
    background:color-mix(in srgb, Canvas 92%, transparent);
    backdrop-filter:blur(18px);
    box-shadow:0 8px 30px color-mix(in srgb, CanvasText 16%, transparent);
  }}
  .mobile-bottom-nav button {{
    min-width:0; min-height:42px; padding:5px 2px;
    font-size:11px; border-radius:9px;
  }}
  .creator-summary {{
    display:block;
    overflow:visible;
    padding-bottom:3px;
  }}
  .creator-summary-label {{
    display:block;
    padding-top:0;
    margin-bottom:6px;
  }}
  .creator-top-list,
  .creator-more-list {{
    flex-wrap:wrap;
  }}
  .creator-chip {{ flex:0 0 auto; }}
}}


.card {{ content-visibility:auto; contain-intrinsic-size:420px 560px; }}
.car-group {{ content-visibility:auto; contain-intrinsic-size:600px 900px; }}
.select-box {{ display:inline-flex; align-items:center; }}
.card-select {{ width:18px; height:18px; cursor:pointer; }}
.flag-toggle {{ cursor:pointer; }}
.flag-toggle.active {{ font-weight:800; border-width:2px; }}
.personal-meta {{ margin:10px 0; border-top:1px dashed var(--line); padding-top:7px; }}
.personal-meta summary {{ cursor:pointer; font-size:12px; font-weight:700; }}
.personal-meta label {{ display:grid; gap:4px; margin-top:7px; font-size:11px; }}
.personal-meta input,.personal-meta textarea {{ width:100%; box-sizing:border-box; font:inherit; padding:7px 8px; }}
.progress-row {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:8px 0 4px; font-size:12px; }}
.progress-row progress {{ width:min(260px,50vw); }}
.modal {{ position:fixed; inset:0; z-index:150; background:rgba(0,0,0,.58); padding:18px; overflow:auto; }}
.modal-panel {{ max-width:1100px; margin:20px auto; background:Canvas; color:CanvasText; border-radius:16px; padding:14px; }}
.modal-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
.compare-panel {{ max-width:1180px; }}
.compare-summary {{ margin:3px 0 0; }}
.compare-actions {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; margin:10px 0 12px; }}
.compare-actions .compare-selection-count {{ margin-left:auto; }}
.compare-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
.compare-item,.detail-item {{ border:1px solid var(--line); border-radius:12px; overflow:hidden; padding:10px; }}
.compare-item {{ display:grid; gap:8px; align-content:start; }}
.compare-item.is-selected {{ outline:2px solid var(--accent); outline-offset:1px; }}
.compare-item img {{ width:100%; aspect-ratio:16/9; object-fit:cover; border-radius:8px; }}
.compare-badges {{ display:flex; flex-wrap:wrap; gap:5px; align-items:center; }}
.compare-badge {{ display:inline-flex; padding:3px 7px; border:1px solid var(--line); border-radius:999px; font-size:10px; font-weight:700; }}
.compare-badge.reason {{ border-color:color-mix(in srgb, var(--accent) 55%, var(--line)); }}
.compare-badge.newest {{ font-weight:850; }}
.compare-meta {{ display:grid; grid-template-columns:max-content 1fr; gap:3px 8px; margin:0; font-size:11px; }}
.compare-meta dt {{ font-weight:700; opacity:.78; }}
.compare-meta dd {{ margin:0; min-width:0; overflow-wrap:anywhere; }}
.compare-description {{ margin:0; font-size:11px; line-height:1.45; }}
.compare-item-actions {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:auto; }}
.detail-list {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }}
.card.keyboard-active {{ outline:3px solid var(--accent); outline-offset:2px; }}
body.dark-theme {{ color-scheme:dark; background:#111318; color:#f3f5f8; }}
body.dark-theme .toolbar,body.dark-theme .card,body.dark-theme .stat-card,body.dark-theme .summary,body.dark-theme .modal-panel {{ background:#171a20; color:#f3f5f8; border-color:#343945; }}
body.dark-theme input,body.dark-theme select,body.dark-theme button,body.dark-theme textarea {{ background:#1a1e25; color:#f3f5f8; border-color:#444b58; }}
@media (max-width:540px) {{
  .progress-row {{ display:grid; grid-template-columns:1fr 1fr; }}
  .progress-row progress {{ width:100%; grid-column:1/-1; }}
  .modal {{ padding:6px; }}
  .modal-panel {{ margin:4px auto; }}
}}


.keyboard-guide {{
  position:fixed; right:12px; bottom:12px; z-index:80;
  display:flex; gap:6px; flex-wrap:wrap; max-width:470px; justify-content:flex-end;
  pointer-events:none;
}}
.keyboard-guide span {{
  padding:4px 7px; border:1px solid var(--line); border-radius:999px;
  background:color-mix(in srgb, Canvas 92%, transparent);
  backdrop-filter:blur(10px); font-size:10px; opacity:.82;
}}
@media (max-width:540px) {{ .keyboard-guide {{ display:none; }} }}


.scan-baseline-row {{ justify-content:space-between; border-top:1px solid var(--line); padding-top:8px; }}
.runtime-error {{
  margin-top:8px;
  padding:8px 10px;
  border:1px solid #d84a4a;
  border-radius:9px;
  background:color-mix(in srgb, #d84a4a 12%, Canvas);
  font-size:12px;
  white-space:pre-wrap;
}}
#uiStatus[data-state="ok"] {{ font-weight:800; }}
#uiStatus[data-state="error"] {{ color:#d84a4a; font-weight:800; }}
#storageStatus {{ font-weight:700; }}


.creator-search-row {{
  display:flex;
  gap:7px;
  align-items:center;
  margin-bottom:7px;
}}
.creator-search-row input {{
  min-width:220px;
  max-width:420px;
  width:100%;
  padding:6px 9px;
  font:inherit;
  font-size:12px;
}}
.toolbar button.active {{
  border-color:var(--accent);
  background:color-mix(in srgb, var(--accent) 13%, Canvas);
  font-weight:750;
}}
.restore-preview-actions {{
  display:flex;
  flex-wrap:wrap;
  gap:8px;
  margin-top:14px;
}}
.history-list,.diagnostics-list {{
  display:grid;
  gap:7px;
}}
.history-row,.diagnostics-row {{
  display:flex;
  gap:10px;
  justify-content:space-between;
  align-items:flex-start;
  border:1px solid var(--line);
  border-radius:9px;
  padding:8px 10px;
}}
.diagnostics-ok {{ font-weight:800; }}
.diagnostics-ng {{ color:#d84a4a; font-weight:800; }}
.diagnostics-detail {{
  margin-top:10px;
  padding:9px 10px;
  border:1px solid var(--line);
  border-radius:11px;
  background:color-mix(in srgb, var(--surface) 94%, transparent);
}}
.diagnostics-detail summary {{ cursor:pointer; font-weight:750; }}
.diagnostics-issue-list {{ margin:8px 0 0; padding-left:1.35em; font-size:11px; line-height:1.55; }}
.diagnostics-issue-list code {{ font-size:10.5px; }}

/* =======================================================================
   v0.4.39 — 利用準備と復旧導線
   ======================================================================= */
.startup-readiness-card {{
  grid-column:1 / -1;
  min-width:0;
  padding:10px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, Canvas 97%, CanvasText 3%);
}}
.startup-readiness-head {{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-bottom:7px;
}}
.startup-readiness-head b {{ font-size:12px; }}
.startup-readiness-status {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:76px;
  padding:4px 8px;
  border:1px solid var(--line);
  border-radius:999px;
  font-size:10.5px;
  font-weight:850;
  white-space:nowrap;
}}
.startup-readiness-card[data-state="ok"] {{
  border-color:color-mix(in srgb, var(--good) 34%, var(--line));
  background:color-mix(in srgb, var(--good-soft) 48%, var(--surface));
}}
.startup-readiness-card[data-state="ok"] .startup-readiness-status {{
  border-color:color-mix(in srgb, var(--good) 46%, var(--line));
  background:var(--good-soft);
}}
.startup-readiness-card[data-state="warning"] {{
  border-color:color-mix(in srgb, #d97706 36%, var(--line));
  background:color-mix(in srgb, #d97706 6%, var(--surface));
}}
.startup-readiness-card[data-state="warning"] .startup-readiness-status {{
  border-color:color-mix(in srgb, #d97706 48%, var(--line));
  background:color-mix(in srgb, #d97706 11%, Canvas);
}}
.startup-readiness-card[data-state="error"] {{
  border-color:color-mix(in srgb, var(--bad) 42%, var(--line));
  background:var(--bad-soft);
}}
.startup-readiness-card[data-state="error"] .startup-readiness-status {{
  border-color:color-mix(in srgb, var(--bad) 50%, var(--line));
  background:var(--bad-soft);
}}
.startup-readiness-items {{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:6px;
}}
.startup-readiness-item {{
  min-width:0;
  padding:7px 8px;
  border:1px solid var(--line);
  border-radius:9px;
  background:color-mix(in srgb, var(--surface) 94%, transparent);
  font-size:10.5px;
}}
.startup-readiness-item span {{ display:block; color:var(--muted); margin-bottom:2px; }}
.startup-readiness-item b {{ display:block; overflow-wrap:anywhere; }}
.startup-readiness-foot {{
  display:flex;
  align-items:center;
  gap:8px;
  margin-top:7px;
}}
.startup-readiness-foot .small {{ flex:1 1 auto; min-width:0; line-height:1.45; }}
.startup-readiness-actions {{ display:flex; flex:0 0 auto; gap:6px; }}
.startup-readiness-actions button {{ min-height:30px; padding:5px 8px; font-size:10.5px; }}
#runtimeErrorBanner {{
  align-items:center;
  justify-content:space-between;
  gap:8px;
}}
#runtimeErrorBanner:not(.hidden) {{ display:flex; }}
#runtimeErrorMessage {{ flex:1 1 auto; min-width:0; overflow-wrap:anywhere; }}
#runtimeDiagnosticsAction {{ flex:0 0 auto; min-height:30px; padding:5px 8px; font-size:10.5px; }}
body.dark-theme .startup-readiness-card {{ background:var(--surface); }}
@media (max-width:620px) {{
  .startup-readiness-items {{ grid-template-columns:1fr; }}
  .startup-readiness-foot {{ display:block; }}
  .startup-readiness-actions {{ margin-top:7px; }}
}}

@media (max-width:540px) {{
  .creator-search-row {{ display:block; }}
  .creator-search-row input {{ max-width:none; }}
}}


/* =======================================================================
   v0.4.0 — モダンUI調整
   ======================================================================= */
:root {{
  --accent:#5873f6;
  --accent-strong:#405de6;
  --accent-soft:color-mix(in srgb, var(--accent) 11%, Canvas);
  --accent2:#8a63e8;
  --good:#249b64;
  --good-soft:color-mix(in srgb, var(--good) 10%, Canvas);
  --bad:#d65353;
  --bad-soft:color-mix(in srgb, var(--bad) 9%, Canvas);
  --surface:color-mix(in srgb, Canvas 96%, CanvasText 4%);
  --surface-elevated:color-mix(in srgb, Canvas 98%, CanvasText 2%);
  --control-bg:color-mix(in srgb, Canvas 97%, CanvasText 3%);
  --control-hover:color-mix(in srgb, Canvas 93%, var(--accent) 7%);
  --line:color-mix(in srgb, CanvasText 13%, transparent);
  --line-strong:color-mix(in srgb, CanvasText 21%, transparent);
  --shadow-xs:0 1px 2px color-mix(in srgb, CanvasText 7%, transparent);
  --shadow-sm:0 4px 14px color-mix(in srgb, CanvasText 7%, transparent);
  --shadow-md:0 12px 34px color-mix(in srgb, CanvasText 10%, transparent);
  --shadow-lg:0 24px 70px color-mix(in srgb, CanvasText 15%, transparent);
  --radius-control:11px;
  --radius-panel:18px;
  --radius-card:20px;
}}

html {{ scroll-behavior:smooth; }}

body {{
  letter-spacing:.005em;
  background:
    radial-gradient(circle at 8% -5%, color-mix(in srgb, var(--accent) 13%, transparent), transparent 34rem),
    radial-gradient(circle at 92% 0%, color-mix(in srgb, var(--accent2) 10%, transparent), transparent 31rem),
    Canvas;
}}

header {{ padding-top:16px; }}

.hero {{
  border-radius:24px;
  border:1px solid var(--line);
  background:color-mix(in srgb, Canvas 91%, transparent);
  box-shadow:var(--shadow-md);
  backdrop-filter:blur(16px);
}}

.hero h1 {{
  font-weight:780;
  letter-spacing:-.035em;
}}

.hero-sub {{ opacity:.66; }}

.stat-card {{
  border-radius:17px;
  border:1px solid var(--line);
  background:var(--surface-elevated);
  box-shadow:var(--shadow-xs);
  transition:transform .16s ease, border-color .16s ease, box-shadow .16s ease;
}}

.stat-card:hover {{
  transform:translateY(-1px);
  border-color:color-mix(in srgb, var(--accent) 24%, var(--line));
  box-shadow:var(--shadow-sm);
}}

.toolbar {{
  gap:7px;
  padding:10px;
  border-radius:19px;
  border:1px solid var(--line);
  background:color-mix(in srgb, Canvas 84%, transparent);
  box-shadow:var(--shadow-sm);
}}

button,
select,
input[type="search"],
input[type="text"],
input[type="number"],
input:not([type]),
textarea {{
  font:inherit;
  border:1px solid var(--line-strong);
  border-radius:var(--radius-control);
  background:var(--control-bg);
  color:CanvasText;
  box-shadow:var(--shadow-xs);
  transition:
    background .14s ease,
    border-color .14s ease,
    box-shadow .14s ease,
    transform .14s ease,
    opacity .14s ease;
}}

button {{
  min-height:38px;
  padding:8px 12px;
  font-weight:650;
  line-height:1.15;
  cursor:pointer;
}}

.toolbar button {{
  padding:8px 12px;
  border-radius:11px;
}}

select {{
  min-height:38px;
  padding:7px 31px 7px 11px;
}}

input[type="search"],
input[type="text"],
input[type="number"],
input:not([type]),
textarea {{
  padding:9px 12px;
}}

button:hover:not(:disabled),
select:hover,
input[type="search"]:hover,
input[type="text"]:hover,
input[type="number"]:hover,
input:not([type]):hover,
textarea:hover {{
  border-color:color-mix(in srgb, var(--accent) 40%, var(--line-strong));
  background:var(--control-hover);
  box-shadow:0 5px 15px color-mix(in srgb, CanvasText 8%, transparent);
}}

button:hover:not(:disabled) {{ transform:translateY(-1px); }}
button:active:not(:disabled) {{
  transform:translateY(0);
  box-shadow:var(--shadow-xs);
}}

button:disabled {{
  cursor:not-allowed;
  opacity:.46;
  box-shadow:none;
}}

button:focus-visible,
select:focus-visible,
input:focus-visible,
textarea:focus-visible,
summary:focus-visible {{
  outline:3px solid color-mix(in srgb, var(--accent) 28%, transparent);
  outline-offset:2px;
  border-color:var(--accent);
}}

.toolbar button.active,
.decision button.active,
.flag-toggle.active {{
  border-color:color-mix(in srgb, var(--accent) 62%, transparent);
  background:linear-gradient(
    180deg,
    color-mix(in srgb, var(--accent) 17%, Canvas),
    color-mix(in srgb, var(--accent) 10%, Canvas)
  );
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent) 12%, transparent),
    var(--shadow-xs);
}}

#bulkKeep {{
  border-color:color-mix(in srgb, var(--good) 30%, var(--line));
}}
#bulkKeep:hover:not(:disabled) {{
  background:var(--good-soft);
  border-color:color-mix(in srgb, var(--good) 58%, var(--line));
}}

#bulkDelete,
#resetStates {{
  border-color:color-mix(in srgb, var(--bad) 28%, var(--line));
}}
#bulkDelete:hover:not(:disabled),
#resetStates:hover:not(:disabled) {{
  background:var(--bad-soft);
  border-color:color-mix(in srgb, var(--bad) 58%, var(--line));
}}

#downloadExcel {{
  border-color:color-mix(in srgb, var(--good) 24%, var(--line));
}}

.secondary-actions-trigger {{
  margin-inline-start:13px;
  position:relative;
}}

.secondary-actions-trigger::before {{
  content:"";
  position:absolute;
  left:-11px;
  top:7px;
  bottom:7px;
  width:1px;
  background:var(--line-strong);
  pointer-events:none;
}}

#secondaryActionsToggle[aria-expanded="true"] {{
  font-weight:700;
  border-color:color-mix(in srgb, var(--accent) 45%, var(--line));
  background:var(--accent-soft);
}}

.secondary-actions {{
  flex-basis:100%;
  width:100%;
  margin-top:2px;
  padding:10px;
  gap:7px;
  border:1px solid var(--line);
  border-radius:15px;
  background:color-mix(in srgb, Canvas 93%, CanvasText 7%);
  box-shadow:inset 0 1px 0 color-mix(in srgb, Canvas 80%, transparent);
}}

.summary {{
  border-radius:var(--radius-panel);
  padding:14px 16px;
  background:var(--surface);
  box-shadow:var(--shadow-xs);
}}

.group-heading {{ padding-left:13px; }}
.group-heading::before {{
  width:4px;
  border-radius:999px;
}}
.group-heading h2 {{ letter-spacing:-.02em; }}

.card {{
  border-radius:var(--radius-card);
  border:1px solid var(--line);
  background:var(--surface-elevated);
  box-shadow:var(--shadow-xs);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}}

.card:hover {{
  transform:translateY(-3px);
  border-color:color-mix(in srgb, var(--accent) 20%, var(--line));
  box-shadow:var(--shadow-md);
}}

.card img,
.card img.livery-image,
.noimg {{
  border-radius:19px 19px 0 0;
}}

.body {{ padding:14px; }}

.pill,
.counter,
.group-count-badge {{
  border-color:var(--line);
  box-shadow:0 1px 0 color-mix(in srgb, Canvas 80%, transparent);
}}

.pill {{ padding:4px 8px; }}

.counter {{
  background:color-mix(in srgb, Canvas 95%, CanvasText 5%);
}}

.decision {{ gap:7px; }}
.decision button,
.decision-row button {{ border-radius:10px; }}

.personal-meta {{
  margin-top:12px;
  padding-top:10px;
  border-top:1px solid var(--line);
}}

.personal-meta summary {{
  padding:4px 1px;
  border-radius:8px;
}}

.compare-item,
.detail-item {{
  border-radius:16px;
  border-color:var(--line);
  background:var(--surface);
  box-shadow:var(--shadow-xs);
}}

.modal {{
  background:color-mix(in srgb, #080b12 68%, transparent);
  backdrop-filter:blur(7px);
}}

.modal-panel {{
  border:1px solid var(--line);
  border-radius:22px;
  padding:18px;
  background:var(--surface-elevated);
  box-shadow:var(--shadow-lg);
}}

.modal-head {{
  padding-bottom:8px;
  margin-bottom:8px;
  border-bottom:1px solid var(--line);
}}

.history-row,
.diagnostics-row {{
  border-radius:13px;
  background:var(--surface);
}}

.creator-chip {{ border-radius:999px !important; }}
.runtime-error {{ border-radius:13px; }}
.lightbox img {{ border-radius:18px; }}
.mobile-actions button,
.mobile-bottom-nav button {{ border-radius:12px; }}

body.dark-theme {{
  --surface:#171b22;
  --surface-elevated:#1b2028;
  --control-bg:#1d222b;
  --control-hover:#232a36;
  --line:#323946;
  --line-strong:#414a59;
  --shadow-xs:0 1px 2px rgba(0,0,0,.22);
  --shadow-sm:0 5px 16px rgba(0,0,0,.24);
  --shadow-md:0 14px 36px rgba(0,0,0,.32);
  --shadow-lg:0 28px 78px rgba(0,0,0,.46);
}}

body.dark-theme .toolbar,
body.dark-theme .card,
body.dark-theme .stat-card,
body.dark-theme .summary,
body.dark-theme .modal-panel {{
  background:var(--surface-elevated);
  border-color:var(--line);
}}

body.dark-theme button,
body.dark-theme select,
body.dark-theme input,
body.dark-theme textarea {{
  background:var(--control-bg);
  border-color:var(--line-strong);
}}

body.dark-theme button:hover:not(:disabled),
body.dark-theme select:hover,
body.dark-theme input:hover,
body.dark-theme textarea:hover {{
  background:var(--control-hover);
}}

@media (max-width:900px) {{
  .toolbar {{
    border-radius:16px;
    gap:8px;
  }}

  .secondary-actions-trigger {{
    margin-inline-start:0;
  }}

  .secondary-actions-trigger::before {{
    display:none;
  }}

  .secondary-actions {{
    grid-column:1 / -1;
    margin-top:0;
    border-radius:14px;
  }}

  button,
  select,
  input[type="search"],
  input[type="text"],
  input:not([type]),
  textarea {{
    border-radius:11px;
  }}

  .card {{ border-radius:17px; }}

  .card img,
  .card img.livery-image,
  .noimg {{
    border-radius:16px 16px 0 0;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *,
  *::before,
  *::after {{
    scroll-behavior:auto !important;
    transition:none !important;
  }}
}}


/* =======================================================================
   v0.4.0 — ヘルプ / フッター調整
   ======================================================================= */
.app-footer {{ display:none; }}
.footer-separator {{ display:none; }}

.help-panel {{
  max-width:1040px;
}}

.help-intro {{
  margin:12px 0 12px;
  padding:14px 16px;
  border:1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
  border-radius:15px;
  background:color-mix(in srgb, var(--accent) 7%, var(--surface));
  line-height:1.75;
}}

.help-quick-start {{
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:8px;
  margin:0 0 14px;
}}

.help-step {{
  min-width:0;
  padding:10px 11px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, var(--surface) 93%, transparent);
}}

.help-step-number {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:22px;
  height:22px;
  margin-right:5px;
  border-radius:999px;
  background:var(--accent-soft);
  color:var(--accent);
  font-size:11px;
  font-weight:900;
}}

.help-step b {{
  font-size:12px;
}}

.help-step p {{
  margin:6px 0 0;
  color:var(--muted);
  font-size:11px;
  line-height:1.55;
}}

.help-grid {{
  display:grid;
  grid-template-columns:repeat(2, minmax(0, 1fr));
  gap:12px;
}}

.help-section {{
  min-width:0;
  padding:15px 16px;
  border:1px solid var(--line);
  border-radius:16px;
  background:var(--surface);
  box-shadow:var(--shadow-xs);
}}

.help-section h4 {{
  margin:0 0 9px;
  font-size:15px;
  letter-spacing:-.015em;
}}

.help-section p {{
  margin:7px 0 0;
  line-height:1.72;
}}

.help-section ol,
.help-section ul {{
  margin:8px 0 0;
  padding-left:1.4em;
  line-height:1.75;
}}

.help-section li + li {{
  margin-top:4px;
}}

.help-path {{
  display:inline-flex;
  align-items:center;
  max-width:100%;
  margin:2px 0;
  padding:3px 7px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--control-bg);
  font-size:11px;
  font-weight:750;
  overflow-wrap:anywhere;
}}

.help-tip {{
  margin-top:9px;
  padding:8px 10px;
  border-left:3px solid var(--accent);
  border-radius:8px;
  background:color-mix(in srgb, var(--accent-soft) 50%, transparent);
  font-size:11px;
  line-height:1.65;
}}

.help-warning {{
  border-left-color:var(--bad);
  background:color-mix(in srgb, var(--bad-soft) 55%, transparent);
}}

.help-mini-table {{
  width:100%;
  margin-top:8px;
  border-collapse:collapse;
  font-size:11px;
}}

.help-mini-table th,
.help-mini-table td {{
  padding:6px 7px;
  border:1px solid var(--line);
  text-align:left;
  vertical-align:top;
}}

.help-mini-table th {{
  background:color-mix(in srgb, var(--surface) 82%, var(--accent-soft));
  white-space:nowrap;
}}

.help-section-wide {{
  grid-column:1 / -1;
}}

.help-safety {{
  border-color:color-mix(in srgb, var(--good) 28%, var(--line));
  background:color-mix(in srgb, var(--good) 5%, var(--surface));
}}

.help-shortcuts {{
  display:grid;
  grid-template-columns:repeat(2, minmax(0, 1fr));
  gap:9px 14px;
}}

.help-shortcuts span {{
  display:flex;
  align-items:center;
  gap:7px;
  min-width:0;
}}

kbd {{
  display:inline-flex;
  min-width:28px;
  min-height:26px;
  align-items:center;
  justify-content:center;
  padding:3px 7px;
  border:1px solid var(--line-strong);
  border-bottom-width:2px;
  border-radius:7px;
  background:var(--control-bg);
  box-shadow:var(--shadow-xs);
  font:600 12px/1 system-ui,-apple-system,"Segoe UI",sans-serif;
  white-space:nowrap;
}}

#helpAction {{
  border-color:color-mix(in srgb, var(--accent) 26%, var(--line));
}}

#helpAction:hover {{
  background:var(--accent-soft);
}}

@media (max-width:760px) {{
  .help-quick-start {{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }}

  .help-grid {{
    grid-template-columns:1fr;
  }}

  .help-section-wide {{
    grid-column:auto;
  }}

  .help-shortcuts {{
    grid-template-columns:1fr;
  }}

}}

@media (max-width:460px) {{
  .help-quick-start {{
    grid-template-columns:1fr;
  }}

  .help-mini-table {{
    font-size:10.5px;
  }}
}}


/* =======================================================================
   v0.4.0 — 著作権表示固定 + ヘルプ配置
   ======================================================================= */
.keyboard-guide {{
  right:12px;
  bottom:12px;
  max-width:none;
  flex-wrap:nowrap;
  align-items:center;
}}

.keyboard-guide .keyboard-copyright {{
  margin-right:3px;
  padding-inline:9px;
  border-color:color-mix(in srgb, var(--accent) 18%, var(--line));
  background:color-mix(in srgb, Canvas 88%, var(--accent) 5%);
  color:inherit;
  font-weight:650;
  letter-spacing:.02em;
  opacity:.76;
  pointer-events:auto;
  text-decoration:none;
}}

.keyboard-guide .keyboard-copyright:hover {{
  text-decoration:underline;
}}

#helpAction.help-action {{
  margin-inline-start:0;
}}

@media (min-width:901px) {{
  #secondaryActionsToggle + #helpAction {{
    margin-inline-start:0;
  }}
}}

@media (max-width:540px) {{
  .keyboard-guide {{
    display:flex;
    right:10px;
    bottom:calc(max(8px, env(safe-area-inset-bottom)) + 60px);
    z-index:91;
    pointer-events:none;
  }}

  .keyboard-guide span:not(.keyboard-copyright) {{
    display:none;
  }}

  .keyboard-guide .keyboard-copyright {{
    display:inline-flex;
    padding:5px 9px;
    border-radius:999px;
    background:color-mix(in srgb, Canvas 90%, transparent);
    backdrop-filter:blur(12px);
    box-shadow:var(--shadow-sm);
    opacity:.8;
  }}
}}


/* =======================================================================
   v0.4.0 — コンパクトなペイントカード
   ======================================================================= */
.card-vehicle-sort-only {{
  display:none !important;
}}

body.flat-sort-mode .card-vehicle-sort-only,
body.creator-sort-mode .card-vehicle-sort-only {{
  display:block !important;
  margin:4px 0 3px;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-size:13.5px;
  line-height:1.25;
  font-weight:750;
  letter-spacing:-.01em;
}}

body.compact.flat-sort-mode .card-vehicle-sort-only,
body.compact.creator-sort-mode .card-vehicle-sort-only {{
  margin:3px 0 2px;
  font-size:12.5px;
}}

.grid {{
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:12px;
}}

.card img,
.card img.livery-image,
.noimg {{
  aspect-ratio:2.15 / 1;
}}

.body {{
  padding:8px 10px 9px;
}}

.topline {{
  gap:5px;
  align-items:center;
  margin-bottom:5px;
}}

.topline .pill {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:3px 7px;
  font-size:10.5px;
  min-height:28px;
}}

.select-box {{
  min-height:28px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
}}

.card-select {{
  width:17px;
  height:17px;
}}

.vehicle-meta {{
  margin-top:0;
  font-size:11.5px;
  line-height:1.25;
}}

.asset {{
  margin-top:1px;
  font-size:10.5px;
  line-height:1.2;
}}

.card h4 {{
  margin:5px 0 1px;
  font-size:15px;
  line-height:1.2;
}}

.card .desc {{
  display:-webkit-box;
  -webkit-box-orient:vertical;
  -webkit-line-clamp:1;
  overflow:hidden;
  margin:0 0 5px;
  min-height:0;
  max-height:1.4em;
  font-size:12px;
  line-height:1.35;
}}

.card dl {{
  grid-template-columns:68px minmax(0,1fr);
  gap:1px 7px;
  margin:5px 0 3px;
  font-size:12px;
  line-height:1.3;
}}

.card dt,
.card dd {{
  min-height:16px;
}}

.card .personal-meta {{
  margin-top:4px;
  padding-top:4px;
}}

.card .personal-meta summary {{
  padding:1px;
  font-size:11.5px;
  line-height:1.25;
}}

.card .personal-meta[open] {{
  padding-bottom:2px;
}}

.card .personal-meta label {{
  margin-top:4px;
}}

.card .personal-meta input,
.card .personal-meta textarea {{
  padding:6px 8px;
  min-height:31px;
  font-size:12px;
}}

.card .personal-meta textarea {{
  min-height:46px;
}}

.card .decision {{
  gap:6px;
  margin:5px 0 0;
}}

.card .decision button {{
  min-height:33px;
  padding:4px 3px;
  font-size:13.5px;
}}

body.compact .grid {{
  grid-template-columns:repeat(auto-fill,minmax(225px,1fr));
  gap:10px;
}}

body.compact .card img,
body.compact .card img.livery-image,
body.compact .noimg {{
  aspect-ratio:2.45 / 1;
}}

body.compact .body {{
  padding:6px 8px 7px;
}}

body.compact .topline {{
  margin-bottom:3px;
}}

body.compact .vehicle-meta,
body.compact .asset {{
  line-height:1.15;
}}

body.compact .card h4 {{
  margin-top:3px;
}}

body.compact .card dl {{
  margin:3px 0 2px;
  gap:1px 6px;
  font-size:11.5px;
}}

body.compact .decision {{
  margin-top:3px;
}}

body.compact .decision button {{
  min-height:30px;
  font-size:12.5px;
}}

@media (max-width:600px) {{
  .grid {{
    gap:10px;
  }}

  .card img,
  .card img.livery-image,
  .noimg {{
    aspect-ratio:2.08 / 1;
  }}

  .body {{
    padding:7px 9px 8px;
  }}

  .topline {{
    margin-bottom:4px;
  }}

  .card h4 {{
    margin-top:4px;
  }}

  .card .decision button {{
    min-height:34px;
  }}
}}


/* =======================================================================
   v0.4.0 — カード優先デスクトップUI
   ======================================================================= */
header {{
  padding:7px 12px 5px;
}}

.card-first-hero {{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:8px 16px;
  min-height:58px;
  padding:8px 12px;
  margin:0;
  border-radius:14px;
  overflow:visible;
}}

.hero-brand {{
  flex:0 0 auto;
  min-width:max-content;
  max-width:100%;
}}

.card-first-hero h1 {{
  display:flex;
  align-items:center;
  gap:8px;
  margin:0;
  font-size:25.5px;
  line-height:1.1;
  letter-spacing:-.025em;
  white-space:nowrap;
}}

.card-first-hero h1 .pill {{
  padding:4px 9px;
  font-size:15px;
}}

.card-first-hero .hero-sub {{
  display:none;
}}

.card-first-hero .stats-grid {{
  flex:1 1 720px;
  min-width:0;
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:5px 4px;
  margin:0;
  overflow:visible;
}}

.card-first-hero .stat-card {{
  flex:0 0 auto;
  display:flex;
  align-items:baseline;
  gap:5px;
  min-width:0;
  padding:6px 10px;
  border-radius:999px;
  box-shadow:none;
  white-space:nowrap;
}}

.card-first-hero .stat-card:hover {{
  transform:none;
  box-shadow:none;
}}

.card-first-hero .stat-value {{
  font-size:19.5px;
  line-height:1;
  font-weight:800;
}}

.card-first-hero .stat-label {{
  margin:0;
  font-size:14px;
  line-height:1;
  opacity:.62;
}}

.card-first-toolbar {{
  position:sticky;
  top:6px;
  z-index:80;
  display:flex;
  flex-wrap:nowrap;
  align-items:center;
  gap:6px;
  min-height:46px;
  margin:6px 0 0;
  padding:5px 7px;
  border-radius:13px;
}}

.card-first-toolbar > #q {{
  flex:1 1 520px;
  min-width:260px;
}}

.card-first-toolbar > #sortOrder {{
  flex:0 0 184px;
  width:184px;
}}

.card-first-toolbar > button {{
  flex:0 0 auto;
  min-height:36px;
  padding:7px 10px;
  white-space:nowrap;
}}

#filterPanelToggle[aria-expanded="true"],
#secondaryActionsToggle[aria-expanded="true"] {{
  border-color:color-mix(in srgb, var(--accent) 48%, var(--line));
  background:var(--accent-soft);
}}

.filter-panel,
.secondary-actions,
.report-info-panel {{
  position:absolute;
  top:calc(100% + 7px);
  z-index:90;
  max-height:min(68vh,620px);
  overflow:auto;
  padding:10px;
  border:1px solid var(--line);
  border-radius:16px;
  background:color-mix(in srgb, Canvas 94%, transparent);
  box-shadow:var(--shadow-lg);
  backdrop-filter:blur(18px);
}}

.filter-panel {{
  left:0;
  right:0;
  width:auto;
  display:grid;
  grid-template-columns:repeat(4,minmax(150px,1fr));
  gap:7px;
}}

.filter-panel > * {{
  min-width:0;
  width:100%;
  box-sizing:border-box;
}}

.filter-panel #tagFilter,
.filter-panel #paintCountFilter,
.filter-panel #vinylCountFilter {{
  min-width:0;
}}

.filter-panel #bulkTag {{
  grid-column:auto;
}}

.filter-multi-note {{
  grid-column:1 / -1;
  padding:5px 8px;
  border:1px dashed var(--line);
  border-radius:9px;
  background:color-mix(in srgb, var(--accent-soft) 26%, transparent);
  color:var(--muted);
  font-size:10.5px;
  line-height:1.35;
}}

.detail-filter-source {{
  display:none !important;
}}

.detail-filter-card,
.range-filter-card,
.filter-preset-card {{
  min-width:0;
  padding:8px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, var(--surface) 88%, transparent);
}}

.detail-filter-head,
.range-filter-head {{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  margin-bottom:6px;
}}

.detail-filter-head b,
.range-filter-head b {{
  font-size:12px;
}}

.detail-filter-count {{
  color:var(--muted);
  font-size:10px;
  font-weight:700;
  white-space:nowrap;
}}

.detail-filter-quick-trigger {{
  width:100%;
  min-height:34px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding:6px 9px;
  border-radius:9px;
  text-align:left;
  font-size:11.5px;
}}

.detail-filter-quick-trigger.active,
.detail-filter-quick-trigger[aria-expanded="true"] {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line));
  background:var(--accent-soft);
}}

.paint-count-quick-note {{
  display:block;
  margin-top:6px;
  color:var(--muted);
}}

.detail-filter-search,
.stat-quick-filter-search {{
  width:100%;
  min-height:32px;
  margin-bottom:6px;
  padding:6px 8px;
  border-radius:9px;
  font-size:11.5px;
}}

.detail-filter-actions,
.stat-quick-filter-actions {{
  display:flex;
  flex-wrap:wrap;
  gap:4px;
  margin-bottom:6px;
}}

.detail-filter-actions button,
.stat-quick-filter-actions button {{
  min-height:28px;
  padding:4px 7px;
  border-radius:8px;
  font-size:10.5px;
  font-weight:700;
}}

.detail-filter-choices {{
  display:grid;
  grid-template-columns:1fr;
  gap:4px;
  max-height:178px;
  overflow:auto;
  padding:1px;
}}

.detail-filter-choice {{
  min-height:31px;
  width:100%;
  padding:5px 7px;
  border-radius:8px;
  text-align:left;
  font-size:11px;
  font-weight:650;
  display:flex;
  align-items:center;
  gap:6px;
}}

.detail-filter-choice::before {{
  content:"□";
  flex:0 0 auto;
  color:var(--muted);
  font-size:13px;
}}

.detail-filter-choice.active::before {{
  content:"✓";
  color:var(--accent);
  font-weight:900;
}}

.detail-filter-choice.active {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line));
  background:var(--accent-soft);
}}

.detail-filter-choice.hidden-choice,
.stat-quick-choice.hidden-choice {{
  display:none;
}}

.range-filter-inputs {{
  display:grid;
  grid-template-columns:1fr auto 1fr;
  gap:6px;
  align-items:center;
}}

.range-filter-inputs input {{
  min-width:0;
  width:100%;
  min-height:38px;
  box-sizing:border-box;
}}

.tag-match-mode {{
  display:flex;
  gap:4px;
  margin:0 0 6px;
}}

.tag-match-mode button {{
  flex:1 1 0;
  min-height:28px;
  padding:4px 6px;
  font-size:10px;
}}

.tag-match-mode button.active {{
  border-color:var(--accent);
  background:var(--accent-soft);
}}

.filter-preset-card {{
  grid-column:1 / -1;
  display:grid;
  grid-template-columns:minmax(140px,1fr) auto minmax(150px,1fr) auto auto;
  gap:6px;
  align-items:center;
}}

.filter-preset-card input,
.filter-preset-card select {{
  min-width:0;
  width:100%;
}}

.active-filter-chips {{
  display:flex;
  flex-wrap:wrap;
  gap:5px;
  padding:0 2px 5px;
}}

.active-filter-chips:empty {{
  display:none;
}}

.active-filter-chip {{
  display:inline-flex;
  align-items:center;
  gap:5px;
  max-width:min(340px,100%);
  min-height:27px;
  padding:4px 7px 4px 9px;
  border:1px solid color-mix(in srgb, var(--accent) 38%, var(--line));
  border-radius:999px;
  background:color-mix(in srgb, var(--accent-soft) 70%, var(--surface));
  font-size:10.5px;
  font-weight:700;
}}

.active-filter-chip span {{
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}

.active-filter-chip button {{
  min-height:20px;
  min-width:20px;
  padding:0;
  border:0;
  border-radius:999px;
  background:transparent;
  font-size:14px;
  line-height:1;
}}

.active-filter-chip button:hover {{
  background:color-mix(in srgb, var(--accent) 12%, transparent);
}}

@media (max-width:760px) {{
  .filter-preset-card {{
    grid-template-columns:1fr 1fr;
  }}
  .filter-preset-card input,
  .filter-preset-card select {{
    grid-column:1 / -1;
  }}
}}

.secondary-actions {{
  right:0;
  width:min(820px,calc(100vw - 28px));
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:10px;
  align-items:start;
  align-content:start;
  flex-basis:auto;
}}

.secondary-action-group {{
  min-width:0;
  padding:9px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, Canvas 96%, CanvasText 4%);
}}

.secondary-action-group h4 {{
  margin:0 0 7px;
  padding:0 2px 6px;
  border-bottom:1px solid var(--line);
  font-size:12px;
  line-height:1.2;
  color:var(--muted);
}}

.secondary-action-group-actions {{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:6px;
}}

.secondary-actions button {{
  width:100%;
  min-width:0;
}}

.secondary-action-maintenance #resetStates {{
  grid-column:1 / -1;
  border-color:color-mix(in srgb, var(--bad) 34%, var(--line));
}}

@media (max-width:680px) {{
  .secondary-actions {{
    grid-template-columns:1fr;
    width:min(520px,calc(100vw - 20px));
  }}
}}

@media (max-width:420px) {{
  .secondary-action-group-actions {{
    grid-template-columns:1fr;
  }}
  .secondary-action-maintenance #resetStates {{
    grid-column:auto;
  }}
}}

#secondaryActionsToggle.secondary-actions-trigger {{
  margin-inline-start:0;
}}

#secondaryActionsToggle.secondary-actions-trigger::before {{
  display:none;
}}

main {{
  padding:6px 12px 78px;
}}

.report-info-panel {{
  right:0;
  width:min(820px,calc(100vw - 28px));
  margin:0;
  padding:12px 14px;
  z-index:92;
}}

.report-info-head {{
  position:sticky;
  top:-12px;
  z-index:2;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin:-12px -14px 10px;
  padding:10px 12px;
  border-bottom:1px solid var(--line);
  background:color-mix(in srgb, Canvas 95%, transparent);
  backdrop-filter:blur(16px);
}}

.report-info-head > div {{
  display:flex;
  align-items:baseline;
  gap:8px;
}}

#groupedSections,
#creatorGroupedSections,
#flatSortSection {{
  margin-top:0;
}}

.group-heading {{
  margin-top:5px;
  margin-bottom:5px;
}}

.group-heading h2 {{
  margin:5px 0;
  font-size:16px;
}}

.grid {{
  gap:9px;
}}

.mobile-stats-summary,
.mobile-actions {{
  display:none;
}}

body.dark-theme .filter-panel,
body.dark-theme .secondary-actions,
body.dark-theme .report-info-panel,
body.dark-theme .report-info-head {{
  background:color-mix(in srgb, #171b22 94%, transparent);
  border-color:var(--line);
}}

@media (max-width:1100px) and (min-width:541px) {{
  .card-first-hero {{
    gap:7px 10px;
  }}

  .card-first-hero h1 {{
    font-size:21px;
  }}

  .card-first-hero .stats-grid {{
    flex-basis:100%;
    width:100%;
  }}

  .card-first-hero .stat-card {{
    padding:4px 6px;
  }}

  .card-first-toolbar > #q {{
    min-width:200px;
  }}

  .card-first-toolbar > #sortOrder {{
    flex-basis:165px;
    width:165px;
  }}

  .filter-panel {{
    grid-template-columns:repeat(3,minmax(140px,1fr));
  }}

  .secondary-actions {{
    grid-template-columns:repeat(3,minmax(140px,1fr));
  }}
}}

@media (max-width:900px) and (min-width:541px) {{
  header,
  main {{
    padding-left:9px;
    padding-right:9px;
  }}

  .card-first-hero {{
    border-radius:13px;
  }}

  .card-first-toolbar {{
    display:grid;
    grid-template-columns:minmax(0,1fr) 170px auto auto auto auto;
    position:sticky;
    top:4px;
    margin-top:5px;
  }}

  .card-first-toolbar > #q {{
    min-width:0;
  }}

  .card-first-toolbar > #sortOrder {{
    width:100%;
    min-width:0;
  }}

  .card-first-toolbar > button {{
    white-space:normal;
    overflow-wrap:anywhere;
  }}

  .filter-panel,
  .secondary-actions {{
    top:calc(100% + 6px);
  }}
}}

@media (max-width:540px) {{
  header {{
    padding:6px 8px 4px;
  }}

  .card-first-hero {{
    min-height:38px;
    margin:0 -8px;
    padding:6px 10px;
    border-radius:0 0 12px 12px;
  }}

  .card-first-hero h1 {{
    font-size:23px;
  }}

  .card-first-hero .stats-grid {{
    display:none;
  }}

  .mobile-stats-summary {{
    display:block;
    margin:4px 1px 5px;
    padding:0;
    font-size:11px;
  }}

  .mobile-quick-filters {{
    display:flex;
    flex-wrap:wrap;
    gap:5px;
    margin:0 0 5px;
  }}

  .mobile-quick-filters > button {{
    flex:1 1 auto;
  }}

  .mobile-actions {{
    display:flex;
    margin:0 0 5px;
  }}

  #mobileFilterToggle {{
    min-height:34px;
    padding:6px 9px;
  }}

  .card-first-toolbar {{
    display:none;
    position:relative;
    top:auto;
    grid-template-columns:1fr 1fr;
    gap:6px;
    margin:0 0 6px;
    padding:6px;
    min-height:0;
  }}

  .card-first-toolbar.mobile-open {{
    display:grid;
  }}

  .card-first-toolbar > #q {{
    grid-column:1 / -1;
    min-width:0;
  }}

  .card-first-toolbar > #sortOrder {{
    grid-column:1 / -1;
    width:100%;
  }}

  .card-first-toolbar > button {{
    width:100%;
    min-height:36px;
  }}

  .filter-panel,
  .secondary-actions {{
    position:fixed;
    top:68px;
    left:8px;
    right:8px;
    width:auto;
    max-height:calc(100vh - 142px);
    grid-template-columns:1fr 1fr;
    gap:6px;
  }}

  .filter-panel {{
    z-index:110;
  }}

  .secondary-actions {{
    z-index:111;
  }}

  .report-info-panel {{
    right:0;
    left:0;
    width:auto;
    max-height:min(68vh,620px);
  }}

  main {{
    padding:2px 8px 82px;
  }}

  .group-heading {{
    margin-top:2px;
    margin-bottom:3px;
  }}
}}

@media (max-width:390px) {{
  .filter-panel,
  .secondary-actions {{
    grid-template-columns:1fr;
  }}
}}


/* =======================================================================
   v0.4.0 — 上部統計クイックフィルター
   ======================================================================= */
.stat-filter-card {{
  appearance:none;
  position:relative;
  font:inherit;
  color:inherit;
  cursor:pointer;
  min-height:0;
  text-align:left;
  border-color:color-mix(in srgb, var(--accent) 28%, var(--line)) !important;
  background:color-mix(in srgb, var(--accent-soft) 38%, transparent) !important;
}}

.card-first-hero .stat-filter-card {{
  padding:6px 8px;
}}

.stat-filter-card:hover {{
  transform:none !important;
  border-color:color-mix(in srgb, var(--accent) 62%, var(--line)) !important;
  background:var(--accent-soft) !important;
}}

.stat-filter-card:focus-visible,
.mobile-stat-filter-trigger:focus-visible {{
  outline:2px solid var(--accent);
  outline-offset:2px;
}}

.stat-filter-hint {{
  display:inline-flex;
  align-items:center;
  max-width:150px;
  margin-left:4px;
  padding:2px 6px;
  border:1px solid color-mix(in srgb, var(--accent) 30%, var(--line));
  border-radius:999px;
  background:color-mix(in srgb, var(--accent) 10%, transparent);
  color:var(--accent);
  font-size:9.5px;
  font-weight:800;
  line-height:1.2;
  vertical-align:middle;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}}

.stat-filter-card.active .stat-filter-hint {{
  border-color:var(--accent);
  background:var(--accent);
  color:white;
}}

.mobile-quick-filters {{
  display:none;
}}

.mobile-stat-filter-trigger {{
  min-height:32px;
  padding:5px 8px;
  border-radius:10px;
  white-space:nowrap;
  font-size:11px;
  font-weight:750;
}}

.mobile-stat-filter-trigger.active {{
  border-color:var(--accent);
  background:var(--accent-soft);
}}

@media (max-width:540px) {{
  .mobile-quick-filters {{
    display:flex;
    flex-wrap:wrap;
    gap:5px;
    margin:0 0 5px;
  }}

  .mobile-quick-filters > button {{
    flex:1 1 auto;
  }}
}}

.stat-filter-card.active,
.stat-filter-card[aria-expanded="true"] {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line)) !important;
  background:var(--accent-soft) !important;
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 10%, transparent) !important;
}}

.stat-filter-card .stat-value,
.stat-filter-card .stat-label {{
  display:inline;
}}

.stat-quick-filter-panel {{
  position:fixed;
  z-index:130;
  width:min(540px,calc(100vw - 16px));
  padding:9px;
  border:1px solid var(--line);
  border-radius:15px;
  background:color-mix(in srgb, Canvas 95%, transparent);
  box-shadow:var(--shadow-lg);
  backdrop-filter:blur(18px);
}}

.stat-quick-filter-head {{
  display:flex;
  align-items:baseline;
  justify-content:space-between;
  gap:10px;
  margin-bottom:7px;
}}

.stat-quick-filter-head b {{
  font-size:13px;
  white-space:nowrap;
}}

.stat-quick-filter-head .small {{
  text-align:right;
}}

.stat-quick-select {{
  display:none !important;
}}

.stat-quick-choices {{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:6px;
  max-height:min(58vh,520px);
  overflow:auto;
  padding:1px;
}}

.stat-quick-choice {{
  min-height:36px;
  width:100%;
  padding:7px 9px;
  border-radius:10px;
  text-align:left;
  line-height:1.25;
  font-size:12.5px;
  font-weight:600;
  display:flex;
  align-items:center;
  gap:7px;
}}

.stat-quick-choice::before {{
  content:"□";
  flex:0 0 auto;
  font-size:14px;
  line-height:1;
  color:var(--muted);
}}

.stat-quick-choice.active::before {{
  content:"✓";
  color:var(--accent);
  font-weight:900;
}}

.stat-quick-choice.active {{
  border-color:color-mix(in srgb, var(--accent) 65%, var(--line));
  background:var(--accent-soft);
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 10%, transparent);
}}

@media (max-width:680px) {{
  .stat-quick-choices {{
    grid-template-columns:1fr;
  }}

  .stat-quick-filter-head .small {{
    display:none;
  }}
}}

body.dark-theme .stat-quick-filter-panel {{
  background:color-mix(in srgb, #171b22 95%, transparent);
  border-color:var(--line);
}}

@media (max-width:540px) {{
  .stat-quick-filter-panel {{
    left:8px !important;
    right:8px !important;
    width:auto;
  }}
}}


/* =======================================================================
   v0.4.25 — 一括タグ管理
   ======================================================================= */
.tag-manager-panel {{
  max-width:720px;
}}

.tag-manager-grid {{
  display:grid;
  gap:13px;
  margin-top:10px;
}}

.tag-manager-field {{
  display:grid;
  gap:6px;
  font-size:12px;
  font-weight:700;
}}

.tag-manager-field select,
.tag-manager-field input {{
  width:100%;
  min-width:0;
}}

.tag-manager-note {{
  padding:9px 11px;
  border:1px solid var(--line);
  border-radius:11px;
  background:color-mix(in srgb, var(--accent-soft) 42%, var(--surface));
  font-size:11px;
  line-height:1.55;
}}

.tag-manager-actions {{
  display:flex;
  flex-wrap:wrap;
  justify-content:flex-end;
  gap:7px;
}}

#tagManagerApply {{
  border-color:color-mix(in srgb, var(--accent) 46%, var(--line));
  background:var(--accent-soft);
}}

@media (max-width:540px) {{
  .tag-manager-actions {{
    display:grid;
    grid-template-columns:1fr 1fr;
  }}

  .tag-manager-actions button {{
    width:100%;
  }}
}}


/* =======================================================================
   v0.4.26 — 車種ごとの整理進捗
   ======================================================================= */
.group-progress-badge {{
  --group-progress-color:var(--muted);
  display:inline-flex;
  align-items:center;
  gap:7px;
  margin-left:auto;
  padding:4px 8px;
  border:1px solid var(--line);
  border-radius:999px;
  background:color-mix(in srgb, var(--surface) 90%, transparent);
  font-size:10.5px;
  font-weight:750;
  line-height:1;
  white-space:nowrap;
  opacity:1 !important;
}}

.group-progress-badge[data-progress-state="partial"] {{
  --group-progress-color:var(--accent);
  border-color:color-mix(in srgb, var(--accent) 32%, var(--line));
  background:color-mix(in srgb, var(--accent-soft) 55%, var(--surface));
}}

.group-progress-badge[data-progress-state="complete"] {{
  --group-progress-color:var(--good);
  border-color:color-mix(in srgb, var(--good) 42%, var(--line));
  background:color-mix(in srgb, var(--good-soft) 62%, var(--surface));
}}

.group-progress-badge .group-progress-text {{
  opacity:1 !important;
}}

.group-progress-bar {{
  width:78px;
  height:8px;
  border:0;
  accent-color:var(--group-progress-color);
}}

.group-progress-bar::-webkit-progress-bar {{
  background:color-mix(in srgb, CanvasText 10%, transparent);
  border-radius:999px;
}}

.group-progress-bar::-webkit-progress-value {{
  background:var(--group-progress-color);
  border-radius:999px;
}}

.group-progress-bar::-moz-progress-bar {{
  background:var(--group-progress-color);
  border-radius:999px;
}}

@media (max-width:760px) {{
  .group-progress-badge {{
    margin-left:0;
  }}
}}

@media (max-width:420px) {{
  .group-progress-bar {{
    width:64px;
  }}
}}


/* =======================================================================
   v0.4.27 — バックアップ鮮度状態
   ======================================================================= */
.backup-status-panel {{
  margin:10px 0 2px;
  padding:10px;
  border:1px solid var(--line);
  border-radius:13px;
  background:color-mix(in srgb, var(--surface) 92%, transparent);
}}

.backup-status-head {{
  display:flex;
  align-items:baseline;
  justify-content:space-between;
  gap:10px;
  margin-bottom:7px;
}}

.backup-status-head b {{
  font-size:12px;
}}

.backup-status-list {{
  display:grid;
  gap:6px;
}}

.backup-status-row {{
  display:grid;
  grid-template-columns:minmax(120px,1fr) auto minmax(160px,auto);
  gap:8px;
  align-items:center;
  padding:7px 8px;
  border:1px solid var(--line);
  border-radius:10px;
  background:color-mix(in srgb, Canvas 97%, CanvasText 3%);
}}

.backup-status-kind {{
  min-width:0;
  font-size:11px;
  font-weight:750;
}}

.backup-status-badge {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:78px;
  padding:4px 8px;
  border:1px solid var(--line);
  border-radius:999px;
  font-size:10.5px;
  font-weight:850;
  white-space:nowrap;
}}

.backup-status-badge[data-state="current"] {{
  border-color:color-mix(in srgb, var(--good) 44%, var(--line));
  background:var(--good-soft);
}}

.backup-status-badge[data-state="changed"] {{
  border-color:color-mix(in srgb, #d97706 48%, var(--line));
  background:color-mix(in srgb, #d97706 11%, Canvas);
}}

.backup-status-badge[data-state="none"] {{
  color:var(--muted);
}}

.backup-status-time {{
  color:var(--muted);
  font-size:10.5px;
  text-align:right;
  white-space:nowrap;
}}

.backup-recommendation {{
  margin-top:7px;
  padding:7px 9px;
  border-left:3px solid var(--line-strong);
  border-radius:8px;
  background:color-mix(in srgb, Canvas 96%, CanvasText 4%);
  font-size:10.5px;
  line-height:1.5;
}}

.backup-recommendation[data-level="ok"] {{
  border-left-color:var(--good);
  background:color-mix(in srgb, var(--good-soft) 58%, transparent);
}}

.backup-recommendation[data-level="warning"] {{
  border-left-color:#d97706;
  background:color-mix(in srgb, #d97706 9%, Canvas);
}}

.backup-recommendation[data-level="urgent"] {{
  border-left-color:var(--bad);
  background:var(--bad-soft);
}}

.backup-status-link-note {{
  display:block;
  margin-top:7px;
}}

body.dark-theme .backup-status-row {{
  background:var(--surface);
}}

@media (max-width:620px) {{
  .backup-status-head {{
    display:block;
  }}
  .backup-status-row {{
    grid-template-columns:1fr auto;
  }}
  .backup-status-time {{
    grid-column:1 / -1;
    text-align:left;
  }}
}}



/* =======================================================================
   v0.4.31 — バックアップ後の変更概要
   ======================================================================= */
.backup-change-summary {{
  margin-top:7px;
  padding:8px 9px;
  border:1px solid var(--line);
  border-radius:10px;
  background:color-mix(in srgb, Canvas 97%, CanvasText 3%);
}}

.backup-change-summary-head {{
  display:flex;
  align-items:baseline;
  justify-content:space-between;
  gap:8px;
  margin-bottom:6px;
}}

.backup-change-summary-head b {{
  font-size:11px;
}}

.backup-change-items {{
  display:flex;
  flex-wrap:wrap;
  gap:5px;
}}

.backup-change-item {{
  display:inline-flex;
  align-items:center;
  gap:4px;
  min-height:25px;
  padding:3px 7px;
  border:1px solid var(--line);
  border-radius:999px;
  background:color-mix(in srgb, var(--surface) 92%, transparent);
  font-size:10px;
  white-space:nowrap;
}}

.backup-change-item b {{
  font-variant-numeric:tabular-nums;
}}

.backup-change-summary[data-state="changed"] {{
  border-color:color-mix(in srgb, #d97706 38%, var(--line));
  background:color-mix(in srgb, #d97706 6%, Canvas);
}}

.backup-change-summary[data-state="current"] {{
  border-color:color-mix(in srgb, var(--good) 30%, var(--line));
}}

#backupChangeSummaryNote {{
  display:block;
  margin-top:6px;
  line-height:1.45;
}}

body.dark-theme .backup-change-summary {{
  background:var(--surface);
}}

@media (max-width:620px) {{
  .backup-change-summary-head {{
    display:block;
  }}
}}

/* =======================================================================
   v0.4.32 — コンパクトなフィルター / レポートメニュー
   ======================================================================= */
.filter-panel-tabs,
.report-info-tabs {{
  display:grid;
  gap:5px;
  margin-bottom:8px;
}}

.filter-panel-tabs {{
  grid-template-columns:repeat(2,minmax(0,1fr));
}}

.report-info-tabs {{
  grid-template-columns:repeat(2,minmax(0,1fr));
}}

.filter-panel-tab,
.report-info-tab {{
  min-height:32px;
  padding:5px 9px;
  border-radius:9px;
  font-size:11px;
  font-weight:800;
}}

.filter-panel-tab.active,
.report-info-tab.active {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line));
  background:var(--accent-soft);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 10%, transparent);
}}

.filter-panel {{
  display:block;
}}

.filter-panel-pane {{
  min-width:0;
}}

.filter-condition-pane {{
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  gap:7px;
  align-items:start;
  align-content:start;
}}

.filter-condition-pane > * {{
  min-width:0;
  width:100%;
  box-sizing:border-box;
}}

.filter-condition-pane .filter-multi-note,
.filter-condition-pane .creator-filter-summary,
.filter-condition-pane .filter-preset-card,
.filter-condition-pane .filter-quick-toggle-grid {{
  grid-column:1 / -1;
}}

.filter-quick-toggle-grid {{
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  gap:6px;
}}

.compact-filter-trigger-card {{
  min-width:0;
  padding:8px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, var(--surface) 88%, transparent);
}}

.compact-filter-trigger-card .detail-filter-head {{
  margin-bottom:6px;
}}

.compact-filter-trigger-card .detail-filter-quick-trigger {{
  margin:0;
}}

.compact-tag-card .tag-match-mode {{
  margin-bottom:6px;
}}

.filter-bulk-pane {{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:8px;
  align-items:start;
  align-content:start;
}}

.filter-bulk-group {{
  min-width:0;
  padding:9px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, Canvas 96%, CanvasText 4%);
}}

.filter-bulk-group h4 {{
  margin:0 0 7px;
  padding:0 2px 6px;
  border-bottom:1px solid var(--line);
  color:var(--muted);
  font-size:11px;
}}

.filter-bulk-actions {{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:6px;
}}

.filter-bulk-actions button {{
  width:100%;
  min-width:0;
}}

#compareSelected {{
  grid-column:1 / -1;
  border-color:color-mix(in srgb, var(--accent) 36%, var(--line));
}}

.report-info-panel {{
  width:min(900px,calc(100vw - 28px));
}}

.report-info-pane {{
  min-width:0;
}}

.report-overview-grid {{
  display:grid;
  grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);
  gap:10px;
  align-items:start;
}}

.report-meta-card,
.report-progress-card {{
  min-width:0;
  padding:10px;
  border:1px solid var(--line);
  border-radius:12px;
  background:color-mix(in srgb, Canvas 97%, CanvasText 3%);
}}

.report-meta-grid {{
  display:grid;
  grid-template-columns:max-content minmax(0,1fr);
  gap:5px 9px;
  margin:0;
  font-size:11px;
  line-height:1.35;
}}

.report-meta-grid dt {{
  font-weight:800;
  color:var(--muted);
}}

.report-meta-grid dd {{
  margin:0;
  min-width:0;
  overflow-wrap:anywhere;
}}

.report-progress-card .counterbar {{
  margin-top:0;
}}

.report-progress-card .progress-row {{
  margin-top:8px;
}}

.report-info-safety {{
  margin-top:8px;
  font-size:10.5px;
  line-height:1.45;
}}

@media (min-width:901px) {{
  .filter-panel,
  .report-info-panel {{
    max-height:none;
    overflow:visible;
  }}
}}

@media (max-width:1100px) and (min-width:761px) {{
  .filter-condition-pane {{
    grid-template-columns:repeat(3,minmax(0,1fr));
  }}
  .filter-quick-toggle-grid {{
    grid-template-columns:repeat(3,minmax(0,1fr));
  }}
  .filter-bulk-pane {{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }}
  .report-overview-grid {{
    grid-template-columns:1fr;
  }}
}}

@media (max-width:760px) {{
  .filter-condition-pane {{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }}
  .filter-quick-toggle-grid {{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }}
  .filter-bulk-pane {{
    grid-template-columns:1fr;
  }}
  .report-overview-grid {{
    grid-template-columns:1fr;
  }}
}}

@media (max-width:420px) {{
  .filter-condition-pane,
  .filter-quick-toggle-grid {{
    grid-template-columns:1fr;
  }}
  .filter-bulk-actions {{
    grid-template-columns:1fr;
  }}
}}

body.dark-theme .filter-bulk-group,
body.dark-theme .report-meta-card,
body.dark-theme .report-progress-card {{
  background:var(--surface);
  border-color:var(--line);
}}

/* =======================================================================
   v0.4.33 — 整理完了概要
   ======================================================================= */
.organization-completion-summary {{
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:6px 10px;
  margin:3px 1px 5px;
  padding:6px 9px;
  border:1px solid color-mix(in srgb, var(--good) 34%, var(--line));
  border-radius:11px;
  background:color-mix(in srgb, var(--good-soft) 68%, var(--surface));
  box-shadow:var(--shadow-xs);
  font-size:10.5px;
  line-height:1.3;
}}

.organization-completion-summary strong {{
  color:var(--good);
  font-size:11px;
  white-space:nowrap;
}}

.organization-completion-detail {{
  white-space:nowrap;
}}

.organization-completion-backup {{
  margin-left:auto;
  padding:3px 7px;
  border:1px solid var(--line);
  border-radius:999px;
  background:color-mix(in srgb, Canvas 96%, CanvasText 4%);
  font-weight:750;
  white-space:nowrap;
}}

.organization-completion-backup[data-state="current"] {{
  border-color:color-mix(in srgb, var(--good) 42%, var(--line));
  background:var(--good-soft);
}}

.organization-completion-backup[data-state="changed"] {{
  border-color:color-mix(in srgb, #d97706 45%, var(--line));
  background:color-mix(in srgb, #d97706 10%, Canvas);
}}

.organization-completion-backup[data-state="none"],
.organization-completion-backup[data-state="temporary"] {{
  border-color:color-mix(in srgb, var(--bad) 32%, var(--line));
  background:var(--bad-soft);
}}

body.dark-theme .organization-completion-backup {{
  background:var(--surface);
}}

@media (max-width:540px) {{
  .organization-completion-summary {{
    margin:3px 0 5px;
    padding:6px 8px;
    gap:5px 8px;
  }}
  .organization-completion-backup {{
    width:100%;
    margin-left:0;
    text-align:center;
  }}
}}

/* =======================================================================
   v0.4.35 — 現行ワークフローのヘルプナビゲーション
   ======================================================================= */
.help-tabs {{
  position:sticky;
  top:-18px;
  z-index:3;
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:6px;
  margin:0 -2px 12px;
  padding:7px 2px;
  background:color-mix(in srgb, var(--surface-elevated) 96%, transparent);
  backdrop-filter:blur(16px);
}}

.help-tab {{
  min-height:34px;
  padding:6px 8px;
  border-radius:10px;
  font-size:11px;
  font-weight:800;
}}

.help-tab.active {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line));
  background:var(--accent-soft);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 10%, transparent);
}}

.help-pane {{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:12px;
}}

.help-pane > .help-section-wide {{
  grid-column:1 / -1;
}}

.help-current-note {{
  margin:0 0 12px;
  padding:8px 10px;
  border:1px dashed var(--line);
  border-radius:10px;
  color:var(--muted);
  font-size:10.5px;
  line-height:1.55;
}}

@media (max-width:760px) {{
  .help-tabs {{
    position:static;
    grid-template-columns:repeat(2,minmax(0,1fr));
    margin-bottom:10px;
  }}
  .help-pane {{
    grid-template-columns:1fr;
  }}
  .help-pane > .help-section-wide {{
    grid-column:auto;
  }}
}}

@media (max-width:420px) {{
  .help-tabs {{
    grid-template-columns:1fr 1fr;
    gap:5px;
  }}
}}

/* =======================================================================
   v0.4.34 — 現在車種のナビゲーション強調
   ======================================================================= */
.car-group.vehicle-navigation-current > .group-heading {{
  margin-left:-4px;
  margin-right:-4px;
  padding-top:4px;
  padding-right:7px;
  padding-bottom:4px;
  border-radius:10px;
  background:color-mix(in srgb, var(--accent-soft) 78%, transparent);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 24%, transparent);
}}

.car-group.vehicle-navigation-current > .group-heading::before {{
  width:5px;
  background:var(--accent);
}}

button.group-progress-badge[aria-current="true"] {{
  border-color:color-mix(in srgb, var(--accent) 58%, var(--line));
  background:color-mix(in srgb, var(--accent-soft) 82%, var(--surface));
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 10%, transparent);
}}

#vehicleWorkflowHint[data-navigation-state="current"] {{
  color:var(--accent);
  font-weight:800;
  opacity:1;
}}

#vehicleWorkflowHint[data-navigation-state="complete"] {{
  color:var(--good);
  font-weight:800;
  opacity:1;
}}

@media (max-width:540px) {{
  .car-group.vehicle-navigation-current > .group-heading {{
    margin-left:0;
    margin-right:0;
  }}
}}

/* =======================================================================
   v0.4.29 — 車種ワークフローのクイックナビゲーション
   ======================================================================= */
button.group-progress-badge {{
  appearance:none;
  min-height:0;
  color:inherit;
  font:inherit;
  cursor:pointer;
  box-shadow:none;
}}

button.group-progress-badge:hover:not(:disabled) {{
  transform:none;
  border-color:color-mix(in srgb, var(--accent) 52%, var(--line));
  background:color-mix(in srgb, var(--accent-soft) 72%, var(--surface));
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 9%, transparent);
}}

button.group-progress-badge:focus-visible {{
  outline:3px solid color-mix(in srgb, var(--accent) 28%, transparent);
  outline-offset:2px;
}}

.vehicle-workflow-bar {{
  display:flex;
  align-items:center;
  gap:6px;
  margin:5px 1px 4px;
  padding:6px 8px;
  border:1px solid color-mix(in srgb, var(--accent) 20%, var(--line));
  border-radius:12px;
  background:color-mix(in srgb, var(--accent-soft) 38%, var(--surface));
  box-shadow:var(--shadow-xs);
}}

.vehicle-workflow-label {{
  flex:0 0 auto;
  padding:0 3px;
  color:var(--muted);
  font-size:11px;
  font-weight:800;
  white-space:nowrap;
}}

.vehicle-workflow-bar button {{
  flex:0 0 auto;
  min-height:32px;
  padding:5px 9px;
  font-size:11px;
}}

.vehicle-workflow-bar button.active {{
  border-color:color-mix(in srgb, var(--accent) 62%, var(--line));
  background:var(--accent-soft);
  box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 10%, transparent);
}}

#vehicleWorkflowHint {{
  min-width:0;
  margin-left:auto;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}

body.dark-theme .vehicle-workflow-bar {{
  background:color-mix(in srgb, var(--surface) 92%, var(--accent) 8%);
  border-color:var(--line);
}}

/* 長い翻訳でも中幅画面で横にはみ出さないよう、操作群を自然に折り返します。 */
@media (max-width:1100px) and (min-width:541px) {{
  .vehicle-workflow-bar {{
    flex-wrap:wrap;
  }}
  #vehicleWorkflowHint {{
    flex:1 1 100%;
    width:100%;
    margin-left:0;
    text-align:right;
  }}
}}

/* =======================================================================
   v0.4.30 — 車種整理概要
   ======================================================================= */
.vehicle-progress-summary {{
  display:inline-flex;
  align-items:center;
  gap:4px;
  white-space:nowrap;
}}

.vehicle-progress-summary b {{
  min-width:1.4em;
  text-align:right;
  font-variant-numeric:tabular-nums;
}}

.vehicle-progress-summary[data-vehicle-progress-state="none"] b {{
  color:var(--muted);
}}

.vehicle-progress-summary[data-vehicle-progress-state="partial"] b {{
  color:var(--accent);
}}

.vehicle-progress-summary[data-vehicle-progress-state="complete"] b {{
  color:var(--good);
}}

@media (max-width:540px) {{
  .vehicle-workflow-bar {{
    display:grid;
    grid-template-columns:repeat(6,minmax(0,1fr));
    gap:5px;
    margin:3px 0 4px;
    padding:5px;
    border-radius:11px;
  }}
  .vehicle-workflow-label {{
    display:none;
  }}
  .vehicle-workflow-bar button {{
    width:100%;
    min-width:0;
    min-height:34px;
    padding:5px 5px;
  }}
  .vehicle-progress-summary {{
    grid-column:span 2;
    justify-content:center;
    font-size:10px !important;
  }}
  #unfinishedVehiclesOnly {{
    grid-column:1 / -1;
  }}
  #previousUnfinishedVehicleQuick,
  #nextUnfinishedVehicleQuick {{
    grid-column:span 3;
  }}
  #vehicleWorkflowHint {{
    grid-column:1 / -1;
    margin-left:0;
    padding:0 2px 1px;
    font-size:10px;
    text-align:right;
  }}
}}



/* =======================================================================
   v0.4.56-r22 — リリース前仕上げ / FH6マイデザイン情報配置
   ======================================================================= */
.fh6-creator-display,
.fh6-display-date {{
  display:none;
}}
/* FH6本体との目視照合をしやすくするため、FH6マイデザイン順だけは
   タイトル → 作成者 → DD/MM/YYYY の順にまとめ、その下へ取得日時・バイナル数を置きます。 */
body.fh6-my-design-view-mode .fh6-my-design-column .fh6-creator-display {{
  display:block;
  margin:1px 1px 0;
  text-align:left;
  font-size:12.5px;
  line-height:1.2;
  font-weight:650;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .fh6-display-date {{
  display:block;
  margin:2px 1px 5px;
  text-align:left;
  font-size:12.5px;
  line-height:1.2;
  font-weight:800;
  font-variant-numeric:tabular-nums;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .fh6-normal-creator-row {{
  display:none !important;
}}
.exact-duplicate-panel {{ max-width:1180px; }}
.exact-duplicate-nav {{
  display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin:10px 0 12px;
}}
.exact-duplicate-nav .small {{ margin-left:auto; }}
.exact-duplicate-item {{ position:relative; }}
.exact-duplicate-item.is-keeper {{
  outline:3px solid var(--good);
  outline-offset:1px;
}}
.exact-duplicate-item .keeper-action {{
  width:100%;
  border-color:color-mix(in srgb, var(--good) 42%, var(--line));
}}
.exact-duplicate-item.is-keeper .keeper-action {{
  background:var(--good-soft);
  border-color:var(--good);
  font-weight:850;
}}

/* =======================================================================
   v0.4.56-r16 — 再ダウンロード完全一致の整理導線
   ======================================================================= */
.pill.exact-duplicate {{
  border-color:color-mix(in srgb, #b45309 55%, transparent);
  background:color-mix(in srgb, #b45309 15%, Canvas);
  font-weight:800;
}}

/* =======================================================================
   v0.4.56-r14 — モーダルのキーボードフォーカス管理
   ======================================================================= */
/* ダイアログ表示中はフォーカスをダイアログ内に保ち、閉じたら起点へ戻します。 */
.modal-panel[tabindex="-1"]:focus {{ outline:none; }}

/* =======================================================================
   v0.4.56-r13 — 類似候補の理由別絞り込み
   ======================================================================= */
/* 「類似候補のみ」に加え、表示中の判定理由で「画像一致」「同一作者・同名」を
   個別に絞り込めるようにします。既存カードの類似判定ロジック自体は変更しません。 */

/* =======================================================================
   v0.4.57-r05 — FH6マイデザイン車種ジャンプのキーボード操作統合
   ======================================================================= */
/* 既存の実スロット / #列U・D位置ジャンプと車種検索に、
   Jキーで入力欄へ戻る操作、Shift+← / Shift+→で一致位置を巡回する操作を追加します。
   検索確定後はジャンプ先カードをキーボード操作対象に切り替えます。 */
.fh6-my-design-jump-input-wrap {{
  position:relative;
  display:inline-flex;
}}
.fh6-my-design-jump input {{
  width:20em;
  max-width:min(420px, 70vw);
}}
.fh6-my-design-jump-suggestions {{
  position:absolute;
  z-index:40;
  top:calc(100% + 4px);
  left:0;
  width:min(430px, 76vw);
  max-height:280px;
  overflow:auto;
  padding:5px;
  border:1px solid var(--line);
  border-radius:10px;
  background:var(--surface);
  box-shadow:var(--shadow-md);
}}
.fh6-my-design-jump-suggestions.hidden {{ display:none; }}
.fh6-vehicle-suggestion {{
  display:flex;
  width:100%;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:7px 8px;
  border:0;
  border-radius:7px;
  background:transparent;
  color:inherit;
  text-align:left;
  cursor:pointer;
}}
.fh6-vehicle-suggestion:hover,
.fh6-vehicle-suggestion:focus-visible,
.fh6-vehicle-suggestion[aria-selected="true"] {{
  background:color-mix(in srgb, var(--accent) 12%, transparent);
}}
.fh6-vehicle-suggestion[aria-selected="true"] {{
  outline:2px solid color-mix(in srgb, var(--accent) 42%, transparent);
  outline-offset:-2px;
}}
.fh6-vehicle-suggestion-label {{
  min-width:0;
  font-weight:800;
}}
.fh6-vehicle-suggestion-meta {{
  flex:0 0 auto;
  font-size:10px;
  opacity:.78;
  white-space:nowrap;
  font-variant-numeric:tabular-nums;
}}
.fh6-vehicle-match-nav {{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:5px;
  flex:1 1 100%;
}}
.fh6-vehicle-match-nav.hidden {{ display:none; }}
#fh6VehicleMatchState {{
  max-width:36em;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-variant-numeric:tabular-nums;
}}
.fh6-vehicle-match-nav button {{
  min-height:28px;
  padding:4px 8px;
  font-size:10px;
}}

/* =======================================================================
   v0.4.57-r02 — FH6位置表記 U/D化 + 実スロット番号表示
   ======================================================================= */
/* FH6マイデザイン順では #001（実スロット）と #001U / #001D（FH6位置）を
   同時に表示します。位置ジャンプの列指定は U/D のみ受け付けます。 */

/* =======================================================================
   v0.4.57-r01 — FH6マイデザイン位置ジャンプ
   ======================================================================= */
.fh6-my-design-head {{
  flex-wrap:wrap;
}}
.fh6-my-design-jump {{
  display:flex;
  align-items:center;
  gap:5px;
  flex-wrap:wrap;
  flex:1 1 300px;
  justify-content:flex-end;
}}
.fh6-my-design-jump label {{
  font-size:11px;
  font-weight:800;
  white-space:nowrap;
}}
.fh6-my-design-jump input {{
  width:10.5em;
  min-height:32px;
  padding:5px 8px;
  border:1px solid var(--line);
  border-radius:8px;
  background:var(--surface);
  color:inherit;
  font:inherit;
  font-size:11px;
  font-variant-numeric:tabular-nums;
}}
.fh6-my-design-jump input:focus-visible {{
  outline:3px solid color-mix(in srgb, var(--accent) 24%, transparent);
  outline-offset:1px;
}}
.fh6-my-design-jump button {{
  min-height:32px;
  padding:5px 9px;
  font-size:11px;
}}
.fh6-my-design-slot.fh6-jump-highlight > .card {{
  outline:4px solid var(--accent);
  outline-offset:2px;
  animation:fh6-jump-pulse 900ms ease-out 2;
}}
@keyframes fh6-jump-pulse {{
  0%, 100% {{ transform:translateZ(0) scale(1); }}
  45% {{ transform:translateZ(0) scale(0.985); }}
}}
@media (prefers-reduced-motion: reduce) {{
  .fh6-my-design-slot.fh6-jump-highlight > .card {{ animation:none; }}
}}

/* =======================================================================
   v0.4.56-r12 — FH6マイデザイン順（マウスホイール横移動）
   ======================================================================= */
.fh6-my-design-section {{
  margin-top:4px;
  padding:9px 10px 10px;
  border:1px solid var(--line);
  border-radius:15px;
  background:color-mix(in srgb, var(--surface) 92%, transparent);
  box-shadow:var(--shadow-xs);
}}
body.fh6-my-design-view-mode #groupedSections,
body.fh6-my-design-view-mode #creatorGroupedSections,
body.fh6-my-design-view-mode #flatSortSection {{
  display:none !important;
}}
body.fh6-my-design-view-mode #fh6MyDesignSection {{
  display:block !important;
}}
.fh6-my-design-head {{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-bottom:7px;
}}
.fh6-my-design-head > div:first-child {{
  display:flex;
  align-items:baseline;
  gap:8px;
  min-width:0;
}}
.fh6-my-design-head h2 {{
  margin:0;
  font-size:16px;
  white-space:nowrap;
}}
.fh6-my-design-nav {{
  display:flex;
  align-items:center;
  gap:6px;
  flex:0 0 auto;
}}
.fh6-my-design-nav button {{
  min-height:32px;
  padding:5px 9px;
  font-size:11px;
}}
#fh6MyDesignPosition {{
  min-width:9em;
  text-align:center;
  font-variant-numeric:tabular-nums;
  font-weight:800;
}}
.fh6-my-design-viewport {{
  width:100%;
  overflow-x:auto;
  overflow-y:hidden;
  scroll-snap-type:x mandatory;
  overscroll-behavior-x:contain;
  scrollbar-gutter:stable;
  padding:2px 1px 8px;
  outline:none;
}}
.fh6-my-design-viewport:focus-visible {{
  outline:3px solid color-mix(in srgb, var(--accent) 24%, transparent);
  outline-offset:2px;
  border-radius:10px;
}}
.fh6-my-design-track {{
  display:flex;
  align-items:stretch;
  gap:10px;
  width:max-content;
  min-width:100%;
}}
.fh6-my-design-column {{
  flex:0 0 clamp(260px,22vw,340px);
  width:clamp(260px,22vw,340px);
  display:grid;
  grid-template-rows:repeat(2,minmax(0,1fr));
  gap:10px;
  scroll-snap-align:start;
  scroll-snap-stop:always;
}}
.fh6-my-design-slot {{
  min-width:0;
  min-height:0;
}}
.fh6-my-design-empty-slot {{
  min-height:170px;
  display:grid;
  place-items:center;
  border:1px dashed var(--line);
  border-radius:16px;
  color:var(--muted);
  font-size:11px;
}}
.fh6-my-design-foot {{
  margin-top:7px;
  line-height:1.55;
}}
.fh6-my-design-foot p {{
  margin:0;
}}
.fh6-my-design-foot p + p {{
  margin-top:7px;
}}
.fh6-my-design-foot b.fh6-foot-label {{
  display:inline-block;
  min-width:7.5em;
  margin-right:4px;
  color:var(--muted);
}}
.pill.fh6-my-design-position {{
  display:none;
  min-width:5.6em;
  align-items:center;
  justify-content:center;
  border-color:color-mix(in srgb, var(--accent2) 40%, transparent);
  background:color-mix(in srgb, var(--accent2) 10%, Canvas);
  font-variant-numeric:tabular-nums;
  font-weight:850;
}}
/* 通常のマイデザイン順では実スロット通し番号を表示します。
   FH6マイデザイン順では、実スロット通し番号と列＋U/D位置を同時に表示します。 */
.topline .pill.my-design-index {{
  display:none;
}}
body.my-design-sort-mode .topline .pill.my-design-index {{
  display:inline-flex;
}}
body.fh6-my-design-view-mode .topline .pill.my-design-index {{
  display:inline-flex !important;
}}
body.fh6-my-design-view-mode .topline .pill.fh6-my-design-position {{
  display:inline-flex !important;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .card {{
  width:100%;
  height:100%;
  content-visibility:visible;
  contain-intrinsic-size:auto;
  border-radius:16px;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .card img,
body.fh6-my-design-view-mode .fh6-my-design-column .card img.livery-image,
body.fh6-my-design-view-mode .fh6-my-design-column .noimg {{
  aspect-ratio:2.15 / 1;
  border-radius:15px 15px 0 0;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .body {{
  padding:7px 9px 8px;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .topline {{
  margin-bottom:3px;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .card-vehicle-sort-only {{
  display:block !important;
  margin:2px 0 2px;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-size:12px;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .asset,
body.fh6-my-design-view-mode .fh6-my-design-column .desc,
body.fh6-my-design-view-mode .fh6-my-design-column .personal-meta,
body.fh6-my-design-view-mode .fh6-my-design-column .decision {{
  display:none !important;
}}
body.fh6-my-design-view-mode .fh6-my-design-column h4 {{
  margin:7px 0 2px;
  font-size:14px;
  line-height:1.15;
  height:2.3em;
  overflow:hidden;
}}
body.fh6-my-design-view-mode .fh6-my-design-column h4 .title-filter {{
  display:block;
  width:100%;
  max-width:none;
  white-space:normal;
  overflow-wrap:anywhere;
  word-break:normal;
  text-overflow:clip;
  text-transform:uppercase;
  text-align:left;
  line-height:inherit;
}}
body.fh6-my-design-view-mode .fh6-my-design-column dl {{
  margin:3px 0 0;
  grid-template-columns:58px minmax(0,1fr);
  gap:1px 5px;
  font-size:10.5px;
  line-height:1.2;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .vehicle-meta {{
  font-size:10.5px;
}}
body.fh6-my-design-view-mode .fh6-my-design-column .card:hover {{
  transform:none;
}}
body.dark-theme .fh6-my-design-section {{
  background:var(--surface);
  border-color:var(--line);
}}
@media (max-width:760px) {{
  .fh6-my-design-head {{
    align-items:flex-start;
    flex-direction:column;
  }}
  .fh6-my-design-nav {{
    width:100%;
  }}
  .fh6-my-design-nav button {{
    flex:1 1 0;
  }}
  #fh6MyDesignPosition {{
    flex:0 0 auto;
  }}
  .fh6-my-design-column {{
    flex-basis:min(82vw,320px);
    width:min(82vw,320px);
  }}
}}


/* =======================================================================
   v0.4.57-r07 — 位置・車種ジャンプの状態表示を1か所へ統合
   ======================================================================= */
/* r06で上段と一致ナビ内に重複していた状態表示を、
   「前の一致 / 次の一致」の間にある中央ステータスへ統合します。
   上段は入力操作だけにして、長い車種名に使える横幅も確保します。 */
.fh6-my-design-head {{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  grid-template-areas:
    "heading nav"
    "jump jump";
  align-items:center;
  gap:7px 10px;
}}
.fh6-my-design-head > div:first-child {{
  grid-area:heading;
}}
.fh6-my-design-nav {{
  grid-area:nav;
}}
.fh6-my-design-jump {{
  grid-area:jump;
  width:100%;
  display:grid;
  grid-template-columns:auto minmax(14em,34em) auto auto;
  grid-template-areas:
    "label input action navigator"
    "match match match match"
    "settings settings settings settings";
  align-items:center;
  justify-content:start;
  gap:5px 7px;
  flex:none;
}}
.fh6-my-design-jump > label {{
  grid-area:label;
}}
.fh6-my-design-jump-input-wrap {{
  grid-area:input;
  width:100%;
}}
.fh6-my-design-jump input {{
  width:100%;
  max-width:none;
  box-sizing:border-box;
}}
#fh6MyDesignJump {{
  grid-area:action;
}}
#fh6NavigatorMove {{
  grid-area:navigator;
  border-color:color-mix(in srgb, var(--accent) 48%, var(--line));
  background:color-mix(in srgb, var(--accent) 10%, var(--surface));
  white-space:nowrap;
}}
#fh6NavigatorMove:not(:disabled):hover {{
  background:color-mix(in srgb, var(--accent) 17%, var(--surface));
}}
.fh6-vehicle-match-nav {{
  grid-area:match;
  width:100%;
  display:grid;
  grid-template-columns:auto minmax(0,1fr) auto;
  align-items:center;
  justify-content:stretch;
  gap:8px;
  flex:none;
}}
#fh6VehicleMatchState {{
  min-width:0;
  max-width:none;
  width:100%;
  text-align:left;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-variant-numeric:tabular-nums;
}}
#fh6VehicleMatchState[data-state="error"] {{
  font-weight:800;
}}

@media (max-width:760px) {{
  .fh6-my-design-head {{
    grid-template-columns:minmax(0,1fr);
    grid-template-areas:
      "heading"
      "jump"
      "nav";
    align-items:stretch;
  }}
  .fh6-my-design-jump {{
    grid-template-columns:auto minmax(0,1fr) auto;
    grid-template-areas:
      "label input action"
      "navigator navigator navigator"
      "match match match"
      "settings settings settings";
  }}
  .fh6-my-design-nav {{
    width:100%;
  }}
  #fh6VehicleMatchState {{
    white-space:normal;
  }}
}}


/* =======================================================================
   v0.4.57-r17 — 初期位置リセット標準値 / FH6マイデザイン説明整理
   ======================================================================= */
/* ESC後 500ms / RET後 800ms を標準値とし、FH6マイデザイン順の説明を段落化します。 */

/* =======================================================================
   v0.4.57-r16 — FH6移動設定の表示修正
   ======================================================================= */
/* ジャンプ欄のラベル指定を直下要素だけに限定し、設定項目の重なりを防止します。
   折りたたみ見出しもクリック可能と分かる表示へ変更します。 */

/* =======================================================================
   v0.4.59-r10 — FH6移動設定を全ソート共通表示
   ======================================================================= */
/* 設定UIは1個だけ保持し、ソート順に応じて表示先hostへDOM移動します。
   これによりFH6マイデザイン順とその他のソートで設定内容・移動計画が分岐しません。 */
.fh6-navigator-settings-host {{
  width:100%;
  min-width:0;
}}
.fh6-navigator-settings-my-design-host {{
  grid-area:settings;
}}
.fh6-navigator-settings-global-host {{
  margin:4px 1px 0;
}}
/* 旧compactルール body.compact details {{ display:none; }} の対象から、
   FH6移動設定だけを明示的に戻します。 */
body.compact #fh6NavigatorSettings {{
  display:block;
}}

/* =======================================================================
   v0.4.57-r10 — Navigator設定をHTMLへ統合
   ======================================================================= */
.fh6-navigator-settings {{
  grid-area:settings;
  width:100%;
  min-width:0;
  margin-top:1px;
  padding:0;
  border:1px solid var(--line);
  border-radius:10px;
  background:color-mix(in srgb, var(--surface) 94%, transparent);
}}
.fh6-navigator-settings > summary {{
  display:grid;
  grid-template-columns:auto auto minmax(0,1fr) auto;
  align-items:center;
  gap:8px;
  min-height:42px;
  cursor:pointer;
  padding:7px 10px;
  border-radius:9px;
  background:color-mix(in srgb, var(--accent) 6%, var(--surface));
  color:inherit;
  font-size:11px;
  font-weight:850;
  user-select:none;
  list-style:none;
  transition:background .14s ease, border-color .14s ease;
}}
.fh6-navigator-settings > summary::-webkit-details-marker {{ display:none; }}
.fh6-navigator-settings > summary::before {{
  content:"▶";
  grid-column:1;
  color:var(--accent);
  font-size:10px;
}}
.fh6-navigator-settings-title {{
  grid-column:2;
  white-space:nowrap;
}}
.fh6-navigator-plan-summary {{
  grid-column:3;
  min-width:0;
  padding:4px 7px;
  border-radius:8px;
  background:color-mix(in srgb, var(--accent) 7%, transparent);
  font-size:10.5px;
  line-height:1.3;
  font-weight:600;
  font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere;
}}
.fh6-navigator-plan-summary b {{ font-size:10.5px; }}
.fh6-navigator-settings > summary::after {{
  content:"設定を開く";
  grid-column:4;
  padding:3px 7px;
  border:1px solid color-mix(in srgb, var(--accent) 32%, var(--line));
  border-radius:999px;
  background:var(--surface);
  color:var(--muted);
  font-size:9.5px;
  font-weight:750;
  white-space:nowrap;
}}
.fh6-navigator-settings > summary:hover {{
  background:color-mix(in srgb, var(--accent) 12%, var(--surface));
}}
.fh6-navigator-settings[open] > summary {{
  border-bottom:1px solid var(--line);
  border-radius:9px 9px 0 0;
  background:color-mix(in srgb, var(--accent) 10%, var(--surface));
}}
.fh6-navigator-settings[open] > summary::before {{ content:"▼"; }}
.fh6-navigator-settings[open] > summary::after {{ content:"設定を閉じる"; }}
.fh6-navigator-settings-body {{
  display:grid;
  grid-template-columns:repeat(4,minmax(120px,1fr)) auto;
  gap:7px;
  align-items:end;
  padding:8px 9px 9px;
}}
.fh6-navigator-setting {{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  gap:3px 5px;
  align-items:center;
  min-width:0;
}}
.fh6-navigator-setting > span:first-child {{
  grid-column:1 / -1;
  color:var(--muted);
  font-size:9.5px;
  line-height:1.25;
}}
.fh6-navigator-setting input {{
  width:100%;
  min-width:0;
  min-height:30px;
  padding:4px 7px;
  font-size:11px;
  font-variant-numeric:tabular-nums;
}}
.fh6-navigator-setting .unit {{
  font-size:10px;
  color:var(--muted);
}}
.fh6-navigator-reset-option {{
  grid-column:1 / -1;
  display:flex;
  align-items:center;
  gap:7px;
  min-height:28px;
  font-size:10.5px;
  color:var(--text);
}}
.fh6-navigator-reset-option input {{ width:auto; min-height:auto; }}
.fh6-navigator-settings-actions {{
  display:flex;
  gap:5px;
  align-items:center;
}}
#fh6NavigatorSettingsSync,
#fh6NavigatorSettingsReset {{
  min-height:30px;
  padding:4px 8px;
  font-size:10px;
  white-space:nowrap;
}}
#fh6NavigatorSettingsSync {{
  border-color:color-mix(in srgb, var(--accent) 42%, var(--line));
  background:color-mix(in srgb, var(--accent) 8%, var(--surface));
}}
@media (max-width:900px) {{
  .fh6-navigator-settings > summary {{ grid-template-columns:auto auto minmax(0,1fr); }}
  .fh6-navigator-settings > summary::after {{ display:none; }}
  .fh6-navigator-settings-body {{ grid-template-columns:repeat(2,minmax(120px,1fr)); }}
  .fh6-navigator-settings-actions {{ width:100%; }}
  #fh6NavigatorSettingsSync, #fh6NavigatorSettingsReset {{ flex:1 1 0; }}
}}
@media (max-width:540px) {{
  .fh6-navigator-settings > summary {{
    grid-template-columns:auto minmax(0,1fr);
    align-items:start;
  }}
  .fh6-navigator-settings-title {{ grid-column:2; }}
  .fh6-navigator-plan-summary {{ grid-column:1 / -1; }}
  .fh6-navigator-settings-body {{ grid-template-columns:1fr 1fr; }}
}}

/* =======================================================================
   v0.4.58-r09 — FH6移動対象番号の操作領域を明確化
   ======================================================================= */
/* 実スロット番号と列+U/D位置を「FH6移動対象」という一つの操作グループとして
   見せ、番号がクリック可能な選択ボタンであることを初見でも判断しやすくします。 */
.fh6-move-target-group {{
  display:inline-flex;
  align-items:stretch;
  flex-wrap:nowrap;
  gap:0;
  width:max-content;
  max-width:100%;
  overflow:hidden;
  min-height:28px;
  border:1px solid color-mix(in srgb, var(--accent) 48%, var(--line));
  border-radius:10px;
  background:color-mix(in srgb, var(--accent) 5%, var(--surface));
  box-shadow:var(--shadow-xs);
}}
.fh6-move-target-caption,
.fh6-location-caption {{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:3px 7px;
  background:color-mix(in srgb, var(--accent) 11%, var(--surface));
  color:var(--accent);
  font-size:9.5px;
  font-weight:850;
  line-height:1.2;
  white-space:nowrap;
}}
.fh6-move-target-caption {{
  border-right:1px solid color-mix(in srgb, var(--accent) 30%, var(--line));
}}
.topline .fh6-move-target-group .pill.fh6-move-target-trigger {{
  min-height:28px;
  margin:0;
  border:0;
  border-radius:0;
  background:transparent;
  box-shadow:none;
  text-decoration:none;
}}
.topline .fh6-move-target-group .pill.fh6-move-target-trigger + .pill.fh6-move-target-trigger {{
  border-left:1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
}}
.topline .fh6-move-target-group .pill.fh6-move-target-trigger:hover:not(:disabled) {{
  background:var(--accent-soft);
}}
.topline .fh6-move-target-group .pill.fh6-move-target-trigger:focus-visible,
.fh6-location-button:focus-visible {{
  position:relative;
  z-index:1;
  outline:2px solid var(--accent);
  outline-offset:-2px;
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]),
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) {{
  border-color:var(--accent);
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 12%, transparent);
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-caption,
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-caption {{
  background:var(--accent);
  color:white;
}}
/* r09 rev2: 選択状態はグループ全体で一度だけ示します。
   各番号の後ろへ「移動対象」を重複表示しません。 */
.fh6-move-target-group .fh6-move-target-trigger[aria-pressed="true"],
.fh6-location-buttons .fh6-location-button[aria-pressed="true"] {{
  background:transparent;
  box-shadow:none;
  color:var(--accent);
  font-weight:850;
}}
.fh6-move-target-trigger[aria-pressed="true"]::after,
.fh6-location-button[aria-pressed="true"]::after {{
  content:none !important;
  display:none !important;
}}
.fh6-location-buttons {{
  gap:0 !important;
  overflow:hidden;
  width:max-content;
  max-width:100%;
  border:1px solid color-mix(in srgb, var(--accent) 48%, var(--line));
  border-radius:10px;
  background:color-mix(in srgb, var(--accent) 5%, var(--surface));
  box-shadow:var(--shadow-xs);
}}
.fh6-location-caption {{
  border-right:1px solid color-mix(in srgb, var(--accent) 30%, var(--line));
}}
.fh6-location-buttons .fh6-location-button {{
  min-height:28px;
  margin:0;
  border:0;
  border-radius:0;
  background:transparent;
  text-decoration:none;
}}
.fh6-location-buttons .fh6-location-button + .fh6-location-button {{
  border-left:1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
}}
.fh6-location-buttons .fh6-location-button:hover:not(:disabled) {{
  background:var(--accent-soft);
}}
@media (max-width:540px) {{
  .fh6-move-target-caption, .fh6-location-caption {{
    padding-inline:6px;
    font-size:9px;
  }}
}}

/* =======================================================================
   v0.4.57-r23 — リリース前微調整
   ======================================================================= */
/* 左循環後の追加待ち既定値を400msへ更新し、ヘルプのFH6マイデザイン順を
   機能別の段落に分けて読みやすくします。 */

/* =======================================================================
   v0.4.57-r22 — リリース前UX仕上げ
   ======================================================================= */
/* FH6位置番号は「情報」だけでなくクリック可能な移動対象選択ボタンであることが
   初見でも分かるよう、通常時から控えめにアクセントを付けます。 */
.fh6-move-target-trigger:not(:disabled),
.fh6-location-button:not(:disabled) {{
  border-color:color-mix(in srgb, var(--accent) 34%, var(--line));
  background:color-mix(in srgb, var(--accent) 5%, var(--surface));
  text-decoration-line:underline;
  text-decoration-style:dotted;
  text-decoration-thickness:1px;
  text-underline-offset:2px;
}}
.fh6-move-target-trigger:hover:not(:disabled),
.fh6-location-button:hover:not(:disabled) {{
  text-decoration-style:solid;
  text-decoration-thickness:1.5px;
}}
.fh6-move-target-trigger[aria-pressed="true"],
.fh6-location-button[aria-pressed="true"] {{
  text-decoration:none;
}}

.help-fh6-move-workflow {{
  margin:0 0 14px;
  padding:12px 14px;
  border:1px solid color-mix(in srgb, var(--accent) 32%, var(--line));
  border-radius:14px;
  background:color-mix(in srgb, var(--accent-soft) 62%, var(--surface));
  box-shadow:var(--shadow-xs);
}}
.help-fh6-move-workflow h4 {{
  margin:0 0 7px;
  font-size:13px;
}}
.help-sort-fh6-detail p {{
  margin:0;
  line-height:1.65;
}}
.help-sort-fh6-detail p + p {{
  margin-top:9px;
  padding-top:9px;
  border-top:1px dashed var(--line);
}}
.help-sort-fh6-detail b {{
  line-height:1.45;
}}
.help-fh6-move-workflow ol {{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:7px;
  margin:0;
  padding:0;
  list-style:none;
  counter-reset:fh6-move-step;
}}
.help-fh6-move-workflow li {{
  position:relative;
  min-width:0;
  padding:8px 9px 8px 35px;
  border:1px solid var(--line);
  border-radius:10px;
  background:color-mix(in srgb, var(--surface-elevated) 92%, transparent);
  font-size:11px;
  line-height:1.5;
  counter-increment:fh6-move-step;
}}
.help-fh6-move-workflow li::before {{
  content:counter(fh6-move-step);
  position:absolute;
  left:8px;
  top:8px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:20px;
  height:20px;
  border-radius:999px;
  background:var(--accent);
  color:white;
  font-size:10px;
  font-weight:900;
}}
@media (max-width:680px) {{
  .help-fh6-move-workflow ol {{ grid-template-columns:1fr; }}
}}

/* =======================================================================
   v0.4.57-r21 — FH6移動ショートカット / 移動対象表示
   ======================================================================= */
/* r21で導入した番号ごとの「移動対象」バッジは、r09 rev2で操作グループ全体の
   アクセント表示へ置き換えました。 */

/* =======================================================================
   v0.4.57-r20 — Organizer全体のFH6移動対象
   ======================================================================= */
.topline .pill.my-design-index.fh6-move-target-trigger,
.topline .pill.fh6-my-design-position.fh6-move-target-trigger {{
  display:inline-flex !important;
  align-items:center;
  justify-content:center;
  min-height:28px;
  cursor:pointer;
  font-variant-numeric:tabular-nums;
}}
.fh6-move-target-trigger:hover:not(:disabled),
.fh6-location-button:hover:not(:disabled) {{
  border-color:color-mix(in srgb, var(--accent) 60%, var(--line));
  background:var(--accent-soft);
}}
.fh6-move-target-trigger[aria-pressed="true"],
.fh6-location-button[aria-pressed="true"] {{
  border-color:var(--accent);
  background:var(--accent-soft);
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 12%, transparent);
  font-weight:850;
}}
.fh6-move-target-trigger:disabled {{
  cursor:default;
  opacity:.62;
}}
.fh6-global-move-bar {{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:8px;
  margin:4px 1px 0;
  padding:6px 8px;
  border:1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
  border-radius:11px;
  background:color-mix(in srgb, var(--accent-soft) 50%, var(--surface));
  box-shadow:var(--shadow-xs);
  font-size:10.5px;
}}
.fh6-global-move-target {{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
#fh6GlobalMoveButton {{ min-height:32px; padding:5px 9px; font-size:11px; }}
body.fh6-my-design-view-mode .fh6-global-move-bar {{ display:none !important; }}
.fh6-location-buttons {{ display:flex; flex-wrap:wrap; gap:5px; align-items:center; }}
.fh6-location-button {{
  min-height:28px;
  padding:4px 7px;
  border-radius:999px;
  font-size:10.5px;
  font-weight:800;
  font-variant-numeric:tabular-nums;
}}
.compare-item.fh6-move-target-selected {{
  outline:3px solid var(--accent);
  outline-offset:1px;
}}
#compareFh6Move, #exactDuplicateFh6Move {{
  border-color:color-mix(in srgb, var(--accent) 42%, var(--line));
}}
@media (max-width:620px) {{
  .fh6-global-move-bar {{ align-items:stretch; flex-direction:column; }}
  .fh6-global-move-target {{ white-space:normal; }}
  #fh6GlobalMoveButton {{ width:100%; }}
}}

/* =======================================================================
   v0.4.58-r12 rev2 — FH6移動対象の選択表示をグループ全体へ統一
   ======================================================================= */
/* 通常カードと比較画面のどちらでも、選択中は見出しだけでなく
   FH6移動グループ全体を同じアクセント色で塗り、一体の操作として見せます。 */
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]),
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) {{
  background:var(--accent);
  border-color:var(--accent);
  color:white;
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-caption,
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-caption,
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-trigger,
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-button {{
  background:transparent;
  color:white;
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-caption,
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-caption {{
  border-right-color:color-mix(in srgb, white 32%, transparent);
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-trigger + .fh6-move-target-trigger,
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-button + .fh6-location-button {{
  border-left-color:color-mix(in srgb, white 32%, transparent);
}}
.fh6-move-target-group:has(.fh6-move-target-trigger[aria-pressed="true"]) .fh6-move-target-trigger:hover:not(:disabled),
.fh6-location-buttons:has(.fh6-location-button[aria-pressed="true"]) .fh6-location-button:hover:not(:disabled) {{
  background:color-mix(in srgb, white 14%, transparent);
  color:white;
}}

/* =======================================================================
   v0.4.57-r09 — Navigator Bridge for FH6連携
   ======================================================================= */
/* Organizer全体で選択したFH6移動対象をNavigator Bridgeへ渡します。
   仮削除後の現在実スロット番号と最終実スロット数を使うため、どの並び順・比較画面でもFH6側の現在位置と揃います。 */
#fh6MyDesignTrack .card.fh6-navigator-selected {{
  box-shadow:0 0 0 2px color-mix(in srgb, var(--accent) 42%, transparent), var(--shadow-xs);
}}

/* =======================================================================
   v0.4.57-r08 — FH6削除済み（仮） + 実スロット再計算
   ======================================================================= */
.fh6-my-design-heading-line {{
  display:flex;
  align-items:center;
  gap:8px;
  flex-wrap:wrap;
}}
.fh6-my-design-heading-line h2 {{ margin:0; }}
.fh6-temp-delete-review-host {{
  min-width:0;
}}
.fh6-temp-delete-review-global-host {{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  min-height:0;
  margin:4px 1px 0;
}}
.fh6-temp-delete-review-global-host:empty,
.fh6-temp-delete-review-global-host:has(> #fh6TempDeletedReview.hidden) {{
  display:none;
}}
#fh6TempDeletedReview {{
  border:1px solid color-mix(in srgb, #b42318 35%, var(--line));
  background:color-mix(in srgb, #b42318 8%, var(--surface));
  color:color-mix(in srgb, #b42318 85%, var(--text));
  font-weight:800;
}}
#fh6TempDeletedReview.hidden {{ display:none; }}
.fh6-temp-delete-action {{
  border-color:color-mix(in srgb, #b42318 28%, var(--line)) !important;
  background:color-mix(in srgb, #b42318 6%, var(--surface)) !important;
  color:color-mix(in srgb, #b42318 82%, var(--text)) !important;
}}
.fh6-temp-delete-list {{
  display:grid;
  gap:8px;
  margin-top:10px;
}}
.fh6-temp-delete-row {{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  gap:10px;
  align-items:center;
  padding:10px;
  border:1px solid var(--line);
  border-radius:10px;
  background:var(--surface);
}}
.fh6-temp-delete-row-main {{ min-width:0; }}
.fh6-temp-delete-row-title {{
  font-weight:800;
  overflow-wrap:anywhere;
}}
.fh6-temp-delete-row-meta {{
  margin-top:3px;
  color:var(--muted);
  font-size:11px;
  font-variant-numeric:tabular-nums;
}}
.fh6-temp-delete-empty {{
  padding:14px;
  border:1px dashed var(--line);
  border-radius:10px;
  color:var(--muted);
}}
.fh6-temp-delete-modal-actions {{
  display:flex;
  justify-content:flex-end;
  gap:8px;
  margin-top:10px;
}}
@media (max-width:760px) {{
  .fh6-temp-delete-row {{ grid-template-columns:minmax(0,1fr); }}
  .fh6-temp-delete-row button {{ width:100%; }}
}}


/* =======================================================================
   v0.4.59-r07 — 高密度コンパクト表示 + 表示項目選択
   ======================================================================= */
.compact-display-settings {{
  margin-top:8px;
  padding:0;
  border:1px solid var(--line);
  border-radius:10px;
  background:color-mix(in srgb, var(--surface) 92%, transparent);
}}
.compact-display-settings > summary {{
  min-height:32px;
  padding:7px 9px;
  cursor:pointer;
  font-size:11px;
  font-weight:800;
}}
.compact-display-settings-body {{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:5px 8px;
  padding:0 9px 9px;
}}
.compact-display-settings-body label {{
  display:flex;
  align-items:center;
  gap:6px;
  min-width:0;
  font-size:10.5px;
}}
.compact-display-settings-body input {{
  flex:0 0 auto;
}}
.compact-display-required {{
  grid-column:1 / -1;
  line-height:1.45;
}}
body.compact .compact-display-settings {{
  display:block !important;
}}

body.compact:not(.fh6-my-design-view-mode) .grid {{
  grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
  gap:6px;
}}
body.compact:not(.fh6-my-design-view-mode) .card {{
  border-radius:12px;
}}
body.compact:not(.fh6-my-design-view-mode) .card img,
body.compact:not(.fh6-my-design-view-mode) .card img.livery-image,
body.compact:not(.fh6-my-design-view-mode) .noimg {{
  aspect-ratio:2.7 / 1;
  border-radius:11px 11px 0 0;
}}
body.compact:not(.fh6-my-design-view-mode) .body {{
  padding:4px 5px 5px;
}}
body.compact:not(.fh6-my-design-view-mode) .topline {{
  gap:3px;
  margin-bottom:2px;
}}
body.compact:not(.fh6-my-design-view-mode) .topline .pill {{
  min-height:22px;
  padding:2px 5px;
  font-size:9px;
}}
body.compact:not(.fh6-my-design-view-mode) .card-vehicle-sort-only {{
  margin:2px 0 1px;
  font-size:10.5px;
  line-height:1.15;
}}
body.compact:not(.fh6-my-design-view-mode) .card h4 {{
  margin:2px 0 1px;
  font-size:11.5px;
  line-height:1.15;
}}
body.compact:not(.fh6-my-design-view-mode) .card h4 .title-filter {{
  display:block;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}
body.compact:not(.fh6-my-design-view-mode) .card dl {{
  display:block;
  margin:2px 0 1px;
  font-size:9.5px;
  line-height:1.2;
}}
body.compact:not(.fh6-my-design-view-mode) .card dl dt {{
  display:none;
}}
body.compact:not(.fh6-my-design-view-mode) .card dl dd {{
  display:block;
  min-height:0;
  margin:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}
body.compact:not(.fh6-my-design-view-mode) .card dl dd.fh6-normal-creator-row::before {{
  content:"@ ";
  opacity:.6;
}}
body.compact:not(.fh6-my-design-view-mode) .compact-detail-value.compact-optional-acquired::before {{
  content:"取得 ";
  opacity:.6;
}}
body.compact:not(.fh6-my-design-view-mode) .compact-detail-value.compact-optional-vinyl::before {{
  content:"バイナル ";
  opacity:.6;
}}
body.compact:not(.fh6-my-design-view-mode) .card .decision {{
  gap:3px;
  margin-top:3px;
}}
body.compact:not(.fh6-my-design-view-mode) .card .decision button {{
  min-height:25px;
  padding:2px 1px;
  border-radius:7px;
  font-size:9.5px;
  line-height:1.05;
}}
body.compact:not(.fh6-my-design-view-mode) .compact-optional-selection,
body.compact:not(.fh6-my-design-view-mode) .fh6-move-target-group,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-make-year,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-asset,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-description,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-acquired,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-vinyl,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-personal,
body.compact:not(.fh6-my-design-view-mode) .compact-optional-flags {{
  display:none !important;
}}
body.compact.compact-show-selection:not(.fh6-my-design-view-mode) .compact-optional-selection {{
  display:inline-flex !important;
}}
body.compact.compact-show-fh6:not(.fh6-my-design-view-mode) .fh6-move-target-group {{
  display:inline-flex !important;
}}
body.compact.compact-show-make-year:not(.fh6-my-design-view-mode) .compact-optional-make-year,
body.compact.compact-show-asset:not(.fh6-my-design-view-mode) .compact-optional-asset,
body.compact.compact-show-description:not(.fh6-my-design-view-mode) .compact-optional-description {{
  display:block !important;
}}
body.compact.compact-show-acquired:not(.fh6-my-design-view-mode) .compact-optional-acquired.compact-detail-value,
body.compact.compact-show-vinyl:not(.fh6-my-design-view-mode) .compact-optional-vinyl.compact-detail-value {{
  display:block !important;
}}
body.compact.compact-show-personal:not(.fh6-my-design-view-mode) .compact-optional-personal {{
  display:block !important;
}}
body.compact.compact-show-flags:not(.fh6-my-design-view-mode) .compact-optional-flags {{
  display:inline-flex !important;
}}
@media (max-width:600px) {{
  body.compact:not(.fh6-my-design-view-mode) .grid {{
    grid-template-columns:1fr;
    gap:8px;
  }}
  .compact-display-settings-body {{
    grid-template-columns:1fr;
  }}
  .compact-display-required {{
    grid-column:auto;
  }}
}}


/* =======================================================================
   v0.4.59-r09 — デスクトップ横幅をカード領域へ最大活用
   ======================================================================= */
/* 1800pxの上限を撤廃し、横長・高解像度ディスプレイでもブラウザの利用可能幅を
   カード一覧へそのまま割り当てます。カード幅やモバイル時の1列表示は既存ルールを維持し、
   広い画面では列数だけを自然に増やします。 */
@media (min-width:901px) {{
  main {{
    width:100%;
    max-width:none;
    margin-left:0;
    margin-right:0;
  }}
}}

/* =======================================================================
   v0.4.59-r08 — FH6マイデザイン順のコンパクト幅対応
   ======================================================================= */
/* FH6との目視照合に必要な実スロット / U・D位置 / 車種 / タイトル / 作成者 /
   FH6日付は残しつつ、コンパクト表示では専用列をおおむね従来の2/3へ縮小します。
   150px固定にはせず、タイトルと2つの位置番号の可読性を守るため180–230pxとします。 */
body.compact.fh6-my-design-view-mode .fh6-my-design-column {{
  flex-basis:clamp(180px,15vw,230px);
  width:clamp(180px,15vw,230px);
  gap:6px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-empty-slot {{
  min-height:125px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .card {{
  border-radius:12px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .card img,
body.compact.fh6-my-design-view-mode .fh6-my-design-column .card img.livery-image,
body.compact.fh6-my-design-view-mode .fh6-my-design-column .noimg {{
  aspect-ratio:2.55 / 1;
  border-radius:11px 11px 0 0;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .body {{
  padding:4px 5px 5px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .topline {{
  gap:2px;
  margin-bottom:1px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-move-target-caption {{
  display:none;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-move-target-group {{
  min-height:22px;
  border-radius:7px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .topline .pill.fh6-move-target-trigger {{
  min-width:0;
  min-height:22px;
  padding:2px 5px;
  font-size:8.5px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .card-vehicle-sort-only {{
  margin:1px 0;
  font-size:9.5px;
  line-height:1.1;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column h4 {{
  margin:3px 0 1px;
  height:2.2em;
  font-size:10.5px;
  line-height:1.1;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-creator-display,
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-display-date {{
  margin:1px 0 2px;
  font-size:9.5px;
  line-height:1.1;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .vehicle-meta {{
  font-size:9px;
}}
@media (max-width:760px) {{
  body.compact.fh6-my-design-view-mode .fh6-my-design-column {{
    flex-basis:min(68vw,230px);
    width:min(68vw,230px);
  }}
}}

/* =======================================================================
   v0.4.59-r11 — FH6マイデザイン順を通常コンパクト相当まで高密度化
   ======================================================================= */
/* 状態バッジをFH6位置番号とは別行へ移し、番号行の幅に引きずられず150px級まで縮小します。
   通常表示ではwrapperをdisplay:contentsにして従来のtopline配置を維持します。 */
.fh6-secondary-badges {{
  display:contents;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column {{
  flex-basis:clamp(150px,12vw,180px);
  width:clamp(150px,12vw,180px);
  gap:5px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .topline {{
  align-items:flex-start;
  gap:2px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-move-target-group {{
  order:1;
  flex:0 0 auto;
  max-width:100%;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .compact-optional-selection {{
  order:2;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-secondary-badges {{
  order:3;
  flex:1 0 100%;
  min-width:0;
  display:flex;
  flex-wrap:wrap;
  align-items:center;
  gap:2px;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-secondary-badges > .pill {{
  min-width:0;
  max-width:100%;
  min-height:19px;
  padding:1px 4px;
  font-size:8px;
  line-height:1.05;
}}
body.compact.fh6-my-design-view-mode .fh6-my-design-column .fh6-creator-display {{
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}
@media (max-width:760px) {{
  body.compact.fh6-my-design-view-mode .fh6-my-design-column {{
    flex-basis:min(62vw,180px);
    width:min(62vw,180px);
  }}
}}


/* =======================================================================
   v0.4.59-r13 — ダークテーマのアクセント文字可読性
   ======================================================================= */
/* ライトテーマや選択中のアクセント背景は従来どおりに保ち、
   ダークテーマ上で文字として使う青だけを明るくして判読性を上げます。 */
body.dark-theme {{
  --accent-text:#b7c5ff;
}}
body.dark-theme .stat-filter-hint,
body.dark-theme .fh6-move-target-caption,
body.dark-theme .fh6-location-caption {{
  color:var(--accent-text);
}}

</style>
</head>
<body>
<header>
  <section class="hero card-first-hero">
    <div class="hero-brand">
      <h1>Livery Organizer for FH6 <span class="pill strong">v{VERSION}</span></h1>
      <div class="hero-sub">ダウンロードしたペイントの整理ツール</div>
    </div>
    <div class="stats-grid" aria-label="ペイント統計">
      <div class="stat-card"><div class="stat-value">{len(records):,}</div><div class="stat-label">ペイント数</div></div>
      <button id="vehicleStatAction" class="stat-card stat-filter-card" type="button"
        data-stat-filter-target="vehicleFilter" aria-expanded="false" aria-controls="statQuickFilterPanel"
        title="車種で絞り込み">
        <span class="stat-value">{stats.get("unique_car_ids", 0):,}</span><span class="stat-label">車種数</span>
        <span id="vehicleStatHint" class="stat-filter-hint">絞り込み ▾</span>
      </button>
      <button id="makeStatAction" class="stat-card stat-filter-card" type="button"
        data-stat-filter-target="makeFilter" aria-expanded="false" aria-controls="statQuickFilterPanel"
        title="メーカーで絞り込み">
        <span class="stat-value">{len(unique_makes):,}</span><span class="stat-label">メーカー</span>
        <span id="makeStatHint" class="stat-filter-hint">絞り込み ▾</span>
      </button>
      <button id="creatorStatAction" class="stat-card stat-filter-card" type="button"
        data-stat-filter-target="creatorFilter" aria-expanded="false" aria-controls="statQuickFilterPanel"
        title="作成者で絞り込み">
        <span class="stat-value">{len(unique_creators):,}</span><span class="stat-label">作成者数</span>
        <span id="creatorStatHint" class="stat-filter-hint">絞り込み ▾</span>
      </button>
      <button id="yearStatAction" class="stat-card stat-filter-card" type="button"
        data-stat-filter-target="yearFilter" aria-expanded="false" aria-controls="statQuickFilterPanel"
        title="年式で絞り込み">
        <span class="stat-value">{f"{oldest_year}–{newest_year}" if oldest_year and newest_year else "—"}</span><span class="stat-label">年式</span>
        <span id="yearStatHint" class="stat-filter-hint">絞り込み ▾</span>
      </button>
      <button id="undecidedStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="未決定のみ表示">
        <span class="stat-value" id="statUndecided">0</span><span class="stat-label">未決定</span>
      </button>
      <button id="favoriteStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="お気に入りのみ表示">
        <span class="stat-value" id="statFavorite">0</span><span class="stat-label">お気に入り</span>
      </button>
      <button id="reviewStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="後で確認のみ表示">
        <span class="stat-value" id="statReview">0</span><span class="stat-label">後で確認</span>
      </button>
      <button id="newStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="新規のみ表示">
        <span class="stat-value" id="statNew">0</span><span class="stat-label">新規</span>
      </button>
      <button id="similarStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="類似候補のみ表示">
        <span class="stat-value" id="statSimilar">0</span><span class="stat-label">類似候補</span>
      </button>
      <button id="exactDuplicateStatAction" class="stat-card live-stat stat-filter-card" type="button"
        aria-pressed="false" title="現在のFH6に同一内容で複数スロット存在するペイントだけを表示">
        <span class="stat-value" id="statExactDuplicate">{stats.get("fh6_exact_duplicate_groups", 0)}組</span><span class="stat-label">再DL重複</span>
      </button>
    </div>
  </section>

  <div id="statQuickFilterPanel" class="stat-quick-filter-panel hidden" aria-hidden="true">
    <div class="stat-quick-filter-head">
      <b id="statQuickFilterTitle">クイック絞り込み</b>
      <span class="small">同じ項目内はOR。候補をクリックして追加 / 解除できます</span>
    </div>
    <input id="statQuickFilterSearch" class="stat-quick-filter-search" type="search" placeholder="候補を検索…" aria-label="クイック絞り込み候補を検索">
    <div class="stat-quick-filter-actions">
      <button id="statQuickSelectedOnly" type="button">選択中のみ</button>
      <button id="statQuickSelectVisible" type="button">表示候補をすべて選択</button>
      <button id="statQuickClear" type="button">この項目を解除</button>
    </div>
    <div id="statQuickFilterChoices" class="stat-quick-choices" role="listbox" aria-multiselectable="true" aria-label="絞り込み候補"></div>
    <select id="vehicleFilter" class="stat-quick-select hidden" aria-label="車種" multiple>
      <option value="all">車種 すべて</option>
    </select>
    <select id="makeFilter" class="stat-quick-select hidden" aria-label="メーカー" multiple>
      <option value="all">メーカー: すべて</option>
    </select>
    <select id="creatorFilter" class="stat-quick-select hidden" aria-label="作成者" multiple>
      <option value="all">作成者: すべて</option>
    </select>
    <select id="yearFilter" class="stat-quick-select hidden" aria-label="年式" multiple>
      <option value="all">年式: すべて</option>
    </select>
  </div>

  <div class="mobile-stats-summary">
    <strong>{len(records):,}</strong>件のペイント /
    <strong>{stats.get("unique_car_ids", 0):,}</strong>車種
  </div>
  <div class="mobile-quick-filters" aria-label="クイック絞り込み">
    <button type="button" class="mobile-stat-filter-trigger" data-stat-filter-target="vehicleFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">車種 ▾</button>
    <button type="button" class="mobile-stat-filter-trigger" data-stat-filter-target="makeFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">メーカー ▾</button>
    <button type="button" class="mobile-stat-filter-trigger" data-stat-filter-target="creatorFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">作成者 ▾</button>
    <button type="button" class="mobile-stat-filter-trigger" data-stat-filter-target="yearFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">年式 ▾</button>
  </div>
  <div class="mobile-actions">
    <button id="mobileFilterToggle" type="button" aria-expanded="false">絞り込み・並び替え</button>
    <span id="mobileFilterSummary">条件なし</span>
  </div>
  <div class="toolbar card-first-toolbar" id="filterToolbar">
    <input id="q" type="search" placeholder='検索…  例 v:0363 c:creator n:"title" t:tag'>
    <select id="sortOrder" aria-label="並び順">
      <optgroup label="基本">
        <option value="manufacturer">メーカー順</option>
        <option value="vehicle">車名順</option>
        <option value="fh6-my-designs">FH6マイデザイン順</option>
        <option value="my-designs">マイデザイン順</option>
        <option value="creator">作成者順</option>
        <option value="title">タイトル順</option>
      </optgroup>
      <optgroup label="日時・年式">
        <option value="timestamp-desc">取得日時:新しい順</option>
        <option value="timestamp-asc">取得日時:古い順</option>
        <option value="year-desc">年式:新しい順</option>
        <option value="year-asc">年式:古い順</option>
      </optgroup>
      <optgroup label="整理">
        <option value="decision">整理状態順</option>
        <option value="progress-asc">整理進捗:未着手→完了順</option>
        <option value="progress-desc">整理進捗:完了→未着手順</option>
      </optgroup>
      <optgroup label="件数・分析">
        <option value="paint-desc">ペイント件数:多い順</option>
        <option value="paint-asc">ペイント件数:少ない順</option>
        <option value="vinyl-desc">バイナル数:多い順</option>
        <option value="vinyl-asc">バイナル数:少ない順</option>
      </optgroup>
    </select>
    <button id="filterPanelToggle" class="filter-panel-trigger" type="button"
      aria-expanded="false" aria-controls="filterPanel">絞り込み</button>
    <button id="clearFilters" type="button">絞り込み解除</button>
    <button id="reportInfoAction" type="button" aria-expanded="false" aria-controls="reportInfoPanel">レポート情報</button>
    <button id="secondaryActionsToggle" class="secondary-actions-trigger" type="button"
      aria-expanded="false" aria-controls="secondaryActions">その他の操作</button>
    <button id="helpAction" class="help-action" type="button">ヘルプ</button>

    <div id="filterPanel" class="filter-panel hidden" aria-hidden="true">
      <div class="filter-panel-tabs" role="tablist" aria-label="絞り込みメニュー">
        <button id="filterConditionsTab" class="filter-panel-tab active" type="button" role="tab"
          data-filter-panel-tab="conditions" aria-selected="true" aria-controls="filterPanelConditions">条件</button>
        <button id="filterBulkTab" class="filter-panel-tab" type="button" role="tab"
          data-filter-panel-tab="bulk" aria-selected="false" aria-controls="filterPanelBulk">選択・一括</button>
      </div>

      <div id="filterPanelConditions" class="filter-panel-pane filter-condition-pane" role="tabpanel" aria-labelledby="filterConditionsTab">
        <div class="filter-multi-note">候補はクリックで追加 / 解除できます。同じ項目内はOR、異なる項目間はANDです。タグだけはOR / ANDを切り替えられます。</div>

        <section class="creator-summary creator-filter-summary" aria-labelledby="creatorFilterSummaryTitle">
          <div class="creator-summary-content">
            <div class="detail-filter-head">
              <b id="creatorFilterSummaryTitle">作成者クイック絞り込み</b>
              <span class="small">検索・上位候補から直接選択</span>
            </div>
            <div class="creator-search-row">
              <input id="creatorQuickSearch" type="search" placeholder="作成者を検索…" aria-label="作成者を検索">
              <span id="creatorSearchCount" class="small"></span>
            </div>
            {creator_summary_html if creator_summary_html else f'<span class="small">{html.escape(report_fallback_creator)}</span>'}
          </div>
        </section>

        <select id="decisionFilter" class="detail-filter-source hidden" aria-label="整理状態" multiple>
          <option value="all">すべて</option>
          <option value="undecided">未決定</option>
          <option value="keep">残す</option>
          <option value="delete">削除候補</option>
        </select>
        <div class="compact-filter-trigger-card">
          <div class="detail-filter-head"><b>整理状態</b><span class="small">複数選択</span></div>
          <button id="decisionQuickAction" class="detail-filter-quick-trigger" type="button"
            data-stat-filter-target="decisionFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">
            <span>整理状態を選択 ▾</span>
          </button>
        </div>

        <select id="progressFilter" class="detail-filter-source hidden" aria-label="車種の整理進捗" multiple>
          <option value="all">整理進捗: すべて</option>
          <option value="none">整理進捗: 未着手 (0%)</option>
          <option value="partial">整理進捗: 整理中 (1–99%)</option>
          <option value="complete">整理進捗: 完了 (100%)</option>
        </select>
        <div class="compact-filter-trigger-card">
          <div class="detail-filter-head"><b>車種の整理進捗</b><span class="small">複数選択</span></div>
          <button id="progressQuickAction" class="detail-filter-quick-trigger" type="button"
            data-stat-filter-target="progressFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">
            <span>整理進捗を選択 ▾</span>
          </button>
        </div>

        <select id="paintCountFilter" class="detail-filter-source hidden" aria-label="車種ごとのペイント件数" multiple>
          <option value="all">ペイント件数: すべて</option>
          {paint_count_options_html}
        </select>
        <div class="compact-filter-trigger-card paint-count-quick-card">
          <div class="detail-filter-head">
            <b>ペイント件数</b>
            <span id="paintCountQuickCount" class="detail-filter-count"></span>
          </div>
          <button id="paintCountQuickAction" class="detail-filter-quick-trigger" type="button"
            data-stat-filter-target="paintCountFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">
            <span id="paintCountQuickHint">ペイント件数を選択 ▾</span>
          </button>
        </div>

        <select id="vinylCountFilter" class="detail-filter-source hidden" aria-label="旧バイナルしきい値" multiple>
          <option value="all">バイナル数: すべて</option>
        </select>
        <div class="range-filter-card">
          <div class="range-filter-head"><b>バイナル数</b><span id="vinylRangeCount" class="detail-filter-count"></span></div>
          <div class="range-filter-inputs">
            <input id="vinylMin" type="number" min="0" step="1" inputmode="numeric" placeholder="最小">
            <span>〜</span>
            <input id="vinylMax" type="number" min="0" step="1" inputmode="numeric" placeholder="最大">
          </div>
          <div class="detail-filter-actions" style="margin-top:6px;margin-bottom:0">
            <button id="vinylRangeClear" type="button">範囲を解除</button>
          </div>
        </div>

        <select id="tagFilter" class="detail-filter-source hidden" aria-label="タグ" multiple><option value="all">タグ: すべて</option></select>
        <div class="compact-filter-trigger-card compact-tag-card">
          <div class="detail-filter-head"><b>タグ</b><span class="small">複数選択</span></div>
          <div class="tag-match-mode" aria-label="タグ一致条件">
            <button id="tagModeOr" type="button" class="active">いずれか（OR）</button>
            <button id="tagModeAnd" type="button">すべて（AND）</button>
          </div>
          <button id="tagQuickAction" class="detail-filter-quick-trigger" type="button"
            data-stat-filter-target="tagFilter" aria-expanded="false" aria-controls="statQuickFilterPanel">
            <span>タグを選択 ▾</span>
          </button>
        </div>

        <div class="filter-quick-toggle-grid" aria-label="クイック条件">
          <button id="deleteReview" type="button">削除候補を確認</button>
          <button id="newOnly" type="button">新規のみ</button>
          <button id="similarOnly" type="button" title="類似候補を理由に関係なく表示">類似候補のみ</button>
          <button id="similarImageOnly" type="button" title="サムネイル完全一致の類似候補だけを表示">画像一致のみ</button>
          <button id="similarCreatorTitleOnly" type="button" title="作成者＋タイトル一致の類似候補だけを表示">同一作者・同名のみ</button>
          <button id="exactDuplicateOnly" type="button" title="現在のFH6に同一内容で複数スロット存在する再ダウンロード重複だけを表示">再DL重複のみ</button>
          <button id="favoriteOnly" type="button">お気に入りのみ</button>
          <button id="reviewOnly" type="button">後で確認のみ</button>
        </div>

        <div class="filter-preset-card">
          <input id="filterPresetName" type="text" placeholder="プリセット名">
          <button id="saveFilterPreset" type="button">現在条件を保存</button>
          <select id="filterPresetSelect" aria-label="絞り込みプリセット"><option value="">プリセットを選択…</option></select>
          <button id="applyFilterPreset" type="button">適用</button>
          <button id="deleteFilterPreset" type="button">削除</button>
        </div>
      </div>

      <div id="filterPanelBulk" class="filter-panel-pane filter-bulk-pane hidden" role="tabpanel" aria-labelledby="filterBulkTab">
        <section class="filter-bulk-group" aria-labelledby="filterSelectionTitle">
          <h4 id="filterSelectionTitle">選択</h4>
          <div class="filter-bulk-actions">
            <button id="selectVisible" type="button">表示中を選択</button>
            <button id="selectedOnly" type="button">選択中のみ</button>
            <button id="invertSelection" type="button">表示中の選択反転</button>
            <button id="clearSelection" type="button">選択解除</button>
            <button id="compareSelected" type="button" disabled title="2件以上選択すると比較できます">選択中を比較 (0件)</button>
          </div>
        </section>

        <section class="filter-bulk-group" aria-labelledby="filterDecisionBulkTitle">
          <h4 id="filterDecisionBulkTitle">一括判定</h4>
          <div class="filter-bulk-actions">
            <button id="bulkKeep" type="button">選択→残す</button>
            <button id="bulkDelete" type="button">選択→削除候補</button>
            <button id="bulkUndecided" type="button">選択→未決定</button>
          </div>
        </section>

        <section class="filter-bulk-group" aria-labelledby="filterMetaBulkTitle">
          <h4 id="filterMetaBulkTitle">一括メタデータ</h4>
          <div class="filter-bulk-actions">
            <button id="bulkFavorite" type="button">選択→お気に入り</button>
            <button id="bulkReview" type="button">選択→後で確認</button>
            <button id="bulkTag" type="button">選択→タグ管理</button>
          </div>
        </section>

        <section class="filter-bulk-group" aria-labelledby="filterHistoryBulkTitle">
          <h4 id="filterHistoryBulkTitle">操作</h4>
          <div class="filter-bulk-actions">
            <button id="undoAction" type="button" disabled>元に戻す</button>
            <button id="redoAction" type="button" disabled>やり直す</button>
          </div>
        </section>
      </div>
    </div>
    <div id="reportInfoPanel" class="summary report-info-panel hidden" aria-hidden="true">
      <div class="report-info-head">
        <div>
          <b>レポート情報</b>
          <span class="small">スキャン・保存・整理状況</span>
        </div>
      </div>
      <div class="report-info-tabs" role="tablist" aria-label="レポート情報メニュー">
        <button id="reportOverviewTab" class="report-info-tab active" type="button" role="tab"
          data-report-info-tab="overview" aria-selected="true" aria-controls="reportInfoOverview">概要・進捗</button>
        <button id="reportBackupTab" class="report-info-tab" type="button" role="tab"
          data-report-info-tab="backup" aria-selected="false" aria-controls="reportInfoBackup">バックアップ状態</button>
      </div>

      <div id="reportInfoOverview" class="report-info-pane" role="tabpanel" aria-labelledby="reportOverviewTab">
        <div class="report-overview-grid">
          <section class="report-meta-card" aria-label="スキャン情報">
            <dl class="report-meta-grid">
              <dt>保存領域</dt><dd><code>{html.escape(display_path_text(normpath(root)))}</code></dd>
              <dt>ペイント</dt><dd><b>{stats.get("unique_liveries", 0)}</b>件</dd>
              <dt>車種</dt><dd><b>{stats.get("unique_car_ids", 0)}</b>件</dd>
              <dt>履歴コピー</dt><dd><b>{stats.get("duplicate_snapshot_copies_removed", 0)}</b>件を非表示</dd>
              <dt>再DL完全一致</dt><dd><b>{stats.get("fh6_exact_duplicate_groups", 0)}</b>組 / {stats.get("fh6_exact_duplicate_cards", 0)}件（余分 {stats.get("fh6_exact_duplicate_instances", 0)}件）</dd>
              <dt>車両DB</dt><dd>{len(vehicle_db or {})}件{" / " + html.escape(display_path_text(normpath(game_root))) if game_root else " / FH6インストール先未指定"}</dd>
              <dt>最終スキャン</dt><dd>{html.escape(payload["generated_at"].replace("T", " "))}</dd>
              <dt>解析データ</dt><dd>{"data フォルダへ出力" if export_analysis_data else "未出力（通常モード）"}</dd>
              <dt>サムネイル</dt><dd>{"HTML内に埋め込み" if embed_images else "thumbnails フォルダ参照"}</dd>
              <dt>ビルド</dt><dd>v{VERSION}</dd>
              <dt>UI状態</dt><dd><span id="uiStatus">初期化中</span></dd>
              <dt>保存方式</dt><dd><span id="storageStatus">確認中</span></dd>
            </dl>
            <div id="runtimeErrorBanner" class="runtime-error hidden" role="alert">
              <span id="runtimeErrorMessage"></span>
              <button id="runtimeDiagnosticsAction" type="button">動作診断</button>
            </div>
            <div class="small report-info-safety">
              「残す / 削除候補 / 未決定」はこのブラウザのlocalStorageだけに保存されます。FH6のGameSaveには一切書き込みません。
            </div>
          </section>

          <section class="report-progress-card" aria-label="整理進捗">
            <div class="counterbar">
              <button class="counter counter-filter" type="button" data-state-filter="all">表示 <b id="visibleCount">0</b> / {len(records)}</button>
              <button class="counter counter-filter" type="button" data-state-filter="keep">残す <b id="keepCount">0</b></button>
              <button class="counter counter-filter" type="button" data-state-filter="delete">削除候補 <b id="deleteCount">0</b></button>
              <button class="counter counter-filter" type="button" data-state-filter="undecided">未決定 <b id="undecidedCount">0</b></button>
            </div>
            <div class="progress-row">
              <span>整理進捗 <b id="decisionProgress">0 / {len(records)}</b></span>
              <progress id="decisionProgressBar" max="{len(records)}" value="0"></progress>
              <span>選択中 <b id="selectedCount">0</b>件</span>
              <button id="showRemoved" type="button" title="保存済みの新規判定基準と今回のレポートの差分を確認します">前回との差分 新規 <b id="newDiffCount">0</b> / 消滅 <b id="removedCount">0</b></button>
            </div>
            <div class="progress-row scan-baseline-row">
              <span id="scanBaselineStatus" class="small">新規判定基準: 読み込み中</span>
              <button id="setScanBaseline" type="button">今回を新規判定の基準にする</button>
            </div>
          </section>

          <section id="startupReadinessPanel" class="startup-readiness-card" data-state="checking" aria-labelledby="startupReadinessTitle" aria-live="polite">
            <div class="startup-readiness-head">
              <b id="startupReadinessTitle">利用準備</b>
              <strong id="startupReadinessStatus" class="startup-readiness-status">確認中</strong>
            </div>
            <div class="startup-readiness-items">
              <div class="startup-readiness-item"><span>ブラウザ保存</span><b id="startupStorageStatus">確認中</b></div>
              <div class="startup-readiness-item"><span>レポートデータ</span><b id="startupDataStatus">確認中</b></div>
              <div class="startup-readiness-item"><span>サムネイル</span><b id="startupThumbnailStatus">確認中</b></div>
            </div>
            <div class="startup-readiness-foot">
              <span id="startupReadinessNote" class="small">レポートの利用準備を確認しています。</span>
              <div class="startup-readiness-actions">
                <button id="startupDiagnosticsAction" type="button">動作診断</button>
                <button id="startupHelpAction" type="button">使い方</button>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div id="reportInfoBackup" class="report-info-pane hidden" role="tabpanel" aria-labelledby="reportBackupTab">
        <section id="backupStatusPanel" class="backup-status-panel" aria-labelledby="backupStatusTitle" aria-live="polite">
          <div class="backup-status-head">
            <b id="backupStatusTitle">バックアップ状態</b>
            <span class="small">このブラウザで行った保存操作との比較</span>
          </div>
          <div class="backup-status-list">
            <div class="backup-status-row">
              <span class="backup-status-kind">ユーザーデータ</span>
              <b id="fullBackupStatus" class="backup-status-badge" data-state="none">未バックアップ</b>
              <span id="fullBackupTime" class="backup-status-time">前回保存: —</span>
            </div>
            <div class="backup-status-row">
              <span class="backup-status-kind">判定のみ</span>
              <b id="decisionBackupStatus" class="backup-status-badge" data-state="none">未バックアップ</b>
              <span id="decisionBackupTime" class="backup-status-time">前回保存: —</span>
            </div>
          </div>
          <div id="backupChangeSummary" class="backup-change-summary" data-state="none">
            <div class="backup-change-summary-head">
              <b>前回のユーザーデータ保存からの変更</b>
              <span id="backupChangeSummaryStatus" class="small">確認中</span>
            </div>
            <div class="backup-change-items" aria-label="バックアップ後の変更内訳">
              <span class="backup-change-item">判定 <b id="backupChangeDecisionCount">—</b></span>
              <span class="backup-change-item">タグ・メモ <b id="backupChangeTagNoteCount">—</b></span>
              <span class="backup-change-item">お気に入り <b id="backupChangeFavoriteCount">—</b></span>
              <span class="backup-change-item">後で確認 <b id="backupChangeReviewCount">—</b></span>
              <span class="backup-change-item">新規判定基準 <b id="backupChangeScanCount">—</b></span>
              <span id="backupChangeOtherItem" class="backup-change-item hidden">その他 <b id="backupChangeOtherCount">0</b></span>
            </div>
            <span id="backupChangeSummaryNote" class="small">変更内訳を確認中です。</span>
          </div>
          <div id="backupRecommendation" class="backup-recommendation" data-level="warning">
            バックアップ状態を確認中です。
          </div>
        </section>
      </div>
    </div>

    <div id="secondaryActions" class="secondary-actions hidden" aria-hidden="true">
      <section class="secondary-action-group" aria-labelledby="secondaryDisplayTitle">
        <h4 id="secondaryDisplayTitle">表示</h4>
        <div class="secondary-action-group-actions">
          <button id="themeToggle" type="button">ダークテーマ</button>
          <button id="compactToggle" type="button">コンパクト表示</button>
        </div>
        <details id="compactDisplaySettings" class="compact-display-settings">
          <summary>コンパクト表示項目</summary>
          <div class="compact-display-settings-body">
            <span class="small compact-display-required">常に表示: サムネイル・車種・タイトル・作成者・整理状態</span>
            <label><input type="checkbox" data-compact-field="selection"> 一括選択</label>
            <label><input type="checkbox" data-compact-field="fh6"> FH6移動位置</label>
            <label><input type="checkbox" data-compact-field="make-year"> メーカー・年式</label>
            <label><input type="checkbox" data-compact-field="asset"> 内部アセット名</label>
            <label><input type="checkbox" data-compact-field="description"> 説明</label>
            <label><input type="checkbox" data-compact-field="acquired"> 取得日時</label>
            <label><input type="checkbox" data-compact-field="vinyl"> バイナル数</label>
            <label><input type="checkbox" data-compact-field="personal"> タグ・メモ</label>
            <label><input type="checkbox" data-compact-field="flags"> お気に入り・後で確認</label>
          </div>
        </details>
      </section>

      <section class="secondary-action-group" aria-labelledby="secondaryReviewTitle">
        <h4 id="secondaryReviewTitle">連続整理</h4>
        <div class="secondary-action-group-actions">
          <button id="nextUndecided" type="button">次の未決定へ</button>
          <button id="firstUnfinishedVehicle" type="button" data-first-unfinished-vehicle title="現在の表示条件で最初の未完了車種へ移動します">最初の未完了車種へ</button>
          <button id="previousUnfinishedVehicle" type="button" data-previous-unfinished-vehicle title="現在の表示条件で前の未完了車種へ移動します">前の未完了車種へ</button>
          <button id="nextUnfinishedVehicle" type="button" data-next-unfinished-vehicle title="現在の表示条件で次の未完了車種へ移動します">次の未完了車種へ</button>
          <button id="sequentialModeToggle" type="button" title="ONにするとK/Dで判定したあと次の未決定へ自動移動します">連続整理: OFF</button>
        </div>
        <span class="small">Nキーでも次の未決定へ移動できます。未完了車種は現在の表示順を基準に先頭 / 前 / 次へ移動でき、Vキーで次、Shift+Vで前へ移動します。連続整理ON時はK/Dのあと自動で次へ進みます。</span>
      </section>

      <section class="secondary-action-group" aria-labelledby="secondaryExportTitle">
        <h4 id="secondaryExportTitle">エクスポート</h4>
        <div class="secondary-action-group-actions">
          <button id="exportCsv" type="button">全件CSV</button>
          <button id="exportFilteredCsv" type="button">表示中CSV</button>
          <button id="downloadExcel" type="button">Excel</button>
        </div>
      </section>

      <section class="secondary-action-group" aria-labelledby="secondaryBackupTitle">
        <h4 id="secondaryBackupTitle">バックアップ・復元</h4>
        <div class="secondary-action-group-actions">
          <button id="exportUserData" type="button">ユーザーデータ保存</button>
          <button id="importUserData" type="button">ユーザーデータ復元</button>
          <input id="importUserDataFile" type="file" accept="application/json,.json" hidden>
          <button id="exportDecisions" type="button">判定バックアップ</button>
          <button id="importDecisions" type="button">判定を復元</button>
          <input id="importDecisionsFile" type="file" accept="application/json,.json" hidden>
        </div>
        <span class="small backup-status-link-note">保存後の変更有無は「レポート情報 → バックアップ状態」で確認できます。</span>
      </section>

      <section class="secondary-action-group secondary-action-maintenance" aria-labelledby="secondaryMaintenanceTitle">
        <h4 id="secondaryMaintenanceTitle">メンテナンス</h4>
        <div class="secondary-action-group-actions">
          <button id="historyAction" type="button">操作履歴</button>
          <button id="selfDiagnostics" type="button">動作診断</button>
          <button id="resetStates" class="danger-subtle" type="button">判定状態を全消去</button>
        </div>
      </section>
    </div>
  </div>
  <div id="vehicleWorkflowBar" class="vehicle-workflow-bar" aria-label="車種整理クイック操作">
    <span class="vehicle-workflow-label">車種整理</span>
    <button type="button" class="vehicle-progress-summary" data-vehicle-progress-state="none" aria-pressed="false"
      title="未着手（0%）の車種だけを表示します">未着手 <b id="vehicleProgressNoneCount">0</b></button>
    <button type="button" class="vehicle-progress-summary" data-vehicle-progress-state="partial" aria-pressed="false"
      title="整理中（1〜99%）の車種だけを表示します">整理中 <b id="vehicleProgressPartialCount">0</b></button>
    <button type="button" class="vehicle-progress-summary" data-vehicle-progress-state="complete" aria-pressed="false"
      title="完了（100%）の車種だけを表示します">完了 <b id="vehicleProgressCompleteCount">0</b></button>
    <button id="unfinishedVehiclesOnly" type="button" data-unfinished-vehicles-toggle aria-pressed="false"
      title="未着手と整理中の車種だけを表示します">未完了車種のみ</button>
    <button id="previousUnfinishedVehicleQuick" type="button" data-previous-unfinished-vehicle
      title="現在の表示条件で前の未完了車種へ移動します">前の未完了車種へ</button>
    <button id="nextUnfinishedVehicleQuick" type="button" data-next-unfinished-vehicle
      title="現在の表示条件で次の未完了車種へ移動します">次の未完了車種へ</button>
    <span id="vehicleWorkflowHint" class="small">車種整理状況を確認中</span>
  </div>
  <div id="organizationCompletionSummary" class="organization-completion-summary hidden" aria-live="polite">
    <strong id="organizationCompletionStatus">整理完了</strong>
    <span id="organizationCompletionCounts" class="organization-completion-detail">残す 0件 / 削除候補 0件</span>
    <span id="organizationCompletionBackup" class="organization-completion-backup" data-state="none">バックアップ 未保存</span>
  </div>
  <div id="activeFilterChips" class="active-filter-chips" aria-label="現在の絞り込み条件" aria-live="polite"></div>
  <div id="fh6TempDeletedReviewGlobalHost"
    class="fh6-temp-delete-review-host fh6-temp-delete-review-global-host">
    <button id="fh6TempDeletedReview" class="pill hidden" type="button"
      title="FH6で削除済みとして一時的に非表示にしたデザインを確認・復元します">
      FH6削除済み（仮） <b id="fh6TempDeletedCount">0</b>件
    </button>
  </div>
  <div id="fh6GlobalMoveBar" class="fh6-global-move-bar hidden" aria-live="polite">
    <span class="fh6-global-move-target">FH6移動対象: <b id="fh6GlobalMoveTarget">未選択</b></span>
    <button id="fh6GlobalMoveButton" type="button" disabled aria-keyshortcuts="F" title="Fキーでも実行できます">FH6で選択デザインへ移動</button>
  </div>
  <div id="fh6NavigatorSettingsGlobalHost"
    class="fh6-navigator-settings-host fh6-navigator-settings-global-host">
    <details id="fh6NavigatorSettings" class="fh6-navigator-settings">
    <summary>
    <span class="fh6-navigator-settings-title">FH6移動設定</span>
    <span id="fh6NavigatorPlan" class="fh6-navigator-plan-summary">カードを選択すると移動計画を表示します。</span>
    </summary>
    <div class="fh6-navigator-settings-body">
    <label class="fh6-navigator-setting">
    <span>キー間隔</span>
    <input id="fh6NavigatorInterval" type="number" min="10" max="2000" step="1" value="{nav_interval_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    <label class="fh6-navigator-setting">
    <span>FH6切替後</span>
    <input id="fh6NavigatorSwitchDelay" type="number" min="0" max="5000" step="10" value="{nav_switch_delay_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    <label class="fh6-navigator-setting">
    <span>横→上下</span>
    <input id="fh6NavigatorTurnDelay" type="number" min="0" max="5000" step="10" value="{nav_turn_delay_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    <label class="fh6-navigator-setting">
    <span>左循環後の追加待ち</span>
    <input id="fh6NavigatorWrapDelay" type="number" min="0" max="5000" step="10" value="{nav_wrap_delay_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    <div class="fh6-navigator-settings-actions">
    <button id="fh6NavigatorSettingsSync" type="button" title="現在のFH6移動設定をNavigator Bridgeの共通設定ファイルへ保存します">共通設定を保存</button>
    <button id="fh6NavigatorSettingsReset" type="button">初期値</button>
    </div>
    <label class="fh6-navigator-reset-option">
    <input id="fh6NavigatorResetOrigin" type="checkbox" {"checked" if nav_reset_origin else ""}>
    <span>移動前にマイデザインを開き直して <b>#001U</b> へ戻す（固定操作: ESC → RET）</span>
    </label>
    <label class="fh6-navigator-setting">
    <span>ESC後の待ち時間</span>
    <input id="fh6NavigatorResetEscDelay" type="number" min="0" max="5000" step="10" value="{nav_reset_esc_delay_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    <label class="fh6-navigator-setting">
    <span>RET後の待ち時間</span>
    <input id="fh6NavigatorResetRetDelay" type="number" min="0" max="5000" step="10" value="{nav_reset_ret_delay_ms:g}" inputmode="decimal">
    <span class="unit">ms</span>
    </label>
    </div>
    </details>
  </div>
</header>

<main>


  <section id="flatSortSection" class="flat-sort-section hidden">
    <div class="group-heading">
      <h2 id="flatSortTitle">並び替え</h2>
      <span class="group-count-badge" id="flatSortCount">0件</span>
    </div>
    <div id="flatSortGrid" class="grid"></div>
  </section>

  <section id="fh6MyDesignSection" class="fh6-my-design-section hidden" aria-label="FH6マイデザイン順">
    <div class="fh6-my-design-head">
      <div>
        <div class="fh6-my-design-heading-line">
          <h2>FH6マイデザイン順</h2>
          <span id="fh6TempDeletedReviewMyDesignHost" class="fh6-temp-delete-review-host"></span>
        </div>
        <span id="fh6MyDesignCount" class="small">0件</span>
      </div>
      <div class="fh6-my-design-jump" aria-label="FH6マイデザイン位置・車種ジャンプ">
        <label for="fh6MyDesignJumpInput">位置・車種ジャンプ <kbd>J</kbd></label>
        <span class="fh6-my-design-jump-input-wrap">
          <input id="fh6MyDesignJumpInput" type="text" inputmode="text" autocomplete="off"
            placeholder="537 / #269U / RX-7" aria-describedby="fh6VehicleMatchState"
            aria-controls="fh6MyDesignJumpSuggestions" aria-autocomplete="list" aria-keyshortcuts="J"
            title="537 / #537、#269U / #269D、または車種名を入力して移動します。Jキーでこの入力欄へ移動できます">
          <span id="fh6MyDesignJumpSuggestions" class="fh6-my-design-jump-suggestions hidden" role="listbox" aria-label="車種候補"></span>
        </span>
        <button id="fh6MyDesignJump" type="button" title="指定した位置または車種へ移動します">移動</button>
        <button id="fh6NavigatorMove" type="button" disabled aria-keyshortcuts="F"
          title="Navigator Bridge for FH6 v0.0.27へ選択デザインの現在位置と移動設定を渡します。Fキーでも実行できます。Navigator Bridge側で連携を一度登録してください。">FH6で選択デザインへ移動</button>
        <span id="fh6VehicleMatchNav" class="fh6-vehicle-match-nav hidden" aria-label="位置・車種ジャンプの状態と一致位置の移動">
          <button id="fh6VehicleMatchPrev" type="button" aria-keyshortcuts="Shift+ArrowLeft" title="検索一致の前へ移動します（Shift+←）" hidden>← 前の一致</button>
          <span id="fh6VehicleMatchState" class="small" aria-live="polite"></span>
          <button id="fh6VehicleMatchNext" type="button" aria-keyshortcuts="Shift+ArrowRight" title="検索一致の次へ移動します（Shift+→）" hidden>次の一致 →</button>
        </span>
        <div id="fh6NavigatorSettingsMyDesignHost"
          class="fh6-navigator-settings-host fh6-navigator-settings-my-design-host"></div>
      </div>
      <div class="fh6-my-design-nav" aria-label="FH6マイデザイン横移動">
        <button id="fh6MyDesignPrev" type="button" title="前の列へ。先頭では最後の列へ移動します">← 前へ</button>
        <span id="fh6MyDesignPosition" class="small">—</span>
        <button id="fh6MyDesignNext" type="button" title="次の列へ。最後では先頭の列へ移動します">次へ →</button>
      </div>
    </div>
    <div id="fh6MyDesignViewport" class="fh6-my-design-viewport" tabindex="0" aria-label="FH6マイデザイン横スクロール一覧">
      <div id="fh6MyDesignTrack" class="fh6-my-design-track"></div>
    </div>
    <div class="fh6-my-design-foot small">
      <p><b class="fh6-foot-label">表示・基本移動</b>1列に上・下の2件を配置します。横スクロール、通常のマウスホイール（縦回転）、← / →キー、または「前へ / 次へ」で移動できます。端では反対側へ循環します。各カード下部にはFH6「マイデザイン」画面と同じ日付を DD/MM/YYYY 形式で表示します。</p>
      <p><b class="fh6-foot-label">位置・車種ジャンプ</b><b>537 / #537</b> のような実スロット通し番号、<b>#269U / #269D</b> のようなFH6画面の列＋U/D位置（U=上段、D=下段）、または <b>RX-7</b> のような車種名を指定できます。車種名は部分一致で候補を表示し、↑ / ↓で選択できます。候補を選ばずにEnterまたは「移動」を押すと、一致した各車種を1車種1位置ずつ巡回します。↑ / ↓で特定の車種候補を選んでEnterすると、その1車種に属する実スロットを巡回します。どちらも検索を確定した後は <b>Shift+→</b> で次の一致、<b>Shift+←</b> で前の一致へ移動し、末尾では先頭へ循環します。<b>J</b> でいつでもジャンプ入力欄へ戻れます。</p>
      <p><b class="fh6-foot-label">重複・仮削除</b>完全一致の再ダウンロードも別ペイントとして表示し、FH6本体の実スロット位置を維持します。FH6で削除したデザインはカードの <b>FH6で削除済み</b> で一時的に非表示にでき、残りの実スロット番号とFH6位置を即時に詰め直します。上部の <b>FH6削除済み（仮）</b> から1件ずつ、または全件を復元できます。仮削除はこの生成HTML専用のlocalStorageへ保存され、新しくHTMLを生成すると引き継ぎません。再DL完全一致は {stats.get("fh6_exact_duplicate_groups", 0)}組 / {stats.get("fh6_exact_duplicate_cards", 0)}件（余分 {stats.get("fh6_exact_duplicate_instances", 0)}件）で、「再DL重複のみ」から直接絞り込めます。</p>
      <p><b class="fh6-foot-label">FH6で選択デザインへ移動</b>カード上の実スロット番号 <b>#603</b> またはFH6位置 <b>#302U</b> をクリックすると、そのデザインをOrganizer全体のFH6移動対象に設定できます。選択中はFH6移動グループ全体をアクセント表示します。メーカー順・車名順・作成者順など他の並び順や、類似ペイント比較・再DL重複整理画面からも同じ移動対象を選べます。選択後はボタンまたは <b>F</b> キーで移動できます。FH6標準の「マイデザイン」ではサムネイル・タイトル・作成者・作成者がUPした日付の4項目だけで目的のペイントを探す必要がありますが、Organizerでは車種・メーカー・年式・作成者・タイトルなどから先に使いたいデザインを特定できます。Bridgeで該当位置まで移動したあと、FH6上で利用者が<b>「デザインを読み込み」</b>を実行すれば、現在運転しているマシンへそのペイントを適用できます。また、不要なペイントをFH6で削除した場合は「FH6で削除済み（仮）」へ反映することで、残りの実スロット番号とFH6位置を再計算し、次の整理へ続けられます。Bridgeは読み込み・選択・削除・確定操作を行わず、対象位置までのカーソル移動だけを補助します。移動時は現在の最終実スロット番号と「FH6移動設定」を Navigator Bridge for FH6 v0.0.27 へ渡します。</p>
      <p><b class="fh6-foot-label">#001Uへ戻す</b>このオプションをONにした場合だけ、移動前に <b>ESC → RET</b> を各1回固定順序で送ってマイデザインを開き直します。標準待ち時間は <b>ESC後 500ms / RET後 800ms</b> です。任意のキーコード・キー名・キー順序は指定できず、上・文字キー・ファンクションキーその他は送信しません。</p>
      <p><b class="fh6-foot-label">Bridge連携</b>Navigator Bridge v0.0.27はシングルインスタンスで動作し、OrganizerからのBridgeモード起動ではGUIを表示しません。起動済みなら新しいウィンドウを増やさず既存Bridgeへ指示を渡します。初回だけNavigator Bridge側の「連携を登録」を実行し、ブラウザから外部アプリを開く確認が表示された場合は許可してください。Bridge本体を別フォルダへ移動・ファイル名変更した場合は、移動後の場所から「連携を登録」を再実行してください。BridgeはFH6の画面内容やゲーム内部のペイント位置・カーソル位置を読み取らず、設定された間隔で固定キー入力を送信する方式です。そのためPCやFH6の処理負荷などで入力が取りこぼされると、指定位置からずれる場合があります。ずれる場合はキー間隔や各待ち時間を長めに調整してください。</p>
    </div>
  </section>

  <div id="creatorGroupedSections" class="creator-grouped-sections"></div>

  <div id="groupedSections">
    {''.join(groups_html) if groups_html else f'<p>{html.escape(report_fallback_no_liveries)}</p>'}
  </div>
</main>

<div id="emptyState" class="empty-state">条件に一致するペイントがありません。検索条件や絞り込みを変更してください。</div>
<div class="keyboard-guide">
  <a class="keyboard-copyright" href="https://x.com/Yomogigari" target="_blank" rel="noopener noreferrer" aria-label="YomogigariのXアカウントを開く">©Yomogigari</a><span>/ 検索</span><span>? ヘルプ</span><span>F FH6移動</span><span>K 残す</span><span>D 削除候補</span><span>U 未決定</span><span>Space 選択</span><span>Ctrl+Z 元に戻す</span><span>Ctrl+Y やり直す</span>
</div>
<nav class="mobile-bottom-nav" aria-label="スマホ用ナビゲーション">
  <button type="button" data-mobile-action="all">一覧</button>
  <button type="button" data-mobile-action="filter">絞り込み</button>
  <button type="button" data-mobile-action="undecided">未決定</button>
  <button type="button" data-mobile-action="delete">削除候補</button>
</nav>
<div id="helpModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel help-panel" role="dialog" aria-modal="true" aria-labelledby="helpTitle">
    <div class="modal-head">
      <div>
        <h3 id="helpTitle">Livery Organizer for FH6 ヘルプ</h3>
        <div class="small">v{VERSION} 現在仕様 / 日常の操作順に整理したガイド</div>
      </div>
      <button data-close-modal="helpModal">閉じる</button>
    </div>

    <div class="help-intro">
      <b>FH6で取得したペイントを、検索・比較・判定・分類・バックアップするための整理画面です。</b>
      判定、タグ、メモ、お気に入り、後で確認などはブラウザ側へ保存され、
      レポート上の操作からFH6のGameSaveを削除・移動・リネーム・上書きすることはありません。
    </div>

    <section class="help-fh6-move-workflow" aria-labelledby="helpFh6MoveWorkflowTitle">
      <h4 id="helpFh6MoveWorkflowTitle">Organizerで目的のデザインを探し、FH6上の位置へ移動する</h4>
      <ol>
        <li>車種・メーカー・年式・作成者・タイトルなどから目的のペイントを探し、カードまたは比較画面の <b>#603 / #302U</b> などをクリックしてFH6移動対象に設定します。</li>
        <li><b>F</b> キー、または <b>FH6で選択デザインへ移動</b> を実行します。</li>
        <li>Navigator BridgeがFH6を前面に切り替え、設定された間隔でキー操作を送り、選択したマイデザイン位置への移動を試みます。到着後は、目的に応じて利用者がFH6の <b>「デザインを読み込み」</b> を実行するか、内容を確認して整理・削除します。</li>
      </ol>
    </section>

    <div class="help-quick-start" aria-label="基本操作">
      <div class="help-step">
        <span class="help-step-number">1</span><b>探す</b>
        <p>検索、並び替え、上部の各統計クイック絞り込みから対象を見つけます。</p>
      </div>
      <div class="help-step">
        <span class="help-step-number">2</span><b>絞る</b>
        <p>整理状態、車種進捗、件数、バイナル数、タグ、新規などを組み合わせます。</p>
      </div>
      <div class="help-step">
        <span class="help-step-number">3</span><b>整理する</b>
        <p>残す / 削除候補 / 未決定と、タグ・メモ・各フラグを設定します。</p>
      </div>
      <div class="help-step">
        <span class="help-step-number">4</span><b>保存・出力</b>
        <p>区切りでユーザーデータを保存し、必要に応じてCSV / Excelを利用します。</p>
      </div>
    </div>

    <div class="help-current-note">
      目的に合わせて、下の4カテゴリを切り替えて確認してください。
    </div>

    <div class="help-tabs" role="tablist" aria-label="ヘルプカテゴリ">
      <button id="helpBasicsTab" class="help-tab active" type="button" role="tab"
        data-help-tab="basics" aria-selected="true" aria-controls="helpBasicsPane">探す・絞る</button>
      <button id="helpOrganizeTab" class="help-tab" type="button" role="tab"
        data-help-tab="organize" aria-selected="false" aria-controls="helpOrganizePane">整理・車種</button>
      <button id="helpDataTab" class="help-tab" type="button" role="tab"
        data-help-tab="data" aria-selected="false" aria-controls="helpDataPane">保存・出力</button>
      <button id="helpEnvironmentTab" class="help-tab" type="button" role="tab"
        data-help-tab="environment" aria-selected="false" aria-controls="helpEnvironmentPane">操作・安全</button>
    </div>

    <div id="helpBasicsPane" class="help-pane" role="tabpanel" aria-labelledby="helpBasicsTab">
      <section class="help-section">
        <h4>画面上部とクイック絞り込み</h4>
        <p>
          上部には総ペイント数、車種数、メーカー数、作成者数、年式範囲と、
          未決定・お気に入り・後で確認・新規・類似候補の現在件数を表示します。
        </p>
        <p>
          <b>車種数 / メーカー / 作成者数 / 年式</b> は候補を選ぶクイック絞り込みです。
          候補検索、複数選択、「選択中のみ」「表示候補をすべて選択」「この項目を解除」が使えます。
          <b>未決定 / お気に入り / 後で確認 / 新規 / 類似候補</b> もクリックでき、対応する「絞り込み」条件を直接ON / OFFできます。
        </p>
        <div class="help-tip">
          同じ項目で複数候補を選ぶと <b>OR</b>、異なる項目を組み合わせると <b>AND</b> です。
        </div>
      </section>

      <section class="help-section">
        <h4>検索</h4>
        <p>
          通常検索は車両情報、タイトル、説明、作成者、Car ID、取得情報に加え、
          ブラウザで入力したタグ・メモも対象にした部分一致検索です。
        </p>
        <table class="help-mini-table">
          <tbody>
            <tr><th><code>v:</code></th><td>Vehicle。数字はCar ID完全一致、文字列は車名・メーカー・モデル・年式。</td></tr>
            <tr><th><code>c:</code></th><td>Creator。作成者。</td></tr>
            <tr><th><code>n:</code></th><td>Name。タイトル。</td></tr>
            <tr><th><code>d:</code></th><td>Description。説明。</td></tr>
            <tr><th><code>t:</code></th><td>Tag。ブラウザで設定したタグ。</td></tr>
          </tbody>
        </table>
        <p>
          例: <code>v:0363</code>、<code>v:Porsche</code>、
          <code>c:DemoWorks n:&quot;デモペイント 001&quot;</code>、<code>t:デモ c:DemoWorks</code>。
          空白を含む値はダブルクォートで囲み、複数指定はAND検索になります。
        </p>
      </section>

      <section class="help-section help-section-wide">
        <h4>並び替え</h4>
        <table class="help-mini-table">
          <thead><tr><th>並び替え</th><th>動作</th></tr></thead>
          <tbody>
            <tr><td>メーカー順 / 車名順 / 年式順</td><td>車種グループを保ったまま、それぞれの基準で並び替えます。年式不明は年式ソートで最後です。</td></tr>
            <tr><td>マイデザイン順</td><td>FH6の「マイデザイン」画面と同じ順序で、Car IDの小さい車種から並べ、同じ車種内は取得日時の古い順にします。カード左上には <b>#001</b> からの通し番号を表示し、FH6画面上の位置を照合しやすくします。絞り込み中も番号は詰め直しません。FH6側に昇順 / 降順の切り替えがないため、この項目は固定順です。</td></tr>
            <tr><td>FH6マイデザイン順</td><td>
              <div class="help-sort-fh6-detail">
                <p><b>表示</b><br>FH6画面に近い <b>2段×横スクロール</b> で表示します。1列目は <b>#001U / #001D</b>、2列目は <b>#002U / #002D</b> のように位置を表示し、カード内は <b>タイトル → 作成者 → 日付</b> の順です。完全一致の再ダウンロードも別ペイントとして扱い、FH6本体と同じ実スロット位置で表示します。</p>
                <p><b>横移動</b><br>横スクロール、通常のマウスホイール（縦回転）、← / →キー、「前へ / 次へ」で1列ずつ移動できます。先頭の左は最後へ、最後の右は先頭へ循環します。</p>
                <p><b>位置・車種ジャンプ</b><br><b>537 / #537</b> の実スロット番号、<b>#269U / #269D</b> の列＋U/D位置、または車種名の一部から直接移動できます。車種候補は年式・メーカー・車名を対象に部分一致し、↑ / ↓で選択できます。候補を選んでEnterするとその車種内を巡回し、候補を選ばずEnterまたは「移動」を押すと一致車種を<b>1車種1位置</b>で巡回します。確定後は <b>Shift+← / Shift+→</b> で前後の一致へ移動でき、<b>J</b>で入力欄へ戻り、Escで候補を閉じます。</p>
                <p><b>FH6で選択デザインへ移動</b><br>FH6標準の「マイデザイン」で確認できるのは、サムネイル・タイトル・作成者・作成者がUPした日付の4項目です。ダウンロード済みペイントが増えると、目的のデザインをFH6画面だけで探すのは手間がかかります。Organizerでは車種・メーカー・年式・作成者・タイトルなどで先に目的のペイントを探し、カードの <b>#603</b> や <b>#302U</b> をクリックしてFH6移動対象にできます。メーカー順・車名順・作成者順など他の並び順や、類似ペイント比較・再DL重複整理画面でも同じ操作ができます。選択後は <b>FH6で選択デザインへ移動</b> または <b>F</b> キーで実行します。対象位置へ移動したあと、FH6上で利用者が <b>「デザインを読み込み」</b> を実行すれば、現在運転しているマシンへそのペイントを適用できます。Bridgeは「デザインを読み込み」、選択、削除、確定を自動化しません。Navigator BridgeはFH6の画面内容や内部のカーソル位置を読み取らず、設定した間隔でキー操作を送るだけなので、PCやFH6の負荷による入力取りこぼしで指定位置からずれる場合があります。ずれる場合はFH6移動設定の待ち時間を長めにしてください。</p>
                <p><b>FH6で削除済み（仮）</b><br>Bridgeで整理対象の位置へ移動し、FH6上で利用者が不要なデザインを削除したあと、同じデザインをOrganizerで一時的に非表示にすると、残りの実スロット番号と列＋U/D位置をその場で詰め直します。再計算された位置は次のBridge移動にも使われるため、削除で後続スロットが詰まっても連続して整理できます。上部の <b>FH6削除済み（仮）</b> から個別復元 / 全件復元できます。この状態は現在の生成HTML専用で、新しく生成したHTMLには引き継ぎません。</p>
                <p><b>絞り込み中</b><br>現在の仮削除反映後の位置を維持し、表示対象がない列だけ省略します。ジャンプ先が絞り込みで非表示の場合は条件を変更せず、その旨を案内します。移動先は一時的に強調表示します。</p>
              </div>
            </td></tr>
            <tr><td>作成者順</td><td>作成者ごとにグループ化して表示します。</td></tr>
            <tr><td>タイトル順 / 整理状態順</td><td>車種グループをまたいでカード単位で並び替えます。整理状態は未決定 → 後で確認 → 残す → 削除候補の作業順です。</td></tr>
            <tr><td>整理進捗順</td><td>車種単位で未着手（0%）/ 整理中（1〜99%）/ 完了（100%）を昇順または逆順にします。</td></tr>
            <tr><td>ペイント件数順</td><td>車種ごとのペイント件数で車種グループを並び替えます。</td></tr>
            <tr><td>バイナル数順 / 取得日時順</td><td>カード単位で昇順 / 降順に並び替えます。取得日時はフォルダ名のUTC時刻をJST（UTC+9）へ変換して表示します。</td></tr>
          </tbody>
        </table>
      </section>

      <section class="help-section help-section-wide">
        <h4>「絞り込み」メニュー</h4>
        <p><span class="help-path">上部ツールバー → 絞り込み</span></p>
        <p>
          メニューは <b>「条件」</b> と <b>「選択・一括」</b> に分かれています。
          「条件」では作成者、整理状態、車種の整理進捗、ペイント件数、バイナル数、タグ、
          削除候補・新規・類似候補・お気に入り・後で確認、プリセットを設定します。
        </p>
        <ul>
          <li><b>整理状態</b>：未決定 / 残す / 削除候補を複数選択。</li>
          <li><b>車種の整理進捗</b>：未着手 / 整理中 / 完了を複数選択。</li>
          <li><b>ペイント件数</b>：車種に含まれるペイント件数を複数選択。</li>
          <li><b>バイナル数</b>：最小 / 最大を範囲指定。片側だけでも可。</li>
          <li><b>タグ</b>：複数選択し「いずれか（OR）」/「すべて（AND）」を切替。</li>
          <li><b>新規のみ</b>：手動保存した新規判定基準より後に現れたカードだけを表示。HTMLを開くだけでは基準は更新しません。</li>
        </ul>
        <p>
          現在条件は画面上部の条件チップへ表示され、×で個別解除できます。
          「絞り込み解除」は検索を含む主要条件をまとめて解除します。よく使う条件は名前付きプリセットとして保存・適用・削除できます。
        </p>
      </section>
    </div>

    <div id="helpOrganizePane" class="help-pane hidden" role="tabpanel" aria-labelledby="helpOrganizeTab">
      <section class="help-section">
        <h4>カードの見方と整理</h4>
        <p>
          各カードにはサムネイル、車両情報、タイトル、説明、作成者、取得日時、バイナル数などを表示します。
          サムネイルはクリックで拡大できます。
        </p>
        <ul>
          <li><b>残す / 削除候補 / 未決定</b>：整理判定。</li>
          <li><b>お気に入り</b>：残したい・よく使う候補の目印。</li>
          <li><b>後で確認</b>：判断を保留したいカードの目印。</li>
          <li><b>タグ・メモ</b>：任意分類と自由記述。検索対象にもなります。</li>
        </ul>
        <div class="help-tip help-warning">
          <b>「削除候補」はOrganizer内のラベルです。</b> FH6のファイルを削除しません。
        </div>
      </section>

      <section class="help-section">
        <h4>選択・一括操作・Undo / Redo</h4>
        <p>
          カード左上のチェックを一括操作対象として使います。
          <span class="help-path">絞り込み → 選択・一括</span> では、表示中を選択、選択反転、選択解除、
          <b>選択中のペイント比較</b>、一括判定、一括お気に入り、一括「後で確認」、タグ管理を利用できます。
        </p>
        <p>
          タグ管理は <b>追加 / 削除 / 置換</b> に対応し、追加ではカンマ区切りで複数タグを指定できます。
          編集操作は「元に戻す / やり直す」の対象です。
          <span class="help-path">その他の操作 → メンテナンス → 操作履歴</span> で履歴も確認できます。
        </p>
      </section>

      <section class="help-section help-section-wide">
        <h4>車種整理ワークフロー</h4>
        <p>
          車種見出しの進捗は、その車種の<b>全ペイント</b>を基準に計算します。
          「残す」または「削除候補」を整理済み、「未決定」を未整理として扱い、
          未着手（0%）/ 整理中（1〜99%）/ 完了（100%）に分類します。
        </p>
        <p>
          画面上部の「車種整理」バーでは未着手 / 整理中 / 完了の車種数を表示し、各ボタンでその状態だけへ絞り込めます。
          <b>未完了車種のみ</b> は未着手＋整理中のショートカットです。
          <b>前の未完了車種へ / 次の未完了車種へ</b> は現在の検索・絞り込み・並び順を基準に未完了車種を前後へ巡回し、その車種の未決定カードを優先してフォーカスします。
          <span class="help-path">その他の操作 → 連続整理</span> の <b>最初の未完了車種へ</b> では、現在の表示順の先頭にある未完了車種へ戻れます。
        </p>
        <p>
          車種の進捗バッジをクリックすると、他の条件を解除してその車種だけを表示します。
          移動中の車種は見出しが強調され、<b>「未完了 3 / 18車種 · 全 76車種」</b> のように現在位置を表示します。
          現在車種を完了すると <b>「現在 完了」</b> へ変わり、検索・絞り込み・並び替えを変えると現在の表示順で再計算します。
        </p>
        <div class="help-tip">
          全ペイントの未決定が0件になると、上部に <b>整理完了</b> を表示し、残す件数 / 削除候補件数とユーザーデータバックアップ状態を同時に確認できます。
        </div>
      </section>

      <section class="help-section">
        <h4>類似候補・詳細表示</h4>
        <p>
          類似候補があるカードには、判定理由に応じて<b>「画像一致 ○件」</b>または<b>「同一作者・同名 ○件」</b>と表示します。
          同じ車種内の<b>サムネイル完全一致</b>または<b>作成者＋タイトル一致</b>を手がかりに候補化し、
          比較画面では一致理由、取得日時、説明、整理状態、フィンガープリントを確認できます。
          <span class="help-path">絞り込み → 条件</span> では、<b>類似候補のみ</b>に加えて
          <b>画像一致のみ</b> / <b>同一作者・同名のみ</b>で、表示中の判定理由ごとに候補を絞り込めます。
          現在スナップショット内に同じペイントを再ダウンロードした完全一致スロットが複数ある場合は、
          それぞれを別カードとして表示し、<b>画像一致</b>の類似候補として扱うほか、<b>再DL重複</b>バッジも表示します。
          <b>再DL重複のみ</b>を使うと、この完全一致再ダウンロードだけを直接絞り込めます。
          <b>再DL重複 ○件</b>バッジをクリックすると専用整理画面を開き、FH6位置・FH6表示日付・取得日時・Livery IDを見比べながら
          <b>「これを残す」</b>を選べます。選んだ1件を「残す」、同じ完全一致グループの残りを「削除候補」にまとめて設定します。
        </p>
        <p>
          カードを2件以上チェックして <span class="help-path">絞り込み → 選択・一括 → 選択中を比較</span> を使うと、
          自動類似判定に入らない任意のペイントも同じ比較画面で見比べられます。
          「古い候補を選択（最新以外）」は類似候補比較のときだけ表示され、Organizer上の一括操作対象を選ぶだけでGameSaveを変更しません。
          車種・作成者リンクのダブルクリックでは件数や平均バイナル数などの詳細も確認できます。
        </p>
      </section>

      <section class="help-section">
        <h4>連続整理</h4>
        <p><span class="help-path">その他の操作 → 連続整理</span></p>
        <p>
          「次の未決定へ」と未完了車種の「最初 / 前 / 次」移動に加え、<b>連続整理: ON</b> では
          <kbd>K</kbd> / <kbd>D</kbd> で判定した直後に現在の表示順で次の未決定カードへ自動移動します。
          <kbd>U</kbd> は自動移動しません。
        </p>
      </section>
    </div>

    <div id="helpDataPane" class="help-pane hidden" role="tabpanel" aria-labelledby="helpDataTab">
      <section class="help-section help-section-wide">
        <h4>レポート情報</h4>
        <p><span class="help-path">上部ツールバー → レポート情報</span></p>
        <p>
          <b>「概要・進捗」</b>では保存領域、件数、重複、車両DB、最終スキャン、サムネイル方式、ビルド、
          UI状態、保存方式と、整理件数・整理進捗・選択数・新規判定基準を確認します。
          下部の<b>「利用準備」</b>ではブラウザ保存、レポートデータ整合性、サムネイル方式をまとめて確認でき、
          そのまま動作診断へ進めます。「表示 / 残す / 削除候補 / 未決定」の件数ボタンは絞り込みにも使えます。
        </p>
        <p>
          <b>「前回との差分」</b>では、保存済みの新規判定基準と今回のHTMLを比較して、<b>新規</b>と<b>消滅</b>を1つの画面で確認できます。
          新規は現在のカード、消滅は基準には存在したものの今回のHTMLには存在しないペイントです。基準を更新するときだけ「今回を新規判定の基準にする」を押します。
        </p>
        <p>
          <b>「バックアップ状態」</b>ではユーザーデータ保存 / 判定バックアップの前回保存時刻と、現在との差を確認します。
          ユーザーデータについては、前回保存から変更された<b>判定、タグ・メモ、お気に入り、後で確認、新規判定基準</b>も項目別に集計します。
        </p>
      </section>

      <section class="help-section">
        <h4>ユーザーデータ保存・復元</h4>
        <p>
          判定、タグ、メモ、お気に入り、後で確認、UI状態、絞り込みプリセットなどは通常ブラウザの
          <code>localStorage</code> へ保存します。利用できない環境では一時メモリへ切り替わります。
        </p>
        <p>
          <b>ユーザーデータ保存</b>は判定・メタデータに加えてUI状態とスキャン状態をJSONへ保存します。
          <b>ユーザーデータ復元</b>ではプレビュー後に「現在データと統合」または「完全に置換」を選べます。
          <b>判定バックアップ</b>は主に残す / 削除候補の判定だけを保存する軽量版です。
        </p>
      </section>

      <section class="help-section">
        <h4>バックアップ状態の読み方</h4>
        <p>
          状態は <b>未バックアップ / 最新 / 変更あり</b> です。
          ユーザーデータの比較対象は判定・タグ・メモ・お気に入り・後で確認・スキャン状態で、
          検索条件、並び順、テーマなどの日常的なUI変更だけでは「変更あり」になりません。
        </p>
        <p>
          「前回のユーザーデータ保存からの変更」ではタグとメモを同じペイントで両方変更しても1件として数えます。
        </p>
        <div class="help-tip">
          表示する保存時刻は、ブラウザがJSONのダウンロード操作を開始した時刻です。実ファイルが保存先に残っているかはHTMLから確認できません。
        </div>
      </section>

      <section class="help-section help-section-wide">
        <h4>出力ファイルとHTMLの持ち運び</h4>
        <table class="help-mini-table">
          <thead><tr><th>出力</th><th>内容・注意点</th></tr></thead>
          <tbody>
            <tr><td>全件CSV</td><td>全ペイント。現在の判定・タグ・メモ・お気に入り・後で確認を反映します。</td></tr>
            <tr><td>表示中CSV</td><td>現在表示されているカードだけを、画面上の現在の並び順と同じ行順で出力します。</td></tr>
            <tr><td>Excel</td><td>レポート生成時の <code>livery-organizer-for-fh6.xlsx</code>。サムネイル入りですが、HTMLを開いた後の判定変更はリアルタイム反映されません。</td></tr>
            <tr><td>ユーザーデータJSON</td><td>判定、タグ、メモ、お気に入り、後で確認、UI状態、スキャン状態をブラウザから保存します。別PCへの整理内容移行にも使えます。</td></tr>
            <tr><td>判定バックアップJSON</td><td>残す / 削除候補を中心に保存する軽量バックアップです。</td></tr>
          </tbody>
        </table>
        <p>
          サムネイルをHTMLへ埋め込む設定ならHTML単体で移動できます。
          <code>thumbnails</code> 参照方式ではHTMLとフォルダを一緒にコピーしてください。
          HTMLだけを別PCへ移しても元ブラウザの <code>localStorage</code> は移らないため、整理内容の移行にはユーザーデータ保存 / 復元を使います。
        </p>
        <p>
          通常出力はHTMLとExcelです。「解析用データを data フォルダへ出力」を有効にした場合だけ、
          JSON / CSVの解析用データを追加生成します。これらはHTML表示には不要です。
        </p>
      </section>
    </div>

    <div id="helpEnvironmentPane" class="help-pane hidden" role="tabpanel" aria-labelledby="helpEnvironmentTab">
      <section class="help-section help-section-wide">
        <h4>最初に確認するところ</h4>
        <p><span class="help-path">レポート情報 → 概要・進捗 → 利用準備</span></p>
        <p>
          <b>ブラウザ保存</b>、<b>レポートデータ</b>、<b>サムネイル方式</b>をまとめて確認できます。
          「準備OK」なら通常利用できます。初めて開いたHTML、別フォルダへ移動したHTML、
          <code>thumbnails</code> 外部参照版では、続けて「動作診断」を実行すると画像の実読込まで確認できます。
        </p>
        <p>
          JavaScriptエラーが発生した場合は「レポート情報」にエラー内容と<b>動作診断</b>ボタンを表示します。
          保存方式が「一時メモリ」の場合は、タブを閉じる前にユーザーデータ保存を利用してください。
        </p>
      </section>

      <section class="help-section help-section-wide">
        <h4>レポート生成前の実行チェック</h4>
        <p>
          デスクトップ画面の<b>実行前チェック</b>では、保存領域、FH6本体、出力先、出力構成を確認します。
          保存領域または出力先に問題がある場合は実行を止め、FH6本体だけが未検出の場合は
          「要確認」としてCar ID表示で続行できます。初回起動時は<b>初回利用ガイド</b>も自動表示し、
          2回目以降も画面下部の同名ボタンから再確認できます。
        </p>
        <p>
          出力先は選択した <code>pgs</code> だけでなく、その親の<b>GameSaveディレクトリ全体</b>を保護対象として扱います。
          GUI、CLI、レポート書込み処理の各段階でGameSave配下への出力を拒否します。
        </p>
        <p>
          Python環境でTkinterを読み込めずGUIを開始できない場合は、自動走査へ移行せず安全に停止します。
          コマンドプロンプトから <code>--environment-check</code> を実行すると、走査せず環境と設定だけを確認できます。
          車両アセット探索では、FH6側の0バイトの <code>.zip</code> は空プレースホルダーとして正常スキップします。
          0バイト以外で「読み取り不可ZIP」が表示された場合は、<code>--inspect-vehicle-assets</code> で
          FH6本体を変更せず、空ZIPと該当ZIPの相対パス・例外種別・先頭シグネチャを確認できます。
        </p>
        <div class="help-tip">
          出力構成には常にHTMLとExcelを含みます。サムネイル埋め込みONではHTMLに画像を含め、
          OFFでは <code>thumbnails</code> フォルダもセットで生成します。解析データON時だけ <code>data</code> を追加します。
        </div>
      </section>

      <section class="help-section help-section-wide">
        <h4>初回利用からレポート確認まで</h4>
        <ol>
          <li>FH6を完全終了してからPython側を起動します。</li>
          <li>保存領域 / FH6本体 / 出力先を確認し、「実行前チェック」がOKまたは要確認になっていることを確認します。</li>
          <li>サムネイル方式と解析データ出力を選び、「ペイントデータチェック」を実行します。</li>
          <li>生成後はHTMLが自動で開きます。「レポート情報 → 利用準備」を確認し、初回利用時や移動後は「動作診断」を実行します。</li>
        </ol>
        <p>
          生成完了ダイアログには、その実行で作成したHTML / Excel / <code>thumbnails</code> / <code>data</code> のうち
          該当する出力を一覧表示します。配布・移動時はこの単位を崩さず扱ってください。
        </p>
      </section>

      <section class="help-section help-section-wide">
        <h4>トラブル時の環境・サポート情報</h4>
        <p>
          Python側の<b>環境・サポート情報</b>では、Organizerのバージョン、Windows / Python環境、Tkinter、
          設定ファイル、3つのパス、出力構成、実行前チェック結果を1つのテキストにまとめて確認・コピーできます。
          不具合報告時にこの情報を添えると、環境差や設定差を切り分けやすくなります。
        </p>
        <div class="help-tip help-warning">
          コピー内容にはWindowsユーザー名やローカルパスが含まれる場合があります。第三者へ送る前に内容を確認してください。
          CLIでは <code>--environment-check</code> でも同じ種類の情報を表示できます。
        </div>
      </section>

      <section class="help-section">
        <h4>「その他の操作」</h4>
        <p><span class="help-path">上部ツールバー → その他の操作</span></p>
        <table class="help-mini-table">
          <tbody>
            <tr><th>表示</th><td>ダーク / ライトテーマ、約150px幅のコンパクト表示。コンパクト表示では追加表示する項目を選択できます。</td></tr>
            <tr><th>連続整理</th><td>次の未決定、未完了車種の最初 / 前 / 次、K/D後の自動移動。</td></tr>
            <tr><th>エクスポート</th><td>全件CSV、表示中CSV、Excel。</td></tr>
            <tr><th>バックアップ・復元</th><td>ユーザーデータ保存 / 復元、判定バックアップ / 復元。</td></tr>
            <tr><th>メンテナンス</th><td>操作履歴、動作診断、判定状態を全消去。動作診断ではカード / CSVの対応、重複キー、車種件数、進捗メタデータ、サムネイル参照に加え、マイデザイン番号、FH6実スロット、FH6表示日付、再DL重複グループも確認します。</td></tr>
          </tbody>
        </table>
        <p>
          「判定状態を全消去」は残す / 削除候補を未決定へ戻す操作です。
          タグ、メモ、お気に入り、後で確認は消去しません。
        </p>
      </section>

      <section class="help-section">
        <h4>スマートフォン表示</h4>
        <p>
          狭い画面では上部UIを簡略化し、車種 / メーカー / 作成者 / 年式のクイック絞り込みと、
          「絞り込み・並び替え」ボタンを表示します。
          車種整理バーの未完了絞り込み・前 / 次の未完了車種移動も利用できます。
        </p>
        <p>画面下部には「一覧 / 絞り込み / 未決定 / 削除候補」のナビゲーションを表示します。</p>
      </section>

      <section class="help-section help-section-wide">
        <h4>キーボード操作</h4>
        <div class="help-shortcuts">
          <span><kbd>← ↑ → ↓</kbd> カード移動</span>
          <span><kbd>/</kbd> 検索欄へ移動</span>
          <span><kbd>?</kbd> ヘルプを開く</span>
          <span><kbd>F</kbd> FH6で選択デザインへ移動</span>
          <span><kbd>J</kbd> FH6マイデザイン順の位置・車種ジャンプへ移動</span>
          <span><kbd>Shift</kbd> + <kbd>← / →</kbd> 車種検索を確定した後、前 / 次の一致へ巡回</span>
          <span><kbd>K</kbd> 残す</span>
          <span><kbd>D</kbd> 削除候補</span>
          <span><kbd>U</kbd> 未決定</span>
          <span><kbd>Space</kbd> 選択切替</span>
          <span><kbd>N</kbd> 次の未決定へ</span>
          <span><kbd>V</kbd> 次の未完了車種へ</span>
          <span><kbd>Shift+V</kbd> 前の未完了車種へ</span>
          <span><kbd>Ctrl</kbd> + <kbd>Z</kbd> 元に戻す</span>
          <span><kbd>Ctrl</kbd> + <kbd>Y</kbd> やり直す</span>
          <span><kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Z</kbd> やり直す</span>
          <span><kbd>Esc</kbd> 開いている操作パネル / ダイアログを閉じる</span>
        </div>
        <div class="help-tip">
          ダイアログを開くとフォーカスはダイアログ内へ移動し、<kbd>Tab</kbd> / <kbd>Shift</kbd> + <kbd>Tab</kbd> はダイアログ内を循環します。閉じると、原則として開く前に操作していたボタンへ戻ります。<kbd>F</kbd> は類似ペイント比較・選択比較・再DL重複整理を開いている間も、選択済みのFH6移動対象へ移動できます。<kbd>J</kbd> と <kbd>Shift</kbd> + <kbd>← / →</kbd> はFH6マイデザイン順でのみ利用できます。入力欄・テキストエリア・選択欄へフォーカスしている間は、文字キーのショートカットを誤作動させないようにしています。
        </div>
      </section>

      <section class="help-section help-section-wide help-safety">
        <h4>GameSaveと安全性</h4>
        <p>
          Livery Organizer for FH6はGameSaveとFH6本体アセットを<b>読み取り対象</b>として扱います。
          レポート生成・HTML上の整理操作によってGameSave内のファイルを削除・移動・リネーム・上書きしません。
          出力先としてGameSave配下を指定した場合も、レポート生成前に拒否します。
        </p>
        <p>
          「削除候補」「基準から消えた」「判定状態を全消去」「古い候補を選択」は、
          すべてOrganizer側の整理・比較・選択に関する表現です。FH6側のペイントやGameSaveを削除する操作ではありません。
        </p>
      </section>
    </div>
  </div>
</div>

<div id="tagManagerModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel tag-manager-panel" role="dialog" aria-modal="true" aria-labelledby="tagManagerTitle">
    <div class="modal-head">
      <div>
        <h3 id="tagManagerTitle">選択中のタグを一括管理</h3>
        <div id="tagManagerSelectionSummary" class="small"></div>
      </div>
      <button data-close-modal="tagManagerModal">閉じる</button>
    </div>

    <div class="tag-manager-grid">
      <label class="tag-manager-field">
        <span>操作</span>
        <select id="tagManagerMode">
          <option value="add">タグを追加</option>
          <option value="remove">タグを削除</option>
          <option value="replace">タグを置換</option>
        </select>
      </label>

      <label id="tagManagerSourceWrap" class="tag-manager-field hidden">
        <span>対象タグ</span>
        <select id="tagManagerSource"></select>
      </label>

      <label id="tagManagerTargetWrap" class="tag-manager-field">
        <span id="tagManagerTargetLabel">追加するタグ</span>
        <input id="tagManagerTarget" type="text" autocomplete="off" data-modal-initial-focus
          placeholder="例: 痛車, レーシング">
      </label>

      <div id="tagManagerInfo" class="tag-manager-note">
        選択中のカードだけを変更します。追加はカンマ区切りで複数タグを指定できます。
        変更は「元に戻す / やり直す」の対象です。
      </div>

      <div class="tag-manager-actions">
        <button id="tagManagerApply" type="button">実行</button>
        <button type="button" data-close-modal="tagManagerModal">キャンセル</button>
      </div>
    </div>
  </div>
</div>
<div id="historyModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="historyTitle">
    <div class="modal-head"><h3 id="historyTitle">操作履歴</h3><button data-close-modal="historyModal">閉じる</button></div>
    <div id="historyBody"></div>
  </div>
</div>
<div id="userDataPreviewModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="userDataPreviewTitle">
    <div class="modal-head"><h3 id="userDataPreviewTitle">ユーザーデータ復元プレビュー</h3><button data-close-modal="userDataPreviewModal">閉じる</button></div>
    <div id="userDataPreviewBody"></div>
    <div class="restore-preview-actions">
      <button id="restoreMerge" type="button" data-modal-initial-focus>現在データと統合</button>
      <button id="restoreReplace" type="button">完全に置換</button>
      <button id="restoreCancel" type="button">キャンセル</button>
    </div>
  </div>
</div>
<div id="diagnosticsModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="diagnosticsTitle">
    <div class="modal-head"><h3 id="diagnosticsTitle">動作診断</h3><button data-close-modal="diagnosticsModal">閉じる</button></div>
    <div class="small">UI機能に加えて、レポート内データとサムネイル参照の整合性も確認します。</div>
    <div id="diagnosticsBody"></div>
  </div>
</div>
<div id="compareModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel compare-panel" role="dialog" aria-modal="true" aria-labelledby="compareModalTitle">
    <div class="modal-head">
      <div>
        <h3 id="compareModalTitle">類似ペイント比較</h3>
        <div id="compareSummary" class="small compare-summary"></div>
      </div>
      <button data-close-modal="compareModal">閉じる</button>
    </div>
    <div class="compare-actions">
      <button id="compareSelectOlder" type="button">古い候補を選択（最新以外）</button>
      <button id="compareSelectAll" type="button">比較候補をすべて選択</button>
      <button id="compareClearSelection" type="button">比較候補の選択解除</button>
      <button id="compareFh6Move" type="button" disabled aria-keyshortcuts="F" title="Fキーでも実行できます">FH6で選択デザインへ移動</button>
      <span id="compareSelectionCount" class="small compare-selection-count"></span>
    </div>
    <div id="compareGrid" class="compare-grid"></div>
  </div>
</div>
<div id="exactDuplicateModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel exact-duplicate-panel" role="dialog" aria-modal="true" aria-labelledby="exactDuplicateModalTitle">
    <div class="modal-head">
      <div>
        <h3 id="exactDuplicateModalTitle">再DL重複を整理</h3>
        <div id="exactDuplicateSummary" class="small compare-summary"></div>
      </div>
      <button data-close-modal="exactDuplicateModal">閉じる</button>
    </div>
    <div class="exact-duplicate-nav">
      <button id="exactDuplicatePrev" type="button">← 前の重複</button>
      <button id="exactDuplicateNext" type="button">次の重複 →</button>
      <button id="exactDuplicateFh6Move" type="button" disabled aria-keyshortcuts="F" title="Fキーでも実行できます">FH6で選択デザインへ移動</button>
      <span id="exactDuplicateGroupPosition" class="small"></span>
    </div>
    <div id="exactDuplicateGrid" class="compare-grid"></div>
    <div class="small" style="margin-top:10px">「これを残す」はOrganizer上の整理状態だけを変更します。FH6のGameSaveからペイントを削除しません。</div>
  </div>
</div>
<div id="fh6TempDeletedModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="fh6TempDeletedTitle">
    <div class="modal-head">
      <div>
        <h3 id="fh6TempDeletedTitle">FH6削除済み（仮）</h3>
        <div class="small">FH6で削除したデザインをこのHTML上だけ一時的に除外しています。元のGameSaveは変更しません。</div>
      </div>
      <button data-close-modal="fh6TempDeletedModal">閉じる</button>
    </div>
    <div id="fh6TempDeletedBody"></div>
    <div class="fh6-temp-delete-modal-actions">
      <button id="fh6TempDeletedRestoreAll" type="button">全件を元に戻す</button>
    </div>
  </div>
</div>
<div id="detailModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="detailTitle"><div class="modal-head"><h3 id="detailTitle">詳細</h3><button data-close-modal="detailModal">閉じる</button></div><div id="detailBody"></div></div>
</div>
<div id="removedModal" class="modal hidden" aria-hidden="true">
  <div class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="removedTitle">
    <div class="modal-head">
      <div>
        <h3 id="removedTitle">前回基準との差分</h3>
        <div class="small">保存済みの新規判定基準と今回のレポートを比較します。</div>
      </div>
      <button data-close-modal="removedModal">閉じる</button>
    </div>
    <div id="removedBody"></div>
  </div>
</div>
<div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="サムネイル拡大表示" aria-hidden="true">
  <button id="lightboxClose" type="button" aria-label="閉じる">×</button>
  <img id="lightboxImage" alt="">
</div>
<script>
const FH6_BUILD = "v{VERSION}";
const REPORT_LOCALE = {json.dumps(report_locale, ensure_ascii=False)};
const REPORT_FALLBACK_UNKNOWN_ERROR = {json.dumps(report_fallback_unknown_error, ensure_ascii=False)};
const REPORT_FALLBACK_PROMISE_ERROR = {json.dumps(report_fallback_promise_error, ensure_ascii=False)};
const REPORT_FALLBACK_UNKNOWN_DATE = {json.dumps(report_fallback_unknown_date, ensure_ascii=False)};
const REPORT_FALLBACK_UNKNOWN_VEHICLE = {json.dumps(report_fallback_unknown_vehicle, ensure_ascii=False)};
const REPORT_FALLBACK_NO_TITLE = {json.dumps(report_fallback_no_title, ensure_ascii=False)};
const REPORT_FALLBACK_TITLE = {json.dumps(report_fallback_title, ensure_ascii=False)};
const REPORT_LABEL_NEWEST = {json.dumps(report_label_newest, ensure_ascii=False)};
const REPORT_LABEL_OLDEST = {json.dumps(report_label_oldest, ensure_ascii=False)};
const REPORT_BASELINE_NOT_SET = {json.dumps(report_baseline_not_set, ensure_ascii=False)};
const REPORT_BASELINE_PREFIX = {json.dumps(report_baseline_prefix, ensure_ascii=False)};
const REPORT_ITEM_SUFFIX = {json.dumps(report_item_suffix, ensure_ascii=False)};

function reportRuntimeError(message) {{
  const status = document.getElementById("uiStatus");
  const banner = document.getElementById("runtimeErrorBanner");
  const messageEl = document.getElementById("runtimeErrorMessage");
  if (status) {{
    status.textContent = "エラー";
    status.dataset.state = "error";
  }}
  if (messageEl) messageEl.textContent = "JavaScriptエラー: " + String(message || REPORT_FALLBACK_UNKNOWN_ERROR);
  if (banner) banner.classList.remove("hidden");
  if (document.readyState !== "loading") {{
    try {{ updateStartupReadiness(); }} catch (_) {{}}
  }}
}}

window.addEventListener("error", event => {{
  reportRuntimeError(event.message || event.error || REPORT_FALLBACK_UNKNOWN_ERROR);
}});
window.addEventListener("unhandledrejection", event => {{
  reportRuntimeError(event.reason || REPORT_FALLBACK_PROMISE_ERROR);
}});

const memoryStorage = new Map();
let persistentStorage = null;
try {{
  const probeKey = "__fh6_storage_probe__";
  window.localStorage.setItem(probeKey, "1");
  window.localStorage.removeItem(probeKey);
  persistentStorage = window.localStorage;
}} catch (_) {{
  persistentStorage = null;
}}

function storageGet(key) {{
  if (persistentStorage) {{
    try {{ return persistentStorage.getItem(key); }}
    catch (_) {{ persistentStorage = null; }}
  }}
  return memoryStorage.has(String(key)) ? memoryStorage.get(String(key)) : null;
}}

function storageSet(key, value) {{
  if (persistentStorage) {{
    try {{
      persistentStorage.setItem(key, value);
      return;
    }} catch (_) {{
      persistentStorage = null;
    }}
  }}
  memoryStorage.set(String(key), String(value));
}}

function storageRemove(key) {{
  if (persistentStorage) {{
    try {{
      persistentStorage.removeItem(key);
      return;
    }} catch (_) {{
      persistentStorage = null;
    }}
  }}
  memoryStorage.delete(String(key));
}}

function storageGetMigrated(currentKey, legacyKeys = []) {{
  const current = storageGet(currentKey);
  if (current !== null) return current;
  for (const legacyKey of legacyKeys) {{
    const legacy = storageGet(legacyKey);
    if (legacy !== null) {{
      storageSet(currentKey, legacy);
      legacyKeys.forEach(key => storageRemove(key));
      return legacy;
    }}
  }}
  return null;
}}

function updateStorageStatus() {{
  const el = document.getElementById("storageStatus");
  if (!el) return;
  if (persistentStorage) {{
    el.textContent = "ブラウザ保存";
    el.title = "localStorageを使用しています";
  }} else {{
    el.textContent = "一時メモリ";
    el.title = "localStorageが利用できないため、このタブを閉じると未バックアップの変更は失われます";
  }}
}}

const STORAGE_PREFIX = "livery-organizer-for-fh6-decision:";
const LEGACY_STORAGE_PREFIXES = ["fh6-livery-decision:", "fh6-livery-v02:"];
const FH6_MY_DESIGN_INSTANCES = {fh6_instance_json};
const FH6_TEMP_DELETE_STORAGE_KEY = "livery-organizer-for-fh6-temp-deleted:{fh6_temp_delete_scope}";
const LEGACY_FH6_TEMP_DELETE_STORAGE_KEYS = ["fh6-my-design-temp-deleted:{fh6_temp_delete_scope}"];
let fh6TempDeletedInstanceIds = new Set();
let FH6_CURRENT_MY_DESIGN_INSTANCES = [];

function loadFh6TempDeletedInstanceIds() {{
  try {{
    const value = JSON.parse(storageGetMigrated(FH6_TEMP_DELETE_STORAGE_KEY, LEGACY_FH6_TEMP_DELETE_STORAGE_KEYS) || "[]");
    const validIds = new Set((Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES : [])
      .map(instance => String(instance.instance_id || ""))
      .filter(Boolean));
    return new Set((Array.isArray(value) ? value : []).map(String).filter(id => validIds.has(id)));
  }} catch (_) {{
    return new Set();
  }}
}}

function saveFh6TempDeletedInstanceIds() {{
  storageSet(FH6_TEMP_DELETE_STORAGE_KEY, JSON.stringify([...fh6TempDeletedInstanceIds]));
}}

function rebuildCurrentFh6MyDesignInstances() {{
  const source = (Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES : [])
    .filter(instance => !fh6TempDeletedInstanceIds.has(String(instance.instance_id || "")));
  const totalColumns = Math.max(1, Math.ceil(source.length / 2));
  const width = Math.max(3, String(totalColumns).length);
  FH6_CURRENT_MY_DESIGN_INSTANCES = source.map((instance, index) => {{
    const slotNumber = index + 1;
    const column = Math.ceil(slotNumber / 2);
    const row = slotNumber % 2 === 1 ? "U" : "D";
    return {{
      ...instance,
      original_slot_number:Number(instance.slot_number || 0),
      original_position:String(instance.position || ""),
      slot_number:slotNumber,
      column,
      row,
      position:`#${{String(column).padStart(width, "0")}}${{row}}`,
    }};
  }});
  return FH6_CURRENT_MY_DESIGN_INSTANCES;
}}

fh6TempDeletedInstanceIds = loadFh6TempDeletedInstanceIds();
rebuildCurrentFh6MyDesignInstances();

function migrateLegacyDecision(card) {{
  const currentKey = STORAGE_PREFIX + card.dataset.key;
  if (storageGet(currentKey)) return;
  for (const prefix of LEGACY_STORAGE_PREFIXES) {{
    const oldKey = prefix + card.dataset.key;
    const oldValue = storageGet(oldKey);
    if (oldValue) {{
      storageSet(currentKey, oldValue);
      LEGACY_STORAGE_PREFIXES.forEach(legacyPrefix => storageRemove(legacyPrefix + card.dataset.key));
      return;
    }}
  }}
}}
const cards = [...document.querySelectorAll(".card")];
// v0.4.58-r15 rev3 — 1000件近いレポートでも検索中にlocalStorage読込や
// 静的文字列の正規化を繰り返さないよう、ページ内だけで使うキャッシュを持ちます。
// ユーザーデータ変更時は applyCardMeta() がメタ情報キャッシュを即時更新します。
const CARD_META_CACHE = new WeakMap();
const CARD_SEARCH_STATIC_CACHE = new WeakMap();
let flatSortOrderCache = [];
let flatSortOrderMode = "";
const VEHICLE_CARDS = new Map();
cards.forEach(card => {{
  const carId = String(card.dataset.car || "");
  if (!VEHICLE_CARDS.has(carId)) VEHICLE_CARDS.set(carId, []);
  VEHICLE_CARDS.get(carId).push(card);
}});
function vehicleProgressInfo(carId) {{
  const members = VEHICLE_CARDS.get(String(carId || "")) || [];
  const keep = members.filter(card => getState(card) === "keep").length;
  const deleted = members.filter(card => getState(card) === "delete").length;
  const decided = keep + deleted;
  const total = members.length;
  const undecided = Math.max(0, total - decided);
  const percent = total ? Math.round(decided / total * 100) : 0;
  const state = decided === 0
    ? "none"
    : decided >= total && total > 0
      ? "complete"
      : "partial";
  const rank = state === "none" ? 0 : state === "partial" ? 1 : 2;
  return {{members, keep, deleted, decided, total, undecided, percent, state, rank}};
}}
function vehicleProgressStateForCard(card) {{
  return vehicleProgressInfo(card?.dataset?.car).state;
}}

function collectCardStateSummary() {{
  const summary = {{
    keep:0, deleted:0, undecided:0, decided:0,
    favorite:0, review:0, newCount:0, similar:0, exactDuplicate:0, total:0
  }};
  cards.forEach(card => {{
    if (fh6CardIsTempDeleted(card)) return;
    summary.total++;
    const state = getState(card);
    if (state === "keep") summary.keep++;
    else if (state === "delete") summary.deleted++;
    else summary.undecided++;
    const meta = loadCardMeta(card);
    if (meta.favorite) summary.favorite++;
    if (meta.reviewLater) summary.review++;
    if (card.dataset.isNew === "1") summary.newCount++;
    if (Number(card.dataset.similarCount || 0) >= 2) summary.similar++;
    if (card.dataset.exactDuplicate === "1") summary.exactDuplicate++;
  }});
  summary.decided = summary.keep + summary.deleted;
  return summary;
}}
const CSV_RECORDS = {csv_export_json};
const q = document.getElementById("q");
const filter = document.getElementById("decisionFilter");
const progressFilter = document.getElementById("progressFilter");
const vehicleFilter = document.getElementById("vehicleFilter");
const makeFilter = document.getElementById("makeFilter");
const yearFilter = document.getElementById("yearFilter");
const creatorFilter = document.getElementById("creatorFilter");
const paintCountFilter = document.getElementById("paintCountFilter");
const vinylCountFilter = document.getElementById("vinylCountFilter"); // v0.4.2移行元の参照専用
const vinylMinInput = document.getElementById("vinylMin");
const vinylMaxInput = document.getElementById("vinylMax");
const tagFilter = document.getElementById("tagFilter");
const creatorQuickSearch = document.getElementById("creatorQuickSearch");
const sortOrder = document.getElementById("sortOrder");
let similarOnlyMode = false;
let similarKindMode = "all";
let exactDuplicateOnlyMode = false;
const SIMILAR_KIND_LABELS = Object.freeze({{
  all:"すべて",
  image:"画像一致",
  "creator-title":"同一作者・同名"
}});
function normalizeSimilarKind(value) {{
  const kind = String(value || "all");
  return Object.prototype.hasOwnProperty.call(SIMILAR_KIND_LABELS, kind) ? kind : "all";
}}
let newOnlyMode = false;
let favoriteOnlyMode = false;
let reviewOnlyMode = false;
let selectedOnlyMode = false;
let sequentialReviewMode = false;
let tagMatchMode = "or";
const selectedKeys = new Set();
const META_PREFIX = "livery-organizer-for-fh6-meta:";
const LEGACY_META_PREFIXES = ["fh6-livery-meta:"];
const SCAN_STATE_KEY = "livery-organizer-for-fh6-scan-state-v1";
const LEGACY_SCAN_STATE_KEYS = ["fh6-livery-scan-state-v1"];
const USERDATA_VERSION = 2;
const BACKUP_STATUS_KEY = "livery-organizer-for-fh6-backup-status-v1";
const LEGACY_BACKUP_STATUS_KEYS = ["fh6-livery-backup-status-v1"];
const BACKUP_STATUS_VERSION = 2;
const undoStack = [];
const redoStack = [];
const MAX_UNDO = 100;
let pendingUserData = null;
let creatorSearchRestoreOpen = null;

const multiFilterSelects = [
  filter, progressFilter, vehicleFilter, makeFilter, yearFilter, creatorFilter,
  paintCountFilter, tagFilter
];
const detailFilterSelects = [filter, progressFilter, tagFilter];

function normalizeFilterValues(raw) {{
  const source = Array.isArray(raw)
    ? raw
    : raw instanceof Set
      ? [...raw]
      : raw === undefined || raw === null
        ? []
        : [raw];
  const values = source
    .map(value => String(value ?? "").trim())
    .filter(value => value && value !== "all");
  return [...new Set(values)];
}}

function selectedFilterValues(select) {{
  if (!select) return [];
  return normalizeFilterValues([...select.selectedOptions].map(option => option.value));
}}

function setFilterValues(select, values) {{
  if (!select) return;
  const requested = normalizeFilterValues(values);
  const wanted = new Set(requested);
  let matched = 0;
  [...select.options].forEach(option => {{
    const selected = option.value !== "all" && wanted.has(option.value);
    option.selected = selected;
    if (selected) matched++;
  }});
  const allOption = [...select.options].find(option => option.value === "all");
  if (allOption) allOption.selected = matched === 0;
}}

function unfinishedVehiclesShortcutActive() {{
  const values = new Set(selectedFilterValues(progressFilter));
  return values.size === 2 && values.has("none") && values.has("partial");
}}

function vehicleProgressStateShortcutActive(state) {{
  const values = selectedFilterValues(progressFilter);
  return values.length === 1 && values[0] === String(state || "");
}}

function vehicleProgressSummary() {{
  const summary = {{none:0, partial:0, complete:0, total:0}};
  VEHICLE_CARDS.forEach((_, carId) => {{
    const state = vehicleProgressInfo(carId).state;
    if (Object.prototype.hasOwnProperty.call(summary, state)) summary[state]++;
    summary.total++;
  }});
  return summary;
}}

function updateVehicleWorkflowQuickUi(summary = null) {{
  const unfinishedActive = unfinishedVehiclesShortcutActive();
  document.querySelectorAll("[data-unfinished-vehicles-toggle]").forEach(button => {{
    button.classList.toggle("active", unfinishedActive);
    button.setAttribute("aria-pressed", unfinishedActive ? "true" : "false");
  }});

  const progressSummary = summary || vehicleProgressSummary();
  const countIds = {{
    none:"vehicleProgressNoneCount",
    partial:"vehicleProgressPartialCount",
    complete:"vehicleProgressCompleteCount"
  }};
  document.querySelectorAll("[data-vehicle-progress-state]").forEach(button => {{
    const state = String(button.dataset.vehicleProgressState || "");
    const active = vehicleProgressStateShortcutActive(state);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    const count = document.getElementById(countIds[state]);
    if (count) count.textContent = String(progressSummary[state] || 0);
  }});

}}

function visibleVehicleSequence(visible = cardsInCurrentDisplayOrder()) {{
  const vehicleOrder = [];
  const firstVisibleByVehicle = new Map();
  const visibleByVehicle = new Map();
  visible.forEach(card => {{
    const carId = String(card.dataset.car || "");
    if (!carId) return;
    if (!visibleByVehicle.has(carId)) visibleByVehicle.set(carId, []);
    visibleByVehicle.get(carId).push(card);
    if (firstVisibleByVehicle.has(carId)) return;
    firstVisibleByVehicle.set(carId, card);
    vehicleOrder.push(carId);
  }});
  return {{visible, vehicleOrder, firstVisibleByVehicle, visibleByVehicle}};
}}

function visibleVehicleNavigationState() {{
  const sequence = visibleVehicleSequence();
  const unfinishedOrder = sequence.vehicleOrder.filter(carId => vehicleProgressInfo(carId).state !== "complete");
  let activeCard = document.querySelector(".card.keyboard-active");
  if (activeCard && !sequence.visible.includes(activeCard)) {{
    activeCard.classList.remove("keyboard-active");
    activeCard = null;
  }}
  const currentCarId = String(activeCard?.dataset?.car || "");
  const unfinishedIndex = currentCarId ? unfinishedOrder.indexOf(currentCarId) : -1;
  return {{...sequence, unfinishedOrder, activeCard, currentCarId, unfinishedIndex}};
}}

function updateVehicleNavigationUi(summary = null) {{
  document.querySelectorAll(".car-group.vehicle-navigation-current").forEach(group =>
    group.classList.remove("vehicle-navigation-current"));
  document.querySelectorAll("[data-group-progress][aria-current='true']").forEach(button =>
    button.removeAttribute("aria-current"));

  const nav = visibleVehicleNavigationState();
  const progressSummary = summary || vehicleProgressSummary();
  const hint = document.getElementById("vehicleWorkflowHint");
  const hasUnfinished = nav.unfinishedOrder.length > 0;
  const hasAdjacentUnfinished = hasUnfinished
    && !(nav.unfinishedOrder.length === 1 && nav.currentCarId === nav.unfinishedOrder[0]);
  document.querySelectorAll("[data-first-unfinished-vehicle]").forEach(button => {{
    button.disabled = !hasUnfinished;
  }});
  document.querySelectorAll("[data-previous-unfinished-vehicle], [data-next-unfinished-vehicle]").forEach(button => {{
    button.disabled = !hasAdjacentUnfinished;
  }});
  if (!hint) return nav;

  hint.dataset.navigationState = "idle";
  if (nav.activeCard && nav.currentCarId) {{
    const group = [...document.querySelectorAll(".car-group")].find(item =>
      String(item.dataset.carGroup || "") === nav.currentCarId) || null;
    group?.classList.add("vehicle-navigation-current");
    group?.querySelector("[data-group-progress]")?.setAttribute("aria-current", "true");

    if (nav.unfinishedIndex >= 0) {{
      hint.textContent = `未完了 ${{nav.unfinishedIndex + 1}} / ${{nav.unfinishedOrder.length}}車種 · 全 ${{progressSummary.total}}車種`;
      hint.dataset.navigationState = "current";
    }} else if (vehicleProgressInfo(nav.currentCarId).state === "complete") {{
      hint.textContent = `現在 完了 · 未完了 ${{nav.unfinishedOrder.length}}車種 · 全 ${{progressSummary.total}}車種`;
      hint.dataset.navigationState = "complete";
    }} else {{
      hint.textContent = `未完了 ${{nav.unfinishedOrder.length}}車種 · 全 ${{progressSummary.total}}車種`;
    }}
  }} else {{
    hint.textContent = `未完了 ${{nav.unfinishedOrder.length}}車種 · 全 ${{progressSummary.total}}車種`;
  }}
  return nav;
}}

function setVehicleProgressOnly(state) {{
  const target = String(state || "");
  if (!["none", "partial", "complete"].includes(target)) return;
  const enable = !vehicleProgressStateShortcutActive(target);
  setFilterValues(progressFilter, enable ? [target] : []);
  applyAndPersist();
}}

function setUnfinishedVehiclesOnly(enabled) {{
  setFilterValues(progressFilter, enabled ? ["none", "partial"] : []);
  applyAndPersist();
}}

function clearCriteriaForVehicleFocus() {{
  q.value = "";
  multiFilterSelects.forEach(select => setFilterValues(select, []));
  setFilterValues(vinylCountFilter, []);
  if (vinylMinInput) vinylMinInput.value = "";
  if (vinylMaxInput) vinylMaxInput.value = "";
  tagMatchMode = "or";
  updateTagModeUi();
  similarOnlyMode = false;
  similarKindMode = "all";
  exactDuplicateOnlyMode = false;
  newOnlyMode = false;
  favoriteOnlyMode = false;
  reviewOnlyMode = false;
  selectedOnlyMode = false;
  document.getElementById("similarOnly")?.classList.remove("active");
  document.getElementById("newOnly")?.classList.remove("active");
  document.getElementById("favoriteOnly")?.classList.remove("active");
  document.getElementById("reviewOnly")?.classList.remove("active");
  document.getElementById("selectedOnly")?.classList.remove("active");
}}

function showOnlyVehicleFromProgress(carId) {{
  const target = String(carId || "");
  if (!target || !VEHICLE_CARDS.has(target)) return;
  clearCriteriaForVehicleFocus();
  setFilterValues(vehicleFilter, [target]);
  applyAndPersist();
  const visibleMembers = cardsInCurrentDisplayOrder().filter(card => String(card.dataset.car || "") === target);
  const focusTarget = visibleMembers.find(card => getState(card) === "undecided") || visibleMembers[0] || null;
  if (focusTarget) focusKeyboardCard(focusTarget);
  else window.scrollTo({{top:0, behavior:"smooth"}});
}}

function normalizeNativeMultiSelection(select) {{
  if (!select?.multiple) return;
  const nonAll = [...select.selectedOptions].filter(option => option.value !== "all");
  const allOption = [...select.options].find(option => option.value === "all");
  if (nonAll.length) {{
    if (allOption) allOption.selected = false;
  }} else if (allOption) {{
    allOption.selected = true;
  }}
}}

function toggleFilterValue(select, value) {{
  if (!select) return;
  if (!value || value === "all") {{
    setFilterValues(select, []);
    return;
  }}
  const current = new Set(selectedFilterValues(select));
  if (current.has(value)) current.delete(value); else current.add(value);
  setFilterValues(select, [...current]);
}}

function selectedFilterLabels(select, stripPrefixes = false) {{
  const values = new Set(selectedFilterValues(select));
  return [...select.options]
    .filter(option => option.value !== "all" && values.has(option.value))
    .map(option => {{
      let label = String(option.dataset.baseLabel || option.textContent || option.value || "")
        .replace(/\\s+\\([^)]*(?:件|車種)[^)]*\\)\\s*$/, "");
      if (stripPrefixes) label = label.replace(/^(車種|メーカー|作成者|年式|整理進捗|ペイント件数|タグ): */, "");
      return label;
    }});
}}

function restoreFilterValues(select, value) {{
  const values = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  const existing = new Set([...select.options].map(option => option.value));
  setFilterValues(select, values.filter(item => existing.has(String(item))));
}}

function parseOptionalNumber(value) {{
  const text = String(value ?? "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}}

// 静的項目の索引。判定・タグ・お気に入りなどの動的項目は都度評価しますが、
// 車種・メーカー・年式・作成者・ペイント件数の候補走査は、
// より小さい索引済みカード集合から開始できます。
const FILTER_INDEX = {{vehicle:new Map(), make:new Map(), year:new Map(), creator:new Map(), paintCount:new Map()}};
function addFilterIndex(indexName, value, card) {{
  if (value === undefined || value === null || value === "") return;
  const key = String(value);
  const map = FILTER_INDEX[indexName];
  if (!map.has(key)) map.set(key, new Set());
  map.get(key).add(card);
}}
cards.forEach(card => {{
  addFilterIndex("vehicle", card.dataset.car, card);
  addFilterIndex("make", normFilterValue(card.dataset.make), card);
  addFilterIndex("year", String(card.dataset.year || "").trim(), card);
  addFilterIndex("creator", normFilterValue(card.dataset.creator), card);
  addFilterIndex("paintCount", Number(card.dataset.paintCount || 0), card);
}});

function indexedCandidateCards(overrides = {{}}) {{
  const pick = (name, current) =>
    Object.prototype.hasOwnProperty.call(overrides, name) ? overrides[name] : current;
  const dimensions = [
    ["vehicle", normalizeFilterValues(pick("vehicle", selectedFilterValues(vehicleFilter)))],
    ["make", normalizeFilterValues(pick("make", selectedFilterValues(makeFilter))).map(normFilterValue)],
    ["year", normalizeFilterValues(pick("year", selectedFilterValues(yearFilter)))],
    ["creator", normalizeFilterValues(pick("creator", selectedFilterValues(creatorFilter))).map(normFilterValue)],
    ["paintCount", normalizeFilterValues(pick("paintCount", selectedFilterValues(paintCountFilter))).map(Number).filter(Number.isFinite)]
  ];
  const dimensionSets = [];
  dimensions.forEach(([name, values]) => {{
    if (!values.length) return;
    const union = new Set();
    values.forEach(value => FILTER_INDEX[name].get(String(value))?.forEach(card => union.add(card)));
    dimensionSets.push(union);
  }});
  if (!dimensionSets.length) return cards;
  dimensionSets.sort((a,b)=>a.size-b.size);
  return [...dimensionSets[0]].filter(card => dimensionSets.every(set => set.has(card)));
}}

function addOptions(select, values, labeler = v => v, counter = null) {{
  [...values].filter(Boolean).sort((a,b) =>
    String(a).localeCompare(String(b), "ja", {{numeric:true, sensitivity:"base"}})
  ).forEach(value => {{
    const option = document.createElement("option");
    option.value = value;
    const count = counter ? counter(value) : null;
    option.textContent = count === null
      ? labeler(value)
      : `${{labeler(value)}} (${{count}}件)`;
    select.appendChild(option);
  }});
}}

const totalPaintCount = cards.length;
const totalCarGroupCount = document.querySelectorAll(".car-group").length;

const vehicleCounts = new Map();
const vehicleLabels = new Map();
cards.forEach(card => {{
  const carId = String(card.dataset.car || "");
  if (!carId) return;
  vehicleCounts.set(carId, (vehicleCounts.get(carId) || 0) + 1);
  const record = CSV_RECORDS[card.dataset.key];
  if (!vehicleLabels.has(carId)) {{
    vehicleLabels.set(carId, record?.vehicle || `Car ID ${{carId.padStart(4, "0")}}`);
  }}
}});
[...vehicleCounts.keys()]
  .sort((a,b) => String(vehicleLabels.get(a) || a).localeCompare(
    String(vehicleLabels.get(b) || b), "ja", {{numeric:true, sensitivity:"base"}}
  ))
  .forEach(carId => {{
    const option = document.createElement("option");
    option.value = carId;
    option.textContent = `${{vehicleLabels.get(carId)}} (${{vehicleCounts.get(carId) || 0}}件)`;
    vehicleFilter.appendChild(option);
  }});
if (vehicleFilter.options.length) {{
  vehicleFilter.options[0].textContent =
    `車種 すべて (${{vehicleCounts.size}}車種 / ${{totalPaintCount}}件)`;
}}

const makeCounts = new Map();
const makeLabels = new Map();
cards.forEach(card => {{
  const make = card.dataset.make;
  if (!make) return;
  makeCounts.set(make, (makeCounts.get(make) || 0) + 1);
  const record = CSV_RECORDS[card.dataset.key];
  if (!makeLabels.has(make)) makeLabels.set(make, record?.manufacturer || make);
}});
addOptions(
  makeFilter,
  new Set(cards.map(c => c.dataset.make).filter(Boolean)),
  v => `メーカー: ${{makeLabels.get(v) || v}}`,
  v => makeCounts.get(v) || 0
);

const yearCounts = new Map();
cards.forEach(card => {{
  const year = card.dataset.year;
  if (year && year !== "0") yearCounts.set(year, (yearCounts.get(year) || 0) + 1);
}});
addOptions(
  yearFilter,
  new Set(cards.map(c => c.dataset.year).filter(v => v && v !== "0")),
  v => `年式: ${{v}}`,
  v => yearCounts.get(v) || 0
);

const creatorCounts = new Map();
const creatorLabels = new Map();
cards.forEach(card => {{
  const creator = card.dataset.creator;
  if (!creator) return;
  creatorCounts.set(creator, (creatorCounts.get(creator) || 0) + 1);
  const record = CSV_RECORDS[card.dataset.key];
  if (!creatorLabels.has(creator)) creatorLabels.set(creator, record?.creator || creator);
}});
addOptions(
  creatorFilter,
  new Set(cards.map(c => c.dataset.creator).filter(Boolean)),
  v => `作成者: ${{creatorLabels.get(v) || v}}`,
  v => creatorCounts.get(v) || 0
);

if (makeFilter.options.length) {{
  makeFilter.options[0].textContent = `メーカー: すべて (${{totalPaintCount}}件)`;
}}
if (yearFilter.options.length) {{
  yearFilter.options[0].textContent = `年式: すべて (${{totalPaintCount}}件)`;
}}
if (creatorFilter.options.length) {{
  creatorFilter.options[0].textContent = `作成者: すべて (${{totalPaintCount}}件)`;
}}
if (paintCountFilter.options.length) {{
  paintCountFilter.options[0].textContent =
    `ペイント件数: すべて (${{totalCarGroupCount}}車種 / ${{totalPaintCount}}件)`;
}}
if (vinylCountFilter.options.length) {{
  vinylCountFilter.options[0].textContent =
    `バイナル数: すべて (${{totalPaintCount}}件)`;
}}

[...paintCountFilter.options].forEach(option => {{
  if (option.value === "all") return;
  const countValue = Number(option.value);
  const matchingGroups = [...document.querySelectorAll(".car-group")]
    .filter(group => Number(group.dataset.paintCount || 0) === countValue);
  const matchingPaints = matchingGroups.reduce(
    (sum, group) => sum + group.querySelectorAll(".card").length,
    0
  );
  option.textContent =
    `ペイント件数: ${{countValue}}件 (${{matchingGroups.length}}車種 / ${{matchingPaints}}件)`;
}});

// 並び順の表示はシンプルな固定文言にする。
// バイナル数の選択肢は実データから生成する。
// 1,000以下は100刻み、1,000を超えたら最大でも1,000刻みにする。
const vinylValues = cards
  .map(card => Number(card.dataset.vinylCount || -1))
  .filter(value => Number.isFinite(value) && value >= 0);

if (vinylValues.length) {{
  const maxVinyl = Math.max(...vinylValues);
  const vinylThresholds = [];

  const lowMax = Math.min(maxVinyl, 1000);
  for (let threshold = 100; threshold <= lowMax; threshold += 100) {{
    vinylThresholds.push(threshold);
  }}

  if (maxVinyl > 1000) {{
    for (let threshold = 1000; threshold <= maxVinyl; threshold += 1000) {{
      if (!vinylThresholds.includes(threshold)) vinylThresholds.push(threshold);
    }}
  }}

  vinylThresholds.forEach(threshold => {{
    const count = vinylValues.filter(value => value >= threshold).length;
    if (count <= 0) return;
    const option = document.createElement("option");
    option.value = String(threshold);
    option.textContent =
      `バイナル数: ${{threshold.toLocaleString(REPORT_LOCALE)}}以上 (${{count}}件)`;
    vinylCountFilter.appendChild(option);
  }});
  if (vinylMinInput) vinylMinInput.max = String(maxVinyl);
  if (vinylMaxInput) vinylMaxInput.max = String(maxVinyl);
}}



function actionLabel(action) {{
  if (action?.label) return action.label;
  if (action?.type === "bulk") return `一括操作 (${{action.items?.length || 0}}件)`;
  if (action?.type === "state") return "整理状態を変更";
  if (action?.type === "meta") return "タグ・メモ等を変更";
  return "操作";
}}

function updateUndoRedoUi() {{
  const undo = document.getElementById("undoAction");
  const redo = document.getElementById("redoAction");
  if (undo) {{
    undo.disabled = undoStack.length === 0;
    undo.title = undoStack.length ? `元に戻す: ${{actionLabel(undoStack.at(-1))}}` : "";
  }}
  if (redo) {{
    redo.disabled = redoStack.length === 0;
    redo.title = redoStack.length ? `やり直す: ${{actionLabel(redoStack.at(-1))}}` : "";
  }}
}}

function pushUndo(action) {{
  undoStack.push(action);
  if (undoStack.length > MAX_UNDO) undoStack.shift();
  redoStack.length = 0;
  updateUndoRedoUi();
}}

function captureInverse(snapshot) {{
  if (!snapshot) return null;
  if (snapshot.type === "state") {{
    const card = cards.find(c => c.dataset.key === snapshot.key);
    if (!card) return null;
    return {{type:"state", key:snapshot.key, previous:getState(card), label:snapshot.label}};
  }}
  if (snapshot.type === "meta") {{
    const card = cards.find(c => c.dataset.key === snapshot.key);
    if (!card) return null;
    return {{type:"meta", key:snapshot.key, previous:loadCardMeta(card), label:snapshot.label}};
  }}
  if (snapshot.type === "bulk") {{
    return {{
      type:"bulk",
      label:snapshot.label,
      items:(snapshot.items || []).map(captureInverse).filter(Boolean)
    }};
  }}
  return null;
}}

function restoreSnapshot(snapshot) {{
  if (!snapshot) return;
  if (snapshot.type === "state") {{
    const card = cards.find(c => c.dataset.key === snapshot.key);
    if (!card) return;
    if (snapshot.previous === "undecided") storageRemove(stateKey(card));
    else storageSet(stateKey(card), snapshot.previous);
    paintState(card);
  }} else if (snapshot.type === "meta") {{
    const card = cards.find(c => c.dataset.key === snapshot.key);
    if (!card) return;
    const previous = snapshot.previous || {{}};
    if (Object.keys(previous).length) storageSet(metaKey(card), JSON.stringify(previous));
    else storageRemove(metaKey(card));
    applyCardMeta(card);
  }} else if (snapshot.type === "bulk") {{
    (snapshot.items || []).forEach(item => restoreSnapshot(item));
  }}
}}

function finishHistoryChange() {{
  rebuildTagFilter();
  refreshOrganizerUi({{mobile:true, persist:true}});
  updateUndoRedoUi();
}}

function undoLast() {{
  const action = undoStack.pop();
  if (!action) return;
  const inverse = captureInverse(action);
  restoreSnapshot(action);
  if (inverse) {{
    redoStack.push(inverse);
    if (redoStack.length > MAX_UNDO) redoStack.shift();
  }}
  finishHistoryChange();
}}

function redoLast() {{
  const action = redoStack.pop();
  if (!action) return;
  const inverse = captureInverse(action);
  restoreSnapshot(action);
  if (inverse) {{
    undoStack.push(inverse);
    if (undoStack.length > MAX_UNDO) undoStack.shift();
  }}
  finishHistoryChange();
}}

function renderHistory() {{
  const body = document.getElementById("historyBody");
  const undoRows = undoStack.slice(-20).reverse().map((action, index) =>
    `<div class="history-row"><span>${{index + 1}}. ${{actionLabel(action)}}</span><small>元に戻せます</small></div>`
  ).join("");
  const redoRows = redoStack.slice(-20).reverse().map((action, index) =>
    `<div class="history-row"><span>${{index + 1}}. ${{actionLabel(action)}}</span><small>やり直せます</small></div>`
  ).join("");
  body.innerHTML = `
    <p><b>Undo</b> ${{undoStack.length}}件 / <b>Redo</b> ${{redoStack.length}}件</p>
    <h4>元に戻せる操作</h4>
    <div class="history-list">${{undoRows || "<span class='small'>履歴なし</span>"}}</div>
    <h4>やり直せる操作</h4>
    <div class="history-list">${{redoRows || "<span class='small'>履歴なし</span>"}}</div>`;
}}

function metaKey(card) {{ return META_PREFIX + card.dataset.key; }}
function loadCardMeta(card, forceReload = false) {{
  if (!forceReload && CARD_META_CACHE.has(card)) return CARD_META_CACHE.get(card);
  let meta = {{}};
  try {{
    const legacyKeys = LEGACY_META_PREFIXES.map(prefix => prefix + card.dataset.key);
    const parsed = JSON.parse(storageGetMigrated(metaKey(card), legacyKeys) || "{{}}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) meta = parsed;
  }} catch (_) {{}}
  CARD_META_CACHE.set(card, meta);
  return meta;
}}
function saveCardMeta(card, patch, recordUndo = true) {{
  const previous = loadCardMeta(card);
  const next = {{...previous, ...patch}};
  if (recordUndo) {{
    const label = Object.prototype.hasOwnProperty.call(patch, "favorite") ? "お気に入りを変更"
      : Object.prototype.hasOwnProperty.call(patch, "reviewLater") ? "後で確認を変更"
      : Object.prototype.hasOwnProperty.call(patch, "tags") ? "タグを変更"
      : Object.prototype.hasOwnProperty.call(patch, "note") ? "メモを変更"
      : "ユーザーデータを変更";
    pushUndo({{type:"meta", key:card.dataset.key, previous, label}});
  }}
  storageSet(metaKey(card), JSON.stringify(next));
  applyCardMeta(card);
  rebuildTagFilter();
  if (typeof refreshBackupUi === "function") refreshBackupUi();
}}
function applyCardMeta(card) {{
  // storageを書き換えた直後にも必ず最新値をキャッシュへ取り込みます。
  const meta = loadCardMeta(card, true);
  card.classList.toggle("favorite", Boolean(meta.favorite));
  card.classList.toggle("review-later", Boolean(meta.reviewLater));
  const fav = card.querySelector(".favorite-toggle");
  const review = card.querySelector(".review-toggle");
  if (fav) {{ fav.classList.toggle("active", Boolean(meta.favorite)); fav.textContent = meta.favorite ? "★ お気に入り" : "☆ お気に入り"; }}
  if (review) review.classList.toggle("active", Boolean(meta.reviewLater));
  const tag = card.querySelector(".tag-input");
  const note = card.querySelector(".note-input");
  if (tag && document.activeElement !== tag) tag.value = meta.tags || "";
  if (note && document.activeElement !== note) note.value = meta.note || "";
  card.dataset.tags = String(meta.tags || "").toLowerCase();
}}
function rebuildTagFilter() {{
  const current = selectedFilterValues(tagFilter);
  const tags = new Map();
  cards.forEach(card => {{
    String(card.dataset.tags || "").split(",").map(x=>x.trim()).filter(Boolean)
      .forEach(tag => tags.set(tag,(tags.get(tag)||0)+1));
  }});
  tagFilter.innerHTML = `<option value="all" data-base-label="タグ: すべて">タグ: すべて (${{cards.length}}件)</option>`;
  [...tags.entries()].sort((a,b)=>a[0].localeCompare(b[0],REPORT_LOCALE)).forEach(([tag,count]) => {{
    const option = document.createElement("option");
    option.value = tag;
    option.dataset.baseLabel = `タグ: ${{tag}}`;
    option.textContent = `${{option.dataset.baseLabel}} (${{count}}件)`;
    tagFilter.appendChild(option);
  }});
  setFilterValues(tagFilter, current);
  if (typeof renderDetailFilterChoices === "function") renderDetailFilterChoices(tagFilter);
}}
function stateKey(card) {{
  return STORAGE_PREFIX + card.dataset.key;
}}

function getState(card) {{
  migrateLegacyDecision(card);
  return storageGet(stateKey(card)) || "undecided";
}}

function setState(card, state, recordUndo = true) {{
  const previous = getState(card);
  if (recordUndo && previous !== state) {{
    const labels = {{keep:"残す", delete:"削除候補", undecided:"未決定"}};
    pushUndo({{type:"state", key:card.dataset.key, previous, label:`${{labels[state] || state}}に変更`}});
  }}
  if (state === "undecided") {{
    storageRemove(stateKey(card));
  }} else {{
    storageSet(stateKey(card), state);
  }}
  paintState(card);
  refreshOrganizerUi({{persist:true}});
}}

function paintState(card) {{
  const state = getState(card);
  card.dataset.decision = state;
  card.querySelectorAll(".decision button").forEach(btn => {{
    btn.classList.toggle("active", btn.dataset.state === state);
  }});
}}

cards.forEach(card => {{
  paintState(card);
  card.querySelectorAll(".decision button").forEach(btn => {{
    btn.addEventListener("click", () => setState(card, btn.dataset.state));
  }});
}});

function cardSortValue(card, key) {{
  if (key === "year") return Number(card.dataset.year || 0);
  if (key === "carid") return Number(card.dataset.car || 0);
  if (key === "paintcount") return Number(card.dataset.paintCount || 0);
  if (key === "vinylcount") return Number(card.dataset.vinylCount || -1);
  return (card.dataset[key] || "").toLocaleLowerCase();
}}

function compareCards(a, b, key, direction = "asc") {{
  const av = cardSortValue(a, key);
  const bv = cardSortValue(b, key);
  let result;
  if (typeof av === "number" && typeof bv === "number") {{
    result = av - bv;
  }} else {{
    result = String(av).localeCompare(String(bv), "ja", {{
      numeric: true,
      sensitivity: "base"
    }});
  }}
  return direction === "desc" ? -result : result;
}}

function fh6TempDeletedInstances() {{
  const deleted = fh6TempDeletedInstanceIds;
  return (Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES : [])
    .filter(instance => deleted.has(String(instance.instance_id || "")))
    .sort((a, b) => Number(a.slot_number || 0) - Number(b.slot_number || 0));
}}

function fh6CardIsTempDeleted(card) {{
  if (!card || !fh6TempDeletedInstanceIds.size) return false;
  const key = String(card.dataset.key || "");
  const liveryId = String(card.dataset.liveryId || "");
  const timestamp = String(card.dataset.timestamp || "");
  let matching = (Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES : []).filter(instance =>
    String(instance.ui_key || instance.fingerprint || "") === key
    && (!liveryId || String(instance.livery_id || "") === liveryId)
    && (!timestamp || String(instance.timestamp_raw || "") === timestamp)
  );
  if (!matching.length) {{
    matching = (Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES : []).filter(instance =>
      String(instance.ui_key || instance.fingerprint || "") === key
      && (!liveryId || String(instance.livery_id || "") === liveryId)
    );
  }}
  return matching.length > 0
    && matching.every(instance => fh6TempDeletedInstanceIds.has(String(instance.instance_id || "")));
}}

function updateFh6TempDeletedUi() {{
  const count = fh6TempDeletedInstanceIds.size;
  const button = document.getElementById("fh6TempDeletedReview");
  const number = document.getElementById("fh6TempDeletedCount");
  if (number) number.textContent = String(count);
  if (button) button.classList.toggle("hidden", count === 0);
  const restoreAll = document.getElementById("fh6TempDeletedRestoreAll");
  if (restoreAll) restoreAll.disabled = count === 0;
}}

// v0.4.60-r02: 「FH6削除済み（仮）」は全ソート共通の操作です。
// FH6マイデザイン順では従来どおり見出し横、それ以外では共通操作領域へ同じボタンを移動します。
function placeFh6TempDeletedReview() {{
  const button = document.getElementById("fh6TempDeletedReview");
  if (!button) return;
  const useMyDesignHost = sortOrder?.value === "fh6-my-designs";
  const host = document.getElementById(
    useMyDesignHost ? "fh6TempDeletedReviewMyDesignHost" : "fh6TempDeletedReviewGlobalHost"
  );
  if (host && button.parentElement !== host) host.appendChild(button);
}}

function renderFh6TempDeletedModal() {{
  const body = document.getElementById("fh6TempDeletedBody");
  if (!body) return;
  const items = fh6TempDeletedInstances();
  body.replaceChildren();
  if (!items.length) {{
    const empty = document.createElement("div");
    empty.className = "fh6-temp-delete-empty";
    empty.textContent = "一時的に非表示にしているデザインはありません。";
    body.appendChild(empty);
    updateFh6TempDeletedUi();
    return;
  }}

  const list = document.createElement("div");
  list.className = "fh6-temp-delete-list";
  const width = Math.max(3, String(Math.max(1, FH6_MY_DESIGN_INSTANCES.length)).length);
  items.forEach(instance => {{
    const row = document.createElement("div");
    row.className = "fh6-temp-delete-row";
    const main = document.createElement("div");
    main.className = "fh6-temp-delete-row-main";
    const title = document.createElement("div");
    title.className = "fh6-temp-delete-row-title";
    const vehicle = String(instance.vehicle_label || `Car ID ${{instance.car_id || "—"}}`);
    const paintTitle = String(instance.title || "").trim();
    title.textContent = paintTitle ? `${{vehicle}} — ${{paintTitle}}` : vehicle;
    const meta = document.createElement("div");
    meta.className = "fh6-temp-delete-row-meta";
    const creator = String(instance.creator || "").trim();
    meta.textContent = `生成時 #${{String(instance.slot_number || 0).padStart(width, "0")}} / ${{String(instance.position || "—")}}${{creator ? ` · ${{creator}}` : ""}}`;
    main.append(title, meta);

    const restore = document.createElement("button");
    restore.type = "button";
    restore.textContent = "元に戻す";
    restore.addEventListener("click", () => restoreFh6TempDeletedInstance(String(instance.instance_id || "")));
    row.append(main, restore);
    list.appendChild(row);
  }});
  body.appendChild(list);
  updateFh6TempDeletedUi();
}}

function refreshFh6AfterTempDelete(message = "") {{
  rebuildCurrentFh6MyDesignInstances();
  ensureFh6NavigatorTargetStillValid();
  syncAllFh6CardPositionLabels();
  clearFh6VehicleMatchSelection();
  hideFh6VehicleSuggestions();
  updateFh6TempDeletedUi();
  // v0.4.60-r02: refreshFilteredView() 単独では、作成者順やカード単位の
  // フラットソートからカードを元グループへ戻した後に現在レイアウトを再構築しません。
  // 通常の全UI更新経路を通し、どのソート順でも仮削除後の表示を保ちます。
  refreshOrganizerUi({{backup:false, mobile:false, persist:false}});
  if (sortOrder?.value === "fh6-my-designs" && message) {{
    setFh6MyDesignJumpStatus(message);
  }}
  renderFh6TempDeletedModal();
}}

function markFh6InstanceTempDeleted(instanceId) {{
  const id = String(instanceId || "");
  if (!id || fh6TempDeletedInstanceIds.has(id)) return false;
  const instance = (Array.isArray(FH6_CURRENT_MY_DESIGN_INSTANCES) ? FH6_CURRENT_MY_DESIGN_INSTANCES : [])
    .find(item => String(item.instance_id || "") === id);
  if (!instance) return false;
  const removedSlot = Number(instance.slot_number || 0);
  const removedPosition = String(instance.position || "—");
  fh6TempDeletedInstanceIds.add(id);
  saveFh6TempDeletedInstanceIds();
  refreshFh6AfterTempDelete(
    `${{removedPosition}}（#${{removedSlot}}）をFH6削除済みとして一時非表示にしました。残りの位置を再計算しました。`
  );
  return true;
}}

function restoreFh6TempDeletedInstance(instanceId) {{
  const id = String(instanceId || "");
  if (!id || !fh6TempDeletedInstanceIds.has(id)) return false;
  fh6TempDeletedInstanceIds.delete(id);
  saveFh6TempDeletedInstanceIds();
  refreshFh6AfterTempDelete("1件を元に戻し、実スロット番号とFH6位置を再計算しました。");
  return true;
}}

function restoreAllFh6TempDeletedInstances() {{
  if (!fh6TempDeletedInstanceIds.size) return false;
  fh6TempDeletedInstanceIds.clear();
  saveFh6TempDeletedInstanceIds();
  refreshFh6AfterTempDelete("仮削除をすべて元に戻しました。");
  return true;
}}

function ensureFh6TempDeleteButton(card, instance) {{
  if (!card || !instance) return;
  let button = card.querySelector(".fh6-temp-delete-action");
  if (!button) {{
    button = document.createElement("button");
    button.type = "button";
    button.className = "pill fh6-temp-delete-action";
    button.textContent = "FH6で削除済み";
    button.title = "FH6でこのデザインを削除した後、現在のHTML上でも一時的に除外して位置を詰め直します";
    const top = card.querySelector(".topline");
    if (top) top.appendChild(button);
  }}
  button.dataset.fh6InstanceId = String(instance.instance_id || "");
  button.onclick = event => {{
    event.preventDefault();
    event.stopPropagation();
    markFh6InstanceTempDeleted(button.dataset.fh6InstanceId);
  }};
}}

function restoreFh6SnapshotPositionLabel(card) {{
  if (!card) return;
  const originalSlot = Number(card.dataset.myDesignIndex || 0);
  const slotLabel = card.querySelector(".my-design-index");
  const positionLabel = card.querySelector(".fh6-my-design-position");
  if (originalSlot > 0) {{
    const slotWidth = Math.max(3, String(Math.max(1, cards.length)).length);
    const column = Math.ceil(originalSlot / 2);
    const row = originalSlot % 2 === 1 ? "U" : "D";
    const columnWidth = Math.max(3, String(Math.max(1, Math.ceil(cards.length / 2))).length);
    if (slotLabel) slotLabel.textContent = `#${{String(originalSlot).padStart(slotWidth, "0")}}`;
    if (positionLabel) positionLabel.textContent = `#${{String(column).padStart(columnWidth, "0")}}${{row}}`;
  }}
}}

function restoreCardsToGroups() {{
  cards.forEach(card => {{
    const owner = card.dataset.ownerGroup || card.dataset.car;
    if (!owner) return;
    card.dataset.ownerGroup = owner;
    const grid = document.querySelector(
      `.car-group[data-car-group="${{owner}}"] .grid`
    );
    if (grid && card.parentElement !== grid) {{
      grid.appendChild(card);
    }}
    syncFh6CardPositionLabels(card);
  }});
  const fh6Track = document.getElementById("fh6MyDesignTrack");
  if (fh6Track) fh6Track.replaceChildren();
}}

let fh6MyDesignCurrentColumn = 1;
let fh6MyDesignScrollTimer = null;
let fh6MyDesignWheelAccumulator = 0;
let fh6MyDesignWheelResetTimer = null;
let fh6MyDesignWheelLocked = false;

function fh6MyDesignVisibleColumns() {{
  return [...document.querySelectorAll("#fh6MyDesignTrack .fh6-my-design-column:not(.hidden)")];
}}

function fh6MyDesignColumnScrollLeft(column) {{
  const viewport = document.getElementById("fh6MyDesignViewport");
  if (!viewport || !column) return 0;
  const viewportRect = viewport.getBoundingClientRect();
  const columnRect = column.getBoundingClientRect();
  return viewport.scrollLeft + (columnRect.left - viewportRect.left);
}}

function updateFh6MyDesignTailSpace() {{
  const viewport = document.getElementById("fh6MyDesignViewport");
  const track = document.getElementById("fh6MyDesignTrack");
  const columns = fh6MyDesignVisibleColumns();
  if (!viewport || !track) return;
  if (!columns.length) {{
    track.style.paddingRight = "0px";
    return;
  }}
  const columnWidth = columns[0].getBoundingClientRect().width;
  // 最終列も左端まで移動できるだけの余白を末尾に確保します。
  track.style.paddingRight = `${{Math.max(0, viewport.clientWidth - columnWidth)}}px`;
}}

function nearestFh6MyDesignColumn() {{
  const viewport = document.getElementById("fh6MyDesignViewport");
  const columns = fh6MyDesignVisibleColumns();
  if (!viewport || !columns.length) return null;
  const left = viewport.scrollLeft;
  return columns.reduce((best, column) =>
    Math.abs(fh6MyDesignColumnScrollLeft(column) - left) < Math.abs(fh6MyDesignColumnScrollLeft(best) - left) ? column : best
  , columns[0]);
}}

function updateFh6MyDesignPositionUi(column = null) {{
  const position = document.getElementById("fh6MyDesignPosition");
  const count = document.getElementById("fh6MyDesignCount");
  const track = document.getElementById("fh6MyDesignTrack");
  const instanceCards = track ? [...track.querySelectorAll(".card")] : [];
  const visibleCards = instanceCards.filter(card => !card.classList.contains("hidden")).length;
  const columns = fh6MyDesignVisibleColumns();
  if (count) count.textContent = `${{visibleCards}} / ${{FH6_CURRENT_MY_DESIGN_INSTANCES.length}}件 · ${{columns.length}}列表示`;
  const current = column || nearestFh6MyDesignColumn();
  if (!current) {{
    if (position) position.textContent = "—";
    return;
  }}
  fh6MyDesignCurrentColumn = Number(current.dataset.fh6Column || 1);
  const visibleIndex = Math.max(0, columns.indexOf(current));
  // #001 のような上下なし番号はカード側と重複するため表示しません。
  if (position) position.textContent = `${{visibleIndex + 1}} / ${{columns.length}}列`;
}}

function syncFh6MyDesignColumnVisibility() {{
  const columns = [...document.querySelectorAll("#fh6MyDesignTrack .fh6-my-design-column")];
  columns.forEach(column => {{
    const anyVisible = [...column.querySelectorAll(".card")].some(card => !card.classList.contains("hidden"));
    column.classList.toggle("hidden", !anyVisible);
  }});
  requestAnimationFrame(() => {{
    updateFh6MyDesignTailSpace();
    updateFh6MyDesignPositionUi();
  }});
}}

function scrollToFh6MyDesignColumn(column, behavior = "smooth") {{
  const viewport = document.getElementById("fh6MyDesignViewport");
  if (!viewport || !column) return;
  fh6MyDesignCurrentColumn = Number(column.dataset.fh6Column || 1);
  updateFh6MyDesignTailSpace();
  const left = fh6MyDesignColumnScrollLeft(column);
  viewport.scrollTo({{left, behavior}});
  updateFh6MyDesignPositionUi(column);
}}

function moveFh6MyDesignColumn(direction = 1) {{
  const columns = fh6MyDesignVisibleColumns();
  if (!columns.length) return;

  // ボタン/キー操作では、アニメーション途中のscrollLeftではなく、
  // 直前に確定した列番号を基準に1列だけ移動します。
  let index = columns.findIndex(column => Number(column.dataset.fh6Column || 0) === fh6MyDesignCurrentColumn);
  if (index < 0) {{
    const current = nearestFh6MyDesignColumn();
    index = current ? columns.indexOf(current) : 0;
  }}
  if (index < 0) index = 0;

  const step = direction < 0 ? -1 : 1;
  const nextIndex = (index + step + columns.length) % columns.length;
  // ボタン/矢印キーは必ず1列単位で確実に移動させるため即時スクロールにします。
  // 端では剰余計算により反対側へ循環します。
  scrollToFh6MyDesignColumn(columns[nextIndex], "auto");
}}

let fh6MyDesignJumpHighlightTimer = null;
let fh6VehicleMatchCarId = null;
let fh6VehicleMatchSlotNumbers = [];
let fh6VehicleMatchIndex = -1;
let fh6VehicleMatchLabel = "";
let fh6VehicleMatchMode = "";
let fh6VehicleMatchVehicleCount = 0;
let fh6VehicleSuggestionIndex = -1;

function setFh6MyDesignJumpStatus(message = "", state = "") {{
  const nav = document.getElementById("fh6VehicleMatchNav");
  const status = document.getElementById("fh6VehicleMatchState");
  if (!status) return;
  status.textContent = message;
  if (state) status.dataset.state = state;
  else delete status.dataset.state;
  if (nav) nav.classList.toggle("hidden", !message && !fh6VehicleMatchSlotNumbers.length);
}}

function normalizeFh6MyDesignJumpText(value) {{
  return String(value || "")
    .trim()
    .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 0xFEE0))
    .replace(/＃/g, "#")
    .replace(/\\s+/g, "")
    .replace(/[／/・\\-ー]/g, "");
}}

function normalizeFh6VehicleSearchText(value) {{
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase(REPORT_LOCALE)
    .trim()
    .replace(/\\s+/g, " ");
}}

function looksLikeFh6PositionJump(value) {{
  const text = normalizeFh6MyDesignJumpText(value);
  return /^#?\\d+(?:[UDud])?$/.test(text);
}}

function resolveFh6MyDesignJumpTarget(rawValue) {{
  const text = normalizeFh6MyDesignJumpText(rawValue);
  if (!text) return {{error:"移動位置を入力してください。"}};

  const totalSlots = Array.isArray(FH6_CURRENT_MY_DESIGN_INSTANCES) ? FH6_CURRENT_MY_DESIGN_INSTANCES.length : 0;
  const totalColumns = Math.ceil(totalSlots / 2);

  const positionMatch = text.match(/^#?(\\d+)([UDud])$/);
  if (positionMatch) {{
    const column = Number(positionMatch[1]);
    const row = positionMatch[2].toUpperCase();
    if (!Number.isInteger(column) || column < 1 || column > totalColumns) {{
      return {{error:`列番号は1〜${{totalColumns}}で指定してください。`}};
    }}
    const slotNumber = (column - 1) * 2 + (row === "U" ? 1 : 2);
    if (slotNumber > totalSlots) {{
      return {{error:`#${{String(column).padStart(Math.max(3, String(totalColumns).length), "0")}}${{row}} にはペイントがありません。`}};
    }}
    return {{column, row, slotNumber}};
  }}

  const slotMatch = text.match(/^#?(\\d+)$/);
  if (!slotMatch) {{
    return {{error:"537 / #537 または #269U / #269D の形式で指定してください。"}};
  }}
  const slotNumber = Number(slotMatch[1]);
  if (!Number.isInteger(slotNumber) || slotNumber < 1 || slotNumber > totalSlots) {{
    return {{error:`実スロット番号は1〜${{totalSlots}}で指定してください。`}};
  }}
  return {{
    column:Math.ceil(slotNumber / 2),
    row:slotNumber % 2 === 1 ? "U" : "D",
    slotNumber,
  }};
}}

function fh6VehicleGroups() {{
  const groups = new Map();
  (Array.isArray(FH6_CURRENT_MY_DESIGN_INSTANCES) ? FH6_CURRENT_MY_DESIGN_INSTANCES : []).forEach(instance => {{
    const carId = Number(instance.car_id || 0);
    if (!carId) return;
    let group = groups.get(carId);
    if (!group) {{
      const label = String(instance.vehicle_label || `Car ID ${{String(carId).padStart(4, "0")}}`);
      const make = String(instance.vehicle_make || "");
      const model = String(instance.vehicle_model || "");
      const year = Number(instance.vehicle_year || 0);
      const searchText = normalizeFh6VehicleSearchText([
        label, make, model, year > 0 ? String(year) : "", String(carId), `Car ID ${{carId}}`,
      ].filter(Boolean).join(" "));
      group = {{carId, label, make, model, year, searchText, instances:[]}};
      groups.set(carId, group);
    }}
    group.instances.push(instance);
  }});
  return [...groups.values()].sort((a, b) => {{
    const aSlot = Number(a.instances[0]?.slot_number || 0);
    const bSlot = Number(b.instances[0]?.slot_number || 0);
    return aSlot - bSlot || a.carId - b.carId;
  }});
}}

function matchingFh6Vehicles(rawValue) {{
  const query = normalizeFh6VehicleSearchText(rawValue);
  if (!query) return [];
  const terms = query.split(" ").filter(Boolean);
  return fh6VehicleGroups()
    .filter(group => terms.every(term => group.searchText.includes(term)))
    .sort((a, b) => {{
      const aLabel = normalizeFh6VehicleSearchText(a.label);
      const bLabel = normalizeFh6VehicleSearchText(b.label);
      const aExact = aLabel === query ? 0 : (aLabel.startsWith(query) ? 1 : 2);
      const bExact = bLabel === query ? 0 : (bLabel.startsWith(query) ? 1 : 2);
      if (aExact !== bExact) return aExact - bExact;
      return Number(a.instances[0]?.slot_number || 0) - Number(b.instances[0]?.slot_number || 0);
    }});
}}

function fh6VehicleSuggestionButtons() {{
  return [...document.querySelectorAll("#fh6MyDesignJumpSuggestions .fh6-vehicle-suggestion")];
}}

function clearFh6VehicleSuggestionSelection() {{
  fh6VehicleSuggestionIndex = -1;
  fh6VehicleSuggestionButtons().forEach(button => button.setAttribute("aria-selected", "false"));
  document.getElementById("fh6MyDesignJumpInput")?.removeAttribute("aria-activedescendant");
}}

function setFh6VehicleSuggestionIndex(index) {{
  const buttons = fh6VehicleSuggestionButtons();
  if (!buttons.length) {{
    fh6VehicleSuggestionIndex = -1;
    return null;
  }}
  const count = buttons.length;
  fh6VehicleSuggestionIndex = ((Number(index) % count) + count) % count;
  let active = null;
  buttons.forEach((button, i) => {{
    const selected = i === fh6VehicleSuggestionIndex;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) active = button;
  }});
  const input = document.getElementById("fh6MyDesignJumpInput");
  if (input && active?.id) input.setAttribute("aria-activedescendant", active.id);
  active?.scrollIntoView({{block:"nearest"}});
  return active;
}}

function hideFh6VehicleSuggestions() {{
  const suggestions = document.getElementById("fh6MyDesignJumpSuggestions");
  if (!suggestions) return;
  suggestions.classList.add("hidden");
  suggestions.replaceChildren();
  clearFh6VehicleSuggestionSelection();
}}

function renderFh6VehicleSuggestions(rawValue = null) {{
  const input = document.getElementById("fh6MyDesignJumpInput");
  const suggestions = document.getElementById("fh6MyDesignJumpSuggestions");
  if (!input || !suggestions) return [];
  const value = rawValue === null ? input.value : rawValue;
  if (!String(value || "").trim() || looksLikeFh6PositionJump(value)) {{
    hideFh6VehicleSuggestions();
    return [];
  }}

  const matches = matchingFh6Vehicles(value);
  suggestions.replaceChildren();
  clearFh6VehicleSuggestionSelection();
  matches.slice(0, 10).forEach((group, index) => {{
    const first = group.instances[0] || {{}};
    const button = document.createElement("button");
    button.type = "button";
    button.tabIndex = -1;
    button.className = "fh6-vehicle-suggestion";
    button.id = `fh6VehicleSuggestion${{index}}`;
    button.dataset.carId = String(group.carId);
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", "false");

    const label = document.createElement("span");
    label.className = "fh6-vehicle-suggestion-label";
    label.textContent = group.label;
    const meta = document.createElement("span");
    meta.className = "fh6-vehicle-suggestion-meta";
    meta.textContent = `${{group.instances.length}}件 · 最初 #${{String(first.slot_number || 0).padStart(Math.max(3, String(FH6_CURRENT_MY_DESIGN_INSTANCES.length).length), "0")}} / ${{String(first.position || "—")}}`;
    button.append(label, meta);
    button.addEventListener("click", () => selectFh6VehicleJump(group.carId));
    suggestions.appendChild(button);
  }});

  if (matches.length > 10) {{
    const more = document.createElement("div");
    more.className = "small";
    more.style.padding = "5px 8px";
    more.textContent = `ほか ${{matches.length - 10}}車種。文字を追加すると絞り込めます。`;
    suggestions.appendChild(more);
  }}
  suggestions.classList.toggle("hidden", matches.length === 0);
  return matches;
}}

function clearFh6VehicleMatchSelection() {{
  fh6VehicleMatchCarId = null;
  fh6VehicleMatchSlotNumbers = [];
  fh6VehicleMatchIndex = -1;
  fh6VehicleMatchLabel = "";
  fh6VehicleMatchMode = "";
  fh6VehicleMatchVehicleCount = 0;
  document.getElementById("fh6VehicleMatchNav")?.classList.add("hidden");
  const state = document.getElementById("fh6VehicleMatchState");
  if (state) {{
    state.textContent = "";
    delete state.dataset.state;
  }}
  const prev = document.getElementById("fh6VehicleMatchPrev");
  const next = document.getElementById("fh6VehicleMatchNext");
  if (prev) prev.hidden = true;
  if (next) next.hidden = true;
}}

function fh6ResolvedTargetFromSlotNumber(slotNumber) {{
  const value = Number(slotNumber || 0);
  if (!Number.isInteger(value) || value < 1 || value > FH6_CURRENT_MY_DESIGN_INSTANCES.length) return null;
  return {{
    column:Math.ceil(value / 2),
    row:value % 2 === 1 ? "U" : "D",
    slotNumber:value,
  }};
}}

function fh6SlotIsVisible(slotNumber) {{
  const target = fh6ResolvedTargetFromSlotNumber(slotNumber);
  if (!target) return false;
  const column = document.querySelector(`#fh6MyDesignTrack .fh6-my-design-column[data-fh6-column="${{target.column}}"]`);
  const card = column?.querySelector(`.fh6-my-design-slot[data-fh6-row="${{target.row}}"] .card`);
  return Boolean(column && card && !column.classList.contains("hidden") && !card.classList.contains("hidden"));
}}

function firstFh6VehicleSlot(group, preferVisible = true) {{
  const slots = (group?.instances || []).map(instance => Number(instance.slot_number || 0)).filter(Boolean);
  if (!slots.length) return 0;
  if (preferVisible) {{
    const visible = slots.find(fh6SlotIsVisible);
    if (visible) return visible;
  }}
  return slots[0];
}}

function focusFh6MyDesignTarget(target, options = {{}}) {{
  const input = document.getElementById("fh6MyDesignJumpInput");
  const column = document.querySelector(
    `#fh6MyDesignTrack .fh6-my-design-column[data-fh6-column="${{target.column}}"]`
  );
  const slot = column?.querySelector(`.fh6-my-design-slot[data-fh6-row="${{target.row}}"]`);
  const card = slot?.querySelector(".card");
  if (!column || !slot || !card) {{
    setFh6MyDesignJumpStatus("指定位置のカードを取得できませんでした。", "error");
    return false;
  }}
  if (column.classList.contains("hidden") || card.classList.contains("hidden")) {{
    setFh6MyDesignJumpStatus("現在の絞り込み条件では対象が非表示です。", "error");
    return false;
  }}

  scrollToFh6MyDesignColumn(column, "auto");
  const totalColumns = Math.ceil(FH6_CURRENT_MY_DESIGN_INSTANCES.length / 2);
  const positionLabel = `#${{String(target.column).padStart(Math.max(3, String(totalColumns).length), "0")}}${{target.row}}`;
  if (input && options.updateInput !== false) input.value = options.inputValue ?? positionLabel;

  clearTimeout(fh6MyDesignJumpHighlightTimer);
  document.querySelectorAll("#fh6MyDesignTrack .fh6-my-design-slot.fh6-jump-highlight")
    .forEach(item => item.classList.remove("fh6-jump-highlight"));
  slot.classList.add("fh6-jump-highlight");
  fh6MyDesignJumpHighlightTimer = setTimeout(() => {{
    slot.classList.remove("fh6-jump-highlight");
  }}, 1900);

  // ジャンプ後は、そのカードを既存のキーボード操作対象にします。
  // 入力欄にフォーカスが残るとカード用ショートカットが無効になるため、
  // Enter確定時などは入力欄からフォーカスを外します。
  document.querySelectorAll(".card.keyboard-active").forEach(item => item.classList.remove("keyboard-active"));
  card.classList.add("keyboard-active");
  if (card.closest("#fh6MyDesignTrack")) {{
    const instance = currentFh6InstanceForCard(card);
    if (instance) fh6NavigatorTargetInstanceId = String(instance.instance_id || "");
  }}
  updateVehicleNavigationUi();
  updateFh6NavigatorUi();
  if (document.activeElement === input) input.blur();

  setFh6MyDesignJumpStatus(options.statusMessage || `${{positionLabel}}（${{target.slotNumber}}件目）へ移動しました。`);
  return true;
}}

function jumpToFh6MyDesignPosition(rawValue = null) {{
  const input = document.getElementById("fh6MyDesignJumpInput");
  const value = rawValue === null ? input?.value : rawValue;
  const target = resolveFh6MyDesignJumpTarget(value);
  if (target.error) {{
    setFh6MyDesignJumpStatus(target.error, "error");
    return false;
  }}
  hideFh6VehicleSuggestions();
  clearFh6VehicleMatchSelection();
  return focusFh6MyDesignTarget(target);
}}

function updateFh6VehicleMatchNav() {{
  const nav = document.getElementById("fh6VehicleMatchNav");
  const state = document.getElementById("fh6VehicleMatchState");
  const prev = document.getElementById("fh6VehicleMatchPrev");
  const next = document.getElementById("fh6VehicleMatchNext");
  if (!nav || !state || !fh6VehicleMatchSlotNumbers.length) {{
    if (prev) prev.hidden = true;
    if (next) next.hidden = true;
    if (!state?.textContent) nav?.classList.add("hidden");
    return;
  }}
  const slotNumber = fh6VehicleMatchSlotNumbers[fh6VehicleMatchIndex] || fh6VehicleMatchSlotNumbers[0];
  const instance = FH6_CURRENT_MY_DESIGN_INSTANCES[slotNumber - 1] || {{}};
  const indexLabel = Math.max(0, fh6VehicleMatchIndex) + 1;
  if (fh6VehicleMatchMode === "query") {{
    const vehicleLabel = String(instance.vehicle_label || `Car ID ${{instance.car_id || "—"}}`);
    state.textContent = `${{fh6VehicleMatchLabel}} · ${{indexLabel}} / ${{fh6VehicleMatchSlotNumbers.length}}車種 · ${{vehicleLabel}} · #${{String(slotNumber).padStart(Math.max(3, String(FH6_CURRENT_MY_DESIGN_INSTANCES.length).length), "0")}} / ${{String(instance.position || "—")}}`;
  }} else {{
    state.textContent = `${{fh6VehicleMatchLabel}} · ${{indexLabel}} / ${{fh6VehicleMatchSlotNumbers.length}} · #${{String(slotNumber).padStart(Math.max(3, String(FH6_CURRENT_MY_DESIGN_INSTANCES.length).length), "0")}} / ${{String(instance.position || "—")}}`;
  }}
  delete state.dataset.state;
  if (prev) prev.hidden = false;
  if (next) next.hidden = false;
  nav.classList.remove("hidden");
}}

function jumpToFh6VehicleMatch(index) {{
  if (!fh6VehicleMatchSlotNumbers.length) return false;
  const count = fh6VehicleMatchSlotNumbers.length;
  fh6VehicleMatchIndex = ((Number(index) % count) + count) % count;
  const slotNumber = fh6VehicleMatchSlotNumbers[fh6VehicleMatchIndex];
  const target = fh6ResolvedTargetFromSlotNumber(slotNumber);
  if (!target) return false;
  const input = document.getElementById("fh6MyDesignJumpInput");
  const instance = FH6_CURRENT_MY_DESIGN_INSTANCES[slotNumber - 1] || {{}};
  const vehicleLabel = String(instance.vehicle_label || `Car ID ${{instance.car_id || "—"}}`);
  if (input && fh6VehicleMatchMode === "vehicle") input.value = fh6VehicleMatchLabel;
  updateFh6VehicleMatchNav();
  const positionLabel = String(instance.position || `#${{target.column}}${{target.row}}`);
  const slotLabel = `#${{String(slotNumber).padStart(Math.max(3, String(FH6_CURRENT_MY_DESIGN_INSTANCES.length).length), "0")}}`;
  const statusMessage = fh6VehicleMatchMode === "query"
    ? `${{fh6VehicleMatchLabel}} · ${{fh6VehicleMatchIndex + 1}} / ${{count}}車種 · ${{vehicleLabel}} · ${{slotLabel}} / ${{positionLabel}}`
    : `${{fh6VehicleMatchLabel}} · ${{fh6VehicleMatchIndex + 1}} / ${{count}} · ${{slotLabel}} / ${{positionLabel}}`;
  return focusFh6MyDesignTarget(target, {{
    updateInput:false,
    statusMessage,
  }});
}}

function moveFh6VehicleMatch(direction = 1) {{
  if (!fh6VehicleMatchSlotNumbers.length) return false;
  return jumpToFh6VehicleMatch(fh6VehicleMatchIndex + (direction < 0 ? -1 : 1));
}}

function selectFh6VehicleJump(carId) {{
  const group = fh6VehicleGroups().find(item => item.carId === Number(carId));
  if (!group) {{
    setFh6MyDesignJumpStatus("指定した車種を取得できませんでした。", "error");
    return false;
  }}
  hideFh6VehicleSuggestions();
  fh6VehicleMatchCarId = group.carId;
  fh6VehicleMatchSlotNumbers = group.instances.map(instance => Number(instance.slot_number || 0)).filter(Boolean);
  fh6VehicleMatchIndex = 0;
  fh6VehicleMatchLabel = group.label;
  fh6VehicleMatchMode = "vehicle";
  fh6VehicleMatchVehicleCount = 1;
  const input = document.getElementById("fh6MyDesignJumpInput");
  if (input) input.value = group.label;

  const firstVisibleIndex = fh6VehicleMatchSlotNumbers.findIndex(fh6SlotIsVisible);
  fh6VehicleMatchIndex = firstVisibleIndex >= 0 ? firstVisibleIndex : 0;
  updateFh6VehicleMatchNav();
  return jumpToFh6VehicleMatch(fh6VehicleMatchIndex);
}}

function selectFh6VehicleQueryJump(rawValue, matches = null) {{
  const queryText = String(rawValue || "").trim();
  const groups = Array.isArray(matches) ? matches : matchingFh6Vehicles(queryText);
  if (!groups.length) return false;

  const representativeSlots = groups
    .map(group => firstFh6VehicleSlot(group, true))
    .filter(Boolean);
  if (!representativeSlots.length) {{
    setFh6MyDesignJumpStatus("一致する車種の位置を取得できませんでした。", "error");
    return false;
  }}

  hideFh6VehicleSuggestions();
  fh6VehicleMatchCarId = null;
  fh6VehicleMatchSlotNumbers = representativeSlots;
  fh6VehicleMatchIndex = 0;
  fh6VehicleMatchLabel = `「${{queryText}}」一致`;
  fh6VehicleMatchMode = "query";
  fh6VehicleMatchVehicleCount = groups.length;
  const input = document.getElementById("fh6MyDesignJumpInput");
  if (input) input.value = queryText;

  const firstVisibleIndex = fh6VehicleMatchSlotNumbers.findIndex(fh6SlotIsVisible);
  fh6VehicleMatchIndex = firstVisibleIndex >= 0 ? firstVisibleIndex : 0;
  updateFh6VehicleMatchNav();
  return jumpToFh6VehicleMatch(fh6VehicleMatchIndex);
}}

function jumpToFh6MyDesignTarget(rawValue = null) {{
  const input = document.getElementById("fh6MyDesignJumpInput");
  const value = rawValue === null ? input?.value : rawValue;
  if (!String(value || "").trim()) {{
    setFh6MyDesignJumpStatus("位置または車種名を入力してください。", "error");
    return false;
  }}
  if (looksLikeFh6PositionJump(value)) return jumpToFh6MyDesignPosition(value);

  const selectedButton = fh6VehicleSuggestionIndex >= 0
    ? fh6VehicleSuggestionButtons()[fh6VehicleSuggestionIndex]
    : null;
  if (selectedButton?.dataset.carId) {{
    return selectFh6VehicleJump(Number(selectedButton.dataset.carId));
  }}

  const matches = matchingFh6Vehicles(value);
  if (!matches.length) {{
    hideFh6VehicleSuggestions();
    clearFh6VehicleMatchSelection();
    setFh6MyDesignJumpStatus("一致する車種がありません。車種名の一部を入力してください。", "error");
    return false;
  }}
  if (matches.length === 1) return selectFh6VehicleJump(matches[0].carId);
  return selectFh6VehicleQueryJump(value, matches);
}}

// =======================================================================
// v0.4.58-r08 — FH6移動対象の再読込復元
// =======================================================================
// 選択したFH6移動対象は同じ生成HTMLの再読込で復元します。
// 仮削除と同じレポート固有スコープを使い、新しく生成したHTMLへは引き継ぎません。
const FH6_NAVIGATOR_TARGET_STORAGE_KEY = "livery-organizer-for-fh6-move-target:{fh6_temp_delete_scope}";
let fh6NavigatorTargetInstanceId = "";

function loadFh6NavigatorTargetInstanceId() {{
  try {{
    const saved = String(storageGet(FH6_NAVIGATOR_TARGET_STORAGE_KEY) || "");
    if (!saved) return "";
    const valid = (Array.isArray(FH6_CURRENT_MY_DESIGN_INSTANCES) ? FH6_CURRENT_MY_DESIGN_INSTANCES : [])
      .some(instance => String(instance.instance_id || "") === saved);
    if (!valid) {{
      storageRemove(FH6_NAVIGATOR_TARGET_STORAGE_KEY);
      return "";
    }}
    return saved;
  }} catch (_) {{
    return "";
  }}
}}

function saveFh6NavigatorTargetInstanceId() {{
  try {{
    if (fh6NavigatorTargetInstanceId) {{
      storageSet(FH6_NAVIGATOR_TARGET_STORAGE_KEY, fh6NavigatorTargetInstanceId);
    }} else {{
      storageRemove(FH6_NAVIGATOR_TARGET_STORAGE_KEY);
    }}
  }} catch (_) {{}}
}}

fh6NavigatorTargetInstanceId = loadFh6NavigatorTargetInstanceId();

// =======================================================================
// v0.4.57-r20 — Organizer全体で共有するFH6移動対象
// =======================================================================

function currentFh6InstancesForCard(card) {{
  if (!card) return [];
  const current = Array.isArray(FH6_CURRENT_MY_DESIGN_INSTANCES) ? FH6_CURRENT_MY_DESIGN_INSTANCES : [];
  const explicitId = String(card.dataset.fh6InstanceId || card.dataset.fh6CurrentInstanceId || "");
  if (explicitId) {{
    const exact = current.find(instance => String(instance.instance_id || "") === explicitId);
    if (exact) return [exact];
  }}
  const key = String(card.dataset.key || "");
  const liveryId = String(card.dataset.liveryId || "");
  const timestamp = String(card.dataset.timestamp || "");
  const originalSlot = Number(card.dataset.myDesignIndex || 0);
  let matching = current.filter(instance =>
    String(instance.ui_key || instance.fingerprint || "") === key
    && (!liveryId || String(instance.livery_id || "") === liveryId)
    && (!timestamp || String(instance.timestamp_raw || "") === timestamp)
  );
  if (!matching.length) {{
    matching = current.filter(instance =>
      String(instance.ui_key || instance.fingerprint || "") === key
      && (!liveryId || String(instance.livery_id || "") === liveryId)
    );
  }}
  if (!matching.length && liveryId) {{
    matching = current.filter(instance =>
      String(instance.livery_id || "") === liveryId
      && (!timestamp || String(instance.timestamp_raw || "") === timestamp)
    );
  }}
  if (matching.length > 1 && originalSlot > 0) {{
    const byOriginalSlot = matching.find(instance => Number(instance.original_slot_number || 0) === originalSlot);
    if (byOriginalSlot) return [byOriginalSlot];
  }}
  return matching;
}}

function currentFh6InstanceForCard(card) {{
  return currentFh6InstancesForCard(card)[0] || null;
}}

function fh6LocationForInstance(instance) {{
  const total = Math.max(0, FH6_CURRENT_MY_DESIGN_INSTANCES.length);
  const slotNumber = Number(instance?.slot_number || 0);
  if (!(slotNumber > 0) || slotNumber > total) return null;
  const slotWidth = Math.max(3, String(Math.max(1, total)).length);
  return {{
    instance,
    slotNumber,
    slotLabel:`#${{String(slotNumber).padStart(slotWidth, "0")}}`,
    position:String(instance.position || "—"),
    instanceId:String(instance.instance_id || ""),
  }};
}}

function fh6LocationForCard(card) {{
  return fh6LocationForInstance(currentFh6InstanceForCard(card));
}}

function syncFh6CardPositionLabels(card) {{
  if (!card) return;
  const slotButton = card.querySelector(".my-design-index");
  const positionButton = card.querySelector(".fh6-my-design-position");
  const location = fh6LocationForCard(card);
  if (!location) {{
    card.dataset.fh6CurrentInstanceId = "";
    card.dataset.fh6CurrentSlot = "";
    card.dataset.fh6CurrentPosition = "";
    card.querySelector(".fh6-temp-delete-action")?.remove();
    if (slotButton) {{
      slotButton.textContent = "FH6位置なし";
      slotButton.disabled = true;
      slotButton.dataset.fh6MoveTargetInstance = "";
      slotButton.setAttribute("aria-pressed", "false");
      slotButton.title = "現在のFH6マイデザイン実スロットには存在しません";
    }}
    if (positionButton) {{
      positionButton.textContent = "#---";
      positionButton.disabled = true;
      positionButton.dataset.fh6MoveTargetInstance = "";
      positionButton.setAttribute("aria-pressed", "false");
      positionButton.classList.add("hidden");
    }}
    return;
  }}
  card.dataset.fh6CurrentInstanceId = location.instanceId;
  card.dataset.fh6CurrentSlot = String(location.slotNumber);
  card.dataset.fh6CurrentPosition = location.position;
  // v0.4.60-r01: FH6移動対象と同じ現在instanceを使い、すべてのソート順で
  // 「FH6で削除済み」を利用できるようにします。
  ensureFh6TempDeleteButton(card, location.instance);
  const selected = location.instanceId === fh6NavigatorTargetInstanceId;
  [slotButton, positionButton].forEach(button => {{
    if (!button) return;
    button.disabled = false;
    button.dataset.fh6MoveTargetInstance = location.instanceId;
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }});
  const targetTitle = selected
    ? `${{location.slotLabel}} / ${{location.position}} のFH6移動対象を解除`
    : `${{location.slotLabel}} / ${{location.position}} をFH6移動対象に設定`;
  if (slotButton) {{
    slotButton.textContent = location.slotLabel;
    slotButton.title = targetTitle;
  }}
  if (positionButton) {{
    positionButton.classList.remove("hidden");
    positionButton.textContent = location.position;
    positionButton.title = targetTitle;
  }}
}}

function syncAllFh6CardPositionLabels() {{
  document.querySelectorAll(".card").forEach(card => syncFh6CardPositionLabels(card));
}}

function selectedFh6NavigatorInstance() {{
  if (!fh6NavigatorTargetInstanceId) return null;
  return FH6_CURRENT_MY_DESIGN_INSTANCES.find(instance =>
    String(instance.instance_id || "") === fh6NavigatorTargetInstanceId
  ) || null;
}}

function ensureFh6NavigatorTargetStillValid() {{
  if (!fh6NavigatorTargetInstanceId) return true;
  if (selectedFh6NavigatorInstance()) return true;
  fh6NavigatorTargetInstanceId = "";
  saveFh6NavigatorTargetInstanceId();
  return false;
}}

function setFh6NavigatorTargetInstance(instance) {{
  const location = fh6LocationForInstance(instance);
  if (!location) return false;
  fh6NavigatorTargetInstanceId = location.instanceId;
  saveFh6NavigatorTargetInstanceId();
  syncAllFh6CardPositionLabels();
  updateFh6NavigatorUi();
  return true;
}}

function setFh6NavigatorTargetByCard(card) {{
  return setFh6NavigatorTargetInstance(currentFh6InstanceForCard(card));
}}

// =======================================================================
// v0.4.58-r11 — FH6移動対象の明示的な選択解除
// =======================================================================
function clearFh6NavigatorTarget() {{
  if (!fh6NavigatorTargetInstanceId) return false;
  fh6NavigatorTargetInstanceId = "";
  saveFh6NavigatorTargetInstanceId();
  syncAllFh6CardPositionLabels();
  updateFh6NavigatorUi(false);
  return true;
}}

function fh6LocationButtonsHtml(card) {{
  const location = fh6LocationForCard(card);
  if (!location) return `<span class="compare-badge">FH6位置なし</span>`;
  const selected = location.instanceId === fh6NavigatorTargetInstanceId;
  const pressed = selected ? "true" : "false";
  const title = selected ? "クリックしてFH6移動対象の選択を解除" : "クリックしてFH6移動対象に設定";
  return `<div class="fh6-location-buttons" aria-label="FH6移動位置">
    <span class="fh6-location-caption">FH6移動:</span>
    <button type="button" class="fh6-location-button" data-fh6-move-target-instance="${{escapeCompareHtml(location.instanceId)}}" aria-pressed="${{pressed}}" title="${{title}}">${{escapeCompareHtml(location.slotLabel)}}</button>
    <button type="button" class="fh6-location-button" data-fh6-move-target-instance="${{escapeCompareHtml(location.instanceId)}}" aria-pressed="${{pressed}}" title="${{title}}">${{escapeCompareHtml(location.position)}}</button>
  </div>`;
}}

const FH6_NAVIGATOR_SETTINGS_KEY = "navigator-bridge-for-fh6-settings-v1";
const LEGACY_FH6_NAVIGATOR_SETTINGS_KEYS = ["fh6-my-designs-navigator-settings-v1"];
const FH6_NAVIGATOR_DEFAULTS = Object.freeze({{
  intervalMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["interval_ms"]:g},
  switchDelayMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["switch_delay_ms"]:g},
  turnDelayMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["turn_delay_ms"]:g},
  wrapDelayMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["wrap_delay_ms"]:g},
  resetOrigin:{str(NAVIGATOR_SHARED_SETTINGS_DEFAULTS["reset_origin"]).lower()},
  resetEscDelayMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["reset_esc_delay_ms"]:g},
  resetRetDelayMs:{NAVIGATOR_SHARED_SETTINGS_DEFAULTS["reset_ret_delay_ms"]:g}
}});
const FH6_NAVIGATOR_INITIAL_SETTINGS = Object.freeze({{
  intervalMs:{nav_interval_ms:g},
  switchDelayMs:{nav_switch_delay_ms:g},
  turnDelayMs:{nav_turn_delay_ms:g},
  wrapDelayMs:{nav_wrap_delay_ms:g},
  resetOrigin:{str(nav_reset_origin).lower()},
  resetEscDelayMs:{nav_reset_esc_delay_ms:g},
  resetRetDelayMs:{nav_reset_ret_delay_ms:g}
}});

function numberInRange(value, min, max, fallback) {{
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : fallback;
}}

function currentFh6NavigatorSettings(showError = false) {{
  const controls = {{
    intervalMs: document.getElementById("fh6NavigatorInterval"),
    switchDelayMs: document.getElementById("fh6NavigatorSwitchDelay"),
    turnDelayMs: document.getElementById("fh6NavigatorTurnDelay"),
    wrapDelayMs: document.getElementById("fh6NavigatorWrapDelay"),
    resetOrigin: document.getElementById("fh6NavigatorResetOrigin"),
    resetEscDelayMs: document.getElementById("fh6NavigatorResetEscDelay"),
    resetRetDelayMs: document.getElementById("fh6NavigatorResetRetDelay")
  }};
  const settings = {{
    intervalMs: numberInRange(controls.intervalMs?.value, 10, 2000, NaN),
    switchDelayMs: numberInRange(controls.switchDelayMs?.value, 0, 5000, NaN),
    turnDelayMs: numberInRange(controls.turnDelayMs?.value, 0, 5000, NaN),
    wrapDelayMs: numberInRange(controls.wrapDelayMs?.value, 0, 5000, NaN),
    resetOrigin: Boolean(controls.resetOrigin?.checked),
    resetEscDelayMs: numberInRange(controls.resetEscDelayMs?.value, 0, 5000, NaN),
    resetRetDelayMs: numberInRange(controls.resetRetDelayMs?.value, 0, 5000, NaN)
  }};
  if ([settings.intervalMs, settings.switchDelayMs, settings.turnDelayMs, settings.wrapDelayMs, settings.resetEscDelayMs, settings.resetRetDelayMs].some(value => !Number.isFinite(value))) {{
    if (showError) alert("FH6移動設定に範囲外の値があります。キー間隔は10～2000ms、その他は0～5000msで指定してください。");
    return null;
  }}
  return settings;
}}

function saveFh6NavigatorSettings() {{
  const settings = currentFh6NavigatorSettings(false);
  if (!settings) return false;
  storageSet(FH6_NAVIGATOR_SETTINGS_KEY, JSON.stringify(settings));
  updateFh6NavigatorUi();
  return true;
}}

function loadFh6NavigatorSettings() {{
  let settings = FH6_NAVIGATOR_INITIAL_SETTINGS;
  try {{
    const saved = JSON.parse(storageGetMigrated(FH6_NAVIGATOR_SETTINGS_KEY, LEGACY_FH6_NAVIGATOR_SETTINGS_KEYS) || "null");
    if (saved && typeof saved === "object") {{
      settings = {{
        intervalMs:numberInRange(saved.intervalMs,10,2000,FH6_NAVIGATOR_INITIAL_SETTINGS.intervalMs),
        switchDelayMs:numberInRange(saved.switchDelayMs,0,5000,FH6_NAVIGATOR_INITIAL_SETTINGS.switchDelayMs),
        turnDelayMs:numberInRange(saved.turnDelayMs,0,5000,FH6_NAVIGATOR_INITIAL_SETTINGS.turnDelayMs),
        wrapDelayMs:numberInRange(saved.wrapDelayMs,0,5000,FH6_NAVIGATOR_INITIAL_SETTINGS.wrapDelayMs),
        resetOrigin:typeof saved.resetOrigin === "boolean" ? saved.resetOrigin : FH6_NAVIGATOR_INITIAL_SETTINGS.resetOrigin,
        resetEscDelayMs:numberInRange(saved.resetEscDelayMs,0,5000,FH6_NAVIGATOR_INITIAL_SETTINGS.resetEscDelayMs),
        resetRetDelayMs:numberInRange(saved.resetRetDelayMs,0,5000,FH6_NAVIGATOR_INITIAL_SETTINGS.resetRetDelayMs)
      }};
    }}
  }} catch (_) {{}}
  const mapping = [
    ["fh6NavigatorInterval", settings.intervalMs],
    ["fh6NavigatorSwitchDelay", settings.switchDelayMs],
    ["fh6NavigatorTurnDelay", settings.turnDelayMs],
    ["fh6NavigatorWrapDelay", settings.wrapDelayMs],
    ["fh6NavigatorResetEscDelay", settings.resetEscDelayMs],
    ["fh6NavigatorResetRetDelay", settings.resetRetDelayMs]
  ];
  mapping.forEach(([id, value]) => {{ const el=document.getElementById(id); if (el) el.value=String(value); }});
  const resetOrigin = document.getElementById("fh6NavigatorResetOrigin");
  if (resetOrigin) resetOrigin.checked = Boolean(settings.resetOrigin);
  updateFh6NavigatorResetControls();
}}

function updateFh6NavigatorResetControls() {{
  const enabled = Boolean(document.getElementById("fh6NavigatorResetOrigin")?.checked);
  ["fh6NavigatorResetEscDelay","fh6NavigatorResetRetDelay"].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.disabled = !enabled;
  }});
}}

function placeFh6NavigatorSettings() {{
  const settings = document.getElementById("fh6NavigatorSettings");
  const hostId = document.body.classList.contains("fh6-my-design-view-mode")
    ? "fh6NavigatorSettingsMyDesignHost"
    : "fh6NavigatorSettingsGlobalHost";
  const host = document.getElementById(hostId);
  if (settings && host && settings.parentElement !== host) host.appendChild(settings);
}}

function resetFh6NavigatorSettings() {{
  storageRemove(FH6_NAVIGATOR_SETTINGS_KEY);
  [["fh6NavigatorInterval",FH6_NAVIGATOR_DEFAULTS.intervalMs],["fh6NavigatorSwitchDelay",FH6_NAVIGATOR_DEFAULTS.switchDelayMs],["fh6NavigatorTurnDelay",FH6_NAVIGATOR_DEFAULTS.turnDelayMs],["fh6NavigatorWrapDelay",FH6_NAVIGATOR_DEFAULTS.wrapDelayMs],["fh6NavigatorResetEscDelay",FH6_NAVIGATOR_DEFAULTS.resetEscDelayMs],["fh6NavigatorResetRetDelay",FH6_NAVIGATOR_DEFAULTS.resetRetDelayMs]]
    .forEach(([id,value]) => {{ const el=document.getElementById(id); if (el) el.value=String(value); }});
  const resetOrigin = document.getElementById("fh6NavigatorResetOrigin");
  if (resetOrigin) resetOrigin.checked = Boolean(FH6_NAVIGATOR_DEFAULTS.resetOrigin);
  updateFh6NavigatorResetControls();
  saveFh6NavigatorSettings();
}}

function fh6NavigatorMovePlan(slotNumber, total) {{
  const slot = Number(slotNumber || 0);
  const count = Number(total || 0);
  if (!(slot > 0) || !(count > 0) || slot > count) return null;
  const column = Math.ceil(slot / 2);
  const row = slot % 2 ? "U" : "D";
  const lastColumn = Math.ceil(count / 2);
  const right = column - 1;
  const left = column === 1 ? 0 : lastColumn - column + 1;
  const useRight = right <= left;
  const horizontal = useRight ? right : left;
  const symbol = horizontal <= 0 ? "" : (useRight ? "▶" : "◀");
  const operation = [horizontal > 0 ? `${{symbol}} × ${{horizontal}}` : "横移動なし", row === "D" ? "▼ × 1" : ""]
    .filter(Boolean).join("　");
  return {{slot,column,row,lastColumn,horizontal,useRight,operation,usesLeftWrap:!useRight && horizontal > 0}};
}}

function updateFh6NavigatorPlan(instance, total) {{
  const el = document.getElementById("fh6NavigatorPlan");
  if (!el) return;
  const slotNumber = Number(instance?.slot_number || 0);
  const plan = fh6NavigatorMovePlan(slotNumber, total);
  if (!plan) {{
    el.textContent = "カードを選択すると移動計画を表示します。";
    return;
  }}
  const settings = currentFh6NavigatorSettings(false) || FH6_NAVIGATOR_DEFAULTS;
  const wrap = plan.usesLeftWrap && plan.horizontal > 1 ? ` / 左循環後 +${{settings.wrapDelayMs}}ms` : "";
  const reset = settings.resetOrigin
    ? ` / 初期位置: <b>ESC → RET</b>（${{settings.resetEscDelayMs}}ms / ${{settings.resetRetDelayMs}}ms）`
    : " / 初期位置リセット: OFF";
  const operation = settings.resetOrigin ? `ESC → RET　${{plan.operation}}` : plan.operation;
  el.innerHTML = `<b>#${{String(slotNumber).padStart(Math.max(3,String(total).length),"0")}} / #${{String(plan.column).padStart(3,"0")}}${{plan.row}}</b>　操作: <b>${{operation}}</b>　最終実スロット #${{total}}${{wrap}}${{reset}}`;
}}

function currentFh6NavigatorInstance() {{
  const selected = selectedFh6NavigatorInstance();
  if (selected) return selected;

  const activeCard = document.querySelector("#fh6MyDesignTrack .card.keyboard-active");
  const activeInstance = currentFh6InstanceForCard(activeCard);
  if (activeInstance) return activeInstance;

  if (fh6VehicleMatchSlotNumbers.length) {{
    const slotNumber = Number(fh6VehicleMatchSlotNumbers[fh6VehicleMatchIndex] || 0);
    if (slotNumber > 0) return FH6_CURRENT_MY_DESIGN_INSTANCES[slotNumber - 1] || null;
  }}
  return null;
}}

function compareModalContainsFh6Target() {{
  if (!fh6NavigatorTargetInstanceId) return false;
  return activeCompareMembers.some(card =>
    String(currentFh6InstanceForCard(card)?.instance_id || "") === fh6NavigatorTargetInstanceId
  );
}}

function exactDuplicateModalContainsFh6Target() {{
  if (!fh6NavigatorTargetInstanceId || !activeExactDuplicateGroup) return false;
  return cards.some(card =>
    card.dataset.exactDuplicateGroup === activeExactDuplicateGroup
    && String(currentFh6InstanceForCard(card)?.instance_id || "") === fh6NavigatorTargetInstanceId
  );
}}

function updateFh6NavigatorUi(allowAutoSelect = true) {{
  ensureFh6NavigatorTargetStillValid();
  let instance = allowAutoSelect ? currentFh6NavigatorInstance() : selectedFh6NavigatorInstance();
  const total = FH6_CURRENT_MY_DESIGN_INSTANCES.length;
  if (allowAutoSelect && instance && !fh6NavigatorTargetInstanceId) {{
    fh6NavigatorTargetInstanceId = String(instance.instance_id || "");
    saveFh6NavigatorTargetInstanceId();
  }}
  instance = selectedFh6NavigatorInstance() || instance;
  const location = fh6LocationForInstance(instance);

  document.querySelectorAll(".card.fh6-navigator-selected, .card.fh6-move-target-selected")
    .forEach(card => card.classList.remove("fh6-navigator-selected", "fh6-move-target-selected"));
  document.querySelectorAll(".fh6-move-target-trigger, .fh6-location-button").forEach(button => {{
    const active = Boolean(location && String(button.dataset.fh6MoveTargetInstance || "") === location.instanceId);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    if (!button.disabled) {{
      button.title = active ? "クリックしてFH6移動対象の選択を解除" : "クリックしてFH6移動対象に設定";
    }}
    button.closest(".compare-item")?.classList.toggle("fh6-move-target-selected", active);
  }});
  if (location) {{
    document.querySelectorAll(".card").forEach(card => {{
      if (String(currentFh6InstanceForCard(card)?.instance_id || "") === location.instanceId) {{
        card.classList.add("fh6-move-target-selected");
        if (card.closest("#fh6MyDesignTrack")) card.classList.add("fh6-navigator-selected");
      }}
    }});
  }}

  const sectionButton = document.getElementById("fh6NavigatorMove");
  const globalButton = document.getElementById("fh6GlobalMoveButton");
  const globalBar = document.getElementById("fh6GlobalMoveBar");
  const globalTarget = document.getElementById("fh6GlobalMoveTarget");
  const moveButtons = [sectionButton, globalButton].filter(Boolean);

  if (!location || total <= 0) {{
    moveButtons.forEach(button => {{
      button.disabled = true;
      button.textContent = "FH6で選択デザインへ移動";
      button.title = "カード上の #実スロット または #列U/D をクリックしてFH6移動対象を選択してください。選択後はFキーでも実行できます。";
    }});
    globalBar?.classList.add("hidden");
    if (globalTarget) globalTarget.textContent = "未選択";
    const compareMove = document.getElementById("compareFh6Move");
    const exactMove = document.getElementById("exactDuplicateFh6Move");
    if (compareMove) compareMove.disabled = true;
    if (exactMove) exactMove.disabled = true;
    updateFh6NavigatorPlan(null, total);
    return;
  }}

  const vehicle = String(instance.vehicle_label || "").trim();
  const title = String(instance.title || "").trim();
  const targetText = `${{location.slotLabel}} / ${{location.position}}${{vehicle ? ` · ${{vehicle}}` : ""}}${{title ? ` · ${{title}}` : ""}}`;
  moveButtons.forEach(button => {{
    button.disabled = false;
    button.textContent = "FH6で選択デザインへ移動";
    button.title = `Navigator Bridgeへ ${{targetText}}、最終実スロット #${{total}} と移動設定を渡します。Fキーでも実行できます。`;
  }});
  globalBar?.classList.remove("hidden");
  if (globalTarget) globalTarget.textContent = targetText;

  const compareMove = document.getElementById("compareFh6Move");
  if (compareMove) {{
    const enabled = compareModalContainsFh6Target();
    compareMove.disabled = !enabled;
    compareMove.title = enabled ? `${{targetText}}（Fキーでも移動）` : "比較候補の #実スロット / #列U/D をクリックして移動対象を選択してください。選択後はFキーでも実行できます。";
  }}
  const exactMove = document.getElementById("exactDuplicateFh6Move");
  if (exactMove) {{
    const enabled = exactDuplicateModalContainsFh6Target();
    exactMove.disabled = !enabled;
    exactMove.title = enabled ? `${{targetText}}（Fキーでも移動）` : "この重複グループの #実スロット / #列U/D をクリックして移動対象を選択してください。選択後はFキーでも実行できます。";
  }}
  updateFh6NavigatorPlan(instance, total);
}}

function syncFh6NavigatorSettingsToBridge() {{
  const settings = currentFh6NavigatorSettings(true);
  if (!settings) return false;
  saveFh6NavigatorSettings();
  const params = new URLSearchParams({{
    interval_ms:String(settings.intervalMs),
    switch_delay_ms:String(settings.switchDelayMs),
    turn_delay_ms:String(settings.turnDelayMs),
    wrap_delay_ms:String(settings.wrapDelayMs),
    reset_origin:settings.resetOrigin ? "1" : "0",
    reset_esc_delay_ms:String(settings.resetEscDelayMs),
    reset_ret_delay_ms:String(settings.resetRetDelayMs),
    autostart:"1"
  }});
  window.location.href = `navigatorbridgeforfh6://settings?${{params.toString()}}`;
  return true;
}}

function launchFh6NavigatorForCurrent() {{
  const instance = currentFh6NavigatorInstance();
  const total = FH6_CURRENT_MY_DESIGN_INSTANCES.length;
  const slotNumber = Number(instance?.slot_number || 0);
  if (!instance || !(slotNumber > 0) || !(total > 0)) {{
    alert("FH6で移動したいデザインの #実スロット または #列U/D をクリックして移動対象を選択してください。");
    updateFh6NavigatorUi();
    return false;
  }}

  const settings = currentFh6NavigatorSettings(true);
  if (!settings) return false;
  saveFh6NavigatorSettings();
  const params = new URLSearchParams({{
    target:String(slotNumber),
    last_slot:String(total),
    interval_ms:String(settings.intervalMs),
    switch_delay_ms:String(settings.switchDelayMs),
    turn_delay_ms:String(settings.turnDelayMs),
    wrap_delay_ms:String(settings.wrapDelayMs),
    reset_origin:settings.resetOrigin ? "1" : "0",
    reset_esc_delay_ms:String(settings.resetEscDelayMs),
    reset_ret_delay_ms:String(settings.resetRetDelayMs),
    autostart:"1"
  }});
  const uri = `navigatorbridgeforfh6://move?${{params.toString()}}`;
  // 外部プロトコル起動はユーザーのクリックイベント内で直接行います。
  // 初回はEdge/Chrome等が外部アプリを開く確認を表示することがあります。
  window.location.href = uri;
  return true;
}}

// v0.4.57-r21 — Fキーで選択済みデザインへ移動
function fh6MoveShortcutAllowed(event) {{
  if (!event || event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false;
  if (String(event.key || "").toLowerCase() !== "f") return false;
  const active = document.activeElement;
  if (active && (["INPUT","TEXTAREA","SELECT"].includes(active.tagName) || active.isContentEditable)) return false;
  if (document.getElementById("lightbox")?.classList.contains("open")) return false;
  const topModal = getTopOpenModal();
  if (topModal && !["compareModal","exactDuplicateModal"].includes(topModal.id)) return false;
  const instance = selectedFh6NavigatorInstance();
  return Boolean(fh6LocationForInstance(instance));
}}

document.addEventListener("keydown", event => {{
  if (!fh6MoveShortcutAllowed(event)) return;
  event.preventDefault();
  event.stopPropagation();
  launchFh6NavigatorForCurrent();
}}, true);

function wireFh6NavigatorCardSelection(card) {{
  if (!card || card.dataset.fh6NavigatorSelectWired === "1") return;
  card.dataset.fh6NavigatorSelectWired = "1";
  card.addEventListener("click", event => {{
    if (!card.closest("#fh6MyDesignTrack")) return;
    if (event.target?.closest?.("button,input,textarea,select,a,label,summary,details")) return;
    setFh6NavigatorTargetByCard(card);
    focusKeyboardCard(card, false);
    updateFh6NavigatorUi();
  }});
}}

function wireFh6DuplicateCard(clone, original) {{
  const cloneCheck = clone.querySelector(".card-select");
  const originalCheck = original.querySelector(".card-select");
  if (cloneCheck && originalCheck) {{
    cloneCheck.checked = originalCheck.checked;
    cloneCheck.addEventListener("change", () => {{
      originalCheck.checked = cloneCheck.checked;
      originalCheck.dispatchEvent(new Event("change", {{bubbles:true}}));
    }});
  }}

  [".favorite-toggle", ".review-toggle", ".compare-similar", ".open-exact-duplicate", ".fh6-temp-delete-action"].forEach(selector => {{
    const cloneButton = clone.querySelector(selector);
    const originalButton = original.querySelector(selector);
    if (cloneButton && originalButton) {{
      cloneButton.addEventListener("click", event => {{
        event.stopPropagation();
        originalButton.click();
      }});
    }}
  }});

  const cloneLinks = [...clone.querySelectorAll(".link-filter, .quick-filter")];
  const originalLinks = [...original.querySelectorAll(".link-filter, .quick-filter")];
  cloneLinks.forEach((button, index) => {{
    const originalButton = originalLinks[index];
    if (!originalButton) return;
    button.addEventListener("click", event => {{
      event.stopPropagation();
      originalButton.click();
    }});
  }});

  const image = clone.querySelector("img.livery-image");
  if (image) {{
    image.addEventListener("click", () => {{
      const lightbox = document.getElementById("lightbox");
      const lightboxImage = document.getElementById("lightboxImage");
      if (!lightbox || !lightboxImage) return;
      lightboxImage.src = image.dataset.full || image.src;
      lightboxImage.alt = image.alt || "";
      lightbox.classList.add("open");
    }});
  }}
}}

function fitFh6MyDesignTitle(card) {{
  if (!card) return;
  const heading = card.querySelector("h4");
  const title = heading?.querySelector(".title-filter");
  if (!heading || !title) return;

  // FH6マイデザイン順ではカード寸法を変えず、タイトル領域を2行固定にします。
  // 長いタイトルだけ段階的に縮小し、可能な限り全文を2行へ収めます。
  title.style.fontSize = "";
  let fontSize = 14;
  const minFontSize = 9.5;
  const step = 0.5;

  const fitsTwoLines = () => {{
    const style = getComputedStyle(title);
    const lineHeight = Number.parseFloat(style.lineHeight) || fontSize * 1.15;
    return title.scrollHeight <= (lineHeight * 2) + 1;
  }};

  while (!fitsTwoLines() && fontSize > minFontSize) {{
    fontSize = Math.max(minFontSize, fontSize - step);
    title.style.fontSize = `${{fontSize}}px`;
  }}
}}

function fitAllFh6MyDesignTitles() {{
  document.querySelectorAll("#fh6MyDesignTrack .card").forEach(card => fitFh6MyDesignTitle(card));
}}

function applyFh6InstanceData(card, instance) {{
  card.dataset.liveryId = String(instance.livery_id || card.dataset.liveryId || "");
  card.dataset.timestamp = String(instance.timestamp_raw || "");
  card.dataset.timestampDisplay = String(instance.timestamp_display || "");
  card.dataset.fh6Date = String(instance.fh6_date_raw || card.dataset.fh6Date || "");
  card.dataset.fh6DateDisplay = String(instance.fh6_date_display || card.dataset.fh6DateDisplay || "");
  card.dataset.fh6MyDesignColumn = String(instance.column || "");
  card.dataset.fh6MyDesignRow = String(instance.row || "");
  card.dataset.fh6InstanceId = String(instance.instance_id || "");

  const slotNumber = Number(instance.slot_number || 0);
  const slotLabel = card.querySelector(".my-design-index");
  if (slotLabel && slotNumber > 0) {{
    const totalSlots = Math.max(1, FH6_CURRENT_MY_DESIGN_INSTANCES.length);
    slotLabel.textContent = `#${{String(slotNumber).padStart(Math.max(3, String(totalSlots).length), "0")}}`;
    slotLabel.title = "実スロット通し番号（FH6『マイデザイン』順）";
  }}

  const position = card.querySelector(".fh6-my-design-position");
  if (position) position.textContent = String(instance.position || "#---");
  card.dataset.fh6CurrentInstanceId = String(instance.instance_id || "");
  card.dataset.fh6CurrentSlot = String(slotNumber || "");
  card.dataset.fh6CurrentPosition = String(instance.position || "");
  [slotLabel, position].forEach(button => {{
    if (!button) return;
    button.disabled = false;
    button.classList.remove("hidden");
    button.dataset.fh6MoveTargetInstance = String(instance.instance_id || "");
    button.setAttribute("aria-pressed", String(instance.instance_id || "") === fh6NavigatorTargetInstanceId ? "true" : "false");
  }});

  const timestampDt = [...card.querySelectorAll("dl dt")]
    .find(dt => dt.textContent.trim() === "取得日時");
  if (timestampDt?.nextElementSibling) {{
    timestampDt.nextElementSibling.textContent = String(instance.timestamp_display || "—");
  }}
  const fh6Date = card.querySelector(".fh6-display-date");
  if (fh6Date) {{
    const value = String(instance.fh6_date_display || card.dataset.fh6DateDisplay || "");
    fh6Date.textContent = value;
    fh6Date.classList.toggle("hidden", !value);
  }}
  ensureFh6TempDeleteButton(card, instance);
}}

function renderFh6MyDesignView() {{
  const section = document.getElementById("fh6MyDesignSection");
  const track = document.getElementById("fh6MyDesignTrack");
  if (!section || !track) return;
  section.classList.remove("hidden");
  // 仮削除のたびに元カードを通常グループへ戻してから、現在の有効スロットで再構築します。
  restoreCardsToGroups();
  track.replaceChildren();

  const originalsByKey = new Map(
    cards.map(card => [String(card.dataset.key || ""), card])
  );
  const usedOriginals = new Set();

  for (let index = 0; index < FH6_CURRENT_MY_DESIGN_INSTANCES.length; index += 2) {{
    const columnNumber = Math.floor(index / 2) + 1;
    const column = document.createElement("section");
    column.className = "fh6-my-design-column";
    column.dataset.fh6Column = String(columnNumber);

    [FH6_CURRENT_MY_DESIGN_INSTANCES[index], FH6_CURRENT_MY_DESIGN_INSTANCES[index + 1] || null]
      .forEach((instance, rowIndex) => {{
        const slot = document.createElement("div");
        slot.className = "fh6-my-design-slot";
        slot.dataset.fh6Row = rowIndex === 0 ? "U" : "D";

        if (!instance) {{
          slot.classList.add("fh6-my-design-empty-slot");
          slot.textContent = "—";
          column.appendChild(slot);
          return;
        }}

        const uiKey = String(instance.ui_key || instance.fingerprint || "");
        const fingerprint = String(instance.fingerprint || "");
        const original = originalsByKey.get(uiKey) || originalsByKey.get(fingerprint);
        if (!original) {{
          slot.classList.add("fh6-my-design-empty-slot");
          slot.textContent = String(instance.position || "—");
          column.appendChild(slot);
          return;
        }}

        const originalLiveryId = String(original.dataset.liveryId || "");
        const canUseOriginal = !usedOriginals.has(uiKey)
          && originalLiveryId === String(instance.livery_id || "");
        let card;
        if (canUseOriginal) {{
          card = original;
          usedOriginals.add(uiKey);
        }} else {{
          card = original.cloneNode(true);
          card.dataset.fh6DuplicateInstance = "1";
          card.dataset.ownerGroup = "";
          wireFh6DuplicateCard(card, original);
        }}

        applyFh6InstanceData(card, instance);
        wireFh6NavigatorCardSelection(card);
        card.classList.toggle("hidden", original.classList.contains("hidden"));
        slot.appendChild(card);
        column.appendChild(slot);
      }});

    track.appendChild(column);
  }}

  syncFh6MyDesignColumnVisibility();
  requestAnimationFrame(() => fitAllFh6MyDesignTitles());
  updateFh6MyDesignTailSpace();
  const visibleColumns = fh6MyDesignVisibleColumns();
  if (!visibleColumns.length) return;
  const preferred = visibleColumns.find(column => Number(column.dataset.fh6Column || 0) === fh6MyDesignCurrentColumn)
    || visibleColumns.reduce((best, column) =>
      Math.abs(Number(column.dataset.fh6Column || 0) - fh6MyDesignCurrentColumn) < Math.abs(Number(best.dataset.fh6Column || 0) - fh6MyDesignCurrentColumn) ? column : best
    , visibleColumns[0]);
  requestAnimationFrame(() => {{
    scrollToFh6MyDesignColumn(preferred, "auto");
    updateFh6NavigatorUi();
  }});
}}

function applySort() {{
  const mode = sortOrder.value;
  // 通常の「マイデザイン順」は実スロット通し番号、FH6マイデザイン順は通し番号＋列U/D位置を表示します。
  document.body.classList.toggle("my-design-sort-mode", mode === "my-designs");
  document.body.classList.toggle("fh6-my-design-view-mode", mode === "fh6-my-designs");
  placeFh6TempDeletedReview();
  placeFh6NavigatorSettings();
  const fh6Section = document.getElementById("fh6MyDesignSection");
  const grouped = document.getElementById("groupedSections");
  const flatGrid = document.getElementById("flatSortGrid");
  const flatCount = document.getElementById("flatSortCount");
  const flatTitle = document.getElementById("flatSortTitle");
  const groups = [...document.querySelectorAll(".car-group")];

  if (mode === "fh6-my-designs") {{
    document.body.classList.remove("flat-sort-mode", "creator-sort-mode");
    restoreCardsToGroups();
    renderFh6MyDesignView();
    return;
  }}

  fh6Section?.classList.add("hidden");
  updateFh6NavigatorUi();

  if (["manufacturer", "my-designs", "vehicle", "year-desc", "year-asc", "progress-asc", "progress-desc"].includes(mode)) {{
    document.body.classList.remove("flat-sort-mode", "creator-sort-mode");
    restoreCardsToGroups();

    const collator = new Intl.Collator("ja", {{
      numeric: true,
      sensitivity: "base",
    }});

    const groupCards = group => [...group.querySelectorAll(".card")];
    const firstNonEmpty = values =>
      values.map(value => String(value || "").trim()).find(Boolean) || "";
    const smallestCreator = group => {{
      const creators = groupCards(group)
        .map(card => String(card.dataset.creatorDisplay || card.dataset.creator || "").trim())
        .filter(Boolean)
        .sort((a, b) => collator.compare(a, b));
      return creators[0] || "";
    }};
    const groupInfo = group => {{
      const members = groupCards(group);
      return {{
        make: firstNonEmpty(members.map(card => card.dataset.make)),
        vehicle: firstNonEmpty(members.map(card => card.dataset.model || card.dataset.vehicle)),
        year: Math.max(0, ...members.map(card => Number(card.dataset.year || 0))),
        creator: smallestCreator(group),
        progress: vehicleProgressInfo(group.dataset.carGroup),
        carId: Number(group.dataset.carGroup || 0),
      }};
    }};
    const compareTextMissingLast = (a, b) => {{
      if (!a && b) return 1;
      if (!b && a) return -1;
      if (!a && !b) return 0;
      return collator.compare(a, b);
    }};
    const compareYearMissingLast = (a, b, direction = "desc") => {{
      if (a <= 0 && b > 0) return 1;
      if (b <= 0 && a > 0) return -1;
      if (a <= 0 && b <= 0) return 0;
      return direction === "asc" ? a - b : b - a;
    }};

    // グループ単位の並び替えでは車種カード階層を維持します。
    // 「マイデザイン順」はFH6画面と同じ順序に合わせ、同一Car ID内を取得日時昇順にします。
    // それ以外は従来どおり作成者昇順 + 取得日時昇順で一定の順序にします。
    groups.forEach(group => {{
      const grid = group.querySelector(".grid");
      if (!grid) return;
      const orderedCards = groupCards(group).sort((a, b) => {{
        if (mode === "my-designs") {{
          const timestampResult = String(a.dataset.timestamp || "").localeCompare(String(b.dataset.timestamp || ""));
          if (timestampResult !== 0) return timestampResult;
          return String(a.dataset.key || "").localeCompare(String(b.dataset.key || ""));
        }}
        const aCreator = String(a.dataset.creatorDisplay || a.dataset.creator || "").trim();
        const bCreator = String(b.dataset.creatorDisplay || b.dataset.creator || "").trim();
        const creatorResult = compareTextMissingLast(aCreator, bCreator);
        if (creatorResult !== 0) return creatorResult;
        return String(a.dataset.timestamp || "").localeCompare(String(b.dataset.timestamp || ""));
      }});
      orderedCards.forEach(card => grid.appendChild(card));
    }});

    groups.sort((a, b) => {{
      const av = groupInfo(a);
      const bv = groupInfo(b);
      let result = 0;

      if (mode === "my-designs") {{
        // FH6「マイデザイン順」: Car ID昇順。
        // 同一Car ID内のカード順は上で取得日時昇順に統一済みです。
        result = av.carId - bv.carId;
        if (result !== 0) return result;
      }} else if (mode === "manufacturer") {{
        result = compareTextMissingLast(av.make, bv.make);
        if (result !== 0) return result;
        result = compareYearMissingLast(av.year, bv.year, "desc");
        if (result !== 0) return result;
        result = compareTextMissingLast(av.creator, bv.creator);
        if (result !== 0) return result;
      }} else if (mode === "vehicle") {{
        result = compareTextMissingLast(av.vehicle, bv.vehicle);
        if (result !== 0) return result;
        result = compareYearMissingLast(av.year, bv.year, "desc");
        if (result !== 0) return result;
        result = compareTextMissingLast(av.make, bv.make);
        if (result !== 0) return result;
        result = compareTextMissingLast(av.creator, bv.creator);
        if (result !== 0) return result;
      }} else if (mode === "year-desc" || mode === "year-asc") {{
        result = compareYearMissingLast(av.year, bv.year, mode.endsWith("-asc") ? "asc" : "desc");
        if (result !== 0) return result;
        result = compareTextMissingLast(av.make, bv.make);
        if (result !== 0) return result;
        result = compareTextMissingLast(av.vehicle, bv.vehicle);
        if (result !== 0) return result;
        result = compareTextMissingLast(av.creator, bv.creator);
        if (result !== 0) return result;
      }} else if (mode === "progress-asc" || mode === "progress-desc") {{
        const direction = mode === "progress-desc" ? -1 : 1;
        result = (av.progress.rank - bv.progress.rank) * direction;
        if (result !== 0) return result;
        result = (av.progress.percent - bv.progress.percent) * direction;
        if (result !== 0) return result;
        result = compareTextMissingLast(av.make, bv.make);
        if (result !== 0) return result;
        result = compareTextMissingLast(av.vehicle, bv.vehicle);
        if (result !== 0) return result;
      }}

      return av.carId - bv.carId;
    }});

    groups.forEach(group => grouped.appendChild(group));
    return;
  }}

  if (mode === "creator") {{
    document.body.classList.remove("flat-sort-mode");
    document.body.classList.add("creator-sort-mode");
    restoreCardsToGroups();

    const creatorGrouped = document.getElementById("creatorGroupedSections");
    if (!creatorGrouped) return;
    creatorGrouped.innerHTML = "";

    const collator = new Intl.Collator("ja", {{
      numeric: true,
      sensitivity: "base",
    }});
    const compareTextMissingLast = (a, b) => {{
      const av = String(a || "").trim();
      const bv = String(b || "").trim();
      if (!av && bv) return 1;
      if (!bv && av) return -1;
      if (!av && !bv) return 0;
      return collator.compare(av, bv);
    }};
    const compareYearDescMissingLast = (a, b) => {{
      const av = Number(a || 0);
      const bv = Number(b || 0);
      if (av <= 0 && bv > 0) return 1;
      if (bv <= 0 && av > 0) return -1;
      if (av <= 0 && bv <= 0) return 0;
      return bv - av;
    }};

    const creatorGroups = new Map();
    cards.forEach(card => {{
      const key = String(card.dataset.creator || "").trim();
      if (!creatorGroups.has(key)) creatorGroups.set(key, []);
      creatorGroups.get(key).push(card);
    }});

    const orderedCreators = [...creatorGroups.entries()].sort((a, b) => {{
      const aLabel = String(a[1][0]?.dataset.creatorDisplay || a[0] || "").trim();
      const bLabel = String(b[1][0]?.dataset.creatorDisplay || b[0] || "").trim();
      return compareTextMissingLast(aLabel, bLabel);
    }});

    orderedCreators.forEach(([creatorKey, members]) => {{
      const orderedCards = [...members].sort((a, b) => {{
        let result = compareTextMissingLast(a.dataset.make, b.dataset.make);
        if (result !== 0) return result;
        result = compareYearDescMissingLast(a.dataset.year, b.dataset.year);
        if (result !== 0) return result;
        result = compareTextMissingLast(a.dataset.model || a.dataset.vehicle, b.dataset.model || b.dataset.vehicle);
        if (result !== 0) return result;
        result = Number(a.dataset.car || 0) - Number(b.dataset.car || 0);
        if (result !== 0) return result;
        return String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || ""));
      }});

      const shown = orderedCards.filter(card => !card.classList.contains("hidden")).length;
      const section = document.createElement("section");
      section.className = "creator-group";
      section.dataset.creatorGroup = creatorKey;
      section.classList.toggle("hidden", shown === 0);

      const heading = document.createElement("div");
      heading.className = "group-heading";
      const title = document.createElement("h2");
      const creatorLabel = String(members[0]?.dataset.creatorDisplay || "").trim();
      title.textContent = `作成者: ${{creatorLabel || "未取得"}}`;
      const count = document.createElement("span");
      count.className = "group-count-badge";
      count.textContent = shown === orderedCards.length
        ? `${{orderedCards.length}}件`
        : `${{shown}} / ${{orderedCards.length}}件`;
      heading.append(title, count);

      const grid = document.createElement("div");
      grid.className = "grid";
      orderedCards.forEach(card => grid.appendChild(card));
      section.append(heading, grid);
      creatorGrouped.appendChild(section);
    }});
    return;
  }}

  if (mode === "paint-asc" || mode === "paint-desc") {{
    document.body.classList.remove("flat-sort-mode", "creator-sort-mode");
    restoreCardsToGroups();

    const direction = mode.endsWith("-desc") ? "desc" : "asc";

    // ペイント件数の並び替えは車種グループ単位です。別のグループ並び替えから切り替えた際に
    // その内部順序を引き継がないよう、各車種グループ内のカード順を一定に戻します。
    groups.forEach(group => {{
      const grid = group.querySelector(".grid");
      if (!grid) return;
      [...group.querySelectorAll(".card")]
        .sort((a, b) => String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || "")))
        .forEach(card => grid.appendChild(card));
    }});

    groups.sort((a, b) => {{
      const av = Number(a.dataset.paintCount || 0);
      const bv = Number(b.dataset.paintCount || 0);
      const result = av - bv;
      if (result !== 0) return direction === "desc" ? -result : result;
      return Number(a.dataset.carGroup || 0) - Number(b.dataset.carGroup || 0);
    }});
    groups.forEach(group => grouped.appendChild(group));
    return;
  }}

  if (
    mode === "title" || mode === "decision" ||
    mode === "vinyl-asc" || mode === "vinyl-desc" ||
    mode === "timestamp-asc" || mode === "timestamp-desc"
  ) {{
    document.body.classList.remove("creator-sort-mode");
    // フラット並び替えグリッドへ移動する前に、各カードの元グループを記録します。
    groups.forEach(group => {{
      group.querySelectorAll(".card").forEach(card => {{
        if (!card.dataset.ownerGroup) {{
          card.dataset.ownerGroup = group.dataset.carGroup;
        }}
      }});
    }});

    const direction = mode.endsWith("-desc") ? "desc" : "asc";
    // 検索文字が変わっても並び順自体は変わらないため、全カードの順序をここで1度確定します。
    // ライブ検索ではこの配列から表示対象だけを抜き出し、再ソートしません。
    const sortedCards = [...cards];
    const collator = new Intl.Collator("ja", {{numeric:true, sensitivity:"base"}});
    const compareTextMissingLast = (a, b) => {{
      const av = String(a || "").trim();
      const bv = String(b || "").trim();
      if (!av && bv) return 1;
      if (!bv && av) return -1;
      if (!av && !bv) return 0;
      return collator.compare(av, bv);
    }};

    if (mode === "title") {{
      sortedCards.sort((a, b) => {{
        let result = compareTextMissingLast(a.dataset.titleDisplay || a.dataset.title, b.dataset.titleDisplay || b.dataset.title);
        if (result !== 0) return result;
        result = compareTextMissingLast(a.dataset.model || a.dataset.vehicle, b.dataset.model || b.dataset.vehicle);
        if (result !== 0) return result;
        result = compareTextMissingLast(a.dataset.creatorDisplay || a.dataset.creator, b.dataset.creatorDisplay || b.dataset.creator);
        if (result !== 0) return result;
        result = String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || ""));
        if (result !== 0) return result;
        return String(a.dataset.key || "").localeCompare(String(b.dataset.key || ""));
      }});
      if (flatTitle) flatTitle.textContent = "タイトル";
    }} else if (mode === "decision") {{
      const workflowRank = card => {{
        const state = getState(card);
        const meta = loadCardMeta(card);
        if (state === "undecided" && !meta.reviewLater) return 0;
        if (meta.reviewLater) return 1;
        if (state === "keep") return 2;
        if (state === "delete") return 3;
        return 4;
      }};
      sortedCards.sort((a, b) => {{
        let result = workflowRank(a) - workflowRank(b);
        if (result !== 0) return result;
        result = compareTextMissingLast(a.dataset.model || a.dataset.vehicle, b.dataset.model || b.dataset.vehicle);
        if (result !== 0) return result;
        result = compareTextMissingLast(a.dataset.titleDisplay || a.dataset.title, b.dataset.titleDisplay || b.dataset.title);
        if (result !== 0) return result;
        result = String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || ""));
        if (result !== 0) return result;
        result = Number(a.dataset.car || 0) - Number(b.dataset.car || 0);
        if (result !== 0) return result;
        return String(a.dataset.key || "").localeCompare(String(b.dataset.key || ""));
      }});
      if (flatTitle) flatTitle.textContent = "整理状態: 未決定 → 後で確認 → 残す → 削除候補";
    }} else if (mode.startsWith("vinyl-")) {{
      sortedCards.sort((a, b) => {{
        const av = Number(a.dataset.vinylCount || -1);
        const bv = Number(b.dataset.vinylCount || -1);

        // バイナル数が不明なカードは常に末尾へ配置します。
        if (av < 0 && bv >= 0) return 1;
        if (bv < 0 && av >= 0) return -1;
        if (av < 0 && bv < 0) return 0;

        const result = av - bv;
        if (result !== 0) return direction === "desc" ? -result : result;
        return String(a.dataset.timestamp || "").localeCompare(String(b.dataset.timestamp || ""));
      }});
      if (flatTitle) flatTitle.textContent =
        direction === "desc" ? "バイナル数:降順" : "バイナル数:昇順";
    }} else {{
      sortedCards.sort((a, b) => {{
        // timestamp_rawはYYYYMMDDhhmmss（UTC）なので、文字列順がそのまま時系列順になります。
        // 表示時刻はJST（+09:00）ですが、並び順は同じです。
        const av = String(a.dataset.timestamp || "");
        const bv = String(b.dataset.timestamp || "");
        const result = av.localeCompare(bv);
        if (result !== 0) return direction === "desc" ? -result : result;
        return Number(a.dataset.car || 0) - Number(b.dataset.car || 0);
      }});
      if (flatTitle) flatTitle.textContent =
        direction === "desc" ? "取得日時:降順" : "取得日時:昇順";
    }}

    flatSortOrderCache = sortedCards;
    flatSortOrderMode = mode;
    const visibleCards = sortedCards.filter(card => !card.classList.contains("hidden"));
    flatGrid.replaceChildren(...visibleCards);
    flatCount.textContent = `${{visibleCards.length}}件`;
    document.body.classList.add("flat-sort-mode");
  }}
}}

function normFilterValue(value) {{
  return String(value || "").trim().toLocaleLowerCase(REPORT_LOCALE);
}}

function staticCardSearchData(card) {{
  const cached = CARD_SEARCH_STATIC_CACHE.get(card);
  if (cached) return cached;
  const value = {{
    general:normFilterValue(card.dataset.search),
    vehicle:normFilterValue([
      card.dataset.vehicle,
      card.dataset.make,
      card.dataset.model,
      card.dataset.year
    ].join(" ")),
    make:normFilterValue(card.dataset.make),
    year:String(card.dataset.year || "").trim(),
    creator:normFilterValue(card.dataset.creator),
    title:normFilterValue(card.dataset.title),
    description:normFilterValue(card.dataset.description),
    paintCount:Number(card.dataset.paintCount || 0),
    vinylCount:Number(card.dataset.vinylCount || -1)
  }};
  CARD_SEARCH_STATIC_CACHE.set(card, value);
  return value;
}}


function collectCurrentScan() {{
  const entries = {{}};
  cards.forEach(card => {{
    entries[card.dataset.key] = {{
      car:card.dataset.car,
      creator:card.dataset.creator,
      title:card.dataset.title,
      vehicle:card.querySelector(".vehicle")?.textContent || "",
      timestamp:card.dataset.timestamp || "",
      timestampDisplay:card.dataset.timestampDisplay || ""
    }};
  }});
  return entries;
}}
function loadScanBaseline() {{
  try {{
    const state = JSON.parse(storageGetMigrated(SCAN_STATE_KEY, LEGACY_SCAN_STATE_KEYS) || "null");
    if (state && state.entries && typeof state.entries === "object") return state;
  }} catch (_) {{}}
  return null;
}}
function updateScanBaselineStatus(state) {{
  const status = document.getElementById("scanBaselineStatus");
  if (!status) return;
  if (!state) {{
    status.textContent = REPORT_BASELINE_NOT_SET;
    return;
  }}
  const count = Object.keys(state.entries || {{}}).length;
  let saved = REPORT_FALLBACK_UNKNOWN_DATE;
  if (state.savedAt) {{
    const date = new Date(state.savedAt);
    if (!Number.isNaN(date.getTime())) saved = date.toLocaleString(REPORT_LOCALE);
  }}
  status.textContent = `${{REPORT_BASELINE_PREFIX}} ${{count}}${{REPORT_ITEM_SUFFIX}} / ${{saved}}`;
}}
function applyScanDiff() {{
  const current = collectCurrentScan();
  const baselineState = loadScanBaseline();
  const previous = baselineState?.entries || {{}};
  const hasBaseline = Boolean(baselineState);
  const removed = hasBaseline
    ? Object.keys(previous).filter(key=>!current[key]).map(key=>previous[key])
    : [];
  let newCount = 0;
  cards.forEach(card => {{
    const isNew = hasBaseline && !previous[card.dataset.key];
    card.dataset.isNew = isNew ? "1" : "0";
    card.querySelector(".new-badge")?.classList.toggle("hidden", !isNew);
    if (isNew) newCount++;
  }});
  window.__fh6CurrentScanEntries = current;
  window.__fh6RemovedEntries = removed;
  document.getElementById("removedCount").textContent = removed.length;
  const newDiffCount = document.getElementById("newDiffCount");
  if (newDiffCount) newDiffCount.textContent = newCount;
  document.getElementById("newOnly").textContent = `新規のみ (${{newCount}}件)`;
  updateScanBaselineStatus(baselineState);
}}
function setCurrentScanAsBaseline() {{
  const current = collectCurrentScan();
  const count = Object.keys(current).length;
  if (!confirm(`現在の ${{count}}件を、今後の「新規 / 基準から消えた」判定の基準にしますか？`)) return;
  storageSet(SCAN_STATE_KEY, JSON.stringify({{savedAt:new Date().toISOString(), entries:current}}));
  applyScanDiff();
  applyFilters();
}}
document.getElementById("setScanBaseline")?.addEventListener("click", setCurrentScanAsBaseline);
function updateSelectionUi() {{
  const count = selectedKeys.size;
  document.getElementById("selectedCount").textContent = count;
  document.getElementById("bulkKeep").textContent = `選択${{count}}件→残す`;
  document.getElementById("bulkDelete").textContent = `選択${{count}}件→削除候補`;
  document.getElementById("bulkUndecided").textContent = `選択${{count}}件→未決定`;
  document.getElementById("bulkFavorite").textContent = `選択${{count}}件→お気に入り`;
  document.getElementById("bulkReview").textContent = `選択${{count}}件→後で確認`;
  document.getElementById("bulkTag").textContent = `選択${{count}}件→タグ管理`;
  const compareSelected = document.getElementById("compareSelected");
  if (compareSelected) {{
    compareSelected.textContent = `選択中を比較 (${{count}}件)`;
    compareSelected.disabled = count < 2;
    compareSelected.title = count < 2 ? "2件以上選択すると比較できます" : `選択中の${{count}}件を比較します`;
  }}
  cards.forEach(card => {{
    const box = card.querySelector(".card-select");
    if (box) box.checked = selectedKeys.has(card.dataset.key);
  }});
  document.getElementById("selectedOnly").textContent = `選択中のみ (${{count}}件)`;
}}
function selectedCardsForBulk(actionLabel) {{
  const selected = cards.filter(card => selectedKeys.has(card.dataset.key));
  if (selected.length) return selected;
  alert(
    `「${{actionLabel}}」を実行するペイントが選択されていません。\n` +
    `カード左上のチェックボックス、または「表示中を選択」を使用してください。`
  );
  return [];
}}

function bulkSetState(state) {{
  const labels = {{keep:"残す", delete:"削除候補", undecided:"未決定"}};
  const selected = selectedCardsForBulk(labels[state] || "一括操作");
  if (!selected.length) return;

  const items = [];
  selected.forEach(card => {{
    const previous = getState(card);
    if (previous !== state) items.push({{type:"state", key:card.dataset.key, previous}});
    if (state === "undecided") storageRemove(stateKey(card));
    else storageSet(stateKey(card), state);
    paintState(card);
  }});
  if (items.length) pushUndo({{type:"bulk", items, label:`選択${{selected.length}}件→${{labels[state] || state}}`}});
  applyFilters();
  saveUiState();
}}
const modalReturnFocus = new Map();
const MODAL_FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

function getTopOpenModal() {{
  const open = [...document.querySelectorAll(".modal:not(.hidden)")];
  return open.length ? open[open.length - 1] : null;
}}

function modalFocusableElements(modal) {{
  if (!modal) return [];
  return [...modal.querySelectorAll(MODAL_FOCUSABLE_SELECTOR)].filter(element => {{
    if (!(element instanceof HTMLElement)) return false;
    if (element.hidden || element.getAttribute("aria-hidden") === "true" || element.closest(".hidden")) return false;
    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  }});
}}

function focusModalContent(modal) {{
  if (!modal) return;
  requestAnimationFrame(() => {{
    if (modal.classList.contains("hidden")) return;
    const preferred = modal.querySelector("[data-modal-initial-focus]");
    const focusables = modalFocusableElements(modal);
    const panel = modal.querySelector(".modal-panel");
    const target = (preferred instanceof HTMLElement && !preferred.disabled)
      ? preferred
      : focusables[0] || panel;
    if (!(target instanceof HTMLElement)) return;
    if (target === panel && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    try {{ target.focus({{preventScroll:true}}); }} catch (_) {{ target.focus(); }}
  }});
}}

function openModal(id, opener = null) {{
  const modal = document.getElementById(id);
  if (!modal) return;
  const active = opener instanceof HTMLElement ? opener : document.activeElement;
  if (active instanceof HTMLElement && active !== document.body && !modal.contains(active)) {{
    modalReturnFocus.set(id, active);
  }}
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  focusModalContent(modal);
}}

function closeModal(id, restoreFocus = true) {{
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  const returnTarget = modalReturnFocus.get(id);
  modalReturnFocus.delete(id);
  if (!restoreFocus || !(returnTarget instanceof HTMLElement)) return;
  requestAnimationFrame(() => {{
    if (!returnTarget.isConnected || returnTarget.disabled) return;
    try {{ returnTarget.focus({{preventScroll:true}}); }} catch (_) {{ returnTarget.focus(); }}
  }});
}}

function trapModalTab(event, modal) {{
  if (event.key !== "Tab" || !modal) return false;
  const focusables = modalFocusableElements(modal);
  if (!focusables.length) {{
    const panel = modal.querySelector(".modal-panel");
    if (panel instanceof HTMLElement) {{
      if (!panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "-1");
      panel.focus();
    }}
    event.preventDefault();
    return true;
  }}
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !modal.contains(active))) {{
    last.focus();
    event.preventDefault();
    return true;
  }}
  if (!event.shiftKey && (active === last || !modal.contains(active))) {{
    first.focus();
    event.preventDefault();
    return true;
  }}
  return false;
}}
// v0.4.19 検索構文:
//   v: 車種 / Car ID、c: 作成者、n: 名前（タイトル）、d: 説明、t: タグ。
// フィールド指定はAND条件です。複数語の値は引用符で囲めます。例:
//   c:DemoWorks n:"デモペイント 001"
// 接頭辞なしの文字列は、従来どおり全項目を対象に部分一致検索します。
function parseSearchQuery(rawValue) {{
  const text = String(rawValue || "").trim();
  const fields = [];
  const generalParts = [];
  const validFields = new Set(["v", "c", "n", "d", "t"]);
  const isSpace = ch => Boolean(ch) && ch.charCodeAt(0) <= 32;
  let i = 0;

  const readValue = () => {{
    while (i < text.length && isSpace(text[i])) i++;
    let value = "";
    if (text[i] === '"') {{
      i++;
      while (i < text.length) {{
        const ch = text[i];
        if (ch === "\\\\" && i + 1 < text.length) {{
          value += text[i + 1];
          i += 2;
          continue;
        }}
        if (ch === '"') {{ i++; break; }}
        value += ch;
        i++;
      }}
    }} else {{
      while (i < text.length && !isSpace(text[i])) {{
        value += text[i];
        i++;
      }}
    }}
    return value.trim();
  }};

  while (i < text.length) {{
    while (i < text.length && isSpace(text[i])) i++;
    if (i >= text.length) break;

    const field = String(text[i] || "").toLowerCase();
    if (validFields.has(field) && text[i + 1] === ":") {{
      i += 2;
      const value = readValue();
      if (value) fields.push({{field, value:normFilterValue(value)}});
      continue;
    }}

    const value = readValue();
    if (value) generalParts.push(value);
  }}

  return {{fields, general:normFilterValue(generalParts.join(" "))}};
}}

function fieldSearchQuery(field, value) {{
  return `${{field}}:${{JSON.stringify(String(value || ""))}}`;
}}

function buildCardCriteriaContext(overrides = {{}}) {{
  // 検索文字入力時に同じ検索式・フィルター状態をカード件数分だけ再解析しないよう、
  // 1回の絞り込み更新につき判定条件を1度だけ組み立てて全カードで共用します。
  const pick = (name, current) =>
    Object.prototype.hasOwnProperty.call(overrides, name) ? overrides[name] : current;

  const rawQuery = String(pick("query", q.value) || "").trim();
  return {{
    parsedQuery: parseSearchQuery(rawQuery),
    decisions: normalizeFilterValues(pick("decision", selectedFilterValues(filter))),
    progressStates: normalizeFilterValues(pick("progress", selectedFilterValues(progressFilter))),
    vehicles: normalizeFilterValues(pick("vehicle", selectedFilterValues(vehicleFilter))),
    makes: normalizeFilterValues(pick("make", selectedFilterValues(makeFilter))).map(normFilterValue),
    years: normalizeFilterValues(pick("year", selectedFilterValues(yearFilter))),
    creators: normalizeFilterValues(pick("creator", selectedFilterValues(creatorFilter))).map(normFilterValue),
    paintCountValues: normalizeFilterValues(pick("paintCount", selectedFilterValues(paintCountFilter)))
      .map(Number).filter(Number.isFinite),
    vinylMin: parseOptionalNumber(pick("vinylMin", vinylMinInput?.value)),
    vinylMax: parseOptionalNumber(pick("vinylMax", vinylMaxInput?.value)),
    tagValues: normalizeFilterValues(pick("tag", selectedFilterValues(tagFilter))),
    tagMode: String(pick("tagMode", tagMatchMode) || "or").toLowerCase() === "and" ? "and" : "or",
    similarOnly: Boolean(pick("similarOnly", similarOnlyMode)),
    similarKind: normalizeSimilarKind(pick("similarKind", similarKindMode)),
    exactDuplicateOnly: Boolean(pick("exactDuplicateOnly", exactDuplicateOnlyMode)),
    newOnly: Boolean(pick("newOnly", newOnlyMode)),
    favoriteOnly: Boolean(pick("favoriteOnly", favoriteOnlyMode)),
    reviewOnly: Boolean(pick("reviewOnly", reviewOnlyMode)),
    selectedOnly: Boolean(pick("selectedOnly", selectedOnlyMode)),
  }};
}}

function cardMatchesCriteria(card, overrides = {{}}, criteria = null) {{
  if (fh6CardIsTempDeleted(card)) return false;
  const ctx = criteria || buildCardCriteriaContext(overrides);
  const {{
    parsedQuery, decisions, progressStates, vehicles, makes, years, creators, paintCountValues,
    vinylMin, vinylMax, tagValues, tagMode, similarOnly, similarKind, exactDuplicateOnly,
    newOnly, favoriteOnly, reviewOnly, selectedOnly
  }} = ctx;

  const meta = loadCardMeta(card);
  const staticSearch = staticCardSearchData(card);
  const cardTags = normFilterValue(meta.tags);
  const cardNote = normFilterValue(meta.note);
  const searchText = cardTags || cardNote
    ? `${{staticSearch.general}} ${{cardTags}} ${{cardNote}}`
    : staticSearch.general;
  const vehicleSearchText = staticSearch.vehicle;
  const cardMake = staticSearch.make;
  const cardYear = staticSearch.year;
  const cardCreator = staticSearch.creator;
  const cardTitle = staticSearch.title;
  const cardDescription = staticSearch.description;
  const cardPaintCount = staticSearch.paintCount;
  const cardVinylCount = staticSearch.vinylCount;

  if (parsedQuery.general && !searchText.includes(parsedQuery.general)) return false;

  for (const clause of parsedQuery.fields) {{
    const needle = clause.value;
    if (clause.field === "v") {{
      if (/^[0-9]+$/.test(needle)) {{
        if (Number(card.dataset.car || -1) !== Number(needle)) return false;
      }} else if (!vehicleSearchText.includes(needle)) return false;
    }} else if (clause.field === "c") {{
      if (!cardCreator.includes(needle)) return false;
    }} else if (clause.field === "n") {{
      if (!cardTitle.includes(needle)) return false;
    }} else if (clause.field === "d") {{
      if (!cardDescription.includes(needle)) return false;
    }} else if (clause.field === "t") {{
      if (!cardTags.includes(needle)) return false;
    }}
  }}

  if (decisions.length && !decisions.includes(getState(card))) return false;
  if (progressStates.length && !progressStates.includes(vehicleProgressStateForCard(card))) return false;
  if (vehicles.length && !vehicles.includes(String(card.dataset.car || ""))) return false;
  if (makes.length && !makes.includes(cardMake)) return false;
  if (years.length && !years.includes(cardYear)) return false;
  if (creators.length && !creators.includes(cardCreator)) return false;
  if (paintCountValues.length && !paintCountValues.includes(cardPaintCount)) return false;
  if (vinylMin !== null && cardVinylCount < vinylMin) return false;
  if (vinylMax !== null && cardVinylCount > vinylMax) return false;
  if (tagValues.length) {{
    const tags = String(card.dataset.tags || "").split(",").map(x=>x.trim()).filter(Boolean);
    const tagMatch = tagMode === "and"
      ? tagValues.every(tag => tags.includes(tag))
      : tagValues.some(tag => tags.includes(tag));
    if (!tagMatch) return false;
  }}
  if (similarOnly) {{
    if (Number(card.dataset.similarCount || 0) < 2) return false;
    if (similarKind !== "all" && String(card.dataset.similarKind || "") !== similarKind) return false;
  }}
  if (exactDuplicateOnly && card.dataset.exactDuplicate !== "1") return false;
  if (newOnly && card.dataset.isNew !== "1") return false;
  if (favoriteOnly && !meta.favorite) return false;
  if (reviewOnly && !meta.reviewLater) return false;
  if (selectedOnly && !selectedKeys.has(card.dataset.key)) return false;
  return true;
}}

function matchingCards(overrides = {{}}) {{
  const criteria = buildCardCriteriaContext(overrides);
  return indexedCandidateCards(overrides).filter(card => cardMatchesCriteria(card, overrides, criteria));
}}

function ensureBaseLabels(select) {{
  [...select.options].forEach(option => {{
    if (!option.dataset.baseLabel) {{
      option.dataset.baseLabel = option.textContent.replace(
        /\\s+\\([^)]*(?:件|車種)[^)]*\\)\\s*$/, ""
      );
    }}
  }});
}}

function filterKeyForSelect(select) {{
  return new Map([
    [filter, "decision"], [progressFilter, "progress"], [vehicleFilter, "vehicle"], [makeFilter, "make"],
    [yearFilter, "year"], [creatorFilter, "creator"], [paintCountFilter, "paintCount"],
    [tagFilter, "tag"]
  ]).get(select) || "";
}}

function filterChoiceCounts(select, value) {{
  const key = filterKeyForSelect(select);
  if (!key) return {{single:0, combined:0}};
  const current = selectedFilterValues(select);
  const singleValues = value === "all" ? [] : [value];
  const combinedValues = value === "all"
    ? []
    : current.includes(value)
      ? current
      : [...current, value];
  const countMatches = values => {{
    const matches = matchingCards({{[key]: values}});
    if (select === progressFilter) {{
      return new Set(matches.map(card => String(card.dataset.car || ""))).size;
    }}
    return matches.length;
  }};
  const single = countMatches(singleValues);
  const combined = countMatches(combinedValues);
  return {{single, combined}};
}}

function selectedStatFilterLabel(select) {{
  const labels = selectedFilterLabels(select, true);
  if (!labels.length) return "";
  if (labels.length === 1) return labels[0];
  return `${{labels.length}}件選択`;
}}

function updateStatFilterUi(targetId, hintId, select, defaultTitle) {{
  const values = selectedFilterValues(select);
  const active = values.length > 0;
  document.querySelectorAll(`[data-stat-filter-target="${{select.id}}"]`).forEach(button => {{
    button.classList.toggle("active", active);
    if (button.classList.contains("mobile-stat-filter-trigger")) {{
      const base = {{vehicleFilter:"車種",makeFilter:"メーカー",creatorFilter:"作成者",yearFilter:"年式"}}[select.id] || defaultTitle;
      button.textContent = active ? `${{base}} (${{values.length}}) ▾` : `${{base}} ▾`;
    }}
  }});
  const desktopButton = document.getElementById(targetId);
  const hint = document.getElementById(hintId);
  const selectedLabel = active ? selectedStatFilterLabel(select) : "";
  if (hint) hint.textContent = active ? `${{selectedLabel}} ▾` : "絞り込み ▾";
  if (desktopButton) desktopButton.setAttribute("title", active ? `${{defaultTitle}}: ${{selectedFilterLabels(select, true).join(", ")}}` : defaultTitle);
}}

function updateFilterSelectionUi() {{
  updateStatFilterUi("vehicleStatAction", "vehicleStatHint", vehicleFilter, "車種で絞り込み");
  updateStatFilterUi("makeStatAction", "makeStatHint", makeFilter, "メーカーで絞り込み");
  updateStatFilterUi("creatorStatAction", "creatorStatHint", creatorFilter, "作成者で絞り込み");
  updateStatFilterUi("yearStatAction", "yearStatHint", yearFilter, "年式で絞り込み");
  updateStatFilterUi("decisionQuickAction", "decisionQuickHint", filter, "整理状態で絞り込み");
  updateStatFilterUi("progressQuickAction", "progressQuickHint", progressFilter, "車種の整理進捗で絞り込み");
  updateStatFilterUi("paintCountQuickAction", "paintCountQuickHint", paintCountFilter, "ペイント件数で絞り込み");
  updateStatFilterUi("tagQuickAction", "tagQuickHint", tagFilter, "タグで絞り込み");
  const paintCountValues = selectedFilterValues(paintCountFilter);
  const paintCountQuickCount = document.getElementById("paintCountQuickCount");
  if (paintCountQuickCount) {{
    paintCountQuickCount.textContent = paintCountValues.length
      ? `${{paintCountValues.length}}件選択`
      : `${{Math.max(0, paintCountFilter.options.length - 1)}}候補`;
  }}
  renderActiveFilterChips();
}}

function updateDynamicFilterCounts() {{
  [filter, progressFilter, vehicleFilter, makeFilter, yearFilter, creatorFilter, paintCountFilter, tagFilter]
    .forEach(ensureBaseLabels);

  // 負荷の高い候補別件数は詳細フィルターパネルを開いている間だけ更新します。
  // クイックフィルターの件数は描画時に必要に応じて計算します。
  const detailOpen = !document.getElementById("filterPanel")?.classList.contains("hidden");
  if (detailOpen) detailFilterSelects.forEach(select => renderDetailFilterChoices(select));

  const vinylRangeMatches = matchingCards({{
    vinylMin: parseOptionalNumber(vinylMinInput?.value),
    vinylMax: parseOptionalNumber(vinylMaxInput?.value)
  }}).length;
  const rangeCount = document.getElementById("vinylRangeCount");
  if (rangeCount) rangeCount.textContent = `${{vinylRangeMatches}}件`;

  document.querySelectorAll(".creator-chip").forEach(btn => {{
    const count = matchingCards({{creator: [btn.dataset.creator]}}).length;
    const number = btn.querySelector("b");
    if (number) number.textContent = count;
  }});

  const baseWithoutFavorite = matchingCards({{favoriteOnly:false}});
  const favoriteCount = baseWithoutFavorite.filter(c => Boolean(loadCardMeta(c).favorite)).length;
  const baseWithoutReview = matchingCards({{reviewOnly:false}});
  const reviewCount = baseWithoutReview.filter(c => Boolean(loadCardMeta(c).reviewLater)).length;
  const baseWithoutNew = matchingCards({{newOnly:false}});
  const newCount = baseWithoutNew.filter(c => c.dataset.isNew === "1").length;
  const baseWithoutSimilar = matchingCards({{similarOnly:false, similarKind:"all"}});
  const similarCandidates = baseWithoutSimilar.filter(c => Number(c.dataset.similarCount || 0) >= 2);
  const similarCount = similarCandidates.length;
  const similarImageCount = similarCandidates.filter(c => String(c.dataset.similarKind || "") === "image").length;
  const similarCreatorTitleCount = similarCandidates.filter(c => String(c.dataset.similarKind || "") === "creator-title").length;
  const baseWithoutExactDuplicate = matchingCards({{exactDuplicateOnly:false}});
  const exactDuplicateCards = baseWithoutExactDuplicate.filter(c => c.dataset.exactDuplicate === "1");
  const exactDuplicateCount = exactDuplicateCards.length;
  const exactDuplicateGroups = new Set(exactDuplicateCards.map(c => String(c.dataset.exactDuplicateGroup || "")).filter(Boolean)).size;
  const baseWithoutSelected = matchingCards({{selectedOnly:false}});
  const selectedCount = baseWithoutSelected.filter(c => selectedKeys.has(c.dataset.key)).length;

  document.getElementById("favoriteOnly").textContent = `お気に入りのみ (${{favoriteCount}}件)`;
  document.getElementById("reviewOnly").textContent = `後で確認のみ (${{reviewCount}}件)`;
  document.getElementById("newOnly").textContent = `新規のみ (${{newCount}}件)`;
  document.getElementById("similarOnly").textContent = `類似候補のみ (${{similarCount}}件)`;
  document.getElementById("similarImageOnly").textContent = `画像一致のみ (${{similarImageCount}}件)`;
  document.getElementById("similarCreatorTitleOnly").textContent = `同一作者・同名のみ (${{similarCreatorTitleCount}}件)`;
  document.getElementById("exactDuplicateOnly").textContent = `再DL重複のみ (${{exactDuplicateGroups}}組 / ${{exactDuplicateCount}}件)`;
  const exactStatValue = document.getElementById("statExactDuplicate");
  if (exactStatValue) exactStatValue.textContent = `${{exactDuplicateGroups}}組`;
  document.getElementById("selectedOnly").textContent = `選択中のみ (${{selectedCount}}件)`;
  updateFilterSelectionUi();
}}


const detailFilterSelectedOnly = new Map();
const detailFilterSearchText = new Map();

function cleanDetailChoiceLabel(select, option) {{
  let label = String(option.dataset.baseLabel || option.textContent || option.value || "")
    .replace(/\\s+\\([^)]*(?:件|車種)[^)]*\\)\\s*$/, "");
  if (select === paintCountFilter) label = label.replace(/^ペイント件数: */, "");
  if (select === progressFilter) label = label.replace(/^整理進捗: */, "");
  if (select === tagFilter) label = label.replace(/^タグ: */, "");
  return label;
}}

function renderDetailFilterChoices(select) {{
  if (!select) return;
  const host = document.querySelector(`[data-detail-choices="${{select.id}}"]`);
  if (!host) return;
  ensureBaseLabels(select);
  const selected = new Set(selectedFilterValues(select));
  const search = normFilterValue(detailFilterSearchText.get(select.id) || "");
  const selectedOnly = Boolean(detailFilterSelectedOnly.get(select.id));
  host.innerHTML = "";

  [...select.options].filter(option => option.value !== "all").forEach(option => {{
    const label = cleanDetailChoiceLabel(select, option);
    const active = selected.has(option.value);
    const visible = (!search || normFilterValue(label).includes(search)) && (!selectedOnly || active);
    const counts = filterChoiceCounts(select, option.value);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "detail-filter-choice";
    button.dataset.value = option.value;
    button.dataset.detailTarget = select.id;
    button.classList.toggle("active", active);
    button.classList.toggle("hidden-choice", !visible);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    const unit = select === progressFilter ? "車種" : "件";
    const suffix = active
      ? `${{counts.single}}${{unit}} / 現在 ${{counts.combined}}${{unit}}`
      : `${{counts.single}}${{unit}} / 追加後 ${{counts.combined}}${{unit}}`;
    button.textContent = `${{label}} (${{suffix}})`;
    button.addEventListener("click", () => {{
      toggleFilterValue(select, option.value);
      applyAndPersist();
      renderDetailFilterChoices(select);
    }});
    host.appendChild(button);
  }});
  const count = document.querySelector(`[data-detail-count="${{select.id}}"]`);
  if (count) count.textContent = selected.size ? `${{selected.size}}件選択` : "すべて";
}}

function renderAllDetailFilterChoices() {{
  detailFilterSelects.forEach(renderDetailFilterChoices);
}}

document.querySelectorAll("[data-detail-search]").forEach(input => {{
  input.addEventListener("input", () => {{
    detailFilterSearchText.set(input.dataset.detailSearch, input.value);
    renderDetailFilterChoices(document.getElementById(input.dataset.detailSearch));
  }});
}});

document.querySelectorAll("[data-detail-action]").forEach(button => {{
  button.addEventListener("click", () => {{
    const select = document.getElementById(button.dataset.detailTarget);
    if (!select) return;
    const action = button.dataset.detailAction;
    if (action === "clear") {{
      setFilterValues(select, []);
      detailFilterSelectedOnly.set(select.id, false);
    }} else if (action === "selected") {{
      const next = !detailFilterSelectedOnly.get(select.id);
      detailFilterSelectedOnly.set(select.id, next);
      button.classList.toggle("active", next);
    }} else if (action === "all-visible") {{
      const host = document.querySelector(`[data-detail-choices="${{select.id}}"]`);
      const visibleValues = [...(host?.querySelectorAll(".detail-filter-choice:not(.hidden-choice)") || [])]
        .map(choice => choice.dataset.value).filter(Boolean);
      setFilterValues(select, [...new Set([...selectedFilterValues(select), ...visibleValues])]);
    }}
    applyAndPersist();
    renderDetailFilterChoices(select);
  }});
}});

function updateTagModeUi() {{
  document.getElementById("tagModeOr")?.classList.toggle("active", tagMatchMode === "or");
  document.getElementById("tagModeAnd")?.classList.toggle("active", tagMatchMode === "and");
}}
document.getElementById("tagModeOr")?.addEventListener("click", () => {{ tagMatchMode = "or"; updateTagModeUi(); applyAndPersist(); }});
document.getElementById("tagModeAnd")?.addEventListener("click", () => {{ tagMatchMode = "and"; updateTagModeUi(); applyAndPersist(); }});

[vinylMinInput, vinylMaxInput].forEach(input => input?.addEventListener("input", () => {{
  const min = parseOptionalNumber(vinylMinInput?.value);
  const max = parseOptionalNumber(vinylMaxInput?.value);
  if (min !== null && max !== null && min > max) return;
  applyAndPersist();
}}));
document.getElementById("vinylRangeClear")?.addEventListener("click", () => {{
  if (vinylMinInput) vinylMinInput.value = "";
  if (vinylMaxInput) vinylMaxInput.value = "";
  applyAndPersist();
}});

function updateSimilarityFilterUi() {{
  similarKindMode = normalizeSimilarKind(similarKindMode);
  const allActive = similarOnlyMode && similarKindMode === "all";
  const imageActive = similarOnlyMode && similarKindMode === "image";
  const creatorTitleActive = similarOnlyMode && similarKindMode === "creator-title";
  [
    ["similarOnly", allActive],
    ["similarImageOnly", imageActive],
    ["similarCreatorTitleOnly", creatorTitleActive]
  ].forEach(([id, active]) => {{
    const button = document.getElementById(id);
    button?.classList.toggle("active", active);
    button?.setAttribute("aria-pressed", active ? "true" : "false");
  }});
  const stat = document.getElementById("similarStatAction");
  stat?.classList.toggle("active", similarOnlyMode);
  stat?.setAttribute("aria-pressed", similarOnlyMode ? "true" : "false");
  stat?.setAttribute("title", similarOnlyMode && similarKindMode !== "all"
    ? `類似候補: ${{SIMILAR_KIND_LABELS[similarKindMode]}}のみ表示中`
    : "類似候補のみ表示");
  const exactButton = document.getElementById("exactDuplicateOnly");
  exactButton?.classList.toggle("active", exactDuplicateOnlyMode);
  exactButton?.setAttribute("aria-pressed", exactDuplicateOnlyMode ? "true" : "false");
  const exactStat = document.getElementById("exactDuplicateStatAction");
  exactStat?.classList.toggle("active", exactDuplicateOnlyMode);
  exactStat?.setAttribute("aria-pressed", exactDuplicateOnlyMode ? "true" : "false");
}}

function refreshFilteredView(options = {{}}) {{
  const settings = {{dynamicCounts:true, ...options}};
  restoreCardsToGroups();

  const criteria = buildCardCriteriaContext();
  let visible = 0;
  cards.forEach(card => {{
    const show = cardMatchesCriteria(card, {{}}, criteria);
    card.classList.toggle("hidden", !show);
    if (show) visible++;
  }});

  document.querySelectorAll(".car-group").forEach(group => {{
    const groupCards = [...group.querySelectorAll(".card")];
    const shown = groupCards.filter(c => !c.classList.contains("hidden")).length;
    group.classList.toggle("hidden", shown === 0);
    const count = group.querySelector(".group-count-badge");
    if (count) {{
      count.textContent = shown === groupCards.length
        ? `${{groupCards.length}}件`
        : `${{shown}} / ${{groupCards.length}}件`;
    }}

    // 車種進捗は絞り込み後に表示中のカードだけでなく、その車種グループ内の全カードを使います。
    // 同じ計算を進捗フィルター、進捗並び替え、次の車種への移動で共用します。
    const progress = vehicleProgressInfo(group.dataset.carGroup);
    const progressBadge = group.querySelector("[data-group-progress]");
    const progressBar = progressBadge?.querySelector(".group-progress-bar");
    const progressText = progressBadge?.querySelector("[data-group-progress-text]");

    if (progressBar) {{
      progressBar.max = Math.max(1, progress.total);
      progressBar.value = progress.decided;
    }}
    if (progressText) {{
      progressText.textContent = `整理 ${{progress.decided}} / ${{progress.total}} · ${{progress.percent}}%`;
    }}
    if (progressBadge) {{
      progressBadge.dataset.progressState = progress.state;
      progressBadge.title =
        `整理済み ${{progress.decided}} / ${{progress.total}}（残す ${{progress.keep}} / 削除候補 ${{progress.deleted}} / 未決定 ${{progress.undecided}}）｜クリックしてこの車種だけ表示`;
    }}
  }});

  const stateSummary = collectCardStateSummary();
  document.getElementById("visibleCount").textContent = visible;
  document.getElementById("emptyState").classList.toggle("show", visible === 0);
  document.getElementById("keepCount").textContent = stateSummary.keep;
  document.getElementById("deleteCount").textContent = stateSummary.deleted;
  document.getElementById("undecidedCount").textContent = stateSummary.undecided;

  document.getElementById("decisionProgress").textContent =
    `${{stateSummary.decided}} / ${{stateSummary.total}} (${{stateSummary.total ? Math.round(stateSummary.decided/stateSummary.total*100) : 0}}%)`;
  document.getElementById("decisionProgressBar").value = stateSummary.decided;
  updateSelectionUi();

  document.getElementById("statUndecided").textContent = stateSummary.undecided;
  document.getElementById("statFavorite").textContent = stateSummary.favorite;
  document.getElementById("statReview").textContent = stateSummary.review;
  document.getElementById("statNew").textContent = stateSummary.newCount;
  document.getElementById("statSimilar").textContent = stateSummary.similar;

  const selectedDecisions = new Set(selectedFilterValues(filter));
  document.querySelectorAll(".counter-filter").forEach(btn => {{
    const value = btn.dataset.stateFilter || "all";
    btn.classList.toggle("active", value === "all" ? selectedDecisions.size === 0 : selectedDecisions.has(value));
  }});
  const undecidedOnlyActive = selectedDecisions.size === 1 && selectedDecisions.has("undecided");
  document.getElementById("newOnly").classList.toggle("active", newOnlyMode);
  document.getElementById("favoriteOnly").classList.toggle("active", favoriteOnlyMode);
  document.getElementById("reviewOnly").classList.toggle("active", reviewOnlyMode);
  updateSimilarityFilterUi();
  [
    ["undecidedStatAction", undecidedOnlyActive],
    ["favoriteStatAction", favoriteOnlyMode],
    ["reviewStatAction", reviewOnlyMode],
    ["newStatAction", newOnlyMode],
  ].forEach(([id, active]) => {{
    const button = document.getElementById(id);
    button?.classList.toggle("active", Boolean(active));
    button?.setAttribute("aria-pressed", active ? "true" : "false");
  }});
  document.getElementById("selectedOnly").classList.toggle("active", selectedOnlyMode);
  const vehicleSummary = vehicleProgressSummary();
  updateVehicleWorkflowQuickUi(vehicleSummary);

  if (settings.dynamicCounts) updateDynamicFilterCounts();
  return {{visible, stateSummary, vehicleSummary}};
}}

// v0.4.58-r15 rev3 — 検索文字の変更だけでは並び順、整理進捗、バックアップ状態、
// 選択状態などは変化しません。ライブ検索中はカード一致判定と現在レイアウトの
// 表示/非表示だけを更新し、全体再ソート・全状態再集計を避けます。
function updateGroupedLiveSearchVisibility() {{
  document.querySelectorAll(".car-group").forEach(group => {{
    const members = [...group.querySelectorAll(".card")];
    const shown = members.filter(card => !card.classList.contains("hidden")).length;
    group.classList.toggle("hidden", shown === 0);
    const count = group.querySelector(".group-count-badge");
    if (count) count.textContent = shown === members.length
      ? `${{members.length}}件`
      : `${{shown}} / ${{members.length}}件`;
  }});
}}

function updateCreatorLiveSearchVisibility() {{
  document.querySelectorAll("#creatorGroupedSections .creator-group").forEach(group => {{
    const members = [...group.querySelectorAll(".card")];
    const shown = members.filter(card => !card.classList.contains("hidden")).length;
    group.classList.toggle("hidden", shown === 0);
    const count = group.querySelector(".group-count-badge");
    if (count) count.textContent = shown === members.length
      ? `${{members.length}}件`
      : `${{shown}} / ${{members.length}}件`;
  }});
}}

function updateFlatLiveSearchVisibility(mode) {{
  const flatGrid = document.getElementById("flatSortGrid");
  const flatCount = document.getElementById("flatSortCount");
  if (!flatGrid) return;
  // 通常はapplySort()で確定済みの順序を再利用します。万一キャッシュが無い場合だけ
  // 現在のカード配列を使い、次の通常更新で正規の並び順へ戻します。
  const ordered = flatSortOrderMode === mode && flatSortOrderCache.length
    ? flatSortOrderCache
    : cards;
  const visibleCards = ordered.filter(card => !card.classList.contains("hidden"));
  flatGrid.replaceChildren(...visibleCards);
  if (flatCount) flatCount.textContent = `${{visibleCards.length}}件`;
}}

function updateFh6LiveSearchVisibility() {{
  const visibility = new Map(cards.map(card => [
    String(card.dataset.key || ""),
    !card.classList.contains("hidden")
  ]));
  document.querySelectorAll("#fh6MyDesignTrack .card").forEach(card => {{
    const key = String(card.dataset.key || "");
    if (visibility.has(key)) card.classList.toggle("hidden", !visibility.get(key));
  }});
  syncFh6MyDesignColumnVisibility();
}}

function syncLiveSearchLayout() {{
  const mode = sortOrder.value;
  if (mode === "fh6-my-designs") {{
    updateFh6LiveSearchVisibility();
    return;
  }}
  if (mode === "creator") {{
    updateCreatorLiveSearchVisibility();
    return;
  }}
  if (["title","decision","vinyl-asc","vinyl-desc","timestamp-asc","timestamp-desc"].includes(mode)) {{
    updateFlatLiveSearchVisibility(mode);
    return;
  }}
  updateGroupedLiveSearchVisibility();
}}

function refreshLiveSearchView() {{
  const criteria = buildCardCriteriaContext();
  let visible = 0;
  cards.forEach(card => {{
    const show = cardMatchesCriteria(card, {{}}, criteria);
    card.classList.toggle("hidden", !show);
    if (show) visible++;
  }});
  syncLiveSearchLayout();
  const visibleCount = document.getElementById("visibleCount");
  if (visibleCount) visibleCount.textContent = String(visible);
  document.getElementById("emptyState")?.classList.toggle("show", visible === 0);
  renderActiveFilterChips();
  updateMobileFilterSummary();
  return visible;
}}

const UI_REFRESH_DEFAULTS = Object.freeze({{
  view:true,
  backup:true,
  sort:true,
  navigation:true,
  mobile:false,
  persist:false,
  dynamicCounts:true
}});

function refreshOrganizerUi(options = {{}}) {{
  const settings = {{...UI_REFRESH_DEFAULTS, ...options}};
  const viewState = settings.view ? refreshFilteredView({{dynamicCounts:settings.dynamicCounts}}) : null;

  if (settings.backup) updateBackupStatus(viewState?.stateSummary || null);
  if (settings.sort) applySort();
  if (settings.navigation) updateVehicleNavigationUi(viewState?.vehicleSummary || null);
  if (settings.mobile) updateMobileFilterSummary();
  if (settings.persist) saveUiState();

  return viewState;
}}

function refreshBackupUi() {{
  return refreshOrganizerUi({{
    view:false, backup:true, sort:false, navigation:false, mobile:false, persist:false
  }});
}}

function applyFilters() {{
  return refreshOrganizerUi();
}}


document.querySelectorAll(".counter-filter").forEach(btn => {{
  btn.addEventListener("click", () => {{
    setFilterValues(filter, btn.dataset.stateFilter === "all" ? [] : [btn.dataset.stateFilter || ""]);
    applyAndPersist();
  }});
}});

document.querySelectorAll(".creator-chip").forEach(btn => {{
  btn.addEventListener("click", () => {{
    setFilterValues(creatorFilter, btn.dataset.creator ? [btn.dataset.creator] : []);
    applyAndPersist();
  }});
}});

const creatorMoreToggle = document.getElementById("creatorMoreToggle");
const creatorMoreList = document.getElementById("creatorMoreList");
if (creatorMoreToggle && creatorMoreList) {{
  creatorMoreToggle.addEventListener("click", () => {{
    const open = creatorMoreList.classList.contains("hidden");
    creatorMoreList.classList.toggle("hidden", !open);
    creatorMoreToggle.setAttribute("aria-expanded", open ? "true" : "false");
    creatorMoreToggle.textContent = open
      ? "作成者を折りたたむ"
      : creatorMoreToggle.dataset.closedLabel;
    saveUiState();
  }});
}}

document.querySelectorAll("[data-group-progress]").forEach(button => {{
  button.addEventListener("click", event => {{
    event.preventDefault();
    event.stopPropagation();
    showOnlyVehicleFromProgress(button.dataset.progressCar);
  }});
}});

document.querySelectorAll("[data-vehicle-progress-state]").forEach(button => {{
  button.addEventListener("click", () => {{
    setVehicleProgressOnly(button.dataset.vehicleProgressState);
  }});
}});

document.querySelectorAll("[data-unfinished-vehicles-toggle]").forEach(button => {{
  button.addEventListener("click", () => {{
    setUnfinishedVehiclesOnly(!unfinishedVehiclesShortcutActive());
  }});
}});

document.querySelectorAll("[data-filter-type]").forEach(el => {{
  el.addEventListener("click", event => {{
    event.preventDefault();
    event.stopPropagation();
    const type = el.dataset.filterType;
    const value = el.dataset.filterValue || "";
    if (type === "creator") setFilterValues(creatorFilter, value ? [value] : []);
    if (type === "make") setFilterValues(makeFilter, value ? [value] : []);
    if (type === "car") q.value = `v:${{String(value).padStart(4, "0")}}`;
    if (type === "title") q.value = fieldSearchQuery("n", value);
    applyAndPersist();
    window.scrollTo({{top:0, behavior:"smooth"}});
  }});
}});

document.getElementById("deleteReview").addEventListener("click", () => {{
  setFilterValues(filter, ["delete"]);
  similarOnlyMode = false;
  similarKindMode = "all";
  exactDuplicateOnlyMode = false;
  newOnlyMode = false;
  setFilterValues(tagFilter, []);
  document.getElementById("similarOnly").classList.remove("active");
  document.getElementById("newOnly").classList.remove("active");
  applyAndPersist();
}});

function toggleUndecidedOnlyFilter() {{
  const selected = new Set(selectedFilterValues(filter));
  const active = selected.size === 1 && selected.has("undecided");
  setFilterValues(filter, active ? [] : ["undecided"]);
  applyAndPersist();
}}
function toggleSimilarOnlyFilter() {{
  const active = similarOnlyMode && similarKindMode === "all";
  similarOnlyMode = !active;
  similarKindMode = "all";
  applyAndPersist();
}}
function toggleSimilarKindFilter(kind) {{
  const target = normalizeSimilarKind(kind);
  if (target === "all") return toggleSimilarOnlyFilter();
  const active = similarOnlyMode && similarKindMode === target;
  similarOnlyMode = !active;
  similarKindMode = active ? "all" : target;
  applyAndPersist();
}}
function toggleSimilarStatFilter() {{
  similarOnlyMode = !similarOnlyMode;
  similarKindMode = "all";
  applyAndPersist();
}}
function toggleExactDuplicateOnlyFilter() {{
  exactDuplicateOnlyMode = !exactDuplicateOnlyMode;
  applyAndPersist();
}}
function toggleNewOnlyFilter() {{
  newOnlyMode = !newOnlyMode;
  applyAndPersist();
}}
function toggleFavoriteOnlyFilter() {{
  favoriteOnlyMode = !favoriteOnlyMode;
  applyAndPersist();
}}
function toggleReviewOnlyFilter() {{
  reviewOnlyMode = !reviewOnlyMode;
  applyAndPersist();
}}

document.getElementById("undecidedStatAction")?.addEventListener("click", toggleUndecidedOnlyFilter);
document.getElementById("similarOnly").addEventListener("click", toggleSimilarOnlyFilter);
document.getElementById("similarImageOnly")?.addEventListener("click", () => toggleSimilarKindFilter("image"));
document.getElementById("similarCreatorTitleOnly")?.addEventListener("click", () => toggleSimilarKindFilter("creator-title"));
document.getElementById("similarStatAction")?.addEventListener("click", toggleSimilarStatFilter);
document.getElementById("exactDuplicateOnly")?.addEventListener("click", toggleExactDuplicateOnlyFilter);
document.getElementById("exactDuplicateStatAction")?.addEventListener("click", toggleExactDuplicateOnlyFilter);
document.getElementById("newOnly").addEventListener("click", toggleNewOnlyFilter);
document.getElementById("newStatAction")?.addEventListener("click", toggleNewOnlyFilter);
document.getElementById("favoriteOnly").addEventListener("click", toggleFavoriteOnlyFilter);
document.getElementById("favoriteStatAction")?.addEventListener("click", toggleFavoriteOnlyFilter);
document.getElementById("reviewOnly").addEventListener("click", toggleReviewOnlyFilter);
document.getElementById("reviewStatAction")?.addEventListener("click", toggleReviewOnlyFilter);

function applyCreatorSearch() {{
  const needle = normFilterValue(creatorQuickSearch?.value || "");
  const chips = [...document.querySelectorAll(".creator-chip")];
  const moreList = document.getElementById("creatorMoreList");
  const moreToggle = document.getElementById("creatorMoreToggle");

  if (needle && creatorSearchRestoreOpen === null && moreList) {{
    creatorSearchRestoreOpen = !moreList.classList.contains("hidden");
  }}

  let matches = 0;
  chips.forEach(chip => {{
    const match = !needle || normFilterValue(chip.dataset.creator).includes(needle);
    chip.classList.toggle("hidden", !match);
    if (match) matches++;
  }});

  if (needle) {{
    if (moreList) moreList.classList.remove("hidden");
    if (moreToggle) moreToggle.classList.add("hidden");
  }} else {{
    if (moreToggle) moreToggle.classList.remove("hidden");
    if (moreList && creatorSearchRestoreOpen !== null) {{
      moreList.classList.toggle("hidden", !creatorSearchRestoreOpen);
      moreToggle?.setAttribute("aria-expanded", creatorSearchRestoreOpen ? "true" : "false");
      if (moreToggle) {{
        moreToggle.textContent = creatorSearchRestoreOpen
          ? "作成者を折りたたむ"
          : moreToggle.dataset.closedLabel;
      }}
    }}
    creatorSearchRestoreOpen = null;
  }}

  const countEl = document.getElementById("creatorSearchCount");
  if (countEl) countEl.textContent = needle ? `${{matches}}人` : "";
}}
creatorQuickSearch?.addEventListener("input", applyCreatorSearch);

document.querySelectorAll(".mobile-bottom-nav button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const action = btn.dataset.mobileAction;
    if (action === "filter") {{
      const toolbar = document.getElementById("filterToolbar");
      toolbar.classList.add("mobile-open");
      document.getElementById("mobileFilterToggle").setAttribute("aria-expanded", "true");
      document.getElementById("mobileFilterToggle").textContent = "絞り込みを閉じる";
      window.scrollTo({{top:0, behavior:"smooth"}});
      return;
    }}
    setFilterValues(filter, action === "all" ? [] : [action]);
    applyAndPersist();
    window.scrollTo({{top:0, behavior:"smooth"}});
  }});
}});


cards.forEach(card => {{
  applyCardMeta(card);
  card.querySelector(".card-select")?.addEventListener("change", e => {{
    if (e.target.checked) selectedKeys.add(card.dataset.key); else selectedKeys.delete(card.dataset.key);
    applyFilters();
  }});
  card.querySelector(".favorite-toggle")?.addEventListener("click", e => {{
    e.stopPropagation();
    const meta=loadCardMeta(card);
    saveCardMeta(card,{{favorite:!meta.favorite}});
    applyAndPersist();
  }});
  card.querySelector(".review-toggle")?.addEventListener("click", e => {{
    e.stopPropagation();
    const meta=loadCardMeta(card);
    saveCardMeta(card,{{reviewLater:!meta.reviewLater}});
    applyAndPersist();
  }});
  card.querySelector(".tag-input")?.addEventListener("change", e => {{ saveCardMeta(card,{{tags:e.target.value}}); applyAndPersist(); }});
  card.querySelector(".note-input")?.addEventListener("change", e => saveCardMeta(card,{{note:e.target.value}}));
}});
rebuildTagFilter();

document.getElementById("selectVisible").addEventListener("click",()=>{{
  const visible = cards.filter(c=>!c.classList.contains("hidden"));
  if (!visible.length) {{
    alert("現在の絞り込み条件で表示されているペイントがありません。");
    return;
  }}
  visible.forEach(c=>selectedKeys.add(c.dataset.key));
  applyFilters();
}});
document.getElementById("clearSelection").addEventListener("click",()=>{{
  selectedKeys.clear();
  if (selectedOnlyMode) selectedOnlyMode = false;
  applyFilters();
}});
document.getElementById("selectedOnly").addEventListener("click", () => {{
  if (!selectedKeys.size && !selectedOnlyMode) {{
    alert("選択中のペイントがありません。");
    return;
  }}
  selectedOnlyMode = !selectedOnlyMode;
  applyAndPersist();
}});
document.getElementById("invertSelection").addEventListener("click", () => {{
  const visible = cards.filter(card => !card.classList.contains("hidden"));
  if (!visible.length) {{
    alert("現在表示されているペイントがありません。");
    return;
  }}
  visible.forEach(card => {{
    if (selectedKeys.has(card.dataset.key)) selectedKeys.delete(card.dataset.key);
    else selectedKeys.add(card.dataset.key);
  }});
  applyFilters();
}});
document.getElementById("bulkKeep").addEventListener("click",()=>bulkSetState("keep"));
document.getElementById("bulkDelete").addEventListener("click",()=>bulkSetState("delete"));
document.getElementById("bulkUndecided").addEventListener("click",()=>bulkSetState("undecided"));

document.getElementById("bulkFavorite").addEventListener("click", () => {{
  const selected = selectedCardsForBulk("お気に入り");
  if (!selected.length) return;
  const items = [];
  selected.forEach(card => {{
    const previous = loadCardMeta(card);
    items.push({{type:"meta", key:card.dataset.key, previous}});
    storageSet(metaKey(card), JSON.stringify({{...previous, favorite:true}}));
    applyCardMeta(card);
  }});
  if (items.length) pushUndo({{type:"bulk", items, label:`選択${{selected.length}}件→お気に入り`}});
  rebuildTagFilter(); applyFilters();
}});
document.getElementById("bulkReview").addEventListener("click", () => {{
  const selected = selectedCardsForBulk("後で確認");
  if (!selected.length) return;
  const items = [];
  selected.forEach(card => {{
    const previous = loadCardMeta(card);
    items.push({{type:"meta", key:card.dataset.key, previous}});
    storageSet(metaKey(card), JSON.stringify({{...previous, reviewLater:true}}));
    applyCardMeta(card);
  }});
  if (items.length) pushUndo({{type:"bulk", items, label:`選択${{selected.length}}件→後で確認`}});
  rebuildTagFilter(); applyFilters();
}});
function splitUserTags(value) {{
  return String(value || "")
    .split(",")
    .map(tag => tag.trim())
    .filter(Boolean);
}}

function dedupeUserTags(tags) {{
  const result = [];
  tags.forEach(tag => {{
    const normalized = String(tag || "").trim();
    if (normalized && !result.includes(normalized)) result.push(normalized);
  }});
  return result;
}}

function selectedTagUsage(selected) {{
  const counts = new Map();
  selected.forEach(card => {{
    dedupeUserTags(splitUserTags(loadCardMeta(card).tags)).forEach(tag => {{
      counts.set(tag, (counts.get(tag) || 0) + 1);
    }});
  }});
  return [...counts.entries()].sort((a, b) =>
    a[0].localeCompare(b[0], "ja", {{numeric:true, sensitivity:"base"}})
  );
}}

function updateTagManagerModeUi() {{
  const mode = document.getElementById("tagManagerMode")?.value || "add";
  const sourceWrap = document.getElementById("tagManagerSourceWrap");
  const targetWrap = document.getElementById("tagManagerTargetWrap");
  const targetLabel = document.getElementById("tagManagerTargetLabel");
  const target = document.getElementById("tagManagerTarget");

  sourceWrap?.classList.toggle("hidden", mode === "add");
  targetWrap?.classList.toggle("hidden", mode === "remove");

  if (targetLabel) {{
    targetLabel.textContent = mode === "replace" ? "置換後のタグ" : "追加するタグ";
  }}
  if (target) {{
    target.placeholder = mode === "replace"
      ? "例: サーキット"
      : "例: 痛車, レーシング";
  }}
}}

function openTagManager() {{
  const selected = selectedCardsForBulk("タグ管理");
  if (!selected.length) return;

  const usage = selectedTagUsage(selected);
  const summary = document.getElementById("tagManagerSelectionSummary");
  if (summary) {{
    summary.textContent =
      `選択 ${{selected.length}}件 / 使用中タグ ${{usage.length}}種類`;
  }}

  const source = document.getElementById("tagManagerSource");
  if (source) {{
    source.innerHTML = "";
    usage.forEach(([tag, count]) => {{
      const option = document.createElement("option");
      option.value = tag;
      option.textContent =
        `${{tag}} (${{count}} / ${{selected.length}}件)`;
      source.appendChild(option);
    }});

    if (!usage.length) {{
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "選択中のカードにタグがありません";
      source.appendChild(option);
    }}
  }}

  const mode = document.getElementById("tagManagerMode");
  if (mode) mode.value = "add";

  const target = document.getElementById("tagManagerTarget");
  if (target) target.value = "";

  updateTagManagerModeUi();
  openModal("tagManagerModal");
}}

function applyBulkTagManagement() {{
  const selected = selectedCardsForBulk("タグ管理");
  if (!selected.length) {{
    closeModal("tagManagerModal");
    return;
  }}

  const mode = document.getElementById("tagManagerMode")?.value || "add";
  const sourceTag =
    String(document.getElementById("tagManagerSource")?.value || "").trim();
  const targetText =
    String(document.getElementById("tagManagerTarget")?.value || "").trim();
  const targetTags = dedupeUserTags(splitUserTags(targetText));

  if ((mode === "remove" || mode === "replace") && !sourceTag) {{
    alert("対象タグを選択してください。");
    return;
  }}

  if (mode === "add" && !targetTags.length) {{
    alert("追加するタグを入力してください。");
    return;
  }}

  if (mode === "replace") {{
    if (targetTags.length !== 1) {{
      alert("置換後のタグは1つだけ入力してください。");
      return;
    }}
    if (sourceTag === targetTags[0]) {{
      alert("置換前と置換後が同じタグです。");
      return;
    }}
  }}

  const replacementTag = targetTags[0] || "";
  const items = [];

  selected.forEach(card => {{
    const previous = loadCardMeta(card);
    const beforeTags = dedupeUserTags(splitUserTags(previous.tags));
    let afterTags = [...beforeTags];

    if (mode === "add") {{
      afterTags = dedupeUserTags([...afterTags, ...targetTags]);
    }} else if (mode === "remove") {{
      afterTags = afterTags.filter(tag => tag !== sourceTag);
    }} else if (mode === "replace") {{
      afterTags = dedupeUserTags(
        afterTags.map(tag => tag === sourceTag ? replacementTag : tag)
      );
    }}

    if (JSON.stringify(afterTags) === JSON.stringify(beforeTags)) return;

    items.push({{type:"meta", key:card.dataset.key, previous}});
    storageSet(
      metaKey(card),
      JSON.stringify({{...previous, tags:afterTags.join(", ")}})
    );
    applyCardMeta(card);
  }});

  if (!items.length) {{
    alert("変更対象はありませんでした。");
    return;
  }}

  const actionLabel =
    mode === "add"
      ? `タグ追加「${{targetTags.join(", ")}}」`
      : mode === "remove"
        ? `タグ削除「${{sourceTag}}」`
        : `タグ置換「${{sourceTag}}」→「${{replacementTag}}」`;

  pushUndo({{
    type:"bulk",
    items,
    label:`選択${{items.length}}件→${{actionLabel}}`
  }});

  rebuildTagFilter();
  applyFilters();
  saveUiState();
  closeModal("tagManagerModal");
}}

document.getElementById("bulkTag").addEventListener("click", openTagManager);
document.getElementById("tagManagerMode")?.addEventListener("change", updateTagManagerModeUi);
document.getElementById("tagManagerApply")?.addEventListener("click", applyBulkTagManagement);
document.getElementById("tagManagerTarget")?.addEventListener("keydown", event => {{
  if (event.key === "Enter") {{
    event.preventDefault();
    applyBulkTagManagement();
  }}
}});
document.getElementById("undoAction").addEventListener("click", undoLast);
document.getElementById("redoAction").addEventListener("click", redoLast);
document.getElementById("historyAction").addEventListener("click", () => {{
  renderHistory();
  openModal("historyModal");
}});
function openHelpDialog(tab = activeHelpTab, opener = null) {{
  setStatQuickFilterOpen(null);
  setFilterPanelOpen(false);
  setSecondaryActionsOpen(false);
  setReportInfoOpen(false);
  setHelpTab(tab);
  openModal("helpModal", opener);
}}

document.getElementById("helpAction").addEventListener("click", event => {{
  openHelpDialog(activeHelpTab, event.currentTarget);
}});

const statQuickFilterPanel = document.getElementById("statQuickFilterPanel");
const statQuickFilterTitle = document.getElementById("statQuickFilterTitle");
const statQuickFilterChoices = document.getElementById("statQuickFilterChoices");
const statQuickFilterSearch = document.getElementById("statQuickFilterSearch");
const statQuickSelectedOnly = document.getElementById("statQuickSelectedOnly");
const statQuickSelectVisible = document.getElementById("statQuickSelectVisible");
const statQuickClear = document.getElementById("statQuickClear");
const statFilterButtons = [...document.querySelectorAll("[data-stat-filter-target]")];
let activeStatQuickFilterTarget = null;
let statQuickSelectedOnlyMode = false;

function cleanStatChoiceLabel(text) {{
  return String(text || "")
    .replace(/^(車種|メーカー|作成者|年式|ペイント件数|整理進捗|タグ): */, "")
    .replace(/\\s+\\([^)]*(?:件|車種)[^)]*\\)\\s*$/, "");
}}

function renderStatQuickChoices(select, targetId) {{
  if (!statQuickFilterChoices || !select) return;
  statQuickFilterChoices.innerHTML = "";
  const selected = new Set(selectedFilterValues(select));
  const search = normFilterValue(statQuickFilterSearch?.value || "");
  const key = filterKeyForSelect(select);

  [...select.options].forEach(option => {{
    const rawLabel = cleanStatChoiceLabel(option.dataset.baseLabel || option.textContent);
    const active = option.value === "all" ? selected.size === 0 : selected.has(option.value);
    const visible = option.value === "all"
      ? !statQuickSelectedOnlyMode && !search
      : (!search || normFilterValue(rawLabel).includes(search)) && (!statQuickSelectedOnlyMode || active);
    const choice = document.createElement("button");
    choice.type = "button";
    choice.className = "stat-quick-choice";
    choice.setAttribute("role", "option");
    choice.dataset.value = option.value;
    choice.classList.toggle("hidden-choice", !visible);
    choice.classList.toggle("active", active);
    choice.setAttribute("aria-selected", active ? "true" : "false");

    if (option.value === "all") {{
      choice.textContent = "すべて解除";
    }} else {{
      const counts = filterChoiceCounts(select, option.value);
      const unit = select === progressFilter ? "車種" : "件";
      choice.textContent = `${{rawLabel}} (${{counts.single}}${{unit}} / ${{active ? "現在" : "追加後"}} ${{counts.combined}}${{unit}})`;
    }}

    choice.addEventListener("click", () => {{
      if (option.value === "all") {{
        setFilterValues(select, []);
        applyAndPersist();
        setStatQuickFilterOpen(null);
        return;
      }}
      toggleFilterValue(select, option.value);
      applyAndPersist();
      renderStatQuickChoices(select, targetId);
    }});
    statQuickFilterChoices.appendChild(choice);
  }});
}}

statQuickFilterSearch?.addEventListener("input", () => {{
  if (!activeStatQuickFilterTarget) return;
  renderStatQuickChoices(document.getElementById(activeStatQuickFilterTarget), activeStatQuickFilterTarget);
}});
statQuickSelectedOnly?.addEventListener("click", () => {{
  statQuickSelectedOnlyMode = !statQuickSelectedOnlyMode;
  statQuickSelectedOnly.classList.toggle("active", statQuickSelectedOnlyMode);
  if (activeStatQuickFilterTarget) renderStatQuickChoices(document.getElementById(activeStatQuickFilterTarget), activeStatQuickFilterTarget);
}});
statQuickSelectVisible?.addEventListener("click", () => {{
  if (!activeStatQuickFilterTarget) return;
  const select = document.getElementById(activeStatQuickFilterTarget);
  const visibleValues = [...statQuickFilterChoices.querySelectorAll('.stat-quick-choice:not(.hidden-choice)')]
    .map(choice => choice.dataset.value).filter(value => value && value !== "all");
  setFilterValues(select, [...new Set([...selectedFilterValues(select), ...visibleValues])]);
  applyAndPersist();
  renderStatQuickChoices(select, activeStatQuickFilterTarget);
}});
statQuickClear?.addEventListener("click", () => {{
  if (!activeStatQuickFilterTarget) return;
  const select = document.getElementById(activeStatQuickFilterTarget);
  setFilterValues(select, []);
  applyAndPersist();
  renderStatQuickChoices(select, activeStatQuickFilterTarget);
}});

function setStatQuickFilterOpen(targetId = null, button = null) {{
  if (!statQuickFilterPanel) return;

  const open = Boolean(targetId && button);
  activeStatQuickFilterTarget = open ? targetId : null;
  statFilterButtons.forEach(btn => btn.setAttribute("aria-expanded", "false"));

  if (!open) {{
    statQuickFilterPanel.classList.add("hidden");
    statQuickFilterPanel.setAttribute("aria-hidden", "true");
    if (statQuickFilterChoices) statQuickFilterChoices.innerHTML = "";
    return;
  }}

  const select = document.getElementById(targetId);
  if (!select) return;
  if (statQuickFilterSearch) statQuickFilterSearch.value = "";
  statQuickSelectedOnlyMode = false;
  statQuickSelectedOnly?.classList.remove("active");

  const titles = {{
    vehicleFilter: "車種で絞り込み",
    makeFilter: "メーカーで絞り込み",
    creatorFilter: "作成者で絞り込み",
    yearFilter: "年式で絞り込み",
    decisionFilter: "整理状態で絞り込み",
    progressFilter: "車種の整理進捗で絞り込み",
    paintCountFilter: "ペイント件数で絞り込み",
    tagFilter: "タグで絞り込み"
  }};
  statQuickFilterTitle.textContent = `${{titles[targetId] || "クイック絞り込み"}}（複数選択）`;
  renderStatQuickChoices(select, targetId);

  statQuickFilterPanel.classList.remove("hidden");
  statQuickFilterPanel.setAttribute("aria-hidden", "false");
  button.setAttribute("aria-expanded", "true");

  requestAnimationFrame(() => {{
    const rect = button.getBoundingClientRect();
    const panelRect = statQuickFilterPanel.getBoundingClientRect();
    const margin = 8;
    let left = rect.left;
    left = Math.max(margin, Math.min(left, window.innerWidth - panelRect.width - margin));
    let top = rect.bottom + 6;
    if (top + panelRect.height > window.innerHeight - margin) {{
      top = Math.max(margin, rect.top - panelRect.height - 6);
    }}
    statQuickFilterPanel.style.left = `${{Math.round(left)}}px`;
    statQuickFilterPanel.style.top = `${{Math.round(top)}}px`;
  }});
}}

statFilterButtons.forEach(button => button.addEventListener("click", () => {{
  const targetId = button.dataset.statFilterTarget;
  const alreadyOpen =
    activeStatQuickFilterTarget === targetId &&
    !statQuickFilterPanel.classList.contains("hidden");
  const insideDetailedFilter = Boolean(button.closest("#filterPanel"));
  if (!insideDetailedFilter) setFilterPanelOpen(false);
  setSecondaryActionsOpen(false);
  setReportInfoOpen(false);
  setStatQuickFilterOpen(alreadyOpen ? null : targetId, alreadyOpen ? null : button);
}}));

document.addEventListener("pointerdown", event => {{
  if (!statQuickFilterPanel || statQuickFilterPanel.classList.contains("hidden")) return;
  const target = event.target;
  if (statQuickFilterPanel.contains(target)) return;
  if (target?.closest?.("[data-stat-filter-target]")) return;
  setStatQuickFilterOpen(null);
}});

const filterPanelToggle = document.getElementById("filterPanelToggle");
const filterPanel = document.getElementById("filterPanel");
const secondaryActionsToggle = document.getElementById("secondaryActionsToggle");
const secondaryActions = document.getElementById("secondaryActions");
const reportInfoAction = document.getElementById("reportInfoAction");
const reportInfoPanel = document.getElementById("reportInfoPanel");
const filterPanelTabs = [...document.querySelectorAll("[data-filter-panel-tab]")];
const reportInfoTabs = [...document.querySelectorAll("[data-report-info-tab]")];
const helpTabs = [...document.querySelectorAll("[data-help-tab]")];
let activeFilterPanelTab = "conditions";
let activeReportInfoTab = "overview";
let activeHelpTab = "basics";

function setTabbedPaneState(name, allowedNames, paneIds, buttons, dataKey) {{
  const activeName = allowedNames.includes(String(name || "")) ? String(name) : allowedNames[0];
  Object.entries(paneIds).forEach(([paneName, paneId]) => {{
    document.getElementById(paneId)?.classList.toggle("hidden", paneName !== activeName);
  }});
  buttons.forEach(button => {{
    const active = String(button.dataset[dataKey] || "") === activeName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }});
  return activeName;
}}

function setFilterPanelTab(name = "conditions") {{
  activeFilterPanelTab = setTabbedPaneState(
    name, ["conditions", "bulk"],
    {{conditions:"filterPanelConditions", bulk:"filterPanelBulk"}},
    filterPanelTabs, "filterPanelTab"
  );
}}

function setReportInfoTab(name = "overview") {{
  activeReportInfoTab = setTabbedPaneState(
    name, ["overview", "backup"],
    {{overview:"reportInfoOverview", backup:"reportInfoBackup"}},
    reportInfoTabs, "reportInfoTab"
  );
}}

function setHelpTab(name = "basics") {{
  activeHelpTab = setTabbedPaneState(
    name, ["basics", "organize", "data", "environment"],
    {{basics:"helpBasicsPane", organize:"helpOrganizePane", data:"helpDataPane", environment:"helpEnvironmentPane"}},
    helpTabs, "helpTab"
  );
}}

filterPanelTabs.forEach(button => button.addEventListener("click", () => {{
  setStatQuickFilterOpen(null);
  setFilterPanelTab(button.dataset.filterPanelTab);
}}));

reportInfoTabs.forEach(button => button.addEventListener("click", () => {{
  setReportInfoTab(button.dataset.reportInfoTab);
}}));

helpTabs.forEach(button => button.addEventListener("click", () => {{
  setHelpTab(button.dataset.helpTab);
}}));

function setFilterPanelOpen(open) {{
  if (!filterPanel || !filterPanelToggle) return;
  filterPanel.classList.toggle("hidden", !open);
  filterPanel.setAttribute("aria-hidden", open ? "false" : "true");
  filterPanelToggle.setAttribute("aria-expanded", open ? "true" : "false");
  filterPanelToggle.textContent = open ? "絞り込みを閉じる" : "絞り込み";
  if (open) {{
    setFilterPanelTab(activeFilterPanelTab);
    renderAllDetailFilterChoices();
    updateDynamicFilterCounts();
  }}
}}

function setSecondaryActionsOpen(open) {{
  if (!secondaryActions || !secondaryActionsToggle) return;
  secondaryActions.classList.toggle("hidden", !open);
  secondaryActions.setAttribute("aria-hidden", open ? "false" : "true");
  secondaryActionsToggle.setAttribute("aria-expanded", open ? "true" : "false");
  secondaryActionsToggle.textContent = open ? "その他の操作を閉じる" : "その他の操作";
}}

function setReportInfoOpen(open) {{
  if (!reportInfoPanel) return;
  reportInfoPanel.classList.toggle("hidden", !open);
  reportInfoPanel.setAttribute("aria-hidden", open ? "false" : "true");
  if (reportInfoAction) {{
    reportInfoAction.setAttribute("aria-expanded", open ? "true" : "false");
    reportInfoAction.textContent = open ? "レポート情報を閉じる" : "レポート情報";
  }}
  if (open) setReportInfoTab(activeReportInfoTab);
}}

filterPanelToggle?.addEventListener("click", () => {{
  const open = filterPanel?.classList.contains("hidden");
  setStatQuickFilterOpen(null);
  setSecondaryActionsOpen(false);
  setReportInfoOpen(false);
  setFilterPanelOpen(Boolean(open));
}});

secondaryActionsToggle?.addEventListener("click", () => {{
  const open = secondaryActions?.classList.contains("hidden");
  setStatQuickFilterOpen(null);
  setFilterPanelOpen(false);
  setReportInfoOpen(false);
  setSecondaryActionsOpen(Boolean(open));
}});

reportInfoAction?.addEventListener("click", () => {{
  const open = reportInfoPanel?.classList.contains("hidden");
  setStatQuickFilterOpen(null);
  setFilterPanelOpen(false);
  setSecondaryActionsOpen(false);
  setReportInfoOpen(Boolean(open));
}});

// 開いているメニューの外側をクリックしたら閉じる。
// トグル自身のクリックは各clickハンドラーに任せ、
// パネル内部の操作では意図せず閉じないようにする。
document.addEventListener("pointerdown", event => {{
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (filterPanel && !filterPanel.classList.contains("hidden")
      && !filterPanel.contains(target)
      && !filterPanelToggle?.contains(target)) {{
    setFilterPanelOpen(false);
  }}

  if (reportInfoPanel && !reportInfoPanel.classList.contains("hidden")
      && !reportInfoPanel.contains(target)
      && !reportInfoAction?.contains(target)) {{
    setReportInfoOpen(false);
  }}

  if (secondaryActions && !secondaryActions.classList.contains("hidden")
      && !secondaryActions.contains(target)
      && !secondaryActionsToggle?.contains(target)) {{
    setSecondaryActionsOpen(false);
  }}

  // 「閉じる」を持つHTMLモーダルは、背景部分のクリックでも統一して閉じる。
  document.querySelectorAll(".modal").forEach(modal => {{
    if (!modal.classList.contains("hidden") && target === modal) {{
      closeModal(modal.id);
    }}
  }});
}});

document.addEventListener("keydown", e => {{
  const topModal = getTopOpenModal();
  if (topModal && e.key === "Tab") {{
    trapModalTab(e, topModal);
    return;
  }}
  if (e.key !== "Escape") return;

  // 「閉じる」を持つHTMLモーダルが開いている場合は、まず最前面相当の1件を閉じる。
  if (topModal) {{
    closeModal(topModal.id);
    e.preventDefault();
    return;
  }}

  setStatQuickFilterOpen(null);
  setFilterPanelOpen(false);
  setSecondaryActionsOpen(false);
  setReportInfoOpen(false);
}});

function duplicateTextValues(values) {{
  const counts = new Map();
  values.forEach(value => {{
    const key = String(value ?? "");
    counts.set(key, (counts.get(key) || 0) + 1);
  }});
  return [...counts.entries()].filter(([,count]) => count > 1).map(([value]) => value);
}}

function collectReportDataIntegrity() {{
  const cardKeys = cards.map(card => String(card.dataset.key || ""));
  const missingCardKeys = cards.filter(card => !String(card.dataset.key || "")).map(card => String(card.dataset.car || "?") || "?");
  const duplicateCardKeys = duplicateTextValues(cardKeys.filter(Boolean));
  const csvKeys = Object.keys(CSV_RECORDS);
  const cardKeySet = new Set(cardKeys.filter(Boolean));
  const csvKeySet = new Set(csvKeys);
  const missingCsvRecords = [...cardKeySet].filter(key => !csvKeySet.has(key));
  const orphanCsvRecords = csvKeys.filter(key => !cardKeySet.has(key));
  const csvRecordKeyMismatches = csvKeys.filter(key => String(CSV_RECORDS[key]?.ui_key || "") !== key);

  const groups = [...document.querySelectorAll(".car-group")];
  const groupIds = groups.map(group => String(group.dataset.carGroup || ""));
  const duplicateGroupIds = duplicateTextValues(groupIds.filter(Boolean));
  const groupIdSet = new Set(groupIds.filter(Boolean));
  const cardsWithoutGroup = cards
    .filter(card => !groupIdSet.has(String(card.dataset.car || "")))
    .map(card => String(card.dataset.key || card.dataset.car || "?"));

  const vehicleCountMismatches = [];
  const progressMaxMismatches = [];
  groups.forEach(group => {{
    const carId = String(group.dataset.carGroup || "");
    const declared = Number(group.dataset.paintCount || 0);
    const actual = (VEHICLE_CARDS.get(carId) || []).length;
    if (!Number.isFinite(declared) || declared !== actual) {{
      vehicleCountMismatches.push(`${{carId || "?"}}: 宣言 ${{group.dataset.paintCount || "?"}} / 実数 ${{actual}}`);
    }}
    const progress = group.querySelector("[data-group-progress] progress");
    const progressMax = progress ? Number(progress.max || progress.getAttribute("max") || 0) : NaN;
    if (!progress || !Number.isFinite(progressMax) || progressMax !== actual) {{
      progressMaxMismatches.push(`${{carId || "?"}}: max ${{progress ? progress.getAttribute("max") : "なし"}} / 実数 ${{actual}}`);
    }}
  }});

  const cardsWithImage = cards.filter(card => Boolean(card.querySelector("img.livery-image")));
  const thumbnailMissingElements = cards
    .filter(card => !card.querySelector("img.livery-image"))
    .map(card => String(card.dataset.key || card.dataset.car || "?"));
  const thumbnailMissingSources = cardsWithImage
    .filter(card => {{
      const img = card.querySelector("img.livery-image");
      return !String(img?.getAttribute("src") || "").trim() || !String(img?.dataset?.full || "").trim();
    }})
    .map(card => String(card.dataset.key || card.dataset.car || "?"));

  const myDesignIndexes = cards.map(card => Number(card.dataset.myDesignIndex || 0));
  const myDesignIndexSet = new Set(myDesignIndexes);
  const myDesignIndexIssues = [];
  if (cards.length) {{
    if (myDesignIndexes.some(value => !Number.isInteger(value) || value < 1)) myDesignIndexIssues.push("無効な番号あり");
    if (myDesignIndexSet.size !== cards.length) myDesignIndexIssues.push("番号重複あり");
    if (Math.min(...myDesignIndexes) !== 1 || Math.max(...myDesignIndexes) !== cards.length) {{
      myDesignIndexIssues.push(`範囲 ${{Math.min(...myDesignIndexes)}}〜${{Math.max(...myDesignIndexes)}} / 期待 1〜${{cards.length}}`);
    }}
  }}

  const fh6DateIssues = cards.filter(card => {{
    const raw = String(card.dataset.fh6Date || "");
    const display = String(card.dataset.fh6DateDisplay || "");
    if (!/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(raw) || !/^\\d{{2}}\\/\\d{{2}}\\/\\d{{4}}$/.test(display)) return true;
    const [year, month, day] = raw.split("-").map(Number);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return true;
    return display !== `${{String(day).padStart(2,"0")}}/${{String(month).padStart(2,"0")}}/${{year}}`;
  }}).map(card => String(card.dataset.key || card.dataset.car || "?"));

  const exactDuplicateGroups = new Map();
  cards.filter(card => card.dataset.exactDuplicate === "1").forEach(card => {{
    const group = String(card.dataset.exactDuplicateGroup || "");
    if (!exactDuplicateGroups.has(group)) exactDuplicateGroups.set(group, []);
    exactDuplicateGroups.get(group).push(card);
  }});
  const exactDuplicateIssues = [];
  exactDuplicateGroups.forEach((members, group) => {{
    if (!group) exactDuplicateIssues.push("グループIDなし");
    const expected = Number(members[0]?.dataset.exactDuplicateCount || 0);
    if (members.length < 2 || expected !== members.length || members.some(card => Number(card.dataset.exactDuplicateCount || 0) !== members.length)) {{
      exactDuplicateIssues.push(`${{group || "?"}}: 表示 ${{members.length}} / 宣言 ${{expected || "?"}}`);
    }}
    if (members.some(card => card.dataset.similarKind !== "image" || Number(card.dataset.similarCount || 0) < members.length)) {{
      exactDuplicateIssues.push(`${{group || "?"}}: 画像一致類似候補との対応不整合`);
    }}
  }});

  const fh6SlotIssues = [];
  if (!Array.isArray(FH6_MY_DESIGN_INSTANCES)) {{
    fh6SlotIssues.push("実スロット配列なし");
  }} else {{
    if (FH6_MY_DESIGN_INSTANCES.length !== cards.length) {{
      fh6SlotIssues.push(`実スロット ${{FH6_MY_DESIGN_INSTANCES.length}} / カード ${{cards.length}}`);
    }}
    const positions = new Set();
    const cardByKey = new Map(cards.map(card => [String(card.dataset.key || ""), card]));
    FH6_MY_DESIGN_INSTANCES.forEach((item, index) => {{
      const absolute = index + 1;
      const expectedColumn = Math.ceil(absolute / 2);
      const expectedRow = absolute % 2 ? "U" : "D";
      const expectedPosition = `#${{String(expectedColumn).padStart(Math.max(3, String(Math.ceil(Math.max(1, FH6_MY_DESIGN_INSTANCES.length) / 2)).length), "0")}}${{expectedRow}}`;
      const position = String(item.position || "");
      if (Number(item.column || 0) !== expectedColumn || String(item.row || "") !== expectedRow || position !== expectedPosition) {{
        fh6SlotIssues.push(`${{absolute}}番目: ${{position || "位置なし"}} / 期待 ${{expectedPosition}}`);
      }}
      if (positions.has(position)) fh6SlotIssues.push(`位置重複: ${{position}}`);
      positions.add(position);
      const card = cardByKey.get(String(item.ui_key || ""));
      if (!card) fh6SlotIssues.push(`${{position || absolute}}: 対応カードなし`);
      else if (String(card.dataset.fh6Date || "") !== String(item.fh6_date_raw || "")
        || String(card.dataset.fh6DateDisplay || "") !== String(item.fh6_date_display || "")) {{
        fh6SlotIssues.push(`${{position || absolute}}: FH6日付不一致`);
      }}
    }});
  }}

  const issues = [];
  const addIssues = (label, values) => values.slice(0, 20).forEach(value => issues.push(`${{label}}: ${{value}}`));
  addIssues("カードキーなし", missingCardKeys);
  addIssues("カードキー重複", duplicateCardKeys);
  addIssues("CSVなし", missingCsvRecords);
  addIssues("孤立CSV", orphanCsvRecords);
  addIssues("CSVレコードキー不一致", csvRecordKeyMismatches);
  addIssues("車種グループ重複", duplicateGroupIds);
  addIssues("車種グループなし", cardsWithoutGroup);
  addIssues("車種件数不一致", vehicleCountMismatches);
  addIssues("進捗max不一致", progressMaxMismatches);
  addIssues("サムネイル要素なし", thumbnailMissingElements);
  addIssues("サムネイル参照なし", thumbnailMissingSources);
  addIssues("マイデザイン番号", myDesignIndexIssues);
  addIssues("FH6表示日付", fh6DateIssues);
  addIssues("再DL重複グループ", exactDuplicateIssues);
  addIssues("FH6実スロット", fh6SlotIssues);

  return {{
    cardKeys, csvKeys, missingCardKeys, duplicateCardKeys, missingCsvRecords, orphanCsvRecords,
    csvRecordKeyMismatches, groupIds, duplicateGroupIds, cardsWithoutGroup, vehicleCountMismatches,
    progressMaxMismatches, cardsWithImage, thumbnailMissingElements, thumbnailMissingSources,
    myDesignIndexIssues, fh6DateIssues, exactDuplicateGroups, exactDuplicateIssues, fh6SlotIssues, issues
  }};
}}

let lastDiagnosticsStatus = null;

function thumbnailDeliveryMode() {{
  const image = document.querySelector("img.livery-image");
  if (!image) return "サムネイルなし";
  const source = String(image.getAttribute("src") || "").trim();
  if (source.startsWith("data:image/")) return "HTML内に埋め込み";
  if (source) return "thumbnails 外部参照";
  return "参照を確認";
}}

function updateStartupReadiness() {{
  const panel = document.getElementById("startupReadinessPanel");
  const status = document.getElementById("startupReadinessStatus");
  const storageStatus = document.getElementById("startupStorageStatus");
  const dataStatus = document.getElementById("startupDataStatus");
  const thumbnailStatus = document.getElementById("startupThumbnailStatus");
  const note = document.getElementById("startupReadinessNote");
  if (!panel || !status || !storageStatus || !dataStatus || !thumbnailStatus || !note) return null;

  const integrity = collectReportDataIntegrity();
  const dataOk = integrity.issues.length === 0;
  const storageOk = Boolean(persistentStorage);
  const diagnosticsFailed = Boolean(lastDiagnosticsStatus && !lastDiagnosticsStatus.ok);
  const runtimeError = document.getElementById("uiStatus")?.dataset?.state === "error";
  const state = runtimeError || !dataOk || diagnosticsFailed ? "error" : (storageOk ? "ok" : "warning");
  panel.dataset.state = state;
  status.textContent = state === "ok" ? "準備OK" : (state === "warning" ? "要確認" : "問題あり");
  storageStatus.textContent = storageOk ? "ブラウザ保存 OK" : "一時メモリ";
  dataStatus.textContent = dataOk ? `整合性OK（${{cards.length}}件）` : `問題 ${{integrity.issues.length}}件`;
  thumbnailStatus.textContent = thumbnailDeliveryMode();

  if (runtimeError) {{
    note.textContent = "JavaScriptエラーを検出しました。上のエラー内容を確認し、動作診断を実行してください。";
  }} else if (lastDiagnosticsStatus?.ok) {{
    note.textContent = `動作診断 ${{lastDiagnosticsStatus.okCount}} / ${{lastDiagnosticsStatus.total}} 項目正常。通常利用できます。`;
  }} else if (diagnosticsFailed) {{
    note.textContent = `動作診断で ${{lastDiagnosticsStatus.total - lastDiagnosticsStatus.okCount}} 項目の問題を検出しました。診断結果を確認してください。`;
  }} else if (!dataOk) {{
    note.textContent = "レポート内データに不整合があります。動作診断で詳細を確認してください。";
  }} else if (!storageOk) {{
    note.textContent = "一時メモリで動作中です。タブを閉じる前にユーザーデータ保存を利用してください。";
  }} else {{
    note.textContent = "基本状態は正常です。初回利用時やHTMLを移動した後は動作診断を実行すると、サムネイル実読込まで確認できます。";
  }}
  return {{state, dataOk, storageOk, integrity, thumbnailMode:thumbnailDeliveryMode()}};
}}

function probeImageSource(source, timeoutMs = 5000) {{
  return new Promise(resolve => {{
    const src = String(source || "").trim();
    if (!src) {{ resolve(false); return; }}
    const probe = new Image();
    let settled = false;
    const finish = ok => {{
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      probe.onload = null;
      probe.onerror = null;
      resolve(Boolean(ok));
    }};
    const timer = setTimeout(() => finish(false), timeoutMs);
    probe.onload = () => finish(probe.naturalWidth > 0);
    probe.onerror = () => finish(false);
    probe.src = src;
    if (probe.complete) finish(probe.naturalWidth > 0);
  }});
}}

async function verifyThumbnailSources() {{
  const targets = cards
    .map(card => {{
      const img = card.querySelector("img.livery-image");
      if (!img) return null;
      const source = String(img.currentSrc || img.src || img.dataset.full || "").trim();
      return source ? {{key:String(card.dataset.key || "?"), source}} : null;
    }})
    .filter(Boolean);
  const results = await Promise.all(targets.map(async target => ({{...target, ok:await probeImageSource(target.source)}})));
  const failed = results.filter(result => !result.ok);
  return {{checked:results.length, failed, ok:failed.length === 0}};
}}

function escapeDiagnosticHtml(value) {{
  return String(value ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[ch]));
}}

async function runSelfDiagnostics() {{
  const diagnosticsBody = document.getElementById("diagnosticsBody");
  const diagnosticsButton = document.getElementById("selfDiagnostics");
  if (diagnosticsButton) diagnosticsButton.disabled = true;
  if (diagnosticsBody) diagnosticsBody.innerHTML = `<p><b>診断中…</b> レポートデータとサムネイル参照を確認しています。</p>`;
  openModal("diagnosticsModal");

  try {{
    const integrity = collectReportDataIntegrity();
    const thumbnailCheck = await verifyThumbnailSources();
    const requiredIds = [
      "q","decisionFilter","progressFilter","vehicleFilter","makeFilter","yearFilter","creatorFilter","paintCountFilter",
      "vinylCountFilter","vinylMin","vinylMax","tagFilter","activeFilterChips","clearFilters","filterPanelToggle","vehicleStatAction","makeStatAction","creatorStatAction","yearStatAction",
      "statQuickFilterPanel","statQuickFilterChoices","selectVisible","bulkKeep","bulkDelete","firstUnfinishedVehicle","previousUnfinishedVehicle","nextUnfinishedVehicle",
      "vehicleWorkflowBar","vehicleProgressNoneCount","vehicleProgressPartialCount","vehicleProgressCompleteCount",
      "unfinishedVehiclesOnly","previousUnfinishedVehicleQuick","nextUnfinishedVehicleQuick","vehicleWorkflowHint",
      "organizationCompletionSummary","organizationCompletionStatus","organizationCompletionCounts","organizationCompletionBackup",
      "bulkUndecided","bulkTag","tagManagerModal","tagManagerMode","tagManagerSource","tagManagerTarget","tagManagerApply","exportCsv","exportFilteredCsv","downloadExcel","helpAction","themeToggle",
      "reportInfoAction","reportInfoPanel","reportInfoOverview","reportInfoBackup","reportOverviewTab","reportBackupTab",
      "filterPanelConditions","filterPanelBulk","filterConditionsTab","filterBulkTab",
      "helpBasicsTab","helpOrganizeTab","helpDataTab","helpEnvironmentTab",
      "helpBasicsPane","helpOrganizePane","helpDataPane","helpEnvironmentPane",
      "backupStatusPanel","fullBackupStatus","fullBackupTime",
      "decisionBackupStatus","decisionBackupTime","backupChangeSummary","backupChangeSummaryStatus",
      "backupChangeDecisionCount","backupChangeTagNoteCount","backupChangeFavoriteCount","backupChangeReviewCount","backupChangeScanCount",
      "backupRecommendation","exportUserData","importUserData","exportDecisions","importDecisions",
      "startupReadinessPanel","startupReadinessStatus","startupStorageStatus","startupDataStatus","startupThumbnailStatus",
      "startupReadinessNote","startupDiagnosticsAction","startupHelpAction","runtimeErrorMessage","runtimeDiagnosticsAction",
      "showRemoved","newDiffCount","removedCount","removedModal","removedBody",
      "similarOnly","similarImageOnly","similarCreatorTitleOnly","exactDuplicateOnly",
      "fh6MyDesignSection","fh6MyDesignViewport","fh6MyDesignTrack","fh6MyDesignPrev","fh6MyDesignNext","fh6MyDesignPosition"
    ];
    const checks = [
      ["ビルド", FH6_BUILD === "v{VERSION}", FH6_BUILD],
      ["UI初期化", document.getElementById("uiStatus")?.textContent === "正常", document.getElementById("uiStatus")?.textContent || "不明"],
      ["ペイントカード", cards.length > 0, `${{cards.length}}件`],
      ["カードキー一意", integrity.missingCardKeys.length === 0 && integrity.duplicateCardKeys.length === 0,
        `キーなし ${{integrity.missingCardKeys.length}} / 重複 ${{integrity.duplicateCardKeys.length}}件`],
      ["カード / CSV対応", integrity.missingCsvRecords.length === 0 && integrity.orphanCsvRecords.length === 0,
        `CSVなし ${{integrity.missingCsvRecords.length}} / 孤立CSV ${{integrity.orphanCsvRecords.length}}件`],
      ["CSVレコードキー", integrity.csvRecordKeyMismatches.length === 0, `不一致 ${{integrity.csvRecordKeyMismatches.length}}件`],
      ["CSVデータ整合", Object.keys(CSV_RECORDS).length === cards.length, `${{Object.keys(CSV_RECORDS).length}} / ${{cards.length}}件`],
      ["車種グループ整合", integrity.duplicateGroupIds.length === 0 && integrity.cardsWithoutGroup.length === 0 && integrity.vehicleCountMismatches.length === 0,
        `重複 ${{integrity.duplicateGroupIds.length}} / グループなし ${{integrity.cardsWithoutGroup.length}} / 件数不一致 ${{integrity.vehicleCountMismatches.length}}件`],
      ["進捗メタデータ", integrity.progressMaxMismatches.length === 0, `max不一致 ${{integrity.progressMaxMismatches.length}}件`],
      ["サムネイル参照", integrity.thumbnailMissingElements.length === 0 && integrity.thumbnailMissingSources.length === 0,
        `要素なし ${{integrity.thumbnailMissingElements.length}} / 参照なし ${{integrity.thumbnailMissingSources.length}}件`],
      ["サムネイル読込", thumbnailCheck.ok, `${{thumbnailCheck.checked}}件確認 / ${{thumbnailCheck.failed.length}}件失敗`],
      ["表示中CSV順序", typeof cardsInCurrentDisplayOrder === "function", "現在のDOM表示順"],
      ["Excel", Boolean(document.getElementById("downloadExcel")), "livery-organizer-for-fh6.xlsx"],
      ["固定UI要素", requiredIds.every(id => document.getElementById(id)), `${{requiredIds.filter(id => !document.getElementById(id)).length}}件不足`],
      ["複数絞り込み", multiFilterSelects.every(select => select.multiple), `${{multiFilterSelects.filter(select => !select.multiple).length}}件未対応`],
      ["UI state schema", UI_STATE_VERSION === 3, `v${{UI_STATE_VERSION}}`],
      ["絞り込みプリセット", Boolean(document.getElementById("filterPresetSelect")), "localStorage"],
      ["作成者ボタン", document.querySelectorAll(".creator-chip").length === Math.max(0, creatorFilter.options.length - 1),
        `${{document.querySelectorAll(".creator-chip").length}} / ${{Math.max(0, creatorFilter.options.length - 1)}}人`],
      ["カード識別子", cards.every(card => Boolean(card.dataset.key)), "fingerprint"],
      ["判定ボタン", cards.every(card => card.querySelectorAll(".decision button[data-state]").length === 3), "各カード3個"],
      ["車種別整理進捗", [...document.querySelectorAll(".car-group")].every(group => Boolean(group.querySelector("[data-group-progress] [data-group-progress-text]"))),
        `${{document.querySelectorAll(".car-group [data-group-progress]").length}} / ${{document.querySelectorAll(".car-group").length}}車種`],
      ["整理進捗ワークフロー", Boolean(progressFilter)
        && ["progress-asc","progress-desc"].every(value => [...sortOrder.options].some(option => option.value === value))
        && document.querySelectorAll("[data-first-unfinished-vehicle]").length >= 1
        && document.querySelectorAll("[data-previous-unfinished-vehicle]").length >= 2
        && document.querySelectorAll("[data-next-unfinished-vehicle]").length >= 2
        && Boolean(document.getElementById("unfinishedVehiclesOnly"))
        && document.querySelectorAll("button[data-group-progress]").length === document.querySelectorAll(".car-group").length,
        "進捗バッジ + 未完了ショートカット + 最初 / 前 / 次の未完了車種"],
      ["車種整理サマリー", ["none","partial","complete"].every(state => Boolean(document.querySelector(`[data-vehicle-progress-state="${{state}}"]`)))
        && vehicleProgressSummary().total === VEHICLE_CARDS.size,
        `未着手 ${{vehicleProgressSummary().none}} / 整理中 ${{vehicleProgressSummary().partial}} / 完了 ${{vehicleProgressSummary().complete}}車種`],
      ["バックアップ状態", BACKUP_STATUS_VERSION === 2 && Boolean(document.getElementById("backupStatusPanel")),
        `schema v${{BACKUP_STATUS_VERSION}} / full + decisions`],
      ["バックアップ変更サマリー", typeof backupSnapshotChangeSummary === "function"
        && Boolean(document.getElementById("backupChangeSummary")),
        "判定 + タグ・メモ + お気に入り + 後で確認 + 新規判定基準"],
      ["コンパクトメニュー", filterPanelTabs.length === 2 && reportInfoTabs.length === 2
        && Boolean(document.getElementById("filterPanelConditions")) && Boolean(document.getElementById("filterPanelBulk"))
        && Boolean(document.getElementById("reportInfoOverview")) && Boolean(document.getElementById("reportInfoBackup")),
        "絞り込み2タブ + レポート情報2タブ"],
      ["整理完了サマリー", typeof updateOrganizationCompletionSummary === "function"
        && Boolean(document.getElementById("organizationCompletionSummary"))
        && Boolean(document.getElementById("organizationCompletionBackup")),
        "未決定0件で整理結果 + バックアップ状態"],
      ["車種ナビゲーション位置", typeof visibleVehicleNavigationState === "function"
        && typeof visibleVehicleSequence === "function"
        && typeof updateVehicleNavigationUi === "function"
        && Boolean(document.getElementById("vehicleWorkflowHint")),
        "共通車種順序 + 現在車種の強調 + 未完了車種内の現在位置"],
      ["未完了車種移動", typeof findFirstVisibleUnfinishedVehicle === "function"
        && typeof findPreviousVisibleUnfinishedVehicle === "function"
        && typeof findNextVisibleUnfinishedVehicle === "function"
        && typeof goToFirstUnfinishedVehicle === "function"
        && typeof goToPreviousUnfinishedVehicle === "function"
        && typeof goToNextUnfinishedVehicle === "function",
        "現在の表示順で最初 / 前 / 次へ移動 + V / Shift+V"],
      ["現在仕様ヘルプ", helpTabs.length === 4
        && typeof setHelpTab === "function"
        && ["helpBasicsPane","helpOrganizePane","helpDataPane","helpEnvironmentPane"].every(id => Boolean(document.getElementById(id))),
        "探す・絞る / 整理・車種 / 保存・出力 / 操作・安全"],
      ["共通状態集計", typeof collectCardStateSummary === "function", "判定 + フラグ + 新規 + 類似候補 + 再DL重複"],
      ["上部状態クイック絞り込み", ["undecidedStatAction","favoriteStatAction","reviewStatAction","newStatAction","similarStatAction","exactDuplicateStatAction"]
        .every(id => Boolean(document.getElementById(id))),
        "未決定 + お気に入り + 後で確認 + 新規 + 類似候補 + 再DL重複"],
      ["類似理由別絞り込み", ["similarOnly","similarImageOnly","similarCreatorTitleOnly"]
        .every(id => Boolean(document.getElementById(id)))
        && typeof normalizeSimilarKind === "function",
        "すべて / 画像一致 / 同一作者・同名"],
      ["再DL重複絞り込み", ["exactDuplicateOnly","exactDuplicateStatAction"]
        .every(id => Boolean(document.getElementById(id))),
        "現在スナップショット内の完全一致再ダウンロードを直接絞り込み"],
      ["再DL重複専用整理", typeof renderExactDuplicateModal === "function"
        && typeof chooseExactDuplicateKeeper === "function"
        && Boolean(document.getElementById("exactDuplicateModal")),
        "グループ比較 + 前/次移動 + 残す1件を選択"],
      ["前回基準との差分", typeof renderScanDiffModal === "function"
        && typeof collectCurrentScan === "function"
        && Boolean(document.getElementById("showRemoved"))
        && Boolean(document.getElementById("removedModal")),
        "新規 + 消滅を同一画面で確認"],
      ["マイデザイン通し番号", cards.length > 0
        && integrity.myDesignIndexIssues.length === 0
        && cards.every(card => Boolean(card.querySelector(".my-design-index"))),
        `#001〜#${{String(cards.length).padStart(Math.max(3, String(cards.length).length), "0")}} / 不整合 ${{integrity.myDesignIndexIssues.length}}件`],
      ["FH6表示日付", integrity.fh6DateIssues.length === 0,
        `DD/MM/YYYY / 不整合 ${{integrity.fh6DateIssues.length}}件`],
      ["再DL重複グループ整合", integrity.exactDuplicateIssues.length === 0,
        `${{integrity.exactDuplicateGroups.size}}組 / 不整合 ${{integrity.exactDuplicateIssues.length}}件`],
      ["FH6マイデザイン情報配置", cards.every(card => Boolean(card.querySelector(".fh6-display-date"))
        && Boolean(card.querySelector(".fh6-creator-display"))),
        "タイトル → 作成者 → 日付の順で表示し、その下に取得日時・バイナル数を配置"],
      ["FH6マイデザイン実スロット", [...sortOrder.options].some(option => option.value === "fh6-my-designs")
        && typeof renderFh6MyDesignView === "function"
        && typeof moveFh6MyDesignColumn === "function"
        && integrity.fh6SlotIssues.length === 0,
        `2段×横スクロール + 実スロット ${{Array.isArray(FH6_MY_DESIGN_INSTANCES) ? FH6_MY_DESIGN_INSTANCES.length : 0}}件 / 不整合 ${{integrity.fh6SlotIssues.length}}件`],
      ["FH6マイデザイン位置ジャンプ", typeof jumpToFh6MyDesignPosition === "function"
        && typeof resolveFh6MyDesignJumpTarget === "function"
        && Boolean(document.getElementById("fh6MyDesignJumpInput"))
        && Boolean(document.getElementById("fh6MyDesignJump")),
        "実スロット番号 / 列＋U/D位置を指定して直接移動"],
      ["FH6マイデザイン車種ジャンプ", typeof jumpToFh6MyDesignTarget === "function"
        && typeof matchingFh6Vehicles === "function"
        && typeof selectFh6VehicleJump === "function"
        && typeof selectFh6VehicleQueryJump === "function"
        && typeof setFh6VehicleSuggestionIndex === "function"
        && typeof moveFh6VehicleMatch === "function"
        && Boolean(document.getElementById("fh6MyDesignJumpSuggestions"))
        && Boolean(document.getElementById("fh6VehicleMatchNav")),
        "車種名部分一致 + ↑/↓候補選択 + Shift+←/→一致巡回 + Jで入力欄復帰 + 選択車種の実スロット巡回"],
      ["FH6削除済み（仮）", typeof markFh6InstanceTempDeleted === "function"
        && typeof restoreFh6TempDeletedInstance === "function"
        && typeof rebuildCurrentFh6MyDesignInstances === "function"
        && typeof placeFh6TempDeletedReview === "function"
        && Boolean(document.getElementById("fh6TempDeletedReview"))
        && Boolean(document.getElementById("fh6TempDeletedReviewGlobalHost"))
        && Boolean(document.getElementById("fh6TempDeletedReviewMyDesignHost"))
        && Boolean(document.getElementById("fh6TempDeletedModal")),
        `全ソート共通 / 一時非表示 ${{fh6TempDeletedInstanceIds.size}}件 / 現在実スロット ${{FH6_CURRENT_MY_DESIGN_INSTANCES.length}}件 / 位置再計算`],
      ["Navigator Bridge連携", typeof currentFh6NavigatorInstance === "function"
        && typeof launchFh6NavigatorForCurrent === "function"
        && typeof updateFh6NavigatorUi === "function"
        && typeof currentFh6InstanceForCard === "function"
        && typeof setFh6NavigatorTargetInstance === "function"
        && Boolean(document.getElementById("fh6NavigatorMove"))
        && Boolean(document.getElementById("fh6GlobalMoveButton"))
        && Boolean(document.getElementById("compareFh6Move"))
        && Boolean(document.getElementById("exactDuplicateFh6Move")),
        `全ソート・比較画面の#実スロット/#列U/Dから移動対象を選択 + 仮削除反映後の最終実スロット ${{FH6_CURRENT_MY_DESIGN_INSTANCES.length}}件 + navigatorbridgeforfh6:// で受け渡し`],
      ["Navigator Bridge移動設定", typeof currentFh6NavigatorSettings === "function"
        && typeof fh6NavigatorMovePlan === "function"
        && typeof placeFh6NavigatorSettings === "function"
        && Boolean(document.getElementById("fh6NavigatorSettings"))
        && Boolean(document.getElementById("fh6NavigatorSettingsGlobalHost"))
        && Boolean(document.getElementById("fh6NavigatorSettingsMyDesignHost"))
        && Boolean(document.getElementById("fh6NavigatorPlan"))
        && Boolean(document.getElementById("fh6NavigatorResetOrigin"))
        && Boolean(document.getElementById("fh6NavigatorResetEscDelay"))
        && Boolean(document.getElementById("fh6NavigatorResetRetDelay")),
        "全ソート共通でキー間隔 / FH6切替後 / 横→上下 / 左循環後 / 任意の#001Uリセット（ESC→RET）を設定・保存し、カーソル移動回数をプレビュー"],
      ["選択ペイント比較", typeof renderSelectedCompareModal === "function"
        && Boolean(document.getElementById("compareSelected"))
        && Boolean(document.getElementById("compareModalTitle")),
        "2件以上の任意選択を共通比較画面へ表示"],
      ["モーダルフォーカス管理", typeof getTopOpenModal === "function"
        && typeof modalFocusableElements === "function"
        && typeof trapModalTab === "function"
        && [...document.querySelectorAll(".modal")].every(modal => modal.getAttribute("aria-hidden") !== null
          && Boolean(modal.querySelector('[role="dialog"][aria-modal="true"]'))),
        "開く→内部へ移動 / Tab循環 / 閉じる→起点へ復帰"],
      ["共通UI更新経路", typeof refreshOrganizerUi === "function"
        && typeof refreshFilteredView === "function"
        && typeof refreshBackupUi === "function",
        "表示 + バックアップ + ソート + 車種ナビ + モバイル要約 + UI保存"],
      ["データ健全性診断", typeof collectReportDataIntegrity === "function"
        && typeof verifyThumbnailSources === "function",
        "カード / CSV / 車種 / 進捗 / サムネイル / マイデザイン番号 / FH6日付 / 再DL重複 / 実スロット"],
      ["利用準備表示", typeof updateStartupReadiness === "function"
        && typeof thumbnailDeliveryMode === "function"
        && Boolean(document.getElementById("startupReadinessPanel"))
        && Boolean(document.getElementById("runtimeDiagnosticsAction")),
        "保存方式 + データ整合 + サムネイル方式 + エラー時の診断導線"],
      ["保存方式", true, persistentStorage ? "ブラウザ保存" : "一時メモリ"]
    ];
    const okCount = checks.filter(x => x[1]).length;
    const issueLines = [...integrity.issues];
    thumbnailCheck.failed.slice(0, 20).forEach(item => issueLines.push(`サムネイル読込失敗: ${{item.key}}`));
    const issueDetail = issueLines.length
      ? `<details class="diagnostics-detail"><summary>問題の詳細（${{issueLines.length}}件${{issueLines.length >= 20 ? "・先頭のみ" : ""}}）</summary><ul class="diagnostics-issue-list">${{issueLines.slice(0,20).map(item => `<li><code>${{escapeDiagnosticHtml(item)}}</code></li>`).join("")}}</ul></details>`
      : `<div class="diagnostics-detail"><b>レポートデータ健全性:</b> 問題は見つかりませんでした。</div>`;
    diagnosticsBody.innerHTML = `
      <p><b>${{okCount}} / ${{checks.length}}</b> 項目正常</p>
      <div class="diagnostics-list">${{checks.map(([name,ok,detail]) =>
        `<div class="diagnostics-row"><span>${{name}}<br><small>${{detail}}</small></span><b class="${{ok?"diagnostics-ok":"diagnostics-ng"}}">${{ok?"OK":"NG"}}</b></div>`
      ).join("")}}</div>
      ${{issueDetail}}`;
    lastDiagnosticsStatus = {{ok:okCount === checks.length, okCount, total:checks.length}};
    updateStartupReadiness();
  }} catch (error) {{
    lastDiagnosticsStatus = {{ok:false, okCount:0, total:1}};
    try {{ updateStartupReadiness(); }} catch (_) {{}}
    if (diagnosticsBody) diagnosticsBody.innerHTML = `<div class="runtime-error">動作診断に失敗しました。\n${{escapeDiagnosticHtml(error?.message || error)}}</div>`;
  }} finally {{
    if (diagnosticsButton) diagnosticsButton.disabled = false;
  }}
}}
document.getElementById("selfDiagnostics").addEventListener("click", () => {{ void runSelfDiagnostics(); }});
document.getElementById("startupDiagnosticsAction")?.addEventListener("click", () => {{ void runSelfDiagnostics(); }});
document.getElementById("runtimeDiagnosticsAction")?.addEventListener("click", () => {{ void runSelfDiagnostics(); }});
document.getElementById("startupHelpAction")?.addEventListener("click", event => {{
  openHelpDialog("environment", event.currentTarget);
}});

document.getElementById("themeToggle").addEventListener("click",()=>{{document.body.classList.toggle("dark-theme");document.getElementById("themeToggle").textContent=document.body.classList.contains("dark-theme")?"ライトテーマ":"ダークテーマ";saveUiState();}});

let activeCompareMembers = [];
let activeCompareMode = "similar";
function escapeCompareHtml(value) {{
  return String(value ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[ch]));
}}
function compareDecisionLabel(card) {{
  return ({{undecided:"未決定", keep:"残す", delete:"削除候補"}})[getState(card)] || getState(card);
}}
function compareCreatorLabel(card) {{
  return String(card.dataset.creatorDisplay || card.dataset.creator || "").trim() || "—";
}}
function compareTitleLabel(card) {{
  return String(card.dataset.titleDisplay || "").trim() || REPORT_FALLBACK_TITLE;
}}
function updateCompareSelectionUi() {{
  const count = activeCompareMembers.filter(card => selectedKeys.has(card.dataset.key)).length;
  const countEl = document.getElementById("compareSelectionCount");
  if (countEl) countEl.textContent = `比較対象 ${{activeCompareMembers.length}}件中 ${{count}}件を選択中`;
  document.querySelectorAll("#compareGrid .compare-item").forEach(item => {{
    const selected = selectedKeys.has(item.dataset.compareKey || "");
    item.classList.toggle("is-selected", selected);
    const button = item.querySelector("[data-compare-toggle]");
    if (button) button.textContent = selected ? "選択解除" : "選択";
  }});
}}
function setCompareSelection(members, selected) {{
  members.forEach(card => {{
    if (selected) selectedKeys.add(card.dataset.key);
    else selectedKeys.delete(card.dataset.key);
  }});
  applyFilters();
  updateCompareSelectionUi();
}}
function renderCompareMembers(members, options = {{}}) {{
  activeCompareMembers = [...members];
  activeCompareMode = options.mode === "selected" ? "selected" : "similar";
  const title = document.getElementById("compareModalTitle");
  const grid = document.getElementById("compareGrid");
  const summary = document.getElementById("compareSummary");
  const olderButton = document.getElementById("compareSelectOlder");
  if (title) title.textContent = options.title || (activeCompareMode === "selected" ? "選択中のペイント比較" : "類似ペイント比較");
  if (summary) summary.textContent = options.summary || "";
  olderButton?.classList.toggle("hidden", activeCompareMode !== "similar");
  if (!grid) return;
  grid.innerHTML = "";
  activeCompareMembers.forEach((member,index) => {{
    const item=document.createElement("div");
    item.className="compare-item";
    item.dataset.compareKey = member.dataset.key;
    const img=member.querySelector("img.livery-image");
    const showAgeBadges = Boolean(options.showAgeBadges);
    const newest = showAgeBadges && index === 0 && activeCompareMembers.length > 1;
    const oldest = showAgeBadges && index === activeCompareMembers.length - 1 && activeCompareMembers.length > 1;
    const fingerprint = String(member.dataset.key || "");
    const description = String(member.dataset.description || "").trim() || "—";
    const vinyl = Number(member.dataset.vinylCount);
    const badgeLabel = String(options.badgeLabel || "").trim();
    const reasonBadge = badgeLabel ? `<span class="compare-badge reason">${{escapeCompareHtml(badgeLabel)}}</span>` : "";
    const relativeBadges = `${{newest?`<span class="compare-badge newest">${{REPORT_LABEL_NEWEST}}</span>`:""}}${{oldest?`<span class="compare-badge">${{REPORT_LABEL_OLDEST}}</span>`:""}}`;
    const badges = `${{reasonBadge}}${{relativeBadges}}`;
    const locationHtml = fh6LocationButtonsHtml(member);
    item.innerHTML=`
      ${{img?`<img loading="lazy" decoding="async" src="${{escapeCompareHtml(img.getAttribute("src")||"")}}" alt="">`:""}}
      ${{badges ? `<div class="compare-badges">${{badges}}</div>` : ""}}
      ${{locationHtml}}
      <b class="compare-vehicle-user-data">${{escapeCompareHtml(member.querySelector(".vehicle")?.textContent || "")}}</b>
      <div class="compare-title-user-data">${{escapeCompareHtml(compareTitleLabel(member))}}</div>
      <p class="compare-description compare-user-data">${{escapeCompareHtml(description)}}</p>
      <dl class="compare-meta">
        <dt>作成者</dt><dd class="compare-user-data">${{escapeCompareHtml(compareCreatorLabel(member))}}</dd>
        <dt>取得日時</dt><dd>${{escapeCompareHtml(member.dataset.timestampDisplay || member.dataset.timestamp || "—")}}</dd>
        <dt>バイナル数</dt><dd>${{vinyl>=0?vinyl.toLocaleString(REPORT_LOCALE):"—"}}</dd>
        <dt>整理状態</dt><dd>${{escapeCompareHtml(compareDecisionLabel(member))}}</dd>
        <dt>Fingerprint</dt><dd><code title="${{escapeCompareHtml(fingerprint)}}">${{escapeCompareHtml(fingerprint.slice(0,16))}}</code></dd>
      </dl>
      <div class="compare-item-actions">
        <button type="button" data-compare-toggle="${{escapeCompareHtml(member.dataset.key)}}">${{selectedKeys.has(member.dataset.key)?"選択解除":"選択"}}</button>
      </div>`;
    grid.appendChild(item);
  }});
  grid.querySelectorAll("[data-compare-toggle]").forEach(button => button.addEventListener("click", () => {{
    const member = cards.find(card => card.dataset.key === button.dataset.compareToggle);
    if (!member) return;
    if (selectedKeys.has(member.dataset.key)) selectedKeys.delete(member.dataset.key);
    else selectedKeys.add(member.dataset.key);
    applyFilters();
    updateCompareSelectionUi();
  }}));
  updateCompareSelectionUi();
  updateFh6NavigatorUi();
}}
function renderCompareModal(sourceCard) {{
  const group = sourceCard?.dataset.similarGroup || "";
  const reason = sourceCard?.dataset.similarReason || "類似条件一致";
  const members = cards
    .filter(card => card.dataset.similarGroup === group)
    .sort((a,b) => String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || "")) || String(a.dataset.key).localeCompare(String(b.dataset.key)));
  renderCompareMembers(members, {{
    mode:"similar",
    title:"類似ペイント比較",
    summary:`${{reason}} / ${{members.length}}件。新しい取得日時から順に表示しています。`,
    badgeLabel:reason,
    showAgeBadges:true,
  }});
}}
function renderSelectedCompareModal() {{
  const members = cards
    .filter(card => selectedKeys.has(card.dataset.key))
    .sort((a,b) => String(b.dataset.timestamp || "").localeCompare(String(a.dataset.timestamp || "")) || String(a.dataset.key).localeCompare(String(b.dataset.key)));
  if (members.length < 2) {{
    alert("比較するペイントを2件以上選択してください。");
    return false;
  }}
  renderCompareMembers(members, {{
    mode:"selected",
    title:"選択中のペイント比較",
    summary:`選択中の${{members.length}}件を取得日時の新しい順で比較しています。`,
    badgeLabel:"選択中",
    showAgeBadges:false,
  }});
  return true;
}}

let activeExactDuplicateGroup = "";

function exactDuplicateGroupEntries() {{
  const groups = new Map();
  cards.forEach(card => {{
    if (card.dataset.exactDuplicate !== "1") return;
    const group = String(card.dataset.exactDuplicateGroup || "");
    if (!group) return;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(card);
  }});
  return [...groups.entries()]
    .map(([group, members]) => [group, members.sort((a,b) =>
      Number(fh6LocationForCard(a)?.slotNumber || Number.MAX_SAFE_INTEGER) - Number(fh6LocationForCard(b)?.slotNumber || Number.MAX_SAFE_INTEGER)
      || String(a.dataset.key || "").localeCompare(String(b.dataset.key || ""))
    )])
    .sort((a,b) =>
      Number(fh6LocationForCard(a[1][0])?.slotNumber || Number.MAX_SAFE_INTEGER) - Number(fh6LocationForCard(b[1][0])?.slotNumber || Number.MAX_SAFE_INTEGER)
      || a[0].localeCompare(b[0])
    );
}}

function renderExactDuplicateModal(groupId) {{
  const entries = exactDuplicateGroupEntries();
  if (!entries.length) return false;
  let index = entries.findIndex(([group]) => group === groupId);
  if (index < 0) index = 0;
  const [group, members] = entries[index];
  activeExactDuplicateGroup = group;
  const grid = document.getElementById("exactDuplicateGrid");
  const summary = document.getElementById("exactDuplicateSummary");
  const position = document.getElementById("exactDuplicateGroupPosition");
  if (summary) summary.textContent = `${{members.length}}件の完全一致スロット / 余分 ${{Math.max(0, members.length - 1)}}件。残す1件を選択してください。`;
  if (position) position.textContent = `${{index + 1}} / ${{entries.length}}組`;
  if (!grid) return true;
  grid.innerHTML = "";
  members.forEach(member => {{
    const item = document.createElement("div");
    item.className = "compare-item exact-duplicate-item";
    item.dataset.exactDuplicateKey = member.dataset.key || "";
    const img = member.querySelector("img.livery-image");
    const state = getState(member);
    item.classList.toggle("is-keeper", state === "keep");
    const locationHtml = fh6LocationButtonsHtml(member);
    const vinyl = Number(member.dataset.vinylCount);
    item.innerHTML = `
      ${{img ? `<img loading="lazy" decoding="async" src="${{escapeCompareHtml(img.getAttribute("src") || "")}}" alt="">` : ""}}
      <div class="compare-badges"><span class="compare-badge">${{escapeCompareHtml(compareDecisionLabel(member))}}</span></div>
      ${{locationHtml}}
      <b class="compare-vehicle-user-data">${{escapeCompareHtml(member.querySelector(".vehicle")?.textContent || member.dataset.vehicle || "")}}</b>
      <div class="compare-title-user-data">${{escapeCompareHtml(compareTitleLabel(member))}}</div>
      <dl class="compare-meta">
        <dt>作成者</dt><dd class="compare-user-data">${{escapeCompareHtml(compareCreatorLabel(member))}}</dd>
        <dt>FH6表示日付</dt><dd>${{escapeCompareHtml(member.dataset.fh6DateDisplay || "—")}}</dd>
        <dt>取得日時</dt><dd>${{escapeCompareHtml(member.dataset.timestampDisplay || member.dataset.timestamp || "—")}}</dd>
        <dt>バイナル数</dt><dd>${{vinyl >= 0 ? vinyl.toLocaleString(REPORT_LOCALE) : "—"}}</dd>
        <dt>Livery ID</dt><dd><code>${{escapeCompareHtml(member.dataset.liveryId || "—")}}</code></dd>
      </dl>
      <div class="compare-item-actions">
        <button class="keeper-action" type="button" data-exact-duplicate-keeper="${{escapeCompareHtml(member.dataset.key || "")}}">${{state === "keep" ? "この1件を残しています" : "これを残す"}}</button>
      </div>`;
    grid.appendChild(item);
  }});
  grid.querySelectorAll("[data-exact-duplicate-keeper]").forEach(button => button.addEventListener("click", () => {{
    chooseExactDuplicateKeeper(button.dataset.exactDuplicateKeeper || "");
  }}));
  updateFh6NavigatorUi();
  return true;
}}

function chooseExactDuplicateKeeper(keeperKey) {{
  const members = cards.filter(card => card.dataset.exactDuplicateGroup === activeExactDuplicateGroup);
  const keeper = members.find(card => card.dataset.key === keeperKey);
  if (!keeper || members.length < 2) return;
  const items = [];
  members.forEach(card => {{
    const desired = card === keeper ? "keep" : "delete";
    const previous = getState(card);
    if (previous !== desired) items.push({{type:"state", key:card.dataset.key, previous}});
    if (desired === "undecided") storageRemove(stateKey(card));
    else storageSet(stateKey(card), desired);
    paintState(card);
  }});
  if (items.length) {{
    pushUndo({{type:"bulk", items, label:`再DL重複 ${{members.length}}件: 残す1件を選択`}});
  }}
  refreshOrganizerUi({{persist:true}});
  renderExactDuplicateModal(activeExactDuplicateGroup);
}}

function moveExactDuplicateGroup(direction = 1) {{
  const entries = exactDuplicateGroupEntries();
  if (!entries.length) return;
  let index = entries.findIndex(([group]) => group === activeExactDuplicateGroup);
  if (index < 0) index = 0;
  const next = (index + (direction < 0 ? -1 : 1) + entries.length) % entries.length;
  renderExactDuplicateModal(entries[next][0]);
}}

// =======================================================================
// v0.4.58-r12 — FH6移動対象番号をトグル操作に統一
// =======================================================================
// 選択中の #実スロット / #列U/D をもう一度クリックすると解除します。
// r12 rev2では専用の「選択解除」ボタンを廃止し、レイアウトを動かさないトグル操作へ一本化します。
document.addEventListener("click", event => {{
  const trigger = event.target?.closest?.(".fh6-move-target-trigger, .fh6-location-button");
  if (!trigger) return;
  event.preventDefault();
  event.stopPropagation();
  const explicitId = String(trigger.dataset.fh6MoveTargetInstance || "");
  const instance = explicitId
    ? FH6_CURRENT_MY_DESIGN_INSTANCES.find(item => String(item.instance_id || "") === explicitId)
    : currentFh6InstanceForCard(trigger.closest(".card"));
  if (!instance) return;
  if (String(instance.instance_id || "") === fh6NavigatorTargetInstanceId) {{
    clearFh6NavigatorTarget();
    return;
  }}
  setFh6NavigatorTargetInstance(instance);
}});

document.getElementById("fh6GlobalMoveButton")?.addEventListener("click", () => launchFh6NavigatorForCurrent());
document.getElementById("compareFh6Move")?.addEventListener("click", () => {{
  if (compareModalContainsFh6Target()) launchFh6NavigatorForCurrent();
}});
document.getElementById("exactDuplicateFh6Move")?.addEventListener("click", () => {{
  if (exactDuplicateModalContainsFh6Target()) launchFh6NavigatorForCurrent();
}});

document.querySelectorAll(".open-exact-duplicate").forEach(btn => btn.addEventListener("click", event => {{
  event.preventDefault();
  event.stopPropagation();
  const card = btn.closest(".card");
  if (!card || !renderExactDuplicateModal(card.dataset.exactDuplicateGroup || "")) return;
  openModal("exactDuplicateModal", btn);
}}));
document.getElementById("exactDuplicatePrev")?.addEventListener("click", () => moveExactDuplicateGroup(-1));
document.getElementById("exactDuplicateNext")?.addEventListener("click", () => moveExactDuplicateGroup(1));

document.querySelectorAll(".compare-similar").forEach(btn=>btn.addEventListener("click",e=>{{
  e.preventDefault();e.stopPropagation();
  const card=btn.closest(".card");
  renderCompareModal(card);
  openModal("compareModal");
}}));

document.getElementById("compareSelected")?.addEventListener("click", () => {{
  if (renderSelectedCompareModal()) openModal("compareModal");
}});

document.getElementById("compareSelectAll")?.addEventListener("click", () => setCompareSelection(activeCompareMembers, true));
document.getElementById("compareClearSelection")?.addEventListener("click", () => setCompareSelection(activeCompareMembers, false));
document.getElementById("compareSelectOlder")?.addEventListener("click", () => {{
  if (activeCompareMode !== "similar" || activeCompareMembers.length < 2) return;
  // メンバーは新しい順です。比較グループ外の選択状態は維持しつつ、古い候補をすべて選択します。
  activeCompareMembers.forEach((card,index) => {{
    if (index === 0) selectedKeys.delete(card.dataset.key);
    else selectedKeys.add(card.dataset.key);
  }});
  applyFilters();
  updateCompareSelectionUi();
}});

function openDetail(kind,value) {{
  const matches=cards.filter(card=>kind==="creator"?card.dataset.creator===value:card.dataset.car===value);
  document.getElementById("detailTitle").textContent=kind==="creator"?`作成者: ${{value}}`:`Car ID ${{value}}`;
  const vals=matches.map(c=>Number(c.dataset.vinylCount)).filter(v=>v>=0);
  const avg=vals.length?Math.round(vals.reduce((a,b)=>a+b,0)/vals.length):null;
  document.getElementById("detailBody").innerHTML=`<p>ペイント数: <b>${{matches.length}}</b>${{avg!==null?` / 平均バイナル数: <b>${{avg.toLocaleString(REPORT_LOCALE)}}</b>`:""}}</p><div class="detail-list">${{matches.map(c=>`<div class="detail-item"><b>${{c.querySelector(".vehicle")?.textContent||""}}</b><br>${{c.querySelector("h4")?.textContent||""}}<br>バイナル数: ${{Number(c.dataset.vinylCount)>=0?Number(c.dataset.vinylCount).toLocaleString(REPORT_LOCALE):"—"}}</div>`).join("")}}</div>`;
  openModal("detailModal");
}}
document.querySelectorAll("[data-filter-type='creator']").forEach(el=>el.addEventListener("dblclick",e=>{{e.preventDefault();e.stopPropagation();openDetail("creator",el.dataset.filterValue||"");}}));
document.querySelectorAll("[data-filter-type='car']").forEach(el=>el.addEventListener("dblclick",e=>{{e.preventDefault();e.stopPropagation();openDetail("car",el.dataset.filterValue||"");}}));

function scanDiffCardHtml(card) {{
  const vehicle = escapeDiagnosticHtml(card.querySelector(".vehicle")?.textContent || card.dataset.vehicle || "");
  const title = escapeDiagnosticHtml(card.dataset.titleDisplay || card.dataset.title || "");
  const creator = escapeDiagnosticHtml(card.dataset.creatorDisplay || card.dataset.creator || "—");
  const acquired = escapeDiagnosticHtml(card.dataset.timestampDisplay || "");
  return `<div class="detail-item"><b>${{vehicle || REPORT_FALLBACK_UNKNOWN_VEHICLE}}</b><br>${{title || REPORT_FALLBACK_NO_TITLE}}<br><span class="small">${{creator}}${{acquired ? ` / ${{acquired}}` : ""}}</span></div>`;
}}

function scanDiffRemovedHtml(entry) {{
  const vehicle = escapeDiagnosticHtml(entry?.vehicle || "");
  const title = escapeDiagnosticHtml(entry?.title || "");
  const creator = escapeDiagnosticHtml(entry?.creator || "—");
  const acquired = escapeDiagnosticHtml(entry?.timestampDisplay || "");
  return `<div class="detail-item"><b>${{vehicle || REPORT_FALLBACK_UNKNOWN_VEHICLE}}</b><br>${{title || REPORT_FALLBACK_NO_TITLE}}<br><span class="small">${{creator}}${{acquired ? ` / ${{acquired}}` : ""}}</span></div>`;
}}

function renderScanDiffModal() {{
  const body = document.getElementById("removedBody");
  if (!body) return;
  const baselineState = loadScanBaseline();
  if (!baselineState) {{
    body.innerHTML = `<p>新規判定基準がまだ設定されていません。</p><p class="small">「今回を新規判定の基準にする」を押すと、次回以降のレポートで新規 / 消滅を比較できます。</p>`;
    return;
  }}

  const added = cards
    .filter(card => card.dataset.isNew === "1")
    .sort((a,b) => Number(a.dataset.myDesignIndex || 0) - Number(b.dataset.myDesignIndex || 0));
  const removed = [...(window.__fh6RemovedEntries || [])]
    .sort((a,b) => Number(a?.car || 0) - Number(b?.car || 0) || String(a?.timestamp || "").localeCompare(String(b?.timestamp || "")));

  const addedItems = added.length
    ? `<div class="detail-list">${{added.map(scanDiffCardHtml).join("")}}</div>`
    : `<p class="small">新規ペイントはありません。</p>`;
  const removedItems = removed.length
    ? `<div class="detail-list">${{removed.map(scanDiffRemovedHtml).join("")}}</div>`
    : `<p class="small">基準から消えたペイントはありません。</p>`;

  body.innerHTML = `
    <p><b>新規 ${{added.length}}件</b> / <b>消滅 ${{removed.length}}件</b></p>
    <section><h4>新規</h4>${{addedItems}}</section>
    <section style="margin-top:16px"><h4>消滅</h4>${{removedItems}}</section>`;
}}

document.getElementById("showRemoved")?.addEventListener("click",()=>{{
  renderScanDiffModal();
  openModal("removedModal");
}});
document.getElementById("fh6TempDeletedReview")?.addEventListener("click", event => {{
  renderFh6TempDeletedModal();
  openModal("fh6TempDeletedModal", event.currentTarget);
}});
document.getElementById("fh6TempDeletedRestoreAll")?.addEventListener("click", () => {{
  if (!fh6TempDeletedInstanceIds.size) return;
  if (!confirm(`FH6削除済み（仮） ${{fh6TempDeletedInstanceIds.size}}件をすべて元に戻しますか？`)) return;
  restoreAllFh6TempDeletedInstances();
}});

document.querySelectorAll("[data-close-modal]").forEach(btn=>btn.addEventListener("click",()=>closeModal(btn.dataset.closeModal)));

function focusKeyboardCard(card, smooth = true) {{
  document.querySelectorAll(".card.keyboard-active").forEach(item => item.classList.remove("keyboard-active"));
  if (!card) {{
    updateVehicleNavigationUi();
    updateFh6NavigatorUi();
    return;
  }}
  card.classList.add("keyboard-active");
  updateVehicleNavigationUi();
  updateFh6NavigatorUi();
  card.scrollIntoView({{behavior:smooth ? "smooth" : "auto", block:"center"}});
}}
function findNextVisibleUndecided(fromCard = null) {{
  const visible = cardsInCurrentDisplayOrder();
  if (!visible.length) return null;
  const start = fromCard ? visible.indexOf(fromCard) : -1;
  for (let step = 1; step <= visible.length; step++) {{
    const candidate = visible[(Math.max(-1, start) + step) % visible.length];
    if (candidate !== fromCard && getState(candidate) === "undecided") return candidate;
  }}
  if (!fromCard && getState(visible[0]) === "undecided") return visible[0];
  return null;
}}
function goToNextUndecided(fromCard = null, silent = false) {{
  const next = findNextVisibleUndecided(fromCard);
  if (!next) {{
    if (!silent) alert("現在の表示条件に、移動できる未決定ペイントはありません。");
    return null;
  }}
  focusKeyboardCard(next);
  return next;
}}
function visibleUnfinishedVehicleTarget(sequence, carId) {{
  const visibleMembers = sequence.visibleByVehicle.get(String(carId || "")) || [];
  return visibleMembers.find(card => getState(card) === "undecided")
    || sequence.firstVisibleByVehicle.get(String(carId || ""))
    || null;
}}
function findFirstVisibleUnfinishedVehicle() {{
  const sequence = visibleVehicleSequence();
  for (const carId of sequence.vehicleOrder) {{
    if (vehicleProgressInfo(carId).state === "complete") continue;
    const target = visibleUnfinishedVehicleTarget(sequence, carId);
    if (target) return target;
  }}
  return null;
}}
function findAdjacentVisibleUnfinishedVehicle(direction = 1, fromCard = null) {{
  const sequence = visibleVehicleSequence();
  const {{vehicleOrder}} = sequence;
  if (!vehicleOrder.length) return null;
  const delta = Number(direction) < 0 ? -1 : 1;
  const fromCarId = String(fromCard?.dataset?.car || "");
  const start = fromCarId ? vehicleOrder.indexOf(fromCarId) : -1;

  if (start < 0) {{
    const scanOrder = delta > 0 ? vehicleOrder : [...vehicleOrder].reverse();
    for (const carId of scanOrder) {{
      if (vehicleProgressInfo(carId).state === "complete") continue;
      const target = visibleUnfinishedVehicleTarget(sequence, carId);
      if (target) return target;
    }}
    return null;
  }}

  for (let step = 1; step <= vehicleOrder.length; step++) {{
    const index = (start + (delta * step) + vehicleOrder.length) % vehicleOrder.length;
    const carId = vehicleOrder[index];
    if (carId === fromCarId || vehicleProgressInfo(carId).state === "complete") continue;
    const target = visibleUnfinishedVehicleTarget(sequence, carId);
    if (target) return target;
  }}
  return null;
}}
function findPreviousVisibleUnfinishedVehicle(fromCard = null) {{
  return findAdjacentVisibleUnfinishedVehicle(-1, fromCard);
}}
function findNextVisibleUnfinishedVehicle(fromCard = null) {{
  return findAdjacentVisibleUnfinishedVehicle(1, fromCard);
}}
function goToFirstUnfinishedVehicle() {{
  const target = findFirstVisibleUnfinishedVehicle();
  if (!target) {{
    alert("現在の表示条件に、移動できる未完了車種はありません。");
    return null;
  }}
  focusKeyboardCard(target);
  return target;
}}
function goToPreviousUnfinishedVehicle(fromCard = null) {{
  const target = findPreviousVisibleUnfinishedVehicle(fromCard);
  if (!target) {{
    alert("現在の表示条件に、前へ移動できる未完了車種はありません。");
    return null;
  }}
  focusKeyboardCard(target);
  return target;
}}
function goToNextUnfinishedVehicle(fromCard = null) {{
  const target = findNextVisibleUnfinishedVehicle(fromCard);
  if (!target) {{
    alert("現在の表示条件に、次へ移動できる未完了車種はありません。");
    return null;
  }}
  focusKeyboardCard(target);
  return target;
}}
function updateSequentialReviewUi() {{
  const button = document.getElementById("sequentialModeToggle");
  if (!button) return;
  button.textContent = sequentialReviewMode ? "連続整理: ON" : "連続整理: OFF";
  button.classList.toggle("active", sequentialReviewMode);
  button.setAttribute("aria-pressed", sequentialReviewMode ? "true" : "false");
}}
document.getElementById("nextUndecided")?.addEventListener("click", () => {{
  goToNextUndecided(document.querySelector(".card.keyboard-active"));
}});
document.querySelectorAll("[data-first-unfinished-vehicle]").forEach(button => {{
  button.addEventListener("click", () => goToFirstUnfinishedVehicle());
}});
document.querySelectorAll("[data-previous-unfinished-vehicle]").forEach(button => {{
  button.addEventListener("click", () => {{
    goToPreviousUnfinishedVehicle(document.querySelector(".card.keyboard-active"));
  }});
}});
document.querySelectorAll("[data-next-unfinished-vehicle]").forEach(button => {{
  button.addEventListener("click", () => {{
    goToNextUnfinishedVehicle(document.querySelector(".card.keyboard-active"));
  }});
}});
document.getElementById("sequentialModeToggle")?.addEventListener("click", () => {{
  sequentialReviewMode = !sequentialReviewMode;
  updateSequentialReviewUi();
  saveUiState();
}});

// v0.4.58-r14 — 検索 / ヘルプへすぐ移動するキーボードショートカット
document.addEventListener("keydown",event=>{{
  if (getTopOpenModal() || document.getElementById("lightbox")?.classList.contains("open")) return;
  const activeTag = document.activeElement?.tagName;
  if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "/"
      && !["INPUT","TEXTAREA","SELECT"].includes(activeTag)) {{
    q.focus();
    q.select();
    event.preventDefault();
    return;
  }}
  if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "?"
      && !["INPUT","TEXTAREA","SELECT"].includes(activeTag)) {{
    openHelpDialog(activeHelpTab);
    event.preventDefault();
    return;
  }}
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && event.shiftKey) {{
    event.preventDefault(); redoLast(); return;
  }}
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {{
    event.preventDefault(); redoLast(); return;
  }}
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {{
    event.preventDefault(); undoLast(); return;
  }}
  if (["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName)) return;
  if (sortOrder.value === "fh6-my-designs"
      && !event.ctrlKey && !event.metaKey && !event.altKey
      && event.key.toLowerCase() === "j") {{
    const jumpInput = document.getElementById("fh6MyDesignJumpInput");
    if (jumpInput) {{
      jumpInput.focus();
      jumpInput.select();
      renderFh6VehicleSuggestions();
      event.preventDefault();
    }}
    return;
  }}
  if (sortOrder.value === "fh6-my-designs"
      && event.shiftKey
      && ["ArrowLeft","ArrowRight"].includes(event.key)
      && fh6VehicleMatchSlotNumbers.length) {{
    moveFh6VehicleMatch(event.key === "ArrowLeft" ? -1 : 1);
    event.preventDefault();
    return;
  }}
  if (sortOrder.value === "fh6-my-designs" && ["ArrowLeft","ArrowRight"].includes(event.key)) {{
    moveFh6MyDesignColumn(event.key === "ArrowLeft" ? -1 : 1);
    event.preventDefault();
    return;
  }}
  const visible=cardsInCurrentDisplayOrder(); if(!visible.length)return;
  let active=document.querySelector(".card.keyboard-active"); let index=visible.indexOf(active);
  const key=event.key.toLowerCase();
  if(key==="v"){{
    if (event.shiftKey) goToPreviousUnfinishedVehicle(index >= 0 ? active : null);
    else goToNextUnfinishedVehicle(index >= 0 ? active : null);
    event.preventDefault();
    return;
  }}
  if(index<0){{index=0;active=visible[0];focusKeyboardCard(active,false);}}
  if(["ArrowRight","ArrowDown"].includes(event.key)){{index=Math.min(visible.length-1,index+1);focusKeyboardCard(visible[index]);event.preventDefault();return;}}
  if(["ArrowLeft","ArrowUp"].includes(event.key)){{index=Math.max(0,index-1);focusKeyboardCard(visible[index]);event.preventDefault();return;}}
  const target=visible[index];
  if(key==="n"){{goToNextUndecided(target);event.preventDefault();return;}}
  if(key==="k" || key==="d"){{
    const next = sequentialReviewMode ? findNextVisibleUndecided(target) : null;
    setState(target, key==="k" ? "keep" : "delete");
    if (next) focusKeyboardCard(next);
    event.preventDefault();
    return;
  }}
  if(key==="u"){{setState(target,"undecided");event.preventDefault();return;}}
  if(event.key===" "){{if(selectedKeys.has(target.dataset.key))selectedKeys.delete(target.dataset.key);else selectedKeys.add(target.dataset.key);updateSelectionUi();event.preventDefault();}}
}});

document.getElementById("fh6MyDesignJump")?.addEventListener("click", () => jumpToFh6MyDesignTarget());
document.getElementById("fh6NavigatorMove")?.addEventListener("click", () => launchFh6NavigatorForCurrent());
["fh6NavigatorInterval","fh6NavigatorSwitchDelay","fh6NavigatorTurnDelay","fh6NavigatorWrapDelay","fh6NavigatorResetEscDelay","fh6NavigatorResetRetDelay"].forEach(id => {{
  const control = document.getElementById(id);
  control?.addEventListener("change", () => saveFh6NavigatorSettings());
  control?.addEventListener("input", () => updateFh6NavigatorUi());
}});
document.getElementById("fh6NavigatorResetOrigin")?.addEventListener("change", () => {{
  updateFh6NavigatorResetControls();
  saveFh6NavigatorSettings();
}});
document.getElementById("fh6NavigatorSettingsSync")?.addEventListener("click", () => syncFh6NavigatorSettingsToBridge());
document.getElementById("fh6NavigatorSettingsReset")?.addEventListener("click", () => resetFh6NavigatorSettings());
const fh6MyDesignJumpInput = document.getElementById("fh6MyDesignJumpInput");
fh6MyDesignJumpInput?.addEventListener("input", () => {{
  clearFh6VehicleMatchSelection();
  setFh6MyDesignJumpStatus("");
  renderFh6VehicleSuggestions();
}});
fh6MyDesignJumpInput?.addEventListener("focus", () => renderFh6VehicleSuggestions());
fh6MyDesignJumpInput?.addEventListener("keydown", event => {{
  if (event.key === "Escape") {{
    hideFh6VehicleSuggestions();
    event.currentTarget.blur();
    event.preventDefault();
    return;
  }}
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {{
    let buttons = fh6VehicleSuggestionButtons();
    if (!buttons.length) {{
      renderFh6VehicleSuggestions();
      buttons = fh6VehicleSuggestionButtons();
    }}
    if (buttons.length) {{
      const nextIndex = fh6VehicleSuggestionIndex < 0
        ? (event.key === "ArrowDown" ? 0 : buttons.length - 1)
        : fh6VehicleSuggestionIndex + (event.key === "ArrowDown" ? 1 : -1);
      setFh6VehicleSuggestionIndex(nextIndex);
      event.preventDefault();
    }}
    return;
  }}
  if (event.key !== "Enter") return;
  event.preventDefault();
  jumpToFh6MyDesignTarget();
}});
document.getElementById("fh6VehicleMatchPrev")?.addEventListener("click", () => moveFh6VehicleMatch(-1));
document.getElementById("fh6VehicleMatchNext")?.addEventListener("click", () => moveFh6VehicleMatch(1));
document.addEventListener("click", event => {{
  if (!event.target?.closest?.(".fh6-my-design-jump")) hideFh6VehicleSuggestions();
}});
document.getElementById("fh6MyDesignPrev")?.addEventListener("click", () => moveFh6MyDesignColumn(-1));
document.getElementById("fh6MyDesignNext")?.addEventListener("click", () => moveFh6MyDesignColumn(1));
const fh6MyDesignViewport = document.getElementById("fh6MyDesignViewport");
fh6MyDesignViewport?.addEventListener("scroll", () => {{
  clearTimeout(fh6MyDesignScrollTimer);
  fh6MyDesignScrollTimer = setTimeout(() => updateFh6MyDesignPositionUi(), 140);
}});
window.addEventListener("resize", () => {{
  if (sortOrder.value !== "fh6-my-designs") return;
  updateFh6MyDesignTailSpace();
  requestAnimationFrame(() => fitAllFh6MyDesignTitles());
  const columns = fh6MyDesignVisibleColumns();
  const current = columns.find(column => Number(column.dataset.fh6Column || 0) === fh6MyDesignCurrentColumn);
  if (current) scrollToFh6MyDesignColumn(current, "auto");
}});
const fh6MyDesignSection = document.getElementById("fh6MyDesignSection");
fh6MyDesignSection?.addEventListener("wheel", event => {{
  if (sortOrder.value !== "fh6-my-designs") return;

  // 横方向のホイール / トラックパッド操作はブラウザ本来の横スクロールへ任せます。
  // 通常のマウスホイールなど縦方向の入力だけを、FH6表示の1列移動へ変換します。
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX) || Math.abs(event.deltaY) < 0.01) return;
  event.preventDefault();

  let delta = event.deltaY;
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) delta *= 40;
  else if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) delta *= Math.max(240, fh6MyDesignViewport?.clientWidth || 800);

  fh6MyDesignWheelAccumulator += delta;
  clearTimeout(fh6MyDesignWheelResetTimer);
  fh6MyDesignWheelResetTimer = setTimeout(() => {{
    fh6MyDesignWheelAccumulator = 0;
    fh6MyDesignWheelLocked = false;
  }}, 180);

  // 高解像度ホイールやタッチパッドの細かなdeltaを少し蓄積してから1列進めます。
  // 1回のノッチが大きい一般的なマウスでは即座に反応します。
  const threshold = 24;
  if (fh6MyDesignWheelLocked || Math.abs(fh6MyDesignWheelAccumulator) < threshold) return;

  const direction = fh6MyDesignWheelAccumulator < 0 ? -1 : 1;
  fh6MyDesignWheelAccumulator = 0;
  fh6MyDesignWheelLocked = true;
  moveFh6MyDesignColumn(direction);

  // 1回のホイール操作で複数列を飛ばしにくくしつつ、連続回転には追従します。
  setTimeout(() => {{
    fh6MyDesignWheelLocked = false;
  }}, 110);
}}, {{passive:false, capture:true}});

// v0.4.58-r15 — 900～1000件でも検索入力を滑らかに保つため、
// 入力中は表示結果を先に更新し、負荷の高い候補件数再集計とlocalStorage保存は
// 入力が少し止まってから追従させます。検索結果・絞り込み条件そのものは従来と同じです。
let liveSearchRefreshTimer = 0;
let liveSearchSecondaryTimer = 0;
const LIVE_SEARCH_REFRESH_DELAY_MS = 70;
const LIVE_SEARCH_SECONDARY_DELAY_MS = 240;

function flushLiveSearchSecondaryRefresh() {{
  clearTimeout(liveSearchSecondaryTimer);
  liveSearchSecondaryTimer = 0;
  updateDynamicFilterCounts();
  // 検索で表示対象が変わるため、車種ナビゲーションだけは入力停止後に追従させます。
  // 並び替え、バックアップ、整理進捗、選択状態の全再計算は行いません。
  updateVehicleNavigationUi();
  saveUiState();
}}

function scheduleLiveSearchRefresh() {{
  clearTimeout(liveSearchRefreshTimer);
  clearTimeout(liveSearchSecondaryTimer);
  liveSearchRefreshTimer = setTimeout(() => {{
    liveSearchRefreshTimer = 0;
    refreshLiveSearchView();
  }}, LIVE_SEARCH_REFRESH_DELAY_MS);
  liveSearchSecondaryTimer = setTimeout(flushLiveSearchSecondaryRefresh, LIVE_SEARCH_SECONDARY_DELAY_MS);
}}

q.addEventListener("input", scheduleLiveSearchRefresh);
q.addEventListener("keydown", event => {{
  if (event.key !== "Escape") return;
  if (q.value) {{
    q.value = "";
    clearTimeout(liveSearchRefreshTimer);
    clearTimeout(liveSearchSecondaryTimer);
    applyAndPersist();
  }}
  q.blur();
  event.preventDefault();
  event.stopPropagation();
}});
multiFilterSelects.forEach(select => select.addEventListener("change", () => {{
  normalizeNativeMultiSelection(select);
  applyAndPersist();
  if (detailFilterSelects.includes(select)) renderDetailFilterChoices(select);
}}));
sortOrder.addEventListener("change", applyAndPersist);

document.getElementById("clearFilters").addEventListener("click", () => {{
  q.value = "";
  multiFilterSelects.forEach(select => setFilterValues(select, []));
  setFilterValues(vinylCountFilter, []);
  if (vinylMinInput) vinylMinInput.value = "";
  if (vinylMaxInput) vinylMaxInput.value = "";
  tagMatchMode = "or";
  updateTagModeUi();
  similarOnlyMode = false;
  similarKindMode = "all";
  exactDuplicateOnlyMode = false;
  newOnlyMode = false;
  favoriteOnlyMode = false;
  reviewOnlyMode = false;
  selectedOnlyMode = false;
  updateSimilarityFilterUi();
  document.getElementById("newOnly").classList.remove("active");
  document.getElementById("favoriteOnly").classList.remove("active");
  document.getElementById("reviewOnly").classList.remove("active");
  document.getElementById("selectedOnly").classList.remove("active");
  applyAndPersist();
}});

const COMPACT_FIELD_NAMES = [
  "selection", "fh6", "make-year", "asset", "description",
  "acquired", "vinyl", "personal", "flags"
];
const DEFAULT_COMPACT_FIELDS = [];

function normalizeCompactFields(value) {{
  if (!Array.isArray(value)) return [...DEFAULT_COMPACT_FIELDS];
  return value.filter(name => COMPACT_FIELD_NAMES.includes(String(name)));
}}

function selectedCompactFields() {{
  return [...document.querySelectorAll("[data-compact-field]")]
    .filter(input => input.checked)
    .map(input => input.dataset.compactField)
    .filter(name => COMPACT_FIELD_NAMES.includes(name));
}}

function applyCompactFields(value) {{
  const selected = new Set(normalizeCompactFields(value));
  COMPACT_FIELD_NAMES.forEach(name => {{
    document.body.classList.toggle(`compact-show-${{name}}`, selected.has(name));
  }});
  document.querySelectorAll("[data-compact-field]").forEach(input => {{
    input.checked = selected.has(input.dataset.compactField);
  }});
}}

document.querySelectorAll("[data-compact-field]").forEach(input => {{
  input.addEventListener("change", () => {{
    applyCompactFields(selectedCompactFields());
    saveUiState();
  }});
}});

document.getElementById("compactToggle").addEventListener("click", () => {{
  document.body.classList.toggle("compact");
  document.getElementById("compactToggle").textContent =
    document.body.classList.contains("compact") ? "通常表示" : "コンパクト表示";
  saveUiState();
}});

document.getElementById("resetStates").addEventListener("click", () => {{
  if (!confirm("このレポートの「残す / 削除候補」の判定状態をすべて消去しますか？\\nタグ・メモ・お気に入り・後で確認は消去しません。")) return;
  cards.forEach(card => storageRemove(stateKey(card)));
  cards.forEach(paintState);
  applyFilters();
}});



function buildDecisionBackupData() {{
  const decisions = {{}};
  cards.forEach(card => {{
    const state = getState(card);
    if (state !== "undecided") decisions[card.dataset.key] = state;
  }});
  return decisions;
}}

function buildMetadataBackupData() {{
  const metadata = {{}};
  cards.forEach(card => {{
    const meta = loadCardMeta(card);
    if (Object.keys(meta).length) metadata[card.dataset.key] = meta;
  }});
  return metadata;
}}

function loadScanStateForBackup() {{
  try {{ return JSON.parse(storageGetMigrated(SCAN_STATE_KEY, LEGACY_SCAN_STATE_KEYS) || "null"); }}
  catch (_) {{ return null; }}
}}

function stableBackupClone(value) {{
  if (Array.isArray(value)) return value.map(stableBackupClone);
  if (value && typeof value === "object") {{
    const sorted = {{}};
    Object.keys(value).sort().forEach(key => {{
      sorted[key] = stableBackupClone(value[key]);
    }});
    return sorted;
  }}
  return value;
}}

function stableBackupString(value) {{
  return JSON.stringify(stableBackupClone(value));
}}

function currentDecisionBackupSignature() {{
  return stableBackupString(buildDecisionBackupData());
}}

function buildFullBackupSnapshot() {{
  return stableBackupClone({{
    decisions:buildDecisionBackupData(),
    metadata:buildMetadataBackupData(),
    scanState:loadScanStateForBackup()
  }});
}}

function currentUserDataBackupSignature() {{
  return stableBackupString(buildFullBackupSnapshot());
}}


function backupSnapshotChangeSummary(previousSnapshot) {{
  if (!previousSnapshot || typeof previousSnapshot !== "object") return null;
  if (!previousSnapshot.decisions || typeof previousSnapshot.decisions !== "object") return null;
  if (!previousSnapshot.metadata || typeof previousSnapshot.metadata !== "object") return null;

  const current = buildFullBackupSnapshot();
  const previousDecisions = previousSnapshot.decisions || {{}};
  const currentDecisions = current.decisions || {{}};
  const decisionKeys = new Set([...Object.keys(previousDecisions), ...Object.keys(currentDecisions)]);
  let decisions = 0;
  decisionKeys.forEach(key => {{
    const before = previousDecisions[key] || "undecided";
    const after = currentDecisions[key] || "undecided";
    if (before !== after) decisions++;
  }});

  const previousMetadata = previousSnapshot.metadata || {{}};
  const currentMetadata = current.metadata || {{}};
  const metadataKeys = new Set([...Object.keys(previousMetadata), ...Object.keys(currentMetadata)]);
  let tagNote = 0;
  let favorites = 0;
  let review = 0;
  let other = 0;

  metadataKeys.forEach(key => {{
    const before = previousMetadata[key] && typeof previousMetadata[key] === "object" ? previousMetadata[key] : {{}};
    const after = currentMetadata[key] && typeof currentMetadata[key] === "object" ? currentMetadata[key] : {{}};
    const tagChanged = String(before.tags ?? "") !== String(after.tags ?? "");
    const noteChanged = String(before.note ?? "") !== String(after.note ?? "");
    const favoriteChanged = Boolean(before.favorite) !== Boolean(after.favorite);
    const reviewChanged = Boolean(before.reviewLater) !== Boolean(after.reviewLater);
    if (tagChanged || noteChanged) tagNote++;
    if (favoriteChanged) favorites++;
    if (reviewChanged) review++;

    const stripKnown = meta => {{
      const clone = {{...meta}};
      delete clone.tags;
      delete clone.note;
      delete clone.favorite;
      delete clone.reviewLater;
      return clone;
    }};
    const rawChanged = stableBackupString(before) !== stableBackupString(after);
    const knownChanged = tagChanged || noteChanged || favoriteChanged || reviewChanged;
    if (stableBackupString(stripKnown(before)) !== stableBackupString(stripKnown(after)) || (rawChanged && !knownChanged)) other++;
  }});

  const scanState = stableBackupString(previousSnapshot.scanState ?? null) === stableBackupString(current.scanState ?? null) ? 0 : 1;
  const total = decisions + tagNote + favorites + review + scanState + other;
  return {{decisions, tagNote, favorites, review, scanState, other, total}};
}}

function setBackupChangeCount(id, value) {{
  const el = document.getElementById(id);
  if (el) el.textContent = value === null ? "—" : String(value);
}}

function updateBackupChangeSummary(fullEntry, fullState) {{
  const panel = document.getElementById("backupChangeSummary");
  if (!panel) return;
  const status = document.getElementById("backupChangeSummaryStatus");
  const note = document.getElementById("backupChangeSummaryNote");
  const otherItem = document.getElementById("backupChangeOtherItem");
  const summary = backupSnapshotChangeSummary(fullEntry?.snapshot);

  if (!fullEntry?.savedAt) {{
    panel.dataset.state = "none";
    if (status) status.textContent = "未バックアップ";
    if (note) note.textContent = "最初のユーザーデータ保存後から、変更内容の件数を表示します。";
    ["backupChangeDecisionCount","backupChangeTagNoteCount","backupChangeFavoriteCount","backupChangeReviewCount","backupChangeScanCount"].forEach(id => setBackupChangeCount(id, null));
    otherItem?.classList.add("hidden");
    return;
  }}

  if (!summary) {{
    panel.dataset.state = fullState === "current" ? "current" : "changed";
    if (status) status.textContent = "内訳未記録";
    if (note) note.textContent = "この保存記録は旧バージョン形式です。次回ユーザーデータ保存後から変更内訳を表示できます。";
    ["backupChangeDecisionCount","backupChangeTagNoteCount","backupChangeFavoriteCount","backupChangeReviewCount","backupChangeScanCount"].forEach(id => setBackupChangeCount(id, null));
    otherItem?.classList.add("hidden");
    return;
  }}

  panel.dataset.state = summary.total ? "changed" : "current";
  if (status) status.textContent = summary.total ? "変更あり" : "変更なし";
  setBackupChangeCount("backupChangeDecisionCount", summary.decisions);
  setBackupChangeCount("backupChangeTagNoteCount", summary.tagNote);
  setBackupChangeCount("backupChangeFavoriteCount", summary.favorites);
  setBackupChangeCount("backupChangeReviewCount", summary.review);
  setBackupChangeCount("backupChangeScanCount", summary.scanState);
  setBackupChangeCount("backupChangeOtherCount", summary.other);
  otherItem?.classList.toggle("hidden", summary.other === 0);
  if (note) {{
    note.textContent = summary.total
      ? "件数は、前回保存時点と現在を比較した変更対象数です。タグとメモは同じペイントで両方変わっても1件として数えます。"
      : "現在のユーザーデータは、前回保存時点と同じ内容です。";
  }}
}}

function loadBackupStatusState() {{
  try {{
    const state = JSON.parse(storageGetMigrated(BACKUP_STATUS_KEY, LEGACY_BACKUP_STATUS_KEYS) || "null");
    return state && typeof state === "object" ? state : {{}};
  }} catch (_) {{
    return {{}};
  }}
}}

function saveBackupStatusState(state) {{
  storageSet(BACKUP_STATUS_KEY, JSON.stringify({{
    backupStatusVersion:BACKUP_STATUS_VERSION,
    ...state
  }}));
}}

function formatBackupTimestamp(value) {{
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return REPORT_FALLBACK_UNKNOWN_DATE;
  return date.toLocaleString(REPORT_LOCALE);
}}

function updateBackupBadge(statusEl, timeEl, entry, currentSignature) {{
  const savedAt = entry?.savedAt || "";
  const savedSignature = typeof entry?.signature === "string" ? entry.signature : "";
  let state = "none";
  let label = "未バックアップ";
  if (savedAt && savedSignature) {{
    if (savedSignature === currentSignature) {{
      state = "current";
      label = "最新";
    }} else {{
      state = "changed";
      label = "変更あり";
    }}
  }}
  if (statusEl) {{
    statusEl.dataset.state = state;
    statusEl.textContent = label;
  }}
  if (timeEl) timeEl.textContent = `前回保存: ${{formatBackupTimestamp(savedAt)}}`;
  return state;
}}

function currentFullBackupState() {{
  const state = loadBackupStatusState();
  const entry = state.full;
  const savedAt = entry?.savedAt || "";
  const savedSignature = typeof entry?.signature === "string" ? entry.signature : "";
  if (!savedAt || !savedSignature) return "none";
  return savedSignature === currentUserDataBackupSignature() ? "current" : "changed";
}}

function updateOrganizationCompletionSummary(stateSummary = null, backupStateOverride = "") {{
  const panel = document.getElementById("organizationCompletionSummary");
  if (!panel) return;

  stateSummary = stateSummary || collectCardStateSummary();
  const complete = stateSummary.total > 0 && stateSummary.undecided === 0;
  panel.classList.toggle("hidden", !complete);
  if (!complete) return;

  const status = document.getElementById("organizationCompletionStatus");
  const counts = document.getElementById("organizationCompletionCounts");
  const backup = document.getElementById("organizationCompletionBackup");
  if (status) status.textContent = "整理完了";
  if (counts) counts.textContent = `残す ${{stateSummary.keep}}件 / 削除候補 ${{stateSummary.deleted}}件`;

  let backupState = ["none","current","changed"].includes(backupStateOverride)
    ? backupStateOverride
    : currentFullBackupState();
  let backupText = "バックアップ 未保存";
  if (!persistentStorage) {{
    backupState = "temporary";
    backupText = "一時メモリ保存 · バックアップ推奨";
  }} else if (backupState === "current") {{
    backupText = "バックアップ 最新";
  }} else if (backupState === "changed") {{
    backupText = "バックアップ 変更あり";
  }}
  if (backup) {{
    backup.dataset.state = backupState;
    backup.textContent = backupText;
  }}
}}

function updateBackupStatus(stateSummary = null) {{
  const panel = document.getElementById("backupStatusPanel");
  if (!panel) return;
  const state = loadBackupStatusState();
  const fullState = updateBackupBadge(
    document.getElementById("fullBackupStatus"),
    document.getElementById("fullBackupTime"),
    state.full,
    currentUserDataBackupSignature()
  );
  updateBackupBadge(
    document.getElementById("decisionBackupStatus"),
    document.getElementById("decisionBackupTime"),
    state.decisions,
    currentDecisionBackupSignature()
  );
  updateBackupChangeSummary(state.full, fullState);

  updateOrganizationCompletionSummary(stateSummary, fullState);

  const recommendation = document.getElementById("backupRecommendation");
  if (!recommendation) return;
  if (!persistentStorage) {{
    recommendation.dataset.level = "urgent";
    recommendation.textContent = "現在は一時メモリ保存です。タブを閉じる前にユーザーデータ保存を実行してください。";
  }} else if (fullState === "none") {{
    recommendation.dataset.level = "warning";
    recommendation.textContent = "このブラウザではユーザーデータ保存の記録がありません。最初のバックアップを作成しておくことをおすすめします。";
  }} else if (fullState === "changed") {{
    recommendation.dataset.level = "warning";
    recommendation.textContent = "前回のユーザーデータ保存後に整理データの変更があります。区切りのよいところで再保存してください。";
  }} else {{
    recommendation.dataset.level = "ok";
    recommendation.textContent = "ユーザーデータは前回の保存操作時点と一致しています。";
  }}
}}

function recordBackupSnapshot(kind) {{
  const state = loadBackupStatusState();
  const savedAt = new Date().toISOString();
  if (kind === "full") {{
    state.full = {{
      savedAt,
      signature:currentUserDataBackupSignature(),
      snapshot:buildFullBackupSnapshot()
    }};
  }} else if (kind === "decisions") {{
    state.decisions = {{
      savedAt,
      signature:currentDecisionBackupSignature(),
      snapshot:stableBackupClone(buildDecisionBackupData())
    }};
  }} else {{
    return;
  }}
  saveBackupStatusState(state);
  refreshBackupUi();
}}

function buildUserDataPayload() {{
  let uiState = null;
  try {{ uiState = JSON.parse(storageGetMigrated(UI_STATE_KEY, LEGACY_UI_STATE_KEYS) || "null"); }} catch (_) {{}}
  return {{
    app:"Livery Organizer for FH6", version:"{VERSION}", userdataVersion:USERDATA_VERSION,
    exportedAt:new Date().toISOString(),
    decisions:buildDecisionBackupData(),
    metadata:buildMetadataBackupData(),
    uiState,
    scanState:loadScanStateForBackup()
  }};
}}
document.getElementById("exportUserData").addEventListener("click", () => {{
  const blob = new Blob([JSON.stringify(buildUserDataPayload(), null, 2)], {{type:"application/json;charset=utf-8"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href=url; a.download="livery-organizer-for-fh6-userdata.json"; a.click();
  URL.revokeObjectURL(url);
  recordBackupSnapshot("full");
}});
document.getElementById("importUserData").addEventListener("click", () => document.getElementById("importUserDataFile").click());
function summarizeUserDataPayload(payload) {{
  const decisions = payload?.decisions || {{}};
  const metadata = payload?.metadata || {{}};
  const keys = new Set([...Object.keys(decisions), ...Object.keys(metadata)]);
  const matched = [...keys].filter(key => cards.some(card => card.dataset.key === key)).length;
  const metaValues = Object.values(metadata);
  return {{
    decisions: Object.keys(decisions).length,
    metadata: Object.keys(metadata).length,
    tags: metaValues.filter(meta => String(meta?.tags || "").trim()).length,
    notes: metaValues.filter(meta => String(meta?.note || "").trim()).length,
    favorites: metaValues.filter(meta => Boolean(meta?.favorite)).length,
    review: metaValues.filter(meta => Boolean(meta?.reviewLater)).length,
    matched,
    unmatched: Math.max(0, keys.size - matched)
  }};
}}

function showUserDataPreview(payload) {{
  const s = summarizeUserDataPayload(payload);
  document.getElementById("userDataPreviewBody").innerHTML = `
    <p>読み込むファイルの内容を確認してください。</p>
    <div class="diagnostics-list">
      <div class="diagnostics-row"><span>整理状態</span><b>${{s.decisions}}件</b></div>
      <div class="diagnostics-row"><span>タグ・メモ等</span><b>${{s.metadata}}件</b></div>
      <div class="diagnostics-row"><span>タグあり</span><b>${{s.tags}}件</b></div>
      <div class="diagnostics-row"><span>メモあり</span><b>${{s.notes}}件</b></div>
      <div class="diagnostics-row"><span>お気に入り</span><b>${{s.favorites}}件</b></div>
      <div class="diagnostics-row"><span>後で確認</span><b>${{s.review}}件</b></div>
      <div class="diagnostics-row"><span>現在のペイントと一致</span><b>${{s.matched}}件</b></div>
      <div class="diagnostics-row"><span>現在存在しないデータ</span><b>${{s.unmatched}}件</b></div>
    </div>
    <p class="small">「統合」は現在データを残してファイル内の値だけ上書きします。「完全に置換」は現在の整理状態・タグ・メモ等を消去してから復元します。</p>`;
  openModal("userDataPreviewModal", document.getElementById("importUserData"));
}}

function applyUserDataPayload(payload, replaceExisting = false) {{
  const decisions = payload?.decisions || {{}};
  const metadata = payload?.metadata || {{}};

  if (replaceExisting) {{
    cards.forEach(card => {{
      storageRemove(stateKey(card));
      storageRemove(metaKey(card));
    }});
  }}

  cards.forEach(card => {{
    const state = decisions[card.dataset.key];
    if (["keep","delete","undecided"].includes(state)) {{
      if (state === "undecided") storageRemove(stateKey(card));
      else storageSet(stateKey(card), state);
    }}
    if (Object.prototype.hasOwnProperty.call(metadata, card.dataset.key)) {{
      storageSet(metaKey(card), JSON.stringify(metadata[card.dataset.key] || {{}}));
    }}
    paintState(card);
    applyCardMeta(card);
  }});

  if (payload?.uiState) storageSet(UI_STATE_KEY, JSON.stringify(payload.uiState));
  if (payload?.scanState) storageSet(SCAN_STATE_KEY, JSON.stringify(payload.scanState));
  applyScanDiff();

  undoStack.length = 0;
  redoStack.length = 0;
  updateUndoRedoUi();
  rebuildTagFilter();
  restoreUiState();
  applyFilters();
  closeModal("userDataPreviewModal");
  pendingUserData = null;
  alert(replaceExisting ? "ユーザーデータを完全置換で復元しました。" : "ユーザーデータを統合して復元しました。");
}}

document.getElementById("importUserDataFile").addEventListener("change", async event => {{
  const file = event.target.files?.[0];
  if (!file) return;
  try {{
    const payload = JSON.parse(await file.text());
    if (!payload || typeof payload !== "object") throw new Error("invalid payload");
    pendingUserData = payload;
    showUserDataPreview(payload);
  }} catch (_) {{
    pendingUserData = null;
    alert("ユーザーデータを読み込めませんでした。");
  }} finally {{
    event.target.value = "";
  }}
}});

document.getElementById("restoreMerge").addEventListener("click", () => {{
  if (pendingUserData) applyUserDataPayload(pendingUserData, false);
}});
document.getElementById("restoreReplace").addEventListener("click", () => {{
  if (pendingUserData) applyUserDataPayload(pendingUserData, true);
}});
document.getElementById("restoreCancel").addEventListener("click", () => {{
  pendingUserData = null;
  closeModal("userDataPreviewModal");
}});

document.getElementById("exportDecisions").addEventListener("click", () => {{
  const decisions = buildDecisionBackupData();
  const payload = {{
    app: "Livery Organizer for FH6",
    version: "{VERSION}",
    exportedAt: new Date().toISOString(),
    decisions
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type:"application/json;charset=utf-8"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "livery-organizer-for-fh6-decisions-backup.json";
  a.click();
  URL.revokeObjectURL(url);
  recordBackupSnapshot("decisions");
}});

document.getElementById("importDecisions").addEventListener("click", () => {{
  document.getElementById("importDecisionsFile").click();
}});

document.getElementById("importDecisionsFile").addEventListener("change", async event => {{
  const file = event.target.files?.[0];
  if (!file) return;
  try {{
    const payload = JSON.parse(await file.text());
    const decisions = payload?.decisions || {{}};
    let restored = 0;
    cards.forEach(card => {{
      const state = decisions[card.dataset.key];
      if (["keep","delete","undecided"].includes(state)) {{
        if (state === "undecided") storageRemove(stateKey(card));
        else storageSet(stateKey(card), state);
        restored++;
      }}
      paintState(card);
    }});
    applyFilters();
    alert(`${{restored}}件の判定を復元しました。`);
  }} catch (error) {{
    alert("判定バックアップを読み込めませんでした。");
  }} finally {{
    event.target.value = "";
  }}
}});

function csvEscape(v) {{
  const s = String(v ?? "");
  return '"' + s.replaceAll('"', '""') + '"';
}}

function cardsInCurrentDisplayOrder() {{
  if (document.body.classList.contains("fh6-my-design-view-mode")) {{
    return [...document.querySelectorAll("#fh6MyDesignTrack .fh6-my-design-column:not(.hidden) .card")]
      .filter(card => !card.classList.contains("hidden"));
  }}
  if (document.body.classList.contains("creator-sort-mode")) {{
    return [...document.querySelectorAll("#creatorGroupedSections .creator-group .grid .card")]
      .filter(card => !card.classList.contains("hidden"));
  }}
  if (document.body.classList.contains("flat-sort-mode")) {{
    return [...document.querySelectorAll("#flatSortGrid .card")]
      .filter(card => !card.classList.contains("hidden"));
  }}

  return [...document.querySelectorAll("#groupedSections .car-group .grid .card")]
    .filter(card => !card.classList.contains("hidden"));
}}

function exportDecisionCsv(visibleOnly = false) {{
  const decisionLabels = {{undecided:"未決定",keep:"残す",delete:"削除候補"}};
  const rows = [[
    "整理状態","Car ID","車両名","メーカー","モデル","年式",
    "車両アセット","作成者","バイナル数","タイトル","説明","取得日時",
    "タグ","メモ","お気に入り","後で確認","Livery参照ID","ペイントID",
    "フィンガープリント","サムネイル元","保存元","解析メモ"
  ]];

  // 表示中CSVは、現在画面に見えている順番をそのままCSVの行順へ反映する。
  // 全件CSVは従来どおり全レコードの基準順を維持する。
  const exportCards = visibleOnly ? cardsInCurrentDisplayOrder() : cards;

  exportCards.forEach(card => {{
    const record = CSV_RECORDS[card.dataset.key]; if (!record) return;
    const meta = loadCardMeta(card);
    rows.push([
      decisionLabels[getState(card)] || getState(card),
      record.car_id,
      record.vehicle,
      record.manufacturer,
      record.model,
      record.year,
      record.vehicle_asset,
      record.creator,
      record.vinyl_count,
      record.title,
      record.description,
      record.timestamp,
      meta.tags || "",
      meta.note || "",
      meta.favorite ? "はい" : "",
      meta.reviewLater ? "はい" : "",
      record.livery_reference_id,
      record.livery_id,
      record.fingerprint,
      record.image_path,
      record.source_dir,
      record.analysis_notes
    ]);
  }});
  const csv = rows.map(row => row.map(csvEscape).join(",")).join("\\r\\n");
  const blob = new Blob(["\\ufeff",csv],{{type:"text/csv;charset=utf-8"}});
  const url = URL.createObjectURL(blob); const a=document.createElement("a");
  a.href=url; a.download=visibleOnly?"livery-organizer-for-fh6-decisions-filtered.csv":"livery-organizer-for-fh6-decisions.csv"; a.click();
  URL.revokeObjectURL(url);
  return csv;
}}
document.getElementById("exportCsv").addEventListener("click",()=>exportDecisionCsv(false));
document.getElementById("exportFilteredCsv").addEventListener("click",()=>exportDecisionCsv(true));

function downloadExcelReport() {{
  try {{
    const a = document.createElement("a");
    a.href = "livery-organizer-for-fh6.xlsx";
    a.download = "livery-organizer-for-fh6.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }} catch (error) {{
    alert("Excelファイルを開けませんでした。レポートフォルダ内の livery-organizer-for-fh6.xlsx を確認してください。");
  }}
}}
document.getElementById("downloadExcel").addEventListener("click", downloadExcelReport);

const UI_STATE_KEY = "livery-organizer-for-fh6-ui-v4";
const LEGACY_UI_STATE_KEYS = ["livery-organizer-for-fh6-ui-v3", "fh6-livery-organizer-ui-v3", "fh6-livery-organizer-ui-v2"];
const UI_STATE_VERSION = 4;
const FILTER_PRESETS_KEY = "livery-organizer-for-fh6-filter-presets-v1";
const LEGACY_FILTER_PRESETS_KEYS = ["fh6-livery-filter-presets-v1"];

function currentUiState() {{
  return {{
    uiStateVersion:UI_STATE_VERSION,
    query: q.value,
    decision: selectedFilterValues(filter),
    progress: selectedFilterValues(progressFilter),
    vehicle: selectedFilterValues(vehicleFilter),
    make: selectedFilterValues(makeFilter),
    year: selectedFilterValues(yearFilter),
    creator: selectedFilterValues(creatorFilter),
    paintCount: selectedFilterValues(paintCountFilter),
    vinylMin: vinylMinInput?.value || "",
    vinylMax: vinylMaxInput?.value || "",
    sort: sortOrder.value,
    compact: document.body.classList.contains("compact"),
    compactFields: selectedCompactFields(),
    similarOnly: similarOnlyMode,
    similarKind: similarKindMode,
    exactDuplicateOnly: exactDuplicateOnlyMode,
    newOnly: newOnlyMode,
    favoriteOnly: favoriteOnlyMode,
    reviewOnly: reviewOnlyMode,
    sequentialReview: sequentialReviewMode,
    tag: selectedFilterValues(tagFilter),
    tagMode: tagMatchMode,
    creatorSearch: creatorQuickSearch?.value || "",
    darkTheme: document.body.classList.contains("dark-theme"),
    creatorMoreOpen: creatorSearchRestoreOpen !== null
      ? Boolean(creatorSearchRestoreOpen)
      : Boolean(
          document.getElementById("creatorMoreList") &&
          !document.getElementById("creatorMoreList").classList.contains("hidden")
        )
  }};
}}

function currentFilterPresetState() {{
  const state = currentUiState();
  return {{
    presetStateVersion:2,
    query:state.query, decision:state.decision, progress:state.progress, vehicle:state.vehicle, make:state.make,
    year:state.year, creator:state.creator, paintCount:state.paintCount,
    vinylMin:state.vinylMin, vinylMax:state.vinylMax, tag:state.tag, tagMode:state.tagMode,
    similarOnly:state.similarOnly, similarKind:state.similarKind, exactDuplicateOnly:state.exactDuplicateOnly, newOnly:state.newOnly, favoriteOnly:state.favoriteOnly,
    reviewOnly:state.reviewOnly, sort:state.sort
  }};
}}

function applyFilterState(state) {{
  if (!state || typeof state !== "object") return;
  if (typeof state.query === "string") q.value = state.query;
  restoreFilterValues(filter, state.decision);
  restoreFilterValues(progressFilter, state.progress);
  restoreFilterValues(vehicleFilter, state.vehicle);
  restoreFilterValues(makeFilter, state.make);
  restoreFilterValues(yearFilter, state.year);
  restoreFilterValues(creatorFilter, state.creator);
  restoreFilterValues(paintCountFilter, state.paintCount);
  restoreFilterValues(tagFilter, state.tag);

  // v0.4.2互換処理: vinylCountは「以上」しきい値の配列または文字列でした。
  if (state.vinylMin !== undefined || state.vinylMax !== undefined) {{
    if (vinylMinInput) vinylMinInput.value = String(state.vinylMin ?? "");
    if (vinylMaxInput) vinylMaxInput.value = String(state.vinylMax ?? "");
  }} else {{
    const oldThresholds = normalizeFilterValues(state.vinylCount).map(Number).filter(Number.isFinite);
    if (vinylMinInput) vinylMinInput.value = oldThresholds.length ? String(Math.min(...oldThresholds)) : "";
    if (vinylMaxInput) vinylMaxInput.value = "";
  }}
  setFilterValues(vinylCountFilter, []);

  tagMatchMode = state.tagMode === "and" ? "and" : "or";
  updateTagModeUi();
  similarOnlyMode = Boolean(state.similarOnly);
  similarKindMode = similarOnlyMode ? normalizeSimilarKind(state.similarKind) : "all";
  exactDuplicateOnlyMode = Boolean(state.exactDuplicateOnly);
  newOnlyMode = Boolean(state.newOnly);
  favoriteOnlyMode = Boolean(state.favoriteOnly);
  reviewOnlyMode = Boolean(state.reviewOnly);
  selectedOnlyMode = false;
  updateSimilarityFilterUi();
  document.getElementById("newOnly").classList.toggle("active", newOnlyMode);
  document.getElementById("favoriteOnly").classList.toggle("active", favoriteOnlyMode);
  document.getElementById("reviewOnly").classList.toggle("active", reviewOnlyMode);
  const sort = state.sort;
  if (typeof sort === "string" && [...sortOrder.options].some(option => option.value === sort)) sortOrder.value = sort;
  renderAllDetailFilterChoices();
}}

function saveUiState() {{
  try {{
    storageSet(UI_STATE_KEY, JSON.stringify(currentUiState()));
  }} catch (_) {{}}
}}

function restoreUiState() {{
  try {{
    const raw = storageGetMigrated(UI_STATE_KEY, LEGACY_UI_STATE_KEYS);
    if (!raw) return;
    const state = JSON.parse(raw);
    applyFilterState(state);

    document.body.classList.toggle("dark-theme", Boolean(state.darkTheme));
    document.getElementById("themeToggle").textContent = document.body.classList.contains("dark-theme") ? "ライトテーマ" : "ダークテーマ";
    const creatorMoreList = document.getElementById("creatorMoreList");
    const creatorMoreToggle = document.getElementById("creatorMoreToggle");
    if (creatorMoreList && creatorMoreToggle) {{
      const open = Boolean(state.creatorMoreOpen);
      creatorMoreList.classList.toggle("hidden", !open);
      creatorMoreToggle.setAttribute("aria-expanded", open ? "true" : "false");
      creatorMoreToggle.textContent = open ? "作成者を折りたたむ" : creatorMoreToggle.dataset.closedLabel;
    }}
    document.body.classList.toggle("compact", Boolean(state.compact));
    applyCompactFields(state.compactFields);
    document.getElementById("compactToggle").textContent = document.body.classList.contains("compact") ? "通常表示" : "コンパクト表示";
    sequentialReviewMode = Boolean(state.sequentialReview);
    updateSequentialReviewUi();
    if (creatorQuickSearch && typeof state.creatorSearch === "string") {{
      creatorQuickSearch.value = state.creatorSearch;
      applyCreatorSearch();
    }}
    // 移行済みv2状態を、明示的なv3スキーマキーへ保存します。
    saveUiState();
  }} catch (_) {{}}
}}

function loadFilterPresets() {{
  try {{
    const payload = JSON.parse(storageGetMigrated(FILTER_PRESETS_KEY, LEGACY_FILTER_PRESETS_KEYS) || '{{"presetVersion":1,"items":[]}}');
    return Array.isArray(payload?.items) ? payload.items.filter(item => item && typeof item.name === "string") : [];
  }} catch (_) {{ return []; }}
}}
function saveFilterPresets(items) {{
  storageSet(FILTER_PRESETS_KEY, JSON.stringify({{presetVersion:1, items}}));
}}
function renderFilterPresets() {{
  const select = document.getElementById("filterPresetSelect");
  if (!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">プリセットを選択…</option>';
  loadFilterPresets().sort((a,b)=>a.name.localeCompare(b.name,REPORT_LOCALE)).forEach(item => {{
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.name;
    select.appendChild(option);
  }});
  if ([...select.options].some(option => option.value === current)) select.value = current;
}}

document.getElementById("saveFilterPreset")?.addEventListener("click", () => {{
  const input = document.getElementById("filterPresetName");
  const name = String(input?.value || "").trim();
  if (!name) {{ alert("プリセット名を入力してください。"); return; }}
  const items = loadFilterPresets();
  const existing = items.findIndex(item => item.name === name);
  if (existing >= 0 && !confirm(`「${{name}}」を現在の条件で上書きしますか？`)) return;
  const item = {{name, state:currentFilterPresetState()}};
  if (existing >= 0) items[existing] = item; else items.push(item);
  saveFilterPresets(items);
  renderFilterPresets();
  document.getElementById("filterPresetSelect").value = name;
}});
document.getElementById("applyFilterPreset")?.addEventListener("click", () => {{
  const name = document.getElementById("filterPresetSelect")?.value || "";
  const preset = loadFilterPresets().find(item => item.name === name);
  if (!preset) {{ alert("適用するプリセットを選択してください。"); return; }}
  applyFilterState(preset.state || {{}});
  applyAndPersist();
}});
document.getElementById("deleteFilterPreset")?.addEventListener("click", () => {{
  const select = document.getElementById("filterPresetSelect");
  const name = select?.value || "";
  if (!name) {{ alert("削除するプリセットを選択してください。"); return; }}
  if (!confirm(`プリセット「${{name}}」を削除しますか？`)) return;
  saveFilterPresets(loadFilterPresets().filter(item => item.name !== name));
  renderFilterPresets();
}});
renderFilterPresets();

function renderActiveFilterChips() {{
  const host = document.getElementById("activeFilterChips");
  if (!host) return;
  host.innerHTML = "";
  const chips = [];
  const add = (label, remover) => chips.push({{label, remover}});
  if (q.value.trim()) add(`検索: ${{q.value.trim()}}`, () => {{ q.value=""; }});

  const dimensions = [
    [filter,"整理状態"],[progressFilter,"整理進捗"],[vehicleFilter,"車種"],[makeFilter,"メーカー"],[yearFilter,"年式"],
    [creatorFilter,"作成者"],[paintCountFilter,"ペイント件数"],[tagFilter,"タグ"]
  ];
  dimensions.forEach(([select, title]) => {{
    const values = selectedFilterValues(select);
    const labels = selectedFilterLabels(select, true);
    values.forEach((value,index) => add(`${{title}}: ${{labels[index] || value}}`, () => {{
      setFilterValues(select, selectedFilterValues(select).filter(item => item !== value));
      if (detailFilterSelects.includes(select)) renderDetailFilterChoices(select);
    }}));
  }});

  const vinylMin = parseOptionalNumber(vinylMinInput?.value);
  const vinylMax = parseOptionalNumber(vinylMaxInput?.value);
  if (vinylMin !== null || vinylMax !== null) add(`バイナル: ${{vinylMin ?? 0}}〜${{vinylMax ?? "上限なし"}}`, () => {{
    if (vinylMinInput) vinylMinInput.value="";
    if (vinylMaxInput) vinylMaxInput.value="";
  }});
  if (selectedFilterValues(tagFilter).length > 1) add(`タグ条件: ${{tagMatchMode.toUpperCase()}}`, () => {{ tagMatchMode="or"; updateTagModeUi(); }});
  if (newOnlyMode) add("新規のみ", () => {{newOnlyMode=false;}});
  if (similarOnlyMode) add(
    similarKindMode === "all" ? "類似候補のみ" : `類似候補: ${{SIMILAR_KIND_LABELS[similarKindMode]}}のみ`,
    () => {{similarOnlyMode=false; similarKindMode="all";}}
  );
  if (exactDuplicateOnlyMode) add("再DL重複のみ", () => {{exactDuplicateOnlyMode=false;}});
  if (favoriteOnlyMode) add("お気に入りのみ", () => {{favoriteOnlyMode=false;}});
  if (reviewOnlyMode) add("後で確認のみ", () => {{reviewOnlyMode=false;}});
  if (selectedOnlyMode) add("選択中のみ", () => {{selectedOnlyMode=false;}});

  chips.forEach(item => {{
    const chip = document.createElement("div");
    chip.className = "active-filter-chip";
    const label = document.createElement("span");
    label.textContent = item.label;
    const close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", `${{item.label}}を解除`);
    close.textContent = "×";
    close.addEventListener("click", () => {{ item.remover(); applyAndPersist(); }});
    chip.append(label, close);
    host.appendChild(chip);
  }});
}}

function updateMobileFilterSummary() {{
  const parts = [];
  if (q.value.trim()) parts.push(`検索: ${{q.value.trim()}}`);

  [filter, progressFilter, vehicleFilter, makeFilter, yearFilter, creatorFilter, paintCountFilter, tagFilter]
    .forEach(select => {{
      const labels = selectedFilterLabels(select, false);
      if (!labels.length) return;
      parts.push(labels.length <= 2 ? labels.join(", ") : `${{labels[0]}} 他${{labels.length - 1}}件`);
    }});
  const vinylMin = parseOptionalNumber(vinylMinInput?.value);
  const vinylMax = parseOptionalNumber(vinylMaxInput?.value);
  if (vinylMin !== null || vinylMax !== null) parts.push(`バイナル: ${{vinylMin ?? 0}}〜${{vinylMax ?? "上限なし"}}`);
  if (selectedFilterValues(tagFilter).length > 1) parts.push(`タグ: ${{tagMatchMode.toUpperCase()}}`);
  if (similarOnlyMode) parts.push(similarKindMode === "all" ? "類似候補のみ" : `類似:${{SIMILAR_KIND_LABELS[similarKindMode]}}`);
  if (exactDuplicateOnlyMode) parts.push("再DL重複のみ");
  if (favoriteOnlyMode) parts.push("お気に入りのみ");
  if (reviewOnlyMode) parts.push("後で確認のみ");
  if (selectedOnlyMode) parts.push("選択中のみ");
  parts.push(sortOrder.options[sortOrder.selectedIndex]?.textContent || "");
  document.getElementById("mobileFilterSummary").textContent = parts.filter(Boolean).join(" / ") || "条件なし";
}}

function applyAndPersist() {{
  return refreshOrganizerUi({{mobile:true, persist:true}});
}}

const mobileFilterToggle = document.getElementById("mobileFilterToggle");
const filterToolbar = document.getElementById("filterToolbar");

mobileFilterToggle.addEventListener("click", () => {{
  const open = filterToolbar.classList.toggle("mobile-open");
  mobileFilterToggle.setAttribute("aria-expanded", open ? "true" : "false");
  mobileFilterToggle.textContent = open ? "絞り込みを閉じる" : "絞り込み・並び替え";
}});

const lightbox = document.getElementById("lightbox");
const lightboxImage = document.getElementById("lightboxImage");
const lightboxClose = document.getElementById("lightboxClose");
let lightboxReturnFocus = null;

document.querySelectorAll("img.livery-image").forEach(img => {{
  img.addEventListener("click", () => {{
    lightboxReturnFocus = img;
    lightboxImage.src = img.dataset.full || img.src;
    lightboxImage.alt = img.alt || "";
    lightbox.classList.add("open");
    lightbox.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => lightboxClose.focus());
  }});
}});
function closeLightbox() {{
  const returnTarget = lightboxReturnFocus;
  lightboxReturnFocus = null;
  lightbox.classList.remove("open");
  lightbox.setAttribute("aria-hidden", "true");
  lightboxImage.removeAttribute("src");
  if (returnTarget instanceof HTMLElement && returnTarget.isConnected) {{
    // 画像自体は通常のTab順には入れませんが、拡大表示を閉じた後の位置は戻します。
    if (!returnTarget.hasAttribute("tabindex")) returnTarget.setAttribute("tabindex", "-1");
    requestAnimationFrame(() => returnTarget.focus({{preventScroll:true}}));
  }}
}}
lightboxClose.addEventListener("click", closeLightbox);
lightbox.addEventListener("click", e => {{
  if (e.target === lightbox) closeLightbox();
}});
document.addEventListener("keydown", e => {{
  if (!lightbox.classList.contains("open")) return;
  if (e.key === "Tab") {{
    e.preventDefault();
    lightboxClose.focus();
    return;
  }}
  if (e.key === "Escape") {{
    e.preventDefault();
    closeLightbox();
  }}
}});

multiFilterSelects.forEach(normalizeNativeMultiSelection);
applyCompactFields(DEFAULT_COMPACT_FIELDS);
applyScanDiff();
renderAllDetailFilterChoices();
updateTagModeUi();
restoreUiState();
loadFh6NavigatorSettings();
syncAllFh6CardPositionLabels();
updateFh6NavigatorUi();
applyFilters();
applyCreatorSearch();
updateMobileFilterSummary();
updateStorageStatus();
updateFh6TempDeletedUi();
updateUndoRedoUi();
updateSequentialReviewUi();
const uiStatus = document.getElementById("uiStatus");
if (uiStatus && uiStatus.dataset.state !== "error") {{
  uiStatus.textContent = "正常";
  uiStatus.dataset.state = "ok";
}}
updateStartupReadiness();
</script>
</body>
</html>
"""
    if report_language != "ja":
        doc = doc.replace('<html lang="ja">', f'<html lang="{report_language}">', 1)
        report_i18n_script = build_report_i18n_script(report_language)
        if report_i18n_script:
            doc = doc.replace("</body>", report_i18n_script + "\n</body>", 1)
    html_path.write_text(doc, encoding="utf-8")

    # HTMLを先に利用可能にしてからExcelを生成します。
    # Excelの内容・ファイル名・生成有無は従来と同じです。
    # 1行目にはExcel標準のオートフィルターを設定し、固定表示します。
    xlsx_path, xlsx_image_count = write_excel_report(records, outdir)
    stats["excel_file"] = str(xlsx_path)
    stats["excel_images_embedded"] = xlsx_image_count
    return html_path



def scan_and_report(
    root: Path,
    outdir: Path,
    embed_images: bool = True,
    verbose: bool = True,
    game_root: Optional[Path] = None,
    export_analysis_data: bool = False,
) -> Path:
    # 任意のdata/出力を作成する前に安全性を確認します。
    ensure_safe_output_directory(root, outdir)

    def progress(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    records, fh6_records, stats = scan_liveries(root, progress=progress)
    applied_stats = skip_applied_livery_reference_scan(
        records, progress=progress
    )
    stats = dict(stats)
    stats["applied_detection"] = applied_stats

    actual_game_root = game_root
    if actual_game_root is None:
        detected = default_game_roots()
        actual_game_root = detected[0] if detected else None

    vehicle_db: dict[int, VehicleInfo] = {}
    if actual_game_root and actual_game_root.exists():
        progress(tr("log.fh6_install", path=display_path_text(actual_game_root)))
        vehicle_db = scan_vehicle_assets(
            actual_game_root,
            progress=progress,
            required_car_ids={int(record.car_id) for record in [*records, *fh6_records]},
        )
        enrich_records_with_vehicle_info(records, vehicle_db)
        enrich_records_with_vehicle_info(fh6_records, vehicle_db)
        if export_analysis_data:
            write_vehicle_database(vehicle_db, outdir / "data")
    else:
        progress(tr("log.fh6_install_missing"))

    report = write_report(
        root,
        records,
        stats,
        outdir,
        embed_images=embed_images,
        game_root=actual_game_root,
        vehicle_db=vehicle_db,
        export_analysis_data=export_analysis_data,
        fh6_records=fh6_records,
    )

    if verbose:
        print()
        print(tr("log.complete", folders=stats["raw_livery_folders"], paints=stats["unique_liveries"], vehicles=stats["unique_car_ids"], vehicle_db=len(vehicle_db)))
        print(tr("log.output_bundle", bundle=output_bundle_label(embed_images=embed_images, export_analysis_data=export_analysis_data)))
        for label, path in output_bundle_entries(
            report.parent,
            embed_images=embed_images,
            export_analysis_data=export_analysis_data,
        ):
            print(f"{label}: {path}")
        print(tr("complete.source_unchanged"))

    return report


class App:
    def __init__(self, master):
        self.master = master
        configure_gui_fonts(self.master)
        self.master.title(f"{APP_NAME} v{VERSION}")
        self.master.geometry("1000x840")

        self._first_run = not settings_path().exists()
        self._quick_start_window = None
        saved = load_settings()
        self._settings_language = normalize_language(saved.get("language") or DEFAULT_LANGUAGE)
        if self._settings_language == "qps":
            self._settings_language = DEFAULT_LANGUAGE
        initialize_ui_language(saved)

        roots = default_roots()
        detected_root = str(roots[0]) if roots else r"C:\XboxGames\GameSave\pgs"
        game_roots = default_game_roots()
        detected_game_root = str(game_roots[0]) if game_roots else ""
        detected_out = str(Path.home() / "Documents" / DEFAULT_REPORT_DIR_NAME)

        default_root = str(saved.get("save_root") or detected_root)
        default_game_root = str(saved.get("game_root") or detected_game_root)
        saved_out = normalize_legacy_output_root(saved.get("output_root"))
        default_out = saved_out or detected_out
        default_copy = bool(saved.get("embed_thumbnails", saved.get("copy_thumbnails", True)))
        default_analysis = bool(saved.get("export_analysis_data", False))

        frm = ttk.Frame(master, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=f"{APP_NAME} v{VERSION}", font=(GUI_FONT_FAMILY, 18, "bold")).pack(anchor="w")
        ttk.Label(
            frm,
            text=tr("app.subtitle"),
            wraplength=930,
            justify="left",
        ).pack(anchor="w", pady=(2, 14))

        self.root_var = tk.StringVar(value=display_path_text(default_root))
        self.game_root_var = tk.StringVar(value=display_path_text(default_game_root))
        self.out_var = tk.StringVar(value=display_path_text(default_out))
        self.copy_var = tk.BooleanVar(value=default_copy)
        self.analysis_var = tk.BooleanVar(value=default_analysis)
        self._language_labels = {code: label for code, label in available_languages()}
        self._language_codes = {label: code for code, label in available_languages()}
        self._language_env_override = bool(os.environ.get("FH6_ORGANIZER_LANG"))
        displayed_language = get_language() if self._language_env_override else self._settings_language
        self.language_var = tk.StringVar(
            value=(
                language_display_name(displayed_language)
                if self._language_env_override
                else self._language_labels.get(displayed_language, self._language_labels[DEFAULT_LANGUAGE])
            )
        )

        self._settings_save_job = None
        self._preflight_update_job = None
        self._scan_running = False
        self._vehicle_metadata_update_running = False
        for var in (
            self.root_var,
            self.game_root_var,
            self.out_var,
            self.copy_var,
            self.analysis_var,
        ):
            var.trace_add("write", self._schedule_save_settings)
            var.trace_add("write", self._schedule_preflight_update)
        self.master.protocol("WM_DELETE_WINDOW", self.on_close)

        self._path_row(frm, tr("path.save_root"), self.root_var, self.choose_root)
        self._path_row(frm, tr("path.game_root"), self.game_root_var, self.choose_game_root)
        self._path_row(frm, tr("path.output_root"), self.out_var, self.choose_out)
        ttk.Label(
            frm,
            text=tr("settings.auto_saved", path=display_path_text(settings_path())),
            foreground="#666666",
            wraplength=930,
            justify="left",
        ).pack(anchor="w", pady=(2, 2))

        language_row = ttk.Frame(frm)
        language_row.pack(fill="x", pady=(8, 2))
        ttk.Label(language_row, text=tr("language.label")).pack(side="left")
        language_combo = ttk.Combobox(
            language_row,
            textvariable=self.language_var,
            values=[label for _, label in available_languages()],
            state="disabled" if self._language_env_override else "readonly",
            width=14,
        )
        language_combo.pack(side="left", padx=(8, 8))
        language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        ttk.Label(
            language_row,
            text=tr("language.env_override") if self._language_env_override else tr("language.note"),
            foreground="#666666",
            wraplength=650,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        ttk.Checkbutton(
            frm,
            text=tr("option.embed_thumbnails"),
            variable=self.copy_var,
        ).pack(anchor="w", pady=(10, 3))
        ttk.Checkbutton(
            frm,
            text=tr("option.export_analysis"),
            variable=self.analysis_var,
        ).pack(anchor="w", pady=(0, 6))

        preflight = ttk.LabelFrame(frm, text=tr("preflight.title"), padding=9)
        preflight.pack(fill="x", pady=(6, 8))
        self.preflight_summary_var = tk.StringVar(value=tr("preflight.checking"))
        self.preflight_save_var = tk.StringVar(
            value=tr("preflight.item_checking", label=tr("path.save_root"))
        )
        self.preflight_game_var = tk.StringVar(
            value=tr("preflight.item_checking", label=tr("path.game_root"))
        )
        self.preflight_output_var = tk.StringVar(
            value=tr("preflight.item_checking", label=tr("path.output_root"))
        )
        self.preflight_delivery_var = tk.StringVar(
            value=tr("preflight.item_checking", label=tr("path.output_bundle"))
        )
        ttk.Label(preflight, textvariable=self.preflight_summary_var, font=(GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold")).pack(anchor="w")
        preflight_grid = ttk.Frame(preflight)
        preflight_grid.pack(fill="x", pady=(4, 0))
        ttk.Label(preflight_grid, textvariable=self.preflight_save_var, wraplength=455, justify="left").grid(row=0, column=0, sticky="w", padx=(0, 18), pady=1)
        ttk.Label(preflight_grid, textvariable=self.preflight_game_var, wraplength=455, justify="left").grid(row=0, column=1, sticky="w", pady=1)
        ttk.Label(preflight_grid, textvariable=self.preflight_output_var, wraplength=455, justify="left").grid(row=1, column=0, sticky="w", padx=(0, 18), pady=1)
        ttk.Label(preflight_grid, textvariable=self.preflight_delivery_var, wraplength=455, justify="left").grid(row=1, column=1, sticky="w", pady=1)
        preflight_grid.columnconfigure(0, weight=1)
        preflight_grid.columnconfigure(1, weight=1)

        safety = ttk.LabelFrame(frm, text=tr("safety.title"), padding=10)
        safety.pack(fill="x", pady=(8, 12))
        ttk.Label(
            safety,
            text=tr("safety.body"),
            wraplength=930,
            justify="left",
        ).pack(anchor="w")

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        self.scan_btn = ttk.Button(btns, text=tr("button.scan"), command=self.start_scan)
        self.vehicle_metadata_update_btn = ttk.Button(
            btns,
            text=update_gui_text("button", get_language()),
            command=self.check_vehicle_metadata_update_gui,
        )
        action_buttons = [
            self.scan_btn,
            ttk.Button(btns, text=tr("button.open_output"), command=self.open_output),
            ttk.Button(btns, text=tr("button.recheck"), command=self.update_preflight),
            ttk.Button(btns, text=tr("button.quick_start"), command=self.show_quick_start_guide),
            ttk.Button(btns, text=tr("button.support_info"), command=self.show_support_info),
            self.vehicle_metadata_update_btn,
        ]
        for index, button in enumerate(action_buttons):
            button.pack(side="left", padx=(0 if index == 0 else 8, 0))

        # 長い翻訳では操作ボタンを2行へ自動退避し、文字切れを防ぎます。
        # 日本語 / 英語の現在レイアウトは1行のまま維持します。
        self.master.update_idletasks()
        required_button_width = sum(button.winfo_reqwidth() for button in action_buttons) + 8 * (len(action_buttons) - 1)
        if required_button_width > 940:
            for button in action_buttons:
                button.pack_forget()
            for column in range(3):
                btns.columnconfigure(column, weight=0)
            for index, button in enumerate(action_buttons):
                button.grid(
                    row=index // 3,
                    column=index % 3,
                    sticky="w",
                    padx=(0 if index % 3 == 0 else 8, 0),
                    pady=(0 if index < 3 else 6, 0),
                )

        self.update_preflight()

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.pack(fill="x", pady=(14, 8))

        self.status = tk.Text(frm, height=3, wrap="word")
        self.status.pack(fill="both", expand=True)
        self.log(tr("log.ready", app=APP_NAME, version=VERSION))
        self.log(tr("log.settings_file", path=settings_path()))

        # 翻訳が長い場合だけ必要高さへ広げます。通常の日本語 / 英語では1000×840を維持し、
        # 疑似ローカライズや将来の長い言語でもログ欄3行を潰さないようにします。
        self.master.update_idletasks()
        requested_height = self.master.winfo_reqheight()
        if requested_height > 840:
            screen_limit = max(840, self.master.winfo_screenheight() - 80)
            self.master.geometry(f"1000x{min(requested_height, screen_limit)}")

        if self._first_run:
            self.master.after(300, self.show_quick_start_guide)

    def _on_language_selected(self, *_):
        selected = self.language_var.get()
        code = self._language_codes.get(selected, DEFAULT_LANGUAGE)
        if code == self._settings_language:
            return
        self._settings_language = code
        self._save_settings_now()
        message = tr("language.saved")
        if os.environ.get("FH6_ORGANIZER_LANG"):
            message += "\n\n" + tr("language.env_override")
        messagebox.showinfo(tr("language.saved_title"), message)

    def current_settings(self) -> dict:
        return {
            # 保存する言語設定と、開発・テスト用の一時上書き
            # FH6_ORGANIZER_LANG は分離して扱います。
            "language": self._settings_language,
            "save_root": native_path_text(self.root_var.get().strip()),
            "game_root": native_path_text(self.game_root_var.get().strip()),
            "output_root": native_path_text(self.out_var.get().strip()),
            "embed_thumbnails": bool(self.copy_var.get()),
            "export_analysis_data": bool(self.analysis_var.get()),
        }

    def _schedule_save_settings(self, *_):
        if self._settings_save_job is not None:
            try:
                self.master.after_cancel(self._settings_save_job)
            except Exception:
                pass
        self._settings_save_job = self.master.after(350, self._save_settings_now)

    def _save_settings_now(self):
        self._settings_save_job = None
        try:
            save_settings(self.current_settings())
        except Exception as e:
            try:
                self.log(tr("settings.save_warning", error=e))
            except Exception:
                pass

    def _schedule_preflight_update(self, *_):
        if self._preflight_update_job is not None:
            try:
                self.master.after_cancel(self._preflight_update_job)
            except Exception:
                pass
        self._preflight_update_job = self.master.after(140, self.update_preflight)

    def _current_preflight_paths(self) -> tuple[Optional[Path], Optional[Path], Optional[Path]]:
        root_text = native_path_text(self.root_var.get().strip())
        game_text = native_path_text(self.game_root_var.get().strip())
        out_text = native_path_text(self.out_var.get().strip())
        return (
            Path(root_text) if root_text else None,
            Path(game_text) if game_text else None,
            Path(out_text) if out_text else None,
        )

    def show_quick_start_guide(self):
        existing = self._quick_start_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self.master)
        win.withdraw()
        self._quick_start_window = win
        win.title(f"{APP_NAME} — {tr('quick.title')}")
        win.minsize(680, 560)
        try:
            win.transient(self.master)
        except Exception:
            pass

        outer = ttk.Frame(win, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=tr("quick.heading"),
            font=(GUI_FONT_FAMILY, 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=tr("quick.intro"),
            wraplength=650,
            justify="left",
        ).pack(anchor="w", pady=(3, 12))

        steps = [
            (tr("quick.step1.title"), tr("quick.step1.body")),
            (tr("quick.step2.title"), tr("quick.step2.body")),
            (tr("quick.step3.title"), tr("quick.step3.body")),
            (tr("quick.step4.title"), tr("quick.step4.body")),
        ]
        for title, detail in steps:
            card = ttk.LabelFrame(outer, text=title, padding=9)
            card.pack(fill="x", pady=4)
            ttk.Label(card, text=detail, wraplength=650, justify="left").pack(anchor="w")

        current_var = tk.StringVar()
        bundle_var = tk.StringVar()
        status = ttk.LabelFrame(outer, text=tr("quick.current_settings"), padding=9)
        status.pack(fill="x", pady=(10, 4))
        ttk.Label(status, textvariable=current_var, font=(GUI_FONT_FAMILY, GUI_FONT_SIZE, "bold")).pack(anchor="w")
        ttk.Label(status, textvariable=bundle_var, wraplength=650).pack(anchor="w", pady=(3, 0))

        def refresh_status():
            result = self.update_preflight()
            marker = {
                "ready": tr("marker.ready"),
                "warning": tr("marker.warning"),
                "error": tr("marker.error"),
            }.get(result["state"], tr("marker.check"))
            current_var.set(tr("quick.preflight_status", marker=marker, summary=result["summary"]))
            bundle_var.set(tr(
                "quick.output_bundle",
                bundle=output_bundle_label(
                    embed_images=bool(self.copy_var.get()),
                    export_analysis_data=bool(self.analysis_var.get()),
                ),
            ))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text=tr("button.recheck"), command=refresh_status).pack(side="left")
        ttk.Button(buttons, text=tr("button.support_info"), command=self.show_support_info).pack(side="left", padx=(8, 0))

        def close_guide():
            self._quick_start_window = None
            win.destroy()

        ttk.Button(buttons, text=tr("button.close"), command=close_guide).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close_guide)
        refresh_status()
        win.update_idletasks()
        guide_height = max(650, min(win.winfo_reqheight(), win.winfo_screenheight() - 80))
        position_child_window(win, self.master, 800, guide_height)
        win.deiconify()
        win.lift()

    def support_info_text(self) -> str:
        scan_root, game_root, outdir = self._current_preflight_paths()
        info = support_environment_info(
            scan_root,
            game_root,
            outdir,
            embed_images=bool(self.copy_var.get()),
            export_analysis_data=bool(self.analysis_var.get()),
        )
        return format_support_environment_text(info)

    def show_support_info(self):
        win = tk.Toplevel(self.master)
        win.withdraw()
        win.title(f"{APP_NAME} — {tr('support.title')}")
        win.minsize(720, 560)
        try:
            win.transient(self.master)
        except Exception:
            pass

        outer = ttk.Frame(win, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=tr("support.title"),
            font=(GUI_FONT_FAMILY, 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=tr("support.intro"),
            wraplength=710,
            justify="left",
        ).pack(anchor="w", pady=(3, 9))

        # 環境情報やパスの長い行は折り返し、横スクロールなしでも
        # 行末まで確認できるようにします。
        text = tk.Text(outer, height=24, wrap="char")
        text.pack(fill="both", expand=True)
        text.insert("1.0", display_path_text(self.support_info_text()))
        text.configure(state="disabled")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))

        def refresh():
            content = self.support_info_text()
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", display_path_text(content))
            text.configure(state="disabled")

        def copy_info():
            content = self.support_info_text()
            try:
                self.master.clipboard_clear()
                self.master.clipboard_append(content)
                self.master.update_idletasks()
                messagebox.showinfo(APP_NAME, tr("support.copy_success"))
            except Exception as e:
                messagebox.showerror(APP_NAME, tr("support.copy_failed", error=e))

        ttk.Button(buttons, text=tr("button.refresh"), command=refresh).pack(side="left")
        ttk.Button(buttons, text=tr("button.copy_clipboard"), command=copy_info).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text=tr("button.close"), command=win.destroy).pack(side="right")
        position_child_window(win, self.master, 920, 700)
        win.deiconify()
        win.lift()

    def _show_vehicle_metadata_update_result_dialog(
        self,
        title: str,
        body: str,
        *,
        kind: str = "info",
    ) -> None:
        """更新確認結果を選択・コピーできるモーダルダイアログで表示します。"""
        win = tk.Toplevel(self.master)
        win.withdraw()
        win.title(title)
        win.minsize(700, 390)
        try:
            win.transient(self.master)
        except Exception:
            pass

        outer = ttk.Frame(win, padding=14)
        outer.pack(fill="both", expand=True)

        text_frame = ttk.Frame(outer)
        text_frame.pack(fill="both", expand=True)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        text = tk.Text(
            text_frame,
            height=16,
            wrap="none",
            padx=8,
            pady=8,
            font="TkTextFont",
            exportselection=False,
        )
        yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(text_frame, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text.insert("1.0", body)
        text.configure(state="disabled")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))

        def copy_to_clipboard(value: str) -> bool:
            try:
                self.master.clipboard_clear()
                self.master.clipboard_append(value)
                self.master.update_idletasks()
                return True
            except Exception:
                return False

        def copy_all():
            copy_to_clipboard(body)

        def select_all(_event=None):
            try:
                text.tag_add("sel", "1.0", "end-1c")
                text.mark_set("insert", "1.0")
                text.see("1.0")
            except Exception:
                pass
            return "break"

        def copy_selection(_event=None):
            try:
                selected = text.get("sel.first", "sel.last")
            except Exception:
                return "break"
            copy_to_clipboard(selected)
            return "break"

        def close_dialog():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        text.bind("<Control-a>", select_all)
        text.bind("<Control-A>", select_all)
        text.bind("<Control-c>", copy_selection)
        text.bind("<Control-C>", copy_selection)

        ttk.Button(
            buttons,
            text=tr("button.copy_clipboard"),
            command=copy_all,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text=tr("button.close"),
            command=close_dialog,
        ).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", close_dialog)
        win.bind("<Escape>", lambda _event: close_dialog())
        position_child_window(win, self.master, 860, 520)
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
            text.focus_set()
        except Exception:
            pass
        win.wait_window()

    def check_vehicle_metadata_update_gui(self):
        if self._vehicle_metadata_update_running:
            return

        self._vehicle_metadata_update_running = True
        try:
            self.vehicle_metadata_update_btn.configure(state="disabled")
        except Exception:
            pass
        self.log(update_gui_text("checking", get_language()))

        def worker():
            result, manifest_bytes = check_vehicle_metadata_update_with_manifest(
                vehicle_metadata_runtime_path(),
                DEFAULT_MANIFEST_URL,
            )
            try:
                self.master.after(
                    0,
                    self._finish_vehicle_metadata_update_check,
                    result,
                    manifest_bytes,
                )
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_vehicle_metadata_update_check(
        self,
        result,
        manifest_bytes,
    ):
        language = get_language()
        kind, title, body = gui_update_presentation(result, language)
        try:
            first_line = body.splitlines()[0] if body else title
            self.log(first_line)
        except Exception:
            pass

        if (
            result.status == STATUS_UPDATE_AVAILABLE
            and manifest_bytes is not None
        ):
            self._show_vehicle_metadata_update_result_dialog(
                title,
                body,
                kind=kind,
            )
            approved = messagebox.askyesno(
                title,
                update_gui_text("download_question", language),
                parent=self.master,
            )
            if approved:
                self.log(update_gui_text("downloading", language))

                def download_worker():
                    try:
                        state = download_and_cache_vehicle_metadata(
                            manifest_bytes,
                            default_vehicle_metadata_cache_path(),
                        )
                        error = None
                    except Exception as exc:
                        state = None
                        error = f"{type(exc).__name__}: {exc}"

                    try:
                        self.master.after(
                            0,
                            self._finish_vehicle_metadata_download,
                            state,
                            error,
                        )
                    except Exception:
                        pass

                threading.Thread(
                    target=download_worker,
                    daemon=True,
                ).start()
                return

            self._set_vehicle_metadata_update_idle()
            return

        self._set_vehicle_metadata_update_idle()

        self._show_vehicle_metadata_update_result_dialog(
            title,
            body,
            kind=kind,
        )

    def _set_vehicle_metadata_update_idle(self):
        self._vehicle_metadata_update_running = False
        try:
            self.vehicle_metadata_update_btn.configure(state="normal")
        except Exception:
            pass

    def _finish_vehicle_metadata_download(self, state, error):
        self._set_vehicle_metadata_update_idle()

        language = get_language()
        title = update_gui_text("title", language)
        if error:
            body = update_gui_text("download_failed", language)
            body += "\n\n" + str(error)
            try:
                self.log(body.splitlines()[0])
            except Exception:
                pass
            messagebox.showwarning(
                title,
                body,
                parent=self.master,
            )
            return

        body = update_gui_text("download_success", language)
        if isinstance(state, dict):
            source_updated = state.get("source_updated")
            record_count = state.get("record_count")
            if source_updated:
                body += f"\n\n{source_updated}"
            if record_count is not None:
                body += f" / {record_count}"
        try:
            self.log(body.splitlines()[0])
        except Exception:
            pass
        messagebox.showinfo(
            title,
            body,
            parent=self.master,
        )

    def update_preflight(self):
        self._preflight_update_job = None
        scan_root, game_root, outdir = self._current_preflight_paths()
        result = generator_preflight(
            scan_root,
            game_root,
            outdir,
            embed_images=bool(self.copy_var.get()),
            export_analysis_data=bool(self.analysis_var.get()),
        )
        marker = {
            "ready": tr("marker.ready"),
            "warning": tr("marker.warning"),
            "error": tr("marker.error"),
        }.get(result["state"], tr("marker.check"))
        self.preflight_summary_var.set(f"{marker}: {result['summary']}")
        variables = {
            "save": self.preflight_save_var,
            "game": self.preflight_game_var,
            "output": self.preflight_output_var,
            "delivery": self.preflight_delivery_var,
        }
        item_marker = {
            "ok": tr("marker.ready"),
            "warning": tr("marker.warning"),
            "error": tr("marker.error"),
        }
        for item in result["items"]:
            var = variables.get(item["key"])
            if var is not None:
                var.set(f"{item_marker.get(item['state'], tr('marker.check'))} {item['label']}: {item['detail']}")
        if hasattr(self, "scan_btn"):
            disabled = self._scan_running or result["state"] == "error"
            self.scan_btn.configure(state="disabled" if disabled else "normal")
        return result

    def on_close(self):
        try:
            if self._settings_save_job is not None:
                self.master.after_cancel(self._settings_save_job)
                self._settings_save_job = None
            if self._preflight_update_job is not None:
                self.master.after_cancel(self._preflight_update_job)
                self._preflight_update_job = None
            save_settings(self.current_settings())
        except Exception:
            pass
        self.master.destroy()

    def _path_row(self, parent, label, var, command):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=12).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=tr("button.browse"), command=command).pack(side="left", padx=(8, 0))

    def choose_root(self):
        p = filedialog.askdirectory(initialdir=native_path_text(self.root_var.get()) or None)
        if p:
            self.root_var.set(display_path_text(p))

    def choose_game_root(self):
        p = filedialog.askdirectory(
            initialdir=native_path_text(self.game_root_var.get()) or None
        )
        if p:
            self.game_root_var.set(display_path_text(p))

    def choose_out(self):
        p = filedialog.askdirectory(initialdir=native_path_text(self.out_var.get()) or None)
        if p:
            self.out_var.set(display_path_text(p))

    def log(self, text: str):
        self.status.insert("end", display_path_text(text) + "\n")
        self.status.see("end")

    def open_output(self):
        scan_root, _, outdir = self._current_preflight_paths()
        if outdir is None:
            messagebox.showerror(APP_NAME, tr("dialog.output_required"))
            return
        if scan_root is None:
            messagebox.showerror(APP_NAME, tr("dialog.save_root_required"))
            return
        error = output_location_error(scan_root, outdir)
        if error:
            messagebox.showerror(APP_NAME, error)
            return
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, tr("dialog.create_output_failed", error=e))
            return
        if os.name == "nt":
            os.startfile(str(outdir))
        else:
            webbrowser.open(outdir.resolve().as_uri())

    def start_scan(self):
        self._save_settings_now()
        root, game_root, out = self._current_preflight_paths()
        preflight = self.update_preflight()
        if preflight["state"] == "error":
            problems = [
                f"• {item['label']}: {item['detail']}"
                for item in preflight["items"]
                if item["state"] == "error"
            ]
            messagebox.showerror(
                APP_NAME,
                tr("preflight.problem_dialog", problems="\n".join(problems)),
            )
            return
        if root is None or out is None:
            messagebox.showerror(APP_NAME, tr("preflight.paths_required"))
            return
        try:
            ensure_safe_output_directory(root, out)
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        if preflight["state"] == "warning":
            warnings = [item["detail"] for item in preflight["items"] if item["state"] == "warning"]
            for warning in warnings:
                self.log(tr("preflight.warning_log", detail=warning))

        embed_images = bool(self.copy_var.get())
        export_analysis_data = bool(self.analysis_var.get())
        self._scan_running = True
        self.scan_btn.configure(state="disabled")
        self.progress.start(10)
        self.log(tr("log.scan_start", path=display_path_text(root)))
        self.log(tr("log.running_version", version=VERSION))
        self.log(tr(
            "log.output_bundle",
            bundle=output_bundle_label(
                embed_images=embed_images,
                export_analysis_data=export_analysis_data,
            ),
        ))

        def worker():
            try:
                records, fh6_records, stats = scan_liveries(
                    root,
                    progress=lambda text: self.master.after(0, self.log, text),
                )
                applied_stats = skip_applied_livery_reference_scan(
                    records,
                    progress=lambda text: self.master.after(0, self.log, text),
                )
                stats = dict(stats)
                stats["applied_detection"] = applied_stats
                actual_game_root = game_root
                if actual_game_root is None:
                    detected = default_game_roots()
                    actual_game_root = detected[0] if detected else None

                vehicle_db = {}
                if actual_game_root and actual_game_root.exists():
                    self.master.after(
                        0,
                        self.log,
                        tr("log.fh6_install", path=display_path_text(actual_game_root)),
                    )
                    vehicle_db = scan_vehicle_assets(
                        actual_game_root,
                        progress=lambda text: self.master.after(0, self.log, text),
                        required_car_ids={int(record.car_id) for record in [*records, *fh6_records]},
                    )
                    enrich_records_with_vehicle_info(records, vehicle_db)
                    enrich_records_with_vehicle_info(fh6_records, vehicle_db)
                    if export_analysis_data:
                        write_vehicle_database(vehicle_db, out / "data")
                else:
                    self.master.after(0, self.log, tr("log.fh6_install_missing"))

                report = write_report(
                    root,
                    records,
                    stats,
                    out,
                    embed_images=embed_images,
                    game_root=actual_game_root,
                    vehicle_db=vehicle_db,
                    export_analysis_data=export_analysis_data,
                    fh6_records=fh6_records,
                )
                stats = dict(stats)
                stats["vehicle_db_count"] = len(vehicle_db)
                self.master.after(
                    0,
                    self.done,
                    report,
                    stats,
                    embed_images,
                    export_analysis_data,
                )
            except Exception as e:
                self.master.after(0, self.failed, e)

        threading.Thread(target=worker, daemon=True).start()

    def show_report_complete_dialog(self, message: str):
        """メイン画面と同じ読みやすいGUIフォントでレポート生成完了を表示します。"""
        win = tk.Toplevel(self.master)
        win.withdraw()
        win.title(f"{APP_NAME} — {tr('complete.title')}")
        win.minsize(650, 390)
        try:
            win.transient(self.master)
        except Exception:
            pass

        outer = ttk.Frame(win, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=tr("complete.heading", version=VERSION),
            font=(GUI_FONT_FAMILY, 14, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        body = tk.Text(
            outer,
            height=15,
            wrap="char",
            borderwidth=0,
            highlightthickness=0,
            padx=2,
            pady=2,
            font=(GUI_FONT_FAMILY, GUI_FONT_SIZE),
        )
        body.pack(fill="both", expand=True)
        body.insert("1.0", display_path_text(message))
        body.configure(state="disabled", cursor="arrow")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))

        def close_dialog():
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        ttk.Button(buttons, text="OK", command=close_dialog).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close_dialog)
        position_child_window(win, self.master, 760, 470)
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
            win.focus_force()
        except Exception:
            pass

    def done(
        self,
        report: Path,
        stats: dict,
        embed_images: bool,
        export_analysis_data: bool,
    ):
        self.progress.stop()
        self._scan_running = False
        self.update_preflight()
        self.log(tr(
            "log.complete",
            folders=stats["raw_livery_folders"],
            paints=stats["unique_liveries"],
            vehicles=stats["unique_car_ids"],
            vehicle_db=stats.get("vehicle_db_count", 0),
        ))
        self.log(f"HTML: {display_path_text(report)}")
        excel_path = report.parent / "livery-organizer-for-fh6.xlsx"
        if excel_path.exists():
            self.log(f"Excel: {display_path_text(excel_path)}")
        if stats.get("analysis_data_exported"):
            self.log(tr("log.analysis_path", path=display_path_text(report.parent / "data")))
        else:
            self.log(tr("log.analysis_not_exported"))
        self.log(tr(
            "log.generated",
            bundle=output_bundle_label(
                embed_images=embed_images,
                export_analysis_data=export_analysis_data,
            ),
        ))
        self.log(tr("log.portable_embedded") if embed_images else tr("log.portable_external"))
        try:
            cache_marker = datetime.now().strftime("%Y%m%d%H%M%S%f")
            webbrowser.open_new_tab(
                report.resolve().as_uri() + f"#build={VERSION}-{cache_marker}"
            )
        except Exception:
            try:
                webbrowser.open(report.resolve().as_uri())
            except Exception:
                pass
        bundle_lines = [
            f"• {label}: {display_path_text(path)}"
            for label, path in output_bundle_entries(
                report.parent,
                embed_images=embed_images,
                export_analysis_data=export_analysis_data,
            )
        ]
        self.show_report_complete_dialog(
            tr("complete.items", items="\n".join(bundle_lines))
            + "\n\n"
            + tr("complete.next_steps")
            + "\n\n"
            + tr("complete.source_unchanged")
        )

    def failed(self, e: Exception):
        self.progress.stop()
        self._scan_running = False
        self.update_preflight()
        self.log(tr("log.error_type", name=type(e).__name__))
        self.log(tr("log.error", error=repr(e)))
        self.log(tr("log.traceback"))
        self.log("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        messagebox.showerror(APP_NAME, tr("dialog.scan_failed", name=type(e).__name__, error=e))


class LocalizedArgumentParser(argparse.ArgumentParser):
    """Localize argparse's built-in headings without external dependencies."""

    def format_help(self) -> str:
        text = super().format_help()
        return (
            text.replace("usage:", tr("cli.usage_prefix"), 1)
            .replace("options:", tr("cli.options_prefix"), 1)
            .replace("show this help message and exit", tr("cli.help_builtin"))
        )


def build_parser() -> argparse.ArgumentParser:
    p = LocalizedArgumentParser(
        description=tr("cli.description", version=VERSION)
    )
    p.add_argument(
        "--root",
        type=Path,
        help=tr("cli.root_help"),
    )
    p.add_argument("--out", type=Path, help=tr("cli.out_help"))
    p.add_argument(
        "--game-root",
        type=Path,
        help=tr("cli.game_root_help"),
    )
    p.add_argument(
        "--print-default-game-roots",
        action="store_true",
        help=tr("cli.print_game_roots_help"),
    )
    p.add_argument(
        "--no-embed-images",
        "--no-copy-images",
        dest="no_embed_images",
        action="store_true",
        help=tr("cli.no_embed_help"),
    )
    p.add_argument(
        "--export-analysis-data",
        action="store_true",
        help=tr("cli.export_analysis_help"),
    )
    p.add_argument(
        "--environment-check",
        action="store_true",
        help=tr("cli.environment_check_help"),
    )
    p.add_argument(
        "--inspect-vehicle-assets",
        action="store_true",
        help=tr("cli.inspect_assets_help"),
    )
    p.add_argument(
        "--check-vehicle-metadata-update",
        action="store_true",
        help=update_cli_text("check_help", get_language()),
    )
    p.add_argument(
        "--vehicle-metadata-manifest-url",
        help=update_cli_text("url_help", get_language()),
    )
    p.add_argument(
        "--cli",
        action="store_true",
        help=tr("cli.cli_help"),
    )
    p.add_argument(
        "--print-default-roots",
        action="store_true",
        help=tr("cli.print_roots_help"),
    )
    return p


def main() -> int:
    initialize_ui_language()
    args = build_parser().parse_args()

    if args.check_vehicle_metadata_update:
        manifest_url = str(args.vehicle_metadata_manifest_url or "").strip()
        if not manifest_url:
            print(
                update_cli_text("url_required", get_language()),
                file=sys.stderr,
            )
            return 2
        result = check_vehicle_metadata_update(
            vehicle_metadata_runtime_path(),
            manifest_url,
        )
        print(format_update_check_result(result, get_language()))
        if result.status in {STATUS_CHECK_FAILED, STATUS_INCOMPATIBLE}:
            return 2
        return 0

    if args.print_default_game_roots:
        roots = default_game_roots()
        if not roots:
            print(
                tr("cli.no_game_roots"),
                file=sys.stderr,
            )
            return 1
        for path in roots:
            print(path)
        return 0

    if args.print_default_roots:
        roots = default_roots()
        if not roots:
            print(tr("cli.no_save_roots"), file=sys.stderr)
            return 1
        for p in roots:
            print(p)
        return 0

    if args.inspect_vehicle_assets:
        saved = load_settings()
        game_roots = default_game_roots()
        saved_game_root = str(saved.get("game_root") or "").strip()
        game_root = args.game_root or (Path(saved_game_root) if saved_game_root else (game_roots[0] if game_roots else None))
        if game_root is None or not game_root.exists() or not game_root.is_dir():
            print(
                tr("cli.inspect_game_root_required"),
                file=sys.stderr,
            )
            return 2
        print(tr("cli.inspect_intro"))
        vehicle_db, empty_archives, problems = inspect_vehicle_asset_archives(
            game_root,
            progress=lambda msg: print(msg, flush=True),
        )
        print()
        print(
            format_vehicle_asset_problems(
                game_root, vehicle_db, empty_archives, problems
            )
        )
        return 0

    if args.environment_check:
        saved = load_settings()
        roots = default_roots()
        game_roots = default_game_roots()
        saved_root = str(saved.get("save_root") or "").strip()
        saved_game_root = str(saved.get("game_root") or "").strip()
        saved_output = normalize_legacy_output_root(saved.get("output_root"))
        scan_root = args.root or (Path(saved_root) if saved_root else (roots[0] if roots else None))
        game_root = args.game_root or (Path(saved_game_root) if saved_game_root else (game_roots[0] if game_roots else None))
        outdir = args.out or (Path(saved_output) if saved_output else (Path.home() / "Documents" / DEFAULT_REPORT_DIR_NAME))
        embed_images = not args.no_embed_images if args.no_embed_images else bool(saved.get("embed_thumbnails", saved.get("copy_thumbnails", True)))
        export_analysis_data = bool(args.export_analysis_data or saved.get("export_analysis_data", False))
        info = support_environment_info(
            scan_root,
            game_root,
            outdir,
            embed_images=embed_images,
            export_analysis_data=export_analysis_data,
        )
        print(format_support_environment_text(info))
        return 2 if info["preflight"]["state"] == "error" else 0

    if not args.cli and args.root is None:
        if tk is None:
            print(tr("cli.gui_unavailable"), file=sys.stderr)
            return 2
        root = tk.Tk()
        apply_app_icon(root)
        App(root)
        root.mainloop()
        return 0

    scan_root = args.root
    if scan_root is None:
        roots = default_roots()
        if not roots:
            print(tr("cli.root_required"), file=sys.stderr)
            return 2
        scan_root = roots[0]

    out = args.out or (Path.home() / "Documents" / DEFAULT_REPORT_DIR_NAME)

    if not scan_root.exists():
        print(tr("cli.root_not_found", path=display_path_text(scan_root)), file=sys.stderr)
        return 2

    try:
        ensure_safe_output_directory(scan_root, out)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    report = scan_and_report(
        scan_root,
        out,
        embed_images=not args.no_embed_images,
        verbose=True,
        game_root=args.game_root,
        export_analysis_data=args.export_analysis_data,
    )
    try:
        webbrowser.open(report.resolve().as_uri())
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
