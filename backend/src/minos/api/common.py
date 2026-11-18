"""Shared HTTP helpers: JSON responses, problem documents, API-key principals."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, cast

import orjson
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minos.control.errors import Forbidden, NotFound, Unauthorized
from minos.control.identity import Actor, Via, at_least
from minos.db import Workspace
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
    """The caller: an API key (machines), a signed-in user (Studio), or nobody on an open
    installation (``DEV_PRINCIPAL``, an administrator)."""

    name: str
    """Key name, or the user's primary e-mail address."""
    workspace_id: uuid.UUID | None
    scopes: frozenset[str]
    workspace: str | None = None
    """Slug of the key's workspace (``None`` for global admin keys)."""
    kind: Literal["apikey", "user"] = "apikey"
    user_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    """Users: the organization their session works in."""
    org_role: str | None = None
    workspace_roles: Mapping[uuid.UUID, str] = field(default_factory=dict)
    """Users: their own role in the workspaces of the organization."""
    via: Via = "api"

    @property
    def actor(self) -> Actor:
        if self.kind == "user":
            return Actor(f"user:{self.name}", self.via)
        return Actor(f"apikey:{self.name}", self.via)

    def is_admin(self) -> bool:
        """Administrator of the installation (admin key, or an open installation)."""
        return "admin" in self.scopes

    def can_execute(self, workspace: str) -> bool:
        return self.is_admin() or ("exec" in self.scopes and self.workspace == workspace)

    def require(self, scope: str, workspace_id: uuid.UUID | None = None) -> None:
        if self.is_admin():
            return
        if self.kind == "user":
            raise Forbidden("this needs an administrator of the installation (an admin key)")
        if scope not in self.scopes:
            raise Forbidden(f"the API key lacks the {scope!r} scope")
        if workspace_id is not None and workspace_id != self.workspace_id:
            raise Forbidden("the API key belongs to another workspace")

    def org_role_in(self, organization_id: uuid.UUID) -> str | None:
        """Role in an organization: admins of the installation act as owners."""
        if self.is_admin():
            return "owner"
        if self.kind == "user" and organization_id == self.organization_id:
            return self.org_role
        return None

    def role_in(self, ws: Workspace) -> str | None:
        """Workspace role: a ``manage`` key is admin of its workspace; organization owners and
        admins are admins of all its workspaces."""
        if self.is_admin():
            return "admin"
        if self.kind == "apikey":
            return "admin" if "manage" in self.scopes and ws.id == self.workspace_id else None
        if ws.organization_id != self.organization_id or self.org_role is None:
            return None
        if self.org_role in ("owner", "admin"):
            return "admin"
        return self.workspace_roles.get(ws.id)

    def require_role(self, ws: Workspace, needed: str) -> str:
        role = self.role_in(ws)
        if role is None:
            if self.kind == "user" and ws.organization_id != self.organization_id:
                # Other tenants' workspaces do not exist for this user.
                raise NotFound(f"workspace {ws.slug!r} not found")
            if self.kind == "apikey":
                if "manage" not in self.scopes:
                    raise Forbidden("the API key lacks the 'manage' scope")
                raise Forbidden("the API key belongs to another workspace")
            raise Forbidden(f"you have no role in workspace {ws.slug!r}")
        if not at_least(role, needed):
            raise Forbidden(
                f"this needs the {needed!r} role in workspace {ws.slug!r} (you are {role!r})"
            )
        return role


DEV_PRINCIPAL = Principal("dev", None, frozenset({"admin"}))
"""Caller identity when API keys are not required (the default, open installation)."""


def via_from(request: Request, default: Via = "api") -> Via:
    """The channel a request says it comes from (``X-Minos-Via``: the Studio and the MCP server
    set it); informational, for the audit."""
    raw = request.headers.get("x-minos-via", "").strip().lower()
    return cast(Via, raw) if raw in ("studio", "mcp", "api") else default


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


def hostname(host: str) -> str:
    """``localhost:8000`` -> ``localhost``; ``[::1]:8000`` -> ``::1``."""
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 0 else host
    name, _, _port = host.partition(":") if host.count(":") == 1 else (host, "", "")
    return name


class HostCheck:
    """ASGI middleware for open installations: answer only to the configured host names, so
    that a web page cannot drive the API through DNS rebinding (its requests would carry the
    attacker's host name)."""

    def __init__(self, app: ASGIApp, hosts: tuple[str, ...]) -> None:
        self.app = app
        self.hosts = frozenset(h.lower() for h in hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "*" not in self.hosts:
            raw = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1").lower()
            if hostname(raw) not in self.hosts:
                body = orjson.dumps(
                    {
                        "type": "about:blank",
                        "title": "Misdirected Request",
                        "status": 421,
                        "detail": f"host {raw!r} is not allowed (MINOS_ALLOWED_HOSTS)",
                    }
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 421,
                        "headers": [(b"content-type", b"application/problem+json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def install_limits(app: FastAPI, cfg: Settings | None = None) -> None:
    app.add_middleware(BodyLimit)
    if cfg is not None and not cfg.require_auth:
        app.add_middleware(HostCheck, hosts=cfg.allowed_hosts)


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
                "X-Minos-Via",
                "X-Minos-Organization",
            ],
            expose_headers=[
                "ETag",
                "X-Ruleset-Version",
                "X-Ruleset-Hash",
                "X-Request-Id",
                "Server-Timing",
            ],
        )
