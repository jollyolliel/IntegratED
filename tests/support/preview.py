"""A second app booted as a preview, on its own throwaway SQLite file and bucket."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def preview_app(app, tmp_path_factory):
    """`create_app()` under `APP_ENV=preview`, with its schema created and the small seed applied.

    The session `app` is requested first so it has already been built as development.
    """
    from extensions import db, limiter
    from helpers.preview.seed import seed_preview
    from main import create_app
    from settings import REFUSED_IN_PREVIEW

    patch = pytest.MonkeyPatch()
    patch.setenv("APP_ENV", "preview")
    patch.setenv("PREVIEW_DATA_DIR", str(tmp_path_factory.mktemp("preview")))
    patch.setenv("PREVIEW_PR", "42")
    patch.setenv("GIT_SHA", "abcdef1234567890")
    # A developer's .env has been loaded into this process, and a preview refuses to start beside it.
    for name in (*REFUSED_IN_PREVIEW, "GOOGLE_CLIENT_ID", "K_SERVICE"):
        patch.delenv(name, raising=False)
    try:
        application = create_app()
        application.config.update(TESTING=True)
        # init_app on the shared limiter switched it back on; the suite runs with it off.
        limiter.enabled = False
        with application.app_context():
            db.create_all()
            seed_preview("small")
        yield application
    finally:
        patch.undo()
        limiter.enabled = False


@pytest.fixture
def preview_client(preview_app):
    return preview_app.test_client()
