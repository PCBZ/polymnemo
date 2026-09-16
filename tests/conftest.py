"""Test config. Force an offline, deterministic environment BEFORE any polymnemo
import so the config singleton picks it up: the stub embedder (no model
download / no network) and static auth (no bearer header needed in-process)."""

import os

os.environ.setdefault("POLYMNEMO_EMBED_BACKEND", "stub")
os.environ.setdefault("POLYMNEMO_AUTH_BACKEND", "static")
# Small chunks so chunking tests split without huge inputs.
os.environ.setdefault("POLYMNEMO_CHUNK_TOKENS", "40")
os.environ.setdefault("POLYMNEMO_CHUNK_OVERLAP_TOKENS", "8")

from dataclasses import replace

import pytest

from polymnemo.context import build_context
from polymnemo.service import MemoryService


class FakeBlobStore:
    """Test double for BlobStore — deterministic, network-free URLs. Lives in the
    tests (not src): it's only for exercising the media path offline, never a real
    runtime backend."""

    _BASE = "https://blob.local"

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.head_size = 12345  # tests bump this to trigger the size cap

    def presign_put(self, object_key: str, content_type: str) -> str:
        return f"{self._BASE}/{object_key}?method=PUT&content_type={content_type}"

    def presign_get(self, object_key: str) -> str:
        return f"{self._BASE}/{object_key}?method=GET"

    def head(self, object_key: str) -> tuple[int, str]:
        if self.head_size is None:  # simulate "bytes never uploaded"
            from polymnemo.blobstore.base import BlobError

            raise BlobError(f"object {object_key} not found — upload it first.")
        return (self.head_size, "fake-etag")

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


@pytest.fixture
def fake_blob_store() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture
def service() -> MemoryService:
    """A service backed by a fresh in-memory store + stub embedder, with a fake
    blob store injected so the media tools are exercisable."""
    ctx = replace(build_context(), blob_store=FakeBlobStore())
    return MemoryService(ctx)


@pytest.fixture
def restore_loggers():
    """Undo what `configure_logging` does to global logger state.

    **Any test class that calls `configure_logging` must request this**, via
    `@pytest.mark.usefixtures("restore_loggers")` on the class. It is opt-in
    rather than autouse because most tests never touch logger configuration,
    but a class that does and forgets the mark leaks `basicConfig(force=True)`'s
    replacement root handler into every later test — which surfaces as an
    order-dependent failure somewhere else entirely.

    Shared rather than copied into each class: the two copies it replaces were
    byte-identical, which is exactly the drift this guards against.
    """
    import logging

    from polymnemo import logging as log_mod

    names = ("", "polymnemo", log_mod.CALL_LOGGER, log_mod.AUTH_LOGGER)
    # Handlers as well as levels, and for the named loggers too: restoring a
    # level while leaving an added handler in place still leaks.
    saved = [
        (
            logging.getLogger(n),
            logging.getLogger(n).level,
            list(logging.getLogger(n).handlers),
        )
        for n in names
    ]
    yield
    for log, level, handlers in saved:
        log.setLevel(level)
        log.handlers = handlers
