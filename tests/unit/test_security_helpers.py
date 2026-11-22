"""Pure helpers where a wrong answer is a security hole.

Path traversal, where a wrong answer is a security hole. Cheap to test
directly, and never to be reasoned about from the call site instead.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit


# ── worksheet path safety ────────────────────────────────────────────────────


@pytest.fixture
def local_storage(tmp_path):
    from helpers.storage import LocalBucket

    return LocalBucket(str(tmp_path))


def test_a_path_inside_the_worksheet_directory_is_safe(local_storage):
    assert local_storage.is_safe_path(local_storage.key_for("sheet.pdf")) is True


@pytest.mark.parametrize(
    "filename",
    ["../escape.pdf", "../../etc/passwd", "sub/../../outside.pdf"],
)
def test_a_traversing_path_is_refused(local_storage, filename):
    assert local_storage.is_safe_path(local_storage.key_for(filename)) is False


def test_local_storage_never_prefers_inline(local_storage):
    """Local disk is cheap to read, so nothing is kept in the DB row."""

    assert local_storage.prefers_inline_storage("md") is False
    assert local_storage.prefers_inline_storage("pdf") is False


def test_a_saved_file_round_trips(local_storage):
    path = local_storage.key_for("note.md")
    os.makedirs(os.path.dirname(local_storage.local_path(path)), exist_ok=True)
    with open(local_storage.local_path(path), "w", encoding="utf-8") as handle:
        handle.write("# Hello")

    assert local_storage.exists(path) is True
    assert local_storage.read_text(path) == "# Hello"
    assert local_storage.read_bytes(path) == b"# Hello"




def test_a_missing_file_does_not_exist(local_storage):
    assert local_storage.exists(local_storage.key_for("absent.pdf")) is False


# ── path resolution ──────────────────────────────────────────────────────────


def test_a_resource_path_is_absolute():
    import os

    from helpers.paths import get_resource_path

    assert os.path.isabs(get_resource_path("seed"))


def test_a_data_path_sits_under_the_writable_instance_directory():
    """Runtime-written files go to `instance/`, not the read-only `seed/` tree."""

    from helpers.paths import get_data_path

    assert get_data_path("questions.json").replace("\\", "/").endswith(
        "instance/questions.json"
    )
