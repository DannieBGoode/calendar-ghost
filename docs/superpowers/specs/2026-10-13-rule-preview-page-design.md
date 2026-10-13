# Rule Preview page: design

Terms are in `CONTEXT.md` (Rule Preview, Initial Sync Window, Event Projection). The preview stores
only counts, as before; event titles never leave the request that asked for them (ADR 0014).

## Goal

Preview answers one question before "Start syncing": what will this rule do to my calendar? Today
it answers with two counts. It should show every source event beside what it becomes in the
destination, or why it stays out.

## Where it lives

- Its own page, `/rules/<id>/preview`, inside the app shell, titled with the rule ("Family → Work").
  The browser tab reads "Family → Work – Preview – Calendar Ghost".
- Every "Preview rule" and "Preview to restart" opens it, from a rule row, Rule Details, or the end
  of the rule builder. The page runs the preview as it loads.
- "Start syncing" exists only on this page. A previewed rule's row and Rule Details read "Ready to
  start" and offer "Review and start", which opens this page.
- The browser keeps the result for the session (no refetch on focus or reconnect); "Preview again"
  runs it on purpose. A reload runs it again, which is cheap and side-effect-free. Any change to
  the rule (policy, calendars, pause, enable, removal) forgets the kept result, so the next visit
  previews the rule as it is now.

## Page structure

```
┌ top navigation (Rules active) ─────────────────────────────────────────────┐
│ Family → Work                                                              │  1. what rule
│ Preview. Nothing is written until you start syncing.                       │  2. what this is
│ + 38 to add  ~ 3 to update  − 1 to remove  ⊘ 9 not synced                   │  3. what changes
│ [lock] Busy only: titles, descriptions, and locations stay private.        │  4. what is shared
│                                                                            │
│ (All 51 | Will sync 42 | Not synced 9) │ [All-day 6] [Birthdays 4] [Maybe 1]│  5. narrow it
│                                                                            │
│                                                                            │
│ ┌ When │ Family  source │ → │ Work  destination │ What happens ─────────┐  │
│ │ › Earlier, from 13 Sep · + 15 to add · − 1 to remove                  │  │
│ │ Today · Mon 13 Oct                                                    │  │  6. the evidence
│ │ 09:00–10:00 │ Dentist          │ → │ Busy           │ + Add           │  │
│ │ All day     │ Mum's birthday   │   │ Not written    │ ⊘ Not synced: … │  │
│ └───────────────────────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────────────────────┤
│ ← Back to rule      Previewed at 10:42 · Preview again   [Start syncing to Work] │  7. act
└────────────────────────────────────────────────────────────────────────────┘
```

## Header

- **Title:** "Family → Work", `{typography.headline}`, with no label above it (Page Titles).
- **Accounts:** under the title, in its order, each account with its avatar (the provider's mark on
  its corner) and, in words, its provider and address: "Google account · sam@family.example". The
  title already names the calendars, so nothing under it names them again; a rule within one
  account shows it once. Below 900px both accounts share one row, provider over address, and a
  long address breaks after its "@" (under 23rem the two accounts stack instead).
- **What this is:** "Previewed at 4:55 PM. Nothing is written until you start syncing." (with the
  date, "Previewed Tue, Oct 13 at 4:55 PM", once the preview is not from today), with
  "Refresh" at its end. Not "Sync again": nothing has synced, and the word would promise a write.
- **What is shared:** the policy's own line. Busy-Only: a lock and "Busy only: titles, descriptions,
  and locations stay private." Details: an eye in Attention Ochre and "Copies titles, descriptions,
  and locations to Work. Anyone who can see Work sees them." (Destructive and Privacy-Widening
  Changes).
- **What this rule syncs:** one quiet line under the privacy line, in its style, with each choice in
  a few words: "From the past 30 days · All-day events · No birthdays · Maybe as “Busy (tentative)” ·
  Unanswered as Maybe · No declined events", and "Change" as a text action at its end. Nothing to
  open: the line is short enough to read in place.

The counts ("+ 12 to add · ⊘ 3 not synced") sit in the sticky footer beside Start syncing, so the
decision is made with them in view; they cover the whole preview, never the filtered view.

## The table

One table, four columns: `When (GMT+2) | Family source | → Work destination | What happens`. The
When header names the time zone. Each written row starts its destination cell with the arrow, so
the arrow sits beside what it leads to. There are no colored calendar dots.

- The destination shows exactly what will be written: the policy's title ("Busy", "Busy
  (tentative)", or the title under Details Projection) and its recurrence. Its time is the
  source's, so it is not repeated.
- An excluded row's destination cell is empty to the eye and says "Nothing is written" to screen
  readers; its outcome gives the reason once ("Not synced: you declined"), so the source cell does
  not repeat the response.
- What happens uses Activity's signs and reason words (`ChangeSign`, `activity-reasons.ts`): + Add,
  ~ Update, − Remove, ✓ Already up to date, ⊘ Not synced with its reason (all-day, birthday, you
  declined, you answered Maybe, you haven't answered, written by Calendar Ghost, no occurrence
  left). Signs sit in Activity's small tinted discs, not bright filled circles. Update and Remove
  are in semibold, so the rare rows that change or delete what is already there stand out among the
  adds; "Add" itself is in Muted Ink beside its green sign, since most written rows add.
- An excluded row is muted as a whole, in Muted Ink (which passes body contrast), so the rows that
  write read first.
- Rows are one line where they fit. A recurrence or Invitation Response sits inline after the
  title, in muted text ("Swim class · Weekly on Tuesday · since 2 Sep").
- Rows sort by start time under day headings ("Today · Mon 13 Oct", "Tomorrow · Tue 14 Oct", "Wed
  15 Oct") on a faint Quiet Surface band. The past part of the window is one collapsed group above
  Today, so the page opens at Today with no scrolling. The group's label carries its own action
  counts ("Earlier, from 13 Sep · + 15 to add · − 1 to remove"), and it opens by itself when it
  holds a removal.
- A series is one row at its next occurrence on or after today, stepped in the series' own time
  zone, with its recurrence in words and when it began. A rule the page cannot step exactly
  (BYSETPOS, RDATE, a day filter its frequency does not use) reads "Repeats" and sits under Today. Only a series that has fully ended sits in the Earlier group.
- A changed occurrence is its own row on its own date, labelled with what changed:
  `19:00  Swim class · This date only: moved from 18:00  → Busy, 19:00  ~ Update`, or
  `Swim class · This date only: cancelled  ⊘ Not synced: cancelled`. Its outcome is the planned
  action; for a series the run writes for the first time (or again), a changed date is "+ Add" and
  a cancelled or excluded one is "Not synced", since nothing is there to update or remove.
- The table ends with "That is every event in Family now. Repeating events continue past the dates
  shown, and new or changed events sync on their own." A filtered table leaves this line out, since
  it does not hold every event.
- Times use the browser's time zone, named once above the table by its generic name ("Spain Time", not "GMT+2", which a DST change would make wrong for later rows), in tabular numerals. An event that
  crosses midnight shows its end with the day ("22:00–01:00 Tue"). A multi-day all-day event shows
  its dates ("All day, 13–15 Oct").
- A source event deleted since the last run has no date left, but the run will remove its
  projection, so it is listed first under "Deleted in Family" rather than left out.
- Every row renders, with no paging. Each day group uses `content-visibility: auto` so long
  windows stay fast.
- Nothing animates. The Earlier group opens instantly, filters apply instantly, and content
  replaces the skeleton without a fade.

## Filters

- One row: **Show** (All · Will sync · Not synced), one joined control with one choice, then a
  hairline, then each kind this preview has (All-day · Birthdays · Recurring · Declined · Maybe ·
  Not answered) as pills that combine with Show and with each other ("any of"). A kind no event in
  the preview has is not offered. The kinds are always in view, never folded behind a toggle.
- Every count follows the other choices (faceted), so the chosen Show count is always the rows
  shown; there is no "Showing X of Y" or "Clear filters" line to come and go and shift the table.
  An option that would show nothing beside the others stays in place, dimmed, so the row keeps its
  shape, and cannot be pressed unless chosen; it stays in the tab order (`aria-disabled`).
- Show is a radio group: one tab stop, with the arrow keys, Home, and End moving the choice. Kinds
  are toggle buttons (`aria-pressed`). On a phone the kinds take their own line under Show.
- Counts sit in small badges after their labels, in tabular numerals. Filters change only this
  page, never the rule.

## Start syncing

A sticky footer spans the window on Quiet Surface with a top `quiet-border`. Its content aligns
with the page column:

- Left: "← Back to rule" (Rule Details), then the counts ("+ 13 to add · ⊘ 4 not synced").
- Right: "You can pause or remove the rule at any time.", then the page's one primary action,
  "Start syncing to Work" (`{components.button-primary}`).
- When the rule copies details, the button names the effect where the decision is made: "Start
  syncing and share details with Work" (Destructive and Privacy-Widening Changes), with the header's
  ochre privacy line above.

The button carries no count; the counts beside it say what it will do, and no filter changes them.
While enabling, it reads "Starting…" and is disabled. Success returns to Rule Details, which
announces the result as it does today. The page reserves bottom padding equal to the footer's
height, so the footer never covers the last row, and scroll padding, kept at the footer's measured
height, keeps a control focused by keyboard above it. On a window under 36rem tall, such as a phone at large text, the footer stops
sticking and closes the page instead.

## States

| State | What the person sees |
|---|---|
| Loading | Title and privacy line at once. In place of the lead, at its size so nothing below moves, the small ghost mark and "Reading Family…" ("Reading Family and Work…" when the rule has mappings). Refresh does the same; the last results stay, dimmed, `aria-busy`, and inert, so the filters and Earlier keep their state and the page does not jump. A failure panel stays while its retry reads, and focus moves to the lead's Refresh, so it never falls to the page. Six skeleton rows; no chips until counts exist. "Start syncing" disabled, with "Available when the preview finishes". No shimmer under reduced motion. |
| Lapsed account | In place of the table, a Destructive Red panel: "Your Google account needs reauthorization", with one action, "Reauthorize account", which opens its Settings row. |
| Provider unavailable or limiting | An Attention Ochre panel: "Google Calendar is not answering right now", with Likely cause when known, and "Preview again". Provider text only under the diagnostic disclosure. |
| Rule changed or busy | A Quiet Surface panel: "This rule changed while it was being previewed", with "Preview again". |
| Rule already syncing | "This rule is already syncing", with "Open rule". No footer action. |
| Nothing in the window | The ghost mark (empty state) and "Family has no events from 13 Sep onward. Once you start syncing, new events sync as they appear." "Start syncing" stays enabled. |
| Every event excluded | The table as usual, all muted, above it: "None of Family's 9 events will sync with these settings", with "Change what syncs" (the rule's policy editor). "Start syncing" stays enabled, because future events may qualify. |
| No rows match the filters | Inside the table: "No events match these filters", with "Clear filters". |
| Enabling fails because the rule changed | The footer shows "This rule changed since the preview." in place of the counts, and "Refresh" takes Start's place as the primary button, with focus. |

In every failure state, "Start syncing" is disabled, and the footer drops the counts. Only a preview
that is reading says "Available when the preview finishes"; a failed one leaves the next step to its
panel, and a retry that fails again is announced: a refresh that fails leaves no numbers or timestamp from the earlier
preview on the page.

## Narrow screens

- **Below 900px:** one continuous list with the same day bands and dividers, never a card per row
  (it would be stacked cards).
  - Each row has three lines: time with the outcome sign on the right; "source title → destination
    title"; then muted recurrence, response, or reason.
  - The chips wrap; they never scroll sideways.
  - In the footer, "Back to rule" and the counts come first, then the button at full width with
    "You can pause or remove the rule at any time." under it, with safe-area padding.
- Filter options, the Earlier toggle, Back to rule, and Start are at least 44px tall below 900px.
  Refresh and Change, text actions inside a sentence, are at least 24px (WCAG 2.5.8), so they do
  not push their lines apart.

## Accessibility

- It is a real `<table>` with a visually hidden caption: "What Family → Work will write to Work".
  Column headers use `scope="col"`.
- Each day heading is a `<th scope="rowgroup">` across the row. The arrow column is `aria-hidden`.
- The Earlier group's toggle is a button with `aria-expanded` that controls its row group.
- Show is a labelled radio group and the kinds a labelled group ("Kind"). Each change is announced through the existing
  persistent live region ("Showing 12 of 51").
- Outcomes are always words beside their sign, never color alone.
- Focus order: header, chips, table, footer. Focus rings use the existing indigo ring.
- The text must also fit about 35% longer translations; check with `?locale=pseudo`.

## Provider calls

| Situation | Calls |
|---|---|
| New rule, no mappings | One paged source listing, one live-occurrence check per series, a parent read for an occurrence whose series is not listed. No destination reads. |
| Rule with mappings | The above, plus one paged `managed_events` listing of the destination, matched against mappings in memory, instead of `get_event` per mapped event. `get_occurrence` only for changed occurrences of mapped series. |
| Rule that has run | The above, plus the source changes since the rule's saved cursor, read without saving the next one. A change the window no longer shows, such as an event deleted or moved before the window while the rule was paused, is planned like any other, so the preview shows every action the resumed rule's next Sync Run will take. |
| Coming back to the page | None. |

A mapped event missing from the destination listing plans as projection missing (+ Add), as a
`get_event` returning nothing does today; verify against `SyncDecisionService` while building.

## API

`POST /api/v1/rules/{rule_id}/preview` returns every item, not a sample of 10. Each item gains:

- The source title, its start and end (or all-day dates), its recurrence as structured data (the
  UI writes it in the reader's language), its Invitation Response, and whether it is a provider
  birthday.
- The parent series and original start for an occurrence.
- The projected title, whether the projection carries a description or location, and the
  projected recurrence.
- The planned action with its `SyncReason`.

Excluded events are items too, with no projection. The stored summary keeps its counts as they are;
the page counts additions, updates, and removals from the items. A Previewed rule may be previewed
again, so "Preview again" and "See what will sync" work before it is enabled.

## NOT in scope

- **Editing the rule from the preview.** "Change what syncs" links to the existing policy editor.
- **Per-event include or exclude.** Eligibility is per rule (product invariant).
- **Storing the event list on the server.** Only counts are kept (ADR 0014).
- **Regenerating the mockup.** This text is canonical where it differs from the mockup: no count
  on the button, neutral pressed chips, no calendar dots, tinted discs, and the "Start syncing"
  wording.

## What already exists

`ChangeSign` and `activity-reasons.ts` (signs and reason words), `EventWhen` (time formatting),
People's "Show only" pill toggles, `PageSkeleton`, `LoadFailure`, the Cause wording in `causes.ts`
and `how-to-fix-link.tsx`, `use-rule-commands.ts` (its live region and enable command),
`previewReadyLabel`, the rule work note, `detail-toolbar`, the `GhostMark` empty and loading
states, and Activity's narrow-screen list pattern.

## Approved Mockups

| Screen/Section | Mockup Path | Direction | Notes |
|----------------|-------------|-----------|-------|
| Rule Preview page, desktop | /Users/danielcalatayud/.gstack/projects/DannieBGoode-calendar-ghost/designs/rule-preview-page-20261013/blend/variant-B.png | A blend of A and B: header arrow, one-line rows with inline recurrence, day bands, full-width sticky footer | This text wins on the button label, chip fill, dots, sign discs, and copy |

## Implementation Tasks

- [ ] **T1 (P1, human: ~1d / CC: ~45min)**: preview use case and API. Return every item with source, projection, action, and reason. Read the destination through one `managed_events` listing. Count additions, updates, and removals apart.
  - Files: `src/calendar_sync/application/sync/preview.py`, `interfaces/api/routes/rules.py`, `interfaces/api/schemas.py`, `web/openapi.json`, `web/src/lib/api-schema.ts`, tests.
  - Verify: `pytest tests -k preview`, `lint-imports`.
- [ ] **T2 (P1, human: ~1.5d / CC: ~1h)**: the `/rules/<id>/preview` page. Header, table, day groups, series and occurrence placement, Earlier group, filters, sticky footer.
  - Files: `web/src/lib/navigation.ts`, `web/src/features/rule-preview*.tsx`, `web/src/lib/rule-preview.ts`, `web/src/i18n/locales/en/*.json`.
  - Verify: `pnpm test`, `pnpm run lint`, `pnpm run doctor`.
- [ ] **T3 (P1, human: ~4h / CC: ~20min)**: the States table (loading, failures, empty, all excluded, filtered empty, enabling fails).
  - Verify: component tests per state.
- [ ] **T4 (P1, human: ~4h / CC: ~20min)**: narrow-screen layouts and accessibility (table semantics, rowgroup headings, `aria-expanded`, live-region announcements, 44px targets).
  - Verify: tests plus a manual check at 375px and with `?locale=pseudo`.
- [ ] **T5 (P2, human: ~2h / CC: ~10min)**: entry points. Preview buttons open the page, the count line links to it, and the builder ends there.
  - Files: `components/rule-commands.tsx`, `lib/use-rule-commands.ts`, `features/rule-builder.tsx`.
- [ ] **T6 (P2, human: ~1h / CC: ~5min)**: Details Projection's privacy line in Attention Ochre, and the "with description and location" marker.

## Engineering review

Target: this spec and its implementation in the working tree. The user delegated every decision
("make your own decisions"), so each finding below took the recommended fix; all are applied and
covered by tests.

### Findings and dispositions

| # | Sev | Conf | Where | Finding | Disposition |
|---|---|---|---|---|---|
| E1 | P1 | 9 | `web/src/features/rule-preview.tsx:32`, `lib/use-rule-refresh.ts` | The preview was cached per rule for the session, but no rule change cleared it, so after a policy edit the page showed the old table under the new privacy line and never re-ran the required preview. Codex found it too. | Fixed: `rulePreviewKey` is removed on every rule change, command, enable, and removal; test `use-rule-refresh.test.tsx`. |
| E2 | P2 | 8 | `rule-preview.tsx:30` | A reconnect re-ran the preview (React Query default), costing provider calls. | Fixed: `refetchOnReconnect: false`, `gcTime: Infinity`. |
| E3 | P2 | 8 | `preview.py` `_decide` | One SQLite mapping query per previewed event. | Fixed: the rule's mappings load once with the destination listing. |
| O1 | P1 | 9 | `preview.py` items filter | A source event deleted after a run has no time, and was dropped, hiding a removal the run makes. | Fixed: kept unless nothing happens; shown under "Deleted in {source}"; tests on both sides. |
| O2 | P2 | 9 | `preview.py` `_Destination.get` | A cancelled destination projection was compared as present, while a Sync Run treats it as missing (`event_sync.py:114`). | Fixed: normalized to missing; test. |
| O3 | P2 | 8 | `preview.py` `_decide_occurrence` | With the destination series deleted, occurrences read as blocked, though the run writes the series again with them. | Fixed: planned as changes in a new series; test strengthened. |
| O4 | P2 | 9 | `preview.py` `item` | Occurrences of an excluded mapped series inherited its removal, multiplying the removal count. | Fixed: they inherit the reason, not the action; test. |
| O5 | P2 | 8 | `recurrence.ts` | Unsupported RRULE combinations (DAILY+BYDAY, BYDAY+BYMONTHDAY, WKST, RDATE) were stepped wrongly; EXDATE ignored. | Fixed: refused (shown as "Repeats"); EXDATE days skipped; tests. |
| O6 | P2 | 8 | `recurrence.ts` | Series were stepped in the browser's zone, so a cross-zone viewer saw an hour off after DST. | Fixed: the API returns `time_zone`; stepping uses the series' zone; DST test. |
| O7 | P2 | 9 | `rule-preview.tsx` footer | Enable answers `invalid_state_transition` when the rule moved on; only `rule_not_executable` was recognized. | Fixed: both read as "changed since the preview"; rule details refetched. |
| O8 | P2 | 8 | `rule-preview-failure.ts` | Reauthorize could point at an unrelated lapsed account. | Fixed: only the rule's accounts, matching the failing provider. |
| O9 | P2 | 8 | `rule-preview-text.ts` | A recurring multi-day all-day row showed its first dates, not its next ones. | Fixed: range from its placed date; test. |

E = this review; O = Codex code review (outside voice, gpt-6.1-sol via `codex exec`).

### Failure modes

| Path | Realistic failure | Handling | Visible to the person |
|---|---|---|---|
| Preview POST | Provider refuses or lapses | 424 → panel with one next step | Yes |
| Preview POST | Rule changed or enabled meanwhile | 409 → changed or already-syncing panel | Yes |
| Enable | Rule moved on since preview | 409 → "changed since the preview", Preview again | Yes |
| Destination listing | Projection deleted or cancelled in the destination | Read alone or normalized to missing → "+ Add" | Yes |
| Recurrence in the browser | Rule it cannot step | "Repeats", placed under Today | Yes |
| Long preview | Slow provider paging | Skeleton and "Reading Family…"; no client timeout | Partly (waits) |

No critical gaps: every path either shows an error or a correct row.

### Coverage

```
BACKEND  application/sync/preview.py
  _classify ............ [★★★] counts, live series, managed sources (existing tests)
  _Planner.item
    single/series ...... [★★★] create, birthday skip, response policies, current, removal
    occurrence (new) ... [★★★] moved, cancelled, declined → removal
    occurrence (mapped)  [★★ ] destination series deleted → rewritten
    excluded series .... [★★★] one removal, occurrences ignored
  _Destination ......... [★★★] one listing, read-alone fallback, cancelled → missing
  deleted source ....... [★★★] removal kept
FRONTEND
  recurrence.ts ........ [★★★] words, stepping, COUNT/UNTIL, month gaps, zones, EXDATE, refusals
  rule-preview.ts ...... [★★★] outcomes, kinds, filters, layout, undated, multi-day
  page ................. [★★ ] table, filter, start syncing, lapsed panel, pseudo-locale
  cache ................ [★★★] dropped on rule change
GAP (accepted): no browser check at 1440 and 390 px; run the dev preview before merging.
```

### NOT in scope

- A server-side next-occurrence calculation: no RRULE library on the server; the browser does it.
- A client timeout for very slow previews: the existing work note covers the wait.

Parallelization: sequential implementation, no parallelization opportunity (one feature, done).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | n/a | n/a |
| Outside Review | `codex exec` via `/codex review` (code) | Independent 2nd opinion | 1 | completed | 10 findings (1 P1, 9 P2), 10/10 fixed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open (all fixed) | 12 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | clean | score: 5/10 → 9/10, 22 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | n/a | n/a |

- **OUTSIDE COVERAGE:** Codex (gpt-6.1-sol) code review of the working tree completed with 10 findings; design-phase Codex review completed earlier.
- **CROSS-MODEL:** Both Claude and Codex found the stale preview cache (E1). Codex alone found the planning mismatches with a Sync Run (O1 to O4) and the recurrence issues (O5, O6, O9).
- **VERDICT:** Design Review CLEARED. Eng Review: every finding fixed and tested; re-run `/review` on the final diff before merging.

NO UNRESOLVED DECISIONS
