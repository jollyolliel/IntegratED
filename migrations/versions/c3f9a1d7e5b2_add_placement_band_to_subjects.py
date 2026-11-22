"""add placement band to subjects

Revision ID: c3f9a1d7e5b2
Revises: b9e2c7a4f1d3
Create Date: 2026-11-06

Courses on a shared placement scale (ADR 0016): a subject may name the placement scale it sits on
(`placement_scale_id`, another subject) and the band of that scale's levels it serves
(`placement_min_level`..`placement_max_level`). All three stay NULL for existing subjects, which keep
working as before; the importer fills them from `data/questions.json`.
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f9a1d7e5b2"
down_revision = "b9e2c7a4f1d3"
branch_labels = None
depends_on = None

_FK = "fk_subjects_placement_scale_id_subjects"


def _subject_columns():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subjects")}


def upgrade():
    if "placement_scale_id" in _subject_columns():
        return
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.add_column(sa.Column("placement_scale_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("placement_min_level", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("placement_max_level", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(_FK, "subjects", ["placement_scale_id"], ["id"])


def downgrade():
    if "placement_scale_id" not in _subject_columns():
        return
    with op.batch_alter_table("subjects") as batch_op:
        batch_op.drop_constraint(_FK, type_="foreignkey")
        batch_op.drop_column("placement_max_level")
        batch_op.drop_column("placement_min_level")
        batch_op.drop_column("placement_scale_id")
