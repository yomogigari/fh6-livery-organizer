"""準備のキャッシュ（ペイントごとの準備のフォルダーと、車種ごとの _fh6-vehicle-cache）の容量の上限。

- 既定では何も消さない。共有の設定 vehicle_cache_limit_gb に正の数があるときだけ、表示の準備の後に
  上限の 90% を超えていれば 75% まで消す（vehicle_analysis_cache.plan_eviction、2026-11-17 に承認の方針）。
- 消す順番：古い版の残骸（名前の版が今のコードと違う）→ 元のペイントが無い準備のフォルダー →
  「大きさ × 使っていない期間 ÷ 作り直しの秒数」が大きいもの。
- 消さないもの：表示中の車（今の準備のフォルダーと、それが参照するキャッシュ）・2 車種以上が参照する
  もの・最近（7 日以内）使ったもの・タイヤの側面の文字・解析結果・部品の色の Texture・索引・
  種類の分からないファイル。古い版の残骸と元のペイントが無いものは、表示中のもの以外は保護しない。
- 参照の数は、ペイントごとの準備のフォルダーの JSON の記録に現れるキャッシュのパスから数える
  （タイヤの署名済みの GLB は車種ごとに 1 つで、共通ではない）。
- 消すのは準備のキャッシュのフォルダーの中だけ。リンク（シンボリックリンク・ジャンクション）は辿らず、
  消さない。消せなかったもの（使用中など）は飛ばして記録する。ゲームの原本・GameSave には触れない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Iterable

from .vehicle_analysis_cache import LAST_USED_FIELD, plan_eviction

VEHICLE_CACHE_DIR = "_fh6-vehicle-cache"
LIMIT_SETTING_KEY = "vehicle_cache_limit_gb"
PREPARED_DIR_RE = re.compile(r"car-(\d+)__")
# ペイントの元のパスを持つ準備の記録（organizer-preview-request.normalized.json の source）
REQUEST_FILE = "organizer-preview-request.normalized.json"
# 削除の途中で止まったフォルダーの名前の印（次回、古い版の残骸として消す）
DELETING_MARK = ".lo4fh6-deleting-"

_CHASSIS_RE = re.compile(r"\.local-chassis-v(\d+)")
_OVERLAY_RE = re.compile(r"\.overlay-firstparty-v(\d+)\.glb")
_PART_OPTION_RE = re.compile(r"-v(\d+)-r(\d+)-[A-Za-z]+-\d+\.glb$")
_STANDARD_TIRE_RE = re.compile(r"^r(\d+)-")


@dataclass(frozen=True)
class CacheRevisions:
    """今のコードの版（名前の版がこれと違えば古い版の残骸）。"""
    chassis: int
    overlay: int
    part_option: int
    standard_tire: int


def current_revisions() -> CacheRevisions:
    from .part_option_overlay import PART_OPTION_OVERLAY_REVISION
    from .portable_mesh_converter import LOCAL_CHASSIS_FORMAT_REVISION
    from .source_tire_original_normal import STANDARD_TIRE_NORMAL_CACHE_REVISION
    return CacheRevisions(chassis=LOCAL_CHASSIS_FORMAT_REVISION, overlay=2,
                          part_option=PART_OPTION_OVERLAY_REVISION,
                          standard_tire=STANDARD_TIRE_NORMAL_CACHE_REVISION)


@dataclass
class CacheUnit:
    kind: str
    paths: list[Path]
    bytes: int = 0
    last_used: float = 0.0
    obsolete: bool = False
    orphan: bool = False
    pinned: bool = False
    small_analysis: bool = False
    shared_by: int = 0
    in_use: bool = False
    rebuild_seconds: float = 1.0
    referenced_by: set[int] = field(default_factory=set)

    def as_plan_row(self) -> dict:
        return {"unit": self, "bytes": self.bytes, LAST_USED_FIELD: self.last_used, "obsolete": self.obsolete,
                "orphan": self.orphan, "in_use": self.in_use, "pinned": self.pinned,
                "shared_by": max(self.shared_by, len(self.referenced_by)),
                "small_analysis": self.small_analysis, "rebuild_seconds": self.rebuild_seconds}


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def _measure(paths: Iterable[Path]) -> tuple[int, float]:
    size, used = 0, 0.0
    for path in paths:
        if _is_link(path):
            continue
        if path.is_dir():
            for current, dirs, files in os.walk(path):
                dirs[:] = [name for name in dirs if not _is_link(Path(current) / name)]
                for name in files:
                    try:
                        stat = (Path(current) / name).stat()
                    except OSError:
                        continue
                    size += stat.st_size
                    used = max(used, stat.st_atime)
        else:
            try:
                stat = path.stat()
            except OSError:
                continue
            size += stat.st_size
            used = max(used, stat.st_atime)
    return size, used


def _key(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _prepared_source_missing(folder: Path) -> bool:
    """準備のフォルダーの元のペイント（C_livery）が無くなっていれば True。記録が読めなければ False（消さない）。"""
    try:
        request = json.loads((folder / REQUEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    source = request.get("source") if isinstance(request, dict) else None
    if not isinstance(source, str) or not source:
        return False
    return not Path(source).exists()


def _referenced_paths(folder: Path) -> set[str]:
    """準備のフォルダーの JSON の記録から、車種のキャッシュ（_fh6-vehicle-cache）の中のパスを集める。"""
    found: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, str):
            if VEHICLE_CACHE_DIR in value and len(value) < 1024:
                found.add(_key(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for path in folder.glob("*.json"):
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            walk(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return found


def collect_cache_units(output_root: Path | str, *, revisions: CacheRevisions | None = None,
                        current_prepared_dir: Path | str | None = None) -> list[CacheUnit]:
    """消す単位の一覧。単位はまとめて消す（GLB と付属の JSON、タイヤのフォルダー等）。"""
    root = Path(output_root)
    revisions = revisions or current_revisions()
    cache = root / VEHICLE_CACHE_DIR
    units: list[CacheUnit] = []
    current_key = _key(current_prepared_dir) if current_prepared_dir else None

    # 1. ペイントごとの準備のフォルダー
    prepared: list[tuple[CacheUnit, set[str]]] = []
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            match = PREPARED_DIR_RE.match(folder.name)
            if not match or not folder.is_dir() or _is_link(folder):
                continue
            if DELETING_MARK in folder.name:
                units.append(CacheUnit("leftover", [folder], obsolete=True))
                continue
            unit = CacheUnit("prepared", [folder], rebuild_seconds=5.0)
            unit.in_use = current_key is not None and _key(folder) == current_key
            unit.orphan = _prepared_source_missing(folder)
            units.append(unit)
            prepared.append((unit, _referenced_paths(folder)))

    def add(kind: str, paths: list[Path], **flags) -> CacheUnit:
        if any(DELETING_MARK in path.name for path in paths):
            kind, flags = "leftover", {"obsolete": True}
        unit = CacheUnit(kind, paths, **flags)
        units.append(unit)
        return unit

    # 2. 車種ごとのキャッシュ
    if cache.is_dir() and not _is_link(cache):
        for entry in sorted(cache.iterdir()):
            if _is_link(entry):
                continue
            name = entry.name
            if entry.is_file():
                add("index" if name == "vehicle-index.json" else "other", [entry], pinned=True)
            elif name == "meshes":
                groups: dict[str, list[Path]] = {}
                for path in sorted(entry.iterdir()):
                    if _is_link(path) or not path.is_file():
                        continue
                    base = path.name.split(".glb", 1)[0] + ".glb" if ".glb" in path.name else path.name
                    groups.setdefault(base, []).append(path)
                for base, paths in groups.items():
                    chassis = _CHASSIS_RE.search(base)
                    overlay = _OVERLAY_RE.search(base)
                    obsolete = bool((chassis and int(chassis.group(1)) != revisions.chassis)
                                    or (overlay and int(overlay.group(1)) != revisions.overlay))
                    known = bool(chassis or overlay)
                    add("chassis" if chassis else ("overlay" if overlay else "other"), paths,
                        obsolete=obsolete, pinned=not known, rebuild_seconds=15.0 if chassis else 3.0)
            elif name == "part-options":
                for path in sorted(entry.iterdir()):
                    if _is_link(path) or not path.is_file():
                        continue
                    match = _PART_OPTION_RE.search(path.name)
                    obsolete = bool(match and (int(match.group(1)) != revisions.chassis
                                               or int(match.group(2)) != revisions.part_option))
                    add("part_option", [path], obsolete=obsolete, pinned=match is None, rebuild_seconds=3.0)
            elif name == "wheel-tire":
                for group in sorted(entry.iterdir()):
                    if _is_link(group):
                        continue
                    if group.name == "Original-Tire-Source-Signed-Standard" and group.is_dir():
                        for folder in sorted(group.iterdir()):
                            if _is_link(folder) or not folder.is_dir():
                                continue
                            match = _STANDARD_TIRE_RE.match(folder.name)
                            add("tire", [folder], obsolete=bool(match and int(match.group(1)) != revisions.standard_tire),
                                pinned=match is None, rebuild_seconds=20.0)
                    elif group.name == "_original_tire_local_source" and group.is_dir():
                        # タイヤの中間ファイル（GLB と証拠の JSON の組）。名前から版は分からないので、古い版は
                        # 使われなくなった期間で消す（最近 7 日以内に使ったものは保護）。
                        pairs: dict[str, list[Path]] = {}
                        for path in sorted(group.iterdir()):
                            if not _is_link(path) and path.is_file():
                                pairs.setdefault(path.name.split(".", 1)[0], []).append(path)
                        for paths in pairs.values():
                            add("tire_source", paths, rebuild_seconds=20.0)
                    else:
                        # タイヤの側面の文字の Texture 等：小さく、多くの車種で共通に使うので消さない。
                        add("tire_text", [group], pinned=True)
            elif name == "projection-masks":
                for folder in sorted(entry.iterdir()):
                    if not _is_link(folder):
                        add("projection_mask", [folder], rebuild_seconds=2.0)
            elif name == "wheel-routing":
                for path in sorted(entry.iterdir()):
                    if not _is_link(path) and path.is_file():
                        add("wheel_routing", [path], rebuild_seconds=1.0)
            elif name == "vehicle-analysis":
                add("analysis", [entry], small_analysis=True, pinned=True)
            elif name == "body-trim-textures":
                add("trim_texture", [entry], pinned=True)
            else:
                add("other", [entry], pinned=True)

    for unit in units:
        unit.bytes, unit.last_used = _measure(unit.paths)

    # 3. 参照：どの準備のフォルダー（車の番号）が、どのキャッシュの単位を使っているか
    owners = []
    for unit in units:
        if unit.kind == "prepared":
            continue
        owners.append(([_key(path) for path in unit.paths], unit))
    for prepared_unit, references in prepared:
        car = int(PREPARED_DIR_RE.match(prepared_unit.paths[0].name).group(1))
        for reference in references:
            for keys, unit in owners:
                if any(reference == key or reference.startswith(key + os.sep) for key in keys):
                    unit.referenced_by.add(car)
                    if prepared_unit.in_use:
                        unit.in_use = True
    return units


def usage_summary(units: list[CacheUnit]) -> dict:
    by_kind: dict[str, dict] = {}
    for unit in units:
        row = by_kind.setdefault(unit.kind, {"units": 0, "bytes": 0, "obsolete_bytes": 0})
        row["units"] += 1
        row["bytes"] += unit.bytes
        if unit.obsolete:
            row["obsolete_bytes"] += unit.bytes
    return {"total_bytes": sum(unit.bytes for unit in units), "by_kind": dict(sorted(by_kind.items()))}


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _delete_unit(root: Path, unit: CacheUnit) -> str | None:
    """単位を消す。消せなければ理由を返す（一部だけ消えた単位は次回また候補になる）。

    フォルダーは、先に「削除中」の名前へ変えてから消す。途中で止まっても、中身の欠けたフォルダーが
    元の名前で残らない（タイヤ等は、元の名前のフォルダーの中身が欠けているとエラーにする）。
    """
    for path in unit.paths:
        if _is_link(path) or not _inside(root, path):
            return f"準備のキャッシュの外か、リンクです: {path}"
    for path in unit.paths:
        try:
            if path.is_dir():
                target = path if DELETING_MARK in path.name else path.with_name(
                    f"{path.name}{DELETING_MARK}{os.getpid()}-{time.time_ns()}")
                if target != path:
                    path.rename(target)
                shutil.rmtree(target)
            elif path.exists():
                path.unlink()
        except OSError as exc:
            return f"{type(exc).__name__}: {exc}"
    return None


def enforce_cache_limit(output_root: Path | str, limit_bytes: int, *, current_prepared_dir: Path | str | None = None,
                        apply: bool = True, now: float | None = None,
                        revisions: CacheRevisions | None = None) -> dict:
    """上限を超えそうなら、方針どおりに消す（apply=False なら計画だけ）。結果の記録を返す。"""
    root = Path(output_root)
    units = collect_cache_units(root, revisions=revisions, current_prepared_dir=current_prepared_dir)
    rows = [unit.as_plan_row() for unit in units]
    plan = plan_eviction(rows, int(limit_bytes), now=now)
    deleted, failed = [], []
    for row in plan:
        unit: CacheUnit = row["unit"]
        record = {"kind": unit.kind, "bytes": unit.bytes, "paths": [str(path) for path in unit.paths],
                  "obsolete": unit.obsolete, "orphan": unit.orphan}
        if not apply:
            deleted.append(record)
            continue
        reason = _delete_unit(root, unit)
        if reason is None:
            deleted.append(record)
        else:
            failed.append({**record, "reason": reason})
    usage = usage_summary(units)
    return {"limit_bytes": int(limit_bytes), "applied": bool(apply), "before_bytes": usage["total_bytes"],
            "deleted_units": len(deleted), "deleted_bytes": sum(row["bytes"] for row in deleted),
            "failed_units": len(failed), "deleted": deleted, "failed": failed, "usage": usage,
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def limit_bytes_from_settings(settings: dict) -> int | None:
    """共有の設定の vehicle_cache_limit_gb（GB）。無い・正でない・数でなければ None（上限なし）。"""
    value = settings.get(LIMIT_SETTING_KEY) if isinstance(settings, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        return None
    return int(float(value) * 1024 ** 3)


def main(argv: list[str]) -> int:
    """使い方：python -m tools.livery.vehicle_cache_limit <準備のキャッシュ> [上限 GB] [--apply]
    上限を省くと使用量だけを表示する。--apply が無ければ、消す候補を表示するだけで消さない。"""
    if not argv:
        print(main.__doc__)
        return 2
    root = Path(argv[0])
    numbers = [value for value in argv[1:] if not value.startswith("--")]
    units = collect_cache_units(root)
    usage = usage_summary(units)
    print(f"合計 {usage['total_bytes'] / 1024 ** 3:.2f} GB")
    for kind, row in usage["by_kind"].items():
        print(f"  {kind}: {row['units']} 単位 {row['bytes'] / 1024 ** 3:.2f} GB（古い版 {row['obsolete_bytes'] / 1024 ** 3:.2f} GB）")
    if numbers:
        result = enforce_cache_limit(root, int(float(numbers[0]) * 1024 ** 3), apply="--apply" in argv[1:])
        word = "消した" if result["applied"] else "消す候補"
        print(f"{word}: {result['deleted_units']} 単位 {result['deleted_bytes'] / 1024 ** 3:.2f} GB、"
              f"消せなかった {result['failed_units']} 単位")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
