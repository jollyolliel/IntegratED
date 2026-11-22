"""The development seed: what a fresh dev database and dev bucket are filled with.

`seed/seed.toml` says which schools, users, articles, team members and site text to create.
`seed/files/` mirrors the bucket (`content/` for questions, worksheets and announcements,
`worksheets/` for PDFs) and is copied in while the dev bucket is empty. Content is then read
from the bucket's `content/` exactly as production reads it (helpers/content_source.py).
Rows from `seed.toml` are insert-only on a natural key, so running it again never duplicates
a row or overwrites an edit. Nothing here runs outside development, and nothing outside this
package reads `seed/`.

Layout:
  _config.py  load_config / validate: the pure TOML side
  _apply.py   apply_config and one apply_* per section
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from extensions import db
from helpers.seed._apply import SeedCounts, apply_config
from helpers.seed._config import (
    CONFIG_PATH,
    EMPTY_CONFIG,
    FILES_DIR,
    SeedConfig,
    SeedError,
    load_config,
)
from settings import get_settings

if TYPE_CHECKING:
    from helpers.storage import Bucket

__all__ = [
    "CONFIG_PATH",
    "EMPTY_CONFIG",
    "FILES_DIR",
    "SeedConfig",
    "SeedCounts",
    "SeedError",
    "apply_config",
    "database_is_empty",
    "load_config",
    "seed_content",
    "seed_development",
]


def database_is_empty() -> bool:
    """Whether the database has no school and no user yet (a brand-new dev database)."""
    from models import School, User

    return not db.session.scalar(db.select(db.func.count()).select_from(School)) and not db.session.scalar(
        db.select(db.func.count()).select_from(User)
    )


def seed_content(storage: Bucket) -> None:
    """Import the bucket's sample questions, worksheets and announcements; each step skips what exists.

    Best-effort: a failing step is reported and the dev server still starts.

    Args:
        storage (Bucket): The dev bucket, already filled from `seed/files/`.
    """
    from helpers.announcements import sync_announcements
    from helpers.content import import_questions
    from helpers.content_source import ContentSourceError, staged_content
    from helpers.worksheet_manifest import sync_worksheet_manifest
    from models import Subject

    try:
        with staged_content(storage) as folder:
            if db.session.scalar(db.select(db.func.count()).select_from(Subject)) == 0:
                try:
                    import_questions(db, os.path.join(folder, "questions.json"))
                    print(" * Questions imported.")
                except Exception as error:  # noqa: BLE001 - dev-only best-effort seeding, any failure here must not stop the app from starting
                    print(f" * Question import skipped: {error}")
            try:
                synced = sync_worksheet_manifest(storage, os.path.join(folder, "worksheets"))
                if synced.added or synced.updated:
                    print(f" * Worksheet manifest: {synced.added} added, {synced.updated} updated.")
            except Exception as error:  # noqa: BLE001 - dev-only best-effort seeding, a bad manifest must not stop the app from starting
                db.session.rollback()
                print(f" * Worksheet manifest sync skipped: {error}")
            try:
                sync_announcements(os.path.join(folder, "announcements.json"))
            except Exception as error:  # noqa: BLE001 - dev-only best-effort seeding, any failure here must not stop the app from starting
                db.session.rollback()
                print(f" * Feature announcement sync skipped: {error}")
    except ContentSourceError:
        print(" * The dev bucket has no content/: delete instance/bucket/ to refill it from seed/files/.")


def seed_development(*, force: bool = False) -> SeedCounts | None:
    """Fill the dev bucket and database from `seed/`; `force` applies `seed.toml` even to a non-empty database.

    Returns:
        SeedCounts | None: Rows created from `seed.toml`, or None when it was skipped.

    Raises:
        SeedError: `seed.toml` is invalid, or the app is not running in development.
    """
    from helpers.storage import LocalBucket, get_bucket

    env = get_settings().env
    if not get_settings().is_development:
        raise SeedError(f"Seeding is for development; APP_ENV is {env}, so nothing was written.")
    storage = get_bucket()
    if isinstance(storage, LocalBucket):
        storage.seed_from(FILES_DIR)
    seed_content(storage)
    if force or database_is_empty():
        return apply_config(load_config(), storage=storage)
    return None
