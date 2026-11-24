"""The weekly Postgres → GCS backup check.

Neither Postgres nor GCS is available in tests, so `pg_dump` and the bucket are
both doubles. The behaviour that matters is the content-hash skip: a redeploy
inside the same week, or a week with no data changes, must not write a second
copy of the same dump.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.support.app import use_environment

pytestmark = pytest.mark.integration


class FakeBlob:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    def exists(self):
        return self.name in self._store

    def download_as_text(self, encoding="utf-8"):
        return self._store[self.name].decode(encoding)

    def upload_from_string(self, data, content_type=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._store[self.name] = data


class FakeBucket:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def blob(self, name):
        return FakeBlob(self.store, name)

    def backups(self):
        return sorted(n for n in self.store if n.endswith(".sql.gz"))

    def manifest(self):
        from helpers.backup import MANIFEST_BLOB

        raw = self.store.get(MANIFEST_BLOB)
        return json.loads(raw.decode("utf-8")) if raw else None


@pytest.fixture
def bucket():
    return FakeBucket()


@pytest.fixture
def dump(monkeypatch):
    """Replace pg_dump with a controllable byte source."""

    from helpers import backup

    holder = {"bytes": b"-- schema v1\n"}
    monkeypatch.setattr(backup, "_pg_dump", lambda database_url: holder["bytes"])
    return holder


def _manifest(bucket, **fields):
    from helpers.backup import MANIFEST_BLOB

    bucket.store[MANIFEST_BLOB] = json.dumps(fields).encode("utf-8")


# ── the guard rails ──────────────────────────────────────────────────────────


def test_the_backup_is_skipped_outside_production(app, monkeypatch):
    from helpers import backup

    use_environment(app, monkeypatch, "development")
    called = []
    monkeypatch.setattr(backup, "_check_and_backup", lambda *a: called.append(a))

    backup.run_backup_check(app)

    assert called == []


def test_the_backup_is_skipped_without_a_postgres_url(app, monkeypatch):
    from helpers import backup

    use_environment(app, monkeypatch, "production", database_url="sqlite:///local.db")
    called = []
    monkeypatch.setattr(backup, "_check_and_backup", lambda *a: called.append(a))

    backup.run_backup_check(app)

    assert called == []


def _fake_gcs_module(client_factory):
    """A stand-in for `google.cloud.storage` — a real client reaches for
    credentials and the metadata server."""

    import types

    module = types.ModuleType("google.cloud.storage")
    module.Client = client_factory  # ty: ignore[missing-attribute]  # ModuleType has no static attrs; this IS the fake module's API
    return module


@pytest.fixture
def deployed(app, monkeypatch, bucket):
    """Production-shaped configuration with a fake GCS client."""

    import sys

    use_environment(app, monkeypatch, "production", database_url="postgresql://user@host/db", gcs_bucket_name="bucket")

    class _Client:
        def bucket(self, name):
            return bucket

    monkeypatch.setitem(
        sys.modules, "google.cloud.storage", _fake_gcs_module(lambda: _Client())
    )
    return bucket


def test_a_backup_failure_is_logged_not_raised(app, monkeypatch, deployed):
    """The daily job retries tomorrow, so a failure only needs logging."""

    from helpers import backup

    monkeypatch.setattr(backup, "_check_and_backup", _raise)

    backup.run_backup_check(app)  # must not raise


def _raise(*args, **kwargs):
    raise RuntimeError("bucket on fire")


def test_a_client_that_cannot_be_built_is_survived(app, monkeypatch):
    """No credentials in the environment must skip, not crash the boot."""

    import sys

    from helpers import backup

    use_environment(app, monkeypatch, "production", database_url="postgresql://user@host/db", gcs_bucket_name="bucket")

    def no_credentials():
        raise RuntimeError("could not determine credentials")

    monkeypatch.setitem(
        sys.modules, "google.cloud.storage", _fake_gcs_module(no_credentials)
    )

    backup.run_backup_check(app)  # must not raise


def test_a_deployed_run_reaches_the_bucket(app, deployed, dump):
    """The happy path from `flask backup-db` all the way to an upload."""

    from helpers import backup

    backup.run_backup_check(app)

    assert len(deployed.backups()) == 1


# ── the content-hashed check ─────────────────────────────────────────────────


def test_the_first_run_uploads_a_backup_and_a_manifest(app, bucket, dump):
    from helpers.backup import _check_and_backup

    _check_and_backup(bucket, "postgresql://user@host/db")

    assert len(bucket.backups()) == 1
    manifest = bucket.manifest()
    assert manifest["sha256"]
    assert manifest["size_bytes"] > 0


def test_the_uploaded_backup_is_the_gzipped_dump(app, bucket, dump):
    from helpers.backup import _check_and_backup

    _check_and_backup(bucket, "postgresql://user@host/db")

    stored = bucket.store[bucket.backups()[0]]
    assert gzip.decompress(stored) == dump["bytes"]


def test_a_check_inside_the_week_does_nothing(app, bucket, dump):
    from helpers.backup import _check_and_backup

    recent = datetime.now(UTC) - timedelta(days=2)
    _manifest(bucket, checked_at=recent.isoformat(), sha256="abc", blob="old")

    _check_and_backup(bucket, "postgresql://user@host/db")

    assert bucket.backups() == []


def test_an_unchanged_database_is_not_uploaded_twice(app, bucket, dump):
    """The whole point of the content hash."""

    import hashlib

    from helpers.backup import _check_and_backup

    old = datetime.now(UTC) - timedelta(days=8)
    digest = hashlib.sha256(dump["bytes"]).hexdigest()
    _manifest(bucket, checked_at=old.isoformat(), sha256=digest, blob="backups/old.sql.gz")

    _check_and_backup(bucket, "postgresql://user@host/db")

    assert bucket.backups() == []
    # The check timestamp still moves forward, so the next check waits a week.
    assert bucket.manifest()["checked_at"] != old.isoformat()


def test_a_changed_database_uploads_a_new_snapshot(app, bucket, dump):
    from helpers.backup import _check_and_backup

    old = datetime.now(UTC) - timedelta(days=8)
    _manifest(bucket, checked_at=old.isoformat(), sha256="stale", blob="backups/old.sql.gz")
    dump["bytes"] = b"-- schema v2, now with more rows\n"

    _check_and_backup(bucket, "postgresql://user@host/db")

    assert len(bucket.backups()) == 1
    assert bucket.manifest()["sha256"] != "stale"


def test_a_corrupt_manifest_is_treated_as_no_manifest(app, bucket, dump):
    from helpers.backup import MANIFEST_BLOB, _check_and_backup

    bucket.store[MANIFEST_BLOB] = b"not json at all"

    _check_and_backup(bucket, "postgresql://user@host/db")

    assert len(bucket.backups()) == 1


# ── pg_dump itself ───────────────────────────────────────────────────────────


def test_a_missing_pg_dump_binary_is_reported_clearly(app, monkeypatch):
    from helpers import backup

    def missing(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(backup.subprocess, "run", missing)

    with pytest.raises(RuntimeError, match="pg_dump not found"):
        backup._pg_dump("postgresql://user@host/db")


def test_a_pg_dump_timeout_is_reported_clearly(app, monkeypatch):
    import subprocess

    from helpers import backup

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pg_dump", timeout=1)

    monkeypatch.setattr(backup.subprocess, "run", slow)

    with pytest.raises(RuntimeError, match="timed out"):
        backup._pg_dump("postgresql://user@host/db")


def test_a_failing_pg_dump_reports_its_stderr(app, monkeypatch):
    from helpers import backup

    class _Result:
        returncode = 1
        stdout = b""
        stderr = b"could not connect to server"

    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: _Result())

    with pytest.raises(RuntimeError, match="could not connect"):
        backup._pg_dump("postgresql://user@host/db")


def test_a_successful_pg_dump_returns_its_bytes(app, monkeypatch):
    from helpers import backup

    class _Result:
        returncode = 0
        stdout = b"-- dump"
        stderr = b""

    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: _Result())

    assert backup._pg_dump("postgresql://user@host/db") == b"-- dump"


# ── the forced backup `flask release` takes ──────────────────────────────────


def test_a_forced_backup_ignores_the_seven_day_guard(app, deployed, dump):
    from helpers import backup

    recent = datetime.now(UTC) - timedelta(hours=1)
    _manifest(deployed, checked_at=recent.isoformat(), sha256="stale", blob="backups/old.sql.gz")

    blob = backup.run_backup_check(app, force=True)

    assert len(deployed.backups()) == 1
    assert blob == deployed.backups()[0]


def test_a_forced_backup_of_an_unchanged_database_names_the_existing_backup(app, deployed, dump):
    import hashlib

    from helpers import backup

    recent = datetime.now(UTC) - timedelta(hours=1)
    digest = hashlib.sha256(dump["bytes"]).hexdigest()
    _manifest(deployed, checked_at=recent.isoformat(), sha256=digest, blob="backups/db_same.sql.gz")

    assert backup.run_backup_check(app, force=True) == "backups/db_same.sql.gz"
    assert deployed.backups() == []


def test_a_forced_backup_failure_raises(app, monkeypatch, deployed):
    """`flask release` must stop before it deletes content it could not back up."""

    from helpers import backup

    monkeypatch.setattr(backup, "_pg_dump", _raise)

    with pytest.raises(RuntimeError, match="bucket on fire"):
        backup.run_backup_check(app, force=True)


def test_a_forced_backup_raises_when_the_client_cannot_be_built(app, monkeypatch):
    import sys

    from helpers import backup

    use_environment(app, monkeypatch, "production", database_url="postgresql://user@host/db", gcs_bucket_name="bucket")

    def no_credentials():
        raise RuntimeError("could not determine credentials")

    monkeypatch.setitem(sys.modules, "google.cloud.storage", _fake_gcs_module(no_credentials))

    with pytest.raises(RuntimeError, match="credentials"):
        backup.run_backup_check(app, force=True)


@pytest.mark.parametrize(("production", "database_url", "bucket_name"), [
    (False, "postgresql://user@host/db", "bucket"),
    (True, "sqlite:///local.db", "bucket"),
])
def test_a_forced_backup_does_nothing_outside_a_production_postgres(
    app, monkeypatch, production, database_url, bucket_name
):
    from helpers import backup

    use_environment(app, monkeypatch, "production" if production else "development", database_url=database_url, gcs_bucket_name=bucket_name)
    monkeypatch.setattr(backup, "_check_and_backup", _raise)

    assert backup.run_backup_check(app, force=True) is None
