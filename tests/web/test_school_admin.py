"""School-admin routes.

Every page is scoped to `current_user.school`, so each read has a matching
"another school's row is a 404" test — that scoping is the whole security model
of this blueprint.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.factories import (
    make_attendance,
    make_donation,
    make_learner,
    make_school,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web

AJAX = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def campus(db_session, authenticated_school_admin):
    """The signed-in admin's school, populated, plus a rival school."""

    school = authenticated_school_admin.school
    teacher = make_teacher(db_session, school, name="Ms Okafor")
    learner = make_learner(db_session, school, teacher, name="Ada")
    volunteer = make_volunteer(db_session, school, teacher, name="Bo")

    rival = make_school(db_session, name="Rival School")
    rival_teacher = make_teacher(db_session, rival, name="Mr Elsewhere")
    rival_learner = make_learner(db_session, rival, rival_teacher, name="Outsider")
    rival_volunteer = make_volunteer(db_session, rival, rival_teacher, name="Stranger")

    return {
        "school": school,
        "teacher": teacher,
        "learner": learner,
        "volunteer": volunteer,
        "rival": rival,
        "rival_teacher": rival_teacher,
        "rival_learner": rival_learner,
        "rival_volunteer": rival_volunteer,
    }


# ── pages render ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/school/", "/school/people", "/school/donations", "/school/settings", "/school/attendance"],
)
def test_school_pages_render_for_a_school_admin(client, db_session, campus, path):
    assert_success(client.get(path))


def test_a_teacher_cannot_read_the_school_dashboard(client, db_session, authenticated_teacher):
    assert client.get("/school/").status_code == 403


def test_the_dashboard_reports_the_schools_own_totals(client, db_session, campus):
    make_attendance(db_session, campus["teacher"], campus["learner"], duration=2.0)

    body = assert_success(client.get("/school/")).get_data(as_text=True)

    assert campus["school"].name in body


def test_the_people_page_lists_only_this_school(client, db_session, campus):
    body = assert_success(client.get("/school/people")).get_data(as_text=True)

    assert "Ada" in body
    assert "Bo" in body
    assert "Ms Okafor" in body
    assert "Outsider" not in body
    assert "Stranger" not in body


def test_the_learner_table_pages_independently_of_the_other_two(client, db_session, campus):
    school = campus["school"]
    teacher = campus["teacher"]
    for i in range(30):
        make_learner(db_session, school, teacher, username=f"learner{i:02d}")

    page1 = assert_success(client.get("/school/people")).get_data(as_text=True)
    page2 = assert_success(client.get("/school/people?learner_page=2")).get_data(as_text=True)

    assert "learner29" in page1
    assert "learner04" in page2 and "learner29" not in page2
    # Paging the learner table doesn't drop this page's teacher/volunteer rows.
    assert "Ms Okafor" in page2
    assert "Bo" in page2


def test_paging_one_table_preserves_the_other_tables_current_page(client, db_session, campus):
    school = campus["school"]
    teacher = campus["teacher"]
    for i in range(30):
        make_learner(db_session, school, teacher, username=f"learner{i:02d}")
        make_volunteer(db_session, school, teacher, name=f"Volunteer {i:02d}")

    # On learner page 2, hop the volunteer table to its own page 2 — the
    # learner_page arg must survive that hop (docs/ui-design/page-behaviour.md's args trap).
    body = assert_success(
        client.get("/school/people?learner_page=2&volunteer_page=2")
    ).get_data(as_text=True)

    assert "learner04" in body
    assert "Volunteer 04" in body


# ── person detail is school-scoped ───────────────────────────────────────────


def test_a_teacher_detail_page_renders(client, db_session, campus):
    body = assert_success(
        client.get(f"/school/people/teachers/{campus['teacher'].id}")
    ).get_data(as_text=True)

    assert "Ms Okafor" in body


def test_a_learner_detail_page_renders(client, db_session, campus):
    worksheet = make_worksheet(db_session)
    make_worksheet_assignment(db_session, campus["teacher"], campus["learner"], worksheet)

    body = assert_success(
        client.get(f"/school/people/learners/{campus['learner'].id}")
    ).get_data(as_text=True)

    assert "Ada" in body


def test_a_volunteer_detail_page_renders(client, db_session, campus):
    make_attendance(db_session, campus["teacher"], campus["volunteer"], duration=1.0)

    body = assert_success(
        client.get(f"/school/people/volunteers/{campus['volunteer'].id}")
    ).get_data(as_text=True)

    assert "Bo" in body


@pytest.mark.parametrize(
    ("path", "markers"),
    [
        ("/school/", [
            "Quick Actions", "Recent Donations", "Kind Donor",
            'href="/school/people"', 'href="/school/attendance"',
            'href="/school/donations"', 'href="/school/settings"',
        ]),
        ("/school/settings", [
            "School Identity", "Email Domain Mapping", 'action="/school/settings"',
            'name="mission_statement"', 'name="volunteer_domain"', 'name="teacher_domain"',
            'value="mine.example.com"', ">Learn together</textarea>", 'type="submit"',
        ]),
        ("/school/people/learners/{learner}", [
            "Reset Password", 'href="/school/people"', 'id="set-password-form"', "js-ajax-form",
            'action="/school/people/learners/{learner}/set-password"', 'name="password"',
            'action="/school/people/learners/{learner}/delete"', "data-confirm=",
        ]),
        ("/school/people/teachers/{teacher}", [
            "Attendance Records", 'href="/school/people"', "Ms Okafor",
        ]),
        ("/school/people/volunteers/{volunteer}", [
            "Matched Learner", 'href="/school/people"', 'href="/school/people/learners/{learner}"',
            'action="/school/people/volunteers/{volunteer}/delete"', "data-confirm=",
        ]),
    ],
)
def test_each_school_page_renders_its_headings_links_and_forms(client, db_session, campus, path, markers):
    school, learner, volunteer = campus["school"], campus["learner"], campus["volunteer"]
    school.mission_statement = "Learn together"
    school.volunteer_domain = "mine.example.com"
    volunteer.learner_matches.append(learner)
    db_session.commit()
    make_donation(db_session, school=school, donor_name="Kind Donor")
    ids = {"learner": learner.id, "teacher": campus["teacher"].id, "volunteer": volunteer.id}

    body = assert_success(client.get(path.format(**ids))).get_data(as_text=True)

    for marker in markers:
        assert marker.format(**ids) in body


@pytest.mark.parametrize(
    "template,key",
    [
        ("/school/people/teachers/{}", "rival_teacher"),
        ("/school/people/learners/{}", "rival_learner"),
        ("/school/people/volunteers/{}", "rival_volunteer"),
    ],
)
def test_another_schools_person_is_a_404(client, db_session, campus, template, key):
    response = client.get(template.format(campus[key].id))

    assert response.status_code == 404


def test_an_unknown_learner_is_a_404(client, db_session, campus):
    assert client.get("/school/people/learners/999999").status_code == 404


# ── teacher hours are learner-scoped ─────────────────────────────────────────


def test_teacher_hours_count_learner_rows_only(client, db_session, campus):
    """A pair holds two rows for one session; only the learner's is counted."""

    teacher, learner, volunteer = campus["teacher"], campus["learner"], campus["volunteer"]
    make_attendance(db_session, teacher, learner, partner=volunteer, duration=2.0)
    make_attendance(db_session, teacher, volunteer, partner=learner, duration=2.0)

    body = assert_success(
        client.get(f"/school/people/teachers/{teacher.id}")
    ).get_data(as_text=True)

    assert "4.0" not in body


# ── deletions ────────────────────────────────────────────────────────────────


def test_a_learner_can_be_deleted(client, db_session, campus):
    from models import Learner

    learner_id = campus["learner"].id

    response = client.post(f"/school/people/learners/{learner_id}/delete")

    assert_redirects_to(response, "/school/people")
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=learner_id)) == 0


def test_another_schools_learner_cannot_be_deleted(client, db_session, campus):
    from models import Learner

    outsider_id = campus["rival_learner"].id

    assert client.post(f"/school/people/learners/{outsider_id}/delete").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=outsider_id)) == 1


def test_a_volunteer_can_be_deleted(client, db_session, campus):
    from models import Volunteer

    volunteer_id = campus["volunteer"].id

    client.post(f"/school/people/volunteers/{volunteer_id}/delete")

    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(id=volunteer_id)) == 0


def test_another_schools_volunteer_cannot_be_deleted(client, db_session, campus):
    from models import Volunteer

    outsider_id = campus["rival_volunteer"].id

    assert client.post(f"/school/people/volunteers/{outsider_id}/delete").status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(id=outsider_id)) == 1


# ── passwords ────────────────────────────────────────────────────────────────


def test_a_learner_password_can_be_reset(client, db_session, campus):
    client.post(
        f"/school/people/learners/{campus['learner'].id}/set-password",
        data={"password": "BrandNew1!"},
    )

    db_session.expire_all()
    assert campus["learner"].check_password("BrandNew1!")


def test_a_reset_password_is_stored_without_surrounding_spaces(client, db_session, campus):
    client.post(
        f"/school/people/learners/{campus['learner'].id}/set-password",
        data={"password": " BrandNew1! "},
    )

    db_session.expire_all()
    assert campus["learner"].check_password("BrandNew1!")


def test_a_reset_password_with_a_space_inside_is_refused(client, db_session, campus):
    response = client.post(
        f"/school/people/learners/{campus['learner'].id}/set-password",
        data={"password": "Brand New1!"},
        headers=AJAX,
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False
    db_session.expire_all()
    assert not campus["learner"].check_password("Brand New1!")


def test_an_empty_password_is_refused(client, db_session, campus):
    response = client.post(
        f"/school/people/learners/{campus['learner'].id}/set-password",
        data={"password": "   "},
        headers=AJAX,
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_a_password_reset_can_answer_json(client, db_session, campus):
    response = assert_success(
        client.post(
            f"/school/people/learners/{campus['learner'].id}/set-password",
            data={"password": "BrandNew1!"},
            headers=AJAX,
        )
    )

    assert response.get_json()["success"] is True


def test_another_schools_learner_password_cannot_be_reset(client, db_session, campus):
    response = client.post(
        f"/school/people/learners/{campus['rival_learner'].id}/set-password",
        data={"password": "x"},
    )

    assert response.status_code == 404


# ── donations and attendance ─────────────────────────────────────────────────


def test_donations_are_scoped_to_the_school(client, db_session, campus):
    make_donation(db_session, school=campus["school"], donor_name="Local Giver")
    make_donation(db_session, school=campus["rival"], donor_name="Rival Giver")

    body = assert_success(client.get("/school/donations")).get_data(as_text=True)

    assert "Local Giver" in body
    assert "Rival Giver" not in body


def test_attendance_is_scoped_to_the_schools_learners(client, db_session, campus):
    make_attendance(db_session, campus["teacher"], campus["learner"], duration=2.0)
    make_attendance(
        db_session, campus["rival_teacher"], campus["rival_learner"], duration=7.0
    )

    body = assert_success(client.get("/school/attendance")).get_data(as_text=True)

    assert "Ada" in body
    assert "Outsider" not in body


def test_the_donations_ledger_pages_and_totals_the_whole_school(client, db_session, campus):
    for _ in range(30):
        make_donation(db_session, school=campus["school"], amount=1_000)

    page1 = assert_success(client.get("/school/donations")).get_data(as_text=True)
    page2 = assert_success(client.get("/school/donations?page=2")).get_data(as_text=True)

    assert "page=2" in page1
    # Separate aggregate query, not a Python sum over the page's own rows —
    # identical on page 1 and page 2.
    assert "$300.00" in page1  # total across all 30, not just the 25 shown
    assert "$300.00" in page2
    assert "30" in page1
    assert "30" in page2


def test_the_attendance_ledger_pages_and_totals_the_whole_school(client, db_session, campus):
    for i in range(30):
        make_attendance(db_session, campus["teacher"], campus["learner"], duration=2.0, notes=f"session {i}")

    page1 = assert_success(client.get("/school/attendance")).get_data(as_text=True)
    page2 = assert_success(client.get("/school/attendance?page=2")).get_data(as_text=True)

    assert "page=2" in page1
    # Separate aggregate query, not a Python sum over the page's own rows —
    # identical on page 1 and page 2.
    assert "60.0" in page1  # total hours across all 30 sessions, not just the page
    assert "60.0" in page2
    assert "30" in page1
    assert "30" in page2


def test_attendance_can_be_filtered_to_one_teacher_for_the_detail_preview(client, db_session, campus):
    make_attendance(db_session, campus["teacher"], campus["learner"], duration=2.0)
    make_attendance(db_session, campus["rival_teacher"], campus["rival_learner"], duration=7.0)

    body = assert_success(
        client.get(f"/school/attendance?teacher={campus['teacher'].id}")
    ).get_data(as_text=True)

    assert "Ada" in body
    assert "Outsider" not in body


def test_the_teacher_filter_survives_a_page_hop_on_attendance(client, db_session, campus):
    for i in range(30):
        make_attendance(db_session, campus["teacher"], campus["learner"], duration=1.0, notes=f"s{i}")
    make_attendance(db_session, campus["rival_teacher"], campus["rival_learner"], duration=99.0, notes="rival")

    page2 = assert_success(
        client.get(f"/school/attendance?teacher={campus['teacher'].id}&page=2")
    ).get_data(as_text=True)

    assert "Outsider" not in page2
    assert f"teacher={campus['teacher'].id}" in page2


def test_a_teacher_detail_page_previews_and_links_to_the_full_ledger(client, db_session, campus):
    teacher = campus["teacher"]
    for i in range(10):
        make_attendance(db_session, teacher, campus["learner"], duration=1.0, notes=f"s{i}")

    body = assert_success(
        client.get(f"/school/people/teachers/{teacher.id}")
    ).get_data(as_text=True)

    assert f"teacher={teacher.id}" in body
    assert "10" in body  # full session count, not the 7-row preview

    linked = assert_success(
        client.get(f"/school/attendance?teacher={teacher.id}")
    ).get_data(as_text=True)
    assert "10" in linked  # the link actually returns all 10 previewed sessions


def test_a_volunteer_detail_page_previews_and_links_to_the_full_ledger(client, db_session, campus):
    """The preview counts the volunteer's own records; the linked ledger
    filters the matching learner-side records instead (same asymmetry as
    `teacher_volunteer_detail`) — a realistic pairing writes both sides of
    each session, so the two counts still agree here."""
    volunteer = campus["volunteer"]
    learner = campus["learner"]
    for i in range(10):
        make_attendance(db_session, campus["teacher"], volunteer, partner=learner, duration=1.0, notes=f"v{i}")
        make_attendance(db_session, campus["teacher"], learner, partner=volunteer, duration=1.0, notes=f"l{i}")

    body = assert_success(
        client.get(f"/school/people/volunteers/{volunteer.id}")
    ).get_data(as_text=True)

    assert f"volunteer={volunteer.id}" in body
    assert "10" in body

    linked = assert_success(
        client.get(f"/school/attendance?volunteer={volunteer.id}")
    ).get_data(as_text=True)
    assert "10" in linked


def test_a_learner_detail_page_previews_and_links_to_the_full_ledger(client, db_session, campus):
    learner = campus["learner"]
    for i in range(10):
        make_attendance(db_session, campus["teacher"], learner, duration=1.0, notes=f"s{i}")

    body = assert_success(
        client.get(f"/school/people/learners/{learner.id}")
    ).get_data(as_text=True)

    assert f"learner={learner.id}" in body
    assert "10" in body

    linked = assert_success(
        client.get(f"/school/attendance?learner={learner.id}")
    ).get_data(as_text=True)
    assert "10" in linked


# ── settings ─────────────────────────────────────────────────────────────────


def test_settings_can_be_saved(client, db_session, campus):
    response = client.post(
        "/school/settings",
        data={
            "mission_statement": "Learn together",
            "volunteer_domain": "Volunteers.Example.COM",
            "teacher_domain": "staff.example.com",
        },
    )

    assert_redirects_to(response, "/school/settings")
    db_session.expire_all()
    assert campus["school"].mission_statement == "Learn together"
    # Domains are normalized to lowercase so matching a sign-in address works.
    assert campus["school"].volunteer_domain == "volunteers.example.com"


def test_blank_settings_are_stored_as_empty_rather_than_whitespace(client, db_session, campus):
    client.post(
        "/school/settings",
        data={"mission_statement": "   ", "volunteer_domain": "  ", "teacher_domain": ""},
    )

    db_session.expire_all()
    assert campus["school"].mission_statement is None
    assert campus["school"].volunteer_domain is None


def test_a_volunteer_domain_claimed_by_another_school_is_refused(client, db_session, campus):
    campus["rival"].volunteer_domain = "taken.example.com"
    db_session.commit()

    response = client.post(
        "/school/settings", data={"volunteer_domain": "taken.example.com"}
    )

    assert_success(response)
    db_session.expire_all()
    assert campus["school"].volunteer_domain != "taken.example.com"


def test_a_teacher_domain_claimed_by_another_school_is_refused(client, db_session, campus):
    campus["rival"].teacher_domain = "staff.taken.com"
    db_session.commit()

    response = client.post("/school/settings", data={"teacher_domain": "staff.taken.com"})

    assert_success(response)
    db_session.expire_all()
    assert campus["school"].teacher_domain != "staff.taken.com"


def test_a_school_may_keep_its_own_domain_on_resave(client, db_session, campus):
    """The uniqueness check must exclude the school doing the saving."""

    campus["school"].volunteer_domain = "mine.example.com"
    db_session.commit()

    client.post("/school/settings", data={"volunteer_domain": "mine.example.com"})

    db_session.expire_all()
    assert campus["school"].volunteer_domain == "mine.example.com"


@pytest.mark.parametrize("path", ["/school/", "/school/people", "/school/attendance", "/school/donations", "/school/settings"])
def test_every_nav_link_to_the_current_page_is_marked_active(client, db_session, campus, path):
    """The desktop bar and the mobile menu both link each page; both must show it as current."""
    from tests.support.html import parse

    page = parse(assert_success(client.get(path)).get_data(as_text=True))
    to_here = [a for a in page.find_all("a") if a.attrs.get("href") == path]
    bar = next(a for a in to_here if "data-label" in a.attrs)
    menu = next(a for a in to_here if "py-3" in a.classes)

    assert "nav-link-active" in bar.classes
    assert "bg-sky-100" in menu.classes
