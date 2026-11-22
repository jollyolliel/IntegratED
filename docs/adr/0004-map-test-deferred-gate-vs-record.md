# Map test completion is a gate; deferral needs its own flag

The dashboard and the rest of the learning path must not be reachable until
a Learner has been through the placement flow — some value is needed as a
hard gate. The obvious choice is a single "completed the map test" boolean
doing double duty as both that gate and the record of whether the test was
actually taken. That collapses two different questions into one: a Learner
who taps "I'll do this later" still has to get past the gate (the dashboard
has to open for them), but the app also needs to remember that they didn't
really take the test — to keep showing the reminder banner, to keep the
placement routes reachable, and to tell a Volunteer's partner view the truth
about their learner's status.

The decision is two separate booleans. The completion flag is set True the
moment the Learner either finishes or defers — it is purely the *gate*, and
reads as "may this learner reach the dashboard." A second, independent flag
records whether the test was actually completed versus deferred — the
*record*. Anywhere in the app that means "has this learner really been
assessed" must check both together; checking the gate flag alone silently
treats a deferral as a completion.

Status: accepted.
