"""ModelBin Mesh v1.12 / VLay v1.1 / IndB / VerB real-data primitive decoder.

Research stage; this does not apply skin, instance transforms, material/Mask policy,
UV scaling, morph, or make a viewer-accepted GLB. It never silently strips UV channels.
No game-derived bytes embedded in this source.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import math
import struct
from typing import NamedTuple
import numpy as np

class DecodeError(ValueError): pass

# 書式ごとの struct.Struct を使い回す（毎回 calcsize と書式の解釈をしない。読む値とエラーは同じ。2026-11-19）
_STRUCTS: dict[str, struct.Struct] = {}

class Read:
    def __init__(self, data):
        self.data = memoryview(data); self.pos = 0
    def value(self, fmt):
        packer=_STRUCTS.get(fmt)
        if packer is None: packer=_STRUCTS[fmt]=struct.Struct('<'+fmt)
        n=packer.size
        if self.pos+n>len(self.data): raise DecodeError(f'field {fmt} truncated at {self.pos}')
        result=packer.unpack_from(self.data,self.pos);self.pos+=n
        return result[0] if len(result)==1 else result
    def uint32_array(self, count):
        """value('I') を count 回読むのと同じ値の tuple（まとめて読む）。途中で切れていれば同じ位置でエラーにする。"""
        available=(len(self.data)-self.pos)//4
        if count>available: raise DecodeError(f'field I truncated at {self.pos+4*available}')
        result=struct.unpack_from(f'<{count}I',self.data,self.pos) if count else ()
        self.pos+=4*count
        return tuple(result)
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise DecodeError(f'truncated skip {n} at {self.pos}')
        result=self.data[self.pos:self.pos+n];self.pos+=n;return result
    def text(self):
        n=self.value('i')
        if not 0<=n<=8192:raise DecodeError('string length out of range')
        return bytes(self.take(n)).decode('latin-1')
    def count(self,max_allowed=200000):
        n=self.value('i')
        if not 0<=n<=max_allowed:raise DecodeError('element count unsafe')
        return n
    def end(self):
        if self.pos!=len(self.data):raise DecodeError(f'unrecognized trailing {len(self.data)-self.pos} bytes')

@dataclass(frozen=True)
class Blob:
    tag: str
    v: tuple[int,int]
    offset: int
    length: int
    meta_id: int|None
    name: str|None

@dataclass(frozen=True)
class Usage:
    index:int;slot:int;stride:int;offset:int;reserved:int

@dataclass(frozen=True)
class Mesh:
    blob:Blob
    materials:tuple[int,...]
    material_groups:tuple[tuple[int,...],...]
    bone:int;lod:int;bucket:int;bucket_order:int;skin_count:int;morph_count:int
    is_morph_damage:bool
    index_width:int;topology:int;index_buffer_id:int;index_byte_offset:int;index_draw_offset:int
    vertex_offset:int;index_count:int;prim_count:int;ref_vertex_count:int;ref_vertices:tuple[int,...]
    layout_id:int;usages:tuple[Usage,...];morph_id:int;skin_id:int
    uv_xforms:tuple[tuple[float,...],...];scale:tuple[float,...];translate:tuple[float,...]

def _metadata(raw,offset,count,header_end):
    out={}
    for j in range(count):
        position=offset+8*j
        if position+8>header_end:raise DecodeError('meta table outside directory')
        tag,flags,rel=struct.unpack_from('<4sHH',raw,position)
        data_len=flags>>4
        value_pos=position+rel
        if value_pos+data_len>header_end:raise DecodeError('meta bytes outside header')
        kind=tag[::-1].decode('latin-1')
        value=memoryview(raw)[value_pos:value_pos+data_len]
        if kind=='Id  ':
            if data_len<4:raise DecodeError('metadata ID too short')
            out['id']=struct.unpack_from('<I',value)[0]
        elif kind=='Name':
            rd=Read(value)
            try:out['name']=rd.text()
            except DecodeError:out['name']=bytes(value).decode('latin-1',errors='replace')
    return out

def parse_bundle(raw:bytes):
    if len(raw)<20 or raw[:4]!=b'burG':raise DecodeError('invalid ModelBin magic')
    maj,minr=raw[4],raw[5]
    if (maj,minr)<(1,1):raise DecodeError('unsupported Bundle version')
    _,header_bytes,total,nb=struct.unpack_from('<hIII',raw,6)
    if total!=len(raw) or nb>65535 or 20+24*nb>header_bytes>total:
        raise DecodeError('invalid Bundle header')
    if not 20+24*nb<=header_bytes<=total:raise DecodeError('unsafe Bundle header')
    blobs=[]
    for i in range(nb):
        tag,major,minor,nmeta,moff,doff,clen,ulen=struct.unpack_from('<4sBBHIIII',raw,20+i*24)
        if doff<header_bytes or doff+max(clen,ulen)>total:raise DecodeError('blob bounds')
        metadata=_metadata(raw,moff,nmeta,header_bytes)
        if ulen not in (0,clen):raise DecodeError('compressed blob not supported')
        blobs.append(Blob(tag[::-1].decode('latin-1'),(major,minor),doff,max(clen,ulen),metadata.get('id'),metadata.get('name')))
    return blobs

def data(raw,blob):return memoryview(raw)[blob.offset:blob.offset+blob.length]

def layout_decode(raw,blob):
    if blob.tag!='VLay' or blob.v<(1,1):raise DecodeError('unsupported VertexLayout')
    r=Read(data(raw,blob));names=[]
    for _ in range(r.value('H')):names.append(r.text())
    elems=[]
    for _ in range(r.value('H')):
        name_index,idx,slot,klass,fmt,offset,step=r.value('hhhhiii')
        if not 0<=name_index<len(names) or not 0<=slot<32 or idx<0:raise DecodeError('invalid vertex semantic')
        elems.append((names[name_index],idx,slot,klass,fmt,offset,step))
    packed=[r.value('i') for _ in elems]
    flags=r.value('I');r.end()
    return elems,packed,flags

def mesh_decode(raw,blob):
    if blob.tag!='Mesh' or blob.v not in ((1,12),(1,13)):
        raise DecodeError('Mesh version not yet implemented')
    r=Read(data(raw,blob))
    groups=(r.count(1024) if blob.v>=(1,13) else 1)
    if groups<1:raise DecodeError('zero source MaterialGroup')
    material_groups=tuple(tuple(r.value('h') for _ in range(4)) for _ in range(groups))
    mats=material_groups[0]
    bone=r.value('h');lod=r.value('H');r.take(2)
    bucket=r.value('H');order=r.value('B');skin=r.value('B');morph=r.value('I')
    damage=r.value('B');index32=r.value('B');topo=r.value('H')
    if damage not in (0,1):raise DecodeError('unknown original Morph damage Boolean')
    idx_id,idx_off,idx_draw,vtx_off,count,prims=r.value('iiiiii')
    r.value('f');refcount=r.value('I')
    nref=r.count(8000000)
    refs=r.uint32_array(nref)
    layout=r.value('i');nuse=r.count(64)
    usages=tuple(Usage(*r.value('iIIII')) for _ in range(nuse))
    mid,sid=r.value('ii')
    ncb=r.count(1024);r.take(4*ncb)
    r.value('I')  # source mesh index
    uvs=tuple(tuple(r.value('f') for _ in range(4)) for _ in range(5))
    scale=r.value('ffff');translate=r.value('ffff')
    r.end()
    if count<0 or count>20_000_000 or idx_draw<0 or idx_off<0:
        raise DecodeError('invalid mesh indices')
    if count>0 and (index32 not in (0,1) or topo not in (4,)):
        raise DecodeError('unsupported mesh topology/size')
    return Mesh(blob,mats,material_groups,bone,lod,bucket,order,skin,morph,bool(damage),4 if index32 else 2,topo,
                idx_id,idx_off,idx_draw,vtx_off,count,prims,refcount,refs,layout,usages,
                mid,sid,uvs,scale,translate)

def buffer_header(raw,blob):
    if blob.tag not in ('IndB','VerB','MBuf') or blob.v[0]<1:raise DecodeError('unsupported buffer header')
    hdr=data(raw,blob)
    if len(hdr)<16:raise DecodeError('buffer header truncated')
    count,size,stride,sub,_,fmt=struct.unpack_from('<iiHBBi',hdr)
    if count<0 or size<0 or stride<0 or 16+size>len(hdr) or (stride and count*stride>size):
        raise DecodeError('invalid vertex/index buffer boundaries')
    return count,size,stride,sub,fmt

def mesh_index_range(raw,mesh,blobs):
    ind=[b for b in blobs if b.tag=='IndB']
    if not ind:raise DecodeError('no index buffer')
    ib=next((b for b in ind if b.meta_id==mesh.index_buffer_id),None)
    if ib is None:
        if 0<=mesh.index_buffer_id<len(ind):ib=ind[mesh.index_buffer_id]
        else:raise DecodeError('unresolved index buffer id')
    count,size,st,sub,fmt=buffer_header(raw,ib)
    start=16+mesh.index_byte_offset+mesh.index_draw_offset*mesh.index_width
    end=start+mesh.index_count*mesh.index_width
    b=data(raw,ib)
    if start<16 or end>len(b):raise DecodeError('index slice out of bounds')
    if mesh.index_count==0:return 0,0
    dtype='<u4' if mesh.index_width==4 else '<u2'
    idx=np.frombuffer(b[start:end],dtype=dtype)
    return int(idx.min()),int(idx.max())

def analyze_modelbin(raw):
    blobs=parse_bundle(raw)
    layouts={b.meta_id:layout_decode(raw,b) for b in blobs if b.tag=='VLay' and b.meta_id is not None}
    meshes=[mesh_decode(raw,b) for b in blobs if b.tag=='Mesh']
    ranges=[]
    for mesh in meshes:
        if mesh.index_count:
            ranges.append(mesh_index_range(raw,mesh,blobs))
        else:ranges.append((0,0))
    return {'meshes':len(meshes),'triangles':sum(m.prim_count for m in meshes),
        'uv_indices':sorted({idx for lay in layouts.values() for sem,idx,*_ in lay[0] if sem=='TEXCOORD'}),
        'skins':sum(m.skin_count>0 for m in meshes), 'morphs':sum(m.morph_count>0 for m in meshes),
        'referenced_index_values':sum(m.index_count for m in meshes),
        'mesh_lod0':sum(bool(m.lod&2) for m in meshes),
        'positions_valid':all(v[1]>=v[0] for v in ranges),
        'mesh_versions':sorted({m.blob.v for m in meshes}),
        'layout_count':len(layouts),
        'tag_counts':dict(Counter(b.tag for b in blobs)),
        }

FORMAT_BYTES={2:16,6:12,10:8,13:8,16:8,24:4,28:4,35:4,37:4}

def extract_raw_geometry(raw:bytes,mesh:Mesh,blobs:list[Blob], *, uv_channels=(0,1,2,3,4)):
    """Decode source vertices, normals, UVs, indexed faces, retaining every UV semantic.

    It deliberately DOES NOT transform bones or apply UV affine: the output is a
    research primitive, NOT a replacement for verified normal/stock scene.
    """
    if mesh.index_count==0:return None
    imin,imax=mesh_index_range(raw,mesh,blobs)
    n=imax-imin+1
    if n>2_000_000 or n<=0:raise DecodeError('unsafe indexed vertex count')
    # resolve exact VertexLayout metadata ID, never assume first layout for all meshes
    layouts=[b for b in blobs if b.tag=='VLay']
    layout=next((b for b in layouts if b.meta_id==mesh.layout_id),None)
    if layout is None:
        if not 0<=mesh.layout_id<len(layouts):raise DecodeError('source layout unresolved')
        layout=layouts[mesh.layout_id]
    elements,packed,flags=layout_decode(raw,layout)
    by_slot={}
    for e in elements:
        sem,semidx,slot,klass,fmt,aligned,step=e
        if fmt not in FORMAT_BYTES:raise DecodeError(f'unknown packed DXGI format {fmt}')
        if slot not in by_slot:by_slot[slot]=[]
        by_slot[slot].append(e)
    offsets={}
    for slot,entries in by_slot.items():
        offset=0
        for e in entries:
            sem,semidx,_,_,fmt,aligned,_=e
            if aligned>=0 and aligned!=offset:raise DecodeError('source packed element offset differs from explicit offset')
            offsets[(sem,semidx,slot)]=offset
            offset+=FORMAT_BYTES[fmt]
    data_by_slot={}
    for usage in mesh.usages:
        vb_list=[b for b in blobs if b.tag=='VerB']
        vb=next((b for b in vb_list if b.meta_id==usage.index),None)
        if vb is None:
            if not 0<=usage.index<len(vb_list):raise DecodeError('source vertex buffer unresolved')
            vb=vb_list[usage.index]
        count,size,stride,sub,fmt=buffer_header(raw,vb)
        if stride<=0:raise DecodeError('zero source vertex stride')
        if usage.slot in data_by_slot:raise DecodeError('duplicate slot binding')
        data_by_slot[usage.slot]=(data(raw,vb),count,stride,usage.offset)
    indices_blob=next((b for b in blobs if b.tag=='IndB' and b.meta_id==mesh.index_buffer_id),None)
    if indices_blob is None:
        ind=[b for b in blobs if b.tag=='IndB']
        indices_blob=ind[mesh.index_buffer_id]
    start=16+mesh.index_byte_offset+mesh.index_draw_offset*mesh.index_width
    index_raw=data(raw,indices_blob)[start:start+mesh.index_count*mesh.index_width]
    indices=np.frombuffer(index_raw,dtype='<u4' if mesh.index_width==4 else '<u2').astype(np.int64)-imin
    if indices.min()<0 or indices.max()>=n:raise DecodeError('index out of local vertex bounds')
    arrays={};position_w=None
    for sem,semidx,slot,klass,fmt,aligned,step in elements:
        if sem not in ('POSITION','NORMAL','TEXCOORD','COLOR'):continue
        if sem=='TEXCOORD' and semidx not in uv_channels:continue
        if slot not in data_by_slot:raise DecodeError('missing source vertex buffer slot')
        buf,count,stride,usage_offset=data_by_slot[slot]
        offset=offsets[(sem,semidx,slot)]
        addr=16+usage_offset+(imin+mesh.vertex_offset)*stride+offset
        last=addr+(n-1)*stride+FORMAT_BYTES[fmt]
        if addr<16 or last>len(buf):raise DecodeError('original vertex data exceeds source buffer')
        row_bytes=FORMAT_BYTES[fmt]
        # numpy vectorized strided views; preserves original zero-copy buffer and minimizes Python loop overhead
        data_view=np.ndarray((n,row_bytes),dtype='u1',buffer=buf,offset=addr,strides=(stride,1))
        key=(sem,semidx)
        if sem=='POSITION' and fmt==13:
            p=np.ndarray((n,4),dtype='<i2',buffer=buf,offset=addr,strides=(stride,2)).astype(np.float32)
            p=np.clip(p/32767.,-1.,1.)
            position_w=p[:,3].copy()
            xyz=p[:,:3].copy()
            if any(mesh.scale[i]!=0 for i in range(3)):
                xyz=xyz*np.array(mesh.scale[:3],dtype=np.float32)+np.array(mesh.translate[:3],dtype=np.float32)
            arrays[key]=xyz
        elif sem=='POSITION' and fmt==6:
            xyz=np.ndarray((n,3),dtype='<f4',buffer=buf,offset=addr,strides=(stride,4))
            arrays[key]=xyz.copy()
            position_w=np.ones(n,np.float32)
        elif sem=='NORMAL' and fmt==37:
            if position_w is None:raise DecodeError('packed normal requires decoded source position.W')
            n2=np.ndarray((n,2),dtype='<i2',buffer=buf,offset=addr,strides=(stride,2)).astype(np.float32)
            n2=np.clip(n2/32767.,-1.,1.)
            normals=np.column_stack((position_w,n2))
            lengths=np.linalg.norm(normals,axis=1)
            normals/=np.maximum(lengths,1.e-15)[:,None]
            arrays[key]=normals
        elif sem=='NORMAL' and fmt==6:
            xyz=np.ndarray((n,3),dtype='<f4',buffer=buf,offset=addr,strides=(stride,4)).copy()
            xyz/=np.maximum(np.linalg.norm(xyz,axis=1),1e-15)[:,None];arrays[key]=xyz
        elif sem=='NORMAL' and fmt==24:
            vals=np.ndarray((n,),dtype='<u4',buffer=buf,offset=addr,strides=(stride,))
            normals=np.stack([((vals>>b)&1023).astype('f4')*(2/1023)-1 for b in (0,10,20)],axis=1)
            normals/=np.maximum(np.linalg.norm(normals,axis=1),1e-15)[:,None];arrays[key]=normals
        elif sem=='NORMAL' and fmt==10:
            vals=np.ndarray((n,4),dtype='<f2',buffer=buf,offset=addr,strides=(stride,2))[:,:3].astype('f4')
            vals/=np.maximum(np.linalg.norm(vals,axis=1),1e-15)[:,None];arrays[key]=vals
        elif sem=='TEXCOORD' and fmt==35:
            u=np.ndarray((n,2),dtype='<u2',buffer=buf,offset=addr,strides=(stride,2)).astype(np.float32)/65535
            arrays[key]=u
        elif sem=='TEXCOORD' and fmt==16:
            u=np.ndarray((n,2),dtype='<f4',buffer=buf,offset=addr,strides=(stride,4)).copy()
            arrays[key]=u
        elif sem=='COLOR' and fmt==28:
            a=np.ndarray((n,4),dtype='u1',buffer=buf,offset=addr,strides=(stride,1)).astype(np.float32)/255
            arrays[key]=a
        elif sem=='COLOR' and fmt==2:
            a=np.ndarray((n,4),dtype='<f4',buffer=buf,offset=addr,strides=(stride,4)).copy();arrays[key]=a
        else:
            raise DecodeError(f'unsupported required semantic {sem}/{semidx}/format {fmt}')
    if ('POSITION',0) not in arrays:raise DecodeError('source lacks position')
    missing_normal=('NORMAL',0) not in arrays  # never fabricate or silently hide source absence
    if not all(np.isfinite(v).all() for v in arrays.values()):raise DecodeError('nonfinite original vertex attributes')
    return {'vertices':n,'triangles':mesh.index_count//3,'indices':indices,'arrays':arrays,
            'index_min':imin,'index_max':imax,'lod_flags':mesh.lod,'materials':mesh.materials,
            'source_uv_indices':sorted({idx for sem,idx,*_ in elements if sem=='TEXCOORD'}),
            'space_proof':'SOURCE_VERTEX_ONLY_NOT_BONE_INSTANCED',
            'missing_source_normal':missing_normal}
