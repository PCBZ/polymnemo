# Vendored from PCBZ/rsp examples/gitleaks-py at v0.1.1 (Apache-2.0).
# Unmodified apart from this header. See README.md in this directory.
"""Wraps the gitleaks binary, through its `stdin` command and its report.

Everything here is bytes. A Python `str` is indexed by code point, so
`content[start:end]` with the byte offsets S1 requires returns the wrong text
for any content that is not ASCII — quietly, with no exception and nothing
truncated. Go gets this right by construction, Rust panics, TypeScript
truncates; this is the one that would publish a secret and report success.
"""

from __future__ import annotations

import json
import os
import subprocess

FOUND = 2
"""Separates "found something" from gitleaks failing, which shares 1."""


def binary() -> str:
    return os.environ.get("RSP_GITLEAKS") or "gitleaks"


def run(args: list[str], content: bytes) -> tuple[str, int]:
    """Runs the binary once, returning what it wrote and how it exited.

    The status is why this exists: a gitleaks that could not run prints
    nothing, exactly like a clean chunk, so ignoring it would turn every
    failure into an ALLOW (E1, D3).
    """
    done = subprocess.run([binary(), *args], input=content, capture_output=True, check=False)
    if done.returncode not in (0, FOUND):
        raise RuntimeError(f"gitleaks exited with {done.returncode}")
    return done.stdout.decode("utf-8").strip(), done.returncode


def version() -> str:
    """Carried in the declaration so a cache key includes it (D4)."""
    return run(["version"], b"")[0]


def scan(content: bytes) -> list[dict]:
    """The findings for one chunk."""
    # "-" is gitleaks' own spelling of stdout; /dev/stdout fails its
    # writability pre-check. --no-banner keeps stdout to the report alone.
    report, status = run(
        [
            "stdin",
            "--no-banner",
            "--report-format",
            "json",
            "--report-path",
            "-",
            "--exit-code",
            "2",
        ],
        content,
    )
    # Exit 0 with nothing written is a clean chunk. Exit 2 is gitleaks saying
    # it found something, so nothing written is a report that went missing,
    # and reading it as no findings is the ALLOW E1 exists to refuse.
    if status == FOUND and not report:
        raise RuntimeError("gitleaks reported findings and wrote no report")
    if not report:
        return []
    findings = json.loads(report)
    if not isinstance(findings, list):
        raise TypeError("gitleaks wrote a report that is not a list of findings")
    return findings


def to_spans(findings: list[dict], content: bytes) -> list[dict]:
    """Converts gitleaks' positions into byte offsets.

    Its columns count from the newline byte ending the previous line, not from
    the line's first byte, so only line one matches the 1-based column anyone
    assumes. EndColumn belongs to EndLine, which differs whenever a finding
    spans lines. Anything that does not slice Match back out is dropped, and
    the caller turns a dropped finding into a BLOCK.
    """
    origins = column_origins(content)
    spans = []
    for finding in findings:
        first = origin(origins, finding.get("StartLine", 0))
        last = origin(origins, finding.get("EndLine", 0))
        if first is None or last is None:
            continue
        start = first + finding.get("StartColumn", 0) - 1
        end = last + finding.get("EndColumn", 0)
        # What S3 will check, checked here: an adapter should not hand the host
        # a span it is going to reject.
        if not usable(start, end, content):
            continue
        if content[start:end] != finding.get("Match", "").encode("utf-8"):
            continue
        spans.append({"start": start, "end": end, "type": finding.get("RuleID", "")})
    return spans


def usable(start: int, end: int, content: bytes) -> bool:
    """In range, non-empty, and on a character boundary at both ends."""
    if start < 0 or end > len(content) or end <= start:
        return False
    # A continuation byte is 0b10xxxxxx; a boundary is anything else.
    return all(at in (0, len(content)) or content[at] & 0xC0 != 0x80 for at in (start, end))


def origin(origins: list[int], line: int) -> int | None:
    """The byte gitleaks counts this line's columns from."""
    if line == 1:
        return 0
    if line < 1 or line > len(origins):
        return None
    return origins[line - 1] - 1


def column_origins(content: bytes) -> list[int]:
    """Where each line begins."""
    starts = [0]
    starts.extend(at + 1 for at, byte in enumerate(content) if byte == 0x0A)
    return starts
