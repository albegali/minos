"""Shared HTTP helpers: JSON responses, problem documents, API-key principals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

import orjson
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minos.control.errors import Forbidden, Unauthorized
from minos.settings import Settings


def json_response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(
        content=orjson.dumps(body, option=orjson.OPT_NON_STR_KEYS),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )


def problem(status: int, title: str, detail: str, **extra: Any) -> Response:
    return Response(
        content=orjson.dumps({"status": status, "title": title, "detail": detail, **extra}),
        status_code=status,
        media_type="application/problem+json",
    )


@dataclass(frozen=True, slots=True)
class Principal:
    """The caller, as identified by its API key."""

    name: str
    workspace_id: uuid.UUID | None
    scopes: frozenset[str]
    workspace: str | None = None
    """Slug of the key's workspace (``None`` for global admin keys)."""

    @property
    def actor(self) -> str:
        return f"apikey:{self.name}"

    def is_admin(self) -> bool:
        return "admin" in self.scopes

    def can_execute(self, workspace: str) -> bool:
        return self.is_admin() or ("exec" in self.scopes and self.workspace == workspace)

    def require(self, scope: str, workspace_id: uuid.UUID | None = None) -> None:
        if self.is_admin():
            return
        if scope not in self.scopes:
            raise Forbidden(f"the API key lacks the {scope!r} scope")
        if workspace_id is not None and workspace_id != self.workspace_id:
            raise Forbidden("the API key belongs to another workspace")


DEV_PRINCIPAL = Principal("dev", None, frozenset({"admin"}))
"""Caller identity when API keys are not required (the default, open installation)."""


def api_key_from(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    raise Unauthorized("missing API key: send 'Authorization: Bearer <key>' or 'X-Api-Key'")


MAX_REQUEST_BYTES: Final = 10 * 1_048_576
"""Largest request body accepted (bundles with their tests are the biggest); the execution
endpoints apply their own 1 MB limit on top."""


class BodyLimit:
    """ASGI middleware: ``413`` for bodies over ``limit`` bytes, declared or streamed, before
    anything reads them into memory."""

    def __init__(self, app: ASGIApp, limit: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._reject(send)
            return
        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = orjson.dumps(
            {
                "type": "about:blank",
                "title": "Payload Too Large",
                "status": 413,
                "detail": f"request body exceeds {self.limit // 1_048_576} MB",
            }
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass


def install_limits(app: FastAPI) -> None:
    app.add_middleware(BodyLimit)


def install_cors(app: FastAPI, cfg: Settings) -> None:
    """Allow a separately hosted Studio (e.g. a Dynamics web resource) to call the API."""
    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=[
                "Authorization",
                "X-Api-Key",
                "Content-Type",
                "If-Match",
                "X-Request-Id",
            ],
            expose_headers=[
                "ETag",
                "X-Ruleset-Version",
                "X-Ruleset-Hash",
                "X-Request-Id",
                "Server-Timing",
            ],
        )
