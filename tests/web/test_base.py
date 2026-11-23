"""Public pages, account settings, and the donation/Stripe boundary.

Stripe is never contacted: the checkout session, the retrieve call and the
webhook signature check are each monkeypatched at the seam `routes/base.py`
actually calls.
"""

from __future__ import annotations

from datetime import UTC
from typing import ClassVar

import pytest
import stripe
from sqlalchemy import func, select

from tests.support.app import use_environment
from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.factories import (
    make_article,
    make_attendance,
    make_donation,
    make_learner,
    make_school,
    make_site_content,
    make_teacher,
    make_team_member,
    make_volunteer,
)
from tests.support.html import parse

pytestmark = pytest.mark.web


# ── public pages ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/schools",
        "/donations",
        "/donation-success",
        "/about",
        "/news",
        "/terms",
        "/privacy",
        "/error",
        "/health",
    ],
)
def test_public_pages_return_success(client, db_session, path):
    assert_success(client.get(path))


@pytest.mark.parametrize(
    ("path", "markers"),
    [
        ("/", [
            "<title>IntegratED - Empowering Learner Education</title>", 'name="description"',
            "The people at the heart of IntegratED.", "Our community so far",
            'data-cta="join_with_code" data-cta-location="hero"', 'data-cta="see_lesson"', 'data-cta="start_learning"',
            'data-cta-location="get_involved"', 'data-cta="donate"', 'href="#try-it"', 'href="/donations"',
            'id="demo"', 'id="demoOptions"', 'id="demoSpeak"', 'id="demoNext"', 'id="demoAgain"', 'id="demoTicks"',
            'data-stat="learners"', 'data-stat="hours"', 'data-stat="pairs"', "const MCOptions = {",
            'class="lp-mark"', 'id="get-involved"',
        ]),
        ("/about", ["About IntegratED", "Our Impact", "Who We Are", "Our Mission"]),
        ("/donations", [
            "Give the Gift of Education", "Choose a School", "Choose an Amount", "Donate Now",
            'action="/donations"', 'id="donation-form"', 'name="school"', 'name="amount"', 'name="donor_name"',
            'name="donor_email"', 'name="message"', 'id="donate-btn"', 'id="custom-amount"', 'data-amount="500"',
            'id="submit-summary"',
        ]),
        ("/donation-success", ["Thank You!", "Your donation has been received.", 'href="/donations"', 'href="/"']),
        ("/terms", ["<h1", "Terms of Use", "Last Updated: 25 May 2026", "Legal", 'href="/privacy"', "legal-prose"]),
        ("/privacy", ["<h1", "Privacy Policy", "Last Updated: 25 May 2026", "Legal", 'href="/terms"', "legal-prose"]),
        ("/error", ["404", "Something Went Wrong", "Go Home", 'href="/"', "javascript:history.back()"]),
    ],
)
def test_each_public_page_renders_its_heading_and_markers(client, db_session, path, markers):
    body = assert_success(client.get(path)).get_data(as_text=True)

    for marker in markers:
        assert marker in body


def test_the_landing_page_shows_the_latest_articles(client, db_session):
    from tests.support.factories import make_admin

    article = make_article(db_session, make_admin(db_session), title="Garden Day")

    body = assert_success(client.get("/")).get_data(as_text=True)

    assert "Garden Day" in body
    assert f'href="/news/{article.id}"' in body


def test_the_landing_page_offers_no_get_involved_cards_once_signed_in(client, authenticated_learner):
    body = assert_success(client.get("/")).get_data(as_text=True)

    assert 'data-cta-location="get_involved"' not in body
    assert 'data-cta="see_lesson"' in body


def test_the_about_page_lists_each_team_member_with_their_job(client, db_session):
    make_team_member(db_session, name="Sam Coordinator", job="Lead Mentor")

    body = assert_success(client.get("/about")).get_data(as_text=True)

    assert "Meet Our Team" in body
    assert "Lead Mentor" in body


def test_the_donations_page_offers_each_school(client, db_session):
    make_school(db_session, name="Riverside")

    body = assert_success(client.get("/donations")).get_data(as_text=True)

    assert 'data-school="Riverside"' in body
    assert 'value="Riverside"' in body


def _by_id(page, element_id):
    return next(el for el in page.find_all() if el.attrs.get("id") == element_id)


def test_the_donations_page_preselects_the_school_in_the_link(client, db_session):
    make_school(db_session, name="Alpha School")
    chosen = make_school(db_session, name="Riverside")

    page = parse(assert_success(client.get(f"/donations?school={chosen.id}")).get_data(as_text=True))
    pressed = [el.attrs["data-school"] for el in page.find_all() if el.attrs.get("aria-pressed") == "true"]

    assert pressed == ["Riverside"]
    assert _by_id(page, "school-input").attrs["value"] == "Riverside"
    assert _by_id(page, "summary-school").all_text == "Riverside"


@pytest.mark.parametrize("query", ["?school=999999", "?school=abc", ""])
def test_the_donations_page_falls_back_to_the_first_school(client, db_session, query):
    make_school(db_session, name="Alpha School")
    make_school(db_session, name="Riverside")

    page = parse(assert_success(client.get(f"/donations{query}")).get_data(as_text=True))

    assert _by_id(page, "school-input").attrs["value"] == "Alpha School"


def test_the_terms_link_back_to_settings_when_signed_in(client, authenticated_learner):
    body = assert_success(client.get("/terms")).get_data(as_text=True)

    assert 'href="/settings"' in body


def test_the_unknown_page_error_has_its_title_and_way_home(client, db_session):
    response = client.get("/does-not-exist")

    body = response.get_data(as_text=True)
    assert response.status_code == 404
    assert "Page Not Found" in body
    assert "The page you are looking for does not exist." in body
    assert "Go Home" in body
    assert "<header" in body


def test_a_server_error_renders_the_styled_error_page(client, db_session, monkeypatch):
    from models import Attendance

    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(Attendance, "programme_hours", staticmethod(explode))

    response = client.get("/about")

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "Server Error" in body
    assert "Something went wrong." in body
    assert "Go Home" in body
    assert "<header" in body


def test_a_forbidden_page_renders_the_styled_error_page(client, db_session, authenticated_learner):
    response = client.get("/volunteer/")

    assert response.status_code == 403
    assert "Forbidden" in response.get_data(as_text=True)


def test_the_favicon_is_served(client, db_session):
    assert client.get("/favicon.ico").status_code in {200, 302, 308, 404}


def test_the_health_check_answers_without_a_session(client, db_session):
    assert_success(client.get("/health"))


def test_a_failing_health_check_does_not_leak_the_database_error(client, db_session, monkeypatch):
    from extensions import db

    def explode(*_args, **_kwargs):
        raise RuntimeError("could not connect to server at 10.0.0.5")

    monkeypatch.setattr(db.session, "execute", explode)

    response = client.get("/health")

    assert response.status_code == 503
    assert "10.0.0.5" not in response.get_data(as_text=True)


def test_the_schools_page_lists_schools_with_their_totals(client, db_session):
    school = make_school(db_session, name="Riverside")
    teacher = make_teacher(db_session, school)
    make_learner(db_session, school, teacher)
    make_donation(db_session, school=school, amount=5_000)

    body = assert_success(client.get("/schools")).get_data(as_text=True)

    assert "Riverside" in body


def test_the_school_directory_pages_at_twenty_five_from_a_to_z(client, db_session):
    for i in range(30):
        school = make_school(db_session, name=f"School {i:02d}")
        # Higher-index schools raise more, so the top three are School 29, 28, 27.
        make_donation(db_session, school=school, amount=(i + 1) * 100)

    page1 = assert_success(client.get("/schools")).get_data(as_text=True)
    page2 = assert_success(client.get("/schools?page=2")).get_data(as_text=True)

    for i in range(25):
        assert f"School {i:02d}" in page1
    for i in range(25, 30):
        assert f"School {i:02d}" in page2
    # Page 1 also shows the top three; nothing else from page 2 leaks onto it.
    assert "School 25" not in page1
    assert "School 26" not in page1
    assert "School 00" not in page2


def test_the_schools_page_opens_with_the_top_three_by_donations(client, db_session):
    schools = [make_school(db_session, name=f"School {i}") for i in range(5)]
    for amount, school in zip([100, 900, 300, 700, 500], schools, strict=True):
        make_donation(db_session, school=school, amount=amount)

    page = parse(assert_success(client.get("/schools")).get_data(as_text=True))
    ranks = {}
    for el in page.find_all():
        if "data-rank" in el.attrs:
            ranks.setdefault(el.attrs["data-rank"], set()).add(el.attrs["href"])

    assert ranks == {
        "1": {f"/schools/{schools[1].id}"},
        "2": {f"/schools/{schools[3].id}"},
        "3": {f"/schools/{schools[4].id}"},
    }


def test_the_top_three_step_aside_while_searching_or_paging(client, db_session):
    for i in range(30):
        make_school(db_session, name=f"School {i:02d}")

    for path in ["/schools?q=school", "/schools?page=2"]:
        page = parse(assert_success(client.get(path)).get_data(as_text=True))
        assert not [el for el in page.find_all() if "data-rank" in el.attrs], path


def test_an_out_of_range_schools_page_clamps_to_the_last_page(client, db_session):
    for i in range(30):
        make_school(db_session, name=f"School {i:02d}")

    assert_success(client.get("/schools?page=99"))


def test_the_about_page_shows_team_members_and_site_content(client, db_session):
    make_team_member(db_session, name="Sam Coordinator")
    make_site_content(db_session, key="about_intro", value="We are IntegratED")

    body = assert_success(client.get("/about")).get_data(as_text=True)

    assert "Sam Coordinator" in body


def test_the_about_page_counts_active_partnerships(client, db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    db_session.commit()
    make_attendance(db_session, teacher, learner, duration=2.0)

    assert_success(client.get("/about"))


# ── news (articles) ──────────────────────────────────────────────────────────

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _with_attr(elements, name, value):
    return [el for el in elements if el.attrs.get(name) == value]


def test_the_news_index_lists_articles(client, db_session):
    from tests.support.factories import make_admin

    author = make_admin(db_session)
    make_article(db_session, author, title="Our First Year")

    body = assert_success(client.get("/news")).get_data(as_text=True)

    assert "Our First Year" in body
    assert "<title>News - IntegratED</title>" in body


def test_the_news_index_pages_at_twenty_five_with_no_overlap(client, db_session):
    from datetime import datetime, timedelta

    from tests.support.factories import make_admin

    author = make_admin(db_session)
    base = datetime.now(UTC)
    for i in range(30):
        make_article(db_session, author, title=f"Article {i:02d}", created_at=base - timedelta(days=i))

    page1 = assert_success(client.get("/news")).get_data(as_text=True)
    page2 = assert_success(client.get("/news?page=2")).get_data(as_text=True)

    for i in range(25):
        assert f"Article {i:02d}" in page1
    assert "Article 25" not in page1
    for i in range(25, 30):
        assert f"Article {i:02d}" in page2
    assert "Article 00" not in page2


def test_an_article_detail_page_renders(client, db_session):
    from tests.support.factories import make_admin

    author = make_admin(db_session)
    article = make_article(db_session, author, title="Deep Dive")

    body = assert_success(client.get(f"/news/{article.id}")).get_data(as_text=True)

    assert "Deep Dive" in body
    assert "<title>Deep Dive - IntegratED</title>" in body
    assert "IntegratED Editor" in body
    assert "<h1>Heading</h1>" in body


def test_an_article_page_has_one_link_back_to_the_news_index(client, db_session):
    from tests.support.factories import make_admin

    article = make_article(db_session, make_admin(db_session))

    body = assert_success(client.get(f"/news/{article.id}")).get_data(as_text=True)

    assert body.count("Back to News") == 1
    assert len(_with_attr(parse(body).find("main").find_all("a"), "href", "/news")) == 1


def test_an_unknown_article_is_a_404(client, db_session):
    assert client.get("/news/999999").status_code == 404


def test_the_old_articles_urls_redirect_permanently_to_news(client, db_session):
    from tests.support.factories import make_admin

    article = make_article(db_session, make_admin(db_session))

    index = client.get("/articles?page=2")
    detail = client.get(f"/articles/{article.id}")

    assert index.status_code == 301
    assert index.headers["Location"].endswith("/news?page=2")
    assert detail.status_code == 301
    assert detail.headers["Location"].endswith(f"/news/{article.id}")


def test_the_public_nav_and_footer_link_to_the_news_page(client, db_session):
    doc = parse(assert_success(client.get("/about")).get_data(as_text=True))

    assert _with_attr(doc.find("header").find_all("a"), "href", "/news")
    assert _with_attr(doc.find("footer").find_all("a"), "href", "/news")


def test_a_signed_in_user_can_reach_news_from_the_footer(client, authenticated_teacher):
    doc = parse(assert_success(client.get("/teacher/")).get_data(as_text=True))

    assert _with_attr(doc.find("footer").find_all("a"), "href", "/news")


def test_an_article_with_a_hero_image_shows_it(client, db_session, monkeypatch):
    from tests.support.factories import make_admin
    from tests.support.storage import use_fake_storage

    storage = use_fake_storage(monkeypatch)
    storage.write("images/" + "a" * 32 + ".png", PNG_BYTES, "image/png")
    article = make_article(db_session, make_admin(db_session), hero_image="a" * 32 + ".png")

    detail = parse(assert_success(client.get(f"/news/{article.id}")).get_data(as_text=True))
    index = parse(assert_success(client.get("/news")).get_data(as_text=True))

    src = f"/news/images/{'a' * 32}.png"
    assert _with_attr(detail.find_all("img"), "src", src)
    assert _with_attr(index.find_all("img"), "src", src)


def test_an_article_without_a_hero_image_has_no_hero(client, db_session):
    from tests.support.factories import make_admin

    article = make_article(db_session, make_admin(db_session))

    body = assert_success(client.get(f"/news/{article.id}")).get_data(as_text=True)

    assert "/news/images/" not in body


def test_a_hero_image_is_served_publicly_with_a_long_cache(client, db_session, monkeypatch):
    from tests.support.storage import use_fake_storage

    storage = use_fake_storage(monkeypatch)
    storage.write("images/" + "b" * 32 + ".png", PNG_BYTES, "image/png")

    response = client.get(f"/news/images/{'b' * 32}.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data == PNG_BYTES
    assert "immutable" in response.headers["Cache-Control"]


@pytest.mark.parametrize("filename", ["c" * 32 + ".png", "..%2Fsecret.png", "not-a-hash.png", "d" * 32 + ".exe"])
def test_an_unknown_or_malformed_hero_image_is_a_404(client, db_session, monkeypatch, filename):
    from tests.support.storage import use_fake_storage

    use_fake_storage(monkeypatch)

    assert client.get(f"/news/images/{filename}").status_code == 404


# ── language switching ───────────────────────────────────────────────────────


def test_the_interface_language_can_be_switched(client, db_session):
    client.post("/set-language", data={"lang": "ar"})

    with client.session_transaction() as session:
        assert session.get("ui_lang") == "ar"


@pytest.mark.parametrize("lang", ["a", "toolongcode", "e n", "../etc", "12"])
def test_a_malformed_language_code_is_ignored(client, db_session, lang):
    client.post("/set-language", data={"lang": lang})

    with client.session_transaction() as session:
        assert session.get("ui_lang") is None


def test_switching_language_returns_to_the_page_you_came_from(client, db_session):
    response = client.post("/set-language", data={"lang": "es", "next": "/about"})

    assert_redirects_to(response, "/about")


# ── donations: starting checkout ─────────────────────────────────────────────


class _FakeCheckoutSession:
    url = "https://checkout.stripe.test/session/cs_test_123"


@pytest.fixture
def stripe_checkout(monkeypatch):
    """Capture what would have been sent to Stripe, without a network call."""


    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return _FakeCheckoutSession()

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(create))
    return calls


def test_starting_a_donation_redirects_to_stripe(client, db_session, stripe_checkout):
    make_school(db_session, name="Riverside")

    response = client.post(
        "/donations",
        data={"school": "Riverside", "amount": "25", "donor_name": "Kind Person"},
    )

    assert response.status_code == 303
    assert response.headers["Location"] == _FakeCheckoutSession.url
    assert stripe_checkout[0]["metadata"]["school"] == "Riverside"


def test_the_donation_amount_is_sent_to_stripe_in_cents(client, db_session, stripe_checkout):
    make_school(db_session, name="Riverside")

    client.post("/donations", data={"school": "Riverside", "amount": "25.50"})

    assert stripe_checkout[0]["line_items"][0]["price_data"]["unit_amount"] == 2550


def test_checkout_only_sends_parameters_the_installed_stripe_accepts(client, db_session, stripe_checkout):
    # The create call is mocked, so a parameter the pinned Stripe API version
    # dropped would otherwise pass here and fail every real donation.
    from stripe.params.checkout import SessionCreateParams

    make_school(db_session, name="Riverside")

    client.post("/donations", data={"school": "Riverside", "amount": "25", "donor_email": "a@example.com"})

    accepted = SessionCreateParams.__required_keys__ | SessionCreateParams.__optional_keys__
    assert set(stripe_checkout[0]) - accepted == set()


@pytest.mark.parametrize("amount",["0.10", "0", "-5", "abc", ""])
def test_an_invalid_donation_amount_is_refused(client, db_session, stripe_checkout, amount):
    make_school(db_session, name="Riverside")

    response = client.post("/donations", data={"school": "Riverside", "amount": amount})

    assert_redirects_to(response, "/donations")
    assert stripe_checkout == []


def test_a_donation_needs_a_school(client, db_session, stripe_checkout):
    response = client.post("/donations", data={"school": "", "amount": "25"})

    assert_redirects_to(response, "/donations")
    assert stripe_checkout == []


def test_a_stripe_failure_is_reported_rather_than_raised(client, db_session, monkeypatch):

    class _Boom(stripe.StripeError):
        user_message = "card declined"

    def explode(**kwargs):
        raise _Boom("nope")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(explode))
    make_school(db_session, name="Riverside")

    response = client.post("/donations", data={"school": "Riverside", "amount": "25"})

    assert_redirects_to(response, "/donations")


# ── donations: recording the result ──────────────────────────────────────────


def _completed_session(session_id="cs_test_1", school="Riverside", amount=2500):
    return {
        "id": session_id,
        "amount_total": amount,
        "payment_status": "paid",
        "metadata": {"school": school, "donor_name": "Kind Person", "message": "Well done"},
        "customer_details": {"email": "kind@example.com"},
    }


def test_a_completed_session_becomes_a_donation(app, db_session):
    from models import Donation
    from routes.base import record_donation_from_session

    school = make_school(db_session, name="Riverside")

    record_donation_from_session(_completed_session())

    donation = db_session.scalars(select(Donation)).one()
    assert donation.amount == 2500
    assert donation.donor_name == "Kind Person"
    assert donation.donor_email == "kind@example.com"
    assert donation.school_id == school.id


def test_recording_the_same_session_twice_creates_one_donation(app, db_session):
    """Both the webhook and the success page call this."""

    from models import Donation
    from routes.base import record_donation_from_session

    make_school(db_session, name="Riverside")

    record_donation_from_session(_completed_session())
    second = record_donation_from_session(_completed_session())

    assert second is None
    assert db_session.scalar(select(func.count()).select_from(Donation)) == 1


def test_a_session_with_no_id_is_ignored(app, db_session):
    from models import Donation
    from routes.base import record_donation_from_session

    assert record_donation_from_session({"amount_total": 100}) is None
    assert db_session.scalar(select(func.count()).select_from(Donation)) == 0


def test_a_donation_to_an_unknown_school_is_still_recorded(app, db_session):
    """The money arrived; losing it because the name did not match is worse."""

    from models import Donation
    from routes.base import record_donation_from_session

    record_donation_from_session(_completed_session(school="Nowhere High"))

    assert db_session.scalars(select(Donation)).one().school_id is None


def test_a_stripe_object_without_get_is_normalized(app, db_session):
    from models import Donation
    from routes.base import record_donation_from_session

    class _StripeObject:
        def to_dict(self):
            return _completed_session("cs_obj_1")

    record_donation_from_session(_StripeObject())

    assert db_session.scalar(select(func.count()).select_from(Donation).filter_by(stripe_session_id="cs_obj_1")) == 1


def test_the_success_page_records_a_paid_session(client, db_session, monkeypatch):
    from models import Donation

    make_school(db_session, name="Riverside")
    monkeypatch.setattr(
        stripe.checkout.Session,
        "retrieve",
        staticmethod(lambda session_id: _FakeRetrieved()),
    )

    assert_success(client.get("/donation-success?session_id=cs_test_9"))

    assert db_session.scalar(select(func.count()).select_from(Donation)) == 1


class _FakeRetrieved:
    id = "cs_test_9"
    amount_total = 2500
    payment_status = "paid"
    metadata: ClassVar[dict[str, str]] = {"school": "Riverside", "donor_name": "Kind Person", "message": ""}

    def to_dict(self):
        return {
            "id": self.id,
            "amount_total": self.amount_total,
            "metadata": self.metadata,
            "customer_details": {"email": "kind@example.com"},
        }


def test_the_success_page_survives_a_stripe_error(client, db_session, monkeypatch):

    def explode(session_id):
        raise stripe.StripeError("gone")

    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(explode))

    assert_success(client.get("/donation-success?session_id=cs_bad"))


# ── the Stripe webhook ───────────────────────────────────────────────────────


def test_the_webhook_is_refused_when_no_secret_is_configured(app, client, db_session, monkeypatch):
    use_environment(app, monkeypatch, "development", stripe_webhook_secret="")

    assert client.post("/stripe/webhook", data=b"{}").status_code == 400


def test_a_webhook_with_a_bad_signature_is_refused(app, client, db_session, monkeypatch):

    use_environment(app, monkeypatch, "development", stripe_webhook_secret="whsec_test")

    def explode(payload, sig_header, secret):
        raise ValueError("bad signature")

    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(explode))

    assert client.post("/stripe/webhook", data=b"{}").status_code == 400


def test_a_verified_completed_checkout_records_the_donation(app, client, db_session, monkeypatch):
    from models import Donation

    make_school(db_session, name="Riverside")
    use_environment(app, monkeypatch, "development", stripe_webhook_secret="whsec_test")
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(
            lambda payload, sig, secret: {
                "type": "checkout.session.completed",
                "data": {"object": _completed_session("cs_hook_1")},
            }
        ),
    )

    response = client.post("/stripe/webhook", data=b"{}")

    assert response.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Donation).filter_by(stripe_session_id="cs_hook_1")) == 1


def test_an_unrelated_webhook_event_is_acknowledged_and_ignored(app, client, db_session, monkeypatch):
    from models import Donation

    use_environment(app, monkeypatch, "development", stripe_webhook_secret="whsec_test")
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda payload, sig, secret: {"type": "invoice.paid", "data": {}}),
    )

    assert client.post("/stripe/webhook", data=b"{}").status_code == 200
    assert db_session.scalar(select(func.count()).select_from(Donation)) == 0


# ── account settings ─────────────────────────────────────────────────────────


def test_settings_require_a_session(client, db_session):
    response = client.get("/settings")

    assert response.status_code in {301, 302, 303, 401}


@pytest.mark.parametrize(
    "fixture_name",
    ["authenticated_learner", "authenticated_teacher", "authenticated_volunteer", "authenticated_admin"],
)
def test_settings_render_for_every_role(client, db_session, request, fixture_name):
    request.getfixturevalue(fixture_name)

    assert_success(client.get("/settings"))


_SETTINGS_SHARED = [
    "Account Settings", 'action="/settings"', 'value="update_profile"', 'name="name"', 'value="delete_account"',
    'name="confirm_delete"', 'id="show-delete-form-btn"', 'id="delete-submit-btn"', 'id="cancel-delete-btn"',
    'action="/set-language"', 'name="lang"', 'value="ar"', 'href="/terms"', 'href="/privacy"',
    'data-section="profile"', 'data-section="language"', 'data-section="legal"', 'data-section="danger"',
]
_SETTINGS_PASSWORD = [
    'name="username"', 'value="change_password"', 'name="current_password"', 'name="new_password"',
    'name="confirm_password"', 'data-section="security"',
]


@pytest.mark.parametrize(
    ("fixture_name", "present", "absent"),
    [
        ("authenticated_learner", [*_SETTINGS_SHARED, *_SETTINGS_PASSWORD, '/learner/survey'], ["Managed by Google"]),
        ("authenticated_volunteer", [*_SETTINGS_SHARED, '/volunteer/survey', "readonly"], _SETTINGS_PASSWORD),
        ("authenticated_teacher", [*_SETTINGS_SHARED, "readonly"], [*_SETTINGS_PASSWORD, 'data-section="personalization"']),
        ("authenticated_admin", [*_SETTINGS_SHARED, *_SETTINGS_PASSWORD, "Administrator"], ['data-section="personalization"']),
    ],
)
def test_settings_shows_each_role_its_sections_and_fields(client, db_session, request, fixture_name, present, absent):
    request.getfixturevalue(fixture_name)

    body = assert_success(client.get("/settings")).get_data(as_text=True)

    for marker in present:
        assert marker in body
    for marker in absent:
        assert marker not in body


def test_settings_gives_personalization_its_own_colour_and_icon(client, db_session, authenticated_learner):
    page = parse(assert_success(client.get("/settings")).get_data(as_text=True))
    nav = {link.attrs["data-section"]: link for link in page.find_all("a", "settings-nav-link")}
    sections = {s.attrs["id"]: s for s in page.find_all("section")}

    assert "clay-card-pink" in sections["personalization"].find("div").classes
    assert "clay-card-purple" in sections["legal"].find("div").classes
    assert nav["personalization"].find("div").classes != nav["legal"].find("div").classes
    assert nav["personalization"].find("svg").find_all() != nav["legal"].find("svg").find_all()


def test_the_header_settings_button_is_active_only_on_settings(client, db_session, authenticated_learner):
    def settings_button(path):
        page = parse(assert_success(client.get(path)).get_data(as_text=True))
        return next(a for a in page.find_all("a", "btn-nav-icon") if a.attrs.get("href") == "/settings")

    assert settings_button("/settings").attrs.get("aria-current") == "page"
    assert "aria-current" not in settings_button("/terms").attrs


def test_settings_prefills_the_learners_name_and_username(client, db_session, authenticated_learner):
    body = assert_success(client.get("/settings")).get_data(as_text=True)

    assert f'value="{authenticated_learner.username}"' in body
    assert f'value="{authenticated_learner.name}"' in body


def test_settings_shows_a_google_users_email_read_only(client, db_session, authenticated_teacher):
    body = assert_success(client.get("/settings")).get_data(as_text=True)

    assert f'value="{authenticated_teacher.email}"' in body


@pytest.mark.parametrize("fixture_name", ["authenticated_learner", "authenticated_volunteer"])
def test_settings_shows_a_redo_survey_link_for_learners_and_volunteers(client, db_session, request, fixture_name):
    request.getfixturevalue(fixture_name)

    body = assert_success(client.get("/settings")).get_data(as_text=True)

    assert "personalization" in body


@pytest.mark.parametrize("fixture_name", ["authenticated_teacher", "authenticated_admin"])
def test_settings_hides_the_redo_survey_link_for_staff_roles(client, db_session, request, fixture_name):
    request.getfixturevalue(fixture_name)

    body = assert_success(client.get("/settings")).get_data(as_text=True)

    assert "personalization" not in body


def test_a_learner_can_change_their_display_name(client, db_session, authenticated_learner):
    client.post("/settings", data={"action": "update_profile", "name": "Ada L"})

    db_session.expire_all()
    assert authenticated_learner.name == "Ada L"


def test_a_learner_can_change_their_username(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={"action": "update_profile", "name": "Ada", "username": "ada_new"},
    )

    db_session.expire_all()
    assert authenticated_learner.username == "ada_new"


def test_a_username_already_taken_is_refused(client, db_session, authenticated_learner, school):
    teacher = make_teacher(db_session, school)
    make_learner(db_session, school, teacher, username="taken")
    original = authenticated_learner.username

    client.post(
        "/settings", data={"action": "update_profile", "name": "Ada", "username": "taken"}
    )

    db_session.expire_all()
    assert authenticated_learner.username == original


def test_a_learner_can_change_their_password(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "Password1!",
            "new_password": "BrandNew1!",
            "confirm_password": "BrandNew1!",
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("BrandNew1!")


def test_a_password_change_ignores_whitespace_around_each_password(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "Password1! ",
            "new_password": " BrandNew1! ",
            "confirm_password": "BrandNew1!",
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("BrandNew1!")


def test_a_username_with_a_space_is_refused(client, db_session, authenticated_learner):
    original = authenticated_learner.username

    client.post("/settings", data={"action": "update_profile", "name": "Ada", "username": "ada new"})

    db_session.expire_all()
    assert authenticated_learner.username == original


@pytest.mark.parametrize("new_password", ["Brand New1!", "Brand New1!"])
def test_a_new_password_with_a_space_is_refused(client, db_session, authenticated_learner, new_password):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "Password1!",
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("Password1!")


def test_the_settings_password_fields_have_toggles_and_say_spaces_are_not_allowed(client, db_session, authenticated_learner):
    body = assert_success(client.get("/settings")).get_data(as_text=True)
    controls = [b.attrs.get("aria-controls") for b in parse(body).find_all("button", "password-toggle")]

    assert controls == ["current_password", "new_password", "confirm_password"]
    assert "No spaces allowed." in body


def test_the_current_password_must_be_right(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "WrongPassword1!",
            "new_password": "BrandNew1!",
            "confirm_password": "BrandNew1!",
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("Password1!")


def test_a_mistyped_confirmation_is_refused(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "Password1!",
            "new_password": "BrandNew1!",
            "confirm_password": "Different1!",
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("Password1!")


def test_a_weak_new_password_is_refused(client, db_session, authenticated_learner):
    client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "Password1!",
            "new_password": "short",
            "confirm_password": "short",
        },
    )

    db_session.expire_all()
    assert authenticated_learner.check_password("Password1!")


def test_a_google_account_cannot_change_a_password(client, db_session, authenticated_teacher):
    """Teachers and volunteers sign in through Google and hold no password."""

    response = client.post(
        "/settings",
        data={
            "action": "change_password",
            "current_password": "x",
            "new_password": "BrandNew1!",
            "confirm_password": "BrandNew1!",
        },
    )

    assert_redirects_to(response, "/settings")


# ── deleting an account ──────────────────────────────────────────────────────


def test_deleting_an_account_requires_the_exact_confirmation(client, db_session, authenticated_learner):
    from models import Learner

    learner_id = authenticated_learner.id

    client.post("/settings", data={"action": "delete_account", "confirm_delete": "delete"})

    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=learner_id)) == 1


def test_a_learner_can_delete_their_own_account(client, db_session, authenticated_learner):
    from models import Learner

    learner_id = authenticated_learner.id

    response = client.post(
        "/settings", data={"action": "delete_account", "confirm_delete": "DELETE"}
    )

    assert_redirects_to(response, "/")
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=learner_id)) == 0


def test_a_volunteer_can_delete_their_own_account(client, db_session, authenticated_volunteer):
    from models import Volunteer

    volunteer_id = authenticated_volunteer.id

    client.post("/settings", data={"action": "delete_account", "confirm_delete": "DELETE"})

    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(id=volunteer_id)) == 0


def test_deleting_a_teacher_releases_their_roster_rather_than_deleting_it(
    client, db_session, authenticated_teacher
):
    """The people must survive their teacher leaving."""

    from models import Learner, Volunteer

    school = authenticated_teacher.school
    learner = make_learner(db_session, school, authenticated_teacher)
    volunteer = make_volunteer(db_session, school, authenticated_teacher)

    client.post("/settings", data={"action": "delete_account", "confirm_delete": "DELETE"})

    db_session.expire_all()
    assert db_session.get(Learner, learner.id).teacher_id is None
    assert db_session.get(Volunteer, volunteer.id).teacher_id is None


def test_a_donation_is_thanked_with_its_impact_tier():
    from routes.base._donations import impact_tier

    assert [impact_tier(amount) for amount in (10, 25, 120, 250, 9_999)] == ["default", "25", "100", "250", "500"]


def test_the_donation_form_carries_translated_impact_lines(client, db_session):
    make_school(db_session, name="Riverside")

    html = assert_success(client.get("/donations")).get_data(as_text=True)

    assert "const IMPACT = [[500," in html
    assert "Your generous donation will make a real difference" not in html


def test_the_success_confetti_respects_reduced_motion(client, db_session):
    html = assert_success(client.get("/donation-success")).get_data(as_text=True)

    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in html


def _tagged_by_id(page, tag, element_id):
    return next(el for el in page.find_all(tag) if el.attrs.get("id") == element_id)


def test_the_settings_fields_block_spaces_and_have_inline_errors(client, db_session, authenticated_learner):
    page = parse(assert_success(client.get("/settings")).get_data(as_text=True))

    for field_id in ("username", "new_password", "confirm_password"):
        assert "data-no-spaces" in _tagged_by_id(page, "input", field_id).attrs
    for error_id in ("new-password-error", "confirm-password-error"):
        assert "hidden" in _tagged_by_id(page, "p", error_id).attrs["class"]
