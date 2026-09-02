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
      [/^v([^ ]+) 現在仕様 \/ 日常の操作順に整理したガイド$/, "v$1 current specification / workflow guide"],
      [/^残り (\d+)人を表示$/, "Show remaining $1 creators"],
      [/^から1件ずつ、または全件を復元できます。仮削除はこの生成HTML専用のlocalStorageへ保存され、新しくHTMLを生成すると引き継ぎません。再DL完全一致は (\d+)組 \/ (\d+)件（余分 (\d+)件）で、「再DL重複のみ」から直接絞り込めます。$/, "using the control at the top to restore individual items or all items. Temporary deletions are stored in localStorage for this generated HTML only and are not carried into a newly generated HTML. Exact re-downloads: $1 groups / $2 items ($3 extra); use Re-download duplicates only to filter them directly."],
      [/^JavaScriptエラー: (.+)$/, "JavaScript error: $1"],
      [/^生成時 #(\d+) \/ (#[0-9]+[UD]|—)(.*)$/, "Generated at #$1 / $2$3"],
      [/^(\d+)件 · 最初 #(\d+) \/ (#[0-9]+[UD]|—)$/, "$1 items · first #$2 / $3"],
      [/^ほか (\d+)車種。文字を追加すると絞り込めます。$/, "$1 more vehicles. Type more characters to narrow the list."],
      [/^(.+) · (\d+) \/ (\d+)車種 · (.+) · #(\d+) \/ (#[0-9]+[UD]|—)$/, "$1 · $2 / $3 vehicles · $4 · #$5 / $6"],
      [/^新規判定基準: (\d+)件 \/ (.+)$/, "New-item baseline: $1 items / $2"],
      [/^現在の (\d+)件を、今後の「新規 \/ 基準から消えた」判定の基準にしますか？$/, "Use the current $1 items as the baseline for future New / Missing-from-baseline detection?"],
      [/^選択中の(\d+)件を比較します$/, "Compare the $1 selected items"],
      [/^選択中の(\d+)件を取得日時の新しい順で比較しています。$/, "Comparing the $1 selected items from newest to oldest acquisition time."],
      [/^選択 (\d+)件 \/ 使用中タグ (\d+)種類$/, "$1 selected / $2 tags in use"],
      [/^再DL重複 (\d+)件$/, "Re-download duplicates: $1 items"],
      [/^Creator: すべて \((\d+)件\)$/, "Creator: All ($1 items)"],
      [/^Manufacturer: すべて \((\d+)件\)$/, "Manufacturer: All ($1 items)"],
      [/^Year: すべて \((\d+)件\)$/, "Year: All ($1 items)"],
      [/^Creator: (.+) \((\d+)件\)$/, "Creator: $1 ($2 items)"],
      [/^Manufacturer: (.+) \((\d+)件\)$/, "Manufacturer: $1 ($2 items)"],
      [/^Year: (.+) \((\d+)件\)$/, "Year: $1 ($2 items)"],
      [/^Creator: すべて$/, "Creator: All"],
      [/^Manufacturer: すべて$/, "Manufacturer: All"],
      [/^Year: すべて$/, "Year: All"],
      [/^(\d+)件選択$/, "$1 selected"],
      [/^(\d+)人$/, "$1 creators"],
      [/^比較対象 (\d+)件中 (\d+)件を選択中$/, "$2 of $1 comparison items selected"],
      [/^(\d+)件の完全一致スロット \/ 余分 (\d+)件。残す1件を選択してください。$/, "$1 exact-match slots / $2 extra. Choose one item to keep."],
      [/^(\d+) \/ (\d+)組$/, "$1 / $2 groups"],
      [/^FH6削除済み（仮） (\d+)件をすべて元に戻しますか？$/, "Restore all $1 temporarily deleted-in-FH6 items?"],
      [/^前回保存: (.+)$/, "Last saved: $1"],
      [/^(\d+)件の判定を復元しました。$/, "Restored decisions for $1 items."],
      [/^「(.+)」を現在の条件で上書きしますか？$/, "Overwrite preset “$1” with the current filters?"],
      [/^プリセット「(.+)」を削除しますか？$/, "Delete preset “$1”?"],
      [/^(.+) \((\d+)件 \/ 現在 (\d+)件\)$/, "$1 ($2 items / current $3 items)"],
      [/^(.+) \((\d+)件 \/ 追加後 (\d+)件\)$/, "$1 ($2 items / after adding $3 items)"],
      [/^(.+) \((\d+)車種 \/ 現在 (\d+)車種\)$/, "$1 ($2 vehicles / current $3 vehicles)"],
      [/^(.+) \((\d+)車種 \/ 追加後 (\d+)車種\)$/, "$1 ($2 vehicles / after adding $3 vehicles)"],
      [/^未完了 (\d+) \/ (\d+)車種 · 全 (\d+)車種$/, "Unfinished $1 / $2 vehicles · Total $3 vehicles"],
      [/^現在 完了 · 未完了 (\d+)車種 · 全 (\d+)車種$/, "Current vehicle complete · $1 unfinished vehicles · Total $2 vehicles"],
      [/^(\d+) \/ (\d+)件 · (\d+)列表示$/, "$1 / $2 items · $3 columns"],
      [/^(\d+) \/ (\d+)列$/, "$1 / $2 columns"],
      [/^整合性OK（(\d+)件）$/, "Integrity OK ($1 items)"],
      [/^最終実スロット #(\d+) \/ 初期位置リセット: OFF$/, "Final actual slot #$1 / origin reset: OFF"],
      [/^最終実スロット #(\d+) \/ 左循環後 \+(\d+)ms \/ 初期位置リセット: OFF$/, "Final actual slot #$1 / after left wrap +$2 ms / origin reset: OFF"],
      [/^最終実スロット #(\d+) \/ 初期位置: ESC → RET（(\d+)ms \/ (\d+)ms）$/, "Final actual slot #$1 / origin: ESC → RET ($2 ms / $3 ms)"],
      [/^最終実スロット #(\d+) \/ 左循環後 \+(\d+)ms \/ 初期位置: ESC → RET（(\d+)ms \/ (\d+)ms）$/, "Final actual slot #$1 / after left wrap +$2 ms / origin: ESC → RET ($3 ms / $4 ms)"],
      [/^Navigator Bridgeへ (.+)、最終実スロット #(\d+) と移動設定を渡します。Fキーでも実行できます。$/, "Pass $1, final actual slot #$2, and navigation settings to Navigator Bridge. You can also press F."],
      [/^(.+)（Fキーでも移動）$/, "$1 (F also runs it)"],
      [/^車種件数不一致: ([^:]+): 宣言 (.+) \/ 実数 (\d+)$/, "Vehicle count mismatch: $1: declared $2 / actual $3"],
      [/^進捗max不一致: ([^:]+): max (.+) \/ 実数 (\d+)$/, "Progress max mismatch: $1: max $2 / actual $3"],
      [/^マイデザイン番号: 無効な番号あり$/, "My Designs number: invalid number"],
      [/^マイデザイン番号: 番号重複あり$/, "My Designs number: duplicate number"],
      [/^マイデザイン番号: 範囲 (.+)〜(.+) \/ 期待 1〜(.+)$/, "My Designs number: range $1–$2 / expected 1–$3"],
      [/^再DL重複グループ: グループIDなし$/, "Re-download duplicate group: missing group ID"],
      [/^再DL重複グループ: (.+): 表示 (\d+) \/ 宣言 (.+)$/, "Re-download duplicate group: $1: displayed $2 / declared $3"],
      [/^再DL重複グループ: (.+): 画像一致類似候補との対応不整合$/, "Re-download duplicate group: $1: inconsistent with image-match similar candidates"],
      [/^FH6実スロット: 実スロット配列なし$/, "FH6 actual slot: actual-slot array missing"],
      [/^FH6実スロット: 実スロット (\d+) \/ カード (\d+)$/, "FH6 actual slot: $1 slots / $2 cards"],
      [/^FH6実スロット: (\d+)番目: (.+) \/ 期待 (.+)$/, "FH6 actual slot: item $1: $2 / expected $3"],
      [/^FH6実スロット: 位置重複: (.+)$/, "FH6 actual slot: duplicate position: $1"],
      [/^FH6実スロット: (.+): 対応カードなし$/, "FH6 actual slot: $1: corresponding card missing"],
      [/^FH6実スロット: (.+): FH6日付不一致$/, "FH6 actual slot: $1: FH6 date mismatch"],
      [/^サムネイル読込失敗: (.+)$/, "Thumbnail load failed: $1"],
      [/^(\d+)組$/, "$1 groups"],
      [/^(\d+)件$/, "$1 items"],
      [/^(\d+)車種$/, "$1 vehicles"],
      [/^(\d+)候補$/, "$1 choices"],
      [/^未完了 (\d+)車種 · 全 (\d+)車種$/, "Unfinished $1 vehicles · Total $2 vehicles"],
      [/^整理 (\d+) \/ (\d+) · (\d+)%$/, "Organized $1 / $2 · $3%"],
      [/^残す (\d+)件 \/ 削除候補 (\d+)件$/, "Keep $1 / Delete candidates $2"],
      [/^問題 (\d+)件$/, "$1 issues"],
      [/^選択中のみ \((\d+)件\)$/, "Selected only ($1 items)"],
      [/^選択中を比較 \((\d+)件\)$/, "Compare selected ($1 items)"],
      [/^選択(\d+)件→残す$/, "$1 selected → Keep"],
      [/^選択(\d+)件→削除候補$/, "$1 selected → Delete candidate"],
      [/^選択(\d+)件→未決定$/, "$1 selected → Undecided"],
      [/^選択(\d+)件→お気に入り$/, "$1 selected → Favorite"],
      [/^選択(\d+)件→後で確認$/, "$1 selected → Review later"],
      [/^選択(\d+)件→タグ管理$/, "$1 selected → Manage tags"],
      [/^新規のみ \((\d+)件\)$/, "New only ($1 items)"],
      [/^類似候補のみ \((\d+)件\)$/, "Similar only ($1 items)"],
      [/^画像一致のみ \((\d+)件\)$/, "Image match only ($1 items)"],
      [/^同一作者・同名のみ \((\d+)件\)$/, "Same creator & title only ($1 items)"],
      [/^お気に入りのみ \((\d+)件\)$/, "Favorites only ($1 items)"],
      [/^後で確認のみ \((\d+)件\)$/, "Review later only ($1 items)"],
      [/^再DL重複のみ \((\d+)組 \/ (\d+)件\)$/, "Re-download duplicates only ($1 groups / $2 items)"],
      [/^車種 すべて \((\d+)車種 \/ (\d+)件\)$/, "Vehicle: All ($1 vehicles / $2 items)"],
      [/^メーカー: すべて \((\d+)件\)$/, "Manufacturer: All ($1 items)"],
      [/^作成者: すべて \((\d+)件\)$/, "Creator: All ($1 items)"],
      [/^年式: すべて \((\d+)件\)$/, "Year: All ($1 items)"],
      [/^ペイント件数: すべて \((\d+)車種 \/ (\d+)件\)$/, "Paint count: All ($1 vehicles / $2 items)"],
      [/^ペイント件数: (\d+)件 \((\d+)車種 \/ (\d+)件\)$/, "Paint count: $1 ($2 vehicles / $3 items)"],
      [/^バイナル数: すべて \((\d+)件\)$/, "Vinyl count: All ($1 items)"],
      [/^バイナル数: (\d+)以上 \((\d+)件\)$/, "Vinyl count: $1 or more ($2 items)"],
      [/^バイナル数: (.+) \((\d+)件\)$/, "Vinyl count: $1 ($2 items)"],
      [/^組 \/ (\d+)件（余分 (\d+)件）$/, "groups / $1 items ($2 extra)"],
      [/^(\d+)件 \/ FH6インストール先未指定$/, "$1 items / FH6 install not specified"],
      [/^タグ: すべて \((\d+)件\)$/, "Tags: All ($1 items)"],
      [/^メーカー: (.+) \((\d+)件\)$/, "Manufacturer: $1 ($2 items)"],
      [/^作成者: (.+) \((\d+)件\)$/, "Creator: $1 ($2 items)"],
      [/^年式: (.+) \((\d+)件\)$/, "Year: $1 ($2 items)"],
      [/^車種 すべて$/, "Vehicle: All"],
      [/^メーカー: すべて$/, "Manufacturer: All"],
      [/^メーカー: (.+)$/, "Manufacturer: $1"],
      [/^作成者: すべて$/, "Creator: All"],
      [/^作成者: (.+)$/, "Creator: $1"],
      [/^年式: すべて$/, "Year: All"],
      [/^年式: (.+)$/, "Year: $1"],
      [/^ペイント件数: すべて$/, "Paint count: All"],
      [/^タグ: すべて$/, "Tags: All"],
      [/^タグ: (.+)$/, "Tags: $1"],
      [/^(.+) \((\d+)件\)$/, "$1 ($2 items)"],
      [/^整理済み (\d+) \/ (\d+)（残す (\d+) \/ 削除候補 (\d+) \/ 未決定 (\d+)）｜クリックしてこの車種だけ表示$/, "Organized $1 / $2 (Keep $3 / Delete candidate $4 / Undecided $5) | Click to show only this vehicle"],
      [/^(#\d+ \/ #\d+[UD]) をFH6移動対象に設定$/, "Set $1 as the FH6 move target"],
      [/^整理 — \/ (\d+)$/, "Organized — / $1"],
      [/^整理 (\d+) \/ (\d+)$/, "Organized $1 / $2"],
      [/^動作診断で (\d+) 項目の問題を検出しました。診断結果を確認してください。$/, "Diagnostics found $1 issues. Review the diagnostic results."],
      [/^動作診断 (\d+) \/ (\d+) 項目正常。通常利用できます。$/, "Diagnostics: $1 / $2 checks OK. Normal use is available."],
      [/^(\d+) \/ (\d+) 項目正常$/, "$1 / $2 checks OK"],
      [/^(\d+) \/ (\d+)車種$/, "$1 / $2 vehicles"],
      [/^キーなし (\d+) \/ 重複 (\d+)件$/, "missing keys $1 / duplicates $2"],
      [/^CSVなし (\d+) \/ 孤立CSV (\d+)件$/, "missing CSV $1 / orphan CSV $2"],
      [/^不一致 (\d+)件$/, "$1 mismatches"],
      [/^重複 (\d+) \/ グループなし (\d+) \/ 件数不一致 (\d+)件$/, "duplicates $1 / missing groups $2 / count mismatches $3"],
      [/^max不一致 (\d+)件$/, "max mismatches $1"],
      [/^要素なし (\d+) \/ 参照なし (\d+)件$/, "missing elements $1 / missing references $2"],
      [/^(\d+)件確認 \/ (\d+)件失敗$/, "$1 checked / $2 failed"],
      [/^(\d+)件不足$/, "$1 missing"],
      [/^(\d+)件未対応$/, "$1 unsupported"],
      [/^(\d+) \/ (\d+)人$/, "$1 / $2 creators"],
      [/^未着手 (\d+) \/ 整理中 (\d+) \/ 完了 (\d+)車種$/, "Not started $1 / In progress $2 / Complete $3 vehicles"],
      [/^#(\d+)〜#(\d+) \/ 不整合 (\d+)件$/, "#$1–#$2 / inconsistencies $3"],
      [/^DD\/MM\/YYYY \/ 不整合 (\d+)件$/, "DD/MM/YYYY / inconsistencies $1"],
      [/^(\d+)組 \/ 不整合 (\d+)件$/, "$1 groups / inconsistencies $2"],
      [/^2段×横スクロール \+ 実スロット (\d+)件 \/ 不整合 (\d+)件$/, "two-row horizontal scrolling + $1 actual slots / inconsistencies $2"],
      [/^一時非表示 (\d+)件 \/ 現在実スロット (\d+)件 \/ 位置再計算$/, "$1 temporarily hidden / $2 current actual slots / positions recalculated"],
      [/^全ソート・比較画面の#実スロット\/#列U\/Dから移動対象を選択 \+ 仮削除反映後の最終実スロット (\d+)件 \+ navigatorbridgeforfh6:\/\/ で受け渡し$/, "choose move target from #actual-slot/#columnU-D in all sort/comparison views + final actual slot after temporary deletions: $1 + pass via navigatorbridgeforfh6://"],
      [/^問題の詳細（(\d+)件(?:・先頭のみ)?）$/, "Issue details ($1 items)"],
      [/^サムネイル要素なし: (.+)$/, "Missing thumbnail element: $1"],
      [/^FH6表示日付: (.+)$/, "FH6 display date: $1"],
      [/^カードキーなし: (.+)$/, "Missing card key: $1"],
      [/^カードキー重複: (.+)$/, "Duplicate card key: $1"],
      [/^CSVなし: (.+)$/, "Missing CSV record: $1"],
      [/^孤立CSV: (.+)$/, "Orphan CSV record: $1"],
      [/^CSVレコードキー不一致: (.+)$/, "CSV record key mismatch: $1"],
      [/^車種グループ重複: (.+)$/, "Duplicate vehicle group: $1"],
      [/^車種グループなし: (.+)$/, "Missing vehicle group: $1"],
      [/^サムネイル要素なし: (.+)$/, "Missing thumbnail element: $1"],
      [/^サムネイル参照なし: (.+)$/, "Missing thumbnail reference: $1"],
    ];
    for (const [pattern, replacement] of rules) {{
      if (pattern.test(s)) return {{value:s.replace(pattern, replacement), matched:true}};
    }}

    // 動的な短いUI文言では、利用者データ領域を除外したうえで共通語を置換します。
    const fragments = [
      ["絞り込みを閉じる", "Close filters"],
      ["絞り込み・並び替え", "Filter & Sort"],
      ["絞り込み", "Filter"],
      ["未決定", "Undecided"],
      ["削除候補", "Delete candidate"],
      ["後で確認", "Review later"],
      ["お気に入り", "Favorite"],
      ["類似候補", "Similar"],
      ["サムネイル完全一致", "Exact thumbnail match"],
      ["作成者＋タイトル一致", "Same creator + title"],
      ["新しい取得日時から順に表示しています。", "Sorted by acquisition time, newest first."],
      ["初期位置リセット", "origin reset"],
      ["最終実スロット", "Final actual slot"],
      ["左循環後", "after left wrap"],
      ["初期位置", "origin"],
      ["画像一致", "Image match"],
      ["同一作者・同名", "Same creator & title"],
      ["作成者", "Creator"],
      ["取得日時", "Acquired"],
      ["バイナル数", "Vinyl count"],
      ["ペイント件数", "Paint count"],
      ["車種", "vehicle"],
      ["件", " items"],
      ["組", " groups"],
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

