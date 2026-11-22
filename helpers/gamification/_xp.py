from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from models import Learner

#: XP a level spans; level = xp // XP_PER_LEVEL + 1, capped at the last level name.
XP_PER_LEVEL = 500

LEVEL_MULTIPLIERS = {1: 1.0, 2: 1.1, 3: 1.2, 4: 1.3, 5: 1.5, 6: 1.7, 7: 2.0}

LEVEL_NAMES = ['Rookie', 'Explorer', 'Navigator', 'Pioneer', 'Astronaut', 'Commander', 'Legend']


def compute_level(xp: int) -> int:
    """Level for a given XP total.

    Args:
        xp (int): Total XP.

    Returns:
        int: Level, `min(7, (xp // XP_PER_LEVEL) + 1)`.
    """
    return min(len(LEVEL_NAMES), (xp // XP_PER_LEVEL) + 1)


def level_name(level: int) -> str:
    """Display name for a level.

    Args:
        level (int): Level number (1-7).

    Returns:
        str: Level name, e.g. "Rookie".
    """
    return LEVEL_NAMES[min(level - 1, len(LEVEL_NAMES) - 1)]


def apply_xp(learner: Learner, base_xp: int) -> tuple[int, int | None]:
    """Award XP with level multiplier.

    Args:
        learner (Learner): The learner to award XP to (mutated in place, not committed).
        base_xp (int): Base XP before the level multiplier.

    Returns:
        tuple[int, int | None]: `(xp_earned, new_level)` — `new_level` is None
            unless this award leveled the learner up.
    """
    current_xp = learner.xp or 0
    multiplier = LEVEL_MULTIPLIERS.get(compute_level(current_xp), 1.0)
    earned = round(base_xp * multiplier)
    old_level = compute_level(current_xp)
    learner.xp = current_xp + earned
    new_level = compute_level(learner.xp)
    leveled_up = new_level > old_level
    return earned, (new_level if leveled_up else None)


class LevelProgress(TypedDict):
    """Where a learner stands on the level bar — what the dashboard draws."""

    level: int
    name: str
    at_top: bool
    xp_in_level: int
    xp_left: int
    percent: float
    next_level: int
    next_name: str


def level_progress(xp: int) -> LevelProgress:
    """The level bar for an XP total. Past the last level the bar stays full and nothing is next.

    Args:
        xp (int): Total XP.

    Returns:
        LevelProgress: The level, its name, XP into and left in it, and the next level.
    """
    level = compute_level(xp)
    at_top = level >= len(LEVEL_NAMES)
    xp_in_level = XP_PER_LEVEL if at_top else xp % XP_PER_LEVEL
    return LevelProgress(
        level=level,
        name=level_name(level),
        at_top=at_top,
        xp_in_level=xp_in_level,
        xp_left=XP_PER_LEVEL - xp_in_level,
        percent=xp_in_level / XP_PER_LEVEL * 100,
        next_level=level + 1,
        next_name="" if at_top else LEVEL_NAMES[level],
    )
