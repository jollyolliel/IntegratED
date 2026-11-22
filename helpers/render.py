"""`render_template` for both template kinds: `.jx` through the jx catalog, the rest through Flask."""

from __future__ import annotations

from typing import Any

import flask
from flask import current_app


def render_template(template_name: str, /, **context: Any) -> str:
    """A `.jx` page gets the context-processor values (`t`, `current_user`, …) as globals every nested
    component sees, and `context` as props. Any other name goes to Flask unchanged."""
    if not template_name.endswith(".jx"):
        return flask.render_template(template_name, **context)
    ctx: dict[str, Any] = {}
    current_app.update_template_context(ctx)
    for key in context:  # the route's value wins, as in Flask; jx globals would override props
        ctx.pop(key, None)
    return current_app.extensions["jx"].render(template_name, globals=ctx, **context)
