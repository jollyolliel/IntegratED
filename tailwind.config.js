/* Design tokens: the single source for every colour, radius and clay
   geometry value in the app.

   - The plugin below publishes them on :root as CSS variables, for
     hand-written CSS (static/css/components, static/css/pages partials, page
     <style> blocks): `border-color: var(--color-card-sky-border)`.
   - `theme.extend` exposes the role colours and radii as utilities:
     `bg-primary`, `text-ink-muted`, `rounded-card`.

   Hand-written CSS never uses a raw hex — the ast-grep rules in lint/ fail it. */

const colors = require("tailwindcss/colors");
const plugin = require("tailwindcss/plugin");

// Palette families in use. Every shade becomes --color-<family>-<shade>.
const PALETTE_FAMILIES = [
  "sky", "green", "emerald", "amber", "yellow", "orange", "rose", "red",
  "pink", "purple", "violet", "indigo", "blue", "gray", "slate",
];

// What a colour is FOR. Components and templates ask for a role, not a shade,
// so re-pointing a role here re-themes everything that uses it.
const ROLES = {
  primary: colors.sky[600],
  "primary-dark": colors.sky[800],
  "primary-light": colors.sky[200],
  "primary-soft": colors.sky[100],
  "primary-tint": colors.sky[50],
  accent: colors.green[600],
  "accent-dark": colors.green[700],
  danger: colors.red[600],
  "danger-dark": colors.red[800],
  surface: colors.white,
  "surface-page": "#f5f7ff",
  "surface-card": "#f8f9ff",
  "ink-heading": colors.indigo[950],
  "ink-navy": "#0c2d48",
  "ink-body": colors.gray[700],
  "ink-muted": colors.gray[500],
  "ink-faint": colors.gray[400],
  line: colors.gray[200],
  // "Happening now" indicator — the pulsing dot on the active learning link.
  live: colors.blue[500],
  // Reward gold — coins, equipped avatar items, the rocket game.
  gold: "#e5b81a",
  // Static card pairs: the shadow is one step PALER than the border — the
  // only signal a card does not respond to a tap (docs/ui-design/visual-language.md).
  "card-sky-border": colors.sky[200],
  "card-sky-shadow": colors.sky[100],
  "card-green-border": colors.emerald[200],
  "card-green-shadow": colors.emerald[100],
  "card-amber-border": colors.amber[200],
  "card-amber-shadow": colors.amber[100],
  "card-rose-border": colors.rose[200],
  "card-rose-shadow": colors.rose[100],
  "card-purple-border": colors.purple[200],
  "card-purple-shadow": colors.purple[100],
  "card-pink-border": colors.pink[200],
  "card-pink-shadow": colors.pink[100],
};

// Clay geometry. Hover/press shadows are derived, never picked:
// hover = offset + lift, press = offset - press (docs/ui-design/visual-language.md).
const GEOMETRY = {
  "--clay-border-width": "2.5px",
  "--clay-border-width-thin": "2px",
  "--clay-offset": "3px",
  "--clay-lift": "1.5px",
  "--clay-press": "2px",
  "--clay-offset-sm": "2px",
  "--clay-lift-sm": "1px",
  "--clay-press-sm": "1px",
  "--clay-static-offset": "4px",
  "--clay-modal-offset": "6px",
  "--radius-input": "12px",
  "--radius-btn": "14px",
  "--radius-card": "20px",
  "--radius-pill": "999px",
};

// "#0284c7" -> "2 132 199", for `rgb(var(--color-primary-rgb) / 0.18)` —
// alpha on a token without color-mix(), which older phones lack.
function rgbChannels(hex) {
  const digits = hex.slice(1);
  const full = digits.length === 3 ? [...digits].map((d) => d + d).join("") : digits;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)).join(" ");
}

function rootVariables() {
  const vars = {};
  for (const family of PALETTE_FAMILIES) {
    for (const [shade, hex] of Object.entries(colors[family])) {
      vars[`--color-${family}-${shade}`] = hex;
    }
  }
  for (const [role, hex] of Object.entries(ROLES)) {
    vars[`--color-${role}`] = hex;
    vars[`--color-${role}-rgb`] = rgbChannels(hex);
  }
  return { ...vars, ...GEOMETRY };
}

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./templates/**/*.jx",
    "./static/**/*.js",
    // Literal icon-size classes the Icon helper emits.
    "./helpers/clay_primitives.py",
  ],
  theme: {
    extend: {
      colors: ROLES,
      borderRadius: {
        input: GEOMETRY["--radius-input"],
        btn: GEOMETRY["--radius-btn"],
        card: GEOMETRY["--radius-card"],
      },
    },
  },
  plugins: [
    plugin(({ addBase }) => {
      addBase({ ":root": rootVariables() });
    }),
  ],
};
