"""Dev-only stand-in for Google at `/dev/google-sign-in` (issue #173): type an email and it signs in
through the same account logic as the real `/authorize` callback. The guards matter most, since
the page lets anyone sign in as any email; the rest checks the page reaches the real logic."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select

from helpers.auth_utils import get_or_create_invite_code
from models import Teacher, Volunteer
from tests.support.app import use_environment
from tests.support.assertions import assert_redirects_to
from tests.support.factories import make_school, make_teacher

pytestmark = pytest.mark.web

PAGE = "/dev/google-sign-in"
REMOTE = {"REMOTE_ADDR": "203.0.113.7"}


def _session_user_id(client):
    with client.session_transaction() as session:
        return session.get("_user_id")


# ── guards ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_page_is_hidden_when_deployed(app, client, db_session, monkeypatch, method):
    make_teacher(db_session, make_school(db_session), email="t@staff.example.com")
    use_environment(app, monkeypatch, "production")

    response = getattr(client, method)(PAGE, data={"email": "t@staff.example.com"})

    assert response.status_code == 404
    assert _session_user_id(client) is None


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_page_is_hidden_from_non_loopback_clients(client, db_session, method):
    make_teacher(db_session, make_school(db_session), email="t@staff.example.com")

    response = getattr(client, method)(PAGE, data={"email": "t@staff.example.com"}, environ_base=REMOTE)

    assert response.status_code == 404
    assert _session_user_id(client) is None


def test_the_google_button_opens_the_dev_page_on_a_local_dev_server(client, db_session):
    assert_redirects_to(client.get("/login/google"), PAGE)


def test_the_google_button_still_goes_to_google_when_deployed(app, client, db_session, monkeypatch):
    use_environment(app, monkeypatch, "production")

    response = client.get("/login/google")

    assert response.status_code in {301, 302, 303}
    assert response.headers["Location"].startswith("https://accounts.google.com/")


def test_the_google_button_goes_to_google_for_a_non_loopback_client(client, db_session):
    response = client.get("/login/google", environ_base=REMOTE)

    assert response.headers["Location"].startswith("https://accounts.google.com/")


def test_real_google_is_reachable_from_a_local_dev_server(client, db_session):
    response = client.get("/login/google?real=1")

    assert response.headers["Location"].startswith("https://accounts.google.com/")


def test_real_google_without_credentials_returns_to_the_dev_page(app, client, db_session, monkeypatch):
    use_environment(app, monkeypatch, "development", google_client_id="", google_client_secret="")

    response = client.get("/login/google?real=1")

    assert_redirects_to(response, PAGE)
    with client.session_transaction() as session:
        assert any("Google credentials" in message for _, message in session["_flashes"])


def test_the_callback_is_a_404_without_google_credentials(app, client, db_session, monkeypatch):
    use_environment(app, monkeypatch, "development", google_client_id="", google_client_secret="")

    assert client.get("/authorize").status_code == 404


def test_the_page_offers_real_google_only_when_credentials_are_set(app, client, db_session, monkeypatch):
    assert 'href="/login/google?real=1"' in client.get(PAGE).get_data(as_text=True)

    use_environment(app, monkeypatch, "development", google_client_id="", google_client_secret="")

    assert "real=1" not in client.get(PAGE).get_data(as_text=True)


# ── the page ─────────────────────────────────────────────────────────────────


def test_the_page_has_an_email_field_and_posts_to_itself(client, db_session):
    response = client.get(PAGE)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="email"' in html and 'type="email"' in html
    assert 'name="name"' in html
    assert f'action="{PAGE}"' in html


def test_an_existing_teacher_signs_in_by_email(client, db_session):
    teacher = make_teacher(db_session, make_school(db_session), email="t@staff.example.com")

    response = client.post(PAGE, data={"email": "t@staff.example.com"})

    assert_redirects_to(response, "/teacher/")
    assert _session_user_id(client) == str(teacher.id)


def test_an_unknown_gmail_address_becomes_an_unaffiliated_teacher(client, db_session):
    response = client.post(PAGE, data={"email": "someone@gmail.com", "name": "Sam Dev"})

    assert_redirects_to(response, "/teacher/")
    created = db_session.scalars(select(Teacher).filter_by(email="someone@gmail.com")).one()
    assert created.school_id is None
    assert created.name == "Sam Dev"
    assert created.google_sub == "dev-someone@gmail.com"
    assert _session_user_id(client) == str(created.id)


def test_a_blank_name_falls_back_to_the_email(client, db_session):
    client.post(PAGE, data={"email": "someone@gmail.com", "name": "  "})

    assert db_session.scalars(select(Teacher).filter_by(email="someone@gmail.com")).one().name == "someone"


def test_an_unauthorised_domain_is_refused_as_with_google(client, db_session):
    response = client.post(PAGE, data={"email": "stranger@unknown.example"})

    assert_redirects_to(response, "/login")
    assert db_session.scalar(select(func.count()).select_from(Teacher)) == 0
    assert _session_user_id(client) is None


def test_a_blank_email_is_refused_as_with_google(client, db_session):
    assert_redirects_to(client.post(PAGE, data={"email": "  "}), "/login")
    assert _session_user_id(client) is None


def test_the_volunteer_wizard_works_end_to_end(client, db_session):
    """`/start-volunteer-register` stashes the invite and sends the browser to Google; the dev page
    must keep the stashed code so the new volunteer is created in the inviting school."""

    school = make_school(db_session, volunteer_domain="students.example.com")
    code = get_or_create_invite_code(school)

    started = client.post("/start-volunteer-register", data={"invite_code": code})
    assert_redirects_to(started, "/login/google")
    assert_redirects_to(client.get("/login/google"), PAGE)
    response = client.post(PAGE, data={"email": "new.volunteer@students.example.com"})

    assert_redirects_to(response, "/volunteer/survey")
    created = db_session.scalars(select(Volunteer).filter_by(email="new.volunteer@students.example.com")).one()
    assert created.school_id == school.id


# ── presets ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("preset", ["teacher", "volunteer"])
def test_the_page_offers_a_button_for_each_preset(client, db_session, preset):
    html = client.get(PAGE).get_data(as_text=True)

    assert re.search(rf'<button[^>]*name="preset"[^>]*value="{preset}"', html)


def test_the_teacher_preset_registers_a_new_teacher_at_a_school_by_its_domain(client, db_session):
    school = make_school(db_session, teacher_domain="staff.example.com")

    response = client.post(PAGE, data={"preset": "teacher"})

    assert_redirects_to(response, "/teacher/")
    created = db_session.scalars(select(Teacher)).one()
    assert created.email.endswith("@staff.example.com")
    assert created.name.strip()
    assert created.school_id == school.id
    assert _session_user_id(client) == str(created.id)


def test_the_teacher_preset_falls_back_to_an_unaffiliated_gmail_teacher(client, db_session):
    make_school(db_session)

    response = client.post(PAGE, data={"preset": "teacher"})

    assert_redirects_to(response, "/teacher/")
    created = db_session.scalars(select(Teacher)).one()
    assert created.email.endswith("@gmail.com")
    assert created.school_id is None


def test_the_volunteer_preset_registers_a_new_volunteer_in_a_school_with_its_invite(client, db_session):
    school = make_school(db_session, volunteer_domain="students.example.com")

    response = client.post(PAGE, data={"preset": "volunteer"})

    assert_redirects_to(response, "/volunteer/survey")
    created = db_session.scalars(select(Volunteer)).one()
    assert created.email.endswith("@students.example.com")
    assert created.name.strip()
    assert created.school_id == school.id
    assert _session_user_id(client) == str(created.id)


def test_the_volunteer_preset_explains_when_no_school_takes_volunteers(client, db_session):
    make_school(db_session)

    response = client.post(PAGE, data={"preset": "volunteer"})

    assert_redirects_to(response, PAGE)
    assert db_session.scalar(select(func.count()).select_from(Volunteer)) == 0
    assert _session_user_id(client) is None


def test_a_refused_preset_leaves_no_invite_code_or_email_in_the_session(client, db_session):
    make_school(db_session, volunteer_domain="students.example.com")
    client.post(PAGE, data={"email": "stranger@unknown.example"})
    with client.session_transaction() as session:
        session["pending_invite_code"] = "stale"

    client.post(PAGE, data={"preset": "volunteer"})

    with client.session_transaction() as session:
        assert "pending_invite_code" not in session
    client.post(PAGE, data={"email": "stranger@unknown.example"})
    with client.session_transaction() as session:
        assert "user_email" not in session


def test_a_preset_for_an_existing_user_leaves_no_invite_code(client, db_session):
    school = make_school(db_session, volunteer_domain="students.example.com")
    with client.session_transaction() as session:
        session["pending_invite_code"] = get_or_create_invite_code(school)

    client.post(PAGE, data={"preset": "volunteer"})
    with client.session_transaction() as session:
        assert "pending_invite_code" not in session


def test_each_preset_click_makes_a_different_account(client, db_session):
    make_school(db_session, teacher_domain="staff.example.com")

    client.post(PAGE, data={"preset": "teacher"})
    client.post(PAGE, data={"preset": "teacher"})

    emails = db_session.scalars(select(Teacher.email)).all()
    assert len(emails) == 2 and len(set(emails)) == 2


def test_an_unknown_preset_is_ignored_and_the_typed_email_is_used(client, db_session):
    client.post(PAGE, data={"preset": "nonsense", "email": "someone@gmail.com"})

    assert db_session.scalars(select(Teacher)).one().email == "someone@gmail.com"


@pytest.mark.parametrize("preset", ["teacher", "volunteer"])
def test_a_preset_is_hidden_when_deployed(app, client, db_session, monkeypatch, preset):
    make_school(db_session, teacher_domain="staff.example.com", volunteer_domain="students.example.com")
    use_environment(app, monkeypatch, "production")

    assert client.post(PAGE, data={"preset": preset}).status_code == 404
    assert _session_user_id(client) is None
