# Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the self-hosting landing page for `calendarghost.com` in a `site/` folder of this
repository, with an animated ghost hero, and ship it through Cloudflare Workers Builds.

**Architecture:** An Astro static site with three React islands (The Wide Reveal hero, The Haunted
Week, The Crossing). All copy lives in one typed English message module; demo data and animation
timing are pure functions with unit tests; the islands only render them. Browser-level promises (no
third-party requests, reduced motion, keyboard, no JavaScript, phone width, clipboard fallback) are
pinned by Playwright tests against the production build.

**Tech Stack:** Astro 7.3.5, @astrojs/react 7.0.0, @astrojs/sitemap 3.7.4, React 19.2.8,
TypeScript 6.0.3, Vitest 4.1.11 with happy-dom, Playwright 1.63.0, Wrangler 4.147.0,
@fontsource-variable Figtree and Fraunces 5.3.0.

**Spec:** `docs/superpowers/specs/2026-10-04-landing-page-design.md`

## Global Constraints

- The site lives in `site/` with its own `package.json` and lockfile; nothing under `site/` enters
  the Docker build context or image.
- Node.js 22.12 or later (Astro 7's floor); exact versions pinned with `--save-exact`.
- No analytics, no tracking script, and no request to any host other than the page's own origin:
  fonts are self-hosted, nothing loads from a CDN, and the star button shows no count.
- All user-visible copy lives in `site/src/i18n/en.ts`; components never contain literal copy.
  Product names, shell commands, clock times, and URLs are not copy.
- No text is baked into images or animations.
- Copy is plain, literal, short active sentences; microcopy may joke; no em dashes (U+2014).
- Copy is true to `CONTEXT.md`: a Details Projection copies title, description, and location; guests,
  organizer, conferencing links, attachments, and invitations never cross over. Avoided glossary
  terms are not used.
- Headline: "Sync your calendars. Keep your privacy." Chip: "Pre-alpha · Open source (AGPL) ·
  Google Calendar".
- Demo content follows Sam with Personal, Family, and Work calendars.
- English only; `defaultLocale: "en"` without a path prefix; the language picker renders only when
  a second locale exists.
- The page follows the device's light or dark setting; every demo works in both.
- `prefers-reduced-motion` stops everything that moves by itself.
- WCAG 2.2 AA.
- Repository URL: `https://github.com/DannieBGoode/calendar-ghost`. Site URL:
  `https://calendarghost.com`.

## Review Focus

1. **Reduced motion:** a visitor with reduced motion sees nothing move by itself; the hero rests
   with its slider at 55% and still responds to dragging. Pinned in Task 9.
2. **Keyboard and screen reader on the hero slider:** arrow keys move the reveal, the value is
   announced, and the ghost does not snatch it back while the slider has focus. Pinned in Task 9.
3. **JavaScript off:** every section's text, the hero's resting state, and the screenshots are in
   the HTML. Pinned in Task 9.
4. **Phone width (390×844):** the headline and "Self-host it" are visible without scrolling, and
   the hero week shows Monday to Wednesday instead of five unreadable columns. Pinned in Task 9.
5. **Clipboard unavailable** (plain HTTP on a LAN, older browsers): a copy button selects the
   command so the visitor can copy it by hand, instead of failing silently. Pinned in Task 9.

---

## File map

```text
site/
  package.json, package-lock.json, .node-version
  astro.config.mjs, tsconfig.json, vitest.config.ts, playwright.config.ts, wrangler.jsonc
  public/          favicon.svg, og.png, robots.txt
  scripts/         audit.mjs (+ audit.test.mjs), audit-dist.mjs, og-image.mjs
  e2e/             landing.spec.ts
  src/
    links.ts                     repository and documentation URLs
    i18n/en.ts                   all English copy; defines the Messages type
    i18n/index.ts                locales, messagesFor, hasLanguagePicker, localePath
    i18n/format.ts               {placeholder} interpolation
    i18n/messages.test.ts        copy rules
    demo/week.ts                 Sam's week
    demo/layout.ts               event position math
    demo/haunted.ts              The Haunted Week's timeline
    demo/crossing.ts             which fields cross over per mode
    demo/*.test.ts
    content/self-host.ts         the three install commands (+ test against README)
    islands/GhostMark.tsx, WeekGrid.tsx, EventCard.tsx
    islands/motion.ts (+ test), hooks.ts
    islands/WideReveal.tsx (+ test), HauntedWeek.tsx, Crossing.tsx (+ test)
    sections/*.astro             one component per page section
    layouts/Layout.astro
    pages/index.astro, pages/404.astro
    styles/tokens.css, global.css, demos.css
```

Root files touched: `.dockerignore`, `.gitignore`, `AGENTS.md`, `docs/development.md`,
`tests/test_ubiquitous_language.py`, `.github/workflows/site.yml` (new).

---

### Task 1: Site workspace, brand foundation, and the copy contract

**Files:**
- Create: `site/package.json`, `site/.node-version`, `site/astro.config.mjs`, `site/tsconfig.json`,
  `site/vitest.config.ts`, `site/src/links.ts`, `site/src/i18n/en.ts`, `site/src/i18n/index.ts`,
  `site/src/i18n/format.ts`, `site/src/styles/tokens.css`, `site/src/styles/global.css`,
  `site/src/styles/demos.css` (empty for now), `site/src/layouts/Layout.astro`,
  `site/src/pages/index.astro`, `site/public/favicon.svg`
- Test: `site/src/i18n/messages.test.ts`
- Modify: `.dockerignore`, `.gitignore`

**Interfaces:**
- Produces: `en` and `type Messages` (from `src/i18n/en.ts`, re-exported by `src/i18n/index.ts`);
  `messagesFor(locale?: string): Messages`; `hasLanguagePicker(): boolean`;
  `localePath(locale: Locale, pathname: string): string`; `LOCALES`; `type Locale`;
  `format(template: string, values: Record<string, string | number>): string`;
  `REPO_URL`, `GUIDE_URL`, `LICENSE_URL`, `TRADEMARKS_URL` from `src/links.ts`;
  `Layout.astro` with props `{ title: string; description: string; noindex?: boolean }`.

- [ ] **Step 1: Create the package and install exact versions**

Create `site/package.json`:

```json
{
  "name": "calendar-ghost-site",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "check": "astro check",
    "test": "vitest run",
    "audit:dist": "node scripts/audit-dist.mjs",
    "e2e": "playwright test"
  }
}
```

Create `site/.node-version` containing `22` (Cloudflare Workers Builds reads it).

Run from `site/`:

```sh
npm install --save-exact astro@7.3.5 @astrojs/react@7.0.0 @astrojs/sitemap@3.7.4 \
  react@19.2.8 react-dom@19.2.8 oxc-transform-react@^0.145.0 \
  @fontsource-variable/figtree@5.3.0 @fontsource-variable/fraunces@5.3.0
npm install --save-exact --save-dev @astrojs/check@0.9.10 typescript@6.0.3 \
  @types/react@19.2.18 @types/react-dom@19.2.5 vitest@4.1.11 happy-dom@20.14.5 \
  @playwright/test@1.63.0 wrangler@4.147.0
```

Expected: install succeeds with no peer-dependency errors. `oxc-transform-react` is a peer of
`@astrojs/react` 7; `--save-exact` records the resolved `0.145.x`.

- [ ] **Step 2: Configure Astro, TypeScript, and Vitest**

`site/astro.config.mjs`:

```js
import react from "@astrojs/react"
import sitemap from "@astrojs/sitemap"
import { defineConfig } from "astro/config"

export default defineConfig({
  site: "https://calendarghost.com",
  i18n: { defaultLocale: "en", locales: ["en"], routing: { prefixDefaultLocale: false } },
  integrations: [react(), sitemap()],
  // Screenshots are imported from docs/assets so the page and the README never drift.
  vite: { server: { fs: { allow: [".."] } } },
})
```

`site/tsconfig.json`:

```json
{
  "extends": "astro/tsconfigs/strict",
  "compilerOptions": { "jsx": "react-jsx", "jsxImportSource": "react" },
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist", "node_modules"]
}
```

`site/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config"

export default defineConfig({
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "scripts/**/*.test.mjs"],
  },
})
```

- [ ] **Step 3: Write the failing copy-rules test**

`site/src/i18n/messages.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { en } from "./en"
import { format } from "./format"
import { hasLanguagePicker, localePath, messagesFor } from "./index"

function strings(value: unknown, path = "en"): [string, string][] {
  if (typeof value === "string") return [[path, value]]
  if (Array.isArray(value)) return value.flatMap((item, index) => strings(item, `${path}[${index}]`))
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => strings(item, `${path}.${key}`))
  }
  return []
}

describe("English copy", () => {
  it("has no empty or padded strings", () => {
    const bad = strings(en).filter(([, text]) => text.trim() === "" || text.trim() !== text)
    expect(bad).toEqual([])
  })

  it("never uses an em dash", () => {
    expect(strings(en).filter(([, text]) => text.includes("\u2014"))).toEqual([])
  })

  it("states the approved headline and scope chip", () => {
    expect(en.hero.title).toBe("Sync your calendars. Keep your privacy.")
    expect(en.hero.chip).toBe("Pre-alpha · Open source (AGPL) · Google Calendar")
  })

  it("lists everything that never crosses over", () => {
    expect(en.crossing.alwaysStays).toEqual([
      "Guests",
      "Organizer",
      "Meeting links",
      "Attachments",
      "Invitations",
    ])
  })
})

describe("locales", () => {
  it("falls back to English for an unknown locale", () => {
    expect(messagesFor("xx")).toBe(en)
    expect(messagesFor(undefined)).toBe(en)
  })

  it("hides the language picker while English is the only language", () => {
    expect(hasLanguagePicker()).toBe(false)
  })

  it("serves English without a prefix", () => {
    expect(localePath("en", "/")).toBe("/")
    expect(localePath("en", "/404")).toBe("/404")
  })
})

describe("format", () => {
  it("fills placeholders and leaves unknown ones", () => {
    expect(format("{percent}% of {thing}", { percent: 40 })).toBe("40% of {thing}")
  })
})
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npm test -- src/i18n` (from `site/`)
Expected: FAIL, cannot resolve `./en`.

- [ ] **Step 5: Write the copy, the i18n helpers, and the links**

`site/src/links.ts`:

```ts
export const SITE_URL = "https://calendarghost.com"
export const REPO_URL = "https://github.com/DannieBGoode/calendar-ghost"
export const GUIDE_URL = `${REPO_URL}/blob/main/docs/self-hosting.md`
export const LICENSE_URL = `${REPO_URL}/blob/main/LICENSE`
export const TRADEMARKS_URL = `${REPO_URL}/blob/main/TRADEMARKS.md`
```

`site/src/i18n/format.ts`:

```ts
/** Replaces each `{name}` with its value; unknown names stay as written. */
export function format(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in values ? String(values[name]) : match,
  )
}
```

`site/src/i18n/en.ts` (the complete copy; later tasks read keys from here):

```ts
// Every user-visible word on the site. A new language copies this module and
// `satisfies Messages`, so a missing key fails `astro check`.
export const en = {
  meta: {
    title: "Calendar Ghost: private calendar sync you host yourself",
    description:
      "Sync your Google calendars on your own server. Share only “Busy”, or the details you choose. Open source, self-hosted, no trackers.",
    notFoundTitle: "Page not found · Calendar Ghost",
  },
  nav: {
    label: "Main",
    home: "Calendar Ghost home",
    howItWorks: "How it works",
    features: "Features",
    selfHost: "Self-host",
    star: "Star on GitHub",
    menu: "Menu",
    language: "Language",
  },
  hero: {
    chip: "Pre-alpha · Open source (AGPL) · Google Calendar",
    title: "Sync your calendars. Keep your privacy.",
    sub: "Calendar Ghost copies events from one Google calendar to another, on your own server. You choose what crosses over. Guests and meeting links always stay behind.",
    primary: "Self-host it",
    secondary: "Star on GitHub",
  },
  demo: {
    days: ["Mon", "Tue", "Wed", "Thu", "Fri"],
    youSee: "What you see",
    workSees: "What work sees",
    busy: "Busy",
    sliderLabel: "Compare your week with what work sees",
    sliderValueText: "{percent}% of the week shows your view",
    hint: "Drag the ghost.",
    revealSummary:
      "Sam's work week, twice. On the left, Sam sees work meetings and personal plans with their details. On the right, work sees the same meetings, and each personal plan only as “Busy”.",
    workCalendar: "Work calendar · sam@work.example",
    calendars: { personal: "Personal", family: "Family", work: "Work" },
    from: { personal: "from Personal", family: "from Family" },
    events: {
      standup: { title: "Standup", detail: "Team" },
      clientCall: { title: "Client call", detail: "Acme" },
      oneOnOne: { title: "1:1 with Lee", detail: "Room 3" },
      designReview: { title: "Design review", detail: "Team" },
      retro: { title: "Retro", detail: "Team" },
      dentist: { title: "Dentist", detail: "Smile Clinic" },
      gym: { title: "Gym", detail: "with Ana" },
      schoolDropOff: { title: "School drop-off", detail: "Maple Primary" },
      therapy: { title: "Therapy", detail: "Dr. Okafor" },
      recital: { title: "Recital", detail: "Town hall" },
    },
  },
  how: {
    title: "How it works",
    steps: [
      {
        title: "Connect your Google accounts.",
        body: "Personal, family, and work can each be a different Google account.",
      },
      {
        title: "Make a rule.",
        body: "Pick one calendar to read from and one to write to. Then choose what crosses over.",
      },
      {
        title: "Preview, then sync.",
        body: "See exactly what will be written before anything changes. Then it runs by itself every five minutes.",
      },
    ],
  },
  week: {
    title: "One week, every calendar.",
    body: "Make one rule per calendar: Personal to Work, Family to Work. Calendar Ghost keeps them all in step.",
    summary:
      "Events from the Personal and Family calendars arrive on the Work calendar as “Busy”. Work's own meetings stay as they are.",
  },
  crossing: {
    title: "You choose what crosses over.",
    switchLabel: "What crosses over",
    busyOnly: "Busy only",
    withDetails: "With details",
    busyOnlyBody: "Only the time crosses over, titled “Busy”.",
    withDetailsBody: "The title, description, and place cross over too.",
    alwaysStaysTitle: "Always stays behind",
    alwaysStays: ["Guests", "Organizer", "Meeting links", "Attachments", "Invitations"],
    guests: "Dr. Ruiz",
    link: "meet.google.com/abc-defg-hij",
    summary:
      "The Dentist event moves from the Personal calendar to the Work calendar. With Busy only, it arrives titled “Busy”. With details, it keeps its title and place. Guests and the meeting link never cross over.",
  },
  app: {
    title: "See the app",
    body: "Real screens, with made-up data for Sam's three calendars.",
    overview: {
      alt: "Calendar Ghost Overview showing healthy synchronization, rules, and recent changes",
      caption: "Overview: one plain answer to “is everything in sync?”",
    },
    rules: {
      alt: "Calendar Ghost Rules showing source and destination calendars",
      caption: "Rules: each one reads one calendar and writes one other.",
    },
    activity: {
      alt: "Calendar Ghost Activity showing what each rule did",
      caption: "Activity: what happened to each event, and why.",
    },
  },
  trust: {
    title: "Built to be trusted",
    cards: [
      {
        title: "Fixes itself",
        body: "Someone edits or deletes a synced event? The next sync puts it back the way the source calendar says.",
      },
      { title: "Preview first", body: "A rule cannot start until you have seen exactly what it will write." },
      { title: "Never emails your guests", body: "Synced events never send invitations or updates to anyone." },
      {
        title: "No loops",
        body: "Events that Calendar Ghost creates are never synced again, even with rules in both directions.",
      },
      {
        title: "Recurring events stay recurring",
        body: "A weekly meeting arrives as a weekly event, with its exceptions.",
      },
      { title: "See what happened", body: "Activity shows what each rule did, and why." },
      { title: "No telemetry", body: "It talks only to Google and to the notification targets you set up." },
      {
        title: "Monitors and AI agents",
        body: "A status API and an MCP server report health to Uptime Kuma, your homelab dashboard, or your AI agent.",
      },
    ],
  },
  selfHost: {
    title: "Self-host it",
    body: "Calendar Ghost runs as one small Docker service with one SQLite file. You own the server, the data, and the keys.",
    needsTitle: "What you need",
    needs: [
      "Docker with Compose",
      "A Google Cloud project, for sign-in with Google",
      "Any small machine: a home server, a VPS, or a Raspberry Pi (arm64)",
    ],
    stepsTitle: "Start it",
    steps: [
      "Get the code.",
      "Create your settings file, then fill it in as the guide shows.",
      "Start it, then open http://localhost:8000.",
    ],
    copy: "Copy",
    copied: "Copied",
    selected: "Selected. Press Ctrl+C or ⌘C.",
    oauthNote: "Creating the Google sign-in client is the longest step. The guide walks you through it.",
    guide: "Read the self-hosting guide",
  },
  why: {
    title: "Why I built this",
    body: [
      "I wanted my personal and family plans to block time on my work calendar, without my employer seeing my dentist appointments, and without handing every calendar I own to yet another hosted service.",
      "The self-hosted tools I found did not work the way I needed. So I built the one I wanted: one-way rules, Busy by default, a preview before anything is written, and everything on my own machine.",
      "It is early, it is open source, and I would love your feedback.",
    ],
    signature: "Daniel (@DannieBGoode)",
  },
  faq: {
    title: "Questions",
    items: [
      { q: "Is it free?", a: "Yes. It is open source under AGPL-3.0. You run it and pay only for your own server." },
      {
        q: "Can it sync both ways?",
        a: "Yes, with two rules, one in each direction. Calendar Ghost never syncs its own events back.",
      },
      { q: "Outlook, iCloud, or CalDAV?", a: "Not yet. Google Calendar is the only provider today." },
      {
        q: "Is it ready for my real calendars?",
        a: "Not yet. It is pre-alpha: use test calendars and keep backups.",
      },
      { q: "Is there a hosted version?", a: "Not yet. If one comes, it will run this same open code." },
    ],
  },
  footer: {
    cta: "Ready to try it?",
    license: "Open source under the GNU AGPL, version 3 or later.",
    trademarks: "Trademarks",
    github: "GitHub",
    noTrackers: "This page has no trackers.",
  },
  notFound: {
    title: "Nothing here but a ghost.",
    body: "This page does not exist. The ghost looked everywhere, then took a nap.",
    home: "Back to the home page",
  },
}

export type Messages = typeof en
```

`site/src/i18n/index.ts`:

```ts
import { en, type Messages } from "./en"

export type { Messages }

export const LOCALES = { en } satisfies Record<string, Messages>
export type Locale = keyof typeof LOCALES
export const DEFAULT_LOCALE: Locale = "en"

export function messagesFor(locale: string | undefined): Messages {
  return locale && locale in LOCALES ? LOCALES[locale as Locale] : LOCALES[DEFAULT_LOCALE]
}

export function hasLanguagePicker(): boolean {
  return Object.keys(LOCALES).length > 1
}

/** English has no prefix; every other language lives under `/<locale>`. */
export function localePath(locale: Locale, pathname: string): string {
  return locale === DEFAULT_LOCALE ? pathname : `/${locale}${pathname}`
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm test -- src/i18n`
Expected: PASS, 8 tests.

- [ ] **Step 7: Add tokens, base styles, the favicon, and the layout**

`site/src/styles/tokens.css`:

```css
/* A subset of the application's tokens (web/src/index.css). DESIGN.md is the source of truth;
   keep these in step with it. The page follows the device's color scheme only. */
:root {
  color-scheme: light dark;
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
  --ring: oklch(0.47 0.15 278);
  --brand-glow: oklch(0.97 0.02 285);
  --brand-line: var(--primary);
  --brand-eyes: var(--primary);
  --event-work: oklch(0.95 0.012 285);
  --event-personal: oklch(0.92 0.06 155);
  --event-personal-edge: oklch(0.55 0.12 155);
  --event-family: oklch(0.93 0.07 85);
  --event-family-edge: oklch(0.62 0.12 75);
  --event-busy: oklch(0.93 0.035 280 / 0.85);
  --reveal-you: oklch(0.965 0.02 200);
  --radius: 0.625rem;
  --panel-radius: 0.875rem;
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: oklch(0.17 0.022 280);
    --foreground: oklch(0.95 0.012 285);
    --surface: oklch(0.21 0.026 280);
    --muted: oklch(0.26 0.03 280);
    --muted-foreground: oklch(0.75 0.025 285);
    --primary: oklch(0.74 0.12 278);
    --primary-foreground: oklch(0.17 0.03 280);
    --primary-soft: oklch(0.28 0.06 278);
    --border: oklch(0.34 0.03 280);
    --ring: oklch(0.74 0.12 278);
    --brand-glow: oklch(0.93 0.03 285);
    --brand-line: oklch(0.93 0.03 285);
    --brand-eyes: oklch(0.2 0.04 280);
    --event-work: oklch(0.26 0.03 280);
    --event-personal: oklch(0.45 0.09 155 / 0.9);
    --event-personal-edge: oklch(0.72 0.12 155);
    --event-family: oklch(0.5 0.09 80 / 0.85);
    --event-family-edge: oklch(0.80 0.12 80);
    --event-busy: oklch(0.42 0.08 278 / 0.55);
    --reveal-you: oklch(0.22 0.03 200);
  }
}
```

`site/src/styles/global.css`:

```css
*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 1rem;
  line-height: 1.6;
  color: var(--foreground);
  background: var(--background);
  text-rendering: optimizeLegibility;
}
h1, h2 {
  font-family: var(--font-display);
  font-weight: 560;
  font-variation-settings: "SOFT" 100;
  letter-spacing: -0.015em;
  line-height: 1.1;
  margin: 0 0 0.75rem;
}
h1 { font-size: clamp(2.25rem, 5vw + 1rem, 4rem); }
h2 { font-size: clamp(1.75rem, 2.5vw + 1rem, 2.5rem); }
h3 { font-size: 1rem; font-weight: 650; margin: 0 0 0.25rem; }
p { margin: 0 0 1rem; }
a { color: var(--primary); }
:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
.container { width: min(72rem, 100% - 2.5rem); margin-inline: auto; }
.section { padding-block: clamp(4rem, 8vw, 7rem); }
.lead { font-size: 1.125rem; color: var(--muted-foreground); max-width: 46ch; }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
.chip {
  display: inline-block; font-size: 0.8125rem; font-weight: 600; color: var(--muted-foreground);
  border: 1px solid var(--border); border-radius: 999px; padding: 0.25rem 0.75rem; margin: 0 0 1rem;
}
.ctas { display: flex; flex-wrap: wrap; gap: 0.75rem; }
.btn {
  display: inline-flex; align-items: center; gap: 0.4rem; min-height: 2.75rem; padding: 0.6rem 1.1rem;
  border-radius: var(--radius); border: 1px solid var(--border); background: var(--surface);
  color: var(--foreground); font: 600 0.9375rem/1 var(--font-sans); text-decoration: none; cursor: pointer;
  transition: background 180ms var(--ease-out);
}
.btn:hover { background: var(--muted); }
.btn-primary { background: var(--primary); color: var(--primary-foreground); border-color: transparent; }
.btn-primary:hover { background: color-mix(in oklch, var(--primary), var(--foreground) 12%); }
.btn-small { min-height: 2.25rem; padding: 0.4rem 0.8rem; font-size: 0.875rem; }
```

Create `site/src/styles/demos.css` empty; Tasks 4 to 6 append to it.

Copy `web/src/assets/favicon.svg` to `site/public/favicon.svg` unchanged.

`site/src/layouts/Layout.astro`:

```astro
---
import "@fontsource-variable/figtree"
import "@fontsource-variable/fraunces/full.css"
import "../styles/tokens.css"
import "../styles/global.css"
import "../styles/demos.css"
import { LOCALES, hasLanguagePicker, localePath, type Locale } from "../i18n"

interface Props {
  title: string
  description: string
  noindex?: boolean
}

const { title, description, noindex = false } = Astro.props
const site = Astro.site ?? new URL("https://calendarghost.com")
const canonical = new URL(Astro.url.pathname, site)
const ogImage = new URL("/og.png", site)
const lang = Astro.currentLocale ?? "en"
const alternates = hasLanguagePicker()
  ? (Object.keys(LOCALES) as Locale[]).map((locale) => ({
      locale,
      href: new URL(localePath(locale, Astro.url.pathname), site).href,
    }))
  : []
---

<!doctype html>
<html lang={lang}>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <link rel="canonical" href={canonical.href} />
    {alternates.map((alt) => <link rel="alternate" hreflang={alt.locale} href={alt.href} />)}
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <meta name="theme-color" media="(prefers-color-scheme: light)" content="#fbfbfe" />
    <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0d0e19" />
    <meta property="og:type" content="website" />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:url" content={canonical.href} />
    <meta property="og:image" content={ogImage.href} />
    <meta name="twitter:card" content="summary_large_image" />
    {noindex && <meta name="robots" content="noindex" />}
  </head>
  <body>
    <slot />
  </body>
</html>
```

`site/src/pages/index.astro` (temporary; Task 7 fills it in):

```astro
---
import Layout from "../layouts/Layout.astro"
import { messagesFor } from "../i18n"

const m = messagesFor(Astro.currentLocale)
---

<Layout title={m.meta.title} description={m.meta.description}>
  <main class="container section">
    <h1>{m.hero.title}</h1>
  </main>
</Layout>
```

- [ ] **Step 8: Keep the site out of Docker and Git noise**

Append to `.dockerignore`:

```text
# The landing page deploys separately to Cloudflare and never enters the image.
site
```

Append to `.gitignore`:

```text
# Landing page build and tool output.
site/.astro/
site/.wrangler/
site/test-results/
site/playwright-report/
```

- [ ] **Step 9: Verify the type check and build**

Run (from `site/`): `npm run check && npm run build`
Expected: `astro check` reports 0 errors; `dist/index.html` exists and contains
`Sync your calendars. Keep your privacy.`

Run: `grep -c "Sync your calendars" dist/index.html`
Expected: `1` or more.

- [ ] **Step 10: Commit**

```bash
git add site .dockerignore .gitignore
git commit -m "Scaffold the landing page workspace and its copy"
```

---

### Task 2: Sam's week and event layout

**Files:**
- Create: `site/src/demo/week.ts`, `site/src/demo/layout.ts`
- Test: `site/src/demo/layout.test.ts`

**Interfaces:**
- Consumes: `Messages["demo"]["events"]` keys from Task 1.
- Produces: `type EventKind = "work" | "personal" | "family"`;
  `type EventKey = keyof Messages["demo"]["events"]`;
  `interface DemoEvent { key: EventKey; kind: EventKind; day: number; start: number; end: number }`;
  `SAM_WEEK: readonly DemoEvent[]`; `DAY_START = 9`; `DAY_END = 17`; `DAYS = 5`;
  `interface WeekFrame { heightPx: number; headerPx: number; gapPx: number }`;
  `interface Box { leftPct: number; widthPct: number; topPx: number; heightPx: number }`;
  `eventBox(event: DemoEvent, frame: WeekFrame): Box`; `fitsTwoLines(box: Box): boolean`;
  `TWO_LINE_MIN_PX = 34`.

- [ ] **Step 1: Write the failing test**

`site/src/demo/layout.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { eventBox, fitsTwoLines } from "./layout"
import { SAM_WEEK, type DemoEvent } from "./week"

const FRAME = { heightPx: 380, headerPx: 36, gapPx: 3 }
const event = (overrides: Partial<DemoEvent>): DemoEvent => ({
  key: "standup",
  kind: "work",
  day: 0,
  start: 10,
  end: 11,
  ...overrides,
})

describe("eventBox", () => {
  it("places an hour-long Monday event by its time", () => {
    // (380 - 36) / 8 hours = 43px per hour.
    expect(eventBox(event({}), FRAME)).toEqual({ leftPct: 0, widthPct: 20, topPx: 79, heightPx: 40 })
  })

  it("places Friday in the last fifth", () => {
    expect(eventBox(event({ day: 4, start: 9, end: 9.5 }), FRAME)).toMatchObject({
      leftPct: 80,
      topPx: 36,
    })
  })

  it("keeps every event of Sam's week inside the frame", () => {
    for (const item of SAM_WEEK) {
      const box = eventBox(item, FRAME)
      expect(box.topPx).toBeGreaterThanOrEqual(FRAME.headerPx)
      expect(box.topPx + box.heightPx).toBeLessThanOrEqual(FRAME.heightPx)
    }
  })
})

describe("fitsTwoLines", () => {
  it("shows the detail line only when an event is tall enough", () => {
    expect(fitsTwoLines({ leftPct: 0, widthPct: 20, topPx: 0, heightPx: 40 })).toBe(true)
    expect(fitsTwoLines({ leftPct: 0, widthPct: 20, topPx: 0, heightPx: 20 })).toBe(false)
  })
})

describe("Sam's week", () => {
  it("has work events that stay and personal or family events that cross over", () => {
    expect(SAM_WEEK.filter((item) => item.kind === "work")).toHaveLength(5)
    expect(SAM_WEEK.filter((item) => item.kind !== "work")).toHaveLength(5)
  })

  it("never overlaps two events on the same day", () => {
    for (const a of SAM_WEEK) {
      for (const b of SAM_WEEK) {
        if (a !== b && a.day === b.day) expect(a.end <= b.start || b.end <= a.start).toBe(true)
      }
    }
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- src/demo/layout`
Expected: FAIL, cannot resolve `./layout`.

- [ ] **Step 3: Write the data and the layout math**

`site/src/demo/week.ts`:

```ts
import type { Messages } from "../i18n"

export type EventKind = "work" | "personal" | "family"
export type EventKey = keyof Messages["demo"]["events"]

/** One event in Sam's demo week. `day` 0 is Monday; times are hours, so 9.5 is 9:30. */
export interface DemoEvent {
  key: EventKey
  kind: EventKind
  day: number
  start: number
  end: number
}

export const DAY_START = 9
export const DAY_END = 17
export const DAYS = 5

export const SAM_WEEK: readonly DemoEvent[] = [
  { key: "standup", kind: "work", day: 0, start: 10, end: 11 },
  { key: "clientCall", kind: "work", day: 1, start: 14.5, end: 15.5 },
  { key: "oneOnOne", kind: "work", day: 2, start: 14, end: 15 },
  { key: "designReview", kind: "work", day: 3, start: 9.5, end: 10.5 },
  { key: "retro", kind: "work", day: 4, start: 11, end: 12 },
  { key: "dentist", kind: "personal", day: 0, start: 15, end: 16 },
  { key: "gym", kind: "personal", day: 1, start: 12, end: 13 },
  { key: "schoolDropOff", kind: "family", day: 2, start: 9, end: 10 },
  { key: "therapy", kind: "personal", day: 3, start: 13, end: 14.5 },
  { key: "recital", kind: "family", day: 4, start: 15.5, end: 17 },
]
```

`site/src/demo/layout.ts`:

```ts
import { DAY_END, DAY_START, DAYS, type DemoEvent } from "./week"

export interface WeekFrame {
  heightPx: number
  headerPx: number
  gapPx: number
}

export interface Box {
  leftPct: number
  widthPct: number
  topPx: number
  heightPx: number
}

export const TWO_LINE_MIN_PX = 34

/** Where an event sits in a five-day week whose day header is `headerPx` tall. */
export function eventBox(event: DemoEvent, frame: WeekFrame): Box {
  const hourPx = (frame.heightPx - frame.headerPx) / (DAY_END - DAY_START)
  return {
    leftPct: (event.day * 100) / DAYS,
    widthPct: 100 / DAYS,
    topPx: Math.round(frame.headerPx + (event.start - DAY_START) * hourPx),
    heightPx: Math.round((event.end - event.start) * hourPx - frame.gapPx),
  }
}

export function fitsTwoLines(box: Box): boolean {
  return box.heightPx >= TWO_LINE_MIN_PX
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/demo/layout`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add site/src/demo
git commit -m "Add Sam's demo week and its layout math"
```

---

### Task 3: Ghost mark, week primitives, and motion helpers

**Files:**
- Create: `site/src/islands/GhostMark.tsx`, `site/src/islands/WeekGrid.tsx`,
  `site/src/islands/EventCard.tsx`, `site/src/islands/motion.ts`, `site/src/islands/hooks.ts`
- Test: `site/src/islands/motion.test.ts`
- Modify: `site/src/styles/demos.css`

**Interfaces:**
- Consumes: `Box`, `fitsTwoLines` (Task 2).
- Produces:
  - `GhostMark({ className?, eyes?: { x: number; y: number }, face?: "neutral" | "sleepy" })`
  - `WeekGrid({ days: readonly string[]; children: ReactNode; className?: string })`
  - `type CardLook = "work" | "personal" | "family" | "busy"`;
    `EventCard({ box: Box; look: CardLook; title: string; detail?: string; className?: string })`
  - `REVEAL_REST = 55`; `SWEEP_PERIOD_MS = 10_000`; `clampPercent(p)`; `sweepPercent(ms, periodMs?)`;
    `sweepTimeFor(percent, periodMs?)`; `eyeOffset(dx, dy): { x; y }`;
    `interface LoopConditions { onScreen; pageVisible; reducedMotion; held }`;
    `shouldAnimate(c: LoopConditions): boolean`
  - `useReducedMotion(): boolean`; `useOnScreen(ref): boolean`; `usePageVisible(): boolean`;
    `useAnimationFrame(onFrame: (elapsedMs: number) => void, active: boolean): void`;
    `usePointerEyes(ref): { x: number; y: number }`

- [ ] **Step 1: Write the failing test**

`site/src/islands/motion.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  REVEAL_REST,
  SWEEP_PERIOD_MS,
  clampPercent,
  eyeOffset,
  shouldAnimate,
  sweepPercent,
  sweepTimeFor,
} from "./motion"

describe("sweep", () => {
  it("swings between 12% and 88% around the middle", () => {
    expect(sweepPercent(0)).toBeCloseTo(50)
    expect(sweepPercent(SWEEP_PERIOD_MS / 4)).toBeCloseTo(88)
    expect(sweepPercent((SWEEP_PERIOD_MS * 3) / 4)).toBeCloseTo(12)
  })

  it("resumes from where the visitor left the slider", () => {
    for (const percent of [REVEAL_REST, 20, 70]) {
      expect(sweepPercent(sweepTimeFor(percent))).toBeCloseTo(percent)
    }
  })

  it("resumes from the nearest edge of the swing when left outside it", () => {
    expect(sweepPercent(sweepTimeFor(97))).toBeCloseTo(88)
    expect(sweepPercent(sweepTimeFor(3))).toBeCloseTo(12)
  })

  it("keeps the handle inside the frame", () => {
    expect(clampPercent(-10)).toBe(2)
    expect(clampPercent(140)).toBe(98)
    expect(clampPercent(40)).toBe(40)
  })
})

describe("eyeOffset", () => {
  it("looks straight ahead when the pointer is on the ghost", () => {
    expect(eyeOffset(0, 0)).toEqual({ x: 0, y: 0 })
  })

  it("looks toward the pointer by at most the eye's travel", () => {
    expect(eyeOffset(10, 0)).toEqual({ x: 1.3, y: 0 })
    expect(eyeOffset(0, -400)).toEqual({ x: 0, y: -1.1 })
  })
})

describe("shouldAnimate", () => {
  const running = { onScreen: true, pageVisible: true, reducedMotion: false, held: false }

  it("animates only when nothing stops it", () => {
    expect(shouldAnimate(running)).toBe(true)
    expect(shouldAnimate({ ...running, onScreen: false })).toBe(false)
    expect(shouldAnimate({ ...running, pageVisible: false })).toBe(false)
    expect(shouldAnimate({ ...running, reducedMotion: true })).toBe(false)
    expect(shouldAnimate({ ...running, held: true })).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- src/islands/motion`
Expected: FAIL, cannot resolve `./motion`.

- [ ] **Step 3: Write the motion helpers**

`site/src/islands/motion.ts`:

```ts
export const REVEAL_REST = 55
export const SWEEP_PERIOD_MS = 10_000
const SWEEP_CENTER = 50
const SWEEP_SWING = 38

export function clampPercent(percent: number): number {
  return Math.min(98, Math.max(2, percent))
}

/** The hero slider's position while it sweeps by itself. */
export function sweepPercent(ms: number, periodMs = SWEEP_PERIOD_MS): number {
  return SWEEP_CENTER + SWEEP_SWING * Math.sin((2 * Math.PI * ms) / periodMs)
}

/** The sweep time at which the slider is at `percent`, so a resumed sweep does not jump. */
export function sweepTimeFor(percent: number, periodMs = SWEEP_PERIOD_MS): number {
  const ratio = Math.min(1, Math.max(-1, (percent - SWEEP_CENTER) / SWEEP_SWING))
  return (Math.asin(ratio) / (2 * Math.PI)) * periodMs
}

/** How far the ghost's eyes move toward the pointer, in mark units. */
export function eyeOffset(dx: number, dy: number): { x: number; y: number } {
  const distance = Math.hypot(dx, dy)
  if (distance === 0) return { x: 0, y: 0 }
  return { x: Number(((dx / distance) * 1.3).toFixed(2)), y: Number(((dy / distance) * 1.1).toFixed(2)) }
}

export interface LoopConditions {
  onScreen: boolean
  pageVisible: boolean
  reducedMotion: boolean
  held: boolean
}

export function shouldAnimate(conditions: LoopConditions): boolean {
  return conditions.onScreen && conditions.pageVisible && !conditions.reducedMotion && !conditions.held
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/islands/motion`
Expected: PASS, 7 tests.

- [ ] **Step 5: Write the hooks and components**

`site/src/islands/hooks.ts`:

```ts
import { useEffect, useRef, useState, type RefObject } from "react"
import { eyeOffset } from "./motion"

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener("change", update)
    return () => list.removeEventListener("change", update)
  }, [query])
  return matches
}

export function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)")
}

export function useOnScreen(ref: RefObject<Element | null>): boolean {
  const [onScreen, setOnScreen] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry?.isIntersecting ?? false))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return onScreen
}

export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible")
    update()
    document.addEventListener("visibilitychange", update)
    return () => document.removeEventListener("visibilitychange", update)
  }, [])
  return visible
}

/** Calls `onFrame` with the time since the loop started, on every frame while `active`. */
export function useAnimationFrame(onFrame: (elapsedMs: number) => void, active: boolean): void {
  const callback = useRef(onFrame)
  useEffect(() => {
    callback.current = onFrame
  })
  useEffect(() => {
    if (!active) return
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      callback.current(now - start)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [active])
}

/** Eye offset toward the pointer for the ghost inside `ref`. */
export function usePointerEyes(ref: RefObject<Element | null>): { x: number; y: number } {
  const [eyes, setEyes] = useState({ x: 0, y: 0 })
  useEffect(() => {
    let frame = 0
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const box = ref.current?.getBoundingClientRect()
        if (!box) return
        setEyes(eyeOffset(event.clientX - (box.left + box.width / 2), event.clientY - (box.top + box.height / 2)))
      })
    }
    window.addEventListener("pointermove", onMove, { passive: true })
    return () => {
      window.removeEventListener("pointermove", onMove)
      cancelAnimationFrame(frame)
    }
  }, [ref])
  return eyes
}
```

`site/src/islands/GhostMark.tsx`:

```tsx
// The application's mark (web/src/components/ghost-mark.tsx), with eyes that can look around.
const BODY = "M6 13a6 6 0 0 1 6-6h8a6 6 0 0 1 6 6v11q-2 3-4 0q-2-3-4 0q-2 3-4 0q-2-3-4 0q-2 3-4 0Z"

export type GhostFace = "neutral" | "sleepy"

export function GhostMark({
  className,
  eyes = { x: 0, y: 0 },
  face = "neutral",
}: {
  className?: string
  eyes?: { x: number; y: number }
  face?: GhostFace
}) {
  return (
    <svg className={className} viewBox="0 -1 32 32" fill="none" aria-hidden="true" focusable="false">
      <path d={BODY} fill="var(--brand-glow)" stroke="var(--brand-line)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M12 4.5v4M20 4.5v4" stroke="var(--brand-line)" strokeWidth="2" strokeLinecap="round" />
      {face === "sleepy" ? (
        <path
          d="M11.5 15q1.5 1.6 3 0M17.5 15q1.5 1.6 3 0"
          stroke="var(--brand-eyes)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      ) : (
        <g transform={`translate(${eyes.x} ${eyes.y})`}>
          <circle cx="13" cy="15" r="1.75" fill="var(--brand-eyes)" />
          <circle cx="19" cy="15" r="1.75" fill="var(--brand-eyes)" />
        </g>
      )}
    </svg>
  )
}
```

`site/src/islands/WeekGrid.tsx`:

```tsx
import type { ReactNode } from "react"

/** A Monday-to-Friday frame: day names on top and a dashed line between days. */
export function WeekGrid({
  days,
  children,
  className = "",
}: {
  days: readonly string[]
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`week ${className}`.trim()}>
      <div className="week-days" aria-hidden="true">
        {days.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="week-columns" aria-hidden="true">
        {days.map((day) => (
          <span key={day} />
        ))}
      </div>
      {children}
    </div>
  )
}
```

`site/src/islands/EventCard.tsx`:

```tsx
import { fitsTwoLines, type Box } from "../demo/layout"

export type CardLook = "work" | "personal" | "family" | "busy"

export function EventCard({
  box,
  look,
  title,
  detail,
  className = "",
}: {
  box: Box
  look: CardLook
  title: string
  detail?: string
  className?: string
}) {
  const classes = ["cal-event", `is-${look}`, fitsTwoLines(box) ? "" : "is-short", className]
  return (
    <div
      className={classes.filter(Boolean).join(" ")}
      style={{
        left: `calc(${box.leftPct}% + 4px)`,
        width: `calc(${box.widthPct}% - 8px)`,
        top: box.topPx,
        height: box.heightPx,
      }}
    >
      <span>{title}</span>
      {detail ? <small>{detail}</small> : null}
    </div>
  )
}
```

Append to `site/src/styles/demos.css`:

```css
/* Shared demo pieces: the week frame, event cards, and the ghost's bob. */
.week { position: relative; height: 100%; }
.week-days {
  position: absolute; inset: 0 0 auto 0; height: 36px; display: grid;
  grid-template-columns: repeat(5, 1fr); border-bottom: 1px solid var(--border);
  font-size: 0.75rem; font-weight: 600; color: var(--muted-foreground);
}
.week-days span { padding: 0.55rem 0.65rem; }
.week-columns { position: absolute; inset: 36px 0 0 0; display: grid; grid-template-columns: repeat(5, 1fr); }
.week-columns span + span { border-left: 1px dashed var(--border); }
.cal-event {
  position: absolute; overflow: hidden; border-radius: 6px; padding: 4px 7px;
  font-size: 0.6875rem; font-weight: 600; line-height: 1.3; color: var(--foreground);
  border-left: 3px solid transparent;
  transition: background 450ms var(--ease-out), border-color 450ms var(--ease-out),
    opacity 450ms var(--ease-out), transform 450ms cubic-bezier(0.3, 1.4, 0.5, 1);
}
.cal-event > span, .cal-event > small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cal-event > small { font-weight: 500; font-size: 0.625rem; opacity: 0.75; }
.cal-event.is-short > small { display: none; }
.cal-event.is-work { background: var(--event-work); border-left-color: var(--primary); }
.cal-event.is-personal { background: var(--event-personal); border-left-color: var(--event-personal-edge); }
.cal-event.is-family { background: var(--event-family); border-left-color: var(--event-family-edge); }
.cal-event.is-busy { background: var(--event-busy); border: 1px dashed var(--primary); }
@keyframes ghost-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
.ghost-bob { animation: ghost-bob 1.5s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .ghost-bob { animation: none; }
  .cal-event { transition: none; }
}
```

- [ ] **Step 6: Verify types and tests**

Run: `npm run check && npm test`
Expected: 0 type errors; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add site/src/islands site/src/styles/demos.css
git commit -m "Add the ghost mark, week primitives, and motion helpers"
```

---

### Task 4: The hero, "The Wide Reveal"

**Files:**
- Create: `site/src/islands/WideReveal.tsx`, `site/src/sections/Hero.astro`
- Test: `site/src/islands/WideReveal.test.tsx`
- Modify: `site/src/styles/demos.css`, `site/src/pages/index.astro`

**Interfaces:**
- Consumes: `SAM_WEEK` (Task 2); `eventBox` (Task 2); `GhostMark`, `WeekGrid`, `EventCard`,
  motion helpers, and hooks (Task 3); `format` and `Messages` (Task 1); `REPO_URL` (Task 1).
- Produces: `WideReveal({ m: Messages["demo"] })`; `Hero.astro` with props `{ m: Messages }`;
  CSS custom property `--split` on `.reveal-frame`; the range input
  `role=slider` named `m.demo.sliderLabel`.

- [ ] **Step 1: Write the failing test**

`site/src/islands/WideReveal.test.tsx`:

```tsx
import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { WideReveal } from "./WideReveal"

describe("WideReveal", () => {
  it("renders at rest with both views when JavaScript has not run", () => {
    const html = renderToString(<WideReveal m={en.demo} />)
    expect(html).toContain("--split:55%")
    expect(html).toContain(en.demo.youSee)
    expect(html).toContain(en.demo.workSees)
    // Work sees every personal plan only as Busy, and every work meeting by name.
    expect(html.split(`>${en.demo.busy}<`).length - 1).toBe(5)
    expect(html.split(`>${en.demo.events.standup.title}<`).length - 1).toBe(2)
    expect(html.split(`>${en.demo.events.dentist.title}<`).length - 1).toBe(1)
  })

  describe("in the browser", () => {
    let container: HTMLDivElement
    beforeEach(() => {
      container = document.createElement("div")
      document.body.append(container)
      ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    })
    afterEach(() => container.remove())

    it("holds the position a visitor picks with the slider", async () => {
      const root = createRoot(container)
      await act(async () => root.render(<WideReveal m={en.demo} />))
      const slider = container.querySelector<HTMLInputElement>("input[type=range]")!
      expect(slider.getAttribute("aria-label")).toBe(en.demo.sliderLabel)

      await act(async () => {
        const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!
        setValue.call(slider, "30")
        slider.dispatchEvent(new Event("input", { bubbles: true }))
      })

      const frame = container.querySelector<HTMLElement>(".reveal-frame")!
      expect(frame.style.getPropertyValue("--split")).toBe("30%")
      expect(slider.getAttribute("aria-valuetext")).toBe("30% of the week shows your view")
      await act(async () => root.unmount())
    })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- src/islands/WideReveal`
Expected: FAIL, cannot resolve `./WideReveal`.

- [ ] **Step 3: Write the island**

`site/src/islands/WideReveal.tsx`:

```tsx
import { useRef, useState, type CSSProperties } from "react"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { format } from "../i18n/format"
import { EventCard } from "./EventCard"
import { GhostMark } from "./GhostMark"
import { useAnimationFrame, useOnScreen, usePageVisible, usePointerEyes, useReducedMotion } from "./hooks"
import { REVEAL_REST, clampPercent, shouldAnimate, sweepPercent, sweepTimeFor } from "./motion"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 380, headerPx: 36, gapPx: 3 }
const PLACED = SAM_WEEK.map((event) => ({ event, box: eventBox(event, FRAME) }))

/** The hero: Sam's week as Sam sees it, revealed over what work sees, with the ghost as handle. */
export function WideReveal({ m }: { m: Messages["demo"] }) {
  const frame = useRef<HTMLDivElement>(null)
  const handle = useRef<HTMLDivElement>(null)
  const [held, setHeld] = useState<number | null>(null)
  const [auto, setAuto] = useState(REVEAL_REST)
  const [phase, setPhase] = useState(() => sweepTimeFor(REVEAL_REST))
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(frame)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(handle)
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: held !== null })
  useAnimationFrame((elapsed) => setAuto(sweepPercent(phase + elapsed)), animating)

  const split = Math.round(held ?? auto)
  const release = () => {
    if (held === null) return
    setPhase(sweepTimeFor(held))
    setAuto(held)
    setHeld(null)
  }

  return (
    <figure className="reveal">
      <div ref={frame} className="reveal-frame" style={{ "--split": `${split}%` } as CSSProperties}>
        <div className="reveal-layer reveal-work">
          <WeekGrid days={m.days} className="reveal-week">
            {PLACED.map(({ event, box }) =>
              event.kind === "work" ? (
                <EventCard key={event.key} box={box} look="work" title={m.events[event.key].title} detail={m.events[event.key].detail} />
              ) : (
                <EventCard key={event.key} box={box} look="busy" title={m.busy} />
              ),
            )}
          </WeekGrid>
          <span className="reveal-tag reveal-tag-work">{m.workSees}</span>
        </div>
        <div className="reveal-layer reveal-you">
          <WeekGrid days={m.days} className="reveal-week">
            {PLACED.map(({ event, box }) => (
              <EventCard key={event.key} box={box} look={event.kind} title={m.events[event.key].title} detail={m.events[event.key].detail} />
            ))}
          </WeekGrid>
          <span className="reveal-tag reveal-tag-you">{m.youSee}</span>
        </div>
        <div className="reveal-divider" aria-hidden="true" />
        <div ref={handle} className="reveal-handle" aria-hidden="true">
          <GhostMark className="ghost-bob" eyes={eyes} />
        </div>
        <input
          className="reveal-range"
          type="range"
          min={2}
          max={98}
          step={1}
          value={split}
          aria-label={m.sliderLabel}
          aria-valuetext={format(m.sliderValueText, { percent: split })}
          onChange={(event) => setHeld(clampPercent(Number(event.currentTarget.value)))}
          onPointerMove={(event) => {
            if (event.pointerType !== "mouse" || event.buttons !== 0) return
            const box = event.currentTarget.getBoundingClientRect()
            setHeld(clampPercent(((event.clientX - box.left) / box.width) * 100))
          }}
          onPointerLeave={release}
          onBlur={release}
        />
      </div>
      <figcaption className="sr-only">{m.revealSummary}</figcaption>
      <p className="reveal-hint" aria-hidden="true">
        {m.hint}
      </p>
    </figure>
  )
}
```

Note: a focused slider keeps `held` until blur, so the sweep never takes it back from a keyboard
user. A mouse hover holds the position until the pointer leaves.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/islands/WideReveal`
Expected: PASS, 2 tests.

- [ ] **Step 5: Style the reveal**

Append to `site/src/styles/demos.css`:

```css
/* The Wide Reveal. The top layer shows Sam's view up to --split; below it, what work sees. */
.reveal { margin: 2.5rem 0 0; }
.reveal-frame {
  --split: 55%;
  position: relative; height: 380px; overflow: hidden;
  border: 1px solid var(--border); border-radius: var(--panel-radius); background: var(--surface);
}
.reveal-layer { position: absolute; inset: 0; overflow: hidden; }
.reveal-work { background: var(--surface); }
.reveal-you { background: var(--reveal-you); clip-path: inset(0 calc(100% - var(--split)) 0 0); }
/* On a phone the week is wider than the frame, so Monday to Wednesday fill it. */
.reveal-week { width: 100%; }
@media (max-width: 639px) { .reveal-week { width: calc(100% * 5 / 3); } }
.reveal-tag {
  position: absolute; bottom: 0.6rem; z-index: 2; font-size: 0.75rem; font-weight: 700;
  padding: 0.2rem 0.6rem; border-radius: 999px; background: var(--muted);
}
.reveal-tag-you { left: 0.6rem; }
.reveal-tag-work { right: 0.6rem; }
.reveal-divider {
  position: absolute; top: 0; bottom: 0; left: var(--split); width: 2px; margin-left: -1px; z-index: 3;
  background: var(--brand-line); box-shadow: 0 0 18px color-mix(in oklch, var(--primary), transparent 40%);
}
.reveal-handle {
  position: absolute; top: 50%; left: var(--split); width: 56px; height: 56px; margin: -28px 0 0 -28px;
  z-index: 4; pointer-events: none;
}
.reveal-handle svg { width: 100%; height: 100%; overflow: visible; }
/* The real control: a transparent range input over the whole frame, for mouse, touch, and keys. */
.reveal-range {
  position: absolute; inset: 0; z-index: 5; width: 100%; height: 100%; margin: 0;
  opacity: 0; cursor: ew-resize; touch-action: pan-y;
}
.reveal-range::-webkit-slider-thumb { -webkit-appearance: none; width: 56px; height: 380px; }
.reveal-range::-moz-range-thumb { width: 56px; height: 380px; border: 0; }
.reveal-frame:has(.reveal-range:focus-visible) { outline: 2px solid var(--ring); outline-offset: 3px; }
.reveal-hint { text-align: center; font-size: 0.8125rem; color: var(--muted-foreground); margin-top: 0.6rem; }
```

- [ ] **Step 6: Write the hero section and show it on the page**

`site/src/sections/Hero.astro`:

```astro
---
import { WideReveal } from "../islands/WideReveal"
import type { Messages } from "../i18n"
import { REPO_URL } from "../links"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section class="hero section">
  <div class="container hero-copy">
    <p class="chip">{m.hero.chip}</p>
    <h1>{m.hero.title}</h1>
    <p class="lead">{m.hero.sub}</p>
    <div class="ctas">
      <a class="btn btn-primary" href="#self-host">{m.hero.primary}</a>
      <a class="btn" href={REPO_URL}><span aria-hidden="true">★</span> {m.hero.secondary}</a>
    </div>
  </div>
  <div class="container">
    <WideReveal client:load m={m.demo} />
  </div>
</section>

<style>
  .hero { padding-top: clamp(2.5rem, 6vw, 5rem); }
  .hero-copy { text-align: center; display: flex; flex-direction: column; align-items: center; }
  .hero-copy .lead { margin-inline: auto; }
  .hero-copy .ctas { justify-content: center; }
</style>
```

Replace the `<main>` in `site/src/pages/index.astro` with:

```astro
<main>
  <Hero m={m} />
</main>
```

and add `import Hero from "../sections/Hero.astro"` to its frontmatter.

- [ ] **Step 7: Check it in a browser**

Run: `npm run dev`, open `http://localhost:4321`.
Expected: the ghost sweeps across the week; work meetings look the same on both sides; personal
plans turn into "Busy" on the work side; hovering holds the position; Tab focuses the frame and
arrow keys move it. Check light and dark (system setting) and a 390px-wide window (Monday to
Wednesday fill the frame).

- [ ] **Step 8: Commit**

```bash
git add site/src
git commit -m "Add the Wide Reveal hero"
```

---

### Task 5: "One week, every calendar" with The Haunted Week

**Files:**
- Create: `site/src/demo/haunted.ts`, `site/src/islands/HauntedWeek.tsx`, `site/src/sections/Week.astro`
- Test: `site/src/demo/haunted.test.ts`
- Modify: `site/src/styles/demos.css`, `site/src/pages/index.astro`

**Interfaces:**
- Consumes: `SAM_WEEK`, `eventBox` (Task 2); `WeekGrid`, `EventCard`, `GhostMark`, hooks,
  `shouldAnimate` (Task 3).
- Produces: `HAUNTED_PERIOD_MS = 9000`; `HAUNTED_STILL_MS = 8000`;
  `interface HauntedFrame { ghost: { xPct: number; yPct: number; visible: boolean }; shown: boolean[]; busy: boolean[]; fading: boolean }`;
  `hauntedFrame(ms: number, incomingDays: readonly number[]): HauntedFrame`;
  `HauntedWeek({ m: Messages["demo"] })`; `Week.astro` with props `{ m: Messages }`.

- [ ] **Step 1: Write the failing test**

`site/src/demo/haunted.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { HAUNTED_PERIOD_MS, HAUNTED_STILL_MS, hauntedFrame } from "./haunted"

const DAYS = [0, 1, 2, 3, 4]

describe("hauntedFrame", () => {
  it("starts empty, with the ghost out of sight", () => {
    const frame = hauntedFrame(0, DAYS)
    expect(frame.shown).toEqual([false, false, false, false, false])
    expect(frame.busy).toEqual([false, false, false, false, false])
    expect(frame.ghost.visible).toBe(false)
  })

  it("slides every event in before the ghost arrives", () => {
    const frame = hauntedFrame(1000, DAYS)
    expect(frame.shown).toEqual([true, true, true, true, true])
    expect(frame.busy.some(Boolean)).toBe(false)
  })

  it("turns an event into Busy once the ghost has passed its day", () => {
    const frame = hauntedFrame(4000, DAYS)
    expect(frame.ghost.visible).toBe(true)
    expect(frame.busy).toEqual([true, true, false, false, false])
  })

  it("rests with every event Busy and nothing fading", () => {
    const frame = hauntedFrame(HAUNTED_STILL_MS, DAYS)
    expect(frame.busy).toEqual([true, true, true, true, true])
    expect(frame.fading).toBe(false)
    expect(frame.ghost.visible).toBe(false)
  })

  it("fades out at the end and repeats", () => {
    expect(hauntedFrame(8600, DAYS).fading).toBe(true)
    expect(hauntedFrame(HAUNTED_PERIOD_MS + 1000, DAYS)).toEqual(hauntedFrame(1000, DAYS))
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- src/demo/haunted`
Expected: FAIL, cannot resolve `./haunted`.

- [ ] **Step 3: Write the timeline**

`site/src/demo/haunted.ts`:

```ts
export const HAUNTED_PERIOD_MS = 9000
/** The moment shown when nothing animates: every incoming event already Busy. */
export const HAUNTED_STILL_MS = 8000

export interface HauntedFrame {
  ghost: { xPct: number; yPct: number; visible: boolean }
  shown: boolean[]
  busy: boolean[]
  fading: boolean
}

/** The Haunted Week at `ms`. `incomingDays` is the day of each event that crosses over. */
export function hauntedFrame(ms: number, incomingDays: readonly number[]): HauntedFrame {
  const t = ((ms % HAUNTED_PERIOD_MS) + HAUNTED_PERIOD_MS) % HAUNTED_PERIOD_MS
  const progress = Math.min(1, Math.max(0, (t - 1700) / 5200))
  const xPct = progress * 112 - 6
  return {
    ghost: { xPct, yPct: 52 + 26 * Math.sin((xPct / 100) * Math.PI * 3), visible: t >= 1500 && t <= 7300 },
    shown: incomingDays.map((_, index) => t > 200 + index * 170),
    busy: incomingDays.map((day) => xPct > day * 20 + 10),
    fading: t > 8500,
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/demo/haunted`
Expected: PASS, 5 tests.

- [ ] **Step 5: Write the island and the section**

`site/src/islands/HauntedWeek.tsx`:

```tsx
import { useRef, useState } from "react"
import { HAUNTED_STILL_MS, hauntedFrame } from "../demo/haunted"
import { eventBox } from "../demo/layout"
import { SAM_WEEK } from "../demo/week"
import type { Messages } from "../i18n"
import { EventCard } from "./EventCard"
import { GhostMark } from "./GhostMark"
import { useAnimationFrame, useOnScreen, usePageVisible, useReducedMotion } from "./hooks"
import { shouldAnimate } from "./motion"
import { WeekGrid } from "./WeekGrid"

const FRAME = { heightPx: 360, headerPx: 36, gapPx: 3 }
const WORK = SAM_WEEK.filter((event) => event.kind === "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING = SAM_WEEK.filter((event) => event.kind !== "work").map((event) => ({ event, box: eventBox(event, FRAME) }))
const INCOMING_DAYS = INCOMING.map(({ event }) => event.day)

export function HauntedWeek({ m }: { m: Messages["demo"] }) {
  const root = useRef<HTMLDivElement>(null)
  const [ms, setMs] = useState(HAUNTED_STILL_MS)
  const reducedMotion = useReducedMotion()
  const onScreen = useOnScreen(root)
  const pageVisible = usePageVisible()
  const animating = shouldAnimate({ onScreen, pageVisible, reducedMotion, held: false })
  useAnimationFrame(setMs, animating)
  const frame = hauntedFrame(animating ? ms : HAUNTED_STILL_MS, INCOMING_DAYS)

  return (
    <figure className="haunt">
      <div ref={root} className="haunt-frame" aria-hidden="true">
        <WeekGrid days={m.days}>
          {WORK.map(({ event, box }) => (
            <EventCard key={event.key} box={box} look="work" title={m.events[event.key].title} detail={m.events[event.key].detail} />
          ))}
          {INCOMING.map(({ event, box }, index) => {
            const busy = frame.busy[index]
            const state = [frame.shown[index] ? "is-shown" : "is-arriving", busy ? "is-settled" : "", frame.fading ? "is-fading" : ""]
            return (
              <EventCard
                key={event.key}
                box={box}
                look={busy ? "busy" : event.kind}
                title={busy ? m.busy : m.events[event.key].title}
                detail={busy ? undefined : m.from[event.kind === "family" ? "family" : "personal"]}
                className={state.filter(Boolean).join(" ")}
              />
            )
          })}
        </WeekGrid>
        <div
          className="haunt-ghost"
          style={{ left: `${frame.ghost.xPct}%`, top: `${frame.ghost.yPct}%`, opacity: frame.ghost.visible ? 1 : 0 }}
        >
          <GhostMark />
        </div>
        <span className="haunt-label">{m.workCalendar}</span>
      </div>
    </figure>
  )
}
```

Append to `site/src/styles/demos.css`:

```css
/* The Haunted Week. */
.haunt { margin: 2rem 0 0; }
.haunt-frame {
  position: relative; height: 360px; overflow: hidden;
  border: 1px solid var(--border); border-radius: var(--panel-radius); background: var(--surface);
}
.haunt .cal-event.is-arriving { opacity: 0; transform: translateX(-14px); }
.haunt .cal-event.is-fading { opacity: 0; }
.haunt-ghost {
  position: absolute; width: 44px; height: 44px; margin: -22px 0 0 -22px; z-index: 3;
  filter: drop-shadow(0 0 14px color-mix(in oklch, var(--primary), transparent 50%));
  transition: opacity 300ms var(--ease-out);
}
.haunt-ghost svg { width: 100%; height: 100%; }
.haunt-label { position: absolute; right: 0.7rem; bottom: 0.5rem; font-size: 0.75rem; color: var(--muted-foreground); }
@media (max-width: 639px) { .haunt-frame .week { width: calc(100% * 5 / 3); } }
```

`site/src/sections/Week.astro`:

```astro
---
import { HauntedWeek } from "../islands/HauntedWeek"
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section class="section" aria-labelledby="week-title">
  <div class="container">
    <h2 id="week-title">{m.week.title}</h2>
    <p class="lead">{m.week.body}</p>
    <p class="sr-only">{m.week.summary}</p>
    <HauntedWeek client:visible m={m.demo} />
  </div>
</section>
```

Add `<Week m={m} />` after `<Hero m={m} />` in `index.astro` (Task 7 inserts How it works between
them), with its import.

- [ ] **Step 6: Check it in a browser**

Run: `npm run dev`.
Expected: personal and family events slide in tagged "from Personal" or "from Family", the ghost
flies across, each turns into "Busy" as it passes, work meetings never change, and the loop
repeats. With reduced motion on, every incoming event is already "Busy" and nothing moves.

- [ ] **Step 7: Commit**

```bash
git add site/src
git commit -m "Add the Haunted Week section"
```

---

### Task 6: "You choose what crosses over" with The Crossing

**Files:**
- Create: `site/src/demo/crossing.ts`, `site/src/islands/Crossing.tsx`, `site/src/sections/CrossingSection.astro`
- Test: `site/src/demo/crossing.test.ts`, `site/src/islands/Crossing.test.tsx`
- Modify: `site/src/styles/demos.css`, `site/src/pages/index.astro`

**Interfaces:**
- Consumes: `GhostMark`, `useOnScreen`, `usePageVisible`, `usePointerEyes` (Task 3); `Messages` (Task 1).
- Produces: `type CrossingMode = "busy" | "details"`;
  `interface CrossingFields { title: boolean; location: boolean; guests: boolean; link: boolean }`;
  `crossingFields(mode: CrossingMode): CrossingFields`;
  `Crossing({ m: Pick<Messages, "crossing" | "demo"> })`; `CrossingSection.astro` with props `{ m: Messages }`.

- [ ] **Step 1: Write the failing tests**

`site/src/demo/crossing.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { crossingFields } from "./crossing"

describe("crossingFields", () => {
  it("lets only the time cross over with Busy only", () => {
    expect(crossingFields("busy")).toEqual({ title: false, location: false, guests: false, link: false })
  })

  it("adds title and place with details, never guests or meeting links", () => {
    expect(crossingFields("details")).toEqual({ title: true, location: true, guests: false, link: false })
  })
})
```

`site/src/islands/Crossing.test.tsx`:

```tsx
import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { Crossing } from "./Crossing"

describe("Crossing", () => {
  it("switches between Busy only and With details", async () => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement("div")
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(<Crossing m={{ crossing: en.crossing, demo: en.demo }} />))

    const [busy, details] = Array.from(container.querySelectorAll("button"))
    expect(busy?.getAttribute("aria-pressed")).toBe("true")
    expect(container.textContent).toContain(en.crossing.busyOnlyBody)

    await act(async () => details?.click())
    expect(details?.getAttribute("aria-pressed")).toBe("true")
    expect(container.querySelector(".crossing")?.getAttribute("data-mode")).toBe("details")
    expect(container.textContent).toContain(en.crossing.withDetailsBody)

    await act(async () => root.unmount())
    container.remove()
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- crossing Crossing`
Expected: FAIL, cannot resolve `./crossing` and `./Crossing`.

- [ ] **Step 3: Write the fields rule and the island**

`site/src/demo/crossing.ts`:

```ts
export type CrossingMode = "busy" | "details"

export interface CrossingFields {
  title: boolean
  location: boolean
  guests: boolean
  link: boolean
}

/** What reaches the destination: Busy-Only Projection or Details Projection (CONTEXT.md). */
export function crossingFields(mode: CrossingMode): CrossingFields {
  const details = mode === "details"
  return { title: details, location: details, guests: false, link: false }
}
```

`site/src/islands/Crossing.tsx`:

```tsx
import { useRef, useState } from "react"
import { crossingFields, type CrossingMode } from "../demo/crossing"
import type { Messages } from "../i18n"
import { GhostMark } from "./GhostMark"
import { useOnScreen, usePageVisible, usePointerEyes } from "./hooks"

const HOURS = ["14:00", "15:00", "16:00", "17:00"]
const MODES: readonly CrossingMode[] = ["busy", "details"]

function fieldClass(stays: boolean): string {
  return stays ? "crossing-field" : "crossing-field crossing-fades"
}

/** One event carried by the ghost from Personal to Work; the switch picks what crosses over. */
export function Crossing({ m }: { m: Pick<Messages, "crossing" | "demo"> }) {
  const stage = useRef<HTMLDivElement>(null)
  const carrier = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<CrossingMode>("busy")
  const onScreen = useOnScreen(stage)
  const pageVisible = usePageVisible()
  const eyes = usePointerEyes(carrier)
  const fields = crossingFields(mode)
  const dentist = m.demo.events.dentist

  return (
    <div className="crossing" data-mode={mode} data-playing={onScreen && pageVisible ? "true" : "false"}>
      <div className="crossing-controls">
        <div className="crossing-switch" role="group" aria-label={m.crossing.switchLabel}>
          {MODES.map((option) => (
            <button key={option} type="button" aria-pressed={mode === option} onClick={() => setMode(option)}>
              {option === "busy" ? m.crossing.busyOnly : m.crossing.withDetails}
            </button>
          ))}
        </div>
        <p className="crossing-explain" aria-live="polite">
          {mode === "busy" ? m.crossing.busyOnlyBody : m.crossing.withDetailsBody}
        </p>
      </div>
      <div ref={stage} className="crossing-stage" aria-hidden="true">
        {(["personal", "work"] as const).map((calendar) => (
          <div key={calendar} className={`crossing-cal crossing-${calendar}`}>
            <header>{m.demo.calendars[calendar]}</header>
            {HOURS.map((hour) => (
              <div key={hour} className="crossing-row">
                {hour}
              </div>
            ))}
            {calendar === "personal" ? (
              <div className="cal-event is-personal crossing-original">
                <span>{dentist.title}</span>
              </div>
            ) : (
              <div className="cal-event is-work crossing-existing">
                <span>{m.demo.events.clientCall.title}</span>
              </div>
            )}
          </div>
        ))}
        <div key={mode} className="crossing-traveler">
          <div className="cal-event crossing-card">
            <span className={fieldClass(fields.title)}>{dentist.title}</span>
            {fields.title ? null : <span className="crossing-busy">{m.demo.busy}</span>}
            <span className="crossing-chips">
              <small className={fieldClass(fields.location)}>{dentist.detail}</small>
              <small className={fieldClass(fields.guests)}>{m.crossing.guests}</small>
              <small className={fieldClass(fields.link)}>{m.crossing.link}</small>
            </span>
          </div>
          <div ref={carrier} className="crossing-carrier">
            <GhostMark className="ghost-bob" eyes={eyes} />
          </div>
        </div>
      </div>
      <p className="sr-only">{m.crossing.summary}</p>
    </div>
  )
}
```

`key={mode}` on the traveler restarts its animation when the visitor flips the switch.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- crossing Crossing`
Expected: PASS, 3 tests.

- [ ] **Step 5: Style and animate the crossing**

Append to `site/src/styles/demos.css`:

```css
/* The Crossing: a 7-second loop. Details that do not cross over fade out with the event's other
   information as it travels; nothing falls. */
.crossing { display: grid; gap: 1.5rem; }
.crossing-switch {
  display: inline-flex; padding: 3px; border: 1px solid var(--border); border-radius: 999px; background: var(--surface);
}
.crossing-switch button {
  all: unset; cursor: pointer; padding: 0.4rem 0.9rem; border-radius: 999px;
  font-size: 0.875rem; font-weight: 600; color: var(--muted-foreground);
}
.crossing-switch button[aria-pressed="true"] { background: var(--muted); color: var(--foreground); }
.crossing-switch button:focus-visible { outline: 2px solid var(--ring); }
.crossing-explain { margin: 0.6rem 0 0; color: var(--muted-foreground); }
.crossing-stage { position: relative; height: 300px; }
.crossing-cal {
  position: absolute; top: 0; width: 42%; height: 100%; overflow: hidden;
  border: 1px solid var(--border); border-radius: 12px; background: var(--surface);
}
.crossing-personal { left: 0; }
.crossing-work { right: 0; }
.crossing-cal header {
  font-size: 0.75rem; font-weight: 600; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border);
}
.crossing-row {
  height: 60px; padding: 3px 8px; font-size: 0.625rem; color: var(--muted-foreground);
  border-bottom: 1px dashed var(--border);
}
.crossing-original, .crossing-existing { left: 44px; right: 8px; height: 54px; }
.crossing-original { top: 98px; }
.crossing-existing { top: 38px; }
.crossing-traveler {
  position: absolute; left: 0; top: 0; width: 42%; height: 100%; pointer-events: none;
  animation: crossing-move 7s cubic-bezier(0.45, 0, 0.25, 1) infinite;
}
.crossing-card {
  left: 44px; right: 8px; top: 98px; height: 54px;
  background: var(--event-personal); border-left-color: var(--event-personal-edge);
  animation: crossing-tint 7s infinite;
}
.crossing-busy { position: absolute; left: 7px; top: 4px; opacity: 0; animation: crossing-busy 7s infinite; }
.crossing-chips > small {
  display: inline-block; margin: 3px 3px 0 0; padding: 1px 5px; border-radius: 4px;
  background: color-mix(in oklch, var(--background), transparent 30%); font-size: 0.625rem; font-weight: 500;
}
.crossing-fades { animation: crossing-fade 7s infinite; }
.crossing-carrier { position: absolute; left: 62%; top: 52px; width: 46px; height: 46px; animation: crossing-carry 7s infinite; }
.crossing-carrier svg { width: 100%; height: 100%; }
.crossing[data-playing="false"] .crossing-traveler,
.crossing[data-playing="false"] .crossing-traveler * { animation-play-state: paused; }
@keyframes crossing-move {
  0%, 6% { transform: translate(0, 0); opacity: 0; }
  12% { transform: translate(0, 0); opacity: 1; }
  22% { transform: translate(0, -34px); }
  62% { transform: translate(138.1%, -34px); }
  72%, 92% { transform: translate(138.1%, 0); opacity: 1; }
  100% { transform: translate(138.1%, 0); opacity: 0; }
}
@keyframes crossing-carry {
  0%, 8% { opacity: 0; transform: translateY(-10px); }
  14%, 72% { opacity: 1; transform: translateY(0); }
  84%, 100% { opacity: 0; transform: translate(20px, -40px); }
}
@keyframes crossing-tint {
  0%, 52% { background: var(--event-personal); border-left-color: var(--event-personal-edge); }
  64%, 100% { background: var(--event-busy); border-left-color: var(--primary); }
}
@keyframes crossing-fade { 0%, 40% { opacity: 1; } 58%, 100% { opacity: 0; } }
@keyframes crossing-busy { 0%, 56% { opacity: 0; } 64%, 100% { opacity: 1; } }
@media (max-width: 639px) {
  .crossing-cal { width: 47%; }
  .crossing-traveler { width: 47%; }
  @keyframes crossing-move {
    0%, 6% { transform: translate(0, 0); opacity: 0; }
    12% { transform: translate(0, 0); opacity: 1; }
    22% { transform: translate(0, -34px); }
    62% { transform: translate(112.8%, -34px); }
    72%, 92% { transform: translate(112.8%, 0); opacity: 1; }
    100% { transform: translate(112.8%, 0); opacity: 0; }
  }
}
/* Reduced motion: show where the event lands, with what crossed over. */
@media (prefers-reduced-motion: reduce) {
  .crossing-traveler, .crossing-traveler * { animation: none !important; }
  .crossing-traveler { transform: translate(138.1%, 0); }
  .crossing-card { background: var(--event-busy); border-left-color: var(--primary); }
  .crossing-fades { opacity: 0; }
  .crossing-busy { opacity: 1; }
  .crossing-carrier { opacity: 0; }
}
@media (prefers-reduced-motion: reduce) and (max-width: 639px) {
  .crossing-traveler { transform: translate(112.8%, 0); }
}
```

(138.1% = 58/42 of the traveler's width; 112.8% = 53/47 on phones.)

`site/src/sections/CrossingSection.astro`:

```astro
---
import { Crossing } from "../islands/Crossing"
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section class="section" aria-labelledby="crossing-title">
  <div class="container crossing-section">
    <div>
      <h2 id="crossing-title">{m.crossing.title}</h2>
      <h3>{m.crossing.alwaysStaysTitle}</h3>
      <ul class="stays">
        {m.crossing.alwaysStays.map((item) => <li>{item}</li>)}
      </ul>
    </div>
    <Crossing client:visible m={{ crossing: m.crossing, demo: m.demo }} />
  </div>
</section>

<style>
  .crossing-section { display: grid; gap: 2.5rem; }
  @media (min-width: 960px) { .crossing-section { grid-template-columns: 1fr 1.6fr; align-items: start; } }
  .stays { margin: 0; padding-left: 1.1rem; color: var(--muted-foreground); }
</style>
```

Add `<CrossingSection m={m} />` after `<Week m={m} />` in `index.astro`, with its import.

- [ ] **Step 6: Check it in a browser**

Run: `npm run dev`.
Expected: with Busy only, the title, place, guests, and meeting link fade out together while the
ghost carries the event, and it lands as "Busy". With details, the title and place stay; only the
guests and meeting link fade. Flipping the switch restarts the loop. Reduced motion shows the
landed result. Check a 390px-wide window.

- [ ] **Step 7: Commit**

```bash
git add site/src
git commit -m "Add the Crossing section"
```

---

### Task 7: The remaining sections and the full page

**Files:**
- Create: `site/src/content/self-host.ts`, `site/src/sections/Nav.astro`,
  `site/src/sections/LanguagePicker.astro`, `site/src/sections/HowItWorks.astro`,
  `site/src/sections/AppShots.astro`, `site/src/sections/Trust.astro`,
  `site/src/sections/SelfHost.astro`, `site/src/sections/Why.astro`, `site/src/sections/Faq.astro`,
  `site/src/sections/Footer.astro`
- Test: `site/src/content/self-host.test.ts`
- Modify: `site/src/pages/index.astro`

**Interfaces:**
- Consumes: `Messages`, `LOCALES`, `hasLanguagePicker`, `localePath` (Task 1); links (Task 1);
  `GhostMark` (Task 3); `Hero`, `Week`, `CrossingSection` (Tasks 4 to 6).
- Produces: `SELF_HOST_COMMANDS: readonly string[]`; section ids `how-it-works`, `features`,
  `self-host`; copy buttons `button[data-copy]` targeting `code#self-host-command-<n>`.

- [ ] **Step 1: Write the failing test**

`site/src/content/self-host.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { REPO_URL } from "../links"
import { SELF_HOST_COMMANDS } from "./self-host"

const README = readFileSync(new URL("../../../README.md", import.meta.url), "utf8")

describe("self-host commands", () => {
  it("clone this repository", () => {
    expect(SELF_HOST_COMMANDS[0]).toBe(`git clone ${REPO_URL}.git && cd calendar-ghost`)
  })

  it("match the README's quick start, so the page never drifts from it", () => {
    for (const command of SELF_HOST_COMMANDS.slice(1)) expect(README).toContain(command)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- src/content`
Expected: FAIL, cannot resolve `./self-host`.

- [ ] **Step 3: Write the commands**

`site/src/content/self-host.ts`:

```ts
import { REPO_URL } from "../links"

/** The steps that are true today: there is no published image yet (see the spec). */
export const SELF_HOST_COMMANDS = [
  `git clone ${REPO_URL}.git && cd calendar-ghost`,
  "cp .env.example .env",
  "docker compose up -d --build",
] as const
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- src/content`
Expected: PASS, 2 tests.

- [ ] **Step 5: Write the sections**

`site/src/sections/LanguagePicker.astro`:

```astro
---
import { LOCALES, hasLanguagePicker, localePath, type Locale, type Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
const locales = Object.keys(LOCALES) as Locale[]
const path = Astro.url.pathname
---

{
  hasLanguagePicker() && (
    <nav aria-label={m.nav.language}>
      <ul class="languages">
        {locales.map((locale) => (
          <li>
            <a href={localePath(locale, path)} hreflang={locale} lang={locale}>
              {locale.toUpperCase()}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
```

`site/src/sections/Nav.astro`:

```astro
---
import { GhostMark } from "../islands/GhostMark"
import type { Messages } from "../i18n"
import { REPO_URL } from "../links"
import LanguagePicker from "./LanguagePicker.astro"

interface Props {
  m: Messages
}

const { m } = Astro.props
const links = [
  { href: "#how-it-works", label: m.nav.howItWorks },
  { href: "#features", label: m.nav.features },
  { href: "#self-host", label: m.nav.selfHost },
]
---

<header class="nav">
  <div class="container nav-inner">
    <a class="nav-brand" href="/" aria-label={m.nav.home}>
      <GhostMark className="nav-mark" />
      <span>Calendar Ghost</span>
    </a>
    <nav class="nav-links" aria-label={m.nav.label}>
      <ul class="nav-wide">
        {links.map((link) => <li><a href={link.href}>{link.label}</a></li>)}
      </ul>
      <details class="nav-narrow">
        <summary>{m.nav.menu}</summary>
        <ul>
          {links.map((link) => <li><a href={link.href}>{link.label}</a></li>)}
        </ul>
      </details>
      <LanguagePicker m={m} />
      <a class="btn btn-small" href={REPO_URL}><span aria-hidden="true">★</span> {m.nav.star}</a>
    </nav>
  </div>
</header>

<style>
  .nav { position: sticky; top: 0; z-index: 10; background: color-mix(in oklch, var(--background), transparent 12%); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); }
  .nav-inner { display: flex; align-items: center; justify-content: space-between; min-height: 4rem; gap: 1rem; }
  .nav-brand { display: flex; align-items: center; gap: 0.5rem; color: var(--foreground); text-decoration: none; font-weight: 650; }
  .nav-brand :global(.nav-mark) { width: 28px; height: 28px; }
  .nav-links { display: flex; align-items: center; gap: 1rem; }
  .nav-links ul { list-style: none; margin: 0; padding: 0; }
  .nav-wide { display: flex; gap: 1.25rem; }
  .nav-links a:not(.btn) { color: var(--muted-foreground); text-decoration: none; font-weight: 600; font-size: 0.9375rem; }
  .nav-links a:not(.btn):hover { color: var(--foreground); }
  .nav-narrow { display: none; position: relative; }
  .nav-narrow summary { cursor: pointer; font-weight: 600; list-style: none; }
  .nav-narrow ul { position: absolute; right: 0; top: 2rem; padding: 0.75rem 1rem; display: grid; gap: 0.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); min-width: 12rem; }
  @media (max-width: 719px) {
    .nav-wide { display: none; }
    .nav-narrow { display: block; }
  }
</style>
```

`site/src/sections/HowItWorks.astro`:

```astro
---
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section id="how-it-works" class="section" aria-labelledby="how-title">
  <div class="container">
    <h2 id="how-title">{m.how.title}</h2>
    <ol class="steps">
      {
        m.how.steps.map((step, index) => (
          <li>
            <span class="step-number" aria-hidden="true">{index + 1}</span>
            <h3>{step.title}</h3>
            <p>{step.body}</p>
          </li>
        ))
      }
    </ol>
  </div>
</section>

<style>
  .steps { list-style: none; margin: 2rem 0 0; padding: 0; display: grid; gap: 1.5rem; }
  @media (min-width: 840px) { .steps { grid-template-columns: repeat(3, 1fr); } }
  .steps li { padding: 1.5rem; border: 1px solid var(--border); border-radius: var(--panel-radius); background: var(--surface); }
  .steps p { color: var(--muted-foreground); margin: 0; }
  .step-number { display: inline-grid; place-items: center; width: 2rem; height: 2rem; margin-bottom: 0.75rem; border-radius: 999px; background: var(--primary-soft); color: var(--primary); font-weight: 700; }
</style>
```

`site/src/sections/AppShots.astro`:

```astro
---
import { getImage } from "astro:assets"
import activityDark from "../../../docs/assets/calendar-ghost-activity-dark.png"
import activityLight from "../../../docs/assets/calendar-ghost-activity-light.png"
import overviewDark from "../../../docs/assets/calendar-ghost-overview-dark.png"
import overviewLight from "../../../docs/assets/calendar-ghost-overview-light.png"
import rulesDark from "../../../docs/assets/calendar-ghost-rules-dark.png"
import rulesLight from "../../../docs/assets/calendar-ghost-rules-light.png"
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
const sources = [
  { key: "overview", light: overviewLight, dark: overviewDark },
  { key: "rules", light: rulesLight, dark: rulesDark },
  { key: "activity", light: activityLight, dark: activityDark },
] as const
const shots = await Promise.all(
  sources.map(async (source) => ({
    copy: m.app[source.key],
    light: await getImage({ src: source.light, format: "webp", width: 1200 }),
    dark: await getImage({ src: source.dark, format: "webp", width: 1200 }),
  })),
)
---

<section class="section" aria-labelledby="app-title">
  <div class="container">
    <h2 id="app-title">{m.app.title}</h2>
    <p class="lead">{m.app.body}</p>
    <div class="shots">
      {
        shots.map((shot) => (
          <figure>
            <picture>
              <source media="(prefers-color-scheme: dark)" srcset={shot.dark.src} />
              <img
                src={shot.light.src}
                width={shot.light.attributes.width}
                height={shot.light.attributes.height}
                alt={shot.copy.alt}
                loading="lazy"
                decoding="async"
              />
            </picture>
            <figcaption>{shot.copy.caption}</figcaption>
          </figure>
        ))
      }
    </div>
  </div>
</section>

<style>
  .shots { display: grid; gap: 2rem; margin-top: 2rem; }
  @media (min-width: 960px) { .shots { grid-template-columns: 1fr 1fr; } .shots figure:first-child { grid-column: 1 / -1; } }
  figure { margin: 0; }
  img { display: block; width: 100%; height: auto; border: 1px solid var(--border); border-radius: var(--panel-radius); }
  figcaption { margin-top: 0.6rem; color: var(--muted-foreground); font-size: 0.9375rem; }
</style>
```

`site/src/sections/Trust.astro`:

```astro
---
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section id="features" class="section" aria-labelledby="trust-title">
  <div class="container">
    <h2 id="trust-title">{m.trust.title}</h2>
    <ul class="cards">
      {
        m.trust.cards.map((card) => (
          <li>
            <h3>{card.title}</h3>
            <p>{card.body}</p>
          </li>
        ))
      }
    </ul>
  </div>
</section>

<style>
  .cards { list-style: none; margin: 2rem 0 0; padding: 0; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }
  .cards li { padding: 1.25rem; border: 1px solid var(--border); border-radius: var(--panel-radius); background: var(--surface); }
  .cards p { margin: 0; color: var(--muted-foreground); font-size: 0.9375rem; }
</style>
```

`site/src/sections/SelfHost.astro`:

```astro
---
import { SELF_HOST_COMMANDS } from "../content/self-host"
import type { Messages } from "../i18n"
import { GUIDE_URL } from "../links"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section id="self-host" class="section" aria-labelledby="self-host-title">
  <div class="container self-host">
    <div>
      <h2 id="self-host-title">{m.selfHost.title}</h2>
      <p class="lead">{m.selfHost.body}</p>
      <h3>{m.selfHost.needsTitle}</h3>
      <ul class="needs">{m.selfHost.needs.map((need) => <li>{need}</li>)}</ul>
    </div>
    <div>
      <h3>{m.selfHost.stepsTitle}</h3>
      <ol class="commands">
        {
          SELF_HOST_COMMANDS.map((command, index) => (
            <li>
              <p>{m.selfHost.steps[index]}</p>
              <div class="command">
                <code id={`self-host-command-${index}`}>{command}</code>
                <button
                  type="button"
                  class="btn btn-small"
                  hidden
                  data-copy={`self-host-command-${index}`}
                  data-label={m.selfHost.copy}
                  data-copied={m.selfHost.copied}
                  data-selected={m.selfHost.selected}
                >
                  {m.selfHost.copy}
                </button>
              </div>
            </li>
          ))
        }
      </ol>
      <p class="note">{m.selfHost.oauthNote}</p>
      <a class="btn btn-primary" href={GUIDE_URL}>{m.selfHost.guide}</a>
    </div>
  </div>
</section>

<script>
  // Copy buttons appear only with JavaScript. Without the Clipboard API (plain HTTP on a LAN,
  // older browsers) the command is selected so the visitor can copy it by hand.
  for (const button of document.querySelectorAll<HTMLButtonElement>("button[data-copy]")) {
    button.hidden = false
    button.addEventListener("click", async () => {
      const code = document.getElementById(button.dataset.copy ?? "")
      if (!code) return
      try {
        await navigator.clipboard.writeText(code.textContent ?? "")
        button.textContent = button.dataset.copied ?? ""
      } catch {
        const range = document.createRange()
        range.selectNodeContents(code)
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
        button.textContent = button.dataset.selected ?? ""
      }
      window.setTimeout(() => (button.textContent = button.dataset.label ?? ""), 2500)
    })
  }
</script>

<style>
  .self-host { display: grid; gap: 2.5rem; }
  @media (min-width: 960px) { .self-host { grid-template-columns: 1fr 1.2fr; } }
  .needs { padding-left: 1.1rem; color: var(--muted-foreground); }
  .commands { list-style: none; margin: 1rem 0; padding: 0; display: grid; gap: 1rem; }
  .commands p { margin: 0 0 0.35rem; font-weight: 600; font-size: 0.9375rem; }
  .command { display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 0.6rem 0.6rem 0.9rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .command code { flex: 1; overflow-x: auto; white-space: nowrap; font-size: 0.875rem; }
  .note { color: var(--muted-foreground); }
</style>
```

`site/src/sections/Why.astro`:

```astro
---
import { GhostMark } from "../islands/GhostMark"
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section class="section" aria-labelledby="why-title">
  <div class="container why">
    <h2 id="why-title">{m.why.title}</h2>
    {m.why.body.map((paragraph) => <p>{paragraph}</p>)}
    <p class="signature"><GhostMark className="why-mark" /> {m.why.signature}</p>
  </div>
</section>

<style>
  .why { max-width: 42rem; }
  .why p { font-size: 1.0625rem; }
  .signature { display: flex; align-items: center; gap: 0.5rem; font-weight: 650; }
  .signature :global(.why-mark) { width: 24px; height: 24px; }
</style>
```

`site/src/sections/Faq.astro`:

```astro
---
import type { Messages } from "../i18n"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<section class="section" aria-labelledby="faq-title">
  <div class="container faq">
    <h2 id="faq-title">{m.faq.title}</h2>
    {
      m.faq.items.map((item) => (
        <details>
          <summary>{item.q}</summary>
          <p>{item.a}</p>
        </details>
      ))
    }
  </div>
</section>

<style>
  .faq { max-width: 48rem; }
  details { border-bottom: 1px solid var(--border); padding: 1rem 0; }
  summary { cursor: pointer; font-weight: 650; }
  details p { margin: 0.6rem 0 0; color: var(--muted-foreground); }
</style>
```

`site/src/sections/Footer.astro`:

```astro
---
import { GhostMark } from "../islands/GhostMark"
import type { Messages } from "../i18n"
import { LICENSE_URL, REPO_URL, TRADEMARKS_URL } from "../links"
import LanguagePicker from "./LanguagePicker.astro"

interface Props {
  m: Messages
}

const { m } = Astro.props
---

<footer class="footer">
  <div class="container footer-cta">
    <GhostMark className="footer-mark" face="sleepy" />
    <h2>{m.footer.cta}</h2>
    <a class="btn btn-primary" href="#self-host">{m.hero.primary}</a>
  </div>
  <div class="container footer-meta">
    <p><a href={LICENSE_URL}>{m.footer.license}</a></p>
    <p><a href={TRADEMARKS_URL}>{m.footer.trademarks}</a> · <a href={REPO_URL}>{m.footer.github}</a></p>
    <LanguagePicker m={m} />
    <p>{m.footer.noTrackers}</p>
  </div>
</footer>

<style>
  .footer { border-top: 1px solid var(--border); padding-block: 4rem 2rem; }
  .footer-cta { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 0.5rem; margin-bottom: 3rem; }
  .footer-cta :global(.footer-mark) { width: 56px; height: 56px; }
  .footer-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem 2rem; font-size: 0.875rem; color: var(--muted-foreground); }
  .footer-meta p { margin: 0; }
</style>
```

Replace `site/src/pages/index.astro` with:

```astro
---
import Layout from "../layouts/Layout.astro"
import { messagesFor } from "../i18n"
import AppShots from "../sections/AppShots.astro"
import CrossingSection from "../sections/CrossingSection.astro"
import Faq from "../sections/Faq.astro"
import Footer from "../sections/Footer.astro"
import Hero from "../sections/Hero.astro"
import HowItWorks from "../sections/HowItWorks.astro"
import Nav from "../sections/Nav.astro"
import SelfHost from "../sections/SelfHost.astro"
import Trust from "../sections/Trust.astro"
import Week from "../sections/Week.astro"
import Why from "../sections/Why.astro"

const m = messagesFor(Astro.currentLocale)
---

<Layout title={m.meta.title} description={m.meta.description}>
  <Nav m={m} />
  <main>
    <Hero m={m} />
    <HowItWorks m={m} />
    <Week m={m} />
    <CrossingSection m={m} />
    <AppShots m={m} />
    <Trust m={m} />
    <SelfHost m={m} />
    <Why m={m} />
    <Faq m={m} />
  </main>
  <Footer m={m} />
</Layout>
```

- [ ] **Step 6: Verify**

Run: `npm run check && npm test && npm run build`
Expected: 0 type errors; all tests pass; the build writes `dist/index.html` and webp screenshots
under `dist/_astro/`.

Run: `npm run preview` and read the whole page top to bottom in light and dark, at 1280px and
390px wide. Every anchor in the navigation scrolls to its section.

- [ ] **Step 7: Commit**

```bash
git add site/src
git commit -m "Assemble the landing page sections"
```

---

### Task 8: 404 page, search and sharing, Cloudflare config, and the dist audit

**Files:**
- Create: `site/src/pages/404.astro`, `site/public/robots.txt`, `site/wrangler.jsonc`,
  `site/scripts/audit.mjs`, `site/scripts/audit-dist.mjs`, `site/scripts/og-image.mjs`,
  `site/public/og.png` (generated)
- Test: `site/scripts/audit.test.mjs`

**Interfaces:**
- Consumes: `Layout.astro`, `Nav.astro`, `GhostMark`, `Messages` (earlier tasks).
- Produces: `thirdPartyRequests(text: string, allowedHost: string): string[]`;
  `missingHeadTags(html: string): string[]`; `npm run audit:dist` exits non-zero on findings.

- [ ] **Step 1: Write the failing test**

`site/scripts/audit.test.mjs`:

```js
import { describe, expect, it } from "vitest"
import { missingHeadTags, thirdPartyRequests } from "./audit.mjs"

const HOST = "calendarghost.com"

describe("thirdPartyRequests", () => {
  it("allows the site's own and relative URLs", () => {
    const html = `<link rel="canonical" href="https://calendarghost.com/"><img src="/_astro/a.webp"><script src="/_astro/b.js"></script>`
    expect(thirdPartyRequests(html, HOST)).toEqual([])
  })

  it("ignores ordinary links, which load nothing", () => {
    expect(thirdPartyRequests(`<a href="https://github.com/x">GitHub</a>`, HOST)).toEqual([])
  })

  it("finds scripts, stylesheets, images, and srcset entries from other hosts", () => {
    const html = [
      `<script src="https://cdn.example.com/x.js"></script>`,
      `<link rel="stylesheet" href="//fonts.googleapis.com/css">`,
      `<source srcset="/a.webp 1x, https://img.example.org/b.webp 2x">`,
    ].join("")
    expect(thirdPartyRequests(html, HOST)).toEqual([
      "https://cdn.example.com/x.js",
      "//fonts.googleapis.com/css",
      "https://img.example.org/b.webp",
    ])
  })

  it("finds remote URLs in CSS", () => {
    expect(thirdPartyRequests(`@font-face{src:url("https://fonts.gstatic.com/f.woff2")}`, HOST)).toEqual([
      "https://fonts.gstatic.com/f.woff2",
    ])
  })
})

describe("missingHeadTags", () => {
  it("names each missing tag", () => {
    expect(missingHeadTags("<head></head>")).toEqual(["title", "description", "canonical"])
    expect(
      missingHeadTags(`<title>x</title><meta name="description" content="y"><link rel="canonical" href="z">`),
    ).toEqual([])
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- scripts`
Expected: FAIL, cannot resolve `./audit.mjs`.

- [ ] **Step 3: Write the audit**

`site/scripts/audit.mjs`:

```js
// Requests a page makes on its own: scripts, stylesheets and other <link>s, media, and frames.
// Plain <a href> links load nothing and are allowed anywhere.
const REQUEST_ATTRIBUTE = /<(?:script|img|source|link|iframe|video|audio)\b[^>]*?\s(?:src|href|srcset)=["']([^"']+)["']/gi
const CSS_URL = /url\(\s*["']?([^"')]+)["']?\s*\)/gi
const ABSOLUTE = /^(?:https?:)?\/\//i

export function thirdPartyRequests(text, allowedHost) {
  const urls = [...text.matchAll(REQUEST_ATTRIBUTE), ...text.matchAll(CSS_URL)].flatMap((match) =>
    match[1].split(",").map((entry) => entry.trim().split(/\s+/)[0]),
  )
  return urls.filter((url) => ABSOLUTE.test(url) && new URL(url, `https://${allowedHost}`).host !== allowedHost)
}

export function missingHeadTags(html) {
  const checks = {
    title: /<title>[^<]+<\/title>/i,
    description: /<meta\s+name="description"\s+content="[^"]+"/i,
    canonical: /<link\s+rel="canonical"\s+href="[^"]+"/i,
  }
  return Object.entries(checks)
    .filter(([, pattern]) => !pattern.test(html))
    .map(([name]) => name)
}
```

`site/scripts/audit-dist.mjs`:

```js
import { readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"
import { missingHeadTags, thirdPartyRequests } from "./audit.mjs"

const DIST = new URL("../dist/", import.meta.url).pathname
const HOST = "calendarghost.com"

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? files(join(directory, entry.name)) : [join(directory, entry.name)],
  )
}

const problems = []
for (const file of files(DIST)) {
  if (!/\.(html|css)$/.test(file)) continue
  const text = readFileSync(file, "utf8")
  const name = relative(DIST, file)
  for (const url of thirdPartyRequests(text, HOST)) problems.push(`${name}: third-party request ${url}`)
  if (file.endsWith(".html")) {
    for (const tag of missingHeadTags(text)) problems.push(`${name}: missing ${tag}`)
  }
}

if (problems.length > 0) {
  console.error(problems.join("\n"))
  process.exit(1)
}
console.log("dist audit: no third-party requests; every page has a title, description, and canonical URL")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- scripts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Add the 404 page, robots.txt, and the Cloudflare config**

`site/src/pages/404.astro`:

```astro
---
import { GhostMark } from "../islands/GhostMark"
import Layout from "../layouts/Layout.astro"
import { messagesFor } from "../i18n"
import Nav from "../sections/Nav.astro"

const m = messagesFor(Astro.currentLocale)
---

<Layout title={m.meta.notFoundTitle} description={m.meta.description} noindex>
  <Nav m={m} />
  <main class="container section not-found">
    <GhostMark className="not-found-mark" face="sleepy" />
    <h1>{m.notFound.title}</h1>
    <p class="lead">{m.notFound.body}</p>
    <a class="btn btn-primary" href="/">{m.notFound.home}</a>
  </main>
</Layout>

<style>
  .not-found { display: flex; flex-direction: column; align-items: center; text-align: center; }
  .not-found :global(.not-found-mark) { width: 96px; height: 96px; margin-bottom: 1rem; }
</style>
```

`site/public/robots.txt`:

```text
User-agent: *
Allow: /
Sitemap: https://calendarghost.com/sitemap-index.xml
```

`site/wrangler.jsonc`:

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "calendar-ghost-site",
  "compatibility_date": "2026-10-01",
  // Static files only: no Worker script runs at launch.
  "assets": { "directory": "./dist", "not_found_handling": "404-page" },
  "routes": [{ "pattern": "calendarghost.com", "custom_domain": true }]
}
```

- [ ] **Step 6: Build and audit**

Run: `npm run build && npm run audit:dist`
Expected: the audit prints its success line. `dist/404.html`, `dist/sitemap-index.xml`, and
`dist/robots.txt` exist.

Run: `npx wrangler deploy --dry-run`
Expected: Wrangler validates the config and lists the assets without deploying.

- [ ] **Step 7: Generate the Open Graph image**

`site/scripts/og-image.mjs`:

```js
// Writes public/og.png from the running preview's hero. Run `npm run preview` first.
import { chromium } from "@playwright/test"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, colorScheme: "dark", reducedMotion: "reduce" })
await page.goto("http://localhost:4321/")
await page.locator(".nav").evaluate((nav) => nav.remove())
await page.screenshot({ path: new URL("../public/og.png", import.meta.url).pathname })
await browser.close()
```

Run: `npx playwright install chromium`, then `npm run preview` in one terminal and
`node scripts/og-image.mjs` in another.
Expected: `site/public/og.png` is a 1200×630 picture of the headline and the reveal at rest. Open
it and check it reads well as a link preview.

- [ ] **Step 8: Commit**

```bash
git add site
git commit -m "Add the 404 page, sharing metadata, Cloudflare config, and the dist audit"
```

---

### Task 9: Browser checks for the Review Focus

**Files:**
- Create: `site/playwright.config.ts`, `site/e2e/landing.spec.ts`

**Interfaces:**
- Consumes: the built site from `npm run build`; selectors `.reveal-frame`, `.reveal-week`,
  `button[data-copy]`, `#self-host-command-1`; slider name from `en.demo.sliderLabel`.

- [ ] **Step 1: Configure Playwright**

`site/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: "http://localhost:4321" },
  webServer: {
    command: "npm run preview -- --port 4321",
    url: "http://localhost:4321",
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
})
```

- [ ] **Step 2: Write the browser tests**

`site/e2e/landing.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test"
import { en } from "../src/i18n/en"

const split = (page: Page) =>
  page.locator(".reveal-frame").evaluate((frame) => getComputedStyle(frame).getPropertyValue("--split").trim())

test("loads nothing from another host", async ({ page }) => {
  const foreign: string[] = []
  page.on("request", (request) => {
    if (new URL(request.url()).host !== "localhost:4321") foreign.push(request.url())
  })
  await page.goto("/")
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await page.waitForLoadState("networkidle")
  expect(foreign).toEqual([])
})

test("with reduced motion, the hero rests at 55% and nothing sweeps", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.goto("/")
  await page.waitForTimeout(300)
  expect(await split(page)).toBe("55%")
  await page.waitForTimeout(1200)
  expect(await split(page)).toBe("55%")
})

test("the hero slider works from the keyboard and keeps its position", async ({ page }) => {
  await page.goto("/")
  const slider = page.getByRole("slider", { name: en.demo.sliderLabel })
  await slider.focus()
  for (let press = 0; press < 10; press += 1) await slider.press("ArrowLeft")
  const value = await slider.inputValue()
  await page.waitForTimeout(800)
  expect(await slider.inputValue()).toBe(value)
  expect(await split(page)).toBe(`${value}%`)
  await expect(slider).toHaveAttribute("aria-valuetext", `${value}% of the week shows your view`)
})

test("without JavaScript, the content and the hero's resting state are there", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.hero.title)
  await expect(page.getByText(en.demo.workSees).first()).toBeVisible()
  await expect(page.getByText(en.faq.items[0]!.q)).toBeVisible()
  await expect(page.getByRole("img", { name: en.app.overview.alt })).toBeVisible()
  expect(await split(page)).toBe("55%")
  await context.close()
})

test("on a phone, the pitch fits the first screen and the week shows Monday to Wednesday", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" })
  const page = await context.newPage()
  await page.goto("/")
  await expect(page.getByRole("heading", { level: 1 })).toBeInViewport()
  await expect(page.getByRole("link", { name: en.hero.primary }).first()).toBeInViewport()
  const frame = (await page.locator(".reveal-frame").boundingBox())!
  const thursday = (await page.locator(".reveal-work .week-days span").nth(3).boundingBox())!
  const wednesday = (await page.locator(".reveal-work .week-days span").nth(2).boundingBox())!
  expect(wednesday.x + wednesday.width).toBeLessThanOrEqual(frame.x + frame.width + 1)
  expect(thursday.x).toBeGreaterThanOrEqual(frame.x + frame.width - 1)
  await context.close()
})

test("a copy button selects the command when the clipboard is unavailable", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", { value: undefined }))
  await page.goto("/#self-host")
  await page.locator('button[data-copy="self-host-command-1"]').click()
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("cp .env.example .env")
  await expect(page.locator('button[data-copy="self-host-command-1"]')).toHaveText(en.selfHost.selected)
})

test("screenshots follow the dark color scheme", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" })
  const page = await context.newPage()
  await page.goto("/")
  const image = page.getByRole("img", { name: en.app.overview.alt })
  await image.scrollIntoViewIfNeeded()
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.currentSrc)).toContain("dark")
  await context.close()
})
```

- [ ] **Step 3: Run them**

Run: `npx playwright install chromium && npm run build && npm run e2e`
Expected: PASS, 7 tests. If a test fails, fix the component, not the test: each one states a
promise from the spec.

- [ ] **Step 4: Commit**

```bash
git add site/playwright.config.ts site/e2e
git commit -m "Check the landing page's browser promises with Playwright"
```

---

### Task 10: Repository integration

**Files:**
- Create: `.github/workflows/site.yml`
- Modify: `tests/test_ubiquitous_language.py`, `AGENTS.md`, `docs/development.md`

**Interfaces:**
- Consumes: the `site/` scripts `check`, `test`, `build`, `audit:dist`, `e2e`.

- [ ] **Step 1: Write the failing language test**

Add to `tests/test_ubiquitous_language.py`, after `test_every_checked_term_is_one_the_glossary_avoids`:

```python
def test_landing_page_copy_is_searched() -> None:
    searched = set(_searched_files())

    assert REPOSITORY / "site/src/i18n/en.ts" in searched
    assert REPOSITORY / "site/src/sections/Hero.astro" in searched
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -q`
Expected: FAIL on `test_landing_page_copy_is_searched`.

- [ ] **Step 3: Search the site's copy**

In `tests/test_ubiquitous_language.py`, change:

```python
SEARCHED = ("src/calendar_sync", "web/src", "docs", "scripts", "tests")
SUFFIXES = {".py", ".ts", ".tsx", ".md", ".sql", ".html"}
```

to:

```python
SEARCHED = ("src/calendar_sync", "web/src", "site/src", "docs", "scripts", "tests")
SUFFIXES = {".py", ".ts", ".tsx", ".astro", ".md", ".sql", ".html"}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py -q`
Expected: PASS. If the site copy uses an avoided term, change the copy in `en.ts`.

- [ ] **Step 5: Add the CI workflow**

`.github/workflows/site.yml`:

```yaml
name: Site

on:
  push:
    branches: [main]
    paths: ["site/**", "docs/assets/**", "README.md", ".github/workflows/site.yml"]
  pull_request:
    paths: ["site/**", "docs/assets/**", "README.md", ".github/workflows/site.yml"]

permissions:
  contents: read

jobs:
  site:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: site
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: site/package-lock.json
      - run: npm ci
      - run: npm audit --audit-level=high
      - run: npm run check
      - run: npm test
      - run: npm run build
      - run: npm run audit:dist
      - run: npx playwright install --with-deps chromium
      - run: npm run e2e
```

- [ ] **Step 6: Document the site for agents and developers**

Add to `AGENTS.md`, after the "Architecture boundaries" section:

```markdown
## Landing page

`site/` is the public landing page for `calendarghost.com`, an Astro site deployed by Cloudflare
Workers Builds. It is not part of the application: it has its own `package.json`, is excluded from
the Docker build context, and has its own `Site` workflow.

- It follows the Landing Page Register Rule in `DESIGN.md`: the ghost may play, explanations stay
  literal, and every decorative motion stops under reduced motion.
- All copy lives in `site/src/i18n/en.ts`; components contain no literal copy. Copy must stay true
  to `CONTEXT.md`; `tests/test_ubiquitous_language.py` searches it.
- The page contacts no host but its own: no analytics, trackers, CDNs, remote fonts, or live
  GitHub requests. `npm run audit:dist` and the Playwright tests enforce this.
- Self-host commands must match the README's quick start; a unit test compares them.
```

Add to `docs/development.md`, before "## Quality checks":

````markdown
## Landing page

The landing page in `site/` has its own toolchain:

```sh
npm ci --prefix site
npm --prefix site run dev          # http://localhost:4321
npm --prefix site run check        # astro check
npm --prefix site test             # unit tests
npm --prefix site run build && npm --prefix site run audit:dist
npm --prefix site run e2e          # Playwright; run `npx playwright install chromium` once
```

Cloudflare Workers Builds deploys it from `main`; other branches get preview URLs.
````

- [ ] **Step 7: Run every gate**

Run:

```sh
.venv/bin/pytest -q
cd site && npm run check && npm test && npm run build && npm run audit:dist && npm run e2e
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/site.yml tests/test_ubiquitous_language.py AGENTS.md docs/development.md
git commit -m "Run the landing page's checks in CI and document it"
```

---

### Task 11: Launch verification

**Files:** none, unless a check fails.

- [ ] **Step 1: Lighthouse on the production build**

Run (from `site/`, with `npm run preview` running):

```sh
CHROME_PATH="$(node -e "console.log(require('@playwright/test').chromium.executablePath())")" \
  npx --yes lighthouse@latest http://localhost:4321/ --quiet --chrome-flags="--headless=new" \
  --only-categories=performance,accessibility,best-practices,seo --output=json --output-path=./lighthouse.json
node -e "const r=require('./lighthouse.json');for(const [k,v] of Object.entries(r.categories))console.log(k,Math.round(v.score*100))"
rm lighthouse.json
```

Expected: each category scores at least 95. Fix what it reports and re-run.

- [ ] **Step 2: Look at it**

Take screenshots at 1280×800 and 390×844, in light and dark, with and without reduced motion, and
read every section. The hero must explain the product without scrolling at both sizes.

- [ ] **Step 3: Confirm the image is untouched**

Run: `git diff --stat origin/main -- Dockerfile` and `docker build --check .` (or the CI Docker
job). Expected: no Dockerfile change, and `site` appears in `.dockerignore`.

- [ ] **Step 4: Hand over the administrator's steps**

Report these to the administrator; they are not code:

1. Read "Why I built this" in `site/src/i18n/en.ts` and add one or two concrete details.
2. In Cloudflare, create a Worker from this repository with Workers Builds: root directory `site`,
   build command `npm ci && npm run build`, deploy command `npx wrangler deploy`, build watch paths
   `site/*`, production branch `main`.
3. Add a redirect rule from `www.calendarghost.com/*` to `https://calendarghost.com/${1}` (301).
4. Decide whether to publish the container image before sharing the page (spec, "Launch
   dependency").
5. After the first deploy, add `https://calendarghost.com` as the repository's website in GitHub.
