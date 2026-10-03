---
target: web/src/features/activity.tsx + web/src/features/settings.tsx
total_score: 31
p0_count: 0
p1_count: 2
timestamp: 2026-10-03T09-58-23Z
slug: eatures-activity-tsx-web-src-features-settings-tsx
---
## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 3/4 | Activity clearly exposes decisions and filters; preview Settings does not communicate that its account summary is non-interactive. |
| 2 | Match System / Real World | 4/4 | Calendar language, event times, rules, and outcomes map cleanly to the administrator's mental model. |
| 3 | User Control and Freedom | 3/4 | Activity supports filtering, selection, and closing details; the preview account list removes the expected collapse control. |
| 4 | Consistency and Standards | 3/4 | Live Settings and the visual preview disagree on the Connected accounts interaction model. |
| 5 | Error Prevention | 3/4 | The UI exposes safe rule outcomes and keeps destructive controls explicit; setup guidance is not present where a first-time user needs it. |
| 6 | Recognition Rather Than Recall | 3/4 | The Activity table explains each decision, but Settings does not surface the short connection path or why permissions matter. |
| 7 | Flexibility and Efficiency | 3/4 | Search, rule, and outcome filters are useful; a compact connection guide would reduce setup backtracking. |
| 8 | Aesthetic and Minimalist Design | 3/4 | The contained History card is strong; the full-width dark Today band is heavier than the date grouping needs to be. |
| 9 | Error Recovery | 3/4 | Activity links into details and incidents; connection recovery is available but not taught in the normal Settings path. |
| 10 | Help and Documentation | 2/4 | The Getting started guide exists only on Overview setup state, so it disappears in the healthy mock preview and is absent from Settings. |
| **Total** |  | **31/40** | Good foundation, with one preview fidelity regression and one visible grouping polish issue. |

## Anti-Patterns Verdict

The interface does not read as AI-generated. It uses a restrained palette, familiar controls, meaningful cards, and domain-specific language. The detector found no issues in `activity.tsx`, `settings.tsx`, or `preview-banner.tsx` (`detect.mjs --json` returned `[]`). The only visible anti-pattern risk is over-weighting a semantic date separator with a full-canvas color band.

## Overall Impression

The Activity page is clear and trustworthy. The screenshot's table hierarchy is strong: filters, column labels, event identity, outcome, and rule direction all scan in the right order. The two notes are valid regressions in the mock surface: preview Settings is not showing the same interaction as live Settings, and the Today separator looks like a selected or special-status row instead of a quiet date label.

## What's Working

- The History card gives a dense audit surface a stable boundary without turning it into an infrastructure console.
- The Activity copy explains outcomes in calendar language: added, updated, skipped, blocked, and removed.
- Live Settings already has the correct collapsed-account logic at `web/src/features/settings.tsx:288-297`; it opens only for attention, a fresh connection, or an active confirmation.

## Priority Issues

### [P1] Preview Settings drops the Connected accounts disclosure

**Location:** `web/src/features/settings.tsx:923-967`

**Why it matters:** The live page collapses healthy accounts, but the mock page renders every account and replaces the disclosure button with a plain `div` labeled “Mock data.” That makes the preview feel like a different product and adds unnecessary vertical noise to the page. It is also not keyboard-operable and has no `aria-expanded` state.

**Fix:** Reuse the same account-summary interaction in preview mode. Default it closed when every sample account is healthy, open it only when a sample account needs attention, and keep the read-only buttons inside the expanded list.

**Suggested command:** `$impeccable normalize` or `$impeccable polish`

### [P1] The mini connection guide is only available in one health state

**Location:** `web/src/features/overview.tsx:508-610`

**Why it matters:** The `Getting started` / connection guide is rendered only when `health.tone === "setup"`. The healthy mock preview therefore hides it, and Settings has no compact equivalent. A first-time administrator can land in Settings and see a Connect button without a clear three-step explanation of account access, rule creation, and preview.

**Fix:** Extract the first step into a small reusable `ConnectionGuide` and show it in Connected accounts when there are no connected accounts or the installation is not configured. Keep the full three-step guide on Overview for setup; use a collapsed helper disclosure in Settings so it does not compete with routine account management.

**Suggested command:** `$impeccable onboard`

### [P2] “Today” is styled as a data row instead of a date group

**Location:** `web/src/features/activity.tsx:348-355`, `web/src/index.css:3068-3079`

**Why it matters:** The sticky header uses `var(--background)` across the entire table width with a large top pad. In dark themes that produces the nearly black band shown in the screenshot. It reads like a selected or warning row even though it is only a date separator.

**Fix:** Keep the grouping row, but make it quieter: use the card surface for the sticky backing, muted text, a smaller vertical inset, and a single divider. Change the header semantics from `scope="colgroup"` to `scope="rowgroup"` so assistive technology understands that “Today” labels the following row group.

**Suggested command:** `$impeccable colorize` or `$impeccable polish`

### [P2] Mock Overview still starts live data queries

**Location:** `web/src/features/overview.tsx:89-100`

**Why it matters:** Preview mode supplies synthetic data, but the component still requests dashboard, rules, Google configuration, and incident data. That creates avoidable network traffic and makes the visual review depend on an authenticated API even though the page is meant to be read-only sample data.

**Fix:** Gate live queries with `enabled: !dashboardPreviewEnabled`, or use preview-aware query functions and keys consistently. Keep the normal authenticated shell, but do not fetch installation data when the explicit preview flag is active.

**Suggested command:** `$impeccable optimize`

## Audit Health Score

| # | Dimension | Score | Key finding |
|---|---|---:|---|
| 1 | Accessibility | 3/4 | Good landmarks, labels, focus handling, and row links; preview account summary is a non-interactive `div`, and the date group uses the wrong scope. |
| 2 | Performance | 3/4 | No layout-thrashing or hard-coded colors in the focused TSX; preview Overview still starts live queries. Built JS is about 442 KB before gzip. |
| 3 | Responsive Design | 3/4 | Activity switches to a stacked mobile row layout and Settings has responsive rules; account action density remains a watch item at narrow widths. |
| 4 | Theming | 4/4 | Focused components use semantic tokens, and the Activity surface is covered in light, twilight, and midnight captures. |
| 5 | Anti-Patterns | 4/4 | No detector findings; no gradients, decorative shadows, or generic dashboard patterns in the reviewed files. |
| **Total** |  | **17/20** | Good; fix the preview interaction and date-group semantics before calling the preview finished. |

## Persona Red Flags

- **Jordan, first-time administrator:** In Settings, the Connect action is present, but the “why these permissions / what happens next” guide is absent. The only full explanation lives in Overview and disappears as soon as the synthetic state is healthy.
- **Alex, power user:** Activity is efficient once loaded, with filters and keyboard selection, but the Today band adds visual weight without adding information. The extra dark strip slows scanning through long history.
- **Low-vision / keyboard user:** The live account summary is accessible, but the preview account summary is not a button, cannot be collapsed, and exposes no expanded/collapsed state. The date header's `colgroup` scope also weakens table navigation semantics.

## Minor Observations

- The text “Mock data” is useful, but it should sit in the preview banner or a disabled status badge, not where the live page says “Show accounts.”
- The Activity screenshot has a strong density balance on desktop. Keep the mobile stacked layout under the same date-group treatment so the fix does not reintroduce a large band there.
- The visual design is otherwise consistent with the product register: calm, operational, and free of decorative sidebar or analytics-dashboard tropes.

## Questions to Consider

- Should the mini connection guide live only in the empty/unconfigured Connected accounts state, or remain available as a collapsed “How connection works” helper after accounts exist?
- Should the Activity date separator remain sticky, or become a quieter non-sticky label so it never competes with the row content?
- For preview fidelity, should every read-only preview surface mirror the live interaction states exactly, including collapsed sections, even when the mock data has no incidents?
