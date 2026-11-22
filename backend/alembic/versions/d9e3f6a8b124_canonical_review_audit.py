"""canonical review audit and conflict detail

Revision ID: d9e3f6a8b124
Revises: c8d2e5f7a013
Create Date: 2026-11-22

Adds conflict detail columns to canonical rows and an append-only manual decision audit table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9e3f6a8b124"
down_revision = "c8d2e5f7a013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("player_observation_canonicals") as batch:
        batch.add_column(sa.Column("conflict_types_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("changed_fields_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_canonical_reviewed_by"), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))

    op.create_table(
        "player_observation_canonical_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_id", sa.Integer(), sa.ForeignKey("player_observation_canonicals.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("selected_snapshot_id", sa.Integer(), sa.ForeignKey("player_snapshots.id"), nullable=True),
        sa.Column("previous_status", sa.String(length=24), nullable=True),
        sa.Column("new_status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_player_observation_canonical_actions_fm_save_id",
        "player_observation_canonical_actions",
        ["fm_save_id"],
    )
    op.create_index(
        "ix_player_observation_canonical_actions_canonical_id",
        "player_observation_canonical_actions",
        ["canonical_id"],
    )
    op.create_index(
        "ix_canonical_action_save_canonical",
        "player_observation_canonical_actions",
        ["fm_save_id", "canonical_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_action_save_canonical", table_name="player_observation_canonical_actions")
    op.drop_index("ix_player_observation_canonical_actions_canonical_id", table_name="player_observation_canonical_actions")
    op.drop_index("ix_player_observation_canonical_actions_fm_save_id", table_name="player_observation_canonical_actions")
    op.drop_table("player_observation_canonical_actions")
    with op.batch_alter_table("player_observation_canonicals") as batch:
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("changed_fields_json")
        batch.drop_column("conflict_types_json")
