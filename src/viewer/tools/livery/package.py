from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
import os
import shutil
import struct
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from PIL import Image

from fh_livery_preview_core.canonical import SURFACE_DESIGN_FORMAT

from .first_party_package_source import (
    LIVERY_SECTION_NAMES,
    clivery_to_layers,
    extract_livery_payload,
    inspect_clivery_privacy,
    layers_to_lo4_json_layers,
    unwrap_forza_container,
    unwrap_forza_container_bytes,
)

from .vehicle_assets import (
    VehicleAsset,
    inspect_vehicle_archive,
    load_or_build_vehicle_asset_index,
    read_projection_metadata,
)


PACKAGE_FORMAT = "lo4_full_livery_package_v1"
PACKAGE_EXTENSION = ".lo4livery"
PRIVATE_PREVIEW_FORMAT = "lo4_local_livery_preview_v1"
PRIVATE_PREVIEW_EXTENSION = ".lo4preview"
# 復号・検証・面描画で生成データの意味が変わる場合に改訂番号を更新する。
PACKAGE_COMPILER_REVISION = 11
MAX_PACKAGE_FILES = 256
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024


class FullLiveryPackageError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")


def _json_from_bytes(data: bytes) -> Any:
    return json.loads(
        data.decode("utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def _safe_member_name(name: str) -> str:
    normalized = str(PurePosixPath(str(name).replace("\\", "/")))
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ".." in path.parts or ":" in path.parts[0]:
        raise FullLiveryPackageError(f"unsafe package member path: {name!r}")
    return normalized


def _canonical_package_id(value: Any) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise FullLiveryPackageError("The package identifier is invalid.") from exc
    canonical = str(parsed)
    if str(value) != canonical:
        raise FullLiveryPackageError("The package identifier is not canonical.")
    return canonical


def _decode_livery_contract(payload: bytes) -> tuple[dict[str, Any], dict[str, Any], list[int], dict[str, Any]]:
    layers, report = clivery_to_layers(payload)
    json_layers, identity_warnings = layers_to_lo4_json_layers(layers, game="fh6")
    _, counts, payload_meta = extract_livery_payload(payload)
    warnings = list(report.get("warnings") or [])
    warnings.extend(identity_warnings)
    report = {**report, "warnings": warnings, "identity_warnings": identity_warnings}
    contract = {
        "format": "lo4_full_livery_layers_v1",
        "game": "fh6",
        "target_car_id": struct.unpack_from("<I", payload, 0x10)[0],
        "section_order": list(LIVERY_SECTION_NAMES),
        "section_counts": dict(zip(LIVERY_SECTION_NAMES, counts)),
        "layers": json_layers,
    }
    return contract, report, counts, payload_meta


def _section_layers(layers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_section = {section: [] for section in LIVERY_SECTION_NAMES}
    for layer in layers:
        section = str(layer.get("source_section") or "")
        if section not in by_section:
            raise FullLiveryPackageError(f"A decoded layer uses unsupported livery section {section!r}.")
        by_section[section].append(layer)
    return by_section


def _read_header_title(header: bytes) -> str:
    if len(header) < 8:
        return ""
    units = struct.unpack_from("<I", header, 4)[0]
    if units <= 0 or units > 4096 or 8 + units * 2 > len(header):
        return ""
    return header[8 : 8 + units * 2].decode("utf-16le", errors="replace").strip("\x00 \t\r\n")


def _target_policies(car_id: int) -> dict[str, Any]:
    common_discard = ["inspection-mesh", "inspection-projection", "preview"]
    return {
        "fh6": {
            "status": "exact-source-preserved",
            "strategy": "preserve-fh6-container",
            "requires_target_car_id": car_id,
            "keep_roles": ["source-container", "source-header", "canonical-layers"],
            "translate": ["destination-save-identity", "header-guid", "creator-metadata-when-requested"],
            "discard_roles_on_game_install": common_discard,
        },
        "fh5": {
            "status": "recompile-required-not-implemented",
            "strategy": "rebuild-sections-for-target-car",
            "keep_roles": ["canonical-layers"],
            "translate": ["target-car-id", "shape-identities", "section-projection", "header-dialect"],
            "discard_roles": ["source-container", "source-header", *common_discard],
        },
        "fh4": {
            "status": "recompile-required-not-implemented",
            "strategy": "rebuild-sections-for-target-car",
            "keep_roles": ["canonical-layers"],
            "translate": ["target-car-id", "shape-identities", "section-projection", "header-dialect"],
            "discard_roles": ["source-container", "source-header", *common_discard],
        },
        "fm8": {
            "status": "blocked-until-livery-dialect-encoder-exists",
            "strategy": "none",
            "keep_roles": ["canonical-layers"],
            "translate": ["all-livery-sections", "target-car-id", "shape-identities", "header-dialect"],
            "discard_roles": ["source-container", "source-header", *common_discard],
        },
    }


def compatibility_decision(
    manifest: dict[str, Any],
    target_game: str,
    *,
    target_car_id: int | None = None,
) -> dict[str, Any]:
    """具体的な配布先に対するパッケージ互換性方針を求める。

    参照製品で裏付けられる変換のみ記載する。
    保全された正規図柄を他ゲームへインストール可能なLiveryとは扱わない。
    """
    game = str(target_game or "").strip().casefold()
    sharing = manifest.get("sharing") or {}
    if sharing.get("preview_only") is True:
        return {
            "target_game": game,
            "target_car_id": int((manifest.get("livery") or {}).get("target_car_id") or 0),
            "status": "local-preview",
            "installable": False,
            "installation_eligible": False,
            "keep_roles": ["local-preview"],
            "translate": [],
            "discard_roles": [],
            "reason": "This is a private local preview. Export eligibility is checked from the original saved livery.",
        }
    policies = manifest.get("compatibility") or {}
    policy = dict(policies.get(game) or {})
    source_car_id = int((manifest.get("livery") or {}).get("target_car_id") or 0)
    requested_car_id = int(target_car_id or source_car_id)
    if not policy:
        return {
            "target_game": game,
            "target_car_id": requested_car_id,
            "status": "unsupported-target",
            "installable": False,
            "keep_roles": ["canonical-layers"],
            "translate": [],
            "discard_roles": [],
            "reason": "No package policy exists for this target system.",
        }

    decision = {
        "target_game": game,
        "target_car_id": requested_car_id,
        **policy,
        "installable": False,
        "installation_eligible": False,
    }
    if game == "fh6" and requested_car_id == source_car_id:
        decision["installation_eligible"] = True
        decision["installable"] = True
        decision["status"] = "exact-car-install-ready"
        decision["reason"] = (
            "The package targets this exact FH6 car. The Viewer can preserve the artwork, rewrite only the "
            "destination account metadata, and install it as a new local livery."
        )
    elif game == "fh6":
        decision["status"] = "different-car-blocked"
        decision["reason"] = (
            "Full-livery installation is restricted to the exact car declared by the package."
        )
    else:
        decision["reason"] = (
            "Canonical section artwork remains available, but this destination needs a verified "
            "livery encoder and target-car projection before installation."
        )
    return decision


def _files_manifest(members: dict[str, bytes]) -> list[dict[str, Any]]:
    roles = {
        "source/fh6/C_livery": "source-container",
        "source/fh6/header": "source-header",
        "source/fh6/bigThumb.webp": "source-thumbnail",
        "livery/layers.json": "canonical-layers",
        "mesh/vehicle.json": "inspection-mesh-metadata",
        "projection/index.json": "inspection-projection-metadata",
        "projection/vehicle-map.json": "vehicle-projection-contract",
    }
    result = []
    for name, data in sorted(members.items()):
        role = roles.get(name)
        if role is None:
            if name.startswith("projection/source/"):
                role = "inspection-projection"
            elif name.startswith("mesh/"):
                role = "inspection-mesh"
            elif name.startswith("projection/rendered/"):
                role = "livery-section-preview"
            elif name.startswith("preview/"):
                role = "preview"
            else:
                role = "package-data"
        result.append({"path": name, "role": role, "size": len(data), "sha256": _sha256(data)})
    return result


def _create_livery_artifact(
    source: Path | str,
    output: Path | str,
    *,
    game_folder: Path | str | None = None,
    vehicle_index_cache: Path | str | None = None,
    model_code_override: str = "",
    target_car_id_override: int | None = None,
    private_preview: bool = False,
    _allow_unowned_private_preview: bool = False,
    _cancel_event=None,
    extra_members: dict[str, bytes] | None = None,
    title_override: str = "",
    render_sections: bool = True,
    predecoded_surface_design: dict[str, Any] | None = None,
    predecoded_privacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if _allow_unowned_private_preview and not private_preview:
        raise FullLiveryPackageError("Unowned sources are restricted to source-free private previews.")
    if render_sections:
        raise FullLiveryPackageError(
            "CPU-painted preview generation was removed. Use the GPU-only Viewer."
        )
    if not render_sections and not private_preview:
        raise FullLiveryPackageError("Section rendering can be skipped only for local private previews.")
    source_path = Path(source)
    if source_path.is_dir():
        source_path = source_path / "C_livery"
    if source_path.name.casefold() != "c_livery" or not source_path.is_file():
        raise FullLiveryPackageError("Choose an FH6 C_livery file or its containing Livery_* folder.")

    raw_container = source_path.read_bytes()
    if _cancel_event is not None and _cancel_event.is_set():
        raise concurrent.futures.CancelledError()
    payload = unwrap_forza_container(source_path)
    if len(payload) < 0x1A or payload[:4] != b"vlrc":
        raise FullLiveryPackageError("The selected file is not an FH6 C_livery container.")
    source_state = struct.unpack_from("<I", payload, 0x08)[0]
    if predecoded_privacy is not None:
        if not private_preview or render_sections:
            raise FullLiveryPackageError(
                "Predecoded privacy evidence is restricted to section-free local private previews."
            )
        privacy = dict(predecoded_privacy)
        if (
            not isinstance(privacy.get("source_owned"), bool)
            or not isinstance(privacy.get("contains_foreign_groups"), bool)
            or not isinstance(privacy.get("foreign_group_count"), int)
            or isinstance(privacy.get("foreign_group_count"), bool)
            or int(privacy.get("foreign_group_count")) < 0
            or not isinstance(privacy.get("protected_group_offsets"), list)
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in privacy.get("protected_group_offsets"))
            or bool(privacy.get("contains_foreign_groups")) != bool(int(privacy.get("foreign_group_count")) > 0)
        ):
            raise FullLiveryPackageError("The predecoded privacy evidence is malformed.")
    else:
        privacy = inspect_clivery_privacy(payload)
    if not privacy["source_owned"] and not _allow_unowned_private_preview:
        raise FullLiveryPackageError("This full livery belongs to another player and cannot be opened or exported by the Viewer.")
    if privacy["contains_foreign_groups"] and not private_preview:
        raise FullLiveryPackageError(
            "This livery contains vinyl groups created by another player. Remove every foreign vinyl group in FH6 "
            "and save the livery again before exporting it from the Viewer."
        )
    embedded_car_id = struct.unpack_from("<I", payload, 0x10)[0]
    if target_car_id_override is not None and not private_preview:
        raise FullLiveryPackageError("A target Car ID override is restricted to private research previews.")
    car_id = int(target_car_id_override or embedded_car_id)
    if car_id <= 0:
        raise FullLiveryPackageError("The resolved target Car ID is invalid.")
    category_state = struct.unpack_from("<I", payload, 0x14)[0]
    predecoded_raster_ids: list[int] | None = None
    if predecoded_surface_design is not None:
        if not private_preview or render_sections:
            raise FullLiveryPackageError(
                "A predecoded surface design is restricted to section-free local private previews."
            )
        design = predecoded_surface_design
        if not isinstance(design, dict) or str(design.get("format") or "") != SURFACE_DESIGN_FORMAT:
            raise FullLiveryPackageError("The predecoded canonical surface design is unsupported.")
        try:
            design_car_id = int(design.get("car_id") or 0)
        except (TypeError, ValueError) as exc:
            raise FullLiveryPackageError("The predecoded canonical surface design has an invalid Car ID.") from exc
        if design_car_id and design_car_id != embedded_car_id:
            raise FullLiveryPackageError(
                "The predecoded canonical surface design does not belong to the selected C_livery."
            )
        _, counts, payload_meta = extract_livery_payload(payload)
        decoded_section_counts = {section: 0 for section in LIVERY_SECTION_NAMES}
        for surface in design.get("surfaces") or []:
            if not isinstance(surface, dict):
                raise FullLiveryPackageError("The predecoded canonical surface design is malformed.")
            section = str(surface.get("source_section") or "")
            if section not in decoded_section_counts:
                raise FullLiveryPackageError(
                    f"The predecoded canonical surface design uses unsupported livery section {section!r}."
                )
            try:
                decoded_count = int(surface.get("shape_count") if surface.get("shape_count") is not None else len(surface.get("shapes") or []))
            except (TypeError, ValueError) as exc:
                raise FullLiveryPackageError("The predecoded canonical surface design has an invalid shape count.") from exc
            decoded_section_counts[section] += decoded_count
        report = design.get("decoder_report") or {}
        decode_report = {
            "warnings": list(report.get("warnings") or []),
            "identity_warnings": [],
        }
        layers = {"layers": []}
        predecoded_raster_ids = sorted({
            int(value) for value in (design.get("raster_ids") or []) if int(value) > 0
        })
    else:
        layers, decode_report, counts, payload_meta = _decode_livery_contract(payload)
        layers_by_section = _section_layers(layers["layers"])
        decoded_section_counts = {section: len(layers_by_section[section]) for section in LIVERY_SECTION_NAMES}

    section_count_mismatches: list[dict[str, int | str]] = []
    for section, declared_count in zip(LIVERY_SECTION_NAMES, counts):
        decoded_count = int(decoded_section_counts.get(section, 0))
        if decoded_count != int(declared_count):
            mismatch = {
                "section": section,
                "declared": int(declared_count),
                "decoded": decoded_count,
            }
            section_count_mismatches.append(mismatch)
            if private_preview:
                decode_report.setdefault("warnings", []).append(
                    f"{section}: rendered {decoded_count} physically embedded placement(s); "
                    f"the save declares {int(declared_count)} logical placement(s)"
                )
                continue
            raise FullLiveryPackageError(
                f"The {section} livery section decoded {decoded_count} of "
                f"{int(declared_count)} declared placements."
            )
    header_path = source_path.parent / "header"
    header = header_path.read_bytes() if header_path.is_file() else b""
    thumbnail_path = source_path.parent / "bigThumb.webp"
    thumbnail = thumbnail_path.read_bytes() if thumbnail_path.is_file() else b""
    if thumbnail:
        try:
            with Image.open(io.BytesIO(thumbnail)) as image:
                if image.format != "WEBP" or image.size != (670, 376):
                    raise FullLiveryPackageError("The FH6 livery thumbnail has invalid dimensions.")
                image.verify()
        except FullLiveryPackageError:
            raise
        except Exception as exc:
            raise FullLiveryPackageError("The FH6 livery thumbnail is unreadable.") from exc
    title = title_override.strip() or _read_header_title(header) or source_path.parent.name

    vehicle: VehicleAsset | None = None
    vehicle_meta: dict[str, Any] = {
        "car_id": car_id,
        "model_code": model_code_override.strip(),
        "resolution": "manual" if model_code_override.strip() else "unresolved",
        "portable_mesh": False,
    }
    projection_metadata: dict[str, Any] = {}
    if game_folder:
        index = load_or_build_vehicle_asset_index(game_folder, vehicle_index_cache)
        vehicle = index.get(car_id)
        if vehicle:
            vehicle_meta = inspect_vehicle_archive(vehicle)
            vehicle_meta["resolution"] = "local-game-archive-index"
            vehicle_meta["portable_mesh"] = False
            projection_metadata = read_projection_metadata(vehicle)
        elif not model_code_override:
            vehicle_meta["resolution_detail"] = "No local car archive advertised the livery target ID."

    # CPUプレビューのラスタライズは削除済み。原本レイヤーはデータとして保持する。
    # 製品Viewerは原本からWebGL2で直接描画する。
    section_textures = {}
    raster_verified = False
    unresolved_raster_ids = (
        list(predecoded_raster_ids)
        if predecoded_raster_ids is not None
        else sorted({
            int(layer.get("raster_id") or 0)
            for layer in layers["layers"]
            if layer.get("is_raster_logo") and int(layer.get("raster_id") or 0) > 0
        })
    )
    decode_report.setdefault("warnings", []).append(
        "CPU-painted section images are not generated; WebGL2-only Viewer required"
    )
    projection_index = {
        "format": "lo4fh6_projection_source_v1",
        "model_code": vehicle_meta.get("model_code", ""),
        "source_inventory": projection_metadata.get("source_inventory", []),
        "vehicle_map_path": "projection/vehicle-map.json" if projection_metadata else "",
        "decoded_for_viewer": False,
    }
    members: dict[str, bytes] = {
        "mesh/vehicle.json": _json_bytes(vehicle_meta),
        "projection/index.json": _json_bytes(projection_index),
    }
    if not private_preview:
        members["source/fh6/C_livery"] = raw_container
        members["livery/layers.json"] = _json_bytes(layers)
        if header:
            members["source/fh6/header"] = header
        if thumbnail:
            members["source/fh6/bigThumb.webp"] = thumbnail
    if projection_metadata:
        members["projection/vehicle-map.json"] = _json_bytes(projection_metadata)
    for section, data in section_textures.items():
        members[f"projection/rendered/{section}.png"] = data
    projection_index["rendered_sections"] = [
        {"section": section, "path": f"projection/rendered/{section}.png", "width": 2048, "height": 1024}
        for section in section_textures
    ]
    projection_index["decoded_for_viewer"] = bool(section_textures)
    preview_complete = not section_count_mismatches and raster_verified
    projection_index["source_container_preserved"] = not private_preview
    projection_index["canonical_decode_complete"] = not section_count_mismatches
    projection_index["preview_complete"] = preview_complete
    projection_index["source_exact"] = preview_complete
    projection_index["incomplete_preview"] = not preview_complete
    projection_index["native_raster_verified"] = raster_verified
    projection_index["unresolved_raster_ids"] = unresolved_raster_ids
    members["mesh/vehicle.json"] = _json_bytes(vehicle_meta)
    members["projection/index.json"] = _json_bytes(projection_index)
    for name, data in (extra_members or {}).items():
        safe_name = _safe_member_name(name)
        if safe_name == "manifest.json" or safe_name in members:
            raise FullLiveryPackageError(f"duplicate or reserved package member: {safe_name}")
        members[safe_name] = bytes(data)

    source_manifest = {
        "game": "fh6",
        "kind": (
            "local-unowned-preview"
            if not privacy["source_owned"]
            else ("local-preview" if private_preview else "C_livery")
        ),
        "source_folder_name": source_path.parent.name,
        "source_state": source_state,
        "owned": bool(privacy["source_owned"]),
        "embedded_car_id": embedded_car_id,
    }
    if not private_preview:
        source_manifest.update({
            "container_sha256": _sha256(raw_container),
            "payload_sha256": _sha256(payload),
            "payload_size": len(payload),
            "container_version": struct.unpack_from("<I", payload, 0x04)[0],
            "locked": False,
            "category_state": category_state,
        })

    decode_warnings = list(dict.fromkeys(str(value) for value in decode_report.get("warnings", []) if value))
    manifest = {
        "format": PRIVATE_PREVIEW_FORMAT if private_preview else PACKAGE_FORMAT,
        "format_version": 1,
        "compiler_revision": PACKAGE_COMPILER_REVISION,
        "package_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source_manifest,
        "livery": {
            "title": title,
            "target_car_id": car_id,
            "logical_placement_count": sum(counts),
            "decoded_layer_count": sum(int(decoded_section_counts.get(section, 0)) for section in LIVERY_SECTION_NAMES),
            "section_counts": dict(zip(LIVERY_SECTION_NAMES, counts)),
            "decoded_section_counts": {
                section: int(decoded_section_counts.get(section, 0)) for section in LIVERY_SECTION_NAMES
            },
            "section_count_mismatches": section_count_mismatches,
            "decode_warnings": decode_warnings,
            "preview_complete": preview_complete,
            "unresolved_raster_ids": unresolved_raster_ids,
            "payload_offsets": payload_meta,
        },
        "vehicle": vehicle_meta,
        "sharing": {
            "exportable": not private_preview,
            "preview_only": private_preview,
            "local_unowned_preview": bool(private_preview and not privacy["source_owned"]),
            "contains_foreign_vinyl_groups": bool(privacy["contains_foreign_groups"]),
            "foreign_vinyl_group_count": int(privacy["foreign_group_count"]),
            "external_game_assets_embedded": False,
            "mesh_policy": "resolve matching car mesh from the recipient's own local game installation",
            "opaque_source_record": not private_preview,
            "source_container_preserved": not private_preview,
            "preview_complete": preview_complete,
            "unresolved_raster_references": bool(unresolved_raster_ids),
            "source_identity_policy": (
                "private rendered inspection only"
                if private_preview
                else "rewrite destination-owned identity and creator metadata during supported installation"
            ),
        },
        "compatibility": {} if private_preview else _target_policies(car_id),
        "files": _files_manifest(members),
    }
    manifest_bytes = _json_bytes(manifest)
    output_path = Path(output)
    extension = PRIVATE_PREVIEW_EXTENSION if private_preview else PACKAGE_EXTENSION
    if output_path.suffix.casefold() != extension:
        output_path = output_path.with_suffix(extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".tmp", dir=output_path.parent)
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            bundle.writestr("manifest.json", manifest_bytes)
            for name, data in sorted(members.items()):
                bundle.writestr(name, data)
        if private_preview:
            validate_livery_inspection_artifact(temporary_path)
        else:
            validate_full_livery_package(
                temporary_path,
                game_folder=game_folder,
                verify_previews=True,
            )
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {**manifest, "package_path": str(output_path.resolve())}


def create_full_livery_package(
    source: Path | str,
    output: Path | str,
    *,
    game_folder: Path | str | None = None,
    vehicle_index_cache: Path | str | None = None,
    model_code_override: str = "",
    extra_members: dict[str, bytes] | None = None,
    title_override: str = "",
) -> dict[str, Any]:
    return _create_livery_artifact(
        source,
        output,
        game_folder=game_folder,
        vehicle_index_cache=vehicle_index_cache,
        model_code_override=model_code_override,
        private_preview=False,
        extra_members=extra_members,
        title_override=title_override,
    )


def create_local_livery_preview(
    source: Path | str,
    output: Path | str,
    *,
    game_folder: Path | str | None = None,
    vehicle_index_cache: Path | str | None = None,
    model_code_override: str = "",
    target_car_id_override: int | None = None,
    render_sections: bool = True,
    predecoded_surface_design: dict[str, Any] | None = None,
    predecoded_privacy: dict[str, Any] | None = None,
    _allow_unowned_private_preview: bool = False,
    _cancel_event=None,
) -> dict[str, Any]:
    return _create_livery_artifact(
        source,
        output,
        game_folder=game_folder,
        vehicle_index_cache=vehicle_index_cache,
        model_code_override=model_code_override,
        target_car_id_override=target_car_id_override,
        private_preview=True,
        render_sections=render_sections,
        predecoded_surface_design=predecoded_surface_design,
        predecoded_privacy=predecoded_privacy,
        _allow_unowned_private_preview=_allow_unowned_private_preview,
        _cancel_event=_cancel_event,
    )


def _read_manifest(bundle: zipfile.ZipFile, *, allow_private_preview: bool = False) -> dict[str, Any]:
    try:
        info = bundle.getinfo("manifest.json")
    except KeyError as exc:
        raise FullLiveryPackageError("The package has no manifest.json.") from exc
    if info.file_size > MAX_MANIFEST_BYTES:
        raise FullLiveryPackageError("The package manifest is too large.")
    try:
        manifest = _json_from_bytes(bundle.read(info))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FullLiveryPackageError("The package manifest is invalid.") from exc
    allowed_formats = {PACKAGE_FORMAT}
    if allow_private_preview:
        allowed_formats.add(PRIVATE_PREVIEW_FORMAT)
    if not isinstance(manifest, dict) or manifest.get("format") not in allowed_formats:
        raise FullLiveryPackageError("This is not a supported full-livery package.")
    if manifest.get("format_version") != 1:
        raise FullLiveryPackageError("This package uses an unsupported full-livery format version.")
    return manifest


def _validate_livery_artifact(
    path: Path | str,
    *,
    allow_private_preview: bool,
    allow_legacy: bool = False,
    game_folder: Path | str | None = None,
    verify_previews: bool = False,
) -> dict[str, Any]:
    package = Path(path)
    try:
        with zipfile.ZipFile(package) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_PACKAGE_FILES:
                raise FullLiveryPackageError("The package contains too many files.")
            total = 0
            seen: set[str] = set()
            for info in infos:
                safe = _safe_member_name(info.filename)
                folded = safe.casefold()
                if folded in seen:
                    raise FullLiveryPackageError(f"The package contains duplicate path {safe}.")
                seen.add(folded)
                if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
                    raise FullLiveryPackageError(f"Package member {safe} exceeds the size limit.")
                total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise FullLiveryPackageError("The expanded package exceeds the size limit.")
            manifest = _read_manifest(bundle, allow_private_preview=allow_private_preview)
            private_preview = manifest.get("format") == PRIVATE_PREVIEW_FORMAT
            _canonical_package_id(manifest.get("package_id"))
            try:
                compiler_revision = int(manifest.get("compiler_revision") or 0)
            except (TypeError, ValueError) as exc:
                raise FullLiveryPackageError("The package compiler revision is invalid.") from exc
            if compiler_revision > PACKAGE_COMPILER_REVISION:
                raise FullLiveryPackageError(
                    "This package was created by a newer livery compiler and cannot be opened safely."
                )
            if compiler_revision != PACKAGE_COMPILER_REVISION and not allow_legacy:
                raise FullLiveryPackageError(
                    f"This package uses livery compiler revision {compiler_revision}; "
                    f"revision {PACKAGE_COMPILER_REVISION} is required. Upgrade the package before opening it."
                )
            records = manifest.get("files")
            if not isinstance(records, list):
                raise FullLiveryPackageError("The package file manifest is missing.")
            recorded_names: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    raise FullLiveryPackageError("The package file manifest contains an invalid record.")
                name = _safe_member_name(str(record.get("path", "")))
                if name.casefold() in recorded_names:
                    raise FullLiveryPackageError(f"The package manifest repeats member {name}.")
                recorded_names.add(name.casefold())
                try:
                    data = bundle.read(name)
                except KeyError as exc:
                    raise FullLiveryPackageError(f"Required package member {name} is missing.") from exc
                if len(data) != int(record.get("size", -1)) or _sha256(data) != record.get("sha256"):
                    raise FullLiveryPackageError(f"Package member {name} failed its integrity check.")
            required = {"mesh/vehicle.json", "projection/index.json"}
            if not private_preview:
                required.update({"source/fh6/C_livery", "livery/layers.json"})
            if not required.issubset({str(record.get("path", "")) for record in records if isinstance(record, dict)}):
                raise FullLiveryPackageError("The package is missing required full-livery data.")
            archive_names = {info.filename.casefold() for info in infos if info.filename != "manifest.json"}
            if archive_names != recorded_names:
                raise FullLiveryPackageError("The package contains untracked or unlisted members.")

            source = manifest.get("source") or {}
            livery = manifest.get("livery") or {}
            try:
                vehicle = _json_from_bytes(bundle.read("mesh/vehicle.json"))
                projection = _json_from_bytes(bundle.read("projection/index.json"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise FullLiveryPackageError("Canonical layer or vehicle metadata is invalid.") from exc
            actual_car_id = int(livery.get("target_car_id") or -1)
            if private_preview:
                forbidden = {"source/fh6/c_livery", "source/fh6/header", "livery/layers.json"}
                if forbidden.intersection(recorded_names):
                    raise FullLiveryPackageError("A private livery preview contains shareable source data.")
                sharing = manifest.get("sharing") or {}
                if sharing.get("exportable") is not False or sharing.get("preview_only") is not True:
                    raise FullLiveryPackageError("The private livery preview policy is invalid.")
                local_unowned = sharing.get("local_unowned_preview") is True
                if source.get("owned") is not True:
                    if not local_unowned or source.get("kind") != "local-unowned-preview":
                        raise FullLiveryPackageError("The private livery preview is not an owned source.")
                elif local_unowned:
                    raise FullLiveryPackageError("The private livery preview has an inconsistent ownership policy.")
            else:
                raw_container = bundle.read("source/fh6/C_livery")
                payload = raw_container if raw_container.startswith(b"vlrc") else unwrap_forza_container_bytes(raw_container, package)
                if len(payload) < 0x1A or payload[:4] != b"vlrc":
                    raise FullLiveryPackageError("The preserved source member is not an FH6 C_livery record.")
                privacy = inspect_clivery_privacy(payload)
                if not privacy["source_owned"] or privacy["contains_foreign_groups"]:
                    raise FullLiveryPackageError(
                        "This package contains artwork created by another player and cannot be shared through the Viewer."
                    )
                actual_car_id = struct.unpack_from("<I", payload, 0x10)[0]
                actual_state = struct.unpack_from("<I", payload, 0x08)[0]
                if actual_car_id != int(livery.get("target_car_id") or -1):
                    raise FullLiveryPackageError("The manifest car identity does not match the preserved source record.")
                if actual_state != int(source.get("source_state") if source.get("source_state") is not None else -1):
                    raise FullLiveryPackageError("The manifest source state does not match the preserved source record.")
                if _sha256(raw_container) != source.get("container_sha256") or _sha256(payload) != source.get("payload_sha256"):
                    raise FullLiveryPackageError("The source identity hashes do not match the preserved record.")
                try:
                    layers = _json_from_bytes(bundle.read("livery/layers.json"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise FullLiveryPackageError("Canonical layer or vehicle metadata is invalid.") from exc
                if not isinstance(layers, dict) or layers.get("format") != "lo4_full_livery_layers_v1":
                    raise FullLiveryPackageError("Canonical layer data uses an unsupported format.")
                if int(layers.get("target_car_id") or -1) != actual_car_id:
                    raise FullLiveryPackageError("Canonical layer data targets a different car.")
                if compiler_revision == PACKAGE_COMPILER_REVISION:
                    if "source/fh6/bigthumb.webp" in recorded_names:
                        try:
                            with Image.open(io.BytesIO(bundle.read("source/fh6/bigThumb.webp"))) as image:
                                if image.format != "WEBP" or image.size != (670, 376):
                                    raise FullLiveryPackageError("The FH6 source thumbnail is invalid.")
                                image.verify()
                        except FullLiveryPackageError:
                            raise
                        except Exception as exc:
                            raise FullLiveryPackageError("The FH6 source thumbnail is unreadable.") from exc
                    try:
                        canonical_layers, decode_report, counts, payload_meta = _decode_livery_contract(payload)
                    except Exception as exc:
                        raise FullLiveryPackageError(
                            "The preserved source record could not be decoded by the current livery compiler."
                        ) from exc
                    if layers != canonical_layers:
                        raise FullLiveryPackageError(
                            "Canonical layer data does not match the preserved FH6 source record."
                        )
                    expected_counts = dict(zip(LIVERY_SECTION_NAMES, counts))
                    if livery.get("section_counts") != expected_counts:
                        raise FullLiveryPackageError("Manifest section counts do not match the preserved source record.")
                    if int(livery.get("logical_placement_count") or 0) != sum(counts):
                        raise FullLiveryPackageError("Manifest placement count does not match the preserved source record.")
                    if int(livery.get("decoded_layer_count") or 0) != len(canonical_layers["layers"]):
                        raise FullLiveryPackageError("Manifest decoded layer count does not match the preserved source record.")
                    if livery.get("payload_offsets") != payload_meta:
                        raise FullLiveryPackageError("Manifest source offsets do not match the preserved source record.")
                    unresolved_raw = projection.get("unresolved_raster_ids")
                    if not isinstance(unresolved_raw, list) or any(
                        isinstance(value, bool) or not isinstance(value, int) for value in unresolved_raw
                    ):
                        raise FullLiveryPackageError("The unresolved raster-reference inventory is invalid.")
                    unresolved_raster_ids = [int(value) for value in unresolved_raw]
                    if (
                        unresolved_raster_ids != sorted(set(unresolved_raster_ids))
                        or any(value <= 0 for value in unresolved_raster_ids)
                    ):
                        raise FullLiveryPackageError("The unresolved raster-reference inventory is invalid.")
                    canonical_raster_ids = {
                        int(layer.get("raster_id") or 0)
                        for layer in canonical_layers["layers"]
                        if layer.get("is_raster_logo") and int(layer.get("raster_id") or 0) > 0
                    }
                    if not set(unresolved_raster_ids).issubset(canonical_raster_ids):
                        raise FullLiveryPackageError(
                            "The package declares an unresolved raster reference that is absent from its source."
                        )
                    if livery.get("unresolved_raster_ids") != unresolved_raster_ids:
                        raise FullLiveryPackageError("Manifest unresolved raster references do not match the preview contract.")
                    if livery.get("section_count_mismatches") not in (None, []):
                        raise FullLiveryPackageError("A shareable package contains an incomplete canonical decode.")
                    preview_complete = not unresolved_raster_ids
                    if projection.get("source_container_preserved") is not True:
                        raise FullLiveryPackageError("The package does not declare preservation of its FH6 source container.")
                    if projection.get("canonical_decode_complete") is not True:
                        raise FullLiveryPackageError("The package does not declare a complete canonical decode.")
                    if projection.get("preview_complete") is not preview_complete:
                        raise FullLiveryPackageError("The package preview-completeness declaration is inconsistent.")
                    if projection.get("source_exact") is not preview_complete:
                        raise FullLiveryPackageError("The package source-exact preview declaration is inconsistent.")
                    if projection.get("incomplete_preview") is not (not preview_complete):
                        raise FullLiveryPackageError("The package incomplete-preview declaration is inconsistent.")
                    if projection.get("native_raster_verified") is not preview_complete:
                        raise FullLiveryPackageError("The package raster-verification declaration is inconsistent.")
                    if livery.get("preview_complete") is not preview_complete:
                        raise FullLiveryPackageError("Manifest preview completeness does not match the preview contract.")
                    sharing = manifest.get("sharing") or {}
                    if sharing.get("source_container_preserved") is not True:
                        raise FullLiveryPackageError("The package sharing policy does not preserve the source container.")
                    if sharing.get("preview_complete") is not preview_complete:
                        raise FullLiveryPackageError("The package sharing preview policy is inconsistent.")
                    if sharing.get("unresolved_raster_references") is not bool(unresolved_raster_ids):
                        raise FullLiveryPackageError("The package unresolved-raster sharing policy is inconsistent.")
                    expected_sections = [
                        section for section, count in zip(LIVERY_SECTION_NAMES, counts) if int(count) > 0
                    ]
                    if not isinstance(projection, dict):
                        raise FullLiveryPackageError("The projection metadata is invalid.")
                    rendered = projection.get("rendered_sections")
                    if not isinstance(rendered, list):
                        raise FullLiveryPackageError("The package has no complete rendered-section inventory.")
                    rendered_sections: list[str] = []
                    for record in rendered:
                        if not isinstance(record, dict):
                            raise FullLiveryPackageError("The rendered-section inventory is invalid.")
                        section = str(record.get("section") or "")
                        member = str(record.get("path") or "")
                        if section not in LIVERY_SECTION_NAMES or member != f"projection/rendered/{section}.png":
                            raise FullLiveryPackageError("The rendered-section inventory contains an invalid entry.")
                        if int(record.get("width") or 0) != 2048 or int(record.get("height") or 0) != 1024:
                            raise FullLiveryPackageError("A rendered-section declaration has invalid dimensions.")
                        if section in rendered_sections:
                            raise FullLiveryPackageError("The rendered-section inventory contains a duplicate section.")
                        rendered_sections.append(section)
                        try:
                            rendered_data = bundle.read(member)
                            with Image.open(io.BytesIO(rendered_data)) as image:
                                if image.size != (2048, 1024) or image.format != "PNG":
                                    raise FullLiveryPackageError(
                                        f"The rendered {section} livery section has invalid dimensions."
                                    )
                                image.verify()
                        except FullLiveryPackageError:
                            raise
                        except Exception as exc:
                            raise FullLiveryPackageError(
                                f"The rendered {section} livery section is missing or unreadable."
                            ) from exc
                    if rendered_sections != expected_sections:
                        raise FullLiveryPackageError(
                            "The package does not contain one complete render for every populated livery section."
                        )
                    if verify_previews:
                        raise FullLiveryPackageError(
                            "CPU-painted preview regeneration was removed; "
                            "GPU-only output must be verified in WebGL2."
                        )
            manifest_vehicle = manifest.get("vehicle") or {}
            if not isinstance(vehicle, dict) or int(vehicle.get("car_id") or -1) != actual_car_id:
                raise FullLiveryPackageError("Vehicle metadata does not match the source car identity.")
            if int(manifest_vehicle.get("car_id") or -1) != actual_car_id:
                raise FullLiveryPackageError("Manifest vehicle metadata does not match the source car identity.")
            if str(manifest_vehicle.get("model_code") or "") != str(vehicle.get("model_code") or ""):
                raise FullLiveryPackageError("Manifest and packaged vehicle model identities disagree.")
            embedded_mesh = "mesh/model.glb" in {str(record.get("path", "")) for record in records}
            if compiler_revision == PACKAGE_COMPILER_REVISION:
                if embedded_mesh or bool(vehicle.get("portable_mesh")):
                    raise FullLiveryPackageError(
                        "Current livery packages must resolve the chassis from the recipient's local game installation."
                    )
                sharing = manifest.get("sharing") or {}
                if sharing.get("external_game_assets_embedded") is not False:
                    raise FullLiveryPackageError("The package game-asset policy is invalid.")
            return manifest
    except FullLiveryPackageError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, KeyError, TypeError, ValueError, struct.error) as exc:
        raise FullLiveryPackageError("The selected file is not a readable ZIP-based livery package.") from exc


def validate_full_livery_package(
    path: Path | str,
    *,
    game_folder: Path | str | None = None,
    verify_previews: bool = False,
) -> dict[str, Any]:
    """持運び可能な原本契約と全パッケージ構成要素を検証する。

    ``verify_previews`` はローカルCompilerの再現性を追加検証する。
    ラスタライザーの版やローカルのゲーム図柄は、保全されたLivery自体が
    不変でも異なる場合があるため、受取時でなく作成時のみ使用する。
    """
    return _validate_livery_artifact(
        path,
        allow_private_preview=False,
        game_folder=game_folder,
        verify_previews=verify_previews,
    )


def validate_livery_inspection_artifact(path: Path | str) -> dict[str, Any]:
    return _validate_livery_artifact(path, allow_private_preview=True)


def package_compiler_revision(path: Path | str) -> int:
    package = Path(path)
    try:
        with zipfile.ZipFile(package) as bundle:
            manifest = _read_manifest(bundle)
        return int(manifest.get("compiler_revision") or 0)
    except FullLiveryPackageError:
        raise
    except (TypeError, ValueError, zipfile.BadZipFile, OSError) as exc:
        raise FullLiveryPackageError("The selected package has no readable compiler revision.") from exc


def migrate_full_livery_package(
    source: Path | str,
    output: Path | str | None = None,
    *,
    game_folder: Path | str | None = None,
    vehicle_index_cache: Path | str | None = None,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    manifest = _validate_livery_artifact(
        source_path,
        allow_private_preview=False,
        allow_legacy=True,
    )
    revision = int(manifest.get("compiler_revision") or 0)
    if revision == PACKAGE_COMPILER_REVISION:
        current = validate_full_livery_package(source_path)
        target = Path(output).resolve() if output else source_path
        if target != source_path:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
            temporary.unlink(missing_ok=True)
            try:
                shutil.copy2(source_path, temporary)
                validate_full_livery_package(temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return {**current, "package_path": str(target)}

    target = Path(output).resolve() if output else source_path
    title = str((manifest.get("livery") or {}).get("title") or source_path.stem)
    with tempfile.TemporaryDirectory(prefix="lo4fh6-livery-migration-") as temporary:
        source_root = Path(temporary) / "source"
        source_root.mkdir(parents=True)
        with zipfile.ZipFile(source_path) as bundle:
            (source_root / "C_livery").write_bytes(bundle.read("source/fh6/C_livery"))
            if "source/fh6/header" in bundle.namelist():
                (source_root / "header").write_bytes(bundle.read("source/fh6/header"))
        result = create_full_livery_package(
            source_root / "C_livery",
            target,
            game_folder=game_folder,
            vehicle_index_cache=vehicle_index_cache,
            model_code_override=str((manifest.get("vehicle") or {}).get("model_code") or ""),
            title_override=title,
        )
    result["migrated_from_revision"] = revision
    return result


def inspect_full_livery_package(path: Path | str, *, allow_legacy: bool = False) -> dict[str, Any]:
    manifest = _validate_livery_artifact(
        path,
        allow_private_preview=False,
        allow_legacy=allow_legacy,
    )
    return {
        "path": str(Path(path).resolve()),
        "package_id": manifest.get("package_id", ""),
        "title": manifest.get("livery", {}).get("title", ""),
        "game": manifest.get("source", {}).get("game", ""),
        "target_car_id": manifest.get("livery", {}).get("target_car_id", 0),
        "model_code": manifest.get("vehicle", {}).get("model_code", ""),
        "logical_placement_count": manifest.get("livery", {}).get("logical_placement_count", 0),
        "decoded_layer_count": manifest.get("livery", {}).get("decoded_layer_count", 0),
        "portable_mesh": bool(manifest.get("vehicle", {}).get("portable_mesh")),
        "compatibility": manifest.get("compatibility", {}),
    }


def read_package_member(path: Path | str, member: str, *, allow_private_preview: bool = False) -> bytes:
    safe = _safe_member_name(member)
    if allow_private_preview:
        validate_livery_inspection_artifact(path)
    else:
        validate_full_livery_package(path)
    with zipfile.ZipFile(path) as bundle:
        try:
            return bundle.read(safe)
        except KeyError as exc:
            raise FullLiveryPackageError(f"Package member {safe} is missing.") from exc


def iter_package_files(path: Path | str, *, allow_private_preview: bool = False) -> Iterable[str]:
    if allow_private_preview:
        validate_livery_inspection_artifact(path)
    else:
        validate_full_livery_package(path)
    with zipfile.ZipFile(path) as bundle:
        yield from (info.filename for info in bundle.infolist())
