"""Organizer / Viewer / Navigator Bridge共通の設定保存。

ゲーム原本・GameSaveは読み取り専用のままとし、独立のAPPDATA内JSONへ
UI・各パスだけを保存する。既存navigator-bridge-settings.jsonやViewer設定は上書きしない。
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Mapping

SCHEMA = 'lo4fh6.desktop_suite.settings.v1'
CONFIG_NAME = 'desktop-suite-settings.json'
SUITE_DIR = 'Livery-Organizer-for-FH6'
MAX_BYTES = 256 * 1024
VALID_THEMES = frozenset({'system', 'light', 'dark'})
# 3 つのツールで共有するフォルダー・ファイル（2026-11-18：Organizer・Navigator Bridge と共有するため save_folder を追加）。
# game_folder：FH6 のフォルダー、save_folder：セーブデータ（ContainersRoot）のフォルダー、gamedb_file：GameDB。
# livery_folder・output_directory は Viewer が使う（出力先はツールごとに用途が違うので、Organizer は自分の設定に持つ）。
SHARED_PATH_KEYS = frozenset({'game_folder', 'save_folder', 'livery_folder', 'gamedb_file', 'output_directory'})
APP_KEYS = frozenset({'organizer', 'viewer', 'navigator_bridge'})
_LANG_RE = re.compile(r'^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*$')

DEFAULTS = {
    'schema': SCHEMA,
    'ui': {'language': 'ja', 'theme': 'system'},
    'paths': {key: '' for key in sorted(SHARED_PATH_KEYS)},
    'apps': {key: {} for key in sorted(APP_KEYS)},
}


def settings_path(*, appdata: str | Path | None = None) -> Path:
    """既存のBridge設定と同じAPPDATA親フォルダーの別ファイルを使う。"""
    base = appdata if appdata is not None else os.environ.get('APPDATA')
    if base:
        return Path(base) / SUITE_DIR / CONFIG_NAME
    return Path.home() / '.livery-organizer-for-fh6' / CONFIG_NAME


def _validate_patch(patch: Mapping) -> None:
    if not isinstance(patch, dict):
        raise ValueError('設定変更は辞書で指定してください')
    if not patch or set(patch) - {'ui', 'paths', 'apps'}:
        raise ValueError('共有設定の変更対象が不正です')
    for group, obj in patch.items():
        if not isinstance(obj, dict):
            raise ValueError(f'{group} は辞書で指定してください')
        if group == 'ui':
            if set(obj) - {'language', 'theme'}:
                raise ValueError('未対応のUI設定キー')
            if 'language' in obj and (not isinstance(obj['language'], str)
                                      or not _LANG_RE.fullmatch(obj['language'])):
                raise ValueError('言語コードが不正です')
            if 'theme' in obj and obj['theme'] not in VALID_THEMES:
                raise ValueError('テーマ指定が不正です')
        elif group == 'paths':
            if set(obj) - SHARED_PATH_KEYS:
                raise ValueError('未対応の共有パスキー')
            if any(not isinstance(v, str) or '\x00' in v or len(v) > 4096 for v in obj.values()):
                raise ValueError('共有パスの文字列が不正です')
        elif group == 'apps':
            if set(obj) - APP_KEYS:
                raise ValueError('未対応のアプリ名')
            if any(not isinstance(v, dict) for v in obj.values()):
                raise ValueError('アプリ個別設定は辞書で指定してください')
            # rM026の容量制限付き派生キャッシュの研究設定。通常は無効。
            if 'viewer' in obj:
                setting = obj['viewer']
                if 'cache_budget_mib' in setting:
                    n = setting['cache_budget_mib']
                    if type(n) is not int or not 16 <= n <= 1024:
                        raise ValueError('Viewerキャッシュ予算は16～1024MiBです')
                if 'atlas_cache_enabled' in setting and type(setting['atlas_cache_enabled']) is not bool:
                    raise ValueError('Viewerのキャッシュ有効化は真偽値です')
                if 'wheel_source' in setting and setting['wheel_source'] not in ('proxy', 'stock', 'game-fit', 'source-verified'):
                    raise ValueError('未対応の車輪表示モードです')
                for option in ('source_material_enabled', 'neutral_livery_grade_enabled'):
                    if option in setting and type(setting[option]) is not bool:
                        raise ValueError('Viewerの原本材質・色補正設定は真偽値です')


def _read_json(path: Path) -> dict:
    if not path.exists():
        return deepcopy(DEFAULTS)
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('共有設定ファイルが大きすぎます')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('共有設定JSONを読み込めません。内容を保全して確認してください') from exc
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        raise ValueError('共有設定のschemaが不正です。旧データは上書きしません')
    result = deepcopy(DEFAULTS)
    for group in ('ui', 'paths', 'apps'):
        stored = data.get(group, {})
        if not isinstance(stored, dict):
            raise ValueError(f'共有設定の{group}が不正です')
        result[group].update(stored)
    _validate_patch({k: {x: v for x, v in result[k].items() if x in (
        {'language', 'theme'} if k == 'ui' else SHARED_PATH_KEYS if k == 'paths' else APP_KEYS
    )} for k in ('ui', 'paths', 'apps')})
    # 古い設定ファイルに未知のキーがあれば黙って削除しない。
    for k, v in data.items():
        if k not in result:
            result[k] = v
    return result


def load_settings(*, path: Path | None = None) -> dict:
    return _read_json(path or settings_path())


@contextmanager
def _lock_config(path: Path, *, timeout: float = 5.0):
    """クロスプロセスでの同時保存による上書き競合を防ぐ。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + '.lock')
    with lock_path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + timeout
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('共有設定が別のアプリから更新中です')
                    time.sleep(.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_settings(patch: Mapping, *, path: Path | None = None) -> dict:
    """関連キーのみ更新。未知のキー・他アプリの設定は残して原子的に保存する。"""
    _validate_patch(patch)
    target = path or settings_path()
    with _lock_config(target):
        current = _read_json(target)
        for group, updates in patch.items():
            for key, value in updates.items():
                if group == 'apps':
                    current[group][key].update(value)
                else:
                    current[group][key] = value
        encoded = (json.dumps(current, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('共有設定が容量上限を超えました')
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent,
                                             prefix='.desktop-suite-', suffix='.tmp', delete=False) as tmp:
                temp_name = tmp.name
                tmp.write(encoded)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_name, target)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    return deepcopy(current)


def viewer_appearance_options(settings: dict | None = None) -> dict[str, bool]:
    """通常の製品Viewerでは原本材質・色補正中立化を必ずONにする。

    旧設定にOFFが残っていても、保存データを変更せず標準表示へ影響させない。
    明示的なOFFによる研究比較はBridge側の開発用環境変数でのみ行う。
    """
    return {'source_material_enabled': True, 'neutral_livery_grade_enabled': True}

def viewer_wheel_source(settings: dict | None = None) -> str:
    """通常Viewerの11/07受入済みWheel/Tireは自動接続。

    以前の設定ファイルのwheel_source=proxy/stockはユーザーデータとして保全するが、
    既確認機能を無効にする通常動作には反映しない。原本不一致は既存Bridgeで明示停止。
    詳細比較用の個別モードは専用診断CLIでのみ指定できる。
    """
    return 'source-verified'
