"""Token-aware chunking that respects the embedding model's context window.

Splitting is done in *tokens* (via the model's own tokenizer) so no chunk exceeds
the model's max sequence length — otherwise the tail of a chunk would be silently
truncated out of its embedding and become unsearchable. Uses semantic-text-splitter,
which also prefers semantic boundaries (paragraphs/sentences) over hard cuts.

The stub backend has no real tokenizer (offline dev/tests), so it approximates
with a character splitter.
"""

from __future__ import annotations

from functools import lru_cache

from .config import settings

# Rough chars-per-token used only for the offline stub approximation.
_CHARS_PER_TOKEN = 4


@lru_cache(maxsize=1)
def _tokenizer():
    """Load the model's HF tokenizer once, shared by every splitter."""
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(settings.embed_model)


def _build_splitter(*, overlap: int, trim: bool):
    """Build a TextSplitter for the active backend.

    Real backend: token-bounded via the shared model tokenizer. Stub backend
    (offline dev/tests): a character splitter approximating tokens by
    ``_CHARS_PER_TOKEN``.
    """
    from semantic_text_splitter import TextSplitter

    if settings.embed_backend == "stub":
        return TextSplitter(
            settings.chunk_tokens * _CHARS_PER_TOKEN,
            overlap=overlap * _CHARS_PER_TOKEN,
            trim=trim,
        )

    return TextSplitter.from_huggingface_tokenizer(
        _tokenizer(),
        capacity=settings.chunk_tokens,
        overlap=overlap,
        trim=trim,
    )


@lru_cache(maxsize=1)
def _splitter():
    # Recall-oriented: overlap so a boundary phrase stays searchable; trim
    # whitespace at cut points for cleaner embeddings.
    return _build_splitter(overlap=settings.chunk_overlap_tokens, trim=True)


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into token-bounded chunks (empty input -> no chunks)."""
    text = (text or "").strip()
    if not text:
        return []
    return _splitter().chunks(text)


@lru_cache(maxsize=1)
def _verbatim_splitter():
    # Lossless: no overlap and no trimming, so concatenating chunks reproduces
    # the input byte-for-byte.
    return _build_splitter(overlap=0, trim=False)


def chunk_verbatim(text: str) -> list[str]:
    """Split into non-overlapping, untrimmed token-bounded chunks whose
    concatenation reconstructs ``text`` exactly — used for saving sessions so
    load_session round-trips losslessly (empty input -> no chunks)."""
    if not text:
        return []
    return _verbatim_splitter().chunks(text)
