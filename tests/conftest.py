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

    def presign_put(self, object_key: str, content_type: str) -> str:
        return f"{self._BASE}/{object_key}?method=PUT&content_type={content_type}"

    def presign_get(self, object_key: str) -> str:
        return f"{self._BASE}/{object_key}?method=GET"


@pytest.fixture
def fake_blob_store() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture
def service() -> MemoryService:
    """A service backed by a fresh in-memory store + stub embedder, with a fake
    blob store injected so the media tools are exercisable."""
    ctx = replace(build_context(), blob_store=FakeBlobStore())
    return MemoryService(ctx)
