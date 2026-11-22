"""Request-level safety: cross-site writes, redirect targets, flash serialisation."""

import json
import re
from urllib.parse import urlsplit

import pytest

from tests.support.assertions import assert_redirects_to
from tests.support.factories import make_learner, make_school, make_teacher

pytestmark = pytest.mark.web


# ── cross-site writes ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Referer": "https://evil.example/page"},
    ],
)
def test_a_write_from_another_site_is_refused(client, db_session, headers):
    response = client.post("/set-language", data={"lang": "ar"}, headers=headers)

    assert response.status_code == 403
    with client.session_transaction() as session:
        assert "ui_lang" not in session


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://localhost"},
        {"Referer": "http://localhost/about"},
        {},
    ],
)
def test_a_write_from_this_site_or_with_no_source_goes_through(client, db_session, headers):
    response = client.post("/set-language", data={"lang": "ar"}, headers=headers)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["ui_lang"] == "ar"


def test_a_read_from_another_site_is_not_refused(client, db_session):
    response = client.get("/about", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200


def test_the_session_cookie_is_not_sent_on_cross_site_posts(client, db_session):
    learner = make_learner(db_session, make_school(db_session))

    response = client.post("/login", data={"username": learner.username, "password": "Password1!"})

    cookie = next(value for value in response.headers.getlist("Set-Cookie") if value.startswith("session="))
    assert "SameSite=Lax" in cookie


# ── /set-language redirect target ────────────────────────────────────────────


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/x", "/\\evil.example", "javascript:alert(1)"])
def test_switching_language_never_redirects_off_site(client, db_session, target):
    response = client.post("/set-language", data={"lang": "es", "next": target})

    location = urlsplit(response.headers["Location"])
    assert response.status_code == 302
    assert location.netloc in ("", "localhost")
    assert location.scheme in ("", "http")
    assert location.path == "/"


def test_switching_language_falls_back_to_a_same_site_referrer(client, db_session):
    response = client.post("/set-language", data={"lang": "es"}, headers={"Referer": "http://localhost/about?x=1"})

    assert_redirects_to(response, "/about?x=1")


def test_switching_language_ignores_an_off_site_referrer_path(client, db_session):
    # No Origin, so the cross-site check is skipped only when Referer is absent;
    # an off-site Referer is refused before the redirect is ever built.
    response = client.post("/set-language", data={"lang": "es"}, headers={"Referer": "https://evil.example/about"})

    assert response.status_code == 403


@pytest.mark.parametrize("target", ["/\t/evil.example", "/\n/evil.example"])
def test_switching_language_refuses_a_target_a_browser_would_read_as_off_site(client, db_session, target):
    response = client.post("/set-language", data={"lang": "es", "next": target})

    assert_redirects_to(response, "/")


# ── flash messages reach the page as valid JSON ──────────────────────────────


def _flash_payload(html):
    match = re.search(r'<script id="flash-messages" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert match, "flash-messages block missing"
    return json.loads(match.group(1))


def test_a_flash_carrying_quotes_and_markup_stays_parseable(client, db_session, authenticated_admin):
    name = 'Evil "School" </script><b>x</b>'

    response = client.post("/admin/schools/new", data={"name": name}, follow_redirects=True)

    messages = _flash_payload(response.get_data(as_text=True))
    assert messages == [{"category": "success", "message": f'School "{name}" created.'}]


# ── impersonation does not survive a fresh sign-in ───────────────────────────


def test_signing_in_again_ends_an_impersonation(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    impersonated = make_learner(db_session, school, teacher)
    other = make_learner(db_session, school, teacher)
    client.post(f"/admin/impersonate/{impersonated.id}")

    client.post("/login", data={"username": other.username, "password": "Password1!"})
    response = client.get("/admin/impersonate/stop")

    assert_redirects_to(response, "/")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(other.id)
        assert "impersonating_admin_id" not in session
