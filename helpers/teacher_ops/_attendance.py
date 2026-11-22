from datetime import date as date_cls
from datetime import datetime
from typing import Any, TypedDict

from extensions import db
from helpers.teacher_ops._shared import _coerce_bool, _coerce_date, _owned
from helpers.utils import day_bounds
from models import Attendance, Learner, Teacher, Volunteer

# What the coercion helpers accept before normalizing. Callers hand these
# straight from a form payload or an assistant tool call, so the raw string
# forms are part of the contract, not a caller mistake.
DateInput = str | date_cls | datetime
BoolInput = bool | str
DurationInput = str | float | int


class AttendanceEdit(TypedDict):
    """One person's attendance row, normalized but not yet written."""
    record: Attendance
    date: date_cls
    is_present: bool
    duration: float
    notes: str | None


class UpdatedAttendance(TypedDict):
    """The committed row from `update_user_attendance`."""
    record: Attendance


class VolunteerSide(TypedDict):
    """A volunteer's own numbers for one pair, before collapsing."""
    volunteer: Volunteer
    is_present: bool
    duration: float
    notes: str | None


class CollapsedVolunteerSide(TypedDict):
    """A volunteer's single record for the day, across every learner held.

    `partner_id` is set only while "who they sat with" has one answer — a
    volunteer holding several learners that day has no single partner.
    """
    volunteer: Volunteer
    is_present: bool
    duration: float
    notes: str | None
    partner_id: int | None


class ResolvedPair(TypedDict):
    """One validated pair from a roster save."""
    learner: Learner
    volunteer: Volunteer | None
    is_present: bool
    duration: float
    notes: str | None
    volunteer_resolved: VolunteerSide | None


class AttendanceBatch(TypedDict):
    """A whole roster save, normalized and ready to write."""
    date: date_cls
    pairs: list[ResolvedPair]
    volunteers: list[CollapsedVolunteerSide]


class AttendanceBatchResult(TypedDict):
    """Counts and rows from a committed roster save.

    Counts are per pair (one session logged), not per Attendance row — a pair
    with a volunteer writes a second row but is not a second session.
    """
    date: date_cls
    created: int
    updated: int
    present: int
    absent: int
    total_hours: float
    records: list[Attendance]


def validate_update_user_attendance(teacher: Teacher, attendance_id: int, date: DateInput | None = None,
                                    is_present: BoolInput | None = None,
                                    duration: DurationInput | None = None, notes: str | None = None) -> AttendanceEdit:
    """Normalize one person's own attendance record, addressed purely by id. Omitted fields keep the row's current value.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        attendance_id (int): Record to update.
        date (DateInput | None): New session date, or None to keep the current one.
        is_present (BoolInput | None): New present/absent value, or None to keep the current one.
        duration (DurationInput | None): New duration in hours, or None to keep/derive it.
        notes (str | None): New notes, or None to keep the current ones.

    Returns:
        AttendanceEdit: The normalized values, not yet written.
    """
    record = _owned(Attendance, attendance_id, teacher, "attendance record")

    new_date = _coerce_date(date) if date is not None else record.date.date()

    new_is_present = record.is_present
    if is_present is not None:
        new_is_present = _coerce_bool(is_present)

    # Absent forces duration = 0.0 — an absence carrying hours would show up in
    # a service-hours certificate. A present session must carry more than
    # zero, or "present"/"absent" become indistinguishable in the sums.
    if not new_is_present:
        new_duration = 0.0
    elif duration is not None:
        try:
            new_duration = float(duration)
        except (TypeError, ValueError):
            raise ValueError("Enter a duration greater than zero for a session that took place.")
        if new_duration <= 0:
            raise ValueError("Enter a duration greater than zero for a session that took place.")
    else:
        new_duration = float(record.duration or 0)
        if new_duration <= 0:
            raise ValueError("Enter a duration greater than zero for a session that took place.")

    new_notes = record.notes
    if notes is not None:
        new_notes = (str(notes) or "").strip() or None

    return {
        "record": record,
        "date": new_date,
        "is_present": new_is_present,
        "duration": new_duration,
        "notes": new_notes,
    }


def update_user_attendance(teacher: Teacher, attendance_id: int, date: DateInput | None = None,
                           is_present: BoolInput | None = None,
                           duration: DurationInput | None = None, notes: str | None = None) -> UpdatedAttendance:
    """Apply a normalized attendance edit and commit.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        attendance_id (int): Record to update.
        date (DateInput | None): New session date, or None to keep the current one.
        is_present (BoolInput | None): New present/absent value, or None to keep the current one.
        duration (DurationInput | None): New duration in hours, or None to keep/derive it.
        notes (str | None): New notes, or None to keep the current ones.

    Returns:
        UpdatedAttendance: The updated Attendance row.
    """
    resolved = validate_update_user_attendance(
        teacher, attendance_id, date=date, is_present=is_present,
        duration=duration, notes=notes,
    )
    record = resolved["record"]
    day = resolved["date"]
    record.date = datetime(day.year, day.month, day.day)
    record.is_present = resolved["is_present"]
    record.duration = resolved["duration"]
    record.notes = resolved["notes"]
    db.session.commit()
    return {"record": record}


def _resolve_side(label: str, is_present: bool, duration_raw: DurationInput | None, default_duration: float | None, mirror_duration: float | None) -> float:
    """Shared present/absent + duration normalization for one side (a learner's own numbers, or a volunteer's).

    Args:
        label (str): Person's display name, for error messages.
        is_present (bool): Whether this side was present.
        duration_raw (DurationInput | None): Duration as submitted, possibly unset.
        default_duration (float | None): Batch-wide fallback duration.
        mirror_duration (float | None): Fallback duration mirrored from the other side.

    Returns:
        float: The resolved duration in hours (0.0 if absent).
    """
    if not is_present:
        return 0.0
    if duration_raw not in (None, ""):
        try:
            duration = float(duration_raw)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid duration for {label}.")
    elif default_duration is not None:
        duration = default_duration
    elif mirror_duration is not None:
        # A present side with no duration of its own falls back to the
        # batch default for a learner, or the learner's own resolved
        # duration for a mirrored volunteer.
        duration = mirror_duration
    else:
        raise ValueError(f"Enter a duration for {label}'s session.")
    if duration <= 0:
        raise ValueError(f"Enter a duration greater than zero for {label}'s session.")
    return duration


def validate_log_attendance_batch(teacher: Teacher, date: DateInput, pairs: list[dict[str, Any]], default_duration: DurationInput | None = None) -> AttendanceBatch:
    """Normalize a full roster save into one resolved dict per pair. Raises on the first invalid pair — a batch commits all-or-nothing.

    Args:
        teacher (Teacher): Teacher logging the batch.
        date (DateInput): Session date for the whole batch.
        pairs (list[dict[str, Any]]): One dict per pair (`learner_id`,
            `volunteer_id`, `is_present`, `duration`, `notes`, and the
            volunteer-side overrides). Raw caller payload, so keys are optional.
        default_duration (DurationInput | None): Fallback duration for a pair that omits its own.

    Returns:
        AttendanceBatch: The batch normalized and ready to write.
    """
    if not pairs:
        raise ValueError("No pairs to log.")

    session_date = _coerce_date(date)

    default = None
    if default_duration not in (None, ""):
        try:
            default = float(default_duration)
        except (TypeError, ValueError):
            raise ValueError("Invalid default duration.")

    resolved_pairs: list[ResolvedPair] = []
    for pair in pairs:
        learner_id = pair.get("learner_id")
        if not isinstance(learner_id, int):
            # ValueError (not TypeError) is intentional: this validation error
            # must be catchable the same way as every other one in this
            # function, and by the assistant loop's ValueError/LookupError/
            # PermissionError -> fed-back-to-model contract (docs/features/ai-assistant.md).
            raise ValueError("Each pair needs a learner_id.")  # noqa: TRY004
        learner = _owned(Learner, learner_id, teacher, "learner")
        label = learner.name or learner.username

        volunteer = None
        v_id = pair.get("volunteer_id")
        if v_id:
            volunteer = _owned(Volunteer, v_id, teacher, "volunteer")

        is_present = _coerce_bool(pair.get("is_present", True))
        duration = _resolve_side(label, is_present, pair.get("duration"), default, None)

        notes = (str(pair.get("notes") or "").strip() or None)

        # Mirrors the learner's own numbers unless the pair explicitly carries
        # its own volunteer_is_present / volunteer_duration / volunteer_notes.
        volunteer_resolved: VolunteerSide | None = None
        if volunteer is not None:
            v_label = volunteer.name or volunteer.email
            if pair.get("volunteer_is_present") is not None:
                v_is_present = _coerce_bool(pair["volunteer_is_present"])
            else:
                v_is_present = is_present
            v_duration = _resolve_side(
                v_label, v_is_present, pair.get("volunteer_duration"), None, duration
            )
            v_notes = pair.get("volunteer_notes")
            v_notes = (str(v_notes).strip() or None) if v_notes is not None else notes
            volunteer_resolved = {
                "volunteer": volunteer,
                "is_present": v_is_present,
                "duration": v_duration,
                "notes": v_notes,
            }

        resolved_pairs.append({
            "learner": learner,
            "volunteer": volunteer,
            "is_present": is_present,
            "duration": duration,
            "notes": notes,
            "volunteer_resolved": volunteer_resolved,
        })

    return {
        "date": session_date,
        "pairs": resolved_pairs,
        "volunteers": _collapse_volunteer_sides(resolved_pairs),
    }


def _collapse_volunteer_sides(resolved_pairs: list[ResolvedPair]) -> list[CollapsedVolunteerSide]:
    """The batch's per-pair volunteer sides, collapsed to one entry per volunteer (they sit one session, not one per learner held).

    Args:
        resolved_pairs (list[ResolvedPair]): Pairs from `validate_log_attendance_batch`.

    Returns:
        list[CollapsedVolunteerSide]: One entry per volunteer.
    """
    entries: dict[int, CollapsedVolunteerSide] = {}
    for pair in resolved_pairs:
        vr = pair["volunteer_resolved"]
        if not vr:
            continue
        entry = entries.get(vr["volunteer"].id)
        if entry is None:
            entries[vr["volunteer"].id] = {
                "volunteer": vr["volunteer"],
                "is_present": vr["is_present"],
                "duration": vr["duration"],
                "notes": vr["notes"],
                # Who they sat with, only while that has a single answer — a
                # group of several learners has no one partner, and each
                # learner's own record already names the volunteer.
                "partner_id": pair["learner"].id,
            }
            continue
        entry["is_present"] = entry["is_present"] or vr["is_present"]
        # Disagreeing rows describe the same stretch of time, so the longest
        # covers it — summing would restore the per-learner double count.
        entry["duration"] = max(entry["duration"], vr["duration"])
        entry["notes"] = entry["notes"] or vr["notes"]
        entry["partner_id"] = None
    return list(entries.values())


def _upsert_attendance(teacher: Teacher, day_dt: datetime, user_id: int, partner_id: int | None, is_present: bool, duration: float, notes: str | None) -> tuple[bool, Attendance]:
    """Create-or-update, keyed by the natural key (date, user_id, partner_id).

    Args:
        teacher (Teacher): Teacher logging the session.
        day_dt (datetime): Session date/time.
        user_id (int): The person this record is about.
        partner_id (int | None): Their partner for the session, if any.
        is_present (bool): Whether they were present.
        duration (float): Session duration in hours.
        notes (str | None): Optional notes.

    Returns:
        tuple[bool, Attendance]: `(created, record)`.
    """
    day_start, day_end = day_bounds(day_dt.date())
    record = db.session.scalar(
        db.select(Attendance).where(
            Attendance.date >= day_start, Attendance.date < day_end,
            Attendance.user_id == user_id, Attendance.partner_id == partner_id,
        )
    )
    if record:
        record.date = day_dt
        record.is_present = is_present
        record.duration = duration
        record.notes = notes
        record.teacher_id = teacher.id
        return False, record
    record = Attendance(
        date=day_dt, is_present=is_present, duration=duration, notes=notes,
        teacher_id=teacher.id, user_id=user_id, partner_id=partner_id,
    )
    db.session.add(record)
    return True, record


def _upsert_volunteer_day(teacher: Teacher, day_dt: datetime, volunteer_id: int, partner_id: int | None, is_present: bool, duration: float, notes: str | None) -> Attendance:
    """The volunteer's one record for the day, found by (date, user_id) alone — not `partner_id`, which would double it per learner held.

    Args:
        teacher (Teacher): Teacher logging the session.
        day_dt (datetime): Session date/time.
        volunteer_id (int): The volunteer this record is about.
        partner_id (int | None): The one learner they sat with, if unambiguous.
        is_present (bool): Whether they were present.
        duration (float): Session duration in hours.
        notes (str | None): Optional notes.

    Returns:
        Attendance: The created or updated record.
    """
    day_start, day_end = day_bounds(day_dt.date())
    records = db.session.scalars(
        db.select(Attendance)
        .where(
            Attendance.date >= day_start, Attendance.date < day_end,
            Attendance.user_id == volunteer_id,
        )
        .order_by(Attendance.id)
    ).all()
    # Any extra rows an earlier (partner_id-keyed) scheme left behind are
    # collapsed into the one kept, so hours can't stay doubled once saved again.
    for extra in records[1:]:
        db.session.delete(extra)

    if records:
        record = records[0]
        record.date = day_dt
        record.partner_id = partner_id
        record.is_present = is_present
        record.duration = duration
        record.notes = notes
        record.teacher_id = teacher.id
        return record

    record = Attendance(
        date=day_dt, is_present=is_present, duration=duration, notes=notes,
        teacher_id=teacher.id, user_id=volunteer_id, partner_id=partner_id,
    )
    db.session.add(record)
    return record


def log_attendance_batch(teacher: Teacher, date: DateInput, pairs: list[dict[str, Any]], default_duration: DurationInput | None = None) -> AttendanceBatchResult:
    """Create-or-update every pair's learner record, plus one mirrored record per volunteer in the batch (not one per pair).

    Args:
        teacher (Teacher): Teacher logging the batch.
        date (DateInput): Session date for the whole batch.
        pairs (list[dict[str, Any]]): One dict per pair, see `validate_log_attendance_batch`.
        default_duration (DurationInput | None): Fallback duration for a pair that omits its own.

    Returns:
        AttendanceBatchResult: Counts and the rows written.
    """
    resolved = validate_log_attendance_batch(teacher, date, pairs, default_duration=default_duration)
    session_date = resolved["date"]
    day_dt = datetime(session_date.year, session_date.month, session_date.day)

    # Counted per pair (one session logged), not per Attendance row — a pair
    # with a volunteer writes a second row but isn't a second session.
    created = updated = present = absent = 0
    total_hours = 0.0
    records = []
    for pair in resolved["pairs"]:
        learner, volunteer = pair["learner"], pair["volunteer"]

        was_created, learner_record = _upsert_attendance(
            teacher, day_dt,
            user_id=learner.id, partner_id=volunteer.id if volunteer else None,
            is_present=pair["is_present"], duration=pair["duration"], notes=pair["notes"],
        )
        created += was_created
        updated += not was_created
        present += pair["is_present"]
        absent += not pair["is_present"]
        if pair["is_present"]:
            total_hours += pair["duration"]
        records.append(learner_record)

    for entry in resolved["volunteers"]:
        records.append(_upsert_volunteer_day(
            teacher, day_dt,
            volunteer_id=entry["volunteer"].id, partner_id=entry["partner_id"],
            is_present=entry["is_present"], duration=entry["duration"],
            notes=entry["notes"],
        ))

    db.session.commit()
    return {
        "date": session_date, "created": created, "updated": updated,
        "present": present, "absent": absent, "total_hours": total_hours,
        "records": records,
    }


# ── single-pair entry points for the assistant ───────────────────────────────
# The batch functions above do the real work; these just call them with a
# one-item list, so a staged write can validate/apply one pair on its own
# instead of the roster sheet's all-or-nothing commit.

def validate_log_attendance_pair(teacher: Teacher, date: DateInput, pair: dict[str, Any], default_duration: DurationInput | None = None) -> AttendanceBatch:
    """Single-pair wrapper around `validate_log_attendance_batch`.

    Args:
        teacher (Teacher): Teacher logging the session.
        date (DateInput): Session date.
        pair (dict[str, Any]): The one pair to validate.
        default_duration (DurationInput | None): Fallback duration if the pair omits its own.

    Returns:
        AttendanceBatch: Same shape as `validate_log_attendance_batch`, for one pair.
    """
    return validate_log_attendance_batch(teacher, date, [pair], default_duration=default_duration)


def log_attendance_pair(teacher: Teacher, date: DateInput, pair: dict[str, Any], default_duration: DurationInput | None = None) -> AttendanceBatchResult:
    """Single-pair wrapper around `log_attendance_batch`.

    Args:
        teacher (Teacher): Teacher logging the session.
        date (DateInput): Session date.
        pair (dict[str, Any]): The one pair to log.
        default_duration (DurationInput | None): Fallback duration if the pair omits its own.

    Returns:
        AttendanceBatchResult: Same shape as `log_attendance_batch`, for one pair.
    """
    return log_attendance_batch(teacher, date, [pair], default_duration=default_duration)
