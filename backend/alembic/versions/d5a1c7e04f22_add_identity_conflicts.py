"""add identity_conflicts

Revision ID: d5a1c7e04f22
Revises: c3f0f7a92b14
Create Date: 2026-11-19

Identity resolution used to keep conflicts only in the warnings list. They are now persisted so a
reviewer can see which UID was reused, with what evidence, and which two identities were kept apart.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d5a1c7e04f22"
down_revision = "c3f0f7a92b14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_conflicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), nullable=False),
        sa.Column("save_local_uid", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("existing_player_id", sa.Integer(), nullable=True),
        sa.Column("incoming_player_id", sa.Integer(), nullable=True),
        sa.Column("existing_name", sa.String(length=128), nullable=True),
        sa.Column("incoming_name", sa.String(length=128), nullable=True),
        sa.Column("existing_birth_date", sa.Date(), nullable=True),
        sa.Column("incoming_birth_date", sa.Date(), nullable=True),
        sa.Column("resolution", sa.String(length=32), nullable=False, server_default="kept_both"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fm_save_id"], ["fm_saves.id"]),
        sa.ForeignKeyConstraint(["existing_player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["incoming_player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identity_conflicts_fm_save_id", "identity_conflicts", ["fm_save_id"])
    op.create_index("ix_identity_conflicts_save_local_uid", "identity_conflicts", ["save_local_uid"])
    op.create_index("ix_identity_conflicts_existing_player_id", "identity_conflicts", ["existing_player_id"])
    op.create_index("ix_identity_conflicts_incoming_player_id", "identity_conflicts", ["incoming_player_id"])
    op.create_index("ix_identity_conflicts_save_uid", "identity_conflicts", ["fm_save_id", "save_local_uid"])


def downgrade() -> None:
    op.drop_index("ix_identity_conflicts_save_uid", table_name="identity_conflicts")
    op.drop_index("ix_identity_conflicts_incoming_player_id", table_name="identity_conflicts")
    op.drop_index("ix_identity_conflicts_existing_player_id", table_name="identity_conflicts")
    op.drop_index("ix_identity_conflicts_save_local_uid", table_name="identity_conflicts")
    op.drop_index("ix_identity_conflicts_fm_save_id", table_name="identity_conflicts")
    op.drop_table("identity_conflicts")
