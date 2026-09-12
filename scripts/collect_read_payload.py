#!/usr/bin/env python
"""Collect the real read payload via the #96 observe log — once per code state —
so the saving from deferring the embedding (#89) can be compared locally.

The store's read paths log, per read, how many rows came back and whether the
embedding column was actually fetched (with the bytes it costs). This drives the
real reads once and captures those log records into a JSON file. Run it on the
no-defer branch for the baseline, on the +defer branch for the optimized number,
then compare the two files — no CI, no workflow:

    TEST_DATABASE_URL=... python scripts/collect_read_payload.py --out before.json
    # (check out the +defer branch, same DB)
    TEST_DATABASE_URL=... python scripts/collect_read_payload.py --out after.json
    python scripts/collect_read_payload.py --compare before.json after.json

Needs a throwaway pgvector DB — it seeds rows and deletes them afterwards. Never
point it at production.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

from polymnemo.config import settings
from polymnemo.models import new_id
from polymnemo.store.postgres import MemoryRow, PostgresStore

USER = "collect"
_OBSERVE_MSG = "read %s: %d rows, embedding"  # the #96 observe log template


class _Capture(logging.Handler):
    """Capture the observe log's structured args (no string parsing)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.rows: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if str(record.msg).startswith(_OBSERVE_MSG) and record.args:
            op, n_rows, state, nbytes = record.args
            self.rows.append(
                {"op": op, "rows": n_rows, "embedding": state, "bytes": nbytes}
            )


def collect(dsn: str, rows: int, content_chars: int) -> dict:
    """Drive the real store reads once, capturing the observe log for each."""
    rng = random.Random(0)
    store = PostgresStore(dsn, shared_namespaces=["shared"])
    ns = f"_collect_{new_id()}"
    sess = f"_sess_{new_id()}"
    content = "x" * content_chars
    ids: list[str] = []

    logger = logging.getLogger("polymnemo")
    prev_level = logger.level
    cap = _Capture()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(cap)
    try:
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
                        embedding=[
                            rng.uniform(-1, 1) for _ in range(settings.embed_dim)
                        ],
                        session_id=sess,
                        seq=i,
                        confirmed=True,
                    )
                )
        qvec = [rng.uniform(-1, 1) for _ in range(settings.embed_dim)]
        store.get(USER, ids[0])
        store.search(USER, ns, qvec, limit=settings.recall_limit)
        store.list_memories(USER, ns, limit=settings.list_limit)
        store.get_session(USER, sess)
    finally:
        logger.removeHandler(cap)
        logger.setLevel(prev_level)
        with Session(store._engine) as s, s.begin():
            s.execute(delete(MemoryRow).where(MemoryRow.namespace == ns))
        store.close()

    return {
        "meta": {
            "dim": settings.embed_dim,
            "rows": rows,
            "content_chars": content_chars,
        },
        "reads": cap.rows,
    }


def compare(before: dict, after: dict) -> None:
    b = {r["op"]: r for r in before["reads"]}
    a = {r["op"]: r for r in after["reads"]}
    print(f"\nRead payload — before vs after defer ({after['meta']['dim']}-dim)\n")
    print(f"{'op':>8}  {'before':>12}  {'after':>12}  {'saved':>12}")
    total_b = total_a = 0
    for op in ("get", "search", "list", "session"):
        if op in b and op in a:
            bb, aa = int(b[op]["bytes"]), int(a[op]["bytes"])
            total_b += bb
            total_a += aa
            print(f"{op:>8}  {bb:>10,} B  {aa:>10,} B  {bb - aa:>10,} B")
    saved = total_b - total_a
    print(f"{'total':>8}  {total_b:>10,} B  {total_a:>10,} B  {saved:>10,} B\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect / compare read payload (#89/#96)")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument(
        "--dsn",
        default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="pgvector DSN (defaults to $TEST_DATABASE_URL). Use a throwaway DB.",
    )
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--content-chars", type=int, default=500)
    ap.add_argument("--out", help="write the collected JSON here")
    args = ap.parse_args()

    if args.compare:
        with open(args.compare[0]) as f:
            before = json.load(f)
        with open(args.compare[1]) as f:
            after = json.load(f)
        compare(before, after)
        return 0

    if not args.dsn:
        print(
            "error: set TEST_DATABASE_URL or pass --dsn (a throwaway pgvector DB)",
            file=sys.stderr,
        )
        return 2

    data = collect(args.dsn, args.rows, args.content_chars)
    for r in data["reads"]:
        print(
            f"  {r['op']:>8}: {r['rows']} rows, embedding {r['embedding']} "
            f"(~{r['bytes']:,} bytes)"
        )
    if args.out:
        with open(args.out, "w") as f:
            json.dump(data, f, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
