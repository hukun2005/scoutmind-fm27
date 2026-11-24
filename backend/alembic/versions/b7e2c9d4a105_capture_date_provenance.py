"""capture runs: record where a game date came from and how far it can be trusted

Revision ID: b7e2c9d4a105
Revises: a8c4d5e6f701
Create Date: 2026-11-24

Additive only: three nullable columns on ``capture_runs``. Existing rows keep working and are read as
"unknown" provenance, so a date that was never verified can never be presented as verified.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e2c9d4a105"
down_revision = "a8c4d5e6f701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("capture_runs") as batch:
        batch.add_column(sa.Column("date_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("date_confidence", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("date_read_status", sa.String(length=24), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("capture_runs") as batch:
        batch.drop_column("date_read_status")
        batch.drop_column("date_confidence")
        batch.drop_column("date_source")
