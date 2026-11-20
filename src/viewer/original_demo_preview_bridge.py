# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=10,<13", "numpy>=1.26,<3", "psutil>=5.9,<8", "pywebview>=5.4,<7"]
# ///
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from tools.livery.inspector_server import LiveryInspectorServer
from tools.livery.package import (
    PACKAGE_COMPILER_REVISION,
    PRIVATE_PREVIEW_FORMAT,
    FullLiveryPackageError,
    _files_manifest,
    _safe_member_name,
    _sha256,
    validate_livery_inspection_artifact,
)
from tools.livery.portable_mesh_converter import (
    LOCAL_CHASSIS_FORMAT_REVISION,
    PortableMeshConverterError,
    convert_vehicle_model_to_glb,
    validate_local_chassis_glb,
)
from tools.livery.render_contract import build_local_livery_atlases
from tools.livery.vehicle_assets import load_or_build_vehicle_asset_index, sha256_file

ROOT = Path(__file__).resolve().parent
VIEWER_ROOT = ROOT / "tools" / "livery-inspector"
DEMO_FORMAT = "lo4fh6_original_demo_livery_v1"
SUMMARY_FORMAT = "lo4fh6_original_demo_preview_summary_v1"
DEMO_PREVIEW_REVISION = 3


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")


def _string(value: Any) -> str:
    return str(value or "").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or open the project-authored original Vivio demo livery in the research Viewer. "
            "The input is a demo-livery-manifest.json + transparent section PNG set, not a C_livery."
        )
    )
    parser.add_argument(
        "--demo-root",
        type=Path,
        default=Path("demo/original-vivio-demo"),
        help="directory containing demo-livery-manifest.json and section PNGs",
    )
    parser.add_argument("--game-folder", type=Path, required=True, help=r"FH6 install or Content folder")
    parser.add_argument("--car-id", type=int, default=None, help="override target Car ID")
    parser.add_argument("--title", default="", help="optional display title override")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("demo-preview-output"),
        help="root directory for prepared preview output",
    )
    parser.add_argument("--rebuild", action="store_true", help="recreate the package and render contract")
    parser.add_argument("--prepare-only", action="store_true", help="prepare output only; do not start the Viewer")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser automatically")
    parser.add_argument(
        "--window-mode",
        choices=("standalone", "browser"),
        default="standalone",
        help="Viewer host; standalone uses the same WebView2 app-window style as Organizer previews",
    )
    return parser.parse_args()


def load_demo_manifest(demo_root: Path) -> dict[str, Any]:
    path = demo_root / "demo-livery-manifest.json"
    if not path.is_file():
        raise FullLiveryPackageError(f"Demo manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != DEMO_FORMAT:
        raise FullLiveryPackageError("The original demo manifest format is unsupported.")
    return data


def demo_base_paint_material(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the Viewer base-paint contract for the project-authored demo."""
    base_paint = manifest.get("base_paint") if isinstance(manifest.get("base_paint"), dict) else {}
    viewer_candidate = base_paint.get("viewer_candidate") if isinstance(base_paint.get("viewer_candidate"), dict) else {}
    return {
        "finish_code_raw": None,
        "finish_label": str(base_paint.get("name") or "synthetic-demo-base-paint"),
        "material_name": str(base_paint.get("name") or "Synthetic Metallic Pink"),
        "primary_color_rgba_hex": str(base_paint.get("primary_color_rgba_hex") or "#ff9ad0ff"),
        "catalog_match": False,
        "viewer_candidate": {
            "roughness": float(viewer_candidate.get("roughness", 0.0)),
            "metalness": float(viewer_candidate.get("metalness", 1.0)),
            "basis": str(viewer_candidate.get("basis") or "Project-authored synthetic metallic-pink demo material."),
        },
    }


def _png_section_bytes(path: Path) -> tuple[bytes, tuple[int, int]]:
    data = path.read_bytes()
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise FullLiveryPackageError(f"Demo section must be PNG: {path.name}")
            size = image.size
            image.verify()
    except FullLiveryPackageError:
        raise
    except Exception as exc:
        raise FullLiveryPackageError(f"Demo section is unreadable: {path.name}") from exc
    return data, size


def create_original_demo_preview_package(
    demo_root: Path,
    output_path: Path,
    *,
    car_id: int,
    model_code: str,
    title: str,
) -> dict[str, Any]:
    manifest = load_demo_manifest(demo_root)
    section_map = manifest.get("sections") or {}
    if not isinstance(section_map, dict):
        raise FullLiveryPackageError("The original demo manifest sections are invalid.")

    members: dict[str, bytes] = {}
    rendered_sections: list[dict[str, Any]] = []
    section_counts: dict[str, int] = {}
    all_sections = [
        "Front", "Back", "Top", "Left", "Right", "Spoiler",
        "FrontWindshield", "BackWindshield", "TopWindow", "LeftWindow", "RightWindow",
    ]
    for section in all_sections:
        section_counts[section] = 0
    for section, relative_name in section_map.items():
        safe_name = _safe_member_name(f"projection/rendered/{section}.png")
        source_path = (demo_root / str(relative_name)).resolve()
        try:
            source_path.relative_to(demo_root.resolve())
        except ValueError as exc:
            raise FullLiveryPackageError(f"Unsafe demo section path: {relative_name}") from exc
        if not source_path.is_file():
            raise FullLiveryPackageError(f"Missing demo section image: {source_path.name}")
        data, size = _png_section_bytes(source_path)
        if size != (2048, 1024):
            raise FullLiveryPackageError(
                f"Demo section {source_path.name} is {size}; expected 2048 x 1024."
            )
        members[safe_name] = data
        rendered_sections.append({"section": section, "path": safe_name, "width": size[0], "height": size[1]})
        if section in section_counts:
            section_counts[section] = 1

    vehicle = {
        "car_id": int(car_id),
        "model_code": str(model_code),
        "portable_mesh": False,
    }
    projection = {
        "format": "lo4fh6_original_demo_projection_v1",
        "source_container_preserved": False,
        "canonical_decode_complete": False,
        "preview_complete": True,
        "source_exact": False,
        "incomplete_preview": False,
        "native_raster_verified": True,
        "unresolved_raster_ids": [],
        "rendered_sections": rendered_sections,
        "notes": [
            "Project-authored synthetic demo artwork for Viewer smoke tests.",
            "This preview package contains only rendered section PNGs and no FH6 source container.",
        ],
    }
    members["mesh/vehicle.json"] = _json_bytes(vehicle)
    members["projection/index.json"] = _json_bytes(projection)
    if (demo_root / "contact-sheet.png").is_file():
        members["preview/contact-sheet.png"] = (demo_root / "contact-sheet.png").read_bytes()

    bundle_manifest = {
        "format": PRIVATE_PREVIEW_FORMAT,
        "format_version": 1,
        "compiler_revision": PACKAGE_COMPILER_REVISION,
        "package_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "game": "fh6",
            "kind": "project-authored-synthetic-demo",
            "source_folder_name": demo_root.name,
            "source_state": None,
            "owned": True,
            "embedded_car_id": int(car_id),
        },
        "livery": {
            "title": title,
            "target_car_id": int(car_id),
            "logical_placement_count": int(manifest.get("intended_vinyl_budget") or 0),
            "decoded_layer_count": 0,
            "section_counts": section_counts,
            "decoded_section_counts": section_counts,
            "section_count_mismatches": [],
            "decode_warnings": ["Synthetic project-authored demo artwork; no C_livery source is embedded."],
            "preview_complete": True,
            "unresolved_raster_ids": [],
            "payload_offsets": {},
        },
        "vehicle": dict(vehicle),
        "sharing": {
            "exportable": False,
            "preview_only": True,
            "local_unowned_preview": False,
            "contains_foreign_vinyl_groups": False,
            "foreign_vinyl_group_count": 0,
            "external_game_assets_embedded": False,
            "mesh_policy": "resolve matching car mesh from the recipient's own local game installation",
            "opaque_source_record": False,
            "source_container_preserved": False,
            "preview_complete": True,
            "unresolved_raster_references": False,
            "source_identity_policy": "project-authored synthetic artwork; rendered preview only",
        },
        "compatibility": {},
        "files": _files_manifest(members),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + f".{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.writestr("manifest.json", _json_bytes(bundle_manifest))
            for name, data in sorted(members.items()):
                bundle.writestr(name, data)
        validate_livery_inspection_artifact(temporary)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {**bundle_manifest, "package_path": str(output_path.resolve())}


def build_output_dir(root: Path, demo_root: Path, car_id: int) -> Path:
    return root / f"car-{car_id}__{demo_root.name}"


def cached_preview_ready(output_dir: Path, demo_root: Path) -> bool:
    summary_path = output_dir / "original-demo-preview-summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    required = ["private_preview", "mesh", "render_root", "render_contract", "package_sha256"]
    if any(not summary.get(key) for key in required):
        return False
    manifest_path = demo_root / "demo-livery-manifest.json"
    if not manifest_path.is_file():
        return False
    if int(summary.get("adapter_revision") or 0) != DEMO_PREVIEW_REVISION:
        return False
    if summary.get("demo_manifest_sha256") != _sha256(manifest_path.read_bytes()):
        return False
    return all(Path(summary[key]).exists() for key in ("private_preview", "mesh", "render_root", "render_contract"))


def prepare_preview(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    demo_root = args.demo_root.expanduser().resolve()
    manifest = load_demo_manifest(demo_root)
    car_id = int(args.car_id or ((manifest.get("vehicle") or {}).get("car_id") or 0))
    if car_id <= 0:
        raise FullLiveryPackageError("The demo manifest has no usable Car ID.")
    title = _string(args.title) or _string(manifest.get("title")) or "LO4FH6 Original Demo Mascot"
    game_folder = args.game_folder.expanduser().resolve()

    output_dir.mkdir(parents=True, exist_ok=True)
    cache = output_dir / "cache"
    cache.mkdir(exist_ok=True)
    vehicle_index_cache = cache / "vehicle-index.json"
    index = load_or_build_vehicle_asset_index(game_folder, vehicle_index_cache)
    asset = index.get(car_id)
    if asset is None:
        raise FullLiveryPackageError(f"The local FH6 installation has no car archive for Car ID {car_id}.")

    preview_path = output_dir / "source.lo4preview"
    create_original_demo_preview_package(
        demo_root,
        preview_path,
        car_id=car_id,
        model_code=asset.model_code,
        title=title,
    )
    validate_livery_inspection_artifact(preview_path)

    mesh_dir = cache / "meshes"
    mesh_dir.mkdir(exist_ok=True)
    source_sha = sha256_file(Path(asset.archive_path))
    mesh_path = mesh_dir / f"{asset.model_code}-{asset.archive_mtime_ns}-{source_sha}.local-chassis-v{LOCAL_CHASSIS_FORMAT_REVISION}.glb"
    mesh_cache_hit = mesh_path.is_file()
    mesh_validation = None
    if mesh_cache_hit:
        try:
            mesh_validation = validate_local_chassis_glb(
                mesh_path, require_product_accepted=True,
                required_firstparty_scope="ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE")
        except (OSError, PortableMeshConverterError):
            mesh_cache_hit = False
            mesh_path.unlink(missing_ok=True)
            mesh_validation = None
    if not mesh_cache_hit:
        print("mesh: converting exact local FH6 chassis for original demo preview...")
        convert_vehicle_model_to_glb(asset, mesh_path)
        mesh_validation = validate_local_chassis_glb(
            mesh_path, require_product_accepted=True,
            required_firstparty_scope="ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE")
    else:
        print("mesh: cache hit")

    render_root = cache / f"renders-car{car_id}-synthetic-demo-r{DEMO_PREVIEW_REVISION}"
    contract = build_local_livery_atlases(
        preview_path,
        asset,
        render_root,
        mesh_path=mesh_path,
        mesh_validation=mesh_validation,
        quality_scale=1,
        game_folder=game_folder,
    )
    contract["paint_bindings"] = []
    contract["paint_layer_diagnostics"] = {}
    contract["base_paint_material"] = demo_base_paint_material(manifest)
    contract["section_composite_supersample"] = 1
    render_contract_path = output_dir / "local-render-contract.json"
    render_contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "format": SUMMARY_FORMAT,
        "adapter_revision": DEMO_PREVIEW_REVISION,
        "demo_manifest_sha256": _sha256((demo_root / "demo-livery-manifest.json").read_bytes()),
        "demo_root": str(demo_root),
        "game_folder": str(game_folder),
        "car_id": car_id,
        "model_code": asset.model_code,
        "title": title,
        "private_preview": str(preview_path.resolve()),
        "mesh": str(mesh_path.resolve()),
        "render_root": str(render_root.resolve()),
        "render_contract": str(render_contract_path.resolve()),
        "package_sha256": _sha256(preview_path.read_bytes()),
        "notes": [
            "Project-authored synthetic Vivio demo artwork.",
            "Prepared for direct Viewer loading without a C_livery source.",
        ],
    }
    summary_path = output_dir / "original-demo-preview-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _configured_demo_server(output_dir: Path) -> tuple[LiveryInspectorServer, str]:
    summary = json.loads((output_dir / "original-demo-preview-summary.json").read_text(encoding="utf-8"))
    package_path = Path(summary["private_preview"]).resolve()
    mesh_path = Path(summary["mesh"]).resolve()
    render_root = Path(summary["render_root"]).resolve()
    render_contract = json.loads(Path(summary["render_contract"]).read_text(encoding="utf-8"))
    validate_livery_inspection_artifact(package_path)
    server = LiveryInspectorServer(VIEWER_ROOT)
    server.set_package(package_path)
    server.set_local_mesh(mesh_path)
    server.set_local_render_contract(render_root, render_contract)
    return server, server.start()


def launch_browser_preview(output_dir: Path, *, auto_open: bool) -> int:
    server, url = _configured_demo_server(output_dir)
    try:
        (output_dir / "viewer-url.txt").write_text(url + "\n", encoding="utf-8")
        print(f"viewer: {url}")
        print(f"output: {output_dir}")
        print("Press Ctrl+C in this terminal to stop the local Viewer.")
        if auto_open:
            webbrowser.open(url, new=2)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nviewer stopped")
        return 0
    finally:
        server.close()


def launch_standalone_preview(output_dir: Path, *, title: str) -> int:
    try:
        import webview  # type: ignore
    except ImportError as exc:
        raise FullLiveryPackageError("Standalone demo Viewer requires pywebview / WebView2 support.") from exc
    server, url = _configured_demo_server(output_dir)
    try:
        (output_dir / "viewer-url.txt").write_text(url + "\n", encoding="utf-8")
        print(f"viewer: {url}")
        print(f"output: {output_dir}")
        webview.create_window(
            f"{title} - Livery Organizer for FH6",
            url=url,
            width=1440,
            height=900,
            min_size=(960, 640),
        )
        from viewer_app_icon import start_options as icon_options
        webview.start(gui="edgechromium", debug=False, private_mode=True, **icon_options(webview.start))
        return 0
    finally:
        server.close()


def main() -> int:
    args = parse_args()
    demo_root = args.demo_root.expanduser().resolve()
    manifest = load_demo_manifest(demo_root)
    car_id = int(args.car_id or ((manifest.get("vehicle") or {}).get("car_id") or 0))
    output_dir = build_output_dir(args.output_root.expanduser().resolve(), demo_root, car_id)
    print(f"demo:   {demo_root}")
    print(f"game:   {args.game_folder.expanduser().resolve()}")
    print(f"output: {output_dir}")
    if args.rebuild or not cached_preview_ready(output_dir, demo_root):
        prepare_preview(args, output_dir)
    else:
        print("cache hit: reusing prepared original demo preview output")
    if args.prepare_only:
        print("PREPARE PASS — original demo bridge did not start the Viewer.")
        return 0
    title = _string(args.title) or _string(manifest.get("title")) or "LO4FH6 Original Demo Mascot"
    if args.window_mode == "browser":
        return launch_browser_preview(output_dir, auto_open=not args.no_open)
    return launch_standalone_preview(output_dir, title=title)


def run_as_program() -> None:
    """プログラムとして動かす（ソースの直接起動と、EXE の入口 livery_viewer_for_fh6 の両方から呼ぶ）。"""
    try:
        raise SystemExit(main())
    except (FullLiveryPackageError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    run_as_program()
