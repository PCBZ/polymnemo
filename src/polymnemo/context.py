"""Application context — assemble the pluggable layers from config.

One place that decides which Auth / Store / Retriever / Embedder implementations
are active (a lightweight composition root). Phase 0 wires the dev defaults
(static auth, in-memory store, stub embedder); later issues swap in the real
ones (BearerKeyAuth #5, PostgresStore #6, fastembed Embedder #3) without
touching call sites.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .auth import Auth, StaticAuth
from .config import settings
from .embedding import Embedder, StubEmbedder
from .retriever import Retriever, VectorRetriever
from .store import InMemoryStore, Store


class AppContext(BaseModel):
    # Holds live service objects, not plain data: allow arbitrary types, and
    # freeze it since the wiring shouldn't change after startup. Field types are
    # the layer Protocols, so pydantic validates each implementation against them
    # (this is why they are @runtime_checkable).
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

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


def build_context() -> AppContext:
    # Phase 0 dev defaults. As real implementations land, select here (e.g. by
    # settings.database_url) instead of always using the in-memory/stub ones.
    store: Store = InMemoryStore()
    embedder: Embedder = StubEmbedder(dim=settings.embed_dim)
    retriever: Retriever = VectorRetriever(store=store, embedder=embedder)
    auth: Auth = StaticAuth()
    return AppContext(auth=auth, store=store, embedder=embedder, retriever=retriever)
