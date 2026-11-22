"""Pruning: what the content tables hold that `questions.json` no longer does, and removing it.

`plan_prune` works the plan out without writing (the release prints it first); `apply_prune` carries
it out. Learners keep their XP; finished lessons, topics and placement levels that point at removed
content are dropped, and sessions on removed content are cleared so those learners restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flask_sqlalchemy import SQLAlchemy

from helpers.content._schema import file_keys, question_key
from helpers.learning import _answer_log as answer_log
from models import (
    Learner,
    LearningSession,
    Lesson,
    MapQuestion,
    Question,
    Subject,
    Topic,
)

__all__ = ["PrunePlan", "apply_prune", "plan_prune"]


@dataclass
class PrunePlan:
    """What a prune would remove, computed against the database without writing.

    The `*_ids` sets include everything cascaded from a removed parent; the
    `removed_*` lists are only what is itself missing from the file, for the
    printed report.
    """

    #: (name, topics, lessons, questions, placement questions) of each removed subject.
    removed_subjects: list[tuple[str, int, int, int, int]] = field(default_factory=list)
    removed_topics: list[tuple[str, int]] = field(default_factory=list)
    removed_lessons: list[str] = field(default_factory=list)
    removed_questions: list[str] = field(default_factory=list)
    removed_map_questions: list[str] = field(default_factory=list)
    subject_ids: set[int] = field(default_factory=set)
    topic_ids: set[int] = field(default_factory=set)
    lesson_ids: set[int] = field(default_factory=set)
    question_ids: set[int] = field(default_factory=set)
    map_question_ids: set[int] = field(default_factory=set)
    session_ids: set[int] = field(default_factory=set)
    #: learner id -> the columns to rewrite on that learner.
    learner_updates: dict[int, dict[str, Any]] = field(default_factory=dict)
    reassessed_learners: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.subject_ids or self.topic_ids or self.lesson_ids or self.question_ids
                    or self.map_question_ids or self.session_ids or self.learner_updates)

    def lines(self) -> list[str]:
        """The plan as readable report lines."""
        if self.is_empty:
            return ["Nothing to remove: the database holds nothing the file doesn't."]
        out: list[str] = []
        if self.removed_subjects:
            out.append("Subjects (with everything in them):")
            out += [f"  - {name} ({topics} topics, {lessons} lessons, {questions} questions, "
                    f"{placement} placement questions)"
                    for name, topics, lessons, questions, placement in self.removed_subjects]
        if self.removed_topics:
            out.append("Topics:")
            out += [f"  - {path} ({lessons} lessons)" for path, lessons in self.removed_topics]
        for title, rows in (("Lessons:", self.removed_lessons), ("Questions:", self.removed_questions),
                            ("Placement questions:", self.removed_map_questions)):
            if rows:
                out.append(title)
                out += [f"  - {row}" for row in rows]
        if self.learner_updates:
            out.append(
                f"Learners: {len(self.learner_updates)} learner(s) lose finished lessons, topics or placement "
                "levels that point at removed content (XP already earned is kept)."
            )
        if self.reassessed_learners:
            out.append(
                f"  {self.reassessed_learners} of them were placed only on removed placement scales and will "
                "be asked to take the placement test again."
            )
        if self.session_ids:
            out.append(
                f"Learning sessions: {len(self.session_ids)} (on removed lessons, quizzes whose questions "
                "changed, or placement tests in progress) — those learners restart that activity."
            )
        return out


def _snip(text: str | None, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plan_prune(db: SQLAlchemy, data: list[Any]) -> PrunePlan:
    """Work out what `data` no longer contains and what points at it. Writes nothing.

    Args:
        db (SQLAlchemy): The app's SQLAlchemy extension instance.
        data (list[Any]): The validated content file.

    Returns:
        PrunePlan: The rows to remove and the learner/session clean-up.
    """
    keys = file_keys(data)
    plan = PrunePlan()

    subjects = db.session.scalars(db.select(Subject)).all()
    names = {s.id: s.name for s in subjects}
    topics = db.session.scalars(db.select(Topic)).all()
    lessons = db.session.scalars(db.select(Lesson)).all()
    questions = db.session.scalars(db.select(Question)).all()
    map_questions = db.session.scalars(db.select(MapQuestion)).all()
    topic_path = {t.id: (names[t.subject_id], t.title) for t in topics}
    lesson_path = {lsn.id: (*topic_path[lsn.topic_id], lsn.title) for lsn in lessons}

    plan.subject_ids = {s.id for s in subjects if s.name not in keys.subjects}
    for t in topics:
        if t.subject_id in plan.subject_ids:
            plan.topic_ids.add(t.id)
        elif topic_path[t.id] not in keys.topics:
            plan.topic_ids.add(t.id)
            plan.removed_topics.append((" > ".join(topic_path[t.id]), sum(1 for lsn in lessons if lsn.topic_id == t.id)))
    for lsn in lessons:
        if lsn.topic_id in plan.topic_ids:
            plan.lesson_ids.add(lsn.id)
        elif lesson_path[lsn.id] not in keys.lessons:
            plan.lesson_ids.add(lsn.id)
            plan.removed_lessons.append(" > ".join(lesson_path[lsn.id]))
    lessons_that_lost_questions: set[int] = set()
    for q in questions:
        if q.lesson_id in plan.lesson_ids or q.topic_id in plan.topic_ids or q.subject_id in plan.subject_ids:
            plan.question_ids.add(q.id)
        elif (*lesson_path[q.lesson_id], *question_key(q)) not in keys.questions:
            plan.question_ids.add(q.id)
            lessons_that_lost_questions.add(q.lesson_id)
            label = q.question_prompt if q.content_type == "match" else q.question_text
            plan.removed_questions.append(f"{' > '.join(lesson_path[q.lesson_id])}: {_snip(label)!r}")
    for mq in map_questions:
        if mq.subject_id in plan.subject_ids:
            plan.map_question_ids.add(mq.id)
        elif (names[mq.subject_id], mq.level, mq.question_text) not in keys.map_questions:
            plan.map_question_ids.add(mq.id)
            plan.removed_map_questions.append(f"{names[mq.subject_id]} level {mq.level}: {_snip(mq.question_text)!r}")
    for s in subjects:
        if s.id in plan.subject_ids:
            s_topics = {t.id for t in topics if t.subject_id == s.id}
            plan.removed_subjects.append((
                s.name,
                len(s_topics),
                sum(1 for lsn in lessons if lsn.topic_id in s_topics),
                sum(1 for q in questions if q.subject_id == s.id),
                sum(1 for mq in map_questions if mq.subject_id == s.id),
            ))

    sessions = db.session.scalars(db.select(LearningSession)).all()
    for row in sessions:
        if (
            (row.lesson_id is not None and row.lesson_id in plan.lesson_ids)
            or (row.session_type == answer_log.LOG_TYPE and row.lesson_id in lessons_that_lost_questions)
            or (row.session_type == "placement" and plan.map_question_ids)
        ):
            plan.session_ids.add(row.id)

    removed_names = {names[i] for i in plan.subject_ids}
    for learner in db.session.scalars(db.select(Learner)).all():
        update: dict[str, Any] = {}
        done = list(learner.completed_lesson_ids or [])
        if any(i in plan.lesson_ids for i in done):
            update["completed_lesson_ids"] = [i for i in done if i not in plan.lesson_ids]
        done_topics = list(learner.completed_topic_ids or [])
        if any(i in plan.topic_ids for i in done_topics):
            update["completed_topic_ids"] = [i for i in done_topics if i not in plan.topic_ids]
        levels = dict(learner.subject_levels or {})
        if any(name in removed_names for name in levels):
            kept = {name: level for name, level in levels.items() if name not in removed_names}
            update["subject_levels"] = kept
            # Their only result was on a scale that is gone: keep the gate open
            # but mark them deferred, so the dashboard invites the new test.
            if not kept and learner.completed_map_test and not learner.map_test_deferred:
                update["map_test_deferred"] = True
                plan.reassessed_learners += 1
        if update:
            plan.learner_updates[learner.id] = update
    return plan


def _delete_ids(db: SQLAlchemy, model: Any, ids: set[int]) -> None:
    ordered = sorted(ids)
    for start in range(0, len(ordered), 500):
        chunk = ordered[start:start + 500]
        db.session.execute(db.delete(model).where(model.id.in_(chunk)), execution_options={"synchronize_session": False})


def apply_prune(db: SQLAlchemy, plan: PrunePlan) -> None:
    """Carry out `plan`, children before parents so Postgres' foreign keys hold. Does not commit."""
    for learner_id, update in plan.learner_updates.items():
        learner = db.session.get(Learner, learner_id)
        if learner is not None:
            for column, value in update.items():
                setattr(learner, column, value)
    db.session.flush()

    _delete_ids(db, LearningSession, plan.session_ids)
    if plan.subject_ids:
        db.session.execute(
            db.update(Subject).where(Subject.placement_scale_id.in_(sorted(plan.subject_ids)))
            .values(placement_scale_id=None, placement_min_level=None, placement_max_level=None),
            execution_options={"synchronize_session": False},
        )
    _delete_ids(db, Question, plan.question_ids)
    _delete_ids(db, Lesson, plan.lesson_ids)
    _delete_ids(db, Topic, plan.topic_ids)
    _delete_ids(db, MapQuestion, plan.map_question_ids)
    _delete_ids(db, Subject, plan.subject_ids)
    db.session.expire_all()
