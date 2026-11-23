"""transfer event candidates

Revision ID: f6a7b8c9d0e1
Revises: e5a1b2c3d4f6
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5a1b2c3d4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_event_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=True),
        sa.Column("to_club_id", sa.Integer(), sa.ForeignKey("clubs.id"), nullable=True),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("evidence_level", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("linked_transfer_id", sa.Integer(), sa.ForeignKey("transfer_history.id"), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "player_instance_id", "from_club_id", "to_club_id", "game_date",
            name="uq_transfer_event_save_player_clubs_date",
        ),
    )
    op.create_index("ix_transfer_event_candidates_fm_save_id", "transfer_event_candidates", ["fm_save_id"])
    op.create_index("ix_transfer_event_candidates_player_instance_id", "transfer_event_candidates", ["player_instance_id"])
    op.create_index("ix_transfer_event_save_status", "transfer_event_candidates", ["fm_save_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_transfer_event_save_status", table_name="transfer_event_candidates")
    op.drop_index("ix_transfer_event_candidates_player_instance_id", table_name="transfer_event_candidates")
    op.drop_index("ix_transfer_event_candidates_fm_save_id", table_name="transfer_event_candidates")
    op.drop_table("transfer_event_candidates")
