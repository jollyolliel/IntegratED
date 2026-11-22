from __future__ import annotations

from typing import TypedDict

from flask import Response, jsonify, request
from flask_login import login_required

from extensions import db
from helpers import teacher_ops
from helpers.ai.tools.domain import learner_name, volunteer_name
from helpers.analytics import capture_event
from helpers.current_user import current_teacher as current_user
from helpers.matching import ScoreMatrix, Scorer, match_band
from models import Learner, Teacher, Volunteer
from routes.api import api_bp


class MatchPlan(TypedDict):
    """One matching run, computed but not applied."""

    learners: list[Learner]
    volunteers: list[Volunteer]
    # learner id -> volunteer id they end up with, `None` meaning nobody. Only
    # learners whose pairing the run changes.
    moves: dict[int, int | None]
    current: dict[int, int]
    # Every pair's score, as the run that produced `moves` computed them.
    scores: ScoreMatrix


class MatchScore(TypedDict):
    score: int
    band: str


class PreviewMove(TypedDict):
    """One proposed change. The volunteer the run picked is `to_volunteer_id`
    and nothing more: their name comes from the `volunteers` list and the
    pair's quality from `options`, both of which the page already reads when
    the teacher swaps the proposal for somebody else. A second copy on the row
    would be a copy that goes stale on the first swap."""

    learner_id: int
    learner_name: str
    from_volunteer_id: int | None
    from_volunteer_name: str | None
    to_volunteer_id: int | None
    # volunteer id (as a JSON string key) -> this learner's score with them,
    # so a teacher swapping the proposed volunteer sees the new pair's quality.
    options: dict[str, MatchScore]


class PreviewVolunteer(TypedDict):
    id: int
    name: str | None
    capacity: int
    load: int


def _teacher_or_error() -> tuple[Teacher, None] | tuple[None, tuple[Response, int]]:
    """The signed-in teacher, or the JSON error response to return instead.

    Returns:
        tuple[Teacher, None] | tuple[None, tuple[Response, int]]: Exactly one
            of the two is set.
    """
    if current_user.user_type != "teacher":
        return None, (jsonify({"error": "Unauthorized"}), 403)
    if not current_user.school_id:
        return None, (jsonify({"error": "Teacher not assigned to a school"}), 400)
    return current_user, None


def _plan(teacher: Teacher) -> MatchPlan | None:
    """Runs the matcher over the teacher's whole own roster without touching it.

    The pool is every learner and every volunteer the teacher owns, matched or
    not, because the matcher spreads learners across volunteers and can only
    do that if it may move a pairing as well as create one. A roster with no
    unmatched learners left would otherwise be frozen in whatever shape the
    first run — or the seeder — happened to leave it. Pairings the run would
    have made anyway are left alone (`KEEP_BONUS` settles ties in the
    incumbent's favour), so running it twice proposes nothing the second time.

    Args:
        teacher (Teacher): The owning teacher; their saved match settings pick
            factor importance and spread strength.

    Returns:
        MatchPlan | None: The plan, or None when the roster has no learners or
            no volunteers.
    """
    # The teacher's own roster, not the whole school — `teacher_ops.match_pair`
    # refuses a row owned by a colleague, and a rejected pair has already spent
    # its volunteer's slot inside the matcher, so a wider pool burns slots and
    # leaves own learners unmatched.
    learners = list(db.session.scalars(db.select(Learner).filter_by(teacher_id=teacher.id)).all())
    volunteers = list(db.session.scalars(db.select(Volunteer).filter_by(teacher_id=teacher.id)).all())
    if not learners or not volunteers:
        return None

    # Full capacity, not open slots: everyone is being placed from scratch, so
    # the learners a volunteer already holds are part of what's being decided
    # rather than a head start on their tier.
    capacities = {v.id: v.capacity for v in volunteers}
    current = {l.id: l.volunteer_id for l in learners if l.volunteer_id}

    matches, scores = Scorer.for_teacher(teacher.match_settings).match_all(
        learners, volunteers, capacities=capacities, keep=current,
    )
    # `None` — "ends up with nobody" — is only reachable when the roster has
    # more learners than slots.
    moves = {
        learner.id: (volunteer.id if volunteer else None)
        for learner, volunteer in matches
        if (volunteer.id if volunteer else None) != current.get(learner.id)
    }
    return {
        "learners": learners, "volunteers": volunteers, "moves": moves,
        "current": current, "scores": scores,
    }


def _parse_moves(raw: object) -> dict[int, int | None] | None:
    """Approved moves sent back from a preview, or None if malformed.

    Args:
        raw (object): The request's `moves` value — a list of
            `{"learner_id": int, "volunteer_id": int | None}`.

    Returns:
        dict[int, int | None] | None: learner id -> volunteer id.
    """
    if not isinstance(raw, list):
        return None
    moves: dict[int, int | None] = {}
    for item in raw:
        if not isinstance(item, dict):
            return None
        learner_id, volunteer_id = item.get("learner_id"), item.get("volunteer_id")
        if not isinstance(learner_id, int) or isinstance(learner_id, bool):
            return None
        if volunteer_id is not None and (not isinstance(volunteer_id, int) or isinstance(volunteer_id, bool)):
            return None
        moves[learner_id] = volunteer_id
    return moves


@api_bp.route("/matching/preview", methods=["POST"])
@login_required
def api_preview_matching():
    """What Auto-Match would change on the teacher's roster. Writes nothing.

    The teacher reviews this list and approves it by posting its moves back to
    `api_run_matching`, so what lands is exactly what was shown — a second
    matcher run could differ if the roster changed in between.

    The teacher may skip a move or swap its volunteer before approving, so
    every own volunteer comes back with capacity and current load — enough
    for the page to refuse an edit set that overfills someone.

    Returns:
        JSON `{"status", "moves": [PreviewMove], "volunteers":
        [PreviewVolunteer], "unchanged_count"}` — `status` is `"no_op"` (with
        `message`) when there is nobody to match.
    """
    teacher, error = _teacher_or_error()
    if teacher is None:
        return error

    plan = _plan(teacher)
    if plan is None:
        return jsonify({
            "status": "no_op", "moves": [], "volunteers": [], "unchanged_count": 0,
            "message": "Your roster has no learners or no volunteers to match them with yet.",
        })

    learners_by_id = {l.id: l for l in plan["learners"]}
    volunteers_by_id = {v.id: v for v in plan["volunteers"]}
    rows: list[PreviewMove] = []
    for learner_id, volunteer_id in plan["moves"].items():
        learner = learners_by_id[learner_id]
        before = volunteers_by_id.get(plan["current"].get(learner_id, -1))
        # Read straight out of the board the matcher optimised, so the band
        # here is the band the connector shows once the pair is applied — and
        # so nothing is scored twice.
        options: dict[str, MatchScore] = {}
        for v in plan["volunteers"]:
            score = plan["scores"].of(learner.id, v.id)
            options[str(v.id)] = {"score": score, "band": match_band(score)}
        rows.append({
            "learner_id": learner.id,
            "learner_name": learner_name(learner),
            "from_volunteer_id": before.id if before else None,
            "from_volunteer_name": volunteer_name(before),
            "to_volunteer_id": volunteer_id,
            "options": options,
        })
    rows.sort(key=lambda row: row["learner_name"].lower())

    loads: dict[int, int] = {}
    for vid in plan["current"].values():
        loads[vid] = loads.get(vid, 0) + 1
    volunteer_rows: list[PreviewVolunteer] = sorted(
        (
            {"id": v.id, "name": volunteer_name(v), "capacity": v.capacity, "load": loads.get(v.id, 0)}
            for v in plan["volunteers"]
        ),
        key=lambda row: (row["name"] or "").lower(),
    )

    capture_event(
        str(teacher.id), "matching_preview_viewed",
        properties={"teacher_id": teacher.id, "proposed_count": len(rows)},
    )
    return jsonify({
        "status": "success",
        "moves": rows,
        "volunteers": volunteer_rows,
        "unchanged_count": len(plan["learners"]) - len(rows),
    })


@api_bp.route("/run-matching", methods=["POST"])
@login_required
def api_run_matching():
    """Applies a matching run to the teacher's own roster.

    With a JSON `moves` list (from `api_preview_matching`) it applies exactly
    those moves — what the teacher approved. Without one it runs the matcher
    itself and applies the result straight away.

    Applied in two passes: every learner who is moving is unmatched first,
    then re-matched. One pass would hit a volunteer who is still nominally
    full of learners this run is about to take off them.
    """
    teacher, error = _teacher_or_error()
    if teacher is None:
        return error

    payload = request.get_json(silent=True)
    raw_moves = payload.get("moves") if isinstance(payload, dict) else None
    from_preview = raw_moves is not None

    capture_event(
        str(teacher.id), "matching_run_started",
        properties={"teacher_id": teacher.id, "school_id": teacher.school_id, "from_preview": from_preview},
    )

    if from_preview:
        moves = _parse_moves(raw_moves)
        if moves is None:
            return jsonify({"error": "Invalid moves"}), 400
        # Own roster only. `teacher_ops.match_pair` / `unmatch_pair` refuse a
        # colleague's row anyway, so this read only feeds change-detection —
        # but a pool wider than the one the writes accept is a boundary stated
        # in one place and inferred in the other.
        current = {
            l.id: l.volunteer_id
            for l in db.session.scalars(
                db.select(Learner).where(Learner.id.in_(moves), Learner.teacher_id == teacher.id)
            ).all()
            if l.volunteer_id
        }
        # A move the roster already reflects is not a change to apply.
        moves = {lid: vid for lid, vid in moves.items() if vid != current.get(lid)}
    else:
        plan = _plan(teacher)
        if plan is None:
            return jsonify({"status": "no_op", "message": "Your roster has no learners or no volunteers to match them with yet."})
        moves, current = plan["moves"], plan["current"]

    # One transaction: a pair that can't land (someone filled up or left this teacher since the
    # snapshot) is skipped and counted, and its learner keeps the volunteer they had.
    result = teacher_ops.apply_moves(teacher, moves, current)
    applied_count, skipped_count, released = result["applied"], result["skipped"], result["released"]

    capture_event(
        str(teacher.id),
        "matching_run_completed",
        properties={
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "released_count": released,
            "teacher_id": teacher.id,
            "from_preview": from_preview,
        },
    )
    return jsonify({
        "status": "success",
        "matches_applied": applied_count,
        "matches_skipped": skipped_count,
        "matches_released": released,
    })
