"""Self-service API tokens (#125) — a credential for headless clients.

OAuth's authorization-code flow needs a browser and a person, so CI, cron jobs
and server-side agents cannot use it. A signed-in user mints a token here and
hands it to those clients, with no maintainer in the loop.

Only the SHA-256 of a token is stored: a leak of the table yields nothing usable,
and the token is unrecoverable after it is shown once. SHA-256 rather than
bcrypt/argon2 deliberately — those slow down brute force on LOW-entropy secrets,
while these carry 256 bits of randomness, and a slow hash would sit in the path
of every authenticated request.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Text, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..models import new_id

# Identifies a polymnemo token on sight — in a log, a paste, or a secret
# scanner — the way GitHub's "ghp_" prefix does.
TOKEN_PREFIX = "pmn_"
# 32 bytes: far past guessing, and short enough to paste.
TOKEN_BYTES = 32


def generate_token() -> str:
    """A fresh token. Returned to the caller once and never stored as-is."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The stored form. Plain SHA-256 — see the module docstring for why."""
    return hashlib.sha256(token.encode()).hexdigest()


class Base(DeclarativeBase):
    pass


class ApiTokenRow(Base):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(default=None)


@dataclass(frozen=True)
class ApiToken:
    """A token's metadata. Never carries the token itself."""

    id: str
    user_id: str
    label: str
    created_at: datetime
    expires_at: datetime | None


def _to_token(row: ApiTokenRow) -> ApiToken:
    return ApiToken(
        id=row.id,
        user_id=row.user_id,
        label=row.label,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


class ApiTokenStore:
    """Token persistence. Shares the memories database; its own engine keeps the
    auth path independent of the memory store's pool, which reads can saturate.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    def create(
        self, user_id: str, label: str, expires_in_days: int | None = None
    ) -> tuple[str, ApiToken]:
        """Mint a token. Returns ``(token, metadata)`` — the only time the token
        itself exists outside the caller's hands."""
        token = generate_token()
        expires_at = (
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days
            else None
        )
        row = ApiTokenRow(
            id=new_id(),
            user_id=user_id,
            token_hash=hash_token(token),
            label=label,
            expires_at=expires_at,
        )
        with Session(self._engine) as session, session.begin():
            session.add(row)
            session.flush()
            meta = _to_token(row)
        return token, meta

    def resolve(self, token: str) -> str | None:
        """``user_id`` for a presented token, or None if unknown or expired.

        Looked up by hash, so the plaintext is never compared against stored
        values and the query hits the unique index rather than scanning.
        """
        stmt = select(ApiTokenRow).where(ApiTokenRow.token_hash == hash_token(token))
        with Session(self._engine) as session:
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            if row.expires_at is not None:
                # Stored as timestamptz; compare in UTC so a naive value read
                # back from some drivers can't silently compare as local time.
                expires = row.expires_at
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires <= datetime.now(UTC):
                    return None
            return row.user_id

    def list_for_user(self, user_id: str) -> list[ApiToken]:
        stmt = (
            select(ApiTokenRow)
            .where(ApiTokenRow.user_id == user_id)
            .order_by(ApiTokenRow.created_at.desc())
        )
        with Session(self._engine) as session:
            return [_to_token(r) for r in session.execute(stmt).scalars().all()]

    def revoke(self, user_id: str, token_id: str) -> bool:
        """Owner-scoped, like every other write: the id and the user must match,
        so one user cannot revoke another's token by guessing an id."""
        stmt = delete(ApiTokenRow).where(
            ApiTokenRow.id == token_id, ApiTokenRow.user_id == user_id
        )
        with Session(self._engine) as session, session.begin():
            return session.execute(stmt).rowcount > 0  # type: ignore[attr-defined]
