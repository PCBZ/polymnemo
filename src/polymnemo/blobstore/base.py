"""Blob-store seam — presigned URLs for large / binary memory content (#44).

Bytes for file / image / video memories never travel through the MCP JSON
channel. Instead this layer mints short-lived **presigned URLs**: the client
uploads bytes straight to object storage (PUT) and downloads them straight back
(GET). polymnemo only ever holds a pointer (``object_key``) + a searchable text
description in Postgres.

The only implementation is ``S3BlobStore`` (Cloudflare R2 / any S3-compatible
store); the test suite injects its own fake for the offline media path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class BlobError(Exception):
    """Raised when blob storage is misconfigured or a presign fails."""


@runtime_checkable
class BlobStore(Protocol):
    def presign_post(
        self, object_key: str, content_type: str, max_bytes: int
    ) -> dict:
        """A short-lived presigned **POST** for direct upload, returning
        ``{"url", "fields"}``. A ``content-length-range`` condition caps the size
        so the store itself rejects an oversized upload (#50)."""
        ...

    def presign_get(self, object_key: str) -> str:
        """A short-lived URL the client GETs bytes from (direct download)."""
        ...

    def head(self, object_key: str) -> tuple[int, str]:
        """Return ``(size_bytes, checksum)`` for an uploaded object; raise
        :class:`BlobError` if it doesn't exist (used to confirm an upload)."""
        ...

    def delete(self, object_key: str) -> None:
        """Delete the object, so ``forget`` removes the bytes, not just the pointer."""
        ...
