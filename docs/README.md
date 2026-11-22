# IntegratED docs

Start with **[system-design.md](system-design.md)** for the whole picture and
**[CONTEXT.md](CONTEXT.md)** for the vocabulary. **[PRODUCT.md](PRODUCT.md)** is
the product brief design work starts from: users, purpose, principles. Then each folder opens with a
README that says which file to read for which task:

- [ui-design/](ui-design/README.md) — building and designing anything a user sees
- [backend/](backend/README.md) — routes, access control, data model, shared services
- [learning/](learning/README.md) — learner journey, quiz and minigames, content
- [features/](features/README.md) — matching, worksheets, AI assistant
- [operations/](operations/README.md) — deployment, CI and releases, production database
- [development/](development/README.md) — running, testing, Python conventions, translations
- [adr/](adr/) — architecture decision records

## What belongs in these docs

The code is the source of truth. A doc earns its place by saying what the
code can't say about itself:

- an idea that spans several files (the clickable/static rule, who owns a
  roster, what every minigame has in common);
- an invariant that breaks silently, or a trap invisible from the function
  you're in;
- the *why* behind a design, when it stops someone undoing it;
- a decision rule for choosing between similar things.

Anything a single `Read` or `grep` would show — field lists, every route,
every class — stays in the code, documented on itself. A doc that restates
code costs every reader and goes stale unnoticed.

## Keeping them true

- A change that makes a sentence here false fixes that sentence in the same
  change. Edit in place; never append a second paragraph about the same thing.
- Present tense only — no dates, no "used to", no changelog. Git holds history.
  (The end-of-turn hook flags dated lines anywhere under `docs/` except `adr/`.)
- One home per fact; elsewhere, link to it.
- New behaviour that no doc claimed needs no doc unless it fits the list above.
  Prefer a comment on the code it constrains.
- A file per *task an agent or person would come for*, not per class: big
  enough to be worth opening, small enough to read whole. A folder README
  routes to its files; keep its table current when adding one.
- Why a hard-to-reverse decision went one way → an ADR in `adr/`
  (`NNNN-slug.md`, status line at the end). Words and their meanings →
  `CONTEXT.md`.
