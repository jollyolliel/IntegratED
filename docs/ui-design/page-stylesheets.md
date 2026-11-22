# Page stylesheets — `static/css/pages/`

A page names the stylesheets it needs in `<Page styles="admin matching">`;
each is linked after the site CSS. A name with no file raises in tests. Which
layer CSS belongs in at all: [styling-system.md](styling-system.md).

Use this table to find the partial that already covers a page before adding
CSS, and read its row's traps before editing it.

| File | Linked by | Holds, and its traps |
|---|---|---|
| `public.css` | index, about, schools, articles | What the public pages share: `.reveal` (its observer, with `[data-cta]` clicks and `[data-counter]` counters, is in `components/shell/theme.jx`), the type scale `.pub-display` / `.pub-h2` / `.pub-lead`, the dotted `.pub-dots` background, and the article reading list (`<ArticleRow>`). |
| `landing.css` | index and `page_components/landing/` | Every `lp-*` rule of the landing page: hero doors, mission, sticker board, session timeline, the lesson demo, games, community postcards, get involved. |
| `auth.css` | login, register, error | Auth card, register role cards, the oversized invite-code box `.code-input` — a large *static* panel: its 3px shadow never moves; a new state changes border and shadow colours together (focus and error use the solid border colour for the shadow). |
| `donations.css` | donations, donation success | Sky hero, donation steps, pickers: each school is a `<Card clickable>` whose chosen state re-points `--qa-border`/`--qa-hover`; `.amount-btn` is driven by `--pick-*` variables — restyle by re-pointing the variables, never `border-color`/`box-shadow` directly, so border and shadow can't drift apart. Success-page confetti. |
| `survey.css` | learner + volunteer survey, map intro | Survey card and bigger-than-global inputs for small fingers. |
| `learning-nav.css` | subjects, topics, `<TopicCard>`, lesson overview, map test, worksheet view, article detail | Topic/lesson cards: `.topic-card-*` modifiers change **colour only**, and each modifier defines both `:hover` and `:active` (a modifier with only `:hover` wins while the mouse is held and kills the press). Game badges `.game-badge-<type>` (one per game type). Overview sidebar `.lesson-row` + `.is-done`/`.is-current`, and `.progress-ticks` — one tick per lesson. Map-test-only bits (`.audio-clay`, `.map-textarea`). |
| `games.css` | every game and the quiz (via `<GamePage>`) | The quiz's mechanics plus what the games share (`.game-hint-toast`, `.game-stat-pill`, `.progress-track`/`.progress-fill`). The quiz progress strip `.quiz-progress-*` sticks at `top: 65px` — the navbar's height — not `top-0`, and condenses via an IntersectionObserver sentinel, never a `scrollY` threshold (the bar's own height change would feed back and make it flicker). |
| `game-<slug>.css` | one game each (`<GamePage styles="game-<slug>">`): rocket, word-storm, match-up, garden-grow, potion-workshop | That game's `.rk-*`/`.ws-*`/`.mu-*`/`.gg-*`/`.pw-*` rules. Each scene's backdrop is decoration with no ids or JS hooks (so a `/live` session can swap it); the layer the script draws sits between its back and front SVGs. Answer buttons are the global clickable card. |
| `dashboard.css` | learner dashboard | XP/level tabs, the wardrobe (character room, folder tabs, item tiles). |
| `admin.css` | settings, staff people/attendance/detail pages, admin DB tools, worksheet assigner, library and assigned tracker | Staff back-office. Attendance `.att-*`: one dense sheet whose rows are date separators, volunteer group rows (tied to their learners by `data-group-key`) or learners; a volunteer row counts in tallies and responds to bulk marks; editing happens in the row; hide rows with `.att-hidden`, never the bare `hidden` attribute. People map `.people-*`: two columns with pairings drawn as SVG lines behind the cards; never transition `transform` on `.people-item` (each redraw resets it to measure), anything that changes a card's height must trigger a redraw, and `.people-item[hidden]` needs its own rule. Similar-looking widgets keep distinct names on purpose (`.avatar-circle-lg`/`-sm`, `.ws-card`/`.pair-ws-card`). |
| `matching.css` | teacher people page | The two Auto-Match modals (`.mp-*`), on the 6px modal elevation. The importance bars fill from `data-level` (level 0 = off), not `:has(:checked)`. Tooltips are positioned `fixed` from JS because the modal body clips. |
| `legal.css` | terms, privacy (via `<LegalPage>`) | `.legal-prose` typography. |

A new partial gets a row here.
