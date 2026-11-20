"""
FH6原本だけからUVアフィン・11面Mask可用性・Shadow分類を行う。
標準製品描画器とは未接続の独立研究段階。
参照製品 MeshBlob v1.12と参照製品 StudioのUV変換順を外部仕様として参照し、Python処理は独自実装した。
未知フィールドや不完全・非互換な原本は明示拒否する。
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
import math
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
from .modelbin_geometry_decoder import DecodeError, Mesh

SECTIONS = {
    'Front': 1, 'Back': 2, 'Top': 4, 'Left': 8, 'Right': 16,
    'Wing': 32, 'Glass_Front': 64, 'Glass_Back': 128,
    'Glass_Top': 256, 'Glass_Left': 512, 'Glass_Right': 1024,
}
MAX_XML = 1024*1024
MAX_MASK = 32*1024*1024

@dataclass(frozen=True)
class NativeMask:
    available_sides: int
    xml_sha256: str
    sections: tuple[tuple[str,bool,bool,str], ...]


def read_source_masks(z: zipfile.ZipFile) -> NativeMask:
    """
    有効な11面には実際のMasks.xmlと対応する原本資産を必須とする。
    ここで返すのは確認済みの可用性だけで、画素被覆・Shader一致・投影結果は認定しない。
    """
    entries = {}
    for info in z.infolist():
        key = info.filename.casefold()
        if key in entries:
            raise DecodeError('ambiguous case-insensitive mask/archive path')
        entries[key] = info
    xml = entries.get('liverymasks/masks.xml')
    if xml is None or not 0 < xml.file_size <= MAX_XML:
        raise DecodeError('required original LiveryMasks/Masks.xml missing or oversized')
    payload = z.read(xml)
    # XML Parserが無視する場合でもEntity展開をすべて拒否する。
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise DecodeError('external/inline XML entities prohibited')
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise DecodeError('invalid original mask XML') from error
    if root.tag != 'LiveryMasks' or root.attrib:
        raise DecodeError('unexpected native mask root')
    sides = 0
    sections = []
    seen = set()
    for section in root:
        name = section.tag
        if name not in SECTIONS or name in seen or list(section):
            raise DecodeError('unknown or duplicated native mask section')
        seen.add(name)
        valid_text = section.attrib.get('valid')
        if valid_text not in ('true','false'):
            raise DecodeError('mask valid declaration missing or invalid')
        valid = valid_text == 'true'
        # 別面のMaskへ推測で代替しないことを検証する。
        canonical = 'liverymasks/'+name.lower()+'.swatchbin'
        info = entries.get(canonical)
        present = info is not None
        checksum = ''
        if present:
            if not 0 < info.file_size <= MAX_MASK or info.flag_bits & 1:
                raise DecodeError('mask resource is empty, encrypted, or oversized')
            if valid:
                checksum=sha256(z.read(info)).hexdigest()
        if valid and present:
            sides |= SECTIONS[name]
        elif valid and not present:
            # 参照製品 StudioはMask面が利用できない状態も扱う。
            # 呼出元にも可用性の欠落を明示する。
            pass
        sections.append((name,valid,present,checksum))
    # 宣言のない面は明示的に利用不可と数える。
    # ファイル名だけを根拠に利用可能へ昇格させない。
    return NativeMask(sides,sha256(payload).hexdigest(),tuple(sections))


def source_uv_affine(decoded: dict, mesh: Mesh) -> dict[int,np.ndarray]:
    """Unflipped native UV * source scale + source offset, retaining channel 4.

    Each transform Vector4 is (offsetU,scaleU,offsetV,scaleV) in native wire order.
    Caller must separately decide shader sampling orientation; NEVER double-flip V.
    """
    if decoded.get('space_proof') != 'SOURCE_VERTEX_ONLY_NOT_BONE_INSTANCED':
        raise DecodeError('UV data has no verified original primitive origin')
    transforms=mesh.uv_xforms
    result={}
    for (semantic,channel),source in decoded['arrays'].items():
        if semantic != 'TEXCOORD':
            continue
        if not isinstance(channel,int) or channel<0 or channel>=5 or channel>=len(transforms):
            raise DecodeError('source UV semantic has no native affine')
        affine=np.asarray(transforms[channel],dtype=np.float64)
        values=np.asarray(source,dtype=np.float64)
        if affine.shape != (4,) or values.ndim!=2 or values.shape[1]!=2 or not np.isfinite(affine).all() or not np.isfinite(values).all():
            raise DecodeError('invalid native UV source values')
        # 参照製品 Program.TransformUvChannelsは非有限Float32 UVだけを拒否する。
        # 従来の1e9境界は原本形式の制約ではない。
        # 参照製品の表示専用代替UVを製品UVとして使用しない。
        mapped=values * affine[[1,3]] + affine[[0,2]]
        if not np.isfinite(mapped).all():
            raise DecodeError('native UV affine produced non-finite values')
        with np.errstate(over='ignore',invalid='ignore'):
            native_uv=mapped.astype('f4')
        if not np.isfinite(native_uv).all():
            raise DecodeError('native UV affine exceeds finite float32 representation')
        result[channel]=native_uv
    if set(result) != {idx for semantic,idx in decoded['arrays'] if semantic=='TEXCOORD'}:
        raise DecodeError('source UV channels dropped')
    return result


def original_shadow_only(mesh:Mesh,decoded:dict) -> bool:
    """
    原本でShadow専用と確認できたPrimitiveのみ、可視面から除外する。
    未検証のMeshをShadowと推測して削除しない。
    """
    if not decoded['missing_source_normal']:
        return False
    material_id=mesh.materials[1] if len(mesh.materials)>1 else None
    if not (mesh.blob.name=='Shadow' and material_id == -1 and
            (mesh.bucket & 8) != 0 and (mesh.bucket & 16) == 0):
        raise DecodeError('non-shadow source has no NORMAL; do not fabricate geometry')
    return True


def native_uv3_side_allowance(role: str,uvs: dict[int,np.ndarray],masks: NativeMask)->int:
    """
    Maskの可用性検査に限定する。
    完全なShader／Mask画素のGPU検証は別途必要。
    """
    if role not in ('paint','glass','trim','dark','hidden'):
        raise DecodeError('unverified source mesh role')
    if 3 not in uvs:
        return 0
    domain=0x3f if role=='paint' else 0x7c0 if role=='glass' else 0
    return domain & masks.available_sides
