"""unresolved players: candidates, observations and manual decisions

Revision ID: a8c4d5e6f701
Revises: f6a7b8c9d0e1
Create Date: 2026-11-23

Additive only: three new tables with their foreign keys and indexes. No published migration and no
existing ``player_instances`` / ``save_local_uid`` column is touched, so a sentinel can never become a
legal UID and 1.x data is unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a8c4d5e6f701"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unresolved_player_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("candidate_key", sa.String(length=160), nullable=False),
        sa.Column("source_identity_kind", sa.String(length=24), nullable=False, server_default="observation"),
        sa.Column("source_identity_value", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=64), nullable=True),
        sa.Column("position", sa.String(length=16), nullable=True),
        sa.Column("raw_uid", sa.String(length=64), nullable=True),
        sa.Column("uid_status", sa.String(length=16), nullable=False),
        sa.Column("uid_reason", sa.String(length=64), nullable=True),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("latest_ca", sa.Integer(), nullable=True),
        sa.Column("latest_pa", sa.Integer(), nullable=True),
        sa.Column("resolution_method", sa.String(length=32), nullable=True),
        sa.Column("resolved_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("resolved_player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("dismissed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("dismiss_reason", sa.String(length=256), nullable=True),
        sa.Column("evidence_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'review_required', 'resolved', 'dismissed')",
            name="ck_unresolved_candidate_status",
        ),
        sa.CheckConstraint(
            "uid_status IN ('sentinel', 'missing', 'invalid')",
            name="ck_unresolved_candidate_uid_status",
        ),
        sa.UniqueConstraint("fm_save_id", "candidate_key", name="uq_unresolved_candidate_save_key"),
    )
    op.create_index("ix_unresolved_player_candidates_fm_save_id", "unresolved_player_candidates", ["fm_save_id"])
    op.create_index(
        "ix_unresolved_player_candidates_resolved_player_id",
        "unresolved_player_candidates",
        ["resolved_player_id"],
    )
    op.create_index(
        "ix_unresolved_candidate_save_status", "unresolved_player_candidates", ["fm_save_id", "status"]
    )
    op.create_index(
        "ix_unresolved_candidate_save_name", "unresolved_player_candidates", ["fm_save_id", "normalized_name"]
    )

    op.create_table(
        "unresolved_player_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("unresolved_player_candidates.id"),
            nullable=False,
        ),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("import_job_id", sa.Integer(), sa.ForeignKey("import_jobs.id"), nullable=True),
        sa.Column("scan_id", sa.String(length=64), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=True),
        sa.Column("raw_uid", sa.String(length=64), nullable=True),
        sa.Column("uid_status", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=64), nullable=True),
        sa.Column("position", sa.String(length=16), nullable=True),
        sa.Column("ca", sa.Integer(), nullable=True),
        sa.Column("pa", sa.Integer(), nullable=True),
        sa.Column("club_name", sa.String(length=128), nullable=True),
        sa.Column("contract_end", sa.Date(), nullable=True),
        sa.Column("raw_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "uid_status IN ('sentinel', 'missing', 'invalid')",
            name="ck_unresolved_observation_uid_status",
        ),
        sa.UniqueConstraint("fm_save_id", "scan_id", "row_index", name="uq_unresolved_observation_scan_row"),
    )
    op.create_index(
        "ix_unresolved_player_observations_candidate_id",
        "unresolved_player_observations",
        ["candidate_id"],
    )
    op.create_index(
        "ix_unresolved_player_observations_fm_save_id",
        "unresolved_player_observations",
        ["fm_save_id"],
    )
    op.create_index(
        "ix_unresolved_player_observations_import_job_id",
        "unresolved_player_observations",
        ["import_job_id"],
    )
    op.create_index(
        "ix_unresolved_observation_candidate", "unresolved_player_observations", ["candidate_id", "observed_at"]
    )
    op.create_index(
        "ix_unresolved_observation_save_scan", "unresolved_player_observations", ["fm_save_id", "scan_id"]
    )

    op.create_table(
        "unresolved_player_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("unresolved_player_candidates.id"),
            nullable=False,
        ),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("target_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_unresolved_player_actions_candidate_id", "unresolved_player_actions", ["candidate_id"])
    op.create_index("ix_unresolved_player_actions_fm_save_id", "unresolved_player_actions", ["fm_save_id"])
    op.create_index("ix_unresolved_action_candidate", "unresolved_player_actions", ["candidate_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_unresolved_action_candidate", table_name="unresolved_player_actions")
    op.drop_index("ix_unresolved_player_actions_fm_save_id", table_name="unresolved_player_actions")
    op.drop_index("ix_unresolved_player_actions_candidate_id", table_name="unresolved_player_actions")
    op.drop_table("unresolved_player_actions")

    op.drop_index("ix_unresolved_observation_save_scan", table_name="unresolved_player_observations")
    op.drop_index("ix_unresolved_observation_candidate", table_name="unresolved_player_observations")
    op.drop_index("ix_unresolved_player_observations_import_job_id", table_name="unresolved_player_observations")
    op.drop_index("ix_unresolved_player_observations_fm_save_id", table_name="unresolved_player_observations")
    op.drop_index("ix_unresolved_player_observations_candidate_id", table_name="unresolved_player_observations")
    op.drop_table("unresolved_player_observations")

    op.drop_index("ix_unresolved_candidate_save_name", table_name="unresolved_player_candidates")
    op.drop_index("ix_unresolved_candidate_save_status", table_name="unresolved_player_candidates")
    op.drop_index(
        "ix_unresolved_player_candidates_resolved_player_id", table_name="unresolved_player_candidates"
    )
    op.drop_index("ix_unresolved_player_candidates_fm_save_id", table_name="unresolved_player_candidates")
    op.drop_table("unresolved_player_candidates")
