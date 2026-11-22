# Learning content — `questions.json`

**The repo holds only a small dev sample** (2 courses, every question type and
game, a few worksheets). The real curriculum is proprietary and lives in the
bucket's `content/` folder: `questions.json`, `worksheets/manifest.json` and
`worksheets/*.md` (the PDFs are in `worksheets/`), plus `announcements.json`.
Every environment reads its bucket's copy (`helpers/content_source.py`): the dev
bucket's is the sample from `seed/files/content/`, and `flask release` refuses to
run if production's is missing. To edit the real content, copy `content/` down,
edit, validate with `flask import-questions --prune` against a dev database, then
`gsutil cp` it back before deploying. To run the curriculum tests, put the full
copy in a folder (`questions.json` plus `worksheets/` with the PDFs) and set
`CURRICULUM_DIR` to it.

The rest of this page describes the file format, which both copies share. It is
loaded by `helpers/content/` — automatically into an empty dev database,
in production by `flask release` at every deploy (with `--prune`), and on demand
with `flask import-questions` (add `--sound` to generate the ElevenLabs audio
ahead of first play: see "Audio" below). Importing never generates audio itself.

## The model

A learner sees **courses** (each a `Subject` → topics → lessons → questions).
The placement test measures one **placement scale**, for example `"English"`,
levels 1…N. Each course on that scale declares the **band** of scale levels it
serves. The learner's level picks the course whose band holds it, then the
starting topic inside that course. Every course and topic stays open to every
learner; the result is only a suggestion. The design is in ADR 0016.

A course with no band is not on any scale. It works as before: nothing
recommends it unless its own placement questions name it (the older shape,
below).

## Shape

The file is a JSON list. Each entry is a course or the one `"Map Test"`
entry, in any order.

```json
[
  {
    "name": "English: First Steps",
    "icon": "seedling",
    "description": "Sounds, letters and first words.",
    "placement": { "scale": "English", "min_level": 1, "max_level": 2 },
    "topics": [
      {
        "title": "Letter sounds", "icon": "ear-listen", "description": "Hear each letter.",
        "overview_markdown": "### Listen and tap", "level": 1,
        "lessons": [
          {
            "title": "A, B, C", "icon": "music", "description": "Three sounds", "game_type": null,
            "questions": [
              { "content_type": "multiple_choice", "question_prompt": "Which letter says /b/?",
                "question_text": "Which letter says /b/?", "options": ["b", "d", "p"], "answer": "b",
                "question_sound": true }
            ]
          }
        ]
      },
      {
        "title": "First words", "icon": "book-open", "description": "Read short words.",
        "overview_markdown": "### Read it", "level": 2,
        "lessons": [
          {
            "title": "Cat and dog", "icon": "paw", "description": "Match words to pictures", "game_type": "match_up",
            "questions": [
              { "content_type": "match", "question_prompt": "Match",
                "match_pairs": [ { "left": "cat", "right": "🐱" }, { "left": "dog", "right": "🐶" } ] }
            ]
          }
        ]
      }
    ]
  },
  {
    "name": "English: Everyday",
    "icon": "comments",
    "description": "Talk about yourself and your day.",
    "placement": { "scale": "English", "min_level": 3, "max_level": 4 },
    "topics": [
      { "title": "My name is…", "icon": "id-card", "description": "Introduce yourself.",
        "overview_markdown": "### Hello", "level": 3, "lessons": [ "…" ] },
      { "title": "At the shop", "icon": "basket-shopping", "description": "Ask for things.",
        "overview_markdown": "### Shopping", "level": 4, "lessons": [ "…" ] }
    ]
  },
  {
    "name": "Map Test",
    "questions": [
      { "subject_name": "English", "level": 1, "content_type": "multiple_choice",
        "question_prompt": "Tap the cat", "question_text": "Tap the cat", "options": ["🐱", "🐶", "🐟"],
        "answer": "🐱", "question_sound": true },
      { "subject_name": "English", "level": 2, "content_type": "multiple_choice",
        "question_prompt": "Which word is cat?", "question_text": "Which word is cat?",
        "options": ["cat", "cot", "cut"], "answer": "cat", "question_sound": true },
      { "subject_name": "English", "level": 3, "content_type": "multiple_choice",
        "question_prompt": "Choose the greeting", "question_text": "Which one do you say when you meet someone?",
        "options": ["Hello", "Table", "Blue"], "answer": "Hello" },
      { "subject_name": "English", "level": 4, "content_type": "open_answer",
        "question_prompt": "Finish the sentence", "question_text": "I would like two ___, please. (apple)",
        "answer": "apples" }
    ]
  }
]
```

This worked example is shortened. A real file needs many more placement
questions per level (see below), and real lessons in place of `"…"`.

### Courses

- `name` (unique, at most 50 characters), `icon`, `description`, `topics`.
- `placement` (optional) puts the course on a scale: `scale` is the name the
  placement questions use as `subject_name`, and `min_level` / `max_level`
  are the inclusive band of scale levels it serves.
- **Name courses with "English" in the name** (for example "English: First
  Steps"). Staff worksheet suggestions (`get_recommended_worksheets`) match a
  learner's course to a worksheet's subject by name, and any name containing
  "english", "grammar", "language" or "greek" counts as language, like the
  worksheet library. A name such as "Phonics" matches only worksheets whose
  subject is literally "Phonics". Topic titles then rank worksheets by shared
  words of 3 letters or more, so a topic called "Greetings" finds a worksheet
  whose title or topic says "greetings".

### Topics

- `title` (unique within its course, at most 150 characters), `icon`,
  `description`, `overview_markdown`, `level`, `lessons`.
- In a course **with a band**, `level` is a level on the placement scale, is
  required, and must lie inside the band. Several topics may share one
  level, and they run in file order. A learner placed at level L starts at the
  first topic of the highest topic level at or below L.
- In a course **without a band**, `level` ranks topics inside the course
  (1 = easiest). It defaults to the topic's position in the list.

### Lessons

- `title` (unique within its topic, at most 150 characters), `icon`,
  `description`, `questions`, optional `overview_markdown`.
- `game_type`: `null` (quiz), `rocket`, `word_storm`, `match_up`,
  `garden_grow`, `potion_workshop`. Anything else fails the import.

### Placement questions (`"Map Test"`)

- `subject_name` (the scale), `level` (whole number from 1), `content_type`,
  `question_prompt`, `question_text`, `answer`, and `options` for multiple
  choice. `question_sound: true` asks for audio of `question_text`.
- `audio_only: true` makes a listening question: the learner gets a big
  speaker and the options but none of the question's words (`question_text`
  is what the voice says, e.g. "Select the word book."). It needs
  `question_sound: true` and `multiple_choice`. Every level 1 and 2 question
  is one, since those learners cannot read the prompt; higher levels mix them
  in as listening checks. If its audio cannot be played,
  the page shows the written question instead, so a learner is never left
  with a question they can neither hear nor read.
- An emoji inside `question_text` is drawn large on the placement page.
- Only **`multiple_choice`** and **`open_answer`** work here: the placement
  page shows nothing else. Both are graded by exact match on `answer`,
  ignoring case and outer spaces. The learner never sees right or wrong.
- A `subject_name` that is never a course's `name` becomes a hidden
  placement-only subject (`map_test_only`). If it *is* a course's name, that
  course is its own scale, which is the older shape. It must then have no
  banded courses on it, and its topics' `level`s line up with its placement
  levels.

### How many placement questions per level

The test asks every learner 10 to 20 questions (`MIN_QUESTIONS`,
`MAX_QUESTIONS` in `routes/api/map_test.py`). Between them, the courses
cover a few placement levels, and the test probes around a learner's level
until it has asked 10. So each level needs a deep pool. A simulation over
20,000 learners shows what the test draws:

| Level | Questions to write | Why |
|---|---|---|
| 1 | **12 or more** | A learner who knows nothing answers 9 level-1 questions; unsure learners near the floor use up to 10. |
| 2 | **8 or more** | The first question is at level 2; a learner who lands at level 1 or 2 also answers level-2 questions. |
| every higher level | **6 or more** | A learner whose result sits at a level answers about 5 questions there; a level they pass on the way up takes 2. |

- Keep a scale to **10 levels or fewer**. A learner climbs one level per 2
  correct answers, starting at level 2, so a learner who gets everything
  right reaches the top of a 10-level scale in 18 questions. On a 12-level
  scale the 20-question cap stops them first.
- Running short does no harm to the test: when a level runs out, the test
  borrows a question from the level next to it, and when both are dry it
  settles early with fewer than 10 questions. It never loops.

## Question types

What the grader actually distinguishes (`grade` in
`helpers/learning/_validators.py`); the list the importer accepts is `CONTENT_TYPES` in
`helpers/content/_schema.py`:

| `content_type` | Learner does | Required fields |
|---|---|---|
| `multiple_choice`, `text_comprehension_multiple_choice`, `text_comprehension_picture`, `text_comprehension_image_selection` | picks one option | `options`, `answer` (must be one of the options) |
| `text_comprehension_fill_blank` | types into `{input}` in `question_text` | `fill_blank_options` = accepted answers (or `answer`) |
| `text_comprehension_drag_drop` | drags chips into several `{input}` blanks | `fill_blank_options` in blank order, `word_bank` = chips incl. decoys |
| `text_comprehension_word_selection` | taps words in the passage | `word_selection_correct_words` |
| `vocabulary_audio`, `text_comprehension_read_word` | taps words to hear them / reads; always counted correct | `word_bank` |
| `open_answer` | free text | `answer` |
| `match` | pairs left with right (Match Up) | `match_pairs: [{left, right}]` |

Every type but `match` also needs `question_text`. `question_subtext` adds a
second instruction line. **`text_group`** is import-only: it wraps several
questions (never another `text_group`) under one shared `context_text` /
`context_image`, which is copied onto each of them. `question_sound: true`
puts the question text on the spoken list, `option_sound: true` each option
(see "Audio").

## Writing for the games

- Garden Grow, Potion Workshop, Rocket and Word Storm use multiple-choice
  questions only, and show options on seed packets, bottles or bubbles — keep
  options to a word or two. Such a lesson with no multiple-choice question
  fails the import.
- Potion Workshop brews pairs of questions, so 4 or 6 questions per lesson fit
  best; phrase prompts as ingredients ("Add the colour of the sky").
- Match Up takes one `match` question per lesson with 4–8 pairs; a
  `match_up` lesson without one fails the import.
- Write for a reader who may not read yet: short prompts, picture-friendly
  words, audio wherever possible.

## Validation — the import fails loudly

Before writing anything the importer checks the whole file and, on any
problem, writes nothing and lists every problem with where it is
(`English: First Steps > Letter sounds > A, B, C > question 2: unknown
content_type 'fill_gap'`). `flask import-questions` exits 1. It refuses:

- a missing required key, an unknown `content_type` or `game_type`, the
  retired `gamified` flag (use `"game_type": "rocket"`), a `text_group` inside
  a `text_group`, a choice question whose `answer` isn't among its `options`,
  and a type missing its required fields;
- a placement question of a type other than `multiple_choice` /
  `open_answer`, and a scale with a level that has no questions
  (levels must run 1, 2, … with no gap);
- bands that overlap, leave a scale level in no course's band, go past the
  scale's highest level, have `min_level` above `max_level`, or name a scale
  with no placement questions; a banded course with no topics; a topic
  without a level or outside its course's band; and a scale that has
  courses on it but is itself a course.

## How the importer behaves

- **It upserts by natural key.** Subject by name, topic by (title, course),
  lesson by (title, topic), question by (`question_text`, lesson), a `match`
  question by (lesson, prompt), a placement question by (scale, level,
  `question_text`). Renaming any of these creates a second copy, and the old
  one stays until you prune.
- **On re-import only some fields refresh**: a course's band and whether a
  subject is placement-only, a topic's `level`, a lesson's `game_type`, and
  every field of a question or placement question. A course's, topic's or
  lesson's icon, description and overview keep their first-imported values.
- Without `--prune` nothing is ever deleted.
- A second import of an unchanged file writes nothing (a `text_group` keeps
  the group id its questions already share).

## Audio

Audio is a cache in front of ElevenLabs (`helpers/audio_cache.py`). A question
stores no URL: the API points it at `/audio/<md5 of "text:voice">.mp3`
(`audio_url`). A request for that name serves the stored file (the bucket's `audio/`
folder: `instance/bucket/audio/` in dev, GCS in production), or, if it is missing,
generates it, stores it and serves it. The first play takes a couple of
seconds; every later one is a stored file.

`/audio/` is public and generating costs money, so only text on the **spoken
list** can be generated: question text with `question_sound`, options with
`option_sound`, and placement question text with `question_sound`. Any other
name is a 404 that never reaches ElevenLabs. The list is read from the
database, so new content is picked up within seconds of an import. Failed
generations are not retried for a minute, and the web service needs
`ELEVEN_API_KEY`: without it a file that is not yet stored is a 404 and the
page falls back to speech synthesis (or, for a listening question, to its
written words).

The importer never calls ElevenLabs. `flask import-questions --sound`
pre-generates every missing file, so the first learner doesn't wait; it is
optional.

## Retiring old content — `--prune`

`flask import-questions --prune` is a **dry run**. It validates the file and
prints everything in the database that the file no longer contains: courses
with their topic, lesson and question counts, topics, lessons, questions and
placement questions. It also prints what learners would lose. It writes
nothing.

`flask import-questions --prune --apply` imports the file and removes all of
that in one transaction (all or nothing). For each learner it:

- drops removed lessons and topics from `completed_lesson_ids` /
  `completed_topic_ids`. XP already earned is kept, and a new lesson can't
  inherit a removed lesson's "done";
- drops removed scales from `subject_levels`. A learner whose only result was
  on a removed scale becomes *deferred*: the dashboard asks them to take the
  new placement test;
- deletes learning sessions on removed lessons, in-progress quizzes whose
  lesson lost questions, and every placement test in progress if any
  placement question was removed. Those learners restart that activity.

In production every deploy does this: `flask release` takes a forced
backup, prints the plan to the job log, then applies it
([../operations/database.md](../operations/database.md)). So before
deploying a file that renames or drops content, run
`flask import-questions --prune` against a dev database holding the previous
file's content and read the list. Anything you meant to keep that appears
there was renamed; fix the file rather than pruning.

A new table that points at content (a subject, topic, lesson, question or
placement question) needs a line in `plan_prune`.
