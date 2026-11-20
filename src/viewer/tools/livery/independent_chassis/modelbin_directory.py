"""原本ModelBin Bundle v1.1+ ディレクトリの独自実装 (private頂点データを出力しない)。"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import struct

class ModelBinFormatError(ValueError): pass

@dataclass(frozen=True)
class Blob:
    tag: str
    major: int
    minor: int
    metadata_count: int
    metadata_offset: int
    data_offset: int
    compressed_size: int
    uncompressed_size: int

def parse_modelbin_directory(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 20 <= len(raw) <= 512 * 1024 * 1024:
        raise ModelBinFormatError('invalid original ModelBin size')
    if raw[:4] != b'burG': raise ModelBinFormatError('ModelBin bundle magic mismatch')
    major,minor=raw[4],raw[5]
    if (major,minor)<(1,1):raise ModelBinFormatError('unsupported legacy Bundle header')
    _,header_size,total_size,blob_count=struct.unpack_from('<hIII',raw,6)
    if blob_count<1 or blob_count>65535 or total_size!=len(raw) or not 20+24*blob_count<=header_size<=len(raw):
        raise ModelBinFormatError('Bundle directory/header size inconsistent')
    blobs=[]
    for i in range(blob_count):
        off=20+24*i
        tag,maj,minr,mcount,moff,doff,csz,usz=struct.unpack_from('<4sBBHIIII',raw,off)
        if mcount>8192 or moff>header_size or (mcount and (moff<20+blob_count*24 or moff+8*mcount>header_size)):
            raise ModelBinFormatError('metadata record outside Bundle header')
        if doff<header_size or doff+max(csz,usz)>len(raw):
            raise ModelBinFormatError('blob record outside Bundle payload')
        blobs.append(Blob(tag.decode('latin-1'),maj,minr,mcount,moff,doff,csz,usz))
    counts=dict(sorted(Counter(b.tag for b in blobs).items()))
    return {'version':f'{major}.{minor}','blobs':tuple(blobs),'counts':counts,
            'header_bytes':header_size,'total_bytes':total_size}
