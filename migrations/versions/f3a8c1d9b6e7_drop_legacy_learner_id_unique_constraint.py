"""Drop legacy unique constraint on learning_sessions.learner_id

The old map_sessions table had a one-to-one unique constraint on
learner_id (a learner could only have a single placement session).
e1f2a3b4c5d6 renamed map_sessions -> learning_sessions to support many
sessions per learner (placement/quiz/game), but never dropped the
inherited unique constraint, so multi-session inserts on the live DB
still get rejected. This drops it and adds the composite index actually
used by lookups.

Revision ID: f3a8c1d9b6e7
Revises: a7c3f9d1e2b4
Create Date: 2026-06-24 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "f3a8c1d9b6e7"
down_revision = "a7c3f9d1e2b4"
branch_labels = None
depends_on = None


def _find_unique_constraint_name(inspector, table_name, column_name):
    for uc in inspector.get_unique_constraints(table_name):
        if uc.get("column_names") == [column_name]:
            return uc.get("name")
    return None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    uq_name = _find_unique_constraint_name(inspector, "learning_sessions", "learner_id")

    with op.batch_alter_table("learning_sessions", recreate="always") as batch_op:
        if uq_name:
            batch_op.drop_constraint(uq_name, type_="unique")
        batch_op.create_index(
            "ix_learning_sessions_learner_session_lesson",
            ["learner_id", "session_type", "lesson_id"],
        )


def downgrade():
    with op.batch_alter_table("learning_sessions", recreate="always") as batch_op:
        batch_op.drop_index("ix_learning_sessions_learner_session_lesson")
        batch_op.create_unique_constraint("uq_map_sessions_learner_id", ["learner_id"])
