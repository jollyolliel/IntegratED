"""Uploaded image checks: which formats are accepted, told apart by their bytes.

The extension and the browser's content type are both client-supplied, so the
type is read from the file's magic number instead. Used by the article hero
image upload (`routes/administrator/cms.py`) and its public route.
"""

import re

__all__ = ["IMAGE_FILENAME_RE", "IMAGE_TYPES", "MAX_IMAGE_BYTES", "image_key", "image_mimetype", "sniff_image"]

#: Extension -> MIME type for every accepted format.
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}

#: The largest accepted upload.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: A stored image's name: 32 hex characters and an accepted extension.
IMAGE_FILENAME_RE = re.compile(r"[0-9a-f]{32}\.(?:png|jpg|webp|gif)")


def image_key(filename: str) -> str:
    """The bucket key a stored image lives under."""
    from helpers.storage import IMAGE_PREFIX

    return IMAGE_PREFIX + filename


def image_mimetype(filename: str) -> str:
    """The MIME type of a stored image, by its (accepted) extension."""
    return IMAGE_TYPES[filename.rsplit(".", 1)[1]]


def sniff_image(data: bytes) -> str | None:
    """Detect an accepted image format from its leading bytes.

    Args:
        data (bytes): The file's content (only the first 12 bytes are read).

    Returns:
        str | None: The extension (a key of `IMAGE_TYPES`), or None if the bytes
            are not a PNG, JPEG, WebP or GIF.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None
