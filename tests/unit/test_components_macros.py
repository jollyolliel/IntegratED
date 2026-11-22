"""The small shared components — back link, table, pagination (its 9-slot window), page header
and the worksheet pieces."""

from __future__ import annotations

import pytest

from tests.support.html import parse
from tests.support.jx import imports as _imports

pytestmark = pytest.mark.unit


# ── BackLink ─────────────────────────────────────────────────────────


def test_back_link_points_back_with_a_mirrored_chevron(render_jx):
    link = parse(render_jx(_imports("BackLink") + '<BackLink href="/people" label="People" />')).find("a")

    assert link.classes == ["back-link"]
    assert link.attrs["href"] == "/people"
    assert "icon-flip-rtl" in link.find("svg").classes
    assert link.all_text == "People"


# ── Table ────────────────────────────────────────────────────────────


def test_table_sits_in_its_scrolling_card(render_jx):
    html = render_jx(
        _imports("Table")
        + '<Table wrap_class="mb-6" class="att-sheet" id="sheet"><tbody><tr><td>1</td></tr></tbody></Table>'
    )
    wrap = parse(html).find("div")
    table = wrap.find("table")

    assert wrap.classes == ["clay-table-wrap", "mb-6"]
    assert table.classes == ["clay-table", "att-sheet"]
    assert table.attrs["id"] == "sheet"
    assert table.find("td").all_text == "1"


def test_an_unwrapped_table_has_no_card(render_jx):
    root = parse(render_jx(_imports("Table") + "<Table wrap={{ false }}><tbody></tbody></Table>"))

    assert root.children[0].tag == "table"


# ── Pagination ───────────────────────────────────────────────────────

_PAGER = _imports("Pagination") + (
    "{#def page, total_pages, key='page', args={} #}"
    '<Pagination endpoint="base.home" page={{ page }} total_pages={{ total_pages }} key={{ key }} args={{ args }} />'
)


def _window(render_jx, page, total_pages):
    nav = parse(render_jx(_PAGER, page=page, total_pages=total_pages)).find("nav")
    numbers = [int(a.all_text) for a in nav.find_all("a", "pagination-link") if a.all_text.isdigit()]
    return numbers, len(nav.find_all("span", "pagination-ellipsis"))


def test_nine_or_fewer_pages_render_every_page_with_no_ellipsis(render_jx):
    assert _window(render_jx, 3, 5) == ([1, 2, 3, 4, 5], 0)


def test_near_the_start_collapses_the_right_side_only(render_jx):
    assert _window(render_jx, 3, 15) == ([1, 2, 3, 4, 5, 6, 7, 15], 1)


def test_near_the_end_collapses_the_left_side_only(render_jx):
    assert _window(render_jx, 13, 15) == ([1, 9, 10, 11, 12, 13, 14, 15], 1)


def test_the_middle_opens_both_ellipses(render_jx):
    assert _window(render_jx, 10, 20) == ([1, 8, 9, 10, 11, 12, 20], 2)


def test_page_five_is_the_last_page_that_collapses_only_the_right(render_jx):
    assert _window(render_jx, 5, 20) == ([1, 2, 3, 4, 5, 6, 7, 20], 1)


def test_page_six_is_the_first_page_with_a_left_ellipsis(render_jx):
    assert _window(render_jx, 6, 20) == ([1, 4, 5, 6, 7, 8, 20], 2)


@pytest.mark.parametrize(
    ("page", "total_pages"),
    [(1, 9), (9, 9), (1, 10), (5, 10), (6, 10), (10, 10), (1, 50), (5, 50), (25, 50), (46, 50), (50, 50)],
)
def test_slot_count_is_nine_for_every_n_of_nine_or_more(render_jx, page, total_pages):
    numbers, ellipses = _window(render_jx, page, total_pages)

    if total_pages <= 9:
        assert (len(numbers), ellipses) == (total_pages, 0)
    else:
        assert len(numbers) + ellipses == 9


def test_the_current_page_is_marked_current(render_jx):
    nav = parse(render_jx(_PAGER, page=3, total_pages=5)).find("nav")
    current = [a for a in nav.find_all("a") if a.attrs.get("aria-current") == "page"]

    assert [a.all_text for a in current] == ["3"]
    assert "active" in current[0].classes


def test_ellipsis_is_not_a_link(render_jx):
    nav = parse(render_jx(_PAGER, page=10, total_pages=20)).find("nav")

    assert all(span.tag == "span" and "href" not in span.attrs for span in nav.find_all(cls="pagination-ellipsis"))


def test_prev_and_next_stay_but_go_inert_at_the_edges(render_jx):
    first = parse(render_jx(_PAGER, page=1, total_pages=3)).find("nav")
    prev, *_rest = first.find_all(cls="pagination-link")

    assert prev.tag == "span"
    assert prev.attrs["aria-disabled"] == "true"
    assert prev.all_text == "Prev"
    assert first.find_all("a")[-1].attrs["rel"] == "next"


def test_a_single_page_renders_no_pager(render_jx):
    assert "pagination" not in render_jx(_PAGER, page=1, total_pages=1)


def test_a_named_pager_writes_its_own_query_field_and_keeps_the_args(render_jx):
    nav = parse(render_jx(_PAGER, page=1, total_pages=3, key="learner", args={"volunteer_page": 2})).find("nav")
    href = nav.find_all("a")[-1].attrs["href"] or ""

    assert "learner_page=2" in href
    assert "volunteer_page=2" in href


def test_the_pager_is_plain_labelled_links_with_no_script_of_its_own(render_jx):
    # The swap is the header's delegated handler: the pager inside a `data-swap-region` swaps it.
    html = render_jx(
        _imports("Pagination")
        + '<Pagination endpoint="base.home" page={{ 1 }} total_pages={{ 2 }} label="Attendance pages" />'
    )
    nav = parse(html).find("nav")

    assert nav.attrs["aria-label"] == "Attendance pages"
    assert "<script" not in html


# ── PageHeader ───────────────────────────────────────────────────────


def test_page_header_stacks_badge_title_and_subtitle(render_jx):
    html = render_jx(
        _imports("PageHeader") + '<PageHeader badge="Teacher Portal" title="People" subtitle="Everyone in your school" />'
    )
    header = parse(html).children[0]

    assert header.find("span", "clay-badge").all_text == "Teacher Portal"
    assert header.find("h1").all_text == "People"
    assert header.find("p").all_text == "Everyone in your school"
    assert "page-header-box" not in header.classes


def test_page_header_amber_badge_and_no_subtitle(render_jx):
    header = parse(render_jx(_imports("PageHeader") + '<PageHeader badge="Review" badge_tone="amber" title="X" />')).children[0]

    assert header.find_all(cls="clay-badge-amber")
    assert not header.find_all("p")


def test_a_boxed_page_header_sits_in_the_gradient_box(render_jx):
    header = parse(render_jx(_imports("PageHeader") + '<PageHeader title="School" boxed />')).children[0]

    assert "page-header-box" in header.classes


def test_page_header_places_a_lead_and_its_actions(render_jx):
    html = render_jx(
        _imports("PageHeader")
        + '<PageHeader title="Ana">{% fill lead %}<img alt="avatar">{% endfill %}<a href="/edit">Edit</a></PageHeader>'
    )
    header = parse(html).children[0]

    assert header.find("img").attrs["alt"] == "avatar"
    assert header.find("a").attrs["href"] == "/edit"


def test_page_header_raises_on_an_unknown_badge_tone(render_jx):
    with pytest.raises(ValueError, match="PageHeader.*badge_tone.*green"):
        render_jx(_imports("PageHeader") + '<PageHeader title="X" badge="b" badge_tone="green" />')


# ── Worksheets ───────────────────────────────────────────────────────


def test_worksheet_viewer_frames_a_pdf_with_an_open_link(render_jx):
    html = render_jx(_imports("WorksheetViewer") + '<WorksheetViewer file_type="pdf" file_url="/w/1.pdf" />')
    card = parse(html).find("div", "clay-card")

    assert card.find("div", "preview-topbar").find("span", "preview-topbar-label").all_text == "PDF Preview"
    link = card.find("a", "btn-clay")
    assert (link.attrs["href"], link.attrs["target"]) == ("/w/1.pdf", "_blank")
    assert {"btn-gray", "btn-flat"} <= set(link.classes)
    assert card.find("iframe").attrs["src"] == "/w/1.pdf"


def test_worksheet_viewer_renders_markdown_as_prose(render_jx):
    html = render_jx(
        _imports("WorksheetViewer") + "{#def body #}<WorksheetViewer file_type=\"md\" worksheet_html={{ body }} />",
        body="<h2>Fractions</h2>",
    )
    card = parse(html).find("div", "clay-card")

    assert card.find("span", "preview-topbar-label").all_text == "Worksheet Content"
    assert card.find("div", "worksheet-prose").find("h2").all_text == "Fractions"


def test_worksheet_viewer_raises_on_an_unknown_file_type(render_jx):
    with pytest.raises(ValueError, match="WorksheetViewer.*file_type.*docx"):
        render_jx(_imports("WorksheetViewer") + '<WorksheetViewer file_type="docx" file_url="/x" />')


@pytest.mark.parametrize("tag", ["div", "article"])
def test_worksheet_prose_wraps_rendered_markdown(render_jx, tag):
    html = render_jx(_imports("WorksheetProse") + f'<WorksheetProse tag="{tag}" class="wv-card"><p>Hi</p></WorksheetProse>')

    assert parse(html).find(tag).classes == ["worksheet-prose", "wv-card"]


def test_worksheet_meta_lists_label_value_rows(render_jx):
    html = render_jx(
        _imports("WorksheetMeta") + "{#def rows #}<WorksheetMeta rows={{ rows }} />",
        rows=[{"label": "Subject", "value": "Maths"}, {"label": "Topic", "value": "Fractions"}],
    )
    root = parse(html)

    assert [p.all_text for p in root.find_all("p", "meta-label")] == ["Subject", "Topic"]
    assert [p.all_text for p in root.find_all("p", "meta-value")] == ["Maths", "Fractions"]
