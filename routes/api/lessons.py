"""A lesson's run, for the quiz and every game alike: its questions, grading one answer (or one
Match Up pair), and finishing it.

Answers never leave the server: the questions payload carries no `answer`,
`fill_blank_options` or Match Up pairing, and every check happens here. What a run is made of —
every question, the ones with options, or Match Up's pairs — is the lesson type's deal
(`helpers.learning.deal`), so the page shows exactly what is scored.
"""

import random
from typing import NotRequired, TypedDict

from flask import jsonify, request

from extensions import db
from helpers.analytics import capture_event
from helpers.audio_cache import audio_url
from helpers.current_user import current_learner as current_user
from helpers.learning import (
    IncompleteLesson,
    answer_log,
    check_match_pair,
    complete_lesson,
    grade,
    hint,
    lesson_run,
)
from models import Lesson, Question
from routes.api import learner_api


class _QuestionPayload(TypedDict):
    """A question as the browser may see it: what shows it, never what grades it."""

    id: int
    content_type: str
    question_prompt: str | None
    question_subtext: str | None
    question_text: str | None
    question_sound: bool | None
    question_sound_url: str | None
    options: object
    context_text: str | None
    context_image: str | None
    word_bank: object
    match_left: NotRequired[list[str]]
    match_right: NotRequired[list[str]]


def _question_payload(q: Question, pairs: list[tuple[str, str]]) -> _QuestionPayload:
    """One question as the browser may see it — everything needed to show it, nothing that grades it."""
    payload: _QuestionPayload = {
        "id": q.id,
        "content_type": q.content_type,
        "question_prompt": q.question_prompt,
        "question_subtext": q.question_subtext,
        "question_text": q.question_text,
        "question_sound": q.question_sound,
        "question_sound_url": audio_url(q.question_text) if q.question_sound else None,
        "options": q.options,
        "context_text": q.context_text,
        "context_image": q.context_image,
        "word_bank": q.word_bank,
    }
    if pairs:
        # The one place Match Up's right column is shuffled; the page lays it out as sent.
        rights = [right for _left, right in pairs]
        random.shuffle(rights)
        payload["match_left"] = [left for left, _right in pairs]
        payload["match_right"] = rights
    return payload


def _lesson_or_404(lesson_id: int):
    lesson = db.session.get(Lesson, lesson_id)
    if lesson is None:
        return None, (jsonify({"error": "Lesson not found"}), 404)
    return lesson, None


@learner_api.route("/quiz/<int:lesson_id>/questions")
def api_get_lesson_questions(lesson_id):
    """The questions a run of the lesson deals, plus its resume state (`helpers.learning.LessonRun`)."""
    lesson, missing = _lesson_or_404(lesson_id)
    if missing:
        return missing

    run = lesson_run(current_user.id, lesson)
    capture_event(
        str(current_user.id),
        "quiz_loaded",
        properties={"lesson_id": lesson_id, "question_count": len(run.questions), "unit_count": run.unit_count},
    )

    return jsonify({
        "questions": [_question_payload(q, run.pairs.get(q.id, [])) for q in run.questions],
        "progress": {
            "correct_ids": run.correct_ids,
            "resume_index": run.resume_index,
        },
    })


@learner_api.route("/quiz/validate-answer", methods=["POST"])
def api_validate_answer():
    """Grade one answer and log it on the lesson's answer log.

    A question answered right once is never logged again, so a learner retrying
    after a wrong answer can't inflate the score — but retries are always
    re-graded. After `HINT_AFTER_WRONG` wrong tries at a typed answer, the reply
    carries the answer as `hint` (`helpers.learning.hint`).
    """
    data = request.get_json(silent=True) or {}
    try:
        lesson_id = int(data.get("lesson_id") or 0)
        question_id = int(data.get("question_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid lesson or question id"}), 400
    if not lesson_id or not question_id:
        return jsonify({"error": "Missing required fields"}), 400

    question = db.session.get(Question, question_id)
    if not question:
        return jsonify({"error": "Question not found"}), 404
    # Logged against lesson_id's log — a question from another lesson
    # would count toward finishing this one.
    if question.lesson_id != lesson_id:
        return jsonify({"error": "Question is not in this lesson"}), 400

    graded = grade(question, data)
    unit = answer_log.question_unit(question_id)
    log = answer_log.log_answer(current_user.id, lesson_id, unit, question_id, graded.is_correct)
    capture_event(str(current_user.id), "quiz_answer_validated", {
        "question_id": question_id,
        "lesson_id": lesson_id,
        "is_correct": graded.is_correct,
        "type": question.content_type,
    })

    reply = {"is_correct": graded.is_correct, "partial_credit": graded.partial_credit}
    revealed = None if graded.is_correct else hint(question, log)
    if revealed is not None:
        reply["hint"] = revealed
    return jsonify(reply)


@learner_api.route("/match-up/<int:lesson_id>/pair", methods=["POST"])
def api_match_up_pair(lesson_id):
    """Check one Match Up pairing — ``{"left", "right"}`` → ``{"is_correct"}`` — and log it,
    so the completion scores the pairs the server saw matched first time."""
    lesson, missing = _lesson_or_404(lesson_id)
    if missing:
        return missing
    if lesson.game_type != "match_up":
        return jsonify({"error": "This lesson is not that game"}), 400
    data = request.get_json(silent=True) or {}
    left, right = data.get("left"), data.get("right")
    if not isinstance(left, str) or not isinstance(right, str):
        return jsonify({"error": "left and right are required"}), 400
    return jsonify({"is_correct": check_match_pair(current_user, lesson, left, right)})


@learner_api.route("/lesson/<int:lesson_id>/completion", methods=["POST"])
def api_lesson_completion(lesson_id):
    """Finish a lesson (the quiz or any game) and answer with what it earned."""
    lesson, missing = _lesson_or_404(lesson_id)
    if missing:
        return missing
    # The body is only a game's bonus count; complete_lesson decides how much of it to believe.
    try:
        return jsonify(complete_lesson(current_user, lesson, request.get_json(silent=True)))
    except IncompleteLesson as error:  # a question not yet answered right: nothing recorded
        return jsonify({"error": "Answer every question before finishing", "unanswered": error.unanswered}), 400
