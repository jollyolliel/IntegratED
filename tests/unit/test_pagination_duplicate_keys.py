"""Lint: no template renders two `<Pagination>` pagers sharing a `key` — they'd write the same
query-string field and fight over the same page number (docs/ui-design/page-behaviour.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

_TAG_RE = re.compile(r"<Pagination\b(.*?)/>", re.DOTALL)
_KEY_RE = re.compile(r"""key\s*=\s*['"]([^'"]*)['"]""")


def _keys(text: str) -> list[str]:
    """The `key` of every pager in one template, in order; a pager with none is `"page"`."""
    return [(match.group(1) if (match := _KEY_RE.search(tag)) else "page") for tag in _TAG_RE.findall(text)]


def _keys_per_file():
    """{template path under templates/: [key, key, ...]} for every file with >=1 pager."""
    result = {}
    for path in TEMPLATES_DIR.rglob("*.jx"):
        keys = _keys(path.read_text(encoding="utf-8"))
        if keys:
            result[path.relative_to(TEMPLATES_DIR).as_posix()] = keys
    return result


def test_every_template_with_multiple_pagers_keys_them_uniquely():
    offenders = []
    for rel_path, keys in _keys_per_file().items():
        seen = set()
        dupes = set()
        for key in keys:
            if key in seen:
                dupes.add(key)
            seen.add(key)
        if dupes:
            offenders.append(f"{rel_path}: shared key(s) {sorted(dupes)!r} across {len(keys)} pagers")

    assert not offenders, "\n".join(offenders)


def test_the_lint_reads_pagination_tags_in_jx():
    source = (
        '<Pagination endpoint="x.y" page={{ a }} total_pages={{ n }} key="teacher" />\n'
        '<Pagination endpoint="x.y" page={{ b }}\n  total_pages={{ n }} />\n'
    )

    assert _keys(source) == ["teacher", "page"]


def test_the_lint_covers_the_jx_page_with_three_pagers():
    assert sorted(_keys_per_file()["page_components/school_admin/people_results.jx"]) == [
        "learner", "teacher", "volunteer",
    ]
