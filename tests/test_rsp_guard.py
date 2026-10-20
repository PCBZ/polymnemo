"""The RSP-backed guard (#158) — against the real runtime and real subprocesses.

Mocking the runtime would test the adapter against my reading of the protocol
rather than against the protocol, and the properties that matter here are the
ones RSP specifies rather than the ones we implement: a crashed plugin must
block, a malformed reply must block, and a bad config must fail at startup.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from rsp.runtime import ConfigError

from polymnemo.config import settings
from polymnemo.context import build_context
from polymnemo.guard import GuardBlocked, NoOpGuard, Verdict
from polymnemo.guard.rsp_guard import RSPGuard
from polymnemo.service import MemoryService

PLUGIN = Path(__file__).parent / "rsp_fake_plugin.py"
MARKER = "AKIAFAKESECRETVALUE1"


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "rsp.toml"
    path.write_text(
        f'[[plugins]]\nname = "fake"\ncommand = ["{sys.executable}", "{PLUGIN}"]\n'
    )
    return path


@pytest.fixture
def mode(monkeypatch):
    def _set(value: str) -> None:
        monkeypatch.setenv("RSP_FAKE_MODE", value)

    return _set


class TestVerdictsHaveNotDrifted:
    """base.Verdict is defined independently so the seam carries no RSP
    dependency (#161). This is the check that keeps the two in agreement."""

    def test_the_names_match_rsp(self):
        from rsp.runtime import Verdict as RSPVerdict

        assert {v.value for v in Verdict} == {v.value for v in RSPVerdict}

    def test_construction_rejects_drift(self, config, mode, monkeypatch):
        """Proves the guard checks rather than assumes — without it, a renamed
        verdict would map to nothing and a BLOCK would silently weaken."""
        import rsp.runtime

        mode("allow")

        class Narrowed:
            ALLOW = type("V", (), {"value": "ALLOW"})()

            def __iter__(self):
                return iter([self.ALLOW])

        monkeypatch.setattr(rsp.runtime, "Verdict", Narrowed())
        with pytest.raises(RuntimeError, match="drifted"):
            RSPGuard(config)


class TestVerdicts:
    def test_allow_passes_chunks_through(self, config, mode):
        mode("allow")
        outcome = RSPGuard(config).inspect(["harmless one", "harmless two"])
        assert outcome.verdict is Verdict.ALLOW
        assert outcome.chunks == ["harmless one", "harmless two"]

    def test_block_returns_no_chunks(self, config, mode):
        """Empty, not partial: on a BLOCK the RSP result carries the ORIGINAL
        text, so handing it back would offer the caller what was just refused."""
        mode("block")
        outcome = RSPGuard(config).inspect(["fine", f"key: {MARKER}"])
        assert outcome.verdict is Verdict.BLOCK
        assert outcome.chunks == []

    def test_redact_replaces_the_span(self, config, mode):
        mode("redact")
        outcome = RSPGuard(config).inspect([f"key: {MARKER} tail"])
        assert outcome.verdict is Verdict.REDACT
        assert outcome.chunks == ["key: [REDACTED] tail"]
        assert MARKER not in outcome.chunks[0]

    def test_one_blocked_chunk_blocks_the_write(self, config, mode):
        mode("block")
        outcome = RSPGuard(config).inspect(["clean", f"{MARKER}", "also clean"])
        assert outcome.verdict is Verdict.BLOCK

    def test_a_block_stops_the_remaining_spawns(
        self, config, mode, monkeypatch, tmp_path
    ):
        """Each chunk costs two process spawns, so continuing past a decision
        already made is waste."""
        counter = tmp_path / "calls"
        monkeypatch.setenv("RSP_FAKE_COUNTER", str(counter))
        mode("block")
        RSPGuard(config).inspect([f"{MARKER}", "clean", "clean", "clean"])
        assert counter.read_text() == "x", "evaluated chunks after the block"


class TestFailClosed:
    """RSP E1/E2: evaluate never raises, and every failure becomes BLOCK. A
    scanner that fails open is worse than no scanner, because it reports success."""

    def test_a_crashed_plugin_blocks(self, config, mode):
        mode("crash")
        assert RSPGuard(config).inspect(["anything"]).verdict is Verdict.BLOCK

    def test_a_malformed_reply_blocks(self, config, mode):
        mode("garbage")
        assert RSPGuard(config).inspect(["anything"]).verdict is Verdict.BLOCK


class TestConfigFailsAtStartup:
    def test_a_missing_config_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            RSPGuard(tmp_path / "absent.toml")

    def test_a_plugin_that_cannot_run_raises(self, tmp_path):
        """Not at the first write, which is the whole point: a deploy should
        fail on a broken scanner rather than serve with one."""
        path = tmp_path / "rsp.toml"
        path.write_text('[[plugins]]\nname = "nope"\ncommand = ["/nonexistent/x"]\n')
        with pytest.raises(ConfigError, match="UNSPAWNABLE"):
            RSPGuard(path)


class TestThroughTheService:
    def test_remember_stores_nothing_when_blocked(self, config, mode):
        mode("block")
        ctx = replace(build_context(), guard=RSPGuard(config))
        service = MemoryService(ctx)
        with pytest.raises(GuardBlocked):
            service.remember("alice", f"deploy key: {MARKER}")
        assert service.list_memories("alice")["total"] == 0

    def test_remember_stores_the_redacted_text(self, config, mode):
        mode("redact")
        ctx = replace(build_context(), guard=RSPGuard(config))
        service = MemoryService(ctx)
        result = service.remember("alice", f"deploy key: {MARKER}")
        stored = service.get_memory("alice", result["ids"][0])["content"]
        assert MARKER not in stored
        assert "[REDACTED]" in stored


class TestTheContextWiresItUp:
    """Everything above constructs RSPGuard directly. This is the path
    production takes, and nothing else covers it: a wrong settings attribute or
    a changed constructor signature would pass every other test here."""

    def test_setting_the_config_selects_the_rsp_guard(self, config, mode, monkeypatch):
        mode("allow")
        monkeypatch.setattr(settings, "rsp_config", str(config))
        ctx = build_context()
        assert isinstance(ctx.guard, RSPGuard)
        assert ctx.describe()["guard"] == "RSPGuard"

    def test_an_unset_config_leaves_the_no_op(self, monkeypatch):
        monkeypatch.setattr(settings, "rsp_config", "")
        assert isinstance(build_context().guard, NoOpGuard)

    def test_a_broken_config_fails_at_startup_not_at_the_first_write(
        self, tmp_path, monkeypatch
    ):
        """build_context runs on import, so this is a deploy that does not come
        up rather than a service that serves with a dead scanner."""
        bad = tmp_path / "rsp.toml"
        bad.write_text('[[plugins]]\nname = "nope"\ncommand = ["/nonexistent/x"]\n')
        monkeypatch.setattr(settings, "rsp_config", str(bad))
        with pytest.raises(ConfigError):
            build_context()
