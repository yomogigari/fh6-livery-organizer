"""C_livery のペイントの記録を、塗る場所の名前（Body・Mirror・Brakes など）で引く。

記録の material_identifier は、塗る場所の名前の FNV-1a 64 ビットのハッシュ（リトルエンディアンの
8 バイト）。原本の Carbin・GLB の結び付けの値（lo4fh6_material_binding_hash）も同じ名前のハッシュ
（数値の 16 進表記）。2026-11-17 に、一括撮影の 40 車種・998 ペイントの記録の識別子 49 種類のうち
32 種類を名前と照合し（Body・Hood・Mirror・Wing・Brakes・Body_SecondaryColor など）、残りの 10 種類は
既存のホイールの塗装の表（FrontWheelPaint・RearWheelPaint）と一致した。参照製品の
material_hashes.h（参照のみ）も同じ値を持つ（kMirrorPaint＝Mirror、kBrakeCaliper＝Brakes 等）。
"""
from __future__ import annotations

from typing import Any

FNV64_OFFSET = 0xCBF29CE484222325
FNV64_PRIME = 0x100000001B3

# 描画に使う塗る場所。Body は車体の地の色、Mirror はドアミラーのカバー、Brakes はキャリパー。
NAMED_PAINT_GROUPS = ("Body", "Hood", "Mirror", "Wing", "Brakes")


def paint_group_hash(name: str) -> int:
    """塗る場所の名前の FNV-1a 64 ビットのハッシュ。"""
    value = FNV64_OFFSET
    for byte in name.encode("utf-8"):
        value = ((value ^ byte) * FNV64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def paint_group_identifier_hex(name: str) -> str:
    """C_livery の記録の material_identifier_hex の表記（リトルエンディアンの 8 バイト）。"""
    return paint_group_hash(name).to_bytes(8, "little").hex()


def paint_group_binding_hex(name: str) -> str:
    """GLB の lo4fh6_material_binding_hash の表記（数値の 16 進、大文字 16 桁）。"""
    return f"{paint_group_hash(name):016X}"


def named_paint_group_cluster(diagnostics: dict, name: str) -> dict:
    """ペイントの記録の集まり（paint-finish-candidate-diagnostics）から、その名前の記録を含む集まりを返す。

    集まりは同じ値（仕上げ・色・メーカー指定色）の記録をまとめたものなので、その名前の記録の値と同じ。
    見つからなければ空の dict。
    """
    wanted = paint_group_identifier_hex(name)
    for key in ("non_panel_clusters", "panel_clusters"):
        for cluster in diagnostics.get(key) or []:
            identifiers = [str(value).lower() for value in cluster.get("material_identifiers") or []]
            if wanted in identifiers:
                result: dict[str, Any] = dict(cluster)
                result["paint_group"] = name
                result["paint_group_identifier_hex"] = wanted
                return result
    return {}
