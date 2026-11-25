"""V3.2.7.4 导入 Worker 生命周期：queued / cancel_requested / cancelled 与重试计数。

Revision ID: b5d9c2e7f4a1
Revises: e1c9a7b3d452
Create Date: 2026-11-25

只做向后兼容的加列与类型放宽，不改动历史迁移、不删除约束：
* ``import_jobs.status`` 从 16 放宽到 32（``cancel_requested`` 恰好 16 字符，放宽后留出余量）。
* 新增 ``attempt_count`` / ``cancel_requested_at`` / ``cancelled_at``。
* 新增 status 索引，便于 `GET /imports` 与启动恢复按状态筛选。
"""
from alembic import op
import sqlalchemy as sa

revision = "b5d9c2e7f4a1"
down_revision = "e1c9a7b3d452"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_jobs") as batch:
        batch.alter_column(
            "status",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_import_jobs_status", table_name="import_jobs")
    # 旧版本的枚举不含 queued/cancel_requested/cancelled；降级前必须落成旧版本可理解的终态，
    # 否则 VARCHAR(16) 收窄会失败。取消中的任务按「未完成」处理为 failed。
    op.execute("UPDATE import_jobs SET status = 'failed' WHERE status = 'cancel_requested'")
    op.execute("UPDATE import_jobs SET status = 'failed' WHERE status = 'cancelled'")
    op.execute("UPDATE import_jobs SET status = 'running' WHERE status = 'queued'")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_column("cancelled_at")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("attempt_count")
        batch.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
