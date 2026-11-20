# Livery Organizer for FH6

**Japanese / 日本語:** [README.md](README.md)

**Livery Organizer for FH6** is a Windows tool for listing, searching, and organizing paint designs (liveries) downloaded in the PC version of **Forza Horizon 6**.

It reads information from the local FH6 GameSave and game assets and generates an HTML report with thumbnails, plus an Excel report. The generated HTML provides search, filtering, sorting, organization states, tags, notes, backups, FH6 My Designs ordering, and optional integration with **Navigator Bridge for FH6**.

This repository and the release package contain three tools:

| Tool | Role |
| --- | --- |
| **Livery Organizer for FH6** (main tool) | Lists, searches, and organizes downloaded liveries and generates HTML / Excel reports. |
| **Livery Viewer for FH6** (optional, experimental) | Shows a report's livery in 3D on the FH6 car body. Bundled starting with v0.4.63. |
| **Navigator Bridge for FH6** (optional) | Moves the FH6 My Designs cursor to a livery position selected in Organizer. |

**v0.4.63 Preview** (release date YYYY-MM-DD: fill in at release) bundles the 3D preview tool, **Livery Viewer for FH6**. Each card in an Organizer report can open a 3D view of that livery applied to the car body. This version also aligns the settings and window style of the three tools, and the release ZIP now contains only the EXEs and the files they need to run.

> [!IMPORTANT]
> This is a Preview release. FH6's internal save-data and asset formats are not public specifications, and some parsing behavior is based on observations from real data. The 3D rendering of Livery Viewer for FH6 is experimental and does not exactly match the in-game appearance.

## What's new in v0.4.63 Preview

### Livery Viewer for FH6 (3D preview, experimental) is bundled

Each card in an Organizer report now has a "3D Preview (Experimental)" link. Clicking it shows the car with that livery in the Livery Viewer for FH6 window.

- The Viewer reads the FH6 game assets and the GameSave liveries as read-only input and renders them on your PC with WebGL2.
- Switching to another livery of the same car happens in the open window (about 1 second on the development PC).
- The first time a car is shown, preparation takes a while (about 10-20 seconds on the development PC). The prepared data is kept in `preview-cache`, so later views of the same car are faster.
- After you close the window, the Viewer waits hidden in the background for 10 minutes so the next view opens faster.
- Liveries that use the game's logo stickers require an FH6 GameDB that the user has prepared locally (not included in the distribution).

### The three tools share settings and style

Organizer, Viewer, and Navigator Bridge share the language, theme (Follow system / Light / Dark), FH6 installation and GameSave folders, and similar settings, and use the same colors, fonts, and spacing. Navigator Bridge also gains language and theme switching.

### Release package

The release ZIP contains only the EXEs and the files they need to run. The Python version (`python` folder) included in earlier releases is no longer included. The source code (Python and Rust) is published in this repository. Bundled third-party components and their licenses are listed in `THIRD-PARTY-NOTICES.txt` in the ZIP.

Navigator Bridge for FH6 is **v0.0.29**. The bundled vehicle metadata is updated to the **2026-11 update / 667 vehicles / package revision 4**.

See [docs/releases/CHANGELOG.md](docs/releases/CHANGELOG.md) (Japanese) for the detailed change history.

## Main features

- List downloaded paint designs by vehicle
- Resolve vehicle name, manufacturer, year, and related information from FH6 assets where available
- Local HTML report with embedded thumbnails
- Excel output with thumbnails
- Search, filtering, and sorting by vehicle, manufacturer, creator, year, title, and other fields
- 3D view of a livery applied to the car body from each report card (Livery Viewer for FH6, experimental)
- Japanese and English Organizer GUI / Viewer / Navigator Bridge / generated HTML / Excel output
- Language, theme (Follow system / Light / Dark), and folder settings shared by the three tools
- `/` shortcut to focus the search field and `?` shortcut to open Help
- Live-search optimizations for large reports
- FH6 My Designs order view
- Current real-slot sequence number and `#columnU / #columnD` FH6-position display
- Keep / Delete candidate / Undecided organization states
- Favorites, Review later, tags, and notes
- Persistent creator colors with a dedicated creator-color manager
- Creator upload-date display and newest-first / oldest-first sorting
- Similar-thumbnail candidate review
- Re-download duplicate comparison and organization
- Organization-state changes and “Deleted in FH6” marking from comparison views
- Per-vehicle organization progress
- Temporary “Deleted in FH6” state with search, restore, and current-position recalculation
- Numeric creation-method audit score with high-to-low / low-to-high sorting
- Undo / Redo
- User-data and decision backups/restores, including data outside the current report
- CSV export
- In-browser diagnostics
- Optional Navigator Bridge for FH6 integration

The creation-method audit score checks five structural/statistical signals in saved `C_livery` data (shapes, colors, transform values, and similar) and shows the number of matching signals as `0/5` through `5/5`. It is not a determination of the creation method, a probability or confidence value, a paint-quality score, or an evaluation of the creator.

## Livery Viewer for FH6

**Livery Viewer for FH6** is an experimental tool that shows a report's livery in 3D on the FH6 car body. It reads the FH6 game assets and the GameSave livery (`Livery_*` folder) as read-only input and renders them on your PC (WebGL2).

1. Start `Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe` and run **Register Organizer integration** once in the settings window.
2. Generate a report in Organizer. Reports that could confirm the FH6 installation location show "3D Preview (Experimental)" on each card.
3. Click "3D Preview (Experimental)". The Viewer window shows the car with that livery. Clicking another livery switches the view in the same window.

You can also choose a `Livery_*` folder in the Viewer settings window. From the preview screen, you can save the current view or a six-direction image as JPEG / PNG.

The Windows integration registration stores the Viewer's **absolute path**. If you move the Viewer folder, run "Register Organizer integration" again from the moved Viewer. Before removing the Viewer, run "Remove Organizer integration" in the settings window.

On first launch, the Viewer downloads three.js (MIT License), which it uses for 3D rendering, from the official npm distribution (an internet connection is required). The downloaded files are verified against fixed checksums and reused afterwards.

### GameDB

Liveries that use the game's logo stickers require the FH6 GameDB (a decrypted SQLite file) to be shown. Liveries without logo stickers can be shown without the GameDB.

The GameDB is not included in the distribution or in this repository, and Organizer and the Viewer do not create, decrypt, copy, or modify it. Only a GameDB that the user has prepared locally and placed at the following location is used, read-only:

```text
%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite
```

See [docs/3D-PREVIEW-GAMEDB.md](docs/3D-PREVIEW-GAMEDB.md) (Japanese) for details.

## Navigator Bridge for FH6

**Navigator Bridge for FH6 v0.0.29** is an optional companion tool that moves the cursor in FH6's **My Designs** screen to a paint position selected in Organizer.

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
- switch between the EXE and running from source (Python).

If you replace an EXE with a newer version while keeping the same folder and filename, registration normally does not need to be repeated.

For detailed behavior and setup, see [docs/releases/NAVIGATOR-BRIDGE-README_EN.txt](docs/releases/NAVIGATOR-BRIDGE-README_EN.txt).

## Safety

### Livery Organizer for FH6 / Livery Viewer for FH6

Organizer and the Viewer treat the FH6 GameSave and FH6 game assets as **read-only inputs**.

They do not write, delete, move, rename, or overwrite the source data, and the GameSave directory cannot be used as a report-output location. Settings, caches, generated reports, and the Viewer's prepared data are stored outside the GameSave.

States such as Delete candidate or Deleted in FH6 (temporary) are Organizer-side organization data. They do not delete files from the GameSave.

None of Organizer, the Viewer, or Navigator Bridge has a network feature for sending the user's livery data to an external server. Livery Viewer for FH6 connects externally only on first launch, to download three.js from the official npm distribution (`registry.npmjs.org`).

### Navigator Bridge for FH6

Navigator Bridge does not modify the FH6 GameSave, game files, or game memory.

The current Bridge accepts an FH6 target only when its title, after trimming outer spaces, **exactly matches `Forza Horizon 6`** and the owning process is **`forzahorizon6.exe`**. If more than one window satisfies both checks, Bridge stops instead of choosing one automatically. Before every normal Left / Right / Down movement key, Bridge revalidates that the same target HWND is still foreground, has the exact title, and belongs to the FH6 process; if any check fails, the next movement key is not sent.

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

## Release package

GitHub Releases provides a ZIP containing the EXEs, the files they need to run, and the Japanese / English documentation.

```text
Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
Livery-Viewer-for-FH6\
  Livery-Viewer-for-FH6.exe
  (files the Viewer needs to run)
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
LICENSE.txt
THIRD-PARTY-NOTICES.txt
```

Livery Viewer for FH6 uses the files inside the `Livery-Viewer-for-FH6` folder. Keep the folder together; do not move the EXE out of it by itself.

Livery Viewer for FH6 and Navigator Bridge for FH6 are optional. If you do not use them, you do not need to start them.

The release ZIP does not include the source code or a Python version. The source code is published in this repository. The Build Kit and detailed instructions for building the Windows EXEs are not included in the distribution or in this repository.

## Repository layout

| Location | Contents |
| --- | --- |
| `src/organizer/` | Livery Organizer for FH6 (Python) |
| `src/navigator_bridge/` | Navigator Bridge for FH6 (Python) |
| `src/viewer/` | Livery Viewer for FH6 (Python, JavaScript, Rust) |
| `docs/` | Internationalization policy, 3D preview and GameDB, release documents (`docs/releases/`) |
| `tests/` | Tests |

`src/viewer/tools/livery/native/lo4fh6_native/` is the Rust source of a component that speeds up some of the Viewer's computations. The release Viewer includes the component (DLL) built from this source. When running from source, the component is not present and the same computations run in Python (they take longer).

## Languages and documentation

The user-facing UI of Organizer, Viewer, and Navigator Bridge currently supports **Japanese** and **English**. The language and theme are shared by the three tools, and a language change takes effect on the next launch. Generated HTML and Excel output use the Organizer language that is active when the report is generated.

Livery titles, descriptions, creator names, vehicle/proper-name data, tags, notes, IDs, and similar user/game data are not translated.

Japanese is the source/primary language for the project's main documentation. English is maintained as the common second documentation language. The release ZIP also includes `README_EN.txt` and `NAVIGATOR-BRIDGE-README_EN.txt`.

If you find awkward or incorrect English, feedback is welcome. When possible, please propose the correction as a change to:

```text
src/organizer/locales/en.py
```

A pull request with the relevant locale change is especially helpful. Translation changes may take time to review because wording, feature meaning, terminology consistency, tests, and UI/layout effects are checked before incorporation.

Additional UI languages may be added in the future, but a complete documentation set will not necessarily be maintained for every language. For languages other than Japanese, use the English documentation as the common reference.

See [docs/I18N_EN.md](docs/I18N_EN.md) for the translation and internationalization policy.

## Demo

A public demo generated from anonymized/dummy data is available here:

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

For safety, the public demo disables launching Navigator Bridge and sending keys to FH6. The 3D preview (Livery Viewer for FH6) is not available in the public demo.

## Supported environment

Primary target environment:

- Windows 11
- PC version of Forza Horizon 6
- A common desktop web browser for generated HTML reports

Livery Viewer for FH6 additionally requires:

- A GPU that supports WebGL2
- The Microsoft Edge WebView2 Runtime (included with Windows 11)
- An internet connection on first launch to download three.js

Development and verification are centered on the Microsoft Store / Xbox App version.

Users have reported successful Organizer use with the Steam version, but Steam is not an officially verified development environment and save/game paths or file layouts may differ. Navigator Bridge and Livery Viewer for FH6 are also not formally verified on Steam. Navigator Bridge requires both the exact `Forza Horizon 6` window title and a verifiable FH6 owning process.

## Running the tools

### Windows EXE

- **Organizer**: run `Livery-Organizer-for-FH6.exe`.
- **Livery Viewer for FH6**: run `Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe` and, on first use, run "Register Organizer integration".
- **Navigator Bridge**: run `Navigator-Bridge-for-FH6.exe` and, on first use, run **Register Integration**.

After the Organizer GUI starts, confirm the FH6 save location, FH6 installation path, and report-output location as needed. They are normally detected automatically.

Fully closing FH6 before scanning is recommended.

### Running from source

Organizer and Navigator Bridge run on Python 3.12 or later using only the standard library (Tkinter for the GUI). From this repository's folder, run:

```powershell
python src\organizer\livery-organizer-for-fh6.py
python src\navigator_bridge\navigator-bridge-for-fh6.py
```

With `uv`:

```powershell
uv run src\organizer\livery-organizer-for-fh6.py
uv run src\navigator_bridge\navigator-bridge-for-fh6.py
```

Navigator Bridge can also be started without a console window from `src\navigator_bridge\start-navigator-bridge-quiet.vbs` (requires `uv`). To use a Bridge running from source with Organizer, start that Bridge by itself and run **Register Integration**.

Livery Viewer for FH6 uses `uv` and Python 3.12. Run `src\viewer\start-viewer-gui.cmd` (or `start-viewer-gui-quiet.vbs` to start without a console window) to open the Viewer settings window. On first launch, `uv` downloads the required Python packages (Pillow, numpy, psutil, and pywebview). See [src/viewer/README.md](src/viewer/README.md) (Japanese) for details.

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

For settings and cache locations, see "Settings / cache locations" in the release [README_EN.txt](docs/releases/README_EN.txt).

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

The 3D rendering of Livery Viewer for FH6 is an independent reproduction from the game files and does not exactly match the in-game appearance. It has not been verified to match the Xbox or PC game screen.

Navigator Bridge does not read the actual current cursor position from FH6. If key input is dropped because of system/game load or the screen is not in the expected state, the cursor can end up at a different position. Adjust the timing settings when necessary and confirm the final state in FH6.

When reporting a problem, do not publish private information or your actual GameSave files.

## Unofficial project

This is an unofficial, non-commercial fan-made project. It is not affiliated with, endorsed by, sponsored by, or approved by Microsoft, Xbox, Turn 10 Studios, Playground Games, or the Forza franchise.

It is not intended to automate game progression, competition, economy, rankings, or similar gameplay systems.

Product names, service names, trademarks, and other rights belong to their respective owners. Users are responsible for reviewing the rules and terms that apply to their use.

## License

MIT License. The software is provided as-is. Back up important data as appropriate and use the software at your own responsibility.

For third-party components bundled in the release ZIP and their licenses, see `THIRD-PARTY-NOTICES.txt` in the ZIP.
