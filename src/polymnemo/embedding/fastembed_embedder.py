"""Local, deterministic embedder via fastembed (ONNX).

No API key, no external / generative-LLM call — the model runs in-process. The
server owns embedding so every LLM shares one vector space (consistent
cross-LLM recall). The model is pinned; changing it means re-embedding the store.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import settings


class FastEmbedEmbedder:
    """Wraps a fastembed model. Loaded lazily on first use so the server starts
    instantly and offline dev (with a cached model) needs no network."""

    def __init__(self, model_name: str | None = None, dim: int | None = None) -> None:
        self.model_name = model_name or settings.embed_model
        self.dim = dim if dim is not None else settings.embed_dim
        self._model = None
        self._dim_checked = False

    # -- model loading --------------------------------------------------------
    def _ensure_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def warm_up(self) -> int:
        """Load the model and confirm its dimension. Returns the detected dim.

        Call at startup (or bake into the image) so the first request doesn't pay
        the load/download cost.
        """
        return len(self.embed_query("warm up"))

    # -- e5 prompt prefixes ---------------------------------------------------
    # e5-family models expect "query:" / "passage:" prefixes; others (like the
    # default multilingual MiniLM) are passed through unchanged.
    def _prefix(self, text: str, kind: str) -> str:
        if "e5" in self.model_name.lower():
            return f"{kind}: {text}"
        return text

    def _check_dim(self, vectors: list[list[float]]) -> None:
        if self._dim_checked or not vectors:
            return
        actual = len(vectors[0])
        if actual != self.dim:
            raise ValueError(
                f"Embedding model '{self.model_name}' produced dimension "
                f"{actual}, but POLYMNEMO_EMBED_DIM is {self.dim}. Set "
                "POLYMNEMO_EMBED_DIM to match the model (and the DB schema)."
            )
        self._dim_checked = True

    # -- public API -----------------------------------------------------------
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        model = self._ensure_model()
        prepared = [self._prefix(t, "passage") for t in texts]
        vectors = [vec.tolist() for vec in model.embed(prepared)]
        self._check_dim(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure_model()
        prepared = self._prefix(text, "query")
        vectors = [vec.tolist() for vec in model.embed([prepared])]
        self._check_dim(vectors)
        return vectors[0]
