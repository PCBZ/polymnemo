"""RSP-backed guard (#158) — scans each chunk through configured plugins.

Only imported when `POLYMNEMO_RSP_CONFIG` names a config file, so a deployment
without one pays nothing: not the import, not the handshakes, not the install
(`rsp` is an opt-in extra).

One plugin invocation is one subprocess, and the plugin may spawn a detector of
its own, so the cost per chunk is two process spawns. That is the number #158
exists to measure.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .base import Guard, GuardOutcome, Verdict

HOOK = "on_chunk"

# BLOCK outranks REDACT outranks FLAG. Ordered so a strong verdict on one chunk
# cannot be softened by a weaker one on another.
_RANK = {Verdict.ALLOW: 0, Verdict.FLAG: 1, Verdict.REDACT: 2, Verdict.BLOCK: 3}


class RSPGuard(Guard):
    def __init__(self, config_path: str | Path) -> None:
        from rsp.config import load
        from rsp.runtime import Runtime
        from rsp.runtime import Verdict as RSPVerdict

        # `base.Verdict` is defined independently so the seam carries no RSP
        # dependency (#161). That allows drift: a renamed or added verdict would
        # map to nothing while this kept compiling, and a BLOCK would quietly
        # become something weaker. This is the only module importing both, so
        # the check belongs here -- and at startup, not at the first write.
        ours = {v.value for v in Verdict}
        theirs = {v.value for v in RSPVerdict}
        if ours != theirs:
            raise RuntimeError(
                "RSP verdicts have drifted from polymnemo's: "
                f"{sorted(theirs ^ ours)}. Reconcile polymnemo.guard.base.Verdict "
                "before deploying."
            )

        # Handshakes every plugin and raises on a bad one, so a broken config
        # fails the deploy instead of the first write.
        self._runtime = Runtime(load(config_path))

    def inspect(self, chunks: Sequence[str]) -> GuardOutcome:
        kept: list[str] = []
        reasons: list[str] = []
        worst = Verdict.ALLOW

        for chunk in chunks:
            result = self._runtime.evaluate(HOOK, chunk)
            verdict = Verdict(result.verdict.value)
            reasons.extend(result.reasons)
            if verdict is Verdict.BLOCK:
                # Stop here: the write is refused whole (#157), so the
                # remaining chunks would be spawns spent on a decision already
                # made. `chunks` comes back EMPTY rather than partial because
                # on a BLOCK `result.content` is the original, unredacted text
                # -- handing it back would offer a caller the very thing the
                # guard refused.
                return GuardOutcome(verdict=Verdict.BLOCK, chunks=[], reasons=reasons)
            if _RANK[verdict] > _RANK[worst]:
                worst = verdict
            kept.append(result.content)

        return GuardOutcome(verdict=worst, chunks=kept, reasons=reasons)
