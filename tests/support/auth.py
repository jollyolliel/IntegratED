"""Authentication helpers and role-specific fixtures."""

from __future__ import annotations

import pytest


def login_as(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return user


@pytest.fixture
def client(app, db_session):
    """A test client over a freshly emptied database.

    The `db_session` dependency is deliberate: without it a `client`-only test
    runs against whatever rows the previous test committed, which makes the
    suite quietly order-dependent.
    """

    return app.test_client()


@pytest.fixture
def school(db_session):
    from .factories import make_school

    return make_school(db_session)


@pytest.fixture
def learner(db_session, school):
    from .factories import make_learner

    return make_learner(db_session, school)


@pytest.fixture
def teacher(db_session, school):
    from .factories import make_teacher

    return make_teacher(db_session, school)


@pytest.fixture
def volunteer(db_session, school, teacher):
    from .factories import make_volunteer

    return make_volunteer(db_session, school, teacher)


@pytest.fixture
def admin(db_session):
    from .factories import make_admin

    return make_admin(db_session)


@pytest.fixture
def school_admin(db_session, school):
    from .factories import make_school_admin

    return make_school_admin(db_session, school)


@pytest.fixture
def authenticated_learner(client, learner):
    return login_as(client, learner)


@pytest.fixture
def authenticated_teacher(client, teacher):
    return login_as(client, teacher)


@pytest.fixture
def pair(db_session, authenticated_teacher):
    """A matched learner/volunteer belonging to the signed-in teacher."""

    from tests.support.factories import make_learner, make_volunteer

    teacher = authenticated_teacher
    school = teacher.school
    learner = make_learner(db_session, school, teacher, name="Ada")
    volunteer = make_volunteer(db_session, school, teacher, name="Bo")
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()
    return {"teacher": teacher, "school": school, "learner": learner, "volunteer": volunteer}


@pytest.fixture
def authenticated_volunteer(client, volunteer):
    return login_as(client, volunteer)


@pytest.fixture
def authenticated_admin(client, admin):
    return login_as(client, admin)


@pytest.fixture
def authenticated_school_admin(client, school_admin):
    return login_as(client, school_admin)
