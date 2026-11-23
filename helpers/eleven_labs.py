import hashlib
import logging
from urllib.parse import quote

import requests

from helpers.storage import get_bucket
from settings import get_settings

logger = logging.getLogger(__name__)

# Without a timeout a hung TTS call holds a gunicorn thread until the worker
# timeout — with 1 worker × 8 threads a few of these starve the whole service.
TTS_TIMEOUT_SECONDS = 30

# The one call this app makes, as the SDK's `text_to_speech.convert` sends it
# (elevenlabs-python src/elevenlabs/text_to_speech/raw_client.py) — a plain
# POST, so the SDK and its httpx/pydantic/websockets stack aren't shipped.
_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_OUTPUT_FORMAT = "mp3_44100_128"

__all__ = ["AUDIO_MIMETYPE", "audio_filename", "audio_key", "generate_audio", "linked_audio"]

AUDIO_MIMETYPE = "audio/mpeg"


def _synthesize(text: str, voice_id: str) -> bytes:
    """Ask ElevenLabs to speak `text`.

    Args:
        text (str): Text to synthesize.
        voice_id (str): ElevenLabs voice id to use.

    Returns:
        bytes: The MP3 audio.

    Raises:
        ValueError: `ELEVEN_API_KEY` is not set.
        requests.RequestException: The request failed or came back non-2xx.
    """
    api_key = get_settings().eleven_api_key
    if not api_key:
        raise ValueError("ELEVEN_API_KEY is required to use ElevenLabs API.")
    response = requests.post(
        _TTS_URL.format(voice_id=quote(voice_id, safe="")),
        params={"output_format": _OUTPUT_FORMAT},
        headers={"xi-api-key": api_key, "Accept": "audio/mpeg"},
        json={"text": text, "model_id": get_settings().eleven_model_id},
        timeout=TTS_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.content


def audio_filename(text: str, voice_id: str | None = None) -> str:
    """The file `generate_audio` saves `text` spoken by `voice_id` under.

    Args:
        text (str): Text that is spoken.
        voice_id (str | None): ElevenLabs voice id; the configured `ELEVEN_VOICE_ID` when omitted.

    Returns:
        str: `<md5 of "text:voice_id">.mp3`.
    """
    voice = voice_id or get_settings().eleven_voice_id
    # A cache name, not a security hash. Changing it would orphan every generated file in the bucket.
    return hashlib.md5(f"{text}:{voice}".encode(), usedforsecurity=False).hexdigest() + ".mp3"


def audio_key(filename: str) -> str:
    """The bucket key an audio file named by `audio_filename` lives under."""
    from helpers.storage import AUDIO_PREFIX

    return AUDIO_PREFIX + filename


def linked_audio(text: str | None, voice_id: str | None = None) -> str | None:
    """URL of audio already generated for `text`, without calling ElevenLabs.

    Args:
        text (str | None): Text that is spoken; returns None if empty.
        voice_id (str | None): ElevenLabs voice id; the configured one when omitted.

    Returns:
        str | None: The URL `generate_audio` would return, or None if the bucket has no such file.
    """
    if not text:
        return None
    filename = audio_filename(text, voice_id)
    return f"/audio/{filename}" if get_bucket().exists(audio_key(filename)) else None


def generate_audio(text: str | None, voice_id: str | None = None) -> str | None:
    """Speak `text` with ElevenLabs into the bucket, unless it is already there.

    Generation spends credits, so it only happens when `TTS_ENABLED` is true; audio that already
    exists in the bucket is linked either way.

    Args:
        text (str | None): Text to synthesize; returns None if empty.
        voice_id (str | None): ElevenLabs voice id; the configured one when omitted.

    Returns:
        str | None: URL path to serve the audio file, or None when empty, disabled or failed.
    """
    existing = linked_audio(text, voice_id)
    if existing or not text or not get_settings().tts_enabled:
        return existing
    voice = voice_id or get_settings().eleven_voice_id
    filename = audio_filename(text, voice)
    try:
        get_bucket().write(audio_key(filename), _synthesize(text, voice), AUDIO_MIMETYPE)
        return f"/audio/{filename}"
    except Exception as e:  # noqa: BLE001 - optional external TTS call, one ElevenLabs failure must not crash the page requesting audio
        logger.error("Error generating audio with ElevenLabs: %s", e)
        return None
