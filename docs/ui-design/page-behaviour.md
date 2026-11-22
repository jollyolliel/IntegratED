# Page behaviour — the shared JavaScript contracts

`components/shell/header.jx` ships the app's global JavaScript on every page
that has a header: AJAX forms, the confirm modal, toasts, paged-table swaps and
the navbar. Pages lean on these instead of writing their own. This file is the
contract between a page, that script, and the route behind it.

## Load order

`window.showToast` exists as soon as the header has parsed.
`window.confirmDelete` and `window.bindDynamicForms` are defined **inside the
header's `DOMContentLoaded` handler**. A page script that calls them while the
page is still parsing — or from a `DOMContentLoaded` listener registered in
`<Page head>`, which runs first — throws, and the rest of that page's init
dies with it. Run page init from a `DOMContentLoaded` listener in the page
body (the header's registers first, so it wins), or from a user event.

## AJAX forms — same-page actions

A POST that should not leave the page (delete a row, toggle a flag, save a
setting) is a normal form with `class="js-ajax-form"`:

```html
<form method="POST" action="{{ url_for('administrator.delete_user', user_id=u.id) }}"
      class="inline js-ajax-form" data-remove-selector="tr"
      data-confirm="{{ t('confirm.delete_user_id', id=u.id) }}">
  <Button variant="danger" flat type="submit">{{ t('admin.users.delete') }}</Button>
</form>
```

- The header intercepts the submit, sends it with
  `X-Requested-With: XMLHttpRequest`, and disables the submit button while in
  flight.
- **The route keeps both branches:** `if wants_json(): return
  jsonify(success=…, message=…)`, else `flash(…)` + redirect. The form must
  still work with JavaScript off.
- The response must carry a truthy **`success`** — a route answering with
  `{status: "success"}` is not understood by this handler.
- On success: `message` shows as a toast, `data-remove-selector` removes the
  closest matching ancestor, and the form fires a bubbling `ajaxform:success`
  event whose `detail` is the JSON — listen for it to update the page.
- `data-skip-ajax` on a submit button opts that button out.
- An `abort(4xx)` inside the route comes back as JSON (`error`, `message`)
  because the main error handler keys on the same header.

**`showToast` inserts its message as HTML.** A `message` built from user data
(a worksheet title, a school name) must be escaped before it leaves the
server, or it is an injection point.

## Confirming destructive actions

- Form: put `data-confirm="<translated message>"` on the `<form>`. The header
  intercepts the submit button's **click** (not the form's `submit` event —
  re-submitting from inside a cancelled submit is a no-op), shows the modal,
  and submits on confirm. Works together with `js-ajax-form`.
- Script: `if (!(await window.confirmDelete(message))) return;`
- Messages live under the `confirm.*` translation keys.
- The modal offers a per-tab "don't ask again" (sessionStorage).

## Toasts

`flash(message, "success" | "error" | "warning" | "info")` from Python;
the header replays queued flashes as toasts on load.
`window.showToast(message, type)` from JavaScript. Flash text and JSON
messages are written in English in Python today — wording a user must
understand belongs in the template through `t()` instead.

## Tables: page, preview, or load more

Every list that can outgrow a screen is bounded. Pick by surface:

| Surface | Control |
|---|---|
| The table *is* the page (history, admin lists, DB editor) | numbered pages — `<Pagination>` |
| The table is one card on a page about something else | a preview of the newest rows + a flat sky `<Button>` to the full paged page, naming the total |
| A grid of cards (worksheet library) | "Load more", server-side filtered |

**Paging contract:**

- Page in the **route**: `clamp_page(total, page_size)` from `helpers/utils.py`
  turns any `?page=` into a valid page; the query uses `.offset()/.limit()`.
  Page sizes are module constants.
- The table, its pager and the "page X of Y" line live in a results component
  (`templates/page_components/<role>/<name>_results.jx`) whose root is
  `<div data-swap-region>`. The full page places that component; the route
  returns **only** the component when `wants_fragment()` is true. One source
  of markup, so the fragment and the page can't drift.
- Clicking a pager link inside a swap region fetches it with `X-Fragment: 1`,
  swaps the region and rewrites the URL; on a non-OK or redirected response it
  falls back to a real navigation (so an expired session lands on login).
- Everything inside a region is replaced on each hop: bind its events by
  **delegation on `document`**, and expect no `<script>` inside the fragment
  to run.
- Totals and averages shown beside a table come from their own aggregate
  query, never from summing the current page's rows.
- `<Pagination args=…>` must carry every filter the page uses, or paging drops
  them. Two pagers on one page need different `key`s, and each pager's `args`
  carries the others' current pages (a test fails on duplicate keys).
- A page with its own fetch-and-swap loader (attendance history) leaves
  `data-swap-region` off so two handlers don't both fire.

**Load more** (`<WorksheetLibrary>`): search and the subject and level
filters run on the server; a filter change replaces the grid and resets to the
first batch, "Load more" appends. `q`/`subject`/`level` go in the URL, the
batch number never does.

## Form controls

- A single-choice `<select>` is styled from the element itself; its first
  child must be `<button><selectedcontent></selectedcontent></button>` (the jx
  lint reports a missing one) or Chromium falls back to the OS picker.
- A hand-made scroll container gets `class="clay-scroll"`; `<Table>` already
  scrolls itself.

## Navbar

- Each role's links sit in `.nav-links-group` in `header.jx`, as `<NavLink
  variant="bar">` (desktop) plus `<NavLink variant="menu">` (mobile menu) —
  a new link needs both.
- Links that would wrap fold into a "More" menu by measuring each label, so
  long translations are handled. Change the group, never add breakpoint
  hacks.
- The mobile menu, like the assistant panel, opens by toggling `.open`; the
  `hidden` attribute would skip its animation.

## "What's new" popup

Content is English, authored in the bucket's `content/announcements.json`
(the dev sample: `seed/files/content/announcements.json`) and inserted into
the database at deploy (`flask release`; the dev server at startup; an
in-app authoring flow is issue #179) — insert-only, keyed on `uid`, so editing a shipped entry
changes nothing and renaming its `uid` re-shows it to everyone. Fields:
`uid`, `roles` (user types), `layout` (`text_only` | `text_image_side` |
`text_image_top`), `title`, `body`, optional `badge`, `image_url`,
`cta_label` + `cta_url` (one green button), `secondary_label` (dismiss-only).
Only the newest unseen announcement for the user's role shows, on dashboards,
and dismissing it also dismisses every older one (ADR 0003). To add one,
append to the file and restart.
