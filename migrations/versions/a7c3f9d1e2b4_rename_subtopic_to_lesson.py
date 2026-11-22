"""Rename Subtopic -> Lesson throughout the schema

Renames:
  - table subtopics -> lessons
  - questions.subtopic_id -> lesson_id
  - learning_sessions.subtopic_id -> lesson_id
  - learners.completed_subtopic_ids -> completed_lesson_ids

Revision ID: a7c3f9d1e2b4
Revises: e1f2a3b4c5d6
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c3f9d1e2b4"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("subtopics", "lessons")

    with op.batch_alter_table("questions", schema=None) as batch_op:
        batch_op.alter_column("subtopic_id", new_column_name="lesson_id")

    with op.batch_alter_table("learning_sessions", schema=None) as batch_op:
        batch_op.alter_column("subtopic_id", new_column_name="lesson_id")

    with op.batch_alter_table("learners", schema=None) as batch_op:
        batch_op.alter_column("completed_subtopic_ids", new_column_name="completed_lesson_ids")


def downgrade():
    with op.batch_alter_table("learners", schema=None) as batch_op:
        batch_op.alter_column("completed_lesson_ids", new_column_name="completed_subtopic_ids")

    with op.batch_alter_table("learning_sessions", schema=None) as batch_op:
        batch_op.alter_column("lesson_id", new_column_name="subtopic_id")

    with op.batch_alter_table("questions", schema=None) as batch_op:
        batch_op.alter_column("lesson_id", new_column_name="subtopic_id")

    op.rename_table("lessons", "subtopics")
