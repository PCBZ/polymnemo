"""Test config. Force an offline, deterministic environment BEFORE any polymnemo
import so the config singleton picks it up: the stub embedder (no model
download / no network) and static auth (no bearer header needed in-process)."""

import os

os.environ.setdefault("POLYMNEMO_EMBED_BACKEND", "stub")
os.environ.setdefault("POLYMNEMO_AUTH_BACKEND", "static")
# Small chunks so chunking tests split without huge inputs.
os.environ.setdefault("POLYMNEMO_CHUNK_TOKENS", "40")
os.environ.setdefault("POLYMNEMO_CHUNK_OVERLAP_TOKENS", "8")

import pytest

from polymnemo.context import build_context
from polymnemo.service import MemoryService


@pytest.fixture
def service() -> MemoryService:
    """A service backed by a fresh in-memory store + stub embedder per test."""
    return MemoryService(build_context())
