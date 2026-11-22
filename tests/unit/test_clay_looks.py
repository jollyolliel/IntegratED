"""`Prop.looks` in helpers/clay_primitives.py and the `look` env global that reads it.

A component's per-value classes live in one table beside the values it allows, so a value can't be
allowed without its classes: an entry outside `allowed` fails at import, and a value a table leaves
out is rejected like an unknown value instead of rendering an empty class.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_a_looks_table_may_not_name_a_value_the_prop_does_not_allow():
    from helpers.clay_primitives import Prop

    with pytest.raises(ValueError, match="purple"):
        Prop(("sky", "green"), "sky", looks={"colour": {"sky": "btn-sky", "purple": "btn-purple"}})


def test_look_returns_a_values_classes_from_the_named_table(app):
    from helpers.jx_catalog import look

    with app.app_context():
        assert look("Button", "variant", "sky", "colour") == "btn-sky"


def test_look_reads_the_props_default_when_the_value_is_unset(app):
    from helpers.jx_catalog import look

    with app.app_context():
        assert look("Card", "tone", None, "static") == "clay-card"


def test_look_rejects_a_value_its_table_leaves_out(app):
    from helpers.jx_catalog import look

    with app.app_context(), pytest.raises(ValueError, match="Card.*tone.*purple"):
        look("Card", "tone", "purple", "clickable")


def test_look_falls_back_to_the_default_outside_testing(app, monkeypatch):
    from helpers.jx_catalog import look

    monkeypatch.setattr(app, "testing", False)
    with app.app_context():
        assert look("Card", "tone", "purple", "clickable") == "quick-action-card"


def test_an_owned_looks_table_counts_toward_the_components_classes():
    from helpers.clay_primitives import COMPONENTS

    assert {"btn-clay", "btn-flat", "btn-sky", "btn-large"} <= COMPONENTS["Button"].owned


def test_a_utility_looks_table_is_not_owned():
    from helpers.clay_primitives import COMPONENTS

    assert "text-primary" not in COMPONENTS["StatTile"].owned
