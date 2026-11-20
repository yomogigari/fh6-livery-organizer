"""FH6 の SwatchBin（burG 形式のテクスチャ）から、寸法・圧縮形式・画素データを取り出す。

FH6 原本のファイルを調べて確認した構造（2026-11-17、ゲーム内の SwatchBin で全件照合）：

- 先頭は "burG"、続いて版（major, minor の各 1 バイト）。
  - 版 1.1 以上：オフセット 16 に項目数（u32）、項目の表はオフセット 20 から。
  - それより前：オフセット 6 に項目数（u16）、項目の表はオフセット 16 から。
- 項目の表は 1 件 24 バイト：種類（4 文字）、版（2 バイト）、付属情報の件数（u16）、
  付属情報の位置（u32）、本体の位置（u32）、本体の大きさ 2 種（u32 ×2。後者が 0 でなければ後者を使う）。
- テクスチャの項目は種類 "BCXT"。付属情報（1 件 8 バイト）のうち種類 "HCXT" がテクスチャ情報で、
  その 6 バイト目の u16 が、付属情報からテクスチャ情報の本体までの距離。
- テクスチャ情報の本体：+0x18 幅（u32）、+0x1C 高さ（u32）、+0x24 配置の情報（u16。上位 2 ビットが
  タイル配置＝Xbox 向けの並び）、+0x28 変換後の形式（i32）、+0x38 断面の表までの距離（u32）。
  断面の表の先頭 u32 が断面の形式。圧縮形式は「変換後の形式が 2 より大きければ その値−2、
  そうでなければ断面の形式」（例：9 が BC7）。

ゲーム原本は読み取りのみで、ここでは書き出さない。
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import struct

MAGIC = b"burG"
TEXTURE_ENTRY = b"BCXT"
TEXTURE_INFO = b"HCXT"
DIRECTORY_ROW = 24
INFO_ROW = 8
INFO_BODY_MIN = 64
MAX_ENTRIES = 1024
MAX_SIDE = 16384

# 圧縮形式（FH6 の番号）→ DDS の DXGI 形式。原本で観測した番号だけを持つ。
DXGI_BY_ENCODING = {0: 80, 3: 80, 4: 81, 5: 83, 6: 84, 9: 98, 13: 28}
BC7_ENCODINGS = (9, 22)


class SwatchFormatError(ValueError):
    """SwatchBin の構造が想定と違う、または必要な範囲が欠けている。"""


@dataclass(frozen=True)
class SwatchSurface:
    version: tuple[int, int]
    entry_count: int
    width: int
    height: int
    encoding: int
    tiled: int
    pixel_size: int  # 項目の表に書かれた本体の大きさ
    pixels: bytes | None  # 本体の範囲がファイルを越えるときは None


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _directory(data: bytes) -> tuple[tuple[int, int], int, int]:
    """(版, 項目数, 表の開始位置) を返す。"""
    if len(data) < 20 or data[:4] != MAGIC:
        raise SwatchFormatError("not burG")
    version = (data[4], data[5])
    if version >= (1, 1):
        return version, _u32(data, 16), 20
    return version, _u16(data, 6), 16


def _texture_info_at(data: bytes, info_count: int, info_offset: int) -> int | None:
    for index in range(info_count):
        row = info_offset + index * INFO_ROW
        if row + INFO_ROW > len(data):
            return None
        if data[row:row + 4] == TEXTURE_INFO:
            return row + _u16(data, row + 6)
    return None


def read_texture_surface(data: bytes) -> SwatchSurface:
    """最初に読めるテクスチャ項目の寸法・形式・画素を返す。読めなければ SwatchFormatError。"""
    version, count, table = _directory(data)
    for index in range(min(count, MAX_ENTRIES)):
        row = table + index * DIRECTORY_ROW
        if row + DIRECTORY_ROW > len(data) or data[row:row + 4] != TEXTURE_ENTRY:
            continue
        info_count = _u16(data, row + 6)
        info_offset, body_offset, size_a, size_b = struct.unpack_from("<IIII", data, row + 8)
        info = _texture_info_at(data, info_count, info_offset)
        if info is None or info + INFO_BODY_MIN > len(data):
            continue
        width, height = struct.unpack_from("<II", data, info + 0x18)
        layout = _u16(data, info + 0x24)
        converted = struct.unpack_from("<i", data, info + 0x28)[0]
        slices = info + _u32(data, info + 0x38)
        if slices + 4 > len(data):
            continue
        encoding = converted - 2 if converted > 1 else _u32(data, slices)
        size = int(size_b or size_a)
        in_range = size > 0 and body_offset + size <= len(data)
        return SwatchSurface(
            version=(int(version[0]), int(version[1])),
            entry_count=int(count),
            width=int(width),
            height=int(height),
            encoding=int(encoding),
            tiled=int(layout >> 14),
            pixel_size=size,
            pixels=bytes(data[body_offset:body_offset + size]) if in_range else None,
        )
    raise SwatchFormatError("no BCXT texture blob")


def dds_bytes(width: int, height: int, pixels: bytes, dxgi_format: int) -> bytes:
    """画素データを、DX10 拡張ヘッダー付きの DDS（1 枚、ミップなし）に包む。"""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000  # CAPS・HEIGHT・WIDTH・PIXELFORMAT・LINEARSIZE
    pixel_format = struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    header = (struct.pack("<IIIIIII", 124, flags, height, width, len(pixels), 0, 1)
              + bytes(44) + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0))
    dx10 = struct.pack("<IIIII", dxgi_format, 3, 0, 1, 0)  # 2D テクスチャ・1 枚
    return b"DDS " + header + dx10 + pixels


def decode_rgba(data: bytes):
    """SwatchBin を PIL の RGBA 画像にする（BC7 だけ）。読めなければ SwatchFormatError。"""
    from PIL import Image

    surface = read_texture_surface(data)
    if surface.tiled:
        raise SwatchFormatError("tiled/Xbox swatch requires detiling")
    if surface.encoding not in BC7_ENCODINGS:
        raise SwatchFormatError(f"encoding {surface.encoding} is not BC7")
    if surface.pixels is None or not (0 < surface.width <= MAX_SIDE and 0 < surface.height <= MAX_SIDE):
        raise SwatchFormatError("swatch pixel range or size invalid")
    try:
        with Image.open(io.BytesIO(dds_bytes(surface.width, surface.height, surface.pixels, 98))) as opened:
            return opened.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise SwatchFormatError(f"BC7 decode failed: {exc}") from exc
