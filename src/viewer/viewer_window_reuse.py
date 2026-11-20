"""Viewer の窓の使い回し（2026-11-19、利用者の承認「より高速化できる方で」）。

1 つの Viewer の窓を開いたままにし、次のペイントの起動は、その窓へ依頼を渡して終わる（窓は次のペイントに
切り替わる。切り替えは organizer_preview_bridge.launch_standalone_preview）。2 枚目以降は、Python の起動
（URI からはコンソール用と窓用の 2 回）・重い部品の読み込み（約 0.9 秒）・WebView2 の起動が要らない。

- 窓を開いた Viewer は 127.0.0.1 で受け付け、受付の情報（形式・プロセスの番号・ポート・合言葉・プログラムの版）を
  %LOCALAPPDATA%/Livery Organizer for FH6/PreviewBridge/viewer-host.json に書く（窓を閉じると消す）。
- 依頼を渡す側は、合言葉・同じプログラム（EXE なら EXE、ソースならブリッジのファイルの場所・大きさ・更新日時）・
  同じ作業フォルダーを確かめる。窓が無い・応答が無い・どれかが違う・依頼が窓の使い回しの対象でないときは、
  従来どおり自分で新しい窓を開く。
- 重い部品を読み込む前に依頼を渡せるよう、このモジュールは標準の部品と lo4fh6_desktop_suite.runtime だけを使う。
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

HOST_FILE = "viewer-host.json"
HOST_FORMAT = "lo4fh6.viewer-host.v1"
CONNECT_SECONDS = 1.5
REPLY_SECONDS = 3.0
MAX_MESSAGE = 65536
VIEWER_ROOT = Path(__file__).resolve().parent
BRIDGE_SCRIPT = VIEWER_ROOT / "organizer_preview_bridge.py"
# 重い部品を読み込む前の受け渡し（forward_early）で、渡さずに従来どおり起動する指定。
# ここで見落としても、受ける側が引数を読み直して確かめ、対象でなければ断る（渡す側が自分で開く）。
_NOT_FORWARDED_FLAGS = {
    "--prepare-only", "--no-open", "--remember-database", "--forget-database", "--show-database",
    "--register-uri-scheme", "--unregister-uri-scheme", "--wheel-morph-reference-helper", "-h", "--help",
}


def preview_bridge_root() -> Path:
    """Viewer のローカルのデータの場所（ログ・設定・Three.js・WebView2 の保存先と同じ親）。"""
    value = os.environ.get("LOCALAPPDATA", "").strip()
    if value:
        return Path(value) / "Livery Organizer for FH6" / "PreviewBridge"
    return Path.home() / "AppData" / "Local" / "Livery Organizer for FH6" / "PreviewBridge"


def host_path() -> Path:
    return preview_bridge_root() / HOST_FILE


def append_log(message: str) -> None:
    """ブリッジの記録（preview-bridge.log）へ 1 行足す（ブリッジの _append_bridge_log と同じ形）。"""
    try:
        path = preview_bridge_root() / "preview-bridge.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message.rstrip()}\n")
    except OSError:
        pass


def code_identity() -> str:
    """依頼を渡す側と受ける側が同じプログラムかを見分ける値。"""
    try:
        from lo4fh6_desktop_suite.runtime import is_packaged, packaged_executable
        target = Path(packaged_executable()).resolve() if is_packaged() else BRIDGE_SCRIPT.resolve()
        stat = target.stat()
    except (OSError, ImportError, RuntimeError):
        return ""
    return f"{target}|{stat.st_size}|{stat.st_mtime_ns}"


def process_alive(pid: int) -> bool:
    """そのプロセスが動いているか。確かめられないときは True（接続して確かめる）。"""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT＝まだ動いている
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def forward(argv: list[str], cwd: str, *, log: Callable[[str], None] = append_log) -> bool:
    """開いている窓へ依頼を渡せたら True。渡せなければ False（呼び出し側が従来どおり開く）。"""
    path = host_path()
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    identity = code_identity()
    if (not isinstance(info, dict) or info.get("format") != HOST_FORMAT
            or not identity or info.get("identity") != identity):
        return False
    try:
        port = int(info["port"])
        pid = int(info["pid"])
        token = str(info["token"])
    except (KeyError, TypeError, ValueError):
        return False
    if not process_alive(pid):
        # 窓が閉じずに終わった（強制終了など）ときの古い情報は消す。
        with contextlib.suppress(OSError):
            path.unlink()
        return False
    if sys.platform == "win32":
        # 依頼を渡した窓が前に出られるように、前に出す許可を渡す（この起動は利用者の操作から始まっている）。
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(pid)
    message = {"op": "open", "token": token, "cwd": cwd,
               "argv": [value for value in argv if value != "--gui-child"]}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_SECONDS) as connection:
            connection.settimeout(REPLY_SECONDS)
            connection.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            reply = b""
            while not reply.endswith(b"\n") and len(reply) <= MAX_MESSAGE:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                reply += chunk
        answer = json.loads(reply.decode("utf-8"))
    except (OSError, ValueError, UnicodeError):
        log("viewer host forward: no answer; opening a new window")
        return False
    ok = isinstance(answer, dict) and answer.get("ok") is True
    reason = "" if ok else f" reason={answer.get('error') if isinstance(answer, dict) else 'invalid'}"
    log(f"viewer host forward: ok={ok}{reason}")
    return ok


def forward_early(argv: list[str]) -> bool:
    """重い部品を読み込む前の受け渡し。Organizer からの URI の起動（--uri）だけを対象にする。"""
    values = list(argv)
    if "--uri" not in values or any(value in _NOT_FORWARDED_FLAGS for value in values):
        return False
    if any(value == "--window-mode" and index + 1 < len(values) and values[index + 1] != "standalone"
           for index, value in enumerate(values)) or any(value.startswith("--window-mode=") and
                                                         value != "--window-mode=standalone" for value in values):
        return False
    # URI からの起動は窓用の Python を VIEWER_ROOT で起動し直すので、依頼の相対パスは VIEWER_ROOT から読む。
    cwd = str(VIEWER_ROOT) if sys.platform == "win32" and "--gui-child" not in values else os.getcwd()
    return forward(values, cwd)


class ViewerHost:
    """開いている Viewer の窓の受付。別の起動から依頼を受け取り、accept に渡す（窓の切り替えは呼び出し側）。"""

    def __init__(self, accept: Callable[[list[str]], None], closed: threading.Event, *,
                 log: Callable[[str], None] = append_log) -> None:
        import secrets
        self._accept = accept
        self._closed = closed
        self._log = log
        self._stopped = threading.Event()
        self.token = secrets.token_urlsafe(32)
        self.cwd = os.getcwd()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._socket.bind(("127.0.0.1", 0))
            self._socket.listen(8)
            self._socket.settimeout(0.5)
        except OSError:
            self._socket.close()
            raise
        self.port = int(self._socket.getsockname()[1])
        threading.Thread(target=self._serve, name="lo4fh6-viewer-host", daemon=True).start()
        self._write_info()

    def _write_info(self) -> None:
        path = host_path()
        info = {"format": HOST_FORMAT, "pid": os.getpid(), "port": self.port,
                "token": self.token, "identity": code_identity()}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(info), encoding="utf-8")
        os.replace(temporary, path)

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                self._handle(connection)

    def _handle(self, connection: Any) -> None:
        connection.settimeout(3.0)
        data = b""
        try:
            while not data.endswith(b"\n") and len(data) <= MAX_MESSAGE:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                data += chunk
            message = json.loads(data.decode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            return
        reply = self.decide(message)
        with contextlib.suppress(OSError):
            connection.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))

    def decide(self, message: object) -> dict[str, Any]:
        import secrets
        if not isinstance(message, dict) or message.get("op") != "open":
            return {"ok": False, "error": "invalid"}
        if not secrets.compare_digest(str(message.get("token") or ""), self.token):
            return {"ok": False, "error": "token"}
        if self._closed.is_set() or self._stopped.is_set():
            return {"ok": False, "error": "closing"}
        argv = message.get("argv")
        if not isinstance(argv, list) or not all(isinstance(value, str) for value in argv):
            return {"ok": False, "error": "arguments"}
        try:
            same_folder = os.path.samefile(str(message.get("cwd") or ""), self.cwd)
        except OSError:
            same_folder = False
        if not same_folder:
            return {"ok": False, "error": "cwd"}
        try:
            self._accept(list(argv))
        except SystemExit:
            return {"ok": False, "error": "arguments"}
        except Exception as exc:  # noqa: BLE001  渡す側が従来どおり新しい窓で開き、そこで理由を出す
            self._log(f"viewer host: request refused: {type(exc).__name__}: {exc}")
            return {"ok": False, "error": type(exc).__name__}
        return {"ok": True}

    def close(self) -> None:
        self._stopped.set()
        with contextlib.suppress(OSError):
            self._socket.close()
        path = host_path()
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(info, dict) and info.get("token") == self.token:
            with contextlib.suppress(OSError):
                path.unlink()


# ---- 窓を閉じても、少しの間 Viewer を裏に残す（2026-11-20、FH6 に近づける案 ⑥）----
# 利用者が窓を閉じたら、閉じる代わりに窓を隠し、決めた時間（既定 10 分）は次の依頼を受け付ける。次に開くとき、
# 同じプロセスのメモリー（解読したペイント・準備の近道・材質の解析など）と、読み込んだページ（同じ車なら
# 差し替え）をそのまま使える。時間が来たら本当に閉じる。Windows の終了中・隠している窓を閉じるとき・時間が 0 の
# ときは、取り消さずにそのまま閉じる。
KEEP_ALIVE_SETTING = "viewer_keep_alive_seconds"
KEEP_ALIVE_DEFAULT_SECONDS = 600.0


def keep_alive_seconds(settings: object) -> float:
    """共有の設定の viewer_keep_alive_seconds（秒）。無い・読めない・負の数なら既定（10 分）。0 で残さない。"""
    value = settings.get(KEEP_ALIVE_SETTING) if isinstance(settings, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return KEEP_ALIVE_DEFAULT_SECONDS
    if value != value or value < 0:  # NaN・負の数
        return KEEP_ALIVE_DEFAULT_SECONDS
    return float(min(value, 24 * 3600))


def windows_shutting_down() -> bool:
    """Windows の終了・サインアウトの途中なら True（GetSystemMetrics の SM_SHUTTINGDOWN）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetSystemMetrics(0x2000))
    except (OSError, AttributeError):
        return False


class KeepAlive:
    """窓を閉じる操作を、決めた時間だけ「隠して残す」に替える。"""

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic,
                 shutting_down: Callable[[], bool] = windows_shutting_down,
                 log: Callable[[str], None] = append_log) -> None:
        self.seconds = max(0.0, float(seconds))
        self._clock = clock
        self._shutting_down = shutting_down
        self._log = log
        self._lock = threading.Lock()
        self.hidden_since: float | None = None
        self.final = False

    def on_closing(self, window: Any) -> bool | None:
        """pywebview の閉じる前の知らせ。False を返すと閉じない（窓を隠して残す）。"""
        with self._lock:
            if self.final or self.seconds <= 0 or self.hidden_since is not None or self._shutting_down():
                self.final = True
                return None
            self.hidden_since = self._clock()
        try:
            window.hide()
        except Exception as exc:  # noqa: BLE001  隠せなければ従来どおり閉じる
            with self._lock:
                self.final = True
                self.hidden_since = None
            self._log(f"viewer keep-alive: hide failed, closing: {type(exc).__name__}: {exc}")
            return None
        self._log(f"viewer hidden; kept alive for {self.seconds:.0f}s")
        return False

    def shown_for_job(self) -> None:
        """次の依頼で窓を出す前に呼ぶ（隠した状態を終える）。"""
        with self._lock:
            if self.hidden_since is not None:
                self._log("viewer shown again for the next request")
            self.hidden_since = None

    def expired(self) -> bool:
        with self._lock:
            return (not self.final and self.hidden_since is not None
                    and self._clock() - self.hidden_since >= self.seconds)

    def finish(self, window: Any) -> None:
        """隠して残す時間が過ぎたので、本当に閉じる。"""
        with self._lock:
            self.final = True
        self._log("viewer keep-alive expired; closing")
        with contextlib.suppress(Exception):
            window.destroy()
