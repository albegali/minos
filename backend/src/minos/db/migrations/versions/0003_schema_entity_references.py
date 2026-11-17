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
    # Schemas that reference other entities cannot be read without their resolved form, and
    # upgrading again could not rebuild it: refuse instead of leaving broken rule sets.
    refs = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM schema_version WHERE json_schema::text LIKE '%\"entity:%'")
    )
    if refs:
        raise RuntimeError(
            f"{refs} schema version(s) reference other entities: the previous release cannot "
            "use them. Remove those versions (or restore a backup) before downgrading."
        )
    op.drop_column("schema_version", "resolved_schema")
