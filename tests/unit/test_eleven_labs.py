"""ElevenLabs text-to-speech, called over plain HTTP rather than the SDK.

The request has to be the one the SDK's `text_to_speech.convert` sends —
same endpoint, auth header, query and body — and every failure has to come
back as `None`, because audio is optional and a page must never break on it.
Audio only ever lives in the bucket, and is only generated when `TTS_ENABLED` is on.
"""

from __future__ import annotations

import os

import pytest
import requests

from helpers import eleven_labs
from settings import DEFAULT_ELEVEN_VOICE_ID, Settings

pytestmark = pytest.mark.unit


class _Response:
    def __init__(self, status_code: int = 200, content: bytes = b"ID3audio") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise requests.HTTPError(f"{self.status_code} error")


class _Api:
    """Stands in for `requests.post`: records each call, answers `response`."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.response = _Response()

    def post(self, url: str, **kwargs) -> _Response:
        self.posts.append({"url": url, **kwargs})
        return self.response


class _Storage:
    """Stands in for the bucket; `saved` is the audio under `audio/`, by filename."""

    def __init__(self, files=()):
        self.saved: dict[str, bytes] = {name: b"" for name in files}

    def exists(self, key: str) -> bool:
        return key.startswith("audio/") and key.removeprefix("audio/") in self.saved

    def write(self, key: str, data: bytes, mimetype: str) -> None:
        assert key.startswith("audio/") and mimetype == "audio/mpeg"
        self.saved[key.removeprefix("audio/")] = data


def _settings(**env) -> Settings:
    return Settings.from_env({**os.environ, "APP_ENV": "development", **env})


@pytest.fixture
def storage(monkeypatch) -> _Storage:
    fake = _Storage()
    monkeypatch.setattr(eleven_labs, "get_bucket", lambda: fake)
    return fake


@pytest.fixture
def api(monkeypatch, storage) -> _Api:
    fake = _Api()
    monkeypatch.setattr(eleven_labs.requests, "post", fake.post)
    monkeypatch.setenv("ELEVEN_API_KEY", "test-key")
    monkeypatch.setattr(eleven_labs, "get_settings", lambda: _settings(TTS_ENABLED="true"))
    return fake


def test_sends_the_request_the_sdk_convert_call_sends(api):
    path = eleven_labs.generate_audio("Hello", voice_id="voice123")

    assert path is not None and path.endswith(".mp3")
    assert len(api.posts) == 1
    call = api.posts[0]
    assert call["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice123"
    assert call["params"] == {"output_format": "mp3_44100_128"}
    assert call["json"] == {"text": "Hello", "model_id": "eleven_v3"}
    assert call["headers"]["xi-api-key"] == "test-key"
    assert call["timeout"] == eleven_labs.TTS_TIMEOUT_SECONDS


def test_the_voice_and_model_come_from_settings(api, monkeypatch):
    monkeypatch.setattr(
        eleven_labs,
        "get_settings",
        lambda: _settings(TTS_ENABLED="true", ELEVEN_VOICE_ID="configured", ELEVEN_MODEL_ID="model-x"),
    )

    eleven_labs.generate_audio("Hello")

    assert api.posts[0]["url"].endswith("/configured")
    assert api.posts[0]["json"]["model_id"] == "model-x"


def test_the_audio_bytes_are_saved_in_the_bucket(api, storage):
    path = eleven_labs.generate_audio("Hello")

    assert path is not None
    assert storage.saved[path.rsplit("/", 1)[-1]] == b"ID3audio"


def test_a_stored_file_is_served_without_calling_the_api(api):
    first = eleven_labs.generate_audio("Hello")
    second = eleven_labs.generate_audio("Hello")

    assert first == second and first is not None and first.startswith("/audio/")
    assert len(api.posts) == 1


def test_nothing_is_generated_unless_tts_is_enabled(api, monkeypatch, storage):
    monkeypatch.setattr(eleven_labs, "get_settings", lambda: _settings())

    assert eleven_labs.generate_audio("Hello") is None
    assert api.posts == []
    assert storage.saved == {}


def test_audio_already_in_the_bucket_is_linked_even_when_tts_is_disabled(api, monkeypatch, storage):
    monkeypatch.setattr(eleven_labs, "get_settings", lambda: _settings())
    name = eleven_labs.audio_filename("Hello")
    storage.saved[name] = b"ID3"

    assert eleven_labs.generate_audio("Hello") == f"/audio/{name}"
    assert api.posts == []


def test_an_api_error_returns_none_and_stores_nothing(api, storage):
    api.response = _Response(status_code=401, content=b'{"detail":"bad key"}')

    assert eleven_labs.generate_audio("Hello") is None
    assert storage.saved == {}


def test_a_network_failure_returns_none(api, monkeypatch):
    def boom(url: str, **kwargs) -> _Response:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(eleven_labs.requests, "post", boom)

    assert eleven_labs.generate_audio("Hello") is None


def test_a_missing_key_returns_none_without_calling_the_api(api, monkeypatch):
    monkeypatch.delenv("ELEVEN_API_KEY")

    assert eleven_labs.generate_audio("Hello") is None
    assert api.posts == []


def test_empty_text_returns_none_without_calling_the_api(api):
    assert eleven_labs.generate_audio("") is None
    assert eleven_labs.generate_audio(None) is None
    assert api.posts == []


def test_generated_audio_is_saved_under_its_audio_filename(api):
    path = eleven_labs.generate_audio("Hello", voice_id="voice123")

    assert path is not None
    assert path.rsplit("/", 1)[-1] == eleven_labs.audio_filename("Hello", "voice123")


def test_the_audio_filename_depends_on_the_text_and_the_voice():
    name = eleven_labs.audio_filename("Hello", "voice123")

    assert name.endswith(".mp3")
    assert name == eleven_labs.audio_filename("Hello", "voice123")
    assert name != eleven_labs.audio_filename("Hello!", "voice123")
    assert name != eleven_labs.audio_filename("Hello", "other-voice")


def test_the_default_filename_is_unchanged_so_cached_audio_still_resolves():
    assert eleven_labs.audio_filename("Hello") == eleven_labs.audio_filename("Hello", DEFAULT_ELEVEN_VOICE_ID)


# ── linking audio that already exists, never generating it ───────────────────


def test_linking_finds_audio_already_in_storage_without_calling_the_api(api, storage):
    name = eleven_labs.audio_filename("Hello")
    storage.saved[name] = b"ID3"

    assert eleven_labs.linked_audio("Hello") == f"/audio/{name}"
    assert api.posts == []


def test_linking_audio_that_was_never_generated_returns_none_without_calling_the_api(api):
    assert eleven_labs.linked_audio("Hello") is None
    assert api.posts == []


def test_linking_needs_no_api_key(monkeypatch, storage):
    monkeypatch.delenv("ELEVEN_API_KEY", raising=False)
    storage.saved[eleven_labs.audio_filename("Hello")] = b"ID3"

    assert eleven_labs.linked_audio("Hello") is not None


def test_linking_empty_text_returns_none(api):
    assert eleven_labs.linked_audio("") is None
    assert eleven_labs.linked_audio(None) is None
