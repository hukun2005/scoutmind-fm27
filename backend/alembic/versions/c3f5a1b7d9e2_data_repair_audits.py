"""V3.3.0 automatic data repair audit

Revision ID: c3f5a1b7d9e2
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26

只新增一张审计表与索引，不修改任何历史 migration、不修改既有表：

* ``data_repair_audits`` 记录 Level 1/2 修复前后值与 Level 3 隔离决策；
* ``(import_job_id, entity, row_index, rule_id)`` 唯一，重复导入不会重复写审计。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f5a1b7d9e2"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

TABLE = "data_repair_audits"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id"), nullable=True),
        sa.Column("scan_id", sa.String(length=64), nullable=True),
        sa.Column("entity", sa.String(length=16), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False, server_default="applied"),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "import_job_id", "entity", "row_index", "rule_id", "field",
            name="uq_data_repair_job_row_rule",
        ),
    )
    op.create_index("ix_data_repair_audits_fm_save_id", TABLE, ["fm_save_id"])
    op.create_index("ix_data_repair_audits_import_job_id", TABLE, ["import_job_id"])
    op.create_index("ix_data_repair_save_scan", TABLE, ["fm_save_id", "scan_id"])
    op.create_index("ix_data_repair_save_decision", TABLE, ["fm_save_id", "decision"])


def downgrade() -> None:
    op.drop_index("ix_data_repair_save_decision", table_name=TABLE)
    op.drop_index("ix_data_repair_save_scan", table_name=TABLE)
    op.drop_index("ix_data_repair_audits_import_job_id", table_name=TABLE)
    op.drop_index("ix_data_repair_audits_fm_save_id", table_name=TABLE)
    op.drop_table(TABLE)
