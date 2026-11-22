# The learner journey

From sign-up to levelling up, and the state that carries a learner through
it.

```
register (invite code) → survey → placement test (or defer) → dashboard → learning path → lesson → completion → XP / level / avatar items
```

The placement test's last answer hands over to its result through
`<JourneyLoader>`, which lasts at least 3s on purpose so the result has a
moment to land — don't trim it as a performance fix.

## Gates

Every learner page past onboarding — dashboard, learning path, games,
worksheets — waits on `Learner.onboarding_step`: the learner blueprint's
`before_request` sends an unfinished learner to the survey, then to
`/map-intro`, and the learner `/api` blueprint refuses them with 403. Two flags,
two meanings for the placement test (ADR 0004):

- `completed_map_test` is the **gate**: true once the learner has finished
  *or deferred* the test.
- `map_test_deferred` is the **record**: true when they chose "I'll do this
  later".

"Assessed" means `completed_map_test and not map_test_deferred`. Anything
that means "this learner was really placed" — the dashboard's reminder
banner, the volunteer's view of their learner, whether the placement routes
stay reachable — checks both. Checking the gate alone treats a skip as a
result.

## Placement test

One adaptive staircase per **placement scale**, the subjects that have
placement questions (`apply_map_answer` in `helpers/learning/_placement.py`
documents the algorithm). Each scale starts at level 2. It climbs after 2
correct answers in a row and steps down after a wrong one. At level 1 it needs
2 misses in a row before the floor counts. A scale **settles** once its level
is bracketed, or it hits the floor or ceiling, *and* it has had its share of
`MIN_QUESTIONS`. Until then it keeps probing around its estimate, so answers
can still move the level up or down. Every learner answers 10 to 20 questions
(`MIN_QUESTIONS`, `MAX_QUESTIONS` in `routes/api/map_test.py`). The test is
shorter only when the questions run out: a dry level borrows from the level
next to it, then the scale settles early. State lives server-side in a
`LearningSession`, so a reload resumes. The learner never sees right or wrong.
There are no wrong answers in a placement test.

On completion the result is just `Learner.subject_levels` (`{scale: level}`)
plus the two flags; the session is deleted and no detail is kept (ADR 0002).
Deferring sets `subject_levels` to `{}` — empty means *not assessed*.

## Where to start, where they are

- `get_recommended_start(learner)` turns an assessed level into a starting
  **course and topic** (ADR 0016). The course is the one whose placement band
  holds the level, clamped to the lowest or highest band. When nothing is
  banded on the scale, the scale itself is the course, if it is a course. The
  topic is the first one at the highest `Topic.level` at or below the level.
  It's computed live from current content and shown as a suggestion until the
  first lesson is finished: on the placement result, the dashboard, the
  course list and the topic list. Every course and topic stays open
  regardless.
- `get_learner_progress_position(learner)` answers "what should they do
  next": in their current course (last finished topic's, else the
  recommended one), the lowest-level topic with unfinished lessons and its
  first unfinished lesson.
- `get_pair_learning_snapshot(learner)` answers "what have they done" for
  staff dashboards.

`Topic.level` drives both ranking and recommendation. In a course on a
placement scale it is a scale level inside the course's band; in any other
course it is the course's own rank, aligned with its placement questions'
`MapQuestion.level`. The authoring rules are in [content.md](content.md).

## Completion and progress

Every activity finishes through `complete_lesson`, which locks the learner
row (`lock_learner`) before scoring, then `record_lesson_completion` in
`helpers/learning/_completion.py`, which on the **first** completion only appends the lesson to `completed_lesson_ids` and
awards XP. A topic becomes complete when all its lessons are. Replays are
always allowed and earn nothing. `completed_lesson_ids` is the single source
of truth for "done"; `LearningSession` rows hold in-progress state and the
last result.

`completed_lesson_ids` has no timestamps — "lessons finished this week" is
not derivable; `LearningSession.updated_at` is the only activity timestamp.

## XP, levels, avatar

All in `helpers/gamification/`:

- XP per completion is computed by the activity (base + game bonuses, see
  [lesson-activities.md](lesson-activities.md)), doubled once by a waiting
  golden potion boost, and passed through `apply_xp`, which applies the
  multiplier of the learner's current level.
- Level = `min(7, xp // XP_PER_LEVEL + 1)`, names in `LEVEL_NAMES`. Use
  `compute_level` / `level_name`, or `level_progress(xp)` for the dashboard's
  level bar, rather than recomputing in a template.
- The avatar is the **Face System**: a full-body character whose layers
  (`FACE_LAYER_ORDER`) stack in one 200×300 box from `static/svg/avatar/`,
  plus an outfit colour that tints the clothes (ADR 0017). Species, outfit and
  colour are `FACE_REQUIRED_SLOTS` and can't be taken off. Items unlock by level
  (`FACE_UNLOCK_LEVEL`, enforced server-side when equipping). New item =
  an SVG in `static/svg/avatar/` (200×300 viewBox, drawing in `<g id="art">`) plus a catalogue row in `_face.py`.
  `resolve_face` is how every reader sees what a learner wears; a level-up lists
  the items it unlocks in the level-up modal.

## Worksheets

Teachers assign printable worksheets to a learner; the learner sees them on
the dashboard and marks them done. The flow is in
[../features/worksheets.md](../features/worksheets.md).
