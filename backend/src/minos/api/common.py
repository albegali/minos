"""Shared HTTP helpers: JSON responses, problem documents, API-key principals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import orjson
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

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
