"""answer logs get their own session type

Revision ID: e8c4a2f6d9b1
Revises: c7d1a3e9f5b2
Create Date: 2026-11-18

A lesson's in-progress answer log was `session_type='quiz'` for every lesson type, so the quiz could
not keep a result row of its own the way each game does, and a repeated quiz completion reported a
score of 0. Answer logs are now `session_type='answer_log'`, which frees `'quiz'` for the quiz's
result row. Every existing log is renamed; no quiz result rows exist yet, so nothing collides.
"""

import sqlalchemy as sa
from alembic import op

revision = "e8c4a2f6d9b1"
down_revision = "c7d1a3e9f5b2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("UPDATE learning_sessions SET session_type = 'answer_log' WHERE session_type = 'quiz'"))


def downgrade():
    # Quiz result rows have no place in the old scheme ('quiz' meant the answer log), so they go
    # before the logs take the name back.
    op.execute(sa.text("DELETE FROM learning_sessions WHERE session_type = 'quiz'"))
    op.execute(sa.text("UPDATE learning_sessions SET session_type = 'quiz' WHERE session_type = 'answer_log'"))
