"""FH6ローカル原本WheelStyleの材質インスタンスから原本テクスチャをGLBへ接続する。

ユーザーPCの原本ZIPを読み取り専用で参照。MatI→MaterialBin→ShaderBinの名前付き
Texture2DスロットでBaseColorAlpha/Alphaが一致したメッシュのみ接続する。
未解釈の塗装ShaderやタイヤShaderは既定の中立材質を維持し、見た目補正をしない。
独立研究モード用であり、Xbox外観の一致を保証するものではない。
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import io
from pathlib import Path, PurePosixPath
import zipfile
import xml.etree.ElementTree as ET

from . import wheel_morph_internal as wm
from .fh6_swatch import decode_swatch_image
from .material_runtime import (
    embedded_material_instance_components,
    material_texture_bindings,
    shader_family_from_material,
    _material_source,
    _texture_source,
    _shader_bundle,
    _shader_refs_from_material,
)

# car_automotive_paintの実MaterialBinにもBaseColorAlpha_Textureが存在する。
# 原本Shader/Texture2Dの出典だけを接続し、FH6固有の色合成式は近似しない。
SHADERS = frozenset(('car_standard', 'car_standard_coated', 'car_automotive_paint'))
# 原本の基本色の Texture を持たないホイールの部品のうち、材質の値から色を求めて描くもの（2026-11-18）。
# FOR_MustangGT500_20・FER_488Pista_19・KOE_AgeraRS_17 のリム（rim・rim2・inner_rim・lip）は
# car_carbonfiber（カーボンのホイール）で、以前は材質を付けず、Viewer の仮の材質で銀に見えていた
# （ゲームのペイントのサムネイルでは黒いカーボン）。車体のカーボンの部品と同じく、織り目の 2 色の平均で描く
# （body_trim_default_color._resolve。織り目は描かない）。car_standard で Texture の無い部品（Mustang の
# outer_rim）は、同じ処理で色合いから色を求める。
FLAT_COLOR_FAMILY_PREFIXES = ('car_carbonfiber', 'car_standard')
FLAT_COLOR_ROUGHNESS = {'car_carbonfiber': 0.3}
MAX_ORIGINAL_SWATCH = 32 * 1024 * 1024
MAX_TEXTURE_DIM = 8192
ORIGIN = 'fh6-local-original-modelbin-materialbin-shaderbin-texture2d-v1'

ORIGINAL_GREEN_WHEELPAINT_TEXTURE = (
    'game:/media/cars/_library/textures/_fmnext/globaltexture/'
    'swatches/flat_texture_green_oscicfi.swatchbin'
)


def is_original_green_wheelpaint_input(shader_family: str, source_reference: str) -> bool:
    """実原本cars/_library WheelPaintの緑色入力を識別。完成塗装色とは扱わない。

    第一者実測: wheelpaint/wheelpaint_ch1 MaterialBin→car_automotive_paint
    の BaseColorAlpha_Texture。車種やCarIDによる外観補正は行わない。
    """
    return (
        shader_family == 'car_automotive_paint'
        and isinstance(source_reference, str)
        and source_reference.replace(chr(92), '/').casefold()
            == ORIGINAL_GREEN_WHEELPAINT_TEXTURE
    )





def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_entry(text: str) -> str:
    if not isinstance(text, str) or not text or '\\' in text or text.startswith('/'):
        raise ValueError('原本ModelBinパスが不正')
    parts = PurePosixPath(text).parts
    if not parts or any(p in ('', '..', '.') for p in parts) or not text.casefold().endswith('.modelbin'):
        raise ValueError('原本ModelBinパスが不正')
    return text


def _index(z: zipfile.ZipFile) -> dict[str, str]:
    result = {}
    for info in z.infolist():
        name = info.filename
        if info.is_dir():continue
        _safe = PurePosixPath(name).parts
        if not _safe or name.startswith('/') or '\\' in name or any(p in ('.', '..') for p in _safe):
            raise ValueError('ゲームZIPの原本パスが不正')
        key = name.casefold()
        if key in result:raise ValueError('ゲームZIPの大小文字重複を拒否')
        result[key] = name
    return result


def _family_shader(content: Path, family: str, material_data: bytes) -> tuple[bytes, ET.Element]:
    """既存material_runtimeの原本Shader解決器を使い、同名family以外への曖昧な代替を拒否。"""
    root = content / 'media/cars/_library/shaders'
    if not root.is_dir():
        raise FileNotFoundError('FH6の原本Shaderフォルダーがありません: '+str(root))
    source, shader_name, xml_name, shader_data, xml_data = _shader_bundle(
        content, family, _shader_refs_from_material(material_data))
    # 一括Shaders.zipは研究保存形式で、実ゲームの配置ではない。
    actual = Path(source['path']).resolve()
    canonical = (root / (family+'.zip')).resolve()
    direct = (root / family / (family+'.shaderbin')).resolve()
    if (str(actual).casefold() not in {str(canonical).casefold(),str(direct).casefold()}
        or shader_name.casefold() != (family+'.shaderbin').casefold()
        or xml_name.casefold() != (family+'.shaderbin.xml').casefold()):
        raise ValueError('原本Shaderのfamily/メンバー一致を検証できません: '+family)
    return shader_data, ET.fromstring(xml_data)


def _decode_rgba(raw: bytes):
    if not 0 < len(raw) < MAX_ORIGINAL_SWATCH:raise ValueError('SwatchBinサイズが不正')
    image, meta = decode_swatch_image(raw)
    if image is None or not (1 <= image.width <= MAX_TEXTURE_DIM and 1 <= image.height <= MAX_TEXTURE_DIM):
        raise ValueError('原本SwatchBinが安全に復号できません: '+str(meta.get('decode_error')))
    return image


# car_standard 系の原本ホイールの材質の色合い・粗さ（MTPR の名前の CRC32）。
STANDARD_TINT_CRC32 = 0x53A946B6  # BaseColor_TintColorParam
STANDARD_ROUGHNESS_SHIFT_CRC32 = None  # 初回に計算


def _standard_wheel_surface(content: Path, mat_bytes: bytes, archive: Path, family: str, slots: dict) -> dict | None:
    """car_standard 系の原本ホイールの材質の色合い（線形）・金属度・粗さ。分からなければ None。

    以前は全ての原本ホイールの材質を、Texture の色そのまま・金属度 0・粗さ 1（つや消し）で作っていた。
    car_standard のリム（例：HON_Prelude_00 の paintedmetal、色合いは線形 0.855 の明るいグレー、
    RoughMetalAO は plainmetal）はゲームでは銀の金属だが、Viewer では白いつや消しに見えていた。
    - 色合い：親 MaterialBin と MatI の MTPR の BaseColor_TintColorParam（MatI が後勝ち）。無ければ
      ShaderBin の既定値（部品の色付け body_trim_default_color と同じ）。
    - 粗さ・金属度：RoughMetalAO_Texture の R（粗さ）・G（金属度）の平均（参照製品 car_model_renderer.cpp
      のシェーダーも R＝粗さ・G＝金属度・B＝AO として読む。参照のみ）。粗さには Roughness_Shift_floatVal を足す。
    """
    global STANDARD_ROUGHNESS_SHIFT_CRC32
    import zlib
    from PIL import ImageStat
    from .body_trim_default_color import _read_parameters_tolerant, _shader_color_default
    from .wheel_default_paint import _mtpr_blobs
    if STANDARD_ROUGHNESS_SHIFT_CRC32 is None:
        STANDARD_ROUGHNESS_SHIFT_CRC32 = zlib.crc32(b'Roughness_Shift_floatVal') & 0xFFFFFFFF
    try:
        paths = embedded_material_instance_components(mat_bytes)['resource_paths']
        if len(paths) != 1:
            return None
        base, _ = _material_source(content, paths[0], archive)
        tint, shift = None, 0.0
        for blob in _mtpr_blobs(base) + _mtpr_blobs(mat_bytes):
            for row in _read_parameters_tolerant(blob):
                key = int(row['parameter_crc32'], 16)
                value = row.get('value')
                if key == STANDARD_TINT_CRC32 and isinstance(value, list) and len(value) >= 3:
                    tint = [float(v) for v in value[:3]]
                elif key == STANDARD_ROUGHNESS_SHIFT_CRC32 and isinstance(value, float):
                    shift = float(value)
        tint_source = 'materialbin-or-material-instance'
        if tint is None:
            tint = _shader_color_default(content, family, 'BaseColor_TintColorParam', {})
            tint = [float(v) for v in tint[:3]] if isinstance(tint, list) and len(tint) >= 3 else None
            tint_source = 'shaderbin-dfpr-default'
        rough = metal = None
        reference = slots.get('RoughMetalAO_Texture')
        if reference:
            raw, _ = _texture_source(content, reference, archive)
            image = _decode_rgba(raw).convert('RGB')
            try:
                means = ImageStat.Stat(image).mean
            finally:
                image.close()
            rough = min(1.0, max(0.04, means[0] / 255.0 + shift))
            metal = min(1.0, max(0.0, means[1] / 255.0))
    except Exception:  # noqa: BLE001  原本を読めなければ従来どおり（推測しない）
        return None
    if tint is None and rough is None:
        return None
    if tint is not None and not all(0.0 <= v <= 4.0 for v in tint):
        return None
    return {'tint_linear': tint, 'tint_source': tint_source if tint is not None else None,
            'roughness': rough, 'metalness': metal, 'roughness_shift': shift,
            'roughmetalao_texture': reference}


def _compose_uv0_alpha(base, mask):
    """別解像度の原本DIFF/OPACを同一UV0でローカルプレビュー合成する。

    FH6の独立Texture2Dスロットは共通の縦横画素数を要求しない。
    ここで行うUV0基準のBILINEAR再サンプリングは表示用PNGだけに適用し、
    インストール済みSwatchBinの内容・署名・原本解像度は変更しない。
    原本ShaderのSampler/UV変換まで同一だと認定するものではない。
    """
    from PIL import Image
    if base.mode != 'RGBA' or mask.mode != 'L':
        raise ValueError('原本DIFF/OPACの復号モードが不正')
    base_size = tuple(base.size)
    mask_size = tuple(mask.size)
    if mask_size != base_size:
        new_mask = mask.resize(base_size, Image.Resampling.BILINEAR)
        mask.close()
        mask = new_mask
        resampling = 'bilinear-uv0-local-preview'
    else:
        resampling = 'none'
    try:
        base.putalpha(mask)
    finally:
        mask.close()
    return {'diffuse_pixels': list(base_size),
            'opacity_source_pixels': list(mask_size),
            'opacity_preview_sampling': resampling,
            'source_textures_unchanged': True,
            'shader_sampler_parity_unapproved': True}


def _source_bindings(content: Path, mat_bytes: bytes, vehicle_zip: Path, cache: dict):
    comp = embedded_material_instance_components(mat_bytes)
    paths = comp['resource_paths']
    if len(paths) != 1:raise ValueError('原本MatIのMaterialBinが一意ではありません')
    base, info = _material_source(content, paths[0], vehicle_zip)
    family = shader_family_from_material(base)
    if family not in SHADERS:return family, {}
    # 同じShader familyでも原本MaterialBinの参照先・Shader Variantは異なり得る。
    # family名のみのキャッシュでは別原本のShader定義を混用するため、
    # 親MaterialBin実バイトSHAとfamilyの両方で一意にする。
    shader_key = (family, digest(base))
    if shader_key not in cache:
        cache[shader_key] = _family_shader(content, family, base)
    shader, xml = cache[shader_key]
    rows = {e['parameter_name']:e['path'] for e in material_texture_bindings(base, shader, xml)}
    for parameter in comp['parameter_blobs']:
        for e in material_texture_bindings(parameter,shader,xml):
            rows[e['parameter_name']]=e['path']
    return family, rows


def attach_original_wheel_textures(doc:dict, binary:bytearray, *, content:Path,
                                   vehicle_archive:Path) -> dict:
    """既存WheelStyleを全て温存。Shader Texture2Dの署名対応分だけGLBを装飾。"""
    from PIL import Image
    if not isinstance(doc.get('meshes'),list) or not isinstance(binary,bytearray):
        raise ValueError('原本GLBのメッシュ/BIN構造が不正')
    archive=Path(vehicle_archive)
    if not archive.is_file():raise FileNotFoundError('インストール済み車両ZIPがありません')
    # パス文字列のstartswithでは "cars-backup" まで許してしまう。
    # Windowsの大文字小文字差も含めPathで実スコープの親子関係を判定する。
    cars_root=(Path(content)/'media'/'cars').resolve()
    if not archive.resolve().is_relative_to(cars_root):
        raise ValueError('車両ZIPの参照先がFH6インストールスコープ外')
    shader_dir=Path(content)/'media/cars/_library/shaders'
    if not shader_dir.is_dir():raise FileNotFoundError('FH6原本shaderディレクトリがありません: '+str(shader_dir))
    shader_cache={};images={};materials={};mesh_updates=0;flat_reader=None;flat_colors={}
    report={'schema':'lo4fh6.private.local_wheel_texture_binding.v1',
            'origin':ORIGIN,'car_zip_sha256':digest(archive.read_bytes()),
            'textured_wheel_meshes':0,'source_materials':0,'source_textures':0,
            'paint_shader_materials_with_unresolved_output_color':0,
            'original_green_wheelpaint_input_materials':0,
            'original_hidden_wheel_passes_without_textures':0,
            'source_shader_is_not_xbox_exact':True,'xbox_approved':False,
            'unresolved':{},'source_records':[],'flat_color_wheel_materials':0}
    # ローカルShader/ModelBinの署名と情報を使用。プレビューへの埋め込み以外は書き込まない。
    with zipfile.ZipFile(archive) as vehicle:
        vi=_index(vehicle)
        material_instances={}
        for mesh in doc['meshes']:
            e=mesh.get('extras') or {}
            if e.get('lo4_part_type')!='WheelStyle':continue
            source=_safe_entry(e.get('lo4_source_entry',''))
            mid=e.get('lo4_wheel_material_id')
            if source.casefold() not in vi:raise ValueError('WheelStyle原本ModelBinが車両ZIPにありません')
            # 第一者Wheel Morphが原本Bucket/幾何の出典で確定させた
            # 非描画Passだけは、未使用のUV0/Texture2Dを要求しない。
            # Mesh/Indexは温存。可視Wheelは従来の厳密なUV0ゲートへ進む。
            hidden_filter=e.get('lo4_wheel_render_pass_filter')
            # 原本MorphでMesh/MatI/Bucket/NORMALを確認済みのShadowだけ例外。
            # 名前にShadowを含むだけ・MaterialIDが-1なだけの可視面は除外しない。
            original_shadow_signed = (
                hidden_filter == 'original-shadow-only'
                and e.get('lo4_wheel_render_pass_original_mesh_name') == 'Shadow'
                and type(mid) is int and mid == -1
                and e.get('lo4_wheel_material_name') in ('', None)
                and type(e.get('lo4_wheel_render_pass_bucket_flags')) is int
                and (e['lo4_wheel_render_pass_bucket_flags'] & 0x08) != 0
                and (e['lo4_wheel_render_pass_bucket_flags'] & 0x10) == 0
            )
            if (e.get('lo4_role')=='hidden'
                    and (hidden_filter in ('transparent-static-view',)
                         or original_shadow_signed)
                    and isinstance(e.get('lo4_wheel_render_pass_original_role'),str)
                    and isinstance(mesh.get('primitives'),list)
                    and len(mesh['primitives'])==1):
                report['original_hidden_wheel_passes_without_textures']+=1
                continue
            # 可視Wheelは原本Material ID=0も有効。欠落・不正値の無言の中立表示を禁止する。
            # 一方、原本証明済み非描画Passには未使用の材質ID・名前を要求しない。
            if type(mid) is not int or mid < 0:
                raise ValueError(
                    '可視WheelStyleの原本Material IDが未設定または不正'
                    f" (Mesh={mesh.get('name')!r}, ModelBin={source!r}, MaterialID={mid!r})")
            label=e.get('lo4_wheel_material_name')
            if not isinstance(label,str) or not label.strip():
                raise ValueError(
                    '可視WheelStyleの原本MaterialNameが未設定または不正'
                    f" (Mesh={mesh.get('name')!r}, ModelBin={source!r}, MaterialID={mid})")
            key=(source.casefold(),mid,label.casefold())
            if key not in material_instances:
                src=vehicle.read(vi[source.casefold()]);blobs=wm._parse_blobs(src)
                mt=[b for b in blobs if b.tag==0x4d617449 and b.identifier==mid]
                if len(mt)!=1 or mt[0].name.casefold()!=label.casefold():
                    raise ValueError('原本ModelBin MatIとGLBのMaterialIDが不一致')
                family,slots=_source_bindings(content,bytes(mt[0].data),archive,shader_cache)
                material_instances[key]={'family':family,'slots':slots,'mat_sha':digest(bytes(mt[0].data)),
                                         'modelbin_sha':digest(src),
                                         'standard_surface':(_standard_wheel_surface(
                                             content,bytes(mt[0].data),archive,family,slots)
                                             if family in ('car_standard','car_standard_coated') else None)}
            record=material_instances[key]
            # 元ModelBin SHAをGLB自身にも保存し、同名別バイトの14種を別出典にする。
            # seal_firstparty_chassis_metadataがlo4fh6_名へ変換する。
            declared=e.get('lo4_wheel_source_modelbin_sha256')
            if declared is not None and declared != record['modelbin_sha']:
                raise ValueError('元WheelStyleのGLB ModelBin SHA署名が不一致')
            e['lo4_wheel_source_modelbin_sha256']=record['modelbin_sha']
            slots=record['slots']
            # FH6 shaderの実パラメータ名と厳密に対応。塗装/Blur/不明なTexture2Dスロットは着色しない。
            diffuse=slots.get('BaseColorAlpha_Texture')
            flat=None
            if (record['family'] not in SHADERS or not diffuse) and str(record['family']).startswith(FLAT_COLOR_FAMILY_PREFIXES):
                # 原本の Texture を持たないカーボン等：材質の値から色を求める（車体の部品と同じ処理）。
                if key not in flat_colors:
                    from .body_trim_default_color import _TextureReader, _resolve
                    if flat_reader is None:
                        flat_reader=_TextureReader(Path(content), vehicle, archive.stem)
                    try:
                        flat_colors[key]=_resolve(vehicle, vi, source, mid, record['mat_sha'], Path(content),
                                                  archive, flat_reader)
                    except Exception as exc:  # noqa: BLE001  求められなければ従来どおり材質を付けない
                        flat_colors[key]=(None, f'{type(exc).__name__}: {exc}')
                flat_record, flat_reason = flat_colors[key]
                if flat_record and isinstance(flat_record.get('rgba_hex'), str) and len(flat_record['rgba_hex']) == 9:
                    flat=flat_record
                else:
                    report['unresolved'][f'{source}#{mid}:{label}']='flat-color-unavailable: '+str(flat_reason)
            if flat is None and (record['family'] not in SHADERS or not diffuse):continue
            # FH6共通原本の緑16x16はShader入力であり、WheelPaint完成RGBではない。
            original_green_input=is_original_green_wheelpaint_input(record['family'],diffuse)
            prims=mesh.get('primitives',[])
            if len(prims)!=1 or not isinstance(prims[0].get('attributes'),dict) or 'TEXCOORD_0' not in prims[0]['attributes']:
                # UV0を勝手に生成しない。原本Mesh/MatI/Shaderの識別子を
                # 必ず記録し、素材欠落とGLB変換欠落の切分けへ渡す。
                raise ValueError(
                    '原本WheelStyleに必要なUV0がありません'
                    f" (Mesh={mesh.get('name')!r}, ModelBin={source!r},"
                    f" MaterialID={mid}, MaterialName={label!r}, ShaderFamily={record['family']!r},"
                    f" PrimitiveCount={len(prims)})"
                )
            opacity=slots.get('Alpha_Texture') if flat is None else None
            image_key=((diffuse.casefold(),opacity.casefold() if opacity else None) if flat is None
                       else ('flat-color', flat['rgba_hex'].lower()))
            if image_key not in images and flat is not None:
                # 色一色の小さな Texture（Viewer の原本のホイールの経路は map を条件にするため）。
                hexcode=flat['rgba_hex'].lstrip('#')
                tile=Image.new('RGBA',(4,4),tuple(int(hexcode[i:i+2],16) for i in (0,2,4))+(255,))
                stream=io.BytesIO();tile.save(stream,format='PNG');payload=stream.getvalue()
                binary.extend(b'\0'*(-len(binary)%4));off=len(binary);binary.extend(payload)
                vi_idx=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':len(payload)})
                img_idx=len(doc.setdefault('images',[]));doc['images'].append({'name':'local-original-wheel-flat-'+str(img_idx),'bufferView':vi_idx,'mimeType':'image/png'})
                tex_idx=len(doc.setdefault('textures',[]));doc['textures'].append({'name':'local-original-wheel-flat-color','source':img_idx})
                images[image_key]=(tex_idx,[{'parameter':'flat-color-from-material-parameters',
                                             'method':flat.get('method'),'rgba_hex':flat['rgba_hex'].lower(),
                                             'approximation':flat.get('approximation')}])
            if image_key not in images:
                try:
                    src_img,source_diff=_texture_source(content,diffuse,archive)
                except FileNotFoundError as exc:
                    # 元Shaderが必要とするTexture2Dを無告知の中立Wheelへ置換しない。
                    raise ValueError('原本Wheelの必須Texture2D参照が欠落: '+diffuse) from exc
                base=_decode_rgba(src_img).convert('RGBA')
                proof=[{'parameter':'BaseColorAlpha_Texture','reference':diffuse,'sha256':digest(src_img),'source_kind':source_diff['kind']}]
                if opacity:
                    mask_bytes,source_mask=_texture_source(content,opacity,archive)
                    mask=_decode_rgba(mask_bytes).convert('L')
                    dimensions=_compose_uv0_alpha(base, mask)
                    proof.append({'parameter':'Alpha_Texture','reference':opacity,
                                  'sha256':digest(mask_bytes),
                                  'source_kind':source_mask['kind'],
                                  **dimensions})
                # 画素は同じで圧縮の仕方だけを選べる。最小化（optimize=True）は約 5 倍遅いので標準の強さにする（2026-11-20）
                stream=io.BytesIO();base.save(stream,format='PNG');payload=stream.getvalue();base.close()
                binary.extend(b'\0'*(-len(binary)%4));off=len(binary);binary.extend(payload)
                vi_idx=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':len(payload)})
                img_idx=len(doc.setdefault('images',[]));doc['images'].append({'name':'local-original-wheel-'+str(img_idx),'bufferView':vi_idx,'mimeType':'image/png'})
                tex_idx=len(doc.setdefault('textures',[]));doc['textures'].append({'name':'local-original-wheel-source-texture','source':img_idx})
                images[image_key]=(tex_idx,proof)
            tex_idx,proof=images[image_key]
            if key not in materials:
                mat_index=len(doc.setdefault('materials',[]));materials[key]=mat_index
                pbr={'baseColorFactor':[1.0,1.0,1.0,1.0],
                     'baseColorTexture':{'index':tex_idx,'texCoord':0},
                     'metallicFactor':0.0,'roughnessFactor':1.0}
                # car_standard 系は原本の色合い・粗さ（_standard_wheel_surface）。塗装の材質は従来どおり。
                # 金属度は付けない：Viewer の環境は暗く、粗さの小さい金属（HON_S660_16 の sandblasted のリム、
                # 粗さ 0.24・金属度 1）は周りの暗さを映して黒く見えた（サムネイルは銀）。金属度 0 のまま
                # 色合いと粗さだけを使うと、Prelude のリムは明るいグレー、S660 は従来どおりの明るい面になる。
                surface=record.get('standard_surface')
                if flat is not None:
                    pbr['roughnessFactor']=FLAT_COLOR_ROUGHNESS.get(
                        'car_carbonfiber' if str(record['family']).startswith('car_carbonfiber') else '',
                        round(surface['roughness'],4) if surface and surface.get('roughness') is not None else 0.5)
                    surface=None
                if surface:
                    if surface.get('tint_linear'):
                        pbr['baseColorFactor']=[min(1.0,max(0.0,v)) for v in surface['tint_linear']]+[1.0]
                    if surface.get('roughness') is not None:
                        pbr['roughnessFactor']=round(surface['roughness'],4)
                mat={'name':'OriginalWheel:'+label,
                     'pbrMetallicRoughness':pbr,'doubleSided':True,
                     'extras':{'lo4fh6_original_source_wheel_texture':ORIGIN,
                               'modelbin_material_id':mid,
                               'source_modelbin_sha256':record['modelbin_sha'],
                               'material_instance_sha256':record['mat_sha'],
                               'shader_family':record['family'],
                               # car_automotive_paint の生テクスチャは最終WheelPaint色と同義ではない。
                               # ShaderBin XMLにg_CarUserColor0/塗装パラメータがあるため
                               # 原本gltf mapを保持しつつ、外観未再現を機械可読に記録。
                               'lo4fh6_wheel_paint_output_color_unresolved':
                                   record['family']=='car_automotive_paint',
                               'lo4fh6_wheel_paint_original_green_source_input':
                                   original_green_input,
                               'source_texture_refs':proof,'pbr_parity_unapproved':True,
                               'lo4fh6_wheel_standard_surface':record.get('standard_surface'),
                               'lo4fh6_wheel_flat_color':(
                                   {'rgba_hex':flat['rgba_hex'].lower(),'method':flat.get('method'),
                                    'approximation':flat.get('approximation'),
                                    'source':'material-parameters-not-original-texture'}
                                   if flat is not None else None)}}
                if opacity:mat.update({'alphaMode':'MASK','alphaCutoff':0.5})
                doc['materials'].append(mat)
                report['source_records'].append({'source_modelbin_sha256':record['modelbin_sha'],
                                                 'source_entry':source,'material_id':mid,
                                                 'shader_family':record['family'],
                                                 'wheel_paint_output_color_unresolved':
                                                     record['family']=='car_automotive_paint',
                                                 'original_green_wheelpaint_input':original_green_input,
                                                 'material_instance_sha256':record['mat_sha'],
                                                 'textures':proof})
                if flat is not None:
                    report['flat_color_wheel_materials']+=1
                if record['family']=='car_automotive_paint':
                    report['paint_shader_materials_with_unresolved_output_color']+=1
                if original_green_input:
                    report['original_green_wheelpaint_input_materials']+=1
            prims[0]['material']=materials[key]
            mesh_updates+=1
    doc['buffers'][0]['byteLength']=len(binary)
    report.update(textured_wheel_meshes=mesh_updates,
                  source_materials=len(materials),source_textures=len(images))
    return report
