#!/usr/bin/env python
"""Measure the read payload the embedding column costs (#89 / #96).

Everything runs inside ONE transaction that is ROLLED BACK, so it never
persists data — safe to point at any throwaway pgvector Postgres. Do NOT point
it at production. It reports, in real bytes measured on a real database:

  * server storage  — pg_column_size(embedding) vs the whole row
  * client transfer — SELECT * (with embedding) vs SELECT <cols - embedding>

Run it against a local/ephemeral pgvector (matches Neon's Postgres 16):

  docker run --rm -d --name pmtest -e POSTGRES_PASSWORD=pm \\
    -p 5433:5432 pgvector/pgvector:pg16
  psql postgresql://postgres:pm@localhost:5433/postgres -f scripts/schema.sql
  TEST_DATABASE_URL=postgresql://postgres:pm@localhost:5433/postgres \\
    python scripts/measure_read_payload.py --rows 200
  docker stop pmtest        # --rm -> auto-removed

The measure-read-payload workflow does exactly this in CI-on-demand and
visualises the JSON (see .github/workflows/measure-read-payload.yml).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from polymnemo.config import settings
from polymnemo.models import new_id
from polymnemo.store.postgres import MemoryRow, _sqlalchemy_url


def measure(dsn: str, rows: int, content_chars: int) -> dict:
    """Insert `rows` synthetic memories, measure the read payload, roll back."""
    dim = settings.embed_dim
    rng = random.Random(0)
    engine = create_engine(
        _sqlalchemy_url(dsn), connect_args={"prepare_threshold": None}
    )
    ns = f"_measure_{new_id()}"
    content = "x" * content_chars
    try:
        with Session(engine) as session:
            session.add_all(
                MemoryRow(
                    id=new_id(),
                    user_id="measure",
                    namespace=ns,
                    content=content,
                    embedding=[rng.uniform(-1, 1) for _ in range(dim)],
                    confirmed=True,
                )
                for _ in range(rows)
            )
            session.flush()  # visible inside the tx; never committed

            # -- server-side storage bytes (authoritative — Postgres itself) ---
            srow = session.execute(
                text(
                    "SELECT sum(pg_column_size(embedding)) AS e, "
                    "sum(pg_column_size(t.*)) AS tot, count(*) AS n "
                    "FROM memories t WHERE namespace = :ns"
                ),
                {"ns": ns},
            ).one()
            embed_store, row_store, n = int(srow.e), int(srow.tot), int(srow.n)

            # -- client transfer bytes (what psycopg materialises per read) ----
            tbl = MemoryRow.__table__
            with_rows = session.execute(select(tbl).where(tbl.c.namespace == ns)).all()
            wire_with = sum(len(str(v).encode()) for r in with_rows for v in r)

            cols = [c for c in tbl.c if c.name != "embedding"]
            without_rows = session.execute(
                select(*cols).where(tbl.c.namespace == ns)
            ).all()
            wire_without = sum(len(str(v).encode()) for r in without_rows for v in r)

            session.rollback()  # nothing persists
    finally:
        engine.dispose()

    return {
        "rows": n,
        "content_chars": content_chars,
        "dim": dim,
        "storage": {
            "embedding_bytes": embed_store,
            "row_bytes": row_store,
            "embedding_pct": round(embed_store / row_store * 100, 1),
            "per_row_embedding": round(embed_store / n),
            "per_row_total": round(row_store / n),
        },
        "wire": {
            "with_embedding_bytes": wire_with,
            "without_embedding_bytes": wire_without,
            "saved_bytes": wire_with - wire_without,
            "saved_pct": round((wire_with - wire_without) / wire_with * 100, 1),
        },
    }


def _print_table(m: dict) -> None:
    s, w = m["storage"], m["wire"]
    print(
        f"\nRead-payload measurement — {m['rows']} rows, {m['dim']}-dim, "
        f"{m['content_chars']}-char content\n"
    )
    print("Server storage (pg_column_size):")
    print(
        f"  embedding column : {s['embedding_bytes']:>12,} B  "
        f"({s['embedding_pct']}% of row, {s['per_row_embedding']:,} B/row)"
    )
    print(
        f"  whole row        : {s['row_bytes']:>12,} B  "
        f"({s['per_row_total']:,} B/row)"
    )
    print("\nClient transfer (SELECT with vs without embedding):")
    print(f"  with embedding   : {w['with_embedding_bytes']:>12,} B")
    print(f"  without embedding: {w['without_embedding_bytes']:>12,} B")
    print(f"  saved            : {w['saved_bytes']:>12,} B  ({w['saved_pct']}%)\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure read payload (#89/#96)")
    ap.add_argument(
        "--dsn",
        default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="pgvector DSN (defaults to $TEST_DATABASE_URL). Use a throwaway DB.",
    )
    ap.add_argument("--rows", type=int, default=200)
    ap.add_argument("--content-chars", type=int, default=500)
    ap.add_argument("--json-out", help="also write the result JSON to this path")
    args = ap.parse_args()
    if not args.dsn:
        print(
            "error: set TEST_DATABASE_URL or pass --dsn "
            "(a throwaway pgvector DB, NOT production)",
            file=sys.stderr,
        )
        return 2

    m = measure(args.dsn, args.rows, args.content_chars)
    _print_table(m)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(m, f, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
