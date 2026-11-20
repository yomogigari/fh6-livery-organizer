from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

CAPABILITY_FORMAT = "lo4fh6_gpu_livery_runtime_capability_v1"
SELECTION_FORMAT = "lo4fh6_gpu_livery_runtime_selection_v1"
CAPABILITY_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def default_capability_cache_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "Livery Organizer for FH6" / "PreviewBridge" / "gpu-livery-runtime-capability.json"


def sanitize_capability_payload(payload: dict[str, Any]) -> dict[str, Any]:
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    reason = str(probe.get("reason") or "")[:64]
    if reason not in {
        "no_webgl2", "context_lost", "target_allocation_failed",
        "rgba8_fbo_complete", "webgl_error", "framebuffer_incomplete",
        "probe_exception", "restore_failed",
    }:
        reason = "unavailable"
    def gpu_code(value: Any) -> int | None:
        try:
            number = int(value)
            return number if 0 <= number <= 0xFFFFFFFF else None
        except (TypeError, ValueError, OverflowError):
            return None
    return {
        "format": CAPABILITY_FORMAT,
        "captured_unix": float(payload.get("captured_unix") or time.time()),
        "webgl2": bool(payload.get("webgl2")),
        "offscreen_framebuffer": bool(payload.get("offscreen_framebuffer")),
        "rgba8_render_target": bool(payload.get("rgba8_render_target")),
        "probe": {
            "reason": reason,
            "framebuffer_status": gpu_code(probe.get("framebuffer_status")),
            "gl_error": gpu_code(probe.get("gl_error")),
            "context_lost": bool(probe.get("context_lost")),
        },
        "limits": {
            "max_texture_size": int(limits.get("max_texture_size") or 0),
            "max_renderbuffer_size": int(limits.get("max_renderbuffer_size") or 0),
            "max_texture_image_units": int(limits.get("max_texture_image_units") or 0),
        },
        "privacy": "hardware/vendor/renderer names are intentionally not persisted",
    }


def write_capability_cache(payload: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    target = (path or default_capability_cache_path()).expanduser().resolve()
    clean = sanitize_capability_payload(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return clean


def load_capability_cache(path: Path | None = None, *, now: float | None = None) -> dict[str, Any] | None:
    target = (path or default_capability_cache_path()).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("format") != CAPABILITY_FORMAT:
        return None
    try:
        captured = float(payload.get("captured_unix") or 0.0)
    except (TypeError, ValueError):
        return None
    current = float(time.time() if now is None else now)
    if captured <= 0.0 or current - captured > CAPABILITY_MAX_AGE_SECONDS:
        return None
    return sanitize_capability_payload(payload)


def evaluate_runtime_selection(
    *,
    requested: str = "auto",
    capability: dict[str, Any] | None,
    production_adapter_available: bool,
    research_gate_passed: bool = True,
) -> dict[str, Any]:
    """GPU専用実行方針。旧研究フラグで標準入口を無効化せずCPU後退もしない。"""
    mode = str(requested or "auto").strip().casefold()
    if mode not in {"auto", "gpu"}:
        raise ValueError("CPU livery paint was removed; use WebGL2 GPU paint")
    gpu_capable = bool(
        capability
        and capability.get("webgl2")
        and capability.get("offscreen_framebuffer")
        and capability.get("rgba8_render_target")
    )
    # 製品標準WebGL2は研究承認フラグでは遮断しない。
    # research_gate_passedは旧API/診断用メタデータとしてのみ保持。
    # 実GPU capabilityと製品Adapterの有無は従来どおり検査する。
    if not production_adapter_available:
        reason = "gpu_production_adapter_not_available"
    elif not gpu_capable:
        reason = "gpu_capability_unavailable"
    else:
        reason = "gpu_selected"
    return {
        "format": SELECTION_FORMAT,
        "requested": "gpu",
        "selected": "gpu" if reason == "gpu_selected" else "unavailable",
        "reason": reason,
        "fallback_used": False,
        "gpu_capable": gpu_capable,
        "production_adapter_available": bool(production_adapter_available),
        "research_gate_passed": bool(research_gate_passed),
        "capability": capability,
    }
