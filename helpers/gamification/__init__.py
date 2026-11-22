"""Single source of truth for all XP/level/Face System data.

Layout:
  _xp.py         LEVEL_MULTIPLIERS/LEVEL_NAMES, compute_level, level_name, apply_xp, level_progress
  _face.py       the Face System avatar (FACE_ITEMS, FACE_UNLOCK_LEVEL, resolve_face,
                 items_unlocked_between) — ADR 0017

XP per lesson type lives in `GAMES` (helpers/learning/_games.py).
"""

from helpers.gamification._face import (  # noqa: F401
    _FACE_ID_TO_TYPE,
    DEFAULT_FACE,
    FACE_CATEGORIES,
    FACE_ID_SET,
    FACE_ITEMS,
    FACE_LAYER_ORDER,
    FACE_REQUIRED_SLOTS,
    FACE_UNLOCK_LEVEL,
    FaceEquipped,
    UnlockedItem,
    get_face_item_type,
    items_unlocked_between,
    resolve_face,
)
from helpers.gamification._xp import (  # noqa: F401
    LEVEL_MULTIPLIERS,
    LEVEL_NAMES,
    XP_PER_LEVEL,
    LevelProgress,
    apply_xp,
    compute_level,
    level_name,
    level_progress,
)
