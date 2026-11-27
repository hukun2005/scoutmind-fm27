"""V3.3.2-05.2 club linkage provenance and background scan tasks

Revision ID: a9f2c6d31b84
Revises: e7c2b9a41f60
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``player_instances.club_link_source / club_linked_at``：记录俱乐部关联的来源与时间，
  只写可验证的关联（payload / squad_csv / snapshot_backfill / legacy）。
* ``player_snapshots.club_uid``：保留来源直接提供的俱乐部引用，用于可验证回填与状态区分。
* ``transfer_opportunities.scan_token``：分批扫描的安全下线令牌。
* ``background_tasks``：本地后台任务持久化；部分唯一索引保证同存档同锁键只有一个活跃任务。

所有新增列 nullable 或带安全 server_default，不删除/重写任何用户数据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9f2c6d31b84"
down_revision = "e7c2b9a41f60"
branch_labels = None
depends_on = None

ACTIVE_STATUSES = "status IN ('PENDING','RUNNING','CANCELLING')"


def upgrade() -> None:
    with op.batch_alter_table("player_instances") as batch:
        batch.add_column(sa.Column("club_link_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("club_linked_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("player_snapshots") as batch:
        batch.add_column(sa.Column("club_uid", sa.String(length=128), nullable=True))

    with op.batch_alter_table("transfer_opportunities") as batch:
        batch.add_column(sa.Column("scan_token", sa.String(length=36), nullable=True))
    op.create_index(
        "ix_opportunity_save_scan_token", "transfer_opportunities", ["fm_save_id", "scan_token"]
    )

    op.create_table(
        "background_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("task_type", sa.String(length=24), nullable=False),
        sa.Column("lock_key", sa.String(length=16), nullable=False, server_default="scan"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("checkpoint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("source_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_background_task_task_id"),
    )
    op.create_index("ix_background_tasks_fm_save_id", "background_tasks", ["fm_save_id"])
    op.create_index("ix_background_task_save_status", "background_tasks", ["fm_save_id", "status"])
    op.create_index("ix_background_task_type_status", "background_tasks", ["task_type", "status"])
    op.create_index(
        "uq_background_task_active_lock",
        "background_tasks",
        ["fm_save_id", "lock_key"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_STATUSES),
        postgresql_where=sa.text(ACTIVE_STATUSES),
    )


def downgrade() -> None:
    op.drop_index("uq_background_task_active_lock", table_name="background_tasks")
    op.drop_index("ix_background_task_type_status", table_name="background_tasks")
    op.drop_index("ix_background_task_save_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_fm_save_id", table_name="background_tasks")
    op.drop_table("background_tasks")

    op.drop_index("ix_opportunity_save_scan_token", table_name="transfer_opportunities")
    with op.batch_alter_table("transfer_opportunities") as batch:
        batch.drop_column("scan_token")

    with op.batch_alter_table("player_snapshots") as batch:
        batch.drop_column("club_uid")

    with op.batch_alter_table("player_instances") as batch:
        batch.drop_column("club_linked_at")
        batch.drop_column("club_link_source")
