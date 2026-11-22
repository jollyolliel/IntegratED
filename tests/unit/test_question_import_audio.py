"""`import_questions` records which questions are spoken and never calls ElevenLabs on its own;
`generate_spoken_audio` makes the audio ahead so the first learner does not wait for it. A second import of
an unchanged file writes nothing — what `flask release` relies on.

Every test writes its own small curriculum to a temp file.
"""

import json
import os

import pytest
from sqlalchemy import event, select

from extensions import db
from helpers import eleven_labs
from settings import DEFAULT_ELEVEN_VOICE_ID, Settings
from tests.support.storage import FakeBucket

pytestmark = pytest.mark.unit


def _mc(text, **extra):
    return {"content_type": "multiple_choice", "question_prompt": "Choose", "question_text": text,
            "options": ["cat", "dog"], "answer": "cat", **extra}


def _curriculum(questions=None, placement=None):
    return [
        {"name": "Map Test", "questions": placement or [
            {"subject_name": "English", "level": 1, **_mc("Tap the cat")},
        ]},
        {"name": "English: First Steps", "icon": "book", "description": "First steps",
         "placement": {"scale": "English", "min_level": 1, "max_level": 1},
         "topics": [{"title": "Sounds", "icon": "star", "description": "Sounds", "overview_markdown": "# Sounds",
                     "level": 1, "lessons": [{"title": "Animals", "icon": "leaf", "description": "Animals",
                                              "game_type": None,
                                              "questions": questions or [_mc("Which is the cat?")]}]}]},
    ]


class _ContentFile:
    """Call with a curriculum to (re)write the file; `path` is what the importer reads."""

    def __init__(self, source, storage=None):
        self.source = source
        self.path = str(source)
        self.storage = storage

    def __call__(self, data):
        self.source.write_text(json.dumps(data), encoding="utf-8")
        if self.storage is not None:
            self.storage.write_key("content/questions.json", json.dumps(data))
        return data


@pytest.fixture
def content_file(tmp_path, monkeypatch):

    source = tmp_path / "questions.json"

    return _ContentFile(source)


@pytest.fixture
def audio_storage(monkeypatch):
    """Empty audio storage, with ElevenLabs wired to fail loudly if called."""

    storage = FakeBucket()
    monkeypatch.setattr(eleven_labs, "get_bucket", lambda: storage)

    def no_api(*args, **kwargs):
        raise AssertionError("ElevenLabs must not be called")

    monkeypatch.setattr(eleven_labs, "_synthesize", no_api)
    monkeypatch.delenv("ELEVEN_API_KEY", raising=False)
    return storage


def _name(text):
    return eleven_labs.audio_filename(text, DEFAULT_ELEVEN_VOICE_ID)


def _question(db_session, text):
    from models import Question

    return db_session.scalar(select(Question).filter_by(question_text=text))


def _map_question(db_session, text):
    from models import MapQuestion

    return db_session.scalar(select(MapQuestion).filter_by(question_text=text))


# ── what is spoken ───────────────────────────────────────────────────────────


def test_a_lesson_question_records_that_it_is_spoken_and_nothing_is_generated(db_session, content_file, audio_storage):
    from helpers.content import import_questions

    content_file(_curriculum([_mc("Which is the cat?", question_sound=True, option_sound=True)]))

    import_questions(db, content_file.path)

    question = _question(db_session, "Which is the cat?")
    assert question.question_sound is True
    assert question.option_sound is True
    assert audio_storage.under("audio/") == {}


def test_a_question_not_marked_for_sound_is_not_spoken(db_session, content_file, audio_storage):
    from helpers.content import import_questions

    content_file(_curriculum([_mc("Which is the cat?")]))

    import_questions(db, content_file.path)

    question = _question(db_session, "Which is the cat?")
    assert not question.question_sound
    assert not question.option_sound


def test_a_placement_question_records_its_sound_and_audio_only_flags(db_session, content_file, audio_storage):
    from helpers.content import import_questions

    content_file(_curriculum(placement=[
        {"subject_name": "English", "level": 1, **_mc("Tap the cat", question_sound=True, audio_only=True)},
        {"subject_name": "English", "level": 1, **_mc("Tap the dog", question_sound=True)},
    ]))

    import_questions(db, content_file.path)

    cat = _map_question(db_session, "Tap the cat")
    assert (cat.question_sound, cat.audio_only) == (True, True)
    assert not _map_question(db_session, "Tap the dog").audio_only


# ── generating ahead of time ─────────────────────────────────────────────────


def test_generating_ahead_makes_every_spoken_text(db_session, content_file, monkeypatch):
    from helpers.audio_cache import generate_spoken_audio
    from helpers.content import import_questions

    storage = FakeBucket()
    monkeypatch.setattr(eleven_labs, "get_bucket", lambda: storage)
    monkeypatch.setattr(eleven_labs, "_synthesize", lambda text, voice_id: b"ID3" + text.encode())
    monkeypatch.setattr(
        eleven_labs, "get_settings", lambda: Settings.from_env({**os.environ, "APP_ENV": "development", "TTS_ENABLED": "true"})
    )
    content_file(_curriculum(
        [_mc("Which is the cat?", question_sound=True, option_sound=True), _mc("Silent question")],
        placement=[{"subject_name": "English", "level": 1, **_mc("Tap the cat", question_sound=True)}],
    ))
    import_questions(db, content_file.path)

    assert generate_spoken_audio() == (4, 4)
    assert set(storage.under("audio/")) == {_name(text) for text in ("Which is the cat?", "cat", "dog", "Tap the cat")}


def test_importing_never_generates_audio(db_session, content_file, audio_storage):
    from helpers.content import import_questions

    content_file(_curriculum([_mc("Which is the cat?", question_sound=True)]))

    import_questions(db, content_file.path)

    assert audio_storage.under("audio/") == {}


def test_generating_ahead_does_not_regenerate_a_file_that_exists(db_session, content_file, monkeypatch):
    from helpers.audio_cache import generate_spoken_audio
    from helpers.content import import_questions

    storage = FakeBucket()
    storage.write_key("audio/" + _name("Which is the cat?"), b"ID3old")
    monkeypatch.setattr(eleven_labs, "get_bucket", lambda: storage)

    def no_api(*args, **kwargs):
        raise AssertionError("ElevenLabs must not be called")

    monkeypatch.setattr(eleven_labs, "_synthesize", no_api)
    content_file(_curriculum([_mc("Which is the cat?", question_sound=True)]))
    import_questions(db, content_file.path)

    generate_spoken_audio()

    assert storage.under("audio/")[_name("Which is the cat?")] == b"ID3old"


# ── an unchanged file writes nothing ─────────────────────────────────────────


@pytest.fixture
def writes(db_session):
    """Every INSERT, UPDATE or DELETE the database sees while the test runs."""

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            statements.append(statement)

    engine = db.engine
    event.listen(engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine, "before_cursor_execute", record)


def test_a_second_import_of_the_same_file_writes_nothing(db_session, content_file, audio_storage, writes):
    from helpers.content import import_questions

    group = {"content_type": "text_group", "context_text": "A cat sat.", "questions": [
        _mc("Who sat?"), _mc("Where?", question_sound=True),
    ]}
    match = {"content_type": "match", "question_prompt": "Match",
             "match_pairs": [{"left": "cat", "right": "a"}, {"left": "dog", "right": "b"}]}
    content_file(_curriculum(
        [_mc("Which is the cat?", question_sound=True, option_sound=True), group, match],
        placement=[{"subject_name": "English", "level": 1, **_mc("Tap the cat", question_sound=True)}],
    ))
    import_questions(db, content_file.path, prune=True)
    assert writes, "the first import should have written the content"

    writes.clear()
    import_questions(db, content_file.path, prune=True)

    assert writes == []
