from typing import Any, TypedDict

from extensions import db
from helpers.matching import (
    DEFAULT_SPREAD_LEVEL,
    DEFAULT_WEIGHT_LEVEL,
    FACTORS,
    SPREAD_PENALTIES,
    WEIGHT_MULTIPLIERS,
    MatchLevels,
)
from helpers.teacher_ops._shared import MAX_VOLUNTEER_CAPACITY, _owned
from models import Learner, Teacher, Volunteer


def validate_set_volunteer_capacity(teacher: Teacher, volunteer_id: int, capacity: Any) -> dict[str, Any]:
    """Check a proposed learner-capacity change for one volunteer.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        volunteer_id (int): Volunteer to change.
        capacity (Any): Proposed new capacity.

    Returns:
        dict[str, Any]: `{"volunteer", "capacity", "learner_count"}`.
    """
    volunteer = _owned(Volunteer, volunteer_id, teacher, "volunteer")
    try:
        value = int(capacity)
    except (TypeError, ValueError):
        value = None
    if value is None or value < 1 or value > MAX_VOLUNTEER_CAPACITY:
        raise ValueError(
            f"Learner limit must be between 1 and {MAX_VOLUNTEER_CAPACITY}."
        )

    # Refuse rather than auto-unmatching — which learner to drop is the
    # teacher's decision, not a side effect of typing a smaller number.
    learner_count = len(volunteer.learner_matches)
    if value < learner_count:
        raise ValueError(
            f"{volunteer.name or volunteer.email} already has {learner_count} learners — "
            "unmatch someone before lowering the limit."
        )
    return {"volunteer": volunteer, "capacity": value, "learner_count": learner_count}


def set_volunteer_capacity(teacher: Teacher, volunteer_id: int, capacity: Any) -> dict[str, Any]:
    """Set one volunteer's learner capacity and commit.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        volunteer_id (int): Volunteer to change.
        capacity (Any): New capacity.

    Returns:
        dict[str, Any]: `{"volunteer", "capacity", "learner_count"}`.
    """
    resolved = validate_set_volunteer_capacity(teacher, volunteer_id, capacity)
    resolved["volunteer"].match_capacity = resolved["capacity"]
    db.session.commit()
    return resolved


def validate_set_default_capacity(teacher: Teacher, capacity: Any) -> dict[str, Any]:
    """Check a proposed default match-capacity change for a teacher.

    Args:
        teacher (Teacher): Teacher whose default is changing.
        capacity (Any): Proposed new default capacity.

    Returns:
        dict[str, Any]: `{"teacher", "capacity"}`.
    """
    try:
        value = int(capacity)
    except (TypeError, ValueError):
        value = None
    if value is None or value < 1 or value > MAX_VOLUNTEER_CAPACITY:
        raise ValueError(
            f"Default learner limit must be between 1 and {MAX_VOLUNTEER_CAPACITY}."
        )
    return {"teacher": teacher, "capacity": value}


# Deliberately does not touch the current roster — a hand-set limit outlives
# a change of default.
def set_default_capacity(teacher: Teacher, capacity: Any) -> dict[str, Any]:
    """The limit newly registering volunteers start on.

    Args:
        teacher (Teacher): Teacher whose default is changing.
        capacity (Any): New default capacity.

    Returns:
        dict[str, Any]: `{"teacher", "capacity"}`.
    """
    resolved = validate_set_default_capacity(teacher, capacity)
    teacher.default_match_capacity = resolved["capacity"]
    db.session.commit()
    return resolved


def _checked_level(value: Any, top: int, label: str) -> int:
    """Coerce one submitted level, refusing anything out of range.

    Args:
        value (Any): Submitted level.
        top (int): Highest level that exists.
        label (str): What the level controls, for the error message.

    Returns:
        int: The level, between 0 and `top`.
    """
    try:
        level = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Each {label} must be a whole number from 0 to {top}.") from None
    if not 0 <= level <= top:
        raise ValueError(f"Each {label} must be from 0 to {top}.")
    return level


def validate_set_match_settings(teacher: Teacher, weights: Any, spread: Any) -> dict[str, Any]:
    """Check a proposed change to how this teacher's matches are weighted.

    Args:
        teacher (Teacher): Teacher whose settings are changing.
        weights (Any): Factor name -> importance level; absent factors keep the default.
        spread (Any): Spread level, or None for the default.

    Returns:
        dict[str, Any]: `{"teacher", "levels"}`.
    """
    # Strict where `matching.normalize_levels` is lenient: that one reads a
    # column nobody can fix by hand, this one reads a submitted form, where an
    # unknown factor means the form and FACTORS have drifted apart.
    if not isinstance(weights, dict):
        # ValueError, not TypeError: this package's contract maps ValueError to
        # a 400 with str(e) shown to the user, and a TypeError would escape as
        # a 500 (see the package docstring).
        raise ValueError("Matching priorities must arrive as a set of factor levels.")  # noqa: TRY004
    unknown = set(weights) - set(FACTORS)
    if unknown:
        raise ValueError(f"Unknown matching factor(s): {', '.join(sorted(unknown))}.")

    levels: MatchLevels = {
        "weights": {
            factor: _checked_level(
                weights.get(factor, DEFAULT_WEIGHT_LEVEL),
                len(WEIGHT_MULTIPLIERS) - 1,
                "importance level",
            )
            for factor in FACTORS
        },
        "spread": _checked_level(
            DEFAULT_SPREAD_LEVEL if spread is None else spread,
            len(SPREAD_PENALTIES) - 1,
            "spread level",
        ),
    }
    return {"teacher": teacher, "levels": levels}


def set_match_settings(teacher: Teacher, weights: Any, spread: Any) -> dict[str, Any]:
    """Set how this teacher's matches are weighted and commit.

    Args:
        teacher (Teacher): Teacher whose settings are changing.
        weights (Any): Factor name -> importance level; absent factors keep the default.
        spread (Any): Spread level, or None for the default.

    Returns:
        dict[str, Any]: `{"teacher", "levels"}`.
    """
    # Deliberately does not re-run matching — this changes what the next run
    # optimises and what every displayed score means, never a standing pair.
    resolved = validate_set_match_settings(teacher, weights, spread)
    teacher.match_settings = dict(resolved["levels"])
    db.session.commit()
    return resolved


def validate_match_pair(teacher: Teacher, learner_id: int, volunteer_id: int) -> dict[str, Any]:
    """Check that a learner can be matched to a volunteer.

    Args:
        teacher (Teacher): Owning teacher, for the ownership checks.
        learner_id (int): Learner to match.
        volunteer_id (int): Volunteer to match them to.

    Returns:
        dict[str, Any]: `{"learner", "volunteer", "already"}`.
    """
    learner = _owned(Learner, learner_id, teacher, "learner")
    volunteer = _owned(Volunteer, volunteer_id, teacher, "volunteer")

    already = learner.volunteer_id == volunteer.id
    if not already and volunteer.is_full:
        raise ValueError(
            f"{volunteer.name or volunteer.email} is already matched with "
            f"{len(volunteer.learner_matches)} learner(s) — raise their learner limit first."
        )
    return {"learner": learner, "volunteer": volunteer, "already": already}


def match_pair(teacher: Teacher, learner_id: int, volunteer_id: int) -> dict[str, Any]:
    """Match a learner to a volunteer and commit.

    Args:
        teacher (Teacher): Owning teacher, for the ownership checks.
        learner_id (int): Learner to match.
        volunteer_id (int): Volunteer to match them to.

    Returns:
        dict[str, Any]: `{"learner", "volunteer", "already"}`.
    """
    resolved = validate_match_pair(teacher, learner_id, volunteer_id)
    if not resolved["already"]:
        _pair(resolved["learner"], resolved["volunteer"])
        db.session.commit()
    return resolved


def _pair(learner: Learner, volunteer: Volunteer) -> None:
    """Point `learner` at `volunteer`, uncommitted. The caller has validated the pair."""
    # A learner still has exactly one volunteer — free the previous one first,
    # so their is_matched flag is re-derived from who is actually left.
    if learner.volunteer_match:
        learner.unmatch()
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True


class AppliedMoves(TypedDict):
    """What `apply_moves` did."""

    applied: int
    skipped: int
    released: int   # learners moved off the volunteer they had (a skipped move that put one back doesn't count)


def apply_moves(teacher: Teacher, moves: dict[int, int | None], current: dict[int, int]) -> AppliedMoves:
    """Apply a matching plan in one transaction: every move lands or is skipped, then one commit.

    Every learner moving away from a volunteer is released first, so a swap can land; then each
    learner is paired with their new volunteer. A pair that can't land (a volunteer filled up or
    left this teacher since the preview) is skipped, and a learner it would have stranded goes
    back to the volunteer they were released from. An unexpected error rolls everything back.

    Args:
        teacher (Teacher): Owning teacher, for the ownership checks.
        moves (dict[int, int | None]): Learner id -> new volunteer id, or None to leave unmatched.
        current (dict[int, int]): Learner id -> volunteer id they hold now.

    Returns:
        AppliedMoves: Pairs made, pairs skipped, and learners moved off the volunteer they had.
    """
    applied = skipped = 0
    released: dict[int, int] = {}
    try:
        for learner_id in moves:
            if current.get(learner_id) is None:
                continue
            try:
                resolved = validate_unmatch_pair(teacher, learner_id)
            except (ValueError, LookupError, PermissionError):
                continue
            resolved["learner"].unmatch()
            released[learner_id] = current[learner_id]
        db.session.flush()

        for learner_id, volunteer_id in moves.items():
            if volunteer_id is None:
                continue
            try:
                resolved = validate_match_pair(teacher, learner_id, volunteer_id)
            except (ValueError, LookupError, PermissionError):
                skipped += 1
                previous = released.get(learner_id)
                if previous is not None:
                    try:
                        back = validate_match_pair(teacher, learner_id, previous)
                    except (ValueError, LookupError, PermissionError):
                        continue
                    _pair(back["learner"], back["volunteer"])
                    del released[learner_id]
                continue
            if not resolved["already"]:
                _pair(resolved["learner"], resolved["volunteer"])
            applied += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return AppliedMoves(applied=applied, skipped=skipped, released=len(released))


def assign_unassigned(teacher: Teacher, dry_run: bool = False, all_schools: bool = False) -> dict[str, Any]:
    """Claim every learner/volunteer with no teacher, scoped to `teacher`'s own school unless `all_schools`.

    Args:
        teacher (Teacher): Teacher claiming the unassigned rows.
        dry_run (bool): If True, don't write — just return what would be claimed.
        all_schools (bool): If True, ignore the school boundary and fix mismatched `school_id`.

    Returns:
        dict[str, Any]: `{"learners", "volunteers"}` — the claimed (or would-be-claimed) rows.
    """
    # all_schools also corrects a mismatched school_id to teacher's own — only
    # meaningful when teacher is genuinely the only one in the app, which is
    # what `flask fix-teacher-assignments` uses it for.
    if all_schools:
        learners = db.session.scalars(db.select(Learner).filter_by(teacher_id=None)).all()
        volunteers = db.session.scalars(db.select(Volunteer).filter_by(teacher_id=None)).all()
    elif teacher.school_id:
        learners = db.session.scalars(
            db.select(Learner).filter_by(school_id=teacher.school_id, teacher_id=None)
        ).all()
        volunteers = db.session.scalars(
            db.select(Volunteer).filter_by(school_id=teacher.school_id, teacher_id=None)
        ).all()
    else:
        learners, volunteers = [], []

    if not dry_run:
        for l in learners:
            l.teacher_id = teacher.id
            if all_schools and teacher.school_id and l.school_id != teacher.school_id:
                l.school_id = teacher.school_id
        for v in volunteers:
            v.teacher_id = teacher.id
            if all_schools and teacher.school_id and v.school_id != teacher.school_id:
                v.school_id = teacher.school_id
        if learners or volunteers:
            db.session.commit()

    return {"learners": learners, "volunteers": volunteers}


def validate_unmatch_pair(teacher: Teacher, learner_id: int) -> dict[str, Any]:
    """Check that a learner is currently matched, so they can be unmatched.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        learner_id (int): Learner to unmatch.

    Returns:
        dict[str, Any]: `{"learner", "volunteer"}`.
    """
    learner = _owned(Learner, learner_id, teacher, "learner")
    if not learner.is_matched or not learner.volunteer_match:
        raise ValueError(
            f"{learner.name or learner.username} is not matched with anyone."
        )
    return {"learner": learner, "volunteer": learner.volunteer_match}


def unmatch_pair(teacher: Teacher, learner_id: int) -> dict[str, Any]:
    """Unmatch a learner from their volunteer and commit.

    Args:
        teacher (Teacher): Owning teacher, for the ownership check.
        learner_id (int): Learner to unmatch.

    Returns:
        dict[str, Any]: `{"learner", "volunteer"}` — the pair that was unmatched.
    """
    resolved = validate_unmatch_pair(teacher, learner_id)
    # Learner.unmatch() re-syncs is_matched on both sides — clearing the FK by
    # hand leaves a volunteer flagged matched with nobody.
    resolved["learner"].unmatch()
    db.session.commit()
    return resolved
