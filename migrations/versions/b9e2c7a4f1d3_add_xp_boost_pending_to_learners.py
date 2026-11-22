"""add xp_boost_pending to learners

Revision ID: b9e2c7a4f1d3
Revises: 686353061f9b
Create Date: 2026-10-31

The golden potion XP boost: a first-time Potion Workshop completion with a golden potion sets it,
and the learner's next first-time lesson completion earns double XP and clears it. Existing rows
backfill to False — nobody has a boost waiting yet.
"""

import sqlalchemy as sa
from alembic import op

revision = "b9e2c7a4f1d3"
down_revision = "686353061f9b"
branch_labels = None
depends_on = None


def _learner_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("learners")}


def upgrade():
    if "xp_boost_pending" not in _learner_columns():
        op.add_column(
            "learners",
            sa.Column("xp_boost_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    if "xp_boost_pending" in _learner_columns():
        with op.batch_alter_table("learners") as batch_op:
            batch_op.drop_column("xp_boost_pending")
