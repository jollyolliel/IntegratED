"""Bring the worksheet library in line with the content folder's `worksheets/manifest.json`: one Worksheet
row per entry, upserted on `storage.key_for(file)` (new rows inserted, changed fields updated), never
deleted (docs/features/worksheets.md)."""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from extensions import db
from helpers.problems import ProblemsError
from helpers.utils import one_line
from helpers.worksheet_library import (
    MAX_TAG_LENGTH,
    MAX_TAGS,
    WORKSHEET_LEVELS,
    normalize_tags,
)
from models import Worksheet

if TYPE_CHECKING:
    from helpers.storage import Bucket

logger = logging.getLogger(__name__)

__all__ = ["ManifestError", "ManifestSync", "read_manifest", "sync_worksheet_manifest"]

MANIFEST_NAME = "manifest.json"
_EXTENSIONS = (".pdf", ".md")
# The Worksheet columns' lengths: Postgres enforces them, SQLite doesn't.
_TITLE_LENGTH, _SUBJECT_LENGTH, _TOPIC_LENGTH = 255, 100, 100


class ManifestError(ProblemsError):
    """The manifest breaks its format; nothing was written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"worksheets/{MANIFEST_NAME}", problems)


@dataclass
class ManifestSync:
    """What one sync did. `skipped` lists entries whose file isn't there yet."""

    added: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)
    found: bool = True


def _check_text(entry: dict[str, Any], key: str, limit: int, where: str, problems: list[str], *,
                required: bool) -> None:
    value = entry.get(key)
    if value is None or value == "":
        if required:
            problems.append(f"{where}: '{key}' is required")
        return
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: '{key}' must be text")
    elif len(value) > limit:
        problems.append(f"{where}: '{key}' is longer than {limit} characters")


def _check_entry(entry: Any, index: int, problems: list[str]) -> None:
    where = f"entry {index + 1}"
    if not isinstance(entry, dict):
        problems.append(f"{where}: must be an object")
        return
    name = entry.get("file")
    if not isinstance(name, str) or not name:
        problems.append(f"{where}: 'file' is required")
    else:
        where = f"entry {index + 1} ({name})"
        if os.path.basename(name) != name or "/" in name or "\\" in name or name.startswith("."):
            problems.append(f"{where}: 'file' must be a bare filename inside worksheets/")
        elif not name.lower().endswith(_EXTENSIONS):
            problems.append(f"{where}: 'file' must be a .pdf or .md")
    _check_text(entry, "title", _TITLE_LENGTH, where, problems, required=True)
    _check_text(entry, "subject", _SUBJECT_LENGTH, where, problems, required=True)
    _check_text(entry, "topic", _TOPIC_LENGTH, where, problems, required=False)
    level = entry.get("level")
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or level not in WORKSHEET_LEVELS):
        problems.append(f"{where}: 'level' must be a whole number from {WORKSHEET_LEVELS.start} "
                        f"to {WORKSHEET_LEVELS.stop - 1}")
    tags = entry.get("tags")
    if tags is None:
        return
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        problems.append(f"{where}: 'tags' must be a list of text")
    elif any(len(tag.strip()) > MAX_TAG_LENGTH for tag in tags):
        problems.append(f"{where}: a tag is longer than {MAX_TAG_LENGTH} characters")
    elif len(normalize_tags(tags)) > MAX_TAGS:
        problems.append(f"{where}: more than {MAX_TAGS} tags")


def _validate(data: Any) -> list[str]:
    if not isinstance(data, list):
        return ["the manifest must be a JSON list of entries"]
    problems: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(data):
        _check_entry(entry, index, problems)
        name = entry.get("file") if isinstance(entry, dict) else None
        if isinstance(name, str):
            if name.lower() in seen:
                problems.append(f"entry {index + 1} ({name}): listed more than once")
            seen.add(name.lower())
    return problems


def _fields(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": entry["title"].strip(),
        "subject": entry["subject"].strip(),
        "topic": (entry.get("topic") or "").strip() or None,
        "level": entry.get("level"),
        "tags": normalize_tags(entry.get("tags") or []),
    }


def _read_markdown(directory: str, name: str) -> str | None:
    """The text of `name` in `directory`, or None when it isn't there or would lie outside it."""
    # `_check_entry` already refuses anything but a bare filename; this guards the read itself.
    root = os.path.realpath(directory)
    path = os.path.realpath(os.path.join(root, name))
    if not path.startswith(root + os.sep):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_manifest(directory: str) -> list[dict[str, Any]] | None:
    """The validated manifest in `directory`, or None when there is none.

    Args:
        directory (str): The staged content folder's `worksheets/`.

    Returns:
        list[dict[str, Any]] | None: The manifest's entries.

    Raises:
        ManifestError: The manifest can't be read or breaks its format.
    """
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError([f"could not be read: {error}"]) from error
    problems = _validate(data)
    if problems:
        raise ManifestError(problems)
    return data


def sync_worksheet_manifest(storage: Bucket, directory: str) -> ManifestSync:
    """Upsert one Worksheet per manifest entry; a missing manifest changes nothing.

    PDF rows are keyed on `storage.key_for(file)`, the key a storage upload uses;
    a new one needs the file in storage. Markdown rows use the same key and store
    the file's text in `content`.

    Args:
        storage (Bucket): The app's storage, where the PDFs live.
        directory (str): The staged content folder's `worksheets/`, holding the manifest and markdown files.

    Returns:
        ManifestSync: Rows added and updated, and entries skipped.

    Raises:
        ManifestError: The manifest is malformed; nothing was written.
    """
    data = read_manifest(directory)
    if data is None:
        return ManifestSync(found=False)

    result = ManifestSync()
    for entry in data:
        name = entry["file"]
        key = storage.key_for(name)
        is_pdf = name.lower().endswith(".pdf")
        fields = _fields(entry)
        if not is_pdf:
            content = _read_markdown(directory, name)
            if content is None:
                logger.warning("Worksheet manifest: skipped %s — the file isn't in the content folder's worksheets/.",
                               one_line(name))
                result.skipped.append(name)
                continue
            fields["content"] = content

        row = db.session.scalar(db.select(Worksheet).filter_by(filepath=key))
        if row is None:
            if is_pdf and not storage.exists(key):
                logger.warning("Worksheet manifest: skipped %s — not in worksheet storage yet.", one_line(name))
                result.skipped.append(name)
                continue
            db.session.add(Worksheet(filepath=key, file_type="pdf" if is_pdf else "md", **fields))
            result.added += 1
            continue
        changed = {column: value for column, value in fields.items() if getattr(row, column) != value}
        if changed:
            for column, value in changed.items():
                setattr(row, column, value)
            result.updated += 1

    if result.added or result.updated:
        db.session.commit()
    return result
