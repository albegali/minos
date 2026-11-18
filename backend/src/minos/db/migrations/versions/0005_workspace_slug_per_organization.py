"""Workspace slugs are unique within their organization, no longer in the whole installation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("workspace_slug_key", "workspace", type_="unique")
    op.create_unique_constraint(
        "workspace_organization_id_slug_key", "workspace", ["organization_id", "slug"]
    )


def downgrade() -> None:
    clashes = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT slug FROM workspace GROUP BY slug HAVING count(*) > 1) d"
        )
    )
    if clashes:
        raise RuntimeError(
            f"{clashes} workspace slug(s) are used by several organizations: rename them "
            "before downgrading (the previous release needs slugs unique in the installation)."
        )
    op.drop_constraint("workspace_organization_id_slug_key", "workspace", type_="unique")
    op.create_unique_constraint("workspace_slug_key", "workspace", ["slug"])
