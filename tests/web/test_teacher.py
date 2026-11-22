"""Teacher routes: roster, people detail, worksheets, pairs, deletions."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_denied, assert_success
from tests.support.factories import (
    make_attendance,
    make_feature_announcement,
    make_learner,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web

#: Routes answer JSON only for the fetch()-based form handler, which is
#: identified by this header rather than by Accept.
AJAX = {"X-Requested-With": "XMLHttpRequest"}


# ── pages render ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/teacher/",
        "/teacher/people",
        "/teacher/attendance",
        "/teacher/attendance/history",
        "/teacher/worksheets",
        "/teacher/worksheets/assign",
    ],
)
def test_teacher_pages_render_for_the_authenticated_role(client, db_session, authenticated_teacher, path):
    assert_success(client.get(path))


@pytest.mark.parametrize(
    ("path", "markers"),
    [
        ("/teacher/", [
            "Dashboard Overview", "Teacher Portal", "Invite Code", "Quick Actions",
            'id="regen-invite-form"', 'action="/teacher/regenerate-invite"', "js-ajax-form",
            'id="invite-code-value"', 'href="/teacher/people"',
            'href="/teacher/attendance"', 'href="/teacher/worksheets"', 'href="/teacher/learners/{learner}"',
            "Ada &amp; Bo",
        ]),
        ("/teacher/attendance?date=2026-03-04", [
            "Take Attendance", 'href="/teacher/attendance/history"', 'id="sessionDate"', 'value="2026-03-04"',
            'id="defaultDuration"', 'id="rosterSearch"', 'id="markAllPresent"', 'id="markAllAbsent"',
            'id="clearAllMarks"', 'id="tallyPresent"', 'id="tallyHours"', 'id="rosterRoot"',
            "data-group-present", 'data-volunteer-mark="absent"', 'data-mark="present"',
            'data-learner-id="{learner}"', 'data-volunteer-id="{volunteer}"', 'id="rosterNoMatch"',
            'id="saveSummary"', 'id="saveAttendance"', 'href="/teacher/learners/{learner}"',
        ]),
        ("/teacher/learners/{learner}", [
            'href="/teacher/people"', "Current Progress", "Recommended Worksheets", "Account",
            'action="/teacher/pairs/{learner}/unmatch"', "data-confirm=", 'href="/teacher/volunteers/{volunteer}"',
            'action="/teacher/learners/{learner}/set-password"', 'id="learnerPassword"', 'name="password"',
            "js-ajax-form", 'action="/teacher/learners/{learner}/delete"', 'id="assignedWorksheets"',
            'action="/teacher/worksheet-assignments/{outstanding}/complete"',
            'action="/teacher/worksheet-assignments/{done}/reopen"',
            '/teacher/worksheet-assignments/print?ids={outstanding}&amp;source=learner_page_one',
            'href="/teacher/attendance/history?learner={learner}"',
        ]),
        ("/teacher/volunteers/{volunteer}", [
            'href="/teacher/people"', "Learner limit", 'action="/teacher/volunteers/{volunteer}/capacity"',
            'name="capacity"', "js-ajax-form", 'action="/teacher/volunteers/{volunteer}/delete"', "data-confirm=",
            'href="/teacher/learners/{learner}"', 'href="/teacher/attendance/history?volunteer={volunteer}"',
        ]),
        ("/teacher/worksheets/assign", [
            "Worksheet Packet Builder", 'href="/teacher/worksheets"', 'id="worksheet-packet-form"',
            'name="double_sided"', "Double-sided printing", 'data-pair-step="0"', 'data-learner-id="{learner}"',
            'data-selection-label', 'data-summary-label', '<option value="{worksheet}">', "Done, Generate PDF",
        ]),
        ("/teacher/worksheets/{worksheet}?learner_id={learner}", [
            "Previewable", 'href="/teacher/worksheets"', "Assign This Worksheet", 'id="assign-section"',
            'action="/teacher/worksheets/{worksheet}/assign"', 'name="learner_id"', 'value="{learner}"',
            'type="submit"', "English Grammar",
        ]),
    ],
)
def test_each_teacher_page_renders_its_headings_links_and_forms(client, db_session, pair, path, markers):
    teacher, learner, volunteer = pair["teacher"], pair["learner"], pair["volunteer"]
    worksheet = make_worksheet(db_session, title="Previewable")
    outstanding = make_worksheet_assignment(db_session, teacher, learner, worksheet, volunteer=volunteer)
    done = make_worksheet_assignment(db_session, teacher, learner, worksheet, volunteer=volunteer, completed=True)
    make_attendance(db_session, teacher, learner, partner=volunteer)
    make_attendance(db_session, teacher, volunteer, partner=learner)
    ids = {
        "learner": learner.id, "volunteer": volunteer.id, "worksheet": worksheet.id,
        "outstanding": outstanding.id, "done": done.id,
    }

    body = assert_success(client.get(path.format(**ids))).get_data(as_text=True)

    for marker in markers:
        assert marker.format(**ids) in body


def test_a_fully_recorded_day_shows_the_saved_card_instead_of_the_sheet(client, db_session, pair):
    make_attendance(db_session, pair["teacher"], pair["learner"], partner=pair["volunteer"],
                    date=datetime(2026, 3, 4, 12, tzinfo=UTC))

    body = assert_success(client.get("/teacher/attendance?date=2026-03-04")).get_data(as_text=True)

    assert "Attendance already saved" in body
    assert 'id="rosterRoot"' not in body


def test_an_empty_roster_shows_the_no_participants_message(client, db_session, authenticated_teacher):
    body = assert_success(client.get("/teacher/attendance")).get_data(as_text=True)

    assert "No learners assigned to you yet." in body
    assert 'id="saveAttendance"' not in body


def test_the_dashboard_shows_a_pending_feature_announcement(client, db_session, authenticated_teacher):
    make_feature_announcement(db_session, roles=["teacher"], title="Brand new register")

    body = assert_success(client.get("/teacher/")).get_data(as_text=True)

    assert "Brand new register" in body


def test_learner_cannot_read_teacher_roster(client, db_session, authenticated_learner):
    response = client.get("/teacher/people")

    assert response.status_code == 403


def test_the_roster_lists_the_teachers_own_people(client, db_session, pair):
    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert "Ada" in body
    assert "Bo" in body


def test_the_roster_bands_each_pair_for_the_connector_colour(client, db_session, pair):
    """The connector line is coloured client-side off the learner card's band."""
    pair["learner"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Beginner"}]}
    pair["volunteer"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Advanced"}]}
    db_session.commit()

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert 'data-pair-band="good"' in body


def test_an_unmatched_learner_card_carries_no_band(client, db_session, authenticated_teacher):
    make_learner(db_session, authenticated_teacher.school, authenticated_teacher, name="Solo")

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert 'data-pair-band=""' in body


def test_matched_volunteers_sort_above_unmatched_ones(client, db_session, pair):
    """An unmatched volunteer between two matched ones leaves a gap in the
    connector map, so matched volunteers come first and alphabetical order
    only breaks ties inside each group."""
    teacher = pair["teacher"]
    school = pair["school"]
    free = make_volunteer(db_session, school, teacher, name="Ana")
    second_matched = make_volunteer(db_session, school, teacher, name="Cy")
    learner = make_learner(db_session, school, teacher, name="Dee")
    learner.volunteer_id = second_matched.id
    learner.is_matched = True
    second_matched.is_matched = True
    db_session.commit()

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)
    order = [int(vid) for vid in re.findall(r'data-volunteer-id="(\d+)"', body)]

    assert order == [pair["volunteer"].id, second_matched.id, free.id]


def test_the_roster_excludes_another_teachers_people(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    make_learner(db_session, pair["school"], other, name="NotMine")

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert "NotMine" not in body


# ── person detail ────────────────────────────────────────────────────────────


def test_a_learner_detail_page_renders(client, db_session, pair):
    body = assert_success(
        client.get(f"/teacher/learners/{pair['learner'].id}")
    ).get_data(as_text=True)

    assert "Ada" in body


def test_a_volunteer_detail_page_renders(client, db_session, pair):
    body = assert_success(
        client.get(f"/teacher/volunteers/{pair['volunteer'].id}")
    ).get_data(as_text=True)

    assert "Bo" in body


def test_the_learner_detail_page_scores_the_match(client, db_session, pair):
    """The pair's compatibility score rides next to the matched volunteer."""
    pair["learner"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Beginner"}]}
    pair["volunteer"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Advanced"}]}
    db_session.commit()

    body = assert_success(
        client.get(f"/teacher/learners/{pair['learner'].id}")
    ).get_data(as_text=True)

    assert re.search(r'match-score-chip match-score-good.*?>\s*85\s*<', body, re.DOTALL)


def test_the_volunteer_detail_page_scores_each_learner(client, db_session, pair):
    pair["learner"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Beginner"}]}
    pair["volunteer"].survey_data = {"age": 16, "languages": [{"language": "English", "level": "Advanced"}]}
    db_session.commit()

    body = assert_success(
        client.get(f"/teacher/volunteers/{pair['volunteer'].id}")
    ).get_data(as_text=True)

    assert re.search(r'match-score-chip match-score-good.*?>\s*85\s*<', body, re.DOTALL)


def test_an_unmatched_learner_detail_shows_no_score(client, db_session, authenticated_teacher):
    learner = make_learner(db_session, authenticated_teacher.school, authenticated_teacher, name="Solo")

    body = assert_success(client.get(f"/teacher/learners/{learner.id}")).get_data(as_text=True)

    assert 'class="match-score-chip' not in body


def test_another_teachers_learner_detail_is_refused(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    theirs = make_learner(db_session, pair["school"], other)

    assert_denied(client.get(f"/teacher/learners/{theirs.id}"))


def test_an_unknown_learner_detail_is_refused(client, db_session, authenticated_teacher):
    assert_denied(client.get("/teacher/learners/999999"))


# ── roster search markup ─────────────────────────────────────────────────────


def test_the_people_page_carries_both_matching_modals(client, db_session, pair):
    """A missing modal is invisible until a teacher presses its button."""
    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert 'id="priorities-overlay"' in body
    assert 'id="match-preview-overlay"' in body
    assert 'id="match-preview-row-template"' in body


def test_a_roster_status_renders_both_pills_with_the_current_one_shown(client, db_session, pair):
    """A match or a limit change made on the page flips a status pill without a
    reload, so both pills are in the markup and the script toggles `hidden`."""
    from tests.support.html import parse

    root = parse(assert_success(client.get("/teacher/people")).get_data(as_text=True))

    for slot_id in (f"learner-status-{pair['learner'].id}", f"volunteer-status-{pair['volunteer'].id}"):
        (slot,) = [el for el in root.find_all("span") if el.attrs.get("id") == slot_id]
        pills = {child.attrs.get("data-status"): child for child in slot.children}
        assert set(pills) == {"on", "off"}
        # Matched learner; volunteer at its limit of one, so full.
        assert "hidden" not in pills["on"].classes
        assert "hidden" in pills["off"].classes


def test_a_roster_card_carries_the_name_as_written_for_the_search_suggestions(
    client, db_session, pair
):
    """The combo shows `data-name` verbatim, so it holds the display casing —
    the lowercase copy used for matching lives in `data-search`."""
    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert 'data-name="Ada"' in body
    assert 'data-name="Bo"' in body


def test_a_roster_card_is_searchable_by_username_and_email(client, db_session, pair):
    """Typing a learner's login or a volunteer's email finds the card, not just
    their display name."""
    learner = pair["learner"]
    volunteer = pair["volunteer"]

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert f'data-search="ada {learner.username.lower()}"' in body
    assert f'data-search="bo {volunteer.email.lower()}"' in body


def test_the_roster_headings_carry_a_live_count_target(client, db_session, pair):
    """The heading count is rewritten as the search filters, so it renders in
    its own element with the unfiltered total on it."""
    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    assert re.search(r'data-count-learners data-total="1">\s*1\s*</span>', body)
    assert re.search(r'data-count-volunteers data-total="1">\s*1\s*</span>', body)


def test_the_roster_scopes_card_lookups_past_the_connector_lines(client, db_session, pair):
    """`drawPairLines` stamps the same data-learner-id / data-volunteer-id onto
    the SVG groups it draws, and they sit above the columns in the DOM — every
    card lookup has to be scoped to `.people-item` or it finds a line first."""
    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    for attribute in ("data-learner-id", "data-volunteer-id", "data-pair-volunteer"):
        lookup = f'[{attribute}="${{'
        assert body.count(lookup) > 0
        assert body.count(f".people-item{lookup}") == body.count(lookup)

# ── invite code ──────────────────────────────────────────────────────────────


def test_regenerating_the_invite_code_replaces_it(client, db_session, authenticated_teacher):
    from helpers.auth_utils import get_or_create_invite_code

    school = authenticated_teacher.school
    original = get_or_create_invite_code(school)

    client.post("/teacher/regenerate-invite")

    db_session.expire_all()
    assert school.invite_code != original


def test_opening_the_dashboard_never_rotates_the_invite_code(client, db_session, authenticated_teacher):
    from helpers.auth_utils import get_or_create_invite_code

    school = authenticated_teacher.school
    original = get_or_create_invite_code(school)

    client.get("/teacher/")
    client.get("/teacher/")

    db_session.expire_all()
    assert school.invite_code == original
    assert original in client.get("/teacher/").get_data(as_text=True)


def test_regenerating_the_invite_code_can_answer_json(client, db_session, authenticated_teacher):
    response = assert_success(
        client.post("/teacher/regenerate-invite", headers=AJAX)
    )

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["invite_code"] == authenticated_teacher.school.invite_code
    assert "invite_expires" not in payload


# ── default capacity ─────────────────────────────────────────────────────────


def test_the_default_capacity_can_be_set(client, db_session, authenticated_teacher):
    client.post("/teacher/default-capacity", data={"default_capacity": "3"})

    db_session.expire_all()
    assert authenticated_teacher.default_match_capacity == 3


def test_the_default_capacity_does_not_rewrite_existing_volunteers(client, db_session, pair):
    """A hand-set capacity must survive a change of default."""

    pair["volunteer"].match_capacity = 5
    db_session.commit()

    client.post("/teacher/default-capacity", data={"default_capacity": "2"})

    db_session.expire_all()
    assert pair["volunteer"].match_capacity == 5


def test_an_out_of_range_default_capacity_is_refused(client, db_session, authenticated_teacher):
    response = client.post(
        "/teacher/default-capacity",
        data={"default_capacity": "99"},
        headers=AJAX,
    )

    assert response.status_code == 400


# ── matching priorities ──────────────────────────────────────────────────────


def test_matching_priorities_can_be_set(client, db_session, authenticated_teacher):
    response = client.post(
        "/teacher/match-settings",
        data={"weight_language": "4", "weight_hobbies": "0", "spread": "3"},
        headers=AJAX,
    )

    assert response.get_json()["success"] is True
    db_session.expire_all()
    stored = authenticated_teacher.match_settings
    assert stored["weights"]["language"] == 4
    assert stored["weights"]["hobbies"] == 0
    assert stored["spread"] == 3


def test_a_factor_the_form_left_out_keeps_its_default(client, db_session, authenticated_teacher):
    client.post("/teacher/match-settings", data={"weight_language": "4"})

    db_session.expire_all()
    from helpers.matching import DEFAULT_WEIGHT_LEVEL

    assert authenticated_teacher.match_settings["weights"]["age"] == DEFAULT_WEIGHT_LEVEL


def test_an_out_of_range_priority_level_is_refused(client, db_session, authenticated_teacher):
    response = client.post(
        "/teacher/match-settings",
        data={"weight_language": "99"},
        headers=AJAX,
    )

    assert response.status_code == 400


def test_resetting_priorities_restores_the_balanced_defaults(client, db_session, authenticated_teacher):
    from helpers.matching import DEFAULT_SPREAD_LEVEL, DEFAULT_WEIGHT_LEVEL

    client.post("/teacher/match-settings", data={"weight_language": "4", "spread": "4"})
    client.post("/teacher/match-settings", data={"reset": "1", "weight_language": "4", "spread": "4"})

    db_session.expire_all()
    stored = authenticated_teacher.match_settings
    assert set(stored["weights"].values()) == {DEFAULT_WEIGHT_LEVEL}
    assert stored["spread"] == DEFAULT_SPREAD_LEVEL


def test_the_priorities_panel_redraws_the_saved_levels(client, db_session, authenticated_teacher):
    """The panel is the only place these levels are visible, so a saved value
    that does not come back selected reads as never having saved."""
    client.post("/teacher/match-settings", data={"weight_language": "4", "spread": "3"})

    body = assert_success(client.get("/teacher/people")).get_data(as_text=True)

    # The bars are drawn off `data-level`, so that attribute is what a teacher
    # actually sees redrawn — a checked radio alone would render an empty row.
    assert re.search(r'name="weight_language"\s+value="4"\s+checked', body)
    assert 'data-level="4"' in body
    assert re.search(r'name="spread"\s+value="3"\s+checked', body)


def test_saved_priorities_steer_the_matching_run(client, db_session, authenticated_teacher):
    """The stored settings are what `/api/run-matching` optimises, so the same
    roster pairs differently under two weightings."""
    from models import Learner

    learner = make_learner(
        db_session, teacher=authenticated_teacher, school=authenticated_teacher.school,
        survey_data={"age": 16, "languages": [{"language": "Arabic", "level": "Beginner"}],
                     "hobbies": ["reading", "football", "music", "art"]},
    )
    linguist = make_volunteer(
        db_session, teacher=authenticated_teacher, school=authenticated_teacher.school,
        survey_data={"age": 40, "languages": [{"language": "Arabic", "level": "Advanced"}]},
    )
    companion = make_volunteer(
        db_session, teacher=authenticated_teacher, school=authenticated_teacher.school,
        survey_data={"age": 40, "languages": [],
                     "hobbies": ["reading", "football", "music", "art"]},
    )

    client.post("/teacher/match-settings", data={"weight_language": "4", "weight_hobbies": "1"})
    assert_success(client.post("/api/run-matching", headers=AJAX))
    db_session.expire_all()
    assert db_session.get(Learner, learner.id).volunteer_id == linguist.id

    client.post("/teacher/match-settings", data={"weight_language": "1", "weight_hobbies": "4"})
    assert_success(client.post("/api/run-matching", headers=AJAX))
    db_session.expire_all()
    assert db_session.get(Learner, learner.id).volunteer_id == companion.id


# ── pairs ────────────────────────────────────────────────────────────────────


def test_a_pair_can_be_dissolved(client, db_session, pair):
    client.post(f"/teacher/pairs/{pair['learner'].id}/unmatch")

    db_session.expire_all()
    assert pair["learner"].volunteer_id is None
    assert pair["learner"].is_matched is False
    assert pair["volunteer"].is_matched is False


def test_another_teachers_pair_cannot_be_dissolved(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    their_learner = make_learner(db_session, pair["school"], other)
    their_volunteer = make_volunteer(db_session, pair["school"], other)
    their_learner.volunteer_id = their_volunteer.id
    their_learner.is_matched = True
    db_session.commit()

    assert_denied(client.post(f"/teacher/pairs/{their_learner.id}/unmatch"))
    db_session.expire_all()
    assert their_learner.volunteer_id == their_volunteer.id


def test_a_pair_can_be_matched_by_hand(client, db_session, authenticated_teacher):
    school = authenticated_teacher.school
    learner = make_learner(db_session, school, authenticated_teacher)
    volunteer = make_volunteer(db_session, school, authenticated_teacher)

    client.post(
        "/teacher/pairs/match",
        data={"learner_id": learner.id, "volunteer_id": volunteer.id},
    )

    db_session.expire_all()
    assert learner.volunteer_id == volunteer.id
    assert volunteer.is_matched is True


def test_matching_a_learner_from_another_roster_is_refused(client, db_session, authenticated_teacher):
    school = authenticated_teacher.school
    other = make_teacher(db_session, school)
    theirs = make_learner(db_session, school, other)
    volunteer = make_volunteer(db_session, school, authenticated_teacher)

    client.post(
        "/teacher/pairs/match", data={"learner_id": theirs.id, "volunteer_id": volunteer.id}
    )

    db_session.expire_all()
    assert theirs.volunteer_id is None


# ── deletions and passwords ──────────────────────────────────────────────────


def test_a_learner_can_be_deleted(client, db_session, pair):
    from models import Learner

    learner_id = pair["learner"].id

    client.post(f"/teacher/learners/{learner_id}/delete")

    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=learner_id)) == 0


def test_another_teachers_learner_cannot_be_deleted(client, db_session, pair):
    from models import Learner

    other = make_teacher(db_session, pair["school"])
    theirs = make_learner(db_session, pair["school"], other)

    assert_denied(client.post(f"/teacher/learners/{theirs.id}/delete"))
    assert db_session.scalar(select(func.count()).select_from(Learner).filter_by(id=theirs.id)) == 1


def test_a_volunteer_can_be_deleted(client, db_session, pair):
    from models import Volunteer

    volunteer_id = pair["volunteer"].id

    client.post(f"/teacher/volunteers/{volunteer_id}/delete")

    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(id=volunteer_id)) == 0


def test_another_teachers_volunteer_cannot_be_deleted(client, db_session, pair):
    from models import Volunteer

    other = make_teacher(db_session, pair["school"])
    theirs = make_volunteer(db_session, pair["school"], other)

    assert_denied(client.post(f"/teacher/volunteers/{theirs.id}/delete"))
    assert db_session.scalar(select(func.count()).select_from(Volunteer).filter_by(id=theirs.id)) == 1


def test_a_learner_password_can_be_reset(client, db_session, pair):
    client.post(
        f"/teacher/learners/{pair['learner'].id}/set-password",
        data={"password": "BrandNew1!"},
    )

    db_session.expire_all()
    assert pair["learner"].check_password("BrandNew1!")


def test_a_password_reset_with_a_space_inside_is_refused(client, db_session, pair):
    response = client.post(
        f"/teacher/learners/{pair['learner'].id}/set-password", data={"password": "Brand New1!"}
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert not pair["learner"].check_password("Brand New1!")


def test_an_empty_password_reset_is_refused(client, db_session, pair):
    response = client.post(
        f"/teacher/learners/{pair['learner'].id}/set-password", data={"password": "  "}
    )

    assert response.status_code == 400


def test_another_teachers_learner_password_cannot_be_reset(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    theirs = make_learner(db_session, pair["school"], other)

    assert_denied(
        client.post(f"/teacher/learners/{theirs.id}/set-password", data={"password": "x"})
    )
