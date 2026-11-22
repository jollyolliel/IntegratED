"""The per-lesson answer log: the one owner of a learner's in-progress answers to a lesson.

Every lesson type — the quiz and each game — grades into one `LearningSession` row with
`session_type="answer_log"` per learner and lesson (a unique constraint holds it to one). A
lesson's finished result is a different row, typed by the lesson (`helpers.learning._games`). Each entry is
one try at one **unit**: a question (`q:<id>`), or for Match Up one pair (`pair:<question id>:<left>`).
A unit answered right is never logged again, so its first try is the one that scores, and the
wrong tries before it are what the quiz's hint counts. Completion reads the log and then clears it,
so a replay starts clean.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from extensions import db
from helpers.utils import utcnow_naive
from models import LearningSession

__all__ = [
    "LOG_TYPE",
    "clear",
    "correct_units",
    "find",
    "first_try_correct",
    "log_answer",
    "pair_unit",
    "question_unit",
    "wrong_tries",
]

#: The `session_type` of an answer log row.
LOG_TYPE = "answer_log"


def question_unit(question_id: int) -> str:
    """The unit a question is graded as."""
    return f"q:{question_id}"


def pair_unit(question_id: int, left: str) -> str:
    """The unit one Match Up pair is graded as: its question and its left side."""
    return f"pair:{question_id}:{left}"


def find(learner_id: int, lesson_id: int) -> LearningSession | None:
    """The learner's answer log for a lesson, if they have answered anything since it was last cleared."""
    return db.session.scalar(
        db.select(LearningSession).filter_by(learner_id=learner_id, session_type=LOG_TYPE, lesson_id=lesson_id)
    )


def _entries(log: LearningSession | None) -> list[dict[str, Any]]:
    return [entry for entry in (log.responses if log else None) or [] if isinstance(entry, dict) and "unit" in entry]


def correct_units(log: LearningSession | None) -> set[str]:
    """Units answered right at some try."""
    return {entry["unit"] for entry in _entries(log) if entry.get("is_correct")}


def first_try_correct(log: LearningSession | None, units: set[str]) -> int:
    """How many of `units` were right at their first try."""
    first: dict[str, bool] = {}
    for entry in _entries(log):
        first.setdefault(entry["unit"], bool(entry.get("is_correct")))
    return sum(1 for unit, right in first.items() if right and unit in units)


def wrong_tries(log: LearningSession | None, unit: str) -> int:
    """Wrong tries logged for one unit."""
    return sum(1 for entry in _entries(log) if entry["unit"] == unit and not entry.get("is_correct"))


def _find_or_create(learner_id: int, lesson_id: int) -> LearningSession:
    log = find(learner_id, lesson_id)
    if log is not None:
        return log
    log = LearningSession(learner_id=learner_id, session_type=LOG_TYPE, lesson_id=lesson_id, responses=[])
    try:
        with db.session.begin_nested():
            db.session.add(log)
    except IntegrityError:
        # Two first answers raced to create the log and the unique constraint let the other one
        # in; only this insert's savepoint is undone, so the other request's row is the log.
        raced = find(learner_id, lesson_id)
        if raced is None:
            raise
        return raced
    return log


def log_answer(learner_id: int, lesson_id: int, unit: str, question_id: int, is_correct: bool) -> LearningSession:
    """Record one try at `unit` (nothing once it has been answered right) and commit.

    Args:
        learner_id (int): The learner answering.
        lesson_id (int): The lesson the unit belongs to.
        unit (str): `question_unit(...)` or `pair_unit(...)`.
        question_id (int): The question the unit is part of (the quiz resumes by it).
        is_correct (bool): Whether this try was right.

    Returns:
        LearningSession: The log, committed.
    """
    log = _find_or_create(learner_id, lesson_id)
    if unit not in correct_units(log):
        log.responses = [*(log.responses or []), {
            "unit": unit, "question_id": question_id, "is_correct": is_correct,
            "timestamp": utcnow_naive().isoformat(),
        }]
        flag_modified(log, "responses")
    db.session.commit()
    return log


def clear(learner_id: int, lesson_id: int) -> None:
    """Drop the lesson's log, uncommitted, so a replay starts clean."""
    db.session.execute(db.delete(LearningSession).where(
        LearningSession.learner_id == learner_id,
        LearningSession.session_type == LOG_TYPE,
        LearningSession.lesson_id == lesson_id,
    ))
