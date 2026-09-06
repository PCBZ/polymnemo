"""Vector retriever — the MVP ranking strategy.

Embeds the query with the same model used on write, then delegates the
nearest-neighbour lookup to the store. Store-agnostic: works with
``InMemoryStore`` today and ``PostgresStore`` (pgvector) later.
"""

from __future__ import annotations

from ..embedding.base import Embedder
from ..models import Memory
from ..store.base import Store


class VectorRetriever:
    def __init__(self, store: Store, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def search(
        self,
        user_id: str,
        query: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        query_vec = self.embedder.embed_query(query)
        return self.store.search(user_id, namespace, query_vec, limit, offset)
