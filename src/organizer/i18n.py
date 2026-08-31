"""Livery Organizer for FH6 の国際化ヘルパー。

外部Pythonパッケージには依存しません。翻訳キーの欠落や未対応言語があっても
現在のUIが利用不能にならないよう、日本語を常にフォールバック言語として扱います。
"""
from __future__ import annotations

from typing import Mapping

try:
    from .locales.en import STRINGS as EN_STRINGS
    from .locales.ja import STRINGS as JA_STRINGS
except ImportError:  # src/organizer から直接実行する場合。
    from locales.en import STRINGS as EN_STRINGS
    from locales.ja import STRINGS as JA_STRINGS

DEFAULT_LANGUAGE = "ja"
SUPPORTED_LANGUAGES: Mapping[str, str] = {
    "ja": "日本語",
    "en": "English",
}

_TRANSLATIONS = {
    "ja": JA_STRINGS,
    "en": EN_STRINGS,
}
_current_language = DEFAULT_LANGUAGE


def normalize_language(value: object) -> str:
    """言語指定を対応済み2文字コードへ正規化し、未対応時は日本語を返します。"""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return DEFAULT_LANGUAGE
    primary = text.split("-", 1)[0]
    return primary if primary in _TRANSLATIONS else DEFAULT_LANGUAGE


def set_language(value: object) -> str:
    """プロセス全体のUI言語を設定し、正規化後のコードを返します。"""
    global _current_language
    _current_language = normalize_language(value)
    return _current_language


def get_language() -> str:
    """現在のUI言語コードを返します。"""
    return _current_language


def available_languages() -> tuple[tuple[str, str], ...]:
    """対応言語を ``(コード, 表示名)`` の組で返します。"""
    return tuple(SUPPORTED_LANGUAGES.items())


def tr(key: str, /, **kwargs: object) -> str:
    """翻訳キーを取得し、必要なら ``str.format`` で値を埋め込みます。"""
    table = _TRANSLATIONS.get(_current_language, JA_STRINGS)
    template = table.get(key, JA_STRINGS.get(key, key))
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        # 翻訳側の書式ミスがあってもOrganizerの起動を妨げません。
        return template
