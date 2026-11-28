"""The preview app's contract: personas sign in with one link, nothing real is reachable, every
page says it is fake, and none of it exists outside preview mode."""

from __future__ import annotations

import pytest

from helpers.preview.links import encode_links
from helpers.preview.personas import PERSONAS
from tests.support.app import use_environment

pytestmark = pytest.mark.web

SLUGS = [persona.slug for persona in PERSONAS]


def _session_user_id(client):
    with client.session_transaction() as session:
        return session.get("_user_id")


@pytest.mark.parametrize("path", ["/_preview/", "/_preview/enter?as=admin"])
def test_the_preview_routes_do_not_exist_outside_preview(client, path):
    assert client.get(path).status_code == 404


def test_reseeding_does_not_exist_outside_preview(client):
    assert client.post("/_preview/reseed", data={"size": "small"}).status_code == 404


def test_a_normal_app_adds_no_preview_headers_or_banner(client):
    response = client.get("/about")
    assert "X-Robots-Tag" not in response.headers
    assert "Server-Timing" not in response.headers
    assert b"integrated-preview-banner" not in response.data


def test_the_hub_lists_every_persona_and_the_commit(preview_client):
    page = preview_client.get("/_preview/").get_data(as_text=True)
    for slug in SLUGS:
        assert f'value="{slug}"' in page
    assert "abcdef1" in page


def test_the_hub_shows_the_pull_requests_links(preview_app, preview_client, monkeypatch):
    from dataclasses import replace

    links = encode_links([("teacher", "/teacher/matching")])
    monkeypatch.setitem(preview_app.config, "SETTINGS", replace(preview_app.config["SETTINGS"], preview_links=links))

    page = preview_client.get("/_preview/").get_data(as_text=True)

    assert "/_preview/enter?as=teacher&amp;next=%2Fteacher%2Fmatching" in page


@pytest.mark.parametrize("slug", SLUGS)
def test_every_persona_signs_in_and_lands_on_a_working_page(preview_client, slug):
    response = preview_client.get(f"/_preview/enter?as={slug}")
    assert response.status_code == 302
    assert _session_user_id(preview_client)

    landed = preview_client.get(response.headers["Location"], follow_redirects=True)

    assert landed.status_code == 200
    assert "/login" not in landed.request.path


def test_next_picks_the_page(preview_client):
    response = preview_client.get("/_preview/enter", query_string={"as": "teacher", "next": "/teacher/matching"})
    assert response.headers["Location"] == "/teacher/matching"


@pytest.mark.parametrize("target", ["//evil.example", "/\\evil.example", "https://evil.example", "/\t/evil.example"])
def test_next_never_redirects_off_site(preview_client, target):
    response = preview_client.get("/_preview/enter", query_string={"as": "teacher", "next": target})
    assert "evil" not in response.headers["Location"]


@pytest.mark.parametrize("query", ["", "?as=", "?as=1", "?as=nobody", "?id=1"])
def test_only_a_persona_slug_signs_in(preview_client, query):
    assert preview_client.get(f"/_preview/enter{query}").status_code == 404
    assert _session_user_id(preview_client) is None


def test_the_new_learner_is_sent_to_the_placement_test(preview_client):
    preview_client.get("/_preview/enter?as=learner-new")
    response = preview_client.get("/learner/", follow_redirects=True)
    assert "map" in response.request.path


def test_the_dev_sign_ins_stay_closed(preview_client):
    assert preview_client.get("/dev/login-as?type=teacher").status_code == 404
    assert preview_client.get("/dev/google-sign-in").status_code == 404


def test_google_sign_in_leads_to_the_persona_hub(preview_client):
    response = preview_client.get("/login/google")
    assert response.headers["Location"].endswith("/_preview/")


def test_the_component_gallery_is_available_but_not_in_production(preview_client, client, app, monkeypatch):
    assert preview_client.get("/dev/components").status_code == 200
    use_environment(app, monkeypatch, "production")
    assert client.get("/dev/components").status_code == 404


def test_every_page_carries_the_banner_and_is_hidden_from_search(preview_client):
    response = preview_client.get("/about")
    page = response.get_data(as_text=True)
    assert page.count("integrated-preview-banner") == 1
    assert "PR #42" in page and "fake data" in page
    assert response.headers["X-Robots-Tag"] == "noindex"


def test_json_is_left_alone_but_still_marked(preview_client):
    response = preview_client.get("/health")
    assert response.get_json() == {"status": "ok"}
    assert response.headers["X-Robots-Tag"] == "noindex"


def test_the_server_reports_total_and_database_time(preview_client):
    preview_client.get("/_preview/enter?as=teacher")
    timing = preview_client.get("/teacher/").headers["Server-Timing"]
    assert "total;dur=" in timing and "db;dur=" in timing
    assert 'desc="0 queries"' not in timing


def test_donating_says_unavailable_without_calling_stripe(preview_client, monkeypatch):
    import stripe

    def _fail(**kwargs):
        raise AssertionError("a preview must not call Stripe")

    monkeypatch.setattr(stripe.checkout.Session, "create", _fail)

    response = preview_client.post("/donations", data={"amount": "5", "school": "Preview School"})

    assert response.headers["Location"].endswith("/donations")
    with preview_client.session_transaction() as session:
        assert any("preview" in message.lower() for _, message in session["_flashes"])


def test_the_assistant_answers_from_a_script_through_the_real_tool_loop(preview_client):
    preview_client.get("/_preview/enter?as=teacher")

    stream = preview_client.post("/assistant/message", data={"message": "who could I match?"}).get_data(as_text=True)

    assert '"type": "step"' in stream and "preview_auto_match" in stream
    assert "scripted" in stream
    assert '"type": "error"' not in stream


def test_reseeding_resets_the_data_and_signs_the_browser_out(preview_app, preview_client):
    from extensions import db
    from models import Learner

    preview_client.get("/_preview/enter?as=teacher")
    with preview_app.app_context():
        before = db.session.scalar(db.select(db.func.count()).select_from(Learner))
        db.session.add(Learner(username="added-by-hand", password_hash="x"))
        db.session.commit()

    response = preview_client.post("/_preview/reseed", data={"size": "small"})

    assert response.status_code == 302
    assert _session_user_id(preview_client) is None
    with preview_app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Learner)) == before


@pytest.mark.parametrize("size", ["", "huge", "100000", "small; drop"])
def test_only_the_named_sizes_reseed(preview_client, size):
    assert preview_client.post("/_preview/reseed", data={"size": size}).status_code == 400


def test_reseeding_is_post_only_and_same_site(preview_client):
    assert preview_client.get("/_preview/reseed?size=small").status_code == 405
    response = preview_client.post("/_preview/reseed", data={"size": "small"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
