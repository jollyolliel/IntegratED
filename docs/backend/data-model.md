# Data model

The ideas behind the schema that no single class shows. Each model's fields
and behaviour are on its own class docstring in `models.py` /
`models_learning.py`; vocabulary is in [../CONTEXT.md](../CONTEXT.md).

## People

- **Joined-table inheritance.** `users` holds the shared columns; each role
  has its own table keyed by `id → users.id`. A query joining **two** role
  classes (learners with their volunteers) needs `aliased(Model, flat=True)`
  on each side, or the `users` join is emitted twice. `db.get_or_404(User, id)`
  returns the subclass.
- **A pair is a fact about a learner**, not a row of its own:
  `Learner.volunteer_id`. One volunteer can hold several learners up to
  `Volunteer.match_capacity` (teacher-set, 1–5); `Teacher.default_match_capacity`
  only seeds a newly registering volunteer. `is_matched` is a cached flag on
  *both* sides, so a match is made with `teacher_ops.match_pair` and dissolved
  with `Learner.unmatch()` / `Volunteer.release_learners()` — never by
  writing `volunteer_id`. Capacity can't drop below the learners already held.
- **Learner progress lives in JSON columns** on `Learner`:
  `completed_lesson_ids` (the single source of what's finished),
  `completed_topic_ids`, `subject_levels` (placement results — `{}` means
  *not assessed*, never default it to a level), `garden_state`,
  `equipped_items`, `survey_data`. They are not mutation-tracked: build a new
  value and assign it; editing in place is silently not saved.
- `Teacher.match_settings` stores the teacher's chosen importance **levels**,
  not multipliers — see [../features/matching.md](../features/matching.md).
  Match scores are never stored; they are recomputed wherever they are shown.

## Attendance is per person

One `Attendance` row per **person** per session day, not one per pair
(ADR 0001). A learner and their volunteer each hold their own record; the
volunteer's is seeded from the learner's when logged and may diverge after.
An absence is a row with `is_present=False` and duration 0, never a missing
row. A volunteer with several learners has one row for the day with no
partner, its duration the longest of their learners'.

Consequence: **hours totals sum learner-owned present rows only**
(`Attendance.programme_hours`) — summing the whole table counts each paired
hour twice.

## Deleting

- People are deleted only through `roster_ops.delete_user`, which runs the
  role's whole cascade and **commits once** (or rolls all of it back). A
  learner or volunteer loses their attendance, assignments, sessions and
  matches; a teacher's roster, attendance and assignments stay with
  `teacher_id` NULL (volunteer hours are summed from them) and only their
  assistant history goes; an administrator's articles pass to the `heir`, by
  default the longest-serving other administrator, and the last administrator
  can't be deleted (`LastAdministratorError`). The caller checks ownership
  first. Teacher, school admin, administrator and the person's own settings
  page all call it.
- A new table that points at a person needs a line in the matching `_clear_*`
  function there.
- **SQLite doesn't enforce foreign keys; Postgres does.** Dev and tests run on
  SQLite, so a delete that leaves a dangling `NOT NULL` reference passes every
  test and fails in production. Reason about every FK when deleting a parent.
- Deleting a school nulls its people's school and teacher links and its
  donations' school, and dissolves their matches rather than deleting them.

## Other shapes worth knowing

- **Announcement dismissal** is one integer per user, the highest
  announcement id dismissed, never a foreign key (ADR 0003).
- **Placement-test detail is thrown away** on completion; only the
  per-placement-scale levels and two flags remain (ADR 0002, ADR 0004).
- **Content is deleted only by `flask import-questions --prune --apply`**
  (`helpers/content/_prune.py`), which also strips removed ids from learners'
  progress columns and drops sessions on removed lessons. A new table or JSON
  column that points at content needs a line in `plan_prune`
  ([../learning/content.md](../learning/content.md)).
- **Donations** are recorded from Stripe — the webhook is authoritative,
  idempotent on `stripe_session_id` — and linked to a school by the school's
  **name** in the checkout metadata.
- **Time** is stored as naive UTC. Compare with `helpers.utils.utcnow_naive()`;
  filter a DateTime column to one calendar day with `day_bounds()`, never
  `== date`, which misses every row not written at midnight.

## Changing the schema

1. Edit the model with a `Mapped[...]` annotation on a `db.Column(...)` /
   `relationship(...)`. Never switch a column to `mapped_column()` — it
   derives SQL type and nullability from the annotation and quietly changes
   the schema (Postgres enforces `VARCHAR` length, SQLite ignores it, so dev
   looks clean while prod drifts).
2. The annotation states the real nullability: a column without
   `nullable=False` is `X | None`, whatever its Python `default=`.
3. `flask db migrate -m "…"`, then **read the generated file** — autogenerate
   misses SQLite type changes and server defaults.
4. Keep it dialect-agnostic: dev is SQLite, prod is Postgres 17. Use
   `sa.inspect(conn).has_table()` / `.get_columns()`, branch on
   `conn.dialect.name` for anything dialect-specific, never `sqlite_master`
   or `INSERT OR IGNORE`. Postgres backs a UNIQUE constraint with an index of
   the same name — drop one, not both.
5. `flask db upgrade` locally and confirm `flask db current` is head.

CI replays the whole migration chain on a real Postgres
(`.github/workflows/migrations.yml`) when migrations or models change. In
production the upgrade runs once per deploy, before the new revision serves;
a failed migration stops the deploy — [../operations/database.md](../operations/database.md).
