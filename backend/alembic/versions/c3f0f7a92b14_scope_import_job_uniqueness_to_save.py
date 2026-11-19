"""scope import job idempotency to (fm_save_id, scan_id)

Revision ID: c3f0f7a92b14
Revises: 992f85fb22b8
Create Date: 2026-11-19

``import_jobs.scan_id`` used to be globally unique, so importing the same scan id into two different
saves failed (or, worse, silently returned the other save's duplicate result). The importer has always
looked duplicates up per save, so the constraint now matches that behaviour.

Existing databases may already contain two jobs with the same (fm_save_id, scan_id) if the old
constraint was bypassed; those older duplicates are removed (the newest job per pair is kept) before
the new constraint is created, otherwise the migration would fail on legacy data.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c3f0f7a92b14"
down_revision = "992f85fb22b8"
branch_labels = None
depends_on = None

TABLE = "import_jobs"
OLD_CONSTRAINT = "uq_import_jobs_scan_id"
NEW_CONSTRAINT = "uq_import_jobs_save_scan"


def _unique_constraints(inspector: sa.engine.reflection.Inspector) -> list[tuple[str | None, tuple[str, ...]]]:
    """Return (name, columns) for every unique constraint, including SQLite's anonymous ones."""
    return [
        (item.get("name"), tuple(item.get("column_names") or ()))
        for item in inspector.get_unique_constraints(TABLE)
    ]


def _drop_scan_id_only_constraint() -> None:
    """Drop the legacy unique constraint on ``scan_id`` alone, whatever its name is."""
    bind = op.get_bind()
    for name, columns in _unique_constraints(sa.inspect(bind)):
        if columns == ("scan_id",) and name:
            with op.batch_alter_table(TABLE) as batch:
                batch.drop_constraint(name, type_="unique")


def upgrade() -> None:
    bind = op.get_bind()
    _drop_scan_id_only_constraint()
    inspector = sa.inspect(bind)
    names = {name for name, _ in _unique_constraints(inspector)}

    # Remove legacy duplicate jobs (same save + scan_id), keeping the most recently received one.
    op.execute(
        sa.text(
            f"""
            DELETE FROM {TABLE}
            WHERE id NOT IN (
                SELECT keep_id FROM (
                    SELECT MAX(id) AS keep_id
                    FROM {TABLE}
                    GROUP BY fm_save_id, scan_id
                ) AS newest
            )
            """
        )
    )

    if OLD_CONSTRAINT in names:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(OLD_CONSTRAINT, type_="unique")

    if NEW_CONSTRAINT not in {name for name, _ in _unique_constraints(sa.inspect(bind))}:
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(NEW_CONSTRAINT, ["fm_save_id", "scan_id"])


def downgrade() -> None:
    bind = op.get_bind()
    names = {name for name, _ in _unique_constraints(sa.inspect(bind))}
    if NEW_CONSTRAINT in names:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(NEW_CONSTRAINT, type_="unique")
    if OLD_CONSTRAINT not in names:
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(OLD_CONSTRAINT, ["scan_id"])
