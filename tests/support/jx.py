"""jx fixtures: the `@fixtures/` test components, and one-line component renders."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jx"


COMPONENTS = Path(__file__).resolve().parents[2] / "templates" / "components"


def imports(*names: str) -> str:
    """`{#import #}` lines for shared components, found in any layer by their snake-case file:
    `imports("Button")` → `{#import "@components/base/button.jx" as Button #}`."""
    lines = []
    for name in names:
        file = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_") + ".jx"
        (path,) = COMPONENTS.rglob(file)
        lines.append(f'{{#import "@components/{path.relative_to(COMPONENTS).as_posix()}" as {name} #}}')
    return "".join(lines)


@pytest.fixture(scope="session")
def jx_fixtures(app):
    """The app's catalog, with tests/fixtures/jx/ registered as `@fixtures/`."""
    catalog = app.extensions["jx"]
    catalog.add_folder(FIXTURES, prefix="fixtures")
    return catalog


@pytest.fixture
def render_component(app, jx_fixtures):
    """`render_component("@components/base/button.jx", variant="sky")` → HTML, rendered in a request under
    `app.testing`, so a disallowed prop value raises ValueError (`clay_check`)."""
    from helpers.render import render_template

    def render(component: str, /, **props) -> str:
        with app.test_request_context("/"):
            return render_template(component, **props)

    return render


@pytest.fixture(scope="session")
def jx_scratch(jx_fixtures, tmp_path_factory):
    """A session folder registered as `@scratch/`, where `render_jx` writes each source."""
    # A real `.jx` file is autoescaped like a page; a `<string>` template would not be.
    folder = tmp_path_factory.mktemp("jx_scratch")
    jx_fixtures.add_folder(folder, prefix="scratch")
    return folder


@pytest.fixture
def render_jx(app, jx_fixtures, jx_scratch):
    """`render_jx('{#import "@components/base/button.jx" as Button #}<Button variant="sky">Go</Button>')` → HTML.

    A `.jx` source rendered as a page (context-processor values as globals, `props` as props) in a
    request to `path` under `app.testing`, so a disallowed prop value raises. `user` is signed in
    and `lang` is the session's UI language for the render."""
    from flask import session
    from flask_login import login_user

    from helpers.render import render_template

    def render(source: str, /, path: str = "/", user=None, lang=None, **props) -> str:
        name = f"s{hashlib.sha1(source.encode()).hexdigest()[:16]}.jx"
        file = jx_scratch / name
        if not file.exists():
            file.write_text(source, encoding="utf-8")
            # jx indexes a folder's files when it is added; adding it again picks up the new one.
            jx_fixtures.add_folder(jx_scratch, prefix="scratch")
        with app.test_request_context(path):
            if user is not None:
                login_user(user)
            if lang is not None:
                session["ui_lang"] = lang
            return str(render_template(f"@scratch/{name}", **props))

    return render

