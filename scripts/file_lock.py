"""A lock file so two Claude chats never read-modify-write the same files at once.

    with locked(".live/edit.lock"):
        text = read(path)
        write(path, change(text))

The lock is a file created with O_EXCL; whoever creates it holds it. A lock
older than `stale` seconds belongs to a writer that crashed, and is taken over.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Generator
from contextlib import contextmanager


class LockTimeout(Exception):
    """Another writer held the lock for longer than the timeout."""


def _try_create(path: str, token: str) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except (FileExistsError, PermissionError):
        # PermissionError: on Windows, the file is being deleted by its holder.
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    return True


def _is_stale(path: str, stale: float) -> bool:
    try:
        return time.time() - os.path.getmtime(path) > stale
    except OSError:
        return False


def _remove(path: str, token: str | None = None) -> None:
    """Delete the lock; with a token, only if it is still ours."""
    try:
        if token is not None:
            with open(path, encoding="utf-8") as handle:
                if handle.read() != token:
                    return
        os.remove(path)
    except OSError:
        pass


@contextmanager
def locked(path: str, timeout: float = 30, stale: float = 120) -> Generator[None, None, None]:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    token = f"{os.getpid()} {secrets.token_hex(8)}"
    deadline = time.monotonic() + timeout
    while not _try_create(path, token):
        if _is_stale(path, stale):
            _remove(path)
            continue
        if time.monotonic() > deadline:
            raise LockTimeout(f"{path} has been held by another writer for over {timeout:g}s")
        time.sleep(0.02)
    try:
        yield
    finally:
        _remove(path, token)
