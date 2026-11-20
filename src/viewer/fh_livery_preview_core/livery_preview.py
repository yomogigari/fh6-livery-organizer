"""FH6 Vinylメタデータの補助処理（GPU専用）。

CPUによる面のラスタライズ、PillowのRGBA合成、CPUへの代替、
ペイントプレビュー画像のキャッシュは意図的に削除した。
すべてのペイント画素はWebGL2描画器が生成し、本モジュールは画像を作らない。
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any

from .painter_compat import configure_vinyl_resource_root, default_vinyl_resource_root

TYPE_BASES = (
    (0x0065, "Primitives"),
    (0x00C9, "Gradient_Shapes"),
    (0x012D, "Stripes"),
    (0x0191, "Tears"),
    (0x01F5, "Racing_Icons"),
    (0x0259, "Flames"),
    (0x02BD, "Paint_Splats"),
    (0x0321, "Tribal"),
    (0x0385, "Nature"),
    (0x0515, "Upper_Letters_2"),
    (0x0579, "Lower_Letters_2"),
    (0x05DD, "Upper_Letters_3"),
    (0x0641, "Lower_Letters_3"),
    (0x06A5, "Upper_Letters_4"),
    (0x0709, "Lower_Letters_4"),
    (0x076D, "Upper_Letters_1"),
    (0x07D1, "Lower_Letters_1"),
    (0x0835, "Community_Vinyls_1"),
    (0x0899, "Community_Vinyls_2"),
    (0x08FD, "Community_Vinyls_3"),
    (0x0961, "Community_Vinyls_4"),
    (0x09C5, "Upper_Letters_5"),
    (0x0A29, "Lower_Letters_5"),
    (0x0A8D, "Upper_Letters_6"),
    (0x0AF1, "Lower_Letters_6"),
    (0x0B55, "Upper_Letters_7"),
    (0x0BB9, "Lower_Letters_7"),
    (0x0C1D, "Upper_Letters_8"),
    (0x0C81, "Lower_Letters_8"),
    (0x0CE5, "Upper_Letters_9"),
    (0x0D49, "Lower_Letters_9"),
    (0x0DAD, "Upper_Letters_10"),
    (0x0E11, "Lower_Letters_10"),
    (0x0E75, "Upper_Letters_11"),
    (0x0ED9, "Lower_Letters_11"),
)
SPECIAL_RESOURCES = {
    0x07D0: ("Lower_Letters_1", 1),
    0x0BB8: ("Lower_Letters_7", 1),
}


def resource_location_key(word: int) -> tuple[str, int] | None:
    """resource_location が探す (family, index)。ファイルがあるかは見ない。"""
    special = SPECIAL_RESOURCES.get(word)
    if special is not None:
        family, index = special
        return family, index
    for base, family in TYPE_BASES:
        index = word - base + 1
        if 1 <= index <= 80:
            return family, index
    return None


def resource_location(root: Path, word: int) -> Path | None:
    key = resource_location_key(word)
    if key is None:
        return None
    family, index = key
    path = root / family / str(index)
    return path if path.is_file() else None


def shape_is_raster(shape: dict[str, Any]) -> bool:
    return bool(shape.get("is_raster_logo"))


def shape_word(shape: dict[str, Any]) -> int:
    value = shape.get("type_word")
    if value is None:
        value = int(shape.get("type", 0)) - 0x100000
    return int(value) & 0xFFFF


def shape_color(shape: dict[str, Any]) -> tuple[int, int, int, int]:
    values = list(shape.get("color") or [])
    values.extend([255] * (4 - len(values)))
    return tuple(max(0, min(255, round(float(value)))) for value in values[:4])


