"""helpers/render.py: `.jx` pages render through the jx catalog with the app's context."""

from __future__ import annotations

import pytest
from flask import session

from helpers.render import render_template

pytestmark = pytest.mark.web


def test_a_jx_page_renders_its_props_escaped(app, jx_fixtures):
    with app.test_request_context("/"):
        html = render_template("@fixtures/page.jx", title="<script>alert(1)</script>")

    assert "<h1>&lt;script&gt;alert(1)&lt;/script&gt;</h1>" in html
    assert "<script>" not in html


def test_context_processor_values_reach_a_nested_component(app, jx_fixtures):
    with app.test_request_context("/"):
        html = render_template("@fixtures/page.jx", title="x")

    assert '<section data-dir="ltr" data-signed-in="False">Home</section>' in html


def test_a_nested_component_sees_rtl_in_arabic(app, jx_fixtures):
    with app.test_request_context("/"):
        session["ui_lang"] = "ar"
        html = render_template("@fixtures/page.jx", title="x")

    assert 'data-dir="rtl"' in html
    assert ">Home<" not in html


def test_a_route_value_wins_over_a_context_processor_value_of_the_same_name(app, jx_fixtures):
    # Flask's rule for `.html`: the route's context overrides the context processors'.
    with app.test_request_context("/"):
        html = render_template("@fixtures/echo.jx", ui_lang="from-the-route")

    assert "<p>from-the-route</p>" in html
