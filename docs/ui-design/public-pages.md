# Public pages

The landing page (`pages/index.jx`), about, schools, articles and donations.
Visitors here are prospective volunteers, schools, donors and partners — not
customers, and not yet signed in.

## Direction

- **People and mission first.** IntegratED is a youth-to-youth charity
  programme: school students tutoring young refugees. Lead with the people,
  the languages, a session together, and how to get involved. It is not a
  product pitch — no feature checklists, XP chips or "sign up now" funnels;
  calls to action are *get involved*: volunteer, support, learn with us.
- **A reference site is a mood, never a layout.** Borrow a feeling (playful
  illustration, motion) and invent sections that only make sense for this
  programme.
- **Big.** Fluid `clamp()` headings, wide containers, large illustrations —
  these pages are often viewed on a wide screen and should feel generous.
- **Real art.** Illustrations and photos from `static/svg/` and `static/img/`
  in the project's own illustration style.

## How they're built

- Full-bleed: each writes its own `<main>` inside `<Page>` and composes
  sections from its own CSS (the landing page's `lp-*` rules in `landing.css`;
  About and Schools in their heads), the shared `public` sheet (reveal, type
  scale, dotted paper, article rows) and, for donations, `donations.css`.
- CTA clicks are tracked from `data-cta` / `data-cta-location` on any page; the
  listener is in the shell (`components/shell/theme.jx`).
- Motion is richer than in the app — scroll reveals, gently bobbing art,
  confetti on a successful donation — and every animation sits inside a full
  `prefers-reduced-motion` block.
- The landing page's "try a question" demo uses the real `<McOptions>`
  component, so the demo is the product.
- Copy goes through `t()` like everywhere else; articles, team members and
  site text come from the CMS models instead (seeded from `seed/seed.toml`'s
  `[[team_members]]` and `[site_content]` in dev), as authored content outside translation.
- Routes listed in `PUBLIC_CACHEABLE_ENDPOINTS` (`main.py`) are cached for 60
  seconds; a new public page that is the same for every visitor joins that
  set.
