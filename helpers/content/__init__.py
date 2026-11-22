"""Loading the content folder's `questions.json` into the content tables: validate the whole file,
upsert it by natural key, and — only when asked — prune what the file no longer contains
(docs/learning/content.md is the authoring contract).

Layout:
  _schema.py    content types, `load_content`, and the natural keys rows are matched by
  _validate.py  `validate_content` and `ContentError`
  _upsert.py    `upsert`: insert or update every row, counting the question rows
  _prune.py     `plan_prune` / `apply_prune`: remove what the file dropped

Audio is not generated on import: it is made on first request, or ahead of time with
`helpers.audio_cache.generate_spoken_audio`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask_sqlalchemy import SQLAlchemy

from helpers.content import _prune
from helpers.content._prune import PrunePlan, plan_prune
from helpers.content._schema import (
    CHOICE_TYPES,
    CONTENT_TYPES,
    PLACEMENT_ENTRY,
    load_content,
)
from helpers.content._upsert import upsert
from helpers.content._validate import ContentError, validate_content

__all__ = [
    "CHOICE_TYPES",
    "CONTENT_TYPES",
    "PLACEMENT_ENTRY",
    "ContentError",
    "ImportResult",
    "PrunePlan",
    "import_content",
    "import_questions",
    "load_content",
    "plan_prune",
    "read_content",
    "validate_content",
]


@dataclass
class ImportResult:
    """What one import wrote: question rows inserted and changed, and the prune it applied."""

    added: int = 0
    updated: int = 0
    pruned: PrunePlan | None = None


def read_content(path: str) -> list[Any]:
    """Load `questions.json` and check it whole.

    Raises:
        ContentError: The file breaks the content contract.
        FileNotFoundError: There is no file at `path`.
    """
    data = load_content(path)
    problems = validate_content(data)
    if problems:
        raise ContentError(problems)
    return data


def import_content(db: SQLAlchemy, data: list[Any], *, prune: bool = False,
                   before_prune: Callable[[PrunePlan], None] | None = None) -> ImportResult:
    """Upsert content `read_content` returned; with ``prune``, also remove what it no longer
    contains — all in one transaction.

    Args:
        db (SQLAlchemy): The app's SQLAlchemy extension instance.
        data (list[Any]): Content already checked by `read_content`.
        prune (bool): When True, delete content missing from the file and clean
            up what pointed at it (see `plan_prune`).
        before_prune (Callable[[PrunePlan], None] | None): Called with the plan
            before it is applied, so it is reported even if applying fails.

    Returns:
        ImportResult: Question rows added and changed, and what was pruned when ``prune``.
    """
    try:
        counts = upsert(db, data)
        db.session.flush()
        result = ImportResult(added=counts.added, updated=counts.updated)
        if prune:
            result.pruned = plan_prune(db, data)
            if before_prune is not None:
                before_prune(result.pruned)
            _prune.apply_prune(db, result.pruned)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return result


def import_questions(db: SQLAlchemy, path: str, *, prune: bool = False,
                     before_prune: Callable[[PrunePlan], None] | None = None) -> ImportResult:
    """`read_content` then `import_content`: validate `questions.json` and import it.

    Raises:
        ContentError: The file breaks the content contract; nothing was written.
        FileNotFoundError: There is no file at `path`.
    """
    return import_content(db, read_content(path), prune=prune, before_prune=before_prune)
