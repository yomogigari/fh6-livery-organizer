from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .gyvl import TYPE_CODE_BASE


RECTANGLE_WORD = 0x0065
PREVIEW_COVER_AREA_RATIO = 16.0
_CONFIGURED_VINYL_RESOURCE_ROOT: Path | None = None


def bundled_vinyl_resource_root() -> Path:
    return Path(__file__).resolve().parent / "assets" / "fh6_vinyl_resources" / "Vinyls"


def configure_vinyl_resource_root(path: Path | str | None) -> Path:
    """Select the vinyl geometry root used by all preview renderers in-process.

    The research viewer points this at geometry reconstructed from the user's
    own FH6 ``media/livery/Vinyls.zip``. Passing ``None`` clears the configured
    root. The historical 1,400-resource bundle is intentionally not distributed.
    """
    global _CONFIGURED_VINYL_RESOURCE_ROOT
    if path is None:
        _CONFIGURED_VINYL_RESOURCE_ROOT = None
        return bundled_vinyl_resource_root()
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"vinyl resource root not found: {root}")
    _CONFIGURED_VINYL_RESOURCE_ROOT = root
    return root


def default_vinyl_resource_root() -> Path:
    # The legacy path is retained as a deterministic empty sentinel for low-level
    # diagnostics/tests that intentionally exercise fallback geometry. The
    # game-facing entry point verifies that a real local FH6 resource root exists
    # before rendering, so this is not a redistribution/runtime fallback.
    return _CONFIGURED_VINYL_RESOURCE_ROOT or bundled_vinyl_resource_root()


def remove_preview_cover_shapes(
    shapes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    measured = [(index, preview_shape_area(shape)) for index, shape in enumerate(shapes)]
    rectangle_areas = [
        area
        for (index, area) in measured
        if area > 0.0 and shape_type_word(shapes[index]) == RECTANGLE_WORD
    ]
    if not rectangle_areas:
        return list(shapes), preview_framing_report([])

    largest = max(rectangle_areas)
    cover_cluster = {
        index
        for index, area in measured
        if shape_type_word(shapes[index]) == RECTANGLE_WORD and area >= largest * 0.95
    }
    reference_areas = [area for index, area in measured if index not in cover_cluster and area > 0.0]
    if not reference_areas or largest < max(reference_areas) * PREVIEW_COVER_AREA_RATIO:
        return list(shapes), preview_framing_report([])

    removed = [shapes[index] for index in sorted(cover_cluster)]
    kept = [shape for index, shape in enumerate(shapes) if index not in cover_cluster]
    return kept, preview_framing_report(removed)


def preview_shape_area(shape: dict[str, Any]) -> float:
    data = list(shape.get("data") or [])
    if len(data) < 4:
        return 0.0
    try:
        area = abs(float(data[2]) * float(data[3]))
    except (TypeError, ValueError):
        return 0.0
    return area if math.isfinite(area) else 0.0


def shape_type_word(shape: dict[str, Any]) -> int | None:
    value = shape.get("type_word")
    if value is None:
        try:
            value = int(shape.get("type")) - TYPE_CODE_BASE
        except (TypeError, ValueError):
            return None
    try:
        return int(value) & 0xFFFF
    except (TypeError, ValueError):
        return None


def preview_framing_report(removed: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "strategy": "exclude_dominant_full_surface_rectangles_when_detail_layers_exist",
        "cover_area_ratio_threshold": PREVIEW_COVER_AREA_RATIO,
        "excluded_shape_count": len(removed),
        "excluded_offsets": [shape.get("gyvl_offset") for shape in removed if shape.get("gyvl_offset")],
    }


def gradient_subdivision(triangle_count: int) -> int:
    if triangle_count <= 4:
        return 8
    if triangle_count <= 32:
        return 3
    return 1


def subdivide_gradient_triangle(
    triangle: tuple[tuple[tuple[float, float], int], ...],
    subdivision: int,
) -> list[tuple[tuple[tuple[float, float], ...], float]]:
    def sample(u: float, v: float) -> tuple[tuple[float, float], float]:
        weights = (1.0 - u - v, u, v)
        x = sum(triangle[index][0][0] * weight for index, weight in enumerate(weights))
        y = sum(triangle[index][0][1] * weight for index, weight in enumerate(weights))
        alpha = sum(triangle[index][1] * weight for index, weight in enumerate(weights))
        return (x, y), alpha

    pieces: list[tuple[tuple[tuple[float, float], ...], float]] = []
    for row in range(subdivision):
        for column in range(subdivision - row):
            a = sample(row / subdivision, column / subdivision)
            b = sample((row + 1) / subdivision, column / subdivision)
            c = sample(row / subdivision, (column + 1) / subdivision)
            pieces.append(((a[0], b[0], c[0]), (a[1] + b[1] + c[1]) / 3.0))
            if column < subdivision - row - 1:
                d = sample((row + 1) / subdivision, (column + 1) / subdivision)
                pieces.append(((b[0], d[0], c[0]), (b[1] + d[1] + c[1]) / 3.0))
    return pieces
