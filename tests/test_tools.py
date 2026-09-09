"""Tool-contract tests: an MCP client (as an LLM would) calls the tools over
FastMCP's in-memory transport. Static auth is active (see conftest), so no
bearer header is needed in-process."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from polymnemo import app, server

EXPECTED_TOOLS = {
    "ping",
    "remember",
    "recall",
    "list_memories",
    "get_memory",
    "update",
    "forget",
    "save_session",
    "load_session",
    "create_upload",
    "confirm_upload",
    "get_download_url",
}


@pytest.fixture(autouse=True)
def _isolate_store():
    """Each test starts from an empty in-memory store."""
    app.ctx.store._rows.clear()
    yield
    app.ctx.store._rows.clear()


async def test_tool_surface_and_annotations():
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert EXPECTED_TOOLS <= set(tools)
        assert tools["recall"].annotations.read_only_hint is True
        assert tools["remember"].annotations.read_only_hint is False
        assert tools["forget"].annotations.destructive_hint is True


async def test_remember_recall_roundtrip():
    async with Client(server.mcp) as client:
        rid = (await client.call_tool("remember", {"content": "hello world"})).data[
            "ids"
        ][0]
        assert (await client.call_tool("list_memories", {})).data["total"] == 1
        got = (await client.call_tool("get_memory", {"id": rid})).data
        assert got["content"] == "hello world"
        recalled = (await client.call_tool("recall", {"query": "hello"})).data
        assert recalled["total"] == 1
        assert (await client.call_tool("forget", {"id": rid})).data["deleted"] is True


async def test_actionable_error_reaches_client():
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("recall", {"query": "   "})
        assert "query is empty" in str(excinfo.value)


async def test_memory_namespace_resource():
    import json

    async with Client(server.mcp) as client:
        templates = {t.uri_template for t in await client.list_resource_templates()}
        assert "memory://{namespace}" in templates

        await client.call_tool("remember", {"content": "hello resource"})
        contents = await client.read_resource("memory://shared")
        data = json.loads(contents[0].text)
        assert data["total"] == 1
        assert data["items"][0]["content"] == "hello resource"


async def test_session_tools_round_trip():
    async with Client(server.mcp) as client:
        content = "session line\n" * 200
        saved = (
            await client.call_tool(
                "save_session", {"session_id": "s1", "content": content}
            )
        ).data
        assert saved["chars"] == len(content)

        loaded, page = "", 0
        while True:
            p = (
                await client.call_tool(
                    "load_session",
                    {"session_id": "s1", "page": page, "page_size": 200},
                )
            ).data
            loaded += p["content"]
            if not p["has_more"]:
                break
            page += 1
        assert loaded == content
