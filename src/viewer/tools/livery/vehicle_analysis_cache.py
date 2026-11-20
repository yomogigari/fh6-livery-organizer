"""車種ごとの解析結果のキャッシュ（ペイントの内容に依存しない結果だけを置く）。

- 一括では作らない。表示の準備のときに、その車種の結果が無ければ作って保存する（cached_analysis）。
- キーには、入力のファイル（車体のGLB・車両ZIP・`_library` のZIP）の大きさと更新日時、
  計算するモジュールのソースのSHA256、版を入れる。どれかが変われば別のキーになり、作り直す。
- 使ったときに、ファイルの最終アクセス日時を今にする（最後に使った日時）。更新日時は変えない
  （更新日時をキーに使うキャッシュがあるため）。Windowsは大きいドライブで最終アクセス日時を自動では
  更新しない設定が多いので、使った箇所で明示的に設定する。将来、キャッシュの容量に上限を設けたときは、
  plan_eviction が「大きくて長く使っていない」ものから消す候補を出す。既定では何も消さない。
- ゲームの原本・GameSave には書き込まない。保存先は準備用の車両キャッシュ（_fh6-vehicle-cache）だけ。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

FORMAT = "lo4fh6.vehicle-analysis-cache.v1"
LAST_USED_FIELD = "last_used"


def file_identity(path: Path | str) -> list | None:
    """ファイルの場所・大きさ・更新日時（読み込まずに比べられる値）。無ければ None。"""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return [str(path.resolve()), stat.st_size, stat.st_mtime_ns]


def library_zip_entries(library: Path | str) -> list[tuple[Path, str, os.stat_result, bool]]:
    """`library` 以下で名前が .zip の項目（Path.rglob("*.zip") と同じもの）を、場所・相対名・stat・ファイルかで返す。

    相対名は path.relative_to(library).as_posix() と同じ文字列を、歩きながら作る（relative_to は遅い）。

    os.scandir の項目の情報を使う（Windows ではフォルダーの一覧から大きさと更新日時が得られ、
    ファイルごとに開き直さない。部品の ZIP 759 個で rglob＋stat の約 0.17 秒がほぼ 0 になる）。
    名前の比べ方は rglob と同じく OS の大文字・小文字の扱いに従う。読めないフォルダーは rglob と同じく飛ばす。
    並べ方は呼び出し側で決める。
    """
    root = Path(library)
    return [(root / relative, relative, stat, is_file) for relative, stat, is_file in library_zip_rows(root)]


def library_zip_rows(library: Path | str) -> list[tuple[str, os.stat_result, bool]]:
    """library_zip_entries と同じ項目を、同じ順に、場所の Path を作らずに（相対名・stat・ファイルか）返す（2026-11-20）。

    呼び出し元の多く（_library の識別・ホイールの色の経路の鍵）は場所を使わない。以前は 759 個の項目ごとに Path を
    作っていた（一覧 1 回の時間の約半分）。中のフォルダーは文字列の場所（os.DirEntry.path）でたどる。
    """
    found: list[tuple[str, os.stat_result, bool]] = []
    pending: list[tuple[str, str]] = [(os.fspath(library), "")]
    while pending:
        folder, prefix = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    relative = prefix + entry.name
                    if os.path.normcase(entry.name).endswith(".zip"):
                        found.append((relative, entry.stat(), entry.is_file()))
                    if entry.is_dir():
                        pending.append((entry.path, relative + "/"))
        except PermissionError:
            continue
    return found


def installed_library_identity(content_root: Path | str) -> list:
    """`media/cars/_library` 以下のZIP（材質・Shader・Texture）の大きさと更新日時の一覧。"""
    library = Path(content_root) / "media" / "cars" / "_library"
    rows: list = []
    if library.is_dir():
        for relative, stat, _is_file in sorted(library_zip_rows(library), key=lambda item: item[0].casefold()):
            rows.append([relative, stat.st_size, stat.st_mtime_ns])
    return rows


def _is_packaged() -> bool:
    """EXE で動いているか（Nuitka は各モジュールに __compiled__ を置き、PyInstaller などは sys.frozen を置く）。"""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


_PACKAGED_IDENTITY: bytes | None = None


def _packaged_program_identity() -> bytes:
    """EXE 自身の名前・大きさ・更新日時（EXE を作り直せば変わる）。プロセスごとに 1 回だけ求める。"""
    global _PACKAGED_IDENTITY
    if _PACKAGED_IDENTITY is None:
        # 配布した EXE（lo4fh6_desktop_suite.runtime.packaged_executable。起動したときの sys.argv[0] を控えた物で、
        # 同じプロセスで準備するために sys.argv が置き換わっていても取り違えない。2026-11-20）。
        try:
            from lo4fh6_desktop_suite.runtime import packaged_executable
        except ImportError:
            program = Path(sys.argv[0]).resolve()
        else:
            program = Path(packaged_executable()).resolve()
        stat = program.stat()
        _PACKAGED_IDENTITY = f"packaged:{program.name}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    return _PACKAGED_IDENTITY


def module_sources_sha256(paths: Iterable[Path | str]) -> str:
    """計算するモジュールのソースのSHA256（コードを直したら自動でキーが変わるように）。

    EXE（Nuitka）にはソースのファイルが無いので、無いファイルは EXE 自身の名前・大きさ・更新日時で代える
    （EXE を作り直せば鍵が変わる。2026-11-20、EXE では準備がここで止まっていた）。ソースから動かすときに
    ファイルが無ければ、今までどおり止める。
    """
    digest = hashlib.sha256()
    for path in sorted((Path(p) for p in paths), key=lambda p: p.name.casefold()):
        digest.update(path.name.encode("utf-8") + b"\0")
        try:
            data_digest = _source_file_digest(path)
        except FileNotFoundError:
            if not _is_packaged():
                raise
            digest.update(_packaged_program_identity())
            continue
        digest.update(data_digest)
    return digest.hexdigest()


# 同じプロセスの中で、ソースのファイルの中身の SHA-256 を、ファイルの識別（場所・機器と番号・大きさ・更新日時）ごとに
# 覚える（2026-11-20。準備のたびに、解析ごとに数個の .py を読んで SHA を求めていた）。
_SOURCE_DIGESTS: dict[tuple, bytes] = {}
_SOURCE_DIGESTS_LIMIT = 256


def _source_file_digest(path: Path) -> bytes:
    """path の中身の SHA-256（以前の hashlib.sha256(path.read_bytes()).digest() と同じ値）。無ければ FileNotFoundError。"""
    stat = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    found = _SOURCE_DIGESTS.get(key)
    if found is None:
        found = hashlib.sha256(path.read_bytes()).digest()
        while len(_SOURCE_DIGESTS) >= _SOURCE_DIGESTS_LIMIT:
            _SOURCE_DIGESTS.pop(next(iter(_SOURCE_DIGESTS)))
        _SOURCE_DIGESTS[key] = found
    return found


def analysis_cache_key(kind: str, revision: str, inputs: dict) -> str:
    payload = json.dumps({"format": FORMAT, "kind": kind, "revision": revision, "inputs": inputs},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 同じプロセスで最近（_MARK_INTERVAL_NS 以内に）印を付けたファイル。ペイントを開くたびに、車の解析が参照する
# 数百のテクスチャのファイルに印を付け直していた（約 0.01〜0.02 秒。2026-11-20）。最後に使った日時は、容量の整理で
# 古いものから消す順を決めるためだけに使うので、10 分の違いは整理の順に影響しない。
_MARKED_AT: dict[str, int] = {}
_MARK_INTERVAL_NS = 600 * 10**9


def mark_used(path: Path | str) -> None:
    """最後に使った日時として、最終アクセス日時を今にする。更新日時は保つ（失敗しても準備は止めない）。"""
    key = os.fspath(path)
    now = time.time_ns()
    if now - _MARKED_AT.get(key, -_MARK_INTERVAL_NS) < _MARK_INTERVAL_NS:
        return
    try:
        stat = os.stat(path)
        os.utime(path, ns=(now, stat.st_mtime_ns))
        _MARKED_AT[key] = now
    except OSError:
        pass


def cached_analysis(cache_root: Path | str, kind: str, key: str, build: Callable[[], dict], *,
                    valid: Callable[[dict], bool] | None = None,
                    metadata: dict | None = None) -> tuple[dict, bool]:
    """保存済みの結果があれば返す（hit=True）。無い・壊れている・valid が偽なら作って保存する。

    metadata（車種名・版など）は結果と一緒に保存し、将来の容量の整理で単位を見分けるのに使う。
    """
    folder = Path(cache_root) / kind
    path = folder / f"{key}.json"
    if path.is_file():
        try:
            # 同じプロセスの中で、同じ結果のファイル（場所・機器と番号・大きさ・更新日時）の読み取りは覚えて、marshal の
            # 写しを返す（2026-11-20。準備のたびに、内装の色の約 400 KB などの JSON を読み直していた）。
            from .process_file_memo import remembered
            saved = remembered("vehicle-analysis-file", [path], None,
                               lambda: json.loads(path.read_text(encoding="utf-8")), copy="marshal", limit=16)
        except (OSError, ValueError):
            saved = None
        if (isinstance(saved, dict) and saved.get("format") == FORMAT and saved.get("kind") == kind
                and saved.get("key") == key and isinstance(saved.get("result"), dict)
                and (valid is None or valid(saved["result"]))):
            mark_used(path)
            return saved["result"], True
    result = build()
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{key}.{os.getpid()}.tmp"
    try:
        temporary.write_text(json.dumps({"format": FORMAT, "kind": kind, "key": key,
                                         "metadata": dict(metadata or {}), "created": time.time(),
                                         "result": result}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return result, False


# ---- 容量の上限（将来用。既定では呼ばれず、何も消さない） ----

def cache_units(root: Path | str, *, unit_dirs: Iterable[str] = ()) -> list[dict]:
    """キャッシュを消す単位ごとの大きさと最後に使った日時（最終アクセス日時の最大）。

    unit_dirs に挙げたフォルダー名（例：'Original-Tire-Source-Signed-Standard'）の直下のフォルダーは、
    中身をまとめて 1 単位とする（GLBと証拠のJSONを片方だけ消さないため）。それ以外は、拡張子を除いた
    名前が同じファイル（例：original-tire-<key>.glb と .json）を 1 単位とする。
    """
    root = Path(root)
    grouped = {name.casefold() for name in unit_dirs}
    units: dict[tuple, dict] = {}
    for current, dirs, files in os.walk(root):
        here = Path(current)
        if here.name.casefold() in grouped:
            for name in list(dirs):
                folder = here / name
                size, used = 0, 0.0
                for inner, _subdirs, inner_files in os.walk(folder):
                    for file in inner_files:
                        stat = (Path(inner) / file).stat()
                        size += stat.st_size
                        used = max(used, stat.st_atime)
                units[("dir", str(folder))] = {"paths": [folder], "bytes": size, LAST_USED_FIELD: used}
            dirs[:] = []
        for file in files:
            path = here / file
            stat = path.stat()
            unit = units.setdefault(("file", str(here), file.split(".", 1)[0].casefold()),
                                    {"paths": [], "bytes": 0, LAST_USED_FIELD: 0.0})
            unit["paths"].append(path)
            unit["bytes"] += stat.st_size
            unit[LAST_USED_FIELD] = max(unit[LAST_USED_FIELD], stat.st_atime)
    return list(units.values())


# 削除の方針（2026-11-17 に利用者が承認）：
# 1. 判断は最後に使った日時（参照日時）。作成日時では判断しない。
# 2. 消す順番は「古い版の残骸」→「元のペイントが無くなったもの」→「大きくて長く使っていないもの」。
# 3. 次は消さない：表示中・利用者が残すと指定したもの・2車種以上で共通に使うもの・
#    小さくて作り直しに時間の掛かる解析結果・最近（既定 7 日以内）使ったもの。
#    ただし古い版の残骸と元のペイントが無いものは、表示中と指定したもの以外は保護しない。
# 4. 同じ段階の中では「大きさ × 使っていない期間 ÷ 作り直しの秒数」が大きいものから。
# 5. 単位（GLBと証拠のJSON等）ごとにまとめて消す。上限の 90% を超えたら始め、75% まで減らす。
RECENT_PROTECT_SECONDS = 7 * 24 * 3600
EVICTION_START_RATIO = 0.90
EVICTION_TARGET_RATIO = 0.75


def _eviction_stage(unit: dict) -> int:
    if unit.get("obsolete"):
        return 0
    if unit.get("orphan"):
        return 1
    return 2


def _eviction_protected(unit: dict, now: float, recent_seconds: float) -> bool:
    if unit.get("in_use") or unit.get("pinned"):
        return True
    if _eviction_stage(unit) < 2:
        return False
    return bool(int(unit.get("shared_by") or 0) >= 2 or unit.get("small_analysis")
                or now - float(unit.get(LAST_USED_FIELD) or 0.0) < recent_seconds)


def plan_eviction(units: list[dict], limit_bytes: int, *, now: float | None = None,
                  start_ratio: float = EVICTION_START_RATIO, target_ratio: float = EVICTION_TARGET_RATIO,
                  recent_seconds: float = RECENT_PROTECT_SECONDS) -> list[dict]:
    """上の方針で、消す単位を消す順に返す（消すのは呼び出し側）。上限の start_ratio 以下なら空。

    単位の項目：bytes・last_used（必須）、obsolete・orphan・in_use・pinned・shared_by（参照している
    車種の数）・small_analysis・rebuild_seconds（作り直しの秒数の目安、既定 1 秒）。
    保護されたものだけで target を超える場合は、消せる分だけを返す。
    """
    total = sum(int(unit["bytes"]) for unit in units)
    if limit_bytes <= 0 or total <= int(limit_bytes * start_ratio):
        return []
    now = time.time() if now is None else now
    target = int(limit_bytes * target_ratio)

    def score(unit: dict) -> float:
        idle = max(1.0, now - float(unit.get(LAST_USED_FIELD) or 0.0))
        return int(unit["bytes"]) * idle / max(1.0, float(unit.get("rebuild_seconds") or 1.0))

    candidates = [unit for unit in units if not _eviction_protected(unit, now, recent_seconds)]
    candidates.sort(key=lambda unit: (_eviction_stage(unit), -score(unit)))
    chosen = []
    for unit in candidates:
        if total <= target:
            break
        chosen.append(unit)
        total -= int(unit["bytes"])
    return chosen
