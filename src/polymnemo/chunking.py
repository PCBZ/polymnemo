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
def _splitter():
    from semantic_text_splitter import TextSplitter

    if settings.embed_backend == "stub":
        return TextSplitter(
            settings.chunk_tokens * _CHARS_PER_TOKEN,
            overlap=settings.chunk_overlap_tokens * _CHARS_PER_TOKEN,
        )

    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(settings.embed_model)
    return TextSplitter.from_huggingface_tokenizer(
        tokenizer,
        capacity=settings.chunk_tokens,
        overlap=settings.chunk_overlap_tokens,
    )


def chunk_text(text: str) -> list[str]:
    """Split ``text`` into token-bounded chunks (empty input -> no chunks)."""
    text = (text or "").strip()
    if not text:
        return []
    return _splitter().chunks(text)


@lru_cache(maxsize=1)
def _verbatim_splitter():
    from semantic_text_splitter import TextSplitter

    if settings.embed_backend == "stub":
        return TextSplitter(
            settings.chunk_tokens * _CHARS_PER_TOKEN, overlap=0, trim=False
        )

    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(settings.embed_model)
    return TextSplitter.from_huggingface_tokenizer(
        tokenizer, capacity=settings.chunk_tokens, overlap=0, trim=False
    )


def chunk_verbatim(text: str) -> list[str]:
    """Split into non-overlapping, untrimmed token-bounded chunks whose
    concatenation reconstructs ``text`` exactly — used for saving sessions so
    load_session round-trips losslessly (empty input -> no chunks)."""
    if not text:
        return []
    return _verbatim_splitter().chunks(text)
