"""V3.3.3-01 agent runtime: tasks, events and approvals

Revision ID: b8e4d1c7f2a9
Revises: c7d2f8a41b60
Create Date: 2026-11-28

只新增表，不修改历史 migration：

* ``agent_tasks``：一次可恢复的 Agent 任务及其最终报告/错误。
* ``agent_task_events``：任务内严格递增的事件流，供 SSE/轮询按 seq 重放。
* ``agent_approvals``：人机协作确认单（一次性、载荷哈希、存档代次、TTL）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8e4d1c7f2a9"
down_revision = "c7d2f8a41b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("agent_conversations.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("save_generation", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("user_goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("final_result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("provider_id", sa.String(length=32), nullable=True),
        sa.Column("model_id", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=24), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("thread_id", name="uq_agent_tasks_thread"),
    )
    op.create_index("ix_agent_tasks_conversation_id", "agent_tasks", ["conversation_id"])
    op.create_index("ix_agent_tasks_save_created", "agent_tasks", ["fm_save_id", "created_at"])
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])

    op.create_table(
        "agent_task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("task_id", "seq", name="uq_agent_task_event_seq"),
    )
    op.create_index("ix_agent_task_events_task_seq", "agent_task_events", ["task_id", "seq"])

    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("approval_type", sa.String(length=24), nullable=False),
        sa.Column("operation_type", sa.String(length=48), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("save_generation", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_approvals_task_status", "agent_approvals", ["task_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_agent_approvals_task_status", table_name="agent_approvals")
    op.drop_table("agent_approvals")
    op.drop_index("ix_agent_task_events_task_seq", table_name="agent_task_events")
    op.drop_table("agent_task_events")
    op.drop_index("ix_agent_tasks_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_save_created", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_conversation_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
