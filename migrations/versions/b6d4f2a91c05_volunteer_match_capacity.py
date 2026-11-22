"""Volunteer match capacity — allow several learners per volunteer

Adds volunteers.match_capacity (teacher-controlled, default 1) and removes the
one-to-one UNIQUE on learners.volunteer_id that made a second learner per
volunteer an IntegrityError. A plain index replaces it — the column is still
looked up by volunteer, just no longer exclusive.

Existing rows keep capacity 1, so current pairings stay exactly as they are.

Revision ID: b6d4f2a91c05
Revises: e5a3f81c9b47
Create Date: 2026-08-12
"""

import sqlalchemy as sa
from alembic import op

revision = "b6d4f2a91c05"
down_revision = "e5a3f81c9b47"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_learners_volunteer_id"


def _unique_names(inspector):
    """UNIQUE on learners.volunteer_id can be recorded either as a constraint
    or as a unique index depending on how the DB was created — collect both."""
    constraint = next(
        (
            uc.get("name")
            for uc in inspector.get_unique_constraints("learners")
            if uc.get("column_names") == ["volunteer_id"]
        ),
        None,
    )
    index = next(
        (
            ix.get("name")
            for ix in inspector.get_indexes("learners")
            if ix.get("unique") and ix.get("column_names") == ["volunteer_id"]
        ),
        None,
    )
    return constraint, index


def _drop_plan(inspector):
    """Names to drop — index only when it is a separate object."""
    # Postgres backs a UNIQUE constraint with an index of the same name;
    # DROP CONSTRAINT removes it, and a second DROP INDEX then fails.
    constraint, index = _unique_names(inspector)
    if index is not None and index == constraint:
        index = None
    return constraint, index


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "match_capacity" not in {c["name"] for c in inspector.get_columns("volunteers")}:
        op.add_column(
            "volunteers",
            sa.Column(
                "match_capacity",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    uq_constraint, uq_index = _drop_plan(inspector)

    if conn.dialect.name == "sqlite":
        # SQLite writes `volunteer_id INTEGER UNIQUE` inline, so the constraint
        # has no name to drop — the table has to be rebuilt from a reflected
        # copy with the constraint stripped out.
        meta = sa.MetaData()
        learners = sa.Table("learners", meta, autoload_with=conn)
        for constraint in list(learners.constraints):
            if isinstance(constraint, sa.UniqueConstraint) and [
                c.name for c in constraint.columns
            ] == ["volunteer_id"]:
                learners.constraints.discard(constraint)
        learners.columns["volunteer_id"].unique = False

        with op.batch_alter_table(
            "learners", recreate="always", copy_from=learners
        ) as batch_op:
            if uq_index:
                batch_op.drop_index(uq_index)
    else:
        if uq_constraint:
            op.drop_constraint(uq_constraint, "learners", type_="unique")
        if uq_index:
            op.drop_index(uq_index, table_name="learners")

    inspector = sa.inspect(conn)
    if _INDEX_NAME not in {ix["name"] for ix in inspector.get_indexes("learners")}:
        op.create_index(_INDEX_NAME, "learners", ["volunteer_id"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("learners")}
    if _INDEX_NAME in existing_indexes:
        op.drop_index(_INDEX_NAME, table_name="learners")

    # Only one learner may survive per volunteer once the constraint returns.
    op.execute(
        """
        UPDATE learners SET volunteer_id = NULL, is_matched = FALSE
        WHERE id NOT IN (
            SELECT MIN(id) FROM learners
            WHERE volunteer_id IS NOT NULL GROUP BY volunteer_id
        ) AND volunteer_id IS NOT NULL
        """
    )

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("learners", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_learners_volunteer_id", ["volunteer_id"]
            )
    else:
        op.create_unique_constraint(
            "uq_learners_volunteer_id", "learners", ["volunteer_id"]
        )

    if "match_capacity" in {c["name"] for c in inspector.get_columns("volunteers")}:
        op.drop_column("volunteers", "match_capacity")
