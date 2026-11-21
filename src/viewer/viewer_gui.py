# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=10,<13", "numpy>=1.26,<3", "psutil>=5.9,<8", "pywebview>=5.4,<7"]
# ///
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

# 本Viewerの第一者デスクトップ共通設定。旧rM026の保存ファイルとは別管理。
from lo4fh6_desktop_suite.settings import (load_settings as load_suite_settings,
    update_settings as update_suite_settings, viewer_appearance_options, viewer_wheel_source)
from lo4fh6_desktop_suite.theme import PALETTES
from lo4fh6_desktop_suite.runtime import is_packaged, self_command
import viewer_window_reuse as window_reuse

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "organizer_preview_bridge.py"
DEMO_BRIDGE = ROOT / "original_demo_preview_bridge.py"
VIEWER_FIXTURE_MARKER = "lo4fh6-viewer-fixture.json"
VIEWER_FIXTURE_FORMAT = "lo4fh6_viewer_livery_fixture_v1"
LIVERY_NAME_RE = re.compile(r"^Livery_(\d+)(?:_|$)", re.IGNORECASE)
CONFIG_FORMAT = "lo4fh6_preview_viewer_gui_v1"
SHARED_UI_CSS = ROOT / "tools" / "livery-inspector" / "lo4fh6-ui.css"

BUILD_IDENTITY_PATH = ROOT / "tools" / "livery-inspector" / "lo4fh6-build-identity.json"
BUILD_IDENTITY_SCHEMA = "lo4fh6.viewer.private-build-identity.v1"


def _git_source_revision() -> str:
    """ソースの版（写しの札、または作業ツリーの .git）。git は起動しない（以前は版の表示のためだけに git を
    起動し、黒い窓が出ていた。2026-11-20）。分からなければ空（配布 ZIP へ偽の版を付けない）。"""
    from tools.livery.source_version import source_revision
    try:
        revision = source_revision(ROOT)
    except OSError:
        return ""
    return revision["commit"] if revision else ""


def _build_source_revision() -> str:
    try:
        identity = json.loads(BUILD_IDENTITY_PATH.read_text(encoding="utf-8"))
        revision = identity.get("source_commit", "")
        if (identity.get("schema") == BUILD_IDENTITY_SCHEMA and
                isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision)):
            return revision
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    return _git_source_revision()


def _build_identity_label() -> str:
    """GUI内の表示は製品基盤と実行ソースを区別する。"""
    try:
        identity = json.loads(BUILD_IDENTITY_PATH.read_text(encoding="utf-8"))
        label = identity.get("display_label")
        if (identity.get("schema") == BUILD_IDENTITY_SCHEMA
                and isinstance(label, str) and 0 < len(label) <= 240):
            return label
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    revision = _git_source_revision()
    if revision:
        return f"版: Git開発ソース {revision[:12]}｜PRIVATE配布ビルド情報なし（未受入）"
    return "版: 配布ビルド情報なし｜実行ソース未識別（確認が必要）"


def _window_title() -> str:
    # 配布の EXE は名前だけにする（版は設定画面と 3D の画面の版の表示に出る。2026-11-18 利用者の決定）。
    if is_packaged():
        return "Livery Viewer for FH6"
    revision = _build_source_revision()
    suffix = ("Git " + revision[:12]) if revision else "ソース識別なし"
    # PRIVATE組立時に取得した実HEADコミット日時。ZIPのビルド日と混同しない。
    try:
        identity = json.loads(BUILD_IDENTITY_PATH.read_text(encoding="utf-8"))
        committed = identity.get("source_commit_at_jst", "")
        if identity.get("schema") == BUILD_IDENTITY_SCHEMA and isinstance(committed, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} JST", committed
        ):
            suffix += f"｜commit【{committed}】"
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    return f"Livery Viewer for FH6｜{suffix}｜PRIVATE"



def _shared_ui_css() -> str:
    return SHARED_UI_CSS.read_text(encoding="utf-8")


def _local_appdata() -> Path:
    raw = os.environ.get("LOCALAPPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Local"


def config_path() -> Path:
    return _local_appdata() / "Livery Organizer for FH6" / "PreviewBridge" / "viewer-gui.json"


def log_path() -> Path:
    return _local_appdata() / "Livery Organizer for FH6" / "PreviewBridge" / "viewer-gui.log"


def default_output_root() -> Path:
    return Path.home() / "Documents" / "Livery-Organizer-for-FH6" / "preview-cache"


def default_game_folder() -> Path:
    candidates = (
        Path(r"C:\XboxGames\Forza Horizon 6\Content"),
        Path(r"C:\XboxGames\Forza Horizon 6"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def normalize_livery_source(value: str | Path) -> Path:
    source = Path(value).expanduser()
    if source.name.casefold() == "c_livery":
        source = source.parent
    return source


def prefer_current_livery_source(value: str | Path) -> Path:
    """Save a live GameSave ``current`` alias, not its changing numeric target.

    Only a validated per-profile GameSave link is eligible.  Never rewrite a
    regular copied Livery folder, a non-link ``current`` directory, or a link
    pointing outside its profile.  No account ID or save-slot number is fixed.
    """
    source = normalize_livery_source(value)
    if not LIVERY_NAME_RE.match(source.name):
        return source
    containers_root = source.parent
    slot = containers_root.parent
    profile = slot.parent
    if not (
        containers_root.name.casefold() == "containersroot"
        and slot.name.isascii() and slot.name.isdecimal()
        and profile.name.casefold().startswith("u_")
        and profile.parent.name.casefold() == "pgs"
    ):
        return source
    current = profile / "current"
    try:
        is_link = current.is_symlink() or bool(getattr(current, "is_junction", lambda: False)())
        if not is_link:
            return source
        link_target = current.resolve(strict=True)
        # The moving alias must target a sibling numbered slot of this profile.
        if link_target.parent != profile.resolve(strict=True) or not link_target.name.isdecimal():
            return source
        candidate = current / "ContainersRoot" / source.name
        if candidate.is_dir() and (candidate / "C_livery").is_file():
            return candidate
    except (OSError, RuntimeError):
        return source
    return source


def _portable_path_name(value: str | Path) -> str:
    raw = str(value).rstrip("\\/")
    parts = [part for part in re.split(r"[\\/]", raw) if part]
    if parts and parts[-1].casefold() == "c_livery":
        parts.pop()
    return parts[-1] if parts else normalize_livery_source(value).name


def infer_car_id(value: str | Path) -> int | None:
    match = LIVERY_NAME_RE.match(_portable_path_name(value))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def validate_livery_source(value: str | Path) -> tuple[Path, int]:
    source = prefer_current_livery_source(value)
    c_livery = source / "C_livery"
    if not source.is_dir():
        raise ValueError(f"Livery_* フォルダーが見つかりません: {source}")
    if not c_livery.is_file():
        raise ValueError(f"C_livery が見つかりません: {source}")
    car_id = infer_car_id(source)
    if car_id is None:
        raise ValueError("フォルダー名からCar IDを取得できません。Livery_<Car ID>_* を選択してください。")
    # abspath normalizes relative input without dereferencing GameSave/current.
    return Path(os.path.abspath(source)), car_id


def validate_game_folder(value: str | Path) -> Path:
    root = Path(value).expanduser()
    direct = root / "media" / "livery" / "Vinyls.zip"
    nested = root / "Content" / "media" / "livery" / "Vinyls.zip"
    if direct.is_file() or nested.is_file():
        return root.resolve()
    raise ValueError("FH6フォルダーを確認できません。インストール先または Content フォルダーを選択してください。")


def _suite_preferences() -> dict[str, Any]:
    """共有設定の読込失敗は元データを保持し、旧GUIを起動可能にする。"""
    try:
        data = load_suite_settings()
        return {'ui': data['ui'], 'paths': data['paths'], 'appearance': {**viewer_appearance_options(data), 'wheel_source': viewer_wheel_source(data)}, 'warning': ''}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {'ui': {'language': 'ja', 'theme': 'system'}, 'paths': {},
                'appearance': {'source_material_enabled': True, 'neutral_livery_grade_enabled': True, 'wheel_source': 'source-verified'},
                'warning': '共通設定の読込に失敗しました。既存ファイルは変更していません: ' + str(exc)}


def _save_suite_paths(source: str, game: str, output: str) -> str:
    """旧GUI設定保存後、共有パスだけを更新。失敗しても旧画面の起動は妨げない。"""
    try:
        update_suite_settings({'paths': {
            'game_folder': str(game),
            'livery_folder': str(prefer_current_livery_source(source)) if source else '',
            'output_directory': str(output),
        }})
        return ''
    except (OSError, ValueError, TypeError, TimeoutError) as exc:
        return '共通設定を更新できませんでした（旧Viewer設定は保存済み）: ' + str(exc)


def load_config(path: Path | None = None) -> dict[str, str]:
    target = path or config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict) or data.get("format") != CONFIG_FORMAT:
        data = {}
    # GUIの読み込み時のみ共通設定値を優先し、旧設定とGameSaveを変更しない。
    paths = _suite_preferences()['paths'] if path is None else {}
    return {
        "game_folder": str(paths.get('game_folder') or data.get("game_folder") or default_game_folder()),
        "output_root": str(paths.get('output_directory') or data.get("output_root") or default_output_root()),
        "last_livery_folder": str(prefer_current_livery_source(paths.get('livery_folder') or data.get('last_livery_folder')))
                              if (paths.get('livery_folder') or data.get('last_livery_folder')) else "",
    }


def save_config(values: dict[str, str], path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": CONFIG_FORMAT,
        "game_folder": str(values.get("game_folder") or ""),
        "output_root": str(values.get("output_root") or ""),
        "last_livery_folder": str(prefer_current_livery_source(values["last_livery_folder"])) if values.get("last_livery_folder") else "",
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def bridge_command(*args: str) -> list[str]:
    # ソースは今の Python と organizer_preview_bridge.py、EXE は EXE 自身（lo4fh6_desktop_suite.runtime）
    return self_command('bridge', *args)


def load_viewer_fixture_marker(source: Path) -> dict[str, Any] | None:
    marker_path = source / VIEWER_FIXTURE_MARKER
    if not marker_path.is_file():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"Viewer fixture markerを読み取れません: {marker_path}") from exc
    if not isinstance(payload, dict) or payload.get("format") != VIEWER_FIXTURE_FORMAT:
        raise ValueError(f"未対応のViewer fixture markerです: {marker_path}")
    return payload


def preview_command(source: Path, game_folder: Path, output_root: Path, car_id: int, wheel_source: str = "source-verified") -> list[str]:
    fixture = load_viewer_fixture_marker(source)
    if fixture is not None:
        fixture_car_id = int(fixture.get("car_id") or 0)
        if fixture_car_id and fixture_car_id != int(car_id):
            raise ValueError(
                f"Viewer fixtureのCar IDがフォルダー名と一致しません: folder={car_id} fixture={fixture_car_id}"
            )
        return self_command(
            'demo-bridge',
            "--demo-root", str(source),
            "--game-folder", str(game_folder),
            "--car-id", str(car_id),
            "--output-root", str(output_root),
            "--window-mode", "standalone",
        )
    wheel_arg = ("--wheel-source", wheel_source)
    return bridge_command(
        "--source", str(source),
        "--game-folder", str(game_folder),
        "--car-id", str(car_id),
        "--output-root", str(output_root),
        "--window-mode", "standalone",
        *wheel_arg,
    )


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    return env


def _windows_folder_dialog(title: str, directory: str = "") -> str:
    # Use an STA Windows Forms picker instead of invoking pywebview's dialog
    # from a JS API callback. This avoids WebView2/pywebview combinations where
    # the folder picker can fail to surface even though the JS call succeeds.
    script = "\n".join([
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
        "Add-Type -AssemblyName System.Windows.Forms",
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
        "$dialog.Description = $env:LO4FH6_FOLDER_DIALOG_TITLE",
        "$dialog.ShowNewFolderButton = $true",
        "if ($env:LO4FH6_FOLDER_DIALOG_INITIAL -and [System.IO.Directory]::Exists($env:LO4FH6_FOLDER_DIALOG_INITIAL)) { $dialog.SelectedPath = $env:LO4FH6_FOLDER_DIALOG_INITIAL }",
        "$owner = New-Object System.Windows.Forms.Form",
        "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen",
        "$owner.ShowInTaskbar = $false",
        "$owner.TopMost = $true",
        "$owner.Width = 1",
        "$owner.Height = 1",
        "$owner.Opacity = 0",
        "try {",
        "  $owner.Show()",
        "  $owner.Activate()",
        "  $result = $dialog.ShowDialog($owner)",
        "  if ($result -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($dialog.SelectedPath) }",
        "}",
        "finally {",
        "  $dialog.Dispose()",
        "  $owner.Close()",
        "  $owner.Dispose()",
        "}",
    ])
    env = _child_env()
    env["LO4FH6_FOLDER_DIALOG_TITLE"] = title
    env["LO4FH6_FOLDER_DIALOG_INITIAL"] = directory if Path(directory).is_dir() else ""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=_creationflags(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Windows folder dialog failed (exit {result.returncode}): {detail}")
    return (result.stdout or "").strip()


def run_bridge_capture(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_child_env(),
        creationflags=_creationflags(),
    )
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    if text:
        with log.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text + "\n")
    return int(result.returncode), text


def _launcher_html(config: dict[str, str]) -> str:
    initial = json.dumps(config, ensure_ascii=False).replace('<', '\\u003c')
    suite = _suite_preferences()
    initial_suite = json.dumps({'language': suite['ui'].get('language', 'ja'),
                                'theme': suite['ui'].get('theme', 'system'),
                                'warning': suite['warning'], 'appearance': suite['appearance'],
                                'standby': window_reuse.standby_enabled(window_reuse.read_preview_settings())},
                               ensure_ascii=False).replace('<', '\\u003c')
    palette_json = json.dumps(PALETTES, ensure_ascii=True)
    shared_css = _shared_ui_css()
    # 既存lo4fh6-ui.cssの変数だけを上書きし、rendererやGUIイベント構造は維持。
    def palette(name: str) -> str:
        t = PALETTES[name]
        values = {
            '--lo4-bg': t['background'], '--lo4-panel': t['surface'],
            '--lo4-panel-solid': t['surface'], '--lo4-control': t['surface'],
            '--lo4-line': t['outline'], '--lo4-line-control': t['outline'],
            '--lo4-text': t['text'], '--lo4-text-control': t['text'],
            '--lo4-text-muted': t['muted'], '--lo4-accent': t['accent'],
            '--lo4-accent-border': t['accent'], '--lo4-accent-text': t['accent_text'],
            '--lo4-danger-text': t['error'],
        }
        values['color-scheme'] = name
        return ';'.join(k + ':' + v for k, v in values.items()) + ';'
    light, dark = palette('light'), palette('dark')
    theme_css = ('.lo4-ui[data-suite-theme="light"]{' + light + '}'
                 '.lo4-ui[data-suite-theme="dark"]{' + dark + '}'
                 '.lo4-ui[data-suite-theme="system"]{' + light + '}'
                 '@media(prefers-color-scheme:dark){.lo4-ui[data-suite-theme="system"]{' + dark + '}}')
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>{shared_css}</style>
<style>{theme_css}</style>
<style>
body{{margin:0}}
main{{max-width:1040px;margin:0 auto;padding:10px 16px 8px;box-sizing:border-box}}h1{{font-size:19px;margin:0 0 4px}}p{{color:var(--lo4-text-muted);line-height:1.4;margin:0 0 5px}}
.card{{padding:8px 12px;margin-top:7px}}.row{{display:grid;grid-template-columns:150px minmax(0,1fr) 66px;gap:8px;align-items:center;margin:5px 0}}.row>.lo4-button{{width:66px;min-width:66px;padding-left:7px;padding-right:7px}}
label{{color:var(--lo4-text-control)}}input{{width:100%;min-width:0;box-sizing:border-box}}input[type=checkbox]{{width:auto;min-width:0}}
.checkrow{{display:flex;gap:8px;align-items:center;margin:8px 0 2px}}
.primary{{font-weight:700}}#status{{min-height:24px;color:var(--lo4-text-control)}}#status.error{{color:var(--lo4-danger-text)}}
pre{{height:calc(10 * 1.45em);font-size:12px;line-height:1.45;overflow:auto;background:var(--lo4-panel-solid);border:1px solid var(--lo4-line);border-radius:var(--lo4-radius-panel);padding:10px;color:var(--lo4-text-muted);white-space:pre-wrap;margin:6px 0}}
.small{{font-size:12px;color:var(--lo4-text-muted)}}
@media(max-width:700px){{.row{{grid-template-columns:1fr}}}}
</style></head><body class="lo4-ui"><main><h1>Livery Viewer for FH6</h1>
<div class="small" id="lo4fh6-gui-build-id" style="font-weight:700;margin:0 0 8px">{html.escape(_build_identity_label())}</div>
<p data-i18n="description">Organizerと連携して3Dリバリーを表示します。Livery_* フォルダーを指定してください。</p>
<div class="card lo4-card"><div class="toolbar lo4-toolbar"><button class="lo4-button" onclick="registerIntegration()" data-i18n="register">Organizer連携を登録</button><button class="lo4-button" onclick="unregisterIntegration()" data-i18n="unregister">連携登録を解除</button></div>
<label class="checkrow" for="standby"><input type="checkbox" id="standby"><span data-i18n="standby">Organizerの起動時に3Dプレビューを準備しておく（最初の表示が速くなります。裏でメモリーを使います）</span></label></div>
<div class="card lo4-card"><div class="row"><label for="suite-language" data-i18n="language">言語</label><select class="lo4-select" id="suite-language"><option value="ja">日本語</option><option value="en">English</option></select><span></span></div>
<div class="row"><label for="suite-theme" data-i18n="theme">表示テーマ</label><select class="lo4-select" id="suite-theme"><option value="system" data-i18n="system">システム設定</option><option value="light" data-i18n="light">ライト</option><option value="dark" data-i18n="dark">ダーク</option></select><span></span></div>
</div>
<div class="card lo4-card">
<div class="row"><label data-i18n="game">FH6フォルダー</label><input class="lo4-input" id="game"><button class="lo4-button" onclick="chooseGame()" data-i18n="browse">参照...</button></div>
<div class="row"><label data-i18n="livery">Livery_* フォルダー</label><input class="lo4-input" id="source"><button class="lo4-button" onclick="chooseLivery()" data-i18n="browse">参照...</button></div>
<div class="row"><label data-i18n="output">preview-cache</label><input class="lo4-input" id="output"><button class="lo4-button" onclick="chooseOutput()" data-i18n="browse">参照...</button></div>
<div class="toolbar lo4-toolbar" style="justify-content:flex-end;margin-top:16px"><button class="primary lo4-button lo4-button-primary" onclick="openPreview()" data-i18n="open">3Dプレビューを開く</button></div>
</div>
<div class="card lo4-card"><div id="status" data-i18n="ready">準備完了</div><pre id="log"></pre><div class="small"><span data-i18n="log">ログ</span>: {html.escape(str(log_path()))}</div></div>
</main><script>
const INITIAL={initial};
const INITIAL_SUITE={initial_suite};
const I18N={{
 ja: {{description:'Organizerと連携して3Dリバリーを表示します。Livery_* フォルダーを指定してください。',language:'言語',theme:'表示テーマ',system:'システム設定',light:'ライト',dark:'ダーク',register:'Organizer連携を登録',unregister:'連携登録を解除',game:'FH6フォルダー',livery:'Livery_* フォルダー',output:'preview-cache',browse:'参照...',ready:'準備完了',log:'ログ',open:'3Dプレビューを開く',chooseGame:'FH6フォルダーを選択してください...',chooseLivery:'Livery_* フォルダーを選択してください...',chooseOutput:'preview-cache フォルダーを選択してください...',selectFailed:'フォルダー選択に失敗しました',registering:'連携を登録しています...',unregistering:'連携登録を解除しています...',opening:'3Dプレビューを開始しています...',registerFailed:'Organizer連携を登録できませんでした',unregisterFailed:'Organizer連携を解除できませんでした',registerDone:'Organizer連携を登録しました',unregisterDone:'Organizer連携を解除しました',openDone:'3Dプレビューを起動しました',saveDone:'共通表示設定を保存しました',sourceMaterial:'原本材質',neutralGrade:'色補正中立化',wheelMode:'車輪・タイヤ',wheelProxy:'従来の車輪',wheelStock:'原本車輪（タイヤ補完）',wheelVerified:'原本4輪＋タイヤ（ローカル原本・研究比較）',appearanceError:'描画設定を保存できませんでした',standby:'Organizerの起動時に3Dプレビューを準備しておく（最初の表示が速くなります。裏でメモリーを使います）',standbyDone:'Organizerの起動時の準備の設定を保存しました',standbyError:'設定を保存できませんでした'}},
 en: {{description:'Preview liveries in 3D and connect with Organizer. Choose a Livery_* folder to start.',language:'Language',theme:'Theme',system:'Follow system',light:'Light',dark:'Dark',register:'Register Organizer integration',unregister:'Remove Organizer integration',game:'FH6 folder',livery:'Livery_* folder',output:'preview-cache',browse:'Browse...',ready:'Ready',log:'Log',open:'Open 3D preview',chooseGame:'Choose your FH6 folder...',chooseLivery:'Choose a Livery_* folder...',chooseOutput:'Choose preview-cache folder...',selectFailed:'Folder selection failed',registering:'Registering Organizer integration...',unregistering:'Removing Organizer integration...',opening:'Launching 3D preview...',registerFailed:'Could not register Organizer integration',unregisterFailed:'Could not remove Organizer integration',registerDone:'Organizer integration registered',unregisterDone:'Organizer integration removed',openDone:'3D preview launched',saveDone:'Shared appearance saved',sourceMaterial:'Source materials',neutralGrade:'Neutral livery grade',wheelMode:'Wheels / tires',wheelProxy:'Legacy wheels',wheelStock:'Recovered wheel with neutral tire',wheelVerified:'Local original wheels + tires (research comparison)',appearanceError:'Could not save rendering settings',standby:'Prepare the 3D preview when Organizer starts (faster first preview; uses memory in the background)',standbyDone:'Organizer startup preparation setting saved',standbyError:'Could not save the setting'}}
}};
const languageInput=document.getElementById('suite-language');
const themeInput=document.getElementById('suite-theme');
function tr(key){{return (I18N[languageInput.value]||I18N.ja)[key]||I18N.ja[key]||key;}}
function applySuiteUi(language,theme){{
  const lang=language==='en'?'en':'ja';
  document.documentElement.lang=lang;
  document.body.dataset.suiteTheme=theme;
  for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=I18N[lang][node.dataset.i18n]||node.textContent;
  requestAnimationFrame(fitWindow);
}}
// 窓の大きさを中身に合わせる（2026-11-21）。中身の下の端を測って Python に渡し、Python が枠の分を足して窓を変える。
// 読み終わったとき・文字が読み込まれたとき・言語を変えたとき（文の長さで折り返しが変わる）に合わせ直す。
async function fitWindow(){{
  try{{
    if(!(window.pywebview&&window.pywebview.api&&window.pywebview.api.fit_window))return;
    const main=document.querySelector('main');
    const needHeight=Math.ceil(main.getBoundingClientRect().bottom+window.scrollY);
    const needWidth=Math.max(document.documentElement.scrollWidth,window.innerWidth);
    await window.pywebview.api.fit_window(needWidth,needHeight,window.innerWidth,window.innerHeight);
  }}catch(e){{}}
}}
window.addEventListener('pywebviewready',()=>{{(document.fonts?document.fonts.ready:Promise.resolve()).then(()=>requestAnimationFrame(fitWindow))}});
languageInput.value=INITIAL_SUITE.language==='en'?'en':'ja';
themeInput.value=['light','dark','system'].includes(INITIAL_SUITE.theme)?INITIAL_SUITE.theme:'system';
applySuiteUi(languageInput.value,themeInput.value);
async function persistSuiteUi(){{
  const previous={{language:INITIAL_SUITE.language,theme:INITIAL_SUITE.theme}};
  const lang=languageInput.value,theme=themeInput.value;
  const response=await pywebview.api.save_suite_ui(lang,theme);
  if(!response.ok){{
    languageInput.value=previous.language==='en'?'en':'ja';
    themeInput.value=['light','dark','system'].includes(previous.theme)?previous.theme:'system';
    applySuiteUi(languageInput.value,themeInput.value);
    status(response.message,true);
    return;
  }}
  INITIAL_SUITE.language=lang;INITIAL_SUITE.theme=theme;
  applySuiteUi(lang,theme);
  status(tr('saveDone'));
}}
languageInput.addEventListener('change',()=>persistSuiteUi().catch(e=>status(String(e),true)));
themeInput.addEventListener('change',()=>persistSuiteUi().catch(e=>status(String(e),true)));
// Organizer の起動時に Viewer を温めておくか（共有の設定 viewer_standby_with_organizer、既定はオン。2026-11-21）
const standbyInput=document.getElementById('standby');
standbyInput.checked=INITIAL_SUITE.standby!==false;
standbyInput.addEventListener('change',async()=>{{
  const wanted=standbyInput.checked;
  try {{
    const r=await pywebview.api.save_standby(wanted);
    if(!(r&&r.ok)){{standbyInput.checked=!wanted;status((r&&r.message)||tr('standbyError'),true);return;}}
    status(tr('standbyDone'));
  }} catch(e) {{standbyInput.checked=!wanted;status(String(e),true)}}
}});
// 原本材質と色補正中立化は標準機能。GUIから切替えず、古い設定は読み取り専用で保全。
const game=document.getElementById('game'), source=document.getElementById('source'), output=document.getElementById('output'), statusEl=document.getElementById('status'), logEl=document.getElementById('log');
game.value=INITIAL.game_folder||'';source.value=INITIAL.last_livery_folder||'';output.value=INITIAL.output_root||'';
if(INITIAL_SUITE.warning)statusEl.textContent=INITIAL_SUITE.warning;
function status(msg, err=false){{statusEl.textContent=msg;statusEl.className=err?'error':''}}
function log(msg){{if(!msg)return;logEl.textContent+=(logEl.textContent?String.fromCharCode(10):'')+msg;logEl.scrollTop=logEl.scrollHeight}}
async function chooseGame(){{try{{status(tr('chooseGame'));const r=await pywebview.api.choose_game_folder();if(r&&r.path)game.value=r.path;status(tr('ready'))}}catch(e){{log(String(e));status(tr('selectFailed'),true)}}}}
async function chooseLivery(){{try{{status(tr('chooseLivery'));const r=await pywebview.api.choose_livery_folder();if(r&&r.path){{source.value=r.path}}status(tr('ready'))}}catch(e){{log(String(e));status(tr('selectFailed'),true)}}}}
async function chooseOutput(){{try{{status(tr('chooseOutput'));const r=await pywebview.api.choose_output_folder();if(r&&r.path)output.value=r.path;status(tr('ready'))}}catch(e){{log(String(e));status(tr('selectFailed'),true)}}}}
async function registerIntegration(){{
  status(tr('registering'));
  try {{
    const r=await pywebview.api.register_integration();
    log((r&&r.output)||'');
    status(r&&r.ok?tr('registerDone'):(r&&r.message)||tr('registerFailed'),!(r&&r.ok));
  }} catch(e) {{log(String(e));status(tr('registerFailed'),true)}}
}}
async function unregisterIntegration(){{
  status(tr('unregistering'));
  try {{
    const r=await pywebview.api.unregister_integration();
    log((r&&r.output)||'');
    status(r&&r.ok?tr('unregisterDone'):(r&&r.message)||tr('unregisterFailed'),!(r&&r.ok));
  }} catch(e) {{log(String(e));status(tr('unregisterFailed'),true)}}
}}
async function openPreview(){{status(tr('opening'));const r=await pywebview.api.open_preview(source.value,game.value,output.value);if(r.source)source.value=r.source;log(r.output||'');status(r.ok?tr('openDone'):r.message,!r.ok)}}
window.addEventListener('beforeunload',()=>{{pywebview.api.save_settings(source.value,game.value,output.value)}});
</script></body></html>'''


def _work_area_logical() -> tuple[int, int]:
    """作業領域（タスクバーを除いた主の画面）の大きさ。pywebview と同じ、拡大率を掛ける前の値。分からなければ (0, 0)。"""
    if sys.platform != "win32":
        return 0, 0
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return 0, 0
        hdc = user32.GetDC(0)
        try:
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) or 96  # LOGPIXELSX
        finally:
            user32.ReleaseDC(0, hdc)
        scale = max(1.0, dpi / 96.0)
        return int((rect.right - rect.left) / scale), int((rect.bottom - rect.top) / scale)
    except Exception:  # noqa: BLE001
        return 0, 0


class LauncherApi:
    def __init__(self) -> None:
        # Keep the pywebview Window private.  pywebview introspects public
        # js_api members recursively; exposing the Window object causes it to
        # walk native WebView2/Accessibility COM objects from a worker thread.
        self._window: Any = None

    def fit_window(self, need_width: Any, need_height: Any, inner_width: Any, inner_height: Any) -> dict[str, Any]:
        """窓の大きさを、ページが測った中身の大きさ（CSS の px）に合わせる（2026-11-21）。

        枠の分は「今の窓の大きさ − ページの見える大きさ」で求める（pywebview の大きさは、拡大率を掛ける前の値で、
        CSS の px と同じ尺度）。作業領域（タスクバーを除いた画面）より大きくしない。差が小さければ変えない。
        """
        window = self._window
        if window is None:
            return {"ok": False, "message": "window is not ready"}
        try:
            numbers = [int(round(float(value))) for value in (need_width, need_height, inner_width, inner_height)]
        except (TypeError, ValueError):
            return {"ok": False, "message": "invalid size"}
        if min(numbers) <= 0 or max(numbers) > 20000:
            return {"ok": False, "message": "invalid size"}
        need_w, need_h, inner_w, inner_h = numbers
        try:
            outer_w, outer_h = int(window.width), int(window.height)
        except Exception as exc:  # noqa: BLE001  大きさを読めなければ変えない
            return {"ok": False, "message": str(exc)}
        target_w = need_w + max(0, outer_w - inner_w)
        target_h = need_h + max(0, outer_h - inner_h)
        work_w, work_h = _work_area_logical()
        if work_w > 0 and work_h > 0:
            target_w, target_h = min(target_w, work_w), min(target_h, work_h)
        if abs(target_w - outer_w) <= 2 and abs(target_h - outer_h) <= 2:
            return {"ok": True, "resized": False, "width": outer_w, "height": outer_h}
        try:
            window.resize(target_w, target_h)
        except Exception as exc:  # noqa: BLE001  変えられなければ今の大きさのまま
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "resized": True, "width": target_w, "height": target_h}

    @staticmethod
    def _folder_dialog_type(webview_module: Any) -> Any:
        file_dialog = getattr(webview_module, "FileDialog", None)
        if file_dialog is not None and hasattr(file_dialog, "FOLDER"):
            return file_dialog.FOLDER
        legacy = getattr(webview_module, "FOLDER_DIALOG", None)
        if legacy is not None:
            return legacy
        raise RuntimeError("pywebview folder dialog API is unavailable")

    def _folder(self, title: str, directory: str = "") -> str:
        if os.name == "nt":
            return _windows_folder_dialog(title, directory)

        import webview  # type: ignore
        kwargs: dict[str, Any] = {
            "dialog_type": self._folder_dialog_type(webview),
            "allow_multiple": False,
        }
        if directory:
            kwargs["directory"] = directory
        if self._window is None:
            raise RuntimeError("GUI window is not ready")
        result = self._window.create_file_dialog(**kwargs)
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            return str(result[0]) if result else ""
        return str(result)

    def choose_game_folder(self) -> dict[str, Any]:
        cfg = load_config()
        return {"path": self._folder("FH6フォルダー", cfg.get("game_folder", ""))}

    def choose_livery_folder(self) -> dict[str, Any]:
        cfg = load_config()
        selected = self._folder("Livery_* フォルダー", cfg.get("last_livery_folder", ""))
        path = str(prefer_current_livery_source(selected)) if selected else ""
        return {"path": path, "car_id": infer_car_id(path) if path else None}

    def choose_output_folder(self) -> dict[str, Any]:
        cfg = load_config()
        return {"path": self._folder("preview-cache", cfg.get("output_root", ""))}

    def _integration(self, unregister: bool = False) -> dict[str, Any]:
        # Old successful registration command is unchanged; only GUI exception
        # boundaries are hardened. A frozen EXE needs its separate URI-entry
        # dispatch to be verified on Windows before release approval.
        option = "--unregister-uri-scheme" if unregister else "--register-uri-scheme"
        try:
            code, output = run_bridge_capture(bridge_command(option))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            # pywebview serializes dict results reliably; raising leaves the
            # JS Promise rejected and the GUI stuck at 'registering'.
            verb = "解除" if unregister else "登録"
            return {"ok": False, "message": f"Organizer連携の{verb}に失敗しました ({type(exc).__name__})",
                    "output": str(exc)}
        return {
            "ok": code == 0,
            "message": "Organizer連携を解除しました" if unregister and code == 0 else (
                "Organizer連携を登録しました" if code == 0 else (
                    f"連携処理に失敗しました (exit {code}): " +
                    next((line.strip()[:280] for line in reversed(output.splitlines())
                          if any(word in line.casefold()
                                 for word in ("error", "exception", "failed", "not found"))),
                         (output.splitlines()[-1][:280] if output.splitlines() else "詳細はGUIログを参照"))
                )
            ),
            "output": output,
        }

    def register_integration(self) -> dict[str, Any]:
        return self._integration(False)

    def unregister_integration(self) -> dict[str, Any]:
        return self._integration(True)

    def save_suite_ui(self, language: str, theme: str) -> dict[str, Any]:
        """共有UI設定だけを保存。旧rM026設定やGameSaveを書き換えない。"""
        if language not in ('ja', 'en') or theme not in ('light', 'dark', 'system'):
            return {'ok': False, 'message': '未対応の表示設定です'}
        try:
            update_suite_settings({'ui': {'language': language, 'theme': theme}})
            return {'ok': True}
        except (OSError, ValueError, TypeError, TimeoutError) as exc:
            return {'ok': False, 'message': '共通表示設定を保存できません: ' + str(exc)}

    def save_standby(self, enabled: bool) -> dict[str, Any]:
        """Organizer の起動時に Viewer を温めておくか（共有の設定 viewer_standby_with_organizer。2026-11-21）。"""
        if not isinstance(enabled, bool):
            return {'ok': False, 'message': '未対応の設定です'}
        try:
            from organizer_preview_database import update_shared_settings
            update_shared_settings({window_reuse.STANDBY_SETTING: enabled})
            return {'ok': True}
        except (OSError, ValueError, TypeError) as exc:
            return {'ok': False, 'message': '設定を保存できません: ' + str(exc)}

    def save_settings(self, source: str, game_folder: str, output_root: str) -> dict[str, Any]:
        save_config({
            "game_folder": game_folder,
            "output_root": output_root,
            "last_livery_folder": source,
        })
        warning = _save_suite_paths(source, game_folder, output_root)
        return {'ok': not bool(warning), 'warning': warning}

    def open_preview(self, source_value: str, game_value: str, output_value: str) -> dict[str, Any]:
        try:
            source, car_id = validate_livery_source(source_value)
            game = validate_game_folder(game_value)
            output = Path(output_value).expanduser().resolve()
            output.mkdir(parents=True, exist_ok=True)
            save_config({
                "game_folder": str(game),
                "output_root": str(output),
                "last_livery_folder": str(source),
            })
            shared_warning = _save_suite_paths(str(source), str(game), str(output))
        except Exception as exc:
            return {"ok": False, "message": str(exc), "output": ""}

        command = preview_command(source, game, output, car_id, viewer_wheel_source())
        log = log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        handle = log.open("a", encoding="utf-8", errors="replace")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
                creationflags=_creationflags(),
            )
        finally:
            handle.close()

        # Do not touch the pywebview Window from a background thread.
        # The child Viewer owns its own lifecycle; the launcher only starts it.
        # This avoids WebView2 COM access from a non-UI thread.
        return {
            "ok": True,
            "source": str(source),
            "message": "3Dプレビューを起動しました",
            "output": subprocess.list2cmdline(command),
            "car_id": car_id,
            "shared_settings_warning": shared_warning,
        }


def main() -> int:
    try:
        import webview  # type: ignore
    except Exception as exc:
        raise SystemExit(f"pywebview is required for the Viewer GUI: {exc}")

    api = LauncherApi()
    window = webview.create_window(
        _window_title(),
        html=_launcher_html(load_config()),
        # 最初の大きさは目安（日本語・拡大率 100% で合わせた後の高さ 約 774 より少し大きい値。最初に中身が切れて
        # 見えず、起動直後に窓が大きく縮んで見えないように）。読み終わったら、ページが中身に合わせ直す（fit_window、2026-11-21）
        width=1040,
        height=780,
        min_size=(720, 480),
        js_api=api,
        text_select=True,
    )
    api._window = window
    from viewer_app_icon import start_options as icon_options
    webview.start(gui="edgechromium", debug=False, private_mode=True, **icon_options(webview.start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
