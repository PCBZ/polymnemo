"""Embedder seam — turn text into vectors, locally and deterministically.

The server owns embedding: whatever LLM connects, the same model is used for
both writes and queries, so the vector space is consistent and cross-LLM recall
is meaningful. The real implementation (fastembed / ONNX) arrives in #3; this
package also ships a dependency-free ``StubEmbedder`` for wiring and tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    # Output dimension; pinned and must match the DB schema.
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed content for storage."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        ...
