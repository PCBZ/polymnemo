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

from collections.abc import Iterable, Sequence
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Text, create_engine, delete, func, or_, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..config import settings
from ..models import Memory


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

    def close(self) -> None:
        self._engine.dispose()

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
        stmt = select(MemoryRow).where(
            MemoryRow.id == memory_id, self._visible(user_id)
        )
        with Session(self._engine) as session:
            row = session.execute(stmt).scalar_one_or_none()
            return row.to_memory() if row else None

    def search(
        self,
        user_id: str,
        namespace: str,
        embedding: Sequence[float],
        limit: int,
        offset: int = 0,
    ) -> list[Memory]:
        # NOTE: with a selective namespace/visibility filter on top of the HNSW
        # ANN scan, a small namespace can under-return (pgvector filters the
        # ~hnsw.ef_search candidates after the vector order-by). Raise
        # hnsw.ef_search or add a partial index if recall matters there.
        distance = MemoryRow.embedding.cosine_distance(list(embedding))
        stmt = (
            select(MemoryRow, (1 - distance).label("score"))
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
            return [
                row.to_memory(score=float(score))
                for row, score in session.execute(stmt)
            ]

    def list_memories(
        self, user_id: str, namespace: str, limit: int, offset: int = 0
    ) -> list[Memory]:
        stmt = (
            select(MemoryRow)
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
            return [row.to_memory() for row in session.execute(stmt).scalars()]

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
            .where(MemoryRow.user_id == user_id, MemoryRow.session_id == session_id)
            .order_by(MemoryRow.seq)
        )
        with Session(self._engine) as session:
            return [row.to_memory() for row in session.execute(stmt).scalars()]

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
