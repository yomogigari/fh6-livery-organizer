from __future__ import annotations

import os
import re
from pathlib import Path




SECTION_NAMES = (
    "front", "back", "top", "left", "right", "wing",
    "front_windscreen", "rear_windscreen", "top_window", "left_window", "right_window",
)


LIVERY_DIR_RE = re.compile(r"^Livery_\d{1,6}_\d{14}$", re.IGNORECASE)


def _readable_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def _livery_dir_name(path: Path) -> str | None:
    candidates = [path.name, path.parent.name]
    candidates.extend(parent.name for parent in path.parents)
    for name in candidates:
        if LIVERY_DIR_RE.fullmatch(name or ""):
            return name
    return None


def _pgs_root_from_source(path: Path) -> Path | None:
    chain = [path, *path.parents]
    for candidate in chain:
        if candidate.name.casefold() == "pgs":
            return candidate
    return None


def _rediscover_c_livery(pgs_root: Path, livery_dir_name: str) -> Path | None:
    """Find a moved GameSave C_livery by stable Livery_* directory name.

    Xbox GameSave container-number directories can rotate.  Search only under
    the inferred pgs root and accept an exact Livery_* directory-name match.
    """
    matches: list[Path] = []
    try:
        for dirpath, dirnames, _filenames in os.walk(pgs_root, topdown=True, onerror=lambda _exc: None):
            hit_names = [name for name in dirnames if name.casefold() == livery_dir_name.casefold()]
            for name in hit_names:
                candidate = Path(dirpath) / name / "C_livery"
                if _readable_file(candidate):
                    matches.append(candidate)
            # No need to recurse into a matched Livery_* directory.
            if hit_names:
                dirnames[:] = [name for name in dirnames if name.casefold() != livery_dir_name.casefold()]
    except OSError:
        return None
    if not matches:
        return None
    # 更新時刻を取得できる場合は新しく読み取れる保存データを優先する。
    # 特殊なファイルシステムでも選択を再現できるよう、パス文字列を第二キーとする。
    def key(candidate: Path) -> tuple[float, str]:
        try:
            stamp = float(candidate.stat().st_mtime)
        except OSError:
            stamp = -1.0
        return stamp, str(candidate).casefold()
    return max(matches, key=key)


def resolve_readable_c_livery(path: Path) -> Path:
    """GameSaveの番号付きコンテナーが切り替わってもC_liveryを特定する。

    最初に指定パスを直接読み込む。旧パスだった場合は、パス表記から
    安定したLivery_*ディレクトリ名とpgsルートを求め、
    現在読み取り可能なC_liveryをpgs配下から再探索する。
    """
    source = path.expanduser()
    candidates: list[Path] = []
    if source.name.casefold() == "c_livery":
        candidates.append(source)
    else:
        candidates.extend((source / "C_livery", source))
    errors: list[str] = []
    for candidate in candidates:
        try:
            with candidate.open("rb") as handle:
                handle.read(1)
            return candidate
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    livery_name = _livery_dir_name(source)
    pgs_root = _pgs_root_from_source(source)
    if livery_name and pgs_root:
        rediscovered = _rediscover_c_livery(pgs_root, livery_name)
        if rediscovered is not None:
            return rediscovered

    detail = " / ".join(errors)
    suffix = ""
    if livery_name and pgs_root:
        suffix = f" / 再探索: {pgs_root} 配下の {livery_name}"
    raise FileNotFoundError(
        f"C_livery を読み取り用に開けません: {path}" + (f" ({detail}{suffix})" if detail or suffix else "")
    )


def resolve_content_root(path: Path) -> Path:
    root = path.expanduser().resolve()
    if (root / "media" / "livery" / "Vinyls.zip").is_file():
        return root
    content = root / "Content"
    if (content / "media" / "livery" / "Vinyls.zip").is_file():
        return content
    raise FileNotFoundError(
        "FH6 Content を確認できません。指定先またはその Content 配下に "
        "media\\livery\\Vinyls.zip が必要です: " + str(root)
    )




