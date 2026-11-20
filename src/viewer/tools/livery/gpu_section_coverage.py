"""原本11面と車両MaskのGPU Paint契約の描画面対応を厳密に検査する。

FH6 C_liveryから11面すべてを正しく復号できても、車両固有の原本Maskに
対応するRenderContractの面が欠ければ、その面の図柄はWebGL2へ届かない。
描画器に入る前に漏れを明示停止する。特定車種・Liveryの例外は持たない。
"""
from __future__ import annotations

from typing import Any, Mapping


CONTRACT_TO_SOURCE_SECTION = {
    "Front": "front",
    "Back": "back",
    "Top": "top",
    "Left": "left",
    "Right": "right",
    "Spoiler": "wing",
    "FrontWindshield": "front_windscreen",
    "BackWindshield": "rear_windscreen",
    "TopWindow": "top_window",
    "LeftWindow": "left_window",
    "RightWindow": "right_window",
}


def require_gpu_source_contract_sections(
    design: Mapping[str, Any], render_contract: Mapping[str, Any]
) -> dict[str, Any]:
    """非空原本面を持つMask契約が全て存在することを保証する。

    原本の面が0図形の場合は対応するMask/UV投影を要求しない。
    複数Maskページや原本車体の違いによって非空原本面が欠ける場合は
    車種固有の代替表示をせず、欠けた面名をエラーに含める。
    """
    if not isinstance(design, Mapping) or not isinstance(render_contract, Mapping):
        raise ValueError("原本GPU契約の入力型が不正です")
    surfaces = design.get("surfaces")
    records = render_contract.get("sections")
    if not isinstance(surfaces, list) or not isinstance(records, list):
        raise ValueError("原本GPU契約の11面またはMask投影一覧が不正です")
    expected_sources = set(CONTRACT_TO_SOURCE_SECTION.values())
    if len(surfaces) != len(expected_sources):
        raise ValueError("原本GPU契約の11面に欠損・重複があります")
    source_counts: dict[str, int] = {}
    for surface in surfaces:
        if not isinstance(surface, dict) or not isinstance(surface.get("name"), str):
            raise ValueError("原本GPU契約の面名が不正です")
        name = surface["name"]
        shapes = surface.get("shapes")
        if name in source_counts or name not in expected_sources or not isinstance(shapes, list):
            raise ValueError("原本GPU契約の面名・図形配列が不正です")
        source_counts[name] = len(shapes)
    contract_names: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("section"), str):
            raise ValueError("原本GPU契約のMask投影面が不正です")
        name = record["section"]
        if name in contract_names or name not in CONTRACT_TO_SOURCE_SECTION:
            raise ValueError("原本GPU契約のMask投影面に重複・未知の面があります")
        contract_names.add(name)
    missing = [contract for contract, source in CONTRACT_TO_SOURCE_SECTION.items()
               if source_counts[source] and contract not in contract_names]
    if missing:
        raise ValueError("原本GPU図形を描画できないMask契約面があります: " + ", ".join(missing))
    active = [name for name, source in CONTRACT_TO_SOURCE_SECTION.items()
              if source_counts[source]]
    return {
        "format": "lo4fh6_gpu_source_contract_section_coverage_v1",
        "source_shape_count": sum(source_counts.values()),
        "active_source_sections": active,
        "contract_sections": [name for name in CONTRACT_TO_SOURCE_SECTION if name in contract_names],
        "missing_active_source_sections": [],
        "empty_source_sections_without_contract": [name for name, source in CONTRACT_TO_SOURCE_SECTION.items()
                                                  if not source_counts[source] and name not in contract_names],
    }
