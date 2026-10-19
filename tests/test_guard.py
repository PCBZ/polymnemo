"""The guard seam (#157) — what must be true before a scanner goes behind it.

The property worth protecting is narrow: when the guard refuses a write, the
content reaches neither the embedder nor the store. A guard that runs after
either one has not blocked anything, because the text is recoverable from the
embedding.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from polymnemo.context import build_context
from polymnemo.guard import Guard, GuardBlocked, GuardOutcome, NoOpGuard, Verdict
from polymnemo.service import MemoryService

SECRET = "AKIA47CQZHT2MVPF3JXB"


class _FixedGuard(Guard):
    """Returns one verdict, and records what it was asked about."""

    def __init__(self, verdict: Verdict, chunks=None, reasons=None) -> None:
        self.verdict = verdict
        self._chunks = chunks
        self.reasons = reasons or []
        self.seen: list[list[str]] = []

    def inspect(self, chunks: list[str]) -> GuardOutcome:
        self.seen.append(list(chunks))
        return GuardOutcome(
            verdict=self.verdict,
            chunks=list(self._chunks if self._chunks is not None else chunks),
            reasons=list(self.reasons),
        )


class _SpyEmbedder:
    """Wraps the real stub embedder to record what it was handed."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.dim = inner.dim
        self.documents: list[str] = []

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return self._inner.embed_documents(texts)

    def embed_query(self, text):
        return self._inner.embed_query(text)


def _service(guard: Guard) -> tuple[MemoryService, _SpyEmbedder]:
    from tests.conftest import FakeBlobStore

    base = build_context()
    spy = _SpyEmbedder(base.embedder)
    ctx = replace(base, guard=guard, embedder=spy, blob_store=FakeBlobStore())
    return MemoryService(ctx), spy


class TestTheDefaultChangesNothing:
    def test_the_default_guard_is_the_no_op(self):
        assert isinstance(build_context().guard, NoOpGuard)

    def test_it_is_named_in_describe(self):
        assert build_context().describe()["guard"] == "NoOpGuard"

    def test_allow_passes_the_chunks_through_untouched(self):
        chunks = ["one", "two"]
        outcome = NoOpGuard().inspect(chunks)
        assert outcome.verdict is Verdict.ALLOW
        assert outcome.chunks == chunks
        assert outcome.blocked is False


class TestBlockReachesNeitherEmbedderNorStore:
    """The whole point of the seam. A scanner that runs after the embedder has
    not prevented anything — the text comes back out of the vector."""

    def test_remember_is_refused(self):
        service, spy = _service(_FixedGuard(Verdict.BLOCK))
        with pytest.raises(GuardBlocked):
            service.remember("alice", SECRET)
        assert spy.documents == [], "blocked content was embedded"
        assert service.list_memories("alice")["total"] == 0

    def test_save_session_is_refused(self):
        service, spy = _service(_FixedGuard(Verdict.BLOCK))
        with pytest.raises(GuardBlocked):
            service.save_session("alice", "s1", SECRET)
        assert spy.documents == [], "blocked content was embedded"

    def test_a_block_is_all_or_nothing(self):
        """One memory becomes several chunks; storing the unblocked ones would
        leave a silent hole in the middle of the text."""
        service, _ = _service(_FixedGuard(Verdict.BLOCK))
        with pytest.raises(GuardBlocked):
            service.remember("alice", "word " * 200)
        assert service.list_memories("alice")["total"] == 0

    def test_the_guard_sees_chunks_not_the_raw_content(self):
        guard = _FixedGuard(Verdict.ALLOW)
        service, _ = _service(guard)
        service.remember("alice", "word " * 200)
        assert len(guard.seen) == 1
        assert len(guard.seen[0]) > 1, "expected the split chunks, not one blob"


class TestRedactIsWhatGetsStored:
    def test_the_replacement_is_embedded_and_stored(self):
        guard = _FixedGuard(Verdict.REDACT, chunks=["[REDACTED]"])
        service, spy = _service(guard)
        result = service.remember("alice", SECRET)

        assert spy.documents == ["[REDACTED]"], "the original was embedded"
        stored = service.get_memory("alice", result["ids"][0])["content"]
        assert stored == "[REDACTED]"
        assert SECRET not in stored


class TestReasonsNeverEscape:
    """A reason is free text from the scanner and may quote what it matched.
    RSP's K1 counts an audit log as storage, so logging one would store the
    secret the guard just refused."""

    def test_the_error_does_not_quote_the_match(self):
        guard = _FixedGuard(Verdict.BLOCK, reasons=[f"aws-access-token: {SECRET}"])
        service, _ = _service(guard)
        with pytest.raises(GuardBlocked) as excinfo:
            service.remember("alice", SECRET)
        assert SECRET not in str(excinfo.value)

    def test_nothing_is_logged_that_quotes_the_match(self, caplog):
        guard = _FixedGuard(Verdict.BLOCK, reasons=[f"aws-access-token: {SECRET}"])
        service, _ = _service(guard)
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(GuardBlocked):
                service.remember("alice", SECRET)
        for record in caplog.records:
            assert SECRET not in record.getMessage()
