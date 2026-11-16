"""Scheduled aliases: an environment may hold several versions with start dates.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ruleset_alias",
        sa.Column(
            "effective_from", sa.Date(), server_default=sa.text("'0001-01-01'"), nullable=False
        ),
    )
    op.drop_constraint("ruleset_alias_pkey", "ruleset_alias", type_="primary")
    op.create_primary_key(
        "ruleset_alias_pkey", "ruleset_alias", ["ruleset_id", "env", "effective_from"]
    )


def downgrade() -> None:
    # Keep, per environment, the entry that applies with no start date.
    op.execute("DELETE FROM ruleset_alias WHERE effective_from <> DATE '0001-01-01'")
    op.drop_constraint("ruleset_alias_pkey", "ruleset_alias", type_="primary")
    op.create_primary_key("ruleset_alias_pkey", "ruleset_alias", ["ruleset_id", "env"])
    op.drop_column("ruleset_alias", "effective_from")
