#!/usr/bin/env python
"""Drive the real store reads with the #96 observe log on, so each read's
payload lands on stdout — the log line IS the measurement. Run it once per code
state and just read (or diff) the two logs — no capture, no JSON, no CI:

    TEST_DATABASE_URL=... python scripts/collect_read_payload.py > before.log  # no-defer branch
    # check out the +defer branch (#103), same DB:
    TEST_DATABASE_URL=... python scripts/collect_read_payload.py > after.log
    diff before.log after.log

Before defer the lines read `embedding fetched (~N bytes)`; after, `deferred
(~0 bytes)`. Needs a throwaway pgvector DB — it seeds rows and deletes them
afterwards. Never point it at production.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Log the real read payload (#89/#96)")
    ap.add_argument(
        "--dsn",
        default=os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL"),
        help="pgvector DSN (defaults to $TEST_DATABASE_URL). Use a throwaway DB.",
    )
    ap.add_argument("--rows", type=int, default=50)
    ap.add_argument("--content-chars", type=int, default=500)
    args = ap.parse_args()
    if not args.dsn:
        print(
            "error: set TEST_DATABASE_URL or pass --dsn (a throwaway pgvector DB)",
            file=sys.stderr,
        )
        return 2

    # Land only the #96 observe log on stdout (no root-logger noise).
    logger = logging.getLogger("polymnemo")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    rng = random.Random(0)
    store = PostgresStore(args.dsn, shared_namespaces=["shared"])
    ns = f"_collect_{new_id()}"
    sess = f"_sess_{new_id()}"
    content = "x" * args.content_chars
    ids: list[str] = []
    try:
        with Session(store._engine) as s, s.begin():
            for i in range(args.rows):
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
        with Session(store._engine) as s, s.begin():
            s.execute(delete(MemoryRow).where(MemoryRow.namespace == ns))
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
