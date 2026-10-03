---
target: web/src/features/activity.tsx web/src/features/settings.tsx web/src/features/overview.tsx
total_score: 37
p0_count: 0
p1_count: 0
timestamp: 2026-10-03T10-21-27Z
slug: eatures-settings-tsx-web-src-features-overview-tsx
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 4/4 | Hero status, account summaries, activity outcomes, and preview state are explicit. |
| 2 | Match System / Real World | 4/4 | Directional Sync Rules, connected accounts, calendar names, and activity decisions use the product's domain language. |
| 3 | User Control and Freedom | 4/4 | Activity entries remain selectable, details can close, and healthy account data stays collapsed until requested. |
| 4 | Consistency and Standards | 4/4 | Live Settings and the synthetic preview now share the same Connected accounts interaction. |
| 5 | Error Prevention | 3/4 | Preview actions are disabled and setup prerequisites are stated, but the helper still relies on the primary button above it. |
| 6 | Recognition Rather Than Recall | 4/4 | Day labels, account summaries, and the connection guide reduce memory load. |
| 7 | Flexibility and Efficiency | 3/4 | Search, filters, preview state controls, and row navigation are strong; the helper could offer a direct next action. |
| 8 | Aesthetic and Minimalist Design | 4/4 | The card boundary contains dense history, and the date separators no longer read as status bands. |
| 9 | Error Recovery | 3/4 | OAuth return help and activity recovery are clear; the general service failure path still falls back to reload. |
| 10 | Help and Documentation | 4/4 | The collapsed connection guide is available in Settings without competing with routine account management. |
| **Total** |  | **37/40** | Strong, ship-ready foundation with two small interaction refinements. |

## Anti-Patterns Verdict

**LLM assessment:** This does not read as AI-generated. The ghost character, restrained indigo status system, contained cards, and audit-oriented Activity layout give the product a specific point of view. The design avoids gradient text, glass cards, generic hero metrics, repeated marketing eyebrows, and identical card grids.

**Deterministic scan:** The bundled detector returned no findings for `web/src/features/activity.tsx`, `web/src/features/settings.tsx`, or `web/src/features/overview.tsx`.

**Browser evidence:** A browser visualization attempt was made, but the fresh local browser stopped at the administrator sign-in screen before the preview surface could render. No reliable user-visible overlay is claimed. The local live-server was stopped after the attempt.

## Overall Impression

This round landed the important consistency work. The Settings preview now feels like the same product as the live installation, and Activity reads as a history surface rather than a dashboard with another warning band. The biggest remaining opportunity is making the compact helper slightly more actionable on touch devices.

## What's Working

- The collapsed account summary preserves the calm default state while keeping account identity, status, and expansion control visible.
- The connection guide is discoverable but quiet. It teaches the three-step path without turning Settings into a second onboarding wizard.
- Activity grouping now uses the right hierarchy: Today, Yesterday, and full date labels are semantic separators, while the run rows retain the interactive focus.

## Priority Issues

### [P2] Compact helper summary has a small touch target

**Location:** `web/src/index.css:1491-1499`, affecting `.connection-guide summary`.

**Why it matters:** The helper summary inherits a 16px icon and a roughly 21px line box with no vertical padding. It is keyboard-visible and semantically correct, but it is smaller than the 24px WCAG 2.2 AA target-size minimum and will feel fiddly on a phone.

**Fix:** Give the helper summary a minimum height of 2.75rem with a small horizontal negative margin so the larger target does not change the surrounding rhythm. Keep the visible label and icon unchanged.

**Suggested command:** `$impeccable adapt`

### [P3] The guide explains the first action but does not repeat it inside the disclosure

**Location:** `web/src/features/settings.tsx:211-218`.

**Why it matters:** After opening the guide, a first-time user reads the steps and then has to look back to the section header to act. This is a minor discoverability cost, especially on a narrow screen where the header button may scroll away.

**Fix:** If Google is configured, add a compact secondary “Connect Google account” link at the end of the guide. Keep it absent or disabled when configuration is missing, and keep preview mode read-only.

**Suggested command:** `$impeccable onboard`

## Persona Red Flags

**Jordan, first-time administrator:** The three-step helper now answers why Google access is needed and what follows. The only friction is that the final action remains above the disclosure instead of inside it.

**Alex, power user:** The compact default state is efficient. Activity row links, rule filters, and the detail pane preserve fast inspection, though the larger mouse target on a row is not itself a separate keyboard target. The event link provides the keyboard path.

**Morgan, accessibility-conscious operator:** Account summaries and Activity details expose state with native buttons, links, `aria-expanded`, and focus styling. The helper summary should gain a larger touch target to remove the remaining small-control concern.

## Minor Observations

- The date separator still uses a full-width divider, but its transparent background and muted label now keep it subordinate to the Activity rows.
- Long account email lists correctly ellipsize in the collapsed summary; the expanded list remains the place for full identity and actions.
- Overview preview query gating is a worthwhile technical improvement because the mock dashboard no longer depends on installation data being available.

## Questions to Consider

- Should the connection guide's final line become the direct Connect action, or do you prefer keeping one primary action in the section header?
- Would you want the helper to remain available after an account is connected, or should it disappear once the user has completed the first step?

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|---|---:|---|
| 1 | Accessibility | 3/4 | Strong semantics and focus states; the compact helper summary should use a larger touch target. |
| 2 | Performance | 4/4 | Preview mode gates live Overview and endpoint queries; UI motion uses lightweight transforms and opacity. |
| 3 | Responsive Design | 3/4 | Mobile layouts and stacked account actions are handled well; the helper disclosure is the one small-target rough edge. |
| 4 | Theming | 4/4 | Changed surfaces use tokens, and the light, Twilight, and Midnight palettes have dedicated values. |
| 5 | Anti-Patterns | 4/4 | No detector findings and no visible AI-style composition tells in the reviewed surfaces. |
| **Total** |  | **18/20** | Excellent, with minor adaptive polish remaining. |

## Audit Findings by Severity

### [P2] Helper disclosure target size

**Category:** Accessibility / Responsive Design

**Impact:** The disclosure is usable with a keyboard and pointer, but the small vertical hit area can make the helper harder to open on touch devices.

**WCAG/Standard:** WCAG 2.2 Success Criterion 2.5.8, Target Size (Minimum), subject to its exceptions.

**Recommendation:** Add a 44px minimum target to `.connection-guide summary` while preserving the quiet visual treatment.

### [P3] Repeated primary action in helper

**Category:** Recognition Rather Than Recall / Onboarding

**Impact:** Users who open the guide must move back to the section header to start connecting.

**Recommendation:** Add a secondary action inside the open guide only when live configuration permits it.

## Patterns & Systemic Issues

No systemic issue was found in the reviewed scope. Token use is consistent, preview and live Settings share their interaction model, and the current detector found no repeated anti-pattern.

## Positive Findings

- The product uses one clear visual language across Overview, Activity, and Settings: quiet surfaces, strong headings, and status color reserved for meaning.
- The preview query guards prevent a read-only visual review from accidentally depending on live installation data.
- Activity rows retain both a direct event link for keyboard users and a larger row click target for pointer users.
