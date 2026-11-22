"""Staging, review and apply for assistant-proposed writes.

Nothing the assistant does mutates a teacher's data. A write tool validates its
request immediately — so the model learns of a bad request in the same turn —
and then writes an `AssistantChange` row instead of touching the target table.
The teacher reviews the diff field by field and applies each one.

Apply **replays the tool call** through `helpers/teacher_ops.py`. It never
writes `after` onto the row directly: a staged value that is legal-looking but
breaks an invariant (an absence carrying hours, a capacity below the count
already matched) still looks fine on a review card, and the row is the only
place that can say no.

Every write op is one `WriteOp` below. Adding a capability is one entry plus a
decorated function in `tools/writes.py` — deliberately not auto-derived from the
mapper; see `docs/features/ai-assistant.md`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

from extensions import db
from helpers import teacher_ops
from helpers.ai import scope
from helpers.refusal import Refusal, refusal_message
from models import AssistantChange

if TYPE_CHECKING:
    from helpers.ai.tools import ToolContext
    from models import Teacher

logger = logging.getLogger(__name__)


class DiffRow(TypedDict):
    """One field on a staged change's review card."""
    field: str
    label: str
    before: Any  # column's live type — varies per entity
    after: Any
    editable: bool
    changed: bool


class ChangePayload(TypedDict):
    """One staged change as the review UI needs it."""
    id: int
    entity: str
    op: str
    tool: str
    summary: str | None
    status: str
    error: str | None
    seq: int
    depends_on_id: int | None
    fields: list[DiffRow]


class ApplyResult(TypedDict):
    """Outcome of applying one staged change."""
    id: int
    status: str
    error: str | None


@dataclass
class DiffField:
    """One row of a review card."""
    column: str          # column name on the target model
    arg: str             # the tool argument it maps back to
    editable: bool = True
    label: str = ""      # shown to the teacher; defaults to the column name
    #: How the live column value is reduced before comparing it to `before`.
    #: **Must match how `build` produced `before`** — a datetime recorded as a
    #: bare date otherwise reads as changed on every staleness check, and every
    #: attendance edit reports stale.
    normalize: Callable | None = None

    def title(self) -> str:
        """Display label for this field on the review card.

        Returns:
            str: `label` if set, else the column name with underscores as spaces.
        """
        return self.label or self.column.replace("_", " ")


@dataclass
class WriteOp:
    """One staged-write capability: how to validate, build a diff, and apply it."""
    name: str
    entity: str
    op: str                       # create | update
    validate: Callable            # (teacher, args) -> resolved dict
    build: Callable               # (teacher, args, resolved) -> (pk, before, after, summary)
    apply: Callable               # (teacher, args) -> anything
    fields: list[DiffField] = field(default_factory=list)

    def arg_for(self, column: str) -> str | None:
        """Tool argument name that maps back to a column.

        Args:
            column (str): Column name to look up.

        Returns:
            str | None: The matching `DiffField.arg`, or None if not found.
        """
        for item in self.fields:
            if item.column == column:
                return item.arg
        return None

    def editable_columns(self) -> set[str]:
        """Columns the teacher may edit on a staged change.

        Returns:
            set[str]: Column names with `editable=True`.
        """
        return {item.column for item in self.fields if item.editable}


WRITE_OPS: dict[str, WriteOp] = {}


def register(op: WriteOp) -> WriteOp:
    """Add a WriteOp to the catalogue, keyed by its name.

    Args:
        op (WriteOp): The write operation to register.

    Returns:
        WriteOp: `op`, unchanged (so it can be used as a decorator-style call).
    """
    WRITE_OPS[op.name] = op
    return op


# ── staging ──────────────────────────────────────────────────────────────────

def stage(ctx: ToolContext, tool_name: str, args: dict[str, Any], summary_prefix: str = "") -> AssistantChange:
    """Validate now, write an AssistantChange, mutate nothing. Raises `teacher_ops`'s own ValueError/LookupError/PermissionError straight through.

    Args:
        ctx (ToolContext): Tool call context (`teacher`, `conversation_id`, `staged`).
        tool_name (str): Registered `WriteOp` name.
        args (dict[str, Any]): Tool call arguments.
        summary_prefix (str): Text prepended to the built summary.

    Returns:
        AssistantChange: The newly staged, pending change.
    """
    write_op = WRITE_OPS.get(tool_name)
    if write_op is None:
        raise Refusal(f"No staged write named {tool_name!r}.")

    teacher = ctx.teacher
    resolved = write_op.validate(teacher, args)
    pk, before, after, summary = write_op.build(teacher, args, resolved)

    change = AssistantChange(
        conversation_id=ctx.conversation_id,
        teacher_id=teacher.id,
        seq=len(ctx.staged),
        op=write_op.op,
        entity=write_op.entity,
        pk=pk,
        before=before,
        after=after,
        tool_name=tool_name,
        tool_args=dict(args),
        summary=(summary_prefix + summary)[:300],
        status="pending",
    )
    db.session.add(change)
    db.session.commit()
    ctx.staged.append(change.id)
    return change


def change_payload(change: AssistantChange) -> ChangePayload:
    """One staged change as the review UI needs it.

    Args:
        change (AssistantChange): The staged change to render.

    Returns:
        ChangePayload: `{"id", "entity", "op", "tool", "summary", "status",
            "error", "seq", "depends_on_id", "fields"}`.
    """
    write_op = WRITE_OPS.get(change.tool_name)
    editable = write_op.editable_columns() if write_op else set()
    labels = {item.column: item.title() for item in (write_op.fields if write_op else [])}

    before = change.before or {}
    after = change.after or {}
    rows: list[DiffRow] = []
    for column in after:
        rows.append({
            "field": column,
            "label": labels.get(column, column.replace("_", " ")),
            "before": before.get(column),
            "after": after.get(column),
            "editable": column in editable,
            "changed": before.get(column) != after.get(column),
        })

    return {
        "id": change.id,
        "entity": change.entity,
        "op": change.op,
        "tool": change.tool_name,
        "summary": change.summary,
        "status": change.status,
        "error": change.error,
        "seq": change.seq,
        "depends_on_id": change.depends_on_id,
        "fields": rows,
    }


def pending_changes(teacher: Teacher) -> list[AssistantChange]:
    """A teacher's pending staged changes, in application order.

    Args:
        teacher (Teacher): Teacher whose changes to list.

    Returns:
        list[AssistantChange]: Pending changes in the order they were staged. That is
            `id` order: `stage` commits each change as it goes, and `seq` restarts at 0
            every turn, so sorting by it would interleave turns.
    """
    return list(db.session.scalars(
        db.select(AssistantChange)
        .where(AssistantChange.teacher_id == teacher.id,
               AssistantChange.status == "pending")
        .order_by(AssistantChange.id.asc())
    ).all())


def get_change(teacher: Teacher, change_id: int) -> AssistantChange:
    """Fetch one staged change and confirm it belongs to `teacher`.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        change_id (int): Change id to look up.

    Returns:
        AssistantChange: The change.
    """
    change = db.session.get(AssistantChange, change_id)
    if change is None:
        raise LookupError(f"No staged change with id {change_id}.")
    if change.teacher_id != teacher.id:
        raise PermissionError("That staged change belongs to another teacher.")
    return change


# ── editing a staged value ───────────────────────────────────────────────────

def update_change(teacher: Teacher, change_id: int, values: dict[str, Any]) -> AssistantChange:
    """Teacher edits the proposed value before applying it.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        change_id (int): Change to edit.
        values (dict[str, Any]): Column name -> new value, for editable columns only.

    Returns:
        AssistantChange: The updated, still-pending change.
    """
    change = get_change(teacher, change_id)
    if change.status != "pending":
        raise Refusal("Only a pending change can be edited.")

    write_op = WRITE_OPS.get(change.tool_name)
    if write_op is None:
        raise Refusal(f"No staged write named {change.tool_name!r}.")

    editable = write_op.editable_columns()
    after = dict(change.after or {})
    for column, value in (values or {}).items():
        if column not in editable:
            raise Refusal(f"{column!r} cannot be edited on this change.")
        after[column] = value

    # Re-validate against the merged arguments so an edit that breaks an
    # invariant is refused here rather than at apply time.
    merged = _merged_args(write_op, change, after)
    write_op.validate(teacher, merged)

    change.after = after
    change.tool_args = merged
    db.session.commit()
    return change


def _merged_args(write_op: WriteOp, change: AssistantChange, after: dict[str, Any] | None) -> dict[str, Any]:
    """Merge edited diff values back onto the original tool call arguments.

    Args:
        write_op (WriteOp): The change's write operation.
        change (AssistantChange): The staged change (for its original `tool_args`).
        after (dict[str, Any] | None): Column -> proposed value (possibly
            teacher-edited); None when the change carries no diff.

    Returns:
        dict[str, Any]: Tool arguments with edited columns mapped back onto their args.
    """
    args = dict(change.tool_args or {})
    for column, value in (after or {}).items():
        arg = write_op.arg_for(column)
        if arg:
            args[arg] = value
    return args


# ── staleness ────────────────────────────────────────────────────────────────

def _live_values(change: AssistantChange, columns: list[str]) -> dict[str, Any] | None:
    """Current DB values for the columns the diff recorded, or None if gone.

    Args:
        change (AssistantChange): The staged change (for its target `entity`/`pk`).
        columns (list[str]): Column names to read.

    Returns:
        dict[str, Any] | None: Column -> current normalized value, or None if the row is gone.
    """
    if not change.pk:
        return None
    try:
        model, _ = scope.resolve(change.entity)
    except PermissionError:
        return None
    row = db.session.get(model, change.pk.get("id"))
    if row is None:
        return None

    write_op = WRITE_OPS.get(change.tool_name)
    normalizers = {
        item.column: item.normalize
        for item in (write_op.fields if write_op else [])
        if item.normalize
    }
    values = {}
    for column in columns:
        raw = getattr(row, column, None)
        reduce = normalizers.get(column)
        values[column] = reduce(raw) if reduce else scope._jsonable(raw)
    return values


def staleness(change: AssistantChange) -> dict[str, Any]:
    """Which recorded `before` values no longer match the live row. Empty means unchanged; a staged create is never stale.

    Args:
        change (AssistantChange): The staged change to check.

    Returns:
        dict[str, Any]: Column (or `"__row__"` if the row was deleted) -> `{"was", "now"}`.
    """
    before = change.before or {}
    if not before:
        return {}
    live = _live_values(change, list(before))
    if live is None:
        return {"__row__": {"was": "present", "now": "deleted"}}
    return {
        column: {"was": value, "now": live[column]}
        for column, value in before.items()
        if live.get(column) != value
    }


# ── apply / reject ───────────────────────────────────────────────────────────

def apply_change(teacher: Teacher, change_id: int) -> AssistantChange:
    """Replay one staged change through teacher_ops.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        change_id (int): Change to apply.

    Returns:
        AssistantChange: The change, now `applied` (or `stale`/`pending` on failure).
    """
    change = get_change(teacher, change_id)
    if change.status != "pending":
        raise Refusal(f"That change is already {change.status}.")

    write_op = WRITE_OPS.get(change.tool_name)
    if write_op is None:
        raise Refusal(f"No staged write named {change.tool_name!r}.")

    if change.depends_on_id:
        parent = db.session.get(AssistantChange, change.depends_on_id)
        if parent is not None and parent.status != "applied":
            raise Refusal(
                "The change this one depends on was not applied, so this one is skipped."
            )

    moved = staleness(change)
    if moved:
        change.status = "stale"
        change.error = "The record changed after this was proposed."
        db.session.commit()
        return change

    from helpers.utils import utcnow_naive

    args = _merged_args(write_op, change, change.after)
    try:
        write_op.apply(teacher, args)
    except (ValueError, LookupError, PermissionError) as exc:
        db.session.rollback()
        change.status = "pending"
        change.error = _failure_text(exc)
        db.session.commit()
        raise

    change.status = "applied"
    change.applied_at = utcnow_naive()
    change.error = None
    db.session.commit()
    return change


def _failure_text(exc: Exception) -> str:
    """What the review panel says about a change that could not be applied.

    Args:
        exc (Exception): What the write op raised.

    Returns:
        str: A `Refusal`'s own message, or a fixed line per exception type — never the raw text
        of an exception nobody wrote for the teacher.
    """
    if isinstance(exc, LookupError):
        return "That record no longer exists."
    if isinstance(exc, PermissionError):
        return "That record belongs to another teacher."
    return refusal_message(exc)


def reject_change(teacher: Teacher, change_id: int) -> AssistantChange:
    """Mark one pending change rejected.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        change_id (int): Change to reject.

    Returns:
        AssistantChange: The now-rejected change.
    """
    change = get_change(teacher, change_id)
    if change.status != "pending":
        raise Refusal(f"That change is already {change.status}.")
    change.status = "rejected"
    db.session.commit()
    return change


def apply_all(teacher: Teacher) -> list[ApplyResult]:
    """Apply every pending change in seq order, reporting each outcome.

    Args:
        teacher (Teacher): Teacher whose pending changes to apply.

    Returns:
        list[ApplyResult]: One `{"id", "status", "error"}` per change attempted.
    """
    results: list[ApplyResult] = []
    for change in pending_changes(teacher):
        try:
            applied = apply_change(teacher, change.id)
            results.append({"id": change.id, "status": applied.status,
                            "error": applied.error})
        except (ValueError, LookupError, PermissionError) as exc:
            results.append({"id": change.id, "status": "failed", "error": _failure_text(exc)})
    return results


# ── the write catalogue ──────────────────────────────────────────────────────

def _name(row: Any, fallback: str) -> str:
    """A row's display name, falling back when it has none.

    Args:
        row (Any): Model instance to read `.name` from.
        fallback (str): Value to use when `row.name` is empty.

    Returns:
        str: `row.name`, or `fallback`.
    """
    return getattr(row, "name", None) or fallback


register(WriteOp(
    name="assign_worksheet",
    entity="WorksheetAssignment",
    op="create",
    validate=lambda teacher, a: teacher_ops.validate_assign_worksheet(
        teacher, a["learner_id"], a["worksheet_id"]),
    apply=lambda teacher, a: teacher_ops.assign_worksheet(
        teacher, a["learner_id"], a["worksheet_id"]),
    fields=[
        DiffField("learner_id", "learner_id", label="learner"),
        DiffField("worksheet_id", "worksheet_id", label="worksheet"),
    ],
    build=lambda teacher, a, r: (
        None,
        None,
        {"learner_id": r["learner"].id, "worksheet_id": r["worksheet"].id},
        'Assign "{}" to {}'.format(
            r["worksheet"].title,
            _name(r["learner"], r["learner"].username),
        ),
    ),
))


def _attendance_build(teacher: Teacher, args: dict[str, Any], resolved: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Build the diff for `update_attendance` from a validated resolve() result.

    Args:
        teacher (Teacher): Teacher staging the change.
        args (dict[str, Any]): Original tool call arguments.
        resolved (dict[str, Any]): Output of `teacher_ops.validate_update_user_attendance`.

    Returns:
        tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]: `(pk, before, after, summary)`.
    """
    record = resolved["record"]
    return (
        {"id": record.id},
        {
            "date": record.date.date().isoformat(),
            "is_present": record.is_present,
            "duration": float(record.duration or 0),
            "notes": record.notes,
        },
        {
            "date": resolved["date"].isoformat(),
            "is_present": resolved["is_present"],
            "duration": float(resolved["duration"]),
            "notes": resolved["notes"],
        },
        "Update {}'s session on {}".format(
            _name(record.user, "person") if record.user else "a person",
            resolved["date"].isoformat(),
        ),
    )


register(WriteOp(
    name="update_attendance",
    entity="Attendance",
    op="update",
    validate=lambda teacher, a: teacher_ops.validate_update_user_attendance(
        teacher, a["attendance_id"], date=a.get("date"), is_present=a.get("is_present"),
        duration=a.get("duration"), notes=a.get("notes")),
    apply=lambda teacher, a: teacher_ops.update_user_attendance(
        teacher, a["attendance_id"], date=a.get("date"), is_present=a.get("is_present"),
        duration=a.get("duration"), notes=a.get("notes")),
    fields=[
        # `before` records the calendar day, so the live datetime is reduced
        # the same way before the two are compared.
        DiffField("date", "date",
                  normalize=lambda v: v.date().isoformat() if v else None),
        DiffField("is_present", "is_present"),
        DiffField("duration", "duration", label="hours",
                  normalize=lambda v: float(v or 0)),
        DiffField("notes", "notes"),
    ],
    build=_attendance_build,
))


def _pair_args(a: dict[str, Any]) -> dict[str, Any]:
    """Flat staged-change args -> the one-pair dict `teacher_ops.log_attendance_*` takes.

    Args:
        a (dict[str, Any]): Staged-change tool arguments.

    Returns:
        dict[str, Any]: A single pair dict for `teacher_ops.validate_log_attendance_batch`.
    """
    return {
        "learner_id": a["learner_id"],
        "volunteer_id": a.get("volunteer_id"),
        "is_present": a.get("is_present", True),
        "duration": a.get("duration"),
        "notes": a.get("notes"),
        "volunteer_is_present": a.get("volunteer_is_present"),
        "volunteer_duration": a.get("volunteer_duration"),
        "volunteer_notes": a.get("volunteer_notes"),
    }


def _attendance_pair_build(teacher: Teacher, args: dict[str, Any], resolved: dict[str, Any]) -> tuple[None, None, dict[str, Any], str]:
    """Build the diff for `log_attendance_pair` from a validated resolve() result.

    Args:
        teacher (Teacher): Teacher staging the change.
        args (dict[str, Any]): Original tool call arguments.
        resolved (dict[str, Any]): Output of `teacher_ops.validate_log_attendance_pair`.

    Returns:
        tuple[None, None, dict[str, Any], str]: `(pk, before, after, summary)` — a staged create has no `before`.
    """
    pair = resolved["pairs"][0]
    learner = pair["learner"]
    after = {
        "learner_id": learner.id,
        "volunteer_id": pair["volunteer"].id if pair["volunteer"] else None,
        "is_present": pair["is_present"],
        "duration": float(pair["duration"]),
        "notes": pair["notes"],
    }
    return (
        None, None, after,
        "Log {}'s session on {}".format(
            _name(learner, learner.username), resolved["date"].isoformat(),
        ),
    )


register(WriteOp(
    name="log_attendance_pair",
    entity="Attendance",
    op="create",
    validate=lambda teacher, a: teacher_ops.validate_log_attendance_pair(
        teacher, a["date"], _pair_args(a), default_duration=a.get("default_duration")),
    apply=lambda teacher, a: teacher_ops.log_attendance_pair(
        teacher, a["date"], _pair_args(a), default_duration=a.get("default_duration")),
    # The learner's own row is what's reviewed and edited; a pair's volunteer
    # side is mirrored as a side effect of apply (same as match_pair's
    # volunteer.is_matched flip), not a separate editable field here.
    fields=[
        DiffField("learner_id", "learner_id", editable=False, label="learner"),
        DiffField("volunteer_id", "volunteer_id", editable=False, label="volunteer"),
        DiffField("is_present", "is_present"),
        DiffField("duration", "duration", label="hours"),
        DiffField("notes", "notes"),
    ],
    build=_attendance_pair_build,
))


register(WriteOp(
    name="set_volunteer_capacity",
    entity="Volunteer",
    op="update",
    validate=lambda teacher, a: teacher_ops.validate_set_volunteer_capacity(
        teacher, a["volunteer_id"], a["capacity"]),
    apply=lambda teacher, a: teacher_ops.set_volunteer_capacity(
        teacher, a["volunteer_id"], a["capacity"]),
    # `before` reads Volunteer.capacity, which floors a NULL column at 1.
    fields=[DiffField("match_capacity", "capacity", label="learner limit",
                      normalize=lambda v: max(1, v or 1))],
    build=lambda teacher, a, r: (
        {"id": r["volunteer"].id},
        {"match_capacity": r["volunteer"].capacity},
        {"match_capacity": r["capacity"]},
        "Set {}'s learner limit to {}".format(
            _name(r["volunteer"], r["volunteer"].email), r["capacity"],
        ),
    ),
))


register(WriteOp(
    name="set_default_capacity",
    entity="Teacher",
    op="update",
    validate=lambda teacher, a: teacher_ops.validate_set_default_capacity(
        teacher, a["capacity"]),
    apply=lambda teacher, a: teacher_ops.set_default_capacity(teacher, a["capacity"]),
    fields=[DiffField("default_match_capacity", "capacity",
                      label="default learner limit",
                      normalize=lambda v: max(1, v or 1))],
    build=lambda teacher, a, r: (
        {"id": teacher.id},
        {"default_match_capacity": max(1, teacher.default_match_capacity or 1)},
        {"default_match_capacity": r["capacity"]},
        "Set the default learner limit for new volunteers to {}".format(r["capacity"]),
    ),
))


register(WriteOp(
    name="match_pair",
    entity="Learner",
    op="update",
    validate=lambda teacher, a: teacher_ops.validate_match_pair(
        teacher, a["learner_id"], a["volunteer_id"]),
    apply=lambda teacher, a: teacher_ops.match_pair(
        teacher, a["learner_id"], a["volunteer_id"]),
    fields=[DiffField("volunteer_id", "volunteer_id", label="volunteer")],
    build=lambda teacher, a, r: (
        {"id": r["learner"].id},
        {"volunteer_id": r["learner"].volunteer_id},
        {"volunteer_id": r["volunteer"].id},
        "Match {} with {}".format(
            _name(r["learner"], r["learner"].username),
            _name(r["volunteer"], r["volunteer"].email),
        ),
    ),
))


register(WriteOp(
    name="unmatch_pair",
    entity="Learner",
    op="update",
    validate=lambda teacher, a: teacher_ops.validate_unmatch_pair(teacher, a["learner_id"]),
    apply=lambda teacher, a: teacher_ops.unmatch_pair(teacher, a["learner_id"]),
    # Not editable: "unmatch, but from someone else" is a different change.
    fields=[
        DiffField("volunteer_id", "volunteer_id", editable=False, label="volunteer"),
        DiffField("is_matched", "", editable=False, label="matched"),
    ],
    build=lambda teacher, a, r: (
        {"id": r["learner"].id},
        {"volunteer_id": r["learner"].volunteer_id, "is_matched": True},
        {"volunteer_id": None, "is_matched": False},
        "Unmatch {} from {}".format(
            _name(r["learner"], r["learner"].username),
            _name(r["volunteer"], r["volunteer"].email),
        ),
    ),
))
