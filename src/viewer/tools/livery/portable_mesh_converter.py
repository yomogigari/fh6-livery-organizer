#!/usr/bin/env python3
"""Livery Inspector用のローカルFH6 ModelBin→GLB変換。"""

from __future__ import annotations

import copy
import json
from hashlib import sha256
import math
import os
import struct
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .vehicle_assets import VehicleAsset, inspection_carbin_entry, inspection_model_entries


class PortableMeshConverterError(RuntimeError):
    pass


class ChassisConversionCancelled(PortableMeshConverterError):
    pass


MAX_LOCAL_CHASSIS_BYTES = 256 * 1024 * 1024
MAX_CONVERTER_RESIDENT_BYTES = 2 * 1024 * 1024 * 1024
LOCAL_CHASSIS_FORMAT_REVISION = 20
GLB_JSON_CHUNK = 0x4E4F534A
GLB_BINARY_CHUNK = 0x004E4942
ROLE_NAMES = {"paint", "glass", "hidden", "dark", "trim"}
ACCESSOR_COMPONENT_BYTES = {5121: 1, 5123: 2, 5125: 4, 5126: 4}
ACCESSOR_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


@dataclass(frozen=True)
class LocalProjectionMesh:
    name: str
    role: str
    projection_sides: int
    positions: np.ndarray
    normals: np.ndarray
    indices: np.ndarray


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 新しい第一者GLBにはLO4FH6のメタデータ名（lo4fh6_*）を永続化し、内部の旧名（lo4_*）は書き込まない。
# 受入済みWheel／Material処理には旧名をメモリ内だけで提示する。
_FIRSTPARTY_CHASSIS_FORMAT = "lo4fh6_source_chassis_scene_v1"
_FIRSTPARTY_META_FIELDS = frozenset({
    "role", "source_entry", "source_mesh_name", "material_name",
    "part_type", "instance_identity", "stock_part", "part_option_ids",
    "draw_groups", "allowed_sides", "projection_sides",
    "material_binding_hash", "part_options", "base_visible",
    "source_wheel_name", "game_fit", "body_kit_overlay",
})


def _firstparty_metadata_records(document: dict) -> list[dict]:
    rows = []
    for section in ("scenes", "nodes", "meshes"):
        for item in document.get(section, []):
            if isinstance(item, dict) and isinstance(item.get("extras"), dict):
                rows.append(item["extras"])
            if section == "meshes" and isinstance(item, dict):
                for primitive in item.get("primitives", []):
                    if isinstance(primitive, dict) and isinstance(primitive.get("extras"), dict):
                        rows.append(primitive["extras"])
    return rows


def _firstparty_is_neutral(document: dict) -> bool:
    return any(
        isinstance(scene, dict) and isinstance(scene.get("extras"), dict)
        and scene["extras"].get("lo4fh6_format") == _FIRSTPARTY_CHASSIS_FORMAT
        for scene in document.get("scenes", [])
    )


def _firstparty_serialized_suffix(suffix: str) -> bool:
    return (suffix in _FIRSTPARTY_META_FIELDS
            or suffix.startswith("wheel_") or suffix.startswith("tire_"))


# 鍵の名前 → 付け替え先の名前（対象でなければ None）。1 つの GLB で約 10 万個の鍵を見るが、名前の種類は少ないので、
# 名前ごとの判定を覚えて使い回す（判定と付け替えの順は以前と同じ。2026-11-20）。
_ADOPT_NAMES: dict[str, str | None] = {}
_SEAL_NAMES: dict[str, str | None] = {}
_NAME_MEMO_LIMIT = 4096
_UNSEEN = object()


def _adopt_name(key: str) -> str | None:
    """lo4fh6_* の鍵の、互換の旧名（lo4_*）。対象でなければ None。"""
    legacy = None
    if key.startswith("lo4fh6_"):
        suffix = key[7:]
        if _firstparty_serialized_suffix(suffix):
            legacy = "lo4_" + suffix
    if len(_ADOPT_NAMES) < _NAME_MEMO_LIMIT:
        _ADOPT_NAMES[key] = legacy
    return legacy


def _seal_name(key: str) -> str | None:
    """lo4_* の鍵の、独立した名前（lo4fh6_*）。対象でなければ None。"""
    modern = None
    if key.startswith("lo4_") and _firstparty_serialized_suffix(key[len("lo4_"):]):
        modern = "lo4fh6_" + key[len("lo4_"):]
    if len(_SEAL_NAMES) < _NAME_MEMO_LIMIT:
        _SEAL_NAMES[key] = modern
    return modern


def adopt_firstparty_chassis_metadata(document: dict) -> dict:
    """受入済みWheel／Paint処理に一時的な互換キーを提示する。"""
    if not _firstparty_is_neutral(document):
        return document
    names = _ADOPT_NAMES
    for extras in _firstparty_metadata_records(document):
        for key, value in list(extras.items()):
            legacy = names.get(key, _UNSEEN)
            if legacy is _UNSEEN:
                legacy = _adopt_name(key)
            if legacy is None:
                continue
            if legacy in extras and extras[legacy] != value:
                raise PortableMeshConverterError("Conflicting GLB metadata aliases: " + key[7:])
            extras[legacy] = value
    return document


def seal_firstparty_chassis_metadata(document: dict) -> dict:
    """旧名互換のWheel／Tire更新後、独立した名前で保存する。"""
    if not _firstparty_is_neutral(document):
        return document
    names = _SEAL_NAMES
    for extras in _firstparty_metadata_records(document):
        for key, value in list(extras.items()):
            modern = names.get(key, _UNSEEN)
            if modern is _UNSEEN:
                modern = _seal_name(key)
            if modern is not None:
                # Wheel Morph段階で一時的な旧名キーの値が更新されている可能性がある。
                extras[modern] = value
                del extras[key]
    return document


def _glb_payloads(path: Path) -> tuple[dict, bytes]:
    if not path.is_file() or path.stat().st_size > MAX_LOCAL_CHASSIS_BYTES:
        raise PortableMeshConverterError("The converted chassis GLB has an unsupported size.")
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise PortableMeshConverterError("The local chassis converter did not create a valid GLB file.")
    if struct.unpack_from("<I", data, 4)[0] != 2:
        raise PortableMeshConverterError("The converted chassis is not a GLB 2.0 file.")
    declared_length = struct.unpack_from("<I", data, 8)[0]
    if declared_length != len(data):
        raise PortableMeshConverterError("The converted chassis GLB has an invalid length declaration.")
    cursor = 12
    document: dict | None = None
    binary: bytes | None = None
    while cursor + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        if length % 4 or cursor + length > len(data):
            raise PortableMeshConverterError("The converted chassis GLB has an invalid chunk boundary.")
        payload = data[cursor : cursor + length]
        cursor += length
        if chunk_type == GLB_JSON_CHUNK:
            if document is not None:
                raise PortableMeshConverterError("The converted chassis GLB has duplicate JSON chunks.")
            try:
                parsed = json.loads(
                    payload.rstrip(b"\x00 \t\r\n"),
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise PortableMeshConverterError("The converted chassis GLB document is invalid.") from exc
            if not isinstance(parsed, dict):
                raise PortableMeshConverterError("The converted chassis GLB document is invalid.")
            document = parsed
        elif chunk_type == GLB_BINARY_CHUNK:
            if binary is not None:
                raise PortableMeshConverterError("The converted chassis GLB has duplicate binary chunks.")
            binary = payload
    if cursor != len(data) or document is None or binary is None:
        raise PortableMeshConverterError("The converted chassis GLB is incomplete.")
    return adopt_firstparty_chassis_metadata(document), binary


def _glb_document(path: Path) -> dict:
    return _glb_payloads(path)[0]


def _document_array(document: dict, key: str) -> list:
    value = document.get(key)
    if not isinstance(value, list):
        raise PortableMeshConverterError(f"The converted chassis has an invalid GLB {key} array.")
    return value


def _array_index(value: object, rows: list, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= len(rows):
        raise PortableMeshConverterError(f"The converted chassis has an invalid GLB {label} index.")
    return value


def _validate_accessor(document: dict, binary: bytes, index: object) -> dict:
    accessors = _document_array(document, "accessors")
    views = _document_array(document, "bufferViews")
    try:
        accessor_index = _array_index(index, accessors, "accessor")
        accessor = accessors[accessor_index]
        if not isinstance(accessor, dict):
            raise TypeError("accessor is not an object")
        view_index = _array_index(accessor["bufferView"], views, "bufferView")
        view = views[view_index]
        if not isinstance(view, dict):
            raise TypeError("bufferView is not an object")
        component_size = ACCESSOR_COMPONENT_BYTES[int(accessor["componentType"])]
        component_count = ACCESSOR_COMPONENTS[str(accessor["type"])]
        count = int(accessor["count"])
        view_offset = int(view.get("byteOffset") or 0)
        view_length = int(view["byteLength"])
        accessor_offset = int(accessor.get("byteOffset") or 0)
        stride = int(view.get("byteStride") or (component_size * component_count))
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise PortableMeshConverterError("The converted chassis has an invalid GLB accessor.") from exc
    required = accessor_offset + ((count - 1) * stride if count else 0) + component_size * component_count
    if (
        int(view.get("buffer") or 0) != 0
        or count <= 0
        or view_offset < 0
        or view_length <= 0
        or accessor_offset < 0
        or stride < component_size * component_count
        or required > view_length
        or view_offset + view_length > len(binary)
    ):
        raise PortableMeshConverterError("The converted chassis GLB accessor is outside its binary buffer.")
    for key in ("min", "max"):
        values = accessor.get(key)
        if values is not None and (
            not isinstance(values, list)
            or len(values) != component_count
            or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values)
        ):
            raise PortableMeshConverterError("The converted chassis GLB accessor bounds are invalid.")
    return accessor


def _actual_index_max(document: dict, binary: bytes, accessor_index: object) -> int:
    accessors = _document_array(document, "accessors")
    views = _document_array(document, "bufferViews")
    index = _array_index(accessor_index, accessors, "accessor")
    accessor = accessors[index]
    view = views[_array_index(accessor["bufferView"], views, "bufferView")]
    component_type = int(accessor["componentType"])
    count = int(accessor["count"])
    component_size = ACCESSOR_COMPONENT_BYTES[component_type]
    stride = int(view.get("byteStride") or component_size)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    format_code = "H" if component_type == 5123 else "I"
    if stride == component_size:
        end = start + count * component_size
        data = binary[start:end]
        # 連続した 16・32 ビットの番号は numpy でまとめて最大値を求める（Python の繰り返しで数百万回比べない）。
        # それ以外の形は従来どおり（結果と例外を変えない）。
        if component_type in (5123, 5125) and data and len(data) % component_size == 0:
            return int(np.frombuffer(data, dtype="<u2" if component_type == 5123 else "<u4").max())
        return max(value[0] for value in struct.iter_unpack(f"<{format_code}", data))
    unpack = struct.Struct(f"<{format_code}").unpack_from
    return max(unpack(binary, start + offset * stride)[0] for offset in range(count))


def _accessor_array(
    document: dict,
    binary: bytes,
    accessor_index: object,
    *,
    component_type: int,
    value_type: str,
) -> np.ndarray:
    accessor = _validate_accessor(document, binary, accessor_index)
    if int(accessor.get("componentType") or 0) != component_type or accessor.get("type") != value_type:
        raise PortableMeshConverterError("The converted chassis geometry accessor has an unexpected type.")
    accessors = _document_array(document, "accessors")
    views = _document_array(document, "bufferViews")
    index = _array_index(accessor_index, accessors, "accessor")
    accessor = accessors[index]
    view = views[_array_index(accessor["bufferView"], views, "bufferView")]
    component_count = ACCESSOR_COMPONENTS[value_type]
    component_size = ACCESSOR_COMPONENT_BYTES[component_type]
    item_size = component_count * component_size
    count = int(accessor["count"])
    stride = int(view.get("byteStride") or item_size)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    dtype = np.dtype("<f4" if component_type == 5126 else "<u2" if component_type == 5123 else "<u4")
    if stride == item_size:
        values = np.frombuffer(binary, dtype=dtype, count=count * component_count, offset=start)
        return values.reshape(count, component_count) if component_count > 1 else values

    output = np.empty((count, component_count), dtype=dtype)
    for row in range(count):
        output[row] = np.frombuffer(
            binary,
            dtype=dtype,
            count=component_count,
            offset=start + row * stride,
        )
    return output if component_count > 1 else output[:, 0]


def read_local_chassis_projection_meshes(path: Path | str) -> list[LocalProjectionMesh]:
    """ローカルMask位置合わせだけに使うワールド座標Meshを読み取る。"""

    glb_path = Path(path)
    validate_local_chassis_glb(glb_path)
    document, binary = _glb_payloads(glb_path)
    meshes = _document_array(document, "meshes")
    result: list[LocalProjectionMesh] = []
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise PortableMeshConverterError("The converted chassis has an invalid mesh record.")
        extras = mesh.get("extras") or {}
        role = str(extras.get("lo4_role") or "")
        projection_sides = int(extras.get("lo4_projection_sides") or 0)
        if role not in {"paint", "glass"} or projection_sides == 0:
            continue
        for primitive_index, primitive in enumerate(mesh.get("primitives") or []):
            attributes = primitive.get("attributes") or {}
            if "TEXCOORD_3" in attributes:
                continue
            positions = _accessor_array(
                document,
                binary,
                attributes["POSITION"],
                component_type=5126,
                value_type="VEC3",
            )
            normals = _accessor_array(
                document,
                binary,
                attributes["NORMAL"],
                component_type=5126,
                value_type="VEC3",
            )
            index_accessor = _validate_accessor(document, binary, primitive["indices"])
            index_component = int(index_accessor.get("componentType") or 0)
            indices = _accessor_array(
                document,
                binary,
                primitive["indices"],
                component_type=index_component,
                value_type="SCALAR",
            ).astype(np.int64, copy=False)
            result.append(LocalProjectionMesh(
                name=f"{mesh.get('name') or f'mesh-{mesh_index}'}:{primitive_index}",
                role=role,
                projection_sides=projection_sides,
                positions=positions,
                normals=normals,
                indices=indices,
            ))
    return result


def validate_product_chassis_glb_provenance(document: dict) -> None:
    """通常製品へ研究GLBを混入させない。旧参照製品受入済みGLBはそのまま許可。

    研究段階の原本Stock GLBは構造検証できてもXbox外観・Skin/Morph・
    Shader/ガラス・原本車輪が未承認。キャッシュからの再読込時も必ず拒否。
    """
    if not isinstance(document, dict):
        raise PortableMeshConverterError("The chassis product GLB metadata is invalid.")
    asset = document.get("asset")
    if not isinstance(asset, dict):
        raise PortableMeshConverterError("The chassis product GLB asset is invalid.")
    generator = str(asset.get("generator") or "")
    is_firstparty = generator.startswith("LO4FH6 firstparty")
    scenes = document.get("scenes")
    if not isinstance(scenes, list):
        raise PortableMeshConverterError("The chassis product GLB scenes are invalid.")
    # 全Sceneを調べる。製品既定Scene以外に未承認面を隠して持ち込めない。
    seen_explicit_acceptance = False
    source_static_preview = False
    for scene in scenes:
        if not isinstance(scene, dict):
            raise PortableMeshConverterError("The chassis product GLB scene is invalid.")
        extras = scene.get("extras")
        if extras is None:
            extras = {}
        if not isinstance(extras, dict):
            raise PortableMeshConverterError("The chassis product GLB scene metadata is invalid.")
        source_static = (
            is_firstparty
            and extras.get("lo4fh6_static_preview_source_verified") is True
            and extras.get("lo4fh6_static_preview_scope")
                in {"ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE",
                    "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"}
            and (extras.get("lo4fh6_static_preview_scope") !=
                 "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"
                 or extras.get("lo4fh6_loose_entry_source_verified") is True)
            and extras.get("lo4fh6_release_approval") is False
            and extras.get("lo4fh6_xbox_visual_approval") is False
            and "lo4fh6_research_only" not in extras
        )
        if ("lo4fh6_research_only" in extras
                or (extras.get("lo4fh6_release_approval") is False and not source_static)):
            raise PortableMeshConverterError(
                "Research-only first-party chassis GLB cannot enter the accepted product cache."
            )
        source_static_preview |= source_static
        seen_explicit_acceptance |= (
            extras.get("lo4fh6_release_approval") is True or source_static
        )
    if is_firstparty and not seen_explicit_acceptance:
        raise PortableMeshConverterError(
            "First-party chassis GLB requires explicit product approval; cache fallback is forbidden."
        )
    research_mesh_flags = (
        "lo4fh6_not_game_runtime_appearance",
        "lo4fh6_nonroot_attachment_unverified",
        "lo4fh6_original_material_shader_gpu_unverified",
        "lo4fh6_original_wheel_fitment_unverified",
        "lo4fh6_shader_role_trial_unapproved",
    )
    for category in ("nodes", "meshes"):
        items = document.get(category)
        if not isinstance(items, list):
            raise PortableMeshConverterError("The chassis product GLB geometry metadata is invalid.")
        for item in items:
            if not isinstance(item, dict):
                continue  # 後段の幾何検証で拒否する
            extras = item.get("extras")
            if extras is None:
                extras = {}
            if not isinstance(extras, dict):
                raise PortableMeshConverterError("The chassis product GLB geometry metadata is invalid.")
            if source_static_preview:
                # 原本参照製品 Static由来の「機能的なViewer入力」としてのみ受け入れる。
                # ゲーム実行時の変形・Wheel装着・Shader一致は保証せず、
                # 未確認事項をextrasに残す。
                if (extras.get("lo4fh6_source_static_instance_verified") is not True
                    and extras.get("lo4fh6_lo4_static_instance_verified") is not True):
                    raise PortableMeshConverterError(
                        "First-party static Viewer input lacks source mesh provenance."
                    )
                if any(
                    isinstance(scene, dict) and isinstance(scene.get("extras"), dict)
                    and scene["extras"].get("lo4fh6_static_preview_scope")
                        == "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"
                    for scene in scenes
                ) and extras.get("lo4fh6_original_loose_modelbin_verified") is not True:
                    raise PortableMeshConverterError(
                        "Original loose ModelBin mesh source provenance is missing."
                    )
                disallowed = {"lo4fh6_shader_role_trial_unapproved"}
            else:
                disallowed = set(research_mesh_flags)
            if any(extras.get(flag) is True for flag in disallowed):
                raise PortableMeshConverterError(
                    "Unverified source geometry is not allowed in the accepted product cache."
                )


# 同じプロセスの中で、同じファイル（場所・大きさ・更新日時・ファイルの番号）を同じ条件で検査した結果を覚え、
# 2 回目からは読み直さない（準備ではブリッジと vehicle_preview が同じ車体の GLB を続けて検査していた。2026-11-19）。
# 覚えるのは検査に通った結果だけ。ファイルが置き換わると番号・更新日時が変わるので、もう一度検査する。
_VALIDATED_CHASSIS: dict[tuple, dict[str, int]] = {}
_VALIDATED_CHASSIS_LIMIT = 32
_VALIDATED_CHASSIS_LOCK = threading.Lock()


def _chassis_validation_key(glb_path: Path, require_product_accepted: bool,
                            required_firstparty_scope: str | None) -> tuple | None:
    try:
        stat = glb_path.stat()
        resolved = str(glb_path.resolve())
    except OSError:
        return None
    return (resolved, stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev,
            bool(require_product_accepted), required_firstparty_scope)


def validate_local_chassis_glb(path: Path | str, *, require_product_accepted: bool = False, required_firstparty_scope: str | None = None) -> dict[str, int]:
    glb_path = Path(path)
    key = _chassis_validation_key(glb_path, require_product_accepted, required_firstparty_scope)
    if key is not None:
        with _VALIDATED_CHASSIS_LOCK:
            saved = _VALIDATED_CHASSIS.get(key)
        if saved is not None:
            return copy.deepcopy(saved)
    result = _validate_local_chassis_glb(glb_path, require_product_accepted=require_product_accepted,
                                         required_firstparty_scope=required_firstparty_scope)
    if key is not None:
        with _VALIDATED_CHASSIS_LOCK:
            if len(_VALIDATED_CHASSIS) >= _VALIDATED_CHASSIS_LIMIT:
                _VALIDATED_CHASSIS.pop(next(iter(_VALIDATED_CHASSIS)))
            _VALIDATED_CHASSIS[key] = copy.deepcopy(result)
    return result


def _validate_local_chassis_glb(glb_path: Path, *, require_product_accepted: bool,
                                required_firstparty_scope: str | None) -> dict[str, int]:
    document, binary = _glb_payloads(glb_path)
    if require_product_accepted:
        validate_product_chassis_glb_provenance(document)
    if required_firstparty_scope is not None:
        if (not require_product_accepted
                or required_firstparty_scope not in {
                    "ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE",
                    "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE",
                }
                or not str((document.get("asset") or {}).get("generator") or "").startswith(
                    "LO4FH6 firstparty original-static functional Viewer candidate"
                )
                or not isinstance(document.get("scenes"), list)
                or len(document["scenes"]) != 1
                or not isinstance(document["scenes"][0], dict)
                or not isinstance(document["scenes"][0].get("extras"), dict)
                or document["scenes"][0]["extras"].get("lo4fh6_static_preview_source_verified") is not True
                or document["scenes"][0]["extras"].get("lo4fh6_static_preview_scope") != required_firstparty_scope):
            raise PortableMeshConverterError(
                "Refusing legacy/research GLB cache in first-party Viewer mode."
            )
    if str((document.get("asset") or {}).get("version") or "") != "2.0":
        raise PortableMeshConverterError("The converted chassis GLB document is not version 2.0.")
    try:
        buffers = _document_array(document, "buffers")
        declared_binary_length = int(buffers[0]["byteLength"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise PortableMeshConverterError("The converted chassis GLB binary declaration is invalid.") from exc
    if len(buffers) != 1 or not isinstance(buffers[0], dict) or not 0 <= declared_binary_length <= len(binary):
        raise PortableMeshConverterError("The converted chassis GLB binary declaration is invalid.")
    nodes = _document_array(document, "nodes")
    meshes = _document_array(document, "meshes")
    scenes = _document_array(document, "scenes")
    part_options: list[dict] = []
    option_keys: set[tuple[str, int]] = set()
    if scenes:
        scene = scenes[_array_index(document.get("scene", 0), scenes, "scene")]
        if not isinstance(scene, dict):
            raise PortableMeshConverterError("The converted chassis has an invalid GLB scene record.")
        raw_options = (scene.get("extras") or {}).get("lo4_part_options") or []
        if not isinstance(raw_options, list) or any(not isinstance(item, dict) for item in raw_options):
            raise PortableMeshConverterError("The converted chassis has invalid part-option metadata.")
        for option in raw_options:
            try:
                part_name = str(option["part_type"]).strip()
                part_type = int(option["part_type_value"])
                option_id = int(option["id"])
                level = int(option["level"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PortableMeshConverterError("The converted chassis has invalid part-option metadata.") from exc
            key = (part_name, option_id)
            if not part_name or part_type < 0 or level < 0 or key in option_keys:
                raise PortableMeshConverterError("The converted chassis has invalid part-option metadata.")
            option_keys.add(key)
            part_options.append(option)
    source_static_preview = any(
        isinstance(scene, dict)
        and isinstance(scene.get("extras"), dict)
        and scene["extras"].get("lo4fh6_static_preview_source_verified") is True
        and scene["extras"].get("lo4fh6_static_preview_scope")
            in {"ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE",
                "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"}
        for scene in scenes
    )
    overlay_source_preview = any(
        isinstance(scene, dict) and isinstance(scene.get("extras"), dict)
        and scene["extras"].get("lo4fh6_static_preview_scope")
            == "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"
        and scene["extras"].get("lo4fh6_loose_entry_source_verified") is True
        for scene in scenes
    )
    roles: dict[int, str] = {}
    allowed_sides: dict[int, object] = {}
    projection_sides: dict[int, object] = {}
    for node in nodes:
        if not isinstance(node, dict) or "mesh" not in node:
            continue
        extras = node.get("extras") or {}
        role = str(extras.get("lo4_role") or "")
        mesh_index = _array_index(node["mesh"], meshes, "mesh")
        roles[mesh_index] = role
        if "lo4_allowed_sides" in extras:
            allowed_sides[mesh_index] = extras["lo4_allowed_sides"]
        if "lo4_projection_sides" in extras:
            projection_sides[mesh_index] = extras["lo4_projection_sides"]
    paint = 0
    glass = 0
    direct_uv3 = 0
    projected = 0
    triangles = 0
    for index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise PortableMeshConverterError("The converted chassis has an invalid mesh record.")
        extras = mesh.get("extras") or {}
        role = str(extras.get("lo4_role") or roles.get(index) or "")
        if role not in ROLE_NAMES:
            raise PortableMeshConverterError("The converted chassis has an invalid material role.")
        raw_allowed = extras.get("lo4_allowed_sides", allowed_sides.get(index))
        raw_projection = extras.get("lo4_projection_sides", projection_sides.get(index))
        raw_option_ids = extras.get("lo4_part_option_ids") or []
        part_type = str(extras.get("lo4_part_type") or "").strip()
        if not isinstance(raw_option_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in raw_option_ids
        ):
            raise PortableMeshConverterError("The converted chassis has invalid mesh part-option metadata.")
        if raw_option_ids and (
            not part_type or any((part_type, option_id) not in option_keys for option_id in raw_option_ids)
        ):
            raise PortableMeshConverterError("The converted chassis references an unknown car-part option.")
        declared_allowed: int | None = None
        if raw_allowed is not None:
            if isinstance(raw_allowed, bool) or not isinstance(raw_allowed, (int, float)):
                raise PortableMeshConverterError("The converted chassis has an invalid livery-side declaration.")
            if isinstance(raw_allowed, float) and (not math.isfinite(raw_allowed) or not raw_allowed.is_integer()):
                raise PortableMeshConverterError("The converted chassis has an invalid livery-side declaration.")
            declared_allowed = int(raw_allowed)
            if declared_allowed < 0 or declared_allowed > 0x7FF:
                raise PortableMeshConverterError("The converted chassis has an invalid livery-side declaration.")
        declared_projection: int | None = None
        if raw_projection is not None:
            if isinstance(raw_projection, bool) or not isinstance(raw_projection, (int, float)):
                raise PortableMeshConverterError("The converted chassis has an invalid projection-side declaration.")
            if isinstance(raw_projection, float) and (
                not math.isfinite(raw_projection) or not raw_projection.is_integer()
            ):
                raise PortableMeshConverterError("The converted chassis has an invalid projection-side declaration.")
            declared_projection = int(raw_projection)
            if declared_projection < 0 or declared_projection > 0x7FF:
                raise PortableMeshConverterError("The converted chassis has an invalid projection-side declaration.")
        primitives = mesh.get("primitives") or []
        if not primitives:
            raise PortableMeshConverterError("The converted chassis contains a mesh with no geometry.")
        has_uv3 = False
        for primitive in primitives:
            if not isinstance(primitive, dict) or int(primitive.get("mode", 4)) != 4:
                raise PortableMeshConverterError("The converted chassis contains unsupported mesh geometry.")
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes or "NORMAL" not in attributes or primitive.get("indices") is None:
                raise PortableMeshConverterError("The converted chassis contains a mesh with no indexed geometry.")
            position = _validate_accessor(document, binary, attributes["POSITION"])
            normal = _validate_accessor(document, binary, attributes["NORMAL"])
            indices = _validate_accessor(document, binary, primitive["indices"])
            if (
                position.get("type") != "VEC3"
                or int(position.get("componentType") or 0) != 5126
                or normal.get("type") != "VEC3"
                or int(normal.get("componentType") or 0) != 5126
                or int(normal.get("count") or 0) != int(position.get("count") or 0)
                or indices.get("type") != "SCALAR"
                or int(indices.get("componentType") or 0) not in {5123, 5125}
                or int(indices.get("count") or 0) % 3
            ):
                raise PortableMeshConverterError("The converted chassis geometry contract is invalid.")
            declared_maximum = indices.get("max")
            index_max = declared_maximum[0] if isinstance(declared_maximum, list) and declared_maximum else -1
            actual_max = _actual_index_max(document, binary, primitive["indices"])
            if (
                not isinstance(index_max, (int, float))
                or isinstance(index_max, bool)
                or int(index_max) != actual_max
                or actual_max >= int(position["count"])
            ):
                raise PortableMeshConverterError("The converted chassis contains an out-of-range index.")
            triangles += int(indices["count"]) // 3
            if "TEXCOORD_3" in attributes:
                uv3 = _validate_accessor(document, binary, attributes["TEXCOORD_3"])
                if (
                    uv3.get("type") != "VEC2"
                    or int(uv3.get("componentType") or 0) != 5126
                    or int(uv3.get("count") or 0) != int(position.get("count") or 0)
                ):
                    raise PortableMeshConverterError("The converted chassis livery UV contract is invalid.")
                has_uv3 = True
        valid_mask = 0x3F if role == "paint" else 0x7C0 if role == "glass" else 0
        # 原本car_windowはガラス材質を表し、Liveryを貼れる証拠ではない。
        # PRIVATEの原本主導研究描画器は許可面0を明示的に扱えるが、
        # 従来製品の参照製品メタデータはGlass Meshに0以外の許可値を要求する。
        #
        # 通常製品の未確認入力拒否条件は維持する。
        # 原本Shaderの証拠を持ち、未承認と明示された第一者研究シーンだけ、
        # ペイント不可の原本窓を構造検査へ通してよい。
        glass_source = extras.get("lo4fh6_original_shader_source_evidence")
        source_trial = (
            role == "glass"
            and declared_allowed == 0
            and not require_product_accepted
            and isinstance(glass_source, dict)
            and glass_source.get("source_shader_family") == "car_window"
            and glass_source.get("game_shader_gpu_verified") is False
            and glass_source.get("original_mask_pixels_verified") is False
            and extras.get("lo4fh6_shader_role_trial_unapproved") is True
            and extras.get("lo4fh6_original_glass_livery_pixel_verified") is False
            and str((document.get("asset") or {}).get("generator") or "").startswith("LO4FH6 firstparty")
            and any(
                isinstance(scene, dict)
                and isinstance(scene.get("extras"), dict)
                and scene["extras"].get("lo4fh6_release_approval") is False
                and bool(scene["extras"].get("lo4fh6_research_only"))
                for scene in scenes
            )
        )
        if declared_allowed is not None:
            if declared_allowed & ~valid_mask or (
                role in {"paint", "glass"} and declared_allowed == 0
                and not source_trial
                and not (
                    source_static_preview and (
                        role == "glass"  # 原本の未塗装Glassは正規の構成要素
                        or role == "paint" and has_uv3  # r485のUV3 Paint面補完
                    )
                )
            ):
                raise PortableMeshConverterError("The converted chassis has an invalid livery-side declaration.")
        if declared_projection is not None and declared_projection & ~valid_mask:
            raise PortableMeshConverterError("The converted chassis has an invalid projection-side declaration.")
        if (role in {"paint", "glass"} and not has_uv3 and not declared_projection
                and not (source_static_preview and role == "glass" and declared_allowed == 0)):
            raise PortableMeshConverterError(
                "The converted chassis has no exact UV3 or safe world-projection path."
            )
        if role == "paint":
            paint += 1
            direct_uv3 += int(has_uv3)
            projected += int(not has_uv3)
        elif role == "glass":
            glass += 1
            direct_uv3 += int(has_uv3)
            projected += int(not has_uv3)
    no_source_paint_capability = (
        source_static_preview and paint == 0
        and all(
            isinstance(scene, dict)
            and isinstance(scene.get("extras"), dict)
            and scene["extras"].get("lo4fh6_original_paint_surface_mesh_count") == 0
            and scene["extras"].get("lo4fh6_paint_livery_supported") is False
            and scene["extras"].get("lo4fh6_paint_capability")
                == "NO_SOURCE_PAINT_SURFACE__LIVERY_APPLICATION_UNSUPPORTED"
            for scene in scenes
        )
    )
    if not meshes or (paint == 0 and not overlay_source_preview
                      and not no_source_paint_capability):
        raise PortableMeshConverterError(
            "The converted chassis did not preserve livery-bearing paint geometry."
        )
    # Paint面のないStatic車体も、幾何表示専用のViewer候補にはなる。
    # Livery適用可能性の証拠ではないため、
    # 明示的なSceneメタデータをUIと描画器へ保持する。
    return {
        "mesh_count": len(meshes),
        "paint_meshes": paint,
        "glass_meshes": glass,
        "triangle_count": triangles,
        "direct_uv3_meshes": direct_uv3,
        "projected_livery_meshes": projected,
        "part_option_count": len(part_options),
    }


def reuse_converter_validation(
    glb_path: Path | str,
    diagnostics: dict[str, Any],
    *,
    modified_after_conversion: bool = False,
) -> tuple[dict[str, int], bool]:
    """実GLBバイトが不変の場合だけConverterの検証結果を再利用する。

    内部WheelStyle MorphでGLBを変更した場合は必ず再検証する。
    診断記録が欠落・不正な場合も厳密な検証を行う。
    """
    result = diagnostics.get("validated_glb")
    required = (
        "mesh_count", "paint_meshes", "glass_meshes", "triangle_count",
        "direct_uv3_meshes", "projected_livery_meshes", "part_option_count",
    )
    if (
        not modified_after_conversion
        and isinstance(result, dict)
        and all(type(result.get(key)) is int and result[key] >= 0 for key in required)
        and result["mesh_count"] > 0
        and result["paint_meshes"] > 0
        and isinstance(diagnostics.get("validated_glb_file_identity"), dict)
        and isinstance(diagnostics.get("validated_glb_sha256"), str)
    ):
        # 記録済み集計値だけで古いGLBを受入しない。実バイトSHAと同一性を検査。
        path = Path(glb_path)
        try:
            stat = path.stat()
            identity = {
                "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
                "inode": int(stat.st_ino), "device": int(stat.st_dev),
            }
            if (identity == diagnostics["validated_glb_file_identity"]
                    and _sha256_file(path) == diagnostics["validated_glb_sha256"]):
                return {key: result[key] for key in required}, True
        except OSError:
            pass
    return validate_local_chassis_glb(glb_path, require_product_accepted=True), False


def validate_converter_product_report(report: object) -> None:
    """製品受入を明示していない第一者出力を拒否する。

    以前受入済みの参照製品レポートには第一者フィールドがない。
    r485／FEOWとの互換性を保つため、それらの既存変換・GLB検証経路は変えない。
    """
    if not isinstance(report, dict):
        raise PortableMeshConverterError("The local chassis converter returned a non-object report.")
    firstparty = report.get("source") == "firstparty-Carbin-ModelBin"
    if report.get("research_only") is True or report.get("product_accepted") is False:
        raise PortableMeshConverterError(
            "First-party chassis output is research-only and cannot replace the accepted product GLB."
        )
    source_static_preview = (
        firstparty and report.get("functional_static_preview") is True
        and report.get("static_preview_source_verified") is True
        and (report.get("source_original_static_selection") is True
             or report.get("source_lo4_static_selection") is True)
        and report.get("release_approved") is False
        and report.get("xbox_visual_approved") is False
    )
    if firstparty and (report.get("product_accepted") is not True
                       or report.get("research_only") is not False):
        raise PortableMeshConverterError(
            "First-party chassis output lacks explicit product acceptance; legacy fallback is forbidden."
        )
    if firstparty:
        unresolved = report.get("unresolved")
        keys = (
            "original_skin_data_unapplied_meshes",
            "original_morph_data_unapplied_meshes",
            "original_nonroot_attachment_unverified_meshes",
            "unverified_native_shader_visible_meshes",
        )
        if (not isinstance(unresolved, dict)
                or any(type(unresolved.get(key)) is not int
                       or (unresolved[key] < 0 if source_static_preview else unresolved[key] != 0)
                       for key in keys)):
            raise PortableMeshConverterError(
                "First-party chassis output has missing or unresolved source runtime surfaces."
            )
        if source_static_preview:
            if report.get("source_loose_entry_mode") is True:
                if (report.get("source_scene_mode") != "loose"
                        or type(report.get("source_loose_entry_count")) is not int
                        or report["source_loose_entry_count"] <= 0
                        or not isinstance(report.get("source_evidence"), dict)
                        or report["source_evidence"].get("source_loose_entry_mode") is not True
                        or report["source_evidence"].get("source_loose_entry_count")
                            != report["source_loose_entry_count"]):
                    raise PortableMeshConverterError(
                        "Original loose ModelBin overlay provenance is incomplete."
                    )
            evidence = report.get("source_evidence") or {}
            counts = evidence.get("counts") if isinstance(evidence, dict) else {}
            if (not isinstance(counts, dict)
                    or evidence.get("lo4_static_preview_selection") is not True
                    or counts.get("lo4_static_expected_source_meshes")
                        != counts.get("source_stock_visible_meshes")
                    or type(counts.get("source_stock_visible_meshes")) is not int
                    or counts["source_stock_visible_meshes"] <= 0):
                raise PortableMeshConverterError(
                    "First-party static-preview source mesh coverage proof is missing."
                )


def validate_firstparty_output_identity(report: dict, output_path: Path) -> None:
    """プロセス終了成功だけで判断せず、生成した実バイトを検査する。"""
    if report.get("source") != "firstparty-Carbin-ModelBin":
        return
    declared_sha = report.get("glb_sha256")
    if (not isinstance(declared_sha, str) or len(declared_sha) != 64
            or any(c not in "0123456789abcdef" for c in declared_sha)
            or not output_path.is_file() or _sha256_file(output_path) != declared_sha):
        raise PortableMeshConverterError(
            "First-party chassis GLB does not match the declared source output SHA-256."
        )


def convert_vehicle_model_to_glb(
    asset: VehicleAsset,
    output: Path | str,
    *,
    part_selection: dict[str, int] | None = None,
    loose_entries: list[str] | None = None,
    part_overlay_only: bool = False,
    converter_path: Path | str | None = None,
    process_env: dict[str, str] | None = None,
    timeout_seconds: float = 300.0,
    cancel_event: threading.Event | None = None,
    max_process_bytes: int = MAX_CONVERTER_RESIDENT_BYTES,
    diagnostics: dict[str, Any] | None = None,
) -> Path:
    """研究用GLBを受け入れず、同一プロセス内の原本Converterを呼び出す。"""
    if cancel_event and cancel_event.is_set():
        raise ChassisConversionCancelled("Local chassis preparation was superseded.")
    if converter_path is not None or process_env is not None:
        raise PortableMeshConverterError("External chassis converter overrides are disabled.")
    if loose_entries is not None and (
        not isinstance(loose_entries, list) or not loose_entries
        or any(not isinstance(entry, str) or not entry.strip()
               or not entry.replace("\\", "/").casefold().startswith("scene/")
               or not entry.casefold().endswith(".modelbin")
               or ".." in Path(entry.replace("\\", "/")).parts
               for entry in loose_entries)
        or len(set(entry.casefold() for entry in loose_entries)) != len(loose_entries)
    ):
        raise PortableMeshConverterError("Invalid original loose ModelBin selection.")
    if part_selection is not None and not isinstance(part_selection, dict):
        raise PortableMeshConverterError("First-party original Carbin part selection must be a dictionary.")
    if timeout_seconds <= 0 or max_process_bytes <= 0:
        raise PortableMeshConverterError("Invalid first-party conversion resource limits.")

    # 遅延importで通常GUIの起動を維持し、子プロセスは作らない。
    # 第一者Carbin／ModelBinモジュールはインストール済みViewer本体にあり、
    # 隣接する開発・研究用チェックアウトに依存しない。
    # 受入済みWindows GUIを単体フォルダーから起動する場合も動作する。
    from .independent_chassis.standard_converter import (
        IndependentConverterNotReady, execute_request,
    )

    # resolve()の前に呼出元のパスを確認する。
    # resolve()は末尾のSymlinkを隠し、製品キャッシュを別位置へ誘導する恐れがある。
    raw_output = Path(output)
    if raw_output.is_symlink():
        raise PortableMeshConverterError("Refusing a symlinked chassis GLB output.")
    output_path = raw_output.resolve()
    if output_path.exists():
        raise PortableMeshConverterError("Refusing to overwrite an existing chassis GLB.")
    source_archive_input = Path(asset.archive_path)
    if source_archive_input.is_symlink() or not source_archive_input.is_file():
        raise PortableMeshConverterError("First-party source archive must be a regular original file.")
    source_archive = source_archive_input.resolve()
    if not source_archive.is_file():
        raise PortableMeshConverterError("First-party source archive must be a regular original file.")
    source_archive_sha256 = _sha256_file(source_archive)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lo4fh6-firstparty-gate-") as temporary:
        candidate = Path(temporary) / "candidate.glb"
        request = {
            "archive": str(source_archive),
            "output": str(candidate),
            "carbin_entry": "" if loose_entries is not None else inspection_carbin_entry(asset),
            "entries": list(loose_entries) if loose_entries is not None else inspection_model_entries(asset),
        }
        try:
            # 製品変換ではresearch_previewを絶対に有効化しない。
            selection = {"source_part_selection": part_selection} if part_selection else {}
            if part_overlay_only:
                # 部品の選択肢の重ね合わせ（その選択肢で加わる部品だけ）。選択肢はちょうど 1 つ。
                if not part_selection or len(part_selection) != 1 or loose_entries is not None:
                    raise PortableMeshConverterError(
                        "A part option overlay needs exactly one original Carbin part selection.")
                selection["source_part_overlay_only"] = True
            if loose_entries is not None:
                if part_selection:
                    raise PortableMeshConverterError(
                        "Loose ModelBin overlay cannot mix with original Carbin part selection."
                    )
                selection["source_loose_entries"] = list(loose_entries)
            report = execute_request(
                request, research_preview=False, source_original_static_selection=True,
                **selection,
            )
        except IndependentConverterNotReady as exc:
            if diagnostics is not None:
                diagnostics["firstparty_product_gate"] = "REJECTED_UNVERIFIED"
                diagnostics["converter_process_seconds"] = round(time.perf_counter() - started, 6)
            raise PortableMeshConverterError(str(exc)) from exc
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            # 原本の欠落・不正、未対応ModelBin、独立Decoder失敗はエラーとする。
            # 旧変換EXE起動や別車両のキャッシュGLB再利用を認めない。
            if diagnostics is not None:
                diagnostics["firstparty_product_gate"] = "REJECTED_SOURCE_ERROR"
                diagnostics["converter_process_seconds"] = round(time.perf_counter() - started, 6)
            raise PortableMeshConverterError(
                f"Independent FH6 chassis source conversion failed: {exc}"
            ) from exc
        if diagnostics is not None:
            diagnostics["converter_report"] = report
        validate_converter_product_report(report)
        validate_firstparty_output_identity(report, candidate)
        # 元Stockと元Looseは機能承認の範囲が異なる。
        # 旧署名参照製品/研究GLBは製品確定前と保存直前の双方で拒否する。
        required_scope = (
            "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"
            if loose_entries is not None
            else "ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE"
        )
        validate_local_chassis_glb(
            candidate, require_product_accepted=True,
            required_firstparty_scope=required_scope,
        )
        if _sha256_file(source_archive) != source_archive_sha256:
            raise PortableMeshConverterError("Original FH6 source archive changed during conversion.")
        # 独立検証済みの製品レポートと製品GLBゲートの両方を通った場合だけ採用する。
        # 研究専用出力はここまで到達させない。
        if cancel_event and cancel_event.is_set():
            raise ChassisConversionCancelled("Local chassis preparation was superseded.")
        if time.perf_counter() - started > timeout_seconds:
            raise PortableMeshConverterError("First-party chassis conversion exceeded its time limit.")
        if candidate.stat().st_size > max_process_bytes:
            raise PortableMeshConverterError("First-party chassis conversion exceeded its byte limit.")
        # 上記いずれの拒否時も受入済みキャッシュを変更しない。
        # os.replaceは同じファイルシステム内で原子的なので、出力先の隣へ一時配置する。
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=output_path.name + ".firstparty-", suffix=".tmp",
            dir=output_path.parent, delete=False,
        ) as staging:
            staging_path = Path(staging.name)
        try:
            with candidate.open("rb") as source, staging_path.open("wb") as target:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    if cancel_event and cancel_event.is_set():
                        raise ChassisConversionCancelled("Local chassis preparation was superseded.")
                    target.write(block)
            validate_firstparty_output_identity(report, staging_path)
            validate_local_chassis_glb(
                staging_path, require_product_accepted=True,
                required_firstparty_scope=required_scope,
            )
            if _sha256_file(source_archive) != source_archive_sha256:
                raise PortableMeshConverterError("Original FH6 source archive changed before product promotion.")
            # 一時GLBのコピー・SHA計算・検証時間も呼出元の期限に算入する。
            # 期限後に結果を公開しない。
            if cancel_event and cancel_event.is_set():
                raise ChassisConversionCancelled("Local chassis preparation was superseded.")
            if time.perf_counter() - started > timeout_seconds:
                raise PortableMeshConverterError("First-party chassis conversion exceeded its time limit.")
            if output_path.exists() or output_path.is_symlink():
                raise PortableMeshConverterError("Refusing to overwrite an existing chassis GLB.")
            # 存在しない場合だけ原子的に作成する。
            # os.replaceでは存在確認後に別のGUI／Organizer要求が生成したファイルを
            # 上書きし得る。同じファイルシステム内でHard Linkを作れば、
            # 競合する製品キャッシュを置換せず失敗できる。
            try:
                os.link(staging_path, output_path, follow_symlinks=False)
            except FileExistsError as exc:
                raise PortableMeshConverterError(
                    "Refusing to overwrite a concurrently created chassis GLB."
                ) from exc
            except OSError as exc:
                raise PortableMeshConverterError(
                    "Atomic first-party GLB promotion failed; product cache unchanged."
                ) from exc
        finally:
            staging_path.unlink(missing_ok=True)
        if diagnostics is not None:
            diagnostics["firstparty_product_gate"] = "ACCEPTED_VALIDATED"
            diagnostics["converter_process_seconds"] = round(time.perf_counter() - started, 6)
        return output_path
