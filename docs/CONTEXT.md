# IntegratED

Youth-to-Youth (Y2Y) learning platform for ACS Athens. Serves refugee learners
from Home Project — largely illiterate in any language — matched with
volunteer tutors and supported by their school's teachers.

## Language

### People & pairing

**Learner**:
A refugee student using the platform to learn — one of the five user roles.
Logs in with a username and password, is optionally matched to one Volunteer,
and is assigned to one Teacher.

**Volunteer**:
A person tutoring one or more Learners. Signs in via Google, and has a
capacity for how many Learners they can be matched to at once.

**Teacher**:
Staff who manages a roster of Learners and Volunteers at one school — runs
matching, logs attendance, assigns worksheets. Signs in via Google.

**Administrator**:
Global, cross-school staff account. Manages every school, all users,
donations, and site content.

**SchoolAdmin**:
Per-school staff account, scoped to one school's people, donations and
settings — narrower than Administrator, no cross-school view.

**Pair** (also "match"):
A Learner and the Volunteer currently attached to them. A fact about a
Learner, not a thing in its own right — there is no page or identity for a
Pair beyond the two people it names. "Matching" is the act of creating one
(an algorithm run, or a manual match); "Pair" is the resulting attachment. A
Volunteer with room for more than one Learner can be in several Pairs at
once; a Learner is in at most one.
_Avoid_: partnership — not the app's word.

**Roster**:
The Learners and Volunteers a Teacher manages at their school — the
population the people list and the matching pool draw from.

### Attendance & sessions

**Attendance**:
A record of one person's own account of meeting for one session, on one day.
A Learner and their Volunteer each keep their own record for the same
day — not one shared row for the pair.

**Session** — three unrelated things share this word here:
- **Attendance** — see above; sometimes just called "a session" in
  conversation ("log today's session").
- **Learning session** — in-progress or completed state for one learner's
  activity: the placement test, a quiz, or a minigame run.
- **Browser session** — the standard web session cookie (language choice, an
  in-flight invite code, and the like), unrelated to learning.
Say which one; "session" alone is ambiguous in this codebase.

### Placement test

**Placement Test** (also "MAP Test"):
The adaptive test a Learner takes before reaching the dashboard. Produces an
assessed level per placement scale, which recommends a Course and a starting
topic in it.

**Placement scale**:
One ladder of levels (1, 2, …) the placement test measures, such as
"English". It is a subject that holds the placement questions. Usually it is
placement-only, hidden from the learning path. Older content uses a course as
its own scale.

**Band**:
The inclusive range of placement-scale levels one Course serves, for
example levels 1–2. The bands on a scale cover every level, without gaps or
overlaps.

**Settle**:
A placement scale's staircase stops probing. That needs its level bracketed
(one level passed, the next failed), or the floor or ceiling reached, *and*
its minimum number of answers. Until then it keeps probing around its level.
The test as a whole finishes once every scale has settled, or the
question-count cap is reached.

**Deferred**:
A Learner chose "I'll do this later" instead of taking the Placement Test.
Reaching the dashboard still requires the test to be marked done — that's a
gate, not proof it was taken — so a separate deferred flag is what
distinguishes a genuine completion from a skip. "Assessed" means completed
**and not** deferred; completion alone doesn't mean the test was taken.

### Minigames

**Grain**:
Garden Grow's bonus-XP unit, earned when a storm harvests an
already-fully-grown plot instead of growing it further.

**Super bloom**:
A Garden Grow plot at its final growth stage — can't grow further, so a
storm harvests it for a grain instead.

**Golden potion**:
A Potion Workshop recipe brewed with zero wrong answers — earns bonus XP and
a mark on the shelf. A lesson with at least one stores a golden potion boost:
the learner's next lesson earns double XP.

**Recipe**:
In Potion Workshop, one chunk of a lesson's questions brewed together as a
single potion.

### Gamification

**Face System**:
The current avatar builder — a full-body character stacked from SVG layers
(species, shoes, bottom, top, hair, eyes, mouth, extra) plus an outfit colour,
which a Learner equips to customize their on-screen character.
Replaced the Avatar System below.

**Avatar System** (retired):
The earlier character-customization mechanism — image layers placed by
hand-tuned per-item positioning onto a base character. No longer used for
new work.
_Avoid_: calling the current character system "the avatar system" — that
name now means only the retired one.

### AI assistant

**Stage** / **staged write**:
A change the Teacher AI assistant has proposed but a Teacher has not yet
approved. Staging records what would change and how; applying is the
separate, explicit step that actually makes it happen. Unrelated to a Garden
Grow plot's growth stage — same word, different concept.

**Scope** (AI assistant):
The set of data one Teacher's assistant conversation is allowed to read,
derived automatically from how a kind of record relates back to that
Teacher. A kind of record with no such relationship is invisible to the
assistant until someone deliberately allows it.

### Content & worksheets

**Course**:
What a Learner sees as one thing to study: a subject with its topics and
lessons ("English: First Steps", "Phonics"). A course may sit on a placement
scale with a Band. The code and schema still call it a Subject.
_Avoid_: "subject" in learner-facing copy.

**Worksheet**:
A piece of practice content — markdown or a PDF — a Teacher can hand out.

**Assignment**:
One Worksheet given to one Learner, outstanding until the Learner or their
Teacher marks it done.

**Lesson**:
The unit of the learning path a Learner completes — either a quiz or one
minigame. Never a single question; a Lesson holds many.
