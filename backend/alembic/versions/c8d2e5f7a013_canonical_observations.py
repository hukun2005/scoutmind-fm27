"""canonical player observations

Revision ID: c8d2e5f7a013
Revises: b7c1e2f4a901
Create Date: 2026-11-22

Adds a canonical mapping for (save, player instance, game date). Raw snapshots are never deleted;
conflicting same-day observations stay ``needs_review`` with no canonical snapshot id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d2e5f7a013"
down_revision = "b7c1e2f4a901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_observation_canonicals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("canonical_snapshot_id", sa.Integer(), sa.ForeignKey("player_snapshots.id"), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("conflict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_content_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "player_instance_id", "game_date",
            name="uq_canonical_save_instance_game_date",
        ),
    )
    op.create_index("ix_player_observation_canonicals_fm_save_id", "player_observation_canonicals", ["fm_save_id"])
    op.create_index(
        "ix_player_observation_canonicals_player_instance_id", "player_observation_canonicals", ["player_instance_id"]
    )
    op.create_index("ix_canonical_save_status", "player_observation_canonicals", ["fm_save_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_canonical_save_status", table_name="player_observation_canonicals")
    op.drop_index("ix_player_observation_canonicals_player_instance_id", table_name="player_observation_canonicals")
    op.drop_index("ix_player_observation_canonicals_fm_save_id", table_name="player_observation_canonicals")
    op.drop_table("player_observation_canonicals")
