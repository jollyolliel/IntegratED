"""add garden_state to learners

Revision ID: c7d2e9a41f83
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24

Persistent Garden Grow game state on the learner:
{"stages": [0-3] * 8, "colors": ["#RRGGBB" | null] * 8}
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d2e9a41f83"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _learner_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("learners")}


def upgrade():
    if "garden_state" not in _learner_columns():
        op.add_column("learners", sa.Column("garden_state", sa.JSON(), nullable=True))


def downgrade():
    if "garden_state" in _learner_columns():
        with op.batch_alter_table("learners") as batch_op:
            batch_op.drop_column("garden_state")
