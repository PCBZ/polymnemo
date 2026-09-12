#!/usr/bin/env python
"""Measure the read payload of the REAL PostgresStore read methods (#89 / #96).

This drives the actual store methods — ``get`` / ``search`` / ``list_memories`` /
``get_session`` — at their real default limits, captures the exact SQL each one
emits, and measures the bytes Postgres serialises to send back with PG17's
``EXPLAIN (ANALYZE, SERIALIZE)`` (text + binary wire formats). It also reports
server-side storage via ``pg_column_size``.

It measures whatever the checked-out store code does: run it on the no-defer
code (before #89) for the baseline, and on the defer code (after #89) for the
optimized number, then compare the two JSONs with plot_read_payload.py. The
JSON self-labels which state it measured via ``meta.reads_fetch_embedding``.

Needs a real pg17 + pgvector server (EXPLAIN SERIALIZE is PG17). Point it at a
THROWAWAY database — it inserts synthetic rows (committed, so the store's own
sessions can read them) and deletes them afterwards. NEVER production.

    docker run --rm -d --name pmtest -e POSTGRES_PASSWORD=pm \\
      -p 5433:5432 pgvector/pgvector:pg17
    psql postgresql://postgres:pm@localhost:5433/postgres -f scripts/schema.sql
    TEST_DATABASE_URL=postgresql://postgres:pm@localhost:5433/postgres \\
      python scripts/measure_read_payload.py --json-out run.json
    docker stop pmtest
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

from sqlalchemy import delete, event, text
from sqlalchemy.orm import Session

from polymnemo.config import settings
from polymnemo.models import new_id
from polymnemo.store.postgres import MemoryRow, PostgresStore

USER = "measure"


def _serialize_bytes(conn, sql: str, params, fmt: str) -> int:
    """Bytes Postgres serialises to send this query's result to the client.

    PG17 ``EXPLAIN (ANALYZE, SERIALIZE <fmt>)`` runs the query and reports the
    serialised ``Output Volume`` (in kB) for the given wire format.
    """
    raw = conn.exec_driver_sql(
        f"EXPLAIN (ANALYZE, SERIALIZE {fmt}, FORMAT JSON) {sql}", params
    ).scalar()
    plan = raw if isinstance(raw, (list, dict)) else json.loads(raw)
    return int(plan[0]["Serialization"]["Output Volume"]) * 1024  # kB -> bytes


def measure(dsn: str, rows: int, content_chars: int) -> dict:
    """Drive the real store reads and measure the payload each one transfers."""
    dim = settings.embed_dim
    rng = random.Random(0)
    store = PostgresStore(dsn, shared_namespaces=["shared"])
    ns = f"_measure_{new_id()}"
    sess = f"_sess_{new_id()}"
    content = "x" * content_chars
    ids: list[str] = []

    try:
        # Commit synthetic rows so the store's own (separate) sessions see them.
        with Session(store._engine) as s, s.begin():
            for i in range(rows):
                mid = new_id()
                ids.append(mid)
                s.add(
                    MemoryRow(
                        id=mid,
                        user_id=USER,
                        namespace=ns,
                        content=content,
                        embedding=[rng.uniform(-1, 1) for _ in range(dim)],
                        session_id=sess,
                        seq=i,
                        confirmed=True,
                    )
                )

        qvec = [rng.uniform(-1, 1) for _ in range(dim)]
        ops = {
            "get": lambda: store.get(USER, ids[0]),
            "recall": lambda: store.search(USER, ns, qvec, limit=settings.recall_limit),
            "list": lambda: store.list_memories(USER, ns, limit=settings.list_limit),
            "session": lambda: store.get_session(USER, sess),
        }

        # Capture the exact SELECT each real read method emits.
        captured: dict[str, tuple[str, object]] = {}
        current: str | None = None

        def _cap(conn, cursor, statement, parameters, context, executemany):
            if current and statement.lstrip().upper().startswith("SELECT"):
                captured.setdefault(current, (statement, parameters))

        event.listen(store._engine, "before_cursor_execute", _cap)
        try:
            for name, fn in ops.items():
                current = name
                fn()
                current = None
        finally:
            event.remove(store._engine, "before_cursor_execute", _cap)

        # EXPLAIN SERIALIZE each captured read, both wire formats.
        reads: dict[str, dict[str, int]] = {}
        with store._engine.connect() as conn:
            for op, (sql, params) in captured.items():
                reads[op] = {
                    fmt: _serialize_bytes(conn, sql, params, fmt)
                    for fmt in ("text", "binary")
                }

            # Server-side storage (pg_column_size), authoritative.
            srow = conn.execute(
                text(
                    "SELECT sum(pg_column_size(embedding)) AS e, "
                    "sum(pg_column_size(t.*)) AS tot, count(*) AS n "
                    "FROM memories t WHERE namespace = :ns"
                ),
                {"ns": ns},
            ).one()
            embed_store, row_store, n = int(srow.e), int(srow.tot), int(srow.n)

        reads_fetch_embedding = any(
            "embedding" in sql.lower() for sql, _ in captured.values()
        )
    finally:
        # Ephemeral DB, but tidy up our namespace regardless.
        with Session(store._engine) as s, s.begin():
            s.execute(delete(MemoryRow).where(MemoryRow.namespace == ns))
        store.close()

    return {
        "meta": {
            "dim": dim,
            "rows": rows,
            "content_chars": content_chars,
            "recall_limit": settings.recall_limit,
            "list_limit": settings.list_limit,
            # True on the pre-#89 (no-defer) code, False once reads defer it.
            "reads_fetch_embedding": reads_fetch_embedding,
        },
        "reads": reads,
        "storage": {
            "embedding_bytes": embed_store,
            "row_bytes": row_store,
            "embedding_pct": round(embed_store / row_store * 100, 1),
            "per_row_embedding": round(embed_store / n),
            "per_row_total": round(row_store / n),
        },
    }


def _print(m: dict) -> None:
    state = (
        "fetches embedding"
        if m["meta"]["reads_fetch_embedding"]
        else "defers embedding"
    )
    print(
        f"\nRead payload — {m['meta']['rows']} rows, {m['meta']['dim']}-dim, "
        f"{m['meta']['content_chars']}-char content · reads {state}\n"
    )
    print("Per-read transfer (EXPLAIN SERIALIZE, text / binary):")
    for op, w in m["reads"].items():
        print(f"  {op:>8}: {w['text']:>10,} B text · {w['binary']:>10,} B binary")
    s = m["storage"]
    print(
        f"\nStorage: embedding {s['embedding_bytes']:,} B "
        f"({s['embedding_pct']}% of row)\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure real read payload (#89/#96)")
    ap.add_argument(
        "--dsn",
        default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="pg17 pgvector DSN (defaults to $TEST_DATABASE_URL). Use a throwaway DB.",
    )
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--content-chars", type=int, default=500)
    ap.add_argument("--json-out", help="write the result JSON to this path")
    args = ap.parse_args()
    if not args.dsn:
        print(
            "error: set TEST_DATABASE_URL or pass --dsn "
            "(a throwaway pg17 pgvector DB, NOT production)",
            file=sys.stderr,
        )
        return 2

    m = measure(args.dsn, args.rows, args.content_chars)
    _print(m)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(m, f, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
