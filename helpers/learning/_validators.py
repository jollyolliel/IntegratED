"""Grading one quiz answer: a validator per content type, and `grade` to dispatch on it.

Validators only say whether an answer is right. What the learner is told is the page's own
copy (quiz.jx, translated), so nothing here returns a message.
"""

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from models import Question

__all__ = [
    "Grade",
    "grade",
    "validate_drag_drop",
    "validate_fill_blank",
    "validate_multiple_choice",
    "validate_open_answer",
    "validate_word_selection",
]


class Grade(NamedTuple):
    """One graded try. `partial_credit` is word selection's found-so-far percentage, else None."""

    is_correct: bool
    partial_credit: int | None = None


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def validate_multiple_choice(question: Question, user_answer: Any) -> bool:
    """Exact (trimmed, case-blind) match on `answer`, for every choice type.

    Args:
        question (Question): Question being answered.
        user_answer (Any): Learner's submitted answer.

    Returns:
        bool: Whether it is right.
    """
    return _norm(user_answer) == _norm(question.answer)


def _accepted(question: Question) -> list[Any]:
    return question.fill_blank_options if isinstance(question.fill_blank_options, list) else []


def validate_open_answer(question: Question, user_answer: Any) -> bool:
    """Whether the reply matches `answer` or one of `fill_blank_options`.

    Args:
        question (Question): Question being answered.
        user_answer (Any): Learner's submitted answer.

    Returns:
        bool: Whether it is right.
    """
    answer = _norm(user_answer)
    return answer == _norm(question.answer) or any(_norm(option) == answer for option in _accepted(question))


def validate_fill_blank(question: Question, user_answer: Any) -> bool:
    """Any of `fill_blank_options`; a question without them falls back to `answer`.

    Args:
        question (Question): Question being answered.
        user_answer (Any): Learner's submitted text.

    Returns:
        bool: Whether it is right.
    """
    accepted = _accepted(question)
    if not accepted:
        return validate_multiple_choice(question, user_answer)
    answer = _norm(user_answer)
    return any(_norm(option) == answer for option in accepted)


def validate_word_selection(question: Question, selected_words: Any) -> Grade:
    """Every correct word and no other; a clean partial selection earns partial credit.

    Args:
        question (Question): Question being answered.
        selected_words (Any): Words the learner selected; anything but a list is wrong.

    Returns:
        Grade: Right only when every correct word is selected; `partial_credit` is the share
            found (0 once any wrong word is in the selection).
    """
    correct = {_norm(word) for word in question.word_selection_correct_words or []}
    if not correct or not isinstance(selected_words, list):
        return Grade(False, 0)
    selected = {_norm(word) for word in selected_words}
    if not selected or selected - correct:
        return Grade(False, 0)
    if selected == correct:
        return Grade(True, 100)
    return Grade(False, int(len(selected) * 100 / len(correct)))


def validate_drag_drop(question: Question, answers: Any) -> bool:
    """Each blank (`"blank-<n>"`) holds its word from `fill_blank_options`, in order.

    Args:
        question (Question): Question being answered.
        answers (Any): Blank key -> placed word; anything but a mapping is wrong.

    Returns:
        bool: Whether every blank is right.
    """
    expected = _accepted(question)
    if not expected or not isinstance(answers, Mapping):
        return False
    return all(_norm(answers.get(f"blank-{index}") or "") == _norm(word) for index, word in enumerate(expected))


_GRADERS: dict[str, Callable[[Question, Mapping[str, Any]], Grade]] = {
    # Read-and-listen questions have nothing to get wrong: pressing Continue is the answer.
    "text_comprehension_read_word": lambda _q, _data: Grade(True),
    "vocabulary_audio": lambda _q, _data: Grade(True),
    "text_comprehension_fill_blank": lambda q, data: Grade(validate_fill_blank(q, data.get("user_answer", ""))),
    "text_comprehension_word_selection": lambda q, data: validate_word_selection(q, data.get("selected_words")),
    "text_comprehension_drag_drop": lambda q, data: Grade(validate_drag_drop(q, data.get("answers"))),
    "open_answer": lambda q, data: Grade(validate_open_answer(q, data.get("user_answer", ""))),
}


def grade(question: Question, data: Mapping[str, Any]) -> Grade:
    """Grade one submitted try with its content type's validator; every choice type is an exact match.

    Args:
        question (Question): Question being answered.
        data (Mapping[str, Any]): The request JSON (`user_answer`, `selected_words` or `answers`).

    Returns:
        Grade: Whether it is right, and word selection's partial credit.
    """
    grader = _GRADERS.get(question.content_type)
    if grader is None:
        return Grade(validate_multiple_choice(question, data.get("user_answer", "")))
    return grader(question, data)
