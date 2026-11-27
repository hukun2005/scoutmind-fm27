"""V3.3.2-08 在线学习：会话、事件、俱乐部画像与学习动态

Revision ID: c7d2f8a41b60
Revises: b1f4d7e82c90
Create Date: 2026-11-27

只新增，不修改历史 migration：

* ``transfer_learning_sessions``：每存档一行，保存状态、游标与检查点。
* ``transfer_learning_events``：在线学习事件日志，``(fm_save_id, event_key)`` 唯一。
* ``club_transfer_profiles``：每存档每俱乐部一行，增量统计与重点标记。
* ``transfer_learning_activities``：用户可读的学习动态。

不复制既有 ``transfer_history`` / ``loan_records`` / ``player_availability`` /
``transfer_negotiations`` / ``background_tasks`` 等表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d2f8a41b60"
down_revision = "b1f4d7e82c90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_learning_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="STOPPED"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_monitor_at", sa.DateTime(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("last_learning_at", sa.DateTime(), nullable=True),
        sa.Column("events_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_cycles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("last_import_job_id", sa.Integer(), nullable=True),
        sa.Column("cursor_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", name="uq_learning_session_save"),
    )
    op.create_index("ix_transfer_learning_sessions_fm_save_id", "transfer_learning_sessions", ["fm_save_id"])
    op.create_index("ix_learning_session_status", "transfer_learning_sessions", ["status"])

    op.create_table(
        "transfer_learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("transaction_type", sa.String(length=16), nullable=True),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="CONFIRMED"),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=True),
        sa.Column("player_identity", sa.String(length=80), nullable=True),
        sa.Column("buying_club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=True),
        sa.Column("selling_club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("learning_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "event_key", name="uq_learning_event_save_key"),
    )
    op.create_index("ix_transfer_learning_events_fm_save_id", "transfer_learning_events", ["fm_save_id"])
    op.create_index("ix_transfer_learning_events_player_instance_id", "transfer_learning_events", ["player_instance_id"])
    op.create_index("ix_transfer_learning_events_buying_club_id", "transfer_learning_events", ["buying_club_id"])
    op.create_index("ix_transfer_learning_events_selling_club_id", "transfer_learning_events", ["selling_club_id"])
    op.create_index("ix_learning_event_save_time", "transfer_learning_events", ["fm_save_id", "observed_at"])
    op.create_index("ix_learning_event_save_type", "transfer_learning_events", ["fm_save_id", "event_type"])
    op.create_index("ix_learning_event_save_player", "transfer_learning_events", ["fm_save_id", "player_instance_id"])

    op.create_table(
        "club_transfer_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False, server_default="global"),
        sa.Column("last_event_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stats_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("confidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "club_id", name="uq_club_profile_save_club"),
    )
    op.create_index("ix_club_transfer_profiles_fm_save_id", "club_transfer_profiles", ["fm_save_id"])
    op.create_index("ix_club_transfer_profiles_club_id", "club_transfer_profiles", ["club_id"])
    op.create_index("ix_club_profile_save_priority", "club_transfer_profiles", ["fm_save_id", "priority"])
    op.create_index("ix_club_profile_save_sample", "club_transfer_profiles", ["fm_save_id", "sample_size"])

    op.create_table(
        "transfer_learning_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("activity_type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("transfer_learning_events.id"), nullable=True),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_transfer_learning_activities_fm_save_id", "transfer_learning_activities", ["fm_save_id"])
    op.create_index("ix_learning_activity_save_time", "transfer_learning_activities", ["fm_save_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_learning_activity_save_time", table_name="transfer_learning_activities")
    op.drop_index("ix_transfer_learning_activities_fm_save_id", table_name="transfer_learning_activities")
    op.drop_table("transfer_learning_activities")

    op.drop_index("ix_club_profile_save_sample", table_name="club_transfer_profiles")
    op.drop_index("ix_club_profile_save_priority", table_name="club_transfer_profiles")
    op.drop_index("ix_club_transfer_profiles_club_id", table_name="club_transfer_profiles")
    op.drop_index("ix_club_transfer_profiles_fm_save_id", table_name="club_transfer_profiles")
    op.drop_table("club_transfer_profiles")

    op.drop_index("ix_learning_event_save_player", table_name="transfer_learning_events")
    op.drop_index("ix_learning_event_save_type", table_name="transfer_learning_events")
    op.drop_index("ix_learning_event_save_time", table_name="transfer_learning_events")
    op.drop_index("ix_transfer_learning_events_selling_club_id", table_name="transfer_learning_events")
    op.drop_index("ix_transfer_learning_events_buying_club_id", table_name="transfer_learning_events")
    op.drop_index("ix_transfer_learning_events_player_instance_id", table_name="transfer_learning_events")
    op.drop_index("ix_transfer_learning_events_fm_save_id", table_name="transfer_learning_events")
    op.drop_table("transfer_learning_events")

    op.drop_index("ix_learning_session_status", table_name="transfer_learning_sessions")
    op.drop_index("ix_transfer_learning_sessions_fm_save_id", table_name="transfer_learning_sessions")
    op.drop_table("transfer_learning_sessions")
