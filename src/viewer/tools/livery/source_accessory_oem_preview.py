"""FH6原本ManufacturerColorsのMirror専用工場出荷色を研究比較へ渡す。

原本のFactory selector 0にあるMirrorスロットだけを読む。C_liveryが
実際にそのOEM selectorを選んだ証拠ではなく、Shader最終RGBではない。
この処理は環境変数で研究を明示したときだけ呼び出す。
"""
from __future__ import annotations

import math
import re

from .manufacturer_colors import ManufacturerColorError, resolve_vehicle_manufacturer_color

_SOURCE_PALETTE = "original-ManufacturerColors.bin-Mirror-slot-factory-selector0-research"


class OriginalAccessoryPaletteError(ValueError):
    """原本Mirrorスロットの出典が一意に確認できない。"""


def signed_original_mirror_preview(resolved: dict) -> dict:
    """元ManufacturerColorsの選択グループ/正確なMirror名を出典検査。"""
    if (not isinstance(resolved, dict) or resolved.get("resolved") is not True
            or type(resolved.get("selector")) is not int
            or resolved["selector"] != 0 or not isinstance(resolved.get("color"), dict)):
        raise OriginalAccessoryPaletteError("Factory selector 0の原本色選択が不正")
    color = resolved["color"]
    slots = color.get("material_slots")
    if (not isinstance(slots, list) or slots.count("Mirror") != 1
            or any(not isinstance(s, str) or not s for s in slots)):
        raise OriginalAccessoryPaletteError("原本Mirrorスロットが一意ではありません")
    path = color.get("material_path")
    if (not isinstance(path, str) or not re.fullmatch(
            r"(?i)game:\\media\\cars\\_library\\materials\\_fmnext\\carpaint_calibrated\\[^\\]+\.materialbin",
            path)):
        raise OriginalAccessoryPaletteError("Mirror原本Calibrated材質のパス署名が不足")
    rgb = color.get("primary_rgb")
    if (not isinstance(rgb, list) or len(rgb) != 3
            or not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in rgb)):
        raise OriginalAccessoryPaletteError("原本Mirror RGBプレビューが不正")
    hex_rgb = "#" + "".join(f"{round(255 * v):02x}" for v in rgb)
    return {
        "schema": "lo4fh6.source-original-accessory-mirror-oem-preview.v1",
        "mirror_factory_rgb_hex": hex_rgb,
        "source_selector": 0,
        "source_slot": "Mirror",
        "source_material_path": path,
        "source_palette": _SOURCE_PALETTE,
        "manufacturer_palette_member": resolved.get("member"),
        "source_color_available": True,
        "selected_game_color_approved": False,
        "game_shader_rgb_equivalent": False,
        "xbox_approved": False,
        "product_default_changed": False,
    }


def source_original_mirror_preview(asset) -> dict:
    """車種共通の元メーカーMirror色候補。原本欠損時は明示エラー。"""
    try:
        resolved = resolve_vehicle_manufacturer_color(asset, 0)
    except ManufacturerColorError as exc:
        raise OriginalAccessoryPaletteError("原本Mirror工場色を読めません") from exc
    return signed_original_mirror_preview(resolved)
