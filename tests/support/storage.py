"""An in-memory bucket.

Mirrors the `LocalBucket` / `GCSBucket` interface in `helpers/storage/` so worksheet, audio and
image tests never read or write a real bucket or the dev seed.
"""

from __future__ import annotations

import io
import os

from flask import send_file

from helpers.storage import WORKSHEET_PREFIX


class FakeBucket:
    """Holds every file in `files`, keyed by its bucket key (`worksheets/a.pdf`, `audio/<hash>.mp3`, ...)."""

    def __init__(self, files=None, *, inline_exts=()):
        #: bucket key -> bytes
        self.files: dict[str, bytes] = {}
        self.inline_exts = set(inline_exts)
        for name, content in (files or {}).items():
            self.add_worksheet(name, content)

    # --- test-side helpers -------------------------------------------------

    def add_worksheet(self, filename, content):
        """Seed a worksheet file. Accepts str or bytes; returns its key."""
        return self.write_key(self.key_for(filename), content)

    def write_key(self, key, content):
        """Store a file under a full bucket key such as `content/questions.json`."""
        self.files[key] = content.encode("utf-8") if isinstance(content, str) else content
        return key

    def under(self, prefix):
        """The files under `prefix`, keyed by the rest of their key (`under("audio/")` → name -> bytes)."""
        return {key[len(prefix):]: data for key, data in self.files.items() if key.startswith(prefix)}

    # --- bucket interface --------------------------------------------------

    def exists(self, key):
        return key in self.files

    def read_text(self, key):
        return self.files[key].decode("utf-8")

    def read_bytes(self, key):
        return self.files[key]

    def write(self, key, data, mimetype):
        self.files[key] = data

    def send(self, key, mimetype):
        return send_file(io.BytesIO(self.files[key]), mimetype=mimetype, download_name=key.rsplit("/", 1)[-1])

    def delete(self, key):
        self.files.pop(key, None)

    def download_prefix(self, prefix, destination):
        for key, data in self.files.items():
            if key.startswith(prefix) and key != prefix:
                target = os.path.join(destination, *key[len(prefix):].split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as handle:
                    handle.write(data)

    def key_for(self, filename):
        return WORKSHEET_PREFIX + filename

    def is_safe_path(self, filepath):
        return not str(filepath).startswith("..") and ".." not in str(filepath).split("/")

    def prefers_inline_storage(self, ext):
        return ext.lower().lstrip(".") in self.inline_exts

    def save_upload(self, werkzeug_file, filename):
        return self.write_key(self.key_for(filename), werkzeug_file.read())


def use_fake_storage(monkeypatch, storage=None, *, targets=()):
    """Point `get_bucket()` at a fake, also in each module of `targets` that imported it by name."""

    from helpers import storage as storage_module

    storage = storage or FakeBucket()
    monkeypatch.setattr(storage_module, "get_bucket", lambda: storage)
    for target in targets:
        if hasattr(target, "get_bucket"):
            monkeypatch.setattr(target, "get_bucket", lambda: storage)
    return storage
