"""ボディキットの部品の重ね合わせの GLB を用意する（2026-11-21）。

以前は、初めて開く車で、選んでいない部品も含めて全部を準備の中で変換していた（部品の多い車では
1〜3 秒。例：295 は 11 個で約 2.8 秒）。今は、準備で表示する部品だけを変換し、ほかの部品は
変換済みならそのまま使い、無ければ Viewer で選ばれたときにサーバーが変換する。
準備とサーバーの両方が、ここの同じ処理を使う（以前の準備の中の処理と同じ手順）。
"""
from __future__ import annotations

from pathlib import Path

from . import chassis_store
from .portable_mesh_converter import PortableMeshConverterError, convert_vehicle_model_to_glb, validate_local_chassis_glb

OVERLAY_SCOPE = "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"


def cached_body_kit_overlay(overlay_mesh: Path) -> dict | None:
    """変換済みで検査に通る重ね合わせの GLB があれば、検査の結果を返す。無い・壊れているなら None（壊れた物は消す）。

    しばらく使っていなければ圧縮した写しだけを残しているので（chassis_store）、先に元の場所へ戻す。
    """
    overlay_mesh = Path(overlay_mesh)
    chassis_store.prepare_for_use(overlay_mesh)
    if not overlay_mesh.is_file():
        return None
    try:
        return validate_local_chassis_glb(overlay_mesh, require_product_accepted=True,
                                          required_firstparty_scope=OVERLAY_SCOPE)
    except (OSError, PortableMeshConverterError):
        overlay_mesh.unlink(missing_ok=True)
        return None


def convert_body_kit_overlay(asset, overlay_mesh: Path, added_entries: list[str]) -> dict:
    """部品の原本のモデルから重ね合わせの GLB を作り、検査の結果を返す。"""
    overlay_mesh = Path(overlay_mesh)
    convert_vehicle_model_to_glb(asset, overlay_mesh, loose_entries=list(added_entries))
    return validate_local_chassis_glb(overlay_mesh, require_product_accepted=True,
                                      required_firstparty_scope=OVERLAY_SCOPE)


def ensure_body_kit_overlay(asset, overlay_mesh: Path, added_entries: list[str]) -> tuple[dict, bool]:
    """重ね合わせの GLB を用意する（無ければ変換する）。返す値は（検査の結果, 変換済みの物を使ったか）。"""
    validation = cached_body_kit_overlay(overlay_mesh)
    if validation is not None:
        return validation, True
    return convert_body_kit_overlay(asset, overlay_mesh, added_entries), False
