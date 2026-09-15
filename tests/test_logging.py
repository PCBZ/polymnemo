"""Logging setup and the per-call log line (#93).

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

from polymnemo import app
from polymnemo import logging as log_mod
from polymnemo.logging import CallLogMiddleware


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
    return [r.message for r in caplog.records if r.name == log_mod.CALL_LOGGER]


def _middleware(user_id=None, new_scope=None, **kw):
    """The resolver is injected, so a test says who the caller is rather than
    patching a private function. A stub resolver needs no real scope, so one is
    supplied to satisfy the pairing rule."""
    if user_id is not None and new_scope is None:
        new_scope = lambda: None  # noqa: E731
    return CallLogMiddleware(
        logger=logging.getLogger(log_mod.CALL_LOGGER),
        user_id=user_id,
        new_scope=new_scope,
        **kw,
    )


@pytest.fixture
def middleware():
    """Anonymous by default: tests that care about user_id must opt in."""
    return _middleware()


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

    async def test_user_id_is_included_when_authenticated(self, caplog):
        middleware = _middleware(user_id=lambda: "github:4242")
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(), _ok)
        assert json.loads(_lines(caplog)[0])["user_id"] == "github:4242"

    async def test_user_id_is_absent_when_not_authenticated(self, middleware, caplog):
        with caplog.at_level(logging.INFO):
            await middleware.on_message(_context(method="initialize"), _ok)
        assert "user_id" not in json.loads(_lines(caplog)[0])

    async def test_text_mode_is_key_value_not_json(self, caplog):
        mw = CallLogMiddleware(
            logger=logging.getLogger(log_mod.CALL_LOGGER), structured=False
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


class TestRequestScope:
    """Identity is recorded where authentication happens and read back by the
    log — so the log names the id the tool actually used, rather than deriving
    its own answer."""

    def test_authenticating_records_the_user(self, monkeypatch):
        from polymnemo import tooling

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=lambda h: "alice")),
            raising=False,
        )
        tooling.new_request_scope()
        assert tooling.current_user_id() is None
        assert tooling.current_user() == "alice"
        assert tooling.current_user_id() == "alice"

    def test_a_failed_authentication_records_nothing(self, monkeypatch):
        from fastmcp.exceptions import ToolError

        from polymnemo import tooling
        from polymnemo.auth import AuthError

        def _refuse(headers):
            raise AuthError("nope")

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=_refuse)),
            raising=False,
        )
        tooling.new_request_scope()
        with pytest.raises(ToolError):
            tooling.current_user()
        assert tooling.current_user_id() is None

    def test_reading_without_a_scope_is_not_an_error(self):
        """`initialize` and other unauthenticated calls never open one."""
        from polymnemo import tooling

        assert tooling.current_user_id() is None


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
        log_mod.configure_logging(structured=True, level="INFO")
        assert self._fmt() == "%(message)s"

    def test_text_mode_keeps_the_readable_prefix(self):
        logging.getLogger().addHandler(logging.StreamHandler())
        log_mod.configure_logging(structured=False, level="INFO")
        assert self._fmt() == log_mod.TEXT_FORMAT

    def test_debug_stays_ours_and_does_not_unleash_third_parties(self):
        """Third-party loggers are NOTSET, so they inherit root — dropping root
        to DEBUG would turn on SQLAlchemy and uvicorn too."""
        log_mod.configure_logging(structured=True, level="DEBUG")
        assert logging.getLogger("polymnemo").level == logging.DEBUG
        assert logging.getLogger().level == logging.INFO

    def test_raising_the_level_quietens_libraries_that_inherit_root(self):
        """It's called LOG_LEVEL, not POLYMNEMO_OWN_LOG_LEVEL: WARNING should
        also stop the INFO chatter of libraries that never set their own level.

        Does not extend to uvicorn, which configures its own loggers after this
        runs — asserted by the test below so the boundary is on the record.
        """
        log_mod.configure_logging(structured=True, level="WARNING")
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
            log_mod.configure_logging(structured=True, level="ERROR")
            assert own.isEnabledFor(logging.INFO)
        finally:
            own.setLevel(logging.NOTSET)

    def test_the_call_log_survives_a_raised_level(self):
        """Upstream logs failures at ERROR and successes at INFO. If the call
        log followed `level`, WARNING would keep the errors and drop the
        successes — so error rate would read 100%, the numerator with no
        denominator."""
        log_mod.configure_logging(structured=True, level="WARNING")
        assert logging.getLogger("polymnemo").level == logging.WARNING
        assert logging.getLogger(log_mod.CALL_LOGGER).level == logging.INFO

    def test_an_unknown_level_falls_back_to_info(self):
        log_mod.configure_logging(structured=True, level="lourd")
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


class TestAuthRejectionIsLogged:
    """`auth/` logged nothing at all before this. A 401 is raised at the
    transport layer, before middleware, so the call log cannot see it — #123
    shipped a bug that 401'd every bearer key and the logs were silent."""

    SECRET = "sk-super-secret-value"

    def _auth(self):
        from polymnemo.auth.bearer import BearerKeyAuth

        return BearerKeyAuth({"sk-alice": "alice"})

    def _reasons(self, caplog) -> list[str]:
        return [r.message for r in caplog.records if "auth rejected" in r.message]

    def test_unknown_key_is_logged(self, caplog):
        from polymnemo.auth import AuthError

        with caplog.at_level(logging.WARNING), pytest.raises(AuthError):
            self._auth().authenticate({"authorization": f"Bearer {self.SECRET}"})
        assert "unknown_key" in self._reasons(caplog)[0]

    def test_missing_header_is_logged(self, caplog):
        from polymnemo.auth import AuthError

        with caplog.at_level(logging.WARNING), pytest.raises(AuthError):
            self._auth().authenticate({})
        assert "missing_header" in self._reasons(caplog)[0]

    def test_malformed_header_is_logged(self, caplog):
        from polymnemo.auth import AuthError

        with caplog.at_level(logging.WARNING), pytest.raises(AuthError):
            self._auth().authenticate({"authorization": "Basic zzz"})
        assert "malformed_header" in self._reasons(caplog)[0]

    def test_the_token_never_reaches_the_log(self, caplog):
        """Not even a prefix: a partial credential in a log is still credential
        material, and logs travel further than the database does."""
        from polymnemo.auth import AuthError

        with caplog.at_level(logging.DEBUG), pytest.raises(AuthError):
            self._auth().authenticate({"authorization": f"Bearer {self.SECRET}"})
        everything = " ".join(r.message for r in caplog.records)
        assert self.SECRET not in everything
        for n in (4, 6, 8):
            assert self.SECRET[:n] not in everything

    def test_a_good_key_logs_no_rejection(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert self._auth().authenticate({"authorization": "Bearer sk-alice"})
        assert self._reasons(caplog) == []


class TestRateLimitIsLogged:
    def test_hitting_the_bucket_is_an_event(self, caplog):
        """In the call log this is a ToolError, indistinguishable from an
        argument-validation failure."""
        from polymnemo.ratelimit import GlobalRateLimiter, RateLimitError

        limiter = GlobalRateLimiter(per_min=1)
        limiter.check(1)
        with caplog.at_level(logging.WARNING), pytest.raises(RateLimitError):
            for _ in range(5):
                limiter.check(1)
        line = next(r.message for r in caplog.records if "rate limit hit" in r.message)
        assert "limit=1/min" in line


class TestLoggingDoesNotAuthenticate:
    """The call log used to re-run authentication to name the caller, which made
    an anonymous request emit a rejection warning about itself — and needed a
    module-level flag to suppress. Injection removes the cause."""

    async def test_an_anonymous_call_logs_no_rejection(
        self, middleware, caplog, monkeypatch
    ):
        from polymnemo.auth.bearer import BearerKeyAuth

        monkeypatch.setattr(
            app, "ctx", SimpleNamespace(auth=BearerKeyAuth({})), raising=False
        )
        with caplog.at_level(logging.DEBUG):
            await middleware.on_message(_context(), _ok)
        assert not [r for r in caplog.records if "auth rejected" in r.message]
        assert "user_id" not in json.loads(_lines(caplog)[0])

    def test_a_real_rejection_still_logs(self, caplog):
        from polymnemo.auth import AuthError
        from polymnemo.auth.bearer import BearerKeyAuth

        with caplog.at_level(logging.WARNING), pytest.raises(AuthError):
            BearerKeyAuth({}).authenticate({"authorization": "Bearer x"})
        assert [r for r in caplog.records if "auth rejected" in r.message]

    def test_the_module_holds_no_cross_request_state(self):
        """A module-level global would be shared by every concurrent request;
        the scope lives in a ContextVar instead. Asserted so a refactor back to
        a global is caught here rather than in production."""
        import inspect

        from polymnemo import tooling

        source = inspect.getsource(log_mod)
        assert "app.ctx" not in source, "the log must not reach into the context"
        assert "ContextVar" in inspect.getsource(tooling)


class TestConcurrentRequestsDoNotMix:
    """Many users authenticate at once. Each call line must name its own."""

    async def test_two_hundred_users_keep_their_own_identity(self):
        import asyncio

        from polymnemo import tooling

        seen: dict[str, str | None] = {}

        async def one_request(user: str):
            tooling.new_request_scope()
            await asyncio.sleep(0)  # let the scheduler interleave
            tooling._scope()["user_id"] = user
            await asyncio.sleep(0)
            seen[user] = tooling.current_user_id()

        users = [f"user{i}" for i in range(200)]
        await asyncio.gather(*(one_request(u) for u in users))
        wrong = {u: seen[u] for u in users if seen[u] != u}
        assert not wrong, f"cross-request contamination: {list(wrong.items())[:3]}"


class TestTheRealWiring:
    """The injected pieces, connected the way `main` connects them. Without
    this, every user_id test runs against a lambda and a broken wiring — a
    missing `new_scope`, say — would ship green."""

    def _middleware_wired_to_tooling(self):
        from polymnemo import tooling

        return _middleware(
            user_id=tooling.current_user_id, new_scope=tooling.new_request_scope
        )

    async def test_the_line_names_the_user_the_tool_authenticated_as(
        self, caplog, monkeypatch
    ):
        from polymnemo import tooling

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=lambda h: "alice")),
            raising=False,
        )

        async def tool_that_authenticates(context):
            tooling.current_user()  # what a real tool does
            return "ok"

        with caplog.at_level(logging.INFO):
            await self._middleware_wired_to_tooling().on_message(
                _context(), tool_that_authenticates
            )
        assert json.loads(_lines(caplog)[0])["user_id"] == "alice"

    async def test_a_tool_that_never_authenticates_has_no_user_id(
        self, caplog, monkeypatch
    ):
        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=lambda h: "alice")),
            raising=False,
        )
        with caplog.at_level(logging.INFO):
            await self._middleware_wired_to_tooling().on_message(_context(), _ok)
        assert "user_id" not in json.loads(_lines(caplog)[0])

    async def test_one_call_cannot_see_the_previous_call_s_user(
        self, caplog, monkeypatch
    ):
        """The scope must be reopened per call, not left over from the last."""
        from polymnemo import tooling

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=lambda h: "alice")),
            raising=False,
        )
        mw = self._middleware_wired_to_tooling()

        async def authenticates(context):
            tooling.current_user()
            return "ok"

        with caplog.at_level(logging.INFO):
            await mw.on_message(_context(), authenticates)
            await mw.on_message(_context(), _ok)  # this one does not authenticate
        first, second = (json.loads(line) for line in _lines(caplog)[:2])
        assert first["user_id"] == "alice"
        assert "user_id" not in second


class TestReviewFixes:
    """One per finding on #128, asserted at the seam each one broke."""

    @pytest.fixture(autouse=True)
    def _restore_loggers(self):
        """These call configure_logging for real. Without restoring, a level set
        here leaks into every later test in the session."""
        names = ("", "polymnemo", log_mod.CALL_LOGGER, log_mod.AUTH_LOGGER)
        saved = [(logging.getLogger(n), logging.getLogger(n).level) for n in names]
        root = logging.getLogger()
        handlers = list(root.handlers)
        yield
        for log, level in saved:
            log.setLevel(level)
        root.handlers = handlers

    def test_a_resolver_without_a_scope_is_refused(self):
        """Constructing with user_id but no new_scope used to succeed and then
        emit every line without user_id — no exception, no warning."""
        with pytest.raises(ValueError) as caught:
            CallLogMiddleware(
                logger=logging.getLogger(log_mod.CALL_LOGGER),
                user_id=lambda: "alice",
            )
        assert str(caught.value) == "pass both user_id and new_scope, or neither"

    def test_a_level_name_that_is_not_a_level_falls_back(self):
        """`getattr(logging, ...)` finds any attribute: BASIC_FORMAT is a str,
        and max() against it raised TypeError before a line was ever logged."""
        log_mod.configure_logging(structured=False, level="BASIC_FORMAT")
        assert logging.getLogger("polymnemo").level == logging.INFO

    def test_auth_rejections_survive_log_level_error(self):
        """A 401 never reaches the middleware, so this logger is its only
        record — LOG_LEVEL=ERROR must not be able to hide a stuffing run."""
        log_mod.configure_logging(structured=False, level="ERROR")
        assert logging.getLogger("polymnemo").level == logging.ERROR
        assert logging.getLogger(log_mod.AUTH_LOGGER).isEnabledFor(logging.WARNING)

    def test_lowering_the_level_still_reaches_the_auth_logger(self):
        log_mod.configure_logging(structured=False, level="DEBUG")
        assert logging.getLogger(log_mod.AUTH_LOGGER).isEnabledFor(logging.DEBUG)

    def test_an_empty_tool_name_is_reported_not_dropped(self):
        context = SimpleNamespace(
            type="request",
            method="tools/call",
            source="client",
            message=SimpleNamespace(name=""),
        )
        assert log_mod._target(context) == ""

    async def test_a_hung_call_still_leaves_a_trace(self, caplog, monkeypatch):
        """Dropping the `*_start` half means a call that never returns never
        reaches a completion line either — it was invisible."""
        import asyncio

        monkeypatch.setattr(log_mod, "SLOW_CALL_SECONDS", 0.01)
        mw = _middleware()

        async def never_returns(context):
            await asyncio.sleep(5)

        with caplog.at_level(logging.WARNING):
            task = asyncio.create_task(mw.on_message(_context(), never_returns))
            await asyncio.sleep(0.1)
            entry = json.loads(_lines(caplog)[0])
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task  # awaited, or pytest reports a destroyed pending task
        assert entry["event"] == "request_in_flight"
        assert entry["target"] == "remember"
        # Measured, not the threshold echoed back.
        assert entry["elapsed_ms"] >= 10
        assert entry["source"] == "client"

    async def test_a_normal_call_leaves_no_in_flight_line(self, caplog):
        with caplog.at_level(logging.WARNING):
            await _middleware().on_message(_context(), _ok)
        assert not [ln for ln in _lines(caplog) if "in_flight" in ln]


class TestTokenStoreAbsentIsSaidPlainly:
    async def test_no_database_is_not_reported_as_expired(self, caplog, monkeypatch):
        """With no store the token is never looked up, so calling it expired
        sends an operator hunting a revocation problem that doesn't exist."""
        from fastmcp.server.auth.providers.github import GitHubProvider

        from polymnemo.auth.oauth import GitHubOAuthProvider

        async def _no_oauth(self, token):
            return None

        monkeypatch.setattr(GitHubProvider, "verify_token", _no_oauth)
        provider = GitHubOAuthProvider(
            client_id="id", client_secret="secret", base_url="https://e.test"
        )
        with caplog.at_level(logging.WARNING):
            assert await provider.verify_token("pmn_whatever") is None
        line = next(r.message for r in caplog.records if "rejected" in r.message)
        assert "no_token_store" in line
        assert "expired" not in line


class TestScopeIsCreatedOnDemand:
    def test_authenticating_without_a_scope_still_records(self, monkeypatch):
        """`_REQUEST.get({})` handed back a throwaway dict, so the write was a
        no-op and the identity vanished — silently, for any path that reaches
        current_user without the middleware."""
        from polymnemo import tooling

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(auth=SimpleNamespace(authenticate=lambda h: "alice")),
            raising=False,
        )
        tooling._REQUEST.set(None)  # no middleware ran
        assert tooling.current_user() == "alice"
        assert tooling.current_user_id() == "alice"


class TestDegradationChecksSurviveSubclassing:
    def test_a_subclass_of_the_in_memory_store_still_warns(self, caplog, monkeypatch):
        """`type(x).__name__ == "InMemoryStore"` passed silently for a subclass
        or after any rename, so the warning would just stop appearing."""
        from polymnemo import server
        from polymnemo.store import InMemoryStore

        class TracingInMemoryStore(InMemoryStore):
            pass

        monkeypatch.setattr(
            app,
            "ctx",
            SimpleNamespace(
                store=TracingInMemoryStore(shared_namespaces=[]),
                auth=SimpleNamespace(),
            ),
            raising=False,
        )
        with caplog.at_level(logging.WARNING):
            server._log_degradations()
        assert [r for r in caplog.records if "InMemoryStore" in r.message]


class TestSignInFailureKeepsTheDetail:
    def test_the_handler_logs_the_message_not_just_the_class(self, caplog):
        """Asserted against web.py's own source, not by calling logger.warning
        with the format string here — that would only prove that Python
        interpolates, and would stay green if web.py reverted to the class
        alone."""
        import inspect

        from polymnemo import web

        source = inspect.getsource(web)
        assert '"token page: GitHub sign-in failed (%s: %s)"' in source
        assert "type(exc).__name__, exc" in source


class TestSecondReviewFixes:
    """One per finding on the second pass over #128."""

    @pytest.fixture(autouse=True)
    def _restore_loggers(self):
        names = ("", "polymnemo", log_mod.CALL_LOGGER, log_mod.AUTH_LOGGER)
        saved = [(logging.getLogger(n), logging.getLogger(n).level) for n in names]
        root = logging.getLogger()
        handlers = list(root.handlers)
        yield
        for log, level in saved:
            log.setLevel(level)
        # configure_logging runs basicConfig(force=True), which swaps root's
        # handler for a fresh one; restoring levels alone leaks it.
        root.handlers = handlers

    def test_a_scope_without_a_resolver_is_refused(self):
        """The guard was one-directional: new_scope alone opened a scope for
        nobody and logged no user_id anywhere, silently."""
        with pytest.raises(ValueError) as caught:
            CallLogMiddleware(
                logger=logging.getLogger(log_mod.CALL_LOGGER),
                new_scope=lambda: None,
            )
        # Symmetric wording: "user_id requires new_scope" would tell this caller
        # to add the thing they already passed.
        assert str(caught.value) == "pass both user_id and new_scope, or neither"

    def test_neither_is_still_allowed(self):
        CallLogMiddleware(logger=logging.getLogger(log_mod.CALL_LOGGER))

    async def test_elapsed_ms_is_measured_not_the_threshold_restated(
        self, caplog, monkeypatch
    ):
        """It was `SLOW_CALL_SECONDS * 1000` — a constant that can only ever
        repeat its own assumption, which is the #96 mistake again."""
        import asyncio

        monkeypatch.setattr(log_mod, "SLOW_CALL_SECONDS", 0.05)
        mw = _middleware()

        async def slow(context):
            await asyncio.sleep(1)

        with caplog.at_level(logging.WARNING):
            task = asyncio.create_task(mw.on_message(_context(), slow))
            await asyncio.sleep(0.25)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elapsed = json.loads(_lines(caplog)[0])["elapsed_ms"]
        assert elapsed != 50.0, "still the threshold echoed back"
        # Two-sided: a microsecond/millisecond mix-up would give ~250_000 and
        # sail past a lower bound alone.
        assert 50.0 <= elapsed <= 1000.0

    async def test_a_missing_source_does_not_become_null(self, caplog):
        """`method` had a fallback and `source` didn't, so a None source
        violated the line's own type and emitted `"source": null`."""
        context = SimpleNamespace(
            type="request",
            method=None,
            source=None,
            message=SimpleNamespace(name="remember"),
        )
        with caplog.at_level(logging.INFO):
            await _middleware().on_message(context, _ok)
        entry = json.loads(_lines(caplog)[0])
        assert entry["source"] == "unknown"
        assert entry["method"] == "unknown"

    def test_auth_modules_do_not_import_the_logging_constant(self):
        """They sit under `polymnemo.auth.*` via __name__ and inherit the level
        pinned there — nothing to keep in sync, and no dependency from auth back
        to logging configuration."""
        import inspect

        from polymnemo.auth import bearer, oauth

        for module in (bearer, oauth):
            source = inspect.getsource(module)
            assert "AUTH_LOGGER" not in source
            assert "getLogger(__name__)" in source
        assert bearer.logger.name.startswith("polymnemo.auth.")

    def test_the_pinned_level_reaches_the_child_loggers(self):
        from polymnemo.auth import bearer

        log_mod.configure_logging(structured=False, level="ERROR")
        assert bearer.logger.isEnabledFor(logging.WARNING)

    async def test_the_watchdog_is_scheduled_as_a_task(self, monkeypatch):
        """Behavioural. `co_names` was a CPython detail, and it couldn't tell
        `asyncio.create_task` from `get_running_loop().create_task`."""
        import asyncio

        real = asyncio.create_task
        scheduled = []

        def spy(coro, **kw):
            scheduled.append(coro)
            return real(coro, **kw)

        monkeypatch.setattr(asyncio, "create_task", spy)
        await _middleware().on_message(_context(), _ok)
        assert scheduled, "the watchdog was never scheduled"


class TestSlowCallLogsTwiceOnPurpose:
    """A call crossing the threshold and then finishing logs both lines.

    The review asked for one; suppressing either loses a fact. The in-flight
    line is the only evidence the call was stuck, and the completion line is the
    only evidence of how it ended. Asserted so the behaviour is a decision
    rather than something that drifted.
    """

    async def test_both_lines_appear_in_order(self, caplog, monkeypatch):
        import asyncio

        monkeypatch.setattr(log_mod, "SLOW_CALL_SECONDS", 0.02)

        async def slow(context):
            await asyncio.sleep(0.15)
            return "ok"

        with caplog.at_level(logging.INFO):
            await _middleware().on_message(_context(), slow)
        events = [json.loads(line)["event"] for line in _lines(caplog)]
        assert events == ["request_in_flight", "request_success"]

    async def test_a_call_under_the_threshold_logs_once(self, caplog, monkeypatch):
        import asyncio

        monkeypatch.setattr(log_mod, "SLOW_CALL_SECONDS", 5.0)
        with caplog.at_level(logging.INFO):
            await _middleware().on_message(_context(), _ok)
            await asyncio.sleep(0)
        assert len(_lines(caplog)) == 1
