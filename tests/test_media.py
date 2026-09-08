"""Media memories (#44): register a file, find it by description, get a download
URL — all without bytes ever crossing the MCP channel (conftest uses the fake
blob store)."""

from dataclasses import replace

import pytest
from fastmcp import Client

from polymnemo import app, server
from polymnemo.service import MemoryService


def test_create_upload_registers_and_is_recallable(service):
    r = service.create_upload("alice", "cat.png", "image/png", "a photo of my cat")
    assert r["upload_url"].startswith("https://blob.local/")
    assert r["object_key"].endswith("/cat.png")
    assert r["memory_id"]

    # findable by its description via vector recall
    found = service.recall("alice", "cat photo")
    assert found["total"] == 1
    item = found["items"][0]
    assert item["kind"] == "image"
    assert item["content_type"] == "image/png"
    assert item["content"] == "a photo of my cat"

    # and a download URL comes back
    d = service.get_download_url("alice", r["memory_id"])
    assert d["url"].startswith("https://blob.local/")
    assert d["content_type"] == "image/png"


def test_get_download_url_rejects_text_memory(service):
    mid = service.remember("alice", "just plain text")["ids"][0]
    with pytest.raises(ValueError):
        service.get_download_url("alice", mid)


def test_create_upload_validates_inputs(service):
    with pytest.raises(ValueError):
        service.create_upload("alice", "x.png", "image/png", "   ")  # empty description
    with pytest.raises(ValueError):
        service.create_upload("alice", "  ", "image/png", "desc")  # empty filename


def test_filename_is_stripped_of_path(service):
    r = service.create_upload("alice", "../../etc/passwd", "text/plain", "sneaky")
    # object key stays under the user's prefix; no path traversal in the key
    assert r["object_key"] == f"alice/{r['memory_id']}/passwd"


def test_media_disabled_raises(service):
    svc = MemoryService(replace(service.ctx, blob_store=None))
    with pytest.raises(ValueError):
        svc.create_upload("alice", "x.png", "image/png", "desc")


def test_s3_blobstore_requires_config():
    # Validation happens before boto3 is imported, so this runs without boto3.
    from polymnemo.blobstore.base import BlobError
    from polymnemo.blobstore.s3 import S3BlobStore

    with pytest.raises(BlobError):
        S3BlobStore(
            bucket="", endpoint_url="", access_key_id="", secret_access_key=""
        )


async def test_media_tools_over_client(monkeypatch, fake_blob_store):
    # Inject the fake into the running app (ctx for the gate, service for the
    # media methods, which read their own ctx.blob_store).
    new_ctx = replace(app.ctx, blob_store=fake_blob_store)
    monkeypatch.setattr(app, "ctx", new_ctx)
    monkeypatch.setattr(app, "service", MemoryService(new_ctx))
    app.ctx.store._rows.clear()
    try:
        async with Client(server.mcp) as client:
            r = (
                await client.call_tool(
                    "create_upload",
                    {
                        "filename": "clip.mp4",
                        "content_type": "video/mp4",
                        "description": "a short demo video",
                    },
                )
            ).data
            assert r["upload_url"].startswith("https://blob.local/")

            recalled = (await client.call_tool("recall", {"query": "demo video"})).data
            assert recalled["total"] == 1
            assert recalled["items"][0]["kind"] == "video"

            d = (
                await client.call_tool("get_download_url", {"id": r["memory_id"]})
            ).data
            assert d["url"].startswith("https://blob.local/")
    finally:
        app.ctx.store._rows.clear()
