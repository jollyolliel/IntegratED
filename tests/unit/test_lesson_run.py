"""`lesson_run` and `hint`: what a run of a lesson serves and where it resumes, and when a typed
answer's hint is given — the lesson logic the lessons API only serialises."""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def lesson_of(db_session):
    """A lesson of `game_type` with one question per content type given, in order."""
    from tests.support.factories import (
        make_lesson,
        make_question,
        make_subject,
        make_topic,
    )

    def _make(*content_types, game_type=None, **question_fields):
        subject = make_subject(db_session)
        topic = make_topic(db_session, subject)
        lesson = make_lesson(db_session, topic, game_type=game_type)
        questions = [
            make_question(db_session, subject, topic, lesson, content_type=kind,
                          question_text=f"Question {index}", **question_fields)
            for index, kind in enumerate(content_types)
        ]
        return lesson, questions

    return _make


def test_a_fresh_run_serves_every_question_and_starts_at_the_first(app, db_session, school, teacher, lesson_of):
    from helpers.learning import lesson_run
    from tests.support.factories import make_learner

    lesson, questions = lesson_of("multiple_choice", "open_answer")
    learner = make_learner(db_session, school, teacher)

    run = lesson_run(learner.id, lesson)

    assert [q.id for q in run.questions] == [q.id for q in questions]
    assert (run.resume_index, run.correct_ids, run.unit_count) == (0, [], 2)


def test_a_run_resumes_on_the_audio_question_leading_into_the_first_unanswered(
    app, db_session, school, teacher, lesson_of
):
    from helpers.learning import answer_log, lesson_run
    from tests.support.factories import make_learner

    lesson, (first, audio, _third) = lesson_of("multiple_choice", "vocabulary_audio", "multiple_choice")
    learner = make_learner(db_session, school, teacher)
    for question in (first, audio):
        answer_log.log_answer(learner.id, lesson.id, answer_log.question_unit(question.id), question.id, True)

    run = lesson_run(learner.id, lesson)

    assert run.resume_index == 1
    assert run.correct_ids == [first.id]  # the audio question is about to be shown again


def test_match_up_pairs_are_grouped_by_their_question(app, db_session, school, teacher, lesson_of):
    from helpers.learning import lesson_run
    from tests.support.factories import make_learner

    pairs = [{"left": "cat", "right": "animal"}, {"left": "red", "right": "colour"}]
    lesson, (match,) = lesson_of("match", game_type="match_up", match_pairs=pairs, options=None)
    learner = make_learner(db_session, school, teacher)

    run = lesson_run(learner.id, lesson)

    assert run.pairs == {match.id: [("cat", "animal"), ("red", "colour")]}
    assert run.unit_count == 2


@pytest.mark.parametrize(("content_type", "wrong_tries", "expected"), [
    ("open_answer", 2, None),
    ("open_answer", 3, "yes"),
    ("text_comprehension_fill_blank", 3, "yes"),
    ("multiple_choice", 5, None),
])
def test_a_typed_answer_is_hinted_after_three_wrong_tries(
    app, db_session, school, teacher, lesson_of, content_type, wrong_tries, expected
):
    from helpers.learning import answer_log, hint
    from tests.support.factories import make_learner

    lesson, (question,) = lesson_of(content_type, answer="yes")
    learner = make_learner(db_session, school, teacher)
    unit = answer_log.question_unit(question.id)
    log = None
    for _ in range(wrong_tries):
        log = answer_log.log_answer(learner.id, lesson.id, unit, question.id, False)

    assert hint(question, log) == expected


def test_a_hint_falls_back_to_the_first_accepted_fill_in_word(app, db_session, school, teacher, lesson_of):
    from helpers.learning import answer_log, hint
    from tests.support.factories import make_learner

    lesson, (question,) = lesson_of("text_comprehension_fill_blank", answer=None, fill_blank_options=["cat", "kitten"])
    learner = make_learner(db_session, school, teacher)
    unit = answer_log.question_unit(question.id)
    log = None
    for _ in range(3):
        log = answer_log.log_answer(learner.id, lesson.id, unit, question.id, False)

    assert hint(question, log) == "cat"
