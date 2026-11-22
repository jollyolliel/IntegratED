"""Volunteer routes: dashboard, partner view, resources, onboarding survey."""

from __future__ import annotations

import re

import pytest

from tests.support.assertions import assert_redirects_to, assert_success
from tests.support.auth import login_as
from tests.support.factories import (
    make_learner,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web


@pytest.fixture
def partnered(db_session, authenticated_volunteer):
    """The signed-in volunteer with one matched learner."""

    volunteer = authenticated_volunteer
    school = volunteer.school
    teacher = volunteer.teacher or make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher, name="Ada")
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()
    return {"volunteer": volunteer, "school": school, "teacher": teacher, "learner": learner}


# ── pages render ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/volunteer/", "/volunteer/my-partner", "/volunteer/profile", "/volunteer/resources"],
)
def test_volunteer_pages_render_for_the_authenticated_role(client, db_session, authenticated_volunteer, path):
    assert_success(client.get(path))


@pytest.mark.parametrize(
    ("path", "markers"),
    [
        ("/volunteer/", [
            "Dashboard Overview", "Quick Actions", "No Active Partnership Yet",
            'href="/volunteer/resources"', 'href="/volunteer/profile"',
        ]),
        ("/volunteer/my-partner", ["My Learning Partner", "No Partner Assigned", 'href="/volunteer/"']),
        ("/volunteer/profile", [
            "My Profile", "Basic Information", "Partnership Status", 'href="/volunteer/"', 'href="/volunteer/survey"',
        ]),
        ("/volunteer/survey", [
            "Survey already completed", 'id="surveyForm"', 'action="/volunteer/survey"',
            'name="name"', 'name="age"', 'name="motivation"', 'name="personality"', 'name="traits"',
            'name="hobbies"', 'name="languages"', 'name="language_level_English"', 'name="tech_interest"',
            'name="match_activities"', 'class="lang-check"', 'id="lang-none-volunteer"',
            'id="error-motivation"', 'id="error-personality"', 'id="error-languages"', 'type="submit"',
        ]),
    ],
)
def test_each_volunteer_page_renders_its_heading_and_markers(client, db_session, authenticated_volunteer, path, markers):
    body = assert_success(client.get(path)).get_data(as_text=True)

    for marker in markers:
        assert marker in body


def test_the_dashboard_links_each_partner_and_the_partner_page(client, db_session, partnered):
    learner = partnered["learner"]

    body = assert_success(client.get("/volunteer/")).get_data(as_text=True)

    assert 'href="/volunteer/my-partner"' in body
    assert f'href="/volunteer/my-partner?learner={learner.id}"' in body
    assert "Your Learning Partner" in body


def test_the_partner_page_offers_a_switcher_for_several_partners(client, db_session, partnered):
    volunteer = partnered["volunteer"]
    volunteer.match_capacity = 2
    second = make_learner(db_session, partnered["school"], partnered["teacher"], name="Cy")
    second.volunteer_id = volunteer.id
    second.is_matched = True
    db_session.commit()

    body = assert_success(client.get("/volunteer/my-partner")).get_data(as_text=True)

    assert "Switch partner" in body
    assert f'href="/volunteer/my-partner?learner={partnered["learner"].id}"' in body
    assert f'href="/volunteer/my-partner?learner={second.id}"' in body


def test_the_profile_lists_the_survey_answers(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(
        db_session,
        school,
        teacher,
        survey_data={"age": "17", "personality": "Kind & Supportive", "traits": ["Patient"], "hobbies": ["Music"],
                     "languages": [{"language": "Greek", "level": "Advanced"}], "match_activities": ["Storytelling"]},
    )
    login_as(client, fresh)

    body = assert_success(client.get("/volunteer/profile")).get_data(as_text=True)

    for answer in ["Kind &amp; Supportive", "Patient", "Music", "Greek", "Advanced", "Storytelling"]:
        assert answer in body


def test_a_new_volunteer_sees_the_survey_step_and_an_editable_name(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    body = assert_success(client.get("/volunteer/survey")).get_data(as_text=True)

    assert "Step 2 of 2" in body
    assert "Tell us about yourself" in body
    assert re.search(r'name="name"[^>]*\brequired\b', body)


def test_the_redo_survey_locks_the_name_to_the_saved_one(client, db_session, authenticated_volunteer):
    body = assert_success(client.get("/volunteer/survey")).get_data(as_text=True)

    name_input = re.search(r'<input[^>]*name="name"[^>]*>', body)
    assert name_input is not None
    assert f'value="{authenticated_volunteer.name}"' in name_input.group()
    assert "readonly" in name_input.group()


def test_the_redo_survey_checks_each_saved_language_and_its_level(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(
        db_session, school, teacher, survey_data={"languages": [{"language": "Greek", "level": "Advanced"}]},
    )
    login_as(client, fresh)

    body = assert_success(client.get("/volunteer/survey")).get_data(as_text=True)

    greek = re.search(r'<input[^>]*value="Greek"[^>]*>', body)
    advanced = re.search(r'<input[^>]*name="language_level_Greek"[^>]*value="Advanced"[^>]*>', body)
    beginner = re.search(r'<input[^>]*name="language_level_Greek"[^>]*value="Beginner"[^>]*>', body)
    assert greek is not None and "checked" in greek.group()
    assert advanced is not None and "checked" in advanced.group()
    assert beginner is not None and "disabled" in beginner.group()


def test_a_learner_cannot_reach_the_volunteer_area(client, db_session, authenticated_learner):
    assert client.get("/volunteer/").status_code == 403


def test_the_dashboard_names_the_matched_partner(client, db_session, partnered):
    body = assert_success(client.get("/volunteer/")).get_data(as_text=True)

    assert "Ada" in body


def test_the_partner_page_renders_with_no_partner(client, db_session, authenticated_volunteer):
    """An unmatched volunteer still gets a page, not a crash."""

    assert_success(client.get("/volunteer/my-partner"))


def test_the_partner_page_shows_the_matched_learner(client, db_session, partnered):
    body = assert_success(client.get("/volunteer/my-partner")).get_data(as_text=True)

    assert "Ada" in body


def test_the_partner_page_can_select_among_several_partners(client, db_session, partnered):
    volunteer = partnered["volunteer"]
    volunteer.match_capacity = 2
    second = make_learner(db_session, partnered["school"], partnered["teacher"], name="Cy")
    second.volunteer_id = volunteer.id
    second.is_matched = True
    db_session.commit()

    body = assert_success(
        client.get(f"/volunteer/my-partner?learner={second.id}")
    ).get_data(as_text=True)

    assert "Cy" in body


def test_an_unknown_partner_selection_falls_back_to_the_first(client, db_session, partnered):
    body = assert_success(
        client.get("/volunteer/my-partner?learner=999999")
    ).get_data(as_text=True)

    assert "Ada" in body


def test_the_partner_page_lists_assigned_worksheets(client, db_session, partnered):
    worksheet = make_worksheet(db_session, title="Reading Practice")
    make_worksheet_assignment(
        db_session, partnered["teacher"], partnered["learner"], worksheet
    )

    body = assert_success(client.get("/volunteer/my-partner")).get_data(as_text=True)

    assert "Reading Practice" in body


# ── resources ────────────────────────────────────────────────────────────────


def test_the_resource_list_shows_worksheets(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Grammar Basics", subject="English Grammar")

    body = assert_success(client.get("/volunteer/resources")).get_data(as_text=True)

    assert "Grammar Basics" in body


def test_the_resource_list_accepts_a_subject_filter(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Grammar Basics", subject="English Grammar")

    assert_success(client.get("/volunteer/resources?subject=English Grammar"))


def test_the_subject_filter_narrows_the_resource_list(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Grammar Basics", subject="English Grammar")
    make_worksheet(db_session, title="Maths One", subject="Maths")

    body = assert_success(client.get("/volunteer/resources?subject=Maths")).get_data(as_text=True)

    assert "Maths One" in body
    assert "Grammar Basics" not in body


def test_the_subject_filter_survives_a_load_more_batch_on_the_resource_list(client, db_session, authenticated_volunteer):
    for i in range(30):
        make_worksheet(db_session, title=f"Grammar {i:02d}", subject="English Grammar")
    make_worksheet(db_session, title="Off Subject", subject="Maths")

    batch2 = assert_success(
        client.get("/volunteer/resources?subject=English Grammar&page=2", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Off Subject" not in batch2
    assert "Grammar 24" in batch2


def test_the_resource_list_load_more_batches_at_twenty_four_with_no_overlap(client, db_session, authenticated_volunteer):
    """First batch renders on the full page; the next batch is a fragment
    fetch (`X-Fragment: 1`) at WORKSHEETS_LIBRARY_PAGE_SIZE (24)."""
    for i in range(30):
        make_worksheet(db_session, title=f"Sheet {i:02d}")

    page1 = assert_success(client.get("/volunteer/resources")).get_data(as_text=True)
    batch2 = assert_success(
        client.get("/volunteer/resources?page=2", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    for i in range(24):
        assert f"Sheet {i:02d}" in page1
    assert "Sheet 24" not in page1
    for i in range(24, 30):
        assert f"Sheet {i:02d}" in batch2
    assert "Sheet 00" not in batch2


def test_a_resource_list_load_more_batch_past_the_end_is_empty_not_a_repeat_of_the_last_batch(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Been", subject="Sight Words")

    res = assert_success(client.get("/volunteer/resources?q=been&page=2", headers={"X-Fragment": "1"}))

    assert "Been" not in res.get_data(as_text=True)
    assert res.headers.get("X-Has-More") == "0"


def test_a_search_query_narrows_the_resource_list_server_side(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Fractions Practice", subject="Maths")
    make_worksheet(db_session, title="Grammar Basics", subject="English Grammar")

    body = assert_success(
        client.get("/volunteer/resources?q=Fractions", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Fractions Practice" in body
    assert "Grammar Basics" not in body


def test_a_worksheet_preview_renders(client, db_session, authenticated_volunteer):
    worksheet = make_worksheet(db_session, title="Previewable")

    body = assert_success(
        client.get(f"/volunteer/worksheets/{worksheet.id}")
    ).get_data(as_text=True)

    assert "Previewable" in body
    assert "Resource Details" in body
    assert 'href="/volunteer/resources"' in body


def test_a_pdf_worksheet_preview_frames_and_offers_its_file(client, db_session, authenticated_volunteer):
    worksheet = make_worksheet(db_session, title="Printable", file_type="pdf", filepath="sheets/printable.pdf")

    body = assert_success(
        client.get(f"/volunteer/worksheets/{worksheet.id}")
    ).get_data(as_text=True)

    assert f'src="/volunteer/worksheets/{worksheet.id}/file"' in body
    assert "Download PDF" in body


def test_an_unknown_worksheet_preview_is_a_404(client, db_session, authenticated_volunteer):
    assert client.get("/volunteer/worksheets/999999").status_code == 404


def test_a_markdown_worksheet_has_no_downloadable_file(client, db_session, authenticated_volunteer):
    worksheet = make_worksheet(db_session)

    assert client.get(f"/volunteer/worksheets/{worksheet.id}/file").status_code == 404


def test_a_pdf_worksheet_with_no_stored_path_is_a_404(client, db_session, authenticated_volunteer):
    worksheet = make_worksheet(db_session, file_type="pdf", filepath=None)

    assert client.get(f"/volunteer/worksheets/{worksheet.id}/file").status_code == 404


# ── onboarding survey ────────────────────────────────────────────────────────


def test_a_volunteer_who_finished_the_survey_can_still_reach_it_to_redo_it(client, db_session, authenticated_volunteer):
    assert_success(client.get("/volunteer/survey"))


def test_the_redo_survey_page_renders_when_survey_data_predates_the_field(client, db_session, school):
    """`scripts/flood.py` seeds volunteers with `completed_survey=True` and no
    `survey_data` at all — the redo page must not 500 on that combination."""
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=True, survey_data=None)
    login_as(client, fresh)

    assert_success(client.get("/volunteer/survey"))


def test_redoing_the_survey_keeps_the_volunteers_existing_name_rather_than_the_submitted_one(
    client, db_session, authenticated_volunteer
):
    original_name = authenticated_volunteer.name

    client.post("/volunteer/survey", data={"name": "Somebody Else", "languages": ["Arabic"], "language_level_Arabic": "beginner"})

    db_session.expire_all()
    assert authenticated_volunteer.name == original_name


def test_the_redo_survey_page_autofills_past_trait_selections(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(
        db_session,
        school,
        teacher,
        completed_survey=True,
        survey_data={"traits": ["Patient"], "personality": None, "hobbies": [], "languages": [],
                     "tech_interest": [], "match_activities": [], "age": None},
    )
    login_as(client, fresh)

    body = assert_success(client.get("/volunteer/survey")).get_data(as_text=True)

    patient_checkbox = re.search(r'<input[^>]*name="traits"[^>]*value="Patient"[^>]*>', body)
    assert patient_checkbox is not None
    assert "checked" in patient_checkbox.group()


def test_an_unsurveyed_volunteer_is_sent_to_the_survey(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    assert_redirects_to(client.get("/volunteer/"), "/volunteer/survey")


def test_the_survey_page_renders_for_a_new_volunteer(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    assert_success(client.get("/volunteer/survey"))


def test_submitting_the_survey_records_the_answers(client, db_session, school):
    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    response = client.post(
        "/volunteer/survey",
        data={
            "name": "Bo Adeyemi",
            "age": "17",
            "personality": "calm",
            "traits": ["patient", "funny"],
            "hobbies": ["football"],
            "languages": ["Arabic", "None"],
            "language_level_Arabic": "fluent",
            "match_activities": ["reading"],
            "tech_interest": ["coding"],
        },
    )

    assert_redirects_to(response, "/volunteer/")
    db_session.expire_all()
    assert fresh.completed_survey is True
    assert fresh.name == "Bo Adeyemi"
    assert fresh.survey_data["traits"] == ["patient", "funny"]


def test_the_none_language_option_is_not_recorded_as_a_language(client, db_session, school):
    """"None" is a UI choice, not a language the matcher should score on."""

    teacher = make_teacher(db_session, school)
    fresh = make_volunteer(db_session, school, teacher, completed_survey=False)
    login_as(client, fresh)

    client.post("/volunteer/survey", data={"name": "Bo", "languages": ["None"]})

    db_session.expire_all()
    assert fresh.survey_data["languages"] == []


def test_the_resource_list_filters_by_level(client, db_session, authenticated_volunteer):
    make_worksheet(db_session, title="Level Two Sheet", level=2)
    make_worksheet(db_session, title="Level Three Sheet", level=3)

    body = assert_success(
        client.get("/volunteer/resources?level=3", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Level Three Sheet" in body and "Level Two Sheet" not in body
