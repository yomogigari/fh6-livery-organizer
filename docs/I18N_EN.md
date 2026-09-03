# Livery Organizer for FH6 Internationalization Policy

**Japanese / 日本語:** [I18N.md](I18N.md)

This document describes the localization architecture, documentation-language policy, and translation contribution rules used by Livery Organizer for FH6.

## Core rules

- Japanese (`ja`) is the fallback language.
- Japanese and English (`en`) are the minimum user-facing languages.
- Desktop GUI and CLI strings are obtained through `tr("key")` instead of embedding user-facing text directly in application logic.
- `src/organizer/locales/ja.py` and `src/organizer/locales/en.py` must contain matching translation-key sets.
- Format placeholders such as `{path}` and `{count}` must also match between languages.
- Unsupported or invalid language selections fall back to Japanese.
- Internationalization must not add external Python package dependencies.

## Documentation languages

Japanese is the source and primary language for the project's main documentation. English is the common second documentation language.

- `README.md` is the primary GitHub README; `README_EN.md` is the English README.
- Normal release ZIPs contain both `README.txt` / `README_EN.txt` and `NAVIGATOR-BRIDGE-README.txt` / `NAVIGATOR-BRIDGE-README_EN.txt`.
- The Python Organizer requires `i18n.py` and `locales/` at runtime, so the normal release ZIP keeps them together with the Organizer script under `python/`.
- `CHANGELOG.md` remains primarily Japanese. Separate changelogs are not maintained for every UI language.
- If additional UI languages are added later, the project does not plan to maintain a complete README, changelog, release notes, and Bridge guide for each language. Users who do not read Japanese should use the English documentation as the common reference.

## English translation feedback

Feedback about awkward wording, mistranslations, inconsistent terminology, or unclear English is welcome.

When possible, please propose the correction as a concrete change to:

```text
src/organizer/locales/en.py
```

A pull request that changes the relevant locale entry is especially helpful because it makes the proposed wording and context easy to review.

Translation changes are not accepted solely on grammatical preference. Review may also check:

- whether the English matches the actual behavior and the Japanese source meaning;
- terminology consistency across Organizer;
- whether longer text affects buttons, dialogs, the generated HTML, or other layouts;
- translation-key and format-placeholder compatibility;
- existing localization and regression tests.

For these reasons, **reviewing and incorporating translation changes may take time**. Immediate incorporation of a reported translation change or pull request is not guaranteed.

## Language setting

- The selected language is stored in `settings.json` as `language`.
- A language change in the main window takes effect on the next launch.
- During development/testing, `FH6_ORGANIZER_LANG=en` can temporarily override the saved language.
- The environment-variable override does not rewrite the saved preference.
- Generated HTML and Excel reports use the Organizer language that is active when the report is generated.

## Paths and presentation

- Japanese UI keeps the existing `¥`-style Windows path presentation.
- English UI uses the normal Windows `\` separator.
- General text such as `JSON / CSV` is not treated as a path and is not rewritten.
- Layouts should allow wrapping when translations are longer than the Japanese source.

## Data that must not be translated

The localization layer translates Organizer-owned UI/system text, not user or game data. The following values remain verbatim:

- livery title and description;
- creator name;
- vehicle/manufacturer/model data values and proper names;
- Car ID, Livery ID, fingerprints, and other internal identifiers;
- user-entered tags and notes;
- technical diagnostic values such as paths, exception text, signatures, and raw identifiers when those values are being displayed as data.

System-generated fallbacks such as `Unknown vehicle`, `No title`, unknown-date messages, empty-report messages, and JavaScript exception fallbacks are localized because they are Organizer-owned UI text.

## Generated HTML

Japanese HTML is the base report. For English (and the development pseudo-locale), Organizer embeds a self-contained translation layer generated from locale resources. It does not require an external JavaScript file or external library.

The translation layer covers static text and dynamic UI created after page load, including status messages, modal summaries, diagnostics, attributes such as `title` / `aria-label` / `placeholder`, and CSS-generated UI labels. User-data regions are explicitly protected from translation.

The report locale is `ja-JP` for Japanese and `en-US` for English-like development output.

## Excel localization

The Excel report follows the Organizer language active when it is generated.

- Japanese keeps the existing `ペイント一覧` sheet and Japanese system labels.
- English uses `Paint List` and English Organizer-generated labels.
- User/game data values are not translated.
- The existing report structure, embedded thumbnails, AutoFilter, frozen header row, and column layout are preserved.

## Development pseudo-locale (`qps`)

`qps` is a development-only pseudo-locale used to find untranslated strings and layout weaknesses caused by longer text.

- It is not shown in the normal language selector.
- It can be enabled only through the development environment override, for example `FH6_ORGANIZER_LANG=qps`.
- It expands English-based UI text while preserving format placeholders and inserted data values.
- Unsupported real language codes do not map to `qps`; they fall back to Japanese.
- HTML uses English-style locale behavior while the pseudo-localized UI stresses responsive layouts.

## Source layout

Localization code is organized as follows:

```text
src/organizer/i18n.py
src/organizer/locales/ja.py
src/organizer/locales/en.py
```

`i18n.py` contains language-independent selection, normalization, `tr()`, pseudo-localization, locale helpers, and generated-report translation-script construction. Locale-specific text and report translation resources live in the locale modules.

For maintainability, translation dictionary entries in `locales/en.py` are kept as one physical source line per entry, including long strings. Display line breaks are represented with `\n` instead of splitting one dictionary entry across multiple implicit Python string literals.

## Testing

`tests/test_i18n.py` covers, among other things:

- matching Japanese/English translation keys and format placeholders;
- language normalization and Japanese fallback;
- saved-language and environment-override behavior;
- English and pseudo-localized CLI/GUI output;
- generated HTML language, dynamic translation coverage, user-data protection, and edge-case fallbacks;
- localized Excel system text while preserving user data;
- layout safeguards for longer translations;
- static checks for user-facing Japanese text that bypasses the localization layer;
- localization-module structure and translation-entry formatting;
- later report UX/search regression checks that must remain compatible with localization.

Additional development smoke tests exercise English and pseudo-localized GUI/report layouts at multiple window widths.

## Adding another UI language

If another UI language is added in the future:

1. Add it as an independent locale resource and preserve key/placeholder compatibility.
2. Preserve the boundary that prevents livery/user/game data from being translated.
3. Check desktop GUI, generated HTML, Excel, CLI, and error/edge-case paths.
4. Run long-text/layout validation comparable to the `qps` checks.
5. Do not assume a complete documentation set will be created for the new language; use the English documentation as the common non-Japanese reference.
