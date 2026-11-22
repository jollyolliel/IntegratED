from flask import abort, redirect, url_for

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_learner as current_user
from helpers.learning import GARDEN_PLOTS
from helpers.render import render_template
from models import Lesson
from routes.learner import learner_bp


@learner_bp.route("/learn/rocket/<int:lesson_id>")
def learner_rocket(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    if lesson.game_type != "rocket":
        return redirect(url_for("learner.learner_questions", lesson_id=lesson_id))
    already_completed = lesson_id in (current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "rocket_game_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template(
        "@pages/learner/learning/rocket.jx",
        lesson=lesson,
        already_completed=already_completed,
    )


@learner_bp.route("/learn/word-storm/<int:lesson_id>")
def learner_word_storm(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    if lesson.game_type != "word_storm":
        return redirect(url_for("learner.learner_questions", lesson_id=lesson_id))
    already_completed = lesson_id in (current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "word_storm_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template(
        "@pages/learner/learning/word_storm.jx",
        lesson=lesson,
        already_completed=already_completed,
    )


@learner_bp.route("/learn/match-up/<int:lesson_id>")
def learner_match_up(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    if lesson.game_type != "match_up":
        return redirect(url_for("learner.learner_questions", lesson_id=lesson_id))
    already_completed = lesson_id in (current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "match_up_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template(
        "@pages/learner/learning/match_up.jx",
        lesson=lesson,
        already_completed=already_completed,
    )


@learner_bp.route("/learn/garden-grow/<int:lesson_id>")
def learner_garden_grow(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    if lesson.game_type != "garden_grow":
        return redirect(url_for("learner.learner_questions", lesson_id=lesson_id))
    already_completed = lesson_id in (current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "garden_grow_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template(
        "@pages/learner/learning/garden_grow.jx",
        lesson=lesson,
        garden_plots=GARDEN_PLOTS,
        already_completed=already_completed,
    )


@learner_bp.route("/learn/potion-workshop/<int:lesson_id>")
def learner_potion_workshop(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    if lesson.game_type != "potion_workshop":
        return redirect(url_for("learner.learner_questions", lesson_id=lesson_id))
    already_completed = lesson_id in (current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "potion_workshop_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template(
        "@pages/learner/learning/potion_workshop.jx",
        lesson=lesson,
        already_completed=already_completed,
    )
