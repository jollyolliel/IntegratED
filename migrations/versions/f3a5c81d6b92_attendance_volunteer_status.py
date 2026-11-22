"""Attendance.volunteer_status — the volunteer's own present/absent mark

The learner's `status` said nothing about whether the volunteer turned up, so a
volunteer who missed a session still collected its hours. NULL means nobody
marked it, which is deliberately not "absent": rows written before this column
existed keep crediting their volunteer, and only an explicit 'absent' drops the
hours (see Volunteer.hours_volunteered).

Revision ID: f3a5c81d6b92
Revises: c1e7b93af204
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "f3a5c81d6b92"
down_revision = "c1e7b93af204"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    if "volunteer_status" not in existing_columns:
        op.add_column(
            "attendance",
            sa.Column("volunteer_status", sa.String(length=10), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    if "volunteer_status" in existing_columns:
        op.drop_column("attendance", "volunteer_status")
