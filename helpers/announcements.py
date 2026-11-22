"""Feature announcement popups — source-file sync and per-user targeting.

The content folder's `announcements.json` (helpers/content_source.py) is the
source: `flask release` syncs it into `feature_announcements` at each deploy
and the dev server syncs the sample copy at startup. See
`docs/ui-design/page-behaviour.md` for the popup itself.
"""

import json
import logging
import os
from typing import Any

from extensions import db

__all__ = ["get_pending_announcement", "sync_announcements"]
from helpers.analytics import capture_event
from models import FeatureAnnouncement

logger = logging.getLogger(__name__)

SOURCE_FILENAME = "announcements.json"


def sync_announcements(source_path: str) -> list[str]:
    """Insert any announcement in the source file whose uid is not yet in the DB.

    Args:
        source_path (str): The source JSON, normally `announcements.json` in the staged content folder;
            a missing file inserts nothing.

    Returns:
        list[str]: uids of the announcements inserted.
    """
    path = source_path
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    known = set(db.session.scalars(db.select(FeatureAnnouncement.uid)).all())

    inserted = []
    for entry in entries:
        uid = entry.get("uid")
        # Insert-only. An existing row may have been edited after import, and
        # the file is only ever the seed copy — never let a boot clobber it.
        if not uid or uid in known:
            continue
        db.session.add(FeatureAnnouncement(uid=uid, content=entry))
        inserted.append(uid)

    if inserted:
        db.session.commit()
        logger.info("Feature announcements inserted: %s", ", ".join(inserted))
    return inserted


def get_pending_announcement(user: Any) -> FeatureAnnouncement | None:
    """The newest announcement targeted at `user`'s role, or None. Newest-only: dismissing one clears every older one too.

    Args:
        user (Any): The current user (or None/anonymous).

    Returns:
        FeatureAnnouncement | None: The announcement to show, or None.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    role = getattr(user, "user_type", None)
    if not role:
        return None

    high_water = user.last_seen_announcement_id or 0
    # Role membership is matched in Python, not SQL — `content` is a JSON blob
    # and the "is this string in that array" operators differ between SQLite
    # (dev) and Postgres (prod). The table holds a handful of rows, so the
    # ordered scan below costs nothing.
    candidates = db.session.scalars(
        db.select(FeatureAnnouncement)
        .where(FeatureAnnouncement.id > high_water)
        .order_by(FeatureAnnouncement.id.desc())
    ).all()
    for announcement in candidates:
        if role in (announcement.content or {}).get("roles", []):
            # Impression, captured here rather than in each dashboard route so
            # the count can never drift from what was actually rendered.
            capture_event(
                str(user.id),
                "announcement_shown",
                properties={"announcement_uid": announcement.uid, "role": role},
            )
            return announcement
    return None
