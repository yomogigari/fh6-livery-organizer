"""自前の部品（native/lo4fh6_native.dll。Rust で作る。ソースは native/lo4fh6_native）を読み込んで使う（2026-11-20、FH6 に近づける案 ④）。

- DLL は、下の DLL_SHA256 と中身が同じときだけ読み込む（作り方は fh6-livery-viewer-internal の
  tools/native/build_lo4fh6_native.py。配布の EXE では、fh6-livery-organizer-internal のキットが同じバイト列に作る）。
- 公開の fh6-livery-organizer（ソースだけ）には DLL が無いので、Python で同じ計算をする。
- 無い・SHA が合わない・読み込めない・Windows でない・環境変数 LO4FH6_NATIVE=0 のときは None を返す。呼び出し側は
  今までの Python の処理を使う（結果は同じ）。
- 結果は Python の処理とバイト単位で同じ（tests/viewer/test_viewer_native_kernels.py で比べる）。
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import os
import random
import struct
import sys
import threading
from pathlib import Path

DLL_NAME = "lo4fh6_native.dll"
NATIVE_VERSION = 3  # 1 は C の版、2 は Rust の BC4 だけの版、3 は C_livery の解読を足した版（2026-11-20）
# C_livery の解読の出力の図形 1 つ（Rust の RECORD_SIZE と同じ並び）
LIVERY_RECORD = struct.Struct("<6dIIIHBB4B")
# 作った DLL の SHA-256（build_lo4fh6_native.py が書き込む）。違う DLL は読み込まない。
DLL_SHA256 = "0e7c4960b8c802d0ae3816e625c07c4a8844db92a8a1671bb4fe1812661418cf"

_LOCK = threading.Lock()
_STATE: dict[str, object] = {"tried": False, "library": None, "math_ok": None}


def dll_path() -> Path:
    return Path(__file__).resolve().parent / "native" / DLL_NAME


def _load() -> ctypes.CDLL | None:
    if os.environ.get("LO4FH6_NATIVE", "").strip() == "0" or sys.platform != "win32":
        return None
    path = dll_path()
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not DLL_SHA256 or hashlib.sha256(data).hexdigest() != DLL_SHA256:
        return None
    try:
        library = ctypes.CDLL(str(path))
        version = library.lo4_native_version
        version.argtypes = []
        version.restype = ctypes.c_int
        if version() != NATIVE_VERSION:
            return None
        decode = library.lo4_decode_bc4_unorm
        decode.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        decode.restype = ctypes.c_int
        layers = library.lo4_decode_livery_layers
        layers.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint32), ctypes.c_char_p,
                           ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
        layers.restype = ctypes.c_int
        evaluate = library.lo4_math_eval
        evaluate.argtypes = [ctypes.c_int, ctypes.c_double, ctypes.c_double]
        evaluate.restype = ctypes.c_double
    except (OSError, AttributeError):
        return None
    return library


def library() -> ctypes.CDLL | None:
    with _LOCK:
        if not _STATE["tried"]:
            _STATE["tried"] = True
            _STATE["library"] = _load()
        return _STATE["library"]  # type: ignore[return-value]


def reset_for_tests() -> None:
    with _LOCK:
        _STATE["tried"] = False
        _STATE["library"] = None
        _STATE["math_ok"] = None


def decode_bc4_unorm(payload: bytes, width: int, height: int):
    """符号なしの BC4 を 8 ビットの画像（numpy の uint8、高さ×幅）に戻す。自前の部品が使えなければ None。"""
    lib = library()
    if lib is None:
        return None
    import numpy as np
    out = np.empty((int(height), int(width)), dtype=np.uint8)
    code = lib.lo4_decode_bc4_unorm(bytes(payload), len(payload), int(width), int(height), out.ctypes.data)
    return out if code == 0 else None


def _math_matches(lib: ctypes.CDLL) -> bool:
    """部品の三角関数などが、この Python の math と同じ値を返すか（プロセスごとに 1 回、約 600 個の値で確かめる）。

    部品は Python の math と同じ Windows の関数（ucrtbase.dll）と、CPython 3.12 の hypot と同じ手順を使う。
    Python の版や作り方が違って 1 つでも合わなければ、C_livery の解読には部品を使わない。
    """
    with _LOCK:
        cached = _STATE["math_ok"]
    if cached is not None:
        return bool(cached)
    rng = random.Random(20261120)
    angles = [0.0, -0.0, 1e-300, math.pi, -math.pi, math.pi / 2, -math.pi / 2, 1e-9, 3.0, -2.5]
    angles += [rng.uniform(-200.0, 200.0) for _ in range(160)]
    pairs = [(0.0, 1.0), (-0.0, 1.0), (0.0, -1.0), (-0.0, -1.0), (1.0, 0.0), (1.0, -0.0), (-1.0, -0.0),
             (1e-9, 3.0), (-2.0, -0.0), (3.0, 4.0), (0.0, 0.0)]
    pairs += [(rng.uniform(-3000.0, 3000.0), rng.uniform(-3000.0, 3000.0)) for _ in range(160)]
    pairs += [(rng.uniform(-1.0, 1.0) * 10 ** rng.uniform(-9.0, 5.0),
               rng.uniform(-1.0, 1.0) * 10 ** rng.uniform(-9.0, 5.0)) for _ in range(160)]
    pack = struct.Struct("<d").pack
    evaluate = lib.lo4_math_eval
    ok = all(pack(evaluate(0, x, 0.0)) == pack(math.cos(x)) and pack(evaluate(1, x, 0.0)) == pack(math.sin(x))
             and pack(evaluate(4, x, 0.0)) == pack(math.degrees(x) % 360.0) for x in angles)
    ok = ok and all(pack(evaluate(2, y, x)) == pack(math.atan2(y, x)) and pack(evaluate(3, y, x)) == pack(math.hypot(y, x))
                    for y, x in pairs)
    with _LOCK:
        _STATE["math_ok"] = ok
    return ok


def decode_livery_layers(body: bytes, counts, turns: bytes) -> tuple[bytes, tuple[int, ...]] | None:
    """C_livery の描画本体を、図形ごとの値（LIVERY_RECORD の並び）と覆いの文脈の件数 7 つにする。

    fh_livery_preview_core.native_canonical_layers の速い道から使う。部品が使えない・数の関数が合わない・
    部品が扱わない入力のときは None（呼び出し側は今までの Python の処理で解読する）。
    """
    lib = library()
    if lib is None or not _math_matches(lib):
        return None
    counts = tuple(int(value) for value in counts)
    if len(counts) != 11 or len(turns) != 11 or any(value < 0 or value > 0xFFFFFFFF for value in counts):
        return None
    total = sum(counts)
    out = ctypes.create_string_buffer(max(total, 1) * LIVERY_RECORD.size)
    evidence = (ctypes.c_uint64 * 7)()
    code = lib.lo4_decode_livery_layers(bytes(body), len(body), (ctypes.c_uint32 * 11)(*counts), bytes(turns),
                                        total, out, evidence)
    if code != 0:
        return None
    return out.raw[:total * LIVERY_RECORD.size], tuple(int(value) for value in evidence)
