from flask import abort

from extensions import db
from helpers.analytics import capture_event
from helpers.current_user import current_learner as current_user
from helpers.learning import get_first_step
from helpers.render import render_template
from models import Lesson, Subject, Topic
from routes.learner import learner_bp


@learner_bp.route("/learn/subjects")
def learner_subjects():
    # Every course stays open; the placement result only marks where to start.
    recommended = get_first_step(current_user)
    recommended_subject_id = recommended["subject_id"] if recommended else None
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "learner_subjects", "recommended_course_id": recommended_subject_id},
    )
    subjects = db.session.scalars(db.select(Subject).filter_by(map_test_only=False)).all()
    return render_template(
        "@pages/learner/learning/subjects.jx", subjects=subjects, recommended_subject_id=recommended_subject_id
    )


@learner_bp.route("/learn/subjects/<int:subject_id>/topics")
def learner_subject_topics(subject_id):
    subject = db.session.get(Subject, subject_id)
    if not subject: abort(404)
    topics = db.session.scalars(
        db.select(Topic).filter_by(subject_id=subject.id).order_by(Topic.level.asc(), Topic.id.asc())
    ).all()
    completed_topic_ids = set(current_user.completed_topic_ids or [])
    started_topic_ids = set(db.session.scalars(
        db.select(Lesson.topic_id).distinct().where(
            Lesson.topic_id.in_([topic.id for topic in topics]),
            Lesson.id.in_(current_user.completed_lesson_ids or []),
        )
    ))
    # Highlighted only on the subject it belongs to.
    recommended = get_first_step(current_user)
    recommended_topic_id = (
        recommended["topic_id"] if recommended and recommended["subject_id"] == subject.id else None
    )
    topic_states = {
        topic.id: "completed" if topic.id in completed_topic_ids
        else "in_progress" if topic.id in started_topic_ids
        else "recommended" if topic.id == recommended_topic_id
        else "empty"
        for topic in topics
    }
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "learner_subject_topics", "subject_id": subject_id},
    )
    return render_template(
        "@pages/learner/learning/topics.jx",
        topics=topics,
        subject=subject,
        is_lesson=False,
        topic_states=topic_states,
    )


@learner_bp.route("/learn/topics/<int:topic_id>/lessons")
def learner_topic_lessons(topic_id):
    lessons = db.session.scalars(db.select(Lesson).filter_by(topic_id=topic_id).order_by(Lesson.id)).all()
    if not lessons: abort(404)
    completed_lesson_ids = set(current_user.completed_lesson_ids or [])
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "learner_topic_lessons", "topic_id": topic_id},
    )
    return render_template(
        "@pages/learner/learning/topics.jx",
        lessons=lessons,
        is_lesson=True,
        completed_lesson_ids=completed_lesson_ids,
    )


@learner_bp.route("/learn/overview/<int:lesson_id>")
def learner_overview(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    all_lessons = db.session.scalars(
        db.select(Lesson).filter_by(topic_id=lesson.topic_id).order_by(Lesson.id)
    ).all()

    # Progress = lessons actually finished, not how far down the list this one sits
    completed_lesson_ids = set(current_user.completed_lesson_ids or [])
    completed_count = sum(1 for item in all_lessons if item.id in completed_lesson_ids)
    total_lessons = len(all_lessons)
    percentage = round((completed_count / total_lessons) * 100) if total_lessons else 0
    capture_event(
        str(current_user.id),
        "page_viewed",
        properties={"page": "learner_overview", "lesson_id": lesson_id},
    )

    return render_template(
        "@pages/learner/learning/overview.jx",
        lesson=lesson,
        topic_lessons=all_lessons,
        completed_lesson_ids=completed_lesson_ids,
        completed_count=completed_count,
        total_lessons=total_lessons,
        percentage=percentage,
    )


@learner_bp.route("/learn/questions/<int:lesson_id>")
def learner_questions(lesson_id):
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson: abort(404)
    capture_event(
        str(current_user.id),
        "quiz_started",
        properties={"lesson_id": lesson_id, "lesson_name": lesson.title},
    )
    return render_template("@pages/learner/learning/quiz.jx", lesson=lesson)
