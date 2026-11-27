"""V3.3.2-05 transfer radar and loan offer terms

Revision ID: e7c2b9a41f60
Revises: c1a4e7f92b30
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``transfer_opportunities``：每个存档/球员/机会类型一份当前快照，可重扫重建。
* ``transfer_opportunity_events``：机会状态变化历史，只追加。
* ``transfer_offers`` 补充租借费、工资承担比例、买断费用与租期（全部 nullable，NULL=未知）。

不新建 player_transfer_intents / strategy_cases：当前数据源没有离队意愿字段，
策略案例由 transfer_history + transfer_fee_components + loan_records 确定性推导。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7c2b9a41f60"
down_revision = "c1a4e7f92b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_opportunities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("opportunity_type", sa.String(length=24), nullable=False),
        sa.Column("verified_status", sa.String(length=12), nullable=False, server_default="confirmed"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("ability_score", sa.Float(), nullable=True),
        sa.Column("squad_fit_score", sa.Float(), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=True),
        sa.Column("financial_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("recommendation_group", sa.String(length=16), nullable=True),
        sa.Column("score_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "player_instance_id", "opportunity_type", name="uq_opportunity_save_instance_type"
        ),
    )
    op.create_index("ix_transfer_opportunities_fm_save_id", "transfer_opportunities", ["fm_save_id"])
    op.create_index(
        "ix_transfer_opportunities_player_instance_id", "transfer_opportunities", ["player_instance_id"]
    )
    op.create_index(
        "ix_opportunity_save_type_active", "transfer_opportunities", ["fm_save_id", "opportunity_type", "active"]
    )
    op.create_index(
        "ix_opportunity_save_primary", "transfer_opportunities", ["fm_save_id", "is_primary", "active"]
    )
    op.create_index("ix_opportunity_save_score", "transfer_opportunities", ["fm_save_id", "overall_score"])
    op.create_index(
        "ix_opportunity_save_instance", "transfer_opportunities", ["fm_save_id", "player_instance_id"]
    )

    op.create_table(
        "transfer_opportunity_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("opportunity_type", sa.String(length=24), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("previous_value", sa.String(length=64), nullable=True),
        sa.Column("new_value", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "player_instance_id", "opportunity_type", "event_type", "observed_at",
            name="uq_opportunity_event_dedup",
        ),
    )
    op.create_index("ix_transfer_opportunity_events_fm_save_id", "transfer_opportunity_events", ["fm_save_id"])
    op.create_index(
        "ix_transfer_opportunity_events_player_instance_id", "transfer_opportunity_events", ["player_instance_id"]
    )
    op.create_index(
        "ix_opportunity_event_save_time", "transfer_opportunity_events", ["fm_save_id", "observed_at"]
    )
    op.create_index(
        "ix_opportunity_event_save_instance", "transfer_opportunity_events", ["fm_save_id", "player_instance_id"]
    )

    with op.batch_alter_table("transfer_offers") as batch:
        batch.add_column(sa.Column("loan_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("wage_contribution_pct", sa.Float(), nullable=True))
        batch.add_column(sa.Column("buy_option_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("buy_obligation_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("loan_months", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transfer_offers") as batch:
        batch.drop_column("loan_months")
        batch.drop_column("buy_obligation_fee")
        batch.drop_column("buy_option_fee")
        batch.drop_column("wage_contribution_pct")
        batch.drop_column("loan_fee")

    op.drop_index("ix_opportunity_event_save_instance", table_name="transfer_opportunity_events")
    op.drop_index("ix_opportunity_event_save_time", table_name="transfer_opportunity_events")
    op.drop_index(
        "ix_transfer_opportunity_events_player_instance_id", table_name="transfer_opportunity_events"
    )
    op.drop_index("ix_transfer_opportunity_events_fm_save_id", table_name="transfer_opportunity_events")
    op.drop_table("transfer_opportunity_events")

    op.drop_index("ix_opportunity_save_instance", table_name="transfer_opportunities")
    op.drop_index("ix_opportunity_save_score", table_name="transfer_opportunities")
    op.drop_index("ix_opportunity_save_primary", table_name="transfer_opportunities")
    op.drop_index("ix_opportunity_save_type_active", table_name="transfer_opportunities")
    op.drop_index("ix_transfer_opportunities_player_instance_id", table_name="transfer_opportunities")
    op.drop_index("ix_transfer_opportunities_fm_save_id", table_name="transfer_opportunities")
    op.drop_table("transfer_opportunities")
