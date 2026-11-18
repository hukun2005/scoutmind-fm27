"""drop circular fk on fm_saves user club

Revision ID: a72e84a1a299
Revises: 4e04ac4ffc89
Create Date: 2026-11-18 22:26:00.000000

``fm_saves.user_club_id`` and ``clubs.fm_save_id`` point at each other. SQLite cannot create or drop such a pair in
one pass, and the ownership rule is enforced in ``ClubResolver.set_user_club`` anyway, so the FK is dropped here.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a72e84a1a299'
down_revision = '4e04ac4ffc89'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('fm_saves', schema=None) as batch_op:
        batch_op.drop_constraint('fk_fm_saves_user_club', type_='foreignkey')


def downgrade() -> None:
    with op.batch_alter_table('fm_saves', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_fm_saves_user_club', 'clubs', ['user_club_id'], ['id'])