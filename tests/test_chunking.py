from polymnemo.chunking import chunk_text


def test_empty_returns_nothing():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_small_content_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_large_content_splits():
    chunks = chunk_text("word " * 200)  # ~1000 chars, well over the cap
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)
