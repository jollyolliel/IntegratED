from typing import TYPE_CHECKING, cast

import pytest

from helpers.learning import (
    validate_fill_blank,
    validate_multiple_choice,
    validate_open_answer,
    validate_word_selection,
)

if TYPE_CHECKING:
    from models import Question

pytestmark = pytest.mark.unit


def test_the_first_step_is_the_placement_start_before_any_lesson_is_finished(db_session):
    from helpers.learning import get_first_step
    from tests.support.factories import make_learner, make_learning_content

    subject, topic, _lesson, _question = make_learning_content(db_session)
    learner = make_learner(db_session, subject_levels={subject.name: 1})

    first_step = get_first_step(learner)

    assert first_step is not None and first_step["topic_id"] == topic.id


def test_the_first_step_is_gone_once_any_lesson_is_finished(db_session):
    from helpers.learning import get_first_step
    from tests.support.factories import make_learner, make_learning_content

    subject, _topic, lesson, _question = make_learning_content(db_session)
    learner = make_learner(db_session, subject_levels={subject.name: 1}, completed_lesson_ids=[lesson.id])

    assert get_first_step(learner) is None


@pytest.mark.parametrize(
    "validator, question, answer, expected",
    [
        (validate_multiple_choice, type("Q", (), {"answer": "Yes"})(), " yes ", True),
        (validate_open_answer, type("Q", (), {"answer": "Yes"})(), "YES", True),
        (validate_fill_blank, type("Q", (), {"answer": "Yes", "fill_blank_options": []})(), "no", False),
    ],
)
def test_answer_validators_return_a_boolean(validator, question, answer, expected):
    assert validator(question, answer) is expected


def test_word_selection_rejects_an_incorrect_selected_word():
    question = cast("Question", type(
        "Q",
        (),
        {"word_selection_correct_words": ["learn"], "id": 4},
    )())

    result = validate_word_selection(question, ["learn", "wrong"])

    assert result.is_correct is False
    assert result.partial_credit == 0


def test_word_selection_gives_partial_credit_for_a_clean_partial_pick():
    question = cast("Question", type("Q", (), {"word_selection_correct_words": ["learn", "read"]})())

    assert validate_word_selection(question, ["learn"]) == (False, 50)
    assert validate_word_selection(question, ["Read", "learn"]) == (True, 100)


def test_pairs_at_the_same_place_share_one_worksheet_lookup(db_session, monkeypatch):
    from helpers.learning import _snapshot, build_teacher_pair_summaries
    from tests.support.factories import (
        make_learner,
        make_school,
        make_teacher,
        make_volunteer,
    )

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    for _ in range(3):
        volunteer = make_volunteer(db_session, school, teacher, is_matched=True)
        make_learner(db_session, school, teacher, volunteer_id=volunteer.id, is_matched=True)
    db_session.expire_all()
    calls = []
    monkeypatch.setattr(_snapshot, "get_recommended_worksheets", lambda *a, **k: calls.append(a) or [])

    summaries = build_teacher_pair_summaries(teacher, recommendation_limit=2)

    assert len(summaries) == 3
    assert len(calls) == 1
