import os

import pytest

from polymnemo.chunking import chunk_text, chunk_verbatim


def test_empty_returns_nothing():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_small_content_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_large_content_splits():
    chunks = chunk_text("word " * 200)  # ~1000 chars, well over the cap
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)


def test_verbatim_reassembles_exactly():
    text = "A\n\n  B with spaces\tand a tab.\nC 中文 内容 " * 40
    chunks = chunk_verbatim(text)
    assert len(chunks) > 1
    assert "".join(chunks) == text  # lossless for save/load session
    assert chunk_verbatim("") == []


@pytest.mark.skipif(
    os.getenv("POLYMNEMO_TEST_REAL_TOKENIZER") != "1",
    reason="opt-in: loads the real HF tokenizer (network / model download)",
)
def test_verbatim_reassembles_exactly_with_real_tokenizer(monkeypatch):
    # The lossless guarantee matters most on the *production* token splitter, not
    # just the offline stub char splitter. Opt in with POLYMNEMO_TEST_REAL_TOKENIZER=1.
    from polymnemo import chunking
    from polymnemo.config import settings

    def reset():
        chunking._tokenizer.cache_clear()
        chunking._splitter.cache_clear()
        chunking._verbatim_splitter.cache_clear()

    monkeypatch.setattr(settings, "embed_backend", "fastembed")
    reset()  # drop any stub-built splitters cached by earlier tests
    try:
        text = "A\n\n  B with spaces\tand a tab.\nC 中文 内容 " * 40
        chunks = chunking.chunk_verbatim(text)
        assert len(chunks) > 1
        assert "".join(chunks) == text
    finally:
        reset()  # don't leak the real splitter into other tests
