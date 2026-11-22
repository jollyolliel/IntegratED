"""helpers/jx_catalog.py: the env globals components use, and the catalog's import boundary."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers.jx_catalog import clay_check, icon, prop

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_clay_check_passes_an_allowed_value_through(app):
    with app.app_context():
        assert clay_check("Button", "variant", "sky", ("accent", "sky"), "accent") == "sky"


def test_clay_check_raises_on_an_unknown_value_under_testing(app):
    with app.app_context(), pytest.raises(ValueError, match="Button.*variant.*acent"):
        clay_check("Button", "variant", "acent", ("accent", "sky"), "accent")


def test_clay_check_logs_and_falls_back_outside_testing(app, monkeypatch, caplog):
    monkeypatch.setitem(app.config, "TESTING", False)
    with app.app_context(), caplog.at_level(logging.WARNING):
        value = clay_check("Button", "variant", "acent", ("accent", "sky"), "accent")

    assert value == "accent"
    assert "acent" in caplog.text


@pytest.mark.parametrize(
    "name", ["chevron-double-right", "arrow-long-left", "arrow-right-circle", "arrow-uturn-left"]
)
def test_a_directional_icon_mirrors_in_rtl(app, name):
    with app.app_context():
        svg = str(icon(name))

    assert svg.startswith("<svg")
    assert "icon-flip-rtl" in svg
    assert 'stroke-width="2"' in svg


def test_a_non_directional_icon_does_not_mirror(app):
    with app.app_context():
        svg = str(icon("home", size="5"))

    assert 'class="w-5 h-5"' in svg
    assert "icon-flip-rtl" not in svg


def test_an_unknown_icon_goes_through_clay_check(app):
    with app.app_context(), pytest.raises(ValueError, match="no-such-icon"):
        icon("no-such-icon")


def test_components_can_call_the_icon_global(render_component):
    html = render_component("@fixtures/icons.jx", name="arrow-long-left")

    assert "<span><svg" in html
    assert "icon-flip-rtl" in html


def test_a_rendered_component_raises_on_an_unknown_value_under_testing(render_component):
    with pytest.raises(ValueError, match="no-such-icon"):
        render_component("@fixtures/icons.jx", name="no-such-icon")


def test_build_catalog_imports_without_main():
    # No SECRET_KEY / OAuth env: importing `main` here would raise.
    env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "GOOGLE_CLIENT_ID")}
    code = (
        "import sys\n"
        "from helpers.jx_catalog import build_catalog\n"
        "build_catalog()\n"
        "assert 'main' not in sys.modules, 'main was imported'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
        check=False,  # asserted below with stderr attached
    )

    assert result.returncode == 0, result.stderr


def test_prop_gives_the_declared_default_for_an_unset_value(app):
    with app.app_context():
        assert prop("Button", "variant", None) == "accent"


def test_prop_passes_an_allowed_value_through(app):
    with app.app_context():
        assert prop("Button", "size", "lg") == "lg"


def test_prop_raises_on_an_unknown_value_under_testing(app):
    with app.app_context(), pytest.raises(ValueError, match="Card.*tone.*blue"):
        prop("Card", "tone", "blue")


def test_render_jx_renders_a_component_tag_from_a_source_string(render_jx):
    html = render_jx('{#import "@fixtures/panel.jx" as Panel #}<div><Panel /></div>')

    assert html.startswith("<div><section")
