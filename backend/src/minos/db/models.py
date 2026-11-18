"""SQLAlchemy models of the control plane (PostgreSQL).

Documents (schemas, rule graphs, test inputs) are JSONB; identity, versions, permissions and
audit are relational. Published versions are immutable: nothing updates ``ruleset_version``
rows except their ``status``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar, Final

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NOTIFY_CHANNEL = "minos_changes"


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, Any: JSONB}


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Organization(Base):
    """A tenant: its workspaces, members and invitations are invisible to other tenants."""

    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = _uuid()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspace"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(64))
    """Unique within the organization. URLs carry only the slug: the organization comes from
    the caller (session, API key, or ``X-Minos-Organization`` / ``default``)."""
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _created()


class User(Base):
    """A person. One password, any number of e-mail addresses (each one can sign in), and a
    membership in any number of organizations."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    """Primary address: how the audit names the person (``user:<email>``)."""
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    """``None`` for accounts that will sign in through an identity provider only."""
    created_at: Mapped[dt.datetime] = _created()
    disabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class UserEmail(Base):
    """Every address of a user, the primary one included (stored lower-case)."""

    __tablename__ = "user_email"

    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[dt.datetime] = _created()


class OrgMember(Base):
    __tablename__ = "org_member"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # owner | admin | member
    created_at: Mapped[dt.datetime] = _created()


class WorkspaceMember(Base):
    """Role of an organization *member* in one workspace (owners and admins of the
    organization are admins of all its workspaces and need no row here)."""

    __tablename__ = "workspace_member"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # viewer | author | publisher | admin
    created_at: Mapped[dt.datetime] = _created()


class Invitation(Base):
    __tablename__ = "invitation"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(16))
    workspaces: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    """``[{"workspace": <uuid>, "role": <role>}]`` granted on acceptance."""
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """A Studio sign-in. The token is random (``mss_...``) and stored as SHA-256, like API
    keys; it works in one organization at a time (``organization_id``), chosen at sign-in."""

    __tablename__ = "user_session"

    id: Mapped[uuid.UUID] = _uuid()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = _created()
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Entity(Base):
    __tablename__ = "entity"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    __table_args__ = (UniqueConstraint("entity_id", "version"),)

    id: Mapped[uuid.UUID] = _uuid()
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entity.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    json_schema: Mapped[dict[str, Any]]
    """As written, with every entity reference pinned to a version."""
    resolved_schema: Mapped[dict[str, Any]]
    """Standalone form: referenced entities embedded under ``$defs`` (see ``minos.schema.refs``).
    Equal to ``json_schema`` when the schema references no entity."""
    source: Mapped[str] = mapped_column(String(20))  # sample | manual | connector | import
    hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _created()


class Ruleset(Base):
    __tablename__ = "ruleset"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"))
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entity.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()

    draft: Mapped[RulesetDraft | None] = relationship(back_populates="ruleset", lazy="raise")


class RulesetDraft(Base):
    __tablename__ = "ruleset_draft"

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ruleset.id", ondelete="CASCADE"), primary_key=True
    )
    schema_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schema_version.id"))
    graph: Mapped[dict[str, Any]]
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ruleset: Mapped[Ruleset] = relationship(back_populates="draft", lazy="raise")


class RulesetVersion(Base):
    __tablename__ = "ruleset_version"
    __table_args__ = (
        UniqueConstraint("ruleset_id", "semver"),
        Index("ix_ruleset_version_order", "ruleset_id", "major", "minor", "patch"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    ruleset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ruleset.id", ondelete="CASCADE"))
    semver: Mapped[str] = mapped_column(String(32))
    major: Mapped[int] = mapped_column(Integer)
    minor: Mapped[int] = mapped_column(Integer)
    patch: Mapped[int] = mapped_column(Integer)
    schema_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schema_version.id"))
    graph: Mapped[dict[str, Any]]
    hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="published")
    notes: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[dt.datetime] = _created()


ALWAYS: Final = dt.date(1, 1, 1)
"""``effective_from`` of an alias entry that applies with no start date."""


class RulesetAlias(Base):
    """Which version an environment runs. An environment may hold several entries with
    different ``effective_from`` dates: a request runs the latest entry whose date is not
    after its reference date (e.g. new rules from the start of the academic year)."""

    __tablename__ = "ruleset_alias"

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ruleset.id", ondelete="CASCADE"), primary_key=True
    )
    env: Mapped[str] = mapped_column(String(32), primary_key=True)
    effective_from: Mapped[dt.date] = mapped_column(
        Date, primary_key=True, default=ALWAYS, server_default=text("'0001-01-01'")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ruleset_version.id"))
    updated_by: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TestCase(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_case"
    __table_args__ = (UniqueConstraint("ruleset_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid()
    ruleset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ruleset.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    input: Mapped[Any]
    expected: Mapped[dict[str, Any]]
    reference_date: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[dt.datetime] = _created()


class ApiClient(Base):
    """A machine key (CI, execution clients, MCP). Names are unique among the active keys of a
    workspace (and among the global keys), so the audit can name the key."""

    __tablename__ = "api_client"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    created_by: Mapped[str] = mapped_column(String(200))
    """Owner: who created the key."""
    created_at: Mapped[dt.datetime] = _created()
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_workspace_id", "workspace_id", "id"),
        Index("ix_audit_organization_id", "organization_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE")
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    actor: Mapped[str] = mapped_column(String(200))
    """``user:<email>``, ``apikey:<name>`` or ``cli``."""
    via: Mapped[str] = mapped_column(String(16), server_default="api")
    """``studio``, ``api``, ``mcp`` or ``cli``."""
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict[str, Any] | None]
