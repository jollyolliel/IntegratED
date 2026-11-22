# Teacher AI assistant

A teacher-only chat panel on every page. It answers questions by calling
tools against the database and **proposes** changes into a review list; a
teacher applies them. Nothing is written without an explicit human apply.

Module docstrings cover the mechanics: `helpers/ai/__init__.py` (layout),
`scope.py`, `staging.py`, `loop.py`, `tools/__init__.py`, and the
`AssistantChange` model. ADR 0007 (provider seam) and ADR 0008 (reads vs
writes) carry the reasoning.

## The big idea: reads are derived, writes are curated

- **Reads** are scoped automatically: `scope.py` walks the foreign-key graph
  out from the teacher to decide which rows of which model their conversation
  may see. A model with no path to a teacher is invisible until someone
  classifies it — **failing closed is the point**. Generic read tools
  (list/describe/query/count/aggregate) need no per-model code, so a new
  model with a `teacher_id` is queryable as soon as it's mapped.
- **Writes** are hand-written, one reviewed function per operation. A write
  tool never mutates: it validates against the database now and records an
  `AssistantChange` (field diff + the original tool call). Applying replays
  the tool call through `helpers/teacher_ops` — the same functions the teacher
  routes use — so a change can't skip a rule the UI would enforce. A row that
  changed since staging comes back **stale** instead of being overwritten.
  Reads can afford automation because the worst case is a useless answer; a
  legal-but-wrong write still looks fine in review.
- **Vendor-neutral**: everything above `helpers/ai/provider.py` is unaware of
  Gemini. Swapping models is one new provider file plus one registry entry.
  The provider's own rendering of each turn is replayed verbatim
  (`ProviderReply.provider_turn`), because reasoning models sign their tool
  calls and reject a reconstructed turn.

## Extending

**A read tool**: an `@ai_tool` function in any module under
`helpers/ai/tools/` (auto-imported). Resolve rows through the scope or
`teacher_ops._owned`; raise `ValueError` / `LookupError` / `PermissionError`
for mistakes the model can correct (they're fed back to it as the tool's
result); return a `TypedDict`. Domain tools should reach the same answer the
teacher's own screens would — wrap the existing helper rather than
re-deriving.

**A write**:
1. A `validate_x` + `x` pair in `helpers/teacher_ops/`, used by the teacher
   route too.
2. A `WriteOp` in `staging.py`. Each `DiffField.normalize` must match how
   `build` produced `before` — they're compared literally, and a mismatch
   makes every change read as stale.
3. An `@ai_tool(writes=True)` in `tools/writes.py` that stages it.
4. If destructive, add it to the panel's `DESTRUCTIVE` list
   (`assistant_panel.jx`) so applying asks for confirmation.

## Traps

- **Edited review fields arrive as strings** from the panel and are merged
  into the tool arguments as-is; every `validate_*` coerces its own types.
- **Staging checks the database, not other pending changes**: two staged
  matches into one free slot both stage; the second fails on apply.
- **Staged creates are never stale** (no `before`), so applying an old
  attendance proposal overwrites a record logged by hand since.
- **The generic tools see volunteers' mirrored attendance rows**; anything
  counting sessions or hours filters to learner rows (per-person attendance).
- **Filters are a constrained grammar**, never SQL; every read tool applies
  the scope clause *and* the filters — a dropped filter raises nothing, it
  returns a plausible larger number the model then states as fact.
- **SSE response** (`POST /assistant/message`): read every request-bound value
  before returning the generator; every chunk must be `bytes` (the dev server
  dies on `str`, and the test client hides it); a streamed response is lazy, so
  a test must read the body; set `Cache-Control: no-store` on it explicitly.
- **Timing**: the turn deadline is checked before each model call, and one
  call — its retries and the backup-model fallback included — is held to
  `REQUEST_TIMEOUT_SECONDS` (`helpers/ai/gemini.py`), so a turn's worst case
  is the deadline plus one call, inside gunicorn's 60s timeout. New retries
  spend from that same budget.
- **Pending changes apply in `id` order** — staging order. `seq` restarts at
  0 every turn, so sorting by it interleaves turns.
- **Model names**: a retired Gemini model name returns 404 — a config error,
  not an outage. `GET /v1beta/models` lists what the key can reach. Settings:
  `GEMINI_AISTUDIO_API_KEY` (secret, optional in `settings.py`, so a missing key
  is a message in the panel, not a boot failure), `ASSISTANT_PROVIDER`,
  `ASSISTANT_MODEL`, `ASSISTANT_MODEL_FALLBACK`.
- The model's answer arrives in one piece; the tool **steps** are what
  stream. Don't fake a typing effect.
- Step labels come from Python in English, outside translation.

## The panel

`templates/components/assistant_panel.jx`, rendered by the header after its
own script so `showToast` / `confirmDelete` exist. It docks rather than
overlays: opening adds `.assist-docked` to `<html>`, which pads the page so
content shrinks beside it (it covers the screen below 900px). Its button sits
outside the navbar's overflow group so it never folds into "More". Answers
render through the panel's own markdown renderer, which escapes first — model
output can never inject markup. Strings come from an `ASSIST_T` object built
with `t()`.

## Tests

`tests/web/test_assistant.py` (routes) and `tests/unit/test_ai*.py` (loop,
scope, staging, registry, tools). `use_fake_provider` from
`tests/support/ai.py` replays scripted model replies with no network.
