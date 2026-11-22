import json
import re
from pathlib import Path

import pytest

from tests.support.assertions import (
    assert_json_keys,
    assert_redirects_to,
    assert_success,
)
from tests.support.factories import (
    make_attendance,
    make_donation,
    make_learner,
    make_school,
    make_teacher,
    make_volunteer,
)
from tests.support.html import parse

pytestmark = pytest.mark.web

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", ["/", "/schools", "/donations", "/privacy", "/terms", "/about"])
def test_public_pages_return_success(client, db_session, path):
    response = client.get(path)

    assert_success(response)


def test_home_counts_partner_schools_from_the_database(client, db_session):
    for _ in range(3):
        make_school(db_session)

    html = client.get("/").get_data(as_text=True)

    assert re.search(r'data-stat="partner_schools"[^>]*data-counter="3"', html)


def test_about_counts_partner_schools_from_the_database(client, db_session):
    for name in ("North School", "South School", "East School"):
        make_school(db_session, name=name)

    html = assert_success(client.get("/about")).get_data(as_text=True)

    assert re.search(r'about-impact-num[^"]*">3<', html)


def test_the_landing_page_shows_no_news_section_without_articles(client, db_session):
    html = assert_success(client.get("/")).get_data(as_text=True)

    assert "article-list" not in html


def test_the_landing_page_lists_the_latest_articles_as_plain_text(client, db_session):
    from tests.support.factories import make_admin, make_article

    make_article(db_session, make_admin(db_session), title="Hello there", content_markdown="**Bold** start")

    html = assert_success(client.get("/")).get_data(as_text=True)

    assert "Hello there" in html and "Bold start" in html and "**Bold**" not in html


def test_home_demo_questions_are_real_lesson_questions(client, db_session):
    from routes.base._public import LANDING_DEMO_QUESTIONS

    course = json.loads((_REPO_ROOT / "seed" / "files" / "content" / "questions.json").read_text(encoding="utf-8"))
    real = {
        (q["question_text"], tuple(q["options"]), q["answer"])
        for subject in course
        for topic in subject.get("topics", [])
        for lesson in topic["lessons"]
        for q in lesson["questions"]
        if q.get("content_type") == "multiple_choice"
    }

    html = client.get("/").get_data(as_text=True)

    assert len(LANDING_DEMO_QUESTIONS) == 3
    for q in LANDING_DEMO_QUESTIONS:
        assert (q["question_text"], tuple(q["options"]), q["answer"]) in real
        assert q["question_text"] in html


def test_home_landing_images_all_resolve(client, db_session):
    html = client.get("/").get_data(as_text=True)
    photos = set(re.findall(r'(/static/img/[\w.-]+\.jpg)', html))
    drawings = set(re.findall(r'(/static/svg/[\w.-]+\.svg)', html))
    sources = photos | drawings

    assert photos and len(drawings) >= 10
    for src in sources:
        assert_success(client.get(src))


def test_home_demo_finishes_on_the_celebration_stage(client, db_session):
    done = [d for d in parse(client.get("/").get_data(as_text=True)).find_all("div", "lp-demo-done")]

    assert len(done) == 1 and "hidden" in done[0].classes
    stage = done[0].find("div", "lp-done-stage")
    assert stage.attrs["aria-hidden"] == "true"
    assert stage.find("img", "lp-done-art").attrs["src"] == "/static/svg/celebrate.svg"
    assert done[0].find("button").attrs["id"] == "demoAgain"


def test_home_page_stylesheets_all_resolve(client, db_session):
    html = client.get("/").get_data(as_text=True)
    sheets = set(re.findall(r'href="(/static/css/pages/[\w-]+\.css)"', html))

    assert {"/static/css/pages/public.css", "/static/css/pages/landing.css"} <= sheets
    for sheet in sheets:
        assert assert_success(client.get(sheet)).mimetype == "text/css"


HOTLINKED_IMAGE_RE = re.compile(r"""<img\b[^>]*\bsrc=["'](?:https?:)?//""", re.IGNORECASE)


def test_no_template_hotlinks_an_image_from_another_site():
    templates = [*_REPO_ROOT.glob("templates/**/*.jx"), *_REPO_ROOT.glob("templates/**/*.html")]
    hits = [
        str(path.relative_to(_REPO_ROOT))
        for path in templates
        if HOTLINKED_IMAGE_RE.search(path.read_text(encoding="utf-8"))
    ]

    assert hits == []


@pytest.mark.parametrize("path", ["/schools", "/donations"])
def test_school_cards_show_each_schools_own_photo(client, db_session, path):
    make_school(db_session, name="Harbour View School", image_path="img/acs-athens.jpg")
    make_school(db_session, name="No Photo School")
    html = assert_success(client.get(path)).get_data(as_text=True)

    assert 'src="/static/img/acs-athens.jpg' in html
    assert 'alt="Harbour View School"' in html
    assert 'alt="No Photo School"' not in html


@pytest.mark.parametrize("path", ["/donations"])
def test_school_named_acs_athens_gets_no_photo_without_an_image_path(client, db_session, path):
    make_school(db_session, name="ACS Athens")
    html = assert_success(client.get(path)).get_data(as_text=True)

    assert 'alt="ACS Athens"' not in html


def test_the_school_directory_links_each_school_to_its_own_page(client, db_session):
    school = make_school(db_session, name="Lakeside Arts Academy")
    html = assert_success(client.get("/schools")).get_data(as_text=True)

    assert f'href="/schools/{school.id}"' in html


def test_searching_the_school_directory_lists_only_matching_schools(client, db_session):
    make_school(db_session, name="Lakeside Arts Academy")
    make_school(db_session, name="Palm Terrace High School")
    html = assert_success(client.get("/schools?q=LAKE")).get_data(as_text=True)

    assert "Lakeside Arts Academy" in html
    assert "Palm Terrace High School" not in html
    assert 'value="LAKE"' in html


def test_a_search_with_wildcards_matches_them_literally(client, db_session):
    make_school(db_session, name="Lakeside Arts Academy")
    html = assert_success(client.get("/schools?q=%25")).get_data(as_text=True)

    assert "Lakeside Arts Academy" not in html
    assert "data-empty-search" in html


def test_the_school_directory_pager_keeps_the_search(client, db_session):
    for i in range(30):
        make_school(db_session, name=f"Lake {i:02d}")
    html = assert_success(client.get("/schools?q=Lake")).get_data(as_text=True)

    assert re.search(r'href="/schools\?q=Lake&amp;page=2"', html)


def test_a_school_page_shows_the_school_and_its_own_impact(client, db_session):
    school = make_school(
        db_session, name="Harbour View School", mission_statement="Reading together after school.",
        image_path="img/acs-athens.jpg", location="Piraeus, Greece",
    )
    teacher = make_teacher(db_session, school)
    volunteer = make_volunteer(db_session, school, teacher)
    learner = make_learner(db_session, school, teacher, volunteer_id=volunteer.id)
    make_learner(db_session, school, teacher)
    make_attendance(db_session, teacher, learner, partner=volunteer, duration=2.5)
    make_donation(db_session, school=school, amount=4_200)
    other = make_school(db_session, name="Elsewhere School")
    make_learner(db_session, other, make_teacher(db_session, other))
    make_donation(db_session, school=other, amount=99_900)

    page = parse(assert_success(client.get(f"/schools/{school.id}")).get_data(as_text=True))
    stats = {el.attrs["data-stat"]: el.all_text for el in page.find_all() if "data-stat" in el.attrs}

    assert page.find("h1").all_text == "Harbour View School"
    assert "Reading together after school." in page.all_text
    assert "Piraeus, Greece" in page.all_text
    assert [img for img in page.find_all("img") if str(img.attrs.get("src")).startswith("/static/img/acs-athens.jpg")]
    assert stats == {"learners": "2", "volunteers": "1", "pairs": "1", "hours": "2.5", "raised": "$42"}


def test_a_school_without_a_logo_shows_its_initials(client, db_session):
    school = make_school(db_session, name="Harbour View School")
    page = parse(assert_success(client.get(f"/schools/{school.id}")).get_data(as_text=True))

    assert page.find(cls="school-mark").all_text == "HV"


def test_a_school_with_a_logo_shows_it(client, db_session):
    school = make_school(db_session, name="Harbour View School", logo_path="svg/school.svg")
    page = parse(assert_success(client.get(f"/schools/{school.id}")).get_data(as_text=True))

    assert str(page.find(cls="school-mark").find("img").attrs["src"]).startswith("/static/svg/school.svg")


def test_a_new_school_says_it_is_getting_started_instead_of_showing_zeros(client, db_session):
    school = make_school(db_session, name="Brand New School")
    html = assert_success(client.get(f"/schools/{school.id}")).get_data(as_text=True)

    assert "data-impact-empty" in html
    assert 'data-stat="learners"' not in html


def test_an_unknown_school_page_is_not_found(client, db_session):
    assert client.get("/schools/999999").status_code == 404


@pytest.mark.parametrize("path", ["/donations", "/about"])
def test_public_page_images_are_our_own_static_files(client, db_session, path):
    make_school(db_session, name="ACS Athens")
    html = assert_success(client.get(path)).get_data(as_text=True)
    sources = re.findall(r'<img\b[^>]*\bsrc="([^"]+)"', html)

    assert sources
    for src in sources:
        assert src.startswith("/static/"), src
        assert_success(client.get(src))


def test_home_offers_learner_and_volunteer_sign_up_to_visitors(client, db_session):
    html = client.get("/").get_data(as_text=True)

    assert "/register?role=learner" in html
    assert "/register?role=volunteer" in html


def test_home_hides_sign_up_from_signed_in_users(client, authenticated_learner):
    html = client.get("/").get_data(as_text=True)

    assert "/register?role=" not in html


def _hero_doors(html):
    hero = parse(html).find("section", "hero-section")
    return hero, {a.attrs["data-cta"]: a for a in hero.find("nav").find_all("a") if "data-cta" in a.attrs}


def test_home_hero_answers_what_a_new_visitor_does_next(client, db_session):
    hero, doors = _hero_doors(client.get("/").get_data(as_text=True))

    assert set(doors) == {"join_with_code", "sign_in", "donate"}
    assert doors["join_with_code"].attrs["href"] == "/register"
    assert doors["sign_in"].attrs["href"] == "/login"
    assert doors["donate"].attrs["href"] == "/donations"
    assert all(a.attrs["data-cta-location"] == "hero" for a in doors.values())
    # Where the code comes from, and that teachers have no sign-up, are said before the click.
    assert "teacher" in doors["join_with_code"].all_text
    assert "already set up" in doors["sign_in"].all_text
    lesson = [a for a in hero.find_all("a") if a.attrs.get("data-cta") == "see_lesson"]
    assert [a.attrs["href"] for a in lesson] == ["#try-it"]


def test_home_hero_shows_no_stock_photos(client, db_session):
    hero, _ = _hero_doors(client.get("/").get_data(as_text=True))

    assert not [img for img in hero.find_all("img") if "/static/img/" in img.attrs.get("src", "")]


def test_home_hero_keeps_only_the_support_door_once_signed_in(client, authenticated_learner):
    _, doors = _hero_doors(client.get("/").get_data(as_text=True))

    assert set(doors) == {"donate"}


def test_pages_load_the_built_tailwind_stylesheet_not_the_cdn(client, db_session):
    html = client.get("/").get_data(as_text=True)

    assert "/static/css/tailwind.css" in html
    assert "cdn.tailwindcss.com" not in html
    assert "tailwindcdn.js" not in html
    assert "tailwind.config" not in html


def test_health_reports_database_is_ready(client, db_session):
    response = client.get("/health")

    assert_json_keys(response, "status")
    assert response.json["status"] == "ok"


def test_unknown_route_renders_the_application_error_page(client, db_session):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert "does not exist" in response.get_data(as_text=True).lower()


def test_language_switcher_only_accepts_alphabetic_codes(client, db_session):
    response = client.post("/set-language", data={"lang": "el", "next": "/about"})

    assert_redirects_to(response, "/about")
    with client.session_transaction() as session:
        assert session["ui_lang"] == "el"


def test_language_switcher_does_not_store_invalid_code(client, db_session):
    client.post("/set-language", data={"lang": "../../", "next": "/"})

    with client.session_transaction() as session:
        assert "ui_lang" not in session


def test_the_school_page_donate_button_preselects_that_school(client, db_session):
    school = make_school(db_session, name="Harbour View School")
    html = assert_success(client.get(f"/schools/{school.id}")).get_data(as_text=True)

    assert f'href="/donations?school={school.id}"' in html
