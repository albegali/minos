"""SQLAlchemy models of the control plane (PostgreSQL).

Documents (schemas, rule graphs, test inputs) are JSONB; identity, versions, permissions and
audit are relational. Published versions are immutable: nothing updates ``ruleset_version``
rows except their ``status``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[uuid.UUID] = _uuid()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _created()


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
    source: Mapped[str] = mapped_column(String(20))  # sample | manual | connector
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


class RulesetAlias(Base):
    __tablename__ = "ruleset_alias"

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ruleset.id", ondelete="CASCADE"), primary_key=True
    )
    env: Mapped[str] = mapped_column(String(32), primary_key=True)
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
    __tablename__ = "api_client"

    id: Mapped[uuid.UUID] = _uuid()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    created_at: Mapped[dt.datetime] = _created()
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_workspace_ts", "workspace_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict[str, Any] | None]
