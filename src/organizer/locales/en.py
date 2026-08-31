"""English UI strings."""

STRINGS = {
    "app.subtitle": (
        "Analyzes Livery_* data and organizes it using Car IDs, internal vehicle names, "
        "and estimated vehicle names read from the Windows FH6 vehicle asset ZIPs."
    ),
    "path.save_root": "Save data",
    "path.game_root": "FH6 install",
    "path.output_root": "Output",
    "path.output_bundle": "Output Bundle",
    "settings.auto_saved": "Settings are saved automatically: {path}",
    "settings.save_warning": "Settings save warning: {error}",
    "option.embed_thumbnails": "Embed thumbnails in HTML (OFF: copy them to the thumbnails folder)",
    "option.export_analysis": "Export analysis data to the data folder (JSON / CSV / vehicle DB)",
    "preflight.title": "Pre-run Check",
    "preflight.checking": "Checking",
    "preflight.item_checking": "{label}: Checking",
    "safety.title": "Safety Design",
    "safety.body": (
        "• No functions write, delete, move, or rename files under GameSave.\n"
        "• Identical historical snapshots are deduplicated, while current re-download duplicates are shown as separate paints.\n"
        "• Keep / delete-candidate decisions are stored only in the HTML browser localStorage.\n"
        "• Car IDs are verified against the folder name and offset 0x10 after expanding C_livery.\n"
        "• Output locations inside the GameSave directory tree are rejected.\n"
        "• Settings are stored in the user profile and are never created under GameSave."
    ),
    "button.scan": "Check Paint Data",
    "button.open_output": "Open Output Folder",
    "button.recheck": "Recheck Settings",
    "button.quick_start": "Quick Start Guide",
    "button.support_info": "Environment / Support Info",
    "button.browse": "Browse…",
    "log.ready": "Ready. {app} v{version} / Fully exit FH6 before running this tool.",
    "log.settings_file": "Settings file: {path}",
    "dialog.output_required": "Select an output folder.",
    "dialog.save_root_required": "Select the save-data location first.",
    "dialog.create_output_failed": "Could not create the output folder.\n\n{error}",
    "cli.usage_prefix": "usage:",
    "cli.options_prefix": "options:",
    "cli.help_builtin": "show this help message and exit",
    "cli.description": "Livery Organizer for FH6 v{version} (read-only access to FH6 save data)",
    "cli.root_help": r"Save-data location to scan. Example: C:\XboxGames\GameSave\pgs",
    "cli.out_help": "Folder where reports are written",
    "cli.game_root_help": "FH6 installation folder used to inspect vehicle assets",
    "cli.print_game_roots_help": "Print auto-detected FH6 installation candidates and exit",
    "cli.no_embed_help": "Do not embed thumbnails in HTML; copy them to thumbnails/ instead",
    "cli.export_analysis_help": "Export paint data and the vehicle DB as JSON/CSV under data/",
    "cli.environment_check_help": "Print environment, settings, and pre-run check information without scanning",
    "cli.inspect_assets_help": "Read-only inspection of FH6 ZIPs, including empty and unreadable archives, then exit",
    "cli.cli_help": "Run in command-line mode without the GUI",
    "cli.print_roots_help": "Print auto-detected FH6 save-data candidates and exit",
}
