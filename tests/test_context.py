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


# --- production-backend selection (the branches the dev defaults skip) --------
# Every real backend's constructor is lazy (no model download / DB connection /
# network), so we can assert the wiring picks the right class without deps.


def test_build_embedder_fastembed(monkeypatch):
    from polymnemo.embedding import FastEmbedEmbedder

    monkeypatch.setattr(settings, "embed_backend", "fastembed")
    assert isinstance(context._build_embedder(), FastEmbedEmbedder)


def test_build_store_postgres(monkeypatch):
    from polymnemo.store.postgres import PostgresStore

    # create_engine is lazy — constructing the store makes no connection.
    monkeypatch.setattr(
        settings, "database_url", "postgresql+psycopg://u:p@localhost/db"
    )
    assert isinstance(context._build_store(), PostgresStore)


def test_build_auth_bearer_with_keys(monkeypatch):
    from polymnemo.auth import BearerKeyAuth

    monkeypatch.setattr(settings, "auth_backend", "bearer")
    monkeypatch.setattr(settings, "api_keys", "k1:alice")
    assert isinstance(context._build_auth(), BearerKeyAuth)


def test_build_auth_bearer_without_keys_warns(monkeypatch):
    from polymnemo.auth import BearerKeyAuth

    # bearer + no keys: constructs a deny-all BearerKeyAuth (and logs a warning).
    monkeypatch.setattr(settings, "auth_backend", "bearer")
    monkeypatch.setattr(settings, "api_keys", "")
    assert isinstance(context._build_auth(), BearerKeyAuth)


def test_build_blob_store_s3(monkeypatch):
    from polymnemo.blobstore.s3 import S3BlobStore

    monkeypatch.setattr(settings, "blob_backend", "s3")
    monkeypatch.setattr(settings, "blob_bucket", "b")
    monkeypatch.setattr(settings, "blob_endpoint_url", "https://s3.example.com")
    monkeypatch.setattr(settings, "blob_access_key_id", "k")
    monkeypatch.setattr(settings, "blob_secret_access_key", "s")
    assert isinstance(context._build_blob_store(), S3BlobStore)


def test_build_blob_store_unknown_backend(monkeypatch):
    monkeypatch.setattr(settings, "blob_backend", "bogus")
    with pytest.raises(RuntimeError, match="unknown"):
        context._build_blob_store()
