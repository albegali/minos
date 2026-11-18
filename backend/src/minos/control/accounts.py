"""Organizations, users, memberships, invitations and sign-in sessions.

A user is a person with one password and any number of e-mail addresses; any of them signs
in. Membership is per user, so whichever address someone uses they see all their
organizations and choose one: a session works in one organization at a time. An address joins
an account when the person accepts an invitation sent to it (holding the invitation proves
they read that mailbox).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from minos.db import (
    Invitation,
    Organization,
    OrgMember,
    User,
    UserEmail,
    UserSession,
    Workspace,
    WorkspaceMember,
)

from . import service as svc
from .errors import Conflict, Forbidden, Invalid, NotFound
from .identity import (
    INVITE_PREFIX,
    ORG_ROLES,
    SESSION_PREFIX,
    WORKSPACE_ROLES,
    Actor,
    at_least,
    generate_token,
    hash_password,
    normalise_email,
    password_problem,
    token_hash,
    verify_password,
)

DEFAULT_ORGANIZATION: Final = svc.DEFAULT_ORGANIZATION


def _email(value: str) -> str:
    email = normalise_email(value)
    if email is None:
        raise Invalid(f"{value!r} is not an e-mail address")
    return email


async def _now(s: AsyncSession) -> dt.datetime:
    now: dt.datetime | None = await s.scalar(select(func.now()))
    assert now is not None
    return now


# --------------------------------------------------------------------------- organizations


async def create_organization(s: AsyncSession, actor: Actor, slug: str, name: str) -> Organization:
    svc._check_slug(slug, "organization slug")
    svc._check_name(name, "organization name")
    org = Organization(slug=slug, name=name)
    s.add(org)
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"organization {slug!r} already exists") from exc
    await svc.audit(s, actor, "organization.create", slug, org)
    return org


async def get_organization(s: AsyncSession, slug: str) -> Organization:
    org = await s.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise NotFound(f"organization {slug!r} not found")
    return org


async def list_organizations(
    s: AsyncSession, user_id: uuid.UUID | None = None
) -> list[tuple[Organization, str | None]]:
    """Every organization (role ``None``), or those of a user with their role."""
    if user_id is None:
        orgs = await s.scalars(select(Organization).order_by(Organization.slug))
        return [(o, None) for o in orgs]
    rows = await s.execute(
        select(Organization, OrgMember.role)
        .join(OrgMember, OrgMember.organization_id == Organization.id)
        .where(OrgMember.user_id == user_id)
        .order_by(Organization.slug)
    )
    return [(o, r) for o, r in rows]


# --------------------------------------------------------------------------- users


async def find_user(s: AsyncSession, email: str) -> User | None:
    """The account an address belongs to (any of its addresses)."""
    normal = normalise_email(email)
    if normal is None:
        return None
    return await s.scalar(
        select(User).join(UserEmail, UserEmail.user_id == User.id).where(UserEmail.email == normal)
    )


async def user_emails(s: AsyncSession, user: User) -> list[str]:
    rows = await s.scalars(
        select(UserEmail.email).where(UserEmail.user_id == user.id).order_by(UserEmail.created_at)
    )
    return list(rows)


async def create_user(s: AsyncSession, email: str, name: str, password: str | None) -> User:
    """A new account; ``password=None`` for one that will only sign in through an identity
    provider."""
    address = _email(email)
    svc._check_name(name, "name")
    password_hash = None
    if password is not None:
        problem = password_problem(password)
        if problem:
            raise Invalid(problem)
        password_hash = await asyncio.to_thread(hash_password, password)
    if await find_user(s, address) is not None:
        raise Conflict(f"an account already uses {address}")
    user = User(email=address, name=name.strip(), password_hash=password_hash)
    s.add(user)
    await s.flush()
    s.add(UserEmail(email=address, user_id=user.id))
    try:
        await s.flush()
    except IntegrityError as exc:
        raise Conflict(f"an account already uses {address}") from exc
    return user


async def link_email(s: AsyncSession, user: User, email: str) -> None:
    """Add an address to an account (no-op if it already has it)."""
    address = _email(email)
    owner = await find_user(s, address)
    if owner is not None and owner.id != user.id:
        raise Conflict(f"{address} belongs to another account: sign in with it to accept")
    if owner is None:
        s.add(UserEmail(email=address, user_id=user.id))
        try:
            await s.flush()
        except IntegrityError as exc:
            raise Conflict(f"{address} belongs to another account") from exc


async def authenticate(s: AsyncSession, email: str, password: str) -> User | None:
    """The account matching an address and password; the same work whether or not the address
    has an account."""
    user = await find_user(s, email)
    stored = user.password_hash if user is not None and user.disabled_at is None else None
    ok = await asyncio.to_thread(verify_password, password, stored)
    return user if ok else None


async def change_password(s: AsyncSession, user: User, current: str, new: str) -> None:
    if not await asyncio.to_thread(verify_password, current, user.password_hash):
        raise Forbidden("the current password is wrong")
    problem = password_problem(new)
    if problem:
        raise Invalid(problem)
    user.password_hash = await asyncio.to_thread(hash_password, new)
    await svc.audit(s, Actor(f"user:{user.email}", "studio"), "user.password", user.email, None)


# --------------------------------------------------------------------------- sessions


async def create_session(
    s: AsyncSession, user: User, org: Organization | None, ttl: dt.timedelta
) -> tuple[UserSession, str]:
    token = generate_token(SESSION_PREFIX)
    digest = token_hash(token)
    assert digest is not None
    session = UserSession(
        token_hash=digest,
        user_id=user.id,
        organization_id=org.id if org else None,
        expires_at=await _now(s) + ttl,
    )
    s.add(session)
    await s.flush()
    return session, token


async def find_session(s: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    digest = token_hash(token)
    if digest is None or not token.startswith(SESSION_PREFIX):
        return None
    row = (
        await s.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == digest,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > func.now(),
                User.disabled_at.is_(None),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def end_session(s: AsyncSession, session: UserSession) -> None:
    session.revoked_at = await _now(s)


@dataclass(frozen=True, slots=True)
class Access:
    """What a user may do in the organization of their session."""

    org_role: str | None = None
    workspaces: dict[uuid.UUID, str] = field(default_factory=dict)


async def access(s: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID | None) -> Access:
    if org_id is None:
        return Access()
    role = await s.scalar(
        select(OrgMember.role).where(
            OrgMember.organization_id == org_id, OrgMember.user_id == user_id
        )
    )
    if role is None:  # removed from the organization since signing in
        return Access()
    grants = await s.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id, Workspace.organization_id == org_id)
    )
    return Access(role, dict(grants.all()))


async def org_role(s: AsyncSession, user_id: uuid.UUID, org: Organization) -> str | None:
    return await s.scalar(
        select(OrgMember.role).where(
            OrgMember.organization_id == org.id, OrgMember.user_id == user_id
        )
    )


# --------------------------------------------------------------------------- members


def _check_org_role(role: str) -> None:
    if role not in ORG_ROLES:
        raise Invalid(f"role must be one of {list(ORG_ROLES)}")


def _check_workspace_role(role: str) -> None:
    if role not in WORKSPACE_ROLES:
        raise Invalid(f"workspace role must be one of {list(WORKSPACE_ROLES)}")


async def add_member(
    s: AsyncSession, actor: Actor, org: Organization, user: User, role: str
) -> None:
    """Make ``user`` a member with ``role``, or raise their role to it if they already are one
    (an invitation never lowers a role)."""
    _check_org_role(role)
    member = await s.get(OrgMember, (org.id, user.id), with_for_update=True)
    if member is None:
        s.add(OrgMember(organization_id=org.id, user_id=user.id, role=role))
        await s.flush()
    elif at_least(role, member.role, ORG_ROLES) and role != member.role:
        member.role = role
    else:
        return
    await svc.audit(s, actor, "member.add", user.email, org, {"role": role})


async def _owners(s: AsyncSession, org: Organization) -> int:
    return int(
        await s.scalar(
            select(func.count()).where(
                OrgMember.organization_id == org.id, OrgMember.role == "owner"
            )
        )
        or 0
    )


def _may_manage(actor_role: str | None, target_role: str, new_role: str | None = None) -> None:
    """Owners manage everyone; admins manage members and admins, never owners."""
    if not at_least(actor_role, "admin", ORG_ROLES):
        raise Forbidden("managing members requires the admin or owner role in the organization")
    if actor_role != "owner" and "owner" in (target_role, new_role):
        raise Forbidden("only owners can manage owners")


async def list_members(s: AsyncSession, org: Organization) -> list[dict[str, Any]]:
    rows = await s.execute(
        select(User, OrgMember.role)
        .join(OrgMember, OrgMember.user_id == User.id)
        .where(OrgMember.organization_id == org.id)
        .order_by(User.name, User.email)
    )
    members = list(rows)
    ids = [u.id for u, _ in members]
    emails: dict[uuid.UUID, list[str]] = {}
    for user_id, email in await s.execute(
        select(UserEmail.user_id, UserEmail.email)
        .where(UserEmail.user_id.in_(ids))
        .order_by(UserEmail.created_at)
    ):
        emails.setdefault(user_id, []).append(email)
    grants: dict[uuid.UUID, list[dict[str, str]]] = {}
    for user_id, slug, role in await s.execute(
        select(WorkspaceMember.user_id, Workspace.slug, WorkspaceMember.role)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(Workspace.organization_id == org.id, WorkspaceMember.user_id.in_(ids))
        .order_by(Workspace.slug)
    ):
        grants.setdefault(user_id, []).append({"workspace": slug, "role": role})
    return [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "emails": emails.get(u.id, [u.email]),
            "role": role,
            "workspaces": grants.get(u.id, []),
            "disabled": u.disabled_at is not None,
        }
        for u, role in members
    ]


async def _member(s: AsyncSession, org: Organization, user_id: uuid.UUID) -> tuple[OrgMember, User]:
    member = await s.get(OrgMember, (org.id, user_id), with_for_update=True)
    user = await s.get(User, user_id)
    if member is None or user is None:
        raise NotFound("member not found")
    return member, user


async def set_member_role(
    s: AsyncSession,
    actor: Actor,
    actor_role: str | None,
    org: Organization,
    user_id: uuid.UUID,
    role: str,
) -> None:
    _check_org_role(role)
    member, user = await _member(s, org, user_id)
    _may_manage(actor_role, member.role, role)
    if member.role == role:
        return
    if member.role == "owner" and await _owners(s, org) == 1:
        raise Conflict("an organization needs at least one owner")
    before = member.role
    member.role = role
    await svc.audit(s, actor, "member.role", user.email, org, {"role": role, "previous": before})


async def remove_member(
    s: AsyncSession,
    actor: Actor,
    actor_role: str | None,
    org: Organization,
    user_id: uuid.UUID,
    *,
    self_removal: bool = False,
) -> None:
    member, user = await _member(s, org, user_id)
    if not self_removal:
        _may_manage(actor_role, member.role)
    if member.role == "owner" and await _owners(s, org) == 1:
        raise Conflict("an organization needs at least one owner")
    await s.delete(member)
    await s.execute(
        delete(WorkspaceMember).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id.in_(
                select(Workspace.id).where(Workspace.organization_id == org.id)
            ),
        )
    )
    await svc.audit(s, actor, "member.remove", user.email, org, {"role": member.role})


# --------------------------------------------------------------------------- workspace roles


async def list_workspace_members(s: AsyncSession, ws: Workspace) -> list[dict[str, Any]]:
    """Everyone with access to a workspace: explicit grants, and the organization's owners and
    admins (``inherited``)."""
    rows = await s.execute(
        select(User, OrgMember.role, WorkspaceMember.role)
        .join(OrgMember, OrgMember.user_id == User.id)
        .outerjoin(
            WorkspaceMember,
            (WorkspaceMember.user_id == User.id) & (WorkspaceMember.workspace_id == ws.id),
        )
        .where(OrgMember.organization_id == ws.organization_id)
        .order_by(User.name, User.email)
    )
    out = []
    for user, org_role_, ws_role in rows:
        inherited = org_role_ in ("owner", "admin")
        if not inherited and ws_role is None:
            continue
        out.append(
            {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": "admin" if inherited else ws_role,
                "inherited": inherited,
            }
        )
    return out


async def set_workspace_role(
    s: AsyncSession, actor: Actor, ws: Workspace, user_id: uuid.UUID, role: str
) -> None:
    _check_workspace_role(role)
    user = await s.get(User, user_id)
    member = await s.get(OrgMember, (ws.organization_id, user_id))
    if user is None or member is None:
        raise NotFound("not a member of the workspace's organization")
    grant = await s.get(WorkspaceMember, (ws.id, user_id), with_for_update=True)
    if grant is None:
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role=role))
    elif grant.role == role:
        return
    else:
        grant.role = role
    await s.flush()
    await svc.audit(s, actor, "workspace.role", f"{ws.slug}:{user.email}", ws, {"role": role})


async def remove_workspace_role(
    s: AsyncSession, actor: Actor, ws: Workspace, user_id: uuid.UUID
) -> None:
    grant = await s.get(WorkspaceMember, (ws.id, user_id))
    user = await s.get(User, user_id)
    if grant is None or user is None:
        raise NotFound("this user has no role of their own in the workspace")
    await s.delete(grant)
    await svc.audit(
        s, actor, "workspace.unrole", f"{ws.slug}:{user.email}", ws, {"role": grant.role}
    )


# --------------------------------------------------------------------------- invitations


async def create_invitation(
    s: AsyncSession,
    actor: Actor,
    actor_role: str | None,
    org: Organization,
    email: str,
    role: str,
    workspaces: list[tuple[str, str]],
    ttl: dt.timedelta,
) -> tuple[Invitation, str]:
    """Invite an address with an organization role and, optionally, workspace roles; the
    token (the secret part of the invitation link) is returned once."""
    address = _email(email)
    _check_org_role(role)
    _may_manage(actor_role, "member", role)
    grants: list[dict[str, str]] = []
    for slug, ws_role in workspaces:
        _check_workspace_role(ws_role)
        try:
            ws = await svc.get_workspace(s, org.id, slug)
        except NotFound:
            raise NotFound(f"workspace {slug!r} not found in organization {org.slug!r}") from None
        grants.append({"workspace": str(ws.id), "role": ws_role})
    user = await find_user(s, address)
    if user is not None and await org_role(s, user.id, org) is not None:
        raise Conflict(f"{address} is already a member of {org.slug!r}")
    now = await _now(s)
    # one pending invitation per address: a new one replaces the previous
    for old in await s.scalars(
        select(Invitation).where(
            Invitation.organization_id == org.id,
            Invitation.email == address,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
    ):
        old.revoked_at = now
    token = generate_token(INVITE_PREFIX)
    digest = token_hash(token)
    assert digest is not None
    invitation = Invitation(
        organization_id=org.id,
        email=address,
        role=role,
        workspaces=grants,
        token_hash=digest,
        invited_by=actor.id[:200],
        expires_at=now + ttl,
    )
    s.add(invitation)
    await s.flush()
    await svc.audit(
        s,
        actor,
        "invitation.create",
        address,
        org,
        {"role": role, "workspaces": [{"workspace": w, "role": r} for w, r in workspaces]},
    )
    return invitation, token


async def list_invitations(s: AsyncSession, org: Organization) -> list[Invitation]:
    """Pending invitations (not accepted, revoked or expired)."""
    return list(
        await s.scalars(
            select(Invitation)
            .where(
                Invitation.organization_id == org.id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > func.now(),
            )
            .order_by(Invitation.created_at)
        )
    )


async def revoke_invitation(
    s: AsyncSession, actor: Actor, actor_role: str | None, org: Organization, inv_id: uuid.UUID
) -> None:
    invitation = await s.get(Invitation, inv_id)
    if invitation is None or invitation.organization_id != org.id:
        raise NotFound("invitation not found")
    _may_manage(actor_role, "member", invitation.role)
    if invitation.revoked_at is None and invitation.accepted_at is None:
        invitation.revoked_at = await _now(s)
        await svc.audit(s, actor, "invitation.revoke", invitation.email, org)


async def find_invitation(
    s: AsyncSession, token: str, *, lock: bool = False
) -> tuple[Invitation, Organization]:
    """A pending invitation by its token; the same error for every kind of unusable token."""
    digest = token_hash(token)
    row = None
    if digest is not None and token.startswith(INVITE_PREFIX):
        query = (
            select(Invitation, Organization)
            .join(Organization, Organization.id == Invitation.organization_id)
            .where(
                Invitation.token_hash == digest,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > func.now(),
            )
        )
        row = (await s.execute(query.with_for_update(of=Invitation) if lock else query)).first()
    if row is None:
        raise NotFound("this invitation is not valid: it was used, revoked or has expired")
    return row[0], row[1]


async def accept_invitation(
    s: AsyncSession, invitation: Invitation, org: Organization, user: User
) -> None:
    """Join ``user`` to the organization; the invited address becomes one of theirs."""
    await link_email(s, user, invitation.email)
    actor = Actor(f"user:{user.email}", "studio")
    await add_member(s, actor, org, user, invitation.role)
    for grant in invitation.workspaces:
        ws = await s.get(Workspace, uuid.UUID(grant["workspace"]))
        if ws is None or ws.organization_id != org.id:  # deleted since
            continue
        current = await s.get(WorkspaceMember, (ws.id, user.id))
        if current is None or not at_least(current.role, grant["role"]):
            await set_workspace_role(s, actor, ws, user.id, grant["role"])
    invitation.accepted_at = await _now(s)
    invitation.accepted_by = user.id
    await svc.audit(
        s, actor, "invitation.accept", invitation.email, org, {"invitedBy": invitation.invited_by}
    )
