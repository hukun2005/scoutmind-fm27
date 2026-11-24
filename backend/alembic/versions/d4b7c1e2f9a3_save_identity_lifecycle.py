"""V3.2.7.2 存档身份生命周期：验证主体、会话心跳与不可变审计事件。

Revision ID: d4b7c1e2f9a3
Revises: c3d8f1a2b407
Create Date: 2026-11-25

只新增可空列与新表；不改历史列、不回填、不改变既有数据语义。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4b7c1e2f9a3"
down_revision = "c3d8f1a2b407"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("save_identities") as batch:
        batch.add_column(sa.Column("verified_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("verified_by", sa.String(length=64), nullable=True))

    with op.batch_alter_table("save_sessions") as batch:
        batch.add_column(sa.Column("agent_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))

    op.create_table(
        "save_identity_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), nullable=True),
        sa.Column("identity_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("capture_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("old_status", sa.String(length=24), nullable=True),
        sa.Column("new_status", sa.String(length=24), nullable=True),
        sa.Column("old_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("new_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("actor", sa.String(length=64), nullable=False, server_default="backend"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_save_identity_audit_events_fm_save_id", "save_identity_audit_events", ["fm_save_id"]
    )
    op.create_index(
        "ix_save_identity_audit_identity", "save_identity_audit_events", ["identity_id", "occurred_at"]
    )
    op.create_index(
        "ix_save_identity_audit_session", "save_identity_audit_events", ["session_id", "occurred_at"]
    )
    op.create_index(
        "ix_save_identity_audit_capture", "save_identity_audit_events", ["capture_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_save_identity_audit_capture", table_name="save_identity_audit_events")
    op.drop_index("ix_save_identity_audit_session", table_name="save_identity_audit_events")
    op.drop_index("ix_save_identity_audit_identity", table_name="save_identity_audit_events")
    op.drop_index("ix_save_identity_audit_events_fm_save_id", table_name="save_identity_audit_events")
    op.drop_table("save_identity_audit_events")

    with op.batch_alter_table("save_sessions") as batch:
        batch.drop_column("last_heartbeat_at")
        batch.drop_column("agent_id")

    with op.batch_alter_table("save_identities") as batch:
        batch.drop_column("verified_by")
        batch.drop_column("verified_at")
