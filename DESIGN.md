---
name: Calendar Ghost
description: A calm ghost that keeps your busy time where it needs to be
colors:
  lantern-indigo: "oklch(0.47 0.15 278)"
  mist: "oklch(0.99 0.004 285)"
  quiet-surface: "oklch(0.972 0.008 285)"
  muted-surface: "oklch(0.95 0.012 285)"
  calm-ink: "oklch(0.22 0.045 280)"
  muted-ink: "oklch(0.45 0.035 280)"
  quiet-border: "oklch(0.90 0.014 285)"
  healthy-soft: "oklch(0.94 0.04 155)"
  healthy-ink: "oklch(0.31 0.09 155)"
  attention-soft: "oklch(0.94 0.055 80)"
  attention-ink: "oklch(0.34 0.08 70)"
  attention-surface: "oklch(0.975 0.022 80)"
  attention-border: "oklch(0.86 0.06 80)"
  healthy-surface: "oklch(0.975 0.018 155)"
  healthy-border: "oklch(0.85 0.035 155)"
  destructive: "oklch(0.50 0.18 25)"
  daylight: "oklch(1 0 0)"
  brand-glow: "oklch(0.97 0.02 285)"
  twilight-canvas: "oklch(0.2 0.04 280)"
  twilight-ink: "oklch(0.95 0.012 285)"
  twilight-muted: "oklch(0.80 0.03 285)"
  night: "oklch(0.17 0.022 280)"
  night-surface: "oklch(0.21 0.026 280)"
  night-muted-surface: "oklch(0.26 0.03 280)"
  night-calm-ink: "oklch(0.95 0.012 285)"
  night-muted-ink: "oklch(0.75 0.025 285)"
  night-lantern-indigo: "oklch(0.74 0.12 278)"
  night-status-soft: "oklch(0.28 0.06 278)"
  night-quiet-border: "oklch(0.34 0.03 280)"
  night-input-border: "oklch(0.52 0.03 280)"
  night-healthy-soft: "oklch(0.27 0.045 155)"
  night-healthy-ink: "oklch(0.79 0.11 155)"
  night-healthy-surface: "oklch(0.22 0.025 155)"
  night-healthy-border: "oklch(0.40 0.055 155)"
  night-attention-soft: "oklch(0.29 0.05 80)"
  night-attention-ink: "oklch(0.83 0.11 85)"
  night-attention-surface: "oklch(0.22 0.025 80)"
  night-attention-border: "oklch(0.42 0.06 80)"
  night-destructive: "oklch(0.68 0.16 25)"
  night-destructive-soft: "oklch(0.28 0.06 25)"
  night-destructive-ink: "oklch(0.80 0.11 25)"
  midnight: "oklch(0.17 0.03 250)"
  midnight-surface: "oklch(0.21 0.033 250)"
  midnight-muted-surface: "oklch(0.26 0.038 250)"
  midnight-calm-ink: "oklch(0.95 0.01 240)"
  midnight-muted-ink: "oklch(0.76 0.03 240)"
  midnight-lantern-blue: "oklch(0.75 0.12 240)"
  midnight-quiet-border: "oklch(0.34 0.035 250)"
  midnight-input-border: "oklch(0.53 0.035 250)"
  midnight-twilight-canvas: "oklch(0.2 0.045 252)"
typography:
  headline:
    fontFamily: "Fraunces Variable, ui-serif, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 560
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  object-title:
    fontFamily: "Figtree Variable, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 650
    lineHeight: 1.25
  title:
    fontFamily: "Figtree Variable, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Figtree Variable, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Figtree Variable, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  panel: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.lantern-indigo}"
    textColor: "{colors.daylight}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "40px"
  button-outline:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.calm-ink}"
    rounded: "{rounded.md}"
    padding: "10px 16px"
    height: "40px"
  input:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.calm-ink}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
    height: "40px"
  health-badge:
    backgroundColor: "{colors.healthy-soft}"
    textColor: "{colors.healthy-ink}"
    rounded: "999px"
    padding: "4px 10px"
---

# Design System: Calendar Ghost

## Overview

**Creative North Star: "The Calm Ghost"**

A friendly presence at twilight: pale, quiet, and always where you expect it. The ghost lives in
the mark, the sign-in panel, loading, and empty states; everywhere else the interface is a calm
household utility. It serves a nontechnical administrator first, with audit and provider evidence
available through progressive disclosure.

The layout uses a restrained top navigation and a readable central work area rather than a permanent dashboard sidebar. Stable information stays flat. Forms and workflows use familiar shadcn/ui affordances, while domain-specific health strips and directional rule rows carry the product language. Administration surfaces, such as People and its Plans, are denser in the same calm surfaces: a feature's state and its switch lead, a data table compares like things by column, and a side panel holds the form for the selected row.

**Key Characteristics:**

- Calm operational summaries with specific next actions
- Privacy consequences visible before synchronization begins
- Human language at the surface, diagnostics one level deeper
- Responsive state feedback without decorative entrances
- Structural mobile layouts with unchanged text hierarchy

## Brand

**Name:** Calendar Ghost. **Tagline:** *"Your busy time, everywhere it needs to be."*

**The mark.** A rounded calendar page with two binder tabs, drawn on a 32-unit grid; its bottom
edge is a three-scallop ghost hem, and two dot eyes sit in the upper body. `GhostMark`
(`web/src/components/ghost-mark.tsx`) renders it as inline SVG colored by three tokens:
`--brand-glow` (body fill), `--brand-line` (outline and tabs), and `--brand-eyes` (the two dots).
In light appearance the ghost is pale with an indigo outline and eyes; in dark appearance and on
the twilight auth panel it is a solid ghost-white silhouette with dark eyes. On the Overview health hero it is filled with the state's color and its face follows the state
(see Overview Health Hero). It is decorative
(`aria-hidden`) wherever the name sits beside it, and appears in the top-bar lockup, the auth intro
panel, the Overview health hero, empty states, and the startup loading screen.

### Named Rules

**The Ghost Is Brand, Not Vocabulary Rule.** The ghost appears in the mark, the sign-in panel,
Overview health hero, loading, and empty states; labels and explanations always use the glossary
in `CONTEXT.md`, never calling a Managed Projection a "ghost."

**The Landing Page Register Rule.** On the landing page (`site/`), the ghost is the main character:
it carries events between calendars, reacts, and reuses the Overview faces (adding proud, surprised,
and wink), drawn filled at character size by `site/src/islands/Ghost.tsx`. Microcopy may joke.
Explanations stay literal and true to the glossary, and every decorative motion stops under
`prefers-reduced-motion`. The rest of this document describes the application.

## Colors

A lavender-tinted neutral canvas (the "Twilight" palette) supports a single indigo indicator color, Lantern Indigo, with distinct low-chroma semantic surfaces for health and attention. Dark appearance keeps the same roles on a lavender-tinted near-black canvas, increasing foreground and control contrast without turning the interface into an infrastructure console.

### Appearance

- **Device setting** is the default and follows the browser's current color-scheme preference, including changes made while the app is open.
- **Light** and **Dark** are explicit browser-local choices. They apply before the interface paints and persist across visits without adding installation state to SQLite.
- **Dark palette** chooses the colors used whenever the interface is dark, whether by choice or by following the device. **Twilight** (indigo) is the default; **Midnight** is a blue alternative with a navy canvas, cool blue-grey neutrals, and Lantern Blue in place of Lantern Indigo, and it turns the auth intro panel navy too. Like the theme, it is browser-local, applies before paint, and sets the browser chrome color. Light appearance has one palette.
- Semantic meaning does not change between appearances or palettes. The palette's lantern color remains action and focus, moss remains healthy, ochre remains attention, and red remains destructive or stopped.

### Primary

- **Lantern Indigo**: Primary actions, selected navigation, focus, and active setup progress. It is never decorative.

### Secondary

- **Healthy Moss**: Quiet confirmation surfaces and healthy text.
- **Attention Ochre**: Conditions to review while synchronization keeps running, such as blocked events and incidents on running rules.
- **Destructive Red**: Confirmed destructive actions, validation errors, and stopped synchronization: a rule suspended until the administrator acts.

### Neutral

- **Mist**: Main page and field background.
- **Quiet Surface**: Grouped controls, intro panels, and inactive structure.
- **Muted Surface**: Hover, selected-neutral, and skeleton states.
- **Calm Ink**: Primary text.
- **Muted Ink**: Supporting text that still passes body-text contrast.
- **Quiet Border**: Dividers and field boundaries.

### Named Rules

**The Quiet Indicator Rule.** Lantern Indigo occupies no more than 10% of a screen. Its rarity makes action and focus immediately legible.

**The Status Is Not Just Color Rule.** Healthy, degraded, running, and failed states always combine color with text and an icon.

**The Provider Mark Rule.** A provider's own mark (Google Calendar, Outlook) appears in only two places: on the lower corner of a Connected Account's avatar, on a small tile of the page color, and beside that provider's name in Connect. It helps the eye scan accounts by provider; the text beside it always names the provider too ("Microsoft account · address"), so the mark is never the only signal. Marks keep their own colors and never replace the ghost mark or carry status.

## Typography

**Display Font:** Fraunces (bundled variable font, SOFT axis 100), used only for page titles and the auth headline.

**Body Font:** Figtree (bundled variable font), used for all other text and every control.

**Character:** A quiet serif marks the handful of places the product wants to feel considered; a single humanist-leaning sans family keeps small status labels and longer guidance equally legible everywhere else. Both are bundled self-hosted woff2 with `font-display: swap`, so an offline Raspberry Pi renders them without a fallback to the device's system face.

### Hierarchy

Product text uses seven steps: 2rem Fraunces page titles, 1.25rem Figtree object titles (weight 650), 1rem Figtree section titles (weight 650), 1rem Figtree row titles (weight 550), 1rem Figtree body (weight 400), 0.875rem labels and controls (weight 600), and 0.8125rem supporting metadata. Settings and Rule Details section and row headings are aligned to these levels. Counts in tables, meters, and facts use tabular numerals, so columns of numbers line up.

- **Headline**: Screen titles and the auth headline, in Fraunces at a strong but quiet scale.
- **Object title**: The name of the one thing a panel or card is about, such as a Plan's name in its side panel, on a person's Plan card, and on Your plan, and the state a status card leads with ("Plans are on"). It sits between the page title and section titles, so a Plan's name never reads as a row label.
- **Title**: Section titles and row titles (rule names, grouped settings, and recovery headings) in Figtree, distinguished by weight rather than size.
- **Body**: Instructions and explanations, capped near 70 characters per line.
- **Label**: Field labels, navigation, compact state, and metadata in sentence case.

### Named Rules

**The Calendar Language Rule.** Labels use the domain glossary and plain calendar terminology. Provider codes, tokens, and infrastructure terms remain in diagnostic details.

**The Data Register Rule.** Table cells, chips, facts, and meters hold nouns and numbers ("2 people", "1 over a limit", "2 of 1"); sentences belong to hints, descriptions, empty states, confirmations, and results. Both use the same words, so a cell is the short form of the sentence that explains it, never a different term.

**The Room To Grow Rule.** Leave room for about 35% longer text in other languages; check layouts with `?locale=pseudo`.

## Elevation

The system is flat by default. Tonal layering, dividers, and spacing establish structure. Only transient menus, popovers, dialogs, and toasts may lift above the page; stable panels never use decorative shadows. A side panel beside a table is stable: a border, no shadow.

### Named Rules

**The Stable Surface Rule.** A shadow signals a temporary layer. If a resting container appears to float, remove the shadow.

## Components

### Buttons

- **Shape:** Gently curved and compact.
- **Primary:** Lantern Indigo with a contrast-checked foreground, reserved for the next meaningful action.
- **Hover / Focus:** A small tonal change and a visible indigo focus ring over 180 milliseconds.
- **Secondary / Ghost:** Neutral structure for reversible and navigational actions.
- **Size:** 40 pixels high; on a coarse pointer, buttons, fields, switches, checkboxes, and segmented options reach a 44-pixel target.

### Chips

- **Style:** Full-pill semantic tint with text and a 14px icon; the Badge primitive sizes every
  icon inside it.
- **State:** Health, attention, and neutral lifecycle labels use separate named roles.

### Cards / Containers

- **Corner Style:** Panels use the panel radius; list structure often uses dividers with no card at all.
- **Background:** The active canvas or Quiet Surface token.
- **Shadow Strategy:** None at rest.
- **Border:** One quiet full border only when grouping needs a boundary.
- **Internal Padding:** 16 to 24 pixels depending on workflow density.
- The Overview hero, Recent Changes, Rules summary, and setup workflow use bordered cards to make
  operational groups easy to scan. Rules, Activity, and Rule Details reuse the same panel radius,
  Quiet Surface, and 16–24px internal padding for grouped lists and controls. A card is a boundary
  for meaningful information, not a wrapper for every paragraph; stable list rows still use dividers.

### Inputs / Fields

- **Style:** Canvas fill, quiet border, compact curved edge.
- **Focus:** Indigo border and a visible translucent ring with at least 3:1 contrast.
- **Error / Disabled:** Error text accompanies destructive color; disabled controls remain readable and explain their prerequisite nearby.

### Switches

A switch turns a mode on or off and applies at once; it never waits for a Save, and a choice a form
saves is a checkbox or radio instead. It is `role="switch"` with its state as visible text beside
it ("On", "Off"), so it never relies on the thumb's position or color, and its label and the
sentence beside it say what it does now or would do before it is pressed. A feature's state and its
switch lead the page that manages the feature, before the things it applies to, as Plans' status
card does. Its result is a toast; a change that deletes nothing needs no confirmation.

### Limit Fields

A limit that may be unlimited is one segmented radio group, never a checkbox beside a number:
`No limit | Up to [- 3 +] rules`, and, where zero is a real choice, `None | Up to [- 2 +] |
No limit`. The number stays visible, dimmed, while another option is chosen, so switching back
keeps it. The number is a text field with a numeric keyboard and a stepper on each side, so a
scroll wheel never changes it. Its hint, above the control, says in one line what counts.

### Radio Cards

When each option of a choice needs a sentence, the options are radio cards: a bordered row per
option with its radio, an optional icon, a title, and a description, the chosen one outlined in
the palette's lantern color. Sync speed and Change plan use them. An option that cannot be chosen
stays visible, dimmed, with why ("Current").

### Selection and Bulk Actions

A table whose rows people act on together gives each row a checkbox and its header one that selects
the page, mixed when only some are. Selecting shows a bulk bar above the table, on Quiet Surface
with the panel radius: how many are selected, the actions, and Clear selection. Each bulk action is
also in each row's More actions for one person.

### Meters

A meter shows how much of a limit is in use: a thin track with a neutral fill (muted ink, never
the lantern color), always beside its numbers ("1 of 1") and a chip. At the limit the chip is
neutral, "Limit reached"; past it the fill turns Attention Ochre with diagonal stripes, and the
chip, "Over", carries the attention icon, with one sentence below on what keeps working and how to
make room. While the limit is not enforced, as while Plans are off, a count past it stays neutral
and its chip reads "Would be over". A count with no limit, or a thing the Plan does not include,
has no meter, only words.
Each meter is `role="meter"` with an `aria-valuetext` such as "2 of 1, over the limit". A compact
meter beside a limit is not a metric card.

### Toasts

A result that belongs to the page rather than a row, such as Plans turned on or a new default, is
a toast at the bottom of the window: an icon, one sentence ("Plans are on. They limit 2 people."),
and Undo when the change can be reversed. It is announced through one polite live region, never
takes focus, and stays until it is closed or the next result replaces it, so Undo is still there
when a keyboard or screen reader user reaches it. A result about one row still appears on that
row.

### Popovers

A popover holds one short choice beside the control that opened it, such as Change plan for the
selected people: a title, the choice, what it will do, and its one action with Cancel. It lifts
above the page as a menu does, takes focus when it opens, and Escape or Cancel closes it and
returns focus to its control. It never blocks the rest of the page, and anything longer is a side
panel.

### Data Tables

When people compare like things, such as Plans, a data table gives each comparable value a column:
a header row, one row per thing with its name as a link, counts right-aligned in tabular numerals,
"Unlimited" and "None" in muted text, chips beside a value they qualify, and a More actions menu
whose items carry descriptions and say why an item is disabled. Columns keep fixed widths, and
when the table itself is narrow each row becomes a card that labels its values, as People's
Everyone does. A data table is how an administration surface compares; it is not a chart wall.

### Side Panels

A side panel opens the selected row of a table beside it, at its own address, never as a modal:
Activity's entry and incident panels, and a Plan's panel on People. It may hold the form that
creates or edits the selected thing, with a footer holding its one primary action, Cancel, and how
many changes are not saved, and tabs when the thing has more than one side. While it is open the
table drops the columns it no longer has room for, and marks the open row as selected. Opening it
moves focus to its title; Close returns to the table's address and focus to the row it came from.
On a narrow screen it replaces the table.

### Navigation

The desktop top bar uses the ghost-mark-and-wordmark lockup, text labels, and a two-pixel active underline. Mobile replaces it with a full-width menu using the same labels and familiar icons. Navigation never competes with the current task.

### Overview Health Hero

A single expressive Overview surface combines a plain-language state, one sentence of detail, a quiet synchronization summary, and at most one action, each saying something the others do not. It is a status surface, not a metric-card grid. Its surface, the ghost's fill, and the ghost's face follow one health model, most urgent first:

| State | When | Surface | Ghost |
| --- | --- | --- | --- |
| Stopped | A rule is suspended until the administrator acts, such as reauthorizing a Google account | Destructive Red | Crying, calling for help |
| Needs a look | Rules keep running, but events were blocked or a problem kept happening | Attention Ochre | Concerned |
| Waiting | Google is limiting or failing requests; rules retry by themselves and nothing is asked of the administrator | Quiet Surface with Lantern Indigo | Neutral |
| Paused | Rules have synced before, but none is running now | Quiet Surface with Lantern Indigo | Asleep |
| Setup | Nothing is synchronizing yet; the Getting started steps carry progress | Quiet Surface | Neutral |
| Healthy | Every running rule is up to date | Healthy Moss | Happy |

Red asks the administrator to act now, ochre to take a look, and indigo only informs. When the
stopped rules share a Cause only the Installation Administrator can fix, the hero's title says
"Temporarily unavailable", naming neither the cause nor the administrator, and its one action is
Check access to try again; an administrator reading their own Overview reads the cause and is sent
to People instead. Waiting on Google says when the
rule was last tried and when it tries again. When one rule is the cause, the hero names it and its action opens that rule. The most urgent problem leads; every other current problem is listed under "Also" in a few words with its own link, so one never hides another. The ghost has no mouth: its eyes, brows, and tears carry the feeling. Its speech bubble reacts in a few words and never repeats the copy; a stopped ghost calls out slowly, one line at a time in a new place around it, and reduced motion keeps the first line still. The ghost illustration and bubble belong to this Overview-only moment; other pages keep the quieter surface grammar. The development preview starts in any state with `scripts/dev_preview.py --scenario`.

### Recent Changes

The Overview lists the latest runs that changed events, newest first, inside a contained timeline:
a semantic calendar marker, relative time, the event, the rule, and one sentence in calendar language
("Added 1 event and updated 2 in Family."). The marker carries a sign on its corner for what the
change did to the destination calendar: + added (including an event put back), − removed, ~ changed
(an event or a rule's settings), and × blocked, as a diff would mark them. Activity's What happened
column uses the same signs in a small tinted disc, with ✓ for already up to date, ⊘ for skipped, and
a pin for an event kept as an ordinary one, so one outcome never has two icons; the Overview line
beside a marker carries only words. Changes are moss, a
removal included, because removing an event is routine; blocked changes use Attention Ochre text and
link to that rule's Activity. Event titles appear only on request, as each run recorded them.

### Activity

While any Incident is kept, Activity has two link tabs under its title, each at its own address:
History (`/activity`), the table of what each run did, and Incidents (`/activity/incidents`). With
none, Activity is History alone, with no tabs; the Incidents address still answers with an empty
state. Filters and the open entry belong to History and stay in its query string. While an
Incident is open, the Incidents tab carries an Attention Ochre count of the open ones; at zero it
carries none. The page title follows the tab: "What your rules did" over History, "What needed
attention" over Incidents, each with its own sentence. Incidents is one card holding a table grouped
like History's days, each opened by the same quiet heading: a warning icon and "2 open" in
Attention Ochre, then a check and "5 resolved" in muted text. Each open row ends in an Attention
Ochre "Still open" chip, the tab's count repeated on the rows it counts, so a person who followed
it sees at once which rows it meant, before selecting any. Rows take no colored fill, which turns
muddy on the dark palettes; the icons, the headings, and the words say the same without color. A row is one line and, as in History, starts with its time:
when it opened, a warning icon (open) or a check (resolved) beside what happened, the rule's
calendars or the account, and when it closed with how long it lasted ("after 2 hours"), or "Still
open". Selecting a row opens the incident beside the table at its own address
(`/activity/incidents/<id>`), in the same panel History uses for an entry, never a modal: an Open or
Resolved chip, what happened, what it means or how it closed, the likely Cause when it is known,
one next step (the fix while open, with How to fix for an administrator's Cause, or the rule's
history once resolved), then when it opened, was last seen or closed, and the rule with its
accounts. The server decides the next step; an administrator's Cause shows its likely Cause and How to
fix only to an administrator, and anyone else reads that Google Calendar is not available right
now, with Check access. The table lists the server's most recent incidents and ends in "Load older
incidents" while it holds more; until then the last group's count reads as a floor ("100+
resolved"). While the panel is open the table drops its rule column, as History does. On a narrow
screen each row becomes a card that labels its values, and the panel replaces the table.

### Rule Rows

Each rule row shows its direction, policy, last run, status badge, and at most one visible next step (preview, review and start, or reauthorize). A rule starts only from its preview page, where the events it will write are in view; a previewed rule reads "Ready to start", or "Previewed" with the reason when its Plan would refuse Start. Routine commands such as Sync Now, Reconcile Now, and Pause live in a "More actions" menu whose items explain what each does and when it runs by itself. Command results appear on the row that ran them and are announced through one persistent live region.

### Page Titles

Pages carry no label above their title; the active navigation item already says where you are. Rule Details titles the page with the rule itself ("Family → Work").

### Rule Setting Icons

Each thing a rule decides has one icon, whatever it decides, and Rule Preview and Rule Details both
show it: a page for event information, a question mark for Maybe, an envelope for unanswered
invitations, a crossed circle for declined events, a calendar for all-day events, a cake for
birthdays, and a clock turning back for the starting point. On the preview each icon leads its
choice and reads quieter when the choice leaves events out; on Rule Details it leads the label in
the label's color, and the value says what the rule decides.

Both pages list the choices in this order, grouped as the policy form groups them: how events look,
then which events the rule includes. Rule Details puts each group in its own column; the preview
leaves out event information, which its privacy line already states. How many projections the rule
keeps is not a choice, so Rule Details shows it under Latest runs.

### Settings Groups

Settings sections run from what the installation depends on to what only this browser keeps: Connected accounts, Storage, Integrations, Appearance. Each section's heading and one sentence sit above a single group of rows with the same border, Quiet Surface fill, panel radius, and panel padding as the app's other cards; a row pairs a title and its current state with at most its own controls, and a section with nothing to show or change does not exist. Connect is one action, never a button per provider: "Connect Google account" when one provider is configured, otherwise a "Connect an account" menu whose items name each provider's account beside its mark and say that it opens that provider's sign-in. While no account exists it is primary and sits in the empty state, as it does in Getting started; after that it is an outline button in the section heading. Connected accounts collapse to one summary row naming how many there are and how many need reauthorization ("2 accounts, 1 needs reauthorization"), with their addresses grouped by provider ("Google: a, b · Microsoft: c"), and open by themselves when one does. Their avatars overlap only slightly, earlier ones on top, so initials stay whole. An account row names its provider beside its address, and shows its state chip, its one fix, and Check access; the fix that leaves for the provider's consent says so ("Reauthorize with Microsoft"); a lapsed account says so once, in its chip and its stopped rules, and Disconnect account waits in the row's "More actions" menu. Integrations, which most administrators never use, collapse the same way to one row naming how many tokens are in use and when one was last used. A newly issued token appears once, on Quiet Surface inside the group, in a read-only field with Copy beside it; revoked tokens gather under one disclosure at the end of the group. Plain HTTP on this machine or a home network is the homelab norm and says nothing; only an address that would carry a token across the internet unencrypted gets a quiet note in the group's footer. Conditions that need no action, such as Google and Microsoft returning to a different address, close the group they affect as a quiet disclosure on Quiet Surface, and become an Attention Ochre step only while the administrator can act on them. Providers that return elsewhere share one such note: it names the address when they agree and lists each provider's when they do not, has one field that finishes any of them because the returned address names its provider, and gives the fix once. Your plan, under Your account, is one card titled with the Plan's name, with a meter per limit as a person's page shows it, in the person's own words: a count past its limit reads "2 of 1" with an "Over" chip in Attention Ochre with an icon and a sentence on what keeps working and where to make room, never color alone, and the card closes by saying to ask the administrator, naming nobody.

### People

People is the Installation Administrator's view of everyone here, laid out like Rules and Activity:
a Fraunces title with one sentence and one primary action, then link tabs (Everyone first, then
Invitations with a count of those waiting, hidden at zero, then Plans). The sentence and the action
follow the tab, as Activity's title does: Everyone and Invitations say what an administrator sees
and offer "Invite someone", which says which Plan the person will get once a Plan is the default;
Plans says what Plans do and offers "New plan", outline while a side panel is open so the panel's
footer holds the one primary action. Plans sit beside the people they limit, so Settings keeps only
each person's own Your plan.

The Plans tab leads with a status card: the state as an object title ("Plans are on"), one
sentence on what Plans do now or, while they are off, would do once on, and the switch, which
applies at once and answers in a toast with Undo. Below them sit four facts: Limited now, Over a
limit (in Attention Ochre with an icon, and Show, which opens Everyone narrowed to those people),
Default plan, and Never limited, which explains why People counts include people Plans do not
limit. While Plans are off the facts say what turning on would do, and every over-limit chip on
the page turns neutral, because nothing is enforced. With no Plan, the card is followed by one
empty state whose action is New plan. Otherwise the catalog follows: a data table of Plans with one
column per limit, the default first with a "Default" badge, and People as a link to Everyone
filtered by the Plan, with an Attention Ochre "1 over a limit" chip linking to those of them over
it. Each row's More actions holds Edit, Assign people, Make default, which says whom it moves,
Duplicate, and Remove. Remove on the default, or on a Plan someone has, is disabled with its reason
as its description, naming the first three who have it by email and then how many more, instead
of a confirmation the server would refuse. There is no Default plan select and no "No default": a
Plan becomes the default only by Make default, and Plans are never on without one.

Selecting a Plan opens its side panel at its own address, with two tabs. Limits is the editor: a
name, never a key, refused before it is sent when another Plan has it; a Limit field per count,
with what counts as its hint; Sync speed as radio cards; and, under a limit typed lower than the
people on the Plan use, how many people it would leave with more, in Attention Ochre with an icon.
People is a searchable checklist of the people who do not have the Plan, each saying before anyone
confirms what they would be over, administrators last as never limited, then who has the Plan now.
While a Plan command is on its way, its controls stay focusable and wait, so focus never drops to
the page; a refusal shows under the field it names, which takes focus.

Everyone shows Installation Health in a card, then everyone here in one card holding its search,
filters, table, and pages, sorted by when people joined unless asked otherwise. Installation Health
leads with what the administrator must do: "Needs you" in Destructive Red with the likely causes only they can fix, or
"Nothing needs you" in Healthy Moss with one quiet sentence on how many people have something of
their own to fix ("1 of 4 people has something to fix on their own dashboard"). While something
needs them, a small red dot sits beside People in the navigation, read as "needs you". Then quiet
pill counts ("Show only: Stopped: 1, …, Disabled: 1") that set the list's Sync
and State filters to exactly the people counted, and read as pressed whenever the filters say the
same; "What each sync status means" opens below them. A person's sync status is a chip with an
icon, text, and its tone (red stopped, ochre needs a look, neutral otherwise, moss healthy);
Disabled is a neutral chip, because disabling is a choice, not an emergency. Table columns keep
fixed widths, and the list becomes cards when the list itself is narrow, not the window. A
command's result appears beside the person it changed. Once a Plan exists, the table has a Plan
column, the Plan's name with chips ("Default", "Over a limit" in Attention Ochre with an icon, "Not
limited" for an administrator), and the filters a Plan filter and a Limits filter, kept in the
address like the others. Rows can be selected; the bulk bar's Change plan opens a popover of radio
cards, "Follow the default plan" first, then each Plan with what it allows, which says before it is
confirmed who moves and who would be over. Each row's More actions and the person's page open the
same chooser for one person, and the result of a change for several people is a toast.

A person's page starts at their name, and the browser tab names them. It leads with a
Synchronization card: the verdict with how many rules run, then a problem several rules share,
such as a lapsed Google account, said once with the rules it stops, then each rule with its status
chip and last sync, and under a rule its own problems with who takes the next step: "Robin can fix this from their dashboard" for any
problem the person fixes themself, with a muted "If they ask for help: …" saying what they do, "You fix this as the administrator" with "How to fix" for the
installation's own, and nothing for the administrator to do otherwise. On their own page an
administrator reads the steps as their own, with a link to take each one, and their calendars by
name. Once a Plan exists, a Plan card follows Synchronization: who gave the Plan and when, whether it limits them
now, Change plan, the Plan's name as an object title, and one meter per limit with "1 of 1" and its
chip, past a limit with one sentence on what keeps working; an administrator's card says no Plan
limits administrators. With problems, a second card holds their accounts, Activity, and calls,
with one line on whether the calls look normal; with none, those close the one Synchronization card. Calendars of
anyone else appear only by number ("Calendar 1"), in the reader's language. The privacy note closes
the page as a footnote, and coming back to People returns to their row.
Settings does not show a person what administrators see about them.

A problem a provider refused carries its likely cause as a muted line under it ("Likely cause: the
Google Calendar API is turned off for this installation."), unless the problem already says it, as
"needs reauthorization" and "Waiting for Google" do. A problem only the administrator can fix sits on
Attention Ochre with its full border instead of the quiet well. Who acts follows the Cause's owner. For
an administrator's Cause, an administrator reads that the fix is theirs, with "How to fix" opening
the troubleshooting guide's section in a new tab, and the person reads only "Temporarily
unavailable", with no likely-cause line, no mention of the administrator, and no step only an
administrator can take. For a person's own Cause, the administrator
reads only "{name} can fix this from their dashboard" and is offered nothing to do, while the person
gets their one step. Installation Hints sit in the Installation Health card under "Likely causes",
between its sentence and its counts: one Attention Ochre row per hint with a lightbulb, one sentence
naming how many people it affects, and "How to fix". There is no way for an administrator to message
a person about a problem.

### Destructive and Privacy-Widening Changes

Removal shows its choice, its consequence, and a destructive button that names the effect in one step, with a neutral "Keep rule" beside it. A change that shows event details to more people uses Attention Ochre, says who will see them, and names the effect on its button.

## Do's and Don'ts

### Do:

- **Do** lead with current synchronization health and the next meaningful action.
- **Do** make rule direction, privacy policy, and exclusions readable before enablement.
- **Do** use list rhythm and progressive disclosure instead of nesting cards.
- **Do** implement hover, focus, active, disabled, loading, and error states for every control.
- **Do** preserve full keyboard operation, reduced motion, mobile structure, and non-color status cues.
- **Do** compare like things in a data table with a column per value, and keep sentences for hints, descriptions, and results.
- **Do** lead a page that manages a feature with the feature's state and its switch.

### Don't:

- **Don't** build a generic SaaS analytics dashboard with oversized metric cards, dense decorative charts, promotional copy, or a permanent icon-heavy sidebar. A compact meter beside a limit, and a data table on an administration surface, are not that.
- **Don't** imitate Google Calendar's visual language or calendar grid.
- **Don't** make setup or recovery resemble a terminal or infrastructure console.
- **Don't** reproduce a Datadog-style observability console with chart walls, compact technical labels, or excessive severity color.
- **Don't** use decorative shadows, gradient text, glass panels, colored side stripes, or display typography in controls.
