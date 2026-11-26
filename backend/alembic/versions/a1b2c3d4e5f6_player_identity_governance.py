"""V3.2.9 player identity governance

Revision ID: a1b2c3d4e5f6
Revises: b5d9c2e7f4a1
Create Date: 2026-11-26

新增全库身份治理所需的六张表：UID 观测、Canonical 关联、人工审核队列与审计、
扫描批次状态、跨存档候选。全部是新增表，不修改任何既有 migration 或既有表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "b5d9c2e7f4a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_uid_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("observation_key", sa.String(length=64), nullable=False),
        sa.Column("save_identity_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("session_key", sa.String(length=128), nullable=True),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("uid", sa.String(length=64), nullable=True),
        sa.Column("uid_status", sa.String(length=16), nullable=False),
        sa.Column("uid_reason", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("layout_version", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attribute_record_digest", sa.String(length=64), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("conflicting_player_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "observation_key", name="uq_uid_observation_save_key"),
    )
    op.create_index("ix_player_uid_observations_fm_save_id", "player_uid_observations", ["fm_save_id"])
    op.create_index("ix_player_uid_observations_player_id", "player_uid_observations", ["player_id"])
    op.create_index("ix_uid_observation_save_uid", "player_uid_observations", ["fm_save_id", "uid"])
    op.create_index("ix_uid_observation_save_status", "player_uid_observations", ["fm_save_id", "status"])
    op.create_index("ix_uid_observation_instance", "player_uid_observations", ["player_instance_id"])

    op.create_table(
        "player_identity_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("player_instance_id", sa.Integer(), sa.ForeignKey("player_instances.id"), nullable=True),
        sa.Column("save_local_uid", sa.String(length=64), nullable=True),
        sa.Column("uid_occurrence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_record_id", sa.String(length=64), nullable=True),
        sa.Column("verification_status", sa.String(length=24), nullable=False, server_default="Candidate"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("link_key", sa.String(length=64), nullable=False),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "link_key", name="uq_identity_link_save_key"),
    )
    op.create_index("ix_player_identity_links_canonical_player_id", "player_identity_links", ["canonical_player_id"])
    op.create_index("ix_player_identity_links_fm_save_id", "player_identity_links", ["fm_save_id"])
    op.create_index("ix_identity_link_save_player", "player_identity_links", ["fm_save_id", "canonical_player_id"])
    op.create_index("ix_identity_link_save_uid", "player_identity_links", ["fm_save_id", "save_local_uid"])
    op.create_index("ix_identity_link_status", "player_identity_links", ["fm_save_id", "verification_status"])

    op.create_table(
        "player_identity_review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PendingHumanReview"),
        sa.Column("subject_uid", sa.String(length=64), nullable=True),
        sa.Column("primary_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("candidate_player_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("conflict_reason", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "item_key", name="uq_identity_review_save_key"),
    )
    op.create_index("ix_player_identity_review_items_fm_save_id", "player_identity_review_items", ["fm_save_id"])
    op.create_index("ix_identity_review_save_status", "player_identity_review_items", ["fm_save_id", "status"])
    op.create_index("ix_identity_review_save_type", "player_identity_review_items", ["fm_save_id", "item_type"])

    op.create_table(
        "player_identity_review_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("player_identity_review_items.id"), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=24), nullable=True),
        sa.Column("new_status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_player_identity_review_actions_review_id", "player_identity_review_actions", ["review_id"])
    op.create_index("ix_player_identity_review_actions_fm_save_id", "player_identity_review_actions", ["fm_save_id"])
    op.create_index("ix_identity_review_action_item", "player_identity_review_actions", ["review_id", "created_at"])

    op.create_table(
        "identity_scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("scan_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Queued"),
        sa.Column("cursor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("total_instances", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_checksum", sa.String(length=64), nullable=True),
        sa.Column("save_identity_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("layout_version", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fm_save_id", "scan_id", name="uq_identity_scan_save_scan"),
    )
    op.create_index("ix_identity_scan_runs_fm_save_id", "identity_scan_runs", ["fm_save_id"])
    op.create_index("ix_identity_scan_save_status", "identity_scan_runs", ["fm_save_id", "status"])

    op.create_table(
        "cross_save_identity_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("other_save_id", sa.Integer(), sa.ForeignKey("fm_saves.id"), nullable=False),
        sa.Column("subject_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("other_player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="CrossSaveCandidate"),
        sa.Column("uid_equal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "other_save_id", "subject_player_id", "other_player_id",
            name="uq_cross_save_pair",
        ),
    )
    op.create_index("ix_cross_save_identity_candidates_fm_save_id", "cross_save_identity_candidates", ["fm_save_id"])
    op.create_index("ix_cross_save_identity_candidates_other_save_id", "cross_save_identity_candidates", ["other_save_id"])
    op.create_index("ix_cross_save_identity_candidates_subject_player_id", "cross_save_identity_candidates", ["subject_player_id"])
    op.create_index("ix_cross_save_identity_candidates_other_player_id", "cross_save_identity_candidates", ["other_player_id"])
    op.create_index("ix_cross_save_save_status", "cross_save_identity_candidates", ["fm_save_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_cross_save_save_status", table_name="cross_save_identity_candidates")
    op.drop_index("ix_cross_save_identity_candidates_other_player_id", table_name="cross_save_identity_candidates")
    op.drop_index("ix_cross_save_identity_candidates_subject_player_id", table_name="cross_save_identity_candidates")
    op.drop_index("ix_cross_save_identity_candidates_other_save_id", table_name="cross_save_identity_candidates")
    op.drop_index("ix_cross_save_identity_candidates_fm_save_id", table_name="cross_save_identity_candidates")
    op.drop_table("cross_save_identity_candidates")

    op.drop_index("ix_identity_scan_save_status", table_name="identity_scan_runs")
    op.drop_index("ix_identity_scan_runs_fm_save_id", table_name="identity_scan_runs")
    op.drop_table("identity_scan_runs")

    op.drop_index("ix_identity_review_action_item", table_name="player_identity_review_actions")
    op.drop_index("ix_player_identity_review_actions_fm_save_id", table_name="player_identity_review_actions")
    op.drop_index("ix_player_identity_review_actions_review_id", table_name="player_identity_review_actions")
    op.drop_table("player_identity_review_actions")

    op.drop_index("ix_identity_review_save_type", table_name="player_identity_review_items")
    op.drop_index("ix_identity_review_save_status", table_name="player_identity_review_items")
    op.drop_index("ix_player_identity_review_items_fm_save_id", table_name="player_identity_review_items")
    op.drop_table("player_identity_review_items")

    op.drop_index("ix_identity_link_status", table_name="player_identity_links")
    op.drop_index("ix_identity_link_save_uid", table_name="player_identity_links")
    op.drop_index("ix_identity_link_save_player", table_name="player_identity_links")
    op.drop_index("ix_player_identity_links_fm_save_id", table_name="player_identity_links")
    op.drop_index("ix_player_identity_links_canonical_player_id", table_name="player_identity_links")
    op.drop_table("player_identity_links")

    op.drop_index("ix_uid_observation_instance", table_name="player_uid_observations")
    op.drop_index("ix_uid_observation_save_status", table_name="player_uid_observations")
    op.drop_index("ix_uid_observation_save_uid", table_name="player_uid_observations")
    op.drop_index("ix_player_uid_observations_player_id", table_name="player_uid_observations")
    op.drop_index("ix_player_uid_observations_fm_save_id", table_name="player_uid_observations")
    op.drop_table("player_uid_observations")
