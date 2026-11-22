"""Teacher.default_match_capacity — learner limit given to new volunteers

The teacher picks the limit once, beside Auto-Match, and every volunteer who
joins under them starts there instead of at the hard-coded 1. Existing rows
backfill to 1, which is exactly what they were doing implicitly, so no
volunteer's own match_capacity is touched.

Revision ID: d4b7e209fa61
Revises: a92f5d17c4be
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d4b7e209fa61"
down_revision = "a92f5d17c4be"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("teachers")}

    if "default_match_capacity" not in existing_columns:
        op.add_column(
            "teachers",
            sa.Column(
                "default_match_capacity",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.execute(
            "UPDATE teachers SET default_match_capacity = 1 "
            "WHERE default_match_capacity IS NULL"
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("teachers")}

    if "default_match_capacity" in existing_columns:
        op.drop_column("teachers", "default_match_capacity")
