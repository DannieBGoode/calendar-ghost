# Instant Sync: design

Terms are in `CONTEXT.md`; this design adds Instant Sync, Calendar Watch, Watch Registration, Watch
Notice, Instant Sync Request, and Delivery Evidence. ADR 0036 records the decision, and it amends
ADR 0029 for the one new reader that crosses Users. Two rounds of independent review (Codex) shaped
the lifecycle, race, and provider rules below.

## Goal

A rule runs soon after its provider reports a change that may concern its Source Calendar. It does
not wait for the next Scheduled Sync. Scheduled Sync every five minutes and the daily full pass do
not change, and they remain the safety net for every missed or refused notice.

The target is that a run starts within 30 seconds after a notice arrives, when the installation has
free capacity. Delivery time is the provider's: Google usually delivers in seconds, and Microsoft
does not publish event-notice latency. The docs make no promise from the moment of the edit.

The Hosted Service may reserve Instant Sync for paying Plans. Plans (multi-user design, phase 3)
come right after this work and plug into one port; nothing in this design waits for them.

## Settled decisions

1. **No new setting for the installation.** Instant Sync is possible when
   `CALENDAR_SYNC_PUBLIC_URL` is an `https` address at the root of its host (the rule of
   `public_address()`, restricted to `https`). Providers deliver only to `https` with a valid
   certificate.
2. **Per User.** It is on for every enabled rule of a User whose Sync Cadence allows it, unless the
   User turns it off in account settings (`instant_sync`, default on, beside `notify_by_email`).
3. **Plans decide who may use it.** A `SyncCadencePolicy` port returns each User's `SyncCadence`
   (`instant`, `poll_every`). Until Plans exist, it returns `instant=True`, `poll_every=5 min` for
   everyone, which is what "Plans off" means in ADR 0028. Phase 3 implements the port from the
   Plan's "shortest sync interval" limit, whose shortest value is "instant". There is no interim
   administrator toggle.
4. **The switch explains itself.** When the installation cannot offer Instant Sync, or the User's
   Plan does not include it, or providers are known not to reach the installation, the switch is
   disabled with the reason and a "Learn why" link to the section of `docs/instant-sync.md` that
   explains the fix.
5. **Durable request, in-process dispatcher.** The webhook records a durable, per-rule Instant Sync
   Request and wakes a dispatcher, which runs the rule through the scheduler's own path.
6. **Only source rules are dispatched.** Watches exist only for Source Calendars. Destination
   drift is still repaired by the poll. An Outlook watch covers the whole mailbox (see Watch
   Scope), so it also hears destination writes and other calendars; that wakes source rules more
   often, but never dispatches anything else.

## Provider facts this design rests on

- **Google** (`events.watch`, `channels.stop`): one channel watches one calendar. We choose the
  channel id and a secret token. Google sends a `sync` message when the channel starts, possibly
  before `events.watch` returns, then `exists` or `not_exists` on changes. Channels cannot be
  renewed, only replaced; stopping one needs its id and `resourceId`. Google drops a small share of
  notices in normal operation. The `calendar.events` scope we already request allows watching.
- **Microsoft Graph** (`/subscriptions`): event subscriptions are documented only for a whole
  mailbox (`/me/events`). Delegated permissions cannot watch a calendar shared from another
  mailbox. A subscription lasts at most 10,080 minutes and is renewed in place with `PATCH`. A
  second subscription with the same resource and change types answers `409 Conflict`. Graph
  validates the notification URL before it answers `201`, so a created subscription proves that
  Graph reached the installation. Graph needs an answer within 3 seconds and retries on `5xx`.
  `GET /subscriptions` lists the app's subscriptions for the signed-in identity and withholds
  `clientState`. Lifecycle notices: `reauthorizationRequired`, `subscriptionRemoved`, `missed`. At
  most 1,000 Outlook subscriptions exist per mailbox across all applications.

## Domain model

`domain/watches.py` and `domain/cadence.py` hold values and decisions only, without I/O.

- **`SyncCadence`**: `instant: bool` and `poll_every: timedelta`. This work reads `instant`. The
  rule page renders `poll_every` ("Syncs every 5 minutes"), so Plans need no copy change.
- **`WatchScope`**: what one watch covers, as a non-null key: `calendar:<id>` (Google) or
  `account` (Outlook). The provider adapter chooses it.
- **Calendar Watch**: one row per User, Connected Account, and scope key. It holds the calendars it
  covers (`watch_coverage`), which upkeep records after the adapter confirmed each one can be
  watched. Notices wake only rules whose Source Calendar is in its coverage.
- **Watch Registration**: one provider channel or subscription of a watch. It has:
  - our `id`
  - the provider handle (null until created)
  - a hash of its secret token
  - the address it points at
  - a state: `creating`, `live`, `retiring`, or `abandoned`
  - `requested_until`, and `expires_at` as the provider returned it
  - `confirmed_at`, `renew_at` (fixed with jitter once, when the receipt is recorded), and
    `renew_requested_at`

  The watch itself holds `retry_at` and `failures`.
- **Lifecycle transitions** are conditional SQL updates from a named state, so a late writer
  changes nothing:

  | Writer | Transition |
  | --- | --- |
  | Upkeep | insert `creating` · `creating → live` (receipt) · `live → retiring` (Google replacement recorded) · any → `abandoned` · delete |
  | Inbox | set `confirmed_at` on every authenticated notice (idempotent) · set `renew_requested_at` (idempotent) · `live → retiring` or `creating → abandoned` on `subscriptionRemoved` |

  A receipt for a row that is no longer `creating` updates nothing, so a removed registration is
  never brought back. Upkeep clears `renew_requested_at` only if it still holds the value upkeep
  read.
- **`InstantSyncAvailability`**, a pure decision in the style of ADR 0033. Its inputs:
  - whether the address is `https`
  - `cadence.instant`
  - the User's preference
  - the Delivery State of each provider the User's watched sources use: `unknown`, `working`, or
    `failing`

  Its outputs:
  - `on`
  - `off_by_user`
  - `not_in_plan`
  - `no_public_address`
  - `not_reaching`: at least one provider is used, and every provider used is `failing`. A User
    with no watchable sources is `on`.

  Every output except `on` and `off_by_user` names its docs anchor.
- **Effective cadence** of a rule:
  - It is `instant` when availability is `on` and the rule's source is covered by a watch with a
    `live`, confirmed, unexpired registration that points at the current public address.
  - Otherwise it is `scheduled`, with one reason: an availability reason, `not_watchable`, or
    `waiting_for_provider`.
  - `not_watchable` means upkeep found, within the last day, that the source's provider cannot
    watch it (the process-wide record of `AccountBackoff`). A source no watch covers for any other
    reason, such as a new or resumed rule upkeep has not reached yet, or an account whose scope
    lookup backs off, is `waiting_for_provider`.

## Application

### Ports and types in `sync` (`application/sync/watch_ports.py`)

The provider descriptor lives in `sync`, so everything it exposes is declared here.

- **`CalendarWatcher`**, per provider:
  - `scope(endpoint) -> WatchScope | None`. It may ask the provider, for example whether an
    Outlook calendar belongs to the signed-in mailbox. `None` means the calendar cannot be
    watched.
  - `register(scope, registration_id, token, address, until) -> Receipt` (handle and returned
    expiry). The address contains the registration id (see Interfaces).
  - `extend(registration, until) -> datetime | None`. Graph renews in place and returns the new
    expiry. Google returns `None`, meaning "replace it": the application then persists a new
    registration with a new id and token and calls `register` with them. The adapter never
    invents an identity during a network call.
  - `adopt(scope, registration_id) -> Receipt | None`. After a `409`, it finds the subscription
    whose notification URL holds exactly this registration id. It never matches by resource
    alone, and it never deletes an unidentified subscription.
  - `stop(registration)`
- **`NoticeReader`**: `read(NoticeRequest) -> NoticeBatch`. `NoticeRequest` is neutral (headers,
  query, body bytes), so no Starlette type crosses the descriptor. A `WatchNotice` carries the
  registration id from the path, the provider handle and token it presents, and a kind:
  `started`, `changed`, `missed`, `reauthorize`, or `removed`.
- **Failure classes** for watch calls, kept apart from ordinary sync failures: `unauthorized`,
  `unsupported`, `duplicate`, `unreachable` (the provider's validation reason, not a bare `400`),
  `rate_limited`, and `temporary`.

### Use case `UpkeepWatches` (sync context, one User's unit of work)

`execute(cadence_allows, wanted, address)` reconciles one User's watches. It is idempotent, and no
provider call happens inside a write transaction.

1. **Desired coverage.** For each enabled rule's Source Calendar, call `scope()` when instant is
   allowed, wanted, and an address exists. Otherwise nothing is desired.
2. **Create.** For each desired scope without a usable registration (none `live`, or the live one
   points at another address):
   1. Persist a `creating` row: a fresh id, the hash of a fresh 32-byte token, and
      `requested_until`. Commit.
   2. Call `register`, and record the receipt. A Graph `201` also sets `confirmed_at`.
   3. On `duplicate`, call `adopt` once. A subscription found with our id is recorded as `live`.
      If nothing matches, another registration (another User connected the same mailbox) holds
      it: the scope is left to polling with `retry_at` = 1 day.
3. **Recover.** A `creating` row older than 10 minutes, after a crash or a lost response, becomes
   `abandoned` and stays until `requested_until`. Its notices are then recognized and ignored, and
   Graph can adopt it.
4. **Renew** when `renew_at` passed or `renew_requested_at` is set, through `extend`, or through
   replacement for Google. A replacement makes the old registration `retiring`, and it is stopped
   after the new one is recorded. Notices on both count meanwhile.
5. **Retire what is no longer desired.** This covers a paused or removed rule, a User who turned
   it off, a lowered Plan, a disabled User, or an address that changed. Upkeep calls `stop` (best
   effort), then deletes the rows. If a stop fails, the row becomes `abandoned` until its expiry.
   Nothing waits on remote cleanup.
6. **Delete expired** `abandoned` and `retiring` rows.
7. **Failures.**
   - `unauthorized` goes to `LapsedAuthorizations.lapsed(account, failure, attempted_at=call
     start)` (ADR 0027), so a refusal of credentials since replaced lapses nothing.
   - Every other class sets the watch's `retry_at` with exponential backoff, capped at 1 day,
     honoring `Retry-After`. A provider that cannot watch a calendar never lapses the account.
   - `unreachable` also records failing Delivery Evidence.

User Deletion calls `stop` for that User's registrations after Rule Removal and before deleting
the User, and account disconnection calls it for the account's registrations after stopping its
rules and before discarding its credentials, which stopping needs. Both are best effort, with a
short deadline (10 seconds), then delete as today. Owned rows cascade. Notices for the deleted
registrations are unknown and acknowledged without effect.

### Operations context (`application/operations/instant_sync.py`)

- **`WatchUpkeep.run(budget)`** runs installation-wide, beside the scheduler. Each cycle it does
  this:
  1. Lists every User with enabled rules or existing watches, disabled Users included (their
     desired set is empty).
  2. Computes each User's `SyncCadence` and preference.
  3. Runs `UpkeepWatches` in order of the earliest due work (`renew_at`, `retry_at`, missing
     coverage), stopping when the cycle's provider-call budget is spent.

  The budget counts the provider calls each step actually made, as the per-thread Provider Call
  tally measures them, including listing, deleting, retrying, and pages. Upkeep asks a provider
  for the scope of a Source Calendar only when no watch covers it yet. It persists what it finds
  as it goes, so a cycle that runs out of budget keeps its progress. The next cycle starts with
  the Users this one never reached, then the one it stopped on, so no User starves. Calls are
  counted per User in Provider Calls, so they appear on the Operator Overview. A scope lookup the
  provider refuses backs off per account, honoring `Retry-After`.
- **`InstantDispatch`** chooses runs. `due(now)` returns `InstantRun(scheduled_run, captured_seq)`
  for each rule whose request has `requested_seq > handled_seq` and that meets all of these:
  - its owner is not disabled
  - the owner's cadence allows instant and the owner wants it
  - the rule is enabled
  - its last run did not fail (a failing rule is left to Scheduled Sync until a run succeeds)
  - it is not already reserved by the dispatcher
  - its last instant run was at least 30 seconds ago

  Requests of rules whose owner no longer wants Instant Sync, whose cadence no longer allows it,
  or whose last run failed, are acknowledged and dropped. The dispatcher checks this again once a
  queued run gets a slot. Requests of paused rules and disabled Users are never listed: they
  wait, and run or are dropped once the rule or User is active again. Delivery Evidence never
  blocks a run: an authenticated notice is itself proof that delivery works.
- **Acknowledgement** happens after `ScheduledPass.run` returns, whether the run succeeded or
  failed. One statement sets `handled_seq = max(handled_seq, captured_seq)` and `last_run_at`. A
  notice that arrives during the run raises `requested_seq`, so another run follows.

  This is a deliberate trade. A failed run consumes its request, and Scheduled Sync retries the
  rule with its own failure handling and backoff, as it does today. A crash before
  acknowledgement leaves the request pending, so the run happens again after restart.

### Notice intake: `WatchNoticeInbox` (operations context)

This is the one new reader that crosses Users, and ADR 0029 is amended to name it. It is its own
narrow port (`record(notices, provider, address_base, at) -> int`), not the installation-wide
unit of work, and it reads and writes only registrations, Instant Sync Requests, and Delivery
Evidence. The dispatcher, which is part of the scheduler, joins `INSTALLATION_UNIT_RECEIVERS`.

For each notice, it locates the registration by the id in the path, then checks two things in
constant time: the token hash, and the provider handle when the notice carries one. Unknown,
`abandoned`, and refused notices change nothing. Every other notice, of any kind, sets the
registration's `confirmed_at` if it is unset: it proves that the provider reaches the installation
through it, so a dropped Google `sync` notice, or a proxy fixed after a registration was created,
does not leave rules waiting for the provider while notices flow. Then each acts by kind:

| Kind | Effect |
| --- | --- |
| `started` (Google `sync`) | nothing more |
| `changed`, `missed` | one statement upserts a request for each enabled rule of the owner whose source is in the watch's coverage, raising `requested_seq` |
| `reauthorize` | set `renew_requested_at` |
| `removed` | `live → retiring`, or `creating → abandoned` so a late receipt cannot revive it, and raise requests (catch-up) |

Every authenticated notice refreshes the provider's success evidence for the current address, at
most once a minute. Intake makes one short write transaction per HTTP request, in a worker thread,
on a connection whose lock wait is 1 second (a new parameter of `connections.py`). It makes no
provider call.

### Delivery Evidence

Delivery Evidence is one installation row per provider and public address: `last_success_at` and
`last_failure_at`.

- **Success** comes from an authenticated notice or a Graph `201`.
- **Failure** comes from a Google registration not confirmed within 2 minutes, or a Graph
  `unreachable` refusal.

A provider is `failing` when its latest failure is newer than its latest success for the current
address, and `unknown` when it has no evidence for that address. Evidence informs the switch,
rule cadence reasons, and Installation Health. It never removes watches or blocks runs.

## Infrastructure

- **`infrastructure/google/watches.py`**:
  - Watching uses `events.watch` with `type=web_hook`, `id` = registration id, `token`, `address`,
    and `expiration`. Stopping uses `channels.stop`, and `extend` returns `None`.
  - Notices are read from `X-Goog-Channel-ID`, `X-Goog-Channel-Token`, and
    `X-Goog-Resource-State`.
  - `scope()` returns `calendar:<id>` for any calendar.
- **`infrastructure/microsoft/watches.py`**:
  - `POST /subscriptions` uses `resource=me/events`, `changeType=created,updated,deleted`,
    `clientState` = token, `notificationUrl` and `lifecycleNotificationUrl`, and an expiry of up
    to 10,080 minutes. Renewal uses `PATCH`, stopping uses `DELETE`, and adoption uses
    `GET /subscriptions` with exact URL matching.
  - `scope()` returns `account` only for calendars in the signed-in mailbox. It reads the
    calendar's owner once per cycle, and a shared calendar is `None`.
  - `validationToken` requests are answered by the route and are not evidence.
- **Descriptors** gain `watcher: CalendarWatcher | None` and `notice_reader: NoticeReader | None`.
  No code outside a provider's package branches on its Provider Kind.
- **Migration 0031** adds the owned tables `calendar_watches`, `watch_coverage`,
  `watch_registrations`, and `instant_sync_requests`, each with `user_id` and composite
  references that cascade with their account, rule, and User. It also adds
  `users.instant_sync INTEGER NOT NULL DEFAULT 1` and the installation table `delivery_evidence`.
  In-memory twins and contract tests cover them all.
  - **Upgrade:** nothing is rewritten. Watches appear at the first upkeep after start.
  - **Application rollback:** earlier releases ignore the tables. The route no longer exists, so
    providers receive `404` until their registrations expire (at most about 7 days), and polling
    runs as before.
  - **Upgrading again:** registrations still live in the table keep working. Expired ones are
    deleted and recreated by upkeep.
- **`infrastructure/scheduling.py`**:
  - **`InstantSyncDispatcher`** is an asyncio loop. It wakes on an event that the route sets from
    its worker thread (`loop.call_soon_threadsafe`), and on a timer set to the earliest moment a
    pending request becomes due: the end of its 10-second quiet window, capped at 30 seconds after
    the first pending notice, or the end of the rule's 30-second gap. It holds a process-local
    reservation for each rule it queued and checks the rule again after admission. Its own
    concurrency bound is 2, separate from the scheduler's 4. That way neither kind of run waits
    behind the other's queue, and the total stays bounded at 6.
  - A run that meets a rule held by a scheduled or manual run waits for the rule lock, which is
    correct, only slower.
  - The loop survives exceptions the way the scheduler's does. It is cancelled on shutdown, and
    its requests remain durable.
- **`WatchKeeper`** runs `WatchUpkeep` every 5 minutes, with its own concurrency of 2 and a
  per-cycle budget of 200 provider calls. Slow provider calls therefore never delay rule runs or
  the scheduler's heartbeat.
- **`app.py`** lifespan starts and cancels both loops beside the scheduler.

## Interfaces

- **Public `POST /api/v1/watch-notices/{provider_slug}/{registration_id}`:**
  - The body is streamed with a hard 64 KB cap, answering `413` above it. A Graph batch holds at
    most 100 items.
  - A Graph `validationToken` request is answered with `200` and the token echoed as `text/plain`
    (length-capped).
  - Otherwise the route answers `202` once the inbox committed, alike for known, unknown, and
    refused notices. It answers `503` when the commit cannot finish within the lock wait, so
    providers retry.
  - It never logs tokens, handles, registration ids, or bodies.
  - It is added to AGENTS.md's list of intentionally public routes and to
    `tests/adapters/test_api_authorization.py`.
- **`PUT /api/v1/account/instant-sync`**, beside `/account/notifications`.
  `SignedInUserResponse` gains `instant_sync` and `instant_sync_availability` (the decision and
  its docs anchor). Rule responses gain `effective_cadence` with its reason and `poll_every`. The
  OpenAPI file and web types are regenerated.
- **Web UI:**
  - In account settings, an "Instant sync" switch. When it is unavailable, it is disabled with the
    reason and "Learn why".
  - On the rule page, "Syncs instantly" or "Syncs every 5 minutes", with the reason.
  - All text is in the i18n catalogs.
- **Installation Health hints** for administrators:
  - an `http` public address while Users want Instant Sync
  - a provider whose Delivery Evidence is `failing`

## Documentation

- **New `docs/instant-sync.md`:**
  - what Instant Sync is and what it does not promise
  - requirements: a public `https` address with a valid certificate, and a reverse proxy that
    forwards `/api/v1/watch-notices/` with its body unchanged
  - how to turn it on, and how to check that it works
  - one anchored section per unavailable reason, with its fix
  - privacy: notices carry no event content and none is logged
  - cost per run per provider, measured during implementation
  - Outlook's whole-mailbox wakes
  - how Plans decide it
- **Updates:**
  - `docs/deployment.md`: reverse proxy, Cloudflare Tunnel, and the Raspberry Pi note
  - `docs/self-hosting.md`, `docs/sync-model.md`, `docs/troubleshooting.md`
  - `docs/architecture.md`: descriptors and loops
  - `CONTEXT.md`, README, and AGENTS.md (public routes, receivers)
  - CHANGELOG
  - ADR 0036, and the ADR 0029 amendment
  - the multi-user design's phase 3: implement `SyncCadencePolicy` from Plans

## Testing

The usual layers apply, with synthetic fixtures only. Each test below proves a failure that
review raised:

- A Google `sync` notice that arrives before `register` returns is recorded.
- A late receipt for an abandoned or deleted registration changes nothing.
- An inbox `reauthorize` that races upkeep's renewal is not lost.
- A crash between a run and its acknowledgement leads to a second run after restart.
- A partial fan-out failure acknowledges each rule on its own.
- During Google renewal overlap, both registrations are accepted.
- A Graph `409` adopts only an exact registration id. Another User's subscription is never touched
  or deleted.
- A shared Outlook calendar is `not_watchable`; a source upkeep has not reached yet is
  `waiting_for_provider`.
- Any authenticated notice confirms its registration, not only Google's `sync`.
- A disabled User's watches are stopped, and a deleted User's notices become unknown.
- A spoofed `validationToken` produces no evidence.
- Evidence recovers after the address changes. Evidence does not block runs.
- The dispatcher never runs one rule twice at once, and wakes at the earliest due time.
- The upkeep budget resumes in due order without starving any User.
- The route answers `503` when storage is locked, `413` above the cap, and the same `202` for
  known and unknown notices.
- The new tables pass the isolation schema and contract tests.
- `unauthorized` lapses the account through ADR 0027, and `unsupported` never does.

The plan also holds a manual checklist against real Google and Microsoft accounts, kept out of CI,
and a measurement of provider calls per instant run.

## Out of scope

- Watching Destination Calendars.
- Shorter or longer polling per Plan, which is phase 3.
- A relay for installations without a public address.
- Graph rich notifications (resource data).
- More than one application process (the shipped deployment is one process).
