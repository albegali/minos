"""Entity references: every schema version also stores its resolved (standalone) form.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schema_version", sa.Column("resolved_schema", JSONB(), nullable=True))
    # Existing schemas reference no entity: the resolved form is the schema itself.
    op.execute("UPDATE schema_version SET resolved_schema = json_schema")
    op.alter_column("schema_version", "resolved_schema", nullable=False)


def downgrade() -> None:
    op.drop_column("schema_version", "resolved_schema")
