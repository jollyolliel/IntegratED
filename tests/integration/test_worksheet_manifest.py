"""`sync_worksheet_manifest`: one Worksheet row per `worksheets/manifest.json` entry in the content folder.

Each test writes its own manifest and files into a temp directory and uses the
in-memory storage double, so the real content folder is never read.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from tests.support.storage import FakeBucket

pytestmark = pytest.mark.integration


def _entry(file="01_the.pdf", **fields):
    return {"file": file, "title": "The", "subject": "English: Reading Start", "topic": "Sight words",
            "level": 2, "tags": ["sight-words", "reading"], **fields}


@pytest.fixture
def shipped(tmp_path):
    """The directory the manifest ships in; call it with the entries (and md files) to write."""

    def write(entries, **markdown):
        (tmp_path / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
        for name, text in markdown.items():
            (tmp_path / name.replace("__", ".")).write_text(text, encoding="utf-8")
        return tmp_path

    return write


@pytest.fixture
def storage():
    return FakeBucket()


def _sync(storage, directory):
    from helpers.worksheet_manifest import sync_worksheet_manifest

    return sync_worksheet_manifest(storage, directory=str(directory))


def _rows(db_session):
    from models import Worksheet

    return db_session.scalars(select(Worksheet).order_by(Worksheet.id)).all()


# ── PDFs ─────────────────────────────────────────────────────────────────────


def test_a_pdf_entry_adds_a_row_keyed_like_the_storage_upload(db_session, shipped, storage):
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry()])

    result = _sync(storage, directory)

    (row,) = _rows(db_session)
    assert (result.added, result.updated) == (1, 0)
    assert row.filepath == storage.key_for("01_the.pdf")
    assert (row.title, row.subject, row.topic, row.level, row.tags, row.file_type) == (
        "The", "English: Reading Start", "Sight words", 2, ["sight-words", "reading"], "pdf")


def test_a_pdf_row_already_there_is_updated_not_duplicated(db_session, shipped, storage):
    from models import Worksheet

    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    db_session.add(Worksheet(title="The", subject="Sight Words", filepath=storage.key_for("01_the.pdf"), file_type="pdf"))
    db_session.commit()
    directory = shipped([_entry(title="The (sight word)")])

    result = _sync(storage, directory)

    (row,) = _rows(db_session)
    assert (result.added, result.updated) == (0, 1)
    assert (row.title, row.subject, row.level) == ("The (sight word)", "English: Reading Start", 2)


def test_a_pdf_not_in_storage_yet_is_skipped_with_a_warning(db_session, shipped, storage, caplog):
    directory = shipped([_entry()])

    result = _sync(storage, directory)

    assert _rows(db_session) == []
    assert (result.added, result.updated) == (0, 0)
    assert result.skipped == ["01_the.pdf"]
    assert "01_the.pdf" in caplog.text


# ── markdown ─────────────────────────────────────────────────────────────────


def test_a_markdown_entry_stores_the_shipped_file_inline(db_session, shipped, storage):
    directory = shipped([_entry(file="greetings.md", title="Greetings")], greetings__md="# Hello\n")

    _sync(storage, directory)

    (row,) = _rows(db_session)
    assert (row.file_type, row.content, row.title) == ("md", "# Hello\n", "Greetings")
    assert row.filepath == storage.key_for("greetings.md")


def test_an_edited_markdown_file_updates_the_same_row(db_session, shipped, storage):
    directory = shipped([_entry(file="greetings.md")], greetings__md="# Hello\n")
    _sync(storage, directory)
    first_id = _rows(db_session)[0].id

    shipped([_entry(file="greetings.md", title="Greetings again")], greetings__md="# Hello again\n")
    result = _sync(storage, directory)

    (row,) = _rows(db_session)
    assert (result.added, result.updated) == (0, 1)
    assert (row.id, row.content, row.title) == (first_id, "# Hello again\n", "Greetings again")


def test_a_markdown_entry_whose_file_was_not_shipped_is_skipped(db_session, shipped, storage):
    directory = shipped([_entry(file="missing.md")])

    result = _sync(storage, directory)

    assert _rows(db_session) == []
    assert result.skipped == ["missing.md"]


# ── safety ───────────────────────────────────────────────────────────────────


def test_a_second_sync_of_the_same_manifest_changes_nothing(db_session, shipped, storage):
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry(), _entry(file="greetings.md", title="Greetings")], greetings__md="# Hi\n")
    _sync(storage, directory)

    result = _sync(storage, directory)

    assert (result.added, result.updated) == (0, 0)


def test_an_entry_dropped_from_the_manifest_keeps_its_row(db_session, shipped, storage):
    """Assignments point at worksheets, so the sync never deletes."""
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry()])
    _sync(storage, directory)

    shipped([])
    _sync(storage, directory)

    assert len(_rows(db_session)) == 1


def test_a_missing_manifest_changes_nothing_and_does_not_fail(db_session, tmp_path, storage):
    from models import Worksheet

    result = _sync(storage, tmp_path)

    assert result.found is False
    assert (result.added, result.updated) == (0, 0)
    assert db_session.scalar(select(func.count()).select_from(Worksheet)) == 0


def test_tags_are_stored_lowercase_without_duplicates(db_session, shipped, storage):
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry(tags=[" Sight-Words", "reading", "sight-words"])])

    _sync(storage, directory)

    assert _rows(db_session)[0].tags == ["sight-words", "reading"]


def test_an_entry_without_level_topic_or_tags_imports_with_them_empty(db_session, shipped, storage):
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([{"file": "01_the.pdf", "title": "The", "subject": "English: Reading Start"}])

    _sync(storage, directory)

    (row,) = _rows(db_session)
    assert (row.topic, row.level, row.tags) == (None, None, [])


@pytest.mark.parametrize("bad_entry", [
    _entry(file="../secrets.pdf"),
    _entry(file="sub/dir.pdf"),
    _entry(file="notes.txt"),
    _entry(title=""),
    _entry(subject=None),
    _entry(level=0),
    _entry(level="2"),
    _entry(level=True),
    _entry(tags="reading"),
    _entry(tags=["x" * 41]),
    "not an object",
])
def test_a_malformed_entry_fails_the_whole_sync_and_writes_nothing(db_session, shipped, storage, bad_entry):
    from helpers.worksheet_manifest import ManifestError

    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    storage.add_worksheet("02_and.pdf", b"%PDF-1.4")
    directory = shipped([_entry(file="02_and.pdf"), bad_entry])

    with pytest.raises(ManifestError):
        _sync(storage, directory)

    assert _rows(db_session) == []


def test_a_file_listed_twice_fails_the_sync(db_session, shipped, storage):
    from helpers.worksheet_manifest import ManifestError

    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry(), _entry(title="Again")])

    with pytest.raises(ManifestError, match="01_the.pdf"):
        _sync(storage, directory)


def test_a_manifest_that_is_not_a_json_list_fails_the_sync(db_session, tmp_path, storage):
    from helpers.worksheet_manifest import ManifestError

    (tmp_path / "manifest.json").write_text('{"file": "01_the.pdf"}', encoding="utf-8")

    with pytest.raises(ManifestError):
        _sync(storage, tmp_path)


# ── the command ──────────────────────────────────────────────────────────────


def test_the_sync_worksheets_command_reports_its_counts(app, db_session, shipped, storage, monkeypatch):
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    directory = shipped([_entry()])
    for path in directory.iterdir():
        storage.write_key(f"content/worksheets/{path.name}", path.read_bytes())
    storage.write_key("content/questions.json", "[]")
    monkeypatch.setitem(app.config, "BUCKET", storage)

    result = app.test_cli_runner().invoke(args=["sync-worksheets"])

    assert result.exit_code == 0, result.output
    assert "1 added, 0 updated" in result.output
