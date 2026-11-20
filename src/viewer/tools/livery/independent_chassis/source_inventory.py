"""自作Carbin/ModelBin読取段階の入力原本検証。未対応形式を黙って省かない。"""
from __future__ import annotations
from collections import Counter
from pathlib import Path, PurePosixPath
import stat
import zipfile
from .carbin_reader import CarbinFormatError, parse_carbin
from .modelbin_directory import ModelBinFormatError, parse_modelbin_directory
from .source_static_preview_selection import select_static_stock_instances

class SourceInventoryError(ValueError): pass


def _normalized(name: str) -> str:
    if not name or name.startswith(('/', '\\')) or '\\' in name or ':' in name or '\x00' in name:
        raise SourceInventoryError('unsafe archive filename')
    p=PurePosixPath(name)
    if '..' in p.parts or p.as_posix()!=name or name.endswith('/'):
        raise SourceInventoryError('unsafe archive filename')
    return name.casefold()


def _local_reference_path(path: str,car_stem:str)->str:
    raw=path.replace('\\','/').casefold()
    prefix='game:/media/cars/'+car_stem.casefold()+'/'
    if not raw.startswith(prefix):
        raise SourceInventoryError('external or mismatched car model; full cross-archive resolution required')
    rel=raw[len(prefix):]
    if not rel.startswith('scene/') or not rel.endswith('.modelbin'):
        raise SourceInventoryError('invalid source model reference')
    return _normalized(rel)


def inventory_car_archive(path: Path | str)->dict:
    path=Path(path)
    if not path.is_file() or path.is_symlink():raise SourceInventoryError('source ZIP not a regular file')
    with zipfile.ZipFile(path) as archive:
        names={}
        for info in archive.infolist():
            if info.is_dir():continue
            name=_normalized(info.filename)
            if name in names or stat.S_IFMT(info.external_attr >> 16)==stat.S_IFLNK:
                raise SourceInventoryError('archive contains ambiguous paths or symlinks')
            if info.flag_bits&1 or info.file_size>512*1024*1024 or info.compress_type not in (0,8):
                raise SourceInventoryError('unsupported encrypted/compressed/oversized car asset')
            names[name]=info
        carbin=[n for n in names if n.endswith('.carbin') and '/' not in n]
        if len(carbin)!=1:raise SourceInventoryError('exactly one vehicle Carbin required')
        car_stem=carbin[0][:-7]
        try: scene=parse_carbin(archive.read(names[carbin[0]]))
        except CarbinFormatError as exc:raise SourceInventoryError('Carbin parsing failed: '+str(exc)) from exc
        # 参照製品は選択された基準構成を変換し、任意のUpgrade候補は記録に残す。
        # 未選択Upgradeの欠落だけで完成Stock Sceneを無効扱いしない。
        selected={_local_reference_path(instance.path,car_stem)
                  for instance,_ in select_static_stock_instances(
                      scene, lambda source,media:_local_reference_path(source,car_stem))}
        resolved=[]
        missing_optional=[]
        for model in scene['models']:
            rel=_local_reference_path(model.path,car_stem)
            if rel not in names:
                if rel in selected:
                    raise SourceInventoryError('selected original Stock ModelBin missing from ZIP: '+rel)
                missing_optional.append(rel)
                continue
            resolved.append(rel)
        unique=set(resolved)
        model_files={n for n in names if n.endswith('.modelbin')}
        # 参照されないSkeleton／Proxyなどを欠落と即断しない。
        # 幾何を捏造せず元の存在状況を報告する。
        tag_counts=Counter(); blob_count=0
        for rel in sorted(unique):
            try: report=parse_modelbin_directory(archive.read(names[rel]))
            except (ModelBinFormatError,NotImplementedError) as exc:
                raise SourceInventoryError('ModelBin directory unsupported: '+rel+': '+str(exc)) from exc
            tag_counts.update(report['counts']);blob_count+=len(report['blobs'])
    return {'schema':'lo4fh6.firstparty-chassis-source-inventory.v1',
            'car_id':scene['ordinal'],'carbin_version':scene['version'],
            'carbin_bytes_consumed':scene['bytes_consumed'],
            'model_references':len(scene['models']),'resolved_model_references':len(resolved),
            'unique_model_references':len(unique),
            'missing_optional_model_references':sorted(set(missing_optional)),
            'unknown_shared_option_references':scene.get('option_reference_issues',[]),
            'modelbin_files_in_archive':len(model_files),'referenced_bundle_blobs':blob_count,
            'tag_counts':dict(sorted(tag_counts.items())),
            'stock_references':sum(m.stock for m in scene['models']),
            'upgrade_option_count':len(scene['options']),
            'all_references_resolved':True,
            'mesh_vertex_decode':'NOT_IMPLEMENTED',
            'material_binding_decode':'REFERENCE_HASH_ONLY',
            'glb_conversion':'NOT_IMPLEMENTED',
            'standard_viewer_modified':False}
