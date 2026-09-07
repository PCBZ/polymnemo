from datetime import datetime, timedelta, timezone

from polymnemo.models import Memory, new_id
from polymnemo.store import InMemoryStore


def _mem(user_id="alice", namespace="shared", content="x", created_at=None):
    return Memory(
        id=new_id(),
        user_id=user_id,
        namespace=namespace,
        content=content,
        created_at=created_at,
    )


def test_add_get_count_and_tenant_isolation():
    store = InMemoryStore()
    m = _mem(content="a")
    store.add(m, [1.0, 0.0])
    assert store.count("alice", "shared") == 1
    assert store.get("alice", m.id).content == "a"
    assert store.get("bob", m.id) is None  # another user cannot read it


def test_search_ranks_by_similarity():
    store = InMemoryStore()
    a, b = _mem(content="a"), _mem(content="b")
    store.add(a, [1.0, 0.0])
    store.add(b, [0.0, 1.0])
    res = store.search("alice", "shared", [1.0, 0.0], limit=2)
    assert res[0].id == a.id
    assert res[0].score >= res[1].score


def test_list_newest_first_and_pagination():
    store = InMemoryStore()
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for i, c in enumerate(["1", "2", "3"]):
        store.add(_mem(content=c, created_at=base + timedelta(seconds=i)), [0.0, 0.0])
    page1 = store.list("alice", "shared", limit=2, offset=0)
    assert [m.content for m in page1] == ["3", "2"]  # newest first
    assert len(store.list("alice", "shared", limit=2, offset=2)) == 1


def test_update_and_delete():
    store = InMemoryStore()
    m = _mem(content="a")
    store.add(m, [1.0, 0.0])
    assert store.update("alice", m.id, "a2", [0.0, 1.0]).content == "a2"
    assert store.update("bob", m.id, "x", [0.0, 0.0]) is None  # isolation
    assert store.delete("alice", m.id) is True
    assert store.delete("alice", m.id) is False  # already gone
