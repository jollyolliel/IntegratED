"""teacher password login and lasting invite codes

Revision ID: d4b8f2a6c1e3
Revises: a7c3e1f95b24
Create Date: 2026-11-08

A teacher may also sign in with a username and password an admin set up; both columns stay
empty for Google-only teachers. A school's invite code no longer expires: it changes only when
a teacher regenerates it. `schools.invite_code_expires_at` is left in place, because the revision
still serving while this runs reads it; a later migration drops it once no deployed code does
(docs/operations/database.md).
"""

import sqlalchemy as sa
from alembic import op

revision = "d4b8f2a6c1e3"
down_revision = "a7c3e1f95b24"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    teacher_columns = _columns("teachers")
    with op.batch_alter_table("teachers") as batch_op:
        if "username" not in teacher_columns:
            batch_op.add_column(sa.Column("username", sa.String(length=80), nullable=True))
            batch_op.create_index(batch_op.f("ix_teachers_username"), ["username"], unique=True)
        if "password_hash" not in teacher_columns:
            batch_op.add_column(sa.Column("password_hash", sa.String(length=200), nullable=True))


def downgrade():
    teacher_columns = _columns("teachers")
    with op.batch_alter_table("teachers") as batch_op:
        if "password_hash" in teacher_columns:
            batch_op.drop_column("password_hash")
        if "username" in teacher_columns:
            batch_op.drop_index(batch_op.f("ix_teachers_username"))
            batch_op.drop_column("username")
