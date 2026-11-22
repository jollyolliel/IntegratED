# Learning — start here

Read this before working on anything in the learner's learning experience:
the survey, the placement test, the learning path, the quiz, the minigames,
XP and levels, the avatar, or the learning content itself.

The model in one breath: content is **Subject → Topic → Lesson → Question**,
and learners see a subject as a course. A lesson is either a quiz or one
minigame (`Lesson.game_type`). A learner takes an adaptive placement test
once and gets a suggested course and starting topic. Courses sit in bands on a
shared placement scale. Then they work through lessons. Finishing a lesson
the first time earns XP, which raises their level and unlocks avatar items.

## Which file for which task

| You are… | Read |
|---|---|
| Changing onboarding, the placement test, recommendations, the learning path, progress, XP, levels or the avatar | [learner-journey.md](learner-journey.md) |
| Changing the quiz or a minigame, or adding a new game | [lesson-activities.md](lesson-activities.md) |
| Editing `questions.json`, adding question types, importing or pruning content | [content.md](content.md) |
| Designing any screen a learner sees | [../ui-design/designing-for-learners.md](../ui-design/designing-for-learners.md) |

Where the code is: `routes/learner/` (pages), `routes/api/` (the JSON the
placement test, quiz and games call), `helpers/learning/` (placement,
completion, games registry, recommendations, answer validators),
`helpers/gamification/` (XP, levels, Face System), `models_learning.py`,
`templates/pages/learner/`.

Words used here — Course, Placement scale, Band, Placement Test, Settle,
Deferred, Lesson, Grain, Super bloom, Golden potion, Recipe, Face System — are
defined in
[../CONTEXT.md](../CONTEXT.md).
