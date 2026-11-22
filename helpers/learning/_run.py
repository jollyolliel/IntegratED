"""A learner's run of a lesson: what it serves, where it resumes, and when a typed answer is hinted.

The lessons API (routes/api/lessons.py) only turns these into JSON. What a run is made of is the
lesson type's deal (`deal`); what has been answered is the answer log.
"""

from __future__ import annotations

from typing import NamedTuple

from helpers.learning import _answer_log as answer_log
from helpers.learning._games import deal, dealt_questions
from models import LearningSession, Lesson, Question

__all__ = ["HINT_AFTER_WRONG", "HINT_TYPES", "LessonRun", "hint", "lesson_run"]

# Typed-answer questions are easy to miss by a letter, so after this many wrong
# tries grading also returns the answer as a hint.
HINT_TYPES = frozenset({"open_answer", "text_comprehension_fill_blank"})
HINT_AFTER_WRONG = 3


class LessonRun(NamedTuple):
    """One learner's run of a lesson, as the questions endpoint serves it."""

    #: The distinct questions the run deals, in order.
    questions: list[Question]
    #: Match Up: question id -> its (left, right) pairs, in deal order. Empty for other types.
    pairs: dict[int, list[tuple[str, str]]]
    #: Questions done and not about to be replayed: every one before `resume_index`, never the one at it.
    correct_ids: list[int]
    #: Where the in-order frontends (the quiz, Rocket) reopen.
    resume_index: int
    #: How many units the run is scored over (a Match Up pair each, else a question each).
    unit_count: int


def lesson_run(learner_id: int, lesson: Lesson) -> LessonRun:
    """The learner's run of `lesson`: its questions, pairs and resume point."""
    units = deal(lesson)
    questions = dealt_questions(units)
    pairs: dict[int, list[tuple[str, str]]] = {}
    for unit in units:
        if unit.left is not None and unit.right is not None:
            pairs.setdefault(unit.question.id, []).append((unit.left, unit.right))

    done = answer_log.correct_units(answer_log.find(learner_id, lesson.id))
    answered = [answer_log.question_unit(q.id) in done for q in questions]
    first_unanswered = next((i for i, right in enumerate(answered) if not right), len(questions))
    # Step back over audio-only questions leading into the first unanswered one: they are logged
    # on Continue, so a quiz left after its opening listening question would reopen on question 2.
    # Those are shown again, so they drop out of `correct_ids` (or the strip ticks them as done).
    resume_index = first_unanswered
    while resume_index > 0 and questions[resume_index - 1].content_type == "vocabulary_audio":
        resume_index -= 1
    # Games that answer out of order (Garden Grow, Potion Workshop) keep what lies past the resume point.
    replayed = range(resume_index, first_unanswered)
    correct_ids = [q.id for i, q in enumerate(questions) if answered[i] and i not in replayed]
    return LessonRun(questions, pairs, correct_ids, resume_index, len(units))


def hint(question: Question, log: LearningSession | None) -> str | None:
    """The answer to reveal after a wrong try, once a typed answer has `HINT_AFTER_WRONG` wrong tries.

    Returns:
        str | None: `answer`, else the first accepted fill-in word; None when no hint is due.
    """
    unit = answer_log.question_unit(question.id)
    if question.content_type not in HINT_TYPES or answer_log.wrong_tries(log, unit) < HINT_AFTER_WRONG:
        return None
    accepted = question.fill_blank_options if isinstance(question.fill_blank_options, list) else []
    answer = question.answer or (accepted[0] if accepted else "")
    return " / ".join(map(str, answer)) if isinstance(answer, list) else str(answer)
