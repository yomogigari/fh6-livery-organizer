"""車体の形の GLB を、最近使った数台のほかは圧縮して保存する（キャッシュの容量を減らす。2026-11-20）。

車体の形の GLB（_fh6-vehicle-cache/meshes の *.local-chassis-v*.glb）は 1 台 約 30〜40 MB で、車のキャッシュの
大半を占める。lzma で約 4 分の 1 になる（4212 で 34.6 MB → 8.5 MB。展開は約 0.4 秒）。

- 準備のたびに、その車の GLB に最後に使った印を付ける。GLB が無く、圧縮した写し（<GLB の名前>.lzma）があれば、
  元の場所に戻す。戻すときは中身の大きさと SHA-256 を確かめ、更新日時も元に戻す。場所・大きさ・更新日時で
  決まる他のキャッシュ（部品の色付けの解析など）の鍵は変わらず、そのまま使える。
- 準備の後、裏の糸で、最近使った KEEP_EXPANDED 台より古く、PROTECT_SECONDS より前に使った GLB を、
  圧縮した写しを作ってから（作ってあれば確かめてから）消す。使用中のファイルは消せないので飛ばす。
- 圧縮した写しが壊れていれば使わずに消す（GLB は今までどおり作り直す）。
- 部品の選択肢（ボディーキット）の重ね合わせの GLB（*.overlay-firstparty-v*.glb）も同じ形で圧縮し、使う前に戻す
  （最近使った KEEP_EXPANDED_OVERLAYS 個を残す。2026-11-20）。
- 圧縮した写しの形（.lzma）：先頭 8 バイト b"LO4GLBZ1"、4 バイトの見出しの長さ（little endian）、見出し
  （UTF-8 の JSON：format・glb_name・glb_size・glb_sha256・glb_mtime_ns・codec）、残りは lzma の生の流れ
  （FILTERS）。
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
# 部品の選択肢（ボディーキット）の重ね合わせの GLB も同じく圧縮する（1 個 1〜13 MB、lzma で約 4 分の 1。2026-11-20）。
OVERLAY_PATTERN = "*.overlay-firstparty-v*.glb"
# 展開したまま残す数（今の車を含む）。重ね合わせは 1 台に選択肢の数だけあるので多めに残す。
KEEP_EXPANDED = 3
KEEP_EXPANDED_OVERLAYS = 6
# 最後に使ってから消してよくなるまでの秒数。別のプロセスが使っている最中に消さないため、最後に使った印の付け直しの
# 間隔（vehicle_analysis_cache.mark_used の 10 分）より長く。2026-11-20 に 1 時間から 11 分にした（作った直後の
# キャッシュを早く小さくする。最近の KEEP_EXPANDED 台は時間によらず残すので、続けて開く車は展開したまま）。
PROTECT_SECONDS = 660
_STORE_PATTERNS = ((PATTERN, KEEP_EXPANDED), (OVERLAY_PATTERN, KEEP_EXPANDED_OVERLAYS))
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None


class CompressedChassisError(ValueError):
    """圧縮した写しが読めない・中身が記録と違う。"""


def compressed_path(glb: Path) -> Path:
    return glb.with_name(glb.name + SUFFIX)


def _last_used_ns(path: Path) -> int:
    stat = path.stat()
    return max(stat.st_atime_ns, stat.st_mtime_ns)


def _mark_used(path: Path) -> None:
    from .vehicle_analysis_cache import mark_used
    mark_used(path)


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
    """見出しが、この GLB（名前・大きさ・更新日時）から作ったものか。"""
    try:
        stat = glb.stat()
    except OSError:
        return False
    return (header.get("glb_name") == glb.name and header.get("glb_size") == stat.st_size
            and header.get("glb_mtime_ns") == stat.st_mtime_ns and len(str(header.get("glb_sha256") or "")) == 64)


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

    同じプロセスの裏の糸（evict）と同じ錠の中で行う（戻した直後・印を付ける前に消されない）。
    """
    with _LOCK:
        restored = _restore_locked(glb)
        if glb.is_file():
            _mark_used(glb)
        return restored


def evict(mesh_dir: Path, keep: Path | None = None, *, now_ns: int | None = None) -> list[Path]:
    """最近使った KEEP_EXPANDED 台（keep を含む）より古く、PROTECT_SECONDS より前に使った GLB を、
    圧縮した写しを作ってから消す。消した GLB の一覧を返す（消せなかったものは飛ばす）。
    車体の GLB と、部品の選択肢の重ね合わせの GLB（KEEP_EXPANDED_OVERLAYS 個を残す）を、それぞれ並べて決める。"""
    now_ns = time.time_ns() if now_ns is None else now_ns
    removed: list[Path] = []
    for pattern, keep_count in _STORE_PATTERNS:
        removed += _evict_pattern(mesh_dir, pattern, keep_count, keep, now_ns)
    return removed


def _evict_pattern(mesh_dir: Path, pattern: str, keep_count: int, keep: Path | None, now_ns: int) -> list[Path]:
    try:
        expanded = [path for path in mesh_dir.glob(pattern) if path.is_file()]
    except OSError:
        return []
    keep_resolved = keep.resolve() if keep is not None else None
    ranked = sorted(expanded, key=lambda path: (path.resolve() == keep_resolved, _last_used_ns(path)), reverse=True)
    removed: list[Path] = []
    for path in ranked[max(1, keep_count):]:
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


def _clean_partials(mesh_dir: Path, now_ns: int) -> None:
    """途中で止まった書き出しの残り（1 時間より前のもの）を消す。"""
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
    """準備の後に呼ぶ：裏の糸で evict を動かす（同じプロセスでは 1 本だけ。動いていれば何もしない）。"""
    global _WORKER
    with _LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return None

        def run() -> None:
            now_ns = time.time_ns()
            _clean_partials(mesh_dir, now_ns)
            evict(mesh_dir, keep, now_ns=now_ns)

        _WORKER = threading.Thread(target=run, name="lo4fh6-chassis-store", daemon=True)
        _WORKER.start()
        return _WORKER
