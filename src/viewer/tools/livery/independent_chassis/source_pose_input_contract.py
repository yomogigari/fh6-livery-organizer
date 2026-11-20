"""Source-authored Bind candidate and deformation buffer signatures for research GLB.

ModelBin skeleton matrices can represent competing candidates; this validates
a caller's *explicit* choice against source bytes, but does not infer which
candidate FH6 uses during gameplay. Never populate a missing runtime pose or
Morph weight with identity/zero.
"""
from __future__ import annotations

from hashlib import sha256
import numpy as np

from .source_skeleton_pose import world_bone_matrices


class SourcePoseInputError(ValueError):
    pass


_BIND_CANDIDATES = {"modelbin-stored", "modelbin-parent-composed"}


def validate_original_deformation_input(raw_modelbin: bytes, mesh_offset: int,
                                        bones: list, skin, morph, runtime: dict) -> dict:
    """Require source-identity matched runtime inputs before any vertex mutation."""
    if (not isinstance(runtime, dict) or type(mesh_offset) is not int
            or mesh_offset < 0 or (skin is None and morph is None)):
        raise SourcePoseInputError("invalid source deformation mesh identity")
    if (runtime.get("original_modelbin_sha256") != sha256(raw_modelbin).hexdigest()
            or type(runtime.get("original_mesh_offset")) is not int
            or runtime["original_mesh_offset"] != mesh_offset):
        raise SourcePoseInputError("original ModelBin SHA/mesh offset differs from deformation evidence")
    if skin is None:
        if (runtime.get("original_skin_sha256") is not None
                or runtime.get("source_bind_world") is not None
                or runtime.get("source_pose_world") is not None
                or runtime.get("original_bind_candidate") is not None):
            raise SourcePoseInputError("Skin absent: forbidden Bind/Pose inputs")
    elif (runtime.get("original_skin_sha256") != skin.buffer_sha256
          or skin.skeleton_bone_count != len(bones)):
        raise SourcePoseInputError("Skin buffer source SHA/bone count mismatch")
    if morph is None:
        if (runtime.get("original_morph_sha256") is not None
                or runtime.get("original_morph_slot_weights") is not None
                or runtime.get("original_morph_slot_semantics") is not None
                or runtime.get("original_morph_higher_slot_modulation") is not None):
            raise SourcePoseInputError("Morph absent: forbidden coefficient inputs")
    elif runtime.get("original_morph_sha256") != morph.buffer_sha256:
        raise SourcePoseInputError("Morph buffer source SHA mismatch")
    choice = None
    if skin is not None:
        choice = runtime.get("original_bind_candidate")
        if not isinstance(choice, str) or choice not in _BIND_CANDIDATES:
            raise SourcePoseInputError("original Bind candidate must be explicitly selected")
        authored = ([bone.local for bone in bones] if choice == "modelbin-stored"
                    else world_bone_matrices(bones))
        expected = np.asarray(authored, dtype=np.float64)
        submitted = np.asarray(runtime.get("source_bind_world"), dtype=np.float64)
        if (expected.shape != (len(bones), 4, 4)
                or submitted.shape != expected.shape
                or not np.isfinite(expected).all() or not np.isfinite(submitted).all()
                or not np.allclose(submitted, expected, rtol=0, atol=1e-5)):
            raise SourcePoseInputError("source Bind Pose does not match selected original Skeleton candidate")
        current = np.asarray(runtime.get("source_pose_world"), dtype=np.float64)
        if current.shape != expected.shape or not np.isfinite(current).all():
            raise SourcePoseInputError("source current Pose must be explicitly supplied")
        # Current pose's in-game semantics cannot be attested from ModelBin alone.
    return {
        "original_modelbin_sha256": sha256(raw_modelbin).hexdigest(),
        "original_skin_buffer_sha256": skin.buffer_sha256 if skin else None,
        "original_morph_buffer_sha256": morph.buffer_sha256 if morph else None,
        "source_bind_candidate": choice,
        "source_bind_candidate_matches_bytes": skin is not None,
        "original_runtime_pose_game_verified": False,
        "original_morph_coefficients_game_verified": False,
        "product_accepted": False,
    }
