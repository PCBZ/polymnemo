"""The deployment's logs arrive in Log Analytics in the expected shape (#129).

A *check*, not a round trip. Tying a specific request to its line would need a
correlation id the call log does not carry, and buying that would mean driving
traffic and waiting for it to land — neither belongs in a smoke test.

It drives nothing: this runs after the endpoint job, so the calls that job
already made are the lines it looks for.

What it is defending: #128 shipped with `POLYMNEMO_LOG_FORMAT` never injected by
Terraform, so the per-call log the change exists to produce was never emitted in
production. Every unit test passed, the deploy was green, and nothing noticed.

Talks to the Log Analytics query API over plain HTTP rather than shelling out to
`az`, so this needs no CLI on the box and no `az login` in the workflow — the
same three service-principal values Terraform already uses are enough.
"""

from __future__ import annotations

import json
import os
import re
import time

import httpx
import pytest

# Log Analytics is not immediate. Measured over 33,590 lines across 7 days of
# this workspace (`ingestion_time() - TimeGenerated`): p50 4s, p95 10s, p99 28s,
# max 359s. So the common case is seconds, but the tail runs to ~6 minutes — and
# a timeout under that turns a slow ingest into a red deploy. 600 clears the
# observed max with room; it is only ever spent when something is actually
# wrong, since a healthy run returns on the first poll.
#
# Overridable because CI and a local run want different patience.
INGESTION_TIMEOUT_SECONDS = int(os.environ.get("POLYMNEMO_SMOKE_LOG_TIMEOUT", "600"))
POLL_SECONDS = 15

CALL_LOGGER = "polymnemo.calls"

# `api.loganalytics.io` is being replaced by this host. The token's *audience*
# stays on the old name, which is not a typo: Entra has no resource principal
# named api.loganalytics.azure.com, and asking for one fails with AADSTS500011.
QUERY_HOST = "https://api.loganalytics.azure.com"
TOKEN_SCOPE = "https://api.loganalytics.io/.default"

TIMEOUT = httpx.Timeout(60.0)


@pytest.fixture(scope="session")
def log_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """One client-credentials token for the whole session.

    Session-scoped because the fetch below polls: a token per poll would be a
    dozen round trips for a credential that stays valid for an hour.
    """
    response = httpx.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": TOKEN_SCOPE,
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        # The body names the Entra error (AADSTS...), which is the only thing
        # that distinguishes a wrong secret from a missing role assignment.
        pytest.fail(f"could not get a Log Analytics token: {response.text[:400]}")
    return str(response.json()["access_token"])


@pytest.fixture(scope="session")
def recent_lines(workspace: str, app_name: str, log_token: str) -> list[dict]:
    """Structured lines this app logged recently, newest first.

    Session-scoped so the wait is paid once: every assertion below reads the
    same fetch.
    """
    # KQL has no parameter binding here, so the name goes in by interpolation.
    # Azure restricts container app names to this shape, and asserting it says
    # so out loud rather than leaving the query to depend on it silently.
    assert re.fullmatch(r"[a-zA-Z0-9-]+", app_name), (
        f"unexpected app name: {app_name!r}"
    )
    query = (
        "ContainerAppConsoleLogs_CL"
        f" | where TimeGenerated > ago(30m) and ContainerAppName_s == '{app_name}'"
        " | project TimeGenerated, Log_s"
        " | order by TimeGenerated desc"
        " | take 200"
    )
    deadline = time.monotonic() + INGESTION_TIMEOUT_SECONDS
    rows: list[dict] = []
    while True:
        rows = _structured(_query(workspace, query, log_token))
        if rows or time.monotonic() > deadline:
            break
        time.sleep(POLL_SECONDS)

    if not rows:
        pytest.fail(
            f"no structured line from {app_name!r} within "
            f"{INGESTION_TIMEOUT_SECONDS}s — either the deployment is not "
            "emitting JSON (POLYMNEMO_LOG_FORMAT unset?) or ingestion is slower "
            "than this timeout"
        )
    return rows


def _query(workspace: str, kql: str, token: str) -> list[dict]:
    """Run a KQL query, with the API's column/row pairs zipped back into dicts."""
    response = httpx.post(
        f"{QUERY_HOST}/v1/workspaces/{workspace}/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": kql},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        pytest.fail(f"log query failed ({response.status_code}): {response.text[:400]}")
    table = response.json()["tables"][0]
    columns = [column["name"] for column in table["columns"]]
    # strict: a row whose arity differs from the column list would silently
    # drop or invent a field, and every assertion below reads by key.
    return [dict(zip(columns, row, strict=True)) for row in table["rows"]]


def _structured(rows: list[dict]) -> list[dict]:
    """The rows whose payload is one of our JSON lines, parsed."""
    out = []
    for row in rows:
        line = (row.get("Log_s") or "").strip()
        if not line.startswith("{"):
            continue  # uvicorn's own output, banners, tracebacks
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_the_deployment_emits_structured_logs(recent_lines):
    """#128 exactly: with POLYMNEMO_LOG_FORMAT unset the app logs prose, and
    every log-based metric silently returns nothing.

    The startup line alone satisfies this — a deploy restarts the app, so a
    line exists even with no traffic at all.
    """
    assert recent_lines, "no JSON lines at all"
    for line in recent_lines:
        assert "level" in line and "logger" in line, (
            f"a structured line is missing level/logger: {line}"
        )


def test_the_call_log_is_being_written(recent_lines):
    """That the middleware registered and its path works end to end. Without
    it the service still serves every request — it just records none of them."""
    calls = [ln for ln in recent_lines if ln.get("logger") == CALL_LOGGER]
    assert calls, (
        f"no {CALL_LOGGER} lines; the endpoint job's own traffic should have "
        "produced them"
    )
    for line in calls:
        assert line.get("event"), line
        assert "duration_ms" in line, line


def test_an_authenticated_call_is_attributed(recent_lines):
    """The identity plumbing, end to end on a real deployment: the injected
    resolver, the per-request scope, and the worker-thread hop a sync tool
    takes — each of which broke at least once while #128 was in review."""
    attributed = [
        ln
        for ln in recent_lines
        if ln.get("logger") == CALL_LOGGER and ln.get("user_id")
    ]
    assert attributed, (
        "no call-log line carries a user_id, though the endpoint job made "
        "authenticated calls"
    )
