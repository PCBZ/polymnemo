#!/usr/bin/env python3
# Vendored from PCBZ/rsp examples/gitleaks-py at v0.1.1 (Apache-2.0).
# Unmodified apart from this header. See README.md in this directory.
"""One JSON object in, one out, then exit (T1).

Diagnostics go to stderr: a stray line on stdout is indistinguishable from a
response (T2).
"""

from __future__ import annotations

import json
import sys

import strictjson
from protocol import respond


def main() -> None:
    # The wire is UTF-8 (M1), whatever locale the host was started in.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        json.dump(respond(strictjson.loads(sys.stdin.read())), sys.stdout)
    except Exception as exc:
        print(f"rsp-gitleaks-py: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
