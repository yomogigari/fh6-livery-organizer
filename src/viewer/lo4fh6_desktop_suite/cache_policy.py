"""製品候補向け、画質非変更の派生アトラスキャッシュ容量ポリシー。

初回リリースでは本モジュールは読み取り専用。元のゲーム/セーブ/旧r485の
キャッシュは対象にせず、描画契約の署名付きキーが確定するまでGPU再利用をONにしない。
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

MIB = 1024 * 1024
DEFAULT_BUDGET_MIB = 256
MIN_BUDGET_MIB = 16
MAX_BUDGET_MIB = 1024
DERIVED_SUBDIR = Path('LO4FH6') / 'derived-cache' / 'gpu-atlas'
_ENTRY = re.compile(r'[0-9a-f]{64}\.png\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\.sha256\Z')


@dataclass(frozen=True)
class CachePolicy:
    """原本の画質・保存済みStageを変更しない、将来の派生キャッシュ容量上限。"""
    budget_mib: int = DEFAULT_BUDGET_MIB
    enabled: bool = False

    def __post_init__(self):
        if type(self.budget_mib) is not int or not MIN_BUDGET_MIB <= self.budget_mib <= MAX_BUDGET_MIB:
            raise ValueError('GPUアトラスキャッシュ容量は16～1024MiBで指定してください')
        if type(self.enabled) is not bool:
            raise ValueError('キャッシュの有効化は明示的な真偽値で指定してください')

    @property
    def budget_bytes(self) -> int:
        return self.budget_mib * MIB


def dedicated_root(*, localappdata: str | Path | None = None) -> Path:
    """専用の派生ファイル保存場所。実ゲームやGameSaveの所在には依存しない。"""
    base = localappdata if localappdata is not None else os.environ.get('LOCALAPPDATA')
    if not base:
        base = Path.home() / '.cache'
    return Path(base) / DERIVED_SUBDIR


def readonly_inventory(root: Path, policy: CachePolicy) -> dict:
    """ファイルを開かず・削除せず、既存派生キャッシュの容量を試算する。

    専用ルートの単一ファイル名とシンボリックリンクを厳密に区別する。
    元ファイルのSHA照合は行わないため、これだけではキャッシュを使用しない。
    """
    root = Path(root)
    if tuple(root.parts[-3:]) != tuple(DERIVED_SUBDIR.parts):
        raise ValueError('指定できるのはLO4FH6の派生GPUアトラス専用ルートのみです')
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError('不正なキャッシュルートです')
    for parent in root.parents:
        if parent.is_symlink():
            raise ValueError('親ディレクトリがシンボリックリンクです')
    result = {'schema':'lo4fh6.derived-atlas-readonly-budget.v1',
              'root_present':root.is_dir(), 'cache_enabled':policy.enabled,
              'budget_bytes':policy.budget_bytes, 'entries':0, 'png_bytes':0,
              'sidecar_bytes':0, 'other_entries':0, 'symlink_entries':0,
              'managed_bytes':0, 'bytes_over_budget':0,
              'read_only':True, 'pixel_or_gpu_parity_verified':False}
    if not root.is_dir():
        return result
    for entry in root.iterdir():
        if entry.is_symlink():
            result['symlink_entries'] += 1
            continue
        mode = entry.stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            result['other_entries'] += 1
            continue
        if _ENTRY.fullmatch(entry.name):
            result['entries'] += 1
            result['png_bytes'] += entry.stat().st_size
        elif _DIGEST.fullmatch(entry.name):
            result['sidecar_bytes'] += entry.stat().st_size
        elif entry.name == '.atlas-cache.lock':
            # 既存rM026由来の管理済みバックエンドを保護する。
            pass
        else:
            result['other_entries'] += 1
    result['managed_bytes'] = result['png_bytes'] + result['sidecar_bytes']
    result['bytes_over_budget'] = max(0, result['managed_bytes']-policy.budget_bytes)
    return result
