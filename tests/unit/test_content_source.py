"""Where content is read from in every environment: the storage's `content/` folder, staged locally."""

import json
import os

import pytest

from helpers import content_source
from helpers.content import load_content
from tests.support.storage import FakeBucket

pytestmark = pytest.mark.unit


def test_the_storage_content_folder_is_staged_and_cleaned_up():
    storage = FakeBucket()
    storage.write_key("content/questions.json", json.dumps([{"name": "Map Test", "questions": []}]))
    storage.write_key("content/worksheets/manifest.json", "[]")

    with content_source.staged_content(storage) as staged:
        assert load_content(os.path.join(staged, "questions.json")) == [{"name": "Map Test", "questions": []}]
        assert os.path.isfile(os.path.join(staged, "worksheets", "manifest.json"))

    assert not os.path.exists(staged)


def test_storage_without_content_refuses_rather_than_prune_to_nothing():
    with (
        pytest.raises(content_source.ContentSourceError, match="content/questions.json"),
        content_source.staged_content(FakeBucket()),
    ):
        pass


def test_the_dev_sample_is_shaped_like_the_bucket():
    from helpers.paths import get_resource_path

    sample = get_resource_path("seed/files/content")
    assert os.path.isfile(os.path.join(sample, "questions.json"))
    assert os.path.isfile(os.path.join(sample, "announcements.json"))
    assert os.path.isfile(os.path.join(sample, "worksheets", "manifest.json"))
