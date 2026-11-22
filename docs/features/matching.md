# Volunteer–learner matching

A teacher pairs each learner on their roster with a volunteer tutor. They can
match by hand or run **Auto-Match**, which proposes a whole-roster assignment
the teacher reviews, edits and approves.

## How it works

1. **Score.** `helpers/matching.py` is pure — no database. It scores every
   learner × volunteer pair from their survey answers (`survey_data`) on a
   set of `FACTORS` (age, languages, personality, hobbies…), each
   factor's base points weighted by the teacher's priorities.
2. **Assign.** The scores form a matrix and a Hungarian solver picks the best
   overall assignment — `helpers/assignment.py`, a pure-Python port of
   scipy's `linear_sum_assignment` that returns the identical pairing, ties
   included; a dev-only test checks it against scipy itself. Each volunteer is expanded into one column per
   capacity slot, and each deeper slot costs a *spread* penalty, so learners
   spread across volunteers before doubling up. A small bonus for the current
   pairing makes a re-run stable instead of shuffling people for nothing.
3. **Preview.** `POST /api/matching/preview` returns the proposed moves and
   alternatives; the teacher edits them in the Auto-Match modal.
4. **Apply.** `POST /api/run-matching` applies the approved moves through
   `teacher_ops`: it releases every learner who moves first, then matches,
   so a volunteer isn't "full" of the learners it is about to lose. Each step
   commits; a pair refused mid-run (someone else matched meanwhile) is counted
   and reported, not retried.

The pool is always the **teacher's own roster** (`teacher_id`), never the
whole school — the apply path refuses anyone else's people, and a wider pool
would waste slots on pairs that then fail.

## Invariants

- **App code holds a `Scorer`** (`Scorer.for_teacher(teacher)`), which binds
  one teacher's resolved settings to scoring, the matrix and the solver. It
  takes Learner and Volunteer rows directly and hands back the rows it was
  given. The bare `match_all` needs a board the `Scorer` scored; calling the
  primitives directly makes the preview disagree with what the teacher
  configured.
- Teacher priorities are stored as **level indices** in
  `Teacher.match_settings` and resolved by `resolve_settings`, which rescales
  the multipliers to average 1.0. That keeps the fixed `MATCH_BANDS`
  (strong/good/fair/weak) and `SPREAD_PENALTIES` calibrated however a teacher
  weights things.
- `_score_matrix` is the one definition of a score; `score_match` is one cell
  of it. Every factor is an exact integer, weighted once, in a fixed order.
- **Scores are never stored.** A pair outlives both its survey answers and
  the teacher's weighting, so a stored score goes stale; everything that
  shows one recomputes it. The raw total has no ceiling, so it is shown as a
  band colour with the number as a tie-breaker, never as a percentage.
- Capacity: a volunteer holds up to `match_capacity` learners; matching and
  unmatching go through `teacher_ops` / `Learner.unmatch()` so `is_matched`
  stays right on both sides ([../backend/data-model.md](../backend/data-model.md)).
- The AI assistant's `preview_auto_match` is deliberately narrower: it only
  fills open slots with unmatched learners, because a staged change that
  silently breaks up an existing pair is not something to approve blind.

## Showing pairs

The teacher's people page lists each person **once**, learners and volunteers
in two columns, and draws each pairing as a line between them — a volunteer
with several learners reads as one bracket, not repeated cards. The line's
colour is the match band. Never add a third "pairs" list that repeats both
columns.

## Adding a matching factor

1. `helpers/matching.py`: `FACTORS`, `ScoringTraits`, `_preprocess_entity`
   and `_score_matrix`; revisit `MATCH_BANDS`.
2. Collect it in both surveys (learner and volunteer survey pages and their
   routes) and show it on the person detail pages.
3. `teacher.people.factor_<name>` and `factor_<name>_hint` translation keys
   (the priorities modal loops over `FACTORS`).
4. The factor list in the assistant's `match_score` tool description.

No migration: survey answers are JSON, and missing priority levels default.
