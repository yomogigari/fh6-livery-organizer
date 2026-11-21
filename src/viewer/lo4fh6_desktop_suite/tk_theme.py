"""Tkinter の画面へ、Viewer と同じ配色・文字・余白を当てる（Livery Organizer for FH6・Navigator Bridge for FH6 共通）。

配色は Viewer の設定画面と同じ theme.PALETTES（ライト・ダーク）。文字・余白・枠は
tools/livery-inspector/lo4fh6-ui.css の値に合わせる（Segoe UI、本文 12px、ボタンの内側の余白 5px・11px、
枠 1px）。Tk の ttk は角を丸められないので、角は四角のまま、枠の色と太さを合わせる。

使い方：
    from lo4fh6_desktop_suite.tk_theme import apply_tk_theme
    palette = apply_tk_theme(root, 'system')      # 起動直後、部品を作る前に呼ぶ
    apply_tk_theme(root, 'dark')                  # 切り替え時。作成済みの tk の部品も塗り直す
強調のボタンは style='Accent.TButton'、補足の文字は style='Muted.TLabel'。
"""
from __future__ import annotations

import sys
from typing import Any

from .theme import PALETTES

# lo4fh6-ui.css に合わせた値（96 dpi で 15px ≒ 11 ポイント、13px ≒ 10 ポイント）。
# 2026-11-21：全体的に文字が小さいという指摘で、本文 9 → 11 ポイント（約 2 割大きく）にした。
FONT_CANDIDATES = ('Segoe UI Variable', 'Segoe UI', 'Yu Gothic UI')
MONO_FONT_CANDIDATES = ('Cascadia Mono', 'Consolas', 'MS Gothic')
FONT_SIZE_BODY = 11
FONT_SIZE_SMALL = 10
FONT_SIZE_HEADING = 13
FONT_SIZE_MONO = 11
BUTTON_PADDING = (11, 5)
INPUT_PADDING = (8, 5)
FRAME_PADDING = 8
BORDER_WIDTH = 1
TTK_BASE_THEME = 'clam'  # 色を自由に指定できる標準の ttk のテーマ

# tk（ttk でない）の部品ごとの塗り分け。作成済みの部品の塗り直しにも使う。
_TK_WIDGET_ROLES = {
    'Tk': 'window', 'Toplevel': 'window', 'Frame': 'window', 'Labelframe': 'window', 'Canvas': 'window',
    'Label': 'label', 'Message': 'label',
    'Text': 'field', 'Listbox': 'field', 'Entry': 'field', 'Spinbox': 'field',
    'Button': 'button', 'Checkbutton': 'check', 'Radiobutton': 'check', 'Scale': 'window',
    'Menu': 'menu', 'Menubutton': 'button', 'PanedWindow': 'window', 'Scrollbar': 'window',
}


def system_prefers_dark() -> bool | None:
    """Windows の「アプリのモード」がダークなら True。判定できなければ None。"""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return int(value) == 0
    except OSError:
        return None


def resolve_theme(theme: str, *, system_is_dark: bool | None = None) -> str:
    """'system'・'light'・'dark' を、実際に使う 'light' か 'dark' にする。"""
    if theme not in ('system', 'light', 'dark'):
        raise ValueError('未対応のテーマです')
    if theme != 'system':
        return theme
    dark = system_prefers_dark() if system_is_dark is None else system_is_dark
    return 'dark' if dark else 'light'


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * ratio):02x}' for x, y in zip(a, b))


def tk_palette(theme: str, *, system_is_dark: bool | None = None) -> dict[str, str]:
    """theme.PALETTES に、Tk の部品に要る色（ボタンの上に乗ったとき・押したとき・選択・無効）を足す。"""
    name = resolve_theme(theme, system_is_dark=system_is_dark)
    p = dict(PALETTES[name])
    p['name'] = name
    p['control'] = p['surface']
    p['control_hover'] = _mix(p['surface'], p['accent'], 0.14)
    p['control_pressed'] = _mix(p['surface'], p['accent'], 0.26)
    p['accent_hover'] = _mix(p['accent'], p['text'], 0.12)
    p['selection'] = p['accent']
    p['selection_text'] = p['accent_text']
    p['disabled_text'] = _mix(p['muted'], p['background'], 0.35)
    p['trough'] = _mix(p['background'], p['outline'], 0.5)
    return p


def _preferred_family(root, candidates: tuple[str, ...], fallback: str) -> str:
    try:
        from tkinter import font as tkfont
        available = {name.casefold(): name for name in tkfont.families(root)}
    except Exception:  # noqa: BLE001  文字の一覧を取れなくても、標準の文字で続ける
        return fallback
    for name in candidates:
        if name.casefold() in available:
            return available[name.casefold()]
    return fallback


def configure_fonts(root) -> dict[str, tuple[str, int, str]]:
    """Tk の名前付きの文字（TkDefaultFont など）を、Viewer と同じ大きさにする。"""
    from tkinter import font as tkfont
    try:
        default_family = str(tkfont.nametofont('TkDefaultFont', root=root).actual('family'))
        fixed_family = str(tkfont.nametofont('TkFixedFont', root=root).actual('family'))
    except Exception:  # noqa: BLE001
        default_family, fixed_family = 'TkDefaultFont', 'TkFixedFont'
    family = _preferred_family(root, FONT_CANDIDATES, default_family)
    mono = _preferred_family(root, MONO_FONT_CANDIDATES, fixed_family)
    specs = {
        'TkDefaultFont': (family, FONT_SIZE_BODY, 'normal'),
        'TkTextFont': (family, FONT_SIZE_BODY, 'normal'),
        'TkMenuFont': (family, FONT_SIZE_BODY, 'normal'),
        'TkHeadingFont': (family, FONT_SIZE_BODY, 'bold'),
        'TkCaptionFont': (family, FONT_SIZE_HEADING, 'bold'),
        'TkSmallCaptionFont': (family, FONT_SIZE_SMALL, 'normal'),
        'TkIconFont': (family, FONT_SIZE_BODY, 'normal'),
        'TkTooltipFont': (family, FONT_SIZE_SMALL, 'normal'),
        'TkFixedFont': (mono, FONT_SIZE_MONO, 'normal'),
    }
    for name, (fam, size, weight) in specs.items():
        try:
            tkfont.nametofont(name, root=root).configure(family=fam, size=size, weight=weight)
        except Exception:  # noqa: BLE001  無い名前付きの文字は飛ばす
            pass
    return specs


def _configure_ttk(style, p: dict[str, str]) -> None:
    common = dict(background=p['background'], foreground=p['text'], bordercolor=p['outline'],
                  lightcolor=p['outline'], darkcolor=p['outline'], troughcolor=p['trough'],
                  fieldbackground=p['control'], selectbackground=p['selection'],
                  selectforeground=p['selection_text'], insertcolor=p['text'],
                  focuscolor=p['accent'], arrowcolor=p['text'], font='TkDefaultFont')
    style.configure('.', **common)
    style.map('.', foreground=[('disabled', p['disabled_text'])],
              fieldbackground=[('disabled', p['background'])])

    style.configure('TFrame', background=p['background'])
    style.configure('Card.TFrame', background=p['surface'], bordercolor=p['outline'], relief='solid',
                    borderwidth=BORDER_WIDTH)
    style.configure('TLabel', background=p['background'], foreground=p['text'])
    style.configure('Muted.TLabel', background=p['background'], foreground=p['muted'])
    style.configure('Heading.TLabel', background=p['background'], foreground=p['text'], font='TkCaptionFont')
    style.configure('Error.TLabel', background=p['background'], foreground=p['error'])
    style.configure('TLabelframe', background=p['background'], bordercolor=p['outline'],
                    lightcolor=p['outline'], darkcolor=p['outline'], borderwidth=BORDER_WIDTH,
                    relief='solid', padding=FRAME_PADDING)
    style.configure('TLabelframe.Label', background=p['background'], foreground=p['muted'],
                    font='TkHeadingFont')
    style.configure('TSeparator', background=p['outline'])

    style.configure('TButton', background=p['control'], foreground=p['text'], bordercolor=p['outline'],
                    lightcolor=p['control'], darkcolor=p['control'], borderwidth=BORDER_WIDTH,
                    relief='solid', padding=BUTTON_PADDING, anchor='center', font='TkDefaultFont')
    style.map('TButton',
              background=[('disabled', p['background']), ('pressed', p['control_pressed']),
                          ('active', p['control_hover'])],
              bordercolor=[('focus', p['accent']), ('active', p['accent'])],
              lightcolor=[('pressed', p['control_pressed']), ('active', p['control_hover'])],
              darkcolor=[('pressed', p['control_pressed']), ('active', p['control_hover'])],
              foreground=[('disabled', p['disabled_text'])])
    style.configure('Accent.TButton', background=p['accent'], foreground=p['accent_text'],
                    bordercolor=p['accent'], lightcolor=p['accent'], darkcolor=p['accent'])
    style.map('Accent.TButton',
              background=[('disabled', p['background']), ('pressed', p['accent_hover']),
                          ('active', p['accent_hover'])],
              lightcolor=[('pressed', p['accent_hover']), ('active', p['accent_hover'])],
              darkcolor=[('pressed', p['accent_hover']), ('active', p['accent_hover'])],
              bordercolor=[('focus', p['text'])],
              foreground=[('disabled', p['disabled_text'])])

    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, fieldbackground=p['control'], foreground=p['text'], bordercolor=p['outline'],
                        lightcolor=p['control'], darkcolor=p['control'], padding=INPUT_PADDING,
                        insertcolor=p['text'], arrowcolor=p['text'], background=p['control'])
        style.map(name, bordercolor=[('focus', p['accent'])],
                  lightcolor=[('focus', p['accent'])], darkcolor=[('focus', p['accent'])],
                  fieldbackground=[('readonly', p['control']), ('disabled', p['background'])],
                  foreground=[('disabled', p['disabled_text'])])

    for name in ('TCheckbutton', 'TRadiobutton'):
        style.configure(name, background=p['background'], foreground=p['text'],
                        indicatorbackground=p['control'], indicatorforeground=p['accent_text'],
                        upperbordercolor=p['outline'], lowerbordercolor=p['outline'], padding=(2, 3))
        style.map(name, indicatorbackground=[('selected', p['accent']), ('pressed', p['control_pressed'])],
                  background=[('active', p['background'])],
                  foreground=[('disabled', p['disabled_text'])])

    style.configure('TNotebook', background=p['background'], bordercolor=p['outline'],
                    lightcolor=p['outline'], darkcolor=p['outline'], tabmargins=(0, 4, 0, 0))
    style.configure('TNotebook.Tab', background=p['background'], foreground=p['muted'],
                    bordercolor=p['outline'], lightcolor=p['background'], darkcolor=p['background'],
                    padding=(12, 5))
    style.map('TNotebook.Tab',
              background=[('selected', p['surface']), ('active', p['control_hover'])],
              foreground=[('selected', p['text'])],
              lightcolor=[('selected', p['surface'])])

    style.configure('Treeview', background=p['control'], fieldbackground=p['control'], foreground=p['text'],
                    bordercolor=p['outline'], lightcolor=p['control'], darkcolor=p['control'])
    style.map('Treeview', background=[('selected', p['selection'])],
              foreground=[('selected', p['selection_text'])])
    style.configure('Treeview.Heading', background=p['surface'], foreground=p['muted'],
                    bordercolor=p['outline'], lightcolor=p['surface'], darkcolor=p['surface'],
                    font='TkHeadingFont', padding=(6, 4))
    style.map('Treeview.Heading', background=[('active', p['control_hover'])])

    for orient in ('Vertical', 'Horizontal'):
        style.configure(f'{orient}.TScrollbar', background=p['surface'], troughcolor=p['background'],
                        bordercolor=p['background'], lightcolor=p['surface'], darkcolor=p['surface'],
                        arrowcolor=p['muted'])
        style.map(f'{orient}.TScrollbar', background=[('active', p['control_hover'])])
    style.configure('Horizontal.TProgressbar', background=p['accent'], troughcolor=p['trough'],
                    bordercolor=p['outline'], lightcolor=p['accent'], darkcolor=p['accent'])
    style.configure('TScale', background=p['accent'], troughcolor=p['trough'])
    style.configure('TPanedwindow', background=p['background'])
    style.configure('Sash', sashthickness=4, gripcount=0, background=p['outline'])


def _tk_options(role: str, p: dict[str, str]) -> dict[str, Any]:
    if role == 'window':
        return {'background': p['background']}
    if role == 'label':
        return {'background': p['background'], 'foreground': p['text']}
    if role == 'field':
        return {'background': p['control'], 'foreground': p['text'], 'insertbackground': p['text'],
                'selectbackground': p['selection'], 'selectforeground': p['selection_text'],
                'highlightbackground': p['outline'], 'highlightcolor': p['accent']}
    if role == 'button':
        return {'background': p['control'], 'foreground': p['text'], 'activebackground': p['control_hover'],
                'activeforeground': p['text'], 'highlightbackground': p['outline']}
    if role == 'check':
        return {'background': p['background'], 'foreground': p['text'], 'activebackground': p['background'],
                'activeforeground': p['text'], 'selectcolor': p['control']}
    if role == 'menu':
        return {'background': p['surface'], 'foreground': p['text'], 'activebackground': p['selection'],
                'activeforeground': p['selection_text']}
    return {}


def _option_database(root, p: dict[str, str]) -> None:
    """これから作る tk の部品の既定の色（option データベース）。"""
    for pattern, value in (
        ('*Background', p['background']), ('*Foreground', p['text']),
        ('*selectBackground', p['selection']), ('*selectForeground', p['selection_text']),
        ('*insertBackground', p['text']), ('*highlightBackground', p['outline']),
        ('*highlightColor', p['accent']), ('*activeBackground', p['control_hover']),
        ('*activeForeground', p['text']),
        ('*Text.Background', p['control']), ('*Listbox.Background', p['control']),
        ('*Entry.Background', p['control']), ('*Spinbox.Background', p['control']),
        ('*Menu.Background', p['surface']), ('*Menu.activeBackground', p['selection']),
        ('*Menu.activeForeground', p['selection_text']),
        ('*TCombobox*Listbox.background', p['control']), ('*TCombobox*Listbox.foreground', p['text']),
        ('*TCombobox*Listbox.selectBackground', p['selection']),
        ('*TCombobox*Listbox.selectForeground', p['selection_text']),
    ):
        root.option_add(pattern, value, 'widgetDefault')


def recolor_tk_widgets(widget, p: dict[str, str]) -> int:
    """作成済みの tk（ttk でない）の部品を塗り直す。塗り直した数を返す。

    部品が独自の色を持つ場合（属性 lo4fh6_keep_colors が真）は飛ばす。
    """
    count = 0
    stack = [widget]
    while stack:
        item = stack.pop()
        stack.extend(item.winfo_children())
        if getattr(item, 'lo4fh6_keep_colors', False):
            continue
        role = _TK_WIDGET_ROLES.get(item.winfo_class())
        if not role:
            continue
        options = _tk_options(role, p)
        try:
            valid = set(item.keys())
        except Exception:  # noqa: BLE001
            continue
        applied = {k: v for k, v in options.items() if k in valid}
        if applied:
            try:
                item.configure(**applied)
                count += 1
            except Exception:  # noqa: BLE001  設定できない部品は飛ばす
                pass
    return count


def apply_title_bar(window, dark: bool) -> bool:
    """Windows 10 以降で、ウィンドウの枠（タイトルバー）もダークにする。できなければ False。"""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE（新しい番号・古い番号）
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                return True
    except Exception:  # noqa: BLE001  古い Windows では何もしない
        return False
    return False


def apply_tk_theme(root, theme: str = 'system', *, system_is_dark: bool | None = None,
                   fonts: bool = True) -> dict[str, str]:
    """ttk のスタイル・tk の部品の色・名前付きの文字・タイトルバーをまとめて当て、使った色を返す。"""
    from tkinter import ttk
    p = tk_palette(theme, system_is_dark=system_is_dark)
    if fonts:
        configure_fonts(root)
    style = ttk.Style(root)
    if TTK_BASE_THEME in style.theme_names() and style.theme_use() != TTK_BASE_THEME:
        style.theme_use(TTK_BASE_THEME)
    _configure_ttk(style, p)
    _option_database(root, p)
    recolor_tk_widgets(root, p)
    apply_title_bar(root, p['name'] == 'dark')
    try:
        for child in root.winfo_children():
            if child.winfo_class() == 'Toplevel':
                apply_title_bar(child, p['name'] == 'dark')
    except Exception:  # noqa: BLE001
        pass
    return p
