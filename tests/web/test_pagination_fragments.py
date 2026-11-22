"""Fragment parity: a pagination fragment response (`X-Fragment: 1`) equals
the corresponding region of the full page response — one Jinja source for the
markup, so the two can never drift apart (docs/ui-design/page-behaviour.md)."""

from __future__ import annotations

import re

import pytest

from tests.support.assertions import assert_success
from tests.support.factories import make_school

pytestmark = pytest.mark.web

_TAG_RE = re.compile(r"<(/?)div\b")


def _element(html: str, marker: str) -> tuple[str, str]:
    """(outer, inner) HTML of the first `<div>` whose open tag carries `marker`, nested divs matched."""
    marker_pos = html.index(marker)
    open_tag_start = html.rindex("<div", 0, marker_pos + len("<div"))
    open_tag_end = html.index(">", marker_pos) + 1

    depth = 1
    pos = open_tag_end
    while depth > 0:
        m = _TAG_RE.search(html, pos)
        if m is None:
            raise AssertionError(f"unbalanced <div> looking for {marker}")
        depth += -1 if m.group(1) == "/" else 1
        pos = m.end()
    close_tag_start = html.rindex("<", pos - 6, pos)
    close_tag_end = html.index(">", pos) + 1
    return html[open_tag_start:close_tag_end], html[open_tag_end:close_tag_start]


# ── the results routes: fragment, full page, and parity ─────────────────────
#
# Each route renders one results component two ways: alone for an `X-Fragment`
# request, and in place on its page otherwise. A pager's results component is
# its own swap region (`data-swap-region` on its root), so the fragment is the
# whole region. A card grid's fragment is the cards it appends inside the grid,
# and the attendance history's is the inside of the region its page owns.
# `seed` adds a row and returns a string the region shows, so every case
# asserts on real content.


def _seed_article(session, user):
    from tests.support.factories import make_admin, make_article

    make_article(session, make_admin(session), title="Pinned Article")
    return "Pinned Article"


def _seed_school(session, user):
    make_school(session, name="Pinned School")
    return "Pinned School"


def _seed_donation(session, user):
    from tests.support.factories import make_donation

    make_donation(session, school=getattr(user, "school", None) or make_school(session), donor_name="Pinned Donor")
    return "Pinned Donor"


def _seed_user(session, user):
    from tests.support.factories import make_teacher

    make_teacher(session, make_school(session), name="Pinned Teacher")
    return "Pinned Teacher"


def _seed_school_teacher(session, user):
    from tests.support.factories import make_teacher

    make_teacher(session, user.school, name="Pinned Teacher")
    return "Pinned Teacher"


def _seed_school_attendance(session, user):
    from tests.support.factories import make_attendance, make_learner, make_teacher

    teacher = make_teacher(session, user.school)
    make_attendance(session, teacher, make_learner(session, user.school, teacher, name="Pinned Learner"))
    return "Pinned Learner"


def _seed_history(session, user):
    from tests.support.factories import make_attendance, make_learner

    make_attendance(session, user, make_learner(session, user.school, user, name="Pinned Learner"))
    return "Pinned Learner"


def _seed_worksheet(session, user):
    from tests.support.factories import make_worksheet

    make_worksheet(session, title="Pinned Sheet")
    return "Pinned Sheet"


def _seed_assignment(session, user):
    from tests.support.factories import (
        make_learner,
        make_worksheet,
        make_worksheet_assignment,
    )

    learner = make_learner(session, user.school, user)
    make_worksheet_assignment(session, user, learner, make_worksheet(session, title="Pinned Sheet"))
    return "Pinned Sheet"


SWAP = "<div data-swap-region>"

# (path, signed-in fixture or None, the region's marker, whether the fragment is the whole region, seed)
RESULTS_ROUTES = [
    ("/news", None, SWAP, True, _seed_article),
    ("/schools", None, SWAP, True, _seed_school),
    ("/admin/db/table/schools", "authenticated_admin", SWAP, True, _seed_school),
    ("/admin/donations", "authenticated_admin", SWAP, True, _seed_donation),
    ("/admin/schools", "authenticated_admin", SWAP, True, _seed_school),
    ("/admin/users", "authenticated_admin", SWAP, True, _seed_user),
    ("/school/attendance", "authenticated_school_admin", SWAP, True, _seed_school_attendance),
    ("/school/donations", "authenticated_school_admin", SWAP, True, _seed_donation),
    ("/school/people", "authenticated_school_admin", SWAP, True, _seed_school_teacher),
    # The page owns this region: its script swaps the inside (filter changes too) and edits rows in it.
    ("/teacher/attendance/history", "authenticated_teacher", 'id="historyResults"', False, _seed_history),
    ("/teacher/worksheets", "authenticated_teacher", 'id="ws-grid"', False, _seed_worksheet),
    ("/teacher/worksheets/assigned", "authenticated_teacher", SWAP, True, _seed_assignment),
    ("/volunteer/resources", "authenticated_volunteer", 'id="ws-grid"', False, _seed_worksheet),
]
_IDS = [path for path, *_ in RESULTS_ROUTES]


def _get(request, db_session, path, signed_in, seed, **kwargs):
    client = request.getfixturevalue("client")
    user = request.getfixturevalue(signed_in) if signed_in else None
    marker = seed(db_session, user)
    return assert_success(client.get(path, **kwargs)).get_data(as_text=True), marker


@pytest.mark.parametrize(("path", "signed_in", "region", "whole", "seed"), RESULTS_ROUTES, ids=_IDS)
def test_a_fragment_request_gets_only_the_results(request, db_session, path, signed_in, region, whole, seed):
    body, marker = _get(request, db_session, path, signed_in, seed, headers={"X-Fragment": "1"})

    assert "<html" not in body
    assert marker in body


@pytest.mark.parametrize(("path", "signed_in", "region", "whole", "seed"), RESULTS_ROUTES, ids=_IDS)
def test_a_plain_request_gets_the_whole_page_with_the_results(request, db_session, path, signed_in, region, whole, seed):
    body, marker = _get(request, db_session, path, signed_in, seed)

    assert "<html" in body
    assert marker in _element(body, region)[1]


@pytest.mark.parametrize(("path", "signed_in", "region", "whole", "seed"), RESULTS_ROUTES, ids=_IDS)
def test_the_page_heading_stays_outside_the_swapped_region(request, db_session, path, signed_in, region, whole, seed):
    """Only what a page turn changes is swapped; the heading and its actions belong to the page."""
    body, _ = _get(request, db_session, path, signed_in, seed)

    assert "<h1" in body
    assert "<h1" not in _element(body, region)[1]


@pytest.mark.parametrize(("path", "signed_in", "region", "whole", "seed"), RESULTS_ROUTES, ids=_IDS)
def test_the_fragment_matches_the_full_pages_region(request, db_session, path, signed_in, region, whole, seed):
    full, _ = _get(request, db_session, path, signed_in, seed)
    fragment = assert_success(
        request.getfixturevalue("client").get(path, headers={"X-Fragment": "1"})
    ).get_data(as_text=True)

    outer, inner = _element(full, region)

    # .strip(): the indentation around it is not part of the fragment.
    assert (outer if whole else inner).strip() == fragment.strip()
