"""Dependency-free placeholder embedder.

Hashes tokens into a fixed-dimension bag-of-words vector and L2-normalizes it —
deterministic, no model download, no numpy. Overlapping words yield higher
cosine similarity, so in-memory recall is *vaguely* meaningful in dev. Real
semantic quality comes from the fastembed model in #3.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]")


def _tokenize(text: str) -> list[str]:
    # Latin words plus individual CJK characters.
    return _TOKEN_RE.findall(text.lower())


class StubEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            # hashlib (not built-in hash) so vectors are stable across runs.
            digest = hashlib.md5(tok.encode("utf-8")).hexdigest()
            vec[int(digest, 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        return vec

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)
