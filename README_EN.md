# Livery Organizer for FH6

**Japanese / 日本語:** [README.md](README.md)

**Livery Organizer for FH6** is a Windows tool for listing, searching, and organizing paint designs (liveries) downloaded in the PC version of **Forza Horizon 6**.

It reads information from the local FH6 GameSave and game assets and generates an HTML report with thumbnails, plus an Excel report. The generated HTML provides search, filtering, sorting, organization states, tags, notes, backups, FH6 My Designs ordering, and optional integration with **Navigator Bridge for FH6**.

**v0.4.59 Preview** (released 2026-09-04) adds Japanese/English localization for the Organizer desktop UI, generated HTML, and Excel output. It also reduces live-search work in large HTML reports. The bundled **Navigator Bridge for FH6 v0.0.27** tightens FH6 window detection so that unrelated windows containing the game name are not treated as FH6.

> [!IMPORTANT]
> This is a Preview release. FH6's internal save-data and asset formats are not public specifications, and some parsing behavior is based on observations from real data.

## Main features

- List downloaded paint designs by vehicle
- Resolve vehicle name, manufacturer, year, and related information from FH6 assets where available
- Local HTML report with embedded thumbnails
- Excel output with thumbnails
- Search, filtering, and sorting by vehicle, manufacturer, creator, year, title, and other fields
- Japanese and English Organizer GUI / generated HTML / Excel output
- `/` shortcut to focus the search field and `?` shortcut to open Help
- Live-search optimizations for large reports
- FH6 My Designs order view
- Current real-slot sequence number and `#columnU / #columnD` FH6-position display
- Keep / Delete candidate / Undecided organization states
- Favorites, Review later, tags, and notes
- Similar-thumbnail candidate review
- Re-download duplicate comparison and organization
- Per-vehicle organization progress
- Temporary “Deleted in FH6” state with current-position recalculation
- Undo / Redo
- User-data and decision backups/restores
- CSV export
- In-browser diagnostics
- Python version using only the Python standard library
- Optional Navigator Bridge for FH6 integration

## Navigator Bridge for FH6

**Navigator Bridge for FH6 v0.0.27** is an optional companion tool that moves the cursor in FH6's **My Designs** screen to a paint position selected in Organizer.

Organizer can display a position such as:

```text
#603 / #302U
```

`#603` is the current real-slot sequence number. `#302U` means column 302, upper row (U), in FH6 My Designs.

After selecting a move target, press `F` or use **Move to selected design in FH6**. Organizer passes the target position, current final real-slot number, and movement timing settings to Navigator Bridge.

Bridge calculates the required Left / Right / Down cursor inputs from `#001U`, brings the FH6 window to the foreground, verifies the foreground state, and sends the fixed cursor-key sequence using the standard Windows input API.

### Integration registration

On first use, start Navigator Bridge by itself and run **Register Integration** once. Windows stores the absolute path of the Bridge executable/script for the `navigatorbridgeforfh6://` protocol.

Register again from the new Bridge location if you:

- move Bridge to another folder;
- rename the Bridge file;
- switch between the EXE and Python versions.

If you replace an EXE with a newer version while keeping the same folder and filename, registration normally does not need to be repeated.

## Safety

### Livery Organizer for FH6

Organizer treats the FH6 GameSave and FH6 game assets as **read-only inputs**.

It does not write, delete, move, rename, or overwrite the source data, and the GameSave directory cannot be used as a report-output location. Settings, caches, and generated reports are stored outside the GameSave.

States such as Delete candidate or Deleted in FH6 (temporary) are Organizer-side organization data. They do not delete files from the GameSave.

### Navigator Bridge for FH6

Navigator Bridge does not modify the FH6 GameSave, game files, or game memory.

The current Bridge treats a window as FH6 **only when its title, after trimming outer spaces, exactly matches `Forza Horizon 6`**. A browser tab, GitHub page, Organizer window, or another application that merely contains “Forza Horizon 6” in its title is rejected. The foreground title is checked again before key input; if the check fails, Bridge does not send the movement keys.

Normal position movement can send only:

- Left
- Right
- Down

If the optional **Reset to #001U** setting is enabled, Bridge additionally sends one fixed `Esc` followed by one fixed `Return` before normal movement. Arbitrary key codes, key names, or key sequences cannot be supplied through Organizer or the external URI.

Bridge does **not** automate:

- Load Design
- paint selection
- paint deletion
- confirmation actions

It also does not inspect the FH6 screen with image recognition, read the game's internal paint/cursor position, or verify that the resulting cursor is at the expected item. Final confirmation, loading, and deletion remain user actions in FH6.

## Languages and documentation

Organizer currently supports **Japanese** and **English** for user-facing UI. The selected language is stored in `settings.json` and takes effect on the next launch. Generated HTML and Excel output use the Organizer language that is active when the report is generated.

Livery titles, descriptions, creator names, vehicle/proper-name data, tags, notes, IDs, and similar user/game data are not translated.

Japanese is the source/primary language for the project's main documentation. English is maintained as the common second documentation language.

If you find awkward or incorrect English, feedback is welcome. When possible, please propose the correction as a change to:

```text
src/organizer/locales/en.py
```

A pull request with the relevant locale change is especially helpful. Translation changes may take time to review because wording, feature meaning, terminology consistency, tests, and UI/layout effects are checked before incorporation.

Additional UI languages may be added in the future, but a complete documentation set will not necessarily be maintained for every language. For languages other than Japanese, use the English documentation as the common reference.

See [docs/I18N_EN.md](docs/I18N_EN.md) for the translation and internationalization policy.

## Release package

GitHub Releases for v0.4.59 Preview contain the EXE versions, Python versions, and Japanese/English documentation in one ZIP:

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python/
  livery-organizer-for-fh6-v0459.py
  i18n.py
  navigator-bridge-for-fh6-v027.py
  locales/
    __init__.py
    ja.py
    en.py
```

Organizer can be used as either the EXE or Python version. The Python Organizer uses the localization modules in the same `python` folder, so keep `i18n.py` and the `locales` folder together with the Organizer script. Navigator Bridge can also be used as either the EXE or Python version and is optional.

The Build Kit and detailed instructions for rebuilding the Windows EXEs are not included in the normal distribution.

## Demo

A public demo generated from anonymized/dummy data is available here:

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

For safety, the public demo disables launching Navigator Bridge and sending keys to FH6.

## Supported environment

Primary target environment:

- Windows 11
- PC version of Forza Horizon 6
- A common desktop web browser for generated HTML reports

Development and verification are centered on the Microsoft Store / Xbox App version.

Users have reported successful Organizer use with the Steam version, but Steam is not an officially verified development environment and save/game paths or file layouts may differ. Navigator Bridge is also not formally verified on Steam and requires the FH6 window title to match `Forza Horizon 6`.

The Python version uses only the Python standard library and Tkinter for its GUI.

## Running Organizer

### Windows EXE

Run:

```text
Livery-Organizer-for-FH6.exe
```

### Python

Run:

From the folder where you extracted the release ZIP, run:

```powershell
python python\livery-organizer-for-fh6-v0459.py
```

With `uv`:

```powershell
uv run python\livery-organizer-for-fh6-v0459.py
```

Keep `python\i18n.py` and the `python\locales` folder in place; they contain the Japanese/English UI resources used by the Python Organizer.

After the GUI starts, confirm the FH6 save location, FH6 installation path, and report-output location as needed. They are normally detected automatically.

Fully closing FH6 before scanning is recommended.

## Running Navigator Bridge

### Windows EXE

```text
Navigator-Bridge-for-FH6.exe
```

Start it by itself once and run **Register Integration** before using it from Organizer.

### Python

```powershell
python python\navigator-bridge-for-fh6-v027.py
```

For detailed behavior and setup, see `NAVIGATOR-BRIDGE-README_EN.txt` in the release package or `docs/releases/NAVIGATOR-BRIDGE-README_EN.txt` in the repository.

## Generated files

Normal mode primarily generates:

```text
livery-organizer-for-fh6.html
livery-organizer-for-fh6.xlsx
```

The HTML normally embeds thumbnails and can be viewed as a standalone file. Excel also embeds thumbnails.

Optional analysis JSON/CSV files can be written under a `data` directory.

HTML-side exports use names such as:

```text
livery-organizer-for-fh6-userdata.json
livery-organizer-for-fh6-decisions-backup.json
livery-organizer-for-fh6-decisions.csv
livery-organizer-for-fh6-decisions-filtered.csv
```

## Organizer data stored in the browser

The generated HTML stores the following in browser `localStorage`:

- Keep / Delete candidate / Undecided
- Favorite
- Review later
- tags
- notes
- Deleted in FH6 (temporary)
- some UI settings

These values are not written back to the FH6 GameSave.

Deleted in FH6 (temporary) is local to that generated HTML and is not carried into a newly generated report. Use the built-in backup functions for organization data you want to preserve.

## Preview limitations

FH6 save-data and game-asset structures are not controlled by this project. Game updates, format/location changes, or environment differences can cause parsing failures or misidentification.

Navigator Bridge does not read the actual current cursor position from FH6. If key input is dropped because of system/game load or the screen is not in the expected state, the cursor can end up at a different position. Adjust the timing settings when necessary and confirm the final state in FH6.

When reporting a problem, do not publish private information or your actual GameSave files.

## Unofficial project

This is an unofficial, non-commercial fan-made project. It is not affiliated with, endorsed by, sponsored by, or approved by Microsoft, Xbox, Turn 10 Studios, Playground Games, or the Forza franchise.

It is not intended to automate game progression, competition, economy, rankings, or similar gameplay systems.

Product names, service names, trademarks, and other rights belong to their respective owners. Users are responsible for reviewing the rules and terms that apply to their use.

## License

MIT License. The software is provided as-is. Back up important data as appropriate and use the software at your own responsibility.
