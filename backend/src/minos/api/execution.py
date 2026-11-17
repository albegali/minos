"""Execution API (hot path).

No Pydantic and no database on the hot path: the body is parsed with orjson, the
deployment is looked up in memory, API keys are resolved from an in-memory cache.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import orjson
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from minos import __version__
from minos.control.errors import ControlError, Unauthorized
from minos.control.keys import hash_key
from minos.db import ALWAYS, asyncpg_dsn, make_engine, make_sessionmaker
from minos.engine import EvaluationError, ExecuteOptions, ExecutionLimitError
from minos.engine.expressions import to_date
from minos.engine.runtime import DEFAULT_TIME_LIMIT_MS
from minos.settings import Settings

from .common import Principal, api_key_from, install_cors, install_limits, json_response, problem
from .exec_docs import OpenApiCache, swagger_html
from .registry import DEFAULT_ENV, DbSync, Deployment, KeyCache, RulesetRegistry

_TRACE_LEVELS = frozenset({"none", "summary", "full"})
log = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_048_576


def execution_router(
    registry: RulesetRegistry,
    sync: DbSync | None,
    require_auth: bool,
    management: bool = False,
    time_limit_ms: float = DEFAULT_TIME_LIMIT_MS,
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

    async def authenticate(
        request: Request, workspace: str | None
    ) -> tuple[Response | None, Principal | None]:
        """``(denial, caller)``; ``workspace=None`` requires an admin key. The caller is
        ``None`` on an open installation."""
        if not require_auth:
            return None, None
        try:
            key = api_key_from(request)
        except Unauthorized as exc:
            return problem(401, "Unauthorized", exc.detail), None
        if sync is None:
            return problem(401, "Unauthorized", "API keys need a database"), None
        principal = await sync.authenticate(key, hash_key(key))
        if principal is None:
            return problem(401, "Unauthorized", "invalid or revoked API key"), None
        if workspace is None:
            if not principal.is_admin():
                return problem(403, "Forbidden", "an admin API key is required"), principal
        elif not principal.can_execute(workspace):
            return (
                problem(403, "Forbidden", "the API key cannot execute in this workspace"),
                principal,
            )
        return None, principal

    async def authorise(request: Request, workspace: str | None) -> Response | None:
        return (await authenticate(request, workspace))[0]

    async def run(
        request: Request,
        choose: Callable[[dt.date | None], Deployment | None],
        missing: str,
        caller: Principal | None,
    ) -> Response:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            stats.reject("too_large")
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
        reference = opts.get("referenceDate")
        on: dt.date | None = None
        if reference is not None:
            try:
                on = to_date(reference)
            except EvaluationError:
                return problem(400, "Bad Request", "'referenceDate' must be an ISO date")

        # The reference date also picks the version when the environment has a schedule.
        dep = choose(on)
        if dep is None:
            return problem(404, "Not Found", missing)

        data = body["input"]
        validate = opts.get("validateSchema", True)
        if validate is not True and caller is not None and not _can_skip_validation(caller):
            # Unvalidated input reaches expressions the type-check assumed well typed: only
            # keys that can already change the rules may ask for it.
            return problem(
                403, "Forbidden", "'validateSchema: false' needs an admin or manage API key"
            )
        validator = dep.validator if validate is not False else None
        if validator is not None and not validator.is_valid(data):
            stats.reject("invalid_input")
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
                    reference_date=on.isoformat() if on is not None else None,
                    request_id=request.headers.get("x-request-id"),
                    time_limit_ms=time_limit_ms,
                ),
            )
        except ExecutionLimitError as exc:
            stats.reject("limit")
            return problem(422, "Execution Limit", str(exc))
        stats.outcomes[result["outcome"]] = stats.outcomes.get(result["outcome"], 0) + 1
        stats.engine_us += result["timing"]["engineUs"]

        headers = {
            "X-Ruleset-Version": dep.compiled.version,
            "X-Ruleset-Hash": dep.hash,
            "X-Request-Id": result["requestId"],
            "Server-Timing": f"engine;dur={result['timing']['engineUs'] / 1000:.3f}",
        }
        return json_response(result, 422 if result["outcome"] == "error" else 200, headers)

    stats = _Stats()

    @router.get("/health")
    def health() -> Response:
        """Liveness, with what an operator should know: ``degraded`` when changes may not be
        picked up promptly (no NOTIFY connection) or a deployment failed to reload."""
        problems = []
        if sync is not None and not sync.listening:
            problems.append("not listening for changes: relying on polling")
        if sync is not None and sync.failing:
            failing = ", ".join(f"{w}/{r}@{e}" for w, r, e in sorted(sync.failing))
            problems.append(f"cannot reload {failing}: serving the previous version")
        body: dict[str, Any] = {
            "status": "degraded" if problems else "ok",
            "deployments": len(registry.schedules()),
        }
        if problems:
            body["problems"] = problems
        return json_response(body)

    @router.get("/metrics")
    async def metrics(request: Request) -> Response:
        """Prometheus text format (admin key when API keys are on)."""
        denied = await authorise(request, None)
        if denied is not None:
            return denied
        lines = [
            "# HELP minos_executions_total Executions by outcome.",
            "# TYPE minos_executions_total counter",
            *(
                f'minos_executions_total{{outcome="{o}"}} {n}'
                for o, n in sorted(stats.outcomes.items())
            ),
            "# HELP minos_engine_seconds_total Engine time spent executing.",
            "# TYPE minos_engine_seconds_total counter",
            f"minos_engine_seconds_total {stats.engine_us / 1e6:.6f}",
            "# HELP minos_rejected_total Requests refused before execution, by reason.",
            "# TYPE minos_rejected_total counter",
            *(
                f'minos_rejected_total{{reason="{r}"}} {n}'
                for r, n in sorted(stats.rejected.items())
            ),
            "# HELP minos_deployments Deployed environments served by this worker.",
            "# TYPE minos_deployments gauge",
            f"minos_deployments {len(registry.schedules())}",
        ]
        if sync is not None:
            lines += [
                "# TYPE minos_reloads_total counter",
                f"minos_reloads_total {sync.reloads}",
                "# TYPE minos_reload_failures_total counter",
                f"minos_reload_failures_total {sync.reload_failures}",
                "# TYPE minos_listening gauge",
                f"minos_listening {int(sync.listening)}",
            ]
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

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
                    "effectiveFrom": None if start == ALWAYS else start.isoformat(),
                }
                for (ws, rs, env), start, d in registry.all()
            ]
        )

    docs = OpenApiCache(registry, require_auth)

    async def caller(request: Request) -> Principal | None:
        """The principal of the request's API key, if it has a valid one."""
        if sync is None:
            return None
        try:
            key = api_key_from(request)
        except Unauthorized:
            return None
        return await sync.authenticate(key, hash_key(key))

    @router.get("/exec/openapi.json", include_in_schema=False)
    async def exec_openapi(request: Request, workspace: str | None = None) -> Response:
        """OpenAPI document of the deployed rule sets; with API keys, only those the key can
        execute (none without a key)."""
        visible: frozenset[str] | None = None if workspace is None else frozenset({workspace})
        note = None
        if require_auth:
            principal = await caller(request)
            if principal is None:
                visible, note = frozenset(), "Authorize with an API key and reload the page."
            elif not principal.is_admin():
                own = frozenset({principal.workspace}) if principal.workspace else frozenset()
                visible = own if visible is None else visible & own
        return json_response(docs.get(visible, note))

    @router.get("/exec/docs", include_in_schema=False)
    def exec_swagger() -> HTMLResponse:
        return HTMLResponse(swagger_html())

    @router.post("/exec/{workspace}/{target}")
    async def execute(workspace: str, target: str, request: Request) -> Response:
        ruleset, _, env = target.partition("@")
        denied, caller = await authenticate(request, workspace)
        if denied is not None:
            return denied
        name = env or DEFAULT_ENV
        return await run(
            request,
            lambda on: registry.get(workspace, ruleset, name, on),
            f"no deployment {workspace}/{ruleset}@{name} for the reference date",
            caller,
        )

    @router.post("/exec/{workspace}/{ruleset}/versions/{semver}")
    async def execute_version(
        workspace: str, ruleset: str, semver: str, request: Request
    ) -> Response:
        denied, caller = await authenticate(request, workspace)
        if denied is not None:
            return denied
        try:
            dep = await sync.load_version(workspace, ruleset, semver) if sync else None
        except Exception:
            log.exception("cannot load %s/%s/%s", workspace, ruleset, semver)
            return problem(
                500, "Internal Server Error", f"version {semver} cannot be loaded by this worker"
            )
        return await run(
            request, lambda on: dep, f"no version {workspace}/{ruleset}/{semver}", caller
        )

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
    app.include_router(
        execution_router(
            rt.registry,
            rt.sync,
            rt.settings.require_auth,
            time_limit_ms=rt.settings.exec_time_limit_ms,
        )
    )
    install_problem_handler(app)
    install_cors(app, rt.settings)
    install_limits(app, rt.settings)
    return app


def install_problem_handler(app: FastAPI) -> None:
    @app.exception_handler(ControlError)
    async def control_error(request: Request, exc: ControlError) -> Response:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)


def _can_skip_validation(caller: Principal) -> bool:
    return caller.is_admin() or "manage" in caller.scopes


@dataclass
class _Stats:
    """Counters of this worker, exposed by /v1/metrics."""

    outcomes: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)
    engine_us: float = 0.0

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1
