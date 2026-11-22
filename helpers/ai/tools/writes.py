"""Curated write tools. Every one stages a proposal; none mutates anything.

Each validates through `helpers/teacher_ops.py` at call time, so the model is
told immediately when a request is impossible ("that volunteer is already
full") instead of the teacher discovering it on apply.

These are hand-written on purpose. A generic create/update over the mapper
would gain every new scoped table for free, but it would bypass the invariants
that live in code rather than in the schema — an absence must carry zero hours,
a capacity may not drop below the count already matched, a full volunteer may
not take another learner, unmatching must re-derive `is_matched` on both sides.
A staged row that is *legal but wrong* still looks fine in review. Reads are
safe to auto-derive because the worst case is a useless answer.
"""

from typing import Any, TypedDict

from helpers.ai import staging
from helpers.ai.tools import ToolContext, ai_tool
from helpers.ai.tools.domain import AutoMatchProposal, preview_auto_match

_STAGED = (
    " Nothing is written: this is proposed for the teacher to review and apply."
)


class StagedChangePayload(TypedDict):
    """A single proposed write, as every one-change tool below returns it."""
    staged_change_id: int
    summary: str | None


class StagedPair(TypedDict):
    """One pair staged by `log_attendance_batch`."""
    staged_change_id: int
    learner_id: int | None


class BatchStageResult(TypedDict):
    """Result of staging a whole day's attendance pairs.

    `skipped` carries every key from the caller's own pair dict (arbitrary —
    see the tool's `parameters` schema) plus `reason`, so `dict[str, Any]`
    rather than a fixed shape.
    """
    staged: list[StagedPair]
    skipped: list[dict[str, Any]]


class StagedProposal(AutoMatchProposal):
    """One auto-match proposal, staged."""
    staged_change_id: int


class SkippedProposal(AutoMatchProposal):
    """One auto-match proposal that failed to stage, with its reason."""
    reason: str


class AutoMatchStageResult(TypedDict):
    """Result of staging every pair the automatic matcher proposed."""
    staged: list[StagedProposal]
    skipped: list[AutoMatchProposal | SkippedProposal]
    unmatched: list[str]


@ai_tool(
    name="assign_worksheet",
    description="Propose giving one worksheet to one learner." + _STAGED,
    label="Proposing a worksheet for learner {learner_id}",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "learner_id": {"type": "integer"},
            "worksheet_id": {"type": "integer"},
        },
        "required": ["learner_id", "worksheet_id"],
    },
)
def assign_worksheet(ctx: ToolContext, learner_id: int, worksheet_id: int) -> StagedChangePayload:
    """Stage giving one worksheet to one learner.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to assign the worksheet to.
        worksheet_id (int): Worksheet to assign.

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    change = staging.stage(ctx, "assign_worksheet", {
        "learner_id": int(learner_id), "worksheet_id": int(worksheet_id),
    })
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="update_attendance",
    description=(
        "Propose a correction to one attendance record — a learner's own or a "
        "volunteer's own, whichever id is given. Marking a session absent "
        "always zeroes its hours; a session that took place must carry more "
        "than zero. Omitted fields keep their current value." + _STAGED
    ),
    label="Proposing an attendance fix",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "attendance_id": {"type": "integer"},
            "date": {"type": "string", "description": "'YYYY-MM-DD'."},
            "is_present": {"type": "boolean"},
            "duration": {"type": "number", "description": "Hours; ignored when absent."},
            "notes": {"type": "string"},
        },
        "required": ["attendance_id"],
    },
)
def update_attendance(ctx: ToolContext, attendance_id: int, date: str | None = None, is_present: bool | None = None, duration: float | None = None, notes: str | None = None) -> StagedChangePayload:
    """Stage a correction to one attendance record.

    Args:
        ctx (ToolContext): Tool call context.
        attendance_id (int): Record to correct.
        date (str | None): New session date ('YYYY-MM-DD'), or None to keep it.
        is_present (bool | None): New present/absent value, or None to keep it.
        duration (float | None): New duration in hours, or None to keep/derive it.
        notes (str | None): New notes, or None to keep them.

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    args = {"attendance_id": int(attendance_id)}
    for key, value in (("date", date), ("is_present", is_present),
                       ("duration", duration), ("notes", notes)):
        if value is not None:
            args[key] = value
    change = staging.stage(ctx, "update_attendance", args)
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="log_attendance_batch",
    description=(
        "Propose logging attendance for a set of pairs on one day — one "
        "reviewable change per pair, so the teacher can apply some and skip "
        "others. Each pair creates a learner session and, when it has a "
        "volunteer, a mirrored volunteer session (same mark and hours unless "
        "the pair gives its own volunteer_is_present / volunteer_duration / "
        "volunteer_notes). A volunteer keeps one session record per day "
        "however many learners they hold. Re-submitting a pair already logged "
        "that day corrects it rather than duplicating it." + _STAGED
    ),
    label="Proposing attendance for {date}",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "'YYYY-MM-DD'."},
            "default_duration": {
                "type": "number",
                "description": "Fallback hours for a pair with no duration of its own.",
            },
            "pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "learner_id": {"type": "integer"},
                        "volunteer_id": {"type": "integer"},
                        "is_present": {"type": "boolean"},
                        "duration": {"type": "number"},
                        "notes": {"type": "string"},
                        "volunteer_is_present": {"type": "boolean"},
                        "volunteer_duration": {"type": "number"},
                        "volunteer_notes": {"type": "string"},
                    },
                    "required": ["learner_id"],
                },
            },
        },
        "required": ["date", "pairs"],
    },
)
def log_attendance_batch(ctx: ToolContext, date: str, pairs: list[dict[str, Any]], default_duration: float | None = None) -> BatchStageResult:
    """Stage one attendance change per pair for a single day.

    Args:
        ctx (ToolContext): Tool call context.
        date (str): Session date ('YYYY-MM-DD').
        pairs (list[dict[str, Any]]): One dict per pair, see the tool's `parameters` schema.
        default_duration (float | None): Fallback hours for a pair with none of its own.

    Returns:
        BatchStageResult: `{"staged": [...], "skipped": [...]}`.
    """
    staged: list[StagedPair] = []
    skipped: list[dict[str, Any]] = []
    for pair in pairs:
        args = dict(pair)
        args["date"] = date
        if default_duration is not None:
            args["default_duration"] = default_duration
        try:
            change = staging.stage(ctx, "log_attendance_pair", args)
        except (ValueError, LookupError, PermissionError) as exc:
            # One bad pair (unknown learner, no duration anywhere) must not
            # cost the rest of the roster their staged changes.
            skipped.append({**pair, "reason": str(exc)})
            continue
        staged.append({"staged_change_id": change.id, "learner_id": pair.get("learner_id")})
    return {"staged": staged, "skipped": skipped}


@ai_tool(
    name="set_volunteer_capacity",
    description=(
        "Propose how many learners one volunteer may hold at once (1-5). "
        "Cannot go below the number they already have." + _STAGED
    ),
    label="Proposing a limit for volunteer {volunteer_id}",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "volunteer_id": {"type": "integer"},
            "capacity": {"type": "integer"},
        },
        "required": ["volunteer_id", "capacity"],
    },
)
def set_volunteer_capacity(ctx: ToolContext, volunteer_id: int, capacity: int) -> StagedChangePayload:
    """Stage a learner-capacity change for one volunteer.

    Args:
        ctx (ToolContext): Tool call context.
        volunteer_id (int): Volunteer to change.
        capacity (int): New capacity (1-5).

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    change = staging.stage(ctx, "set_volunteer_capacity", {
        "volunteer_id": int(volunteer_id), "capacity": int(capacity),
    })
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="set_default_capacity",
    description=(
        "Propose the learner limit that newly registering volunteers start on "
        "(1-5). Never rewrites a volunteer already on the roster." + _STAGED
    ),
    label="Proposing a new default limit",
    writes=True,
    parameters={
        "type": "object",
        "properties": {"capacity": {"type": "integer"}},
        "required": ["capacity"],
    },
)
def set_default_capacity(ctx: ToolContext, capacity: int) -> StagedChangePayload:
    """Stage the default learner limit for newly registering volunteers.

    Args:
        ctx (ToolContext): Tool call context.
        capacity (int): New default capacity (1-5).

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    change = staging.stage(ctx, "set_default_capacity", {"capacity": int(capacity)})
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="match_pair",
    description=(
        "Propose matching one learner with one volunteer. The learner's current "
        "volunteer, if any, is released." + _STAGED
    ),
    label="Proposing a match for learner {learner_id}",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "learner_id": {"type": "integer"},
            "volunteer_id": {"type": "integer"},
        },
        "required": ["learner_id", "volunteer_id"],
    },
)
def match_pair(ctx: ToolContext, learner_id: int, volunteer_id: int) -> StagedChangePayload:
    """Stage matching one learner with one volunteer.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to match.
        volunteer_id (int): Volunteer to match them to.

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    change = staging.stage(ctx, "match_pair", {
        "learner_id": int(learner_id), "volunteer_id": int(volunteer_id),
    })
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="unmatch_pair",
    description="Propose dissolving one learner's current match." + _STAGED,
    label="Proposing an unmatch for learner {learner_id}",
    writes=True,
    parameters={
        "type": "object",
        "properties": {"learner_id": {"type": "integer"}},
        "required": ["learner_id"],
    },
)
def unmatch_pair(ctx: ToolContext, learner_id: int) -> StagedChangePayload:
    """Stage dissolving one learner's current match.

    Args:
        ctx (ToolContext): Tool call context.
        learner_id (int): Learner to unmatch.

    Returns:
        StagedChangePayload: `{"staged_change_id", "summary"}`.
    """
    change = staging.stage(ctx, "unmatch_pair", {"learner_id": int(learner_id)})
    return {"staged_change_id": change.id, "summary": change.summary}


@ai_tool(
    name="stage_auto_match",
    description=(
        "Run the automatic matcher and propose every pair it produces, one "
        "reviewable change each, so the teacher can accept some and skip "
        "others. Use preview_auto_match first if they only want to see the "
        "scores." + _STAGED
    ),
    label="Proposing automatic matches",
    writes=True,
    parameters={
        "type": "object",
        "properties": {
            "min_score": {
                "type": "integer",
                "description": "Skip proposals scoring below this. Omit for all.",
            }
        },
    },
)
def stage_auto_match(ctx: ToolContext, min_score: int | None = None) -> AutoMatchStageResult:
    """Run the automatic matcher and stage every proposed pair.

    Args:
        ctx (ToolContext): Tool call context.
        min_score (int | None): Skip proposals scoring below this; omit for all.

    Returns:
        AutoMatchStageResult: `{"staged", "skipped", "unmatched"}`.
    """
    preview = preview_auto_match(ctx)
    try:
        floor = int(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        floor = None

    staged: list[StagedProposal] = []
    skipped: list[AutoMatchProposal | SkippedProposal] = []
    for proposal in preview["proposals"]:
        if floor is not None and proposal["score"] < floor:
            skipped.append(proposal)
            continue
        try:
            change = staging.stage(
                ctx, "match_pair",
                {"learner_id": proposal["learner_id"],
                 "volunteer_id": proposal["volunteer_id"]},
                summary_prefix=f"[score {proposal['score']}] ",
            )
        except (ValueError, LookupError, PermissionError) as exc:
            # One volunteer filling up mid-run must not abort the whole batch.
            skipped.append({**proposal, "reason": str(exc)})
            continue
        staged.append({"staged_change_id": change.id, **proposal})

    return {
        "staged": staged,
        "skipped": skipped,
        "unmatched": preview.get("unmatched", []),
    }
