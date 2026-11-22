from __future__ import annotations
from .png_settings import PNG_COMPRESS_LEVEL

import hashlib
import json
import struct
import math
import mimetypes
import re
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .package import FullLiveryPackageError, read_package_member, validate_livery_inspection_artifact
from .render_contract import MASK_PAGE_COUNT, RENDER_CONTRACT_FORMAT



def git_checkout_identity(static_root: Path) -> dict | None:
    """Viewer のソースの版（写しの札、または作業ツリーの .git）。PRIVATE 受入済みの配布物を偽装しない。

    固定の Viewer の入口に一致したときだけ返す。git は起動しない（tools.livery.source_version。以前は版の表示の
    ためだけに git を 4 回起動し、Viewer の窓から黒い窓が出ていた。2026-11-20）。
    ユーザー・ゲームの場所、remote の URL、Git の設定は WebView2 へ出さない。
    """
    from .source_version import safe_branch, source_revision
    repo = Path(__file__).resolve().parents[4]
    if static_root.resolve() != (repo / "src/viewer/tools/livery-inspector").resolve():
        return None
    revision = source_revision(repo / "src" / "viewer")
    if revision is None:
        return None
    commit = revision["commit"]
    if revision["source_type"] == "git-archive":
        branch = ""
        date = revision["committed"][:10]
        label = f"版: ソース {commit[:12]}" + (f"（{date}）" if date else "")
    else:
        # branch 名は利用者が付けられるので、画面には安全な限られた文字だけを出す。
        branch = safe_branch(revision["branch"])
        label = f"版: Git開発ソース {commit[:12]}｜branch {branch}｜PRIVATE配布版ではありません（製品承認は別）"
    return {
        "schema": "lo4fh6.viewer.runtime-source-identity.v1",
        "display_label": label,
        "source_commit": commit,
        "source_branch": branch,
        "source_type": revision["source_type"],
        # 作業ツリーの変更の有無は git に比べさせないと分からないので出さない。
        "worktree_modified": None,
        "private_release_approved": False,
        "release_approval_claimed": False,
    }


class LiveryInspectorServer:
    """埋込みLivery Inspector専用のトークン保護付きlocalhostサーバー。"""

    def __init__(self, static_root: Path | str):
        self.static_root = Path(static_root).resolve()
        self._package: Path | None = None
        self._local_mesh: Path | None = None
        self._local_body_kit_mesh: Path | None = None
        self._local_body_kit: dict = {}
        self._local_body_kit_variants: list[dict] = []
        self._local_body_kit_variant_meshes: dict[int, Path] = {}
        # 準備で変換を後回しにした部品（番号 → 保存先と原本のモデル）と、変換する関数（2026-11-21）
        self._local_body_kit_deferred: dict[int, tuple[Path, list[str]]] = {}
        self._local_body_kit_convert = None
        self._local_render: dict = {}
        self._manifest: dict = {}
        # 保存する画像（現在視点・6方向）の下の帯に書く、ペイントの情報（Organizer から届いた物。2026-11-21）
        self._capture_caption: dict = {}
        self._viewer_preferences: dict = {}
        self._gpu_livery_runtime: dict = {}
        self._stock_body_only: dict = {}
        self._private_wheel_research: dict = {}
        self._private_wheel_png: Path | None = None
        # 部品の選択肢（バンパー等）。選択肢の重ね合わせのGLBは、初めて求められたときに作る。
        self._part_options: dict = {}
        self._part_option_lock = threading.Lock()
        # 飾りの画像のうち BC7 のまま渡すもの（名前 → ゲームの原本の参照）と、読む原本の場所（2026-11-20、案 ①）。
        self._body_trim_source: tuple[Path, Path] | None = None
        self._body_trim_bc7_refs: dict[str, str] = {}
        self._body_trim_bc7_locations: dict[str, dict] = {}
        self._body_trim_bc7_cache: dict[str, bytes] = {}
        # 元の 2 枚のまま渡すラベル（<入力の SHA-256>.label → 大きさ・上書きの色・各画像の参照と位置。2026-11-21）
        self._body_trim_labels: dict[str, dict] = {}
        self._body_trim_bc7_lock = threading.Lock()
        self._token = secrets.token_urlsafe(18)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.request_diagnostic = None  # local-only callback, no URLs or asset contents

    @property
    def url(self) -> str:
        if self._server is None:
            return ""
        return f"http://127.0.0.1:{self._server.server_port}/{self._token}/"

    @property
    def package_path(self) -> Path | None:
        return self._package

    def set_capture_caption(self, caption: dict | None) -> None:
        """保存する画像（現在視点・6方向）の下の帯に書く、ペイントの情報を受け取る（2026-11-21）。

        タイトル・作成者・アップロード日・車名の文字だけを持つ（無い項目は空、長すぎる物は切る）。
        画面の表示や描画には使わず、ページは /api/manifest の capture_caption で受け取る。
        """
        source = caption if isinstance(caption, dict) else {}
        self._capture_caption = {
            key: source[key].strip()[:200] if isinstance(source.get(key), str) else ""
            for key in ("title", "creator_name", "upload_date", "vehicle_name")
        }

    def set_viewer_preferences(self, preferences: dict | None) -> None:
        """Viewer の画面の好み（自動回転の速さの倍率）を受け取る（2026-11-22）。

        ページは /api/manifest の viewer_preferences で受け取る。倍率は 1〜3 の数だけを渡し、ほかは渡さない。
        """
        source = preferences if isinstance(preferences, dict) else {}
        speed = source.get("auto_rotate_speed")
        valid = isinstance(speed, (int, float)) and not isinstance(speed, bool) and 1.0 <= float(speed) <= 3.0
        self._viewer_preferences = {"auto_rotate_speed": float(speed)} if valid else {}

    def set_package(self, package: Path | str) -> dict:
        path = Path(package).resolve()
        manifest = validate_livery_inspection_artifact(path)
        self._package = path
        self._manifest = manifest
        self._local_mesh = None
        self._local_body_kit_mesh = None
        self._local_body_kit = {}
        self._local_body_kit_variants = []
        self._local_body_kit_variant_meshes = {}
        self._local_body_kit_deferred = {}
        self._local_body_kit_convert = None
        self._local_render = {}
        self._gpu_livery_runtime = {}
        self._stock_body_only = {}
        self._private_wheel_research = {}
        self._private_wheel_png = None
        return manifest

    def set_verified_stock_body(self, mesh: Path | str, *, car_id: int, model_code: str,
                                expected_sha256: str) -> None:
        """ペイント無し原本GLBの隔離セッション。既存Liveryパスは変更しない。"""
        if type(car_id) is not int or car_id <= 0:
            raise FullLiveryPackageError("Stock車体のCar IDが不正です")
        if not isinstance(model_code, str) or not re.fullmatch(r"[A-Za-z0-9_]{3,110}", model_code):
            raise FullLiveryPackageError("Stock車体モデル名が不正です")
        if not isinstance(expected_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None:
            raise FullLiveryPackageError("Stock GLBのSHA256が不正です")
        if self._package is not None or self._gpu_livery_runtime:
            raise FullLiveryPackageError("PaintセッションへStock車体を後付けできません")
        supplied_path = Path(mesh)
        if supplied_path.is_symlink() or (hasattr(supplied_path, "is_junction") and supplied_path.is_junction()):
            raise FullLiveryPackageError("原本Stock GLBのリンク/ジャンクションは使用できません")
        path = supplied_path.resolve()
        if not path.is_file() or path.suffix.casefold() != ".glb":
            raise FullLiveryPackageError("原本Stock GLBがありません")
        from .portable_mesh_converter import validate_local_chassis_glb
        validate_local_chassis_glb(
            path, require_product_accepted=True,
            required_firstparty_scope="ORIGINAL_STOCK_STATIC__VIEWER_FUNCTIONAL_CANDIDATE",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise FullLiveryPackageError("Stock GLBのSHAが準備記録と異なります")
        self.set_local_mesh(path)
        self._stock_body_only = {
            "enabled": True,
            "format": "lo4fh6_source_stock_body_webgl2_session_v1",
            "car_id": car_id, "model_code": model_code,
            "glb_sha256": digest,
            "livery_present": False,
            "xbox_approved": False,
        }
        self._manifest = {
            "vehicle": {"model_code": model_code},
            "livery": {"target_car_id": car_id, "logical_placement_count": 0,
                       "title": "原本Stock車体（Liveryなし）"},
        }

    def set_local_mesh(self, mesh: Path | str | None) -> None:
        if mesh is None:
            self._local_mesh = None
            return
        path = Path(mesh).resolve()
        if not path.is_file() or path.suffix.casefold() != ".glb":
            raise FullLiveryPackageError("The local inspection mesh is not a readable GLB file.")
        # 元r485正常経路と完成NORMALは保全。研究中のhidden-only GLBだけ
        # GPU-onlyアトラス準備の前に拒否し、WIPを完成資産と誤認しない。
        from .source_mesh_stage_guard import refuse_hidden_only_source
        try:
            refuse_hidden_only_source(path)
        except ValueError as exc:
            raise FullLiveryPackageError(str(exc)) from exc
        self._local_mesh = path

    def set_private_source_wheel_research(
        self, rgba_png: Path | str, source_proof: Path | str, material_proof: Path | str,
    ) -> None:
        """既存のrM025描画入口へ、署名がそろう元WheelだけをPRIVATEで供給する。

        通常モードは呼ばない。原本タイヤやゲーム素材を再生成しない。
        署名不一致では現行セッションに不完全な入力を残さない。
        """
        self._private_wheel_research = {}
        self._private_wheel_png = None
        if self._local_mesh is None:
            raise FullLiveryPackageError("Wheel研究用の実GLBが登録されていません")
        path = Path(rgba_png).resolve()
        a = Path(source_proof).resolve()
        b = Path(material_proof).resolve()
        for target in (path, a, b):
            if not target.is_file() or target.is_symlink():
                raise FullLiveryPackageError("Wheel研究用の署名ファイルが見つかりません")
        if path.suffix.casefold() != ".png":
            raise FullLiveryPackageError("Wheel研究用RGBAはPNGが必要です")
        source = json.loads(a.read_text(encoding="utf-8"))
        material = json.loads(b.read_text(encoding="utf-8"))
        if (
            source.get("schema") != "lo4fh6.first_party.source_bound_wheel_symbol.v1"
            or source.get("standard_enabled") is not False
            or material.get("schema") != "lo4fh6.source_bound_wheel_material_crosswalk.v1"
            or material.get("standard_enabled") is not False
            or material.get("visible_material_slot_verified") is not True
            or material.get("shader_family") != "car_standard"
            or not material.get("shader_sha256")
            or not source.get("modelbin_sha256")
            or material.get("modelbin_sha256") != source.get("modelbin_sha256")
            or str(material.get("source_entry") or "").casefold() != str(source.get("source_entry") or "").casefold()
            or not isinstance(material.get("wheel_material_id"), int)
            or material.get("wheel_material_id") < 0
            or not material.get("wheel_material_name")
        ):
            raise FullLiveryPackageError("Wheel原本・ModelBin/Shaderの一意証明が不足しています")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source.get("rgba_sha256"):
            raise FullLiveryPackageError("Wheel原本RGBAのSHA-256が一致しません")
        if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
            raise FullLiveryPackageError("Wheel原本RGBA PNGヘッダーが不正です")
        width, height = struct.unpack_from(">II", raw, 16)
        if (
            width != source.get("rgba_width")
            or height != source.get("rgba_height")
            or raw[25] != 6
        ):
            raise FullLiveryPackageError("Wheel原本RGBAのサイズ・色形式が署名と違います")
        from .source_bound_material import glb_source_primitives
        matched = glb_source_primitives(
            self._local_mesh.read_bytes(),
            str(source["source_entry"]),
            int(material["wheel_material_id"]),
        )
        expected = material.get("glb_source_primitives")
        if (
            not isinstance(expected, list)
            or len(matched) != len(expected)
            or sorted(map(lambda p: json.dumps(p, sort_keys=True), matched))
               != sorted(map(lambda p: json.dumps(p, sort_keys=True), expected))
            or len({p.get("wheel") for p in matched if p.get("wheel")}) < 2
        ):
            raise FullLiveryPackageError("Wheel元GLBの材質ID・primitive/UV・左右出典が一致しません")
        self._private_wheel_research = {
            "wheel_symbol_source": {**source, "verified": True, "standard_enabled": False},
            "wheel_material_crosswalk": material,
        }
        self._private_wheel_png = path

    def set_private_source_facing_research(
        self, proof_file: Path | str, original_contract_file: Path | str,
    ) -> None:
        """元GLB/Mask/左右法線証拠の完全一致時だけPRIVATE契約を切り替える。"""
        if self._local_mesh is None or not self._local_render.get("metadata"):
            raise FullLiveryPackageError("PRIVATE Facing研究には原本GLBと11面契約が必要です")
        from .source_facing_runtime import validated_facing_metadata
        verified = validated_facing_metadata(
            self._local_render["metadata"], original_contract_file, proof_file,
            self._local_mesh, self._local_render.get("masks") or [],
        )
        self._local_render["metadata"] = verified

    def set_local_body_kit_overlay(self, mesh: Path | str | None, descriptor: dict | None = None) -> None:
        self._local_body_kit_mesh = None
        self._local_body_kit = dict(descriptor or {})
        if mesh is None:
            return
        path = Path(mesh).resolve()
        if not path.is_file() or path.suffix.casefold() != ".glb":
            raise FullLiveryPackageError("The local body-kit overlay mesh is not a readable GLB file.")
        self._local_body_kit_mesh = path

    def set_local_part_options(self, *, asset, archive_sha256: str, vehicle_cache_root: Path | str,
                               content_root: Path | str, catalog: list[dict], selected: dict | None = None) -> None:
        """部品の選択肢の一覧と、重ね合わせのGLBを作るための情報を登録する（作るのは初めて求められたとき）。"""
        self._part_options = {
            "asset": asset,
            "archive_sha256": str(archive_sha256),
            "vehicle_cache_root": Path(vehicle_cache_root).resolve(),
            "content_root": Path(content_root),
            "catalog": list(catalog or []),
            "selected": {str(k): int(v) for k, v in (selected or {}).items()},
        }

    def _part_option_request(self, request: BaseHTTPRequestHandler, relative: str, prefix: str):
        """「<prefix><種類>/<番号>」を解いて、重ね合わせのGLBを用意する（無ければ作る）。"""
        from .part_option_overlay import PartOptionOverlayError, prepared_part_option_overlay
        options = self._part_options
        parts = relative[len(prefix):].split("/")
        if not options or len(parts) != 2 or not parts[1].isdigit():
            self._error(request, HTTPStatus.NOT_FOUND, "Unknown part option.")
            return None
        family, option_id = parts[0], int(parts[1])
        try:
            with self._part_option_lock:
                mesh = prepared_part_option_overlay(
                    options["asset"], options["vehicle_cache_root"], archive_sha256=options["archive_sha256"],
                    family=family, option_id=option_id, catalog=options["catalog"])
        except PartOptionOverlayError as exc:
            self._error(request, HTTPStatus.NOT_FOUND, str(exc))
            return None
        except Exception as exc:  # noqa: BLE001  変換の失敗はViewerへ理由を返す（他の表示は止めない）。
            self._error(request, HTTPStatus.INTERNAL_SERVER_ERROR, f"Part option conversion failed: {exc}")
            return None
        return family, option_id, mesh

    def set_local_body_kit_variants(self, variants: list[dict] | None,
                                    convert: Callable[[Path, list[str]], None] | None = None) -> None:
        """Viewerの再読込切替に使用するManifest由来のBodyKit候補を登録する。

        準備で変換を後回しにした部品（overlay_deferred）は、convert（保存先, 部品の原本のモデル）を渡されたときだけ
        受け取り口を出し、Viewer で初めて求められたときに変換する（2026-11-21）。convert が無ければ今までどおり出さない。
        """

        self._local_body_kit_variants = []
        self._local_body_kit_variant_meshes = {}
        self._local_body_kit_deferred = {}
        self._local_body_kit_convert = convert
        for raw in variants or []:
            if not isinstance(raw, dict):
                continue
            try:
                part_id = int(raw.get("body_kit_part_id"))
            except (TypeError, ValueError):
                continue
            descriptor = {
                key: value
                for key, value in raw.items()
                if key not in {"overlay_mesh", "overlay_validation", "overlay_cache_hit", "overlay_mesh_planned"}
            }
            mesh_value = str(raw.get("overlay_mesh") or "").strip()
            mesh = Path(mesh_value).resolve() if mesh_value else None
            if mesh is not None:
                if not mesh.is_file() or mesh.suffix.casefold() != ".glb":
                    raise FullLiveryPackageError("A local body-kit catalog mesh is not a readable GLB file.")
                self._local_body_kit_variant_meshes[part_id] = mesh
            planned_value = str(raw.get("overlay_mesh_planned") or "").strip()
            added = [str(entry) for entry in (raw.get("added_entries") or [])]
            if (mesh is None and raw.get("overlay_deferred") is True and planned_value and added
                    and convert is not None and Path(planned_value).suffix.casefold() == ".glb"):
                self._local_body_kit_deferred[part_id] = (Path(planned_value).resolve(), added)
            available = part_id in self._local_body_kit_variant_meshes or part_id in self._local_body_kit_deferred
            descriptor["mesh_available"] = available
            descriptor["endpoint"] = f"api/local-body-kit-mesh/{part_id}" if available else None
            self._local_body_kit_variants.append(descriptor)

    def _local_body_kit_variant_mesh(self, part_id: int) -> Path | None:
        """部品の重ね合わせの GLB。後回しにした部品は、ここで初めて変換する（同時に 1 つずつ）。"""
        mesh = self._local_body_kit_variant_meshes.get(part_id)
        if mesh is not None:
            return mesh
        deferred = self._local_body_kit_deferred.get(part_id)
        convert = self._local_body_kit_convert
        if deferred is None or convert is None:
            return None
        with self._part_option_lock:
            mesh = self._local_body_kit_variant_meshes.get(part_id)
            if mesh is None:
                planned, added = deferred
                convert(planned, added)
                if not planned.is_file():
                    raise FullLiveryPackageError("The deferred body-kit mesh was not created.")
                self._local_body_kit_variant_meshes[part_id] = planned
                self._local_body_kit_deferred.pop(part_id, None)
                mesh = planned
        return mesh

    def set_body_trim_source(self, content_root: Path | str | None, vehicle_archive: Path | str | None) -> None:
        """飾りの画像を BC7 のまま渡すときに読む、ゲームのフォルダーと車の ZIP。"""
        if content_root and vehicle_archive:
            source = (Path(content_root).resolve(), Path(vehicle_archive).resolve())
        else:
            source = None
        with self._body_trim_bc7_lock:
            if source != self._body_trim_source:
                self._body_trim_bc7_cache.clear()
            self._body_trim_source = source

    def _remember_body_trim_bc7(self, groups: object) -> None:
        """色の解析の記録から、原本から直接渡す飾りの画像（.bc7）とラベル（.label）の参照・位置を覚える。"""
        if not isinstance(groups, dict):
            return
        with self._body_trim_bc7_lock:
            for record in groups.values():
                texture = record.get("texture") if isinstance(record, dict) else None
                name = str((texture or {}).get("file") or "") if isinstance(texture, dict) else ""
                ref = record.get("base_color_texture") if isinstance(record, dict) else None
                if re.fullmatch(r"[0-9a-f]{64}\.bc7", name) and isinstance(ref, str) and ref:
                    self._body_trim_bc7_refs[name] = ref
                    location = texture.get("source_location")
                    if isinstance(location, dict):
                        self._body_trim_bc7_locations[name] = dict(location)
                label = texture.get("label") if isinstance(texture, dict) else None
                if re.fullmatch(r"[0-9a-f]{64}\.label", name) and isinstance(label, dict):
                    parts = label.get("parts")
                    if (isinstance(parts, dict) and parts and set(parts) <= {"base", "alpha"}
                            and all(isinstance(entry, dict) and isinstance(entry.get("ref"), str)
                                    and re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256") or ""))
                                    for entry in parts.values())):
                        self._body_trim_labels[name] = json.loads(json.dumps(label))

    def _read_body_trim_located(self, location: dict, source: tuple[Path, Path]) -> bytes | None:
        """記録した位置から原本を直接読む（ZIP の目次を読まない）。場所はゲームのフォルダーか車の ZIP の中だけ。"""
        import zlib
        content_root, vehicle_archive = source
        try:
            if "file" in location:
                path = Path(str(location["file"])).resolve()
            else:
                path = Path(str(location["archive"])).resolve()
            if path != vehicle_archive and not path.is_relative_to(content_root):
                return None
            if "file" in location:
                return path.read_bytes()
            offset, method = int(location["offset"]), int(location["method"])
            compressed, size = int(location["compressed"]), int(location["size"])
            if offset < 0 or compressed < 0 or size < 0 or size > 64 * 1024 * 1024 or compressed > 64 * 1024 * 1024:
                return None
            with path.open("rb") as handle:
                handle.seek(offset)
                header = handle.read(30)
                if len(header) != 30 or header[:4] != b"PK\x03\x04":
                    return None
                name_length, extra_length = struct.unpack_from("<HH", header, 26)
                handle.seek(offset + 30 + name_length + extra_length)
                data = handle.read(compressed)
            if len(data) != compressed:
                return None
            if method == 0:
                raw = data
            elif method == 8:
                raw = zlib.decompress(data, -15)
            else:
                return None
            return raw if len(raw) == size else None
        except (OSError, ValueError, TypeError, KeyError, zlib.error):
            return None

    def _body_trim_bc7(self, name: str, *, png: bool) -> tuple[bytes, str] | None:
        """BC7 のまま渡す飾りの画像。形：LO4BC7 の印・版・幅・高さ（各 4 バイト）と全段の画素。png なら PNG に戻す。

        原本を読んで SHA-256 が名前と同じときだけ渡す。同じプロセスでは覚える（最近の 256 個）。
        """
        from .body_trim_default_color import TEXTURE_MAX_SIZE, bc7_passthrough_surface
        with self._body_trim_bc7_lock:
            ref = self._body_trim_bc7_refs.get(name)
            location = self._body_trim_bc7_locations.get(name)
        if ref is None:
            return None
        data = self._load_body_trim_original(name[:64], ref, location)
        if data is None:
            return None
        surface = bc7_passthrough_surface(data)
        if surface is None:
            return None
        width, height, pixels = surface
        if png:
            import io
            from .fh6_swatch import decode_swatch_image
            image, _meta = decode_swatch_image(data)
            if image is None:
                return None
            image = image.convert("RGB")
            if max(image.size) > TEXTURE_MAX_SIZE:
                # 以前の PNG の書き出しと同じく縮める（2026-11-21 から大きな BC7 もそのまま渡す）
                from PIL import Image
                scale = TEXTURE_MAX_SIZE / max(image.size)
                image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                                     Image.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
            return output.getvalue(), "image/png"
        return b"LO4BC7\0\1" + struct.pack("<II", width, height) + pixels, "application/octet-stream"

    def _load_body_trim_original(self, sha256: str, ref: str, location: object) -> bytes | None:
        """飾りの画像の原本（SHA-256 が sha256 のときだけ）。同じプロセスでは覚える（最近の 256 個）。"""
        from .body_trim_default_color import _TextureReader
        with self._body_trim_bc7_lock:
            source = self._body_trim_source
            data = self._body_trim_bc7_cache.get(sha256)
        if source is None:
            return None
        if data is not None:
            return data
        if isinstance(location, dict):
            # 記録した位置から直接読む（要求のたびに 771 MB の Textures.zip の目次を読まない。2026-11-20）
            located = self._read_body_trim_located(location, source)
            if located is not None and hashlib.sha256(located).hexdigest() == sha256:
                data = located
        if data is None:
            # 位置が無い・合わない（ゲームの更新など）ときは、参照から読む（ZIP を開く）
            import zipfile
            content_root, vehicle_archive = source
            with zipfile.ZipFile(vehicle_archive) as archive:
                reader = _TextureReader(content_root, archive, vehicle_archive.stem)
                try:
                    data = reader.read(ref)
                finally:
                    if reader.archive is not None:
                        reader.archive.close()
                    for other in reader.other_archives.values():
                        if other is not None:
                            other[0].close()
            if data is None or hashlib.sha256(data).hexdigest() != sha256:
                return None
        with self._body_trim_bc7_lock:
            self._body_trim_bc7_cache[sha256] = data
            while len(self._body_trim_bc7_cache) > 256:
                self._body_trim_bc7_cache.pop(next(iter(self._body_trim_bc7_cache)))
        return data

    def _body_trim_label(self, name: str, *, part: str | None, png: bool) -> tuple[bytes, str] | None:
        """元の 2 枚のまま渡すラベルの画像 1 枚（part は base か alpha。2026-11-21）。

        形：LO4TEX の印と版（8 バイト）・形（1＝BC7、2＝BC4、3＝RGBA8）・幅・高さ（各 4 バイト）と画素（BC7・BC4 は
        1×1 までの全段、RGBA8 は一番上の段）。png なら 2 枚を合わせた PNG（色の解析が以前書いていた PNG と同じ作り方。
        BC7・BC4 を受け取れない GPU のため）。原本を読んで SHA-256 が記録と同じときだけ渡す。
        """
        from .body_trim_default_color import compose_label_image, passthrough_part_surface
        with self._body_trim_bc7_lock:
            label = self._body_trim_labels.get(name)
        if label is None:
            return None
        parts = label.get("parts") or {}

        def original(entry: dict) -> bytes | None:
            return self._load_body_trim_original(str(entry["sha256"]), str(entry["ref"]), entry.get("location"))

        if png:
            datas: dict[str, bytes | None] = {}
            for key in ("base", "alpha"):
                entry = parts.get(key)
                datas[key] = original(entry) if entry is not None else None
                if entry is not None and datas[key] is None:
                    return None
            override = label.get("override_srgb8")
            image = compose_label_image(datas["base"], datas["alpha"],
                                        override if isinstance(override, list) and len(override) == 3 else None)
            if image is None:
                return None
            import io
            output = io.BytesIO()
            image.save(output, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
            return output.getvalue(), "image/png"
        entry = parts.get(str(part or ""))
        if entry is None:
            return None
        data = original(entry)
        surface = passthrough_part_surface(data) if data is not None else None
        if surface is None:
            return None
        code = {"bc7": 1, "bc4": 2, "rgba8": 3}[surface["format"]]
        return (b"LO4TEX\0\1" + struct.pack("<III", code, surface["width"], surface["height"]) + surface["pixels"],
                "application/octet-stream")

    def set_local_render_contract(self, root: Path | str, contract: dict) -> None:
        base = Path(root).resolve()
        if str(contract.get("format") or "") != RENDER_CONTRACT_FORMAT:
            raise FullLiveryPackageError("The local FH6 livery render contract is unsupported.")
        files = contract.get("files") or {}

        def local_png(root: Path, name: object, *, kind: str) -> Path:
            path = (root / str(name or "")).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise FullLiveryPackageError(f"The local livery {kind} path is unsafe.") from exc
            if not path.is_file() or path.suffix.casefold() != ".png":
                raise FullLiveryPackageError(f"A local FH6 livery {kind} texture is missing.")
            return path

        # 旧契約経由でもCPUペイントAtlasを登録・配信させない。
        if (contract.get("cpu_shadow_policy") != "gpu-only"
                or contract.get("paint_rasterizer") != "webgl2-only"
                or files.get("paint")):
            raise FullLiveryPackageError("WebGL2-only paint is required; CPU paint is removed.")
        mask_cache = contract.get("mask_cache") if isinstance(contract.get("mask_cache"), dict) else {}
        mask_root_value = str(mask_cache.get("root") or "").strip()
        mask_base = Path(mask_root_value).resolve() if mask_root_value else base

        masks = [local_png(mask_base, name, kind="mask") for name in (files.get("masks") or [])]
        if len(masks) != MASK_PAGE_COUNT:
            raise FullLiveryPackageError("The local FH6 livery mask set is incomplete.")
        sections = contract.get("sections") or []
        slots: set[int] = set()
        for section in sections:
            if not isinstance(section, dict):
                raise FullLiveryPackageError("The local FH6 livery section metadata is invalid.")
            slot = int(section.get("slot_index", -1))
            if slot < 0 or slot >= 11 or slot in slots:
                raise FullLiveryPackageError("The local FH6 livery section slots are invalid.")
            slots.add(slot)
            for key in ("source_region", "paint_region"):
                values = section.get(key)
                if not isinstance(values, list) or len(values) != 4:
                    raise FullLiveryPackageError("The local FH6 livery texture regions are invalid.")
                try:
                    normalized = [float(value) for value in values]
                except (TypeError, ValueError) as exc:
                    raise FullLiveryPackageError("The local FH6 livery texture regions are invalid.") from exc
                if (
                    any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in normalized)
                    or normalized[0] >= normalized[2]
                    or normalized[1] >= normalized[3]
                ):
                    raise FullLiveryPackageError("The local FH6 livery texture regions are outside the atlas.")
        metadata = {
            key: contract[key]
            for key in (
                "format",
                "uv_contract",
                "assembly",
                "assembly_variants",
                "assembly_truth",
                "paint_size",
                "mask_size",
                # 以下はviewer.jsとbuildProductionGpuPaintAtlasの必須入力。
                # 以前はサーバー側の許可リストから漏れていたため、
                # rM036のGPU専用契約が実際のthree.js Viewerで失敗していた。
                "cpu_shadow_policy",
                "paint_rasterizer",
                "render_contract_revision",
                "files",
                "filters",
                "sections",
                "quality_scale",
                "quality_source",
                "section_composite_supersample",
                "paint_bindings",
                "paint_layer_diagnostics",
                "base_paint_selection",
                "base_paint_color_rgba_hex",
                "base_paint_material",
                # PR68: 元ManufacturerColorsのMirror署名済み研究候補をブラウザーへ中継。
                # このフィールドの欠落でPython準備PASS後のGPU Viewerが安全停止していた。
                # 通常契約には存在しないため、製品既定の材質を変えない。
                "original_accessory_research",
                "wheel_paint_colors",
                "wheel_paint_routing",
                # 車体の非塗装部品の原本MatIの色（body_trim_default_color）。HTTP側で欠落すると
                # Viewerは従来の中立の灰色のままになる。
                "body_trim_colors",
                # ペイントの Mirror・Brakes の記録の色（ミラーのカバー・キャリパー）。HTTP側で欠落すると
                # Viewerはメーカー指定色の0番のミラー・原本MatIの既定色のキャリパーのままになる。
                "named_paint_groups",
                # 純正の模様の板（原本の材質 livery_sticker）を見せるか（層の無いデザインで記録がメーカー指定のとき）。
                # HTTP側で欠落すると、Viewerは今までどおり板を隠す（2026-11-22、Car 1477）。
                "factory_livery_stickers",
                # 原本Normalを生成した標準入口の期待値はViewerへ必ず転送する。
                # HTTP側で欠落すると旧GLB全後退の検出が無効になってしまう。
                "lo4fh6_source_tire_standard_required",
                # 元Carbin→C_livery Hashの結び付きを標準Viewerへ受け渡す。
                # 準備PASSでもHTTP側で消すと金色等のメッシュ別色が全て消える。
                "source_paint_binding_diagnostics",
                "source_paint_binding_diagnostics_unavailable",
                # 覆いの画像の中身の SHA。同じ車の差し替えで、前のペイントと同じ覆いを読み直さずに使い回すため
                # （viewer.js の paintSwapMaskTexture。2026-11-20）。
                "file_sha256",
            )
            if key in contract
        }
        detail_normal = base / "base-detail-normal.png"
        detail_mask = base / "base-detail-mask.png"
        # 車体の非塗装部品の原本ベースカラーTexture（body_trim_default_color が書き出したPNG）。
        # 車種ごとのキャッシュでは、車種をまたいで共有のフォルダー（契約の body_trim_texture_cache.root）。
        # 項目の無い以前の準備結果は、ペイントのフォルダーの body-trim-textures。
        trim_cache = (contract.get("body_trim_texture_cache")
                      if isinstance(contract.get("body_trim_texture_cache"), dict) else {})
        trim_root_value = str(trim_cache.get("root") or "").strip()
        body_trim_texture_dir = Path(trim_root_value).resolve() if trim_root_value else base / "body-trim-textures"
        self._remember_body_trim_bc7((contract.get("body_trim_colors") or {}).get("groups")
                                     if isinstance(contract.get("body_trim_colors"), dict) else None)
        self._local_render = {
            "masks": masks,
            "body_trim_texture_dir": body_trim_texture_dir,
            "detail_normal": detail_normal if detail_normal.is_file() else None,
            "detail_mask": detail_mask if detail_mask.is_file() else None,
            "metadata": metadata,
        }


    def set_gpu_livery_runtime(self, manifest: dict, vector_stream: bytes, geometry_pack: bytes, raster_decal_pack: bytes | None = None) -> None:
        if str(manifest.get("format") or "") != "lo4fh6_gpu_livery_production_runtime_v1":
            raise FullLiveryPackageError("The GPU livery runtime manifest is unsupported.")
        if not isinstance(vector_stream, (bytes, bytearray)) or not vector_stream:
            raise FullLiveryPackageError("The GPU livery runtime vector stream is empty.")
        if not isinstance(geometry_pack, (bytes, bytearray)) or not geometry_pack:
            raise FullLiveryPackageError("The GPU livery runtime geometry pack is empty.")
        # 原本Decals.zipから生成したセッションGPU入力を製品の通常入口へ接続。
        # 旧 source_context_mask_research は意味論調査フラグであり、署名済み
        # Raster原本パックの受入条件ではない（生成側は常にFalse）。
        decal_meta = manifest.get("raster_decals") or {}
        raw_count = decal_meta.get("count", 0)
        if type(raw_count) is not int or raw_count < 0:
            raise FullLiveryPackageError("Raster Logo原本のGPU件数が不正です")
        raster_count = raw_count
        if raster_count:
            if (decal_meta.get("source_verified") is not True
                    or decal_meta.get("research_only") is not False
                    or not isinstance(decal_meta.get("source_archive_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", decal_meta["source_archive_sha256"]) is None):
                raise FullLiveryPackageError("Raster Logo原本の署名済みGPU契約が不足しています")
            if (not isinstance(raster_decal_pack, bytes)
                    or len(raster_decal_pack) < 16
                    or decal_meta.get("pack_bytes") != len(raster_decal_pack)):
                raise FullLiveryPackageError("Raster Logo原本のGPU入力バイトが未接続または不一致です")
            magic, version, packed_count = struct.unpack_from("<8sII", raster_decal_pack)
            if magic != b"LO4GRD01" or version != 1 or packed_count != raster_count:
                raise FullLiveryPackageError("Raster Logo原本のGPUパック署名・件数が不正です")
            offset = 16
            seen_ids: set[int] = set()
            for _ in range(raster_count):
                if offset + 16 > len(raster_decal_pack):
                    raise FullLiveryPackageError("Raster Logo原本のGPUパックが途中で切れています")
                raster_id, width, height, size = struct.unpack_from("<IIII", raster_decal_pack, offset)
                offset += 16
                if (raster_id == 0 or raster_id in seen_ids or width == 0 or height == 0
                        or size != width * height * 4
                        or offset + size > len(raster_decal_pack)):
                    raise FullLiveryPackageError("Raster Logo原本のGPU画像ID・寸法・容量が不正です")
                seen_ids.add(raster_id)
                offset += size
            if offset != len(raster_decal_pack):
                raise FullLiveryPackageError("Raster Logo原本のGPUパックに不要な末尾があります")
        elif raster_decal_pack is not None:
            raise FullLiveryPackageError("不要なRaster Logoバイトを通常Viewerに登録できません")
        self._gpu_livery_runtime = {
            "raster_decal_pack": bytes(raster_decal_pack) if raster_decal_pack is not None else None,
            "manifest": dict(manifest),
            "vector_stream": bytes(vector_stream),
            "geometry_pack": bytes(geometry_pack),
        }


    def start(self) -> str:
        if self._server is not None:
            return self.url
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib request-handler API
                owner._handle(self)

            def do_POST(self):  # noqa: N802 - stdlib request-handler API
                owner._handle_post(self)

            def log_message(self, _format, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        server = self._server
        self._thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05),
            name="lo4fh6-livery-inspector",
            daemon=True,
        )
        self._thread.start()
        return self.url

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        path = unquote(urlsplit(request.path).path)
        prefix = f"/{self._token}/"
        if not path.startswith(prefix):
            self._error(request, HTTPStatus.NOT_FOUND, "Unknown inspector session.")
            return
        relative = path[len(prefix) :]
        if relative == "api/runtime-source-identity":
            # Git開発時のみに返す補助表示。PRIVATE配布証明とは別スキーマ。
            source_identity = git_checkout_identity(self.static_root)
            if source_identity is None:
                self._error(request, HTTPStatus.NOT_FOUND, "Git source identity unavailable.")
                return
            self._send(request, json.dumps(source_identity, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if relative == "api/manifest":
            if self.request_diagnostic:
                self.request_diagnostic("manifest_request_received")
            runtime_manifest = dict(self._manifest)
            runtime_manifest["capture_caption"] = dict(self._capture_caption)
            runtime_manifest["viewer_preferences"] = dict(self._viewer_preferences)
            runtime_manifest["inspection_runtime"] = {
                "local_mesh": self._local_mesh is not None,
                "stock_body_only": dict(self._stock_body_only),
                "direct_uv3": self._local_mesh is not None and bool(self._local_render),
                "world_projection_fallback": False,
                "render_contract": self._local_render.get("metadata") or {},
                "body_kit_overlay": {
                    **self._local_body_kit,
                    "active": bool(self._local_body_kit),
                    "mesh_available": self._local_body_kit_mesh is not None,
                    "endpoint": "api/local-body-kit-mesh" if self._local_body_kit_mesh is not None else None,
                },
                "body_kit_variants": self._local_body_kit_variants,
                "part_options": {
                    "available": bool(self._part_options.get("catalog")),
                    "catalog": self._part_options.get("catalog") or [],
                    "selected": self._part_options.get("selected") or {},
                },
                **self._private_wheel_research,
                "gpu_livery_runtime": {
                    "available": bool(self._gpu_livery_runtime),
                    "format": (self._gpu_livery_runtime.get("manifest") or {}).get("format"),
                    "adapter": (self._gpu_livery_runtime.get("manifest") or {}).get("adapter") or {},
                },
            }
            try:
                data = json.dumps(runtime_manifest).encode("utf-8")
            except (TypeError, ValueError, OverflowError) as exc:
                if self.request_diagnostic:
                    self.request_diagnostic("manifest_json_error_" + type(exc).__name__)
                self._error(request, HTTPStatus.INTERNAL_SERVER_ERROR, "The viewer manifest is invalid.")
                return
            self._send(request, data, "application/json")
            if self.request_diagnostic:
                self.request_diagnostic(f"manifest_response_sent bytes={len(data)}")
            return
        if relative == "api/original-wheel-symbol/rgba":
            if self._private_wheel_png is None:
                self._error(request, HTTPStatus.NOT_FOUND, "Wheel原本研究入力は未登録です")
                return
            self._send(request, self._private_wheel_png.read_bytes(), "image/png")
            return
        if relative == "api/local-mesh":
            if self._local_mesh is None:
                self._error(request, HTTPStatus.NOT_FOUND, "No matching local inspection mesh is ready.")
                return
            self._send(request, self._local_mesh.read_bytes(), "model/gltf-binary")
            return
        if relative == "api/local-body-kit-mesh":
            if self._local_body_kit_mesh is None:
                self._error(request, HTTPStatus.NOT_FOUND, "No matching local body-kit overlay is ready.")
                return
            self._send(request, self._local_body_kit_mesh.read_bytes(), "model/gltf-binary")
            return
        if relative.startswith("api/local-part-option-mesh/"):
            prepared = self._part_option_request(request, relative, "api/local-part-option-mesh/")
            if prepared is not None:
                self._send(request, prepared[2].read_bytes(), "model/gltf-binary")
            return
        if relative.startswith("api/local-part-option-meta/"):
            # 重ね合わせの部品の材質の色（部品の色付け）。Textureは車体と同じ共有のフォルダーに置く。
            prepared = self._part_option_request(request, relative, "api/local-part-option-meta/")
            if prepared is None:
                return
            from .body_trim_default_color import cached_body_trim_colors
            from .part_option_overlay import glb_document
            family, option_id, mesh = prepared
            options = self._part_options
            texture_dir = self._local_render.get("body_trim_texture_dir") or (
                options["vehicle_cache_root"] / "body-trim-textures")
            try:
                trim, _hit = cached_body_trim_colors(
                    mesh, content_root=options["content_root"], vehicle_archive=options["asset"].archive_path,
                    cache_root=options["vehicle_cache_root"] / "vehicle-analysis", texture_dir=texture_dir)
            except Exception as exc:  # noqa: BLE001  色が求められなくても部品は描ける（中立色）。
                trim = {"groups": {}, "error": f"{type(exc).__name__}: {exc}"}
            overlay = (glb_document(mesh)["scenes"][0].get("extras") or {}).get("lo4fh6_part_option_overlay")
            payload = {"family": family, "option_id": option_id, "overlay": overlay,
                       "body_trim_groups": trim.get("groups") or {}}
            self._remember_body_trim_bc7(trim.get("groups"))
            self._send(request, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if relative.startswith("api/local-body-kit-mesh/"):
            try:
                part_id = int(relative.rsplit("/", 1)[-1])
            except ValueError:
                self._error(request, HTTPStatus.NOT_FOUND, "Unknown local body-kit variant.")
                return
            try:
                mesh = self._local_body_kit_variant_mesh(part_id)
            except Exception as exc:  # noqa: BLE001  変換の失敗はViewerへ理由を返す（他の表示は止めない）。
                self._error(request, HTTPStatus.INTERNAL_SERVER_ERROR, f"Body-kit variant conversion failed: {exc}")
                return
            if mesh is None:
                self._error(request, HTTPStatus.NOT_FOUND, "No matching local body-kit variant mesh is ready.")
                return
            self._send(request, mesh.read_bytes(), "model/gltf-binary")
            return
        if relative == "api/local-render/base-detail-normal":
            detail = self._local_render.get("detail_normal")
            if detail is None:
                self._error(request, HTTPStatus.NOT_FOUND, "The local base-paint detail normal is unavailable.")
                return
            self._send(request, detail.read_bytes(), "image/png")
            return
        if relative == "api/local-render/base-detail-mask":
            detail = self._local_render.get("detail_mask")
            if detail is None:
                self._error(request, HTTPStatus.NOT_FOUND, "The local base-paint detail mask is unavailable.")
                return
            self._send(request, detail.read_bytes(), "image/png")
            return
        if relative.startswith("api/local-render/body-trim-texture/"):
            name = relative.rsplit("/", 1)[-1]
            if re.fullmatch(r"[0-9a-f]{64}\.bc7", name):
                # ゲームの BC7 のまま渡す（?png=1 なら PNG。BC7 を受け取れない GPU のため）
                query = urlsplit(request.path).query
                try:
                    served = self._body_trim_bc7(name, png="png=1" in query.split("&"))
                except (OSError, ValueError, KeyError):
                    served = None
                if served is None:
                    self._error(request, HTTPStatus.NOT_FOUND, "The body trim texture is unavailable.")
                    return
                self._send(request, served[0], served[1])
                return
            if re.fullmatch(r"[0-9a-f]{64}\.label", name):
                # 元の 2 枚のまま渡すラベル（?part=base か ?part=alpha。?png=1 なら 2 枚を合わせた PNG）
                query = urlsplit(request.path).query.split("&")
                part = next((item.split("=", 1)[1] for item in query if item.startswith("part=")), None)
                try:
                    served = self._body_trim_label(name, part=part, png="png=1" in query)
                except (OSError, ValueError, KeyError, TypeError):
                    served = None
                if served is None:
                    self._error(request, HTTPStatus.NOT_FOUND, "The body trim label is unavailable.")
                    return
                self._send(request, served[0], served[1])
                return
            folder = self._local_render.get("body_trim_texture_dir")
            if folder is None or re.fullmatch(r"[0-9a-f]{64}\.png", name) is None:
                self._error(request, HTTPStatus.NOT_FOUND, "Unknown body trim texture.")
                return
            target = Path(folder) / name
            if target.is_symlink() or not target.is_file():
                self._error(request, HTTPStatus.NOT_FOUND, "The body trim texture is unavailable.")
                return
            self._send(request, target.read_bytes(), "image/png")
            return
        if relative.startswith("api/local-render/mask/"):
            parts = relative.split("/")
            if len(parts) != 4 or not parts[-1].isdigit():
                self._error(request, HTTPStatus.NOT_FOUND, "Unknown local livery mask texture.")
                return
            index = int(parts[-1])
            masks = self._local_render.get("masks") or []
            if index < 0 or index >= len(masks):
                self._error(request, HTTPStatus.NOT_FOUND, "The requested local livery mask is unavailable.")
                return
            self._send(request, masks[index].read_bytes(), "image/png")
            return
        if relative == "api/gpu-livery-runtime/manifest":
            manifest = self._gpu_livery_runtime.get("manifest")
            if not isinstance(manifest, dict):
                self._error(request, HTTPStatus.NOT_FOUND, "GPU livery runtime inputs are unavailable.")
                return
            self._send(request, json.dumps(manifest).encode("utf-8"), "application/json")
            return
        if relative == "api/gpu-livery-runtime/vector-stream":
            payload = self._gpu_livery_runtime.get("vector_stream")
            if not isinstance(payload, bytes):
                self._error(request, HTTPStatus.NOT_FOUND, "GPU livery runtime vector stream is unavailable.")
                return
            self._send(request, payload, "application/octet-stream")
            return
        if relative == "api/gpu-livery-runtime/geometry-pack":
            payload = self._gpu_livery_runtime.get("geometry_pack")
            if not isinstance(payload, bytes):
                self._error(request, HTTPStatus.NOT_FOUND, "GPU livery runtime geometry pack is unavailable.")
                return
            self._send(request, payload, "application/octet-stream")
            return
        if relative == "api/gpu-livery-runtime/raster-decal-pack":
            payload = self._gpu_livery_runtime.get("raster_decal_pack")
            if not isinstance(payload, bytes):
                self._error(request, HTTPStatus.NOT_FOUND, "Raster Logo研究入力は未登録です")
                return
            self._send(request, payload, "application/octet-stream")
            return
        if relative.startswith("api/member/"):
            if self._package is None:
                self._error(request, HTTPStatus.CONFLICT, "No livery package is open.")
                return
            member = relative[len("api/member/") :]
            try:
                data = read_package_member(self._package, member, allow_private_preview=True)
            except FullLiveryPackageError as exc:
                self._error(request, HTTPStatus.NOT_FOUND, str(exc))
                return
            mime = mimetypes.guess_type(member)[0] or "application/octet-stream"
            self._send(request, data, mime)
            return

        static_name = relative or "index.html"
        if static_name.startswith("vendor/three/"):
            # Three.js（第三者ライブラリ）はsrc/viewerに置かず、初回起動時に照合して利用者のローカル領域へ
            # 置いた実体（local_three_dependency）から返す。照合値に載った7ファイル以外は返さない。
            from .local_three_dependency import ThreeDependencyError, served_file
            try:
                target = served_file(static_name[len("vendor/three/"):])
            except ThreeDependencyError as exc:
                self._error(request, HTTPStatus.NOT_FOUND, str(exc))
                return
            mime = "text/javascript" if target.suffix.casefold() in {".js", ".mjs"} else "text/plain; charset=utf-8"
            self._send(request, target.read_bytes(), mime)
            return
        if self.request_diagnostic and static_name in {"index.html", "viewer.js", "gpu-livery-production.js", "gpu-livery-capability-probe.mjs"}:
            self.request_diagnostic("static_request_" + static_name)
        target = (self.static_root / static_name).resolve()
        try:
            target.relative_to(self.static_root)
        except ValueError:
            self._error(request, HTTPStatus.BAD_REQUEST, "Unsafe static path.")
            return
        if not target.is_file():
            self._error(request, HTTPStatus.NOT_FOUND, "Inspector file not found.")
            return
        # WindowsのMIMEレジストリ差で.mjsをapplication/octet-streamとして返すと
        # WebView2がtype="module"を拒否するため、ブラウザー実行資産は固定型で送る。
        static_mime = {
            ".js": "text/javascript",
            ".mjs": "text/javascript",
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".json": "application/json",
        }
        mime = static_mime.get(target.suffix.casefold())
        if mime is None:
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(request, target.read_bytes(), mime)

    def _handle_post(self, request: BaseHTTPRequestHandler) -> None:
        # 旧CPUペイント比較APIを廃止。製品側にPOST受信口は存在しない。
        self._error(request, HTTPStatus.NOT_FOUND, "No POST endpoint is available.")

    @staticmethod
    def _send(request: BaseHTTPRequestHandler, data: bytes, content_type: str) -> None:
        request.send_response(HTTPStatus.OK)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("X-Content-Type-Options", "nosniff")
        request.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self' blob:; worker-src 'self' blob:")
        request.end_headers()
        try:
            request.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    @staticmethod
    def _error(request: BaseHTTPRequestHandler, status: HTTPStatus, message: str) -> None:
        data = message.encode("utf-8", errors="replace")
        request.send_response(status)
        request.send_header("Content-Type", "text/plain; charset=utf-8")
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.end_headers()
        try:
            request.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
