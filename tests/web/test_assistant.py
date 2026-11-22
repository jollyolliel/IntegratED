
import pytest

pytestmark = pytest.mark.web


def test_non_teacher_cannot_read_assistant(client, db_session, authenticated_learner):
    assert client.get("/assistant/conversation").status_code == 403


def test_teacher_without_history_gets_an_empty_conversation(client, db_session, authenticated_teacher):
    response = client.get("/assistant/conversation")

    assert response.status_code == 200
    assert response.json == {"conversation_id": None, "messages": []}


def test_teacher_can_create_and_list_an_assistant_conversation(client, db_session, authenticated_teacher):
    created = client.post("/assistant/conversation/new")
    listed = client.get("/assistant/conversations")

    assert created.status_code == 200
    assert listed.json["conversations"][0]["id"] == created.json["conversation_id"]


def test_empty_assistant_message_is_rejected(client, db_session, authenticated_teacher):
    response = client.post("/assistant/message", data={"message": "  "})

    assert response.status_code == 400
    assert response.json["success"] is False


def test_assistant_message_stream_is_bytes_and_has_stream_headers(
    client, db_session, authenticated_teacher, monkeypatch
):
    from routes import assistant

    monkeypatch.setattr(
        assistant.loop,
        "run_turn",
        lambda teacher_id, conversation_id, text, lang: iter(
            [{"type": "answer", "text": "hello"}, {"type": "done"}]
        ),
    )

    response = client.post("/assistant/message", data={"message": "hello"})
    body = b"".join(response.response)

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-store"
    assert b'"type": "answer"' in body
    assert all(isinstance(frame, bytes) for frame in [body])


def test_assistant_history_is_private_to_each_teacher(client, db_session, teacher, school):
    from models import AssistantConversation
    from tests.support.factories import make_teacher

    other = make_teacher(db_session, school, email="other-teacher@example.com")
    db_session.add(AssistantConversation(teacher_id=other.id, title="private"))
    db_session.commit()

    from tests.support.auth import login_as
    login_as(client, teacher)
    response = client.get("/assistant/conversations")

    assert response.json["conversations"] == []


# ── the staged-change review surface ─────────────────────────────────────────


@pytest.fixture
def staged(db_session, authenticated_teacher):
    """One pending change belonging to the signed-in teacher."""

    from helpers.ai.tools import ToolContext, writes
    from tests.support.factories import make_attendance, make_learner, make_volunteer

    teacher = authenticated_teacher
    school = teacher.school
    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)
    record = make_attendance(db_session, teacher, learner, duration=1.0)
    result = writes.update_attendance(
        ToolContext(teacher=teacher), record.id, duration=2.5
    )
    return {
        "teacher": teacher,
        "school": school,
        "learner": learner,
        "volunteer": volunteer,
        "record": record,
        "change_id": result["staged_change_id"],
    }


def test_pending_changes_are_listed(client, db_session, staged):
    response = client.get("/assistant/changes")

    assert response.status_code == 200
    assert [c["id"] for c in response.json["changes"]] == [staged["change_id"]]


def test_applying_a_change_writes_the_row(client, db_session, staged):
    response = client.post(f"/assistant/changes/{staged['change_id']}/apply")

    assert response.status_code == 200
    assert response.json["success"] is True
    db_session.expire_all()
    assert staged["record"].duration == 2.5


def test_a_refused_apply_explains_why(client, db_session, staged):
    client.post(f"/assistant/changes/{staged['change_id']}/apply")

    response = client.post(f"/assistant/changes/{staged['change_id']}/apply")

    assert response.json["message"] == "That change is already applied."


def test_an_unexpected_apply_error_does_not_leak_its_text(client, db_session, staged, monkeypatch):
    from helpers.ai import staging

    def explode(*_args, **_kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr(staging, "apply_change", explode)

    response = client.post(f"/assistant/changes/{staged['change_id']}/apply")

    assert response.status_code == 400
    assert "internal detail" not in response.json["message"]


def test_apply_all_does_not_leak_unexpected_error_text(client, db_session, staged, monkeypatch):
    from helpers.ai import staging

    def explode(*_args, **_kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr(staging, "apply_change", explode)

    response = client.post("/assistant/changes/apply-all")

    assert response.json["results"][0]["status"] == "failed"
    assert "internal detail" not in response.json["results"][0]["error"]


def test_applying_a_stale_change_reports_a_conflict(client, db_session, staged):
    staged["record"].duration = 9.0
    db_session.commit()

    response = client.post(f"/assistant/changes/{staged['change_id']}/apply")

    assert response.status_code == 409
    assert response.json["status"] == "stale"
    db_session.expire_all()
    assert staged["record"].duration == 9.0


def test_applying_an_unknown_change_is_a_404(client, db_session, authenticated_teacher):
    assert client.post("/assistant/changes/999999/apply").status_code == 404


def test_another_teachers_change_cannot_be_applied(client, db_session, staged):
    from tests.support.auth import login_as
    from tests.support.factories import make_teacher

    outsider = make_teacher(db_session, staged["school"])
    login_as(client, outsider)

    assert client.post(f"/assistant/changes/{staged['change_id']}/apply").status_code == 403


def test_applying_a_change_twice_reports_the_reason(client, db_session, staged):
    client.post(f"/assistant/changes/{staged['change_id']}/apply")

    response = client.post(f"/assistant/changes/{staged['change_id']}/apply")

    assert response.status_code == 400
    assert response.json["success"] is False


def test_rejecting_a_change_leaves_the_row_alone(client, db_session, staged):
    response = client.post(f"/assistant/changes/{staged['change_id']}/reject")

    assert response.status_code == 200
    db_session.expire_all()
    assert staged["record"].duration == 1.0
    assert response.json["changes"] == []


def test_a_staged_value_can_be_edited_before_applying(client, db_session, staged):
    response = client.post(
        f"/assistant/changes/{staged['change_id']}/update",
        json={"values": {"duration": 4.0}},
    )

    assert response.status_code == 200
    client.post(f"/assistant/changes/{staged['change_id']}/apply")
    db_session.expire_all()
    assert staged["record"].duration == 4.0


def test_an_update_with_no_values_is_refused(client, db_session, staged):
    response = client.post(f"/assistant/changes/{staged['change_id']}/update", json={})

    assert response.status_code == 400
    assert response.json["message"] == "Nothing to change."


def test_editing_a_field_that_is_not_editable_is_refused(client, db_session, staged):
    response = client.post(
        f"/assistant/changes/{staged['change_id']}/update", json={"values": {"id": 3}}
    )

    assert response.status_code == 400


def test_editing_another_teachers_change_is_refused(client, db_session, staged):
    from tests.support.auth import login_as
    from tests.support.factories import make_teacher

    login_as(client, make_teacher(db_session, staged["school"]))

    response = client.post(
        f"/assistant/changes/{staged['change_id']}/update",
        json={"values": {"duration": 3.0}},
    )

    assert response.status_code == 403


def test_apply_all_applies_every_pending_change(client, db_session, staged):
    from helpers.ai.tools import ToolContext, writes

    writes.set_volunteer_capacity(
        ToolContext(teacher=staged["teacher"]), staged["volunteer"].id, 3
    )

    response = client.post("/assistant/changes/apply-all")

    assert response.status_code == 200
    assert response.json["applied"] == 2
    assert response.json["changes"] == []


def test_apply_all_with_nothing_pending_is_harmless(client, db_session, authenticated_teacher):
    response = client.post("/assistant/changes/apply-all")

    assert response.status_code == 200
    assert response.json["applied"] == 0


# ── SSE framing ──────────────────────────────────────────────────────────────


def test_a_stream_frame_is_encoded_bytes(app):
    """`direct_passthrough` skips Werkzeug's encoding, so a str would raise."""

    from routes.assistant import _frame

    frame = _frame({"type": "done"})

    assert isinstance(frame, bytes)
    assert frame.startswith(b"data: ")
    assert frame.endswith(b"\n\n")


def test_a_message_longer_than_the_cap_is_truncated(
    client, db_session, authenticated_teacher, monkeypatch
):
    from routes import assistant

    seen = {}

    def fake_run_turn(teacher_id, conversation_id, text, lang):
        seen["text"] = text
        return iter([{"type": "done"}])

    monkeypatch.setattr(assistant.loop, "run_turn", fake_run_turn)

    response = client.post("/assistant/message", data={"message": "x" * 5000})
    b"".join(response.response)

    assert len(seen["text"]) == assistant.MAX_MESSAGE_CHARS


def test_a_stream_that_blows_up_still_closes_cleanly(
    client, db_session, authenticated_teacher, monkeypatch
):
    """A raise inside the generator would otherwise truncate the stream."""

    from routes import assistant

    def explode(teacher_id, conversation_id, text, lang):
        raise RuntimeError("kaboom")
        yield  # pragma: no cover

    monkeypatch.setattr(assistant.loop, "run_turn", explode)

    response = client.post("/assistant/message", data={"message": "hi"})
    body = b"".join(response.response)

    assert b'"type": "error"' in body
    assert b'"type": "done"' in body


def test_a_message_can_continue_a_named_conversation(
    client, db_session, authenticated_teacher, monkeypatch
):
    from routes import assistant

    seen = {}

    def fake_run_turn(teacher_id, conversation_id, text, lang):
        seen["conversation_id"] = conversation_id
        return iter([{"type": "done"}])

    monkeypatch.setattr(assistant.loop, "run_turn", fake_run_turn)
    created = client.post("/assistant/conversation/new").json["conversation_id"]

    response = client.post(
        "/assistant/message", data={"message": "hi", "conversation_id": created}
    )
    b"".join(response.response)

    assert seen["conversation_id"] == created
