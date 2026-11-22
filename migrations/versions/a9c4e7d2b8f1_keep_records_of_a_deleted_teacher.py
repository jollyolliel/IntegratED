"""keep records of a deleted teacher

Revision ID: a9c4e7d2b8f1
Revises: f1c6a9d3b7e2
Create Date: 2026-11-15

Deleting a teacher's account keeps the attendance it recorded (a volunteer's hours are summed
live from those rows) and the worksheets it assigned, with `teacher_id` set to NULL. Both columns
were NOT NULL, so on Postgres the delete failed on the foreign key.
"""

import sqlalchemy as sa
from alembic import op

revision = "a9c4e7d2b8f1"
down_revision = "f1c6a9d3b7e2"
branch_labels = None
depends_on = None

_TABLES = ("attendance", "worksheet_assignments")


def upgrade():
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("teacher_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # A NULL teacher_id cannot be restored to anyone, so those rows go.
    for table in _TABLES:
        op.execute(sa.text(f"DELETE FROM {table} WHERE teacher_id IS NULL"))
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("teacher_id", existing_type=sa.Integer(), nullable=False)
