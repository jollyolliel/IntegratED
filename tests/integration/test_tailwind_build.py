"""`scripts/tailwind.py` — the one CSS pipeline dev, CI and Docker share."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = ROOT / "static" / "css" / "components"
DOC_COMMENT_RE = re.compile(r"^/\*\s*\.([\w-]+):", re.MULTILINE)


@pytest.fixture(scope="module")
def built_css(tmp_path_factory):
    from scripts.tailwind import main

    out = tmp_path_factory.mktemp("tailwind") / "tailwind.css"
    try:
        code = main(["--output", str(out), "--no-minify"])
    except OSError as err:  # first run downloads the binary
        pytest.skip(f"tailwind binary unavailable: {err}")
    assert code == 0
    return out.read_text(encoding="utf-8")


def documented_classes() -> list[str]:
    names = []
    for css in sorted(COMPONENTS.glob("*.css")):
        names += DOC_COMMENT_RE.findall(css.read_text(encoding="utf-8"))
    return names


def test_every_documented_component_class_survives_the_build(built_css):
    missing = [
        name
        for name in documented_classes()
        # At the start of a selector, not only inside a compound like
        # `.btn-flat.btn-accent` — that would pass even with `.btn-accent` gone.
        if not re.search(r"(?:^|[\s,}])\." + re.escape(name) + r"(?![\w-])", built_css)
    ]

    assert missing == []


def test_every_css_variable_used_is_defined(built_css):
    # A token typo (`var(--color-primray)`) is silently empty, not an error.
    used = set(re.findall(r"var\(\s*(--[\w-]+)", built_css))
    defined = set(re.findall(r"(--[\w-]+)\s*:", built_css))
    missing = sorted(name for name in used - defined if not name.startswith("--tw-"))

    assert missing == []


def test_the_hidden_attribute_beats_a_component_display_rule(built_css):
    # Preflight's `[hidden]` is as specific as `.btn-clay` and loads first, so a clay
    # component's `display` would win and `el.hidden = true` would leave it on screen.
    assert re.search(r"\[hidden\][^{]*\{[^}]*display:\s*none\s*!important", built_css)


@pytest.mark.parametrize(
    "token",
    [
        "--color-primary", "--color-primary-dark", "--color-primary-light",
        "--color-accent", "--color-accent-dark", "--color-danger",
        "--color-surface-page", "--color-surface-card",
        "--color-ink-heading", "--color-ink-body", "--color-ink-muted",
        "--color-ink-heading-rgb", "--color-sky-200", "--color-card-sky-border",
        "--color-card-sky-shadow", "--clay-offset", "--clay-lift", "--clay-press",
        "--radius-card",
    ],
)
def test_design_tokens_are_published_on_root(built_css, token):
    root = re.search(r":root\s*\{([^}]*)\}", built_css)

    assert root is not None
    assert re.search(re.escape(token) + r"\s*:", root.group(1))


RETIRED_BUTTON_CLASS_RE = re.compile(r"(?<![\w-])(?:btn-clay-[a-z-]+|btn-mini(?:-[a-z]+)?|btn-lg|btn-sm)(?![\w-])")


def test_no_template_script_or_stylesheet_uses_a_retired_button_class():
    # Buttons are `btn-clay` + one colour (+ `btn-flat` / `btn-large`); the old
    # single-name classes no longer exist, so any leftover renders unstyled.
    sources = [
        *ROOT.glob("templates/**/*.html"),
        *ROOT.glob("static/css/pages/*.css"),
        *ROOT.glob("static/js/**/*.js"),
        *COMPONENTS.glob("*.css"),
    ]
    hits = [
        f"{path.relative_to(ROOT)}: {match}"
        for path in sources
        for match in RETIRED_BUTTON_CLASS_RE.findall(path.read_text(encoding="utf-8"))
    ]

    assert hits == []


def _write(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_a_missing_build_needs_building(tmp_path):
    from scripts.tailwind import needs_build

    _write(tmp_path / "static/css/input.css", 1000)

    assert needs_build(tmp_path)


def test_a_component_edited_after_the_build_makes_it_stale(tmp_path):
    from scripts.tailwind import needs_build

    _write(tmp_path / "static/css/tailwind.css", 1000)
    _write(tmp_path / "static/css/components/cards.css", 2000)

    assert needs_build(tmp_path)


def test_a_template_edited_after_the_build_makes_it_stale(tmp_path):
    from scripts.tailwind import needs_build

    _write(tmp_path / "static/css/tailwind.css", 1000)
    _write(tmp_path / "templates/pages/home.jx", 2000)

    assert needs_build(tmp_path)


def test_a_build_newer_than_every_source_is_fresh(tmp_path):
    from scripts.tailwind import needs_build

    _write(tmp_path / "static/css/components/cards.css", 1000)
    _write(tmp_path / "templates/pages/home.jx", 1000)
    _write(tmp_path / "static/css/tailwind.css", 2000)

    assert not needs_build(tmp_path)


def test_a_page_partial_edit_does_not_trigger_a_rebuild(tmp_path):
    # static/css/pages/*.css are linked as their own sheets, never compiled in.
    from scripts.tailwind import needs_build

    _write(tmp_path / "static/css/tailwind.css", 1000)
    _write(tmp_path / "static/css/pages/games.css", 2000)

    assert not needs_build(tmp_path)


def test_a_rebuild_that_changes_nothing_still_marks_the_build_fresh(tmp_path, monkeypatch):
    # Tailwind skips writing an identical file, so without a touch the output
    # stays older than the edited template and every run would rebuild again.
    from scripts import tailwind

    _write(tmp_path / "static/css/tailwind.css", 1000)
    _write(tmp_path / "templates/pages/home.jx", 2000)
    monkeypatch.setattr(tailwind, "main", lambda argv=None: 0)

    assert tailwind.build_if_stale(tmp_path) == 0
    assert not tailwind.needs_build(tmp_path)


def test_a_fresh_build_is_not_rebuilt(tmp_path, monkeypatch):
    from scripts import tailwind

    _write(tmp_path / "templates/pages/home.jx", 1000)
    _write(tmp_path / "static/css/tailwind.css", 2000)
    monkeypatch.setattr(tailwind, "main", lambda argv=None: pytest.fail("rebuilt a fresh build"))

    assert tailwind.build_if_stale(tmp_path) is None


def test_every_tailwind_content_glob_is_watched_for_staleness():
    # A content glob missing from SOURCE_GLOBS would let its edits ship stale CSS.
    from scripts.tailwind import SOURCE_GLOBS

    config = (ROOT / "tailwind.config.js").read_text(encoding="utf-8")
    content = re.search(r"content:\s*\[(.*?)\]", config, re.DOTALL)
    assert content is not None
    globs = [glob.removeprefix("./") for glob in re.findall(r'"([^"]+)"', content.group(1))]

    assert globs
    assert [glob for glob in globs if glob not in SOURCE_GLOBS] == []


def test_utilities_are_emitted_after_components(built_css):
    # Equal-specificity tie-break is source order: a utility on a clay element
    # must win without `!` (`class="clay-card px-4"`).
    component = built_css.index(".clay-card")
    utility = re.search(r"^\.px-4\s*\{", built_css, re.MULTILINE)

    assert utility is not None
    assert component < utility.start()
