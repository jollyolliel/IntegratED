"""Component-tag lint for `.jx` files, on jx's own parser (`jx.parse_ast` + `jx.walk`).

ast-grep's HTML parser loses attributes after an unquoted `{{ a > b }}`; jx's
parser reads every attribute exactly. What each component allows comes from
helpers/clay_primitives.py. Run over the repo by tests/unit/test_lint_jx.py.

A component under templates/components/ may restyle the bases it builds on:
that is how a composed component reaches its look. A page may not, unless the
tag carries a `{# design: override — <reason> #}` comment on its own line or
the line before.
"""

from __future__ import annotations

import functools
import os
import re
import sys
from dataclasses import dataclass

import jx
import yaml
from jx.lexer import AttrKind
from jx.nodes import Comment, Component, Raw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from helpers.clay_primitives import COMPONENTS, Spec


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


def _literal(attr) -> str | None:
    """A quoted attribute's text, or None for an expression or a bare flag."""
    if attr.kind is not AttrKind.STRING or attr.value is None:
        return None
    return attr.value[1:-1]


def _unknown_prop_values(tag: Component, spec: Spec, path: str) -> list[Finding]:
    findings = []
    for attr in tag.attrs:
        prop = spec.props.get(attr.name)
        value = _literal(attr)
        if prop is None or value is None or value in prop.allowed:
            continue
        shown = f" (one of: {', '.join(prop.allowed)})" if len(prop.allowed) <= 10 else ""
        findings.append(Finding(
            path, attr.span.line, "unknown-prop-value",
            f"<{tag.name}> {attr.name}={value!r} is not allowed{shown}.",
        ))
    return findings


@functools.cache
def _restyle_rule(rule_id: str) -> tuple[re.Pattern, str]:
    """(banned utilities, message) of lint/rules/<rule_id>.yml — a component tag is already the element."""
    with open(os.path.join(ROOT, "lint", "rules", f"{rule_id}.yml"), encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    _element, utilities = config["rule"]["all"]
    return re.compile(utilities["regex"]), config["message"].strip()


def _restyled(tag: Component, spec: Spec, path: str) -> list[Finding]:
    if spec.restyle_rule is None:
        return []
    utilities, message = _restyle_rule(spec.restyle_rule)
    return [
        Finding(path, attr.span.line, "no-restyle-on-component", f"<{tag.name} class=\"{value}\">: {message}")
        for attr in tag.attrs
        if attr.name == "class" and (value := _literal(attr)) is not None and utilities.search(value)
    ]


#: Which component's file may write each clay class.
OWNERS = {name: spec.file for spec in COMPONENTS.values() for name in spec.owned}
#: Composed and shell components restyle bases freely; the restyle rules guard pages.
COMPONENT_FOLDER = "templates/components/"
#: `{# design: override — <reason> #}`: a page's deliberate step off the design.
OVERRIDE_RE = re.compile(r"design:\s*override\b\W*(.*?)\s*#\}$", re.DOTALL)

# An HTML or component `class="…"` attribute. The leading space keeps
# `attrs.render(class="…")` out: a base's own markup is written that way.
CLASS_ATTR_RE = re.compile(r"""(?<=\s)class\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _without(source: str, spans) -> str:
    """`source` with each span blanked to spaces, newlines kept so lines still line up."""
    chars = list(source)
    for span in spans:
        for index in range(span.start, span.end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _raw_clay_classes(markup: str, path: str) -> list[Finding]:
    own_file = path.replace(os.sep, "/")
    findings = []
    for match in CLASS_ATTR_RE.finditer(markup):
        names = set((match.group(1) or match.group(2) or "").split())
        line = markup.count("\n", 0, match.start()) + 1
        foreign = sorted(name for name in names if name in OWNERS and OWNERS[name] != own_file)
        if foreign:
            findings.append(Finding(
                path, line, "no-raw-clay-class",
                f"{', '.join(foreign)} belongs to a component "
                f"({', '.join(sorted({OWNERS[name] for name in foreign}))}); use the component instead.",
            ))
    return findings


SELECT_OPEN_RE = re.compile(r"<select\b")
BUTTON_FIRST_RE = re.compile(r"\s*<button>\s*<selectedcontent")
LISTBOX_RE = re.compile(r"\bmultiple\b|\bsize\s*=\s*[\"']?(?:[2-9]|\d\d)")
JINJA_CLOSE = {"{{": "}}", "{%": "%}"}


def _select_open_tags(markup: str):
    """(start, attributes, end) of each `<select …>` open tag, `end` just past its `>`. Jinja inside
    the tag may hold a `>`, so a `{{`/`{%` block is skipped whole, to its own close; a tag whose block
    or `>` never closes is not a tag."""
    # A hand scan, not one regex: CodeQL flags the equivalent pattern as exponential backtracking.
    pos = 0
    while (match := SELECT_OPEN_RE.search(markup, pos)) is not None:
        i = match.end()
        while i < len(markup) and markup[i] != ">":
            close = JINJA_CLOSE.get(markup[i:i + 2])
            if close is None:
                i += 1
                continue
            found = markup.find(close, i + 2)
            i = len(markup) if found == -1 else found + 2
        if i < len(markup):
            yield match.start(), markup[match.end():i], i + 1
            pos = i + 1
        else:
            pos = match.end()


def _selects_without_button(markup: str, path: str) -> list[Finding]:
    """A single-choice `<select>` must open with `<button><selectedcontent></selectedcontent></button>`:
    it is what `appearance: base-select` draws as the closed control (docs/ui-design/page-behaviour.md)."""
    return [
        Finding(
            path, markup.count("\n", 0, start) + 1, "select-without-button",
            "A <select> opens with <button><selectedcontent></selectedcontent></button>, "
            "or Chromium drops the clay picker.",
        )
        for start, attributes, end in _select_open_tags(markup)
        if not BUTTON_FIRST_RE.match(markup, end) and not LISTBOX_RE.search(attributes)
    ]


def _overrides(comments: list[Comment], path: str) -> tuple[set[int], list[Finding]]:
    """The lines a `{# design: override — reason #}` comment frees from the restyle rules (its own
    line and the next), and a finding for each such comment that gives no reason."""
    lines: set[int] = set()
    findings = []
    for comment in comments:
        match = OVERRIDE_RE.search(comment.value)
        if match is None:
            continue
        if not match.group(1):
            findings.append(Finding(
                path, comment.span.line, "override-without-reason",
                "A design override says why: {# design: override — <reason> #}.",
            ))
            continue
        end = comment.span.line + comment.value.count("\n")
        lines |= {end, end + 1}
    return lines, findings


#: ast-grep's HTML parser reads a <Script>/<Style> body as raw text, so no rule would see inside.
RESERVED_NAMES = frozenset({"Script", "Style"})
#: `{#import "<jx name>" as <Alias> #}`
IMPORT_RE = re.compile(r"""^\s*["']([^"']+)["']\s+as\s+(\w+)\s*$""")
#: A constrained component by its jx name: `@` + its path under templates/ (helpers/jx_catalog.py).
BY_JX_NAME = {"@" + spec.file.removeprefix("templates/"): spec for spec in COMPONENTS.values()}


def _reserved(name: str, line: int, path: str) -> list[Finding]:
    if name not in RESERVED_NAMES:
        return []
    return [Finding(
        path, line, "reserved-component-name",
        f"A component may not be named {name}: ast-grep would read its body as raw text. Rename it.",
    )]


def _quoted_expressions(tag: Component, path: str) -> list[Finding]:
    """A quoted attribute on a component tag is literal text in jx: `class="a {{ b }}"` renders
    the characters `{{ b }}`. The expression form is `class={{ "a " ~ b }}`."""
    return [
        Finding(
            path, attr.span.line, "quoted-expression",
            f"<{tag.name} {attr.name}=\"...\"> is literal text in jx; write {attr.name}={{{{ ... }}}} instead.",
        )
        for attr in tag.attrs
        if "{{" in (_literal(attr) or "")
    ]


def lint_jx(source: str, path: str) -> list[Finding]:
    """Every finding in one `.jx` file, in source order."""
    document = jx.parse_ast(source, name=path)
    findings: list[Finding] = []
    imported: dict[str, str] = {}  # alias -> jx name
    for declaration in document.declarations:
        match = IMPORT_RE.match(declaration.expr) if declaration.keyword == "import" else None
        if match:
            imported[match.group(2)] = match.group(1)
            findings += _reserved(match.group(2), declaration.span.line, path)
    nodes = jx.walk(document)
    overridden, override_findings = _overrides([node for node in nodes if isinstance(node, Comment)], path)
    findings += override_findings
    in_component = path.replace(os.sep, "/").startswith(COMPONENT_FOLDER)
    for node in nodes:
        if not isinstance(node, Component):
            continue
        findings += _reserved(node.name, node.span.line, path)
        findings += _quoted_expressions(node, path)
        # By import path, not alias: `as Btn` is still the clay Button.
        spec = BY_JX_NAME.get(imported.get(node.name, ""))
        if spec is not None:
            findings += _unknown_prop_values(node, spec, path)
            if not in_component:
                findings += [f for f in _restyled(node, spec, path) if f.line not in overridden]
    markup = _without(source, [node.span for node in nodes if isinstance(node, (Comment, Raw))])
    findings += _raw_clay_classes(markup, path)
    findings += _selects_without_button(markup, path)
    return sorted(findings, key=lambda finding: finding.line)
