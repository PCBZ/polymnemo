# Vendored from PCBZ/rsp examples/gitleaks-py at v0.1.1 (Apache-2.0).
# Unmodified apart from this header. See README.md in this directory.
"""The shape SPEC.md requires, in one file.

Kept apart from the adapter for whoever ports this again.
"""

from __future__ import annotations

from gitleaks import scan, to_spans, version

REPLACEMENT = "[REDACTED:secret]"


def declare() -> dict:
    """What this plugin says it is (H2).

    The version carries the binary's: for a wrapper it is the tool that decides
    verdicts, and the cache is keyed on this string (D4).
    """
    return {
        "rsp_version": "0.1",
        "name": "rsp-gitleaks-py",
        "version": f"0.1.0+{version()}",
        "hooks": ["on_chunk", "on_retrieve"],
        "deterministic": True,
    }


def respond(request: dict) -> dict:
    """Unrecognized request fields are ignored, never an error (D8)."""
    if request.get("hook") == "handshake":
        return declare()

    # Encoded once, here: every offset below indexes these bytes, and a str
    # would be indexed by code point.
    content = request.get("content", "").encode("utf-8")
    findings = scan(content)
    # ALLOW carries nothing else: the common case is the cheap one (V2).
    if not findings:
        return {"verdict": "ALLOW"}

    spans = to_spans(findings, content)
    # A finding with no span is a secret we cannot point at; redacting the rest
    # would leave it in the chunk (V4).
    if len(spans) != len(findings):
        return {
            "verdict": "BLOCK",
            "reason": "gitleaks reported a finding whose position could not be confirmed",
            "severity": "critical",
        }
    return {
        "verdict": "REDACT",
        "spans": spans,
        "replacement": REPLACEMENT,
        "severity": "critical",
    }
