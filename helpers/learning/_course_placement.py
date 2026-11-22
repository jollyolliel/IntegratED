"""Placement bands: which course and starting topic a placement level points at.

Pure rules over already-loaded rows — the snapshot (`_snapshot.py`) supplies them once per request.
A course sits on a placement scale with a band of levels (`placement_min_level`..`placement_max_level`);
a learner's level on that scale picks the course whose band holds it, and the first topic at the
highest topic level at or below it.
"""

from collections.abc import Sequence
from typing import Any

from models import Subject, Topic

__all__ = ["assessed_level", "course_for_level", "courses_by_scale", "placed_course", "starting_topic"]


def courses_by_scale(subjects: Sequence[Subject]) -> dict[str, list[Subject]]:
    """Group banded courses under the name of the placement scale they sit on."""
    by_id = {s.id: s for s in subjects}
    grouped: dict[str, list[Subject]] = {}
    for subject in subjects:
        scale = by_id.get(subject.placement_scale_id) if subject.placement_scale_id else None
        if scale is not None:
            grouped.setdefault(scale.name, []).append(subject)
    return grouped


def assessed_level(raw: Any) -> int:
    """A stored placement level as an int; anything unreadable counts as level 1."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def course_for_level(courses: Sequence[Subject], level: int) -> Subject | None:
    """The banded course whose band holds ``level``, clamped to the lowest or
    highest band when the level is outside them all.

    Args:
        courses (Sequence[Subject]): Courses on one placement scale.
        level (int): The learner's level on that scale.

    Returns:
        Subject | None: The course, or None if there are no courses.
    """
    ordered = sorted(courses, key=lambda c: (c.placement_min_level or 0, c.id))
    if not ordered:
        return None
    for course in ordered:
        if (course.placement_min_level or 0) <= level <= (course.placement_max_level or 0):
            return course
    # Outside every band (or in a gap the importer would have refused): the
    # highest band starting at or below the level, else the lowest band.
    below = [c for c in ordered if (c.placement_min_level or 0) <= level]
    return below[-1] if below else ordered[0]


def placed_course(scale: Subject | None, level: int, courses_on_scale: Sequence[Subject]) -> Subject | None:
    """The course a placement result points at: the banded course for the level
    when courses sit on this scale, else the subject itself if it is a course.

    Args:
        scale (Subject | None): The subject named by a `subject_levels` key.
        level (int): The assessed level.
        courses_on_scale (Sequence[Subject]): Courses banded on that subject.

    Returns:
        Subject | None: The course, or None (unknown name, or a placement-only
            scale with no courses on it).
    """
    if courses_on_scale:
        return course_for_level(courses_on_scale, level)
    if scale is not None and not scale.map_test_only:
        return scale
    return None


def starting_topic(topics: Sequence[Topic], level: int) -> Topic:
    """The first topic of the highest topic level at or below ``level`` —
    the first topic overall when every topic is above it.

    Args:
        topics (Sequence[Topic]): One course's topics, ordered by (level, id).
        level (int): The assessed level.

    Returns:
        Topic: The starting topic.
    """
    eligible = [t.level for t in topics if t.level <= level]
    if not eligible:
        return topics[0]
    target_level = max(eligible)
    return next(t for t in topics if t.level == target_level)
