#!/usr/bin/env python3
"""FH6原本タイヤの参照テクスチャを、原本Shader/MaterialBinから安全に解決する。

第一者の既存 material_runtime / fh6_swatch を再利用し、描画用の模造データは生成しない。
未所有のTextures.zipは不在を明示し、未確認のShader Textureスロットを推定しない。
ゲーム原本バイト/本人データをGitHubへ含めず、出力は匿名の参照証拠のみとする。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import zipfile
import xml.etree.ElementTree as ET

from tools.livery.material_runtime import (
    _game_refs_from_material, shader_texture_defaults,
    _normalized_game_relative, _texture_role_candidate,
)
from tools.livery.fh6_swatch import read_swatch_surface


class SourceVerificationError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_index(archive: zipfile.ZipFile) -> dict[str, str]:
    result = {}
    for info in archive.infolist():
        name = info.filename
        parts = pathlib.PurePosixPath(name).parts
        if (not parts or name.startswith('/') or '\\' in name
                or any(part in ('', '.', '..') for part in parts)
                or (info.external_attr >> 16) & 0o170000 == 0o120000):
            raise SourceVerificationError('ZIPに不正なパス・リンクが含まれています')
        low = name.casefold()
        if low in result:
            raise SourceVerificationError('ZIPの大小文字同一・重複entryを拒否')
        result[low] = name
    if archive.testzip() is not None:
        raise SourceVerificationError('ZIP CRCの不一致')
    return result


def _texture_member(ref: str) -> str:
    prefix = 'media/cars/_library/textures/'
    path = _normalized_game_relative(ref)
    if not path.casefold().startswith(prefix):
        raise SourceVerificationError('cars/_library以外のTexture参照は拒否')
    member = path[len(prefix):]
    parts = pathlib.PurePosixPath(member).parts
    if not parts or any(x in ('', '.', '..') for x in parts) or '\\' in member:
        raise SourceVerificationError('不正なTextureメンバーパス')
    return member


def inspect(*, cars_materials: pathlib.Path, cars_shaders: pathlib.Path,
            cars_textures: pathlib.Path | None = None,
            expected_textures_sha256: str | None = None,
            allow_absent: bool = True) -> dict:
    """同一FH6 carsスコープのZIPで照合し、参照の実体とCRC/BCXTを検査する。"""
    with zipfile.ZipFile(cars_materials) as mz, zipfile.ZipFile(cars_shaders) as sz:
        mi = _zip_index(mz)
        si = _zip_index(sz)
        shader_key = 'shaders/car_tires_pg.zip'
        if shader_key not in si:
            raise SourceVerificationError('Shader family car_tires_pgが原本ZIPに存在しません')
        with zipfile.ZipFile(io.BytesIO(sz.read(si[shader_key]))) as tz:
            shader_idx = _zip_index(tz)
            shader = tz.read(shader_idx['car_tires_pg.shaderbin'])
            xml = tz.read(shader_idx['car_tires_pg.shaderbin.xml'])
        root = ET.fromstring(xml)
        variants = root.findall('./Variants/ExportVariant')
        xml_tex = root.findall('./Textures/Texture')
        if not variants or not xml_tex:
            raise SourceVerificationError('原本Shader XMLの構造が不正')
        used = {x.strip() for v in variants for x in v.attrib.get('textureusage','').split(',') if x.strip()}
        defined = {x.attrib['parametername'] for x in xml_tex}
        if not used.issubset(defined):
            raise SourceVerificationError('Shader使用テクスチャ名がXML宣言に存在しません')
        if any(not all('TexCoord'+str(n) in v.attrib.get('vertexinputs','') for n in range(4)) for v in variants):
            raise SourceVerificationError('原本Tire ShaderのUV0〜3契約と不一致')
        src = {}
        for value in _game_refs_from_material(shader, '.swatchbin'):
            src[value.casefold()] = {'path': value, 'provenance': ['shaderbin']}
        defaults = shader_texture_defaults(shader, root)
        for row in defaults:
            if row['path'].casefold() in src:
                src[row['path'].casefold()]['provenance'].append('shader_parameter:'+row['parameter_name'])
        materials = ['_fmnext/tires/tires_pg_sidewall.materialbin','_fmnext/tires/tires_pg_tread.materialbin']
        for mat in materials:
            if mat not in mi:raise SourceVerificationError('車両用材質が欠けています: '+mat)
            raw = mz.read(mi[mat]);
            if b'car_tires_pg.shaderbin' not in raw:raise SourceVerificationError('材質Shader family不一致')
            for value in _game_refs_from_material(raw, '.swatchbin'):
                key = value.casefold()
                if key not in src:src[key] = {'path':value,'provenance':[]}
                src[key]['provenance'].append('materialbin:'+mat)
        if not src:raise SourceVerificationError('原本テクスチャ参照が空です')
        expected_names = sorted(_texture_member(row['path']) for row in src.values())
        if len({x.casefold() for x in expected_names}) != len(expected_names):
            raise SourceVerificationError('原本Texture参照が重複しています')
        available = 0
        texture_sha = None
        texture_index = None
        ztex = None
        if cars_textures is not None:
            # 同名の別用途ZIPを採用しないため、既知の原本SHAが必須。
            if not expected_textures_sha256 or len(expected_textures_sha256) != 64:
                raise SourceVerificationError('原本Texture ZIPの期待SHA-256を指定してください')
            texture_sha = hashlib.sha256(cars_textures.read_bytes()).hexdigest()
            if texture_sha != expected_textures_sha256.casefold():
                raise SourceVerificationError('原本Texture ZIP SHA-256の不一致（同名別scopeを拒否）')
            ztex = zipfile.ZipFile(cars_textures)
            texture_index = _zip_index(ztex)
        try:
            rows = []
            for ref in sorted(src.values(),key=lambda x:x['path'].casefold()):
                member = _texture_member(ref['path'])
                row = {'member':member,'role_candidate':_texture_role_candidate(ref['path']),
                       'provenance':sorted(ref['provenance']),'status':'SOURCE_NOT_PRESENT'}
                if texture_index is not None:
                    name = texture_index.get(member.casefold())
                    if name:
                        data = ztex.read(name)
                        meta=read_swatch_surface(data)
                        meta.pop('pixels',None)
                        if not meta.get('supported_bundle') or not meta.get('pixel_range_valid'):
                            raise SourceVerificationError('原本SwatchBinの構造/画素長が不正: '+member)
                        row.update(status='SOURCE_VERIFIED',bytes=len(data),sha256=sha(data),
                                   surface={k:meta.get(k) for k in ('width','height','encoding','tiled_flag')})
                        available+=1
                    else:
                        row['status']='MEMBER_MISSING'
                rows.append(row)
        finally:
            if ztex:ztex.close()
    total=len(rows)
    complete=available==total
    if not complete and not allow_absent:
        raise SourceVerificationError(f'原本Textureの実バイトが不足: {available}/{total}')
    return {'schema':'lo4fh6.source_tire_texture_binding.v1',
            'status':'SOURCE_VERIFIED' if complete else 'MISSING_OR_PARTIAL_SOURCE',
            'original_shader_family':'car_tires_pg',
            'cars_materials_sha256':sha(cars_materials.read_bytes()),
            'cars_shaders_sha256':sha(cars_shaders.read_bytes()),
            'source_textures_sha256':texture_sha,
            'texture_archive_expected_game_relative':'Content/media/cars/_library/Textures.zip',
            'texture_slots_declared':len(xml_tex),
            'texture_slots_used_by_shader':len(used),
            'unique_source_texture_refs':total,
            'source_texture_refs_verified':available,
            'unmapped_parameter_bindings_are_not_inferred':True,
            'game_shader_pixel_equivalence_verified':False,
            'regular_runtime_changed':False,
            'general_release_approved':False,
            'textures':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cars-materials',type=pathlib.Path,required=True)
    p.add_argument('--cars-shaders',type=pathlib.Path,required=True)
    p.add_argument('--cars-textures',type=pathlib.Path)
    p.add_argument('--expected-textures-sha256',help='FH6 cars/_library/Textures.zip原本の実SHA-256')
    p.add_argument('--report',type=pathlib.Path)
    p.add_argument('--strict',action='store_true')
    a=p.parse_args()
    result=inspect(cars_materials=a.cars_materials,cars_shaders=a.cars_shaders,
                   cars_textures=a.cars_textures,expected_textures_sha256=a.expected_textures_sha256,allow_absent=not a.strict)
    if a.report:
        if a.report.exists():raise FileExistsError('既存証拠は上書きしません')
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({key:result[key] for key in ('status','texture_slots_declared','texture_slots_used_by_shader','unique_source_texture_refs','source_texture_refs_verified')},ensure_ascii=False))
    return 0 if result['status']=='SOURCE_VERIFIED' else 2


if __name__=='__main__':
    raise SystemExit(main())
