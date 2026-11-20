from __future__ import annotations

import contextlib
import contextvars
import threading
from collections import OrderedDict
from typing import Any, Callable
import hashlib
import io
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tools.livery.fh6_swatch import decode_swatch_image, read_swatch_surface

ASCII_RE = re.compile(rb"[ -~]{6,}")
GLOBAL_USER_COLOR_RE = re.compile(r"^g_CarUserColor(\d+)$")

FOCUS_NEEDLES = (
    "UserColor", "PaintColor", "FlakeColor", "FlakeRoughness", "FlakeCoverage",
    "Glitter", "Iridescence", "Glancing", "Roughness_Shift", "ClearCoat",
    "Aniso", "Metal", "NormalMap00", "NormalMap0", "UVChoice", "Weave",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ascii_strings(data: bytes) -> list[str]:
    return [m.decode("ascii", "replace") for m in ASCII_RE.findall(data)]


def shader_base_name(parameter_name: str) -> str:
    name = str(parameter_name or "")
    suffixes = (
        "ColorParam", "CarLightParam", "Vector2", "Vector3", "Vector4",
        "_floatVal", "floatVal", "Bool", "_Texture", "Texture",
        "_Value", "Value", "_HeightScale", "HeightScale",
    )
    changed = True
    while changed and name:
        changed = False
        for suffix in suffixes:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[:-len(suffix)]
                changed = True
                break
    return name.rstrip("_")


# シェーダーの引数・Texture の番号の解析（shaderbin の中を名前で何度も探す）は、shaderbin のバイト列と XML の
# 要素の属性だけで決まる。部品の色付けの解析では、同じシェーダーを使う約 450 の材質で同じ解析を繰り返していた
# （初めての車で約 1 秒。2026-11-20）。同じプロセスで同じバイト列と属性の結果を覚え、写しを返す。
_SHADER_IDS_MEMO: "OrderedDict[tuple, dict[str, dict]]" = OrderedDict()
_SHADER_IDS_LIMIT = 32
_SHADER_IDS_LOCK = threading.Lock()


def _remembered_shader_ids(kind: str, tag: str, shader_data: bytes, root: ET.Element,
                           compute: Callable[[bytes, ET.Element], dict[str, dict]]) -> dict[str, dict]:
    if not isinstance(shader_data, bytes):
        return compute(shader_data, root)
    signature = tuple(tuple(sorted(elem.attrib.items())) for elem in root.findall(f".//{tag}"))
    key = (kind, shader_data, signature)
    with _SHADER_IDS_LOCK:
        cached = _SHADER_IDS_MEMO.get(key)
        if cached is not None:
            _SHADER_IDS_MEMO.move_to_end(key)
    if cached is None:
        cached = compute(shader_data, root)
        with _SHADER_IDS_LOCK:
            _SHADER_IDS_MEMO[key] = {name: dict(meta) for name, meta in cached.items()}
            while len(_SHADER_IDS_MEMO) > _SHADER_IDS_LIMIT:
                _SHADER_IDS_MEMO.popitem(last=False)
        return cached
    return {name: dict(meta) for name, meta in cached.items()}


def shader_parameter_ids(shader_data: bytes, root: ET.Element) -> dict[str, dict]:
    """数値の引数（Parameter）の名前から、shaderbin の中の番号と既定値の位置を引く（同じ入力の結果は覚える）。"""
    return _remembered_shader_ids("parameter", "Parameter", shader_data, root, _shader_parameter_ids_uncached)


def shader_texture_parameter_ids(shader_data: bytes, root: ET.Element) -> dict[str, dict]:
    """Texture2D の引数（Texture）の名前から、shaderbin の中の番号を引く（同じ入力の結果は覚える）。"""
    return _remembered_shader_ids("texture", "Texture", shader_data, root, _shader_texture_parameter_ids_uncached)


def _shader_parameter_ids_uncached(shader_data: bytes, root: ET.Element) -> dict[str, dict]:
    resolved: dict[str, dict] = {}
    for elem in root.findall(".//Parameter"):
        xml_name = elem.attrib.get("parametername") or ""
        base_name = shader_base_name(xml_name)
        encoded = base_name.encode("ascii", errors="ignore")
        if not encoded:
            continue
        candidates = []
        start = 0
        while True:
            pos = shader_data.find(encoded, start)
            if pos < 0:
                break
            end = pos + len(encoded)
            if end + 4 <= len(shader_data):
                param_id = shader_data[end:end + 4]
                record_prefix = b"\x03\x04" + param_id + b"\x01"
                record_pos = shader_data.find(record_prefix)
                if record_pos >= 0:
                    candidates.append((pos, param_id, record_pos))
            start = pos + 1
        if candidates:
            name_pos, param_id, record_pos = max(candidates, key=lambda item: item[0])
            resolved[xml_name] = {
                "xml_name": xml_name,
                "parameter_id_hex": param_id.hex(),
                "default_record_offset": record_pos,
                "size": int(elem.attrib.get("size", "0") or 0),
                "referenced": str(elem.attrib.get("referenced", "")).casefold() == "true",
                "name_offset": name_pos,
            }
    return resolved


def semantic_external_user_color_evidence(root: ET.Element, resolved_parameter_ids: dict[str, dict]) -> dict:
    """Classify shader XML g_CarUserColor* entries as semantic external inputs.

    r195 established the structural distinction used here: material-owned controls
    resolve through the shaderbin compact name/hash + default-record table, while
    g_CarUserColor* is referenced by shader XML but is absent from that table.
    This is semantic routing evidence only; it does not claim a compiled constant-
    buffer offset or an instruction-level shader equation.
    """
    rows: list[dict] = []
    for elem in root.findall(".//Parameter"):
        name = str(elem.attrib.get("parametername") or "")
        match = GLOBAL_USER_COLOR_RE.fullmatch(name)
        if match is None:
            continue
        size = int(elem.attrib.get("size", "0") or 0)
        referenced = str(elem.attrib.get("referenced", "")).casefold() == "true"
        if not referenced or size != 4 or name in resolved_parameter_ids:
            continue
        rows.append({
            "index": int(match.group(1)),
            "name": name,
            "size": size,
            "referenced": True,
            "material_default_record": False,
            "classification": "semantic_external_user_color_input",
        })
    rows.sort(key=lambda row: (int(row["index"]), str(row["name"])))
    control_count = len(resolved_parameter_ids)
    structurally_resolved = bool(rows and control_count >= 2)
    return {
        "resolved": structurally_resolved,
        "inputs": rows,
        "material_default_record_parameter_count": control_count,
        "compiled_constant_buffer_offset_resolved": False,
        "compiled_shader_equation_resolved": False,
        "basis": (
            "referenced float4 g_CarUserColor* shader XML parameter is structurally absent "
            "from the material-default compact record table while multiple material-owned parameters resolve"
            if structurally_resolved else
            "semantic user-colour evidence is incomplete: no referenced float4 candidate or fewer than two material-default controls resolved"
        ),
    }


def external_user_color_contract(runtime: dict, expected_input_count: object) -> dict:
    """Return renderer-contract diagnostics for resolved semantic user-colour inputs."""
    evidence = dict(runtime.get("semantic_external_user_color_inputs") or {})
    input_rows = evidence.get("inputs")
    rows = [dict(row) for row in input_rows if isinstance(row, dict)] \
        if isinstance(input_rows, list) else []
    # NumInputColorsはGameDBのINTEGER列。bool、文字列、少数をint()で
    # 暗黙変換すると別原本の色数を製品標準に認可してしまう。
    expected = expected_input_count if type(expected_input_count) is int \
        and expected_input_count >= 0 else 0
    indices = [row.get("index") for row in rows]
    names = [row.get("name") for row in rows]
    defaults = evidence.get("material_default_record_parameter_count")
    valid_defaults = type(defaults) is int and defaults >= 2
    # Shader XML由来の浮動でない番号・正式名・float4参照・独立入力という
    # 元宣言が全件一致した場合だけ、GameDBの要求色数と交差させる。
    valid_rows = (
        isinstance(input_rows, list) and len(rows) == len(input_rows)
        and all(
            type(index) is int and index >= 0
            and row.get("name") == f"g_CarUserColor{index}"
            and type(row.get("size")) is int and row["size"] == 4
            and row.get("referenced") is True
            and row.get("material_default_record") is False
            and row.get("classification") == "semantic_external_user_color_input"
            for row, index in zip(rows, indices)
        )
    )
    # 共用ShaderのColor0/1宣言と仕上げごとの0/1/2色数を分離する。
    # 未署名宣言や飛び番で「存在するColor0」を捏造しない。
    contiguous = indices == list(range(len(indices)))
    material_arity_proven = (
        expected > 0 and len(rows) >= expected and valid_rows
        and valid_defaults and contiguous
    )
    resolved = bool(
        runtime.get("available") is True
        and evidence.get("resolved") is True
        and material_arity_proven
    )
    return {
        "resolved": resolved,
        "expected_input_count": expected,
        "resolved_input_count": len(rows),  # 既存監査フィールドはShader XMLの宣言数を保持
        "material_bound_input_count": expected if resolved else 0,
        "shader_declared_input_count": len(rows),
        "semantic_input_names": names[:expected] if resolved else [],
        "extra_shader_declared_input_names": names[expected:] if resolved else [],
        "material_arity_subset_of_shader": bool(resolved and len(rows) > expected),
        "source": "installed_fh6_shader_xml_structural_classification",
        "material_default_record_parameter_count": defaults if valid_defaults else 0,
        "renderer_behavior_changed": False,
        "compiled_constant_buffer_offset_resolved": False,
        "compiled_shader_equation_resolved": False,
        "basis": (
            evidence.get("basis")
            if resolved else
            "semantic input count or structural evidence did not match the material input contract"
        ),
    }


def _shader_texture_parameter_ids_uncached(shader_data: bytes, root: ET.Element) -> dict[str, dict]:
    """Resolve Texture2D parameter hashes from shaderbin/XML evidence.

    FH6 shader XML keeps texture parameters in ``<Texture>`` elements rather
    than the scalar/vector ``<Parameter>`` collection.  The compiled shaderbin
    still carries the same base-name + uint32 hash relationship used by the
    numeric parameter decoder.  Keep this path separate so texture records are
    never mis-decoded as floats.
    """
    resolved: dict[str, dict] = {}
    for elem in root.findall(".//Texture"):
        xml_name = elem.attrib.get("parametername") or ""
        base_name = shader_base_name(xml_name)
        encoded = base_name.encode("ascii", errors="ignore")
        if not encoded:
            continue
        candidates = []
        start = 0
        while True:
            pos = shader_data.find(encoded, start)
            if pos < 0:
                break
            end = pos + len(encoded)
            if end + 4 <= len(shader_data):
                param_id = shader_data[end:end + 4]
                # Default shader Texture2D records use the same leading
                # version/hash bytes as scalar records.  Requiring the record
                # keeps incidental printable strings from becoming evidence.
                record_prefix = b"\x03\x04" + param_id + b"\x01"
                record_pos = shader_data.find(record_prefix)
                if record_pos >= 0:
                    candidates.append((pos, param_id, record_pos))
            start = pos + 1
        if candidates:
            name_pos, param_id, record_pos = max(candidates, key=lambda item: item[0])
            resolved[xml_name] = {
                "xml_name": xml_name,
                "parameter_id_hex": param_id.hex(),
                "default_record_offset": record_pos,
                "referenced": str(elem.attrib.get("referenced", "")).casefold() == "true",
                "name_offset": name_pos,
            }
    return resolved


def _read_7bit_uint(data: bytes, offset: int) -> tuple[int, int] | None:
    """Read the variable-byte-count length used by FH6 Texture2D paths."""
    value = 0
    shift = 0
    for index in range(5):
        pos = offset + index
        if pos >= len(data):
            return None
        byte = data[pos]
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, index + 1
        shift += 7
    return None


def decode_material_texture_override(material_data: bytes, parameter_id_hex: str) -> dict | None:
    """Decode one material Texture2D parameter by shader parameter hash.

    This mirrors the audited 参照ツール material record layout: version bytes,
    uint32 name hash, optional v3.1+ field, type byte, GUID for v3+, then the
    variable-byte-count path and v2+ path hash.  Only type 6 (Texture2D) is
    accepted; malformed candidates fail closed.
    """
    param_id = bytes.fromhex(parameter_id_hex)
    start = 0
    while True:
        hash_pos = material_data.find(param_id, start)
        if hash_pos < 0:
            return None
        record_pos = hash_pos - 2
        start = hash_pos + 1
        if record_pos < 0 or hash_pos + 4 > len(material_data):
            continue
        major = material_data[record_pos]
        minor = material_data[record_pos + 1]
        if not (1 <= major <= 4):
            continue
        cursor = hash_pos + 4
        if major > 3 or (major == 3 and minor >= 1):
            if cursor >= len(material_data):
                continue
            has_unknown = material_data[cursor] != 0
            cursor += 1
            if has_unknown:
                cursor += 4
        if cursor >= len(material_data) or material_data[cursor] != 6:
            continue
        cursor += 1
        if major >= 3:
            cursor += 16
        if cursor >= len(material_data):
            continue
        length_info = _read_7bit_uint(material_data, cursor)
        if length_info is None:
            continue
        byte_count, length_size = length_info
        path_start = cursor + length_size
        path_end = path_start + byte_count
        if byte_count <= 0 or path_end > len(material_data):
            continue
        try:
            path = material_data[path_start:path_end].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if ".swatchbin" not in path.casefold():
            continue
        path_hash = None
        if major >= 2 and path_end + 4 <= len(material_data):
            path_hash = struct.unpack_from("<I", material_data, path_end)[0]
        return {
            "path": path,
            "path_hash": path_hash,
            "record_offset": record_pos,
            "version": [major, minor],
            "type": "Texture2D",
        }


def decode_shader_texture_default(shader_data: bytes, record_offset: int) -> dict | None:
    """Decode one shader-default Texture2D record at an audited record offset.

    Texture defaults use the same versioned Texture2D payload layout as
    material overrides.  The shader record carries the default-record marker
    at byte 6; malformed or non-Texture2D records fail closed.
    """
    pos = int(record_offset)
    if pos < 0 or pos + 12 > len(shader_data) or shader_data[pos:pos + 2] != b"\x03\x04":
        return None
    major = shader_data[pos]
    minor = shader_data[pos + 1]
    if not (1 <= major <= 4):
        return None
    cursor = pos + 6
    if major > 3 or (major == 3 and minor >= 1):
        if cursor >= len(shader_data):
            return None
        has_unknown = shader_data[cursor] != 0
        cursor += 1
        if has_unknown:
            cursor += 4
    if cursor >= len(shader_data) or shader_data[cursor] != 6:
        return None
    cursor += 1
    if major >= 3:
        cursor += 16
    if cursor >= len(shader_data):
        return None
    length_info = _read_7bit_uint(shader_data, cursor)
    if length_info is None:
        return None
    byte_count, length_size = length_info
    path_start = cursor + length_size
    path_end = path_start + byte_count
    if byte_count <= 0 or path_end > len(shader_data):
        return None
    try:
        path = shader_data[path_start:path_end].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if ".swatchbin" not in path.casefold():
        return None
    path_hash = None
    if major >= 2 and path_end + 4 <= len(shader_data):
        path_hash = struct.unpack_from("<I", shader_data, path_end)[0]
    return {
        "path": path,
        "path_hash": path_hash,
        "record_offset": pos,
        "version": [major, minor],
        "type": "Texture2D",
    }


def shader_texture_defaults(shader_data: bytes, root: ET.Element) -> list[dict]:
    """Return shader Texture2D defaults tied to exact XML parameter hashes."""
    rows: list[dict] = []
    for name, meta in shader_texture_parameter_ids(shader_data, root).items():
        decoded = decode_shader_texture_default(shader_data, meta["default_record_offset"])
        if decoded is None:
            continue
        rows.append({
            "parameter_name": name,
            "parameter_id_hex": meta["parameter_id_hex"],
            **decoded,
        })
    return rows


def material_texture_bindings(material_data: bytes, shader_data: bytes, root: ET.Element) -> list[dict]:
    """Return shader-name -> material texture bindings backed by both assets."""
    rows: list[dict] = []
    for name, meta in shader_texture_parameter_ids(shader_data, root).items():
        decoded = decode_material_texture_override(material_data, meta["parameter_id_hex"])
        if decoded is None:
            continue
        rows.append({
            "parameter_name": name,
            "parameter_id_hex": meta["parameter_id_hex"],
            **decoded,
        })
    return rows


def texture_binding_evidence(runtime: dict, game_ref: str) -> dict:
    """Return exact shader Texture2D binding evidence for one resolved asset."""
    target = _normalized_game_relative(game_ref).casefold()
    rows = [
        dict(row) for row in (runtime.get("material_texture_bindings") or [])
        if isinstance(row, dict)
        and _normalized_game_relative(str(row.get("path") or "")).casefold() == target
    ]
    return {
        "available": bool(rows),
        "bindings": rows,
        "parameter_names": [str(row.get("parameter_name") or "") for row in rows],
        "reason": (
            "material Texture2D record matched the installed shader parameter hash"
            if rows else
            "no audited material Texture2D record matched this texture reference"
        ),
    }


def weave_semantic_evidence(runtime: dict) -> dict:
    """Summarize decoded weave controls without inventing a shader equation."""
    effective = dict(runtime.get("effective_focus") or {})
    tint_a = ((effective.get("WeaveColorTintAColorParam") or {}).get("value"))
    tint_b = ((effective.get("WeaveColorTintBColorParam") or {}).get("value"))
    intensity = ((effective.get("WeaveNormal_Intensity_floatVal") or {}).get("value"))
    equal = None
    max_delta = None
    if isinstance(tint_a, (list, tuple)) and isinstance(tint_b, (list, tuple)) and len(tint_a) >= 3 and len(tint_b) >= 3:
        try:
            deltas = [abs(float(a) - float(b)) for a, b in zip(tint_a[:4], tint_b[:4])]
            if deltas and all(math.isfinite(value) for value in deltas):
                max_delta = max(deltas)
                equal = max_delta <= 1.0e-6
        except (TypeError, ValueError):
            pass
    return {
        "weave_color_tint_a": tint_a,
        "weave_color_tint_b": tint_b,
        "weave_tint_max_delta": max_delta,
        "weave_tints_effectively_equal": equal,
        "weave_normal_intensity": intensity,
        "interpretation": (
            "parameter names and material bindings identify weave controls, but the exact compiled shader equation remains unaudited"
        ),
    }


def decode_shader_default(shader_data: bytes, record_offset: int, parameter_size: int):
    pos = int(record_offset)
    if pos < 0 or pos + 28 > len(shader_data) or shader_data[pos:pos + 2] != b"\x03\x04":
        return None
    type_code = shader_data[pos + 11]
    value_pos = pos + 28
    value_size = 16 if int(parameter_size) == 4 else 4
    if value_pos + value_size > len(shader_data):
        return None
    raw = shader_data[value_pos:value_pos + value_size]
    if int(parameter_size) == 4:
        return [round(float(v), 9) for v in struct.unpack("<4f", raw)]
    if type_code == 0x03:
        return bool(struct.unpack("<I", raw)[0])
    return round(float(struct.unpack("<f", raw)[0]), 9)


def decode_material_override(material_data: bytes, parameter_id_hex: str, parameter_size: int):
    param_id = bytes.fromhex(parameter_id_hex)
    prefix = b"\x03\x04" + param_id + b"\x00"
    pos = material_data.find(prefix)
    if pos < 0:
        return None
    type_pos = pos + 7
    value_pos = pos + 24
    value_size = 16 if int(parameter_size) == 4 else 4
    if value_pos + value_size > len(material_data):
        return None
    type_code = material_data[type_pos]
    raw = material_data[value_pos:value_pos + value_size]
    if int(parameter_size) == 4:
        return [round(float(v), 9) for v in struct.unpack("<4f", raw)]
    if type_code == 0x03:
        return bool(struct.unpack("<I", raw)[0])
    return round(float(struct.unpack("<f", raw)[0]), 9)


def shader_family_from_material(data: bytes) -> str:
    for value in ascii_strings(data):
        if ".shaderbin" in value.casefold():
            parts = value.replace("\\", "/").split("/")
            if len(parts) >= 2:
                return parts[-2]
    return ""


def focus_parameters(params: dict[str, dict]) -> dict[str, dict]:
    return {
        key: value for key, value in params.items()
        if any(needle.casefold() in key.casefold() for needle in FOCUS_NEEDLES)
    }


# 部品の色付けのように多数の材質を続けて読む解析では、材質ごとに Materials.zip・Textures.zip
# （数千項目）を開き直して目録を読むのに大半の時間が掛かっていた（220 材質で約 7 秒）。
# shared_archive_reads() の中では、同じ ZIP を 1 回だけ開いて使い回し、抜けるときに閉じる。
# 外では従来どおり読むたびに開いて閉じる（ゲームの更新でファイルを掴んだままにしない）。
# 文脈変数なので、別のスレッドからは共有されない（ZipFile を複数のスレッドで同時に読まない）。
_SHARED_ARCHIVES: contextvars.ContextVar = contextvars.ContextVar("lo4fh6_shared_archives", default=None)
# 同じ範囲の中では原本のファイルは変わらない（準備の間だけの範囲）ので、原本から読み出した同じ結果も
# その範囲の中だけ覚えて使い回す（scoped_memo。2026-11-19。範囲を抜けると捨てる）。
_SHARED_MEMOS: contextvars.ContextVar = contextvars.ContextVar("lo4fh6_shared_memos", default=None)


@contextlib.contextmanager
def shared_archive_reads():
    if _SHARED_ARCHIVES.get() is not None:
        yield
        return
    opened: dict[str, zipfile.ZipFile] = {}
    token = _SHARED_ARCHIVES.set(opened)
    memo_token = _SHARED_MEMOS.set({})
    try:
        yield
    finally:
        _SHARED_MEMOS.reset(memo_token)
        _SHARED_ARCHIVES.reset(token)
        for archive in opened.values():
            archive.close()


def scoped_memo(kind: str, key: Any, compute: Callable[[], Any]) -> Any:
    """shared_archive_reads の中なら、同じ kind・key の結果を覚えて返す（例外は覚えない）。外では毎回 compute。"""
    memos = _SHARED_MEMOS.get()
    if memos is None:
        return compute()
    full = (kind, key)
    if full in memos:
        return memos[full]
    value = compute()
    memos[full] = value
    return value


def _scoped_is_file(path: Path) -> bool:
    """path.is_file()。shared_archive_reads の中では同じ場所の答えを覚える（原本は範囲の中で変わらない）。

    材質・画像の原本を探すたびに、無いはずの直接のファイルと ZIP の有無を調べていた。ゲームのフォルダーの
    stat は 1 回 約 0.1 ミリ秒で、部品の色付けの解析（約 860 回）で約 0.25 秒になっていた（2026-11-20）。
    """
    return bool(scoped_memo("is-file", str(path), path.is_file))


# ZIP の目次（中央ディレクトリ）を、同じファイルのあいだプロセスで使い回す（2026-11-20）。
# Textures.zip（18,465 項目）は、開いて目次を読むだけで約 70 ms 掛かり、ペイントの差し替えのたびに読み直していた。
# ファイルは今までどおり開いて閉じる（ゲームの更新でファイルを掴んだままにしない）。覚えるのは目次の写しだけ。
# 目次の値は Python 3.12 の zipfile（ZipFile._RealGetContents が決める start_dir・_comment・filelist・NameToInfo、
# 各項目の _end_offset）をそのまま写すので、ほかの版では使わない（毎回読む）。
_ZIP_DIRECTORIES: "OrderedDict[tuple, tuple]" = OrderedDict()
_CASEFOLD_INDEXES: "OrderedDict[tuple, dict[str, list[str]]]" = OrderedDict()
_ZIP_DIRECTORY_LIMIT = 8
_ZIP_DIRECTORY_LOCK = threading.Lock()
_ZIP_DIRECTORY_SUPPORTED = sys.version_info[:2] == (3, 12)


def _remember_limited(table: OrderedDict, key: tuple, value: Any, limit: int) -> None:
    with _ZIP_DIRECTORY_LOCK:
        table[key] = value
        table.move_to_end(key)
        while len(table) > limit:
            table.popitem(last=False)


class _RememberedDirectoryZipFile(zipfile.ZipFile):
    """目次を、同じファイル（場所・大きさ・更新日時・ファイルの番号）のあいだ使い回す読み取り用の ZipFile。

    目次の項目（ZipInfo）は読むだけなので、同じファイルの ZipFile どうしで共有する。
    """

    def __init__(self, path, identity: tuple) -> None:
        self._lo4fh6_identity = identity
        super().__init__(path)

    def _RealGetContents(self) -> None:
        with _ZIP_DIRECTORY_LOCK:
            remembered = _ZIP_DIRECTORIES.get(self._lo4fh6_identity)
            if remembered is not None:
                _ZIP_DIRECTORIES.move_to_end(self._lo4fh6_identity)
        if remembered is not None:
            self._comment, self.start_dir, filelist, names = remembered
            self.filelist = list(filelist)
            self.NameToInfo = dict(names)
            return
        super()._RealGetContents()
        _remember_limited(_ZIP_DIRECTORIES, self._lo4fh6_identity,
                          (self._comment, self.start_dir, tuple(self.filelist), dict(self.NameToInfo)),
                          _ZIP_DIRECTORY_LIMIT)


def _zip_file(path: Path) -> zipfile.ZipFile:
    """読むために ZIP を開く（同じファイルのあいだ、目次を使い回す）。"""
    if _ZIP_DIRECTORY_SUPPORTED:
        try:
            stat = os.stat(path)
        except OSError:
            stat = None
        if stat is not None:
            identity = (os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns, stat.st_ino,
                        stat.st_dev)
            return _RememberedDirectoryZipFile(path, identity)
    return zipfile.ZipFile(path)


@contextlib.contextmanager
def _open_zip(path: Path):
    opened = _SHARED_ARCHIVES.get()
    if opened is None:
        with _zip_file(path) as archive:
            yield archive
        return
    key = str(path)
    archive = opened.get(key)
    if archive is None:
        archive = opened[key] = _zip_file(path)
    yield archive


def _casefold_index(archive: zipfile.ZipFile, *, slash: bool) -> dict[str, list[str]]:
    """目録の名前を casefold した値から元の名前への辞書（ZIP ごとに 1 回だけ作る。読むだけ）。

    目次を使い回す ZipFile では、同じファイルのあいだ辞書も使い回す。
    """
    attribute = "_lo4fh6_casefold_slash_index" if slash else "_lo4fh6_casefold_index"
    index = getattr(archive, attribute, None)
    if index is None:
        identity = getattr(archive, "_lo4fh6_identity", None)
        key = (identity, slash) if identity is not None else None
        if key is not None:
            with _ZIP_DIRECTORY_LOCK:
                index = _CASEFOLD_INDEXES.get(key)
        if index is None:
            index = {}
            for name in archive.namelist():
                index.setdefault((name.replace("\\", "/") if slash else name).casefold(), []).append(name)
            if key is not None:
                _remember_limited(_CASEFOLD_INDEXES, key, index, 2 * _ZIP_DIRECTORY_LIMIT)
        setattr(archive, attribute, index)
    return index


def _zip_member_casefold(z: zipfile.ZipFile, candidate: str) -> str | None:
    target = candidate.replace("\\", "/").lstrip("/").casefold()
    by_lower = _casefold_index(z, slash=True)
    if target in by_lower:
        matches = by_lower[target]
    else:
        # Older Cars Shader ZIPs contain either family/family.shaderbin or
        # family.shaderbin. Retain that compatibility, but never arbitrarily
        # choose a same-named member from two different archive directories.
        matches = [name for low, names in by_lower.items()
                   if low.endswith(target) for name in names]
    if len(matches) > 1:
        raise ValueError('FH6 archive has ambiguous suffix/case-folded members')
    return matches[0] if matches else None


def _normalized_game_relative(game_ref: str) -> str:
    text = str(game_ref or "").strip()
    game_pos = text.casefold().find("game:\\")
    if game_pos >= 0:
        text = text[game_pos + len("game:\\"):]
    else:
        text = re.sub(r"(?i)^[a-z]?game:\\", "", text)
    return text.replace("\\", "/").lstrip("/")


def _game_refs_from_material(data: bytes, extension: str) -> list[str]:
    """Extract clean Game:\\... references ending at the requested extension."""
    suffix = str(extension or "").casefold()
    refs: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(rf"(?i)game:\\[^\x00\r\n]*?{re.escape(suffix)}")
    for value in ascii_strings(data):
        for match in pattern.finditer(value):
            ref = match.group(0)
            key = ref.casefold()
            if key not in seen:
                seen.add(key)
                refs.append(ref)
    return refs


def _texture_role_candidate(game_ref: str) -> str:
    """Infer only filename-explicit texture roles; ambiguous refs remain unknown."""
    text = _normalized_game_relative(game_ref).casefold()
    name = Path(text).name.casefold()
    if any(token in name for token in ("basecolor", "base_color", "albedo", "diffuse")):
        return "base_color_candidate"
    if any(token in name for token in ("normal", "nrml")):
        return "normal_candidate"
    if "rmao" in name:
        return "rmao_candidate"
    if "roughness" in name:
        return "roughness_candidate"
    if "mask" in name:
        return "mask_candidate"
    return "unknown"


def _strict_scoped_zip_member_path_only(member: str) -> None:
    if (not isinstance(member, str) or not member or member.startswith('/')
            or any(part in ('', '.', '..') for part in member.split('/'))
            or any(c in member for c in ('\\', ':', '\x00'))):
        raise ValueError('FH6 global library reference contains an unsafe member path')


def _strict_scoped_zip_member(archive: zipfile.ZipFile, member: str) -> str | None:
    """FH6 library namespace is part of the original asset identity.

    For global archives, never resolve a basename/suffix from another directory
    and never silently choose one of multiple case-folded ZIP members.
    """
    _strict_scoped_zip_member_path_only(member)
    matches = list(_casefold_index(archive, slash=False).get(member.casefold(), ()))
    if len(matches) > 1:
        raise ValueError('FH6 global library ZIP has ambiguous case-folded members')
    return matches[0] if matches else None


def _safe_game_asset_relative(game_ref: str) -> str:
    """FH6原本Game参照がMedia名前空間外へ逸脱するのを防ぐ。"""
    relative = _normalized_game_relative(game_ref)
    _strict_scoped_zip_member_path_only(relative)
    if not relative.casefold().startswith("media/"):
        raise ValueError("FH6 Game: reference is outside the Media namespace")
    return relative


def _texture_source(content: Path, game_ref: str, vehicle_archive: Path | None) -> tuple[bytes, dict]:
    relative = _safe_game_asset_relative(game_ref)
    direct = content / Path(relative)
    if _scoped_is_file(direct):
        data = direct.read_bytes()
        return data, {"kind": "direct", "path": str(direct), "member": None}

    library_prefix = "media/cars/_library/textures/"
    if relative.casefold().startswith(library_prefix):
        member = relative[len(library_prefix):]
        archive = content / "media" / "cars" / "_library" / "Textures.zip"
        _strict_scoped_zip_member_path_only(member)
        if _scoped_is_file(archive):
            with _open_zip(archive) as z:
                found = _strict_scoped_zip_member(z, member)
                if found:
                    data = z.read(found)
                    return data, {"kind": "textures_zip", "path": str(archive), "member": found}
        # 独立したCars/_libraryを車両ZIPや別スコープから代用しない。
        raise FileNotFoundError(f"texture reference not found in local FH6 assets: {game_ref}")

    # Game:/Media/_library/textures/... is a separate FH6 archive namespace.
    # Do not search a similarly named car/vehicle swatch as a substitute.
    global_prefix = "media/_library/textures/"
    if relative.casefold().startswith(global_prefix):
        member = relative[len(global_prefix):]
        archive = content / "media" / "_library" / "Textures.zip"
        # Validate even when the original archive is absent; never consult Cars.
        _strict_scoped_zip_member_path_only(member)
        if _scoped_is_file(archive):
            with _open_zip(archive) as z:
                found = _strict_scoped_zip_member(z, member)
                if found:
                    return z.read(found), {"kind": "media_global_textures_zip",
                                           "path": str(archive), "member": found}
        raise FileNotFoundError(f"texture reference not found in local FH6 assets: {game_ref}")

    if vehicle_archive is not None and _scoped_is_file(vehicle_archive):
        parts = relative.split("/")
        member = "/".join(parts[3:]) if len(parts) >= 4 and parts[0].casefold() == "media" and parts[1].casefold() == "cars" else relative
        with _open_zip(vehicle_archive) as z:
            found = _zip_member_casefold(z, member)
            if found:
                data = z.read(found)
                return data, {"kind": "vehicle_archive", "path": str(vehicle_archive), "member": found}

    raise FileNotFoundError(f"texture reference not found in local FH6 assets: {game_ref}")


def inspect_material_texture_assets(
    content: Path,
    texture_refs: list[str],
    *,
    vehicle_archive: Path | None = None,
) -> list[dict]:
    """Resolve material-referenced swatches without assigning unproven semantics."""
    rows: list[dict] = []
    for ref in texture_refs:
        row = {
            "reference": ref,
            "role_candidate": _texture_role_candidate(ref),
            "available": False,
            "error": None,
        }
        try:
            data, source = _texture_source(content, ref, vehicle_archive)
            surface = read_swatch_surface(data)
            surface.pop("pixels", None)
            row.update({
                "available": True,
                "source": source,
                "size": len(data),
                "sha256": _sha256_bytes(data),
                "surface": surface,
            })
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows



def extract_material_texture_preview(texture_asset: dict, output: Path) -> dict:
    """Decode one already-resolved runtime swatch to a derived local PNG.

    The source swatch stays in the installed FH6 asset archive.  Only a derived
    PNG is written into the local preview cache.
    """
    result = {
        "available": False,
        "output": str(output),
        "reference": str(texture_asset.get("reference") or ""),
        "role_candidate": str(texture_asset.get("role_candidate") or "unknown"),
        "source": texture_asset.get("source"),
        "source_sha256": texture_asset.get("sha256"),
        "error": None,
    }
    source = texture_asset.get("source") or {}
    try:
        path = Path(str(source.get("path") or ""))
        member = source.get("member")
        kind = str(source.get("kind") or "")
        if kind == "direct":
            def load() -> bytes:
                return path.read_bytes()
        elif member and path.is_file():
            def load() -> bytes:
                with _open_zip(path) as z:
                    return z.read(str(member))
        else:
            raise FileNotFoundError("runtime texture source is not readable")
        meta, png, width, height = derived_swatch_png(path, None if kind == "direct" else str(member), load, output)
        result.update(meta)
        if png is None:
            return result
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png)
        result.update({
            "available": True,
            "derived_sha256": hashlib.sha256(png).hexdigest(),
            "width": width,
            "height": height,
        })
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def derived_swatch_png(source: Path, member: str | None, load: Callable[[], bytes], output: Path
                       ) -> tuple[dict, bytes | None, int, int]:
    """原本の Swatch を復号して PNG のバイト列にする（画素は復号したまま。圧縮は zlib の標準の強さ）。

    戻り値は (復号の情報, PNG のバイト列（画像が無ければ None）, 幅, 高さ)。
    同じプロセスで同じ原本（ファイルの場所・大きさ・更新日時と ZIP の中の名前）は覚えて使い回す。炭素繊維などの
    ペイントを初めて開くたびに、同じ Swatch を復号して PNG に圧縮し直していた（1 枚 約 0.2 秒。2026-11-20）。
    """
    from tools.livery.process_file_memo import remembered

    def compute() -> tuple[dict, bytes | None, int, int]:
        image, meta = decode_swatch_image(load())
        if image is None:
            return dict(meta), None, 0, 0
        buffer = io.BytesIO()
        # 画素は同じで圧縮の仕方だけを選べる。最小化（optimize=True）は約 5 倍遅く、小さくなるのは約 6%（2026-11-20）
        image.save(buffer, format="PNG")
        return dict(meta), buffer.getvalue(), int(image.width), int(image.height)

    if output.suffix.casefold() != ".png":
        raise ValueError("derived swatch preview must be a PNG file")
    return remembered("derived-swatch-png", [source], member, compute, limit=16)

def _material_source(content: Path, game_ref: str, vehicle_archive: Path | None) -> tuple[bytes, dict]:
    relative = _safe_game_asset_relative(game_ref)
    direct = content / Path(relative)
    if _scoped_is_file(direct):
        data = direct.read_bytes()
        return data, {"kind": "direct", "path": str(direct), "member": None}

    library_prefix = "media/cars/_library/materials/"
    if relative.casefold().startswith(library_prefix):
        member = relative[len(library_prefix):]
        archive = content / "media" / "cars" / "_library" / "Materials.zip"
        _strict_scoped_zip_member_path_only(member)
        if _scoped_is_file(archive):
            with _open_zip(archive) as z:
                found = _strict_scoped_zip_member(z, member)
                if found:
                    data = z.read(found)
                    return data, {"kind": "materials_zip", "path": str(archive), "member": found}
        # 独立したCars/_libraryを車両ZIPや別スコープから代用しない。
        raise FileNotFoundError(f"material reference not found in local FH6 assets: {game_ref}")

    # Game:/Media/_library/materials is NOT the same archive as
    # Game:/Media/Cars/_library/materials. Both exist in FH6 originals.
    global_prefix = 'media/_library/materials/'
    if relative.casefold().startswith(global_prefix):
        member = relative[len(global_prefix):]
        _strict_scoped_zip_member_path_only(member)
        archive = content / 'media' / '_library' / 'Materials.zip'
        if _scoped_is_file(archive):
            with _open_zip(archive) as z:
                found = _strict_scoped_zip_member(z, member)
                if found:
                    return z.read(found), {'kind': 'media_global_materials_zip',
                                           'path': str(archive), 'member': found}
        raise FileNotFoundError(f'material reference not found in local FH6 assets: {game_ref}')

    if vehicle_archive is not None and _scoped_is_file(vehicle_archive):
        parts = relative.split("/")
        member = "/".join(parts[3:]) if len(parts) >= 4 and parts[0].casefold() == "media" and parts[1].casefold() == "cars" else relative
        with _open_zip(vehicle_archive) as z:
            found = _zip_member_casefold(z, member)
            if found:
                data = z.read(found)
                return data, {"kind": "vehicle_archive", "path": str(vehicle_archive), "member": found}

    raise FileNotFoundError(f"material reference not found in local FH6 assets: {game_ref}")


def _shader_refs_from_material(data: bytes) -> list[str]:
    return _game_refs_from_material(data, ".shaderbin")


def _texture_refs_from_material(data: bytes) -> list[str]:
    return _game_refs_from_material(data, ".swatchbin")


def _shader_bundle(content: Path, family: str, shader_refs: list[str] | None = None) -> tuple[dict, str, str, bytes, bytes]:
    """シェーダーの束（中身は _shader_bundle_uncached）。shared_archive_reads の中では同じ引数の結果を使い回す。

    部品の色の解析では材質ごとに呼ばれ（1 台で約 460 回）、そのたびにシェーダーの ZIP を開き、シェーダーのフォルダーの
    ZIP の一覧（約 700 個）を作っていた。返す辞書は写し（中は文字列だけ）、バイト列は変わらないのでそのまま。
    """
    key = (str(content), str(family), tuple(str(ref) for ref in (shader_refs or ())))
    source, shader_member, xml_member, shader_data, xml_data = scoped_memo(
        "shader_bundle", key, lambda: _shader_bundle_uncached(content, family, shader_refs))
    return dict(source), shader_member, xml_member, shader_data, xml_data


def _shader_bundle_uncached(content: Path, family: str, shader_refs: list[str] | None = None) -> tuple[dict, str, str, bytes, bytes]:
    # Global and Cars shaders are distinct FH6 namespaces, just as Materials
    # and Textures are. A global shader reference must NEVER fall through to a
    # same-named Cars family ZIP.
    global_prefix = 'media/_library/shaders/'
    cars_prefix = 'media/cars/_library/shaders/'
    explicit_scopes: set[str] = set()
    family_source_dirs: list[str] = []
    for ref in shader_refs or []:
        rel = _normalized_game_relative(ref)
        if rel.casefold().startswith(global_prefix):
            suffix = rel[len(global_prefix):]
            _strict_scoped_zip_member_path_only(suffix)
            explicit_scopes.add('global')
            family_source_dirs.append(str(Path(suffix).parent))
        elif rel.casefold().startswith(cars_prefix):
            suffix = rel[len(cars_prefix):]
            _strict_scoped_zip_member_path_only(suffix)
            explicit_scopes.add('cars')
        elif rel.casefold().startswith('media/') and '/shaders/' in rel.casefold():
            # Parts, Tracks, etc. are not a synonym for Cars. Explicitly
            # reject unknown origins until their original library is verified.
            raise ValueError('unsupported FH6 Shader library namespace: ' + rel)
    if len(explicit_scopes) > 1:
        raise ValueError('FH6 MaterialBin references multiple incompatible Shader library namespaces')
    global_scope = explicit_scopes == {'global'}
    shader_root = (content / 'media' / '_library' / 'shaders' if global_scope else
                   content / 'media' / 'cars' / '_library' / 'shaders')

    # Retail FH6 assets may expose a shader family as an extracted directory
    # rather than a ZIP. Prefer the exact Game:\ reference carried by the
    # material, then try the canonical family directory.
    direct_candidates: list[Path] = []
    for ref in shader_refs or []:
        relative = _normalized_game_relative(ref)
        direct_candidates.append(content / Path(relative))
    direct_candidates.append(shader_root / family / f"{family}.shaderbin")
    seen_direct: set[str] = set()
    for shader_path in direct_candidates:
        key = str(shader_path).casefold()
        if key in seen_direct:
            continue
        seen_direct.add(key)
        xml_path = Path(str(shader_path) + ".xml")
        if shader_path.is_file() and xml_path.is_file():
            return (
                {"kind": "direct", "path": str(shader_path), "xml_path": str(xml_path)},
                shader_path.name,
                xml_path.name,
                shader_path.read_bytes(),
                xml_path.read_bytes(),
            )

    candidates = [shader_root / f"{family}.zip"]
    if global_scope:
        # MaterialBin provides the exact path hierarchy: e.g.
        # Media/_library/shaders/pg/family/family.shaderbin can be bundled as
        # Media/_library/shaders/pg/family.zip. No cross-family wildcard scan.
        for directory in family_source_dirs:
            d = Path(directory)
            if d.name.casefold() == family.casefold() and str(d.parent) != '.':
                candidate = shader_root / d.parent / f'{family}.zip'
                if candidate not in candidates:
                    candidates.insert(0, candidate)
    else:
        candidates.append(shader_root / 'usercustomizable.zip')
        if shader_root.is_dir():
            candidates.extend(path for path in sorted(shader_root.glob('*.zip')) if path not in candidates)

    # The shipped shader archives observed by the research prototype do not
    # guarantee a family-name directory inside the ZIP. Match by file-name
    # suffix so both `family/family.shaderbin` and root-level
    # `family.shaderbin` layouts are accepted.
    bin_suffix = f"{family}.shaderbin"
    xml_suffix = f"{family}.shaderbin.xml"
    searched_archives: list[str] = []
    for archive in candidates:
        if not archive.is_file():
            continue
        searched_archives.append(str(archive))
        try:
            with zipfile.ZipFile(archive) as z:
                if global_scope:
                    allowed_bin = {bin_suffix.casefold(),
                                   (family + '/' + bin_suffix).casefold()}
                    allowed_xml = {xml_suffix.casefold(),
                                   (family + '/' + xml_suffix).casefold()}
                    shader_candidates = [n for n in z.namelist() if n.casefold() in allowed_bin]
                    xml_candidates = [n for n in z.namelist() if n.casefold() in allowed_xml]
                    if len(shader_candidates) > 1 or len(xml_candidates) > 1:
                        raise ValueError('FH6 global Shader family ZIP has ambiguous members')
                    shader_member = shader_candidates[0] if shader_candidates else None
                    xml_member = xml_candidates[0] if xml_candidates else None
                else:
                    shader_member = _zip_member_casefold(z, bin_suffix)
                    xml_member = _zip_member_casefold(z, xml_suffix)
                if shader_member and xml_member:
                    return (
                        {"kind": "shader_zip", "path": str(archive)},
                        shader_member,
                        xml_member,
                        z.read(shader_member),
                        z.read(xml_member),
                    )
        except (OSError, zipfile.BadZipFile):
            continue
    raise FileNotFoundError(
        f"shader family {family!r} was not found as a direct pair or in shader archives below {shader_root}; "
        f"searched {len(searched_archives)} readable archive candidate(s)"
    )


def _library_files_identity(content: Path) -> tuple:
    """材質の解析が読む原本の _library（media/cars/_library と media/_library）以下の全ファイルの名前・大きさ・更新日時。

    os.scandir の項目の情報を使う（Windows ではフォルダーの一覧から大きさと更新日時が得られる。約 830 個で数ミリ秒）。
    """
    rows: list[tuple[str, int, int]] = []
    for scope, library in (("cars", content / "media" / "cars" / "_library"), ("global", content / "media" / "_library")):
        pending: list[tuple[str, str]] = [(str(library), "")]
        while pending:
            folder, prefix = pending.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if entry.is_dir():
                            pending.append((entry.path, prefix + entry.name + "/"))
                        elif entry.is_file():
                            stat = entry.stat()
                            rows.append((f"{scope}:{prefix}{entry.name}", stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
    return tuple(sorted(rows))


def inspect_game_material_runtime(
    content: Path,
    material_path: str,
    *,
    vehicle_archive: Path | None = None,
    include_shader_default_textures: bool = False,
) -> dict:
    """Resolve one FH6 material reference and decode shader defaults/overrides.

    The function is read-only and returns diagnostic metadata only.  It does not
    copy game material or shader bytes into the preview output.

    同じプロセスで同じ原本（_library 以下の全ファイルと車両 ZIP の場所・大きさ・更新日時が同じ）と同じ引数の
    結果は覚えて写しを返す（同じ車のペイントを続けて開くたびに、材質・画像・シェーダーの ZIP を開き直して
    同じ解析をしていた。1 件あたり約 0.08〜0.1 秒。2026-11-20）。読み取りに失敗した結果（error あり）は覚えない。
    """
    from tools.livery.process_file_memo import remembered
    content_path = Path(content)
    files = [] if vehicle_archive is None else [Path(vehicle_archive)]
    library = scoped_memo("library-files-identity", str(content_path),
                          lambda: _library_files_identity(content_path))
    key = (str(content_path.resolve()), str(material_path or ""), bool(include_shader_default_textures), library)
    return remembered(
        "game-material-runtime", files, key,
        lambda: _inspect_game_material_runtime_uncached(
            content, material_path, vehicle_archive=vehicle_archive,
            include_shader_default_textures=include_shader_default_textures),
        limit=64, keep=lambda value: value.get("error") is None)


def _inspect_game_material_runtime_uncached(
    content: Path,
    material_path: str,
    *,
    vehicle_archive: Path | None = None,
    include_shader_default_textures: bool = False,
) -> dict:
    result = {
        "available": False,
        "material_available": False,
        "shader_available": False,
        "material_path": str(material_path or ""),
        "error": None,
    }
    try:
        material_data, source = _material_source(content, material_path, vehicle_archive)
        family = shader_family_from_material(material_data)
        shader_refs = _shader_refs_from_material(material_data)
        texture_refs = _texture_refs_from_material(material_data)
        result.update({
            "material_available": True,
            "material_source": source,
            "material_size": len(material_data),
            "material_sha256": _sha256_bytes(material_data),
            "shader_family": family,
            "material_shader_refs": shader_refs,
            "material_texture_refs": texture_refs,
            "material_texture_assets": inspect_material_texture_assets(
                content, texture_refs, vehicle_archive=vehicle_archive
            ),
        })
        if not family:
            raise ValueError("material contains no shaderbin family reference")
        shader_source, shader_member, xml_member, shader_data, xml_data = _shader_bundle(content, family, shader_refs)
        root = ET.fromstring(xml_data)
        ids = shader_parameter_ids(shader_data, root)
        texture_ids = shader_texture_parameter_ids(shader_data, root)
        defaults: dict[str, dict] = {}
        overrides: dict[str, dict] = {}
        effective: dict[str, dict] = {}
        for name, meta in ids.items():
            default = decode_shader_default(shader_data, meta["default_record_offset"], meta["size"])
            override = decode_material_override(material_data, meta["parameter_id_hex"], meta["size"])
            if default is not None:
                defaults[name] = {"value": default}
            if override is not None:
                overrides[name] = {"value": override}
            value = override if override is not None else default
            if value is not None:
                effective[name] = {"value": value}
        semantic_user_colors = semantic_external_user_color_evidence(root, ids)
        texture_bindings = material_texture_bindings(material_data, shader_data, root)
        texture_defaults = shader_texture_defaults(shader_data, root) if include_shader_default_textures else []
        texture_assets = list(result.get("material_texture_assets") or [])
        for asset in texture_assets:
            if not isinstance(asset, dict):
                continue
            asset_ref = str(asset.get("reference") or "")
            asset_key = _normalized_game_relative(asset_ref).casefold()
            bound_names = [
                str(row.get("parameter_name") or "")
                for row in texture_bindings
                if _normalized_game_relative(str(row.get("path") or "")).casefold() == asset_key
            ]
            if bound_names:
                asset["shader_texture_parameters"] = bound_names
        default_refs: list[str] = []
        seen_default_refs: set[str] = set()
        for row in texture_defaults:
            ref = str(row.get("path") or "")
            key = _normalized_game_relative(ref).casefold()
            if ref and key not in seen_default_refs:
                seen_default_refs.add(key)
                default_refs.append(ref)
        default_texture_assets = inspect_material_texture_assets(
            content, default_refs, vehicle_archive=vehicle_archive
        )
        for asset in default_texture_assets:
            if not isinstance(asset, dict):
                continue
            asset_ref = str(asset.get("reference") or "")
            asset_key = _normalized_game_relative(asset_ref).casefold()
            names = [
                str(row.get("parameter_name") or "")
                for row in texture_defaults
                if _normalized_game_relative(str(row.get("path") or "")).casefold() == asset_key
            ]
            if names:
                asset["shader_texture_parameters"] = names
                asset["binding_source"] = "shader_default"

        result.update({
            "available": True,
            "shader_available": True,
            "shader_source": {
                **shader_source,
                "member": shader_member,
                "xml_member": xml_member,
            },
            "shader_sha256": _sha256_bytes(shader_data),
            "shader_xml_sha256": _sha256_bytes(xml_data),
            "parameter_count": len(ids),
            "texture_parameter_count": len(texture_ids),
            "shader_texture_parameters": list(texture_ids),
            "material_texture_bindings": texture_bindings,
            "material_texture_assets": texture_assets,
            "semantic_external_user_color_inputs": semantic_user_colors,
            "override_count": len(overrides),
            "overrides_focus": focus_parameters(overrides),
            "effective_focus": focus_parameters(effective),
        })
        if include_shader_default_textures:
            result["shader_texture_defaults"] = texture_defaults
            result["shader_default_texture_assets"] = default_texture_assets
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result



def inspect_material_runtime_bytes(
    content: Path,
    material_data: bytes,
    *,
    material_label: str = "inline-material",
    material_source: dict | None = None,
    vehicle_archive: Path | None = None,
) -> dict:
    """Decode shader/runtime evidence from already-resolved FH6 material bytes.

    WheelStyle modelbin embeds ``MatI`` material-instance bundles directly.  The
    normal runtime path starts from a ``Game:\\...materialbin`` reference, but
    the same shader-family/default/override decoder can operate on the embedded
    bytes without inventing a filesystem path.  This helper is read-only and is
    intended for diagnostics first; it does not map the decoded values onto the
    Viewer by itself.
    """
    data = bytes(material_data or b"")
    result = {
        "available": False,
        "material_available": bool(data),
        "shader_available": False,
        "material_path": str(material_label or "inline-material"),
        "material_source": material_source or {"kind": "inline-wheelstyle-modelbin"},
        "material_size": len(data),
        "material_sha256": _sha256_bytes(data) if data else None,
        "error": None,
    }
    try:
        if not data:
            raise ValueError("inline material payload is empty")
        family = shader_family_from_material(data)
        shader_refs = _shader_refs_from_material(data)
        texture_refs = _texture_refs_from_material(data)
        result.update({
            "shader_family": family,
            "material_shader_refs": shader_refs,
            "material_texture_refs": texture_refs,
            "material_texture_assets": inspect_material_texture_assets(
                content, texture_refs, vehicle_archive=vehicle_archive
            ),
        })
        if not family:
            raise ValueError("inline material contains no shaderbin family reference")
        shader_source, shader_member, xml_member, shader_data, xml_data = _shader_bundle(
            content, family, shader_refs
        )
        root = ET.fromstring(xml_data)
        ids = shader_parameter_ids(shader_data, root)
        texture_ids = shader_texture_parameter_ids(shader_data, root)
        defaults: dict[str, dict] = {}
        overrides: dict[str, dict] = {}
        effective: dict[str, dict] = {}
        for name, meta in ids.items():
            default = decode_shader_default(shader_data, meta["default_record_offset"], meta["size"])
            override = decode_material_override(data, meta["parameter_id_hex"], meta["size"])
            if default is not None:
                defaults[name] = {"value": default}
            if override is not None:
                overrides[name] = {"value": override}
            value = override if override is not None else default
            if value is not None:
                effective[name] = {"value": value}
        semantic_user_colors = semantic_external_user_color_evidence(root, ids)
        texture_bindings = material_texture_bindings(data, shader_data, root)
        texture_assets = list(result.get("material_texture_assets") or [])
        for asset in texture_assets:
            if not isinstance(asset, dict):
                continue
            asset_ref = str(asset.get("reference") or "")
            asset_key = _normalized_game_relative(asset_ref).casefold()
            bound_names = [
                str(row.get("parameter_name") or "")
                for row in texture_bindings
                if _normalized_game_relative(str(row.get("path") or "")).casefold() == asset_key
            ]
            if bound_names:
                asset["shader_texture_parameters"] = bound_names
        result.update({
            "available": True,
            "shader_available": True,
            "shader_source": {
                **shader_source,
                "member": shader_member,
                "xml_member": xml_member,
            },
            "shader_sha256": _sha256_bytes(shader_data),
            "shader_xml_sha256": _sha256_bytes(xml_data),
            "parameter_count": len(ids),
            "texture_parameter_count": len(texture_ids),
            "shader_texture_parameters": list(texture_ids),
            "material_texture_bindings": texture_bindings,
            "material_texture_assets": texture_assets,
            "semantic_external_user_color_inputs": semantic_user_colors,
            "override_count": len(overrides),
            "overrides_focus": focus_parameters(overrides),
            "effective_focus": focus_parameters(effective),
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


_TAG_GRUB_BUNDLE = 0x47727562
_TAG_MATERIAL_RESOURCE = 0x4D415449
_TAG_MATERIAL_SHADER_PARAMETER = 0x4D545052


def _embedded_bundle_payloads(data: bytes) -> list[dict]:
    """Return read-only child payloads from one embedded FH6 Grub bundle.

    This intentionally implements only the bundle table fields needed for
    MaterialInstance diagnostics. Compressed children fail closed.
    """
    payload = bytes(data or b"")
    if len(payload) < 16 or struct.unpack_from("<I", payload, 0)[0] != _TAG_GRUB_BUNDLE:
        raise ValueError("embedded material instance is not a supported Grub bundle")
    major, minor = int(payload[4]), int(payload[5])
    if major > 1 or (major == 1 and minor >= 1):
        if len(payload) < 20:
            raise ValueError("embedded material bundle header is truncated")
        count = struct.unpack_from("<I", payload, 16)[0]
        headers_start = 20
    else:
        count = struct.unpack_from("<H", payload, 6)[0]
        headers_start = 16
    if count > 4096 or headers_start + count * 24 > len(payload):
        raise ValueError("embedded material bundle table is invalid")
    rows: list[dict] = []
    for index in range(int(count)):
        base = headers_start + index * 24
        tag, bmaj, bmin, _meta_count, _meta_offset, data_offset, compressed, uncompressed = struct.unpack_from(
            "<IBBHIIII", payload, base
        )
        size = int(uncompressed or compressed)
        if compressed != uncompressed and uncompressed:
            raise ValueError("compressed embedded material child is not supported")
        if data_offset < 0 or data_offset + size > len(payload):
            raise ValueError("embedded material child payload is out of bounds")
        rows.append({
            "index": index,
            "tag": int(tag),
            "major": int(bmaj),
            "minor": int(bmin),
            "data": payload[data_offset:data_offset + size],
        })
    return rows


def _embedded_material_resource_path(data: bytes) -> str:
    length_info = _read_7bit_uint(bytes(data or b""), 0)
    if length_info is None:
        return ""
    byte_count, length_size = length_info
    start = length_size
    end = start + int(byte_count)
    if byte_count <= 0 or end > len(data):
        return ""
    try:
        return bytes(data[start:end]).decode("utf-8").rstrip("\x00")
    except UnicodeDecodeError:
        return ""


def embedded_material_instance_components(data: bytes) -> dict:
    """Decode resource-path and inline shader-parameter children from a MatI bundle."""
    resource_paths: list[str] = []
    parameter_blobs: list[bytes] = []
    for row in _embedded_bundle_payloads(data):
        if row["tag"] == _TAG_MATERIAL_RESOURCE:
            path = _embedded_material_resource_path(row["data"])
            if path and path.casefold() not in {value.casefold() for value in resource_paths}:
                resource_paths.append(path)
        elif row["tag"] == _TAG_MATERIAL_SHADER_PARAMETER:
            parameter_blobs.append(bytes(row["data"]))
    return {
        "resource_paths": resource_paths,
        "parameter_blobs": parameter_blobs,
    }


def inspect_embedded_material_instance_runtime(
    content: Path,
    material_instance_data: bytes,
    *,
    material_label: str = "embedded-material-instance",
    material_source: dict | None = None,
    vehicle_archive: Path | None = None,
    include_texture_assets: bool = True,
) -> dict:
    """Resolve an embedded WheelStyle MatI through its nested MATI + MTPR children.

    include_texture_assets=False は、参照Textureの中身（Swatchの寸法・形式）の読み取りを省く。
    Textureの割当（material_texture_bindings）は従来どおり返す。車体trimの色の計算で、
    材質ごとにTextures.zipを開き直す時間（1回約0.1秒）を避けるために使う。

    FH6 stock WheelStyle materials are a bundle-of-bundles: the outer ``MatI``
    carries a nested material-resource path (``MATI``) plus zero or more inline
    shader-parameter blobs (``MTPR``). The base material supplies the shader
    family/defaults and the inline MTPR values override that base instance.
    """
    data = bytes(material_instance_data or b"")
    result = {
        "available": False,
        "material_available": bool(data),
        "shader_available": False,
        "material_path": str(material_label or "embedded-material-instance"),
        "material_source": material_source or {"kind": "embedded-wheelstyle-modelbin"},
        "material_size": len(data),
        "material_sha256": _sha256_bytes(data) if data else None,
        "error": None,
    }
    try:
        if not data:
            raise ValueError("embedded material instance payload is empty")
        components = embedded_material_instance_components(data)
        resource_paths = list(components.get("resource_paths") or [])
        parameter_blobs = list(components.get("parameter_blobs") or [])
        result.update({
            "material_resource_paths": resource_paths,
            "inline_parameter_blob_count": len(parameter_blobs),
        })
        if not resource_paths:
            raise ValueError("embedded material instance contains no material-resource path")

        resource_path = resource_paths[0]
        base_data, base_source = _material_source(content, resource_path, vehicle_archive)
        family = shader_family_from_material(base_data)
        shader_refs = _shader_refs_from_material(base_data)
        base_texture_refs = _texture_refs_from_material(base_data)
        inline_texture_refs: list[str] = []
        for blob in parameter_blobs:
            for ref in _texture_refs_from_material(blob):
                if ref.casefold() not in {value.casefold() for value in inline_texture_refs}:
                    inline_texture_refs.append(ref)
        texture_refs = list(base_texture_refs)
        for ref in inline_texture_refs:
            if ref.casefold() not in {value.casefold() for value in texture_refs}:
                texture_refs.append(ref)
        result.update({
            "resolved_material_path": resource_path,
            "resolved_material_source": base_source,
            "resolved_material_size": len(base_data),
            "resolved_material_sha256": _sha256_bytes(base_data),
            "shader_family": family,
            "material_shader_refs": shader_refs,
            "material_texture_refs": texture_refs,
        })
        if not family:
            raise ValueError("resolved material contains no shaderbin family reference")

        shader_source, shader_member, xml_member, shader_data, xml_data = _shader_bundle(
            content, family, shader_refs
        )
        root = ET.fromstring(xml_data)
        ids = shader_parameter_ids(shader_data, root)
        texture_ids = shader_texture_parameter_ids(shader_data, root)
        defaults: dict[str, dict] = {}
        base_overrides: dict[str, dict] = {}
        inline_overrides: dict[str, dict] = {}
        effective: dict[str, dict] = {}
        for name, meta in ids.items():
            default = decode_shader_default(shader_data, meta["default_record_offset"], meta["size"])
            base_override = decode_material_override(base_data, meta["parameter_id_hex"], meta["size"])
            inline_override = None
            for blob in parameter_blobs:
                candidate = decode_material_override(blob, meta["parameter_id_hex"], meta["size"])
                if candidate is not None:
                    inline_override = candidate
            if default is not None:
                defaults[name] = {"value": default}
            if base_override is not None:
                base_overrides[name] = {"value": base_override}
            if inline_override is not None:
                inline_overrides[name] = {"value": inline_override}
            value = inline_override if inline_override is not None else base_override if base_override is not None else default
            if value is not None:
                effective[name] = {"value": value}

        base_texture_bindings = material_texture_bindings(base_data, shader_data, root)
        inline_texture_bindings: list[dict] = []
        for blob in parameter_blobs:
            inline_texture_bindings.extend(material_texture_bindings(blob, shader_data, root))
        by_name = {str(row.get("parameter_name") or ""): dict(row) for row in base_texture_bindings}
        for row in inline_texture_bindings:
            by_name[str(row.get("parameter_name") or "")] = dict(row)
        texture_bindings = [by_name[key] for key in sorted(by_name) if key]
        texture_assets = (inspect_material_texture_assets(content, texture_refs, vehicle_archive=vehicle_archive)
                          if include_texture_assets else [])
        for asset in texture_assets:
            if not isinstance(asset, dict):
                continue
            target = _normalized_game_relative(str(asset.get("reference") or "")).casefold()
            names = [
                str(row.get("parameter_name") or "")
                for row in texture_bindings
                if _normalized_game_relative(str(row.get("path") or "")).casefold() == target
            ]
            if names:
                asset["shader_texture_parameters"] = names

        merged_overrides = dict(base_overrides)
        merged_overrides.update(inline_overrides)
        result.update({
            "available": True,
            "shader_available": True,
            "shader_source": {**shader_source, "member": shader_member, "xml_member": xml_member},
            "shader_sha256": _sha256_bytes(shader_data),
            "shader_xml_sha256": _sha256_bytes(xml_data),
            "parameter_count": len(ids),
            "texture_parameter_count": len(texture_ids),
            "shader_texture_parameters": list(texture_ids),
            "material_texture_bindings": texture_bindings,
            "material_texture_assets": texture_assets,
            "semantic_external_user_color_inputs": semantic_external_user_color_evidence(root, ids),
            "base_override_count": len(base_overrides),
            "inline_override_count": len(inline_overrides),
            "override_count": len(merged_overrides),
            "base_overrides_focus": focus_parameters(base_overrides),
            "inline_overrides_focus": focus_parameters(inline_overrides),
            "overrides_focus": focus_parameters(merged_overrides),
            "effective_focus": focus_parameters(effective),
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result

def _number(effective: dict, name: str) -> float | None:
    value = ((effective.get(name) or {}).get("value"))
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _bool(effective: dict, name: str) -> bool | None:
    value = ((effective.get(name) or {}).get("value"))
    return bool(value) if isinstance(value, bool) else None


def _bounded(value: float | None, fallback: float) -> float:
    if value is None or not math.isfinite(float(value)):
        return fallback
    return max(0.0, min(1.0, float(value)))


def _roughness_from_shift(shift: float | None, fallback: float = 0.42) -> float:
    if shift is None:
        return fallback
    if shift <= -0.95:
        return 0.08
    if shift <= -0.75:
        return 0.20
    if shift <= -0.55:
        return 0.32
    if shift <= -0.35:
        return 0.50
    return fallback



def material_defined_paint_color(effective_focus: dict, shader_family: str) -> dict:
    """Return a renderer colour only when the installed material defines it itself.

    Finish-only livery materials declare ``num_input_colors == 0`` in GameDB.
    For automotive-paint shader families, ``PaintColorColorParam`` is therefore
    usable as material-owned colour evidence when the user-colour switches are
    not enabled.  This helper never falls back to descriptor RGB and never
    invents a colour for texture-driven families such as carbon fibre.
    """
    family = str(shader_family or "").casefold()
    automotive_families = {
        "car_automotive_paint", "car_automotive_paint_user",
        "car_candy_paint", "car_candy_paint_user",
        "car_glitter_paint", "car_glitter_paint_user",
    }
    if family not in automotive_families:
        return {
            "available": False,
            "source": "material_runtime_paint_color_param",
            "reason": "shader family is not an automotive paint family",
        }

    for switch_name in ("UserColorSwitchBool", "UserColorOverrideBool"):
        switch = _bool(effective_focus, switch_name)
        if switch is True:
            return {
                "available": False,
                "source": "material_runtime_paint_color_param",
                "reason": f"{switch_name} requires an external/user colour",
            }

    raw = ((effective_focus.get("PaintColorColorParam") or {}).get("value"))
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return {
            "available": False,
            "source": "material_runtime_paint_color_param",
            "reason": "PaintColorColorParam is unavailable",
        }
    values: list[float] = []
    for item in raw[:4]:
        if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            return {
                "available": False,
                "source": "material_runtime_paint_color_param",
                "reason": "PaintColorColorParam contains a non-finite component",
            }
        values.append(max(0.0, min(1.0, float(item))))
    while len(values) < 4:
        values.append(1.0)
    rgba = "#" + "".join(f"{int(round(component * 255.0)):02x}" for component in values[:4])
    return {
        "available": True,
        "source": "material_runtime_paint_color_param",
        "parameter": "PaintColorColorParam",
        "normalized_rgba": [round(component, 9) for component in values[:4]],
        "rgba_hex": rgba,
        "reason": "installed FH6 material supplies its own automotive paint colour",
    }

def release_safe_viewer_candidate(
    material_name: str,
    shader_family: str,
    effective_focus: dict,
    *,
    source: str,
) -> tuple[dict, dict]:
    """Map decoded FH6 material evidence to bounded Viewer PBR controls."""
    material_key = str(material_name or "").casefold()
    family = str(shader_family or "").casefold()
    roughness_shift = _number(effective_focus, "Roughness_Shift_floatVal")
    metalness_param = _number(effective_focus, "Metalness_floatVal")
    clearcoat_coverage = _number(effective_focus, "ClearCoatCoverage_floatVal")
    clearcoat_roughness = _number(effective_focus, "ClearCoatRoughness_floatVal")
    clearcoat_on_livery = _bool(effective_focus, "ClearCoatOnLiveryBool")
    flake_roughness = _number(effective_focus, "FlakeRoughness_floatVal")
    flake_coverage = _number(effective_focus, "FlakeCoverage_floatVal")
    glitter_intensity = _number(effective_focus, "GlitterIntensity_floatVal")
    glancing_angle_strength = _number(effective_focus, "GlancingAngleStrength_floatVal")
    glancing_flop_power = _number(effective_focus, "GlancingFlopPower_floatVal")
    user_color_enabled = _bool(effective_focus, "UserColorSwitchBool")
    # 第 2 色（ラメの色）の使い方を決める切り替え（2026-11-18）。入れ替えが偽で、角度の切り替え（ツートン）が偽なら、
    # 第 1 色が地の色、第 2 色がラメ（FlakeColor）の色になる（car_glitter_paint_user・car_automotive_paint_user の引数）。
    user_color_swap = _bool(effective_focus, "UserColorSwapPrimarySecondaryBool")
    user_color_flop_switch1 = _bool(effective_focus, "UserColorFlopSwitch1Bool")
    user_color_flop_switch2 = _bool(effective_focus, "UserColorFlopSwitch2Bool")
    clearcoat_normal_u2_tiling = _number(effective_focus, "ClearCoatNormalU2_Tiling_floatVal")
    clearcoat_normal_v2_tiling = _number(effective_focus, "ClearCoatNormalV2_Tiling_floatVal")
    anisotropy_strength = _number(effective_focus, "AnisoStrength_floatVal")
    uv_choice_on_ch1_off_ch2 = _bool(effective_focus, "UVChoice_OnCh1_OffCh2Bool")
    game_parameters = {
        key: value for key, value in {
            "roughness_shift": roughness_shift,
            "metalness": metalness_param,
            "clearcoat_coverage": clearcoat_coverage,
            "clearcoat_roughness": clearcoat_roughness,
            "clearcoat_on_livery": clearcoat_on_livery,
            "flake_roughness": flake_roughness,
            "flake_coverage": flake_coverage,
            "glitter_intensity": glitter_intensity,
            "glancing_angle_strength": glancing_angle_strength,
            "glancing_flop_power": glancing_flop_power,
            "user_color_enabled": user_color_enabled,
            "user_color_swap_primary_secondary": user_color_swap,
            "user_color_flop_switch1": user_color_flop_switch1,
            "user_color_flop_switch2": user_color_flop_switch2,
            "clearcoat_normal_u2_tiling": clearcoat_normal_u2_tiling,
            "clearcoat_normal_v2_tiling": clearcoat_normal_v2_tiling,
            "anisotropy_strength": anisotropy_strength,
            "uv_choice_on_ch1_off_ch2": uv_choice_on_ch1_off_ch2,
        }.items() if value is not None
    }
    candidate = {
        "roughness": 0.42,
        "metalness": 0.04,
        "env_map_intensity": 1.15,
        "clearcoat": 0.35,
        "clearcoat_roughness": 0.25,
        "base_clearcoat_scale_home_soft": 0.22,
        "source": source,
        "release_safe_fallback": True,
    }
    carbon_families = {"car_carbonfiber", "car_carbonfiber_user"}
    standard_families = {"car_standard", "car_standard_user"}
    automotive_families = {
        "car_automotive_paint", "car_automotive_paint_user",
        "car_candy_paint", "car_candy_paint_user",
        "car_glitter_paint", "car_glitter_paint_user",
    }
    if family in carbon_families:
        candidate.update({
            "roughness": 0.50 if "matte" in material_key else 0.24,
            "metalness": _bounded(metalness_param, 0.20),
            "env_map_intensity": 1.15,
            "clearcoat": _bounded(clearcoat_coverage, 1.0),
            "clearcoat_roughness": _bounded(clearcoat_roughness, 0.60 if "matte" in material_key else 0.0),
        })
        if (
            clearcoat_normal_u2_tiling is not None
            and clearcoat_normal_v2_tiling is not None
        ):
            candidate.update({
                "detail_normal_u_tiling": max(0.01, min(128.0, clearcoat_normal_u2_tiling)),
                "detail_normal_v_tiling": max(0.01, min(128.0, clearcoat_normal_v2_tiling)),
                "detail_normal_intensity": 1.0,
                "detail_normal_source": "installed FH6 carbon-fibre normal swatch; ClearCoatNormal U2/V2 tiling",
            })
            if uv_choice_on_ch1_off_ch2 is not None:
                candidate.update({
                    "detail_normal_three_uv_channel": 0 if uv_choice_on_ch1_off_ch2 else 1,
                    "detail_normal_uv_choice_on_ch1_off_ch2": uv_choice_on_ch1_off_ch2,
                    "detail_normal_uv_resolution": "shader_parameter",
                })
            else:
                if family == "car_carbonfiber_user":
                    # r186: r185 raw-normal A/B on shipped CarbonFiberMatte showed
                    # TEXCOORD_0 carrying the coherent twin-twill detail mapping while
                    # TEXCOORD_1 was effectively flat for this fixed shader path.
                    # Promote UV0 only for the audited user-carbon family; retain both
                    # candidates for diagnostics and keep other carbon families closed.
                    candidate.update({
                        "detail_normal_three_uv_channel": 0,
                        "detail_normal_uv_resolution": "audited_fixed_shader_path_uv0",
                        "detail_normal_uv_candidates": [0, 1],
                        "detail_normal_uv_evidence": "r185 CarbonFiberMatte raw-normal UV0/UV1 A/B plus mesh UV attribute diagnostics",
                    })
                else:
                    candidate.update({
                        "detail_normal_uv_resolution": "fixed_shader_path_unresolved",
                        "detail_normal_uv_candidates": [0, 1],
                    })
        if anisotropy_strength is not None:
            candidate["anisotropy_strength"] = max(0.0, min(1.0, anisotropy_strength))
    elif family in standard_families:
        metal_surface = material_key.startswith((
            "aluminum", "brass", "chromium", "copper", "gold", "steel", "damascus", "galvanized"
        ))
        candidate.update({
            "roughness": _roughness_from_shift(roughness_shift),
            "metalness": 1.0 if metal_surface else 0.05,
            "env_map_intensity": 1.45 if metal_surface else 1.10,
            "clearcoat": 0.0,
            "clearcoat_roughness": 0.0,
        })
    elif family in automotive_families:
        audited_clearcoat = clearcoat_coverage if clearcoat_coverage is not None else 1.0
        audited_clearcoat_roughness = clearcoat_roughness if clearcoat_roughness is not None else 0.0
        base_roughness = 0.30 + 0.35 * _bounded(audited_clearcoat_roughness, 0.0)
        if roughness_shift is not None and roughness_shift < 0.0:
            base_roughness += 0.25 * roughness_shift

        flake_cov = _bounded(flake_coverage, 0.0)
        flake_rough = _bounded(flake_roughness, _bounded(base_roughness, 0.36))
        glitter = max(0.0, min(2.0, float(glitter_intensity))) if glitter_intensity is not None else 0.0
        glancing = _bounded(glancing_angle_strength, 0.0)
        flop_power = max(0.25, min(8.0, float(glancing_flop_power))) if glancing_flop_power is not None else 2.0

        # r176: keep the clearcoat/base roughness evidence separate from the
        # metallic-flake response.  A coverage-weighted blend gives the
        # single-value Three.js roughness a conservative average, while the
        # original flake/glancing controls remain available to the Viewer.
        flake_mix = min(0.28, 0.28 * flake_cov)
        average_roughness = (1.0 - flake_mix) * _bounded(base_roughness, 0.36) + flake_mix * flake_rough
        flake_response = min(1.0, flake_cov * (0.55 + 0.45 * min(1.0, glitter)))
        glancing_response = min(0.35, glancing * (0.55 + 0.45 * flake_cov) + 0.08 * flake_cov * min(1.0, glitter))
        env_intensity = max(1.0, min(1.55, 1.18 + 0.14 * flake_cov + 0.06 * min(1.0, glitter) + 0.08 * glancing))
        candidate.update({
            "roughness": _bounded(average_roughness, 0.36),
            "metalness": 0.06,
            "env_map_intensity": env_intensity,
            "clearcoat": _bounded(audited_clearcoat, 1.0),
            "clearcoat_roughness": _bounded(audited_clearcoat_roughness, 0.0),
            "flake_roughness": flake_rough,
            "flake_coverage": flake_cov,
            "flake_response_strength": flake_response,
            "glitter_intensity": glitter,
            "glancing_angle_strength": glancing,
            "glancing_flop_power": flop_power,
            "glancing_response_strength": glancing_response,
        })
    if material_key == "aluminumbrushed":
        candidate.update({
            "roughness": 0.32, "metalness": 1.0, "env_map_intensity": 1.70,
            "clearcoat": 1.0, "clearcoat_roughness": 0.06,
            "base_clearcoat_scale_home_soft": 0.62,
            "detail_normal_u_tiling": 4.0, "detail_normal_v_tiling": 10.0,
            "detail_normal_intensity": 1.0,
            "detail_normal_source": "FH6 AluminumBrushed material: dtl_brushed_001, U=4, V=10, Normal_Intensity=1",
        })
    elif material_key == "aluminumpolished":
        candidate.update({
            "roughness": 0.0, "metalness": 1.0, "env_map_intensity": 1.32,
            "clearcoat": 1.0, "clearcoat_roughness": 0.0,
            "base_clearcoat_scale_home_soft": 0.22,
        })
    candidate["basis"] = (
        f"FH6 material {material_name or 'unknown'}; shader family={shader_family or 'unknown'}; "
        f"decoded parameters={game_parameters}. Viewer values are bounded approximations, not exact 参照ツール shader equations."
    )
    return candidate, game_parameters
