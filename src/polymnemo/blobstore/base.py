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
    def presign_put(self, object_key: str, content_type: str) -> str:
        """A short-lived URL the client PUTs bytes to (direct upload). PUT is used
        (not presigned POST) because it's universally supported by S3-compatible
        stores incl. Cloudflare R2; the size cap is enforced at ``confirm`` via
        ``head`` instead (#50)."""
        ...

    def presign_get(self, object_key: str) -> str:
        """A short-lived URL the client GETs bytes from (direct download)."""
        ...

    def head(self, object_key: str) -> tuple[int, str]:
        """Return ``(size_bytes, etag)`` for an uploaded object; raise
        :class:`BlobError` if it doesn't exist. ``etag`` is opaque (not a
        guaranteed content hash — multipart/store-specific), stored as ``checksum``
        for reference only."""
        ...

    def delete(self, object_key: str) -> None:
        """Delete the object, so ``forget`` removes the bytes, not just the pointer."""
        ...
