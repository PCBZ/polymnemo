"""Guard seam — inspect chunks after splitting, before anything stores them.

The fourth pluggable layer, beside Auth / Store / Retriever / Embedder. It sits
at the one point where refusing content means it was never written: after
chunking, before `embed_documents` and before the store. A scanner placed after
storage has already lost, because the text is recoverable from the embedding.

The default is `NoOpGuard`, so a deployment that configures nothing behaves
exactly as it did before this seam existed. The real implementation (RSP, #158)
goes behind this protocol without changing either call site.

Verdict names match RSP's deliberately (#156): an adapter should map them one
for one rather than translate, because a translation layer is where a BLOCK
quietly becomes something weaker.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class Verdict(enum.StrEnum):
    ALLOW = "ALLOW"
    FLAG = "FLAG"
    REDACT = "REDACT"
    BLOCK = "BLOCK"


class GuardBlocked(ValueError):
    """A write refused by the guard.

    A ValueError so it travels the path `tool_errors` already maps to an
    actionable ToolError, and a distinct type so a caller can tell a refusal
    from malformed input.
    """


@dataclass(frozen=True)
class GuardOutcome:
    """One decision about a whole write.

    `chunks` is what should be stored: already redacted, so no caller handles
    spans. `reasons` is free text from the scanner and MAY QUOTE THE CONTENT IT
    MATCHED — it is carried for a caller that has somewhere safe to put it, and
    this codebase has nowhere, so nothing logs or returns it. See the note in
    `service._guarded`.
    """

    verdict: Verdict
    chunks: list[str]
    reasons: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCK


@runtime_checkable
class Guard(Protocol):
    def inspect(self, chunks: list[str]) -> GuardOutcome:
        """Judge a whole write.

        The entire chunk list, not one chunk at a time: the caller needs a
        single decision about one `remember`, and a per-chunk interface would
        push the partial-write question into every implementation instead of
        settling it once.
        """
        ...
