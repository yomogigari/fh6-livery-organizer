from __future__ import annotations

"""Resolve a user-managed decrypted FH6 GameDB without scanning arbitrary drives.

The resolver deliberately does not decrypt ``gamedbRC.slt`` and does not bundle a
GameDB snapshot.  It only validates and remembers an existing local SQLite file
that the user has already prepared.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import Mapping

GAMEDB_ENV_VAR = "LO4FH6_GAMEDB"
SETTINGS_FORMAT = "lo4fh6_preview_settings_v2"
SETTINGS_DATABASE_KEY = "database"
DEFAULT_DATABASE_DIR = Path("Documents") / "Livery-Organizer-for-FH6" / "game-data"
DEFAULT_DATABASE_NAME = "fh6-gamedb.sqlite"
REQUIRED_TABLES = {
    "data_car",
    "data_carbody",
    "list_upgradecarbody",
    "list_upgradetirecompound",
}


@dataclass(frozen=True)
class DatabaseResolution:
    path: Path
    source: str


def _local_appdata_root(environ: Mapping[str, str] | None = None, *, home: Path | None = None) -> Path:
    env = environ if environ is not None else os.environ
    raw = str(env.get("LOCALAPPDATA") or "").strip()
    if raw:
        return Path(raw) / "Livery Organizer for FH6" / "PreviewBridge"
    base = Path(home) if home is not None else Path.home()
    return base / "AppData" / "Local" / "Livery Organizer for FH6" / "PreviewBridge"


def settings_path(environ: Mapping[str, str] | None = None, *, home: Path | None = None) -> Path:
    return _local_appdata_root(environ, home=home) / "preview-settings.json"


def _suite_settings_module():
    """Organizer・Viewer・Navigator Bridge の共有設定（lo4fh6_desktop_suite.settings）。読み込めなければ None。"""
    try:
        from lo4fh6_desktop_suite import settings as suite_settings
    except ImportError:
        return None
    return suite_settings


def load_suite_gamedb(suite_settings_file: Path | None = None) -> str:
    """共有設定の GameDB のファイル（paths.gamedb_file）。無い・読めない場合は空。"""
    suite = _suite_settings_module()
    if suite is None:
        return ""
    try:
        data = suite.load_settings(path=suite_settings_file) if suite_settings_file else suite.load_settings()
    except Exception:  # noqa: BLE001  壊れた共有設定は読まない（共有設定の側で保全する）
        return ""
    return str((data.get("paths") or {}).get("gamedb_file") or "").strip()


def save_suite_gamedb(value: str, suite_settings_file: Path | None = None) -> bool:
    """共有設定へ GameDB のファイルを保存する（空なら消す）。書けなかった場合は False（Viewer 専用の設定には残る）。"""
    suite = _suite_settings_module()
    if suite is None:
        return False
    try:
        patch = {"paths": {"gamedb_file": str(value or "")}}
        if suite_settings_file:
            suite.update_settings(patch, path=suite_settings_file)
        else:
            suite.update_settings(patch)
        return True
    except Exception:  # noqa: BLE001
        return False


def _uses_suite(settings_file: Path | None, suite_settings_file: Path | None,
                environ: Mapping[str, str] | None = None, home: Path | None = None) -> bool:
    """共有設定を使うか。既定の Viewer 専用の設定を使うときだけ使う（一時の設定を渡すテストは本物の共有設定を読まない）。"""
    if suite_settings_file is not None:
        return True
    if settings_file is None:
        return True
    try:
        return Path(settings_file).resolve() == settings_path(environ, home=home).resolve()
    except OSError:
        return False


def load_shared_settings(path: Path | None = None) -> dict[str, object]:
    target = Path(path) if path is not None else settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def update_shared_settings(values: Mapping[str, object | None], path: Path | None = None) -> Path:
    target = Path(path) if path is not None else settings_path()
    payload = load_shared_settings(target)
    payload["format"] = SETTINGS_FORMAT
    for key, value in values.items():
        if value in (None, ""):
            payload.pop(str(key), None)
        else:
            payload[str(key)] = value
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def validate_fh6_database(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise ValueError(f"FH6 GameDB SQLite was not found: {candidate}")
    with candidate.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise ValueError("FH6 GameDB input is not a decrypted SQLite database.")
    uri = candidate.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to open FH6 GameDB SQLite: {exc}") from exc
    finally:
        try:
            connection.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
    tables = {str(row[0]).casefold() for row in rows if row and row[0]}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise ValueError("FH6 GameDB SQLite is missing required vehicle tables: " + ", ".join(missing))
    return candidate


def remember_database(path: str | Path, *, settings_file: Path | None = None,
                      suite_settings_file: Path | None = None) -> DatabaseResolution:
    """GameDB を覚える。3 つのツールの共有設定と、Viewer 専用の設定（古い版の Organizer も読む）の両方へ書く。"""
    database = validate_fh6_database(path)
    update_shared_settings({SETTINGS_DATABASE_KEY: str(database)}, settings_file)
    if _uses_suite(settings_file, suite_settings_file):
        save_suite_gamedb(str(database), suite_settings_file)
    return DatabaseResolution(database, "shared-setting")


def forget_database(*, settings_file: Path | None = None, suite_settings_file: Path | None = None) -> None:
    update_shared_settings({SETTINGS_DATABASE_KEY: None}, settings_file)
    if _uses_suite(settings_file, suite_settings_file):
        save_suite_gamedb("", suite_settings_file)


def _stable_candidates(*, home: Path | None = None) -> list[Path]:
    base = Path(home) if home is not None else Path.home()
    root = base / DEFAULT_DATABASE_DIR
    candidates = [root / DEFAULT_DATABASE_NAME]
    try:
        snapshots = sorted(
            root.glob("fh6-gamedb-*.sqlite"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        snapshots = []
    candidates.extend(snapshots)
    return candidates


def resolve_database_path(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    settings_file: Path | None = None,
    home: Path | None = None,
    stable_candidates: list[Path] | tuple[Path, ...] | None = None,
    suite_settings_file: Path | None = None,
) -> DatabaseResolution | None:
    """Resolve a prepared GameDB using an intentionally narrow priority order.

    Priority: explicit argument -> ``LO4FH6_GAMEDB`` -> desktop-suite shared setting
    (``paths.gamedb_file``) -> Viewer preview setting -> stable per-user game-data folder.  An explicit/environment path is treated
    as configuration and therefore fails closed when invalid.  A stale saved or
    conventional path is ignored so existing non-GameDB preview behavior remains
    available.
    """

    if explicit not in (None, ""):
        return DatabaseResolution(validate_fh6_database(explicit), "explicit")

    env = environ if environ is not None else os.environ
    environment_value = str(env.get(GAMEDB_ENV_VAR) or "").strip()
    if environment_value:
        return DatabaseResolution(validate_fh6_database(environment_value), "environment")

    # 3 つのツールの共有設定（paths.gamedb_file）。2026-11-18 から GameDB の指定の正本
    use_suite = _uses_suite(settings_file, suite_settings_file, env, home)
    if use_suite:
        suite_value = load_suite_gamedb(suite_settings_file)
        if suite_value:
            try:
                return DatabaseResolution(validate_fh6_database(suite_value), "suite-setting")
            except ValueError:
                pass

    target_settings = settings_file if settings_file is not None else settings_path(env, home=home)
    saved = str(load_shared_settings(target_settings).get(SETTINGS_DATABASE_KEY) or "").strip()
    if saved:
        try:
            resolution = DatabaseResolution(validate_fh6_database(saved), "shared-setting")
        except ValueError:
            pass
        else:
            # Viewer 専用の設定にしか無い場合は、共有設定へ一度だけ写す（Organizer・Navigator Bridge も使えるように）
            if use_suite and not load_suite_gamedb(suite_settings_file):
                save_suite_gamedb(str(resolution.path), suite_settings_file)
            return resolution

    candidates = list(stable_candidates) if stable_candidates is not None else _stable_candidates(home=home)
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = Path(candidate).expanduser()
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate.absolute()
        if key in seen:
            continue
        seen.add(key)
        try:
            return DatabaseResolution(validate_fh6_database(candidate), "stable-user-data")
        except ValueError:
            continue
    return None
