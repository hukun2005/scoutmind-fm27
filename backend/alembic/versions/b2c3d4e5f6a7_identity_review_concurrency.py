"""V3.2.9.2 identity review concurrency and audit

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-26

只新增列与唯一约束，不修改已发布 migration、不删除历史数据：

* ``player_identity_review_items.version``：乐观锁版本，初始 1；
* ``player_identity_review_actions.previous_version`` / ``new_version``：历史可追溯版本变化；
* ``player_identity_review_actions.request_key``：幂等键，同一 review 上唯一（NULL 不受限）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

ITEMS = "player_identity_review_items"
ACTIONS = "player_identity_review_actions"


def upgrade() -> None:
    with op.batch_alter_table(ITEMS) as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    with op.batch_alter_table(ACTIONS) as batch:
        batch.add_column(sa.Column("previous_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("new_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("request_key", sa.String(length=64), nullable=True))
        batch.create_unique_constraint(
            "uq_identity_review_action_request", ["review_id", "request_key"]
        )

    # 全库扫描按 (存档, 实例) 查找当前有效关联；缺索引会退化为逐行全表扫描。
    op.create_index(
        "ix_identity_link_save_instance",
        "player_identity_links",
        ["fm_save_id", "player_instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_identity_link_save_instance", table_name="player_identity_links")
    with op.batch_alter_table(ACTIONS) as batch:
        batch.drop_constraint("uq_identity_review_action_request", type_="unique")
        batch.drop_column("request_key")
        batch.drop_column("new_version")
        batch.drop_column("previous_version")

    with op.batch_alter_table(ITEMS) as batch:
        batch.drop_column("version")
