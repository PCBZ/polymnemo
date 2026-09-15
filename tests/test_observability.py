"""Per-call structured logging (#93).

Two things the issue's acceptance actually asks for: one structured line per
call, and no sensitive data in it. Both are asserted against the emitted line
rather than the implementation, so a FastMCP upgrade that changes the private
hooks this subclasses turns CI red instead of quietly degrading the logs.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from polymnemo import observability
from polymnemo.observability import CallLogMiddleware

# Captured at import, before the autouse fixture below replaces the module
# attribute — otherwise the resolution tests would exercise the stub.
_REAL_USER_ID = observability._user_id


def _context(method: str = "tools/call", type_: str = "request"):
    """Stands in for a MiddlewareContext: the middleware reads these four."""
    message = (
        SimpleNamespace(uri="memory://shared")
        if method == "resources/read"
        else SimpleNamespace(name="remember")
    )
    return SimpleNamespace(type=type_, method=method, source="client", message=message)


async def _ok(context):
    return "result"


def _boom(exc: Exception):
    async def call_next(context):
        raise exc

    return call_next


def _lines(caplog) -> list[str]:
    return [r.message for r in caplog.records if r.name == observability.CALL_LOGGER]


@pytest.fixture
def middleware():
    return CallLogMiddleware(logger=logging.getLogger(observability.CALL_LOGGER))


@pytest.fixture(autouse=True)
def _anonymous(monkeypatch):
    """Default to an unauthenticated caller, so tests that care about user_id
    have to opt in and can't pass by accident."""
    monkeypatch.setattr(observability, "_user_id", lambda: None)


class TestOneLinePerCall:
    async def test_success_emits_exactly_one_line(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(), _ok)
        assert len(_lines(caplog)) == 1

    async def test_failure_emits_exactly_one_line(self, middleware, caplog):
        with caplog.at_level(logging.INFO), pytest.raises(ValueError):
            await middleware.on_message(_context(), _boom(ValueError("x")))
        assert len(_lines(caplog)) == 1

    async def test_the_start_half_is_dropped(self, middleware, caplog):
        """The parent logs a `*_start` line before the call; suppressing it is
        what gets this to one line."""
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(), _ok)
        assert not any("_start" in line for line in _lines(caplog))

    async def test_the_error_is_not_swallowed(self, middleware, caplog):
        """Logging a failure must not turn it into a success."""
        with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
            await middleware.on_message(_context(), _boom(RuntimeError("x")))


class TestFields:
    async def test_success_line_carries_method_and_duration(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(method="tools/call"), _ok)
        entry = json.loads(_lines(caplog)[0])
        assert entry["event"].endswith("_success")
        assert entry["method"] == "tools/call"
        assert isinstance(entry["duration_ms"], int | float)

    async def test_resource_reads_are_logged_too(self, middleware, caplog):
        """`memory://{namespace}` arrives as a resource read, not a tool call,
        and hits the same table — a tool-only hook would miss it."""
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(method="resources/read"), _ok)
        assert json.loads(_lines(caplog)[0])["method"] == "resources/read"

    async def test_user_id_is_included_when_authenticated(
        self, middleware, caplog, monkeypatch
    ):
        monkeypatch.setattr(observability, "_user_id", lambda: "github:4242")
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(), _ok)
        assert json.loads(_lines(caplog)[0])["user_id"] == "github:4242"

    async def test_user_id_is_absent_when_not_authenticated(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(method="initialize"), _ok)
        assert "user_id" not in json.loads(_lines(caplog)[0])

    async def test_text_mode_is_key_value_not_json(self, caplog):
        mw = CallLogMiddleware(
            logger=logging.getLogger(observability.CALL_LOGGER), structured=False
        )
        with caplog.at_level(logging.INFO):
            await mw.on_message(_context(), _ok)
        line = _lines(caplog)[0]
        assert "method=tools/call" in line
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


class TestNoSensitiveData:
    async def test_error_records_the_class_not_the_message(self, middleware, caplog):
        """`tool_errors` keeps domain ValueError messages intact and service
        validation echoes user input, so `str(error)` would log caller data."""
        secret = "alice@example.com wrote 'my bank pin is 4321'"
        with caplog.at_level(logging.INFO), pytest.raises(ValueError):
            await middleware.on_message(_context(), _boom(ValueError(secret)))
        line = _lines(caplog)[0]
        assert "4321" not in line
        assert "alice@example.com" not in line
        assert json.loads(line)["error"] == "ValueError"

    async def test_payloads_are_not_logged(self, middleware, caplog):
        """Payloads are off by default upstream; assert it, because turning them
        on would put memory contents in the logs. The tool *name* is logged on
        purpose — what must not appear is its arguments."""
        context = _context()
        context.message = SimpleNamespace(
            name="remember", arguments={"content": "my bank pin is 4321"}
        )
        with caplog.at_level(logging.INFO):
            await middleware.on_message(context, _ok)
        line = _lines(caplog)[0]
        assert "payload" not in json.loads(line)
        assert "4321" not in line
        assert "bank pin" not in line
        assert json.loads(line)["target"] == "remember"  # the name, not the args


class TestUserIdResolution:
    def test_auth_failure_yields_no_user_id(self, monkeypatch):
        """An AuthError means anonymous, not an error worth raising."""
        from polymnemo.auth import AuthError

        class _Failing:
            def authenticate(self, headers):
                raise AuthError("nope")

        monkeypatch.setattr(
            observability.app, "ctx", SimpleNamespace(auth=_Failing()), raising=False
        )
        assert _REAL_USER_ID() is None

    def test_unexpected_failure_does_not_propagate(self, monkeypatch):
        """Logging must never break the request it describes."""

        class _Exploding:
            def authenticate(self, headers):
                raise RuntimeError("context not built")

        monkeypatch.setattr(
            observability.app, "ctx", SimpleNamespace(auth=_Exploding()), raising=False
        )
        assert _REAL_USER_ID() is None


class TestConfigureLogging:
    """`basicConfig` is a no-op once root has a handler, and something else does
    install one before the entry point runs — so without `force=True` the format
    is silently ignored and every json line arrives with an
    `INFO:polymnemo.calls:` prefix in front of the object."""

    @pytest.fixture(autouse=True)
    def _restore_root(self):
        root = logging.getLogger()
        saved = list(root.handlers), root.level
        yield
        root.handlers, root.level = saved[0], saved[1]

    def _fmt(self) -> str | None:
        handler = logging.getLogger().handlers[0]
        return handler.formatter._fmt if handler.formatter else None

    def test_json_mode_emits_the_bare_record(self):
        logging.getLogger().addHandler(logging.StreamHandler())  # pre-existing
        observability.configure_logging(structured=True, level="INFO")
        assert self._fmt() == "%(message)s"

    def test_text_mode_keeps_the_readable_prefix(self):
        logging.getLogger().addHandler(logging.StreamHandler())
        observability.configure_logging(structured=False, level="INFO")
        assert self._fmt() == observability.TEXT_FORMAT

    def test_debug_stays_ours_and_does_not_unleash_third_parties(self):
        """Third-party loggers are NOTSET, so they inherit root — dropping root
        to DEBUG would turn on SQLAlchemy and uvicorn too."""
        observability.configure_logging(structured=True, level="DEBUG")
        assert logging.getLogger("polymnemo").level == logging.DEBUG
        assert logging.getLogger().level == logging.INFO

    def test_raising_the_level_quietens_libraries_that_inherit_root(self):
        """It's called LOG_LEVEL, not POLYMNEMO_OWN_LOG_LEVEL: WARNING should
        also stop the INFO chatter of libraries that never set their own level.

        Does not extend to uvicorn, which configures its own loggers after this
        runs — asserted by the test below so the boundary is on the record.
        """
        observability.configure_logging(structured=True, level="WARNING")
        assert logging.getLogger().level == logging.WARNING
        assert logging.getLogger("polymnemo").level == logging.WARNING
        # NOTSET, so it inherits root.
        inheritor = logging.getLogger("sqlalchemy.engine")
        assert inheritor.level == logging.NOTSET
        assert not inheritor.isEnabledFor(logging.INFO)

    def test_a_library_with_its_own_level_is_not_affected(self):
        """uvicorn's startup lines survive at ERROR. Recorded because the
        docstring would otherwise overclaim what this function reaches."""
        own = logging.getLogger("test_uvicorn_lookalike")
        own.setLevel(logging.INFO)
        try:
            observability.configure_logging(structured=True, level="ERROR")
            assert own.isEnabledFor(logging.INFO)
        finally:
            own.setLevel(logging.NOTSET)

    def test_the_call_log_survives_a_raised_level(self):
        """Upstream logs failures at ERROR and successes at INFO. If the call
        log followed `level`, WARNING would keep the errors and drop the
        successes — so error rate would read 100%, the numerator with no
        denominator."""
        observability.configure_logging(structured=True, level="WARNING")
        assert logging.getLogger("polymnemo").level == logging.WARNING
        assert logging.getLogger(observability.CALL_LOGGER).level == logging.INFO

    def test_an_unknown_level_falls_back_to_info(self):
        observability.configure_logging(structured=True, level="lourd")
        assert logging.getLogger("polymnemo").level == logging.INFO


class TestTarget:
    """`method` is only ever `tools/call`, so it can't answer "which tool?" —
    which is precisely what the issue's acceptance asks for."""

    async def test_tool_name_is_recorded(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(), _ok)
        assert json.loads(_lines(caplog)[0])["target"] == "remember"

    async def test_resource_uri_is_recorded(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(method="resources/read"), _ok)
        assert json.loads(_lines(caplog)[0])["target"] == "memory://shared"

    async def test_error_line_also_carries_the_target(self, middleware, caplog):
        with caplog.at_level(logging.INFO), pytest.raises(ValueError):
            await middleware.on_message(_context(), _boom(ValueError("x")))
        assert json.loads(_lines(caplog)[0])["target"] == "remember"

    async def test_absent_when_there_is_nothing_to_name(self, middleware, caplog):
        context = SimpleNamespace(
            type="request", method="initialize", source="client", message=None
        )
        with caplog.at_level(logging.INFO):
            await middleware.on_message(context, _ok)
        assert "target" not in json.loads(_lines(caplog)[0])
