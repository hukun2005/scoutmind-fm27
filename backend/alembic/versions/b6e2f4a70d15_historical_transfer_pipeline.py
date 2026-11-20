"""historical transfer pipeline schema

Revision ID: b6e2f4a70d15
Revises: a4d8e1f63c09
Create Date: 2026-11-20

Adds the transfer source registry, per-import batch reports and the extra transaction columns
needed by the historical transfer pipeline (announcement/effective dates, sell-on share, wage
contribution, loan fee, raw payload).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "b6e2f4a70d15"
down_revision = "a4d8e1f63c09"
branch_labels = None
depends_on = None

TRANSFERS = "transfer_history"


def upgrade() -> None:
    op.create_table(
        "transfer_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("license", sa.String(length=128), nullable=True),
        sa.Column("supports_history", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "transfer_import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fm_save_id"], ["fm_saves.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["transfer_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transfer_import_runs_fm_save_id", "transfer_import_runs", ["fm_save_id"])
    op.create_index("ix_transfer_import_runs_source_id", "transfer_import_runs", ["source_id"])
    op.create_index("ix_transfer_import_runs_content_sha256", "transfer_import_runs", ["content_sha256"])

    with op.batch_alter_table(TRANSFERS) as batch:
        batch.add_column(sa.Column("announcement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("sell_on_clause_pct", sa.Float(), nullable=True))
        batch.add_column(sa.Column("wage_contribution", sa.Float(), nullable=True))
        batch.add_column(sa.Column("loan_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("raw_payload_json", sa.Text(), nullable=True))
    op.create_index("ix_transfer_history_source_id", TRANSFERS, ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_transfer_history_source_id", table_name=TRANSFERS)
    with op.batch_alter_table(TRANSFERS) as batch:
        batch.drop_column("raw_payload_json")
        batch.drop_column("source_id")
        batch.drop_column("loan_fee")
        batch.drop_column("wage_contribution")
        batch.drop_column("sell_on_clause_pct")
        batch.drop_column("effective_date")
        batch.drop_column("announcement_date")
    op.drop_index("ix_transfer_import_runs_content_sha256", table_name="transfer_import_runs")
    op.drop_index("ix_transfer_import_runs_source_id", table_name="transfer_import_runs")
    op.drop_index("ix_transfer_import_runs_fm_save_id", table_name="transfer_import_runs")
    op.drop_table("transfer_import_runs")
    op.drop_table("transfer_sources")
