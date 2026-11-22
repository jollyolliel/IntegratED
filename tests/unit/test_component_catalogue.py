"""helpers/clay_primitives.py against static/css/components/ and templates/components/.

Every class the design system defines is owned by exactly one component or free for any template.
Every spec entry names a real file, and the three
layers stack: a base imports only bases, and no base or composed component imports a shell.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]

#: Names in component selectors that belong to no component: state classes toggled by scripts
#: (`.btn-lang.active`, `.mobile-menu.open`, `.confirm-modal-overlay.hidden`) and a Tailwind
#: utility (`.clay-table thead th.text-right`).
NOT_OWNED = frozenset({"active", "open", "hidden", "text-right"})


def css_classes(css: str) -> set[str]:
    """Class names in the selectors of one stylesheet."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # A statement at-rule (`@import url(...);`) has no block: drop it, or the selector after it
    # reads as part of an at-rule and is skipped.
    css = re.sub(r"@(?:import|charset|layer)[^;{]*;", "", css)
    css = re.sub(r"url\([^)]*\)", "", css)
    names: set[str] = set()
    for selector in re.findall(r"([^{}]+)\{", css):
        if selector.strip().startswith("@"):
            continue
        names |= set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", selector))
    return names


def defined_classes() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "static" / "css" / "components").glob("*.css"):
        names |= css_classes(path.read_text(encoding="utf-8"))
    return names - NOT_OWNED


def test_a_class_after_an_import_statement_is_still_found():
    css = '@import url("https://fonts.example/x.css");\n.nav-logo-font { font-family: x; }\n.a, .b:hover { color: red; }'

    assert css_classes(css) == {"nav-logo-font", "a", "b"}


def test_every_design_system_class_is_owned_or_free_exactly_once():
    from helpers.clay_primitives import COMPONENTS, FREE_CLASSES

    claimed = Counter(name for spec in COMPONENTS.values() for name in spec.owned)
    claimed.update(FREE_CLASSES)
    defined = defined_classes()

    assert sorted(defined - set(claimed)) == [], "classes nothing claims"
    assert sorted(name for name, count in claimed.items() if count > 1) == [], "classes claimed twice"
    assert sorted(set(claimed) - defined) == [], "claimed classes that no stylesheet defines"


def test_each_layer_lives_in_its_own_folder():
    from helpers.clay_primitives import COMPONENTS

    folders = {"base": "templates/components/base/", "shell": "templates/components/shell/"}
    misplaced = {
        name: spec.file for name, spec in COMPONENTS.items()
        if spec.layer in folders and not spec.file.startswith(folders[spec.layer])
        or spec.layer == "composed" and spec.file.count("/") != 2
    }

    assert misplaced == {}


IMPORT_RE = re.compile(r"""\{#import\s+"@components/([^"]+)\.jx"\s""")


def _imported_layers(path: Path) -> set[str]:
    layers = set()
    for target in IMPORT_RE.findall(path.read_text(encoding="utf-8")):
        layers.add(target.split("/")[0] if "/" in target else "composed")
    return layers


def test_a_base_builds_only_on_other_bases():
    bad = {
        path.name: _imported_layers(path) - {"base"}
        for path in (ROOT / "templates" / "components" / "base").glob("*.jx")
        if _imported_layers(path) - {"base"}
    }

    assert bad == {}


def test_no_base_or_composed_component_builds_on_a_shell():
    bad = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "templates" / "components").rglob("*.jx")
        if path.parent.name != "shell" and "shell" in _imported_layers(path)
    ]

    assert bad == []


def test_headings_take_the_display_font_everywhere():
    base = (ROOT / "static" / "css" / "components" / "base.css").read_text(encoding="utf-8")

    assert re.search(r"h1,\s*h2,\s*h3,\s*h4\s*\{[^}]*font-family:\s*'Baloo 2'", base)


def test_every_single_choice_select_takes_the_clay_look_from_the_element():
    forms = (ROOT / "static" / "css" / "components" / "forms.css").read_text(encoding="utf-8")
    single = "select:where(:not([multiple]))"

    assert re.search(rf"^{re.escape(single)}\s*\{{", forms, re.MULTILINE)
    assert f"{single}::picker(select)" in forms
    assert "clay-select" not in css_classes(forms)


def test_every_spec_entry_names_its_component_file():
    from helpers.clay_primitives import COMPONENTS

    missing = {name: spec.file for name, spec in COMPONENTS.items() if not (ROOT / spec.file).is_file()}

    assert missing == {}


def test_every_default_is_an_allowed_value():
    from helpers.clay_primitives import COMPONENTS

    bad = {
        f"{name}.{prop_name}": prop.default
        for name, spec in COMPONENTS.items()
        for prop_name, prop in spec.props.items()
        if prop.default is not None and prop.default not in prop.allowed
    }

    assert bad == {}
