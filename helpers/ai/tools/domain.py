"""Curated analysis tools — what the app *thinks*, not just what rows exist.

The generic tools answer "which rows are there". These wrap logic that already
runs behind the teacher's screens, so the assistant reaches the same conclusion
the UI would rather than re-deriving it from raw columns and getting it subtly
wrong.
"""

import datetime as dt
from typing import Any, NotRequired, TypedDict

import sqlalchemy as sa

from extensions import db
from helpers.ai.tools import ToolContext, ai_tool
from helpers.learning import (
    build_teacher_pair_summaries,
    get_pair_learning_snapshot,
    get_recommended_worksheets,
)
from helpers.matching import Scorer
from helpers.teacher_ops import _owned
from helpers.utils import day_bounds
from models import (
    Attendance,
    Learner,
    LearningSession,
    Teacher,
    Volunteer,
    WorksheetAssignment,
)

_DATE_ARG = {"type": "string", "description": "Calendar date, 'YYYY-MM-DD'."}


class _WorksheetBrief(TypedDict):
    id: int
    title: str
    subject: str


class PairSummary(TypedDict):
    """One matched learner-volunteer pair, as `pair_summaries` reports it."""
    learner_id: int
    learner: str
    volunteer_id: int | None
    volunteer: str | None
    subject: str | None
    topic: str | None
    progress_percent: float
    hours_learned: float
    recommended_worksheets: list[_WorksheetBrief]


class PairSummariesResult(TypedDict):
    pairs: list[PairSummary]


class _OpenAssignment(TypedDict):
    assignment_id: int
    worksheet: str | None
    assigned_at: str | None
    completed: bool


class LearnerSnapshot(TypedDict):
    """One learner's current position, as `learner_snapshot` reports it."""
    learner_id: int
    learner: str
    volunteer: str | None
    volunteer_id: int | None
    subject: str | None
    topic: str | None
    progress_percent: float
    hours_learned: float
    lessons_completed: int
    topics_completed: int
    placement_levels: dict[str, Any]
    placement_deferred: bool
    xp: int
    worksheets: list[_OpenAssignment]


class _RecommendedWorksheet(TypedDict):
    id: int
    title: str
    subject: str
    topic: str | None


class RecommendedWorksheetsResult(TypedDict):
    learner_id: int
    subject: str | None
    topic: str | None
    worksheets: list[_RecommendedWorksheet]


class LearnerWindowActivity(TypedDict):
    """One learner's activity in a `progress_between` window."""
    learner_id: int
    learner: str
    volunteer: str | None
    sessions_attended: int
    absences: int
    hours: float
    learning_activity: int
    worksheets_assigned: int
    worksheets_completed: int
    lessons_completed_total: int


# "from" is a reserved word, so these two use TypedDict's functional form
# rather than class syntax.
ProgressBetweenResult = TypedDict("ProgressBetweenResult", {
    "from": str,
    "to": str,
    "learners": list[LearnerWindowActivity],
    "no_records_in_window": list[str],
})


class AttendanceBucket(TypedDict):
    """One group's present/absent/hours in `attendance_summary`."""
    group: str
    id: int | None
    present: int
    absent: int
    hours: float
    attendance_rate: int


AttendanceSummaryResult = TypedDict("AttendanceSummaryResult", {
    "from": str,
    "to": str,
    "group_by": str,
    "total_sessions": int,
    "groups": list[AttendanceBucket],
})


class MatchScoreResult(TypedDict):
    learner_id: int
    learner: str
    volunteer_id: int
    volunteer: str | None
    score: int
    volunteer_open_slots: int
    learner_already_matched: bool


class AutoMatchProposal(TypedDict):
    """One pair the automatic matcher would create."""
    learner_id: int
    learner: str
    volunteer_id: int
    volunteer: str | None
    score: int


class PreviewAutoMatchResult(TypedDict):
    proposals: list[AutoMatchProposal]
    unmatched: list[str]
    note: NotRequired[str]


def _day(value: Any, what: str) -> dt.date:
    """Parse a 'YYYY-MM-DD' value into a date, with a friendly error.

    Args:
        value (Any): Value to parse.
        what (str): Field name, for the error message.

    Returns:
        date: The parsed date.
    """
    try:
        return dt.date.fromisoformat(str(value).strip())
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{what} must be a date like 2026-08-17.")


def _window(date_from: Any, date_to: Any) -> tuple[dt.datetime, dt.datetime]:
    """Turn a `date_from`/`date_to` pair into a half-open datetime range.

    Args:
        date_from (Any): Start date ('YYYY-MM-DD').
        date_to (Any): End date ('YYYY-MM-DD'), inclusive.

    Returns:
        tuple[datetime, datetime]: `(start, end)` — `start` inclusive, `end` exclusive.
    """
    start = day_bounds(_day(date_from, "date_from"))[0]
    end = day_bounds(_day(date_to, "date_to"))[1]
    if end <= start:
        raise ValueError("date_to must not be before date_from.")
    return start, end


def learner_name(learner: Learner) -> str:
    """Display name for a learner, with an id-based fallback.

    Args:
        learner (Learner): The learner.

    Returns:
        str: `name`, else `username`, else `"Learner <id>"`.
    """
    return learner.name or learner.username or f"Learner {learner.id}"


def volunteer_name(volunteer: Volunteer | None) -> str | None:
    """Display name for a volunteer, with an id-based fallback.

    Args:
        volunteer (Volunteer | None): The volunteer, or None.

    Returns:
        str | None: `name`, else email local-part, else `"Volunteer <id>"`; None if `volunteer` is None.
    """
    if volunteer is None:
        return None
    return volunteer.name or (volunteer.email.split("@")[0] if volunteer.email else f"Volunteer {volunteer.id}")


def _owned_learner(teacher: Teacher, learner_id: int) -> Learner:
    """Fetch a learner and confirm it belongs to `teacher`.

    Args:
        teacher (Teacher): Owning teacher.
        learner_id (int): Learner to fetch.

    Returns:
        Learner: The learner.
    """
    return _owned(Learner, learner_id, teacher, "learner")


def _owned_volunteer(teacher: Teacher, volunteer_id: int) -> Volunteer:
    """Fetch a volunteer and confirm it belongs to `teacher`.

    Args:
        teacher (Teacher): Owning teacher.
        volunteer_id (int): Volunteer to fetch.

    Returns:
        Volunteer: The volunteer.
    """
    return _owned(Volunteer, volunteer_id, teacher, "volunteer")


# ── snapshots ────────────────────────────────────────────────────────────────

@ai_tool(
    name="pair_summaries",
    description=(
        "Every matched learner-volunteer pair with the learner's current "
        "subject, topic, progress percentage and recommended worksheets — the "
        "same summary the teacher dashboard shows. One row per learner, so a "
        "volunteer holding several learners appears several times."
    ),
    label="Reading your pairs",
    parameters={
        "type": "object",
        "properties": {
            "recommendation_limit": {"type": "integer", "description": "Worksheets per pair (default 3)."}
        },
    },
)
def pair_summaries(ctx: ToolContext, recommendation_limit: int = 3) -> PairSummariesResult:
    """Every matched pair with subject/topic/progress and recommended worksheets.

    Args:
        ctx (ToolContext): Tool call context.
        recommendation_limit (int): Worksheets per pair (default 3, capped at 10).

    Returns:
        PairSummariesResult: `{"pairs": [...]}` — see the tool's `description` for shape.
    """
    try:
        limit = max(0, min(int(recommendation_limit), 10))
    except (TypeError, ValueError):
        limit = 3

    pairs = build_teacher_pair_summaries(ctx.teacher, recommendation_limit=limit)
    return {
        "pairs": [
            {
                "learner_id": pair["learner"].id,
                "learner": learner_name(pair["learner"]),
                "volunteer_id": pair["volunteer"].id if pair["volunteer"] else None,
                "volunteer": volunteer_name(pair["volunteer"]),
                "subject": pair["subject"],
                "topic": pair["topic"],
                "progress_percent": pair["progress"],
                "hours_learned": pair["learner"].hours_learned,
                "recommended_worksheets": [
                    {"id": w.id, "title": w.title, "subject": w.subject}
                    for w in pair["worksheets"]
                ],
            }
            for pair in pairs
        ]
    }


@ai_tool(
    name="learner_snapshot",
    description=(
        "One learner's current learning position: subject, topic, progress "
        "percentage, hours, placement levels, matched volunteer and open "
        "worksheet assignments."
    ),
    label="Checking learner {learner_id}",
    parameters={
        "type": "object",
        "properties": {"learner_id": {"type": "integer"}},
        "required": ["learner_id"],
    },
)
def learner_snapshot(ctx: ToolContext, learner_id: int) -> LearnerSnapshot:
    """One learner's current position, progress, placement levels, and open worksheets.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to snapshot.

    Returns:
        LearnerSnapshot: See the tool's `description` for shape.
    """
    learner = _owned_learner(ctx.teacher, learner_id)
    snapshot = get_pair_learning_snapshot(learner)
    assignments = db.session.scalars(
        db.select(WorksheetAssignment)
        .filter_by(teacher_id=ctx.teacher.id, learner_id=learner.id)
        .order_by(WorksheetAssignment.assigned_at.desc())
        .limit(20)
    ).all()
    return {
        "learner_id": learner.id,
        "learner": learner_name(learner),
        "volunteer": volunteer_name(learner.volunteer_match),
        "volunteer_id": learner.volunteer_id,
        "subject": snapshot["subject"],
        "topic": snapshot["topic"],
        "progress_percent": snapshot["progress"],
        "hours_learned": learner.hours_learned,
        "lessons_completed": len(learner.completed_lesson_ids or []),
        "topics_completed": len(learner.completed_topic_ids or []),
        # {} means the placement test was never really taken — not level 1.
        "placement_levels": learner.subject_levels or {},
        "placement_deferred": bool(learner.map_test_deferred),
        "xp": learner.xp,
        "worksheets": [
            {
                "assignment_id": a.id,
                "worksheet": a.worksheet.title if a.worksheet else None,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                "completed": bool(a.completed),
            }
            for a in assignments
        ],
    }


@ai_tool(
    name="recommended_worksheets",
    description=(
        "Worksheets scored against a learner's current subject and topic, best "
        "first — the same ranking the worksheets page uses."
    ),
    label="Finding worksheets for learner {learner_id}",
    parameters={
        "type": "object",
        "properties": {
            "learner_id": {"type": "integer"},
            "limit": {"type": "integer", "description": "Default 4, max 20."},
        },
        "required": ["learner_id"],
    },
)
def recommended_worksheets(ctx: ToolContext, learner_id: int, limit: int = 4) -> RecommendedWorksheetsResult:
    """Worksheets scored against a learner's current subject/topic, best first.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to recommend worksheets for.
        limit (int): Max worksheets to return (default 4, capped at 20).

    Returns:
        RecommendedWorksheetsResult: `{"learner_id", "subject", "topic", "worksheets"}`.
    """
    learner = _owned_learner(ctx.teacher, learner_id)
    try:
        size = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        size = 4
    snapshot = get_pair_learning_snapshot(learner)
    sheets = get_recommended_worksheets(snapshot["subject"], snapshot["topic"], limit=size, level=snapshot["level"])
    return {
        "learner_id": learner.id,
        "subject": snapshot["subject"],
        "topic": snapshot["topic"],
        "worksheets": [
            {"id": w.id, "title": w.title, "subject": w.subject, "topic": w.topic}
            for w in sheets
        ],
    }


# ── windowed activity ────────────────────────────────────────────────────────

@ai_tool(
    name="progress_between",
    description=(
        "Per-learner activity between two dates, least active first — the "
        "'who moved least this session' question. Reports attended sessions, "
        "hours, absences, learning activity recorded in the window and "
        "worksheets assigned/completed in it. Note: a learner's completed "
        "lesson list carries no timestamps, so learning activity inside a "
        "window is measured from learning-session records, which exist for "
        "games and in-progress quizzes but not for a quiz finished before the "
        "window. Say so if the answer hinges on it."
    ),
    label="Comparing progress {date_from} to {date_to}",
    parameters={
        "type": "object",
        "properties": {
            "date_from": _DATE_ARG,
            "date_to": _DATE_ARG,
            "learner_ids": {
                "type": "array", "items": {"type": "integer"},
                "description": "Restrict to these learners. Omit for everyone who attended.",
            },
        },
        "required": ["date_from", "date_to"],
    },
)
def progress_between(ctx: ToolContext, date_from: str, date_to: str, learner_ids: list[int] | None = None) -> ProgressBetweenResult:
    """Per-learner attendance/hours/activity/worksheet activity between two dates.

    Args:
        ctx (ToolContext): Tool call context.
        date_from (str): Start date ('YYYY-MM-DD').
        date_to (str): End date ('YYYY-MM-DD'), inclusive.
        learner_ids (list[int] | None): Restrict to these learners; else everyone who attended.

    Returns:
        ProgressBetweenResult: `{"from", "to", "learners", "no_records_in_window"}`,
            `learners` sorted least-active first.
    """
    start, end = _window(date_from, date_to)
    teacher = ctx.teacher

    roster = {learner.id: learner for learner in teacher.managed_learners}
    if learner_ids:
        wanted = {int(i) for i in learner_ids}
        unknown = wanted - set(roster)
        if unknown:
            raise ValueError(
                "Not your learners: " + ", ".join(str(i) for i in sorted(unknown))
            )
        roster = {i: roster[i] for i in wanted}

    # Learners' own records only — one row per session, not doubled up by
    # each pair's mirrored volunteer record.
    attendance = db.session.scalars(
        db.select(Attendance).where(
            Attendance.teacher_id == teacher.id,
            Attendance.user_id.in_(list(roster) or [-1]),
            Attendance.date >= start, Attendance.date < end,
        )
    ).all()
    by_learner = {}
    for row in attendance:
        bucket = by_learner.setdefault(
            row.user_id, {"sessions": 0, "absences": 0, "hours": 0.0}
        )
        if not row.is_present:
            bucket["absences"] += 1
        else:
            bucket["sessions"] += 1
            bucket["hours"] += float(row.duration or 0)

    activity_rows = db.session.execute(
        db.select(LearningSession.learner_id, sa.func.count(LearningSession.id))
        .where(
            LearningSession.learner_id.in_(list(roster) or [-1]),
            LearningSession.updated_at >= start,
            LearningSession.updated_at < end,
        )
        .group_by(LearningSession.learner_id)
    ).all()
    activity = {learner_id: int(n) for learner_id, n in activity_rows}

    assignments = db.session.scalars(
        db.select(WorksheetAssignment).where(
            WorksheetAssignment.teacher_id == teacher.id,
            WorksheetAssignment.assigned_at >= start,
            WorksheetAssignment.assigned_at < end,
        )
    ).all()
    assigned, completed = {}, {}
    for row in assignments:
        assigned[row.learner_id] = assigned.get(row.learner_id, 0) + 1
        if row.completed:
            completed[row.learner_id] = completed.get(row.learner_id, 0) + 1

    # Only learners with something recorded in the window — a learner who was
    # never marked at all did not "make the least progress", they are missing
    # from the register, which is a different problem.
    results: list[LearnerWindowActivity] = []
    for learner_id in sorted(set(by_learner) | set(activity) | set(assigned)):
        learner = roster[learner_id]
        marks = by_learner.get(learner_id, {"sessions": 0, "absences": 0, "hours": 0.0})
        results.append({
            "learner_id": learner_id,
            "learner": learner_name(learner),
            "volunteer": volunteer_name(learner.volunteer_match),
            "sessions_attended": marks["sessions"],
            "absences": marks["absences"],
            "hours": round(marks["hours"], 2),
            "learning_activity": activity.get(learner_id, 0),
            "worksheets_assigned": assigned.get(learner_id, 0),
            "worksheets_completed": completed.get(learner_id, 0),
            "lessons_completed_total": len(learner.completed_lesson_ids or []),
        })

    results.sort(key=lambda r: (r["learning_activity"], r["hours"], r["worksheets_completed"]))
    unrecorded = sorted(
        learner_name(roster[i]) for i in roster if i not in set(by_learner) | set(activity) | set(assigned)
    )
    return {
        "from": start.date().isoformat(),
        "to": (end - dt.timedelta(days=1)).date().isoformat(),
        "learners": results,
        "no_records_in_window": unrecorded,
    }


@ai_tool(
    name="attendance_summary",
    description=(
        "Present/absent counts and hours over a date range, grouped by learner, "
        "volunteer or day."
    ),
    label="Summarising attendance {date_from} to {date_to}",
    parameters={
        "type": "object",
        "properties": {
            "date_from": _DATE_ARG,
            "date_to": _DATE_ARG,
            "group_by": {"type": "string", "enum": ["learner", "volunteer", "day"]},
        },
        "required": ["date_from", "date_to"],
    },
)
def attendance_summary(ctx: ToolContext, date_from: str, date_to: str, group_by: str = "learner") -> AttendanceSummaryResult:
    """Present/absent counts and hours over a date range, grouped by learner/volunteer/day.

    Args:
        ctx (ToolContext): Tool call context.
        date_from (str): Start date ('YYYY-MM-DD').
        date_to (str): End date ('YYYY-MM-DD'), inclusive.
        group_by (str): One of `"learner"`, `"volunteer"`, `"day"`.

    Returns:
        AttendanceSummaryResult: `{"from", "to", "group_by", "total_sessions", "groups"}`.
    """
    start, end = _window(date_from, date_to)
    key = (group_by or "learner").strip().lower()
    if key not in ("learner", "volunteer", "day"):
        raise ValueError("group_by must be 'learner', 'volunteer' or 'day'.")

    # Learners' own records only — the canonical one-row-per-session view; a
    # pair's mirrored volunteer record isn't a second session.
    rows = db.session.scalars(
        db.select(Attendance)
        .join(Learner, Learner.id == Attendance.user_id)
        .where(Attendance.teacher_id == ctx.teacher.id,
               Attendance.date >= start, Attendance.date < end)
    ).all()

    buckets = {}
    for row in rows:
        if key == "learner":
            label = learner_name(row.user) if row.user else f"Learner {row.user_id}"
            row_id = row.user_id
        elif key == "volunteer":
            label = volunteer_name(row.partner) if row.partner else "No volunteer"
            row_id = row.partner_id
        else:
            label = row.date.date().isoformat()
            row_id = None
        bucket = buckets.setdefault(
            label, {"group": label, "id": row_id, "present": 0, "absent": 0, "hours": 0.0}
        )
        if not row.is_present:
            bucket["absent"] += 1
        else:
            bucket["present"] += 1
            bucket["hours"] += float(row.duration or 0)

    groups = sorted(buckets.values(), key=lambda b: b["group"])
    for bucket in groups:
        bucket["hours"] = round(bucket["hours"], 2)
        total = bucket["present"] + bucket["absent"]
        bucket["attendance_rate"] = round(bucket["present"] * 100 / total) if total else 0

    return {
        "from": start.date().isoformat(),
        "to": (end - dt.timedelta(days=1)).date().isoformat(),
        "group_by": key,
        "total_sessions": len(rows),
        "groups": groups,
    }


# ── matching ─────────────────────────────────────────────────────────────────

@ai_tool(
    name="match_score",
    description=(
        "Compatibility score between one learner and one volunteer, using the "
        "same weighting the auto-matcher uses: shared languages, shared "
        "activities, hobbies, tech interests, age and personality, each "
        "counting as much as this teacher's own matching priorities say it "
        "should. Higher is better; there is no fixed maximum."
    ),
    label="Scoring learner {learner_id} with volunteer {volunteer_id}",
    parameters={
        "type": "object",
        "properties": {
            "learner_id": {"type": "integer"},
            "volunteer_id": {"type": "integer"},
        },
        "required": ["learner_id", "volunteer_id"],
    },
)
def match_score(ctx: ToolContext, learner_id: int, volunteer_id: int) -> MatchScoreResult:
    """Compatibility score between one learner and one volunteer.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to score.
        volunteer_id (int): Volunteer to score against.

    Returns:
        MatchScoreResult: `{"learner_id", "learner", "volunteer_id", "volunteer",
            "score", "volunteer_open_slots", "learner_already_matched"}`.
    """
    learner = _owned_learner(ctx.teacher, learner_id)
    volunteer = _owned_volunteer(ctx.teacher, volunteer_id)
    score = Scorer.for_teacher(ctx.teacher.match_settings).pair(learner, volunteer)
    return {
        "learner_id": learner.id, "learner": learner_name(learner),
        "volunteer_id": volunteer.id, "volunteer": volunteer_name(volunteer),
        "score": int(score),
        "volunteer_open_slots": volunteer.open_slots,
        "learner_already_matched": bool(learner.is_matched),
    }


def _auto_match_candidates(teacher: Teacher) -> tuple[list[Learner], list[Volunteer]]:
    """Unmatched learners + volunteers with a free slot, teacher's own roster only.

    The pool is the roster, not the school: `teacher_ops.match_pair` refuses a
    row owned by a colleague, and a pair rejected there has already spent its
    volunteer's slot inside the matcher, so a wider pool burns slots and leaves
    own learners unmatched.

    Args:
        teacher (Teacher): Teacher whose roster to draw candidates from.

    Returns:
        tuple[list[Learner], list[Volunteer]]: Unmatched learners, volunteers with an open slot.
    """
    if not teacher.school_id:
        raise ValueError("You are not assigned to a school, so matching has no pool to draw from.")

    learners = list(db.session.scalars(
        db.select(Learner).filter_by(teacher_id=teacher.id, is_matched=False)
    ).all())
    volunteers = [
        v for v in db.session.scalars(
            db.select(Volunteer).filter_by(teacher_id=teacher.id)
        ).all()
        if v.open_slots > 0
    ]
    return learners, volunteers


@ai_tool(
    name="preview_auto_match",
    description=(
        "Run the automatic matcher and return the pairs it WOULD create, each "
        "with its compatibility score. Changes nothing. Use stage_auto_match to "
        "put these in front of the teacher for approval."
    ),
    label="Previewing automatic matches",
    parameters={"type": "object", "properties": {}},
)
def preview_auto_match(ctx: ToolContext) -> PreviewAutoMatchResult:
    """Run the automatic matcher and return the pairs it would create. Changes nothing.

    Args:
        ctx (ToolContext): Tool call context.

    Returns:
        PreviewAutoMatchResult: `{"proposals", "unmatched"}` (and `"note"` when there's nothing to match).
    """
    learners, volunteers = _auto_match_candidates(ctx.teacher)
    if not learners or not volunteers:
        return {
            "proposals": [], "unmatched": [learner_name(l) for l in learners],
            "note": "No unmatched learners, or no volunteer with a free slot.",
        }

    # Same saved priorities the Auto-Match button runs on, so a preview the
    # teacher approves lands the pairs they were shown.
    pairs, scores = Scorer.for_teacher(ctx.teacher.match_settings).match_all(
        learners,
        volunteers,
        capacities={v.id: v.open_slots for v in volunteers},
        loads={v.id: len(v.learner_matches) for v in volunteers},
    )

    proposals: list[AutoMatchProposal] = []
    unmatched: list[str] = []
    remaining = {v.id: v.open_slots for v in volunteers}
    for learner, volunteer in pairs:
        if not volunteer or remaining.get(volunteer.id, 0) <= 0:
            unmatched.append(learner_name(learner))
            continue
        remaining[volunteer.id] -= 1
        proposals.append({
            "learner_id": learner.id, "learner": learner_name(learner),
            "volunteer_id": volunteer.id, "volunteer": volunteer_name(volunteer),
            "score": scores.of(learner.id, volunteer.id),
        })

    proposals.sort(key=lambda p: -p["score"])
    return {"proposals": proposals, "unmatched": unmatched}
