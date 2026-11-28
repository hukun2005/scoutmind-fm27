"""V3.3.3-02 performance indexes

Revision ID: c4d5e6f7a8b9
Revises: b8e4d1c7f2a9
Create Date: 2026-11-28

只新增索引，不修改历史 migration：

* ``transfer_history(fm_save_id, status, transfer_date)``：转会列表默认筛选（completed）
  与默认排序（transfer_date DESC）一次索引扫描完成。
* ``transfer_history(fm_save_id, status, effective_fee)``：按成交金额排序时避免全表排序。
* ``agent_tasks(fm_save_id, user_id, created_at)``：任务列表按存档 + 用户过滤并按创建时间倒序。
"""

from __future__ import annotations

from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b8e4d1c7f2a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_transfer_save_status_date",
        "transfer_history",
        ["fm_save_id", "status", "transfer_date"],
    )
    op.create_index(
        "ix_transfer_save_status_fee",
        "transfer_history",
        ["fm_save_id", "status", "effective_fee"],
    )
    op.create_index(
        "ix_agent_tasks_save_user_created",
        "agent_tasks",
        ["fm_save_id", "user_id", "created_at"],
    )
    # 注意：不要给 player_snapshots(observed_at) 单独建索引。实测 50 万行时优化器会为
    # UNION 子查询选择"按 observed_at 扫描再回表过滤"，列表反而慢 2~3 倍。


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_save_user_created", table_name="agent_tasks")
    op.drop_index("ix_transfer_save_status_fee", table_name="transfer_history")
    op.drop_index("ix_transfer_save_status_date", table_name="transfer_history")
