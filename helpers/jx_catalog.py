"""The jx component catalog, built without importing `main`.

Tests and `jx.tools.check_all()` build it with no secrets and no seeding;
`create_app()` builds the same catalog on `app.jinja_env`.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from pathlib import Path

import jinja2
import jx
from flask import current_app, has_app_context
from heroicons.jinja import heroicon_outline
from markupsafe import Markup

from helpers.clay_primitives import COMPONENTS, ICON_FLIP_RTL, ICON_SIZES

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

#: The folders under templates/ that hold `.jx` files, each its own catalog prefix.
JX_FOLDERS = ("components", "page_components", "pages")

#: The page-domain stylesheets in static/css/pages/ a `<Page styles="...">` may link.
STYLE_PARTIALS = tuple(sorted(path.stem for path in (ROOT / "static/css/pages").glob("*.css")))


def clay_check(component: str, prop: str, value, allowed: Collection, default):
    """`value` when it's in `allowed`; otherwise `default`, logged — or a ValueError under `app.testing`."""
    if value in allowed:
        return value
    choices = f" (one of: {', '.join(map(str, allowed))})" if len(allowed) <= 10 else ""
    message = f"<{component}> {prop}={value!r} is not allowed{choices}"
    if has_app_context() and current_app.testing:
        raise ValueError(message)
    logger.warning("%s; falling back to %r", message, default)
    return default


def prop(component: str, name: str, value=None):
    """A component's `name` prop: its declared default when unset, else `value` via `clay_check`."""
    spec = COMPONENTS[component].props[name]
    if value is None:
        return spec.default
    return clay_check(component, name, value, spec.allowed, spec.default)


def look(component: str, name: str, value, part: str) -> str:
    """What `value` of a component's `name` prop renders in its `part` table (`Prop.looks`): the
    prop's default when unset; a value the table leaves out goes through `clay_check`."""
    spec = COMPONENTS[component].props[name]
    table = spec.looks[part]
    fallback = spec.default if spec.default in table else next(iter(table))
    value = clay_check(component, name, spec.default if value is None else value, tuple(table), fallback)
    return table[value]


#: Checked on every icon render, so a set rather than the registry's ~300-name tuple.
_ICON_NAMES = frozenset(COMPONENTS["Icon"].props["name"].allowed)


def icon(name: str, size: str | None = None, **attrs) -> Markup:
    """A heroicons outline SVG, stroke 2, sized by class; horizontal arrows mirror in RTL. Extra
    `attrs` land on the `<svg>`, a `class` after the size classes."""
    props = COMPONENTS["Icon"].props
    size = props["size"].default if size is None else size
    checked_name = clay_check("Icon", "name", name, _ICON_NAMES, props["name"].default)
    checked_size = clay_check("Icon", "size", size, props["size"].allowed, props["size"].default)
    if checked_name is None:
        return Markup("")
    classes = ICON_SIZES[checked_size] + (" icon-flip-rtl" if checked_name in ICON_FLIP_RTL else "")
    extra = attrs.pop("class", "")
    attrs["class"] = f"{classes} {extra}".strip()
    return Markup(heroicon_outline(checked_name, size=None, stroke_width="2", **attrs))


def build_catalog(jinja_env: jinja2.Environment | None = None, *, auto_reload: bool = True) -> jx.Catalog:
    """Catalog over templates/{components,page_components,pages}. Every `.jx` is named `@` + its path
    under templates/ (`@components/base/button.jx`, `@pages/teacher/x.jx`) in imports and render calls — never `./`/`../`."""
    catalog = jx.Catalog(
        jinja_env=jinja_env, auto_reload=auto_reload,
        clay_check=clay_check, icon=icon, look=look, prop=prop, style_partials=STYLE_PARTIALS,
    )
    for folder in JX_FOLDERS:
        catalog.add_folder(TEMPLATES / folder, prefix=folder)
    return catalog
