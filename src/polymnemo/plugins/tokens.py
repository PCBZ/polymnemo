"""An RSP plugin for polymnemo's own API tokens.

No off-the-shelf scanner knows this format, because we invented it, and it is
the most directly exploitable credential a memory can carry: the default
namespace is `shared`, so a token pasted into a memory is readable by every
other user, and it authenticates as the person who pasted it.

BLOCK rather than REDACT. A redaction would store the memory and say nothing,
leaving a live token in the author's hands and their account open. A refusal is
the only outcome that makes them go and revoke it.
"""

from __future__ import annotations

import re

from . import _runner

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


def inspect(content: bytes) -> dict:
    hits = list(TOKEN.finditer(content))
    if not hits:
        return {"verdict": "ALLOW"}
    return {
        "verdict": "BLOCK",
        "reason": f"{len(hits)} polymnemo API token(s) in the content",
        "severity": "critical",
    }


def main() -> None:
    _runner.run(declare, inspect)


if __name__ == "__main__":
    main()
