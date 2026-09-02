"""Livery Organizer for FH6 の国際化ヘルパー。

外部Pythonパッケージには依存しません。翻訳キーの欠落や未対応言語があっても
現在のUIが利用不能にならないよう、日本語を常にフォールバック言語として扱います。
"""
from __future__ import annotations

from string import Formatter
from typing import Mapping
import json
import math


try:
    from .locales.en import (
        LANGUAGE_CODE as EN_LANGUAGE_CODE,
        LANGUAGE_NAME as EN_LANGUAGE_NAME,
        REPORT_ATTR as EN_REPORT_ATTR,
        REPORT_DYNAMIC_RULES_JS as EN_REPORT_DYNAMIC_RULES_JS,
        REPORT_FRAGMENTS_JS as EN_REPORT_FRAGMENTS_JS,
        REPORT_LOCALE as EN_REPORT_LOCALE,
        REPORT_RUNTIME as EN_REPORT_RUNTIME,
        REPORT_SPECIAL as EN_REPORT_SPECIAL,
        REPORT_TEXT as EN_REPORT_TEXT,
        STRINGS as EN_STRINGS,
    )
    from .locales.ja import (
        LANGUAGE_CODE as JA_LANGUAGE_CODE,
        LANGUAGE_NAME as JA_LANGUAGE_NAME,
        REPORT_LOCALE as JA_REPORT_LOCALE,
        STRINGS as JA_STRINGS,
    )
except ImportError:  # src/organizer から直接実行する場合。
    from locales.en import (
        LANGUAGE_CODE as EN_LANGUAGE_CODE, LANGUAGE_NAME as EN_LANGUAGE_NAME,
        REPORT_ATTR as EN_REPORT_ATTR, REPORT_DYNAMIC_RULES_JS as EN_REPORT_DYNAMIC_RULES_JS,
        REPORT_FRAGMENTS_JS as EN_REPORT_FRAGMENTS_JS, REPORT_LOCALE as EN_REPORT_LOCALE,
        REPORT_RUNTIME as EN_REPORT_RUNTIME, REPORT_SPECIAL as EN_REPORT_SPECIAL,
        REPORT_TEXT as EN_REPORT_TEXT, STRINGS as EN_STRINGS,
    )
    from locales.ja import (
        LANGUAGE_CODE as JA_LANGUAGE_CODE, LANGUAGE_NAME as JA_LANGUAGE_NAME,
        REPORT_LOCALE as JA_REPORT_LOCALE, STRINGS as JA_STRINGS,
    )

DEFAULT_LANGUAGE = JA_LANGUAGE_CODE
PSEUDO_LANGUAGE = "qps"
SUPPORTED_LANGUAGES: Mapping[str, str] = {
    JA_LANGUAGE_CODE: JA_LANGUAGE_NAME,
    EN_LANGUAGE_CODE: EN_LANGUAGE_NAME,
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


def locale_for_language(value: object | None = None) -> str:
    """UI/レポートで使用するBCP 47ロケール名を返します。qpsは英語ロケールを使います。"""
    language = get_language() if value is None else normalize_language(value)
    return EN_REPORT_LOCALE if language in {EN_LANGUAGE_CODE, PSEUDO_LANGUAGE} else JA_REPORT_LOCALE


def _report_target_map(source: Mapping[str, str], language: str) -> dict[str, str]:
    """生成HTMLの翻訳辞書を英語または開発用疑似ロケールへ変換します。"""
    if language == PSEUDO_LANGUAGE:
        return {key: pseudo_localize(value) for key, value in source.items()}
    return dict(source)


def build_report_i18n_script(language: str) -> str:
    """生成HTML末尾へ埋め込むUI翻訳スクリプトを返します。

    日本語HTMLを基準とし、翻訳リソースは ``locales/en.py`` に集約します。
    ``qps`` は英語の静的UIを長文化してレイアウト耐性を確認する開発専用モードです。
    """
    language = normalize_language(language)
    if language not in {EN_LANGUAGE_CODE, PSEUDO_LANGUAGE}:
        return ""
    text_json = json.dumps(_report_target_map(EN_REPORT_TEXT, language), ensure_ascii=False, separators=(",", ":"))
    attr_json = json.dumps(_report_target_map(EN_REPORT_ATTR, language), ensure_ascii=False, separators=(",", ":"))
    special = _report_target_map(EN_REPORT_SPECIAL, language)
    runtime_json = json.dumps(EN_REPORT_RUNTIME, ensure_ascii=False, separators=(",", ":"))
    pseudo_css = ""
    if language == PSEUDO_LANGUAGE:
        pseudo_css = r"""
html[data-pseudo-locale="qps"] button,
html[data-pseudo-locale="qps"] select,
html[data-pseudo-locale="qps"] input,
html[data-pseudo-locale="qps"] .small,
html[data-pseudo-locale="qps"] .stat-label,
html[data-pseudo-locale="qps"] .fh6-foot-label { letter-spacing:.035em; }
html[data-pseudo-locale="qps"] .card-first-toolbar { flex-wrap:wrap; }
html[data-pseudo-locale="qps"] .card-first-toolbar > #q { min-width:min(360px,100%); }
html[data-pseudo-locale="qps"] .card-first-toolbar > #sortOrder { flex:1 1 260px; width:auto; }
html[data-pseudo-locale="qps"] .fh6-my-design-head h2 { white-space:normal; }
html[data-pseudo-locale="qps"] .fh6-navigator-settings-title { white-space:normal; }
"""
    return rf"""
<style id="reportI18nEnglishOverrides">
.fh6-navigator-settings > summary::after {{ content:{json.dumps(special["open_settings"], ensure_ascii=False)} !important; }}
.fh6-navigator-settings[open] > summary::after {{ content:{json.dumps(special["close_settings"], ensure_ascii=False)} !important; }}
{pseudo_css}
</style>
<script>
(() => {{
  "use strict";
  const REPORT_LANGUAGE = {json.dumps(language)};
  if (REPORT_LANGUAGE === "qps") document.documentElement.dataset.pseudoLocale = "qps";
  const TEXT = {text_json};
  const ATTR = {attr_json};
  const RUNTIME = {runtime_json};
  const jp = /[\u3040-\u30ff\u3400-\u9fff]/;
  const protectedSelectors = [
    ".card h3", ".card .vehicle-meta", ".card .asset", ".card h4",
    ".card .desc", ".card .fh6-creator-display", ".card .fh6-display-date",
    ".card dl dd", ".car-group .group-heading h2", "code", "pre",
    ".compare-value", ".detail-value", ".creator-name",
    ".compare-vehicle-user-data", ".compare-title-user-data", ".compare-user-data"
  ].join(",");

  function protectedNode(node) {{
    const el = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    if (el && el.closest && el.closest(".help-panel code, .diagnostics-issue-list code")) return false;
    return Boolean(el && el.closest && el.closest(protectedSelectors));
  }}

  function translateResult(value) {{
    let s = String(value ?? "");
    if (!jp.test(s)) return {{value:s, matched:false}};
    if (Object.prototype.hasOwnProperty.call(TEXT, s)) return {{value:TEXT[s], matched:true}};
    if (Object.prototype.hasOwnProperty.call(ATTR, s)) return {{value:ATTR[s], matched:true}};

    // 動的UIが「既知のUI文字列 + 補足」を組み立てるケース。
    // 利用者データを含む可能性のある値は、UI側の接頭辞だけ翻訳して値自体は保持します。
    let wrapper = s.match(/^(.+)（複数選択）$/);
    if (wrapper) {{
      const base = translateResult(wrapper[1]);
      if (base.matched) return {{value:`${{base.value}}${{RUNTIME.multiple_selection_suffix}}`, matched:true}};
    }}
    wrapper = s.match(/^元に戻す: (.+)$/);
    if (wrapper) {{
      const base = translateResult(wrapper[1]);
      return {{value:`${{RUNTIME.undo_prefix}}${{base.matched ? base.value : wrapper[1]}}`, matched:true}};
    }}
    wrapper = s.match(/^やり直す: (.+)$/);
    if (wrapper) {{
      const base = translateResult(wrapper[1]);
      return {{value:`${{RUNTIME.redo_prefix}}${{base.matched ? base.value : wrapper[1]}}`, matched:true}};
    }}
    wrapper = s.match(/^作成者: (.+)$/);
    if (wrapper) {{
      let tail = wrapper[1];
      let m = tail.match(/^すべて \((\d+)件\)$/);
      if (m) tail = `${{RUNTIME.all}} (${{m[1]}} ${{RUNTIME.items_word}})`;
      else if (tail === "すべて") tail = RUNTIME.all;
      else {{
        m = tail.match(/^(.+) \((\d+)件\)$/);
        if (m) tail = `${{m[1]}} (${{m[2]}} ${{RUNTIME.items_word}})`;
      }}
      return {{value:`${{RUNTIME.creator_prefix}}${{tail}}`, matched:true}};
    }}

    // 類似比較の概要は判定理由と実件数を実行時に組み立てるため、
    // 理由部分だけ再帰的に翻訳してから英文を組み立てます。
    wrapper = s.match(/^(.+) \/ (\d+)件。新しい取得日時から順に表示しています。$/);
    if (wrapper) {{
      const reason = translateResult(wrapper[1]);
      return {{
        value:`${{reason.matched ? reason.value : wrapper[1]}} / ${{wrapper[2]}}${{RUNTIME.similar_summary_suffix}}`,
        matched:true
      }};
    }}

    const rules = [
{EN_REPORT_DYNAMIC_RULES_JS}
    ];
    for (const [pattern, replacement] of rules) {{
      if (pattern.test(s)) return {{value:s.replace(pattern, replacement), matched:true}};
    }}

    // 動的な短いUI文言では、利用者データ領域を除外したうえで共通語を置換します。
    const fragments = [
{EN_REPORT_FRAGMENTS_JS}
    ];
    const original = s;
    for (const [from, to] of fragments) s = s.split(from).join(to);
    return {{value:s, matched:s !== original && !jp.test(s)}};
  }}

  function dynamicTranslate(value) {{
    return translateResult(value).value;
  }}

  function translateTextNode(node) {{
    if (!node || protectedNode(node)) return;
    const oldValue = node.nodeValue || "";
    if (!jp.test(oldValue)) return;
    const trimmed = oldValue.trim();
    if (!trimmed) return;
    const result = translateResult(trimmed);
    if (!result.matched || result.value === trimmed) return;
    const leading = oldValue.match(/^\s*/)?.[0] || "";
    const trailing = oldValue.match(/\s*$/)?.[0] || "";
    node.nodeValue = leading + result.value + trailing;
  }}

  function translateElement(el) {{
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return;
    for (const name of ["title", "aria-label", "placeholder", "label", "data-closed-label", "data-base-label"]) {{
      const value = el.getAttribute(name);
      if (!value || !jp.test(value)) continue;
      if (Object.prototype.hasOwnProperty.call(ATTR, value)) {{
        el.setAttribute(name, ATTR[value]);
        continue;
      }}
      const result = translateResult(value);
      if (result.matched && result.value !== value) el.setAttribute(name, result.value);
    }}
  }}

  function translateTree(root = document.body) {{
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) translateTextNode(root);
    if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {{
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      else translateElement(node);
    }}
  }}

  const nativeAlert = window.alert.bind(window);
  const nativeConfirm = window.confirm.bind(window);
  const nativePrompt = window.prompt.bind(window);
  window.alert = message => nativeAlert(dynamicTranslate(message));
  window.confirm = message => nativeConfirm(dynamicTranslate(message));
  window.prompt = (message, value) => nativePrompt(dynamicTranslate(message), value);

  translateTree(document.body);
  const observer = new MutationObserver(mutations => {{
    for (const mutation of mutations) {{
      if (mutation.type === "characterData") translateTextNode(mutation.target);
      else if (mutation.type === "attributes") translateElement(mutation.target);
      else for (const node of mutation.addedNodes) translateTree(node);
    }}
  }});
  observer.observe(document.body, {{subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:["title","aria-label","placeholder","label","data-closed-label","data-base-label"]}});
  document.documentElement.lang = REPORT_LANGUAGE;
}})();
</script>"""

