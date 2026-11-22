"""Attendance.volunteer_duration / volunteer_notes — the volunteer's own session

A volunteer's stretch need not equal any learner's, and their note is about
their own session, so neither can be read off `duration`/`notes`. Both are NULL
for every existing row, which means "never entered" and keeps those rows falling
back to the learners' hours (see Volunteer.hours_volunteered).

Revision ID: a92f5d17c4be
Revises: f3a5c81d6b92
Create Date: 2026-08-15
"""

import sqlalchemy as sa
from alembic import op

revision = "a92f5d17c4be"
down_revision = "f3a5c81d6b92"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    if "volunteer_duration" not in existing_columns:
        op.add_column("attendance", sa.Column("volunteer_duration", sa.Float(), nullable=True))
    if "volunteer_notes" not in existing_columns:
        op.add_column("attendance", sa.Column("volunteer_notes", sa.Text(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    if "volunteer_notes" in existing_columns:
        op.drop_column("attendance", "volunteer_notes")
    if "volunteer_duration" in existing_columns:
        op.drop_column("attendance", "volunteer_duration")
