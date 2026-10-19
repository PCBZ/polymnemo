"""The default guard: inspects nothing, allows everything.

Keeps the seam free when no scanner is configured — same behaviour, same cost.
"""

from __future__ import annotations

from .base import Guard, GuardOutcome, Verdict


class NoOpGuard(Guard):
    def inspect(self, chunks: list[str]) -> GuardOutcome:
        return GuardOutcome(verdict=Verdict.ALLOW, chunks=list(chunks))
