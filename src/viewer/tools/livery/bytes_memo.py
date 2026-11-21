"""タイヤの段で、同じ GLB のバイト列の SHA-256 と、書いたばかりのファイルの中身を、同じプロセスの中で覚える
（2026-11-21、FH6 に近づける案 ⑤ の A）。

- タイヤの段では、同じ 25 MB の GLB の SHA-256 を、確かめ・証拠・差分・置き場で何度も求めていた（1 回 約 15 ms）。
  sha256_digest は、書き換えられない bytes のオブジェクトだけを覚え、同じオブジェクト（is）のときだけ覚えた値を使う。
  中身が同じでも別のオブジェクトなら求め直す（取り違えない）。bytearray などの書き換えられる物は覚えない。
- 書いたばかりの GLB（途中の GLB）を次の段がファイルから読み直していた。remember_file で覚えた物は、read_file が、
  場所・大きさ・更新日時が同じときだけ、同じバイト列を返す（違えばファイルから読む）。
- 覚えるのは直近の数件だけ。release でまとめて捨てる（Viewer は窓を閉じても残るので、タイヤの段の後に捨てる）。
"""
from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from pathlib import Path

SHA_LIMIT = 4
FILE_LIMIT = 2
SMALL_BYTES = 1 << 20  # これより小さい物は覚えない（求め直す方が速い）
_LOCK = threading.Lock()
_SHA_BY_OBJECT: "OrderedDict[int, tuple[bytes, bytes]]" = OrderedDict()
_FILES: "OrderedDict[str, tuple[tuple[int, int, int, int], bytes]]" = OrderedDict()


def sha256_digest(data) -> bytes:
    """data の SHA-256（digest）。大きな bytes のオブジェクトは、同じオブジェクトなら覚えた値を使う。"""
    if type(data) is not bytes or len(data) < SMALL_BYTES:
        return hashlib.sha256(data).digest()
    key = id(data)
    with _LOCK:
        found = _SHA_BY_OBJECT.get(key)
        if found is not None and found[0] is data:
            _SHA_BY_OBJECT.move_to_end(key)
            return found[1]
    value = hashlib.sha256(data).digest()
    with _LOCK:
        _SHA_BY_OBJECT[key] = (data, value)
        _SHA_BY_OBJECT.move_to_end(key)
        while len(_SHA_BY_OBJECT) > SHA_LIMIT:
            _SHA_BY_OBJECT.popitem(last=False)
    return value


def sha256_hex(data) -> str:
    return sha256_digest(data).hex()


def _identity(path: Path) -> tuple[str, tuple[int, int, int, int]] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return os.path.normcase(os.path.abspath(path)), (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def remember_file(path: Path, data: bytes) -> None:
    """書いたばかりのファイル（path）の中身として data を覚える（大きさが違えば覚えない）。"""
    if type(data) is not bytes or len(data) < SMALL_BYTES:
        return
    identity = _identity(Path(path))
    if identity is None or identity[1][2] != len(data):
        return
    with _LOCK:
        _FILES[identity[0]] = (identity[1], data)
        _FILES.move_to_end(identity[0])
        while len(_FILES) > FILE_LIMIT:
            _FILES.popitem(last=False)


def moved(old: Path, new: Path) -> None:
    """覚えたファイルの名前を付け替える（一時の名前に書いてから置き換えたとき）。中身の識別が同じときだけ。"""
    old_key = os.path.normcase(os.path.abspath(old))
    identity = _identity(Path(new))
    with _LOCK:
        found = _FILES.pop(old_key, None)
        if found is None or identity is None or found[0][2:] != identity[1][2:]:
            return
        _FILES[identity[0]] = (identity[1], found[1])
        while len(_FILES) > FILE_LIMIT:
            _FILES.popitem(last=False)


def read_file(path: Path) -> bytes:
    """ファイルの中身。remember_file で覚えた物と場所・大きさ・更新日時が同じなら、覚えたバイト列を返す。"""
    identity = _identity(Path(path))
    if identity is not None:
        with _LOCK:
            found = _FILES.get(identity[0])
        if found is not None and found[0] == identity[1]:
            return found[1]
    return Path(path).read_bytes()


def release() -> None:
    """覚えた物を捨てる。"""
    with _LOCK:
        _SHA_BY_OBJECT.clear()
        _FILES.clear()
