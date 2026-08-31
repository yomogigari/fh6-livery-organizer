"""Localization helpers for Livery Organizer for FH6.

This module intentionally has no third-party dependencies.  Japanese remains the
fallback language so an incomplete or invalid locale can never make the current
UI less usable.
"""
from __future__ import annotations

from typing import Mapping

try:
    from .locales.en import STRINGS as EN_STRINGS
    from .locales.ja import STRINGS as JA_STRINGS
except ImportError:  # Direct execution from src/organizer.
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
    """Return a supported two-letter language code, falling back to Japanese."""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return DEFAULT_LANGUAGE
    primary = text.split("-", 1)[0]
    return primary if primary in _TRANSLATIONS else DEFAULT_LANGUAGE


def set_language(value: object) -> str:
    """Set the process-wide UI language and return the normalized code."""
    global _current_language
    _current_language = normalize_language(value)
    return _current_language


def get_language() -> str:
    return _current_language


def available_languages() -> tuple[tuple[str, str], ...]:
    return tuple(SUPPORTED_LANGUAGES.items())


def tr(key: str, /, **kwargs: object) -> str:
    """Translate *key* with Japanese fallback and optional ``str.format`` values."""
    table = _TRANSLATIONS.get(_current_language, JA_STRINGS)
    template = table.get(key, JA_STRINGS.get(key, key))
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        # Translation mistakes must not prevent the Organizer from starting.
        return template
