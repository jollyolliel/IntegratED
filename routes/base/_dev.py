"""Dev-only component gallery (spec 02): every shared component in templates/components/, in
every allowed value, at /dev/components. The page shells are whole documents, so each renders
on its own at /dev/components/shell/<name> and the gallery frames it. Both 404 outside development.
`?lang=<code>` switches this session's UI language, as the language picker does (`?lang=ar` for RTL).
No PostHog events and no translation keys: it is a developer tool."""

from __future__ import annotations

from types import SimpleNamespace

from flask import abort, request, session

from helpers.clay_primitives import COMPONENTS
from helpers.i18n import NATIVE_LANGS
from helpers.render import render_template
from routes.base import base_bp
from settings import get_settings

GALLERY = "@pages/dev/components.jx"
SHELLS = ("game", "legal", "library", "announcement", "assistant")


def _dev_only() -> None:
    if not get_settings().is_development:
        abort(404)
    lang = request.args.get("lang")
    if lang in NATIVE_LANGS:
        session["ui_lang"] = lang


def _demo() -> SimpleNamespace:
    """Sample data for the components that render records."""
    maths = SimpleNamespace(id=1, title="Fractions 1", subject="Maths", topic="Fractions", file_type="pdf")
    english = SimpleNamespace(id=2, title="Everyday words", subject="English", topic=None, file_type="md")
    pair = SimpleNamespace(
        worksheets=[maths],
        learner=SimpleNamespace(name="Amina", username="amina"),
        volunteer=SimpleNamespace(name="Nikos", email="nikos@example.org"),
    )
    return SimpleNamespace(
        lesson=SimpleNamespace(title="Shapes around us", topic_id=1),
        worksheets=[maths, english],
        pairs=[pair],
        announcement=SimpleNamespace(id=0, content={
            "layout": "text_only", "badge": "New", "title": "Worksheets, one click away",
            "body": "Assign a worksheet to a pair straight from the library.",
            "cta_label": "Open the library", "cta_url": "#", "secondary_label": "Later",
        }),
        meta=[{"label": "Subject", "value": "Maths"}, {"label": "Topic", "value": "Fractions"}],
        markdown="<h2>Halves and quarters</h2><p>Colour <strong>half</strong> of each shape.</p>",
    )


@base_bp.route("/dev/components")
def component_gallery():
    _dev_only()
    return render_template(GALLERY, spec=COMPONENTS, shell=None, demo=_demo())


@base_bp.route("/dev/quiz-hint")
def quiz_hint_preview():
    """The quiz's wrong-answer card in both hint states, for designing the hint button."""
    _dev_only()
    return render_template("@pages/dev/quiz_hint.jx", lesson=_demo().lesson)


@base_bp.route("/dev/components/shell/<name>")
def component_gallery_shell(name: str):
    _dev_only()
    if name not in SHELLS:
        abort(404)
    return render_template(GALLERY, spec=COMPONENTS, shell=name, demo=_demo())
