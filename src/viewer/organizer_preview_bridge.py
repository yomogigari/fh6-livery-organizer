# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=10,<13", "numpy>=1.26,<3", "psutil>=5.9,<8", "pywebview>=5.4,<7"]
# ///
from __future__ import annotations

import argparse
import contextlib
from collections import OrderedDict
import html
import itertools
import json
import math
import os
import queue
import re
import hashlib
import shutil
import subprocess
import sys
if __name__ == "__main__":
    # ソースから動かすとき、Organizer のリンクからは Windows が pythonw.exe でこのファイルを直接起動する
    # （--uri … --gui-child。Navigator Bridge と同じ登録の形）。作業の場所はブラウザー次第なので、依頼の相対パスを
    # 読む基準（このファイルのフォルダー）へ移す（以前の C# の起動用プログラムがしていたことと同じ。2026-11-20）。
    if sys.platform == "win32" and "--uri" in sys.argv[1:] and "--gui-child" in sys.argv[1:]:
        import os as _early_os
        _early_os.chdir(_early_os.path.dirname(_early_os.path.abspath(__file__)))
    # Organizer からの起動（--uri）は、重い部品（約 0.9 秒）を読み込む前に、開いている Viewer の窓へ依頼を渡せたら終わる。
    import viewer_window_reuse as _early_window_reuse
    if _early_window_reuse.forward_early(sys.argv[1:]):
        raise SystemExit(0)
from console_text_safety import configure_console_text_streams
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode

from organizer_preview_database import (
    forget_database,
    load_shared_settings,
    remember_database,
    resolve_database_path,
    update_shared_settings,
)
from organizer_preview_handoff import (
    URI_SCHEME,
    build_launch_uri,
    parse_launch_uri,
    request_from_manifest,
)
from fh6_vinyl_runtime import ensure_local_vinyl_geometry
from lo4fh6_desktop_suite.settings import viewer_appearance_options
from fh6_gpu_livery_runtime_policy import (
    default_capability_cache_path,
    evaluate_runtime_selection,
    load_capability_cache,
    write_capability_cache,
)
from fh6_gpu_livery_production import build_gpu_livery_production_runtime
from tools.livery.inspector_server import LiveryInspectorServer
from tools.livery.package import FullLiveryPackageError, validate_livery_inspection_artifact
from tools.livery.render_contract import RENDER_CONTRACT_FORMAT, RENDER_CONTRACT_REVISION
from tools.livery.fh6_swatch import extract_swatch_preview_from_zip
from tools.livery.material_runtime import external_user_color_contract, extract_material_texture_preview, inspect_game_material_runtime, material_defined_paint_color, release_safe_viewer_candidate, texture_binding_evidence, weave_semantic_evidence

ROOT = Path(__file__).resolve().parent
PREVIEW_SCRIPT = ROOT / "vehicle_preview.py"
VIEWER_ROOT = ROOT / "tools" / "livery-inspector"
REQUEST_FORMAT_V1 = "lo4fh6_organizer_preview_request_v1"
REQUEST_FORMAT_V2 = "lo4fh6_organizer_preview_request_v2"
SUPPORTED_REQUEST_FORMATS = {"", REQUEST_FORMAT_V1, REQUEST_FORMAT_V2}
REQUEST_FORMAT = REQUEST_FORMAT_V1

QUALITY_PRESETS = {
    "minimum": "1",
    "standard": "2",
    "high": "3",
    "ultra": "4",
}
RENDER_QUALITY_TO_PRESET = {
    "minimum": "minimum",
    "standard": "standard",
    "high": "high",
    "reference": "ultra",
}
PRESET_TO_RENDER_QUALITY = {value: key for key, value in RENDER_QUALITY_TO_PRESET.items()}
DEFAULT_QUALITY_PRESET = "standard"

GPU_LIVERY_PRODUCTION_ADAPTER_AVAILABLE = True

# 2（2026-11-20）：Python 標準の venv で作り、pythonw.exe が窓用（GUI）であることを確かめる。uv venv が作った環境の
# pythonw.exe はコンソール用の中継プログラムで、起動のたびに黒い窓が一瞬出ていた（版を上げて作り直させる）。
URI_RUNTIME_SCHEMA = 2
_GUI_STDIO_HANDLES: list[Any] = []
URI_RUNTIME_DEPENDENCIES = (
    "Pillow>=10,<13",
    "numpy>=1.26,<3",
    "psutil>=5.9,<8",
    "pywebview>=5.4,<7",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research bridge that opens the game-facing 3D preview from an Organizer-style request. "
            "It can reuse an already prepared preview output directory or build one on demand."
        )
    )
    parser.add_argument("--request-json", type=Path, default=None, help="Organizer-style preview request JSON")
    parser.add_argument("--manifest-json", type=Path, default=None, help="Organizer preview manifest JSON")
    parser.add_argument("--record-id", default="", help="record ID in --manifest-json")
    parser.add_argument("--uri", default="", help=f"{URI_SCHEME}:// URI supplied by generated HTML")
    parser.add_argument("--register-uri-scheme", action="store_true", help="register the research preview URI scheme for the current user")
    parser.add_argument("--unregister-uri-scheme", action="store_true", help="remove the research preview URI scheme for the current user")
    parser.add_argument("--source", type=Path, default=None, help="Livery_* folder or C_livery file")
    parser.add_argument("--game-folder", type=Path, default=None, help=r"FH6 install or Content folder")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="optional decrypted local FH6 GameDB SQLite for exact wheel/tire assembly dimensions",
    )
    parser.add_argument(
        "--remember-database",
        type=Path,
        default=None,
        help=(
            "validate and save a user-prepared decrypted FH6 GameDB SQLite path for future Organizer/Viewer launches; "
            "does not decrypt or copy the database"
        ),
    )
    parser.add_argument(
        "--forget-database",
        action="store_true",
        help="remove the saved GameDB path; the database file itself is never deleted",
    )
    parser.add_argument(
        "--show-database",
        action="store_true",
        help="show the currently resolved GameDB path and resolution source, if any",
    )
    parser.add_argument(
        "--gamedb-car-body-id",
        type=int,
        default=None,
        help=(
            "research-only explicit GameDB CarBodyID for exact wheel/tire assembly selection; "
            "independent of --body-kit-part-id"
        ),
    )
    parser.add_argument(
        "--wheel-placement",
        choices=("gamedb", "carbin"),
        default=None,
        help=(
            "research-only wheel placement after independent WheelStyle morph: "
            "gamedb (default) or carbin for original-placement A/B comparison"
        ),
    )
    parser.add_argument(
        "--wheel-morph-reference-helper",
        type=Path,
        default=None,
        help=(
            "research-only pinned external WheelStyle morph visual oracle; hash-verified and never bundled. "
            "Requires --database"
        ),
    )
    parser.add_argument("--pr76-tire-model", default="",
        help="PR76 direct CLI research only: replace the source TireModelName for signed original Wheel+Tire capture; normal Viewer untouched")
    parser.add_argument("--car-id", type=int, default=None, help="resolved Car ID from Livery Organizer for FH6")
    parser.add_argument("--title", default="", help="optional display title")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("organizer-preview-output"),
        help="root directory for per-livery cached outputs",
    )
    parser.add_argument(
        "--vinyl-cache-root",
        type=Path,
        default=None,
        help=(
            "optional shared cache directory for local FH6 vinyl geometry; "
            "default is <output-root>/_fh6-vinyl-geometry"
        ),
    )
    parser.add_argument("--output-key", default="", help="optional stable key from Organizer record ID / slot")
    parser.add_argument(
        "--quality",
        choices=("auto", "1", "2", "3", "4"),
        default=None,
        help="preview quality passed to vehicle_preview.py; default 4 unless request JSON supplies one",
    )
    parser.add_argument(
        "--quality-preset",
        choices=tuple(QUALITY_PRESETS),
        default=None,
        help="end-to-end quality preset: minimum=1x, standard=2x, high=3x, ultra=4x",
    )
    parser.add_argument(
        "--wheel-source",
        choices=("proxy", "stock", "game-fit", "source-verified"),
        default=None,
        help=("presentation-only wheel source; proxy is the legacy plain-CLI default when omitted; "
              "stock shows raw local wheel/tire meshes; game-fit uses WheelStyle with a neutral tire fallback; source-verified requires all four signed source WheelStyle and original Tire meshes, and refuses incomplete inputs"),
    )
    parser.add_argument(
        "--shader-validation", choices=("strict", "deferred-experimental", "overlap-experimental"), default=None,
        help="research-only: defer initial 3D shader diagnostics on devices supporting KHR_parallel_shader_compile; default strict",
    )
    parser.add_argument(
        "--atlas-capacity-probe", action="store_true", default=None,
        help="research-only: measure lossless PNG bytes for the final GPU paint atlas after first paint; no PNG file is saved",
    )
    parser.add_argument(
        "--body-kit-part-id",
        type=int,
        default=None,
        help=(
            "research-only explicit CarBody PartId. Matching exterior Manifest.xml families with the same PartId "
            "are used for chassis conversion; this does not resolve the player's save state"
        ),
    )
    parser.add_argument(
        "--private-context-mask-visual-check", action="store_true",
        help="開発者専用: 0x40/0x50 Group Mask研究候補を実3D GPUで確認（未承認・通常入口不変）",
    )
    parser.add_argument("--rebuild", action="store_true", help="ignore reusable cached output and prepare again")
    parser.add_argument("--prepare-only", action="store_true", help="prepare cache output only; do not start the local viewer")
    parser.add_argument("--no-open", action="store_true", help="prepare/start the local server without opening a viewer window")
    parser.add_argument(
        "--window-mode",
        choices=("standalone", "browser"),
        default="standalone",
        help="viewer host; standalone uses a WebView2-backed app window, browser preserves the older browser-tab path",
    )
    parser.add_argument(
        "--gui-child",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _string(value: Any) -> str:
    # 構造化要求v2ではsourceなどのトップレベルキーが辞書になる。
    # 辞書を文字列化すると波括弧を含む架空パスになるため、必ず構造のまま扱う。
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value or "").strip()


ORGANIZER_OPTIONAL_KEYS = (
    "record_id",
    "slot_label",
    "list_name",
    "creator_name",
    "vehicle_name",
    "share_code",
    "upload_date",
)


def _nested_string(data: dict[str, Any], *path: str) -> str:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return ""
        current = current.get(key)
    return _string(current)


def _nested_value(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current.get(key)
    return current


def sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", _string(value))
    cleaned = cleaned.strip("-._")
    return cleaned[:80] or "item"


def resolve_game_content_root(value: str | Path) -> Path:
    """
    FH6のインストールルート、またはそのContentディレクトリを解決する。
    """
    root = Path(value).expanduser()
    direct_vinyls = root / "media" / "livery" / "Vinyls.zip"
    if direct_vinyls.is_file():
        return root.resolve()
    content = root / "Content"
    content_vinyls = content / "media" / "livery" / "Vinyls.zip"
    if content_vinyls.is_file():
        return content.resolve()
    # 両形式とも存在しない場合は元のパス表記を維持する。
    # 診断に必要であり、Windows絶対パスの字面を壊さない。
    return root


def normalize_request_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    要求v1／v2の入力をBridge内部の共通要求Mapへ正規化する。
    """
    if not isinstance(data, dict):
        raise ValueError("The Organizer request JSON must contain an object.")
    request_format = _string(data.get("format"))
    if request_format not in SUPPORTED_REQUEST_FORMATS:
        raise ValueError(f"Unsupported request format: {data.get('format')}")
    request = {
        "format": REQUEST_FORMAT_V2 if request_format == REQUEST_FORMAT_V2 else REQUEST_FORMAT_V1,
        "source": _string(data.get("source")) or _nested_string(data, "source", "path"),
        "game_folder": _string(data.get("game_folder")) or _nested_string(data, "environment", "game_folder"),
        "database": _string(data.get("database")) or _nested_string(data, "environment", "database"),
        "car_id": data.get("car_id") if data.get("car_id") is not None else _nested_value(data, "vehicle", "car_id"),
        "title": _string(data.get("title")) or _nested_string(data, "display", "title"),
        "output_key": _string(data.get("output_key")) or _nested_string(data, "organizer", "output_key"),
        "quality": _string(data.get("quality")) or _nested_string(data, "viewer", "quality") or "4",
        "body_kit_part_id": data.get("body_kit_part_id") if data.get("body_kit_part_id") is not None else _nested_value(data, "viewer", "body_kit_part_id"),
        "gamedb_car_body_id": data.get("gamedb_car_body_id") if data.get("gamedb_car_body_id") is not None else _nested_value(data, "viewer", "gamedb_car_body_id"),
        "wheel_placement": _string(data.get("wheel_placement")) or _nested_string(data, "viewer", "wheel_placement"),
        "wheel_source": _string(data.get("wheel_source")) or _nested_string(data, "viewer", "wheel_source"),
        "shader_validation": _string(data.get("shader_validation")) or _nested_string(data, "viewer", "shader_validation"),
        "atlas_capacity_probe": data.get("atlas_capacity_probe", _nested_value(data, "viewer", "atlas_capacity_probe")),
        "record_id": _string(data.get("record_id")) or _nested_string(data, "organizer", "record_id"),
        "slot_label": _string(data.get("slot_label")) or _nested_string(data, "organizer", "slot_label"),
        "list_name": _string(data.get("list_name")) or _nested_string(data, "organizer", "list_name"),
        "creator_name": _string(data.get("creator_name")) or _nested_string(data, "display", "creator_name"),
        "vehicle_name": _string(data.get("vehicle_name")) or _nested_string(data, "display", "vehicle_name"),
        "share_code": _string(data.get("share_code")) or _nested_string(data, "display", "share_code"),
        "upload_date": _string(data.get("upload_date")) or _nested_string(data, "display", "upload_date"),
    }
    if request["car_id"] is not None:
        request["car_id"] = int(request["car_id"])
    if request.get("body_kit_part_id") not in (None, ""):
        request["body_kit_part_id"] = int(request["body_kit_part_id"])
    if request.get("gamedb_car_body_id") not in (None, ""):
        request["gamedb_car_body_id"] = int(request["gamedb_car_body_id"])
    return request


def load_request(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return normalize_request_payload(data)


def request_json_from_manifest(manifest_path: Path, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not record_id:
        raise ValueError("--record-id is required with --manifest-json.")
    return request_from_manifest(manifest_path, record_id)


def request_json_from_uri(uri: str) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    manifest_path, record_id = parse_launch_uri(uri)
    request, manifest = request_from_manifest(manifest_path, record_id)
    return request, manifest, manifest_path, record_id


def _local_appdata_root() -> Path:
    value = os.environ.get("LOCALAPPDATA", "").strip()
    if value:
        return Path(value) / "Livery Organizer for FH6" / "PreviewBridge"
    return Path.home() / "AppData" / "Local" / "Livery Organizer for FH6" / "PreviewBridge"


# Viewer の窓（WebView2）の保存先。以前は開くたびに新しい保存先（private_mode）で、シェーダーと JavaScript の
# 作成済みの結果が残らず、窓を開いてから最初の 1 枚まで毎回 14〜16 秒かかっていた（2026-11-19 の計測）。
# Viewer 専用の保存先を使い回して作成済みの結果を残す（2026-11-19）。
# ペイントの中身はローカルのサーバーが Cache-Control: no-store で返すので残らない。Cookie も使っていない。
# 閲覧の履歴（Viewer の URL）は起動のたびに消す（別の Viewer が使用中で消せないときはそのまま）。
WEBVIEW_PROFILE_DIR = "webview-profile"
_WEBVIEW_HISTORY_FILES = (
    "History", "History-journal", "Visited Links", "Top Sites", "Top Sites-journal",
    "Shortcuts", "Shortcuts-journal", "Network Action Predictor", "Network Action Predictor-journal",
)


def _webview_profile_root() -> Path:
    return _local_appdata_root() / WEBVIEW_PROFILE_DIR


def _clear_webview_history(profile: Path) -> None:
    """保存先の閲覧の履歴のファイルを消す（WebView2 は保存先の EBWebView\\Default に置く）。"""
    for folder in (profile / "EBWebView" / "Default", profile / "Default"):
        for name in _WEBVIEW_HISTORY_FILES:
            try:
                (folder / name).unlink()
            except OSError:
                pass


def _webview_start_options() -> dict[str, Any]:
    """webview.start に渡す保存先の指定。保存先を作れないときは従来どおり毎回新しい保存先にする。"""
    profile = _webview_profile_root()
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"private_mode": True}
    _clear_webview_history(profile)
    return {"private_mode": False, "storage_path": str(profile)}


def _legacy_hidden_uri_launcher_path() -> Path:
    return _local_appdata_root() / "preview-uri-launcher.vbs"


def _bridge_log_path() -> Path:
    return _local_appdata_root() / "preview-bridge.log"


def _settings_path() -> Path:
    return _local_appdata_root() / "preview-settings.json"


# 自動回転の速さ（もとの速さ 0.65 に対する倍率）。標準は 2 倍、選べるのは 1〜3 倍（2026-11-22）。
AUTO_ROTATE_SPEED_KEY = "viewer_auto_rotate_speed"
AUTO_ROTATE_SPEED_DEFAULT = 2.0
AUTO_ROTATE_SPEED_CHOICES = (1.0, 1.5, 2.0, 2.5, 3.0)


def _auto_rotate_speed(settings: dict[str, Any] | None) -> float:
    """Viewer の設定に保存した自動回転の速さの倍率。無い・選べない値なら標準（2 倍）。"""
    value = (settings or {}).get(AUTO_ROTATE_SPEED_KEY)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) in AUTO_ROTATE_SPEED_CHOICES:
        return float(value)
    return AUTO_ROTATE_SPEED_DEFAULT


def _viewer_preferences() -> dict[str, Any]:
    """ページへ渡す画面の好み（/api/manifest の viewer_preferences）。"""
    return {"auto_rotate_speed": _auto_rotate_speed(load_shared_settings(_settings_path()))}


def _uri_runtime_root() -> Path:
    return _local_appdata_root() / "runtime"


def _uri_runtime_python_path() -> Path:
    return _uri_runtime_root() / "Scripts" / "python.exe"


def _uri_runtime_pythonw_path() -> Path:
    return _uri_runtime_root() / "Scripts" / "pythonw.exe"


def _uri_runtime_stamp_path() -> Path:
    return _uri_runtime_root() / "lo4fh6-preview-runtime.json"


def _old_native_launcher_files() -> list[Path]:
    """以前の版が C# で作った起動用プログラム（2026-11-20 にやめた）。登録・解除のときに消す。"""
    root = _local_appdata_root() / "bin"
    return [root / "LiveryOrganizerPreviewLauncher.exe", root / "LiveryOrganizerPreviewLauncher.json"]


def _remove_old_native_launcher() -> None:
    for old in _old_native_launcher_files():
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        (_local_appdata_root() / "bin").rmdir()  # 空のときだけ消える
    except OSError:
        pass


def _runtime_stamp_payload() -> dict[str, Any]:
    return {
        "schema": URI_RUNTIME_SCHEMA,
        "dependencies": list(URI_RUNTIME_DEPENDENCIES),
    }


_PE_SUBSYSTEM_WINDOWS_GUI = 2


def _windows_subsystem(path: Path) -> int | None:
    """Windows の実行ファイルの種類（PE の Subsystem：2 が窓用、3 がコンソール用）。読めなければ None。"""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(4096)
        if head[:2] != b"MZ":
            return None
        pe = int.from_bytes(head[0x3C:0x40], "little")
        if head[pe:pe + 4] != b"PE\0\0" or pe + 24 + 70 > len(head):
            return None
        return int.from_bytes(head[pe + 24 + 68:pe + 24 + 70], "little")
    except OSError:
        return None


def _runtime_stamp_matches() -> bool:
    python = _uri_runtime_python_path()
    pythonw = _uri_runtime_pythonw_path()
    stamp = _uri_runtime_stamp_path()
    if not python.is_file() or not pythonw.is_file() or not stamp.is_file():
        return False
    if _windows_subsystem(pythonw) != _PE_SUBSYSTEM_WINDOWS_GUI:
        return False  # 黒い窓を出す pythonw.exe の環境は作り直す
    try:
        data = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return data == _runtime_stamp_payload()


def _ensure_uri_runtime() -> Path:
    """
    研究用URI Handlerに必要な、Consoleを出さない安定したPython Runtimeを用意する。
    """
    if sys.platform != "win32":
        raise ValueError("URI runtime setup is supported only on Windows.")
    if _runtime_stamp_matches():
        return _uri_runtime_pythonw_path()

    uv_path = shutil.which("uv")
    if not uv_path:
        raise ValueError("uv was not found in PATH; URI registration requires uv for runtime setup.")

    runtime_root = _uri_runtime_root()
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    base_python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    # 登録の操作から動かす venv・uv も、黒い窓を出さずに動かす。
    quiet = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    # Python 標準の venv で作る（Scripts\pythonw.exe が窓用の中継プログラム venvwlauncher になる）。
    subprocess.run([str(base_python), "-m", "venv", "--clear", str(runtime_root)], check=True, **quiet)
    runtime_python = _uri_runtime_python_path()
    runtime_pythonw = _uri_runtime_pythonw_path()
    if not runtime_python.is_file() or not runtime_pythonw.is_file():
        raise ValueError(f"URI runtime did not create python/pythonw under: {runtime_root}")
    if _windows_subsystem(runtime_pythonw) != _PE_SUBSYSTEM_WINDOWS_GUI:
        raise ValueError(
            "Viewer 専用の Python の環境の pythonw.exe が窓用ではありません（起動のたびに黒い窓が出ます）: "
            + str(runtime_pythonw))
    subprocess.run(
        [
            str(Path(uv_path).resolve()),
            "pip",
            "install",
            "--python",
            str(runtime_python),
            *URI_RUNTIME_DEPENDENCIES,
        ],
        check=True,
        **quiet,
    )
    subprocess.run(
        [str(runtime_python), "-c", "import PIL, numpy, psutil, webview"],
        check=True,
        **quiet,
    )
    _uri_runtime_stamp_path().write_text(
        json.dumps(_runtime_stamp_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        _legacy_hidden_uri_launcher_path().unlink(missing_ok=True)
    except OSError:
        pass
    return runtime_pythonw


def _load_quality_preset() -> str:
    data = load_shared_settings(_settings_path())
    preset = _string(data.get("quality_preset"))
    return preset if preset in QUALITY_PRESETS else DEFAULT_QUALITY_PRESET


def _save_quality_preset(preset: str) -> None:
    if preset not in QUALITY_PRESETS:
        raise ValueError(f"Unsupported quality preset: {preset}")
    update_shared_settings({"quality_preset": preset}, _settings_path())


def _render_quality_for_request(request: dict[str, Any]) -> str:
    quality = _string(request.get("quality"))
    preset = next((name for name, scale in QUALITY_PRESETS.items() if scale == quality), DEFAULT_QUALITY_PRESET)
    return PRESET_TO_RENDER_QUALITY[preset]


def _append_bridge_log(message: str) -> None:
    try:
        path = _bridge_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message.rstrip()}\n")
    except OSError:
        pass


def _console_python_executable(executable: Path | None = None) -> Path:
    """
    明示的なTerminal／手動実行ではConsole付きInterpreterを返す。
    """
    executable = (executable or Path(sys.executable)).resolve()
    if sys.platform == "win32" and executable.name.casefold() == "pythonw.exe":
        python = executable.with_name("python.exe")
        if python.is_file():
            return python
    return executable


def _detach_gui_console() -> None:
    """
    登録済みGUI起動へ誤って付随したConsoleを切り離す。
    """
    if sys.platform != "win32":
        return
    # Console切離し後もprintとError出力を安全に扱う。
    # 登録済みGUI起動はログへ出力する。
    for stream_name in ("stdout", "stderr"):
        try:
            handle = open(os.devnull, "w", encoding="utf-8", errors="replace")
            _GUI_STDIO_HANDLES.append(handle)
            setattr(sys, stream_name, handle)
        except OSError:
            pass
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            kernel32.FreeConsole()
    except Exception:
        pass


def _gui_python_executable() -> Path:
    """
    可能な限り現在の実行環境からConsoleなしInterpreterを取得する。
    """
    executable = Path(sys.executable).resolve()
    if sys.platform == "win32":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.is_file():
            return pythonw
    return executable


def _is_packaged() -> bool:
    """EXE（Livery-Viewer-for-FH6.exe）で動いているか（lo4fh6_desktop_suite.runtime）。"""
    from lo4fh6_desktop_suite.runtime import is_packaged
    return is_packaged()


def _spawn_uri_gui_child(args: argparse.Namespace) -> bool:
    """
    手動の``uv run --uri``起動をpythonwへ分離しConsole表示を避ける。
    """
    if sys.platform != "win32":
        return False
    if getattr(args, "gui_child", False):
        return False
    if not _string(getattr(args, "uri", "")):
        return False
    if getattr(args, "window_mode", "standalone") != "standalone":
        return False
    if getattr(args, "prepare_only", False) or getattr(args, "no_open", False):
        return False

    if _is_packaged():
        # EXE はコンソールを持たないので、EXE 自身を連携の役割で起動し直す
        from lo4fh6_desktop_suite.runtime import packaged_executable, self_command
        python = packaged_executable()
        command = self_command("bridge", *sys.argv[1:], "--gui-child")
    else:
        python = _gui_python_executable()
        command = [
            str(python),
            str(Path(__file__).resolve()),
            *sys.argv[1:],
            "--gui-child",
        ]
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    # SW_SHOWNORMAL（＝1）。subprocess には SW_HIDE しか無く、subprocess.SW_SHOWNORMAL は AttributeError で
    # 窓用の起動し直し（EXE の URI の起動・手動の --uri）が止まっていた（2026-11-19 に確認して直した）。
    startupinfo.wShowWindow = 1
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    if python.name.casefold() != "pythonw.exe":
        creationflags |= subprocess.CREATE_NO_WINDOW

    _append_bridge_log(
        f"detaching manual standalone GUI child: interpreter={python} record-uri={bool(args.uri)}"
    )
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
    return True


def _uri_open_command(runtime_pythonw: Path | None = None) -> str:
    """Windows に登録する起動の命令。

    EXE は自分自身を直接登録する。ソースから動かすときは、Navigator Bridge と同じく、窓を出さない Python
    （Viewer 専用の環境の pythonw.exe）でこのファイルを直接起動する（2026-11-20 に C# の起動用プログラムをやめた）。
    """
    if _is_packaged():
        from lo4fh6_desktop_suite.runtime import packaged_executable
        return f'"{packaged_executable()}" --uri "%1"'
    pythonw = runtime_pythonw or _uri_runtime_pythonw_path()
    return f'"{pythonw}" "{Path(__file__).resolve()}" --uri "%1" --gui-child'


def register_uri_scheme() -> None:
    if sys.platform != "win32":
        raise ValueError("URI registration is supported only on Windows.")
    import winreg

    runtime_pythonw = None if _is_packaged() else _ensure_uri_runtime()
    command = _uri_open_command(runtime_pythonw)
    root_path = rf"Software\Classes\{URI_SCHEME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Livery Organizer for FH6 3D Preview")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        # 以前の C# の起動用プログラムが読んでいた値。今は起動の命令に直接書くので消す（残っていると登録先を取り違える）。
        for stale in ("PreviewPythonwPath", "PreviewBridgeScriptPath"):
            try:
                winreg.DeleteValue(key, stale)
            except FileNotFoundError:
                pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_path + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    _remove_old_native_launcher()
    print(f"registered: {URI_SCHEME}://")
    print(f"command:    {command}")
    if runtime_pythonw is not None:
        print(f"runtime:    {_uri_runtime_root()}")


def unregister_uri_scheme() -> None:
    if sys.platform != "win32":
        raise ValueError("URI registration is supported only on Windows.")
    import winreg

    root_path = rf"Software\Classes\{URI_SCHEME}"
    for suffix in (
        r"\shell\open\command",
        r"\shell\open",
        r"\shell",
        "",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root_path + suffix)
        except FileNotFoundError:
            pass
    try:
        _legacy_hidden_uri_launcher_path().unlink(missing_ok=True)
    except OSError:
        pass
    _remove_old_native_launcher()
    print(f"unregistered: {URI_SCHEME}://")


def request_from_args(args: argparse.Namespace) -> dict[str, Any]:
    manifest_context: dict[str, Any] | None = None
    uri_value = getattr(args, "uri", "")
    manifest_json = getattr(args, "manifest_json", None)
    record_id = getattr(args, "record_id", "")
    if uri_value:
        request_json, manifest_context, _manifest_path, _record_id = request_json_from_uri(uri_value)
        request = request_json
    elif manifest_json:
        request, manifest_context = request_json_from_manifest(manifest_json, record_id)
    else:
        request = load_request(args.request_json) if args.request_json else {"format": REQUEST_FORMAT_V1}
    # 研究用Maskは直接CLI専用。URI/Manifest/JSONからの研究ON注入は拒否。
    private_context_mask_check = getattr(args, "private_context_mask_visual_check", False) is True
    if private_context_mask_check and (
        uri_value or manifest_json or getattr(args, "request_json", None)
    ):
        raise ValueError("Mask研究3D確認は直接CLI --source/--car-id/--game-folder のみ許可します")
    if getattr(args, "pr76_tire_model", "") and (
        uri_value or manifest_json or getattr(args, "request_json", None)
    ):
        raise ValueError("PR76タイヤ種類の変更は直接CLI限定です（Organizer/URI/JSONから適用不可）")
    # 全入口は同じv1／v2要求正規化を通る。
    # r113では要求ファイルだけ正規化し、Manifest／URI入口が抜けていた。
    request = normalize_request_payload(request)
    # 保存済みの旧CPU設定を無言でGPU設定に変換せず、入口で明示的に拒否する。
    legacy_cpu_paint_policy = _string(request.get("gpu_shadow_policy")).casefold()
    if legacy_cpu_paint_policy and legacy_cpu_paint_policy != "gpu-only":
        raise ValueError(
            "旧CPUペイント設定は廃止されました。WebGL2 GPU専用の設定で再実行してください。"
        )
    # 正常版11/07 Stage3 Wheel+FEOWをOrganizerの通常 URI/manifest/request へ接続。
    # Organizer旧manifestに明示された stock も旧既定値であり受入の無効化ではない。
    # 詳細診断用の --wheel-source は直接CLI要求にのみ残す。
    if uri_value or manifest_json or getattr(args, "request_json", None):
        request["wheel_source"] = "source-verified"
    elif not _string(request.get("wheel_source")):
        request["wheel_source"] = "source-verified"
    for key, value in {
        "source": args.source,
        "game_folder": args.game_folder,
        "database": getattr(args, "database", None),
        "gamedb_car_body_id": getattr(args, "gamedb_car_body_id", None),
        "pr76_tire_model": getattr(args, "pr76_tire_model", None),
        "wheel_placement": getattr(args, "wheel_placement", None),
        "wheel_morph_reference_helper": getattr(args, "wheel_morph_reference_helper", None),
        "car_id": args.car_id,
        "title": args.title,
        "output_key": args.output_key,
        "quality": args.quality,
        "wheel_source": getattr(args, "wheel_source", None),
        "shader_validation": getattr(args, "shader_validation", None),
        "atlas_capacity_probe": getattr(args, "atlas_capacity_probe", None),
        "body_kit_part_id": getattr(args, "body_kit_part_id", None),
    }.items():
        if value not in (None, ""):
            request[key] = str(value) if isinstance(value, Path) else value
    # CLI指定を含め、通常のOrganizer入口では未承認旧車輪への後退を認めない。
    if uri_value or manifest_json or getattr(args, "request_json", None):
        request["wheel_source"] = "source-verified"
    quality_preset = getattr(args, "quality_preset", None)
    if quality_preset:
        request["quality"] = QUALITY_PRESETS[str(quality_preset)]
    source = Path(_string(request.get("source"))) if _string(request.get("source")) else None
    if source is not None:
        source_current = _prefer_current_gamesave_path(source)
        if source_current != source:
            # 番号付きゲーム保存先は更新で移動する。確認済みcurrentを
            # Organizer GUI/CLI共通の正規要求へ保存し、次回以降も参照可能に。
            source = source_current
            request["source"] = str(source_current)
    game_folder = resolve_game_content_root(_string(request.get("game_folder"))) if _string(request.get("game_folder")) else None
    database_resolution = resolve_database_path(
        _string(request.get("database")) or None,
        settings_file=_settings_path(),
    )
    database = database_resolution.path if database_resolution is not None else None
    car_id = request.get("car_id")
    if source is None:
        raise ValueError("source is required (either --source or request JSON).")
    if game_folder is None:
        raise ValueError("game_folder is required (either --game-folder or request JSON).")
    if car_id is None:
        raise ValueError("car_id is required (either --car-id or request JSON).")
    pr76_tire_model = _string(request.get("pr76_tire_model"))
    if pr76_tire_model:
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", pr76_tire_model)
                or database is None or _string(request.get("wheel_source")) != "source-verified"):
            raise ValueError("PR76原本TireModelNameは直接CLI/実GameDB/原本Wheelが必要です")
    quality = _string(request.get("quality")) or "4"
    if quality not in {"auto", "1", "2", "3", "4"}:
        raise ValueError(f"Unsupported quality: {quality}")
    wheel_placement = (_string(request.get("wheel_placement")) or "gamedb").casefold()
    if wheel_placement not in {"gamedb", "carbin"}:
        raise ValueError(f"Unsupported wheel placement: {wheel_placement}")
    wheel_source = _string(request.get("wheel_source"))
    gamedb_missing = database is None
    if gamedb_missing and wheel_source.casefold() == "source-verified":
        # 原本 4 輪＋タイヤは、車輪の位置・寸法とタイヤを GameDB から求めるので、GameDB が無いと作れない。
        # 止めずに簡易の車輪で表示し、画面にその旨を出す（2026-11-21。GameDB を持たない利用者も
        # ペイントを見られるようにする）。
        wheel_source = "proxy"
    normalized = {
        "format": request.get("format") or REQUEST_FORMAT_V1,
        "source": source,
        "game_folder": game_folder,
        "database": database,
        "database_resolution_source": database_resolution.source if database_resolution is not None else "",
        "wheel_morph_reference_helper": (
            Path(_string(request.get("wheel_morph_reference_helper"))).resolve()
            if _string(request.get("wheel_morph_reference_helper")) else None
        ),
        "car_id": int(car_id),
        "title": _string(request.get("title")),
        "output_key": _string(request.get("output_key")),
        "quality": quality,
        "wheel_source": wheel_source,
        "gamedb_missing": gamedb_missing,
        "pr76_tire_model": pr76_tire_model,
        # CLI上書きと要求正規化の後も研究用Shader方針を保つ。
        # r400ではこの境界で値が失われ、指定済みでもViewer URLが厳密既定へ戻っていた。
        "atlas_capacity_probe": _string(request.get("atlas_capacity_probe")).casefold() in {"1", "true", "yes"},
        "private_context_mask_visual_check": private_context_mask_check,
        "shader_validation": (
            _string(request.get("shader_validation"))
            if _string(request.get("shader_validation")) in {"deferred-experimental", "overlap-experimental"}
            else "strict"
        ),
        "gpu_shadow_policy": (
            _string(request.get("gpu_shadow_policy"))
            if _string(request.get("gpu_shadow_policy")) in {"gpu-only"}
            else "gpu-only"
        ),
        "body_kit_part_id": (
            int(request["body_kit_part_id"])
            if request.get("body_kit_part_id") not in (None, "")
            else None
        ),
        "gamedb_car_body_id": (
            int(request["gamedb_car_body_id"])
            if request.get("gamedb_car_body_id") not in (None, "")
            else None
        ),
        "wheel_placement": wheel_placement,
        "record_id": _string(request.get("record_id")),
        "slot_label": _string(request.get("slot_label")),
        "list_name": _string(request.get("list_name")),
        "creator_name": _string(request.get("creator_name")),
        "vehicle_name": _string(request.get("vehicle_name")),
        "share_code": _string(request.get("share_code")),
        "upload_date": _string(request.get("upload_date")),
    }
    if manifest_context:
        preview = manifest_context.get("preview") if isinstance(manifest_context.get("preview"), dict) else {}
        normalized["manifest_output_root"] = _string(preview.get("output_root"))
    return normalized


def _effective_viewer_wheel_source(request: dict[str, Any]) -> str:
    """
    Viewerが実際に使用するWheel表示モードを返す。
    """

    return _viewer_wheel_source(request)


def _wheel_source_comparison_note(request: dict[str, Any]) -> str:
    effective = _effective_viewer_wheel_source(request)
    if effective == "proxy" and not _string(request.get("wheel_source")):
        return (
            "wheel source: proxy (legacy plain-CLI default; use --wheel-source stock "
            "when comparing recovered local FH6 wheel geometry)"
        )
    return f"wheel source: {effective}"


def _viewer_wheel_source(request: dict[str, Any]) -> str:
    """
    Viewer URLへ渡す検証済みWheel原本Query値を返す。
    """

    value = _string(request.get("wheel_source")).casefold() or "source-verified"
    if value not in {"proxy", "stock", "game-fit", "source-verified"}:
        raise ValueError("未対応の車輪描画方式: " + value)
    return value


def request_to_serializable(request: dict[str, Any]) -> dict[str, Any]:
    data = {
        "format": request.get("format") or REQUEST_FORMAT_V1,
        "source": str(request["source"]),
        "game_folder": str(request["game_folder"]),
        "car_id": int(request["car_id"]),
        "title": _string(request.get("title")),
        "output_key": _string(request.get("output_key")),
        "quality": _string(request.get("quality")) or "4",
    }
    if request.get("database") not in (None, ""):
        data["database"] = str(request["database"])
    if request.get("wheel_morph_reference_helper") not in (None, ""):
        data["wheel_morph_reference_helper"] = str(request["wheel_morph_reference_helper"])
    wheel_source = _string(request.get("wheel_source"))
    if wheel_source:
        data["wheel_source"] = wheel_source
    if request.get("atlas_capacity_probe") is True:
        data["atlas_capacity_probe"] = True
    if _string(request.get("shader_validation")) in {"deferred-experimental", "overlap-experimental"}:
        data["shader_validation"] = _string(request.get("shader_validation"))
    gpu_shadow_policy = _string(request.get("gpu_shadow_policy"))
    if gpu_shadow_policy and gpu_shadow_policy != "full":
        data["gpu_shadow_policy"] = gpu_shadow_policy
    if request.get("body_kit_part_id") not in (None, ""):
        data["body_kit_part_id"] = int(request["body_kit_part_id"])
    if request.get("gamedb_car_body_id") not in (None, ""):
        data["gamedb_car_body_id"] = int(request["gamedb_car_body_id"])
    wheel_placement = _string(request.get("wheel_placement")).casefold()
    if wheel_placement and wheel_placement != "gamedb":
        data["wheel_placement"] = wheel_placement
    for key in ORGANIZER_OPTIONAL_KEYS:
        value = _string(request.get(key))
        if value:
            data[key] = value
    return data


def build_output_dir(root: Path, request: dict[str, Any]) -> Path:
    source = Path(request["source"])
    source_name = sanitize_segment(source.parent.name if source.name.casefold() == "c_livery" else source.name)
    car_id = int(request["car_id"])
    raw_key = _string(request.get("output_key", ""))
    raw_record_id = _string(request.get("record_id", ""))
    raw_slot = _string(request.get("slot_label", ""))
    raw_title = _string(request.get("title", ""))
    key = sanitize_segment(raw_key) if raw_key else ""
    record_id = sanitize_segment(raw_record_id) if raw_record_id else ""
    slot_label = sanitize_segment(raw_slot) if raw_slot else ""
    title = sanitize_segment(raw_title) if raw_title else ""
    pieces = [f"car-{car_id}", source_name]
    body_kit_part_id = request.get("body_kit_part_id")
    if body_kit_part_id not in (None, ""):
        pieces.append(f"bodykit-{int(body_kit_part_id)}")
    gamedb_car_body_id = request.get("gamedb_car_body_id")
    if gamedb_car_body_id not in (None, ""):
        pieces.append(f"gamedbbody-{int(gamedb_car_body_id)}")
    wheel_placement = _string(request.get("wheel_placement")).casefold() or "gamedb"
    if wheel_placement != "gamedb":
        pieces.append(f"wheelpos-{sanitize_segment(wheel_placement)}")
    for candidate in (key, record_id, slot_label, title):
        if candidate and candidate not in pieces:
            pieces.append(candidate)
            break
    return root / "__".join(pieces)


def read_summary(summary_path: Path) -> dict[str, Any]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("vehicle-preview-summary.json is invalid.")
    return data


def _render_contract_cache_is_current(render_contract: Path, render_root: Path) -> bool:
    try:
        contract = json.loads(render_contract.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(contract, dict) or contract.get("format") != RENDER_CONTRACT_FORMAT:
        return False
    signature = contract.get("signature")
    if not isinstance(signature, dict):
        return False
    try:
        if int(signature.get("contract_revision") or 0) != RENDER_CONTRACT_REVISION:
            return False
    except (TypeError, ValueError):
        return False

    files = contract.get("files") if isinstance(contract.get("files"), dict) else {}
    hashes = contract.get("file_sha256") if isinstance(contract.get("file_sha256"), dict) else {}
    paint_name = str(files.get("paint") or "")
    paint_cache = contract.get("paint_cache") if isinstance(contract.get("paint_cache"), dict) else {}
    paint_scope = str(paint_cache.get("scope") or "")
    mask_cache = contract.get("mask_cache") if isinstance(contract.get("mask_cache"), dict) else {}
    mask_scope = str(mask_cache.get("scope") or "")

    # r282：共有PaintはContent Addressed Rootに存在する必要がある。
    # r281の共有Mask契約ではPaintはrender_root内に残るため、そこも確認する。
    # 古いLivery別契約はこの追加検査だけで不正キャッシュ扱いしない。
    # GPU だけで絵を描く契約（gpu-session-only）は絵の画像のファイルを作らないので求めない
    # （2026-11-21。求めていたため、前のプロセスの出力の使い回しが必ず外れていた）。
    if paint_scope != "gpu-session-only" and (
            paint_scope == "shared-by-content" or mask_scope == "shared-by-model-archive"):
        paint_root_value = _string(paint_cache.get("root")) if paint_scope == "shared-by-content" else ""
        paint_root = Path(paint_root_value).resolve() if paint_root_value else render_root
        paint_candidate = paint_root / paint_name
        if not paint_name or Path(paint_name).name != paint_name or not paint_candidate.is_file():
            return False
        if hashes and hashes.get(paint_name) and _sha256_file(paint_candidate) != hashes.get(paint_name):
            return False

    if mask_scope == "shared-by-model-archive":
        mask_names = [str(name or "") for name in (files.get("masks") or [])]
        mask_root_value = _string(mask_cache.get("root"))
        mask_root = Path(mask_root_value).resolve() if mask_root_value else render_root
        if len(mask_names) != 3:
            return False
        for name in mask_names:
            candidate = mask_root / name
            if not name or Path(name).name != name or not candidate.is_file():
                return False
            if hashes and hashes.get(name) and _sha256_file(candidate) != hashes.get(name):
                return False

    base_material = contract.get("base_paint_material")
    if isinstance(base_material, dict):
        for detail_key in ("detail_normal", "detail_normal_probe"):
            detail_normal = base_material.get(detail_key)
            if isinstance(detail_normal, dict) and detail_normal.get("available"):
                if not (render_root / "base-detail-normal.png").is_file():
                    return False
        detail_mask = base_material.get("detail_mask_probe")
        if isinstance(detail_mask, dict) and detail_mask.get("available"):
            if not (render_root / "base-detail-mask.png").is_file():
                return False
    return True


LEGACY_SOURCELESS_MIGRATION_FROM_REVISION = 18
LEGACY_SOURCELESS_MIGRATION_COMPATIBLE_REVISIONS = (33,)
LEGACY_SOURCELESS_MIGRATION_TO_REVISION = 34
ALUMINUM_BRUSHED_DETAIL_NORMAL_MEMBER = (
    "roughness/swatches/dtl_brushed_001_nrml_e3dfa281-81b4-4c87-a031-c17e72d551dd.swatchbin"
)


def _prefer_current_gamesave_path(source: Path) -> Path:
    """番号付きGameSaveパスより既存のcurrentリンクを優先（通常GUIも同じ入口）。

    書換/探索で別リバリーへ移ることは禁止。親アカウントとLivery名は不変。
    currentが存在しなければ元の正常入力を維持し、旧成功入口を壊さない。
    """
    original = str(source)
    replaced = re.sub(
        r"(?i)([\\/]GameSave[\\/]pgs[\\/][^\\/]+[\\/])[0-9]+([\\/]ContainersRoot[\\/])",
        r"\g<1>current\g<2>", original, count=1,
    )
    if replaced == original:
        return source
    current = Path(replaced)
    valid = (current.is_file() if source.name.casefold() == "c_livery"
             else current.is_dir() and (current / "C_livery").is_file())
    return current if valid else source


def _requested_c_livery_path(request: dict[str, Any]) -> Path:
    source = Path(request["source"])
    return source if source.name.casefold() == "c_livery" else source / "C_livery"


def _relocated_source_candidate(request: dict[str, Any]) -> Path | None:
    """
    番号が切り替わったFH6保存コンテナー内から同一Liveryフォルダーを探す。
    """
    requested_c_livery = _requested_c_livery_path(request)
    if requested_c_livery.is_file():
        return None

    containers_root = next(
        (parent for parent in requested_c_livery.parents if parent.name.casefold() == "containersroot"),
        None,
    )
    if containers_root is None:
        return None
    container_directory = containers_root.parent
    account_root = container_directory.parent
    if not account_root.is_dir():
        return None

    livery_directory_name = requested_c_livery.parent.name
    candidates: list[Path] = []
    try:
        siblings = tuple(account_root.iterdir())
    except OSError:
        return None
    for sibling in siblings:
        if not sibling.is_dir():
            continue
        candidate = sibling / "ContainersRoot" / livery_directory_name / "C_livery"
        try:
            if candidate.is_file():
                candidates.append(candidate.resolve())
        except OSError:
            continue

    unique_candidates = list(dict.fromkeys(candidates))
    if len(unique_candidates) != 1:
        return None

    original_source = Path(request["source"])
    return unique_candidates[0] if original_source.name.casefold() == "c_livery" else unique_candidates[0].parent


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".r139.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _legacy_render_index_is_intact(render_root: Path, expected_signature: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    index_path = render_root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False, None
    if not isinstance(index, dict) or index.get("format") != RENDER_CONTRACT_FORMAT:
        return False, None
    signature = index.get("signature")
    if not isinstance(signature, dict) or signature != expected_signature:
        return False, None
    files = index.get("files")
    hashes = index.get("file_sha256")
    if not isinstance(files, dict) or not isinstance(hashes, dict):
        return False, None
    names = [files.get("paint"), *(files.get("masks") or [])]
    if len(names) != 4:
        return False, None
    for raw_name in names:
        name = str(raw_name or "")
        candidate = render_root / name
        if not name or Path(name).name != name or not candidate.is_file():
            return False, None
        if _sha256_file(candidate) != hashes.get(name):
            return False, None
    return True, index


def _upgrade_cached_material_runtime(
    contract: dict[str, Any],
    request: dict[str, Any],
    summary: dict[str, Any],
) -> bool:
    base_material = contract.get("base_paint_material")
    if not isinstance(base_material, dict):
        return True
    source_kind = str(base_material.get("source_kind") or "")
    if source_kind not in {"manufacturer_selector", "implicit_or_default", "finish_without_explicit_color", "explicit_primary_color"}:
        return True
    material_path = _string(base_material.get("material_path"))
    if not material_path:
        return False
    game_folder = Path(request["game_folder"]).expanduser().resolve()
    if not (game_folder / "media").is_dir() and (game_folder / "Content" / "media").is_dir():
        game_folder = (game_folder / "Content").resolve()
    raw_archive = _string(summary.get("vehicle_archive"))
    vehicle_archive = Path(raw_archive) if raw_archive else None
    runtime = inspect_game_material_runtime(
        game_folder,
        material_path,
        vehicle_archive=vehicle_archive if vehicle_archive and vehicle_archive.is_file() else None,
    )
    base_material["runtime_material"] = runtime
    if not runtime.get("available"):
        return False
    external_inputs = external_user_color_contract(runtime, base_material.get("num_input_colors"))
    if int(external_inputs.get("expected_input_count") or 0) > 0:
        base_material["external_color_inputs"] = external_inputs
    effective = dict(runtime.get("effective_focus") or {})
    material_color = material_defined_paint_color(effective, str(runtime.get("shader_family") or ""))
    base_material["material_defined_color"] = material_color
    if source_kind == "finish_without_explicit_color":
        family = str(runtime.get("shader_family") or "").casefold()
        automotive_families = {
            "car_automotive_paint", "car_automotive_paint_user",
            "car_candy_paint", "car_candy_paint_user",
            "car_glitter_paint", "car_glitter_paint_user",
        }
        if material_color.get("available") and material_color.get("rgba_hex"):
            rgba_hex = str(material_color["rgba_hex"])
            base_material["primary_color_rgba_hex"] = rgba_hex
            base_material["color_source"] = "material_runtime_paint_color_param"
            selection = contract.get("base_paint_selection")
            if isinstance(selection, dict):
                selection["color_available"] = True
                selection["primary_color_rgba_hex"] = rgba_hex
                selection["color_source"] = "material_runtime_paint_color_param"
                selection["semantics_status"] = (
                    "finish material is self-contained; installed FH6 material PaintColorColorParam "
                    "supplies the renderer colour without descriptor RGB"
                )
                summary["base_paint_selection"] = selection
            contract["base_paint_color_rgba_hex"] = rgba_hex
            summary["base_paint_color_rgba_hex"] = rgba_hex
        elif family in automotive_families:
            return False
    candidate, game_parameters = release_safe_viewer_candidate(
        str(base_material.get("material_name") or Path(material_path.replace("\\", "/")).stem),
        str(runtime.get("shader_family") or ""),
        effective,
        source="installed_fh6_material_runtime+r176",
    )
    base_material["shader_family"] = runtime.get("shader_family")
    base_material["roughness_shift"] = ((effective.get("Roughness_Shift_floatVal") or {}).get("value"))
    base_material["game_material_parameters"] = game_parameters
    base_material["viewer_candidate"] = candidate
    summary["base_paint_material"] = base_material
    return True


def _try_migrate_sourceless_legacy_cache(
    request: dict[str, Any],
    output_dir: Path,
    expected_vinyl_resource_root: Path,
    expected_quality: str | None,
) -> bool:
    """
    元C_liveryが既にない場合に、直前版と検証済みのCacheだけを移行する。
    """
    if RENDER_CONTRACT_REVISION != LEGACY_SOURCELESS_MIGRATION_TO_REVISION:
        return False
    if _requested_c_livery_path(request).is_file():
        return False
    summary_path = output_dir / "vehicle-preview-summary.json"
    try:
        summary = read_summary(summary_path)
    except Exception:
        return False
    required = [summary.get("private_preview"), summary.get("mesh"), summary.get("render_root"), summary.get("render_contract")]
    if any(not value for value in required) or "base_paint_selection" not in summary:
        return False
    actual_vinyl = _string(summary.get("vinyl_resource_root"))
    if not actual_vinyl or Path(actual_vinyl).resolve() != expected_vinyl_resource_root.resolve():
        return False
    if summary.get("vinyl_resource_source") != "local_fh6_cache":
        return False
    if expected_quality in {"1", "2", "3", "4"}:
        try:
            if int(summary.get("quality_scale") or 0) != int(expected_quality):
                return False
        except (TypeError, ValueError):
            return False

    package = Path(summary["private_preview"])
    mesh = Path(summary["mesh"])
    render_root = Path(summary["render_root"])
    render_contract_path = Path(summary["render_contract"])
    if not package.is_file() or not mesh.is_file() or not render_root.is_dir() or not render_contract_path.is_file():
        return False
    try:
        contract = json.loads(render_contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(contract, dict) or contract.get("format") != RENDER_CONTRACT_FORMAT:
        return False
    signature = contract.get("signature")
    if not isinstance(signature, dict):
        return False
    try:
        revision = int(signature.get("contract_revision") or 0)
    except (TypeError, ValueError):
        return False
    if revision not in LEGACY_SOURCELESS_MIGRATION_COMPATIBLE_REVISIONS:
        return False

    diagnostics_path = output_dir / "paint-finish-candidate-diagnostics.json"
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    dominant = dict(diagnostics.get("dominant_repeated_non_panel_descriptor_cluster") or {})
    current_selection = dict(contract.get("base_paint_selection") or summary.get("base_paint_selection") or {})
    if not dominant:
        return False
    if (
        int(current_selection.get("finish_code_raw") or 0) != int(dominant.get("finish_code_raw") or 0)
        or [int(value) for value in (current_selection.get("record_indices") or [])]
        != [int(value) for value in (dominant.get("record_indices") or [])]
    ):
        return False

    intact, index = _legacy_render_index_is_intact(render_root, signature)
    if not intact or index is None:
        return False

    if not _upgrade_cached_material_runtime(contract, request, summary):
        return False

    base_material = contract.get("base_paint_material")
    if isinstance(base_material, dict):
        game_folder = Path(request["game_folder"]).resolve()
        if not (game_folder / "media").is_dir() and (game_folder / "Content" / "media").is_dir():
            game_folder = game_folder / "Content"
        material_name = str(base_material.get("material_name") or "").casefold()
        shader_family = str(base_material.get("shader_family") or "").casefold()
        if revision == LEGACY_SOURCELESS_MIGRATION_FROM_REVISION and material_name == "aluminumbrushed":
            detail_result = extract_swatch_preview_from_zip(
                game_folder / "media" / "cars" / "_library" / "Textures.zip",
                ALUMINUM_BRUSHED_DETAIL_NORMAL_MEMBER,
                render_root / "base-detail-normal.png",
            )
            if not detail_result.get("available"):
                return False
            base_material["detail_normal"] = {
                **{key: value for key, value in detail_result.items() if key != "output"},
                "local_render_endpoint": "api/local-render/base-detail-normal",
            }
        elif shader_family in {"car_carbonfiber", "car_carbonfiber_user"}:
            candidate = dict(base_material.get("viewer_candidate") or {})
            runtime = dict(base_material.get("runtime_material") or {})
            normal_assets = [
                dict(row) for row in (runtime.get("material_texture_assets") or [])
                if isinstance(row, dict) and row.get("available") and row.get("role_candidate") == "normal_candidate"
            ]
            if (
                len(normal_assets) == 1
                and "detail_normal_u_tiling" in candidate
                and "detail_normal_v_tiling" in candidate
            ):
                detail_result = extract_material_texture_preview(
                    normal_assets[0], render_root / "base-detail-normal.png"
                )
                if not detail_result.get("available"):
                    return False
                normal_binding = texture_binding_evidence(
                    runtime, str(normal_assets[0].get("reference") or "")
                )
                detail_common = {
                    **{key: value for key, value in detail_result.items() if key != "output"},
                    "u_tiling": candidate.get("detail_normal_u_tiling"),
                    "v_tiling": candidate.get("detail_normal_v_tiling"),
                    "scope": "exposed_base_paint_only",
                    "local_render_endpoint": "api/local-render/base-detail-normal",
                    "shader_texture_binding": normal_binding,
                }
                if "detail_normal_three_uv_channel" in candidate:
                    base_material["detail_normal"] = {
                        **detail_common,
                        "production_enabled": True,
                        "three_uv_channel": candidate.get("detail_normal_three_uv_channel"),
                        "uv_choice_on_ch1_off_ch2": candidate.get("detail_normal_uv_choice_on_ch1_off_ch2"),
                        "uv_resolution": candidate.get("detail_normal_uv_resolution", "shader_parameter"),
                        "uv_evidence": candidate.get("detail_normal_uv_evidence"),
                    }
                    if candidate.get("detail_normal_uv_candidates"):
                        base_material["detail_normal_probe"] = {
                            **detail_common,
                            "production_enabled": False,
                            "production_uv_channel": candidate.get("detail_normal_three_uv_channel"),
                            "uv_resolution": candidate.get("detail_normal_uv_resolution", "audited_fixed_shader_path_uv0"),
                            "uv_candidates": list(candidate.get("detail_normal_uv_candidates") or [0, 1]),
                            "reason": "production UV channel is audited; alternate channel retained for diagnostics",
                        }
                else:
                    base_material["detail_normal_probe"] = {
                        **detail_common,
                        "production_enabled": False,
                        "uv_resolution": candidate.get("detail_normal_uv_resolution", "fixed_shader_path_unresolved"),
                        "uv_candidates": list(candidate.get("detail_normal_uv_candidates") or [0, 1]),
                        "reason": "installed carbon shader exposes tiling but no UVChoice parameter",
                    }
            mask_assets = [
                dict(row) for row in (runtime.get("material_texture_assets") or [])
                if isinstance(row, dict) and row.get("available") and row.get("role_candidate") == "mask_candidate"
            ]
            if (
                len(mask_assets) == 1
                and "detail_normal_u_tiling" in candidate
                and "detail_normal_v_tiling" in candidate
            ):
                mask_result = extract_material_texture_preview(
                    mask_assets[0], render_root / "base-detail-mask.png"
                )
                if not mask_result.get("available"):
                    return False
                mask_binding = texture_binding_evidence(
                    runtime, str(mask_assets[0].get("reference") or "")
                )
                weave_evidence = weave_semantic_evidence(runtime)
                bound_names = {str(name).casefold() for name in mask_binding.get("parameter_names") or []}
                mask_is_weave = "weavemask_texture" in bound_names
                base_material["detail_mask_probe"] = {
                    **{key: value for key, value in mask_result.items() if key != "output"},
                    "u_tiling": candidate.get("detail_normal_u_tiling"),
                    "v_tiling": candidate.get("detail_normal_v_tiling"),
                    "scope": "diagnostic_only",
                    "local_render_endpoint": "api/local-render/base-detail-mask",
                    "production_enabled": False,
                    "shader_texture_binding": mask_binding,
                    "weave_semantic_evidence": weave_evidence,
                    "semantic_resolution": "audited_weave_mask_binding" if mask_is_weave else "unresolved_texture_binding",
                    "uv_resolution": "unresolved_weave_mask_semantics",
                    "uv_candidates": [0, 1],
                    "reason": (
                        "installed material Texture2D record binds this swatch to WeaveMask_Texture; exact downstream shader equation and UV semantics remain diagnostic"
                        if mask_is_weave else
                        "filename-explicit carbon weave mask; exact shader binding was not resolved"
                    ),
                }

    signature["contract_revision"] = RENDER_CONTRACT_REVISION
    index_signature = index.get("signature")
    if not isinstance(index_signature, dict):
        return False
    index_signature["contract_revision"] = RENDER_CONTRACT_REVISION
    summary["render_contract_revision"] = RENDER_CONTRACT_REVISION
    summary["cache_migration"] = {
        "from_render_contract_revision": revision,
        "to_render_contract_revision": RENDER_CONTRACT_REVISION,
        "reason": "original C_livery unavailable; preserved verified cached livery atlases and mesh",
    }
    _write_json_atomic(render_root / "index.json", index)
    _write_json_atomic(render_contract_path, contract)
    _write_json_atomic(summary_path, summary)
    return cached_preview_ready(output_dir, expected_vinyl_resource_root, expected_quality)


def _migrate_legacy_preview_mesh_to_shared_cache(output_dir: Path, shared_root: Path) -> bool:
    """
    旧プレビューごとの車体GLBを共有車両キャッシュへ移す。
    """
    summary_path = output_dir / "vehicle-preview-summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = read_summary(summary_path)
    except Exception:
        return False
    raw_mesh = _string(summary.get("mesh"))
    if not raw_mesh:
        return False
    mesh = Path(raw_mesh).resolve()
    shared_root = shared_root.resolve()
    try:
        mesh.relative_to(shared_root)
        return False
    except ValueError:
        pass
    try:
        mesh.relative_to(output_dir.resolve())
    except ValueError:
        return False
    if not mesh.is_file() or mesh.suffix.casefold() != ".glb":
        return False

    shared_mesh_dir = shared_root / "meshes"
    shared_mesh_dir.mkdir(parents=True, exist_ok=True)
    target = shared_mesh_dir / mesh.name
    moved = False
    if target.is_file():
        try:
            if target.stat().st_size != mesh.stat().st_size or _sha256_file(target) != _sha256_file(mesh):
                return False
        except OSError:
            return False
    else:
        try:
            mesh.replace(target)
            moved = True
        except OSError:
            return False

    updated = dict(summary)
    updated["mesh"] = str(target)
    updated["vehicle_cache_root"] = str(shared_root)
    updated["vehicle_mesh_cache_scope"] = "shared-by-model-archive-revision"
    updated["vehicle_mesh_cache_migrated"] = True
    try:
        _write_json_atomic(summary_path, updated)
    except OSError:
        if moved:
            try:
                target.replace(mesh)
            except OSError:
                pass
        return False

    if not moved:
        try:
            mesh.unlink()
        except OSError:
            pass
    try:
        mesh.parent.rmdir()
    except OSError:
        pass
    return True


def _valid_explicit_paint_color(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{8}", value) is not None and value[-2:].casefold() != "00"


def _r150_base_paint_selection_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    dominant = dict(diagnostics.get("dominant_repeated_non_panel_descriptor_cluster") or {})
    if dominant:
        color = dominant.get("primary_color_rgba_hex")
        if (
            int(dominant.get("count") or 0) >= 2
            and bool(dominant.get("primary_color_enabled"))
            and _valid_explicit_paint_color(color)
        ):
            finish = dominant.get("finish_code_raw")
            return {
                "source": "dominant_repeated_non_panel_descriptor_cluster",
                "available": finish is not None,
                "finish_code_raw": int(finish) if finish is not None else None,
                "primary_color_enabled": True,
                "primary_color_rgba_hex": color,
                "cluster_count": int(dominant.get("count") or 0),
                "record_indices": [int(value) for value in (dominant.get("record_indices") or [])],
                "semantics_status": (
                    "dominant descriptor-table primary color is renderer-authoritative; "
                    "lower-frequency coloured clusters are not base-paint substitutes"
                ),
            }
        return {}

    special = dict(diagnostics.get("dominant_repeated_non_panel_special_finish_cluster") or {})
    candidates = [special] if special else []
    candidates.extend(dict(item) for item in (diagnostics.get("non_panel_clusters") or []))
    seen: set[tuple[Any, ...]] = set()
    for item in candidates:
        key = (
            item.get("finish_code_raw"),
            item.get("primary_color_rgba_hex"),
            tuple(item.get("record_indices") or []),
        )
        if key in seen:
            continue
        seen.add(key)
        if int(item.get("count") or 0) < 2:
            continue
        if not bool(item.get("primary_color_enabled")):
            continue
        color = item.get("primary_color_rgba_hex")
        if not _valid_explicit_paint_color(color):
            continue
        finish = item.get("finish_code_raw")
        source = (
            "dominant_repeated_non_panel_special_finish_cluster"
            if item is special and special
            else "dominant_repeated_non_panel_colored_cluster"
        )
        return {
            "source": source,
            "available": finish is not None,
            "finish_code_raw": int(finish) if finish is not None else None,
            "primary_color_enabled": True,
            "primary_color_rgba_hex": color,
            "cluster_count": int(item.get("count") or 0),
            "record_indices": [int(value) for value in (item.get("record_indices") or [])],
            "semantics_status": (
                "descriptor-table primary color is renderer-authoritative; "
                "finish name/material enrichment remains independently mapped"
            ),
        }
    return {}


def _migrate_r150_base_paint_color(output_dir: Path) -> bool:
    """
    通常Paintの色が欠落していたr150以前のCacheメタデータを修復する。
    """
    summary_path = output_dir / "vehicle-preview-summary.json"
    diagnostics_path = output_dir / "paint-finish-candidate-diagnostics.json"
    contract_path = output_dir / "local-render-contract.json"
    if not summary_path.is_file() or not diagnostics_path.is_file() or not contract_path.is_file():
        return False
    try:
        summary = read_summary(summary_path)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False

    current = dict(summary.get("base_paint_selection") or contract.get("base_paint_selection") or {})
    if bool(current.get("available")) and _valid_explicit_paint_color(current.get("primary_color_rgba_hex")):
        return False
    selection = _r150_base_paint_selection_from_diagnostics(diagnostics)
    if not selection.get("available"):
        return False

    updated_contract = dict(contract)
    updated_contract["base_paint_selection"] = selection
    updated_contract["base_paint_color_rgba_hex"] = selection.get("primary_color_rgba_hex")
    updated_summary = dict(summary)
    updated_summary["base_paint_selection"] = selection
    updated_summary["base_paint_color_cache_migrated"] = True
    _write_json_atomic(contract_path, updated_contract)
    _write_json_atomic(summary_path, updated_summary)
    return True


# ---- 同じプロセスの中だけの準備の近道（2026-11-20、FH6 に近づける案 ②）----
# このプロセスで準備したペイントの出力を、同じペイントを開き直したときに使い回す（準備の本体を動かさない）。
# プロセスが同じなのでコードは同じ。確かめるもの：準備に渡す依頼の値・C_livery の中身の SHA・ゲームの _library
# 以下の全ファイルの識別・ゲームの版の目印・出力と参照するファイル（要約・描画の目録・パッケージ・車体の GLB・
# 車の ZIP・GameDB・部品の重ね合わせ・覆い）の場所・大きさ・更新日時・目録が参照する車の解析の結果。
# 1 つでも違う・読めないときは、今までどおり準備する。ディスクには何も書かない（プロセスが終われば消える）。
_PREPARED_IN_PROCESS: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_PREPARED_IN_PROCESS_LOCK = threading.Lock()
_PREPARED_IN_PROCESS_LIMIT = 16
_GAME_VERSION_MARKERS = ("appxmanifest.xml", "MicrosoftGame.Config")
# 準備の本体へ渡す依頼の値（prepare_preview の引数になるもの）
_PREPARE_REQUEST_KEYS = ("source", "game_folder", "car_id", "quality", "private_context_mask_visual_check",
                         "database", "gamedb_car_body_id", "wheel_placement", "body_kit_part_id")


def _prepared_request_key(request: dict[str, Any]) -> str:
    values = {key: ("" if request.get(key) in (None, "") else str(request.get(key))) for key in _PREPARE_REQUEST_KEYS}
    values["wheel_placement"] = values["wheel_placement"].casefold() or "gamedb"
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def _in_process_guard(output_dir: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    """近道の確かめに使う値。集められない（ファイルが無い・SHA が合わない）ときは None（近道を使わない）。"""
    from tools.livery import shared_contract_results
    from tools.livery.material_runtime import _library_files_identity
    from tools.livery.process_file_memo import file_identity
    try:
        summary_path = output_dir / "vehicle-preview-summary.json"
        summary = read_summary(summary_path)
        c_livery = Path(str(summary.get("source") or ""))
        c_livery_sha256 = str(summary.get("source_c_livery_sha256") or "")
        if len(c_livery_sha256) != 64 or not c_livery.is_file():
            return None
        if hashlib.sha256(c_livery.read_bytes()).hexdigest() != c_livery_sha256:
            return None
        import vehicle_preview
        content = vehicle_preview._runtime_content_root(Path(str(summary.get("game_folder") or "")))
        render_contract = Path(str(summary["render_contract"]))
        contract = json.loads(render_contract.read_text(encoding="utf-8"))
        if (not isinstance(contract, dict)
                or shared_contract_results.resolve(contract, summary.get("vehicle_cache_root")) is None):
            return None
        files = [summary_path, render_contract, Path(str(summary["private_preview"])), Path(str(summary["mesh"]))]
        for key in ("vehicle_archive", "game_database", "body_kit_overlay_mesh"):
            value = _string(summary.get(key))
            if value:
                files.append(Path(value))
        mask_cache = contract.get("mask_cache") if isinstance(contract.get("mask_cache"), dict) else {}
        mask_root = Path(_string(mask_cache.get("root")) or _string(summary.get("render_root")))
        files.extend(mask_root / str(name) for name in ((contract.get("files") or {}).get("masks") or []))
        files.extend(content / name for name in _GAME_VERSION_MARKERS if (content / name).is_file())
        identities = {str(item): file_identity(item) for item in files}
        if any(identity is None for identity in identities.values()):
            return None
        library = hashlib.sha256(repr(_library_files_identity(content)).encode("utf-8")).hexdigest()
        return {"request": _prepared_request_key(request), "c_livery_sha256": c_livery_sha256,
                "library": library, "files": identities}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _remember_prepared_in_process(output_dir: Path, request: dict[str, Any]) -> None:
    key = os.path.normcase(str(output_dir.resolve()))
    guard = _in_process_guard(output_dir, request)
    with _PREPARED_IN_PROCESS_LOCK:
        _PREPARED_IN_PROCESS.pop(key, None)
        if guard is not None:
            _PREPARED_IN_PROCESS[key] = guard
            while len(_PREPARED_IN_PROCESS) > _PREPARED_IN_PROCESS_LIMIT:
                _PREPARED_IN_PROCESS.popitem(last=False)
    _write_prepared_guard(output_dir, guard)


# ---- プロセスをまたぐ近道（2026-11-21）----
# Viewer を開き直したとき（新しいプロセス）、前に準備したペイントの出力を使い回す。GPU だけで絵を描くように
# なってから、近道の判断（cached_preview_ready）は絵の画像のファイルを求めて必ず外れ、開き直すたびに準備を
# 一からやり直していた。同じプロセスの近道と同じ値（依頼・C_livery の SHA・ライブラリ・関係するファイル）に、
# コードの識別を足して出力のフォルダーに残し、次のプロセスで今の値と比べる。ファイルは場所・大きさ・更新日時で
# 比べる（車体の GLB は圧縮の写しから戻すとファイルの番号が変わるが、更新日時は元に戻る）。
PREPARED_GUARD_FILE = "prepared-guard.json"
PREPARED_GUARD_FORMAT = "lo4fh6_prepared_guard_v1"
_PREPARED_CODE_IDENTITY: str | None = None


def _prepared_code_identity() -> str:
    """準備の出力を作るコードの識別。ソースなら Viewer の .py・.json の場所・大きさ・更新日時、EXE なら EXE 自身の
    名前・大きさ・更新日時（どちらもコードを直せば変わる）。

    画面の側（tools/livery-inspector）と試験は、準備の出力に関わらないので含めない。ファイルは開かず、フォルダーの
    一覧の情報だけを使う（中身の SHA は 143 個を開くのに約 0.2 秒かかった）。プロセスごとに 1 回だけ求める。
    """
    global _PREPARED_CODE_IDENTITY
    if _PREPARED_CODE_IDENTITY is None:
        from tools.livery import vehicle_analysis_cache
        if vehicle_analysis_cache._is_packaged():
            identity = vehicle_analysis_cache._packaged_program_identity().decode("utf-8")
        else:
            skip = {"tests", "__pycache__", "livery-inspector"}
            rows: list[str] = []
            folders = [(ROOT, "")]
            while folders:
                folder, prefix = folders.pop()
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in skip:
                                folders.append((Path(entry.path), prefix + entry.name + "/"))
                        elif entry.name.endswith((".py", ".json")) and entry.is_file():
                            stat = entry.stat()
                            rows.append(f"{prefix}{entry.name}|{stat.st_size}|{stat.st_mtime_ns}")
            identity = "source:" + hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()
        _PREPARED_CODE_IDENTITY = identity
    return _PREPARED_CODE_IDENTITY


def _disk_guard_from(guard: dict[str, Any]) -> dict[str, Any]:
    files = {path: [identity[3], identity[4]] for path, identity in guard["files"].items()}  # 大きさ・更新日時
    return {"format": PREPARED_GUARD_FORMAT, "code": _prepared_code_identity(), "request": guard["request"],
            "c_livery_sha256": guard["c_livery_sha256"], "library": guard["library"], "files": files}


def _write_prepared_guard(output_dir: Path, guard: dict[str, Any] | None) -> None:
    """近道の値を出力のフォルダーに残す。値を集められないときは、古い値を消す（近道を使わない）。"""
    path = output_dir / PREPARED_GUARD_FILE
    try:
        if guard is None:
            path.unlink(missing_ok=True)
            return
        data = _disk_guard_from(guard)
        try:
            if json.loads(path.read_text(encoding="utf-8")) == data:
                return
        except (OSError, ValueError):
            pass
        _write_json_atomic(path, data)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _prepared_on_disk(output_dir: Path, request: dict[str, Any]) -> bool:
    """前のプロセスで準備した出力が、今の依頼・原本・ゲームのファイル・コードのままか。"""
    try:
        recorded = json.loads((output_dir / PREPARED_GUARD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(recorded, dict) or recorded.get("format") != PREPARED_GUARD_FORMAT:
        return False
    try:
        if recorded.get("code") != _prepared_code_identity():
            return False
        # 車体の GLB が以前の版の圧縮の写しだけになっていれば、元の場所・元の更新日時で戻す（_prepared_in_this_process と
        # 同じ）。消した印だけのとき（2026-11-21〜、chassis_store）は、下の照合が合わず、準備をやり直す（作り直す）。
        from tools.livery import chassis_store
        chassis_store.prepare_for_use(Path(str(read_summary(output_dir / "vehicle-preview-summary.json")["mesh"])))
        guard = _in_process_guard(output_dir, request)
        return guard is not None and _disk_guard_from(guard) == recorded
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return False


def _prepared_in_this_process(output_dir: Path, request: dict[str, Any]) -> bool:
    """このプロセスで準備した出力が、今の依頼・原本・ゲームのファイルのままか（そのまま使えるか）。"""
    key = os.path.normcase(str(output_dir.resolve()))
    with _PREPARED_IN_PROCESS_LOCK:
        recorded = _PREPARED_IN_PROCESS.get(key)
    if recorded is None:
        return False
    try:
        # 車体の GLB が以前の版の圧縮の写しだけになっていれば、元の場所・元の更新日時で戻す（識別は変わらない）。
        # 消した印だけのときは、下の照合が合わず、準備をやり直す（作り直す。chassis_store、2026-11-21）。
        from tools.livery import chassis_store
        chassis_store.prepare_for_use(Path(str(read_summary(output_dir / "vehicle-preview-summary.json")["mesh"])))
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return _in_process_guard(output_dir, request) == recorded


# ---- ペイントの準備のフォルダーは、最近の数件だけ残す（2026-11-20、FH6 に近づける案 ②）----
# 窓で開いたペイントの準備のフォルダー（car-<ID>__…、1 件 約 0.4 MB）は、開いたペイントの数だけ溜まっていた。
# 窓で開いた後に、表示中のものと最近使った数件のほかを消す。元のペイントが無いもの（作り直せない）・記録が
# 読めないもの・最近（10 分以内）使ったもの（別の窓が表示中かもしれない）は消さない。リンクは辿らない。
PAINT_FOLDER_KEEP = 3
PAINT_FOLDER_PROTECT_SECONDS = 600.0


def _paint_folder_last_used(folder: Path) -> float:
    latest = 0.0
    for name in ("organizer-preview-request.normalized.json", "viewer-startup-metrics.json",
                 "vehicle-preview-summary.json"):
        with contextlib.suppress(OSError):
            latest = max(latest, (folder / name).stat().st_mtime)
    return latest


def _retain_recent_paint_folders(output_root: Path, current: Path, *, keep: int = PAINT_FOLDER_KEEP,
                                 protect_seconds: float = PAINT_FOLDER_PROTECT_SECONDS,
                                 now: float | None = None) -> list[str]:
    """表示中・最近のペイントの準備のフォルダーのほかを消し、消したフォルダーの名前を返す。"""
    from tools.livery import vehicle_cache_limit as limit
    now = time.time() if now is None else now
    current_key = limit._key(current)
    candidates: list[tuple[float, Path]] = []
    leftovers: list[Path] = []
    try:
        entries = list(Path(output_root).iterdir())
    except OSError:
        return []
    for folder in entries:
        if not folder.is_dir() or limit._is_link(folder) or not limit.PREPARED_DIR_RE.match(folder.name):
            continue
        if limit.DELETING_MARK in folder.name:
            leftovers.append(folder)
            continue
        if limit._key(folder) == current_key:
            continue
        try:
            request = json.loads((folder / limit.REQUEST_FILE).read_text(encoding="utf-8"))
            source = request.get("source") if isinstance(request, dict) else None
        except (OSError, ValueError):
            continue
        if not isinstance(source, str) or not source or not Path(source).exists():
            continue
        used = _paint_folder_last_used(folder)
        if now - used < protect_seconds:
            continue
        candidates.append((used, folder))
    candidates.sort(key=lambda row: row[0], reverse=True)
    removed: list[str] = []
    for folder in leftovers + [folder for _used, folder in candidates[max(0, keep - 1):]]:
        unit = limit.CacheUnit(kind="prepared", paths=[folder])
        if limit._delete_unit(Path(output_root), unit) is None:
            removed.append(folder.name)
    return removed


def _retain_recent_paint_folders_later(output_root: Path, current: Path) -> None:
    """窓で開いた後に、裏でペイントの準備のフォルダーを整理する（表示を待たせない）。"""
    def work() -> None:
        try:
            removed = _retain_recent_paint_folders(output_root, current)
            if removed:
                _append_bridge_log(f"paint folders removed: {len(removed)}")
        except Exception as exc:  # noqa: BLE001  整理の失敗で表示を止めない
            _append_bridge_log(f"paint folder cleanup ERROR: {type(exc).__name__}: {exc}")
    threading.Thread(target=work, name="lo4fh6-paint-folder-cleanup", daemon=True).start()


def cached_preview_ready(
    output_dir: Path,
    expected_vinyl_resource_root: Path | None = None,
    expected_quality: str | None = None,
    expected_database: Path | None = None,
    expected_wheel_morph_reference_helper: Path | None = None,
    expected_gpu_shadow_policy: str | None = None,
) -> bool:
    summary_path = output_dir / "vehicle-preview-summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = read_summary(summary_path)
    except Exception:
        return False
    required = [
        summary.get("private_preview"),
        summary.get("mesh"),
        summary.get("render_root"),
        summary.get("render_contract"),
    ]
    if any(not path for path in required):
        return False
    # r129のRenderer契約：Base Paintの明示的なルーティング以前のCacheを扱う。
    if "base_paint_selection" not in summary:
        return False
    if expected_vinyl_resource_root is not None:
        actual = _string(summary.get("vinyl_resource_root"))
        if not actual or Path(actual).resolve() != expected_vinyl_resource_root.resolve():
            return False
        if summary.get("vinyl_resource_source") != "local_fh6_cache":
            return False
    if expected_quality in {"1", "2", "3", "4"}:
        try:
            if int(summary.get("quality_scale") or 0) != int(expected_quality):
                return False
        except (TypeError, ValueError):
            return False
    if expected_database is not None:
        try:
            expected_database = expected_database.resolve()
            stat = expected_database.stat()
            actual = _string(summary.get("game_database"))
            if not actual or Path(actual).resolve() != expected_database:
                return False
            if int(summary.get("game_database_size") or -1) != int(stat.st_size):
                return False
            if int(summary.get("game_database_mtime_ns") or -1) != int(stat.st_mtime_ns):
                return False
        except (OSError, TypeError, ValueError):
            return False
    if expected_wheel_morph_reference_helper is not None:
        try:
            expected_wheel_morph_reference_helper = expected_wheel_morph_reference_helper.resolve()
            actual = _string(summary.get("wheel_morph_reference_helper"))
            if not actual or Path(actual).resolve() != expected_wheel_morph_reference_helper:
                return False
            if not _string(summary.get("wheel_morph_reference_helper_sha256")):
                return False
        except (OSError, TypeError, ValueError):
            return False
    elif _string(summary.get("wheel_morph_reference_helper")):
        # 通常Viewerで研究用Oracle Cacheを無告知で再利用しない。
        return False
    package = Path(summary["private_preview"])
    mesh = Path(summary["mesh"])
    render_root = Path(summary["render_root"])
    render_contract = Path(summary["render_contract"])
    if expected_gpu_shadow_policy is not None:
        try:
            contract_data = json.loads(render_contract.read_text(encoding="utf-8"))
            if _string(contract_data.get("cpu_shadow_policy")) != expected_gpu_shadow_policy:
                return False
        except (OSError, ValueError, TypeError, AttributeError):
            return False
    # 目録が車の解析の結果を参照で持つなら、その結果が今もあって中身が同じこと（無ければ準備をやり直す）
    try:
        from tools.livery import shared_contract_results
        contract_data = json.loads(render_contract.read_text(encoding="utf-8"))
        if (not isinstance(contract_data, dict)
                or shared_contract_results.resolve(contract_data, summary.get("vehicle_cache_root")) is None):
            return False
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    overlay_plan = summary.get("body_kit_overlay_plan") if isinstance(summary.get("body_kit_overlay_plan"), dict) else {}
    overlay_added = overlay_plan.get("added_entries") if isinstance(overlay_plan.get("added_entries"), list) else []
    overlay_value = _string(summary.get("body_kit_overlay_mesh"))
    overlay_ready = True
    # 第一者製品v13：古い署名参照製品 GLB、過去研究GLB、旧overlay v1を
    # キャッシュ扱いで黙って再利用しない。元の正常ZIP／キャッシュは残す。
    # 完全なGLB構造とSource scopeを両方検査する。
    try:
        from tools.livery.portable_mesh_converter import (
            BODY_KIT_OVERLAY_FORMAT_REVISION,
            LOCAL_CHASSIS_FORMAT_REVISION,
            PortableMeshConverterError,
            validate_local_chassis_glb,
        )
        if f".local-chassis-v{LOCAL_CHASSIS_FORMAT_REVISION}" not in mesh.name:
            return False
        # キャッシュの出所と同じ原本ZIPが今も存在し、実SHAが一致すること。
        # ファイル名／mtime／summaryの自己申告だけでは再利用を認めない。
        from tools.livery.vehicle_assets import sha256_file
        archive_value = _string(summary.get("vehicle_archive"))
        archived_sha = _string(summary.get("vehicle_archive_sha256")).lower()
        if (not archive_value or len(archived_sha) != 64
                or any(ch not in "0123456789abcdef" for ch in archived_sha)
                or archived_sha not in mesh.name):
            return False
        original_archive = Path(archive_value)
        if (not original_archive.is_absolute() or original_archive.is_symlink()
                or not original_archive.is_file()
                or sha256_file(original_archive) != archived_sha):
            return False
        # 最近使っていない車の車体の GLB は消して、消した印だけを残している（chassis_store、2026-11-21）。以前の版の
        # 圧縮した写しがあれば元の場所・元の更新日時で戻し、最後に使った印を付けてから確かめる（この準備の間に裏の
        # 整理で消されない）。GLB が無ければ、下の確かめで外れて準備をやり直す（作り直す）。
        from tools.livery import chassis_store
        chassis_store.prepare_for_use(mesh)
        validate_local_chassis_glb(
            mesh, require_product_accepted=True,
            required_firstparty_scope="ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE",
        )
        if overlay_added:
            if overlay_value:
                chassis_store.prepare_for_use(Path(overlay_value))  # 重ね合わせの GLB も圧縮した写しから戻す
            overlay_ready = bool(overlay_value and Path(overlay_value).is_file())
            if (not overlay_ready or f"overlay-firstparty-v{BODY_KIT_OVERLAY_FORMAT_REVISION}.glb" not in Path(overlay_value).name
                    or archived_sha not in Path(overlay_value).name):
                return False
            validate_local_chassis_glb(
                Path(overlay_value), require_product_accepted=True,
                required_firstparty_scope="ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE",
            )
    except (OSError, ValueError, PortableMeshConverterError):
        return False
    return (
        package.is_file()
        and mesh.is_file()
        and render_root.is_dir()
        and render_contract.is_file()
        and overlay_ready
        and _render_contract_cache_is_current(render_contract, render_root)
    )


def _worker_log_path(output_dir: Path) -> Path:
    return output_dir / "preview-worker.log"


def _read_worker_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").rstrip()
    except OSError:
        return ""


def _run_preview_prepare_in_process(
    command_args: list[str],
    worker_log: Path,
) -> int:
    """
    WindowsではGUIと同じプロセス内でプレビュー準備を実行する。
    """
    worker_log.parent.mkdir(parents=True, exist_ok=True)
    old_argv = sys.argv[:]
    try:
        # EXE では sys.argv[0] を本物（配布した EXE）のままにする。EXE の識別（解析の鍵）や、EXE 自身を別のプロセスで
        # 起動する所が sys.argv[0] を使うため、EXE の中に無い vehicle_preview.py に置き換えると、窓の流れの準備が
        # 「ファイルが見つかりません」で止まっていた（2026-11-20）。ソースから動かすときは今までどおり。
        from lo4fh6_desktop_suite.runtime import is_packaged
        program = old_argv[0] if (is_packaged() and old_argv) else str(PREVIEW_SCRIPT)
        sys.argv = [program, *command_args]
        with worker_log.open("w", encoding="utf-8", errors="replace", buffering=1) as handle, \
             contextlib.redirect_stdout(handle), \
             contextlib.redirect_stderr(handle):
            try:
                # 部品として 1 回だけ読み込んで同じ処理を呼ぶ（EXE の中にはスクリプトのファイルが無い）。
                # ソースから動かすときも同じにする。以前は runpy.run_path でペイントのたびにスクリプトを翻訳し直していた
                # （約 0.07 秒。2026-11-20）。準備の本体はモジュールの状態に頼らない（EXE で同じ使い方をしている）。
                import vehicle_preview
                vehicle_preview.run_as_program()
            except SystemExit as exc:
                code = exc.code
                if code is None:
                    return 0
                if isinstance(code, int):
                    return code
                print(code, file=handle)
                return 1
        return 0
    finally:
        sys.argv = old_argv


def prepare_preview(
    request: dict[str, Any],
    output_dir: Path,
    vinyl_resource_root: Path | None = None,
    *,
    hide_window: bool = False,
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    worker_log = _worker_log_path(output_dir)
    command_args = [
        str(request["source"]),
        "--game-folder",
        str(request["game_folder"]),
        "--car-id",
        str(request["car_id"]),
        "--quality",
        str(request["quality"]),
        "--output",
        str(output_dir),
        "--prepare-only",
        "--no-open",
        "--viewer-fast-path",
        "--vehicle-cache-root",
        str((output_dir.parent / "_fh6-vehicle-cache").resolve()),
    ]
    if request.get("private_context_mask_visual_check") is True:
        command_args.append("--private-context-mask-visual-check")
    if vinyl_resource_root is not None:
        command_args.extend(["--vinyl-resource-root", str(vinyl_resource_root)])
    if request.get("database") not in (None, ""):
        command_args.extend(["--database", str(request["database"])])
    if request.get("gamedb_car_body_id") not in (None, ""):
        command_args.extend(["--gamedb-car-body-id", str(int(request["gamedb_car_body_id"]))])
    wheel_placement = _string(request.get("wheel_placement")).casefold() or "gamedb"
    command_args.extend(["--wheel-placement", wheel_placement])
    gpu_shadow_policy = "gpu-only"
    command_args.extend(["--gpu-shadow-policy", gpu_shadow_policy])
    if request.get("body_kit_part_id") not in (None, ""):
        command_args.extend(["--body-kit-part-id", str(int(request["body_kit_part_id"]))])

    # Organizer連携のサポート環境はWindows。
    # 登録済みGUIの準備処理はpythonw内で完結させ、追加のPython Consoleを作らない。
    if hide_window and sys.platform == "win32":
        exit_code = _run_preview_prepare_in_process(command_args, worker_log)
        captured = _read_worker_log(worker_log)
        if captured:
            _append_bridge_log(captured)
        if exit_code != 0:
            if captured:
                tail = "\n".join(captured.splitlines()[-20:])
                _append_bridge_log(f"preview worker exit={exit_code}; tail:\n{tail}")
            raise ValueError(
                f"3D preview preparation failed (exit code {exit_code}). "
                f"See diagnostic log: {_bridge_log_path()}"
            )
        return

    from lo4fh6_desktop_suite.runtime import self_command
    command = self_command("vehicle-preview", *command_args, python=_console_python_executable())
    run_kwargs: dict[str, Any] = {}
    if request.get("private_context_mask_visual_check") is True:
        # 研究Viewer限定: 失敗時の子stderrを保存し、原因不明Exit1を防止。
        # 正常GUI/Organizerのsubprocess起動経路は既存のまま維持。
        worker_log.parent.mkdir(parents=True, exist_ok=True)
        with worker_log.open("w", encoding="utf-8", errors="replace", buffering=1) as handle:
            result = subprocess.run(
                command, check=False, stdout=handle, stderr=subprocess.STDOUT,
                **run_kwargs,
            )
        captured = _read_worker_log(worker_log)
        if result.returncode:
            tail = "\n".join(captured.splitlines()[-35:]) if captured else "(worker output empty)"
            _append_bridge_log("Mask research preview worker failed: " + tail)
            print("MASK_RESEARCH_PREPARE_ERROR_LOG=" + str(worker_log), file=sys.stderr)
            print("MASK_RESEARCH_PREPARE_ERROR_TAIL:\n" + tail, file=sys.stderr)
            raise ValueError(
                f"Mask research preview worker exit={result.returncode}; "
                f"log={worker_log}"
            )
        _append_bridge_log("Mask research preview worker PASS; log=" + str(worker_log))
        return
    try:
        result = subprocess.run(command, check=True, **run_kwargs)
    except subprocess.CalledProcessError as exc:
        captured = str(getattr(exc, "stdout", "") or "").rstrip()
        if captured:
            _append_bridge_log(captured)
            tail = "\n".join(captured.splitlines()[-20:])
            _append_bridge_log(f"preview worker exit={exc.returncode}; tail:\n{tail}")
        raise ValueError(
            f"3D preview preparation failed (exit code {exc.returncode}). "
            f"See diagnostic log: {_bridge_log_path()}"
        ) from exc
    captured = str(getattr(result, "stdout", "") or "").rstrip()
    if captured:
        _append_bridge_log(captured)


def _cached_canonical_design_for_gpu(output_dir: Path, request: dict[str, Any]) -> dict | None:
    """準備の前半が同じプロセスで解読した C_livery の結果（メモリーに覚えたもの）。

    中身の SHA（記録の名前）が今の C_livery と一致するときだけ返す。無い・合わない・研究用の確認では None
    （GPU の入力を作るときに解読し直す）。準備を別のプロセスで動かしたときも None になる。
    """
    if request.get("private_context_mask_visual_check") is True:
        return None
    try:
        summary = read_summary(output_dir / "vehicle-preview-summary.json")
        entry = Path(str(summary.get("canonical_design_cache_root") or ""))
        if not entry.name:
            return None
        from fh6_gpu_livery_parity_input import resolve_readable_c_livery
        import vehicle_preview
        source = resolve_readable_c_livery(Path(_requested_c_livery_path(request)))
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if entry.name != source_sha256:
            return None
        design, _ = vehicle_preview._read_cached_canonical_design(
            entry.parents[2], source_sha256, int(summary.get("c_livery_embedded_id") or 0))
        return design
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


def _load_output_into_server(server: LiveryInspectorServer, output_dir: Path, request: dict[str, Any] | None = None) -> tuple[Path, Path, Path, Path]:
    summary = read_summary(output_dir / "vehicle-preview-summary.json")
    package_path = Path(summary["private_preview"]).resolve()
    mesh_path = Path(summary["mesh"]).resolve()
    render_root = Path(summary["render_root"]).resolve()
    render_contract_path = Path(summary["render_contract"]).resolve()
    render_contract = json.loads(render_contract_path.read_text(encoding="utf-8"))
    # 目録のファイルは、車ごとに同じ解析の結果（内装・トリムの色）を車のキャッシュのファイルへの参照で持つ
    # （shared_contract_results）。サーバーへ渡す前に元の値に戻す（画面に渡す目録は今までと同じ）。
    from tools.livery import shared_contract_results
    resolved_contract = shared_contract_results.resolve(render_contract, summary.get("vehicle_cache_root"))
    if resolved_contract is None:
        raise ValueError("描画の目録が指す車の解析の結果が見つからないか、中身が違います。準備をやり直してください")
    render_contract = resolved_contract
    # 原本タイヤ・側面文字・署名付きタイヤのGLBは、ペイントの内容に依存しない（キーは元のGLBと
    # 原本の署名）。ペイントごとのフォルダーに複製せず、車種をまたいで共有のキャッシュに置く。
    # 要約に車両キャッシュの場所が無い以前の準備結果は、従来どおりペイントのフォルダー。
    from tools.livery.vehicle_analysis_cache import mark_used
    vehicle_cache_value = str(summary.get("vehicle_cache_root") or "").strip()
    tire_cache_root = (Path(vehicle_cache_value).resolve() / "wheel-tire") if vehicle_cache_value else output_dir
    # 最後に使った日時（将来、キャッシュの容量に上限を設けたときに古いものから消すため）。
    mark_used(mesh_path)
    # 研究用にGameDB純正タイヤとは異なる原本Tireを選ぶときは、
    # 原本モデル名/ZIPを既存の解決器で検証し、同じViewer材質処理へ流す。
    # この変更はメモリ上の一回限り。Stock製品入口と原本GameDBは変更しない。
    research_tire = _string(request.get("pr76_tire_model")) if request is not None else ""
    if research_tire:
        import re as _re
        from tools.livery.source_tire_local_runtime import resolve_installed_tire_archive
        if (not _re.fullmatch(r"[A-Za-z0-9_-]{1,96}", research_tire)
                or _viewer_wheel_source(request) != "source-verified"
                or request.get("database") is None):
            raise ValueError("PR76タイヤ研究は直接CLIの原本・GameDB・source-verifiedに限定")
        original_assembly = render_contract.get("assembly")
        if (not isinstance(original_assembly, dict)
                or original_assembly.get("format") != "lo4fh6_local_vehicle_assembly_v2"):
            raise ValueError("PR76タイヤ研究にGameDB実車両寸法がありません")
        resolved_tire = resolve_installed_tire_archive(Path(request["game_folder"]), research_tire)
        stock_name = original_assembly.get("tire_model_name")
        render_contract = {
            **render_contract,
            "assembly": {**original_assembly, "tire_model_name": research_tire},
            "pr76_tire_corpus_research": {
                "requested_original_tire_model_name": research_tire,
                "source_archive_name": resolved_tire.name,
                "game_db_stock_tire_name": stock_name,
                "is_game_db_stock_pair": research_tire.casefold() == str(stock_name).casefold(),
                "tire_shoehorn_compatibility_proven": False,
                "source_family_compatibility_unapproved": True,
                "windows_and_xbox_appearance_unapproved": True,
            },
        }
    # 原本タイヤを選択したときだけ、ゲームフォルダーからModelBinを読み取り専用で
    # 取得し、署名付きの12タイヤを独立プレビューキャッシュへ非破壊結合する。
    # 旧GLB・GameSave・ゲーム原本・通常のproxy/stock経路には触れない。
    if request is not None and _viewer_wheel_source(request) == "source-verified":
        from tools.livery.source_tire_local_runtime import (
            LocalTireSourceError, prepared_local_tire_mesh, local_tire_cache_paths,
            resolve_installed_tire_archive as _tire_archive, _validated_assembly as _tire_assembly,
        )
        from tools.livery.source_tire_original_normal import lookup_standard_tire
        from tools.livery.vehicle_assets import resolve_fh6_cars_dir as _cars_dir
        # 正常な原本材質を出せない状態で「原本車輪」の成功を装わない。
        # 原本アーカイブはゲームインストール内のみ。配布物への同梱・書換なし。
        if not summary.get("vehicle_archive"):
            raise ValueError("原本4輪＋タイヤの車両原本ZIPパスが準備結果にありません")
        try:
            # 元の車体＋原本タイヤの GLB の保存先（入力の鍵の名前）。標準Tireが同じ入力で作ってあれば、
            # この GLB は作らず照合もしない（標準Tireの索引は名前の鍵だけで引ける）。
            local_tire_glb, local_tire_proof, _, _ = local_tire_cache_paths(
                mesh_path, render_contract, Path(request["game_folder"]), tire_cache_root,
                vehicle_archive=Path(summary["vehicle_archive"]),
            )
            local_tire_zip = _tire_archive(Path(request["game_folder"]), _tire_assembly(render_contract)[0])
            local_tire_cars_dir = _cars_dir(Path(request["game_folder"]))
            standard_tire_ready = lookup_standard_tire(
                local_tire_glb, local_tire_zip, local_tire_cars_dir, tire_cache_root) is not None
            if standard_tire_ready:
                mesh_path = local_tire_glb
            else:
                mesh_path = prepared_local_tire_mesh(
                    mesh_path, render_contract, Path(request["game_folder"]), tire_cache_root,
                    vehicle_archive=Path(summary["vehicle_archive"]),
                )
                mark_used(mesh_path)
        except LocalTireSourceError as exc:
            raise ValueError("原本4輪＋タイヤのローカル準備に失敗: " + str(exc)) from exc
    # 確認済みの原本タイヤ側面文字は、原本ModelBin/MatI/Shaderの証拠一致時に標準接続。
    # 非該当タイヤへFEOW文字を強制しない。対応原本が欠ける場合は明示エラー。
    # 以前の手動FEOW環境変数を製品に必要としない。
    if request is not None and _viewer_wheel_source(request) == "source-verified":
        from tools.livery.source_tire_local_runtime import resolve_installed_tire_archive, _validated_assembly
        from tools.livery.source_tire_feow_auto import (
            auto_feow_sidewall_glb, installed_original_textures_archive,
            source_tire_feow_family, source_tire_text_report,
        )
        from tools.livery.source_tire_mati_sidewall_preview import (
            SourceTextError, SourceTextTextureMissingError,
        )
        from tools.livery.vehicle_assets import resolve_fh6_cars_dir
        name, _, _ = _validated_assembly(render_contract)
        model_zip = resolve_installed_tire_archive(Path(request['game_folder']), name)
        cars_dir = resolve_fh6_cars_dir(Path(request['game_folder']))
        # 側面文字の出典は原本MatI（TextSwitch=1と文字Texture 2枚）から作る。
        # 以前のstreet_FE_OW固定証拠JSONと同じ項目・値になることをテストで照合済み。
        try:
            report_path = source_tire_text_report(model_zip, cars_dir)
        except SourceTextTextureMissingError as exc:
            # 原本アセット側の参照不整合（GYWhite等）。推測で別Textureを当てず、
            # 文字なしの原本Normal表示で続行し、理由を診断へ明記する。
            report_path = None
            render_contract['lo4fh6_source_tire_text_unavailable'] = str(exc)
            _append_bridge_log('原本Tireの側面文字は未接続（文字なしで表示）: ' + str(exc))
        except SourceTextError as exc:
            raise ValueError('原本Tireの側面文字の出典照合に失敗。表示を省略せず停止: ' + str(exc)) from exc
        shader_library = cars_dir/'_library'
        shader_family = shader_library/'shaders'/'car_tires_pg.zip'
        shader_legacy = shader_library/'shaders.zip'
        shader_source = shader_family if shader_family.is_file() else shader_legacy
        # FEOWの原本署名が一致した場合、4輪全LOD0の原本Normalを先に付ける。
        # FEOW合成はsidewall4材質のみ上書きするため、他のTire材質8件を
        # 旧診断ラバーへ戻さず保持できる。車種ID・実行時の研究スイッチは使わない。
        signed_feow = source_tire_feow_family(model_zip, report_path)
        if signed_feow:
            from tools.livery.source_tire_original_normal import (
                OriginalTireNormalError, cached_original_tire_normal_glb,
            )
            try:
                mesh_path = cached_original_tire_normal_glb(
                    mesh_path, model_zip, cars_dir, tire_cache_root)
                mark_used(mesh_path)
            except (OriginalTireNormalError, ValueError, KeyError) as exc:
                raise ValueError(
                    '原本FEOWのTreadを原本Normal材質へ接続できません。'
                    '診断用ラバーへ後退せず停止: ' + str(exc)) from exc
            render_contract['lo4fh6_source_tire_standard_required'] = (
                'original-feow-sidewall-plus-normal-source-signed-v1')
        # 古い研究環境の2画像ZIPは通常製品では不要。選択抽出は実原本Textures.zipから行う。
        mesh_path, feow_applied = auto_feow_sidewall_glb(
            mesh_path,model_zip,report_path,cars_dir,tire_cache_root,shader_source)
        mark_used(mesh_path)
        if signed_feow and not feow_applied:
            raise ValueError('側面文字の原本署名適合後に4輪描画が生成されませんでした')
        if feow_applied:
            _append_bridge_log(
                '原本MatI署名一致：側面文字4輪（TextSwitch=1）＋原本Normal材質（文字以外）を標準接続。'
                'Shader全式・Xbox外観は未承認')
        # Windows受入済みRoad側面刻印を、原本MatI/Shader署名で車種共通の標準入口に接続する。
        # FEOWの正常4輪表示が最優先。推測Tire種別/Car IDでは振り分けない。
        # 未適合では原本通常経路を保持し、署名適合後の欠損は明示エラーで止める。
        if not feow_applied:
            from tools.livery.source_tire_composite import (
                SourceTireCompositeError, original_tire_compound_signed_eligible,
            )
            from tools.livery.source_tire_original_normal import (
                OriginalTireNormalError, cached_original_tire_normal_glb,
                original_tire_normal_signed_eligible,
            )
            try:
                signed_compound = original_tire_compound_signed_eligible(model_zip, shader_library)
                if signed_compound:
                    # PR73の受入表示とPR76のLOD0・Normal・元色・署名を同一GLBに統合する。
                    # 元Extra/BlurのAO/粗さ経路はFH6 Shader完全一致未承認と区別。
                    mesh_path = cached_original_tire_normal_glb(
                        mesh_path, model_zip, cars_dir, tire_cache_root,
                     )
                    mark_used(mesh_path)
                    render_contract['lo4fh6_source_tire_standard_required'] = 'original-normal-compound-source-signed-v1'
                    _append_bridge_log(
                        '原本Tire統合: 受入済みExtra/Blur＋原本Normal/UV0/'
                        'BaseTyreColour/LOD0。FH6複合PBR式の完全一致は未承認')
                elif original_tire_normal_signed_eligible(model_zip, cars_dir):
                    # Street等のTextSwitch未宣言タイプも原本Normalの署名条件を独立評価。
                    # 全Shaderの色/Blur/PBRを近似適用せず、原本UniqueNormのみ統合。
                    mesh_path = cached_original_tire_normal_glb(
                        mesh_path, model_zip, cars_dir, tire_cache_root,
                     )
                    mark_used(mesh_path)
                    # 署名済みNormal GLBが正常に返った後にだけViewerへ期待経路を伝える。
                    # この宣言があるのにGLTFLoaderでNormalを保持できなければ明示停止。
                    render_contract['lo4fh6_source_tire_standard_required'] = 'original-normal-source-signed-v1'
                    _append_bridge_log(
                        '原本Tire Normal: 原本MatI/ShaderBin・四輪LOD0材質・'
                        '元UV/Normal Swatch署名一致。標準入口へ接続（Xbox・Shader全式未承認）')
                else:
                    # source-verifiedの原本Tireを旧中立ラバーで描画成功としない。
                    raise ValueError(
                        '原本Tireの通常LOD0材質署名が非対応です。'
                        '原本MatI/Shaderを検証してから変換します')
            except (SourceTireCompositeError, OriginalTireNormalError, KeyError, ValueError) as exc:
                raise ValueError('原本Tire材質の署名済み接続に失敗。表示を省略せず停止: ' + str(exc)) from exc
    # 標準Tireができたら、元の車体＋原本タイヤの GLB は残さない（車ごとに約 20 MB。同じ入力なら次からは
    # 標準Tireの索引で足りる）。標準Tireが消えたとき（容量の上限・版の更新）は、元の GLB から作り直す。
    if (request is not None and _viewer_wheel_source(request) == "source-verified"
            and not standard_tire_ready and local_tire_glb.is_file()
            and lookup_standard_tire(local_tire_glb, local_tire_zip, local_tire_cars_dir, tire_cache_root) is not None):
        local_tire_glb.unlink(missing_ok=True)
        local_tire_proof.unlink(missing_ok=True)
    if request is not None and _viewer_wheel_source(request) == "source-verified":
        # タイヤの段で覚えた GLB（解析の結果・SHA・書いたばかりのファイル）を捨てる。Viewer は窓を閉じても残るので
        # 持ち続けない（2026-11-21、案 ⑤ の A）。
        from tools.livery.source_tire_glb_bridge import release_tire_stage_memos
        release_tire_stage_memos()
    # 標準準備の原本Carbin→YRVL照合は、最終Tire/FEOW結合GLBでも再監査。
    # 計数と原本SHAは診断のみで利用し、未承認Shader/色を描画へ注入しない。
    # 実車両の原本Meshごとの未対応は隠さず診断に残す。
    # 旧キャッシュ/環境が残っても、過去の研究URLへ処理を切り替えない。
    render_contract.pop("source_mesh_finish_trial", None)
    render_contract.pop("source_mesh_finish_trial_unavailable", None)
    source_finish = render_contract.get("source_paint_binding_diagnostics")
    if isinstance(source_finish, dict):
        # 同じ GLB のファイル（場所・大きさ・更新日時が同じ）の SHA と目次の事実は、同じプロセスで覚えて使い回す
        # （同じ車のペイントを続けて開くたびに約 35 MB を読み直していた。2026-11-20）
        from tools.livery.independent_chassis.source_paint_mesh_descriptor_stage import glb_sha256_for_file
        final_sha = glb_sha256_for_file(mesh_path)
        if final_sha != source_finish.get("source_glb_sha256"):
            from tools.livery.independent_chassis.source_paint_mesh_descriptor_stage import (
                OriginalPaintMeshBindingError, apply_finish_display_colors,
                audit_source_mesh_finish_bindings_for_file, resolve_manufacturer_carpaint_groups,
            )
            try:
                yrvl_path = Path(summary["yrvl_material_diagnostics"]).resolve()
                yrvl_source = json.loads(yrvl_path.read_text(encoding="utf-8"))
                # 実GLBに新規色/仕上げを捏造しない。Workerが同一元GameDB
                # 出典で既に採用した署名CarPaint groupだけを再検証する。
                catalog: dict[int, dict] = {}
                # メーカー指定色で補った集まり・描画用の色は、元の車体の監査で求めた値をそのまま使う。
                palette_rows: dict[int, dict] = {}
                display_rows: dict[int, str] = {}
                for row in source_finish.get("carpaint_groups", {}).values():
                    if "manufacturer_selector_raw" in row:
                        palette_rows[int(row["manufacturer_selector_raw"])] = {
                            "rgba_hex": row.get("primary_color_rgba_hex"),
                            "material_name": row.get("finish_material_name")}
                        continue
                    if isinstance(row.get("display_rgba_hex"), str):
                        display_rows[row.get("finish_code_raw")] = row["display_rgba_hex"]
                    code = row.get("finish_code_raw")
                    inputs = row.get("required_input_colors")
                    name = row.get("finish_material_name")
                    if (type(code) is not int or type(inputs) is not int
                            or not isinstance(name, str) or not name
                            or code in catalog and catalog[code] != {
                                "id": code, "material_name": name, "num_input_colors": inputs}):
                        raise OriginalPaintMeshBindingError("元CarPaint仕上げ署名の整合性がありません")
                    catalog[code] = {"id": code, "material_name": name, "num_input_colors": inputs}
                refreshed = audit_source_mesh_finish_bindings_for_file(
                    mesh_path, yrvl_source, catalog,
                )
                refreshed = resolve_manufacturer_carpaint_groups(refreshed, palette_rows.get)
                refreshed = apply_finish_display_colors(refreshed, display_rows.get)
                if refreshed["carpaint_groups"] != source_finish.get("carpaint_groups"):
                    raise OriginalPaintMeshBindingError("結合後GLBのCarPaint材質ルートが元車体と異なります")
                refreshed["original_chassis_glb_sha256"] = source_finish["source_glb_sha256"]
                refreshed["combined_source_mesh_audited"] = True
                render_contract["source_paint_binding_diagnostics"] = refreshed
                if refreshed.get("carpaint_binding_complete_for_research") is not True:
                    render_contract["source_paint_binding_diagnostics_unavailable"] = (
                        "最終GLBのcarPaintに原本C_livery未対応材質IDあり（"
                        + str(refreshed.get("counts", {}).get("carpaint_mesh_unresolved_for_research", 0))
                        + "件）。根拠確定まで描画へ自動適用しない"
                    )
            except (OriginalPaintMeshBindingError, KeyError, OSError, ValueError) as exc:
                # 標準表示の原本Wheel/FEOW/Paintを止めず、診断不成立は明示。
                render_contract.pop("source_paint_binding_diagnostics", None)
                render_contract["source_paint_binding_diagnostics_unavailable"] = str(exc)
    validate_livery_inspection_artifact(package_path)
    server.set_package(package_path)
    server.set_capture_caption(_capture_caption(request))
    server.set_viewer_preferences(_viewer_preferences())
    server.set_local_mesh(mesh_path)
    overlay_plan = summary.get("body_kit_overlay_plan") if isinstance(summary.get("body_kit_overlay_plan"), dict) else {}
    overlay_value = _string(summary.get("body_kit_overlay_mesh"))
    overlay_path = Path(overlay_value).resolve() if overlay_value else None
    overlay_descriptor = dict(overlay_plan) if overlay_plan else {}
    if overlay_descriptor:
        overlay_descriptor["body_kit_part_id"] = summary.get("body_kit_part_id")
        overlay_descriptor["part_selection"] = summary.get("part_selection") or {}
        overlay_descriptor["player_save_state_resolved"] = bool(summary.get("installed_save_state_resolved"))
    server.set_local_body_kit_overlay(overlay_path if overlay_path and overlay_path.is_file() else None, overlay_descriptor)
    raw_variants = summary.get("body_kit_variants")
    variants = [dict(item) for item in raw_variants] if isinstance(raw_variants, list) else []
    server.set_local_body_kit_variants(variants, convert=_deferred_body_kit_converter(summary))
    _register_part_options(server, summary)
    # 飾りの画像を BC7 のまま渡すときに読む原本（ゲームのフォルダーと車の ZIP。2026-11-20、案 ①）
    try:
        from tools.livery.vehicle_assets import normalize_fh6_game_folder as _content_root_of
        server.set_body_trim_source(_content_root_of(Path(_string(summary.get("game_folder")))),
                                    _string(summary.get("vehicle_archive")) or None)
    except Exception as exc:  # noqa: BLE001  原本が読めなくても、BC7 のまま渡す画像が出ないだけ（平均色で描く）
        _append_bridge_log("飾りの画像の原本の場所が分からない: " + f"{type(exc).__name__}: {exc}")
        server.set_body_trim_source(None, None)
    server.set_local_render_contract(render_root, render_contract)
    _remove_stale_render_roots(output_dir, render_root)
    _start_vehicle_cache_limit(output_dir, summary)
    return package_path, mesh_path, render_root, render_contract_path


_RENDER_ROOT_NAME = re.compile(r"car\d+-\d+-\d+-r\d+-q\d+")


def _remove_stale_render_roots(output_dir: Path, render_root: Path) -> None:
    """同じペイントの古い描画用フォルダー（output/cache/renders の、今のもの以外）を消す。

    描画用フォルダーの名前にはパッケージの大きさが入り、作り直すたびに変わる（パッケージに作った日時が入る）。
    同じペイントを開き直すたびに古いフォルダー（下地の細部の PNG などで 20〜100 KB）が残っていた（2026-11-20）。
    サーバーが今のフォルダーに切り替えた後なので、古いフォルダーはもう渡さない。名前の形が違うもの・リンクは
    触らない。消せないもの（使用中など）は飛ばす。
    """
    renders = output_dir.resolve() / "cache" / "renders"
    try:
        current = render_root.resolve()
        if current.parent != renders:
            return
        for entry in renders.iterdir():
            if (entry.name == current.name or not _RENDER_ROOT_NAME.fullmatch(entry.name)
                    or entry.is_symlink() or not entry.is_dir() or os.path.isjunction(entry)):
                continue
            shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        return


# キャッシュの見回し（古い版の残骸・容量の上限）は、Viewer のプロセスごと・キャッシュの場所ごとに 1 回だけ、
# 最初の表示の準備のこの秒数の後に裏で行う（2026-11-21）。準備のたびに見回すと、キャッシュ全体（準備のフォルダーの
# JSON・全ファイルの大きさ・参照の照らし合わせ）を毎回読み、同じプロセスの準備・ページへの受け渡しと取り合っていた。
CACHE_MAINTENANCE_DELAY_SECONDS = 15.0
_CACHE_MAINTENANCE_LOCK = threading.Lock()
# 見回しを始めたキャッシュの場所 → 最新の表示中の準備のフォルダー（見回すときに、その時点で表示中の物を守る）
_CACHE_MAINTENANCE_LATEST: dict[str, Path] = {}


def _start_vehicle_cache_limit(output_dir: Path, summary: dict, *,
                               delay_seconds: float = CACHE_MAINTENANCE_DELAY_SECONDS) -> None:
    """共有の設定に準備のキャッシュの容量の上限（vehicle_cache_limit_gb）があれば、上限を超えた分を裏で消す。

    設定が無いときは、古い版の残骸（名前の版が今のコードと違うもの）だけを消す（2026-11-20）。古い版の残骸は
    版が変わったとき（新しいプロセス）にしか増えないので、見回しはプロセスごと・キャッシュの場所ごとに 1 回だけ、
    最初の表示の準備の delay_seconds 秒後に行う（2026-11-21。最初の表示と取り合わない）。2 回目からの準備は、
    表示中の準備のフォルダーを覚え直すだけ。表示中の車のものは消さない（tools.livery.vehicle_cache_limit）。
    失敗しても表示は止めず、消した・消せなかった結果をブリッジのログに残す。
    """
    try:
        from tools.livery.vehicle_cache_limit import (VEHICLE_CACHE_DIR, enforce_cache_limit,
                                                      limit_bytes_from_settings, remove_obsolete)
        cache_value = _string(summary.get("vehicle_cache_root"))
        if not cache_value:
            return
        cache_root = Path(cache_value).resolve()
        if cache_root.name != VEHICLE_CACHE_DIR:
            return
        output_root = cache_root.parent
        prepared = Path(output_dir).resolve()
        key = os.path.normcase(str(output_root))
        with _CACHE_MAINTENANCE_LOCK:
            started = key in _CACHE_MAINTENANCE_LATEST
            _CACHE_MAINTENANCE_LATEST[key] = prepared
        if started:
            return
        limit = limit_bytes_from_settings(load_shared_settings(_settings_path()))
    except Exception as exc:  # noqa: BLE001  容量の上限は補助。表示は止めない。
        _append_bridge_log("キャッシュの容量の上限の準備に失敗: " + f"{type(exc).__name__}: {exc}")
        return

    def run() -> None:
        try:
            with _CACHE_MAINTENANCE_LOCK:
                current = _CACHE_MAINTENANCE_LATEST.get(key, prepared)
            if limit is None:
                result = remove_obsolete(output_root, current_prepared_dir=current)
                if result["deleted_units"] or result["failed_units"]:
                    _append_bridge_log(
                        f"キャッシュの古い版の残骸：消した {result['deleted_units']} 単位 "
                        f"{result['deleted_bytes'] / 1024 ** 3:.2f} GB、消せなかった {result['failed_units']} 単位")
                return
            result = enforce_cache_limit(output_root, limit, current_prepared_dir=current)
            if result["deleted_units"] or result["failed_units"]:
                _append_bridge_log(
                    f"キャッシュの容量の上限 {limit / 1024 ** 3:.1f} GB：使用 {result['before_bytes'] / 1024 ** 3:.2f} GB、"
                    f"消した {result['deleted_units']} 単位 {result['deleted_bytes'] / 1024 ** 3:.2f} GB、"
                    f"消せなかった {result['failed_units']} 単位")
        except Exception as exc:  # noqa: BLE001
            _append_bridge_log("キャッシュの容量の上限の処理に失敗: " + f"{type(exc).__name__}: {exc}")

    timer = threading.Timer(max(0.0, float(delay_seconds)), run)
    timer.name = "lo4fh6-vehicle-cache-limit"
    timer.daemon = True
    timer.start()


def _deferred_body_kit_converter(summary: dict) -> Callable[[Path, list[str]], None] | None:
    """準備で変換を後回しにしたボディキットの部品を、Viewer で選ばれたときに変換する関数（2026-11-21）。

    車の原本の情報（車の一覧）は、初めて変換するときに読む（ページを開く時間を延ばさない）。保存先は、この車の
    キャッシュの meshes の中で、名前に今の原本の ZIP の SHA と更新日時が入っている物だけを受け付ける
    （準備の後にゲームが更新されていれば、変換せずに理由を返す）。
    """
    cache_value = _string(summary.get("vehicle_cache_root"))
    archive_sha = _string(summary.get("vehicle_archive_sha256")).lower()
    game_folder = _string(summary.get("game_folder"))
    archive_value = _string(summary.get("vehicle_archive"))
    car_id = summary.get("car_id")
    if not cache_value or len(archive_sha) != 64 or not game_folder or not archive_value or car_id is None:
        return None
    vehicle_cache_root = Path(cache_value).resolve()
    mesh_dir = vehicle_cache_root / "meshes"

    def convert(planned: Path, added_entries: list[str]) -> None:
        from tools.livery.body_kit_overlay_mesh import ensure_body_kit_overlay
        from tools.livery.vehicle_assets import load_or_build_vehicle_asset_index
        target = Path(planned).resolve()
        if target.parent != mesh_dir or archive_sha not in target.name or target.suffix.casefold() != ".glb":
            raise ValueError("The deferred body-kit mesh is outside this vehicle cache.")
        index = load_or_build_vehicle_asset_index(game_folder, vehicle_cache_root / "vehicle-index.json")
        asset = index.get(int(car_id))
        if asset is None or Path(asset.archive_path).resolve() != Path(archive_value).resolve():
            raise ValueError("The vehicle archive for the deferred body-kit mesh is no longer available.")
        if not target.name.startswith(f"{asset.model_code}-{asset.archive_mtime_ns}-"):
            raise ValueError("The vehicle archive changed after the preview was prepared.")
        started = time.perf_counter()
        _validation, cache_hit = ensure_body_kit_overlay(asset, target, added_entries)
        _append_bridge_log(f"ボディキットの部品を{'キャッシュから用意' if cache_hit else '変換'}しました: "
                           f"{target.name}（{time.perf_counter() - started:.2f} 秒）")

    return convert


def _register_part_options(server: LiveryInspectorServer, summary: dict) -> None:
    """部品の選択肢（バンパー・ボンネット・サイドスカート・リアウイング）をViewerのサーバーへ登録する。

    選択肢の重ね合わせのGLBは、Viewerで初めて選ばれたときにサーバーが変換して車種ごとに保存する。
    一覧は車体のGLBに記録した原本Carbinの選択肢から、今の車体（body_kit_part_id）のものに限る。
    製造元の名前は、GameDB とゲームの文字列の表から加える（読めなければ名前なしで登録する）。
    登録できなくても車体の表示は止めず、理由をログに残す。
    """
    try:
        from tools.livery.part_option_overlay import part_option_catalog_for_file, with_manufacturer_names
        from tools.livery.vehicle_assets import load_or_build_vehicle_asset_index, normalize_fh6_game_folder
        cache_value = _string(summary.get("vehicle_cache_root"))
        archive_sha = _string(summary.get("vehicle_archive_sha256"))
        game_folder = _string(summary.get("game_folder"))
        if not cache_value or len(archive_sha) != 64 or not game_folder:
            return
        body_id = summary.get("body_kit_part_id")
        catalog = part_option_catalog_for_file(Path(summary["mesh"]).resolve(),
                                               car_body_id=body_id if type(body_id) is int else None)
        if not catalog:
            return
        vehicle_cache_root = Path(cache_value).resolve()
        index = load_or_build_vehicle_asset_index(game_folder, vehicle_cache_root / "vehicle-index.json")
        asset = index.get(int(summary.get("car_id")))
        if asset is None or Path(asset.archive_path).resolve() != Path(_string(summary.get("vehicle_archive"))).resolve():
            return
        content_root = normalize_fh6_game_folder(game_folder)
        database = _string(summary.get("game_database"))
        if database:
            try:
                catalog = with_manufacturer_names(catalog, database=database, content_root=content_root)
            except Exception as exc:  # noqa: BLE001  名前は表示の補助。選択肢は名前なしで使える。
                _append_bridge_log("部品の製造元の名前は使えません: " + f"{type(exc).__name__}: {exc}")
        server.set_local_part_options(asset=asset, archive_sha256=archive_sha, vehicle_cache_root=vehicle_cache_root,
                                      content_root=content_root, catalog=catalog)
    except Exception as exc:  # noqa: BLE001  部品の選択肢は追加の機能。車体の表示は止めない。
        _append_bridge_log("部品の選択肢は使えません: " + f"{type(exc).__name__}: {exc}")


def _configure_server(
    output_dir: Path,
    request: dict[str, Any],
    vinyl_resource_root: Path | None = None,
    *,
    server: LiveryInspectorServer | None = None,
) -> tuple[LiveryInspectorServer, str]:
    """表示用のサーバーに出力を読み込み、表示の URL を返す。

    server を渡すと、動いているそのサーバー（同じ窓・同じ URL）に次のペイントの出力を読み込み直す
    （窓の使い回しで、ページを読み直さずに同じ車の次のペイントへ差し替えるため。2026-11-19）。
    """
    reuse_server = server is not None
    if not reuse_server:
        # 標準GUI・Organizer URI・Browserを同一依存環境にする。
        # PR研究Stageに同梱済みかどうかへ依存せず、署名済Threeを通常入口で保証。
        from tools.livery.local_three_dependency import ThreeDependencyError, ensure as ensure_three_vendor
        try:
            ensure_three_vendor(Path(__file__).resolve().parents[2])
        except ThreeDependencyError as exc:
            raise ValueError('Three.js r185の標準依存準備エラー: ' + str(exc)) from exc
        server = LiveryInspectorServer(VIEWER_ROOT)
        # localhostトークン、原本パス、データ内容はログに保存しない。
        # Python HTTP APIとWebView2初期化のどちらで止まったか共通ログで確認。
        server.request_diagnostic = lambda stage: _append_bridge_log("viewer localhost: " + stage)
    # 後半のタイヤ・ホイールの組み立ては、大きな原本の ZIP（Textures.zip など）を何度も開いて目録を読んでいた
    # （キャッシュの無い車で約 1 秒）。前半（vehicle_preview）と同じく、この間は同じ ZIP を 1 回だけ開いて使い回す。
    from tools.livery.material_runtime import shared_archive_reads
    with shared_archive_reads():
        package_path, mesh_path, render_root, render_contract_path = _load_output_into_server(server, output_dir, request)
    selection = _gpu_livery_runtime_selection()
    # r364：製品GPU Runtimeは常駐のVinyl全1400種Cacheを消費しない。
    # 利用者のVinyls.zipからC_liveryで参照する図形だけを復号し、Geometry Pack生成後に一時データを破棄する。
    # vinyl_resource_root引数は呼出元互換のためにだけ残す。
    _ = vinyl_resource_root
    if GPU_LIVERY_PRODUCTION_ADAPTER_AVAILABLE:
        try:
            render_contract = json.loads(render_contract_path.read_text(encoding="utf-8"))
            content_root = resolve_game_content_root(request["game_folder"])
            vinyl_zip_path = content_root / "media" / "livery" / "Vinyls.zip"
            runtime = build_gpu_livery_production_runtime(
                _requested_c_livery_path(request),
                vinyl_zip_path=vinyl_zip_path,
                decals_zip_path=content_root / "media" / "livery" / "Decals.zip",
                gamedb_path=request.get("database"),
                render_contract=render_contract,
                canonical_design=_cached_canonical_design_for_gpu(output_dir, request),
            )
            if request.get("private_context_mask_visual_check") is True:
                _append_bridge_log("旧GroupMask研究CLIは同じ製品標準GPU入口を使用（機能切替なし）")
            if runtime.get("raster_decal_pack") is not None:
                # Raster Logoがあるときだけ原本署名済みRGBAパックを追加。
                # 研究用入口ではなく通常GPU描画の標準契約。
                server.set_gpu_livery_runtime(
                    runtime["manifest"], runtime["vector_stream"], runtime["geometry_pack"],
                    runtime["raster_decal_pack"],
                )
            else:
                server.set_gpu_livery_runtime(
                    runtime["manifest"], runtime["vector_stream"], runtime["geometry_pack"]
                )
            selection = {
                **selection,
                "runtime_manifest": {
                    "format": runtime["manifest"].get("format"),
                    "source_context_mask_policy": runtime["manifest"].get("source_context_mask_policy"),
                    "source_context_mask_xbox_approved": False,
                    "stream": runtime["manifest"].get("stream"),
                    "geometry": runtime["manifest"].get("geometry"),
                    "adapter": runtime["manifest"].get("adapter"),
                    "preparation_profile_seconds": runtime["manifest"].get("preparation_profile_seconds"),
                    "runtime_memory_footprint": runtime["manifest"].get("runtime_memory_footprint"),
                },
            }
            if selection.get("selected") == "gpu":
                selection.update({
                    "reason": "gpu_production_adapter_ready",
                    "fallback_used": False,
                })
        except Exception as exc:
            _append_bridge_log(f"GPU-only livery runtime preparation ERROR: {exc}")
            raise ValueError("WebGL2ペイント入力の準備に失敗しました。CPU描画はありません: " + str(exc)) from exc
    else:
        raise ValueError("WebGL2ペイントアダプターが利用できません。CPU描画はありません")
    if _string(request.get("gpu_shadow_policy")) == "gpu-only" and (
        selection.get("selected") != "gpu" or not selection.get("runtime_manifest")
    ):
        raise ValueError("GPU専用ペイントに必要なWebGL2 runtimeが準備できません: " + str(selection.get("reason") or "unavailable"))
    _write_gpu_livery_runtime_selection(output_dir, selection)
    summary = read_summary(output_dir / "vehicle-preview-summary.json")
    url = server.url if reuse_server else server.start()
    render_quality = _render_quality_for_request(request)
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}render-quality={render_quality}"
    wheel_source = _viewer_wheel_source(request)
    if wheel_source:
        url = f"{url}&wheel-source={wheel_source}"
        if wheel_source == "source-verified":
            # 原本四輪・タイヤUV4を同時に検証。欠損は明示エラーで拒否する。
            url += "&wheel-fitment=source-bound-research"
    if request.get("gamedb_missing"):
        # GameDB が無い：画面に「車輪は簡易表示・ゲームのロゴのステッカーは省く」旨を出す
        url += "&gamedb=missing"
    # Windows受入時のみ、保存済JPEGのSHAと原本Wheel描画フレームを同じ記録へ接続。
    # 通常のGUI/Organizerと旧正常描画は一切変更しない。
    if os.environ.get('LO4FH6_RELEASE_CAPTURE_AUDIT', '').strip() == '1':
        url += '&release-scene-capture-audit=1'
        if os.environ.get('LO4FH6_RELEASE_CAPTURE_REQUIRE_GLASS', '').strip() == '1':
            url += '&release-scene-require-glass=1'
    if _string(request.get("shader_validation")) in {"deferred-experimental", "overlap-experimental"}:
        url = f"{url}&shader-validation={_string(request.get('shader_validation'))}"
    if request.get("atlas_capacity_probe") is True:
        url = f"{url}&atlas-capacity-probe=png-lossless"
    # 確認済みの原本材質と中立色補正は通常Viewerで常時適用。
    # 古いユーザー設定・親PowerShell・URLの研究用ON/OFFに依存しない。
    # FEOWも原本対応タイヤの材質署名による自動接続。

    # r207：ConverterはFH6の選択可能部品をGLB内で保全し、lo4_part_option_idsで識別する。
    # r206では変換Entryは正しくてもViewer側の選択がStockへ戻り、比較結果が同一になった。
    # 選択済みManifestのFamily→PartIdを共通MapでViewerへ渡す。
    # これは手動研究状態であり、GameSaveの証拠ではない。
    raw_part_selection = summary.get("part_selection")
    part_selection = {
        str(family): int(part_id)
        for family, part_id in (raw_part_selection.items() if isinstance(raw_part_selection, dict) else [])
        if str(family).strip() and not isinstance(part_id, bool)
    }
    if part_selection:
        encoded = quote(json.dumps(part_selection, ensure_ascii=False, separators=(",", ":")), safe="")
        url = f"{url}&part-selection={encoded}"
    (output_dir / "viewer-url.txt").write_text(url + "\n", encoding="utf-8")
    (output_dir / "organizer-preview-bridge-summary.json").write_text(
        json.dumps(
            {
                "format": "lo4fh6_organizer_preview_bridge_summary_v2",
                "request": request_to_serializable(request),
                "output": str(output_dir.resolve()),
                "viewer_url": url,
                "package": str(package_path),
                "mesh": str(mesh_path),
                "render_contract": str(render_contract_path),
                "window_mode": "standalone",
                "gpu_livery_runtime_selection": _gpu_livery_runtime_selection(),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return server, url


def _loading_html(request: dict[str, Any]) -> str:
    title = html.escape(_string(request.get("title")) or _string(request.get("vehicle_name")) or "3D Preview")
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Livery Organizer for FH6 - 3D Preview</title>
<style>
html,body{{height:100%;margin:0;background:#0b0e12;color:#eef3f8;font-family:"Segoe UI",sans-serif}}
main{{height:100%;display:grid;place-items:center}}section{{width:min(620px,86vw);text-align:center}}
.spinner{{width:44px;height:44px;margin:0 auto 24px;border:4px solid #34404c;border-top-color:#e8eef4;border-radius:50%;animation:s 1s linear infinite}}
@keyframes s{{to{{transform:rotate(360deg)}}}}h1{{font-size:22px;margin:0 0 10px}}p{{color:#aeb9c4;line-height:1.65}}
#status{{color:#fff}}.small{{font-size:13px}}
</style></head><body><main><section><div class="spinner"></div><h1>{title}</h1>
<p id="status">3Dプレビューを準備しています...</p>
<p class="small">初回は車両データとペイント表示用キャッシュの作成に時間がかかることがあります。</p>
</section></main></body></html>'''


def _error_html(message: str) -> str:
    text = html.escape(message)
    log_path = html.escape(str(_bridge_log_path()))
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
html,body{{height:100%;margin:0;background:#120d0d;color:#f7eded;font-family:"Segoe UI",sans-serif}}
main{{height:100%;display:grid;place-items:center}}section{{width:min(760px,88vw)}}h1{{font-size:22px}}pre{{white-space:pre-wrap;background:#211515;padding:16px;border-radius:8px}}
p{{color:#d2bcbc}}
</style></head><body><main><section><h1>3Dプレビューを開始できませんでした</h1><pre>{text}</pre>
<p>診断ログ: {log_path}</p></section></main></body></html>'''


def _set_window_status(window: Any, message: str) -> None:
    try:
        payload = json.dumps(str(message), ensure_ascii=False)
        window.evaluate_js(f"document.getElementById('status').textContent = {payload};")
    except Exception:
        pass


def _gamedb_assembly_evidence(output_dir: Path) -> dict[str, Any] | None:
    """
    準備済みViewer契約がローカルFH6 GameDBのAssembly原本に基づくことを確認する。
    """

    contract_path = output_dir / "local-render-contract.json"
    if not contract_path.is_file():
        return None
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    truth = dict(contract.get("assembly_truth") or {})
    if truth.get("source") != "local-fh6-gamedb":
        return None
    variants = dict(contract.get("assembly_variants") or {})
    ids = sorted((int(value) for value in variants if str(value).isdigit()))
    selected = dict(contract.get("assembly") or {})
    selected_id = selected.get("car_body_id")
    internal = dict(truth.get("wheelstyle_morph_internal") or {})
    morph_report = dict(internal.get("morph_report") or {})
    filtered_meshes = morph_report.get("wheel_render_pass_filtered_meshes")
    face_filtered_meshes = morph_report.get("wheel_face_occluder_filtered_meshes")
    placement_mode = _string(morph_report.get("wheel_placement")).casefold() or "gamedb"
    morph_assignment_changed = morph_report.get("wheel_morph_identity_assignment_changed") is True
    placement_applied = morph_report.get("wheel_gamedb_placement_applied")
    placement_wheels = morph_report.get("wheel_gamedb_placement_wheels")
    placement_meshes = morph_report.get("wheel_gamedb_placement_meshes")
    placement_max_distance = morph_report.get("wheel_gamedb_placement_max_distance_m")
    placement_reason = _string(morph_report.get("wheel_gamedb_placement_reason"))
    placement_guard_fallback = morph_report.get("wheel_gamedb_placement_guard_fallback") is True
    placement_guard_threshold = morph_report.get("wheel_gamedb_placement_guard_threshold_m")
    placement_assignment_changed = morph_report.get("wheel_gamedb_placement_identity_assignment_changed") is True
    return {
        "database": str(truth.get("database") or ""),
        "car_body_ids": ids,
        "selected_car_body_id": int(selected_id) if isinstance(selected_id, int) else None,
        "wheelstyle_morph_applied": bool(truth.get("wheelstyle_morph_applied")),
        "wheelstyle_morph_source": _string(truth.get("wheelstyle_morph_source")),
        "wheelstyle_morph_car_body_id": (
            int(truth["wheelstyle_morph_car_body_id"])
            if isinstance(truth.get("wheelstyle_morph_car_body_id"), int) else None
        ),
        "wheel_render_pass_filtered_meshes": (
            int(filtered_meshes)
            if isinstance(filtered_meshes, int) and not isinstance(filtered_meshes, bool)
            else None
        ),
        "wheel_face_occluder_filtered_meshes": (
            int(face_filtered_meshes)
            if isinstance(face_filtered_meshes, int) and not isinstance(face_filtered_meshes, bool)
            else None
        ),
        "wheel_placement": placement_mode,
        "wheel_morph_identity_assignment_changed": morph_assignment_changed,
        "wheel_gamedb_placement_applied": placement_applied is True,
        "wheel_gamedb_placement_wheels": (
            int(placement_wheels)
            if isinstance(placement_wheels, int) and not isinstance(placement_wheels, bool)
            else None
        ),
        "wheel_gamedb_placement_meshes": (
            int(placement_meshes)
            if isinstance(placement_meshes, int) and not isinstance(placement_meshes, bool)
            else None
        ),
        "wheel_gamedb_placement_max_distance_m": (
            float(placement_max_distance)
            if isinstance(placement_max_distance, (int, float)) and not isinstance(placement_max_distance, bool)
            else None
        ),
        "wheel_gamedb_placement_reason": placement_reason,
        "wheel_gamedb_placement_guard_fallback": placement_guard_fallback,
        "wheel_gamedb_placement_guard_threshold_m": (
            float(placement_guard_threshold)
            if isinstance(placement_guard_threshold, (int, float)) and not isinstance(placement_guard_threshold, bool)
            else None
        ),
        "wheel_gamedb_placement_identity_assignment_changed": placement_assignment_changed,
    }


def _format_gamedb_assembly_evidence(evidence: dict[str, Any]) -> str:
    ids = ", ".join(str(value) for value in evidence.get("car_body_ids") or []) or "(none)"
    selected = evidence.get("selected_car_body_id")
    selected_text = str(selected) if isinstance(selected, int) else "(fallback)"
    morph = "yes" if evidence.get("wheelstyle_morph_applied") else "no"
    source = _string(evidence.get("wheelstyle_morph_source"))
    morph_body = evidence.get("wheelstyle_morph_car_body_id")
    suffix = ""
    if morph == "yes":
        body_text = str(morph_body) if isinstance(morph_body, int) else "?"
        suffix = f" / morph source {source or 'unknown'} / morph Body {body_text}"
        filtered_meshes = evidence.get("wheel_render_pass_filtered_meshes")
        if isinstance(filtered_meshes, int) and not isinstance(filtered_meshes, bool):
            suffix += f" / transparent static-pass hidden {filtered_meshes} meshes"
        face_filtered_meshes = evidence.get("wheel_face_occluder_filtered_meshes")
        if isinstance(face_filtered_meshes, int) and not isinstance(face_filtered_meshes, bool):
            suffix += f" / dense face hidden {face_filtered_meshes} meshes"
        if evidence.get("wheel_morph_identity_assignment_changed"):
            suffix += " / morph wheel identity reassigned"
        if evidence.get("wheel_gamedb_placement_applied"):
            placement_wheels = evidence.get("wheel_gamedb_placement_wheels")
            placement_meshes = evidence.get("wheel_gamedb_placement_meshes")
            placement_max = evidence.get("wheel_gamedb_placement_max_distance_m")
            if isinstance(placement_wheels, int) and isinstance(placement_meshes, int):
                suffix += f" / GameDB placement {placement_wheels} wheels / {placement_meshes} meshes"
            if isinstance(placement_max, (int, float)) and not isinstance(placement_max, bool):
                suffix += f" / max shift {float(placement_max):.3f} m"
        elif evidence.get("wheel_gamedb_placement_guard_fallback"):
            placement_max = evidence.get("wheel_gamedb_placement_max_distance_m")
            threshold = evidence.get("wheel_gamedb_placement_guard_threshold_m")
            suffix += " / GameDB placement guarded -> carbin"
            if isinstance(placement_max, (int, float)) and not isinstance(placement_max, bool):
                suffix += f" / max shift {float(placement_max):.3f} m"
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
                suffix += f" > {float(threshold):.3f} m"
        elif _string(evidence.get("wheel_placement")).casefold() == "carbin":
            suffix += " / carbin placement preserved"
    return f"GameDB assembly active: CarBodyID {ids} / selected {selected_text} / WheelStyle morph {morph}{suffix}"


def _prepare_for_viewer(
    request: dict[str, Any],
    output_dir: Path,
    vinyl_cache_root: Path,
    *,
    rebuild: bool,
    status: Callable[[str], None] | None = None,
    hide_subprocess_window: bool = False,
) -> Path | None:
    def update(message: str) -> None:
        print(message)
        _append_bridge_log(message)
        if status is not None:
            status(message)

    if request.get("wheel_morph_reference_helper") not in (None, ""):
        raise FullLiveryPackageError(
            "旧外部Wheel Morph EXEヘルパーは通常GUI・Organizerの準備経路では使用できません。"
            "既存の独自WheelStyle Morphを使用してください。"
        )

    print(f"request: source={request['source']} car_id={request['car_id']} quality={request['quality']}")
    print(f"cache:   {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    vehicle_cache_root = (output_dir.parent / "_fh6-vehicle-cache").resolve()
    # 第一者v13は旧参照製品生成GLBの自動移動・再利用を禁止する。
    # 元のr485/段階③キャッシュは削除せず、独自Converter用に別キーで生成する。
    if _migrate_r150_base_paint_color(output_dir):
        update("車体ベース色キャッシュを現在の判定へ移行しました...")
    quality = _string(request.get("quality"))
    expected_database = Path(request["database"]).resolve() if request.get("database") not in (None, "") else None
    expected_wheel_morph_reference_helper = (
        Path(request["wheel_morph_reference_helper"]).resolve()
        if request.get("wheel_morph_reference_helper") not in (None, "") else None
    )

    # r364：準備済み出力はViewer起動に必要な情報を保持している。
    # 古い全Vinyl Cacheに触れる前に出力を再利用し、必要形状だけを後からVinyls.zipから取得する。
    reusable_in_process = not rebuild and _prepared_in_this_process(output_dir, request)
    # 前のプロセスで準備した出力は、残した近道の値が今のままのときだけ使い回す（2026-11-21）
    reusable_without_full_vinyl_cache = reusable_in_process or (
        not rebuild
        and _prepared_on_disk(output_dir, request)
        and cached_preview_ready(
            output_dir,
            None,
            quality,
            expected_database,
            expected_wheel_morph_reference_helper,
            _string(request.get("gpu_shadow_policy")) or "gpu-only",
        )
    )
    if reusable_without_full_vinyl_cache:
        (output_dir / "organizer-preview-request.normalized.json").write_text(
            json.dumps(request_to_serializable(request), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        update("キャッシュ済み3Dプレビューを読み込んでいます...")
        print("cache hit: reusing prepared preview output")
        print("vinyl:   GPU runtime selects required shapes directly from installed Vinyls.zip")
        prepare_state = {
            "format": "lo4fh6_bridge_prepare_state_v1",
            "prepared_output_reused": True,
            "prepared_output_reuse_scope": "same-process" if reusable_in_process else "prepared-output",
            "full_vinyl_cache_required": False,
            "full_vinyl_cache_reason": "not-required-for-warm-gpu-runtime",
            "gpu_geometry_source": "selected-vinyls-zip",
        }
        (output_dir / "viewer-prepare-state.json").write_text(
            json.dumps(prepare_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not reusable_in_process:
            # 前のプロセスの出力を使い回したら、このプロセスの近道にも覚える（次の差し替えは確かめが軽い）
            _remember_prepared_in_process(output_dir, request)
        if expected_database is not None:
            evidence = _gamedb_assembly_evidence(output_dir)
            if evidence is None:
                update("WARNING: GameDB was requested, but the prepared Viewer contract has no local-FH6 GameDB assembly evidence.")
            else:
                update(_format_gamedb_assembly_evidence(evidence))
        return None

    # 新規準備ではCPUペイントを生成しない。GPUの図形パック構築時には
    # C_livery参照済み図形のみをVinyls.zipから一時的に取得する。
    # 全件旧キャッシュは元データ不在の旧キャッシュ移行に限って参照する。
    cache_ready = False
    requested_c_livery = _requested_c_livery_path(request)
    if not requested_c_livery.is_file():
        relocated_source = _relocated_source_candidate(request)
        if relocated_source is not None:
            previous_source = Path(request["source"])
            request["source"] = relocated_source
            requested_c_livery = _requested_c_livery_path(request)
            update(
                "保存データ内で同じペイントを再検出したため、現在の保存先を使用します..."
            )
            print(f"source relocated: {previous_source} -> {relocated_source}")

    (output_dir / "organizer-preview-request.normalized.json").write_text(
        json.dumps(request_to_serializable(request), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    vinyl_resource_root: Path | None = None
    migrated = False
    if not requested_c_livery.is_file():
        # 原本なしの厳密なCache移行では選択図形集合を求められない。
        # 旧Vinyl全体Cacheはこの互換処理だけで使用する。
        update("FH6のバイナル形状キャッシュを確認しています...（旧キャッシュ移行用）")
        vinyl_resource_root = ensure_local_vinyl_geometry(Path(request["game_folder"]), vinyl_cache_root)
        print(f"vinyl:   {vinyl_resource_root}")
        if not rebuild and expected_database is None:
            cache_ready = _try_migrate_sourceless_legacy_cache(
                request, output_dir, vinyl_resource_root, quality
            )
            if cache_ready:
                migrated = True
                update("元ペイントが見つからないため、既存3Dプレビューキャッシュを現在形式へ移行しました...")

    generated = False
    if rebuild or not cache_ready:
        requested_c_livery = _requested_c_livery_path(request)
        if not requested_c_livery.is_file():
            raise ValueError(
                "C_livery not found, and no exact relocated source or reusable preview cache was found: "
                f"{requested_c_livery.parent}"
            )
        update("車両とペイントの3Dプレビューを準備しています...")
        if vinyl_resource_root is None:
            print("vinyl:   GPU runtime selects required shapes from installed Vinyls.zip")
        # 作り直しの途中で止まっても、古い近道の値で使い回さない（終わったら新しい値を残す）
        (output_dir / PREPARED_GUARD_FILE).unlink(missing_ok=True)
        prepare_preview(request, output_dir, vinyl_resource_root, hide_window=hide_subprocess_window)
        generated = True
        _remember_prepared_in_process(output_dir, request)
    else:
        update("キャッシュ済み3Dプレビューを読み込んでいます...")
        print("cache hit: reusing prepared preview output")

    full_cache_required = bool(vinyl_resource_root is not None)
    prepare_state = {
        "format": "lo4fh6_bridge_prepare_state_v1",
        "prepared_output_reused": bool(not generated),
        "prepared_output_generated": generated,
        "legacy_cache_migrated": migrated,
        "full_vinyl_cache_required": full_cache_required,
        "full_vinyl_cache_reason": (
            "sourceless-legacy-migration-r373"
            if full_cache_required
            else "not-required-selected-gpu-shapes"
        ),
        "gpu_geometry_source": "selected-vinyls-zip",
    }
    (output_dir / "viewer-prepare-state.json").write_text(
        json.dumps(prepare_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if expected_database is not None:
        evidence = _gamedb_assembly_evidence(output_dir)
        if evidence is None:
            update("WARNING: GameDB was requested, but the prepared Viewer contract has no local-FH6 GameDB assembly evidence.")
        else:
            update(_format_gamedb_assembly_evidence(evidence))
    return vinyl_resource_root


def _gpu_livery_runtime_selection() -> dict[str, Any]:
    capability = load_capability_cache(default_capability_cache_path())
    selection = evaluate_runtime_selection(
        requested="gpu",
        capability=capability,
        production_adapter_available=GPU_LIVERY_PRODUCTION_ADAPTER_AVAILABLE,
    )
    # rM016以降CPU Paintモードは存在しない。
    # 初回にブラウザーのGPU能力CacheがなくてもGPU Streamを準備し、
    # 実WebGL2 Contextで判定する。CPUへの無告知切替やGPU準備省略は行わない。
    if GPU_LIVERY_PRODUCTION_ADAPTER_AVAILABLE:
        selection.update(selected="gpu", requested="gpu", fallback_used=False,
                         reason="gpu_only_browser_capability_pending")
    return selection


def _write_gpu_livery_runtime_selection(output_dir: Path, selection: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gpu-livery-runtime-selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _bounded_int_list(value: Any, limit: int) -> list[int]:
    if not isinstance(value, list):
        return []
    return [int(item or 0) for item in value[:limit]]


def _sanitize_gpu_mismatch_owner_diagnostic(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    records: list[dict[str, Any]] = []
    raw_records = value.get("top_gpu_owner_records")
    if isinstance(raw_records, list):
        for raw in raw_records[:20]:
            if not isinstance(raw, dict):
                continue
            transform = raw.get("transform") if isinstance(raw.get("transform"), dict) else {}
            records.append({
                "record_index": max(0, int(raw.get("record_index") or 0)),
                "mismatch_pixels": max(0, int(raw.get("mismatch_pixels") or 0)),
                "mismatch_share": float(raw.get("mismatch_share") or 0.0),
                "mismatch_bbox": _bounded_int_list(raw.get("mismatch_bbox"), 4),
                "section_index": int(raw.get("section_index") or 0),
                "mode": str(raw.get("mode") or "")[:16],
                "shape_word": max(0, int(raw.get("shape_word") or 0)),
                "shape_word_hex": str(raw.get("shape_word_hex") or "")[:16],
                "color_rgba": _bounded_int_list(raw.get("color_rgba"), 4),
                "transform": {
                    "x": float(transform.get("x") or 0.0),
                    "y": float(transform.get("y") or 0.0),
                    "sx": float(transform.get("sx") or 0.0),
                    "sy": float(transform.get("sy") or 0.0),
                    "rotation": float(transform.get("rotation") or 0.0),
                    "memory_skew": float(transform.get("memory_skew") or 0.0),
                },
            })
    return {
        "semantics": str(value.get("semantics") or "")[:128],
        "rgb_large_mismatch_threshold": max(0, int(value.get("rgb_large_mismatch_threshold") or 0)),
        "large_mismatch_pixels": max(0, int(value.get("large_mismatch_pixels") or 0)),
        "owned_large_mismatch_pixels": max(0, int(value.get("owned_large_mismatch_pixels") or 0)),
        "unowned_large_mismatch_pixels": max(0, int(value.get("unowned_large_mismatch_pixels") or 0)),
        "paint_owned_large_mismatch_pixels": max(0, int(value.get("paint_owned_large_mismatch_pixels") or 0)),
        "mask_owned_large_mismatch_pixels": max(0, int(value.get("mask_owned_large_mismatch_pixels") or 0)),
        "top_gpu_owner_records": records,
    }


def _sanitize_gpu_adapter_report(payload: dict[str, Any]) -> dict[str, Any]:
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    sections = []
    for item in raw_sections[:16]:
        if not isinstance(item, dict):
            continue
        record = {
            "section": str(item.get("section") or "")[:64],
            "tile_width": int(item.get("tile_width") or 0),
            "tile_height": int(item.get("tile_height") or 0),
            "tile_pixels": int(item.get("tile_pixels") or 0),
            "accepted": bool(item.get("accepted")),
            "acceptance_mode": str(item.get("acceptance_mode") or "")[:64],
            "alpha_mismatch_pixels": int(item.get("alpha_mismatch_pixels") or 0),
            "alpha_binary_mismatch_pixels": int(item.get("alpha_binary_mismatch_pixels") or 0),
            "alpha_binary_mismatch_canvas_ratio": float(item.get("alpha_binary_mismatch_canvas_ratio") or 0.0),
            "binary_interior_gt2px": int(item.get("binary_interior_gt2px") or 0),
            "binary_boundary_2px_ratio": float(item.get("binary_boundary_2px_ratio") or 0.0),
            "alpha_intermediate_mismatch_pixels": int(item.get("alpha_intermediate_mismatch_pixels") or 0),
            "alpha_intermediate_mismatch_canvas_ratio": float(item.get("alpha_intermediate_mismatch_canvas_ratio") or 0.0),
            "alpha_candidate_higher_pixels": int(item.get("alpha_candidate_higher_pixels") or 0),
            "alpha_candidate_lower_pixels": int(item.get("alpha_candidate_lower_pixels") or 0),
            "alpha_intermediate_mean_abs": float(item.get("alpha_intermediate_mean_abs") or 0.0),
            "alpha_intermediate_max_abs": int(item.get("alpha_intermediate_max_abs") or 0),
            "alpha_intermediate_edge_exchange_2px_ratio": float(item.get("alpha_intermediate_edge_exchange_2px_ratio") or 0.0),
            "alpha_intermediate_interior_gt2px": int(item.get("alpha_intermediate_interior_gt2px") or 0),
            "alpha_intermediate_gradient_boundary_1px_ratio": float(item.get("alpha_intermediate_gradient_boundary_1px_ratio") or 0.0),
            "alpha_intermediate_gradient_boundary_2px_ratio": float(item.get("alpha_intermediate_gradient_boundary_2px_ratio") or 0.0),
            "alpha_intermediate_gradient_interior_gt1px": int(item.get("alpha_intermediate_gradient_interior_gt1px") or 0),
            "alpha_intermediate_gradient_interior_gt2px": int(item.get("alpha_intermediate_gradient_interior_gt2px") or 0),
            "rgb_mean_abs": float(item.get("rgb_mean_abs") or 0.0),
            "rgb_max_abs": int(item.get("rgb_max_abs") or 0),
            "rgb_large_mismatch_pixels": int(item.get("rgb_large_mismatch_pixels") or 0),
            "rgb_large_mismatch_visible_ratio": float(item.get("rgb_large_mismatch_visible_ratio") or 0.0),
        }
        # ローカルViewer Bridge由来でも入力は信用しない。
        # 不正な空間データを拒否し、文字列や上限16区画を超える値は保存しない。
        # 画素単位の情報は保持しない。
        spatial = item.get("glass_spatial_diagnostic")
        if isinstance(spatial, dict) and spatial.get("format") == "lo4fh6_glass_spatial_4x4_v1" and spatial.get("grid_size") == 4:
            raw_cells = spatial.get("cells")
            names = ("visible_pixels", "rgb_large_mismatch_pixels", "alpha_mismatch_pixels", "alpha_candidate_higher_pixels", "alpha_candidate_lower_pixels")
            max_pixels = record["tile_width"] * record["tile_height"]
            if (isinstance(raw_cells, list) and len(raw_cells) == 16 and 0 < max_pixels <= 8192 * 8192
                and all(isinstance(cell, dict) and all(type(cell.get(k)) is int and 0 <= cell[k] <= max_pixels for k in names) for cell in raw_cells)):
                record["glass_spatial_diagnostic"] = {
                    "format": "lo4fh6_glass_spatial_4x4_v1", "grid_size": 4,
                    "cells": [{k: cell[k] for k in names} for cell in raw_cells],
                }
        # r438：上限内の数値Alpha Cohort計数だけを受け付け、自由記述は許可しない。
        cohort = item.get("glass_alpha_cohort_diagnostic")
        if isinstance(cohort, dict) and cohort.get("format") == "lo4fh6_glass_alpha_cohorts_v1":
            names = ("transparent", "partial", "opaque")
            transitions = tuple(f"{a}_to_{b}" for a in names for b in names)
            deltas = ("abs_1_2", "abs_3_8", "abs_9_plus")
            sizes = ("compared_pixels", "visible_pixels", "alpha_mismatch_pixels", "rgb_large_mismatch_pixels")
            bound = record["tile_width"] * record["tile_height"]
            tr, dl, rgb = (cohort.get(k) for k in ("alpha_transitions", "alpha_mismatch_by_abs_delta", "rgb_large_mismatch_by_cpu_alpha"))
            if (0 < bound <= 8192 * 8192 and all(isinstance(v, dict) for v in (tr, dl, rgb))
                and all(type(cohort.get(k)) is int and 0 <= cohort[k] <= bound for k in sizes)
                and cohort["compared_pixels"] == bound
                and all(type(tr.get(k)) is int and 0 <= tr[k] <= bound for k in transitions)
                and all(type(dl.get(k)) is int and 0 <= dl[k] <= bound for k in deltas)
                and all(type(rgb.get(k)) is int and 0 <= rgb[k] <= bound for k in names)
                and sum(tr[k] for k in transitions) == bound
                and sum(dl[k] for k in deltas) == cohort["alpha_mismatch_pixels"]
                and sum(rgb[k] for k in names) == cohort["rgb_large_mismatch_pixels"]
                and cohort["alpha_mismatch_pixels"] == record["alpha_mismatch_pixels"]
                and cohort["rgb_large_mismatch_pixels"] == record["rgb_large_mismatch_pixels"]):
                record["glass_alpha_cohort_diagnostic"] = {
                    "format": "lo4fh6_glass_alpha_cohorts_v1",
                    **{k: cohort[k] for k in sizes},
                    "alpha_transitions": {k: tr[k] for k in transitions},
                    "alpha_mismatch_by_abs_delta": {k: dl[k] for k in deltas},
                    "rgb_large_mismatch_by_cpu_alpha": {k: rgb[k] for k in names},
                }
                # r440：許可リスト内の上限付き数値の同時件数だけ受け付ける。
                # 個人識別キーを除外し、欠落や矛盾した重複数は拒否する。
                overlap = cohort.get("rgb_alpha_overlap_diagnostic")
                if isinstance(overlap, dict) and overlap.get("format") == "lo4fh6_glass_rgb_alpha_overlap_v1":
                    keys = ("rgb_large_with_alpha_mismatch_pixels", "rgb_large_without_alpha_mismatch_pixels",
                            "alpha_mismatch_without_rgb_large_pixels")
                    by_tr = overlap.get("rgb_large_by_alpha_transition")
                    by_dl = overlap.get("rgb_large_with_alpha_mismatch_by_abs_delta")
                    if (isinstance(by_tr, dict) and isinstance(by_dl, dict)
                        and all(type(overlap.get(k)) is int and 0 <= overlap[k] <= bound for k in keys)
                        and all(type(by_tr.get(k)) is int and 0 <= by_tr[k] <= tr[k] for k in transitions)
                        and all(type(by_dl.get(k)) is int and 0 <= by_dl[k] <= dl[k] for k in deltas)
                        and sum(by_tr[k] for k in transitions) == cohort["rgb_large_mismatch_pixels"]
                        and all(sum(by_tr[f"{a}_to_{z}"] for z in names) == rgb[a] for a in names)
                        and overlap[keys[0]] + overlap[keys[1]] == cohort["rgb_large_mismatch_pixels"]
                        and overlap[keys[0]] + overlap[keys[2]] == cohort["alpha_mismatch_pixels"]
                        and sum(by_dl[k] for k in deltas) == overlap[keys[0]]):
                        record["glass_alpha_cohort_diagnostic"]["rgb_alpha_overlap_diagnostic"] = {
                            "format": "lo4fh6_glass_rgb_alpha_overlap_v1",
                            **{k: overlap[k] for k in keys},
                            "rgb_large_by_alpha_transition": {k: by_tr[k] for k in transitions},
                            "rgb_large_with_alpha_mismatch_by_abs_delta": {k: by_dl[k] for k in deltas},
                        }
                        # r442: strict whitelist of RGB-large premultiplied
                        # 診断専用。原本画素の内容は外部へ転送しない。
                        pm = overlap.get("rgb_premult_diagnostic")
                        pm_groups = ("partial_equal_alpha", "partial_changed_alpha",
                                     "opaque_equal_alpha", "other")
                        pm_bins = ("pm_abs_0_2", "pm_abs_3_8", "pm_abs_9_31",
                                   "pm_abs_32_63", "pm_abs_64_plus")
                        pm_data = pm.get("rgb_large_premult_by_alpha_condition") if isinstance(pm, dict) else None
                        if (isinstance(pm, dict) and pm.get("format") == "lo4fh6_glass_rgb_premult_diagnostic_v1"
                            and isinstance(pm_data, dict) and set(pm_data) == set(pm_groups)
                            and all(isinstance(pm_data.get(g), dict) and set(pm_data[g]) == set(pm_bins)
                                    and all(type(pm_data[g][b]) is int and 0 <= pm_data[g][b] <= bound for b in pm_bins)
                                    for g in pm_groups)):
                            pm_totals = {g: sum(pm_data[g][b] for b in pm_bins) for g in pm_groups}
                            stable_opaque = by_tr["opaque_to_opaque"]
                            stable_partial = overlap[keys[1]] - stable_opaque
                            if (stable_partial >= 0
                                and pm_totals["partial_equal_alpha"] == stable_partial
                                and pm_totals["partial_changed_alpha"] == by_tr["partial_to_partial"] - stable_partial
                                and pm_totals["opaque_equal_alpha"] == stable_opaque
                                and pm_totals["other"] == cohort["rgb_large_mismatch_pixels"]
                                  - by_tr["partial_to_partial"] - stable_opaque
                                and all(pm_data["opaque_equal_alpha"][b] == 0 for b in pm_bins[:-1])):
                                record["glass_alpha_cohort_diagnostic"]["rgb_alpha_overlap_diagnostic"]["rgb_premult_diagnostic"] = {
                                    "format": "lo4fh6_glass_rgb_premult_diagnostic_v1",
                                    "rgb_large_premult_by_alpha_condition": {
                                        g: {b: pm_data[g][b] for b in pm_bins} for g in pm_groups
                                    },
                                }
        source_coverage = item.get("source_coverage_diagnostic")
        if isinstance(source_coverage, dict):
            record["source_coverage_diagnostic"] = {
                "canonical_shape_count": int(source_coverage.get("canonical_shape_count") or 0),
                "valid_affine_shape_count": int(source_coverage.get("valid_affine_shape_count") or 0),
                "manifest_stream_record_count": int(source_coverage.get("manifest_stream_record_count") or 0),
                "dropped_before_stream_count": int(source_coverage.get("dropped_before_stream_count") or 0),
                "canonical_paint_shape_count": int(source_coverage.get("canonical_paint_shape_count") or 0),
                "canonical_mask_shape_count": int(source_coverage.get("canonical_mask_shape_count") or 0),
                "canonical_raster_shape_count": int(source_coverage.get("canonical_raster_shape_count") or 0),
                "canonical_opaque_color_shape_count": int(source_coverage.get("canonical_opaque_color_shape_count") or 0),
                "canonical_semitransparent_color_shape_count": int(source_coverage.get("canonical_semitransparent_color_shape_count") or 0),
                "canonical_transparent_color_shape_count": int(source_coverage.get("canonical_transparent_color_shape_count") or 0),
                "draw_plan_source_record_count": int(source_coverage.get("draw_plan_source_record_count") or 0),
                "draw_plan_vector_record_count": int(source_coverage.get("draw_plan_vector_record_count") or 0),
                "record_count_delta": int(source_coverage.get("record_count_delta") or 0),
                "placement_count": int(source_coverage.get("placement_count") or 0),
                "triangle_count": int(source_coverage.get("triangle_count") or 0),
                "raster_record_count": int(source_coverage.get("raster_record_count") or 0),
                "missing_geometry_count": int(source_coverage.get("missing_geometry_count") or 0),
                "paint_solid_placement_count": int(source_coverage.get("paint_solid_placement_count") or 0),
                "paint_vertex_alpha_placement_count": int(source_coverage.get("paint_vertex_alpha_placement_count") or 0),
                "mask_solid_placement_count": int(source_coverage.get("mask_solid_placement_count") or 0),
                "mask_vertex_alpha_placement_count": int(source_coverage.get("mask_vertex_alpha_placement_count") or 0),
                "fully_inside_viewport_placement_count": int(source_coverage.get("fully_inside_viewport_placement_count") or 0),
                "partially_clipped_viewport_placement_count": int(source_coverage.get("partially_clipped_viewport_placement_count") or 0),
                "fully_outside_viewport_placement_count": int(source_coverage.get("fully_outside_viewport_placement_count") or 0),
                "source_size": [int(value) for value in list(source_coverage.get("source_size") or [])[:2]],
                "tile_size": [int(value) for value in list(source_coverage.get("tile_size") or [])[:2]],
                "world_bounds": [float(value) for value in list(source_coverage.get("world_bounds") or [])[:4]],
            }
        diagnostic = item.get("side_orientation_diagnostic")
        if isinstance(diagnostic, dict):
            variants = diagnostic.get("variants") if isinstance(diagnostic.get("variants"), dict) else {}
            clean_variants = {}
            for name in ("identity", "flip-x", "flip-y", "rotate-180"):
                value = variants.get(name)
                if not isinstance(value, dict):
                    continue
                clean_variants[name] = {
                    "alpha_mismatch_pixels": int(value.get("alpha_mismatch_pixels") or 0),
                    "alpha_binary_mismatch_pixels": int(value.get("alpha_binary_mismatch_pixels") or 0),
                    "alpha_intermediate_mismatch_pixels": int(value.get("alpha_intermediate_mismatch_pixels") or 0),
                    "alpha_mismatch_mean_abs": float(value.get("alpha_mismatch_mean_abs") or 0.0),
                    "reference_only_visible_pixels": int(value.get("reference_only_visible_pixels") or 0),
                    "candidate_only_visible_pixels": int(value.get("candidate_only_visible_pixels") or 0),
                }
            record["side_orientation_diagnostic"] = {
                "reference_alpha_sum": int(diagnostic.get("reference_alpha_sum") or 0),
                "candidate_alpha_sum": int(diagnostic.get("candidate_alpha_sum") or 0),
                "alpha_sum_delta": int(diagnostic.get("alpha_sum_delta") or 0),
                "reference_visible_pixels": int(diagnostic.get("reference_visible_pixels") or 0),
                "candidate_visible_pixels": int(diagnostic.get("candidate_visible_pixels") or 0),
                "reference_opaque_pixels": int(diagnostic.get("reference_opaque_pixels") or 0),
                "candidate_opaque_pixels": int(diagnostic.get("candidate_opaque_pixels") or 0),
                "reference_intermediate_pixels": int(diagnostic.get("reference_intermediate_pixels") or 0),
                "candidate_intermediate_pixels": int(diagnostic.get("candidate_intermediate_pixels") or 0),
                "best_variant": str(diagnostic.get("best_variant") or "")[:32],
                "best_alpha_mismatch_pixels": int(diagnostic.get("best_alpha_mismatch_pixels") or 0),
                "variants": clean_variants,
            }
        owner = _sanitize_gpu_mismatch_owner_diagnostic(item.get("gpu_mismatch_owner_diagnostic"))
        if owner is not None:
            record["gpu_mismatch_owner_diagnostic"] = owner
        sections.append(record)
    rejected_sections = [
        str(value)[:64]
        for value in list(payload.get("rejected_sections") or [])[:16]
        if str(value).strip()
    ]
    return {
        "format": "lo4fh6_gpu_livery_production_adapter_report_v1",
        "used_gpu": bool(payload.get("used_gpu")),
        "reason": str(payload.get("reason") or "")[:128],
        "raw_rejected_diagnostic": bool(payload.get("raw_rejected_diagnostic")),
        "rejected_sections": rejected_sections,
        "gpu_section_count": max(0, int(payload.get("gpu_section_count") or 0)),
        "section_count": len(sections),
        "sections": sections,
        "privacy": "hardware/vendor/renderer names are intentionally not persisted",
    }



VIEWER_DISPLAY_TIMING_KEYS = frozenset({
    "manifest", "assets", "materials", "scene", "firstFrame", "firstPaintOpportunity",
    "assetLoadMs", "gpuAtlasBuildMs", "sceneBuildMs", "variantBuildMs",
    "gpuAtlasTileRenderMs", "gpuAtlasShadowCompareMs", "gpuAtlasComposeMs",
    "firstFrameRenderMs", "sceneToFirstFrameMs",
    "secondFrameRenderMs", "secondFrameNewPrograms",
    "gpuAtlasPngProbeRequested", "gpuAtlasPngProbeSucceeded", "gpuAtlasPngBytes",
    "gpuAtlasPngEncodeMs", "gpuAtlasPngWidth", "gpuAtlasPngHeight", "gpuAtlasRawRgbaBytes",
    "gpuAtlasPngProbeFailureCode",
    "gpuAtlasSparsePngSucceeded", "gpuAtlasSparsePngFailureCode",
    "gpuAtlasSparsePngBytes", "gpuAtlasSparsePngTotalTiles",
    "gpuAtlasSparsePngNonzeroTiles", "gpuAtlasSparsePngZeroTiles",
    "gpuAtlasSparsePngEncodeMs",
    "gpuAtlasReadbackSucceeded", "gpuAtlasReadbackFailureCode",
    "gpuAtlasReadbackDecodeMs", "gpuAtlasReadbackDrawMs", "gpuAtlasReadbackCompareMs",
    "gpuAtlasReadbackComparedComponents", "gpuAtlasReadbackMismatchedComponents",
    "gpuAtlasReadbackMaxAbsoluteError", "gpuAtlasReadbackPixelExact",
    "gpuAtlasSyntheticIoSucceeded", "gpuAtlasSyntheticIoFailureCode",
    "gpuAtlasSyntheticIoCleanupSucceeded", "gpuAtlasSyntheticIoBytes",
    "gpuAtlasSyntheticIoWriteMs", "gpuAtlasSyntheticIoReadMs", "gpuAtlasSyntheticIoVerifyMs",
    "secondFrameGlGetProgramInfoLogMs", "secondFrameGlGetProgramParameterMs", "secondFrameGlTextureMs",
    "firstFrameResizeMs", "firstFrameControlsMs", "firstFrameSceneRenderMs",
    "gpuAtlasPlanBuildMs", "gpuAtlasWebglRenderMs", "gpuAtlasReadbackResolveMs",
    "gpuAtlasReadPixelsMs", "gpuAtlasPixelConvertMs", "gpuAtlasCanvasResolveMs",
    "firstFrameAaTargetMs", "firstFrameAaCompositeMs", "firstFrameVariantSetupMs", "firstFrameThreeRenderMs",
    "firstFrameProgramsBefore", "firstFrameProgramsAfter", "firstFrameGlInstrumentedMethods",
    "firstFrameGlShaderCalls", "firstFrameGlShaderMs", "firstFrameGlBufferCalls", "firstFrameGlBufferMs",
    "firstFrameGlTextureCalls", "firstFrameGlTextureMs", "firstFrameGlDrawCalls", "firstFrameGlDrawMs",
    "firstFrameGlTargetCalls", "firstFrameGlTargetMs",
    "firstFrameShadowProfileAvailable", "firstFrameShadowPassCalls", "firstFrameShadowPassMs",
    "firstFrameShadowDrawCalls", "firstFrameShadowDrawCpuMs", "firstFrameNonShadowDrawCalls",
    "firstFrameGlProgramCalls", "firstFrameGlProgramMs", "firstFrameGlUniformCalls", "firstFrameGlUniformMs",
    "firstFrameGlStateCalls", "firstFrameGlStateMs",
    "firstFrameGlCreateProgramCalls", "firstFrameGlCreateProgramMs",
    "firstFrameGlGetProgramInfoLogCalls", "firstFrameGlGetProgramInfoLogMs",
    "firstFrameGlGetShaderInfoLogCalls", "firstFrameGlGetShaderInfoLogMs",
    "firstFrameGlGetUniformLocationCalls", "firstFrameGlGetUniformLocationMs",
    "firstFrameGlGetAttribLocationCalls", "firstFrameGlGetAttribLocationMs",
    "firstFrameGlGetActiveUniformCalls", "firstFrameGlGetActiveUniformMs",
    "firstFrameGlGetActiveAttribCalls", "firstFrameGlGetActiveAttribMs",
    "firstFrameGlValidateProgramCalls", "firstFrameGlValidateProgramMs",
    "firstFrameGlUseProgramCalls", "firstFrameGlUseProgramMs",
    "firstFrameGlCompileShaderCalls", "firstFrameGlCompileShaderMs",
    "firstFrameGlGetShaderParameterCalls", "firstFrameGlGetShaderParameterMs",
    "firstFrameGlLinkProgramCalls", "firstFrameGlLinkProgramMs",
    "firstFrameGlGetProgramParameterCalls", "firstFrameGlGetProgramParameterMs",
    "firstFrameShaderDeferredRequested", "firstFrameShaderDeferredActive",
    "firstFrameShaderDeferredProgramCount", "firstFrameShaderValidationMs", "firstFrameShaderFailedPrograms",
    "shaderOverlapRequested", "shaderOverlapActive", "shaderOverlapPrewarmStarted",
    "shaderOverlapPrewarmMs", "shaderOverlapPrewarmFailed", "shaderOverlapPaintSwapCount",
    "shaderOverlapAaTargetMatched", "shaderOverlapProgramsBefore", "shaderOverlapProgramsSubmitted",
    "shaderOverlapProgramsReady", "shaderOverlapFirstFrameNewPrograms",
    "shaderOverlapAaEnabled", "shaderOverlapRenderTargetConditionMatched",
    "shaderOverlapPrewarmKeyCount", "shaderOverlapFirstFrameNewKeyCount",
    "shaderOverlapFirstFrameNewObjects", "shaderOverlapClosestExactKeyCount",
    "shaderOverlapClosestOneFieldCount", "shaderOverlapClosestTwoFieldsCount",
    "shaderOverlapNoComparableKeyCount",
    "shaderOverlapOneFieldDominantTailOffset", "shaderOverlapOneFieldDominantTailCount",
    "shaderOverlapOneFieldDistinctTailOffsets", "shaderOverlapPrewarmTargeted",
    "shaderOverlapSameLo4CacheSuffixOneFieldCount", "shaderOverlapSameLo4CacheSuffixTail8Count",
    "shaderOverlapUntrustedOneFieldCount",
    "shaderOverlapOneFieldDominantPosition", "shaderOverlapOneFieldDominantCount",
    "shaderOverlapOneFieldDistinctPositions",
})


def _sanitize_viewer_display_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """
    上限付きのTiming情報だけを受け付け、機器情報や原本メタデータを含めない。
    """
    if not isinstance(payload, dict):
        raise ValueError("Viewer display profile must be an object.")
    raw = payload.get("timings_ms")
    if not isinstance(raw, dict):
        raise ValueError("Viewer display timings must be an object.")
    timings: dict[str, float] = {}
    for key in sorted(VIEWER_DISPLAY_TIMING_KEYS):
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Invalid Viewer display timing: {key}")
        amount = float(value)
        # PNGの容量はByte単位でありMillisecondではない。
        # その他のTimingは15分を上限として扱う。
        ceiling = 256 * 1024 * 1024 if key in {
            "gpuAtlasPngBytes", "gpuAtlasRawRgbaBytes", "gpuAtlasSparsePngBytes",
            "gpuAtlasReadbackComparedComponents", "gpuAtlasReadbackMismatchedComponents", "gpuAtlasSyntheticIoBytes",
        } else 900_000.0
        if not math.isfinite(amount) or amount < 0.0 or amount > ceiling:
            raise ValueError(f"Out-of-range Viewer display timing: {key}")
        timings[key] = round(amount, 3)
    def bounded_count(key: str) -> int:
        value = payload.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 32:
            raise ValueError(f"Invalid Viewer display count: {key}")
        return value
    return {
        "format": "lo4fh6_viewer_display_profile_v1",
        "timings_ms": timings,
        "initial_variant_count": bounded_count("initial_variant_count"),
        "loaded_variant_count": bounded_count("loaded_variant_count"),
        "measurement_scope": "viewer-script-to-first-present-opportunity; not physical scanout",
    }

class PreviewJsApi:
    def __init__(
        self,
        request: dict[str, Any],
        output_dir: Path,
        vinyl_cache_root: Path,
        state: dict[str, Any],
    ) -> None:
        self.request = request
        self.output_dir = output_dir
        self.vinyl_cache_root = vinyl_cache_root
        self.state = state
        self._lock = threading.Lock()
        self._viewer_last_stage = ""
        # ページの「Viewerを終了」で呼ぶ処理（窓を作った後に、窓を閉じる側が入れる。2026-11-22）
        self._quit_handler: Callable[[], None] | None = None
        # 保存ダイアログは利用者操作から開始し、保存完了を実バイトで照合する。
        from tools.livery.native_image_export import NativeImageExport
        self._image_exports = NativeImageExport()
        # 同じ車の次のペイントへの差し替えの、ページからの返事（report_paint_swap）。
        self._paint_swap_event = threading.Event()
        self._paint_swap_result: dict[str, Any] | None = None

    def save_auto_rotate_speed(self, value: Any) -> dict[str, Any]:
        """ページの「自動回転の速さ」で選んだ倍率を、Viewer の設定に保存する（次に開いたときも使う）。"""
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) not in AUTO_ROTATE_SPEED_CHOICES:
            return {"saved": False, "reason": "invalid-speed"}
        try:
            update_shared_settings({AUTO_ROTATE_SPEED_KEY: float(value)}, _settings_path())
        except OSError as exc:
            _append_bridge_log(f"auto-rotate speed: save failed: {type(exc).__name__}")
            return {"saved": False, "reason": "write-failed"}
        return {"saved": True, "auto_rotate_speed": float(value)}

    def report_paint_swap(self, payload: dict[str, Any]) -> dict[str, Any]:
        """ページが同じ車の次のペイントへの差し替えを受け付けたか（受け付けなければ Python がページを読み直す）。"""
        payload = payload if isinstance(payload, dict) else {}
        self._paint_swap_result = {"accepted": payload.get("accepted") is True,
                                   "reason": str(payload.get("reason") or "")[:120]}
        self._paint_swap_event.set()
        return {"ok": True}

    def quit_viewer(self) -> dict[str, Any]:
        """ページの「Viewerを終了」。窓を閉じたときのように隠して残さず、Viewer のプロセスを終える（2026-11-22）。

        ページへの返事を先に返してから閉じる（閉じるのは別の糸で少し待ってから）。
        """
        handler = self._quit_handler
        if handler is None:
            return {"ok": False, "reason": "unavailable"}
        _append_bridge_log("viewer quit requested from the page")

        def run() -> None:
            time.sleep(0.2)
            handler()

        threading.Thread(target=run, name="lo4fh6-viewer-quit", daemon=True).start()
        return {"ok": True}

    def _expect_paint_swap(self) -> None:
        self._paint_swap_result = None
        self._paint_swap_event.clear()

    def _wait_paint_swap(self, timeout: float) -> dict[str, Any] | None:
        return self._paint_swap_result if self._paint_swap_event.wait(timeout) else None

    def _switch_session(self, request: dict[str, Any], output_dir: Path, vinyl_cache_root: Path) -> None:
        """窓の使い回しで次のペイントに切り替えたとき、この窓の操作の相手を新しい件にする（state は同じ辞書）。"""
        with self._lock:
            self.request = request
            self.output_dir = output_dir
            self.vinyl_cache_root = vinyl_cache_root
            self._viewer_last_stage = ""

    def begin_image_save(self, filename: str, fmt: str) -> dict[str, Any]:
        """Windowsの保存先選択を開き、未保存ファイルの一時セッションを発行。"""
        return self._image_exports.begin(filename, fmt)

    def append_image_save(self, token: str, data_base64: str) -> dict[str, Any]:
        """GPU画素から作成したJPEG/PNG実バイトを分割書き込み。"""
        return self._image_exports.append(token, data_base64)

    def finish_image_save(self, token: str, expected_bytes: int) -> dict[str, Any]:
        """実ファイルのバイト数とSHAを検証し、選択済みパスへ確定。"""
        return self._image_exports.finish(token, expected_bytes)

    def abort_image_save(self, token: str) -> dict[str, Any]:
        """キャンセル・失敗時の未確定ファイルのみ削除。"""
        return self._image_exports.abort(token)

    def record_release_scene_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        """明示受入時の撮影フレームとWindowsで保存済みの実JPEG/PNG SHAを記録。"""
        if os.environ.get('LO4FH6_RELEASE_CAPTURE_AUDIT', '').strip() != '1':
            return {'ok': False, 'error': '受入診断は明示起動時のみ利用できます'}
        try:
            from tools.livery.release_capture_receipt import save_release_capture_receipt
            return save_release_capture_receipt(self.output_dir, payload)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            _append_bridge_log('release capture evidence ERROR: ' + str(exc))
            return {'ok': False, 'error': str(exc)[:240]}

    def report_viewer_stage(self, payload: dict[str, Any]) -> dict[str, Any]:
        """初期表示の進行を原本・車両非依存で監視。表示可否の認定には使わない。"""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid-stage-payload"}
        stage = str(payload.get("stage") or "").strip()
        allowed = {"script_loaded", "manifest", "manifest_http", "manifest_parsed",
                   "assets", "mesh_received", "mesh_parsed", "assets_ready",
                   "materials", "scene", "gpu_paint_start", "gpu_paint_ready",
                   "first_frame", "context_lost", "error"}
        if stage not in allowed:
            return {"ok": False, "error": "invalid-viewer-stage"}
        try:
            elapsed = max(0, min(600000, int(payload.get("elapsed_ms") or 0)))
        except (TypeError, ValueError):
            elapsed = 0
        with self._lock:
            if stage == self._viewer_last_stage and stage != "error":
                return {"ok": True}
            self._viewer_last_stage = stage
        # 出力はローカルのみ。ユーザーファイル/HTTP session tokenをログへ書かない。
        detail = str(payload.get("detail") or "")[:240]
        detail = re.sub(r"[A-Za-z]:[\\/][^\s]+", "[local-path]", detail)
        detail = re.sub(r"https?://[^\s]+", "[local-url]", detail)
        _append_bridge_log(
            f"browser viewer stage: {stage} elapsed_ms={elapsed}"
            + (f" detail={detail}" if detail else "")
        )
        return {"ok": True}

    def report_gpu_livery_capability(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"ok": False, "error": "GPU capability payload must be an object."}
        try:
            clean = write_capability_cache(payload, default_capability_cache_path())
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "gpu-livery-runtime-capability.json").write_text(
                json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            selection = evaluate_runtime_selection(
                requested="auto",
                capability=clean,
                production_adapter_available=GPU_LIVERY_PRODUCTION_ADAPTER_AVAILABLE,
            )
            previous = self.state.get("gpu_livery_runtime_selection")
            previous_report = previous.get("adapter_report") if isinstance(previous, dict) else None
            previous_runtime_manifest = previous.get("runtime_manifest") if isinstance(previous, dict) else None
            if isinstance(previous_runtime_manifest, dict):
                selection["runtime_manifest"] = previous_runtime_manifest
            if isinstance(previous_report, dict):
                selection["adapter_report"] = previous_report
                if previous_report.get("used_gpu") and selection.get("selected") == "gpu":
                    selection.update(reason="gpu_production_adapter_active", fallback_used=False)
                else:
                    selection.update(selected="unavailable",
                                     reason="gpu_production_adapter_failed",
                                     fallback_used=False)
            _write_gpu_livery_runtime_selection(self.output_dir, selection)
            self.state["gpu_livery_capability"] = clean
            self.state["gpu_livery_runtime_selection"] = selection
            probe = clean.get("probe") if isinstance(clean.get("probe"), dict) else {}
            _append_bridge_log(
                "gpu livery capability: "
                f"webgl2={clean.get('webgl2')} offscreen={clean.get('offscreen_framebuffer')} "
                f"rgba8={clean.get('rgba8_render_target')} selected={selection.get('selected')} "
                f"reason={selection.get('reason')} "
                f"probe={probe.get('reason', 'unavailable')} "
                f"framebuffer_status={probe.get('framebuffer_status')} "
                f"gl_error={probe.get('gl_error')} context_lost={probe.get('context_lost')}"
            )
            return {
                "ok": True,
                "selected": selection.get("selected"),
                "reason": selection.get("reason"),
            }
        except Exception as exc:
            _append_bridge_log(f"gpu livery capability ERROR: {exc}")
            return {"ok": False, "error": str(exc)}

    def report_gpu_livery_adapter_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"ok": False, "error": "GPU adapter report must be an object."}
        try:
            report = _sanitize_gpu_adapter_report(payload)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "gpu-livery-production-adapter.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            base = dict(self.state.get("gpu_livery_runtime_selection") or _gpu_livery_runtime_selection())
            selection = {
                **base,
                "selected": "gpu" if report["used_gpu"] and not report["rejected_sections"] else "unavailable",
                "reason": "gpu_production_adapter_active"
                          if report["used_gpu"] and not report["rejected_sections"]
                          else "gpu_production_adapter_failed",
                "fallback_used": False,
            }
            selection["adapter_report"] = report
            _write_gpu_livery_runtime_selection(self.output_dir, selection)
            self.state["gpu_livery_runtime_selection"] = selection
            _append_bridge_log(
                "gpu livery production adapter: "
                f"used_gpu={report.get('used_gpu')} reason={report.get('reason')} "
                f"sections={report.get('section_count')}"
            )
            return {"ok": True, "selected": selection.get("selected"), "reason": selection.get("reason")}
        except Exception as exc:
            _append_bridge_log(f"gpu livery production adapter ERROR: {exc}")
            return {"ok": False, "error": str(exc)}

    def report_viewer_display_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        個人識別メタデータを含めず、現在のSession内でPaint表示時間だけを記録する。
        """
        try:
            report = _sanitize_viewer_display_profile(payload)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "viewer-display-profile.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return {"ok": True}
        except (OSError, TypeError, ValueError) as exc:
            _append_bridge_log(f"viewer display profile ERROR: {type(exc).__name__}")
            return {"ok": False, "error": str(exc)[:100]}

    def set_quality_preset(self, render_quality: str) -> dict[str, Any]:
        preset = RENDER_QUALITY_TO_PRESET.get(_string(render_quality))
        if preset is None:
            return {"ok": False, "error": f"Unsupported quality preset: {render_quality}"}
        target_quality = QUALITY_PRESETS[preset]
        current_quality = _string(self.request.get("quality"))
        if target_quality == current_quality:
            _save_quality_preset(preset)
            return {"ok": True, "reload": False, "preset": preset, "quality": target_quality}
        with self._lock:
            quality_change_started = time.perf_counter()
            try:
                updated = dict(self.request)
                updated["quality"] = target_quality
                _append_bridge_log(f"quality preset change: {current_quality} -> {target_quality} ({preset})")
                # r364：旧原本なしCache移行で全Vinyl Cacheが必要かどうかは共有準備経路に委ねる。
                # 準備済み画質設定を使用するだけなら、Cacheなしでも維持できる。
                vinyl_root = _prepare_for_viewer(
                    updated,
                    self.output_dir,
                    self.vinyl_cache_root,
                    rebuild=False,
                    hide_subprocess_window=True,
                )
                self.state["vinyl_resource_root"] = vinyl_root
                server = self.state.get("server")
                if server is None:
                    raise ValueError("Viewer server is not running.")
                from tools.livery.material_runtime import shared_archive_reads
                with shared_archive_reads():
                    _load_output_into_server(server, self.output_dir, updated)
                self.request.update(updated)
                _save_quality_preset(preset)
                elapsed = time.perf_counter() - quality_change_started
                metrics = {
                    "format": "lo4fh6_quality_change_metrics_v1",
                    "record_id": _string(updated.get("record_id")),
                    "car_id": int(updated.get("car_id") or 0),
                    "from_quality": current_quality,
                    "to_quality": target_quality,
                    "preset": preset,
                    "seconds": round(elapsed, 4),
                }
                self.output_dir.mkdir(parents=True, exist_ok=True)
                (self.output_dir / "viewer-quality-change-metrics.json").write_text(
                    json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                _append_bridge_log(
                    f"quality preset ready: {current_quality} -> {target_quality} ({preset}) in {elapsed:.2f}s"
                )
                return {"ok": True, "reload": True, "preset": preset, "quality": target_quality}
            except Exception as exc:
                _append_bridge_log(f"quality preset ERROR: {exc}\n{traceback.format_exc()}")
                return {"ok": False, "error": str(exc), "preset": preset}


# ---- Viewer の窓の使い回し（2026-11-19）----
# 受付と依頼の受け渡しは viewer_window_reuse（重い部品を読み込む前にも使えるよう標準の部品だけで書いた）。
# ここでは、引数を読んだ後の受け渡しと、受け取った依頼を窓で開く 1 件にする処理を持つ。
import viewer_window_reuse as _window_reuse

VIEWER_HOST_FILE = _window_reuse.HOST_FILE
VIEWER_HOST_FORMAT = _window_reuse.HOST_FORMAT


def _viewer_host_path() -> Path:
    return _window_reuse.host_path()


def _viewer_code_identity() -> str:
    return _window_reuse.code_identity()


def _forwardable_standalone_launch(args: argparse.Namespace) -> bool:
    return (getattr(args, "window_mode", "standalone") == "standalone"
            and not getattr(args, "prepare_only", False)
            and not getattr(args, "no_open", False))


def _forwarded_cwd(args: argparse.Namespace) -> str:
    """依頼の相対パスを読む作業フォルダー。URI からの起動は窓用の Python を ROOT で起動し直すので ROOT。"""
    if (sys.platform == "win32" and _string(getattr(args, "uri", ""))
            and not getattr(args, "gui_child", False)):
        return str(ROOT)
    return os.getcwd()


def _forward_to_running_viewer(args: argparse.Namespace, argv: list[str]) -> bool:
    """開いている Viewer の窓へ依頼を渡せたら True（この起動はここで終わる）。渡せなければ False（従来どおり開く）。"""
    if not _forwardable_standalone_launch(args):
        return False
    return _window_reuse.forward(argv, _forwarded_cwd(args), log=_append_bridge_log)


def _ViewerHost(accept: Callable[[list[str]], None], closed: threading.Event,
                standby: Callable[[int], None] | None = None) -> "_window_reuse.ViewerHost":
    return _window_reuse.ViewerHost(accept, closed, log=_append_bridge_log, standby=standby)


def _start_viewer_standby(args: argparse.Namespace, parent_pid: int) -> int:
    """Organizer の起動で Viewer を温めておく（2026-11-21、FH6 に近づける案 ⑥ の続き）。

    共有の設定 viewer_standby_with_organizer がオフなら何もしない。開いている（隠している）Viewer があれば、
    窓を増やさずに Organizer の番号を伝えて終わる。無ければ、窓を隠したまま起動して待つ（最初の依頼は窓の使い回しと
    同じく受付へ渡り、窓を出して開く）。
    """
    if not _window_reuse.standby_enabled(load_shared_settings(_settings_path())):
        _append_bridge_log("viewer standby: off in the settings")
        return 0
    if _window_reuse.send_standby(parent_pid, log=_append_bridge_log):
        return 0
    if getattr(args, "window_mode", "standalone") == "browser":
        return 0
    if _spawn_uri_gui_child(args):
        return 0
    _append_bridge_log(f"viewer standby: starting hidden for Organizer pid={parent_pid}")
    return launch_standalone_preview(None, None, None, rebuild=False, standby_parent_pid=parent_pid)


def _warm_viewer_modules() -> None:
    """温めておく起動で、準備に使う重い部品を先に読み込む（最初の依頼の準備を短くする）。失敗しても続ける。"""
    started = time.perf_counter()
    for name in ("vehicle_preview", "fh6_gpu_livery_production", "tools.livery.portable_mesh_converter",
                 "tools.livery.inspector_server", "tools.livery.native_kernels"):
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001  読み込めない部品は、依頼のときに今までどおり読み込む
            _append_bridge_log(f"viewer standby: warm import skipped {name}: {type(exc).__name__}")
    _append_bridge_log(f"viewer standby: modules warmed in {time.perf_counter() - started:.2f}s")


def _wait_for_standby_job(jobs: "queue.Queue[dict[str, Any]]", keep_alive: Any) -> dict[str, Any] | None:
    """温めておく起動で、窓を作らずに最初の件を待つ（2026-11-21）。待つ前に重い部品を読み込む。

    受付へ渡った件のうち最後の 1 件を、最初の件として返す。Organizer が終わり、残す時間が過ぎたら None
    （窓を作らずに終える）。
    """
    _warm_viewer_modules()
    while True:
        if keep_alive.expired():
            _append_bridge_log("viewer standby: ended without a request")
            return None
        try:
            job = jobs.get(timeout=0.5)
        except queue.Empty:
            continue
        # 続けて届いた依頼は、最後の 1 件だけ開く
        while True:
            try:
                job = jobs.get_nowait()
            except queue.Empty:
                break
        keep_alive.shown_for_job()
        _append_bridge_log("viewer standby: opening the window for the first request")
        return {**job, "first": True, "from_standby": True}


def _capture_caption(request: dict[str, Any] | None) -> dict[str, str]:
    """保存する画像（現在視点・6方向）の下の帯に書く、ペイントの情報（Organizer から届いた表示の項目。2026-11-21）。"""
    request = request if isinstance(request, dict) else {}
    return {key: _string(request.get(key)) for key in ("title", "creator_name", "upload_date", "vehicle_name")}


def _standalone_title(request: dict[str, Any]) -> str:
    return _string(request.get("title")) or _string(request.get("vehicle_name")) or "3D Preview"


def _standalone_paths(args: argparse.Namespace, request: dict[str, Any]) -> tuple[Path, Path]:
    """依頼の品質・出力のフォルダー・図形のキャッシュを決め、記録に残す（main と窓の使い回しで共通）。"""
    if (args.uri or args.manifest_json) and args.quality is None and args.quality_preset is None:
        preset = _load_quality_preset()
        request["quality"] = QUALITY_PRESETS[preset]
    manifest_output_root = _string(request.get("manifest_output_root"))
    output_root = Path(manifest_output_root).resolve() if manifest_output_root and args.output_root == Path("organizer-preview-output") else args.output_root.resolve()
    output_dir = build_output_dir(output_root, request)
    vinyl_cache_root = (args.vinyl_cache_root.resolve() if args.vinyl_cache_root is not None else output_root / "_fh6-vinyl-geometry")
    _append_bridge_log(
        f"launch request: source={request['source']} car_id={request['car_id']} quality={request['quality']} mode={args.window_mode}"
    )
    wheel_source_note = _wheel_source_comparison_note(request)
    _append_bridge_log(wheel_source_note)
    print(wheel_source_note)
    if request.get("database") is not None:
        source_label = _string(request.get("database_resolution_source")) or "request"
        _append_bridge_log(f"GameDB resolved: source={source_label} path={request['database']}")
        if source_label != "explicit":
            print(f"GameDB resolved: {source_label}")
    return output_dir, vinyl_cache_root


def _forwarded_standalone_job(argv: list[str]) -> dict[str, Any]:
    """別の起動から渡された引数を、窓で開く 1 件にする（main の標準の窓の起動と同じ読み方）。"""
    args = parse_args(argv)
    if (args.wheel_morph_reference_helper is not None or args.remember_database is not None
            or args.forget_database or args.show_database or args.register_uri_scheme
            or args.unregister_uri_scheme or not _forwardable_standalone_launch(args)):
        raise ValueError("窓の使い回しの対象ではない依頼です")
    request = request_from_args(args)
    if request.get("wheel_morph_reference_helper") not in (None, ""):
        raise ValueError("External WheelStyle helper requests are blocked.")
    output_dir, vinyl_cache_root = _standalone_paths(args, request)
    return {"request": request, "output_dir": output_dir, "vinyl_cache_root": vinyl_cache_root,
            "rebuild": bool(args.rebuild), "started": time.perf_counter(), "first": False}


def _paint_swap_session(request: dict[str, Any], mesh_identity: tuple | None) -> dict[str, Any]:
    """開いた件の要約。次の件を、ページを読み直さずに差し替えられるかの判断に使う。"""
    return {"car_id": int(request.get("car_id") or 0), "quality": _string(request.get("quality")),
            "wheel_source": _effective_viewer_wheel_source(request), "mesh_identity": mesh_identity}


def _paint_swap_candidate(previous_server: Any, previous_error: Any, previous_session: dict[str, Any],
                          request: dict[str, Any]) -> bool:
    """前の件が正常に開けていて、車・品質・ホイールの出所が同じなら、差し替えを試みてよい。

    最後は、サーバーが渡す車体の GLB のファイルが同じか（_served_mesh_identity）を確かめてから頼む。
    """
    if previous_server is None or previous_error is not None or not previous_session:
        return False
    current = _paint_swap_session(request, None)
    return all(previous_session.get(key) == current[key] for key in ("car_id", "quality", "wheel_source"))


def _served_mesh_identity(server: Any) -> tuple | None:
    """サーバーが画面に渡す車体の GLB のファイル（場所・大きさ・更新日時）。同じ車かの判断に使う。"""
    path = getattr(server, "_local_mesh", None)
    if not path:
        return None
    try:
        stat = Path(path).stat()
        return (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def _show_paint_swap_status(window: Any, message: str) -> None:
    """差し替えの準備の間、前のペイントの上に状態を出す（ページの setStatus。最初の 1 枚を描くと消える）。"""
    with contextlib.suppress(Exception):
        payload = json.dumps(str(message), ensure_ascii=False)
        window.evaluate_js(f"window.lo4fh6ShowPaintSwapStatus && window.lo4fh6ShowPaintSwapStatus({payload});")


# 窓の読み直しの URL に付ける、毎回違う印の名前と番号（2026-11-22）。
VIEWER_RELOAD_PARAM = "lo4fh6-load"
_viewer_reload_counter = itertools.count(1)


def _viewer_reload_url(url: str) -> str:
    """窓を読み直す URL に、毎回違う印（lo4fh6-load=番号）を付ける（前の印は外す）。

    同じ車の次のペイントはサーバーを使い回すので、URL が今のページと同じになる。WebView2 は同じ URL では読み直さず、
    pywebview の load_url が下ろした「読み込み済み」の印も戻らない。その後のページへの命令は 1 回 20 秒待たされて失敗し、
    「Viewerを起動しています...」のまま止まった（2026-11-22、自動回転中に次のペイントを開いて差し替えが断られたとき）。
    ページは、この印を差し替えで違ってよい項目として扱う（viewer.js の PAINT_SWAP_VARIABLE_PARAMS）。
    """
    parts = urlsplit(str(url))
    kept = [item for item in parts.query.split("&") if item and not item.startswith(VIEWER_RELOAD_PARAM + "=")]
    kept.append(f"{VIEWER_RELOAD_PARAM}={next(_viewer_reload_counter)}")
    return urlunsplit(parts._replace(query="&".join(kept)))


def _try_paint_swap(window: Any, api: "PreviewJsApi", url: str, timeout: float = 10.0) -> bool:
    """ページに同じ車の次のペイントへの差し替えを頼む。受け付けられれば True（受け付けなければ呼び出し側が読み直す）。"""
    api._expect_paint_swap()
    payload = json.dumps(str(url), ensure_ascii=False)
    try:
        window.evaluate_js(
            f"window.lo4fh6SwapPaint ? void window.lo4fh6SwapPaint({payload}) : "
            "window.pywebview && window.pywebview.api.report_paint_swap({accepted: false, reason: 'no-swap-function'});")
    except Exception as exc:  # noqa: BLE001  頼めなければ読み直す
        _append_bridge_log(f"viewer paint swap: request failed: {type(exc).__name__}")
        return False
    result = api._wait_paint_swap(timeout)
    accepted = bool(result and result.get("accepted"))
    reason = "" if accepted else f" reason={(result or {}).get('reason') or 'timeout'}"
    _append_bridge_log(f"viewer paint swap: accepted={accepted}{reason}")
    return accepted


def _bring_window_to_front(window: Any) -> None:
    for action in (window.restore, window.show):
        with contextlib.suppress(Exception):
            action()
    # いったん最前面にしてすぐ戻す。pywebview の window.on_top は使わない（隠して作った窓を初めて表示するときに、
    # 窓の糸と互いに待って止まった。2026-11-21、viewer_window_reuse.raise_own_windows の説明）。
    with contextlib.suppress(Exception):
        _window_reuse.raise_own_windows()


def launch_standalone_preview(
    output_dir: Path | None,
    request: dict[str, Any] | None,
    vinyl_cache_root: Path | None,
    *,
    rebuild: bool,
    standby_parent_pid: int | None = None,
) -> int:
    """Viewer の窓を開き、最初の件と、別の起動から渡された件（窓の使い回し）を順に開く。

    standby_parent_pid を渡すと、窓を作らずに待つ（Organizer の起動で温めておく。2026-11-21）。Python の起動・重い部品の
    読み込み・受付だけを先に済ませ、最初の件が受付へ渡ったら、通常の起動と同じく見える窓を作って開く。その番号の
    Organizer が動いている間は終えない。
    （初めは窓を隠したまま作って待っていたが、その窓を初めて表示すると、最初の 1 枚が約 6 秒遅れ、前に出す操作で
    止まることもあった。2026-11-21）
    """
    launch_started = time.perf_counter()
    try:
        import webview  # type: ignore
    except ImportError as exc:
        raise ValueError("Standalone viewer requires pywebview / WebView2 support.") from exc

    standby = standby_parent_pid is not None
    # 窓を閉じても、決めた時間（共有の設定 viewer_keep_alive_seconds、既定 10 分）は隠して残す（2026-11-20）。
    keep_alive = _window_reuse.KeepAlive(_window_reuse.keep_alive_seconds(load_shared_settings(_settings_path())))
    if standby:
        keep_alive.start_hidden()
        keep_alive.watch_parent(int(standby_parent_pid or 0))
    closed = threading.Event()
    # 窓で開く件の順番。最初の件のあとは、別の起動から渡された件（窓の使い回し）が入る。
    jobs: "queue.Queue[dict[str, Any]]" = queue.Queue()
    if not standby:
        jobs.put({"request": request, "output_dir": output_dir, "vinyl_cache_root": vinyl_cache_root,
                  "rebuild": rebuild, "started": launch_started, "first": True})
    host: _ViewerHost | None = None
    try:
        host = _ViewerHost(lambda argv: jobs.put(_forwarded_standalone_job(argv)), closed,
                           standby=keep_alive.watch_parent)
    except OSError as exc:
        _append_bridge_log(f"viewer host unavailable; later launches open new windows: {exc}")
        if standby:
            return 0  # 受付が無ければ温めておいても使えない
    if standby:
        first_job = _wait_for_standby_job(jobs, keep_alive)
        if first_job is None:
            if host is not None:
                host.close()
            return 0
        jobs.put(first_job)
        request, output_dir, vinyl_cache_root = first_job["request"], first_job["output_dir"], first_job["vinyl_cache_root"]

    request = request if request is not None else {}
    title = _standalone_title(request)
    initial_gpu_selection = _gpu_livery_runtime_selection()
    if output_dir is not None:
        _write_gpu_livery_runtime_selection(output_dir, initial_gpu_selection)
    state: dict[str, Any] = {
        "server": None,
        "error": None,
        "vinyl_resource_root": None,
        "gpu_livery_runtime_selection": initial_gpu_selection,
    }
    api = PreviewJsApi(request, output_dir or Path(), vinyl_cache_root or Path(), state)
    window = webview.create_window(
        f"{title} - Livery Organizer for FH6",
        html=_loading_html(request),
        js_api=api,
        width=1440,
        height=900,
        min_size=(960, 640),
    )

    def on_closed() -> None:
        closed.set()

    try:
        window.events.closed += on_closed
    except Exception:
        pass
    try:
        window.events.closing += lambda: keep_alive.on_closing(window)
    except Exception:
        pass
    # ページの「Viewerを終了」：隠して残さず、すぐ終える（2026-11-22）
    api._quit_handler = lambda: keep_alive.quit(window)

    def worker() -> None:
        while not closed.is_set():
            if keep_alive.expired():
                keep_alive.finish(window)
                continue
            try:
                job = jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            # 準備の間に続けて届いた依頼は、最後の 1 件だけ開く。
            while True:
                try:
                    job = jobs.get_nowait()
                except queue.Empty:
                    break
            keep_alive.shown_for_job()
            _open_standalone_job(window, api, state, job, closed)

    from viewer_app_icon import start_options as icon_options
    try:
        webview.start(worker, gui="edgechromium", debug=False, **_webview_start_options(),
                      **icon_options(webview.start))
    finally:
        if host is not None:
            host.close()
        server = state.get("server")
        if server is not None:
            server.close()
            _append_bridge_log("viewer stopped; local server closed")
    return 1 if state.get("error") is not None else 0


def _open_standalone_job(window: Any, api: "PreviewJsApi", state: dict[str, Any], job: dict[str, Any],
                         closed: threading.Event) -> None:
    """窓で 1 件を準備して開く。2 件目からは、前のサーバーを閉じて同じ窓を次のペイントに切り替える。"""
    request = job["request"]
    output_dir = job["output_dir"]
    vinyl_cache_root = job["vinyl_cache_root"]
    rebuild = bool(job["rebuild"])
    launch_started = float(job["started"])
    swap_server: LiveryInspectorServer | None = None
    previous_session: dict[str, Any] = {}
    if not job.get("first"):
        previous_server = state.get("server")
        previous_session = dict(state.get("session") or {})
        # 同じ車・同じ品質・同じホイールの出所で、前の件が正常に開けていれば、ページを読み直さずに差し替えを試みる
        # （同じ窓・同じサーバー）。最後は、同じ車体の GLB のファイルかを確かめてから差し替える。
        swap_candidate = _paint_swap_candidate(previous_server, state.get("error"), previous_session, request)
        selection = _gpu_livery_runtime_selection()
        _write_gpu_livery_runtime_selection(output_dir, selection)
        state.clear()
        state.update({"server": previous_server if swap_candidate else None, "error": None,
                      "vinyl_resource_root": None, "gpu_livery_runtime_selection": selection,
                      "session": previous_session})
        api._switch_session(request, output_dir, vinyl_cache_root)
        with contextlib.suppress(Exception):
            window.set_title(f"{_standalone_title(request)} - Livery Organizer for FH6")
        if swap_candidate:
            swap_server = previous_server
            _bring_window_to_front(window)
            _show_paint_swap_status(window, "次のペイントを準備しています...")
        else:
            with contextlib.suppress(Exception):
                window.load_html(_loading_html(request))
            _bring_window_to_front(window)
            if previous_server is not None:
                with contextlib.suppress(Exception):
                    previous_server.close()
                _append_bridge_log("viewer switched to the next paint; previous local server closed")
    if job.get("from_standby"):
        # 温めておいた起動の最初の件は、Organizer のリンクから渡った依頼。窓をほかの窓の上に出す（2026-11-21）
        _bring_window_to_front(window)
    initial_gpu_selection = state.get("gpu_livery_runtime_selection")
    if swap_server is not None:
        def status_callback(message: str) -> None:
            _show_paint_swap_status(window, message)
    else:
        def status_callback(message: str) -> None:
            _set_window_status(window, message)
    try:
        # 登録済みr122のURI起動は安定したLocalAppDataのpythonwへ直接入る。
        # Cache処理より前に読み込み画面を明示し、初回起動の進捗を必ず見せる。
        try:
            window.show()
        except Exception:
            pass
        state["vinyl_resource_root"] = _prepare_for_viewer(
            request,
            output_dir,
            vinyl_cache_root,
            rebuild=rebuild,
            status=status_callback,
            hide_subprocess_window=True,
        )
        prepare_elapsed = time.perf_counter() - launch_started
        _append_bridge_log(f"startup prepare complete: {prepare_elapsed:.2f}s")
        if closed.is_set():
            return
        status_callback("Viewerを起動しています...")
        server, url = _configure_server(output_dir, request, state.get("vinyl_resource_root"), server=swap_server)
        state["server"] = server
        mesh_identity = _served_mesh_identity(server)
        state["session"] = _paint_swap_session(request, mesh_identity)
        # ブランチ差分を唯一の実行隔離境界とし、localhostのセッションURLを
        # 研究フラグで変えない。Wheel/Mirror/Tireは原本署名の標準判定のみ。
        try:
            state["gpu_livery_runtime_selection"] = json.loads(
                (output_dir / "gpu-livery-runtime-selection.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            pass
        ready_elapsed = time.perf_counter() - launch_started
        preview_timings: dict[str, Any] = {}
        preview_profile: dict[str, Any] = {}
        cache_state: dict[str, Any] = {}
        cache_footprint: dict[str, Any] = {}
        base_paint_selection: dict[str, Any] = {}
        bridge_prepare_state: dict[str, Any] = {}
        prepare_state_path = output_dir / "viewer-prepare-state.json"
        if prepare_state_path.is_file():
            try:
                payload = json.loads(prepare_state_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    bridge_prepare_state = payload
            except (OSError, ValueError, TypeError):
                bridge_prepare_state = {}
        summary_path = output_dir / "vehicle-preview-summary.json"
        if summary_path.is_file():
            try:
                summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
                preview_timings = dict(summary_payload.get("timings_seconds") or {})
                preview_profile = dict(summary_payload.get("atlas_prepare_profile_seconds") or {})
                cache_state = dict(summary_payload.get("cache_state") or {})
                cache_footprint = dict(summary_payload.get("cache_footprint") or {})
                base_paint_selection = dict(summary_payload.get("base_paint_selection") or {})
            except (OSError, ValueError, TypeError):
                preview_timings = {}
                preview_profile = {}
                cache_state = {}
                cache_footprint = {}
                base_paint_selection = {}
        output_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "format": "lo4fh6_viewer_startup_metrics_v1",
            "record_id": _string(request.get("record_id")),
            "car_id": int(request.get("car_id") or 0),
            "quality": _string(request.get("quality")),
            "wheel_source_requested": _string(request.get("wheel_source")),
            "wheel_source_effective": _effective_viewer_wheel_source(request),
            "gamedb_missing": bool(request.get("gamedb_missing")),
            "bridge_prepare_seconds": round(prepare_elapsed, 4),
            "bridge_ready_seconds": round(ready_elapsed, 4),
            "viewer_window_reused": not bool(job.get("first")),
            "performance_target": {
                "goal": "paint-download-complete-to-viewer-ready",
                "target_seconds": 5.0,
                "target_met": bool(ready_elapsed <= 5.0),
                "over_target_seconds": round(max(0.0, ready_elapsed - 5.0), 4),
            },
            "preview_timings_seconds": preview_timings,
            "atlas_prepare_profile_seconds": preview_profile,
            "cache_state": cache_state,
            "cache_footprint": cache_footprint,
            "bridge_prepare_state": bridge_prepare_state,
            "prepared_output_reused_this_launch": bool(bridge_prepare_state.get("prepared_output_reused")),
            "full_vinyl_cache_required_this_launch": bool(bridge_prepare_state.get("full_vinyl_cache_required")),
            "base_paint_selection": base_paint_selection,
            "gpu_livery_runtime_selection": dict(state.get("gpu_livery_runtime_selection") or initial_gpu_selection or {}),
        }
        (output_dir / "viewer-startup-metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if base_paint_selection:
            _append_bridge_log(
                "base paint: "
                f"available={base_paint_selection.get('available')} "
                f"finish={base_paint_selection.get('finish_code_raw')} "
                f"color={base_paint_selection.get('primary_color_rgba_hex')} "
                f"count={base_paint_selection.get('cluster_count')}"
            )
        _append_bridge_log(
            f"viewer ready: total={ready_elapsed:.2f}s prepare={prepare_elapsed:.2f}s "
            f"quality={request.get('quality')} reused_window={not bool(job.get('first'))} timings={preview_timings}"
        )
        _append_bridge_log(
            "5s target: "
            f"ready={ready_elapsed:.2f}s target=5.00s "
            f"met={ready_elapsed <= 5.0} cache={cache_state}"
        )
        _append_bridge_log(f"viewer started: {url}")
        if not closed.is_set():
            swapped = False
            if (swap_server is not None and mesh_identity is not None
                    and mesh_identity == previous_session.get("mesh_identity")):
                swapped = _try_paint_swap(window, api, url)
            if not swapped:
                # 同じ URL でも必ず読み直すよう、毎回違う印を付ける（差し替えが断られたとき、URL が今のページと同じになる）
                window.load_url(_viewer_reload_url(url))
            _retain_recent_paint_folders_later(output_dir.parent, output_dir)
    except Exception as exc:
        state["error"] = exc
        _append_bridge_log(f"ERROR: {exc}\n{traceback.format_exc()}")
        if not closed.is_set():
            try:
                window.load_html(_error_html(str(exc)))
            except Exception:
                pass


def launch_browser_preview(
    output_dir: Path, request: dict[str, Any], *, auto_open: bool, vinyl_resource_root: Path | None = None
) -> int:
    server, url = _configure_server(output_dir, request, vinyl_resource_root)
    try:
        print(f"viewer: {url}")
        print(f"output: {output_dir}")
        print("Press Ctrl+C in this terminal to stop the local viewer.")
        if auto_open:
            webbrowser.open(url, new=2)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nviewer stopped")
        return 0
    finally:
        server.close()


def main() -> int:
    configure_console_text_streams()
    args = parse_args()
    if args.wheel_morph_reference_helper is not None:
        print(
            "The external WheelStyle morph executable is unavailable in the first-party product. "
            "Remove --wheel-morph-reference-helper; native Wheel Morph is automatic.",
            file=sys.stderr,
        )
        return 2
    if getattr(args, "gui_child", False):
        _detach_gui_console()
    if args.remember_database is not None:
        resolution = remember_database(args.remember_database, settings_file=_settings_path())
        print(f"GameDB saved: {resolution.path}")
        print("The database file was validated in place; it was not copied or modified.")
        return 0
    if args.forget_database:
        forget_database(settings_file=_settings_path())
        print("Saved GameDB path cleared. The database file was not deleted.")
        return 0
    if args.show_database:
        resolution = resolve_database_path(settings_file=_settings_path())
        if resolution is None:
            print("GameDB: not configured")
        else:
            print(f"GameDB: {resolution.path}")
            print(f"source: {resolution.source}")
        return 0
    if args.register_uri_scheme:
        register_uri_scheme()
        return 0
    if args.unregister_uri_scheme:
        unregister_uri_scheme()
        return 0
    # Organizer の起動で温めておく依頼（liveryorganizerpreviewforfh6://standby?pid=…。2026-11-21）
    standby_parent = _window_reuse.standby_request_pid(sys.argv[1:])
    if standby_parent is not None:
        return _start_viewer_standby(args, standby_parent)
    # 開いている Viewer の窓があれば、そこへ依頼を渡して終わる（窓の使い回し）。無ければ従来どおり。
    if _forward_to_running_viewer(args, sys.argv[1:]):
        return 0
    if _spawn_uri_gui_child(args):
        return 0
    request = request_from_args(args)
    if request.get("wheel_morph_reference_helper") not in (None, ""):
        print(
            "External WheelStyle helper requests are blocked. "
            "Use the existing independent WheelStyle morph without an EXE.",
            file=sys.stderr,
        )
        return 2
    output_dir, vinyl_cache_root = _standalone_paths(args, request)
    if args.prepare_only:
        _prepare_for_viewer(request, output_dir, vinyl_cache_root, rebuild=args.rebuild)
        print("PREPARE PASS — organizer bridge did not start the viewer.")
        return 0
    if args.no_open:
        vinyl_resource_root = _prepare_for_viewer(request, output_dir, vinyl_cache_root, rebuild=args.rebuild)
        server, url = _configure_server(output_dir, request, vinyl_resource_root)
        try:
            print(f"viewer: {url}")
            print("NO-OPEN mode: press Ctrl+C to stop the local viewer.")
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0
        finally:
            server.close()
    if args.window_mode == "browser":
        vinyl_resource_root = _prepare_for_viewer(request, output_dir, vinyl_cache_root, rebuild=args.rebuild)
        return launch_browser_preview(
            output_dir, request, auto_open=True, vinyl_resource_root=vinyl_resource_root
        )
    return launch_standalone_preview(output_dir, request, vinyl_cache_root, rebuild=args.rebuild)


def run_as_program() -> None:
    """プログラムとして動かす（ソースの直接起動と、EXE の入口 livery_viewer_for_fh6 の両方から呼ぶ）。"""
    try:
        raise SystemExit(main())
    except (FullLiveryPackageError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        _append_bridge_log(f"ERROR: {exc}\n{traceback.format_exc()}")
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    run_as_program()
