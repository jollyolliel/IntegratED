"""`scripts/flood.py`: bulk dev data for load-testing admin and teacher tables. Dev only, school-agnostic."""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import func, select

from helpers import flood as helpers_flood
from scripts import flood
from tests.support.app import use_environment

pytestmark = pytest.mark.integration

QUIET: dict[str, Any] = {"worksheets": 0, "assignments": 0, "donations": 0, "articles": 0}


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_it_refuses_outside_development(app, db_session, school, teacher, monkeypatch):
    from models import Learner

    use_environment(app, monkeypatch, "production")

    lines = flood.flood_database(learners=3, volunteers=0, **QUIET)

    assert "development" in lines[0].lower()
    assert _count(db_session, Learner) == 0


def test_it_refuses_on_a_non_sqlite_database(app, db_session, school, teacher, monkeypatch):
    from models import Learner

    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", "postgresql://user:pw@host/db")

    lines = flood.flood_database(learners=3, volunteers=0, **QUIET)

    assert "Refusing" in lines[0]
    assert _count(db_session, Learner) == 0


def test_it_reports_when_there_are_no_schools(app, db_session):
    assert "No schools" in flood.flood_database(learners=1, volunteers=1, **QUIET)[0]


def test_it_reports_when_there_are_no_teachers_and_none_are_asked_for(app, db_session, school):
    assert "No teachers" in flood.flood_database(learners=1, volunteers=1, **QUIET)[0]


def test_it_adds_learners_and_volunteers_to_existing_teachers(app, db_session, school, teacher):
    from models import Administrator, Learner, Teacher, Volunteer

    flood.flood_database(learners=10, volunteers=6, **QUIET)

    assert _count(db_session, Learner) == 10
    assert _count(db_session, Volunteer) == 6
    assert _count(db_session, Teacher) == 1
    assert _count(db_session, Administrator) == 0
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(is_matched=True)) > 0


def test_teachers_can_be_created_too(app, db_session, school):
    from models import Teacher

    flood.flood_database(learners=2, volunteers=0, teachers=3, **QUIET)

    assert _count(db_session, Teacher) == 3


def test_volunteers_never_exceed_their_capacity(app, db_session, school, teacher):
    from models import Volunteer

    flood.flood_database(learners=20, volunteers=5, **QUIET)

    for volunteer in db_session.scalars(select(Volunteer)).all():
        assert len(volunteer.learner_matches) <= volunteer.capacity


def test_worksheets_assignments_attendance_and_donations_are_created(app, db_session, school, teacher):
    from models import Attendance, Donation, Worksheet, WorksheetAssignment

    flood.flood_database(
        learners=8, volunteers=4, worksheets=5, assignments=15, donations=6, articles=0, attendance_weeks=3
    )

    assert _count(db_session, Worksheet) == 5
    assert _count(db_session, WorksheetAssignment) == 15
    assert _count(db_session, Donation) == 6
    attendance = _count(db_session, Attendance)
    assert attendance > 0 and attendance % 2 == 0


def test_assignments_only_target_new_learners(app, db_session, school, teacher):
    from models import WorksheetAssignment
    from tests.support.factories import make_learner, make_worksheet

    untouched = make_learner(db_session, school, teacher, username="untouched")
    make_worksheet(db_session)

    flood.flood_database(learners=5, volunteers=2, worksheets=2, assignments=10, donations=0, articles=0)

    assert untouched.id not in {a.learner_id for a in db_session.scalars(select(WorksheetAssignment)).all()}


def test_it_can_run_twice_without_colliding(app, db_session, school, teacher):
    from models import Learner

    flood.flood_database(learners=5, volunteers=3, **QUIET)
    flood.flood_database(learners=5, volunteers=3, **QUIET)

    assert _count(db_session, Learner) == 10


def test_the_same_seed_gives_the_same_people(app, db_session, school, teacher):
    from models import Learner

    flood.flood_database(learners=6, volunteers=0, seed=7, **QUIET)
    first = sorted(db_session.scalars(select(Learner.username)).all())
    for learner in db_session.scalars(select(Learner)).all():
        db_session.delete(learner)
    db_session.commit()

    flood.flood_database(learners=6, volunteers=0, seed=7, **QUIET)

    assert sorted(db_session.scalars(select(Learner.username)).all()) == first


def test_volunteer_emails_use_their_schools_own_domain(app, db_session, teacher):
    from models import Volunteer

    teacher.school.volunteer_domain = "stu.example.test"
    db_session.commit()

    flood.flood_database(learners=0, volunteers=4, **QUIET)

    emails = db_session.scalars(select(Volunteer.email)).all()
    assert emails and all(email.endswith("@stu.example.test") for email in emails)


def test_a_school_without_a_domain_falls_back_to_example_test(app, db_session, teacher):
    from models import Volunteer

    teacher.school.volunteer_domain = None
    db_session.commit()

    flood.flood_database(learners=0, volunteers=2, **QUIET)

    assert all(email.endswith("@example.test") for email in db_session.scalars(select(Volunteer.email)).all())


def test_only_the_named_schools_are_flooded(app, db_session, school, teacher):
    from models import Learner
    from tests.support.factories import make_school, make_teacher

    other = make_school(db_session, name="Other School")
    make_teacher(db_session, other)

    flood.flood_database(learners=10, volunteers=0, school_names=["Other School"], **QUIET)

    assert {learner.school_id for learner in db_session.scalars(select(Learner)).all()} == {other.id}


def test_an_unknown_school_name_is_reported(app, db_session, school, teacher):
    assert "Nowhere" in flood.flood_database(learners=1, volunteers=0, school_names=["Nowhere"], **QUIET)[0]


def test_a_chosen_password_works_for_a_flooded_learner(app, db_session, school, teacher):
    from models import Learner

    lines = flood.flood_database(learners=2, volunteers=0, password="chosen-pass", **QUIET)

    assert all(learner.check_password("chosen-pass") for learner in db_session.scalars(select(Learner)).all())
    assert any("chosen-pass" in line for line in lines)


def test_a_random_password_is_reported_when_none_is_given(app, db_session, school, teacher):
    from models import Learner

    lines = flood.flood_database(learners=1, volunteers=0, **QUIET)

    learner = db_session.scalars(select(Learner)).first()
    match = re.search(r"password '([^']+)'", next(line for line in lines if line.startswith("Login")))
    assert match is not None
    password = match.group(1)
    assert learner.check_password(password)


def test_a_dry_run_saves_nothing(app, db_session, school, teacher):
    from models import Learner

    lines = flood.flood_database(learners=4, volunteers=2, dry_run=True, **QUIET)

    assert _count(db_session, Learner) == 0
    assert any("dry run" in line.lower() for line in lines)


def test_no_school_names_are_baked_into_the_script():
    import inspect

    source = (inspect.getsource(flood) + inspect.getsource(helpers_flood)).lower()
    assert "acs" not in source and "home project" not in source
