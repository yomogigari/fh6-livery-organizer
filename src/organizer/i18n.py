"""Livery Organizer for FH6 の国際化ヘルパー。

外部Pythonパッケージには依存しません。翻訳キーの欠落や未対応言語があっても
現在のUIが利用不能にならないよう、日本語を常にフォールバック言語として扱います。
"""
from __future__ import annotations

from string import Formatter
from typing import Mapping
import math


try:
    from .locales.en import STRINGS as EN_STRINGS
    from .locales.ja import STRINGS as JA_STRINGS
except ImportError:  # src/organizer から直接実行する場合。
    from locales.en import STRINGS as EN_STRINGS
    from locales.ja import STRINGS as JA_STRINGS

DEFAULT_LANGUAGE = "ja"
PSEUDO_LANGUAGE = "qps"
SUPPORTED_LANGUAGES: Mapping[str, str] = {
    "ja": "日本語",
    "en": "English",
}

_TRANSLATIONS = {
    "ja": JA_STRINGS,
    "en": EN_STRINGS,
}
_current_language = DEFAULT_LANGUAGE

_PSEUDO_TRANSLATION = str.maketrans({
    "A": "Å", "B": "Ɓ", "C": "Ç", "D": "Ð", "E": "Ë", "F": "Ƒ", "G": "Ĝ",
    "H": "Ĥ", "I": "Ï", "J": "Ĵ", "K": "Ķ", "L": "Ŀ", "M": "Ṁ", "N": "Ñ",
    "O": "Ö", "P": "Þ", "Q": "Ɋ", "R": "Ŗ", "S": "Š", "T": "Ţ", "U": "Ü",
    "V": "Ṽ", "W": "Ŵ", "X": "Ẍ", "Y": "Ÿ", "Z": "Ž",
    "a": "å", "b": "ƀ", "c": "ç", "d": "ð", "e": "ë", "f": "ƒ", "g": "ĝ",
    "h": "ĥ", "i": "ï", "j": "ĵ", "k": "ķ", "l": "ŀ", "m": "ṁ", "n": "ñ",
    "o": "ö", "p": "þ", "q": "ɋ", "r": "ŗ", "s": "š", "t": "ţ", "u": "ü",
    "v": "ṽ", "w": "ŵ", "x": "ẍ", "y": "ÿ", "z": "ž",
})


def _pseudo_literal(text: str) -> str:
    """英語のリテラル部分を長文化し、未変換箇所を目視しやすくします。"""
    if not text:
        return text
    accented = text.translate(_PSEUDO_TRANSLATION)
    visible = sum(1 for ch in text if ch.isalnum())
    padding = max(2, math.ceil(visible * 0.35)) if visible else 0
    return accented + ((" " + "·" * padding) if padding else "")


def pseudo_localize(template: str) -> str:
    """英語テンプレートを開発用疑似ロケールへ変換します。

    ``str.format`` のフィールドは変換せず保持するため、パス・車名・件数など
    実データを埋め込んだ後も利用者データ自体は疑似変換されません。
    """
    parts: list[str] = []
    for literal, field_name, format_spec, conversion in Formatter().parse(str(template)):
        parts.append(_pseudo_literal(literal))
        if field_name is not None:
            field = "{" + field_name
            if conversion:
                field += "!" + conversion
            if format_spec:
                field += ":" + format_spec
            field += "}"
            parts.append(field)
    return "⟦" + "".join(parts) + "⟧"


def normalize_language(value: object) -> str:
    """言語指定を対応済み2文字コードへ正規化し、未対応時は日本語を返します。"""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return DEFAULT_LANGUAGE
    primary = text.split("-", 1)[0]
    if primary == PSEUDO_LANGUAGE:
        return PSEUDO_LANGUAGE
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
    """利用者が選択できる言語を ``(コード, 表示名)`` の組で返します。

    ``qps`` はレイアウト検証専用なので通常の言語選択には表示しません。
    """
    return tuple(SUPPORTED_LANGUAGES.items())


def language_display_name(code: str) -> str:
    """言語選択欄へ表示する名称を返します。疑似言語は開発時だけ表示します。"""
    normalized = normalize_language(code)
    if normalized == PSEUDO_LANGUAGE:
        return pseudo_localize("Pseudo localization (development only)")
    return SUPPORTED_LANGUAGES.get(normalized, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])


def tr(key: str, /, **kwargs: object) -> str:
    """翻訳キーを取得し、必要なら ``str.format`` で値を埋め込みます。"""
    if _current_language == PSEUDO_LANGUAGE:
        base = EN_STRINGS.get(key, JA_STRINGS.get(key, key))
        template = pseudo_localize(base)
    else:
        table = _TRANSLATIONS.get(_current_language, JA_STRINGS)
        template = table.get(key, JA_STRINGS.get(key, key))
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        # 翻訳側の書式ミスがあってもOrganizerの起動を妨げません。
        return template
