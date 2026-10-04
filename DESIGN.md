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

The layout uses a restrained top navigation and a readable central work area rather than a permanent dashboard sidebar. Stable information stays flat. Forms and workflows use familiar shadcn/ui affordances, while domain-specific health strips and directional rule rows carry the product language.

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

## Typography

**Display Font:** Fraunces (bundled variable font, SOFT axis 100), used only for page titles and the auth headline.

**Body Font:** Figtree (bundled variable font), used for all other text and every control.

**Character:** A quiet serif marks the handful of places the product wants to feel considered; a single humanist-leaning sans family keeps small status labels and longer guidance equally legible everywhere else. Both are bundled self-hosted woff2 with `font-display: swap`, so an offline Raspberry Pi renders them without a fallback to the device's system face.

### Hierarchy

Product text uses six steps: 2rem Fraunces page titles, 1rem Figtree section titles (weight 650), 1rem Figtree row titles (weight 550), 1rem Figtree body (weight 400), 0.875rem labels and controls (weight 600), and 0.8125rem supporting metadata. Settings and Rule Details section and row headings are aligned to these levels.

- **Headline**: Screen titles and the auth headline, in Fraunces at a strong but quiet scale.
- **Title**: Section titles and row titles (rule names, grouped settings, and recovery headings) in Figtree, distinguished by weight rather than size.
- **Body**: Instructions and explanations, capped near 70 characters per line.
- **Label**: Field labels, navigation, compact state, and metadata in sentence case.

### Named Rules

**The Calendar Language Rule.** Labels use the domain glossary and plain calendar terminology. Provider codes, tokens, and infrastructure terms remain in diagnostic details.

## Elevation

The system is flat by default. Tonal layering, dividers, and spacing establish structure. Only transient menus, dialogs, and toasts may lift above the page; stable panels never use decorative shadows.

### Named Rules

**The Stable Surface Rule.** A shadow signals a temporary layer. If a resting container appears to float, remove the shadow.

## Components

### Buttons

- **Shape:** Gently curved and compact.
- **Primary:** Lantern Indigo with a contrast-checked foreground, reserved for the next meaningful action.
- **Hover / Focus:** A small tonal change and a visible indigo focus ring over 180 milliseconds.
- **Secondary / Ghost:** Neutral structure for reversible and navigational actions.

### Chips

- **Style:** Full-pill semantic tint with text and an icon.
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

Red asks the administrator to act now, ochre to take a look, and indigo only informs. When one rule is the cause, the hero names it and its action opens that rule. The most urgent problem leads; every other current problem is listed under "Also" in a few words with its own link, so one never hides another. The ghost has no mouth: its eyes, brows, and tears carry the feeling. Its speech bubble reacts in a few words and never repeats the copy; a stopped ghost calls out slowly, one line at a time in a new place around it, and reduced motion keeps the first line still. The ghost illustration and bubble belong to this Overview-only moment; other pages keep the quieter surface grammar. The development preview starts in any state with `scripts/dev_preview.py --scenario`.

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

### Rule Rows

Each rule row shows its direction, policy, last run, status badge, and at most one visible next step (preview, start syncing, or reauthorize). Routine commands such as Sync Now, Reconcile Now, and Pause live in a "More actions" menu whose items explain what each does and when it runs by itself. Command results appear on the row that ran them and are announced through one persistent live region.

### Page Titles

Pages carry no label above their title; the active navigation item already says where you are. Rule Details titles the page with the rule itself ("Family → Work").

### Settings Groups

Settings sections run from what the installation depends on to what only this browser keeps: Connected accounts, Storage, Integrations, Appearance. Each section's heading and one sentence sit above a single bordered group of rows; a row pairs a title and its current state with at most its own controls, and a section with nothing to show or change does not exist. Connected accounts collapse to one summary row naming how many are connected and how many need reauthorization, and open by themselves when one does. Integrations, which most administrators never use, collapse the same way to one row naming how many tokens are in use and when one was last used. A newly issued token appears once, on Quiet Surface inside the group, in a read-only field with Copy beside it; revoked tokens gather under one disclosure at the end of the group. Plain HTTP on this machine or a home network is the homelab norm and says nothing; only an address that would carry a token across the internet unencrypted gets a quiet note in the group's footer. Conditions that need no action, such as Google returning to a different address, close the group they affect as a quiet disclosure on Quiet Surface, and become an Attention Ochre step only while the administrator can act on them.

### Destructive and Privacy-Widening Changes

Removal shows its choice, its consequence, and a destructive button that names the effect in one step, with a neutral "Keep rule" beside it. A change that shows event details to more people uses Attention Ochre, says who will see them, and names the effect on its button.

## Do's and Don'ts

### Do:

- **Do** lead with current synchronization health and the next meaningful action.
- **Do** make rule direction, privacy policy, and exclusions readable before enablement.
- **Do** use list rhythm and progressive disclosure instead of nesting cards.
- **Do** implement hover, focus, active, disabled, loading, and error states for every control.
- **Do** preserve full keyboard operation, reduced motion, mobile structure, and non-color status cues.

### Don't:

- **Don't** build a generic SaaS analytics dashboard with oversized metric cards, dense decorative charts, promotional copy, or a permanent icon-heavy sidebar.
- **Don't** imitate Google Calendar's visual language or calendar grid.
- **Don't** make setup or recovery resemble a terminal or infrastructure console.
- **Don't** reproduce a Datadog-style observability console with chart walls, compact technical labels, or excessive severity color.
- **Don't** use decorative shadows, gradient text, glass panels, colored side stripes, or display typography in controls.
