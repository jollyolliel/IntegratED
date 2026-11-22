# Per-person attendance records, not one shared row per pair

A matched Learner and Volunteer meet together, so the obvious schema is one
Attendance row per session shared by both of them. But a Learner can be
unmatched (no Volunteer to share a row with), a Volunteer can hold several
Learners in one sitting (whose row would it be?), and the two sides of a pair
routinely disagree in practice — a Volunteer edits their own duration after
the fact, or marks themselves absent while their Learner's row stays present.
A single shared row has nowhere to put that disagreement without inventing a
second table just to hold the other person's version.

The decision is one Attendance row per **person** per session, not one row
per pair. A Learner and their Volunteer each hold an independent record for
the same day — the Volunteer's is seeded from the Learner's numbers when the
session is first logged, and is free to diverge from then on (a later edit to
one never propagates to the other). Absence is a recorded fact (a row with
`is_present=False`, duration 0), never a missing row, so "didn't meet" stays
distinguishable from "nobody logged it yet." The trade-off this buys: a
programme-wide hours total can no longer be a bare `SUM(duration)` over the
table — a matched pair holds two rows for the same hour, so that reads ~2x.
Anywhere a total is needed, it must sum only Learner-owned present rows (the
one total that equals the sum of every Learner's own hours) rather than the
whole table.

Status: accepted.
