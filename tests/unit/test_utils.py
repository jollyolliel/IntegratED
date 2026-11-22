"""Small pure helpers in `helpers/utils.py`."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from models import Learner, Volunteer

pytestmark = pytest.mark.unit


# ── time ─────────────────────────────────────────────────────────────────────


def test_a_missing_page_arg_defaults_to_page_one(app):
    from helpers.utils import clamp_page

    with app.test_request_context("/list"):
        assert clamp_page(total=100, page_size=25) == (1, 4)


@pytest.mark.parametrize("raw", ["0", "-3", "not-a-number"])
def test_an_invalid_page_arg_clamps_to_one(app, raw):
    from helpers.utils import clamp_page

    with app.test_request_context(f"/list?page={raw}"):
        assert clamp_page(total=100, page_size=25)[0] == 1


def test_a_page_past_the_end_clamps_to_the_last_page(app):
    from helpers.utils import clamp_page

    with app.test_request_context("/list?page=99"):
        assert clamp_page(total=100, page_size=25) == (4, 4)


def test_an_empty_table_is_still_one_page(app):
    from helpers.utils import clamp_page

    with app.test_request_context("/list?page=3"):
        assert clamp_page(total=0, page_size=25) == (1, 1)


def test_a_custom_arg_name_pages_a_second_table_independently(app):
    from helpers.utils import clamp_page

    with app.test_request_context("/list?page=5&volunteer_page=2"):
        assert clamp_page(total=100, page_size=25, arg="page") == (4, 4)
        assert clamp_page(total=30, page_size=25, arg="volunteer_page") == (2, 2)


def test_utcnow_is_naive():
    """DB columns are TIMESTAMP WITHOUT TIME ZONE; an aware value raises."""

    from helpers.utils import utcnow_naive

    assert utcnow_naive().tzinfo is None


def test_day_bounds_span_exactly_one_day():
    from helpers.utils import day_bounds

    start, end = day_bounds(date(2026, 3, 4))

    assert start == datetime(2026, 3, 4, 0, 0)
    assert end == datetime(2026, 3, 5, 0, 0)


def test_day_bounds_include_a_row_written_mid_afternoon():
    """The half-open range is what stops an `== date` comparison missing rows."""

    from helpers.utils import day_bounds

    start, end = day_bounds(date(2026, 3, 4))

    assert start <= datetime(2026, 3, 4, 14, 30) < end


def test_day_bounds_exclude_the_following_midnight():
    from helpers.utils import day_bounds

    _start, end = day_bounds(date(2026, 3, 4))

    assert not datetime(2026, 3, 5, 0, 0) < end


# ── pair naming ──────────────────────────────────────────────────────────────


class _Person:
    """Duck-typed stand-in for `Learner`/`Volunteer` — `get_pair_display_name`
    only ever reads `.name`/`.username`/`.email`, so this avoids constructing
    a real (DB-backed) model in a pure-function unit test. Cast at each call
    site to satisfy the real model types in the function signature."""

    def __init__(self, name=None, username=None, email=None):
        self.name = name
        self.username = username
        self.email = email


def _learner(**kwargs) -> Learner:
    return cast("Learner", _Person(**kwargs))


def _volunteer(**kwargs) -> Volunteer:
    return cast("Volunteer", _Person(**kwargs))


def test_a_pair_name_joins_both_people():
    from helpers.utils import get_pair_display_name

    result = get_pair_display_name(_learner(name="Ada"), _volunteer(name="Bo"))

    assert result == "Ada & Bo"


def test_a_learner_without_a_name_falls_back_to_their_username():
    from helpers.utils import get_pair_display_name

    result = get_pair_display_name(_learner(username="ada99"), _volunteer(name="Bo"))

    assert result == "ada99 & Bo"


def test_a_volunteer_without_a_name_falls_back_to_their_email_local_part():
    from helpers.utils import get_pair_display_name

    result = get_pair_display_name(
        _learner(name="Ada"), _volunteer(email="bo.smith@example.com")
    )

    assert result == "Ada & bo.smith"


def test_an_unmatched_learner_reads_as_pending_a_volunteer():
    from helpers.utils import get_pair_display_name

    assert get_pair_display_name(_learner(name="Ada"), None) == "Ada & Volunteer"


def test_a_volunteer_with_neither_name_nor_email_still_renders():
    from helpers.utils import get_pair_display_name

    assert get_pair_display_name(_learner(name="Ada"), _volunteer()) == "Ada & Volunteer"


# ── subject buckets ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subject",
    ["English Grammar", "GRAMMAR", "Greek", "Language Arts", "  english  "],
)
def test_language_subjects_collapse_into_one_bucket(subject):
    from helpers.utils import normalize_subject_bucket

    assert normalize_subject_bucket(subject) == "language"


def test_an_unrecognized_subject_keeps_its_own_bucket():
    from helpers.utils import normalize_subject_bucket

    assert normalize_subject_bucket("Mathematics") == "mathematics"


@pytest.mark.parametrize("subject", [None, "", "   "])
def test_a_missing_subject_falls_back_to_general(subject):
    from helpers.utils import normalize_subject_bucket

    assert normalize_subject_bucket(subject) == "general"


# ── tokenizing ───────────────────────────────────────────────────────────────


def test_tokenizing_lowercases_and_splits_on_punctuation():
    from helpers.utils import tokenize_text

    assert tokenize_text("Present Simple: verbs!") == ["present", "simple", "verbs"]


def test_short_tokens_are_dropped():
    """Two-letter noise words would match almost everything."""

    from helpers.utils import tokenize_text

    assert tokenize_text("a an to the cat") == ["the", "cat"]


@pytest.mark.parametrize("text", [None, "", "!!!"])
def test_tokenizing_empty_input_gives_no_tokens(text):
    from helpers.utils import tokenize_text

    assert tokenize_text(text) == []


# ── markdown ─────────────────────────────────────────────────────────────────


def test_markdown_renders_a_heading():
    from helpers.utils import render_markdown

    assert "<h1>" in render_markdown("# Title")


def test_markdown_supports_tables_and_fenced_code():
    from helpers.utils import render_markdown

    table = render_markdown("| a | b |\n| - | - |\n| 1 | 2 |")
    code = render_markdown("```\nprint(1)\n```")

    assert "<table>" in table
    assert "<code>" in code


@pytest.mark.parametrize("text", [None, ""])
def test_empty_markdown_renders_nothing(text):
    from helpers.utils import render_markdown

    assert render_markdown(text) == ""


# ── context processors ───────────────────────────────────────────────────────


def test_the_year_is_injected_for_templates():
    from helpers.utils import inject_now, utcnow_naive

    assert inject_now() == {"year": utcnow_naive().year}


def test_the_build_version_falls_back_to_dev(monkeypatch):
    from helpers.utils import inject_version

    monkeypatch.delenv("GIT_SHA", raising=False)

    assert inject_version() == {"app_version": "dev", "app_version_full": "dev"}


def test_a_real_commit_sha_is_shortened_for_display(monkeypatch):
    from helpers.utils import inject_version

    monkeypatch.setenv("GIT_SHA", "abcdef1234567890")

    assert inject_version() == {
        "app_version": "abcdef1",
        "app_version_full": "abcdef1234567890",
    }


# ── request shape ────────────────────────────────────────────────────────────


def test_the_ajax_header_selects_a_json_response(app):
    from helpers.utils import wants_json

    with app.test_request_context(headers={"X-Requested-With": "XMLHttpRequest"}):
        assert wants_json() is True


def test_a_plain_request_does_not_want_json(app):
    from helpers.utils import wants_json

    with app.test_request_context():
        assert wants_json() is False
