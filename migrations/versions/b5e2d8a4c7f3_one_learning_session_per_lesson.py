"""one learning session per learner, type and lesson

Revision ID: b5e2d8a4c7f3
Revises: a9c4e7d2b8f1
Create Date: 2026-11-15

A lesson's answer log and each game's result record are one row per (learner, session type,
lesson). The composite index did not enforce that, so two first answers arriving together made
two answer logs. Duplicates are removed first, keeping the oldest row of each, then the index
becomes a unique constraint. Placement sessions have no lesson and are untouched by it.

In-progress placement tests are also cleared, once: their staircase state now has a fixed shape
(`ScaleState`), and the code no longer upgrades older states. A placement session lives only
for one sitting (ADR 0002), so a learner mid-test at the deploy simply starts it again.
"""

import sqlalchemy as sa
from alembic import op

revision = "b5e2d8a4c7f3"
down_revision = "a9c4e7d2b8f1"
branch_labels = None
depends_on = None

_INDEX = "ix_learning_sessions_learner_session_lesson"
_UNIQUE = "uq_learning_sessions_learner_session_lesson"
_COLUMNS = ["learner_id", "session_type", "lesson_id"]


def _index_names():
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("learning_sessions")}


def upgrade():
    op.execute(sa.text("DELETE FROM learning_sessions WHERE session_type = 'placement'"))
    op.execute(sa.text(
        "DELETE FROM learning_sessions WHERE lesson_id IS NOT NULL AND id NOT IN ("
        " SELECT keep_id FROM (SELECT MIN(id) AS keep_id FROM learning_sessions"
        " WHERE lesson_id IS NOT NULL GROUP BY learner_id, session_type, lesson_id) AS kept)"
    ))
    with op.batch_alter_table("learning_sessions") as batch_op:
        if _INDEX in _index_names():
            batch_op.drop_index(_INDEX)
        batch_op.create_unique_constraint(_UNIQUE, _COLUMNS)


def downgrade():
    with op.batch_alter_table("learning_sessions") as batch_op:
        batch_op.drop_constraint(_UNIQUE, type_="unique")
        batch_op.create_index(_INDEX, _COLUMNS)
