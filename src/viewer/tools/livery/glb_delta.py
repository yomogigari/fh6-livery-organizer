"""GLB の差分の保存（キャッシュの容量を減らす。2026-11-20）。

標準タイヤ付きの車体などの GLB は、車体の形の GLB とほとんど同じ中身を持つ（4212 で 36.3 MB のうち 29.0 MB が同じ）。
丸ごと保存せず、土台の GLB との差分だけを保存し、使うときに組み立て直す。組み立てた GLB は元の GLB と 1 バイトも
違わない（SHA-256 で確かめる。違えば使わない）。

差分の形（.glbdelta）：
- 先頭 8 バイト：b"LO4GLBD1"
- 4 バイト：目録の長さ（little endian）、続けて目録（UTF-8 の JSON を zlib で圧縮したもの）
- 残り：自前のバイト列（zlib で圧縮）
目録：
- format・target_sha256・target_length・base_sha256・base_length
- header：GLB の先頭 12 バイトとチャンクの見出しを含む、BIN チャンクより前の全部（JSON チャンクを含む）は自前のバイト列に入れる
- segments：組み立ての順に [種類, 位置, 長さ]。種類 "b" は土台の GLB のバイト（位置は土台の中）、"o" は自前のバイト列
土台の GLB の中から同じバイト列を探す単位は、比べる GLB の bufferView（データの区画）。土台の bufferView と
バイト列が同じものを参照にし、ほかは自前のバイト列に入れる。区画の間の詰め物・BIN より後ろのチャンクも自前。
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import zlib
from pathlib import Path

MAGIC = b"LO4GLBD1"
FORMAT = "lo4fh6.glb-delta.v1"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class GlbDeltaError(ValueError):
    """差分を作れない・組み立てた結果が元と一致しない。"""


class GlbDeltaBaseMismatch(GlbDeltaError):
    """差分の土台が、作ったときの土台と違う（土台が作り直された）。差分を作り直せばよい。"""


def _chunks(data: bytes) -> list[tuple[int, int, int]]:
    """GLB のチャンクの一覧 [(種類, データの開始位置, 長さ)]。GLB でなければ例外。"""
    if len(data) < 12:
        raise GlbDeltaError("GLB が短すぎる")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or length != len(data):
        raise GlbDeltaError("GLB の見出しが不正")
    chunks = []
    offset = 12
    while offset < length:
        if offset + 8 > length:
            raise GlbDeltaError("GLB のチャンクの見出しが途中で切れている")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        start = offset + 8
        if start + chunk_length > length:
            raise GlbDeltaError("GLB のチャンクが途中で切れている")
        chunks.append((chunk_type, start, chunk_length))
        offset = start + chunk_length
    return chunks


def _views(data: bytes) -> tuple[int, int, list[tuple[int, int]]]:
    """BIN チャンクの開始位置・長さと、bufferView の [(BIN の中の位置, 長さ)]（buffer 0 のものだけ）。"""
    chunks = _chunks(data)
    json_chunk = next((c for c in chunks if c[0] == _JSON_CHUNK), None)
    bin_chunk = next((c for c in chunks if c[0] == _BIN_CHUNK), None)
    if json_chunk is None:
        raise GlbDeltaError("GLB に JSON チャンクが無い")
    if bin_chunk is None:
        return 0, 0, []
    doc = json.loads(data[json_chunk[1]:json_chunk[1] + json_chunk[2]])
    views = []
    for view in doc.get("bufferViews", []) or []:
        if int(view.get("buffer", 0)) != 0:
            continue
        start = int(view.get("byteOffset", 0))
        size = int(view.get("byteLength", 0))
        if size > 0 and 0 <= start and start + size <= bin_chunk[2]:
            views.append((start, size))
    return bin_chunk[1], bin_chunk[2], views


def make_delta(target: bytes, base: bytes) -> bytes:
    """target（GLB）を base（GLB）との差分にする。組み立て直すと target と同じバイト列になる。"""
    bin_start, bin_length, target_views = _views(target)
    base_bin_start, _, base_views = _views(base)
    # 土台の区画を (長さ, SHA-1) で引けるようにする（同じ中身の区画が複数あれば最初のもの）
    index: dict[tuple[int, bytes], int] = {}
    for start, size in base_views:
        index.setdefault((size, hashlib.sha1(base[base_bin_start + start:base_bin_start + start + size]).digest()),
                         base_bin_start + start)
    own = bytearray()
    segments: list[list] = []

    def add_own(start: int, end: int) -> None:
        if end <= start:
            return
        if segments and segments[-1][0] == "o" and segments[-1][1] + segments[-1][2] == len(own):
            segments[-1][2] += end - start
        else:
            segments.append(["o", len(own), end - start])
        own.extend(target[start:end])

    def add_base(position: int, size: int) -> None:
        if segments and segments[-1][0] == "b" and segments[-1][1] + segments[-1][2] == position:
            segments[-1][2] += size
        else:
            segments.append(["b", position, size])

    cursor = 0
    if bin_length:
        add_own(0, bin_start)  # BIN より前（GLB の見出し・JSON チャンク・BIN の見出し）
        cursor = bin_start
        for start, size in sorted(target_views):
            absolute = bin_start + start
            if absolute < cursor:
                continue  # 重なる区画は、前の区画で入れ済み
            add_own(cursor, absolute)
            chunk = target[absolute:absolute + size]
            found = index.get((size, hashlib.sha1(chunk).digest()))
            if found is not None and base[found:found + size] == chunk:
                add_base(found, size)
            else:
                add_own(absolute, absolute + size)
            cursor = absolute + size
    add_own(cursor, len(target))
    manifest = {
        "format": FORMAT,
        "target_sha256": hashlib.sha256(target).hexdigest(),
        "target_length": len(target),
        "base_sha256": hashlib.sha256(base).hexdigest(),
        "base_length": len(base),
        "segments": segments,
    }
    packed_manifest = zlib.compress(json.dumps(manifest, separators=(",", ":")).encode("utf-8"), 9)
    delta = MAGIC + struct.pack("<I", len(packed_manifest)) + packed_manifest + zlib.compress(bytes(own), 6)
    if apply_delta(delta, base) != target:
        raise GlbDeltaError("差分から組み立てた GLB が元と一致しない")
    return delta


def read_manifest(delta: bytes) -> dict:
    if not delta.startswith(MAGIC) or len(delta) < len(MAGIC) + 4:
        raise GlbDeltaError("GLB の差分ではない")
    (size,) = struct.unpack_from("<I", delta, len(MAGIC))
    start = len(MAGIC) + 4
    manifest = json.loads(zlib.decompress(delta[start:start + size]))
    if manifest.get("format") != FORMAT:
        raise GlbDeltaError("GLB の差分の版が違う")
    return manifest


def apply_delta(delta: bytes, base: bytes) -> bytes:
    """差分と土台から GLB を組み立てる。土台が違う・組み立てた結果の SHA-256 が記録と違えば例外。"""
    manifest = read_manifest(delta)
    if len(base) != manifest["base_length"] or hashlib.sha256(base).hexdigest() != manifest["base_sha256"]:
        raise GlbDeltaBaseMismatch("GLB の差分の土台が違う")
    (size,) = struct.unpack_from("<I", delta, len(MAGIC))
    own = zlib.decompress(delta[len(MAGIC) + 4 + size:])
    out = bytearray()
    for kind, position, length in manifest["segments"]:
        source = base if kind == "b" else own
        if position < 0 or position + length > len(source):
            raise GlbDeltaError("GLB の差分の参照が範囲の外")
        out.extend(source[position:position + length])
    data = bytes(out)
    if len(data) != manifest["target_length"] or hashlib.sha256(data).hexdigest() != manifest["target_sha256"]:
        raise GlbDeltaError("差分から組み立てた GLB の SHA が記録と違う")
    return data


def write_delta_file(path: Path, target: bytes, base: bytes) -> dict:
    """差分のファイルを書く（一時の名前に書いてから置き換える）。目録を返す。"""
    delta = make_delta(target, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(delta)
    partial.replace(path)
    return read_manifest(delta)


# ---- 組み立てた GLB の置き場（差分から組み立てた GLB を、表示の間だけファイルとして置く） ----
MATERIALIZED_DIR = "Materialized-GLB"
MATERIALIZED_KEEP = 4  # 側面の文字のある車は、標準タイヤと側面の文字の 2 つを使う
_VERIFIED_MATERIALIZED: set[tuple[str, int, int, int, int]] = set()


def _verified_identity(path: Path, stat: os.stat_result) -> tuple[str, int, int, int, int]:
    """確かめた GLB の識別。場所は resolve せず（Windows ではファイルを開いて閉じ、さらに stat する）abspath にし、
    どのファイルかは stat の機器と番号で見分ける（2026-11-20）。"""
    return (os.path.normcase(os.path.abspath(path)), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _remember_verified(path: Path) -> None:
    _VERIFIED_MATERIALIZED.add(_verified_identity(path, path.stat()))


def _already_verified(path: Path, expected_sha: str) -> bool:
    """置き場の GLB が記録の SHA と同じか（同じプロセスで一度確かめたものは、大きさと時刻が同じなら確かめ直さない）。"""
    try:
        stat = path.stat()
    except OSError:
        return False
    if _verified_identity(path, stat) in _VERIFIED_MATERIALIZED:
        return True
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        return False
    _remember_verified(path)
    return True


def _mark_recently_used(path: Path) -> None:
    """最近使ったものとして、最終アクセスの時刻だけを今にする（更新日時は変えない）。

    更新日時を変えると、ファイルの識別（場所・大きさ・更新日時）が準備のたびに変わる。すると、照合済みの記録が
    外れて毎回 SHA を計算し直し、同じ車の次のペイントの差し替え（サーバーが渡す GLB の識別が前と同じときだけ
    働く）も効かなくなる（2026-11-20 に確認）。最終アクセスの時刻は明示して書くので、OS の自動更新の設定に依らない。
    """
    try:
        stat = path.stat()
        os.utime(path, ns=(time.time_ns(), stat.st_mtime_ns))
    except OSError:
        pass


def _trim_store(store: Path, keep: Path) -> None:
    """置き場に残すのは、最近使った MATERIALIZED_KEEP 個まで（今使うものは残す）。"""
    try:
        entries = [p for p in store.iterdir() if p.is_file() and p.suffix == ".glb" and p != keep]
    except OSError:
        return
    entries.sort(key=lambda p: max(p.stat().st_atime, p.stat().st_mtime), reverse=True)
    for old in entries[MATERIALIZED_KEEP - 1:]:
        try:
            old.unlink()
        except OSError:
            pass


def place_materialized(store: Path, data: bytes, expected_sha: str, base: Path | None = None) -> Path:
    """組み立てた GLB（バイト列）を置き場に置いて場所を返す。SHA が記録と違えば例外。

    base を渡すと、置いた GLB の名前にも同じ土台を登録する（次の段がこの GLB を入力にして差分で保存できる）。
    """
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise GlbDeltaError("組み立てた GLB の SHA が記録と違う")
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{expected_sha}.glb"
    if not _already_verified(path, expected_sha):
        partial = path.with_name(path.name + ".partial")
        partial.write_bytes(data)
        partial.replace(path)
        _remember_verified(path)
    _trim_store(store, path)
    if base is not None:
        register_delta_base(path.name, base)
    return path


def materialize(delta_path: Path, base_path: Path, store: Path, expected_sha: str) -> Path:
    """差分のファイルと土台の GLB から GLB を組み立てて置き場に置き、場所を返す。

    置き場にすでに同じ GLB があれば組み立てない。土台が違う・SHA が違えば GlbDeltaError。
    """
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{expected_sha}.glb"
    if _already_verified(path, expected_sha):
        _mark_recently_used(path)
        _trim_store(store, path)
        register_delta_base(path.name, base_path)
        return path
    delta = delta_path.read_bytes()
    if read_manifest(delta).get("target_sha256") != expected_sha:
        raise GlbDeltaError("GLB の差分の出来上がりの SHA が記録と違う")
    return place_materialized(store, apply_delta(delta, base_path.read_bytes()), expected_sha, base_path)


# ---- 差分の土台の登録（同じプロセスの中で、作った GLB の名前から土台の GLB を引く） ----
# 元の車体＋原本タイヤの GLB の名前（original-tire-<鍵>.glb）は、車体の形の GLB の SHA などから決まる。標準タイヤの段は
# その名前だけを受け取るので、鍵を決めた所（source_tire_local_runtime.local_tire_cache_paths）が土台を登録しておく。
_DELTA_BASES: dict[str, Path] = {}


def register_delta_base(name: str, base: Path) -> None:
    _DELTA_BASES[str(name)] = Path(base)


def delta_base_for(name: str) -> Path | None:
    base = _DELTA_BASES.get(str(name))
    return base if base is not None and base.is_file() else None
