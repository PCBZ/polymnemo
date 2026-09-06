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

from dataclasses import dataclass

from .auth import Auth, StaticAuth
from .config import settings
from .embedding import Embedder, FastEmbedEmbedder, StubEmbedder
from .retriever import Retriever, VectorRetriever
from .store import InMemoryStore, Store


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


def build_context() -> AppContext:
    # Phase 0 dev defaults. As real implementations land, select here (e.g. by
    # settings.database_url for the store) instead of the in-memory one.
    store: Store = InMemoryStore()
    embedder: Embedder = _build_embedder()
    retriever: Retriever = VectorRetriever(store=store, embedder=embedder)
    auth: Auth = StaticAuth()
    return AppContext(auth=auth, store=store, embedder=embedder, retriever=retriever)
