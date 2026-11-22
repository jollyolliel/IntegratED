"""reconcile schema with models

Revision ID: 49f840084b51
Revises: cf3700945711
Create Date: 2026-10-04 14:26:58.560902

Brings a database built by replaying the chain into line with `models.py`, and
leaves one built by `db.create_all()` untouched — every step is guarded:

  - questions / learning_sessions: `ix_*_subtopic_id` -> `ix_*_lesson_id`
    (a7c3f9d1e2b4 renamed the column, not its index)
  - learning_sessions: `ix_learning_sessions_learner_session_lesson`, created by
    f3a8c1d9b6e7 and now declared on LearningSession
  - learning_sessions: the legacy `UNIQUE (learner_id)` f3a8c1d9b6e7 could not
    find on SQLite, where it is unnamed
  - learning_sessions.lesson_id -> lessons.id foreign key, which e1f2a3b4c5d6's
    map_sessions-rename branch never added. Sessions pointing at a lesson that
    no longer exists are deleted first: every lookup filters on lesson_id, so
    they are unreachable, and the constraint cannot be added while they exist.
"""
import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '49f840084b51'
down_revision = 'cf3700945711'
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

LESSON_FK = "learning_sessions_lesson_id_fkey"  # Postgres' own name under create_all()
COMPOSITE_INDEX = "ix_learning_sessions_learner_session_lesson"

# Gives SQLite's unnamed constraints a name batch mode can drop them by.
NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _index_names(inspector, table):
    return {index["name"] for index in inspector.get_indexes(table)}


def _lesson_fks(inspector):
    return [
        fk for fk in inspector.get_foreign_keys("learning_sessions")
        if fk["constrained_columns"] == ["lesson_id"] and fk["referred_table"] == "lessons"
    ]


def _swap_index(batch_op, existing, old, new, columns):
    if old in existing:
        batch_op.drop_index(old)
    if new not in existing:
        batch_op.create_index(new, columns)


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    question_indexes = _index_names(inspector, "questions")
    if "ix_questions_subtopic_id" in question_indexes or "ix_questions_lesson_id" not in question_indexes:
        with op.batch_alter_table("questions") as batch_op:
            _swap_index(batch_op, question_indexes, "ix_questions_subtopic_id", "ix_questions_lesson_id", ["lesson_id"])

    session_indexes = _index_names(inspector, "learning_sessions")
    learner_uniques = [
        uc for uc in inspector.get_unique_constraints("learning_sessions") if uc["column_names"] == ["learner_id"]
    ]
    add_lesson_fk = not _lesson_fks(inspector)

    if add_lesson_fk:
        orphans = conn.execute(sa.text(
            "DELETE FROM learning_sessions "
            "WHERE lesson_id IS NOT NULL AND lesson_id NOT IN (SELECT id FROM lessons)"
        ))
        if orphans.rowcount:
            logger.warning("Deleted %s learning session(s) whose lesson no longer exists", orphans.rowcount)

    if not (
        learner_uniques
        or add_lesson_fk
        or "ix_learning_sessions_subtopic_id" in session_indexes
        or "ix_learning_sessions_lesson_id" not in session_indexes
        or COMPOSITE_INDEX not in session_indexes
    ):
        return

    with op.batch_alter_table("learning_sessions", naming_convention=NAMING_CONVENTION) as batch_op:
        for unique in learner_uniques:
            # On Postgres this also takes the backing index of the same name —
            # never drop that index separately.
            batch_op.drop_constraint(unique["name"] or "uq_learning_sessions_learner_id", type_="unique")
        _swap_index(
            batch_op, session_indexes,
            "ix_learning_sessions_subtopic_id", "ix_learning_sessions_lesson_id", ["lesson_id"],
        )
        if COMPOSITE_INDEX not in session_indexes:
            batch_op.create_index(COMPOSITE_INDEX, ["learner_id", "session_type", "lesson_id"])
        if add_lesson_fk:
            batch_op.create_foreign_key(LESSON_FK, "lessons", ["lesson_id"], ["id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())

    question_indexes = _index_names(inspector, "questions")
    if "ix_questions_lesson_id" in question_indexes:
        with op.batch_alter_table("questions") as batch_op:
            _swap_index(batch_op, question_indexes, "ix_questions_lesson_id", "ix_questions_subtopic_id", ["lesson_id"])

    session_indexes = _index_names(inspector, "learning_sessions")
    lesson_fks = _lesson_fks(inspector)
    with op.batch_alter_table("learning_sessions", naming_convention=NAMING_CONVENTION) as batch_op:
        for fk in lesson_fks:
            batch_op.drop_constraint(fk["name"] or "fk_learning_sessions_lesson_id_lessons", type_="foreignkey")
        if "ix_learning_sessions_lesson_id" in session_indexes:
            _swap_index(
                batch_op, session_indexes,
                "ix_learning_sessions_lesson_id", "ix_learning_sessions_subtopic_id", ["lesson_id"],
            )
