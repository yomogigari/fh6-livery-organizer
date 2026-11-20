# -*- coding: utf-8 -*-
"""FH6原本Tire ModelBin/MatI→SwatchBinのNormalをGLB側面へ接続する研究アダプター。

GameDBから既に選択済みのタイヤModelBin、原本MatI、car_tires_pg
Shader XML、インストール済みTextures.zip、四輪の原本GLBだけを使う。
車種/タイヤ名/HORIZON固定や模造Texture、原本への書き込みは行わない。
UV0+MeshBlob affineとPBR法線は研究比較でありShader/Xbox完全一致ではない。
FEOW 2-image確認済みパスには接続しない。
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
import re
import struct
import zlib
import zipfile
from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET

from . import wheel_morph_internal as wm
from .fh6_swatch import decode_swatch_image
from .material_runtime import _game_refs_from_material
from .source_tire_texture_bridge import _texture_member
from .source_tire_glb_bridge import read_glb
from .source_tire_mesh_uv_affine import mesh_affines
from .portable_mesh_converter import seal_firstparty_chassis_metadata
from .json_tree_copy import json_tree_deepcopy  # GLB の中身まるごとの複製（deepcopy と同じ結果で約 3 倍速い）

ROLES = ("sidewall", "tread", "scaling_text")
WHEELS = ("front_left", "front_right", "rear_left", "rear_right")


def _expected_tire_wheels(doc: dict) -> tuple[str, ...]:
    """タイヤを付ける車輪の役割。原本の車輪がちょうど 4 つの角の車は従来どおり 4 輪。

    原本が 3 輪（角が 3 つ）・6 輪（中央の 2 輪）の車（変換の段階の印が偽）は、タイヤの GLB にある役割
    （source_tire_local_runtime が実際の WheelStyle から作ったもの）。角が 3 つ未満なら拒否する。
    """
    from .source_tire_glb_bridge import ALL_WHEEL_ROLES, _standard_four_corner_flags
    if _standard_four_corner_flags(doc) != {False}:
        return WHEELS
    present = {mesh.get("extras", {}).get("lo4_tire_source_wheel") for mesh in doc.get("meshes", [])
               if mesh.get("extras", {}).get("lo4_part_type") == "Tire"}
    roles = tuple(role for role in ALL_WHEEL_ROLES if role in present)
    if sum(1 for role in WHEELS if role in present) < 3:
        raise OriginalTireNormalError("3 輪・6 輪の車のタイヤの車輪が不足しています")
    return roles
SCHEMA = "lo4fh6.original-tire-source-normal-pbr-research.v1"
MAX_SWATCH = 32 * 1024 * 1024
# Normalとして受け付けるSwatch encoding。5/6=BC5、9=BC7、13=非圧縮RGBA8（DXGI 28）。
UNCOMPRESSED_NORMAL_ENCODING = 13
NORMAL_SWATCH_ENCODINGS = (5, 6, 9, UNCOMPRESSED_NORMAL_ENCODING)


class OriginalTireNormalError(ValueError):
    """出典が不明・不一致なら描画を偽装せず停止する."""


def _require_tangent_normal(image, ref: str) -> None:
    """非圧縮RGBA8は汎用のカラー形式のため、接空間Normalの符号化であることを確かめる。

    接空間Normalは X/Y（R/G）が中央値128付近、Z（B）が常に正（128以上）で
    平均が高い。色テクスチャを誤ってNormalとして使わないよう、外れたら停止する。
    13はsRGB版（DXGI 29）もあり得る（参照ツール texture.rs）。平坦なNormalを
    sRGBで格納するとR/Gは約188になるため、この中央値の検査で線形格納も確かめる。
    """
    from PIL import ImageStat

    stat = ImageStat.Stat(image)
    mean_r, mean_g, mean_b = stat.mean[:3]
    min_b = stat.extrema[2][0]
    if not (96.0 <= mean_r <= 160.0 and 96.0 <= mean_g <= 160.0
            and mean_b >= 192.0 and min_b >= 128):
        raise OriginalTireNormalError(
            "原本SwatchのRGBA8が接空間Normalの符号化ではありません: " + ref
            + f" / 平均RGB=({mean_r:.1f},{mean_g:.1f},{mean_b:.1f}) 最小B={min_b}")


class TireParentNormalMissingError(OriginalTireNormalError):
    """元MatIと親MaterialBinの両方にNormalが無い。署名済Shader既定値だけを確認する。"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parent_materialbin_normal(materials_zip: Path, member: str, parameter: str,
                               shader_xml: bytes) -> tuple[str, str]:
    """元MaterialBin MTPRに実在するTexture2DだけをNormal既定値として取り込む。

    参照製品のDefaults→MatI override順を参考にするが、
    実参照はModelBinのMaterialResource文字列とFH6原本CRC/Shaderで確定。
    欠損時に仮Normalを生成しない。非Tire scopeや型不一致は安全停止。
    """
    from .source_tire_shader_binding import (
        _read_parameters, shader_xml_ids, TireBindingError,
    )
    if not materials_zip.is_file() or materials_zip.name.casefold() != "materials.zip":
        raise OriginalTireNormalError("元Tire Materials.zipが見つかりません")
    if not member.startswith("_fmnext/tires/") or member.count("/") != 2:
        raise OriginalTireNormalError("元Tire MaterialBinの参照がTire scope外")
    with zipfile.ZipFile(materials_zip) as source:
        matched = [item for item in source.infolist()
                   if not item.is_dir() and item.filename.casefold() == member.casefold()]
        if len(matched) != 1:
            raise OriginalTireNormalError("元Tire MaterialBinが一意ではありません: " + member)
        info = matched[0]
        if info.flag_bits & 1 or not 0 < info.file_size < 1024 * 1024:
            raise OriginalTireNormalError("元Tire MaterialBinの暗号化/異常サイズ")
        raw = source.read(info)
    if b"car_tires_pg.shaderbin" not in raw:
        raise OriginalTireNormalError("元Tire MaterialBinのShader参照が不一致")
    blobs = wm._parse_blobs(raw)
    params = [bytes(item.data) for item in blobs if item.tag == 0x4D545052]
    if len(params) != 1:
        raise OriginalTireNormalError("元Tire MaterialBinのMTPRが一意ではありません")
    key = zlib.crc32(parameter.encode("ascii"))
    if shader_xml_ids(shader_xml).get(key) != (parameter, 6):
        raise OriginalTireNormalError("元Tire MaterialBin NormalのShader CRC/型が不一致")
    try:
        rows = _read_parameters(params[0])
    except TireBindingError as exc:
        raise OriginalTireNormalError("元Tire MaterialBinのMTPRが不正: " + str(exc)) from exc
    selected = [row for row in rows if int(row["parameter_crc32"], 16) == key]
    if not selected:
        raise TireParentNormalMissingError(
            "元Tire MatIと親MaterialBinの両方でNormal入力が未設定: " + parameter)
    if len(selected) != 1 or selected[0]["type"] != 6:
        raise OriginalTireNormalError("元Tire親MaterialBin Normal Texture2D型が不一致")
    return _texture_member(selected[0]["value"]), _sha(raw)


# Normal（Unique系マップ）のUV繰り返し数。FH6原本のMatI MTPR → 親MaterialBin MTPRの順に解決する。
# 例: tires_pg_tread=[6,1]、tires_pg_sidewall=[0.25,1]、tires_pg_sidewall_legacy=[1,1]。
# 側面はMeshBlob affine後のU範囲が約4.0のため、0.25で円周をちょうど1周する（2026-11-17 Jaguar4354実測）。
UNIQUE_MAP_TILING_PARAMETER = "UniqueMapTilingVector2"
# 刻印（scaling_text）は親が側面MaterialBin（0.25）だが、MeshBlob affine後のU範囲が約10.0で、
# 0.25を掛けると円周2.5周となり整数周にならない。TextUVTiling等の別パラメーターの関与が
# 未解明のため、従来の受入表示（繰り返し数を適用しない）を維持し、保留として記録する。
TIRE_TILING_PENDING_ROLES = ("scaling_text",)


def _parent_materialbin_vector2(materials_zip: Path, member: str, parameter: str,
                                shader_xml: bytes) -> tuple[list[float] | None, str]:
    """親MaterialBin MTPRのVector2（型11）を読む。無ければNone。参照範囲・一意性は厳密に検査。"""
    return _parent_materialbin_param(materials_zip, member, parameter, shader_xml, 11)


def _parent_materialbin_param(materials_zip: Path, member: str, parameter: str,
                              shader_xml: bytes, kind: int) -> tuple[object | None, str]:
    """親MaterialBin MTPRの指定型（2=Float、3=Bool、11=Vector2）の値を読む。無ければNone。"""
    from .source_tire_shader_binding import (
        _read_parameters, shader_xml_ids, TireBindingError,
    )
    if not materials_zip.is_file() or materials_zip.name.casefold() != "materials.zip":
        raise OriginalTireNormalError("元Tire Materials.zipが見つかりません")
    if not member.startswith("_fmnext/tires/") or member.count("/") != 2:
        raise OriginalTireNormalError("元Tire MaterialBinの参照がTire scope外")
    with zipfile.ZipFile(materials_zip) as source:
        matched = [item for item in source.infolist()
                   if not item.is_dir() and item.filename.casefold() == member.casefold()]
        if len(matched) != 1:
            raise OriginalTireNormalError("元Tire MaterialBinが一意ではありません: " + member)
        info = matched[0]
        if info.flag_bits & 1 or not 0 < info.file_size < 1024 * 1024:
            raise OriginalTireNormalError("元Tire MaterialBinの暗号化/異常サイズ")
        raw = source.read(info)
    if b"car_tires_pg.shaderbin" not in raw:
        raise OriginalTireNormalError("元Tire MaterialBinのShader参照が不一致")
    params = [bytes(item.data) for item in wm._parse_blobs(raw) if item.tag == 0x4D545052]
    if len(params) != 1:
        raise OriginalTireNormalError("元Tire MaterialBinのMTPRが一意ではありません")
    key = zlib.crc32(parameter.encode("ascii"))
    if shader_xml_ids(shader_xml).get(key, (parameter, kind))[0] != parameter:
        raise OriginalTireNormalError("元Tire MaterialBinのShader CRCが不一致: " + parameter)
    try:
        rows = _read_parameters(params[0])
    except TireBindingError as exc:
        raise OriginalTireNormalError("元Tire MaterialBinのMTPRが不正: " + str(exc)) from exc
    selected = [row for row in rows if int(row["parameter_crc32"], 16) == key]
    if not selected:
        return None, _sha(raw)
    if len(selected) != 1 or selected[0]["type"] != kind:
        raise OriginalTireNormalError("元Tire親MaterialBinの" + parameter + "型が不一致")
    return selected[0]["value"], _sha(raw)


def _valid_tiling(value) -> tuple[float, float]:
    if (not isinstance(value, list) or len(value) != 2
            or any(not isinstance(v, (int, float)) or not math.isfinite(v)
                   or not 0.001 <= v <= 100 for v in value)):
        raise OriginalTireNormalError("元TireのUniqueMapTilingが不正: " + repr(value))
    return float(value[0]), float(value[1])


def tire_unique_map_tiling(mati_bindings_map: dict, *, role: str,
                           materials_zip: Path | None, material_member: str | None,
                           shader_xml: bytes) -> dict:
    """Normal（Unique系マップ）のUV繰り返し数を原本から解決する。

    MatIの上書き → 親MaterialBin の順。どちらにも無ければ(1,1)で、その事実を記録する。
    刻印（scaling_text）は保留（TIRE_TILING_PENDING_ROLES）として適用しない。
    """
    if role in TIRE_TILING_PENDING_ROLES:
        return {"scale": (1.0, 1.0), "origin": "pending-" + role}
    override = mati_bindings_map.get(UNIQUE_MAP_TILING_PARAMETER)
    if override is not None:
        if override.get("type") != 11:
            raise OriginalTireNormalError("元MatIのUniqueMapTiling型が不一致")
        return {"scale": _valid_tiling(override.get("value")), "origin": "modelbin_mati"}
    if materials_zip is not None and material_member:
        value, parent_sha = _parent_materialbin_vector2(
            materials_zip, material_member, UNIQUE_MAP_TILING_PARAMETER, shader_xml)
        if value is not None:
            return {"scale": _valid_tiling(value), "origin": "parent_materialbin",
                    "parent_materialbin_sha256": parent_sha}
    return {"scale": (1.0, 1.0), "origin": "unresolved-no-source"}


def tire_original_normal_variant(mati_bytes: bytes, shader_xml: bytes, *,
                                 materials_zip: Path | None = None,
                                 shader_library: Path | None = None) -> dict:
    """元MatIが最優先。欠落時だけ出典一致MaterialBinの既定Normalを検証する。

    Shader/MaterialBin同値を主張せず、実MaterialBin MTPRの存在・型・
    CRCと参照元MatIの一致を署名する。FEOW側面文字は変更しない。
    """
    from .source_tire_shader_binding import (
        TIRE_TEXTURE_PARAMETER, TIRE_LEGACY_NORMAL_PARAMETER,
        normal_reference, TireBindingError, TireUniqueNormMissingError,
    )
    refs = _game_refs_from_material(mati_bytes, '.materialbin')
    if len(refs) != 1:
        raise OriginalTireNormalError('元Tire MatIのMaterialBin出典が一意ではありません')
    source = refs[0].replace(chr(92), '/').casefold()
    prefix = 'game:/media/cars/_library/materials/_fmnext/tires/'
    if not source.startswith(prefix) or '/' in source[len(prefix):]:
        raise OriginalTireNormalError('Tire MatI MaterialBinが原本cars/_library範囲外')
    leaf = source[len(prefix):]
    if leaf in ('tires_pg_sidewall.materialbin', 'tires_pg_tread.materialbin'):
        parameter, variant, family = TIRE_TEXTURE_PARAMETER, '_Standard', 'pg'
    elif leaf in ('tires_pg_sidewall_legacy.materialbin', 'tires_pg_tread_legacy.materialbin'):
        parameter, variant, family = TIRE_LEGACY_NORMAL_PARAMETER, '_Standard_L', 'pg_legacy'
    else:
        raise OriginalTireNormalError('Tire MatIの原本MaterialBinタイプは未対応: ' + leaf)
    root = ET.fromstring(shader_xml)
    tex = [e for e in root.findall('./Textures/Texture')
           if e.get('parametername') == parameter
           and e.get('referenced', '').casefold() == 'true']
    variants = [v for v in root.findall('./Variants/ExportVariant')
                if v.get('name') == variant
                and 'TexCoord0' in [x.strip() for x in v.get('vertexinputs', '').split(',')]
                and parameter in [x.strip() for x in v.get('textureusage', '').split(',')]]
    if len(tex) != 1 or len(variants) != 1:
        raise OriginalTireNormalError('元Tire Shader variant/UV0/Normal Texture2D宣言不一致')
    origin = 'modelbin_mati'
    parent_sha = None
    shader_default_sha = None
    try:
        ref = normal_reference(mati_bytes, shader_xml, normal_parameter=parameter)
        member = _texture_member(ref)
    except TireUniqueNormMissingError as exc:
        if materials_zip is None:
            raise OriginalTireNormalError(
                '元Tire MatI Normal入力が未設定（親MaterialBin未照合）: ' + parameter
            ) from exc
        try:
            member, parent_sha = _parent_materialbin_normal(
                materials_zip, '_fmnext/tires/' + leaf, parameter, shader_xml)
            origin = 'source_materialbin_default'
        except TireParentNormalMissingError:
            # 元MatI→親MaterialBin→元ShaderBin DFPRの順で厳密に継承する。
            # 本体側が現物のShader原本を明示した場合にのみ使用。
            if shader_library is None:
                raise
            from .source_tire_shader_binding import (
                shader_dfpr_normal_default_reference,
            )
            source_shader, source_xml = _source_shader_proof(
                Path(shader_library), return_original_bytes=True)
            if source_xml != shader_xml:
                raise OriginalTireNormalError(
                    '元Tire ShaderBinと呼出し元Shader XMLの実バイトが不一致')
            try:
                shader_ref = shader_dfpr_normal_default_reference(
                    source_shader, shader_xml, normal_parameter=parameter)
                member = _texture_member(shader_ref)
            except TireBindingError as shader_error:
                raise OriginalTireNormalError(
                    '原本ShaderBin DFPRのNormal既定値が不正: ' + str(shader_error)
                ) from shader_error
            origin = 'source_shaderbin_dfpr_default'
            shader_default_sha = _sha(source_shader)
    except TireBindingError as exc:
        raise OriginalTireNormalError('元Tire MatI Normal CRC/Texture2D不一致: ' + str(exc)) from exc
    return {'reference': member, 'original_parameter': parameter, 'shader_variant': variant,
            'material_member': '_fmnext/tires/' + leaf, 'source_family': family,
            'normal_reference_origin': origin,
            'source_parent_materialbin_sha256': parent_sha,
            'source_shaderbin_dfpr_sha256': shader_default_sha}


def select_source_normal(mati_bytes: bytes, shader_xml: bytes | None = None) -> str:
    """原本MatI→ShaderBinのNormalパラメータを選択。PGとLegacyを別Variantで照合。"""
    if shader_xml is not None:
        return tire_original_normal_variant(mati_bytes, shader_xml)['reference']
    # Shader XMLなしの入力は旧合成テスト互換のみ。製品原本には使わない。
    if mati_bytes.startswith(b"burG"):
        raise OriginalTireNormalError('原本MatIはShader XMLなしのファイル名判定を禁止')
    refs = _game_refs_from_material(mati_bytes, ".swatchbin")
    candidates = [ref for ref in refs
                  if re.search(r"(?i)(?:^|_)nrml_[^/\\]+\.swatchbin$", ref)
                  and "_blur_" not in ref.casefold()]
    if len(candidates) != 1:
        raise OriginalTireNormalError(
            f"合成MatIの非Blur Normal参照が一意でありません: {len(candidates)}")
    return _texture_member(candidates[0])

def _source_shader_proof(shader_library: Path, *, return_xml: bool = False,
                         return_original_bytes: bool = False) -> str | tuple[str, bytes] | bytes:
    family = shader_library / "shaders" / "car_tires_pg.zip"
    outer = shader_library / "shaders.zip"
    if family.is_file():
        with zipfile.ZipFile(family) as z:
            raw = z.read("car_tires_pg.shaderbin")
            xml = z.read("car_tires_pg.shaderbin.xml")
    elif outer.is_file():
        with zipfile.ZipFile(outer) as z:
            with zipfile.ZipFile(io.BytesIO(z.read("shaders/car_tires_pg.zip"))) as nested:
                raw = nested.read("car_tires_pg.shaderbin")
                xml = nested.read("car_tires_pg.shaderbin.xml")
    else:
        raise OriginalTireNormalError("原本car_tires_pg ShaderBinが不足")
    root = ET.fromstring(xml)
    parameters = [x for x in root.findall("./Textures/Texture")
                  if x.get("parametername") == "UniqueNorm_Tires_PGTexture"
                  and x.get("referenced", "").casefold() == "true"]
    variants = root.findall("./Variants/ExportVariant")
    if len(parameters) != 1 or not variants or not any(
            "TexCoord0" in x.get("vertexinputs", "").split(", ") and
            "UniqueNorm_Tires_PGTexture" in x.get("textureusage", "").split(",")
            for x in variants):
        raise OriginalTireNormalError("原本Tire ShaderのUniqueNorm/UV契約不一致")
    if return_xml and return_original_bytes:
        raise OriginalTireNormalError("元Tire Shaderの取得形式が二重指定")
    if return_original_bytes:
        # 元Shader実バイトとそのXMLを同じアーカイブから一度に取得する。
        return raw, xml
    return (_sha(raw), xml) if return_xml else _sha(raw)


def _source_material_proof(material_zip: Path, *, include_legacy: bool = False) -> str:
    required = ("_fmnext/tires/tires_pg_sidewall.materialbin",
                "_fmnext/tires/tires_pg_tread.materialbin")
    if include_legacy:
        required += ("_fmnext/tires/tires_pg_sidewall_legacy.materialbin",
                     "_fmnext/tires/tires_pg_tread_legacy.materialbin")
    with zipfile.ZipFile(material_zip) as z:
        rows = [z.read(name) for name in required]
    if not all(b"car_tires_pg.shaderbin" in raw for raw in rows):
        raise OriginalTireNormalError("元Tire MaterialBinがcar_tires_pgを参照しません")
    return _sha(b"".join(rows))


def source_original_tire_base_color(materials_zip: Path, shader_xml: bytes) -> tuple[list[float], str]:
    """元car_tires_pg既定のBaseTyreColourをShader CRC/型とMaterialBinから取得。

    仮の黒色定数は使わない。元値は線形RGBAでglTF baseColorFactorに渡す。
    これは元Shaderの入力値であり、最終Xboxシェーディング同値ではない。
    """
    from .source_tire_shader_binding import shader_xml_ids, _read_parameters
    key = zlib.crc32(b"BaseTyreColourColorParam")
    if shader_xml_ids(shader_xml).get(key) != ("BaseTyreColourColorParam", -1):
        raise OriginalTireNormalError("Tire既定のBaseTyreColour元Shaderパラメータ不一致")
    with zipfile.ZipFile(materials_zip) as source:
        raw = source.read("_fmnext/tires/tires_pg.materialbin")
    if b"car_tires_pg.shaderbin" not in raw:
        raise OriginalTireNormalError("Tire既定色MaterialBinの元Shader参照が不一致")
    blobs = [bytes(blob.data) for blob in wm._parse_blobs(raw)
             if blob.tag == 0x4D545052]
    if len(blobs) != 1:
        raise OriginalTireNormalError("元BaseTyreColourのMTPRが一意ではありません")
    matches = [row for row in _read_parameters(blobs[0])
               if int(row["parameter_crc32"], 16) == key]
    if len(matches) != 1 or matches[0]["type"] != 1:
        raise OriginalTireNormalError("元BaseTyreColourのColor型・CRCが不正")
    values = matches[0]["value"]
    if (not isinstance(values, list) or len(values) != 4
            or any(not isinstance(v, float) or not math.isfinite(v) or v < 0 or v > 1
                   for v in values)):
        raise OriginalTireNormalError("元BaseTyreColourの線形RGBAが不正")
    return values, _sha(raw)


def _original_models(model_zip: Path):
    raw = model_zip.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:
            raise OriginalTireNormalError("Tire原本ZIP CRC不一致")
        # 独立Wheel/Tire取付けの既存第一者モデル名判定を共有。
        # 単一1原本・左右/前後2原本・四隅4原本とも同じViewer原本選択を使う。
        from .source_tire_local_runtime import (
            _original_tire_model_entries, LocalTireSourceError, tire_archive_model_name,
        )
        try:
            chosen = _original_tire_model_entries(z, tire_archive_model_name(model_zip))
        except LocalTireSourceError as exc:
            raise OriginalTireNormalError("Tire原本ModelBinの役割判定が不完全") from exc
        names = tuple(dict.fromkeys(entry.filename for entry in chosen.values()))
        if len(names) not in (1, 2, 4):
            raise OriginalTireNormalError("元Tireの選択ModelBin数が不正")
        result = {}
        for name in names:
            data = z.read(name)
            blobs = wm._parse_blobs(data)
            material_blobs = [b for b in blobs
                              if b.tag == 0x4d617449 and b.identifier is not None]
            if len(material_blobs) != len({int(b.identifier) for b in material_blobs}):
                raise OriginalTireNormalError("元Tire MatIのMaterialIDが重複")
            material = {int(b.identifier): b for b in material_blobs}
            if not material:
                raise OriginalTireNormalError("元Tire MatIの宣言がありません")
            digest = _sha(data)
            if digest in result:
                raise OriginalTireNormalError("異なる原本Tire ModelBinのSHAが重複")
            result[digest] = (data, blobs, material)
        return _sha(raw), result


def _original_swatch_images(textures_zip: Path, refs: set[str]):
    if not textures_zip.is_file() or textures_zip.name.casefold() != "textures.zip":
        raise OriginalTireNormalError("原本media/cars/_library/Textures.zipが見つかりません")
    image_map = {}
    with zipfile.ZipFile(textures_zip) as z:
        # 参照名は元MatIからだけ取得。ファイル名の曖昧な部分一致は拒否する。
        index = {}
        for info in z.infolist():
            if info.is_dir():
                continue
            normalized = info.filename.replace("\\", "/").casefold().lstrip("/")
            index.setdefault(normalized, []).append(info)
        for ref in sorted(refs):
            suffix = ref.casefold()
            hits = [info for name, infos in index.items()
                    if name == suffix or name.endswith("/" + suffix)
                    for info in infos]
            if len(hits) != 1:
                raise OriginalTireNormalError(f"元Normal Swatchの原本参照が一意でありません: {ref} count={len(hits)}")
            item = hits[0]
            if item.flag_bits & 1 or not 0 < item.file_size <= MAX_SWATCH:
                raise OriginalTireNormalError("原本Swatchに暗号化/異常サイズあり")
            raw = z.read(item)  # 読んだエントリのCRCを検証する
            image, meta = decode_swatch_image(raw)
            # 実FH6原本のNormal材質でもSwatch encoding=9 (BC7)が使われる。
            # MatIの一意な*_nrml参照とShaderのUniqueNorm契約が成立する
            # この研究経路に限りBC5(5/6)とBC7(9)の既存第一者復号を許す。
            # BC7のRGBをBC5のXY正規化に置換しない。Xbox Shader一致は未承認。
            # 側面文字のNormal（tire_letters_dunlop_b/michelin_white等）は
            # 非圧縮RGBA8（encoding=13、DXGI 28）で格納されている。複合材質の
            # 経路は既に13を受け付けており、Normal経路だけが停止していた。
            encoding = meta.get("encoding")
            if (image is None or type(encoding) is not int
                    or encoding not in NORMAL_SWATCH_ENCODINGS
                    or image.mode != "RGB" or min(image.size) <= 0):
                raise OriginalTireNormalError(
                    "原本SwatchのBC5/BC7/RGBA8 Normal候補を復号できません: "
                    + ref + " / " + str(meta.get("decode_error", encoding)))
            if encoding == UNCOMPRESSED_NORMAL_ENCODING:
                _require_tangent_normal(image, ref)
            encoded = io.BytesIO()
            # 画素は同じで圧縮の仕方だけを選べる。最小化（optimize=True）は約 5 倍遅く（4212 で 0.61 秒と 0.11 秒）、
            # 小さくなるのは約 6%（1.12 MB と 1.06 MB）。初めての車の準備を速くするため標準の強さにする（2026-11-20）
            image.save(encoded, format="PNG")
            image_map[ref] = {
                "png": encoded.getvalue(),
                "source_sha256": _sha(raw),
                "size": list(image.size),
                "encoding": meta["encoding"],
            }
    return image_map


def _glb(doc, original_bin: bytes) -> bytes:
    binary = bytearray(original_bin)
    binary.extend(b"\0" * (-len(binary) % 4))
    doc["buffers"][0]["byteLength"] = len(binary)
    clean = seal_firstparty_chassis_metadata(json_tree_deepcopy(doc))
    js = json.dumps(clean, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(binary))
            + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)


def _verify_tire_lod0_material_slots(selected: list[tuple], models: dict,
                                     expected_wheels: tuple[str, ...] = WHEELS) -> dict[str,int]:
    """GLBの4輪を元ModelBinの実LOD0 (materialId, name) ごとに完全照合。

    左右のMatI名一致は要求しない。各ModelBin IDは独立namespace。
    各輪の元LOD0材質数は原本どおり保持し、異なる件数も一意署名なら受け入れる。
    """
    from .source_tire_local_runtime import _load_source_meshes
    per_wheel = {wheel: [] for wheel in expected_wheels}
    for row in selected:
        sha, material_id, wheel, role = row[3], row[4], row[5], row[6]
        if wheel not in per_wheel or sha not in models:
            raise OriginalTireNormalError('原本Tireの車輪/ModelBin出典が不正')
        if len(row) < 8 or type(row[7]) is not int:
            raise OriginalTireNormalError('原本Tire MeshBlob出典indexが不足')
        per_wheel[wheel].append((sha, material_id, role, row[7]))
    signed_counts: dict[str,int] = {}
    invalid: dict = {}
    for wheel, rows in per_wheel.items():
        if not rows or len({item[0] for item in rows}) != 1:
            invalid[wheel] = '原本ModelBin混在またはLOD0不足'
            continue
        model_data, _blobs, _matis = models[rows[0][0]]
        native = _load_source_meshes(model_data, 'L' if wheel.endswith('left') else 'R')
        expected = [(row['material_id'], row['material_name'], row['meshblob_index'])
                    for row in native]
        actual = [(id_, name, blob_idx) for _, id_, name, blob_idx in rows]
        if (len(expected) != len(set(expected))
                or len(actual) != len(set(actual))
                or set(expected) != set(actual)):
            invalid[wheel] = {'原本LOD0': sorted(expected), 'GLB出力': sorted(actual)}
        signed_counts[wheel] = len(expected)
    if (invalid or len(signed_counts) != len(expected_wheels)
            or len(selected) != sum(signed_counts.values())):
        raise OriginalTireNormalError(
            '純正Tireの4輪×元LOD0材質署名が一致しません'
            f' / 原本役割数={signed_counts} / 不一致={invalid}')
    return signed_counts


def build_original_tire_normal_glb(source_glb: bytes, model_zip: Path,
                                   materials_zip: Path, shader_library: Path,
                                   textures_zip: Path,
                                   *, source_signed_normal_auto: bool = False) -> tuple[bytes, dict]:
    """署名済み原本4輪×実LOD0材質をGLBへ接続。車体・FEOWは変更しない。"""
    doc, base_bin = read_glb(source_glb)
    before = json_tree_deepcopy(doc)
    model_sha, models = _original_models(model_zip)
    shader_sha, shader_xml = _source_shader_proof(shader_library, return_xml=True)
    material_sha = _source_material_proof(materials_zip)
    if source_signed_normal_auto:
        source_tire_color, source_tire_color_material_sha = source_original_tire_base_color(
            materials_zip, shader_xml)
    else:
        source_tire_color, source_tire_color_material_sha = None, None
    if not isinstance(doc.get("meshes"), list) or not isinstance(doc.get("materials"), list):
        raise OriginalTireNormalError("元GLBメッシュ・Material構造が不足")
    selected = []
    refs = set()
    role_counts = Counter()
    expected_wheels = _expected_tire_wheels(doc)
    for mesh in doc["meshes"]:
        ex = mesh.get("extras", {})
        if ex.get("lo4_part_type") != "Tire":
            continue
        wheel = ex.get("lo4_tire_source_wheel")
        role = ex.get("lo4_tire_original_material_name")
        sha = ex.get("lo4_tire_original_modelbin_sha256")
        material_id = ex.get("lo4_tire_original_material_id")
        if wheel not in expected_wheels or not isinstance(role, str) or not role or sha not in models:
            raise OriginalTireNormalError("TireのRole・ModelBin出典が不一致")
        data, blobs, source_mats = models[sha]
        mati = source_mats.get(material_id)
        if mati is None or mati.name != role or len(mesh.get("primitives", [])) != 1:
            raise OriginalTireNormalError("元MatI ID/RoleまたはTire primitive件数不一致")
        normal_binding = tire_original_normal_variant(
            bytes(mati.data), shader_xml,
            materials_zip=materials_zip, shader_library=shader_library)
        ref = normal_binding['reference']
        refs.add(ref)
        prim = mesh["primitives"][0]
        if "TEXCOORD_0" not in prim.get("attributes", {}):
            raise OriginalTireNormalError("元Tire UV0がありません")
        source_blob, affine = mesh_affines(
            blobs, material_id, prim, doc, base_bin,
            source_meshblob_index=ex.get("lo4_tire_source_meshblob_index"))
        if not all(__import__("math").isfinite(float(v)) for v in affine[0]):
            raise OriginalTireNormalError("原本MeshBlob UV affine非有限値")
        from .source_tire_shader_binding import mati_bindings
        mati_values = mati_bindings(
            bytes(mati.data), shader_xml,
            normal_parameter=normal_binding['original_parameter'],
            require_normal=normal_binding['normal_reference_origin'] == 'modelbin_mati',
        )["bindings"]
        tiling = tire_unique_map_tiling(
            mati_values, role=role, materials_zip=materials_zip,
            material_member=normal_binding.get('material_member'), shader_xml=shader_xml)
        if source_signed_normal_auto:
            base_override = mati_values.get("BaseTyreColourColorParam")
            tire_color = list(source_tire_color)
            if base_override is not None:
                raw_color = base_override.get("value")
                if (base_override.get("type") != 1
                        or not isinstance(raw_color, list) or len(raw_color) != 4
                        or any(not isinstance(v, float) or not math.isfinite(v)
                               or v < 0 or v > 1 for v in raw_color)):
                    raise OriginalTireNormalError("元MatIのBaseTyreColour原本色が不正")
                tire_color = list(raw_color)
        else:
            tire_color = None
        selected.append((mesh, prim, ref, sha, material_id, wheel, role,
                         int(source_blob.index), [float(v) for v in affine[0]],
                         tire_color, tiling, normal_binding))
        role_counts[(wheel, role)] += 1
    # 原本LOD0名は左右で同一とは限らない。ModelBin IDを正本にする。
    signed_counts = _verify_tire_lod0_material_slots(selected, models, expected_wheels)
    if any(row[-1]['source_family'] == 'pg_legacy' for row in selected):
        material_sha = _source_material_proof(materials_zip, include_legacy=True)
    sources = _original_swatch_images(textures_zip, refs)
    doc.setdefault("images", [])
    doc.setdefault("textures", [])
    doc.setdefault("bufferViews", [])
    doc.setdefault("extensionsUsed", [])
    if "KHR_texture_transform" not in doc["extensionsUsed"]:
        doc["extensionsUsed"].append("KHR_texture_transform")
    binary = bytearray(base_bin)
    texture_ids = {}
    for ref, img in sorted(sources.items()):
        binary.extend(b"\0" * (-len(binary) % 4))
        offset = len(binary)
        binary.extend(img["png"])
        bv = len(doc["bufferViews"])
        doc["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(img["png"])})
        index = len(doc["images"])
        doc["images"].append({"bufferView": bv, "mimeType": "image/png",
                              "extras": {"original_swatch_sha256": img["source_sha256"],
                                         "original_texture_reference": ref}})
        texture_ids[ref] = len(doc["textures"])
        doc["textures"].append({"source": index})
    for mesh, prim, ref, source_sha, material_id, wheel, role, blob, affine, tire_color, tiling, normal_binding in selected:
        uoffset, uscale, voffset, vscale = affine
        tile_u, tile_v = tiling["scale"]
        if abs(uscale) < 1e-10 or abs(vscale) < 1e-10 or max(map(abs, affine)) >= 1e6:
            raise OriginalTireNormalError("元Tire UV affine値が特異")
        previous = prim.get("material")
        if not isinstance(previous, int) or not 0 <= previous < len(before["materials"]):
            raise OriginalTireNormalError("原本中立Tire材質が不正")
        mat = copy.deepcopy(before["materials"][previous])
        mat["name"] = "Original Tire MatI " + normal_binding['original_parameter'] + " (source verified)"
        if source_signed_normal_auto:
            # 元Shader/MaterialBinに宣言された線形ベース色をそのままGLTFに接続。
            # PBR最終合成は研究段階。推測の黒色や車種固有RGBへは置換しない。
            mat.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = tire_color
        # MeshBlob affine（原本UV変換）に、原本MatI/MaterialBinのUniqueMapTilingを掛ける。
        # 複合材質の段階では再適用しない（二重適用の防止）。
        mat["normalTexture"] = {
            "index": texture_ids[ref], "texCoord": 0, "scale": 1.0,
            "extensions": {"KHR_texture_transform": {
                "offset": [uoffset, voffset],
                "scale": [uscale * tile_u, vscale * tile_v],
            }},
        }
        mat["extras"] = {
            "lo4fh6_original_tire_normal_research": True,
            "lo4fh6_source_signed_normal_auto": bool(source_signed_normal_auto),
            "source_original_tire_base_color_linear_rgba": tire_color,
            "source_original_tire_base_materialbin_sha256": source_tire_color_material_sha,
            "source_original_mati_id": material_id,
            "source_modelbin_sha256": source_sha,
            "source_swatch_sha256": sources[ref]["source_sha256"],
            "source_shaderbin_sha256": shader_sha,
            "source_materials_sha256": material_sha,
            "original_shader_parameter": normal_binding['original_parameter'],
            "original_shader_variant": normal_binding['shader_variant'],
            "original_material_member": normal_binding['material_member'],
            "normal_reference_origin": normal_binding['normal_reference_origin'],
            "source_parent_materialbin_sha256": normal_binding['source_parent_materialbin_sha256'],
            "source_shaderbin_dfpr_sha256": normal_binding.get('source_shaderbin_dfpr_sha256'),
            "lo4fh6_source_original_tire_normal_expected_mesh_count": len(selected),
            # 4輪別の原本LOD0役割数。前後で構成が異なる原本も固定件数に矯正しない。
            "lo4fh6_source_original_tire_normal_expected_wheel_role_count": signed_counts[wheel],
            "source_native_meshblob_index": blob,
            "source_uv_channel_research": 0,
            "source_uv_affine": affine,
            "source_unique_map_tiling": [tile_u, tile_v],
            "source_unique_map_tiling_origin": tiling["origin"],
            "shader_equivalent": False,
            "xbox_approved": False,
            "product_default_changed": bool(source_signed_normal_auto),
        }
        prim["material"] = len(doc["materials"])
        doc["materials"].append(mat)
    doc["buffers"][0]["byteLength"] = len(binary)
    out = _glb(doc, bytes(binary))
    after, decoded = read_glb(out)
    if bytes(decoded[:len(base_bin)]) != bytes(base_bin):
        raise OriginalTireNormalError("元GLB BINの先頭バイトが変更されました")
    for key in ("nodes", "accessors"):
        if after.get(key) != before.get(key):
            raise OriginalTireNormalError(f"元車体GLB構造を変更しました: {key}")
    for old, new in zip(before["meshes"], after["meshes"]):
        if old.get("extras", {}).get("lo4_part_type") != "Tire" and old != new:
            raise OriginalTireNormalError("タイヤ以外のMesh変更を拒否")
    proof = {
        "schema": SCHEMA, "source_glb_sha256": _sha(source_glb),
        "output_glb_sha256": _sha(out), "source_tire_zip_sha256": model_sha,
        "source_shaderbin_sha256": shader_sha, "source_materials_sha256": material_sha,
        "source_normals": {k: {"sha256": v["source_sha256"], "size": v["size"],
                                "encoding": v["encoding"]} for k, v in sources.items()},
        "four_wheel_tire_materials": len(selected), "normal_role_counts": dict(Counter(row[6] for row in selected)),
        "source_wheel_material_counts": signed_counts,
        "old_bin_prefix_unchanged": True, "other_meshes_unchanged": True,
        "uv_channel": 0, "affine": "native-MeshBlob", "shader_equivalent": False,
        "xbox_approved": False,
        "source_signed_auto_normal": bool(source_signed_normal_auto),
        "source_original_base_tire_materialbin_sha256": source_tire_color_material_sha,
        "source_original_base_tire_linear_rgba": source_tire_color,
        "product_default_changed": bool(source_signed_normal_auto),
    }
    return out, proof


def _original_tire_active_lod0_material_ids(tire_zip: Path, models: dict) -> dict[str, set[int]]:
    """原本4輪の描画用LOD0だけが使うMatI IDを一意に抽出する。

    元ModelBinのMatIにはLODS影用・非表示用も含まれる。未使用MatIの
    Normal欠落で可視LOD0まで拒否せず、実LOD0の全材質を個別に照合する。
    出力はモデルSHA→使用MatI IDで、別名・別形状の代用はしない。
    """
    from .source_tire_local_runtime import (
        _original_tire_model_entries, _load_source_meshes, LocalTireSourceError,
        tire_archive_model_name,
    )
    try:
        source_model = tire_archive_model_name(tire_zip)
    except LocalTireSourceError as exc:
        raise OriginalTireNormalError("Tire原本ZIPの名前が不正") from exc
    active: dict[str, set[int]] = {}
    with zipfile.ZipFile(tire_zip) as archive:
        if archive.testzip() is not None:
            raise OriginalTireNormalError("Tire原本ZIPのCRCが不正")
        try:
            wheel_entries = _original_tire_model_entries(archive, source_model)
        except LocalTireSourceError as exc:
            raise OriginalTireNormalError("Tire原本4輪ModelBinの所属を確定できません") from exc
        if set(wheel_entries) != set(WHEELS):
            raise OriginalTireNormalError("Tire原本4輪ModelBinの一意署名が不足")
        for wheel in WHEELS:
            packet = archive.read(wheel_entries[wheel])
            model_sha = _sha(packet)
            if model_sha not in models or models[model_sha][0] != packet:
                raise OriginalTireNormalError("Tire LOD0の元ModelBin SHA/実バイトが不一致")
            _source_packet, _blobs, matis = models[model_sha]
            side = "L" if wheel.endswith("left") else "R"
            try:
                native = _load_source_meshes(packet, side)
            except (LocalTireSourceError, ValueError, KeyError) as exc:
                raise OriginalTireNormalError(
                    "Tire描画用LOD0の材質参照を復号できません: " + wheel
                ) from exc
            if not native:
                raise OriginalTireNormalError("Tire描画用LOD0が空です: " + wheel)
            used: set[int] = set()
            seen_blobs: set[int] = set()
            for mesh in native:
                mid = mesh.get("material_id")
                name = mesh.get("material_name")
                blob_idx = mesh.get("meshblob_index")
                if (type(mid) is not int or mid < 0
                        or type(blob_idx) is not int or blob_idx in seen_blobs
                        or not isinstance(name, str) or not name.strip()
                        or mid not in matis or matis[mid].name != name):
                    raise OriginalTireNormalError(
                        "Tire描画用LOD0のMatI/原本MeshBlob ID・名前が欠損・重複・不一致: " + wheel
                    )
                seen_blobs.add(blob_idx)
                used.add(mid)
            previous = active.get(model_sha)
            if previous is not None and previous != used:
                raise OriginalTireNormalError(
                    "同一Tire ModelBinの前後LOD0材質出典が矛盾"
                )
            active[model_sha] = used
    if set(active) != set(models):
        raise OriginalTireNormalError("Tire原本LOD0で未使用のModelBinが混在")
    return active


def original_tire_normal_signed_eligible(tire_zip: Path, game_cars_dir: Path) -> bool:
    """原本Tire Normalの署名照合（中身は _original_tire_normal_signed_eligible_uncached）。"""
    # 同じプロセスの中で、同じ原本（タイヤの ZIP と _library の材質・画像・シェーダーの大きさ・更新日時）なら
    # 前の判定を使う（tire_input_memo。ペイントに依らない判定で、窓の使い回し・撮影の係で毎回繰り返していた）。
    from .tire_input_memo import exists, file_identity, library_identity, remembered
    tire = file_identity(tire_zip)
    key = (tire, library_identity(Path(game_cars_dir) / "_library"))
    return remembered("original_tire_normal_signed_eligible", key,
                      lambda: _original_tire_normal_signed_eligible_uncached(tire_zip, game_cars_dir),
                      enabled=exists(tire))

def _original_tire_normal_signed_eligible_uncached(tire_zip: Path, game_cars_dir: Path) -> bool:
    """4輪の描画用LOD0が使うMatIと個別/親Normalだけを原本署名照合する。

    3 MatI固定や全MatI/左右件数固定を使わない。原本ID/名前・SHAを
    ここで照合し、GLB生成時も全LOD0 Primitiveを再照合する。
    """
    _, models = _original_models(tire_zip)
    shader_sha, shader_xml = _source_shader_proof(
        game_cars_dir / "_library", return_xml=True)
    if not re.fullmatch(r"[0-9a-f]{64}", shader_sha):
        raise OriginalTireNormalError("原本Tire Shader SHA不正")
    library = game_cars_dir / "_library" / "Materials.zip"
    _source_material_proof(library)
    # FH6原本の影用LODS/非表示MatIまで可視Normal必須にしない。
    # 実LOD0の全材質ID・名前・ModelBin SHAを4輪ごとに確定する。
    active = _original_tire_active_lod0_material_ids(tire_zip, models)
    legacy_found = False
    for model_sha, (_model, _blobs, matis) in models.items():
        used_ids = active[model_sha]
        for material_id in sorted(used_ids):
            item = matis[material_id]
            binding = tire_original_normal_variant(
                bytes(item.data), shader_xml, materials_zip=library,
                shader_library=game_cars_dir / "_library")
            if binding['source_family'] == 'pg_legacy':
                legacy_found = True
    if legacy_found:
        _source_material_proof(library, include_legacy=True)
    # 最終GLB生成段でも原本4輪LOD0と全Primitiveを再照合する。
    return True


# 標準Tireキャッシュのレポート形式の版。
# レポートの必須項目を増やした場合はこの値を上げ、旧版のキャッシュを
# 拒否して停止するのではなく、別の保存先へ作り直す。
# 旧版のフォルダーは削除せず保全する（過去の撮影の証拠として残す）。
# r2: source_signed_auto_compound=False を必須化（2026-11-17）。
# r3: 利用者が Windows 実機で受け入れた原本 Extra/Blur 複合の標準統合を復元し、
#     複合の有無をレポートとキャッシュ照合へ記録（2026-11-17）。
# r4: 側面文字あり（TextSwitch=1、FEOW等）のTireでも、トレッドと刻印の2役割へ
#     複合を適用（文字の側面MatIはNormalのみ）（2026-11-17）。
# r5: UniqueMapTilingをNormal段階で原本MatI→親MaterialBinの順に解決（2026-11-17）。
STANDARD_TIRE_NORMAL_CACHE_REVISION = 6
# 入力 → 標準Tireの保存先の索引（保存先の名前は出来上がりの SHA なので、索引が無いと毎回作り直して探すしかない）。
# 作り方を変えたときは、上の版を上げる（索引の鍵にも版が入る）。
STANDARD_TIRE_INPUT_INDEX_DIR = "Original-Tire-Source-Signed-Standard-Index"
_LOCAL_TIRE_GLB_NAME = re.compile(r"original-tire-([0-9a-f]{24})\.glb")


def _file_identity(path: Path) -> list:
    # 無いファイルは「無い」として鍵に入れる（本当に無ければ、組み立ての段で従来どおり止まる）。
    try:
        stat = path.stat()
    except OSError:
        return [path.name, None, None]
    return [path.name, stat.st_size, stat.st_mtime_ns]


def _listed_file_identities(folder: Path) -> list:
    """フォルダーの直下のファイルの [名前, 大きさ, 更新日時] を並べたもの（sorted(_file_identity(p) for p in
    folder.iterdir() if p.is_file()) と同じ値）。フォルダーの一覧（os.scandir）から得るので、Windows ではファイルごとに
    問い合わせない（以前は 1 つにつき is_file と stat の 2 回。2026-11-20）。"""
    rows = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.is_file():
                stat = entry.stat()
                rows.append([entry.name, stat.st_size, stat.st_mtime_ns])
    return sorted(rows)


def standard_tire_input_key(source_glb: Path, tire_zip: Path, game_cars_dir: Path) -> str:
    """標準Tireを作る入力の鍵。元の車体＋原本タイヤの GLB は、その保存名の鍵（入力から決まる）を使う。

    保存名の形でない GLB は中身の SHA。タイヤの原本 ZIP・材質・画像・シェーダーは大きさと更新時刻。
    """
    library = game_cars_dir / "_library"
    match = _LOCAL_TIRE_GLB_NAME.fullmatch(source_glb.name)
    source = ["local-tire-key", match.group(1)] if match else ["sha256", _sha(source_glb.read_bytes())]
    shaders = library / "shaders"
    inputs = {
        "source": source,
        "tire_zip": _file_identity(tire_zip),
        "materials": _file_identity(library / "Materials.zip"),
        "textures": _file_identity(library / "Textures.zip") if (library / "Textures.zip").is_file() else None,
        "shader_files": _listed_file_identities(shaders) if shaders.is_dir() else [],
        "shaders_zip": _file_identity(library / "shaders.zip") if (library / "shaders.zip").is_file() else None,
        "revision": STANDARD_TIRE_NORMAL_CACHE_REVISION,
    }
    return _sha(json.dumps(inputs, sort_keys=True).encode("utf-8"))[:32]


# 照合済みの標準Tire（パス・大きさ・更新時刻）。同じプロセスで同じファイルを何度も照合しない
# （準備の係は同じ車のペイントを続けて準備する）。ファイルが変われば大きさか時刻が変わるので照合し直す。
_VERIFIED_STANDARD_TIRES: set[tuple[str, int, int]] = set()


def _standard_tire_store(folder: Path) -> Path:
    """差分から組み立てた標準Tireの置き場（wheel-tire/Materialized-GLB。最近使った数個だけ残す）。"""
    from .glb_delta import MATERIALIZED_DIR
    return folder.parent.parent / MATERIALIZED_DIR


def _materialized_standard_tire(folder: Path, delta_base: Path | None) -> Path | None:
    """差分（source-signed-tire.glbdelta）で保存した標準Tireを、土台から組み立てて置き場に置き、場所を返す。

    差分が無い・土台が分からないときは None。土台が作り直されて違うときも None（作り直す）。
    差分が証拠と食い違うときは停止（旧版へ後退しない）。
    """
    from .glb_delta import GlbDeltaBaseMismatch, GlbDeltaError, materialize
    delta = folder / "source-signed-tire.glbdelta"
    report = folder / "source-signed-tire.json"
    if not delta.is_file() or not report.is_file() or delta_base is None:
        return None
    old = json.loads(report.read_text(encoding="utf-8"))
    if old.get("standard_tire_cache_revision") != STANDARD_TIRE_NORMAL_CACHE_REVISION:
        raise OriginalTireNormalError("標準Tireキャッシュ署名が不一致。旧版へ後退しません")
    try:
        return materialize(delta, delta_base, _standard_tire_store(folder), str(old.get("output_glb_sha256") or ""))
    except GlbDeltaBaseMismatch:
        return None
    except (GlbDeltaError, OSError, ValueError) as exc:
        raise OriginalTireNormalError("標準Tireキャッシュの差分が証拠と不一致。旧版へ後退しません: " + str(exc)) from exc


def _verified_standard_tire_folder(folder: Path, delta_base: Path | None = None) -> Path | None:
    """保存済みの標準Tireを、出来上がりの SHA と証拠の版で照合して返す。無ければ None、不一致は停止。

    差分で保存してあれば、土台（delta_base、車体の形の GLB）から組み立てた GLB の場所を返す。
    """
    result = folder / "source-signed-tire.glb"
    report = folder / "source-signed-tire.json"
    if not result.is_file() or not report.is_file():
        return _materialized_standard_tire(folder, delta_base)
    stat = result.stat()
    identity = (str(result.resolve()), stat.st_size, stat.st_mtime_ns)
    if identity in _VERIFIED_STANDARD_TIRES:
        return result
    old = json.loads(report.read_text(encoding="utf-8"))
    if (old.get("standard_tire_cache_revision") != STANDARD_TIRE_NORMAL_CACHE_REVISION
            or _sha(result.read_bytes()) != old.get("output_glb_sha256")):
        raise OriginalTireNormalError("標準Tireキャッシュ署名が不一致。旧版へ後退しません")
    _VERIFIED_STANDARD_TIRES.add(identity)
    return result


def lookup_standard_tire(source_glb: Path, tire_zip: Path, game_cars_dir: Path, output_dir: Path) -> Path | None:
    """同じ入力で作った標準Tireを索引から引く。当たれば照合済みの保存先、無ければ None。

    元の車体＋原本タイヤの GLB は名前（入力の鍵）だけを使い、中身は読まない（その GLB が無くてもよい）。
    """
    input_key = standard_tire_input_key(source_glb, tire_zip, game_cars_dir)
    index = output_dir / STANDARD_TIRE_INPUT_INDEX_DIR / f"{input_key}.json"
    if not index.is_file():
        return None
    entry = json.loads(index.read_text(encoding="utf-8"))
    folder_name = str(entry.get("folder") or "")
    if not re.fullmatch(r"r\d+-[0-9a-f]{64}", folder_name):
        return None
    from .glb_delta import delta_base_for
    return _verified_standard_tire_folder(output_dir / "Original-Tire-Source-Signed-Standard" / folder_name,
                                          delta_base_for(source_glb.name))


def cached_original_tire_normal_glb(source_glb: Path, tire_zip: Path,
                                     game_cars_dir: Path, output_dir: Path) -> Path:
    """標準Tire材質を原本署名から必ず自動構築。外部ON/OFF引数や環境変数は設けない。

    FEOWは呼出元で合成。Normalと原本Extra/Blurを適用できるかは
    ModelBin/MatI/ShaderBin/LOD0の出典で決める。旧研究GLBには後退しない。

    原本Extra/Blurの複合は、2026-11-16 に利用者がWindows実機で
    Vivio3960のタイヤを「仮物ではなくテクスチャもOK」と受け入れた表示
    （HEAD 2bef683）の標準経路。AO/粗さへの割当がFH6 Shader全式と同値とは
    主張しない（Xbox外観の承認は別判定）。

    キャッシュは版付きの保存先に置く。旧版のレポート形式で作られた
    キャッシュは読まずに新しい版の保存先へ作り直す。同じ版の保存先で
    証拠が改ざん・不一致の場合は、従来どおり明示停止する。
    """
    from .source_tire_composite import (
        original_tire_compound_signed_eligible,
        build_original_tire_compound_research,
    )
    from .source_tire_glb_bridge import read_glb
    library = game_cars_dir / "_library"
    # 同じ入力で作った標準Tireがあれば、作り直さずに返す（出来上がりの SHA と証拠の版は照合する）。
    # 索引は、適合の判定と組み立てが通ったときにだけ書く。
    cached = lookup_standard_tire(source_glb, tire_zip, game_cars_dir, output_dir)
    if cached is not None:
        return cached
    input_key = standard_tire_input_key(source_glb, tire_zip, game_cars_dir)
    index = output_dir / STANDARD_TIRE_INPUT_INDEX_DIR / f"{input_key}.json"
    result, folder = _build_cached_original_tire_normal_glb(source_glb, tire_zip, game_cars_dir, output_dir,
                                                    library, read_glb, original_tire_compound_signed_eligible,
                                                    build_original_tire_compound_research)
    index.parent.mkdir(parents=True, exist_ok=True)
    partial = index.with_name(index.name + ".partial")
    # 索引には保存先のフォルダー（r<版>-<署名>）を書く（差分で保存したときの result は組み立てた GLB の置き場）。
    partial.write_text(json.dumps({"folder": folder.name, "input_key": input_key}, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    partial.replace(index)
    return result


def _build_cached_original_tire_normal_glb(source_glb: Path, tire_zip: Path, game_cars_dir: Path, output_dir: Path,
                                          library: Path, read_glb, original_tire_compound_signed_eligible,
                                          build_original_tire_compound_research) -> tuple[Path, Path]:
    """標準Tireを組み立て、出来上がりの SHA の保存先に置く（従来の cached_original_tire_normal_glb の本体）。"""
    if not original_tire_normal_signed_eligible(tire_zip, game_cars_dir):
        raise OriginalTireNormalError("標準TireのLOD0/Normal原本署名が不適合。旧材質へ後退しません")
    compound_signed = bool(original_tire_compound_signed_eligible(tire_zip, library))
    original = source_glb.read_bytes()
    source_hash = _sha(original)
    data, proof = build_original_tire_normal_glb(
        original, tire_zip,
        library / "Materials.zip", library, library / "Textures.zip",
        source_signed_normal_auto=True,
    )
    proof["source_integrated_compound_standard"] = compound_signed
    proof["source_signed_auto_compound"] = compound_signed
    if compound_signed:
        # 既存Windows受入の複合テクスチャを、新LOD0・Normal・原本色の後段へ統合。
        # AO/粗さへの割当は原本FH6 Shader全式と同値と主張しない。
        data, compound = build_original_tire_compound_research(
            data, tire_zip,
            library / "Materials.zip", library, library / "Textures.zip",
        )
        proof["original_normal_glb_sha256_before_compound"] = proof["output_glb_sha256"]
        proof["output_glb_sha256"] = _sha(data)
        proof["compound_rgba_research"] = {
            "schema": compound["schema"],
            "native_rgba_image_count": compound["native_rgba_image_count"],
            "four_wheel_roles": compound["four_wheel_roles"],
            "original_text_switches": compound["original_text_switches"],
            "game_shader_equivalent": False,
            "xbox_approved": False,
            "windows_user_accepted_at_head": "2bef683fb4786afbac7fdefa45f4d6028bb0da10",
        }
        merged, _ = read_glb(data)
        merged_mats = [
            mat for mat in merged.get("materials", [])
            if mat.get("extras", {}).get("lo4fh6_tire_source_rgba_compound_research") is True
        ]
        source_color = proof.get("source_original_base_tire_linear_rgba")
        # 側面文字あり（TextSwitch=1）の側面MatIは複合の対象外（Normalのみ）。
        text_sidewalls = int(compound["four_wheel_roles"].get("sidewall_text_normal_only", 0))
        if (len(merged_mats) + text_sidewalls != proof.get("four_wheel_tire_materials")
                or not isinstance(source_color, list) or len(source_color) != 4):
            raise OriginalTireNormalError("統合Tire材質のLOD0数またはBaseTyreColourが不一致")
        for mat in merged_mats:
            meta = mat.get("extras", {})
            pbr = mat.get("pbrMetallicRoughness", {})
            if (meta.get("lo4fh6_original_tire_normal_research") is not True
                    or meta.get("lo4fh6_source_signed_normal_auto") is not True
                    or pbr.get("baseColorFactor") != source_color
                    or not mat.get("normalTexture")
                    or not mat.get("occlusionTexture")
                    or not pbr.get("metallicRoughnessTexture")
                    or not all(meta.get(key) for key in (
                        "source_extra_swatch_sha256",
                        "source_blur_extra_swatch_sha256",
                        "source_blur_normal_swatch_sha256"))):
                raise OriginalTireNormalError("統合Tire材質にNormal/Extra/Blur/元色が保持されていません")
        proof["integrated_source_materials_verified"] = len(merged_mats)
    proof["standard_tire_cache_revision"] = STANDARD_TIRE_NORMAL_CACHE_REVISION
    signature = _sha((source_hash + proof["output_glb_sha256"]).encode("ascii"))
    folder = (output_dir / "Original-Tire-Source-Signed-Standard"
              / f"r{STANDARD_TIRE_NORMAL_CACHE_REVISION}-{signature}")
    result = folder / "source-signed-tire.glb"
    delta = folder / "source-signed-tire.glbdelta"
    report = folder / "source-signed-tire.json"
    # 差分の土台（元の車体の形の GLB）。分かれば、車体と同じ中身を持たずに差分だけを保存する（1 台 約 60 MB →
    # 約 2 MB。組み立てた GLB は元と 1 バイトも違わない。2026-11-20）。分からなければ従来どおり丸ごと保存する。
    from .glb_delta import delta_base_for, place_materialized, write_delta_file
    delta_base = delta_base_for(source_glb.name)
    if folder.exists():
        if not report.is_file() or not (result.is_file() or delta.is_file()):
            raise OriginalTireNormalError("標準Tireキャッシュ署名が不一致。旧版へ後退しません")
        if result.is_file() and _sha(result.read_bytes()) != proof["output_glb_sha256"]:
            raise OriginalTireNormalError("標準Tireキャッシュ署名が不一致。旧版へ後退しません")
        old = json.loads(report.read_text(encoding="utf-8"))
        if (old.get("source_glb_sha256") != proof["source_glb_sha256"]
                or old.get("output_glb_sha256") != proof["output_glb_sha256"]
                or old.get("standard_tire_cache_revision") != STANDARD_TIRE_NORMAL_CACHE_REVISION
                or old.get("source_integrated_compound_standard") is not compound_signed
                or old.get("source_signed_auto_compound") is not compound_signed):
            raise OriginalTireNormalError("標準Tireキャッシュ証拠が不一致")
        if result.is_file():
            return result, folder
        if delta_base is not None:
            # 土台が作り直されていれば、今の土台で差分を作り直す（出来上がりの中身は同じ）。
            materialized = _materialized_standard_tire(folder, delta_base)
            if materialized is not None:
                return materialized, folder
            write_delta_file(delta, data, delta_base.read_bytes())
            return place_materialized(_standard_tire_store(folder), data, proof["output_glb_sha256"], delta_base), folder
        result.write_bytes(data)
        return result, folder
    folder.mkdir(parents=True, exist_ok=False)
    if delta_base is not None:
        manifest = write_delta_file(delta, data, delta_base.read_bytes())
        proof["stored_as_glb_delta"] = True
        proof["glb_delta_base_sha256"] = manifest["base_sha256"]
        report.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return place_materialized(_standard_tire_store(folder), data, proof["output_glb_sha256"], delta_base), folder
    result.write_bytes(data)
    report.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, folder
