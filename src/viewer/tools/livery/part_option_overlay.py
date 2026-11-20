"""部品の選択肢（バンパー・ボンネット・サイドスカート・リアウイング）ごとの重ね合わせのGLB。

- 選択肢を初めて選んだときに、その選択肢で加わる部品だけを変換し（Carbinの配置のまま）、
  車種ごとのキャッシュ（_fh6-vehicle-cache/part-options）に保存する。全選択肢を一括では作らない。
- GLBのシーンの lo4fh6_part_option_overlay に、置き換える純正の部品の識別子を記録する。
  Viewerは、その部品を隠して重ね合わせの部品を描く。
- 選べる選択肢は、車体のGLBに記録した原本Carbinの選択肢の一覧（lo4fh6_original_carbin_part_options）から、
  今の車体（CarBody）の選択肢に限る。表示名は段階（Level）と番号。
- 製造元の名前（日本語・英語）は、GameDB の選択肢の表の ManufacturerId から、ゲームの文字列の表
  （List_PartManufacturer）で引いて加える（with_manufacturer_names）。引けなければ付けない。
"""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import struct
from pathlib import Path

from .vehicle_analysis_cache import mark_used

PART_OPTION_FAMILIES = ("FrontBumper", "RearBumper", "Hood", "SideSkirts", "RearWing")
# 重ね合わせのGLBの版。作り方を変えたら上げる（車体のGLBの版 LOCAL_CHASSIS_FORMAT_REVISION も名前に入る）。
PART_OPTION_OVERLAY_REVISION = 1
PART_OPTION_CACHE_DIR = "part-options"
# 種類ごとの GameDB の選択肢の表（Id は原本Carbinの選択肢の番号と同じ）
PART_OPTION_GAMEDB_TABLES = {
    "FrontBumper": "List_UpgradeCarBodyFrontBumper",
    "RearBumper": "List_UpgradeCarBodyRearBumper",
    "Hood": "List_UpgradeCarBodyHood",
    "SideSkirts": "List_UpgradeCarBodySideSkirt",
    "RearWing": "List_UpgradeRearWing",
}
# List_PartManufacturer の 0（なし）と 1（「ストック」）は製造元として表示しない。
_NO_MANUFACTURER_IDS = (0, 1)


class PartOptionOverlayError(ValueError):
    pass


def glb_document(path: Path | str) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise PartOptionOverlayError("GLBではありません")
    length, tag = struct.unpack_from("<I4s", raw, 12)
    if tag != b"JSON":
        raise PartOptionOverlayError("GLBのJSONがありません")
    return json.loads(raw[20:20 + length])


def part_option_catalog(document: dict, *, car_body_id: int | None = None) -> list[dict]:
    """選べる部品の選択肢の一覧（種類ごと。選択肢が 2 つ以上ある種類だけ）。

    car_body_id を省くと、純正の車体（CarBody の純正の選択肢）の番号を使う。
    リアウイング等の car_body_id が -1 の選択肢は、車体に関係なく選べる。
    """
    scenes = document.get("scenes") or []
    extras = (scenes[0].get("extras") if scenes and isinstance(scenes[0], dict) else None) or {}
    rows = [row for row in extras.get("lo4fh6_original_carbin_part_options") or [] if isinstance(row, dict)]
    if car_body_id is None:
        bodies = [row.get("id") for row in rows if row.get("part_type") == "CarBody" and row.get("is_stock") is True]
        car_body_id = bodies[0] if len(bodies) == 1 and type(bodies[0]) is int else None
    catalog = []
    for family in PART_OPTION_FAMILIES:
        options = [
            {"id": row["id"], "level": int(row.get("level") or 0), "is_stock": row.get("is_stock") is True}
            for row in rows
            if row.get("part_type") == family and type(row.get("id")) is int
            and (row.get("car_body_id") in (-1, None) or row.get("car_body_id") == car_body_id)
        ]
        options.sort(key=lambda option: (not option["is_stock"], option["level"], option["id"]))
        if len(options) >= 2 and options[0]["is_stock"]:
            catalog.append({"family": family, "options": options})
    return catalog


def part_option_catalog_for_file(path: Path | str, *, car_body_id: int | None = None) -> list[dict]:
    """part_option_catalog(glb_document(path)) と同じ一覧。

    同じプロセスで同じ GLB のファイル（場所・大きさ・更新日時が同じ）と同じ車体の一覧は覚えて写しを返す
    （同じ車のペイントを続けて開くたびに、約 35 MB の GLB を読んで目次を解析していた。約 0.04 秒。2026-11-20）。
    """
    from .process_file_memo import remembered
    target = Path(path)
    return remembered("part-option-catalog", [target], car_body_id,
                      lambda: part_option_catalog(glb_document(target), car_body_id=car_body_id), limit=4)


def with_manufacturer_names(catalog: list[dict], *, database: Path | str,
                            content_root: Path | str) -> list[dict]:
    """純正以外の選択肢に製造元の名前 {"ja": ..., "en": ...} を加えた一覧を返す（元の一覧は変えない）。

    GameDB・文字列の表が読めない、または名前が無い選択肢には付けない（表示は段階と番号のまま）。
    """
    from .game_string_table import LANGUAGE_ARCHIVES, load_string_table, resolve_string_key

    result = [{**entry, "options": [dict(option) for option in entry["options"]]} for entry in catalog]
    wanted = {entry["family"]: [option["id"] for option in entry["options"] if not option["is_stock"]]
              for entry in result if entry["family"] in PART_OPTION_GAMEDB_TABLES}
    if not any(wanted.values()):
        return result
    path = Path(database).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        keys = dict(connection.execute("select Id, PartManufacturer from List_PartManufacturer"))
        makers: dict[tuple[str, int], int] = {}
        for family, ids in wanted.items():
            if not ids:
                continue
            table = PART_OPTION_GAMEDB_TABLES[family]
            marks = ",".join("?" * len(ids))
            for option_id, maker in connection.execute(
                    f"select Id, ManufacturerId from {table} where Id in ({marks})", ids):
                if type(maker) is int and maker not in _NO_MANUFACTURER_IDS:
                    makers[(family, option_id)] = maker
    tables = {language: load_string_table(content_root, language, "List_PartManufacturer")
              for language in LANGUAGE_ARCHIVES}
    for entry in result:
        for option in entry["options"]:
            maker = makers.get((entry["family"], option["id"]))
            if maker is None:
                continue
            names = {language: resolve_string_key(table, keys.get(maker)) for language, table in tables.items()}
            if all(names.values()):
                option["manufacturer"] = names
    return result


def part_option_overlay_path(cache_root: Path | str, *, model_code: str, archive_sha256: str,
                             family: str, option_id: int) -> Path:
    from .portable_mesh_converter import LOCAL_CHASSIS_FORMAT_REVISION
    return (Path(cache_root) / PART_OPTION_CACHE_DIR
            / (f"{model_code}-{archive_sha256[:16]}-v{LOCAL_CHASSIS_FORMAT_REVISION}"
               f"-r{PART_OPTION_OVERLAY_REVISION}-{family}-{option_id}.glb"))


def prepared_part_option_overlay(asset, cache_root: Path | str, *, archive_sha256: str, family: str,
                                 option_id: int, catalog: list[dict]) -> Path:
    """選択肢の重ね合わせのGLB（無ければ変換して保存する）。catalog に無い選択肢は拒否する。"""
    allowed = {(entry["family"], option["id"]) for entry in catalog for option in entry["options"]
               if not option["is_stock"]}
    if family not in PART_OPTION_FAMILIES or type(option_id) is not int or (family, option_id) not in allowed:
        raise PartOptionOverlayError("選べない部品の選択肢です")
    if not isinstance(archive_sha256, str) or len(archive_sha256) != 64:
        raise PartOptionOverlayError("車両ZIPのSHA256がありません")
    target = part_option_overlay_path(cache_root, model_code=asset.model_code, archive_sha256=archive_sha256,
                                      family=family, option_id=option_id)
    if target.is_file():
        mark_used(target)
        return target
    from .portable_mesh_converter import convert_vehicle_model_to_glb
    target.parent.mkdir(parents=True, exist_ok=True)
    convert_vehicle_model_to_glb(asset, target, part_selection={family: option_id}, part_overlay_only=True)
    overlay = (glb_document(target)["scenes"][0].get("extras") or {}).get("lo4fh6_part_option_overlay") or {}
    if overlay.get("family") != family or overlay.get("option_id") != option_id:
        target.unlink(missing_ok=True)
        raise PartOptionOverlayError("重ね合わせのGLBの選択肢が一致しません")
    return target
