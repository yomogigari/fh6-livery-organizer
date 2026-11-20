"""FH6 original ManufacturerColors.bin (burG/MNCL) palette record reader.

Independent source-bound read-only decoding. This does not infer the native color
shader, does not tint any mesh, and does not guess RGB from the selector alone.
The preview RGB is *not* an accepted Xbox base-paint value. Original bytes are
never serialized in this report.
"""
from __future__ import annotations
from hashlib import sha256
import math
import struct
import zipfile
import zlib
from pathlib import Path

class SourceManufacturerPaletteError(ValueError):
    pass

_BUNDLE_MAGIC=b'burG'
_MNCL_TAG=b'LCNM'
_MAX_FILE=32*1024*1024  # hard safety bound on a single OEM palette asset, not mesh count

class _Reader:
    def __init__(self,data):self.data=memoryview(data);self.offset=0
    def take(self,size):
        if type(size) is not int or size<0 or size>len(self.data)-self.offset:
            raise SourceManufacturerPaletteError('truncated original palette')
        v=self.data[self.offset:self.offset+size].tobytes();self.offset+=size;return v
    def u8(self):return self.take(1)[0]
    def u16(self):return struct.unpack('<H',self.take(2))[0]
    def u32(self):return struct.unpack('<I',self.take(4))[0]
    def rgb(self):
        v=struct.unpack('<3f',self.take(12))
        if not all(math.isfinite(x) for x in v):
            raise SourceManufacturerPaletteError('non-finite native palette RGB')
        return list(v)
    def string(self):
        n=self.u8()
        # Forza source paths and slot names are 8-bit strings, source content is kept intact.
        return self.take(n).decode('latin-1')


def decode_original_manufacturer_colors(raw:bytes)->dict:
    """Resolve exactly one MNCL palette blob and native group selector indices."""
    if not isinstance(raw,bytes) or not 44<=len(raw)<=_MAX_FILE or raw[:4]!=_BUNDLE_MAGIC:
        raise SourceManufacturerPaletteError('invalid original ManufacturerColors burG header/size')
    bundle_version=(raw[4],raw[5])
    if bundle_version<(1,1):
        raise SourceManufacturerPaletteError('old bundle container not accepted without original proof')
    blob_count=struct.unpack_from('<I',raw,16)[0]
    if blob_count<1 or 20+blob_count*24>len(raw):
        raise SourceManufacturerPaletteError('manufacturer bundle directory malformed')
    blobs=[]
    for i in range(blob_count):
        tag,major,minor,flags,unknown,offset,packed,unpacked=struct.unpack_from('<4sBBHIIII',raw,20+24*i)
        if tag!=_MNCL_TAG:continue
        if (major,minor) not in {(1,0),(1,1),(2,0)} or unpacked<=0 or unpacked>_MAX_FILE or offset<20+blob_count*24 or offset+packed>len(raw):
            raise SourceManufacturerPaletteError('MNCL blob format/offset invalid')
        block=raw[offset:offset+packed]
        if packed!=unpacked:
            try:block=zlib.decompress(block)
            except zlib.error as exc:raise SourceManufacturerPaletteError('MNCL compressed encoding unsupported') from exc
        if len(block)!=unpacked:
            raise SourceManufacturerPaletteError('MNCL size mismatch')
        blobs.append(((major,minor),block))
    if len(blobs)!=1:raise SourceManufacturerPaletteError('expected one original MNCL palette')
    version,payload=blobs[0]
    r=_Reader(payload)
    group_count=r.u8()
    colors=[]
    for group_index in range(group_count):
        count=r.u8()
        entries=[]
        for _ in range(count):
            if version[0]>=2:
                n=r.u32()
                if n>len(payload):raise SourceManufacturerPaletteError('invalid slot-name count')
                material_names=[r.string() for _ in range(n)]
                mask=None
            else:
                material_names=None
                mask=r.u32() if version[1]>=1 else r.u16()
            swatch=r.rgb()
            material_path=r.string()
            entries.append({'material_slot_names':material_names,
                            'material_index_mask':mask,
                            'source_preview_rgb_f32':swatch,
                            'source_material_path':material_path})
        group={'source_selector_index':group_index,'source_entries':entries,
               'source_group_enabled':count>0}
        if version[0]>=2:
            # 記録の末尾は「有無フラグ(u8)＋RGB(3f。フラグ=1 のときだけ続く)」の3組。
            # FH6 原本の全 691 車種で、推測なし・余りバイトなしで読み切れることを確認（2026-11-17）。
            # 1組目＝主色（全記録で有り）、3組目＝副色（2色目の項目を持つ記録で有り）。
            # 2組目が有るのは 3 車種（HON_52_S2000WTA_04・NIS_GTRTG_12・VIP_Viper_13）だけで、意味は未確認。
            previews=[]
            for _ in range(3):
                present=r.u8()
                if present not in (0,1):raise SourceManufacturerPaletteError('invalid group preview flag')
                previews.append(r.rgb() if present else None)
            primary,middle,secondary=previews
            group['source_group_preview_primary_present']=primary is not None
            group['source_group_preview_primary_f32']=primary
            group['source_group_preview_middle_present']=middle is not None
            group['source_group_preview_middle_f32']=middle
            group['source_group_preview_secondary_present']=secondary is not None
            group['source_group_preview_secondary_f32']=secondary
        colors.append(group)
    if r.offset!=len(payload):
        raise SourceManufacturerPaletteError('unexpected trailing MNCL data; refuse opaque palette')
    return {'schema':'lo4fh6.firstparty.source-original-manufacturer-colors.v1',
            'source_manufacturer_colors_sha256':sha256(raw).hexdigest(),
            'source_bundle_version':list(bundle_version),'source_palette_blob_version':list(version),
            'source_selector_groups':colors,
            'preview_rgb_is_verified_game_shader_basecolor':False,
            'original_game_material_shader_applied':False,
            'product_default_modified':False,'windows_xbox_approved':False}


def decode_manufacturer_colors_from_archive(archive:Path|str)->dict:
    """Read original archive member; reject aliases/ambiguity. No extraction to disk."""
    with zipfile.ZipFile(archive) as z:
        items=[i for i in z.infolist() if i.filename.casefold()=='manufacturercolors.bin']
        if len(items)!=1 or items[0].flag_bits&1 or items[0].file_size>_MAX_FILE:
            raise SourceManufacturerPaletteError('exact original ManufacturerColors.bin missing or ambiguous')
        return decode_original_manufacturer_colors(z.read(items[0]))


def original_palette_selection(palette:dict,selector:int)->dict:
    """Source selector is positional. Do not silently fall back to group zero."""
    groups=palette.get('source_selector_groups')
    if type(selector) is not int or selector<0 or not isinstance(groups,list) or selector>=len(groups):
        raise SourceManufacturerPaletteError('original manufacturer color selector absent')
    group=groups[selector]
    if group['source_selector_index']!=selector or not group['source_group_enabled']:
        raise SourceManufacturerPaletteError('manufacturer palette group disabled or inconsistent')
    return group


def correlate_original_paint_manufacturer_groups(paint_report:dict,palette:dict)->dict:
    """Bind original Yrvl OEM selectors to original burG palette groups, without shading.

    A factory color selector identifies a *palette group* (many material slots),
    never a ready-to-use RGB or a single global paint value. The original
    material slot names / paths / preview floats are preserved exactly.
    """
    if (not isinstance(paint_report,dict) or
            paint_report.get('schema')!='lo4fh6.firstparty.source-mesh-paint-group-binding.v1'
            or paint_report.get('product_default_modified') is not False
            or paint_report.get('manufacturer_palette_rgb_substituted') is not False
            or paint_report.get('windows_xbox_approved') is not False
            or not isinstance(paint_report.get('manufacturer_palette_groups_unresolved'),dict)):
        raise SourceManufacturerPaletteError('original paint audit required, manufacturer RGB must remain source-only')
    if (not isinstance(palette,dict) or
            palette.get('schema')!='lo4fh6.firstparty.source-original-manufacturer-colors.v1'
            or palette.get('original_game_material_shader_applied') is not False):
        raise SourceManufacturerPaletteError('source ManufacturerColors proof required')
    matched={}
    for hash_id,ref in paint_report['manufacturer_palette_groups_unresolved'].items():
        if (not isinstance(hash_id,str) or len(hash_id)!=16 or any(c not in '0123456789abcdefABCDEF' for c in hash_id)
                or not isinstance(ref,dict) or ref.get('research_only') is not True
                or ref.get('manufacturer_palette_resolved') is not False
                or ref.get('source_finish_code_raw')!=0):
            raise SourceManufacturerPaletteError('original manufacturer selector binding malformed')
        group=original_palette_selection(palette,ref.get('manufacturer_selector_raw'))
        matched[hash_id.upper()]={
            'source_manufacturer_selector':group['source_selector_index'],
            'source_color_entries':group['source_entries'],
            'source_group_preview_primary_present':group.get('source_group_preview_primary_present'),
            'source_group_preview_primary_f32':group.get('source_group_preview_primary_f32'),
            'source_group_preview_secondary_present':group.get('source_group_preview_secondary_present'),
            'source_group_preview_secondary_f32':group.get('source_group_preview_secondary_f32'),
            'source_group_material_shading_applied':False,
            'preview_is_not_game_body_color':True,
        }
    return {'schema':'lo4fh6.firstparty.source-paint-manufacturer-selector-join.v1',
            'source_glb_sha256':paint_report.get('source_glb_sha256'),
            'source_manufacturer_colors_sha256':palette['source_manufacturer_colors_sha256'],
            'source_binding_groups':matched,
            'original_manufacturer_selector_groups_verified':len(matched),
            'original_manufacturer_palette_bytes_modified':False,
            'manufacturer_preview_rgb_substituted_into_shader':False,
            'product_default_modified':False,'windows_xbox_approved':False}



def original_oem_exact_slot_entry(source_binding_group:dict, original_mesh_slot:str):
    """Return a source factory material slot only if the name is *exactly* in MNCL.

    This does not imply its preview RGB is the source game's per-pixel base colour.
    In particular, Livery/Livery2/Livery3 are NOT aliases for Body/Stripes.
    """
    if not isinstance(source_binding_group,dict) or not isinstance(original_mesh_slot,str) or not original_mesh_slot:
        raise SourceManufacturerPaletteError('original palette group / mesh slot invalid')
    entries=source_binding_group.get('source_color_entries')
    if not isinstance(entries,list) or not entries:
        raise SourceManufacturerPaletteError('original palette group has no material slots')
    matched=[]
    for entry in entries:
        if not isinstance(entry,dict):
            raise SourceManufacturerPaletteError('invalid factory material slot entry')
        slots=entry.get('material_slot_names')
        if not isinstance(slots,list):
            # Old MNCL material bitmasks require a separate source slot-index map.
            raise SourceManufacturerPaletteError('native factory slot mask has no verified slot-name mapping')
        if any(not isinstance(s,str) or not s for s in slots):
            raise SourceManufacturerPaletteError('malformed source factory slot name')
        if any(s.casefold()==original_mesh_slot.casefold() for s in slots):
            if not isinstance(entry.get('source_material_path'),str) or not entry['source_material_path']:
                raise SourceManufacturerPaletteError('original slot material path unavailable')
            matched.append(entry)
    if len(matched)>1:
        raise SourceManufacturerPaletteError('original material slot is ambiguous across OEM entries')
    return matched[0] if matched else None


def audit_original_manufacturer_mesh_slots(original_glb:bytes, source_palette_join:dict)->dict:
    """Audit exact mesh material names vs OEM slot names; do not render OEM RGB.

    The hashed carpaint/Livery binding identifies a group, not the correct factory
    entry per mesh. An absent exact slot is an unresolved mapping, NOT Body/Stripes.
    """
    from collections import Counter
    from hashlib import sha256
    from .source_paint_mesh_descriptor_stage import _glb_json
    joined=source_palette_join
    if (not isinstance(joined,dict) or
        joined.get('schema')!='lo4fh6.firstparty.source-paint-manufacturer-selector-join.v1' or
        joined.get('product_default_modified') is not False or
        joined.get('manufacturer_preview_rgb_substituted_into_shader') is not False or
        joined.get('windows_xbox_approved') is not False or
        not isinstance(joined.get('source_binding_groups'),dict) or
        joined.get('source_glb_sha256')!=sha256(original_glb).hexdigest()):
        raise SourceManufacturerPaletteError('original OEM palette and mesh GLB SHA do not match')
    doc,_=_glb_json(original_glb)
    groups=joined['source_binding_groups']
    if not groups:raise SourceManufacturerPaletteError('original OEM material groups missing')
    counts=Counter()
    unresolved=Counter()
    matched=Counter()
    for mesh in doc.get('meshes',[]):
        e=mesh.get('extras',{})
        if not isinstance(e,dict):continue
        h=e.get('lo4_material_binding_hash')
        if not isinstance(h,str) or h.upper() not in groups:continue
        counts['manufacturer_selector_mesh_refs']+=1
        slot=e.get('lo4_material_name')
        if not isinstance(slot,str) or not slot:
            raise SourceManufacturerPaletteError('original mesh material slot name unavailable')
        entry=original_oem_exact_slot_entry(groups[h.upper()],slot)
        if entry is None:
            counts['manufacturer_slot_not_directly_matched']+=1
            unresolved[slot]+=1
        else:
            counts['manufacturer_slot_exact_candidate']+=1
            matched[slot]+=1
    return {
        'schema':'lo4fh6.firstparty.original-manufacturer-slot-audit.v1',
        'source_glb_sha256':joined['source_glb_sha256'],
        'source_manufacturer_colors_sha256':joined['source_manufacturer_colors_sha256'],
        'counts':dict(sorted(counts.items())),
        'unresolved_source_mesh_material_names':dict(sorted(unresolved.items())),
        'exact_candidate_material_names':dict(sorted(matched.items())),
        'oem_preview_rgb_applied':False,
        'automatic_livery_to_body_or_stripes_aliasing':False,
        'native_material_shader_applied':False,
        'product_default_modified':False,
        'windows_xbox_approved':False,
    }