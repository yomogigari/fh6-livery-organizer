"""Windows版Viewerのネイティブ画像保存。

Browser downloadの完了をファイル保存完了と誤認しない。ユーザーが選んだパスへ
原子置換で書き込み、サイズ/SHA-256を照合して初めて成功を報告する。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from typing import Any, Callable

_FORMATS = {'jpeg': ('image/jpeg', '.jpg'), 'png': ('image/png', '.png')}
_MAX_CHUNK = 1024 * 1024  # base64文字列の長さ。小さな分割転送を強制。
_MAX_IMAGE = 512 * 1024 * 1024  # 6方向の大型PNGも許すが上限を明示。


def _choose_windows_file(name: str, fmt: str) -> str:
    """PS5.1対応、STAのWindows SaveFileDialog。空文字は利用者のキャンセル。"""
    if os.name != 'nt':
        raise RuntimeError('Windowsの保存ダイアログが利用できません')
    script = '\n'.join([
        '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)',
        'Add-Type -AssemblyName System.Windows.Forms',
        '$dlg = New-Object System.Windows.Forms.SaveFileDialog',
        '$dlg.Title = "Viewer 画像を保存"',
        '$dlg.FileName = $env:LO4FH6_CAPTURE_FILENAME',
        '$dlg.DefaultExt = $env:LO4FH6_CAPTURE_EXT',
        '$dlg.Filter = if ($env:LO4FH6_CAPTURE_EXT -eq "jpg") { "JPEG画像 (*.jpg)|*.jpg" } else { "PNG画像 (*.png)|*.png" }',
        '$dlg.AddExtension = $true',
        '$dlg.OverwritePrompt = $true',
        '$dlg.CheckPathExists = $true',
        '$dlg.InitialDirectory = [Environment]::GetFolderPath("MyPictures")',
        '$owner = New-Object System.Windows.Forms.Form',
        '$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen',
        '$owner.ShowInTaskbar = $false',
        '$owner.TopMost = $true',
        '$owner.Width = 1; $owner.Height = 1; $owner.Opacity = 0',
        'try {',
        ' $owner.Show(); $owner.Activate()',
        ' $decision = $dlg.ShowDialog($owner)',
        ' if ($decision -eq [System.Windows.Forms.DialogResult]::OK) {',
        '   [Console]::Write($dlg.FileName)',
        ' }',
        '} finally { $dlg.Dispose(); $owner.Close(); $owner.Dispose() }',
    ])
    env = os.environ.copy()
    env['LO4FH6_CAPTURE_FILENAME'] = name
    env['LO4FH6_CAPTURE_EXT'] = 'jpg' if fmt == 'jpeg' else 'png'
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    cp = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-STA',
                         '-ExecutionPolicy', 'Bypass', '-Command', script],
                        capture_output=True, text=True, encoding='utf-8', errors='replace',
                        env=env, creationflags=flags, check=False)
    if cp.returncode:
        raise RuntimeError('保存ダイアログを起動できません: ' + (cp.stderr or '')[:400])
    return cp.stdout.strip().lstrip('\ufeff')


class NativeImageExport:
    """1つのユーザー操作に限定した画像転送トランザクション。"""

    def __init__(self, chooser: Callable[[str, str], str] = _choose_windows_file) -> None:
        self._chooser = chooser
        self._lock = threading.RLock()
        self._active: dict[str, Any] | None = None

    def begin(self, name: str, fmt: str) -> dict[str, Any]:
        try:
            if not isinstance(name, str) or not name or len(name) > 180 or Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('保存ファイル名が不正です')
            if fmt not in _FORMATS or not name.lower().endswith(_FORMATS[fmt][1]):
                raise ValueError('保存形式と拡張子が一致しません')
            with self._lock:
                if self._active is not None:
                    raise RuntimeError('別の画像保存が進行中です')
                # OSダイアログは同じ操作の同期領域で呼び出す。
                chosen = self._chooser(name, fmt)
                if not chosen:
                    return {'ok': False, 'cancelled': True}
                target = Path(chosen)
                if not target.is_absolute() or target.suffix.lower() != _FORMATS[fmt][1]:
                    raise ValueError('画像の保存先・拡張子が不正です')
                if not target.parent.is_dir() or target.is_symlink() or target.is_dir():
                    raise ValueError('画像の保存先が安全ではありません')
                token = secrets.token_hex(16)
                temp = target.with_name('.' + target.name + '.lo4fh6-' + token + '.part')
                fp = temp.open('xb')
                self._active = {'token': token, 'target': target, 'temp': temp, 'fp': fp,
                                'size': 0, 'fmt': fmt, 'sha': hashlib.sha256(), 'head': b''}
                return {'ok': True, 'token': token}
        except (OSError, ValueError, RuntimeError) as e:
            return {'ok': False, 'error': str(e)}

    def append(self, token: str, data_b64: str) -> dict[str, Any]:
        with self._lock:
            s = self._active
            if not s or token != s['token']:
                return {'ok': False, 'error': '画像保存のセッションがありません'}
            try:
                if not isinstance(data_b64, str) or not data_b64 or len(data_b64) > _MAX_CHUNK:
                    raise ValueError('転送チャンクが不正です')
                part = base64.b64decode(data_b64, validate=True)
                if s['size'] + len(part) > _MAX_IMAGE:
                    raise ValueError('画像ファイルが上限512MiBを超えました')
                s['head'] = (s['head'] + part)[:8]
                s['fp'].write(part)
                s['sha'].update(part)
                s['size'] += len(part)
                return {'ok': True, 'bytes': s['size']}
            except (OSError, ValueError, binascii.Error) as e:
                self._abort_locked()
                return {'ok': False, 'error': str(e)}

    def finish(self, token: str, expected_bytes: int) -> dict[str, Any]:
        with self._lock:
            s = self._active
            if not s or s['token'] != token:
                return {'ok': False, 'error': '画像保存のセッションがありません'}
            try:
                magic = s['head']
                match = magic.startswith(b'\xff\xd8\xff') if s['fmt'] == 'jpeg' else magic.startswith(b'\x89PNG\r\n\x1a\n')
                if not match or not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes <= 0 or s['size'] != expected_bytes:
                    raise ValueError('保存画像の形式・サイズが一致しません')
                fp = s['fp']
                fp.flush(); os.fsync(fp.fileno()); fp.close()
                if s['temp'].stat().st_size != expected_bytes:
                    raise OSError('保存ファイルの実バイト数が不一致です')
                # 上書きはダイアログで利用者が確定したパスのみ。
                os.replace(s['temp'], s['target'])
                result = {'ok': True, 'path': str(s['target']),
                          'bytes': expected_bytes, 'sha256': s['sha'].hexdigest()}
                self._active = None
                return result
            except (OSError, ValueError) as e:
                self._abort_locked()
                return {'ok': False, 'error': str(e)}

    def abort(self, token: str) -> dict[str, Any]:
        with self._lock:
            if self._active and self._active['token'] == token:
                self._abort_locked()
                return {'ok': True}
            return {'ok': False, 'error': '画像保存のセッションがありません'}

    def _abort_locked(self) -> None:
        s = self._active
        self._active = None
        if s is not None:
            try: s['fp'].close()
            except OSError: pass
            try: s['temp'].unlink(missing_ok=True)
            except OSError: pass
