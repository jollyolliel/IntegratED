"""Which rows of which model a teacher may see — derived from the FK graph.

Nothing here is hand-listed per model except the policy overrides at the top.
A new model with a `teacher_id` (the `Group` in `newfeatures`, say) becomes
readable the moment it is mapped; a new model with no route to a teacher is
invisible until someone classifies it. **Failing closed is the point.**

Resolution order, first match wins:

1. `POLICY` override
2. **direct** — a `teacher_id` FK on the model's own table
3. **hop** — an FK to a model resolved at (2), one hop only
4. **self** — `Teacher` itself
5. **global** — ownerless shared content (`GLOBAL_READABLE`), or `School`
   narrowed to the teacher's own school
6. **deny**

## The inheritance trap

`Learner`/`Volunteer`/`Teacher`/`Administrator`/`SchoolAdmin` are joined-table
subclasses: the subclass primary key *is* the FK to `users.id`
(`id = Column(Integer, ForeignKey("users.id"), primary_key=True)`). Follow that
edge and the walk finds Learner -> users -> Teacher, and every model in the app
resolves through a bogus path. So: **skip any FK whose local column is part of
the model's own primary key.** That one rule is what keeps the graph honest.

Scope filters are built against each model's *local table*, and ownership is
expressed as `IN (SELECT ...)` rather than a join. A join between two `User`
subclasses would emit the `users` join twice unless every side is wrapped in
`aliased(Model, flat=True)`; a subquery has no such failure mode.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from extensions import db

if TYPE_CHECKING:
    from models import Teacher

logger = logging.getLogger(__name__)

# Explicit classification. Always wins over the walk below.
#   "deny"   — never exposed, not even listed
#   "global" — ownerless content the teacher legitimately sees whole
#   "school" — narrowed to the teacher's own school
POLICY = {
    # People and records that are not this teacher's business.
    "User": "deny",
    "Administrator": "deny",
    "SchoolAdmin": "deny",
    "Donation": "deny",
    "Article": "deny",
    "SiteContent": "deny",
    "TeamMember": "deny",
    # The assistant's own bookkeeping. Reading it back would let a question
    # about "changes" answer from the ledger instead of the review list, which
    # is the surface the teacher actually acts on.
    "AssistantConversation": "deny",
    "AssistantMessage": "deny",
    "AssistantChange": "deny",
}

# Shared curriculum/content — no owner column exists, and a teacher already
# browses all of it in the UI.
GLOBAL_READABLE = {
    "Subject", "Topic", "Lesson", "Question", "MapQuestion", "Worksheet",
}

# Narrowed to the teacher's own row rather than every school.
SCHOOL_SCOPED = {"School"}

TEACHER_TABLE = "teachers"

# Never serialized, on any model. `password_hash` is a credential;
# `google_sub` is an internal OAuth identifier with no teaching meaning.
REDACTED_FIELDS = {"password_hash", "google_sub"}

# A human sentence where the column list alone reads badly. Optional — a model
# missing from here still gets a description derived from its mapper, so new
# models need no entry.
DESCRIPTIONS = {
    "Learner": "A student this teacher manages. Progress lives in completed_lesson_ids / completed_topic_ids and subject_levels.",
    "Volunteer": "A youth volunteer this teacher manages. match_capacity is how many learners they may hold.",
    "Teacher": "The teacher themselves.",
    "Attendance": "One person's own record of one session on one day (user_id owns it, partner_id is who they sat with). is_present false always carries duration 0.",
    "WorksheetAssignment": "A worksheet given to a learner, with its completion state.",
    "LearningSession": "In-progress or finished learning activity — placement test, quiz, or one of the games.",
    "School": "The teacher's school.",
}


# ── rules ────────────────────────────────────────────────────────────────────

class ScopeRule:
    """How one mapped model resolves to a teacher's rows — see module docstring."""
    __slots__ = ("column", "kind", "reason", "via")

    def __init__(self, kind: str, column: str | None = None, via: str | None = None, reason: str = "") -> None:
        """Set up one model's scope classification.

        Args:
            kind (str): One of `direct`/`hop`/`self`/`global`/`school`/`deny`.
            column (str | None): Local column carrying the scope, for `direct`/`hop`.
            via (str | None): Owner model name, for `hop`.
            reason (str): Human-readable explanation, shown in `describe`/logs.

        Returns:
            None
        """
        self.kind = kind        # direct | hop | self | global | school | deny
        self.column = column    # local column carrying the scope
        self.via = via          # owner model name, for hop
        self.reason = reason

    @property
    def readable(self) -> bool:
        """Whether this rule permits reading the model at all.

        Returns:
            bool: True unless `kind == "deny"`.
        """
        return self.kind != "deny"

    def __repr__(self) -> str:
        """Debug representation.

        Returns:
            str: `<ScopeRule <kind> <reason>>`.
        """
        return f"<ScopeRule {self.kind} {self.reason}>"


# ── mapper inspection ────────────────────────────────────────────────────────

def mapped_models() -> dict[str, type]:
    """{class name: mapped class} for everything registered on db.Model.

    Returns:
        dict[str, type]: Model class name -> the class itself.
    """
    models = {}
    # `db.Model` is Flask-SQLAlchemy's runtime-generated declarative base; ty
    # cannot resolve its MRO (see [tool.ty.rules] unsupported-base in
    # pyproject.toml) so `.registry` reads as unresolved even though it's a
    # real attribute at runtime.
    for mapper in db.Model.registry.mappers:  # ty: ignore[missing-attribute]
        models[mapper.class_.__name__] = mapper.class_
    return models


def local_table(model: type) -> sa.Table:
    """The model's own table — `learners`, not the `users` join for a subclass.

    Args:
        model (type): Mapped model class.

    Returns:
        sa.Table: The model's local table.
    """
    return sa.inspect(model).local_table


def _outbound_fks(model: type) -> list[tuple[str, str]]:
    """[(local column name, referenced table name)], with the inheritance-PK edge to `users.id` skipped.

    Args:
        model (type): Mapped model class.

    Returns:
        list[tuple[str, str]]: `(local column name, referenced table name)` pairs.
    """
    table = local_table(model)
    pk_columns = {column.name for column in table.primary_key}
    edges = []
    for column in table.columns:
        if column.name in pk_columns:
            continue
        for fk in column.foreign_keys:
            edges.append((column.name, fk.column.table.name))
    return edges


def _table_to_model() -> dict[str, str]:
    """Reverse index from table name to model class name.

    Returns:
        dict[str, str]: Local table name -> model class name.
    """
    return {local_table(model).name: name for name, model in mapped_models().items()}


# ── resolution ───────────────────────────────────────────────────────────────

def _resolve_direct(model: type) -> ScopeRule | None:
    """Check whether a model has a direct `teacher_id`-style FK.

    Args:
        model (type): Mapped model class.

    Returns:
        ScopeRule | None: A `direct` rule, or None if no such FK exists.
    """
    for column_name, target_table in _outbound_fks(model):
        if target_table == TEACHER_TABLE:
            return ScopeRule("direct", column=column_name,
                             reason=f"{column_name} -> teachers.id")
    return None


def classify_all() -> dict[str, ScopeRule]:
    """{model name: ScopeRule} for every mapped model. Pure, no DB access.

    Returns:
        dict[str, ScopeRule]: Every mapped model's resolved scope rule.
    """
    models = mapped_models()
    by_table = _table_to_model()
    rules = {}

    # Pass 1 — policy, self, direct.
    for name, model in models.items():
        override = POLICY.get(name)
        if override == "deny":
            rules[name] = ScopeRule("deny", reason="policy: not exposed")
            continue
        if override == "global" or name in GLOBAL_READABLE:
            rules[name] = ScopeRule("global", reason="ownerless shared content")
            continue
        if override == "school" or name in SCHOOL_SCOPED:
            rules[name] = ScopeRule("school", reason="narrowed to the teacher's school")
            continue
        if local_table(model).name == TEACHER_TABLE:
            rules[name] = ScopeRule("self", reason="the teacher's own row")
            continue
        direct = _resolve_direct(model)
        if direct is not None:
            rules[name] = direct

    # Pass 2 — one hop from a directly-owned model, and no further. Anything
    # deeper has to be a POLICY entry rather than a guess.
    directly_owned = {n for n, rule in rules.items() if rule.kind == "direct"}
    for name, model in models.items():
        if name in rules:
            continue
        for column_name, target_table in _outbound_fks(model):
            owner = by_table.get(target_table)
            if owner in directly_owned:
                rules[name] = ScopeRule(
                    "hop", column=column_name, via=owner,
                    reason=f"{column_name} -> {target_table}.id, scoped via {owner}",
                )
                break

    # Pass 3 — everything left is invisible.
    for name in models:
        rules.setdefault(name, ScopeRule("deny", reason="no path to a teacher"))
    return rules


_cached_rules = None


def rules() -> dict[str, ScopeRule]:
    """Cached `classify_all()` result — computed once per process.

    Returns:
        dict[str, ScopeRule]: Every mapped model's resolved scope rule.
    """
    global _cached_rules
    if _cached_rules is None:
        _cached_rules = classify_all()
    return _cached_rules


def readable_models() -> dict[str, type]:
    """{model name: mapped class} the assistant may query, sorted by name.

    Returns:
        dict[str, type]: Readable model class name -> the class itself.
    """
    models = mapped_models()
    return {
        name: models[name]
        for name in sorted(models)
        if rules()[name].readable
    }


def canonical_name(name: str) -> str:
    """Entity name as the mapper spells it, matched case-insensitively.

    Args:
        name (str): Entity name as given (any case).

    Returns:
        str: The mapper's canonical spelling, or `name` unchanged if unknown.
    """
    models = mapped_models()
    if name in models:
        return name
    folded = str(name or "").strip().lower()
    return next((n for n in models if n.lower() == folded), name)


def resolve(name: str) -> tuple[type, ScopeRule]:
    """(model class, ScopeRule). Raises PermissionError for unknown/denied.

    Args:
        name (str): Entity name (any case).

    Returns:
        tuple[type, ScopeRule]: The resolved model class and its scope rule.
    """
    models = mapped_models()
    name = canonical_name(name)
    model = models.get(name)
    if model is None:
        known = ", ".join(sorted(readable_models()))
        raise PermissionError(f"Unknown entity {name!r}. Readable entities: {known}.")
    rule = rules()[name]
    if not rule.readable:
        raise PermissionError(f"Entity {name!r} is not available to the assistant.")
    return model, rule


# ── the filter ───────────────────────────────────────────────────────────────

def scope_clause(name: str, teacher: Teacher) -> Any | None:
    """SQL clause restricting `name`'s rows to this teacher, or None for global.

    Args:
        name (str): Entity name.
        teacher (Teacher): Teacher to scope rows to.

    Returns:
        Any | None: A SQLAlchemy boolean clause, or None for globally-readable entities.
    """
    model, rule = resolve(name)
    table = local_table(model)

    if rule.kind == "global":
        return None
    if rule.kind == "self":
        return table.c.id == teacher.id
    if rule.kind == "school":
        # A teacher with no school sees no school rather than all of them.
        return table.c.id == (teacher.school_id or -1)
    if rule.kind == "direct":
        # classify_all() always sets `column` for a "direct" rule.
        assert rule.column is not None
        return table.c[rule.column] == teacher.id
    if rule.kind == "hop":
        # classify_all() always sets both `column` and `via` for a "hop" rule.
        assert rule.column is not None
        assert rule.via is not None
        owner_model, owner_rule = resolve(rule.via)
        owner_table = local_table(owner_model)
        assert owner_rule.column is not None
        owner_ids = sa.select(owner_table.c.id).where(
            owner_table.c[owner_rule.column] == teacher.id
        )
        return table.c[rule.column].in_(owner_ids)

    raise PermissionError(f"Entity {name!r} is not available to the assistant.")


def scoped_query(name: str, teacher: Teacher) -> tuple[Any, sa.Table]:
    """A SELECT over the model's local table, already restricted to `teacher`.

    Args:
        name (str): Entity name.
        teacher (Teacher): Teacher to scope rows to.

    Returns:
        tuple[Any, sa.Table]: `(select statement, local table)`.
    """
    model, _ = resolve(name)
    table = local_table(model)
    query = sa.select(table)
    clause = scope_clause(name, teacher)
    if clause is not None:
        query = query.where(clause)
    return query, table


# ── serialization ────────────────────────────────────────────────────────────

def visible_columns(model: type) -> list[str]:
    """Column names the assistant may see, redaction applied.

    Args:
        model (type): Mapped model class.

    Returns:
        list[str]: Column names, `REDACTED_FIELDS` excluded.
    """
    return [
        column.name
        for column in local_table(model).columns
        if column.name not in REDACTED_FIELDS
    ]


def serialize_row(model: type, row: Any, fields: list[str] | None = None) -> dict[str, Any]:
    """One row -> a JSON-safe dict. Redacted fields can never be requested back
    in: the allowlist is intersected, not merely subtracted from.

    Args:
        model (type): Mapped model class the row belongs to.
        row (Any): A row (mapping-like, e.g. a SQLAlchemy `Row`).
        fields (list[str] | None): Requested fields; defaults to all visible columns.

    Returns:
        dict[str, Any]: Field name -> JSON-safe value.
    """
    allowed = visible_columns(model)
    wanted = [f for f in (fields or allowed) if f in allowed]
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {field: _jsonable(mapping[field]) for field in wanted}


def _jsonable(value: Any) -> Any:
    """Coerce one value to a JSON-safe form.

    Args:
        value (Any): Raw column value.

    Returns:
        Any: `value`, or an ISO string / float for date/datetime/Decimal.
    """
    import datetime as _dt
    from decimal import Decimal

    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def describe(name: str) -> dict[str, Any]:
    """Schema of one entity, derived live from the mapper.

    Args:
        name (str): Entity name.

    Returns:
        dict[str, Any]: `{"entity", "description", "scope", "columns"}`.
    """
    model, rule = resolve(name)
    name = canonical_name(name)
    table = local_table(model)
    columns = []
    for column in table.columns:
        if column.name in REDACTED_FIELDS:
            continue
        target = next(
            (fk.column.table.name for fk in column.foreign_keys), None
        )
        columns.append({
            "name": column.name,
            "type": type(column.type).__name__.lower(),
            "nullable": bool(column.nullable),
            "references": target,
        })
    return {
        "entity": name,
        "description": description_for(name, model),
        "scope": rule.reason,
        "columns": columns,
    }


def description_for(name: str, model: type | None = None) -> str:
    """A human sentence if one is written, else one derived from the mapper.

    Args:
        name (str): Entity name.
        model (type | None): The mapped class, to avoid a re-lookup; resolved if omitted.

    Returns:
        str: A `DESCRIPTIONS` entry, the model's docstring, or a fallback listing columns.
    """
    if name in DESCRIPTIONS:
        return DESCRIPTIONS[name]
    model = model or mapped_models()[name]
    doc = (model.__doc__ or "").strip().split("\n")[0].strip()
    if doc:
        return doc
    names = ", ".join(visible_columns(model)[:8])
    return f"Rows in `{local_table(model).name}` — fields include {names}."


# ── startup self-check ───────────────────────────────────────────────────────

def log_classification(logger_: logging.Logger | None = None) -> None:
    """Print every model and how it resolved, once — surfaces an unclassified model landing in "deny" instead of failing confusingly at query time.

    Args:
        logger_ (logging.Logger | None): Logger to use; defaults to this module's.

    Returns:
        None
    """
    log = logger_ or logger
    lines = []
    for name, rule in sorted(rules().items()):
        lines.append(f"    {name:<26} {rule.kind:<7} {rule.reason}")
    log.info("Assistant entity scope:\n%s", "\n".join(lines))
