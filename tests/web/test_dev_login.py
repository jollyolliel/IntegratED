"""Dev-only `/dev/login-as`. Only the security guards are covered: a passwordless login leaking
into prod is the one failure here that matters, and CI is the only thing that would catch it.
The happy-path test is the control that keeps the 404 tests from passing on a broken route."""

from __future__ import annotations

import pytest

from tests.support.app import use_environment
from tests.support.factories import make_learner, make_school, make_teacher

pytestmark = pytest.mark.web


def _session_user_id(client):
    with client.session_transaction() as session:
        return session.get("_user_id")


def test_login_by_id_signs_in_and_lands_on_the_role_dashboard(client, db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)

    response = client.get(f"/dev/login-as?id={teacher.id}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/teacher/")
    assert _session_user_id(client) == str(teacher.id)


@pytest.mark.parametrize(
    "next_path", ["//evil.example", "/\\evil.example", "https://evil.example", "/\t/evil.example"]
)
def test_next_never_redirects_off_site(client, db_session, next_path):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)

    response = client.get("/dev/login-as", query_string={"id": teacher.id, "next": next_path})

    assert response.headers["Location"].endswith("/teacher/")


@pytest.mark.parametrize(
    ("query", "completed", "deferred"),
    [
        ({"map_test": "0"}, False, False),
        ({"map_test": "deferred"}, True, True),
        ({"map_test": "1"}, True, False),
    ],
)
def test_map_test_state_can_be_set(client, db_session, query, completed, deferred):
    learner = make_learner(db_session, make_school(db_session))
    learner.completed_map_test, learner.map_test_deferred = True, True
    learner.subject_levels = {"math": 2}
    db_session.commit()

    client.get("/dev/login-as", query_string={"id": learner.id, **query})

    db_session.refresh(learner)
    assert learner.completed_map_test is completed
    assert learner.map_test_deferred is deferred
    if query["map_test"] != "1":
        assert learner.subject_levels == {}


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("1", True)])
def test_survey_state_can_be_set(client, db_session, value, expected):
    learner = make_learner(db_session, make_school(db_session))
    learner.completed_survey = not expected
    db_session.commit()

    client.get("/dev/login-as", query_string={"id": learner.id, "survey": value})

    db_session.refresh(learner)
    assert learner.completed_survey is expected


def test_state_params_leave_state_alone_when_absent(client, db_session):
    learner = make_learner(db_session, make_school(db_session))
    learner.completed_survey, learner.completed_map_test = False, False
    db_session.commit()

    client.get(f"/dev/login-as?id={learner.id}")

    db_session.refresh(learner)
    assert learner.completed_survey is False
    assert learner.completed_map_test is False


def test_bad_state_value_is_a_400(client, db_session):
    learner = make_learner(db_session, make_school(db_session))

    response = client.get("/dev/login-as", query_string={"id": learner.id, "map_test": "maybe"})

    assert response.status_code == 400


def test_the_route_is_hidden_when_deployed(app, client, db_session, monkeypatch):
    learner = make_learner(db_session, make_school(db_session))
    use_environment(app, monkeypatch, "production")

    response = client.get(f"/dev/login-as?id={learner.id}")

    assert response.status_code == 404
    assert _session_user_id(client) is None


def test_the_route_is_hidden_from_non_loopback_clients(client, db_session):
    learner = make_learner(db_session, make_school(db_session))

    response = client.get(
        f"/dev/login-as?id={learner.id}", environ_base={"REMOTE_ADDR": "203.0.113.7"}
    )

    assert response.status_code == 404
    assert _session_user_id(client) is None
