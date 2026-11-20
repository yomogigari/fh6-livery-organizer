Livery Organizer for FH6 v0.4.63 Preview
========================================

Release date: YYYY-MM-DD (fill in at release)

Livery Organizer for FH6 is a Windows tool for listing, searching, and organizing
paint designs (liveries) downloaded in the PC version of Forza Horizon 6.

This distribution contains three tools:

- Livery Organizer for FH6 (main tool)
  Lists, searches, and organizes downloaded liveries and generates HTML / Excel reports.
- Livery Viewer for FH6 (optional, experimental)
  Shows a report's livery in 3D on the FH6 car body. Bundled starting with this version.
- Navigator Bridge for FH6 (optional)
  Moves the FH6 My Designs cursor to a livery position selected in Organizer.

This release is a preview version.

v0.4.63 bundles the 3D preview tool, Livery Viewer for FH6. Each card in an
Organizer report can open a 3D view of that livery applied to the car body.
Livery Viewer for FH6 is experimental, and its rendering does not exactly match
the in-game appearance.

The three tools now share settings such as the language, theme (Follow system /
Light / Dark), and the FH6 installation and GameSave folders, and use the same
window style.

The release ZIP contains only the EXEs and the files they need to run. The Python
version (python folder) included in earlier releases is no longer included. The
source code is published in the GitHub repository.

The bundled vehicle metadata is updated to the 2026-11 update with 667 vehicles
and metadata package revision 4.


■ Release files

Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe (plus the files it needs in the same folder)
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
LICENSE.txt
THIRD-PARTY-NOTICES.txt

Livery Viewer for FH6 uses the files inside the Livery-Viewer-for-FH6 folder.
Keep the folder together; do not move the EXE out of it by itself.

Livery Viewer for FH6 and Navigator Bridge for FH6 are optional. Organizer's
listing, search, organization, CSV, and Excel features do not require them.

The source code (Python and Rust) is published in the GitHub repository:
https://github.com/yomogigari/fh6-livery-organizer
The Build Kit and detailed instructions for building the Windows EXEs are not
included in the distribution or in the repository.


■ Language, theme, and documentation

The user-facing UI of Organizer, Viewer, and Navigator Bridge supports Japanese
and English. The language and theme (Follow system / Light / Dark) are shared by
the three tools. A language change takes effect on the next launch.

Generated HTML and Excel reports use the Organizer language that is active when
the report is generated.

Livery titles, descriptions, creator names, vehicle/proper-name values, tags,
notes, IDs, and similar user/game data are not translated.

Japanese is the source/primary documentation language. English is maintained as
the common second documentation language.

If you find awkward or incorrect English, feedback is welcome. When possible,
please propose the correction as a concrete change to the GitHub source file:

src/organizer/locales/en.py

A pull request with the relevant locale change is especially helpful.
Translation changes may take time to review because feature meaning, terminology,
layout effects, and regression tests are checked before incorporation.

If additional UI languages are added later, a complete documentation set will
not necessarily be maintained for each language. Users who do not read Japanese
should use the English documentation as the common reference.


■ Livery Viewer for FH6

Livery Viewer for FH6 is an experimental tool that shows a report's livery in 3D
on the FH6 car body. It reads the FH6 game assets and the GameSave livery
(Livery_* folder) as read-only input and renders them on your PC (WebGL2).

- Open a livery from the "3D Preview (Experimental)" link on each report card.
- You can also choose a Livery_* folder in the Viewer settings window.
- The first time a car is shown, preparation takes a while (about 10-20 seconds
  on the development PC). The prepared data is kept in preview-cache, so later
  views of the same car are faster.
- Switching to another livery of the same car happens in the open window
  (about 1 second on the development PC).
- After you close the window, the Viewer waits hidden in the background for
  10 minutes so the next view opens faster, then exits.
- The rendering does not exactly match the in-game appearance. It has not been
  verified to match the Xbox or PC game screen.

The Viewer only reads and displays liveries. It does not write to the GameSave
or the FH6 installation.


■ Using Livery Viewer for FH6

1. Start Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe and run
   "Register Organizer integration" once in the settings window.
   If you move the Viewer to another folder, run "Register Organizer integration"
   again from the moved Viewer. The Windows registration stores the Viewer's
   absolute path.
2. Generate a report in Organizer. Reports that could confirm the FH6
   installation location show "3D Preview (Experimental)" on each card.
3. Click "3D Preview (Experimental)". If the browser asks whether to open an
   external app, check the request and allow it. Organizer and the Viewer use
   liveryorganizerpreviewforfh6:// for local integration.
4. The Viewer window shows the car with that livery. Clicking
   "3D Preview (Experimental)" for another livery switches the view in the same
   window.

To open a livery from the settings window, check "FH6 folder", "Livery_* folder",
and "preview-cache", then run "Open 3D preview".

On first launch, the Viewer downloads three.js (MIT License), which it uses for 3D
rendering, from the official npm distribution (an internet connection is required).
The downloaded files are verified against fixed checksums and reused afterwards.


■ Livery Viewer for FH6 and the GameDB

Liveries that use the game's logo stickers require the FH6 GameDB (a decrypted
SQLite file) to be shown. Without the GameDB, such a livery cannot be shown in 3D.
Liveries without logo stickers can be shown without the GameDB.

The GameDB is not included in the distribution, and Organizer and the Viewer do
not create, decrypt, copy, or modify it. Only a GameDB that the user has prepared
locally and placed at the following location is used, read-only:

%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite

When the GameDB is available, it is also used for the car body composition and
for wheel dimensions and placement.


■ Main features

- Search, filtering, and sorting by vehicle, manufacturer, year, creator, title,
  and other fields
- Keep / Delete candidate / Undecided organization states
- Favorites, Review later, tags, and notes
- Persistent creator colors and a dedicated creator-color manager
- Creator upload-date display and newest-first / oldest-first sorting
- Per-vehicle organization progress and unfinished-vehicle navigation
- Undo / Redo
- User-data and decision backup / restore, including data outside the current report
- CSV output and Excel output with thumbnails
- FH6 My Designs order view
- Real-slot numbers such as #001 and FH6 positions such as #001U / #001D
- Position or vehicle-name jump within FH6 My Designs order
- Creator upload date in FH6-style DD/MM/YYYY format
- Similar-design comparison by image or creator/title match
- Separate handling of identical re-downloaded liveries that currently occupy
  different GameSave slots
- Dedicated re-download duplicate review
- Temporary "Deleted in FH6" state that recalculates remaining positions
- FH6 move-target selection from normal lists and comparison dialogs
- F key or Move to selected design in FH6 to send a target to Navigator Bridge
- 3D view of a livery from each report card with Livery Viewer for FH6 (experimental)
- / shortcut to focus search
- ? shortcut to open Help
- Optimized live search for large reports

Organizer-side organization actions do not directly delete or modify livery
files in the FH6 GameSave.


■ Running Organizer

Start Livery-Organizer-for-FH6.exe.

After the GUI starts, confirm these paths as needed:

- FH6 save location
- FH6 installation location
- report output location

They are normally detected automatically.
Fully closing FH6 before scanning is recommended.


■ Generated files

Normal mode primarily generates:

livery-organizer-for-fh6.html
livery-organizer-for-fh6.xlsx

Optional analysis JSON/CSV data can also be written under a data folder.
HTML-side exports use names such as:

livery-organizer-for-fh6-userdata.json
livery-organizer-for-fh6-decisions-backup.json
livery-organizer-for-fh6-decisions.csv
livery-organizer-for-fh6-decisions-filtered.csv

The normal HTML report embeds thumbnails and can usually be viewed as a
standalone file. Excel also embeds thumbnails.


■ Organizer data stored in the browser

The generated HTML stores organization data in browser localStorage, including:

- Keep / Delete candidate / Undecided
- Favorite
- Review later
- tags
- notes
- Deleted in FH6 (temporary)
- some UI settings

These values are not written back to the FH6 GameSave.

Deleted in FH6 (temporary) is specific to that generated HTML and is not carried
into a newly generated report. Use the built-in backup functions for data you
want to preserve.


■ Navigator Bridge for FH6 v0.0.29

Navigator Bridge is an optional companion tool that moves the FH6 My Designs
cursor to a paint position selected in Organizer.

Organizer may show a target such as:

#603 / #302U

#603 is the current real-slot sequence number.
#302U means column 302, upper row, in FH6 My Designs.

Select the number and press F or use Move to selected design in FH6. Organizer
passes the target, the current final real-slot number, and movement timing
settings to Bridge.

Bridge calculates the cursor moves from #001U, foregrounds the unique FH6 window
that passed the title + process checks, and sends the fixed Left / Right / Down
cursor sequence through the standard Windows input API.

On first use, start Bridge by itself and run Register Integration once.
The navigatorbridgeforfh6:// Windows registration stores Bridge's absolute path.
Register again if you move/rename Bridge or switch between the EXE and running
from the source code (Python). Replacing an EXE at the same path and filename
normally does not require registration again.

See NAVIGATOR-BRIDGE-README_EN.txt for detailed behavior, timing settings, and
safety boundaries.


■ Navigator Bridge safety boundary

Normal movement can send only:

- Left
- Right
- Down

If Reset to #001U is enabled, Bridge additionally sends one fixed Esc followed
by one fixed Return before normal movement.

Organizer or the external URI cannot supply arbitrary key codes, key names, or
key sequences.

Bridge accepts a target only when the title, after trimming outer spaces,
exactly matches "Forza Horizon 6" and the owning process is forzahorizon6.exe.
If multiple windows satisfy both checks, Bridge stops instead of selecting one.
Before every normal Left / Right / Down movement key, it revalidates that the same
HWND is foreground, has the exact title, and belongs to the FH6 process. If any
check fails, the next movement key is not sent.

Bridge does not modify game memory, executable code, game files, or GameSave.
It does not use image recognition and does not read the game's internal paint or
cursor position.

Bridge does not automate Load Design, paint selection, deletion, or confirmation.
Final actions remain the user's responsibility in FH6.

Because Bridge does not read back the real cursor position, dropped input or an
unexpected FH6 screen state can cause the cursor to end at the wrong location.
Increase timing values if necessary and confirm the final position yourself.


■ Default FH6 navigation timing

Key interval                    50 ms
After switching to FH6         500 ms
Horizontal -> vertical         200 ms
Extra wait after left wrap     400 ms
Reset to #001U                 OFF
Wait after Esc                 500 ms
Wait after Return              800 ms

Shared setting file:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json


■ Environment

Primary target:
Windows 11
PC version of Forza Horizon 6

Livery Viewer for FH6 additionally requires:
- a GPU that supports WebGL2
- the Microsoft Edge WebView2 Runtime (included with Windows 11)
- an internet connection for the first-time three.js download

Development and verification are centered on the Microsoft Store / Xbox App
version.

Users have reported successful Organizer use with the Steam version, but Steam
is not an officially verified development environment. Navigator Bridge and
Livery Viewer for FH6 are also not formally verified on Steam. Navigator Bridge
requires the FH6 window title to match "Forza Horizon 6".

For running the tools from the source code with Python, see the GitHub repository.


■ Settings / cache locations

Organizer settings:
%APPDATA%\Livery-Organizer-for-FH6\settings.json

Settings shared by the three tools (language, theme, FH6 installation and
GameSave folders, and similar):
%APPDATA%\Livery-Organizer-for-FH6\desktop-suite-settings.json

Organizer / Bridge shared navigation settings:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Vehicle DB cache:
%LOCALAPPDATA%\Livery-Organizer-for-FH6\cache\

Navigator Bridge IPC / log:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\

Livery Viewer for FH6 settings, logs, and downloaded three.js:
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\

Livery Viewer for FH6 prepared data (per-car models, images, and similar):
%USERPROFILE%\Documents\Livery-Organizer-for-FH6\preview-cache\
If you delete it, it is rebuilt the next time a car is shown (the first view of
that car takes longer). This version does not delete it automatically by size.

The time the Viewer waits in the background after its window closes can be
changed with viewer_keep_alive_seconds (seconds; 0 disables waiting) in
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-settings.json.


■ Moving or removing Livery Viewer for FH6

The Organizer integration registration in Windows stores the Viewer's absolute
path. If you move the Livery-Viewer-for-FH6 folder, start the moved Viewer and run
"Register Organizer integration" again in the settings window.

To remove the Viewer, first start it and run "Remove Organizer integration" in
the settings window to remove the liveryorganizerpreviewforfh6:// registration.
Then delete the Livery-Viewer-for-FH6 folder and, if no longer needed, the Viewer
locations listed above.


■ Demo

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

The public demo uses anonymized/dummy data and disables launching Navigator Bridge
and sending keys to FH6.


■ Safety

Livery Organizer for FH6 and Livery Viewer for FH6 treat the FH6 GameSave and the
FH6 game assets as read-only input. They do not write, delete, move, rename, or
overwrite them. The GameSave cannot be chosen as the report output location.

None of Organizer, the Viewer, or Navigator Bridge has a network feature for
sending your livery data to an external server. Livery Viewer for FH6 connects
to the internet only to download three.js from the official npm distribution
(registry.npmjs.org) on first launch.


■ Preview notice / unofficial project

FH6 internal data formats are not public specifications, and some parsing behavior
is based on observations from real data. Game updates, format/location changes,
or environment differences may require future changes.

The 3D rendering of Livery Viewer for FH6 is an independent reconstruction from
the game files and does not exactly match the in-game appearance.

This is an unofficial, non-commercial fan-made project. It is not affiliated
with, endorsed by, sponsored by, or approved by Microsoft, Xbox, Turn 10 Studios,
Playground Games, or the Forza franchise.

It is not intended to automate game progression, economy, rewards, rankings,
competition, or similar gameplay systems.

Product/service names, trademarks, and other rights belong to their respective
owners. Users are responsible for reviewing the rules and terms that apply.

Reference: Xbox Game Content Usage Rules
https://www.xbox.com/en-US/developers/rules


■ License / disclaimer

MIT License (included LICENSE.txt).
For third-party components and their licenses, see the included THIRD-PARTY-NOTICES.txt.
The software is provided as-is. Back up important data as appropriate and use the
software at your own responsibility.
