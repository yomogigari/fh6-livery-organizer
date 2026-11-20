#!/usr/bin/env python3
"""署名付きFH6原本Tireの側面文字を標準プレビューへ接続する第一者アダプター。

GameDBから選んだTireモデルと原本MatI/Shader/文字SwatchBinの出典が揃う場合に限る。
元のゲームファイル・成功GLBには書き込まず、必要な文字Textureだけ専用cacheへ取り出す。
当初はstreet_FE_OW（FEOW）1原本の固定証拠JSONだけを受け付けていた。現在は原本MatIの
TextSwitch=1から証拠を作り（source_tire_text_report）、全Tireへ同じ処理を適用する。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import stat
import zipfile
from pathlib import Path

from .source_tire_mati_sidewall_preview import (
    SOURCE_IMAGE_MAX, SourceTextError, SourceTextTextureMissingError, source_manifest,
    read_original_text_extract, derive_text_sidewall_report,
)
from .source_tire_dxil_original2_glb import cached_original2_research_glb


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tire_text_report(model_zip: Path, cars_dir: Path) -> dict | None:
    """原本Tireの側面文字の証拠（中身は _source_tire_text_report_uncached）。"""
    # 同じプロセスの中で、同じ原本（タイヤの ZIP と _library の材質・画像・シェーダーの大きさ・更新日時）なら
    # 前の判定を使う（tire_input_memo。ペイントに依らない判定で、窓の使い回し・撮影の係で毎回繰り返していた）。
    from .tire_input_memo import exists, file_identity, library_identity, remembered
    tire = file_identity(model_zip)
    key = (tire, library_identity(Path(cars_dir) / '_library'))
    return remembered("source_tire_text_report", key, lambda: _source_tire_text_report_uncached(model_zip, cars_dir),
                      enabled=exists(tire))

def _source_tire_text_report_uncached(model_zip: Path, cars_dir: Path) -> dict | None:
    """原本Tire ZIPの文字MatI（TextSwitch=1）から側面文字の証拠を作る。文字なしならNone。"""
    library = cars_dir/'_library'
    shader = library/'shaders'/'car_tires_pg.zip'
    materials = [p for p in library.iterdir()
                 if p.is_file() and p.name.casefold()=='materials.zip'] if library.is_dir() else []
    if not shader.is_file() or len(materials)!=1:
        raise SourceTextError('原本car_tires_pg.zip/Materials.zipが見つかりません')
    report = derive_text_sidewall_report(model_zip, shader, materials[0])
    if report is None:
        return None
    # 文字Textureが原本Textures.zipに一意に存在することを先に確かめる（参照不整合は別扱い）。
    textures = installed_original_textures_archive(cars_dir)
    with zipfile.ZipFile(textures) as z:
        names = [i.filename.replace(chr(92), '/').casefold() for i in z.infolist() if not i.is_dir()]
    absent = [p for p in report['unique_sidewall_mati_text_swatch_paths']
              if len([n for n in names if n == p or n.endswith('/' + p)]) != 1]
    if absent:
        raise SourceTextTextureMissingError(
            '原本MatIの文字Textureが原本Textures.zipに一意に存在しません: ' + ', '.join(absent))
    return report


def source_tire_feow_family(model_zip: Path, source_report) -> bool:
    """車種名でなく、原本ModelBinのハッシュとMatIファミリーの同一性で判定。"""
    if source_report is None:
        return False
    report=(source_report if isinstance(source_report,dict)
            else json.loads(source_report.read_text(encoding='utf-8-sig')))
    expected=report.get('model_archive_sha256')
    if not isinstance(expected,str) or len(expected)!=64:
        raise SourceTextError('FEOW原本MatI証拠が不正です')
    # 別タイヤの通常描画を壊さず、FEOW原本が一致したときだけ自動処理へ進む。
    return _sha(model_zip.read_bytes())==expected


def original_text_zip_from_game(original_textures_zip: Path, source_report: dict,
                                cache_root: Path) -> Path:
    """既存のselective texture extract v1契約を原本Textures.zipの2メンバーから作成。"""
    if not original_textures_zip.is_file() or original_textures_zip.is_symlink():
        raise SourceTextError('原本Textures.zipが見つかりません')
    if original_textures_zip.name.casefold()!='textures.zip':
        raise SourceTextError('原本Textures.zip以外は受け付けません')
    expected=set(source_report['unique_sidewall_mati_text_swatch_paths'])
    if not expected:
        raise SourceTextError('側面文字の原本参照がありません')
    records=[]
    with zipfile.ZipFile(original_textures_zip) as z:
        for path in sorted(expected):
            matched=[i for i in z.infolist() if not i.is_dir() and
                (i.filename.replace('\\','/').casefold()==path or
                 i.filename.replace('\\','/').casefold().endswith('/'+path))]
            if len(matched)!=1:
                raise SourceTextError('原本Textures.zipの文字swatchが一意に見つかりません: '+path)
            info=matched[0]
            if (info.flag_bits & 1) or stat.S_IFMT(info.external_attr>>16)==stat.S_IFLNK:
                raise SourceTextError('原本Textures.zipの暗号化/リンク項目を拒否: '+path)
            if info.file_size<=0 or info.file_size>SOURCE_IMAGE_MAX:
                raise SourceTextError('原本文字swatchサイズ不正: '+path)
            raw=z.read(info)   # CRCはこの2メンバーの読取で検証する
            records.append((path,raw))
    signature=_sha(b''.join(bytes.fromhex(_sha(raw)) for _,raw in records))
    output=cache_root/'FEOW-Original-Two-Textures'/signature/'selected-original-textures.zip'
    if output.is_file():
        # キャッシュ自体が改変された場合に黙って再構築しない。
        with zipfile.ZipFile(output) as zz:
            if set(zz.namelist()) != {'PRIVATE-EXTRACTION-MANIFEST.json',*(('assets/'+p) for p in expected)}:
                raise SourceTextError('FEOW二画像キャッシュに余分/欠損したエントリがあります')
        read_original_text_extract(output,expected)
        return output
    if output.parent.exists():
        raise SourceTextError('FEOW二画像キャッシュが不完全です（上書きしません）')
    output.parent.mkdir(parents=True,exist_ok=False)
    manifest={
      'schema':'lo4fh6.private.selective_texture_extract.v1',
      'source_archive_name':'Textures.zip',
      'requested_count':len(records),'extracted_count':len(records),'missing':[],
      'files':[{'requested':path,'output_member':'assets/'+path,'sha256':_sha(raw),
                'size_bytes':len(raw),'match_method':'path-suffix'} for path,raw in records],
    }
    # 未署名原本は製品ZIPへ格納しない。ゲームの読取とローカルキャッシュ作成だけ。
    with tempfile.NamedTemporaryFile(dir=output.parent,suffix='.partial',delete=False) as tmp:
        temp_path=Path(tmp.name)
    try:
        with zipfile.ZipFile(temp_path,'w',compression=zipfile.ZIP_DEFLATED) as zz:
            zz.writestr('PRIVATE-EXTRACTION-MANIFEST.json',json.dumps(manifest,ensure_ascii=False))
            for path,raw in records: zz.writestr('assets/'+path,raw)
        read_original_text_extract(temp_path,expected)
        temp_path.rename(output)
    finally:
        if temp_path.exists():temp_path.unlink()
    return output


def installed_original_textures_archive(cars_dir: Path) -> Path:
    folder=cars_dir/'_library'
    matches=[p for p in folder.iterdir() if p.is_file() and p.name.casefold()=='textures.zip'] if folder.is_dir() else []
    if len(matches)!=1 or matches[0].is_symlink():
        raise SourceTextError('FH6原本media/cars/_library/Textures.zipが一意に存在しません')
    return matches[0]


def auto_feow_sidewall_glb(mesh_path: Path, model_zip: Path, report_path,
                           game_cars_dir: Path, output_dir: Path, shader_source_zip: Path,
                           legacy_text_zip: Path|None=None) -> tuple[Path,bool]:
    """原本タイヤが対応しない場合は何も変えず、FEOW一致時は欠損を明示エラーにする。"""
    if not source_tire_feow_family(model_zip,report_path):
        return mesh_path,False
    report,_=source_manifest(model_zip,report_path)
    if not shader_source_zip.is_file() or shader_source_zip.is_symlink():
        raise SourceTextError('FEOW原本 car_tires_pg ShaderBin ZIPがありません')
    if legacy_text_zip is not None:
        extracted=legacy_text_zip
    else:
        extracted=original_text_zip_from_game(installed_original_textures_archive(game_cars_dir),report,output_dir)
    return cached_original2_research_glb(mesh_path,model_zip,report_path,extracted,output_dir,shader_source_zip),True
