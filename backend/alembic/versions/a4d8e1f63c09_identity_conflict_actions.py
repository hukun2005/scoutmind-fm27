"""identity conflict review audit

Revision ID: a4d8e1f63c09
Revises: f3a9c57e21d8
Create Date: 2026-11-20

The Identity Resolution Center needs an append-only audit of manual decisions. Conflicts keep
their evidence rows; only status/resolution change, and every decision is recorded here.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a4d8e1f63c09"
down_revision = "f3a9c57e21d8"
branch_labels = None
depends_on = None

TABLE = "identity_conflict_actions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conflict_id", sa.Integer(), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conflict_id"], ["identity_conflicts.id"]),
        sa.ForeignKeyConstraint(["fm_save_id"], ["fm_saves.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identity_conflict_actions_conflict_id", TABLE, ["conflict_id"])
    op.create_index("ix_identity_conflict_actions_fm_save_id", TABLE, ["fm_save_id"])
    op.create_index("ix_identity_conflict_actions_user_id", TABLE, ["user_id"])
    op.create_index("ix_conflict_actions_conflict", TABLE, ["conflict_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_conflict_actions_conflict", table_name=TABLE)
    op.drop_index("ix_identity_conflict_actions_user_id", table_name=TABLE)
    op.drop_index("ix_identity_conflict_actions_fm_save_id", table_name=TABLE)
    op.drop_index("ix_identity_conflict_actions_conflict_id", table_name=TABLE)
    op.drop_table(TABLE)
