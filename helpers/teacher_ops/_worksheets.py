from datetime import timedelta
from typing import Any, TypedDict

from sqlalchemy import Select, case, func
from sqlalchemy.orm import selectinload

from extensions import db
from helpers.teacher_ops._shared import _coerce_bool, _owned
from helpers.utils import utcnow_naive
from models import Learner, Teacher, Volunteer, Worksheet, WorksheetAssignment


def validate_assign_worksheet(teacher: Teacher, learner_id: int, worksheet_id: int) -> dict[str, Any]:
    """Resolve and check the rows an `assign_worksheet` call needs, without writing.

    Args:
        teacher (Teacher): Teacher making the assignment.
        learner_id (int): Learner to assign the worksheet to.
        worksheet_id (int): Worksheet to assign.

    Returns:
        dict[str, Any]: `{"learner", "volunteer", "worksheet"}`.
    """
    learner = _owned(Learner, learner_id, teacher, "learner")
    worksheet = db.session.get(Worksheet, worksheet_id)
    if worksheet is None:
        raise LookupError(f"No worksheet with id {worksheet_id}.")
    return {
        "learner": learner,
        "volunteer": learner.volunteer_match,
        "worksheet": worksheet,
    }


def assign_worksheet(teacher: Teacher, learner_id: int, worksheet_id: int) -> dict[str, Any]:
    """Give one worksheet to one learner. Duplicates are allowed — reassigning
    the same sheet is how a teacher asks for it again.

    Args:
        teacher (Teacher): Teacher making the assignment.
        learner_id (int): Learner to assign the worksheet to.
        worksheet_id (int): Worksheet to assign.

    Returns:
        dict[str, Any]: `{"assignment", "learner", "volunteer", "worksheet"}`.
    """
    resolved = validate_assign_worksheet(teacher, learner_id, worksheet_id)
    volunteer = resolved["volunteer"]
    assignment = WorksheetAssignment(
        teacher_id=teacher.id,
        learner_id=resolved["learner"].id,
        volunteer_id=volunteer.id if volunteer else None,
        worksheet_id=resolved["worksheet"].id,
    )
    db.session.add(assignment)
    db.session.commit()
    return {"assignment": assignment, **resolved}


def validate_set_assignment_completion(teacher: Teacher, assignment_id: int, completed: Any) -> dict[str, Any]:
    """The **learner** is the access gate, not who assigned the sheet.

    Args:
        teacher (Teacher): Teacher who must own the assignment's learner.
        assignment_id (int): Assignment to update.
        completed (Any): New completed value.

    Returns:
        dict[str, Any]: `{"assignment", "learner", "completed"}`.
    """
    # An assignment is a fact about the learner (a second teacher at the same
    # school may have set it) — checking the assignment's own teacher_id would
    # lock a teacher out of their own learner's list.
    assignment = db.session.get(WorksheetAssignment, assignment_id)
    if assignment is None:
        raise LookupError(f"No worksheet assignment with id {assignment_id}.")
    learner = assignment.learner
    if learner is None or learner.teacher_id != teacher.id:
        raise PermissionError("That worksheet belongs to another teacher's learner.")
    return {
        "assignment": assignment,
        "learner": learner,
        "completed": _coerce_bool(completed),
    }


def set_assignment_completion(teacher: Teacher, assignment_id: int, completed: Any) -> dict[str, Any]:
    """Mark one assignment done or put it back on the outstanding pile.

    Args:
        teacher (Teacher): Teacher who must own the assignment's learner.
        assignment_id (int): Assignment to update.
        completed (Any): New completed value.

    Returns:
        dict[str, Any]: `{"assignment", "learner", "completed"}`.
    """
    resolved = validate_set_assignment_completion(teacher, assignment_id, completed)
    assignment = resolved["assignment"]
    assignment.completed = resolved["completed"]
    # Reopening clears completed_at — a stale timestamp on an incomplete row
    # would date a completion that no longer exists.
    assignment.completed_at = utcnow_naive() if resolved["completed"] else None
    db.session.commit()
    return resolved


# ── the tracker: every assignment of a teacher's learners ──────────────────────

#: A sheet still outstanding after this long has probably been lost or skipped.
STALE_AFTER_DAYS = 14
#: "Completed recently" on the tracker's summary tiles.
RECENT_COMPLETED_DAYS = 30


class AssignmentSummary(TypedDict):
    """Totals over every assignment of a teacher's learners."""

    total: int
    outstanding: int
    completed_recent: int
    stale: int
    completion_rate: int


class PairRow(TypedDict):
    """One learner's sheets on the tracker's per-pair overview."""

    learner: Learner
    volunteer: Volunteer | None
    matched: bool
    outstanding_ids: list[int]
    oldest_outstanding_days: int | None
    last_completed_days: int | None
    total: int
    needs_sheet: bool


def learner_assignments(teacher: Teacher) -> Select[tuple[WorksheetAssignment]]:
    """Every assignment of the teacher's learners, with `Learner` and `Worksheet` joined for filtering.

    The learner is the gate, not who assigned the sheet: a colleague's assignment to one of
    this teacher's learners is theirs to see (docs/features/worksheets.md).

    Args:
        teacher (Teacher): Teacher whose learners' assignments to select.

    Returns:
        Select[tuple[WorksheetAssignment]]: The statement, to narrow, count or page.
    """
    return (
        db.select(WorksheetAssignment)
        .join(Learner, Learner.id == WorksheetAssignment.learner_id)
        .join(Worksheet, Worksheet.id == WorksheetAssignment.worksheet_id)
        .where(Learner.teacher_id == teacher.id)
    )


def assignment_summary(teacher: Teacher) -> AssignmentSummary:
    """Totals over every assignment of the teacher's learners, never a filtered page.

    Args:
        teacher (Teacher): Teacher to summarise.

    Returns:
        AssignmentSummary: Counts and the completion rate (a whole percent).
    """
    now = utcnow_naive()
    outstanding = WorksheetAssignment.completed.is_(False)
    total, outstanding_count, completed_recent, stale = db.session.execute(
        learner_assignments(teacher).with_only_columns(
            func.count(WorksheetAssignment.id),
            func.coalesce(func.sum(case((outstanding, 1), else_=0)), 0),
            func.coalesce(func.sum(case(
                (WorksheetAssignment.completed_at >= now - timedelta(days=RECENT_COMPLETED_DAYS), 1), else_=0)), 0),
            func.coalesce(func.sum(case(
                (outstanding & (WorksheetAssignment.assigned_at < now - timedelta(days=STALE_AFTER_DAYS)), 1),
                else_=0)), 0),
        )
    ).one()
    total = int(total or 0)
    open_count = int(outstanding_count or 0)
    return AssignmentSummary(
        total=total,
        outstanding=open_count,
        completed_recent=int(completed_recent or 0),
        stale=int(stale or 0),
        completion_rate=round((total - open_count) * 100 / total) if total else 0,
    )


def outstanding_count(teacher: Teacher) -> int:
    """Outstanding sheets across the teacher's learners — the count on the Assigned tab.

    Args:
        teacher (Teacher): Teacher to count for.

    Returns:
        int: Assignments not yet completed.
    """
    return db.session.scalar(
        learner_assignments(teacher)
        .where(WorksheetAssignment.completed.is_(False))
        .with_only_columns(func.count(WorksheetAssignment.id))
    ) or 0


def pair_rows(teacher: Teacher) -> list[PairRow]:
    """One row per learner who is matched or has ever had a sheet, most urgent first.

    A matched pair with nothing outstanding has nothing to work on next session, so it
    sorts first, then the longest-waiting sheets.

    Args:
        teacher (Teacher): Teacher whose learners to list.

    Returns:
        list[PairRow]: What each learner has outstanding (ids, for printing it all at once)
            and how long since anything moved.
    """
    now = utcnow_naive()
    assignments = db.session.execute(
        learner_assignments(teacher)
        .with_only_columns(
            WorksheetAssignment.id, WorksheetAssignment.learner_id, WorksheetAssignment.completed,
            WorksheetAssignment.assigned_at, WorksheetAssignment.completed_at,
        )
        .order_by(WorksheetAssignment.assigned_at.asc(), WorksheetAssignment.id.asc())
    ).all()
    by_learner: dict[int, list] = {}
    for row in assignments:
        by_learner.setdefault(row.learner_id, []).append(row)

    learners = db.session.scalars(
        db.select(Learner).where(Learner.teacher_id == teacher.id).options(selectinload(Learner.volunteer_match))
    ).all()
    rows: list[PairRow] = []
    for learner in learners:
        mine = by_learner.get(learner.id, [])
        matched = bool(learner.is_matched and learner.volunteer_match)
        if not matched and not mine:
            continue
        outstanding = [r for r in mine if not r.completed]
        completed_at = [r.completed_at for r in mine if r.completed and r.completed_at]
        rows.append(PairRow(
            learner=learner,
            volunteer=learner.volunteer_match if matched else None,
            matched=matched,
            outstanding_ids=[r.id for r in outstanding],
            oldest_outstanding_days=(now - outstanding[0].assigned_at).days if outstanding else None,
            last_completed_days=(now - max(completed_at)).days if completed_at else None,
            total=len(mine),
            needs_sheet=matched and not outstanding,
        ))
    rows.sort(key=lambda r: (
        not r["needs_sheet"],
        -(r["oldest_outstanding_days"] if r["oldest_outstanding_days"] is not None else -1),
        r["learner"].sort_name,
    ))
    return rows


def owned_assignments(teacher: Teacher, ids: list[int]) -> list[WorksheetAssignment]:
    """The assignments `ids` names, every one of them the teacher's learners', or none at all.

    Args:
        teacher (Teacher): Teacher who must own each assignment's learner.
        ids (list[int]): Assignment ids; repeats count once.

    Returns:
        list[WorksheetAssignment]: The assignments, learner and worksheet loaded.

    Raises:
        LookupError: An id names no assignment.
        PermissionError: An assignment belongs to another teacher's learner.
    """
    wanted = set(ids)
    found = db.session.scalars(
        db.select(WorksheetAssignment)
        .where(WorksheetAssignment.id.in_(wanted))
        .options(selectinload(WorksheetAssignment.learner), selectinload(WorksheetAssignment.worksheet))
    ).all()
    if len(found) != len(wanted):
        raise LookupError("No worksheet assignment with one of those ids.")
    if any(not a.learner or a.learner.teacher_id != teacher.id for a in found):
        raise PermissionError("One of those worksheets belongs to another teacher's learner.")
    return list(found)


def complete_assignments(teacher: Teacher, ids: list[int]) -> list[WorksheetAssignment]:
    """Mark several assignments complete at once, in one commit, after checking every one.

    Args:
        teacher (Teacher): Teacher who must own each assignment's learner.
        ids (list[int]): Assignment ids.

    Returns:
        list[WorksheetAssignment]: The assignments, now all complete.

    Raises:
        LookupError: An id names no assignment; nothing was changed.
        PermissionError: An assignment belongs to another teacher's learner; nothing was changed.
    """
    assignments = owned_assignments(teacher, ids)
    now = utcnow_naive()
    for assignment in assignments:
        if not assignment.completed:
            assignment.completed = True
            assignment.completed_at = now
    db.session.commit()
    return assignments
