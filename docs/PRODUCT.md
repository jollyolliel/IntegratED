# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

IntegratED is a youth-to-youth (Y2Y) learning programme run from ACS Athens. Five signed-in roles plus the public:

- **Learner** (primary): a young refugee from The Home Project, usually not yet literate in any language, often on a cheap phone, using one of 13 interface languages (Arabic, Farsi and Pashto right-to-left). Sometimes sits with a volunteer tutor, sometimes alone. Job: learn to read and build basic skills through a placement test, a learning path, quizzes and five minigames, earning XP and customising an avatar.
- **Volunteer**: a secondary-school student tutoring one or more learners. Job: see their learners, sessions and worksheets; show up and tutor.
- **Teacher**: school staff running the programme. Job: build the roster, match learners to volunteers, log attendance, assign and print worksheets, and ask an AI assistant for help.
- **School admin**: runs one school's people, settings, donations and attendance.
- **Administrator**: runs every school, all users, site content (CMS) and the database console.
- **Public visitor**: prospective volunteers, schools, donors and partners, not yet signed in. Not customers.

## Product Purpose

Let school students teach young refugees who can't yet read, and let teachers run that programme without it becoming a second job. Success, all four held together:

1. **Learners learn to read**: measurable literacy progress for Home Project learners.
2. **More schools join**: the programme grows beyond ACS Athens. Multi-school support is built in.
3. **Teachers save time**: roster, matching, attendance and worksheets feel effortless.
4. **Volunteers stay engaged**: students keep showing up and feel their tutoring matters.

The experience must be engaging and feel good and premium, never "vibe coded". Design decisions should be data-driven: instrumented, measured, and judged on whether they work.

## Positioning

A learning app built for someone who cannot read the screen, run by teenagers tutoring teenagers and children, with the school's teachers holding the rosters. Meaning is carried by icons, pictures, colour, shape and speech before text. The tutoring pair is human; the software supports it rather than replacing it. On the public side it is a youth-led charity programme, not a product pitch.

## Operating Context

- Learners: phone-first, often low-end devices, in any of 13 languages, with or without a tutor beside them. Read-aloud audio on questions; minigames are calm, with no timers and free retries.
- Teachers: a weekly rhythm. Open the dashboard and claim sign-ups, run Auto-Match and approve pairs, log each session's attendance on one register, assign and print worksheets, and ask the AI assistant, which stages changes for approval and never acts alone.
- Physical sessions: learners and volunteers meet in person. Attendance records each person's own account of the day.
- Infrastructure: one Flask monolith on Google Cloud Run with Neon Postgres. Both scale to zero, so cold starts show a "starting up" page. PostHog (EU) analytics, Stripe donations, Gemini for the assistant, ElevenLabs for speech.

## Capabilities and Constraints

- Server-rendered jx components with Tailwind and plain page JavaScript talking to JSON endpoints. An existing component registry and lint prevent pages from restyling components or using raw colours (`docs/ui-design/`, ADR 0011, 0012).
- Every UI string goes through `t()` with translation keys. Layout uses logical directions for RTL.
- Every new web feature ships with PostHog analytics.
- Learning content: English Grammar and Phonics for Reading subjects, plus an adaptive placement test that recommends a course and starting topic (the bucket's `content/questions.json`).
- Access follows roster ownership (`teacher_id`), not just role.
- Vocabulary is fixed in `docs/CONTEXT.md` (Pair, Roster, Attendance, Stage, Face System, and so on).
- Undecided: no formal accessibility conformance target has been set.

## Brand Commitments

None formal yet. The IntegratED name is the only fixed asset. ACS Athens and The Home Project are the real organisations involved, but no logo usage or co-branding rules have been confirmed.

## Evidence on Hand

- Photos in `static/img/` (`photo-session.jpg`, `photo-reading-together.jpg`, `photo-homework-help.jpg`, `photo-students-collaborating.jpg`, `photo-tablet-pair.jpg`) are **stock**, not programme photos. `acs-athens.jpg` shows the school.
- Learner art: 67 illustrations in `static/svg/` in the project's own style.
- CMS seed content in `seed/seed.toml` under `[[team_members]]` and `[site_content]` (development only). No articles ship; admins publish them.
- Absent: no real programme photos, testimonials, impact statistics, learner outcomes data or partner quotes. Do not fabricate any of them.

## Product Principles

1. **Design for someone who can't read.** Meaning never rides on text alone, and colour is never the only cue. Anything to read can be heard.
2. **Calm, not pressure; suggest, never block.** No timers or lost lives for learners. Progress counts work done. Every topic stays open.
3. **Protect the learners.** Never show identifiable refugee learners. Illustration carries the learner's side of the story.
4. **Premium through craft, proven by data.** It should feel considered and good to use for every role. Instrument it, and judge changes by whether they move the four success goals.
5. **Software serves the human pair.** Tools save teachers time and keep volunteers engaged. The assistant proposes, a person approves.

## Accessibility & Inclusion

- Pre-literate users: icon, picture, colour and shape on every meaningful element, with read-aloud audio for instructions and questions.
- 13 languages including right-to-left Arabic, Farsi and Pashto. Learner screens are tested in Arabic as well as English.
- Screen readers: state is spoken through `sr-only` text, and progress strips are announced once.
- Large touch targets, one question on screen at a time, and phone width first.
- Every animation honours `prefers-reduced-motion`.
