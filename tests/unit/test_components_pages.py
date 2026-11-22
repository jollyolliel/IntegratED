"""`<Page>` and the page-family shells in templates/components/ (component-catalogue.md section 4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


# ── Page ─────────────────────────────────────────────────────────────


def test_page_is_a_full_document_with_header_main_and_footer(render_jx):
    html = render_jx(_imports("Page") + '<Page title="People"><main id="m">Body</main></Page>')
    root = parse(html)

    assert html.lstrip().lower().startswith("<!doctype html>")
    assert root.find("title").all_text == "People"
    hrefs = [link.attrs.get("href") or "" for link in root.find_all("link")]
    assert any("Baloo+2" in href for href in hrefs)
    assert any("tailwind.css" in href for href in hrefs)
    body = root.find("body")
    assert body.classes == ["min-h-screen", "flex", "flex-col"]
    assert [child.tag for child in body.children if child.tag in ("header", "main", "footer")] == ["header", "main", "footer"]


def test_page_carries_the_pager_swap_handler_once(render_jx):
    html = render_jx(_imports("Page") + '<Page title="People"><main>Body</main></Page>')

    assert html.count('closest("[data-swap-region]")') == 1


def test_page_sets_language_and_direction_on_the_html_element(render_jx):
    html_el = parse(render_jx(_imports("Page") + '<Page title="x">y</Page>', lang="ar")).find("html")

    assert (html_el.attrs["lang"], html_el.attrs["dir"]) == ("ar", "rtl")


def test_page_links_its_page_stylesheets_after_tailwind_and_then_its_head(render_jx):
    source = _imports("Page") + (
        '{% set head %}<script src="/extra.js"></script>{% endset %}'
        '<Page title="x" styles="legal matching" head={{ head }}>y</Page>'
    )
    head = parse(render_jx(source)).find("head")
    sheets = [link.attrs.get("href") or "" for link in head.find_all("link") if link.attrs.get("rel") == "stylesheet"]
    style = " ".join(s.all_text for s in head.find_all("style"))

    assert [s for s in sheets if "/static/css/" in s] == [
        "/static/css/tailwind.css", "/static/css/pages/legal.css", "/static/css/pages/matching.css",
    ]
    assert ".legal-prose" not in style
    assert "/extra.js" in [s.attrs.get("src") for s in head.find_all("script")]


def test_a_plain_string_head_is_escaped(render_jx):
    html = render_jx(_imports("Page") + '<Page title="x" head="<script>alert(1)</script>">y</Page>')

    assert "<script>alert(1)</script>" not in html


def test_page_raises_on_an_unknown_style_partial(render_jx):
    with pytest.raises(ValueError, match="Page.*styles.*nope"):
        render_jx(_imports("Page") + '<Page title="x" styles="admin nope">y</Page>')


def test_page_can_drop_its_nav_and_footer_and_restyle_its_body(render_jx):
    html = render_jx(
        _imports("Page") + '<Page title="x" nav={{ false }} footer={{ false }} body_class="h-screen">y</Page>'
    )
    body = parse(html).find("body")

    assert not body.find_all("header")
    assert not body.find_all("footer")
    assert body.classes == ["h-screen"]


def test_page_forwards_a_pending_announcement_to_the_header(render_jx):
    announcement = SimpleNamespace(id=7, content={"layout": "text_only", "title": "New", "body": "b"})
    html = render_jx(_imports("Page") + '{#def a #}<Page title="x" announcement={{ a }}>y</Page>', a=announcement)

    assert 'id="feature-announcement-overlay"' in html


# ── GamePage ─────────────────────────────────────────────────────────


def test_game_page_is_full_bleed_with_both_game_overlays(render_jx):
    source = _imports("GamePage") + (
        '{#def lesson #}<GamePage title="Quiz" lesson={{ lesson }} body_class="h-screen"><main>game</main></GamePage>'
    )
    root = parse(render_jx(source, lesson=SimpleNamespace(title="Shapes", topic_id=3)))
    ids = {el.attrs.get("id") for el in root.find_all("div")}

    assert not root.find_all("footer")
    assert root.find("body").classes == ["h-screen"]
    assert any("gsap" in (s.attrs.get("src") or "") for s in root.find_all("script"))
    assert "/static/css/pages/games.css" in [link.attrs.get("href") for link in root.find("head").find_all("link")]
    assert {"levelUpModal", "completionScreen"} <= ids


# ── LegalPage ────────────────────────────────────────────────────────

_LEGAL = _imports("LegalPage") + (
    '<LegalPage title="Terms" updated="25 May 2026" other_href="/privacy" other_label="Privacy Policy">'
    "<p>Welcome.</p></LegalPage>"
)


def test_legal_page_wraps_the_policy_in_its_card_with_a_link_to_the_other(render_jx):
    root = parse(render_jx(_LEGAL))
    main = root.find("main")
    prose = main.find("div", "legal-prose")

    assert main.find("h1").all_text == "Terms"
    assert "25 May 2026" in main.all_text
    assert prose.all_text == "Welcome."
    assert "clay-card" in prose.classes
    assert [a.attrs["href"] for a in main.find_all("a")] == ["/privacy"]
    assert root.find("body").classes == ["min-h-screen", "flex", "flex-col", "bg-slate-50"]


def test_a_signed_in_reader_gets_a_way_back_to_settings(render_jx, db_session, teacher):
    back = parse(render_jx(_LEGAL, user=teacher)).find("main").find_all("a")[-1]

    assert back.attrs["href"] == "/settings"
    assert "icon-flip-rtl" in back.find("svg").classes


# ── WorksheetLibrary ─────────────────────────────────────────────────

_LIBRARY = _imports("WorksheetLibrary") + (
    "{#def worksheets, q, selected_subject, has_more #}"
    '<WorksheetLibrary title="Worksheets" endpoint="teacher.teacher_worksheets" subjects={{ ["Maths", "English"] }}'
    " selected_subject={{ selected_subject }} q={{ q }} worksheets={{ worksheets }} has_more={{ has_more }}"
    ' search_placeholder="Search worksheets" all_label="All" no_results_text="None match"'
    ' no_results_sub_text="Try another">'
    "{% fill header %}<h1>Library</h1>{% endfill %}"
    '{% fill cards %}<article class="ws-card">One</article>{% endfill %}'
    '{% fill modals %}<div id="upload-modal"></div>{% endfill %}'
    "</WorksheetLibrary>"
)


def _by_id(root):
    return {element.attrs.get("id"): element for element in root.find_all()}


def test_worksheet_library_lays_out_search_pills_grid_and_slots(render_jx):
    root = parse(render_jx(_LIBRARY, worksheets=[1], q="frac", selected_subject="Maths", has_more=True))
    main = root.find("main")
    by_id = _by_id(root)
    search = by_id["ws-search"]
    pills = by_id["ws-subject-pills"].find_all("a", "subject-pill")

    assert main.find("h1").all_text == "Library"
    assert (search.attrs["value"], search.attrs["placeholder"]) == ("frac", "Search worksheets")
    assert [pill.all_text for pill in pills] == ["All", "Maths", "English"]
    assert "subject-pill-active" in pills[1].classes
    assert by_id["ws-grid"].find("article", "ws-card")
    assert "hidden" not in by_id["ws-load-more"].attrs
    assert "upload-modal" in by_id


def test_an_empty_unfiltered_library_shows_the_empty_state(render_jx):
    by_id = _by_id(parse(render_jx(_LIBRARY, worksheets=[], q="", selected_subject=None, has_more=False)))

    assert "hidden" in by_id["no-results"].classes
    assert "hidden" not in by_id["ws-empty-state"].attrs
    assert by_id["ws-empty-state"].find("div", "empty-state")
    assert "hidden" in by_id["ws-load-more"].attrs


def test_an_empty_filtered_library_says_nothing_matches(render_jx):
    by_id = _by_id(parse(render_jx(_LIBRARY, worksheets=[], q="zzz", selected_subject=None, has_more=False)))

    assert "hidden" not in by_id["no-results"].classes
    assert by_id["no-results"].all_text == "None match Try another"
    assert "hidden" in by_id["ws-empty-state"].attrs
