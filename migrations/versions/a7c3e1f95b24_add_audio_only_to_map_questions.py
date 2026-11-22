"""add audio_only to map_questions

Revision ID: a7c3e1f95b24
Revises: e5a2c8f4b7d1
Create Date: 2026-11-07

A listening placement question is heard, not read: the page shows no prompt text, only the
options. Existing rows are ordinary questions, so they backfill to False.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e1f95b24"
down_revision = "e5a2c8f4b7d1"
branch_labels = None
depends_on = None


def _columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("map_questions")}


def upgrade():
    if "audio_only" not in _columns():
        op.add_column(
            "map_questions",
            sa.Column("audio_only", sa.Boolean(), nullable=True, server_default=sa.false()),
        )


def downgrade():
    if "audio_only" in _columns():
        with op.batch_alter_table("map_questions") as batch_op:
            batch_op.drop_column("audio_only")
