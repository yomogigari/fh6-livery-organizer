"""車両の工場出荷色（ManufacturerColors.bin）から、選択番号の色と材質を返す。

形式の読み取りは independent_chassis/source_manufacturer_palette_stage.py
（FH6 原本の全 691 車種で、推測なし・余りバイトなしで読み切れることを確認した独自の読み取り）を使う。
ここでは、車両 ZIP の中から使うファイルを選び、選択番号ごとの色・材質を整えて返すだけを行う。
ゲーム原本は読み取りのみで、書き出さない。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
import zipfile

from .independent_chassis.source_manufacturer_palette_stage import (
    SourceManufacturerPaletteError,
    decode_original_manufacturer_colors,
)
from .vehicle_assets import VehicleAsset

PALETTE_FILE_NAME = "manufacturercolors.bin"


class ManufacturerColorError(RuntimeError):
    """工場出荷色を読めない、または使うファイルが決まらない。"""


def _unit_rgb_hex(rgb: tuple[float, float, float] | None) -> str | None:
    """0〜1 の RGB を #rrggbb にする（範囲外は切り詰める）。"""
    if rgb is None:
        return None
    return "#" + "".join(f"{round(min(1.0, max(0.0, float(value))) * 255):02x}" for value in rgb)


def _rgb_tuple(values: Any) -> tuple[float, float, float] | None:
    if values is None:
        return None
    return (float(values[0]), float(values[1]), float(values[2]))


@dataclass(frozen=True)
class ManufacturerColor:
    """選択番号 1 つ分の工場出荷色。primary_* は先頭の項目（車体）、group_* は記録末尾の色。"""

    selector: int
    enabled: bool
    entry_count: int
    primary_rgb: tuple[float, float, float] | None
    group_primary_rgb: tuple[float, float, float] | None
    group_primary_enabled: bool
    secondary_rgb: tuple[float, float, float] | None
    secondary_enabled: bool
    material_path: str
    material_slots: tuple[str, ...]
    material_index_mask: int | None

    def public_metadata(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "enabled": self.enabled,
            "entry_count": self.entry_count,
            "primary_rgb": list(self.primary_rgb) if self.primary_rgb is not None else None,
            "primary_unit_rgb_hex": _unit_rgb_hex(self.primary_rgb),
            "group_primary_rgb": list(self.group_primary_rgb) if self.group_primary_rgb is not None else None,
            "group_primary_unit_rgb_hex": _unit_rgb_hex(self.group_primary_rgb),
            "group_primary_enabled": self.group_primary_enabled,
            "secondary_rgb": list(self.secondary_rgb) if self.secondary_rgb is not None else None,
            "secondary_unit_rgb_hex": _unit_rgb_hex(self.secondary_rgb),
            "secondary_enabled": self.secondary_enabled,
            "material_path": self.material_path,
            "material_slots": list(self.material_slots),
            "material_index_mask": self.material_index_mask,
        }


def _color_from_group(group: dict) -> ManufacturerColor:
    entries = list(group.get("source_entries") or [])
    first = entries[0] if entries else None
    return ManufacturerColor(
        selector=int(group["source_selector_index"]),
        enabled=bool(entries),
        entry_count=len(entries),
        primary_rgb=_rgb_tuple(first["source_preview_rgb_f32"]) if first else None,
        group_primary_rgb=_rgb_tuple(group.get("source_group_preview_primary_f32")),
        group_primary_enabled=bool(group.get("source_group_preview_primary_present")),
        secondary_rgb=_rgb_tuple(group.get("source_group_preview_secondary_f32")),
        secondary_enabled=bool(group.get("source_group_preview_secondary_present")),
        material_path=str(first["source_material_path"]) if first else "",
        material_slots=tuple(first.get("material_slot_names") or ()) if first else (),
        material_index_mask=first.get("material_index_mask") if first else None,
    )


def decode_manufacturer_colors(data: bytes) -> list[ManufacturerColor]:
    """ManufacturerColors.bin の中身を、選択番号順の色の一覧にする。"""
    try:
        palette = decode_original_manufacturer_colors(data)
    except SourceManufacturerPaletteError as exc:
        raise ManufacturerColorError(str(exc)) from exc
    return [_color_from_group(group) for group in palette["source_selector_groups"]]


def _member_key(name: str) -> PurePosixPath:
    return PurePosixPath(name.replace("\\", "/").lstrip("/"))


def _palette_members(names: list[str]) -> list[str]:
    """使う ManufacturerColors.bin の候補を、優先順に並べる。

    1. 車両の .carbin と同じフォルダーにあるもの
    2. ZIP の最上位にあるもの
    3. それ以外（同じ名前のファイル）
    """
    palettes = [name for name in names if _member_key(name).name.casefold() == PALETTE_FILE_NAME]
    carbin_folders = {
        str(_member_key(name).parent).casefold()
        for name in names
        if _member_key(name).suffix.casefold() == ".carbin"
    }

    def rank(name: str) -> int:
        folder = str(_member_key(name).parent).casefold()
        if folder in carbin_folders:
            return 0
        if folder == ".":
            return 1
        return 2

    ordered: list[str] = []
    seen: set[str] = set()
    for name in sorted(palettes, key=lambda item: (rank(item), palettes.index(item))):
        key = str(_member_key(name)).casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(name)
    return ordered


def read_vehicle_manufacturer_colors(asset: VehicleAsset) -> tuple[str, list[ManufacturerColor]]:
    """車両 ZIP の ManufacturerColors.bin を読み、(ZIP 内の名前, 色の一覧) を返す。"""
    with zipfile.ZipFile(asset.archive_path) as bundle:
        members = _palette_members(bundle.namelist())
        if not members:
            raise ManufacturerColorError(f"{asset.archive_name} has no manufacturercolors.bin")
        failures: list[str] = []
        for member in members:
            try:
                colors = decode_manufacturer_colors(bundle.read(member))
            except ManufacturerColorError as exc:
                failures.append(f"{_member_key(member)}: {exc}")
                continue
            return str(_member_key(member)), colors
    raise ManufacturerColorError(
        f"{asset.archive_name} has no decodable manufacturercolors.bin: " + "; ".join(failures[:4])
    )


def resolve_vehicle_manufacturer_color(asset: VehicleAsset, selector: int) -> dict[str, Any]:
    """選択番号の工場出荷色を返す。番号が範囲外・無効なら resolved=False。"""
    member, palette = read_vehicle_manufacturer_colors(asset)
    selected = palette[selector] if 0 <= selector < len(palette) and palette[selector].enabled else None
    return {
        "archive_name": asset.archive_name,
        "model_code": asset.model_code,
        "member": member,
        "palette_size": len(palette),
        "selector": int(selector),
        "resolved": selected is not None,
        "color": selected.public_metadata() if selected is not None else None,
    }
