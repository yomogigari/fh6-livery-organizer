"""ゲームの文字列の表（media/stripped/stringtables/<言語>.zip の <表の名前>.str）を読む（読み取りのみ）。

GameDB の表示名の列は `_&<64 ビットの整数>` の形のキーで、その下位 32 ビットが文字列の表の項目の ID になる
（上位 32 ビットは表ごとに同じ値）。

.str の構造（FH6 の実ファイルで確かめた。複数の表で長さの検算が一致する）：
- 0x00〜：表の名前（NUL 埋め）
- 0x82：版（uint16、2）
- 0x88：第 1 区画の終わりの位置（uint32、ファイルの先頭から）
- 0x90：文字列の領域のバイト数（uint32）
- 0x94：項目の数（uint32）
- 0x98〜：項目（ID uint32・文字列の領域の先頭からの位置 uint32）× 項目の数
- その後：文字列の領域（UTF-8、NUL 終端）
- 第 1 区画の後の区画（ID の名前など）は使わない。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import struct
import zipfile

# Viewer の言語 → 文字列の表の ZIP の名前
LANGUAGE_ARCHIVES = {"ja": "JP", "en": "EN"}
STRING_TABLE_DIR = Path("media") / "stripped" / "stringtables"
_HEADER_END = 0x98
_MAX_ENTRIES = 1_000_000


class GameStringTableError(ValueError):
    pass


def parse_string_table(data: bytes) -> dict[int, str]:
    """.str のバイト列から、項目の ID → 文字列の辞書を作る。構造が合わなければ拒否する。"""
    if len(data) < _HEADER_END:
        raise GameStringTableError("文字列の表が短すぎます")
    version = struct.unpack_from("<H", data, 0x82)[0]
    section_end, = struct.unpack_from("<I", data, 0x88)
    strings_size, count = struct.unpack_from("<II", data, 0x90)
    if version != 2:
        raise GameStringTableError(f"文字列の表の版が違います: {version}")
    if not 0 <= count <= _MAX_ENTRIES:
        raise GameStringTableError(f"文字列の表の項目の数が不正です: {count}")
    strings_start = _HEADER_END + count * 8
    if strings_start + strings_size != section_end or section_end > len(data):
        raise GameStringTableError("文字列の表の長さが合いません")
    region = data[strings_start:section_end]
    result: dict[int, str] = {}
    for index in range(count):
        ident, offset = struct.unpack_from("<II", data, _HEADER_END + index * 8)
        if offset >= strings_size:
            raise GameStringTableError("文字列の位置が領域の外です")
        end = region.find(b"\0", offset)
        if end < 0:
            raise GameStringTableError("文字列の終端がありません")
        result[ident] = region[offset:end].decode("utf-8", "replace")
    return result


@lru_cache(maxsize=32)
def _cached_table(archive: str, size: int, mtime_ns: int, table: str) -> dict[int, str]:
    del size, mtime_ns  # キャッシュの鍵（ファイルが変われば読み直す）
    with zipfile.ZipFile(archive) as bundle:
        try:
            data = bundle.read(f"{table}.str")
        except KeyError as exc:
            raise GameStringTableError(f"文字列の表がありません: {table}") from exc
    return parse_string_table(data)


def load_string_table(content_root: Path | str, language: str, table: str) -> dict[int, str]:
    """ゲームの Content フォルダーから、言語（ja・en）の文字列の表を読む。"""
    archive_name = LANGUAGE_ARCHIVES.get(language)
    if archive_name is None:
        raise GameStringTableError(f"対応していない言語です: {language}")
    if not table.replace("_", "").isalnum():
        raise GameStringTableError(f"表の名前が不正です: {table}")
    archive = Path(content_root) / STRING_TABLE_DIR / f"{archive_name}.zip"
    stat = archive.stat()
    if stat.st_size == 0:
        raise GameStringTableError(f"文字列の表の ZIP が空です: {archive.name}")
    return _cached_table(str(archive), stat.st_size, stat.st_mtime_ns, table)


def string_key_id(key: object) -> int | None:
    """GameDB の `_&<64 ビットの整数>` のキーから、文字列の表の項目の ID（下位 32 ビット）を取る。"""
    if not isinstance(key, str) or not key.startswith("_&") or not key[2:].isdigit():
        return None
    value = int(key[2:])
    if value >= 1 << 64:
        return None
    return value & 0xFFFFFFFF


def resolve_string_key(table: dict[int, str], key: object) -> str | None:
    ident = string_key_id(key)
    if ident is None:
        return None
    text = table.get(ident)
    return text.strip() if isinstance(text, str) and text.strip() else None
