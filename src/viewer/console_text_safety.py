from __future__ import annotations

import sys
from typing import Any


def configure_console_text_streams(*streams: Any) -> None:
    """Keep Windows console/pipe text output fail-soft for Unicode diagnostics.

    Windows PowerShell can expose a CP932-backed stdout/stderr when native
    process output is piped (for example through Select-String), even when an
    interactive console is configured for UTF-8.  Preserve the active encoding
    so representable Japanese text keeps its normal behavior, but replace only
    characters that the stream cannot encode instead of aborting preparation.
    """

    targets = streams or (sys.stdout, sys.stderr)
    for stream in targets:
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, TypeError, ValueError):
            # StringIO/custom GUI streams may not permit reconfiguration.
            continue
