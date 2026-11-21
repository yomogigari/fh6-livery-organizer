"""タイヤの swatch を PNG にした結果を、別のプロセスでも使い回す（2026-11-21）。

標準タイヤの GLB を作るとき、Textures.zip の swatch（タイヤの複合の画像・凹凸の画像）を復号して PNG に書く（1 台
約 0.5 秒。PNG を書くのが大半）。タイヤの種類は限られていて、ほとんどの車は前に見た車と同じ swatch を使うのに、
Viewer を開き直すたびに同じ PNG を書き直していた。書いた PNG は、GLB の差分の共有の置き場（wheel-tire/Shared-Blobs、
中身の SHA-256 の名前）に入る。ここでは、ZIP の項目（名前・CRC・大きさ）から、その PNG と付随の値を引く小さな索引
（wheel-tire/Swatch-PNG-Index）を残し、次からは PNG を読むだけにする（項目の中身の展開もしない）。
- 共有の置き場の PNG は、大きさと SHA-256 を確かめてから使う（glb_delta._get_shared）。無い・壊れている・索引が
  読めないときは、今までどおり作り、置き直す。
- 索引の鍵には、PNG の圧縮の強さと、この仕組みの版を入れる（変われば作り直す）。
- 使うのは、swatch_png_store の範囲の中（標準タイヤの GLB を作る所）だけ。外では毎回作る。
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path

from .glb_delta import GlbDeltaError, _get_shared, _put_shared
from .png_settings import PNG_COMPRESS_LEVEL

REVISION = 1
INDEX_DIR = "Swatch-PNG-Index"
_STORE: contextvars.ContextVar = contextvars.ContextVar("lo4fh6_swatch_png_store", default=None)


@contextlib.contextmanager
def swatch_png_store(shared_dir: Path, index_dir: Path):
    """この範囲の中では、swatch の PNG を共有の置き場と索引から使い回す。"""
    token = _STORE.set((Path(shared_dir), Path(index_dir)))
    try:
        yield
    finally:
        _STORE.reset(token)


def _key(kind: str, info: zipfile.ZipInfo) -> str:
    text = json.dumps([REVISION, PNG_COMPRESS_LEVEL, kind, info.filename, int(info.CRC), int(info.file_size),
                       int(info.compress_size), int(info.compress_type)], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def remembered_swatch_png(kind: str, info: zipfile.ZipInfo, compute: Callable[[], tuple[bytes, dict]]) -> tuple[bytes, dict]:
    """kind と ZIP の項目が同じなら、前に作った（PNG, 付随の値）を返す。無ければ compute して置く（失敗は覚えない）。"""
    store = _STORE.get()
    if store is None:
        return compute()
    shared, index = store
    entry = index / f"{_key(kind, info)}.json"
    try:
        record = json.loads(entry.read_text(encoding="utf-8"))
        png = _get_shared(shared, record["png_sha256"], int(record["png_bytes"]))
        meta = record["meta"]
        if isinstance(meta, dict):
            return png, dict(meta)
    except (OSError, ValueError, KeyError, TypeError, GlbDeltaError):
        pass
    png, meta = compute()
    try:
        digest = _put_shared(shared, png)
        index.mkdir(parents=True, exist_ok=True)
        partial = entry.with_name(f"{entry.name}.{os.getpid()}.partial")
        partial.write_text(json.dumps({"png_sha256": digest, "png_bytes": len(png), "meta": meta}, ensure_ascii=False),
                           encoding="utf-8")
        partial.replace(entry)
    except (OSError, TypeError, ValueError):
        pass
    return png, meta
