"""Placeholder auth for local development.

``StaticAuth`` ignores the request and returns a single fixed ``user_id``. It
exists only so the server can start end-to-end before real auth lands. The
canonical per-user ``BearerKeyAuth`` arrives in #5.
"""

from __future__ import annotations

from collections.abc import Mapping


class StaticAuth:
    """Resolves every request to the same ``user_id``. Dev only — no security."""

    def __init__(self, user_id: str = "local") -> None:
        self.user_id = user_id

    def authenticate(self, headers: Mapping[str, str]) -> str:
        return self.user_id
