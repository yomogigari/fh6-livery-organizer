Navigator Bridge for FH6 v0.0.28
================================
Release date: 2026-09-11

Navigator Bridge for FH6 v0.0.28 further hardens FH6 window targeting. A target
must have the exact "Forza Horizon 6" title and be owned by forzahorizon6.exe.
Ambiguous multiple candidates are rejected, and the same target is revalidated
immediately before every normal movement key.

This document describes the current behavior and usage of the optional Bridge.


■ What Navigator Bridge for FH6 does

Navigator Bridge for FH6 is an optional companion tool for Livery Organizer for
FH6. It moves the cursor in FH6's My Designs screen to a paint position selected
in Organizer.

Organizer may display a position such as:

  #603 / #302U

#603 is the current real-slot sequence number.
#302U is column 302, upper row (U), in FH6 My Designs.

When you select the position and press F or choose Move to selected design in
FH6, Organizer passes the target position, current final real-slot number, and
navigation timing settings to Navigator Bridge.

Bridge calculates how many cursor inputs are required from #001U. It compares
the normal route to the right with the route that wraps from the first column to
the final column by pressing Left, and uses the route with fewer horizontal key
inputs. If the target is D (lower row), one Down input is sent after horizontal
movement.

For example, if the final real slot is #827 (final column #414U) and Organizer
selects #603 / #302U, moving right from #001U would require 301 Right inputs,
while using the left wrap requires 113 Left inputs. Bridge chooses the shorter
113-Left plan.

Bridge then finds a unique window whose title exactly matches "Forza Horizon 6"
and whose owning process is forzahorizon6.exe, brings it to the foreground, and
sends the planned cursor keys at the configured intervals using the standard
Windows input API. Before each normal movement key, the same HWND is revalidated.

In short:

  Select #603 / #302U in Organizer
       ↓
  Organizer passes target / final real slot / timing settings
       ↓
  Bridge calculates the cursor route from #001U
       ↓
  Bridge finds and foregrounds the exact FH6 window
       ↓
  Bridge verifies the foreground FH6 title
       ↓
  Bridge sends fixed Left / Right / Down cursor inputs
       ↓
  The cursor moves toward the requested paint position

Navigator Bridge is optional. Organizer's listing, search, organization, CSV,
and Excel features work without it.


■ Finding a downloaded paint and using Load Design

Bridge is useful not only when deleting/organizing unwanted paints, but also when
you want to find a previously downloaded paint and apply it to the car you are
currently driving.

FH6 My Designs normally shows only limited information for each paint, such as
thumbnail, title, creator, and upload date. As the number of downloaded paints
grows, finding one item only through the FH6 screen can become time-consuming.

Organizer can search/filter/sort by vehicle, manufacturer, year, creator, title,
and other information. Find the target in Organizer first, choose its
#real-slot / #columnU-or-D position, and send the target to Bridge. After Bridge
moves the FH6 cursor to that position, use FH6's Load Design action yourself.

Bridge does not perform Load Design, selection, or confirmation.


■ Organizing My Designs with Deleted in FH6 (temporary)

When you actually delete a paint in FH6, later My Designs slots shift forward.
Organizer does not read the deletion result back from the game automatically.

After deleting a paint in FH6, mark the corresponding Organizer card as Deleted
in FH6 (temporary). Organizer temporarily excludes the card and recalculates the
remaining #real-slot / #columnU-or-D positions. The recalculated positions are
then used by later Bridge moves.

Typical workflow:

  1. Find an item to review in Organizer.
  2. Select #603 / #302U (example) and run the Bridge move.
  3. Bridge moves the FH6 My Designs cursor to the target.
  4. Review the paint in FH6 and delete it yourself if desired.
  5. Mark the same item Deleted in FH6 (temporary) in Organizer.
  6. Organizer recalculates the remaining positions.
  7. Select the next item and repeat.

Bridge never deletes the paint. Final review, deletion, and confirmation happen
in FH6 and remain user actions.


■ Important: Bridge does not read the actual FH6 cursor position

Navigator Bridge does not use image recognition to inspect the FH6 screen and
does not read the game's internal paint position or cursor position.

It calculates a fixed input sequence from the Organizer target and sends that
sequence at configured intervals.

For FH6 window safety, Bridge accepts only a window whose title, after trimming
outer spaces, exactly matches:

  Forza Horizon 6

and whose owning process image is:

  forzahorizon6.exe

Examples that are rejected include browsers, GitHub pages, Organizer/Bridge
windows whose titles merely contain the game name, and a different process even
if its window title has been changed to exactly "Forza Horizon 6". If more than
one window passes both identity checks, Bridge stops instead of choosing one.

Before each normal movement key, Bridge verifies that the same target HWND is
still foreground, still has the exact title, and is still owned by the FH6
process. If any check fails, the next movement key is not sent.

Because Bridge does not read back the real cursor location, dropped key input,
unexpected screen state, system load, frame-rate changes, or window-switch delay
can cause the resulting cursor position to differ from the target. Increase the
key interval or waits if necessary and confirm the final position yourself.


■ Starting position #001U

Normal movement calculations use #001U as the starting point.

Reset to #001U OFF:
Before running a move, make sure the FH6 My Designs cursor is at #001U, such as
immediately after opening the screen.

Reset to #001U ON:
Before normal movement, Bridge sends one fixed Esc followed by one fixed Return
to reopen My Designs and make the starting point easier to align.

This reset is still a fixed input sequence. Bridge does not inspect the screen or
read the actual cursor position to confirm the result.


■ First-time Organizer integration

1. Start Navigator Bridge by itself.
2. Run Register Integration once.
3. Open a report generated by Livery Organizer.
4. Click a #real-slot or #columnU/D number to select the FH6 move target.
5. Press F or click Move to selected design in FH6.
6. Bridge foregrounds FH6 and sends the calculated cursor sequence.
7. Perform Load Design, review, deletion, or confirmation yourself in FH6.

Organizer/Bridge local integration uses:

  navigatorbridgeforfh6://

Your browser may ask for permission to open an external application. Review the
prompt before allowing it.

Bridge uses a single-instance design. If Bridge is already running, Organizer
passes the instruction to the existing instance instead of opening another
normal GUI window. When started by Organizer in Bridge mode, it normally runs
without showing the GUI.


■ Moving or renaming Bridge

The navigatorbridgeforfh6:// Windows registration stores Bridge's absolute path.

Register integration again if you:

- move Navigator-Bridge-for-FH6.exe or the Python script to another folder;
- rename the Bridge file;
- switch from EXE to Python or from Python to EXE.

You do not need to unregister before moving it. After the move/change, start the
new Bridge and run Register Integration again; the registration is overwritten
with the new absolute path.

If an EXE is replaced by a newer version at the same folder and filename, the
absolute path does not change and registration normally does not need to be
repeated.

The Bridge GUI displays the current execution type and registered integration
path so you can check whether re-registration is required.


■ Default navigation timing

Key interval                    50 ms
After switching to FH6         500 ms
Horizontal -> vertical         200 ms
Extra wait after left wrap     400 ms
Reset to #001U                 OFF
Wait after Esc                 500 ms
Wait after Return              800 ms

PC/FH6 performance can require longer waits than the defaults.

Shared settings:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json


■ Fixed safety boundary

Normal FH6 position movement can send only these three cursor keys:

- Left
- Right
- Down

Only when Reset to #001U is enabled, Bridge additionally sends this fixed
pre-movement sequence:

- Esc once
- Return once

Organizer and the external URI cannot specify arbitrary key codes, arbitrary key
names, or arbitrary key order. Up, character keys, function keys, and other keys
are not available as normal movement commands.

Bridge selects a movement target only when:

1. its title, after trimming outer spaces, exactly matches "Forza Horizon 6";
2. its owning process image is forzahorizon6.exe; and
3. exactly one window satisfies both identity checks.

Before every normal Left / Right / Down movement key, Bridge revalidates that the
same target HWND is still foreground and still passes the title + process checks.
If any check fails, the next movement key is not sent.

Bridge uses the standard Windows input API. It does not modify game memory,
executable code, game files, or GameSave.

It is not intended to automate game progression, economy, rewards, rankings,
competition, deletion confirmation, or similar gameplay systems. Final review,
Load Design, selection, deletion, and confirmation remain user actions.


■ Unregistering / removing Bridge

Before permanently removing Navigator Bridge, start it by itself and use
Unregister Integration to remove the navigatorbridgeforfh6:// Windows
registration.

Bridge IPC / log directory:
%LOCALAPPDATA%\Navigator-Bridge-for-FH6\

If you want to keep shared navigation settings, do not remove:
%APPDATA%\Livery-Organizer-for-FH6\navigator-bridge-settings.json


■ Unofficial tool

Navigator Bridge for FH6 is an unofficial, non-commercial fan-made operation
assistant. It is not affiliated with, endorsed by, sponsored by, or approved by
Microsoft, Xbox, Turn 10 Studios, Playground Games, or the Forza franchise.

Microsoft, Xbox, Forza, and related names, trademarks, and copyrighted material
belong to their respective owners. Users are responsible for reviewing applicable
rules, terms, and laws.

Reference: Xbox Game Content Usage Rules
https://www.xbox.com/en-US/developers/rules
