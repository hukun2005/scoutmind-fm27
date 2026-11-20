"""transfer fee raw amounts and currency audit

Revision ID: d2f7a91b64e0
Revises: b6e2f4a70d15
Create Date: 2026-11-20

SM-022 keeps the original fee strings next to the parsed numbers, so an import can always be
audited back to the source text ("£2.5m" vs 2500000) and to the currency symbol that was used.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d2f7a91b64e0"
down_revision = "b6e2f4a70d15"
branch_labels = None
depends_on = None

TABLE = "transfer_history"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("fee_raw", sa.Text(), nullable=True))
        batch.add_column(sa.Column("addons_raw", sa.Text(), nullable=True))
        batch.add_column(sa.Column("loan_fee_raw", sa.Text(), nullable=True))
        batch.add_column(sa.Column("currency_original", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("currency_original")
        batch.drop_column("loan_fee_raw")
        batch.drop_column("addons_raw")
        batch.drop_column("fee_raw")
