"""The teacher's assigned-worksheets tracker, printing from it, and the
assign-and-print shortcut on a worksheet's own page."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.support.assertions import assert_denied, assert_redirects_to, assert_success
from tests.support.factories import (
    make_learner,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web

TRACKER = "/teacher/worksheets/assigned"


def _assign(db_session, pair, title, **overrides):
    worksheet = make_worksheet(db_session, title=title, subject=overrides.pop("subject", "English Grammar"))
    return make_worksheet_assignment(
        db_session, pair["teacher"], pair["learner"], worksheet, volunteer=pair["volunteer"], **overrides
    )


def _second_pair(db_session, teacher, name="Cleo", volunteer_name="Dan"):
    learner = make_learner(db_session, teacher.school, teacher, name=name)
    volunteer = make_volunteer(db_session, teacher.school, teacher, name=volunteer_name)
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()
    return {"teacher": teacher, "learner": learner, "volunteer": volunteer}


# ── the tracker page ────────────────────────────────────────────────────────


def test_the_tracker_lists_outstanding_and_completed_assignments(client, db_session, pair):
    _assign(db_session, pair, "Waiting Sheet")
    _assign(db_session, pair, "Finished Sheet", completed=True)

    body = assert_success(client.get(TRACKER)).get_data(as_text=True)

    assert "Waiting Sheet" in body
    assert "Finished Sheet" in body


def test_the_tracker_hides_another_teachers_learners(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    their_learner = make_learner(db_session, pair["school"], other)
    make_worksheet_assignment(db_session, other, their_learner, make_worksheet(db_session, title="Not Yours"))

    body = assert_success(client.get(TRACKER)).get_data(as_text=True)

    assert "Not Yours" not in body


def test_a_colleagues_assignment_to_my_learner_is_listed(client, db_session, pair):
    """The learner is the gate, as on the learner page — not who set the sheet."""
    colleague = make_teacher(db_session, pair["school"])
    make_worksheet_assignment(db_session, colleague, pair["learner"], make_worksheet(db_session, title="From A Colleague"))

    body = assert_success(client.get(TRACKER)).get_data(as_text=True)

    assert "From A Colleague" in body


def test_the_status_filter_splits_outstanding_from_completed(client, db_session, pair):
    _assign(db_session, pair, "Waiting Sheet")
    _assign(db_session, pair, "Finished Sheet", completed=True)

    outstanding = assert_success(client.get(f"{TRACKER}?status=outstanding")).get_data(as_text=True)
    completed = assert_success(client.get(f"{TRACKER}?status=completed")).get_data(as_text=True)

    assert "Waiting Sheet" in outstanding and "Finished Sheet" not in outstanding
    assert "Finished Sheet" in completed and "Waiting Sheet" not in completed


def test_the_learner_filter_narrows_to_one_pair(client, db_session, pair):
    other_pair = _second_pair(db_session, pair["teacher"])
    _assign(db_session, pair, "Ada Sheet")
    _assign(db_session, other_pair, "Cleo Sheet")

    body = assert_success(
        client.get(f"{TRACKER}?learner={other_pair['learner'].id}", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Cleo Sheet" in body
    assert "Ada Sheet" not in body


def test_the_subject_filter_and_search_narrow_the_list(client, db_session, pair):
    _assign(db_session, pair, "Fractions Practice", subject="Maths")
    _assign(db_session, pair, "Grammar Basics", subject="English Grammar")
    _assign(db_session, pair, "Grammar Advanced", subject="English Grammar")

    by_subject = assert_success(
        client.get(f"{TRACKER}?subject=Maths", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)
    by_search = assert_success(
        client.get(f"{TRACKER}?q=advanced", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Fractions Practice" in by_subject and "Grammar Basics" not in by_subject
    assert "Grammar Advanced" in by_search and "Grammar Basics" not in by_search


def test_the_range_filter_drops_assignments_older_than_the_window(client, db_session, pair):
    _assign(db_session, pair, "Fresh Sheet")
    _assign(db_session, pair, "Old Sheet", assigned_at=datetime.now(UTC) - timedelta(days=60))

    body = assert_success(
        client.get(f"{TRACKER}?range=month", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Fresh Sheet" in body
    assert "Old Sheet" not in body


def test_an_unknown_filter_value_is_ignored_not_a_500(client, db_session, pair):
    _assign(db_session, pair, "Any Sheet")

    body = assert_success(client.get(f"{TRACKER}?status=bogus&range=forever&learner=abc")).get_data(as_text=True)

    assert "Any Sheet" in body


def test_the_tracker_pages_at_twenty_five(client, db_session, pair):
    for i in range(30):
        _assign(db_session, pair, f"Sheet {i:02d}", assigned_at=datetime.now(UTC) - timedelta(minutes=i))

    page1 = assert_success(client.get(TRACKER, headers={"X-Fragment": "1"})).get_data(as_text=True)
    page2 = assert_success(client.get(f"{TRACKER}?page=2", headers={"X-Fragment": "1"})).get_data(as_text=True)

    assert "Sheet 00" in page1 and "Sheet 24" in page1 and "Sheet 25" not in page1
    assert "Sheet 25" in page2 and "Sheet 00" not in page2


def test_the_summary_counts_cover_every_assignment_not_the_filtered_page(client, db_session, pair):
    _assign(db_session, pair, "One")
    _assign(db_session, pair, "Two")
    _assign(db_session, pair, "Three", completed=True)
    _assign(db_session, pair, "Stale", assigned_at=datetime.now(UTC) - timedelta(days=20))

    body = assert_success(client.get(f"{TRACKER}?status=completed")).get_data(as_text=True)

    assert 'data-stat="outstanding">3<' in body
    assert 'data-stat="completed_recent">1<' in body
    assert 'data-stat="stale">1<' in body


def test_a_matched_pair_with_nothing_outstanding_is_flagged(client, db_session, pair):
    busy_pair = _second_pair(db_session, pair["teacher"])
    _assign(db_session, busy_pair, "Busy Sheet")
    _assign(db_session, pair, "Done Sheet", completed=True)

    body = assert_success(client.get(TRACKER)).get_data(as_text=True)

    assert f'data-needs-sheet="{pair["learner"].id}"' in body
    assert f'data-needs-sheet="{busy_pair["learner"].id}"' not in body


def test_a_pair_row_prints_everything_it_has_outstanding(client, db_session, pair):
    first = _assign(db_session, pair, "First")
    second = _assign(db_session, pair, "Second")
    _assign(db_session, pair, "Done", completed=True)

    body = assert_success(client.get(TRACKER)).get_data(as_text=True)

    assert f"/teacher/worksheet-assignments/print?ids={first.id}&amp;ids={second.id}" in body or \
        f"/teacher/worksheet-assignments/print?ids={second.id}&amp;ids={first.id}" in body


def test_the_tracker_is_teacher_only(client, db_session, authenticated_volunteer):
    assert_denied(client.get(TRACKER))


def test_the_library_links_to_the_tracker(client, db_session, authenticated_teacher):
    body = assert_success(client.get("/teacher/worksheets")).get_data(as_text=True)

    assert f'href="{TRACKER}"' in body


def test_the_learner_page_links_to_their_full_list_on_the_tracker(client, db_session, pair):
    _assign(db_session, pair, "Waiting")

    body = assert_success(client.get(f"/teacher/learners/{pair['learner'].id}")).get_data(as_text=True)

    assert f"{TRACKER}?learner={pair['learner'].id}" in body


# ── printing ────────────────────────────────────────────────────────────────


def test_printing_one_assignment_opens_the_pdf_inline(client, db_session, pair):
    assignment = _assign(db_session, pair, "Inline")

    response = client.get(f"/teacher/worksheet-assignments/print?ids={assignment.id}")

    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline")


def test_there_is_no_separate_single_print_route(client, db_session, pair):
    assignment = _assign(db_session, pair, "Inline")

    assert client.get(f"/teacher/worksheet-assignments/{assignment.id}/print").status_code == 404


def test_print_all_outstanding_is_offered_only_while_it_fits_one_packet(client, db_session, pair, monkeypatch):
    from routes.teacher import worksheet_assignments

    for number in range(3):
        _assign(db_session, pair, f"Sheet {number}")
    learner_page = f"/teacher/learners/{pair['learner'].id}"

    assert 'data-print-all' in assert_success(client.get(TRACKER)).get_data(as_text=True)
    assert 'data-print-all' in assert_success(client.get(learner_page)).get_data(as_text=True)

    monkeypatch.setattr(worksheet_assignments, "MAX_PRINT_BATCH", 2)

    assert 'data-print-all' not in assert_success(client.get(TRACKER)).get_data(as_text=True)
    assert 'data-print-all' not in assert_success(client.get(learner_page)).get_data(as_text=True)


def test_paging_keeps_the_learner_filter(client, db_session, pair):
    for number in range(30):
        _assign(db_session, pair, f"Sheet {number:02}")

    body = assert_success(client.get(f"{TRACKER}?learner={pair['learner'].id}")).get_data(as_text=True)

    assert re.search(rf"learner={pair['learner'].id}[^\"]*page=2|page=2[^\"]*learner={pair['learner'].id}", body)


def test_printing_several_assignments_returns_one_inline_pdf(client, db_session, pair):
    first = _assign(db_session, pair, "First")
    other_pair = _second_pair(db_session, pair["teacher"])
    second = _assign(db_session, other_pair, "Second")

    response = client.get(f"/teacher/worksheet-assignments/print?ids={first.id}&ids={second.id}&double_sided=on")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline")


def test_printing_another_teachers_assignment_in_a_batch_is_refused(client, db_session, pair):
    mine = _assign(db_session, pair, "Mine")
    other = make_teacher(db_session, pair["school"])
    theirs = make_worksheet_assignment(db_session, other, make_learner(db_session, pair["school"], other), make_worksheet(db_session))

    assert client.get(f"/teacher/worksheet-assignments/print?ids={mine.id}&ids={theirs.id}").status_code == 403


def test_printing_with_nothing_selected_goes_back_to_the_tracker(client, db_session, pair):
    assert_redirects_to(client.get("/teacher/worksheet-assignments/print"), TRACKER)


def test_printing_an_unknown_assignment_in_a_batch_is_a_404(client, db_session, pair):
    assert client.get("/teacher/worksheet-assignments/print?ids=999999").status_code == 404


# ── completing in bulk ──────────────────────────────────────────────────────


def test_several_assignments_can_be_completed_at_once(client, db_session, pair):
    from models import WorksheetAssignment

    first = _assign(db_session, pair, "First")
    second = _assign(db_session, pair, "Second")

    response = client.post(
        "/teacher/worksheet-assignments/complete",
        data={"ids": [first.id, second.id]},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.get_json()["success"] is True
    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, first.id).completed is True
    assert db_session.get(WorksheetAssignment, second.id).completed is True


def test_a_bulk_complete_with_a_foreign_assignment_changes_nothing(client, db_session, pair):
    from models import WorksheetAssignment

    mine = _assign(db_session, pair, "Mine")
    other = make_teacher(db_session, pair["school"])
    theirs = make_worksheet_assignment(db_session, other, make_learner(db_session, pair["school"], other), make_worksheet(db_session))

    response = client.post("/teacher/worksheet-assignments/complete", data={"ids": [mine.id, theirs.id]})

    assert response.status_code == 403
    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, mine.id).completed is False


def test_a_bulk_complete_without_javascript_returns_to_the_filtered_tracker(client, db_session, pair):
    assignment = _assign(db_session, pair, "Mine")

    response = client.post(
        "/teacher/worksheet-assignments/complete",
        data={"ids": [assignment.id], "next": f"{TRACKER}?status=outstanding"},
    )

    assert_redirects_to(response, f"{TRACKER}?status=outstanding")


def test_completing_one_assignment_honours_a_local_next(client, db_session, pair):
    assignment = _assign(db_session, pair, "Mine")

    response = client.post(
        f"/teacher/worksheet-assignments/{assignment.id}/complete", data={"next": f"{TRACKER}?status=outstanding"}
    )

    assert_redirects_to(response, f"{TRACKER}?status=outstanding")


@pytest.mark.parametrize("next_url", ["//evil.example/x", "https://evil.example/x", "/\\evil.example"])
def test_completing_one_assignment_ignores_an_offsite_next(client, db_session, pair, next_url):
    assignment = _assign(db_session, pair, "Mine")

    response = client.post(f"/teacher/worksheet-assignments/{assignment.id}/complete", data={"next": next_url})

    assert_redirects_to(response, f"/teacher/learners/{pair['learner'].id}")


# ── assigning from a worksheet's page ───────────────────────────────────────


def test_assign_and_print_creates_the_assignment_then_opens_its_pdf(client, db_session, pair):
    from models import WorksheetAssignment

    worksheet = make_worksheet(db_session)

    response = client.post(
        f"/teacher/worksheets/{worksheet.id}/assign", data={"learner_id": pair["learner"].id, "then": "print"}
    )

    assignment = db_session.scalars(select(WorksheetAssignment).filter_by(worksheet_id=worksheet.id)).one()
    assert_redirects_to(response, f"/teacher/worksheet-assignments/print?ids={assignment.id}")


def test_assigning_without_printing_stays_on_the_worksheet(client, db_session, pair):
    worksheet = make_worksheet(db_session)

    response = client.post(f"/teacher/worksheets/{worksheet.id}/assign", data={"learner_id": pair["learner"].id})

    assert_redirects_to(response, f"/teacher/worksheets/{worksheet.id}?learner_id={pair['learner'].id}")


def test_an_ajax_assign_answers_with_the_print_link(client, db_session, pair):
    from models import WorksheetAssignment

    worksheet = make_worksheet(db_session, title="Tom & <Jerry>")

    payload = client.post(
        f"/teacher/worksheets/{worksheet.id}/assign",
        data={"learner_id": pair["learner"].id, "then": "print"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    ).get_json()

    assignment = db_session.scalars(select(WorksheetAssignment).filter_by(worksheet_id=worksheet.id)).one()
    assert payload["success"] is True
    assert payload["print_url"] == f"/teacher/worksheet-assignments/print?ids={assignment.id}"
    # The toast sets the message as text, so it arrives unescaped: escaping it here showed "&amp;".
    assert '"Tom & <Jerry>"' in payload["message"]
    assert "&amp;" not in payload["message"]


def test_the_worksheet_page_shows_who_already_has_it(client, db_session, pair):
    worksheet = make_worksheet(db_session, title="Shared Sheet")
    assignment = make_worksheet_assignment(db_session, pair["teacher"], pair["learner"], worksheet, volunteer=pair["volunteer"])

    body = assert_success(client.get(f"/teacher/worksheets/{worksheet.id}")).get_data(as_text=True)

    assert 'id="ws-already-assigned"' in body
    assert f"/teacher/worksheet-assignments/print?ids={assignment.id}" in body


def test_the_worksheet_page_offers_assign_and_print(client, db_session, pair):
    worksheet = make_worksheet(db_session)

    body = assert_success(client.get(f"/teacher/worksheets/{worksheet.id}")).get_data(as_text=True)

    assert re.search(r'<button[^>]*name="then"[^>]*value="print"', body)
