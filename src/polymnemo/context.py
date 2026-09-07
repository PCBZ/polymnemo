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
from .retriever import Retriever, VectorRetriever
from .store import InMemoryStore, Store

logger = logging.getLogger("polymnemo")


@dataclass(frozen=True)
class AppContext:
    auth: Auth
    store: Store
    embedder: Embedder
    retriever: Retriever

    def describe(self) -> dict[str, str]:
        """Names of the active implementations (for diagnostics / ``ping``)."""
        return {
            "auth": type(self.auth).__name__,
            "store": type(self.store).__name__,
            "embedder": type(self.embedder).__name__,
            "retriever": type(self.retriever).__name__,
        }


def _build_embedder() -> Embedder:
    if settings.embed_backend == "stub":
        return StubEmbedder(dim=settings.embed_dim)
    return FastEmbedEmbedder()


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


def build_context() -> AppContext:
    # Phase 0 dev defaults. As real implementations land, select here (e.g. by
    # settings.database_url for the store) instead of the in-memory one.
    store: Store = InMemoryStore(shared_namespaces=settings.parse_shared_namespaces())
    embedder: Embedder = _build_embedder()
    retriever: Retriever = VectorRetriever(store=store, embedder=embedder)
    auth: Auth = _build_auth()
    return AppContext(auth=auth, store=store, embedder=embedder, retriever=retriever)
