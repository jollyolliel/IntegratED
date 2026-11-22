"""The jx guard: no `.html` template under templates/ except the permanent exceptions, and every
`render_template(...)` under routes/ and in main.py names a `.jx` page or one of those exceptions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"

#: Stays `.html` for good: the boot page.
PERMANENT_EXCEPTIONS = frozenset({
    "starting_up.html",
})


def _html_templates() -> set[str]:
    return {path.relative_to(TEMPLATES).as_posix() for path in TEMPLATES.rglob("*.html")}


def test_no_html_template_remains_except_the_exceptions():
    leftover = _html_templates() - PERMANENT_EXCEPTIONS

    assert not leftover, f"Convert these to .jx: {sorted(leftover)}"


def test_the_permanent_exceptions_still_exist():
    assert PERMANENT_EXCEPTIONS <= _html_templates()


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments, so `render_template(GALLERY)` resolves."""
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def render_template_names(source: str) -> list[tuple[int, str | None]]:
    """(line, template name) for every `render_template(...)` call in one module; the name is None
    when it is neither a string literal nor a module-level string constant."""
    tree = ast.parse(source)
    constants = _module_strings(tree)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name != "render_template":
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            calls.append((node.lineno, first.value))
        elif isinstance(first, ast.Name):
            calls.append((node.lineno, constants.get(first.id)))
        else:
            calls.append((node.lineno, None))
    return calls


def _renders_a_page(name: str | None) -> bool:
    return name is not None and (name.endswith(".jx") or name in PERMANENT_EXCEPTIONS)


def test_the_route_scan_reads_literals_constants_and_attribute_calls():
    source = (
        'PAGE = "@pages/x.jx"\n'
        'render_template("@pages/a.jx")\n'
        "render_template(PAGE)\n"
        'flask.render_template("old.html")\n'
        "render_template(name)\n"
    )

    assert render_template_names(source) == [(2, "@pages/a.jx"), (3, "@pages/x.jx"), (4, "old.html"), (5, None)]
    assert [_renders_a_page(name) for _, name in render_template_names(source)] == [True, True, False, False]


def test_every_route_renders_a_jx_page_or_a_permanent_exception():
    modules = [*sorted((ROOT / "routes").rglob("*.py")), ROOT / "main.py"]
    bad = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {name!r}"
        for path in modules
        for line, name in render_template_names(path.read_text(encoding="utf-8"))
        if not _renders_a_page(name)
    ]

    assert bad == [], "render_template must name a .jx page:\n" + "\n".join(bad)
