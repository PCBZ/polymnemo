"""Durable store on Postgres + pgvector (Neon in production), via SQLAlchemy.

Mirrors the shared/private rules of ``InMemoryStore`` (#14): a read is visible if
the caller owns the row OR it lives in a shared namespace; writes are
owner-scoped and atomic (``UPDATE/DELETE ... WHERE id AND user_id``).

The table/extension/index are provisioned by ``scripts/schema.sql`` (pgvector
DDL is clearest as SQL); ``MemoryRow`` is the query-layer mapping of that table.

This module imports SQLAlchemy / pgvector at import time, so it is imported
lazily by ``context`` only when a database is configured — the base install
(in-memory only) never touches it. Install the ``postgres`` extra to use it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Text,
    create_engine,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, defer, mapped_column

from ..config import settings
from ..models import Memory
from .text import keyword_terms, like_escape

logger = logging.getLogger("polymnemo")


def _observe(op: str, rows: Sequence[object]) -> None:
    """Log a read's payload (#96): how many rows came back and whether the
    embedding column was fetched, with the bytes it (would) cost. This makes the
    embedding's read-path cost — and the saving once reads defer it (#89) —
    visible in a live deployment.

    DEBUG level — enable DEBUG on the ``polymnemo`` logger to land these lines;
    ``logger.debug`` itself skips formatting/emitting when DEBUG is off.
    """
    # `embedding` is in a row's unloaded set exactly when it was deferred (not
    # fetched). Reading `.unloaded` does not trigger a load.
    fetched = bool(rows) and "embedding" not in sa_inspect(rows[0]).unloaded  # type: ignore[union-attr]  # ORM instance -> InstanceState
    embed_bytes = len(rows) * settings.embed_dim * 4 if fetched else 0
    logger.debug(
        "read %s: %d rows, embedding %s (~%d bytes)",
        op,
        len(rows),
        "fetched" if fetched else "deferred",
        embed_bytes,
    )


class Base(DeclarativeBase):
    pass


class MemoryRow(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    namespace: Mapped[str] = mapped_column(index=True)
    content: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embed_dim))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    source: Mapped[str | None] = mapped_column(default=None)
    session_id: Mapped[str | None] = mapped_column(default=None, index=True)
    seq: Mapped[int | None] = mapped_column(default=None)
    kind: Mapped[str] = mapped_column(default="text")
    object_key: Mapped[str | None] = mapped_column(default=None)
    content_type: Mapped[str | None] = mapped_column(default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    checksum: Mapped[str | None] = mapped_column(default=None)
    confirmed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def to_memory(self, score: float | None = None) -> Memory:
        return Memory(
            id=self.id,
            user_id=self.user_id,
            namespace=self.namespace,
            content=self.content,
            tags=list(self.tags or []),
            source=self.source,
            session_id=self.session_id,
            seq=self.seq,
            kind=self.kind,
            object_key=self.object_key,
            content_type=self.content_type,
            size_bytes=self.size_bytes,
            checksum=self.checksum,
            confirmed=self.confirmed,
            created_at=self.created_at,
            updated_at=self.updated_at,
            score=score,
        )


# Warn once rather than per search: a deployment on an older pgvector should
# know its filtered searches can come up short, without a line per request.
_WARNED_NO_ITERATIVE_SCAN = False

# hnsw.iterative_scan arrived in pgvector 0.8.0.
_MIN_PGVECTOR = (0, 8)


def _pgvector_version(session) -> tuple[int, ...] | None:
    row = session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).first()
    if row is None:
        return None
    return tuple(int(part) for part in row[0].split(".") if part.isdigit())


def _sqlalchemy_url(dsn: str) -> str:
    """Ensure the URL uses the psycopg (v3) driver."""
    if dsn.startswith("postgresql+"):
        return dsn
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


class PostgresStore:
    def __init__(
        self, dsn: str, shared_namespaces: Iterable[str] = (), *, pool_size: int = 5
    ) -> None:
        self._shared = list(dict.fromkeys(shared_namespaces))
        # Neon: pass the POOLED connection string. pool_pre_ping drops stale conns.
        # prepare_threshold=None disables psycopg3 auto-prepared statements: Neon's
        # pooled endpoint is PgBouncer in transaction mode, where a statement
        # prepared on one backend fails (InvalidSqlStatementName) on another.
        self._engine = create_engine(
            _sqlalchemy_url(dsn),
            pool_size=pool_size,
            pool_pre_ping=True,
            connect_args={"prepare_threshold": None},
        )
        # None until the first vector search has read the pgvector version.
        self._iterative_scan_ok: bool | None = None

    @property
    def engine(self):
        """The SQLAlchemy engine, for layers that share this database (#125).
        Public so they don't reach into a private attribute that a refactor
        could rename without any error at startup."""
        return self._engine

    def close(self) -> None:
        self._engine.dispose()

    def _supports_iterative_scan(self, session) -> bool:
        """Whether this pgvector has `hnsw.iterative_scan`, read once and cached.

        The version is READ, not inferred from whether a SET succeeds: Postgres
        accepts a SET for any two-part name as a placeholder, so on pgvector
        < 0.8 the statement succeeds, does nothing, and warns nobody.
        """
        global _WARNED_NO_ITERATIVE_SCAN
        if self._iterative_scan_ok is not None:
            return self._iterative_scan_ok
        try:
            # A savepoint, so a failed probe cannot abort the search's own
            # transaction: an optimisation must not become an outage.
            with session.begin_nested():
                version = _pgvector_version(session)
        except Exception as exc:
            # Not cached: a transient error should not disable this for good.
            logger.warning(
                "could not read the pgvector version (%s: %s); this search will "
                "run without hnsw.iterative_scan.",
                type(exc).__name__,
                exc,
            )
            return False
        ok = version is not None and version[:2] >= _MIN_PGVECTOR
        self._iterative_scan_ok = ok
        if not ok and not _WARNED_NO_ITERATIVE_SCAN:
            _WARNED_NO_ITERATIVE_SCAN = True
            logger.warning(
                "pgvector %s has no hnsw.iterative_scan (needs >= 0.8); filtered "
                "searches may return fewer rows than exist.",
                ".".join(map(str, version)) if version else "(not installed)",
            )
        return ok

    def _use_iterative_scan(self, session) -> None:
        """Keep the HNSW scan going until enough rows survive the filter (#169).

        pgvector collects about `hnsw.ef_search` candidates by distance and only
        then applies WHERE, so a selective namespace or visibility filter can
        leave fewer than LIMIT -- rows that never entered the candidate set
        rather than rows that ranked low, which reads as poor recall instead of
        as a bug. Iterative scan (pgvector 0.8) rescans until the limit is met.

        SET LOCAL, inside the search's own transaction. An earlier version ran a
        session-level SET when the connection opened, and the app connects
        through Neon's pooled endpoint: PgBouncer in transaction mode, where
        Neon documents SET as unsupported because a connection goes back to the
        pool after every transaction. The setting then applied to whichever
        requests happened to land on the backend that had received it. CI could
        not see this, since it connects straight to Postgres. pgvector's own
        README recommends SET LOCAL for per-query settings, and it is the form
        that survives a transaction pooler.

        `strict_order`, not `relaxed_order`: search returns a `score`, and
        relaxed ordering can hand back rows slightly out of distance order.
        """
        if self._supports_iterative_scan(session):
            session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))

    def _visible(self, user_id: str):
        """A row is visible if the caller owns it or it's in a shared namespace."""
        return or_(MemoryRow.user_id == user_id, MemoryRow.namespace.in_(self._shared))

    # -- writes (owner-scoped) ------------------------------------------------
    def add(self, memory: Memory, embedding: Sequence[float]) -> str:
        with Session(self._engine) as session, session.begin():
            session.add(
                MemoryRow(
                    id=memory.id,
                    user_id=memory.user_id,
                    namespace=memory.namespace,
                    content=memory.content,
                    embedding=list(embedding),
                    tags=list(memory.tags),
                    source=memory.source,
                    session_id=memory.session_id,
                    seq=memory.seq,
                    kind=memory.kind,
                    object_key=memory.object_key,
                    content_type=memory.content_type,
                    size_bytes=memory.size_bytes,
                    checksum=memory.checksum,
                    confirmed=memory.confirmed,
                )
            )
        return memory.id

    def update(
        self, user_id: str, memory_id: str, content: str, embedding: Sequence[float]
    ) -> Memory | None:
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id == memory_id, MemoryRow.user_id == user_id)
            .values(content=content, embedding=list(embedding), updated_at=func.now())
            .returning(MemoryRow)
            .execution_options(synchronize_session=False)
        )
        with Session(self._engine) as session, session.begin():
            row = session.execute(stmt).scalar_one_or_none()
            return row.to_memory() if row else None

    def confirm_media(
        self, user_id: str, memory_id: str, size_bytes: int, checksum: str
    ) -> Memory | None:
        stmt = (
            update(MemoryRow)
            .where(MemoryRow.id == memory_id, MemoryRow.user_id == user_id)
            .values(
                confirmed=True,
                size_bytes=size_bytes,
                checksum=checksum,
                updated_at=func.now(),
            )
            .returning(MemoryRow)
            .execution_options(synchronize_session=False)
        )
        with Session(self._engine) as session, session.begin():
            row = session.execute(stmt).scalar_one_or_none()
            return row.to_memory() if row else None

    def delete(self, user_id: str, memory_id: str) -> bool:
        stmt = delete(MemoryRow).where(
            MemoryRow.id == memory_id, MemoryRow.user_id == user_id
        )
        with Session(self._engine) as session, session.begin():
            return session.execute(stmt).rowcount > 0  # type: ignore[attr-defined]  # DML -> CursorResult

    # -- reads (owner or shared namespace) ------------------------------------
    def get(self, user_id: str, memory_id: str) -> Memory | None:
        stmt = (
            select(MemoryRow)
            .options(defer(MemoryRow.embedding))  # reads never need the vector
            .where(MemoryRow.id == memory_id, self._visible(user_id))
        )
        with Session(self._engine) as session:
            row = session.execute(stmt).scalar_one_or_none()
            _observe("get", [row] if row else [])
            return row.to_memory() if row else None

    def search(
        self,
        user_id: str,
        namespace: str,
        embedding: Sequence[float],
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        # The namespace/visibility filter runs AFTER the HNSW order-by; see
        # _use_iterative_scan for why that can under-return and how it is handled.
        distance = MemoryRow.embedding.cosine_distance(list(embedding))
        stmt = (
            select(MemoryRow, (1 - distance).label("score"))
            # distance is computed server-side; don't ship each row's vector back.
            .options(defer(MemoryRow.embedding))
            .where(
                MemoryRow.namespace == namespace,
                self._visible(user_id),
                MemoryRow.confirmed,
            )
            .order_by(distance)
            .limit(limit)
            .offset(offset)
        )
        with Session(self._engine) as session:
            self._use_iterative_scan(session)
            results = session.execute(stmt).all()
            _observe("search", [row for row, _ in results])
            return [row.to_memory(score=float(score)) for row, score in results]

    def search_text(
        self,
        user_id: str,
        namespace: str,
        query: str,
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        terms = keyword_terms(query)
        if not terms:
            return []
        # Exact substring match, every term required: predictable for IDs and
        # error strings, which is what keyword mode is for. The GIN trigram
        # index (schema.sql) only accelerates this; it cannot change which rows
        # match.
        #
        # similarity() ranks the hits, not word_similarity(): that scores the
        # best-matching PART of the text, so an exact word scores 1.0 whether
        # the chunk is one word or thirty, and ranking collapses to recency.
        # similarity() penalises a chunk the query is lost in.
        score = func.similarity(MemoryRow.content, query)
        stmt = (
            select(MemoryRow, score.label("score"))
            .options(defer(MemoryRow.embedding))
            .where(
                MemoryRow.namespace == namespace,
                self._visible(user_id),
                MemoryRow.confirmed,
                *[
                    MemoryRow.content.ilike(f"%{like_escape(t)}%", escape="\\")
                    for t in terms
                ],
            )
            .order_by(score.desc(), MemoryRow.created_at.desc(), MemoryRow.id)
            .limit(limit)
            .offset(offset)
        )
        with Session(self._engine) as session:
            results = session.execute(stmt).all()
            _observe("search_text", [row for row, _ in results])
            return [row.to_memory(score=float(sc)) for row, sc in results]

    def list_memories(
        self, user_id: str, namespace: str, limit: int, offset: int = 0
    ) -> list[Memory]:
        stmt = (
            select(MemoryRow)
            .options(defer(MemoryRow.embedding))
            .where(
                MemoryRow.namespace == namespace,
                self._visible(user_id),
                MemoryRow.confirmed,
            )
            .order_by(MemoryRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with Session(self._engine) as session:
            rows = session.execute(stmt).scalars().all()
            _observe("list", rows)
            return [row.to_memory() for row in rows]

    def count(self, user_id: str, namespace: str) -> int:
        stmt = (
            select(func.count())
            .select_from(MemoryRow)
            .where(
                MemoryRow.namespace == namespace,
                self._visible(user_id),
                MemoryRow.confirmed,
            )
        )
        with Session(self._engine) as session:
            return session.execute(stmt).scalar_one()

    def get_session(self, user_id: str, session_id: str) -> list[Memory]:
        stmt = (
            select(MemoryRow)
            .options(defer(MemoryRow.embedding))
            .where(MemoryRow.user_id == user_id, MemoryRow.session_id == session_id)
            .order_by(MemoryRow.seq)
        )
        with Session(self._engine) as session:
            rows = session.execute(stmt).scalars().all()
            _observe("session", rows)
            return [row.to_memory() for row in rows]

    def delete_session(self, user_id: str, session_id: str) -> int:
        stmt = delete(MemoryRow).where(
            MemoryRow.user_id == user_id, MemoryRow.session_id == session_id
        )
        with Session(self._engine) as session, session.begin():
            return session.execute(stmt).rowcount  # type: ignore[attr-defined]  # DML -> CursorResult

    def replace_session(
        self,
        user_id: str,
        session_id: str,
        memories: Sequence[Memory],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        # One transaction: delete old + insert new is all-or-nothing.
        with Session(self._engine) as session, session.begin():
            session.execute(
                delete(MemoryRow).where(
                    MemoryRow.user_id == user_id,
                    MemoryRow.session_id == session_id,
                )
            )
            session.add_all(
                MemoryRow(
                    id=memory.id,
                    user_id=memory.user_id,
                    namespace=memory.namespace,
                    content=memory.content,
                    embedding=list(embedding),
                    tags=list(memory.tags),
                    source=memory.source,
                    session_id=memory.session_id,
                    seq=memory.seq,
                )
                for memory, embedding in zip(memories, embeddings, strict=True)
            )
