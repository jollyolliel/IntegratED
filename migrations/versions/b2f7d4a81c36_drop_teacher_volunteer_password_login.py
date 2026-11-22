"""drop the teacher and volunteer password login columns

Revision ID: b2f7d4a81c36
Revises: e8c4a2f6d9b1
Create Date: 2026-11-19

Teacher and volunteer password login was reverted in #177: both roles sign in with Google only.
`username` and `password_hash` (added by d4b8f2a6c1e3 and f1c6a9d3b7e2) are no longer mapped, so
they go, along with the unique index on `username`. The teacher and volunteer rows stay.
"""

import sqlalchemy as sa
from alembic import op

revision = "b2f7d4a81c36"
down_revision = "e8c4a2f6d9b1"
branch_labels = None
depends_on = None

TABLES = ("teachers", "volunteers")


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    for table in TABLES:
        columns = _columns(table)
        index = f"ix_{table}_username"
        has_index = index in _indexes(table)
        with op.batch_alter_table(table) as batch_op:
            if has_index:
                batch_op.drop_index(batch_op.f(index))
            if "username" in columns:
                batch_op.drop_column("username")
            if "password_hash" in columns:
                batch_op.drop_column("password_hash")


def downgrade():
    for table in TABLES:
        columns = _columns(table)
        with op.batch_alter_table(table) as batch_op:
            if "username" not in columns:
                batch_op.add_column(sa.Column("username", sa.String(length=80), nullable=True))
                batch_op.create_index(batch_op.f(f"ix_{table}_username"), ["username"], unique=True)
            if "password_hash" not in columns:
                batch_op.add_column(sa.Column("password_hash", sa.String(length=200), nullable=True))
