"""add transfer_history.source_id foreign key

Revision ID: f0a2c6d81b47
Revises: d2f7a91b64e0
Create Date: 2026-11-21

The b6e2f4a70d15 migration added the source_id column without its foreign key, while the ORM
declares one. PostgreSQL validation (SM-040) caught the mismatch. This additive migration adds
the constraint; existing values are either NULL or valid source ids.
"""

from __future__ import annotations

from alembic import op

revision = "f0a2c6d81b47"
down_revision = "d2f7a91b64e0"
branch_labels = None
depends_on = None

TABLE = "transfer_history"
CONSTRAINT = "fk_transfer_history_source_id"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.create_foreign_key(CONSTRAINT, "transfer_sources", ["source_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="foreignkey")
