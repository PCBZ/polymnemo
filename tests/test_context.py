import pytest

from polymnemo import context
from polymnemo.config import settings
from polymnemo.store import InMemoryStore


def test_defaults_to_in_memory_when_no_database_url(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "require_database", False)
    assert isinstance(context._build_store(), InMemoryStore)


def test_require_database_fails_fast(monkeypatch):
    # Production: a missing database URL must not silently fall back to memory.
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "require_database", True)
    with pytest.raises(RuntimeError):
        context._build_store()
