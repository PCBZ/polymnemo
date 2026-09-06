"""Auth seam — resolve a request to a ``user_id``.

The server is multi-tenant: every stored memory belongs to a ``user_id``, and
namespaces are only meaningful if callers are told apart. This layer is the one
place that turns an incoming request into that identity.
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


class AuthError(Exception):
    """Raised when a request cannot be authenticated (missing/invalid key)."""


@runtime_checkable
class Auth(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> str:
        """Return the ``user_id`` for this request, or raise :class:`AuthError`.

        ``headers`` is the request's HTTP headers (case-insensitive lookups are
        the implementation's responsibility). The canonical implementation reads
        the ``Authorization: Bearer <key>`` header (see ``BearerKeyAuth``, #5).
        """
        ...
