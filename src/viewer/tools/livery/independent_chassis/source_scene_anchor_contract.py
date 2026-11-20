"""Original Carbin/Scene Skeleton anchor identity audit; NEVER add its World Bone twice.

The previously tested extra Scene Skeleton multiplication displaced original
suspension parts in Jaguar and Vivio. This module verifies source references
only; all authored ModelBin rigid bone + Carbin instance transforms remain as-is.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from pathlib import PurePosixPath
import stat
import zipfile
import numpy as np

from .carbin_reader import parse_carbin
from .modelbin_geometry_decoder import parse_bundle
from .source_skeleton_pose import read_bones, world_bone_matrices
from .source_stock_scene import _source_entry, _highest_detail_lod


class SourceSceneAnchorError(ValueError):
    pass


def original_anchor_identity(instance, scene_bones) -> int | None:
    """Verify exact source ID/name without applying Scene World Bone geometry."""
    bone_id = getattr(instance, "bone_id", None)
    bone_name = getattr(instance, "bone", None)
    snap = getattr(instance, "snap_to_parent", None)
    if type(snap) is not bool or snap:
        raise SourceSceneAnchorError("source SnapToParent requires separate proven parent contract")
    raw = np.asarray(getattr(instance, "matrix", None), dtype=np.float64)
    if (raw.shape != (16,) or not np.isfinite(raw).all()):
        raise SourceSceneAnchorError("invalid original Carbin instance matrix")
    matrix = raw.reshape((4, 4))
    if (not np.allclose(matrix[:3, 3], 0., atol=1e-6, rtol=0.)
            or not np.isclose(matrix[3, 3], 1., atol=1e-6, rtol=0.)
            or abs(float(np.linalg.det(matrix[:3, :3]))) < 1e-12):
        raise SourceSceneAnchorError("non-affine or singular original instance matrix")
    if type(bone_id) is not int or not isinstance(bone_name, str):
        raise SourceSceneAnchorError("invalid original Carbin Scene Bone reference")
    if bone_id == -1 and bone_name == "":
        return None
    if bone_id < 0 or bone_id >= len(scene_bones) or not bone_name:
        raise SourceSceneAnchorError("unresolved original Scene Bone ID")
    names = [bone.name.casefold() for bone in scene_bones]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise SourceSceneAnchorError("ambiguous original Scene Skeleton Bone names")
    if names[bone_id] != bone_name.casefold():
        raise SourceSceneAnchorError("Carbin Scene Bone ID/name mismatch")
    return bone_id


def audit_original_scene_anchors(archive: Path | str) -> dict:
    """Full-source identity evidence, without changing GLB bytes or wheel pose."""
    with zipfile.ZipFile(archive) as z:
        paths = {}
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            p = PurePosixPath(name)
            if (not name or name.startswith("/") or "\\" in name or ":" in name
                    or "." in p.parts or ".." in p.parts or info.flag_bits & 1
                    or stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                    or info.file_size > 512 * 1024 * 1024
                    or name.casefold() in paths):
                raise SourceSceneAnchorError("unsafe/duplicate original car archive path")
            paths[name.casefold()] = info.filename
        carbins = [n for n in paths if n.endswith(".carbin") and "/" not in n]
        if len(carbins) != 1:
            raise SourceSceneAnchorError("original Carbin root is not unique")
        carbin = z.read(paths[carbins[0]])
        scene = parse_carbin(carbin)
        skeleton_entry = _source_entry(scene["skeleton"], scene["media"])
        if skeleton_entry not in paths:
            raise SourceSceneAnchorError("original Scene Skeleton source is missing")
        skeleton_raw = z.read(paths[skeleton_entry])
        skels = [b for b in parse_bundle(skeleton_raw) if b.tag == "Skel"]
        if len(skels) != 1:
            raise SourceSceneAnchorError("original Scene Skeleton is not unique")
        bones = read_bones(skeleton_raw, skels[0])
        # Validate hierarchy; do not multiply these matrices into the rendered car.
        world_bone_matrices(bones)
        lod = _highest_detail_lod(scene["lod"])
        selected = 0
        nonroot = 0
        unresolved_root = 0
        for instance in scene["models"]:
            if not instance.stock or (instance.lod_flags and not instance.lod_flags & lod):
                continue
            selected += 1
            idx = original_anchor_identity(instance, bones)
            if idx is None:
                unresolved_root += 1
            elif idx > 1:
                nonroot += 1
        if selected == 0:
            raise SourceSceneAnchorError("original Carbin selected no Stock instances")
        return {
            "schema": "lo4fh6.firstparty-scene-anchor-identity.v1",
            "carbin_sha256": sha256(carbin).hexdigest(),
            "source_scene_skeleton_modelbin_sha256": sha256(skeleton_raw).hexdigest(),
            "source_scene_bone_count": len(bones),
            "declared_instances": len(scene["models"]),
            "selected_stock_instances": selected,
            "selected_nonroot_anchors": nonroot,
            "selected_missing_anchor": unresolved_root,
            "bone_id_and_name_verified": True,
            "carbin_authored_matrices_preserved": True,
            "extra_scene_world_bone_transform_applied": False,
            "game_runtime_pose_accepted": False,
            "product_accepted": False,
        }
