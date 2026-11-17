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
    # One entry per environment: the one with no start date, else the one in force today,
    # else the next one to start. Dropping every dated entry would make an environment with
    # only dated entries disappear.
    op.execute(
        """
        WITH keep AS (
            SELECT DISTINCT ON (ruleset_id, env) ruleset_id, env, effective_from
            FROM ruleset_alias
            ORDER BY ruleset_id, env,
                (effective_from = DATE '0001-01-01') DESC,
                (effective_from <= CURRENT_DATE) DESC,
                CASE WHEN effective_from <= CURRENT_DATE THEN effective_from END DESC,
                effective_from ASC
        )
        DELETE FROM ruleset_alias a
        WHERE NOT EXISTS (
            SELECT 1 FROM keep k
            WHERE k.ruleset_id = a.ruleset_id AND k.env = a.env
              AND k.effective_from = a.effective_from
        )
        """
    )
    op.drop_constraint("ruleset_alias_pkey", "ruleset_alias", type_="primary")
    op.create_primary_key("ruleset_alias_pkey", "ruleset_alias", ["ruleset_id", "env"])
    op.drop_column("ruleset_alias", "effective_from")
