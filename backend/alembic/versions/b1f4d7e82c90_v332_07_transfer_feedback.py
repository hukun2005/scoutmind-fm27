"""V3.3.2-07 谈判结果反馈表

Revision ID: b1f4d7e82c90
Revises: a9f2c6d31b84
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``transfer_feedback``：用户确认或导入的谈判结果反馈。``dedupe_key`` 唯一，保证同一
  反馈重复提交不会重复计入学习统计；只有 ``outcome=completed`` 且金额有效时才派生
  成交案例。不新增后台任务表，复用 ``background_tasks``。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1f4d7e82c90"
down_revision = "a9f2c6d31b84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("transfer_offers.id"), nullable=True),
        sa.Column("negotiation_id", sa.Integer(), sa.ForeignKey("transfer_negotiations.id"), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="user_confirmed"),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_transfer_feedback_dedupe"),
    )
    op.create_index("ix_transfer_feedback_fm_save_id", "transfer_feedback", ["fm_save_id"])
    op.create_index(
        "ix_transfer_feedback_player_instance_id", "transfer_feedback", ["player_instance_id"]
    )
    op.create_index(
        "ix_transfer_feedback_save_instance", "transfer_feedback", ["fm_save_id", "player_instance_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_transfer_feedback_save_instance", table_name="transfer_feedback")
    op.drop_index("ix_transfer_feedback_player_instance_id", table_name="transfer_feedback")
    op.drop_index("ix_transfer_feedback_fm_save_id", table_name="transfer_feedback")
    op.drop_table("transfer_feedback")
