"""タイヤの原本の判定を、同じプロセスの中で覚える（2026-11-19）。

Viewer の窓の使い回しと撮影の係では、同じプロセスで同じ車（同じタイヤ）のペイントを続けて準備する。
そのたびに、原本のタイヤの ZIP・Materials.zip・Textures.zip・シェーダーを読み直して、ペイントに依らない
同じ判定（適合の判定・側面の文字の報告・タイヤの ZIP の場所）をしていた（1 件あたり約 0.45 秒）。

- 鍵は、判定が読む原本のファイルの場所・大きさ・更新日時（タイヤの ZIP と、_library の Materials.zip・
  Textures.zip・shaders.zip・shaders の中のファイル）と、判定の引数。どれかが変われば判定し直す。
- 覚えるのは、原本のタイヤの ZIP が実在し、判定が最後まで終わった結果だけ（例外は覚えない）。辞書などは写しを返し、呼び出し側が変えても
  覚えた結果は変わらない。
- プロセスが終われば消える（ディスクには書かない）。
"""
from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")
_MEMO: dict[tuple, Any] = {}
_LOCK = threading.Lock()
_LIMIT = 256


def file_identity(path: Path | str) -> tuple:
    """ファイルの場所・大きさ・更新日時・機器と番号。読めないときは場所だけ（無いことも鍵に入る）。

    2026-11-20：場所は Path.resolve()（Windows ではファイルを開いて閉じ、さらに stat する）をやめて
    os.path.abspath（大文字・小文字をそろえる）にし、どのファイルかは stat の機器と番号で見分ける。
    2 つ目が大きさ（exists が見る）なのは以前と同じ。
    """
    path = Path(path)
    try:
        stat = path.stat()
        return (os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino)
    except OSError:
        return (str(path), None, None)


def library_identity(library: Path | str) -> tuple:
    """_library の材質・画像・シェーダーの情報（タイヤの判定が読むもの）。"""
    library = Path(library)
    shaders = library / "shaders"
    shader_files: list[tuple] = []
    try:
        with os.scandir(shaders) as entries:
            for entry in entries:
                if entry.is_file():
                    stat = entry.stat()
                    shader_files.append((entry.name, stat.st_size, stat.st_mtime_ns))
    except OSError:
        pass
    return (file_identity(library / "Materials.zip"), file_identity(library / "Textures.zip"),
            file_identity(library / "shaders.zip"), tuple(sorted(shader_files)))


def exists(identity: tuple) -> bool:
    """file_identity の結果が、実在するファイル（大きさが読めた）か。"""
    return identity[1] is not None


def remembered(kind: str, key: tuple, compute: Callable[[], T], *, enabled: bool = True) -> T:
    """同じ kind・key で最後まで終わった結果があれば写しを返す。無ければ compute して覚える。

    enabled が偽（判定の元の原本のファイルが無いときなど）は、覚えずに毎回 compute する。
    """
    if not enabled:
        return compute()
    full = (kind, key)
    with _LOCK:
        if full in _MEMO:
            return copy.deepcopy(_MEMO[full])
    value = compute()
    with _LOCK:
        if len(_MEMO) >= _LIMIT:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[full] = copy.deepcopy(value)
    return value


def clear() -> None:
    with _LOCK:
        _MEMO.clear()
