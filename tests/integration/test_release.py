"""A production boot does no database work; ``flask release`` does it once per deploy.

ADR 0015: Cloud Run throttles CPU outside requests, so work a container starts
in the background at boot crawls, and the app must serve as soon as gunicorn
has imported it. The schema and announcements are brought up to date by
``flask release``, which the deploy runs before the new revision takes traffic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from tests.support.migrations import ROOT, flask_command

pytestmark = pytest.mark.integration

# Counts every pool checkout made while `main` imports, then asks the production
# app for a static file. Printed as the last stdout line.
_BOOT_PROBE = """
import json
import sqlalchemy.pool

attempts = []
_connect = sqlalchemy.pool.Pool.connect


def _spy(self):
    attempts.append(1)
    return _connect(self)


sqlalchemy.pool.Pool.connect = _spy

import main
import sys

connects_during_import = len(attempts)
heavy = ("alembic", "authlib", "flask_migrate", "google.cloud.storage", "markdown", "stripe")
loaded = sorted(name for name in heavy if name in sys.modules)
status = main.app.test_client().get("/static/svg/book.svg").status_code
print(json.dumps({
    "connects_during_import": connects_during_import,
    "heavy_modules_loaded": loaded,
    "static_status": status,
}))
"""


def _boot_production(tmp_path, bucket: str = "example-bucket") -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DATABASE_URL", "TEST_DATABASE_URL", "APP_ENV"}
    }
    env.update(
        APP_ENV="production",
        DATABASE_URL=f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
        GCS_BUCKET_NAME=bucket,
        POSTHOG_API_KEY="",
        SECRET_KEY="test-secret-key",
        GOOGLE_CLIENT_ID="test-client-id",
        GOOGLE_CLIENT_SECRET="test-client-secret",
    )
    result = subprocess.run(
        [sys.executable, "-c", _BOOT_PROBE],
        check=False,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_import_never_connects_to_the_database(tmp_path):
    # gunicorn --preload imports the app before it opens its port, so a
    # connect here holds the first request for a Neon wake.
    assert _boot_production(tmp_path)["connects_during_import"] == 0


def test_production_app_serves_as_soon_as_it_is_imported(tmp_path):
    assert _boot_production(tmp_path)["static_status"] == 200


def test_production_import_leaves_storage_for_the_requests_that_use_it(tmp_path):
    # Every module the import opens is a slow read on a cold Cloud Run host,
    # and building the GCS client also asks the metadata server for
    # credentials — all before gunicorn opens its port.
    boot = _boot_production(tmp_path)
    assert "google.cloud.storage" not in boot["heavy_modules_loaded"]


def test_production_import_leaves_cli_and_rare_route_libraries_unloaded(tmp_path):
    # Each is a noticeable slice of a cold start, and only a CLI command or a
    # rarely hit route uses it: Alembic under Flask-Migrate (`flask db`,
    # `flask release`), Stripe (donations), Authlib (Google sign-in) and
    # Markdown (pages that render it).
    boot = _boot_production(tmp_path)
    assert boot["heavy_modules_loaded"] == []


def test_release_migrates_an_empty_database_and_lands_the_announcements(tmp_path):
    """The real `flask release` in a subprocess, against the sample content in a dev bucket."""

    import shutil

    database_url = f"sqlite:///{(tmp_path / 'release.db').as_posix()}"
    bucket = tmp_path / "bucket"
    shutil.copytree(ROOT / "seed" / "files" / "content", bucket / "content")
    (bucket / "content" / "announcements.json").write_text(
        json.dumps([{"uid": "release-test", "title": "Hello"}]), encoding="utf-8"
    )

    result = flask_command(database_url, "release", bucket=str(bucket))

    assert result.returncode == 0, result.stderr[-4000:] + result.stdout[-4000:]
    engine = create_engine(database_url)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        landed = set(connection.execute(text("SELECT uid FROM feature_announcements")).scalars())
    engine.dispose()
    assert version
    assert landed == {"release-test"}


# ── content: backup, questions, worksheets ───────────────────────────────────


def _release_course(name="English: First Steps", banded=True):
    question = {"content_type": "multiple_choice", "question_prompt": "Choose", "question_text": f"{name} q",
                "options": ["yes", "no"], "answer": "yes"}
    course = {"name": name, "icon": "book", "description": name,
            "topics": [{"title": "Sounds", "icon": "star", "description": "Sounds", "overview_markdown": "# S",
                        "level": 1, "lessons": [{"title": "One", "icon": "leaf", "description": "One",
                                                 "game_type": None, "questions": [question]}]}]}
    if banded:
        course["placement"] = {"scale": "English", "min_level": 1, "max_level": 1}
    return course


def _release_content():
    placement = {"name": "Map Test", "questions": [
        {"subject_name": "English", "level": 1, "content_type": "multiple_choice", "question_prompt": "Choose",
         "question_text": "Tap yes", "options": ["yes", "no"], "answer": "yes"},
    ]}
    return [placement, _release_course()]


_MANIFEST = [{"file": "01_the.pdf", "title": "The", "subject": "English: Reading Start", "level": 1,
              "tags": ["sight-words"]}]


@pytest.fixture
def bucket(app, monkeypatch):
    """The app's storage (`bucket.storage`), holding a PDF; `bucket.content(...)` (re)writes its `content/`."""

    from tests.support.storage import FakeBucket

    storage = FakeBucket()
    storage.add_worksheet("01_the.pdf", b"%PDF-1.4")
    monkeypatch.setitem(app.config, "BUCKET", storage)

    def content(questions=None, manifest=None, announcements=None):
        storage.write_key("content/questions.json", json.dumps(_release_content() if questions is None else questions))
        storage.write_key("content/worksheets/manifest.json", json.dumps(_MANIFEST if manifest is None else manifest))
        storage.write_key("content/announcements.json", json.dumps(announcements or []))

    return SimpleNamespace(storage=storage, content=content)


@pytest.fixture
def release_files(app, db_session, bucket, monkeypatch):
    """`flask release` in-process against the test database and the fake bucket, migrations stubbed."""

    monkeypatch.setattr("flask_migrate.upgrade", lambda *a, **k: None)
    return bucket.content


def _empty_sync():
    from helpers.worksheet_manifest import ManifestSync

    return ManifestSync()


def _record_steps(monkeypatch, calls):
    import commands
    from helpers.content import ImportResult

    monkeypatch.setattr("flask_migrate.upgrade", lambda *a, **k: calls.append("upgrade"))
    monkeypatch.setattr(commands, "sync_announcements", lambda path: calls.append("announcements") or [])
    monkeypatch.setattr("helpers.backup.run_backup_check",
                        lambda app, force=False: calls.append(("backup", force)) and None)

    def fake_import(db, data, *, prune=False, before_prune=None):
        calls.append(("questions", prune))
        return ImportResult()

    monkeypatch.setattr(commands, "import_content", fake_import)
    monkeypatch.setattr(commands, "sync_worksheet_manifest",
                        lambda storage, directory: calls.append("worksheets") or _empty_sync())


def test_release_validates_then_backs_up_before_migrating_and_importing(app, bucket, monkeypatch):
    calls = []
    bucket.content()
    _record_steps(monkeypatch, calls)

    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code == 0, result.output
    assert calls == [("backup", True), "upgrade", "announcements", ("questions", True), "worksheets"]


def test_release_stops_before_changing_anything_when_the_backup_fails(app, bucket, monkeypatch):
    calls = []
    bucket.content()
    _record_steps(monkeypatch, calls)

    def failing_backup(app, force=False):
        raise RuntimeError("pg_dump failed")

    monkeypatch.setattr("helpers.backup.run_backup_check", failing_backup)

    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code != 0
    assert calls == []


def test_release_stops_before_the_announcements_when_the_migration_fails(app, bucket, monkeypatch):
    calls = []
    bucket.content()
    _record_steps(monkeypatch, calls)

    def failing_upgrade(*_args, **_kwargs):
        raise RuntimeError("migration exploded")

    monkeypatch.setattr("flask_migrate.upgrade", failing_upgrade)

    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code != 0
    assert calls == [("backup", True)]


@pytest.mark.parametrize("broken", ["questions", "manifest"])
def test_release_changes_nothing_when_the_content_is_invalid(app, bucket, monkeypatch, broken):
    calls = []
    if broken == "questions":
        bucket.content(questions=[{"name": ""}])
    else:
        bucket.content(manifest=[{"file": "../escape.pdf", "title": "X", "subject": "Y"}])
    _record_steps(monkeypatch, calls)

    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code != 0
    assert calls == []


def test_release_refuses_a_bucket_without_content(app, bucket, monkeypatch):
    calls = []
    _record_steps(monkeypatch, calls)

    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code != 0
    assert "content/questions.json" in result.output
    assert calls == []


def test_release_imports_content_and_a_second_run_reports_nothing_to_change(app, release_files):
    from extensions import db
    from models import Subject, Worksheet

    release_files()
    runner = app.test_cli_runner()

    first = runner.invoke(args=["release"])
    second = runner.invoke(args=["release"])

    assert first.exit_code == 0, first.output
    assert "Worksheets: 1 added, 0 updated" in first.output
    assert second.exit_code == 0, second.output
    assert "Nothing to remove" in second.output
    assert "Questions: 0 added, 0 updated" in second.output
    assert "Worksheets: 0 added, 0 updated" in second.output
    assert db.session.scalar(db.select(Subject).filter_by(name="English: First Steps")) is not None
    assert db.session.scalar(db.select(Worksheet).filter_by(title="The")).tags == ["sight-words"]


def test_release_prints_the_prune_plan_before_applying_it(app, release_files, monkeypatch):
    from helpers import content

    release_files(_release_content() + [_release_course("English: Retired", banded=False)])
    assert app.test_cli_runner().invoke(args=["release"]).exit_code == 0
    release_files()

    def failing_apply(db, plan):
        raise RuntimeError("apply exploded")

    monkeypatch.setattr(content._prune, "apply_prune", failing_apply)
    result = app.test_cli_runner().invoke(args=["release"])

    assert result.exit_code != 0
    assert "English: Retired" in result.output
