"""No live variant session may be committed: each must be accepted or discarded first.

This fails on purpose while a session is open (scripts/live.py). Plain pytest
narrows to the diff, so it runs in CI and under --all-tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
_LEFTOVER_RE = re.compile(r'data-live-session="([^"]*)"|\{# live:(\S*)')


def find_leftovers(templates: Path) -> list[str]:
    """One message per session still open in a file under `templates`."""
    found, seen = [], set()
    for path in sorted(p for p in templates.rglob("*") if p.is_file()):
        rel = path.relative_to(templates.parent).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            match = _LEFTOVER_RE.search(line)
            if not match:
                continue
            sid = match.group(1) or match.group(2) or "?"
            if (rel, sid) not in seen:
                seen.add((rel, sid))
                found.append(
                    f"{rel}:{number} live session {sid} is still open — accept or discard it "
                    "(uv run scripts/live.py status)"
                )
    return found


def test_the_guard_names_each_open_session_once(tmp_path):
    pages = tmp_path / "templates" / "pages"
    pages.mkdir(parents=True)
    (pages / "clean.jx").write_text("<p>hi</p>\n", encoding="utf-8")
    (pages / "open.jx").write_text(
        '<p>a</p>\n{# live:a1b2c3d4 start #}\n<div data-live-session="a1b2c3d4">\n</div>\n{# live:a1b2c3d4 end #}\n',
        encoding="utf-8",
    )
    (pages / "stray.jx").write_text(
        '<div data-live-session="0000beef"></div>\n', encoding="utf-8"
    )

    assert find_leftovers(tmp_path / "templates") == [
        "templates/pages/open.jx:2 live session a1b2c3d4 is still open — accept or discard it (uv run scripts/live.py status)",
        "templates/pages/stray.jx:1 live session 0000beef is still open — accept or discard it (uv run scripts/live.py status)",
    ]


def test_no_live_session_is_left_in_templates():
    leftovers = find_leftovers(ROOT / "templates")

    assert not leftovers, "\n".join(leftovers)


# Everything scripts/live.py can put into markup: any data-live-* attribute
# (wrappers, <style data-live-base>/<style data-live-css>, knobs) and the
# variants-file comments, which only belong in .live/<id>.jx.
_LIVE_MARKUP_RE = re.compile(
    r"data-live-[a-z-]+|\{# live:|\{# variant name=|\{# knobs\b"
)
_MARKUP_SUFFIXES = {".jx", ".html", ".css", ".js", ".svg"}


def find_live_markup(*folders: Path) -> list[str]:
    """One message per line under `folders` still carrying live markup."""
    found = []
    for folder in folders:
        files = sorted(p for p in folder.rglob("*") if p.suffix in _MARKUP_SUFFIXES)
        for path in files:
            rel = path.relative_to(folder.parent).as_posix()
            text = path.read_text(encoding="utf-8", errors="ignore")
            for number, line in enumerate(text.splitlines(), start=1):
                hits = sorted(set(_LIVE_MARKUP_RE.findall(line)))
                if hits:
                    found.append(
                        f"{rel}:{number} live markup left behind: {', '.join(hits)}"
                    )
    return found


def test_the_markup_guard_catches_what_the_session_guard_misses(tmp_path):
    templates, static = tmp_path / "templates", tmp_path / "static"
    (templates / "pages").mkdir(parents=True)
    (static / "css").mkdir(parents=True)
    (templates / "pages" / "clean.jx").write_text(
        '<div data-lively="no" class="live">live: fine</div>\n', encoding="utf-8"
    )
    (templates / "pages" / "half.jx").write_text(
        '<p>a</p>\n<div data-live-variant="2" data-live-name="Bold">\n'
        "<style data-live-base>x{}</style>\n</div>\n",
        encoding="utf-8",
    )
    (templates / "pages" / "pasted.jx").write_text(
        '{# variant name="Louder" #}\n{# knobs [] #}\n<p>b</p>\n', encoding="utf-8"
    )
    (static / "css" / "page.css").write_text(
        '[data-live-variant="1"] .hero{color:red}\n', encoding="utf-8"
    )
    (static / "css" / "photo.png").write_bytes(b"data-live-variant")

    assert find_live_markup(templates, static) == [
        "templates/pages/half.jx:2 live markup left behind: data-live-name, data-live-variant",
        "templates/pages/half.jx:3 live markup left behind: data-live-base",
        "templates/pages/pasted.jx:1 live markup left behind: {# variant name=",
        "templates/pages/pasted.jx:2 live markup left behind: {# knobs",
        "static/css/page.css:1 live markup left behind: data-live-variant",
    ]


def test_no_live_markup_is_left_in_html():
    leftovers = find_live_markup(ROOT / "templates", ROOT / "static")

    assert not leftovers, "\n".join(leftovers)
