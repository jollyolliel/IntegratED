"""`/audio/<file>`: a cache in front of ElevenLabs.

A stored file is served as it is. A missing one is generated, stored, then served, but only if
its text is on the list of spoken text: quiz questions with `question_sound`, their options with
`option_sound`, and placement questions with `question_sound`. Anything else is a 404 that never
reaches ElevenLabs, so nobody can have arbitrary text voiced.
"""

from __future__ import annotations

import os

import pytest

from helpers import audio_cache, eleven_labs
from settings import Settings
from tests.support.factories import (
    make_learning_content,
    make_map_question,
    make_question,
    make_subject,
)
from tests.support.storage import FakeBucket

pytestmark = pytest.mark.web


class _Synth:
    """Stands in for `eleven_labs._synthesize`: records each text it is asked to speak."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def __call__(self, text: str, voice_id: str) -> bytes:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("ElevenLabs is down")
        return b"ID3" + text.encode()


@pytest.fixture
def storage(app, monkeypatch):
    fake = FakeBucket()
    monkeypatch.setitem(app.config, "BUCKET", fake)
    audio_cache.reset()
    yield fake
    audio_cache.reset()


@pytest.fixture
def synth(monkeypatch):
    fake = _Synth()
    monkeypatch.setattr(eleven_labs, "_synthesize", fake)
    monkeypatch.setattr(
        eleven_labs, "get_settings", lambda: Settings.from_env({**os.environ, "APP_ENV": "development", "TTS_ENABLED": "true"})
    )
    return fake


def _spoken_question(db_session, text="Which is the cat?", **overrides):
    subject, topic, lesson, _first = make_learning_content(db_session)
    return make_question(db_session, subject, topic, lesson, question_text=text, **overrides)


def test_a_stored_file_is_served_without_generating(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=True)
    storage.write_key("audio/" + eleven_labs.audio_filename("Which is the cat?"), b"ID3stored")

    response = client.get(audio_cache.audio_url("Which is the cat?"))

    assert response.status_code == 200
    assert response.data == b"ID3stored"
    assert synth.calls == []


def test_a_missing_file_for_a_listed_question_is_generated_stored_and_served(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=True)
    url = audio_cache.audio_url("Which is the cat?")

    response = client.get(url)

    assert response.status_code == 200
    assert response.data == b"ID3Which is the cat?"
    assert storage.under("audio/")[eleven_labs.audio_filename("Which is the cat?")] == b"ID3Which is the cat?"

    client.get(url)

    assert synth.calls == ["Which is the cat?"]


def test_a_generated_file_is_cached_for_good_by_the_browser(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=True)

    response = client.get(audio_cache.audio_url("Which is the cat?"))

    assert "immutable" in response.headers["Cache-Control"]


def test_text_that_is_not_on_the_list_is_refused_and_never_voiced(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=True)

    response = client.get(audio_cache.audio_url("Say something else entirely"))

    assert response.status_code == 404
    assert synth.calls == []


def test_a_question_without_sound_enabled_is_not_voiced(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=False)

    response = client.get(audio_cache.audio_url("Which is the cat?"))

    assert response.status_code == 404
    assert synth.calls == []


def test_options_are_voiced_only_when_option_sound_is_on(client, db_session, storage, synth):
    _spoken_question(db_session, "First?", options=["cat", "dog"], option_sound=True)
    _spoken_question(db_session, "Second?", options=["fish", "bird"], option_sound=False)

    assert client.get(audio_cache.audio_url("cat")).status_code == 200
    assert client.get(audio_cache.audio_url("fish")).status_code == 404
    assert synth.calls == ["cat"]


def test_a_placement_question_with_sound_is_voiced(client, db_session, storage, synth):
    make_map_question(db_session, make_subject(db_session), question_text="Select the word book.", question_sound=True)

    response = client.get(audio_cache.audio_url("Select the word book."))

    assert response.status_code == 200
    assert synth.calls == ["Select the word book."]


@pytest.mark.parametrize(
    "path",
    [
        "/audio/notahash.mp3",
        "/audio/" + "a" * 32 + ".wav",
        "/audio/" + "A" * 32 + ".mp3",
        "/audio/" + "a" * 31 + ".mp3",
        "/audio/..%2Fsecret.mp3",
    ],
)
def test_a_name_that_is_not_an_audio_hash_is_refused(client, db_session, storage, synth, path):
    assert client.get(path).status_code == 404
    assert synth.calls == []


def test_a_failed_generation_is_a_404_and_is_not_retried_straight_away(client, db_session, storage, synth):
    _spoken_question(db_session, question_sound=True)
    synth.fail = True
    url = audio_cache.audio_url("Which is the cat?")

    assert client.get(url).status_code == 404
    assert client.get(url).status_code == 404

    assert synth.calls == ["Which is the cat?"]


def test_content_added_after_the_list_was_built_is_picked_up(client, db_session, storage, synth, monkeypatch):
    monkeypatch.setattr(audio_cache, "REFRESH_SECONDS", 0)
    assert client.get(audio_cache.audio_url("Which is the cat?")).status_code == 404

    _spoken_question(db_session, question_sound=True)

    assert client.get(audio_cache.audio_url("Which is the cat?")).status_code == 200


def test_the_list_is_not_rebuilt_on_every_unknown_request(client, db_session, storage, synth, monkeypatch):
    builds = []
    real = audio_cache.spoken_texts
    monkeypatch.setattr(audio_cache, "spoken_texts", lambda: builds.append(1) or real())

    for n in range(5):
        client.get(audio_cache.audio_url(f"unlisted {n}"))

    assert len(builds) == 1
