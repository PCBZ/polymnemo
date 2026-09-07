import pytest

from polymnemo.service import _parse_offset


def test_remember_chunks_large_content(service):
    r = service.remember("alice", "word " * 200)
    assert r["chunks"] > 1
    assert len(r["ids"]) == r["chunks"]
    assert r["namespace"] == "shared"


def test_recall_pagination(service):
    for d in ["a", "b", "c"]:
        service.remember("alice", d)

    p1 = service.recall("alice", "x", limit=2)
    assert p1["total"] == 3
    assert p1["has_more"] is True
    assert p1["next_cursor"] == "2"

    p2 = service.recall("alice", "x", limit=2, cursor=p1["next_cursor"])
    assert p2["has_more"] is False
    assert p2["next_cursor"] is None
    ids1 = {i["id"] for i in p1["items"]}
    ids2 = {i["id"] for i in p2["items"]}
    assert ids1.isdisjoint(ids2)


def test_crud_and_tenant_isolation(service):
    # A private namespace (not in shared_namespaces) is owner-only.
    mid = service.remember("alice", "hello", namespace="alice-private")["ids"][0]
    assert service.get_memory("alice", mid)["content"] == "hello"
    assert service.update("alice", mid, "hi")["content"] == "hi"

    with pytest.raises(ValueError):
        service.get_memory("bob", mid)  # private ns -> not visible to bob

    assert service.forget("alice", mid) == {"id": mid, "deleted": True}
    assert service.forget("alice", mid)["deleted"] is False


def test_shared_namespace_is_cross_user(service):
    # Default namespace "shared" is readable by everyone ("born shared").
    service.remember("alice", "toyota oil change", namespace="shared")
    assert service.list_memories("bob", namespace="shared")["total"] == 1
    assert service.recall("bob", "oil change", namespace="shared")["total"] == 1


def test_private_namespace_is_isolated(service):
    service.remember("alice", "secret diary entry", namespace="diary")
    assert service.list_memories("bob", namespace="diary")["total"] == 0
    assert service.recall("bob", "diary", namespace="diary")["total"] == 0
    assert service.list_memories("alice", namespace="diary")["total"] == 1  # owner sees it


def test_empty_inputs_raise(service):
    with pytest.raises(ValueError):
        service.remember("alice", "   ")
    with pytest.raises(ValueError):
        service.recall("alice", "   ")


def test_parse_offset():
    assert _parse_offset(None) == 0
    assert _parse_offset("") == 0
    assert _parse_offset("5") == 5
    assert _parse_offset("-3") == 0  # clamped
    assert _parse_offset("garbage") == 0


def test_session_round_trip_is_lossless(service):
    content = "Line one.\n\n  Indented two.\tTab.\nThree 中文内容。\n" * 60
    r = service.save_session("alice", "sess1", content)
    assert r["chunks"] >= 1
    assert r["chars"] == len(content)

    reassembled, page = "", 0
    while True:
        p = service.load_session("alice", "sess1", page=page, page_size=100)
        reassembled += p["content"]
        if not p["has_more"]:
            break
        page += 1
    assert reassembled == content  # exact round-trip across pages


def test_save_session_replaces(service):
    service.save_session("alice", "s", "first version")
    service.save_session("alice", "s", "second version")
    p = service.load_session("alice", "s")
    assert p["content"] == "second version"
    assert p["total_chars"] == len("second version")


def test_session_is_user_scoped(service):
    service.save_session("alice", "s", "alice content")
    p = service.load_session("bob", "s")  # bob has no session "s"
    assert p["total_chars"] == 0
    assert p["content"] == ""


def test_save_session_rejects_empty(service):
    with pytest.raises(ValueError):
        service.save_session("alice", "  ", "x")
    with pytest.raises(ValueError):
        service.save_session("alice", "s", "")


def test_failed_save_preserves_old_session(service, monkeypatch):
    service.save_session("alice", "s", "original content")

    def boom(*args, **kwargs):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(service.ctx.embedder, "embed_documents", boom)
    with pytest.raises(RuntimeError):
        service.save_session("alice", "s", "new content that never lands")

    # embedding failed before any store mutation -> old session intact
    assert service.load_session("alice", "s")["content"] == "original content"
