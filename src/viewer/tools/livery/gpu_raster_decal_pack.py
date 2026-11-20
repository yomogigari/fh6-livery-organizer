"""FH6原本Decals.zipをWebGL2向けの一時RGBA入力へ変換する（描画は行わない）。

このパックはローカル研究セッション内のみで使用し、配布物・GitHubには同梱しない。
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import re
import sqlite3
import struct
from pathlib import Path
from typing import Any

from fh_livery_preview_core.raster_decals import FH6RasterDecalResolver

MAGIC = b"LO4GRD01"
VERSION = 1
HEADER = struct.Struct("<8sII")
ENTRY = struct.Struct("<IIII")

DECAL_DATABASE_CONTRACT = "fh6-gamedb-livery-decals-source-path-v1"
# ゲームに無いステッカーの代わりに入れる、完全に透明な 1x1 の画像（描画は「その層を飛ばす」のと同じ）。
OMITTED_PLACEHOLDER_SIZE = (1, 1)
OMITTED_PLACEHOLDER_RGBA = bytes(4)
OMISSION_POLICY = "missing-from-game-transparent-placeholder-v1"
_DECAL_PATH = re.compile(r"GAME:\\Media\\Livery\\Decals\\decal([0-9]+)\.modelbin\Z", re.I)


def _gamedb_decal_asset_ids(database: Path | str, ids: list[int], *,
                            allow_unregistered: bool = False) -> tuple[dict[int, int], str]:
    """GameDBのRaster IDと原本Decalファイル番号は別の名前空間として解決する。

    allow_unregistered が真なら、GameDB に登録の無い Raster ID は止めずに結果から外す（呼び出し側が省く）。
    """
    path = Path(database).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"FH6 GameDBが見つかりません: {path}")
    # 対応表と GameDB 全体の SHA-256 は GameDB のファイルだけで決まるので、同じプロセスの中でファイルの識別
    # （場所・機器と番号・大きさ・更新日時）ごとに覚える（2026-11-20。ペイントのたびに表を全部読み、16 MB の
    # SHA-256 を求めていた）。番号ごとの引き当てと、その例外は毎回行う。
    from .process_file_memo import remembered
    mapping, digest_hex = remembered("gamedb-livery-decals", [path], None, lambda: _gamedb_decal_mapping(path),
                                     copy="marshal", limit=4)
    resolved: dict[int, int] = {}
    for source_id in ids:
        if source_id not in mapping:
            if allow_unregistered:
                continue
            raise ValueError(f"GameDBのLivery_DecalsにRaster ID {source_id} の登録がありません")
        resolved[source_id] = mapping[source_id]
    return resolved, digest_hex


def _gamedb_decal_mapping(path: Path) -> tuple[dict[int, int], str]:
    """GameDB の Livery_Decals の対応表（Raster ID → 原本の Decal の番号）と、GameDB 全体の SHA-256。"""
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ValueError("Raster参照GameDBは復号済みSQLiteである必要があります")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute('SELECT ID, Filename FROM "Livery_Decals"').fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError("GameDBのLivery_Decals対応表を読み取れません") from exc
    mapping: dict[int, int] = {}
    for raw_id, filename in rows:
        if type(raw_id) is not int or raw_id <= 0 or not isinstance(filename, str):
            raise ValueError("GameDBのLivery_Decalsに不正なID・パスがあります")
        matched = _DECAL_PATH.fullmatch(filename.replace("/", "\\"))
        if matched is None or int(matched.group(1)) <= 0:
            raise ValueError(f"GameDBのLivery_Decals ID {raw_id} の原本パスが不正です")
        asset_id = int(matched.group(1))
        if raw_id in mapping and mapping[raw_id] != asset_id:
            raise ValueError(f"GameDBのLivery_Decals ID {raw_id} が重複しています")
        mapping[raw_id] = asset_id
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return mapping, digest.hexdigest()



def _member_present(resolver, asset_id: int) -> bool:
    """Decals.zip にその番号のファイルがあるか（調べる手段が無い解決器は「ある」とみなす）。"""
    finder = getattr(resolver, "member_name", None)
    return True if finder is None else finder(asset_id) is not None


def build_gpu_raster_decal_pack(
    archive: Path | str, raster_ids: set[int] | list[int] | tuple[int, ...], *,
    gamedb_path: Path | str | None = None,
    omit_missing: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """参照したIDだけを解決。失敗時は黙って省略せず例外にする。

    CPUは原本テクスチャのBC7復号だけ担当し、形状変換・積層・ペイントはGPU。

    omit_missing が真なら、ゲームに無いステッカー（GameDB に登録が無い・Decals.zip にファイルが無い）だけは
    止めずに、完全に透明な 1x1 の画像を入れて記録する（summary の omitted。2026-11-18 利用者の決定。
    参照製品も無いステッカーの層を飛ばす）。ファイルがあるのに解読できないものは、今までどおり止める。
    """
    if any(type(value) is not int or not 0 < value <= 0x7FFF for value in raster_ids):
        raise ValueError("Raster decal IDは1～32767の整数である必要があります")
    ids = sorted(set(raster_ids))
    if not ids:
        return HEADER.pack(MAGIC, VERSION, 0), {"count": 0, "bytes": HEADER.size, "ids": []}

    if gamedb_path is None:
        raise ValueError("Raster Logoの正確な画像対応にはFH6 GameDBが必要です")
    mapping, gamedb_sha256 = _gamedb_decal_asset_ids(gamedb_path, ids, allow_unregistered=omit_missing)
    resolver = FH6RasterDecalResolver(archive)
    entries: list[bytes] = []
    omitted: list[dict[str, Any]] = []
    for raster_id in ids:
        asset_id = mapping.get(raster_id)
        reason = ""
        if asset_id is None:
            reason = "gamedb-unregistered"
        elif omit_missing and not _member_present(resolver, asset_id):
            reason = "decals-zip-missing"
        if reason:
            omitted.append({"raster_id": raster_id, "asset_id": asset_id, "reason": reason})
            entries.append(ENTRY.pack(raster_id, *OMITTED_PLACEHOLDER_SIZE, len(OMITTED_PLACEHOLDER_RGBA))
                           + OMITTED_PLACEHOLDER_RGBA)
            continue
        source = resolver(asset_id)
        if source is None:
            raise ValueError(
                f"Raster ID {raster_id} に対応するGameDB原本decal{asset_id}が"
                "Decals.zipに存在しないか復号できません"
            )
        rgba = source.convert("RGBA")
        width, height = rgba.size
        pixels = rgba.tobytes()
        if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
            raise ValueError(f"Raster decal ID {raster_id} のRGBA寸法が不正です")
        entries.append(ENTRY.pack(raster_id, width, height, len(pixels)) + pixels)

    payload = HEADER.pack(MAGIC, VERSION, len(ids)) + b"".join(entries)
    return payload, {
        "count": len(ids), "bytes": len(payload), "ids": ids,
        "decoded_count": len(ids) - len(omitted),
        "omitted": omitted,
        "omission_policy": OMISSION_POLICY if omit_missing else "reject",
        "source_asset_ids": {str(k): v for k, v in mapping.items()},
        "source_binding_contract": DECAL_DATABASE_CONTRACT,
        "gamedb_sha256": gamedb_sha256,
    }
