"""V3.2.7 存档身份：身份 / 证据 / 会话 / 冲突，并给采集与导入增加身份归属列。

Revision ID: c3d8f1a2b407
Revises: b7e2c9d4a105
Create Date: 2026-11-24

只新增表与可空列；历史行保持 NULL，并以 LEGACY_UNVERIFIED 证据标记，绝不回填成已验证。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d8f1a2b407"
down_revision = "b7e2c9d4a105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "save_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), nullable=True),
        sa.Column("identity_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("identity_status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("identity_confidence", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("identity_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("identity_kind", sa.String(length=32), nullable=False, server_default="unresolved"),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("plugin_version", sa.String(length=32), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "fm_save_id", "identity_version", "identity_fingerprint",
            name="uq_save_identity_save_version_fingerprint",
        ),
    )
    op.create_index("ix_save_identities_fm_save_id", "save_identities", ["fm_save_id"])
    op.create_index("ix_save_identities_identity_fingerprint", "save_identities", ["identity_fingerprint"])
    op.create_index("ix_save_identity_status", "save_identities", ["identity_status"])

    op.create_table(
        "save_evidences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("save_identity_id", sa.Integer(), nullable=False),
        sa.Column("fm_save_id", sa.Integer(), nullable=True),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("evidence_source", sa.String(length=16), nullable=False),
        sa.Column("evidence_hash", sa.String(length=128), nullable=False),
        sa.Column("evidence_version", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_save_evidences_save_identity_id", "save_evidences", ["save_identity_id"])
    op.create_index("ix_save_evidences_fm_save_id", "save_evidences", ["fm_save_id"])
    op.create_index("ix_save_evidences_session_id", "save_evidences", ["session_id"])
    op.create_index(
        "ix_save_evidence_identity_observed", "save_evidences", ["save_identity_id", "observed_at"]
    )

    op.create_table(
        "save_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), nullable=True),
        sa.Column("save_identity_id", sa.Integer(), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("process_start_time", sa.DateTime(), nullable=True),
        sa.Column("session_key", sa.String(length=128), nullable=False),
        sa.Column("session_started_at", sa.DateTime(), nullable=False),
        sa.Column("session_ended_at", sa.DateTime(), nullable=True),
        sa.Column("game_build", sa.String(length=64), nullable=True),
        sa.Column("plugin_version", sa.String(length=32), nullable=True),
        sa.Column("session_status", sa.String(length=16), nullable=False, server_default="created"),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_key", name="uq_save_sessions_session_key"),
    )
    op.create_index("ix_save_sessions_fm_save_id", "save_sessions", ["fm_save_id"])
    op.create_index("ix_save_sessions_save_identity_id", "save_sessions", ["save_identity_id"])
    op.create_index("ix_save_session_identity", "save_sessions", ["save_identity_id"])

    op.create_table(
        "save_identity_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fm_save_id", sa.Integer(), nullable=True),
        sa.Column("current_identity_id", sa.Integer(), nullable=False),
        sa.Column("conflicting_identity_id", sa.Integer(), nullable=True),
        sa.Column("conflict_reason", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("conflict_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_save_identity_conflicts_fm_save_id", "save_identity_conflicts", ["fm_save_id"])
    op.create_index("ix_save_identity_conflicts_current_identity_id", "save_identity_conflicts", ["current_identity_id"])
    op.create_index("ix_save_conflict_status", "save_identity_conflicts", ["status"])

    with op.batch_alter_table("capture_runs") as batch:
        batch.add_column(sa.Column("save_identity_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("save_session_id", sa.Integer(), nullable=True))
        batch.create_index("ix_capture_runs_save_identity_id", ["save_identity_id"])
        batch.create_index("ix_capture_runs_save_session_id", ["save_session_id"])

    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(sa.Column("save_identity_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("save_session_id", sa.Integer(), nullable=True))
        batch.create_index("ix_import_jobs_save_identity_id", ["save_identity_id"])
        batch.create_index("ix_import_jobs_save_session_id", ["save_session_id"])

    # 历史存档：只标记为“未验证”，不猜身份、不生成可认证指纹。
    op.execute(
        """
        INSERT INTO save_identities (
            fm_save_id, identity_version, identity_status, identity_confidence,
            identity_fingerprint, identity_kind, game_build, plugin_version,
            first_seen_at, last_seen_at, created_at, updated_at
        )
        SELECT
            id, 1, 'unknown', 'none',
            'si:v1:unresolved:legacy:' || id, 'unresolved', game_build, NULL,
            created_at, updated_at, created_at, updated_at
        FROM fm_saves
        """
    )
    op.execute(
        """
        INSERT INTO save_evidences (
            save_identity_id, fm_save_id, evidence_type, evidence_source,
            evidence_hash, evidence_version, confidence, observed_at,
            session_id, metadata_json, created_at, updated_at
        )
        SELECT
            si.id, si.fm_save_id, 'LEGACY_UNVERIFIED', 'backend',
            'legacy:' || si.fm_save_id, NULL, 'none', si.created_at,
            NULL, '{}', si.created_at, si.updated_at
        FROM save_identities si
        WHERE si.identity_kind = 'unresolved'
          AND si.identity_fingerprint LIKE 'si:v1:unresolved:legacy:%'
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM save_evidences WHERE evidence_type = 'LEGACY_UNVERIFIED'"
    )
    op.execute(
        "DELETE FROM save_identities WHERE identity_kind = 'unresolved' "
        "AND identity_fingerprint LIKE 'si:v1:unresolved:legacy:%'"
    )

    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_index("ix_import_jobs_save_session_id")
        batch.drop_index("ix_import_jobs_save_identity_id")
        batch.drop_column("save_session_id")
        batch.drop_column("save_identity_id")

    with op.batch_alter_table("capture_runs") as batch:
        batch.drop_index("ix_capture_runs_save_session_id")
        batch.drop_index("ix_capture_runs_save_identity_id")
        batch.drop_column("save_session_id")
        batch.drop_column("save_identity_id")

    op.drop_table("save_identity_conflicts")
    op.drop_table("save_sessions")
    op.drop_table("save_evidences")
    op.drop_table("save_identities")
