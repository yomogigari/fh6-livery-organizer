# -*- coding: utf-8 -*-
"""FH6 Tire MatI のShaderパラメータIDと元Texture2D参照を照合する第一者研究モジュール。

参照製品のパラメータ型区分、参照製品の参照追跡、参照製品の原本抽出を
参照し、原本MatI/Shader XMLの実データを独立復号する。第三者コードを移植しない。
RGBAチャンネル意味論・合成式・Xbox外観を勝手に確定しない。
"""
from __future__ import annotations

import hashlib
import struct
import xml.etree.ElementTree as ET
import zlib

from . import wheel_morph_internal as wm

MAX_PARAMETER_BLOB = 1024 * 1024
MAX_PARAMETER_COUNT = 256
TIRE_TEXTURE_PARAMETER = 'UniqueNorm_Tires_PGTexture'
TIRE_LEGACY_NORMAL_PARAMETER = 'LegacyNormal_Tires_PG_LegacyTexture'


class TireBindingError(ValueError):
    """曖昧なID・未解析パラメータ・別scopeファイルを拒否する。"""

class TireUniqueNormMissingError(TireBindingError):
    """整形式の元MatIがUniqueNormを持たない。署名適用可否では非適合として扱う。"""


def _take(raw: bytes, offset: int, length: int) -> tuple[bytes, int]:
    if offset < 0 or length < 0 or offset + length > len(raw):
        raise TireBindingError('MatIパラメータが途中で切れています')
    return raw[offset:offset + length], offset + length


def _length7(raw: bytes, offset: int) -> tuple[int, int]:
    number = 0
    for i in range(5):
        chunk, offset = _take(raw, offset, 1)
        number |= (chunk[0] & 127) << (7 * i)
        if chunk[0] < 128:
            return number, offset
    raise TireBindingError('MatI 7bit文字列長が不正')


def shader_xml_ids(xml: bytes) -> dict[int, tuple[str, int]]:
    """XMLに明記されたパラメータ名だけをCRC32で識別する。衝突は拒否。"""
    root = ET.fromstring(xml)
    if not root.findall('./Variants/ExportVariant'):
        raise TireBindingError('Tire Shader ExportVariant宣言がありません')
    mapping: dict[int, tuple[str, int]] = {}
    for tag, expected_type in (('Texture', 6), ('Parameter', -1)):
        for elem in root.findall(f'./{"Textures" if tag == "Texture" else "Parameters"}/{tag}'):
            name = elem.get('parametername') or ''
            if not name.isascii() or not name or len(name) > 160:
                raise TireBindingError('Shaderパラメータ名が不正')
            key = zlib.crc32(name.encode('ascii'))
            if key in mapping:
                raise TireBindingError('Shader CRC32の重複・衝突')
            mapping[key] = (name, expected_type)
    if zlib.crc32(TIRE_TEXTURE_PARAMETER.encode()) not in mapping:
        raise TireBindingError('UniqueNorm Shader宣言がありません')
    return mapping


def _read_parameters(raw: bytes) -> list[dict]:
    """参照ツール v1–v4パラメータを境界付きで読み取る。型6のみTexture2D。"""
    if not 1 <= len(raw) <= MAX_PARAMETER_BLOB:
        raise TireBindingError('MatI MTPR サイズが不正')
    count = raw[0]
    if count > MAX_PARAMETER_COUNT:
        raise TireBindingError('MatI MTPR件数が異常')
    pos = 1
    rows = []
    seen = set()
    for _ in range(count):
        start = pos
        header, pos = _take(raw, pos, 6)
        major, minor, key = header[0], header[1], struct.unpack_from('<I', header, 2)[0]
        if not 1 <= major <= 4 or key in seen:
            raise TireBindingError('MatI versionまたはパラメータIDが不正・重複')
        seen.add(key)
        if major > 3 or major == 3 and minor >= 1:
            present, pos = _take(raw, pos, 1)
            if present[0]:
                _, pos = _take(raw, pos, 4)
        type_byte, pos = _take(raw, pos, 1)
        typ = type_byte[0]
        if major >= 3:
            _, pos = _take(raw, pos, 16)
        value = None
        if typ in (0, 1, 5, 9):
            chunk, pos = _take(raw, pos, 16)
            value = list(struct.unpack('<4f', chunk))
        elif typ in (2, 3, 4):
            chunk, pos = _take(raw, pos, 4)
            value = (struct.unpack('<f', chunk)[0] if typ == 2 else struct.unpack('<i', chunk)[0])
        elif typ == 6:
            length, pos = _length7(raw, pos)
            if length < 15 or length > 1024:
                raise TireBindingError('Texture2D参照名長が異常')
            chunk, pos = _take(raw, pos, length)
            try:
                ref = chunk.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise TireBindingError('Texture2D参照がUTF-8でありません') from exc
            if not ref.casefold().startswith('game:\\media\\cars\\_library\\textures\\') or not ref.casefold().endswith('.swatchbin'):
                raise TireBindingError('原本Textures.zip scope外の参照')
            if any(x in ref for x in ('..', '/', '\x00')):
                raise TireBindingError('Texture2D参照に不正なパス')
            if major >= 2:
                checksum, pos = _take(raw, pos, 4)
                stored = struct.unpack('<I', checksum)[0]
                if stored != zlib.crc32(ref.casefold().encode('utf-8')):
                    raise TireBindingError('Texture2D参照パスCRC32不一致')
            value = ref
        elif typ == 7:
            chunk, pos = _take(raw, pos, 8)
            value = list(struct.unpack('<ii', chunk))
            if major > 1 or (major == 1 and minor >= 1):
                _, pos = _take(raw, pos, 4)
        elif typ == 11:
            chunk, pos = _take(raw, pos, 8)
            value = list(struct.unpack('<ff', chunk))
            if major == 1:
                _, pos = _take(raw, pos, 8)
        elif typ == 8:
            chunk, pos = _take(raw, pos, 4)
            entries = struct.unpack('<I', chunk)[0]
            if entries > 256:
                raise TireBindingError('Shader Gradient要素が異常')
            _, pos = _take(raw, pos, entries * 16)
            value = {'gradient_entries': entries}
        else:
            raise TireBindingError('未知のShaderパラメータ型: ' + str(typ))
        rows.append({'parameter_crc32': f'{key:08x}', 'type': typ, 'value': value,
                     'bytes': pos - start})
    if len(raw) - pos > 32:
        raise TireBindingError('MatI MTPRの追加メタデータが想定範囲を超えます')
    # MTPR末尾の元メタデータは解釈せず保全・合成には使わない。
    return rows


def mati_bindings(mati_bytes: bytes, shader_xml: bytes, *,
                  normal_parameter: str = TIRE_TEXTURE_PARAMETER,
                  require_normal: bool = True) -> dict:
    """ModelBinに格納された一つの元MatIについて、名前とID・値を原本一致で確定する。"""
    if not mati_bytes.startswith(b'burG') or len(mati_bytes) > MAX_PARAMETER_BLOB:
        raise TireBindingError('原本MatI bundle形式ではありません')
    source = wm._parse_blobs(mati_bytes)
    blocks = [bytes(entry.data) for entry in source if entry.tag == 0x4d545052]
    if len(blocks) != 1:
        raise TireBindingError('MatIのMTPRブロックが一意でありません')
    ids = shader_xml_ids(shader_xml)
    records = _read_parameters(blocks[0])
    values = {}
    for row in records:
        key = int(row['parameter_crc32'], 16)
        if key not in ids:
            raise TireBindingError('MatIパラメータIDがShader XMLにありません: ' + row['parameter_crc32'])
        name, typ = ids[key]
        if typ != -1 and typ != row['type']:
            raise TireBindingError('Shader Texture2D宣言と実型が一致しません: ' + name)
        values[name] = {'type': row['type'], 'value': row['value'],
                        'parameter_crc32': row['parameter_crc32']}
    if normal_parameter not in (TIRE_TEXTURE_PARAMETER, TIRE_LEGACY_NORMAL_PARAMETER):
        raise TireBindingError('Tire NormalのShaderパラメータが未承認')
    # 親MaterialBinの原本MTPRがNormalを供給することを別途SHA検証した
    # 場合だけ、個別MatIの非Normal overrideの抽出を許す。既定は厳密拒否。
    if require_normal and normal_parameter not in values:
        raise TireUniqueNormMissingError('Tire '+normal_parameter+'入力が未設定')
    return {'parameter_count': len(records), 'bindings': values,
            'source_mati_sha256': hashlib.sha256(mati_bytes).hexdigest(),
            'shader_equation_verified': False, 'xbox_approved': False}


def normal_reference(mati_bytes: bytes, shader_xml: bytes, *,
                     normal_parameter: str = TIRE_TEXTURE_PARAMETER) -> str:
    """ファイル名のnrml文字列ではなくShader UniqueNormのCRC32パラメータから厳密取得。"""
    proof = mati_bindings(mati_bytes, shader_xml, normal_parameter=normal_parameter)
    entry = proof['bindings'][normal_parameter]
    if entry['type'] != 6:
        raise TireBindingError('UniqueNormはTexture2Dではありません')
    return entry['value']


def _shader_dfpr_defaults(shader_data: bytes, shader_xml: bytes,
                          wanted: set[int]) -> tuple[dict[int, str], dict[int, tuple[int, object]]]:
    """FH6元ShaderBinのPARM（1.2）とDFPR（2.1）を全件復号して照合する。

    PARMの完全名ハッシュ→表示名と、指定したハッシュの(型, 既定値)を返す。
    型・CRC・版・重複・未宣言・末尾の余りはすべて拒否する。
    """
    source_ids = shader_xml_ids(shader_xml)
    if not isinstance(shader_data, bytes) or not 0 < len(shader_data) <= MAX_PARAMETER_BLOB:
        raise TireBindingError('元Tire ShaderBinが不正サイズ')
    try:
        blobs = wm._parse_blobs(shader_data)
    except Exception as exc:
        raise TireBindingError('元Tire ShaderBinの原本Bundleを解釈できません') from exc
    def original(tag: str, version: tuple[int, int]) -> bytes:
        members = [b for b in blobs if b.tag == int.from_bytes(tag.encode('ascii'), 'big')]
        if len(members) != 1 or (members[0].major, members[0].minor) != version:
            raise TireBindingError('元Tire ShaderBin ' + tag + 'の件数/版が不一致')
        return bytes(members[0].data)
    parm = original('PARM', (1, 2))
    dfpr = original('DFPR', (2, 1))
    head, pos = _take(parm, 0, 4)
    count = struct.unpack('<I', head)[0]
    if not 0 < count <= MAX_PARAMETER_COUNT:
        raise TireBindingError('元Shader PARM件数が不正')
    ids = {}
    for _ in range(count):
        key_bytes, pos = _take(parm, pos, 4)
        name_crc = struct.unpack('<I', key_bytes)[0]
        name_length, pos = _length7(parm, pos)
        if not 0 < name_length <= 160:
            raise TireBindingError('元Shader PARM名長が不正')
        name_bytes, pos = _take(parm, pos, name_length)
        try:
            name = name_bytes.decode('ascii')
        except UnicodeDecodeError as exc:
            raise TireBindingError('元Shader PARM名がASCIIでありません') from exc
        key_bytes, pos = _take(parm, pos, 4)
        parameter_crc = struct.unpack('<I', key_bytes)[0]
        extra, pos = _take(parm, pos, 1)
        _, pos = _take(parm, pos, extra[0])
        # PARMの名前は短い表示名で、実原本でも重複する（car_tires_pgでは
        # 'path'が側面文字Texture 2件、'ParallaxStrength'がPG/Legacyの2件）。
        # パラメーターを一意に識別するのは完全名のハッシュなので、重複は
        # ハッシュで拒否し、表示名の重複は許す。
        if (zlib.crc32(name_bytes) != name_crc
                or parameter_crc in ids or (parameter_crc not in source_ids
                and not name.startswith('SamplerStates'))):
            raise TireBindingError('元Shader PARM名/CRC/重複が不一致')
        ids[parameter_crc] = name
    if pos != len(parm):
        raise TireBindingError('元Shader PARMの末尾に未解釈のバイトがあります')
    count_bytes, pos = _take(dfpr, 0, 2)
    defaults = struct.unpack('<H', count_bytes)[0]
    if defaults != count:
        raise TireBindingError('元Shader DFPRとPARMの宣言件数が不一致')
    found = set()
    values: dict[int, tuple[int, object]] = {}
    for _ in range(defaults):
        version, pos = _take(dfpr, pos, 2)
        if version[0] != 3 or version[1] not in (1, 3, 4):
            raise TireBindingError('元Shader DFPRパラメータ版が不正')
        key_bytes, pos = _take(dfpr, pos, 4)
        parameter_crc = struct.unpack('<I', key_bytes)[0]
        has_extra, pos = _take(dfpr, pos, 1)
        if has_extra[0] not in (0, 1):
            raise TireBindingError('元Shader DFPRメタフラグが不正')
        if has_extra[0]:
            _, pos = _take(dfpr, pos, 4)
        kind_bytes, pos = _take(dfpr, pos, 1)
        kind = kind_bytes[0]
        _, pos = _take(dfpr, pos, 16)
        value = None
        if kind in (0, 1, 5, 7, 12):
            _, pos = _take(dfpr, pos, 16)
        elif kind in (2, 3, 4):
            raw4, pos = _take(dfpr, pos, 4)
            value = (struct.unpack('<f', raw4)[0] if kind == 2
                     else struct.unpack('<i', raw4)[0])
        elif kind == 11:
            raw8, pos = _take(dfpr, pos, 8)
            value = struct.unpack('<2f', raw8)
        elif kind == 8:
            entries_bytes, pos = _take(dfpr, pos, 4)
            entries = struct.unpack('<I', entries_bytes)[0]
            if entries > 1024:
                raise TireBindingError('元Shader DFPR Gradient件数が不正')
            _, pos = _take(dfpr, pos, 4 * entries)
        elif kind == 6:
            value_length, pos = _length7(dfpr, pos)
            if value_length > 1024:
                raise TireBindingError('元Shader DFPR Texture2D参照長が異常')
            raw_reference, pos = _take(dfpr, pos, value_length)
            stored_crc, pos = _take(dfpr, pos, 4)
            try:
                value = raw_reference.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise TireBindingError('元Shader DFPR Texture2D参照がUTF-8でありません') from exc
            if struct.unpack('<I', stored_crc)[0] != zlib.crc32(value.casefold().encode('utf-8')):
                raise TireBindingError('元Shader DFPR Texture2D参照CRC不一致')
        else:
            raise TireBindingError('元Shader DFPR未対応パラメータ型: ' + str(kind))
        if parameter_crc not in ids or parameter_crc in found:
            raise TireBindingError('元Shader DFPRのIDが未宣言または重複')
        # FH6 car_tires_pg原本PARMにはXML未宣言のSamplerStates項目2件。
        # Texture2Dや色を隠すための例外にはせず、実DFPR型7だけを受理する。
        if parameter_crc not in source_ids and kind != 7:
            raise TireBindingError('元Shader XML未宣言PARMの実型がSamplerでありません')
        found.add(parameter_crc)
        found.add(parameter_crc)
        if parameter_crc in wanted:
            values[parameter_crc] = (kind, value)
    if pos != len(dfpr) or found != set(ids):
        raise TireBindingError('元Shader DFPRの全件の署名が未完了')
    return ids, values


def shader_dfpr_normal_default_reference(shader_data: bytes, shader_xml: bytes, *,
                                         normal_parameter: str = TIRE_TEXTURE_PARAMETER) -> str:
    """FH6元ShaderBinのPARM名→CRC→DFPR型6既定値を完全照合する。

    MatI/親MaterialBinのNormalが実際に欠損するときだけ呼び、原本Shaderの
    Default Parameterを使用する。文字列/Swatchを推測しない。
    原本PARM（1.2）とDFPR（2.1）を別々に全件復号し、型・CRC・版・重複を拒否。
    """
    names = {
        TIRE_TEXTURE_PARAMETER: 'UniqueNorm',
        TIRE_LEGACY_NORMAL_PARAMETER: 'LegacyNormal',
    }
    if normal_parameter not in names:
        raise TireBindingError('元Shader Normalのパラメータが不明')
    source_ids = shader_xml_ids(shader_xml)
    target_crc = zlib.crc32(normal_parameter.encode('ascii'))
    if source_ids.get(target_crc) != (normal_parameter, 6):
        raise TireBindingError('元Tire Shader XMLのNormal CRC/Texture2Dが不一致')
    ids, values = _shader_dfpr_defaults(shader_data, shader_xml, {target_crc})
    if ids.get(target_crc) != names[normal_parameter]:
        raise TireBindingError('元Shader PARM→Normal XML名の署名が不一致')
    kind, value = values.get(target_crc, (None, None))
    if kind != 6 or not isinstance(value, str) or not value:
        raise TireBindingError('元Shader DFPR Normalの既定Texture2Dが欠損')
    if (not value.casefold().startswith('game:\\media\\cars\\_library\\textures\\')
            or not value.casefold().endswith('.swatchbin')
            or '..' in value or '/' in value or chr(0) in value):
        raise TireBindingError('元Shader DFPR Normalの参照が原本Textures範囲外')
    return value


def shader_dfpr_scalar_default(shader_data: bytes, shader_xml: bytes,
                               parameter: str, kind: int) -> object:
    """原本ShaderBin DFPRのFloat(2)/Bool(3)/Int(4)/Vector2(11)既定値を返す。

    MatIと親MaterialBinに値が無いときの最後の継承先（MatI→MaterialBin→DFPR）。
    XMLの完全名とDFPRの型が一致しなければ停止する。
    """
    if kind not in (2, 3, 4, 11):
        raise TireBindingError('元Shader DFPRのスカラー型が未対応: ' + str(kind))
    source_ids = shader_xml_ids(shader_xml)
    target_crc = zlib.crc32(parameter.encode('ascii'))
    if source_ids.get(target_crc, (None,))[0] != parameter:
        raise TireBindingError('元Tire Shader XMLに対象パラメーターがありません: ' + parameter)
    _, values = _shader_dfpr_defaults(shader_data, shader_xml, {target_crc})
    found_kind, value = values.get(target_crc, (None, None))
    if found_kind != kind or value is None:
        raise TireBindingError('元Shader DFPRの既定値の型が不一致: ' + parameter)
    return value
