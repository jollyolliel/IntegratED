"""The auto-derived read tools: filter grammar, row caps, and scoping.

These tools take no argument that would let the model widen its own scope, so
the tests below check both the grammar (which the model drives) and the
invariant that another teacher's rows stay unreachable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.support.factories import (
    make_attendance,
    make_learner,
    make_school,
    make_teacher,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def generic(app):
    from helpers.ai.tools import generic as module

    with app.app_context():
        yield module


@pytest.fixture
def roster(db_session):
    """A teacher with two learners, plus a second teacher to leak against."""

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    other = make_teacher(db_session, school)
    first = make_learner(db_session, school, teacher, username="ada")
    second = make_learner(db_session, school, teacher, username="grace")
    outsider = make_learner(db_session, school, other, username="outsider")
    return {
        "school": school,
        "teacher": teacher,
        "other": other,
        "learners": [first, second],
        "outsider": outsider,
    }


def _ctx(teacher):
    from helpers.ai.tools import ToolContext

    return ToolContext(teacher=teacher)


def _table_for(generic, name):
    from helpers.ai import scope

    model, _ = scope.resolve(name)
    return model, scope.local_table(model)


# ── filter grammar ───────────────────────────────────────────────────────────


def test_an_unknown_operator_is_refused(generic):
    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="Unknown operator"):
        generic.build_filters(model, table, [{"field": "name", "op": "regex", "value": "x"}])


def test_a_non_object_filter_is_refused(generic):
    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="must be an object"):
        generic.build_filters(model, table, ["name = 'Ada'"])


def test_an_unknown_field_is_refused_and_lists_what_exists(generic):
    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="No filterable field"):
        generic.build_filters(model, table, [{"field": "nope", "op": "eq", "value": 1}])


def test_a_redacted_field_cannot_be_filtered_on(generic):
    """Redaction has to hold on the way in as well as on the way out."""

    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="No filterable field"):
        generic.build_filters(
            model, table, [{"field": "password_hash", "op": "eq", "value": "x"}]
        )


def test_base_class_columns_are_not_filterable_on_a_subclass(generic):
    """`name` lives on `users`, and scoping works on each model's local table.

    So a Learner exposes `username` but not `name`. This is a real consequence
    of the joined-table inheritance the scope walk deliberately refuses to
    traverse — pinned here so it is a decision rather than a surprise.
    """

    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="No filterable field"):
        generic.build_filters(model, table, [{"field": "name", "op": "eq", "value": "Ada"}])


def test_the_in_operator_requires_a_list(generic):
    model, table = _table_for(generic, "Learner")

    with pytest.raises(ValueError, match="needs a list"):
        generic.build_filters(model, table, [{"field": "id", "op": "in", "value": 1}])


@pytest.mark.parametrize("op", ["eq", "ne", "lt", "lte", "gt", "gte"])
def test_every_comparison_operator_builds_a_clause(generic, op):
    model, table = _table_for(generic, "Learner")

    clauses = generic.build_filters(model, table, [{"field": "id", "op": op, "value": "1"}])

    assert len(clauses) == 1


@pytest.mark.parametrize("op,expected", [("in", 2), ("contains", 1), ("is_null", 1)])
def test_the_set_and_null_operators_build_clauses(generic, op, expected):
    model, table = _table_for(generic, "Learner")
    value = [1, 2] if op == "in" else ("ada" if op == "contains" else True)

    clauses = generic.build_filters(model, table, [{"field": "username", "op": op, "value": value}])

    assert len(clauses) == 1


def test_the_default_operator_is_equality(generic, db_session, roster):
    model, table = _table_for(generic, "Learner")

    clauses = generic.build_filters(model, table, [{"field": "username", "value": "ada"}])

    assert len(clauses) == 1


def test_a_boolean_column_coerces_a_string(generic):
    _model, table = _table_for(generic, "Learner")

    assert generic._coerce(table.c.is_matched, "true") is True
    assert generic._coerce(table.c.is_matched, "no") is False


def test_a_non_numeric_string_against_an_int_column_is_left_alone(generic):
    """Coercion is best-effort; the comparison simply matches nothing."""

    _model, table = _table_for(generic, "Learner")

    assert generic._coerce(table.c.id, "not-a-number") == "not-a-number"


def test_a_bare_date_against_a_datetime_column_spans_the_whole_day(generic, db_session):
    """A row written at 14:00 must match a filter on its calendar date."""

    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    afternoon = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
    make_attendance(db_session, teacher, learner, date=afternoon)

    result = generic.query_records(
        _ctx(teacher),
        "Attendance",
        filters=[{"field": "date", "op": "eq", "value": "2026-03-04"}],
    )

    assert result["count"] == 1


def test_a_date_range_filter_selects_the_expected_days(generic, db_session):
    school = make_school(db_session)
    teacher = make_teacher(db_session, school)
    learner = make_learner(db_session, school, teacher)
    for day in (1, 2, 3):
        make_attendance(
            db_session, teacher, learner,
            date=datetime(2026, 3, day, 9, 0, tzinfo=UTC),
        )

    result = generic.query_records(
        _ctx(teacher),
        "Attendance",
        filters=[{"field": "date", "op": "gte", "value": "2026-03-02"}],
    )

    assert result["count"] == 2


def test_a_date_value_with_an_unsupported_operator_is_refused(generic):
    _model, table = _table_for(generic, "Attendance")

    with pytest.raises(ValueError, match="does not take a date value"):
        generic._day_clause(table.c.date, "contains", "2026-03-04")


# ── list / describe ──────────────────────────────────────────────────────────


def test_list_entities_reports_only_readable_models(generic, db_session, roster):
    result = generic.list_entities(_ctx(roster["teacher"]))

    names = {entry["name"] for entry in result["entities"]}
    assert "Learner" in names
    assert "Donation" not in names
    assert all(entry["description"] for entry in result["entities"])


def test_describe_entity_returns_the_live_schema(generic, db_session, roster):
    result = generic.describe_entity(_ctx(roster["teacher"]), "learner")

    assert result["entity"] == "Learner"
    assert {"name", "type", "nullable", "references"} <= set(result["columns"][0])


# ── query_records ────────────────────────────────────────────────────────────


def test_query_records_returns_only_this_teachers_rows(generic, db_session, roster):
    result = generic.query_records(_ctx(roster["teacher"]), "Learner")

    names = {record["username"] for record in result["records"]}
    assert names == {"ada", "grace"}


def test_query_records_never_returns_a_redacted_column(generic, db_session, roster):
    result = generic.query_records(_ctx(roster["teacher"]), "Learner")

    assert all("password_hash" not in record for record in result["records"])


def test_query_records_honours_a_field_allowlist(generic, db_session, roster):
    result = generic.query_records(
        _ctx(roster["teacher"]), "Learner", fields=["id", "username"]
    )

    assert set(result["records"][0]) == {"id", "username"}


def test_query_records_orders_descending_with_a_minus_prefix(generic, db_session, roster):
    ascending = generic.query_records(_ctx(roster["teacher"]), "Learner", order_by="username")
    descending = generic.query_records(_ctx(roster["teacher"]), "Learner", order_by="-username")

    assert [r["username"] for r in ascending["records"]] == ["ada", "grace"]
    assert [r["username"] for r in descending["records"]] == ["grace", "ada"]


def test_query_records_reports_truncation(generic, db_session, roster):
    result = generic.query_records(_ctx(roster["teacher"]), "Learner", limit=1)

    assert result["count"] == 1
    assert result["truncated"] is True


def test_query_records_caps_an_oversized_limit(generic, db_session, roster):
    result = generic.query_records(_ctx(roster["teacher"]), "Learner", limit=10_000)

    assert result["count"] == 2
    assert result["truncated"] is False


def test_query_records_falls_back_to_the_default_limit_on_junk(generic, db_session, roster):
    result = generic.query_records(_ctx(roster["teacher"]), "Learner", limit="lots")

    assert result["count"] == 2


def test_query_records_refuses_a_denied_entity(generic, db_session, roster):
    with pytest.raises(PermissionError):
        generic.query_records(_ctx(roster["teacher"]), "Donation")


# ── count_records ────────────────────────────────────────────────────────────


def test_count_records_counts_within_scope(generic, db_session, roster):
    result = generic.count_records(_ctx(roster["teacher"]), "Learner")

    assert result["count"] == 2


def test_count_records_applies_its_filters(generic, db_session, roster):
    """A dropped filter would return a larger, plausible, wrong number."""

    result = generic.count_records(
        _ctx(roster["teacher"]),
        "Learner",
        filters=[{"field": "username", "op": "eq", "value": "ada"}],
    )

    assert result["count"] == 1


def test_count_records_groups_by_a_column(generic, db_session, roster):
    result = generic.count_records(
        _ctx(roster["teacher"]), "Learner", group_by="is_matched"
    )

    assert result["group_by"] == "is_matched"
    assert sum(group["count"] for group in result["groups"]) == 2


# ── aggregate_records ────────────────────────────────────────────────────────


def test_aggregate_sums_within_scope(generic, db_session, roster):
    teacher = roster["teacher"]
    for learner in roster["learners"]:
        make_attendance(db_session, teacher, learner, duration=1.5)
    make_attendance(db_session, roster["other"], roster["outsider"], duration=99.0)

    result = generic.aggregate_records(_ctx(teacher), "Attendance", "sum", "duration")

    assert result["value"] == pytest.approx(3.0)


def test_aggregate_rejects_an_unknown_operation(generic, db_session, roster):
    with pytest.raises(ValueError, match="Unknown aggregation"):
        generic.aggregate_records(_ctx(roster["teacher"]), "Attendance", "median", "duration")


def test_aggregate_groups_by_a_column(generic, db_session, roster):
    teacher = roster["teacher"]
    first, second = roster["learners"]
    make_attendance(db_session, teacher, first, duration=2.0)
    make_attendance(db_session, teacher, second, duration=1.0)

    result = generic.aggregate_records(
        _ctx(teacher), "Attendance", "sum", "duration", group_by="user_id"
    )

    assert result["group_by"] == "user_id"
    assert len(result["groups"]) == 2
    # Ordered by the aggregate, descending.
    assert result["groups"][0]["value"] == first.id


@pytest.mark.parametrize("op", ["sum", "avg", "min", "max"])
def test_every_aggregation_runs(generic, db_session, roster, op):
    teacher = roster["teacher"]
    make_attendance(db_session, teacher, roster["learners"][0], duration=2.0)

    result = generic.aggregate_records(_ctx(teacher), "Attendance", op, "duration")

    assert result["op"] == op
