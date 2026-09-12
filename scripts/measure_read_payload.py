#!/usr/bin/env python
"""Measure the read payload the embedding column costs (#89 / #96).

Everything runs inside ONE transaction that is ROLLED BACK, so it never
persists data — safe to point at any throwaway pgvector Postgres. Do NOT point
it at production. It reports, in real bytes measured on a real database:

  * server storage  — pg_column_size(embedding) vs the whole row
  * client transfer — EXPLAIN (ANALYZE, SERIALIZE) of SELECT * vs
    SELECT <cols - embedding>, in both wire formats (text + binary)

Transfer is measured with Postgres 17's EXPLAIN (SERIALIZE): Postgres itself
reports the exact volume it serialises to send to the client — authoritative,
not a str() proxy — so this needs a pg17 server. (Production Neon can stay on
pg16; the embedding's share of the payload is version-independent.)

Run it against a local/ephemeral pgvector on pg17:

  docker run --rm -d --name pmtest -e POSTGRES_PASSWORD=pm \\
    -p 5433:5432 pgvector/pgvector:pg17
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

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from polymnemo.config import settings
from polymnemo.models import new_id
from polymnemo.store.postgres import MemoryRow, _sqlalchemy_url


def _serialize_bytes(session, select_sql: str, ns: str, fmt: str) -> int:
    """Bytes Postgres serialises to send this query's result to the client.

    PG17's ``EXPLAIN (ANALYZE, SERIALIZE <fmt>)`` runs the query and reports the
    serialised output volume (``Output Volume``, in kB) for the given wire format
    (``text`` or ``binary``) — the authoritative transfer size, not a proxy.
    """
    raw = session.execute(
        text(
            f"EXPLAIN (ANALYZE, SERIALIZE {fmt}, FORMAT JSON) "
            f"{select_sql} WHERE namespace = :ns"
        ),
        {"ns": ns},
    ).scalar()
    plan = raw if isinstance(raw, (list, dict)) else json.loads(raw)
    return int(plan[0]["Serialization"]["Output Volume"]) * 1024  # kB -> bytes


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

            # -- client transfer bytes (PG17 EXPLAIN SERIALIZE, both formats) --
            names = [c.name for c in MemoryRow.__table__.c]
            no_embed = ", ".join(c for c in names if c != "embedding")
            sel_with = "SELECT * FROM memories"
            sel_without = f"SELECT {no_embed} FROM memories"

            wire = {}
            for fmt in ("text", "binary"):
                w = _serialize_bytes(session, sel_with, ns, fmt)
                o = _serialize_bytes(session, sel_without, ns, fmt)
                wire[fmt] = {
                    "with_embedding_bytes": w,
                    "without_embedding_bytes": o,
                    "saved_bytes": w - o,
                    "saved_pct": round((w - o) / w * 100, 1) if w else 0.0,
                }

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
        # text is the primary/headline wire format (EXPLAIN's default); binary is
        # reported alongside since pgvector/psycopg can negotiate it.
        "wire": {**wire["text"], "format": "text"},
        "wire_binary": {**wire["binary"], "format": "binary"},
    }


# Designed test-case matrix (#96), anchored to real config: chunk_tokens=120
# (a ~500-char typical chunk), recall_limit=8, list_limit=20, embed_dim=384.
# Each sweep varies ONE axis so the result is a trend, not a single point.
CONTENT_SWEEP = (40, 120, 500, 1000, 2000)  # A: content chars/row (media→long)
ROWS_SWEEP = (1, 8, 20, 100, 1000)  # B: rows returned (get / recall / list / …)
A_ROWS = 20  # fix rows at list_limit while sweeping content
B_CONTENT = 500  # fix content at a typical chunk while sweeping rows


def sweep(dsn: str, a_rows: int = A_ROWS, b_content: int = B_CONTENT) -> dict:
    """Run the #96 test-case matrix: sweep content size (A) and row count (B)."""
    return {
        "meta": {
            "dim": settings.embed_dim,
            "a_rows": a_rows,
            "b_content": b_content,
            "recall_limit": 8,
            "list_limit": 20,
        },
        "content_sweep": [measure(dsn, a_rows, c) for c in CONTENT_SWEEP],
        "rows_sweep": [measure(dsn, r, b_content) for r in ROWS_SWEEP],
    }


def _print_sweep(sw: dict) -> None:
    print(f"\nSweep A — transfer vs content (rows={sw['meta']['a_rows']}):")
    for m in sw["content_sweep"]:
        print(f"  {m['content_chars']:>5}-char: saved {m['wire']['saved_pct']}%")
    print(f"\nSweep B — transfer vs rows (content={sw['meta']['b_content']}):")
    for m in sw["rows_sweep"]:
        print(f"  {m['rows']:>5} rows: saved {m['wire']['saved_bytes']:,} B")
    print()


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
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="run the #96 test-case matrix (content + rows sweeps) instead of "
        "a single measurement",
    )
    ap.add_argument("--json-out", help="also write the result JSON to this path")
    args = ap.parse_args()
    if not args.dsn:
        print(
            "error: set TEST_DATABASE_URL or pass --dsn "
            "(a throwaway pgvector DB, NOT production)",
            file=sys.stderr,
        )
        return 2

    result = (
        sweep(args.dsn)
        if args.sweep
        else measure(args.dsn, args.rows, args.content_chars)
    )
    (_print_sweep if args.sweep else _print_table)(result)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
