"""backfill completed_topic_ids

Minigame completions never rolled a finished topic up into
`Learner.completed_topic_ids` — only the quiz route did — so a topic finished
by games reads as unfinished everywhere that column is read. Roll up every
topic whose lessons are all in the learner's `completed_lesson_ids`. Data only,
no DDL; downgrade is a no-op since a backfilled id can't be told apart.

Revision ID: a7c3e9f1b2d4
Revises: 49f840084b51
Create Date: 2026-10-07 00:00:00.000000

"""
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a7c3e9f1b2d4'
down_revision = '49f840084b51'
branch_labels = None
depends_on = None


def _as_list(raw):
    if isinstance(raw, str):
        return json.loads(raw or '[]')
    return list(raw or [])


def backfill_completed_topic_ids(bind):
    lessons = sa.table('lessons', sa.column('id', sa.Integer), sa.column('topic_id', sa.Integer))
    learners = sa.table(
        'learners',
        sa.column('id', sa.Integer),
        sa.column('completed_lesson_ids', sa.JSON),
        sa.column('completed_topic_ids', sa.JSON),
    )

    lessons_by_topic = {}
    for lesson_id, topic_id in bind.execute(sa.select(lessons.c.id, lessons.c.topic_id)):
        lessons_by_topic.setdefault(topic_id, set()).add(lesson_id)

    rows = bind.execute(
        sa.select(learners.c.id, learners.c.completed_lesson_ids, learners.c.completed_topic_ids)
    ).all()
    for learner_id, raw_lessons, raw_topics in rows:
        done_lessons = set(_as_list(raw_lessons))
        topic_ids = _as_list(raw_topics)
        missing = sorted(
            topic_id for topic_id, ids in lessons_by_topic.items()
            if topic_id not in topic_ids and ids <= done_lessons
        )
        if missing:
            bind.execute(
                learners.update()
                .where(learners.c.id == learner_id)
                .values(completed_topic_ids=topic_ids + missing)
            )


def upgrade():
    backfill_completed_topic_ids(op.get_bind())


def downgrade():
    pass
