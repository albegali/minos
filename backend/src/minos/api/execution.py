"""Execution API (hot path).

No Pydantic and no database on the hot path: the body is parsed with orjson, the
deployment is looked up in memory, API keys are resolved from an in-memory cache.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import orjson
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncEngine

from minos import __version__
from minos.control.errors import ControlError, Unauthorized
from minos.control.keys import hash_key
from minos.db import asyncpg_dsn, make_engine, make_sessionmaker
from minos.engine import ExecuteOptions, ExecutionLimitError
from minos.settings import Settings

from .common import api_key_from, install_cors, json_response, problem
from .registry import DEFAULT_ENV, DbSync, Deployment, KeyCache, RulesetRegistry

_TRACE_LEVELS = frozenset({"none", "summary", "full"})
MAX_BODY_BYTES = 1_048_576


def execution_router(
    registry: RulesetRegistry,
    sync: DbSync | None,
    require_auth: bool,
    management: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/info")
    def info() -> Response:
        """Public: lets clients (Minos Studio) adapt to this installation."""
        return json_response(
            {
                "name": "minos",
                "version": __version__,
                "authRequired": require_auth,
                "management": management,
                "database": sync is not None,
            }
        )

    async def authorise(request: Request, workspace: str | None) -> Response | None:
        """``workspace=None`` requires an admin key."""
        if not require_auth:
            return None
        try:
            key = api_key_from(request)
        except Unauthorized as exc:
            return problem(401, "Unauthorized", exc.detail)
        if sync is None:
            return problem(401, "Unauthorized", "API keys need a database")
        principal = await sync.authenticate(key, hash_key(key))
        if principal is None:
            return problem(401, "Unauthorized", "invalid or revoked API key")
        if workspace is None:
            if not principal.is_admin():
                return problem(403, "Forbidden", "an admin API key is required")
        elif not principal.can_execute(workspace):
            return problem(403, "Forbidden", "the API key cannot execute in this workspace")
        return None

    async def run(request: Request, dep: Deployment) -> Response:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return problem(413, "Payload Too Large", "input exceeds 1 MB")
        try:
            body = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            return problem(400, "Bad Request", f"invalid JSON: {exc}")
        if not isinstance(body, dict) or "input" not in body:
            return problem(400, "Bad Request", "body must be an object with an 'input' member")
        opts: Any = body.get("options") or {}
        if not isinstance(opts, dict):
            return problem(400, "Bad Request", "'options' must be an object")
        trace = opts.get("trace", "none")
        if trace not in _TRACE_LEVELS:
            return problem(400, "Bad Request", f"'trace' must be one of {sorted(_TRACE_LEVELS)}")

        data = body["input"]
        validator = dep.validator if opts.get("validateSchema", True) else None
        if validator is not None and not validator.is_valid(data):
            return problem(
                400,
                "Bad Request",
                "input does not match the entity schema",
                errors=validator.errors(data),
            )

        try:
            result = dep.compiled.execute(
                data,
                ExecuteOptions(
                    trace=trace,
                    locale=opts.get("locale"),
                    reference_date=opts.get("referenceDate"),
                    request_id=request.headers.get("x-request-id"),
                ),
            )
        except ExecutionLimitError as exc:
            return problem(422, "Execution Limit", str(exc))

        headers = {
            "X-Ruleset-Version": dep.compiled.version,
            "X-Ruleset-Hash": dep.hash,
            "X-Request-Id": result["requestId"],
            "Server-Timing": f"engine;dur={result['timing']['engineUs'] / 1000:.3f}",
        }
        return json_response(result, 422 if result["outcome"] == "error" else 200, headers)

    @router.get("/health")
    def health() -> Response:
        return json_response({"status": "ok", "deployments": len(registry.all())})

    @router.get("/ready")
    def ready() -> Response:
        if not registry.ready:
            return problem(503, "Service Unavailable", "rule sets are still loading")
        return json_response({"status": "ready"})

    @router.get("/deployments")
    async def deployments(request: Request) -> Response:
        denied = await authorise(request, None)
        if denied is not None:
            return denied
        return json_response(
            [
                {
                    "workspace": ws,
                    "ruleset": rs,
                    "env": env,
                    "version": d.compiled.version,
                    "hash": d.hash,
                }
                for (ws, rs, env), d in registry.all()
            ]
        )

    @router.post("/exec/{workspace}/{target}")
    async def execute(workspace: str, target: str, request: Request) -> Response:
        ruleset, _, env = target.partition("@")
        denied = await authorise(request, workspace)
        if denied is not None:
            return denied
        dep = registry.get(workspace, ruleset, env or DEFAULT_ENV)
        if dep is None:
            return problem(
                404, "Not Found", f"no deployment {workspace}/{ruleset}@{env or DEFAULT_ENV}"
            )
        return await run(request, dep)

    @router.post("/exec/{workspace}/{ruleset}/versions/{semver}")
    async def execute_version(
        workspace: str, ruleset: str, semver: str, request: Request
    ) -> Response:
        denied = await authorise(request, workspace)
        if denied is not None:
            return denied
        dep = await sync.load_version(workspace, ruleset, semver) if sync else None
        if dep is None:
            return problem(404, "Not Found", f"no version {workspace}/{ruleset}/{semver}")
        return await run(request, dep)

    return router


@dataclass
class ExecutionRuntime:
    """Registry plus (optionally) its database synchroniser and engine."""

    settings: Settings
    registry: RulesetRegistry = field(default_factory=RulesetRegistry)
    sync: DbSync | None = None
    engine: AsyncEngine | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> ExecutionRuntime:
        rt = cls(settings)
        if settings.rulesets_dir is not None:
            rt.registry.load_directory(settings.rulesets_dir)
        if settings.database_url:
            rt.engine = make_engine(settings.database_url)
            rt.sync = DbSync(
                rt.registry,
                KeyCache(),
                make_sessionmaker(rt.engine),
                asyncpg_dsn(settings.database_url),
                settings.poll_interval_s,
            )
        return rt

    async def start(self) -> None:
        if self.sync is not None:
            await self.sync.start()
        self.registry.ready = True

    async def stop(self) -> None:
        if self.sync is not None:
            await self.sync.stop()
        if self.engine is not None:
            await self.engine.dispose()


def create_execution_app(settings: Settings | None = None) -> FastAPI:
    rt = ExecutionRuntime.from_settings(settings or Settings.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(title="Minos Execution API", version=__version__, lifespan=lifespan)
    app.state.runtime = rt
    app.include_router(execution_router(rt.registry, rt.sync, rt.settings.require_auth))
    install_problem_handler(app)
    install_cors(app, rt.settings)
    return app


def install_problem_handler(app: FastAPI) -> None:
    @app.exception_handler(ControlError)
    async def control_error(request: Request, exc: ControlError) -> Response:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)
