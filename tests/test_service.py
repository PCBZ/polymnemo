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
    mid = service.remember("alice", "hello")["ids"][0]
    assert service.get_memory("alice", mid)["content"] == "hello"
    assert service.update("alice", mid, "hi")["content"] == "hi"

    with pytest.raises(ValueError):
        service.get_memory("bob", mid)  # another user cannot read it

    assert service.forget("alice", mid) == {"id": mid, "deleted": True}
    assert service.forget("alice", mid)["deleted"] is False


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
