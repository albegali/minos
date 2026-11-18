"""MCP server: describe rules in natural language, an AI client writes them as Minos drafts.

The tools are a thin layer over the Management API, so they work against any installation and
follow its rules (validation, optimistic locking, API keys). They create and change entities,
schemas, rule set drafts and tests; publishing stays with the people who review the draft in the
Studio, whose link every write returns.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from minos import __version__

HERE = Path(__file__).resolve().parent
AUTH_HEADERS = ("authorization", "x-api-key", "x-minos-organization")

INSTRUCTIONS = """\
Minos is a JSON rule engine. With these tools you turn a description of business rules into a
Minos rule set: an entity (the JSON object to validate, with its schema) and a rule graph saved
as a draft. Call `guide` first: it explains the workflow and the rule graph format. Every write
returns `studioUrl`: give it to the user, who reviews, simulates and publishes the rule set in
Minos Studio. Nothing is published or live until they do."""

# Opens an HTTP client for the Management API, with the caller's credentials when the MCP
# transport carries them (HTTP) or the configured key (stdio).
type ApiFactory = Callable[[dict[str, str]], AbstractAsyncContextManager[httpx.AsyncClient]]

Json = dict[str, Any]
Graph = Annotated[
    Json | str,
    Field(description="Rule Graph Document (RGD 1.0) as a JSON object; see the `guide` tool."),
]
Samples = Annotated[
    list[Any] | None,
    Field(description="One or more example objects; the JSON Schema is inferred from them."),
]


@cache
def guide_text() -> str:
    return "\n\n".join(
        (HERE / name).read_text(encoding="utf-8") for name in ("workflow.md", "rgd-format.md")
    )


def http_api(base_url: str, api_key: str | None = None) -> ApiFactory:
    """Management API over HTTP (stdio server, or an installation elsewhere)."""

    @asynccontextmanager
    async def open_client(headers: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
        sent = dict(headers)
        if api_key and not sent:
            sent["Authorization"] = f"Bearer {api_key}"
        sent["X-Minos-Via"] = "mcp"
        async with httpx.AsyncClient(base_url=base_url, headers=sent, timeout=30) as client:
            yield client

    return open_client


def _caller_headers(ctx: Context | None) -> dict[str, str]:
    headers = (ctx.headers if ctx is not None else None) or {}
    return {k: v for k, v in headers.items() if k.lower() in AUTH_HEADERS}


def _graph(value: Json | str) -> Json:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolError(f"graph is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ToolError("graph must be a JSON object")
    return value


def _p(segment: str) -> str:
    return quote(segment, safe="")


def build_server(api: ApiFactory, studio_url: str) -> MCPServer:
    studio = studio_url.rstrip("/")
    mcp = MCPServer(
        name="minos",
        title="Minos rule engine",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    writes = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    async def call(
        ctx: Context | None,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with api(_caller_headers(ctx)) as client:
            res = await client.request(method, f"/v1{path}", json=body, headers=headers)
        if res.status_code >= 400:
            try:
                problem = res.json()
            except ValueError:
                problem = {"status": res.status_code, "detail": res.text}
            raise ToolError(json.dumps(problem, ensure_ascii=False))
        return res

    async def get(ctx: Context | None, path: str) -> Any:
        return (await call(ctx, "GET", path)).json()

    async def post(ctx: Context | None, path: str, body: Any = None) -> Any:
        return (await call(ctx, "POST", path, body)).json()

    def entity_url(ws: str, entity: str) -> str:
        return f"{studio}/w/{_p(ws)}/entities/{_p(entity)}"

    def ruleset_url(ws: str, rs: str) -> str:
        return f"{studio}/w/{_p(ws)}/rulesets/{_p(rs)}"

    def rs_path(ws: str, rs: str) -> str:
        return f"/workspaces/{_p(ws)}/rulesets/{_p(rs)}"

    async def checked(ctx: Context | None, ws: str, rs: str) -> Json:
        validation = await post(ctx, f"{rs_path(ws, rs)}/validate")
        out: Json = {"validation": validation, "studioUrl": ruleset_url(ws, rs)}
        if validation["valid"] and await get(ctx, f"{rs_path(ws, rs)}/tests"):
            out["tests"] = await post(ctx, f"{rs_path(ws, rs)}/tests/run")
        return out

    # ------------------------------------------------------------------ reference

    @mcp.tool(annotations=read_only)
    def guide() -> str:
        """How to write Minos rules: the workflow to follow with these tools, a complete example
        and the Rule Graph Document (RGD 1.0) reference (nodes, edges, expressions, operators,
        functions, decision tables, feedback). Read it before writing a rule set."""
        return guide_text()

    # ------------------------------------------------------------------ workspaces

    @mcp.tool(annotations=read_only)
    async def list_workspaces(ctx: Context) -> list[Json]:
        """Workspaces of this Minos installation (slug and name)."""
        items: list[Json] = await get(ctx, "/workspaces")
        return items

    @mcp.tool(annotations=writes)
    async def create_workspace(
        ctx: Context,
        slug: Annotated[str, Field(description="Lower-case identifier, e.g. 'acme'")],
        name: str,
    ) -> Json:
        """Create a workspace, the container of entities and rule sets (one per team or
        domain). Only when no existing workspace fits."""
        out: Json = await post(ctx, "/workspaces", {"slug": slug, "name": name})
        out["studioUrl"] = f"{studio}/w/{_p(slug)}"
        return out

    # ------------------------------------------------------------------ entities

    @mcp.tool(annotations=read_only)
    async def list_entities(ctx: Context, workspace: str) -> list[Json]:
        """Entities of a workspace: the kinds of object that rule sets validate."""
        items: list[Json] = await get(ctx, f"/workspaces/{_p(workspace)}/entities")
        return items

    @mcp.tool(annotations=read_only)
    async def get_entity(ctx: Context, workspace: str, entity: str) -> Json:
        """An entity with its latest JSON Schema: every `$.input` reference of a rule set must
        exist in it. When it references other entities, `references` lists them and
        `resolvedSchema` embeds them (under `$defs`), showing every field a rule can read."""
        base = f"/workspaces/{_p(workspace)}/entities/{_p(entity)}"
        versions = await get(ctx, f"{base}/schemas")
        out: Json = {"entity": entity, "schemaVersions": [v["version"] for v in versions]}
        if versions:
            latest = max(v["version"] for v in versions)
            sv = await get(ctx, f"{base}/schemas/{latest}")
            out["schema"] = sv["schema"]
            out["schemaVersion"] = latest
            if sv.get("references"):
                out["references"] = sv["references"]
                out["resolvedSchema"] = sv["resolved"]
        out["studioUrl"] = entity_url(workspace, entity)
        return out

    async def add_schema(
        ctx: Context | None,
        workspace: str,
        entity: str,
        samples: list[Any] | None,
        json_schema: Json | None,
    ) -> Json:
        if (samples is None) == (json_schema is None):
            raise ToolError("pass exactly one of 'samples' or 'json_schema'")
        body = {"samples": samples} if samples is not None else {"schema": json_schema}
        path = f"/workspaces/{_p(workspace)}/entities/{_p(entity)}/schemas"
        out: Json = await post(ctx, path, body)
        return out

    @mcp.tool(annotations=writes)
    async def create_entity(
        ctx: Context,
        workspace: str,
        key: Annotated[str, Field(description="Identifier in PascalCase, e.g. 'Order'")],
        name: Annotated[str, Field(description="Display name, e.g. 'Ordine'")],
        samples: Samples = None,
        json_schema: Annotated[
            Json | None, Field(description="A JSON Schema, instead of samples")
        ] = None,
        description: str | None = None,
    ) -> Json:
        """Create the entity a rule set validates, with its first schema version inferred from
        `samples` (preferred) or given as `json_schema`. A `json_schema` may use other entities
        as field types with `{"$ref": "entity:<key>"}` (see `guide`)."""
        entities = f"/workspaces/{_p(workspace)}/entities"
        existing = {e["key"] for e in await get(ctx, entities)}
        if key in existing:
            # A previous attempt may have created the entity and then failed on its schema:
            # retrying completes it, but an entity that already has a schema is not touched.
            if await get(ctx, f"{entities}/{_p(key)}/schemas"):
                raise ToolError(
                    f"entity {key!r} already exists: use update_entity_schema to change it"
                )
        else:
            await post(ctx, entities, {"key": key, "name": name, "description": description})
        sv = await add_schema(ctx, workspace, key, samples, json_schema)
        return {
            "entity": key,
            "schemaVersion": sv["version"],
            "schema": sv["schema"],
            "studioUrl": entity_url(workspace, key),
        }

    @mcp.tool(annotations=writes)
    async def update_entity_schema(
        ctx: Context,
        workspace: str,
        entity: str,
        samples: Samples = None,
        json_schema: Annotated[
            Json | None, Field(description="A JSON Schema, instead of samples")
        ] = None,
    ) -> Json:
        """Add a schema version to an entity (for example a new field). Existing drafts keep
        their schema version: pass `use_latest_schema` to `update_ruleset` to move them."""
        sv = await add_schema(ctx, workspace, entity, samples, json_schema)
        return {
            "entity": entity,
            "schemaVersion": sv["version"],
            "schema": sv["schema"],
            "studioUrl": entity_url(workspace, entity),
        }

    # ------------------------------------------------------------------ rule sets

    @mcp.tool(annotations=read_only)
    async def list_rulesets(ctx: Context, workspace: str) -> list[Json]:
        """Rule sets of a workspace."""
        items: list[Json] = await get(ctx, f"/workspaces/{_p(workspace)}/rulesets")
        return items

    @mcp.tool(annotations=read_only)
    async def get_ruleset(ctx: Context, workspace: str, ruleset: str) -> Json:
        """A rule set: entity, published versions and environments, and its current draft
        graph (the one to change with `update_ruleset`)."""
        path = rs_path(workspace, ruleset)
        info: Json = await get(ctx, path)
        draft = await get(ctx, f"{path}/draft")
        info["draft"] = {
            "graph": draft["graph"],
            "schemaVersion": draft["schemaVersion"],
            "lockVersion": draft["lockVersion"],
        }
        info["tests"] = [t["name"] for t in await get(ctx, f"{path}/tests")]
        info["studioUrl"] = ruleset_url(workspace, ruleset)
        return info

    @mcp.tool(annotations=writes)
    async def create_ruleset(
        ctx: Context,
        workspace: str,
        key: Annotated[str, Field(description="Lower case with dots, e.g. 'shop.order.basic'")],
        name: Annotated[str, Field(description="Display name")],
        entity: Annotated[str, Field(description="Key of the entity it validates")],
        graph: Graph,
        description: str | None = None,
    ) -> Json:
        """Create a rule set and save `graph` as its draft (against the entity's latest schema).
        Returns the validation result: fix the issues with `update_ruleset` until it is valid.
        Not published: the user reviews and publishes it from `studioUrl`."""
        await post(
            ctx,
            f"/workspaces/{_p(workspace)}/rulesets",
            {
                "key": key,
                "name": name,
                "entity": entity,
                "description": description,
                "graph": _graph(graph),
            },
        )
        return await checked(ctx, workspace, key)

    @mcp.tool(annotations=writes)
    async def update_ruleset(
        ctx: Context,
        workspace: str,
        ruleset: str,
        graph: Graph,
        use_latest_schema: Annotated[
            bool, Field(description="Move the draft to the entity's latest schema version")
        ] = False,
        lock_version: Annotated[
            int | None,
            Field(description="draft.lockVersion from get_ruleset: the save fails if it changed"),
        ] = None,
    ) -> Json:
        """Replace the draft graph of a rule set (send the whole graph, from `get_ruleset`).
        Pass `lock_version` from `get_ruleset`: if someone saved the draft since, the update
        fails instead of overwriting their change; read it again and reapply yours.
        Returns the validation result and, when valid, the test results."""
        body: Json = {"graph": _graph(graph)}
        path = rs_path(workspace, ruleset)
        if lock_version is not None:
            etag = f'"{lock_version}"'
        else:
            etag = (await call(ctx, "GET", f"{path}/draft")).headers["ETag"]
        if use_latest_schema:
            info = await get(ctx, path)
            versions = await get(
                ctx, f"/workspaces/{_p(workspace)}/entities/{_p(info['entity'])}/schemas"
            )
            if versions:
                body["schemaVersion"] = max(v["version"] for v in versions)
        await call(ctx, "PUT", f"{path}/draft", body, {"If-Match": etag})
        return await checked(ctx, workspace, ruleset)

    @mcp.tool(annotations=read_only)
    async def validate_ruleset(ctx: Context, workspace: str, ruleset: str) -> Json:
        """Compile the draft against the entity schema: structural and type issues, warnings."""
        return await checked(ctx, workspace, ruleset)

    @mcp.tool(annotations=read_only)
    async def simulate_ruleset(
        ctx: Context,
        workspace: str,
        ruleset: str,
        input: Annotated[Any, Field(description="The object to validate")],
        reference_date: Annotated[
            str | None, Field(description="YYYY-MM-DD used by today() and age()")
        ] = None,
        locale: Annotated[str | None, Field(description="Language of the messages")] = None,
    ) -> Json:
        """Run the draft on an input: outcome (valid/invalid/warning/error), feedback messages,
        result and the path of nodes taken. Nothing is stored."""
        options: Json = {"trace": "summary"}
        if reference_date:
            options["referenceDate"] = reference_date
        if locale:
            options["locale"] = locale
        result: Json = await post(
            ctx, f"{rs_path(workspace, ruleset)}/simulate", {"input": input, "options": options}
        )
        return result

    @mcp.tool(annotations=writes)
    async def add_test(
        ctx: Context,
        workspace: str,
        ruleset: str,
        name: str,
        input: Annotated[Any, Field(description="The object to validate")],
        expected: Annotated[
            Json,
            Field(
                description=(
                    "What the run must produce, e.g. {'outcome': 'invalid', "
                    "'feedbackCodes': ['ORD_MIN']}; "
                    "keys: outcome, exitNodeId, feedbackCodes, result"
                )
            ),
        ],
        reference_date: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
        replace: Annotated[
            bool, Field(description="Replace a test with the same name (to fix a wrong test)")
        ] = False,
    ) -> Json:
        """Save a regression test on the rule set. Tests must pass for the rule set to be
        published. With replace=true an existing test of that name is overwritten."""
        body = {"name": name, "input": input, "expected": expected, "referenceDate": reference_date}
        path = f"{rs_path(workspace, ruleset)}/tests"
        if replace:
            await call(ctx, "PUT", f"{path}/{_p(name)}", body)
        else:
            await post(ctx, path, body)
        return {"test": name, "studioUrl": ruleset_url(workspace, ruleset)}

    @mcp.tool(annotations=read_only)
    async def run_tests(ctx: Context, workspace: str, ruleset: str) -> Json:
        """Run the saved tests against the draft."""
        result: Json = await post(ctx, f"{rs_path(workspace, ruleset)}/tests/run")
        return result

    return mcp
