"""FH6 original-source Skin/Morph record binding; NO guessed runtime pose.

A ModelBin Mesh's source identifiers, exact index span, original half floats,
stride and skeleton range must all agree before exposing a binding. Nothing
in this module computes game-runtime joint pose, morph coefficients, or shader.
This is first-party code inspired by verified wire formats and the project's
existing original-skin-half-decoder research. Original game bytes not bundled.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import numpy as np
from .modelbin_geometry_decoder import Blob, Mesh, DecodeError, data, mesh_index_range


@dataclass(frozen=True)
class SkinBinding:
    original_buffer_id: int
    original_record_start: int
    vertex_count: int
    skeleton_bone_count: int
    buffer_sha256: str
    bone_indices: np.ndarray  # shape (vertex_count, 1|2); as-authored source IDs
    weights: np.ndarray  # shape (vertex_count, 1|2); original normalized half floats


@dataclass(frozen=True)
class MorphBinding:
    original_buffer_id: int
    original_record_start: int
    vertex_count: int
    target_count: int
    buffer_sha256: str
    position_deltas: np.ndarray   # shape (n, targets, 3), as-authored source local deltas
    normal_deltas: np.ndarray     # shape (n, targets, 3), as-authored source local deltas
    position_weight_indices: np.ndarray
    normal_weight_indices: np.ndarray
    is_damage: bool  # true means native damage shader / coefficient path, not ordinary fitment


def _identified_buffer(raw: bytes, mesh: Mesh, blobs: list[Blob], *, kind: str):
    if kind == 'Skin':
        source_id=mesh.skin_id
        count=mesh.skin_count
    elif kind == 'MBuf':
        source_id=mesh.morph_id
        count=mesh.morph_count
    else:
        raise DecodeError('unknown original deformation kind')
    if count == 0:
        if source_id != -1:
            raise DecodeError(f'zero source {kind} count has a buffer reference')
        return None
    if not 0 < count <= 32 or source_id < 0:
        raise DecodeError(f'unsupported source {kind} elements or missing original buffer id')
    candidates=[b for b in blobs if b.tag==kind and b.meta_id==source_id]
    if len(candidates)!=1:
        raise DecodeError(f'{kind} reference is missing or not unique; no ordinal fallback')
    b=candidates[0]
    if b.v!=(1,1):
        raise DecodeError(f'unsupported original {kind} buffer version')
    payload=data(raw,b)
    if len(payload)<16:
        raise DecodeError(f'original {kind} header truncated')
    # ForzaTools BufferHeader v1.1; format and subelement counts are authoritative.
    import struct
    num,bytes_count,stride,sub,unused,fmt=struct.unpack_from('<iiHBBi',payload)
    if (num<1 or num>3_000_000 or bytes_count<1 or bytes_count>128*1024*1024
        or unused!=0 or len(payload)!=16+bytes_count or num*stride!=bytes_count):
        raise DecodeError(f'{kind} buffer length/subheader inconsistency')
    lo,hi=mesh_index_range(raw,mesh,blobs)
    first=lo+mesh.vertex_offset
    last=hi+mesh.vertex_offset
    if first<0 or last>=num or last<first:
        raise DecodeError(f'{kind} source vertex indices do not fit the referenced buffer')
    return b,payload,first,last+1,sub,fmt,stride


def decode_original_skin(raw: bytes,mesh: Mesh,blobs: list[Blob],*,bone_count:int)->SkinBinding|None:
    """Read indexed original Skin half weight/Bone IDs, without applying bind pose."""
    if not 1<=bone_count<=2048:
        raise DecodeError('source skin skeleton has invalid bone count')
    source=_identified_buffer(raw,mesh,blobs,kind='Skin')
    if source is None:
        return None
    blob,payload,first,end,sub,fmt,stride=source
    if fmt!=34 or stride!=mesh.skin_count*4 or sub!=mesh.skin_count or mesh.skin_count not in (1,2):
        raise DecodeError('unsupported original Skin weight/pair format')
    n=end-first
    raw_pairs=np.ndarray((n,mesh.skin_count,2),dtype='<f2',buffer=payload,
                         offset=16+first*stride,strides=(stride,4,2)).astype('f4')
    weights=raw_pairs[:,:,0]
    joints=raw_pairs[:,:,1]
    if (not np.isfinite(raw_pairs).all() or np.any(weights<0) or np.any(weights>1)
        or np.any(joints<0) or np.any(joints>=bone_count)
        or np.any(joints!=np.floor(joints))
        or np.any(np.abs(weights.sum(axis=1)-1)>0.002)):
        raise DecodeError('original Skin half weights or Bone IDs are invalid')
    return SkinBinding(mesh.skin_id,first,n,bone_count,sha256(payload).hexdigest(),
                       joints.astype('i4'),weights.copy())


def decode_original_morph(raw: bytes,mesh: Mesh,blobs: list[Blob])->MorphBinding|None:
    """Preserve source position/normal half deltas and native weight-index slots.

    These records cannot be evaluated without validated game coefficients and
    a classified damage-vs-fitment source. Never assume a coefficient of 0.
    """
    source=_identified_buffer(raw,mesh,blobs,kind='MBuf')
    if source is None:
        return None
    blob,payload,first,end,sub,fmt,stride=source
    targets=mesh.morph_count
    if fmt!=10 or sub!=2*targets or stride!=16*targets:
        raise DecodeError('unsupported original MBuf target/half-delta layout')
    n=end-first
    values=np.ndarray((n,2*targets,4),dtype='<f2',buffer=payload,
                      offset=16+first*stride,strides=(stride,8,2)).astype('f4')
    if not np.isfinite(values).all():
        raise DecodeError('original Morph contains nonfinite delta or weight slot')
    slots=values[:,:,3]
    if np.any(slots<0) or np.any(slots>=32) or np.any(slots!=np.floor(slots)):
        raise DecodeError('original Morph references an unsupported weight slot')
    return MorphBinding(mesh.morph_id,first,n,targets,sha256(payload).hexdigest(),
                        values[:,:targets,:3].copy(),values[:,targets:,:3].copy(),
                        slots[:,:targets].astype('i4'),slots[:,targets:].astype('i4'),
                       bool(mesh.is_morph_damage))
