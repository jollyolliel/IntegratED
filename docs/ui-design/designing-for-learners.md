# Designing for learners

Read for anything a learner sees: dashboard, survey, placement test, learning
path, games, worksheets. Staff pages can assume a reader; learner pages
cannot.

## Who the learner is

A young refugee, usually not literate in any language yet, often on a cheap
phone, using the app in one of 13 interface languages (Arabic, Farsi
and Pashto right-to-left). They sit with a volunteer tutor some of the time and alone
the rest. Every screen should work for a child who can't read the words on
it.

## The principles

**Meaning never rides on text alone.** Pair every label with an icon, an
illustration, a colour *and* a shape. Text is for the tutor and for screen
readers; the picture is for the learner.

**Colour is never the only cue either.** State is carried by shape first — a
tick in a disc for done, a ring for "you are here" — with colour reinforcing
it, and an `sr-only` sentence stating it. The lesson list's game badge is
icon + colour with the game's name in `title` and `aria-label`.

**Anything to read can be heard.** Questions carry a read-aloud
`<AudioButton>`: it plays the question's recorded `question_sound_url` when
there is one, else the browser's `speechSynthesis`. Word chips speak
themselves when tapped. New learner screens with instructions offer the same.

**Calm, not pressure.** No timers, no lives lost for a wrong answer, retry
freely, and score only first-try correct answers so retrying is never
punished. Every minigame follows this; new games do too.

**Answering is the game.** In a minigame the answer *is* the mechanic — a
correct answer becomes a water drop, an ingredient poured into a cauldron —
not a quiz followed by a reward cutscene. And give real choices that persist:
the garden carries over between lessons, the recipe order is the learner's.

**Progress means work done, never position.** Progress strips have one tick
per item in list order, green when actually finished, a sky ring on the
current one. A percentage counts completed items, so clicking ahead never
inflates it; a "Question 3 of 8" label shows position separately. The tick
row is one `role="img"` with a spoken summary, and the visual readout beside
it is `aria-hidden`, so a screen reader hears it once.

**Big targets, one thing at a time.** Answer options are large clay buttons
(`<McOptions>`, `<Card clickable>`), with letters A–F as a second cue beside
colour. One question on screen. The primary action is the one green button.

**Suggest, never block.** The placement test recommends a course and a starting
topic; the path highlights them but leaves every course and topic open. Replaying a finished lesson is
always allowed (it just earns no XP the second time).

**Every language, both directions.** Strings through `t()`, including the
ones a game script builds at runtime (a `T`/`QUIZ_T` object rendered with
`| tojson`, placeholders filled in JS). Layout in logical directions. Test a
learner screen in Arabic as well as English.

## Practicalities

- Flying elements in games (a seed, a drop, a bottle clone) are positioned on
  `<body>` in page coordinates, read once at animation start — fixed
  positioning lands them in the wrong place if the learner scrolls mid-flight.
- Learner art is plain static files in `static/svg/` and `static/img/`,
  served publicly via `url_for('static', …)`. Only uploads and worksheet PDFs
  are login-gated.
- The learner's avatar is the Face System — a full-body character of stacked layers (ADR 0017);
  the older layered Avatar System is retired.

Game mechanics and how to add one: [../learning/lesson-activities.md](../learning/lesson-activities.md).
