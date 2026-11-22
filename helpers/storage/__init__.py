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

    # Any key
    def exists(self, key: str, /) -> bool: ...
    def read_text(self, key: str, /) -> str: ...
    def read_bytes(self, key: str, /) -> bytes: ...
    def write(self, key: str, data: bytes, mimetype: str, /) -> None: ...
    def send(self, key: str, mimetype: str, /) -> Response: ...
    def delete(self, key: str, /) -> None: ...
    def download_prefix(self, prefix: str, destination: str, /) -> None: ...

    # Worksheet uploads, under WORKSHEET_PREFIX
    def key_for(self, filename: str, /) -> str: ...
    def is_safe_path(self, key: str, /) -> bool: ...
    def prefers_inline_storage(self, ext: str, /) -> bool: ...
    def save_upload(self, werkzeug_file: FileStorage, filename: str, /) -> str: ...


def get_bucket() -> Bucket:
    """The app's configured bucket.

    Returns:
        Bucket: `app.config["BUCKET"]`.
    """
    from flask import current_app
    return current_app.config["BUCKET"]
