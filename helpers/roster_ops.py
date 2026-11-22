"""The delete cascade for a person — shared by every surface that may delete
one (teacher, school_admin, administrator, the person themself).

A learner and a volunteer are both deletable from three surfaces with three
different ownership checks (teacher_id / school_id / unscoped-admin). The
cascade itself — what "delete this person" means — is one invariant, not
three: unmatch, drop the person's own records, keep their partner's record
with `partner_id` nulled rather than orphaned or deleted, clear worksheet
assignments, wipe learning progress. `delete_user` takes the row the caller
already scoped, runs the whole cascade for its role and commits once — or rolls
the whole of it back. It reads no request state, so any caller — a route or a
CLI command — gets the identical cascade.
"""

from collections.abc import Callable
from typing import Any

from extensions import db
from models import (
    Administrator,
    Article,
    AssistantChange,
    AssistantConversation,
    AssistantMessage,
    Attendance,
    Learner,
    LearningSession,
    SchoolAdmin,
    Teacher,
    User,
    Volunteer,
    WorksheetAssignment,
)

__all__ = ["LastAdministratorError", "delete_user"]


class LastAdministratorError(ValueError):
    """Deleting this administrator would leave none; nothing was changed."""


def _clear_learner(learner: Learner) -> None:
    learner.unmatch()
    db.session.execute(db.delete(Attendance).where(Attendance.user_id == learner.id))
    # A volunteer's own row that named this learner as partner survives,
    # partner_id nulled so it no longer points at a row about to be gone.
    db.session.execute(
        db.update(Attendance).where(Attendance.partner_id == learner.id).values(partner_id=None)
    )
    # Worksheet assignments and learning sessions are theirs alone, dropped outright.
    db.session.execute(db.delete(WorksheetAssignment).where(WorksheetAssignment.learner_id == learner.id))
    db.session.execute(db.delete(LearningSession).where(LearningSession.learner_id == learner.id))
    # Cleared for symmetry with the row being gone — a re-created account with
    # the same username should not resume with someone else's progress.
    learner.completed_lesson_ids = []
    learner.completed_topic_ids = []


def _clear_volunteer(volunteer: Volunteer) -> None:
    volunteer.release_learners()
    db.session.execute(db.delete(Attendance).where(Attendance.user_id == volunteer.id))
    # A learner's own row that named this volunteer as partner survives, partner_id nulled.
    db.session.execute(
        db.update(Attendance).where(Attendance.partner_id == volunteer.id).values(partner_id=None)
    )
    # An assignment names both sides — deleting a volunteer only clears who
    # handed the worksheet out, not the learner's assignment itself.
    db.session.execute(
        db.update(WorksheetAssignment)
        .where(WorksheetAssignment.volunteer_id == volunteer.id)
        .values(volunteer_id=None)
    )


def _clear_teacher(teacher: Teacher) -> None:
    # Roster, attendance and assignments stay with teacher_id nulled: a volunteer's hours are
    # summed live from attendance, and an unassigned learner/volunteer is claimed by the next
    # same-school teacher. Assistant history is theirs alone and goes.
    for model in (Learner, Volunteer, Attendance, WorksheetAssignment):
        db.session.execute(db.update(model).where(model.teacher_id == teacher.id).values(teacher_id=None))
    conversation_ids = db.select(AssistantConversation.id).where(AssistantConversation.teacher_id == teacher.id)
    # Changes first: they point at conversations and at each other (depends_on_id).
    db.session.execute(db.update(AssistantChange).where(AssistantChange.teacher_id == teacher.id).values(depends_on_id=None))
    db.session.execute(db.delete(AssistantChange).where(AssistantChange.teacher_id == teacher.id))
    db.session.execute(db.delete(AssistantMessage).where(AssistantMessage.conversation_id.in_(conversation_ids)))
    db.session.execute(db.delete(AssistantConversation).where(AssistantConversation.teacher_id == teacher.id))


def _clear_administrator(admin: Administrator, heir: Administrator | None) -> None:
    # Only administrators write articles, so one leaving hands them to another: `heir`, else
    # the longest-serving other administrator. There must always be one left.
    if heir is None:
        heir = db.session.scalar(
            db.select(Administrator).where(Administrator.id != admin.id).order_by(Administrator.id)
        )
    if heir is None:
        raise LastAdministratorError("Cannot delete the last administrator account.")
    if heir.id == admin.id:
        raise ValueError("An administrator cannot hand their articles to themself.")
    db.session.execute(db.update(Article).where(Article.author_id == admin.id).values(author_id=heir.id))


def delete_user(user: User, *, heir: Administrator | None = None) -> None:
    """Delete a person and everything that belongs to only them, in one transaction.

    Args:
        user (User): The person to delete. The caller owns the ownership check.
        heir (Administrator | None): For an administrator, who now authors their articles;
            the longest-serving other administrator when omitted. Other roles have no articles.

    Raises:
        LastAdministratorError: `user` is the only administrator; nothing was changed.
        ValueError: An administrator was named as their own heir; nothing was changed.
        TypeError: `user` is a role with no delete cascade here; nothing was changed.
    """
    # What deleting each role takes with it, beyond the row itself. A school admin owns nothing else.
    cascades: dict[type, Callable[[Any], None]] = {
        Learner: _clear_learner,
        Volunteer: _clear_volunteer,
        Teacher: _clear_teacher,
        Administrator: lambda admin: _clear_administrator(admin, heir),
        SchoolAdmin: lambda _admin: None,
    }
    clear = cascades.get(type(user))
    if clear is None:
        raise TypeError(f"No delete cascade for {type(user).__name__} ({user.user_type!r}).")
    try:
        clear(user)
        db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
