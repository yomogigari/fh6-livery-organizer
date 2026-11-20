"""Viewer のソースの版（コミット）を、プロセスを起動せずに読む（2026-11-20）。

以前は版の表示のためだけに git を何回も起動していた（Viewer の窓からは黒い窓が出ていた）。git は起動しない。
1. 写し（リリース）：git archive が取り出すときに、版の札（tools/livery-inspector/lo4fh6-source-version.json）の
   $Format:…$ をコミットの番号と日付に置き換える（.gitattributes の export-subst）。.git が無くても読める。
2. 開発の作業ツリー：札は置き換わっていないので、作業ツリーの .git の中のファイル（HEAD・ブランチの参照・
   packed-refs、worktree なら gitdir と commondir）を直接読む。作業ツリーの変更の有無は分からない（git が要る）。
画面へは、コミットの番号・日付・ブランチの名前（安全な文字だけ）のほかは出さない（場所・remote・設定は出さない）。
"""
from __future__ import annotations

import json
from pathlib import Path
import re

STAMP_RELATIVE = Path("tools") / "livery-inspector" / "lo4fh6-source-version.json"
STAMP_SCHEMA = "lo4fh6.viewer.source-version-stamp.v1"
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
_SAFE_BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")


def read_archive_stamp(viewer_root: Path | str) -> dict | None:
    """写し（git archive）で置き換わった版の札。置き換わっていない（開発の作業ツリー）・無い・壊れていれば None。"""
    try:
        data = json.loads((Path(viewer_root) / STAMP_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != STAMP_SCHEMA:
        return None
    commit = str(data.get("commit") or "")
    if not _SHA_RE.fullmatch(commit):
        return None
    committed = str(data.get("committed") or "")
    return {"commit": commit.lower(), "committed": committed if _DATE_RE.fullmatch(committed) else ""}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _git_dirs(repo_root: Path) -> tuple[Path, Path] | None:
    """作業ツリーの .git から、その作業ツリーの git の場所と、共通の場所（参照・packed-refs）を返す。"""
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        git_dir = dot_git
    elif dot_git.is_file():
        text = _read_text(dot_git) or ""
        if not text.startswith("gitdir:"):
            return None
        git_dir = Path(text.split(":", 1)[1].strip())
        if not git_dir.is_absolute():
            git_dir = repo_root / git_dir
    else:
        return None
    common = git_dir
    commondir = _read_text(git_dir / "commondir")
    if commondir:
        common = Path(commondir) if Path(commondir).is_absolute() else git_dir / commondir
    return git_dir, common


def _resolve_ref(git_dir: Path, common: Path, ref: str) -> str | None:
    if not ref.startswith("refs/") or ".." in ref:
        return None
    for base in (git_dir, common):
        value = _read_text(base / ref)
        if value:
            return value
    packed = _read_text(common / "packed-refs")
    for line in (packed or "").splitlines():
        if line.startswith(("#", "^")):
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].strip() == ref:
            return parts[0]
    return None


def read_git_head(repo_root: Path | str) -> tuple[str, str] | None:
    """作業ツリーの一番上の .git から、先頭のコミット（40 桁）とブランチの名前（切り離しなら空）を読む。"""
    dirs = _git_dirs(Path(repo_root))
    if dirs is None:
        return None
    git_dir, common = dirs
    head = _read_text(git_dir / "HEAD")
    if not head:
        return None
    branch = ""
    if head.startswith("ref:"):
        ref = head[4:].strip()
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/"):]
        head = _resolve_ref(git_dir, common, ref) or ""
    if not _SHA_RE.fullmatch(head):
        return None
    return head.lower(), branch


def safe_branch(branch: str) -> str:
    """画面に出すブランチの名前（安全な文字だけ。そうでなければ detached-HEAD）。"""
    return branch if _SAFE_BRANCH_RE.fullmatch(branch or "") else "detached-HEAD"


def source_revision(viewer_root: Path | str) -> dict | None:
    """Viewer のソースの版。写しの札、なければ作業ツリーの .git。どちらも無ければ None。"""
    viewer_root = Path(viewer_root)
    stamp = read_archive_stamp(viewer_root)
    if stamp is not None:
        return {"source_type": "git-archive", "commit": stamp["commit"], "committed": stamp["committed"], "branch": ""}
    head = read_git_head(viewer_root.parent.parent)
    if head is not None:
        return {"source_type": "git-checkout", "commit": head[0], "committed": "", "branch": head[1]}
    return None
