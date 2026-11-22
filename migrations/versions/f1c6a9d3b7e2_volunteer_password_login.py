"""volunteer password login

Revision ID: f1c6a9d3b7e2
Revises: d4b8f2a6c1e3
Create Date: 2026-11-10

A volunteer may also sign in with a username and password an admin set up; both columns stay
empty for Google-only volunteers.
"""

import sqlalchemy as sa
from alembic import op

revision = "f1c6a9d3b7e2"
down_revision = "d4b8f2a6c1e3"
branch_labels = None
depends_on = None


def _columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("volunteers")}


def upgrade():
    columns = _columns()
    with op.batch_alter_table("volunteers") as batch_op:
        if "username" not in columns:
            batch_op.add_column(sa.Column("username", sa.String(length=80), nullable=True))
            batch_op.create_index(batch_op.f("ix_volunteers_username"), ["username"], unique=True)
        if "password_hash" not in columns:
            batch_op.add_column(sa.Column("password_hash", sa.String(length=200), nullable=True))


def downgrade():
    columns = _columns()
    with op.batch_alter_table("volunteers") as batch_op:
        if "password_hash" in columns:
            batch_op.drop_column("password_hash")
        if "username" in columns:
            batch_op.drop_index(batch_op.f("ix_volunteers_username"))
            batch_op.drop_column("username")
