"""Hybrid retriever — vector and keyword results fused with RRF.

Reciprocal Rank Fusion scores a row `sum(1 / (k + rank))` over each ranking it
appears in. Only ranks are used, never the scores, which is why it needs no
weight: a cosine similarity and a trigram score are not on the same scale, and
choosing how much one counts for the other would be a guess that goes stale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ..models import Memory
from .base import Retriever

# 60 is the constant from the original RRF paper and what most implementations
# use. It damps the advantage of rank 1 over rank 2, so a row near the top of
# both lists beats one at the very top of only one.
RRF_K = 60

# How many candidates each leg contributes. FIXED, not a multiple of the page
# asked for: a fused rank depends on a row's place in BOTH lists, so reading the
# legs deeper on page 2 can reorder rows that page 1 already returned, repeating
# one and losing another. Every page of a cursor sequence fuses the same window
# and slices it, so paging is stable at the price of a ceiling -- rows ranked
# past the window in both legs are not reachable by paging.
RRF_DEPTH = 50


def rrf_fuse(rankings: Sequence[Sequence[Memory]], k: int = RRF_K) -> list[Memory]:
    """Merge ranked lists into one, best first, deduplicated by id.

    Ties keep first-appearance order, so the earlier ranking wins and the result
    is deterministic. Each returned row carries its fused score.
    """
    scores: dict[str, float] = {}
    first: dict[str, Memory] = {}
    for ranking in rankings:
        for rank, memory in enumerate(ranking, start=1):
            scores[memory.id] = scores.get(memory.id, 0.0) + 1.0 / (k + rank)
            first.setdefault(memory.id, memory)
    order = {memory_id: n for n, memory_id in enumerate(first)}
    ranked = sorted(
        scores, key=lambda memory_id: (-scores[memory_id], order[memory_id])
    )
    return [replace(first[memory_id], score=scores[memory_id]) for memory_id in ranked]


class HybridRetriever:
    def __init__(
        self,
        vector: Retriever,
        keyword: Retriever,
        *,
        depth: int = RRF_DEPTH,
        k: int = RRF_K,
    ) -> None:
        self.vector = vector
        self.keyword = keyword
        self.depth = depth
        self.k = k

    def search(
        self,
        user_id: str,
        query: str,
        namespace: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        # Both legs from rank 0, never offset, and to the SAME depth on every
        # page; see RRF_DEPTH. A page larger than the window widens it rather
        # than being silently truncated -- stable so long as the client keeps
        # its page size, which it does within one cursor sequence.
        depth = max(self.depth, limit)
        fused = rrf_fuse(
            [
                self.vector.search(user_id, query, namespace, depth, 0),
                self.keyword.search(user_id, query, namespace, depth, 0),
            ],
            self.k,
        )
        return fused[offset : offset + limit]
