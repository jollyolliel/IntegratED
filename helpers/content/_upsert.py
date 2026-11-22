"""Writing a validated `questions.json` into the content tables, matched by natural key.

Rows are found by the keys in `_schema.py` and updated in place, so a re-import changes nothing it
does not have to. `upsert` reports how many question rows (lesson and placement) it added and changed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from flask_sqlalchemy import SQLAlchemy

from helpers.content._schema import PLACEMENT_ENTRY, question_key
from models import Lesson, MapQuestion, Question, Subject, Topic

__all__ = ["QuestionCounts", "upsert"]


@dataclass
class QuestionCounts:
    """Question rows (lesson and placement) an import inserted, and existing ones whose values changed."""

    added: int = 0
    updated: int = 0


def _assign(row: Any, fields: dict[str, Any]) -> bool:
    """Set each field that differs on `row`; whether any did."""
    changed = False
    for name, value in fields.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return changed


def _upsert_question(db: SQLAlchemy, row: Any, model: type, key_fields: dict[str, Any],
                     fields: dict[str, Any], counts: QuestionCounts) -> None:
    """Insert `row` (built from `key_fields`) when it is None, else update it; count which."""
    if row is None:
        db.session.add(model(**key_fields, **fields))
        counts.added += 1
    elif _assign(row, fields):
        counts.updated += 1


def _upsert_placement_questions(db: SQLAlchemy, entry: dict[str, Any], subjects_by_name: dict[str, Subject],
                                course_names: set[str], counts: QuestionCounts) -> None:
    for q_data in entry["questions"]:
        scale_name = q_data["subject_name"]
        if scale_name not in subjects_by_name:
            scale = Subject(name=scale_name, icon="question", description=f"{scale_name} subject",
                            map_test_only=scale_name not in course_names)
            db.session.add(scale)
            db.session.flush()
            subjects_by_name[scale_name] = scale
        scale = subjects_by_name[scale_name]

        key_fields = {"subject_id": scale.id, "level": q_data["level"], "question_text": q_data["question_text"]}
        _upsert_question(db, db.session.scalar(db.select(MapQuestion).filter_by(**key_fields)), MapQuestion, key_fields, {
            "content_type": q_data["content_type"],
            "question_prompt": q_data["question_prompt"],
            "options": q_data.get("options"),
            "answer": q_data["answer"],
            "question_sound": q_data.get("question_sound", False),
            "audio_only": bool(q_data.get("audio_only", False)),
        }, counts)


def _group_id(db: SQLAlchemy, group: dict[str, Any], lesson: Lesson) -> str:
    """The group id a `text_group`'s questions already share, else a new one."""
    for q_data in group.get("questions", []):
        existing = db.session.scalar(db.select(Question.context_group_id).filter_by(
            question_text=q_data.get("question_text", ""), lesson_id=lesson.id,
        ))
        if existing:
            return existing
    return str(uuid.uuid4())


def _existing_question(db: SQLAlchemy, q_data: dict[str, Any], lesson: Lesson) -> Question | None:
    kind, key = question_key(q_data)
    if kind == "match":
        return db.session.scalar(db.select(Question).filter_by(content_type="match", lesson_id=lesson.id,
                                                               question_prompt=key))
    return db.session.scalar(db.select(Question).where(
        Question.question_text == key, Question.lesson_id == lesson.id, Question.content_type != "match",
    ))


def _upsert_lesson_questions(db: SQLAlchemy, lesson_data: dict[str, Any], subject: Subject, topic: Topic,
                             lesson: Lesson, counts: QuestionCounts) -> None:
    for item in lesson_data.get("questions", []):
        # A text_group's questions share its context and one group id; a lone question has its own context.
        if item.get("content_type") == "text_group":
            group_id, members = _group_id(db, item, lesson), item.get("questions", [])
        else:
            group_id, members = None, [item]
        for q_data in members:
            _upsert_lesson_question(db, q_data, item, group_id, subject, topic, lesson, counts)


def _upsert_lesson_question(db: SQLAlchemy, q_data: dict[str, Any], context: dict[str, Any], group_id: str | None,
                            subject: Subject, topic: Topic, lesson: Lesson, counts: QuestionCounts) -> None:
    kind, key = question_key(q_data)
    # A match question has no text of its own; its first lefts stand in for it.
    question_text = ",".join(p["left"] for p in q_data["match_pairs"][:3]) if kind == "match" else key
    _upsert_question(
        db, _existing_question(db, q_data, lesson), Question,
        {"lesson_id": lesson.id, "subject_id": subject.id, "topic_id": topic.id},
        {
            "question_text": question_text,
            "content_type": q_data["content_type"],
            "question_sound": q_data.get("question_sound", q_data.get("sound", False)),
            "option_sound": q_data.get("option_sound", False),
            "question_prompt": key if kind == "match" else q_data.get("question_prompt", ""),
            "question_subtext": q_data.get("question_subtext", ""),
            "options": q_data.get("options"),
            "answer": q_data.get("answer"),
            "context_group_id": group_id,
            "context_text": context.get("context_text"),
            "context_image": context.get("context_image"),
            "word_selection_correct_words": q_data.get("word_selection_correct_words"),
            "fill_blank_options": q_data.get("fill_blank_options"),
            "word_bank": q_data.get("word_bank"),
            "word_type": q_data.get("word_type"),
            "max_attempts": q_data.get("max_attempts"),
            "match_pairs": q_data.get("match_pairs"),
        },
        counts,
    )


def _upsert_course(db: SQLAlchemy, sub_data: dict[str, Any], subjects_by_name: dict[str, Subject],
                   counts: QuestionCounts) -> None:
    subj_name = sub_data["name"]
    if subj_name not in subjects_by_name:
        subject = Subject(name=subj_name, icon=sub_data.get("icon", ""), description=sub_data.get("description", ""))
        db.session.add(subject)
        db.session.flush()
        subjects_by_name[subj_name] = subject
    subject = subjects_by_name[subj_name]

    for topic_index, top_data in enumerate(sub_data.get("topics", [])):
        # Difficulty rank: explicit "level" wins, else the topic's position in the subject
        # (1-based). A course with a placement band must give every topic a level — validation checks.
        topic_level = top_data.get("level", topic_index + 1)
        topic = db.session.scalar(db.select(Topic).filter_by(title=top_data["title"], subject_id=subject.id))
        if not topic:
            topic = Topic(
                subject_id=subject.id,
                title=top_data["title"],
                icon=top_data["icon"],
                description=top_data["description"],
                overview_markdown=top_data["overview_markdown"],
                level=topic_level,
            )
            db.session.add(topic)
            db.session.flush()
        else:
            topic.level = topic_level

        for lesson_data in top_data.get("lessons", []):
            lesson = db.session.scalar(db.select(Lesson).filter_by(title=lesson_data["title"], topic_id=topic.id))
            if not lesson:
                lesson = Lesson(
                    topic_id=topic.id,
                    title=lesson_data["title"],
                    icon=lesson_data["icon"],
                    description=lesson_data["description"],
                    overview_markdown=lesson_data.get("overview_markdown", ""),
                    game_type=lesson_data.get("game_type"),
                )
                db.session.add(lesson)
                db.session.flush()
            else:
                lesson.game_type = lesson_data.get("game_type")

            _upsert_lesson_questions(db, lesson_data, subject, topic, lesson, counts)


def upsert(db: SQLAlchemy, data: list[Any]) -> QuestionCounts:
    """Write a validated content file into the content tables. Does not commit.

    Returns:
        QuestionCounts: Question rows added and changed.
    """
    counts = QuestionCounts()
    subjects_by_name = {s.name: s for s in db.session.scalars(db.select(Subject)).all()}
    course_names = {entry["name"] for entry in data if entry["name"] != PLACEMENT_ENTRY}

    for sub_data in data:
        if sub_data["name"] == PLACEMENT_ENTRY:
            _upsert_placement_questions(db, sub_data, subjects_by_name, course_names, counts)
        else:
            _upsert_course(db, sub_data, subjects_by_name, counts)

    # Second pass, now every subject exists whatever the file order: what the
    # file says each subject is. A name that is only ever a placement
    # `subject_name` is a placement scale (hidden from the learning path); a
    # course's band is set from its "placement", or cleared without one.
    scale_names = {
        q["subject_name"] for entry in data if entry["name"] == PLACEMENT_ENTRY for q in entry.get("questions", [])
    }
    for name in scale_names | course_names:
        subjects_by_name[name].map_test_only = name not in course_names
    for sub_data in data:
        if sub_data["name"] == PLACEMENT_ENTRY:
            continue
        course = subjects_by_name[sub_data["name"]]
        band = sub_data.get("placement")
        if band:
            course.placement_scale_id = subjects_by_name[band["scale"]].id
            course.placement_min_level = band["min_level"]
            course.placement_max_level = band["max_level"]
        else:
            course.placement_scale_id = course.placement_min_level = course.placement_max_level = None
    return counts
