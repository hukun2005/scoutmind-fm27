"""V3.2.7.3 写入安全：存档写入门次与导入操作身份。

Revision ID: e1c9a7b3d452
Revises: d4b7c1e2f9a3
Create Date: 2026-11-25

只新增表与可空/带默认值的列；不改历史列、不回填业务数据。
旧数据迁移后 ``generation=0``，旧会话 ``session_epoch`` 取默认 0，不会因此获得新的写入资格：
写入资格仍要求会话状态为 verified 且 gate.current_session_id 指向该会话。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1c9a7b3d452"
down_revision = "d4b7c1e2f9a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("save_sessions") as batch:
        batch.add_column(sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(sa.Column("operation_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("save_generation", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rejected_reason", sa.String(length=64), nullable=True))

    op.create_index("ix_import_jobs_operation_id", "import_jobs", ["operation_id"])
    op.create_index(
        "uq_import_jobs_save_operation",
        "import_jobs",
        ["fm_save_id", "operation_id"],
        unique=True,
    )

    op.create_table(
        "save_write_gates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_session_id", sa.Integer(), nullable=True),
        sa.Column("current_identity_id", sa.Integer(), nullable=True),
        sa.Column("last_switch_at", sa.DateTime(), nullable=True),
        sa.Column("last_switch_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", name="uq_save_write_gate_save"),
    )
    op.create_index("ix_save_write_gates_fm_save_id", "save_write_gates", ["fm_save_id"])


def downgrade() -> None:
    op.drop_index("ix_save_write_gates_fm_save_id", table_name="save_write_gates")
    op.drop_table("save_write_gates")
    op.drop_index("uq_import_jobs_save_operation", table_name="import_jobs")
    op.drop_index("ix_import_jobs_operation_id", table_name="import_jobs")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_column("rejected_reason")
        batch.drop_column("save_generation")
        batch.drop_column("operation_id")
    with op.batch_alter_table("save_sessions") as batch:
        batch.drop_column("session_epoch")
