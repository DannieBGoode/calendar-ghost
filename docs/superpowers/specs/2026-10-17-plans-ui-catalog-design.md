# Plans UI: the catalog

Terms are in `CONTEXT.md`. This record replaces the Plans tab, People, and Your plan paragraphs of
the [Plans design](2026-10-15-plans-design.md), section 10.2, and keeps every server rule of
[ADR 0038](../../adr/0038-plans-allowances-and-limits.md) except the few listed under "Server
changes". The product owner approved it on 2026-10-17, after a third design review compared three
directions with static mockups, a critique, a code audit, and research into how other admin
products present plans. Those working files are not part of the repository; this record states
what the build needs from them.

## Why

The first Plans UI was correct and accessible, and the owner rejected how it read:

- Plans' on and off was a checkbox, "Limit people with plans", at the bottom of the Default plan
  card, coupled with a Default plan select and Save default. Nothing at the top said whether Plans
  were on, and the result appeared as loose text under the cards.
- The Default plan select offered "No default", although Plans are never on without a default.
- Each Plan was three lines of prose, so Plans could not be compared by limit.
- The limits were sentences ("Rules that can sync", "Calendar accounts they can connect"), and each
  was a "No limit" checkbox beside a number field that disappeared when it was checked.
- A Plan could be given only from a person's page, one person at a time.
- Usage was told in sentences and never shown.

## Direction A, "Catalog"

A status card with one switch and four facts, then a table of Plans with one column per limit and a
row menu, as a product catalog or a billing console shows them, in Calendar Ghost's own calm
surfaces. Selecting a Plan opens a side panel beside a narrower table, at the Plan's own address,
with two tabs: Limits, the editor, and People, who has the Plan and who could get it. It is
Activity's entry panel, generalized: beside the table, at its own address, never a modal, and in
place of the table on a narrow screen. Everyone gains row selection and a bulk Change plan, a
person's page gains a Plan card with meters, and Your plan becomes meters with text.

Two other directions were rejected: plan pages with a side-by-side ladder, which stops working past
about five Plans and leaves the catalog to edit or assign, and a split-view workspace that edits in
place, which compares only one Plan at a time and carries the most accessibility risk.

## The owner's decisions

1. **Labels.** The editor's limits are "Maximum active rules", "Maximum calendar accounts",
   "Maximum integration tokens", and "Sync speed"; columns and usage say "Active rules", "Calendar
   accounts", "Integration tokens", and "Sync speed" (sentence case, the glossary term too).
   Calendar accounts are never "active": Disconnected Accounts count. CONTEXT.md defines
   Active Rule.
2. **One switch, first.** One Plans on and off switch, at the top of the Plans tab in a status
   card, which applies at once and says the result in a toast.
3. **No "No default", no Default plan card.** The default is a "Default" badge on its Plan, and
   every other Plan has "Make default" in its row menu.
4. **A side panel.** Edit and Assign people open in a non-modal side panel at `/people/plans/<key>`,
   and New plan at `/people/plans/new`, as Activity's entry panel does.
5. **Assigning from the Plan.** A searchable checklist, with a dry run that says who would be over
   before the administrator confirms. Administrators are listed last, marked as never limited.
6. **Bulk Change plan from Everyone.**
7. **The person page's Plan card** with a meter per limit.
8. **Your plan as meters with text,** never color alone. It says to ask the administrator without
   naming anyone.
9. **Invite someone names the Plan** the person will get once a Plan is the default: "They get the
   default plan, {name}. You can change it after they join." Invitations still carry no Plan.
10. **Out of scope:** locking the switch while Commercial Mode is on ("Billing manages plans"),
    which waits for the billing design.

## Kept from the earlier rounds

Every behavior the earlier rounds built and tested stays:

- Plan names are unique whatever their case; the form refuses a name another Plan has before
  sending it ("Another plan is named Free. Choose a different name."), with focus on Name.
- A Plan's key is made from its name, and the Web UI neither asks for it nor shows it.
- Who is over a limit is computed by the Operator Overview, as `has`, `over`, `over_people`, and
  `use`; the Web UI computes no counts of its own.
- Limit hints fail open: when Your plan cannot be read, every hint is left out and every control
  works, and the server still checks.

## Screens

The examples use one installation: No limits (the default, unlimited, Instant), Free (1 active
rule, 1 calendar account, no Integration Tokens, every 5 minutes), and Pro (unlimited, Instant).
alex@example.test has the default, robin@example.test and jordan@example.test have Free, and
sam@example.test has Pro; robin has 2 calendar accounts, so is over Free. dana@example.test
administers.

### People's header

People's sentence and primary action follow the tab, as Activity's title does. Everyone and
Invitations keep the privacy sentence and Invite someone. Plans says "Plans set how much each person
can use and how soon their calendars sync." and has no action in the header: New plan sits at the
right of the catalog's head, beside "3 plans", on the list it adds to, and is outline while a panel
is open, so the panel's footer holds the one primary action. With no Plan, New plan lives in the
empty state.

### Plans tab

1. **Status card.** Its title is the state, "Plans are on" or "Plans are off", with one sentence
   that says what the facts cannot, never a count or a name a fact shows, and the switch, labelled
   "On" or "Off" beside it:
   - On: "People can't add more than their plan allows. Anyone without a plan of their own,
     including people who join later, gets the default plan."
   - Off, with Plans: "Nobody is limited. Turning plans on applies each person's plan at once.", and
     with no default ", and adds a plan named No limits as the default for everyone without a plan
     of their own."
   - Off, with no Plan: "Everyone can use everything, with no limits. Turning plans on adds a plan
     named No limits as the default, so nobody is limited until you give someone a smaller plan."

   Below, three facts, one equal column each: "Limited now", "Over a limit" (in Attention Ochre
   with an icon, its number the link that opens Everyone narrowed to people over a limit, "⚠ 1
   person ›", named "Show the 1 person over a limit"), and "Default plan". On a narrow card the
   first two lead side by side and "Default plan" follows on one quieter line, one line at 390 px.
   While Plans are
   off they read "Would limit" and "Would be over a limit", neutral, because nothing is enforced.
   With no Plan, the card has no facts.
2. **Catalog table,** titled "3 plans", with New plan at the right of its head and no instruction
   under it. Columns: Plan, Active rules, Calendar accounts, Integration tokens, Sync speed, People,
   and More actions. The default comes first, then the others by name. The Plan cell heads its row: the Plan's name, a link that opens
   its panel, with a "Default" badge beside the default's name. A press anywhere else on the row
   opens the same panel, as Activity's rows do. Names and People counts read as ink, underlined
   only under the pointer or keyboard focus. The Plan column takes what the fixed columns leave;
   counts are right-aligned in tabular numerals under right-aligned headings that wrap rather than
   overhang; a limit reads in ink, numbers and "None" alike, and "Unlimited" and "Nobody" are
   muted. Sync speed is "Instant" with a lightning icon or "Every 5 min" with a clock, on the row's
   line of text, a little apart from the counts. People is
   a link, "2 people", to Everyone filtered by the Plan, with a chip "1 over a limit" in Attention
   Ochre with an icon on the same line that links to the same list narrowed to people over ("1
   would be over", neutral, while Plans are off). Rows are 48 px. A footnote, its icon on its first
   line, says "People counts include administrators, who are never limited. Paused rules and
   drafts are not active.", the one place the page says it.
3. **Row menu** (the existing More actions menu, whose items carry descriptions): Edit; Assign
   people; Make default, described "People without a plan of their own (2 now) move to Free.", and,
   for people given the current default as their own Plan, "1 person keeps No limits, which was
   given to them."; Duplicate; and, after a divider, Remove. Remove is disabled with its reason as its description
   on the default ("Make another plan the default first.") and on a Plan someone has, which names
   them, the first three by email and then how many more, the count alone until the names arrive
   ("2 people have Free. Give them another plan first."). On any other Plan it confirms inline, the
   confirmation scrolling fully into view as it opens. A
   refused removal reads the Plans again; when someone has the Plan now, the confirmation gives way
   to the refusal under the row, focus goes to More actions, and its Remove says who has it. The
   menu, like a popover, opens above its button when there is more room there, and stays clear of
   the top bar and a toast.
4. **Results** of the switch, Make default, and Remove are toasts: "Plans are on. They limit 2
   people." with Undo, "Plans are off. Nobody is limited." with Undo, "Free is the default plan
   now." with Undo, and "Free was removed."
5. **Narrow screens.** Below a 56rem catalog, each row becomes a card that labels its values, as
   Everyone's rows do.

### Plan panel: Limits

The panel opens beside the table at `/people/plans/<key>`, or `/people/plans/new` for New plan.
While it is open, the status card keeps only its title, one short sentence ("They limit 2 people.
People without a plan get No limits."), and the switch; the table keeps Plan, Sync speed, and
People, marks the open Plan's row as selected, and its footnote says "Changes apply as soon as you
save. Nobody loses anything they already have."

- **Head.** "Plan" as a label, the Plan's name as an object title, and one line on who has it and
  what it allows ("1 person has Pro. Unlimited, with Instant sync."), then Close, which returns to
  `/people/plans`, the page to where it was before the panel opened, and focus to the Plan's row.
  Tabs: Limits and People, with how many have it.
- **Fit.** The panel fits the window below where it starts, so its footer with Save is in view as
  it opens, and only its body scrolls; once it sticks under the top bar it is as tall as the room
  there.
- **Name,** with "People see this name in Your plan."
- **"Limits for each person",** each limit with its hint and a segmented control:
  - "Maximum active rules": "Running rules count, and rules waiting for an account to be
    reauthorized. Paused rules and drafts don't." `No limit | Up to [- 3 +] rules`.
  - "Maximum calendar accounts": "Every connected account counts, disconnected ones too.
    Reconnecting is never refused." `No limit | Up to [- 3 +] accounts`.
  - "Maximum integration tokens": "Revoked tokens don't count." `None | Up to [- 2 +] | No limit`.
  - The number stays visible, dimmed, while No limit or None is chosen, so switching back keeps
    it. It is a text field with a numeric keyboard, so a scroll wheel never changes a limit.
  - Where the field is too narrow for its options on one line, as on a phone, they stack as a list,
    each a full-width row; wider, an option that wraps fills its line.
  - A limit lower than the people on the Plan use warns under it, in Attention Ochre with an icon,
    counted from `use` and naming nobody: "1 person on Pro has more active rules than this. Their
    rules keep syncing, but they can't start another." While Plans are off its second sentence
    starts "Once plans are on, ...".
- **Sync speed,** "How soon changes reach the other calendars.", as six radio cards: "Instant",
  "Changes sync soon after the calendar provider reports them, with a check every 5 minutes as a
  backup.", then "Every 5 minutes", "Calendars are checked for changes every 5 minutes.", and so on
  for every 10, 15, and 30 minutes, and "Every hour", "Calendars are checked for changes every
  hour." Instant promises no delivery time, so the card does not say "within seconds".
- **Footer:** Save plan (primary), Cancel, and how many changes are not saved ("1 change not
  saved"). Save names the field it waits for; a refusal shows under the field it names, which takes
  focus.
- **New plan** opens the same panel titled "New plan", with no People tab, an empty name, every
  count at No limit, and Instant; Duplicate opens it with the Plan's limits and the name "Free
  copy", checked like any name.
- **Saving** closes the panel once the server answers, without asking, since nothing is left to
  discard. `/people/plans` replaces the panel's address, so Back never returns to an empty New
  plan, and focus goes to the Plan's name in the table, or to New plan while a new Plan is not
  listed yet. A toast says what happened: "Free was saved.", or, for a new Plan or a duplicate,
  "Free was added." with Assign people, which opens the Plan's People tab with focus on the
  panel's title, and stays until it is closed or replaced. Save with nothing changed only closes
  the panel. A refusal keeps it open, and changes not saved still ask before it closes.

### Plan panel: People

At `/people/plans/<key>/people`, which Assign people in the row menu opens.

- **Assign people,** "They move to Free at once. Administrators are listed last; no plan limits
  them." On the default's panel it gives the default as following it, as Change plan does: "They
  follow Free, the default plan, at once, and move with it when the default changes.", and sends
  no Plan of their own. A search field by email with how many it found, then a checklist of the people who do not
  have the Plan. Each shows their email, the Plan they have ("Has No limits, the default", "Has
  Pro"), and, from a dry run before anyone confirms, what they would be over in Attention Ochre
  with an icon ("Would be over: 3 active rules, Free allows 1"). Administrators follow under
  "Administrators", each "Never limited, whatever plan they have", the reader marked "You".
- Whoever is checked stays checked while a search hides them, and the dry run still asks about
  them, so the note below still names them.
- When a checked person would be over, a note says what that means: "alex@example.test will have
  more than Free allows. Their 3 active rules keep syncing, but they can't start another until only
  1 is active."
- **Have Free now,** with "Show in Everyone": each person with what they are over ("2 calendar
  accounts, 1 allowed") or "Within every limit", and Change plan.
- **Footer:** "Give Free to 1 person" (primary), Cancel, and "1 selected". The result is a toast,
  "alex@example.test now has Free." or "2 people now have Free.", with Undo, which gives each person
  back the Plan they had. With more than 100 chosen, the most the server gives a Plan to at once,
  Give waits and says "Choose at most 100 people at a time."

### Everyone

- Header sentence: "The people who sign in here and whether their synchronization works. You see
  their email, role, plan, and sync status, never their calendars, connected account emails, or
  events."
- Once a Plan exists, the filters are Search by email, Role, Sync, Plan ("Any plan", each Plan,
  the default as "No limits (default)"), and Limits ("Anyone", "Over a limit"), each kept in the
  address.
- The Plan column is the Plan's name with chips: "Default", "Over a limit" in Attention Ochre with
  an icon ("Would be over", neutral, while Plans are off), and "Not limited" for an administrator,
  then which limit someone is over on a muted line under them ("2 calendar accounts, 1 allowed").
  Each email heads its row, in ink, underlined only under the pointer or keyboard focus.
- Row checkboxes, with one in the header for the page that can be mixed. Selecting shows a bulk bar
  above the table: "2 selected", Change plan, and Clear selection.
- **Change plan** opens a popover, "Change plan for 2 people", with the one compact chooser
  Change plan uses everywhere: one row per Plan, the default first with its "Default" badge, each
  with its limits in short beside its name ("1 rule, 1 account, no tokens, every 5 min",
  "Unlimited, Instant"). There is no separate "Follow the default plan": choosing the default Plan
  means they follow it, and one line under the rows says so: "People on the default plan move
  with it when the default changes." While no Plan is the default, "No plan" comes last ("Nothing
  limits them until a plan is the default."). What all of them have now is chosen and marked
  "Current", their own default Plan included; when they differ, nothing is chosen and each Plan
  says how many have it ("1 has it"). Once another Plan is chosen, a dry run says under it, in a
  live region, who would be over and which limit ("robin@example.test would be over: 2 calendar
  accounts, 1 allowed", "2 people would be over a limit") in Attention Ochre with its icon while
  Plans are on, or "Nobody would be over a limit". Then Save and Cancel. Save with what they have
  now closes it and sends nothing; with nothing chosen it says "Choose a plan first." and moves
  focus to the first Plan. Focus starts on the Plan chosen.
- The popover never leaves the window, on a phone too: it opens under its control, or above it
  when there is more room there, below the top bar and above a toast. Its height is capped at the
  room it has and its rows scroll inside it, while its title, note, and Save stay in view; a
  control with little room on both sides is first scrolled up, as far as the page scrolls. While
  rows sit below the cut edge, they fade out at it, and the fade is gone at the end of the list; a
  screen reader still has every row.
- Each row's More actions holds Change plan, which opens the same chooser for that person, titled
  "Change plan for robin@example.test".
- A change for one person or several answers in a toast, "robin@example.test now has Pro." or "2
  people now have Pro.", with Undo, which gives each person back the Plan they had.

### A person's page

A Plan card follows the Synchronization card once any Plan exists.

- Title "Plan", with who gave it and whether it limits them now: "Given by dana@example.test on Oct
  12. Plans are on, so it limits robin@example.test now.", "The default plan. Plans are off, so it
  limits nobody yet.", or, for an administrator, "No plan limits administrators." Change plan
  (outline) opens the same chooser as Everyone's inside the card, in place of the Plan's name,
  titled "Change plan", since the page names them, so their usage stays in view under it. It
  scrolls fully into view as it opens, with focus on the Plan chosen. Save or Cancel closes it and
  returns focus to Change plan; the result is a toast with Undo ("robin@example.test now has
  Free.").
- The Plan's name as an object title, with "Default" and "Over a limit" chips as in Everyone.
- One row per limit: its name and what counts ("Running, or waiting for reauthorization",
  "Disconnected accounts count", "Revoked tokens don't count", "How soon changes reach other
  calendars"), a meter, "1 of 1", and a chip: neutral "Limit reached" at the limit, Attention Ochre
  "Over" with an icon past it, with a sentence: "robin@example.test has 2 calendar accounts and Free
  allows 1. Their accounts keep syncing, but they can't connect another until one is removed. They
  see the same on Your plan." While Plans are off, a count past its limit stays neutral with "Would
  be over". Unlimited reads "3 in use" and "No limit" with no meter; Integration Tokens that the Plan
  does not include read "Free includes none." and "Not included"; Sync speed reads "Instant sync is
  not part of Free." and "Every 5 minutes".
- The privacy footnote becomes "You see whether their synchronization works and how much of their
  plan they use, never their calendar names, connected account emails, or events."

### Your plan

Under Settings, Your account, "Your plan", with "What you can use here, and how much of it you use
now." One card titled with the Plan's name and an "Over a limit" chip when it applies, with "Set by
your administrator" or "The default plan". Then the person page's rows, in the person's words:
"Running rules, and rules waiting for you to reauthorize an account. Paused rules and drafts don't
count."; "To start another rule, pause one first." at the rule limit; past the account limit, "You
have 2 calendar accounts and your plan allows 1. They keep syncing, but you can't connect another
until you remove one in Connections.", linking to Connections; "Your plan does not include
integration tokens."; and "Instant sync is not part of your plan." It closes with "To change your
plan, ask your administrator." An administrator reads "You administer this installation, so no plan
limits you." Your plan stays hidden while Plans are off and under Only Me, and arriving by "See your
plan" still moves focus to its heading.

### Invite someone

Once a Plan is the default, the Invite form says "They get the default plan, Free. You can change
it after they join." With no default, or when Plans cannot be read, it says nothing about Plans.

### States

- **First visit** (Plans off, no Plan): the status card with its switch, then one empty state with
  the ghost: "No plans yet", "A plan sets how many rules, calendar accounts, and integration tokens
  a person can have, and how soon their calendars sync. Make one, then give it to people or make
  it the default.", and New plan, the page's one primary action.
- **Off, with Plans:** the status card says what turning on would do, and over-limit chips are
  neutral.
- **Right after a change:** a toast with Undo, never loose text under the cards.
- **Loading:** skeletons in the shape of the status card and the table, so nothing moves when the
  data arrives.
- **Could not load:** "Plans could not load. Nothing changed: the limits people had still apply."
  with Try again.

## Components

The build adds these primitives under `web/src/components/ui`, each with unit tests for its keyboard
behavior and roles, and DESIGN.md describes them:

- **Switch** (`role="switch"`) with its visible "On" or "Off" label and a 44 px target.
- **Limit field:** a segmented radio group of No limit, Up to with a stepper, and, for tokens, None.
- **Radio cards:** a radio group whose options carry a title, an icon, and a description.
- **Radio rows:** a radio group of compact rows: a title with badges, a short summary, and a line
  under each row, a live region, for what choosing it would do.
- **Checkbox,** with a mixed state for the header.
- **Meter** (`role="meter"` with `aria-valuetext`, such as "2 of 1, over the limit").
- **Toast** with one polite live region, an optional Undo or one next step, such as Assign people
  for a Plan just added, and no timeout shorter than a person needs: one with Undo or a next step,
  or a refusal, stays until closed or replaced; any other leaves after six seconds, and waits while
  the pointer or focus is on it.
- **Popover** for the Change plan chooser in Everyone: it takes focus, Escape or Cancel returns it,
  and it stays inside the window, flipping above its control and capping its height. The row menu
  shares its placement (`keep-in-window.ts`), so a menu never runs under the window's foot, the
  footer, or a toast, and a disabled item's reason stays readable.

The side panel reuses Activity's layout and `DetailToolbar`; the row menu reuses `OverflowMenu`;
search reuses `SearchField`. The popover, the person page's card, and a Plan's People tab share
one Change plan component.

## Server changes

[ADR 0038](../../adr/0038-plans-allowances-and-limits.md) records the server changes this design
needed. `PUT /api/v1/plan-settings` does not change: the switch sends the saved default with the
new `enabled`, and Make default sends the saved `enabled` with the new `default_plan`.

## Accessibility

- Every status combines color with text and an icon; meters always have their numbers beside them.
- Controls reach 44 px on a coarse pointer, the base Button, Input, and NativeSelect included.
- A Plan's name heads its row in the catalog, and a person's email in Everyone, so a screen reader
  names the row as it moves down a column.
- The panel is not modal: opening it moves focus to its title, Close returns it to the row, and the
  rest of the page stays usable. Change plan moves focus to the Plan chosen, the arrow keys move
  the choice, and Escape or Cancel closes it and returns focus to its button.
- The switch, the bulk bar, and every command keep focus with `aria-disabled` while they wait.
- Checked at 390 and 1440 px, in light, dark, and Midnight, with the pseudo-locale and 200% text.
