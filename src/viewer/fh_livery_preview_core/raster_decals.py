"""利用者のゲームの Decals.zip から、FH6 の組み込みロゴ（ラスター画像）を読み出す。

ロゴの画像は Decals.zip の textures/decal<番号>.swatchbin（番号は 3 桁ゼロ埋めの場合もある）。
SwatchBin の読み取りと BC7 の復号は swatch_texture（独自実装）を使う。
ゲーム原本は読み取りのみで、画像を書き出したり同梱したりしない。
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import os
import threading
import zipfile

from .swatch_texture import SwatchFormatError, decode_rgba

DECALS_ARCHIVE_NAME = "decals.zip"

# 同じプロセスの中で、Decals.zip の目次と、解いたロゴの画像を覚える（2026-11-20）。ペイントのたびに目次を読み直し、
# ロゴ 1 枚ごとに Decals.zip を開き直して解いていた。ロゴはペイントの間で同じ物がよく出る。鍵は Decals.zip の
# 識別（場所・機器と番号・大きさ・更新日時）と項目の名前。画像は写しを渡し、覚えた画像は渡さない。
_ARCHIVE_NAMES: "OrderedDict[tuple, dict[str, str]]" = OrderedDict()
_ARCHIVE_NAMES_LIMIT = 4
_DECODED: "OrderedDict[tuple, object]" = OrderedDict()
_DECODED_LIMIT = 64
_MEMO_LOCK = threading.Lock()


def _archive_identity(path: Path) -> tuple | None:
    try:
        stat = os.stat(path)
    except (OSError, ValueError):
        return None
    return (os.path.normcase(os.path.abspath(path)), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _remember(memo: OrderedDict, key: tuple, value: object, limit: int) -> None:
    with _MEMO_LOCK:
        memo[key] = value
        memo.move_to_end(key)
        while len(memo) > limit:
            memo.popitem(last=False)


class RasterDecalError(RuntimeError):
    """組み込みロゴの書庫・画像を読めない。"""


def resolve_fh6_decals_archive(game_folder: Path | str) -> Path:
    """ゲームのフォルダー・Content フォルダー・Decals.zip 自身のどれからでも Decals.zip を見つける。"""
    root = Path(game_folder).expanduser()
    for candidate in (root,
                      root / "media" / "livery" / "Decals.zip",
                      root / "Content" / "media" / "livery" / "Decals.zip"):
        if candidate.is_file() and candidate.name.casefold() == DECALS_ARCHIVE_NAME:
            return candidate.resolve()
    raise RasterDecalError(
        f"FH6 built-in decal textures were not found below {root}. "
        "Choose the game folder, its Content folder, or Decals.zip itself."
    )


def decode_fh6_decal_swatch(data: bytes):
    """組み込みロゴの SwatchBin を RGBA 画像にする。"""
    try:
        return decode_rgba(data)
    except SwatchFormatError as exc:
        raise RasterDecalError(f"The built-in decal texture could not be decoded: {exc}") from exc


class FH6RasterDecalResolver:
    """ロゴ番号 → RGBA 画像（読めなければ None）。同じ番号は一度だけ読む。"""

    def __init__(self, game_folder: Path | str):
        self.archive = resolve_fh6_decals_archive(game_folder)
        self._images: dict[int, object | None] = {}
        self._identity = _archive_identity(self.archive)
        with _MEMO_LOCK:
            names = _ARCHIVE_NAMES.get(self._identity) if self._identity is not None else None
        if names is None:
            try:
                with zipfile.ZipFile(self.archive) as bundle:
                    names = {name.casefold(): name for name in bundle.namelist()}
            except (OSError, zipfile.BadZipFile) as exc:
                raise RasterDecalError("The FH6 built-in decal archive is unreadable.") from exc
            if self._identity is not None:
                _remember(_ARCHIVE_NAMES, self._identity, names, _ARCHIVE_NAMES_LIMIT)
        self._names = names  # 覚えた目次を共有する（引くだけで、変えない）

    def expected_members(self, raster_id: int) -> tuple[str, str]:
        number = int(raster_id)
        return (f"textures/decal{number}.swatchbin", f"textures/decal{number:03d}.swatchbin")

    def member_name(self, raster_id: int) -> str | None:
        for name in self.expected_members(raster_id):
            if name in self._names:
                return self._names[name]
        return None

    def __call__(self, raster_id: int):
        number = int(raster_id)
        if number not in self._images:
            self._images[number] = self._load(number)
        return self._images[number]

    def _load(self, number: int):
        member = self.member_name(number)
        if member is None:
            return None
        key = (self._identity, member) if self._identity is not None else None
        if key is not None:
            with _MEMO_LOCK:
                remembered = _DECODED.get(key)
                if remembered is not None:
                    _DECODED.move_to_end(key)
            if remembered is not None:
                return remembered.copy()
        try:
            with zipfile.ZipFile(self.archive) as bundle:
                image = decode_fh6_decal_swatch(bundle.read(member))
        except (KeyError, OSError, zipfile.BadZipFile, RasterDecalError):
            return None
        if key is not None and image is not None and hasattr(image, "copy"):
            _remember(_DECODED, key, image.copy(), _DECODED_LIMIT)
        return image
