"""GCSBucket builds its client on first use, not at app boot."""

from __future__ import annotations

import sys
import types

import pytest

from helpers.storage import GCSBucket

pytestmark = pytest.mark.unit


class _Blob:
    def exists(self):
        return True


class _Bucket:
    def blob(self, _name):
        return _Blob()


def _fake_gcs(monkeypatch):
    built = []

    class _Client:
        def __init__(self):
            built.append(self)

        def bucket(self, _name):
            return _Bucket()

    module = types.ModuleType("google.cloud.storage")
    module.Client = _Client  # ty: ignore[unresolved-attribute]  # ModuleType has no static attrs; this IS the fake module's API
    monkeypatch.setitem(sys.modules, "google.cloud.storage", module)
    return built


def test_constructing_the_storage_builds_no_client(monkeypatch):
    built = _fake_gcs(monkeypatch)

    GCSBucket("bucket")

    assert built == []


def test_the_first_use_builds_one_client_and_later_uses_share_it(monkeypatch):
    built = _fake_gcs(monkeypatch)
    storage = GCSBucket("bucket")

    assert storage.exists("audio/a.mp3")
    assert storage.exists("audio/b.mp3")

    assert len(built) == 1
