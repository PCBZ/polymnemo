import os

import pytest

from polymnemo.embedding import StubEmbedder
from polymnemo.models import Memory, new_id
from polymnemo.retriever import VectorRetriever
from polymnemo.store import InMemoryStore


def test_vector_retriever_ranks_by_token_overlap():
    store, embedder = InMemoryStore(), StubEmbedder(dim=384)
    for content in ["toyota oil change", "coffee latte art", "python asyncio"]:
        m = Memory(id=new_id(), user_id="alice", namespace="shared", content=content)
        store.add(m, embedder.embed_documents([content])[0])

    retriever = VectorRetriever(store, embedder)
    res = retriever.search("alice", "car oil change", "shared", limit=3)

    assert res[0].content == "toyota oil change"  # shares tokens -> ranks top
    assert res[0].score >= res[-1].score


@pytest.mark.skipif(
    os.getenv("POLYMNEMO_TEST_REAL_EMBED") != "1",
    reason="opt-in: downloads the real multilingual embedding model",
)
def test_cross_language_semantic_recall():
    # #7 Definition of Done: recall("车") surfaces "丰田换机油" via vector
    # nearest-neighbour. Query and target share NO characters — only the real
    # multilingual embeddings bridge them (the stub bag-of-words cannot).
    # Opt in with POLYMNEMO_TEST_REAL_EMBED=1 (offline CI stays on the stub).
    from polymnemo.embedding import FastEmbedEmbedder

    store, embedder = InMemoryStore(shared_namespaces=["shared"]), FastEmbedEmbedder()
    corpus = ["丰田换机油", "咖啡拉花教程", "python asyncio 笔记", "今天天气不错"]
    for content in corpus:
        m = Memory(id=new_id(), user_id="alice", namespace="shared", content=content)
        store.add(m, embedder.embed_documents([content])[0])

    retriever = VectorRetriever(store, embedder)
    res = retriever.search("alice", "车", "shared", limit=len(corpus))

    assert res[0].content == "丰田换机油"  # nearest neighbour across languages
    assert res[0].score > res[1].score  # clearly ahead of the distractors
