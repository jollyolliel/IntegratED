"""add level and tags to worksheets

Revision ID: e5a2c8f4b7d1
Revises: c3f9a1d7e5b2
Create Date: 2026-11-06

A worksheet may sit at a level on the English placement scale (`level`) and carry short lowercase
labels the library search matches (`tags`). Both stay NULL for existing rows; the worksheet manifest
sync and teacher uploads fill them.
"""

import sqlalchemy as sa
from alembic import op

revision = "e5a2c8f4b7d1"
down_revision = "c3f9a1d7e5b2"
branch_labels = None
depends_on = None


def _worksheet_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("worksheets")}


def upgrade():
    columns = _worksheet_columns()
    if "level" not in columns:
        op.add_column("worksheets", sa.Column("level", sa.Integer(), nullable=True))
    if "tags" not in columns:
        op.add_column("worksheets", sa.Column("tags", sa.JSON(), nullable=True))


def downgrade():
    columns = _worksheet_columns()
    with op.batch_alter_table("worksheets") as batch_op:
        if "tags" in columns:
            batch_op.drop_column("tags")
        if "level" in columns:
            batch_op.drop_column("level")
