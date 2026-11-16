"""Execution API (F0 skeleton).

The hot path avoids Pydantic: the body is parsed with orjson, the compiled rule set is
looked up in memory and the result is serialised with orjson.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import orjson
from fastapi import FastAPI, Request
from fastapi.responses import Response

from minos import __version__
from minos.engine import ExecuteOptions, ExecutionLimitError

from .registry import RulesetRegistry

_TRACE_LEVELS = {"none", "summary", "full"}
_MAX_BODY_BYTES = 1_048_576


def _json(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(
        content=orjson.dumps(body),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )


def _problem(status: int, title: str, detail: str) -> Response:
    return _json({"status": status, "title": title, "detail": detail}, status)


def _default_rulesets_dir() -> Path | None:
    env = os.environ.get("MINOS_RULESETS_DIR")
    if env:
        return Path(env)
    candidate = Path(__file__).resolve().parents[4] / "examples" / "rulesets"
    return candidate if candidate.is_dir() else None


def create_app(rulesets_dir: Path | None = None) -> FastAPI:
    registry = RulesetRegistry()
    directory = rulesets_dir or _default_rulesets_dir()
    if directory is not None:
        registry.load_directory(directory)

    app = FastAPI(title="Minos Execution API", version=__version__)
    app.state.registry = registry

    @app.get("/v1/health")
    def health() -> Response:
        return _json({"status": "ok", "rulesets": len(registry.all())})

    @app.get("/v1/rulesets")
    def list_rulesets() -> Response:
        return _json(
            [
                {"ruleset": r.ruleset, "version": r.version, "hash": r.hash, "mode": r.mode}
                for r in registry.all()
            ]
        )

    @app.post("/v1/exec/{ruleset}")
    async def execute(ruleset: str, request: Request) -> Response:
        compiled = registry.get(ruleset)
        if compiled is None:
            return _problem(404, "Not Found", f"unknown ruleset {ruleset!r}")

        raw = await request.body()
        if len(raw) > _MAX_BODY_BYTES:
            return _problem(413, "Payload Too Large", "input exceeds 1 MB")
        try:
            body = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            return _problem(400, "Bad Request", f"invalid JSON: {exc}")
        if not isinstance(body, dict) or "input" not in body:
            return _problem(400, "Bad Request", "body must be an object with an 'input' member")

        opts = body.get("options") or {}
        if not isinstance(opts, dict):
            return _problem(400, "Bad Request", "'options' must be an object")
        trace = opts.get("trace", "none")
        if trace not in _TRACE_LEVELS:
            return _problem(400, "Bad Request", f"'trace' must be one of {sorted(_TRACE_LEVELS)}")

        try:
            result = compiled.execute(
                body["input"],
                ExecuteOptions(
                    trace=trace,
                    locale=opts.get("locale"),
                    reference_date=opts.get("referenceDate"),
                    request_id=request.headers.get("x-request-id"),
                ),
            )
        except ExecutionLimitError as exc:
            return _problem(422, "Execution Limit", str(exc))

        headers = {
            "X-Ruleset-Version": compiled.version,
            "X-Request-Id": result["requestId"],
            "Server-Timing": f"engine;dur={result['timing']['engineUs'] / 1000:.3f}",
        }
        status = 422 if result["outcome"] == "error" else 200
        return _json(result, status, headers)

    return app


app = create_app()
