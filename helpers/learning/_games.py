"""Every kind of lesson — the quiz and the five games — as one table, and the one completion path.

A lesson type says what it **deals** (the units a run is made of and scored over), how it
scores and what bonus it may add. The questions endpoint serves exactly what is dealt, the
answer log grades each unit, and `complete_lesson` scores the log against the deal under the
learner's lock, records the result and clears the log.

Every lesson keeps one result row, `LearningSession(session_type=result_type(lesson))`: the
game's name, or `"quiz"` for the quiz. It is what a repeated completion reports back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, NamedTuple

from extensions import db
from helpers.analytics import capture_event
from helpers.learning import _answer_log as answer_log
from helpers.learning._completion import (
    CompletionPayload,
    lock_learner,
    record_lesson_completion,
)
from models import Learner, LearningSession, Lesson, Question

__all__ = [
    "GAMES",
    "GARDEN_PLOTS",
    "IncompleteLesson",
    "Unit",
    "check_match_pair",
    "complete_lesson",
    "deal",
    "dealt_questions",
    "lesson_type",
    "result_type",
]

#: The result row's `session_type` for a quiz (a game's is its `game_type`).
QUIZ_RESULT_TYPE = "quiz"

# Garden Grow plot count — the garden page draws this many plots
# (routes/learner/_games.py passes it in). Bounds the grains a single
# water drop can harvest (a rainstorm reaps every super bloom at once) and
# shapes the persisted garden_state (routes/api/garden.py).
GARDEN_PLOTS = 8


class Unit(NamedTuple):
    """One graded piece of a run: a question, or one Match Up pair of a `match` question."""

    key: str
    question: Question
    left: str | None = None
    right: str | None = None


class _Bonus(NamedTuple):
    """Extra XP from a client-reported count: ``payload[key]`` × 10, clamped to ``cap(correct, total)``."""

    key: str
    cap: Callable[[int, int], int]
    #: A bonus earned with at least one right answer stores a golden-potion XP boost.
    grants_boost: bool = False


class _LessonType(NamedTuple):
    event_name: str
    #: What a run deals: every question, the questions with options, or every Match Up pair.
    serves: Literal["questions", "choices", "pairs"]
    #: XP for a first completion with `correct` units right at the first try.
    xp: Callable[[int], int]
    bonus: _Bonus | None = None
    #: The quiz only moves past a question once it is right, so a finished run has every unit right.
    requires_every_unit: bool = False


def _game_xp(correct: int) -> int:
    return correct * 10 + 50


#: Keyed by `Lesson.game_type`; the quiz is `None`.
GAMES: dict[str | None, _LessonType] = {
    None: _LessonType(event_name="lesson_completed", serves="questions", xp=lambda _correct: 50, requires_every_unit=True),
    "rocket": _LessonType(event_name="rocket_game_completed", serves="choices", xp=_game_xp),
    "word_storm": _LessonType(event_name="word_storm_completed", serves="choices", xp=_game_xp),
    "match_up": _LessonType(event_name="match_up_completed", serves="pairs", xp=_game_xp),
    # Each correct answer earns one water drop, and spending it on a rainstorm harvests every
    # super bloom at once — so one drop pays out up to GARDEN_PLOTS grains. (ADR 0005)
    "garden_grow": _LessonType(event_name="garden_grow_completed", serves="choices", xp=_game_xp,
        bonus=_Bonus("grains", lambda correct, _total: correct * GARDEN_PLOTS),
    ),
    # Recipes are chunks of >= 2 questions, so there are at most ceil(dealt / 2) golden potions.
    "potion_workshop": _LessonType(event_name="potion_workshop_completed", serves="choices", xp=_game_xp,
        bonus=_Bonus("golden_count", lambda _correct, total: (max(total, 1) + 1) // 2, grants_boost=True),
    ),
}


class IncompleteLesson(ValueError):
    """A quiz finished before every question was answered right; nothing was recorded."""

    def __init__(self, unanswered: int) -> None:
        self.unanswered = unanswered
        super().__init__(f"{unanswered} question(s) still need a right answer.")


def lesson_type(lesson: Lesson) -> _LessonType:
    """The lesson's entry in `GAMES`.

    Raises:
        ValueError: The lesson names a game this app doesn't have.
    """
    entry = GAMES.get(lesson.game_type)
    if entry is None:
        raise ValueError(f"Unknown game type {lesson.game_type!r}.")
    return entry


def _pairs(question: Question) -> list[tuple[str, str]]:
    return [
        (str(pair["left"]), str(pair["right"]))
        for pair in (question.match_pairs if isinstance(question.match_pairs, list) else [])
        if isinstance(pair, Mapping) and pair.get("left") and pair.get("right")
    ]


def deal(lesson: Lesson) -> list[Unit]:
    """The units a run of ``lesson`` is made of, in order — what is served and what is scored."""
    serves = lesson_type(lesson).serves
    questions = db.session.scalars(db.select(Question).filter_by(lesson_id=lesson.id).order_by(Question.id)).all()
    if serves == "pairs":
        return [
            Unit(answer_log.pair_unit(q.id, left), q, left, right)
            for q in questions if q.content_type == "match"
            for left, right in _pairs(q)
        ]
    if serves == "choices":
        questions = [q for q in questions if isinstance(q.options, list) and q.options]
    return [Unit(answer_log.question_unit(q.id), q) for q in questions]


def dealt_questions(units: list[Unit]) -> list[Question]:
    """The distinct questions behind `units`, in order: what the questions endpoint serves."""
    seen: dict[int, Question] = {}
    for unit in units:
        seen.setdefault(unit.question.id, unit.question)
    return list(seen.values())


def check_match_pair(learner: Learner, lesson: Lesson, left: str, right: str) -> bool:
    """Whether ``left`` goes with ``right`` in ``lesson``, logged as that pair's try."""
    units = deal(lesson)
    unit = next((u for u in units if u.left == left), None)
    if unit is None:  # names no dealt pair: wrong, and nothing to log
        return False
    # By text, so two lefts sharing a right ("city", "hospital" → "place") both match it.
    is_correct = any(u.left == left and u.right == right for u in units)
    answer_log.log_answer(learner.id, lesson.id, unit.key, unit.question.id, is_correct)
    return is_correct


def _count(payload: Mapping[str, Any], key: str) -> int:
    """A client-reported count as a non-negative int; anything that is not a number is 0."""
    value = payload.get(key, 0)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def result_type(lesson: Lesson) -> str:
    """The `session_type` of the lesson's result row: its game, else `"quiz"`."""
    return lesson.game_type or QUIZ_RESULT_TYPE


def _result(learner: Learner, lesson: Lesson) -> LearningSession | None:
    return db.session.scalar(db.select(LearningSession).filter_by(
        learner_id=learner.id, session_type=result_type(lesson), lesson_id=lesson.id))


def _record(learner: Learner, lesson: Lesson, correct: int, total: int) -> None:
    record = _result(learner, lesson)
    if record is None:
        record = LearningSession(learner_id=learner.id, session_type=result_type(lesson), lesson_id=lesson.id)
        db.session.add(record)
    record.correct_count = correct
    record.questions_completed = total


def complete_lesson(learner: Learner, lesson: Lesson, payload: object) -> CompletionPayload:
    """Finish ``lesson`` — quiz or game — from the raw request JSON, and commit.

    The learner is locked first and the answer log scored inside the lock, so a double submit
    waits for the first and then finds the log already cleared: it changes nothing and reports
    the lesson as already completed. The score is what the server graded — units right at the
    first try — never anything the client claims; a bonus count is clamped to what that score
    could earn, and a malformed payload counts as zeros.

    Raises:
        IncompleteLesson: A quiz with a question not yet answered right.
        ValueError: The lesson names an unknown game.
    """
    kind = lesson_type(lesson)
    data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
    learner = lock_learner(learner)
    units = deal(lesson)
    keys = {unit.key for unit in units}
    log = answer_log.find(learner.id, lesson.id)
    already_done = lesson.id in (learner.completed_lesson_ids or [])

    if log is None and already_done:
        # The log this lesson was scored from is gone: a repeat of a completion already recorded.
        record = _result(learner, lesson)
        correct = (record.correct_count or 0) if record else 0
        done = record_lesson_completion(learner, lesson, 0, correct_count=correct, total_count=len(units))
        db.session.commit()
        return done.payload

    if kind.requires_every_unit:
        missing = keys - answer_log.correct_units(log)
        if missing:
            raise IncompleteLesson(len(missing))

    correct = answer_log.first_try_correct(log, keys)
    total = len(units)
    bonus, extra = 0, {}
    if kind.bonus:
        bonus = min(_count(data, kind.bonus.key), kind.bonus.cap(correct, total))
        extra[kind.bonus.key] = bonus

    done = record_lesson_completion(
        learner, lesson, kind.xp(correct) + bonus * 10, correct_count=correct, total_count=total,
        grant_xp_boost=bool(kind.bonus and kind.bonus.grants_boost and bonus > 0 and correct > 0),
    )
    _record(learner, lesson, correct, total)
    answer_log.clear(learner.id, lesson.id)
    db.session.commit()

    capture_event(str(learner.id), kind.event_name, {
        "lesson_id": lesson.id,
        "topic_id": lesson.topic_id,
        "all_topic_completed": done.topic_completed,
        "correct_count": correct,
        "total_count": total,
        "xp_earned": done.payload["xp_earned"],
        "new_level": done.payload["new_level"],
        "xp_boosted": done.payload["xp_boosted"],
        "boost_earned": done.payload["boost_earned"],
        **extra,
    })
    return done.payload
