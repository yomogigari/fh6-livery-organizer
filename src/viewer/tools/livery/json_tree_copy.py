"""JSON から読んだ木（辞書・一覧・文字列・数・真偽・None）の速い深い複製（2026-11-19）。

copy.deepcopy と同じ結果になる：
- 辞書と一覧は新しく作り、文字列・数・真偽・None はそのまま使う（deepcopy も同じものを返す）。
- 同じ辞書・一覧を指す場所の共有も同じに保つ（複製の対応を id で覚える。GLB の中身は旧名の別名の鍵が
  同じ値を指していて、タイヤの GLB で約 1,100 か所ある）。
- それ以外の型は copy.deepcopy に任せる（同じ対応の表を渡す）。
タイヤの組み立てで GLB の中身まるごとを複製するのに使う（deepcopy の約 3 倍速い）。
"""
from __future__ import annotations

import copy
import marshal
from typing import Any

_ATOMS = (str, int, float, bool)


def json_tree_deepcopy(value: Any, memo: dict[int, Any] | None = None) -> Any:
    if memo is None:
        # まず marshal で書き出して読み戻す（C の速さ。2026-11-20）。marshal は、2 か所以上から指される辞書・一覧を
        # 参照として書くので、読み戻した木でも同じ場所の共有になる。辞書の並び・数の型・浮動小数のビットも同じ。
        # marshal で書けない型が混ざっていれば、下の今までの複製に任せる。
        try:
            return marshal.loads(marshal.dumps(value))
        except ValueError:
            pass
        memo = {}
    return _copy(value, memo)


def _copy(value: Any, memo: dict[int, Any]) -> Any:
    kind = type(value)
    if kind in _ATOMS or value is None:
        return value
    if kind is dict:
        found = memo.get(id(value))
        if found is not None:
            return found
        out: dict = {}
        memo[id(value)] = out
        for key, item in value.items():
            out[key] = item if (type(item) in _ATOMS or item is None) else _copy(item, memo)
        return out
    if kind is list:
        found = memo.get(id(value))
        if found is not None:
            return found
        out_list: list = []
        memo[id(value)] = out_list
        out_list.extend(item if (type(item) in _ATOMS or item is None) else _copy(item, memo) for item in value)
        return out_list
    return copy.deepcopy(value, memo)
