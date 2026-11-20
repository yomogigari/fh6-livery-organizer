r"""Viewerが使う Three.js（MIT ライセンスの第三者ライブラリ）を、初回起動時に用意する。

Three.js はリポジトリにも配布物（src/viewer 一式）にも置かない。初回起動時に npm の公式配布
（版と照合値は three_runtime_manifest）を取得し、7ファイルの SHA256 が一致した場合だけ、
利用者のローカル領域 %LOCALAPPDATA%\Livery Organizer for FH6\PreviewBridge\dependencies\three-<版>
へ原子的に置く。Viewer のローカルサーバーは /vendor/three/ への要求をこの領域から返す。
既に置かれた実体が照合値と一致しない場合は書き換えず、理由を明示して停止する。

src/viewer の中にある Three.js（以前の版が置いた tools/livery-inspector/vendor/three）は
読みも使いもしない（src/viewer に他プロダクトのファイルを置かず使わない方針）。
取得元は次の順で、どれも SHA 照合する：
1. 本人が保全した PRIVATE の署名済み ZIP（Git checkout の隣の work、または Downloads。オフライン用）
2. npm の公式配布
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import stat
import zipfile
from urllib.request import Request, urlopen

from .three_runtime_manifest import PACKAGE_URL, THREE_SHA, THREE_VERSION

MAX_TARBALL_BYTES = 12 * 1024 * 1024
# 旧PRIVATE Stage（Git checkout の隣の work 内）での相対位置。Stage からの取得にだけ使う。
RELATIVE_VENDOR = Path("src/viewer/tools/livery-inspector/vendor/three")
# 照合済みの場所を覚え、サーバーの要求ごとに7ファイルを読み直さない。
_VERIFIED_ROOTS: set[Path] = set()


def runtime_root() -> Path:
    """Three.js を置く利用者のローカル領域。Viewer の他のローカルデータと同じ親フォルダー。"""
    value = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(value) if value else Path.home() / "AppData" / "Local"
    return base / "Livery Organizer for FH6" / "PreviewBridge" / "dependencies" / f"three-{THREE_VERSION}"


class ThreeDependencyError(RuntimeError):
    """Three r185の元SHA/ライセンス/実行依存が保証されない。"""


def _expected(repo: Path | None = None) -> dict[str, str]:
    """照合値（src/viewer 内の three_runtime_manifest）。repo は互換のための引数で使わない。"""
    expected = dict(THREE_SHA)
    if len(expected) != 7:
        raise ThreeDependencyError("正本Three r185はLICENSEを含め7ファイル必要です")
    return expected


def verify(root: Path, expected: dict[str, str]) -> None:
    if not root.is_dir() or root.is_symlink():
        raise ThreeDependencyError(f"Three r185未配置: {root}")
    for name, hash_value in expected.items():
        candidate = root.joinpath(*PurePosixPath(name).parts)
        if not candidate.is_file() or candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
            raise ThreeDependencyError(f"Three r185ファイル欠損: {name}")
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != hash_value:
            raise ThreeDependencyError(f"Three r185 SHA不一致: {name}")
    if b"The MIT License" not in (root / "LICENSE").read_bytes()[:120]:
        raise ThreeDependencyError("Three r185元MITライセンスがありません")


def _download_expected(expected: dict[str, str]) -> dict[str, bytes]:
    # NPM packageは署名実体を取得する運搬手段だけ。採用判定は元正本SHA7件。
    request = Request(PACKAGE_URL, headers={"User-Agent": "LO4FH6-firstparty-three-r185-source-verification"})
    try:
        with urlopen(request, timeout=25) as response:
            compressed = response.read(MAX_TARBALL_BYTES + 1)
    except OSError as exc:
        raise ThreeDependencyError(f"Three r185の公式配布取得に失敗: {exc}") from exc
    if len(compressed) > MAX_TARBALL_BYTES:
        raise ThreeDependencyError("Three r185配布ZIP容量上限を超過")
    found: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(compressed), mode="r:gz") as tar:
            for member in tar:
                if not member.isfile() or member.issym() or member.islnk():
                    continue
                key = member.name.removeprefix("package/")
                if key not in expected:
                    continue
                if key in found or member.size > 8 * 1024 * 1024:
                    raise ThreeDependencyError("Three r185依存の重複または異常サイズ")
                stream = tar.extractfile(member)
                if stream is None:
                    raise ThreeDependencyError(f"Three r185の抽出に失敗: {key}")
                payload = stream.read(member.size + 1)
                if len(payload) != member.size:
                    raise ThreeDependencyError(f"Three r185不完全取得: {key}")
                if hashlib.sha256(payload).hexdigest() != expected[key]:
                    raise ThreeDependencyError(f"公式配布と正本Three r185 SHA不一致: {key}")
                found[key] = payload
    except (tarfile.TarError, EOFError) as exc:
        raise ThreeDependencyError(f"Three r185公式配布の形式が不正: {exc}") from exc
    if set(found) != set(expected):
        raise ThreeDependencyError(f"Three r185の元7ファイル不足: {sorted(set(expected)-set(found))}")
    if b"The MIT License" not in found["LICENSE"][:120]:
        raise ThreeDependencyError("Three r185のMITライセンスが欠落")
    return found


SIGNED_ARCHIVE_NAME = "PR68-Viewer-Repair-20261112-1740-JST.zip"
SIGNED_PREFIX = "signed-three-r185/"
MAX_SIGNED_MEMBER_BYTES = 8 * 1024 * 1024


def _verified_archive(archive: Path, expected: dict[str, str]) -> dict[str, bytes]:
    """既存Windows成功版から保存した署名済み7ファイルだけをZIP内から取得する。

    ZIPの解凍・実行はせず、対象の正規名・実バイトSHA・CRCとMIT原文を検査する。
    """
    found: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(archive) as z:
            for name, digest in expected.items():
                member_name = SIGNED_PREFIX + name
                matches = [i for i in z.infolist() if i.filename == member_name]
                if len(matches) != 1:
                    raise ThreeDependencyError("署名済みThree ZIP内のファイルが欠落・重複: " + name)
                info = matches[0]
                kind = stat.S_IFMT(info.external_attr >> 16)
                if (info.is_dir() or info.flag_bits & 1 or kind == stat.S_IFLNK
                        or info.file_size > MAX_SIGNED_MEMBER_BYTES):
                    raise ThreeDependencyError("署名済みThree ZIP内のファイル属性が不正: " + name)
                payload = z.read(info)  # ZIP CRCも検査。アーカイブの他メンバーは展開しない。
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise ThreeDependencyError("署名済みThree ZIPと正本SHA不一致: " + name)
                found[name] = payload
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ThreeDependencyError("署名済みThree ZIPの読み込み/CRC検証に失敗: " + str(exc)) from exc
    if b"The MIT License" not in found.get("LICENSE", b"")[:120]:
        raise ThreeDependencyError("署名済みThree ZIPの元MITライセンスがありません")
    return found


def _signed_local_source(repo: Path, expected: dict[str, str]) -> dict[str, bytes] | None:
    """通常Git checkoutの隣にある本人保全済みPRIVATEの署名実体だけを自動発見。

    研究ランチャー、専用URL、環境変数を通常起動に要求しない。
    GitにThirdPartyを保存せず、手元の既存PRIVATE資産から再接続する。
    """
    work = repo.parent / "work"
    downloads = Path.home() / "Downloads"
    for folder in (work, downloads):
        # 旧成功版の正規ZIPを直接読む。ユーザーのWindows作業フォルダーの外は探索しない。
        archive = folder / SIGNED_ARCHIVE_NAME
        if archive.is_file():
            return _verified_archive(archive, expected)
        extracted = folder / Path(SIGNED_ARCHIVE_NAME).stem / SIGNED_PREFIX
        if extracted.is_dir():
            verify(extracted, expected)
            return {name: extracted.joinpath(*PurePosixPath(name).parts).read_bytes()
                    for name in expected}
    # 前チャットで生成した標準PRIVATE展開済みStageもSHA確認して再利用。
    stage = work / "LO4FH6-PR68-MergedMain-SignedPrivateRuntime-20261112-1740-JST"
    candidate = stage / RELATIVE_VENDOR
    if candidate.is_dir():
        verify(candidate, expected)
        return {name: candidate.joinpath(*PurePosixPath(name).parts).read_bytes()
                for name in expected}
    return None


def _offline_hint() -> str:
    """取得できないときの開発用の案内（本人保全の署名済み ZIP の置き場）。配布の EXE では出さない。

    配布の EXE の利用者は署名済み ZIP を持たないため、ネット接続の確認だけを案内する（2026-11-18 利用者の決定）。
    """
    try:
        from lo4fh6_desktop_suite.runtime import is_packaged
    except ImportError:
        is_packaged = None
    if is_packaged is not None and is_packaged():
        return ""
    return ("オフラインの場合は、本人保全の PRIVATE 署名済み ZIP を Git checkout の隣の work か Downloads に"
            " 置いてください: " + SIGNED_ARCHIVE_NAME + " / ")


def _default_repo() -> Path:
    # src/viewer/tools/livery/local_three_dependency.py → リポジトリ直下（PRIVATE ZIP の探索の起点）。
    return Path(__file__).resolve().parents[4]


def ensure(repo: Path | None = None, *, install_root: Path | None = None) -> Path:
    """Three.js を利用者のローカル領域に用意し、その場所を返す。

    既に置かれた実体は照合だけして書き換えない（不一致は明示停止）。無ければ、移行用の
    リポジトリ内の実体、PRIVATE 署名済み ZIP、npm 公式配布の順で取得し、照合後に原子的に置く。
    """
    expected = _expected()
    root = Path(install_root) if install_root is not None else runtime_root()
    if root in _VERIFIED_ROOTS and root.is_dir():
        return root
    if root.exists() or root.is_symlink():
        verify(root, expected)
        _VERIFIED_ROOTS.add(root)
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    data = _signed_local_source(Path(repo).resolve() if repo is not None else _default_repo(), expected)
    if data is None:
        try:
            data = _download_expected(expected)
        except ThreeDependencyError as exc:
            raise ThreeDependencyError(
                f"Three.js {THREE_VERSION} を初回起動時に取得できません（ネット接続を確認してください）。"
                + _offline_hint() + "元エラー: " + str(exc)
            ) from exc
    scratch = Path(tempfile.mkdtemp(prefix=".three-verify-", dir=root.parent))
    promoted = False
    try:
        for name, payload in data.items():
            dest = scratch.joinpath(*PurePosixPath(name).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
        verify(scratch, expected)
        if root.exists() or root.is_symlink():
            verify(root, expected)
            return root
        os.replace(scratch, root)
        promoted = True
        verify(root, expected)
        _VERIFIED_ROOTS.add(root)
        return root
    finally:
        if not promoted and scratch.exists():
            shutil.rmtree(scratch)


def served_file(name: str) -> Path:
    """/vendor/three/<name> で返す実体。照合値に載った7ファイルだけを返す。"""
    if name not in THREE_SHA:
        raise ThreeDependencyError(f"Three.js の配信対象外です: {name}")
    root = ensure()
    target = root.joinpath(*PurePosixPath(name).parts)
    if not target.is_file() or target.is_symlink():
        raise ThreeDependencyError(f"Three.js のファイルがありません: {name}")
    return target
