# Tailwind v3.4 tokens, standalone CLI, ast-grep lint

The clay design system lived as roughly 2,500 raw hex values across the component
CSS, the page partials and template `<style>` blocks, with a dead black/gold
theme in `tailwind.config.js`. Dev loaded the Tailwind Play CDN while prod built
the CSS with npm in Docker, and nothing stopped a template from recolouring or
resizing a clay button with utilities. Changing a brand colour meant a
find-and-replace, and a new page could look almost like the others.

All colours, radii and clay geometry are now tokens in `tailwind.config.js`,
published on `:root` as CSS variables and exposed as role utilities. Components
are variants and sizes only. The CSS is built by the standalone Tailwind CLI
through `pytailwindcss` (`scripts/tailwind.py`) in dev, CI and Docker alike.
The rules are enforced by ast-grep rules in `lint/` (`sgconfig.yml`), which run
in the end-of-turn hook and in the test suite.

**Considered options**

- **Tailwind v4** (`@theme`, native cascade layers) needs Safari 16.4 / Chrome
  111. The learners are refugees on whatever phones they have; v3.4 plus CSS
  variables gives the same single token source without that floor. Revisit when
  analytics show old browsers are gone.
- **shadcn/lint** only reads JSX, Vue and Svelte, and ESLint/Oxlint/stylelint
  plugins need a Node toolchain this Flask repo deliberately does not have
  (no npm/pnpm). ast-grep is a Rust binary installed from PyPI by uv, parses
  HTML with its `<style>` blocks as CSS, and tolerates Jinja. Ruff has no plugin
  API, so it only took the one Python-side check it can express (TID251).

Status: accepted.
