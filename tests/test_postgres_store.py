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
    assert len(store.list_memories("alice", "shared", limit=2, offset=0)) == 2
    assert len(store.list_memories("alice", "shared", limit=2, offset=2)) == 1


def test_update_delete_owner_only(store):
    m = _mem(content="a")
    store.add(m, _vec((0, 1.0)))
    assert store.update("alice", m.id, "a2", _vec((1, 1.0))).content == "a2"
    assert store.update("bob", m.id, "x", _vec((0, 1.0))) is None  # not owner
    assert store.delete("bob", m.id) is False
    assert store.delete("alice", m.id) is True


def test_session_ordered_scoped_and_replaceable(store):
    def add_chunk(session_id, seq, content, user_id="alice"):
        m = Memory(
            id=new_id(),
            user_id=user_id,
            namespace="shared",
            content=content,
            session_id=session_id,
            seq=seq,
        )
        store.add(m, _vec((0, 1.0)))

    add_chunk("s", 1, "world")
    add_chunk("s", 0, "hello ")
    rows = store.get_session("alice", "s")
    assert [r.content for r in rows] == ["hello ", "world"]  # ordered by seq
    assert store.get_session("bob", "s") == []  # user-scoped
    assert store.delete_session("alice", "s") == 2
    assert store.get_session("alice", "s") == []


def test_replace_session_swaps_whole_session(store):
    def session(*contents):
        return [
            Memory(
                id=new_id(),
                user_id="alice",
                namespace="sessions",
                content=c,
                session_id="s",
                seq=i,
            )
            for i, c in enumerate(contents)
        ]

    old = session("old-0 ", "old-1")
    store.replace_session("alice", "s", old, [_vec((0, 1.0))] * len(old))
    assert [r.content for r in store.get_session("alice", "s")] == ["old-0 ", "old-1"]

    # replacing with fewer/more chunks leaves no stragglers from the old set
    new = session("new-0 ", "new-1 ", "new-2")
    store.replace_session("alice", "s", new, [_vec((0, 1.0))] * len(new))
    rows = store.get_session("alice", "s")
    assert [r.content for r in rows] == ["new-0 ", "new-1 ", "new-2"]


def test_media_memory_round_trips(store):
    m = Memory(
        id=new_id(),
        user_id="alice",
        namespace="shared",
        content="a photo of my cat",
        kind="image",
        object_key="alice/xyz/cat.png",
        content_type="image/png",
        size_bytes=1234,
    )
    store.add(m, _vec((0, 1.0)))
    got = store.get("alice", m.id)
    assert got.kind == "image"
    assert got.object_key == "alice/xyz/cat.png"
    assert got.content_type == "image/png"
    assert got.size_bytes == 1234
    assert got.to_public()["kind"] == "image"


def test_unconfirmed_media_hidden_until_confirmed(store):
    m = Memory(
        id=new_id(),
        user_id="alice",
        namespace="media",
        content="a cat photo",
        kind="image",
        object_key="alice/x/cat.png",
        content_type="image/png",
        confirmed=False,
    )
    store.add(m, _vec((0, 1.0)))
    # hidden from search / list / count while unconfirmed...
    assert store.count("alice", "media") == 0
    assert store.list_memories("alice", "media", limit=5) == []
    assert store.search("alice", "media", _vec((0, 1.0)), limit=5) == []
    # ...but fetchable by id (needed to confirm)
    assert store.get("alice", m.id) is not None

    store.confirm_media("alice", m.id, 999, "etag123")
    assert store.count("alice", "media") == 1
    got = store.get("alice", m.id)
    assert got.confirmed and got.size_bytes == 999 and got.checksum == "etag123"


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


def test_reads_defer_embedding(store):
    """#89: compare both states on the real read path.

    AFTER (this branch): the real reads (get / list) no longer SELECT the
    embedding column. BEFORE (an un-deferred SELECT): the row still loads it.
    """
    from sqlalchemy import event, select
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.orm import Session

    from polymnemo.store.postgres import MemoryRow

    store.add(_mem(content="hello"), _vec((0, 1.0)))

    selects: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(store._engine, "before_cursor_execute", _capture)
    try:
        store.get("alice", store.list_memories("alice", "shared", limit=1)[0].id)
        store.list_memories("alice", "shared", limit=10)
    finally:
        event.remove(store._engine, "before_cursor_execute", _capture)

    # AFTER: no read SELECT includes the embedding column.
    assert selects
    assert all("embedding" not in s.lower() for s in selects), selects

    # BEFORE: an un-deferred SELECT still carries the vector.
    with Session(store._engine) as session:
        row = session.execute(select(MemoryRow).limit(1)).scalar_one()
        assert "embedding" not in sa_inspect(row).unloaded  # loaded == fetched
