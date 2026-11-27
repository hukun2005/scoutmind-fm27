"""V3.3.2 latest snapshot reference and query indexes

Revision ID: b8f3d2a6c1e9
Revises: e2b5c8d1f3a7
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``player_instances.latest_snapshot_id``：每个实例的最新快照引用，列表/搜索/阵容不再聚合全部历史快照；
  历史数据按 ``(observed_at DESC, id DESC)`` 回填；无快照实例保持 NULL，读取时回退到原聚合。
* ``(fm_save_id, club_id)`` 与 ``(fm_save_id, position)``：球员列表按存档 + 俱乐部/位置过滤。
* ``watchlist_items(player_instance_id)``：按球员反查关注项（详情页备注/关注状态）。
* ``transfer_history(fm_save_id, player_name)``：转会搜索的姓名条件与排序。

不删除任何历史快照，不覆盖原始属性。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8f3d2a6c1e9"
down_revision = "e2b5c8d1f3a7"
branch_labels = None
depends_on = None

BACKFILL = """
UPDATE player_instances
SET latest_snapshot_id = (
    SELECT ps.id
    FROM player_snapshots AS ps
    WHERE ps.player_instance_id = player_instances.id
    ORDER BY ps.observed_at DESC, ps.id DESC
    LIMIT 1
)
"""


def upgrade() -> None:
    with op.batch_alter_table("player_instances") as batch:
        batch.add_column(sa.Column("latest_snapshot_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_player_instances_latest_snapshot",
        "player_instances",
        ["latest_snapshot_id"],
    )
    op.create_index("ix_instance_save_club", "player_instances", ["fm_save_id", "club_id"])
    op.create_index("ix_instance_save_position", "player_instances", ["fm_save_id", "position"])
    op.create_index("ix_watchlist_items_instance", "watchlist_items", ["player_instance_id"])
    op.create_index("ix_transfer_save_player", "transfer_history", ["fm_save_id", "player_name"])
    op.execute(sa.text(BACKFILL))


def downgrade() -> None:
    op.drop_index("ix_transfer_save_player", table_name="transfer_history")
    op.drop_index("ix_watchlist_items_instance", table_name="watchlist_items")
    op.drop_index("ix_instance_save_position", table_name="player_instances")
    op.drop_index("ix_instance_save_club", table_name="player_instances")
    op.drop_index("ix_player_instances_latest_snapshot", table_name="player_instances")
    with op.batch_alter_table("player_instances") as batch:
        batch.drop_column("latest_snapshot_id")
