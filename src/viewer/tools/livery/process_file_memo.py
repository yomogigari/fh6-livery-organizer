"""同じプロセスの中で、ファイルから計算した結果を覚える（2026-11-20）。

Viewer の窓の使い回しでは、同じプロセスで同じ車のペイントを続けて準備する。そのたびに、ペイントに依らない
同じ計算（車体の GLB の目次の解析と SHA-256・部品の選択肢の一覧・材質の解析・解読済みのデザインの読み込み）を
していた（4212 で 1 件あたり約 0.4 秒）。

- 鍵は、計算が読むファイルの識別（場所・大きさ・更新日時）と、計算の引数。ファイルが変われば大きさか更新日時が
  変わるので、計算し直す。ファイルが無いときは覚えない（毎回計算する）。
- 覚えるのは最後まで終わった結果だけ（例外は覚えない）。
- 返すのは写し（呼び出し側が変えても、覚えた結果は変わらない）。copy="deep" は copy.deepcopy、
  copy="marshal" は marshal で持って毎回作り直す（大きな JSON 由来の値。JSON の解析の約 3 倍速い）、
  copy="none" は変えられない値（文字列・数・それらのタプル）だけに使う。
- 種類ごとに最近の数件だけを覚える。プロセスが終われば消える（ディスクには書かない）。
"""
from __future__ import annotations

import copy as _copy
import marshal
import os
import threading
from stat import S_ISREG
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable, Iterable, TypeVar

T = TypeVar("T")
_LOCK = threading.Lock()
_MEMO: dict[str, OrderedDict] = {}


def file_identity(path: Path | str) -> tuple | None:
    """ファイルの場所・機器と番号・大きさ・更新日時。ファイルでない・読めないときは None。

    2026-11-20：以前は場所を Path.resolve() で求めていた（Windows ではファイルを開いて閉じ、さらに stat する。
    差し替えの準備で数百回）。場所はファイルシステムに触れない os.path.abspath（大文字・小文字をそろえる）にし、
    どのファイルかは stat の機器と番号（st_dev・st_ino。リンクを辿った先のファイル）で見分ける。
    同じプロセスの中の鍵にだけ使う（ディスクには書かない）。
    """
    try:
        target = Path(path)
        stat = target.stat()
        # Path.is_file() と同じ判定を、読んだ stat で行う（もう一度問い合わせない。2026-11-20）。
        if not S_ISREG(stat.st_mode):
            return None
        return (os.path.normcase(os.path.abspath(target)), stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns)
    except (OSError, ValueError):
        return None


def _store(value: Any, mode: str) -> Any:
    if mode == "deep":
        return _copy.deepcopy(value)
    if mode == "marshal":
        return marshal.dumps(value)
    if mode == "none":
        return value
    raise ValueError(f"unknown copy mode: {mode}")


def _restore(stored: Any, mode: str) -> Any:
    if mode == "deep":
        return _copy.deepcopy(stored)
    if mode == "marshal":
        return marshal.loads(stored)
    return stored


def remembered(kind: str, files: Iterable[Path | str], key: Hashable, compute: Callable[[], T], *,
               copy: str = "deep", limit: int = 8, keep: Callable[[T], bool] | None = None) -> T:
    """files の識別と key が同じで最後まで終わった結果があれば写しを返す。無ければ compute して覚える。

    files のどれかが無い（ファイルでない）ときは、覚えずに毎回 compute する。
    keep を渡すと、keep(結果) が真の結果だけを覚える（一時的な読み取りの失敗を表す結果などを覚えない）。
    識別は compute の前に読む（計算の途中でファイルが変わっても、古い識別に新しい結果が付くだけで、次からは外れる）。
    """
    identities = tuple(file_identity(path) for path in files)
    if any(identity is None for identity in identities):
        return compute()
    full = (identities, key)
    with _LOCK:
        bucket = _MEMO.get(kind)
        if bucket is not None and full in bucket:
            bucket.move_to_end(full)
            stored = bucket[full]
            return _restore(stored, copy)
    value = compute()
    if keep is not None and not keep(value):
        return value
    stored = _store(value, copy)
    with _LOCK:
        bucket = _MEMO.setdefault(kind, OrderedDict())
        bucket[full] = stored
        bucket.move_to_end(full)
        while len(bucket) > max(1, limit):
            bucket.popitem(last=False)
    return value


def put(kind: str, files: Iterable[Path | str], key: Hashable, value: Any, *, copy: str = "deep",
        limit: int = 8) -> None:
    """計算済みの値を覚えさせる（書いた直後のファイルを、次に読む所が計算し直さないように）。"""
    identities = tuple(file_identity(path) for path in files)
    if any(identity is None for identity in identities):
        return
    stored = _store(value, copy)
    with _LOCK:
        bucket = _MEMO.setdefault(kind, OrderedDict())
        bucket[(identities, key)] = stored
        bucket.move_to_end((identities, key))
        while len(bucket) > max(1, limit):
            bucket.popitem(last=False)


def clear(kind: str | None = None) -> None:
    with _LOCK:
        if kind is None:
            _MEMO.clear()
        else:
            _MEMO.pop(kind, None)
