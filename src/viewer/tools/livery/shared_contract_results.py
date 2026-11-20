"""ペイントごとの描画の目録（local-render-contract.json）に、車ごとに同じ解析の結果を写さない（2026-11-20）。

内装・トリムの色（body_trim_colors）は車ごとの解析の結果（_fh6-vehicle-cache/vehicle-analysis/<種類>/<鍵>.json）で、
ペイントに依らない。それをペイントごとの目録に丸ごと写していた（4212 で 1 件 約 400 KB。目録の約半分）。

- 書くとき（vehicle_preview）：解析の結果のファイルの中身が今の値と同じなら、目録のファイルにはそのファイルを
  指す参照（{"lo4fh6_shared_analysis": {"vehicle_cache_relative": …, "sha256": …}}）だけを書く。
- 読むとき（橋渡しのサーバーへの読み込み・準備済みの近道の判定）：参照を解析の結果に戻す。戻した値の
  SHA-256（JSON の正規の形）が書いたときと同じことを確かめる。戻せなければ None（準備をやり直す）。
  サーバーが画面に渡す目録は今までと同じ。
- 解析の結果は容量の整理でも消さない（vehicle_cache_limit の「消さないもの」）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

REF_KEY = "lo4fh6_shared_analysis"
SHARED_FIELDS = ("body_trim_colors",)


def canonical_sha256(value: Any) -> str:
    """JSON にしたときの中身の SHA-256（キーの順・空白に依らない。JSON で同じものは同じ）。"""
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    text = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_result(path: Path) -> tuple[dict, str] | None:
    """解析の結果のファイル（cached_analysis の形）の結果と、その SHA-256。同じファイルは同じプロセスで覚える。"""
    from .process_file_memo import remembered

    def compute() -> tuple[dict, str] | None:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        result = saved.get("result") if isinstance(saved, dict) else None
        if not isinstance(result, dict):
            return None
        return result, canonical_sha256(result)

    return remembered("shared-analysis-result", [path], None, compute, copy="marshal", limit=8,
                      keep=lambda value: value is not None)


def for_disk(contract: dict, sources: dict[str, Path | None], vehicle_cache_root: Path) -> dict:
    """目録のファイルに書く形。sources の項目は、解析の結果のファイルの中身が今の値と同じときだけ参照にする。"""
    out = dict(contract)
    for field, source in sources.items():
        value = contract.get(field)
        if field not in SHARED_FIELDS or source is None or not isinstance(value, dict):
            continue
        try:
            relative = Path(source).resolve().relative_to(Path(vehicle_cache_root).resolve()).as_posix()
        except (OSError, ValueError):
            continue
        saved = _read_result(Path(source))
        digest = canonical_sha256(value)
        if saved is None or saved[1] != digest:
            continue
        out[field] = {REF_KEY: {"vehicle_cache_relative": relative, "sha256": digest}}
    return out


def has_references(contract: dict) -> bool:
    return any(isinstance(contract.get(field), dict) and REF_KEY in contract[field] for field in SHARED_FIELDS)


def resolve(contract: dict, vehicle_cache_root: Path | str | None) -> dict | None:
    """参照を解析の結果に戻した目録（参照が無ければそのまま）。戻せなければ None。"""
    if not has_references(contract):
        return contract
    if not vehicle_cache_root:
        return None
    root = Path(vehicle_cache_root)
    out = dict(contract)
    for field in SHARED_FIELDS:
        value = contract.get(field)
        if not (isinstance(value, dict) and REF_KEY in value):
            continue
        reference = value[REF_KEY]
        relative = str(reference.get("vehicle_cache_relative") or "") if isinstance(reference, dict) else ""
        parts = PurePosixPath(relative).parts
        if not relative or PurePosixPath(relative).is_absolute() or ".." in parts or ":" in relative:
            return None
        saved = _read_result(root.joinpath(*parts))
        if saved is None or saved[1] != reference.get("sha256"):
            return None
        out[field] = saved[0]
    return out
