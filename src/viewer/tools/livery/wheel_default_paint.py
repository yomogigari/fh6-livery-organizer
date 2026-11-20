"""ペイントにホイール塗装の記録が無いグループへ、原本ホイールMatIの既定色を補う。

FH6のホイール塗装MaterialBin（_fmnext/wheel/wheelpaint.materialbin、Shader
car_automotive_paint）のBaseColorAlpha_Textureは共通の緑一色Swatchで、完成色ではない。
利用者がホイールを塗っていないペイント（C_liveryのホイール記録が0件）では、
ゲームは各ホイールModelBinのMatIが持つ工場出荷時の塗装色を使うと考えられる。

原本で確認した事実（2026-11-17、Vivio SUB_VivioRXR_94）：
- ホイールModelBinの塗装MatI（rim/rim2/lip/lug/inner_rim）は、それぞれ
  PaintColorColorParam・Flake・ClearCoatRoughnessをインラインで上書きしている。
- 親MaterialBin（wheelpaint）の既定PaintColorは黒（0.019）、UserLiverySwitchBool=0。
- 車ZIPのManufacturerColors.binは車体グループ（Body/Hood/Mirror/Wing等）だけで、
  carbinとGameDB（List_Wheels）にもホイールの色の値は無い。
外部製品（参照のみ）：参照製品はホイール記録が無い場合に固定の銀灰色を使い、
緑一色Swatchは色として使わない。本処理は固定値ではなく原本MatIの値を使う。

色・仕上げは既存の第一者処理で求める：Shader既定値と材質の解決は
inspect_embedded_material_instance_runtime、色はmaterial_defined_paint_color（車体の
仕上げ専用材質と同じ扱い）、PBRの数値はrelease_safe_viewer_candidate。
ただし既存の上書き読取（decode_material_override）はFH6のMTPR記録（版3、GUID付き）を
読めず、MatIのインライン値も親MaterialBinの値も反映されなかった（Vivioで実測、
Shader既定の0.212だけが残った）。車体の受入済み経路へ影響させないよう、ここでは
Tireで実績のあるFH6形式の読取（_read_parameters）で親MaterialBin→MatIの順に重ねる。
同じグループへ異なる既定色のMatIが割り当たる場合は推測で選ばず、補わない。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from . import wheel_morph_internal as wm
from .source_tire_shader_binding import TireBindingError
from .material_runtime import (
    _material_source,
    inspect_embedded_material_instance_runtime,
    material_defined_paint_color,
    release_safe_viewer_candidate,
)

ORIGIN = "original-wheel-mati-default"
# 既定の色の解決（_resolve_default）は、ペイントに依らず、車両ZIP・ゲームの _library・この処理のコードだけで
# 決まる。準備のたびに Materials.zip・Textures.zip を開いて解決していた（1 件あたり約 0.25 秒）ので、
# 解決の結果を車ごとのキャッシュ（vehicle_analysis_cache と同じ形のファイル）に、引数の組
# （ModelBin の項目・MatI の番号・MatI の SHA・材質名）ごとに置く。無い組だけ解決して足す。
WHEEL_DEFAULT_CACHE_KIND = "wheel-default-paint"
WHEEL_DEFAULT_CACHE_REVISION = "r1-20261119"
_WHEEL_DEFAULT_CODE = ("wheel_default_paint.py", "material_runtime.py", "wheel_morph_internal.py",
                       "source_tire_shader_binding.py", "body_trim_default_color.py", "fh6_swatch.py")
# ホイール塗装グループの割当が無い塗装材質（valve_stem等、経路判定unresolved）用のグループ名。
# ペイントのどのグループの色を使うべきか根拠が無いため、その材質自身の原本MatIの既定色を使う。
MATI_GROUP_PREFIX = "OriginalWheelMati:"
VIEWER_FIELDS = ("roughness", "metalness", "clearcoat", "clearcoat_roughness", "env_map_intensity")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _routing_rows(routing: dict) -> list[dict]:
    body = routing.get("routing") if isinstance(routing, dict) else None
    cars = body.get("cars") if isinstance(body, dict) else None
    rows: list[dict] = []
    for car in cars or []:
        for row in (car.get("rows") if isinstance(car, dict) else None) or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _row_groups(row: dict) -> list[str]:
    kind = row.get("route_kind")
    if kind == "axle_paint":
        names = [row.get("front_group"), row.get("rear_group")]
    elif kind == "generic_binding":
        names = [row.get("generic_group")]
    elif (kind == "unresolved" and row.get("external_input") == "g_CarUserColor0"
          and isinstance(row.get("material_instance_sha256"), str)
          and len(row["material_instance_sha256"]) == 64):
        names = [MATI_GROUP_PREFIX + row["material_instance_sha256"].lower()]
    else:
        names = []
    return [str(name) for name in names if isinstance(name, str) and name]


# 同じシェーダーの ZIP（場所・大きさ・更新日時）の名前の表を、同じプロセスの中で使い回す（2026-11-19）。
# 部品の色の解析では材質ごとに同じシェーダーの XML を開いて解釈し直していた（1 台で約 400 回）。
_SHADER_PARAMETER_NAMES: dict[tuple, dict[str, str]] = {}


def _shader_parameter_names(content_root: Path, family: str) -> dict[str, str]:
    """ShaderのXMLにある完全名を、MTPRの記録が持つCRC32（16進）へ対応づける。

    準備の範囲（shared_archive_reads）の中では、同じシェーダーの種類の答えを覚える。部品の色付けの解析で、約 430 の
    材質ごとにゲームのフォルダーのシェーダーの ZIP の stat・resolve をしていた（2026-11-20）。写しを返す。
    """
    from .material_runtime import scoped_memo
    saved = scoped_memo("shader-parameter-names", (str(content_root), str(family)),
                        lambda: _shader_parameter_names_by_file(content_root, family))
    return dict(saved)


def _shader_parameter_names_by_file(content_root: Path, family: str) -> dict[str, str]:
    """シェーダーの ZIP の識別（場所・大きさ・更新日時）ごとに覚えた対応（呼び出し側が写す）。"""
    shaders = Path(content_root) / "media" / "cars" / "_library" / "shaders" / (family + ".zip")
    try:
        stat = shaders.stat()
    except OSError:
        return {}
    if not shaders.is_file():
        return {}
    key = (str(shaders.resolve()), stat.st_size, stat.st_mtime_ns)
    saved = _SHADER_PARAMETER_NAMES.get(key)
    if saved is None:
        saved = _read_shader_parameter_names(shaders)
        if len(_SHADER_PARAMETER_NAMES) >= 128:
            _SHADER_PARAMETER_NAMES.pop(next(iter(_SHADER_PARAMETER_NAMES)))
        _SHADER_PARAMETER_NAMES[key] = saved
    return saved


def _read_shader_parameter_names(shaders: Path) -> dict[str, str]:
    from xml.etree import ElementTree as ET
    import zlib
    with zipfile.ZipFile(shaders) as archive:
        xml = [n for n in archive.namelist() if n.casefold().endswith(".shaderbin.xml")]
        if len(xml) != 1:
            return {}
        root = ET.fromstring(archive.read(xml[0]))
    names: dict[str, str] = {}
    for element in root.iter():
        name = element.get("parametername")
        if name:
            names[f"{zlib.crc32(name.encode('ascii')):08x}"] = name
    return names


def _layer_overrides(effective: dict, names: dict[str, str], blobs: list[bytes]) -> int:
    """FH6のMTPR（親MaterialBin→MatIの順）の値をShader既定値へ重ねる。重ねた件数を返す。"""
    from .source_tire_shader_binding import _read_parameters
    count = 0
    for blob in blobs:
        for row in _read_parameters(blob):
            name = names.get(row.get("parameter_crc32"))
            kind, value = row.get("type"), row.get("value")
            if not name or kind == 6:
                continue
            if kind == 3:
                value = bool(value)
            elif kind in (0, 1, 11):
                value = [float(v) for v in value]
            effective[name] = {"value": value}
            count += 1
    return count


def _mtpr_blobs(data: bytes) -> list[bytes]:
    return [bytes(b.data) for b in wm._parse_blobs(data) if b.tag == 0x4D545052]


def _resolve_default(archive: zipfile.ZipFile, index: dict[str, str], entry: str, material_id: int,
                     mati_sha: str | None, label: str, content_root: Path,
                     vehicle_archive: Path) -> dict | None:
    member = index.get(entry.replace("\\", "/").casefold())
    if member is None:
        return None
    blobs = [b for b in wm._parse_blobs(archive.read(member))
             if b.tag == 0x4D617449 and b.identifier == material_id]
    if len(blobs) != 1:
        return None
    data = bytes(blobs[0].data)
    if mati_sha and _sha(data) != mati_sha:
        return None
    runtime = inspect_embedded_material_instance_runtime(
        content_root, data, material_label=label, vehicle_archive=vehicle_archive)
    if not runtime.get("available"):
        return None
    family = str(runtime.get("shader_family") or "")
    effective = dict(runtime.get("effective_focus") or {})
    names = _shader_parameter_names(content_root, family)
    try:
        base_data, _ = _material_source(content_root, str(runtime.get("resolved_material_path") or ""),
                                        vehicle_archive)
        blobs = _mtpr_blobs(base_data) + _mtpr_blobs(data)
        try:
            layered = _layer_overrides(effective, names, blobs)
        except TireBindingError:
            # ホイールのエンブレム（ARI_Nomad_16・RAD_RXC_15 の wheel_emblem 等）は、MatI の Texture の参照が
            # cars/_library/textures の外にあり、厳密な読取が止まる。ランプの発光部と同じ寛容な読取で、
            # 色・数値だけを重ね直す（Texture の参照は使わない。未知の型は止まる）。
            from .body_trim_default_color import _layer_overrides_tolerant
            effective = dict(runtime.get("effective_focus") or {})
            layered = _layer_overrides_tolerant(effective, names, blobs)
    except Exception:  # noqa: BLE001  原本の読取に失敗したら補わない（推測しない）
        return None
    if layered == 0:
        return None
    color = material_defined_paint_color(effective, family)
    if not color.get("available") or not color.get("rgba_hex"):
        return None
    material_name = Path(str(runtime.get("resolved_material_path") or "").replace("\\", "/")).stem
    candidate, parameters = release_safe_viewer_candidate(
        material_name, family, effective,
        source="installed_fh6_material_runtime+" + ORIGIN)
    if not isinstance(candidate, dict) or any(
            not isinstance(candidate.get(key), (int, float)) for key in VIEWER_FIELDS):
        return None
    return {
        "primary_color_enabled": True,
        "primary_color_rgba_hex": str(color["rgba_hex"]),
        "secondary_color_enabled": False,
        "secondary_color_rgba_hex": "#00000000",
        "color_origin": ORIGIN,
        "finish_material": {
            "finish_origin": ORIGIN,
            "catalog_match": False,
            "material_name": material_name,
            "shader_family": family,
            "viewer_candidate": candidate,
            "game_material_parameters": parameters,
            "source_material_sha256": runtime.get("resolved_material_sha256"),
            "source_material_instance_sha256": runtime.get("material_sha256"),
            "source_shader_sha256": runtime.get("shader_sha256"),
            "source_modelbin_entry": entry,
            "source_material_id": material_id,
            "source_override_layers": "shaderbin_default+parent_materialbin_mtpr+modelbin_mati_mtpr",
            "num_input_colors": 1,
        },
    }


class _DefaultCache:
    """車ごとの既定の色の解決の結果（引数の組 → 記録または None）。読めない・書けないときは使わない。"""

    def __init__(self, cache_root: Path, content_root: Path, vehicle_archive: Path):
        from .vehicle_analysis_cache import (
            FORMAT, analysis_cache_key, file_identity, installed_library_identity, mark_used,
            module_sources_sha256,
        )
        here = Path(__file__).resolve().parent
        self._format = FORMAT
        self.records: dict[str, dict | None] = {}
        self.path: Path | None = None
        self.changed = False
        vehicle = file_identity(vehicle_archive)
        if vehicle is None:
            return
        inputs = {
            "vehicle_archive": vehicle,
            "content_root": str(Path(content_root).resolve()),
            "library": installed_library_identity(content_root),
            "code": module_sources_sha256([here / name for name in _WHEEL_DEFAULT_CODE]),
        }
        self.key = analysis_cache_key(WHEEL_DEFAULT_CACHE_KIND, WHEEL_DEFAULT_CACHE_REVISION, inputs)
        self.vehicle = Path(vehicle_archive).stem
        self.path = Path(cache_root) / WHEEL_DEFAULT_CACHE_KIND / f"{self.key}.json"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        result = saved.get("result") if isinstance(saved, dict) else None
        if (isinstance(saved, dict) and saved.get("format") == FORMAT
                and saved.get("kind") == WHEEL_DEFAULT_CACHE_KIND and saved.get("key") == self.key
                and isinstance(result, dict) and isinstance(result.get("records"), dict)):
            self.records = {str(k): v for k, v in result["records"].items() if v is None or isinstance(v, dict)}
            mark_used(self.path)

    @staticmethod
    def slot(entry: str, material_id: int, key: str, label: str) -> str:
        return json.dumps([entry, material_id, key, label], ensure_ascii=False)

    def get(self, slot: str) -> tuple[bool, dict | None]:
        if slot not in self.records:
            return False, None
        saved = self.records[slot]
        return True, (None if saved is None else json.loads(json.dumps(saved, ensure_ascii=False)))

    def put(self, slot: str, record: dict | None) -> None:
        if self.path is None:
            return
        try:
            self.records[slot] = None if record is None else json.loads(json.dumps(record, ensure_ascii=False))
        except (TypeError, ValueError):
            return
        self.changed = True

    def save(self) -> None:
        if self.path is None or not self.changed:
            return
        import os
        import time
        folder = self.path.parent
        temporary = folder / f".{self.key}.{os.getpid()}.tmp"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({
                "format": self._format, "kind": WHEEL_DEFAULT_CACHE_KIND, "key": self.key,
                "metadata": {"vehicle": self.vehicle, "revision": WHEEL_DEFAULT_CACHE_REVISION},
                "created": time.time(), "result": {"records": self.records},
            }, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            pass
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass


def add_original_wheel_default_paint(wheel_paint: dict, routing: dict, *, content_root: Path,
                                     vehicle_archive: Path, cache_root: Path | None = None) -> dict:
    """ペイントに有効な記録が無いホイール塗装メッシュへ、そのメッシュの原本MatIの既定色を加える。

    既定色はMatI単位（OriginalWheelMati:<MatI SHA>）で持つ。同じグループに既定色の異なる
    MatI（例：rimとvalve_cap）が割り当たる車種や、グループ割当の無い材質（valve_stem、
    wheel_emblem等）も、メッシュごとに自分のMatIの値を使える。Viewerは、メッシュの
    グループにペイントの有効な記録が無いときだけ、この記録を使う。
    戻り値は同じ辞書（groupsへ追記）。補ったMatIと、補えなかった理由を記録する。
    呼出し元（VehicleAsset.archive_path）は文字列のこともあるため、Pathへ揃える。
    cache_root を渡すと、MatI ごとの解決の結果を車ごとのキャッシュから使い、無い組だけ解決して足す。
    """
    content_root = Path(content_root)
    vehicle_archive = Path(vehicle_archive)
    groups = wheel_paint.setdefault("groups", {})
    need: dict[str, tuple[str, int, str]] = {}
    unresolved: dict[str, str] = {}
    for row in _routing_rows(routing):
        entry, material_id = row.get("source_entry"), row.get("material_id")
        mati_sha = str(row.get("material_instance_sha256") or "").lower()
        if (not isinstance(entry, str) or type(material_id) is not int
                or row.get("external_input") not in (None, "g_CarUserColor0")):
            continue
        names = _row_groups(row)
        unassigned = row.get("route_kind") == "unresolved"
        missing = [g for g in names if not g.startswith(MATI_GROUP_PREFIX)
                   and not (isinstance(groups.get(g), dict)
                            and groups[g].get("primary_color_enabled") is True)]
        if not unassigned and not missing:
            continue
        if len(mati_sha) != 64:
            unresolved[f"{entry}#{material_id}"] = "原本MatIのSHAが経路判定に無い"
            continue
        need.setdefault(MATI_GROUP_PREFIX + mati_sha,
                        (entry, material_id, str(row.get("material_name") or "")))
    added: list[str] = []
    if need and vehicle_archive.is_file():
        cache = _DefaultCache(cache_root, content_root, vehicle_archive) if cache_root is not None else None
        resolved: dict[str, dict | None] = {}
        missing: list[tuple[str, str, int, str, str]] = []
        for key, (entry, material_id, label) in sorted(need.items()):
            slot = _DefaultCache.slot(entry, material_id, key, label)
            hit, record = cache.get(slot) if cache is not None else (False, None)
            if hit:
                resolved[key] = record
            else:
                missing.append((key, entry, material_id, label, slot))
        if missing:
            with zipfile.ZipFile(vehicle_archive) as archive:
                index = {name.replace("\\", "/").casefold(): name for name in archive.namelist()}
                for key, entry, material_id, label, slot in missing:
                    record = _resolve_default(archive, index, entry, material_id,
                                              key[len(MATI_GROUP_PREFIX):], label, content_root,
                                              vehicle_archive)
                    if cache is not None:
                        cache.put(slot, record)
                    resolved[key] = record
            if cache is not None:
                cache.save()
        for key in sorted(need):
            record = resolved[key]
            if record is None:
                unresolved[key] = "原本MatIの塗装色または仕上げを解決できない"
                continue
            record["paintable_group"] = key
            groups[key] = record
            added.append(key)
    elif need:
        unresolved.update({key: "車両ZIPが見つからない" for key in need})
    wheel_paint["original_default_paint_groups"] = sorted(added)
    wheel_paint["original_default_paint_unresolved"] = unresolved
    wheel_paint["original_default_paint_boundary"] = (
        "ペイントに有効なホイール記録が無いメッシュだけ、そのメッシュの原本ホイールMatIのPaintColor"
        "（MatI→親MaterialBin→ShaderBin既定値）と仕上げの数値を使う。Xbox外観は未承認。")
    return wheel_paint
