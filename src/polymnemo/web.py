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
flow against the same GitHub app and end in a signed cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import secrets
import time
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

from .auth.tokens import ApiTokenStore
from .config import settings

logger = logging.getLogger("polymnemo")

SESSION_COOKIE = "polymnemo_session"
SESSION_MAX_AGE = 8 * 3600
# The OAuth `state` parameter, held in a cookie rather than server state so the
# callback works on whichever replica answers it.
STATE_COOKIE = "polymnemo_oauth_state"
GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"


def _secret() -> bytes:
    """Key for signing cookies. Derived from the OAuth client secret, so every
    replica derives the same one without another setting to configure."""
    return hashlib.sha256(
        f"polymnemo-web-session:{settings.oauth_client_secret}".encode()
    ).digest()


def _sign(payload: str) -> str:
    mac = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def _unsign(value: str) -> str | None:
    payload, _, mac = value.rpartition(".")
    if not payload or not mac:
        return None
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    # compare_digest, not ==: a plain comparison leaks the correct prefix length
    # through timing, which is enough to forge a signature byte by byte.
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
# Three template files — page, row, stylesheet — not markup in string literals:
# HTML reads as HTML, CSS is served as CSS, and this module stays about auth and
# routing.
#
# `string.Template` (`${hole}`), not `str.format`: `format` reads every brace as
# a hole, so it breaks on any template carrying CSS or script braces.
#
# There is one page. Not-signed-in redirects to GitHub instead of rendering a
# landing page, and failures are plain text — an error doesn't need styling, and
# a page per state was more files than states.
_TEMPLATES = Path(__file__).parent / "templates"


@cache
def _template(name: str) -> Template:
    return Template((_TEMPLATES / name).read_text())


def _fail(message: str) -> Response:
    return PlainTextResponse(message, status_code=400)


def _tokens_page(
    store: ApiTokenStore | None,
    user_id: str,
    csrf: str,
    base: str,
    fresh: str | None = None,
) -> HTMLResponse:
    rows = ""
    if store is not None:
        row = _template("token_row.html")
        for t in store.list_for_user(user_id):
            rows += row.substitute(
                label=html.escape(t.label),
                created=t.created_at.date().isoformat(),
                expires=t.expires_at.date().isoformat() if t.expires_at else "never",
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
            # The reveal block always exists and is hidden when there's nothing
            # to reveal — a plain HTML idiom, and one fewer template than
            # conditionally splicing it in.
            reveal_hidden="" if fresh else " hidden",
            empty_hidden=" hidden" if rows else "",
            fresh=html.escape(fresh) if fresh else "",
        )
    )


def register(mcp, store: ApiTokenStore | None) -> None:
    """Mount the token pages. Called from ``server`` so this module doesn't have
    to import it back.

    ``store`` is passed in rather than read from the app context: tokens are a
    browser concern now, so nothing on the MCP side needs to know about them.
    """

    @mcp.custom_route("/tokens/style.css", methods=["GET"])
    async def tokens_style(request: Request) -> Response:
        # No session check: it's a stylesheet. Cached for a day so the page
        # costs one request after the first load.
        return Response(
            (_TEMPLATES / "tokens.css").read_text(),
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @mcp.custom_route("/tokens", methods=["GET"])
    async def tokens_index(request: Request) -> Response:
        base = _base_url(request)
        user_id = _session_user(request)
        if user_id is None:
            return RedirectResponse(f"{base}/tokens/login", status_code=302)
        return _tokens_page(store, user_id, _session_csrf(request) or "", base)

    @mcp.custom_route("/tokens/login", methods=["GET"])
    async def tokens_login(request: Request) -> Response:
        if not settings.oauth_enabled:
            return _fail("OAuth is not configured on this server.")
        base = _base_url(request)
        state = secrets.token_urlsafe(16)
        url = (
            GITHUB_AUTHORIZE
            + "?"
            + urlencode(
                {
                    "client_id": settings.oauth_client_id,
                    "redirect_uri": f"{base}/tokens/callback",
                    "scope": "read:user",
                    "state": state,
                }
            )
        )
        response = RedirectResponse(url, status_code=302)
        # Signed so the callback can tell its own state from an attacker's.
        _set_cookie(response, STATE_COOKIE, _sign(state), 600)
        return response

    @mcp.custom_route("/tokens/callback", methods=["GET"])
    async def tokens_callback(request: Request) -> Response:
        base = _base_url(request)
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        cookie_state = request.cookies.get(STATE_COOKIE)
        expected = _unsign(cookie_state) if cookie_state else None
        if not code or not state or expected is None or state != expected:
            # Without this an attacker can complete the flow with their own code
            # and log the victim into the attacker's account.
            return _fail(
                "Sign-in failed: invalid or expired request. "
                f"Start again at {base}/tokens"
            )

        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                GITHUB_TOKEN,
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.oauth_client_id,
                    "client_secret": settings.oauth_client_secret,
                    "code": code,
                    "redirect_uri": f"{base}/tokens/callback",
                },
            )
            access = token_resp.json().get("access_token")
            if not access:
                logger.warning("token page: GitHub did not return an access token")
                return _fail("Sign-in failed.")
            user_resp = await client.get(
                GITHUB_USER,
                headers={
                    "Authorization": f"Bearer {access}",
                    "Accept": "application/vnd.github+json",
                },
            )
            sub = user_resp.json().get("id")
        if sub is None:
            return _fail("Sign-in failed.")

        # Same shape TokenSubjectAuth produces, so a token minted here belongs to
        # the same user_id the MCP tools see.
        response = RedirectResponse(f"{base}/tokens", status_code=302)
        _set_cookie(
            response, SESSION_COOKIE, _new_session(f"github:{sub}"), SESSION_MAX_AGE
        )
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
        label = str(form.get("label") or "").strip()[:60]
        if not label:
            return RedirectResponse(f"{base}/tokens", status_code=302)
        try:
            days = int(str(form.get("expires_days") or 90))
        except ValueError:
            days = 90
        days = max(1, min(days, 365))
        token, _ = store.create(user_id, label, days)
        return _tokens_page(
            store, user_id, _session_csrf(request) or "", base, fresh=token
        )

    @mcp.custom_route("/tokens/revoke", methods=["POST"])
    async def tokens_revoke(request: Request) -> Response:
        base = _base_url(request)
        user_id = _session_user(request)
        form = await request.form()
        if user_id is None or not _csrf_ok(request, form):
            return _fail("Request rejected.")
        if store is not None:
            store.revoke(user_id, str(form.get("id") or ""))
        return RedirectResponse(f"{base}/tokens", status_code=302)


def _csrf_ok(request: Request, form) -> bool:
    """SameSite=lax already blocks cross-site form posts; this is the second
    lock, in case a browser or proxy doesn't honour it."""
    expected = _session_csrf(request)
    if not expected:
        return False
    supplied = str(form.get("csrf") or "")
    return hmac.compare_digest(expected, supplied)
