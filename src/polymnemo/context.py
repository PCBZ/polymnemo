"""Application context — assemble the pluggable layers from config.

One place that decides which Auth / Store / Retriever / Embedder implementations
are active (a lightweight composition root). Phase 0 wires the dev defaults
(static auth, in-memory store, stub embedder); later issues swap in the real
ones (BearerKeyAuth #5, PostgresStore #6, fastembed Embedder #3) without
touching call sites.

Held as a frozen dataclass: it carries live service objects (not data to
validate/serialize), and the wiring shouldn't change after startup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .auth import Auth, BearerKeyAuth, StaticAuth
from .config import settings
from .embedding import Embedder, FastEmbedEmbedder, StubEmbedder
from .ratelimit import GlobalRateLimiter
from .retriever import Retriever, VectorRetriever
from .store import InMemoryStore, Store

logger = logging.getLogger("polymnemo")


@dataclass(frozen=True)
class AppContext:
    auth: Auth
    store: Store
    embedder: Embedder
    retriever: Retriever
    rate_limiter: GlobalRateLimiter | None

    def describe(self) -> dict[str, str]:
        """Names of the active implementations (for diagnostics / ``ping``)."""
        return {
            "auth": type(self.auth).__name__,
            "store": type(self.store).__name__,
            "embedder": type(self.embedder).__name__,
            "retriever": type(self.retriever).__name__,
            "rate_limiter": type(self.rate_limiter).__name__ if self.rate_limiter else "disabled",
        }


def _build_embedder() -> Embedder:
    if settings.embed_backend == "stub":
        return StubEmbedder(dim=settings.embed_dim)
    return FastEmbedEmbedder()


def _build_store() -> Store:
    shared = settings.parse_shared_namespaces()
    if settings.database_url:
        from .store.postgres import PostgresStore

        logger.info("Using PostgresStore")
        return PostgresStore(settings.database_url, shared_namespaces=shared)
    if settings.require_database:
        raise RuntimeError(
            "POLYMNEMO_DATABASE_URL is not set but POLYMNEMO_REQUIRE_DATABASE=true. "
            "Provide the database (Neon pooled) connection string."
        )
    logger.warning(
        "No POLYMNEMO_DATABASE_URL -> using InMemoryStore (dev/test only; "
        "NOT durable and NOT shared across instances)."
    )
    return InMemoryStore(shared_namespaces=shared)


def _build_auth() -> Auth:
    if settings.auth_backend == "static":
        return StaticAuth()
    keys = settings.parse_api_keys()
    if not keys:
        logger.warning(
            "auth_backend=bearer but no POLYMNEMO_API_KEYS set; all requests "
            "will be rejected. Set keys, or use POLYMNEMO_AUTH_BACKEND=static for dev."
        )
    return BearerKeyAuth(keys)


def _build_rate_limiter() -> GlobalRateLimiter | None:
    if not settings.ratelimit_enabled:
        return None
    return GlobalRateLimiter(settings.ratelimit_per_min)


def build_context() -> AppContext:
    store: Store = _build_store()
    embedder: Embedder = _build_embedder()
    retriever: Retriever = VectorRetriever(store=store, embedder=embedder)
    auth: Auth = _build_auth()
    rate_limiter: GlobalRateLimiter | None = _build_rate_limiter()
    return AppContext(
        auth=auth,
        store=store,
        embedder=embedder,
        retriever=retriever,
        rate_limiter=rate_limiter,
    )
