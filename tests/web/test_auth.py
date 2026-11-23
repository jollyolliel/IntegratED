"""Sign-in, registration, invite codes, and the Google OAuth account link.

`/authorize` is the largest untested block in the app. Nothing here contacts
Google: `routes.auth._oauth._google` is replaced with a client whose `authorize_access_token`
returns whatever token payload the test wants.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from helpers.auth_utils import get_or_create_invite_code, regenerate_invite_code
from models import Learner, Teacher, Volunteer
from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.factories import (
    make_admin,
    make_school,
    make_school_admin,
    make_teacher,
    make_volunteer,
)
from tests.support.html import parse

pytestmark = pytest.mark.web


# ── password sign-in ─────────────────────────────────────────────────────────


def test_login_page_renders(client, db_session):
    assert client.get("/login").status_code == 200


def test_login_page_has_its_heading_form_and_google_link(client, db_session):
    body = assert_success(client.get("/login")).get_data(as_text=True)

    for marker in [
        "Sign in to IntegratED", 'action="/login"', 'method="POST"', 'name="username"', 'name="password"',
        'autocomplete="current-password"', 'type="submit"', 'href="/login/google"', "Sign in with Google",
        'href="/register"',
    ]:
        assert marker in body


def test_login_redirects_a_valid_learner_to_the_survey(client, db_session, learner):
    response = client.post(
        "/login", data={"username": "learner", "password": "Password1!"}
    )

    assert_redirects_to(response, "/learner/")


# Leading and trailing whitespace is never part of a username or password (issue #176): a
# password pasted with a trailing space, or a username typed after a space, still signs in.
@pytest.mark.parametrize(
    ("username", "password"),
    [("learner", "Password1! "), ("learner", " Password1!"), ("learner", "\tPassword1!\n"),
     (" learner ", "Password1!"), ("learner", "Password1!\u00a0")],
)
def test_login_ignores_whitespace_around_the_credentials(client, db_session, learner, username, password):
    response = client.post("/login", data={"username": username, "password": password})

    assert_redirects_to(response, "/learner/")


def test_a_space_inside_a_password_is_part_of_it(client, db_session, learner):
    learner.set_password("Pass word1")
    db_session.commit()

    assert_redirects_to(client.post("/login", data={"username": "learner", "password": "Pass word1"}), "/learner/")
    assert_redirects_to(client.post("/login", data={"username": "learner", "password": "Password1"}), "/login")


def test_a_password_saved_with_a_trailing_space_before_trimming_still_signs_in(client, db_session, learner):
    # Register and settings once stored passwords exactly as typed, spaces included.
    learner.set_password("Legacy1! ")
    db_session.commit()

    response = client.post("/login", data={"username": "learner", "password": "Legacy1! "})

    assert_redirects_to(response, "/learner/")


def test_login_with_only_whitespace_is_refused(client, db_session, learner):
    response = client.post("/login", data={"username": "learner", "password": "   "})

    assert_redirects_to(response, "/login")
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_the_login_password_field_has_a_show_password_toggle(client, db_session):
    page = parse(assert_success(client.get("/login")).get_data(as_text=True))
    toggle = page.find("button", "password-toggle")

    assert toggle.attrs["aria-controls"] == "password"
    assert toggle.attrs["aria-pressed"] == "false"
    assert toggle.attrs["aria-label"] == "Show password"


def test_login_rejects_invalid_credentials(client, db_session, learner):
    response = client.post(
        "/login", data={"username": "learner", "password": "wrong"}
    )

    assert_redirects_to(response, "/login")


def test_login_rejects_an_unknown_username(client, db_session):
    response = client.post(
        "/login", data={"username": "ghost", "password": "Password1!"}
    )

    assert_redirects_to(response, "/login")
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_an_administrator_lands_on_the_admin_dashboard(client, db_session):
    make_admin(db_session, username="root", password="Password1!")

    response = client.post("/login", data={"username": "root", "password": "Password1!"})

    assert_redirects_to(response, "/admin/dashboard")


def test_a_school_admin_lands_on_the_school_dashboard(client, db_session):
    school = make_school(db_session)
    make_school_admin(db_session, school, username="head", password="Password1!")

    response = client.post("/login", data={"username": "head", "password": "Password1!"})

    assert_redirects_to(response, "/school/")


@pytest.mark.parametrize("model", [Teacher, Volunteer])
def test_google_sign_in_roles_hold_no_username_or_password(model):
    """Teachers and volunteers authenticate through Google only (issue #177)."""
    columns = model.__table__.columns

    assert "username" not in columns
    assert "password_hash" not in columns
    assert not hasattr(model, "set_password")
    assert not hasattr(model, "check_password")


@pytest.mark.parametrize("make", [make_teacher, make_volunteer])
def test_the_password_form_refuses_a_google_sign_in_role(client, db_session, make):
    account = make(db_session, make_school(db_session))

    response = client.post("/login", data={"username": account.email, "password": "Password1!"})

    assert_redirects_to(response, "/login")
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_logout_clears_the_authenticated_session(client, authenticated_learner):
    response = client.get("/logout")

    assert_redirects_to(response, "/")
    assert client.get("/learner/").status_code in {302, 303}


@pytest.mark.parametrize("path", ["/learner/", "/teacher/", "/volunteer/", "/admin/dashboard"])
def test_role_pages_redirect_anonymous_visitors_to_login(client, db_session, path):
    response = client.get(path)

    assert response.status_code in {301, 302, 303}
    assert "/login" in response.headers["Location"]


# ── password strength ────────────────────────────────────────────────────────


@pytest.mark.parametrize("password", ["StrongPass", "aB123456", "LongEnough1"])
def test_a_strong_password_is_accepted(app, password):
    from routes.auth import is_password_strong

    assert is_password_strong(password) is True


@pytest.mark.parametrize("password", ["short", "alllowercase", "ALLUPPERCASE", "Ab1", "", 12345678])
def test_a_weak_password_is_rejected(app, password):
    from routes.auth import is_password_strong

    assert is_password_strong(password) is False


# ── registration ─────────────────────────────────────────────────────────────


def test_the_registration_page_renders(client, db_session):
    assert_success(client.get("/register"))


def test_the_registration_page_has_every_step_and_field(client, db_session):
    body = assert_success(client.get("/register")).get_data(as_text=True)

    for marker in [
        "Enter your invite code", "Learner Registration", "Volunteer Registration", "Sign up with Google",
        'id="signup-steps"', 'id="invite_code"', 'class="code-input"',
        'id="code-btn"', 'id="codeError"', 'id="step-code"', 'id="step-role"', 'id="step-learner"',
        'id="step-volunteer"', 'name="user_type"', 'value="learner"', 'value="volunteer"', 'id="registerForm"',
        'name="username"', 'name="password"', 'name="confirm_password"', 'id="register-btn"', 'id="formError"',
        'action="/start-volunteer-register"', 'name="invite_code"', 'id="volunteer_invite_code"',
        'onclick="verifyCode()"', 'onclick="handleRole()"', 'onclick="goToRole()"', 'onclick="goToCode()"',
        '"/validate-invite"', 'href="/login"',
    ]:
        assert marker in body


def test_the_registration_page_is_the_account_step_of_the_sign_up_journey(client, db_session):
    body = assert_success(client.get("/register")).get_data(as_text=True)
    current = parse(body).find("li", "step-current")

    assert current.find("span", "step-name").all_text == "Account"
    assert 'aria-label="Step 1 of 3"' in body


def test_the_registration_page_carries_a_hidden_two_step_journey_for_volunteers(client, db_session):
    # A volunteer has no placement quiz; the page swaps indicators rather than editing one.
    page = parse(assert_success(client.get("/register")).get_data(as_text=True))
    indicators = {ol.attrs["id"]: ol for ol in page.find_all("ol", "step-indicator")}

    learner_steps, volunteer_steps = indicators["signup-steps"], indicators["signup-steps-volunteer"]
    assert "hidden" not in learner_steps.attrs and len(learner_steps.find_all("li")) == 3
    assert "hidden" in volunteer_steps.attrs and len(volunteer_steps.find_all("li")) == 2
    assert volunteer_steps.attrs["aria-label"] == "Step 1 of 2"


def test_the_registration_password_fields_have_toggles_and_say_spaces_are_not_allowed(client, db_session):
    body = assert_success(client.get("/register")).get_data(as_text=True)
    controls = [b.attrs.get("aria-controls") for b in parse(body).find_all("button", "password-toggle")]

    assert controls == ["password", "confirm_password"]
    assert "No spaces allowed." in body


def test_register_trims_whitespace_around_the_username_and_password(client, db_session, school):
    code = get_or_create_invite_code(school)

    response = client.post(
        "/register",
        json={"username": "  spaced  ", "password": " StrongPass ", "invite_code": code},
    )

    assert_redirects_to(response, "/learner/survey")
    created = db_session.scalars(select(Learner).filter_by(username="spaced")).one()
    assert created.check_password("StrongPass")


def test_register_counts_a_password_without_its_surrounding_spaces(client, db_session, school):
    # 7 characters plus a space is still too short.
    response = client.post(
        "/register",
        json={"username": "short", "password": "Strongp ", "invite_code": get_or_create_invite_code(school)},
    )

    assert response.status_code == 400
    assert db_session.scalars(select(Learner).filter_by(username="short")).first() is None


@pytest.mark.parametrize(
    ("username", "password"),
    [("two words", "StrongPass"), ("tab	name", "StrongPass"), ("nbsp name", "StrongPass"),
     ("nospace", "Strong Pass"), ("nospace", "Strong Pass")],
)
def test_register_refuses_a_space_inside_the_username_or_password(client, db_session, school, username, password):
    response = client.post(
        "/register",
        json={"username": username, "password": password, "invite_code": get_or_create_invite_code(school)},
    )

    assert response.status_code == 400
    assert "spaces" in response.get_json()["message"].lower()
    assert db_session.scalar(select(func.count()).select_from(Learner)) == 0


def test_register_refuses_a_blank_username(client, db_session, school):
    response = client.post(
        "/register",
        json={"username": "   ", "password": "StrongPass", "invite_code": get_or_create_invite_code(school)},
    )

    assert response.status_code == 400


def test_register_requires_json(client, db_session):
    response = client.post("/register", data={"username": "new"})

    assert response.status_code == 415


def test_register_creates_a_learner_with_a_valid_invite(client, db_session, school):
    code = get_or_create_invite_code(school)

    response = client.post(
        "/register",
        json={"username": "newlearner", "password": "StrongPass", "invite_code": code},
    )

    assert_redirects_to(response, "/learner/survey")
    assert db_session.scalars(select(Learner).filter_by(username="newlearner")).one().school_id == school.id


def test_register_signs_the_new_learner_in(client, db_session, school):
    code = get_or_create_invite_code(school)

    client.post(
        "/register",
        json={"username": "newlearner", "password": "StrongPass", "invite_code": code},
    )

    created = db_session.scalars(select(Learner).filter_by(username="newlearner")).one()
    with client.session_transaction() as session:
        assert session["_user_id"] == str(created.id)


def test_registering_ends_impersonation(client, db_session, school):
    code = get_or_create_invite_code(school)
    with client.session_transaction() as session:
        session["impersonating_admin_id"] = 7

    client.post("/register", json={"username": "newlearner", "password": "StrongPass", "invite_code": code})

    with client.session_transaction() as session:
        assert "impersonating_admin_id" not in session


def test_register_rejects_invalid_invite(client, db_session):
    response = client.post(
        "/register",
        json={"username": "newlearner", "password": "StrongPass", "invite_code": "bad"},
    )

    assert response.status_code == 400
    assert response.json["message"] == "Invalid invite code"


def test_register_rejects_an_empty_payload(client, db_session):
    response = client.post("/register", json={})

    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload", [{"password": "StrongPass"}, {"username": "someone"}]
)
def test_register_needs_both_a_username_and_a_password(client, db_session, school, payload):
    payload = {**payload, "invite_code": get_or_create_invite_code(school)}

    response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert "required" in response.json["message"]


def test_register_rejects_a_duplicate_username(client, db_session, school, learner):
    code = get_or_create_invite_code(school)

    response = client.post(
        "/register",
        json={"username": learner.username, "password": "StrongPass", "invite_code": code},
    )

    assert response.status_code == 400
    assert response.json["message"] == "User already exists"


def test_register_rejects_a_weak_password(client, db_session, school):
    code = get_or_create_invite_code(school)

    response = client.post(
        "/register",
        json={"username": "weakling", "password": "short", "invite_code": code},
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(username="weakling")) == 0


# ── invite codes ─────────────────────────────────────────────────────────────


def test_validate_invite_reports_the_school(client, db_session, school):
    code = get_or_create_invite_code(school)

    response = client.post("/validate-invite", json={"invite_code": code.lower()})

    assert response.json == {"valid": True, "school": school.name, "code": code}


def test_validate_invite_rejects_an_unknown_code(client, db_session):
    response = client.post("/validate-invite", json={"invite_code": "NOPE12"})

    assert response.json["valid"] is False


def test_an_invite_code_is_stored_and_survives_a_fresh_session(client, db_session, school):
    """The code lives on the school row, so a restart (a fresh session) reads the same one."""
    code = get_or_create_invite_code(school)

    db_session.expire_all()

    assert school.invite_code == code
    assert get_or_create_invite_code(school) == code
    assert client.post("/validate-invite", json={"invite_code": code}).json["valid"] is True


def test_regenerating_replaces_the_code_and_retires_the_old_one(client, db_session, school):
    first = get_or_create_invite_code(school)

    second = regenerate_invite_code(school)

    assert second != first
    assert get_or_create_invite_code(school) == second
    assert client.post("/validate-invite", json={"invite_code": first}).json["valid"] is False
    assert client.post("/validate-invite", json={"invite_code": second}).json["valid"] is True


def test_two_schools_cannot_share_an_invite_code(db_session, school):
    from sqlalchemy.exc import IntegrityError

    from models import School

    school.invite_code = "SAMECD"
    db_session.commit()
    db_session.add(School(name="Another School", invite_code="SAMECD"))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_regenerating_retries_when_the_code_is_already_taken(db_session, school, monkeypatch):
    from helpers import auth_utils
    from models import School

    db_session.add(School(name="Another School", invite_code="TAKEN1"))
    db_session.commit()
    candidates = iter(["TAKEN1", "FRESH2"])
    monkeypatch.setattr(auth_utils, "_random_code", lambda: next(candidates))

    assert regenerate_invite_code(school) == "FRESH2"
    assert school.invite_code == "FRESH2"


def test_a_code_collision_keeps_the_callers_other_changes(db_session, school, monkeypatch):
    """Drawing again after a collision undoes only that draw, not what the caller had pending."""
    from helpers import auth_utils
    from models import School

    db_session.add(School(name="Another School", invite_code="TAKEN1"))
    db_session.commit()
    candidates = iter(["TAKEN1", "FRESH2"])
    monkeypatch.setattr(auth_utils, "_random_code", lambda: next(candidates))
    school.name = "Renamed in the same request"

    regenerate_invite_code(school)
    db_session.expire_all()

    assert school.name == "Renamed in the same request"
    assert school.invite_code == "FRESH2"


def test_regenerating_gives_up_when_every_draw_collides(db_session, school, monkeypatch):
    from helpers import auth_utils
    from models import School

    db_session.add(School(name="Another School", invite_code="TAKEN1"))
    db_session.commit()
    monkeypatch.setattr(auth_utils, "_random_code", lambda: "TAKEN1")

    with pytest.raises(RuntimeError):
        regenerate_invite_code(school)


def test_a_live_code_is_returned_unchanged(client, db_session, school):
    assert get_or_create_invite_code(school) == get_or_create_invite_code(school)


def test_starting_volunteer_registration_stashes_the_invite(client, db_session, school):
    code = get_or_create_invite_code(school)

    client.post("/start-volunteer-register", data={"invite_code": code})

    with client.session_transaction() as session:
        assert session.get("pending_invite_code") == code


# ── Google OAuth ─────────────────────────────────────────────────────────────


@pytest.fixture
def google_token(monkeypatch):
    """Drive `/authorize` with whatever Google would have returned."""

    from routes.auth import _oauth

    holder = {"token": {}}

    class _FakeGoogle:
        def authorize_access_token(self):
            token = holder["token"]
            if isinstance(token, Exception):
                raise token
            return token

        def authorize_redirect(self, redirect_uri):
            from flask import redirect

            return redirect("https://accounts.google.test/o/oauth2/auth")

    fake = _FakeGoogle()
    monkeypatch.setattr(_oauth, "_google", lambda: fake)

    class _SetUser:
        def __call__(self, email=None, name="Sam Google", sub="sub-123"):
            info = {"name": name, "sub": sub, "picture": ""}
            if email is not None:
                info["email"] = email
            holder["token"] = {"userinfo": info}

        def fail(self, exc):
            holder["token"] = exc

    return _SetUser()


def test_a_failed_google_sign_in_keeps_an_impersonating_admin_able_to_return(client, db_session, google_token):
    google_token(email="stranger@unknown-school.test")
    with client.session_transaction() as session:
        session["impersonating_admin_id"] = 7

    assert_redirects_to(client.get("/authorize"), "/login")

    with client.session_transaction() as session:
        assert session.get("impersonating_admin_id") == 7


def test_a_successful_google_sign_in_ends_impersonation(client, db_session, google_token):
    google_token(email="someone@gmail.com")
    with client.session_transaction() as session:
        session["impersonating_admin_id"] = 7

    client.get("/authorize")

    with client.session_transaction() as session:
        assert "impersonating_admin_id" not in session


def test_a_token_without_an_email_is_refused(client, db_session, google_token):
    google_token(email=None)

    assert_redirects_to(client.get("/authorize"), "/login")


def test_a_gmail_address_becomes_an_unaffiliated_teacher(client, db_session, google_token):
    """The deliberate special case: a teacher with no school yet."""

    google_token(email="someone@gmail.com")

    response = client.get("/authorize")

    assert_redirects_to(response, "/teacher/")
    created = db_session.scalars(select(Teacher).filter_by(email="someone@gmail.com")).one()
    assert created.school_id is None


def test_an_unrecognised_domain_is_refused(client, db_session, google_token):
    google_token(email="stranger@unknown.example")

    response = client.get("/authorize")

    assert_redirects_to(response, "/login")
    assert db_session.scalar(select(func.count()).select_from(Teacher).filter_by(email="stranger@unknown.example")) == 0


def test_a_teacher_domain_creates_a_teacher_in_that_school(client, db_session, google_token):
    school = make_school(db_session, teacher_domain="staff.example.com")
    google_token(email="new.teacher@staff.example.com")

    response = client.get("/authorize")

    assert_redirects_to(response, "/teacher/")
    assert db_session.scalars(select(Teacher).filter_by(email="new.teacher@staff.example.com")).one().school_id == school.id


def test_a_volunteer_domain_needs_a_matching_invite_code(client, db_session, google_token):
    make_school(db_session, volunteer_domain="students.example.com")
    google_token(email="new.volunteer@students.example.com")

    response = client.get("/authorize")

    assert response.status_code in {301, 302, 303}
    assert "role=volunteer" in response.headers["Location"]
    assert db_session.scalar(select(func.count()).select_from(Volunteer)) == 0


def test_a_volunteer_with_a_valid_invite_is_created(client, db_session, google_token):
    school = make_school(db_session, volunteer_domain="students.example.com")
    code = get_or_create_invite_code(school)
    with client.session_transaction() as session:
        session["pending_invite_code"] = code
    google_token(email="new.volunteer@students.example.com")

    response = client.get("/authorize")

    assert_redirects_to(response, "/volunteer/survey")
    created = db_session.scalars(select(Volunteer).filter_by(email="new.volunteer@students.example.com")).one()
    assert created.school_id == school.id


def test_a_new_volunteer_inherits_the_teachers_default_capacity(client, db_session, google_token):
    """Not a hard-coded 1 — a teacher who runs 3-learner volunteers sets it once."""

    school = make_school(db_session, volunteer_domain="students.example.com")
    teacher = make_teacher(db_session, school)
    teacher.default_match_capacity = 3
    db_session.commit()
    code = get_or_create_invite_code(school)
    with client.session_transaction() as session:
        session["pending_invite_code"] = code
    google_token(email="new.volunteer@students.example.com")

    client.get("/authorize")

    assert db_session.scalars(select(Volunteer).filter_by(
        email="new.volunteer@students.example.com"
    )).one().match_capacity == 3


def test_an_invite_for_a_different_school_is_refused(client, db_session, google_token):
    make_school(db_session, name="Theirs", volunteer_domain="students.example.com")
    other = make_school(db_session, name="Elsewhere")
    with client.session_transaction() as session:
        session["pending_invite_code"] = get_or_create_invite_code(other)
    google_token(email="new.volunteer@students.example.com")

    response = client.get("/authorize")

    assert "role=volunteer" in response.headers["Location"]
    assert db_session.scalar(select(func.count()).select_from(Volunteer)) == 0


def test_a_returning_teacher_signs_in_without_a_second_account(client, db_session, google_token):
    school = make_school(db_session, teacher_domain="staff.example.com")
    existing = make_teacher(db_session, school, email="known@staff.example.com")
    google_token(email="known@staff.example.com")

    response = client.get("/authorize")

    assert_redirects_to(response, "/teacher/")
    assert db_session.scalar(select(func.count()).select_from(Teacher).filter_by(email="known@staff.example.com")) == 1
    with client.session_transaction() as session:
        assert session["_user_id"] == str(existing.id)


def test_a_returning_volunteer_lands_on_their_dashboard(client, db_session, google_token):
    school = make_school(db_session, volunteer_domain="students.example.com")
    teacher = make_teacher(db_session, school)
    make_volunteer(db_session, school, teacher, email="known@students.example.com")
    google_token(email="known@students.example.com")

    response = client.get("/authorize")

    assert_redirects_to(response, "/volunteer/")
    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(email="known@students.example.com")) == 1


def test_an_oauth_failure_is_reported_rather_than_crashing(client, db_session, google_token):
    google_token.fail(RuntimeError("token exchange failed"))

    assert_redirects_to(client.get("/authorize"), "/login")


# ── rate limiting ────────────────────────────────────────────────────────────


def test_repeated_login_attempts_are_throttled(client, db_session, learner, rate_limits_on):
    """Limits are off for the rest of the suite, so this opts back in.

    Without the opt-in every test would share one 127.0.0.1 bucket and start
    tripping the app's 300/min default.
    """

    statuses = [
        client.post("/login", data={"username": "learner", "password": "wrong"}).status_code
        for _ in range(12)
    ]

    assert 429 in statuses


def test_rate_limits_are_off_for_ordinary_tests(client, db_session, learner):
    statuses = [
        client.post("/login", data={"username": "learner", "password": "wrong"}).status_code
        for _ in range(15)
    ]

    assert 429 not in statuses


# ── first-time guidance (issue #185) ─────────────────────────────────────────
# The login page must say the same four things to someone who has never used the app.


def _flashes(client):
    with client.session_transaction() as session:
        return [message for _, message in session.get("_flashes", [])]


def test_login_says_who_uses_which_sign_in(client, db_session):
    body = assert_success(client.get("/login")).get_data(as_text=True)

    for marker in [
        "username and password", "Teachers and volunteers", "No password needed",
        "Use your school Google account",
        "Teachers: your account is already set up",
        'name="username"', 'name="password"', 'href="/login/google"', 'href="/register"',
    ]:
        assert marker in body


def test_login_is_one_plain_card_with_one_join_link(client, db_session):
    body = assert_success(client.get("/login")).get_data(as_text=True)
    card = parse(body).find("div", "auth-card")

    assert "auth-panel" not in body
    assert "School admins and administrators also sign in" not in body
    assert [a.attrs["href"] for a in card.find_all("a") if a.attrs["href"] == "/register"] == ["/register"]
    assert "ask your teacher for an invite code" not in body


def test_a_failed_sign_in_returns_to_the_login_page(client, db_session):
    response = client.post("/login", data={"username": "ghost", "password": "Password1!"})

    assert_redirects_to(response, "/login")


def test_a_failed_password_sign_in_points_teachers_and_volunteers_to_google(client, db_session):
    client.post("/login", data={"username": "teacher@school.test", "password": "x"})

    assert any("Sign in with Google" in message for message in _flashes(client))


def test_an_unrecognised_domain_is_told_to_use_a_school_account(client, db_session, google_token):
    google_token(email="stranger@unknown.example")

    client.get("/authorize")

    assert any("school Google account" in message for message in _flashes(client))


def test_a_new_volunteer_without_a_code_is_asked_for_one_rather_than_told_it_is_wrong(
    client, db_session, google_token
):
    """Pressing Sign in with Google on the login page, never having registered."""

    make_school(db_session, volunteer_domain="students.example.com")
    google_token(email="new.volunteer@students.example.com")

    response = client.get("/authorize")

    assert "role=volunteer" in response.headers["Location"]
    messages = _flashes(client)
    assert any("invite code" in message for message in messages)
    assert not any(message.startswith("Invalid") for message in messages)


def test_a_new_volunteer_with_a_wrong_code_is_told_it_is_invalid(client, db_session, google_token):
    make_school(db_session, name="Theirs", volunteer_domain="students.example.com")
    other = make_school(db_session, name="Elsewhere")
    with client.session_transaction() as session:
        session["pending_invite_code"] = get_or_create_invite_code(other)
    google_token(email="new.volunteer@students.example.com")

    client.get("/authorize")

    assert any(message.startswith("Invalid invite code") for message in _flashes(client))


def test_the_registration_page_tells_teachers_they_need_not_sign_up(client, db_session):
    body = assert_success(client.get("/register")).get_data(as_text=True)

    assert "Teachers: your account is already set up" in body
    assert "Already have an account?" in body
    assert "Use your school Google account" in body


def _tagged_by_id(page, tag, element_id):
    return next(el for el in page.find_all(tag) if el.attrs.get("id") == element_id)


def test_the_registration_fields_block_spaces_and_have_inline_errors(client, db_session):
    body = assert_success(client.get("/register")).get_data(as_text=True)
    page = parse(body)

    for field_id in ("username", "password", "confirm_password"):
        assert "data-no-spaces" in _tagged_by_id(page, "input", field_id).attrs
    for error_id in ("username-error", "password-error", "confirm-password-error"):
        assert "hidden" in _tagged_by_id(page, "p", error_id).attrs["class"]
    assert "Password must be 8+ characters" in _tagged_by_id(page, "p", "password-error").all_text
