"""原本ModelBin MatI→原本MaterialBin→Shader族の車種共通SHA照合（研究専用）。

原本ZIPのバイトはGitHub・公開レポートに保存しない。ShaderBin実GPU式の
一致は証明しない。未確認のMatI/MaterialBin参照は絶対に推測しない。
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import zipfile
from .modelbin_geometry_decoder import parse_bundle, data
from .carbin_reader import parse_carbin

MATERIAL_PREFIX = 'game:/media/cars/_library/materials/'
SHADER_PREFIX = 'game:/media/cars/_library/shaders/'
MAX_REFERENCE_BYTES = 8 * 1024 * 1024

class SourceMaterialShaderError(ValueError):
    """ModelBin/MatI/MaterialBinの元証拠が不正または欠損。"""

def _source_string(raw: bytes) -> str:
    """元MaterialBinの7-bit長プレフィックス文字列。アスキー固定幅を推測しない。"""
    length = 0
    pos = 0
    for shift in range(0, 35, 7):
        if pos >= len(raw):
            raise SourceMaterialShaderError('source material string truncated')
        value = raw[pos]
        pos += 1
        length |= (value & 0x7f) << shift
        if value < 0x80:
            break
    else:
        raise SourceMaterialShaderError('source material string length invalid')
    if not 0 < length <= 8192 or pos + length > len(raw) or any(raw[pos + length:]):
        raise SourceMaterialShaderError('source material string bounds/padding invalid')
    try:
        result = raw[pos:pos + length].decode('utf-8')
    except UnicodeDecodeError as exc:
        raise SourceMaterialShaderError('source material string encoding invalid') from exc
    if not result or '\x00' in result:
        raise SourceMaterialShaderError('source material string empty or contains NUL')
    return result.replace('\\', '/').casefold()

def _members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    result: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        parts = name.split('/')
        if (not name or '\\' in name or name.startswith('/') or ':' in name
                or '.' in parts or '..' in parts or info.flag_bits & 1
                or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                or info.file_size > 512 * 1024 * 1024):
            raise SourceMaterialShaderError('source archive has unsafe member')
        key = name.casefold()
        if key in result:
            raise SourceMaterialShaderError('source archive has duplicate casefolded member')
        result[key] = info
    if not 0 < len(result) <= 25000:
        raise SourceMaterialShaderError('source archive inventory invalid')
    return result

def _single_nested_ref(raw: bytes, nested_tag: str) -> str:
    blobs = parse_bundle(raw)
    refs = [blob for blob in blobs if blob.tag == nested_tag]
    if len(refs) != 1:
        raise SourceMaterialShaderError('original material reference blob missing or duplicated: ' + nested_tag)
    return _source_string(bytes(data(raw, refs[0])))

def build_original_material_shader_reference(
    vehicle_archive: Path | str,
    material_library_archive: Path | str,
    *, selected_modelbins: set[str],
) -> tuple[bytes, dict]:
    """元Carbinで選択済みのModelBinだけ照合し、既存Shader族Index入力を生成。"""
    if not isinstance(selected_modelbins, set) or not selected_modelbins:
        raise SourceMaterialShaderError('source selected Stock ModelBin set missing')
    if any(not isinstance(x, str) or not x.endswith('.modelbin') for x in selected_modelbins):
        raise SourceMaterialShaderError('source selected ModelBin path invalid')
    counts = Counter()
    with zipfile.ZipFile(vehicle_archive) as source, zipfile.ZipFile(material_library_archive) as library:
        source_names = _members(source)
        library_names = _members(library)
        carbins = [v for v in source_names if v.endswith('.carbin') and '/' not in v]
        if len(carbins) != 1:
            raise SourceMaterialShaderError('source Carbin identity ambiguous')
        car = parse_carbin(source.read(source_names[carbins[0]]))
        car_id = car.get('ordinal')
        if type(car_id) is not int:
            raise SourceMaterialShaderError('source Carbin ID absent')
        if not selected_modelbins.issubset(source_names):
            raise SourceMaterialShaderError('source selected ModelBin absent')
        cache: dict[str, tuple[str, str]] = {}
        models = []
        for name in sorted(selected_modelbins):
            original_model = source.read(source_names[name])
            records = []
            seen: dict[str, tuple[str, str]] = {}
            for blob in parse_bundle(original_model):
                if blob.tag != 'MatI':
                    continue
                counts['original_mati'] += 1
                if not blob.name:
                    raise SourceMaterialShaderError('source MatI name missing')
                uri = _single_nested_ref(bytes(data(original_model, blob)), 'MATI')
                if uri == 'game:/media/materials/default.materialbin':
                    counts['source_default_outside_verified_library'] += 1
                    continue
                if not uri.startswith(MATERIAL_PREFIX):
                    raise SourceMaterialShaderError('source MatI references unsupported library scope')
                material = uri[len(MATERIAL_PREFIX):]
                if material not in library_names:
                    raise SourceMaterialShaderError('source MaterialBin missing: ' + material)
                if material not in cache:
                    original_bin = library.read(library_names[material])
                    original_shader = _single_nested_ref(original_bin, 'MATL')
                    if not original_shader.startswith(SHADER_PREFIX):
                        raise SourceMaterialShaderError('source MaterialBin ShaderBin outside verified cars library')
                    ref = original_shader[len(SHADER_PREFIX):]
                    parts = ref.split('/')
                    if (len(parts) != 2 or not parts[0] or
                            not re.fullmatch(r'[a-z0-9_+.-]+\.shaderbin', parts[1])):
                        raise SourceMaterialShaderError('source MaterialBin Shader family path invalid')
                    cache[material] = (parts[0], sha256(original_bin).hexdigest())
                family, digest = cache[material]
                key = blob.name.casefold()
                if key in seen and seen[key] != (family, digest):
                    raise SourceMaterialShaderError('source MatI name maps to conflicting original Shader families')
                if key not in seen:
                    seen[key] = family, digest
                    records.append({'source_name': blob.name,
                                    'shader_family': family,
                                    'materialbin_sha256': digest})
                    counts['source_original_shader_bindings'] += 1
                    counts['family_' + family] += 1
            models.append({'model': source_names[name].filename,
                           'source_sha256': sha256(original_model).hexdigest(),
                           'material_instances': records})
        result = {'schema': 'lo4fh6.independent.private.cross-vehicle-mati-shader-reference.v1',
                  'car_id': car_id, 'models': models}
    payload = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if not 0 < len(payload) <= MAX_REFERENCE_BYTES:
        raise SourceMaterialShaderError('source Shader reference exceeds bound')
    audit = {'schema': 'lo4fh6.firstparty-original-mati-to-shader-source-proof.v1',
             'car_id': car_id,
             'selected_original_modelbins': len(models),
             'source_original_materialbins': len(cache),
             'crosswalk_sha256': sha256(payload).hexdigest(),
             'counts': dict(sorted(counts.items())),
             'gpu_windows_xbox': 'NOT_PERFORMED', 'research_only': True}
    return payload, audit
