"""Teacher worksheet routes: the library, bulk-assign packets, uploads."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import func, select

from tests.support.assertions import assert_denied, assert_success
from tests.support.factories import (
    make_learner,
    make_subject,
    make_teacher,
    make_topic,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.web


# ── worksheets ───────────────────────────────────────────────────────────────


def test_the_worksheet_library_lists_worksheets(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Grammar Basics")

    body = assert_success(client.get("/teacher/worksheets")).get_data(as_text=True)

    assert "Grammar Basics" in body


def test_the_worksheet_library_load_more_batches_at_twenty_four_with_no_overlap(client, db_session, authenticated_teacher):
    """First batch renders on the full page; the next batch is a fragment
    fetch (`X-Fragment: 1`) at WORKSHEETS_LIBRARY_PAGE_SIZE (24)."""
    for i in range(30):
        make_worksheet(db_session, title=f"Sheet {i:02d}", subject="English Grammar")

    page1 = assert_success(client.get("/teacher/worksheets")).get_data(as_text=True)
    batch2 = assert_success(
        client.get("/teacher/worksheets?page=2", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    for i in range(24):
        assert f"Sheet {i:02d}" in page1
    assert "Sheet 24" not in page1
    for i in range(24, 30):
        assert f"Sheet {i:02d}" in batch2
    assert "Sheet 00" not in batch2


def test_the_worksheet_library_reports_has_more_and_total_via_headers(client, db_session, authenticated_teacher):
    for i in range(30):
        make_worksheet(db_session, title=f"Sheet {i:02d}")

    res = client.get("/teacher/worksheets", headers={"X-Fragment": "1"})

    assert res.headers.get("X-Has-More") == "1"
    assert res.headers.get("X-Total-Count") == "30"

    last_batch = client.get("/teacher/worksheets?page=2", headers={"X-Fragment": "1"})
    assert last_batch.headers.get("X-Has-More") == "0"


def test_a_subject_filter_narrows_the_library_before_loading_more(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Grammar One", subject="English Grammar")
    make_worksheet(db_session, title="Maths One", subject="Maths")

    body = assert_success(client.get("/teacher/worksheets?subject=Maths")).get_data(as_text=True)

    assert "Maths One" in body
    assert "Grammar One" not in body


def test_the_subject_filter_survives_a_load_more_batch_on_the_worksheet_library(client, db_session, authenticated_teacher):
    for i in range(30):
        make_worksheet(db_session, title=f"Grammar {i:02d}", subject="English Grammar")
    make_worksheet(db_session, title="Off Subject", subject="Maths")

    batch2 = assert_success(
        client.get("/teacher/worksheets?subject=English Grammar&page=2", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Off Subject" not in batch2
    assert "Grammar 24" in batch2


def test_a_search_query_narrows_the_worksheet_library_server_side(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Fractions Practice", subject="Maths")
    make_worksheet(db_session, title="Grammar Basics", subject="English Grammar")

    body = assert_success(
        client.get("/teacher/worksheets?q=Fractions", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "Fractions Practice" in body
    assert "Grammar Basics" not in body


def test_the_full_library_page_always_opens_on_the_first_batch(client, db_session, authenticated_teacher):
    # Load more continues from batch 2, so a full page showing any other batch would skip or repeat.
    for i in range(30):
        make_worksheet(db_session, title=f"Sheet {i:02d}")

    body = assert_success(client.get("/teacher/worksheets?page=2")).get_data(as_text=True)

    assert "Sheet 00" in body
    assert "Sheet 29" not in body


def test_a_load_more_batch_past_the_end_is_empty_not_a_repeat_of_the_last_batch(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Been", subject="Sight Words")

    res = assert_success(client.get("/teacher/worksheets?q=been&page=2", headers={"X-Fragment": "1"}))

    assert "Been" not in res.get_data(as_text=True)
    assert res.headers.get("X-Has-More") == "0"


def test_a_worksheet_preview_renders(client, db_session, authenticated_teacher):
    worksheet = make_worksheet(db_session, title="Previewable")

    body = assert_success(
        client.get(f"/teacher/worksheets/{worksheet.id}")
    ).get_data(as_text=True)

    assert "Previewable" in body


def test_an_unknown_worksheet_preview_is_a_404(client, db_session, authenticated_teacher):
    assert client.get("/teacher/worksheets/999999").status_code == 404


def test_a_worksheet_can_be_assigned_to_a_matched_learner(client, db_session, pair):
    from models import WorksheetAssignment

    worksheet = make_worksheet(db_session)

    client.post(
        f"/teacher/worksheets/{worksheet.id}/assign",
        data={"learner_id": pair["learner"].id},
    )

    assert db_session.scalar(select(func.count()).select_from(WorksheetAssignment).filter_by(
        learner_id=pair["learner"].id, worksheet_id=worksheet.id
    )) == 1


def test_assigning_without_a_learner_is_a_400(client, db_session, authenticated_teacher):
    worksheet = make_worksheet(db_session)

    assert client.post(f"/teacher/worksheets/{worksheet.id}/assign", data={}).status_code == 400


def test_assigning_to_an_unmatched_learner_is_a_404(client, db_session, authenticated_teacher):
    """This route only ever assigns to a matched pair; the 404 is the gate."""

    lonely = make_learner(db_session, authenticated_teacher.school, authenticated_teacher)
    worksheet = make_worksheet(db_session)

    response = client.post(
        f"/teacher/worksheets/{worksheet.id}/assign", data={"learner_id": lonely.id}
    )

    assert response.status_code == 404


# ── bulk assign packet builder ───────────────────────────────────────────────


def test_bulk_assigning_with_the_double_sided_box_unchecked_does_not_500(client, db_session, pair):
    """The checkbox posts no field at all when unchecked — the handler must
    not assume `double_sided` is present in the form data."""
    worksheet = make_worksheet(db_session)

    response = client.post(
        "/teacher/worksheets/assign",
        data={f"worksheet_for_{pair['learner'].id}": str(worksheet.id)},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_bulk_assigning_with_double_sided_checked_returns_a_pdf(client, db_session, pair):
    from models import WorksheetAssignment

    worksheet = make_worksheet(db_session)

    response = client.post(
        "/teacher/worksheets/assign",
        data={f"worksheet_for_{pair['learner'].id}": str(worksheet.id), "double_sided": "on"},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert db_session.scalar(select(func.count()).select_from(WorksheetAssignment).filter_by(
        learner_id=pair["learner"].id, worksheet_id=worksheet.id
    )) == 1


def test_printing_an_existing_assignment_returns_a_pdf(client, db_session, pair):
    worksheet = make_worksheet(db_session)
    assignment = make_worksheet_assignment(db_session, pair["teacher"], pair["learner"], worksheet)

    response = client.get(f"/teacher/worksheet-assignments/print?ids={assignment.id}")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_an_assignment_can_be_completed_and_reopened(client, db_session, pair):
    from models import WorksheetAssignment

    worksheet = make_worksheet(db_session)
    assignment = make_worksheet_assignment(
        db_session, pair["teacher"], pair["learner"], worksheet
    )

    client.post(f"/teacher/worksheet-assignments/{assignment.id}/complete")
    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, assignment.id).completed is True

    client.post(f"/teacher/worksheet-assignments/{assignment.id}/reopen")
    db_session.expire_all()
    assert db_session.get(WorksheetAssignment, assignment.id).completed is False


def test_another_teachers_assignment_cannot_be_completed(client, db_session, pair):
    other = make_teacher(db_session, pair["school"])
    their_learner = make_learner(db_session, pair["school"], other)
    worksheet = make_worksheet(db_session)
    assignment = make_worksheet_assignment(db_session, other, their_learner, worksheet)

    assert_denied(client.post(f"/teacher/worksheet-assignments/{assignment.id}/complete"))


def test_uploading_a_worksheet_requires_a_file(client, db_session, authenticated_teacher):
    response = client.post(
        "/teacher/worksheets/upload", data={"title": "T", "subject": "English Grammar"}
    )

    assert response.status_code == 400


def test_uploading_a_worksheet_requires_a_title_and_subject(client, db_session, authenticated_teacher):
    data = {"file": (io.BytesIO(b"%PDF-1.4"), "sheet.pdf"), "title": "", "subject": ""}

    response = client.post(
        "/teacher/worksheets/upload", data=data, content_type="multipart/form-data"
    )

    assert response.status_code in {400, 302}


def test_an_unsupported_worksheet_extension_is_refused(client, db_session, authenticated_teacher):
    from models import Worksheet

    data = {
        "file": (io.BytesIO(b"whatever"), "payload.exe"),
        "title": "Sneaky",
        "subject": "English Grammar",
    }

    response = client.post(
        "/teacher/worksheets/upload", data=data, content_type="multipart/form-data"
    )

    assert response.status_code in {400, 302}
    assert db_session.scalar(select(func.count()).select_from(Worksheet).filter_by(title="Sneaky")) == 0


def _upload_worksheet(client, monkeypatch, **fields):
    """POST a small PDF to the upload route with `fields` as the form values."""

    from tests.support.storage import use_fake_storage

    use_fake_storage(monkeypatch)
    data = {"file": (io.BytesIO(b"%PDF-1.4"), "sheet.pdf"), "title": "Sheet", **fields}
    return client.post("/teacher/worksheets/upload", data=data, content_type="multipart/form-data")


def test_a_worksheet_uploads_with_a_curriculum_subject_and_topic(
    client, db_session, authenticated_teacher, monkeypatch
):
    from models import Worksheet

    subject = make_subject(db_session, name="Maths")
    make_topic(db_session, subject, title="Counting")

    response = _upload_worksheet(client, monkeypatch, subject="Maths", topic="Counting")

    assert response.status_code == 302
    saved = db_session.scalar(select(Worksheet).filter_by(title="Sheet"))
    assert (saved.subject, saved.topic) == ("Maths", "Counting")


def test_a_worksheet_uploads_without_a_topic(client, db_session, authenticated_teacher, monkeypatch):
    from models import Worksheet

    make_subject(db_session, name="Maths")

    response = _upload_worksheet(client, monkeypatch, subject="Maths", topic="")

    assert response.status_code == 302
    assert db_session.scalar(select(Worksheet).filter_by(title="Sheet")).topic is None


def test_a_worksheet_subject_outside_the_curriculum_is_refused(
    client, db_session, authenticated_teacher, monkeypatch
):
    from models import Worksheet

    make_subject(db_session, name="Maths")

    response = _upload_worksheet(client, monkeypatch, subject="Made Up")

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Worksheet)) == 0


def test_a_worksheet_topic_from_another_subject_is_refused(
    client, db_session, authenticated_teacher, monkeypatch
):
    from models import Worksheet

    maths = make_subject(db_session, name="Maths")
    make_topic(db_session, maths, title="Counting")
    make_subject(db_session, name="Grammar")

    response = _upload_worksheet(client, monkeypatch, subject="Grammar", topic="Counting")

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Worksheet)) == 0


def test_the_upload_form_offers_the_curriculum_subjects_and_topics(
    client, db_session, authenticated_teacher
):
    subject = make_subject(db_session, name="Maths")
    make_topic(db_session, subject, title="Counting")

    page = client.get("/teacher/worksheets").get_data(as_text=True)

    assert '<select id="ws-upload-subject" name="subject"' in page
    assert '<select id="ws-upload-topic" name="topic"' in page
    assert "Maths" in page and "Counting" in page


def _upload_curriculum_offered(client):
    import json

    from tests.support.html import parse

    page = parse(client.get("/teacher/worksheets").get_data(as_text=True))
    [script] = [s for s in page.find_all("script") if s.attrs.get("id") == "ws-upload-curriculum"]
    return json.loads(script.all_text)


def test_the_upload_form_lists_topics_in_learning_path_order(client, db_session, authenticated_teacher):
    subject = make_subject(db_session, name="Maths")
    make_topic(db_session, subject, title="Zebra Counting", level=1)
    make_topic(db_session, subject, title="Advanced", level=2)
    make_topic(db_session, subject, title="Apple Counting", level=1)

    curriculum = _upload_curriculum_offered(client)

    assert curriculum == {"Maths": ["Zebra Counting", "Apple Counting", "Advanced"]}


def test_the_upload_form_leaves_out_placement_only_subjects(client, db_session, authenticated_teacher):
    make_subject(db_session, name="Maths")
    make_subject(db_session, name="Placement Only", map_test_only=True)

    assert list(_upload_curriculum_offered(client)) == ["Maths"]


def test_a_subject_with_no_topics_is_still_offered_for_upload(client, db_session, authenticated_teacher):
    make_subject(db_session, name="Maths")

    assert _upload_curriculum_offered(client) == {"Maths": []}


def test_a_worksheet_for_a_placement_only_subject_is_refused(
    client, db_session, authenticated_teacher, monkeypatch
):
    from models import Worksheet

    make_subject(db_session, name="Placement Only", map_test_only=True)

    response = _upload_worksheet(client, monkeypatch, subject="Placement Only")

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Worksheet)) == 0


@pytest.mark.parametrize(
    "filename,allowed",
    [("a.pdf", True), ("a.md", True), ("a.PDF", True), ("a.exe", False), ("a", False)],
)
def test_the_worksheet_extension_allowlist(app, filename, allowed):
    from routes.teacher import _allowed_worksheet_file

    assert bool(_allowed_worksheet_file(filename)) is allowed


# ── levels and tags ──────────────────────────────────────────────────────────


def test_a_search_matches_a_worksheets_tags(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="The", subject="English: Reading Start", tags=["sight-words", "reading"])
    make_worksheet(db_session, title="Fractions Practice", subject="Maths", tags=["numbers"])

    body = assert_success(
        client.get("/teacher/worksheets?q=sight", headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    assert "The" in body
    assert "Fractions Practice" not in body


def test_the_level_filter_narrows_the_library(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Level Two Sheet", level=2)
    make_worksheet(db_session, title="Level Three Sheet", level=3)
    make_worksheet(db_session, title="Unlevelled Sheet")

    res = assert_success(client.get("/teacher/worksheets?level=2", headers={"X-Fragment": "1"}))
    body = res.get_data(as_text=True)

    assert "Level Two Sheet" in body
    assert "Level Three Sheet" not in body and "Unlevelled Sheet" not in body
    assert res.headers.get("X-Total-Count") == "1"


def test_the_level_filter_combines_with_subject_and_search(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Grammar Two", subject="English Grammar", level=2)
    make_worksheet(db_session, title="Maths Two", subject="Maths", level=2)

    body = assert_success(client.get(
        "/teacher/worksheets?level=2&subject=Maths&q=two", headers={"X-Fragment": "1"}
    )).get_data(as_text=True)

    assert "Maths Two" in body and "Grammar Two" not in body


def test_a_non_numeric_level_is_ignored(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Any Sheet", level=2)

    body = assert_success(client.get("/teacher/worksheets?level=abc")).get_data(as_text=True)

    assert "Any Sheet" in body


def test_the_library_offers_a_level_filter_for_the_levels_worksheets_have(client, db_session, authenticated_teacher):
    from tests.support.html import parse

    make_worksheet(db_session, title="A", level=3)
    make_worksheet(db_session, title="B", level=1)
    make_worksheet(db_session, title="C")

    page = parse(assert_success(client.get("/teacher/worksheets?level=3")).get_data(as_text=True))
    [select_el] = [s for s in page.find_all("select") if s.attrs.get("id") == "ws-level-filter"]
    options = [(o.attrs.get("value"), "selected" in o.attrs) for o in select_el.find_all("option")]

    assert options == [("", False), ("1", False), ("3", True)]


def test_the_library_has_no_level_filter_when_no_worksheet_has_a_level(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Plain")

    body = assert_success(client.get("/teacher/worksheets")).get_data(as_text=True)

    assert 'id="ws-level-filter"' not in body


def test_a_worksheet_card_shows_its_level_and_tags(client, db_session, authenticated_teacher):
    make_worksheet(db_session, title="Tagged", level=2, tags=["sight-words", "reading"])

    body = assert_success(client.get("/teacher/worksheets")).get_data(as_text=True)

    assert "Level 2" in body
    assert "sight-words" in body and "reading" in body


def test_a_level_filter_is_reported_with_the_library_view(client, db_session, authenticated_teacher, monkeypatch):
    from helpers import worksheet_library

    events = []
    monkeypatch.setattr(worksheet_library, "capture_event",
                        lambda user, name, properties=None: events.append((name, properties)))
    make_worksheet(db_session, title="Level Two Sheet", level=2)

    client.get("/teacher/worksheets?level=2")
    client.get("/teacher/worksheets?level=2&q=two")

    assert events[0][0] == "page_viewed" and events[0][1]["selected_level"] == 2
    assert events[1][0] == "worksheet_library_searched" and events[1][1]["selected_level"] == 2


def test_a_worksheet_uploads_with_a_level_and_tags(client, db_session, authenticated_teacher, monkeypatch):
    from models import Worksheet

    make_subject(db_session, name="Maths")

    response = _upload_worksheet(client, monkeypatch, subject="Maths", level="3", tags=" Counting, numbers,counting ,")

    assert response.status_code == 302
    saved = db_session.scalar(select(Worksheet).filter_by(title="Sheet"))
    assert (saved.level, saved.tags) == (3, ["counting", "numbers"])


def test_a_worksheet_uploads_without_a_level_or_tags(client, db_session, authenticated_teacher, monkeypatch):
    from models import Worksheet

    make_subject(db_session, name="Maths")

    response = _upload_worksheet(client, monkeypatch, subject="Maths", level="", tags="")

    assert response.status_code == 302
    saved = db_session.scalar(select(Worksheet).filter_by(title="Sheet"))
    assert (saved.level, saved.tags) == (None, [])


@pytest.mark.parametrize("level", ["0", "-1", "abc", "99"])
def test_an_upload_with_a_level_off_the_scale_is_refused(client, db_session, authenticated_teacher, monkeypatch, level):
    from models import Worksheet

    make_subject(db_session, name="Maths")

    response = _upload_worksheet(client, monkeypatch, subject="Maths", level=level)

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Worksheet)) == 0


def test_the_upload_form_offers_a_level_and_tags(client, db_session, authenticated_teacher):
    make_subject(db_session, name="Maths")

    page = client.get("/teacher/worksheets").get_data(as_text=True)

    assert '<select id="ws-upload-level" name="level"' in page
    assert 'id="ws-upload-tags"' in page and 'name="tags"' in page
