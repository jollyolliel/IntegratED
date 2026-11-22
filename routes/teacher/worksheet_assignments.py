"""The teacher's assigned-worksheets tracker and the batch actions on it.

Every assignment here is one of the teacher's **learners'** — a colleague at
the same school may have set it — matching the learner page's own sheet list
(docs/features/worksheets.md).
"""
import re
from datetime import timedelta
from typing import TypedDict

from flask import abort, flash, jsonify, redirect, request, url_for
from sqlalchemy import func
from sqlalchemy.orm import contains_eager, selectinload

from extensions import db
from helpers import teacher_ops
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.documents import generate_assignments_pdf
from helpers.render import render_template
from helpers.utils import (
    clamp_page,
    get_pair_display_name,
    safe_local_path,
    utcnow_naive,
    wants_fragment,
    wants_json,
)
from models import Learner, Worksheet, WorksheetAssignment
from routes.teacher import teacher_bp

TRACKER_PAGE_SIZE = 25
# One printed packet at most; a teacher's whole outstanding pile fits well inside it.
MAX_PRINT_BATCH = 100
_STATUSES = ("outstanding", "completed")
_RANGES = {"week": 7, "month": 30, "term": 90}


class TrackerFilters(TypedDict):
    """The tracker's filters, keyed by their query-string names so paging can pass them straight on."""

    status: str
    learner: int | None
    subject: str
    q: str
    range: str


def _read_filters() -> TrackerFilters:
    """The query string as filters; any value off its list is dropped, never a 500."""
    status = request.args.get("status", "").strip().lower()
    preset = request.args.get("range", "").strip().lower()
    return {
        "status": status if status in _STATUSES else "",
        "learner": request.args.get("learner", type=int),
        "subject": request.args.get("subject", "").strip(),
        "q": request.args.get("q", "").strip()[:100],
        "range": preset if preset in _RANGES else "",
    }


def _apply_filters(stmt, filters: TrackerFilters):
    if filters["status"] == "outstanding":
        stmt = stmt.where(WorksheetAssignment.completed.is_(False))
    elif filters["status"] == "completed":
        stmt = stmt.where(WorksheetAssignment.completed.is_(True))
    if filters["learner"]:
        stmt = stmt.where(WorksheetAssignment.learner_id == filters["learner"])
    if filters["subject"]:
        stmt = stmt.where(Worksheet.subject == filters["subject"])
    if filters["q"]:
        stmt = stmt.where(Worksheet.title.icontains(filters["q"], autoescape=True))
    if filters["range"]:
        stmt = stmt.where(WorksheetAssignment.assigned_at >= utcnow_naive() - timedelta(days=_RANGES[filters["range"]]))
    return stmt


@teacher_bp.route("/worksheets/assigned")
def teacher_worksheet_assignments():
    """Every worksheet given to the teacher's learners, current and past: summary
    tiles and a per-pair overview (both unfiltered), then a filtered table paged at
    TRACKER_PAGE_SIZE — `status`, `learner`, `subject`, `q` (title) and a `range`
    preset (`week`/`month`/`term`). An `X-Fragment` request returns just the table
    region (docs/ui-design/page-behaviour.md)."""
    teacher = current_user
    filters = _read_filters()
    stmt = _apply_filters(teacher_ops.learner_assignments(teacher), filters)

    result_count = db.session.scalar(stmt.with_only_columns(func.count(WorksheetAssignment.id))) or 0
    page, page_count = clamp_page(result_count, TRACKER_PAGE_SIZE)
    assignments = db.session.scalars(
        stmt.options(
            contains_eager(WorksheetAssignment.learner).selectinload(Learner.volunteer_match),
            contains_eager(WorksheetAssignment.worksheet),
            selectinload(WorksheetAssignment.volunteer),
        )
        .order_by(
            WorksheetAssignment.completed.asc(),
            WorksheetAssignment.assigned_at.desc(),
            WorksheetAssignment.id.desc(),
        )
        .offset((page - 1) * TRACKER_PAGE_SIZE)
        .limit(TRACKER_PAGE_SIZE)
    ).all()

    capture_event(
        str(teacher.id),
        "page_viewed",
        properties={
            "page": "teacher_worksheet_assignments",
            "result_count": result_count,
            "status": filters["status"] or "all",
            "filtered_by_learner": bool(filters["learner"]),
            "subject": filters["subject"] or "all",
            "has_query": bool(filters["q"]),
            "range": filters["range"] or "all",
            "page_number": page,
        },
    )

    results_ctx = {
        "assignments": assignments,
        "filters": filters,
        # Only the filters in use: paging passes them straight on as query args.
        "page_args": {key: value for key, value in filters.items() if value},
        "page": page,
        "page_count": page_count,
        "page_size": TRACKER_PAGE_SIZE,
        "result_count": result_count,
        "now": utcnow_naive(),
        "stale_after_days": teacher_ops.STALE_AFTER_DAYS,
        "next_url": request.full_path.rstrip("?"),
    }
    if wants_fragment():
        return render_template("@page_components/teacher/assignment_results.jx", **results_ctx)

    pair_rows = teacher_ops.pair_rows(teacher)
    subjects = db.session.scalars(
        teacher_ops.learner_assignments(teacher).with_only_columns(Worksheet.subject).distinct().order_by(Worksheet.subject)
    ).all()
    return render_template(
        "@pages/teacher/worksheet_assignments.jx",
        summary=teacher_ops.assignment_summary(teacher),
        pair_rows=pair_rows,
        # "Print all outstanding" — one packet, offered while it fits in one print batch.
        all_outstanding_ids=[i for row in pair_rows for i in row["outstanding_ids"]],
        max_print_batch=MAX_PRINT_BATCH,
        learner_options=sorted(teacher.managed_learners, key=lambda learner: learner.sort_name),
        subjects=subjects,
        range_presets=list(_RANGES),
        **results_ctx,
    )


def _owned_assignments(teacher, ids: list[int]) -> list[WorksheetAssignment]:
    """`teacher_ops.owned_assignments` for a request: 404 for an unknown id, 403 for another teacher's."""
    try:
        return teacher_ops.owned_assignments(teacher, ids)
    except LookupError:
        abort(404)
    except PermissionError:
        abort(403)


@teacher_bp.route("/worksheet-assignments/print")
def teacher_print_assignments():
    """Several assignments (`?ids=1&ids=2`) as one PDF opened in the browser's viewer,
    each pair's names on its pages; `double_sided=on` starts each pair on a fresh sheet.
    `source` only labels the analytics event (which button printed)."""
    teacher = current_user
    ids = request.args.getlist("ids", type=int)
    if not ids:
        flash("Choose at least one worksheet to print.", "warning")
        return redirect(url_for("teacher.teacher_worksheet_assignments"))
    if len(set(ids)) > MAX_PRINT_BATCH:
        abort(400)
    assignments = _owned_assignments(teacher, ids)
    double_sided = request.args.get("double_sided") == "on"

    learner_ids = {a.learner_id for a in assignments}
    if len(learner_ids) == 1:
        name = get_pair_display_name(assignments[0].learner, assignments[0].pair_volunteer)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "pair"
    else:
        slug = "worksheets"
    capture_event(
        str(teacher.id),
        "worksheet_assignments_printed",
        properties={
            "assignment_count": len(assignments),
            "pair_count": len(learner_ids),
            "double_sided": double_sided,
            "source": request.args.get("source", "")[:40] or "unknown",
        },
    )
    return generate_assignments_pdf(
        assignments, f"{slug}-{utcnow_naive().strftime('%Y%m%d')}.pdf", double_sided, inline=True
    )


@teacher_bp.route("/worksheet-assignments/complete", methods=["POST"])
def teacher_complete_assignments():
    """Mark several assignments (`ids`) complete at once — the stack a pair handed back."""
    teacher = current_user
    ids = request.form.getlist("ids", type=int)
    back = safe_local_path(request.form.get("next")) or url_for("teacher.teacher_worksheet_assignments")
    if not ids:
        if wants_json():
            return jsonify(success=False, message="Choose at least one worksheet."), 400
        flash("Choose at least one worksheet.", "warning")
        return redirect(back)

    try:
        assignments = teacher_ops.complete_assignments(teacher, ids)
    except LookupError:
        abort(404)
    except PermissionError:
        abort(403)
    capture_event(
        str(teacher.id),
        "worksheet_completion_set",
        properties={"assignment_count": len(assignments), "completed": True, "mode": "bulk"},
    )

    count = len(assignments)
    message = f"{count} worksheet{'s' if count != 1 else ''} marked complete."
    if wants_json():
        return jsonify(success=True, message=message, completed=True)
    flash(message, "success")
    return redirect(back)
