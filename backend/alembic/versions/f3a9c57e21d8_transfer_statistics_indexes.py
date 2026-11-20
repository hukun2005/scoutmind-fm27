"""transfer statistics indexes

Revision ID: f3a9c57e21d8
Revises: e7b2d91c4a35
Create Date: 2026-11-20

Price statistics and the transaction summary group by (status, transfer_type) and page by date;
without these indexes SQLite scans the whole transfer table for every request.
"""

from __future__ import annotations

from alembic import op

revision = "f3a9c57e21d8"
down_revision = "e7b2d91c4a35"
branch_labels = None
depends_on = None

TABLE = "transfer_history"


def upgrade() -> None:
    op.create_index("ix_transfer_save_status_type", TABLE, ["fm_save_id", "status", "transfer_type"])
    op.create_index("ix_transfer_save_type_date", TABLE, ["fm_save_id", "transfer_type", "transfer_date"])


def downgrade() -> None:
    op.drop_index("ix_transfer_save_type_date", table_name=TABLE)
    op.drop_index("ix_transfer_save_status_type", table_name=TABLE)
