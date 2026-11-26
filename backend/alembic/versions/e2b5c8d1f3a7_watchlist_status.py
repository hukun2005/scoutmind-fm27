"""V3.3.1 watchlist workflow status

Revision ID: e2b5c8d1f3a7
Revises: c3f5a1b7d9e2
Create Date: 2026-11-27

只新增一列与一个复合索引，不修改任何历史 migration：

* ``watchlist_items.status`` 记录用户关注状态（watching / preparing / paused / done）；
* ``(watchlist_id, status)`` 索引服务「按名单 + 状态」筛选。

旧数据全部回填为 ``watching``，不改变已有标签、备注与规则生成的关注项。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2b5c8d1f3a7"
down_revision = "c3f5a1b7d9e2"
branch_labels = None
depends_on = None

TABLE = "watchlist_items"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column("status", sa.String(length=16), nullable=False, server_default="watching")
        )
    op.create_index("ix_watchlist_items_list_status", TABLE, ["watchlist_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_list_status", table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("status")
