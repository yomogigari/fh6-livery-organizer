from __future__ import annotations

"""Private, revision-scoped cache for the model-dependent wheel colour routing report.

A cache hit must be based on the converted wheel mesh and installed vehicle/
material archives. Livery colour values are intentionally excluded: the report
contains material/group routing only; per-design paint colours are decoded anew.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from .vehicle_analysis_cache import library_zip_rows

CACHE_FORMAT = "lo4fh6_wheel_routing_shared_cache_v1"
# MatI識別子とVerB識別子の同数値衝突を分離して原本WheelPaint 20行を再生成。
# 古い16行ルートを返す保存済み診断を削除せず、新キーで安全に無効化する。
CACHE_REVISION = "r388-original-wheel-modelbin-and-mati-sha-bound-route-20261115"
MAX_CACHE_BYTES = 4 * 1024 * 1024


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns) if path.is_file() else None


_CASE_SENSITIVE_PATHS = os.path.normcase("A") == "A"


def _library_order_key(item: tuple) -> list[str]:
    """library_zip_entries の項目を、場所（Path）で並べたときと同じ順にする鍵（2026-11-20）。

    Path どうしの比べは、場所の文字列を（大文字・小文字を区別しない OS では lower() で）区切りで分けた並びで行う。
    項目はどれも同じ _library の下なので、相対名（区切りは /）で同じ並びになる。以前は Path どうしを比べて
    いたので、比べるたびに 759 個の場所を初めて読む処理（Python 3.12 の Path は場所を読むのを後回しにする）が
    走っていた（1 回 約 10 ms）。
    """
    relative = item[1]
    return (relative if _CASE_SENSITIVE_PATHS else relative.lower()).split("/")


def _library_row_order_key(row: tuple) -> list[str]:
    """library_zip_rows の項目（相対名が先頭）を、_library_order_key と同じ順にする鍵。"""
    relative = row[0]
    return (relative if _CASE_SENSITIVE_PATHS else relative.lower()).split("/")


def cache_key(*, content_root: Path, vehicle_archive: Path, mesh_path: Path) -> str | None:
    """Hash private installation location and all relevant installed zip metadata."""
    content_root = Path(content_root).resolve()
    vehicle_archive = Path(vehicle_archive).resolve()
    mesh_path = Path(mesh_path).resolve()
    vehicle_stamp = _file_identity(vehicle_archive)
    mesh_stamp = _file_identity(mesh_path)
    if vehicle_stamp is None or mesh_stamp is None:
        return None
    library_root = content_root / "media" / "cars" / "_library"
    # Referenced material/shader/texture archives may change independently of
    # the car archive. Use metadata only; never read or persist the asset bytes.
    # 一覧は os.scandir の項目の情報で作る（rglob＋ファイルごとの stat と同じ値。vehicle_analysis_cache）。
    archives: list[tuple[str, tuple[int, int] | None]] = []
    try:
        if library_root.is_dir():
            for relative, stat, is_file in sorted(library_zip_rows(library_root), key=_library_row_order_key):
                archives.append((relative, (stat.st_size, stat.st_mtime_ns) if is_file else None))
    except OSError:
        return None
    identity = {
        "format": CACHE_FORMAT,
        "revision": CACHE_REVISION,
        "content_root": str(content_root),
        "vehicle_archive": [str(vehicle_archive), vehicle_stamp],
        "mesh": [str(mesh_path), mesh_stamp],
        "material_archives": archives,
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_report(report: object) -> bool:
    """保存・再利用してよい報告か。

    解析が最後まで終わった報告（available が True）は、PASS でも FAIL でも同じ入力（鍵）なら同じ結果になる。
    FAIL（利用者の色を塗れるホイールの部品が無い車など、全車種の約 14%）も保存し、準備のたびの作り直し
    （0.4〜0.7 秒）をやめる（2026-11-19）。例外で止まった報告（available が False）は保存しない。
    """
    if not isinstance(report, dict):
        return False
    summary = report.get("summary")
    routing = report.get("routing")
    return (
        report.get("format") == "lo4fh6_wheel_paint_routing_diagnostics_v1"
        and report.get("read_only") is True
        and report.get("available") is True
        and isinstance(summary, dict)
        and summary.get("status") in ("PASS", "FAIL")
        and isinstance(routing, dict)
        and isinstance(routing.get("cars"), list)
    )


def cached_wheel_paint_routing(
    *,
    cache_root: Path,
    content_root: Path,
    vehicle_archive: Path,
    mesh_path: Path,
    build: Callable[[], dict],
) -> tuple[dict, bool]:
    """Return (report, hit); failure to use the cache never suppresses building."""
    key = cache_key(
        content_root=content_root, vehicle_archive=vehicle_archive, mesh_path=mesh_path
    )
    path = Path(cache_root) / f"wheel-routing-{key}.json" if key else None
    if path is not None:
        try:
            if 0 < path.stat().st_size <= MAX_CACHE_BYTES:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if (
                    isinstance(saved, dict)
                    and saved.get("format") == CACHE_FORMAT
                    and saved.get("revision") == CACHE_REVISION
                    and saved.get("cache_key") == key
                    and _valid_report(saved.get("report"))
                ):
                    return saved["report"], True
        except (OSError, UnicodeError, ValueError, TypeError):
            pass
    report = build()
    if path is not None and _valid_report(report):
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".wheel-routing-", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump({"format": CACHE_FORMAT, "revision": CACHE_REVISION,
                           "cache_key": key, "report": report}, handle, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_path, path)
        except (OSError, TypeError, ValueError):
            # Cache writing is an optimization, not a requirement for rendering.
            pass
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return report, False
