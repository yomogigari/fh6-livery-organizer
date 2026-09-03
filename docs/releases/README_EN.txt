Livery Organizer for FH6 v0.4.59 Preview
========================================

Release date: 2026-09-04

Livery Organizer for FH6 is a Windows tool for listing, searching, and organizing
paint designs (liveries) downloaded in the PC version of Forza Horizon 6.

v0.4.59 adds Japanese/English localization for the Organizer desktop GUI,
generated HTML report, and Excel report. It also reduces unnecessary work during
live search in large HTML reports.

The optional Navigator Bridge for FH6 is updated to v0.0.27. Bridge now treats a
window as FH6 only when the window title, after trimming outer spaces, exactly
matches "Forza Horizon 6". A browser, GitHub page, Organizer window, or another
application that merely contains the game name is rejected.


■ Release files

Livery-Organizer-for-FH6.exe
Navigator-Bridge-for-FH6.exe
README.txt
README_EN.txt
NAVIGATOR-BRIDGE-README.txt
NAVIGATOR-BRIDGE-README_EN.txt
CHANGELOG.md
python\livery-organizer-for-fh6-v0459.py
python\i18n.py
python\navigator-bridge-for-fh6-v027.py
python\locales\__init__.py
python\locales\ja.py
python\locales\en.py

Organizer can be used as either the EXE or Python version.
The Python Organizer uses the localization modules in the same python folder, so
keep i18n.py and the locales folder together with the Organizer script.
Navigator Bridge can also be used as either the EXE or Python version.
Navigator Bridge is optional; Organizer's listing, search, organization, CSV,
and Excel features do not require it.

The Build Kit and detailed instructions for rebuilding the Windows EXEs are not
included in the normal distribution.


■ Language and documentation

Organizer user-facing UI currently supports Japanese and English.

The language selection is saved in settings.json and takes effect on the next
launch. Generated HTML and Excel reports use the Organizer language that is
active when the report is generated.

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


■ Main features

- Search, filtering, and sorting by vehicle, manufacturer, year, creator, title,
  and other fields
- Keep / Delete candidate / Undecided organization states
- Favorites, Review later, tags, and notes
- Per-vehicle organization progress and unfinished-vehicle navigation
- Undo / Redo
- User-data and decision backup / restore
- CSV output and Excel output with thumbnails
- FH6 My Designs order view
- Real-slot numbers such as #001 and FH6 positions such as #001U / #001D
- Position or vehicle-name jump within FH6 My Designs order
- FH6 display date in DD/MM/YYYY format
- Similar-design comparison by image or creator/title match
- Separate handling of identical re-downloaded liveries that currently occupy
  different GameSave slots
- Dedicated re-download duplicate review
- Temporary "Deleted in FH6" state that recalculates remaining positions
- FH6 move-target selection from normal lists and comparison dialogs
- F key or Move to selected design in FH6 to send a target to Navigator Bridge
- / shortcut to focus search
- ? shortcut to open Help
- Optimized live search for large reports

Organizer-side organization actions do not directly delete or modify livery
files in the FH6 GameSave.


■ Running Organizer

EXE:
Livery-Organizer-for-FH6.exe

Python:
From the folder where you extracted the release ZIP, run:
python python\livery-organizer-for-fh6-v0459.py

With uv:
uv run python\livery-organizer-for-fh6-v0459.py

Keep python\i18n.py and the python\locales folder in place. They contain the
Japanese/English UI resources required by the Python Organizer.

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


■ Navigator Bridge for FH6 v0.0.27

Navigator Bridge is an optional companion tool that moves the FH6 My Designs
cursor to a paint position selected in Organizer.

Organizer may show a target such as:

#603 / #302U

#603 is the current real-slot sequence number.
#302U means column 302, upper row, in FH6 My Designs.

Select the number and press F or use Move to selected design in FH6. Organizer
passes the target, the current final real-slot number, and movement timing
settings to Bridge.

Bridge calculates the cursor moves from #001U, foregrounds FH6, checks that the
foreground title is exactly "Forza Horizon 6", and sends the fixed Left / Right /
Down cursor sequence through the standard Windows input API.

On first use, start Bridge by itself and run Register Integration once.
The navigatorbridgeforfh6:// Windows registration stores Bridge's absolute path.
Register again if you move/rename Bridge or switch between the EXE and Python
versions. Replacing an EXE at the same path and filename normally does not require
registration again.

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

Bridge only accepts a target window whose title, after trimming outer spaces,
exactly matches "Forza Horizon 6". It checks the foreground window again before
input and sends no movement keys if the check fails.

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

Development and verification are centered on the Microsoft Store / Xbox App
version.

Users have reported successful Organizer use with the Steam version, but Steam
is not an officially verified development environment. Navigator Bridge is also
not formally verified on Steam and requires the FH6 window title to match
"Forza Horizon 6".

The Python version uses only the Python standard library and Tkinter.


■ Settings / cache locations

Organizer settings:
%APPDATA%\Livery-Organizer-for-FH6\settings.json

Organizer / Bridge shared navigation settings:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json

Vehicle DB cache:
%LOCALAPPDATA%\Livery-Organizer-for-FH6\cache\

Navigator Bridge IPC / log:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\


■ Demo

https://yomogigari.github.io/fh6-livery-organizer/fh6-livery-organizer-demo.html

The public demo uses anonymized/dummy data and disables launching Navigator Bridge
and sending keys to FH6.


■ Preview notice / unofficial project

FH6 internal data formats are not public specifications, and some parsing behavior
is based on observations from real data. Game updates, format/location changes,
or environment differences may require future changes.

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

MIT License.
The software is provided as-is. Back up important data as appropriate and use the
software at your own responsibility.
