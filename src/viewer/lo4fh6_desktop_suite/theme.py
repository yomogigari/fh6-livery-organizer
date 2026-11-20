"""TkinterとWebView2へ共通適用するデザイントークン。"""
from __future__ import annotations

PALETTES = {
    'light': {
        'background': '#f5f7fa', 'surface': '#ffffff', 'text': '#202a38',
        'muted': '#556579', 'outline': '#cbd4df', 'accent': '#315fa6',
        'accent_text': '#ffffff', 'error': '#a92b37',
    },
    'dark': {
        'background': '#10161e', 'surface': '#19232f', 'text': '#e9edf6',
        'muted': '#a9b6c9', 'outline': '#394657', 'accent': '#5688cb',
        'accent_text': '#ffffff', 'error': '#ffb5b5',
    },
}


def theme_tokens(theme: str, *, system_is_dark: bool | None = None) -> dict[str, str]:
    """systemはOSがダークか判定できるクライアントが渡す。未判定ならライトで安全に表示。"""
    if theme not in ('system', 'light', 'dark'):
        raise ValueError('未対応のテーマです')
    chosen = ('dark' if system_is_dark else 'light') if theme == 'system' else theme
    return dict(PALETTES[chosen])


def webview_css_variables(theme: str, *, system_is_dark: bool | None = None) -> str:
    values = theme_tokens(theme, system_is_dark=system_is_dark)
    return ':root{' + ';'.join(f'--suite-{k.replace("_", "-")}:{v}' for k, v in values.items()) + '}'
