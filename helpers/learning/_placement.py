import random
from typing import TypedDict

from extensions import db
from models import LearningSession, MapQuestion, Subject

# Consecutive corrects required to climb a level in the placement staircase
# (see apply_map_answer) — noise-robustness against a lucky guess. Degrades
# gracefully when a level has fewer than CONFIRM questions.
CONFIRM = 2
# Consecutive misses at level 1 before the floor counts as found: one slip on
# the very first easy question must not be the whole result.
FLOOR_MISSES = 2


class ScaleState(TypedDict):
    """One placement scale's staircase, stored as JSON in `LearningSession.subject_state[scale]`."""

    level: int              # the level the next question is asked at
    consec_correct: int     # right answers in a row at the current level
    floor_misses: int       # wrong answers in a row at level 1
    passed: list[int]       # levels answered right (sorted)
    failed: list[int]       # levels answered wrong (sorted)
    answered: int
    min_answers: int        # answers this scale must collect before it may settle
    settled: bool
    settled_level: int | None


def new_scale_state(start_level: int, min_answers: int) -> ScaleState:
    """A fresh staircase for one placement scale.

    Args:
        start_level (int): Level of the first question.
        min_answers (int): Answers this scale must collect before it may settle.

    Returns:
        ScaleState: The JSON-safe state `apply_map_answer` advances.
    """
    return ScaleState(
        level=start_level, consec_correct=0, floor_misses=0, passed=[], failed=[], answered=0,
        min_answers=min_answers, settled=False, settled_level=None,
    )


def placement_estimate(state: ScaleState) -> int:
    """The scale's best current level: its settled level, else the highest pass
    not contradicted by a known failure at or below it, else the floor.

    Args:
        state (ScaleState): A scale's staircase state.

    Returns:
        int: A level, 1 or more.
    """
    if state["settled_level"]:
        return state["settled_level"]
    best = max(state["passed"], default=1)
    lowest_fail = min(state["failed"], default=None)
    if lowest_fail is not None and best >= lowest_fail:
        best = lowest_fail - 1
    return max(best, 1)


def get_subject_id(name: str) -> int | None:
    """Look up a Subject's id by name.

    Args:
        name (str): Subject name.

    Returns:
        int | None: The subject's id, or None if no such subject exists.
    """
    subj = db.session.scalar(db.select(Subject).filter_by(name=name))
    return subj.id if subj else None


def subject_max_level(subject_id: int) -> int:
    """Highest placement-question level defined for a subject.

    Args:
        subject_id (int): Subject id.

    Returns:
        int: Max `MapQuestion.level` for the subject, or 1 if none exist.
    """
    return db.session.scalar(
        db.select(db.func.max(MapQuestion.level)).where(
            MapQuestion.subject_id == subject_id
        )
    ) or 1


def _unasked_placement_question_at(subject_id: int, level: int, asked_ids: list[int]) -> MapQuestion | None:
    """A random unasked placement question for a subject at an exact level.

    Args:
        subject_id (int): Subject id to pick a question for.
        level (int): Exact placement level to query.
        asked_ids (list[int]): MapQuestion ids already asked this session.

    Returns:
        MapQuestion | None: A candidate question, or None if none remain.
    """
    candidates = db.session.scalars(
        db.select(MapQuestion).where(
            MapQuestion.subject_id == subject_id,
            MapQuestion.level == level,
            ~MapQuestion.id.in_(asked_ids),
        )
    ).all()
    return random.choice(candidates) if candidates else None


def _settle_subject(state: ScaleState, level: int) -> None:
    """Pin a subject's level — it won't be probed again this session.

    Args:
        state (ScaleState): The subject's staircase state (mutated in place).
        level (int): Level to settle at.

    Returns:
        None
    """
    state["settled"] = True
    state["settled_level"] = level
    state["level"] = level


def _conclude(state: ScaleState, estimate: int, probe_level: int) -> None:
    """The staircase has a result: settle on it once the scale has its minimum
    answers, otherwise keep asking, at ``probe_level``.

    Args:
        state (ScaleState): The scale's staircase state (mutated in place).
        estimate (int): The level the evidence points at.
        probe_level (int): Where to ask next if it may not settle yet.

    Returns:
        None
    """
    if state["answered"] >= state["min_answers"]:
        _settle_subject(state, estimate)
        return
    if probe_level != state["level"]:
        state["consec_correct"] = 0
    state["level"] = probe_level


# One staircase per placement scale. Evidence is two lists: `passed` (levels
# answered right) and `failed` (levels answered wrong). Newer evidence
# overrules older: a wrong answer at L drops every pass at L and above; a
# *confirmed* pass at L (CONFIRM corrects in a row) drops every failure at L
# and below. A single correct never overrules a failure — multiple choice
# rewards guessing.
#
# Correct at L: after CONFIRM in a row, climb to L+1 (at the ceiling, the
#   result is the ceiling). If L+1 is a known failure the level is bracketed
#   from above and the result is L at once.
# Wrong at L: step down to L-1. If L-1 is a known pass it is bracketed from
#   below and the result is L-1. At the floor, stay at level 1; the result is
#   the floor only after FLOOR_MISSES misses in a row.
#
# A result settles the scale -- it is not probed again -- only once the scale
# has `min_answers` answers. Before that the staircase keeps probing around
# the result: a bracket from above re-tests the failed level L+1, a bracket
# from below steps to L-1, floor and ceiling ask again at the same level. So
# answers keep moving the estimate both ways until the minimum is met, and
# one wrong answer never ends the test.
def apply_map_answer(state: ScaleState, level: int, is_correct: bool, max_level: int) -> None:
    """Advance one placement scale's staircase given an answer at ``level``.

    Args:
        state (ScaleState): The scale's staircase state (mutated in place).
        level (int): Level the just-answered question was at.
        is_correct (bool): Whether the answer was correct.
        max_level (int): Ceiling level for this scale.

    Returns:
        None
    """
    state["answered"] += 1
    passed, failed = set(state["passed"]), set(state["failed"])

    if is_correct:
        state["consec_correct"] += 1
        state["floor_misses"] = 0
        confirmed = state["consec_correct"] >= CONFIRM
        passed.add(level)
        if confirmed:
            failed = {f for f in failed if f > level}
        state["passed"], state["failed"] = sorted(passed), sorted(failed)

        if min(failed, default=None) == level + 1:
            _conclude(state, level, probe_level=level + 1)       # bracketed from above
        elif confirmed and level >= max_level:
            _conclude(state, max_level, probe_level=max_level)   # aced the ceiling
        elif confirmed:
            state["level"] = min(level + 1, max_level)           # confirmed -> climb
            state["consec_correct"] = 0
        else:
            state["level"] = level                               # ask again to confirm
        return

    state["consec_correct"] = 0
    failed.add(level)
    passed = {p for p in passed if p < level}
    state["passed"], state["failed"] = sorted(passed), sorted(failed)

    if level <= 1:
        state["floor_misses"] += 1
        if state["floor_misses"] >= FLOOR_MISSES:
            _conclude(state, 1, probe_level=1)                   # floor
        else:
            state["level"] = 1                                   # one slip: ask again
        return

    state["floor_misses"] = 0
    if max(passed, default=None) == level - 1:
        _conclude(state, level - 1, probe_level=level - 1)       # bracketed from below
    else:
        state["level"] = level - 1                               # step down


def next_placement_question_for_subject(map_session: LearningSession, subject_name: str, subject_id: int, max_level: int) -> MapQuestion | None:
    """Return an unasked question at or next to the scale's target level, or ``None`` once it settles instead (guaranteed even with thin content).

    When the target level has run dry the neighbouring level is tried — the
    one above first if the learner was just answering right, else the one
    below — and if both are dry the scale settles at its current estimate.
    Every call either returns a question or settles, so the caller can't loop.

    Args:
        map_session (LearningSession): The placement session (`subject_state`, `asked_ids`).
        subject_name (str): Scale whose staircase to advance.
        subject_id (int): The scale's subject id.
        max_level (int): Ceiling level for this scale.

    Returns:
        MapQuestion | None: The next question to ask, or None if the scale
            just settled instead.
    """
    state = map_session.subject_state[subject_name]
    target = state["level"]

    q = _unasked_placement_question_at(subject_id, target, map_session.asked_ids)
    if q:
        return q

    neighbours = [target + 1, target - 1] if state["consec_correct"] > 0 else [target - 1, target + 1]
    for level in neighbours:
        if 1 <= level <= max_level:
            q = _unasked_placement_question_at(subject_id, level, map_session.asked_ids)
            if q:
                return q

    _settle_subject(state, placement_estimate(state))
    return None
