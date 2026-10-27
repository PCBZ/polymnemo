"""PostgresStore tests. Skipped unless TEST_DATABASE_URL points at a Postgres
with the pgvector extension and the schema applied (scripts/schema.sql)."""

import os
from contextlib import contextmanager

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


# --- #169: the filter runs after the HNSW scan ------------------------------
# pgvector collects ~hnsw.ef_search candidates by distance and only then applies
# WHERE, so a sparse namespace can come back short -- rows that never entered
# the candidate set rather than rows that ranked low. These drive the database
# directly, because the behaviour being tested is the index's, not ours.

NOISE_ROWS = 200
TARGET_ROWS = 5
QUERY = _vec((0, 1.0))


def _seed_crowded(store):
    """A crowded namespace nearer the query than the one being searched.

    The near rows are what fills the candidate set; the far rows are what the
    search should still find. Both are far enough apart that the ordering is
    not a matter of floating-point luck.
    """
    from sqlalchemy import text

    rows = []
    for i in range(NOISE_ROWS):
        # Nearly identical to QUERY: these crowd out everything else.
        v = [0.0] * DIM
        v[0], v[1] = 1.0, 0.0001 * (i + 1)
        rows.append((new_id(), "alice", "noise", f"noise {i}", v))
    for i in range(TARGET_ROWS):
        # Clearly farther, but the only rows in the namespace we search.
        v = [0.0] * DIM
        v[0], v[1] = 0.6, 0.8
        v[2] = 0.001 * (i + 1)
        rows.append((new_id(), "alice", "shared", f"target {i}", v))

    with store._engine.begin() as conn:
        for rid, uid, ns, content, vec in rows:
            conn.execute(
                text(
                    "INSERT INTO memories (id, user_id, namespace, content, "
                    "embedding, confirmed) VALUES (:id, :u, :ns, :c, :e, true)"
                ),
                {"id": rid, "u": uid, "ns": ns, "c": content, "e": str(vec)},
            )
        conn.execute(text("ANALYZE memories"))


@contextmanager
def _hnsw_only(store):
    """Yield a connection where HNSW is the only way to answer the query.

    Postgres will not otherwise use it here, and is right not to: with
    `namespace = 'shared'` matching a handful of rows, the B-tree on namespace
    plus an exact sort beats walking a graph. That is the planner protecting us
    -- at this size and selectivity the under-return does not happen at all. It
    stops protecting us once a namespace is large enough that the vector index
    wins on cost, which is the state this reproduces.

    `connect()`, not `begin()`: the latter COMMITS on a clean exit, so the
    dropped indexes would not come back and every later test would fail on a
    missing index. Closing an uncommitted connection rolls the DDL back.
    """
    from sqlalchemy import text

    with store._engine.connect() as conn:
        conn.execute(text("DROP INDEX memories_namespace_idx"))
        conn.execute(text("DROP INDEX memories_user_namespace_idx"))
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        yield conn
        conn.rollback()  # explicit: the indexes are restored here


def _search_sql(conn, *, iterative: str, ef_search: int = 4):
    """The store's query shape, run with the scan settings under test."""
    from sqlalchemy import text

    conn.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
    conn.execute(text(f"SET LOCAL hnsw.iterative_scan = {iterative}"))
    return conn.execute(
        text(
            "SELECT id FROM memories WHERE namespace = 'shared' AND confirmed "
            "ORDER BY embedding <=> :q LIMIT :k"
        ),
        {"q": str(QUERY), "k": TARGET_ROWS},
    ).all()


class TestASparseNamespaceDoesNotUnderReturn:
    def test_the_hnsw_index_is_actually_used(self, store):
        """Guards every assertion below. On a sequential scan the filter and the
        ordering do not compete, so the rest would pass while testing nothing."""
        from sqlalchemy import text

        _seed_crowded(store)
        with _hnsw_only(store) as conn:
            plan = "\n".join(
                r[0]
                for r in conn.execute(
                    text(
                        "EXPLAIN SELECT id FROM memories WHERE namespace = 'shared' "
                        "AND confirmed ORDER BY embedding <=> :q LIMIT 5"
                    ),
                    {"q": str(QUERY)},
                ).all()
            )
        assert "memories_embedding_hnsw_idx" in plan, plan

    def test_without_iterative_scan_the_search_comes_up_short(self, store):
        """The bug, demonstrated. Without this the fix below proves nothing:
        a test that passes either way is not evidence."""
        _seed_crowded(store)
        with _hnsw_only(store) as conn:
            rows = _search_sql(conn, iterative="off")
        assert len(rows) < TARGET_ROWS, (
            f"expected the filter to starve the candidate set, got {len(rows)} "
            f"of {TARGET_ROWS} -- the premise of #169 no longer holds here"
        )

    def test_with_iterative_scan_every_match_comes_back(self, store):
        _seed_crowded(store)
        with _hnsw_only(store) as conn:
            rows = _search_sql(conn, iterative="strict_order")
        assert len(rows) == TARGET_ROWS

    def test_the_store_returns_every_match(self, store):
        """End to end. This cannot force the plan -- the store opens its own
        session -- so at this table size it passes whichever index is used. It
        guards the wiring, not the recall: that is the raw-query tests above."""
        _seed_crowded(store)
        found = store.search("alice", "shared", QUERY, limit=TARGET_ROWS)
        assert len(found) == TARGET_ROWS
        assert all(m.namespace == "shared" for m in found)


def _capture(store):
    """Record every statement the engine sends, in order, until stopped."""
    from sqlalchemy import event

    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement.strip())

    event.listen(store._engine, "before_cursor_execute", record)

    def stop():
        event.remove(store._engine, "before_cursor_execute", record)
        return seen

    return stop


def _is_iterative_set(stmt: str) -> bool:
    return stmt.upper().startswith("SET LOCAL HNSW.ITERATIVE_SCAN")


class TestTheSettingIsPerTransaction:
    """The app connects through Neon's pooled endpoint: PgBouncer in transaction
    mode, where Neon documents session-level SET as unsupported because a
    connection returns to the pool after every transaction. So the setting has
    to be made INSIDE the search's own transaction.

    These run against a direct connection, which cannot reproduce the pooler.
    What they CAN pin is the shape that survives one: SET LOCAL, in the same
    transaction as the query, ahead of it, leaking nothing afterwards."""

    def test_it_is_set_before_the_query_in_the_same_transaction(self, store):
        _add(store, "orion")
        stop = _capture(store)
        store.search("alice", "shared", QUERY, limit=5)
        statements = stop()

        set_at = next(i for i, s in enumerate(statements) if _is_iterative_set(s))
        query_at = next(
            i
            for i, s in enumerate(statements)
            if s.upper().startswith("SELECT") and "FROM MEMORIES" in s.upper()
        )
        assert set_at < query_at, statements
        assert not any(s.upper() == "COMMIT" for s in statements[: query_at + 1]), (
            "committed between the SET and the query, which would end the "
            "transaction SET LOCAL is scoped to"
        )

    def test_it_does_not_outlive_the_search(self):
        """pool_size=1, so the next checkout is provably the same connection. A
        session-level SET would still be there; SET LOCAL must not be."""
        from sqlalchemy import text

        from polymnemo.store.postgres import PostgresStore

        s = PostgresStore(
            os.environ["TEST_DATABASE_URL"], shared_namespaces=["shared"], pool_size=1
        )
        try:
            s.search("alice", "shared", QUERY, limit=5)
            with s._engine.connect() as conn:
                value = conn.execute(
                    text("SELECT current_setting('hnsw.iterative_scan', true)")
                ).scalar_one()
            assert value != "strict_order", "leaked past the transaction"
        finally:
            s.close()

    def test_every_search_sets_it_and_the_version_is_read_only_once(self, store):
        _add(store, "orion")
        stop = _capture(store)
        for _ in range(3):
            store.search("alice", "shared", QUERY, limit=5)
        statements = stop()

        assert sum(_is_iterative_set(s) for s in statements) == 3
        probes = [s for s in statements if "pg_extension" in s]
        assert len(probes) == 1, probes

    def test_keyword_search_does_not_pay_for_it(self, store):
        """No HNSW scan is involved, so the extra round trip would be waste."""
        _add(store, "orion")
        stop = _capture(store)
        store.search_text("alice", "shared", "orion", 5)
        assert not any(_is_iterative_set(s) for s in stop())


class TestAnOlderPgvectorIsReportedNotAssumed:
    """Postgres accepts a SET for ANY two-part name as a placeholder, so on
    pgvector < 0.8 the statement succeeds and does nothing. Success of the SET
    is therefore not evidence of support, and the version has to be read."""

    def test_the_installed_version_is_readable(self, store):
        from sqlalchemy.orm import Session

        from polymnemo.store.postgres import _MIN_PGVECTOR, _pgvector_version

        with Session(store._engine) as session:
            version = _pgvector_version(session)
        assert version is not None, "pgvector is not installed"
        assert version[:2] >= _MIN_PGVECTOR, (
            f"this test database has pgvector {version}, older than 0.8: the "
            "iterative-scan tests above cannot pass on it"
        )

    def test_a_placeholder_set_succeeds_without_proving_support(self, store):
        """The premise, shown rather than quoted: an unknown two-part name is
        accepted. If this ever raises, the version check is merely redundant."""
        from sqlalchemy import text

        with store._engine.connect() as conn:
            conn.execute(text("SET nonexistent_ext.some_option = 'x'"))
            value = conn.execute(text("SHOW nonexistent_ext.some_option")).scalar_one()
            assert value == "x"
            conn.rollback()

    def test_an_old_version_warns_once_and_never_sets(self, monkeypatch, caplog):
        """pgvector is 0.8+ here, so the version is faked: what is under test is
        what the store DOES with an old one, not how to install one."""
        import logging

        from polymnemo.store import postgres as pg

        monkeypatch.setattr(pg, "_pgvector_version", lambda session: (0, 7, 4))
        monkeypatch.setattr(pg, "_WARNED_NO_ITERATIVE_SCAN", False)

        s = pg.PostgresStore(
            os.environ["TEST_DATABASE_URL"], shared_namespaces=["shared"]
        )
        stop = _capture(s)
        try:
            with caplog.at_level(logging.WARNING, logger="polymnemo"):
                for _ in range(3):
                    s.search("alice", "shared", QUERY, limit=5)
        finally:
            statements = stop()
            s.close()

        assert not any(_is_iterative_set(x) for x in statements), "set on old pgvector"
        warnings = [r for r in caplog.records if "iterative_scan" in r.getMessage()]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "0.7.4" in warnings[0].getMessage()

    def test_a_failed_probe_does_not_break_the_search(self, monkeypatch):
        """An optimisation must not become an outage: if reading the version
        fails, the search still runs, just without iterative scan."""
        from polymnemo.store import postgres as pg

        def boom(session):
            raise RuntimeError("catalog unreadable")

        monkeypatch.setattr(pg, "_pgvector_version", boom)
        s = pg.PostgresStore(
            os.environ["TEST_DATABASE_URL"], shared_namespaces=["shared"]
        )
        try:
            _add(s, "orion")
            assert len(s.search("alice", "shared", QUERY, limit=5)) == 1
            assert s._iterative_scan_ok is None, "a transient error was cached"
        finally:
            s.close()


# --- #17: keyword search -----------------------------------------------------
# Exact, case-insensitive substring match, every term required. These pin WHICH
# rows match, which must not depend on the trigram index: it only accelerates.


def _add(store, content, **kw):
    m = _mem(content=content, **kw)
    store.add(m, _vec((0, 1.0)))
    return m


class TestKeywordSearch:
    def test_an_exact_string_is_found_and_only_it(self, store):
        hit = _add(store, "deploy failed on order 88312")
        _add(store, "unrelated note")
        found = store.search_text("alice", "shared", "88312", 10)
        assert [m.id for m in found] == [hit.id]

    def test_matching_ignores_case(self, store):
        _add(store, "Project ORION kickoff")
        assert store.search_text("alice", "shared", "orion", 10)

    def test_every_term_is_required(self, store):
        both = _add(store, "orion kickoff")
        _add(store, "orion")
        _add(store, "kickoff")
        found = store.search_text("alice", "shared", "orion kickoff", 10)
        assert [m.id for m in found] == [both.id]

    def test_a_term_that_is_absent_matches_nothing(self, store):
        _add(store, "I prefer dark roast coffee")
        assert store.search_text("alice", "shared", "tea", 10) == []

    def test_an_id_inside_punctuation_is_found(self, store):
        """Why keyword mode is substring rather than tokens."""
        wanted = _add(store, "request failed: order_id=88312&retry=3")
        _add(store, "request failed: order_id=99999&retry=3")
        found = store.search_text("alice", "shared", "88312", 10)
        assert [m.id for m in found] == [wanted.id]

    @pytest.mark.parametrize(
        "needle,hit,miss",
        [
            ("100%", "100% done", "1000 done"),
            ("a_b", "id a_b here", "id axb here"),
            ("a\\b", "path a\\b end", "path ab end"),
        ],
    )
    def test_metacharacters_match_literally(self, store, needle, hit, miss):
        """Unescaped, `a_b` is a wildcard and `100%` matches everything."""
        wanted = _add(store, hit)
        _add(store, miss)
        found = store.search_text("alice", "shared", needle, 10)
        assert [m.id for m in found] == [wanted.id]

    def test_another_namespace_is_not_searched(self, store):
        _add(store, "orion", namespace="elsewhere")
        assert store.search_text("alice", "shared", "orion", 10) == []

    def test_a_private_namespace_is_invisible_to_other_users(self, store):
        _add(store, "orion", user_id="alice", namespace="private")
        assert store.search_text("bob", "private", "orion", 10) == []
        assert store.search_text("alice", "private", "orion", 10)

    def test_a_shared_namespace_is_visible_to_everyone(self, store):
        _add(store, "orion", user_id="alice", namespace="shared")
        assert store.search_text("bob", "shared", "orion", 10)

    def test_an_unconfirmed_media_memory_is_hidden(self, store):
        m = Memory(
            id=new_id(),
            user_id="alice",
            namespace="shared",
            content="orion photo",
            confirmed=False,
        )
        store.add(m, _vec((0, 1.0)))
        assert store.search_text("alice", "shared", "orion", 10) == []

    def test_results_are_sliced_by_offset_and_limit(self, store):
        for i in range(5):
            _add(store, f"orion {i}")
        p1 = store.search_text("alice", "shared", "orion", 2, 0)
        p2 = store.search_text("alice", "shared", "orion", 2, 2)
        assert len(p1) == len(p2) == 2
        assert {m.id for m in p1}.isdisjoint({m.id for m in p2})

    def test_hits_carry_a_numeric_score(self, store):
        """similarity() must exist, which means pg_trgm is installed."""
        _add(store, "orion")
        assert isinstance(
            store.search_text("alice", "shared", "orion", 10)[0].score, float
        )

    def test_a_tighter_match_ranks_first(self, store):
        """similarity() favours a chunk the query dominates over one it is lost
        in. word_similarity() does not -- it scores the best-matching part, so
        both chunks read 1.0 and recency decided, which is what CI showed."""
        short = _add(store, "orion")
        _add(store, "orion " + "padding " * 30)
        assert store.search_text("alice", "shared", "orion", 10)[0].id == short.id

    def test_an_empty_query_matches_nothing(self, store):
        _add(store, "orion")
        assert store.search_text("alice", "shared", "   ", 10) == []


class TestTheTrigramIndexIsReal:
    def test_the_extension_and_index_exist(self, store):
        from sqlalchemy import text

        with store._engine.connect() as conn:
            ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).first()
            idx = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE tablename = 'memories' "
                    "AND indexname = 'memories_content_trgm_idx'"
                )
            ).first()
        assert ext is not None, "pg_trgm is not installed -- is schema.sql applied?"
        assert idx is not None

    def test_a_longer_ascii_term_uses_it(self, store):
        """Guard, as in #170: on a sequential scan the index is irrelevant and
        every other assertion could pass while it does nothing."""
        from sqlalchemy import text

        for i in range(20):
            _add(store, f"orion note {i}")
        with store._engine.connect() as conn:
            conn.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join(
                r[0]
                for r in conn.execute(
                    text(
                        "EXPLAIN SELECT id FROM memories WHERE content ILIKE '%orion%'"
                    )
                ).all()
            )
            conn.rollback()
        assert "memories_content_trgm_idx" in plan, plan
