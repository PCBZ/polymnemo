"""The two shipped scanners (#163), driven through the real RSP runtime.

The gitleaks binary lives in the image, not here, so that plugin runs against
`fake_gitleaks.py`, which speaks its CLI and report format. What is being
tested is the contract between us and it — exit codes, and columns counted the
way gitleaks counts them — not gitleaks' own rules.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from polymnemo.context import build_context
from polymnemo.guard import GuardBlocked, Verdict
from polymnemo.guard.rsp_guard import RSPGuard
from polymnemo.service import MemoryService

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CMD = ["-m", "polymnemo.plugins.tokens"]
GITLEAKS_CMD = [str(ROOT / "plugins" / "gitleaks" / "main.py")]
STUB = Path(__file__).parent / "fake_gitleaks.py"
FIXTURE = Path(__file__).parent / "fixtures" / "gitleaks-offsets.json"
CASES = json.loads(FIXTURE.read_text())["tests"]
REPLACEMENT = "[REDACTED:secret]"


def _redacted(content: str, spans: list[dict]) -> str:
    """Apply the recorded byte spans the way the host does (S4)."""
    raw = content.encode("utf-8")
    out, at = b"", 0
    for span in sorted(spans, key=lambda s: s["start"]):
        out += raw[at : span["start"]] + REPLACEMENT.encode("utf-8")
        at = span["end"]
    return (out + raw[at:]).decode("utf-8")


# A real-shaped polymnemo token: pmn_ + 43 urlsafe characters.
TOKEN = "pmn_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"
# Case 1 of the recorded fixture: one key, one span, on line one.
CASE_ONE = "deploy with AKIALALEMEL33243OLIB today"


def _config(tmp_path: Path, *plugins: tuple[str, list[str]]) -> Path:
    path = tmp_path / "rsp.toml"
    path.write_text(
        "".join(
            f'[[plugins]]\nname = "{name}"\n'
            f"command = {json.dumps([sys.executable, *args])}\n\n"
            for name, args in plugins
        )
    )
    return path


@pytest.fixture
def tokens_guard(tmp_path):
    return RSPGuard(_config(tmp_path, ("polymnemo-tokens", TOKENS_CMD)))


@pytest.fixture
def gitleaks_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("RSP_GITLEAKS", str(STUB))
    return RSPGuard(_config(tmp_path, ("gitleaks", GITLEAKS_CMD)))


class TestOurOwnTokens:
    """The credential no off-the-shelf scanner knows, and the most directly
    exploitable one a memory can carry: the default namespace is world-readable,
    so a pasted token authenticates anyone who recalls it."""

    def test_a_token_blocks_the_write(self, tokens_guard):
        outcome = tokens_guard.inspect([f"my key is {TOKEN} keep it safe"])
        assert outcome.verdict is Verdict.BLOCK
        assert outcome.chunks == []

    def test_blocked_rather_than_redacted(self, tokens_guard):
        """A redaction would store the memory and say nothing, leaving a live
        token in the author's hands. A refusal makes them go and revoke it."""
        assert tokens_guard.inspect([TOKEN]).verdict is Verdict.BLOCK

    @pytest.mark.parametrize(
        "text",
        [
            "I prefer dark roast coffee and I live in Vancouver",
            "the quarterly report showed 23% growth",
            "pmn_ is the prefix we use for tokens",  # prefix without a token
            "我喜欢深烘咖啡",
        ],
    )
    def test_ordinary_text_passes(self, tokens_guard, text):
        """The bar detect-secrets failed: prose must not trip the scanner, or
        the product stops working."""
        assert tokens_guard.inspect([text]).verdict is Verdict.ALLOW


class TestGitleaksAgainstRecordedCases:
    """Driven by tests/fixtures/gitleaks-offsets.json, transcribed from what
    gitleaks 8.30.1 actually emitted. The adapter's job is to turn those
    line/column positions into byte offsets, and the cases carry both sides --
    so a wrong formula here cannot agree with itself the way invented numbers
    would."""

    @pytest.mark.parametrize("case", CASES, ids=[c["comment"][:40] for c in CASES])
    def test_the_adapter_produces_the_recorded_spans(self, case, tmp_path, monkeypatch):
        monkeypatch.setenv("RSP_GITLEAKS", str(STUB))
        monkeypatch.setenv("FAKE_GITLEAKS_CASE", str(case["tcId"]))
        guard = RSPGuard(_config(tmp_path, ("gitleaks", GITLEAKS_CMD)))
        outcome = guard.inspect([case["content"]])

        findings, spans = case["findings"], case["spans"]
        if not findings:
            assert outcome.verdict is Verdict.ALLOW
            assert outcome.chunks == [case["content"]]
        elif len(spans) == len(findings):
            # Every finding placed: redact, and the replacement lands exactly
            # on the recorded byte ranges.
            assert outcome.verdict is Verdict.REDACT
            assert outcome.chunks[0] == _redacted(case["content"], spans)
        else:
            # A finding the adapter could not place is a secret it cannot
            # point at, so redacting the rest would leave it in the chunk.
            assert outcome.verdict is Verdict.BLOCK
            assert outcome.chunks == []

    def test_clean_text_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RSP_GITLEAKS", str(STUB))
        guard = RSPGuard(_config(tmp_path, ("gitleaks", GITLEAKS_CMD)))
        assert guard.inspect(["nothing secret here"]).verdict is Verdict.ALLOW

    def test_a_broken_binary_blocks_rather_than_allows(self, tmp_path, monkeypatch):
        """A gitleaks that cannot run prints nothing, exactly like a clean
        chunk. Reading that as ALLOW is the failure this design refuses."""
        monkeypatch.setenv("RSP_GITLEAKS", str(STUB))
        monkeypatch.setenv("FAKE_GITLEAKS_MODE", "fail")
        guard = RSPGuard(_config(tmp_path, ("gitleaks", GITLEAKS_CMD)))
        assert guard.inspect(["anything"]).verdict is Verdict.BLOCK


class TestBothTogether:
    def test_each_catches_what_the_other_misses(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RSP_GITLEAKS", str(STUB))
        guard = RSPGuard(
            _config(
                tmp_path, ("polymnemo-tokens", TOKENS_CMD), ("gitleaks", GITLEAKS_CMD)
            )
        )
        # Our plugin does not know an AWS key; gitleaks does not know ours.
        assert guard.inspect([f"token {TOKEN}"]).verdict is Verdict.BLOCK
        monkeypatch.setenv("FAKE_GITLEAKS_CASE", "1")
        assert guard.inspect([CASE_ONE]).verdict is Verdict.REDACT
        monkeypatch.delenv("FAKE_GITLEAKS_CASE")
        assert guard.inspect(["an ordinary memory"]).verdict is Verdict.ALLOW


class TestThroughTheService:
    def test_a_token_never_reaches_the_store(self, tokens_guard):
        service = MemoryService(replace(build_context(), guard=tokens_guard))
        with pytest.raises(GuardBlocked):
            service.remember("alice", f"my polymnemo key is {TOKEN}")
        assert service.list_memories("alice")["total"] == 0

    def test_a_redacted_credential_is_what_gets_stored(
        self, gitleaks_guard, monkeypatch
    ):
        monkeypatch.setenv("FAKE_GITLEAKS_CASE", "1")
        service = MemoryService(replace(build_context(), guard=gitleaks_guard))
        result = service.remember("alice", CASE_ONE)
        stored = service.get_memory("alice", result["ids"][0])["content"]
        assert "AKIALALEMEL33243OLIB" not in stored
        assert REPLACEMENT in stored
