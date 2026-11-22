"""The programme's public numbers, for the whole programme or one school: the one place the landing,
About, Donations and school pages count them."""

from __future__ import annotations

from typing import TypedDict

from extensions import db

__all__ = ["ProgrammeStats", "programme_stats"]


class ProgrammeStats(TypedDict):
    """Counts for the public pages; `hours` is rounded to one decimal and `raised` is in whole units."""

    learners: int
    volunteers: int
    pairs: int
    hours: float
    schools: int
    raised: float


def programme_stats(school_id: int | None = None) -> ProgrammeStats:
    """Learners, volunteers, matched pairs, session hours, partner schools and money raised.

    Args:
        school_id (int | None): Count only this school's; the whole programme when None.

    Returns:
        ProgrammeStats: The counts (`schools` is 1 for a single school).
    """
    from models import Attendance, Donation, Learner, School, Volunteer

    def count(model, *where) -> int:
        stmt = db.select(db.func.count()).select_from(model)
        if school_id is not None:
            stmt = stmt.where(model.school_id == school_id)
        return db.session.scalar(stmt.where(*where)) or 0

    learner_ids = None
    if school_id is not None:
        learner_ids = db.session.scalars(db.select(Learner.id).where(Learner.school_id == school_id)).all()
    raised = db.select(db.func.coalesce(db.func.sum(Donation.amount), 0))
    if school_id is not None:
        raised = raised.where(Donation.school_id == school_id)
    return ProgrammeStats(
        learners=count(Learner),
        volunteers=count(Volunteer),
        pairs=count(Learner, Learner.volunteer_id.isnot(None)),
        hours=round(Attendance.programme_hours(learner_ids), 1),
        schools=1 if school_id is not None else count(School),
        raised=(db.session.scalar(raised) or 0) / 100,
    )
