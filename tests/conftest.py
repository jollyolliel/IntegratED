"""Pytest configuration for the layered replacement suite.

Also home to changed-code selection: a plain run maps the current git diff onto
the tests that can reach it. Engine: ``scripts/change_selection.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.support.app import FakePosthogClient, configure_test_environment

configure_test_environment()

pytest_plugins = [
    "tests.support.db",
    "tests.support.auth",
    "tests.support.jx",
    "tests.support.preview",
]


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    from extensions import db, limiter
    from helpers.storage import LocalBucket
    from main import app as application

    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    # A throwaway bucket per run that pytest cleans up, so the suite never touches the dev one.
    application.config["BUCKET"] = LocalBucket(str(tmp_path_factory.mktemp("bucket")))
    # Flask-Limiter is keyed on the remote address and every test shares
    # 127.0.0.1, so the app's own "300 per minute" default — and the tighter
    # 10/min on login — would start returning
    # 429 to unrelated tests as the suite grows. Tests that assert on
    # throttling opt back in with the `rate_limits_on` fixture.
    #
    # `limiter.enabled` is the switch that actually matters: Flask-Limiter
    # reads RATELIMIT_ENABLED during init_app, which already ran when `main`
    # was imported, so setting the config alone leaves limiting fully on.
    application.config["RATELIMIT_ENABLED"] = False
    limiter.enabled = False
    with application.app_context():
        assert "mode=memory" in str(db.engine.url)
    return application


@pytest.fixture
def rate_limits_on(app):
    """Re-enable real rate limiting for tests that assert a 429."""

    from extensions import limiter

    limiter.reset()
    app.config["RATELIMIT_ENABLED"] = True
    limiter.enabled = True
    yield limiter
    limiter.reset()
    app.config["RATELIMIT_ENABLED"] = False
    limiter.enabled = False


@pytest.fixture(autouse=True)
def reset_module_caches():
    """Drop process-wide caches that would otherwise leak between tests."""

    yield

    from helpers import audio_cache, i18n
    from helpers.ai import loop

    audio_cache.reset()
    i18n._translations_cache.clear()
    loop._classification_logged.cache_clear()


@pytest.fixture(scope="session")
def external_events():
    FakePosthogClient.instances.clear()
    yield FakePosthogClient.instances
    FakePosthogClient.instances.clear()

SUITES = {
    "unit": "fast deterministic helper and model behavior",
    "web": "Flask request and public route contracts",
    "integration": "database, filesystem, PDF, and CLI boundaries",
    "slow": "tests intentionally outside the fast default",
    "external": "tests requiring a real external service (never default)",
}


#: Which directory each marker's layer lives in, for changed-code selection.
SUITE_DIRS = {
    "unit": "tests/unit",
    "web": "tests/web",
    "integration": "tests/integration",
    "slow": "tests",
    "external": "tests",
}

#: Repo root: this file sits one level down, in tests/.
ROOT = Path(__file__).resolve().parent.parent

_SELECTION_CACHE = ".pytest_cache/changed_selection.json"


def pytest_addoption(parser):
    parser.addoption(
        "--suite",
        action="store",
        default="fast",
        help="Run fast (unit/web), all, or a comma-separated marker selection.",
    )
    parser.addoption(
        "--all-tests",
        action="store_true",
        default=bool(os.environ.get("PYTEST_ALL_TESTS")),
        help="Skip changed-code selection and run the whole selected suite.",
    )


def _wanted_suites(config):
    raw = config.getoption("--suite")
    if raw == "all":
        wanted = {"unit", "web", "integration"}
    elif raw == "fast":
        wanted = {"unit", "web"}
    else:
        wanted = {part.strip() for part in raw.split(",") if part.strip()}

    unknown = wanted - set(SUITES)
    if unknown:
        raise pytest.UsageError(
            "unknown suite(s): {}; choose fast, all, or: {}".format(", ".join(sorted(unknown)), ", ".join(sorted(SUITES)))
        )
    return wanted


def _narrowing_is_safe(config):
    """Only narrow a plain, unfiltered run of the configured testpaths."""

    if config.getoption("--all-tests"):
        return False
    if config.getoption("keyword", "") or config.getoption("markexpr", ""):
        return False
    if config.getoption("last_failed", False) or config.getoption("failed_first", False):
        return False

    source = getattr(config, "args_source", None)
    if source is not None:
        return source is type(source).TESTPATHS
    # Older pytest: fall back to "were any paths named on the command line?"
    return not [
        arg
        for arg in config.invocation_params.args
        if not arg.startswith("-") and ("::" in arg or Path(arg).exists())
    ]


def pytest_configure(config):
    for name, description in SUITES.items():
        config.addinivalue_line("markers", f"{name}: {description}")

    config._changed_selection = None
    config._changed_note = None
    if not _narrowing_is_safe(config):
        return

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from scripts import change_selection as engine

        wanted = _wanted_suites(config)
        cache_path = ROOT / _SELECTION_CACHE
        cache = engine.load_cache(cache_path)
        notes = []
        config._changed_selection = engine.compute_selection(
            ROOT,
            sorted({SUITE_DIRS.get(mark, "tests") for mark in wanted}),
            cache=cache,
            wanted_marks=wanted,
            notes=notes,
        )
        engine.save_cache(cache_path, cache)
        if notes:
            config._changed_note = f"changed: full suite ({notes[0]})"
    except Exception as error:  # noqa: BLE001 - never let a bug in the selection engine break a test run; falls back to the note below rather than crashing collection
        config._changed_note = f"changed: selection skipped ({error})"


def pytest_sessionstart(session):
    """Rebuild static/css/tailwind.css first when a CSS/template source is newer.

    No test reads the built file, but the dev server and every page checked in a
    browser do — so a local run catches it up. CI has no build to keep fresh, and
    under xdist only the controller builds.
    """

    if os.environ.get("CI") or hasattr(session.config, "workerinput"):
        return
    try:
        from scripts.tailwind import OUTPUT, build_if_stale

        code = build_if_stale()
    except Exception as error:  # noqa: BLE001 - a CSS build problem (binary download, missing pytailwindcss) must never block a test run
        note, ok = f"tailwind: rebuild skipped ({error})", False
    else:
        if code is None:
            return
        ok = code == 0
        note = f"tailwind: rebuilt {OUTPUT}" if ok else f"tailwind: build FAILED (exit {code}), {OUTPUT} is stale"
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(note, green=ok, yellow=not ok)


def pytest_ignore_collect(collection_path, config):
    """Keep unselected test modules from being imported at all.

    This is where most of the saving is: a deselected test still costs its
    module's import, and a narrow selection touches a handful of files.
    """

    selection = getattr(config, "_changed_selection", None)
    if selection is None:
        return None
    path = Path(collection_path)
    if path.is_dir() or path.suffix != ".py" or not path.name.startswith("test_"):
        return None
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return relative not in selection.files


def pytest_collection_modifyitems(config, items):
    wanted = _wanted_suites(config)

    selected, deselected = [], []
    for item in items:
        marks = {mark.name for mark in item.iter_markers()}
        (selected if marks & wanted else deselected).append(item)

    selection = getattr(config, "_changed_selection", None)
    if selection is not None:
        reached, unreached = [], []
        for item in selected:
            relative = Path(str(item.path)).relative_to(ROOT).as_posix()
            name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
            (reached if name in selection.files.get(relative, ()) else unreached).append(item)
        if reached:
            selected, deselected = reached, deselected + unreached
        else:
            # The marker filter emptied the selection; run what the suite says
            # rather than reporting green on nothing.
            config._changed_selection = None
            config._changed_note = "changed: full suite (selection matched no runnable test)"

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def pytest_report_header(config):
    lines = [f"suite: {config.getoption('--suite')}"]
    selection = getattr(config, "_changed_selection", None)
    if selection is not None:
        reasons = "; ".join(selection.reasons[:3])
        if len(selection.reasons) > 3:
            reasons += f"; +{len(selection.reasons) - 3} more"
        lines.append(
            f"changed: {selection.count} of {selection.total_tests} tests "
            f"in {len(selection.files)} file(s) [{reasons}]; --all-tests runs everything"
        )
    elif config.getoption("--all-tests"):
        lines.append("changed: selection off (--all-tests)")
    elif _narrowing_is_safe(config):
        lines.append(
            getattr(config, "_changed_note", None) or "changed: full suite"
        )
    return lines


def pytest_collection_finish(session):
    """A group that matched nothing must fail loudly — 0 tests reads as green.

    Only when no `-k` is in play; narrowing to nothing with an expression is a
    normal thing to do while iterating.
    """
    config = session.config
    if not session.items and not config.getoption("keyword"):
        raise pytest.UsageError(
            f"--suite={config.getoption('--suite')} selected 0 tests; nothing was checked"
        )
