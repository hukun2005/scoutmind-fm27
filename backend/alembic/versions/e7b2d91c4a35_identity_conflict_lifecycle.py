"""identity conflict lifecycle columns

Revision ID: e7b2d91c4a35
Revises: d5a1c7e04f22
Create Date: 2026-11-20

A conflict now carries its own lifecycle: which fields disagreed, how confident the resolution was,
whether it is still open, and when it was closed by later evidence. Existing rows become
``status='open'`` (they were recorded but never reviewed) and keep their old resolution value.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e7b2d91c4a35"
down_revision = "d5a1c7e04f22"
branch_labels = None
depends_on = None

TABLE = "identity_conflicts"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="open"))
        batch.add_column(sa.Column("conflict_fields", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("source_scan_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.create_index("ix_identity_conflicts_status", TABLE, ["status"])


def downgrade() -> None:
    op.drop_index("ix_identity_conflicts_status", table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("resolved_at")
        batch.drop_column("source_scan_id")
        batch.drop_column("confidence")
        batch.drop_column("conflict_fields")
        batch.drop_column("status")
