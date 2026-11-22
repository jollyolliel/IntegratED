from typing import TypedDict

from flask import abort, flash, jsonify, redirect, request, url_for
from sqlalchemy.orm import joinedload

from extensions import db
from helpers import roster_ops, teacher_ops
from helpers.analytics import capture_event
from helpers.announcements import get_pending_announcement
from helpers.auth_utils import (
    clean_credential,
    get_or_create_invite_code,
    has_whitespace,
    regenerate_invite_code,
)
from helpers.current_user import current_teacher as current_user
from helpers.learning import (
    build_teacher_pair_summaries,
    get_learner_progress_position,
    get_recommended_worksheets,
)
from helpers.matching import (
    FACTORS,
    SPREAD_PENALTIES,
    WEIGHT_MULTIPLIERS,
    Scorer,
    match_band,
    normalize_levels,
)
from helpers.render import render_template
from helpers.teacher_ops import MAX_VOLUNTEER_CAPACITY
from helpers.utils import day_bounds, utcnow_naive, wants_json
from models import Attendance, Learner, Topic, Volunteer, WorksheetAssignment
from routes.teacher import teacher_bp, worksheet_assignments

# How long a finished worksheet still counts as "just done" on the learner page
# — inside the window the card is green and counts days, outside it goes blue
# and names the date.
RECENT_COMPLETION_DAYS = 7

# Person pages show this many sessions, then link out to the full history.
ATTENDANCE_PREVIEW_SIZE = 7
# Learner page's assigned-worksheets card previews this many, newest first —
# no full paged archive exists for this list yet (docs/ui-design/page-behaviour.md preview pattern).
ASSIGNMENTS_PREVIEW_SIZE = 7


def _learner_sort_key(learner):
    return (learner.name or learner.username or "").lower()


def _volunteer_sort_key(volunteer):
    """Matched first, then alphabetical."""
    # An unmatched volunteer between two matched ones leaves the learner column
    # a card short at that height and every connector below it bends around the
    # hole, so the unmatched ones sink to the bottom. Counts attached learners
    # rather than reading `is_matched`, which is a cached flag.
    return (not volunteer.learner_matches, (volunteer.name or volunteer.email or "").lower())


def _session_partners_for(volunteer, records):
    """Who the volunteer sat with on each of their own records' days.

    Their own record names at most one learner and often nobody —
    `_collapse_volunteer_sides` nulls `partner_id` for a group of several — so
    the names come from the other side: the learner rows pointing back at this
    volunteer that day. `_volunteer_records_for` runs the same lookup inverted,
    one row at a time; this one takes the whole preview in a single query and
    buckets it by day, bounded to the days those rows cover so it stays
    preview-sized however long the volunteer's history grows."""
    if not records:
        return {}
    days = [record.date.date() for record in records]
    window_start = day_bounds(min(days))[0]
    window_end = day_bounds(max(days))[1]
    # joinedload, or reading `row.user` below lazy-loads one person per row and
    # puts the N+1 straight back.
    learner_records = db.session.scalars(
        db.select(Attendance)
        .options(joinedload(Attendance.user))
        .where(
            Attendance.partner_id == volunteer.id,
            Attendance.date >= window_start,
            Attendance.date < window_end,
        )
    ).all()

    by_day = {}
    for row in learner_records:
        if row.user:
            by_day.setdefault(row.date.date(), []).append(row.user)
    for partners in by_day.values():
        partners.sort(key=lambda person: (person.name or "").lower())

    # Keep the outer records on `user_id`: the learners' rows may disagree on
    # duration and present-mark (ADR 0001), and a two-learner volunteer would
    # list every session twice if they drove the table.
    return {record.id: by_day.get(record.date.date(), []) for record in records}


@teacher_bp.route("/")
def teacher_dashboard():
    teacher = current_user
    capture_event(str(teacher.id), "dashboard_viewed", properties={"role": "teacher"})

    # Auto-assign students/volunteers from the same school
    teacher_ops.assign_unassigned(teacher)

    managed_learners = teacher.managed_learners
    managed_volunteers = teacher.managed_volunteers
    matched_pairs = build_teacher_pair_summaries(teacher, recommendation_limit=3)

    invite_code = get_or_create_invite_code(teacher.school) if teacher.school else None

    context = {
        "teacher": teacher,
        "matched_pairs": matched_pairs,
        "unmatched_learners": [l for l in managed_learners if not l.is_matched or not l.volunteer_match],
        "unmatched_volunteers": [v for v in managed_volunteers if v.open_slots > 0],
        "total_learners": len(managed_learners),
        "total_volunteers": len(managed_volunteers),
        "total_people": len(managed_learners) + len(managed_volunteers),
        "active_matches": len(matched_pairs),
        "total_learning_hours": sum((l.hours_learned or 0) for l in managed_learners),
        "invite_code": invite_code,
        "pending_announcement": get_pending_announcement(teacher),
    }

    return render_template("@pages/teacher/dashboard.jx", **context)


@teacher_bp.route("/regenerate-invite", methods=["POST"])
def regenerate_invite():
    teacher = current_user
    new_code = None
    if teacher.school:
        new_code = regenerate_invite_code(teacher.school)
        capture_event(str(teacher.id), "invite_code_regenerated", properties={"school": teacher.school.name})
    if wants_json():
        return jsonify(
            success=True,
            message="Invite code regenerated.",
            invite_code=new_code,
        )
    return redirect(url_for("teacher.teacher_dashboard"))


@teacher_bp.route("/people")
def teacher_people():
    """One roster, two columns, a connector drawn between each pair — the pairs
    are the lines, not a third list repeating both columns. Learners are
    ordered by their volunteer's position in the other column so a pair's
    cards sit level. Password reset and delete live on the person's own
    detail page, not here."""
    teacher = current_user
    capture_event(str(teacher.id), "page_viewed", properties={"page": "teacher_people"})

    scorer = Scorer.for_teacher(teacher.match_settings)
    volunteers = sorted(teacher.managed_volunteers, key=_volunteer_sort_key)
    # Learners follow their volunteer's position so a pair's two cards sit at
    # roughly the same height — the connector lines stay short and near-parallel
    # instead of criss-crossing the gutter. Unmatched learners fall to the end.
    volunteer_order = {v.id: index for index, v in enumerate(volunteers)}
    learners = sorted(
        teacher.managed_learners,
        key=lambda l: (
            volunteer_order.get(l.volunteer_id, len(volunteer_order)),
            _learner_sort_key(l),
        ),
    )

    return render_template(
        "@pages/teacher/people.jx",
        teacher=teacher,
        # The connector between a pair is coloured by the pair's band, read off
        # the learner card client-side (`drawPairLines`).
        pair_scores={
            l.id: _match_score(l, l.volunteer_match, scorer)
            for l in learners
            if l.is_matched and l.volunteer_match
        },
        unmatched_learners=[l for l in learners if not l.is_matched],
        # "Available" now means "has a free slot", not "has nobody" — a
        # volunteer with capacity 3 and one learner can still take two more.
        unmatched_volunteers=[v for v in volunteers if v.open_slots > 0],
        learners=learners,
        volunteers=volunteers,
        max_capacity=MAX_VOLUNTEER_CAPACITY,
        default_capacity=max(1, teacher.default_match_capacity or 1),
        match_factors=FACTORS,
        match_levels=normalize_levels(teacher.match_settings),
        weight_level_count=len(WEIGHT_MULTIPLIERS),
        spread_level_count=len(SPREAD_PENALTIES),
    )


@teacher_bp.route("/default-capacity", methods=["POST"])
def teacher_set_default_capacity():
    """The learner limit new volunteers start on. Deliberately does not touch
    volunteers already on the roster — a teacher who hand-set one expects it to
    survive a change of default."""
    teacher = current_user
    try:
        capacity = teacher_ops.set_default_capacity(
            teacher, request.form.get("default_capacity", "")
        )["capacity"]
    except ValueError as exc:
        message = str(exc)
        if wants_json():
            return jsonify(success=False, message=message), 400
        flash(message, "error")
        return redirect(url_for("teacher.teacher_people"))

    capture_event(
        str(teacher.id),
        "default_match_capacity_set",
        properties={"capacity": capacity},
    )

    message = f"New volunteers will start with {capacity} learner slot(s)."
    if wants_json():
        return jsonify(success=True, message=message, default_capacity=capacity)
    flash(message, "success")
    return redirect(url_for("teacher.teacher_people"))


class MatchScore(TypedDict):
    """A pair's compatibility as the person pages show it."""
    score: int
    band: str


def _match_score(learner: Learner, volunteer: Volunteer, scorer: Scorer) -> MatchScore:
    """Scores an existing pair the same way the matcher scored it when it
    proposed the pair, so the number on the page and the number the algorithm
    optimised are one and the same.

    Args:
        learner (Learner): The matched learner.
        volunteer (Volunteer): The volunteer they are matched with.
        scorer (Scorer): The owning teacher's settings, resolved once by the
            calling route — a roster page scores every row, and resolving per
            row would walk `learner.teacher` and redo that work for each.

    Returns:
        MatchScore: The raw score and its band label.
    """
    # Recomputed per view, never stored: survey answers change after a match
    # is applied and the owning teacher can re-weight the factors at any time,
    # so a persisted score would go stale silently in two directions at once.
    score = scorer.pair(learner, volunteer)
    return {"score": score, "band": match_band(score)}


@teacher_bp.route("/learners/<int:learner_id>")
def teacher_learner_detail(learner_id):
    """Everything about one learner, including the pair as one of its facts."""
    teacher = current_user
    learner = db.session.get(Learner, learner_id)
    if not learner or learner.teacher_id != teacher.id:
        abort(403)

    capture_event(
        str(teacher.id),
        "page_viewed",
        properties={"page": "teacher_learner_detail", "learner_id": learner_id},
    )

    # A preview, not the archive: the newest few sessions, with the full
    # filterable history one click away (docs/ui-design/page-behaviour.md).
    attendance_stmt = db.select(Attendance).filter_by(user_id=learner.id).order_by(Attendance.date.desc())
    attendance_total = db.session.scalar(
        db.select(db.func.count()).select_from(Attendance).filter_by(user_id=learner.id)
    )
    attendance = db.session.scalars(attendance_stmt.limit(ATTENDANCE_PREVIEW_SIZE)).all()

    position = get_learner_progress_position(learner)
    # Recommendations follow where the learner is *going*, not the last topic
    # they closed — an empty topic still scores worksheets by subject.
    worksheets = get_recommended_worksheets(
        position["subject"] or "", position["topic"] or "", limit=6
    )

    # No teacher_id filter: the sheet list belongs to the learner, and the
    # teacher_id != learner.teacher_id gate above is what grants access.
    # A preview, not the archive: the newest ASSIGNMENTS_PREVIEW_SIZE overall
    # (outstanding and completed mixed), then split for display below.
    # One pass over the ids gives the total and every outstanding sheet ("Print all
    # outstanding" prints the lot, not just the previewed ones).
    assignment_states = db.session.execute(
        db.select(WorksheetAssignment.id, WorksheetAssignment.completed)
        .filter_by(learner_id=learner.id)
        .order_by(WorksheetAssignment.assigned_at.asc(), WorksheetAssignment.id.asc())
    ).all()
    assignment_total = len(assignment_states)
    outstanding_ids = [row.id for row in assignment_states if not row.completed]
    assignments = db.session.scalars(
        db.select(WorksheetAssignment).filter_by(learner_id=learner.id)
        .order_by(WorksheetAssignment.assigned_at.desc())
        .limit(ASSIGNMENTS_PREVIEW_SIZE)
    ).all()
    outstanding = sorted(
        (a for a in assignments if not a.completed),
        key=lambda a: a.assigned_at,
        reverse=True,
    )
    completed = sorted(
        (a for a in assignments if a.completed),
        key=lambda a: a.completed_at or a.assigned_at,
        reverse=True,
    )

    return render_template(
        "@pages/teacher/learner_detail.jx",
        learner=learner,
        match_score=(
            _match_score(learner, learner.volunteer_match, Scorer.for_teacher(teacher.match_settings))
            if learner.is_matched and learner.volunteer_match
            else None
        ),
        attendance=attendance,
        attendance_total=attendance_total,
        completed_topics=db.session.scalars(
            db.select(Topic).where(Topic.id.in_(learner.completed_topic_ids or []))
        ).all(),
        position=position,
        worksheets=worksheets,
        outstanding_assignments=outstanding,
        completed_assignments=completed,
        assignment_total=assignment_total,
        outstanding_ids=outstanding_ids,
        max_print_batch=worksheet_assignments.MAX_PRINT_BATCH,
        now=utcnow_naive(),
        recent_completion_days=RECENT_COMPLETION_DAYS,
    )


@teacher_bp.route("/volunteers/<int:volunteer_id>")
def teacher_volunteer_detail(volunteer_id):
    """One volunteer, whole picture. Sessions come from the volunteer's own
    `Attendance` records (`user_id`), so the hours shown match the tile
    above them; the partner column is a per-row reverse lookup of the
    matched learners' own rows (bounded to the shown days), since a group
    session leaves the volunteer's own `partner_id` null. Shows the 7 newest
    sessions, then a link to the history page filtered to this volunteer —
    the count there differs from here because a group day is one session on
    the volunteer's side and one per learner on theirs."""
    teacher = current_user
    volunteer = db.session.get(Volunteer, volunteer_id)
    if not volunteer or volunteer.teacher_id != teacher.id:
        abort(403)

    capture_event(
        str(teacher.id),
        "page_viewed",
        properties={"page": "teacher_volunteer_detail", "volunteer_id": volunteer_id},
    )

    # A preview, not the archive: the newest few sessions, with the full
    # filterable history one click away (docs/ui-design/page-behaviour.md). The count is of the
    # volunteer's **own** records, so it agrees with this table and the hours
    # tile; the history page counts the learners' rows instead, and a group day
    # is one session here but one per learner there.
    attendance_stmt = db.select(Attendance).filter_by(user_id=volunteer.id).order_by(Attendance.date.desc())
    attendance_total = db.session.scalar(
        db.select(db.func.count()).select_from(Attendance).filter_by(user_id=volunteer.id)
    )
    attendance = db.session.scalars(attendance_stmt.limit(ATTENDANCE_PREVIEW_SIZE)).all()
    scorer = Scorer.for_teacher(teacher.match_settings)

    return render_template(
        "@pages/teacher/volunteer_detail.jx",
        volunteer=volunteer,
        match_scores={l.id: _match_score(l, volunteer, scorer) for l in volunteer.learner_matches},
        attendance=attendance,
        attendance_total=attendance_total,
        session_partners=_session_partners_for(volunteer, attendance),
        max_capacity=MAX_VOLUNTEER_CAPACITY,
    )


@teacher_bp.route("/learners/<int:learner_id>/delete", methods=["POST"])
def teacher_delete_learner(learner_id):
    teacher = current_user
    learner = db.session.get(Learner, learner_id)
    if not learner or learner.teacher_id != teacher.id:
        abort(403)

    roster_ops.delete_user(learner)

    capture_event(str(teacher.id), "learner_deleted", properties={"learner_id": learner_id})
    if wants_json():
        return jsonify(success=True, message="Learner deleted.")
    return redirect(url_for("teacher.teacher_people"))


@teacher_bp.route("/volunteers/<int:volunteer_id>/delete", methods=["POST"])
def teacher_delete_volunteer(volunteer_id):
    teacher = current_user
    volunteer = db.session.get(Volunteer, volunteer_id)
    if not volunteer or volunteer.teacher_id != teacher.id:
        abort(403)

    roster_ops.delete_user(volunteer)

    capture_event(str(teacher.id), "volunteer_deleted", properties={"volunteer_id": volunteer_id})
    if wants_json():
        return jsonify(success=True, message="Volunteer deleted.")
    return redirect(url_for("teacher.teacher_people"))


@teacher_bp.route("/learners/<int:learner_id>/set-password", methods=["POST"])
def teacher_set_learner_password(learner_id):
    teacher = current_user
    learner = db.session.get(Learner, learner_id)
    if not learner or learner.teacher_id != teacher.id:
        abort(403)

    new_password = clean_credential(request.form.get("password"))
    if not new_password or has_whitespace(new_password):
        abort(400)

    learner.set_password(new_password)
    db.session.commit()

    capture_event(str(teacher.id), "learner_password_reset", properties={"learner_id": learner_id})
    if wants_json():
        return jsonify(success=True, message="Password updated.")
    return redirect(url_for("teacher.teacher_people"))
