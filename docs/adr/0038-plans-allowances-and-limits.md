# Plans: Allowances and limits

Builds on [ADR 0028](0028-plans-apart-from-commercial-mode.md),
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md), and
[ADR 0032](0032-bounded-contexts-as-application-packages.md). Amends
[ADR 0010](0010-rule-removal-and-calendar-replacement.md),
[ADR 0021](0021-community-edition-agpl.md),
[ADR 0023](0023-hosted-service-runs-the-open-codebase.md),
[ADR 0028](0028-plans-apart-from-commercial-mode.md),
[ADR 0030](0030-users-administrators-and-registration.md), and
[ADR 0036](0036-instant-sync-through-provider-notices.md).

## Context

ADR 0028 settled that an Installation Administrator may turn Plans on to limit how much each User
uses, and that billing will later set a User's Plan through the same model. It left open what a
Plan holds, whom it limits, what each limit counts, and how a limit holds when two requests race.

The Hosted Service needs a free Plan and larger ones, with Instant Sync perhaps only on some. A
household administrator needs to keep one User from using up a shared computer and the provider
quota every User draws from. A self-hosted installation must keep every feature, and with Plans
off nothing may change. The [Plans design](../superpowers/specs/2026-10-15-plans-design.md) holds
the whole design and its delivery in four slices, and the
[catalog design](../superpowers/specs/2026-10-17-plans-ui-catalog-design.md) its Web UI. This
record covers the first slice: Plans, their limits, and Instant Sync or a five-minute sync per
Plan. Later slices add their own sections here.

## Decision

- **Plans live in Identity and Access, and Synchronization enforces them through a port it
  declares.** `domain/plans.py` holds the Plan values and the one decision, `allowance_for`.
  Identity owns the administrator's use cases (`ShowPlans`, `DefinePlan`, `ChangePlan`,
  `RemovePlan`, and `SetPlansSetting`, in `application/identity/plans.py`) over the
  `PlanCatalog` and `PlanAssignments` ports. Synchronization declares `Allowances` (`of(user)` and
  `of_users(users)`) in `application/sync/ports.py`, as it already declares `SyncCadencePolicy`,
  so it enforces limits without importing Identity. One `SqlitePlans`
  (`infrastructure/persistence/plans.py`) implements all three ports, and each client depends only
  on the one it uses. The lint-imports layers and the contexts of ADR 0032 do not change, and no
  new table holds a User's records.
- **A Plan** has a key, a name, three counts, and a sync interval. The key is 1 to 32 lower-case
  letters, digits, and hyphens, starting with a letter or digit, and never changes, so billing can
  map prices to it; renaming a Plan changes only its name. `DefinePlan` takes a `NewPlan`, whose
  key may be missing, and `POST /api/v1/plans` an optional `key`, kept as it is and refused with
  409 `plan_key_taken` when another Plan has it. Without one, `PlanCatalog.add` makes it from the
  name with `plan_key_from` in `domain/plans.py`: lower case, accents dropped, one hyphen for each
  run of other characters, at most 32 characters, or `plan` when nothing is left; when another
  Plan has it, `-2`, `-3`, and so on. `SqlitePlans.add` reads the stored keys after
  `BEGIN IMMEDIATE`, so two Plans added at once with one name get different keys. No Plan has the
  key `new`, which the New plan panel's address names (`/people/plans/new`, beside each Plan's
  `/people/plans/<key>`): a key made from a name treats `new` as taken (a Plan named New gets
  `new-2`), and `POST /api/v1/plans` refuses a request that names it with 422 `invalid_plan`. The
  name is 1 to 60 printable characters and can change. Rules and Connected Accounts allow 1 to
  10000, and Integration Tokens 0 to 10000, so a Plan may offer none; each count may instead be
  unlimited. A count out of range answers 422 `invalid_plan` with `reason` `limit` and `max`, the
  largest count, so the Web UI writes it in the reader's number format.
- **Plan names are unique.** Two Plans may not read as one name: names compare after Unicode
  compatibility folding, without case, and without spaces around them (`require_unique_name`).
  `PlanCatalog.add` and `change` check it under the same write lock as the key, so two Plans added
  at once cannot both take a name, and a Plan may keep its own name in another case. A refused
  name answers 409 `plan_name_taken` with the other Plan's `name`.
- **The Default Plan.** The administrator marks one Plan as the default. A User whose own Plan is
  NULL (`users.plan_key`) has it, so changing the default changes every such User at once, with no
  write per User, including Users invited later. When Plans turn on and neither the request nor the
  installation names a default, `change_settings` adds an ordinary Plan named "No limits", with
  every count unlimited and Instant and its key made from its name, and makes it the default in the
  same transaction; when a Plan already reads as "No limits", the Plan made is named apart,
  "No limits 2", so turning Plans on is never refused for a name. Turning Plans on then changes
  nothing until the administrator adds a smaller Plan and gives it to someone, which is how a
  household limits one person. The Plan can be renamed and changed. `plans_need_default` answers
  only a request that would clear the default with Plans on, or as they turn on, so Plans are never
  on without a default, and a default an administrator chose is never replaced. The default cannot
  be removed (`plan_is_default`), and no Plan can be removed while anyone has it (`plan_in_use`):
  the administrator moves those Users first, which is also safe for billing. Turning Plans off is
  always allowed and keeps every definition and assignment.
- **The Allowance decides everything a Plan limits.** `allowance_for` reads, in order: with Plans
  off, no limits (basis `plans_off`); for a User who administers, no limits (`administrator`);
  otherwise their own Plan, or the Default Plan when they have none (`plan`). Plans on with no Plan
  found cannot happen, because Plans cannot be on without a default, but it would read as
  `plans_off`, so a fault in Plans never limits anyone. Every Allowance also carries the User's own
  stored Plan, so an administrator sees a Plan that does not apply yet. The Allowance is read when
  it is needed, with no cache.
- **Installation Administrators are never limited.** Under Only Me the only User administers, so
  Plans have no effect there, and the Web UI hides them. Removing the role subjects a User to their
  Plan from their next request, and granting it lifts every limit at once.
- **What each limit counts, and where it is checked:**

  | Limit | What counts | Checked | Refusal |
  | --- | --- | --- | --- |
  | Rules | Enabled rules, rules stopped only by Lapsed Authorization, and a Rule Replacement's new draft that keeps its previous rule's place | At Start (`EnableSyncRule`). Creating and previewing a rule, and a rule resuming after Lapsed Authorization, are never checked. | 409 `plan_limit_reached`, reason `rules` |
  | Connected Accounts | Every account of the User, Disconnected Accounts included | When the OAuth callback saves a new provider and address | The OAuth outcome `account_limit_reached`, with `limit` |
  | Integration Tokens | Unrevoked tokens | `IssueIntegrationToken` | 409 `plan_limit_reached`, reason `integration_tokens` |
  | Sync interval | Not a count | Instant Sync, through `PlanCadence` | None |

  Disconnected Accounts count because reconnecting one is Reauthorization, which is never refused;
  otherwise a User could disconnect one account, connect another, and reauthorize the first.
  `installation:read` tokens are for administrators only, who are never limited, so health
  monitoring is never blocked. The rule page answers `can_start` and `rule_limit`, so the Web UI
  disables Start with the message a refused Start shows and computes nothing itself. Rules and
  rule details also answer `keeps_place`, so a list that has no `can_start` can tell from Your
  plan that a previewed rule would be refused, and say so with the same message; while Your plan
  cannot be read, it says nothing, and Start still checks.
- **Only Rule Replacement keeps a place.** A rule's place under the rule limit is its counting
  toward it. Drafts, previewed rules, and paused rules do not count. A rule stopped by a provider
  error, or paused by a Material Rule Change, gives up its place, and its restart is checked like
  any Start. A Rule Replacement's new draft keeps its previous rule's place
  (`SyncRule.keeps_place`) when that rule counted, and takes its creation order, so it ranks where
  the previous rule ranked and its Start always succeeds. A replacement of a rule that did not
  count keeps no place and is the newest rule. The place moves atomically: `RemoveSyncRule` inserts
  the draft, with the checks every new rule passes, in the same transaction that begins the
  previous rule's removal, after it waits for that rule's run
  ([ADR 0010](0010-rule-removal-and-calendar-replacement.md), amended). No moment counts both
  rules, no client sees the draft before its place moves, and no cleanup path deletes it. The draft
  keeps the place through previews and Material Rule Changes until it starts or is removed;
  disconnecting one of its accounts gives the place up.
- **Every limit check reads the Allowance inside the transaction it guards, after that transaction
  holds SQLite's writer lock.** `SqlitePlans` writes under `BEGIN IMMEDIATE`, and the database runs
  in WAL mode, so the read sees every committed Plan change and no Plan change commits until the
  check's transaction ends. A Start saves the enabled rule, then reads the Allowance, counts, and
  rolls back with `plan_limit_reached` when the count after the Start passes the limit: two Starts
  cannot both take the last place, and a lowering cannot slip in between. A new account is counted
  inside the existing `BEGIN IMMEDIATE` of the account store's save, and only when no row has the
  same provider and address, so Reauthorization never reads Plans. A token is counted under
  `BEGIN IMMEDIATE` right before its insert.
- **Limit checks fail closed; every other read of Plans fails open.** A check that cannot read the
  Allowance fails its request, as any database error does, so a fault never admits a resource past
  a limit; at the OAuth callback that is a server error after the provider's consent, with nothing
  saved. Every other reader falls back to no limits: Instant Sync dispatch, watch upkeep, and
  Installation Hints treat the User as instant, so no Instant Sync Request is dropped and no watch
  retired; `InstantSyncStatus` answers the default cadence; the rule page answers `can_start` true,
  and the Start still checks; the Operator Overview leaves the Plan out. A fault in Plans never
  stops synchronization, sign-in, or the rules API. Your plan (`ShowOwnPlan`) fails its own request
  instead of showing a basis it could not read; the Web UI then shows no limit hints, and the
  server still checks.
- **Lowering a limit stops nothing.** Rules beyond a lower rule limit keep syncing, but no rule can
  start until fewer count. Existing Connected Accounts keep their Reauthorization, and existing
  Integration Tokens keep working, because a token that stops on its own breaks a monitor
  ([ADR 0024](0024-integration-tokens-installation-status-and-mcp.md)). Only new ones are refused.
  Plan Hold, which holds rules beyond a lower limit after a grace period, arrives in a later slice
  with its own record.
- **A changed account address at the limit.** When a provider reports another address for an
  account, such as a renamed Microsoft or Google Workspace account, the new address is a new
  Connected Account. At the limit, the documented recovery keeps every rule: get one free account
  place, connect the new address, use Replace calendars on each rule, then disconnect and delete
  the old account. Deleting the old account first would delete its rules. When every place holds
  an account with rules, the free place comes from an administrator, who raises the limit or
  assigns a larger Plan for the recovery.
- **Sync intervals are a fixed server list:** `instant`, `5_minutes`, `10_minutes`, `15_minutes`,
  `30_minutes`, and `60_minutes`. `instant` means Instant Sync plus a five-minute Scheduled Sync.
  This slice offers `instant` and `5_minutes`. It reads every value, so a database a later release
  wrote still works, and it polls every value other than `instant` every five minutes without
  Instant Sync, because its scheduler runs every rule at every pass. A value it does not know reads
  as `instant`, with a warning. `PlanCadence` (`application/sync/watch_ports.py`) turns each User's
  Allowance into their Sync Cadence and replaces `EveryUserInstant` as the installation's
  `SyncCadencePolicy` ([ADR 0036](0036-instant-sync-through-provider-notices.md), amended). The
  User keeps only their own choice to turn Instant Sync off.
- **One assignment port.** `PlanAssignments` is the only way a User's own Plan changes, through
  `assign_all(plans, change)`, which gives one User or several each the Plan `plans` names for
  them, all or none, and `None` returns them to the Default Plan. A Plan that is the Default
  Plan, read in the same write transaction, is stored as `None`, recording the same change, and a
  dry run answers the same, so giving the default means following it for every client:
  `POST /api/v1/plan-assignments`, from the Web UI and the API, and billing later; the MCP server
  gives no Plans. `change` is `AssignmentChange(source, actor, at)`, whose source is
  `administrator` or `billing`; the User's row keeps the current one in `plan_assigned_by`,
  `plan_assigner_id`, and `plan_assigned_at`. An administrator may assign while Plans are off, to
  prepare. Billing (Commercial Mode, a later phase) will call the same port and decide from
  `plan_assigned_by` whether it may overwrite an administrator's choice. Each change writes one log
  line with identifiers only; a history waits for the deferred record of administrator actions.
  Make default changes no User's own Plan: people whose own Plan becomes the default keep it, and
  Make default names them. So Undo, which gives back each person's own Plan, makes someone whose
  own Plan is the default by then follow it.
- **Plans for many people at once.** `POST /api/v1/plan-assignments` (administrator) takes
  `plans`, each User's identifier with the key of the Plan to give them, or `null` for the
  default, and gives each of up to 100 Users theirs in one write, all or none, through
  `PlanAssignments`, with one `AssignmentChange(administrator, actor, now)` and one log line per
  User. So Undo gives each person back the Plan they had in one request: when another
  administrator has removed one of those Plans or deleted one of the people meanwhile, it is
  refused and nobody moves. It answers each User with the Plan they had and have, and the limits
  of it they are over. Those come from the Operator Overview, through `plan_use` as `over` does,
  so assigning reads no other User's records outside it
  ([ADR 0029](0029-isolate-users-in-one-sqlite-database.md)). With `dry_run` it writes nothing and
  answers the same, so Assign people and Change plan say who would be over before anyone confirms.
  It refuses a Plan that does not exist with 404 `plan_not_found`, and no Users, more than 100, or
  an identifier that names no User with 422 `invalid_assignment`, whose `reason` is `no_people`,
  `too_many` (with `limit`), or `unknown_people`; the Users are in the body, not the path, and only
  an administrator reaches the route, so 422 reveals nothing. A JSON object names each User once.
  The use case, `AssignPlans`, lives in Operations beside the Operator Overview it reads
  (`application/operations/plan_assignment.py`), and the store checks that every Plan and every
  User exists under the same write lock as the update. Unlike People, it fails when Plans cannot
  be read, so it never says nobody would be over when it could not count. One User is given a Plan
  the same way, as the only one named.
- **The Operator Overview computes who is over a limit,** so the administrator, who can fix it, is
  not the last to know. Counting another User's rules, accounts, and tokens reads across Users, so
  it lives in the Operator Overview read model (`application/operations/operator_overview.py`),
  the reader ADR 0029 allows, and never in Identity. `InstallationUnitOfWork.plan_use(users)`
  counts, for each User, what each limit counts: rules for which `SyncRule.counts_toward_plan`
  holds, every Connected Account, Disconnected Accounts included, and unrevoked Integration
  Tokens, in one query per limit for up to 500 Users. `PlanUse.over(limits)` in `domain/plans.py`
  names each limit a User has more of than it allows, with how many are in use and how many are
  allowed.
- **A person's Plan on their page and their row of People.** `UserOverview.plan` is a
  `PersonPlan`: the Allowance, the Plan they have (their own, or else the Default Plan, whether or
  not Plans are on), and each limit of it they are over. Only an active User who does not
  administer (`User.limited_by_plans`) is ever over, the people `limited_people` counts. The facts
  are computed while Plans are off too, so an administrator sees whom a Plan would leave over it
  before turning Plans on. The person's overview and each row of People answer them as `has` and
  `over` beside `basis`, `plan`, and `assigned`. The person's Plan also has `assigned_by`, the
  email of the administrator who last gave it, `assigned_at`, and `use`: how many Active Rules,
  Connected Accounts, and unrevoked Integration Tokens they have, counted by `plan_use`
  ([ADR 0030](0030-users-administrators-and-registration.md), amended, for the token count). Each
  count comes beside the limit of the Plan they have, with its sync interval, for anyone with a
  Plan, administrators included. `assigned_by` and `assigned_at` come from
  `PlanAssignments.last_changes` only while the Plan is their own, and `assigned_by` is null once
  that administrator is deleted. Like the rest of the Plan fact, a fault reading them leaves the
  Plan out and never fails People.
- **Each Plan's reach.** `OperatorOverview.reach_of(actor, plans)` finds each Plan's people as
  People does, keeps those it limits, and answers a `PlanReach`: how many of them are over any of
  its limits (`over_people`), and, per limit, how many people have each count above 0
  (`use`), so the editor can say exactly how many people a lower limit would leave over it. Only
  counts reach the response, never who. `GET /api/v1/plans`, `PUT /api/v1/plan-settings`, and
  the define and change routes answer both for every Plan they list. Like every Plans route,
  they fail when it cannot be read. The Plans overview also counts `followers`, every User with no
  Plan of their own, whatever their role or state, for the count Make default says it moves
  ("People without a plan of their own (2 now) move to Free."). The default's `people` cannot say
  it, since it also counts those whose own Plan became the default.
- **People finds people by Plan.** `UserQuery.plan` and `GET /api/v1/users?plan=` list everyone
  who has the Plan, as `people` counts them: their own Plan, or, for the Default Plan, none of
  their own, whatever their role or state. A malformed key is an invalid request; a key no Plan has
  finds nobody. `GET /api/v1/users?over=true` lists the Users over a limit of the Plan they have,
  as `over` says, alone or with `?plan=`, for the "1 over a limit" chip and Everyone's Limits
  filter. Like the rest of People it fails open: while Plans cannot be read, it finds nobody. The
  Web UI reads Plans on the Plans tab, and on Everyone only once its people show that a Plan
  exists, for the names of its Plan filter (`/people?plan=family`), so an installation that never
  defined one reads them only on the Plans tab. Remove on a Plan someone has names the first three
  of them from the same list (`?plan=` with `page_size=3`, by email) and links to Everyone
  filtered by that Plan.
- **Returning to setup turns Plans off,** keeping their definitions and the default, so a new
  first User never inherits limits nobody can see. Invitations carry no Plan: an invited User
  starts on the Default Plan.
- **Migration 33** adds the `plans` table, `plans_enabled` and `default_plan_key` on
  `installation_settings`, `plan_key`, `plan_assigned_by`, `plan_assigner_id`, and
  `plan_assigned_at` on `users`, and `keeps_place` on `sync_rules`. Nothing is backfilled: Plans
  start off and limit nobody. The foreign keys keep NO ACTION, so the database refuses to delete a
  Plan that a User or the default names. Rolling back works with the same database: earlier
  releases ignore the table and the columns and limit nobody, and after upgrading again, Plans are
  as the administrator left them.

## Consequences

Plans and their enforcement are the same code on every installation, so self-hosters can read how
the Hosted Service limits its free Plan, and a household administrator can use the same limits.
With Plans off nothing changes, and every existing test keeps its expected behavior.

The Web API gains the administrator's Plans routes (`GET` and `POST /api/v1/plans`, `PUT` and
`DELETE /api/v1/plans/{plan_key}`, `PUT /api/v1/plan-settings`, and
`POST /api/v1/plan-assignments`), the `plan` and `over` filters of `GET /api/v1/users`, and
`GET /api/v1/account/plan` for Your plan. Rule details gain
`can_start` and `rule_limit`, rules and rule details gain `keeps_place`, and the person's overview
and each row of People gain `plan`. The new problem codes are `plan_limit_reached`,
`plans_need_default`, `plan_not_found`, `plan_key_taken`, `plan_name_taken`, `plan_in_use`,
`plan_is_default`, `invalid_plan`, and `invalid_assignment`. A malformed Plan key in a path, the
default, or an assignment names no Plan, so it answers 404 `plan_not_found`; a malformed new key
answers 422 `invalid_plan`. `GET /api/v1/status`, Installation Health, and MCP do not change.

A Connected Account can be refused only after the provider's consent, because only then is its
address known, and the refusal leaves an unused grant at the provider; the Web UI disables Connect
at the limit, which makes this rare. Counting people per Plan scans `users`, which is fine at
household and early Hosted Service scale; an index can come in a later migration. Phase 4 of the
multi-user design rebuilds `installation_settings` and must carry `plans_enabled` and
`default_plan_key`.

## Alternatives considered

- **Plans as their own bounded context.** Rejected for now: it changes the lint-imports layers
  (ADR 0032), loosens the isolation test (ADR 0029), and adds ports for the same behavior. It
  remains open if billing grows large.
- **A key the administrator types when defining a Plan.** Rejected: it asked for a billing
  identifier before billing exists, as an irreversible first choice.
- **A default chosen before Plans can turn on.** Rejected: an administrator who wanted to limit one
  person first had to define an unlimited Plan for everyone else by hand.
- **Places kept by stopped and paused rules.** Rejected: a paused rule would hold a place its User
  cannot use, and a stopped rule could hold one its User cannot give back. Only Rule Replacement
  keeps a place, because its new draft takes over a rule that was already counted.
- **Creating the replacement draft first, then moving its place.** Rejected: the draft would count
  beside its previous rule, or could be started before its place moved, and a removal that failed
  afterwards deleted it even after a client had started it.
- **Checking a limit before the write.** Rejected: two requests could both pass the check. Writing
  first, then counting under the writer lock, serializes them.
- **Failing open on a limit check.** Rejected: a fault would admit a resource past the limit for
  good, while a refused request can simply be tried again.
- **Disconnected Accounts outside the count.** Rejected: a User could disconnect one account,
  connect another, and then reauthorize the first, which is never refused.
- **Counting who is over in Identity.** Rejected: it would read other Users' records outside the
  Operator Overview (ADR 0029).
- **Computing who is over only while Plans are on.** Rejected: it would hide from an administrator
  what turning them on would do.
- **A list of each limited person's counts per Plan.** Rejected: it grows with the people a Plan
  limits, where the counts per value stay small.
- **A route that gives one User a Plan, called once for each person.** Rejected: a failure
  halfway leaves some moved, and nothing says beforehand who would be over.
- **Make default turning people whose own Plan becomes the default into followers.** Rejected: it
  changes an administrator's choice without asking.
