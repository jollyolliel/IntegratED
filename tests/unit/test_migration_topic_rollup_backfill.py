"""The data migration that rolls up topics finished before every completion route recorded it."""

import runpy
from pathlib import Path

import pytest

from tests.support.factories import (
    make_learner,
    make_learning_content,
    make_lesson,
    make_topic,
)

pytestmark = pytest.mark.unit

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "a7c3e9f1b2d4_backfill_completed_topic_ids.py"


@pytest.fixture
def backfill():
    return runpy.run_path(str(MIGRATION))["backfill_completed_topic_ids"]


def test_a_topic_with_every_lesson_finished_is_rolled_up(db_session, school, teacher, backfill):
    _subject, topic, lesson, _question = make_learning_content(db_session)
    learner = make_learner(db_session, school, teacher, completed_lesson_ids=[lesson.id], completed_topic_ids=[])
    db_session.commit()

    backfill(db_session.connection())

    db_session.expire_all()
    assert learner.completed_topic_ids == [topic.id]


def test_a_part_finished_topic_and_existing_roll_ups_are_left_alone(db_session, school, teacher, backfill):
    subject, topic, lesson, _question = make_learning_content(db_session)
    make_lesson(db_session, topic, title="Still To Do")
    done_earlier = make_topic(db_session, subject, title="Done Earlier", level=2)
    learner = make_learner(
        db_session, school, teacher, completed_lesson_ids=[lesson.id], completed_topic_ids=[done_earlier.id]
    )
    db_session.commit()

    backfill(db_session.connection())

    db_session.expire_all()
    assert learner.completed_topic_ids == [done_earlier.id]


def test_a_topic_with_no_lessons_is_never_rolled_up(db_session, school, teacher, backfill):
    subject, _topic, lesson, _question = make_learning_content(db_session)
    make_topic(db_session, subject, title="Empty Topic", level=2)
    learner = make_learner(db_session, school, teacher, completed_lesson_ids=[lesson.id], completed_topic_ids=[])
    db_session.commit()

    backfill(db_session.connection())

    db_session.expire_all()
    assert learner.completed_topic_ids == [lesson.topic_id]
