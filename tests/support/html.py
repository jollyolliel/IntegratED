"""Stdlib HTML helpers for component tests: find elements in rendered markup."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None]
    #: Child elements and text runs, in document order.
    nodes: list[Element | str] = field(default_factory=list)

    @property
    def children(self) -> list[Element]:
        return [node for node in self.nodes if isinstance(node, Element)]

    @property
    def classes(self) -> list[str]:
        return str(self.attrs.get("class") or "").split()

    def find_all(self, tag: str | None = None, cls: str | None = None) -> list[Element]:
        found = []
        for child in self.children:
            if (tag is None or child.tag == tag) and (cls is None or cls in child.classes):
                found.append(child)
            found += child.find_all(tag, cls)
        return found

    def find(self, tag: str | None = None, cls: str | None = None) -> Element:
        found = self.find_all(tag, cls)
        assert found, f"no <{tag or '*'}{' .' + cls if cls else ''}> in the markup"
        return found[0]

    @property
    def all_text(self) -> str:
        parts = [node if isinstance(node, str) else node.all_text for node in self.nodes]
        return " ".join(" ".join(parts).split())


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.stack[-1].nodes.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].nodes.append(Element(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        nodes = self.stack[-1].nodes
        if nodes and isinstance(nodes[-1], str):
            nodes[-1] += data
        else:
            nodes.append(data)


def parse(markup: str) -> Element:
    """The markup's element tree under a `#root` element."""
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    return builder.root

