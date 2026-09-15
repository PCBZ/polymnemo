"""Per-user bearer-key auth — the only auth scheme (no OAuth).

Reads ``Authorization: Bearer <key>`` and maps the key to a ``user_id`` via a
configured ``{api_key -> user_id}`` table. Per-user keys are required: a single
shared token would make namespaces meaningless.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from ..logging import AUTH_LOGGER
from .base import AuthError

logger = logging.getLogger(AUTH_LOGGER)


class BearerKeyAuth:
    def __init__(self, keys: Mapping[str, str]) -> None:
        # {api_key -> user_id}. An empty map rejects everything (secure default).
        self._keys = dict(keys)

    def authenticate(self, headers: Mapping[str, str]) -> str:
        token = self._bearer_token(headers)
        user_id = self._keys.get(token)
        if user_id is None:
            # The reason, never the token or any prefix of it: a partial
            # credential in a log is still credential material.
            _rejected("unknown_key")
            raise AuthError("Invalid API key")
        return user_id

    @staticmethod
    def _bearer_token(headers: Mapping[str, str]) -> str:
        # Case-insensitive header lookup (HTTP header names aren't case-sensitive).
        value = None
        for name, val in headers.items():
            if name.lower() == "authorization":
                value = val
                break
        if not value:
            _rejected("missing_header")
            raise AuthError("Missing Authorization header")
        parts = value.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            _rejected("malformed_header")
            raise AuthError("Expected 'Authorization: Bearer <key>'")
        return parts[1].strip()


def _rejected(reason: str) -> None:
    """One line per rejection.

    WARNING, not ERROR: a single bad key is a client's problem, the *rate* is
    ours. Until now `auth/` logged nothing at all, so a stale CI token or a
    credential-stuffing run left no trace anywhere — #123 shipped a bug that
    401'd every bearer key and the logs showed nothing.
    """
    logger.warning("bearer auth rejected: %s", reason)
