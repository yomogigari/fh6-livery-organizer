"""車体の非塗装部品（trim等）を、原本MatIの材質の色で描くための色を求める。

これまでViewerは、ペイントで塗られない車体部品（樹脂・ゴム・内装等）を、部品名から選んだ
中立の灰色（例：0x56616a）で描いていた。ホイールの緑と同じく原本の色が反映されていない
仮の色で、NIS_SilviaKs_94のボンネット左右の部品（hoodCustom_a、plastic_smooth）が灰色に
見えていた（原本は BaseColor_TintColorParam が線形0.0015のほぼ黒）。

色の求め方（ホイールの既定色 wheel_default_paint と同じ原本の連鎖）：
- 車体GLBの各Meshに保存された原本の出典（lo4fh6_source_entry、lo4fh6_original_matI_id、
  lo4fh6_original_material_sha256）から、車両ZIPのModelBin内MatIを読み、SHAを照合する。
- MatI→親MaterialBin→ShaderBin既定値の順に重ねた値を使う。
- 塗装系の材質（PaintColorColorParamを持つもの）は material_defined_paint_color の色。
- それ以外は BaseColor_TintColorParam（線形）×ベースカラーのTexture（BaseColorAlpha_Texture）の
  平均色（sRGBを線形にして平均）。Textureの模様（細かな凹凸・汚れ）は平均で近似する。
- 求められない材質は記録しない（Viewerは従来の中立色のまま。推測で色を作らない）。

外部製品（参照のみ）：参照製品（MaterialBin/MTPR、SwatchBinの形式）。
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path

from . import wheel_morph_internal as wm
from .material_runtime import (
    scoped_memo,
    shared_archive_reads,
    _material_source,
    _scoped_is_file,
    _safe_game_asset_relative,
    _strict_scoped_zip_member,
    _strict_scoped_zip_member_path_only,
    inspect_embedded_material_instance_runtime,
    material_defined_paint_color,
)
from .wheel_default_paint import _layer_overrides, _mtpr_blobs, _shader_parameter_names

SCHEMA = "lo4fh6.body-trim-original-color.v1"
ORIGIN = "original-body-mati-default"
# 中立色で描かれる車体GLBの役割。paint・glass・hiddenは対象外。
TRIM_ROLES = frozenset({"trim", "dark"})
BASE_COLOR_TEXTURE_PARAMETERS = ("BaseColorAlpha_Texture", "BaseColor_Texture")
TINT_PARAMETER = "BaseColor_TintColorParam"
# 隙間・裏側を黒で塞ぐ原本の特殊材質（例：ボンネット裏・エンジンルームの backfacinggeo＝
# specialcase/blackhole.materialbin、car_blackhole）。パラメーターもTextureも持たない。
# 外部製品（参照のみ）：参照製品 car_model_renderer.cpp は blackhole/blackframe を
# kBlackExteriorColor（線形0.008前後）、参照製品 native-material.mjs は 'dark' として扱う。
BLACK_SPECIAL_FAMILIES = frozenset({"car_blackhole"})
# ナンバープレート（地・文字）のShader系統と、地の色のパラメーター（MatI→MaterialBin→DFPR）。
LICENSE_PLATE_FAMILIES = frozenset({"retro_licenseplate_base", "retro_licenseplate_atlas"})
PLATE_COLOR_PARAMETER = "RetroDiffuseColorParam"
# 原本のガラスShader系統（car_glass、car_glass_detailed等）。
# car_lens（プロジェクターレンズ、glass_projectorlens_ch1）は反射マップで描く不透明に近いレンズで、
# 半透明のガラスにすると奥の車体（ペイントの柄）が透けて見えるため含めない（ALF_4C_14で確認）。
GLASS_FAMILY_PREFIX = ("car_glass", "car_window")
GLASS_COLOR_PARAMETER = "GlassColorColorParam"
BLACK_SPECIAL_MATERIALS = ("specialcase/blackhole.materialbin", "specialcase/blackframe.materialbin")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _glb_json(path: Path) -> dict:
    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) < 20 or header[:4] != b"glTF":
            raise ValueError("車体GLBの形式が不正です")
        length, kind = struct.unpack_from("<I4s", header, 12)
        if kind != b"JSON":
            raise ValueError("車体GLBのJSONチャンクがありません")
        return json.loads(handle.read(length))


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


_SRGB_TABLE = None


def _srgb_to_linear_table():
    """8 ビットの値（0〜255）ごとの線形の値の表。画素ごとに計算せず、度数分布との積で平均を求める。"""
    global _SRGB_TABLE
    if _SRGB_TABLE is None:
        import numpy as np
        _SRGB_TABLE = np.array([_srgb_to_linear(value / 255.0) for value in range(256)], dtype=np.float64)
    return _SRGB_TABLE


def _linear_to_srgb(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


class _TextureReader:
    """車両用 cars/_library/Textures.zip だけを開いたまま読む（材質ごとに開き直さない）。

    material_runtime._texture_source と同じく、Game:/Media/cars/_library/textures/ の参照は
    cars/_library/Textures.zip だけから読み、同名の汎用 media/_library/Textures.zip で代用しない。
    """

    PREFIX = "media/cars/_library/textures/"

    def __init__(self, content_root: Path, vehicle_archive: zipfile.ZipFile | None = None,
                 vehicle_stem: str = ""):
        self.content_root = content_root
        self.archive: zipfile.ZipFile | None = None
        self.means: dict[str, list[float] | None] = {}
        self.alpha_means: dict[str, tuple[list[float], float] | None] = {}
        # 車種固有のTexture（Game:/Media/cars/<車名>/textures/...）はその車の原本ZIPの中にある
        # （例：ALF_4C_14 の内装ラベル）。参照の車名が開いている車両ZIPと一致する場合だけ読む。
        self.vehicle_archive = vehicle_archive
        self.vehicle_prefix = f"media/cars/{vehicle_stem.casefold()}/" if vehicle_stem else ""
        self.vehicle_index = ({name.replace("\\", "/").casefold(): name for name in vehicle_archive.namelist()}
                              if vehicle_archive is not None else {})
        # 共有の部品（例：他の車の _library のペダル）は、別の車の車種固有 Texture を参照することがある
        # （Game:/Media/cars/<別の車>/textures/...）。参照の車名と同じ名前の原本ZIPがあれば、読み取り専用で開く。
        self.other_archives: dict[str, tuple[zipfile.ZipFile, dict[str, str]] | None] = {}

    def _member(self, game_ref: str) -> tuple | None:
        """原本の参照を ("file", パス) か ("zip", ZipFile, 項目の名前) にする。無ければ None。"""
        relative = _safe_game_asset_relative(game_ref)
        direct = self.content_root / Path(relative)
        if _scoped_is_file(direct):  # 準備の範囲の中では、同じ場所の有無を覚える（無いはずの直接のファイル）
            return ("file", direct)
        folded = relative.replace("\\", "/").casefold()
        if self.vehicle_prefix and folded.startswith(self.vehicle_prefix):
            member = self.vehicle_index.get(folded[len(self.vehicle_prefix):])
            return ("zip", self.vehicle_archive, member) if member else None
        parts = folded.split("/")
        if len(parts) >= 4 and parts[0] == "media" and parts[1] == "cars" and parts[2] != "_library":
            other = self._other_archive(parts[2])
            if other is None:
                return None
            archive, index = other
            member = index.get("/".join(parts[3:]))
            return ("zip", archive, member) if member else None
        if not relative.casefold().startswith(self.PREFIX):
            return None
        member = relative[len(self.PREFIX):]
        _strict_scoped_zip_member_path_only(member)
        if self.archive is None:
            path = self.content_root / "media" / "cars" / "_library" / "Textures.zip"
            if not path.is_file():
                return None
            self.archive = zipfile.ZipFile(path)
        found = _strict_scoped_zip_member(self.archive, member)
        return ("zip", self.archive, found) if found else None

    def read(self, game_ref: str) -> bytes | None:
        found = self._member(game_ref)
        if found is None:
            return None
        if found[0] == "file":
            return found[1].read_bytes()
        return found[1].read(found[2])

    def locate(self, game_ref: str) -> dict | None:
        """原本の参照の、ファイルか ZIP の中の位置（先頭からの位置・圧縮の方式・大きさ）。BC7 のまま渡す画像を、
        Viewer のサーバーが ZIP を開かずに直接読むため（2026-11-20）。無ければ None。"""
        found = self._member(game_ref)
        if found is None:
            return None
        if found[0] == "file":
            return {"file": str(Path(found[1]).resolve())}
        archive, member = found[1], found[2]
        info = archive.getinfo(member)
        return {"archive": str(Path(archive.filename).resolve()), "offset": int(info.header_offset),
                "method": int(info.compress_type), "compressed": int(info.compress_size),
                "size": int(info.file_size)}

    def _other_archive(self, car_folder: str) -> tuple[zipfile.ZipFile, dict[str, str]] | None:
        if car_folder in self.other_archives:
            return self.other_archives[car_folder]
        found = None
        cars = self.content_root / "media" / "cars"
        if cars.is_dir() and all(ch.isalnum() or ch in "_-" for ch in car_folder):
            matches = [path for path in cars.glob("*.zip") if path.stem.casefold() == car_folder]
            if len(matches) == 1:
                archive = zipfile.ZipFile(matches[0])
                found = (archive, {name.replace("\\", "/").casefold(): name for name in archive.namelist()})
        self.other_archives[car_folder] = found
        return found

    def close(self) -> None:
        for other in self.other_archives.values():
            if other is not None:
                other[0].close()
        self.other_archives.clear()
        if self.archive is not None:
            self.archive.close()
            self.archive = None


def _texture_mean_linear(reader: _TextureReader, game_ref: str) -> list[float] | None:
    from .fh6_swatch import decode_swatch_image

    key = game_ref.replace("\\", "/").casefold()
    if key in reader.means:
        return reader.means[key]
    data = reader.read(game_ref)
    if data is None:
        reader.means[key] = None
        return None
    image, meta = decode_swatch_image(data)
    if image is None:
        return None
    import numpy as np
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8).reshape(-1, 3)
    if not len(pixels):
        reader.means[key] = None
        return None
    table = _srgb_to_linear_table()
    reader.means[key] = [float(np.bincount(pixels[:, channel], minlength=256) @ table) / len(pixels)
                         for channel in range(3)]
    return reader.means[key]


def _shader_color_default(content_root: Path, family: str, parameter: str,
                          cache: dict[tuple[str, str], list[float] | None]) -> list[float] | None:
    """原本ShaderBin DFPR（2.1）の色（Vec4/Color、型0/1）の既定値。MatI・親MaterialBinに値が無いとき使う。

    記録の形式はタイヤの読取（source_tire_shader_binding._shader_dfpr_defaults）と同じ：
    版(2)・ID(4)・追加フラグ(1)[＋4]・型(1)・GUID(16)・値。未知の型があれば読まない（推測しない）。
    """
    import zlib
    from .source_tire_shader_binding import _length7, _take

    key = (family, parameter)
    if key in cache:
        return cache[key]
    cache[key] = None
    shaders = content_root / "media" / "cars" / "_library" / "shaders" / (family + ".zip")
    if not family or not shaders.is_file():
        return None
    with zipfile.ZipFile(shaders) as archive:
        members = [n for n in archive.namelist() if n.casefold().endswith(".shaderbin")]
        if len(members) != 1:
            return None
        shader = archive.read(members[0])
    dfpr = [b for b in wm._parse_blobs(shader) if b.tag == 0x44465052 and (b.major, b.minor) == (2, 1)]
    if len(dfpr) != 1:
        return None
    raw = bytes(dfpr[0].data)
    target = zlib.crc32(parameter.encode("ascii"))
    try:
        count_bytes, pos = _take(raw, 0, 2)
        for _ in range(struct.unpack("<H", count_bytes)[0]):
            version, pos = _take(raw, pos, 2)
            if version[0] != 3:
                return None
            crc_bytes, pos = _take(raw, pos, 4)
            extra, pos = _take(raw, pos, 1)
            if extra[0]:
                _, pos = _take(raw, pos, 4)
            kind_bytes, pos = _take(raw, pos, 1)
            kind = kind_bytes[0]
            _, pos = _take(raw, pos, 16)
            if kind in (0, 1, 5, 7, 12):
                value, pos = _take(raw, pos, 16)
                if kind in (0, 1) and struct.unpack("<I", crc_bytes)[0] == target:
                    cache[key] = list(struct.unpack("<4f", value))
                    return cache[key]
            elif kind in (2, 3, 4):
                _, pos = _take(raw, pos, 4)
            elif kind == 11:
                _, pos = _take(raw, pos, 8)
            elif kind == 8:
                entries, pos = _take(raw, pos, 4)
                _, pos = _take(raw, pos, 4 * struct.unpack("<I", entries)[0])
            elif kind == 6:
                length, pos = _length7(raw, pos)
                _, pos = _take(raw, pos, length + 4)
            else:
                return None
    except Exception:  # noqa: BLE001  形式が読めなければ既定値を使わない
        return None
    return None


def _read_parameters_tolerant(raw: bytes) -> list[dict]:
    """MTPRの値を読む。Texture2Dの参照は読み飛ばし、参照先の範囲は検査しない（値として使わない）。

    タイヤ用の厳密な読取（source_tire_shader_binding._read_parameters）は、Texture2Dの参照が
    cars/_library/textures 以外だと停止する。ランプの発光部（car_standard_emissive）は光り方の
    Textureを車種や汎用ライブラリから参照するため、色合い（BaseColor_TintColorParam）まで読めなかった。
    ここでは色・数値だけを使い、Textureの参照は使わない。未知の型は停止する（推測しない）。
    """
    from .source_tire_shader_binding import _length7, _take

    count = raw[0] if raw else 0
    pos = 1
    rows = []
    for _ in range(count):
        header, pos = _take(raw, pos, 6)
        major, minor, key = header[0], header[1], struct.unpack_from('<I', header, 2)[0]
        if not 1 <= major <= 4:
            raise ValueError('MTPRの版が不正')
        if major > 3 or (major == 3 and minor >= 1):
            present, pos = _take(raw, pos, 1)
            if present[0]:
                _, pos = _take(raw, pos, 4)
        type_byte, pos = _take(raw, pos, 1)
        typ = type_byte[0]
        if major >= 3:
            _, pos = _take(raw, pos, 16)
        value = None
        if typ in (0, 1, 5, 9, 12):
            # 型12は3成分ベクトル（例：car_glass_detailed の BentAngleVector3）で、浮動小数4つ・16バイト。
            # 実原本で直後が次の記録の版（03 04）から始まることを確認。DFPRの読取も型12を16バイトとする。
            chunk, pos = _take(raw, pos, 16)
            value = list(struct.unpack('<4f', chunk))
        elif typ in (2, 3, 4):
            chunk, pos = _take(raw, pos, 4)
            value = struct.unpack('<f', chunk)[0] if typ == 2 else struct.unpack('<i', chunk)[0]
        elif typ == 6:
            length, pos = _length7(raw, pos)
            _, pos = _take(raw, pos, length)
            if major >= 2:
                _, pos = _take(raw, pos, 4)
        elif typ == 7:
            _, pos = _take(raw, pos, 8)
            if major > 1 or (major == 1 and minor >= 1):
                _, pos = _take(raw, pos, 4)
        elif typ == 11:
            chunk, pos = _take(raw, pos, 8)
            value = list(struct.unpack('<ff', chunk))
            if major == 1:
                _, pos = _take(raw, pos, 8)
        elif typ == 8:
            chunk, pos = _take(raw, pos, 4)
            _, pos = _take(raw, pos, 16 * struct.unpack('<I', chunk)[0])
        else:
            raise ValueError('未知のShaderパラメータ型: ' + str(typ))
        rows.append({'parameter_crc32': f'{key:08x}', 'type': typ, 'value': value})
    return rows


def _layer_overrides_tolerant(effective: dict, names: dict[str, str], blobs: list[bytes]) -> int:
    """wheel_default_paint._layer_overrides と同じ重ね方（親MaterialBin→MatI）で、色・数値だけを重ねる。"""
    count = 0
    for blob in blobs:
        for row in _read_parameters_tolerant(blob):
            name = names.get(row['parameter_crc32'])
            kind, value = row['type'], row['value']
            if not name or kind == 6 or value is None:
                continue
            if kind == 3:
                value = bool(value)
            elif kind in (0, 1, 11, 12):
                value = [float(v) for v in value]
            effective[name] = {'value': value}
            count += 1
    return count


def _texture_rgba_means(reader: _TextureReader, game_ref: str) -> tuple[list[float], float] | None:
    """Textureの平均（線形RGB、透明度で重み付け）と平均の不透明度。"""
    import io
    from .fh6_swatch import read_swatch_surface, _dx10_dds

    key = game_ref.replace("\\", "/").casefold()
    if key in reader.alpha_means:
        return reader.alpha_means[key]
    reader.alpha_means[key] = None
    data = reader.read(game_ref)
    if data is None:
        return None
    from PIL import Image
    surface = read_swatch_surface(data)
    pixels = surface.pop("pixels", None)
    dxgi = {0: 80, 3: 80, 4: 81, 9: 98, 13: 28}.get(int(surface.get("encoding") or -1))
    if not surface.get("supported_bundle") or not pixels or dxgi is None or int(surface.get("tiled_flag") or 0):
        return None
    try:
        with Image.open(io.BytesIO(_dx10_dds(int(surface["width"]), int(surface["height"]), pixels, dxgi))) as opened:
            import numpy as np
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    except Exception:  # noqa: BLE001
        return None
    if not len(rgba):
        return None
    weight = int(rgba[:, 3].sum(dtype=np.int64)) / 255.0
    opacity = weight / len(rgba)
    if weight <= 0:
        return None
    table = _srgb_to_linear_table()
    alpha = rgba[:, 3].astype(np.float64) / 255.0
    mean = [float(table[rgba[:, c]] @ alpha) / weight for c in range(3)]
    reader.alpha_means[key] = (mean, opacity)
    return reader.alpha_means[key]


TEXTURE_MAX_SIZE = 512
# ベースカラーの BC7 の画像は、PNG にせず、ゲームの BC7（ミップ付き）のまま GPU へ渡す（2026-11-20、FH6 に近づける
# 案 ①）。名前は原本の SHA-256 と .bc7 で、ファイルは書かない（サーバーが原本から読む）。一番上の段の色は PNG と
# 同じ（BC7 の復号は規格どおり。透明度は不透明の材質では効かない）。ミップはゲームのもの。
BC7_PASSTHROUGH_SUFFIX = ".bc7"
_BC7_ENCODING = 9


def bc7_chain_bytes(width: int, height: int) -> int:
    """BC7 の 1×1 までの全段の大きさ（4×4 の塊ごとに 16 バイト）。"""
    total, w, h = 0, int(width), int(height)
    while True:
        total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        if w == 1 and h == 1:
            return total
        w, h = max(1, w // 2), max(1, h // 2)


def bc7_passthrough_surface(data: bytes) -> tuple[int, int, bytes] | None:
    """BC7 のまま渡せる画像なら（幅, 高さ, 全段の画素）。BC7 でない・並べ替えあり・大きすぎ・段が欠けていれば None。"""
    from .fh6_swatch import read_swatch_surface
    surface = read_swatch_surface(data)
    pixels = surface.get("pixels")
    if (not surface.get("supported_bundle") or not pixels or int(surface.get("tiled_flag") or 0)
            or int(surface.get("encoding") if surface.get("encoding") is not None else -1) != _BC7_ENCODING):
        return None
    width, height = int(surface.get("width") or 0), int(surface.get("height") or 0)
    if width < 1 or height < 1 or max(width, height) > TEXTURE_MAX_SIZE:
        return None
    if len(pixels) != bc7_chain_bytes(width, height):
        return None
    return width, height, bytes(pixels)


def _export_texture_png(reader: _TextureReader, game_ref: str, output_dir: Path | None) -> str | None:
    """原本のベースカラーTextureをPNG（最大512px、sRGBのまま）で書き出し、ファイル名（原本SHA256）を返す。"""
    if output_dir is None:
        return None
    from .fh6_swatch import decode_swatch_image

    data = reader.read(game_ref)
    if data is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    name = digest + ".png"
    target = output_dir / name
    if bc7_passthrough_surface(data) is not None:
        # 透明度は見ない：この画像（ベースカラー）を貼る材質は、Viewer では常に不透明で描く（透明にするのは
        # ラベルの記録だけで、ラベルは下の PNG の書き出し）。不透明の材質では、画像の透明度は描く色に効かない
        # （Three.js は不透明の材質の透明度を 1 にする。PNG も透明度を捨てていた）。
        # 以前の版が書いた同じ画像の PNG は、もう使わないので消す（参照する古い解析は作り直される）
        try:
            if target.is_file() and not target.is_symlink():
                target.unlink()
        except OSError:
            pass
        return digest + BC7_PASSTHROUGH_SUFFIX
    if target.is_file():
        return name
    image, _meta = decode_swatch_image(data)
    if image is None:
        return None
    image = image.convert("RGB")
    if max(image.size) > TEXTURE_MAX_SIZE:
        from PIL import Image
        scale = TEXTURE_MAX_SIZE / max(image.size)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.LANCZOS)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".png.tmp")
    image.save(temporary, format="PNG")
    temporary.replace(target)
    return name


LABEL_TEXTURE_MAX_SIZE = 1024


def _export_label_texture_png(reader: _TextureReader, base_ref: str | None, alpha_ref: str | None,
                              override_linear: list[float] | None, output_dir: Path | None) -> str | None:
    """ラベルの記号を RGBA の PNG（最大1024px）で書き出し、ファイル名（入力の SHA256）を返す。

    色：上書きの色（BaseColor_OverrideColorParam、線形→sRGB）があればその色、無ければ BaseColorAlpha_Texture の色。
    透明度：BaseColorAlpha_Texture の α × Alpha_Texture（1チャンネル）。どちらかが無ければ有る方だけを使う。
    """
    if output_dir is None or (base_ref is None and alpha_ref is None):
        return None
    from PIL import Image

    from .fh6_swatch import decode_swatch_image

    base_data = reader.read(base_ref) if base_ref else None
    alpha_data = reader.read(alpha_ref) if alpha_ref else None
    if base_data is None and alpha_data is None:
        return None
    key = hashlib.sha256()
    for part in (base_data or b"", b"|", alpha_data or b"", b"|", repr(override_linear).encode("ascii")):
        key.update(part)
    name = key.hexdigest() + ".png"
    target = output_dir / name
    if target.is_file():
        return name
    base = decode_swatch_image(base_data, mode="RGBA")[0] if base_data is not None else None
    alpha = decode_swatch_image(alpha_data)[0] if alpha_data is not None else None
    if base is None and alpha is None:
        return None
    sizes = [image.size for image in (base, alpha) if image is not None]
    width, height = max(s[0] for s in sizes), max(s[1] for s in sizes)
    if max(width, height) > LABEL_TEXTURE_MAX_SIZE:
        scale = LABEL_TEXTURE_MAX_SIZE / max(width, height)
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
    base = (base.convert("RGBA").resize((width, height), Image.LANCZOS) if base is not None
            else Image.new("RGBA", (width, height), (255, 255, 255, 255)))
    red, green, blue, base_alpha = base.split()
    if override_linear is not None:
        rgb = tuple(round(_linear_to_srgb(min(1.0, max(0.0, float(v)))) * 255) for v in override_linear[:3])
        red, green, blue = (Image.new("L", (width, height), value) for value in rgb)
    if alpha is not None:
        mask = alpha.convert("RGB").split()[0].resize((width, height), Image.LANCZOS)
        from PIL import ImageChops
        base_alpha = ImageChops.multiply(base_alpha, mask)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".png.tmp")
    Image.merge("RGBA", (red, green, blue, base_alpha)).save(temporary, format="PNG")
    temporary.replace(target)
    return name


def _parameter_rgb(effective: dict, name: str) -> list[float] | None:
    value = (effective.get(name) or {}).get("value")
    if isinstance(value, list) and len(value) >= 3 and all(isinstance(v, (int, float)) for v in value[:3]):
        return [max(0.0, float(v)) for v in value[:3]]
    return None


def _hex_from_linear(rgb: list[float]) -> str:
    return "#" + "".join(f"{round(_linear_to_srgb(v) * 255):02x}" for v in rgb) + "ff"


def _base_color_texture(runtime: dict) -> str | None:
    for wanted in BASE_COLOR_TEXTURE_PARAMETERS:
        for row in runtime.get("material_texture_bindings") or []:
            if row.get("parameter_name") == wanted and row.get("path"):
                return str(row["path"])
    return None


# 車両ZIPの同じ項目（ModelBin）の解読を、準備の間（shared_archive_reads の中）だけ使い回す（2026-11-19）。
# 部品の色の解析は材質ごとに _resolve を呼び、そのたびに同じ数 MB の ModelBin を読み出して解凍し、解読し直していた
# （1 台で 100〜400 回）。メモリの ZIP（ファイル名の無いもの）は覚えない。


def _member_blobs(archive: zipfile.ZipFile, member: str) -> list:
    """ModelBin の解読。shared_archive_reads の中（準備の間）では、同じ ZIP のファイル・同じ項目の結果を使い回す。

    呼び出し側は結果の一覧から新しい一覧を作るだけで、覚えた一覧を変えない。
    """
    filename = getattr(archive, "filename", None)
    if not (isinstance(filename, str) and filename):
        return wm._parse_blobs(archive.read(member))
    return scoped_memo("modelbin_blobs", (str(Path(filename).absolute()), member),
                       lambda: wm._parse_blobs(archive.read(member)))


def _resolve(archive: zipfile.ZipFile, index: dict[str, str], entry: str, material_id: int,
             mati_sha: str, content_root: Path, vehicle_archive: Path,
             reader: _TextureReader,
             shader_defaults: dict | None = None,
             texture_output_dir: Path | None = None) -> tuple[dict | None, str]:
    member = index.get(entry.replace("\\", "/").casefold())
    if member is None:
        return None, "source-modelbin-not-in-vehicle-archive"
    blobs = [b for b in _member_blobs(archive, member)
             if b.tag == 0x4D617449 and b.identifier == material_id]
    if len(blobs) != 1:
        return None, "source-mati-missing-or-ambiguous"
    data = bytes(blobs[0].data)
    if _sha(data) != mati_sha:
        return None, "source-mati-sha-mismatch"
    runtime = inspect_embedded_material_instance_runtime(
        content_root, data, material_label=str(material_id), vehicle_archive=vehicle_archive,
        include_texture_assets=False)
    if not runtime.get("available"):
        return None, "material-runtime-unavailable"
    family = str(runtime.get("shader_family") or "")
    effective = dict(runtime.get("effective_focus") or {})
    try:
        names = _shader_parameter_names(content_root, family)
        base_data, _ = _material_source(
            content_root, str(runtime.get("resolved_material_path") or ""), vehicle_archive)
        blobs = _mtpr_blobs(base_data) + _mtpr_blobs(data)
        layered = dict(effective)
        try:
            _layer_overrides(layered, names, blobs)
        except Exception as exc:  # noqa: BLE001
            # Textureの参照範囲、または型12（3成分ベクトル）だけが理由なら、色・数値だけを重ねる読取でやり直す。
            if "scope外" not in str(exc) and "パラメータ型: 12" not in str(exc):
                raise
            layered = dict(effective)
            _layer_overrides_tolerant(layered, names, blobs)
        effective = layered
    except Exception:  # noqa: BLE001  原本の読取に失敗したら補わない（推測しない）
        if not family.startswith(GLASS_FAMILY_PREFIX):
            return None, "material-parameter-layering-failed"
    if family.startswith(GLASS_FAMILY_PREFIX):
        # ランプのカバー等のガラス（GLBの役割はtrim）。ガラスの色合いは GlassColorColorParam（線形、
        # MatI→親MaterialBin→ShaderBin DFPR）。型12（3成分ベクトル）を読めるようになり取得できた
        # （例：NIS_SilviaKs_94 のテールランプのガラス 0.871,0.003,0.003＝赤、ヘッドランプは白）。
        glass = (effective.get(GLASS_COLOR_PARAMETER) or {}).get("value")
        if glass is None:
            glass = _shader_color_default(content_root, family, GLASS_COLOR_PARAMETER,
                                          shader_defaults if shader_defaults is not None else {})
        glass_hex = None
        if isinstance(glass, list) and len(glass) >= 3 and all(isinstance(v, (int, float)) for v in glass[:3]):
            glass_hex = "#" + "".join(
                f"{round(_linear_to_srgb(max(0.0, float(v))) * 255):02x}" for v in glass[:3]) + "ff"
        return {
            "surface": "glass",
            "color_origin": ORIGIN,
            "shader_family": family,
            "material_path": str(runtime.get("resolved_material_path") or ""),
            "source_material_instance_sha256": mati_sha,
            "source_modelbin": entry,
            "source_material_id": material_id,
            "glass_rgba_hex": glass_hex,
            "glass_color_linear": [float(v) for v in glass[:3]] if glass_hex else None,
            "method": "original-glass-shader-family",
        }, ""
    record = {
        "color_origin": ORIGIN,
        # 発光部（car_standard_emissive等）。ランプの部品ではViewerが従来のレンズ用プロファイルを保つ
        # （テールランプの赤は色付きガラスの色合い＝MTPR型12にあり未解読。発光色は白・暖白）。
        "emissive": family.endswith("_emissive"),
        "shader_family": family,
        "material_path": str(runtime.get("resolved_material_path") or ""),
        "source_material_instance_sha256": mati_sha,
        "source_modelbin": entry,
        "source_material_id": material_id,
    }
    material_path = str(runtime.get("resolved_material_path") or "").replace("\\", "/").casefold()
    if family in BLACK_SPECIAL_FAMILIES or material_path.endswith(BLACK_SPECIAL_MATERIALS):
        record.update({"rgba_hex": "#000000ff", "method": "special-black-material"})
        return record, ""
    if family == "car_label":
        # 内装の記号・計器の針などのラベル。上書きの色（BaseColorOverrideSwitchBool）があればその色、
        # 無ければベースカラーTextureを透明度で重み付けした平均色。ラベルは透明部分の多い記号なので、
        # 平均の不透明度（Alpha_Texture、無ければベースカラーTextureのα）で半透明に描く。
        override = (effective.get("BaseColorOverrideSwitchBool") or {}).get("value") is True
        textures = {row.get("parameter_name"): str(row.get("path"))
                    for row in runtime.get("material_texture_bindings") or [] if row.get("path")}
        color = _parameter_rgb(effective, "BaseColor_OverrideColorParam") if override else None
        override_color = color  # 原本の上書きの色（Texture の平均で補ったものは含めない）
        base = _texture_rgba_means(reader, textures["BaseColorAlpha_Texture"]) if "BaseColorAlpha_Texture" in textures else None
        alpha = _texture_rgba_means(reader, textures["Alpha_Texture"]) if "Alpha_Texture" in textures else None
        if color is None and base is not None:
            color = base[0]
        if color is None:
            return None, "label-color-unavailable"
        # 不透明度：Alpha_Textureの輝度の平均（白一色なら1）× ベースカラーTextureのα平均。
        opacity = 1.0
        if alpha is not None:
            opacity *= sum(alpha[0]) / 3.0 * alpha[1]
        if base is not None:
            opacity *= base[1]
        record.update({"rgba_hex": _hex_from_linear(color), "method": "label-texture-alpha-weighted",
                       "opacity": round(max(0.05, min(1.0, opacity)), 3),
                       "approximation": "label-symbols-averaged"})
        # 記号そのものを貼るための RGBA の Texture（色は上書きの色か BaseColorAlpha、透明度は両 Texture）。
        # UV は材質の UVChoice_OnCh1_OffCh2Bool（実原本の全ラベルで真＝CH1＝GLBのTEXCOORD_0）。
        # 平均色と不透明度は従来どおり残し、Texture を読めない場合は Viewer がそれで描く。
        choice = (effective.get("UVChoice_OnCh1_OffCh2Bool") or {}).get("value")
        texture_file = (_export_label_texture_png(
            reader, textures.get("BaseColorAlpha_Texture"), textures.get("Alpha_Texture"),
            override_color, texture_output_dir) if isinstance(choice, bool) else None)
        if texture_file:
            record["texture"] = {"file": texture_file, "uv_channel": 0 if choice else 1, "repeat": [1.0, 1.0],
                                 "tint_rgba_hex": "#ffffffff", "alpha": True}
            record["approximation"] = None
        return record, ""
    if family.startswith("car_carbonfiber"):
        # カーボン：織り目の2色（WeaveColorTintA/B、MatI→MaterialBin→DFPR）の平均。織り目は描かない。
        tints = []
        for name in ("WeaveColorTintAColorParam", "WeaveColorTintBColorParam"):
            value = _parameter_rgb(effective, name) or _shader_color_default(
                content_root, family, name, shader_defaults if shader_defaults is not None else {})
            if value:
                tints.append([max(0.0, float(v)) for v in value[:3]])
        if not tints:
            return None, "carbon-weave-color-unavailable"
        mean = [sum(t[c] for t in tints) / len(tints) for c in range(3)]
        record.update({"rgba_hex": _hex_from_linear(mean), "method": "carbon-weave-tint-mean",
                       "approximation": "carbon-weave-not-drawn"})
        return record, ""
    if family == "car_reflector":
        color = _parameter_rgb(effective, "BaseColorColorParam") or _shader_color_default(
            content_root, family, "BaseColorColorParam", shader_defaults if shader_defaults is not None else {})
        if color:
            record.update({"rgba_hex": _hex_from_linear([max(0.0, float(v)) for v in color[:3]]),
                           "method": "reflector-base-color"})
            return record, ""
        return None, "reflector-color-unavailable"
    if family in LICENSE_PLATE_FAMILIES:
        # ナンバープレートの地の色（RetroDiffuseColorParam、線形）。文字（CH1MaskTextureの型抜き）は描かない。
        retro = (effective.get(PLATE_COLOR_PARAMETER) or {}).get("value")
        if retro is None:
            retro = _shader_color_default(content_root, family, PLATE_COLOR_PARAMETER,
                                          shader_defaults if shader_defaults is not None else {})
        if isinstance(retro, list) and len(retro) >= 3 and all(isinstance(v, (int, float)) for v in retro[:3]):
            rgb = "".join(f"{round(_linear_to_srgb(max(0.0, float(v))) * 255):02x}" for v in retro[:3])
            record.update({"rgba_hex": f"#{rgb}ff", "method": "license-plate-retro-diffuse",
                           "approximation": "plate-characters-not-drawn"})
            return record, ""
        return None, "license-plate-color-unavailable"
    paint = material_defined_paint_color(effective, family)
    if paint.get("available") and paint.get("rgba_hex"):
        record.update({"rgba_hex": str(paint["rgba_hex"]).lower(), "method": "material-paint-color"})
        return record, ""
    tint = (effective.get(TINT_PARAMETER) or {}).get("value")
    tint_source = "material-instance-or-materialbin"
    if tint is None and _base_color_texture(runtime):
        # MatI・親MaterialBinに色合いが無い場合は、ShaderBin DFPRの既定値（MatI→MaterialBin→DFPR）。
        tint = _shader_color_default(content_root, family, TINT_PARAMETER,
                                     shader_defaults if shader_defaults is not None else {})
        tint_source = "shaderbin-dfpr-default"
    if not isinstance(tint, list) or len(tint) < 3 or not all(isinstance(v, (int, float)) for v in tint[:3]):
        return None, "no-base-color-tint"
    texture_ref = _base_color_texture(runtime)
    mean = None
    if texture_ref:
        try:
            mean = _texture_mean_linear(reader, texture_ref)
        except (OSError, ValueError, KeyError):
            mean = None
    if mean is None:
        return None, "base-color-texture-unavailable"
    linear = [max(0.0, float(tint[i])) * mean[i] for i in range(3)]
    rgb = "".join(f"{round(_linear_to_srgb(v) * 255):02x}" for v in linear)
    # 原本のベースカラーTextureそのものを貼るための情報。UVは材質の UVChoice_OnCh1_OffCh2Bool
    # （CH1＝GLBのTEXCOORD_0、CH2＝TEXCOORD_1。実原本で _ch1 材質のTEXCOORD_0が0〜1の固有UV、
    # 繰り返し材質のTEXCOORD_1がメートル単位の広い範囲であることを確認）。繰り返し回数は
    # OverrideBaseColorTiling_Value が真なら BaseColorTilingOverrideVector2、無ければ1。
    # 平均色（rgba_hex）は従来どおり残し、Textureを読めない場合はViewerが平均色で描く。
    choice = (effective.get("UVChoice_OnCh1_OffCh2Bool") or {}).get("value")
    texture_file = (_export_texture_png(reader, texture_ref, texture_output_dir)
                    if isinstance(choice, bool) and texture_ref else None)
    if texture_file:
        repeat = [1.0, 1.0]
        if (effective.get("OverrideBaseColorTiling_Value") or {}).get("value") is True:
            tiling = (effective.get("BaseColorTilingOverrideVector2") or {}).get("value")
            if (isinstance(tiling, list) and len(tiling) >= 2
                    and all(isinstance(v, (int, float)) and 1e-4 <= abs(v) <= 1024 for v in tiling[:2])):
                repeat = [float(tiling[0]), float(tiling[1])]
        record["texture"] = {
            "file": texture_file,
            "uv_channel": 0 if choice else 1,
            "repeat": repeat,
            "tint_rgba_hex": "#" + "".join(
                f"{round(_linear_to_srgb(min(1.0, max(0.0, float(tint[i])))) * 255):02x}" for i in range(3)) + "ff",
        }
        if texture_file.endswith(BC7_PASSTHROUGH_SUFFIX):
            # BC7 のまま渡す画像の、ゲームの ZIP の中の位置（サーバーが直接読む。名前の SHA-256 で確かめる）
            location = reader.locate(texture_ref)
            if location is not None:
                record["texture"]["source_location"] = location
    record.update({
        "rgba_hex": f"#{rgb}ff",
        "method": "tint-times-base-color-texture-mean",
        "tint_linear": [float(v) for v in tint[:3]],
        "tint_source": tint_source,
        "base_color_texture": texture_ref,
        "base_color_texture_mean_linear": [round(v, 6) for v in mean],
    })
    return record, ""


def build_body_trim_colors(mesh_path: Path | str, *, content_root: Path | str,
                           vehicle_archive: Path | str, texture_output_dir: Path | str | None = None) -> dict:
    """車体GLBの中立色の部品について、原本MatIの色をMatIのSHAごとに返す。"""
    mesh_path, content_root, vehicle_archive = Path(mesh_path), Path(content_root), Path(vehicle_archive)
    document = _glb_json(mesh_path)
    wanted: dict[str, tuple[str, int]] = {}
    for node in document.get("nodes") or []:
        extras = node.get("extras") or {}
        if extras.get("lo4fh6_role") not in TRIM_ROLES:
            continue
        entry = extras.get("lo4fh6_source_entry")
        material_id = extras.get("lo4fh6_original_matI_id")
        sha = extras.get("lo4fh6_original_material_sha256")
        if (not isinstance(entry, str) or type(material_id) is not int
                or not isinstance(sha, str) or len(sha) != 64):
            continue
        wanted.setdefault(sha.lower(), (entry, material_id))
    groups: dict[str, dict] = {}
    unresolved: dict[str, int] = {}
    shader_defaults: dict = {}
    reader = None
    try:
        # 材質ごとに Materials.zip 等を開き直さないよう、解析の間は ZIP を使い回す。
        with zipfile.ZipFile(vehicle_archive) as archive, shared_archive_reads():
            reader = _TextureReader(content_root, archive, vehicle_archive.stem)
            index = {name.replace("\\", "/").casefold(): name for name in archive.namelist()}
            for sha, (entry, material_id) in sorted(wanted.items()):
                record, reason = _resolve(archive, index, entry, material_id, sha, content_root,
                                          vehicle_archive, reader, shader_defaults,
                                          Path(texture_output_dir) if texture_output_dir else None)
                if record is None:
                    unresolved[reason] = unresolved.get(reason, 0) + 1
                    continue
                groups[sha] = record
    finally:
        if reader is not None:
            reader.close()
    return {
        "schema": SCHEMA,
        "source_glb_sha256": _sha(mesh_path.read_bytes()),
        "groups": groups,
        "counts": {"materials": len(wanted), "resolved": len(groups), "unresolved": unresolved},
        "game_shader_gpu_verified": False,
    }


# 車種ごとのキャッシュの版。結果の形や意味を変えたら上げる（ソースの変更はキーに自動で入る）。
BODY_TRIM_CACHE_REVISION = "r1-20261117-per-vehicle"
BODY_TRIM_CACHE_KIND = "body-trim-colors"
_TEXTURE_FILE = re.compile(r"[0-9a-f]{64}\.png")


def _texture_files(value: object) -> set[str]:
    """結果の中で参照している書き出し済みTextureのファイル名（原本SHA256.png）。

    辞書と一覧を辿り、名前の形に合う文字列を 1 つの集合に積む（以前は辿るたびに小さな集合を作って合わせていた。
    同じ集合になる。2026-11-20）。
    """
    found: set[str] = set()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and _TEXTURE_FILE.fullmatch(item):
            found.add(item)
    return found


def cached_body_trim_colors(mesh_path: Path | str, *, content_root: Path | str, vehicle_archive: Path | str,
                            cache_root: Path | str, texture_dir: Path | str,
                            location: dict | None = None) -> tuple[dict, bool]:
    """build_body_trim_colors の結果を車種ごとにキャッシュする（無ければ作る）。戻り値は (結果, 再利用したか)。

    入力はペイントに依存しない（車体のGLB・車両ZIP・`_library` のZIP）。Textureは原本SHA256の名前で
    texture_dir（車種をまたいで共有）に書き出す。参照するTextureが消えていれば作り直す。
    location に辞書を渡すと、結果を保存したキャッシュのファイルの場所を location["path"] に入れる
    （ペイントごとの描画の目録が、結果を写さずにこのファイルを指すため。2026-11-20）。
    """
    from .vehicle_analysis_cache import (
        analysis_cache_key, cached_analysis, file_identity, installed_library_identity, mark_used,
        module_sources_sha256,
    )
    here = Path(__file__).resolve().parent
    texture_dir = Path(texture_dir)

    def build() -> dict:
        return build_body_trim_colors(mesh_path, content_root=content_root, vehicle_archive=vehicle_archive,
                                      texture_output_dir=texture_dir)

    inputs = {
        "mesh": file_identity(mesh_path),
        "vehicle_archive": file_identity(vehicle_archive),
        "content_root": str(Path(content_root).resolve()),
        "library": installed_library_identity(content_root),
        "code": module_sources_sha256([
            here / "body_trim_default_color.py", here / "material_runtime.py", here / "wheel_default_paint.py",
            here / "wheel_morph_internal.py", here / "fh6_swatch.py"]),
    }
    if inputs["mesh"] is None or inputs["vehicle_archive"] is None:
        return build(), False

    def valid(result: dict) -> bool:
        if result.get("schema") != SCHEMA or not isinstance(result.get("groups"), dict):
            return False
        files = [texture_dir / name for name in sorted(_texture_files(result["groups"]))]
        if not all(path.is_file() for path in files):
            return False
        for path in files:
            mark_used(path)
        return True

    key = analysis_cache_key(BODY_TRIM_CACHE_KIND, BODY_TRIM_CACHE_REVISION, inputs)
    found = cached_analysis(cache_root, BODY_TRIM_CACHE_KIND, key, build, valid=valid,
                            metadata={"vehicle": Path(vehicle_archive).stem,
                                      "revision": BODY_TRIM_CACHE_REVISION, "mesh": Path(mesh_path).name})
    if location is not None:
        location["path"] = Path(cache_root) / BODY_TRIM_CACHE_KIND / f"{key}.json"
    return found
