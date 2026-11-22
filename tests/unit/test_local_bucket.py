"""The dev bucket: a folder with the same keys as the GCS bucket, filled from `seed/files/` while it holds no file."""

from __future__ import annotations

import io

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from helpers.storage import GCSBucket, LocalBucket

pytestmark = pytest.mark.unit


@pytest.fixture
def bucket(tmp_path):
    return LocalBucket(str(tmp_path / "bucket"))


def test_keys_match_the_gcs_keys(bucket):
    gcs = GCSBucket("any-bucket")
    assert bucket.key_for("sheet.pdf") == gcs.key_for("sheet.pdf") == "worksheets/sheet.pdf"


def test_an_upload_lands_under_its_key_inside_the_bucket(bucket, tmp_path):
    upload = FileStorage(stream=io.BytesIO(b"%PDF-1"), filename="sheet.pdf")

    key = bucket.save_upload(upload, "sheet.pdf")

    assert key == "worksheets/sheet.pdf"
    assert (tmp_path / "bucket" / "worksheets" / "sheet.pdf").read_bytes() == b"%PDF-1"
    assert bucket.exists(key) is True
    assert bucket.read_bytes(key) == b"%PDF-1"


def test_a_written_file_lands_under_its_key_in_the_bucket(bucket, tmp_path):
    assert bucket.exists("audio/a.mp3") is False

    bucket.write("audio/a.mp3", b"ID3", "audio/mpeg")

    assert bucket.exists("audio/a.mp3") is True
    assert (tmp_path / "bucket" / "audio" / "a.mp3").read_bytes() == b"ID3"


def test_a_file_is_served_from_the_bucket_as_the_type_asked_for(bucket):
    bucket.write("audio/a.mp3", b"ID3", "audio/mpeg")
    with Flask(__name__).test_request_context():
        response = bucket.send("audio/a.mp3", "audio/mpeg")
        response.direct_passthrough = False
        assert response.get_data() == b"ID3"
        assert response.mimetype == "audio/mpeg"


def test_a_deleted_file_is_gone_and_deleting_again_is_not_an_error(bucket, tmp_path):
    bucket.write("images/a.png", b"png", "image/png")

    bucket.delete("images/a.png")

    assert bucket.exists("images/a.png") is False
    assert not (tmp_path / "bucket" / "images" / "a.png").exists()
    bucket.delete("images/a.png")


@pytest.mark.parametrize("filename", ["../escape.pdf", "../../etc/passwd", "sub/../../outside.pdf"])
def test_a_traversing_key_is_refused(bucket, filename):
    assert bucket.is_safe_path(bucket.key_for(filename)) is False


def test_a_key_inside_the_worksheets_folder_is_safe(bucket):
    assert bucket.is_safe_path(bucket.key_for("sheet.pdf")) is True


def test_seed_from_fills_an_empty_bucket(bucket, tmp_path):
    seed = tmp_path / "files"
    (seed / "worksheets").mkdir(parents=True)
    (seed / "worksheets" / "one.pdf").write_bytes(b"%PDF")
    (seed / "content" / "worksheets").mkdir(parents=True)
    (seed / "content" / "questions.json").write_text("[]", encoding="utf-8")
    (seed / "content" / "worksheets" / "manifest.json").write_text("[]", encoding="utf-8")

    copied = bucket.seed_from(str(seed))

    assert copied == 3
    assert bucket.exists("worksheets/one.pdf")
    assert bucket.exists("content/worksheets/manifest.json")


@pytest.mark.parametrize("existing", ["upload", "audio"])
def test_seed_from_leaves_a_bucket_that_already_has_any_file_alone(bucket, tmp_path, existing):
    if existing == "upload":
        bucket.save_upload(FileStorage(stream=io.BytesIO(b"mine"), filename="mine.pdf"), "mine.pdf")
    else:
        bucket.write("audio/a.mp3", b"ID3", "audio/mpeg")
    seed = tmp_path / "files"
    (seed / "worksheets").mkdir(parents=True)
    (seed / "worksheets" / "one.pdf").write_bytes(b"%PDF")

    assert bucket.seed_from(str(seed)) == 0
    assert bucket.exists("worksheets/one.pdf") is False


def test_download_prefix_copies_a_folder_out_keeping_its_layout(bucket, tmp_path):
    seed = tmp_path / "files"
    (seed / "content" / "worksheets").mkdir(parents=True)
    (seed / "content" / "worksheets" / "manifest.json").write_text("[]", encoding="utf-8")
    bucket.seed_from(str(seed))
    out = tmp_path / "out"
    out.mkdir()

    bucket.download_prefix("content/", str(out))

    assert (out / "worksheets" / "manifest.json").read_text(encoding="utf-8") == "[]"


def test_download_prefix_of_a_missing_folder_copies_nothing(bucket, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    bucket.download_prefix("content/", str(out))

    assert list(out.iterdir()) == []


def test_seed_from_a_missing_folder_does_nothing(bucket, tmp_path):
    assert bucket.seed_from(str(tmp_path / "nope")) == 0
