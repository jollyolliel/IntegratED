"""Staged writes: propose, review, edit, apply, reject.

The load-bearing invariant is that a write tool mutates nothing — it validates
and records an `AssistantChange`. Apply then *replays the tool call* through
`helpers/teacher_ops.py` rather than writing `after` onto the row, so a staged
value that is legal-looking but breaks an invariant is still refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.support.factories import (
    make_attendance,
    make_learner,
    make_school,
    make_teacher,
    make_volunteer,
    make_worksheet,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def staging(app):
    from helpers.ai import staging as module

    with app.app_context():
        yield module


@pytest.fixture
def writes(app):
    from helpers.ai.tools import writes as module

    with app.app_context():
        yield module


@pytest.fixture
def world(db_session):
    """One teacher with a learner, a volunteer and a worksheet."""

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    volunteer = make_volunteer(db_session, school, teacher)
    worksheet = make_worksheet(db_session)
    return {
        "school": school,
        "teacher": teacher,
        "learner": learner,
        "volunteer": volunteer,
        "worksheet": worksheet,
    }


def _ctx(teacher, conversation_id=None):
    from helpers.ai.tools import ToolContext

    return ToolContext(teacher=teacher, conversation_id=conversation_id)


# ── the catalogue ────────────────────────────────────────────────────────────


def test_every_write_tool_has_a_registered_op(staging):
    """A decorated write tool with no WriteOp would fail only at call time."""

    from helpers.ai import tools

    write_tools = {name for name, tool in tools.all_tools().items() if tool.writes}
    # Two tools fan out into other ops instead of owning one: stage_auto_match
    # stages `match_pair` rows, log_attendance_batch stages one
    # `log_attendance_pair` per pair so each is reviewable on its own.
    fan_out = {"stage_auto_match", "log_attendance_batch"}

    assert write_tools - set(staging.WRITE_OPS) == fan_out


def test_staging_an_unknown_tool_is_refused(staging, db_session, world):
    with pytest.raises(ValueError, match="No staged write"):
        staging.stage(_ctx(world["teacher"]), "drop_everything", {})


# ── writes stage rather than mutate ──────────────────────────────────────────


def test_assign_worksheet_stages_and_writes_nothing(writes, db_session, world):
    from models import WorksheetAssignment

    result = writes.assign_worksheet(
        _ctx(world["teacher"]), world["learner"].id, world["worksheet"].id
    )

    assert result["staged_change_id"]
    assert db_session.scalar(select(func.count()).select_from(WorksheetAssignment)) == 0


def test_match_pair_stages_and_leaves_the_learner_unmatched(writes, db_session, world):
    writes.match_pair(_ctx(world["teacher"]), world["learner"].id, world["volunteer"].id)

    db_session.refresh(world["learner"])
    assert world["learner"].volunteer_id is None
    assert world["learner"].is_matched is False


def test_set_volunteer_capacity_stages_and_leaves_capacity_alone(writes, db_session, world):
    before = world["volunteer"].match_capacity

    writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 4)

    db_session.refresh(world["volunteer"])
    assert world["volunteer"].match_capacity == before


def test_update_attendance_stages_and_leaves_the_record_alone(writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)

    writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.0)

    db_session.refresh(record)
    assert record.duration == 1.0


def test_update_attendance_only_stages_the_arguments_given(writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)

    result = writes.update_attendance(_ctx(world["teacher"]), record.id, notes="Late")
    change = _change(result)

    assert set(change.tool_args) == {"attendance_id", "notes"}


def test_a_write_tool_reports_an_impossible_request_immediately(writes, db_session, world):
    """The model must learn in the same turn, not at apply time."""

    with pytest.raises((ValueError, LookupError, PermissionError)):
        writes.assign_worksheet(_ctx(world["teacher"]), 999_999, world["worksheet"].id)


def test_a_teacher_cannot_stage_against_another_teachers_learner(writes, db_session, world):
    outsider = make_teacher(db_session, world["school"])

    with pytest.raises((ValueError, LookupError, PermissionError)):
        writes.assign_worksheet(
            _ctx(outsider), world["learner"].id, world["worksheet"].id
        )


def _change(result):
    from extensions import db
    from models import AssistantChange

    return db.session.get(AssistantChange, result["staged_change_id"])


def test_unmatch_pair_stages_and_leaves_the_pair_intact(writes, db_session, world):
    learner, volunteer = world["learner"], world["volunteer"]
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()

    writes.unmatch_pair(_ctx(world["teacher"]), learner.id)

    db_session.refresh(learner)
    assert learner.volunteer_id == volunteer.id


def test_set_default_capacity_stages_a_school_wide_proposal(writes, db_session, world):
    result = writes.set_default_capacity(_ctx(world["teacher"]), 4)

    change = _change(result)
    assert change.status == "pending"
    assert change.tool_name == "set_default_capacity"


def test_applying_a_default_capacity_change_writes_the_teacher(staging, writes, db_session, world):
    """The default for newly registering volunteers lives on the teacher."""

    result = writes.set_default_capacity(_ctx(world["teacher"]), 4)

    staging.apply_change(world["teacher"], result["staged_change_id"])

    db_session.refresh(world["teacher"])
    assert world["teacher"].default_match_capacity == 4


# ── batch tools fan out into one reviewable change per row ───────────────────


def test_log_attendance_batch_stages_one_change_per_pair(writes, db_session, world):
    from models import Attendance

    second = make_learner(db_session, world["school"], world["teacher"])

    result = writes.log_attendance_batch(
        _ctx(world["teacher"]),
        "2026-03-04",
        [
            {"learner_id": world["learner"].id, "is_present": True, "duration": 1.5},
            {"learner_id": second.id, "is_present": True, "duration": 2.0},
        ],
    )

    assert len(result["staged"]) == 2
    assert result["skipped"] == []
    assert db_session.scalar(select(func.count()).select_from(Attendance)) == 0


def test_one_bad_pair_does_not_cost_the_rest_their_changes(writes, db_session, world):
    result = writes.log_attendance_batch(
        _ctx(world["teacher"]),
        "2026-03-04",
        [
            {"learner_id": world["learner"].id, "is_present": True, "duration": 1.5},
            {"learner_id": 999_999, "is_present": True, "duration": 1.0},
        ],
    )

    assert len(result["staged"]) == 1
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"]


def test_applying_a_staged_attendance_pair_writes_the_record(staging, writes, db_session, world):
    from models import Attendance

    result = writes.log_attendance_batch(
        _ctx(world["teacher"]),
        "2026-03-04",
        [{"learner_id": world["learner"].id, "is_present": True, "duration": 1.5}],
    )

    staging.apply_change(world["teacher"], result["staged"][0]["staged_change_id"])

    record = db_session.scalars(select(Attendance).filter_by(user_id=world["learner"].id)).one()
    assert record.duration == 1.5
    assert record.is_present is True


def test_stage_auto_match_proposes_a_change_per_pairing(writes, db_session, world):
    result = writes.stage_auto_match(_ctx(world["teacher"]))

    assert len(result["staged"]) == 1
    assert result["staged"][0]["learner_id"] == world["learner"].id


def test_stage_auto_match_skips_proposals_below_a_score_floor(writes, db_session, world):
    result = writes.stage_auto_match(_ctx(world["teacher"]), min_score=10_000)

    assert result["staged"] == []
    assert len(result["skipped"]) == 1


def test_stage_auto_match_ignores_a_junk_score_floor(writes, db_session, world):
    result = writes.stage_auto_match(_ctx(world["teacher"]), min_score="high")

    assert len(result["staged"]) == 1


# ── review payload ───────────────────────────────────────────────────────────


def test_the_review_payload_marks_changed_and_editable_fields(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.5)

    payload = staging.change_payload(_change(result))

    assert payload["tool"] == "update_attendance"
    assert payload["status"] == "pending"
    duration = next(row for row in payload["fields"] if row["field"] == "duration")
    assert duration["before"] == 1.0
    assert duration["after"] == 2.5
    assert duration["changed"] is True
    assert duration["editable"] is True


def test_pending_changes_are_ordered_by_sequence(staging, writes, db_session, world):
    ctx = _ctx(world["teacher"])
    first = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    writes.update_attendance(ctx, first.id, duration=2.0)
    writes.set_volunteer_capacity(ctx, world["volunteer"].id, 3)

    pending = staging.pending_changes(world["teacher"])

    assert [change.seq for change in pending] == [0, 1]


def test_another_teachers_change_is_not_readable(staging, writes, db_session, world):
    outsider = make_teacher(db_session, world["school"])
    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)

    with pytest.raises(PermissionError):
        staging.get_change(outsider, result["staged_change_id"])


def test_a_missing_change_raises_lookup_error(staging, db_session, world):
    with pytest.raises(LookupError):
        staging.get_change(world["teacher"], 999_999)


# ── editing ──────────────────────────────────────────────────────────────────


def test_a_teacher_can_edit_a_staged_value(staging, writes, db_session, world):
    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)

    updated = staging.update_change(
        world["teacher"], result["staged_change_id"], {"match_capacity": 5}
    )

    assert updated.after["match_capacity"] == 5
    assert updated.tool_args["capacity"] == 5


def test_an_edit_that_breaks_an_invariant_is_refused_at_edit_time(staging, writes, db_session, world):
    """Re-validation happens on edit, not only on apply."""

    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)

    with pytest.raises(ValueError):
        staging.update_change(
            world["teacher"], result["staged_change_id"], {"match_capacity": 99}
        )


def test_a_non_editable_column_cannot_be_edited(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.0)

    with pytest.raises(ValueError, match="cannot be edited"):
        staging.update_change(
            world["teacher"], result["staged_change_id"], {"id": 12}
        )


# ── apply ────────────────────────────────────────────────────────────────────


def test_applying_replays_the_tool_and_writes_the_row(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.5)

    applied = staging.apply_change(world["teacher"], result["staged_change_id"])

    db_session.refresh(record)
    assert applied.status == "applied"
    assert applied.applied_at is not None
    assert record.duration == 2.5


def test_applying_a_match_updates_both_sides(staging, writes, db_session, world):
    result = writes.match_pair(
        _ctx(world["teacher"]), world["learner"].id, world["volunteer"].id
    )

    staging.apply_change(world["teacher"], result["staged_change_id"])

    db_session.refresh(world["learner"])
    db_session.refresh(world["volunteer"])
    assert world["learner"].volunteer_id == world["volunteer"].id
    assert world["learner"].is_matched is True
    assert world["volunteer"].is_matched is True


def test_applying_twice_is_refused(staging, writes, db_session, world):
    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)
    staging.apply_change(world["teacher"], result["staged_change_id"])

    with pytest.raises(ValueError, match="already applied"):
        staging.apply_change(world["teacher"], result["staged_change_id"])


def test_a_change_becomes_stale_when_the_row_moved_underneath_it(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.5)

    record.duration = 4.0
    db_session.commit()

    applied = staging.apply_change(world["teacher"], result["staged_change_id"])

    assert applied.status == "stale"
    assert applied.error
    db_session.refresh(record)
    assert record.duration == 4.0


def test_a_change_is_stale_when_the_row_was_deleted(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.5)
    change = _change(result)

    db_session.delete(record)
    db_session.commit()

    assert staging.staleness(change) == {"__row__": {"was": "present", "now": "deleted"}}


def test_a_freshly_staged_change_is_not_stale(staging, writes, db_session, world):
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    result = writes.update_attendance(_ctx(world["teacher"]), record.id, duration=2.5)

    assert staging.staleness(_change(result)) == {}


# ── reject ───────────────────────────────────────────────────────────────────


def test_rejecting_leaves_the_row_untouched(staging, writes, db_session, world):
    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)
    before = world["volunteer"].match_capacity

    rejected = staging.reject_change(world["teacher"], result["staged_change_id"])

    db_session.refresh(world["volunteer"])
    assert rejected.status == "rejected"
    assert world["volunteer"].match_capacity == before


def test_a_rejected_change_cannot_be_applied(staging, writes, db_session, world):
    result = writes.set_volunteer_capacity(_ctx(world["teacher"]), world["volunteer"].id, 3)
    staging.reject_change(world["teacher"], result["staged_change_id"])

    with pytest.raises(ValueError, match="already rejected"):
        staging.apply_change(world["teacher"], result["staged_change_id"])


# ── apply_all ────────────────────────────────────────────────────────────────


def test_apply_all_reports_one_outcome_per_change(staging, writes, db_session, world):
    ctx = _ctx(world["teacher"])
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    writes.update_attendance(ctx, record.id, duration=2.0)
    writes.set_volunteer_capacity(ctx, world["volunteer"].id, 3)

    results = staging.apply_all(world["teacher"])

    assert len(results) == 2
    assert {r["status"] for r in results} == {"applied"}
    assert staging.pending_changes(world["teacher"]) == []


def test_apply_all_keeps_going_after_one_change_goes_stale(staging, writes, db_session, world):
    ctx = _ctx(world["teacher"])
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    writes.update_attendance(ctx, record.id, duration=2.0)
    writes.set_volunteer_capacity(ctx, world["volunteer"].id, 3)

    record.duration = 9.0
    db_session.commit()

    results = staging.apply_all(world["teacher"])

    assert [r["status"] for r in results] == ["stale", "applied"]
    db_session.refresh(world["volunteer"])
    assert world["volunteer"].match_capacity == 3


def test_pending_changes_from_two_turns_keep_turn_order(staging, writes, db_session, world):
    # seq restarts at 0 every turn, so sorting by it interleaved the turns.
    first_turn, second_turn = _ctx(world["teacher"]), _ctx(world["teacher"])
    record = make_attendance(db_session, world["teacher"], world["learner"], duration=1.0)
    a = writes.update_attendance(first_turn, record.id, duration=2.0)["staged_change_id"]
    b = writes.set_volunteer_capacity(first_turn, world["volunteer"].id, 3)["staged_change_id"]
    c = writes.update_attendance(second_turn, record.id, duration=3.0)["staged_change_id"]
    d = writes.set_volunteer_capacity(second_turn, world["volunteer"].id, 4)["staged_change_id"]

    pending = staging.pending_changes(world["teacher"])

    assert [change.id for change in pending] == [a, b, c, d]
