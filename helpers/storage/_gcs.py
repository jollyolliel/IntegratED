from __future__ import annotations

import os
from functools import cached_property
from io import BytesIO
from typing import TYPE_CHECKING

from flask import Response, send_file
from werkzeug.datastructures import FileStorage

from helpers.storage._keys import WORKSHEET_PREFIX

if TYPE_CHECKING:
    from google.cloud import storage as gcs


class GCSBucket:
    """The Google Cloud Storage bucket, for Cloud Run. Keys are blob names."""

    def __init__(self, bucket_name: str) -> None:
        """Bind to a GCS bucket.

        Args:
            bucket_name (str): Name of the GCS bucket to use.
        """
        self._bucket_name = bucket_name

    # Built on first use, not in __init__: that runs at app import, before
    # gunicorn opens its port, and building a client loads ~150 modules and
    # asks the metadata server for credentials. Two threads racing here each
    # build one and one is kept — harmless, as clients are interchangeable.
    @cached_property
    def _client(self) -> gcs.Client:
        """The GCS client, built on first use."""
        from google.cloud import storage as gcs
        return gcs.Client()

    @cached_property
    def _bucket(self) -> gcs.Bucket:
        """The bucket handle, built on first use."""
        return self._client.bucket(self._bucket_name)

    # --- any key -----------------------------------------------------------

    def exists(self, key: str) -> bool:
        """Whether a blob exists."""
        return self._bucket.blob(key).exists()

    def read_text(self, key: str) -> str:
        """A blob as UTF-8 text."""
        return self._bucket.blob(key).download_as_text(encoding="utf-8")

    def read_bytes(self, key: str) -> bytes:
        """A blob as raw bytes."""
        return self._bucket.blob(key).download_as_bytes()

    def write(self, key: str, data: bytes, mimetype: str) -> None:
        """Upload `data` as the blob `key`, stored with `mimetype` as its content type."""
        self._bucket.blob(key).upload_from_string(data, content_type=mimetype)

    def send(self, key: str, mimetype: str) -> Response:
        """A blob as a Flask response served as `mimetype`."""
        buf = BytesIO()
        self._bucket.blob(key).download_to_file(buf)
        buf.seek(0)
        return send_file(buf, mimetype=mimetype)

    def delete(self, key: str) -> None:
        """Remove a blob; a missing blob is not an error."""
        blob = self._bucket.blob(key)
        if blob.exists():
            blob.delete()

    def download_prefix(self, prefix: str, destination: str) -> None:
        """Copy every blob under `prefix` into `destination`, keeping the folder layout below the prefix.

        Args:
            prefix (str): Blob-name prefix such as `content/`.
            destination (str): Existing local folder to fill.
        """
        for blob in self._client.list_blobs(self._bucket, prefix=prefix):
            relative = blob.name[len(prefix):]
            if not relative or relative.endswith("/"):
                continue
            target = os.path.join(destination, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            blob.download_to_filename(target)

    # --- worksheet uploads -------------------------------------------------

    def key_for(self, filename: str) -> str:
        """The blob name a worksheet file is stored under."""
        return WORKSHEET_PREFIX + filename

    def is_safe_path(self, key: str) -> bool:
        """Blob names can't traverse a filesystem — always safe."""
        return True

    def prefers_inline_storage(self, ext: str) -> bool:
        """Markdown worksheets skip the blob round-trip and live in the DB row directly."""
        return ext == "md"

    def save_upload(self, werkzeug_file: FileStorage, filename: str) -> str:
        """Upload a worksheet file and return its blob name."""
        key = self.key_for(filename)
        werkzeug_file.stream.seek(0)
        content_type = werkzeug_file.mimetype or "application/octet-stream"
        self._bucket.blob(key).upload_from_file(werkzeug_file.stream, content_type=content_type)
        return key
