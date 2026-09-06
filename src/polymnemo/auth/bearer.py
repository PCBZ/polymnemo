"""Per-user bearer-key auth — the only auth scheme (no OAuth).

Reads ``Authorization: Bearer <key>`` and maps the key to a ``user_id`` via a
configured ``{api_key -> user_id}`` table. Per-user keys are required: a single
shared token would make namespaces meaningless.
"""

from __future__ import annotations

from typing import Mapping

from .base import AuthError


class BearerKeyAuth:
    def __init__(self, keys: Mapping[str, str]) -> None:
        # {api_key -> user_id}. An empty map rejects everything (secure default).
        self._keys = dict(keys)

    def authenticate(self, headers: Mapping[str, str]) -> str:
        token = self._bearer_token(headers)
        user_id = self._keys.get(token)
        if user_id is None:
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
            raise AuthError("Missing Authorization header")
        parts = value.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            raise AuthError("Expected 'Authorization: Bearer <key>'")
        return parts[1].strip()
