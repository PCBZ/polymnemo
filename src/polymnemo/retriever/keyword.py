"""Keyword retriever — rows containing every term of the query.

Exact substring matching, so it finds what vector search is worst at: an ID, a
name, a project codename, an error string. It knows nothing about meaning, so
`coffee` will not find a memory that says `espresso`. Use `similarity` for that,
or `rrf` for both.
"""

from __future__ import annotations

from ..models import Memory
from ..store.base import Store


class KeywordRetriever:
    def __init__(self, store: Store) -> None:
        self.store = store

    def search(
        self,
        user_id: str,
        query: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        return self.store.search_text(user_id, namespace, query, limit, offset)
