"""MCP server: an AI client writes an entity and a rule set draft from a description."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

from minos.api.app import create_app
from minos.cli import create_admin_key
from minos.mcp import __main__ as entry
from minos.mcp import build_server, guide_text, http_api
from minos.mcp.server import HERE

from .test_platform import settings

ROOT = Path(__file__).resolve().parents[2]
STUDIO = "http://studio.test"

ORDER = {"orderId": "A-1", "lines": [{"sku": "BOOK", "quantity": 2, "unitPrice": 12.5}]}
EMPTY = {"orderId": "A-2", "lines": []}


def example_graph() -> dict[str, Any]:
    """The complete example of the workflow guide: what the AI is shown must be valid."""
    match = re.search(r"```json\n(.*?)\n```", (HERE / "workflow.md").read_text(), re.S)
    assert match
    graph: dict[str, Any] = json.loads(match.group(1))
    return graph


def test_guide_includes_the_format_reference() -> None:
    # the packaged copy (shipped in the Docker image) must follow docs/rgd-format.md
    assert (HERE / "rgd-format.md").read_text() == (ROOT / "docs" / "rgd-format.md").read_text()
    assert "Workflow" in guide_text() and "## Expressions" in guide_text()


@asynccontextmanager
async def minos_app(url: str, **overrides: Any) -> AsyncIterator[Any]:
    app = create_app(settings(url, **overrides))
    async with app.router.lifespan_context(app):
        yield app


def in_process(app: Any) -> Any:
    @asynccontextmanager
    async def open_client(headers: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://minos", headers=headers
        ) as c:
            yield c

    return open_client


def data(result: Any) -> Any:
    assert not result.is_error, result.content
    if result.structured_content is not None:
        sc = result.structured_content
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


async def test_describe_to_draft(clean_db: str) -> None:
    async with minos_app(clean_db, require_auth=False) as app:
        server = build_server(in_process(app), STUDIO)
        async with Client(server) as ai:
            tools = {t.name for t in (await ai.list_tools()).tools}
            assert {"guide", "create_entity", "create_ruleset", "simulate_ruleset"} <= tools
            assert not any("publish" in t for t in tools)  # publishing stays with people

            guide = await ai.call_tool("guide", {})
            assert "Rule Graph Document" in guide.content[0].text

            ws = data(await ai.call_tool("create_workspace", {"slug": "shop", "name": "Shop"}))
            assert ws["studioUrl"] == f"{STUDIO}/w/shop"
            assert [w["slug"] for w in data(await ai.call_tool("list_workspaces", {}))] == ["shop"]

            entity = data(
                await ai.call_tool(
                    "create_entity",
                    {"workspace": "shop", "key": "Order", "name": "Ordine", "samples": [ORDER]},
                )
            )
            assert entity["schemaVersion"] == 1
            assert entity["studioUrl"] == f"{STUDIO}/w/shop/entities/Order"
            assert "lines" in entity["schema"]["properties"]
            got = data(await ai.call_tool("get_entity", {"workspace": "shop", "entity": "Order"}))
            assert got["schema"] == entity["schema"]

            created = data(
                await ai.call_tool(
                    "create_ruleset",
                    {
                        "workspace": "shop",
                        "key": "shop.order.basic",
                        "name": "Ordine",
                        "entity": "Order",
                        "graph": example_graph(),
                    },
                )
            )
            assert created["validation"]["valid"], created["validation"]
            assert created["studioUrl"] == f"{STUDIO}/w/shop/rulesets/shop.order.basic"

            args = {"workspace": "shop", "ruleset": "shop.order.basic"}
            ok = data(await ai.call_tool("simulate_ruleset", {**args, "input": ORDER}))
            assert ok["outcome"] == "valid" and ok["result"] == {"total": 25.0}
            ko = data(await ai.call_tool("simulate_ruleset", {**args, "input": EMPTY}))
            assert ko["outcome"] == "invalid"
            assert {f["code"] for f in ko["feedback"]} == {"ORD_EMPTY", "ORD_MIN"}

            await ai.call_tool(
                "add_test",
                {
                    **args,
                    "name": "ordine vuoto",
                    "input": EMPTY,
                    "expected": {"outcome": "invalid", "feedbackCodes": ["ORD_EMPTY", "ORD_MIN"]},
                },
            )
            assert data(await ai.call_tool("run_tests", args))["passed"]

            # a change that does not type-check comes back as issues to fix, saved as a draft
            graph = example_graph()
            graph["nodes"][1]["assign"]["total"] = {"ref": "$.input.amount"}
            broken = data(await ai.call_tool("update_ruleset", {**args, "graph": graph}))
            assert not broken["validation"]["valid"]
            assert "amount" in json.dumps(broken["validation"]["issues"])
            assert "tests" not in broken

            # graph sent as a string (some clients do), back to valid: tests run again
            fixed = data(
                await ai.call_tool("update_ruleset", {**args, "graph": json.dumps(example_graph())})
            )
            assert fixed["validation"]["valid"] and fixed["tests"]["passed"]

            rs = data(await ai.call_tool("get_ruleset", args))
            assert rs["entity"] == "Order" and rs["latestVersion"] is None
            assert rs["tests"] == ["ordine vuoto"]
            assert rs["draft"]["graph"]["constants"] == {"minTotal": 10, "reviewAbove": 5000}

            # schema change: a new field becomes usable once the draft moves to it
            await ai.call_tool(
                "update_entity_schema",
                {
                    "workspace": "shop",
                    "entity": "Order",
                    "samples": [{**ORDER, "coupon": "WELCOME"}],
                },
            )
            graph = example_graph()
            graph["nodes"][-2]["output"]["coupon"] = {"ref": "$.input.coupon"}
            stale = data(await ai.call_tool("update_ruleset", {**args, "graph": graph}))
            assert not stale["validation"]["valid"]
            moved = data(
                await ai.call_tool(
                    "update_ruleset", {**args, "graph": graph, "use_latest_schema": True}
                )
            )
            assert moved["validation"]["valid"]

            # several entities: a composite one references Order as a field type
            await ai.call_tool(
                "create_entity",
                {
                    "workspace": "shop",
                    "key": "Basket",
                    "name": "Carrello",
                    "json_schema": {
                        "type": "object",
                        "properties": {
                            "orders": {"type": "array", "items": {"$ref": "entity:Order"}}
                        },
                    },
                },
            )
            basket = data(
                await ai.call_tool("get_entity", {"workspace": "shop", "entity": "Basket"})
            )
            assert basket["references"] == [{"entity": "Order", "version": 2, "latest": 2}]
            assert "entity:Order@2" in basket["resolvedSchema"]["$defs"]

            # API errors reach the model as tool errors it can read
            dup = await ai.call_tool("create_workspace", {"slug": "shop", "name": "Again"})
            assert dup.is_error and "already exists" in dup.content[0].text
            bad = await ai.call_tool("update_ruleset", {**args, "graph": "{not json"})
            assert bad.is_error and "not valid JSON" in bad.content[0].text
            both = await ai.call_tool(
                "update_entity_schema", {"workspace": "shop", "entity": "Order"}
            )
            assert both.is_error


@asynccontextmanager
async def over_http(app: Any, headers: dict[str, str] | None = None) -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8000", headers=headers
    )
    async with (
        http,
        Client(streamable_http_client("http://localhost:8000/mcp", http_client=http)) as client,
    ):
        yield client


async def test_mcp_endpoint_on_the_api(clean_db: str) -> None:
    async with (
        minos_app(clean_db, require_auth=False, studio_url=STUDIO) as app,
        over_http(app) as ai,
    ):
        ws = data(await ai.call_tool("create_workspace", {"slug": "web", "name": "Web"}))
        assert ws["studioUrl"] == f"{STUDIO}/w/web"


async def test_mcp_endpoint_forwards_the_api_key(clean_db: str) -> None:
    key = await create_admin_key(clean_db, "ai")
    async with minos_app(clean_db, require_auth=True) as app:
        async with over_http(app) as anonymous:
            denied = await anonymous.call_tool("list_workspaces", {})
            assert denied.is_error and "401" in denied.content[0].text
        async with over_http(app, {"Authorization": f"Bearer {key}"}) as ai:
            assert data(await ai.call_tool("list_workspaces", {})) == []


async def test_stdio_server_uses_the_configured_key(clean_db: str) -> None:
    key = await create_admin_key(clean_db, "ai")
    async with minos_app(clean_db, require_auth=True) as app:
        base = http_api("http://minos", key)

        @asynccontextmanager
        async def via_app(headers: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
            async with (
                base(headers) as configured,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://minos",
                    headers=configured.headers,
                ) as c,
            ):
                yield c

        server: MCPServer = build_server(via_app, STUDIO)
        async with Client(server) as ai:
            assert data(await ai.call_tool("list_workspaces", {})) == []


@pytest.mark.parametrize("value", ["[1, 2]", "42"])
async def test_graph_must_be_an_object(clean_db: str, value: str) -> None:
    async with (
        minos_app(clean_db, require_auth=False) as app,
        Client(build_server(in_process(app), STUDIO)) as ai,
    ):
        res = await ai.call_tool(
            "update_ruleset", {"workspace": "x", "ruleset": "y", "graph": value}
        )
        assert res.is_error  # rejected by the arguments schema or by the tool


def test_stdio_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[tuple[MCPServer, str]] = []
    monkeypatch.setattr(MCPServer, "run", lambda self, transport: runs.append((self, transport)))
    monkeypatch.setenv("MINOS_API_URL", "http://api.test")
    monkeypatch.setenv("MINOS_API_KEY", "mns_x")
    entry.main()
    assert runs and runs[0][1] == "stdio" and runs[0][0].name == "minos"
