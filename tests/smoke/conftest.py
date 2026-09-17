"""Smoke tests: they run against a *deployed* polymnemo, not an in-process one.

Opt-in, and skipped when unconfigured — the offline unit suite has to stay
runnable with no cloud, no network, and no credentials.

    POLYMNEMO_SMOKE_URL=https://<host>          # required by both jobs
    POLYMNEMO_SMOKE_KEY=<a bearer key it accepts>
    POLYMNEMO_SMOKE_WORKSPACE=<Log Analytics customer id>   # log check only
    POLYMNEMO_SMOKE_APP=<container app name>                # log check only

Two waits are overridable, because CI can afford patience and a developer
cannot: POLYMNEMO_SMOKE_READY_TIMEOUT (default 300) for how long to wait for a
freshly applied revision to start serving, and POLYMNEMO_SMOKE_LOG_TIMEOUT
(default 600) for Log Analytics ingestion.

The log check also reads ARM_TENANT_ID / ARM_CLIENT_ID / ARM_CLIENT_SECRET — the
same service principal Terraform authenticates with, reused rather than minted
again so there is one identity to grant workspace read to.
"""

from __future__ import annotations

import os

import pytest

SMOKE_URL = "POLYMNEMO_SMOKE_URL"
SMOKE_KEY = "POLYMNEMO_SMOKE_KEY"
SMOKE_WORKSPACE = "POLYMNEMO_SMOKE_WORKSPACE"
SMOKE_APP = "POLYMNEMO_SMOKE_APP"


def _required(name: str, why: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to {why}")
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return _required(SMOKE_URL, "smoke-test a deployment").rstrip("/")


@pytest.fixture(scope="session")
def bearer_key() -> str:
    return _required(SMOKE_KEY, "exercise the authenticated paths")


@pytest.fixture(scope="session")
def workspace() -> str:
    return _required(SMOKE_WORKSPACE, "query the deployment's logs")


@pytest.fixture(scope="session")
def app_name() -> str:
    return _required(SMOKE_APP, "scope the log query to one app")


# Reusing the ARM_* names, not POLYMNEMO_SMOKE_*: anyone who can already run
# terraform against this deployment has them exported, and a second name for the
# same credential invites the two drifting apart.
@pytest.fixture(scope="session")
def tenant_id() -> str:
    return _required("ARM_TENANT_ID", "get a Log Analytics token")


@pytest.fixture(scope="session")
def client_id() -> str:
    return _required("ARM_CLIENT_ID", "get a Log Analytics token")


@pytest.fixture(scope="session")
def client_secret() -> str:
    return _required("ARM_CLIENT_SECRET", "get a Log Analytics token")
