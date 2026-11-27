"""V3.3.2-05 AI Transfer Director tables

Revision ID: c1a4e7f92b30
Revises: b8f3d2a6c1e9
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``transfer_status_history``：历史转会状态变化（agreed → completed 等）只追加保留。
* ``transfer_offers`` / ``transfer_negotiations`` / ``negotiation_events``：AI 报价草稿与用户真实谈判记录。
* ``loan_records`` 补充租借费用、工资承担、买断费用与条款状态（全部 nullable，NULL=未知）。
* ``transfer_fee_components`` 补充条款级来源、可信度与付款计划。

合同字段继续使用 ``player_snapshots``，费用继续使用 ``transfer_history`` + ``transfer_fee_components``；
不新建重复的 contract_snapshots / transfer_financials 表，不删除任何历史数据。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1a4e7f92b30"
down_revision = "b8f3d2a6c1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("transfer_history.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "transfer_id", "new_status", "changed_at", name="uq_transfer_status_transfer_new_changed"
        ),
    )
    op.create_index("ix_transfer_status_history_transfer_id", "transfer_status_history", ["transfer_id"])
    op.create_index("ix_transfer_status_history_fm_save_id", "transfer_status_history", ["fm_save_id"])
    op.create_index("ix_transfer_status_save_time", "transfer_status_history", ["fm_save_id", "changed_at"])

    op.create_table(
        "transfer_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("offer_type", sa.String(length=16), nullable=False),
        sa.Column("base_fee", sa.Float(), nullable=True),
        sa.Column("immediate_payment", sa.Float(), nullable=True),
        sa.Column("installments_total", sa.Float(), nullable=True),
        sa.Column("addons_potential", sa.Float(), nullable=True),
        sa.Column("total_committed", sa.Float(), nullable=True),
        sa.Column("potential_total", sa.Float(), nullable=True),
        sa.Column("sell_on_pct", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="EUR"),
        sa.Column("wage_impact", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=8), nullable=False, server_default="medium"),
        sa.Column("rationale_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False, server_default="transfer-offer-1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="ai_estimate"),
        sa.Column("created_by", sa.String(length=16), nullable=False, server_default="engine"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_transfer_offers_fm_save_id", "transfer_offers", ["fm_save_id"])
    op.create_index("ix_transfer_offers_player_instance_id", "transfer_offers", ["player_instance_id"])
    op.create_index("ix_transfer_offers_save_player", "transfer_offers", ["fm_save_id", "player_instance_id"])
    op.create_index("ix_transfer_offers_save_direction", "transfer_offers", ["fm_save_id", "direction"])

    op.create_table(
        "transfer_negotiations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("transfer_offers.id"), nullable=True),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="DRAFT"),
        sa.Column("round_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("initial_ask", sa.Float(), nullable=True),
        sa.Column("user_offer", sa.Float(), nullable=True),
        sa.Column("counter_offer", sa.Float(), nullable=True),
        sa.Column("final_fee", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="EUR"),
        sa.Column("final_terms_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reject_reason", sa.String(length=256), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="user_confirmed"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_transfer_negotiations_fm_save_id", "transfer_negotiations", ["fm_save_id"])
    op.create_index("ix_transfer_negotiations_player_instance_id", "transfer_negotiations", ["player_instance_id"])
    op.create_index("ix_transfer_negotiations_offer_id", "transfer_negotiations", ["offer_id"])
    op.create_index("ix_negotiation_save_status", "transfer_negotiations", ["fm_save_id", "status"])
    op.create_index("ix_negotiation_save_player", "transfer_negotiations", ["fm_save_id", "player_instance_id"])

    op.create_table(
        "negotiation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("negotiation_id", sa.Integer(), sa.ForeignKey("transfer_negotiations.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("event_data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="user_confirmed"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_negotiation_events_negotiation_id", "negotiation_events", ["negotiation_id"])
    op.create_index("ix_negotiation_events_fm_save_id", "negotiation_events", ["fm_save_id"])
    op.create_index("ix_negotiation_event_negotiation", "negotiation_events", ["negotiation_id", "occurred_at"])
    op.create_index("ix_negotiation_event_save", "negotiation_events", ["fm_save_id", "occurred_at"])

    with op.batch_alter_table("loan_records") as batch:
        batch.add_column(sa.Column("loan_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("wage_contribution_amount", sa.Float(), nullable=True))
        batch.add_column(sa.Column("wage_contribution_pct", sa.Float(), nullable=True))
        batch.add_column(sa.Column("buy_option_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("buy_obligation_fee", sa.Float(), nullable=True))
        batch.add_column(sa.Column("option_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))

    with op.batch_alter_table("transfer_fee_components") as batch:
        batch.add_column(sa.Column("source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("payment_schedule", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transfer_fee_components") as batch:
        batch.drop_column("payment_schedule")
        batch.drop_column("confidence")
        batch.drop_column("source")

    with op.batch_alter_table("loan_records") as batch:
        batch.drop_column("confidence")
        batch.drop_column("option_status")
        batch.drop_column("buy_obligation_fee")
        batch.drop_column("buy_option_fee")
        batch.drop_column("wage_contribution_pct")
        batch.drop_column("wage_contribution_amount")
        batch.drop_column("loan_fee")

    op.drop_index("ix_negotiation_event_save", table_name="negotiation_events")
    op.drop_index("ix_negotiation_event_negotiation", table_name="negotiation_events")
    op.drop_index("ix_negotiation_events_fm_save_id", table_name="negotiation_events")
    op.drop_index("ix_negotiation_events_negotiation_id", table_name="negotiation_events")
    op.drop_table("negotiation_events")

    op.drop_index("ix_negotiation_save_player", table_name="transfer_negotiations")
    op.drop_index("ix_negotiation_save_status", table_name="transfer_negotiations")
    op.drop_index("ix_transfer_negotiations_offer_id", table_name="transfer_negotiations")
    op.drop_index("ix_transfer_negotiations_player_instance_id", table_name="transfer_negotiations")
    op.drop_index("ix_transfer_negotiations_fm_save_id", table_name="transfer_negotiations")
    op.drop_table("transfer_negotiations")

    op.drop_index("ix_transfer_offers_save_direction", table_name="transfer_offers")
    op.drop_index("ix_transfer_offers_save_player", table_name="transfer_offers")
    op.drop_index("ix_transfer_offers_player_instance_id", table_name="transfer_offers")
    op.drop_index("ix_transfer_offers_fm_save_id", table_name="transfer_offers")
    op.drop_table("transfer_offers")

    op.drop_index("ix_transfer_status_save_time", table_name="transfer_status_history")
    op.drop_index("ix_transfer_status_history_fm_save_id", table_name="transfer_status_history")
    op.drop_index("ix_transfer_status_history_transfer_id", table_name="transfer_status_history")
    op.drop_table("transfer_status_history")
