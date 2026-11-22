# Placement test session is deleted on completion, not snapshotted

When a Learner finishes (or skips) the placement test, the obvious instinct
is to keep a record of how it went — a `map_test_data` snapshot of the
questions asked, the answers given, the staircase's path to each settled
level. Nothing in the product actually reads that history, though: every
surface that cares about placement only ever needs the *outcome* — the
assessed level per subject and whether the test counts as taken.

The decision is to let the in-progress placement session be the only place
that detail ever lives, and delete it the moment the test completes. The
result is captured entirely by the Learner's completion flag, the deferred
flag, and the per-subject assessed levels — no snapshot is written alongside
it. This is a deliberate trade: if a future feature wants "what did this
learner get wrong on the placement test," that data no longer exists once the
test is done, and adding it back means introducing a real snapshot at
completion time rather than recovering one that was silently kept.

Status: accepted.
