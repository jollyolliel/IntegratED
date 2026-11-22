import os
import shutil

from flask import Response, send_file
from werkzeug.datastructures import FileStorage

from helpers.storage._keys import WORKSHEET_PREFIX


class LocalBucket:
    """A folder that behaves like the GCS bucket, for local development.

    Keys are the GCS keys (`worksheets/<file>`, `audio/<file>`, `images/<file>`), so rows saved in
    dev look exactly like rows saved in production and callers never branch on the backend.
    """

    def __init__(self, root: str) -> None:
        """Create the bucket folder if needed and bind to it.

        Args:
            root (str): Directory that plays the bucket.
        """
        self.root = root
        os.makedirs(root, exist_ok=True)

    def local_path(self, key: str) -> str:
        """The normalized filesystem path behind a key (just outside `root` for a traversing key)."""
        return os.path.normpath(os.path.join(self.root, key))

    # --- any key -----------------------------------------------------------

    def exists(self, key: str) -> bool:
        """Whether a stored file exists."""
        return os.path.isfile(self.local_path(key))

    def read_text(self, key: str) -> str:
        """A stored file as UTF-8 text."""
        with open(self.local_path(key), encoding="utf-8") as f:
            return f.read()

    def read_bytes(self, key: str) -> bytes:
        """A stored file as raw bytes."""
        with open(self.local_path(key), "rb") as f:
            return f.read()

    def write(self, key: str, data: bytes, mimetype: str) -> None:
        """Store `data` at `key` (`mimetype` matters only to GCS; a file has none)."""
        path = self.local_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def send(self, key: str, mimetype: str) -> Response:
        """A stored file as a Flask response served as `mimetype`."""
        return send_file(self.local_path(key), mimetype=mimetype)

    def delete(self, key: str) -> None:
        """Remove a stored file; a missing file is not an error."""
        path = self.local_path(key)
        if os.path.isfile(path):
            os.remove(path)

    def download_prefix(self, prefix: str, destination: str) -> None:
        """Copy every file under `prefix` into `destination`, keeping the folder layout below the prefix.

        Args:
            prefix (str): Key prefix such as `content/`.
            destination (str): Existing local folder to fill.
        """
        source = self.local_path(prefix)
        if os.path.isdir(source):
            shutil.copytree(source, destination, dirs_exist_ok=True)

    # --- worksheet uploads -------------------------------------------------

    def key_for(self, filename: str) -> str:
        """The key a worksheet file is stored under."""
        return WORKSHEET_PREFIX + filename

    def is_safe_path(self, key: str) -> bool:
        """Whether `key` resolves inside the worksheets folder — the traversal guard a real filesystem needs."""
        folder = os.path.realpath(self.local_path(WORKSHEET_PREFIX))
        return os.path.realpath(self.local_path(key)).startswith(folder + os.sep)

    def prefers_inline_storage(self, ext: str) -> bool:
        """Never: a dev folder keeps every worksheet as a file."""
        return False

    def save_upload(self, werkzeug_file: FileStorage, filename: str) -> str:
        """Save a worksheet file and return its key."""
        key = self.key_for(filename)
        path = self.local_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        werkzeug_file.save(path)
        return key

    # --- development seeding -----------------------------------------------

    def seed_from(self, directory: str) -> int:
        """Copy `directory` into the bucket when the bucket holds no files yet; otherwise do nothing.

        Args:
            directory (str): Folder whose layout mirrors the bucket (`content/`, `worksheets/`, ...).

        Returns:
            int: Files copied; 0 when the bucket already had files or `directory` is missing.
        """
        if not os.path.isdir(directory) or any(files for _, _, files in os.walk(self.root)):
            return 0
        copied = 0
        for walked, _, files in os.walk(directory):
            for name in files:
                source = os.path.join(walked, name)
                target = self.local_path(os.path.relpath(source, directory))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(source, target)
                copied += 1
        return copied
