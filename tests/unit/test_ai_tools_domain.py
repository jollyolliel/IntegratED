"""Curated analysis tools — the ones that answer a teacher's actual question.

Unlike the generic read tools these are hand-written per question, so each one
gets its ownership boundary and its date-window arithmetic checked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.support.factories import (
    make_attendance,
    make_learner,
    make_school,
    make_teacher,
    make_volunteer,
    make_worksheet,
    make_worksheet_assignment,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def domain(app):
    from helpers.ai.tools import domain as module

    with app.app_context():
        yield module


@pytest.fixture
def world(db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher, name="Ada")
    volunteer = make_volunteer(db_session, school, teacher, name="Bo")
    return {
        "school": school,
        "teacher": teacher,
        "learner": learner,
        "volunteer": volunteer,
    }


def _ctx(teacher):
    from helpers.ai.tools import ToolContext

    return ToolContext(teacher=teacher)


def _on(year, month, day):
    return datetime(year, month, day, 10, 0, tzinfo=UTC)


# ── date arguments ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["not-a-date", "", None, "2026-13-40"])
def test_a_malformed_date_argument_is_refused(domain, value):
    with pytest.raises(ValueError, match="must be a date"):
        domain._day(value, "date_from")


def test_a_backwards_window_is_refused(domain):
    with pytest.raises(ValueError, match="must not be before"):
        domain._window("2026-03-10", "2026-03-01")


def test_a_single_day_window_is_allowed(domain):
    start, end = domain._window("2026-03-01", "2026-03-01")

    assert start < end


# ── naming ───────────────────────────────────────────────────────────────────


def test_a_learner_falls_back_from_name_to_username(domain, db_session, world):
    nameless = make_learner(
        db_session, world["school"], world["teacher"], name=None, username="zed"
    )

    assert domain.learner_name(nameless) == "zed"


def test_a_volunteer_falls_back_to_their_email_local_part(domain, db_session, world):
    nameless = make_volunteer(
        db_session, world["school"], world["teacher"],
        name=None, email="bright.spark@example.com",
    )

    assert domain.volunteer_name(nameless) == "bright.spark"


def test_no_volunteer_has_no_name(domain):
    assert domain.volunteer_name(None) is None


# ── ownership ────────────────────────────────────────────────────────────────


def test_another_teachers_learner_is_not_reachable(domain, db_session, world):
    outsider = make_teacher(db_session, world["school"])

    with pytest.raises((LookupError, PermissionError, ValueError)):
        domain.learner_snapshot(_ctx(outsider), world["learner"].id)


def test_an_unknown_learner_is_refused(domain, db_session, world):
    with pytest.raises((LookupError, PermissionError, ValueError)):
        domain.learner_snapshot(_ctx(world["teacher"]), 999_999)


# ── pair summaries ───────────────────────────────────────────────────────────


def _match(db_session, learner, volunteer):
    learner.volunteer_id = volunteer.id
    learner.is_matched = True
    volunteer.is_matched = True
    db_session.commit()


def test_pair_summaries_reports_a_matched_pair(domain, db_session, world):
    _match(db_session, world["learner"], world["volunteer"])

    result = domain.pair_summaries(_ctx(world["teacher"]))

    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    assert pair["learner"] == "Ada"
    assert pair["volunteer"] == "Bo"


def test_pair_summaries_omits_an_unmatched_learner(domain, db_session, world):
    """Only matched pairs are summarized — an unmatched learner has no pair."""

    result = domain.pair_summaries(_ctx(world["teacher"]))

    assert result["pairs"] == []


def test_pair_summaries_excludes_another_teachers_pairs(domain, db_session, world):
    _match(db_session, world["learner"], world["volunteer"])
    other = make_teacher(db_session, world["school"])
    hidden_learner = make_learner(db_session, world["school"], other, name="Hidden")
    hidden_volunteer = make_volunteer(db_session, world["school"], other)
    _match(db_session, hidden_learner, hidden_volunteer)

    result = domain.pair_summaries(_ctx(world["teacher"]))

    assert "Hidden" not in str(result)


def test_pair_summaries_clamps_a_silly_recommendation_limit(domain, db_session, world):
    _match(db_session, world["learner"], world["volunteer"])

    result = domain.pair_summaries(_ctx(world["teacher"]), recommendation_limit="lots")

    assert len(result["pairs"]) == 1


# ── learner snapshot ─────────────────────────────────────────────────────────


def test_learner_snapshot_describes_the_learner(domain, db_session, world):
    result = domain.learner_snapshot(_ctx(world["teacher"]), world["learner"].id)

    assert "Ada" in str(result)


# ── recommended worksheets ───────────────────────────────────────────────────


def test_recommended_worksheets_returns_a_capped_list(domain, db_session, world):
    for index in range(6):
        make_worksheet(db_session, title=f"Sheet {index}", subject="English Grammar")

    result = domain.recommended_worksheets(
        _ctx(world["teacher"]), world["learner"].id, limit=2
    )

    body = next(value for value in result.values() if isinstance(value, list))
    assert len(body) <= 2


# ── progress_between ─────────────────────────────────────────────────────────


def test_progress_between_counts_only_rows_inside_the_window(domain, db_session, world):
    teacher, learner = world["teacher"], world["learner"]
    make_attendance(db_session, teacher, learner, date=_on(2026, 3, 2), duration=1.5)
    make_attendance(db_session, teacher, learner, date=_on(2026, 4, 20), duration=9.0)

    result = domain.progress_between(_ctx(teacher), "2026-03-01", "2026-03-31")

    row = next(r for r in result["learners"] if r["learner"] == "Ada")
    assert row["hours"] == pytest.approx(1.5)
    assert row["sessions_attended"] == 1


def test_progress_between_reports_the_inclusive_window(domain, db_session, world):
    result = domain.progress_between(_ctx(world["teacher"]), "2026-03-01", "2026-03-31")

    assert result["from"] == "2026-03-01"
    assert result["to"] == "2026-03-31"


def test_progress_between_names_learners_with_no_records(domain, db_session, world):
    result = domain.progress_between(_ctx(world["teacher"]), "2026-03-01", "2026-03-31")

    assert "Ada" in result["no_records_in_window"]


def test_progress_between_counts_completed_worksheets(domain, db_session, world):
    teacher, learner = world["teacher"], world["learner"]
    worksheet = make_worksheet(db_session)
    # Assignments are counted by `assigned_at`, so it has to fall in the window.
    make_worksheet_assignment(
        db_session, teacher, learner, worksheet,
        completed=True, assigned_at=_on(2026, 3, 3),
    )
    make_attendance(db_session, teacher, learner, date=_on(2026, 3, 2))

    result = domain.progress_between(_ctx(teacher), "2026-03-01", "2026-03-31")

    row = next(r for r in result["learners"] if r["learner"] == "Ada")
    assert row["worksheets_assigned"] == 1
    assert row["worksheets_completed"] == 1


# ── attendance_summary ───────────────────────────────────────────────────────


def test_attendance_summary_rejects_an_unknown_grouping(domain, db_session, world):
    with pytest.raises(ValueError, match="group_by must be"):
        domain.attendance_summary(
            _ctx(world["teacher"]), "2026-03-01", "2026-03-31", group_by="phase"
        )


@pytest.mark.parametrize("group_by", ["learner", "volunteer", "day"])
def test_attendance_summary_supports_every_grouping(domain, db_session, world, group_by):
    make_attendance(db_session, world["teacher"], world["learner"], date=_on(2026, 3, 2))

    result = domain.attendance_summary(
        _ctx(world["teacher"]), "2026-03-01", "2026-03-31", group_by=group_by
    )

    assert result["group_by"] == group_by
    assert result["total_sessions"] == 1


def test_attendance_summary_computes_a_rate_from_presence(domain, db_session, world):
    teacher, learner = world["teacher"], world["learner"]
    make_attendance(db_session, teacher, learner, date=_on(2026, 3, 2), duration=2.0)
    make_attendance(db_session, teacher, learner, date=_on(2026, 3, 9), is_present=False)

    result = domain.attendance_summary(_ctx(teacher), "2026-03-01", "2026-03-31")

    group = result["groups"][0]
    assert group["present"] == 1
    assert group["absent"] == 1
    assert group["attendance_rate"] == 50
    assert group["hours"] == pytest.approx(2.0)


def test_attendance_summary_ignores_rows_outside_the_window(domain, db_session, world):
    make_attendance(db_session, world["teacher"], world["learner"], date=_on(2026, 5, 5))

    result = domain.attendance_summary(_ctx(world["teacher"]), "2026-03-01", "2026-03-31")

    assert result["total_sessions"] == 0


# ── match_score ──────────────────────────────────────────────────────────────


def test_match_score_reports_a_score_and_the_open_slots(domain, db_session, world):
    result = domain.match_score(
        _ctx(world["teacher"]), world["learner"].id, world["volunteer"].id
    )

    assert isinstance(result["score"], int)
    assert result["learner"] == "Ada"
    assert result["volunteer"] == "Bo"
    assert result["volunteer_open_slots"] >= 1
    assert result["learner_already_matched"] is False


def test_match_score_refuses_another_teachers_volunteer(domain, db_session, world):
    other = make_teacher(db_session, world["school"])
    theirs = make_volunteer(db_session, world["school"], other)

    with pytest.raises((LookupError, PermissionError, ValueError)):
        domain.match_score(_ctx(world["teacher"]), world["learner"].id, theirs.id)


# ── preview_auto_match ───────────────────────────────────────────────────────


def test_preview_auto_match_pairs_an_unmatched_learner(domain, db_session, world):
    result = domain.preview_auto_match(_ctx(world["teacher"]))

    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["learner_id"] == world["learner"].id
    assert proposal["volunteer_id"] == world["volunteer"].id


def test_preview_auto_match_reports_learners_it_could_not_place(domain, db_session, world):
    """More learners than open slots leaves the surplus unmatched."""

    make_learner(db_session, world["school"], world["teacher"], name="Cy")
    make_learner(db_session, world["school"], world["teacher"], name="Di")

    result = domain.preview_auto_match(_ctx(world["teacher"]))

    assert len(result["proposals"]) == 1
    assert len(result["unmatched"]) == 2


def test_preview_auto_match_says_so_when_there_is_no_pool(domain, db_session):
    school = make_school(db_session)
    lonely = make_teacher(db_session, school)

    result = domain.preview_auto_match(_ctx(lonely))

    assert result["proposals"] == []
    assert result["note"]


def test_a_teacher_with_no_school_has_no_matching_pool(domain, db_session):
    homeless = make_teacher(db_session, None)

    with pytest.raises(ValueError, match="not assigned to a school"):
        domain.preview_auto_match(_ctx(homeless))
