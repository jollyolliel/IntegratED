from datetime import date, datetime, timedelta
from typing import Any

from flask import abort, flash, jsonify, redirect, request, url_for
from sqlalchemy import case, func
from werkzeug.exceptions import Forbidden

from extensions import db
from helpers import teacher_ops
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.refusal import refusal_message
from helpers.render import render_template
from helpers.utils import (
    day_bounds,
    same_site_referrer_path,
    wants_fragment,
    wants_json,
)
from models import Attendance, Learner
from routes.teacher import teacher_bp
from routes.teacher.dashboard import _learner_sort_key, _volunteer_sort_key

ATTENDANCE_PAGE_SIZE = 25

# Preset -> how many days back from today the range starts. None = no lower bound.
_HISTORY_RANGES = {"today": 0, "week": 6, "month": 29, "all": None}


def _parse_date_arg(value):
    """'YYYY-MM-DD' -> date, or None when absent/malformed."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _attendance_history_query(teacher, filters):
    """Filtered Attendance query for one teacher, scoped to the learners' own
    records — one row per session logged, matching what the sheet counts as
    "a session". The volunteer side is joined in separately per page (see
    `teacher_attendance_history`), never counted as a second session here."""
    stmt = (
        db.select(Attendance)
        .join(Learner, Learner.id == Attendance.user_id)
        .where(Attendance.teacher_id == teacher.id)
    )

    if filters["learner_id"]:
        stmt = stmt.where(Attendance.user_id == filters["learner_id"])
    if filters["volunteer_id"]:
        stmt = stmt.where(Attendance.partner_id == filters["volunteer_id"])
    if filters["status"] in ("present", "absent"):
        stmt = stmt.where(Attendance.is_present == (filters["status"] == "present"))
    if filters["date_from"]:
        stmt = stmt.where(Attendance.date >= day_bounds(filters["date_from"])[0])
    if filters["date_to"]:
        stmt = stmt.where(Attendance.date < day_bounds(filters["date_to"])[1])

    return stmt


def _volunteer_records_for(records):
    """Each learner record's matching volunteer own-record, keyed by the
    learner record's id — the volunteer's single record for that day, found by
    the volunteer alone: they keep one record however many learners they hold,
    so it names at most one of them back. One lookup per row (page-sized,
    never the whole table)."""
    by_learner_record_id = {}
    for record in records:
        if not record.partner_id:
            continue
        day_start, day_end = day_bounds(record.date.date())
        volunteer_record = db.session.scalar(
            db.select(Attendance).where(
                Attendance.user_id == record.partner_id,
                Attendance.date >= day_start,
                Attendance.date < day_end,
            )
        )
        if volunteer_record:
            by_learner_record_id[record.id] = volunteer_record
    return by_learner_record_id


def _group_history_records(records, volunteer_records):
    """Page rows -> [{"date": date, "groups": [{volunteer, volunteer_record, rows}]}].

    The history sheet reads like the marking sheet: a day separator, then each
    volunteer above their learners. Both nestings keep the order the query
    already produced, so the page stays sorted newest-day-first without a second
    sort here.
    """
    days = []
    day_index = {}
    for record in records:
        day = record.date.date()
        entry = day_index.get(day)
        if entry is None:
            entry: dict[str, Any] = {"date": day, "groups": [], "by_volunteer": {}}
            day_index[day] = entry
            days.append(entry)
        # A row with no volunteer groups under its own heading, same as the
        # marking sheet's unmatched learners — key 0 can't collide with an id.
        key = record.partner_id or 0
        group = entry["by_volunteer"].get(key)
        if group is None:
            group = {
                "volunteer": record.partner,
                # The first pairing's volunteer record represents the group —
                # editing it addresses that one record by its own id, not the
                # whole group (no group propagation on edit any more).
                "volunteer_record": volunteer_records.get(record.id),
                "rows": [],
            }
            entry["by_volunteer"][key] = group
            entry["groups"].append(group)
        group["rows"].append(record)
    for entry in days:
        entry.pop("by_volunteer")
        # Unmatched learners sort last within a day, matching the marking sheet.
        entry["groups"].sort(
            key=lambda g: (g["volunteer"] is None, _volunteer_sort_key(g["volunteer"]) if g["volunteer"] else "")
        )
    return days


def _get_teacher_attendance_or_403(teacher, attendance_id):
    record = db.session.get(Attendance, attendance_id)
    if not record or record.teacher_id != teacher.id:
        abort(403)
    return record


@teacher_bp.route("/attendance")
def teacher_attendance():
    """Roster sheet for one day — every learner the teacher manages, marked
    present/absent with a per-row duration. Distinct from the history page,
    which is the searchable archive of what was already recorded."""
    teacher = current_user
    session_date = _parse_date_arg(request.args.get("date")) or date.today()
    day_start, day_end = day_bounds(session_date)

    existing = db.session.scalars(
        db.select(Attendance).where(
            Attendance.teacher_id == teacher.id,
            Attendance.date >= day_start,
            Attendance.date < day_end,
        )
    ).all()
    learner_ids = {learner.id for learner in teacher.managed_learners}
    # Each pairing is now two independent records — the learner's own and (when
    # matched) the volunteer's own — so the day's rows split by whose record
    # they are, not by a single shared (learner, volunteer) key.
    by_learner = {(row.user_id, row.partner_id): row for row in existing if row.user_id in learner_ids}
    # A volunteer keeps one record for the day however many learners they hold,
    # so theirs is keyed by the volunteer alone.
    by_volunteer = {row.user_id: row for row in existing if row.user_id not in learner_ids}

    # One row per learner — matched or not. An unmatched learner still attends,
    # so excluding them would make the sheet an incomplete register.
    groups = {}
    for learner in teacher.managed_learners:
        volunteer = learner.volunteer_match if learner.is_matched else None
        key = volunteer.id if volunteer else 0
        group = groups.setdefault(key, {"volunteer": volunteer, "rows": []})
        group["rows"].append({
            "learner": learner,
            "volunteer": volunteer,
            "record": by_learner.get((learner.id, volunteer.id if volunteer else None)),
        })

    roster = sorted(
        groups.values(),
        # Unmatched learners sort last — they're the exception, not the header.
        key=lambda g: (g["volunteer"] is None, _volunteer_sort_key(g["volunteer"]) if g["volunteer"] else ""),
    )
    recorded_count = 0
    for group in roster:
        group["rows"].sort(key=lambda r: _learner_sort_key(r["learner"]))
        recorded_count += sum(1 for row in group["rows"] if row["record"])
        volunteer = group["volunteer"]
        group["volunteer_record"] = by_volunteer.get(volunteer.id) if volunteer else None

    learner_count = sum(len(group["rows"]) for group in roster)
    capture_event(str(teacher.id), "page_viewed", properties={"page": "teacher_attendance"})

    return render_template(
        "@pages/teacher/attendance.jx",
        roster=roster,
        session_date=session_date,
        learner_count=learner_count,
        recorded_count=recorded_count,
    )


@teacher_bp.route("/attendance/history")
def teacher_attendance_history():
    """Paginated (25/page), searchable archive of past attendance — grouped
    day -> volunteer -> learners like the marking sheet. Filters `learner`,
    `volunteer` (both ids), `status`, `from`/`to`, and a `range` preset
    (`today`/`week`/`month`/`all`) that only applies when neither date is
    given explicitly. The stat tiles reflect the **filtered** set, not the
    whole table."""
    teacher = current_user

    preset = request.args.get("range", "").strip().lower()
    if preset not in _HISTORY_RANGES:
        preset = ""
    date_from = _parse_date_arg(request.args.get("from"))
    date_to = _parse_date_arg(request.args.get("to"))
    # An explicit range wins; a preset only fills in what wasn't given, so the
    # chips and the two date fields never contradict each other.
    if preset and not date_from and not date_to:
        days_back = _HISTORY_RANGES[preset]
        if days_back is not None:
            date_from = date.today() - timedelta(days=days_back)
            date_to = date.today()

    filters = {
        "learner_id": request.args.get("learner", type=int),
        "volunteer_id": request.args.get("volunteer", type=int),
        "status": request.args.get("status", "").strip().lower(),
        "date_from": date_from,
        "date_to": date_to,
        "range": preset,
    }

    stmt = _attendance_history_query(teacher, filters)

    total_sessions, total_hours, absent_sessions = db.session.execute(
        stmt.with_only_columns(
            func.count(Attendance.id),
            func.coalesce(func.sum(Attendance.duration), 0.0),
            func.coalesce(func.sum(case((Attendance.is_present == False, 1), else_=0)), 0),
        )
    ).one()
    total_sessions = int(total_sessions or 0)
    absent_sessions = int(absent_sessions or 0)
    present_sessions = total_sessions - absent_sessions

    page = max(1, request.args.get("page", default=1, type=int))
    page_count = max(1, -(-total_sessions // ATTENDANCE_PAGE_SIZE))
    page = min(page, page_count)

    records = db.session.scalars(
        stmt.order_by(Attendance.date.desc(), Attendance.id.desc())
        .offset((page - 1) * ATTENDANCE_PAGE_SIZE)
        .limit(ATTENDANCE_PAGE_SIZE)
    ).all()
    volunteer_records = _volunteer_records_for(records)

    capture_event(
        str(teacher.id),
        "page_viewed",
        properties={"page": "teacher_attendance_history", "result_count": total_sessions},
    )

    ctx = {
        "records": records,
        "day_groups": _group_history_records(records, volunteer_records),
        "filters": filters,
        "page": page,
        "page_count": page_count,
        "page_size": ATTENDANCE_PAGE_SIZE,
        "total_sessions": total_sessions,
        "present_sessions": present_sessions,
        "absent_sessions": absent_sessions,
        "total_hours": round(float(total_hours or 0.0), 1),
        "attendance_rate": round(present_sessions * 100 / total_sessions) if total_sessions else 0,
        # The two people filters are type-to-filter comboboxes: the roster is
        # the teacher's own, so the whole list ships with the page and the
        # filtering happens locally instead of a request per keystroke.
        "learner_options": [
            {"id": learner.id, "label": learner.name or learner.username}
            for learner in sorted(teacher.managed_learners, key=_learner_sort_key)
        ],
        "volunteer_options": [
            {"id": volunteer.id, "label": volunteer.name or volunteer.email}
            for volunteer in sorted(teacher.managed_volunteers, key=_volunteer_sort_key)
        ],
    }
    if wants_fragment():
        return render_template("@page_components/teacher/history_results.jx", **ctx)
    return render_template("@pages/teacher/attendance_history.jx", **ctx)


@teacher_bp.route("/attendance/update", methods=["POST"])
def teacher_update_attendance():
    """One attendance record, addressed by id in the request body — a
    learner's own or a volunteer's own, no distinction. There is no more group
    to propagate onto: creation mirrors the volunteer's record from the
    learner's (see `teacher_ops.log_attendance_batch`), and every edit after
    that touches exactly the one record it names. Marking absent forces
    duration to 0; a present record with duration <= 0 is rejected (400).
    There is no delete route — a session that didn't happen is recorded as
    an absence, not removed."""
    teacher = current_user
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form

    raw_attendance_id = payload.get("attendance_id")
    if raw_attendance_id is None:
        abort(404)
    try:
        attendance_id = int(raw_attendance_id)
    except (TypeError, ValueError):
        abort(404)

    # A malformed status from a form is coerced, not rejected — the strictness
    # belongs in teacher_ops, which the assistant calls directly.
    is_present = str(payload.get("status", "present") or "present").strip().lower() != "absent"

    try:
        record = teacher_ops.update_user_attendance(
            teacher,
            attendance_id,
            date=payload.get("date"),
            is_present=is_present,
            duration=payload.get("duration") or 0,
            notes=payload.get("notes") or "",
        )["record"]
    except (LookupError, PermissionError):
        raise Forbidden() from None
    except ValueError as exc:
        message = refusal_message(exc)
        if wants_json():
            return jsonify(success=False, message=message), 400
        flash(message, "error")
        return redirect(same_site_referrer_path() or url_for("teacher.teacher_attendance_history"))

    capture_event(
        str(teacher.id),
        "attendance_updated",
        properties={
            "attendance_id": record.id,
            "is_present": record.is_present,
            "duration": record.duration,
        },
    )

    if wants_json():
        return jsonify(
            success=True,
            message="Session updated.",
            record={
                "id": record.id,
                "date": record.date.strftime("%Y-%m-%d"),
                "status": "present" if record.is_present else "absent",
                "duration": record.duration,
                "notes": record.notes or "",
            },
        )
    return redirect(same_site_referrer_path() or url_for("teacher.teacher_attendance_history"))


@teacher_bp.route("/attendance/log", methods=["POST"])
def teacher_log_attendance():
    """Roster-sheet save: create-or-update one Learner record per pair, plus a
    mirrored Volunteer record for whichever pairs have one. 400s on the
    first invalid pair in the batch and commits nothing — the whole save is
    all-or-nothing, never partially applied."""
    teacher = current_user
    data = request.get_json(silent=True) or {}
    date_str = data.get("date")
    pairs_in = data.get("pairs") or []

    if not date_str or not pairs_in:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    pairs = []
    for p in pairs_in:
        volunteer_status = p.get("volunteer_status")
        pairs.append({
            "learner_id": p.get("learner_id"),
            "volunteer_id": p.get("volunteer_id"),
            "is_present": str(p.get("status", "present") or "present").strip().lower() != "absent",
            "duration": p.get("duration"),
            "notes": p.get("notes"),
            "volunteer_is_present": (
                None if volunteer_status in (None, "")
                else str(volunteer_status).strip().lower() != "absent"
            ),
            "volunteer_duration": p.get("volunteer_duration"),
            "volunteer_notes": p.get("volunteer_notes"),
        })

    try:
        result = teacher_ops.log_attendance_batch(
            teacher, date_str, pairs, default_duration=data.get("duration"),
        )
    except (LookupError, PermissionError):
        return jsonify({"status": "error", "message": "Not your learner or volunteer."}), 403
    except ValueError as exc:
        return jsonify({"status": "error", "message": refusal_message(exc)}), 400

    capture_event(
        str(teacher.id),
        "attendance_logged",
        properties={
            "pair_count": len(pairs),
            "duration": result["total_hours"],
            "created_count": result["created"],
            "updated_count": result["updated"],
            "present_count": result["present"],
            "absent_count": result["absent"],
        },
    )
    return jsonify({
        "status": "success",
        "message": f"Logged attendance for {len(pairs)} pair(s).",
        "logged": len(pairs),
        "created": result["created"],
        "updated": result["updated"],
        "present": result["present"],
        "absent": result["absent"],
        "total_hours": round(result["total_hours"], 2),
    })
