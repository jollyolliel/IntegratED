"""Auto-derived read tools — no per-model code anywhere in this file.

`list_entities` + `describe_entity` are what keep the assistant current: the
system prompt never enumerates the schema, the model asks for it. A model added
tomorrow with a `teacher_id` is queryable today.

Every query here goes through `helpers/ai/scope.scoped_query`, so another
teacher's rows are unreachable and the model has no argument that would let it
opt out.
"""

import datetime as dt
import operator
import re
from typing import Any, TypedDict

import sqlalchemy as sa

from extensions import db
from helpers.ai import scope
from helpers.ai.tools import ToolContext, ai_tool
from helpers.refusal import Refusal
from helpers.utils import day_bounds


class _EntityBrief(TypedDict):
    name: str
    description: str


class ListEntitiesResult(TypedDict):
    entities: list[_EntityBrief]


class QueryRecordsResult(TypedDict):
    """`records` holds arbitrary per-entity columns, so `dict[str, Any]` there
    is the real shape, not a placeholder for one not yet written."""
    entity: str
    count: int
    truncated: bool
    records: list[dict[str, Any]]


class _CountGroup(TypedDict):
    value: Any  # the grouped column's own value, whatever type that is
    count: int


class CountResult(TypedDict):
    entity: str
    count: int


class GroupedCountResult(TypedDict):
    entity: str
    group_by: str
    groups: list[_CountGroup]


class AggregateResult(TypedDict):
    entity: str
    op: str
    field: str
    value: Any  # the aggregated column's own type


class GroupedAggregateResult(TypedDict):
    entity: str
    op: str
    field: str
    group_by: str | None
    groups: list[dict[str, Any]]  # each is {"value": Any, <op>: Any}

# Hard ceiling on rows returned to the model, whatever it asks for. A runaway
# limit is both a token bill and a slow query holding a gunicorn thread.
MAX_ROWS = 200
DEFAULT_ROWS = 25

OPERATORS = ("eq", "ne", "lt", "lte", "gt", "gte", "in", "contains", "is_null")

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_FILTER_SCHEMA = {
    "type": "array",
    "description": (
        "Conditions ANDed together. Never SQL — each item is "
        "{field, op, value} with op one of: " + ", ".join(OPERATORS) + "."
    ),
    "items": {
        "type": "object",
        "properties": {
            "field": {"type": "string", "description": "Column name on the entity."},
            "op": {"type": "string", "enum": list(OPERATORS)},
            "value": {
                "description": (
                    "Comparison value. A 'YYYY-MM-DD' string against a datetime "
                    "column matches that whole calendar day. Omit for is_null."
                )
            },
        },
        "required": ["field", "op"],
    },
}


# ── filter grammar ───────────────────────────────────────────────────────────

def _column(model: type, table: sa.Table, field: str) -> Any:
    """Look up a filterable column by name, rejecting redacted/unknown fields.

    Args:
        model (type): Mapped model class, for the error message's field list.
        table (sa.Table): The entity's local table.
        field (str): Column name requested.

    Returns:
        Any: The SQLAlchemy column.
    """
    if field in scope.REDACTED_FIELDS or field not in table.c:
        raise Refusal(
            f"No filterable field {field!r}. Available: "
            + ", ".join(scope.visible_columns(model))
        )
    return table.c[field]


def _is_datetime(column: Any) -> bool:
    """Whether a column holds a Date/DateTime type.

    Args:
        column (Any): SQLAlchemy column.

    Returns:
        bool: True if the column's type is `Date` or `DateTime`.
    """
    return isinstance(column.type, (sa.DateTime, sa.Date))


def _coerce(column: Any, value: Any) -> Any:
    """Best-effort scalar coercion. Strings from the model are the norm.

    Args:
        column (Any): SQLAlchemy column the value will be compared against.
        value (Any): Raw filter value.

    Returns:
        Any: `value` coerced to match the column's type, or unchanged on failure.
    """
    if value is None or not isinstance(value, str):
        return value
    if isinstance(column.type, sa.Boolean):
        return value.strip().lower() in ("1", "true", "yes", "y")
    if isinstance(column.type, (sa.Integer, sa.BigInteger, sa.SmallInteger)):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(column.type, (sa.Float, sa.Numeric)):
        try:
            return float(value)
        except ValueError:
            return value
    if _is_datetime(column):
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _day_clause(column: Any, op: str, value: str) -> Any:
    """A bare date against a DateTime column spans the whole calendar day, not just midnight rows.

    Args:
        column (Any): SQLAlchemy DateTime column.
        op (str): Comparison operator (`eq`/`ne`/`gte`/`gt`/`lte`/`lt`).
        value (str): `'YYYY-MM-DD'` date string.

    Returns:
        Any: The equivalent range clause spanning the whole day.
    """
    day = dt.date.fromisoformat(value)
    start, end = day_bounds(day)
    if op == "eq":
        return sa.and_(column >= start, column < end)
    if op == "ne":
        return sa.or_(column < start, column >= end)
    if op == "gte":
        return column >= start
    if op == "gt":
        return column >= end
    if op == "lte":
        return column < end
    if op == "lt":
        return column < start
    raise Refusal(f"Operator {op!r} does not take a date value.")


# Dispatched, never built as a dict of all six expressions: SQLAlchemy rejects
# an ordering comparison against None/True/False at construction time, so
# eagerly building `column < value` blows up every boolean or null-valued
# filter before the operator the caller actually asked for is ever selected.
_COMPARISONS = {
    "eq": operator.eq, "ne": operator.ne,
    "lt": operator.lt, "lte": operator.le,
    "gt": operator.gt, "gte": operator.ge,
}


def build_filters(model: type, table: sa.Table, filters: list[dict[str, Any]] | None) -> list[Any]:
    """Compile the `{field, op, value}` filter grammar into SQLAlchemy clauses.

    Args:
        model (type): Mapped model class, for column lookup errors.
        table (sa.Table): The entity's local table.
        filters (list[dict[str, Any]] | None): Filter conditions, ANDed together.

    Returns:
        list[Any]: One SQLAlchemy boolean clause per filter.
    """
    clauses = []
    for item in filters or []:
        if not isinstance(item, dict):
            # ValueError (not TypeError) is intentional: helpers/ai/loop.py feeds
            # ValueError/LookupError/PermissionError back to the model as a
            # correctable tool result, per docs/features/ai-assistant.md's tool contract.
            raise Refusal("Each filter must be an object {field, op, value}.")
        field = item.get("field")
        op = (item.get("op") or "eq").strip().lower()
        value = item.get("value")

        if not isinstance(field, str) or not field:
            raise Refusal("Each filter needs a non-empty string 'field'.")
        if op not in OPERATORS:
            raise Refusal(f"Unknown operator {op!r}. Use one of: {', '.join(OPERATORS)}.")
        column = _column(model, table, field)

        if op == "is_null":
            clauses.append(column.is_(None) if value in (None, True, "true", 1)
                           else column.isnot(None))
            continue
        if op == "in":
            if not isinstance(value, (list, tuple)):
                raise Refusal("Operator 'in' needs a list value.")
            clauses.append(column.in_([_coerce(column, v) for v in value]))
            continue
        if op == "contains":
            clauses.append(column.ilike(f"%{value}%"))
            continue

        if _is_datetime(column) and isinstance(value, str) and _DATE_ONLY.match(value):
            clauses.append(_day_clause(column, op, value))
            continue

        coerced = _coerce(column, value)
        clauses.append(_COMPARISONS[op](column, coerced))
    return clauses


def _apply_order(query: Any, model: type, table: sa.Table, order_by: str | None) -> Any:
    """Apply an `ORDER BY` to a query from a `'column'`/`'-column'` string.

    Args:
        query (Any): SQLAlchemy select statement.
        model (type): Mapped model class, for column lookup errors.
        table (sa.Table): The entity's local table.
        order_by (str | None): Column name, `-`-prefixed for descending.

    Returns:
        Any: The query with ordering applied (unchanged if `order_by` is falsy).
    """
    if not order_by:
        return query
    raw = str(order_by).strip()
    descending = raw.startswith("-")
    column = _column(model, table, raw.lstrip("-"))
    return query.order_by(sa.desc(column) if descending else sa.asc(column))


# ── tools ────────────────────────────────────────────────────────────────────

@ai_tool(
    name="list_entities",
    description=(
        "List every data entity you may read, with a one-line description of "
        "each. Start here when you are unsure what exists — the list is derived "
        "from the live database, so it is never out of date."
    ),
    label="Listing available data",
    parameters={"type": "object", "properties": {}},
)
def list_entities(ctx: ToolContext) -> ListEntitiesResult:
    """List every entity the caller may read, with a one-line description.

    Args:
        ctx (ToolContext): Tool call context.

    Returns:
        ListEntitiesResult: `{"entities": [{"name", "description"}, ...]}`.
    """
    return {
        "entities": [
            {"name": name, "description": scope.description_for(name, model)}
            for name, model in scope.readable_models().items()
        ]
    }


@ai_tool(
    name="describe_entity",
    description=(
        "Columns, types and foreign keys of one entity, plus how its rows are "
        "restricted to this teacher. Call before filtering on a field you have "
        "not used yet."
    ),
    label="Inspecting {entity}",
    parameters={
        "type": "object",
        "properties": {"entity": {"type": "string", "description": "Entity name from list_entities."}},
        "required": ["entity"],
    },
)
def describe_entity(ctx: ToolContext, entity: str) -> dict[str, Any]:
    """Columns, types, foreign keys, and scope for one entity.

    Args:
        ctx (ToolContext): Tool call context.
        entity (str): Entity name from `list_entities`.

    Returns:
        dict[str, Any]: See `scope.describe`.
    """
    return scope.describe(entity)


@ai_tool(
    name="query_records",
    description=(
        "Read rows of one entity. Results are always restricted to this "
        "teacher's own learners, volunteers and records — you cannot widen "
        "that. Ask for only the fields you need; `limit` is capped server-side."
    ),
    label="Reading {entity}",
    parameters={
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "filters": _FILTER_SCHEMA,
            "fields": {
                "type": "array", "items": {"type": "string"},
                "description": "Columns to return. Omit for all visible columns.",
            },
            "order_by": {
                "type": "string",
                "description": "Column name; prefix with '-' for descending.",
            },
            "limit": {"type": "integer", "description": f"Max rows, capped at {MAX_ROWS}."},
        },
        "required": ["entity"],
    },
)
def query_records(ctx: ToolContext, entity: str, filters: list[dict[str, Any]] | None = None, fields: list[str] | None = None, order_by: str | None = None, limit: int | None = None) -> QueryRecordsResult:
    """Read scoped, filtered rows of one entity.

    Args:
        ctx (ToolContext): Tool call context.
        entity (str): Entity name.
        filters (list[dict[str, Any]] | None): `{field, op, value}` conditions, ANDed.
        fields (list[str] | None): Columns to return; all visible columns if omitted.
        order_by (str | None): Column name, `-`-prefixed for descending.
        limit (int | None): Max rows, capped at `MAX_ROWS`.

    Returns:
        QueryRecordsResult: `{"entity", "count", "truncated", "records"}`.
    """
    model, _ = scope.resolve(entity)
    entity = scope.canonical_name(entity)
    query, table = scope.scoped_query(entity, ctx.teacher)

    for clause in build_filters(model, table, filters):
        query = query.where(clause)
    query = _apply_order(query, model, table, order_by)

    try:
        size = int(limit) if limit is not None else DEFAULT_ROWS
    except (TypeError, ValueError):
        size = DEFAULT_ROWS
    size = max(1, min(size, MAX_ROWS))

    rows = db.session.execute(query.limit(size + 1)).all()
    truncated = len(rows) > size
    rows = rows[:size]

    return {
        "entity": entity,
        "count": len(rows),
        "truncated": truncated,
        "records": [scope.serialize_row(model, row, fields) for row in rows],
    }


@ai_tool(
    name="count_records",
    description=(
        "How many rows match, optionally broken down by one column. Use this "
        "instead of pulling rows just to count them."
    ),
    label="Counting {entity}",
    parameters={
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "filters": _FILTER_SCHEMA,
            "group_by": {"type": "string", "description": "Column to group counts by."},
        },
        "required": ["entity"],
    },
)
def count_records(ctx: ToolContext, entity: str, filters: list[dict[str, Any]] | None = None, group_by: str | None = None) -> CountResult | GroupedCountResult:
    """Count scoped, filtered rows of one entity, optionally grouped.

    Args:
        ctx (ToolContext): Tool call context.
        entity (str): Entity name.
        filters (list[dict[str, Any]] | None): `{field, op, value}` conditions, ANDed.
        group_by (str | None): Column to break the count down by.

    Returns:
        CountResult | GroupedCountResult: `{"entity", "count"}`, or
            `{"entity", "group_by", "groups"}` if grouped.
    """
    model, _ = scope.resolve(entity)
    entity = scope.canonical_name(entity)
    base, table = scope.scoped_query(entity, ctx.teacher)
    where = build_filters(model, table, filters)

    if group_by:
        column = _column(model, table, group_by)
        query = sa.select(column, sa.func.count()).select_from(table)
        clause = scope.scope_clause(entity, ctx.teacher)
        if clause is not None:
            query = query.where(clause)
        for item in where:
            query = query.where(item)
        query = query.group_by(column).order_by(sa.desc(sa.func.count())).limit(MAX_ROWS)
        rows = db.session.execute(query).all()
        return {
            "entity": entity,
            "group_by": group_by,
            "groups": [{"value": scope._jsonable(key), "count": int(n)} for key, n in rows],
        }

    # `base` carries the teacher scope only — the filters have to be applied
    # here too. A dropped filter doesn't error, it returns a plausible larger
    # number that the assistant then reports to a teacher as fact.
    for item in where:
        base = base.where(item)
    query = sa.select(sa.func.count()).select_from(base.subquery())
    return {"entity": entity, "count": int(db.session.execute(query).scalar() or 0)}


AGGREGATIONS = {"sum": sa.func.sum, "avg": sa.func.avg,
                "min": sa.func.min, "max": sa.func.max}


@ai_tool(
    name="aggregate_records",
    description=(
        "Sum / average / minimum / maximum of one numeric column, optionally "
        "grouped. Example: total attendance hours per learner."
    ),
    label="Adding up {entity}",
    parameters={
        "type": "object",
        "properties": {
            "entity": {"type": "string"},
            "op": {"type": "string", "enum": sorted(AGGREGATIONS)},
            "field": {"type": "string", "description": "Numeric column to aggregate."},
            "filters": _FILTER_SCHEMA,
            "group_by": {"type": "string"},
        },
        "required": ["entity", "op", "field"],
    },
)
def aggregate_records(ctx: ToolContext, entity: str, op: str, field: str, filters: list[dict[str, Any]] | None = None, group_by: str | None = None) -> AggregateResult | GroupedAggregateResult:
    """Sum/average/min/max of one numeric column, optionally grouped.

    Args:
        ctx (ToolContext): Tool call context.
        entity (str): Entity name.
        op (str): One of `AGGREGATIONS` (`sum`/`avg`/`min`/`max`).
        field (str): Numeric column to aggregate.
        filters (list[dict[str, Any]] | None): `{field, op, value}` conditions, ANDed.
        group_by (str | None): Column to break the aggregate down by.

    Returns:
        AggregateResult | GroupedAggregateResult: `{"entity", "op", "field", "value"}`,
            or with `"group_by"`/`"groups"` if grouped.
    """
    key = str(op).strip().lower()
    if key not in AGGREGATIONS:
        raise Refusal(f"Unknown aggregation {op!r}. Use one of: {', '.join(sorted(AGGREGATIONS))}.")

    model, _ = scope.resolve(entity)
    entity = scope.canonical_name(entity)
    _, table = scope.scoped_query(entity, ctx.teacher)
    aggregate = AGGREGATIONS[key](_column(model, table, field))

    selected = [aggregate]
    grouping = None
    if group_by:
        grouping = _column(model, table, group_by)
        selected = [grouping, aggregate]

    query = sa.select(*selected).select_from(table)
    clause = scope.scope_clause(entity, ctx.teacher)
    if clause is not None:
        query = query.where(clause)
    for item in build_filters(model, table, filters):
        query = query.where(item)

    if grouping is not None:
        query = query.group_by(grouping).order_by(sa.desc(aggregate)).limit(MAX_ROWS)
        rows = db.session.execute(query).all()
        return {
            "entity": entity, "op": key, "field": field, "group_by": group_by,
            "groups": [
                {"value": scope._jsonable(value), key: scope._jsonable(result)}
                for value, result in rows
            ],
        }

    return {
        "entity": entity, "op": key, "field": field,
        "value": scope._jsonable(db.session.execute(query).scalar()),
    }
