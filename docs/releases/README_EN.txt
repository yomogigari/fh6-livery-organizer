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

Extracting the release ZIP (Livery-Organizer-for-FH6-v0.4.63-preview.zip) creates
a folder named after the version (Livery-Organizer-for-FH6-v0.4.63-preview) that
contains the following files:

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

When you update from an earlier version and use the new folder, run
"Register Organizer integration" in the Viewer and "Register integration" in
Navigator Bridge again (both registrations store the absolute path of the EXE).

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
the three tools. A language change takes effect on the next launch in Organizer
and Navigator Bridge, and immediately in the Viewer settings window.
The 3D preview screen starts in the Windows display language rather than the
shared language setting (English unless it is Japanese), and you can switch it
with "Language" at the top of the screen. It uses dark colors only.

Generated HTML and Excel reports use the Organizer language that is active when
the report is generated.

Livery titles, descriptions, creator names, vehicle/proper-name values, tags,
notes, IDs, and similar user/game data are not translated.

Japanese is the source/primary documentation language. English is maintained as
the common second documentation language.

If you find awkward or incorrect English, feedback is welcome. When possible,
please propose the correction as a concrete change to the GitHub source files:

- Organizer: src/organizer/locales/en.py
- Livery Viewer for FH6: the translation table in src/viewer/viewer_gui.py
  (settings window) and src/viewer/tools/livery-inspector/locales/en.js (3D screen)
- Navigator Bridge: the translation table in
  src/navigator_bridge/navigator-bridge-for-fh6.py

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
- The first time a car is shown, preparation takes about 10 seconds on the
  development PC. The very first time the Viewer opens on a PC, it takes about
  15-28 seconds because the rendering components are built for the first time.
  The prepared data is kept in preview-cache, so later views of the same car
  are faster.
- The next livery you open also uses the same window (switching to another
  livery of the same car takes about 1 second on the development PC).
- After you close the window, the Viewer waits hidden in the background for
  10 minutes so the next view opens faster, then exits. While it waits, it still
  uses memory and remains visible in Task Manager.
- When Organizer starts, it starts the Viewer without a window and keeps it
  ready, so the first 3D preview opens a little faster (about 0.3 seconds on the
  development PC; on by default). The Viewer stays
  while Organizer is running, and ends 10 minutes after Organizer closes, as
  above. Turn this on or off with the "Prepare the 3D preview when Organizer
  starts" check box in the Viewer settings window. It does nothing when the
  Organizer integration is not registered.
- The rendering does not exactly match the in-game appearance. It has not been
  verified to match the Xbox or PC game screen.

The Viewer only reads and displays liveries. It does not write to the GameSave
or the FH6 installation.


■ Using Livery Viewer for FH6

1. Put the release folder where you will keep it, then start
   Livery-Viewer-for-FH6\Livery-Viewer-for-FH6.exe and run
   "Register Organizer integration" once in the settings window.
   The Windows registration stores the Viewer's absolute path, so decide the
   location first. If you move the Viewer to another folder, run
   "Register Organizer integration" again from the moved Viewer.
   After registering, you can close the settings window. Opening a 3D preview
   starts the Viewer automatically.
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

The first time you open a 3D preview, the Viewer downloads three.js (MIT License),
which it uses for 3D rendering, from the official npm distribution (an internet
connection is required).
The downloaded files are verified against fixed checksums and reused afterwards.


■ Livery Viewer for FH6 and the GameDB

With the FH6 GameDB (a decrypted SQLite file of the game's database), Livery
Viewer for FH6 can show liveries more accurately. Without the GameDB, liveries
can still be shown in 3D, with the following differences:

- Game logo stickers: their images are looked up in the GameDB. Without it,
  they are omitted.
- Wheels and tires: the game's wheel and tire placement, sizes, and types come
  from the GameDB. Without it, simplified wheels and tires are shown.
When something is omitted or simplified because the GameDB is missing, the
Viewer shows a notice at the top of the screen.

The GameDB is not included in the distribution, and Organizer and the Viewer do
not create, decrypt, copy, or modify it. A GameDB that the user has prepared
locally is used, read-only, when it is placed at the following location:

%USERPROFILE%\Documents\Livery-Organizer-for-FH6\game-data\fh6-gamedb.sqlite

For other ways to specify it (such as an environment variable), see
docs/3D-PREVIEW-GAMEDB.md (Japanese) in the GitHub repository.

How to prepare the GameDB is not covered. If you prepare one, do so at your own
responsibility and check the game's terms of use.


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
- F key or Move to Selected Design in FH6 to send a target to Navigator Bridge
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

Select the number and press F or use Move to Selected Design in FH6. Organizer
passes the target, the current final real-slot number, and movement timing
settings to Bridge.

Bridge calculates the cursor moves from #001U, foregrounds the unique FH6 window
that passed the title + process checks, and sends the fixed Left / Right / Down
cursor sequence through the standard Windows input API.

On first use, start Bridge by itself and run "Register integration" once.
The navigatorbridgeforfh6:// Windows registration stores Bridge's absolute path
(see "Moving, renaming, or removing Navigator Bridge" below).

If the browser asks whether to open an external app, check the request and
allow it. If Bridge is already running, the request is passed to the running
instance without opening another window. When Organizer starts Bridge only for
a move, Bridge does not show its normal window.

See NAVIGATOR-BRIDGE-README_EN.txt for detailed behavior, timing settings, and
safety boundaries.


■ Finding and applying a design with Organizer + Navigator Bridge

FH6 My Designs shows only four items for each livery: thumbnail, title, creator,
and the creator's upload date. As downloaded liveries increase, it becomes hard
to find the design you want from the FH6 screen alone.

1. In Organizer, search and filter to find the livery you want to apply to the
   current car.
2. Click a number such as #603 / #302U, then press F or use
   "Move to Selected Design in FH6".
3. Navigator Bridge moves the cursor to the target position in FH6 My Designs.
4. Check the target in FH6 and run "Load Design" yourself.
5. The livery is applied to the car you are currently driving.

To check how the livery looks on the car first, you can open
"3D Preview (Experimental)" before moving. Navigator Bridge does not automate
loading, selection, or confirmation.


■ Cleaning up My Designs with "Deleted in FH6 (temporary)" + Navigator Bridge

When you delete a livery in FH6 My Designs, the real-slot numbers and FH6
positions of the liveries after it move forward. Organizer does not detect the
deletion automatically. Mark the same design as "Deleted in FH6" in
"FH6 My Designs order" so Organizer hides that card and immediately recalculates
the positions of the remaining liveries. The next Navigator Bridge move uses the
recalculated position.

1. Choose a livery to clean up from delete candidates, re-download duplicates,
   similar-design comparison, or another list.
2. Click its number and press F or use "Move to Selected Design in FH6".
3. Navigator Bridge moves the cursor to the target position in FH6 My Designs.
4. Check the livery in FH6 and delete it yourself if it is not needed.
5. Return to Organizer and mark the card as "Deleted in FH6" in
   "FH6 My Designs order".
6. Organizer recalculates the remaining positions, so the next number matches
   the current FH6 screen.
7. Choose the next target and repeat.

Normal Bridge movement is calculated from #001U. If "Return to #001U" is off,
put the FH6 cursor on #001U before moving. Turning on "Return to #001U" makes the
starting point consistent for repeated cleanup.

"Deleted in FH6 (temporary)" is stored in the localStorage of that generated
HTML only. It does not modify the GameSave and is not carried into a newly
generated report.


■ Navigator Bridge safety boundary

Normal movement can send only:

- Left
- Right
- Down

If Return to #001U is enabled, Bridge additionally sends one fixed Esc followed
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
Return to #001U                OFF
Wait after Esc                 500 ms
Wait after Return              800 ms

Shared setting file:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Navigation settings changed in the Organizer HTML are saved in the browser's
localStorage. "Save shared settings" also saves them to the setting file shared
with Bridge, and they are used as the initial values the next time you generate
a new Organizer HTML report.


■ Environment

Primary target:
Windows 11
PC version of Forza Horizon 6

Livery Viewer for FH6 additionally requires:
- a GPU that supports WebGL2
- the Microsoft Edge WebView2 Runtime (included with Windows 11)
- an internet connection the first time you open a 3D preview, to download three.js

Development and verification are centered on the Microsoft Store / Xbox App
version.

Users have reported successful Organizer use with the Steam version, but Steam
is not an officially verified development environment. Navigator Bridge and
Livery Viewer for FH6 are also not formally verified on Steam. Navigator Bridge
requires the FH6 window title to exactly match "Forza Horizon 6" and the owning
process to be confirmed as FH6.

For running the tools from the source code with Python, see the GitHub repository.


■ Settings / cache locations

Organizer settings:
%APPDATA%\Livery-Organizer-for-FH6\settings.json

Settings shared by the three tools (language, theme, FH6 installation and
GameSave folders, and similar):
%APPDATA%\Livery-Organizer-for-FH6\desktop-suite-settings.json

Organizer / Bridge shared navigation settings:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Organizer caches (vehicle DB and creation-method audit):
%LOCALAPPDATA%\Livery-Organizer-for-FH6\cache\

Navigator Bridge IPC / log:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\

Livery Viewer for FH6 settings, logs, downloaded three.js, and window (WebView2) data:
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\
(This is a different folder from Organizer's %LOCALAPPDATA%\Livery-Organizer-for-FH6,
although the names are similar. The webview-profile folder inside it makes later
starts faster; if you delete it, the next start is as slow as the very first one.)

Livery Viewer for FH6 prepared data (per-car models, images, and similar):
When opened from Organizer, preview-cache inside the report-output folder
(by default %USERPROFILE%\Documents\Livery-Organizer-for-FH6\preview-cache\).
When opened from the Viewer settings window, the location in its "preview-cache"
field.

To keep it from growing:
- only the three most recent livery preparations are kept;
- the body shapes of cars other than the three most recently used are deleted
  and rebuilt the next time the car is opened (which takes extra time);
- data made by older Viewer versions is deleted automatically.

Reference: on the developer's PC, after showing all 999 downloaded liveries in
the GameSave one by one, preview-cache was about 0.7 GB.

No size limit is set by default. To set one, add a value in GB such as
"vehicle_cache_limit_gb": 2 to preview-settings.json (below). When the cache
exceeds 90% of the limit, it is reduced to 75%. The car being shown and data used
within the last 7 days are kept, so the cache can slightly exceed the limit.

Delete preview-cache only after the Viewer has ended (10 minutes after closing
its window, and after closing Organizer if Organizer startup preparation is on).
It is rebuilt the next time a car is shown.

Viewer settings (preview-settings.json):
%LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-settings.json
- viewer_keep_alive_seconds: how long the Viewer waits in the background after
  its window closes (seconds; 0 disables waiting; default 600)
- viewer_standby_with_organizer: Organizer startup preparation (true / false;
  default true; normally changed with the check box in the Viewer settings window)
- vehicle_cache_limit_gb: size limit of preview-cache (GB; no limit by default)

If settings or caches from an older version are found, they are migrated as
needed from the older FH6-Livery-Organizer locations and older localStorage keys
for compatibility.


■ Moving or removing Livery Viewer for FH6

The Organizer integration registration in Windows stores the Viewer's absolute
path. If you move the Livery-Viewer-for-FH6 folder, start the moved Viewer and run
"Register Organizer integration" again in the settings window.

To remove the Viewer, first start it and run "Remove Organizer integration" in
the settings window to remove the liveryorganizerpreviewforfh6:// registration.
Then, after the Viewer has ended (10 minutes after closing its window, and after
closing Organizer if Organizer startup preparation is on; to end it immediately,
you can end Livery-Viewer-for-FH6.exe in Task Manager), delete the
Livery-Viewer-for-FH6 folder and, if no longer needed, the Viewer locations
listed above. Files in use cannot be deleted.


■ Moving, renaming, or removing Navigator Bridge

The Organizer integration registration in Windows stores Navigator Bridge's
absolute path. Start the new Bridge by itself and run "Register integration"
again if you:

- move Bridge to another folder;
- rename the Bridge file;
- switch between the EXE and running from source (Python);
- extract a newer release ZIP into a different folder and use it from there;
- registered the Bridge from the python folder of the v0.4.62 release ZIP.

You do not need to remove the registration first. Registering from the current
Bridge updates the navigatorbridgeforfh6:// registration to the new location.
The "Running as" and "Registered to" lines in the Bridge window show the current
mode and the registered target. If the registered target does not match the
current Bridge, the window shows "Organizer integration: needs to be registered
again".

Replacing the EXE with a newer version while keeping the same folder and file
name normally does not require registration again, because the registered
absolute path does not change.

To remove Navigator Bridge, first start it by itself and use "Remove" in the
Organizer integration area to remove the navigatorbridgeforfh6:// registration.
Then delete the Bridge files and, if no longer needed, the Bridge local folder
listed above. To keep the shared navigation settings, do not delete
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json.


■ Applied-livery detection

The reference search that estimates the currently applied livery is paused.
Normal reports currently treat the applied-livery state as undetermined.


■ Demo

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

The public demo uses anonymized/dummy data and disables launching Navigator Bridge
and sending keys to FH6. The 3D preview (Livery Viewer for FH6) is not available
in the demo. The demo was generated with v0.4.62.


■ Troubleshooting (Livery Viewer for FH6)

- Clicking "3D Preview (Experimental)" does nothing:
  check that you ran "Register Organizer integration" in the Viewer settings
  window and that the browser is not waiting for permission to open an external
  app. If you moved the Viewer folder, register again.
- The first start seems to stop:
  the very first start on a PC takes about 15-28 seconds. The first time you open
  a 3D preview, an internet connection is needed to download three.js.
- A car is not shown or an error appears:
  check the error on the screen and these log files:
  %LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\preview-bridge.log (preparation and startup)
  %LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\viewer-gui.log (settings window)
- The Viewer does not end after closing its window:
  it waits in the background for 10 minutes after the window closes. If Organizer
  startup preparation is on, it stays until Organizer closes.

When reporting a problem, include the version, steps, error text, and the log
files above. Do not attach game files, personal save data, or private livery
files in public places.


■ Safety

Livery Organizer for FH6 and Livery Viewer for FH6 treat the FH6 GameSave and the
FH6 game assets as read-only input. They do not write, delete, move, rename, or
overwrite them. The GameSave cannot be chosen as the report output location.

None of Organizer, the Viewer, or Navigator Bridge has a network feature for
sending your livery data to an external server. Livery Viewer for FH6 connects
to the internet only to download three.js from the official npm distribution
(registry.npmjs.org) the first time you open a 3D preview.


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
