import pytest

pytestmark = pytest.mark.integration


def test_attendance_hours_are_counted_from_learner_rows_only(db_session, school, teacher):
    from models import Attendance
    from tests.support.factories import make_attendance, make_learner, make_volunteer

    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)
    learner.volunteer_match = volunteer
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()
    make_attendance(db_session, teacher, learner, partner=volunteer, duration=2)
    make_attendance(db_session, teacher, volunteer, partner=learner, duration=2)

    assert learner.hours_learned == 2.0
    assert volunteer.hours_volunteered == 2.0
    assert Attendance.programme_hours() == 2.0


def test_recommended_worksheets_prefers_subject_and_topic_matches(db_session):
    from helpers.learning import get_recommended_worksheets
    from tests.support.factories import make_worksheet

    close = make_worksheet(db_session, title="Grammar Basics", subject="English Grammar", topic="Basics")
    far = make_worksheet(db_session, title="Fractions", subject="Math", topic="Numbers")

    recommendations = get_recommended_worksheets(
        "English Grammar", "Basics", worksheet_pool=[far, close]
    )

    assert recommendations[0] is close


def test_recommended_worksheets_follow_an_edited_title(db_session):
    """Cached tokens must not outlive the worksheet text they came from."""
    from helpers.learning import get_recommended_worksheets
    from tests.support.factories import make_worksheet

    target = make_worksheet(db_session, title="Fractions", subject="Math", topic="Numbers")
    other = make_worksheet(db_session, title="Grammar Basics", subject="English Grammar", topic="Basics")
    pool = [target, other]

    assert get_recommended_worksheets("English Grammar", "Basics", worksheet_pool=pool)[0] is other

    target.subject = "English Grammar"
    target.topic = "Basics"
    target.title = "Basics Drill"
    db_session.commit()

    assert get_recommended_worksheets("English Grammar", "Basics", worksheet_pool=pool)[0] is not None
    assert {w.id for w in get_recommended_worksheets(
        "English Grammar", "Basics", limit=2, worksheet_pool=pool)} == {target.id, other.id}


def test_pair_summaries_recommend_per_subject_not_per_learner(db_session, school):
    """Two learners at the same place get the same worksheets."""
    from helpers.learning import build_teacher_pair_summaries
    from tests.support.factories import (
        make_learner,
        make_teacher,
        make_volunteer,
        make_worksheet,
    )

    teacher = make_teacher(db_session, school)
    volunteer = make_volunteer(db_session, school, teacher, match_capacity=2)
    for i in range(4):
        make_worksheet(db_session, title=f"Sheet {i}", subject="English Grammar")
    for i in range(2):
        make_learner(
            db_session, school, teacher, name=f"L{i}",
            is_matched=True, volunteer_id=volunteer.id,
        )
    db_session.commit()

    summaries = build_teacher_pair_summaries(teacher, recommendation_limit=2)

    assert len(summaries) == 2
    assert [w.id for w in summaries[0]["worksheets"]] == [w.id for w in summaries[1]["worksheets"]]


def test_recommended_worksheets_prefer_the_learners_level(db_session):
    from helpers.learning import get_recommended_worksheets
    from tests.support.factories import make_worksheet

    level_one = make_worksheet(db_session, title="A Sheet", subject="English: Reading Start", topic="Sight words", level=1)
    level_two = make_worksheet(db_session, title="B Sheet", subject="English: Reading Start", topic="Sight words", level=2)
    pool = [level_one, level_two]

    assert get_recommended_worksheets("English: Reading Start", "Sight words", worksheet_pool=pool, level=2)[0] is level_two
    assert get_recommended_worksheets("English: Reading Start", "Sight words", worksheet_pool=pool, level=1)[0] is level_one
    # Without a level the old order holds: ties break by title.
    assert get_recommended_worksheets("English: Reading Start", "Sight words", worksheet_pool=pool)[0] is level_one


def test_a_level_match_never_outranks_a_subject_match(db_session):
    from helpers.learning import get_recommended_worksheets
    from tests.support.factories import make_worksheet

    on_subject = make_worksheet(db_session, title="Grammar", subject="English Grammar", topic="Basics")
    on_level = make_worksheet(db_session, title="Fractions", subject="Maths", topic="Numbers", level=2)

    assert get_recommended_worksheets("English Grammar", "Basics", worksheet_pool=[on_level, on_subject],
                                      level=2)[0] is on_subject


def _banded_course(db_session):
    from tests.support.factories import make_subject, make_topic

    scale = make_subject(db_session, name="English", map_test_only=True)
    course = make_subject(db_session, name="English: Reading Start", placement_scale_id=scale.id,
                          placement_min_level=1, placement_max_level=3)
    topics = [make_topic(db_session, course, title=f"Topic {n}", level=n) for n in (1, 2, 3)]
    return course, topics


def test_the_pair_snapshot_carries_the_learners_level_on_the_scale(db_session, school):
    from helpers.learning import get_pair_learning_snapshot
    from tests.support.factories import make_learner, make_teacher

    _course, topics = _banded_course(db_session)
    teacher = make_teacher(db_session, school)
    placed = make_learner(db_session, school, teacher, subject_levels={"English": 2})
    progressed = make_learner(db_session, school, teacher, subject_levels={"English": 1},
                              completed_topic_ids=[topics[2].id])
    unplaced = make_learner(db_session, school, teacher, subject_levels={})

    assert get_pair_learning_snapshot(placed)["level"] == 2
    assert get_pair_learning_snapshot(progressed)["level"] == 3
    assert get_pair_learning_snapshot(unplaced)["level"] is None


def test_pair_summaries_recommend_per_level_too(db_session, school):
    """Two learners on the same course and topic at different levels get their own level's sheets."""
    from helpers.learning import build_teacher_pair_summaries
    from tests.support.factories import (
        make_learner,
        make_teacher,
        make_volunteer,
        make_worksheet,
    )

    _banded_course(db_session)
    teacher = make_teacher(db_session, school)
    volunteer = make_volunteer(db_session, school, teacher, match_capacity=2)
    one = make_worksheet(db_session, title="Level One", subject="English: Reading Start", level=1)
    two = make_worksheet(db_session, title="Level Two", subject="English: Reading Start", level=2)
    for name, level in (("A", 1), ("B", 2)):
        make_learner(db_session, school, teacher, name=name, is_matched=True, volunteer_id=volunteer.id,
                     subject_levels={"English": level})
    db_session.commit()

    summaries = build_teacher_pair_summaries(teacher, recommendation_limit=1)

    assert [s["worksheets"][0].id for s in summaries] == [one.id, two.id]
