
import pytest
from sqlalchemy import func, select

from models import Attendance
from tests.support.factories import make_learner, make_volunteer

pytestmark = pytest.mark.web


@pytest.fixture
def roster(db_session, school, teacher):
    learner = make_learner(db_session, school, teacher, username="matched")
    volunteer = make_volunteer(db_session, school, teacher, email="matched@example.com")
    learner.volunteer_match = volunteer
    learner.is_matched = True
    volunteer.is_matched = True
    solo = make_learner(db_session, school, teacher, username="solo")
    db_session.commit()
    return learner, volunteer, solo


def log_attendance(client, rows, duration=None):
    payload = {"date": "2026-08-10", "pairs": rows}
    if duration is not None:
        payload["duration"] = duration
    return client.post("/teacher/attendance/log", json=payload)


def test_attendance_log_writes_learner_and_mirrored_volunteer_rows(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, solo = roster

    response = log_attendance(
        client,
        [
            {"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 2},
            {"learner_id": solo.id, "status": "absent"},
        ],
    )

    assert response.status_code == 200
    assert response.json["created"] == 2
    rows = db_session.scalars(select(Attendance).order_by(Attendance.user_id)).all()
    assert len(rows) == 3
    assert next(row for row in rows if row.user_id == volunteer.id).duration == 2
    assert next(row for row in rows if row.user_id == solo.id).duration == 0


def test_attendance_resubmit_updates_the_same_day_without_duplicates(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, _ = roster
    pair = {"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present"}

    assert log_attendance(client, [{**pair, "duration": 1}]).status_code == 200
    response = log_attendance(client, [{**pair, "duration": 3, "notes": "updated"}])

    assert response.status_code == 200
    assert response.json["updated"] == 1
    assert db_session.scalar(select(func.count()).select_from(Attendance)) == 2
    assert db_session.scalars(select(Attendance).filter_by(user_id=learner.id)).one().duration == 3


def test_attendance_batch_is_all_or_nothing_when_a_present_row_lacks_duration(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, solo = roster

    response = log_attendance(
        client,
        [
            {"learner_id": solo.id, "status": "present"},
            {"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 2},
        ],
    )

    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(Attendance)) == 0


def test_attendance_rejects_a_learner_outside_the_teacher_roster(
    client, db_session, authenticated_teacher, roster, school
):
    from tests.support.factories import make_teacher

    other = make_teacher(db_session, school, email="other-owner@example.com")
    foreign = make_learner(db_session, school, other, username="foreign")

    response = log_attendance(
        client,
        [{"learner_id": foreign.id, "status": "present", "duration": 1}],
    )

    assert response.status_code == 403


def _logged_record_id(client, db_session, learner, volunteer):
    log_attendance(client, [{"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 1}])
    return db_session.scalars(select(Attendance.id).filter_by(user_id=learner.id)).one()


def test_updating_attendance_never_sends_the_teacher_off_site(client, db_session, authenticated_teacher, roster):
    """A same-site Origin passes the cross-site check, so the Referer must not be trusted as the target."""
    learner, volunteer, _ = roster
    record_id = _logged_record_id(client, db_session, learner, volunteer)

    response = client.post(
        "/teacher/attendance/update",
        data={"attendance_id": record_id, "date": "2026-08-10", "status": "present", "duration": "2"},
        headers={"Origin": "http://localhost", "Referer": "https://evil.example/phish"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/teacher/attendance")


def test_updating_attendance_returns_to_the_same_site_page_it_came_from(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, _ = roster
    record_id = _logged_record_id(client, db_session, learner, volunteer)

    response = client.post(
        "/teacher/attendance/update",
        data={"attendance_id": record_id, "date": "2026-08-10", "status": "present", "duration": "2"},
        headers={"Referer": "http://localhost/teacher/attendance/history?page=2"},
    )

    assert response.headers["Location"] == "/teacher/attendance/history?page=2"


def test_an_unexpected_attendance_error_does_not_leak_its_text(
    client, db_session, authenticated_teacher, roster, monkeypatch
):
    from helpers import teacher_ops

    def explode(*_args, **_kwargs):
        raise ValueError("psycopg internals: relation attendance_pkey")

    monkeypatch.setattr(teacher_ops, "log_attendance_batch", explode)
    learner, _, _ = roster

    response = log_attendance(client, [{"learner_id": learner.id, "status": "present", "duration": 1}])

    assert response.status_code == 400
    assert "psycopg" not in response.json["message"]


def test_an_attendance_refusal_still_explains_itself(client, db_session, authenticated_teacher, roster):
    learner, _, _ = roster

    response = log_attendance(client, [{"learner_id": learner.id, "status": "present", "duration": 0}])

    assert response.status_code == 400
    assert "greater than zero" in response.json["message"]


def register_hours_inputs(client, date="2026-08-10"):
    """The register's hours inputs: ({learner id: input}, {volunteer id: input})."""
    from tests.support.html import parse

    root = parse(client.get(f"/teacher/attendance?date={date}").get_data(as_text=True))
    learners = {
        int(str(row.attrs["data-learner-id"])): row.find("input", "att-hours")
        for row in root.find_all("tr", "att-row")
    }
    volunteers = {
        int(str(head.attrs["data-volunteer-id"])): head.find("input", "att-volunteer-hours")
        for head in root.find_all("tr", "att-group-row")
        if head.attrs.get("data-volunteer-id")
    }
    return learners, volunteers


def test_register_hours_are_locked_for_absent_and_unmarked_rows(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, solo = roster
    log_attendance(
        client,
        [{"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "absent", "volunteer_status": "absent"}],
    )

    learners, volunteers = register_hours_inputs(client)

    assert "disabled" in learners[learner.id].attrs
    assert "disabled" in learners[solo.id].attrs
    assert "disabled" in volunteers[volunteer.id].attrs


def test_register_hours_stay_editable_for_present_rows(client, db_session, authenticated_teacher, roster):
    learner, volunteer, _ = roster
    log_attendance(
        client,
        [{"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 2}],
    )

    learners, volunteers = register_hours_inputs(client)

    assert "disabled" not in learners[learner.id].attrs
    assert "disabled" not in volunteers[volunteer.id].attrs


def register_note_placeholders(client, date="2026-08-10"):
    """The register's note placeholders: ({learner id: text}, {volunteer id: text})."""
    from tests.support.html import parse

    root = parse(client.get(f"/teacher/attendance?date={date}").get_data(as_text=True))
    learners = {
        int(str(row.attrs["data-learner-id"])): row.find("input", "att-note").attrs["placeholder"]
        for row in root.find_all("tr", "att-row")
    }
    volunteers = {
        int(str(head.attrs["data-volunteer-id"])): head.find("input", "att-volunteer-note").attrs["placeholder"]
        for head in root.find_all("tr", "att-group-row")
        if head.attrs.get("data-volunteer-id")
    }
    return learners, volunteers


def test_register_note_prompt_asks_why_for_absent_rows(client, db_session, authenticated_teacher, roster):
    learner, volunteer, solo = roster
    log_attendance(
        client,
        [{"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "absent", "volunteer_status": "absent"}],
    )

    learners, volunteers = register_note_placeholders(client)

    assert learners[learner.id] == "Why were they absent?"
    assert volunteers[volunteer.id] == "Why were they absent?"
    assert learners[solo.id] == "What happened in this session?"


def test_register_note_prompt_asks_what_happened_for_present_rows(
    client, db_session, authenticated_teacher, roster
):
    learner, volunteer, _ = roster
    log_attendance(
        client,
        [{"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 2}],
    )

    learners, volunteers = register_note_placeholders(client)

    assert learners[learner.id] == "What happened in this session?"
    assert volunteers[volunteer.id] == "What happened in this session?"


def test_attendance_history_can_filter_by_status(client, db_session, authenticated_teacher, roster):
    learner, volunteer, solo = roster
    log_attendance(
        client,
        [
            {"learner_id": learner.id, "volunteer_id": volunteer.id, "status": "present", "duration": 2},
            {"learner_id": solo.id, "status": "absent"},
        ],
    )

    response = client.get("/teacher/attendance/history?status=absent")

    assert response.status_code == 200
    solo_record = db_session.scalars(select(Attendance).filter_by(user_id=solo.id)).one()
    assert f'data-record-id="{solo_record.id}"' in response.get_data(as_text=True)
