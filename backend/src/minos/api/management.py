"""Management API (control plane): used by Minos Studio, CI pipelines and administrators.

Not latency-critical: requests are validated with Pydantic and every call runs in one
database transaction (committed when the handler returns without error).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, Literal

import orjson
from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from minos import __version__
from minos.control import accounts
from minos.control import service as svc
from minos.control.bundle import export_bundle, import_bundle
from minos.control.diff import diff_graphs
from minos.control.errors import (
    ControlError,
    Forbidden,
    Invalid,
    NotFound,
    TooManyRequests,
    Unauthorized,
)
from minos.control.identity import ORG_ROLES, SESSION_PREFIX, Actor, at_least, normalise_email
from minos.db import (
    ApiClient,
    AuditEvent,
    Entity,
    Invitation,
    Organization,
    RulesetVersion,
    SchemaVersion,
    User,
    UserSession,
    Workspace,
    make_engine,
    make_sessionmaker,
)
from minos.engine import ExecuteOptions
from minos.engine.catalog import catalog
from minos.schema import infer_schema
from minos.settings import Settings

from .common import (
    DEV_PRINCIPAL,
    Principal,
    api_key_from,
    install_cors,
    install_limits,
    json_response,
    problem,
    via_from,
)

# --------------------------------------------------------------------------- request bodies


class WorkspaceIn(BaseModel):
    slug: str
    name: str
    organization: str | None = None


class OrganizationIn(BaseModel):
    slug: str
    name: str


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    organization: str | None = None


class ChooseOrgIn(BaseModel):
    organization: str


class PasswordIn(BaseModel):
    current: str = Field(max_length=1024)
    new: str = Field(max_length=1024)


class AcceptIn(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, max_length=1024)


class SignupIn(BaseModel):
    organization: OrganizationIn
    name: str | None = None
    email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=1024)


class RoleIn(BaseModel):
    role: str


class GrantIn(BaseModel):
    workspace: str
    role: str


class InvitationIn(BaseModel):
    email: str = Field(max_length=320)
    role: str = "member"
    workspaces: list[GrantIn] = Field(default_factory=list, max_length=200)


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
    effectiveFrom: dt.date | None = None
    """Start date of this entry; omitted: applies with no start date."""


class TestIn(BaseModel):
    name: str
    input: Any
    expected: dict[str, Any]
    referenceDate: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str]


# --------------------------------------------------------------------------- serialisers


def _schema_out(
    sv: SchemaVersion, full: bool = True, references: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": sv.version,
        "source": sv.source,
        "hash": sv.hash,
        "createdBy": sv.created_by,
        "createdAt": sv.created_at.isoformat(),
    }
    if full:
        out["schema"] = sv.json_schema
        out["resolved"] = sv.resolved_schema
        out["references"] = references or []
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


def _schedule_out(entries: list[svc.AliasEntry]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        out.setdefault(e.env, []).append(
            {
                "version": e.version,
                "effectiveFrom": e.effective_from.isoformat() if e.effective_from else None,
            }
        )
    return out


def _exec_options(raw: dict[str, Any]) -> ExecuteOptions:
    trace = raw.get("trace", "full")
    if trace not in ("none", "summary", "full"):
        raise Invalid("trace must be none, summary or full")
    return ExecuteOptions(
        trace=trace, locale=raw.get("locale"), reference_date=raw.get("referenceDate")
    )


# --------------------------------------------------------------------------- router


def _key_out(c: ApiClient) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "name": c.name,
        "prefix": c.key_prefix,
        "scopes": c.scopes,
        "createdBy": c.created_by,
        "createdAt": c.created_at.isoformat(),
        "revoked": c.revoked_at is not None,
    }


def _org_out(o: Organization, role: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"slug": o.slug, "name": o.name}
    if role is not None:
        out["role"] = role
    return out


def _invitation_out(i: Invitation, slugs: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "email": i.email,
        "role": i.role,
        "workspaces": [
            {"workspace": slugs.get(uuid.UUID(g["workspace"]), "?"), "role": g["role"]}
            for g in i.workspaces
        ],
        "invitedBy": i.invited_by,
        "createdAt": i.created_at.isoformat(),
        "expiresAt": i.expires_at.isoformat(),
    }


async def _workspace_slugs(s: AsyncSession, org: Organization | None) -> dict[uuid.UUID, str]:
    return {w.id: w.slug for w in await svc.list_workspaces(s, org.id if org else None)}


def _audit_out(e: AuditEvent, slugs: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": e.id,
        "ts": e.ts.isoformat(),
        "actor": e.actor,
        "via": e.via,
        "action": e.action,
        "target": e.target,
        "workspace": slugs.get(e.workspace_id) if e.workspace_id else None,
        "detail": e.detail,
    }


def _audit_query(request: Request) -> svc.AuditQuery:
    q = request.query_params

    def when(name: str) -> dt.datetime | None:
        raw = q.get(name)
        if not raw:
            return None
        try:
            value = dt.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise Invalid(f"{name} must be an ISO date or date-time") from exc
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)

    def number(name: str, default: int | None) -> int | None:
        raw = q.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise Invalid(f"{name} must be an integer") from exc

    return svc.AuditQuery(
        action=q.get("action") or None,
        target=q.get("target") or None,
        actor=q.get("actor") or None,
        via=q.get("via") or None,
        since=when("since"),
        until=when("until"),
        before=number("cursor", None),
        limit=number("limit", 100) or 100,
    )


class LoginThrottle:
    """Slows down password guessing: after ``attempts`` failures for an address within
    ``window_s``, further attempts are refused until the window passes (per process)."""

    MAX_ENTRIES: Final = 10_000

    def __init__(self, attempts: int = 10, window_s: float = 900) -> None:
        self.attempts = attempts
        self.window_s = window_s
        self._failures: dict[str, tuple[int, float]] = {}

    def blocked(self, email: str) -> bool:
        count, since = self._failures.get(email, (0, 0.0))
        if time.monotonic() - since > self.window_s:
            self._failures.pop(email, None)
            return False
        return count >= self.attempts

    def failed(self, email: str) -> None:
        now = time.monotonic()
        count, since = self._failures.get(email, (0, now))
        if now - since > self.window_s:
            count, since = 0, now
        if len(self._failures) >= self.MAX_ENTRIES:
            self._failures.clear()
        self._failures[email] = (count + 1, since)

    def succeeded(self, email: str) -> None:
        self._failures.pop(email, None)


def management_router(
    sessions: async_sessionmaker[AsyncSession],
    require_auth: bool,
    require_tests: bool = False,
    cfg: Settings | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1")
    session_ttl = dt.timedelta(hours=cfg.session_hours if cfg else 12)
    invitation_ttl = dt.timedelta(days=cfg.invitation_days if cfg else 7)
    studio_url = (cfg.studio_url if cfg else "http://localhost:8080").rstrip("/")
    throttle = LoginThrottle()
    allow_signup = cfg.allow_signup if cfg else False

    async def user_principal(s: AsyncSession, session: UserSession, user: User) -> Principal:
        grants = await accounts.access(s, user.id, session.organization_id)
        return Principal(
            user.email,
            None,
            frozenset(),
            kind="user",
            user_id=user.id,
            organization_id=session.organization_id,
            org_role=grants.org_role,
            workspace_roles=grants.workspaces,
            via="studio",
        )

    async def chosen_org(s: AsyncSession, request: Request) -> uuid.UUID:
        """Organization of an administrator's request: ``X-Minos-Organization``, else
        ``default``."""
        slug = request.headers.get("x-minos-organization", "").strip()
        if not slug or slug == svc.DEFAULT_ORGANIZATION:
            return svc.DEFAULT_ORGANIZATION_ID
        return (await accounts.get_organization(s, slug)).id

    async def principal(request: Request) -> Principal:
        """The caller, and the organization its request works in: the session's, the one of
        the key's workspace, or for administrators (admin keys, open installations) the one
        named by ``X-Minos-Organization`` (``default`` otherwise)."""
        if not require_auth:
            async with sessions() as s:
                org = await chosen_org(s, request)
            return dataclasses.replace(DEV_PRINCIPAL, via=via_from(request), organization_id=org)
        key = api_key_from(request)
        async with sessions() as s:
            if key.startswith(SESSION_PREFIX):
                found = await accounts.find_session(s, key)
                if found is None:
                    raise Unauthorized("your session has expired: sign in again")
                return await user_principal(s, *found)
            client = await svc.find_api_client(s, key)
            if client is None:
                raise Unauthorized("invalid or revoked API key")
            if client.workspace_id is not None:
                bound = await s.get(Workspace, client.workspace_id)
                assert bound is not None
                org = bound.organization_id
            else:
                org = await chosen_org(s, request)
        return Principal(
            client.name,
            client.workspace_id,
            frozenset(client.scopes),
            organization_id=org,
            via=via_from(request),
        )

    async def workspace(s: AsyncSession, who: Principal, slug: str, needed: str) -> Workspace:
        if who.organization_id is None:
            raise Invalid("choose an organization first")
        ws = await svc.get_workspace(s, who.organization_id, slug)
        who.require_role(ws, needed)
        return ws

    async def organization(
        s: AsyncSession, who: Principal, slug: str, needed: str = "member"
    ) -> tuple[Organization, str]:
        org = await accounts.get_organization(s, slug)
        role = who.org_role_in(org.id)
        if role is None:
            raise NotFound(f"organization {slug!r} not found")
        if not at_least(role, needed, ORG_ROLES):
            raise Forbidden(f"this needs the {needed!r} role in organization {slug!r}")
        return org, role

    async def signed_in(request: Request) -> tuple[UserSession, User]:
        token = api_key_from(request)
        async with sessions() as s:
            found = await accounts.find_session(s, token)
        if found is None:
            raise Unauthorized("sign in with an e-mail address and password first")
        return found

    async def session_out(
        s: AsyncSession, session: UserSession, user: User, token: str | None = None
    ) -> dict[str, Any]:
        orgs = await accounts.list_organizations(s, user.id)
        current = next((o for o, _ in orgs if o.id == session.organization_id), None)
        out: dict[str, Any] = {
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "emails": await accounts.user_emails(s, user),
            },
            "organization": _org_out(current, dict((o.id, r) for o, r in orgs).get(current.id))
            if current
            else None,
            "organizations": [_org_out(o, r) for o, r in orgs],
            "expiresAt": session.expires_at.isoformat(),
        }
        if token is not None:
            out["token"] = token
        return out

    # ---------------------------------------------------------------- sign-in

    @router.post("/auth/login")
    async def login(body: LoginIn) -> Response:
        """E-mail address (any of the account's) and password. With several organizations and
        none named, the session starts with none: choose one with ``POST /auth/organization``."""
        email = normalise_email(body.email) or body.email.strip().lower()
        if throttle.blocked(email):
            raise TooManyRequests("too many failed sign-ins for this address: try again later")
        async with sessions.begin() as s:
            user = await accounts.authenticate(s, email, body.password)
            if user is None:
                throttle.failed(email)
                raise Unauthorized("wrong e-mail address or password")
            throttle.succeeded(email)
            orgs = await accounts.list_organizations(s, user.id)
            chosen: Organization | None = None
            if body.organization:
                chosen = next((o for o, _ in orgs if o.slug == body.organization), None)
                if chosen is None:
                    raise Forbidden(f"you are not a member of organization {body.organization!r}")
            elif len(orgs) == 1:
                chosen = orgs[0][0]
            session, token = await accounts.create_session(s, user, chosen, session_ttl)
            await svc.audit(s, Actor(f"user:{user.email}", "studio"), "user.login", email, chosen)
            out = await session_out(s, session, user, token)
        return json_response(out)

    @router.post("/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        session, _ = await signed_in(request)
        async with sessions.begin() as s:
            row = await s.get(UserSession, session.id)
            assert row is not None
            await accounts.end_session(s, row)
        return Response(status_code=204)

    @router.get("/auth/me")
    async def me(request: Request) -> Response:
        """Who the caller is: the signed-in user with their organizations, or the API key."""
        token = request.headers.get("authorization", "")
        if token.lower().startswith("bearer ") and token[7:].strip().startswith(SESSION_PREFIX):
            session, user = await signed_in(request)
            async with sessions() as s:
                return json_response({"kind": "user", **await session_out(s, session, user)})
        who = await principal(request)
        return json_response(
            {
                "kind": "apikey",
                "name": who.name,
                "scopes": sorted(who.scopes),
                "admin": who.is_admin(),
            }
        )

    @router.post("/auth/organization")
    async def choose_organization(body: ChooseOrgIn, request: Request) -> Response:
        """Move the session to another of the user's organizations."""
        session, user = await signed_in(request)
        async with sessions.begin() as s:
            org = await accounts.get_organization(s, body.organization)
            if await accounts.org_role(s, user.id, org) is None:
                raise Forbidden(f"you are not a member of organization {body.organization!r}")
            row = await s.get(UserSession, session.id)
            assert row is not None
            row.organization_id = org.id
            out = await session_out(s, row, user)
        return json_response(out)

    @router.put("/auth/password", status_code=204)
    async def change_password(body: PasswordIn, request: Request) -> Response:
        _, user = await signed_in(request)
        async with sessions.begin() as s:
            row = await s.get(User, user.id)
            assert row is not None
            await accounts.change_password(s, row, body.current, body.new)
        return Response(status_code=204)

    @router.get("/auth/invitations/{token}")
    async def invitation(token: str) -> Response:
        """What an invitation link offers (no sign-in needed: the token is the secret)."""
        async with sessions() as s:
            inv, org = await accounts.find_invitation(s, token)
            existing = await accounts.find_user(s, inv.email)
        return json_response(
            {
                "organization": {"slug": org.slug, "name": org.name},
                "email": inv.email,
                "role": inv.role,
                "invitedBy": inv.invited_by,
                "expiresAt": inv.expires_at.isoformat(),
                "accountExists": existing is not None,
            }
        )

    @router.post("/auth/invitations/{token}/accept")
    async def accept(token: str, body: AcceptIn, request: Request) -> Response:
        """Accept an invitation and sign in to its organization:

        * signed in (``Authorization: Bearer mss_...``): the invited address joins the signed-in
          account, which can then sign in with it too;
        * the address has an account: its ``password``;
        * otherwise a new account: ``name`` and ``password``.
        """
        header = request.headers.get("authorization", "")
        current = None
        if header.lower().startswith("bearer ") and header[7:].strip().startswith(SESSION_PREFIX):
            current = await signed_in(request)
        async with sessions.begin() as s:
            inv, org = await accounts.find_invitation(s, token, lock=True)
            if current is not None:
                user = await s.get(User, current[1].id)
                assert user is not None
            else:
                user = await accounts.find_user(s, inv.email)
                if user is not None:
                    if not await accounts.authenticate(s, inv.email, body.password or ""):
                        raise Unauthorized("wrong password for this account")
                else:
                    if not body.name or not body.password:
                        raise Invalid("a new account needs a name and a password")
                    user = await accounts.create_user(s, inv.email, body.name, body.password)
            await accounts.accept_invitation(s, inv, org, user)
            session, new_token = await accounts.create_session(s, user, org, session_ttl)
            out = await session_out(s, session, user, new_token)
        return json_response(out)

    @router.post("/auth/signup", status_code=201)
    async def signup(body: SignupIn, request: Request) -> Response:
        """Register a new organization and become its owner (``MINOS_ALLOW_SIGNUP``):

        * signed in (``Authorization: Bearer mss_...``): the current account owns it;
        * ``email`` of an existing account: its ``password``;
        * otherwise a new account: ``name``, ``email`` and ``password``.

        Returns a session in the new organization.
        """
        if not allow_signup:
            raise Forbidden("registering organizations is disabled on this installation")
        header = request.headers.get("authorization", "")
        current = None
        if header.lower().startswith("bearer ") and header[7:].strip().startswith(SESSION_PREFIX):
            current = await signed_in(request)
        email = ""
        if current is None:
            if not body.email or not body.password:
                raise Invalid("an e-mail address and a password are required")
            email = normalise_email(body.email) or body.email.strip().lower()
            if throttle.blocked(email):
                raise TooManyRequests("too many failed sign-ins for this address: try again later")
        async with sessions.begin() as s:
            if current is not None:
                user = await s.get(User, current[1].id)
                assert user is not None
            else:
                assert body.password is not None
                user = await accounts.find_user(s, email)
                if user is not None:
                    if not await accounts.authenticate(s, email, body.password):
                        throttle.failed(email)
                        raise Unauthorized("this address already has an account: use its password")
                    throttle.succeeded(email)
                else:
                    if not body.name:
                        raise Invalid("a new account needs a name and a password")
                    user = await accounts.create_user(s, email, body.name, body.password)
            actor = Actor(f"user:{user.email}", "studio")
            org = await accounts.create_organization(
                s, actor, body.organization.slug, body.organization.name
            )
            await accounts.add_member(s, actor, org, user, "owner")
            session, token = await accounts.create_session(s, user, org, session_ttl)
            out = await session_out(s, session, user, token)
        return json_response(out, 201)

    # ---------------------------------------------------------------- organizations

    @router.get("/organizations")
    async def list_orgs(request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            if who.is_admin():
                items = await accounts.list_organizations(s)
            elif who.kind == "user" and who.user_id is not None:
                items = await accounts.list_organizations(s, who.user_id)
            else:
                items = []
        return json_response([_org_out(o, r) for o, r in items])

    @router.post("/organizations", status_code=201)
    async def create_org(body: OrganizationIn, request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions.begin() as s:
            org = await accounts.create_organization(s, who.actor, body.slug, body.name)
        return json_response(_org_out(org, None), 201)

    @router.get("/organizations/{org}/members")
    async def members(org: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            o, _ = await organization(s, who, org)
            items = await accounts.list_members(s, o)
        return json_response(items)

    @router.put("/organizations/{org}/members/{user_id}")
    async def set_member(org: str, user_id: uuid.UUID, body: RoleIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            o, role = await organization(s, who, org, "admin")
            await accounts.set_member_role(s, who.actor, role, o, user_id, body.role)
        return json_response({"id": str(user_id), "role": body.role})

    @router.delete("/organizations/{org}/members/{user_id}", status_code=204)
    async def remove_member(org: str, user_id: uuid.UUID, request: Request) -> Response:
        """Remove a member (owners and admins), or leave the organization (yourself)."""
        who = await principal(request)
        async with sessions.begin() as s:
            o, role = await organization(s, who, org)
            await accounts.remove_member(
                s, who.actor, role, o, user_id, self_removal=user_id == who.user_id
            )
        return Response(status_code=204)

    @router.get("/organizations/{org}/invitations")
    async def invitations(org: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            o, _ = await organization(s, who, org, "admin")
            items = await accounts.list_invitations(s, o)
            slugs = await _workspace_slugs(s, o)
        return json_response([_invitation_out(i, slugs) for i in items])

    @router.post("/organizations/{org}/invitations", status_code=201)
    async def invite(org: str, body: InvitationIn, request: Request) -> Response:
        """Invite an address. The response carries the invitation link once: send it to the
        person (Minos sends no e-mail)."""
        who = await principal(request)
        async with sessions.begin() as s:
            o, role = await organization(s, who, org, "admin")
            inv, token = await accounts.create_invitation(
                s,
                who.actor,
                role,
                o,
                body.email,
                body.role,
                [(g.workspace, g.role) for g in body.workspaces],
                invitation_ttl,
            )
            slugs = await _workspace_slugs(s, o)
        out = _invitation_out(inv, slugs)
        out["token"] = token
        out["url"] = f"{studio_url}/invite/{token}"
        return json_response(out, 201)

    @router.delete("/organizations/{org}/invitations/{inv_id}", status_code=204)
    async def revoke_invitation(org: str, inv_id: uuid.UUID, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            o, role = await organization(s, who, org, "admin")
            await accounts.revoke_invitation(s, who.actor, role, o, inv_id)
        return Response(status_code=204)

    @router.get("/organizations/{org}/audit")
    async def org_audit(org: str, request: Request) -> Response:
        """Events of the organization and of all its workspaces."""
        who = await principal(request)
        query = _audit_query(request)
        async with sessions() as s:
            o, _ = await organization(s, who, org, "admin")
            events, cursor = await svc.list_audit(s, query, organization=o)
            slugs = await _workspace_slugs(s, o)
        return json_response({"items": [_audit_out(e, slugs) for e in events], "next": cursor})

    @router.get("/admin/audit")
    async def admin_audit(request: Request, scope: str = "all") -> Response:
        """Every event (``scope=all``) or only those of no organization (``scope=global``:
        admin keys, organizations created); administrators of the installation only."""
        who = await principal(request)
        who.require("admin")
        if scope not in ("all", "global"):
            raise Invalid("scope must be all or global")
        query = _audit_query(request)
        async with sessions() as s:
            events, cursor = await svc.list_audit(s, query, global_only=scope == "global")
            slugs = await _workspace_slugs(s, None)
        return json_response({"items": [_audit_out(e, slugs) for e in events], "next": cursor})

    # ---------------------------------------------------------------- workspaces & keys

    @router.get("/workspaces")
    async def list_workspaces(request: Request) -> Response:
        """The workspaces the caller can open, with their role. Users see those of the
        organization of their session."""
        who = await principal(request)
        async with sessions() as s:
            if who.kind == "user":
                items = (
                    await svc.list_workspaces(s, who.organization_id) if who.organization_id else []
                )
            elif who.is_admin() and not request.headers.get("x-minos-organization"):
                items = await svc.list_workspaces(s)  # administrators: every organization
            else:
                items = await svc.list_workspaces(s, who.organization_id)
            orgs = {o.id: o.slug for o, _ in await accounts.list_organizations(s)}
        out = []
        for w in items:
            role = who.role_in(w)
            if role is not None:
                out.append(
                    {
                        "slug": w.slug,
                        "name": w.name,
                        "organization": orgs.get(w.organization_id),
                        "role": role,
                    }
                )
        return json_response(out)

    @router.post("/workspaces", status_code=201)
    async def create_workspace(body: WorkspaceIn, request: Request) -> Response:
        """In ``organization`` (default: the user's current one; for admin keys and open
        installations, the ``default`` organization). Needs the admin or owner role there."""
        who = await principal(request)
        async with sessions.begin() as s:
            if body.organization:
                slug = body.organization
            else:
                if who.organization_id is None:
                    raise Invalid("choose an organization first")
                org_row = await s.get(Organization, who.organization_id)
                assert org_row is not None
                slug = org_row.slug
            if who.kind == "apikey" and not who.is_admin():
                raise Forbidden("creating workspaces needs an admin key")
            o, _ = await organization(s, who, slug, "admin")
            ws = await svc.create_workspace(s, who.actor, o, body.slug, body.name)
        return json_response(
            {"slug": ws.slug, "name": ws.name, "organization": o.slug, "role": "admin"}, 201
        )

    @router.get("/workspaces/{ws}/members")
    async def workspace_members(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            items = await accounts.list_workspace_members(s, w)
        return json_response(items)

    @router.put("/workspaces/{ws}/members/{user_id}")
    async def set_workspace_member(
        ws: str, user_id: uuid.UUID, body: RoleIn, request: Request
    ) -> Response:
        """Give a member of the organization a role in this workspace."""
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "admin")
            await accounts.set_workspace_role(s, who.actor, w, user_id, body.role)
        return json_response({"id": str(user_id), "role": body.role})

    @router.delete("/workspaces/{ws}/members/{user_id}", status_code=204)
    async def remove_workspace_member(ws: str, user_id: uuid.UUID, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "admin")
            await accounts.remove_workspace_role(s, who.actor, w, user_id)
        return Response(status_code=204)

    @router.post("/admin/api-keys", status_code=201)
    async def create_admin_key(body: ApiKeyIn, request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions.begin() as s:
            client, key = await svc.create_api_client(s, who.actor, None, body.name, body.scopes)
        return json_response({"id": str(client.id), "key": key, "scopes": client.scopes}, 201)

    @router.get("/admin/api-keys")
    async def list_admin_keys(request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions() as s:
            items = await svc.list_api_clients(s, None)
        return json_response([_key_out(c) for c in items])

    @router.delete("/admin/api-keys/{key_id}", status_code=204)
    async def revoke_admin_key(key_id: uuid.UUID, request: Request) -> Response:
        who = await principal(request)
        who.require("admin")
        async with sessions.begin() as s:
            await svc.revoke_api_client(s, who.actor, None, key_id)
        return Response(status_code=204)

    @router.get("/workspaces/{ws}/api-keys")
    async def list_keys(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "admin")
            items = await svc.list_api_clients(s, w)
        return json_response([_key_out(c) for c in items])

    @router.post("/workspaces/{ws}/api-keys", status_code=201)
    async def create_key(ws: str, body: ApiKeyIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "admin")
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
            w = await workspace(s, who, ws, "admin")
            await svc.revoke_api_client(s, who.actor, w, key_id)
        return Response(status_code=204)

    @router.get("/workspaces/{ws}/audit")
    async def audit(ws: str, request: Request) -> Response:
        """``?action=&target=&actor=&via=&since=&until=&limit=&cursor=``; newest first, the
        ``next`` cursor of a page fetches the following one."""
        who = await principal(request)
        query = _audit_query(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "admin")
            events, cursor = await svc.list_audit(s, query, workspace=w)
        return json_response(
            {"items": [_audit_out(e, {w.id: w.slug}) for e in events], "next": cursor}
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
            w = await workspace(s, who, ws, "viewer")
            items = await svc.list_entities(s, w)
        return json_response(
            [{"key": e.key, "name": e.name, "description": e.description} for e in items]
        )

    @router.post("/workspaces/{ws}/entities", status_code=201)
    async def create_entity(ws: str, body: EntityIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "author")
            e = await svc.create_entity(s, who.actor, w, body.key, body.name, body.description)
        return json_response({"key": e.key, "name": e.name, "description": e.description}, 201)

    @router.get("/workspaces/{ws}/entities/{entity}")
    async def get_entity(ws: str, entity: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            e = await svc.get_entity(s, w, entity)
            used_by = await svc.entities_referencing(s, w, e)
        return json_response(
            {"key": e.key, "name": e.name, "description": e.description, "usedBy": used_by}
        )

    @router.get("/workspaces/{ws}/entities/{entity}/schemas")
    async def list_schemas(ws: str, entity: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            e = await svc.get_entity(s, w, entity)
            items = await svc.list_schema_versions(s, e)
        return json_response([_schema_out(sv, full=False) for sv in items])

    @router.get("/workspaces/{ws}/entities/{entity}/schemas/{version}")
    async def get_schema(ws: str, entity: str, version: int, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            e = await svc.get_entity(s, w, entity)
            sv = await svc.get_schema_version(s, e, version)
            refs = await svc.schema_references(s, w, sv)
        return json_response(_schema_out(sv, references=refs))

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
            w = await workspace(s, who, ws, "author")
            e = await svc.get_entity(s, w, entity)
            sv = await svc.add_schema_version(s, who.actor, w, e, doc, source)
            refs = await svc.schema_references(s, w, sv)
        return json_response(_schema_out(sv, references=refs), 201)

    # ---------------------------------------------------------------- rule sets

    @router.get("/workspaces/{ws}/rulesets")
    async def list_rulesets(ws: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            items = await svc.list_rulesets(s, w)
        return json_response([{"key": r.key, "name": r.name} for r in items])

    @router.post("/workspaces/{ws}/rulesets", status_code=201)
    async def create_ruleset(ws: str, body: RulesetIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "author")
            e = await svc.get_entity(s, w, body.entity)
            rs = await svc.create_ruleset(
                s, who.actor, w, e, body.key, body.name, body.description, body.graph
            )
        return json_response({"key": rs.key, "name": rs.name, "entity": body.entity}, 201)

    @router.get("/workspaces/{ws}/rulesets/{rs}")
    async def get_ruleset(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
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
                "aliases": svc.current_aliases(aliases, dt.datetime.now(dt.UTC).date()),
                "schedule": _schedule_out(aliases),
            }
        )

    @router.get("/workspaces/{ws}/rulesets/{rs}/draft")
    async def get_draft(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
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
            w = await workspace(s, who, ws, "author")
            r = await svc.get_ruleset(s, w, rs)
            d = await svc.save_draft(s, who.actor, w, r, body.graph, lock, body.schemaVersion)
        return json_response(
            {"lockVersion": d.lock_version}, headers={"ETag": f'"{d.lock_version}"'}
        )

    @router.post("/workspaces/{ws}/rulesets/{rs}/validate")
    async def validate(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            v = await svc.validate_draft(s, await svc.get_ruleset(s, w, rs))
        return json_response({"valid": v.valid, "issues": v.issues, "warnings": v.warnings})

    @router.post("/workspaces/{ws}/rulesets/{rs}/simulate")
    async def simulate(ws: str, rs: str, body: SimulateIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            r = await svc.get_ruleset(s, w, rs)
            result = await svc.simulate_draft(s, r, body.input, _exec_options(body.options))
        return json_response(result)

    @router.post("/workspaces/{ws}/rulesets/{rs}/publish", status_code=201)
    async def publish(ws: str, rs: str, body: PublishIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "publisher")
            r = await svc.get_ruleset(s, w, rs)
            version, tests, created = await svc.publish(
                s,
                who.actor,
                w,
                r,
                body.bump,
                body.notes,
                body.promoteTo,
                require_tests=require_tests,
            )
        out = _version_out(version)
        out["tests"] = tests
        out["created"] = created
        if body.promoteTo:
            out["promotedTo"] = body.promoteTo
        # 200: nothing changed since this version, which is returned (and promoted if asked)
        return json_response(out, 201 if created else 200)

    @router.get("/workspaces/{ws}/rulesets/{rs}/versions")
    async def versions(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            items = await svc.list_versions(s, await svc.get_ruleset(s, w, rs))
        return json_response([_version_out(v) for v in items])

    @router.get("/workspaces/{ws}/rulesets/{rs}/versions/{semver}")
    async def version(ws: str, rs: str, semver: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            v = await svc.get_version(s, await svc.get_ruleset(s, w, rs), semver)
        return json_response(_version_out(v, full=True))

    @router.post("/workspaces/{ws}/rulesets/{rs}/versions/{semver}/archive")
    async def archive(ws: str, rs: str, semver: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "publisher")
            v = await svc.archive_version(s, who.actor, w, await svc.get_ruleset(s, w, rs), semver)
        return json_response(_version_out(v))

    @router.get("/workspaces/{ws}/rulesets/{rs}/aliases")
    async def aliases(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            items = await svc.list_aliases(s, await svc.get_ruleset(s, w, rs))
        return json_response(_schedule_out(items))

    @router.put("/workspaces/{ws}/rulesets/{rs}/aliases/{env}")
    async def put_alias(ws: str, rs: str, env: str, body: AliasIn, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "publisher")
            r = await svc.get_ruleset(s, w, rs)
            await svc.set_alias(s, who.actor, w, r, env, body.version, body.effectiveFrom)
        return json_response(
            {
                "env": env,
                "version": body.version,
                "effectiveFrom": body.effectiveFrom.isoformat() if body.effectiveFrom else None,
            }
        )

    @router.delete("/workspaces/{ws}/rulesets/{rs}/aliases/{env}", status_code=204)
    async def delete_alias(
        ws: str, rs: str, env: str, request: Request, effectiveFrom: str | None = None
    ) -> Response:
        """No ``effectiveFrom``: remove the whole environment. ``effectiveFrom=YYYY-MM-DD``:
        remove that scheduled entry; ``effectiveFrom=always``: remove the undated entry."""
        start: dt.date | None = None
        if effectiveFrom not in (None, "always"):
            try:
                start = dt.date.fromisoformat(str(effectiveFrom))
            except ValueError as exc:
                raise Invalid("effectiveFrom must be YYYY-MM-DD or 'always'") from exc
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "publisher")
            await svc.delete_alias(
                s,
                who.actor,
                w,
                await svc.get_ruleset(s, w, rs),
                env,
                start,
                all_entries=effectiveFrom is None,
            )
        return Response(status_code=204)

    @router.get("/workspaces/{ws}/rulesets/{rs}/diff")
    async def diff(ws: str, rs: str, request: Request, to: str = "draft") -> Response:
        """``?from=<version>&to=<version|draft>``: what changes from one to the other."""
        who = await principal(request)
        source = request.query_params.get("from")
        if not source:
            raise Invalid("the 'from' query parameter is required")
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            r = await svc.get_ruleset(s, w, rs)

            async def graph_of(ref: str) -> dict[str, Any]:
                if ref == "draft":
                    return (await svc.get_draft(s, r)).graph
                return (await svc.get_version(s, r, ref)).graph

            result = diff_graphs(await graph_of(source), await graph_of(to))
        return json_response({"from": source, "to": to, **result})

    @router.get("/workspaces/{ws}/rulesets/{rs}/export")
    async def export(ws: str, rs: str, request: Request, version: str | None = None) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            bundle = await export_bundle(s, w, await svc.get_ruleset(s, w, rs), version)
        name = f"{rs}-{version or 'draft'}.minos.json"
        return json_response(
            bundle, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )

    @router.post("/workspaces/{ws}/import")
    async def import_(ws: str, request: Request) -> Response:
        who = await principal(request)
        media = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media != "application/json":
            # A cross-site form or text/plain POST needs no CORS preflight: refusing it keeps
            # other websites from importing into an open installation (CSRF).
            raise Invalid("the bundle must be sent as application/json")
        try:
            bundle = orjson.loads(await request.body())
        except orjson.JSONDecodeError as exc:
            raise Invalid(f"invalid JSON: {exc}") from exc
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "author")
            result = await import_bundle(s, who.actor, w, bundle)
        return json_response(result, 201 if result["created"] else 200)

    # ---------------------------------------------------------------- tests

    @router.get("/workspaces/{ws}/rulesets/{rs}/tests")
    async def list_tests(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
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
            w = await workspace(s, who, ws, "author")
            r = await svc.get_ruleset(s, w, rs)
            t = await svc.add_test(
                s, who.actor, w, r, body.name, body.input, body.expected, body.referenceDate
            )
        return json_response({"name": t.name}, 201)

    @router.put("/workspaces/{ws}/rulesets/{rs}/tests/{name}")
    async def put_test(ws: str, rs: str, name: str, body: TestIn, request: Request) -> Response:
        """Create or replace a test (the name in the path wins over the body's)."""
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "author")
            r = await svc.get_ruleset(s, w, rs)
            t, created = await svc.replace_test(
                s, who.actor, w, r, name, body.input, body.expected, body.referenceDate
            )
        return json_response({"name": t.name, "created": created}, 201 if created else 200)

    @router.delete("/workspaces/{ws}/rulesets/{rs}/tests/{name}", status_code=204)
    async def delete_test(ws: str, rs: str, name: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions.begin() as s:
            w = await workspace(s, who, ws, "author")
            await svc.delete_test(s, who.actor, w, await svc.get_ruleset(s, w, rs), name)
        return Response(status_code=204)

    @router.post("/workspaces/{ws}/rulesets/{rs}/tests/run")
    async def run_tests(ws: str, rs: str, request: Request) -> Response:
        who = await principal(request)
        async with sessions() as s:
            w = await workspace(s, who, ws, "viewer")
            out = await svc.run_draft_tests(s, await svc.get_ruleset(s, w, rs))
        return json_response(out)

    return router


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ControlError)
    async def control_error(request: Request, exc: ControlError) -> Response:
        return problem(exc.status, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(DataError)
    async def data_error(request: Request, exc: DataError) -> Response:
        # Safety net for values the service layer did not check (too long, out of range):
        # the request is wrong, not the server.
        return problem(422, "Unprocessable Content", "a value is too long or out of range")


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
    app.include_router(
        management_router(sessions, cfg.require_auth, cfg.publish_requires_tests, cfg)
    )

    @app.get("/v1/info")
    def info() -> Response:
        return json_response(
            {
                "name": "minos",
                "version": __version__,
                "authRequired": cfg.require_auth,
                "management": True,
                "database": True,
                "signup": cfg.allow_signup,
            }
        )

    install_error_handlers(app)
    install_cors(app, cfg)
    install_limits(app, cfg)
    return app
