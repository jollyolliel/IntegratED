"""Model behaviour: matching invariants, live hour totals, cascades.

The hour properties are computed rather than stored precisely so that editing
attendance cannot leave a running total behind, so each is checked against a
real edit rather than only a fresh insert.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.support.factories import (
    make_attendance,
    make_learner,
    make_learning_content,
    make_school,
    make_teacher,
    make_volunteer,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def roster(db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    return {"school": school, "teacher": teacher}


def _match(db_session, learner, volunteer):
    learner.volunteer_match = volunteer
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()


# ── identity ─────────────────────────────────────────────────────────────────


def test_the_analytics_id_is_stable_and_opaque(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"])

    first = learner.posthog_id

    assert first == learner.posthog_id
    assert learner.username not in first
    assert len(first) == 24


def test_two_users_get_different_analytics_ids(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"])
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])

    assert learner.posthog_id != volunteer.posthog_id


# ── passwords ────────────────────────────────────────────────────────────────


def test_a_password_is_hashed_not_stored(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"], password="Secret1!")

    assert learner.password_hash != "Secret1!"
    assert learner.check_password("Secret1!") is True
    assert learner.check_password("Secret2!") is False


# ── capacity ─────────────────────────────────────────────────────────────────


def test_capacity_is_never_below_one(db_session, roster):
    """Rows predating the column read NULL until backfilled."""

    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = None

    assert volunteer.capacity == 1


def test_open_slots_shrink_as_learners_are_attached(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = 2
    db_session.commit()
    assert volunteer.open_slots == 2

    learner = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, learner, volunteer)

    assert volunteer.open_slots == 1
    assert volunteer.is_full is False


def test_a_volunteer_at_capacity_is_full(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = 1
    learner = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, learner, volunteer)

    assert volunteer.open_slots == 0
    assert volunteer.is_full is True


def test_open_slots_never_go_negative(db_session, roster):
    """Capacity lowered below the count already held must clamp at zero."""

    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = 2
    for _ in range(2):
        _match(db_session, make_learner(db_session, roster["school"], roster["teacher"]), volunteer)
    volunteer.match_capacity = 1
    db_session.commit()

    assert volunteer.open_slots == 0


def test_the_first_attached_learner_is_the_single_partner_view(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    assert volunteer.learner_match is None

    learner = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, learner, volunteer)

    assert volunteer.learner_match.id == learner.id


# ── unmatching ───────────────────────────────────────────────────────────────


def test_unmatching_clears_both_sides(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    learner = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, learner, volunteer)

    released = learner.unmatch()
    db_session.commit()

    assert released.id == volunteer.id
    assert learner.volunteer_id is None
    assert learner.is_matched is False
    assert volunteer.is_matched is False


def test_unmatching_leaves_a_volunteer_matched_when_others_remain(db_session, roster):
    """Clearing the flag on a volunteer who still holds learners is what makes
    the "available" lists lie."""

    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = 2
    first = make_learner(db_session, roster["school"], roster["teacher"])
    second = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, first, volunteer)
    _match(db_session, second, volunteer)

    first.unmatch()
    db_session.commit()

    assert volunteer.is_matched is True


def test_unmatching_an_unmatched_learner_is_harmless(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"])

    assert learner.unmatch() is None
    assert learner.is_matched is False


def test_the_exclude_argument_ignores_a_learner_detached_in_the_same_transaction(db_session, roster):
    """The relationship collection is not refreshed until flush."""

    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    learner = make_learner(db_session, roster["school"], roster["teacher"])
    _match(db_session, learner, volunteer)

    remaining = volunteer.sync_matched_flag(exclude_learner_id=learner.id)

    assert remaining == 0
    assert volunteer.is_matched is False


def test_releasing_every_learner_clears_the_whole_group(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    volunteer.match_capacity = 2
    learners = [make_learner(db_session, roster["school"], roster["teacher"]) for _ in range(2)]
    for learner in learners:
        _match(db_session, learner, volunteer)

    volunteer.release_learners()
    db_session.commit()

    assert volunteer.is_matched is False
    assert all(learner.volunteer_id is None for learner in learners)
    assert all(learner.is_matched is False for learner in learners)


# ── live hour totals ─────────────────────────────────────────────────────────


def test_learned_hours_sum_present_sessions_only(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"])
    make_attendance(db_session, roster["teacher"], learner, duration=1.5)
    make_attendance(db_session, roster["teacher"], learner, duration=2.0)
    make_attendance(db_session, roster["teacher"], learner, is_present=False)

    assert learner.hours_learned == pytest.approx(3.5)


def test_learned_hours_follow_an_edit(db_session, roster):
    """Computed live, so no stored total can drift."""

    learner = make_learner(db_session, roster["school"], roster["teacher"])
    record = make_attendance(db_session, roster["teacher"], learner, duration=2.0)

    record.duration = 5.0
    db_session.commit()

    assert learner.hours_learned == pytest.approx(5.0)


def test_a_learner_with_no_attendance_has_no_hours(db_session, roster):
    learner = make_learner(db_session, roster["school"], roster["teacher"])

    assert learner.hours_learned == 0.0


def test_volunteered_hours_use_the_volunteers_own_records(db_session, roster):
    volunteer = make_volunteer(db_session, roster["school"], roster["teacher"])
    make_attendance(db_session, roster["teacher"], volunteer, duration=2.5)

    assert volunteer.hours_volunteered == pytest.approx(2.5)


# ── programme hours ──────────────────────────────────────────────────────────


def test_programme_hours_do_not_double_count_a_matched_pair(db_session, roster):
    """A pair holds one row each for the same hour; summing the table reads 2x."""

    from models import Attendance

    teacher = roster["teacher"]
    learner = make_learner(db_session, roster["school"], teacher)
    volunteer = make_volunteer(db_session, roster["school"], teacher)
    _match(db_session, learner, volunteer)
    make_attendance(db_session, teacher, learner, partner=volunteer, duration=2.0)
    make_attendance(db_session, teacher, volunteer, partner=learner, duration=2.0)

    assert Attendance.programme_hours() == pytest.approx(2.0)


def test_programme_hours_equal_the_sum_of_every_learners_hours(db_session, roster):
    from models import Attendance

    teacher = roster["teacher"]
    learners = [make_learner(db_session, roster["school"], teacher) for _ in range(3)]
    for index, learner in enumerate(learners, start=1):
        make_attendance(db_session, teacher, learner, duration=float(index))

    assert Attendance.programme_hours() == pytest.approx(
        sum(learner.hours_learned for learner in learners)
    )


def test_programme_hours_can_be_narrowed_to_some_learners(db_session, roster):
    from models import Attendance

    teacher = roster["teacher"]
    mine = make_learner(db_session, roster["school"], teacher)
    theirs = make_learner(db_session, roster["school"], teacher)
    make_attendance(db_session, teacher, mine, duration=1.0)
    make_attendance(db_session, teacher, theirs, duration=4.0)

    assert Attendance.programme_hours([mine.id]) == pytest.approx(1.0)


def test_narrowing_to_no_learners_is_zero_not_everything(db_session, roster):
    """An empty list must not fall through to the unfiltered total."""

    from models import Attendance

    make_attendance(
        db_session, roster["teacher"],
        make_learner(db_session, roster["school"], roster["teacher"]),
        duration=9.0,
    )

    assert Attendance.programme_hours([]) == 0.0


def test_an_absence_never_contributes_hours(db_session, roster):
    from models import Attendance

    learner = make_learner(db_session, roster["school"], roster["teacher"])
    make_attendance(db_session, roster["teacher"], learner, is_present=False, duration=3.0)

    assert Attendance.programme_hours() == 0.0
    assert learner.hours_learned == 0.0


# ── learning content ─────────────────────────────────────────────────────────


def test_a_lesson_is_gamified_only_when_it_names_a_game(db_session):
    from models import Lesson

    _s, _t, plain, _q = make_learning_content(db_session)
    _s2, _topic, _l, _q2 = make_learning_content(db_session, game_type="rocket")
    game_lesson = db_session.scalars(select(Lesson).filter_by(game_type="rocket")).one()

    assert plain.is_gamified is False
    assert game_lesson.is_gamified is True


def test_deleting_a_topic_removes_its_lessons_and_questions(db_session):
    from models import Lesson, Question, Topic

    _subject, topic, _lesson, _question = make_learning_content(db_session)

    db_session.delete(db_session.get(Topic, topic.id))
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Lesson)) == 0
    assert db_session.scalar(select(func.count()).select_from(Question)) == 0


def test_deleting_a_subject_removes_its_whole_tree(db_session):
    from models import Lesson, Question, Subject, Topic

    subject, _topic, _lesson, _question = make_learning_content(db_session)

    db_session.delete(db_session.get(Subject, subject.id))
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Topic)) == 0
    assert db_session.scalar(select(func.count()).select_from(Lesson)) == 0
    assert db_session.scalar(select(func.count()).select_from(Question)) == 0


def test_deleting_a_conversation_removes_its_messages(db_session, roster):
    from models import AssistantConversation, AssistantMessage
    from tests.support.factories import (
        make_assistant_conversation,
        make_assistant_message,
    )

    conversation = make_assistant_conversation(db_session, roster["teacher"])
    make_assistant_message(db_session, conversation)

    db_session.delete(db_session.get(AssistantConversation, conversation.id))
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(AssistantMessage)) == 0
