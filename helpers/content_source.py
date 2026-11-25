"""Where learning content is read from: the storage's `content/` folder, in every environment.

The folder holds `questions.json`, `announcements.json` and `worksheets/` (`manifest.json` plus the
markdown sheets it stores inline). Production keeps the real, proprietary curriculum there in the
bucket; the dev bucket is filled with a small sample from `seed/files/content/`. `staged_content`
copies the folder somewhere local for the length of a block and yields that path, so the importer,
the manifest sync and the announcement sync read files the same way everywhere, and deploying
can never prune production content down to a sample (docs/operations/database.md).
"""

import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from helpers.storage import Bucket

__all__ = ["BUCKET_FOLDER", "ContentSourceError", "staged_content"]

BUCKET_FOLDER = "content/"


class ContentSourceError(RuntimeError):
    """The storage has no content to import; nothing was changed."""


@contextmanager
def staged_content(storage: Bucket) -> Generator[str]:
    """Copy the storage's `content/` folder to a temporary folder for the block.

    Args:
        storage (Bucket): The app's storage.

    Yields:
        str: The local folder holding `questions.json`, `announcements.json` and `worksheets/`.

    Raises:
        ContentSourceError: The storage has no `content/questions.json`.
    """
    with tempfile.TemporaryDirectory(prefix="integrated-content-") as folder:
        storage.download_prefix(BUCKET_FOLDER, folder)
        if not os.path.isfile(os.path.join(folder, "questions.json")):
            raise ContentSourceError(
                f"The storage has no {BUCKET_FOLDER}questions.json. Upload the content file first "
                "(docs/operations/database.md); nothing was imported or pruned."
            )
        yield folder
