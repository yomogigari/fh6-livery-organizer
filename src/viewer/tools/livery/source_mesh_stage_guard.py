"""原本GLBの描画Stage取り違えをGPU処理の前に検出する第一者ゲート。

全メッシュが明示 hidden のGLBだけを拒否する。Paint/Trimの推測や車種固有補正はしない。
それ以外は従来ViewerのmeshCategory/Mask/Facingと出典検証に委ねる。
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path


def inspect_glb_stage(raw: bytes) -> dict[str, object]:
    """JSON chunkのみ読み、誤選択の証拠を匿名集計する。原本頂点バイトは書き換えない。"""
    if len(raw) < 20 or raw[:4] != b'glTF':
        return {'decision': 'DEFER_TO_VIEWER', 'reason': 'not_glb2'}
    version, total, json_bytes, chunk_type = struct.unpack_from('<IIII', raw, 4)
    if version != 2 or total != len(raw) or json_bytes < 4 or json_bytes > 32 * 1024 * 1024 or chunk_type != 0x4E4F534A or 20 + json_bytes > len(raw):
        return {'decision': 'DEFER_TO_VIEWER', 'reason': 'glb_header_unrecognized'}
    try:
        document = json.loads(raw[20:20 + json_bytes].rstrip(b'\x00 \t\n\r').decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return {'decision': 'DEFER_TO_VIEWER', 'reason': 'glb_json_unrecognized'}
    meshes = document.get('meshes') if isinstance(document, dict) else None
    if not isinstance(meshes, list) or not meshes:
        return {'decision': 'DEFER_TO_VIEWER', 'reason': 'mesh_count_unknown'}
    roles = {}
    for mesh in meshes:
        if not isinstance(mesh, dict):
            return {'decision': 'DEFER_TO_VIEWER', 'reason': 'mesh_metadata_unknown'}
        extras = mesh.get('extras') or {}
        role = (extras.get('lo4fh6_role', extras.get('lo4_role'))
                if isinstance(extras, dict) else None)
        token = str(role).casefold() if isinstance(role, str) else 'unspecified'
        roles[token] = roles.get(token, 0) + 1
    return {
        'decision': 'REJECT_HIDDEN_ONLY' if len(roles) == 1 and roles.get('hidden') == len(meshes) else 'DEFER_TO_VIEWER',
        'mesh_count': len(meshes),
        'role_counts': roles,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
    }


def refuse_hidden_only_source(path: str | Path) -> dict[str, object]:
    """正常版や役割未記載旧版は維持。明示hiddenだけのWIPを入力として拒否。

    同じプロセスで同じファイル（場所・大きさ・更新日時が同じ）の検査結果は覚えて使い回す（同じ車のペイントを
    続けて開くたびに、約 35 MB の GLB を読んで目次を解析し SHA を計算していた。約 0.05 秒。2026-11-20）。
    """
    from .process_file_memo import remembered
    target = Path(path)
    report = remembered("glb-stage", [target], None, lambda: inspect_glb_stage(target.read_bytes()), limit=4)
    if report.get('decision') == 'REJECT_HIDDEN_ONLY':
        raise ValueError(
            'GLB is a hidden-only research stage, not a paint-bearing viewer source; '
            f"meshes={report['mesh_count']}, sha256={report['source_sha256']}. "
            'Select the existing verified completed NORMAL/source GLB; do not force-enable paint or rewrite UV3.'
        )
    return report
