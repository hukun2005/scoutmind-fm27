"""field evidence samples

Revision ID: b7c1e2f4a901
Revises: f0a2c6d81b47
Create Date: 2026-11-22

Captured field-level evidence from the reader and game UI. Additive only; no historical rows are
modified.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7c1e2f4a901"
down_revision = "f0a2c6d81b47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "field_evidence_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=False),
        sa.Column("field_id", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("plugin_version", sa.String(length=32), nullable=True),
        sa.Column("layout_version", sa.String(length=32), nullable=True),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("evidence_source", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "player_instance_id", "field_id", "observed_at",
            name="uq_field_evidence_save_instance_field_time",
        ),
    )
    op.create_index("ix_field_evidence_samples_fm_save_id", "field_evidence_samples", ["fm_save_id"])
    op.create_index("ix_field_evidence_samples_player_instance_id", "field_evidence_samples", ["player_instance_id"])
    op.create_index("ix_field_evidence_save_status", "field_evidence_samples", ["fm_save_id", "validation_status"])
    op.create_index("ix_field_evidence_save_field", "field_evidence_samples", ["fm_save_id", "field_id"])


def downgrade() -> None:
    op.drop_index("ix_field_evidence_save_field", table_name="field_evidence_samples")
    op.drop_index("ix_field_evidence_save_status", table_name="field_evidence_samples")
    op.drop_index("ix_field_evidence_samples_player_instance_id", table_name="field_evidence_samples")
    op.drop_index("ix_field_evidence_samples_fm_save_id", table_name="field_evidence_samples")
    op.drop_table("field_evidence_samples")
