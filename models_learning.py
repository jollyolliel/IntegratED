from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Mapped, relationship

from extensions import db

if TYPE_CHECKING:
    from models import Learner


# ======================
# Learn: Subject
# ======================
class Subject(db.Model):
    """Top of the content hierarchy (Subject -> Topic -> Lesson -> Question);
    learners see a subject as a **course**. `map_test_only=True` marks a
    subject that exists for the placement test alone — a **placement scale**
    with no learning path of its own.

    A course on a placement scale names it in `placement_scale_id` and serves
    the scale's levels `placement_min_level`..`placement_max_level`
    (inclusive); its topics' `level`s are then levels on that scale. All three
    are None for a course that isn't on a scale (ADR 0016)."""

    __tablename__ = "subjects"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    name: Mapped[str] = db.Column(db.String(50), unique=True, nullable=False)  # Math, Grammar
    icon: Mapped[str] = db.Column(db.String(100), nullable=False)  # Icon from fontawesome
    map_test_only: Mapped[bool] = db.Column(db.Boolean, nullable=False, default=False)

    description: Mapped[str] = db.Column(db.Text, nullable=False)  # Short description of the subject

    placement_scale_id: Mapped[int | None] = db.Column(
        db.Integer, db.ForeignKey("subjects.id", name="fk_subjects_placement_scale_id_subjects"), nullable=True
    )
    placement_min_level: Mapped[int | None] = db.Column(db.Integer, nullable=True)
    placement_max_level: Mapped[int | None] = db.Column(db.Integer, nullable=True)

    topics: Mapped[list[Topic]] = relationship(
        "Topic", back_populates="subject", cascade="all, delete-orphan"
    )
    questions: Mapped[list[Question]] = relationship("Question", back_populates="subject")
    placement_scale: Mapped[Subject | None] = relationship("Subject", remote_side=[id])


# ======================
# Learn: Topic
# ======================
class Topic(db.Model):
    """A difficulty band within a Subject. `level` orders topics within their
    subject (1 = easiest; several topics may share one) and is what a
    placement result is compared with to recommend a starting topic. In a
    course on a placement scale it is a level on that scale, inside the
    course's band; otherwise it is the subject's own rank, aligned with its
    `MapQuestion.level`s. Deleting a Topic cascades to its Lessons and their
    Questions."""

    __tablename__ = "topics"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    subject_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    icon: Mapped[str] = db.Column(db.String(100), nullable=False)  # Icon from fontawesome

    # Difficulty: a placement-scale level in a banded course, else the subject's own rank.
    level: Mapped[int] = db.Column(db.Integer, nullable=False, default=1)

    description: Mapped[str] = db.Column(db.Text, nullable=False)

    title: Mapped[str] = db.Column(db.String(150), nullable=False)
    overview_markdown: Mapped[str] = db.Column(db.Text, nullable=False)

    subject: Mapped[Subject] = relationship("Subject", back_populates="topics")

    lessons: Mapped[list[Lesson]] = relationship(
        "Lesson", back_populates="topic", cascade="all, delete-orphan"
    )


# ======================
# Learn: Lesson
# ======================
class Lesson(db.Model):
    """A unit of content within a Topic — either a quiz (`game_type` None)
    or one of the minigames (`game_type` set, see `is_gamified`). Deleting
    a Lesson cascades to its Questions."""

    __tablename__ = "lessons"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    topic_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=False)

    icon: Mapped[str] = db.Column(db.String(100), nullable=False)  # Icon from fontawesome
    description: Mapped[str] = db.Column(db.Text, nullable=False)

    title: Mapped[str] = db.Column(db.String(150), nullable=False)
    overview_markdown: Mapped[str | None] = db.Column(db.Text, nullable=True)
    game_type: Mapped[str | None] = db.Column(db.String(50), nullable=True)

    @property
    def is_gamified(self) -> bool:
        return self.game_type is not None

    topic: Mapped[Topic] = relationship("Topic", back_populates="lessons")

    questions: Mapped[list[Question]] = relationship(
        "Question", back_populates="lesson_rel", cascade="all, delete-orphan"
    )


# ======================
# Learn: Question
# ======================
class Question(db.Model):
    """A quiz/lesson question. `subject_id`/`topic_id` duplicate what's
    derivable via `lesson_id` — kept as their own indexed columns purely so
    subject/topic-scoped queries don't have to join through Lesson.
    `content_type` selects which of the type-specific JSON fields (options,
    word_bank, match_pairs, ...) are populated; the accepted values are
    `CONTENT_TYPES` in helpers/content/_schema.py."""

    __tablename__ = "questions"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)

    # Links
    subject_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    topic_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("topics.id"), nullable=False, index=True)
    lesson_id: Mapped[int] = db.Column(
        db.Integer, db.ForeignKey("lessons.id"), nullable=False, index=True
    )

    # Fields
    content_type: Mapped[str] = db.Column(db.String(50), nullable=False)

    # Whether the question's text / each option is spoken. The audio itself is served on request
    # from the text (helpers/audio_cache.py). The *_sound_url columns are no longer read or written
    # and go in a later migration, so a deploy never drops a column the running revision selects.
    question_sound: Mapped[bool | None] = db.Column(db.Boolean, default=False)
    question_sound_url: Mapped[str | None] = db.Column(db.String(500), nullable=True)

    option_sound: Mapped[bool | None] = db.Column(db.Boolean, default=False)
    option_sound_url: Mapped[list[str | None] | None] = db.Column(db.JSON, nullable=True)

    question_prompt: Mapped[str] = db.Column(db.String(300), nullable=False)
    question_subtext: Mapped[str | None] = db.Column(db.String(300), nullable=True)
    question_text: Mapped[str] = db.Column(db.Text, nullable=False)

    # store options as JSON array
    options: Mapped[list[Any] | None] = db.Column(db.JSON, nullable=True)

    answer: Mapped[str | None] = db.Column(db.String(300), nullable=True)

    # Context/reference material
    context_group_id: Mapped[str | None] = db.Column(db.String(100), nullable=True)
    context_text: Mapped[str | None] = db.Column(db.Text, nullable=True)
    context_image: Mapped[str | None] = db.Column(db.String(300), nullable=True)

    word_selection_correct_words: Mapped[list[str] | None] = db.Column(db.JSON, nullable=True)
    fill_blank_options: Mapped[list[Any] | None] = db.Column(db.JSON, nullable=True)
    word_bank: Mapped[list[str] | None] = db.Column(db.JSON, nullable=True)
    word_type: Mapped[str | None] = db.Column(db.String(50), nullable=True)
    max_attempts: Mapped[int | None] = db.Column(db.Integer, nullable=True)
    match_pairs: Mapped[list[Any] | None] = db.Column(db.JSON, nullable=True)

    subject: Mapped[Subject] = relationship("Subject", back_populates="questions")
    lesson_rel: Mapped[Lesson] = relationship("Lesson", back_populates="questions")


# ======================
# Placement: MapQuestion
# ======================
class MapQuestion(db.Model):
    """A placement-test question — same shape as `Question` but scoped by
    `subject_id` (its placement scale) + `level` instead of the
    Subject/Topic/Lesson hierarchy; used only by the adaptive placement test,
    never the regular learning path."""

    __tablename__ = "map_questions"

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)

    # Categorization
    subject_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    level: Mapped[int] = db.Column(db.Integer, nullable=False, default=1)

    content_type: Mapped[str] = db.Column(db.String(50), nullable=False)
    question_prompt: Mapped[str] = db.Column(db.String(300), nullable=False)
    question_text: Mapped[str] = db.Column(db.Text, nullable=False)
    options: Mapped[list[Any] | None] = db.Column(db.JSON, nullable=True)
    answer: Mapped[str | None] = db.Column(db.String(300), nullable=True)
    question_sound: Mapped[bool | None] = db.Column(db.Boolean, default=False)
    question_sound_url: Mapped[str | None] = db.Column(db.String(500), nullable=True)  # unused, see Question
    # Listening question: the learner hears it and sees no prompt text, only the options.
    audio_only: Mapped[bool | None] = db.Column(db.Boolean, default=False)

    subject: Mapped[Subject] = relationship("Subject")


# ======================
# Learning: Session
# ======================
class LearningSession(db.Model):
    """
    Unified in-progress session for all learning activity:
      - session_type='placement'  : adaptive placement test (one per learner, deleted on finish)
      - session_type='answer_log' : one lesson's in-progress answers, any lesson type
                                    (helpers/learning/_answer_log.py; deleted on completion)
      - session_type='quiz'|'rocket'|'word_storm'|'match_up'|'garden_grow'|'potion_workshop'
        : the lesson's result record (`result_type`; kept after completion)

    lesson_id is NULL for placement sessions.
    Quiz/game fields unused for placement; placement fields unused for quiz/game.
    """
    __tablename__ = "learning_sessions"
    # One answer log / one game record per learner and lesson: looked up by exactly these columns,
    # and two first answers arriving together must not make two rows (helpers/learning/_answer_log.py).
    __table_args__ = (
        db.UniqueConstraint(
            "learner_id", "session_type", "lesson_id", name="uq_learning_sessions_learner_session_lesson"
        ),
    )

    id: Mapped[int] = db.Column(db.Integer, primary_key=True)
    learner_id: Mapped[int] = db.Column(db.Integer, db.ForeignKey("learners.id"), nullable=False, index=True)

    # 'placement' | 'answer_log' | 'quiz' | 'rocket' | 'word_storm' |
    # 'match_up' | 'garden_grow' | 'potion_workshop'
    session_type: Mapped[str] = db.Column(db.String(20), nullable=False, default="placement")
    lesson_id: Mapped[int | None] = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=True, index=True)

    # --- Placement test state ---
    subject_state: Mapped[dict[str, Any]] = db.Column(db.JSON, nullable=False, default=dict)
    asked_ids: Mapped[list[int]] = db.Column(db.JSON, nullable=False, default=list)
    history: Mapped[list[Any]] = db.Column(db.JSON, nullable=False, default=list)
    count: Mapped[int | None] = db.Column(db.Integer, default=0)

    # --- Quiz/game progress ---
    responses: Mapped[list[Any] | None] = db.Column(db.JSON, nullable=True, default=list)
    correct_count: Mapped[int | None] = db.Column(db.Integer, default=0)
    questions_completed: Mapped[int | None] = db.Column(db.Integer, default=0)
    word_selection_attempts: Mapped[dict[str, Any] | None] = db.Column(db.JSON, nullable=True, default=dict)

    updated_at: Mapped[datetime | None] = db.Column(
        db.DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    learner: Mapped[Learner] = relationship(
        "Learner", backref=db.backref("learning_sessions", lazy="dynamic")
    )
