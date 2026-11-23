"""automatic capture runs

Revision ID: e5a1b2c3d4f6
Revises: d9e3f6a8b124
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5a1b2c3d4f6"
down_revision = "d9e3f6a8b124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capture_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("reader_version", sa.String(length=32), nullable=True),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("scan_scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("scan_id", sa.String(length=64), nullable=True),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id"), nullable=True),
        sa.Column("supplemental", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "game_date", "reader_version", "scan_scope", "revision",
            name="uq_capture_save_date_reader_scope_revision",
        ),
    )
    op.create_index("ix_capture_runs_fm_save_id", "capture_runs", ["fm_save_id"])
    op.create_index("ix_capture_save_status", "capture_runs", ["fm_save_id", "status"])
    op.create_index("ix_capture_save_date", "capture_runs", ["fm_save_id", "game_date"])


def downgrade() -> None:
    op.drop_index("ix_capture_save_date", table_name="capture_runs")
    op.drop_index("ix_capture_save_status", table_name="capture_runs")
    op.drop_index("ix_capture_runs_fm_save_id", table_name="capture_runs")
    op.drop_table("capture_runs")
