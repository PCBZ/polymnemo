#!/usr/bin/env python
"""Measure what a read actually returns, in bytes (#89 / #96).

The #96 observe log reports a *computed* figure (rows x embed_dim x 4) and a
hard 0 once the column is deferred — useful as a flag, useless as a measurement.
This measures instead: it drives the real ``PostgresStore`` methods, captures the
exact SQL each one issues, and asks Postgres how many bytes that query's result
actually occupies (``sum(pg_column_size(row))``).

Both sides of the before/after comparison are therefore real numbers, and the
"after" value is not zero — it is what a read still costs once the embedding is
out of it.

Run it on main and again on the +defer branch, then diff the two JSON files.
Needs: POLYMNEMO_DATABASE_URL, python3 (no embedding model — vectors are
synthetic, since we are measuring payload size, not recall quality).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import psycopg
from sqlalchemy import event

from polymnemo.models import Memory, new_id
from polymnemo.store.postgres import PostgresStore

USER = "measure-user"


def read_cases(path: str) -> list[tuple[str, int]]:
    """Load the explicit test-case table (op, fanout) from CSV."""
    with open(path, newline="") as f:
        return [(r["op"].strip(), int(r["fanout"])) for r in csv.DictReader(f)]


def _vec(dim: int) -> list[float]:
    # Content-independent: payload size depends on the column's width, not its
    # values, so a fixed vector keeps runs comparable without an embedder.
    return [0.01] * dim


class Capture:
    """Records the SQL + bound params of SELECTs issued on an engine."""

    def __init__(self, engine) -> None:
        self.seen: list[tuple[str, object]] = []
        event.listen(engine, "before_cursor_execute", self._on)

    def _on(self, conn, cur, stmt, params, ctx, many) -> None:
        if stmt.lstrip().upper().startswith("SELECT"):
            self.seen.append((stmt, params))

    def last(self) -> tuple[str, object] | None:
        return self.seen[-1] if self.seen else None

    def clear(self) -> None:
        self.seen.clear()


def measure(dsn: str, stmt: str, params: object) -> tuple[int, int, bool]:
    """Real size and row count of what `stmt` returns, per Postgres, plus whether
    the embedding is among the returned columns.

    The column list comes from the cursor description rather than the SQL text:
    `search` names ``memories.embedding`` inside its cosine-distance expression
    even when the column itself is not selected, so substring-matching the SQL
    reports a false positive there.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT x.* FROM ({stmt}) x LIMIT 0", params)
        returns_embedding = any(d.name == "embedding" for d in cur.description or [])
        cur.execute(
            "SELECT count(*)::bigint, coalesce(sum(pg_column_size(x.*)), 0)::bigint "
            f"FROM ({stmt}) x",
            params,
        )
        rows, size = cur.fetchone()
        return int(size), int(rows), returns_embedding


def seed(store: PostgresStore, ns: str, sess: str, n: int, dim: int) -> list[str]:
    """Populate a fresh namespace with `n` rows plus a session to read back."""
    ids = []
    for i in range(n):
        m = Memory(id=new_id(), user_id=USER, namespace=ns, content=f"measure row {i}")
        store.add(m, _vec(dim))
        ids.append(m.id)
    store.replace_session(
        USER,
        sess,
        [
            Memory(
                id=new_id(),
                user_id=USER,
                namespace="sessions",
                content=f"line {i}",
                session_id=sess,
                seq=i,
            )
            for i in range(3)
        ],
        [_vec(dim) for _ in range(3)],
    )
    return ids


def run_case(store: PostgresStore, cap: Capture, op: str, n: int, ctx: dict) -> None:
    """Invoke the real store method behind `op` at fan-out `n`."""
    if op == "recall":
        store.search(USER, ctx["ns"], _vec(ctx["dim"]), limit=n)
    elif op == "list":
        store.list_memories(USER, ctx["ns"], limit=n)
    elif op == "get":
        store.get(USER, ctx["ids"][0])
    elif op == "session":
        store.get_session(USER, ctx["sess"])
    else:
        raise ValueError(f"unknown op: {op}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure real read payload bytes")
    ap.add_argument("--dsn", default=os.getenv("POLYMNEMO_DATABASE_URL"))
    ap.add_argument(
        "--cases",
        default=os.path.join(os.path.dirname(__file__), "read_payload_cases.csv"),
        help="CSV of test cases (columns: op, fanout)",
    )
    ap.add_argument("--dim", type=int, default=384, help="embedding dimension")
    ap.add_argument("--keep", action="store_true", help="don't delete the seeded rows")
    ap.add_argument("--out", default=f"read-bytes-{datetime.now():%Y%m%d-%H%M%S}.json")
    args = ap.parse_args()

    if not args.dsn:
        print("error: set --dsn or POLYMNEMO_DATABASE_URL", file=sys.stderr)
        return 2

    cases = read_cases(args.cases)
    stamp = int(time.time())
    ns, sess = f"bytes-{stamp}", f"bytes-sess-{stamp}"
    store = PostgresStore(args.dsn, shared_namespaces=[])
    cap = Capture(store._engine)

    max_fanout = max((n for op, n in cases if op in ("recall", "list")), default=1)
    print(f"1) seed {max_fanout} rows into {ns}")
    ids = seed(store, ns, sess, max_fanout, args.dim)
    ctx = {"ns": ns, "sess": sess, "ids": ids, "dim": args.dim}

    print(f"2) run {len(cases)} cases, measuring each query's real result size")
    records = []
    for op, n in cases:
        cap.clear()
        run_case(store, cap, op, n, ctx)
        got = cap.last()
        if not got:
            print(f"   {op:>8} @ {n:<3} no SELECT captured", file=sys.stderr)
            continue
        stmt, params = got
        size, rows, has_embed = measure(args.dsn, stmt, params)
        records.append(
            {
                "op": op,
                "fanout": n,
                "rows": rows,
                "returns_embedding": has_embed,
                "bytes": size,
            }
        )
        state = "with embedding" if has_embed else "deferred"
        print(f"   {op:>8} @ {n:<3} {rows:>3} rows {size:>8} B  ({state})")

    if not args.keep:
        store.delete_session(USER, sess)
        for i in ids:
            store.delete(USER, i)
    store.close()

    with open(args.out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"saved {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
