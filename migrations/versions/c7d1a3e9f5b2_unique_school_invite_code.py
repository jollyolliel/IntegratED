"""one school per invite code

Revision ID: c7d1a3e9f5b2
Revises: b5e2d8a4c7f3
Create Date: 2026-11-18

Invite codes are random six-character strings, so two schools could in principle draw the same one
and a joiner would land in whichever the query returned first. A unique index makes that
impossible; `regenerate_invite_code` draws again on a collision. NULL codes do not collide.
Any duplicate already stored is cleared first (the school gets a fresh code on its next visit to
the teacher dashboard), keeping the lowest school id.
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d1a3e9f5b2"
down_revision = "b5e2d8a4c7f3"
branch_labels = None
depends_on = None

_INDEX = "uq_schools_invite_code"


def _has_index() -> bool:
    return _INDEX in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("schools")}


def upgrade():
    op.execute(sa.text(
        "UPDATE schools SET invite_code = NULL WHERE invite_code IS NOT NULL AND id NOT IN ("
        " SELECT keep_id FROM (SELECT MIN(id) AS keep_id FROM schools"
        " WHERE invite_code IS NOT NULL GROUP BY invite_code) AS kept)"
    ))
    # A create_all database already has it from the model.
    if not _has_index():
        op.create_index(_INDEX, "schools", ["invite_code"], unique=True)


def downgrade():
    if _has_index():
        op.drop_index(_INDEX, table_name="schools")
