"""Teacher.match_settings — per-factor matching weights and spread level

The teacher says which factors the matcher should care about and how hard it
should keep spreading learners across volunteers. Stored as one JSON blob of
level indices, `{"weights": {<factor>: <level>}, "spread": <level>}`.

Nullable with no backfill on purpose: helpers/matching.normalize_levels reads
NULL, `{}` and a half-written blob alike as the balanced defaults, which are
exactly the weights every existing teacher was already matching on.

Revision ID: cf3700945711
Revises: b3d41f9c27ae
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op

revision = "cf3700945711"
down_revision = "b3d41f9c27ae"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("teachers")}

    if "match_settings" not in existing_columns:
        op.add_column("teachers", sa.Column("match_settings", sa.JSON(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {c["name"] for c in inspector.get_columns("teachers")}

    if "match_settings" in existing_columns:
        op.drop_column("teachers", "match_settings")
