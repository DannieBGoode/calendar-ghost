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
   "Maximum Integration Tokens", and "Sync speed"; columns and usage say "Active rules", "Calendar
   accounts", "Integration Tokens", and "Sync speed". Calendar accounts are never "active":
   Disconnected Accounts count. CONTEXT.md defines Active Rule.
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

- Turning Plans on with no default adds the ordinary Plan "No limits" as the default.
- Plan names are unique whatever their case; the form refuses a name another Plan has before
  sending it ("Another plan is named Free. Choose a different name."), with focus on Name.
- A Plan's key is made from its name, and the Web UI neither asks for it nor shows it.
- Who is over a limit is computed by the Operator Overview, as `has`, `over`, `over_people`, and
  `use`; the Web UI computes no counts of its own.
- Limit hints fail open: when Your plan cannot be read, every hint is left out and every control
  works, and the server still checks.
- While a command is on its way, its controls keep focus with `aria-disabled`; a refusal shows
  under the control or field it names, which takes focus; results reach screen readers through
  one live region.
- The lowered-limit warning, counted from `use`; Remove refused with who has the Plan; the
  `?plan=` filter.
- Sync speed offers only Instant and Every 5 minutes, with "Longer intervals arrive in a later
  release." The 10 to 60 minute intervals stay out until the scheduler honors them.

## Screens

The examples use one installation: No limits (the default, unlimited, Instant), Free (1 active
rule, 1 calendar account, no Integration Tokens, every 5 minutes), and Pro (unlimited, Instant).
alex@example.test has the default, robin@example.test and jordan@example.test have Free, and
sam@example.test has Pro; robin has 2 calendar accounts, so is over Free. dana@example.test
administers.

### People's header

People's sentence and primary action follow the tab, as Activity's title does. Everyone and
Invitations keep the privacy sentence and Invite someone. Plans says "Plans set how much each person
can use and how soon their calendars sync. Administrators are never limited." with New plan, which
is outline while a panel is open, so the panel's footer holds the one primary action. With no Plan,
New plan lives only in the empty state.

### Plans tab

1. **Status card.** Its title is the state, "Plans are on" or "Plans are off", with one sentence on
   what Plans do now or would do, and the switch, labelled "On" or "Off" beside it:
   - On: "Plans limit 2 people right now. Everyone without a plan of their own gets No limits, the
     default plan, including people who join later."
   - Off, with Plans: "Everyone can use everything. Your 3 plans are kept. Turning plans on limits 2
     people right away, and 1 of them has more than their plan allows."
   - Off, with no Plan: "Everyone can use everything, with no limits. Turning plans on adds a plan
     named No limits as the default, so nobody is limited until you give someone a smaller plan."

   Below, four facts in a row (two by two on a narrow screen): "Limited now", "Over a limit" (with
   an icon in Attention Ochre and "Show", which opens Everyone narrowed to people over a limit),
   "Default plan", and "Never limited" ("1 administrator"). While Plans are off they read "Would
   limit" and "Would be over a limit", neutral, because nothing is enforced. With no Plan, the card
   has no facts.
2. **Catalog table,** titled "3 plans" with "Select a plan to edit it or give it to people."
   Columns: Plan, Active rules, Calendar accounts, Integration Tokens, Sync speed, People, and More
   actions. The default comes first, then the others by name. The Plan cell is the Plan's name, a
   link that opens its panel, with a "Default" badge and "Everyone without a plan of their own"
   under the default's name. Counts are right-aligned in tabular numerals; "Unlimited" and "None"
   are muted. Sync speed is "Instant" with a lightning icon or "Every 5 min" with a clock. People is
   a link, "2 people", to Everyone filtered by the Plan, with a chip "1 over a limit" in Attention
   Ochre with an icon that links to the same list narrowed to people over ("1 would be over",
   neutral, while Plans are off). A footnote says "People counts include administrators, who are
   never limited. Paused rules and drafts never count as active."
3. **Row menu** (the existing More actions menu, whose items carry descriptions): Edit; Assign
   people; Make default, described "People without a plan of their own (2 now) move to Free.";
   Duplicate; and, after a divider, Remove. Remove is disabled with its reason as its description
   on the default ("Make another plan the default first.") and on a Plan someone has, which names
   them, the first three by email and then how many more, the count alone until the names arrive
   ("2 people have Free. Give them another plan first."). On any other Plan it confirms inline.
4. **Results** of the switch, Make default, and Remove are toasts: "Plans are on. They limit 2
   people." with Undo, "Plans are off. Nobody is limited." with Undo, "Free is the default plan
   now." with Undo, and "Free was removed."
5. **Narrow screens.** Each row becomes a card that labels its values, as Everyone's rows do.

### Plan panel: Limits

The panel opens beside the table at `/people/plans/<key>`, or `/people/plans/new` for New plan.
While it is open, the status card keeps only its title, one short sentence ("They limit 2 people.
People without a plan get No limits."), and the switch; the table keeps Plan, Sync speed, and
People, marks the open Plan's row as selected, and its footnote says "Changes apply as soon as you
save. Nobody loses anything they already have."

- **Head.** "Plan" as a label, the Plan's name as an object title, and one line on who has it and
  what it allows ("1 person has Pro. Unlimited, with Instant sync."), then Close, which returns to
  `/people/plans` and focus to the Plan's row. Tabs: Limits and People, with how many have it.
- **Name,** with "People see this name in Your plan."
- **"Limits for each person",** each limit with its hint and a segmented control:
  - "Maximum active rules": "Running rules count, and rules waiting for an account to be
    reauthorized. Paused rules and drafts don't." `No limit | Up to [- 3 +] rules`.
  - "Maximum calendar accounts": "Every connected account counts, disconnected ones too.
    Reconnecting is never refused." `No limit | Up to [- 3 +] accounts`.
  - "Maximum Integration Tokens": "Revoked tokens don't count." `None | Up to [- 2 +] | No limit`.
  - The number stays visible, dimmed, while No limit or None is chosen, so switching back keeps
    it. It is a text field with a numeric keyboard, so a scroll wheel never changes a limit.
  - A limit lower than the people on the Plan use warns under it, in Attention Ochre with an icon,
    counted from `use` and naming nobody: "1 person on Pro has more active rules than this. Their
    rules keep syncing, but they can't start another." While Plans are off it starts "Once plans
    are on, ...".
- **Sync speed,** "How soon changes reach the other calendars.", as two radio cards: "Instant",
  "Changes sync soon after the calendar provider reports them, with a check every 5 minutes as a
  backup.", and "Every 5 minutes", "Calendars are checked for changes every 5 minutes.", then
  "Longer intervals arrive in a later release." Instant promises no delivery time, so the card does
  not say "within seconds".
- **Footer:** Save plan (primary), Cancel, and how many changes are not saved ("1 change not
  saved"). Save names the field it waits for; a refusal shows under the field it names, which takes
  focus.
- **New plan** opens the same panel titled "New plan", with no People tab, an empty name, every
  count at No limit, and Instant; Duplicate opens it with the Plan's limits and the name "Free
  copy", checked like any name. A saved new Plan's panel moves to its own address.

### Plan panel: People

At `/people/plans/<key>/people`, which Assign people in the row menu opens.

- **Assign people,** "They move to Free at once. Administrators are listed last; no plan limits
  them." A search field by email with how many it found, then a checklist of the people who do not
  have the Plan. Each shows their email, the Plan they have ("Has No limits, the default", "Has
  Pro"), and, from a dry run before anyone confirms, what they would be over in Attention Ochre
  with an icon ("Would be over: 3 active rules, Free allows 1"). Administrators follow under
  "Administrators", each "Never limited, whatever plan they have", the reader marked "You".
- When a checked person would be over, a note says what that means: "alex@example.test will have
  more than Free allows. Their 3 active rules keep syncing, but they can't start another until only
  1 is active."
- **Have Free now,** with "Show in Everyone": each person with what they are over ("2 calendar
  accounts, 1 allowed") or "Within every limit", and Change plan.
- **Footer:** "Give Free to 1 person" (primary), Cancel, and "1 selected". The result is a toast,
  "alex@example.test now has Free." or "2 people now have Free.", with Undo, which gives each person
  back the Plan they had.

### Everyone

- Header sentence: "The people who sign in here and whether their synchronization works. You see
  their email, role, plan, and sync status, never their calendars, connected account emails, or
  events."
- Once a Plan exists, the filters are Search by email, Role, Sync, Plan ("Any plan", each Plan,
  the default as "No limits (default)"), and Limits ("Anyone", "Over a limit"), each kept in the
  address.
- The Plan column is the Plan's name with chips: "Default", "Over a limit" in Attention Ochre with
  an icon ("Would be over", neutral, while Plans are off), and "Not limited" for an administrator.
- Row checkboxes, with one in the header for the page that can be mixed. Selecting shows a bulk bar
  above the table: "2 selected", Change plan, and Clear selection.
- **Change plan** opens a popover: "Change plan for 2 people", who has what now
  ("robin@example.test and jordan@example.test have Free now."), then radio cards: "Follow the
  default plan" first ("No limits now. If the default changes, so does theirs."), then each Plan
  with what it allows ("1 active rule, 1 calendar account, no Integration Tokens, every 5
  minutes"); the Plan all of them have now is marked "Current" and cannot be chosen. Under the
  choice, the dry run's result: "Both move from Free to Pro. robin@example.test is no longer over
  a limit." or what anyone would be over. Then "Give Pro to 2 people" and Cancel.
- Each row's More actions holds Change plan, which opens the same chooser for that person.
- A change for one person shows its result on their row, as every People command does; a change
  for several answers in a toast, "2 people now have Pro.", with Undo.

### A person's page

A Plan card follows the Synchronization card once any Plan exists.

- Title "Plan", with who gave it and whether it limits them now: "Given by dana@example.test on Oct
  12. Plans are on, so it limits robin@example.test now.", "The default plan. Plans are off, so it
  limits nobody yet.", or, for an administrator, "No plan limits administrators." Change plan
  (outline) opens the same chooser as Everyone's, and its result names the Plan on the card
  ("robin@example.test now has Free."), in a status a screen reader announces.
- The Plan's name as an object title, with "Default" and "Over a limit" chips as in Everyone.
- One row per limit: its name and what counts ("Running, or waiting for reauthorization",
  "Disconnected accounts count", "Revoked tokens don't count", "How soon changes reach other
  calendars"), a meter, "1 of 1", and a chip: neutral "Limit reached" at the limit, Attention Ochre
  "Over" with an icon past it, with a sentence: "robin@example.test has 2 calendar accounts and Free
  allows 1. Both keep syncing, but they can't connect another until one is removed. They see the
  same on Your plan." While Plans are off, a count past its limit stays neutral with "Would be
  over". Unlimited reads "3 in use" and "No limit" with no meter; Integration Tokens that the Plan
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
have 2 calendar accounts and your plan allows 1. Both keep syncing, but you can't connect another
until you remove one in Connections.", linking to Connections; "Your plan does not include
Integration Tokens."; and "Instant sync is not part of your plan." It closes with "To change your
plan, ask your administrator." An administrator reads "You administer this installation, so no plan
limits you." Your plan stays hidden while Plans are off and under Only Me, and arriving by "See your
plan" still moves focus to its heading.

### Invite someone

Once a Plan is the default, the Invite form says "They get the default plan, Free. You can change
it after they join." With no default, or when Plans cannot be read, it says nothing about Plans.

### States

- **First visit** (Plans off, no Plan): the status card with its switch, then one empty state with
  the ghost: "No plans yet", "A plan sets how many rules, calendar accounts, and Integration Tokens
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
- **Checkbox,** with a mixed state for the header.
- **Meter** (`role="meter"` with `aria-valuetext`, such as "2 of 1, over the limit").
- **Toast** with one polite live region, an optional Undo, and no timeout shorter than a person
  needs: it stays until closed or replaced.
- **Popover** for the Change plan chooser: it takes focus, and Escape or Cancel returns it.

The side panel reuses Activity's layout and `DetailToolbar`; the row menu reuses `OverflowMenu`;
search reuses `SearchField`. The popover and the person page's chooser share one Change plan
component.

## Server changes

[ADR 0038](../../adr/0038-plans-allowances-and-limits.md)'s 2026-10-17 amendment records them:

- `POST /api/v1/plan-assignments` (administrator) gives one Plan, or the default with `null`, to up
  to 100 people at once, all or none, with one `AssignmentChange` and one log line per person, and
  answers each person's Plan before and after and what they are over. With `dry_run` it writes
  nothing and answers the same. It refuses an unknown Plan with 404 `plan_not_found`, and no
  people, more than 100, or someone who is not a User with 422 `invalid_assignment`.
- `GET /api/v1/users?over=true` lists the people over a limit of the Plan they have.
- The person's Plan gains `assigned_by`, `assigned_at`, and `use`: their Active Rules, Connected
  Accounts, and unrevoked Integration Tokens
  ([ADR 0030](../../adr/0030-users-administrators-and-registration.md), amended, for the token
  count).
- The Plans overview gains how many administrators there are, for the Never limited fact.
- No Plan has the key `new`, which `/people/plans/new` names.
- `PUT /api/v1/plan-settings` does not change: the switch sends the saved default with the new
  `enabled`, and Make default sends the saved `enabled` with the new `default_plan`.

## Accessibility

- Every status combines color with text and an icon; meters always have their numbers beside them.
- Controls reach 44 px on a coarse pointer.
- The panel is not modal: opening it moves focus to its title, Close returns it to the row, and the
  rest of the page stays usable. A popover takes focus, and Escape or Cancel closes it and returns
  focus to its button.
- The switch, the bulk bar, and every command keep focus with `aria-disabled` while they wait.
- Checked at 390 and 1440 px, in light, dark, and Midnight, with the pseudo-locale and 200% text.

## Documentation that follows the build

`docs/self-hosting.md` (its Plans steps), `docs/troubleshooting.md` (removing the default Plan), and
`CHANGELOG.md` describe the Plans UI step by step; they change with the screens they describe.
`docs/data-ownership.md` already lists what a person's Plan card shows an administrator.
