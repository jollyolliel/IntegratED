"""Recording a finished lesson on the learner: XP, progress, the topic roll-up and the next lesson."""

from typing import NamedTuple, TypedDict

from extensions import db
from helpers.gamification import (
    UnlockedItem,
    apply_xp,
    compute_level,
    items_unlocked_between,
    level_name,
)
from models import Learner, Lesson

__all__ = ["CompletionPayload", "LessonCompletion", "LessonRef", "lock_learner", "record_lesson_completion"]


class LessonRef(TypedDict):
    """A lesson as the completion payload names it: the one finished, or the next one."""

    id: int
    title: str


class CompletionPayload(TypedDict):
    """The JSON the completion route answers with, for the quiz and every game alike."""

    status: str
    lesson: LessonRef
    xp_earned: int
    total_xp: int
    already_completed: bool
    next_lesson: LessonRef | None
    is_last: bool
    leveled_up: bool
    new_level: int
    level_name: str
    # Wardrobe items this completion's level-up made available (empty without one).
    new_items_unlocked: list[UnlockedItem]
    # Golden potion boost: this completion's XP was doubled by one / this completion stored one.
    xp_boosted: bool
    boost_earned: bool
    # The score the server graded, which the page shows: units right at the first try, out of all dealt.
    correct_count: int
    total_count: int


class LessonCompletion(NamedTuple):
    payload: CompletionPayload
    topic_completed: bool


def lock_learner(learner: Learner) -> Learner:
    """The learner row, locked for the rest of the transaction, so two completions take turns.

    Raises:
        ValueError: The learner no longer exists.
    """
    locked = db.session.scalar(db.select(Learner).filter_by(id=learner.id).with_for_update())
    if locked is None:
        raise ValueError(f"Learner {learner.id} no longer exists.")
    return locked


def record_lesson_completion(
    learner: Learner, lesson: Lesson, xp: int, *, correct_count: int, total_count: int,
    grant_xp_boost: bool = False,
) -> LessonCompletion:
    """Mark ``lesson`` finished for a learner already locked with `lock_learner`. Does not commit.

    Awards ``xp`` on first completion only, rolls the topic into ``completed_topic_ids`` once
    every lesson in it is done, and finds the next lesson (by id) in the topic. A first
    completion spends a waiting golden potion boost (``Learner.xp_boost_pending``) to double
    ``xp``, then stores a fresh one if ``grant_xp_boost``. A replay does neither, so a waiting
    boost is kept for the next lesson that earns XP.

    Returns:
        LessonCompletion: The response payload, and whether this finished the topic (analytics).
    """
    topic_lessons = db.session.scalars(
        db.select(Lesson).filter_by(topic_id=lesson.topic_id).order_by(Lesson.id)
    ).all()
    current_index = next((i for i, lsn in enumerate(topic_lessons) if lsn.id == lesson.id), -1)
    next_lesson: LessonRef | None = None
    if current_index != -1 and current_index < len(topic_lessons) - 1:
        next_obj = topic_lessons[current_index + 1]
        next_lesson = {"id": next_obj.id, "title": next_obj.title}

    completed_ids = list(learner.completed_lesson_ids or [])
    already_completed = lesson.id in completed_ids

    xp_earned, leveled_up_to = 0, None
    level_before = compute_level(learner.xp or 0)
    xp_boosted = boost_earned = False
    if not already_completed:
        if learner.xp_boost_pending:
            xp, xp_boosted = xp * 2, True
        learner.xp_boost_pending = boost_earned = grant_xp_boost
        xp_earned, leveled_up_to = apply_xp(learner, xp)
        completed_ids.append(lesson.id)
        learner.completed_lesson_ids = completed_ids

    topic_completed = all(lsn.id in completed_ids for lsn in topic_lessons)
    if topic_completed:
        completed_topic_ids = list(learner.completed_topic_ids or [])
        if lesson.topic_id not in completed_topic_ids:
            completed_topic_ids.append(lesson.topic_id)
            learner.completed_topic_ids = completed_topic_ids

    new_level = compute_level(learner.xp or 0)
    payload = CompletionPayload(
        status="success",
        lesson={"id": lesson.id, "title": lesson.title},
        xp_earned=xp_earned,
        total_xp=learner.xp or 0,
        already_completed=already_completed,
        next_lesson=next_lesson,
        is_last=next_lesson is None,
        leveled_up=leveled_up_to is not None,
        new_level=new_level,
        level_name=level_name(new_level),
        new_items_unlocked=items_unlocked_between(level_before, new_level) if leveled_up_to else [],
        xp_boosted=xp_boosted,
        boost_earned=boost_earned,
        correct_count=correct_count,
        total_count=total_count,
    )
    return LessonCompletion(payload, topic_completed)
