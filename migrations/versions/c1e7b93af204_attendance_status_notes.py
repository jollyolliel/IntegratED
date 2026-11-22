"""Attendance status + notes, and a (teacher_id, date) index

Adds attendance.status ('present' | 'absent') so a recorded no-show is
distinguishable from a session nobody logged, and attendance.notes for the
free-text session note. Every existing row is a logged session, so it
backfills to 'present' and keeps its duration untouched.

ix_attendance_teacher_date backs the roster ("what did I already log for this
date") and the paginated history page, both of which filter teacher + date.

Revision ID: c1e7b93af204
Revises: b6d4f2a91c05
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "c1e7b93af204"
down_revision = "b6d4f2a91c05"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_attendance_teacher_date"


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    if "status" not in existing_columns:
        op.add_column(
            "attendance",
            sa.Column(
                "status",
                sa.String(length=10),
                nullable=False,
                server_default="present",
            ),
        )

    if "notes" not in existing_columns:
        op.add_column("attendance", sa.Column("notes", sa.Text(), nullable=True))

    if _INDEX_NAME not in {ix["name"] for ix in inspector.get_indexes("attendance")}:
        op.create_index(_INDEX_NAME, "attendance", ["teacher_id", "date"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if _INDEX_NAME in {ix["name"] for ix in inspector.get_indexes("attendance")}:
        op.drop_index(_INDEX_NAME, table_name="attendance")

    existing_columns = {c["name"] for c in inspector.get_columns("attendance")}

    # Absences carry no hours, so dropping the column would silently turn every
    # no-show into a zero-hour attended session. Remove those rows first.
    if "status" in existing_columns:
        op.execute("DELETE FROM attendance WHERE status = 'absent'")
        op.drop_column("attendance", "status")

    if "notes" in existing_columns:
        op.drop_column("attendance", "notes")
