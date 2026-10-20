#!/usr/bin/env python3
"""An RSP plugin for polymnemo's own API tokens.

No off-the-shelf scanner knows this format, because we invented it, and it is
the most directly exploitable credential a memory can contain: the default
namespace is `shared`, so a token pasted into a memory is readable by every
other user, and it authenticates as the person who pasted it.

BLOCK rather than REDACT. A redaction would store the memory and say nothing,
leaving a live token in the author's clipboard and their account open. A
refusal is the only outcome that makes them go and revoke it.

Self-contained and dependency-free: a plugin is a command, spawned per call.
"""

from __future__ import annotations

import json
import re
import sys

import strictjson

# `pmn_` + secrets.token_urlsafe(32), which is 43 urlsafe-base64 characters.
# The lower bound is loose so a future token length still matches; the prefix
# is what makes a false positive essentially impossible in prose.
TOKEN = re.compile(rb"pmn_[A-Za-z0-9_-]{20,}")


def declare() -> dict:
    return {
        "rsp_version": "0.1",
        "name": "polymnemo-tokens",
        "version": "1",
        "hooks": ["on_chunk", "on_retrieve"],
        # Same input, same answer: a regex over the content and nothing else.
        "deterministic": True,
    }


def respond(request: dict) -> dict:
    if request.get("hook") == "handshake":
        return declare()

    # Bytes, because RSP offsets are byte offsets into UTF-8 (S1). Indexing a
    # str would be by code point and would silently point at the wrong text in
    # any chunk that is not ASCII.
    content = request.get("content", "").encode("utf-8")
    hits = list(TOKEN.finditer(content))
    if not hits:
        return {"verdict": "ALLOW"}
    return {
        "verdict": "BLOCK",
        "reason": f"{len(hits)} polymnemo API token(s) in the content",
        "severity": "critical",
    }


def main() -> None:
    # The wire is UTF-8 (M1) whatever locale the host was started in.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        json.dump(respond(strictjson.loads(sys.stdin.read())), sys.stdout)
    except Exception as exc:
        # stderr: a stray line on stdout is indistinguishable from a response (T2).
        print(f"polymnemo-tokens: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
