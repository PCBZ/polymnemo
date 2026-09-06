"""Retriever seam — turn a text query into ranked memories.

Separated from ``Store`` so ranking strategy is swappable: ``VectorRetriever``
(embedding nearest-neighbour) is the MVP; ``KeywordRetriever`` / hybrid RRF are
optional later (#17). The server owns *mechanism* (ranking, bounded results);
the client owns *judgment* (what to ask, whether it's enough).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Memory


@runtime_checkable
class Retriever(Protocol):
    def search(
        self,
        user_id: str,
        query: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        """Return memories ranked for ``query``, sliced by ``offset``/``limit``."""
        ...
