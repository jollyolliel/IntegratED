"""Audio as a cache in front of ElevenLabs.

A question never stores an audio URL. It points at `/audio/<md5 of "text:voice">.mp3` (`audio_url`),
and `serve` answers that request: a file already in storage is sent as it is; a missing one is
generated, stored, then sent. So nothing has to be pre-generated, linked or uploaded.

Generation costs money, and `/audio/` is public, so only text on the list can be voiced: quiz
questions with `question_sound`, their options with `option_sound`, and placement questions with
`question_sound` (`spoken_texts`). A hash that matches nothing on the list is a 404 that never
reaches ElevenLabs.
"""

from __future__ import annotations

import re
import threading
import time

from flask import Response, abort

from extensions import db
from helpers import eleven_labs
from helpers.storage import get_bucket

#: How soon after the list was built a request for an unknown name may rebuild it, so a burst of
#: made-up names costs one database scan, while content imported a moment ago is still found.
REFRESH_SECONDS = 5
#: After a failed generation the same file is not tried again for this long.
FAILURE_COOLDOWN_SECONDS = 60

_FILENAME = re.compile(r"[0-9a-f]{32}\.mp3")

_lock = threading.Lock()
_allowed: dict[str, str] = {}
_built_at: float | None = None
_failed: dict[str, float] = {}
_generating: dict[str, threading.Lock] = {}


def audio_url(text: str) -> str:
    """The URL the audio of `text` is served from, whether or not it exists yet."""
    return f"/audio/{eleven_labs.audio_filename(text)}"


def spoken_texts() -> set[str]:
    """Every text the app may have voiced.

    Returns:
        set[str]: Quiz question text, quiz options where `option_sound` is on, and placement
        question text, each only where its sound flag is on.
    """
    from models import MapQuestion, Question

    texts: set[str] = set(db.session.scalars(db.select(Question.question_text).where(Question.question_sound.is_(True))))
    for options in db.session.scalars(db.select(Question.options).where(Question.option_sound.is_(True))):
        texts.update(option for option in options or [] if isinstance(option, str))
    texts.update(db.session.scalars(db.select(MapQuestion.question_text).where(MapQuestion.question_sound.is_(True))))
    return {text for text in texts if text.strip()}


def generate_spoken_audio() -> tuple[int, int]:
    """Voice every spoken text now (needs `TTS_ENABLED`): (texts with audio, spoken texts)."""
    texts = sorted(spoken_texts())
    return sum(1 for text in texts if eleven_labs.generate_audio(text)), len(texts)


def reset() -> None:
    """Forget the list and every failure (for tests)."""
    global _allowed, _built_at
    with _lock:
        _allowed = {}
        _built_at = None
        _failed.clear()
        _generating.clear()


def _text_for(filename: str) -> str | None:
    """The listed text behind `filename`, rebuilding the list at most every `REFRESH_SECONDS`."""
    global _allowed, _built_at
    with _lock:
        text = _allowed.get(filename)
        if text is not None:
            return text
        now = time.monotonic()
        if _built_at is not None and now - _built_at < REFRESH_SECONDS:
            return None
        _allowed = {eleven_labs.audio_filename(listed): listed for listed in spoken_texts()}
        _built_at = now
        return _allowed.get(filename)


def _stored(filename: str) -> bool:
    return get_bucket().exists(eleven_labs.audio_key(filename))


def _send(filename: str) -> Response:
    return get_bucket().send(eleven_labs.audio_key(filename), eleven_labs.AUDIO_MIMETYPE)


def _generate(text: str, filename: str) -> bool:
    """Have ElevenLabs speak `text` into storage. One request per file at a time, and no retry
    straight after a failure."""
    with _lock:
        failed_at = _failed.get(filename)
        if failed_at is not None and time.monotonic() - failed_at < FAILURE_COOLDOWN_SECONDS:
            return False
        gate = _generating.setdefault(filename, threading.Lock())
    with gate:
        if _stored(filename):  # another request finished it while this one waited
            return True
        done = eleven_labs.generate_audio(text) is not None
        with _lock:
            if done:
                _failed.pop(filename, None)
            else:
                _failed[filename] = time.monotonic()
            _generating.pop(filename, None)
        return done


def serve(filename: str) -> Response:
    """Answer `GET /audio/<filename>`: the stored file, generated first if listed; else 404."""
    if not _FILENAME.fullmatch(filename):
        abort(404)
    if not _stored(filename):
        text = _text_for(filename)
        if text is None or not _generate(text, filename):
            abort(404)
    response = _send(filename)
    # The name is a hash of the text, so the file behind it never changes.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
