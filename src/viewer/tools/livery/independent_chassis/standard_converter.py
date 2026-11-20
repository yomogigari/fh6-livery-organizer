"""FH6独立Carbin変換器の既存 --request JSON 互換入口（研究候補）。

参照製品 Program.csの契約を原著のバージョン付きソースと照合：
CarbinEntryが存在する場合はEntries/ManifestではなくCarbinを優先。
ゲーム原本・元ファイルは読み取り専用。旧変換EXEを起動しない。
未解決のSkin/Morph/Shader/FEOWを既定の完成GLBと偽らない。
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import stat
import struct
import sys
import zipfile

from .carbin_reader import parse_carbin
from .source_stock_scene import _highest_detail_lod, _source_entry
from .source_static_preview_selection import select_part_option_overlay, select_static_stock_instances
from .modelbin_geometry_decoder import parse_bundle, mesh_decode
from .source_stock_glb import build_research_stock_geometry_glb
from .source_scene_anchor_contract import audit_original_scene_anchors
from .source_material_shader_reference import build_original_material_shader_reference

MAX_REQUEST_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_SOURCE_FILES = 25000
MAX_SHADER_REFERENCE_BYTES = 8 * 1024 * 1024


class IndependentConverterNotReady(ValueError):
    """未検証の通常製品出力を拒否した（旧EXEへの代替起動なし）。"""


def _checked_path(value: object, suffix: str, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("independent converter: absolute file path required")
    path = Path(value)
    if not path.is_absolute() or path.suffix.casefold() != suffix or path.is_symlink():
        raise ValueError("independent converter: invalid source/output path")
    if must_exist:
        if not path.is_file():
            raise ValueError("independent converter: source FH6 archive not found")
    elif path.exists() or not path.parent.is_dir():
        raise ValueError("independent converter: output must be a new file in an existing folder")
    return path.resolve()


def _original_static_selection(archive: Path, scene: dict,
                               source_part_selection: dict[str, int] | None,
                               source_part_overlay_only: bool = False) -> list:
    """GLB段階（build_research_stock_geometry_glb）と同じ静止選択。

    __slod版を通常版の補いとして使うかの判定に、通常版ModelBinのMeshのLODビットを
    同じ原本ZIPから読む（source_lods_cohort_incomplete）。
    """
    with zipfile.ZipFile(archive) as source:
        members = {info.filename.casefold(): info for info in source.infolist() if not info.is_dir()}

        def _source_mesh_lod_masks(path: str) -> list[int]:
            raw = source.read(members[path.casefold()])
            masks = []
            for blob in parse_bundle(raw):
                if blob.tag != "Mesh":
                    continue
                mesh = mesh_decode(raw, blob)
                if mesh.index_count:
                    masks.append(mesh.lod)
            return masks

        if source_part_overlay_only:
            # 部品の選択肢の重ね合わせ：その選択肢で加わる部品だけ（GLBの作成と同じ選び方）。
            (family, option_id), = source_part_selection.items()
            return select_part_option_overlay(
                scene, _source_entry, family=family, option_id=option_id,
                modelbin_lod_masks=_source_mesh_lod_masks)[0]
        return select_static_stock_instances(
            scene, _source_entry, selected_part_ids=source_part_selection,
            modelbin_lod_masks=_source_mesh_lod_masks)


def _source_selection(archive: Path, *, source_original_static_selection: bool = False, source_part_selection: dict[str, int] | None = None, source_loose_entries: list[str] | None = None, source_part_overlay_only: bool = False) -> tuple[str, set[str]]:
    """元CarbinのSceneが優先。ManifestのEntriesを完全一致要求しない。"""
    with zipfile.ZipFile(archive) as source:
        records = [v for v in source.infolist() if not v.is_dir()]
        if not records or len(records) > MAX_SOURCE_FILES:
            raise ValueError("independent converter: invalid original archive inventory")
        names: dict[str, str] = {}
        for member in records:
            name = member.filename
            path = PurePosixPath(name)
            if (
                not name or "\\" in name or name.startswith("/") or ":" in name
                or "." in path.parts or ".." in path.parts or member.flag_bits & 1
                or stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK
                or member.file_size > 512 * 1024 * 1024 or name.casefold() in names
            ):
                raise ValueError("independent converter: unsafe or duplicate FH6 source entry")
            names[name.casefold()] = name
        carbin_files = [name for name in names if name.endswith(".carbin") and "/" not in name]
        if len(carbin_files) != 1:
            raise ValueError("independent converter: expected exactly one root Carbin")
        scene = parse_carbin(source.read(names[carbin_files[0]]))
    lod = _highest_detail_lod(scene["lod"])
    if source_loose_entries is not None:
        selected = {name.casefold() for name in source_loose_entries}
    elif source_original_static_selection:
        selected = {
            path.casefold()
            for _, path in _original_static_selection(archive, scene, source_part_selection,
                                                      source_part_overlay_only)
        }
    else:
        selected = {
            _source_entry(instance.path, scene["media"]).casefold()
            for instance in scene["models"]
            if instance.stock and (not instance.lod_flags or instance.lod_flags & lod)
        }
    if not selected or not selected.issubset(names):
        raise ValueError("independent converter: missing native Stock ModelBin source")
    return carbin_files[0], selected


def _validate_glb_container(glb: bytes) -> None:
    """
    研究用GLBであっても公開前に第一者出力の構造不正を拒否する。
    """
    if len(glb) < 20 or len(glb) % 4:
        raise ValueError("independent converter: malformed GLB container length")
    magic, version, total = struct.unpack_from("<4sII", glb)
    if magic != b"glTF" or version != 2 or total != len(glb):
        raise ValueError("independent converter: malformed GLB header")
    cursor = 12
    chunks = []
    while cursor < len(glb):
        if cursor + 8 > len(glb):
            raise ValueError("independent converter: truncated GLB chunk header")
        length, kind = struct.unpack_from("<I4s", glb, cursor)
        cursor += 8
        if length % 4 or cursor + length > len(glb):
            raise ValueError("independent converter: invalid GLB chunk length")
        chunks.append((kind, glb[cursor:cursor + length]))
        cursor += length
    if not chunks or chunks[0][0] != b"JSON" or len(chunks) > 2:
        raise ValueError("independent converter: invalid GLB chunk order")
    if len(chunks) == 2 and chunks[1][0] != b"BIN\x00":
        raise ValueError("independent converter: invalid GLB binary chunk")
    try:
        document = json.loads(chunks[0][1].decode("utf-8").rstrip(" \t\r\n"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("independent converter: invalid GLB JSON") from exc
    if (not isinstance(document, dict) or not isinstance(document.get("asset"), dict)
            or document["asset"].get("version") != "2.0"):
        raise ValueError("independent converter: invalid GLB asset")
    buffers = document.get("buffers", [])
    if not isinstance(buffers, list) or len(buffers) != (1 if len(chunks) == 2 else 0):
        raise ValueError("independent converter: invalid GLB buffers")
    if buffers and (not isinstance(buffers[0], dict)
                    or type(buffers[0].get("byteLength")) is not int
                    or buffers[0]["byteLength"] < 0
                    or not buffers[0]["byteLength"] <= len(chunks[1][1])
                    or len(chunks[1][1]) - buffers[0]["byteLength"] > 3):
        raise ValueError("independent converter: invalid GLB BIN size")




def _functional_static_preview_glb(glb: bytes, proof: dict) -> bytes:
    """
    構造・機能を確認したStatic Viewer入力を作成するが、FH6／Xbox外観の公開受入とはみなさない。
    元のSkin・Morph・Material・Shaderの未確認状態を保持し、製品受入と研究を区別する。
    """
    counts = proof.get("counts")
    if (not isinstance(counts, dict)
            or proof.get("lo4_static_preview_selection") is not True
            or proof.get("original_skeleton_blobs_and_matI_used") is not True):
        raise IndependentConverterNotReady(
            "independent converter: original Static/LOD source verification is incomplete")
    loose = proof.get("source_loose_entry_mode") is True
    if loose and (type(proof.get("source_loose_entry_count")) is not int
                  or proof["source_loose_entry_count"] <= 0
                  or proof["source_loose_entry_count"] != counts.get("stock_instances")):
        raise IndependentConverterNotReady("original loose ModelBin input coverage is incomplete")
    mesh_count = counts.get("source_stock_visible_meshes")
    source_paint_count = counts.get("lo4_static_classified_paint_meshes", 0)
    if (type(mesh_count) is not int or mesh_count <= 0
            or counts.get("lo4_static_expected_source_meshes") != mesh_count
            or type(counts.get("stock_instances")) is not int
            or counts["stock_instances"] <= 0
            or type(source_paint_count) is not int or source_paint_count < 0
            or source_paint_count > mesh_count):
        # Stock全体の幾何は必須。
        # 原本にCar Paint面がない車両でも参照製品同様に幾何を出力するが、Livery対応とは宣言しない。
        raise IndependentConverterNotReady(
            "independent converter: original Stock mesh or paint surface coverage unverified")
    if (len(glb) < 28 or glb[:4] != b"glTF"
            or struct.unpack_from("<I", glb, 8)[0] != len(glb)):
        raise ValueError("independent converter: invalid source GLB container")
    json_len, json_tag = struct.unpack_from("<I4s", glb, 12)
    if json_tag != b"JSON" or 20 + json_len + 8 > len(glb):
        raise ValueError("independent converter: invalid source GLB metadata chunk")
    document = json.loads(glb[20:20 + json_len])
    scenes = document.get("scenes")
    meshes = document.get("meshes")
    if (not isinstance(scenes, list) or len(scenes) != 1
            or not isinstance(meshes, list) or len(meshes) != mesh_count):
        raise ValueError("independent converter: source-verified GLB scene count mismatch")
    scene = scenes[0]
    extras = scene.get("extras")
    if (not isinstance(extras, dict)
            or not extras.get("lo4fh6_research_only")
            or extras.get("lo4fh6_release_approval") is not False):
        raise ValueError("independent converter: source GLB is not an isolated original candidate")
    # 表示可能なViewer入力は公開・Xbox画質の承認ではない。
    # 原本Material／Skin／Morphの警告を維持し、Shaderの実行時補正を加えない。
    # 製品Cache由来ゲートは専用Static範囲を検証し、旧研究GLBと混同しない。
    extras.pop("lo4fh6_research_only")
    extras["lo4fh6_static_preview_source_verified"] = True
    extras["lo4fh6_original_paint_surface_mesh_count"] = source_paint_count
    extras["lo4fh6_paint_livery_supported"] = bool(source_paint_count)
    extras["lo4fh6_paint_capability"] = (
        "SOURCE_PAINT_SURFACE_PRESENT__XBOX_UNVERIFIED"
        if source_paint_count else
        "NO_SOURCE_PAINT_SURFACE__LIVERY_APPLICATION_UNSUPPORTED"
    )
    # WheelStyle／FEOW装着は別機能として検証する。
    # 3輪・6輪の原本幾何は保持し、異なるTopologyに4輪FEOWの装着成功を主張しない。
    topology = proof.get("wheel_topology")
    if isinstance(topology, dict) and type(topology.get("standard_four_corner_eligible")) is bool:
        extras["lo4fh6_standard_four_corner_feow_eligible"] = topology["standard_four_corner_eligible"]
        extras["lo4fh6_original_wheelstyle_instance_count"] = topology.get(
            "original_unique_wheelstyle_instances", 0
        )
    extras["lo4fh6_static_preview_scope"] = (
        "ORIGINAL_MODELBIN_LOOSE_OVERLAY__VIEWER_FUNCTIONAL_CANDIDATE"
        if loose else "ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE"
    )
    if loose:
        if not all(
            isinstance(mesh, dict)
            and isinstance(mesh.get("extras"), dict)
            and mesh["extras"].get("lo4fh6_original_loose_modelbin_verified") is True
            for mesh in meshes
        ):
            raise IndependentConverterNotReady("original loose ModelBin mesh provenance is incomplete")
        extras["lo4fh6_loose_entry_source_verified"] = True
    extras["lo4fh6_release_approval"] = False
    extras["lo4fh6_xbox_visual_approval"] = False
    document["asset"]["generator"] = "LO4FH6 firstparty original-static functional Viewer candidate"
    source_bin = glb[20 + json_len:]
    encoded = json.dumps(
        document, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    total = 20 + len(encoded) + len(source_bin)
    if total > MAX_OUTPUT_BYTES:
        raise ValueError("independent converter: functional Viewer GLB exceeds bounded output size")
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(encoded), b"JSON")
        + encoded + source_bin
    )


def execute_request(request: dict, *, research_preview: bool = False,
                    verified_deformation_inputs: dict | None = None,
                    source_shader_reference: bytes | None = None,
                    source_material_library_archive: Path | str | None = None,
                    source_original_static_selection: bool = False,
                    source_part_selection: dict[str, int] | None = None,
                    source_loose_entries: list[str] | None = None,
                    source_part_overlay_only: bool = False) -> dict:
    """既存 --request を安全に解析。通常製品への未受入出力は拒否。"""
    if source_part_overlay_only and (not source_original_static_selection or source_loose_entries is not None
                                     or not isinstance(source_part_selection, dict)
                                     or len(source_part_selection) != 1):
        raise IndependentConverterNotReady('part option overlay requires exactly one Carbin part selection')
    if source_loose_entries is not None and (
        not isinstance(source_loose_entries, list) or not source_loose_entries
        or any(not isinstance(name, str) or not name.strip() or "\\" in name
               or ":" in name or name.startswith("/") or ".." in PurePosixPath(name).parts
               or not name.casefold().startswith("scene/")
               or not name.casefold().endswith(".modelbin")
               for name in source_loose_entries)
        or len({name.casefold() for name in source_loose_entries}) != len(source_loose_entries)
    ):
        raise ValueError("independent converter: invalid original loose ModelBin list")
    if source_loose_entries is not None and (not source_original_static_selection or source_part_selection):
        raise IndependentConverterNotReady('loose ModelBin conversion cannot mix with Carbin scene part selection')
    if source_part_selection and not source_original_static_selection:
        raise IndependentConverterNotReady('original Carbin part selection requires static source mode')
    if source_material_library_archive is not None and (
        not research_preview or source_shader_reference is not None
    ):
        raise ValueError("independent converter: original MaterialBin source archive requires exclusive PRIVATE research input")
    if source_shader_reference is not None and (
        not research_preview or not isinstance(source_shader_reference, bytes)
        or not 0 < len(source_shader_reference) <= MAX_SHADER_REFERENCE_BYTES
    ):
        raise ValueError("independent converter: original Shader evidence requires bounded PRIVATE research input")
    # 先に研究専用入力の不正を診断してから製品通常モードを判定する。
    # 不正なShader/MaterialBinを旧EXEへフォールバックさせない。
    if not research_preview and not source_original_static_selection:
        raise IndependentConverterNotReady(
            "independent converter: product static preview requires original static preview "
            "source selection; legacy EXE fallback is forbidden")
    if not isinstance(request, dict) or set(request) != {"archive", "output", "carbin_entry", "entries"}:
        raise ValueError("independent converter: unsupported JSON request contract")
    archive = _checked_path(request["archive"], ".zip", must_exist=True)
    output = _checked_path(request["output"], ".glb", must_exist=False)
    root_carbin, models = _source_selection(archive, source_original_static_selection=source_original_static_selection,
                                            source_part_selection=source_part_selection,
                                            source_loose_entries=source_loose_entries)
    shader_source_audit = None
    if source_material_library_archive is not None:
        original_material_library = _checked_path(
            str(source_material_library_archive), ".zip", must_exist=True
        )
        # 標準変換前に、元ModelBin MatI→元MaterialBin→Shader族をSHA結合。
        # 元資産ZIP・原本ShaderバイトはGitHubにも研究GLBにも同梱しない。
        source_shader_reference, shader_source_audit = build_original_material_shader_reference(
            archive, original_material_library, selected_modelbins=models
        )
    selected_carbin = request["carbin_entry"]
    if source_loose_entries is not None:
        if (selected_carbin != '' or request['entries'] != source_loose_entries):
            raise ValueError('independent converter: loose ModelBin request must use empty CarbinEntry and matching exact entries')
    elif not isinstance(selected_carbin, str) or not selected_carbin.strip():
        raise IndependentConverterNotReady('independent converter: original CarbinEntry is missing')
    if source_loose_entries is None and selected_carbin.replace("\\", "/").casefold() != root_carbin:
        raise ValueError("independent converter: selected Carbin mismatches original archive")
    entries = request["entries"]
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) and entry.strip()
        and entry.replace("\\", "/").casefold().endswith(".modelbin")
        and ".." not in PurePosixPath(entry.replace("\\", "/")).parts
        for entry in entries
    ):
        raise ValueError("independent converter: malformed advisory ModelBin entries")
    # 参照製品 Program.csではCarbinEntryがあればExtractSceneMeshesを使う。
    # EntriesはExtractLooseMeshes専用であり、Jaguar／Vivioの元Manifestも異なるためCarbin Stockと同一視しない。
    # Stock／LOD生成は研究と機能Viewerで共有し、参照製品 EXEは起動しない。
    # Scene SkeletonのAnchor研究と各ModelBin SkeletonのFindBoneWorld契約は別系統。
    # 無関係なScene World Pose条件で正しいSnapToParent／LODを拒否せず、骨変換を二重に適用しない。
    scene_anchor = None if source_original_static_selection else audit_original_scene_anchors(archive)
    # 原本ModelBin SHAとMatI/ShaderBin索引を既存アダプターで照合。
    # 元Shader証拠が無い場合、材料名からLivery/Glassを推測しない。
    glb, proof = build_research_stock_geometry_glb(
        archive, source_wheel_identity_trial=source_loose_entries is None,
        source_shader_reference=source_shader_reference,
        shader_role_trial=source_shader_reference is not None,
        verified_deformation_inputs=verified_deformation_inputs,
        source_original_static_selection=source_original_static_selection,
        source_part_selection=source_part_selection,
        source_loose_entries=source_loose_entries,
        source_part_overlay_only=source_part_overlay_only,
    )
    if (
        not 32 <= len(glb) <= MAX_OUTPUT_BYTES
        or sha256(glb).hexdigest() != proof.get("glb_sha256")
        or proof.get("GPU_Windows_Xbox") != "NOT_PERFORMED"
    ):
        raise ValueError("independent converter: generated GLB/proof mismatch")
    if not research_preview:
        glb = _functional_static_preview_glb(glb, proof)
    _validate_glb_container(glb)
    if source_original_static_selection:
        with zipfile.ZipFile(archive) as native:
            root_members=[info for info in native.infolist() if info.filename.casefold()==root_carbin]
            if len(root_members)!=1:
                raise ValueError("independent converter: ambiguous original root Carbin")
            selected_scene = parse_carbin(native.read(root_members[0]))
        expected_instances = (len(source_loose_entries) if source_loose_entries is not None
                              else len(_original_static_selection(archive, selected_scene,
                                        source_part_selection, source_part_overlay_only)))
        if expected_instances != proof["counts"].get("stock_instances"):
            raise ValueError("independent converter: original static preview Stock instance count mismatch")
        verified_attachments = proof["counts"].get("lo4_static_modelbin_attachment_bound", 0)
        no_match = proof["counts"].get("lo4_static_modelbin_attachment_no_match_kept_carbin", 0)
        if type(verified_attachments) is not int or type(no_match) is not int or (
            verified_attachments + no_match != expected_instances
        ):
            raise ValueError("independent converter: ModelBin attachment coverage inconsistent")
        scene_anchor = {
            "schema": "lo4fh6.firstparty-modelbin-static-attachment-audit.v1",
            "selected_stock_instances": expected_instances,
            "source_modelbin_attachment_matched": verified_attachments,
            "source_modelbin_attachment_not_applicable": no_match,
            "extra_scene_world_bone_transform_applied": False,
            "lo4_original_modelbin_bone_stage_used": True,
            "game_runtime_pose_accepted": False,
            "product_accepted": False,
        }
    elif scene_anchor["selected_stock_instances"] != proof["counts"].get("stock_instances"):
        raise ValueError("independent converter: original scene anchor/Stock instance coverage mismatch")
    unresolved = {
        key: int(proof.get("counts", {}).get(key, 0))
        for key in (
            "original_skin_data_unapplied_meshes",
            "original_morph_data_unapplied_meshes",
            "original_nonroot_attachment_unverified_meshes",
            "unverified_native_shader_visible_meshes",
        )
    }
    requirements = proof.get("source_deformation_requirements", [])
    if not isinstance(requirements, list):
        raise ValueError("independent converter: malformed source deformation requirements")
    if verified_deformation_inputs is not None:
        required_keys = {item["mesh_key"] for item in requirements}
        if len(required_keys) != len(requirements):
            raise ValueError("independent converter: duplicate source deformation mesh identity")
        if required_keys != set(verified_deformation_inputs):
            raise ValueError("independent converter: incomplete or extra source deformation evidence")
    # 通常製品のCacheゲートは、この出力の原本SHA・受入状態を別途厳密に検証する。
    with output.open("xb") as stream:
        stream.write(glb)
    return {
        "schema": ("lo4fh6.firstparty-chassis-static-viewer-candidate.v1"
                   if not research_preview else "lo4fh6.firstparty-chassis-request-research.v1"),
        "source": "firstparty-Carbin-ModelBin",
        "source_scene_mode": "loose" if source_loose_entries is not None else "carbin",
        "source_part_overlay_only": bool(source_part_overlay_only),
        "source_carbin_entry": root_carbin,
        "stock_source_modelbin_count": len(models),
        "manifest_entries_advisory": source_loose_entries is None,
        "research_only": bool(research_preview),
        "product_accepted": not research_preview,
        "static_preview_source_verified": not research_preview,
        "release_approved": False,
        "xbox_visual_approved": False,
        "unresolved_instance_count": 0,
        "glb_sha256": sha256(glb).hexdigest(),
        "unresolved": unresolved,
        "source_evidence": proof,
        "original_scene_anchor_evidence": scene_anchor,
        "verified_deformation_input_meshes": len(verified_deformation_inputs or {}),
        "source_shader_role_reference_supplied": source_shader_reference is not None,
        "source_shader_role_trial_unapproved": source_shader_reference is not None,
        "source_original_static_selection_research_only": bool(source_original_static_selection and research_preview),
        "source_original_static_selection": bool(source_original_static_selection),
        "source_part_selection": dict(source_part_selection or {}),
        "source_loose_entry_mode": source_loose_entries is not None,
        "source_loose_entry_count": len(source_loose_entries or []),
        "functional_static_preview": not research_preview,
        "source_paint_livery_supported": bool(
            proof.get("counts", {}).get("lo4_static_classified_paint_meshes", 0)),
        "source_wheel_four_corner_feow_eligible": bool(
            proof.get("wheel_topology", {}).get("standard_four_corner_eligible", False)),
        "source_material_shader_reference_evidence": shader_source_audit,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LO4FH6 independent FH6 chassis request converter")
    p.add_argument("--request", required=True, type=Path)
    p.add_argument("--research-preview-unapproved", action="store_true")
    p.add_argument("--research-verified-deformation-json", type=Path,
                   help="PRIVATE mesh-keyed source pose/slot evidence; research GLB only")
    p.add_argument("--research-source-shader-reference-json", type=Path,
                   help="PRIVATE source ModelBin SHA/MatI/Shader family crosswalk; research GLB only")
    p.add_argument("--research-original-static-preview-selection", "--research-lo4fh6-static-preview-selection", dest="research_original_static_preview_selection", action="store_true",
                   help="Reference-compatible static LOD/Shadow selection with PRIVATE originals; research only")
    p.add_argument("--research-source-materials-archive", type=Path,
                   help="PRIVATE original cars/_library/Materials.zip, source-linked research only")
    args = p.parse_args(argv)
    try:
        request_file = args.request
        if (
            request_file.is_symlink() or not request_file.is_file()
            or request_file.stat().st_size > MAX_REQUEST_BYTES
        ):
            raise ValueError("independent converter: invalid request JSON file")
        data = json.loads(request_file.read_text(encoding="utf-8-sig"))
        deformation = None
        if args.research_verified_deformation_json is not None:
            evidence_path = args.research_verified_deformation_json
            if (not args.research_preview_unapproved or evidence_path.is_symlink()
                    or not evidence_path.is_file()
                    or evidence_path.stat().st_size > MAX_REQUEST_BYTES * 64):
                raise ValueError("independent converter: invalid PRIVATE deformation evidence")
            deformation = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
            if not isinstance(deformation, dict):
                raise ValueError("independent converter: deformation evidence must be a mesh-keyed object")
        shader_reference = None
        if args.research_source_shader_reference_json is not None:
            path = args.research_source_shader_reference_json
            if (not args.research_preview_unapproved or path.is_symlink()
                    or not path.is_file() or path.suffix.casefold() != ".json"
                    or not 0 < path.stat().st_size <= MAX_SHADER_REFERENCE_BYTES):
                raise ValueError("independent converter: invalid PRIVATE source Shader reference")
            shader_reference = path.read_bytes()
        result = execute_request(data, research_preview=args.research_preview_unapproved,
                                 verified_deformation_inputs=deformation,
                                 source_shader_reference=shader_reference,
                                 source_material_library_archive=args.research_source_materials_archive,
                                 source_original_static_selection=args.research_original_static_preview_selection)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print("Independent FH6 conversion refused: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
