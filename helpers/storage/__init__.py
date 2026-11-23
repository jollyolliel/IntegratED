"""The app's bucket — worksheets, generated audio, public images, content and backups — one
interface, two backends.

Layout:
  _local.py  LocalBucket — a folder, for dev
  _gcs.py    GCSBucket — Google Cloud Storage, for Cloud Run

Both implement `Bucket` on bucket keys (`worksheets/a.pdf`, `audio/<hash>.mp3`, `images/<hash>.png`,
`content/questions.json`); each caller owns its own prefix (`WORKSHEET_PREFIX`, `AUDIO_PREFIX`,
`IMAGE_PREFIX`). Callers never branch on which backend they have, and every environment configures
one, so the app's bucket is never None.
"""

from typing import Protocol

from flask import Response
from werkzeug.datastructures import FileStorage

from helpers.storage._gcs import GCSBucket
from helpers.storage._keys import AUDIO_PREFIX, IMAGE_PREFIX, WORKSHEET_PREFIX
from helpers.storage._local import LocalBucket

__all__ = ["AUDIO_PREFIX", "IMAGE_PREFIX", "WORKSHEET_PREFIX", "Bucket", "GCSBucket", "LocalBucket", "get_bucket"]


class Bucket(Protocol):
    """What the app asks of its bucket: a folder in development, the GCS bucket in production."""

    # A docstring, not `...`, is each body: CodeQL reads a bare `...` as a statement with no effect.

    # Any key
    def exists(self, key: str, /) -> bool:
        """Whether anything is stored under `key`."""

    def read_text(self, key: str, /) -> str:
        """The UTF-8 text stored under `key`."""

    def read_bytes(self, key: str, /) -> bytes:
        """The bytes stored under `key`."""

    def write(self, key: str, data: bytes, mimetype: str, /) -> None:
        """Store `data` under `key` as `mimetype`, replacing what was there."""

    def send(self, key: str, mimetype: str, /) -> Response:
        """What is stored under `key`, as a Flask response served as `mimetype`."""

    def delete(self, key: str, /) -> None:
        """Remove what is stored under `key`."""

    def download_prefix(self, prefix: str, destination: str, /) -> None:
        """Copy every key under `prefix` into the local folder `destination`."""

    # Worksheet uploads, under WORKSHEET_PREFIX
    def key_for(self, filename: str, /) -> str:
        """The key a worksheet file is stored under."""

    def is_safe_path(self, key: str, /) -> bool:
        """Whether `key` stays inside the worksheets prefix."""

    def prefers_inline_storage(self, ext: str, /) -> bool:
        """Whether a worksheet with extension `ext` is better kept in its database row."""

    def save_upload(self, werkzeug_file: FileStorage, filename: str, /) -> str:
        """Save a worksheet file and return its key."""


def get_bucket() -> Bucket:
    """The app's configured bucket.

    Returns:
        Bucket: `app.config["BUCKET"]`.
    """
    from flask import current_app
    return current_app.config["BUCKET"]
