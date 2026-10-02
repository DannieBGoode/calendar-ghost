# Calendar Ghost Brand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product to Calendar Ghost and give the Web UI a calm twilight identity: a ghost mark, bundled Fraunces and Figtree type, the Twilight palette, and the screen fixes in the spec.

**Architecture:** Pure presentation and copy change. Tokens live in `web/src/index.css`; one new `GhostMark` component and one `brand.ts` module carry the identity; copy strings are renamed in place; the backend changes only its email copy and API title. No behavior, API, schema, or configuration change.

**Tech Stack:** React 19, Vite 8, Tailwind 4 with hand-written CSS in `web/src/index.css`, Vitest (node environment, no DOM library; tests read sources with `?raw` or `node:fs`, and React output with `react-dom/server`), `@fontsource-variable/*`, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-calendar-ghost-brand-design.md`

## Global Constraints

- Display name is exactly `Calendar Ghost`; tagline exactly `Your busy time, everywhere it needs to be.`
- Never rename: the `calendar_sync` package, `CALENDAR_SYNC_*` env vars, Docker image/service/volume names, the database filename, the `calendar-sync-theme` localStorage key, the npm package name `calendar-sync-web`, historical CHANGELOG entries, ADRs, or `LICENSE`.
- "Ghost" is brand language only: labels, explanations, and incidents keep `CONTEXT.md` glossary terms.
- Fonts are bundled through npm (`@fontsource-variable/fraunces`, `@fontsource-variable/figtree`); no runtime request to any font CDN.
- Fraunces only for page titles (`h1`) and the auth headline; Figtree for all other text and every control.
- Text contrast ≥ 4.5:1 and non-text (input borders, focus ring, mark eyes) ≥ 3:1, in light and dark.
- Status Cobalt is replaced by Lantern Indigo as the single action/focus color; moss, ochre, red keep their roles and values.
- After any `web/` change the committed build in `src/calendar_sync/interfaces/api/static/` is regenerated (Task 7 does this once for the branch; intermediate commits may leave it stale).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Low-contrast token pairs in either appearance** — every text/surface pair must stay AA after the palette swap. Pinned by `brand-contrast.test.ts` in Task 1.
2. **Offline Raspberry Pi** — fonts must render with no internet; a stray CDN `@import` or `<link>` would silently fall back. Pinned by the "no remote font" test in Task 1.
3. **Upgrade keeps the saved appearance** — renaming the theme storage key would reset every user to Device setting. Pinned by the storage-key test in Task 2.
4. **Old name left in copy** — a missed "Calendar Sync" string in an explanation or incident. Pinned by the old-name guard in Task 4 (web) and the API/notification tests in Task 5.
5. **Reduced motion** — the loading ghost must not animate when the device asks for reduced motion. Pinned by the stylesheet test in Task 2.

---

### Task 1: Twilight tokens, bundled fonts, and heading hierarchy

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (via npm)
- Modify: `web/src/main.tsx:7`
- Modify: `web/src/index.css` (`:root` block lines 3–37, dark block 39–66, and heading rules listed below)
- Modify: `web/index.html` (inline theme script colors and `theme-color` meta)
- Create: `web/src/lib/brand-contrast.test.ts`

**Interfaces:**
- Produces CSS custom properties used by later tasks: `--font-sans`, `--font-display`, `--brand-glow`, `--brand-line`, `--brand-eyes`, `--twilight-canvas`, `--twilight-ink`, `--twilight-muted`, plus the retuned existing tokens.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/brand-contrast.test.ts`:

```ts
import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")
const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8")
const entry = readFileSync(new URL("../main.tsx", import.meta.url), "utf8")

type Tokens = Map<string, string>

function block(selector: RegExp): Tokens {
  const body = stylesheet.match(selector)?.[1]
  if (!body) throw new Error(`No block for ${selector}`)
  return new Map([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]))
}

const light = block(/:root \{([\s\S]*?)\n\}/)
const dark = new Map([...light, ...block(/:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/)])

function resolve(tokens: Tokens, name: string): string {
  const value = tokens.get(name)
  if (!value) throw new Error(`Missing --${name}`)
  const reference = value.match(/^var\(--([\w-]+)\)$/)
  return reference ? resolve(tokens, reference[1]) : value
}

/** WCAG relative luminance of an `oklch(L C H)` value, via OKLab and linear sRGB. */
function luminance(value: string): number {
  const match = value.match(/oklch\(([\d.]+) ([\d.]+) ([\d.]+)/)
  if (!match) throw new Error(`Not oklch: ${value}`)
  const [L, C, h] = match.slice(1).map(Number)
  const a = C * Math.cos((h * Math.PI) / 180)
  const b = C * Math.sin((h * Math.PI) / 180)
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  const clamp = (x: number) => Math.min(1, Math.max(0, x))
  const r = clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
  const g = clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
  const bl = clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)
  return 0.2126 * r + 0.7152 * g + 0.0722 * bl
}

function contrast(tokens: Tokens, fg: string, bg: string): number {
  const [x, y] = [luminance(resolve(tokens, fg)), luminance(resolve(tokens, bg))]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

const TEXT: [string, string][] = [
  ["foreground", "background"],
  ["foreground", "surface"],
  ["muted-foreground", "background"],
  ["muted-foreground", "surface"],
  ["muted-foreground", "muted"],
  ["primary", "background"],
  ["primary-foreground", "primary"],
  ["destructive-foreground", "destructive"],
  ["destructive-soft-foreground", "destructive-soft"],
  ["success-foreground", "success-soft"],
  ["success-foreground", "success-surface"],
  ["warning-foreground", "warning-soft"],
  ["warning-foreground", "warning-surface"],
  ["twilight-ink", "twilight-canvas"],
  ["twilight-muted", "twilight-canvas"],
]
const NON_TEXT: [string, string][] = [
  ["input", "background"],
  ["ring", "background"],
  ["brand-eyes", "brand-glow"],
]

describe.each([
  ["light", light],
  ["dark", dark],
])("%s appearance", (_name, tokens) => {
  it.each(TEXT)("keeps %s on %s at AA text contrast", (fg, bg) => {
    expect(contrast(tokens, fg, bg)).toBeGreaterThanOrEqual(4.5)
  })
  it.each(NON_TEXT)("keeps %s on %s at non-text contrast", (fg, bg) => {
    expect(contrast(tokens, fg, bg)).toBeGreaterThanOrEqual(3)
  })
})

describe("Twilight identity", () => {
  it("uses Lantern Indigo as the action color", () => {
    expect(light.get("primary")).toBe("oklch(0.47 0.15 278)")
    expect(dark.get("primary")).toBe("oklch(0.74 0.12 278)")
  })

  it("bundles both typefaces instead of loading them from the network", () => {
    expect(entry).toContain('import "@fontsource-variable/figtree"')
    expect(entry).toContain('import "@fontsource-variable/fraunces')
    expect(stylesheet).toContain('--font-sans: "Figtree Variable"')
    expect(stylesheet).toContain('--font-display: "Fraunces Variable"')
    for (const source of [stylesheet, html]) {
      expect(source).not.toMatch(/fonts\.(googleapis|gstatic)\.com|@import url\(/)
    }
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test -- brand-contrast`
Expected: FAIL — `Missing --twilight-ink` / `Missing --brand-eyes`, Lantern Indigo assertion, and font assertions.

- [ ] **Step 3: Install the fonts**

Run: `npm --prefix web install --save-exact @fontsource-variable/figtree @fontsource-variable/fraunces`

Then check which Fraunces stylesheet carries the SOFT axis: `ls web/node_modules/@fontsource-variable/fraunces/*.css`. Use `full.css` if present (wght, opsz, SOFT, WONK). Check its latin woff2 size with `ls -l web/node_modules/@fontsource-variable/fraunces/files/*latin-full-normal*`; if it is over 250 KB, use `index.css` instead and drop `font-variation-settings` from Step 6.

- [ ] **Step 4: Import the fonts**

In `web/src/main.tsx`, directly above `import "./index.css"`:

```ts
import "@fontsource-variable/figtree"
import "@fontsource-variable/fraunces/full.css"
```

- [ ] **Step 5: Replace the token blocks**

In `web/src/index.css`, replace line 4 (`font-family: Inter, …`) with `font-family: var(--font-sans);`, and in the `:root` block replace these values (leave every other token unchanged) and add the new ones:

```css
  --font-sans: "Figtree Variable", ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-display: "Fraunces Variable", ui-serif, Georgia, serif;
  --background: oklch(0.99 0.004 285);
  --foreground: oklch(0.22 0.045 280);
  --surface: oklch(0.972 0.008 285);
  --muted: oklch(0.95 0.012 285);
  --muted-foreground: oklch(0.45 0.035 280);
  --primary: oklch(0.47 0.15 278);
  --primary-foreground: oklch(1 0 0);
  --primary-soft: oklch(0.94 0.03 280);
  --border: oklch(0.90 0.014 285);
  --input: oklch(0.65 0.02 285);
  --ring: oklch(0.47 0.15 278);
  --brand-glow: oklch(0.97 0.02 285);
  --brand-line: var(--primary);
  --brand-eyes: var(--primary);
  /* The auth intro panel is twilight in both appearances. */
  --twilight-canvas: oklch(0.2 0.04 280);
  --twilight-ink: oklch(0.95 0.012 285);
  --twilight-muted: oklch(0.80 0.03 285);
  --menu-shadow: 0 12px 32px -12px oklch(0.2 0.04 280 / 0.28);
```

In `:root[data-theme="dark"]` replace:

```css
  --background: oklch(0.17 0.022 280);
  --foreground: oklch(0.95 0.012 285);
  --surface: oklch(0.21 0.026 280);
  --muted: oklch(0.26 0.03 280);
  --muted-foreground: oklch(0.75 0.025 285);
  --primary: oklch(0.74 0.12 278);
  --primary-foreground: oklch(0.17 0.03 280);
  --primary-soft: oklch(0.28 0.06 278);
  --border: oklch(0.34 0.03 280);
  --input: oklch(0.52 0.03 280);
  --ring: oklch(0.74 0.12 278);
  --brand-glow: oklch(0.93 0.03 285);
  --brand-line: oklch(0.93 0.03 285);
  --brand-eyes: oklch(0.2 0.04 280);
```

- [ ] **Step 6: Apply the heading hierarchy**

Add after the `h1, h2, h3 { text-wrap: balance; }` rule:

```css
/* Page titles are the only place the display face appears. */
h1 {
  font-family: var(--font-display);
  font-weight: 560;
  font-variation-settings: "SOFT" 100;
  letter-spacing: -0.015em;
}
```

Remove `letter-spacing: -0.025em;` from `.page-section h1` and `letter-spacing: -0.035em;` from `.auth-intro h1` (the `h1` rule sets it). Then set section and row title weights:

- `.section-heading h2 { font-weight: 700; }` (around line 1266) → `font-weight: 650;`
- `.health-copy h2 { font-weight: 700; }` → `font-weight: 650;`
- Add `font-weight: 550;` to the `.account-empty h3, .account-copy h3, .setting-row h3, …` rule (around line 826) and to a new rule `.setting-row h2 { font-weight: 550; }` placed after it.
- `grep -n "font-weight: 7[05]0" web/src/index.css` and change any remaining heading (`h2`/`h3`) rule to `650`; leave non-heading rules.

- [ ] **Step 7: Update the pre-paint theme colors**

In `web/index.html`: `<meta name="theme-color" content="#ffffff" />` → `content="#fbfbfe"`, and in the inline script `theme === "dark" ? "#0e1217" : "#ffffff"` → `theme === "dark" ? "#0d0e19" : "#fbfbfe"`. Then `grep -rn "0e1217\|#ffffff" web/src` and update the same pair wherever the theme provider sets `theme-color` at runtime.

- [ ] **Step 8: Run tests to verify they pass**

Run: `npm --prefix web run test`
Expected: PASS, including `brand-contrast`, `settings-contrast`, `button-contrast`. If a contrast pair fails, adjust only that token's lightness and update the spec table to match.

- [ ] **Step 9: Commit**

```bash
git add web/package.json web/package-lock.json web/src/main.tsx web/src/index.css web/index.html web/src/lib/brand-contrast.test.ts web/src/components/theme-provider.tsx web/src/lib/theme.ts
git commit -m "feat(web): Twilight palette, bundled Fraunces and Figtree, consistent headings"
```

---

### Task 2: Brand module, ghost mark, favicon, top bar, footer, and loading

**Files:**
- Create: `web/src/lib/brand.ts`, `web/src/lib/brand.test.ts`
- Create: `web/src/components/ghost-mark.tsx`, `web/src/components/ghost-mark.test.tsx`
- Modify: `web/vite.config.ts`, `web/src/vite-env.d.ts`
- Modify: `web/src/App.tsx` (startup loading, fatal state, document title, wordmark, footer)
- Modify: `web/public/favicon.svg`, `web/index.html` (`<title>`, description)
- Modify: `web/src/index.css` (`.startup-loading`, `.wordmark-icon`, `.app-footer`)

**Interfaces:**
- Consumes: `--brand-glow`, `--brand-line`, `--brand-eyes` (Task 1).
- Produces: `PRODUCT_NAME: "Calendar Ghost"`, `TAGLINE: string`, `APP_VERSION: string`, `documentTitle(page: string): string` from `@/lib/brand`; `GhostMark({ className?: string; title?: string })` from `@/components/ghost-mark`.

- [ ] **Step 1: Write the failing tests**

`web/src/lib/brand.test.ts`:

```ts
import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

import { APP_VERSION, PRODUCT_NAME, TAGLINE, documentTitle } from "./brand"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")
const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8")
const themeSource = readFileSync(new URL("./theme.ts", import.meta.url), "utf8")
const pkg = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")) as { version: string }

describe("brand", () => {
  it("names the product and its pages", () => {
    expect(PRODUCT_NAME).toBe("Calendar Ghost")
    expect(TAGLINE).toBe("Your busy time, everywhere it needs to be.")
    expect(documentTitle("Rules")).toBe("Rules – Calendar Ghost")
  })

  it("shows the version the bundle was built from", () => {
    expect(APP_VERSION).toBe(pkg.version)
  })

  it("keeps the saved appearance across the rename", () => {
    expect(themeSource).toContain('"calendar-sync-theme"')
    expect(html).toContain('const storageKey = "calendar-sync-theme"')
  })

  it("keeps the loading ghost still under reduced motion", () => {
    expect(stylesheet).toMatch(/\.startup-ghost \{[^}]*animation: ghost-breath/)
    expect(stylesheet).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.startup-ghost \{\s*animation: none;/)
  })
})
```

`web/src/components/ghost-mark.test.tsx`:

```tsx
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { GhostMark } from "./ghost-mark"

describe("GhostMark", () => {
  it("is decorative unless titled", () => {
    const markup = renderToStaticMarkup(<GhostMark className="x" />)
    expect(markup).toContain('aria-hidden="true"')
    expect(markup).toContain('class="ghost-mark x"')
    expect(markup).not.toContain("role=")
  })

  it("is an image named by its title when it stands alone", () => {
    const markup = renderToStaticMarkup(<GhostMark title="Calendar Ghost" />)
    expect(markup).toContain('role="img"')
    expect(markup).toContain('aria-label="Calendar Ghost"')
    expect(markup).not.toContain("aria-hidden")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm --prefix web run test -- brand ghost-mark`
Expected: FAIL — cannot resolve `./brand` and `./ghost-mark`.

- [ ] **Step 3: Inject the version at build time**

`web/vite.config.ts`:

```ts
import { readFileSync } from "node:fs"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as {
  version: string
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  // …existing resolve, server, and build unchanged
})
```

Append to `web/src/vite-env.d.ts`:

```ts
/** The `web/package.json` version, injected by Vite. */
declare const __APP_VERSION__: string
```

- [ ] **Step 4: Create `web/src/lib/brand.ts`**

```ts
/** User-facing identity. Code identifiers, storage keys, and env vars keep `calendar-sync`. */
export const PRODUCT_NAME = "Calendar Ghost"
export const TAGLINE = "Your busy time, everywhere it needs to be."
export const APP_VERSION = __APP_VERSION__

export function documentTitle(page: string): string {
  return `${page} – ${PRODUCT_NAME}`
}
```

- [ ] **Step 5: Create `web/src/components/ghost-mark.tsx`**

```tsx
import { cn } from "@/lib/utils"

// A calendar page on a 32-unit grid whose bottom edge is a three-scallop ghost hem.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

/** The Calendar Ghost mark. Decorative unless given a title. */
export function GhostMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      className={cn("ghost-mark", className)}
      viewBox="0 -1 32 32"
      fill="none"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="15" r="1.75" fill="var(--brand-eyes)" />
      <circle cx="19" cy="15" r="1.75" fill="var(--brand-eyes)" />
    </svg>
  )
}
```

- [ ] **Step 6: Run the tests**

Run: `npm --prefix web run test -- brand ghost-mark`
Expected: ghost-mark PASS; brand fails only on the reduced-motion assertion.

- [ ] **Step 7: Use the brand in the shell**

In `web/src/App.tsx`:
- Imports: drop `CalendarCheck2` from the lucide import, drop `Skeleton` if now unused; add `import { GhostMark } from "@/components/ghost-mark"` and `import { APP_VERSION, PRODUCT_NAME, documentTitle } from "@/lib/brand"`. `CalendarCheck2` stays used by `navItems`, so keep it if `navItems` still references it.
- Startup: `return <div className="startup-loading" role="status" aria-label={`Loading ${PRODUCT_NAME}`}><GhostMark className="startup-ghost" /></div>`
- Fatal: `<h1>{PRODUCT_NAME} is unavailable</h1>`
- Title: `document.title = documentTitle(location.ruleId ? "Rule" : title)`
- Wordmark: `aria-label={`${PRODUCT_NAME} overview`}` and children `<span className="wordmark-icon"><GhostMark /></span><span>{PRODUCT_NAME}</span>`
- Footer:

```tsx
<footer className="app-footer"><span>{PRODUCT_NAME}</span><span aria-hidden="true">·</span><span>v{APP_VERSION}</span><span aria-hidden="true">·</span><span>Runs on this device</span><span aria-hidden="true">·</span><a href="/api/docs">API documentation</a></footer>
```

- [ ] **Step 8: Style the mark, loading, and footer**

In `web/src/index.css`:
- `.startup-loading`: keep as is. Add after it:

```css
.startup-ghost {
  width: 3.5rem;
  height: 3.5rem;
  animation: ghost-breath 2.4s ease-in-out infinite;
}

@keyframes ghost-breath {
  0%,
  100% {
    opacity: 0.55;
  }

  50% {
    opacity: 1;
  }
}
```

- `.wordmark-icon svg { width: 1.25rem; height: 1.25rem; }` → `width: 1.75rem; height: 1.75rem;`
- `.app-footer`: add `flex-wrap: wrap;`
- At the top of the existing `@media (prefers-reduced-motion: reduce)` block, before the `*` rule:

```css
  .startup-ghost {
    animation: none;
  }
```

- [ ] **Step 9: Favicon and HTML metadata**

Replace `web/public/favicon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -1 32 32" fill="none">
  <style>
    .body{fill:#f3f4ff;stroke:#4a4cac}.tabs{stroke:#4a4cac}.eye{fill:#4a4cac}
    @media (prefers-color-scheme: dark){.body{fill:#e5e6fc;stroke:#e5e6fc}.tabs{stroke:#e5e6fc}.eye{fill:#131428}}
  </style>
  <path class="body" d="M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z" stroke-width="2" stroke-linejoin="round"/>
  <path class="tabs" d="M12 4.5v4M20 4.5v4" stroke-width="2" stroke-linecap="round"/>
  <circle class="eye" cx="13" cy="15" r="1.75"/>
  <circle class="eye" cx="19" cy="15" r="1.75"/>
</svg>
```

In `web/index.html`: `<title>Calendar Sync</title>` → `<title>Calendar Ghost</title>`; description → `content="Calendar Ghost: self-hosted, one-way Google Calendar sync. Your busy time, everywhere it needs to be."`

- [ ] **Step 10: Run tests, typecheck, lint**

Run: `npm --prefix web run test && npm --prefix web run typecheck && npm --prefix web run lint`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add web/src/lib/brand.ts web/src/lib/brand.test.ts web/src/components/ghost-mark.tsx web/src/components/ghost-mark.test.tsx web/vite.config.ts web/src/vite-env.d.ts web/src/App.tsx web/public/favicon.svg web/index.html web/src/index.css
git commit -m "feat(web): Calendar Ghost mark, favicon, wordmark, footer, and loading state"
```

---

### Task 3: Twilight auth panel, branded empty states, and the Settings notice

**Files:**
- Modify: `web/src/features/auth-screen.tsx:1-60`
- Modify: `web/src/features/rules.tsx:160-167`
- Modify: `web/src/features/activity.tsx:443-444`
- Modify: `web/src/features/settings.tsx:237`
- Modify: `web/src/index.css` (`.auth-intro`, `.brand-mark`, `.product-name`, `.auth-copy`, `.privacy-list`, `.empty-note`, `.empty-panel`; new `.inline-attention`, `.auth-tagline`, `.empty-ghost`)
- Create: `web/src/lib/brand-screens.test.ts`

**Interfaces:**
- Consumes: `GhostMark`, `PRODUCT_NAME`, `TAGLINE` (Task 2); `--twilight-*` tokens (Task 1).

- [ ] **Step 1: Write the failing test**

`web/src/lib/brand-screens.test.ts`:

```ts
import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

import authSource from "../features/auth-screen.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import activitySource from "../features/activity.tsx?raw"
import settingsSource from "../features/settings.tsx?raw"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")

describe("brand screens", () => {
  it("introduces sign-in and setup with the mark, name, and tagline", () => {
    expect(authSource).toContain('<GhostMark className="brand-mark" />')
    expect(authSource).toContain("{PRODUCT_NAME}")
    expect(authSource).toContain("{TAGLINE}")
    expect(authSource).not.toContain("CalendarCheck2")
  })

  it("keeps the auth intro twilight in both appearances", () => {
    expect(stylesheet).toMatch(/\.auth-intro \{[^}]*background: var\(--twilight-canvas\)/)
    expect(stylesheet).toMatch(/\.auth-intro \{[^}]*color: var\(--twilight-ink\)/)
  })

  it("shows the ghost in empty Rules and Activity", () => {
    expect(rulesSource).toContain('<GhostMark className="empty-ghost" />')
    expect(activitySource).toContain('<GhostMark className="empty-ghost" />')
  })

  it("uses attention, not destructive, for missing configuration", () => {
    expect(settingsSource).toContain('<div className="inline-attention" role="status">')
    expect(stylesheet).toMatch(/\.inline-attention \{[^}]*background: var\(--warning-surface\)/)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test -- brand-screens`
Expected: FAIL on all four.

- [ ] **Step 3: Auth intro markup**

In `web/src/features/auth-screen.tsx`, change the lucide import to `import { Check, LockKeyhole } from "lucide-react"`, add `import { GhostMark } from "@/components/ghost-mark"` and `import { PRODUCT_NAME, TAGLINE } from "@/lib/brand"`, and replace the brand lines:

```tsx
        <GhostMark className="brand-mark" />
        <p className="product-name">{PRODUCT_NAME}</p>
        <p className="auth-tagline">{TAGLINE}</p>
```

Headline and copy stay as they are.

- [ ] **Step 4: Auth intro styles**

Replace the `.auth-intro`, `.brand-mark, .wordmark-icon`, `.brand-mark`, `.brand-mark svg`, and `.product-name` rules with:

```css
.auth-intro {
  /* The mark on twilight is the dark-appearance ghost in both appearances. */
  --brand-glow: oklch(0.93 0.03 285);
  --brand-line: oklch(0.93 0.03 285);
  --brand-eyes: var(--twilight-canvas);
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: clamp(2.5rem, 7vw, 7rem);
  background: var(--twilight-canvas);
  color: var(--twilight-ink);
}

.wordmark-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.brand-mark {
  width: 4.5rem;
  height: 4.5rem;
  margin-bottom: 1.5rem;
}

.product-name {
  font-size: 1.125rem;
  font-weight: 650;
}

.auth-tagline {
  margin-bottom: 3rem;
  color: var(--twilight-muted);
  font-size: 0.9375rem;
}
```

Change `.auth-copy` and `.privacy-list` `color: var(--muted-foreground)` → `color: var(--twilight-muted)`, and `.privacy-list svg` `color: var(--success-foreground)` → `color: oklch(0.82 0.1 155)`. In the `@media (max-width: 800px)` block rename the `.product-name { margin-bottom: 1.5rem; }` rule to `.auth-tagline { margin-bottom: 1.75rem; }` and add `.brand-mark { width: 3.5rem; height: 3.5rem; }`. Check `grep -n "brand-mark\|product-name" web/src` shows no other user.

- [ ] **Step 5: Empty states**

`web/src/features/rules.tsx` — import `GhostMark` and make the empty note:

```tsx
          <section className="empty-note" aria-labelledby="no-rules-title">
            <GhostMark className="empty-ghost" />
            <div>
              <h2 id="no-rules-title">No rules yet</h2>
              <p>
                {connected.length === 0
                  ? "Connect a Google account in Settings, then create your first rule here."
                  : "Create a rule, preview its effects, then start syncing."}
              </p>
            </div>
          </section>
```

`web/src/features/activity.tsx` — import `GhostMark`; in the non-error empty panel replace `<div className="empty-icon"><Activity aria-hidden="true" /></div>` with `<GhostMark className="empty-ghost" />`. Remove `Activity` from the lucide import only if nothing else in the file uses it (`grep -n "<Activity" web/src/features/activity.tsx`).

CSS — `.empty-note` gains `display: flex; align-items: center; gap: 1rem;` and add:

```css
.empty-ghost {
  width: 3rem;
  height: 3rem;
  flex: none;
}

.empty-panel .empty-ghost {
  margin-bottom: 1rem;
}
```

- [ ] **Step 6: Settings notice**

`web/src/features/settings.tsx:237`: `<div className="inline-error" role="status">` → `<div className="inline-attention" role="status">`. Add after `.inline-error` in `index.css`:

```css
.inline-attention {
  padding: 0.75rem 0.875rem;
  border: 1px solid var(--warning-border);
  border-radius: 0.5rem;
  background: var(--warning-surface);
  color: var(--warning-foreground);
  font-size: 0.875rem;
  line-height: 1.45;
}
```

If `.inline-error code` styling exists, extend that selector to `.inline-attention code`.

- [ ] **Step 7: Run tests, typecheck, lint**

Run: `npm --prefix web run test && npm --prefix web run typecheck && npm --prefix web run lint`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/auth-screen.tsx web/src/features/rules.tsx web/src/features/activity.tsx web/src/features/settings.tsx web/src/index.css web/src/lib/brand-screens.test.ts
git commit -m "feat(web): twilight sign-in, ghost empty states, attention tone for missing configuration"
```

---

### Task 4: Rename the product in Web UI copy

**Files:**
- Create: `web/src/lib/product-name.test.ts`
- Modify (string literals and comments only): `web/src/lib/activity.ts`, `web/src/lib/rule-run.ts`, `web/src/lib/incidents.ts`, `web/src/lib/overview-health.ts`, `web/src/lib/activity-failure.ts`, `web/src/features/overview.tsx`, `web/src/features/settings.tsx`, `web/src/features/activity.tsx`, `web/src/components/activity-event.tsx`
- Modify tests: `web/src/lib/activity.test.ts`, `web/src/lib/rule-run.test.ts`, and any other test the guard reports

- [ ] **Step 1: Write the failing guard**

`web/src/lib/product-name.test.ts`:

```ts
import { describe, expect, it } from "vitest"

const sources = import.meta.glob(["../**/*.{ts,tsx}", "!../**/product-name.test.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>

describe("product name", () => {
  it("never shows the retired name", () => {
    const stale = Object.entries(sources)
      .filter(([, text]) => /Calendar Sync\b/.test(text))
      .map(([path]) => path)
    expect(stale).toEqual([])
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm --prefix web run test -- product-name`
Expected: FAIL listing about a dozen files (those above).

- [ ] **Step 3: Rename**

Run: `grep -rln "Calendar Sync" web/src | xargs perl -pi -e 's/Calendar Sync\b/Calendar Ghost/g'` (perl, because BSD `sed` has no `\b`). Then `git diff web/src` and confirm every change is a user-facing sentence, a test expectation, or a comment — no identifiers, keys, or URLs changed.

- [ ] **Step 4: Run the suite**

Run: `npm --prefix web run test`
Expected: PASS (the renamed test expectations match the renamed copy).

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): call the product Calendar Ghost in every explanation and notice"
```

---

### Task 5: Rename the product in backend copy

**Files:**
- Modify: `src/calendar_sync/infrastructure/notifications.py:88,100`
- Modify: `src/calendar_sync/interfaces/api/app.py:60`
- Modify: `src/calendar_sync/__init__.py:1`, `pyproject.toml:8`
- Create: `tests/adapters/test_notifications.py`
- Modify: `tests/adapters/test_api.py:850,863`

- [ ] **Step 1: Write the failing tests**

Read `src/calendar_sync/infrastructure/notifications.py` for the `IncidentNotification` constructor fields, then create `tests/adapters/test_notifications.py`:

```python
from email.message import EmailMessage
from typing import Any

import pytest

from calendar_sync.infrastructure import notifications
from calendar_sync.infrastructure.notifications import SmtpChannel


class RecordingSmtp:
    sent: list[EmailMessage] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> "RecordingSmtp":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, *_args: str) -> None:
        pass

    def send_message(self, message: EmailMessage) -> None:
        RecordingSmtp.sent.append(message)


def test_incident_email_names_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr(notifications.smtplib, "SMTP", RecordingSmtp)
    channel = SmtpChannel(
        host="smtp.example", port=587, sender="a@example.com", recipient="b@example.com"
    )

    channel.send(incident())

    (message,) = RecordingSmtp.sent
    assert message["Subject"].startswith("Calendar Ghost incident: ")
    assert "Open Calendar Ghost Activity for current status." in message.get_content()
```

Define `incident()` in the same file building an `IncidentNotification` with synthetic values (`summary="A rule needs attention"`, `rule_id="rule-1"`, plus whatever other fields the dataclass requires). In `tests/adapters/test_api.py` change both `assert "Calendar Sync" in response.text` to `assert "Calendar Ghost" in response.text`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_notifications.py tests/adapters/test_api.py -k "notification or frontend_fallback" -v`
Expected: notification test FAILS on the subject; the API tests FAIL until Task 7 rebuilds `static/index.html` (expected; leave them failing until then).

- [ ] **Step 3: Rename**

- `notifications.py`: `f"Calendar Sync incident: …"` → `f"Calendar Ghost incident: …"`; `"Open Calendar Sync Activity for current status."` → `"Open Calendar Ghost Activity for current status."`
- `app.py`: `title="Google Calendar Sync"` → `title="Calendar Ghost"`
- `__init__.py`: `"""Calendar Ghost: a modular monolith for one-way Google Calendar synchronization."""`
- `pyproject.toml`: `description = "Calendar Ghost: self-hosted, one-way Google Calendar synchronization"`

- [ ] **Step 4: Run the notification test**

Run: `.venv/bin/pytest tests/adapters/test_notifications.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/infrastructure/notifications.py src/calendar_sync/interfaces/api/app.py src/calendar_sync/__init__.py pyproject.toml tests/adapters/test_notifications.py tests/adapters/test_api.py
git commit -m "feat: name incident emails and the API Calendar Ghost"
```

---

### Task 6: Documentation and design system

**Files:**
- Modify: `DESIGN.md`, `.impeccable/design.json`, `PRODUCT.md`, `README.md`, `CONTEXT.md`, `AGENTS.md`, `docs/architecture.md`, `docs/deployment.md`, `docs/troubleshooting.md`, `CHANGELOG.md`

- [ ] **Step 1: Rename prose**

Replace "Google Calendar Sync" and "Calendar Sync" with "Calendar Ghost" in `README.md` (title becomes `# Calendar Ghost` followed by a line `*Your busy time, everywhere it needs to be.* Self-hosted, one-way sync between Google calendars.`), `PRODUCT.md`, `AGENTS.md` line 5, `docs/architecture.md`, `docs/deployment.md`, `docs/troubleshooting.md`, and `CONTEXT.md` lines 270–271. Leave `CONTEXT.md`'s `# Calendar Synchronization` heading (it names the domain), `LICENSE`, ADRs, and existing CHANGELOG entries.

- [ ] **Step 2: Record the naming decision in `CONTEXT.md`**

Add to its settled product decisions section:

```markdown
- The product is named **Calendar Ghost**. "Ghost" is brand language for the mark and tagline;
  the interface and documentation keep this glossary's terms, so a Managed Projection is never
  called a "ghost" in labels, explanations, or incidents.
```

- [ ] **Step 3: Rewrite `DESIGN.md`**

- Frontmatter: `name: Calendar Ghost`; `description: A calm ghost that keeps your busy time where it needs to be`. Replace `status-cobalt`/`night-status-cobalt` with `lantern-indigo: "oklch(0.47 0.15 278)"` / `night-lantern-indigo: "oklch(0.74 0.12 278)"`, and update `daylight`→`mist`, `quiet-surface`, `muted-surface`, `calm-ink`, `muted-ink`, `quiet-border`, `night*` neutrals to the Task 1 values; add `brand-glow`, `twilight-canvas`, `twilight-ink`, `twilight-muted`. Typography: `headline.fontFamily: "Fraunces Variable, ui-serif, Georgia, serif"`, `fontWeight: 560`, `letterSpacing: "-0.015em"`; `title`/`body`/`label` use `"Figtree Variable, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"`, `title.fontWeight: 650`. Components: `button-primary.backgroundColor: "{colors.lantern-indigo}"`.
- Body: title `# Design System: Calendar Ghost`. North Star becomes **"The Calm Ghost"**: *"A friendly presence at twilight: pale, quiet, and always where you expect it. The ghost lives in the mark, the sign-in panel, loading, and empty states; everywhere else the interface is a calm household utility."* Rename "Status Cobalt" → "Lantern Indigo" throughout (Quiet Indicator Rule now names Lantern Indigo). Typography section: display Fraunces (page titles and auth headline only, SOFT 100), body Figtree, bundled for offline use, hierarchy as in the spec §4.
- Add a `## Brand` section before `## Colors`: name and tagline; the mark (calendar page, two tabs, three-scallop hem, two eyes; `GhostMark`; `--brand-glow`/`--brand-line`/`--brand-eyes`); **The Ghost Is Brand, Not Vocabulary Rule** — the ghost appears in the mark, auth panel, loading, and empty states; labels and explanations use the glossary.
- Update "Elevation"/"Do's and Don'ts" only where they name cobalt or Inter.

- [ ] **Step 4: Update `.impeccable/design.json`**

Set `"title": "Design System: Calendar Ghost"`; replace the `status-cobalt` colorMeta entry with `lantern-indigo` (`displayName: "Lantern Indigo"`, `canonical: "oklch(0.47 0.15 278)"`, `tonalRamp` from `oklch(0.15 0.06 278)` to `oklch(0.95 0.02 278)` in the same eight steps as before with hue 278), rename `daylight` to `mist` with `canonical: "oklch(0.99 0.004 285)"`; in component CSS strings replace `Inter,system-ui` with `Figtree Variable,system-ui`; `narrative.northStar: "The Calm Ghost"`, `narrative.overview` = the North Star sentence above, rule "The Quiet Indicator Rule" body names Lantern Indigo, and add `{ "name": "The Ghost Is Brand, Not Vocabulary Rule", "body": "The ghost appears in the mark, sign-in, loading, and empty states; labels use the glossary.", "section": "brand" }`. Validate with `python3 -m json.tool .impeccable/design.json > /dev/null`.

- [ ] **Step 5: CHANGELOG**

Under `## [Unreleased]` add (create `### Changed` if absent):

```markdown
### Changed

- The product is now called **Calendar Ghost**, with a ghost mark, a twilight palette led by Lantern Indigo, and bundled Fraunces and Figtree typefaces that render without internet access. Package, environment variable, image, and database names are unchanged, so existing installations upgrade in place and keep their appearance setting. Missing Google configuration in Settings now reads as attention rather than an error.
```

- [ ] **Step 6: Check language and names**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -q && grep -rn "Calendar Sync\b" --include='*.md' . | grep -v node_modules | grep -v "docs/adr/\|docs/superpowers/\|CHANGELOG.md"`
Expected: tests PASS; grep prints nothing except intentional mentions (none expected).

- [ ] **Step 7: Commit**

```bash
git add DESIGN.md .impeccable/design.json PRODUCT.md README.md CONTEXT.md AGENTS.md docs/architecture.md docs/deployment.md docs/troubleshooting.md CHANGELOG.md
git commit -m "docs: Calendar Ghost name, Calm Ghost design system, and changelog"
```

---

### Task 7: Build, quality gates, and visual verification

**Files:**
- Modify: `src/calendar_sync/interfaces/api/static/` (generated)

- [ ] **Step 1: Build the frontend**

Run: `npm --prefix web run build`
Expected: succeeds; `src/calendar_sync/interfaces/api/static/index.html` contains `<title>Calendar Ghost</title>` and the `assets/` folder includes Figtree and Fraunces `.woff2` files (`ls src/calendar_sync/interfaces/api/static/assets | grep -i woff2`).

- [ ] **Step 2: Run both quality gates**

```sh
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build
```

Expected: all PASS, including the `test_frontend_fallback_*` API tests that failed in Task 5.

- [ ] **Step 3: Visual verification**

Start `.venv/bin/python scripts/dev_preview.py` in the background (http://127.0.0.1:8001, password `preview-password`). With `~/.claude/skills/gstack/browse/dist/browse`, capture into `.context/after/`: login, overview, rules, rule-details, activity, settings at 1440×900 in light; overview, login, and settings in dark (`localStorage.setItem('calendar-sync-theme','dark')` then reload); overview and login at 390×844. Check against `.context/before/`:
- the ghost mark is crisp in the top bar and favicon, and its eyes are visible in both appearances;
- page titles render in Fraunces, everything else in Figtree (`browse js "getComputedStyle(document.querySelector('h1')).fontFamily"`);
- the 390px top bar does not wrap or overflow, and the auth panel stacks above the form;
- `browse console --errors` is empty.
Stop the preview task afterwards.

- [ ] **Step 4: Commit**

```bash
git add src/calendar_sync/interfaces/api/static
git commit -m "build: regenerate the Web UI for Calendar Ghost"
```
