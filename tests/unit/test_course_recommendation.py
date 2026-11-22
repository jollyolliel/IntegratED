"""`get_recommended_start` and the staff snapshots once courses sit on a placement scale."""

import pytest

from tests.support.factories import make_learner, make_lesson, make_subject, make_topic

pytestmark = pytest.mark.unit


@pytest.fixture
def english(db_session):
    """An `English` placement scale (levels 1-6) split over three courses, two topics each."""
    scale = make_subject(db_session, name="English", map_test_only=True)
    courses = {}
    for name, (low, high) in {"First Steps": (1, 2), "Reading": (3, 4), "Everyday": (5, 6)}.items():
        course = make_subject(db_session, name=name, placement_scale_id=scale.id,
                              placement_min_level=low, placement_max_level=high)
        topics = [make_topic(db_session, course, title=f"{name} {level}", level=level) for level in (low, high)]
        for topic in topics:
            make_lesson(db_session, topic, title=f"{topic.title} lesson")
        courses[name] = (course, topics)
    db_session.commit()
    return scale, courses


@pytest.mark.parametrize(
    "level, course, topic_index",
    [(1, "First Steps", 0), (2, "First Steps", 1), (3, "Reading", 0), (4, "Reading", 1), (6, "Everyday", 1)],
)
def test_the_assessed_level_picks_the_course_whose_band_holds_it(db_session, english, level, course, topic_index):
    from helpers.learning import get_recommended_start

    _scale, courses = english
    learner = make_learner(db_session, subject_levels={"English": level})

    start = get_recommended_start(learner)

    expected_course, topics = courses[course]
    assert start is not None
    assert start["subject_id"] == expected_course.id
    assert start["subject"] == course
    assert start["topic_id"] == topics[topic_index].id
    assert start["placement_scale"] == "English"
    assert start["assessed_level"] == level


def test_a_level_above_every_band_clamps_to_the_highest_course(db_session, english):
    from helpers.learning import get_recommended_start

    _scale, courses = english
    learner = make_learner(db_session, subject_levels={"English": 9})

    start = get_recommended_start(learner)

    assert start is not None and start["subject_id"] == courses["Everyday"][0].id


def test_several_topics_at_one_level_start_at_the_first_of_them(db_session, english):
    from helpers.learning import get_recommended_start

    _scale, courses = english
    reading, topics = courses["Reading"]
    later = make_topic(db_session, reading, title="Reading 3b", level=3)
    make_lesson(db_session, later)
    learner = make_learner(db_session, subject_levels={"English": 3})

    start = get_recommended_start(learner)

    assert start is not None and start["topic_id"] == topics[0].id


def test_a_course_that_is_its_own_placement_subject_still_recommends_inside_itself(db_session):
    from helpers.learning import get_recommended_start

    grammar = make_subject(db_session, name="English Grammar")
    make_topic(db_session, grammar, title="Nouns", level=1)
    verbs = make_topic(db_session, grammar, title="Verbs", level=2)
    db_session.commit()
    learner = make_learner(db_session, subject_levels={"English Grammar": 2})

    start = get_recommended_start(learner)

    assert start is not None
    assert start["topic_id"] == verbs.id
    assert start["placement_scale"] == "English Grammar"


def test_a_scale_with_no_courses_on_it_recommends_nothing(db_session):
    from helpers.learning import get_recommended_start

    make_subject(db_session, name="Maths", map_test_only=True)
    learner = make_learner(db_session, subject_levels={"Maths": 2})

    assert get_recommended_start(learner) is None


def test_a_placed_learner_who_has_not_started_is_shown_in_their_recommended_course(db_session, english):
    from helpers.learning import (
        get_learner_progress_position,
        get_pair_learning_snapshot,
    )

    _scale, courses = english
    learner = make_learner(db_session, subject_levels={"English": 4})

    position = get_learner_progress_position(learner)
    snapshot = get_pair_learning_snapshot(learner)

    assert position["subject"] == "Reading"
    assert position["topic"] == courses["Reading"][1][0].title
    assert snapshot["subject"] == "Reading"


def test_current_topic_progress_counts_only_lessons_in_the_topic_being_worked_on(db_session):
    from helpers.learning import get_current_topic_progress

    course = make_subject(db_session, name="English Grammar")
    nouns = make_topic(db_session, course, title="Nouns", level=1)
    verbs = make_topic(db_session, course, title="Verbs", level=2)
    noun_lessons = [make_lesson(db_session, nouns, title=f"Noun {i}") for i in range(2)]
    verb_lessons = [make_lesson(db_session, verbs, title=f"Verb {i}") for i in range(4)]
    db_session.commit()
    learner = make_learner(
        db_session,
        subject_levels={"English Grammar": 1},
        completed_lesson_ids=[lesson.id for lesson in noun_lessons] + [verb_lessons[0].id],
    )

    progress = get_current_topic_progress(learner)

    assert progress == {"topic": "Verbs", "done": 1, "total": 4, "progress": 25}


def test_current_topic_progress_is_empty_for_a_learner_who_has_not_started(db_session):
    from helpers.learning import get_current_topic_progress

    learner = make_learner(db_session)

    assert get_current_topic_progress(learner)["topic"] is None
