"""Organizations, users, invitations, sign-in sessions and workspace roles; named key owners;
audit with organization and channel (``via``).

Existing workspaces move into a ``default`` organization (also the home of workspaces created
without one by an admin key or an open installation).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"


def _created() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        _created(),
    )
    op.execute(
        f"INSERT INTO organization (id, slug, name) VALUES ('{DEFAULT_ORG}', 'default', 'Default')"
    )
    op.add_column("workspace", sa.Column("organization_id", UUID(as_uuid=True), nullable=True))
    op.execute(f"UPDATE workspace SET organization_id = '{DEFAULT_ORG}'")
    op.alter_column("workspace", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_workspace_organization",
        "workspace",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_workspace_organization_id", "workspace", ["organization_id"])

    op.create_table(
        "app_user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=True),
        _created(),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "user_email",
        sa.Column("email", sa.String(254), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _created(),
    )
    op.create_index("ix_user_email_user_id", "user_email", ["user_id"])
    op.create_table(
        "org_member",
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
    )
    op.create_index("ix_org_member_user_id", "org_member", ["user_id"])
    op.create_table(
        "workspace_member",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
    )
    op.create_index("ix_workspace_member_user_id", "workspace_member", ["user_id"])
    op.create_table(
        "invitation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("workspaces", JSONB(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(200), nullable=False),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invitation_organization_id", "invitation", ["organization_id"])
    op.create_table(
        "user_session",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"])

    # API keys: an owner, and a name that identifies the key among the active ones.
    op.add_column("api_client", sa.Column("created_by", sa.String(200), nullable=True))
    op.execute("UPDATE api_client SET created_by = 'unknown'")
    op.alter_column("api_client", "created_by", nullable=False)
    op.execute(
        """
        UPDATE api_client SET name = left(name, 180) || ' (' || key_prefix || ')'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY workspace_id, name ORDER BY created_at
                ) AS n
                FROM api_client WHERE revoked_at IS NULL
            ) ranked WHERE n > 1
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_api_client_active_name ON api_client "
        "(coalesce(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), name) "
        "WHERE revoked_at IS NULL"
    )

    # Audit: organization, channel, cursor-friendly indexes.
    op.add_column("audit_event", sa.Column("organization_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_audit_event_organization",
        "audit_event",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "audit_event",
        sa.Column("via", sa.String(16), nullable=False, server_default="api"),
    )
    op.execute(
        "UPDATE audit_event a SET organization_id = w.organization_id "
        "FROM workspace w WHERE a.workspace_id = w.id"
    )
    op.drop_index("ix_audit_workspace_ts", table_name="audit_event")
    op.create_index("ix_audit_workspace_id", "audit_event", ["workspace_id", "id"])
    op.create_index("ix_audit_organization_id", "audit_event", ["organization_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_organization_id", table_name="audit_event")
    op.drop_index("ix_audit_workspace_id", table_name="audit_event")
    op.create_index("ix_audit_workspace_ts", "audit_event", ["workspace_id", "ts"])
    op.drop_column("audit_event", "via")
    op.drop_constraint("fk_audit_event_organization", "audit_event", type_="foreignkey")
    op.drop_column("audit_event", "organization_id")
    op.execute("DROP INDEX ux_api_client_active_name")
    op.drop_column("api_client", "created_by")
    op.drop_table("user_session")
    op.drop_table("invitation")
    op.drop_table("workspace_member")
    op.drop_table("org_member")
    op.drop_table("user_email")
    op.drop_table("app_user")
    op.drop_index("ix_workspace_organization_id", table_name="workspace")
    op.drop_constraint("fk_workspace_organization", "workspace", type_="foreignkey")
    op.drop_column("workspace", "organization_id")
    op.drop_table("organization")
