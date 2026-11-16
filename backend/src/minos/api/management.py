"""Management API (control plane): used by Minos Studio, CI pipelines and administrators.

Not latency-critical: requests are validated with Pydantic and every call runs in one
database transaction (committed when the handler returns without error).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from minos import __version__
from minos.control import service as svc
from minos.control.errors import ControlError, Invalid, Unauthorized
from minos.db import Entity, RulesetVersion, SchemaVersion, make_engine, make_sessionmaker
from minos.engine import ExecuteOptions
from minos.engine.catalog import catalog
from minos.schema import infer_schema
from minos.settings import Settings

from .common import (
    DEV_PRINCIPAL,
    Principal,
    api_key_from,
    install_cors,
    json_response,
    problem,
)

# --------------------------------------------------------------------------- request bodies


class WorkspaceIn(BaseModel):
    slug: str
    name: str


class EntityIn(BaseModel):
    key: str
    name: str
    description: str | None = None


class SchemaIn(BaseModel):
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    samples: list[Any] | None = None
    source: Literal["manual", "sample", "connector"] | None = None


class InferIn(BaseModel):
    samples: list[Any] = Field(min_length=1)
    title: str | None = None


class RulesetIn(BaseModel):
    key: str
    name: str
    entity: str
    description: str | None = None
    graph: dict[str, Any] | None = None


class DraftIn(BaseModel):
    graph: dict[str, Any]
    schemaVersion: int | None = None


class SimulateIn(BaseModel):
    input: Any
    options: dict[str, Any] = Field(default_factory=dict)


class PublishIn(BaseModel):
    bump: Literal["major", "minor", "patch"] = "minor"
    notes: str | None = None
    promoteTo: str | None = None


class AliasIn(BaseModel):
    version: str


class TestIn(BaseModel):
    name: str
    input: Any
    expected: dict[str, Any]
    referenceDate: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str]


# --------------------------------------------------------------------------- serialisers


def _schema_out(sv: SchemaVersion, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": sv.version,
        "source": sv.source,
        "hash": sv.hash,
        "createdBy": sv.created_by,
        "createdAt": sv.created_at.isoformat(),
    }
    if full:
        out["schema"] = sv.json_schema
    return out


def _version_out(v: RulesetVersion, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": v.semver,
        "hash": v.hash,
        "status": v.status,
        "notes": v.notes,
        "publishedBy": v.published_by,
        "publishedAt": v.published_at.isoformat(),
    }
    if full:
        out["graph"] = v.graph
    return out


def _exec_options(raw: dict[str, Any]) -> ExecuteOptions:
    trace = raw.get("trace", "full")
    if trace not in ("none", "summary", "full"):
        raise Invalid("trace must be none, summary or full")
    return ExecuteOptions(
        trace=trace, locale=raw.get("locale"), reference_date=raw.get("referenceDate")
    )


# --------------------------------------------------------------------------- router


def management_router(sessions: async_sessionmaker[AsyncSession], require_auth: bool) -> APIRouter:
    router = APIRouter(prefix="/v1")

    async def principal(request: Request) -> Principal:
        if not require_auth:
            return DEV_PRINCIPAL
        key = api_key_from(request)
        async with sessions() as s:
            client = await svc.find_api_client(s, key)
        if client is None:
            raise Unauthorized("invalid or revoked API key")
        return Principal(client.name, client.workspace_id, frozenset(client.scopes))

    async def workspace(s: AsyncSession, who: Principal, slug: str, scope: str = "manage") -> Any:
        ws = await svc.get_workspace(s, slug)
        who.require(scope, ws.id)
        return ws

    # ---------------------------------------------------------------- workspaces & keys

    @router.get("/workspaces")
    async def list_workspaces(request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            items = await svc.list_workspaces(s)
        visible = [w for w in items if who.is_admin() or w.id == who.workspace_id]
        return json_response([{"slug": w.slug, "name": w.name} for w in visible])

    @router.post("/workspaces", status_code=201)
    async def create_workspace(body: WorkspaceIn, request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions.begin() as s:
            ws = await svc.create_workspace(s, who.actor, body.slug, body.name)
        return json_response({"slug": ws.slug, "name": ws.name}, 201)

    @router.post("/admin/api-keys", status_code=201)
    async def create_admin_key(body: ApiKeyIn, request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions.begin() as s:
            client, key = await svc.create_api_client(s, who.actor, None, body.name, body.scopes)
        return json_response({"id": str(client.id), "key": key, "scopes": client.scopes}, 201)

    @router.get("/workspaces/{ws}/api-keys")
    async def list_keys(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_api_clients(s, w)
        return json_response(
            [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "prefix": c.key_prefix,
                    "scopes": c.scopes,
                    "createdAt": c.created_at.isoformat(),
                    "revoked": c.revoked_at is not None,
                }
                for c in items
            ]
        )

    @router.post("/workspaces/{ws}/api-keys", status_code=201)
    async def create_key(ws: str, body: ApiKeyIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            client, key = await svc.create_api_client(s, who.actor, w, body.name, body.scopes)
        return json_response(
            {
                "id": str(client.id),
                "key": key,
                "prefix": client.key_prefix,
                "scopes": client.scopes,
            },
            201,
        )

    @router.delete("/workspaces/{ws}/api-keys/{key_id}", status_code=204)
    async def revoke_key(ws: str, key_id: uuid.UUID, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            await svc.revoke_api_client(s, who.actor, w, key_id)
        return Response(status_code=204)

    @router.get("/workspaces/{ws}/audit")
    async def audit(ws: str, request: Request, limit: int = 100) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            events = await svc.list_audit(s, w, min(max(limit, 1), 1000))
        return json_response(
            [
                {
                    "ts": e.ts.isoformat(),
                    "actor": e.actor,
                    "action": e.action,
                    "target": e.target,
                    "detail": e.detail,
                }
                for e in events
            ]
        )

    @router.get("/node-types")
    async def node_types(request: Request) -> Response:
        await principal(request)
        return json_response(catalog(), headers={"Cache-Control": "private, max-age=300"})

    # ---------------------------------------------------------------- entities & schemas

    @router.post("/schemas/infer")
    async def infer(body: InferIn, request: Request) -> Response:
        await principal(request)
        try:
            return json_response(infer_schema(body.samples, title=body.title))
        except (TypeError, ValueError) as exc:
            raise Invalid(str(exc)) from exc

    @router.get("/workspaces/{ws}/entities")
    async def list_entities(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_entities(s, w)
        return json_response(
            [{"key": e.key, "name": e.name, "description": e.description} for e in items]
        )

    @router.post("/workspaces/{ws}/entities", status_code=201)
    async def create_entity(ws: str, body: EntityIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            e = await svc.create_entity(s, who.actor, w, body.key, body.name, body.description)
        return json_response({"key": e.key, "name": e.name, "description": e.description}, 201)

    @router.get("/workspaces/{ws}/entities/{entity}/schemas")
    async def list_schemas(ws: str, entity: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            e = await svc.get_entity(s, w, entity)
            items = await svc.list_schema_versions(s, e)
        return json_response([_schema_out(sv, full=False) for sv in items])

    @router.get("/workspaces/{ws}/entities/{entity}/schemas/{version}")
    async def get_schema(ws: str, entity: str, version: int, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            e = await svc.get_entity(s, w, entity)
            sv = await svc.get_schema_version(s, e, version)
        return json_response(_schema_out(sv))

    @router.post("/workspaces/{ws}/entities/{entity}/schemas", status_code=201)
    async def add_schema(ws: str, entity: str, body: SchemaIn, request: Request) -> Response:
        who = await principal(request)
        if (body.schema_ is None) == (body.samples is None):
            raise Invalid("send exactly one of 'schema' or 'samples'")
        if body.samples is not None:
            try:
                doc = infer_schema(body.samples, title=entity)
            except (TypeError, ValueError) as exc:
                raise Invalid(str(exc)) from exc
            source = "sample"
        else:
            assert body.schema_ is not None
            doc, source = body.schema_, body.source or "manual"
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            e = await svc.get_entity(s, w, entity)
            sv = await svc.add_schema_version(s, who.actor, w, e, doc, source)
        return json_response(_schema_out(sv), 201)

    # ---------------------------------------------------------------- rule sets

    @router.get("/workspaces/{ws}/rulesets")
    async def list_rulesets(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_rulesets(s, w)
        return json_response([{"key": r.key, "name": r.name} for r in items])

    @router.post("/workspaces/{ws}/rulesets", status_code=201)
    async def create_ruleset(ws: str, body: RulesetIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            e = await svc.get_entity(s, w, body.entity)
            rs = await svc.create_ruleset(
                s, who.actor, w, e, body.key, body.name, body.description, body.graph
            )
        return json_response({"key": rs.key, "name": rs.name, "entity": body.entity}, 201)

    @router.get("/workspaces/{ws}/rulesets/{rs}")
    async def get_ruleset(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            latest = await svc.latest_version(s, r)
            aliases = await svc.list_aliases(s, r)
            entity = await s.get(Entity, r.entity_id)
        return json_response(
            {
                "key": r.key,
                "name": r.name,
                "entity": entity.key if entity else None,
                "description": r.description,
                "latestVersion": latest.semver if latest else None,
                "aliases": dict(aliases),
            }
        )

    @router.get("/workspaces/{ws}/rulesets/{rs}/draft")
    async def get_draft(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            d = await svc.get_draft(s, r)
            sv = await s.get(SchemaVersion, d.schema_version_id) if d.schema_version_id else None
        return json_response(
            {
                "graph": d.graph,
                "lockVersion": d.lock_version,
                "schemaVersion": sv.version if sv else None,
                "updatedBy": d.updated_by,
                "updatedAt": d.updated_at.isoformat(),
            },
            headers={"ETag": f'"{d.lock_version}"'},
        )

    @router.put("/workspaces/{ws}/rulesets/{rs}/draft")
    async def put_draft(
        ws: str,
        rs: str,
        body: DraftIn,
        request: Request,
        if_match: str | None = Header(default=None),
    ) -> Response:
        who = await principal(request)
        lock = None
        if if_match is not None:
            try:
                lock = int(if_match.strip().strip('"'))
            except ValueError as exc:
                raise Invalid("If-Match must be the draft's ETag") from exc
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            d = await svc.save_draft(s, who.actor, w, r, body.graph, lock, body.schemaVersion)
        return json_response(
            {"lockVersion": d.lock_version}, headers={"ETag": f'"{d.lock_version}"'}
        )

    @router.post("/workspaces/{ws}/rulesets/{rs}/validate")
    async def validate(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            v = await svc.validate_draft(s, await svc.get_ruleset(s, w, rs))
        return json_response({"valid": v.valid, "issues": v.issues, "warnings": v.warnings})

    @router.post("/workspaces/{ws}/rulesets/{rs}/simulate")
    async def simulate(ws: str, rs: str, body: SimulateIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            result = await svc.simulate_draft(s, r, body.input, _exec_options(body.options))
        return json_response(result)

    @router.post("/workspaces/{ws}/rulesets/{rs}/publish", status_code=201)
    async def publish(ws: str, rs: str, body: PublishIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            version, tests = await svc.publish(
                s, who.actor, w, r, body.bump, body.notes, body.promoteTo
            )
        out = _version_out(version)
        out["tests"] = tests
        if body.promoteTo:
            out["promotedTo"] = body.promoteTo
        return json_response(out, 201)

    @router.get("/workspaces/{ws}/rulesets/{rs}/versions")
    async def versions(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_versions(s, await svc.get_ruleset(s, w, rs))
        return json_response([_version_out(v) for v in items])

    @router.get("/workspaces/{ws}/rulesets/{rs}/versions/{semver}")
    async def version(ws: str, rs: str, semver: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            v = await svc.get_version(s, await svc.get_ruleset(s, w, rs), semver)
        return json_response(_version_out(v, full=True))

    @router.get("/workspaces/{ws}/rulesets/{rs}/aliases")
    async def aliases(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_aliases(s, await svc.get_ruleset(s, w, rs))
        return json_response(dict(items))

    @router.put("/workspaces/{ws}/rulesets/{rs}/aliases/{env}")
    async def put_alias(ws: str, rs: str, env: str, body: AliasIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            await svc.set_alias(s, who.actor, w, r, env, body.version)
        return json_response({"env": env, "version": body.version})

    @router.delete("/workspaces/{ws}/rulesets/{rs}/aliases/{env}", status_code=204)
    async def delete_alias(ws: str, rs: str, env: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            await svc.delete_alias(s, who.actor, w, await svc.get_ruleset(s, w, rs), env)
        return Response(status_code=204)

    # ---------------------------------------------------------------- tests

    @router.get("/workspaces/{ws}/rulesets/{rs}/tests")
    async def list_tests(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            items = await svc.list_tests(s, await svc.get_ruleset(s, w, rs))
        return json_response(
            [
                {
                    "name": t.name,
                    "input": t.input,
                    "expected": t.expected,
                    "referenceDate": t.reference_date,
                }
                for t in items
            ]
        )

    @router.post("/workspaces/{ws}/rulesets/{rs}/tests", status_code=201)
    async def add_test(ws: str, rs: str, body: TestIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            r = await svc.get_ruleset(s, w, rs)
            t = await svc.add_test(
                s, who.actor, w, r, body.name, body.input, body.expected, body.referenceDate
            )
        return json_response({"name": t.name}, 201)

    @router.delete("/workspaces/{ws}/rulesets/{rs}/tests/{name}", status_code=204)
    async def delete_test(ws: str, rs: str, name: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws)
            await svc.delete_test(s, who.actor, w, await svc.get_ruleset(s, w, rs), name)
        return Response(status_code=204)

    @router.post("/workspaces/{ws}/rulesets/{rs}/tests/run")
    async def run_tests(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws)
            out = await svc.run_draft_tests(s, await svc.get_ruleset(s, w, rs))
        return json_response(out)

    return router


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ControlError)
    async def control_error(request: Request, exc: ControlError) -> Response:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)


def create_management_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    if not cfg.database_url:
        raise RuntimeError("the management API needs MINOS_DATABASE_URL")
    engine = make_engine(cfg.database_url)
    sessions = make_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="Minos Management API", version=__version__, lifespan=lifespan)
    app.include_router(management_router(sessions, cfg.require_auth))

    @app.get("/v1/info")
    def info() -> Response:
        return json_response(
            {
                "name": "minos",
                "version": __version__,
                "authRequired": cfg.require_auth,
                "management": True,
                "database": True,
            }
        )

    install_error_handlers(app)
    install_cors(app, cfg)
    return app
