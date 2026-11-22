"""What counts as hard-coded text in a `.jx` template, for the i18n scanner
(scripts/translation_audit.py: its --report and its fixes).

jx's own parser (`jx.parse_ast`, as scripts/lint_jx.py uses it) reads the jx parts exactly:
`{#def}` / `{#import}` / `{# … #}` comments, component tags and their props. Plain HTML stays
opaque `Text` to it, so each scanner keeps its own HTML regexes and runs them over `markup`: the
source with comments and component tags blanked, newlines kept so line numbers still line up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import jx
from jx.lexer import AttrKind
from jx.nodes import Block, Comment, Component, Document, Fill, Slot, Text

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

#: Templates with no user-facing copy to translate (paths relative to templates/).
SKIP = frozenset({
    "components/shell/theme.jx",  # <head> scripts and stylesheets
    "pages/dev/components.jx",  # dev-only component gallery
})

#: Component props whose quoted value is shown to the user; any `*_label` prop is too.
TEXT_PROPS = frozenset({
    "label", "title", "subtitle", "sub", "message", "badge", "eyebrow", "description",
    "error", "placeholder", "alt", "aria-label",
})

CLOSING_TAG_RE = re.compile(r"</[A-Z][\w.]*\s*>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)\b[^<>]*?(/?)>")
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
})


@dataclass(frozen=True)
class JxText:
    """Hard-coded text in jx syntax: a quoted text prop (`prop` set) or bare text inside a component.

    `start`/`end` delimit the source it replaces: the whole `label="Back"`, or the text itself.
    """

    tag: str
    prop: str | None
    text: str
    line: int
    start: int
    end: int


def translatable_templates() -> list[Path]:
    """Every `.jx` template and the remaining `.html` ones, minus `SKIP`, in path order."""
    paths = [*TEMPLATES_DIR.rglob("*.jx"), *TEMPLATES_DIR.rglob("*.html")]
    return sorted(
        path for path in paths
        if str(path.relative_to(TEMPLATES_DIR)).replace("\\", "/") not in SKIP
    )


def _is_text_prop(name: str) -> bool:
    return name in TEXT_PROPS or name.endswith("_label")


def _has_words(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", text)) and "{{" not in text


def _blank(source: str, ranges: list[tuple[int, int]]) -> str:
    """`source` with each range blanked to spaces, newlines kept."""
    chars = list(source)
    for start, end in ranges:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _outside_html(markup: str) -> bool:
    """Whether the end of `markup` (Jinja and component tags already blanked) sits outside every
    HTML tag and element it opens."""
    if markup.rfind("<") > markup.rfind(">"):
        return False  # inside a tag, or an <!-- comment
    depth = 0
    for match in HTML_TAG_RE.finditer(markup):
        closing, tag, self_closing = match.groups()
        if closing:
            depth -= 1
        elif not self_closing and tag.lower() not in VOID_ELEMENTS:
            depth += 1
    return depth == 0


def _component_texts(node, owner: Component | None, plain: str, scripts: list[tuple[int, int]]) -> list[JxText]:
    """Bare text whose nearest enclosing tag is a component (`owner`): outside every HTML element
    opened inside that component (text in those is the HTML regexes' job) and outside <script> and
    <style>. Jinja blocks, fills and slots are transparent. jx splits text around each `{{ }}`, so
    where a run sits is read from `plain`, the source with Jinja and component tags blanked."""
    found: list[JxText] = []
    if isinstance(node, Component):
        for child in node.children:
            found += _component_texts(child, node, plain, scripts)
    elif isinstance(node, Document):
        for child in node.children:
            found += _component_texts(child, None, plain, scripts)
    elif isinstance(node, (Block, Fill, Slot)):
        children = node.children if isinstance(node, Block) else node.body if isinstance(node, Fill) else node.default
        for child in children:
            found += _component_texts(child, owner, plain, scripts)
    elif isinstance(node, Text) and owner is not None:
        for run in re.finditer(r"[^<>]+", node.value):
            text = run.group().strip()
            offset = node.span.start + run.start() + (len(run.group()) - len(run.group().lstrip()))
            if (not _has_words(text) or any(start <= offset < end for start, end in scripts)
                    or not _outside_html(plain[owner.span.end:offset])):
                continue
            found.append(JxText(owner.name, None, text, plain.count("\n", 0, offset) + 1, offset, offset + len(text)))
    return found


def scan_jx(source: str, name: str) -> tuple[str, list[JxText]]:
    """(`markup` for the HTML regexes, the hard-coded text found in jx syntax) of one `.jx` file."""
    document = jx.parse_ast(source, name=name)
    blanked: list[tuple[int, int]] = []
    items: list[JxText] = []
    for node in jx.walk(document)[1:]:
        if isinstance(node, Comment):
            blanked.append((node.span.start, node.span.end))
        elif isinstance(node, Component):
            blanked.append((node.span.start, node.span.end))
            for attr in node.attrs:
                if attr.kind is not AttrKind.STRING or attr.value is None or not _is_text_prop(attr.name):
                    continue
                text = attr.value[1:-1].strip()
                if _has_words(text):
                    items.append(JxText(node.name, attr.name, text, attr.span.line, attr.span.start, attr.span.end))
    blanked += [match.span() for match in CLOSING_TAG_RE.finditer(source)]
    markup = _blank(source, blanked)
    plain = _blank(markup, [match.span() for match in JINJA_RE.finditer(markup)])
    scripts = [match.span() for match in SCRIPT_STYLE_RE.finditer(source)]
    items += _component_texts(document, None, plain, scripts)
    return markup, sorted(items, key=lambda item: item.start)


def replacement(item: JxText, key: str) -> str:
    """The translated source for `item`: `label={{ t('key') }}` for a prop, `{{ t('key') }}` for text."""
    call = "{{ t('" + key + "') }}"
    return f"{item.prop}={call}" if item.prop else call
