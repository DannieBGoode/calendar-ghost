# Calendar Ghost: product name and visual identity

## Intent

The Web UI is calm and well structured but has no identity: a stock calendar-check icon, the
generic name "Calendar Sync", an unloaded font that falls back to each device's system face, and
inconsistent heading levels. This change gives the product a name and a calm, distinctive identity
without changing how it behaves or how an existing installation upgrades.

**Decided with the administrator:** the product is renamed **Calendar Ghost**. The ghost is the
brand metaphor for Busy-Only Projection — a silhouette of the source event with its details left
behind. The personality is the *calm ghost*: the ghost appears in the mark, the sign-in screen, the
loading state, and empty states, never in routine controls or incident copy.

**Success:** every user-facing surface says Calendar Ghost; the app looks like one considered
product in light, dark, and mobile; contrast meets WCAG 2.2 AA; an installation upgraded in place
keeps its database, environment, and appearance preference.

## 1. Name

- Display name: **Calendar Ghost**. Tagline: *"Your busy time, everywhere it needs to be."*
- Renamed: app shell and wordmark, document titles (`Rules – Calendar Ghost`), sign-in and setup,
  footer, loading and fatal states, Activity explanations and incident copy in `web/src/lib/`,
  incident email subject and body, the FastAPI title, `index.html` metadata, `README.md`,
  `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`, `CONTEXT.md` (the product's name only),
  `docs/`, `AGENTS.md` prose, the package docstring, and `pyproject.toml`'s description. A
  `CHANGELOG.md` entry records the rename.
- Not renamed: the `calendar_sync` Python package, `CALENDAR_SYNC_*` environment variables, the
  Docker image, Compose service and volume names, the database filename, the
  `calendar-sync-theme` localStorage key, the npm package name, and the repository. Historical
  CHANGELOG entries and ADRs keep the name they were written under.
- "Ghost" is brand language only. Labels, explanations, and incidents keep the `CONTEXT.md`
  glossary ("projection", "Directional Sync Rule"); empty-state copy may use the metaphor once
  ("No ghosts yet") beside the glossary term.

## 2. Mark

- A rounded calendar page with two binder tabs; its bottom edge is a three-scallop ghost hem; two
  dot eyes sit in the upper body. Drawn on a 32-unit grid with strokes and fills that stay legible
  at 16px.
- `web/src/components/ghost-mark.tsx` renders it as inline SVG using `currentColor` plus a
  `--brand-glow` fill, decorative (`aria-hidden`) wherever the name is beside it.
- Uses: top-bar lockup (mark + "Calendar Ghost"), large on the auth intro panel, empty states,
  and the startup loading screen.
- `web/public/favicon.svg` is redrawn as the same mark with an embedded
  `prefers-color-scheme` style so it suits light and dark browser chrome.

## 3. Palette: "Twilight"

Lavender-tinted neutrals (hue 280–285) replace the cobalt-tinted ones; **Lantern Indigo** replaces
Status Cobalt as the single action and focus color. Semantic roles do not change.

| Token | Light | Dark |
|---|---|---|
| `--background` Mist / Night | `oklch(0.99 0.004 285)` | `oklch(0.17 0.022 280)` |
| `--surface` | `oklch(0.972 0.008 285)` | `oklch(0.21 0.026 280)` |
| `--muted` | `oklch(0.95 0.012 285)` | `oklch(0.26 0.03 280)` |
| `--foreground` Ink / Ghost White | `oklch(0.22 0.045 280)` | `oklch(0.95 0.012 285)` |
| `--muted-foreground` | `oklch(0.45 0.035 280)` | `oklch(0.75 0.025 285)` |
| `--primary` Lantern Indigo | `oklch(0.47 0.15 278)` | `oklch(0.74 0.12 278)` |
| `--primary-foreground` | `oklch(1 0 0)` | `oklch(0.17 0.03 280)` |
| `--primary-soft` | `oklch(0.94 0.03 280)` | `oklch(0.28 0.06 278)` |
| `--border` | `oklch(0.90 0.014 285)` | `oklch(0.34 0.03 280)` |
| `--input` | `oklch(0.65 0.02 285)` | `oklch(0.52 0.03 280)` |
| `--brand-glow` (mark only) | `oklch(0.97 0.02 285)` | `oklch(0.93 0.03 285)` |

Moss (healthy), ochre (attention), and red (destructive) keep their hues and current values,
re-checked against the new canvases. The Quiet Indicator Rule (≤10% of a screen) and the Status
Is Not Just Color Rule stay. `theme-color` metadata follows the new canvases.

## 4. Typography

- Bundled with `@fontsource-variable/fraunces` and `@fontsource-variable/figtree` (latin subset,
  self-hosted woff2, `font-display: swap`), so an offline Raspberry Pi renders them.
- **Fraunces** (SOFT axis 100, opsz auto, weight 560) for page titles and the auth headline only.
- **Figtree** for all other text and every control.
- Hierarchy: page title 2rem Fraunces → section title 1rem Figtree 650 → row title 1rem Figtree
  550 → body 1rem 400 → labels 0.875rem 600 → metadata 0.8125rem. Settings and Rule Details
  section and row headings are aligned to these levels.

## 5. Screen changes

- **Auth (setup and sign-in):** the intro half becomes a twilight panel (Night canvas in both
  appearances) with the large mark, the name, the tagline, the headline, and setup's privacy
  points; the form side is unchanged in behavior.
- **Top bar:** the new lockup replaces the stock icon.
- **Settings:** the "not configured" notice uses attention ochre instead of destructive red, as
  DESIGN.md reserves red for destructive actions and validation errors.
- **Empty states:** no rules and no Activity show the mark and one sentence.
- **Startup loading:** the mark with a slow opacity breath, static under `prefers-reduced-motion`.
- **Footer:** "Calendar Ghost · v{version} · Runs on this device · API documentation", with the
  version read from `web/package.json` at build time.

Out of scope: per-calendar colors (the app does not store provider calendar colors yet), layout
restructuring, and any behavior or API change.

## 6. Verification

- Update tests that assert the old name (web lib tests, `tests/adapters/test_api.py`), add an
  assertion for the incident email subject, and extend contrast tests to the new tokens.
- Run both quality gates; rebuild and commit `src/calendar_sync/interfaces/api/static/`.
- Before/after screenshots of auth, Overview, Rules, Rule Details, Activity, and Settings in light,
  dark, and 390px mobile via `scripts/dev_preview.py`.
