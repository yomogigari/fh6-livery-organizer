"""FH6 の SwatchBin（テクスチャ）を、確認用の画像へ復号する。

SwatchBin の構造の読み取りは fh_livery_preview_core.swatch_texture（独自実装）を使う。
"""
from __future__ import annotations

import io
import math
from pathlib import Path

from fh_livery_preview_core.swatch_texture import SwatchFormatError, dds_bytes, read_texture_surface


def read_swatch_surface(data: bytes) -> dict:
    """SwatchBin の寸法・形式・画素を辞書で返す（読み取りは fh_livery_preview_core.swatch_texture）。"""
    row = {"supported_bundle": False, "width": None, "height": None, "encoding": None,
           "pixel_bytes": None, "pixels": None, "error": None}
    try:
        surface = read_texture_surface(data)
    except Exception as exc:  # 構造の不一致・途中で切れたファイルは、理由を返して呼び出し側で判断する
        row["error"] = str(exc) if isinstance(exc, SwatchFormatError) else f"{type(exc).__name__}: {exc}"
        return row
    pixel_size = surface.pixel_size
    row.update({"supported_bundle": True, "version": list(surface.version),
                "blob_count": surface.entry_count, "width": surface.width, "height": surface.height,
                "encoding": surface.encoding, "pixel_bytes": pixel_size, "tiled_flag": surface.tiled,
                "pixel_range_valid": surface.pixels is not None, "pixels": surface.pixels})
    return row


def _dx10_dds(width: int, height: int, pixels: bytes, dxgi_format: int) -> bytes:
    return dds_bytes(width, height, pixels, dxgi_format)


# BC5 の XY から法線の RGB を作る対応表（符号つきか → (R・G の表 256, B の表 256×256)）。プロセスごとに 1 回作る。
_NORMAL_TABLES: dict[bool, tuple[bytes, bytes]] = {}


def _normal_tables(signed: bool) -> tuple[bytes, bytes]:
    """法線の対応表。画素の R・G だけで決まる値を、以前の画素ごとの式のまま 256×256 通り求めておく（2026-11-20）。

    R の表：x（R から）・y（G から）を 0〜255 にした値。B の表：r × 256 + g の位置に、正の z を 0〜255 にした値。
    """
    tables = _NORMAL_TABLES.get(signed)
    if tables is None:
        axis = [max(-1.0, min(1.0, (value - 128.0) / 127.0)) if signed else value / 127.5 - 1.0
                for value in range(256)]
        xy = bytes(int(round((v * .5 + .5) * 255)) for v in axis)
        z = bytearray(256 * 256)
        for r, x in enumerate(axis):
            row = r * 256
            for g, y in enumerate(axis):
                z[row + g] = int(round((math.sqrt(max(0.0, 1.0 - x * x - y * y)) * .5 + .5) * 255))
        tables = _NORMAL_TABLES[signed] = (xy, bytes(z))
    return tables


def _rebuild_normal_image(image, *, signed: bool):
    """BC5 の XY（R・G）から正の Z を作り直した RGB 画像。

    以前は画素ごとに Python で計算していた（1024×1024 で約 0.2 秒）。同じ式で作った対応表を、numpy で
    画素ごとに引く（結果は画素ごとに同じ。tests/viewer/test_viewer_swatch_normals.py で 256×256 通りを比べる）。
    """
    import numpy as np
    from PIL import Image
    xy, z = _normal_tables(signed)
    rgb = np.asarray(image, dtype=np.uint8)
    red = rgb[..., 0]
    green = rgb[..., 1]
    xy_table = np.frombuffer(xy, dtype=np.uint8)
    out = np.empty(rgb.shape[:2] + (3,), dtype=np.uint8)
    out[..., 0] = xy_table[red]
    out[..., 1] = xy_table[green]
    out[..., 2] = np.frombuffer(z, dtype=np.uint8)[red.astype(np.intp) * 256 + green]
    return Image.fromarray(out)


def decode_swatch_image(data: bytes, mode: str = "RGB") -> tuple[object | None, dict]:
    """SwatchBin を PIL 画像にする。mode="RGBA" なら α を残す（法線の Texture は常に RGB）。"""
    from PIL import Image
    surface = read_swatch_surface(data)
    pixels = surface.pop("pixels", None)
    meta = dict(surface)
    if not meta.get("supported_bundle") or not pixels:
        return None, meta
    if int(meta.get("tiled_flag") or 0):
        meta["decode_error"] = "tiled/Xbox swatch requires detiling"
        return None, meta
    # FH6 PC encoding IDs observed by the project tooling. Encoding 9 is BC7.
    dxgi = {0: 80, 3: 80, 4: 81, 5: 83, 6: 84, 9: 98, 13: 28}.get(int(meta["encoding"]))
    if dxgi is None:
        meta["decode_error"] = f"encoding {meta['encoding']} has no local DDS mapping"
        return None, meta
    try:
        with Image.open(io.BytesIO(_dx10_dds(int(meta["width"]), int(meta["height"]), pixels, dxgi))) as opened:
            image = opened.convert("RGBA" if mode == "RGBA" else "RGB")
        if int(meta.get("encoding") or -1) in (5, 6):
            image = _rebuild_normal_image(image.convert("RGB"), signed=int(meta.get("encoding")) == 6)
            meta["preview_semantics"] = "BC5 XY normal with reconstructed positive Z"
        else:
            meta["preview_semantics"] = "decoded texture surface"
        meta["dxgi_format"] = dxgi
        return image, meta
    except Exception as exc:
        meta["decode_error"] = f"{type(exc).__name__}: {exc}"
        return None, meta


def extract_swatch_preview_from_zip(archive: Path, member: str, output: Path) -> dict:
    """ZIP の中の Swatch を PNG に書き出す（同じ原本の PNG は同じプロセスで覚えて使い回す。derived_swatch_png）。"""
    import zipfile
    from tools.livery.material_runtime import derived_swatch_png
    result = {"archive": str(archive), "member": member, "output": str(output), "available": False}
    try:
        def load() -> bytes:
            with zipfile.ZipFile(archive) as zf:
                return zf.read(member)
        meta, png, _width, _height = derived_swatch_png(Path(archive), str(member), load, Path(output))
        result.update(meta)
        if png is None:
            return result
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png)
        result["available"] = True
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
