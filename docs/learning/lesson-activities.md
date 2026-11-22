# Lesson activities — the quiz and the minigames

A lesson is played as the quiz (`Lesson.game_type` null) or as one of five
minigames: `rocket`, `word_storm`, `match_up`, `garden_grow`,
`potion_workshop`. They share one shape, so a change to that shape touches
all six.

## The shared shape

| Step | Where |
|---|---|
| Lesson overview page with a start button per type | `routes/learner/_learning_path.py`, `pages/learner/learning/overview.jx` |
| Game page, inside `<GamePage>` (GSAP, `games.css`, the game's own `game-<slug>.css`, `GameKit`, completion overlay, level-up modal) | `routes/learner/_games.py`, `pages/learner/learning/<type>.jx` |
| What a run is made of | `GAMES[lesson.game_type].serves` (`helpers/learning/_games.py`): every question (the quiz), the questions with options (Rocket, Word Storm, Garden Grow, Potion Workshop) or every Match Up pair. `deal(lesson)` returns those units; it is both what is served and what is scored |
| Load questions + resume progress | `GET /api/quiz/<lesson_id>/questions` — the dealt questions only; no `answer`, no `fill_blank_options`; a `match` question comes as unpaired `match_left` / `match_right` (the right column already shuffled) |
| Grade each answer | `POST /api/quiz/validate-answer` (`grade` in `helpers/learning/_validators.py`; after the third wrong try at a typed answer it also returns `hint`); Match Up: `POST /api/match-up/<lesson_id>/pair` |
| In-progress state | the answer log (`helpers/learning/_answer_log.py`): one `LearningSession(session_type="answer_log")` row per learner + lesson (a unique constraint), one entry per try at a unit, deleted at completion |
| Result | one `LearningSession` row per learner + lesson typed `result_type(lesson)` — the game's name, or `"quiz"` — holding the graded score; a repeated completion reports it back |
| Finish | every type: `POST /api/lesson/<lesson_id>/completion` → `complete_lesson()` → `record_lesson_completion()` |
| End screen | `GameKit.finish(bonus)` shows `CompletionOverlay` with the server's score once the completion is saved, or a retry bar if it isn't |
| Strings | a `T` / `QUIZ_T` object at the top of the page script, built with `t()` + `tojson` |

Resume behaviour differs: the quiz jumps to `progress.resume_index`; Rocket,
Garden Grow and Potion Workshop rebuild from `progress.correct_ids`; Word
Storm restarts; Match Up is one screen with nothing to resume.

## Scoring and the anti-cheat rule

**Never trust a number the browser reports, and never send it an answer.**
`complete_lesson()` locks the learner, then scores the dealt units the answer
log saw right at the first try. The browser sends no score at all, only a
game's bonus count, which is capped by what that score could have earned; a
malformed payload counts as zeros (ADR 0005). The response carries the score
(`correct_count` / `total_count`), and the page shows that, never a count of
its own. A quiz with a question not yet answered right is refused (400). A
repeat of a completion already recorded (a double submit finds the log
cleared) changes nothing and reports the lesson as already completed.
`validate-answer` refuses a question from another lesson. Validators only say
right or wrong; the quiz page shows its own translated feedback (`QUIZ_T`).

Minigame XP = `correct × 10 + 50` (the quiz awards a flat 50), plus the game's bonus at 10 XP per unit — Garden
Grow grains (capped at `correct × GARDEN_PLOTS`), Potion Workshop golden
potions (capped at half the questions, rounded up) — then `apply_xp`'s level
multiplier. First completion only. Score counts first-try correct answers.

A first-time Potion Workshop completion with a golden potion (and a correct
answer) sets `Learner.xp_boost_pending`; `record_lesson_completion` doubles the
next first-time completion's XP, quiz or game, and clears it. One boost at a
time; a replay neither spends nor earns one. The completion response says so
in `xp_boosted` / `boost_earned`, which `GameKit.finish` passes to the
overlay, and the lesson overview shows a ×2 badge while one waits. A level-up
lists the wardrobe items it unlocked (`new_items_unlocked`) in the level-up
modal.

## The games, by design intent

All five are calm (no timer, nothing lost on a wrong answer) and pair the
question with a living illustrated scene that each right answer changes.

- **Garden Grow** (building): a jungle clearing. A correct answer earns a
  water drop the learner chooses to spend — plant a seed or make it rain on
  the whole clearing, which grows every plant a stage and harvests
  already-full super blooms as grains. The 8 plots persist on
  `Learner.garden_state` across lessons (`GET/POST /api/garden`); each plot
  has a fixed spot and species (`SPOTS` in the page script). The scene is
  display-only; the two spend buttons are the only controls.
- **Potion Workshop** (choice): questions are chunked into recipes of two
  (three for the last on odd counts) that the learner brews in any order;
  answers are ingredient bottles poured into the cauldron in a cottage
  workshop; a recipe with no mistakes is a golden potion on the mantel, and
  one golden potion doubles the XP of the learner's next lesson.
- **Rocket** (journey): a star voyage — each right answer flies the rocket a
  hop along a route of moons; the last lands it on the home planet. A wrong
  answer makes it sputter and wait.
- **Word Storm** (shown as "Lantern Sky"): the answers are lanterns
  drifting on a gusty wind over a night lake (never leaving the stage while
  the learner chooses); the right one rises and lights a star of a
  constellation, the rest blow away and the next set blows in. Its lantern
  drift, wind and burst effect are the model for anything floating.
- **Match Up** (building): tap a word, then its partner; each pair couples a
  carriage labelled with it onto a train, which leaves when complete.

New games follow the same pattern — see
[../ui-design/designing-for-learners.md](../ui-design/designing-for-learners.md).

## Adding a new game

Every place a game type is listed — miss one and the lesson silently falls
back to the quiz somewhere:

1. `GAMES` in `helpers/learning/_games.py` — completion event name, what it
   `serves`, its XP, and a `_Bonus` with its cap if the game awards extra XP.
   The type is also its result record's `session_type` (at most 20 characters;
   `quiz`, `answer_log` and `placement` are taken).
2. A page route in `routes/learner/_games.py` — the learner gates, a redirect
   to the quiz if `lesson.game_type` doesn't match, `already_completed`, a
   `<type>_started` event.
3. `templates/pages/learner/learning/<type>.jx` on `<GamePage styles="game-<slug>">`,
   calling `GameKit.init({lessonId, game})`, with its `.<prefix>-*` rules in
   `static/css/pages/game-<slug>.css`.
4. The start button in `overview.jx`, and the badge in `topics.jx`'s
   `game_meta` plus a `.game-badge-<type>` colour in `learning-nav.css`.
5. `learner.<type>.*` translation keys.
6. The hand-kept lists of game types in the tests: the parametrize in
   `tests/unit/test_game_completion.py`, `GAMES` in `tests/web/test_api.py`,
   and `GAME_PAGES`, `GAME_MARKERS` and the overview start-button parametrize
   in `tests/web/test_learner.py`. `grep -rn "potion_workshop" tests/` finds
   them all.
7. The `session_type` comments in `models_learning.py`, and the game counts
   in `components/shell/game_page.jx` and this file.
8. `game_type` in content ([content.md](content.md)); any constant the page
   script shares with Python is passed in by the page route, never copied
   (as `garden_plots` carries `GARDEN_PLOTS` into `N_PLOTS`).

## Page-script toolkit

What a game page already has to hand (read `garden_grow.jx` for a calm game
using all of it): `GameKit` (`components/game_kit.jx`) — `questions()`,
`check()` / `checkPair()` (true, false, or null when the request failed: say
"try again", never count it wrong), `finish(bonus, {after})`, `progress()`
for the HUD, an unbiased `shuffle()`, `speak()` / `speakQuestion()` and
`track('game_answer', {first_try})` — plus a `pageRect()` function for flying
elements (each game page carries its own copy), `<AudioButton>` and GSAP.

## Game page practicalities

- Flying elements live on `<body>` in page coordinates
  ([../ui-design/designing-for-learners.md](../ui-design/designing-for-learners.md)).
- Answer buttons are the shared clickable card (`<Card clickable>`, or the
  `quick-action-card` class when built in script), sized per instance.
- Speech: the question's `question_sound_url` if present, else
  `speechSynthesis`, which also takes over when the audio fails to play.
