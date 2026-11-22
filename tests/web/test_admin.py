"""Administrator routes: platform CRUD, impersonation, site content and articles (the database
console is in test_admin_db_console.py)."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.factories import (
    make_article,
    make_donation,
    make_learner,
    make_school,
    make_site_content,
    make_teacher,
    make_team_member,
    make_volunteer,
)

pytestmark = pytest.mark.web


# ── pages render ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/admin/dashboard",
        "/admin/schools",
        "/admin/schools/new",
        "/admin/users",
        "/admin/donations",
        "/admin/db",
    ],
)
def test_admin_pages_render_for_an_administrator(client, authenticated_admin, path):
    assert_success(client.get(path))


@pytest.mark.parametrize(
    ("path", "markers"),
    [
        ("/admin/dashboard", ["Platform Overview", 'name="team_statement"', 'name="how_we_work"', 'name="mission_statement"']),
        ("/admin/db", ["Database", 'name="sql"', 'id="importModal"', 'id="tableSelect"']),
        ("/admin/schools/new", ["Create New School", 'name="volunteer_domain"', 'name="admin_password"']),
        ("/admin/articles/new", ["Create Article", 'name="title"', 'name="content"']),
        ("/admin/team/new", ["Add Team Member", 'name="job"', 'name="strengths"', 'name="bio"']),
    ],
)
def test_each_admin_page_renders_its_heading_and_form_fields(client, authenticated_admin, path, markers):
    body = assert_success(client.get(path)).get_data(as_text=True)

    for marker in markers:
        assert marker in body


def test_the_article_editor_is_filled_with_the_article(client, db_session, authenticated_admin):
    article = make_article(db_session, authenticated_admin, title="Harvest Day")

    body = assert_success(client.get(f"/admin/articles/edit/{article.id}")).get_data(as_text=True)

    assert 'value="Harvest Day"' in body
    assert article.content_markdown in body


def test_the_team_editor_is_filled_with_the_member(client, db_session, authenticated_admin):
    member = make_team_member(db_session, name="Sam Rivers")

    body = assert_success(client.get(f"/admin/team/edit/{member.id}")).get_data(as_text=True)

    assert 'value="Sam Rivers"' in body


def test_the_school_detail_page_offers_delete_and_impersonation(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)

    body = assert_success(client.get(f"/admin/schools/{school.id}")).get_data(as_text=True)

    assert f'action="/admin/schools/{school.id}/delete"' in body
    assert f'action="/admin/impersonate/{teacher.id}"' in body


def test_the_dashboard_lists_team_members_and_articles_with_delete_forms(client, db_session, authenticated_admin):
    member = make_team_member(db_session, name="Sam Rivers")
    article = make_article(db_session, authenticated_admin, title="Harvest Day")

    body = assert_success(client.get("/admin/dashboard")).get_data(as_text=True)

    assert "Sam Rivers" in body and "Harvest Day" in body
    assert f'action="/admin/team/delete/{member.id}"' in body
    assert f'action="/admin/articles/delete/{article.id}"' in body
    assert 'data-remove-selector="tr"' in body


def test_the_dashboard_reports_platform_totals(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    make_learner(db_session, school, teacher)
    make_donation(db_session, amount=5_000, school=school)

    body = assert_success(client.get("/admin/dashboard")).get_data(as_text=True)

    assert school.name in body


def test_the_school_list_shows_each_school(client, db_session, authenticated_admin):
    make_school(db_session, name="Riverside")

    body = assert_success(client.get("/admin/schools")).get_data(as_text=True)

    assert "Riverside" in body


def test_a_school_detail_page_lists_its_people(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school, name="Ms Okafor")
    make_learner(db_session, school, teacher, name="Ada")

    body = assert_success(client.get(f"/admin/schools/{school.id}")).get_data(as_text=True)

    assert "Ada" in body


def test_an_unknown_school_detail_is_a_404(client, authenticated_admin):
    assert client.get("/admin/schools/999999").status_code == 404


def test_the_donations_ledger_lists_donations(client, db_session, authenticated_admin):
    school = make_school(db_session)
    make_donation(db_session, amount=2_500, school=school, donor_name="Kind Person")

    body = assert_success(client.get("/admin/donations")).get_data(as_text=True)

    assert "Kind Person" in body


# ── pagination ───────────────────────────────────────────────────────────────


def test_the_school_list_pages_at_twenty_five_with_no_overlap(client, db_session, authenticated_admin):
    for i in range(30):
        make_school(db_session, name=f"School {i:02d}")

    page1 = assert_success(client.get("/admin/schools")).get_data(as_text=True)
    page2 = assert_success(client.get("/admin/schools?page=2")).get_data(as_text=True)

    for i in range(25):
        assert f"School {i:02d}" in page1
    assert "School 25" not in page1
    for i in range(25, 30):
        assert f"School {i:02d}" in page2
    assert "School 00" not in page2


def test_an_out_of_range_school_page_clamps_to_the_last_page(client, db_session, authenticated_admin):
    for i in range(30):
        make_school(db_session, name=f"School {i:02d}")

    body = assert_success(client.get("/admin/schools?page=99")).get_data(as_text=True)

    assert "School 29" in body


@pytest.mark.parametrize("bad_page", ["0", "-1", "not-a-number"])
def test_an_invalid_school_page_does_not_error(client, db_session, authenticated_admin, bad_page):
    make_school(db_session, name="Only School")

    body = assert_success(client.get(f"/admin/schools?page={bad_page}")).get_data(as_text=True)

    assert "Only School" in body


def test_the_user_list_pages_and_the_type_filter_survives_the_hop(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    for i in range(30):
        make_learner(db_session, school, teacher, username=f"learner{i:02d}")

    page1 = assert_success(client.get("/admin/users?type=learner")).get_data(as_text=True)
    page2 = assert_success(client.get("/admin/users?type=learner&page=2")).get_data(as_text=True)

    # Newest (highest id) first, so the 30th created row leads page 1.
    assert "learner29" in page1
    assert "learner04" in page2 and "learner29" not in page2
    assert "type=learner" in page1


def test_the_admin_user_list_no_longer_hides_rows_past_five_hundred(client, db_session, authenticated_admin):
    """Regression guard for the removed `.limit(500)` cap: a filtered type with
    more than one page's worth of rows must still expose a second page rather
    than silently truncating."""
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    for i in range(26):
        make_learner(db_session, school, teacher, username=f"learner{i:02d}")

    body = assert_success(client.get("/admin/users?type=learner")).get_data(as_text=True)

    assert "page=2" in body


def test_the_donations_ledger_pages_and_totals_the_whole_table(client, db_session, authenticated_admin):
    school = make_school(db_session)
    for _ in range(30):
        make_donation(db_session, amount=1_000, school=school)

    page1 = assert_success(client.get("/admin/donations")).get_data(as_text=True)
    page2 = assert_success(client.get("/admin/donations?page=2")).get_data(as_text=True)

    assert "page=2" in page1
    # Total is a separate aggregate query, not a Python sum over the page's
    # own rows — identical on page 1 and page 2, never "total of this page".
    assert "$300.00" in page1  # total across all 30, not just the 25 shown
    assert "$300.00" in page2
    assert "30" in page1
    assert "30" in page2  # donation count stat, unaffected by which page


def test_donations_can_be_scoped_to_one_school_for_the_school_detail_preview(
    client, db_session, authenticated_admin
):
    school = make_school(db_session, name="Filtered School")
    other = make_school(db_session, name="Other School")
    make_donation(db_session, amount=500, school=school)
    make_donation(db_session, amount=700, school=other)

    body = assert_success(client.get(f"/admin/donations?school_id={school.id}")).get_data(as_text=True)

    assert "$5.00" in body
    assert "$7.00" not in body


def test_the_school_filter_survives_a_page_hop_on_donations(client, db_session, authenticated_admin):
    school = make_school(db_session, name="Filtered School")
    other = make_school(db_session, name="Other School")
    for _ in range(30):
        make_donation(db_session, amount=100, school=school)
    make_donation(db_session, amount=999_999, school=other)

    page2 = assert_success(
        client.get(f"/admin/donations?school_id={school.id}&page=2")
    ).get_data(as_text=True)

    # Still scoped to the filtered school on page 2 — the other school's huge
    # donation never leaks in just because the filter dropped on the hop.
    assert "$9999.99" not in page2
    assert f"school_id={school.id}" in page2


def test_the_school_detail_page_previews_and_links_to_the_full_donation_list(
    client, db_session, authenticated_admin
):
    school = make_school(db_session)
    for _ in range(10):
        make_donation(db_session, amount=100, school=school)

    body = assert_success(client.get(f"/admin/schools/{school.id}")).get_data(as_text=True)

    assert f"school_id={school.id}" in body
    assert "10" in body  # the full donation count, not the 7-row preview


# ── schools ──────────────────────────────────────────────────────────────────


def test_creating_a_school_persists_it(client, db_session, authenticated_admin):
    from models import School

    response = client.post(
        "/admin/schools/new",
        data={"name": "New School", "mission_statement": "Learn together"},
    )

    assert_redirects_to(response, "/admin/schools")
    assert db_session.scalars(select(School).filter_by(name="New School")).one().mission_statement == "Learn together"


def test_creating_a_school_can_create_its_admin(client, db_session, authenticated_admin):
    from models import SchoolAdmin

    client.post(
        "/admin/schools/new",
        data={
            "name": "Admin School",
            "admin_username": "head",
            "admin_password": "Password1!",
            "admin_name": "Head Teacher",
        },
    )

    created = db_session.scalars(select(SchoolAdmin).filter_by(username="head")).one()
    assert created.check_password("Password1!")


@pytest.mark.parametrize(
    ("admin_username", "admin_password"), [("head teacher", "Password1!"), ("head", "Pass word1!")]
)
def test_a_school_admin_with_a_space_in_the_credentials_is_refused(
    client, db_session, authenticated_admin, admin_username, admin_password
):
    from models import School, SchoolAdmin

    response = client.post(
        "/admin/schools/new",
        data={"name": "Spaced School", "admin_username": admin_username, "admin_password": admin_password},
    )

    assert_success(response)
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(name="Spaced School")) == 0
    assert db_session.scalar(select(func.count()).select_from(SchoolAdmin)) == 0


def test_a_school_needs_a_name(client, db_session, authenticated_admin):
    from models import School

    response = client.post("/admin/schools/new", data={"name": "   "})

    assert_success(response)
    assert db_session.scalar(select(func.count()).select_from(School)) == 0


def test_a_duplicate_school_name_is_refused(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="Only One")

    assert_success(client.post("/admin/schools/new", data={"name": "Only One"}))
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(name="Only One")) == 1


def test_a_duplicate_admin_username_is_refused(client, db_session, authenticated_admin):
    from models import School

    make_school(db_session, name="First")
    client.post(
        "/admin/schools/new",
        data={"name": "Second", "admin_username": "dup", "admin_password": "Password1!"},
    )

    response = client.post(
        "/admin/schools/new",
        data={"name": "Third", "admin_username": "dup", "admin_password": "Password1!"},
    )

    assert_success(response)
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(name="Third")) == 0


def test_a_school_admin_username_already_used_by_a_learner_is_refused(client, db_session, authenticated_admin):
    from models import School

    learner = make_learner(db_session, make_school(db_session))

    response = client.post(
        "/admin/schools/new",
        data={"name": "Clash", "admin_username": learner.username, "admin_password": "Password1!"},
    )

    assert_success(response)
    assert db_session.scalar(select(func.count()).select_from(School).filter_by(name="Clash")) == 0


def test_deleting_a_school_keeps_its_donations_unlinked(client, db_session, authenticated_admin):
    from models import Donation
    from tests.support.factories import make_donation

    school = make_school(db_session)
    donation = make_donation(db_session, school=school)

    client.post(f"/admin/schools/{school.id}/delete")

    db_session.expire_all()
    kept = db_session.get(Donation, donation.id)
    assert kept is not None and kept.school_id is None


def test_deleting_a_teacher_keeps_their_rosters_attendance(client, db_session, authenticated_admin):
    from models import Attendance, Teacher
    from tests.support.factories import make_attendance

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    make_attendance(db_session, teacher, learner)

    client.post(f"/admin/users/{teacher.id}/delete")

    db_session.expire_all()
    assert db_session.get(Teacher, teacher.id) is None
    assert db_session.scalars(select(Attendance.teacher_id)).all() == [None]


def test_deleting_an_administrator_hands_their_articles_to_the_one_deleting(client, db_session, authenticated_admin):
    from models import Article
    from tests.support.factories import make_admin, make_article

    other = make_admin(db_session)
    make_article(db_session, other)
    acting_admin_id = authenticated_admin.id

    client.post(f"/admin/users/{other.id}/delete")

    db_session.expire_all()
    assert db_session.scalars(select(Article.author_id)).all() == [acting_admin_id]


def test_deleting_a_school_removes_it(client, db_session, authenticated_admin):
    from models import School

    school = make_school(db_session)

    client.post(f"/admin/schools/{school.id}/delete")

    assert db_session.get(School, school.id) is None


# ── users ────────────────────────────────────────────────────────────────────


def test_the_user_list_shows_every_role(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school, name="Ms Okafor")
    make_learner(db_session, school, teacher, name="Ada")
    make_volunteer(db_session, school, teacher, name="Bo")

    body = assert_success(client.get("/admin/users")).get_data(as_text=True)

    for name in ("Ms Okafor", "Ada", "Bo"):
        assert name in body


def test_deleting_a_learner_removes_the_row(client, db_session, authenticated_admin):
    from models import Learner

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)

    client.post(f"/admin/users/{learner.id}/delete")

    assert db_session.get(Learner, learner.id) is None


def test_deleting_a_user_can_answer_json(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)

    response = client.post(
        f"/admin/users/{learner.id}/delete",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert_success(response)
    assert response.get_json()["success"] is True


# ── impersonation ────────────────────────────────────────────────────────────


def test_an_administrator_can_impersonate_a_learner(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)

    response = client.post(f"/admin/impersonate/{learner.id}")

    assert_redirects_to(response, "/learner/")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(learner.id)
        assert session["impersonating_admin_id"] == authenticated_admin.id


def test_one_administrator_cannot_impersonate_another(client, db_session, authenticated_admin):
    from tests.support.factories import make_admin

    other = make_admin(db_session)

    response = client.post(f"/admin/impersonate/{other.id}")

    assert_redirects_to(response, "/admin/users")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(authenticated_admin.id)


def test_stopping_impersonation_restores_the_administrator(client, db_session, authenticated_admin):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    admin_id = authenticated_admin.id
    client.post(f"/admin/impersonate/{learner.id}")

    response = client.get("/admin/impersonate/stop")

    assert_redirects_to(response, "/admin/dashboard")
    with client.session_transaction() as session:
        assert session["_user_id"] == str(admin_id)
        assert "impersonating_admin_id" not in session


# ── site content ─────────────────────────────────────────────────────────────


def test_settings_write_site_content(client, db_session, authenticated_admin):
    from models import SiteContent

    client.post("/admin/settings", data={"hero_title": "Learn together"})

    assert db_session.scalars(select(SiteContent).filter_by(key="hero_title")).one().value == "Learn together"


def test_settings_update_existing_site_content(client, db_session, authenticated_admin):
    from models import SiteContent

    make_site_content(db_session, key="hero_title", value="Old")

    client.post("/admin/settings", data={"hero_title": "New"})

    assert db_session.scalars(select(SiteContent).filter_by(key="hero_title")).one().value == "New"


# ── team members ─────────────────────────────────────────────────────────────


def test_a_team_member_can_be_created(client, db_session, authenticated_admin):
    from models import TeamMember

    response = client.post(
        "/admin/team/new", data={"name": "Sam", "job": "Coordinator", "bio": "Hi"}
    )

    assert response.status_code in {200, 302}
    assert db_session.scalar(select(func.count()).select_from(TeamMember).filter_by(name="Sam")) == 1


def test_a_team_member_can_be_edited(client, db_session, authenticated_admin):
    from models import TeamMember

    member = make_team_member(db_session, name="Before")

    client.post(f"/admin/team/edit/{member.id}", data={"name": "After", "job": "Lead"})

    db_session.expire_all()
    assert db_session.get(TeamMember, member.id).name == "After"


def test_a_team_member_can_be_deleted(client, db_session, authenticated_admin):
    from models import TeamMember

    member = make_team_member(db_session)

    client.post(f"/admin/team/delete/{member.id}")

    assert db_session.get(TeamMember, member.id) is None


def test_the_team_edit_page_renders(client, db_session, authenticated_admin):
    member = make_team_member(db_session)

    assert_success(client.get(f"/admin/team/edit/{member.id}"))


# ── articles ─────────────────────────────────────────────────────────────────


def test_an_article_can_be_created(client, db_session, authenticated_admin):
    from models import Article

    response = client.post(
        "/admin/articles/new",
        data={"title": "News", "content": "# Hello"},
    )

    assert response.status_code in {200, 302}
    assert db_session.scalar(select(func.count()).select_from(Article).filter_by(title="News")) == 1


def test_an_article_can_be_edited(client, db_session, authenticated_admin):
    from models import Article

    article = make_article(db_session, authenticated_admin, title="Before")

    client.post(
        f"/admin/articles/edit/{article.id}",
        data={"title": "After", "content": "# Changed"},
    )

    db_session.expire_all()
    assert db_session.get(Article, article.id).title == "After"


def test_an_article_can_be_deleted(client, db_session, authenticated_admin):
    from models import Article

    article = make_article(db_session, authenticated_admin)

    client.post(f"/admin/articles/delete/{article.id}")

    assert db_session.get(Article, article.id) is None


def test_the_article_edit_page_renders(client, db_session, authenticated_admin):
    article = make_article(db_session, authenticated_admin)

    assert_success(client.get(f"/admin/articles/edit/{article.id}"))


# ── article hero images ──────────────────────────────────────────────────────

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _hero_storage(monkeypatch):
    from routes.administrator import cms
    from tests.support.storage import use_fake_storage

    return use_fake_storage(monkeypatch, targets=(cms,))


def test_an_article_can_be_created_with_a_hero_image(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)

    client.post(
        "/admin/articles/new",
        data={"title": "With Hero", "content": "# Hi", "hero_image": (io.BytesIO(PNG_BYTES), "photo.png")},
        content_type="multipart/form-data",
    )

    article = db_session.scalar(select(Article).filter_by(title="With Hero"))
    assert article.hero_image.endswith(".png")
    assert storage.under("images/")[article.hero_image] == PNG_BYTES


def test_editing_without_a_new_file_keeps_the_hero_image(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)
    storage.write("images/" + "a" * 32 + ".png", PNG_BYTES, "image/png")
    article = make_article(db_session, authenticated_admin, hero_image="a" * 32 + ".png")

    client.post(f"/admin/articles/edit/{article.id}", data={"title": "T", "content": "C"})

    db_session.expire_all()
    assert db_session.get(Article, article.id).hero_image == "a" * 32 + ".png"
    assert "a" * 32 + ".png" in storage.under("images/")


def test_uploading_a_new_hero_image_replaces_and_deletes_the_old_one(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)
    storage.write("images/" + "a" * 32 + ".png", PNG_BYTES, "image/png")
    article = make_article(db_session, authenticated_admin, hero_image="a" * 32 + ".png")

    client.post(
        f"/admin/articles/edit/{article.id}",
        data={"title": "T", "content": "C", "hero_image": (io.BytesIO(JPEG_BYTES), "new.jpg")},
        content_type="multipart/form-data",
    )

    db_session.expire_all()
    new_name = db_session.get(Article, article.id).hero_image
    assert new_name.endswith(".jpg")
    assert storage.under("images/")[new_name] == JPEG_BYTES
    assert "a" * 32 + ".png" not in storage.under("images/")


def test_a_hero_image_can_be_removed(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)
    storage.write("images/" + "a" * 32 + ".png", PNG_BYTES, "image/png")
    article = make_article(db_session, authenticated_admin, hero_image="a" * 32 + ".png")

    client.post(f"/admin/articles/edit/{article.id}", data={"title": "T", "content": "C", "remove_hero_image": "1"})

    db_session.expire_all()
    assert db_session.get(Article, article.id).hero_image is None
    assert storage.under("images/") == {}


def test_a_file_that_is_not_an_image_is_rejected(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)

    response = client.post(
        "/admin/articles/new",
        data={"title": "Bad", "content": "C", "hero_image": (io.BytesIO(b"%PDF-1.4 not an image"), "fake.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "PNG, JPEG, WebP or GIF" in response.get_data(as_text=True)
    assert db_session.scalar(select(func.count()).select_from(Article).filter_by(title="Bad")) == 0
    assert storage.under("images/") == {}


def test_a_hero_image_over_five_megabytes_is_rejected(client, db_session, authenticated_admin, monkeypatch):
    from models import Article

    storage = _hero_storage(monkeypatch)
    article = make_article(db_session, authenticated_admin)
    big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024)

    response = client.post(
        f"/admin/articles/edit/{article.id}",
        data={"title": "T", "content": "C", "hero_image": (io.BytesIO(big), "big.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(Article, article.id).hero_image is None
    assert storage.under("images/") == {}


def test_the_article_form_accepts_a_hero_image_upload(client, db_session, authenticated_admin):
    body = assert_success(client.get("/admin/articles/new")).get_data(as_text=True)

    assert 'enctype="multipart/form-data"' in body
    assert 'name="hero_image"' in body
