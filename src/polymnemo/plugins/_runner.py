"""The half of a plugin that never changes: stdin in, one JSON object out.

Modelled on `main.py` in the upstream examples. A plugin module supplies
`declare()` and `inspect()`; everything about the wire lives here.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable

from . import _strictjson


def run(declare: Callable[[], dict], inspect: Callable[[bytes], dict]) -> None:
    """One request, one response, then exit (T1)."""
    # Read and write bytes, decoding UTF-8 ourselves. The wire is UTF-8 (M1)
    # whatever locale the host was started in, and going through the buffers
    # states that rather than depending on `reconfigure` having taken.
    try:
        request = _strictjson.loads(sys.stdin.buffer.read().decode("utf-8"))
        if request.get("hook") == "handshake":
            response = declare()
        else:
            # Bytes, because RSP offsets are byte offsets into UTF-8 (S1).
            # A str is indexed by code point and would point at the wrong text
            # in any content that is not ASCII.
            response = inspect(request.get("content", "").encode("utf-8"))
        payload = json.dumps(response)
    except Exception as exc:
        # stderr: a stray line on stdout is indistinguishable from a response (T2).
        print(f"{declare().get('name', 'plugin')}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sys.stdout.buffer.write(payload.encode("utf-8") + b"\n")
