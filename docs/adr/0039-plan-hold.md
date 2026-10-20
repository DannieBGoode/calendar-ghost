# Hold excess rules after a Plan grace, with explicit production activation

## Context

Plans already refuse new Starts beyond the rule limit (ADR 0038). A lowered limit currently stops
nothing. Enforcing an existing excess needs time for the User to choose, safe automatic release,
and no loss of mappings or projections. A stop must remain distinguishable from Lapsed
Authorization and from a failure that requires a recovery preview.

## Decision

- **The engine ships before activation.** PR 2 includes domain decisions, persistence, User-scoped
  settlement and keep choice, scheduler support, private emails, and the preference rename.
  Production composition explicitly passes `plan_holds=None`. It cannot start a grace, hold a
  rule, or send a Plan notice. PR 3 must activate it in the same change as visible grace and hold
  state, status, Dashboard, MCP, the keep form, and correct recovery actions. The following
  settlement behavior describes the engine when explicitly composed.
- **Use Degraded with stop code 2.** `sync_rules.awaiting_reauthorization` stores 0 for no
  self-resuming cause, 1 for Lapsed Authorization, and 2 for Plan Hold. The domain keeps exclusive
  booleans and exposes `stop_cause`; no new rule state is needed. Held rules do not synchronize,
  count toward their Plan, receive Instant Sync dispatch, or want watches. Watch upkeep can still
  retire their existing watches. They retain mappings, projections, and incremental positions.
- **One seven-day grace per User.** Enabled rules, lapse-stopped rules, and replacement drafts
  keeping a place count. Excess starts a grace; a further lowering or a greater admission counter
  restarts it. Start and keep-choice releases into free places record admissions transactionally,
  so a limit raise and lowering between passes cannot hide a newly admitted rule. At expiry,
  worst-ranked counted rules are held and reserved drafts give up their places. Drafts giving up
  a place are not held rules. A Disabled User clears grace and retains holds. Plans off,
  administrator status, or an unlimited Allowance releases all holds on a successful settlement.
- **Keep first, then oldest.** Rank is keep mark, creation order, then identifier. A replacement
  that keeps a place inherits order and keep mark; replacing a rule that does not count inherits
  neither. The pass releases the best ranks into free places and never swaps. `ChooseKeptRules`
  validates the complete chosen set against fresh eligible standings, rejects unknown, foreign,
  or ineligible identifiers as `RuleNotFound`, and rejects more than a finite limit as
  `TooManyKeptRules`. It saves all marks or none, releases kept held rules into free places, and
  can swap a kept held rule with the worst not-kept counted rule without changing the count.
  These User-requested holds send no email. The HTTP route and form await PR 3.
- **Preview preserves a hold.** Release needs no preview. It reads both account authorizations
  inside the transaction and returns Enabled only when both are authorized, otherwise
  lapse-stopped. Reauthorization resumes only code 1. Pause, disconnection, Material Rule Change,
  removal, required recovery preview, or a failure needing intervention clears a hold. A run in
  flight stops at its next write check; an intervention failure it reports still wins over any
  self-resume. Pausing a hold then previewing permits a normal, limit-checked Start.
- **Lock before reading fresh state.** Settlement and keep choice serialize per User through one
  process-shared `SettleLocks`. After discovering eligible rules, they try rule write locks
  nonblocking in identifier order. Contention releases all acquired rule locks and raises
  `PlanSettlementBusy`; no settle waits for provider work. They then open a fresh User unit of
  work and call `PlanGraceRecord.acquire()`, a no-op UPDATE on its own User row, as the first
  statement. This takes SQLite's writer lock before fresh Allowance, grace, standings, and account
  reads. The transaction writes all decisions atomically and calls no provider. SQLite keeps its
  existing five-second writer timeout; DEFERRED transactions elsewhere remain unchanged.
- **Count fresh rules, change only locked rules.** A newly started rule or replacement outside
  the discovered set counts but remains unchanged until a later pass. Expired grace is retained
  until the remaining excess is settled. A keep choice that would change a fresh unlocked
  eligible rule's mark raises `PlanSettlementBusy` and saves nothing, preserving its whole-set
  meaning. Independent mark persistence prevents a late rule save from overwriting a keep choice.
- **Bound and rotate work.** The optional step follows interrupted-lapse recovery and precedes
  rule listing. Installation standings are light reads; Allowances are read in chunks of 500.
  Pure settlement filters unchanged Users by actions and exact grace equality. At most 100
  changed Users are attempted per pass, rotating after the last attempted identifier, including
  failures and busy skips. One failure cannot starve others. A failed bulk Allowance read settles
  nobody; a failed fresh read rolls back that User. Assuming unlimited on these errors would
  release holds and is unsafe. Ordinary cadence reads retain their fail-open policy.
- **Private, best-effort notices.** A grace start and actual scheduled holds can email only that
  User, gated by active state, email address, `notify_by_email`, and SMTP. The setting is called
  **Email notifications**; its PR 2 explanatory text remains incident-only until PR 3 supplies the
  visible Plan notice fallback. Plan notices contain counts, limit, and a UTC deadline and may
  link to `/settings/account#your-plan` at a valid configured public address. They name no rule,
  calendar, account, or event, create no Incident or Audit Entry, and reach no installation channel.
  Grace counts include reserved drafts but predicted holds count only counted rules. Actual held
  notices count actual holds only; give-ups alone send none. Release sends no email.
- **Mail is independent of passes.** Each `begin(notices=local_collector)` collects locally and
  hands notices to mail only after successful rule listing. One worker belongs to the Scheduler
  object's lifetime. A sending batch has at most 100 notices, with one latest pending notice per
  User; newer pending notices replace stale ones, and a second batch is not drained while sending.
  Unlike access checks, mail shares no rule slots and is never awaited for pass completion.
  Shutdown cancels and awaits the sender without awaiting an already-running bounded SMTP call
  or blocking the event loop on executor shutdown. Failed or cancelled preparation, cancellation,
  shutdown, restart, or SMTP failure may lose notices. There is no outbox or delivery retry.

## Upgrade and rollback

Migration 34 adds `sync_rules.plan_kept` and the User's nullable grace deadline, grace limit,
grace admissions, and default-zero admission counter. Nothing is backfilled into a hold. Only the
User unit of work writes these columns. Production PR 2 stays inert; normally only an activated
PR 3 or later can produce code 2.

Code from before migration 34 ignores the added columns but interprets 2 as Lapsed Authorization.
Start still counts it; older raw `plan_use` display counts may omit it because their SQL uses
exact code 1. Every old save erases 2 with 0 or 1. Unfinished-lapse discovery also selects exact
code 1, so a User with only code-2 rules can remain stopped instead of automatically recovering.
An account restoration or passing access check can recover those rules, or the User can preview
and Start within the limit. Re-upgrading may automatically resume a rule old code saved as 1
without a fresh limit check, and an activated engine then gives a new grace if over the limit.

This inert PR 2 build is different: it recognizes 2 as Plan Hold, and Reauthorization leaves it
held, but production passes cannot release it. When opening a future activated database here,
upgrade to an active release, or pause to clear the hold, then preview and Start within the limit.
Preview alone preserves a hold. The deployment guide and SQL header record both rollback cases.

## Accepted limits and risks

The Plans spec section 13 remains the source of the full tradeoffs:

- A further lowering restarts the whole grace; a raise within the limit clears it, so grace can
  exceed seven days across limit changes. A User's ordinary actions cannot create excess.
- A failed or edited rule may lose its place to a released hold, so its recovery Start can be
  refused. PR 3 must explain that before privacy edits, Pause, or Disconnect.
- A kept rule can stay held after a competing Start; saving the choice again swaps it.
- `awaiting_reauthorization` retains its historical name while rollback is supported.
- Monitors reading only `state` will need the PR 3 status contract: a held rule is `degraded`
  without a Stopped problem. Held rules must count as requiring a scheduler (ADR 0024).
- Account-limit refusal follows OAuth consent and may leave an unused provider grant; renamed
  accounts at the limit can need administrator help.
- Mail is lossy and coalesced. PR 3's Your plan and held-rule views are the durable fallback.
- Mass changes settle at most 100 Users per pass; watch retirement shares the 200-call upkeep
  budget. Pending mail retains at most one notice per affected User, not a fixed global cap.
- There is no global draft cap or simultaneous manual-run cap. Manual-run and scheduler window
  memory resets on restart only give runs back.
- Phase 4 must carry Plans columns through its `installation_settings` rebuild.
- One process per SQLite database remains required. Rule lock contention skips settlement, but
  SQLite writer contention can still consume its five-second timeout.

## Alternatives considered

A new Held state breaks old state readers. A held flag on Enabled risks a missed reader running
it. A separate hold column survives old saves and could revive a stale hold after intervention.
A new table, outbox, global writer, or transaction framework is unnecessary for the accepted
single-process and best-effort delivery guarantees.
