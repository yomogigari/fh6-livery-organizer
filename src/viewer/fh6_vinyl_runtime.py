from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fh6_vinyl_local_geometry import extract_selected_zip, extract_zip

VISIBLE_RESOURCE_COUNT = 1400
CACHE_MANIFEST = "local-vinyl-cache.json"


def vinyl_source_signature(zip_path: Path) -> dict[str, Any]:
    stat = zip_path.stat()
    return {
        "path": str(zip_path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def local_vinyl_cache_ready(cache_root: Path, zip_path: Path) -> bool:
    manifest_path = cache_root / CACHE_MANIFEST
    vinyl_root = cache_root / "Vinyls"
    if not manifest_path.is_file() or not vinyl_root.is_dir():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if manifest.get("source") != vinyl_source_signature(zip_path):
        return False
    if int(manifest.get("written_count") or 0) != VISIBLE_RESOURCE_COUNT:
        return False
    if int(manifest.get("parse_error_count", -1)) != 0:
        return False
    return sum(1 for path in vinyl_root.rglob("*") if path.is_file()) == VISIBLE_RESOURCE_COUNT


def ensure_local_vinyl_geometry(game_folder: Path, cache_root: Path) -> Path:
    game_folder = game_folder.expanduser().resolve()
    cache_root = cache_root.expanduser().resolve()
    zip_path = game_folder / "media" / "livery" / "Vinyls.zip"
    if not zip_path.is_file():
        raise FileNotFoundError(f"FH6 Vinyls.zip not found: {zip_path}")
    if local_vinyl_cache_ready(cache_root, zip_path):
        print(f"vinyl cache hit: {cache_root / 'Vinyls'}")
        return cache_root / "Vinyls"

    print(f"vinyl cache build: {zip_path}")
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    report = extract_zip(zip_path, cache_root, reference_root=None)
    written = int(report.get("written_count") or 0)
    errors = int(report.get("parse_error_count") or 0)
    if written != VISIBLE_RESOURCE_COUNT or errors != 0:
        raise ValueError(
            f"Local FH6 vinyl geometry cache is incomplete: written={written}, parse_errors={errors}"
        )
    manifest = {
        "format": "lo4fh6_local_vinyl_cache_v1",
        "source": vinyl_source_signature(zip_path),
        "written_count": written,
        "parse_error_count": errors,
        "resource_root": str((cache_root / "Vinyls").resolve()),
        "read_only_game_source": True,
    }
    (cache_root / CACHE_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"vinyl cache ready: {cache_root / 'Vinyls'}")
    return cache_root / "Vinyls"


def _runtime_content_root(game_folder: Path) -> Path:
    root = Path(game_folder).expanduser().resolve()
    if (root / "media" / "livery" / "Vinyls.zip").is_file():
        return root
    if (root / "Content" / "media" / "livery" / "Vinyls.zip").is_file():
        return (root / "Content").resolve()
    return root


def selected_shape_words_from_design(design: dict[str, Any]) -> list[int]:
    """Return vector Vinyl shape words referenced by a canonical surface design.

    Raster logos resolve through Decals.zip and do not require Vinyl geometry.
    Transparent vector placements are retained because later composition/mask
    logic owns their effective coverage semantics.
    """
    from fh_livery_preview_core.livery_preview import shape_is_raster, shape_word

    words: set[int] = set()
    for surface in design.get("surfaces") or []:
        if not isinstance(surface, dict):
            continue
        for shape in surface.get("shapes") or []:
            if not isinstance(shape, dict) or shape_is_raster(shape):
                continue
            word = int(shape_word(shape)) & 0xFFFF
            if word:
                words.add(word)
    return sorted(words)


def extract_selected_vinyl_geometry_for_design(
    game_folder: Path,
    output_root: Path,
    design: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Extract only Vinyl geometry referenced by one canonical design.

    This is the normal fresh CPU-paint preparation path from r373 onward.  The
    extracted files are transient working data owned by the caller; no shared
    1,400-resource geometry cache is created.
    """
    content_root = _runtime_content_root(game_folder)
    zip_path = content_root / "media" / "livery" / "Vinyls.zip"
    words = selected_shape_words_from_design(design)
    vinyl_root, report = extract_selected_zip(zip_path, output_root, words)
    return vinyl_root, {
        "format": "lo4fh6_selected_cpu_vinyl_geometry_v1",
        "requested_shape_word_count": len(words),
        "selected_resource_count": int(report.get("selected_resource_count") or 0),
        "parsed_resource_count": int(report.get("parsed_resource_count") or 0),
        "persistent_cache_created": False,
    }

