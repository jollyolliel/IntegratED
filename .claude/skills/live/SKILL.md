---
name: live
description: Live variant mode for this app's pages. Use when a message starts with "/live"
  (pasted from the IntegratED Live Chrome extension: new, insert, refine, apply, accept, discard,
  text, note) or when the user asks for N variants or alternatives of an element on a page.
argument-hint: "[new|insert|refine|apply|accept|discard|text|note] …  or  [n] [direction] variants of [element] on [path]"
user-invocable: true
---

# Live: variants in the browser, one pasted message per turn

The IntegratED Live extension (`tools/live-extension/`) copies a message; the user pastes it here.
Each message is a `/live <verb> <session>` line, a fenced `json` payload, and sometimes a note.
The user marks rows in the browser (approve, comment, discard) and queues new elements, then
copies them all at once, so one paste may hold several messages with different verbs. Answer each
paste in one short turn. The extension watches the page and reloads by itself once everything in
the paste has landed, so Claude never signals anything.

Pasting: whether a multi-line paste starting `/live` runs as the slash command or reaches the skill
through this description has not been observed yet. Both paths land here; the first session to see
it should replace this paragraph with what happened.

`uv run scripts/live.py` does every template edit (wrap, refine, accept, discard), each one write
that is validated and atomic. Claude writes only the variants file, in the format in
[format.md](format.md), and the judgment work.

## Speed rules

- One paste, one turn, however many messages it holds. No recap, no plan in chat, no restating
  the brief.
- Read the fewest lines that locate the element. The brief already holds the outerHTML and styles.
- Generate in this thread; subagents start cold and would rebuild context you already hold.
- Never re-render, screenshot or QA variants before the user has picked one.
- The Stop hook lints changed template lines; fix error-level findings in the variants file and
  rerun `refine --keep` or `wrap`, never by editing the wrapped template. The hook sees every
  uncommitted change, so findings inside a session no paste of yours named belong to another chat:
  leave them.

## Whose session is it

A paste makes its sessions yours, whichever chat opened them: the user often starts a session in
one chat and carries on in another. Each message carries the session's `label`, `action`,
`round`, the shown variant's `variantName` and, for `refine` and `apply`, the `history` of prompts
so far. For anything else, `uv run scripts/live.py show <session>` prints where it is (file,
lines), its label, action, round and every variant's name, knobs and whether it has CSS;
`--variant N --knobs '<knobs JSON>'` adds that variant's markup and CSS with the knobs baked in.
Never refuse or ask about a session because this conversation didn't open it.

Each chat may run its own sessions, on the same page or others. Act only on the session ids in
your own pastes; `status` lists everyone's. `live.py` and `add_translation_key.py` take turns
through a lock file, so neither undoes the other's write; a `busy:` error means another chat held
it for 30 s: rerun the command.

## A paste with several messages

Run them in the order they come: the extension puts `accept`, `discard` and `apply` first, then
`refine`, then `new` / `insert`. Closing a session moves the lines below it, so read the lines for
a wrap only after every close in the same template is done; when two wraps land in one template,
wrap the one lower in the file first. Read the shared setup once. Reply with one line per message.
The page reloads only once all of them have landed, so finish them all in this turn.

## Shared setup, once per conversation

For `new`, `insert`, `refine` and `apply` only: read `docs/ui-design/DESIGN.md` and
`docs/PRODUCT.md` (Impeccable's launcher won't find this DESIGN.md on its own).

## `new` / `insert`

1. **Find the source.** Map `page.path` to its route and template (`routes/`,
   `render_template("@pages/…")`), then search that template, and the components it uses, for the
   element's classes or id, using `element.text` to tell repeats apart. Read only the lines needed.
   If the element shares a line with other markup, first move it onto its own lines in a separate
   edit: the script replaces whole lines only.
2. **Look.** If `screenshot` is set, Read the PNG. Otherwise work from `outerHTML`, `styles` and
   the prompt. Take no screenshot of your own.
3. **Plan.** Read [variant-method.md](variant-method.md), then the action's Impeccable reference
   and `craft-floor.md` (paths in the method file). Write the identity-lock sentence for yourself;
   keep it out of chat.
4. **Write** `count` variants to `.live/<session>.jx` per [format.md](format.md), with knobs per
   the method's budget.
5. **Wrap.**
   `uv run scripts/live.py wrap --id <session> --action <action> --file <template> --lines A-B --label "<name>"`
   (insert mode: `--insert-after N` or `--insert-before N`, where N is the anchor element's first
   or last line). `<name>` is two or three words for the element as the user sees it ("Games
   background", "Title squiggle"); with several sessions on a page, the extension gives each its
   own selector row under that name. On a `live:` error, fix the variants file and rerun.
6. **Reply in one line**, e.g. `3 variants on / (hero): Louder heading · Calmer · Split layout.
   The extension will reload.` The user's browser is the preview; checks run once, at accept.

## `refine`

Get the kept variant with `uv run scripts/live.py show <session> --variant <variant>` (the
payload's `variant`; leave out `--knobs`, since the kept variant returns with its knobs at their
defaults). The payload's `knobs` show where the user had nudged it and `history` what earlier
rounds asked for. Then `new` steps 3, 4 and 6 with `prompt` steering the new round, running
`uv run scripts/live.py refine <session> --keep <variant>` in place of wrap. The kept variant
returns as #1; write only the `count` new ones.

## Finishing an element (`apply`, and `accept` with `css: true`)

The page reloads the moment a session's markers leave the template, so do everything the user
would see **before** the closing write:

1. `uv run scripts/live.py show <session> --variant <variant> --knobs '<knobs JSON>'` (omit
   `--knobs` when the payload has none): the markup and CSS with the user's knob values baked in.
2. For `apply`, make the change `prompt` asks for, reading `history` for what came before. It is
   one direct edit to that variant, no new variants; when the prompt is unclear, make the most
   likely reading and say which in the reply.
3. Place any CSS per `docs/ui-design/styling-system.md` ("Where does this CSS go?"): usually the
   page's `{% set head %}<style>…</style>{% endset %}`, or the feature's page stylesheet when
   several pages share it. Rename variant-specific classes to semantic ones, in the CSS and the
   markup alike.
4. Turn new literal strings into `t()` keys (`uv run scripts/add_translation_key.py <section.key>
   "English"`, following the key naming in that template) and tidy arbitrary values into scale
   classes where an exact one exists (`gap-[2.5rem]` → `gap-10`).
5. Write the finished element to `.live/<session>.jx` as one variant (`{# variant name="Final" #}`,
   then the markup: no `<style>`, no knobs, no `var(--p-…)`), then close with
   `uv run scripts/live.py accept <session> --variants .live/<session>.jx`. It prints the `lines`
   the element now fills.
6. Verify and reply as in `accept` steps 3 and 4; for `apply`, say what changed.

## `accept`

With `css: true`, follow "Finishing an element" instead. Otherwise:

1. `uv run scripts/live.py accept <session> <variant> --knobs '<knobs JSON>'` (omit `--knobs`
   when the payload has none). It prints the `lines` the element now fills.
2. In those lines, turn every new literal string into a `t()` key and tidy arbitrary values, as in
   step 4 above. Neither changes what the page shows, so it is safe after the close.
3. **Verify.** `curl` the page: it must return 200 with no literal `{{`, `{%` or `t(` in the body.
   Then **one** Claude in Chrome load at 390 px width as the role that sees the page
   (`/dev/login-as?type=<role>&next=<path>`, with the role prefix: `/learner/map`), checking the console. The user already saw desktop;
   phone width and the console are the gaps. Fix what you find. With several closes on one page,
   verify it once, after the last.
4. Reply in one or two lines: what was kept, where any CSS went, how many keys were added.

## `discard`

`uv run scripts/live.py discard <session>`, then reply `Discarded <label>.`

## `text`

For each edit in `edits`, find where `before` comes from:

- a `t('key')` → `uv run scripts/add_translation_key.py --update key "after"`;
- a literal in a template → edit it in place;
- data (the database, `questions.json`) → leave it and report it.

Reply with the count applied and anything skipped.

## `note`

Page-level direction with no element (Impeccable's "Steer"). Read the screenshot if there is one,
do the work as ordinary design work (with the Impeccable skill when it's a design task), and verify
per CLAUDE.md's "Done means it works". This is the only verb that runs that full loop.

## Started from chat (`/live 3 bolder variants of the hero on /`)

Parse the count (default 3, max 8) and the direction, and map the direction onto an action:

| Words | Action |
|---|---|
| bold, punchier | bolder |
| calmer, softer | quieter |
| simpler | distill |
| refined | polish |
| type, font | typeset |
| colour | colorize |
| arrangement | layout |
| phone, tablet, device | adapt |
| motion | animate |
| playful | delight |
| rule-breaking | overdrive |
| anything else with intent | impeccable, with the words as the prompt |

With no direction at all, ask one question offering that list. Run
`uv run scripts/live.py new-id`, then `new` steps 1–6, and tell the user to open the page: the
extension finds the session on load.

## When a session goes wrong

`uv run scripts/live.py status` lists open sessions and flags broken ones. `discard` restores the
original byte for byte. `tests/unit/test_no_live_leftovers.py` fails while any session is open, so
nothing half-finished gets committed.
