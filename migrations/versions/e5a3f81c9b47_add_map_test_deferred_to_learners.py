"""add map_test_deferred to learners

Revision ID: e5a3f81c9b47
Revises: c7d2e9a41f83
Create Date: 2026-07-29

Separates "I'll do this later" from a genuine placement-test completion.
completed_map_test stays True for skippers (it's the dashboard gate), so this
flag is what lets the dashboard keep reminding them.

Existing rows backfill to False: a learner who skipped before this migration
is indistinguishable from one who finished (that data was never recorded), and
False = "no outstanding reminder" is the non-nagging default.
"""

import sqlalchemy as sa
from alembic import op

revision = "e5a3f81c9b47"
down_revision = "c7d2e9a41f83"
branch_labels = None
depends_on = None


def _learner_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("learners")}


def upgrade():
    if "map_test_deferred" not in _learner_columns():
        op.add_column(
            "learners",
            sa.Column("map_test_deferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    if "map_test_deferred" in _learner_columns():
        with op.batch_alter_table("learners") as batch_op:
            batch_op.drop_column("map_test_deferred")
