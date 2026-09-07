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
