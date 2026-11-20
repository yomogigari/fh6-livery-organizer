"""保存データの外側の圧縮コンテナだけを読み取るプロジェクト実装。

バイナル、マスク、所有権情報などの内容を解釈しない。
壊れた圧縮ブロックや過大な展開要求は fail closed とする。
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

RAW_SIGNATURES = (b"vlrc", b"gyvl")
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_BLOCKS = 4096


class EnvelopeError(ValueError):
    """圧縮コンテナが不正、または安全上の容量上限を超えている。"""


def unpack_source_bytes(blob: bytes, *, max_unpacked: int = MAX_UNPACKED_BYTES) -> bytes:
    """8バイトのブロック長とzlib本文を連結して、元ペイロードを返す。

    先頭に gyvl / vlrc があるデータは非圧縮本文として扱う。
    意図的に元デコーダーとは別実装・別エラー文言とする。
    """
    if type(blob) is not bytes:
        raise TypeError("source blob must be bytes")
    if type(max_unpacked) is not int or max_unpacked < 1:
        raise ValueError("invalid unpacked byte budget")
    if blob.startswith(RAW_SIGNATURES):
        if len(blob) > max_unpacked:
            raise EnvelopeError("raw data exceeds unpacked byte budget")
        return blob
    if len(blob) < 8:
        raise EnvelopeError("missing compressed block header")
    offset = 0
    blocks = []
    remaining = max_unpacked
    count = 0
    while offset < len(blob):
        if count >= MAX_BLOCKS:
            raise EnvelopeError("too many compressed blocks")
        if len(blob) - offset < 8:
            raise EnvelopeError("truncated compressed block header")
        packed_length, plain_length = struct.unpack_from('<II', blob, offset)
        offset += 8
        if packed_length < 1 or packed_length > len(blob) - offset:
            raise EnvelopeError("invalid compressed block length")
        if plain_length > remaining:
            raise EnvelopeError("unpacked byte budget exceeded")
        packed = blob[offset:offset + packed_length]
        offset += packed_length
        try:
            stream = zlib.decompressobj()
            plain = stream.decompress(packed, plain_length + 1)
            if len(plain) > plain_length or stream.unconsumed_tail or not stream.eof or stream.unused_data:
                raise EnvelopeError("compressed block boundaries mismatch")
            plain += stream.flush()
        except zlib.error as error:
            raise EnvelopeError("invalid zlib compressed block") from error
        if len(plain) != plain_length:
            raise EnvelopeError("unpacked block length mismatch")
        blocks.append(plain)
        remaining -= plain_length
        count += 1
    return b''.join(blocks)


def unpack_source_file(path: str | Path, *, max_unpacked: int = MAX_UNPACKED_BYTES) -> bytes:
    """ローカルに存在する保存データを読み取り専用で展開する。"""
    return unpack_source_bytes(Path(path).read_bytes(), max_unpacked=max_unpacked)
