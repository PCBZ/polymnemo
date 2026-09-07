"""PostgresStore tests. Skipped unless TEST_DATABASE_URL points at a Postgres
with the pgvector extension and the schema applied (scripts/schema.sql)."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL (a pgvector Postgres) to run PostgresStore tests",
)

from polymnemo.models import Memory, new_id  # noqa: E402

DIM = 384


def _vec(*nonzero: tuple[int, float]) -> list[float]:
    v = [0.0] * DIM
    for i, x in nonzero:
        v[i] = x
    return v


def _mem(user_id="alice", namespace="shared", content="x") -> Memory:
    return Memory(id=new_id(), user_id=user_id, namespace=namespace, content=content)


@pytest.fixture
def store():
    # Imported here (not at module top) so the offline suite stays importable
    # without the postgres extra — the skipif only guards test functions.
    from sqlalchemy import text

    from polymnemo.store.postgres import PostgresStore

    s = PostgresStore(os.environ["TEST_DATABASE_URL"], shared_namespaces=["shared"])

    def _truncate():
        with s._engine.begin() as conn:
            conn.execute(text("TRUNCATE memories"))

    _truncate()
    yield s
    _truncate()
    s.close()


def test_add_get_count(store):
    m = _mem(content="hello")
    store.add(m, _vec((0, 1.0)))
    assert store.count("alice", "shared") == 1
    assert store.get("alice", m.id).content == "hello"


def test_search_ranks_by_cosine(store):
    a, b = _mem(content="a"), _mem(content="b")
    store.add(a, _vec((0, 1.0)))
    store.add(b, _vec((1, 1.0)))  # orthogonal to the query
    res = store.search("alice", "shared", _vec((0, 1.0)), limit=2)
    assert res[0].id == a.id
    assert res[0].score >= res[1].score


def test_list_pagination(store):
    for c in ["1", "2", "3"]:
        store.add(_mem(content=c), _vec((0, 1.0)))
    assert len(store.list("alice", "shared", limit=2, offset=0)) == 2
    assert len(store.list("alice", "shared", limit=2, offset=2)) == 1


def test_update_delete_owner_only(store):
    m = _mem(content="a")
    store.add(m, _vec((0, 1.0)))
    assert store.update("alice", m.id, "a2", _vec((1, 1.0))).content == "a2"
    assert store.update("bob", m.id, "x", _vec((0, 1.0))) is None  # not owner
    assert store.delete("bob", m.id) is False
    assert store.delete("alice", m.id) is True


def test_shared_vs_private(store):
    shared = _mem(user_id="alice", namespace="shared", content="team fact")
    private = _mem(user_id="alice", namespace="diary", content="secret")
    store.add(shared, _vec((0, 1.0)))
    store.add(private, _vec((0, 1.0)))

    # bob reads alice's shared memory, not her private one
    assert store.get("bob", shared.id).content == "team fact"
    assert store.get("bob", private.id) is None
    assert store.count("bob", "shared") == 1
    assert store.count("bob", "diary") == 0
    # writes stay owner-only, even in a shared namespace
    assert store.update("bob", shared.id, "x", _vec((0, 1.0))) is None
