"""車体の形の GLB を、最近使った数台のほかは消して、消した印だけを残す（キャッシュの容量を減らす。2026-11-20・21）。

車体の形の GLB（_fh6-vehicle-cache/meshes の *.local-chassis-v*.glb）は 1 台 約 20〜40 MB で、車のキャッシュの
大半を占める。

- 準備のたびに、その車の GLB に最後に使った印を付ける。
- 準備の後、裏の糸で、最近使った KEEP_EXPANDED 台より古く、PROTECT_SECONDS より前に使った GLB を消す。消す前に、
  消した印（<GLB の名前>.evicted.json。名前・大きさ・SHA-256・更新日時だけの小さな JSON）を書く。使用中の
  ファイルは消せないので飛ばす。
  （2026-11-21、FH6 に近づける案 ④。以前は lzma で圧縮した写しを残していた。1 台 平均 5.8 MB、全ペイントの
  撮影の 344 台で 1.99 GB。戻すのは約 0.3 秒、作り直すのは Rust の部品で約 1 秒。）
- 次にその車を使うときは、GLB を今までどおり作り直す。作り直した GLB の大きさと SHA-256 が消した印と同じなら、
  更新日時を消す前に戻す（adopt_evicted_identity）。場所・大きさ・更新日時で決まる他のキャッシュ（部品の色付けの
  解析・タイヤの GLB など）の鍵が変わらず、そのまま使える。違えば印を消すだけ（他のキャッシュは今までどおり
  作り直す）。
- 以前の版が残した車体の圧縮の写し（<GLB の名前>.lzma）は、GLB が無ければ使う前に戻す（prepare_for_use）。
  裏の糸は、PROTECT_SECONDS より前に作られた写しを、その見出しから消した印に書き換えて消す（中身は読まない）。
- 部品の選択肢（ボディーキット）の重ね合わせの GLB（*.overlay-firstparty-v*.glb）は、今までどおり圧縮した写しを
  残し、使う前に戻す（最近使った KEEP_EXPANDED_OVERLAYS 個を残す。表示する部品だけを作るので数が少ない）。
- 圧縮した写しの形（.lzma）：先頭 8 バイト b"LO4GLBZ1"、4 バイトの見出しの長さ（little endian）、見出し
  （UTF-8 の JSON：format・glb_name・glb_size・glb_sha256・glb_mtime_ns・codec）、残りは lzma の生の流れ
  （FILTERS）。
- 消した印の形（.evicted.json）：UTF-8 の JSON（format・glb_name・glb_size・glb_sha256・glb_mtime_ns）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import lzma
import os
import struct
import threading
import time
from pathlib import Path

MAGIC = b"LO4GLBZ1"
FORMAT = "lo4fh6.compressed-glb.v1"
CODEC = "lzma2-raw-preset1-lc0-lp2-pb2"
FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 1, "lc": 0, "lp": 2, "pb": 2}]
SUFFIX = ".lzma"
PATTERN = "*.local-chassis-v*.glb"
# 消した印（2026-11-21）
EVICTED_SUFFIX = ".evicted.json"
EVICTED_FORMAT = "lo4fh6.evicted-glb.v1"
# 部品の選択肢（ボディーキット）の重ね合わせの GLB は圧縮する（1 個 1〜13 MB、lzma で約 4 分の 1。2026-11-20）。
OVERLAY_PATTERN = "*.overlay-firstparty-v*.glb"
# 展開したまま残す数（今の車を含む）。重ね合わせは 1 台に選択肢の数だけあるので多めに残す。
KEEP_EXPANDED = 3
KEEP_EXPANDED_OVERLAYS = 6
# 最後に使ってから消してよくなるまでの秒数。別のプロセスが使っている最中に消さないため、最後に使った印の付け直しの
# 間隔（vehicle_analysis_cache.mark_used の 10 分）より長く。2026-11-20 に 1 時間から 11 分にした（作った直後の
# キャッシュを早く小さくする。最近の KEEP_EXPANDED 台は時間によらず残すので、続けて開く車は消さない）。
PROTECT_SECONDS = 660
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None


class CompressedChassisError(ValueError):
    """圧縮した写しが読めない・中身が記録と違う。"""


def compressed_path(glb: Path) -> Path:
    return glb.with_name(glb.name + SUFFIX)


def evicted_path(glb: Path) -> Path:
    return glb.with_name(glb.name + EVICTED_SUFFIX)


def _last_used_ns(path: Path) -> int:
    stat = path.stat()
    return max(stat.st_atime_ns, stat.st_mtime_ns)


def _mark_used(path: Path) -> None:
    from .vehicle_analysis_cache import mark_used
    mark_used(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_header(path: Path) -> tuple[dict, int]:
    """圧縮した写しの見出しと、本体の始まりの位置。"""
    with path.open("rb") as handle:
        head = handle.read(12)
        if len(head) != 12 or head[:8] != MAGIC:
            raise CompressedChassisError("圧縮した GLB の印が違う")
        size, = struct.unpack_from("<I", head, 8)
        if not 0 < size <= 1 << 20:
            raise CompressedChassisError("圧縮した GLB の見出しの長さが違う")
        header = json.loads(handle.read(size).decode("utf-8"))
    if not isinstance(header, dict) or header.get("format") != FORMAT or header.get("codec") != CODEC:
        raise CompressedChassisError("圧縮した GLB の形が違う")
    return header, 12 + size


def _matches(header: dict, glb: Path) -> bool:
    """見出し（圧縮した写し・消した印）が、この GLB（名前・大きさ・更新日時）から作ったものか。"""
    try:
        stat = glb.stat()
    except OSError:
        return False
    return (header.get("glb_name") == glb.name and header.get("glb_size") == stat.st_size
            and header.get("glb_mtime_ns") == stat.st_mtime_ns and len(str(header.get("glb_sha256") or "")) == 64)


def _identity_fields_valid(record: dict, glb: Path) -> bool:
    return (record.get("glb_name") == glb.name and type(record.get("glb_size")) is int
            and type(record.get("glb_mtime_ns")) is int and len(str(record.get("glb_sha256") or "")) == 64)


def write_compressed(glb: Path) -> Path:
    """GLB の圧縮した写しを書いて場所を返す（同じ GLB から作った写しがすでにあれば書かない）。"""
    target = compressed_path(glb)
    try:
        header, _ = read_header(target)
        if _matches(header, glb):
            return target
    except (OSError, ValueError):
        pass
    stat = glb.stat()
    data = glb.read_bytes()
    if len(data) != stat.st_size or glb.stat().st_mtime_ns != stat.st_mtime_ns:
        raise CompressedChassisError("圧縮の途中で GLB が変わった")
    header = {"format": FORMAT, "codec": CODEC, "glb_name": glb.name, "glb_size": len(data),
              "glb_sha256": hashlib.sha256(data).hexdigest(), "glb_mtime_ns": stat.st_mtime_ns}
    head = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = lzma.compress(data, format=lzma.FORMAT_RAW, filters=FILTERS)
    partial = target.with_name(target.name + f".{os.getpid()}.partial")
    try:
        partial.write_bytes(MAGIC + struct.pack("<I", len(head)) + head + body)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def read_evicted_record(glb: Path) -> dict | None:
    """GLB の消した印（無い・読めない・形が違えば None）。"""
    try:
        record = json.loads(evicted_path(glb).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("format") != EVICTED_FORMAT or not _identity_fields_valid(record, glb):
        return None
    return record


def _write_evicted_record(glb: Path, *, size: int, sha256: str, mtime_ns: int) -> Path:
    target = evicted_path(glb)
    record = {"format": EVICTED_FORMAT, "glb_name": glb.name, "glb_size": int(size),
              "glb_sha256": str(sha256), "glb_mtime_ns": int(mtime_ns)}
    partial = target.with_name(target.name + f".{os.getpid()}.partial")
    try:
        partial.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def write_evicted_record(glb: Path) -> Path:
    """GLB の消した印を書いて場所を返す（同じ GLB の印がすでにあれば書かない。無ければ中身の SHA-256 を求める）。"""
    record = read_evicted_record(glb)
    if record is not None and _matches(record, glb):
        return evicted_path(glb)
    stat = glb.stat()
    sha256 = _sha256_file(glb)
    after = glb.stat()
    if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
        raise CompressedChassisError("印を書く途中で GLB が変わった")
    return _write_evicted_record(glb, size=stat.st_size, sha256=sha256, mtime_ns=stat.st_mtime_ns)


def adopt_evicted_identity(glb: Path) -> bool:
    """作り直した GLB の大きさと SHA-256 が消した印と同じなら、更新日時を消す前に戻す（最終アクセスは今）。

    戻した（もともと同じだった）ら True。印は、合っても合わなくても消す。GLB が無ければ何もしない。
    """
    with _LOCK:
        if not glb.is_file():
            return False
        record = read_evicted_record(glb)
        adopted = False
        if record is not None:
            try:
                stat = glb.stat()
                if stat.st_size == record["glb_size"]:
                    if stat.st_mtime_ns == record["glb_mtime_ns"]:
                        adopted = True
                    elif _sha256_file(glb) == record["glb_sha256"]:
                        os.utime(glb, ns=(time.time_ns(), record["glb_mtime_ns"]))
                        adopted = True
            except OSError:
                adopted = False
        with contextlib.suppress(OSError):
            evicted_path(glb).unlink(missing_ok=True)
        return adopted


def _restore_locked(glb: Path) -> bool:
    if glb.is_file():
        return False
    source = compressed_path(glb)
    if not source.is_file():
        return False
    try:
        header, start = read_header(source)
        if header.get("glb_name") != glb.name:
            raise CompressedChassisError("圧縮した GLB の名前が違う")
        with source.open("rb") as handle:
            handle.seek(start)
            data = lzma.decompress(handle.read(), format=lzma.FORMAT_RAW, filters=FILTERS)
        if len(data) != header.get("glb_size") or hashlib.sha256(data).hexdigest() != header.get("glb_sha256"):
            raise CompressedChassisError("展開した GLB が記録と違う")
    except OSError:
        return False  # 読めない（使用中など、一時的なことがある）。写しは残す
    except (ValueError, lzma.LZMAError, KeyError):
        with contextlib.suppress(OSError):
            source.unlink(missing_ok=True)  # 壊れている・記録と違う写しは使わない
        return False
    partial = glb.with_name(glb.name + f".{os.getpid()}.restore.partial")
    mtime_ns = int(header["glb_mtime_ns"])
    try:
        partial.write_bytes(data)
        # 更新日時は元の GLB のまま（他のキャッシュの鍵が変わらない）。置き換えは名前の付け替えなので日時はそのまま。
        os.utime(partial, ns=(time.time_ns(), mtime_ns))
        partial.replace(glb)
    except OSError:
        return False  # 別のプロセスが同じ GLB を同時に戻して使っているなど。あればそれを使う
    finally:
        with contextlib.suppress(OSError):
            partial.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        os.utime(glb, ns=(time.time_ns(), mtime_ns))  # 最終アクセスは今（最後に使った印）
    return True


def restore(glb: Path) -> bool:
    """GLB が無く、圧縮した写しがあれば元の場所に戻す（中身と更新日時を元どおりにする）。戻したら True。

    写しが壊れている・中身が記録と違うときは、写しを消して False（GLB は呼び出し側が今までどおり作り直す）。
    """
    with _LOCK:
        return _restore_locked(glb)


def prepare_for_use(glb: Path) -> bool:
    """準備の前に呼ぶ：無ければ圧縮した写しから戻し、最後に使った印を付ける。戻したら True。

    車体の GLB を消した印だけのとき（2026-11-21〜）は何もしない（呼び出し側が作り直し、adopt_evicted_identity を呼ぶ）。
    同じプロセスの裏の糸（evict）と同じ錠の中で行う（戻した直後・印を付ける前に消されない）。
    """
    with _LOCK:
        restored = _restore_locked(glb)
        if glb.is_file():
            _mark_used(glb)
        return restored


def _ranked_candidates(mesh_dir: Path, pattern: str, keep_count: int, keep: Path | None) -> tuple[list[Path], Path | None]:
    """消してよいかを見る候補（最近使った keep_count 個（keep を含む）のほか）と、keep の解決した場所。"""
    try:
        expanded = [path for path in mesh_dir.glob(pattern) if path.is_file()]
    except OSError:
        return [], None
    keep_resolved = keep.resolve() if keep is not None else None
    ranked = sorted(expanded, key=lambda path: (path.resolve() == keep_resolved, _last_used_ns(path)), reverse=True)
    return ranked[max(1, keep_count):], keep_resolved


def evict(mesh_dir: Path, keep: Path | None = None, *, now_ns: int | None = None) -> list[Path]:
    """最近使った数台（keep を含む）より古く、PROTECT_SECONDS より前に使った GLB を消す。消した GLB の一覧を返す
    （消せなかったものは飛ばす）。

    - 車体の GLB（KEEP_EXPANDED 台を残す）：消した印を書いてから消す。以前の版の圧縮の写しがあれば一緒に消す。
    - 部品の選択肢の重ね合わせの GLB（KEEP_EXPANDED_OVERLAYS 個を残す）：圧縮した写しを作ってから消す。
    """
    now_ns = time.time_ns() if now_ns is None else now_ns
    return _evict_chassis(mesh_dir, keep, now_ns) + _evict_compressed(mesh_dir, OVERLAY_PATTERN,
                                                                       KEEP_EXPANDED_OVERLAYS, keep, now_ns)


def _evict_chassis(mesh_dir: Path, keep: Path | None, now_ns: int) -> list[Path]:
    candidates, keep_resolved = _ranked_candidates(mesh_dir, PATTERN, KEEP_EXPANDED, keep)
    removed: list[Path] = []
    for path in candidates:
        try:
            before = _last_used_ns(path)
            if path.resolve() == keep_resolved or now_ns - before < PROTECT_SECONDS * 10**9:
                continue
            write_evicted_record(path)
            with _LOCK:
                # 印を書く間に使われていない（最後に使った日時が変わっていない）か、印が今の GLB のものかを確かめ直して
                # から消す。印のために読んだことで OS が最終アクセスを更新したときも、今回は消さない（次の機会には
                # 印があるので読まずに確かめられる）。
                record = read_evicted_record(path)
                if record is None or _last_used_ns(path) != before or not _matches(record, path):
                    continue
                path.unlink()
                with contextlib.suppress(OSError):
                    compressed_path(path).unlink(missing_ok=True)  # 以前の版の写しも、もう要らない
            removed.append(path)
        except (OSError, ValueError):
            continue
    return removed


def _evict_compressed(mesh_dir: Path, pattern: str, keep_count: int, keep: Path | None, now_ns: int) -> list[Path]:
    candidates, keep_resolved = _ranked_candidates(mesh_dir, pattern, keep_count, keep)
    removed: list[Path] = []
    for path in candidates:
        try:
            before = _last_used_ns(path)
            if path.resolve() == keep_resolved or now_ns - before < PROTECT_SECONDS * 10**9:
                continue
            write_compressed(path)
            with _LOCK:
                # 圧縮の間に使われていない（最後に使った日時が変わっていない）か、写しが今の GLB から作ったものかを
                # 確かめ直してから消す。圧縮で読んだために OS が最終アクセスを更新したときも、今回は消さない
                # （次の機会には写しがあるので読まずに確かめられる）。
                header, _ = read_header(compressed_path(path))
                if _last_used_ns(path) != before or not _matches(header, path):
                    continue
                path.unlink()
            removed.append(path)
        except (OSError, ValueError, lzma.LZMAError):
            continue
    return removed


def retire_legacy_copies(mesh_dir: Path, *, now_ns: int | None = None) -> list[Path]:
    """以前の版が残した車体の圧縮の写しのうち、GLB が無く、PROTECT_SECONDS より前に作られたものを、見出しから
    消した印に書き換えて消す（中身は読まない）。消した写しの一覧を返す。"""
    now_ns = time.time_ns() if now_ns is None else now_ns
    retired: list[Path] = []
    try:
        copies = [path for path in mesh_dir.glob(PATTERN + SUFFIX) if path.is_file()]
    except OSError:
        return []
    for copy in copies:
        glb = copy.with_name(copy.name[: -len(SUFFIX)])
        try:
            if glb.exists() or now_ns - copy.stat().st_mtime_ns < PROTECT_SECONDS * 10**9:
                continue
            header, _ = read_header(copy)
            if not _identity_fields_valid(header, glb):
                continue
            with _LOCK:
                if glb.exists():
                    continue  # 別のプロセスが戻した
                _write_evicted_record(glb, size=header["glb_size"], sha256=header["glb_sha256"],
                                      mtime_ns=header["glb_mtime_ns"])
                copy.unlink()
            retired.append(copy)
        except (OSError, ValueError):
            continue
    return retired


def _clean_partials(mesh_dir: Path, now_ns: int) -> None:
    """途中で止まった書き出しの残り（PROTECT_SECONDS より前のもの）を消す。"""
    try:
        for path in mesh_dir.glob("*.partial"):
            try:
                if now_ns - path.stat().st_mtime_ns > PROTECT_SECONDS * 10**9:
                    path.unlink()
            except OSError:
                continue
    except OSError:
        pass


def schedule_maintenance(mesh_dir: Path, keep: Path | None = None) -> threading.Thread | None:
    """準備の後に呼ぶ：裏の糸で evict と retire_legacy_copies を動かす（同じプロセスでは 1 本だけ。動いていれば何もしない）。"""
    global _WORKER
    with _LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return None

        def run() -> None:
            now_ns = time.time_ns()
            _clean_partials(mesh_dir, now_ns)
            evict(mesh_dir, keep, now_ns=now_ns)
            retire_legacy_copies(mesh_dir, now_ns=now_ns)

        _WORKER = threading.Thread(target=run, name="lo4fh6-chassis-store", daemon=True)
        _WORKER.start()
        return _WORKER
