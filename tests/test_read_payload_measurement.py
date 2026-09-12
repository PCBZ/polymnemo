"""#96: measure, on a real pgvector DB, how many bytes the embedding column
costs on read paths.

This is a *measurement*, not a synthetic estimate, so it needs a real database
(DB-gated, like the PostgresStore tests). ``scripts/measure_read_payload.py``
holds the logic; the measure-read-payload workflow runs it against an ephemeral
pgvector service container (never production) and visualises the numbers.

Run locally against a throwaway pgvector:

    docker run --rm -d --name pmtest -e POSTGRES_PASSWORD=pm \\
        -p 5433:5432 pgvector/pgvector:pg16
    psql postgresql://postgres:pm@localhost:5433/postgres -f scripts/schema.sql
    TEST_DATABASE_URL=postgresql://postgres:pm@localhost:5433/postgres \\
        pytest tests/test_read_payload_measurement.py
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="set TEST_DATABASE_URL (a throwaway pgvector Postgres) to measure",
)


def test_measure_read_payload_quantifies_saving():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    from measure_read_payload import measure

    m = measure(os.environ["TEST_DATABASE_URL"], rows=50, content_chars=300)

    # embedding dominates both the stored row and the wire payload
    assert m["storage"]["embedding_pct"] > 50
    assert m["wire"]["without_embedding_bytes"] < m["wire"]["with_embedding_bytes"]
    assert m["wire"]["saved_pct"] > 50
