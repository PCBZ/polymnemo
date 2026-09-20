"""Browser pages for minting API tokens (#125).

A secret must never travel an LLM channel — not a tool result, not a URL in a
transcript. The MCP spec says as much for elicitation ("sensitive credentials
never pass through the LLM context"), and every hosted MCP server surveyed
issues tokens from a web page instead. So does this.

Scope is deliberately *tokens only*. This is polymnemo's first human-facing
surface and the obvious next request is "show me my memories here too"; that
belongs to a different decision, not to feature creep.

Authentication here is its own thing. The MCP OAuth flow serves MCP clients —
dynamic registration, PKCE, a loopback callback — and issues MCP access tokens,
not browser sessions. These routes run a plain server-side authorization-code
flow against whichever identity provider the user picks, ending in a signed
cookie. Each provider is a separate account -- see auth/providers.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import secrets
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from string import Template
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from .auth import providers
from .auth.tokens import ApiToken, ApiTokenStore
from .config import settings
from .logging import AUDIT_LOGGER

logger = logging.getLogger("polymnemo")
# Credential lifecycle: pinned so `log_level` cannot raise it out of view.
audit = logging.getLogger(AUDIT_LOGGER)

SESSION_COOKIE = "polymnemo_session"
SESSION_MAX_AGE = 8 * 3600
# The OAuth `state`, in a cookie so any replica can answer the callback.
STATE_COOKIE = "polymnemo_oauth_state"


def _secret() -> bytes:
    """Key for signing cookies, derived from the OAuth client secret so every
    replica agrees without another setting.

    Refuses an empty secret: that key is the SHA-256 of a public constant, so
    anyone could forge a session for any ``user_id``.
    """
    secret = settings.oauth_client_secret
    if not secret:
        raise RuntimeError(
            "web sessions need POLYMNEMO_OAUTH_CLIENT_SECRET; "
            "without it the signing key would be publicly derivable"
        )
    return hashlib.sha256(f"polymnemo-web-session:{secret}".encode()).digest()


def _sign(payload: str) -> str:
    mac = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def _unsign(value: str) -> str | None:
    payload, _, mac = value.rpartition(".")
    if not payload or not mac:
        return None
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    # compare_digest, not ==: `==` leaks the correct prefix length via timing.
    if not hmac.compare_digest(mac, expected):
        return None
    return payload


def _session_user(request: Request) -> str | None:
    """The signed-in ``user_id``, or None. Expiry is inside the signed payload,
    so a stale cookie can't be replayed by resetting the browser's clock."""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    payload = _unsign(raw)
    if payload is None:
        return None
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    user_id = data.get("sub")
    return user_id if isinstance(user_id, str) else None


def _base_url(request: Request) -> str:
    configured = settings.oauth_base_url.rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _new_session(user_id: str) -> str:
    """A signed session carrying its own expiry and a CSRF token."""
    return _sign(
        json.dumps(
            {
                "sub": user_id,
                "exp": int(time.time()) + SESSION_MAX_AGE,
                "csrf": secrets.token_urlsafe(16),
            },
            separators=(",", ":"),
        )
    )


def _session_csrf(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    payload = _unsign(raw) if raw else None
    if payload is None:
        return None
    try:
        return json.loads(payload).get("csrf")
    except ValueError:
        return None


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,  # JavaScript can't read it, so XSS can't lift the session
        secure=True,
        samesite="lax",  # blocks cross-site POSTs; the CSRF token is belt-and-braces
        path="/tokens",  # never sent to /mcp, which authenticates by token alone
    )


# --- page ------------------------------------------------------------------
# Markup lives in templates/. `string.Template`, not `str.format`: `format`
# reads CSS braces as placeholders.
_TEMPLATES = Path(__file__).parent / "templates"


@cache
def _template(name: str) -> Template:
    return Template((_TEMPLATES / name).read_text())


def _fail(message: str) -> Response:
    return PlainTextResponse(message, status_code=400)


def _fail_signin(message: str) -> Response:
    """A failed sign-in, with the one-shot `state` cookie dropped so a retry
    starts from a clean slate instead of a stale value."""
    response = _fail(message)
    response.delete_cookie(STATE_COOKIE, path="/tokens")
    return response


def _expiry_label(expires_at: datetime | None) -> str:
    """How a token's expiry reads in the table. Expired rows are marked — they
    no longer resolve, and otherwise look identical to working ones."""
    if expires_at is None:
        return "never"
    # Naive rows predate the tz-aware column; don't raise on a mixed compare.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    shown = expires_at.date().isoformat()
    return f"{shown} (expired)" if expires_at <= datetime.now(UTC) else shown


async def _load_tokens(store: ApiTokenStore | None, user_id: str) -> list[ApiToken]:
    """The store is sync and these handlers are async: off the event loop, so a
    slow query can't stall every other in-flight request."""
    if store is None:
        return []
    return await asyncio.to_thread(store.list_for_user, user_id)


def _signin_page(available, base: str) -> HTMLResponse:
    """The chooser. Only reached when more than one provider is configured."""
    button = _template("signin_button.html")
    buttons = "".join(
        button.substitute(base=base, key=p.key, label=html.escape(p.label))
        for p in available
    )
    return HTMLResponse(_template("signin.html").substitute(base=base, buttons=buttons))


def _tokens_page(
    tokens: list[ApiToken],
    user_id: str,
    csrf: str,
    base: str,
    fresh: str | None = None,
) -> HTMLResponse:
    """Renders the page. Takes the rows rather than the store, so the query
    stays in the handler where it can be pushed off the event loop."""
    rows = ""
    if tokens:
        row = _template("token_row.html")
        for t in tokens:
            rows += row.substitute(
                label=html.escape(t.label),
                created=t.created_at.date().isoformat(),
                expires=_expiry_label(t.expires_at),
                base=base,
                csrf=html.escape(csrf),
                id=html.escape(t.id),
            )

    return HTMLResponse(
        _template("tokens.html").substitute(
            user_id=html.escape(user_id),
            csrf=html.escape(csrf),
            base=base,
            rows=rows,
            # Always in the markup, hidden when there's nothing to reveal.
            reveal_hidden="" if fresh else " hidden",
            empty_hidden=" hidden" if rows else "",
            fresh=html.escape(fresh) if fresh else "",
        )
    )


def register(mcp, store: ApiTokenStore | None) -> None:
    """Mount the token pages. Called from ``server`` so this module doesn't have
    to import it back; ``store`` is passed in for the same reason.

    Mounts nothing without OAuth: there is no way to sign in, and the session
    key would derive from an empty secret — forgeable, and the deploy really
    does run that way before the OAuth app is registered.
    """
    if not settings.oauth_enabled:
        logger.info("token pages not mounted: OAuth is not configured")
        return

    @mcp.custom_route("/tokens/style.css", methods=["GET"])
    async def tokens_style(request: Request) -> Response:
        # No session check: it's a stylesheet.
        return Response(
            _template("tokens.css").template,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @mcp.custom_route("/tokens", methods=["GET"])
    async def tokens_index(request: Request) -> Response:
        base = _base_url(request)
        user_id = _session_user(request)
        if user_id is None:
            return RedirectResponse(f"{base}/tokens/login", status_code=302)
        tokens = await _load_tokens(store, user_id)
        return _tokens_page(tokens, user_id, _session_csrf(request) or "", base)

    @mcp.custom_route("/tokens/login", methods=["GET"])
    async def tokens_login(request: Request) -> Response:
        base = _base_url(request)
        available = providers.enabled()
        if not available:
            return _fail("Sign-in is not configured on this deployment.")
        # No chooser for a single provider: a one-button page is just a stop.
        if len(available) == 1:
            return RedirectResponse(
                f"{base}/tokens/login/{available[0].key}", status_code=302
            )
        return _signin_page(available, base)

    @mcp.custom_route("/tokens/login/{provider}", methods=["GET"])
    async def tokens_login_provider(request: Request) -> Response:
        base = _base_url(request)
        # `get` returns None for a provider without credentials, so a crafted
        # URL cannot start a flow the operator never enabled.
        provider = providers.get(request.path_params["provider"])
        if provider is None:
            return _fail("Unknown sign-in method.")
        state = secrets.token_urlsafe(16)
        url = (
            provider.authorize_url
            + "?"
            + urlencode(
                {
                    "client_id": provider.client_id,
                    "redirect_uri": f"{base}/tokens/callback",
                    "scope": provider.scope,
                    "state": state,
                    # Optional for GitHub, required by Google.
                    "response_type": "code",
                }
            )
        )
        response = RedirectResponse(url, status_code=302)
        # Signed so the callback can tell its own state from an attacker's, and
        # carrying the provider so one callback URL can serve every flow.
        _set_cookie(response, STATE_COOKIE, _sign(f"{provider.key}|{state}"), 600)
        return response

    @mcp.custom_route("/tokens/callback", methods=["GET"])
    async def tokens_callback(request: Request) -> Response:
        base = _base_url(request)
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        cookie_state = request.cookies.get(STATE_COOKIE)
        signed = _unsign(cookie_state) if cookie_state else None
        provider_key, _, expected = (signed or "").partition("|")
        provider = providers.get(provider_key)
        if (
            not code
            or not state
            or not expected
            or not secrets.compare_digest(state, expected)
            or provider is None
        ):
            # Else an attacker completes the flow with their own code.
            return _fail_signin(
                "Sign-in failed: invalid or expired request. "
                f"Start again at {base}/tokens"
            )

        # GitHub may answer HTML despite the Accept header; `.json()` raises.
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                token_resp = await client.post(
                    provider.token_url,
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": provider.client_id,
                        "client_secret": provider.client_secret,
                        "code": code,
                        "redirect_uri": f"{base}/tokens/callback",
                        # Ignored by GitHub, required by Google.
                        "grant_type": "authorization_code",
                    },
                )
                access = token_resp.json().get("access_token")
                if not access:
                    logger.warning(
                        "token page: %s returned no access token", provider.key
                    )
                    return _fail_signin("Sign-in failed.")
                user_resp = await client.get(
                    provider.userinfo_url,
                    headers={
                        "Authorization": f"Bearer {access}",
                        **provider.userinfo_headers,
                    },
                )
                sub = user_resp.json().get(provider.subject_field)
        except (ValueError, httpx.HTTPError) as exc:  # ValueError: JSONDecodeError
            # The message too: it carries the status, not the OAuth code.
            logger.warning(
                "token page: %s sign-in failed (%s: %s)",
                provider.key,
                type(exc).__name__,
                exc,
            )
            return _fail_signin("Sign-in failed.")
        if sub is None:
            return _fail_signin("Sign-in failed.")

        user_id = f"{provider.subject_prefix}{sub}"
        audit.info("token page: signed in as %s", user_id)
        response = RedirectResponse(f"{base}/tokens", status_code=302)
        _set_cookie(response, SESSION_COOKIE, _new_session(user_id), SESSION_MAX_AGE)
        response.delete_cookie(STATE_COOKIE, path="/tokens")
        return response

    @mcp.custom_route("/tokens/create", methods=["POST"])
    async def tokens_create(request: Request) -> Response:
        base = _base_url(request)
        user_id = _session_user(request)
        form = await request.form()
        if user_id is None or not _csrf_ok(request, form):
            return _fail(f"Request rejected. Start again at {base}/tokens")
        if store is None:
            return _fail("API tokens need a database; this server has none.")
        # Collapse newlines: `.strip()` only trims the ends, and an interior
        # one lets a label forge a second log line that parses as a call
        # record. The JSON formatter escapes it too; this is the source fix.
        label = " ".join(str(form.get("label") or "").split())[:60]
        if not label:
            return RedirectResponse(f"{base}/tokens", status_code=302)
        try:
            days = int(str(form.get("expires_days") or 90))
        except ValueError:
            days = 90
        # Clamped, and no "never" option: `create` accepts None for a
        # permanent token, but a credential minted from a browser should
        # rotate. A year is the ceiling; scripts wanting longer re-mint.
        days = max(1, min(days, 365))
        token, meta = await asyncio.to_thread(store.create, user_id, label, days)
        # Audit: a credential's provenance can't be reconstructed later.
        audit.info(
            "api token created: user=%s id=%s label=%r expires=%s",
            user_id,
            meta.id,
            meta.label,
            meta.expires_at,
        )
        tokens = await _load_tokens(store, user_id)
        return _tokens_page(
            tokens, user_id, _session_csrf(request) or "", base, fresh=token
        )

    @mcp.custom_route("/tokens/revoke", methods=["POST"])
    async def tokens_revoke(request: Request) -> Response:
        base = _base_url(request)
        user_id = _session_user(request)
        form = await request.form()
        if user_id is None or not _csrf_ok(request, form):
            return _fail("Request rejected.")
        if store is not None:
            token_id = str(form.get("id") or "")
            revoked = await asyncio.to_thread(store.revoke, user_id, token_id)
            audit.info(
                "api token revoke: user=%s id=%s found=%s", user_id, token_id, revoked
            )
            if not revoked:
                # False means no row matched: already gone, or not this user's.
                return _fail("Token not found, or already revoked.")
        return RedirectResponse(f"{base}/tokens", status_code=302)


def _csrf_ok(request: Request, form) -> bool:
    """SameSite=lax already blocks cross-site form posts; this is the second
    lock, in case a browser or proxy doesn't honour it."""
    expected = _session_csrf(request)
    if not expected:
        return False
    supplied = str(form.get("csrf") or "")
    return hmac.compare_digest(expected, supplied)
