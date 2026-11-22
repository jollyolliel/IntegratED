"""Present-hours is read once per person on every roster page, so it must not
cost one aggregate query per person."""

import pytest
from sqlalchemy import event

pytestmark = pytest.mark.web


def _count_hours_queries(fn):
    from extensions import db

    seen = []

    @event.listens_for(db.engine, "before_cursor_execute")
    def before(conn, cursor, statement, params, context, executemany):
        if "sum(attendance.duration)" in statement.lower():
            seen.append(statement)

    try:
        result = fn()
    finally:
        event.remove(db.engine, "before_cursor_execute", before)
    return result, len(seen)


def test_roster_hours_cost_one_query_for_the_whole_page(app, db_session, school):
    from tests.support.factories import (
        make_attendance,
        make_learner,
        make_teacher,
        make_volunteer,
    )

    teacher = make_teacher(db_session, school)
    volunteer = make_volunteer(db_session, school, teacher, match_capacity=6)
    learners = [
        make_learner(db_session, school, teacher, name=f"L{i}", volunteer_id=volunteer.id)
        for i in range(6)
    ]
    for learner in learners[:3]:
        make_attendance(db_session, teacher, learner, partner=volunteer, duration=2.0)
    # The volunteer's own hours come from rows where they are the subject, not
    # the partner — see ADR 0001 on the two sides being recorded separately.
    make_attendance(db_session, teacher, volunteer, duration=6.0)
    db_session.commit()

    with app.test_request_context("/teacher/people"):
        hours, queries = _count_hours_queries(
            lambda: [l.hours_learned for l in learners] + [volunteer.hours_volunteered]
        )

    assert hours[:6] == [2.0, 2.0, 2.0, 0.0, 0.0, 0.0]
    assert hours[6] == 6.0
    assert queries == 1, f"expected one grouped query, got {queries}"


def test_hours_reflect_attendance_written_in_the_same_request(app, db_session, school):
    from tests.support.factories import make_attendance, make_learner, make_teacher

    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    db_session.commit()

    with app.test_request_context("/teacher/"):
        assert learner.hours_learned == 0.0
        make_attendance(db_session, teacher, learner, duration=3.0)
        db_session.commit()
        assert learner.hours_learned == 3.0


def test_hours_work_outside_a_request(app, db_session, school):
    from tests.support.factories import make_attendance, make_learner, make_teacher

    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    make_attendance(db_session, teacher, learner, duration=1.5)
    db_session.commit()

    assert learner.hours_learned == 1.5
