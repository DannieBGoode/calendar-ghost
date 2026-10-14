# Instant Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a rule soon after its provider reports a change that may concern its Source Calendar, through Google push channels and Microsoft Graph subscriptions, while Scheduled Sync and the daily full pass stay as the safety net.

**Architecture:** Each User's Source Calendars get Calendar Watches (Google: one per calendar; Outlook: one per mailbox). Provider notices reach a public route, which writes durable per-rule Instant Sync Requests through a narrow inbox. An in-process dispatcher runs due requests through the scheduler's own `ScheduledPass.run`, and a separate keeper loop registers, renews, and retires watches within a call budget. A `SyncCadencePolicy` port says yes to everyone until Plans (multi-user phase 3) implement it.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), asyncio, google-api-python-client, httpx (Graph), React + TypeScript + Vite (web), Vitest, pytest, mypy, ruff, import-linter.

**Spec:** `docs/superpowers/specs/2026-10-14-instant-sync-design.md`. Read it before any task. Two rounds of Codex review shaped it; this plan was reviewed by Codex once more before hand-off.

## Global Constraints

- Follow `AGENTS.md` in full: dependency direction (`operations` → `identity` → `sync` → `shared`, domain imports nothing above it), provider neutrality (`tests/test_provider_neutrality.py`), no `noqa` for complexity, application dataclasses with behavior take at most 7 constructor fields (`tests/test_architecture.py`).
- No em dashes anywhere: code, comments, docs, commit messages, UI copy.
- Never log or return tokens, provider handles, registration ids, notice bodies, Graph error text, or event content.
- Every owned table carries `user_id` with composite references (`tests/adapters/test_user_isolation_schema.py`).
- No provider call inside a SQLite write transaction.
- Public notice route: `POST /api/v1/watch-notices/{provider_slug}/{registration_id}`; body cap 65,536 bytes; at most 100 Graph items.
- Timing constants: `QUIET = 10 s`, `MAX_WAIT = 30 s`, `MIN_GAP = 30 s`, upkeep every 300 s with a budget of 200 provider calls, dispatcher concurrency 2, `CREATION_DEADLINE = 10 min`, `CONFIRMATION_DEADLINE = 2 min`, `LONGEST_REGISTRATION = 7 days`, `MAX_BACKOFF = 1 day`, inbox lock wait 1 s, evidence refresh at most once a minute.
- Instant Sync runs only when `CALENDAR_SYNC_PUBLIC_URL` is an `https` address at the root of its host and the master key exists.
- Tests use synthetic fixtures and fakes only; no test needs a real Google or Microsoft account.
- After any change under `web/`, run the frontend build and commit the regenerated static assets. After any schema change, regenerate `web/openapi.json` and `web/src/lib/api-schema.ts`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

Inputs and conditions the spec implies that are easy to get wrong. Each has a test in the task named.

1. **A rule edited to a new Source Calendar.** The old watch must be stopped and a new one registered in the next upkeep, with coverage moved. Test: `test_a_rule_moved_to_another_source_calendar_moves_its_watch` (Task 4).
2. **A reverse proxy that drops the query string or rewrites the body.** Graph's `validationToken` check fails, so subscription creation is refused as `unreachable`. Evidence turns `failing`, the switch says why, and the docs name the fix. Tests: the Graph `unreachable` mapping (Task 11), evidence failure on `UNREACHABLE` (Task 4), and the docs anchor test (Task 20).
3. **Two Users, or two installations sharing one OAuth app, watching the same Outlook mailbox.** Graph answers `409`. Adoption must take only an exact registration id, and the other subscription must never be deleted. Tests: `adopt` exact-match tests (Task 11) and the duplicate path in upkeep (Task 4).
4. **Notices that arrive while the rule is already running, or in a burst.** They coalesce into one pending request per rule, and one more run follows the current one. Tests: the "notice during a run" and timing-table tests (Task 14), and the identical-notices test (Task 7).
5. **A restart or crash with requests pending, or between a run and its acknowledgement.** The request stays durable and runs once after restart, without waiting for a new notice. Tests: the crash-before-acknowledgement test (Task 14) and the dispatcher start-up scan (Task 16).

## Settled interface decisions

The parts of this plan were drafted in parallel from one shared contract. Where a part had to refine the contract, it recorded the change below, and later tasks already use the refined form. When a task's code and this section disagree, the task's code wins. Report the disagreement in the review.

### From part A


1. **`UpkeepWatches` takes seven constructor fields, not ten.** `tests/test_architecture.py` fails
   any application dataclass with behavior whose constructor takes more than ruff's `max-args`
   (7), and its allowlist may only shrink. Task 4 groups the provider lookups and the random
   sources into two records without behavior, which the check ignores:
   `WatchProviders(watcher_for, provider_of, slug_of, backoff=AccountBackoff())` and
   `FreshValues(new_token, new_id, jitter)` (each with the contract's defaults). The use case is
   `UpkeepWatches(unit_of_work, providers, evidence, clock, call_stats, lapses=None,
   fresh=FreshValues())`. `call_stats: ProviderCallStats` is required, not defaulted: an
   untallied default would never spend the budget. Part D (bootstrap, `WatchUpkeep.upkeep_for`)
   must build it this way, pass the container's `ContextProviderCallStats`, and share ONE
   `AccountBackoff` instance across every User's `WatchProviders`.
2. **`UpkeepWatches.unit_of_work` is a narrow protocol, `WatchUnitOfWorkFactory`.** Its units
   expose only `watches: CalendarWatchRepository`, `rules` with `list() -> Sequence[SyncRule]`,
   `provider_calls`, `commit()`, and the context manager. The real `UnitOfWorkFactory` satisfies
   it structurally once Task 6 adds `watches`. `lapses` is typed `AccountLapses`, a protocol with
   `LapsedAuthorizations.lapsed`'s signature; bootstrap passes the real `LapsedAuthorizations`.
3. **Task 3 does not add `watches` and `instant_requests` to the `UnitOfWork` protocol.** Adding
   them breaks mypy for both unit-of-work classes until they implement them. Task 6 (Part B) adds
   the two attributes to `UnitOfWork` in `application/sync/ports.py` together with the SQLite and
   in-memory implementations.
4. **`WatchRegistration.gone(now)` also covers a `live` registration past `expires_at`.** It is
   true for every state but `creating` once `expires_at or requested_until` has passed, so an
   expired live row is deleted and recreated instead of lingering forever.
5. **Additions** (all listed under the producing task): `WatchScope.calendar_id` (the calendar a
   calendar scope names, for the Google adapter); `NOTICE_PATH = "/api/v1/watch-notices"` in
   `watch_ports.py`; `RuleListing`, `WatchUnitOfWork`, `WatchUnitOfWorkFactory`, `AccountLapses`,
   `AccountBackoff`, `WatchProviders`, `FreshValues`, `STOP_DEADLINE` in `instant_sync.py`; and
   `CallCountingUnitOfWork`, `CallCountingUnitOfWorkFactory` in `resource_use.py`.
6. **`record_provider_calls` takes a narrower unit-of-work factory.** Task 4 changes its first
   parameter from `UnitOfWorkFactory` to `CallCountingUnitOfWorkFactory` (only `provider_calls`,
   `commit`, and the context manager), so upkeep can record its calls through
   `WatchUnitOfWorkFactory`. Existing callers pass a `UnitOfWorkFactory`, which still satisfies it.
7. **Repository semantics Part B must implement** (the contract left them open; Task 4's fakes
   pin them):
   - `record_receipt` changes only a `creating` row. It keeps a `confirmed_at` already set (a
     Google `sync` notice may arrive before `register` returns) and otherwise sets it to `at` only
     when `receipt.confirmed`.
   - `record_extension` changes only a `live` row, and clears `renew_requested_at` only when it
     still equals `seen_request`.
   - `retire` moves only `live` to `retiring`; `abandon` moves any existing row to `abandoned`
     and returns whether the row exists; `delete_registration` of a missing row does nothing;
     `remove(watch_id)` also deletes the watch's coverage and registrations.
   - `DeliveryEvidenceLog.succeeded` and `.failed` keep the later of the stored and the given
     time. Upkeep records an overdue Google confirmation at `created_at + CONFIRMATION_DEADLINE`
     on every cycle; keeping the later time is what makes that one failure, not a new one per
     cycle.
8. **Budget accounting is measured.** `CallBudget.spend(calls: int) -> None` subtracts what one
   watcher method measured and may take `remaining` below zero; `exhausted` is
   `remaining <= 0`. `execute` and `stop_all` run inside `call_stats.measure()` and record the
   tally per User with `record_provider_calls` in a `finally`. No watcher method starts once the
   budget is exhausted; each one then spends the calls the tally grew by, so a local `scope()`
   (Google) costs nothing and paged listings cost every page. Adapters must record every HTTP
   call through `infrastructure/provider_calls.record_call`, as calendar calls do today.
9. **Discovery is incremental.** `scope()` is called only for a Source Calendar no existing watch
   covers; a covered source keeps its watch's scope (so a calendar whose watchability changes is
   noticed only after its watch is retired). Each discovered calendar is persisted at once
   (`add` or `set_coverage`), so a cycle the budget ends early keeps its progress. An account
   whose discovery is incomplete (budget, backoff) or unsure (a scope failure) keeps every watch
   and its coverage; only accounts whose every source was resolved have coverage narrowed and
   empty watches retired. A source that is not watchable (`scope()` returns `None`) is
   remembered in the process for `UNWATCHABLE_RECHECK = timedelta(days=1)` and not asked again
   until then; a restart forgets it.
10. **Scope failures back off per account, in the process.** `AccountBackoff` holds
    `account -> (not_before, failures)`, set with `backoff(failures, Retry-After)`; discovery
    skips the account until then. The same object holds `calendar -> recheck_at` for
    unwatchable calendars (deviation 9). Its constructor is unchanged: `AccountBackoff()` takes
    no arguments, and `WatchProviders(watcher_for, provider_of, slug_of, backoff=...)` is
    unchanged. `unauthorized` lapses the account instead (when `lapses` and
    `failure.failure` are set). The state is lost on restart, which only means one early retry.
11. **Retiring registrations are stopped by later cycles.** Every cycle stops `retiring`
    registrations, and `live` ones that are not current, of kept watches; retired watches stop
    both `live` and `retiring` ones. A stop the budget cannot pay for leaves the row as it is.
    Graph's `removed` notice also makes a row `retiring`; its adapter's `stop` should treat a
    `404` as stopped.
12. **`stop_all(account=None, deadline=STOP_DEADLINE)`**, `STOP_DEADLINE = timedelta(seconds=10)`.
    No stop starts once `deadline` has passed since the call began; every watch row is then
    deleted anyway, and providers expire what was not stopped.
13. **Failure handling details.** Watchers raise only `WatchFailure`; they translate
    `ConnectedAccountNotFound` and `ConnectedAccountDisconnected` into `unsupported` (Part C), so
    upkeep has no handler for them. A refused `register` deletes its `creating` row, except
    `temporary`, which abandons it (the provider may have made it). `duplicate` calls `adopt`
    once with the new registration's id only; with no match the row is deleted and the watch gets
    `retry_at = now + MAX_BACKOFF` and `failures + 1`. An abandoned row's own subscription is not
    adopted; it expires within 7 days. A failed `stop` only abandons the row (spec step 5: best
    effort); it never lapses the account. `unauthorized` without `lapses`, or without
    `failure.failure`, backs off like any other failure.


### From part B


1. **Identity port name.** The identity port is `UserDirectory` (`application/identity/ports.py`),
   not `UserRepository`. Task 9 adds `UserDirectory.set_instant_sync(user_id, wanted)`; the test
   stand-in is `tests/identity_fakes.MemoryUsers`.
2. **Where the UnitOfWork attributes land.** Task 3 did not add `watches` and `instant_requests` to
   the `UnitOfWork` Protocol, so Task 6 adds them, together with both units (Part A deviation 3).
   `sync/ports.py` imports the two Protocols directly from `watch_ports`. This is safe because
   Part A's `watch_ports` does not import `sync/ports.py`.
3. **Task numbers in `operations/ports.py`.** Task 7 adds `WatchNoticeInbox` and `InboxBusy`, and
   Task 8 adds `InstantSyncOwner`, `PendingInstantRun`, and the two `InstallationUnitOfWork`
   queries. The contract says Task 9 for both.
4. **`transaction()` gains a keyword `timeout`.** This is the spec's "new parameter of
   `connections.py`". `open_connection(timeout=)` already exists, and the inbox opens its one
   transaction through `transaction(path, timeout=INBOX_LOCK_WAIT_SECONDS)`.
5. **`InstantSyncOwner.next_due`** is the earliest of:
   - a watch's `retry_at`
   - a `live` registration's `renew_requested_at`, `renew_at`, or `expires_at` (Part A's `gone`
     also covers a `live` registration past its expiry)
   - a `creating` registration's `created_at + CREATION_DEADLINE`
   - a `retiring` or `abandoned` registration's `expires_at or requested_until`

   It is `None` when nothing is planned, for example for a User without a watch yet. `WatchUpkeep`
   (Part D) should order `None` first, because such a User's coverage is missing. The confirmation
   deadline is left out: an unconfirmed registration would stay overdue forever and starve other
   Users of the budget.
6. **`pending_instant_runs()` does not filter by preference or cadence.** It excludes disabled
   Users and rules that are not enabled. It does not check the User's `instant_sync` preference or
   `SyncCadence`: `InstantDispatch` decides those, and it can read `wanted` from
   `instant_sync_owners()`.
7. **`PersistenceHarness` gains two hooks.** Both units of work run the shared contract, which
   reaches state outside any unit only through harness hooks:
   - `request_run(user, rule_id, at)` (Task 6) raises a rule's request.
   - `prefer(user, wanted)` (Task 8) sets the preference.
8. **Inbox checks the contract leaves open:**
   - A notice counts only when its registration's account has the `provider` that the route's slug
     names.
   - Success evidence is refreshed for `address_base` only when the registration's `address`
     starts with `f"{address_base}/"`. A notice that reached an earlier address proves nothing
     about the current one.
   - Identical notices in one batch count once.
   - A `removed` notice turns a `live` registration `retiring` and a `creating` one `abandoned`.
     A receipt that arrives after the removal therefore changes nothing, and the subscription the
     provider removed never becomes `live` (Codex review).
   - Raising a request never moves its times back, because concurrent notices commit in any
     order (Codex review):
     - `last_requested_at` becomes `MAX(stored, given)`.
     - `first_requested_at` is set when the request becomes pending, and while it stays pending
       it keeps `MIN(stored, given)`.
   - Requests of paused rules and of disabled Users stay out of `pending_instant_runs()` and wait
     there (decided; the spec is being updated).
9. **Repository semantics follow Part A's deviation 6 exactly:**
   - `record_receipt` changes only a `creating` row and keeps a `confirmed_at` already set.
   - `record_extension` changes only a `live` row, and clears `renew_requested_at` only while it
     still equals `seen_request`.
   - `retire` moves only `live` to `retiring`.
   - `abandon` moves a row in any state, including `abandoned`, and returns whether the row exists
     for this User.
   - `delete_registration` of a missing row does nothing, and `remove` cascades.
   - `DeliveryEvidenceLog.succeeded` and `.failed` keep the later time (`MAX`).
10. **Memory store:**
    - The in-memory inbox writes committed partitions directly, as SQLite's inbox commits rows.
    - A memory unit copies its whole partition when it opens and when it commits. A unit kept open
      across an inbox call would therefore overwrite the inbox's writes.
    - Tests interleave notices only between units, which is also how production code runs: no
      unit spans a provider call.
    - `MemoryDatabase` gains `delivery_evidence` (Task 7) and `instant_sync_off` (Task 8).
11. **Extra names produced** (listed in each task's Produces):
    - `infrastructure/persistence/watches.py`: `stored_time`, `watch_from_row`,
      `registration_from_row`, `request_from_row`, and `upkeep_due`
    - `infrastructure/persistence/watch_inbox.py`: `presents`, `EVIDENCE_REFRESH`, and
      `INBOX_LOCK_WAIT_SECONDS`
    - `infrastructure/persistence/memory.py`: `raise_instant_request`
    - `infrastructure/persistence/memory_installation.py`: `InMemoryWatchNoticeInbox(database,
      busy=False)` and `InMemoryDeliveryEvidenceLog(database)`
    - `SqliteWatchNoticeInbox(database_path, lock_wait=INBOX_LOCK_WAIT_SECONDS)` and
      `SqliteDeliveryEvidenceLog(database_path)`

---


### From part C


1. **New provider-neutral helper `infrastructure/watch_failures.py`** (Task 10):
   `watch_failure(failure: ProviderFailure) -> WatchFailure`. Both adapters translate a refusal to a
   `ProviderFailure` the way their calendar adapter already does, then this one function classes it
   for upkeep. It is added to the "Provider-neutral infrastructure" import contract in
   `pyproject.toml`.
2. **`unauthorized` is narrower than a Sync Run's authorization failures.** Only
   `ProviderFailureKind.AUTHENTICATION`, or `AUTHORIZATION` whose Cause is `ACCESS_REVOKED`, becomes
   `UNAUTHORIZED`. A bare `403` while watching becomes `UNSUPPORTED`, because it may refuse only
   watching that calendar, and the spec says that "a provider that cannot watch a calendar never
   lapses the account". The account's next Sync Run still lapses it if its credentials are really
   refused.
3. **Small public seams in the calendar adapters, so nothing is duplicated:**
   - `infrastructure/google/provider.py`: `send(operation, request, timer)` (was the body of
     `GoogleCalendarProvider._call`), `google_failure(error, account, *, attempted_at, now,
     event_scoped=False)` (was the body of `_failure`), and `_status_code` renamed `status_code`.
   - `infrastructure/microsoft/provider.py`: `refusal_failure(error, account, *, attempted_at, now,
     event_scoped=False)` (was the body of `OutlookCalendarProvider._failure`).
   - `infrastructure/microsoft/graph.py`: `GraphRefusal` gains `endpoint_refused: bool = False`.
     Graph says that a notification URL failed validation only in the message text, so
     `graph_refusal` matches the message and keeps only this boolean, never the text.
4. **`ProviderDirectory` gains `watching(slug) -> ProviderDescriptor | None` and
   `slug_of(kind) -> str`** (Task 12). The route (Task 17) uses `watching` to find the reader and
   Provider Kind for a slug. Bootstrap (Task 16) passes `providers.slug_of` as
   `UpkeepWatches.slug_of`.
5. **`RoutingCalendarWatcher.provider_of(account) -> ProviderKind | None`** (Task 12). Bootstrap
   passes it as `UpkeepWatches.provider_of`, so both share one cached lookup.
6. **`CalendarWatcher.scope` may raise `WatchFailure`** (Outlook asks Graph who owns the calendar).
   Every watcher method raises `WatchFailure` for a provider refusal. The credential stores raise
   `ConnectedAccountNotFound` and `ConnectedAccountDisconnected`. Both watchers catch these first,
   in every method that reads credentials, and raise
   `WatchFailure(UNSUPPORTED, "the connected account is no longer available")`. The detail names
   no account. This uses `account_unavailable()` in `watch_failures.py`. So Google's broad
   `except Exception` never turns them into `TEMPORARY`, and nothing untranslated reaches upkeep.
7. **Some watcher calls make more than one provider call, and the budget counts each one.**
   Outlook `scope` makes two lookups when cold: `/me/calendar` and the calendar's own owner.
   Outlook `adopt` reads every page of `GET /subscriptions`. Outlook `stop` of a registration with
   no handle (its `201` was lost) reads those pages too, then deletes only the exact match. Every
   watcher request goes through the path the calendar adapters use, so `record_call` adds it to
   the per-thread `ProviderCallStats` tally:
   - Google `events.watch` and `channels.stop` go through `provider.send`.
   - Every Graph request, including each listing page, goes through `GraphHttp.request`.

   Upkeep spends the calls it measured, so pages count. Access token refreshes go through the same
   paths the calendar adapters use, and are tallied as `token_refreshes`, not `calls`.
8. **For Task 17 (route):** Graph validates `notificationUrl` and `lifecycleNotificationUrl` separately.
   Both point at the same address, so each create sends two validation requests. Each is a
   `POST ...?validationToken=...` with a `text/plain` body, and it must be answered within 10
   seconds. The route must call `reader.validation_token(request)` before it treats the body as a
   notice. A Graph lifecycle event this release does not know is read as `MISSED`, which asks for a
   catch-up run.
9. **Test fakes grow:** `tests/fake_microsoft_graph_api.py` serves `/subscriptions` (new
   `tests/fake_graph_subscriptions.py`), `GET /me/calendar`, and `GET /me/calendars/{id}`.
   `FakeCalendar` gains `owner: str | None = None`.
10. **Docs:** `docs/architecture.md` ("Provider descriptors": the descriptor's roles and the neutral
    modules list) needs the watcher, the notice reader, and `watch_failures`. Part E owns that edit.


### From part D


1. **`INSTALLATION_UNIT_RECEIVERS` gains `application/operations/instant_sync.py` in Task 13, not
   Task 14.** Task 13 is the first to import `InstallationUnitOfWorkFactory` there, and
   `tests/adapters/test_user_isolation_schema.py` fails from that commit on otherwise.
2. **`UpkeepWatches` is built as Part A's deviation 1 says, with its review changes:**
   `UpkeepWatches(unit_of_work, WatchProviders(watcher_for, provider_of, slug_of,
   backoff=account_backoff), evidence, clock, lapses=..., call_stats=adapters.call_stats)`.
   - `watcher_for` is the `RoutingCalendarWatcher` itself, `provider_of` is its `provider_of`
     (Part C deviation 5), and `slug_of` is `ProviderDirectory.slug_of` (Part C deviation 4).
   - One `AccountBackoff()` per process (`Adapters.watch_backoff`) goes to every User's
     `WatchProviders`.
   - Part D assumes the names `AccountBackoff` (in `application/sync/instant_sync.py`, no
     constructor arguments) and the keywords `backoff` and `call_stats`. If Part A names them
     otherwise, rename them in `_watch_upkeep` and `Adapters`.
3. **`WatchUpkeep` carries the Users a cycle did not finish into the next cycle** (a sixth field,
   `_carried: tuple[UserId, ...] = ()`, like `ScheduledPass._due`). Each cycle goes in this order:
   - the Users the last cycle never reached
   - the User it stopped on, whose upkeep the budget may have cut short
   - Users whose `next_due` is None: nothing is planned yet, so coverage is missing (Part B
     deviation 5)
   - the rest by `next_due`

   So no User starves, and two Users whose backlogs each exceed the budget take turns. Part A
   persists discovery progress and counts measured calls; the test fake spends with
   `CallBudget.spend(cost)`.
4. **`InstantSyncStatus` takes seven fields:** `users, unit_of_work, cadence, evidence,
   provider_of, address, clock`. It also has `poll_every(user) -> timedelta`, which the rule
   responses read.
5. **`InstantSyncDispatcher` gains `longest_sleep_seconds: float = 60.0`** (keyword, so tests
   can shorten it). `WatchKeeper(upkeep, interval_seconds=300)` runs upkeep in one worker thread,
   one User after another, not with a concurrency of 2: one `CallBudget` is spent in due order,
   and `CallBudget` is not thread-safe.
6. **A dropped request is acknowledged with `ran_at = now`.** The contract's `acknowledge` always
   sets `last_run_at`, so a dropped request also starts that rule's `MIN_GAP`. This is harmless:
   the rule may not run instantly at that moment anyway.
7. **Requests of paused rules and disabled Users wait.** `pending_instant_runs` never lists them,
   so neither `due()` nor `run()` sees them. Once the rule or User is active again, they run, or
   are dropped by the usual rules (preference, Plan, failing last run). The tests' fake lists
   requests as production does. `run(item)` reads the request again before running, because a run
   may wait in the dispatcher's queue:
   - a request no longer listed waits, unrun
   - one no longer eligible is dropped, unrun

   That read lists every pending run, as the contract has no query for one rule.
8. **Effective cadence is on `RuleSummaryResponse` and `RuleDetailResponse` only** (the list and
   detail reads). It is not on `RuleResponse`, which create, enable, pause, edit, and replace
   return. The schema uses the Literal aliases `InstantSyncAvailabilityValue` and
   `EffectiveCadenceValue`, which mirror `Availability` and `CadenceReason` and are added to
   `tests/adapters/test_schema_enums.py`.
9. **The Watch Notice route is left out of the OpenAPI schema** (`include_in_schema=False`).
   Providers call it, not the Web UI, whose types come from that schema. The route builds its path
   from Part A's `NOTICE_PATH`. It asks `reader.validation_token` with headers and query only, and
   an empty body, before it reads the body (Part C deviation 8). It answers a blank registration id
   with the same `202` as an unknown one, without recording anything.
10. **Names used from Part B:**
    - `SqliteWatchNoticeInbox(database_path)` (default `lock_wait`) and
      `SqliteDeliveryEvidenceLog(database_path)`
    - `SetInstantSync(users).execute(user_id, wanted) -> User` and `User.instant_sync`
    - `memory_units()` units with working `watches`
    - `pending_instant_runs()` does not filter by preference or cadence, and `InstantDispatch`
      does (Part B deviation 6).

    The route passes the https public address, with no trailing slash, as `address_base`. The
    inbox compares registrations against it (Part B deviation 8). Task 17 wires `SetInstantSync`
    into `IdentityServices`; if Task 9 already does that, skip that hunk.
11. **The loops and the inbox exist only with an https public address and the master key** (the
    brief). Without them nothing retires earlier registrations. Each expires at its provider within
    `LONGEST_REGISTRATION`, and the next upkeep that has an address deletes its row.
12. **The notice route takes `at` from `datetime.now(UTC)`,** as `routes/accounts.py` already
    does, rather than from an injected clock.
13. **Bootstrap filters Uvicorn's access log** (`bootstrap/logs.py`, `NoticePathFilter`). Each
    access line names the request path, and a Watch Notice path names its registration, which the
    spec says no log line may. The filter rewrites the path to `/api/v1/watch-notices/<slug>/…`,
    dropping the registration and any query, such as a validation token.
14. **`OwnedRules` gains `stop_watches: Callable[[], None]`, and `DisconnectConnectedAccount`
    gains `stop_watches: Callable[[ConnectedAccountId], None]`.** Bootstrap passes them
    `UpkeepWatches.stop_all`, so `identity` and `sync` never import `operations`.
    `DeleteConnectedAccount` stops nothing: its account is already disconnected and has no
    credentials. The watch rows cascade with it.
15. **Task 17 also updates the typed Web UI test fixtures,** which the regenerated types make
    incomplete, and runs the complete frontend gate (audit, api:check, typecheck, lint, doctor,
    knip, test, build), so it stays green in every commit. Only fixtures and erased types change,
    so the rebuilt static assets are committed only when they differ by more than the embedded
    commit SHA. The user's standing rule is that no SHA-only rebuild is committed. Part E (Task 18) adds the API
    client method and the UI.
16. **Aligned with Part E's assumptions:**
    - `Adapters.delivery_evidence: DeliveryEvidenceLog` and `Adapters.sync_cadence:
      SyncCadencePolicy` (default `EveryUserInstant()`). `compose` reads the policy from there,
      so Task 19 and a later Plans phase replace it in one place.
    - `PUT /api/v1/account/instant-sync` answers `SignedInUserResponse`.
    - `instant_sync_availability` and `effective_cadence` are `Literal` aliases mirroring
      `Availability` and `CadenceReason`.
    - Rule responses carry no docs anchor (Part E deviation 7).

    Nothing in Part E's assumptions was left unaligned.
17. **Left to Part E:** AGENTS.md's sentence that "only the scheduler, migrations, and the
    Operator Overview" receive `InstallationUnitOfWork`. Instant Sync's upkeep and dispatch run
    beside the scheduler. Task 17 edits only AGENTS.md's list of public routes.


### From part E


1. **`InstallationHint.cause` becomes `Cause | None`** (Task 19). The two Instant Sync hints come
   from no failed provider call, so they have no Cause. `InstallationHintResponse.cause` becomes
   `CauseValue | None`, and `HintKind` (with its schema alias `HintKindValue`) gains
   `plain_http_address` and `notices_not_arriving`.
2. **`GetInstallationHealth` takes a `HintSources` record** (Task 19). It already has 7 constructor
   fields, Ruff's `max-args`, and `tests/test_architecture.py` forbids an eighth. `sightings` and
   `guides` move into `HintSources(sightings, guides, instant_sync)`; the tests and the container
   that construct it change with it.
3. **The plain-HTTP hint fires only for a host the internet reaches** (Task 19). The spec says any
   `http` public address. DESIGN.md says "Plain HTTP on this machine or a home network is the
   homelab norm and says nothing", and an `http://192.168.1.50:8000` public address is common for
   email links. A hint there would make Installation Health need attention forever. Each person's
   switch still says `no_public_address` with its "Learn why" link.
4. **Task 16 names assumed** (Task 19 container wiring): `Adapters.delivery_evidence:
   DeliveryEvidenceLog` and `Adapters.sync_cadence: SyncCadencePolicy`. Delivery Evidence is
   assumed to be keyed by the public base address as `public_address(settings)` returns it (no
   trailing slash). If Task 16 chose other names, use them in `_instant_sync_signals`.
5. **`PUT /api/v1/account/instant-sync` is assumed to answer `SignedInUserResponse`**, as
   `/account/notifications` does. Task 18 adds `api.setInstantSync` to `web/src/lib/api.ts`.
6. **The Web UI reads `instant_sync_availability` and `effective_cadence` as strings** and treats a
   value it does not know as `unknown`. This works whether Task 17 typed them as `str` or as
   `Literal` aliases. Recommended for the integrator: `Literal` aliases mirroring `Availability`
   and `CadenceReason` in `tests/adapters/test_schema_enums.py`.
7. **Rule responses carry no docs anchor**, so the rule page's "Learn why" uses a Web UI map from
   reason to section (`web/src/lib/instant-sync.ts`). Task 20's `tests/test_instant_sync_docs.py`
   checks every section it names exists, as `tests/test_troubleshooting_anchors.py` does for
   `causes.ts`.
8. **Migration 31 in `docs/deployment.md`**: Task 20 writes its upgrade and rollback paragraph. If
   Task 5 already added one, Task 20 replaces it with this text.
9. **Web test fixtures**: if Task 17 regenerated the web types without updating the frontend test
   fixtures, Task 18 Step 4 adds the new required fields to them.
10. **CONTEXT.md also gains "Sync Cadence"**, which the spec capitalizes as a term. "Push sync" and
    "real-time sync" move from Scheduled Sync's `_Avoid_` line to Instant Sync's, and join
    `AVOIDED` in `tests/test_ubiquitous_language.py`.
11. **Possible leak for Task 17 to check**: Uvicorn's access log prints request paths, and the
    notice path contains the registration id. Task 21 Step 6 checks the logs for registration ids.

---


---

### Task 1: Sync Cadence and the values of Calendar Watches

**Files:**
- Create: `src/calendar_sync/domain/cadence.py`
- Create: `src/calendar_sync/domain/watches.py`
- Test: `tests/domain/test_cadence.py`
- Test: `tests/domain/test_watches.py`

**Interfaces:**
- Consumes: `calendar_sync.domain.model` (`CalendarEndpoint`, `CalendarId`,
  `ConnectedAccountId`), `calendar_sync.domain.errors.DomainValidationError`.
- Produces, in `calendar_sync.domain.cadence`:
  - `SCHEDULED_EVERY = timedelta(minutes=5)`
  - `SyncCadence(instant: bool, poll_every: timedelta)` (frozen; `poll_every <= 0` raises
    `DomainValidationError`)
  - `DEFAULT_CADENCE = SyncCadence(instant=True, poll_every=SCHEDULED_EVERY)`
- Produces, in `calendar_sync.domain.watches`:
  - `CREATION_DEADLINE`, `CONFIRMATION_DEADLINE`, `LONGEST_REGISTRATION`, `MAX_BACKOFF`
  - `CalendarWatchId(value: str)`, `WatchRegistrationId(value: str)` (non-empty)
  - `WatchScope(key: str)` with `WatchScope.account()`, `WatchScope.calendar(calendar_id)`, and
    the property `calendar_id -> CalendarId | None` (new; for the Google adapter)
  - `RegistrationState` (`CREATING`, `LIVE`, `RETIRING`, `ABANDONED`)
  - `WatchRegistration(id, watch_id, state, address, token_hash, created_at, requested_until,
    handle=None, expires_at=None, confirmed_at=None, renew_at=None, renew_requested_at=None)` with
    `usable(now, address)`, `delivering(now)`, `creation_stale(now)`,
    `confirmation_overdue(now)`, `renewal_due(now)`, `gone(now)` (`gone` widened: see
    deviation 4)
  - `CalendarWatch(id, account, scope, coverage=frozenset(), retry_at=None, failures=0)` with
    `covers(calendar: CalendarEndpoint) -> bool` and `waiting(now) -> bool`
  - `renewal_time(created_at, expires_at, jitter) -> datetime` (jitter outside `[0, 1)` raises)
  - `backoff(failures, retry_after=None) -> timedelta` (`failures < 1` raises)
  - `token_hash(token) -> str` (sha256 hex digest, as `infrastructure/security.token_hash`)

- [ ] **Step 1: Write the failing tests**

`tests/domain/test_cadence.py`:

```python
"""A Sync Cadence says how soon a User's rules run; with Plans off, everyone's is the default."""

from datetime import timedelta

import pytest

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainValidationError


def test_the_default_cadence_syncs_instantly_and_polls_every_five_minutes() -> None:
    assert (DEFAULT_CADENCE.instant, DEFAULT_CADENCE.poll_every) == (True, SCHEDULED_EVERY)
    assert timedelta(minutes=5) == SCHEDULED_EVERY


@pytest.mark.parametrize("poll_every", [timedelta(0), timedelta(minutes=-5)])
def test_a_cadence_must_poll_after_some_time(poll_every: timedelta) -> None:
    with pytest.raises(DomainValidationError):
        SyncCadence(instant=False, poll_every=poll_every)
```

`tests/domain/test_watches.py`:

```python
"""Watch Registrations and Calendar Watches decide their own lifecycle from time alone."""

import hashlib
from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    CREATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    backoff,
    renewal_time,
    token_hash,
)
from tests.helpers import NOW, endpoint

ADDRESS = "https://ghost.example.test/api/v1/watch-notices/example/registration-1"
LIVE = WatchRegistration(
    id=WatchRegistrationId("registration-1"),
    watch_id=CalendarWatchId("watch-1"),
    state=RegistrationState.LIVE,
    address=ADDRESS,
    token_hash=token_hash("synthetic-token"),
    created_at=NOW,
    requested_until=NOW + LONGEST_REGISTRATION,
    handle="synthetic-handle",
    expires_at=NOW + timedelta(days=6),
    confirmed_at=NOW,
    renew_at=NOW + timedelta(days=4),
)
CREATING = replace(
    LIVE,
    state=RegistrationState.CREATING,
    handle=None,
    expires_at=None,
    confirmed_at=None,
    renew_at=None,
)


@pytest.mark.parametrize("value", ["", "   "])
def test_identifiers_must_not_be_empty(value: str) -> None:
    with pytest.raises(DomainValidationError):
        CalendarWatchId(value)
    with pytest.raises(DomainValidationError):
        WatchRegistrationId(value)


def test_a_scope_covers_an_account_or_one_calendar() -> None:
    assert WatchScope.account().key == "account"
    assert WatchScope.account().calendar_id is None
    assert WatchScope.calendar(CalendarId("team@example.test")).key == "calendar:team@example.test"
    assert WatchScope.calendar(CalendarId("team")).calendar_id == CalendarId("team")


@pytest.mark.parametrize("key", ["", "calendar", "calendar:", "calendar: ", "mailbox"])
def test_a_scope_refuses_any_other_key(key: str) -> None:
    with pytest.raises(DomainValidationError):
        WatchScope(key)


def test_a_live_registration_is_usable_only_at_its_own_address_until_it_expires() -> None:
    assert LIVE.usable(NOW, ADDRESS)
    assert not LIVE.usable(NOW, ADDRESS.replace("ghost", "moved"))
    assert not LIVE.usable(NOW + timedelta(days=6), ADDRESS)
    for state in (RegistrationState.RETIRING, RegistrationState.ABANDONED):
        assert not replace(LIVE, state=state).usable(NOW, ADDRESS)
    assert not CREATING.usable(NOW, ADDRESS)


def test_only_a_confirmed_live_unexpired_registration_is_delivering() -> None:
    assert LIVE.delivering(NOW)
    assert not replace(LIVE, confirmed_at=None).delivering(NOW)
    assert not LIVE.delivering(NOW + timedelta(days=6))
    assert not replace(LIVE, state=RegistrationState.RETIRING).delivering(NOW)


def test_a_creation_is_stale_once_its_deadline_passes() -> None:
    assert not CREATING.creation_stale(NOW + CREATION_DEADLINE - timedelta(seconds=1))
    assert CREATING.creation_stale(NOW + CREATION_DEADLINE)
    assert not LIVE.creation_stale(NOW + CREATION_DEADLINE)


def test_an_unconfirmed_live_registration_is_overdue_after_the_confirmation_deadline() -> None:
    unconfirmed = replace(LIVE, confirmed_at=None)

    assert not unconfirmed.confirmation_overdue(NOW + CONFIRMATION_DEADLINE - timedelta(seconds=1))
    assert unconfirmed.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)
    assert not LIVE.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)
    assert not CREATING.confirmation_overdue(NOW + CONFIRMATION_DEADLINE)


def test_renewal_is_due_at_its_time_or_when_the_provider_asks() -> None:
    assert not LIVE.renewal_due(NOW + timedelta(days=4) - timedelta(seconds=1))
    assert LIVE.renewal_due(NOW + timedelta(days=4))
    assert replace(LIVE, renew_requested_at=NOW).renewal_due(NOW)
    assert not replace(LIVE, state=RegistrationState.RETIRING, renew_requested_at=NOW).renewal_due(
        NOW
    )


def test_a_registration_is_gone_once_it_would_have_expired() -> None:
    retiring = replace(LIVE, state=RegistrationState.RETIRING)
    lost = replace(CREATING, state=RegistrationState.ABANDONED)

    assert not retiring.gone(NOW + timedelta(days=6) - timedelta(seconds=1))
    assert retiring.gone(NOW + timedelta(days=6))
    assert LIVE.gone(NOW + timedelta(days=6))
    # Without an answer, it is kept as long as upkeep asked the provider to keep it.
    assert not lost.gone(NOW + timedelta(days=6))
    assert lost.gone(NOW + LONGEST_REGISTRATION)
    assert not CREATING.gone(NOW + timedelta(days=30))


def test_a_watch_covers_only_its_own_accounts_calendars_in_its_coverage() -> None:
    watch = CalendarWatch(
        CalendarWatchId("watch-1"),
        ConnectedAccountId("personal-account"),
        WatchScope.account(),
        coverage=frozenset({CalendarId("personal-calendar")}),
    )

    assert watch.covers(endpoint("personal-account", "personal-calendar"))
    assert not watch.covers(endpoint("personal-account", "other-calendar"))
    assert not watch.covers(endpoint("work-account", "personal-calendar"))


def test_a_watch_waits_until_its_retry_time() -> None:
    watch = CalendarWatch(
        CalendarWatchId("watch-1"), ConnectedAccountId("personal-account"), WatchScope.account()
    )

    assert not watch.waiting(NOW)
    assert replace(watch, retry_at=NOW + timedelta(minutes=1)).waiting(NOW)
    assert not replace(watch, retry_at=NOW).waiting(NOW)


@pytest.mark.parametrize(
    ("jitter", "after"),
    [(0.0, timedelta(days=4)), (0.5, timedelta(days=4, hours=12)), (0.999, timedelta(days=5))],
)
def test_renewal_falls_in_the_last_third_of_the_lifetime(jitter: float, after: timedelta) -> None:
    renew_at = renewal_time(NOW, NOW + timedelta(days=6), jitter)

    assert abs(renew_at - (NOW + after)) < timedelta(minutes=10)
    assert NOW + timedelta(days=4) <= renew_at < NOW + timedelta(days=5)


@pytest.mark.parametrize("jitter", [-0.1, 1.0])
def test_renewal_jitter_lies_between_zero_and_one(jitter: float) -> None:
    with pytest.raises(DomainValidationError):
        renewal_time(NOW, NOW + timedelta(days=6), jitter)


@pytest.mark.parametrize(
    ("failures", "delay"),
    [
        (1, timedelta(minutes=1)),
        (2, timedelta(minutes=2)),
        (5, timedelta(minutes=16)),
        (11, timedelta(minutes=1024)),
        (12, MAX_BACKOFF),
        (500, MAX_BACKOFF),
    ],
)
def test_backoff_doubles_from_a_minute_up_to_a_day(failures: int, delay: timedelta) -> None:
    assert backoff(failures) == delay


def test_backoff_honors_a_longer_retry_after() -> None:
    assert backoff(1, timedelta(minutes=10)) == timedelta(minutes=10)
    assert backoff(3, timedelta(seconds=30)) == timedelta(minutes=4)


def test_backoff_follows_at_least_one_failure() -> None:
    with pytest.raises(DomainValidationError):
        backoff(0)


def test_a_token_is_kept_only_as_its_sha256_hex_digest() -> None:
    digest = token_hash("synthetic-token")

    assert digest == hashlib.sha256(b"synthetic-token").hexdigest()
    assert "synthetic-token" not in digest
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/domain/test_cadence.py tests/domain/test_watches.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.domain.cadence'` and
`'calendar_sync.domain.watches'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/domain/cadence.py`:

```python
"""Sync Cadence: how soon a User's rules run after their sources change (ADR 0036).

Plans decide it (ADR 0028). While Plans are off, every User has the default cadence: Instant Sync,
and Scheduled Sync every five minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from calendar_sync.domain.errors import DomainValidationError

SCHEDULED_EVERY = timedelta(minutes=5)
"""How often Scheduled Sync runs every enabled rule."""


@dataclass(frozen=True, slots=True)
class SyncCadence:
    """How soon a User's rules run after their sources change."""

    instant: bool
    """Whether a rule may run soon after its provider reports a change (Instant Sync)."""
    poll_every: timedelta
    """How often Scheduled Sync runs the rule, whether or not it also syncs instantly."""

    def __post_init__(self) -> None:
        if self.poll_every <= timedelta(0):
            raise DomainValidationError("a sync cadence must poll after some time")


DEFAULT_CADENCE = SyncCadence(instant=True, poll_every=SCHEDULED_EVERY)
"""Every User's cadence while Plans are off (ADR 0028)."""
```

`src/calendar_sync/domain/watches.py`:

```python
"""Instant Sync's Calendar Watches and Watch Registrations: values and decisions, no I/O.

A Calendar Watch is what one Connected Account's provider is asked to report changes to, for one
Watch Scope. Each Watch Registration is one channel or subscription the provider holds for it.
Writers move a registration between states only from a named state, so a late writer changes
nothing (ADR 0036).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId

CREATION_DEADLINE = timedelta(minutes=10)
"""How long a registration may stay `creating` before upkeep counts its answer lost."""
CONFIRMATION_DEADLINE = timedelta(minutes=2)
"""How soon a provider that reaches the installation confirms a new registration."""
LONGEST_REGISTRATION = timedelta(days=7)
"""How long upkeep asks a provider to keep a registration; a provider may keep it for less."""
MAX_BACKOFF = timedelta(days=1)
"""The longest a watch waits after failures before upkeep calls its provider again."""

_FIRST_BACKOFF = timedelta(minutes=1)
# Doublings after which the first backoff already exceeds the longest, so a long run of failures
# never computes an interval too large to represent.
_LAST_DOUBLING = 11
_ACCOUNT_SCOPE = "account"
_CALENDAR_PREFIX = "calendar:"


def _require_non_empty(value: str, label: str) -> None:
    if not value or value.isspace():
        raise DomainValidationError(f"{label} must not be empty")


@dataclass(frozen=True, slots=True)
class CalendarWatchId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "calendar watch id")


@dataclass(frozen=True, slots=True)
class WatchRegistrationId:
    """Names a registration in the address its provider delivers notices to.

    Upkeep generates 32 lowercase hex characters, so the address reveals nothing else.
    """

    value: str

    def __post_init__(self) -> None:
        _require_non_empty(self.value, "watch registration id")


@dataclass(frozen=True, slots=True)
class WatchScope:
    """What one watch covers, as its provider's adapter decides: one calendar, or an account."""

    key: str
    """`account`, or `calendar:` followed by the calendar's id; stored, so the form never
    changes."""

    def __post_init__(self) -> None:
        if self.key == _ACCOUNT_SCOPE:
            return
        if not self.key.startswith(_CALENDAR_PREFIX):
            raise DomainValidationError("a watch scope covers an account or one calendar")
        _require_non_empty(self.key.removeprefix(_CALENDAR_PREFIX), "watched calendar id")

    @classmethod
    def account(cls) -> WatchScope:
        """Every calendar of the Connected Account, as one subscription watches a mailbox."""
        return cls(_ACCOUNT_SCOPE)

    @classmethod
    def calendar(cls, calendar_id: CalendarId) -> WatchScope:
        """One calendar, as one channel watches it."""
        return cls(_CALENDAR_PREFIX + calendar_id.value)

    @property
    def calendar_id(self) -> CalendarId | None:
        """The calendar a calendar scope covers; None for a whole account."""
        if self.key == _ACCOUNT_SCOPE:
            return None
        return CalendarId(self.key.removeprefix(_CALENDAR_PREFIX))


class RegistrationState(StrEnum):
    """Where a registration is in its life; stored, so values never change."""

    CREATING = "creating"
    """Persisted before its provider was asked for it; the answer is not recorded yet."""
    LIVE = "live"
    """The provider holds it, and it is the watch's current registration."""
    RETIRING = "retiring"
    """Replaced or removed; its notices still count until it is stopped or expires."""
    ABANDONED = "abandoned"
    """Its answer was lost or its stop failed; its notices are recognized and ignored until it
    would expire."""


@dataclass(frozen=True, slots=True)
class WatchRegistration:
    """One channel or subscription a provider holds for a watch.

    Only a hash of its secret token is kept. The provider's handle is opaque outside its adapter.
    """

    id: WatchRegistrationId
    watch_id: CalendarWatchId
    state: RegistrationState
    address: str
    """The full notice address it points at, which names its id."""
    token_hash: str
    created_at: datetime
    requested_until: datetime
    """When upkeep asked the provider to end it."""
    handle: str | None = None
    """The provider's identifiers for it; None until the provider answered."""
    expires_at: datetime | None = None
    """When the provider said it ends; None until the provider answered."""
    confirmed_at: datetime | None = None
    """When the provider first proved it reaches the installation through it."""
    renew_at: datetime | None = None
    """When upkeep renews it, fixed with jitter once its expiry is known."""
    renew_requested_at: datetime | None = None
    """When its provider asked for it to be renewed early."""

    def usable(self, now: datetime, address: str) -> bool:
        """Whether it is live, unexpired, and points at `address`."""
        return (
            self.state is RegistrationState.LIVE
            and self.address == address
            and self.expires_at is not None
            and self.expires_at > now
        )

    def delivering(self, now: datetime) -> bool:
        """Whether notices arrive through it: live, unexpired, and confirmed."""
        return (
            self.state is RegistrationState.LIVE
            and self.confirmed_at is not None
            and self.expires_at is not None
            and self.expires_at > now
        )

    def creation_stale(self, now: datetime) -> bool:
        """Whether it was persisted so long ago that its provider's answer is lost."""
        return self.state is RegistrationState.CREATING and now - self.created_at >= (
            CREATION_DEADLINE
        )

    def confirmation_overdue(self, now: datetime) -> bool:
        """Whether its provider has not confirmed it within the deadline after creation."""
        return (
            self.state is RegistrationState.LIVE
            and self.confirmed_at is None
            and now - self.created_at >= CONFIRMATION_DEADLINE
        )

    def renewal_due(self, now: datetime) -> bool:
        """Whether upkeep renews it now: its renewal time passed, or its provider asked."""
        return self.state is RegistrationState.LIVE and (
            self.renew_requested_at is not None
            or (self.renew_at is not None and self.renew_at <= now)
        )

    def gone(self, now: datetime) -> bool:
        """Whether its provider no longer keeps it, so its row can be deleted.

        A registration being created is never gone: its row turns abandoned first, so its notices
        stay recognized until it would have expired.
        """
        if self.state is RegistrationState.CREATING:
            return False
        return (self.expires_at or self.requested_until) <= now


@dataclass(frozen=True, slots=True)
class CalendarWatch:
    """One Connected Account's watch for one Watch Scope, and the calendars it covers.

    Notices it receives wake only rules whose Source Calendar it covers.
    """

    id: CalendarWatchId
    account: ConnectedAccountId
    scope: WatchScope
    coverage: frozenset[CalendarId] = frozenset()
    """The Source Calendars its scope covers, as upkeep last found them watchable."""
    retry_at: datetime | None = None
    """Until when upkeep leaves it alone after failures; None when it may call now."""
    failures: int = 0
    """Consecutive failed provider calls, which set how long it waits."""

    def covers(self, calendar: CalendarEndpoint) -> bool:
        return (
            calendar.connected_account_id == self.account and calendar.calendar_id in self.coverage
        )

    def waiting(self, now: datetime) -> bool:
        """Whether it is still waiting out a backoff."""
        return self.retry_at is not None and self.retry_at > now


def renewal_time(created_at: datetime, expires_at: datetime, jitter: float) -> datetime:
    """When to renew a registration: a point in the last third of its lifetime.

    It starts at the last third and adds `jitter` times a sixth of the lifetime, so registrations
    made together are not all renewed together. Jitter is chosen once, in [0, 1).
    """
    if not 0 <= jitter < 1:
        raise DomainValidationError("renewal jitter must be at least 0 and below 1")
    lifetime = expires_at - created_at
    return created_at + lifetime * 2 / 3 + lifetime / 6 * jitter


def backoff(failures: int, retry_after: timedelta | None = None) -> timedelta:
    """How long a watch waits after `failures` consecutive failures.

    One minute after the first, doubling up to a day, and never less than the provider asked.
    """
    if failures < 1:
        raise DomainValidationError("backoff follows at least one failure")
    delay = min(MAX_BACKOFF, _FIRST_BACKOFF * (1 << min(failures - 1, _LAST_DOUBLING)))
    return delay if retry_after is None else max(delay, retry_after)


def token_hash(token: str) -> str:
    """The hash a registration keeps of its secret token, so the store never holds the token."""
    return hashlib.sha256(token.encode()).hexdigest()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_cadence.py tests/domain/test_watches.py -q`, then
`.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`,
`.venv/bin/lint-imports`
Expected: PASS, and every check clean

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain/cadence.py src/calendar_sync/domain/watches.py tests/domain/test_cadence.py tests/domain/test_watches.py
git commit -m "Add Sync Cadence, Calendar Watches, and the lifecycle of their registrations

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 2: Instant Sync availability and each rule's effective cadence

**Files:**
- Modify: `src/calendar_sync/domain/watches.py` (imports; append Delivery Evidence,
  availability, and effective cadence)
- Test: `tests/domain/test_instant_sync_availability.py`

**Interfaces:**
- Consumes: Task 1's `SyncCadence`, `CalendarWatch`, `WatchRegistration.delivering`;
  `calendar_sync.domain.accounts.ProviderKind`.
- Produces, in `calendar_sync.domain.watches`:
  - `DeliveryState` (`UNKNOWN`, `WORKING`, `FAILING`)
  - `DeliveryEvidence(provider, address, last_success_at=None, last_failure_at=None)` with the
    property `state -> DeliveryState` (failing only while the latest failure is newer than the
    latest success; a tie is working)
  - `Availability` (`ON`, `OFF_BY_USER`, `NOT_IN_PLAN`, `NO_PUBLIC_ADDRESS`, `NOT_REACHING`)
  - `AVAILABILITY_ANCHORS: Mapping[Availability, str]` (read-only; keys `NOT_IN_PLAN`,
    `NO_PUBLIC_ADDRESS`, `NOT_REACHING`; anchors `not-in-your-plan`, `no-public-https-address`,
    `providers-cannot-reach-the-installation`, which Part E's `docs/instant-sync.md` headings must
    produce)
  - `instant_sync_availability(*, address_is_https, cadence, wanted, delivery) -> Availability`
    (order: `NO_PUBLIC_ADDRESS`, `NOT_IN_PLAN`, `OFF_BY_USER`, `NOT_REACHING`, `ON`)
  - `CadenceReason` (`INSTANT`, `NOT_WATCHABLE`, `WAITING_FOR_PROVIDER`, `OFF_BY_USER`,
    `NOT_IN_PLAN`, `NO_PUBLIC_ADDRESS`, `NOT_REACHING`)
  - `effective_cadence(availability, watch, registrations, now) -> CadenceReason` (only
    registrations whose `watch_id` is `watch.id` count, so callers may pass all of a User's)

- [ ] **Step 1: Write the failing test**

`tests/domain/test_instant_sync_availability.py`:

```python
"""Whether a User's rules may sync instantly, and how each rule syncs now, decided from facts."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    AVAILABILITY_ANCHORS,
    LONGEST_REGISTRATION,
    Availability,
    CadenceReason,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    DeliveryState,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    effective_cadence,
    instant_sync_availability,
    token_hash,
)
from tests.helpers import NOW

ADDRESS = "https://ghost.example.test"
NO_INSTANT = SyncCadence(instant=False, poll_every=timedelta(minutes=5))
WORKING, FAILING, UNKNOWN = DeliveryState.WORKING, DeliveryState.FAILING, DeliveryState.UNKNOWN
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    ConnectedAccountId("personal-account"),
    WatchScope.calendar(CalendarId("personal-calendar")),
    coverage=frozenset({CalendarId("personal-calendar")}),
)
DELIVERING = WatchRegistration(
    id=WatchRegistrationId("registration-1"),
    watch_id=WATCH.id,
    state=RegistrationState.LIVE,
    address=f"{ADDRESS}/api/v1/watch-notices/example/registration-1",
    token_hash=token_hash("synthetic-token"),
    created_at=NOW,
    requested_until=NOW + LONGEST_REGISTRATION,
    handle="synthetic-handle",
    expires_at=NOW + timedelta(days=6),
    confirmed_at=NOW,
    renew_at=NOW + timedelta(days=4),
)


@pytest.mark.parametrize(
    ("success", "failure", "state"),
    [
        (None, None, DeliveryState.UNKNOWN),
        (NOW, None, DeliveryState.WORKING),
        (None, NOW, DeliveryState.FAILING),
        (NOW, NOW - timedelta(minutes=1), DeliveryState.WORKING),
        (NOW - timedelta(minutes=1), NOW, DeliveryState.FAILING),
        (NOW, NOW, DeliveryState.WORKING),
    ],
)
def test_delivery_fails_only_while_the_latest_failure_is_newer_than_the_latest_success(
    success: datetime | None, failure: datetime | None, state: DeliveryState
) -> None:
    evidence = DeliveryEvidence(ProviderKind.GOOGLE, ADDRESS, success, failure)

    assert evidence.state is state


@pytest.mark.parametrize(
    ("https", "cadence", "wanted", "delivery", "availability"),
    [
        (True, DEFAULT_CADENCE, True, (), Availability.ON),
        (True, DEFAULT_CADENCE, True, (WORKING, UNKNOWN), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING, WORKING), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING, UNKNOWN), Availability.ON),
        (True, DEFAULT_CADENCE, True, (FAILING,), Availability.NOT_REACHING),
        (True, DEFAULT_CADENCE, True, (FAILING, FAILING), Availability.NOT_REACHING),
        (True, DEFAULT_CADENCE, False, (FAILING,), Availability.OFF_BY_USER),
        (True, NO_INSTANT, False, (FAILING,), Availability.NOT_IN_PLAN),
        (False, NO_INSTANT, False, (FAILING,), Availability.NO_PUBLIC_ADDRESS),
        (False, DEFAULT_CADENCE, True, (), Availability.NO_PUBLIC_ADDRESS),
    ],
)
def test_availability_names_the_first_reason_that_stops_instant_sync(
    https: bool,
    cadence: SyncCadence,
    wanted: bool,
    delivery: tuple[DeliveryState, ...],
    availability: Availability,
) -> None:
    decided = instant_sync_availability(
        address_is_https=https, cadence=cadence, wanted=wanted, delivery=delivery
    )

    assert decided is availability


def test_every_reason_but_on_and_off_by_user_names_its_docs_section() -> None:
    assert set(AVAILABILITY_ANCHORS) == set(Availability) - {
        Availability.ON,
        Availability.OFF_BY_USER,
    }
    assert AVAILABILITY_ANCHORS[Availability.NO_PUBLIC_ADDRESS] == "no-public-https-address"
    assert AVAILABILITY_ANCHORS[Availability.NOT_IN_PLAN] == "not-in-your-plan"
    assert (
        AVAILABILITY_ANCHORS[Availability.NOT_REACHING] == "providers-cannot-reach-the-installation"
    )


@pytest.mark.parametrize(
    ("availability", "reason"),
    [
        (Availability.OFF_BY_USER, CadenceReason.OFF_BY_USER),
        (Availability.NOT_IN_PLAN, CadenceReason.NOT_IN_PLAN),
        (Availability.NO_PUBLIC_ADDRESS, CadenceReason.NO_PUBLIC_ADDRESS),
        (Availability.NOT_REACHING, CadenceReason.NOT_REACHING),
    ],
)
def test_a_rule_syncs_on_schedule_for_its_owners_reason_even_with_a_delivering_watch(
    availability: Availability, reason: CadenceReason
) -> None:
    assert effective_cadence(availability, WATCH, (DELIVERING,), NOW) is reason


def test_a_rule_whose_source_no_watch_covers_is_not_watchable() -> None:
    assert effective_cadence(Availability.ON, None, (), NOW) is CadenceReason.NOT_WATCHABLE


def test_a_rule_syncs_instantly_while_its_watch_has_a_delivering_registration() -> None:
    assert effective_cadence(Availability.ON, WATCH, (DELIVERING,), NOW) is CadenceReason.INSTANT


@pytest.mark.parametrize(
    "registrations",
    [
        (),
        (replace(DELIVERING, confirmed_at=None),),
        (replace(DELIVERING, state=RegistrationState.CREATING),),
        (replace(DELIVERING, state=RegistrationState.RETIRING),),
        (replace(DELIVERING, expires_at=NOW),),
        (replace(DELIVERING, watch_id=CalendarWatchId("another-watch")),),
    ],
)
def test_a_watch_without_a_delivering_registration_waits_for_its_provider(
    registrations: tuple[WatchRegistration, ...],
) -> None:
    reason = effective_cadence(Availability.ON, WATCH, registrations, NOW)

    assert reason is CadenceReason.WAITING_FOR_PROVIDER
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_instant_sync_availability.py -q`
Expected: FAIL (`ImportError: cannot import name 'AVAILABILITY_ANCHORS' from
'calendar_sync.domain.watches'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/domain/watches.py`, replace the import block:

```python
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId
```

with:

```python
import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SyncCadence
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId
```

Then append to the end of the module, after `token_hash`:

```python
class DeliveryState(StrEnum):
    """Whether a provider's notices reach the installation's public address."""

    UNKNOWN = "unknown"
    """No evidence yet for this address."""
    WORKING = "working"
    FAILING = "failing"


@dataclass(frozen=True, slots=True)
class DeliveryEvidence:
    """The latest proof that one provider's notices reach one public address, and the latest
    sign that they do not."""

    provider: ProviderKind
    address: str
    last_success_at: datetime | None = None
    """An authenticated notice, or a creation that itself proves delivery."""
    last_failure_at: datetime | None = None
    """A registration not confirmed in time, or a provider that could not reach the address."""

    @property
    def state(self) -> DeliveryState:
        """Failing when the latest failure is newer than the latest success."""
        if self.last_failure_at is not None and (
            self.last_success_at is None or self.last_failure_at > self.last_success_at
        ):
            return DeliveryState.FAILING
        if self.last_success_at is not None:
            return DeliveryState.WORKING
        return DeliveryState.UNKNOWN


class Availability(StrEnum):
    """Whether a User's rules may sync instantly, or the one reason they may not."""

    ON = "on"
    OFF_BY_USER = "off_by_user"
    NOT_IN_PLAN = "not_in_plan"
    NO_PUBLIC_ADDRESS = "no_public_address"
    NOT_REACHING = "not_reaching"


AVAILABILITY_ANCHORS: Mapping[Availability, str] = MappingProxyType(
    {
        Availability.NOT_IN_PLAN: "not-in-your-plan",
        Availability.NO_PUBLIC_ADDRESS: "no-public-https-address",
        Availability.NOT_REACHING: "providers-cannot-reach-the-installation",
    }
)
"""The section of docs/instant-sync.md that explains each reason only an administrator or a Plan
can change."""


def instant_sync_availability(
    *,
    address_is_https: bool,
    cadence: SyncCadence,
    wanted: bool,
    delivery: Collection[DeliveryState],
) -> Availability:
    """Whether a User's rules may sync instantly, with the first reason that stops them.

    `delivery` holds the Delivery State of each provider the User's watched sources use. Providers
    are known not to reach the installation only when at least one is used and every one used is
    failing; a User with no watchable source is on.
    """
    if not address_is_https:
        return Availability.NO_PUBLIC_ADDRESS
    if not cadence.instant:
        return Availability.NOT_IN_PLAN
    if not wanted:
        return Availability.OFF_BY_USER
    if delivery and all(state is DeliveryState.FAILING for state in delivery):
        return Availability.NOT_REACHING
    return Availability.ON


class CadenceReason(StrEnum):
    """How a rule syncs now: instantly, or on schedule for one reason."""

    INSTANT = "instant"
    NOT_WATCHABLE = "not_watchable"
    """Its Source Calendar's provider cannot watch it, such as a calendar shared from another
    mailbox."""
    WAITING_FOR_PROVIDER = "waiting_for_provider"
    """Its watch exists, but no registration has proved yet that notices arrive."""
    OFF_BY_USER = "off_by_user"
    NOT_IN_PLAN = "not_in_plan"
    NO_PUBLIC_ADDRESS = "no_public_address"
    NOT_REACHING = "not_reaching"


_AVAILABILITY_REASONS: Mapping[Availability, CadenceReason] = MappingProxyType(
    {
        Availability.OFF_BY_USER: CadenceReason.OFF_BY_USER,
        Availability.NOT_IN_PLAN: CadenceReason.NOT_IN_PLAN,
        Availability.NO_PUBLIC_ADDRESS: CadenceReason.NO_PUBLIC_ADDRESS,
        Availability.NOT_REACHING: CadenceReason.NOT_REACHING,
    }
)


def effective_cadence(
    availability: Availability,
    watch: CalendarWatch | None,
    registrations: Collection[WatchRegistration],
    now: datetime,
) -> CadenceReason:
    """How a rule syncs now, given its owner's availability and the watch covering its source.

    It syncs instantly only while one of that watch's registrations is delivering.
    """
    if availability is not Availability.ON:
        return _AVAILABILITY_REASONS[availability]
    if watch is None:
        return CadenceReason.NOT_WATCHABLE
    if any(
        registration.watch_id == watch.id and registration.delivering(now)
        for registration in registrations
    ):
        return CadenceReason.INSTANT
    return CadenceReason.WAITING_FOR_PROVIDER
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/domain -q`, then `.venv/bin/ruff format --check .`,
`.venv/bin/ruff check .`, `.venv/bin/mypy`, `.venv/bin/lint-imports`
Expected: PASS, and every check clean (`domain.watches` now imports `domain.accounts` and
`domain.cadence`, both inside `domain`)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain/watches.py tests/domain/test_instant_sync_availability.py
git commit -m "Decide whether a User may sync instantly, and how each rule syncs now

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 3: Ports and types of Instant Sync in the sync context

**Files:**
- Create: `src/calendar_sync/application/sync/watch_ports.py`
- Test: `tests/application/test_watch_ports.py`

**Interfaces:**
- Consumes: Tasks 1-2 (`CalendarWatch`, `CalendarWatchId`, `DeliveryEvidence`,
  `WatchRegistration`, `WatchRegistrationId`, `WatchScope`, `DEFAULT_CADENCE`, `SyncCadence`);
  `ApplicationError`; `ProviderFailure`; `UserId`; `ProviderKind`.
- Produces, in `calendar_sync.application.sync.watch_ports`, exactly the contract's names:
  `Receipt(handle, expires_at, confirmed=False)`, `WatchFailureKind`,
  `WatchFailure(kind, detail, retry_after_seconds=None, failure=None)` (an `ApplicationError`
  dataclass with `eq=False`; `str()` is `detail`), `CalendarWatcher`, `WatcherFor`,
  `NoticeRequest(headers, query, body)`, `NoticeKind`,
  `WatchNotice(registration_id, token, handle, kind)`, `MalformedNotice`, `NoticeReader`
  (`validation_token`, `read`), `CalendarWatchRepository` (semantics in each docstring; see
  deviation 6), `PendingRequest`, `InstantSyncRequestRepository`, `DeliveryEvidenceLog`
  (`succeeded` and `failed` keep the later time), `SyncCadencePolicy`, `EveryUserInstant`,
  `notice_address(public_address, provider_slug, registration_id) -> str`, and the new constant
  `NOTICE_PATH = "/api/v1/watch-notices"` (Part D's route prefix should import it).
  `CalendarWatcher` methods raise only `WatchFailure`; a Connected Account that no longer exists
  or is disconnected surfaces as `unsupported` (Part C's watchers translate
  `ConnectedAccountNotFound` and `ConnectedAccountDisconnected`).
- Does NOT change `UnitOfWork` in `application/sync/ports.py`. Adding `watches` and
  `instant_requests` there now would break mypy for `SqliteUnitOfWork` and the in-memory unit
  until they implement them. Task 6 adds both Protocol attributes together with their SQLite and
  in-memory implementations.

- [ ] **Step 1: Write the failing test**

`tests/application/test_watch_ports.py`:

```python
"""What the ports of Instant Sync decide on their own: notice addresses and the default cadence."""

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.cadence import DEFAULT_CADENCE
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import WatchRegistrationId
from tests.users import OTHER_USER, USER


def test_a_notice_address_names_the_provider_and_the_registration() -> None:
    address = notice_address(
        "https://ghost.example.test", "example", WatchRegistrationId("0123456789abcdef" * 2)
    )

    assert address == (
        "https://ghost.example.test/api/v1/watch-notices/example/0123456789abcdef0123456789abcdef"
    )


def test_with_plans_off_every_user_may_sync_instantly() -> None:
    policy = EveryUserInstant()

    assert policy.cadence(USER) == DEFAULT_CADENCE
    assert policy.cadence(OTHER_USER) == DEFAULT_CADENCE


def test_a_watch_failure_reads_as_its_detail_and_carries_the_refusal() -> None:
    refusal = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired")
    failure = WatchFailure(WatchFailureKind.UNAUTHORIZED, "refused", failure=refusal)

    assert str(failure) == "refused"
    assert failure.failure is refusal
    assert failure.retry_after_seconds is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/application/test_watch_ports.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.application.sync.watch_ports'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/application/sync/watch_ports.py`:

```python
"""Ports of Instant Sync: watching calendars, reading notices, and the records they keep.

A provider's descriptor offers its watcher and notice reader, and descriptors live in `sync`, so
everything they expose is declared here (ADR 0036). Nothing here carries event content.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SyncCadence
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId, SyncRuleId
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)

NOTICE_PATH = "/api/v1/watch-notices"
"""Where providers deliver notices, below the installation's public address."""


@dataclass(frozen=True, slots=True)
class Receipt:
    """A provider's answer to a registration it now holds."""

    handle: str
    """The provider's identifiers for it, opaque outside its adapter."""
    expires_at: datetime
    confirmed: bool = False
    """Whether creating it already proved the provider reaches the installation, as a provider
    that validates the address first does."""


class WatchFailureKind(StrEnum):
    """How a watch call failed, kept apart from the failures of Sync Runs."""

    UNAUTHORIZED = "unauthorized"
    """The provider refused the account's credentials, which lapses the account (ADR 0027)."""
    UNSUPPORTED = "unsupported"
    """The provider cannot watch this; it never lapses the account."""
    DUPLICATE = "duplicate"
    """The provider already holds a registration for the same scope."""
    UNREACHABLE = "unreachable"
    """The provider said it cannot reach the notice address."""
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    """No answer, or one a later attempt can change; the provider may have done what was asked."""


# Not frozen: raising an error sets its __traceback__, which a frozen dataclass refuses.
@dataclass(eq=False)
class WatchFailure(ApplicationError):
    kind: WatchFailureKind
    detail: str
    retry_after_seconds: int | None = None
    failure: ProviderFailure | None = None
    """For an unauthorized call, the refusal Lapsed Authorization records (ADR 0027)."""

    def __str__(self) -> str:
        return self.detail


class CalendarWatcher(Protocol):
    """Asks one provider to report changes, through channels or subscriptions it holds.

    Every method raises only WatchFailure. A Connected Account that no longer exists or is
    disconnected is `unsupported`, so upkeep backs off and never lapses it. The adapter never
    invents an identity during a call: the registration id and token come from upkeep, which
    persisted them first.
    """

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        """What a watch covering this calendar watches; None when it cannot be watched."""
        ...

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        """Ask the provider to deliver notices for `scope` to `address` until `until`."""
        ...

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        """Renew a registration in place; its new expiry, or None when the provider renews only
        by replacing it with a new registration."""
        ...

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        """After a duplicate, the provider's registration whose address names exactly this id;
        None when another one holds the scope. It never matches by scope alone and never deletes
        a registration it cannot identify."""
        ...

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None: ...


WatcherFor = Callable[[ConnectedAccountId], CalendarWatcher | None]
"""The watcher of a Connected Account's provider; None when its provider watches nothing."""


@dataclass(frozen=True, slots=True)
class NoticeRequest:
    """A notice as it arrived, without any web framework's types."""

    headers: Mapping[str, str]
    """Header names in lower case."""
    query: Mapping[str, str]
    body: bytes


class NoticeKind(StrEnum):
    STARTED = "started"
    """The provider began delivering through a new registration."""
    CHANGED = "changed"
    MISSED = "missed"
    """The provider dropped notices, so a run catches up."""
    REAUTHORIZE = "reauthorize"
    """The provider asks for the registration to be renewed early."""
    REMOVED = "removed"
    """The provider ended the registration itself."""


@dataclass(frozen=True, slots=True)
class WatchNotice:
    """One notice: the registration its address names, and what it presented and reports."""

    registration_id: WatchRegistrationId
    token: str
    handle: str | None
    """The provider's identifiers it presented, when it carries any."""
    kind: NoticeKind


class MalformedNotice(ApplicationError):
    """A request at a notice address that is not a notice its provider sends."""


class NoticeReader(Protocol):
    """Reads one provider's notices; it makes no provider call and keeps nothing."""

    def validation_token(self, request: NoticeRequest) -> str | None:
        """The token to echo when the provider is validating the address; None otherwise."""
        ...

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        """The notices in a request; raises MalformedNotice for anything else."""
        ...


class CalendarWatchRepository(Protocol):
    """One User's Calendar Watches and their registrations.

    Every state change is conditional on the state it leaves, so a late writer changes nothing.
    """

    def list(self) -> Sequence[CalendarWatch]: ...

    def registrations(self) -> Sequence[WatchRegistration]:
        """Every registration of every watch of the User."""
        ...

    def add(self, watch: CalendarWatch) -> None: ...

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None: ...

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None: ...

    def remove(self, watch_id: CalendarWatchId) -> None:
        """Delete the watch with its coverage and registrations."""
        ...

    def add_registration(self, registration: WatchRegistration) -> None: ...

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        """Make a `creating` registration live with the provider's answer; whether it was still
        being created.

        A confirming receipt sets `confirmed_at` to `at`; a confirmation a notice recorded first
        is kept.
        """
        ...

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        """Record a live registration's new expiry; whether it was still live.

        Its early renewal request is cleared only if it is still the one upkeep read, so a request
        that arrived during the renewal is not lost.
        """
        ...

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        """Make a live registration retiring; whether it was live."""
        ...

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        """Make a registration in any state abandoned; whether it exists."""
        ...

    def delete_registration(self, registration_id: WatchRegistrationId) -> None: ...


@dataclass(frozen=True, slots=True)
class PendingRequest:
    """A rule's Instant Sync Request: notices counted, and how many a run has handled."""

    rule_id: SyncRuleId
    requested_seq: int
    handled_seq: int
    first_requested_at: datetime
    """When `requested_seq` first rose above `handled_seq`."""
    last_requested_at: datetime
    last_run_at: datetime | None


class InstantSyncRequestRepository(Protocol):
    """One User's Instant Sync Requests."""

    def pending(self) -> Sequence[PendingRequest]:
        """Requests with notices no run has handled yet."""
        ...

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        """Mark notices up to `seq` handled by a run at `ran_at`, in one statement, so notices
        counted during the run stay pending."""
        ...


class DeliveryEvidenceLog(Protocol):
    """Whether each provider's notices reach a public address; installation data, no User's."""

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        """Record a success; an older time than the one recorded changes nothing."""
        ...

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        """Record a failure; an older time than the one recorded changes nothing, so recording
        one failure again is harmless."""
        ...

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]: ...


class SyncCadencePolicy(Protocol):
    """Each User's Sync Cadence, as their Plan allows (ADR 0028)."""

    def cadence(self, user: UserId) -> SyncCadence: ...


@dataclass(frozen=True, slots=True)
class EveryUserInstant:
    """The cadence policy while Plans are off: every User has every feature (ADR 0028)."""

    # The port names the User so Plans can tell Users apart; while they are off, none differ.
    def cadence(self, user: UserId) -> SyncCadence:  # noqa: ARG002
        return DEFAULT_CADENCE


def notice_address(
    public_address: str, provider_slug: str, registration_id: WatchRegistrationId
) -> str:
    """Where a provider delivers one registration's notices."""
    return f"{public_address}{NOTICE_PATH}/{provider_slug}/{registration_id.value}"
```

The `# noqa: ARG002` on `EveryUserInstant.cadence` follows the adapters' practice for a port
argument an implementation does not read; `tests/test_architecture.py` forbids only complexity
and argument-count suppressions.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/application/test_watch_ports.py tests/test_architecture.py -q`, then
`.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`,
`.venv/bin/lint-imports`
Expected: PASS, and every check clean (the module belongs to the `sync` context and imports only
`shared`, `sync`, and `domain`)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/sync/watch_ports.py tests/application/test_watch_ports.py
git commit -m "Declare the ports Instant Sync watches calendars and reads notices through

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 4: UpkeepWatches keeps one User's watches registered

**Files:**
- Modify: `src/calendar_sync/application/sync/resource_use.py` (`record_provider_calls` takes a
  narrow `CallCountingUnitOfWorkFactory`)
- Create: `src/calendar_sync/application/sync/instant_sync.py`
- Test: `tests/application/test_instant_sync_upkeep.py`

**Interfaces:**
- Consumes: Task 1 (`CalendarWatch`, `CalendarWatchId`, `RegistrationState`,
  `WatchRegistration`, `WatchRegistrationId`, `WatchScope`, `CONFIRMATION_DEADLINE`,
  `LONGEST_REGISTRATION`, `MAX_BACKOFF`, `backoff`, `renewal_time`, `token_hash`); Task 3
  (`CalendarWatcher`, `CalendarWatchRepository`, `DeliveryEvidenceLog`, `Receipt`, `WatcherFor`,
  `WatchFailure`, `WatchFailureKind`, `notice_address`); `Clock`; `ProviderFailure`;
  `ProviderCallStats`, `ProviderCallTally`, `ProviderCallRepository` from
  `application/sync/ports.py`; `record_provider_calls` from `application/sync/resource_use.py`;
  `SyncRule.synchronizes`. Watchers raise only `WatchFailure` (a missing or disconnected account
  is `unsupported`), so upkeep handles no other exception.
- Does not depend on Task 6. `UpkeepWatches` touches only `uow.watches`, `uow.rules.list()`,
  `uow.provider_calls` (through `record_provider_calls`), `uow.commit()`, and the unit's context
  manager, through the narrow `WatchUnitOfWorkFactory` protocol declared in this module. The
  tests use small in-test fakes of `CalendarWatchRepository`, `ProviderCallRepository`,
  `ProviderCallStats`, and that factory. They keep committed records apart from each unit's
  writes, fail any provider call made while a unit is open, and add each watcher call's cost to
  the measured tally as an adapter does.
- Produces, in `calendar_sync.application.sync.resource_use`:
  - `CallCountingUnitOfWork`, `CallCountingUnitOfWorkFactory` (protocols);
    `record_provider_calls(unit_of_work: CallCountingUnitOfWorkFactory, clock, calls)`
- Produces, in `calendar_sync.application.sync.instant_sync`:
  - `STOP_DEADLINE = timedelta(seconds=10)`, `UNWATCHABLE_RECHECK = timedelta(days=1)`
  - `CallBudget(remaining: int)` with `spend(calls: int) -> None` (may go below zero) and the
    property `exhausted` (`remaining <= 0`)
  - `AccountBackoff()` (no constructor arguments) with `waiting(account, now) -> bool`,
    `failed(account, at, retry_after: timedelta | None)`, `succeeded(account)`,
    `known_unwatchable(calendar: CalendarEndpoint, now) -> bool`, and
    `cannot_watch(calendar: CalendarEndpoint, at)`; process-local
  - `WatchProviders(watcher_for: WatcherFor, provider_of: Callable[[ConnectedAccountId],
    ProviderKind | None], slug_of: Callable[[ProviderKind], str],
    backoff: AccountBackoff = AccountBackoff())`; bootstrap shares one `AccountBackoff`
  - `FreshValues(new_token=secrets.token_urlsafe(32), new_id=uuid4().hex, jitter=random.random)`
    (callables)
  - `RuleListing`, `WatchUnitOfWork` (extends `CallCountingUnitOfWork`),
    `WatchUnitOfWorkFactory`, `AccountLapses` (protocols)
  - `UpkeepWatches(unit_of_work: WatchUnitOfWorkFactory, providers: WatchProviders,
    evidence: DeliveryEvidenceLog, clock: Clock, call_stats: ProviderCallStats,
    lapses: AccountLapses | None = None, fresh: FreshValues = FreshValues())` with
    `execute(*, allowed: bool, address: str | None, budget: CallBudget) -> None` and
    `stop_all(account: ConnectedAccountId | None = None, deadline: timedelta = STOP_DEADLINE)
    -> None`. `address` is the public base address (`https://host`); registrations point at
    `notice_address(address, slug_of(provider), registration_id)`, and Delivery Evidence is
    recorded against the base address.
- What `execute` does, in order (spec steps 1-7), inside `call_stats.measure()`:
  1. One transaction: reads enabled rules, deletes `gone` registrations, abandons stale
     `creating` ones. Commit.
  2. Discovery, when `allowed` and `address` is set: a Source Calendar an existing watch covers
     keeps that watch's scope, and one found unwatchable within the last day is skipped as
     resolved. For each other one, unless its account is backing off or the budget is exhausted,
     calls `scope()` and persists the result at once (adds the watch, or widens its coverage); a
     `None` scope is remembered for `UNWATCHABLE_RECHECK`. A failure marks the account unsure:
     `unauthorized` lapses it, others back it off in `AccountBackoff` (honoring Retry-After).
  3. One transaction: for accounts whose every source was resolved, narrows each watch's
     coverage to the enabled sources. Unsure or incomplete accounts keep their coverage.
  4. Each watch with coverage: stops and deletes `retiring` registrations and `live` ones at
     another address; without a usable registration and no `creating` one, and not waiting:
     persists a `creating` row, commits, then calls `register` outside any transaction; records
     the receipt with `renew_at = renewal_time(created_at, expires_at, jitter)`; on `duplicate`
     adopts once. A due registration is renewed with `extend`; `None` means replacement: the new
     registration is recorded (`retire` of the old one in the same transaction), then the old one
     is stopped and deleted (abandoned when the stop fails; left `retiring` for the next cycle
     when the budget cannot pay).
  5. Each watch without coverage, of an account whose discovery completed: stops (best effort)
     and deletes its `live` and `retiring` registrations, abandons those whose stop fails, and
     removes the watch once no registration is left.
  6. Failures: `unauthorized` goes to `lapses.lapsed(account, failure.failure,
     attempted_at=<call start>)`; others set `retry_at = now + backoff(failures + 1,
     retry_after)`; `unreachable` also records failing evidence; `Receipt.confirmed` records a
     success; an overdue confirmation records a failure at `created_at + CONFIRMATION_DEADLINE`.
  7. No watcher method starts once the budget is exhausted; each spends what the tally measured.
     A creation is never persisted once the budget is exhausted. The tally is recorded for the
     User in a `finally`.

- [ ] **Step 1: Write the failing test**

`tests/application/test_instant_sync_upkeep.py`:

```python
"""Upkeep keeps one User's Calendar Watches as their enabled rules need (ADR 0036).

The fakes keep committed records apart from each unit's own writes, as a store does, and the
watcher fails a test that calls it while a unit of work is open: no provider call may happen
inside a write transaction. Each watcher method adds its cost to the measured tally, as an
adapter adds each HTTP call, and the budget is spent by what the tally grew.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from itertools import count
from types import TracebackType
from typing import Self

import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.instant_sync import (
    CallBudget,
    FreshValues,
    UpkeepWatches,
    WatchProviders,
)
from calendar_sync.application.sync.ports import ProviderCallCounts, ProviderCallTally
from calendar_sync.application.sync.watch_ports import (
    Receipt,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    CREATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    renewal_time,
    token_hash,
)
from tests.helpers import NOW, endpoint

ADDRESS = "https://ghost.example.test"
MOVED = "https://moved.example.test"
PERSONAL = ConnectedAccountId("personal-account")
OTHER = ConnectedAccountId("other-account")
THIRD = ConnectedAccountId("third-account")
SOURCE = endpoint("personal-account", "personal-calendar")
SCOPE = WatchScope.calendar(CalendarId("personal-calendar"))
LIFETIME = timedelta(days=6)
JITTER = 0.5
EXPIRED = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=PERSONAL)


def source_rule(
    source: CalendarEndpoint = SOURCE,
    rule_id: str = "rule-1",
    state: SyncRuleState = SyncRuleState.ENABLED,
) -> SyncRule:
    return SyncRule(
        id=SyncRuleId(rule_id),
        source=source,
        destination=endpoint("work-account", "work-calendar"),
        state=state,
    )


@dataclass
class Records:
    watches: dict[CalendarWatchId, CalendarWatch] = field(default_factory=dict)
    registrations: dict[WatchRegistrationId, WatchRegistration] = field(default_factory=dict)

    def copy(self) -> Records:
        return Records(dict(self.watches), dict(self.registrations))


class Watches:
    """A CalendarWatchRepository over one unit's records, with the store's conditional writes."""

    def __init__(self, records: Records) -> None:
        self.records = records

    def list(self) -> Sequence[CalendarWatch]:
        return tuple(self.records.watches.values())

    def registrations(self) -> Sequence[WatchRegistration]:
        return tuple(self.records.registrations.values())

    def add(self, watch: CalendarWatch) -> None:
        self.records.watches[watch.id] = watch

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        watch = self.records.watches[watch_id]
        self.records.watches[watch_id] = replace(watch, coverage=coverage)

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        watch = self.records.watches[watch_id]
        self.records.watches[watch_id] = replace(watch, retry_at=retry_at, failures=failures)

    def remove(self, watch_id: CalendarWatchId) -> None:
        del self.records.watches[watch_id]
        for registration in self.registrations():
            if registration.watch_id == watch_id:
                del self.records.registrations[registration.id]

    def add_registration(self, registration: WatchRegistration) -> None:
        self.records.registrations[registration.id] = registration

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or current.state is not RegistrationState.CREATING:
            return False
        confirmed_at = current.confirmed_at or (at if receipt.confirmed else None)
        self.records.registrations[registration_id] = replace(
            current,
            state=RegistrationState.LIVE,
            handle=receipt.handle,
            expires_at=receipt.expires_at,
            confirmed_at=confirmed_at,
            renew_at=renew_at,
        )
        return True

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or current.state is not RegistrationState.LIVE:
            return False
        request = None if current.renew_requested_at == seen_request else current.renew_requested_at
        self.records.registrations[registration_id] = replace(
            current, expires_at=expires_at, renew_at=renew_at, renew_requested_at=request
        )
        return True

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.LIVE, RegistrationState.RETIRING)

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, None, RegistrationState.ABANDONED)

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self.records.registrations.pop(registration_id, None)

    def _move(
        self,
        registration_id: WatchRegistrationId,
        source: RegistrationState | None,
        target: RegistrationState,
    ) -> bool:
        current = self.records.registrations.get(registration_id)
        if current is None or source not in (None, current.state):
            return False
        self.records.registrations[registration_id] = replace(current, state=target)
        return True


@dataclass
class Rules:
    rules: list[SyncRule]

    def list(self) -> Sequence[SyncRule]:
        return tuple(self.rules)


@dataclass
class ProviderCalls:
    counted: list[tuple[date, ProviderKind, int]] = field(default_factory=list)

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        self.counted.append((day, provider, counts.calls))


@dataclass
class Units:
    """One User's units of work: each works on a copy of the committed records."""

    rules: list[SyncRule] = field(default_factory=lambda: [source_rule()])
    committed: Records = field(default_factory=Records)
    provider_calls: ProviderCalls = field(default_factory=ProviderCalls)
    open: int = 0

    def __call__(self) -> Unit:
        return Unit(self)


class Unit:
    def __init__(self, units: Units) -> None:
        self._units = units
        self._records = units.committed.copy()
        self.watches = Watches(self._records)
        self.rules = Rules(units.rules)
        self.provider_calls = units.provider_calls

    def __enter__(self) -> Self:
        self._units.open += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._units.open -= 1

    def commit(self) -> None:
        self._units.committed = self._records.copy()


@dataclass
class MovingClock:
    at: datetime = NOW

    def now(self) -> datetime:
        return self.at


Hook = Callable[[Records], None]


@dataclass
class FakeWatcher:
    """A provider that watches calendars; `during` hooks act while a call is in flight.

    Scoping is local, as Google's is, unless a test gives it a cost; every other call costs one.
    """

    units: Units
    clock: MovingClock
    costs: dict[str, int] = field(default_factory=lambda: {"scope": 0})
    tally: ProviderCallTally = field(default_factory=ProviderCallTally)
    scopes: dict[CalendarEndpoint, WatchScope | None] = field(default_factory=dict)
    refusals: dict[str, WatchFailure] = field(default_factory=dict)
    during: dict[str, Hook] = field(default_factory=dict)
    confirms: bool = False
    extends: bool = True
    """False for a provider that renews only by replacement."""
    adoptable: Receipt | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        self._call("scope", calendar.calendar_id.value)
        return self.scopes.get(calendar, WatchScope.calendar(calendar.calendar_id))

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        # Persisted and committed before the provider is asked, so no answer can be lost.
        persisted = self.units.committed.registrations[registration_id]
        assert persisted.state is RegistrationState.CREATING
        assert (persisted.token_hash, persisted.address) == (token_hash(token), address)
        assert until == persisted.requested_until
        self._call("register", registration_id.value)
        expires_at = self.clock.now() + LIFETIME
        return Receipt(f"handle-{registration_id.value}", expires_at, self.confirms)

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        self._call("extend", registration.id.value)
        return self.clock.now() + LIFETIME if self.extends else None

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        self._call("adopt", registration_id.value)
        return self.adoptable

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        self._call("stop", registration.id.value)

    def _call(self, operation: str, subject: str) -> None:
        assert self.units.open == 0, "a provider call inside a unit of work"
        self.calls.append((operation, subject))
        cost = self.costs.get(operation, 1)
        self.tally.calls += cost
        self.tally.providers.setdefault(ProviderKind.GOOGLE, ProviderCallCounts()).calls += cost
        if operation in self.during:
            self.during[operation](self.units.committed)
        if operation in self.refusals:
            raise self.refusals[operation]

    def operations(self) -> list[str]:
        return [operation for operation, _ in self.calls]


@dataclass
class CallStats:
    """Gives each run a fresh tally, which the watcher adds its calls to."""

    watcher: FakeWatcher | None = None

    def measure(self) -> AbstractContextManager[ProviderCallTally]:
        assert self.watcher is not None
        self.watcher.tally = ProviderCallTally()
        return nullcontext(self.watcher.tally)


@dataclass
class Evidence:
    successes: list[tuple[ProviderKind, str, datetime]] = field(default_factory=list)
    failures: list[tuple[ProviderKind, str, datetime]] = field(default_factory=list)

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        self.successes.append((provider, address, at))

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        self.failures.append((provider, address, at))

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]:
        return {}


@dataclass
class Lapses:
    recorded: list[tuple[ConnectedAccountId, ProviderFailure, datetime]] = field(
        default_factory=list
    )

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool:
        self.recorded.append((account_id, failure, attempted_at))
        return True


@dataclass
class World:
    clock: MovingClock
    units: Units
    watcher: FakeWatcher
    evidence: Evidence
    lapses: Lapses
    upkeep: UpkeepWatches

    def run(
        self, *, allowed: bool = True, address: str | None = ADDRESS, budget: int = 100
    ) -> CallBudget:
        calls = CallBudget(budget)
        self.upkeep.execute(allowed=allowed, address=address, budget=calls)
        return calls

    def watches(self) -> list[CalendarWatch]:
        return list(self.units.committed.watches.values())

    def registrations(self) -> list[WatchRegistration]:
        return list(self.units.committed.registrations.values())

    def registration(self) -> WatchRegistration:
        (registration,) = self.registrations()
        return registration


def world(*rules: SyncRule) -> World:
    clock = MovingClock()
    units = Units(rules=list(rules or (source_rule(),)))
    watcher = FakeWatcher(units, clock)
    evidence, lapses = Evidence(), Lapses()
    call_stats = CallStats(watcher)
    ids = count(1)
    upkeep = UpkeepWatches(
        units,
        WatchProviders(
            watcher_for=lambda _account: watcher,
            provider_of=lambda _account: ProviderKind.GOOGLE,
            slug_of=lambda _provider: "example",
        ),
        evidence,
        clock,
        call_stats,
        lapses,
        FreshValues(
            new_token=lambda: f"token-{next(ids)}",
            new_id=lambda: f"{next(ids):032x}",
            jitter=lambda: JITTER,
        ),
    )
    return World(clock, units, watcher, evidence, lapses, upkeep)


def seeded(registration_state: RegistrationState, *, created_at: datetime = NOW) -> World:
    """A world whose watch already holds one registration in `registration_state`."""
    scenario = world()
    watch = CalendarWatch(
        CalendarWatchId("watch-1"), PERSONAL, SCOPE, frozenset({CalendarId("personal-calendar")})
    )
    registration_id = WatchRegistrationId("0" * 31 + "a")
    live = registration_state is not RegistrationState.CREATING
    registration = WatchRegistration(
        id=registration_id,
        watch_id=watch.id,
        state=registration_state,
        address=notice_address(ADDRESS, "example", registration_id),
        token_hash=token_hash("seeded-token"),
        created_at=created_at,
        requested_until=created_at + LONGEST_REGISTRATION,
        handle="seeded-handle" if live else None,
        expires_at=created_at + LIFETIME if live else None,
        confirmed_at=created_at if live else None,
        renew_at=renewal_time(created_at, created_at + LIFETIME, JITTER) if live else None,
    )
    scenario.units.committed = Records({watch.id: watch}, {registration.id: registration})
    return scenario


def refusal(kind: WatchFailureKind, retry_after_seconds: int | None = None) -> WatchFailure:
    return WatchFailure(kind, "refused", retry_after_seconds=retry_after_seconds)


def test_upkeep_registers_a_watch_for_an_enabled_rules_source_after_persisting_it() -> None:
    scenario = world()

    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.account, watch.scope, watch.coverage) == (
        PERSONAL,
        SCOPE,
        frozenset({CalendarId("personal-calendar")}),
    )
    registration = scenario.registration()
    assert registration.state is RegistrationState.LIVE
    assert registration.address == notice_address(ADDRESS, "example", registration.id)
    assert registration.handle == f"handle-{registration.id.value}"
    assert registration.expires_at == NOW + LIFETIME
    assert registration.renew_at == renewal_time(NOW, NOW + LIFETIME, JITTER)
    assert registration.confirmed_at is None
    # Only the Source Calendar is watched.
    assert scenario.watcher.calls == [
        ("scope", "personal-calendar"),
        ("register", registration.id.value),
    ]


def test_a_second_run_with_everything_in_place_registers_nothing() -> None:
    scenario = world()
    scenario.run()

    scenario.run()

    # The covered source keeps its watch's scope, so the provider is not asked again.
    assert scenario.watcher.operations() == ["scope", "register"]


def test_one_account_scope_covers_every_watchable_calendar_and_skips_a_shared_one() -> None:
    other = endpoint("personal-account", "other-calendar")
    shared = endpoint("personal-account", "shared-calendar")
    scenario = world(source_rule(), source_rule(other, "rule-2"), source_rule(shared, "rule-3"))
    scenario.watcher.scopes = {
        SOURCE: WatchScope.account(),
        other: WatchScope.account(),
        shared: None,
    }

    scenario.run()

    (watch,) = scenario.watches()
    assert watch.scope == WatchScope.account()
    assert watch.coverage == {CalendarId("personal-calendar"), CalendarId("other-calendar")}
    assert scenario.watcher.operations().count("register") == 1


@pytest.mark.parametrize(
    ("allowed", "address", "state"),
    [
        (False, ADDRESS, SyncRuleState.ENABLED),
        (True, None, SyncRuleState.ENABLED),
        (True, ADDRESS, SyncRuleState.PAUSED),
    ],
)
def test_a_watch_no_rule_needs_is_stopped_and_removed(
    allowed: bool, address: str | None, state: SyncRuleState
) -> None:
    scenario = world()
    scenario.run()
    registration = scenario.registration()
    scenario.units.rules = [source_rule(state=state)]

    scenario.run(allowed=allowed, address=address)

    assert scenario.watcher.calls[-1] == ("stop", registration.id.value)
    assert scenario.watches() == []
    assert scenario.registrations() == []


def test_a_registration_whose_stop_fails_is_abandoned_until_it_expires() -> None:
    scenario = world()
    scenario.run()
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run(allowed=False)

    assert scenario.registration().state is RegistrationState.ABANDONED
    (watch,) = scenario.watches()
    assert watch.coverage == frozenset()
    scenario.clock.at = NOW + LIFETIME
    scenario.run(allowed=False)
    assert scenario.registrations() == []
    assert scenario.watches() == []


def test_a_changed_public_address_replaces_the_registration() -> None:
    scenario = world()
    scenario.run()
    old = scenario.registration()

    scenario.run(address=MOVED)

    new = scenario.registration()
    assert new.address == notice_address(MOVED, "example", new.id)
    assert ("stop", old.id.value) in scenario.watcher.calls


def test_a_lost_creation_is_abandoned_and_a_new_registration_made() -> None:
    scenario = seeded(RegistrationState.CREATING, created_at=NOW - CREATION_DEADLINE)

    scenario.run()

    states = sorted(registration.state for registration in scenario.registrations())
    assert states == [RegistrationState.ABANDONED, RegistrationState.LIVE]


def test_a_creation_still_in_progress_is_left_alone() -> None:
    scenario = seeded(RegistrationState.CREATING, created_at=NOW - timedelta(minutes=1))

    scenario.run()

    assert scenario.registration().state is RegistrationState.CREATING
    assert "register" not in scenario.watcher.operations()


def test_a_late_receipt_for_a_registration_abandoned_meanwhile_changes_nothing() -> None:
    def abandon_creations(records: Records) -> None:
        for registration in list(records.registrations.values()):
            abandoned = replace(registration, state=RegistrationState.ABANDONED)
            records.registrations[registration.id] = abandoned

    scenario = world()
    scenario.watcher.during["register"] = abandon_creations

    scenario.run()

    registration = scenario.registration()
    assert (registration.state, registration.handle) == (RegistrationState.ABANDONED, None)


def test_a_late_receipt_for_a_registration_deleted_meanwhile_brings_nothing_back() -> None:
    scenario = world()
    scenario.watcher.during["register"] = lambda records: records.registrations.clear()

    scenario.run()

    assert scenario.registrations() == []


def test_a_start_notice_that_arrives_before_register_returns_is_kept() -> None:
    def confirm(records: Records) -> None:
        for registration in list(records.registrations.values()):
            records.registrations[registration.id] = replace(registration, confirmed_at=NOW)

    scenario = world()
    scenario.watcher.during["register"] = confirm

    scenario.run()

    assert scenario.registration().confirmed_at == NOW


def test_a_receipt_that_proves_delivery_confirms_and_records_success() -> None:
    scenario = world()
    scenario.watcher.confirms = True

    scenario.run()

    assert scenario.registration().confirmed_at == NOW
    assert scenario.evidence.successes == [(ProviderKind.GOOGLE, ADDRESS, NOW)]


def test_an_unconfirmed_registration_records_the_same_failure_at_its_deadline() -> None:
    scenario = world()
    scenario.run()

    scenario.clock.at = NOW + CONFIRMATION_DEADLINE
    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=7)
    scenario.run()

    deadline = (ProviderKind.GOOGLE, ADDRESS, NOW + CONFIRMATION_DEADLINE)
    assert scenario.evidence.failures == [deadline, deadline]


def test_a_duplicate_adopts_the_providers_registration_that_names_this_id() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.DUPLICATE)
    scenario.watcher.adoptable = Receipt("adopted-handle", NOW + LIFETIME, confirmed=True)

    scenario.run()

    registration = scenario.registration()
    assert (registration.state, registration.handle) == (RegistrationState.LIVE, "adopted-handle")
    assert ("adopt", registration.id.value) in scenario.watcher.calls


def test_a_duplicate_held_by_another_registration_is_never_touched_and_waits_a_day() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.DUPLICATE)

    scenario.run()

    assert scenario.registrations() == []
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + MAX_BACKOFF, 1)
    assert scenario.watcher.operations() == ["scope", "register", "adopt"]
    scenario.clock.at = NOW + timedelta(hours=1)
    scenario.run()
    assert "stop" not in scenario.watcher.operations()
    assert scenario.watcher.operations().count("register") == 1


def test_a_registration_due_for_renewal_is_extended_in_place() -> None:
    scenario = seeded(RegistrationState.LIVE)
    due = scenario.registration().renew_at
    assert due is not None
    scenario.clock.at = due

    scenario.run()

    registration = scenario.registration()
    assert registration.expires_at == due + LIFETIME
    assert registration.renew_at == renewal_time(due, due + LIFETIME, JITTER)
    assert scenario.watcher.operations() == ["extend"]


def test_an_early_renewal_request_is_cleared_once_honored() -> None:
    scenario = seeded(RegistrationState.LIVE)
    registration = scenario.registration()
    scenario.units.committed.registrations[registration.id] = replace(
        registration, renew_requested_at=NOW
    )

    scenario.run()

    assert scenario.registration().renew_requested_at is None


def test_an_early_renewal_request_that_arrives_during_renewal_is_not_lost() -> None:
    later = NOW + timedelta(seconds=30)

    def request_again(records: Records) -> None:
        for registration in list(records.registrations.values()):
            records.registrations[registration.id] = replace(registration, renew_requested_at=later)

    scenario = seeded(RegistrationState.LIVE)
    registration = scenario.registration()
    scenario.units.committed.registrations[registration.id] = replace(
        registration, renew_requested_at=NOW
    )
    scenario.watcher.during["extend"] = request_again

    scenario.run()

    assert scenario.registration().renew_requested_at == later


def test_a_replacement_is_recorded_before_the_registration_it_replaces_is_stopped() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False
    seen: dict[str, RegistrationState] = {}

    def at_register(records: Records) -> None:
        seen["register"] = records.registrations[old.id].state

    def at_stop(records: Records) -> None:
        seen["stop"] = records.registrations[old.id].state

    scenario.watcher.during = {"register": at_register, "stop": at_stop}

    scenario.run()

    # Notices on both count until the old one is stopped.
    assert seen == {"register": RegistrationState.LIVE, "stop": RegistrationState.RETIRING}
    new = scenario.registration()
    assert new.id != old.id
    assert new.state is RegistrationState.LIVE
    assert scenario.watcher.operations() == ["extend", "register", "stop"]


def test_a_replaced_registration_whose_stop_fails_is_abandoned() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run()

    states = {registration.id: registration.state for registration in scenario.registrations()}
    assert states.pop(old.id) is RegistrationState.ABANDONED
    assert list(states.values()) == [RegistrationState.LIVE]


def test_a_refusal_of_credentials_lapses_the_account_as_of_the_calls_start() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = WatchFailure(
        WatchFailureKind.UNAUTHORIZED, "refused", failure=EXPIRED
    )

    def slow(records: Records) -> None:
        scenario.clock.at = NOW + timedelta(seconds=5)

    scenario.watcher.during["register"] = slow

    scenario.run()

    assert scenario.lapses.recorded == [(PERSONAL, EXPIRED, NOW)]
    assert scenario.registrations() == []
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (None, 0)


def test_a_provider_that_cannot_watch_a_calendar_backs_off_and_never_lapses_the_account() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNSUPPORTED)

    scenario.run()
    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + timedelta(minutes=1), 1)
    scenario.run()
    assert scenario.watcher.operations().count("register") == 1
    scenario.clock.at = NOW + timedelta(minutes=1)
    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (NOW + timedelta(minutes=3), 2)
    assert scenario.lapses.recorded == []
    assert scenario.registrations() == []


def test_a_rate_limit_waits_at_least_as_long_as_the_provider_asks() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.RATE_LIMITED, 600)

    scenario.run()

    (watch,) = scenario.watches()
    assert watch.retry_at == NOW + timedelta(minutes=10)


def test_an_unreachable_address_records_failing_delivery() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNREACHABLE)

    scenario.run()

    assert scenario.evidence.failures == [(ProviderKind.GOOGLE, ADDRESS, NOW)]
    (watch,) = scenario.watches()
    assert watch.failures == 1


def test_a_temporary_failure_keeps_a_registration_the_provider_may_have_made() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.run()

    assert scenario.registration().state is RegistrationState.ABANDONED


def test_a_success_after_failures_clears_the_backoff() -> None:
    scenario = world()
    scenario.watcher.refusals["register"] = refusal(WatchFailureKind.UNSUPPORTED)
    scenario.run()
    del scenario.watcher.refusals["register"]
    scenario.clock.at = NOW + timedelta(minutes=1)

    scenario.run()

    (watch,) = scenario.watches()
    assert (watch.retry_at, watch.failures) == (None, 0)
    assert scenario.registration().state is RegistrationState.LIVE


def test_an_account_whose_scope_is_refused_keeps_its_watches_and_lapses() -> None:
    scenario = seeded(RegistrationState.LIVE)
    # The seeded watch's rule is gone; the new rule's source has no watch yet.
    scenario.units.rules = [source_rule(endpoint("personal-account", "other-calendar"))]
    scenario.watcher.refusals["scope"] = WatchFailure(
        WatchFailureKind.UNAUTHORIZED, "refused", failure=EXPIRED
    )

    scenario.run()

    assert scenario.lapses.recorded == [(PERSONAL, EXPIRED, NOW)]
    assert scenario.registration().state is RegistrationState.LIVE
    (watch,) = scenario.watches()
    assert watch.coverage == {CalendarId("personal-calendar")}
    assert scenario.watcher.operations() == ["scope"]


def test_an_account_whose_sources_are_not_all_scoped_keeps_its_watches() -> None:
    scenario = seeded(RegistrationState.LIVE)
    scenario.units.rules = [source_rule(endpoint("personal-account", "other-calendar"))]
    scenario.watcher.costs["scope"] = 1
    before = scenario.units.committed.copy()

    scenario.run(budget=0)

    assert scenario.watcher.calls == []
    assert scenario.units.committed == before
    scenario.run(budget=10)
    (watch,) = scenario.watches()
    assert watch.coverage == {CalendarId("other-calendar")}
    assert scenario.watcher.operations() == ["scope", "stop", "register"]


def test_a_large_user_makes_progress_across_cycles_when_scoping_is_free() -> None:
    sources = [endpoint("personal-account", f"calendar-{n}") for n in range(250)]
    scenario = world(*(source_rule(source, f"rule-{n}") for n, source in enumerate(sources)))

    first = scenario.run(budget=200)

    assert len(scenario.watches()) == 250
    assert len(scenario.registrations()) == 200
    assert first.exhausted
    scenario.run(budget=200)
    assert len(scenario.registrations()) == 250
    assert all(each.state is RegistrationState.LIVE for each in scenario.registrations())
    assert scenario.watcher.operations().count("scope") == 250


def test_scoping_that_costs_calls_is_kept_as_found_and_never_asked_again() -> None:
    sources = [endpoint("personal-account", f"calendar-{n}") for n in range(250)]
    scenario = world(*(source_rule(source, f"rule-{n}") for n, source in enumerate(sources)))
    scenario.watcher.costs["scope"] = 1

    scenario.run(budget=200)
    assert (len(scenario.watches()), len(scenario.registrations())) == (200, 0)
    scenario.run(budget=200)
    assert (len(scenario.watches()), len(scenario.registrations())) == (250, 150)
    scenario.run(budget=200)

    assert len(scenario.registrations()) == 250
    assert scenario.watcher.operations().count("scope") == 250


def test_a_calendar_that_cannot_be_watched_is_not_asked_again_for_a_day() -> None:
    shared = [endpoint("personal-account", f"shared-{n}") for n in range(250)]
    rules = [source_rule(source, f"rule-{n}") for n, source in enumerate(shared)]
    scenario = world(*rules, source_rule(SOURCE, "watchable"))
    scenario.watcher.costs["scope"] = 1
    scenario.watcher.scopes = dict.fromkeys(shared)

    scenario.run(budget=200)
    scenario.run(budget=200)

    assert scenario.registration().state is RegistrationState.LIVE
    asked = [subject for operation, subject in scenario.watcher.calls if operation == "scope"]
    assert len(asked) == len(set(asked)) == 251
    scenario.clock.at = NOW + timedelta(hours=23)
    scenario.run(budget=200)
    assert scenario.watcher.operations().count("scope") == 251
    scenario.clock.at = NOW + timedelta(days=1)
    scenario.run(budget=500)
    assert scenario.watcher.operations().count("scope") == 501


def test_upkeep_counts_its_measured_calls_for_the_user() -> None:
    scenario = world()

    budget = scenario.run(budget=5)

    assert budget.remaining == 4
    assert scenario.units.provider_calls.counted == [(NOW.date(), ProviderKind.GOOGLE, 1)]


def test_a_creation_the_budget_cannot_pay_for_persists_nothing() -> None:
    scenario = world()

    scenario.run(budget=0)

    assert scenario.watches() == []
    assert scenario.registrations() == []
    scenario.run(budget=1)
    assert scenario.registration().state is RegistrationState.LIVE


def test_a_spent_budget_may_go_below_zero_and_stays_exhausted() -> None:
    budget = CallBudget(2)

    budget.spend(1)
    assert not budget.exhausted
    budget.spend(3)

    assert (budget.remaining, budget.exhausted) == (-2, True)


def test_a_replaced_registration_the_budget_could_not_stop_is_stopped_next_cycle() -> None:
    scenario = seeded(RegistrationState.LIVE)
    old = scenario.registration()
    assert old.renew_at is not None
    scenario.clock.at = old.renew_at
    scenario.watcher.extends = False

    scenario.run(budget=2)

    states = {registration.id: registration.state for registration in scenario.registrations()}
    assert states.pop(old.id) is RegistrationState.RETIRING
    assert list(states.values()) == [RegistrationState.LIVE]
    scenario.run(budget=10)
    assert scenario.registration().id != old.id
    assert scenario.watcher.calls[-1] == ("stop", old.id.value)


def test_a_refused_scope_backs_off_as_long_as_the_provider_asks() -> None:
    scenario = world()
    scenario.watcher.refusals["scope"] = refusal(WatchFailureKind.RATE_LIMITED, 600)

    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=5)
    scenario.run()
    assert scenario.watcher.operations() == ["scope"]
    del scenario.watcher.refusals["scope"]
    scenario.clock.at = NOW + timedelta(minutes=10)
    scenario.run()

    assert scenario.watcher.operations() == ["scope", "scope", "register"]
    assert scenario.lapses.recorded == []


def test_a_scope_the_provider_cannot_give_backs_off_from_a_minute() -> None:
    scenario = world()
    scenario.watcher.refusals["scope"] = refusal(WatchFailureKind.UNSUPPORTED)

    scenario.run()
    scenario.clock.at = NOW + timedelta(seconds=59)
    scenario.run()
    scenario.clock.at = NOW + timedelta(minutes=1)
    scenario.run()

    assert scenario.watcher.operations() == ["scope", "scope"]


def test_stopping_one_accounts_watches_leaves_the_others() -> None:
    scenario = world(source_rule(), source_rule(endpoint("other-account", "other-calendar"), "r2"))
    scenario.run()
    scenario.watcher.refusals["stop"] = refusal(WatchFailureKind.TEMPORARY)

    scenario.upkeep.stop_all(PERSONAL)

    (watch,) = scenario.watches()
    assert watch.account == OTHER
    assert scenario.watcher.operations().count("stop") == 1
    scenario.upkeep.stop_all()
    assert scenario.watches() == []
    assert scenario.registrations() == []


def test_stopping_everything_gives_up_on_stops_at_the_deadline_and_removes_every_row() -> None:
    accounts = ("personal-account", "other-account", "third-account")
    scenario = world(*(source_rule(endpoint(account, "calendar"), account) for account in accounts))
    scenario.run()

    def slow(records: Records) -> None:
        scenario.clock.at += timedelta(seconds=6)

    scenario.watcher.during["stop"] = slow

    scenario.upkeep.stop_all(deadline=timedelta(seconds=10))

    assert scenario.watcher.operations().count("stop") == 2
    assert scenario.watches() == []
    assert scenario.registrations() == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/application/test_instant_sync_upkeep.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.application.sync.instant_sync'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/application/sync/resource_use.py`, replace the imports:

```python
import logging
from datetime import UTC, date, timedelta

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.ports import ProviderCallTally, UnitOfWorkFactory
```

with:

```python
import logging
from datetime import UTC, date, timedelta
from types import TracebackType
from typing import Protocol, Self

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.ports import ProviderCallRepository, ProviderCallTally
```

and replace the head of `record_provider_calls`:

```python
def record_provider_calls(
    unit_of_work: UnitOfWorkFactory, clock: Clock, calls: ProviderCallTally
) -> None:
```

with the two protocols and the narrowed signature (the body is unchanged):

```python
class CallCountingUnitOfWork(Protocol):
    """The part of a User's unit of work that counts their provider calls."""

    @property
    def provider_calls(self) -> ProviderCallRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class CallCountingUnitOfWorkFactory(Protocol):
    """Opens units of work for the one User whose provider calls are counted."""

    def __call__(self) -> CallCountingUnitOfWork: ...


def record_provider_calls(
    unit_of_work: CallCountingUnitOfWorkFactory, clock: Clock, calls: ProviderCallTally
) -> None:
```

`src/calendar_sync/application/sync/instant_sync.py`:

```python
"""Upkeep of one User's Calendar Watches, so their providers report changes (ADR 0036).

Upkeep makes the registrations providers hold match what the User's enabled rules need. A
registration is persisted before its provider is asked for it, and no provider call happens
inside a write transaction, so a crash or a lost answer leaves a row upkeep recognizes, never
one it does not know. Each state change is a conditional write, so a late writer changes nothing.

Every provider call spends the cycle's budget by what it measured, so a scope its adapter knows
without asking costs nothing, and a listing that pages costs each page. Progress is persisted as
it is made, so a cycle the budget ends early resumes where it stopped.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.ports import ProviderCallStats, ProviderCallTally
from calendar_sync.application.sync.resource_use import (
    CallCountingUnitOfWork,
    record_provider_calls,
)
from calendar_sync.application.sync.watch_ports import (
    CalendarWatcher,
    CalendarWatchRepository,
    DeliveryEvidenceLog,
    Receipt,
    WatcherFor,
    WatchFailure,
    WatchFailureKind,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId, SyncRule
from calendar_sync.domain.watches import (
    CONFIRMATION_DEADLINE,
    LONGEST_REGISTRATION,
    MAX_BACKOFF,
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    backoff,
    renewal_time,
    token_hash,
)

STOP_DEADLINE = timedelta(seconds=10)
"""How long User Deletion and account disconnection wait on stopping registrations."""
UNWATCHABLE_RECHECK = timedelta(days=1)
"""How long a Source Calendar its provider cannot watch goes without being asked again."""


class RuleListing(Protocol):
    def list(self) -> Sequence[SyncRule]: ...


class WatchUnitOfWork(CallCountingUnitOfWork, Protocol):
    """The part of one User's unit of work upkeep uses: their watches, their rules to read, and
    their provider call counts."""

    @property
    def watches(self) -> CalendarWatchRepository: ...

    @property
    def rules(self) -> RuleListing: ...


class WatchUnitOfWorkFactory(Protocol):
    """Opens units of work for the one User whose watches upkeep keeps (ADR 0029)."""

    def __call__(self) -> WatchUnitOfWork: ...


class AccountLapses(Protocol):
    """Records Lapsed Authorization, as `LapsedAuthorizations` does (ADR 0027)."""

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool: ...


@dataclass(slots=True)
class CallBudget:
    """How many provider calls an upkeep cycle may still make, across every User it keeps."""

    remaining: int

    def spend(self, calls: int) -> None:
        """Take the calls one provider method made; the last one may take it below zero."""
        self.remaining -= calls

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


@dataclass(slots=True)
class AccountBackoff:
    """When upkeep may ask a provider again what it can watch: an account after failures, and a
    calendar it cannot watch after a day.

    Kept in the process only: after a restart, everything is asked again at once. Each account
    belongs to one User, whose upkeep runs one at a time, so no two threads change one entry.
    """

    waits: dict[ConnectedAccountId, tuple[datetime, int]] = field(default_factory=dict, init=False)
    unwatchable: dict[CalendarEndpoint, datetime] = field(default_factory=dict, init=False)
    """Until when each calendar found unwatchable goes without being asked again."""

    def waiting(self, account: ConnectedAccountId, now: datetime) -> bool:
        wait = self.waits.get(account)
        return wait is not None and wait[0] > now

    def failed(
        self, account: ConnectedAccountId, at: datetime, retry_after: timedelta | None
    ) -> None:
        failures = self.waits.get(account, (at, 0))[1] + 1
        self.waits[account] = (at + backoff(failures, retry_after), failures)

    def succeeded(self, account: ConnectedAccountId) -> None:
        self.waits.pop(account, None)

    def known_unwatchable(self, calendar: CalendarEndpoint, now: datetime) -> bool:
        until = self.unwatchable.get(calendar)
        return until is not None and until > now

    def cannot_watch(self, calendar: CalendarEndpoint, at: datetime) -> None:
        self.unwatchable[calendar] = at + UNWATCHABLE_RECHECK


@dataclass(frozen=True, slots=True)
class WatchProviders:
    """How upkeep reaches the provider of each Connected Account."""

    watcher_for: WatcherFor
    provider_of: Callable[[ConnectedAccountId], ProviderKind | None]
    slug_of: Callable[[ProviderKind], str]
    """The provider's slug in notice addresses, from its descriptor."""
    backoff: AccountBackoff = field(default_factory=AccountBackoff)
    """Shared by every User's upkeep, so bootstrap passes one instance to all of them."""


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True, slots=True)
class FreshValues:
    """Where upkeep takes new secrets, identifiers, and renewal jitter."""

    new_token: Callable[[], str] = _new_token
    """A registration's secret token: 32 random bytes."""
    new_id: Callable[[], str] = _new_id
    """A watch's or registration's identifier: 32 lowercase hex characters."""
    jitter: Callable[[], float] = random.random
    """Where in its window a registration is renewed, in [0, 1); not a secret."""


@dataclass(slots=True)
class UpkeepWatches:
    """Keeps one User's Calendar Watches and their registrations as their enabled rules need."""

    unit_of_work: WatchUnitOfWorkFactory
    providers: WatchProviders
    evidence: DeliveryEvidenceLog
    clock: Clock
    call_stats: ProviderCallStats
    """Measures the provider calls upkeep makes, which spend the budget and count for the User."""
    lapses: AccountLapses | None = None
    fresh: FreshValues = field(default_factory=FreshValues)

    def execute(self, *, allowed: bool, address: str | None, budget: CallBudget) -> None:
        """Reconcile the User's watches with what their enabled rules need.

        Nothing is desired unless Instant Sync is `allowed` for the User and the installation has
        a public `address`. No provider call starts once the budget is exhausted; what it could
        not pay for waits for the next cycle, and an account whose sources were not all scoped
        keeps every watch it has.
        """
        with self.call_stats.measure() as calls:
            try:
                cycle = _Cycle(self, address, _Meter(budget, calls), self.clock.now())
                cycle.run(allowed)
            finally:
                record_provider_calls(self.unit_of_work, self.clock, calls)

    def stop_all(
        self, account: ConnectedAccountId | None = None, deadline: timedelta = STOP_DEADLINE
    ) -> None:
        """Stop the registrations of every watch, or of one account's, then remove the watches.

        Best effort, for User Deletion and account disconnection: no stop starts after
        `deadline`, and a registration left running, or whose stop failed, expires with its
        provider, its notices then finding no registration.
        """
        with self.call_stats.measure() as calls:
            try:
                self._stop_all(account, self.clock.now() + deadline)
            finally:
                record_provider_calls(self.unit_of_work, self.clock, calls)

    def _stop_all(self, account: ConnectedAccountId | None, until: datetime) -> None:
        now = self.clock.now()
        with self.unit_of_work() as uow:
            watches = tuple(
                watch for watch in uow.watches.list() if account is None or watch.account == account
            )
            registrations = tuple(uow.watches.registrations())
        running = [
            (watch, registration)
            for watch in watches
            for registration in registrations
            if registration.watch_id == watch.id
            and registration.handle is not None
            and not registration.gone(now)
        ]
        for watch, registration in running:
            if self.clock.now() >= until:
                break
            watcher = self.providers.watcher_for(watch.account)
            if watcher is not None:
                with suppress(WatchFailure):
                    watcher.stop(watch.account, registration)
        with self.unit_of_work() as uow:
            for watch in watches:
                uow.watches.remove(watch.id)
            uow.commit()


def _sources(rules: Sequence[SyncRule]) -> tuple[CalendarEndpoint, ...]:
    """The Source Calendars of enabled rules, each once: only sources are watched."""
    return tuple(dict.fromkeys(rule.source for rule in rules if rule.synchronizes))


def _retry_after(failure: WatchFailure) -> timedelta | None:
    seconds = failure.retry_after_seconds
    return None if seconds is None else timedelta(seconds=seconds)


def _lapse(
    lapses: AccountLapses | None,
    account: ConnectedAccountId,
    failure: WatchFailure,
    attempted_at: datetime,
) -> bool:
    """Lapse the account for a refusal of its credentials; whether the failure was one.

    The call's start decides, so a refusal of credentials since replaced lapses nothing.
    """
    if failure.kind is not WatchFailureKind.UNAUTHORIZED:
        return False
    if lapses is None or failure.failure is None:
        return False
    lapses.lapsed(account, failure.failure, attempted_at=attempted_at)
    return True


@dataclass(slots=True)
class _Meter:
    """The cycle's budget, spent by the provider calls each watcher method measured."""

    budget: CallBudget
    tally: ProviderCallTally

    @property
    def exhausted(self) -> bool:
        return self.budget.exhausted

    def paid[T](self, call: Callable[[], T]) -> T:
        before = self.tally.calls
        try:
            return call()
        finally:
            self.budget.spend(self.tally.calls - before)


@dataclass(frozen=True, slots=True)
class _Target:
    """A watch to keep, with its provider's watcher and the installation's public address."""

    watch: CalendarWatch
    watcher: CalendarWatcher
    provider: ProviderKind
    slug: str
    address: str

    def notice_address(self, registration_id: WatchRegistrationId) -> str:
        return notice_address(self.address, self.slug, registration_id)

    def current(
        self, registrations: Sequence[WatchRegistration], now: datetime
    ) -> WatchRegistration | None:
        """The live registration that points at the installation's address now."""
        return next(
            (each for each in registrations if each.usable(now, self.notice_address(each.id))),
            None,
        )


@dataclass(slots=True)
class _Cycle:
    """One upkeep run for one User: its time, public address, and metered call budget."""

    upkeep: UpkeepWatches
    address: str | None
    meter: _Meter
    now: datetime

    def run(self, allowed: bool) -> None:
        with self.upkeep.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
            _tidy_registrations(uow.watches, self.now)
            watches = tuple(uow.watches.list())
            uow.commit()
        sources = _sources(rules) if allowed and self.address is not None else ()
        unsure = self._discover(sources, watches)
        with self.upkeep.unit_of_work() as uow:
            _narrow_coverage(uow.watches, sources, unsure)
            watches = tuple(uow.watches.list())
            registrations = tuple(uow.watches.registrations())
            uow.commit()
        for watch in watches:
            owned = tuple(each for each in registrations if each.watch_id == watch.id)
            if watch.coverage:
                self._keep(watch, owned)
            elif watch.account not in unsure:
                self._retire(watch, owned)

    def _discover(
        self, sources: Sequence[CalendarEndpoint], watches: Iterable[CalendarWatch]
    ) -> frozenset[ConnectedAccountId]:
        """Scope each source no watch covers yet, keeping each one as it is found; the accounts
        whose sources were not all scoped.

        A covered source keeps its watch's scope without asking its provider again.
        """
        known = {(watch.account, watch.scope): watch for watch in watches}
        unsure: set[ConnectedAccountId] = set()
        for source in sources:
            account = source.connected_account_id
            if account in unsure or any(watch.covers(source) for watch in known.values()):
                continue
            scoped, scope = self._scope(source)
            if not scoped:
                unsure.add(account)
            elif scope is not None:
                self._cover(known, account, scope, source.calendar_id)
        return frozenset(unsure)

    def _scope(self, source: CalendarEndpoint) -> tuple[bool, WatchScope | None]:
        """Whether the source's provider said what watches it, and what does: None when nothing
        can, such as for a calendar shared from another mailbox."""
        account = source.connected_account_id
        providers = self.upkeep.providers
        watcher = providers.watcher_for(account)
        if watcher is None or providers.backoff.known_unwatchable(source, self.now):
            return True, None
        if self.meter.exhausted or providers.backoff.waiting(account, self.now):
            return False, None
        attempted_at = self.upkeep.clock.now()
        try:
            scope = self.meter.paid(lambda: watcher.scope(source))
        except WatchFailure as failure:
            if not _lapse(self.upkeep.lapses, account, failure, attempted_at):
                providers.backoff.failed(account, self.upkeep.clock.now(), _retry_after(failure))
            return False, None
        providers.backoff.succeeded(account)
        if scope is None:
            # Asked again only after a day, so such calendars never spend every cycle's budget.
            providers.backoff.cannot_watch(source, self.now)
        return True, scope

    def _cover(
        self,
        known: dict[tuple[ConnectedAccountId, WatchScope], CalendarWatch],
        account: ConnectedAccountId,
        scope: WatchScope,
        calendar: CalendarId,
    ) -> None:
        """Keep a calendar in the coverage of its watch at once, adding the watch if needed."""
        found = known.get((account, scope))
        with self.upkeep.unit_of_work() as uow:
            if found is None:
                watch_id = CalendarWatchId(self.upkeep.fresh.new_id())
                found = CalendarWatch(watch_id, account, scope, frozenset({calendar}))
                uow.watches.add(found)
            else:
                found = replace(found, coverage=found.coverage | {calendar})
                uow.watches.set_coverage(found.id, found.coverage)
            uow.commit()
        known[(account, scope)] = found

    def _keep(self, watch: CalendarWatch, owned: Sequence[WatchRegistration]) -> None:
        target = self._target(watch)
        if target is None:
            return
        current = target.current(owned, self.now)
        for registration in owned:
            if registration.state is RegistrationState.RETIRING or (
                registration.state is RegistrationState.LIVE and registration != current
            ):
                # Replaced, removed, or pointing at an address no longer the installation's.
                self._stop(target.watcher, watch, registration)
        if current is None:
            self._ensure(target, owned)
            return
        self._check_confirmation(target, current)
        if current.renewal_due(self.now) and not watch.waiting(self.now):
            self._renew(target, current)

    def _target(self, watch: CalendarWatch) -> _Target | None:
        providers = self.upkeep.providers
        watcher = providers.watcher_for(watch.account)
        provider = providers.provider_of(watch.account)
        if watcher is None or provider is None or self.address is None:
            return None
        return _Target(watch, watcher, provider, providers.slug_of(provider), self.address)

    def _ensure(self, target: _Target, owned: Sequence[WatchRegistration]) -> None:
        """Create a registration, unless one is being created or the watch waits out a backoff."""
        creating = any(each.state is RegistrationState.CREATING for each in owned)
        if not creating and not target.watch.waiting(self.now):
            self._create(target)

    def _create(self, target: _Target, replacing: WatchRegistration | None = None) -> None:
        if self.meter.exhausted:
            return
        token = self.upkeep.fresh.new_token()
        registration = self._persist(target, token)
        attempted_at = self.upkeep.clock.now()
        try:
            receipt: Receipt | None = self.meter.paid(
                lambda: target.watcher.register(
                    target.watch.account,
                    target.watch.scope,
                    registration.id,
                    token,
                    registration.address,
                    registration.requested_until,
                )
            )
        except WatchFailure as failure:
            receipt = self._refused(target, registration, failure, attempted_at)
        if receipt is not None:
            self._record(target, registration, receipt, replacing)

    def _persist(self, target: _Target, token: str) -> WatchRegistration:
        """Keep a new registration as being created, before its provider is asked for it."""
        created_at = self.upkeep.clock.now()
        registration_id = WatchRegistrationId(self.upkeep.fresh.new_id())
        registration = WatchRegistration(
            id=registration_id,
            watch_id=target.watch.id,
            state=RegistrationState.CREATING,
            address=target.notice_address(registration_id),
            token_hash=token_hash(token),
            created_at=created_at,
            requested_until=created_at + LONGEST_REGISTRATION,
        )
        with self.upkeep.unit_of_work() as uow:
            uow.watches.add_registration(registration)
            uow.commit()
        return registration

    def _refused(
        self,
        target: _Target,
        registration: WatchRegistration,
        failure: WatchFailure,
        attempted_at: datetime,
    ) -> Receipt | None:
        if failure.kind is WatchFailureKind.DUPLICATE:
            return self._adopt(target, registration)
        self._forget(registration, failure)
        self._failed(target, failure, attempted_at)
        return None

    def _adopt(self, target: _Target, registration: WatchRegistration) -> Receipt | None:
        """After a duplicate, take over the provider's registration only if it names this one's
        id, as one whose answer a retry lost does."""
        if self.meter.exhausted:
            return None
        attempted_at = self.upkeep.clock.now()
        try:
            receipt = self.meter.paid(
                lambda: target.watcher.adopt(
                    target.watch.account, target.watch.scope, registration.id, registration.address
                )
            )
        except WatchFailure as failure:
            self._forget(registration, failure)
            self._failed(target, failure, attempted_at)
            return None
        if receipt is None:
            # Another registration holds the scope, such as another User's of the same mailbox.
            # It is never touched; the scope is left to Scheduled Sync for a day.
            with self.upkeep.unit_of_work() as uow:
                uow.watches.delete_registration(registration.id)
                retry_at = self.upkeep.clock.now() + MAX_BACKOFF
                uow.watches.set_retry(target.watch.id, retry_at, target.watch.failures + 1)
                uow.commit()
        return receipt

    def _forget(self, registration: WatchRegistration, failure: WatchFailure) -> None:
        """Drop a registration its provider refused; keep one it may have made recognized."""
        with self.upkeep.unit_of_work() as uow:
            if failure.kind is WatchFailureKind.TEMPORARY:
                uow.watches.abandon(registration.id)
            else:
                uow.watches.delete_registration(registration.id)
            uow.commit()

    def _record(
        self,
        target: _Target,
        registration: WatchRegistration,
        receipt: Receipt,
        replacing: WatchRegistration | None,
    ) -> None:
        at = self.upkeep.clock.now()
        renew_at = renewal_time(registration.created_at, receipt.expires_at, self._jitter())
        with self.upkeep.unit_of_work() as uow:
            recorded = uow.watches.record_receipt(registration.id, receipt, renew_at, at)
            if recorded and replacing is not None:
                # Both count until the replaced one is stopped, in this cycle or a later one.
                uow.watches.retire(replacing.id)
            if recorded:
                _clear_backoff(uow.watches, target.watch)
            uow.commit()
        if receipt.confirmed:
            self.upkeep.evidence.succeeded(target.provider, target.address, at)
        if recorded and replacing is not None:
            self._stop(target.watcher, target.watch, replacing)

    def _renew(self, target: _Target, current: WatchRegistration) -> None:
        if self.meter.exhausted:
            return
        seen = current.renew_requested_at
        attempted_at = self.upkeep.clock.now()
        until = attempted_at + LONGEST_REGISTRATION
        try:
            expires_at = self.meter.paid(
                lambda: target.watcher.extend(target.watch.account, current, until)
            )
        except WatchFailure as failure:
            self._failed(target, failure, attempted_at)
            return
        if expires_at is None:
            # Its provider renews only by replacement: a new registration, recorded first.
            self._create(target, replacing=current)
            return
        renew_at = renewal_time(attempted_at, expires_at, self._jitter())
        with self.upkeep.unit_of_work() as uow:
            if uow.watches.record_extension(current.id, expires_at, renew_at, seen):
                _clear_backoff(uow.watches, target.watch)
            uow.commit()

    def _check_confirmation(self, target: _Target, current: WatchRegistration) -> None:
        if current.confirmation_overdue(self.now):
            # Recorded at the deadline, not now, so every later cycle records the same failure.
            at = current.created_at + CONFIRMATION_DEADLINE
            self.upkeep.evidence.failed(target.provider, target.address, at)

    def _retire(self, watch: CalendarWatch, owned: Sequence[WatchRegistration]) -> None:
        """Stop a watch no rule needs; it goes once no registration of it is left."""
        watcher = self.upkeep.providers.watcher_for(watch.account)
        for registration in owned:
            if registration.state in {RegistrationState.LIVE, RegistrationState.RETIRING}:
                self._stop(watcher, watch, registration)
        with self.upkeep.unit_of_work() as uow:
            if not any(each.watch_id == watch.id for each in uow.watches.registrations()):
                uow.watches.remove(watch.id)
            uow.commit()

    def _stop(
        self, watcher: CalendarWatcher | None, watch: CalendarWatch, registration: WatchRegistration
    ) -> None:
        """Stop a registration, best effort, then delete it.

        One whose stop fails is abandoned until it would expire, and one the budget cannot pay
        to stop yet keeps its state, so the next cycle stops it.
        """
        if watcher is not None:
            if self.meter.exhausted:
                return
            try:
                self.meter.paid(lambda: watcher.stop(watch.account, registration))
            except WatchFailure:
                with self.upkeep.unit_of_work() as uow:
                    uow.watches.abandon(registration.id)
                    uow.commit()
                return
        with self.upkeep.unit_of_work() as uow:
            uow.watches.delete_registration(registration.id)
            uow.commit()

    def _failed(self, target: _Target, failure: WatchFailure, attempted_at: datetime) -> None:
        """Lapse the account for a refusal of its credentials; back off for any other failure."""
        if _lapse(self.upkeep.lapses, target.watch.account, failure, attempted_at):
            return
        at = self.upkeep.clock.now()
        if failure.kind is WatchFailureKind.UNREACHABLE:
            self.upkeep.evidence.failed(target.provider, target.address, at)
        failures = target.watch.failures + 1
        retry_at = at + backoff(failures, _retry_after(failure))
        with self.upkeep.unit_of_work() as uow:
            uow.watches.set_retry(target.watch.id, retry_at, failures)
            uow.commit()

    def _jitter(self) -> float:
        return self.upkeep.fresh.jitter()


def _tidy_registrations(watches: CalendarWatchRepository, now: datetime) -> None:
    """Delete registrations their providers no longer keep, and abandon lost creations."""
    for registration in watches.registrations():
        if registration.gone(now):
            watches.delete_registration(registration.id)
        elif registration.creation_stale(now):
            # A crash or a lost answer: the provider may hold it, so its notices stay
            # recognized, and ignored, until it would have expired.
            watches.abandon(registration.id)


def _narrow_coverage(
    watches: CalendarWatchRepository,
    sources: Sequence[CalendarEndpoint],
    unsure: frozenset[ConnectedAccountId],
) -> None:
    """Drop from each watch the calendars no enabled rule has as its source any more.

    An account whose sources were not all scoped keeps its coverage as it is.
    """
    needed = {(source.connected_account_id, source.calendar_id) for source in sources}
    for watch in watches.list():
        if watch.account in unsure:
            continue
        coverage = frozenset(each for each in watch.coverage if (watch.account, each) in needed)
        if coverage != watch.coverage:
            # Its notices wake no rule for what it no longer covers.
            watches.set_coverage(watch.id, coverage)


def _clear_backoff(watches: CalendarWatchRepository, watch: CalendarWatch) -> None:
    if watch.failures or watch.retry_at is not None:
        watches.set_retry(watch.id, None, 0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/application/test_instant_sync_upkeep.py tests/application/test_resource_use.py tests/application/test_execute_sync_rule.py tests/application/test_remove_sync_rule.py tests/application/test_reconcile_sync_rule.py tests/test_architecture.py -q`,
then `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`,
`.venv/bin/lint-imports`
Expected: PASS, and every check clean. mypy confirms the existing callers of
`record_provider_calls` still type-check with the narrower parameter. `tests/test_architecture.py`
confirms no new wide dataclass (`UpkeepWatches` has seven constructor fields, `_Cycle` four,
`AccountBackoff` none) and no complexity `noqa`.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/sync/resource_use.py src/calendar_sync/application/sync/instant_sync.py tests/application/test_instant_sync_upkeep.py
git commit -m "Keep each User's Calendar Watches registered with their providers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 5: Migration 0031 for Instant Sync

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/0031_instant_sync.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/migrations.py` (register `(31, "0031_instant_sync.sql")`)
- Modify: `tests/adapters/test_user_isolation_schema.py` (`delivery_evidence` joins `INSTALLATION_TABLES`)
- Test: `tests/adapters/test_instant_sync_schema.py`

**Interfaces:**
- Consumes: the existing tables `users`, `connected_accounts` (with `UNIQUE (id, user_id)`), and `sync_rules` (with `UNIQUE (id, user_id)`)
- Produces:
  - Owned tables:
    - `calendar_watches(id, user_id, account_id, scope_key, retry_at, failures)`
    - `watch_coverage(watch_id, user_id, calendar_id)`
    - `watch_registrations(id, watch_id, user_id, state, address, token_hash, created_at, requested_until, handle, expires_at, confirmed_at, renew_at, renew_requested_at)`
    - `instant_sync_requests(rule_id, user_id, requested_seq, handled_seq, first_requested_at, last_requested_at, last_run_at)`
  - The column `users.instant_sync INTEGER NOT NULL DEFAULT 1`
  - The installation table `delivery_evidence(provider, address, last_success_at, last_failure_at)`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_instant_sync_schema.py`:

```python
"""Migration 31 keeps what Instant Sync needs: each User's watches and requests, which go with
their account, rule, and User, and the installation's Delivery Evidence."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.adapters.test_user_migration import database_at_version
from tests.helpers import NOW, rule
from tests.users import OTHER_USER, USER, add_account, add_user, sqlite_units

OWNED = ("calendar_watches", "watch_coverage", "watch_registrations", "instant_sync_requests")


def test_migration_31_lets_every_existing_user_want_instant_sync(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 30)
    add_user(database, USER)
    add_user(database, OTHER_USER, state="disabled")

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        wanted = connection.execute("SELECT id, instant_sync FROM users ORDER BY id").fetchall()
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert wanted == [(USER.value, 1), (OTHER_USER.value, 1)]
    assert {*OWNED, "delivery_evidence"} <= tables
    assert broken == []


def _watch_with_a_request(database: Path) -> None:
    """USER's watch of RULE's Source Calendar, a live registration, and RULE's request."""
    with sqlite_units(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO calendar_watches (id, user_id, account_id, scope_key)
            VALUES ('watch-1', ?, 'personal-account', 'calendar:personal-calendar')
            """,
            (USER.value,),
        )
        connection.execute(
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            VALUES ('watch-1', ?, 'personal-calendar')
            """,
            (USER.value,),
        )
        connection.execute(
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES (
                'registration-1', 'watch-1', ?, 'live',
                'https://calendar.example.test/api/v1/watch-notices/test/registration-1',
                'token-hash', ?, ?
            )
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO instant_sync_requests (
                rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                last_requested_at
            ) VALUES ('rule-1', ?, 1, 0, ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        )


def test_instant_sync_records_refer_through_their_user_and_go_with_them(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    _watch_with_a_request(database)
    add_account(database, "their-account", OTHER_USER)
    refused: tuple[tuple[str, tuple[str, ...]], ...] = (
        # Another User's watch of this User's account.
        (
            """
            INSERT INTO calendar_watches (id, user_id, account_id, scope_key)
            VALUES ('watch-2', ?, 'personal-account', 'account')
            """,
            (OTHER_USER.value,),
        ),
        # Another User's coverage of this User's watch.
        (
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            VALUES ('watch-1', ?, 'family')
            """,
            (OTHER_USER.value,),
        ),
        # A registration in a state the lifecycle does not know.
        (
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES ('registration-2', 'watch-1', ?, 'paused', 'address', 'other-hash', ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
        # A second registration with the same token.
        (
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES ('registration-3', 'watch-1', ?, 'live', 'address', 'token-hash', ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
        # A request for a rule that does not exist.
        (
            """
            INSERT INTO instant_sync_requests (
                rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                last_requested_at
            ) VALUES ('missing-rule', ?, 1, 0, ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
    )
    for statement, values in refused:
        with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
            connection.execute(statement, values)

    with transaction(database) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (USER.value,))

    with sqlite3.connect(database) as connection:
        left = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in OWNED
        ]
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert left == [0, 0, 0, 0]
    assert broken == []


def test_removing_an_account_or_a_rule_removes_what_instant_sync_kept_of_it(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    _watch_with_a_request(database)

    with transaction(database) as connection:
        connection.execute("DELETE FROM sync_rules WHERE id = 'rule-1'")
        connection.execute("DELETE FROM connected_accounts WHERE id = 'personal-account'")

    with sqlite3.connect(database) as connection:
        left = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in OWNED
        ]
    assert left == [0, 0, 0, 0]
```

Modify `tests/adapters/test_user_isolation_schema.py`: replace the comment and set above
`INSTALLATION_TABLES` with:

```python
# Tables that hold no User's records: the migration ledger, the Users themselves, the
# installation's settings, Invitations, which belong to nobody until they are used, and Delivery
# Evidence, which says whether providers reach the installation's own address.
INSTALLATION_TABLES = {
    "schema_migrations",
    "users",
    "installation_settings",
    "invitations",
    "delivery_evidence",
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_schema.py tests/adapters/test_user_isolation_schema.py -q`
Expected: FAIL (`no such column: instant_sync` and `no such table: calendar_watches`; the isolation test still passes)

- [ ] **Step 3: Implement**

Create `src/calendar_sync/infrastructure/persistence/0031_instant_sync.sql`:

```sql
-- Instant Sync (ADR 0036): a rule runs soon after its provider reports a change that may concern
-- its Source Calendar. A User's Calendar Watches, the calendars each one covers, the provider
-- channels or subscriptions that deliver its Watch Notices, and each rule's Instant Sync Request
-- belong to that User. Each refers to its account, watch, or rule by identifier and User together,
-- so the database refuses one whose User differs from its parent's, and it goes with its parent.
-- Only a hash of each registration's secret token is kept.
-- Delivery Evidence belongs to the installation: whether each provider reached its public address.
-- Nothing is rewritten: every existing User wants Instant Sync, and watches appear at the first
-- upkeep after start. Earlier releases ignore these tables and the column, so rolling back is safe;
-- providers then receive 404 until their registrations expire, and polling runs as before.
ALTER TABLE users ADD COLUMN instant_sync INTEGER NOT NULL DEFAULT 1;

CREATE TABLE calendar_watches (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    retry_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
    UNIQUE (id, user_id),
    UNIQUE (user_id, account_id, scope_key),
    FOREIGN KEY (account_id, user_id)
        REFERENCES connected_accounts(id, user_id) ON DELETE CASCADE
);
CREATE INDEX calendar_watches_account ON calendar_watches(account_id, user_id);

CREATE TABLE watch_coverage (
    watch_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    PRIMARY KEY (watch_id, calendar_id),
    FOREIGN KEY (watch_id, user_id)
        REFERENCES calendar_watches(id, user_id) ON DELETE CASCADE
);

CREATE TABLE watch_registrations (
    id TEXT PRIMARY KEY,
    watch_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('creating', 'live', 'retiring', 'abandoned')),
    address TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    requested_until TEXT NOT NULL,
    handle TEXT,
    expires_at TEXT,
    confirmed_at TEXT,
    renew_at TEXT,
    renew_requested_at TEXT,
    FOREIGN KEY (watch_id, user_id)
        REFERENCES calendar_watches(id, user_id) ON DELETE CASCADE
);
CREATE INDEX watch_registrations_watch ON watch_registrations(watch_id, user_id);
CREATE INDEX watch_registrations_user ON watch_registrations(user_id);

CREATE TABLE instant_sync_requests (
    rule_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    requested_seq INTEGER NOT NULL CHECK (requested_seq >= 0),
    handled_seq INTEGER NOT NULL DEFAULT 0 CHECK (handled_seq >= 0),
    first_requested_at TEXT NOT NULL,
    last_requested_at TEXT NOT NULL,
    last_run_at TEXT,
    FOREIGN KEY (rule_id, user_id) REFERENCES sync_rules(id, user_id) ON DELETE CASCADE
);
CREATE INDEX instant_sync_requests_pending
ON instant_sync_requests(user_id) WHERE requested_seq > handled_seq;

-- One row per provider and public address; no User's records.
CREATE TABLE delivery_evidence (
    provider TEXT NOT NULL,
    address TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    PRIMARY KEY (provider, address)
);
```

In `src/calendar_sync/infrastructure/persistence/migrations.py`, append to `_FORWARD_MIGRATIONS`
after `(30, "0030_birthday_policy.sql"),`:

```python
((31, "0031_instant_sync.sql"),)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_schema.py tests/adapters/test_user_isolation_schema.py tests/adapters/test_sqlite.py tests/adapters/test_user_migration.py tests/adapters/test_users_store.py -q`
Expected: PASS (`test_sqlite.py`'s version list now ends at 31)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/infrastructure/persistence/0031_instant_sync.sql \
  src/calendar_sync/infrastructure/persistence/migrations.py \
  tests/adapters/test_instant_sync_schema.py tests/adapters/test_user_isolation_schema.py
git commit -m "Keep each User's watches and Instant Sync Requests, and the installation's Delivery Evidence

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: User-scoped watch and request repositories in both units of work

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/watches.py`
- Modify: `src/calendar_sync/application/sync/ports.py` (`UnitOfWork` gains `watches` and `instant_requests`)
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`SqliteUnitOfWork` builds both repositories)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py` (`MemoryState` fields, in-memory twins, cascades, `raise_instant_request`)
- Modify: `tests/contracts/persistence.py` (harness hook `request_run`, contract tests)
- Modify: `tests/adapters/test_persistence_contract.py` (both harnesses supply `request_run`)
- Test: `tests/adapters/test_persistence_contract.py`

**Interfaces:**
- Consumes:
  - From `domain/watches.py` (Tasks 1 and 2): `CalendarWatch`, `CalendarWatchId`, `WatchScope`, `RegistrationState`, `WatchRegistration`, `WatchRegistrationId`, and `token_hash(token: str) -> str`
  - From `application/sync/watch_ports.py` (Task 3): `Receipt`, `PendingRequest`, `CalendarWatchRepository`, and `InstantSyncRequestRepository`
- Produces:
  - `UnitOfWork.watches: CalendarWatchRepository` and `UnitOfWork.instant_requests: InstantSyncRequestRepository`, in both units
  - In `infrastructure/persistence/watches.py`:
    - `SqliteCalendarWatchRepository(connection, user_id)`
    - `SqliteInstantSyncRequestRepository(connection, user_id)`
    - `stored_time(value: datetime) -> str`
    - `watch_from_row(row, coverage=frozenset()) -> CalendarWatch`
    - `registration_from_row(row) -> WatchRegistration`
    - `request_from_row(row) -> PendingRequest`
  - In `infrastructure/persistence/memory.py`:
    - `MemoryState.watches`, `MemoryState.registrations`, and `MemoryState.instant_requests`
    - `InMemoryCalendarWatchRepository` and `InMemoryInstantSyncRequestRepository`
    - `raise_instant_request(state: MemoryState, rule_id: SyncRuleId, at: datetime) -> None`
  - `PersistenceHarness.request_run: Callable[[UserId, SyncRuleId, datetime], object]`

- [ ] **Step 1: Write the failing test**

In `tests/contracts/persistence.py`:

Add to the imports (keep isort order):

```python
from calendar_sync.application.sync.watch_ports import PendingRequest, Receipt
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
```

After `HOUR = timedelta(hours=1)`, add:

```python
MINUTE = timedelta(minutes=1)
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    ACCOUNT,
    WatchScope.calendar(RULE.source.calendar_id),
    frozenset({RULE.source.calendar_id}),
)
THEIR_WATCH = CalendarWatch(
    CalendarWatchId("their-watch"),
    THEIR_SOURCE.connected_account_id,
    WatchScope.calendar(THEIR_SOURCE.calendar_id),
    frozenset({THEIR_SOURCE.calendar_id}),
)
"""Another User's watch of a calendar with the same identifier as WATCH's."""
RECEIPT = Receipt("handle-1", NOW + 7 * DAY)
```

Add a field to `PersistenceHarness`, after `incidents`:

```python
    request_run: Callable[[UserId, SyncRuleId, datetime], object]
    """Raise a rule's Instant Sync Request, as an authentic Watch Notice would outside any unit
    of work."""
```

After `_commit_as`, add:

```python
def _registration(
    name: str = "registration-1", watch: CalendarWatchId = WATCH.id
) -> WatchRegistration:
    """A registration upkeep recorded before asking the provider for it."""
    return WatchRegistration(
        WatchRegistrationId(name),
        watch,
        RegistrationState.CREATING,
        f"https://calendar.example.test/api/v1/watch-notices/test/{name}",
        token_hash(f"token-{name}"),
        NOW,
        NOW + 7 * DAY,
    )


def _live(name: str = "registration-1", watch: CalendarWatchId = WATCH.id) -> WatchRegistration:
    return replace(
        _registration(name, watch),
        state=RegistrationState.LIVE,
        handle=f"handle-{name}",
        expires_at=NOW + 7 * DAY,
        renew_at=NOW + 5 * DAY,
    )


def _watching(harness: PersistenceHarness, *registrations: WatchRegistration) -> None:
    """USER's watch of RULE's Source Calendar, with `registrations`."""
    with harness.unit_of_work() as uow:
        uow.watches.add(WATCH)
        for registration in registrations:
            uow.watches.add_registration(registration)
        uow.commit()
```

At the end of `class PersistenceContract`, add:

```python
# Calendar Watches and Instant Sync Requests


def test_watches_round_trip_with_their_coverage_and_registrations(
    self, harness: PersistenceHarness
) -> None:
    live = _live("registration-2")
    _watching(harness, _registration(), live)
    family = CalendarId("family")
    with harness.unit_of_work() as uow:
        uow.watches.set_coverage(WATCH.id, frozenset({RULE.source.calendar_id, family}))
        uow.watches.set_retry(WATCH.id, NOW + HOUR, 2)
        uow.commit()

    with harness.unit_of_work() as uow:
        watches, registrations = uow.watches.list(), uow.watches.registrations()

    assert watches == (
        replace(
            WATCH,
            coverage=frozenset({RULE.source.calendar_id, family}),
            retry_at=NOW + HOUR,
            failures=2,
        ),
    )
    assert registrations == (_registration(), live)


def test_a_receipt_makes_only_a_registration_still_being_created_live(
    self, harness: PersistenceHarness
) -> None:
    created, abandoned = (
        WatchRegistrationId("registration-1"),
        WatchRegistrationId("registration-2"),
    )
    _watching(harness, _registration(), _registration("registration-2"))
    with harness.unit_of_work() as uow:
        # Creation itself proved delivery, as a provider that validates the address does.
        assert uow.watches.record_receipt(
            created, Receipt("handle-1", NOW + 7 * DAY, confirmed=True), NOW + 5 * DAY, NOW
        )
        assert uow.watches.abandon(abandoned)
        uow.commit()

    with harness.unit_of_work() as uow:
        # Late receipts: the registration was abandoned, made live, or deleted meanwhile.
        late = (
            uow.watches.record_receipt(abandoned, RECEIPT, NOW + 5 * DAY, NOW + MINUTE),
            uow.watches.record_receipt(
                created, Receipt("handle-other", NOW + DAY), NOW, NOW + HOUR
            ),
            uow.watches.record_receipt(WatchRegistrationId("missing"), RECEIPT, NOW, NOW + HOUR),
        )
        uow.commit()
    with harness.unit_of_work() as uow:
        registrations = uow.watches.registrations()

    assert late == (False, False, False)
    assert registrations == (
        replace(
            _registration(),
            state=RegistrationState.LIVE,
            handle="handle-1",
            expires_at=NOW + 7 * DAY,
            renew_at=NOW + 5 * DAY,
            confirmed_at=NOW,
        ),
        replace(_registration("registration-2"), state=RegistrationState.ABANDONED),
    )


def test_a_receipt_after_a_removal_abandoned_its_registration_changes_nothing(
    self, harness: PersistenceHarness
) -> None:
    creating = _registration()
    _watching(harness, creating)
    # The inbox abandons a registration being created when its provider removes it.
    with harness.unit_of_work() as uow:
        removed = uow.watches.abandon(creating.id)
        uow.commit()
    with harness.unit_of_work() as uow:
        late = uow.watches.record_receipt(
            creating.id, Receipt("handle-1", NOW + 7 * DAY, confirmed=True), NOW, NOW
        )
        uow.commit()
    with harness.unit_of_work() as uow:
        registrations = uow.watches.registrations()

    assert (removed, late) == (True, False)
    assert registrations == (replace(creating, state=RegistrationState.ABANDONED),)


def test_an_extension_keeps_a_renewal_request_newer_than_the_one_it_answered(
    self, harness: PersistenceHarness
) -> None:
    asked = replace(_live(), renew_requested_at=NOW + HOUR)
    _watching(harness, asked)
    with harness.unit_of_work() as uow:
        # Upkeep read a request of NOW; the provider asked again at NOW + HOUR meanwhile.
        assert uow.watches.record_extension(
            asked.id, NOW + 8 * DAY, NOW + 6 * DAY, seen_request=NOW
        )
        uow.commit()
    with harness.unit_of_work() as uow:
        kept = uow.watches.registrations()[0]
        assert uow.watches.record_extension(
            asked.id, NOW + 9 * DAY, NOW + 7 * DAY, seen_request=NOW + HOUR
        )
        uow.commit()
    with harness.unit_of_work() as uow:
        cleared = uow.watches.registrations()[0]

    assert (kept.expires_at, kept.renew_at, kept.renew_requested_at) == (
        NOW + 8 * DAY,
        NOW + 6 * DAY,
        NOW + HOUR,
    )
    assert (cleared.expires_at, cleared.renew_at, cleared.renew_requested_at) == (
        NOW + 9 * DAY,
        NOW + 7 * DAY,
        None,
    )


def test_only_a_live_registration_extends_or_retires_and_any_is_abandoned(
    self, harness: PersistenceHarness
) -> None:
    creating = WatchRegistrationId("registration-1")
    live = WatchRegistrationId("registration-2")
    _watching(harness, _registration(), _live("registration-2"))
    with harness.unit_of_work() as uow:
        refused = (
            uow.watches.record_extension(creating, NOW + DAY, NOW, seen_request=None),
            uow.watches.retire(creating),
        )
        retired = (uow.watches.retire(live), uow.watches.retire(live))
        extended_retiring = uow.watches.record_extension(live, NOW + DAY, NOW, seen_request=None)
        abandoned = (
            uow.watches.abandon(creating),
            uow.watches.abandon(live),
            uow.watches.abandon(live),
            uow.watches.abandon(WatchRegistrationId("missing")),
        )
        uow.commit()
    with harness.unit_of_work() as uow:
        states = [registration.state for registration in uow.watches.registrations()]
        uow.watches.delete_registration(creating)
        uow.commit()
    with harness.unit_of_work() as uow:
        left = [registration.id for registration in uow.watches.registrations()]

    assert refused == (False, False)
    assert retired == (True, False)
    assert not extended_retiring
    # Abandoning works from any state, again too; only a missing registration refuses it.
    assert abandoned == (True, True, True, False)
    assert states == [RegistrationState.ABANDONED, RegistrationState.ABANDONED]
    assert left == [live]


def test_a_watch_needs_its_users_account_one_scope_and_a_token_of_its_own(
    self, harness: PersistenceHarness
) -> None:
    harness.connect_account(THEIR_ACCOUNT, OTHER_USER)
    with harness.unit_of_work() as uow:
        uow.watches.add(WATCH)
        uow.watches.add_registration(_registration())
        with pytest.raises(IdentityCollision):
            uow.watches.add(replace(WATCH, id=CalendarWatchId("watch-2")))
        with pytest.raises(MissingReference):
            uow.watches.add(replace(WATCH, id=CalendarWatchId("watch-3"), account=THEIR_ACCOUNT))
        with pytest.raises(MissingReference):
            uow.watches.add_registration(
                _registration("registration-2", CalendarWatchId("missing"))
            )
        with pytest.raises(IdentityCollision):
            uow.watches.add_registration(
                replace(_registration("registration-3"), token_hash=_registration().token_hash)
            )
        uow.commit()

    with harness.unit_of_work() as uow:
        assert uow.watches.list() == (WATCH,)
        assert uow.watches.registrations() == (_registration(),)


def test_another_user_can_neither_read_nor_change_a_users_watches_or_requests(
    self, harness: PersistenceHarness
) -> None:
    asked = replace(_live(), renew_requested_at=NOW)
    with harness.unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
    _watching(harness, asked, _registration("registration-2"))
    harness.request_run(USER, RULE.id, NOW)
    harness.connect_account(THEIR_SOURCE.connected_account_id, OTHER_USER)
    with harness.unit_of_work() as uow:
        watches, registrations = uow.watches.list(), uow.watches.registrations()

    with harness.units(OTHER_USER)() as theirs:
        seen = (
            theirs.watches.list(),
            theirs.watches.registrations(),
            theirs.instant_requests.pending(),
        )
        changed = (
            theirs.watches.record_receipt(WatchRegistrationId("registration-2"), RECEIPT, NOW, NOW),
            theirs.watches.record_extension(asked.id, NOW + 9 * DAY, NOW, seen_request=NOW),
            theirs.watches.retire(asked.id),
            theirs.watches.abandon(asked.id),
        )
        theirs.watches.set_coverage(WATCH.id, frozenset())
        theirs.watches.set_retry(WATCH.id, NOW + DAY, 5)
        theirs.watches.delete_registration(asked.id)
        theirs.watches.remove(WATCH.id)
        theirs.instant_requests.acknowledge(RULE.id, 1, NOW)
        # The identifier is taken; the account and the watch are another User's.
        with pytest.raises(IdentityCollision):
            theirs.watches.add(replace(THEIR_WATCH, id=WATCH.id))
        with pytest.raises(MissingReference):
            theirs.watches.add(replace(THEIR_WATCH, account=ACCOUNT))
        with pytest.raises(MissingReference):
            theirs.watches.add_registration(_registration("theirs"))
        theirs.commit()

    with harness.unit_of_work() as uow:
        assert (uow.watches.list(), uow.watches.registrations()) == (watches, registrations)
        assert uow.instant_requests.pending() == (PendingRequest(RULE.id, 1, 0, NOW, NOW, None),)
    assert seen == ((), (), ())
    assert changed == (False, False, False, False)


def test_acknowledging_a_request_never_lowers_what_was_handled(
    self, harness: PersistenceHarness
) -> None:
    with harness.unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
    for minutes in (0, 1, 2):
        harness.request_run(USER, RULE.id, NOW + minutes * MINUTE)
    with harness.unit_of_work() as uow:
        waiting = uow.instant_requests.pending()
        uow.instant_requests.acknowledge(RULE.id, 3, NOW + 3 * MINUTE)
        # A run that captured an earlier request finishes later.
        uow.instant_requests.acknowledge(RULE.id, 1, NOW + 4 * MINUTE)
        uow.commit()
    with harness.unit_of_work() as uow:
        handled = uow.instant_requests.pending()
    harness.request_run(USER, RULE.id, NOW + 5 * MINUTE)
    with harness.unit_of_work() as uow:
        again = uow.instant_requests.pending()

    assert waiting == (PendingRequest(RULE.id, 3, 0, NOW, NOW + 2 * MINUTE, None),)
    assert handled == ()
    # Waiting starts again from the notice that came after the runs.
    assert again == (
        PendingRequest(RULE.id, 4, 3, NOW + 5 * MINUTE, NOW + 5 * MINUTE, NOW + 4 * MINUTE),
    )


def test_removing_a_rule_removes_its_request_and_deleting_an_account_its_watches(
    self, harness: PersistenceHarness
) -> None:
    with harness.unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.rules.add(OTHER_RULE)
        uow.commit()
    for each in (RULE, OTHER_RULE):
        harness.request_run(USER, each.id, NOW)
    _watching(harness, _live())

    with harness.unit_of_work() as uow:
        uow.rules.remove(RULE.id)
        uow.commit()
    with harness.unit_of_work() as uow:
        kept = [request.rule_id for request in uow.instant_requests.pending()]
        uow.rules.purge(OTHER_RULE.id)
        uow.commit()
    harness.disconnect_account(ACCOUNT)
    with harness.unit_of_work() as uow:
        assert uow.accounts.delete_disconnected(ACCOUNT)
        uow.commit()
    with harness.unit_of_work() as uow:
        left = (
            uow.watches.list(),
            uow.watches.registrations(),
            uow.instant_requests.pending(),
        )

    assert kept == [OTHER_RULE.id]
    assert left == ((), (), ())
```

In `tests/adapters/test_persistence_contract.py`, add `from datetime import datetime` above
`from pathlib import Path`, and replace the existing `domain.model` and `memory` imports with:

```python
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    InMemoryUnitOfWorkFactory,
    raise_instant_request,
)
```

In `TestInMemoryUnitOfWork.harness`, before `return PersistenceHarness(`, add:

```python
        def request_run(user: UserId, rule_id: SyncRuleId, at: datetime) -> None:
            raise_instant_request(database.for_user(user).state, rule_id, at)
```

and pass `request_run=request_run,` after `incidents=...`.

In `TestSqliteUnitOfWork.harness`, before `return PersistenceHarness(`, add:

```python
        def request_run(user: UserId, rule_id: SyncRuleId, at: datetime) -> None:
            # As the Watch Notice inbox raises it: a handled request starts waiting again.
            with transaction(database) as connection:
                connection.execute(
                    """
                    INSERT INTO instant_sync_requests (
                        rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                        last_requested_at
                    ) VALUES (?, ?, 1, 0, ?, ?)
                    ON CONFLICT (rule_id) DO UPDATE SET
                        first_requested_at = CASE WHEN requested_seq = handled_seq
                            THEN excluded.first_requested_at
                            ELSE MIN(first_requested_at, excluded.first_requested_at) END,
                        requested_seq = requested_seq + 1,
                        last_requested_at = MAX(last_requested_at, excluded.last_requested_at)
                    """,
                    (rule_id.value, user.value, at.isoformat(), at.isoformat()),
                )
```

and pass `request_run=request_run,` after `incidents=...`.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py -q`
Expected: FAIL (`ImportError: cannot import name 'raise_instant_request'`, then `AttributeError: ... has no attribute 'watches'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/application/sync/ports.py`, add after the `application.sync.errors` import:

```python
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
)
```

In `class UnitOfWork(Protocol)`, after `provider_calls: ProviderCallRepository`, add:

```python
    watches: CalendarWatchRepository
    instant_requests: InstantSyncRequestRepository
```

Create `src/calendar_sync/infrastructure/persistence/watches.py`:

```python
"""SQLite storage of each User's Calendar Watches, Watch Registrations, and Instant Sync Requests.

Every change of a registration's state names the state it leaves, in one statement, so a writer
that comes late changes nothing: a receipt for a registration no longer being created never brings
it back, and upkeep clears a renewal request only while it still holds the time upkeep read.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from calendar_sync.application.sync.watch_ports import PendingRequest, Receipt
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import CalendarId, ConnectedAccountId, SyncRuleId
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.persistence.refusals import refusals


def stored_time(value: datetime) -> str:
    """UTC ISO 8601 text, which orders as the instants do, to the microsecond."""
    return value.astimezone(UTC).isoformat()


def _stored(value: datetime | None) -> str | None:
    return None if value is None else stored_time(value)


def _read(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


class SqliteCalendarWatchRepository:
    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def list(self) -> Sequence[CalendarWatch]:
        coverage: dict[str, set[CalendarId]] = {}
        for row in self._connection.execute(
            "SELECT watch_id, calendar_id FROM watch_coverage WHERE user_id = ?", (self._user,)
        ):
            covered = coverage.setdefault(str(row["watch_id"]), set())
            covered.add(CalendarId(str(row["calendar_id"])))
        rows = self._connection.execute(
            "SELECT * FROM calendar_watches WHERE user_id = ? ORDER BY id", (self._user,)
        ).fetchall()
        return tuple(
            watch_from_row(row, frozenset(coverage.get(str(row["id"]), ()))) for row in rows
        )

    def registrations(self) -> Sequence[WatchRegistration]:
        rows = self._connection.execute(
            """
            SELECT * FROM watch_registrations WHERE user_id = ?
            ORDER BY watch_id, created_at, id
            """,
            (self._user,),
        ).fetchall()
        return tuple(registration_from_row(row) for row in rows)

    def add(self, watch: CalendarWatch) -> None:
        # The reference to the account names this User, so another User's account is refused.
        with refusals():
            self._connection.execute(
                """
                INSERT INTO calendar_watches (
                    id, user_id, account_id, scope_key, retry_at, failures
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    watch.id.value,
                    self._user,
                    watch.account.value,
                    watch.scope.key,
                    _stored(watch.retry_at),
                    watch.failures,
                ),
            )
        self.set_coverage(watch.id, watch.coverage)

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        owned = (watch_id.value, self._user)
        self._connection.execute(
            "DELETE FROM watch_coverage WHERE watch_id = ? AND user_id = ?", owned
        )
        # Selecting from the watch records nothing for another User's.
        self._connection.executemany(
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            SELECT id, user_id, ? FROM calendar_watches WHERE id = ? AND user_id = ?
            """,
            [
                (calendar.value, *owned)
                for calendar in sorted(coverage, key=lambda calendar: calendar.value)
            ],
        )

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        self._connection.execute(
            "UPDATE calendar_watches SET retry_at = ?, failures = ? WHERE id = ? AND user_id = ?",
            (_stored(retry_at), failures, watch_id.value, self._user),
        )

    def remove(self, watch_id: CalendarWatchId) -> None:
        # Its coverage and registrations refer to it with ON DELETE CASCADE.
        self._connection.execute(
            "DELETE FROM calendar_watches WHERE id = ? AND user_id = ?",
            (watch_id.value, self._user),
        )

    def add_registration(self, registration: WatchRegistration) -> None:
        # The reference to the watch names this User, so another User's watch is refused.
        with refusals():
            self._connection.execute(
                """
                INSERT INTO watch_registrations (
                    id, watch_id, user_id, state, address, token_hash, created_at,
                    requested_until, handle, expires_at, confirmed_at, renew_at,
                    renew_requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.id.value,
                    registration.watch_id.value,
                    self._user,
                    registration.state.value,
                    registration.address,
                    registration.token_hash,
                    stored_time(registration.created_at),
                    stored_time(registration.requested_until),
                    registration.handle,
                    _stored(registration.expires_at),
                    _stored(registration.confirmed_at),
                    _stored(registration.renew_at),
                    _stored(registration.renew_requested_at),
                ),
            )

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        # A notice may have confirmed it before the provider answered; that confirmation stands.
        cursor = self._connection.execute(
            """
            UPDATE watch_registrations SET
                state = :live, handle = :handle, expires_at = :expires_at, renew_at = :renew_at,
                confirmed_at = CASE WHEN :confirmed THEN COALESCE(confirmed_at, :at)
                    ELSE confirmed_at END
            WHERE id = :id AND user_id = :user AND state = :creating
            """,
            {
                "live": RegistrationState.LIVE.value,
                "handle": receipt.handle,
                "expires_at": stored_time(receipt.expires_at),
                "renew_at": stored_time(renew_at),
                "confirmed": receipt.confirmed,
                "at": stored_time(at),
                "id": registration_id.value,
                "user": self._user,
                "creating": RegistrationState.CREATING.value,
            },
        )
        return cursor.rowcount == 1

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        # A renewal the provider asked for after upkeep read `seen_request` is kept for the next.
        cursor = self._connection.execute(
            """
            UPDATE watch_registrations SET
                expires_at = ?, renew_at = ?,
                renew_requested_at = CASE WHEN renew_requested_at IS ? THEN NULL
                    ELSE renew_requested_at END
            WHERE id = ? AND user_id = ? AND state = ?
            """,
            (
                stored_time(expires_at),
                stored_time(renew_at),
                _stored(seen_request),
                registration_id.value,
                self._user,
                RegistrationState.LIVE.value,
            ),
        )
        return cursor.rowcount == 1

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        cursor = self._connection.execute(
            "UPDATE watch_registrations SET state = ? WHERE id = ? AND user_id = ? AND state = ?",
            (
                RegistrationState.RETIRING.value,
                registration_id.value,
                self._user,
                RegistrationState.LIVE.value,
            ),
        )
        return cursor.rowcount == 1

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        # From any state; whether this User has the registration.
        cursor = self._connection.execute(
            "UPDATE watch_registrations SET state = ? WHERE id = ? AND user_id = ?",
            (RegistrationState.ABANDONED.value, registration_id.value, self._user),
        )
        return cursor.rowcount == 1

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self._connection.execute(
            "DELETE FROM watch_registrations WHERE id = ? AND user_id = ?",
            (registration_id.value, self._user),
        )


class SqliteInstantSyncRequestRepository:
    """One User's Instant Sync Requests. The Watch Notice inbox raises them outside any unit of
    work; a unit of work reads and acknowledges them."""

    def __init__(self, connection: sqlite3.Connection, user_id: UserId) -> None:
        self._connection = connection
        self._user = user_id.value

    def pending(self) -> Sequence[PendingRequest]:
        rows = self._connection.execute(
            """
            SELECT * FROM instant_sync_requests
            WHERE user_id = ? AND requested_seq > handled_seq
            ORDER BY rule_id
            """,
            (self._user,),
        ).fetchall()
        return tuple(request_from_row(row) for row in rows)

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        # One statement that never lowers what was handled: a notice during the run raised
        # requested_seq past `seq`, so another run follows.
        self._connection.execute(
            """
            UPDATE instant_sync_requests SET handled_seq = MAX(handled_seq, ?), last_run_at = ?
            WHERE rule_id = ? AND user_id = ?
            """,
            (seq, stored_time(ran_at), rule_id.value, self._user),
        )


def watch_from_row(
    row: sqlite3.Row, coverage: frozenset[CalendarId] = frozenset()
) -> CalendarWatch:
    return CalendarWatch(
        id=CalendarWatchId(str(row["id"])),
        account=ConnectedAccountId(str(row["account_id"])),
        scope=WatchScope(str(row["scope_key"])),
        coverage=coverage,
        retry_at=_read(row["retry_at"]),
        failures=int(row["failures"]),
    )


def registration_from_row(row: sqlite3.Row) -> WatchRegistration:
    return WatchRegistration(
        id=WatchRegistrationId(str(row["id"])),
        watch_id=CalendarWatchId(str(row["watch_id"])),
        state=RegistrationState(str(row["state"])),
        address=str(row["address"]),
        token_hash=str(row["token_hash"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        requested_until=datetime.fromisoformat(str(row["requested_until"])),
        handle=None if row["handle"] is None else str(row["handle"]),
        expires_at=_read(row["expires_at"]),
        confirmed_at=_read(row["confirmed_at"]),
        renew_at=_read(row["renew_at"]),
        renew_requested_at=_read(row["renew_requested_at"]),
    )


def request_from_row(row: sqlite3.Row) -> PendingRequest:
    return PendingRequest(
        rule_id=SyncRuleId(str(row["rule_id"])),
        requested_seq=int(row["requested_seq"]),
        handled_seq=int(row["handled_seq"]),
        first_requested_at=datetime.fromisoformat(str(row["first_requested_at"])),
        last_requested_at=datetime.fromisoformat(str(row["last_requested_at"])),
        last_run_at=_read(row["last_run_at"]),
    )
```

In `src/calendar_sync/infrastructure/persistence/sqlite.py`:

Add the imports:

```python
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
)
from calendar_sync.infrastructure.persistence.watches import (
    SqliteCalendarWatchRepository,
    SqliteInstantSyncRequestRepository,
)
```

In `class SqliteUnitOfWork`, after `provider_calls: ProviderCallRepository`, add:

```python
    watches: CalendarWatchRepository
    instant_requests: InstantSyncRequestRepository
```

In `SqliteUnitOfWork.__enter__`, after `self.provider_calls = SqliteProviderCallRepository(connection, user)`, add:

```python
        self.watches = SqliteCalendarWatchRepository(connection, user)
        self.instant_requests = SqliteInstantSyncRequestRepository(connection, user)
```

In `src/calendar_sync/infrastructure/persistence/memory.py`:

Add these imports, in isort order beside the existing ones:

```python
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
    PendingRequest,
    Receipt,
)
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
)
```

In `class MemoryState`, after the `provider_calls` field, add:

```python
    watches: dict[CalendarWatchId, CalendarWatch] = field(default_factory=dict)
    registrations: dict[WatchRegistrationId, WatchRegistration] = field(default_factory=dict)
    instant_requests: dict[SyncRuleId, PendingRequest] = field(default_factory=dict)
    """Raised by the Watch Notice inbox outside any unit of work, as SQLite's are. A unit copies
    its partition when it opens and commits, so a test raises requests only between units."""
```

After `_duplicate_relationship`, add:

```python
def _forget_watches(state: MemoryState, account_id: ConnectedAccountId) -> None:
    """Mirror SQLite's cascade from an account to its watches and their registrations."""
    gone = {key for key, watch in state.watches.items() if watch.account == account_id}
    state.watches = {key: watch for key, watch in state.watches.items() if key not in gone}
    state.registrations = {
        key: registration
        for key, registration in state.registrations.items()
        if registration.watch_id not in gone
    }


def raise_instant_request(state: MemoryState, rule_id: SyncRuleId, at: datetime) -> None:
    """Raise a rule's Instant Sync Request as SQLite's inbox does: a request already handled
    starts waiting again from `at`, and a pending one keeps the earliest time it waits since and
    the latest time it was raised, whatever order notices arrive in."""
    current = state.instant_requests.get(rule_id)
    if current is None:
        state.instant_requests[rule_id] = PendingRequest(rule_id, 1, 0, at, at, None)
        return
    waiting = current.requested_seq > current.handled_seq
    state.instant_requests[rule_id] = replace(
        current,
        requested_seq=current.requested_seq + 1,
        first_requested_at=min(current.first_requested_at, at) if waiting else at,
        last_requested_at=max(current.last_requested_at, at),
    )
```

In `InMemoryConnectedAccountRecords.delete_disconnected`, after the `calendar_names` filter and
before the Incident comment, add:

```python
        _forget_watches(self._state, account_id)
```

In `InMemorySyncRuleRepository.remove`, after `self._state.previews.pop(rule_id, None)`, add:

```python
        self._state.instant_requests.pop(rule_id, None)
```

After `class InMemoryProviderCallRepository`, add:

```python
class InMemoryCalendarWatchRepository:
    def __init__(self, state: MemoryState, others: _OtherUsers) -> None:
        self._state = state
        self._others = others

    def list(self) -> tuple[CalendarWatch, ...]:
        return tuple(sorted(self._state.watches.values(), key=lambda watch: watch.id.value))

    def registrations(self) -> tuple[WatchRegistration, ...]:
        return tuple(
            sorted(
                self._state.registrations.values(),
                key=lambda each: (each.watch_id.value, each.created_at, each.id.value),
            )
        )

    def add(self, watch: CalendarWatch) -> None:
        # Mirror SQLite's primary key, its one watch per account and scope, and its reference to
        # the User's own account.
        if (
            watch.id in self._state.watches
            or self._others.hold_watch(watch.id)
            or any(
                other.account == watch.account and other.scope == watch.scope
                for other in self._state.watches.values()
            )
        ):
            raise IdentityCollision(f"calendar watch {watch.id.value} already exists")
        if watch.account not in self._state.accounts:
            raise MissingReference(f"connected account {watch.account.value} does not exist")
        self._state.watches[watch.id] = watch

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        watch = self._state.watches.get(watch_id)
        if watch is not None:
            self._state.watches[watch_id] = replace(watch, coverage=frozenset(coverage))

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        watch = self._state.watches.get(watch_id)
        if watch is not None:
            self._state.watches[watch_id] = replace(watch, retry_at=retry_at, failures=failures)

    def remove(self, watch_id: CalendarWatchId) -> None:
        self._state.watches.pop(watch_id, None)
        self._state.registrations = {
            key: registration
            for key, registration in self._state.registrations.items()
            if registration.watch_id != watch_id
        }

    def add_registration(self, registration: WatchRegistration) -> None:
        # Mirror SQLite's primary key, its unique token hash, and its reference to the watch.
        if self._others.hold_registration(registration) or any(
            other.id == registration.id or other.token_hash == registration.token_hash
            for other in self._state.registrations.values()
        ):
            raise IdentityCollision(f"watch registration {registration.id.value} already exists")
        if registration.watch_id not in self._state.watches:
            raise MissingReference(f"calendar watch {registration.watch_id.value} does not exist")
        self._state.registrations[registration.id] = registration

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state is not RegistrationState.CREATING:
            return False
        confirmed = registration.confirmed_at or (at if receipt.confirmed else None)
        self._state.registrations[registration_id] = replace(
            registration,
            state=RegistrationState.LIVE,
            handle=receipt.handle,
            expires_at=receipt.expires_at,
            renew_at=renew_at,
            confirmed_at=confirmed,
        )
        return True

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state is not RegistrationState.LIVE:
            return False
        asked = registration.renew_requested_at
        self._state.registrations[registration_id] = replace(
            registration,
            expires_at=expires_at,
            renew_at=renew_at,
            renew_requested_at=None if asked == seen_request else asked,
        )
        return True

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.RETIRING, {RegistrationState.LIVE})

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.ABANDONED, set(RegistrationState))

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self._state.registrations.pop(registration_id, None)

    def _move(
        self,
        registration_id: WatchRegistrationId,
        to: RegistrationState,
        leaving: Collection[RegistrationState],
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state not in leaving:
            return False
        self._state.registrations[registration_id] = replace(registration, state=to)
        return True


class InMemoryInstantSyncRequestRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def pending(self) -> tuple[PendingRequest, ...]:
        return tuple(
            sorted(
                (
                    request
                    for request in self._state.instant_requests.values()
                    if request.requested_seq > request.handled_seq
                ),
                key=lambda request: request.rule_id.value,
            )
        )

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        current = self._state.instant_requests.get(rule_id)
        if current is not None:
            self._state.instant_requests[rule_id] = replace(
                current, handled_seq=max(current.handled_seq, seq), last_run_at=ran_at
            )
```

In `class InMemoryUnitOfWork`, after `provider_calls: ProviderCallRepository`, add:

```python
    watches: CalendarWatchRepository
    instant_requests: InstantSyncRequestRepository
```

In `InMemoryUnitOfWork.__enter__`, after `self.provider_calls = InMemoryProviderCallRepository(working)`, add:

```python
        self.watches = InMemoryCalendarWatchRepository(working, others)
        self.instant_requests = InMemoryInstantSyncRequestRepository(working)
```

In `class _OtherUsers`, after `hold_occurrence`, add:

```python
def hold_watch(self, watch_id: CalendarWatchId) -> bool:
    return any(watch_id in state.watches for state in self._states())


def hold_registration(self, registration: WatchRegistration) -> bool:
    return any(
        other.id == registration.id or other.token_hash == registration.token_hash
        for state in self._states()
        for other in state.registrations.values()
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py tests/adapters/test_sqlite.py tests/application -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/sync/ports.py \
  src/calendar_sync/infrastructure/persistence/watches.py \
  src/calendar_sync/infrastructure/persistence/sqlite.py \
  src/calendar_sync/infrastructure/persistence/memory.py \
  tests/contracts/persistence.py tests/adapters/test_persistence_contract.py
git commit -m "Store each User's Calendar Watches and Instant Sync Requests with transitions a late writer cannot undo

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Watch Notice inbox and Delivery Evidence log

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/watch_inbox.py`
- Modify: `src/calendar_sync/application/operations/ports.py` (`WatchNoticeInbox`, `InboxBusy`)
- Modify: `src/calendar_sync/infrastructure/persistence/connections.py` (`transaction(..., timeout=)`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py` (`MemoryDatabase.delivery_evidence`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory_installation.py` (`InMemoryWatchNoticeInbox`, `InMemoryDeliveryEvidenceLog`)
- Test: `tests/adapters/test_watch_inbox.py`

**Interfaces:**
- Consumes:
  - From `application/sync/watch_ports.py`: `WatchNotice`, `NoticeKind`, `DeliveryEvidenceLog`, `PendingRequest`, and `notice_address(public_address, provider_slug, registration_id) -> str`
  - From `domain/watches.py`: `DeliveryEvidence`, `RegistrationState`, `token_hash`, and `CalendarWatch.covers(endpoint) -> bool`
  - From Task 6: `stored_time` and `raise_instant_request`
- Produces:
  - In `application/operations/ports.py`:
    - `class WatchNoticeInbox(Protocol): def record(self, notices: Sequence[WatchNotice], provider: ProviderKind, address_base: str, at: datetime) -> int`
    - `class InboxBusy(ApplicationError)`
  - In `infrastructure/persistence/watch_inbox.py`:
    - `INBOX_LOCK_WAIT_SECONDS = 1.0` and `EVIDENCE_REFRESH = timedelta(minutes=1)`
    - `presents(notice: WatchNotice, stored_hash: str, stored_handle: str | None) -> bool`
    - `SqliteWatchNoticeInbox(database_path: Path, lock_wait: float = INBOX_LOCK_WAIT_SECONDS)`
    - `SqliteDeliveryEvidenceLog(database_path: Path)`, which implements `DeliveryEvidenceLog`
  - In `infrastructure/persistence/memory_installation.py`:
    - `InMemoryWatchNoticeInbox(database: MemoryDatabase, busy: bool = False)`
    - `InMemoryDeliveryEvidenceLog(database: MemoryDatabase)`
  - `transaction(database_path, *, timeout=BUSY_TIMEOUT_SECONDS)`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_watch_inbox.py`:

```python
"""Watch Notices as the inbox records them for every User, in SQLite and in memory alike."""

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.operations.ports import InboxBusy, WatchNoticeInbox
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    NoticeKind,
    PendingRequest,
    Receipt,
    WatchNotice,
    notice_address,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
from calendar_sync.infrastructure.persistence.connections import open_connection
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    MemoryDatabase,
)
from calendar_sync.infrastructure.persistence.memory_installation import (
    InMemoryDeliveryEvidenceLog,
    InMemoryWatchNoticeInbox,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.watch_inbox import (
    SqliteDeliveryEvidenceLog,
    SqliteWatchNoticeInbox,
)
from tests.helpers import NOW, endpoint, rule
from tests.users import OTHER_USER, RULE_ACCOUNTS, USER, add_account, memory_units

GOOGLE, OUTLOOK = ProviderKind.GOOGLE, ProviderKind.OUTLOOK
BASE = "https://calendar.example.test"
SECOND, MINUTE, HOUR, DAY = (
    timedelta(seconds=1),
    timedelta(minutes=1),
    timedelta(hours=1),
    timedelta(days=1),
)
THEIR_ACCOUNTS = ("their-personal-account", "their-work-account")
RULE = rule()
UNCOVERED = replace(
    RULE, id=SyncRuleId("rule-uncovered"), source=endpoint("personal-account", "family")
)
PAUSED = replace(
    RULE,
    id=SyncRuleId("rule-paused"),
    destination=endpoint("work-account", "other-calendar"),
    state=SyncRuleState.PAUSED,
)
THEIRS = replace(
    RULE,
    id=SyncRuleId("their-rule"),
    source=endpoint("their-personal-account", "personal-calendar"),
    destination=endpoint("their-work-account", "work-calendar"),
)
"""Another User's rule, whose Source Calendar has the same identifier as RULE's."""
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    RULE.source.connected_account_id,
    WatchScope.calendar(RULE.source.calendar_id),
    frozenset({RULE.source.calendar_id}),
)
THEIR_WATCH = CalendarWatch(
    CalendarWatchId("their-watch"),
    THEIRS.source.connected_account_id,
    WatchScope.calendar(THEIRS.source.calendar_id),
    frozenset({THEIRS.source.calendar_id}),
)
RECEIPT = Receipt("handle-registration-1", NOW + 7 * DAY)


@dataclass(frozen=True, slots=True)
class Store:
    units: Callable[[UserId], UnitOfWorkFactory]
    inbox: WatchNoticeInbox
    evidence: DeliveryEvidenceLog


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    """Both stores, with each User's accounts connected as their provider's."""
    owners = ((USER, RULE_ACCOUNTS), (OTHER_USER, THEIR_ACCOUNTS))
    if request.param == "sqlite":
        database = tmp_path / "calendar-sync.db"
        initialize_database(database)
        for user, accounts in owners:
            for account in accounts:
                add_account(database, account, user)
        return Store(
            SqliteUnitOfWorkFactory(database).for_user,
            SqliteWatchNoticeInbox(database),
            SqliteDeliveryEvidenceLog(database),
        )
    factory = InMemoryUnitOfWorkFactory()
    for user, accounts in owners:
        units = memory_units(factory, user=user, accounts=accounts)
        for account in accounts:
            units.state.providers[ConnectedAccountId(account)] = GOOGLE
    return Store(
        factory.for_user,
        InMemoryWatchNoticeInbox(factory.database),
        InMemoryDeliveryEvidenceLog(factory.database),
    )


def _registration(
    state: RegistrationState = RegistrationState.LIVE,
    *,
    name: str = "registration-1",
    watch: CalendarWatch = WATCH,
    base: str = BASE,
) -> WatchRegistration:
    registration_id = WatchRegistrationId(name)
    answered = state is not RegistrationState.CREATING
    return WatchRegistration(
        registration_id,
        watch.id,
        state,
        notice_address(base, "google", registration_id),
        token_hash(f"token-{name}"),
        NOW - HOUR,
        NOW + 7 * DAY,
        handle=f"handle-{name}" if answered else None,
        expires_at=NOW + 7 * DAY if answered else None,
    )


def _seed(
    store: Store,
    registration: WatchRegistration,
    *,
    user: UserId = USER,
    watch: CalendarWatch = WATCH,
    rules: tuple[SyncRule, ...] = (RULE,),
) -> None:
    with store.units(user)() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.watches.add(watch)
        uow.watches.add_registration(registration)
        uow.commit()


def _notice(
    kind: NoticeKind = NoticeKind.CHANGED,
    *,
    name: str = "registration-1",
    token: str | None = None,
    handle: str | None = None,
) -> WatchNotice:
    return WatchNotice(WatchRegistrationId(name), token or f"token-{name}", handle, kind)


def _record(
    store: Store,
    *notices: WatchNotice,
    after: timedelta = timedelta(0),
    provider: ProviderKind = GOOGLE,
) -> int:
    return store.inbox.record(notices, provider, BASE, NOW + after)


def _pending(store: Store, user: UserId = USER) -> tuple[PendingRequest, ...]:
    with store.units(user)() as uow:
        return tuple(uow.instant_requests.pending())


def _registrations(store: Store, user: UserId = USER) -> tuple[WatchRegistration, ...]:
    with store.units(user)() as uow:
        return tuple(uow.watches.registrations())


def test_an_unknown_registration_changes_nothing_and_proves_nothing(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(name="missing")) == 0

    assert _pending(store) == ()
    assert store.evidence.evidence(BASE) == {}


def test_a_wrong_token_changes_nothing(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(token="token-guessed")) == 0
    assert _record(store, _notice(NoticeKind.REAUTHORIZE, token="token-guessed")) == 0

    assert _pending(store) == ()
    assert _registrations(store) == (_registration(),)
    assert store.evidence.evidence(BASE) == {}


def test_an_abandoned_registration_is_recognized_and_ignored(store: Store) -> None:
    _seed(store, _registration(RegistrationState.ABANDONED))

    assert _record(store, _notice(), _notice(NoticeKind.STARTED)) == 0

    assert _pending(store) == ()
    assert _registrations(store) == (_registration(RegistrationState.ABANDONED),)
    assert store.evidence.evidence(BASE) == {}


def test_a_handle_that_differs_is_refused_and_a_missing_one_is_not_checked(store: Store) -> None:
    _seed(store, _registration())

    refused = _record(store, _notice(handle="handle-other"))
    accepted = _record(store, _notice(handle="handle-registration-1"), after=MINUTE)
    unchecked = _record(store, _notice(), after=2 * MINUTE)

    assert (refused, accepted, unchecked) == (0, 1, 1)
    assert [request.requested_seq for request in _pending(store)] == [2]


def test_a_notice_at_another_providers_address_is_refused(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(), provider=OUTLOOK) == 0

    assert _pending(store) == ()


def test_a_start_notice_confirms_a_registration_even_before_its_receipt(store: Store) -> None:
    # The provider confirmed the channel before it answered the request that created it.
    creating = _registration(RegistrationState.CREATING)
    _seed(store, creating)

    assert _record(store, _notice(NoticeKind.STARTED)) == 0
    assert _record(store, _notice(NoticeKind.STARTED), after=MINUTE) == 0
    with store.units(USER)() as uow:
        made_live = uow.watches.record_receipt(
            creating.id, RECEIPT, NOW + 5 * DAY, NOW + 2 * MINUTE
        )
        uow.commit()

    assert made_live
    assert _registrations(store) == (
        replace(
            creating,
            state=RegistrationState.LIVE,
            handle=RECEIPT.handle,
            expires_at=RECEIPT.expires_at,
            renew_at=NOW + 5 * DAY,
            confirmed_at=NOW,
        ),
    )


def test_a_change_requests_only_the_covered_enabled_rules_of_the_owner(store: Store) -> None:
    _seed(store, _registration(), rules=(RULE, UNCOVERED, PAUSED))
    _seed(
        store,
        _registration(name="their-registration", watch=THEIR_WATCH),
        user=OTHER_USER,
        watch=THEIR_WATCH,
        rules=(THEIRS,),
    )

    first = _record(store, _notice())
    missed = _record(store, _notice(NoticeKind.MISSED), after=MINUTE)
    waiting = _pending(store)
    with store.units(USER)() as uow:
        uow.instant_requests.acknowledge(RULE.id, 2, NOW + 2 * MINUTE)
        uow.commit()
    again = _record(store, _notice(), after=3 * MINUTE)

    assert (first, missed, again) == (1, 1, 1)
    assert waiting == (PendingRequest(RULE.id, 2, 0, NOW, NOW + MINUTE, None),)
    # Waiting starts again from the first notice after the run.
    assert _pending(store) == (
        PendingRequest(RULE.id, 3, 2, NOW + 3 * MINUTE, NOW + 3 * MINUTE, NOW + 2 * MINUTE),
    )
    # Another User's rule of a calendar with the same identifier is not this notice's to wake.
    assert _pending(store, OTHER_USER) == ()


def test_one_notice_repeated_in_a_batch_counts_once(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(), _notice()) == 1

    assert [request.requested_seq for request in _pending(store)] == [1]


def test_a_reauthorization_notice_asks_for_renewal_at_its_latest_time(store: Store) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(NoticeKind.REAUTHORIZE), after=MINUTE) == 0
    assert _record(store, _notice(NoticeKind.REAUTHORIZE), after=2 * MINUTE) == 0

    assert _registrations(store)[0].renew_requested_at == NOW + 2 * MINUTE
    assert _pending(store) == ()


def test_a_removal_notice_retires_the_registration_and_asks_for_a_catch_up_run(
    store: Store,
) -> None:
    _seed(store, _registration())

    assert _record(store, _notice(NoticeKind.REMOVED)) == 1

    assert _registrations(store)[0].state is RegistrationState.RETIRING
    assert [request.rule_id for request in _pending(store)] == [RULE.id]


def test_a_removal_before_the_receipt_abandons_the_registration_for_good(store: Store) -> None:
    # The provider removed the subscription before upkeep recorded its answer.
    creating = _registration(RegistrationState.CREATING)
    _seed(store, creating)

    assert _record(store, _notice(NoticeKind.REMOVED)) == 1
    with store.units(USER)() as uow:
        late = uow.watches.record_receipt(creating.id, RECEIPT, NOW + 5 * DAY, NOW + MINUTE)
        uow.commit()

    assert not late
    assert _registrations(store) == (replace(creating, state=RegistrationState.ABANDONED),)
    # Its later notices are recognized and ignored.
    assert _record(store, _notice(), after=2 * MINUTE) == 0


def test_notices_committed_out_of_order_never_move_a_requests_times_back(store: Store) -> None:
    _seed(store, _registration())

    # Two requests' notices: the later one commits first.
    _record(store, _notice(), after=MINUTE)
    _record(store, _notice())

    assert _pending(store) == (PendingRequest(RULE.id, 2, 0, NOW, NOW + MINUTE, None),)


def test_success_evidence_is_refreshed_at_most_once_a_minute(store: Store) -> None:
    _seed(store, _registration())

    _record(store, _notice())
    _record(store, _notice(), after=30 * SECOND)
    throttled = store.evidence.evidence(BASE)
    _record(store, _notice(), after=61 * SECOND)
    refreshed = store.evidence.evidence(BASE)
    # A failure since the last success is answered by the next notice, however soon.
    store.evidence.failed(GOOGLE, BASE, NOW + 70 * SECOND)
    _record(store, _notice(), after=80 * SECOND)

    assert throttled == {GOOGLE: DeliveryEvidence(GOOGLE, BASE, last_success_at=NOW)}
    assert refreshed[GOOGLE].last_success_at == NOW + 61 * SECOND
    assert store.evidence.evidence(BASE) == {
        GOOGLE: DeliveryEvidence(
            GOOGLE,
            BASE,
            last_success_at=NOW + 80 * SECOND,
            last_failure_at=NOW + 70 * SECOND,
        )
    }


def test_a_notice_sent_to_an_earlier_address_proves_nothing_about_the_current_one(
    store: Store,
) -> None:
    _seed(store, _registration(base="https://old.example.test"))

    assert _record(store, _notice()) == 1

    assert store.evidence.evidence(BASE) == {}


def test_delivery_evidence_keeps_the_latest_success_and_failure_per_provider_and_address(
    store: Store,
) -> None:
    other = "https://other.example.test"
    store.evidence.succeeded(GOOGLE, BASE, NOW)
    store.evidence.failed(GOOGLE, BASE, NOW + HOUR)
    # An earlier time recorded later moves nothing back.
    store.evidence.succeeded(GOOGLE, BASE, NOW - HOUR)
    store.evidence.failed(GOOGLE, BASE, NOW)
    store.evidence.failed(OUTLOOK, other, NOW)

    assert store.evidence.evidence(BASE) == {
        GOOGLE: DeliveryEvidence(GOOGLE, BASE, last_success_at=NOW, last_failure_at=NOW + HOUR)
    }
    assert store.evidence.evidence(other) == {
        OUTLOOK: DeliveryEvidence(OUTLOOK, other, last_failure_at=NOW)
    }


def test_a_locked_store_answers_busy_and_records_nothing(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    for account in RULE_ACCOUNTS:
        add_account(database, account, USER)
    units = SqliteUnitOfWorkFactory(database).for_user(USER)
    with units() as uow:
        uow.rules.add(RULE)
        uow.watches.add(WATCH)
        uow.watches.add_registration(_registration())
        uow.commit()
    inbox = SqliteWatchNoticeInbox(database, lock_wait=0.05)

    with closing(open_connection(database)) as blocker:
        # Another writer holds the lock past the inbox's wait.
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(InboxBusy):
            inbox.record([_notice()], GOOGLE, BASE, NOW)
        blocker.rollback()

    with units() as uow:
        assert uow.instant_requests.pending() == ()


def test_the_in_memory_inbox_stands_for_a_locked_store_when_busy() -> None:
    inbox = InMemoryWatchNoticeInbox(MemoryDatabase(), busy=True)

    with pytest.raises(InboxBusy):
        inbox.record([_notice()], GOOGLE, BASE, NOW)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_watch_inbox.py -q`
Expected: FAIL (`ImportError: cannot import name 'InboxBusy' from 'calendar_sync.application.operations.ports'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/infrastructure/persistence/connections.py`, replace `transaction` with:

```python
@contextmanager
def transaction(
    database_path: Path, *, timeout: float = BUSY_TIMEOUT_SECONDS
) -> Iterator[sqlite3.Connection]:
    """One short transaction: committed when the block succeeds, rolled back if it raises.

    The connection is closed either way, so no handle or lock outlives the block. A write waits up
    to `timeout` seconds for another writer's lock.
    """
    with closing(open_connection(database_path, timeout=timeout)) as connection, connection:
        yield connection
```

In `src/calendar_sync/application/operations/ports.py`, add the imports:

```python
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.application.sync.watch_ports import WatchNotice
```

and after `class InstallationUnitOfWorkFactory`, add:

```python
class InboxBusy(ApplicationError):
    """The store stayed locked past the inbox's short wait; the provider sends the notice again."""


class WatchNoticeInbox(Protocol):
    """Where every User's Watch Notices are recorded (ADR 0029, amended by ADR 0036). It reads
    and writes only Watch Registrations, Instant Sync Requests, and Delivery Evidence, and makes
    no provider call."""

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        """Apply each authentic notice in one short transaction; how many rule requests it
        raised. A notice for an unknown or abandoned registration, another provider's, or one that
        presents a wrong token or handle changes nothing. Raises InboxBusy when the store stays
        locked past the inbox's wait."""
        ...
```

Create `src/calendar_sync/infrastructure/persistence/watch_inbox.py`:

```python
"""Every User's Watch Notices, recorded where they land (ADR 0029, amended by ADR 0036).

Besides the installation-wide unit of work, this is the one reader that crosses Users. It reads
and writes only Watch Registrations, Instant Sync Requests, and Delivery Evidence, in one short
write transaction per request, and makes no provider call. A notice proves itself by its
registration's secret token, compared by hash in constant time; one that does not changes nothing.
"""

from __future__ import annotations

import hmac
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from calendar_sync.application.operations.ports import InboxBusy
from calendar_sync.application.sync.watch_ports import NoticeKind, WatchNotice
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import SyncRuleState
from calendar_sync.domain.watches import DeliveryEvidence, RegistrationState, token_hash
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.watches import stored_time

INBOX_LOCK_WAIT_SECONDS = 1.0
"""How long a notice waits for another writer before the provider is asked to send it again."""
EVIDENCE_REFRESH = timedelta(minutes=1)
"""How often notices refresh a provider's success evidence, so a busy calendar rarely writes it."""
_BUSY = frozenset({"SQLITE_BUSY", "SQLITE_LOCKED"})


def presents(notice: WatchNotice, stored_hash: str, stored_handle: str | None) -> bool:
    """Whether `notice` presents its registration's token, and its handle when both have one; a
    registration still being created has no handle yet. Both compare in constant time."""
    token = hmac.compare_digest(token_hash(notice.token).encode(), stored_hash.encode())
    handle = (
        notice.handle is None
        or stored_handle is None
        or hmac.compare_digest(notice.handle.encode(), stored_handle.encode())
    )
    return token and handle


class SqliteWatchNoticeInbox:
    def __init__(self, database_path: Path, lock_wait: float = INBOX_LOCK_WAIT_SECONDS) -> None:
        self._database_path = database_path
        self._lock_wait = lock_wait

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        try:
            with transaction(self._database_path, timeout=self._lock_wait) as connection:
                # The write lock first, so what is read is what is written.
                connection.execute("BEGIN IMMEDIATE")
                return _record(connection, notices, provider, address_base, at)
        except sqlite3.OperationalError as error:
            if error.sqlite_errorname not in _BUSY:
                raise
            raise InboxBusy("the store stayed locked; the notice is to be sent again") from error


def _record(
    connection: sqlite3.Connection,
    notices: Sequence[WatchNotice],
    provider: ProviderKind,
    address_base: str,
    at: datetime,
) -> int:
    requested, delivered = 0, False
    # A batch may repeat one notice; it counts once.
    for notice in dict.fromkeys(notices):
        found = _authentic(connection, notice, provider)
        if found is None:
            continue
        # Only a notice sent to the current address proves that the provider reaches it.
        delivered = delivered or str(found["address"]).startswith(f"{address_base}/")
        requested += _apply(connection, found, notice.kind, stored_time(at))
    if delivered:
        _refresh_success(connection, provider, address_base, at)
    return requested


def _authentic(
    connection: sqlite3.Connection, notice: WatchNotice, provider: ProviderKind
) -> sqlite3.Row | None:
    """The registration `notice` names, when the notice proves itself and the registration is
    `provider`'s and not abandoned. An abandoned one is recognized and ignored."""
    row = connection.execute(
        """
        SELECT registration.id, registration.user_id, registration.watch_id,
            registration.token_hash, registration.handle, registration.address
        FROM watch_registrations registration
        JOIN calendar_watches watch
            ON watch.id = registration.watch_id AND watch.user_id = registration.user_id
        JOIN connected_accounts account
            ON account.id = watch.account_id AND account.user_id = watch.user_id
        WHERE registration.id = ? AND registration.state != ? AND account.provider = ?
        """,
        (notice.registration_id.value, RegistrationState.ABANDONED.value, provider.value),
    ).fetchone()
    if row is None or not presents(notice, str(row["token_hash"]), row["handle"]):
        return None
    return row


def _apply(connection: sqlite3.Connection, found: sqlite3.Row, kind: NoticeKind, at: str) -> int:
    """What one authentic notice does, by kind; how many rule requests it raised."""
    owned = (str(found["id"]), str(found["user_id"]))
    if kind is NoticeKind.STARTED:
        connection.execute(
            """
            UPDATE watch_registrations SET confirmed_at = COALESCE(confirmed_at, ?)
            WHERE id = ? AND user_id = ?
            """,
            (at, *owned),
        )
        return 0
    if kind is NoticeKind.REAUTHORIZE:
        # The latest time, so upkeep that read an earlier one keeps this request for later.
        connection.execute(
            """
            UPDATE watch_registrations
            SET renew_requested_at = MAX(COALESCE(renew_requested_at, ?), ?)
            WHERE id = ? AND user_id = ?
            """,
            (at, at, *owned),
        )
        return 0
    if kind is NoticeKind.REMOVED:
        # A live registration retires. One still being created is abandoned, so the receipt
        # that arrives later cannot make a subscription the provider removed live.
        connection.execute(
            """
            UPDATE watch_registrations
            SET state = CASE state WHEN :live THEN :retiring ELSE :abandoned END
            WHERE id = :id AND user_id = :user AND state IN (:live, :creating)
            """,
            {
                "live": RegistrationState.LIVE.value,
                "retiring": RegistrationState.RETIRING.value,
                "abandoned": RegistrationState.ABANDONED.value,
                "creating": RegistrationState.CREATING.value,
                "id": owned[0],
                "user": owned[1],
            },
        )
    # A change, a missed notice, or a removal: what the provider did not say is caught up on.
    return _request_runs(connection, str(found["watch_id"]), owned[1], at)


def _request_runs(connection: sqlite3.Connection, watch_id: str, user: str, at: str) -> int:
    """Raise the request of each enabled rule of the watch's User whose Source Calendar the watch
    covers, in one statement. A request already handled starts waiting again from `at`.

    Notices of concurrent requests commit in any order, so neither time goes back: a pending
    request keeps the earliest time it waits since and the latest time it was raised."""
    return connection.execute(
        """
        INSERT INTO instant_sync_requests (
            rule_id, user_id, requested_seq, handled_seq, first_requested_at, last_requested_at
        )
        SELECT rule.id, rule.user_id, 1, 0, :at, :at
        FROM sync_rules rule
        JOIN calendar_watches watch
            ON watch.user_id = rule.user_id AND watch.account_id = rule.source_account_id
        JOIN watch_coverage coverage
            ON coverage.watch_id = watch.id AND coverage.user_id = watch.user_id
            AND coverage.calendar_id = rule.source_calendar_id
        WHERE watch.id = :watch AND rule.user_id = :user AND rule.state = :enabled
        ON CONFLICT (rule_id) DO UPDATE SET
            first_requested_at = CASE WHEN requested_seq = handled_seq
                THEN excluded.first_requested_at
                ELSE MIN(first_requested_at, excluded.first_requested_at) END,
            requested_seq = requested_seq + 1,
            last_requested_at = MAX(last_requested_at, excluded.last_requested_at)
        WHERE user_id = excluded.user_id
        """,
        {"at": at, "watch": watch_id, "user": user, "enabled": SyncRuleState.ENABLED.value},
    ).rowcount


def _refresh_success(
    connection: sqlite3.Connection, provider: ProviderKind, address: str, at: datetime
) -> None:
    """Record that `provider` reached `address`, at most once a minute unless a failure was
    recorded since the last success."""
    connection.execute(
        """
        INSERT INTO delivery_evidence (provider, address, last_success_at) VALUES (?, ?, ?)
        ON CONFLICT (provider, address) DO UPDATE SET
            last_success_at = MAX(
                COALESCE(last_success_at, excluded.last_success_at), excluded.last_success_at
            )
        WHERE last_success_at IS NULL OR last_success_at <= ?
            OR last_failure_at >= last_success_at
        """,
        (provider.value, address, stored_time(at), stored_time(at - EVIDENCE_REFRESH)),
    )


class SqliteDeliveryEvidenceLog:
    """Whether each provider reached each public address: installation data, no User's."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO delivery_evidence (provider, address, last_success_at)
                VALUES (?, ?, ?)
                ON CONFLICT (provider, address) DO UPDATE SET
                    last_success_at = MAX(
                        COALESCE(last_success_at, excluded.last_success_at),
                        excluded.last_success_at
                    )
                """,
                (provider.value, address, stored_time(at)),
            )

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO delivery_evidence (provider, address, last_failure_at)
                VALUES (?, ?, ?)
                ON CONFLICT (provider, address) DO UPDATE SET
                    last_failure_at = MAX(
                        COALESCE(last_failure_at, excluded.last_failure_at),
                        excluded.last_failure_at
                    )
                """,
                (provider.value, address, stored_time(at)),
            )

    def evidence(self, address: str) -> dict[ProviderKind, DeliveryEvidence]:
        with transaction(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT provider, last_success_at, last_failure_at FROM delivery_evidence
                WHERE address = ? ORDER BY provider
                """,
                (address,),
            ).fetchall()
        found: dict[ProviderKind, DeliveryEvidence] = {}
        for row in rows:
            # A provider a later release recorded and this one does not know is left out.
            provider = ProviderKind.recorded(row["provider"])
            if provider is not None:
                found[provider] = DeliveryEvidence(
                    provider,
                    address,
                    last_success_at=_moment(row["last_success_at"]),
                    last_failure_at=_moment(row["last_failure_at"]),
                )
        return found


def _moment(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))
```

In `src/calendar_sync/infrastructure/persistence/memory.py`, add
`from calendar_sync.domain.watches import DeliveryEvidence` to the `domain.watches` import, and in
`class MemoryDatabase` after the `incidents` field add:

```python
delivery_evidence: dict[tuple[ProviderKind, str], DeliveryEvidence] = field(default_factory=dict)
"""Whether each provider reached each public address, as SQLite's installation table keeps."""
```

In `src/calendar_sync/infrastructure/persistence/memory_installation.py`:

Change `from collections.abc import Collection` to `from collections.abc import Collection, Sequence`,
`from dataclasses import dataclass` to `from dataclasses import dataclass, replace`, extend the
`application.operations.ports` import with `InboxBusy`, and add:

```python
from calendar_sync.application.sync.watch_ports import NoticeKind, WatchNotice
from calendar_sync.domain.watches import (
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
)
from calendar_sync.infrastructure.persistence.watch_inbox import EVIDENCE_REFRESH, presents
```

and add `raise_instant_request` to the existing `calendar_sync.infrastructure.persistence.memory`
import.

Before `class InMemoryInstallationUnitOfWorkFactory`, add:

```python
@dataclass(slots=True)
class InMemoryWatchNoticeInbox:
    """Every User's Watch Notices, as SQLite's inbox records them. Its writes reach each User's
    committed records at once. Setting `busy` stands for a store that stays locked."""

    database: MemoryDatabase
    busy: bool = False

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        if self.busy:
            raise InboxBusy("the store stayed locked; the notice is to be sent again")
        requested, delivered = 0, False
        for notice in dict.fromkeys(notices):
            found = _authentic(self.database, notice, provider)
            if found is None:
                continue
            state, registration = found
            delivered = delivered or registration.address.startswith(f"{address_base}/")
            requested += _apply(state, registration, notice.kind, at)
        if delivered:
            _refresh_success(self.database, provider, address_base, at)
        return requested


_REMOVED_TO = {
    RegistrationState.LIVE: RegistrationState.RETIRING,
    RegistrationState.CREATING: RegistrationState.ABANDONED,
}
"""What a removal notice makes of a registration: one still being created is abandoned, so its
late receipt cannot make it live."""


def _authentic(
    database: MemoryDatabase, notice: WatchNotice, provider: ProviderKind
) -> tuple[MemoryState, WatchRegistration] | None:
    for state in database.partitions.values():
        registration = state.registrations.get(notice.registration_id)
        if registration is None:
            continue
        watch = state.watches.get(registration.watch_id)
        if (
            registration.state is RegistrationState.ABANDONED
            or watch is None
            or state.providers.get(watch.account) is not provider
            or not presents(notice, registration.token_hash, registration.handle)
        ):
            return None
        return state, registration
    return None


def _apply(
    state: MemoryState, registration: WatchRegistration, kind: NoticeKind, at: datetime
) -> int:
    key = registration.id
    if kind is NoticeKind.STARTED:
        state.registrations[key] = replace(
            registration, confirmed_at=registration.confirmed_at or at
        )
        return 0
    if kind is NoticeKind.REAUTHORIZE:
        asked = registration.renew_requested_at
        state.registrations[key] = replace(
            registration, renew_requested_at=max(asked, at) if asked else at
        )
        return 0
    if kind is NoticeKind.REMOVED and registration.state in _REMOVED_TO:
        state.registrations[key] = replace(registration, state=_REMOVED_TO[registration.state])
    return _request_runs(state, registration.watch_id, at)


def _request_runs(state: MemoryState, watch_id: CalendarWatchId, at: datetime) -> int:
    watch = state.watches.get(watch_id)
    if watch is None:
        return 0
    woken = [
        rule.id
        for rule in state.rules.values()
        if rule.state is SyncRuleState.ENABLED and watch.covers(rule.source)
    ]
    for rule_id in woken:
        raise_instant_request(state, rule_id, at)
    return len(woken)


def _refresh_success(
    database: MemoryDatabase, provider: ProviderKind, address: str, at: datetime
) -> None:
    kept = database.delivery_evidence.get((provider, address))
    latest = kept.last_success_at if kept else None
    failed_since = (
        kept is not None
        and latest is not None
        and kept.last_failure_at is not None
        and kept.last_failure_at >= latest
    )
    if latest is None or latest <= at - EVIDENCE_REFRESH or failed_since:
        InMemoryDeliveryEvidenceLog(database).succeeded(provider, address, at)


@dataclass(frozen=True, slots=True)
class InMemoryDeliveryEvidenceLog:
    database: MemoryDatabase

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        kept = self._kept(provider, address)
        latest = kept.last_success_at
        self.database.delivery_evidence[(provider, address)] = replace(
            kept, last_success_at=max(latest, at) if latest else at
        )

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        kept = self._kept(provider, address)
        latest = kept.last_failure_at
        self.database.delivery_evidence[(provider, address)] = replace(
            kept, last_failure_at=max(latest, at) if latest else at
        )

    def evidence(self, address: str) -> dict[ProviderKind, DeliveryEvidence]:
        return {
            provider: kept
            for (provider, kept_address), kept in sorted(
                self.database.delivery_evidence.items(), key=lambda item: item[0][0].value
            )
            if kept_address == address
        }

    def _kept(self, provider: ProviderKind, address: str) -> DeliveryEvidence:
        return self.database.delivery_evidence.get((provider, address)) or DeliveryEvidence(
            provider, address
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_watch_inbox.py tests/adapters/test_persistence_contract.py tests/adapters/test_user_isolation_schema.py tests/adapters/test_sqlite_connections.py tests/test_provider_neutrality.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS (`watch_inbox.py` names no installation unit of work, so `INSTALLATION_UNIT_RECEIVERS` is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/operations/ports.py \
  src/calendar_sync/infrastructure/persistence/connections.py \
  src/calendar_sync/infrastructure/persistence/watch_inbox.py \
  src/calendar_sync/infrastructure/persistence/memory.py \
  src/calendar_sync/infrastructure/persistence/memory_installation.py \
  tests/adapters/test_watch_inbox.py
git commit -m "Record authentic Watch Notices for every User in one short transaction, and keep Delivery Evidence

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Installation queries for upkeep and dispatch

**Files:**
- Modify: `src/calendar_sync/application/operations/ports.py` (`InstantSyncOwner`, `PendingInstantRun`, two `InstallationUnitOfWork` queries)
- Modify: `src/calendar_sync/infrastructure/persistence/watches.py` (`upkeep_due`)
- Modify: `src/calendar_sync/infrastructure/persistence/installation.py` (SQLite queries)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py` (`MemoryDatabase.instant_sync_off`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory_installation.py` (in-memory queries)
- Modify: `tests/contracts/persistence.py` (harness hook `prefer`, contract tests)
- Modify: `tests/adapters/test_persistence_contract.py` (both harnesses supply `prefer`)
- Test: `tests/adapters/test_persistence_contract.py`

**Interfaces:**
- Consumes:
  - From Task 6: `watch_from_row`, `registration_from_row`, `request_from_row`, `MemoryState.watches`, `MemoryState.registrations`, `MemoryState.instant_requests`, and `PersistenceHarness.request_run`
  - From Task 5: the `users.instant_sync` column
  - `domain/watches.CREATION_DEADLINE` and `application/sync/ports.ScheduledRule`
- Produces:
  - `InstantSyncOwner(user: UserId, wanted: bool, disabled: bool, next_due: datetime | None)`
  - `PendingInstantRun(scheduled: ScheduledRule, request: PendingRequest, last_run_failed: bool)`
  - `InstallationUnitOfWork.instant_sync_owners() -> Sequence[InstantSyncOwner]`, ordered by User identifier
  - `InstallationUnitOfWork.pending_instant_runs() -> Sequence[PendingInstantRun]`, ordered by User and then rule
  - `upkeep_due(watches: Iterable[CalendarWatch], registrations: Iterable[WatchRegistration]) -> datetime | None`
  - `MemoryDatabase.instant_sync_off: set[UserId]`
  - `PersistenceHarness.prefer: Callable[[UserId, bool], object]`

- [ ] **Step 1: Write the failing test**

In `tests/contracts/persistence.py`:

Extend the `application.operations.ports` import with `InstantSyncOwner` and `PendingInstantRun`,
the `application.sync.ports` import with `ScheduledRule`, and the `domain.watches` import with
`CREATION_DEADLINE`.

Add a field to `PersistenceHarness`, after `request_run`:

```python
    prefer: Callable[[UserId, bool], object]
    """Record whether a User wants Instant Sync, as their account settings would outside any unit
    of work."""
```

At the end of `class PersistenceContract`, add:

```python
# What Instant Sync reads across Users


def test_instant_sync_owners_have_an_enabled_rule_or_a_watch_disabled_ones_included(
    self, harness: PersistenceHarness
) -> None:
    theirs = replace(
        RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
    )
    for account in (THEIR_SOURCE, THEIR_DESTINATION):
        harness.connect_account(account.connected_account_id, OTHER_USER)
    with harness.unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
    _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(theirs.pause()))
    with harness.installation() as installation:
        without_watches = installation.instant_sync_owners()

    _watching(harness, replace(_live(), confirmed_at=NOW))
    with harness.unit_of_work() as uow:
        uow.watches.set_retry(WATCH.id, NOW + HOUR, 1)
        uow.commit()

    def watch_theirs(uow: UnitOfWork) -> None:
        uow.watches.add(THEIR_WATCH)
        uow.watches.add_registration(_registration("their-registration", THEIR_WATCH.id))

    _commit_as(harness, OTHER_USER, watch_theirs)
    harness.disable(OTHER_USER)
    harness.prefer(OTHER_USER, False)
    with harness.installation() as installation:
        owners = installation.instant_sync_owners()

    # A paused rule alone needs no watch, and a User without a watch has nothing planned.
    assert without_watches == (InstantSyncOwner(USER, True, False, None),)
    assert owners == (
        # The retry comes before the planned renewal.
        InstantSyncOwner(USER, wanted=True, disabled=False, next_due=NOW + HOUR),
        # A disabled User is listed, so upkeep stops their watches.
        InstantSyncOwner(OTHER_USER, wanted=False, disabled=True, next_due=NOW + CREATION_DEADLINE),
    )


def test_pending_instant_runs_are_unhandled_requests_of_enabled_rules_of_active_users(
    self, harness: PersistenceHarness
) -> None:
    handled = replace(
        OTHER_RULE, id=SyncRuleId("rule-2"), destination=endpoint("work-account", "third")
    )
    theirs = replace(
        RULE, id=SyncRuleId("their-rule"), source=THEIR_SOURCE, destination=THEIR_DESTINATION
    )
    for account in (THEIR_SOURCE, THEIR_DESTINATION):
        harness.connect_account(account.connected_account_id, OTHER_USER)
    failed = RuleRunOutcome(
        RULE.id, RunKind.SYNC, NOW, False, failure_kind=ProviderFailureKind.TEMPORARY
    )
    with harness.unit_of_work() as uow:
        for each in (RULE, OTHER_RULE, handled):
            uow.rules.add(each)
        uow.run_outcomes.record(failed)
        uow.commit()
    _commit_as(harness, OTHER_USER, lambda uow: uow.rules.add(theirs))
    requested = ((USER, RULE), (USER, OTHER_RULE), (USER, handled), (OTHER_USER, theirs))
    for owner, each in requested:
        harness.request_run(owner, each.id, NOW)
    with harness.unit_of_work() as uow:
        uow.rules.save(OTHER_RULE.pause())
        uow.instant_requests.acknowledge(handled.id, 1, NOW + MINUTE)
        uow.commit()
    harness.disable(OTHER_USER)

    with harness.installation() as installation:
        failing = installation.pending_instant_runs()
    with harness.unit_of_work() as uow:
        uow.run_outcomes.record(
            replace(failed, completed_at=NOW + HOUR, succeeded=True, failure_kind=None)
        )
        uow.commit()
    with harness.installation() as installation:
        recovered = installation.pending_instant_runs()

    request = PendingRequest(RULE.id, 1, 0, NOW, NOW, None)
    scheduled = ScheduledRule(USER, RULE, None)
    assert failing == (PendingInstantRun(scheduled, request, last_run_failed=True),)
    assert recovered == (PendingInstantRun(scheduled, request, last_run_failed=False),)
```

In `tests/adapters/test_persistence_contract.py`:

In `TestInMemoryUnitOfWork.harness`, before `return PersistenceHarness(`, add:

```python
        def prefer(user: UserId, wanted: bool) -> None:
            off = database.database.instant_sync_off
            if wanted:
                off.discard(user)
            else:
                off.add(user)
```

and pass `prefer=prefer,` after `request_run=request_run,`.

In `TestSqliteUnitOfWork.harness`, before `return PersistenceHarness(`, add:

```python
        def prefer(user: UserId, wanted: bool) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE users SET instant_sync = ? WHERE id = ?", (int(wanted), user.value)
                )
```

and pass `prefer=prefer,` after `request_run=request_run,`.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py -q`
Expected: FAIL (`ImportError: cannot import name 'InstantSyncOwner'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/application/operations/ports.py`, change the `watch_ports` import to
`from calendar_sync.application.sync.watch_ports import PendingRequest, WatchNotice`, and after
`class CauseSighting` add:

```python
@dataclass(frozen=True, slots=True)
class InstantSyncOwner:
    """A User whose Calendar Watches upkeep reconciles: one with an enabled rule or a watch."""

    user: UserId
    wanted: bool
    """Whether they want Instant Sync, as their account settings say."""
    disabled: bool
    """A disabled User is listed too, so upkeep stops their watches."""
    next_due: datetime | None
    """When their watches next need upkeep: a retry, a renewal asked for or planned, a creation
    deadline, or the end of a registration. None when nothing is planned, as for a User without
    a watch yet, whose coverage is still missing."""


@dataclass(frozen=True, slots=True)
class PendingInstantRun:
    """An enabled rule of a User who is not disabled, whose Instant Sync Request waits."""

    scheduled: ScheduledRule
    request: PendingRequest
    last_run_failed: bool
    """Whether its latest Sync Run failed; Scheduled Sync retries such a rule until one succeeds."""
```

In `class InstallationUnitOfWork(Protocol)`, after `status_records`, add:

```python
def instant_sync_owners(self) -> Sequence[InstantSyncOwner]:
    """Every User with an enabled rule or a Calendar Watch, disabled Users included, by
    identifier."""
    ...


def pending_instant_runs(self) -> Sequence[PendingInstantRun]:
    """Every enabled rule of a User who is not disabled whose Instant Sync Request is not yet
    handled, by User and then by rule. Neither the User's wish nor their cadence is read
    here; dispatch decides with them."""
    ...
```

In `src/calendar_sync/infrastructure/persistence/watches.py`, change
`from collections.abc import Sequence` to `from collections.abc import Iterable, Sequence`, add
`CREATION_DEADLINE` to the `domain.watches` import, and append:

```python
def upkeep_due(
    watches: Iterable[CalendarWatch], registrations: Iterable[WatchRegistration]
) -> datetime | None:
    """When upkeep next has work for one User's watches; None when nothing is planned."""
    retries = (watch.retry_at for watch in watches)
    moments = [moment for moment in retries if moment is not None]
    moments.extend(moment for registration in registrations for moment in _due(registration))
    return min(moments, default=None)


def _due(registration: WatchRegistration) -> tuple[datetime, ...]:
    """A creation deadline, a renewal asked for or planned, or the end of the registration, after
    which upkeep deletes it (`WatchRegistration.gone`)."""
    if registration.state is RegistrationState.CREATING:
        return (registration.created_at + CREATION_DEADLINE,)
    if registration.state is RegistrationState.LIVE:
        asked, planned, ends = (
            registration.renew_requested_at,
            registration.renew_at,
            registration.expires_at,
        )
        return tuple(moment for moment in (asked, planned, ends) if moment is not None)
    return (registration.expires_at or registration.requested_until,)
```

In `src/calendar_sync/infrastructure/persistence/installation.py`:

Extend the `application.operations.ports` import with `InstantSyncOwner` and `PendingInstantRun`,
add `UserState` to the `domain.access` import, and add:

```python
from calendar_sync.domain.watches import CalendarWatch, WatchRegistration
from calendar_sync.infrastructure.persistence.watches import (
    registration_from_row,
    request_from_row,
    upkeep_due,
    watch_from_row,
)
```

In `class SqliteInstallationUnitOfWork`, after `status_records`, add:

```python
def instant_sync_owners(self) -> Sequence[InstantSyncOwner]:
    assert self._connection is not None
    due = _upkeep_due(self._connection)
    rows = self._connection.execute(
        """
        SELECT id, state, instant_sync FROM users
        WHERE EXISTS (
            SELECT 1 FROM sync_rules
            WHERE sync_rules.user_id = users.id AND sync_rules.state = ?
        ) OR EXISTS (
            SELECT 1 FROM calendar_watches WHERE calendar_watches.user_id = users.id
        )
        ORDER BY id
        """,
        (SyncRuleState.ENABLED.value,),
    ).fetchall()
    return tuple(
        InstantSyncOwner(
            UserId(str(row["id"])),
            wanted=bool(row["instant_sync"]),
            disabled=row["state"] == UserState.DISABLED.value,
            next_due=due.get(str(row["id"])),
        )
        for row in rows
    )


def pending_instant_runs(self) -> Sequence[PendingInstantRun]:
    assert self._connection is not None
    rows = self._connection.execute(
        """
        SELECT sync_rules.*, outcome.last_full_succeeded_at,
            outcome.succeeded AS last_succeeded, request.rule_id, request.requested_seq,
            request.handled_seq, request.first_requested_at, request.last_requested_at,
            request.last_run_at
        FROM instant_sync_requests request
        JOIN sync_rules
            ON sync_rules.id = request.rule_id AND sync_rules.user_id = request.user_id
        JOIN users ON users.id = sync_rules.user_id AND users.state = 'active'
        LEFT JOIN rule_run_outcomes outcome
            ON outcome.rule_id = sync_rules.id AND outcome.kind = 'sync'
        WHERE sync_rules.state = ? AND request.requested_seq > request.handled_seq
        ORDER BY sync_rules.user_id, sync_rules.id
        """,
        (SyncRuleState.ENABLED.value,),
    ).fetchall()
    return tuple(
        PendingInstantRun(
            ScheduledRule(
                UserId(str(row["user_id"])),
                rule_from_row(row),
                optional_time(row["last_full_succeeded_at"]),
            ),
            request_from_row(row),
            last_run_failed=row["last_succeeded"] == 0,
        )
        for row in rows
    )
```

After `_USERS_PER_QUERY`, add:

```python
def _upkeep_due(connection: sqlite3.Connection) -> dict[str, datetime | None]:
    """When upkeep next has work for each User with a watch."""
    watches: dict[str, list[CalendarWatch]] = {}
    for row in connection.execute("SELECT * FROM calendar_watches"):
        watches.setdefault(str(row["user_id"]), []).append(watch_from_row(row))
    registrations: dict[str, list[WatchRegistration]] = {}
    for row in connection.execute("SELECT * FROM watch_registrations"):
        registrations.setdefault(str(row["user_id"]), []).append(registration_from_row(row))
    return {user: upkeep_due(kept, registrations.get(user, ())) for user, kept in watches.items()}
```

In `src/calendar_sync/infrastructure/persistence/memory.py`, in `class MemoryDatabase` after the
`disabled` field, add:

```python
    instant_sync_off: set[UserId] = field(default_factory=set)
    """Users who turned Instant Sync off; like `disabled`, kept as SQLite's users table keeps it."""
```

In `src/calendar_sync/infrastructure/persistence/memory_installation.py`:

Change `from collections.abc import Collection, Sequence` to
`from collections.abc import Collection, Iterator, Sequence`, extend the
`application.operations.ports` import with `InstantSyncOwner` and `PendingInstantRun`, and add
`from calendar_sync.infrastructure.persistence.watches import upkeep_due`.

In `class InMemoryInstallationUnitOfWork`, after `status_records`, add:

```python
def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
    database = self._database
    return tuple(
        InstantSyncOwner(
            owner,
            wanted=owner not in database.instant_sync_off,
            disabled=owner in database.disabled,
            next_due=upkeep_due(state.watches.values(), state.registrations.values()),
        )
        for owner, state in sorted(database.partitions.items(), key=lambda item: item[0].value)
        if state.watches
        or any(rule.state is SyncRuleState.ENABLED for rule in state.rules.values())
    )


def pending_instant_runs(self) -> tuple[PendingInstantRun, ...]:
    return tuple(
        run
        for owner, state in sorted(
            self._database.partitions.items(), key=lambda item: item[0].value
        )
        if owner not in self._database.disabled
        for run in _pending_runs(owner, state)
    )
```

After `_last_full_sync`, add:

```python
def _pending_runs(owner: UserId, state: MemoryState) -> Iterator[PendingInstantRun]:
    for rule_id, request in sorted(state.instant_requests.items(), key=lambda item: item[0].value):
        rule = state.rules.get(rule_id)
        if rule is None or rule.state is not SyncRuleState.ENABLED:
            continue
        if request.requested_seq <= request.handled_seq:
            continue
        outcome = state.outcomes.get((rule_id, RunKind.SYNC))
        yield PendingInstantRun(
            ScheduledRule(owner, rule, _last_full_sync(state, rule_id)),
            request,
            last_run_failed=outcome is not None and not outcome.succeeded,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py tests/application/test_scheduled_pass.py tests/adapters/test_user_isolation_schema.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/operations/ports.py \
  src/calendar_sync/infrastructure/persistence/watches.py \
  src/calendar_sync/infrastructure/persistence/installation.py \
  src/calendar_sync/infrastructure/persistence/memory.py \
  src/calendar_sync/infrastructure/persistence/memory_installation.py \
  tests/contracts/persistence.py tests/adapters/test_persistence_contract.py
git commit -m "Read across Users who needs watch upkeep and which rules wait for an instant run

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The User's Instant Sync preference

**Files:**
- Modify: `src/calendar_sync/domain/access.py` (`User.instant_sync: bool = True`)
- Modify: `src/calendar_sync/application/identity/ports.py` (`UserDirectory.set_instant_sync`)
- Modify: `src/calendar_sync/application/identity/sign_in.py` (`SetInstantSync`)
- Modify: `src/calendar_sync/infrastructure/persistence/users.py` (read, insert, and write `instant_sync`)
- Modify: `tests/identity_fakes.py` (`MemoryUsers.set_instant_sync`)
- Test: `tests/adapters/test_users_store.py`, `tests/application/test_identity.py`

**Interfaces:**
- Consumes: the `users.instant_sync` column from Task 5
- Produces:
  - `User.instant_sync: bool = True`
  - `UserDirectory.set_instant_sync(user_id: UserId, wanted: bool) -> None`
  - `SetInstantSync(users: UserDirectory).execute(user_id: UserId, wanted: bool) -> User`

- [ ] **Step 1: Write the failing test**

Append to `tests/adapters/test_users_store.py`, after
`test_the_last_administrator_is_deleted_only_as_the_last_user`:

```python
def test_a_users_instant_sync_choice_is_kept_without_touching_role_or_state(
    directory: SqliteUserDirectory | MemoryUsers,
) -> None:
    directory.add(FIRST, "hash-1")
    directory.add(replace(SECOND, instant_sync=False), "hash-2")
    # An Installation Administrator disables the User after the Web UI read them.
    directory.set_state(SECOND.id, UserState.DISABLED)

    directory.set_instant_sync(SECOND.id, True)
    directory.set_instant_sync(FIRST.id, False)
    directory.set_instant_sync(UserId("missing"), False)

    assert directory.get(FIRST.id) == replace(FIRST, instant_sync=False)
    assert directory.get(SECOND.id) == replace(SECOND, state=UserState.DISABLED)
    assert directory.count() == 2


def test_a_new_user_wants_instant_sync(tmp_path: Path) -> None:
    users = _users(tmp_path)
    users.add(FIRST, "hash-1")

    stored = users.get(FIRST.id)

    assert stored is not None
    assert stored.instant_sync
```

In `tests/application/test_identity.py`, add `SetInstantSync` to the `sign_in` import, and after
`test_choosing_incident_emails_never_restores_a_role_or_state_changed_meanwhile` add:

```python
def test_choosing_instant_sync_never_restores_a_role_or_state_changed_meanwhile() -> None:
    users = DemotedAfterReading()
    users.add(
        User(
            UserId("admin"),
            "admin@example.test",
            Role.INSTALLATION_ADMINISTRATOR,
            UserState.ACTIVE,
            NOW,
        ),
        f"hashed:{PASSWORD}",
    )

    changed = SetInstantSync(users).execute(UserId("admin"), wanted=False)

    stored = users.users[UserId("admin")]
    assert (stored.instant_sync, stored.role, stored.state) == (
        False,
        Role.USER,
        UserState.DISABLED,
    )
    assert changed == stored


def test_choosing_instant_sync_needs_a_user_who_still_exists() -> None:
    with pytest.raises(IncorrectCredentials):
        SetInstantSync(MemoryUsers()).execute(UserId("gone"), wanted=True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_users_store.py tests/application/test_identity.py -q`
Expected: FAIL (`ImportError: cannot import name 'SetInstantSync'`; `TypeError: ... unexpected keyword argument 'instant_sync'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/domain/access.py`, in `class User`, after the `notify_by_email` field and
its docstring, add:

```python
    instant_sync: bool = True
    """Whether their rules run soon after a change is reported, where their Plan and the
    installation allow it."""
```

In `src/calendar_sync/application/identity/ports.py`, in `class UserDirectory`, after
`set_notification_email`, add:

```python
    def set_instant_sync(self, user_id: UserId, wanted: bool) -> None:
        """Change only whether a User wants Instant Sync."""
        ...
```

In `src/calendar_sync/application/identity/sign_in.py`, after `class SetNotificationEmail`, add:

```python
@dataclass(slots=True)
class SetInstantSync:
    """Whether the signed-in User's rules run soon after a change is reported."""

    users: UserDirectory

    def execute(self, user_id: UserId, wanted: bool) -> User:
        _existing(self.users, user_id)
        self.users.set_instant_sync(user_id, wanted)
        return _existing(self.users, user_id)
```

In `src/calendar_sync/infrastructure/persistence/users.py`:

Replace `_COLUMNS` with:

```python
_COLUMNS = (
    "id, email, role, state, language, notify_by_email, instant_sync, created_at, last_sign_in_at"
)
```

After `set_notification_email`, add:

```python
    def set_instant_sync(self, user_id: UserId, wanted: bool) -> None:
        with transaction(self._database_path) as connection:
            connection.execute(
                "UPDATE users SET instant_sync = ? WHERE id = ?", (int(wanted), user_id.value)
            )
```

Replace the body of `insert_user`'s `connection.execute` call with:

```python
        connection.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, state, language, notify_by_email, instant_sync,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id.value,
                user.email,
                password_hash,
                user.role.value,
                user.state.value,
                user.language,
                int(user.notify_by_email),
                int(user.instant_sync),
                user.created_at.isoformat(),
            ),
        )
```

In `_user`, after `notify_by_email=bool(row["notify_by_email"]),`, add:

```python
instant_sync = (bool(row["instant_sync"]),)
```

In `tests/identity_fakes.py`, in `class MemoryUsers`, after `set_notification_email`, add:

```python
    def set_instant_sync(self, user_id: UserId, wanted: bool) -> None:
        if user_id in self.users:
            self.users[user_id] = replace(self.users[user_id], instant_sync=wanted)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_users_store.py tests/application/test_identity.py tests/adapters/test_identity_api.py tests/adapters/test_users_api.py tests/test_provider_neutrality.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain/access.py src/calendar_sync/application/identity/ports.py \
  src/calendar_sync/application/identity/sign_in.py \
  src/calendar_sync/infrastructure/persistence/users.py tests/identity_fakes.py \
  tests/adapters/test_users_store.py tests/application/test_identity.py
git commit -m "Let each User choose whether their rules use Instant Sync

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 10: Google watcher and notice reader

**Files:**
- Create: `src/calendar_sync/infrastructure/watch_failures.py`
- Create: `src/calendar_sync/infrastructure/google/watches.py`
- Modify: `src/calendar_sync/infrastructure/google/provider.py` (extract `send` and `google_failure`; rename `_status_code` to `status_code`)
- Modify: `pyproject.toml` (add `calendar_sync.infrastructure.watch_failures` to the provider-neutral import contract)
- Test: `tests/adapters/shared/test_watch_failures.py`
- Test: `tests/adapters/google/test_watches.py`

**Interfaces:**
- Consumes: `Receipt`, `WatchFailure(kind, detail, retry_after_seconds=None, failure=None)`, `WatchFailureKind`, `NoticeRequest(headers, query, body)`, `NoticeKind`, `WatchNotice(registration_id, token, handle, kind)`, `MalformedNotice`, `notice_address(public_address, provider_slug, registration_id)` from `application/sync/watch_ports.py` (Task 3); `WatchScope.calendar(calendar_id)`, `WatchScope.account()`, `WatchRegistration`, `WatchRegistrationId`, `CalendarWatchId`, `RegistrationState` from `domain/watches.py` (Tasks 1-2).
- Produces:
  - `calendar_sync.infrastructure.watch_failures.watch_failure(failure: ProviderFailure) -> WatchFailure`
  - `calendar_sync.infrastructure.watch_failures.ACCOUNT_UNAVAILABLE` (the tuple `(ConnectedAccountNotFound, ConnectedAccountDisconnected)`) and `account_unavailable() -> WatchFailure` (`UNSUPPORTED`, detail naming no account)
  - `calendar_sync.infrastructure.google.watches.GoogleCalendarWatcher(service_for: GoogleServiceFactory, clock: Clock, timer: Callable[[], float] = time.monotonic)` implementing `CalendarWatcher`
  - `calendar_sync.infrastructure.google.watches.GoogleNoticeReader()` implementing `NoticeReader`
  - `calendar_sync.infrastructure.google.provider.send(operation: str, request: Any, timer: Callable[[], float]) -> Any`
  - `calendar_sync.infrastructure.google.provider.google_failure(error: Exception, account: ConnectedAccountId, *, attempted_at: datetime, now: datetime, event_scoped: bool = False) -> ProviderFailure`
  - `calendar_sync.infrastructure.google.provider.status_code(error: Exception) -> int | None`

- [ ] **Step 1: Write the failing tests**

`tests/adapters/shared/test_watch_failures.py`:

```python
"""A provider failure met while watching becomes the failure Instant Sync's upkeep acts on: only a
refusal of the account's credentials lapses it, and no provider text is kept (ADR 0036)."""

import pytest

from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.watch_ports import WatchFailureKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.infrastructure.watch_failures import account_unavailable, watch_failure


def failure(
    kind: ProviderFailureKind, cause: Cause | None = None, retry_after: int | None = None
) -> ProviderFailure:
    return ProviderFailure(
        kind,
        "private-marker said no",
        retry_after,
        cause=cause,
        provider_label="Example Calendar",
    )


@pytest.mark.parametrize(
    ("provider_failure", "kind"),
    [
        (
            failure(ProviderFailureKind.AUTHENTICATION, Cause.ACCESS_REVOKED),
            WatchFailureKind.UNAUTHORIZED,
        ),
        (
            failure(ProviderFailureKind.AUTHORIZATION, Cause.ACCESS_REVOKED),
            WatchFailureKind.UNAUTHORIZED,
        ),
        # A bare refusal may concern watching this calendar alone: it never lapses the account.
        (failure(ProviderFailureKind.AUTHORIZATION, Cause.UNKNOWN), WatchFailureKind.UNSUPPORTED),
        (
            failure(ProviderFailureKind.PERMANENT, Cause.CALENDAR_FORBIDDEN),
            WatchFailureKind.UNSUPPORTED,
        ),
        (
            failure(ProviderFailureKind.RATE_LIMIT, Cause.RATE_LIMITED, 30),
            WatchFailureKind.RATE_LIMITED,
        ),
        (failure(ProviderFailureKind.TEMPORARY, Cause.TEMPORARY), WatchFailureKind.TEMPORARY),
    ],
)
def test_a_provider_failure_is_classed_for_upkeep_in_calendar_ghosts_words(
    provider_failure: ProviderFailure, kind: WatchFailureKind
) -> None:
    watched = watch_failure(provider_failure)

    assert watched.kind is kind
    assert watched.detail.startswith("Example Calendar ")
    assert "private-marker" not in watched.detail


def test_only_a_refusal_of_credentials_carries_the_failure_that_lapses_the_account() -> None:
    refused = failure(ProviderFailureKind.AUTHENTICATION, Cause.ACCESS_REVOKED)

    assert watch_failure(refused).failure is refused
    assert watch_failure(failure(ProviderFailureKind.PERMANENT)).failure is None
    assert watch_failure(failure(ProviderFailureKind.TEMPORARY)).failure is None


def test_a_rate_limit_keeps_the_providers_retry_after() -> None:
    limited = watch_failure(failure(ProviderFailureKind.RATE_LIMIT, Cause.RATE_LIMITED, 30))

    assert limited.retry_after_seconds == 30


def test_an_unnamed_provider_is_named_neutrally() -> None:
    unnamed = ProviderFailure(ProviderFailureKind.TEMPORARY, "private-marker")

    assert watch_failure(unnamed).detail == "The calendar provider is temporarily unavailable"


def test_an_unavailable_account_is_unsupported_and_named_by_nothing() -> None:
    unavailable = account_unavailable()

    assert unavailable.kind is WatchFailureKind.UNSUPPORTED
    assert unavailable.failure is None
    assert "account-" not in unavailable.detail
```

`tests/adapters/google/test_watches.py`:

```python
"""Google push channels: one per calendar, opened under the registration's id and token, never
renewed or adopted, stopped by id and resourceId, and refused without Google's words (ADR 0036)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import CalendarId, ConnectedAccountId
from calendar_sync.domain.watches import (
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from tests.adapters.google.test_provider import FixedClock, request_raising, request_returning
from tests.helpers import NOW, endpoint

ACCOUNT = ConnectedAccountId("account-family")
CALENDAR = endpoint("account-family", "family@example.test")
SCOPE = WatchScope.calendar(CALENDAR.calendar_id)
REGISTRATION = WatchRegistrationId("0123456789abcdef0123456789abcdef")
TOKEN = "synthetic-channel-token"
ADDRESS = notice_address("https://ghost.example.test", "google", REGISTRATION)
UNTIL = NOW + timedelta(days=3)
HANDLE = json.dumps({"channel": REGISTRATION.value, "resource": "resource-1"})


def watcher(service: MagicMock) -> GoogleCalendarWatcher:
    return GoogleCalendarWatcher(lambda _account: service, FixedClock(NOW))


def opened(expiration: datetime = UNTIL, **answer: Any) -> dict[str, Any]:
    """Google's answer to events.watch, which gives the expiry in milliseconds, as a string."""
    return {
        "kind": "api#channel",
        "id": REGISTRATION.value,
        "resourceId": "resource-1",
        "resourceUri": "https://www.googleapis.com/calendar/v3/calendars/family/events",
        "token": TOKEN,
        "expiration": str(round(expiration.timestamp() * 1000)),
        **answer,
    }


def registration(handle: str | None = HANDLE) -> WatchRegistration:
    return WatchRegistration(
        id=REGISTRATION,
        watch_id=CalendarWatchId("watch-1"),
        state=RegistrationState.LIVE,
        address=ADDRESS,
        token_hash="synthetic-hash",
        created_at=NOW,
        requested_until=UNTIL,
        handle=handle,
    )


def register(google: GoogleCalendarWatcher, scope: WatchScope = SCOPE) -> Receipt:
    return google.register(ACCOUNT, scope, REGISTRATION, TOKEN, ADDRESS, UNTIL)


def test_every_calendar_is_watched_on_its_own() -> None:
    google = watcher(MagicMock())

    assert google.scope(CALENDAR) == WatchScope.calendar(CalendarId("family@example.test"))


def test_a_channel_names_the_registration_and_points_at_its_address() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(
        opened(NOW + timedelta(days=2))
    )

    receipt = register(watcher(service))

    service.events.return_value.watch.assert_called_once_with(
        calendarId="family@example.test",
        body={
            "id": REGISTRATION.value,
            "type": "web_hook",
            "address": ADDRESS,
            "token": TOKEN,
            "expiration": round(UNTIL.timestamp() * 1000),
        },
    )
    # Google may shorten a channel's life, so its own expiry is kept. Only its sync notice
    # proves delivery.
    assert receipt == Receipt(HANDLE, NOW + timedelta(days=2), confirmed=False)


def test_a_channel_google_did_not_identify_is_not_recorded() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(opened(resourceId=None))

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


def test_a_scope_wider_than_one_calendar_is_not_watched() -> None:
    service = MagicMock()

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service), WatchScope.account())

    assert raised.value.kind is WatchFailureKind.UNSUPPORTED
    assert service.mock_calls == []


def test_a_channel_is_replaced_rather_than_renewed_and_never_adopted() -> None:
    service = MagicMock()
    google = watcher(service)

    assert google.extend(ACCOUNT, registration(), UNTIL) is None
    assert google.adopt(ACCOUNT, SCOPE, REGISTRATION, ADDRESS) is None
    assert service.mock_calls == []


def test_stopping_a_channel_names_its_id_and_resource() -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_returning({})

    watcher(service).stop(ACCOUNT, registration())

    service.channels.return_value.stop.assert_called_once_with(
        body={"id": REGISTRATION.value, "resourceId": "resource-1"}
    )


@pytest.mark.parametrize("status", [404, 410])
def test_a_channel_already_gone_is_stopped(status: int) -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_raising(status)

    watcher(service).stop(ACCOUNT, registration())


def test_a_channel_without_a_handle_is_left_to_expire() -> None:
    service = MagicMock()

    watcher(service).stop(ACCOUNT, registration(None))

    assert service.mock_calls == []


def test_a_stop_google_could_not_answer_is_reported() -> None:
    service = MagicMock()
    service.channels.return_value.stop.return_value = request_raising(503)

    with pytest.raises(WatchFailure) as raised:
        watcher(service).stop(ACCOUNT, registration())

    assert raised.value.kind is WatchFailureKind.TEMPORARY


@pytest.mark.parametrize(
    ("status", "reason", "kind"),
    [
        (401, None, WatchFailureKind.UNAUTHORIZED),
        (403, "insufficientPermissions", WatchFailureKind.UNAUTHORIZED),
        # A bare refusal may concern this calendar alone, so it never lapses the account.
        (403, None, WatchFailureKind.UNSUPPORTED),
        (403, "forbidden", WatchFailureKind.UNSUPPORTED),
        (403, "rateLimitExceeded", WatchFailureKind.RATE_LIMITED),
        (429, None, WatchFailureKind.RATE_LIMITED),
        (400, "pushNotSupportedForRequestedResource", WatchFailureKind.UNSUPPORTED),
        (400, "push.webhookUrlNotHttps", WatchFailureKind.UNREACHABLE),
        # Google answers 401 when it refuses the address, which is no refusal of the account.
        (401, "push.webhookUrlUnauthorized", WatchFailureKind.UNREACHABLE),
        (400, "somethingNew", WatchFailureKind.UNSUPPORTED),
        (503, None, WatchFailureKind.TEMPORARY),
    ],
)
def test_refusals_are_classed_for_upkeep_without_googles_words(
    status: int, reason: str | None, kind: WatchFailureKind
) -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(status, reason=reason)

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is kind
    assert "synthetic Google" not in raised.value.detail


def test_a_refused_account_lapses_from_when_its_credentials_were_read() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(401)

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    lapse = raised.value.failure
    assert lapse is not None
    assert lapse.account_id == ACCOUNT
    assert lapse.provider is ProviderKind.GOOGLE
    assert lapse.attempted_at == NOW


def test_a_rate_limit_carries_googles_retry_after() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_raising(
        429, headers={"Retry-After": "30"}
    )

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.retry_after_seconds == 30


def test_credentials_google_no_longer_accepts_are_unauthorized() -> None:
    def refused(_account: ConnectedAccountId) -> Any:
        raise RefreshError("invalid_grant: revoked")  # type: ignore[no-untyped-call]

    with pytest.raises(WatchFailure) as raised:
        register(GoogleCalendarWatcher(refused, FixedClock(NOW)))

    assert raised.value.kind is WatchFailureKind.UNAUTHORIZED


def test_a_token_endpoint_google_could_not_reach_is_temporary() -> None:
    def unreachable(_account: ConnectedAccountId) -> Any:
        raise TransportError("connection reset")  # type: ignore[no-untyped-call]

    with pytest.raises(WatchFailure) as raised:
        register(GoogleCalendarWatcher(unreachable, FixedClock(NOW)))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


@pytest.mark.parametrize(
    "gone",
    [
        ConnectedAccountNotFound("connected account account-family does not exist"),
        ConnectedAccountDisconnected("connected account account-family needs reauthorization"),
    ],
)
def test_an_account_without_credentials_is_unsupported_not_temporary(gone: Exception) -> None:
    def unavailable(_account: ConnectedAccountId) -> Any:
        raise gone

    google = GoogleCalendarWatcher(unavailable, FixedClock(NOW))

    for call in (lambda: register(google), lambda: google.stop(ACCOUNT, registration())):
        with pytest.raises(WatchFailure) as raised:
            call()
        assert raised.value.kind is WatchFailureKind.UNSUPPORTED
        assert "account-family" not in raised.value.detail


def test_a_request_that_got_no_answer_is_temporary() -> None:
    request = MagicMock()
    request.execute.side_effect = OSError("network down")
    service = MagicMock()
    service.events.return_value.watch.return_value = request

    with pytest.raises(WatchFailure) as raised:
        register(watcher(service))

    assert raised.value.kind is WatchFailureKind.TEMPORARY


def test_watch_calls_count_toward_provider_calls() -> None:
    service = MagicMock()
    service.events.return_value.watch.return_value = request_returning(opened())
    service.channels.return_value.stop.return_value = request_returning({})
    google = watcher(service)

    with ContextProviderCallStats().measure() as tally:
        register(google)
        google.stop(ACCOUNT, registration())

    assert tally.providers[ProviderKind.GOOGLE].calls == 2


def notice(headers: dict[str, str]) -> NoticeRequest:
    return NoticeRequest(headers, {}, b"")


def channel_headers(state: str) -> dict[str, str]:
    return {
        "x-goog-channel-id": REGISTRATION.value,
        "x-goog-channel-token": TOKEN,
        "x-goog-resource-id": "resource-1",
        "x-goog-resource-state": state,
        "x-goog-message-number": "1",
    }


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("sync", NoticeKind.STARTED),
        ("exists", NoticeKind.CHANGED),
        ("not_exists", NoticeKind.CHANGED),
    ],
)
def test_each_resource_state_is_a_notice_without_a_handle(state: str, kind: NoticeKind) -> None:
    # The sync notice may arrive before events.watch answers, so no notice names a handle.
    assert GoogleNoticeReader().read(REGISTRATION, notice(channel_headers(state))) == (
        WatchNotice(REGISTRATION, TOKEN, None, kind),
    )


@pytest.mark.parametrize(
    "headers",
    [
        {**channel_headers("exists"), "x-goog-channel-id": "another-channel"},
        {**channel_headers("exists"), "x-goog-channel-token": ""},
        {key: value for key, value in channel_headers("exists").items() if "token" not in key},
        {**channel_headers("exists"), "x-goog-resource-state": "unexpected"},
        {key: value for key, value in channel_headers("exists").items() if "state" not in key},
    ],
)
def test_a_notice_google_would_not_send_is_malformed(headers: dict[str, str]) -> None:
    with pytest.raises(MalformedNotice):
        GoogleNoticeReader().read(REGISTRATION, notice(headers))


def test_google_never_asks_the_address_to_prove_itself() -> None:
    request = NoticeRequest({}, {"validationToken": "opaque"}, b"")

    assert GoogleNoticeReader().validation_token(request) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/shared/test_watch_failures.py tests/adapters/google/test_watches.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.infrastructure.watch_failures'` and `... 'calendar_sync.infrastructure.google.watches'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/infrastructure/watch_failures.py`:

```python
"""Watch call failures, from the provider failure an adapter already translated (ADR 0036).

Watching keeps its own failure classes, apart from a Sync Run's, so a provider that cannot watch
a calendar never stops a rule or lapses an account. Only a refusal of the account's credentials,
which its next Sync Run would meet as well, is `unauthorized`. The detail is Calendar Ghost's own
sentence: a provider's message text can quote the request, so it is never kept.
"""

from __future__ import annotations

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
    ProviderFailure,
)
from calendar_sync.application.sync.watch_ports import WatchFailure, WatchFailureKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.providers import ProviderFailureKind

ACCOUNT_UNAVAILABLE = (ConnectedAccountNotFound, ConnectedAccountDisconnected)
"""What the credential stores raise for an account removed or waiting for reauthorization."""


def account_unavailable() -> WatchFailure:
    """An account whose credentials are gone cannot be watched. Its rules meet the same and its
    owner is told there, so watching only backs off; the detail names no account."""
    return WatchFailure(
        kind=WatchFailureKind.UNSUPPORTED,
        detail="the connected account is no longer available",
    )


def watch_failure(failure: ProviderFailure) -> WatchFailure:
    """`failure`, met while watching, as the failure Instant Sync's upkeep acts on."""
    name = _named(failure)
    if _refuses_credentials(failure):
        return WatchFailure(
            kind=WatchFailureKind.UNAUTHORIZED,
            detail=f"{name} no longer accepts this account's access",
            failure=failure,
        )
    if failure.kind is ProviderFailureKind.RATE_LIMIT:
        return WatchFailure(
            kind=WatchFailureKind.RATE_LIMITED,
            detail=f"{name} is limiting requests",
            retry_after_seconds=failure.retry_after_seconds,
        )
    if failure.kind is ProviderFailureKind.TEMPORARY:
        return WatchFailure(
            kind=WatchFailureKind.TEMPORARY,
            detail=f"{name} is temporarily unavailable",
            retry_after_seconds=failure.retry_after_seconds,
        )
    return WatchFailure(
        kind=WatchFailureKind.UNSUPPORTED, detail=f"{name} cannot watch this calendar"
    )


def _refuses_credentials(failure: ProviderFailure) -> bool:
    """A refusal of the account's credentials or grant. A bare refusal may concern watching one
    calendar only, so it never lapses the account."""
    if failure.kind is ProviderFailureKind.AUTHENTICATION:
        return True
    return (
        failure.kind is ProviderFailureKind.AUTHORIZATION and failure.cause is Cause.ACCESS_REVOKED
    )


def _named(failure: ProviderFailure) -> str:
    name = failure.provider_name
    return name[:1].upper() + name[1:]
```

`src/calendar_sync/infrastructure/google/provider.py`, first rename the status helper everywhere
in the file:

```bash
perl -pi -e 's/\b_status_code\(/status_code(/g' src/calendar_sync/infrastructure/google/provider.py
```

Then replace the body of `GoogleCalendarProvider._call`:

```python
    def _call(self, operation: str, request: Any) -> Any:
        """Send one Google request, tallying and logging it by its operation name alone."""
        return send(operation, request, self._timer)
```

and the body of `GoogleCalendarProvider._failure`:

```python
    def _failure(
        self, error: Exception, account: ConnectedAccountId, *, event_scoped: bool = False
    ) -> ProviderFailure:
        # When the request read the account's credentials tells whether a Reauthorization has
        # replaced them since.
        now = self._clock.now()
        read: dict[ConnectedAccountId, datetime] = self._credentials_read.__dict__.get("at", {})
        return google_failure(
            error, account, attempted_at=read.get(account, now), now=now, event_scoped=event_scoped
        )
```

and add these two module functions directly above `def _provider_failure(`:

```python
def send(operation: str, request: Any, timer: Callable[[], float]) -> Any:
    """Send one Google request, tallying and logging it by its operation name alone."""
    started = timer()
    status: int | None = 200
    rate_limited = False
    try:
        return request.execute()
    except Exception as error:
        status = status_code(error)
        rate_limited = status == 429 or (status == 403 and _is_rate_limit_error(error))
        raise
    finally:
        record_call(
            ProviderKind.GOOGLE,
            operation,
            status,
            timer() - started,
            rate_limited=rate_limited,
        )


def google_failure(
    error: Exception,
    account: ConnectedAccountId,
    *,
    attempted_at: datetime,
    now: datetime,
    event_scoped: bool = False,
) -> ProviderFailure:
    """A Google error as the provider failure the account's request met.

    The account names whose access to renew when Google rejected its credentials, and
    `attempted_at`, when the request read them, tells whether a Reauthorization has replaced them
    since (ADR 0027). `now` turns a Retry-After date into the seconds the retry helper waits. A
    write to one event its calendar just listed or returned names that event alone
    (`event_scoped`).
    """
    return replace(
        _provider_failure(error, now, event_scoped),
        account_id=account,
        provider=ProviderKind.GOOGLE,
        provider_label=GOOGLE.calendar_name,
        attempted_at=attempted_at,
    )
```

The renamed `status_code` keeps its body:

```python
def status_code(error: Exception) -> int | None:
    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    return int(status) if isinstance(status, int) else None
```

`src/calendar_sync/infrastructure/google/watches.py`:

```python
"""Google Calendar push channels: one channel watches one calendar (ADR 0036).

`events.watch` opens a channel whose id is the registration id Calendar Ghost chose. The channel
carries the registration's secret token and delivers to its notice address. Google cannot renew a
channel, only replace it, so `extend` answers None. Stopping one with `channels.stop` needs its id
and Google's `resourceId`, which the handle keeps. A notice is headers only, never event content:
the channel id, its token, and the resource state. The state is `sync` when the channel starts,
and `exists` or `not_exists` after a change.

Sources, checked 2026-10-14:
- Push notifications: https://developers.google.com/workspace/calendar/api/guides/push
- events.watch: https://developers.google.com/workspace/calendar/api/v3/reference/events/watch
- channels.stop: https://developers.google.com/workspace/calendar/api/v3/reference/channels/stop
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
)
from calendar_sync.domain.model import CalendarEndpoint, CalendarId, ConnectedAccountId
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.watches import WatchRegistration, WatchRegistrationId, WatchScope
from calendar_sync.infrastructure.google.causes import http_reasons
from calendar_sync.infrastructure.google.provider import (
    GoogleServiceFactory,
    google_failure,
    send,
    status_code,
)
from calendar_sync.infrastructure.watch_failures import (
    ACCOUNT_UNAVAILABLE,
    account_unavailable,
    watch_failure,
)

# How a watch scope names one calendar (domain/watches.py).
CALENDAR_SCOPE = "calendar:"
# Reasons Google gives when it will not deliver to the notice address: the address is not https,
# or Google does not accept its certificate or domain. Only the installation's administrator can
# fix them, so the address counts as unreachable, never as a refusal of the account.
UNREACHABLE_REASONS = frozenset({"push.webhookUrlNotHttps", "push.webhookUrlUnauthorized"})
# The calendar offers no push channel, as some calendars Google publishes itself do not.
UNSUPPORTED_REASONS = frozenset({"pushNotSupportedForRequestedResource"})
# Answers to channels.stop meaning the channel is already gone.
GONE = frozenset({404, 410})
STATES = {
    "sync": NoticeKind.STARTED,
    "exists": NoticeKind.CHANGED,
    "not_exists": NoticeKind.CHANGED,
}


@dataclass(frozen=True, slots=True)
class _Handle:
    """What stopping a channel needs: its id and the resourceId Google gave it."""

    channel: str
    resource: str

    def encode(self) -> str:
        return json.dumps({"channel": self.channel, "resource": self.resource})

    @classmethod
    def decode(cls, value: str | None) -> _Handle | None:
        try:
            raw = json.loads(value or "")
            return cls(str(raw["channel"]), str(raw["resource"]))
        except (ValueError, KeyError, TypeError):
            return None


class GoogleCalendarWatcher:
    """CalendarWatcher for Google Calendar: one push channel per watched calendar."""

    def __init__(
        self,
        service_for: GoogleServiceFactory,
        clock: Clock,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service_for = service_for
        self._clock = clock
        # Seconds from an arbitrary start, for timing calls; the clock tells wall time.
        self._timer = timer

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        # Google watches any calendar the account can read, one channel each.
        return WatchScope.calendar(calendar.calendar_id)

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        calendar = _calendar_of(scope)
        body = {
            "id": registration_id.value,
            "type": "web_hook",
            "address": address,
            "token": token,
            "expiration": _milliseconds(until),
        }
        started = self._clock.now()
        try:
            request = (
                self._service_for(account).events().watch(calendarId=calendar.value, body=body)
            )
            answer = send("events.watch", request, self._timer)
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        except Exception as error:
            raise self._failure(error, account, started) from error
        return _receipt(answer, registration_id, until)

    def extend(
        self,
        # Google cannot renew a channel: None asks upkeep for a replacement with a new id and
        # token, so nothing here is read.
        account: ConnectedAccountId,  # noqa: ARG002
        registration: WatchRegistration,  # noqa: ARG002
        until: datetime,  # noqa: ARG002
    ) -> datetime | None:
        return None

    def adopt(
        self,
        # Google never refuses a second channel on one calendar, so there is nothing to adopt.
        account: ConnectedAccountId,  # noqa: ARG002
        scope: WatchScope,  # noqa: ARG002
        registration_id: WatchRegistrationId,  # noqa: ARG002
        address: str,  # noqa: ARG002
    ) -> Receipt | None:
        return None

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        handle = _Handle.decode(registration.handle)
        if handle is None:
            # Without Google's resourceId a channel cannot be stopped; it ends at its expiry.
            return
        started = self._clock.now()
        try:
            request = (
                self._service_for(account)
                .channels()
                .stop(body={"id": handle.channel, "resourceId": handle.resource})
            )
            send("channels.stop", request, self._timer)
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        except Exception as error:
            if status_code(error) in GONE:
                return
            raise self._failure(error, account, started) from error

    def _failure(
        self, error: Exception, account: ConnectedAccountId, started: datetime
    ) -> WatchFailure:
        """Google's refusal as a watch failure; `started` is when the call read the account's
        credentials."""
        reasons = http_reasons(error)
        if reasons & UNREACHABLE_REASONS:
            return WatchFailure(
                kind=WatchFailureKind.UNREACHABLE,
                detail="Google Calendar will not deliver notices to this installation's address",
            )
        if reasons & UNSUPPORTED_REASONS:
            return WatchFailure(
                kind=WatchFailureKind.UNSUPPORTED,
                detail="Google Calendar cannot watch this calendar",
            )
        failure = google_failure(error, account, attempted_at=started, now=self._clock.now())
        if failure.kind is ProviderFailureKind.PERMANENT and status_code(error) is None:
            # No answer arrived, as when the network failed: nothing refused the watch.
            return WatchFailure(
                kind=WatchFailureKind.TEMPORARY, detail="Google Calendar could not be reached"
            )
        return watch_failure(failure)


class GoogleNoticeReader:
    """NoticeReader for Google: one notice per request, in its headers."""

    def validation_token(self, request: NoticeRequest) -> str | None:  # noqa: ARG002
        # Google never asks the notice address to prove itself.
        return None

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        headers = request.headers
        if headers.get("x-goog-channel-id") != registration_id.value:
            raise MalformedNotice("the notice names another channel than its address does")
        token = headers.get("x-goog-channel-token")
        kind = STATES.get(headers.get("x-goog-resource-state", ""))
        if not token or kind is None:
            raise MalformedNotice("the notice is not one Google Calendar sends")
        # Google's sync notice may arrive before events.watch answers, so no notice names the
        # handle: the registration id and its token identify the channel.
        return (WatchNotice(registration_id, token, None, kind),)


def _calendar_of(scope: WatchScope) -> CalendarId:
    """The one calendar a scope names; Google watches nothing wider."""
    calendar = scope.key.removeprefix(CALENDAR_SCOPE)
    if calendar == scope.key or not calendar:
        raise WatchFailure(
            kind=WatchFailureKind.UNSUPPORTED,
            detail="Google Calendar watches one calendar at a time",
        )
    return CalendarId(calendar)


def _receipt(
    answer: Mapping[str, Any], registration_id: WatchRegistrationId, until: datetime
) -> Receipt:
    resource = answer.get("resourceId")
    if answer.get("id") != registration_id.value or not isinstance(resource, str) or not resource:
        # Without its resourceId the channel could never be stopped; it ends at its expiry.
        raise WatchFailure(
            kind=WatchFailureKind.TEMPORARY,
            detail="Google Calendar did not identify the channel it opened",
        )
    # Google may shorten what was asked for; only its sync notice proves delivery.
    return Receipt(
        handle=_Handle(registration_id.value, resource).encode(),
        expires_at=_instant(answer.get("expiration")) or until,
    )


def _milliseconds(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def _instant(value: object) -> datetime | None:
    """Google's expiry: milliseconds since the epoch, as a string."""
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
```

`pyproject.toml`, in the contract named "Provider-neutral infrastructure does not depend on one
provider's adapter", add the new module to `source_modules`:

```toml
source_modules = [
  "calendar_sync.infrastructure.oauth",
  "calendar_sync.infrastructure.providers",
  "calendar_sync.infrastructure.provider_calls",
  "calendar_sync.infrastructure.retry_after",
  "calendar_sync.infrastructure.watch_failures",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/shared/test_watch_failures.py tests/adapters/google tests/test_provider_neutrality.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS (the existing Google provider and tally tests confirm that `send`, `google_failure`, and `status_code` kept their behavior)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/infrastructure/watch_failures.py \
  src/calendar_sync/infrastructure/google/watches.py \
  src/calendar_sync/infrastructure/google/provider.py pyproject.toml \
  tests/adapters/shared/test_watch_failures.py tests/adapters/google/test_watches.py
git commit -m "Watch Google calendars through push channels and read their notices

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 11: Outlook watcher and notice reader

**Files:**
- Create: `src/calendar_sync/infrastructure/microsoft/watches.py`
- Modify: `src/calendar_sync/infrastructure/microsoft/graph.py` (`GraphRefusal.endpoint_refused`, read from the message in `graph_refusal` and never kept)
- Modify: `src/calendar_sync/infrastructure/microsoft/provider.py` (extract `refusal_failure`)
- Create: `tests/fake_graph_subscriptions.py`
- Modify: `tests/fake_microsoft_graph_api.py` (`FakeCalendar.owner`; serve `/subscriptions`, `GET /me/calendar`, `GET /me/calendars/{id}`)
- Test: `tests/adapters/microsoft/test_watches.py`

**Interfaces:**
- Consumes: `Receipt`, `WatchFailure`, `WatchFailureKind`, `NoticeRequest`, `NoticeKind`, `WatchNotice`, `MalformedNotice`, `notice_address` (Task 3); `WatchScope`, `WatchRegistration`, `WatchRegistrationId`, `CalendarWatchId`, `RegistrationState` (Tasks 1-2); `watch_failure(failure: ProviderFailure) -> WatchFailure`, `ACCOUNT_UNAVAILABLE`, `account_unavailable() -> WatchFailure` (Task 10).
- Produces:
  - `calendar_sync.infrastructure.microsoft.watches.OutlookCalendarWatcher(tokens: AccessTokens, graph: GraphHttp, clock: Clock)` implementing `CalendarWatcher`
  - `calendar_sync.infrastructure.microsoft.watches.OutlookNoticeReader()` implementing `NoticeReader`
  - `calendar_sync.infrastructure.microsoft.provider.refusal_failure(error: GraphRefusal | TokenRefusal, account: ConnectedAccountId, *, attempted_at: datetime, now: datetime, event_scoped: bool = False) -> ProviderFailure`
  - `GraphRefusal.endpoint_refused: bool = False`
  - Test fake `tests.fake_graph_subscriptions.FakeGraphSubscriptions` with `stored`, `reachable`, `seed(...)`; `FakeMicrosoftGraph.subscriptions`

- [ ] **Step 1: Write the failing tests and the fake they drive**

`tests/fake_graph_subscriptions.py`:

```python
"""Graph subscriptions in fake mailboxes, as Graph v1.0 documents them (ADR 0036).

A subscription belongs to the mailbox that created it, which alone lists, renews, or deletes it.
Creating one first validates its notification and lifecycle URLs, as Graph does before it answers
201. A test makes an address unreachable through `reachable`. A second subscription of a mailbox
with the same resource and change types is refused with 409. Listings withhold `clientState`, as
Graph does. Graph documents the statuses and the messages used here; the error codes are
stand-ins, since the adapter reads only the status and whether a 400 says the URL failed
validation.

Sources:
- https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
Json = dict[str, Any]

PAGE = 2
"""Small, so a listing of more than two subscriptions is answered in pages."""
# Graph's message for an address that did not answer its validation request, with something
# private that must never be kept.
UNVALIDATED = (
    "Subscription validation request failed. Notification endpoint must respond with 200 OK to "
    "validation request. private-marker"
)


@dataclass
class StoredSubscription:
    id: str
    mailbox: str
    resource: str
    change_type: str
    notification_url: str
    lifecycle_url: str | None
    client_state: str | None
    expires: str

    def answer(self, *, with_state: bool) -> Json:
        return {
            "id": self.id,
            "resource": self.resource,
            "changeType": self.change_type,
            "notificationUrl": self.notification_url,
            "lifecycleNotificationUrl": self.lifecycle_url,
            "expirationDateTime": self.expires,
            "clientState": self.client_state if with_state else None,
        }


class FakeGraphSubscriptions:
    """`/subscriptions` for every mailbox of a FakeMicrosoftGraph."""

    def __init__(self) -> None:
        self.stored: dict[str, StoredSubscription] = {}
        self.reachable: Callable[[str], bool] = lambda _address: True
        self._next = 1

    def seed(
        self,
        mailbox: str,
        notification_url: str,
        *,
        resource: str = "me/events",
        change_type: str = "created,updated,deleted",
        expires: str = "2026-09-02T10:00:00Z",
    ) -> str:
        """A subscription made earlier, by another registration or another application."""
        subscription = StoredSubscription(
            self._new_id(),
            mailbox,
            resource,
            change_type,
            notification_url,
            notification_url,
            "someone-elses-state",
            expires,
        )
        self.stored[subscription.id] = subscription
        return subscription.id

    def serve(self, request: httpx.Request, mailbox: str, path: str) -> httpx.Response:
        rest = path.removeprefix("/subscriptions").strip("/")
        if not rest:
            if request.method == "POST":
                return self._create(mailbox, _json(request))
            return self._list(mailbox, int(request.url.params.get("page", "0")))
        found = self.stored.get(rest)
        if found is None or found.mailbox != mailbox:
            return _error(404, "ResourceNotFound", "private-marker not found")
        if request.method == "PATCH":
            found.expires = str(_json(request)["expirationDateTime"])
            return httpx.Response(200, json=found.answer(with_state=False))
        if request.method == "DELETE":
            del self.stored[rest]
            return httpx.Response(204)
        return httpx.Response(200, json=found.answer(with_state=False))

    def _create(self, mailbox: str, body: Json) -> httpx.Response:
        url = str(body.get("notificationUrl", ""))
        lifecycle = body.get("lifecycleNotificationUrl")
        addresses = [url, *([lifecycle] if isinstance(lifecycle, str) else [])]
        if not all(self.reachable(address) for address in addresses):
            return _error(400, "ValidationError", UNVALIDATED)
        resource, change_type = str(body["resource"]), str(body["changeType"])
        for existing in self.stored.values():
            if (
                existing.mailbox == mailbox
                and existing.resource.lower() == resource.lower()
                and existing.change_type == change_type
            ):
                return _error(
                    409,
                    "Conflict",
                    f"Subscription Id {existing.id} already exists for the requested combination",
                )
        subscription = StoredSubscription(
            self._new_id(),
            mailbox,
            resource,
            change_type,
            url,
            lifecycle if isinstance(lifecycle, str) else None,
            str(body.get("clientState")),
            str(body["expirationDateTime"]),
        )
        self.stored[subscription.id] = subscription
        return httpx.Response(201, json=subscription.answer(with_state=True))

    def _list(self, mailbox: str, page: int) -> httpx.Response:
        mine = [s for s in self.stored.values() if s.mailbox == mailbox]
        body: Json = {
            "value": [s.answer(with_state=False) for s in mine[page * PAGE : (page + 1) * PAGE]]
        }
        if (page + 1) * PAGE < len(mine):
            body["@odata.nextLink"] = f"{GRAPH}/subscriptions?page={page + 1}"
        return httpx.Response(200, json=body)

    def _new_id(self) -> str:
        identifier = f"subscription-{self._next}"
        self._next += 1
        return identifier


def _json(request: httpx.Request) -> Json:
    body = json.loads(request.content or b"{}")
    assert isinstance(body, dict)
    return body


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})
```

`tests/fake_microsoft_graph_api.py` changes:

```python
# import, beside FakeGraphEvents
from tests.fake_graph_subscriptions import FakeGraphSubscriptions


@dataclass
class FakeCalendar:
    id: str
    name: str | None
    can_edit: bool = True
    default: bool = False
    owner: str | None = None
    """The address of the mailbox it belongs to; None for the mailbox showing it. Another
    mailbox's calendar is one it shares."""
```

In `FakeMicrosoftGraph.__init__`, after `self.events = FakeGraphEvents()`:

```python
        self.subscriptions = FakeGraphSubscriptions()
```

In `FakeMicrosoftGraph.graph`, after the `/me/calendars` branch and before `calendar = next(...)`:

```python
        if path == "/subscriptions" or path.startswith("/subscriptions/"):
            return self.subscriptions.serve(request, mailbox.address, path)
        if request.method == "GET" and path == "/me/calendar":
            default = next((c for c in mailbox.calendars if c.default), mailbox.calendars[0])
            return httpx.Response(200, json=_calendar_owner(mailbox, default))
        exact = next((c for c in mailbox.calendars if path == f"/me/calendars/{c.id}"), None)
        if request.method == "GET" and exact is not None:
            return httpx.Response(200, json=_calendar_owner(mailbox, exact))
```

And a module function beside `_graph_error`:

```python
def _calendar_owner(mailbox: FakeMailbox, calendar: FakeCalendar) -> Json:
    """A calendar as `$select=owner` reads it: the address of the mailbox it belongs to."""
    return {
        "id": calendar.id,
        "owner": {"name": mailbox.display_name, "address": calendar.owner or mailbox.address},
    }
```

`tests/adapters/microsoft/test_watches.py`:

```python
"""Outlook watches through Graph subscriptions: one per mailbox, only for calendars it owns,
renewed in place, adopted only by their exact address, never deleted unidentified, and refused
without Graph's words (ADR 0036)."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import pytest

from calendar_sync.application.sync.errors import (
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
    notice_address,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.domain.watches import (
    CalendarWatchId,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
)
from calendar_sync.infrastructure.microsoft.graph import GraphHttp
from calendar_sync.infrastructure.microsoft.watches import (
    OutlookCalendarWatcher,
    OutlookNoticeReader,
)
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, IssuedTokens
from tests.fake_microsoft_graph_api import FakeCalendar, FakeMicrosoftGraph, Refusal, graph_error
from tests.helpers import NOW, endpoint

ACCOUNT = ConnectedAccountId("personal-account")
MAILBOX = MAILBOXES["personal-account"][0]
OWN = endpoint("personal-account", "personal-calendar")
SHARED = endpoint("personal-account", "shared-calendar")
OURS = WatchRegistrationId("0123456789abcdef0123456789abcdef")
THEIRS = WatchRegistrationId("fedcba9876543210fedcba9876543210")
PUBLIC = "https://ghost.example.test"
ADDRESS = notice_address(PUBLIC, "microsoft", OURS)
OTHER_ADDRESS = notice_address(PUBLIC, "microsoft", THEIRS)
TOKEN = "synthetic-client-state"
UNTIL = NOW + timedelta(days=3)


@dataclass
class MovingClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


def outlook(
    clock: MovingClock | None = None,
) -> tuple[OutlookCalendarWatcher, FakeMicrosoftGraph]:
    graph = FakeMicrosoftGraph()
    tokens = {}
    for account, (address, calendar) in MAILBOXES.items():
        graph.mailbox(
            address,
            calendars=[
                FakeCalendar(calendar, calendar.title(), default=True),
                FakeCalendar(
                    "shared-calendar", "Colleague", can_edit=False, owner="colleague@example.test"
                ),
            ],
        )
        tokens[account] = graph.issue(address)["access_token"]
    watcher = OutlookCalendarWatcher(
        IssuedTokens(tokens), GraphHttp(graph.client()), clock or MovingClock()
    )
    return watcher, graph


def register(
    watcher: OutlookCalendarWatcher,
    registration_id: WatchRegistrationId = OURS,
    address: str = ADDRESS,
    until: datetime = UNTIL,
) -> Receipt:
    return watcher.register(ACCOUNT, WatchScope.account(), registration_id, TOKEN, address, until)


def registration(
    handle: str | None, registration_id: WatchRegistrationId = OURS, address: str = ADDRESS
) -> WatchRegistration:
    return WatchRegistration(
        id=registration_id,
        watch_id=CalendarWatchId("watch-1"),
        state=RegistrationState.LIVE,
        address=address,
        token_hash="synthetic-hash",
        created_at=NOW,
        requested_until=UNTIL,
        handle=handle,
    )


def sent(graph: FakeMicrosoftGraph, method: str, path: str) -> list[httpx.Request]:
    return [r for r in graph.requests if r.method == method and r.url.path == f"/v1.0{path}"]


# Scope ------------------------------------------------------------------------------------


def test_a_calendar_the_mailbox_owns_is_watched_with_the_whole_mailbox() -> None:
    watcher, _ = outlook()

    assert watcher.scope(OWN) == WatchScope.account()


def test_a_calendar_another_mailbox_shares_cannot_be_watched() -> None:
    watcher, _ = outlook()

    assert watcher.scope(SHARED) is None


def test_a_calendar_that_is_gone_cannot_be_watched() -> None:
    watcher, _ = outlook()

    assert watcher.scope(endpoint("personal-account", "deleted-calendar")) is None


def test_who_owns_a_calendar_is_read_once_per_upkeep_cycle() -> None:
    clock = MovingClock()
    watcher, graph = outlook(clock)

    watcher.scope(OWN)
    watcher.scope(OWN)

    assert len(sent(graph, "GET", "/me/calendar")) == 1
    assert len(sent(graph, "GET", "/me/calendars/personal-calendar")) == 1
    clock.moment += timedelta(minutes=5)
    watcher.scope(OWN)
    assert len(sent(graph, "GET", "/me/calendars/personal-calendar")) == 2


def test_a_cold_scope_is_measured_as_two_provider_calls_and_a_warm_one_as_none() -> None:
    watcher, _ = outlook()

    with ContextProviderCallStats().measure() as cold:
        watcher.scope(OWN)
    with ContextProviderCallStats().measure() as warm:
        watcher.scope(OWN)

    assert cold.calls == 2
    assert cold.providers[ProviderKind.OUTLOOK].calls == 2
    assert warm.calls == 0


# Subscriptions ----------------------------------------------------------------------------


def test_a_subscription_covers_the_mailbox_and_proves_delivery() -> None:
    watcher, graph = outlook()

    receipt = register(watcher)

    (created,) = graph.subscriptions.stored.values()
    # Graph validated the address before it answered, so delivery is proven.
    assert receipt == Receipt(created.id, UNTIL, confirmed=True)
    assert json.loads(sent(graph, "POST", "/subscriptions")[0].content) == {
        "changeType": "created,updated,deleted",
        "notificationUrl": ADDRESS,
        "lifecycleNotificationUrl": ADDRESS,
        "resource": "me/events",
        "expirationDateTime": "2026-09-02T10:00:00Z",
        "clientState": TOKEN,
    }


def test_a_subscription_asks_for_no_longer_than_graph_allows() -> None:
    watcher, graph = outlook()

    receipt = register(watcher, until=NOW + timedelta(days=30))

    assert receipt.expires_at == NOW + timedelta(minutes=10_075)
    body = json.loads(sent(graph, "POST", "/subscriptions")[0].content)
    assert body["expirationDateTime"] == "2026-09-06T09:55:00Z"


def test_only_the_whole_mailbox_at_an_address_naming_the_registration_is_subscribed() -> None:
    watcher, graph = outlook()

    for scope, address in (
        (WatchScope.calendar(OWN.calendar_id), ADDRESS),
        (WatchScope.account(), OTHER_ADDRESS),
    ):
        with pytest.raises(WatchFailure) as raised:
            watcher.register(ACCOUNT, scope, OURS, TOKEN, address, UNTIL)
        assert raised.value.kind is WatchFailureKind.UNSUPPORTED
    assert sent(graph, "POST", "/subscriptions") == []


def test_an_address_graph_cannot_reach_is_unreachable_and_keeps_none_of_graphs_words() -> None:
    watcher, graph = outlook()
    graph.subscriptions.reachable = lambda _address: False

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.kind is WatchFailureKind.UNREACHABLE
    assert "private-marker" not in raised.value.detail
    assert "validation request" not in raised.value.detail
    assert graph.subscriptions.stored == {}


def test_a_second_subscription_is_a_duplicate_adopted_only_by_its_exact_address() -> None:
    watcher, graph = outlook()
    first = register(watcher)

    with pytest.raises(WatchFailure) as raised:
        register(watcher, THEIRS, OTHER_ADDRESS)

    assert raised.value.kind is WatchFailureKind.DUPLICATE
    assert first.handle not in raised.value.detail
    # The subscription holding the mailbox belongs to another registration: never adopted.
    assert watcher.adopt(ACCOUNT, WatchScope.account(), THEIRS, OTHER_ADDRESS) is None
    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS) == first
    assert not any(request.method == "DELETE" for request in graph.requests)
    assert list(graph.subscriptions.stored) == [first.handle]


def test_adoption_never_matches_by_resource_or_address_alone() -> None:
    watcher, graph = outlook()
    graph.subscriptions.seed(MAILBOX, OTHER_ADDRESS)
    graph.subscriptions.seed(MAILBOX, ADDRESS, resource="me/mailFolders('Inbox')/messages")

    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS) is None
    # An address that does not name the registration is never looked for.
    assert watcher.adopt(ACCOUNT, WatchScope.account(), OURS, OTHER_ADDRESS) is None


def test_adoption_reads_every_page_of_the_mailboxs_subscriptions() -> None:
    watcher, graph = outlook()
    for number in range(3):
        other = WatchRegistrationId(f"{number:032x}")
        graph.subscriptions.seed(MAILBOX, notice_address(PUBLIC, "microsoft", other))
    ours = graph.subscriptions.seed(MAILBOX, ADDRESS)

    with ContextProviderCallStats().measure() as tally:
        adopted = watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS)

    assert adopted == Receipt(ours, UNTIL, confirmed=True)
    assert len(sent(graph, "GET", "/subscriptions")) == 2
    # Upkeep spends what it measured, so every page counts.
    assert tally.calls == 2


def test_a_subscription_is_renewed_in_place() -> None:
    watcher, graph = outlook()
    receipt = register(watcher)

    renewed = watcher.extend(ACCOUNT, registration(receipt.handle), NOW + timedelta(days=6))

    assert renewed == NOW + timedelta(days=6)
    assert graph.subscriptions.stored[receipt.handle].expires == "2026-09-05T10:00:00Z"


def test_a_subscription_graph_removed_is_replaced_rather_than_renewed() -> None:
    watcher, graph = outlook()

    assert watcher.extend(ACCOUNT, registration("removed-subscription"), UNTIL) is None
    assert watcher.extend(ACCOUNT, registration(None), UNTIL) is None
    assert sent(graph, "POST", "/subscriptions") == []


def test_stopping_deletes_the_subscription_and_one_already_gone_is_stopped() -> None:
    watcher, graph = outlook()
    receipt = register(watcher)

    watcher.stop(ACCOUNT, registration(receipt.handle))
    watcher.stop(ACCOUNT, registration(receipt.handle))

    assert graph.subscriptions.stored == {}


def test_a_subscription_whose_answer_was_lost_is_stopped_by_its_exact_address() -> None:
    watcher, graph = outlook()
    register(watcher)

    watcher.stop(ACCOUNT, registration(None))

    assert graph.subscriptions.stored == {}


def test_stopping_never_deletes_a_subscription_another_registration_holds() -> None:
    watcher, graph = outlook()
    theirs = register(watcher, THEIRS, OTHER_ADDRESS)

    watcher.stop(ACCOUNT, registration(None))

    assert list(graph.subscriptions.stored) == [theirs.handle]
    assert not any(request.method == "DELETE" for request in graph.requests)


# Refusals ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("refusal", "kind"),
    [
        (graph_error(401, "InvalidAuthenticationToken"), WatchFailureKind.UNAUTHORIZED),
        (graph_error(403, "Authorization_RequestDenied"), WatchFailureKind.UNAUTHORIZED),
        # A refusal of this request alone never lapses the account.
        (graph_error(403, "ErrorAccessDenied"), WatchFailureKind.UNSUPPORTED),
        (graph_error(400, "BadRequest"), WatchFailureKind.UNSUPPORTED),
        (
            graph_error(429, "TooManyRequests", **{"Retry-After": "30"}),
            WatchFailureKind.RATE_LIMITED,
        ),
        (graph_error(503, "ServiceNotAvailable"), WatchFailureKind.TEMPORARY),
    ],
)
def test_refusals_are_classed_for_upkeep_without_graphs_words(
    refusal: Refusal, kind: WatchFailureKind
) -> None:
    watcher, graph = outlook()
    graph.refuse(refusal, lambda request: request.url.path.endswith("/subscriptions"))

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    failure = raised.value
    assert failure.kind is kind
    assert "private-marker" not in failure.detail
    assert failure.failure is None or "private-marker" not in failure.failure.detail


def test_a_rate_limit_carries_graphs_retry_after() -> None:
    watcher, graph = outlook()
    graph.refuse(graph_error(429, "TooManyRequests", **{"Retry-After": "30"}))

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.retry_after_seconds == 30


def test_an_account_graph_refuses_lapses_from_when_its_token_was_read() -> None:
    watcher, graph = outlook()
    graph.revoke(MAILBOX)

    with pytest.raises(WatchFailure) as raised:
        register(watcher)

    assert raised.value.kind is WatchFailureKind.UNAUTHORIZED
    lapse = raised.value.failure
    assert lapse is not None
    assert lapse.account_id == ACCOUNT
    assert lapse.attempted_at == NOW


@dataclass
class UnavailableTokens:
    """A credential store whose account was removed, or waits for reauthorization."""

    error: Exception

    def access_token(self, account_id: ConnectedAccountId) -> str:
        raise self.error


@pytest.mark.parametrize(
    "gone",
    [
        ConnectedAccountNotFound("connected account personal-account does not exist"),
        ConnectedAccountDisconnected("connected account personal-account needs reauthorization"),
    ],
)
def test_an_account_without_credentials_is_unsupported_in_every_call(gone: Exception) -> None:
    graph = FakeMicrosoftGraph()
    watcher = OutlookCalendarWatcher(
        UnavailableTokens(gone), GraphHttp(graph.client()), MovingClock()
    )
    calls = (
        lambda: watcher.scope(OWN),
        lambda: register(watcher),
        lambda: watcher.extend(ACCOUNT, registration("subscription-1"), UNTIL),
        lambda: watcher.adopt(ACCOUNT, WatchScope.account(), OURS, ADDRESS),
        lambda: watcher.stop(ACCOUNT, registration("subscription-1")),
    )

    for call in calls:
        with pytest.raises(WatchFailure) as raised:
            call()
        assert raised.value.kind is WatchFailureKind.UNSUPPORTED
        assert "personal-account" not in raised.value.detail
    assert graph.requests == []


def test_a_scope_graph_refuses_is_a_watch_failure() -> None:
    watcher, graph = outlook()
    graph.refuse(graph_error(503, "ServiceNotAvailable"))

    with pytest.raises(WatchFailure) as raised:
        watcher.scope(OWN)

    assert raised.value.kind is WatchFailureKind.TEMPORARY


# Notices ----------------------------------------------------------------------------------


def item(**fields: object) -> dict[str, object]:
    return {
        "subscriptionId": "subscription-1",
        "clientState": TOKEN,
        "tenantId": "synthetic-tenant",
        "subscriptionExpirationDateTime": "2026-09-02T10:00:00Z",
        **fields,
    }


def batch(*items: object) -> NoticeRequest:
    body = json.dumps({"value": list(items)}).encode()
    return NoticeRequest({"content-type": "application/json"}, {}, body)


def test_graph_asks_the_address_to_echo_its_validation_token() -> None:
    reader = OutlookNoticeReader()

    request = NoticeRequest({}, {"validationToken": "opaque token"}, b"")
    assert reader.validation_token(request) == "opaque token"
    assert reader.validation_token(batch(item())) is None


def test_a_batch_reads_changes_and_lifecycle_events() -> None:
    notices = OutlookNoticeReader().read(
        OURS,
        batch(
            item(changeType="updated", resource="Users/synthetic/Events/synthetic"),
            item(lifecycleEvent="missed"),
            item(lifecycleEvent="reauthorizationRequired"),
            item(lifecycleEvent="subscriptionRemoved"),
            # One this release does not know asks for a catch-up run.
            item(lifecycleEvent="somethingNew"),
        ),
    )

    assert [notice.kind for notice in notices] == [
        NoticeKind.CHANGED,
        NoticeKind.MISSED,
        NoticeKind.REAUTHORIZE,
        NoticeKind.REMOVED,
        NoticeKind.MISSED,
    ]
    assert notices[0] == WatchNotice(OURS, TOKEN, "subscription-1", NoticeKind.CHANGED)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        b"{}",
        b"[]",
        json.dumps({"value": []}).encode(),
        json.dumps({"value": [item()] * 101}).encode(),
        json.dumps({"value": [item(clientState=None)]}).encode(),
        json.dumps({"value": [item(subscriptionId=7)]}).encode(),
        json.dumps({"value": ["text"]}).encode(),
    ],
)
def test_a_body_outlook_would_not_send_is_malformed(body: bytes) -> None:
    with pytest.raises(MalformedNotice):
        OutlookNoticeReader().read(OURS, NoticeRequest({}, {}, body))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/adapters/microsoft/test_watches.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.infrastructure.microsoft.watches'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/infrastructure/microsoft/graph.py`. Change the module docstring's second
paragraph to:

```python
"""Requests to Microsoft Graph v1.0 and the identity platform, and how they are refused.

Every Graph request names an operation, carries the account's access token, asks for UTC times
and text bodies, and is tallied for the run that made it. A refusal keeps only what may be
recorded: its HTTP status, Microsoft's error codes, its Retry-After hint, and whether it says a
subscription's notification URL failed validation. It never keeps the message, which can quote
the request (ADR 0031, ADR 0034, ADR 0036).
"""
```

Add `import re` to the imports, and below `TIMEOUT_SECONDS`:

```python
# Graph refuses a subscription whose notification URL failed its validation request with a 400
# that says so only in its message, such as "Subscription validation request failed.
# Notification endpoint must respond with 200 OK to validation request." The message is matched
# here and never kept (ADR 0036).
UNVALIDATED_ENDPOINT = re.compile(
    r"validation request (?:failed|timed out)|notification endpoint", re.IGNORECASE
)
```

Extend `GraphRefusal`:

```python
@dataclass(eq=False)
class GraphRefusal(Exception):
    """Graph answered a request with an error."""

    status: int | None
    """None when no answer arrived at all."""
    codes: tuple[str, ...] = ()
    """`error.code` and each nested `innerError.code`, outermost first."""
    retry_after: str | None = None
    endpoint_refused: bool = False
    """Graph would not create a subscription because its notification URL did not answer the
    validation request: the installation's address is unreachable, not the account refused."""

    def __str__(self) -> str:
        return f"Graph answered {self.status or 'nothing'} {' '.join(self.codes)}".strip()
```

Replace `graph_refusal` and add its helper:

```python
def graph_refusal(response: httpx.Response) -> GraphRefusal:
    body = _json(response)
    return GraphRefusal(
        response.status_code,
        _graph_codes(body),
        response.headers.get("retry-after"),
        endpoint_refused=response.status_code == 400 and _says_endpoint_unvalidated(body),
    )


def _says_endpoint_unvalidated(body: Mapping[str, Any]) -> bool:
    """Whether Graph's message says the notification URL failed validation; only this answer
    is kept, never the message."""
    error = body.get("error")
    message = error.get("message") if isinstance(error, Mapping) else None
    return isinstance(message, str) and UNVALIDATED_ENDPOINT.search(message) is not None
```

`src/calendar_sync/infrastructure/microsoft/provider.py`. Replace the body of
`OutlookCalendarProvider._failure`:

```python
    def _failure(
        self,
        error: GraphRefusal | TokenRefusal,
        account: ConnectedAccountId,
        *,
        event_scoped: bool,
    ) -> ProviderFailure:
        now = self._clock.now()
        read: dict[ConnectedAccountId, datetime] = self._credentials_read.__dict__.get("at", {})
        return refusal_failure(
            error, account, attempted_at=read.get(account, now), now=now, event_scoped=event_scoped
        )
```

and add this module function directly above `def _kind(`:

```python
def refusal_failure(
    error: GraphRefusal | TokenRefusal,
    account: ConnectedAccountId,
    *,
    attempted_at: datetime,
    now: datetime,
    event_scoped: bool = False,
) -> ProviderFailure:
    """A Microsoft refusal as the provider failure the account's request met, keeping no message
    text. `attempted_at`, when the request read the account's credentials, tells whether a
    Reauthorization has replaced them since (ADR 0027); `now` counts a Retry-After date down."""
    return ProviderFailure(
        _kind(error),
        str(error),
        retry_after_seconds(error.retry_after, now),
        account_id=account,
        provider=ProviderKind.OUTLOOK,
        attempted_at=attempted_at,
        cause=cause_of(error, event_scoped=event_scoped),
        provider_label=MICROSOFT.calendar_name,
    )
```

`src/calendar_sync/infrastructure/microsoft/watches.py`:

```python
"""Outlook change notifications through Microsoft Graph subscriptions (ADR 0036).

Graph documents event subscriptions only for a whole mailbox, `me/events`. Delegated permissions
cannot watch a calendar that another mailbox shares, so one subscription covers every calendar
the signed-in mailbox owns, and a shared calendar is not watched. Before it answers 201, Graph
validates the notification URL and the lifecycle URL, which is the same address, so a created
subscription proves Graph reached the installation. A subscription lasts at most 10,080 minutes
and is renewed in place. Graph refuses a second one for the same resource and change types with
409. Such a subscription is adopted only when its notification URL names this registration
exactly, and an unidentified subscription is never deleted. Graph's message text is never kept
(ADR 0034).

Sources, checked 2026-10-14:
- Create subscription:
  https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
- Webhook delivery, validation, renewal, and deletion:
  https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks
- Lifecycle notifications:
  https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    Receipt,
    WatchFailure,
    WatchFailureKind,
    WatchNotice,
)
from calendar_sync.domain.model import CalendarEndpoint, ConnectedAccountId
from calendar_sync.domain.watches import WatchRegistration, WatchRegistrationId, WatchScope
from calendar_sync.infrastructure.microsoft.graph import (
    GraphHttp,
    GraphRefusal,
    TokenRefusal,
    items_of,
)
from calendar_sync.infrastructure.microsoft.provider import AccessTokens, refusal_failure
from calendar_sync.infrastructure.watch_failures import (
    ACCOUNT_UNAVAILABLE,
    account_unavailable,
    watch_failure,
)

RESOURCE = "me/events"
CHANGE_TYPES = "created,updated,deleted"
# Graph's longest Outlook subscription is 10,080 minutes; asking a little less leaves room for
# clocks that disagree.
LONGEST = timedelta(minutes=10_080) - timedelta(minutes=5)
# How long who owns a calendar is remembered: about one upkeep cycle.
OWNER_MEMORY = timedelta(minutes=5)
# Answers meaning the subscription or calendar is gone.
GONE = frozenset({404, 410})
# Graph's answer to a second subscription with the same resource and change types.
CONFLICT = 409
# A notice batch holds at most this many items.
MAX_ITEMS = 100
LIFECYCLE = {
    "missed": NoticeKind.MISSED,
    "reauthorizationRequired": NoticeKind.REAUTHORIZE,
    "subscriptionRemoved": NoticeKind.REMOVED,
}


class OutlookCalendarWatcher:
    """CalendarWatcher for Outlook: one Graph subscription per signed-in mailbox."""

    def __init__(self, tokens: AccessTokens, graph: GraphHttp, clock: Clock) -> None:
        self._tokens = tokens
        self._graph = graph
        self._clock = clock
        self._owners: dict[tuple[ConnectedAccountId, str], tuple[str | None, datetime]] = {}
        # Upkeep checks several Users' calendars at once.
        self._guard = Lock()

    def scope(self, calendar: CalendarEndpoint) -> WatchScope | None:
        account = calendar.connected_account_id
        started = self._clock.now()
        try:
            mailbox = self._owner(account, "/me/calendar", started)
            owner = self._owner(account, f"/me/calendars/{calendar.calendar_id.value}", started)
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from error
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        # A calendar another mailbox shares cannot be watched with delegated permissions.
        return WatchScope.account() if mailbox is not None and owner == mailbox else None

    def register(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        token: str,
        address: str,
        until: datetime,
    ) -> Receipt:
        if scope != WatchScope.account() or not _names(address, registration_id):
            raise WatchFailure(
                kind=WatchFailureKind.UNSUPPORTED,
                detail="Outlook watches a whole mailbox, at an address naming its registration",
            )
        started = self._clock.now()
        expiry = _capped(until, started)
        body = {
            "changeType": CHANGE_TYPES,
            "notificationUrl": address,
            "lifecycleNotificationUrl": address,
            "resource": RESOURCE,
            "expirationDateTime": _stamp(expiry),
            "clientState": token,
        }
        try:
            answer = self._graph.request(
                "subscriptions.create",
                "POST",
                "/subscriptions",
                self._tokens.access_token(account),
                body=body,
            )
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from error
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        receipt = _receipt(answer, expiry)
        if receipt is None:
            raise WatchFailure(
                kind=WatchFailureKind.TEMPORARY,
                detail="Outlook did not name the subscription it created",
            )
        return receipt

    def extend(
        self, account: ConnectedAccountId, registration: WatchRegistration, until: datetime
    ) -> datetime | None:
        if registration.handle is None:
            return None
        started = self._clock.now()
        expiry = _capped(until, started)
        try:
            answer = self._graph.request(
                "subscriptions.update",
                "PATCH",
                f"/subscriptions/{registration.handle}",
                self._tokens.access_token(account),
                body={"expirationDateTime": _stamp(expiry)},
            )
        except GraphRefusal as error:
            if error.status in GONE:
                # Graph removed it: None asks upkeep for a new subscription in its place.
                return None
            raise self._failure(error, account, started) from error
        except TokenRefusal as error:
            raise self._failure(error, account, started) from error
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        return _instant(answer.get("expirationDateTime")) or expiry

    def adopt(
        self,
        account: ConnectedAccountId,
        scope: WatchScope,
        registration_id: WatchRegistrationId,
        address: str,
    ) -> Receipt | None:
        if scope != WatchScope.account() or not _names(address, registration_id):
            return None
        started = self._clock.now()
        try:
            found = self._find(account, address)
        except (GraphRefusal, TokenRefusal) as error:
            raise self._failure(error, account, started) from error
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error
        return None if found is None else _receipt(found, None)

    def stop(self, account: ConnectedAccountId, registration: WatchRegistration) -> None:
        started = self._clock.now()
        try:
            handle = registration.handle or self._lost(account, registration)
            if handle is not None:
                self._graph.request(
                    "subscriptions.delete",
                    "DELETE",
                    f"/subscriptions/{handle}",
                    self._tokens.access_token(account),
                )
        except GraphRefusal as error:
            if error.status not in GONE:
                raise self._failure(error, account, started) from error
        except TokenRefusal as error:
            raise self._failure(error, account, started) from error
        except ACCOUNT_UNAVAILABLE as error:
            raise account_unavailable() from error

    def _owner(self, account: ConnectedAccountId, path: str, now: datetime) -> str | None:
        """Who owns the calendar at `path`, remembered for about one upkeep cycle; None when it
        is gone."""
        key = (account, path)
        with self._guard:
            known = self._owners.get(key)
        if known is not None and now - known[1] < OWNER_MEMORY:
            return known[0]
        try:
            answer = self._graph.request(
                "calendars.get",
                "GET",
                path,
                self._tokens.access_token(account),
                params={"$select": "owner"},
            )
            owner = _address(answer.get("owner"))
        except GraphRefusal as error:
            if error.status not in GONE:
                raise
            owner = None
        with self._guard:
            # Forget answers older than a cycle, so the memory stays as small as the work.
            self._owners = {
                seen: remembered
                for seen, remembered in self._owners.items()
                if now - remembered[1] < OWNER_MEMORY
            }
            self._owners[key] = (owner, now)
        return owner

    def _find(self, account: ConnectedAccountId, address: str) -> Mapping[str, Any] | None:
        """The subscription to the mailbox's events whose notification URL is exactly
        `address`, among those this application holds for the signed-in mailbox."""
        token = self._tokens.access_token(account)
        for page in self._graph.pages("subscriptions.list", "/subscriptions", token):
            for item in items_of(page):
                if item.get("notificationUrl") == address and _resource(item) == RESOURCE:
                    return item
        return None

    def _lost(self, account: ConnectedAccountId, registration: WatchRegistration) -> str | None:
        """The subscription a registration created whose answer was lost, found only by its
        exact address, so no other subscription is ever deleted."""
        if not _names(registration.address, registration.id):
            return None
        found = self._find(account, registration.address)
        handle = None if found is None else found.get("id")
        return handle if isinstance(handle, str) and handle else None

    def _failure(
        self, error: GraphRefusal | TokenRefusal, account: ConnectedAccountId, started: datetime
    ) -> WatchFailure:
        """Microsoft's refusal as a watch failure; `started` is when the call read the account's
        access token."""
        if isinstance(error, GraphRefusal) and error.status == CONFLICT:
            return WatchFailure(
                kind=WatchFailureKind.DUPLICATE,
                detail="Outlook already holds a subscription to this mailbox's events",
            )
        if isinstance(error, GraphRefusal) and error.endpoint_refused:
            return WatchFailure(
                kind=WatchFailureKind.UNREACHABLE,
                detail="Outlook could not reach this installation's notice address",
            )
        return watch_failure(
            refusal_failure(error, account, attempted_at=started, now=self._clock.now())
        )


class OutlookNoticeReader:
    """NoticeReader for Outlook: a batch of change and lifecycle notices in a JSON body."""

    def validation_token(self, request: NoticeRequest) -> str | None:
        # Graph proves the address by asking it to echo this token, which the route answers.
        return request.query.get("validationToken") or None

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        try:
            body = json.loads(request.body)
        except ValueError as error:
            raise MalformedNotice("the notice is not JSON") from error
        items = body.get("value") if isinstance(body, dict) else None
        if not isinstance(items, list) or not 0 < len(items) <= MAX_ITEMS:
            raise MalformedNotice("the notice is not a batch Outlook sends")
        return tuple(_notice(registration_id, item) for item in items)


def _notice(registration_id: WatchRegistrationId, item: object) -> WatchNotice:
    if not isinstance(item, Mapping):
        raise MalformedNotice("a notice in the batch is not an object")
    handle, token = item.get("subscriptionId"), item.get("clientState")
    if not (isinstance(handle, str) and handle and isinstance(token, str) and token):
        raise MalformedNotice("a notice names no subscription or carries no client state")
    event = item.get("lifecycleEvent")
    if event is None:
        return WatchNotice(registration_id, token, handle, NoticeKind.CHANGED)
    # A lifecycle event this release does not know asks for a catch-up run, as `missed` does.
    kind = LIFECYCLE.get(str(event), NoticeKind.MISSED)
    return WatchNotice(registration_id, token, handle, kind)


def _receipt(item: Mapping[str, Any], fallback: datetime | None) -> Receipt | None:
    """A subscription as upkeep records it. Graph validated its address before creating it, so
    delivery is proven."""
    handle = item.get("id")
    expires = _instant(item.get("expirationDateTime")) or fallback
    if not isinstance(handle, str) or not handle or expires is None:
        return None
    return Receipt(handle=handle, expires_at=expires, confirmed=True)


def _names(address: str, registration_id: WatchRegistrationId) -> bool:
    """Whether `address` is a notice address naming this registration, as adoption requires."""
    return address.endswith(f"/{registration_id.value}")


def _resource(item: Mapping[str, Any]) -> str:
    return str(item.get("resource") or "").strip("/").lower()


def _capped(until: datetime, now: datetime) -> datetime:
    return min(until, now + LONGEST).replace(microsecond=0)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(value: object) -> datetime | None:
    """Graph's `expirationDateTime`, such as "2026-09-02T10:00:00.0000000Z"."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _address(owner: object) -> str | None:
    address = owner.get("address") if isinstance(owner, Mapping) else None
    return (address.strip().lower() or None) if isinstance(address, str) else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/microsoft tests/test_provider_neutrality.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS (the existing Outlook provider and cause tests confirm that `refusal_failure` and the new `GraphRefusal` field changed nothing they read)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/infrastructure/microsoft/watches.py \
  src/calendar_sync/infrastructure/microsoft/graph.py \
  src/calendar_sync/infrastructure/microsoft/provider.py \
  tests/fake_graph_subscriptions.py tests/fake_microsoft_graph_api.py \
  tests/adapters/microsoft/test_watches.py
git commit -m "Watch Outlook mailboxes through Graph subscriptions and read their notices

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 12: Descriptors offer watchers and notice readers, and routing finds them

**Files:**
- Modify: `src/calendar_sync/application/sync/provider_descriptors.py` (`ProviderDescriptor.watcher`, `.notice_reader`; `ProviderDirectory.watching`, `.slug_of`; `ProviderGuide.slug` docstring)
- Modify: `src/calendar_sync/infrastructure/google/descriptor.py` (build the watcher and reader)
- Modify: `src/calendar_sync/infrastructure/microsoft/descriptor.py` (build the watcher and reader)
- Modify: `src/calendar_sync/infrastructure/providers/routing.py` (`RoutingCalendarWatcher`)
- Test: `tests/adapters/shared/test_routing.py` (append)
- Test: `tests/adapters/microsoft/test_descriptor.py` (extend)
- Test: `tests/adapters/google/test_descriptor.py` (create)

**Interfaces:**
- Consumes: `CalendarWatcher`, `NoticeReader`, `WatcherFor` (Task 3); `GoogleCalendarWatcher`, `GoogleNoticeReader` (Task 10); `OutlookCalendarWatcher`, `OutlookNoticeReader` (Task 11).
- Produces:
  - `ProviderDescriptor.watcher: CalendarWatcher | None = None`, `ProviderDescriptor.notice_reader: NoticeReader | None = None`
  - `ProviderDirectory.watching(slug: str) -> ProviderDescriptor | None`: the descriptor at `slug` when it reads notices (Task 17's route uses `.notice_reader` and `.kind`)
  - `ProviderDirectory.slug_of(kind: ProviderKind) -> str` (raises `LookupError` for a kind with no descriptor; Task 16 passes it as `UpkeepWatches.slug_of`)
  - `RoutingCalendarWatcher(kinds: ProviderKinds, watchers: Mapping[ProviderKind, CalendarWatcher])`, `RoutingCalendarWatcher.of(kinds, providers: ProviderDirectory)`, `__call__(account: ConnectedAccountId) -> CalendarWatcher | None` (satisfies `WatcherFor`), `provider_of(account: ConnectedAccountId) -> ProviderKind | None` (Task 16 passes it as `UpkeepWatches.provider_of`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/adapters/shared/test_routing.py`, adding these imports beside the existing ones:

```python
from calendar_sync.application.sync.watch_ports import CalendarWatcher, NoticeReader
from calendar_sync.infrastructure.providers.routing import RoutingCalendarWatcher
```

and these tests:

```python
def test_an_accounts_watcher_is_the_one_of_its_provider() -> None:
    watcher = cast(CalendarWatcher, Mock())
    kinds = StoredKinds({PERSONAL: ProviderKind.GOOGLE})
    router = RoutingCalendarWatcher.of(
        kinds, ProviderDirectory((ProviderDescriptor(GUIDE, watcher=watcher),))
    )

    assert router(PERSONAL) is watcher
    assert router(PERSONAL) is watcher
    assert router.provider_of(PERSONAL) is ProviderKind.GOOGLE
    assert kinds.lookups == [PERSONAL]


def test_an_account_whose_provider_cannot_watch_has_no_watcher() -> None:
    router = RoutingCalendarWatcher.of(
        StoredKinds({PERSONAL: ProviderKind.GOOGLE}),
        ProviderDirectory((ProviderDescriptor(GUIDE),)),
    )

    assert router(PERSONAL) is None


def test_an_account_that_does_not_exist_has_no_watcher() -> None:
    kinds = StoredKinds({})
    router = RoutingCalendarWatcher(kinds, {ProviderKind.GOOGLE: cast(CalendarWatcher, Mock())})

    assert router(PERSONAL) is None
    assert router.provider_of(PERSONAL) is None
    # An account that later connects is found: only answers are kept.
    kinds.kinds[PERSONAL] = ProviderKind.GOOGLE
    assert router(PERSONAL) is not None


def test_notices_reach_only_a_provider_that_reads_them() -> None:
    reading = ProviderDescriptor(GUIDE, notice_reader=cast(NoticeReader, Mock()))
    silent = ProviderDescriptor(
        ProviderGuide(ProviderKind.OUTLOOK, "other", "Other", "Other Calendar", {})
    )
    directory = ProviderDirectory((reading, silent))

    assert directory.watching("example") is reading
    assert directory.watching("other") is None
    assert directory.watching("unknown") is None


def test_a_providers_slug_names_where_its_notices_arrive() -> None:
    directory = ProviderDirectory((ProviderDescriptor(GUIDE),))

    assert directory.slug_of(ProviderKind.GOOGLE) == "example"
    with pytest.raises(LookupError):
        directory.slug_of(ProviderKind.OUTLOOK)
```

`tests/adapters/microsoft/test_descriptor.py`: add these imports:

```python
from calendar_sync.infrastructure.microsoft.watches import (
    OutlookCalendarWatcher,
    OutlookNoticeReader,
)
```

At the end of `test_a_configured_installation_gets_every_microsoft_role`, add:

```python
    assert isinstance(descriptor.watcher, OutlookCalendarWatcher)
    assert isinstance(descriptor.notice_reader, OutlookNoticeReader)
```

and in `test_without_its_application_or_the_master_key_microsoft_offers_nothing`, replace the loop's
assertion with:

```python
        assert (
            descriptor.connection,
            descriptor.calendars,
            descriptor.provider,
            descriptor.watcher,
            descriptor.notice_reader,
        ) == (None, None, None, None, None)
```

Create `tests/adapters/google/test_descriptor.py`:

```python
"""The Google package as bootstrap composes it: one descriptor (ADR 0022, ADR 0036)."""

from pathlib import Path

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.google.descriptor import google_provider
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher

CLIENT = OAuthClientConfig("client", "secret", "http://localhost:8000/api/v1/oauth/google/callback")


def test_google_watches_its_calendars_and_reads_their_notices(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    key = CredentialCipher.generate_key()
    store = SqliteConnectedAccountStore(database, CredentialCipher(key))

    descriptor = google_provider(
        CLIENT, store, SqliteAuthorizationStates(database), key, SystemClock()
    )

    assert descriptor.kind is ProviderKind.GOOGLE
    assert isinstance(descriptor.watcher, GoogleCalendarWatcher)
    assert isinstance(descriptor.notice_reader, GoogleNoticeReader)


def test_without_the_master_key_google_watches_nothing(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)

    descriptor = google_provider(
        CLIENT, None, SqliteAuthorizationStates(database), "", SystemClock()
    )

    assert (descriptor.watcher, descriptor.notice_reader) == (None, None)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/shared/test_routing.py tests/adapters/microsoft/test_descriptor.py tests/adapters/google/test_descriptor.py -q`
Expected: FAIL (`ImportError: cannot import name 'RoutingCalendarWatcher'`; `TypeError: ProviderDescriptor.__init__() got an unexpected keyword argument 'watcher'`; `AttributeError: 'ProviderDescriptor' object has no attribute 'watcher'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/application/sync/provider_descriptors.py`. Change the module docstring's
first paragraph to name the new roles:

```python
"""What each calendar provider tells the rest of Calendar Ghost about itself.

A provider's package describes itself to bootstrap with one ProviderDescriptor: its Provider Kind,
the names messages use, where the troubleshooting guide explains each Cause it can raise, any
Installation Hint only it explains, and the adapters it offers, including how Instant Sync
watches its calendars and reads its notices. Routing, Installation Hints, the notice route, and
the Web API read the descriptors, so no code outside a provider's package asks which provider it
is talking to (ADR 0022, ADR 0036).
"""
```

Add the import:

```python
from calendar_sync.application.sync.watch_ports import CalendarWatcher, NoticeReader
```

Change the `slug` docstring in `ProviderGuide`:

```python
    slug: str
    """Where its connection flow lives, under `/api/v1/oauth/{slug}/`, and where its watch notices
    arrive, under `/api/v1/watch-notices/{slug}/`; it never changes, because every installation
    registers the callback there with the provider, and live watches point there."""
```

Add two fields at the end of `ProviderDescriptor`, after `secret_expires`:

```python
    watcher: CalendarWatcher | None = None
    """How Instant Sync watches the provider's calendars, when the provider can (ADR 0036)."""
    notice_reader: NoticeReader | None = None
    """How the provider's watch notices are read, at `/api/v1/watch-notices/{slug}/`."""
```

Add two methods at the end of `ProviderDirectory`:

```python
def watching(self, slug: str) -> ProviderDescriptor | None:
    """The provider whose watch notices arrive under `slug`, when it reads them."""
    found = self.at(slug)
    return found if found is not None and found.notice_reader is not None else None


def slug_of(self, kind: ProviderKind) -> str:
    """Where `kind`'s connection flow and watch notices live. Every provider this release
    knows has a descriptor, so a missing one is a composition error."""
    found = self.of(kind)
    if found is None:
        raise LookupError(f"no descriptor for provider {kind.value}")
    return found.guide.slug
```

`src/calendar_sync/infrastructure/google/descriptor.py`:

```python
"""The Google package as bootstrap composes it: one descriptor (ADR 0022, ADR 0036)."""

from __future__ import annotations

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.provider_descriptors import (
    ProviderConnection,
    ProviderDescriptor,
)
from calendar_sync.infrastructure.google.guide import GOOGLE
from calendar_sync.infrastructure.google.oauth import GoogleOAuthService
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)


def google_provider(
    client: OAuthClientConfig,
    accounts: SqliteConnectedAccountStore | None,
    states: SqliteAuthorizationStates,
    master_key: str,
    clock: Clock,
) -> ProviderDescriptor:
    """Google's descriptor. Without the installation master key no account can be stored, so it
    offers no adapters; without its OAuth client, no User can connect an account."""
    if accounts is None:
        return ProviderDescriptor(GOOGLE)
    oauth = GoogleOAuthService(client, accounts, states, verifier_key=master_key)
    return ProviderDescriptor(
        GOOGLE,
        configured=bool(client.client_id and client.client_secret),
        connection=ProviderConnection(oauth, client.redirect_uri),
        calendars=oauth,
        provider=GoogleCalendarProvider(oauth.service_for, clock),
        watcher=GoogleCalendarWatcher(oauth.service_for, clock),
        notice_reader=GoogleNoticeReader(),
    )
```

`src/calendar_sync/infrastructure/microsoft/descriptor.py`: add the import

```python
from calendar_sync.infrastructure.microsoft.watches import (
    OutlookCalendarWatcher,
    OutlookNoticeReader,
)
```

change the module docstring to `"""The Microsoft package as bootstrap composes it: one descriptor (ADR 0022, ADR 0034, ADR 0036)."""`, and make the configured return:

```python
    return ProviderDescriptor(
        MICROSOFT,
        configured=True,
        connection=ProviderConnection(oauth, client.oauth.redirect_uri),
        calendars=oauth,
        provider=OutlookCalendarProvider(oauth, oauth.graph, clock),
        secret_expires=secret_expires,
        watcher=OutlookCalendarWatcher(oauth, oauth.graph, clock),
        notice_reader=OutlookNoticeReader(),
    )
```

`src/calendar_sync/infrastructure/providers/routing.py`: change the module docstring to

```python
"""Sends each calendar request to the adapter of the provider its Connected Account belongs to.

A rule's source and destination may belong to different providers, so every request is routed
by the account its endpoint names (ADR 0022). Instant Sync finds each account's watcher the same
way (ADR 0036). An account's provider never changes, so the answer is kept after the first
lookup; an account not found is looked up again next time.
"""
```

add the import

```python
from calendar_sync.application.sync.watch_ports import CalendarWatcher
```

and append the class:

```python
class RoutingCalendarWatcher:
    """The watcher of each Connected Account's provider, for Instant Sync (WatcherFor): None when
    the provider cannot watch, or the account no longer exists."""

    def __init__(
        self, kinds: ProviderKinds, watchers: Mapping[ProviderKind, CalendarWatcher]
    ) -> None:
        self._kinds = _KnownKinds(kinds)
        self._watchers = dict(watchers)

    @classmethod
    def of(cls, kinds: ProviderKinds, providers: ProviderDirectory) -> RoutingCalendarWatcher:
        """A router to the watcher each provider's descriptor offers."""
        return cls(
            kinds,
            {d.kind: d.watcher for d in providers.descriptors if d.watcher is not None},
        )

    def __call__(self, account_id: ConnectedAccountId) -> CalendarWatcher | None:
        kind = self._kinds.of(account_id)
        return None if kind is None else self._watchers.get(kind)

    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        """The account's Provider Kind, from the same remembered lookup."""
        return self._kinds.of(account_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/shared tests/adapters/microsoft/test_descriptor.py tests/adapters/google/test_descriptor.py tests/test_provider_neutrality.py tests/test_architecture.py tests/adapters/test_composition.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS (`ProviderDescriptor` has only properties, so the wide-dataclass check ignores its eight fields. The neutrality test passes because the new core text names no provider and no module outside a provider's package names a Provider Kind member.)

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/sync/provider_descriptors.py \
  src/calendar_sync/infrastructure/google/descriptor.py \
  src/calendar_sync/infrastructure/microsoft/descriptor.py \
  src/calendar_sync/infrastructure/providers/routing.py \
  tests/adapters/shared/test_routing.py tests/adapters/microsoft/test_descriptor.py \
  tests/adapters/google/test_descriptor.py
git commit -m "Let each provider's descriptor offer its calendar watcher and notice reader

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 13: WatchUpkeep keeps every User's watches within one call budget

**Files:**
- Create: `src/calendar_sync/application/operations/instant_sync.py`
- Modify: `tests/adapters/test_user_isolation_schema.py` (`INSTALLATION_UNIT_RECEIVERS` gains the new module, with its comment)
- Test: `tests/application/test_watch_upkeep.py`

**Interfaces:**
- Consumes: `InstallationUnitOfWorkFactory`, `InstantSyncOwner(user, wanted, disabled, next_due)` and `InstallationUnitOfWork.instant_sync_owners() -> Sequence[InstantSyncOwner]` (Task 9); `CallBudget(remaining)` with `spend(calls: int) -> None` (may go below zero) and `exhausted` (`remaining <= 0`), `UpkeepWatches.execute(*, allowed: bool, address: str | None, budget: CallBudget) -> None` (Task 4); `SyncCadencePolicy.cadence(user) -> SyncCadence` (Task 3); `Clock`.
- Produces, in `calendar_sync.application.operations.instant_sync`: `QUIET`, `MAX_WAIT`, `MIN_GAP`, `UPKEEP_BUDGET = 200`; `WatchUpkeep(installation, upkeep_for: Callable[[UserId], UpkeepWatches | None], cadence, address: str | None, clock)` with `run(budget: int = UPKEEP_BUDGET) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/application/test_watch_upkeep.py`:

```python
"""Watch upkeep across Users: who may have watches, in what order, within one call budget."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import TracebackType
from typing import Self, cast

import pytest

from calendar_sync.application.operations.instant_sync import UPKEEP_BUDGET, WatchUpkeep
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
)
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from tests.fake_calendar import FixedClock
from tests.helpers import NOW
from tests.users import OTHER_USER, USER

ADDRESS = "https://ghost.example.test"
THIRD_USER = UserId("user-3")

Visit = tuple[UserId, bool, str | None]


class Owners:
    """The installation-wide unit of work, as far as watch upkeep reads it."""

    def __init__(self, *owners: InstantSyncOwner) -> None:
        self.owners = list(owners)

    def __call__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def commit(self) -> None:
        return None

    def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
        return tuple(self.owners)


class Cadences:
    """Each User's Sync Cadence; Users named here have no Instant Sync in their Plan."""

    def __init__(self, *scheduled_only: UserId) -> None:
        self.scheduled_only = set(scheduled_only)

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)


class Upkeep:
    """One User's watch upkeep: it records each visit and spends `cost` provider calls."""

    def __init__(self, user: UserId, visits: list[Visit], cost: int, failing: bool) -> None:
        self.user, self.visits, self.cost, self.failing = user, visits, cost, failing

    def execute(self, *, allowed: bool, address: str | None, budget: CallBudget) -> None:
        self.visits.append((self.user, allowed, address))
        if self.failing:
            raise RuntimeError("synthetic provider outage")
        budget.spend(self.cost)


def _owner(
    user: UserId,
    *,
    wanted: bool = True,
    disabled: bool = False,
    next_due: datetime | None = None,
) -> InstantSyncOwner:
    return InstantSyncOwner(user=user, wanted=wanted, disabled=disabled, next_due=next_due)


def _upkeep(
    owners: Owners,
    visits: list[Visit],
    *,
    cost: int = 0,
    failing: frozenset[UserId] = frozenset(),
    missing: frozenset[UserId] = frozenset(),
    cadence: Cadences | None = None,
    address: str | None = ADDRESS,
) -> WatchUpkeep:
    def upkeep_for(user: UserId) -> UpkeepWatches | None:
        if user in missing:
            return None
        return cast(UpkeepWatches, Upkeep(user, visits, cost, user in failing))

    return WatchUpkeep(
        cast(InstallationUnitOfWorkFactory, owners),
        upkeep_for,
        cadence or Cadences(),
        address,
        FixedClock(),
    )


@pytest.mark.parametrize(
    ("owner", "cadence", "address", "allowed"),
    [
        (_owner(USER), Cadences(), ADDRESS, True),
        (_owner(USER), Cadences(), None, False),
        (_owner(USER, disabled=True), Cadences(), ADDRESS, False),
        (_owner(USER, wanted=False), Cadences(), ADDRESS, False),
        (_owner(USER), Cadences(USER), ADDRESS, False),
    ],
    ids=["allowed", "no public address", "disabled", "turned off", "not in plan"],
)
def test_a_user_may_have_watches_only_when_everything_allows_instant_sync(
    owner: InstantSyncOwner, cadence: Cadences, address: str | None, allowed: bool
) -> None:
    visits: list[Visit] = []

    _upkeep(Owners(owner), visits, cadence=cadence, address=address).run()

    # A User who may not have watches is still visited, so the watches they have stop.
    assert visits == [(USER, allowed, address)]


def test_a_cycle_goes_by_due_work_and_the_next_resumes_where_the_budget_ran_out() -> None:
    owners = Owners(
        # A User with nothing planned yet is missing coverage, so goes first.
        _owner(USER, next_due=None),
        _owner(OTHER_USER, next_due=NOW - timedelta(hours=1)),
        _owner(THIRD_USER, next_due=NOW + timedelta(hours=1)),
    )
    visits: list[Visit] = []
    upkeep = _upkeep(owners, visits, cost=2)
    cycles = []

    for _ in range(3):
        visits.clear()
        upkeep.run(budget=3)
        cycles.append([user for user, _, _ in visits])

    # The Users a cycle never reached go first in the next, then the User it stopped on.
    assert cycles == [[USER, OTHER_USER], [THIRD_USER, OTHER_USER], [USER, OTHER_USER]]


def test_two_users_with_large_backlogs_take_turns() -> None:
    visits: list[Visit] = []
    # Each User alone could spend a whole cycle's budget.
    upkeep = _upkeep(Owners(_owner(USER), _owner(OTHER_USER)), visits, cost=5)
    cycles = []

    for _ in range(4):
        visits.clear()
        upkeep.run(budget=3)
        cycles.append([user for user, _, _ in visits])

    assert cycles == [[USER], [OTHER_USER], [USER], [OTHER_USER]]


def test_a_cycle_with_budget_to_spare_visits_every_user() -> None:
    owners = Owners(_owner(USER), _owner(OTHER_USER), _owner(THIRD_USER))
    visits: list[Visit] = []

    _upkeep(owners, visits, cost=2).run()

    assert UPKEEP_BUDGET == 200
    assert [user for user, _, _ in visits] == [USER, OTHER_USER, THIRD_USER]


def test_one_users_failing_upkeep_holds_up_nobody_else(caplog: pytest.LogCaptureFixture) -> None:
    visits: list[Visit] = []
    owners = Owners(_owner(USER), _owner(OTHER_USER))

    with caplog.at_level("ERROR", logger="calendar_sync.application.operations.instant_sync"):
        _upkeep(owners, visits, failing=frozenset({USER})).run()

    assert [user for user, _, _ in visits] == [USER, OTHER_USER]
    assert "Upkeep of a User's watches failed; trying again next cycle" in caplog.text
    assert USER.value not in caplog.text


def test_users_no_provider_can_watch_for_are_skipped() -> None:
    visits: list[Visit] = []

    _upkeep(Owners(_owner(USER), _owner(OTHER_USER)), visits, missing=frozenset({USER})).run()

    assert visits == [(OTHER_USER, True, ADDRESS)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/application/test_watch_upkeep.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.application.operations.instant_sync'`)

- [ ] **Step 3: Implement**

`src/calendar_sync/application/operations/instant_sync.py`:

```python
"""Instant Sync across Users (ADR 0036): watch upkeep and the dispatch of Instant Sync Requests.

Both run beside the scheduler and, like it, read every User through the installation-wide unit
of work (ADR 0029). Each User's own work still runs with that User's units: their watch upkeep,
each rule's run through the scheduled pass, and each acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy
from calendar_sync.domain.access import UserId

logger = logging.getLogger(__name__)

QUIET = timedelta(seconds=10)
"""How long a rule's notices must stay quiet before its instant run, so a burst runs it once."""
MAX_WAIT = timedelta(seconds=30)
"""The longest that notices which keep coming hold a rule's instant run back."""
MIN_GAP = timedelta(seconds=30)
"""The shortest time between two instant runs of one rule."""
UPKEEP_BUDGET = 200
"""Provider calls one upkeep cycle may make across every User; the rest waits a cycle."""


@dataclass(slots=True)
class WatchUpkeep:
    """Keeps every User's Calendar Watches as their rules, preference, and Plan want them.

    Each cycle visits Users with nothing planned yet first, then the others in order of their
    earliest due work, so what waited longest goes first. Disabled Users are visited too: nothing
    is wanted for them, so their watches stop.
    """

    installation: InstallationUnitOfWorkFactory
    upkeep_for: Callable[[UserId], UpkeepWatches | None]
    """A User's own upkeep; None where no provider can watch, as without the master key."""
    cadence: SyncCadencePolicy
    address: str | None
    """The installation's public https address; None when it has none."""
    clock: Clock
    _carried: tuple[UserId, ...] = ()
    """The Users the last cycle never reached, then the User it stopped on; they go first."""

    def run(self, budget: int = UPKEEP_BUDGET) -> None:
        calls = CallBudget(budget)
        with self.installation() as installation:
            owners = self._in_turn(installation.instant_sync_owners())
        self._carried = ()
        for position, owner in enumerate(owners):
            self._keep(owner, calls)
            if calls.exhausted:
                # The Users it never reached go first next cycle, then this one, whose upkeep
                # the budget may have cut short. So a User with a large backlog never stays
                # first forever, and two such Users take turns.
                unreached = owners[position + 1 :]
                self._carried = (*(each.user for each in unreached), owner.user)
                logger.info("Watch upkeep spent its provider call budget; the rest waits a cycle")
                return

    def _in_turn(self, owners: Sequence[InstantSyncOwner]) -> list[InstantSyncOwner]:
        """The Users the last cycle never reached, then the User it stopped on, then those with
        nothing planned yet, whose coverage is missing, then the rest by earliest due work."""
        now = self.clock.now()
        carried = {user: turn for turn, user in enumerate(self._carried)}

        def turn(owner: InstantSyncOwner) -> tuple[int, int, datetime, str]:
            if owner.user in carried:
                return 0, carried[owner.user], now, owner.user.value
            if owner.next_due is None:
                return 1, 0, now, owner.user.value
            return 2, 0, owner.next_due, owner.user.value

        return sorted(owners, key=turn)

    def _keep(self, owner: InstantSyncOwner, calls: CallBudget) -> None:
        """One User's upkeep; a failure waits for the next cycle and holds up nobody else."""
        try:
            upkeep = self.upkeep_for(owner.user)
            if upkeep is not None:
                upkeep.execute(allowed=self._allowed(owner), address=self.address, budget=calls)
        except Exception:
            logger.exception("Upkeep of a User's watches failed; trying again next cycle")

    def _allowed(self, owner: InstantSyncOwner) -> bool:
        """Whether the User may have watches: the installation can be reached, the User is
        active and wants Instant Sync, and their Plan includes it."""
        return (
            self.address is not None
            and not owner.disabled
            and owner.wanted
            and self.cadence.cadence(owner.user).instant
        )
```

In `tests/adapters/test_user_isolation_schema.py`, replace the comment and set:

```python
# Only these may receive the installation-wide unit of work: the ports that declare it, the
# adapters that implement it and run migrations, the scheduled pass, Instant Sync's upkeep and
# dispatch, which run beside it (ADR 0036), the Operator Overview, and the composition root that
# hands it to them.
INSTALLATION_UNIT_RECEIVERS = {
    "application/operations/instant_sync.py",
    "application/operations/operator_overview.py",
    "application/operations/ports.py",
    "application/operations/scheduled_pass.py",
    "bootstrap/container.py",
    "infrastructure/persistence/installation.py",
    "infrastructure/persistence/memory_installation.py",
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/application/test_watch_upkeep.py tests/adapters/test_user_isolation_schema.py tests/test_architecture.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/operations/instant_sync.py tests/application/test_watch_upkeep.py tests/adapters/test_user_isolation_schema.py
git commit -m "Keep every User's Calendar Watches within one provider call budget per cycle

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 14: InstantDispatch chooses due Instant Sync Requests and acknowledges each run

**Files:**
- Modify: `src/calendar_sync/application/operations/instant_sync.py` (adds `InstantRun`, `due_at`, `InstantDispatch`)
- Test: `tests/application/test_instant_dispatch.py`

**Interfaces:**
- Consumes: `InstallationUnitOfWork.instant_sync_owners()` and `pending_instant_runs() -> Sequence[PendingInstantRun]`, `PendingInstantRun(scheduled: ScheduledRule, request: PendingRequest, last_run_failed: bool)` (Task 9); `PendingRequest`, `SyncCadencePolicy` (Task 3); `UnitOfWork.instant_requests.acknowledge(rule_id, seq, ran_at)` (Tasks 3 and 6); `ScheduledPass.run(ScheduledRun) -> bool`, `ScheduledRun`, `fairly_ordered` (existing).
- Produces: `InstantRun(scheduled: ScheduledRun, seq: int)`; `due_at(request: PendingRequest) -> datetime`; `InstantDispatch(installation, scheduled_pass, requests_for: Callable[[UserId], UnitOfWorkFactory], cadence, clock)` with `due(reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]` and `run(item: InstantRun) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/application/test_instant_dispatch.py`:

```python
"""Instant dispatch: which Instant Sync Requests run now, in what order, and how each run
acknowledges its request (ADR 0036)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Self, cast

import pytest

from calendar_sync.application.operations.instant_sync import (
    MAX_WAIT,
    MIN_GAP,
    QUIET,
    InstantDispatch,
    InstantRun,
    due_at,
)
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
)
from calendar_sync.application.operations.scheduled_pass import (
    ScheduledPass,
    ScheduledServices,
    SyncRuns,
)
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.health import RunHealth
from calendar_sync.application.sync.ports import ScheduledRule, UnitOfWorkFactory
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.application.sync.watch_ports import PendingRequest
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.providers import ProviderFailureKind
from tests.helpers import NOW, rule
from tests.scheduled_fakes import RecordingHealth
from tests.users import OTHER_USER, USER


class Clock:
    def __init__(self) -> None:
        self.moment = NOW

    def now(self) -> datetime:
        return self.moment


@dataclass
class Requests:
    """Every User's Instant Sync Requests, as the inbox raises them and runs acknowledge them."""

    clock: Clock
    pending: dict[tuple[UserId, SyncRuleId], PendingRequest] = field(default_factory=dict)
    acknowledging_fails: bool = False

    def notice(self, owner: UserId, rule_id: SyncRuleId, at: datetime | None = None) -> None:
        moment = at or self.clock.now()
        known = self.pending.get((owner, rule_id))
        if known is None:
            self.pending[owner, rule_id] = PendingRequest(rule_id, 1, 0, moment, moment, None)
            return
        waiting = known.requested_seq > known.handled_seq
        self.pending[owner, rule_id] = replace(
            known,
            requested_seq=known.requested_seq + 1,
            first_requested_at=known.first_requested_at if waiting else moment,
            last_requested_at=moment,
        )

    def acknowledge(self, owner: UserId, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        if self.acknowledging_fails:
            raise RuntimeError("database is locked")
        known = self.pending[owner, rule_id]
        self.pending[owner, rule_id] = replace(
            known, handled_seq=max(known.handled_seq, seq), last_run_at=ran_at
        )

    def waiting(self, owner: UserId, rule_id: SyncRuleId) -> bool:
        known = self.pending[owner, rule_id]
        return known.requested_seq > known.handled_seq


class OwnersRequests:
    def __init__(self, requests: Requests, owner: UserId) -> None:
        self.requests, self.owner = requests, owner

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        self.requests.acknowledge(self.owner, rule_id, seq, ran_at)


class OwnersUnit:
    """One User's unit of work, as far as acknowledging their requests uses it."""

    def __init__(self, requests: Requests, owner: UserId) -> None:
        self.instant_requests = OwnersRequests(requests, owner)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def commit(self) -> None:
        return None


@dataclass
class Installation:
    """Every User's records, as far as dispatch reads them across Users."""

    requests: Requests
    rules: dict[SyncRuleId, tuple[UserId, SyncRule]]
    owners: dict[UserId, InstantSyncOwner]
    failing: set[SyncRuleId] = field(default_factory=set)

    def __call__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
        return tuple(self.owners.values())

    def pending_instant_runs(self) -> tuple[PendingInstantRun, ...]:
        """As the stores list them: enabled rules of Users who are not disabled."""
        return tuple(
            PendingInstantRun(
                ScheduledRule(owner, self.rules[rule_id][1], None),
                request,
                rule_id in self.failing,
            )
            for (owner, rule_id), request in self.requests.pending.items()
            if request.requested_seq > request.handled_seq
            and self.rules[rule_id][1].state is SyncRuleState.ENABLED
            and not self.owners[owner].disabled
        )


class Runs:
    """A User's Sync Runs: each records its rule, and may do something while it runs."""

    def __init__(self) -> None:
        self.ran: list[tuple[str, bool]] = []
        self.during: Callable[[], None] = lambda: None
        self.failure: Exception | None = None

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        self.ran.append((rule_id.value, full))
        self.during()
        if self.failure is not None:
            raise self.failure
        return SyncRunResult(rule_id)


class Cadences:
    def __init__(self) -> None:
        self.scheduled_only: set[UserId] = set()

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.scheduled_only, poll_every=SCHEDULED_EVERY)


class World:
    """An installation whose rules' Instant Sync Requests one dispatch runs."""

    def __init__(self, *owned: tuple[UserId, SyncRule]) -> None:
        self.clock = Clock()
        self.requests = Requests(self.clock)
        self.installation = Installation(
            self.requests,
            {each.id: (owner, each) for owner, each in owned},
            {
                owner: InstantSyncOwner(user=owner, wanted=True, disabled=False, next_due=None)
                for owner, _ in owned
            },
        )
        self.runs = Runs()
        self.cadences = Cadences()
        services = ScheduledServices(cast(SyncRuns, self.runs), cast(RunHealth, RecordingHealth()))
        installation = cast(InstallationUnitOfWorkFactory, self.installation)
        self.dispatch = InstantDispatch(
            installation,
            ScheduledPass(installation, lambda _owner: services, self.clock),
            self._units,
            self.cadences,
            self.clock,
        )

    def _units(self, owner: UserId) -> UnitOfWorkFactory:
        return cast(UnitOfWorkFactory, lambda: OwnersUnit(self.requests, owner))

    def owner(self, user: UserId, *, wanted: bool = True, disabled: bool = False) -> None:
        self.installation.owners[user] = replace(
            self.installation.owners[user], wanted=wanted, disabled=disabled
        )


def _rule(rule_id: str) -> SyncRule:
    return replace(rule(), id=SyncRuleId(rule_id))


def _ids(runs: tuple[InstantRun, ...]) -> list[str]:
    return [run.scheduled.scheduled.rule.id.value for run in runs]


def test_the_timing_is_the_one_the_design_settles() -> None:
    assert (QUIET, MAX_WAIT, MIN_GAP) == (
        timedelta(seconds=10),
        timedelta(seconds=30),
        timedelta(seconds=30),
    )
    assert due_at(PendingRequest(rule().id, 1, 0, NOW, NOW, None)) == NOW + QUIET


@pytest.mark.parametrize(
    ("first", "last", "ran", "due_now", "wake"),
    [
        (-10, -10, None, True, None),
        (-5, -5, None, False, 5),
        (-30, -1, None, True, None),
        (-25, -1, None, False, 5),
        (-20, -20, -10, False, 20),
        (-20, -20, -30, True, None),
    ],
    ids=[
        "quiet for its window",
        "still within its quiet window",
        "notices kept coming for the longest wait",
        "notices keep coming within the longest wait",
        "ran within the gap",
        "ran before the gap",
    ],
)
def test_a_request_is_due_after_its_quiet_window_its_longest_wait_and_the_rules_gap(
    first: int, last: int, ran: int | None, due_now: bool, wake: int | None
) -> None:
    world = World((USER, rule()))
    world.requests.pending[USER, rule().id] = PendingRequest(
        rule().id,
        1,
        0,
        NOW + timedelta(seconds=first),
        NOW + timedelta(seconds=last),
        None if ran is None else NOW + timedelta(seconds=ran),
    )

    runs, next_due = world.dispatch.due(frozenset())

    assert _ids(runs) == (["rule-1"] if due_now else [])
    assert next_due == (None if wake is None else NOW + timedelta(seconds=wake))
    assert world.requests.waiting(USER, rule().id)


def test_due_runs_take_turns_between_users_and_never_list_in_full() -> None:
    owned = [
        *((USER, _rule(f"rule-{number}")) for number in (1, 2, 3)),
        (OTHER_USER, _rule("rule-4")),
    ]
    world = World(*owned)
    for owner, each in owned:
        world.requests.notice(owner, each.id, NOW - QUIET)

    runs, next_due = world.dispatch.due(frozenset())

    assert _ids(runs) == ["rule-1", "rule-4", "rule-2", "rule-3"]
    assert {run.scheduled.full for run in runs} == {False}
    assert [run.seq for run in runs] == [1, 1, 1, 1]
    assert next_due is None


def test_a_reserved_rule_is_left_alone() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)

    runs, next_due = world.dispatch.due(frozenset({"rule-1"}))

    assert (runs, next_due) == ((), None)
    assert world.requests.waiting(USER, rule().id)


INELIGIBLE: dict[str, Callable[[World], None]] = {
    "turned off": lambda world: world.owner(USER, wanted=False),
    "not in plan": lambda world: world.cadences.scheduled_only.add(USER),
    "last run failed": lambda world: world.installation.failing.add(rule().id),
}


def _pause(world: World) -> None:
    world.installation.rules[rule().id] = (USER, rule(state=SyncRuleState.PAUSED))


def _resume(world: World) -> None:
    world.installation.rules[rule().id] = (USER, rule())


INACTIVE: dict[str, tuple[Callable[[World], None], Callable[[World], None]]] = {
    "paused rule": (_pause, _resume),
    "disabled user": (
        lambda world: world.owner(USER, disabled=True),
        lambda world: world.owner(USER),
    ),
}


@pytest.mark.parametrize("change", list(INELIGIBLE.values()), ids=list(INELIGIBLE))
def test_a_request_whose_rule_may_not_run_instantly_is_dropped(
    change: Callable[[World], None],
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    change(world)

    runs, next_due = world.dispatch.due(frozenset())

    assert (runs, next_due) == ((), None)
    assert not world.requests.waiting(USER, rule().id)
    assert world.runs.ran == []


@pytest.mark.parametrize(("stop", "resume"), list(INACTIVE.values()), ids=list(INACTIVE))
def test_a_request_waits_while_its_rule_or_user_is_inactive_then_runs(
    stop: Callable[[World], None], resume: Callable[[World], None]
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    stop(world)

    waiting = world.dispatch.due(frozenset())
    resume(world)
    runs, _ = world.dispatch.due(frozenset())

    assert waiting == ((), None)
    assert _ids(runs) == ["rule-1"]


@pytest.mark.parametrize(("stop", "resume"), list(INACTIVE.values()), ids=list(INACTIVE))
def test_a_waiting_request_is_dropped_once_active_if_its_user_turned_instant_sync_off(
    stop: Callable[[World], None], resume: Callable[[World], None]
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    stop(world)
    world.dispatch.due(frozenset())
    resume(world)
    world.owner(USER, wanted=False)

    runs, next_due = world.dispatch.due(frozenset())

    assert (runs, next_due) == ((), None)
    assert not world.requests.waiting(USER, rule().id)


def test_a_queued_run_whose_user_turned_instant_sync_off_does_not_run() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.owner(USER, wanted=False)

    world.dispatch.run(item)

    assert world.runs.ran == []
    assert not world.requests.waiting(USER, rule().id)


def test_a_queued_run_whose_rule_was_paused_waits_without_running() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    _pause(world)

    world.dispatch.run(item)

    assert world.runs.ran == []
    assert world.requests.waiting(USER, rule().id)


@pytest.mark.parametrize(
    "failure",
    [None, ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic refusal")],
    ids=["succeeded", "failed"],
)
def test_a_run_acknowledges_its_request_whether_it_succeeded_or_failed(
    failure: ProviderFailure | None,
) -> None:
    world = World((USER, rule()))
    world.runs.failure = failure
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.clock.moment = NOW + timedelta(seconds=3)

    world.dispatch.run(item)

    assert world.runs.ran == [("rule-1", False)]
    assert not world.requests.waiting(USER, rule().id)
    assert world.requests.pending[USER, rule().id].last_run_at == NOW + timedelta(seconds=3)


def test_a_notice_during_a_run_keeps_its_request_for_another_run() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    world.runs.during = lambda: world.requests.notice(USER, rule().id)
    (item,), _ = world.dispatch.due(frozenset())

    world.dispatch.run(item)
    runs, next_due = world.dispatch.due(frozenset())

    assert world.requests.waiting(USER, rule().id)
    # It runs again, once the rule's gap since this run has passed.
    assert (runs, next_due) == ((), NOW + MIN_GAP)


def test_a_crash_before_the_acknowledgement_runs_the_rule_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())
    world.requests.acknowledging_fails = True

    with caplog.at_level("ERROR", logger="calendar_sync.application.operations.instant_sync"):
        world.dispatch.run(item)
    world.requests.acknowledging_fails = False
    again, _ = world.dispatch.due(frozenset())

    assert world.requests.waiting(USER, rule().id)
    assert _ids(again) == ["rule-1"]
    assert "Could not acknowledge the instant run of rule rule-1" in caplog.text


def test_an_unexpected_failure_still_acknowledges_the_request() -> None:
    world = World((USER, rule()))
    world.requests.notice(USER, rule().id, NOW - QUIET)
    (item,), _ = world.dispatch.due(frozenset())

    def broken(_owner: UserId) -> ScheduledServices:
        raise RuntimeError("synthetic composition failure")

    world.dispatch.scheduled_pass = ScheduledPass(
        cast(InstallationUnitOfWorkFactory, world.installation), broken, world.clock
    )

    with pytest.raises(RuntimeError):
        world.dispatch.run(item)

    assert not world.requests.waiting(USER, rule().id)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/application/test_instant_dispatch.py -q`
Expected: FAIL (`ImportError: cannot import name 'InstantDispatch' from 'calendar_sync.application.operations.instant_sync'`)

- [ ] **Step 3: Implement**

Replace `src/calendar_sync/application/operations/instant_sync.py` with:

```python
"""Instant Sync across Users (ADR 0036): watch upkeep and the dispatch of Instant Sync Requests.

Both run beside the scheduler and, like it, read every User through the installation-wide unit
of work (ADR 0029). Each User's own work still runs with that User's units: their watch upkeep,
each rule's run through the scheduled pass, and each acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
)
from calendar_sync.application.operations.scheduled_pass import (
    ScheduledPass,
    ScheduledRun,
    fairly_ordered,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.watch_ports import PendingRequest, SyncCadencePolicy
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId, SyncRuleState

logger = logging.getLogger(__name__)

QUIET = timedelta(seconds=10)
"""How long a rule's notices must stay quiet before its instant run, so a burst runs it once."""
MAX_WAIT = timedelta(seconds=30)
"""The longest that notices which keep coming hold a rule's instant run back."""
MIN_GAP = timedelta(seconds=30)
"""The shortest time between two instant runs of one rule."""
UPKEEP_BUDGET = 200
"""Provider calls one upkeep cycle may make across every User; the rest waits a cycle."""


@dataclass(slots=True)
class WatchUpkeep:
    """Keeps every User's Calendar Watches as their rules, preference, and Plan want them.

    Each cycle visits Users with nothing planned yet first, then the others in order of their
    earliest due work, so what waited longest goes first. Disabled Users are visited too: nothing
    is wanted for them, so their watches stop.
    """

    installation: InstallationUnitOfWorkFactory
    upkeep_for: Callable[[UserId], UpkeepWatches | None]
    """A User's own upkeep; None where no provider can watch, as without the master key."""
    cadence: SyncCadencePolicy
    address: str | None
    """The installation's public https address; None when it has none."""
    clock: Clock
    _carried: tuple[UserId, ...] = ()
    """The Users the last cycle never reached, then the User it stopped on; they go first."""

    def run(self, budget: int = UPKEEP_BUDGET) -> None:
        calls = CallBudget(budget)
        with self.installation() as installation:
            owners = self._in_turn(installation.instant_sync_owners())
        self._carried = ()
        for position, owner in enumerate(owners):
            self._keep(owner, calls)
            if calls.exhausted:
                # The Users it never reached go first next cycle, then this one, whose upkeep
                # the budget may have cut short. So a User with a large backlog never stays
                # first forever, and two such Users take turns.
                unreached = owners[position + 1 :]
                self._carried = (*(each.user for each in unreached), owner.user)
                logger.info("Watch upkeep spent its provider call budget; the rest waits a cycle")
                return

    def _in_turn(self, owners: Sequence[InstantSyncOwner]) -> list[InstantSyncOwner]:
        """The Users the last cycle never reached, then the User it stopped on, then those with
        nothing planned yet, whose coverage is missing, then the rest by earliest due work."""
        now = self.clock.now()
        carried = {user: turn for turn, user in enumerate(self._carried)}

        def turn(owner: InstantSyncOwner) -> tuple[int, int, datetime, str]:
            if owner.user in carried:
                return 0, carried[owner.user], now, owner.user.value
            if owner.next_due is None:
                return 1, 0, now, owner.user.value
            return 2, 0, owner.next_due, owner.user.value

        return sorted(owners, key=turn)

    def _keep(self, owner: InstantSyncOwner, calls: CallBudget) -> None:
        """One User's upkeep; a failure waits for the next cycle and holds up nobody else."""
        try:
            upkeep = self.upkeep_for(owner.user)
            if upkeep is not None:
                upkeep.execute(allowed=self._allowed(owner), address=self.address, budget=calls)
        except Exception:
            logger.exception("Upkeep of a User's watches failed; trying again next cycle")

    def _allowed(self, owner: InstantSyncOwner) -> bool:
        """Whether the User may have watches: the installation can be reached, the User is
        active and wants Instant Sync, and their Plan includes it."""
        return (
            self.address is not None
            and not owner.disabled
            and owner.wanted
            and self.cadence.cadence(owner.user).instant
        )


@dataclass(frozen=True, slots=True)
class InstantRun:
    """A rule's run for its Instant Sync Request, and the request's sequence it answers."""

    scheduled: ScheduledRun
    seq: int
    """The request's `requested_seq` when the run was chosen; notices after it stay pending."""


def due_at(request: PendingRequest) -> datetime:
    """When a pending request may run: once its notices were quiet for QUIET, or MAX_WAIT after
    the first, and never within MIN_GAP of the rule's last instant run."""
    settled = min(request.last_requested_at + QUIET, request.first_requested_at + MAX_WAIT)
    if request.last_run_at is None:
        return settled
    return max(settled, request.last_run_at + MIN_GAP)


@dataclass(slots=True)
class InstantDispatch:
    """Chooses which rules run now for their Instant Sync Requests, and runs them.

    A request whose rule may no longer run instantly is acknowledged and dropped: its owner turned
    Instant Sync off, their Plan no longer includes it, or the rule's last run failed, which
    Scheduled Sync retries with its own backoff. Requests of a paused rule or a disabled User are
    not listed, so they wait, and run or are dropped once the rule or User is active again.
    Delivery Evidence never holds a run back: an authenticated notice proves delivery works.
    """

    installation: InstallationUnitOfWorkFactory
    scheduled_pass: ScheduledPass
    requests_for: Callable[[UserId], UnitOfWorkFactory]
    """Each User's units, which acknowledge that User's requests."""
    cadence: SyncCadencePolicy
    clock: Clock

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        """The runs to start now, taking turns between Users, and when the next pending request
        becomes due. Rules in `reserved` are queued or running already and are left alone."""
        now = self.clock.now()
        with self.installation() as installation:
            instant = self._instant_users(installation.instant_sync_owners())
            pending = installation.pending_instant_runs()
        ready: list[PendingInstantRun] = []
        later: list[datetime] = []
        for item in pending:
            if item.scheduled.rule.id.value in reserved:
                continue
            if not _eligible(item, instant):
                self._drop(item, now)
            elif (at := due_at(item.request)) <= now:
                ready.append(item)
            else:
                later.append(at)
        return _fair_runs(ready), min(later, default=None)

    def run(self, item: InstantRun) -> None:
        """Run the rule as the scheduler does, then acknowledge the request whether the run
        succeeded or failed. A notice that came during the run raised the request past the
        captured sequence, so another run follows; a crash before acknowledging runs it again.

        A run may wait in the dispatcher's queue, so the request is read again first. One no
        longer listed waits, as `due` leaves it: its rule was paused or its owner disabled. One
        whose rule may no longer run instantly is dropped without running."""
        scheduled = item.scheduled.scheduled
        current, instant = self._recheck(item)
        if current is None:
            return
        if not _eligible(current, instant):
            self._drop(current, self.clock.now())
            return
        try:
            self.scheduled_pass.run(item.scheduled)
        finally:
            try:
                self._acknowledge(scheduled.owner, scheduled.rule.id, item.seq, self.clock.now())
            except Exception:
                logger.exception(
                    "Could not acknowledge the instant run of rule %s; it runs again",
                    scheduled.rule.id.value,
                )

    def _recheck(self, item: InstantRun) -> tuple[PendingInstantRun | None, frozenset[UserId]]:
        """The run's request as it is pending now, if it still is, and who may run instantly."""
        owner, rule_id = item.scheduled.scheduled.owner, item.scheduled.scheduled.rule.id
        with self.installation() as installation:
            instant = self._instant_users(installation.instant_sync_owners())
            pending = installation.pending_instant_runs()
        current = next(
            (
                each
                for each in pending
                if each.scheduled.owner == owner and each.scheduled.rule.id == rule_id
            ),
            None,
        )
        return current, instant

    def _instant_users(self, owners: Sequence[InstantSyncOwner]) -> frozenset[UserId]:
        """The Users whose rules may run instantly now."""
        return frozenset(
            owner.user
            for owner in owners
            if owner.wanted and not owner.disabled and self.cadence.cadence(owner.user).instant
        )

    def _drop(self, item: PendingInstantRun, now: datetime) -> None:
        """Acknowledge a request no instant run will answer; Scheduled Sync runs the rule."""
        scheduled = item.scheduled
        try:
            self._acknowledge(scheduled.owner, scheduled.rule.id, item.request.requested_seq, now)
        except Exception:
            logger.exception("Could not drop an Instant Sync Request; trying again next look")

    def _acknowledge(self, owner: UserId, rule_id: SyncRuleId, seq: int, at: datetime) -> None:
        with self.requests_for(owner)() as uow:
            uow.instant_requests.acknowledge(rule_id, seq, at)
            uow.commit()


def _eligible(item: PendingInstantRun, instant: frozenset[UserId]) -> bool:
    return (
        item.scheduled.owner in instant
        and item.scheduled.rule.state is SyncRuleState.ENABLED
        and not item.last_run_failed
    )


def _fair_runs(ready: Sequence[PendingInstantRun]) -> tuple[InstantRun, ...]:
    """Due runs taking turns between Users, as a scheduled pass orders its rules."""
    seqs = {
        (item.scheduled.owner, item.scheduled.rule.id): item.request.requested_seq for item in ready
    }
    return tuple(
        InstantRun(ScheduledRun(scheduled, full=False), seqs[scheduled.owner, scheduled.rule.id])
        for scheduled in fairly_ordered([item.scheduled for item in ready])
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/adapters/test_user_isolation_schema.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/operations/instant_sync.py tests/application/test_instant_dispatch.py
git commit -m "Run a rule soon after its Watch Notices, and acknowledge each run's request

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 15: InstantSyncStatus says whether Instant Sync is on and why each rule syncs as it does

**Files:**
- Modify: `src/calendar_sync/application/operations/instant_sync.py` (adds `InstantSyncStatus`)
- Test: `tests/application/test_instant_sync_status.py`

**Interfaces:**
- Consumes: `UserDirectory.get(user) -> User | None` and `User.instant_sync` (Task 9); `WatchRegistration.address` (only registrations under `f"{address}/"` count); `UnitOfWork.rules.list()`, `UnitOfWork.watches.list()` and `.registrations()` (Tasks 3 and 6); `DeliveryEvidenceLog.evidence(address)`, `SyncCadencePolicy` (Task 3); `instant_sync_availability`, `effective_cadence`, `Availability`, `CadenceReason`, `DeliveryState`, `CalendarWatch.covers` (Tasks 1 and 2).
- Produces: `InstantSyncStatus(users, unit_of_work: Callable[[UserId], UnitOfWorkFactory], cadence, evidence, provider_of: Callable[[ConnectedAccountId], ProviderKind | None], address: str | None, clock)` with `availability(user) -> Availability`, `cadences(user) -> Mapping[SyncRuleId, CadenceReason]`, `poll_every(user) -> timedelta`.

- [ ] **Step 1: Write the failing test**

`tests/application/test_instant_sync_status.py`:

```python
"""What the Web UI reads about Instant Sync: whether it is on for a User, and why each of their
rules syncs as it does (ADR 0036)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.operations.instant_sync import InstantSyncStatus
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    Receipt,
    SyncCadencePolicy,
    notice_address,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.watches import (
    Availability,
    CadenceReason,
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
    WatchScope,
    token_hash,
)
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule
from tests.identity_fakes import MemoryUsers
from tests.users import OTHER_USER, USER, memory_units

ADDRESS = "https://ghost.example.test"
WATCH = CalendarWatch(
    CalendarWatchId("watch-1"),
    rule().source.connected_account_id,
    WatchScope.calendar(rule().source.calendar_id),
)
REGISTRATION = WatchRegistrationId("0123456789abcdef0123456789abcdef")
FAILING = DeliveryEvidence(
    ProviderKind.GOOGLE,
    ADDRESS,
    last_success_at=NOW - timedelta(hours=2),
    last_failure_at=NOW - timedelta(hours=1),
)


class Evidence:
    """Delivery Evidence per provider and address; the status only reads it."""

    def __init__(self, *recorded: DeliveryEvidence) -> None:
        self.recorded = recorded

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        raise AssertionError("the status records nothing")

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        raise AssertionError("the status records nothing")

    def evidence(self, address: str) -> Mapping[ProviderKind, DeliveryEvidence]:
        return {item.provider: item for item in self.recorded if item.address == address}


class Plan:
    def __init__(self, *, instant: bool = True, poll_every: timedelta = SCHEDULED_EVERY) -> None:
        self.allowed = SyncCadence(instant=instant, poll_every=poll_every)

    def cadence(self, user: UserId) -> SyncCadence:
        return self.allowed


def _user(user_id: UserId = USER, *, wanted: bool = True) -> User:
    return User(
        user_id,
        f"{user_id.value}@example.test",
        Role.USER,
        UserState.ACTIVE,
        NOW,
        instant_sync=wanted,
    )


def _status(
    database: InMemoryUnitOfWorkFactory,
    *,
    users: tuple[User, ...] = (_user(),),
    address: str | None = ADDRESS,
    evidence: Evidence | None = None,
    plan: SyncCadencePolicy | None = None,
) -> InstantSyncStatus:
    directory = MemoryUsers()
    for user in users:
        directory.add(user, "hashed:synthetic")
    return InstantSyncStatus(
        users=directory,
        unit_of_work=database.for_user,
        cadence=plan or EveryUserInstant(),
        evidence=evidence or Evidence(),
        provider_of=lambda _account: ProviderKind.GOOGLE,
        address=address,
        clock=FixedClock(),
    )


def _with_rule(
    database: InMemoryUnitOfWorkFactory, user: UserId = USER
) -> InMemoryUserUnitOfWorkFactory:
    units = memory_units(database, user=user)
    with units() as uow:
        uow.rules.add(rule())
        uow.commit()
    return units


def _watched(units: InMemoryUserUnitOfWorkFactory, *, confirmed: bool) -> None:
    """The rule's source covered by a watch whose registration its provider created."""
    created = NOW - timedelta(minutes=5)
    with units() as uow:
        uow.watches.add(WATCH)
        uow.watches.set_coverage(WATCH.id, frozenset({rule().source.calendar_id}))
        uow.watches.add_registration(
            WatchRegistration(
                REGISTRATION,
                WATCH.id,
                RegistrationState.CREATING,
                notice_address(ADDRESS, "google", REGISTRATION),
                token_hash("synthetic-watch-token"),
                created,
                NOW + timedelta(days=7),
            )
        )
        uow.watches.record_receipt(
            REGISTRATION,
            Receipt("synthetic-handle", NOW + timedelta(days=7), confirmed=confirmed),
            NOW + timedelta(days=5),
            created,
        )
        uow.commit()


def test_instant_sync_is_on_for_a_user_who_wants_it_on_an_https_installation() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    status = _status(database)

    assert status.availability(USER) is Availability.ON
    assert status.cadences(USER) == {rule().id: CadenceReason.INSTANT}


OFF: dict[str, tuple[Callable[[InMemoryUnitOfWorkFactory], InstantSyncStatus], Availability]] = {
    "no public address": (
        lambda database: _status(database, address=None),
        Availability.NO_PUBLIC_ADDRESS,
    ),
    "not in plan": (
        lambda database: _status(database, plan=Plan(instant=False)),
        Availability.NOT_IN_PLAN,
    ),
    "turned off": (
        lambda database: _status(database, users=(_user(wanted=False),)),
        Availability.OFF_BY_USER,
    ),
    "deleted meanwhile": (lambda database: _status(database, users=()), Availability.OFF_BY_USER),
    "providers cannot reach it": (
        lambda database: _status(database, evidence=Evidence(FAILING)),
        Availability.NOT_REACHING,
    ),
}


@pytest.mark.parametrize(("make", "expected"), list(OFF.values()), ids=list(OFF))
def test_instant_sync_says_why_it_is_off_and_every_rule_says_the_same(
    make: Callable[[InMemoryUnitOfWorkFactory], InstantSyncStatus], expected: Availability
) -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    status = make(database)

    assert status.availability(USER) is expected
    assert status.cadences(USER) == {rule().id: CadenceReason(expected.value)}


def test_failing_evidence_matters_only_for_providers_the_users_watches_use() -> None:
    database = InMemoryUnitOfWorkFactory()
    _with_rule(database)

    status = _status(database, evidence=Evidence(FAILING))

    assert status.availability(USER) is Availability.ON
    assert status.cadences(USER) == {rule().id: CadenceReason.NOT_WATCHABLE}


def test_evidence_for_another_address_is_not_this_installations() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)
    elsewhere = DeliveryEvidence(
        ProviderKind.GOOGLE,
        "https://old.example.test",
        last_success_at=None,
        last_failure_at=NOW,
    )

    assert _status(database, evidence=Evidence(elsewhere)).availability(USER) is Availability.ON


def test_a_registration_its_provider_has_not_confirmed_waits_for_the_provider() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=False)

    assert _status(database).cadences(USER) == {rule().id: CadenceReason.WAITING_FOR_PROVIDER}


def test_a_registration_for_an_earlier_address_never_makes_a_rule_instant() -> None:
    database = InMemoryUnitOfWorkFactory()
    _watched(_with_rule(database), confirmed=True)

    moved = _status(database, address="https://new.example.test")

    assert moved.availability(USER) is Availability.ON
    assert moved.cadences(USER) == {rule().id: CadenceReason.WAITING_FOR_PROVIDER}


def test_another_users_watch_never_makes_a_rule_instant() -> None:
    database = InMemoryUnitOfWorkFactory()
    _with_rule(database)
    _watched(_with_rule(database, OTHER_USER), confirmed=True)

    status = _status(database, users=(_user(), _user(OTHER_USER)))

    assert status.cadences(USER) == {rule().id: CadenceReason.NOT_WATCHABLE}
    assert status.cadences(OTHER_USER) == {rule().id: CadenceReason.INSTANT}


def test_rules_are_polled_as_often_as_the_plan_says() -> None:
    status = _status(InMemoryUnitOfWorkFactory(), plan=Plan(poll_every=timedelta(minutes=15)))

    assert status.poll_every(USER) == timedelta(minutes=15)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/application/test_instant_sync_status.py -q`
Expected: FAIL (`ImportError: cannot import name 'InstantSyncStatus' from 'calendar_sync.application.operations.instant_sync'`)

- [ ] **Step 3: Implement**

In `src/calendar_sync/application/operations/instant_sync.py`, replace the module docstring and the import block with:

```python
"""Instant Sync across Users (ADR 0036): watch upkeep, the dispatch of Instant Sync Requests,
and what the Web UI reads about both.

Upkeep and dispatch run beside the scheduler and, like it, read every User through the
installation-wide unit of work (ADR 0029). Each User's own work still runs with that User's
units: their watch upkeep, each rule's run through the scheduled pass, and each acknowledgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.operations.ports import (
    InstallationUnitOfWorkFactory,
    InstantSyncOwner,
    PendingInstantRun,
)
from calendar_sync.application.operations.scheduled_pass import (
    ScheduledPass,
    ScheduledRun,
    fairly_ordered,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.instant_sync import CallBudget, UpkeepWatches
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    PendingRequest,
    SyncCadencePolicy,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    ConnectedAccountId,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.watches import (
    Availability,
    CadenceReason,
    CalendarWatch,
    DeliveryState,
    WatchRegistration,
    effective_cadence,
    instant_sync_availability,
)
```

and append at the end of the module:

```python
@dataclass(slots=True)
class InstantSyncStatus:
    """Whether Instant Sync is on for a User, and why each of their rules syncs as it does.

    The account switch and the rule pages read it. It reads the User's own records, their
    preference, their Plan's cadence, and the Delivery Evidence of the installation's address.
    """

    users: UserDirectory
    unit_of_work: Callable[[UserId], UnitOfWorkFactory]
    cadence: SyncCadencePolicy
    evidence: DeliveryEvidenceLog
    provider_of: Callable[[ConnectedAccountId], ProviderKind | None]
    address: str | None
    """The installation's public https address; None when it cannot offer Instant Sync."""
    clock: Clock

    def availability(self, user: UserId) -> Availability:
        with self.unit_of_work(user)() as uow:
            watches = tuple(uow.watches.list())
        return self._availability(user, watches)

    def cadences(self, user: UserId) -> Mapping[SyncRuleId, CadenceReason]:
        """Each rule's Effective Cadence: instant, or why Scheduled Sync runs it instead."""
        with self.unit_of_work(user)() as uow:
            rules = tuple(uow.rules.list())
            watches = tuple(uow.watches.list())
            registrations = tuple(uow.watches.registrations())
        availability = self._availability(user, watches)
        now = self.clock.now()
        # A registration made for an earlier public address delivers nowhere this one hears.
        current = tuple(
            registration
            for registration in registrations
            if self.address is not None and registration.address.startswith(f"{self.address}/")
        )
        return {
            rule.id: _cadence_of(rule.source, availability, watches, current, now) for rule in rules
        }

    def poll_every(self, user: UserId) -> timedelta:
        """How often Scheduled Sync runs the User's rules, as their Plan says."""
        return self.cadence.cadence(user).poll_every

    def _availability(self, user: UserId, watches: Sequence[CalendarWatch]) -> Availability:
        found = self.users.get(user)
        return instant_sync_availability(
            address_is_https=self.address is not None,
            cadence=self.cadence.cadence(user),
            wanted=found is not None and found.instant_sync,
            delivery=self._delivery(watches),
        )

    def _delivery(self, watches: Sequence[CalendarWatch]) -> tuple[DeliveryState, ...]:
        """The Delivery State of each provider the User's watched sources use, at this
        installation's address; evidence for another address says nothing about this one."""
        if self.address is None or not watches:
            return ()
        evidence = self.evidence.evidence(self.address)
        providers = {self.provider_of(watch.account) for watch in watches}
        return tuple(
            evidence[provider].state if provider in evidence else DeliveryState.UNKNOWN
            for provider in providers
            if provider is not None
        )


def _cadence_of(
    source: CalendarEndpoint,
    availability: Availability,
    watches: Sequence[CalendarWatch],
    registrations: Sequence[WatchRegistration],
    now: datetime,
) -> CadenceReason:
    """One rule's Effective Cadence, from the watch covering its Source Calendar, if any."""
    watch = next((each for each in watches if each.covers(source)), None)
    own = tuple(
        registration
        for registration in registrations
        if watch is not None and registration.watch_id == watch.id
    )
    return effective_cadence(availability, watch, own, now)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/application/test_instant_sync_status.py tests/application/test_instant_dispatch.py tests/application/test_watch_upkeep.py tests/test_architecture.py tests/test_provider_neutrality.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/operations/instant_sync.py tests/application/test_instant_sync_status.py
git commit -m "Say whether Instant Sync is on for a User and why each rule syncs as it does

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 16: Run Instant Sync's loops beside the scheduler, and stop watches before deletion and disconnection

**Files:**
- Modify: `src/calendar_sync/infrastructure/scheduling.py` (adds `InstantSyncDispatcher`, `WatchKeeper`)
- Modify: `src/calendar_sync/application/identity/administration.py` (`OwnedRules.stop_watches`; User Deletion stops watches first)
- Modify: `src/calendar_sync/application/sync/accounts.py` (`DisconnectConnectedAccount.stop_watches`)
- Modify: `src/calendar_sync/bootstrap/container.py` (adapters, per-User upkeep, loops, status, container fields, `instant_sync_address`)
- Modify: `src/calendar_sync/interfaces/api/app.py` (lifespan starts and cancels both loops)
- Test: `tests/adapters/test_instant_sync_loops.py`
- Test: `tests/application/test_user_deletion.py` (two tests; `Installation.owned` records stops)
- Test: `tests/application/test_accounts.py` (two tests)

**Interfaces:**
- Consumes: `InstantDispatch.due/run`, `InstantRun`, `WatchUpkeep.run` (Tasks 13 and 14); `InstantSyncStatus` (Task 15); `UpkeepWatches(unit_of_work, providers, evidence, clock, lapses=None, call_stats=...)`, `WatchProviders(watcher_for, provider_of, slug_of, backoff=...)`, `AccountBackoff()`, `UpkeepWatches.stop_all(account=None)` (Task 4); `EveryUserInstant`, `NoticeReader`, `DeliveryEvidenceLog` (Task 3); `WatchNoticeInbox` (Task 9); `SqliteWatchNoticeInbox(database)`, `SqliteDeliveryEvidenceLog(database)` (Task 7); `RoutingCalendarWatcher.of(kinds, providers)` with `__call__` and `provider_of`, `ProviderDirectory.slug_of`, `ProviderDescriptor.notice_reader` (Task 12).
- Produces: `Adapters.delivery_evidence: DeliveryEvidenceLog`, `Adapters.watch_inbox: WatchNoticeInbox`, `Adapters.watchers: RoutingCalendarWatcher | None`, `Adapters.sync_cadence: SyncCadencePolicy`, `Adapters.watch_backoff: AccountBackoff` (one per process); `InstantSyncDispatcher(dispatch, concurrency=2, clock=None, longest_sleep_seconds=60.0)` with `wake()` and `run_forever()`; `WatchKeeper(upkeep, interval_seconds=300)` with `run_forever()`; `bootstrap.container.instant_sync_address(settings) -> str | None`; `Container.instant_dispatcher`, `.watch_keeper`, `.watch_inbox`, `.notice_readers: Mapping[str, tuple[ProviderKind, NoticeReader]]`, `.instant_sync_status: InstantSyncStatus`, `.instant_sync_address: str | None`; `UserServices.instant_sync_status`, `UserServices.watch_upkeep: UpkeepWatches | None`; `OwnedRules.stop_watches: Callable[[], None]`; `DisconnectConnectedAccount.stop_watches: Callable[[ConnectedAccountId], None]`.

- [ ] **Step 1: Write the failing tests**

`tests/adapters/test_instant_sync_loops.py`:

```python
"""Instant Sync's loops beside the scheduler: the dispatcher that starts instant runs, the keeper
that runs watch upkeep, and how the service composes, starts, and stops them (ADR 0036)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.operations.instant_sync import InstantRun
from calendar_sync.application.operations.scheduled_pass import ScheduledRun
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container, instant_sync_address
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.scheduling import InstantSyncDispatcher, WatchKeeper
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import rule
from tests.users import USER

ADDRESS = "https://ghost.example.test"


def _instant(rule_id: str) -> InstantRun:
    scheduled = ScheduledRule(USER, replace(rule(), id=SyncRuleId(rule_id)), None)
    return InstantRun(ScheduledRun(scheduled, full=False), seq=1)


async def _until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def _running(dispatcher: InstantSyncDispatcher, condition: Callable[[], bool]) -> None:
    """Run the dispatcher until `condition` holds, then stop it as the service does."""
    task = asyncio.create_task(dispatcher.run_forever())
    try:
        await _until(condition)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class Offering:
    """Offers each of its rules whenever it is not reserved, as rules whose notices keep coming,
    and records how many run at once."""

    def __init__(self, *rules: str, hold: float = 0.01, failing: bool = False) -> None:
        self.rules, self.hold, self.failing = rules, hold, failing
        self.running: dict[str, int] = {}
        self.most_of_one = 0
        self.most_at_once = 0
        self.runs = 0
        self.lock = threading.Lock()

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        return tuple(_instant(each) for each in self.rules if each not in reserved), None

    def run(self, item: InstantRun) -> None:
        key = item.scheduled.scheduled.rule.id.value
        with self.lock:
            self.running[key] = self.running.get(key, 0) + 1
            self.most_of_one = max(self.most_of_one, self.running[key])
            self.most_at_once = max(self.most_at_once, sum(self.running.values()))
        time.sleep(self.hold)
        with self.lock:
            self.running[key] -= 1
            self.runs += 1
        if self.failing:
            raise RuntimeError("synthetic run failure")


class Looking:
    """Nothing is due; it counts the looks, and may say when the next request is due."""

    def __init__(
        self,
        next_due: Callable[[], datetime] | None = None,
        failing_looks: int = 0,
    ) -> None:
        self.next_due, self.failing_looks = next_due, failing_looks
        self.looks: list[float] = []

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
        self.looks.append(time.monotonic())
        if len(self.looks) <= self.failing_looks:
            raise RuntimeError("database is locked")
        return (), self.next_due() if self.next_due is not None else None

    def run(self, item: InstantRun) -> None:
        raise AssertionError("nothing is due")


def test_the_dispatcher_never_runs_one_rule_twice_at_once() -> None:
    dispatch = Offering("rule-1")

    asyncio.run(_running(InstantSyncDispatcher(dispatch), lambda: dispatch.runs >= 3))

    assert dispatch.most_of_one == 1


def test_the_dispatcher_runs_no_more_rules_at_once_than_its_concurrency() -> None:
    dispatch = Offering("rule-1", "rule-2", "rule-3", "rule-4", hold=0.05)

    asyncio.run(
        _running(InstantSyncDispatcher(dispatch, concurrency=2), lambda: dispatch.runs >= 4)
    )

    assert dispatch.most_at_once == 2


def test_a_wake_from_another_thread_makes_the_dispatcher_look_at_once() -> None:
    dispatch = Looking()
    # With nothing due it would otherwise sleep its longest, a minute.
    dispatcher = InstantSyncDispatcher(dispatch)

    async def scenario() -> None:
        task = asyncio.create_task(dispatcher.run_forever())
        await _until(lambda: len(dispatch.looks) == 1)
        threading.Thread(target=dispatcher.wake).start()
        await _until(lambda: len(dispatch.looks) == 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_the_dispatcher_looks_again_when_the_next_request_becomes_due() -> None:
    clock = SystemClock()
    dispatch = Looking(next_due=lambda: clock.now() + timedelta(milliseconds=50))

    asyncio.run(
        _running(InstantSyncDispatcher(dispatch, clock=clock), lambda: len(dispatch.looks) >= 2)
    )

    assert dispatch.looks[1] - dispatch.looks[0] >= 0.03


def test_waking_the_dispatcher_before_it_starts_is_harmless() -> None:
    dispatch = Looking()

    InstantSyncDispatcher(dispatch).wake()

    assert dispatch.looks == []


def test_a_failed_look_or_run_never_ends_the_dispatcher(caplog: pytest.LogCaptureFixture) -> None:
    looking = Looking(failing_looks=1)
    failing = Offering("rule-1", failing=True)

    with caplog.at_level("ERROR", logger="calendar_sync.infrastructure.scheduling"):
        asyncio.run(
            _running(
                InstantSyncDispatcher(looking, longest_sleep_seconds=0.01),
                lambda: len(looking.looks) >= 2,
            )
        )
        asyncio.run(_running(InstantSyncDispatcher(failing), lambda: failing.runs >= 2))

    assert "Choosing instant runs failed; looking again shortly" in caplog.text
    assert "Instant run of rule rule-1 failed" in caplog.text


def test_stopping_the_dispatcher_lets_a_running_run_finish_its_acknowledgement() -> None:
    release, finished = threading.Event(), threading.Event()

    class Holding:
        def __init__(self) -> None:
            self.started = threading.Event()

        def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]:
            if "rule-1" in reserved or self.started.is_set():
                return (), None
            return (_instant("rule-1"),), None

        def run(self, item: InstantRun) -> None:
            self.started.set()
            release.wait(5)
            finished.set()

    dispatch = Holding()

    async def scenario() -> None:
        task = asyncio.create_task(InstantSyncDispatcher(dispatch).run_forever())
        await _until(dispatch.started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()

    asyncio.run(scenario())

    # The run's thread acknowledges its request; a request never acknowledged stays durable.
    assert finished.wait(5)


def test_the_watch_keeper_runs_upkeep_each_interval_and_survives_a_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Upkeep:
        def __init__(self) -> None:
            self.cycles = 0

        def run(self) -> None:
            self.cycles += 1
            if self.cycles == 1:
                raise RuntimeError("synthetic provider outage")

    upkeep = Upkeep()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("calendar_sync.infrastructure.scheduling.asyncio.sleep", sleep)

    with (
        caplog.at_level("ERROR", logger="calendar_sync.infrastructure.scheduling"),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(WatchKeeper(upkeep, interval_seconds=300).run_forever())

    assert upkeep.cycles == 2
    assert sleeps == [300, 300]
    assert [record.getMessage() for record in caplog.records] == [
        "Watch upkeep failed; trying again at the next interval"
    ]


@pytest.mark.parametrize(
    ("public_url", "with_key", "offered"),
    [
        (ADDRESS, True, True),
        ("http://ghost.example.test", True, False),
        ("", True, False),
        (ADDRESS, False, False),
    ],
    ids=["https", "http", "no address", "no master key"],
)
def test_instant_sync_runs_only_with_a_public_https_address_and_the_master_key(
    tmp_path: Path, public_url: str, with_key: bool, offered: bool
) -> None:
    settings = Settings(
        tmp_path / "test.db",
        master_key=CredentialCipher.generate_key() if with_key else "",
        public_url=public_url,
    )

    container = build_container(settings)

    present = {
        container.instant_dispatcher is not None,
        container.watch_keeper is not None,
        container.watch_inbox is not None,
    }
    assert present == {offered}
    assert container.instant_sync_address == (ADDRESS if offered else None)
    assert container.instant_sync_status.address == container.instant_sync_address


def test_providers_deliver_only_to_an_https_address_at_the_root_of_its_host(
    tmp_path: Path,
) -> None:
    def address(public_url: str) -> str | None:
        return instant_sync_address(Settings(tmp_path / "test.db", public_url=public_url))

    assert address("https://ghost.example.test/") == ADDRESS
    assert address("http://ghost.example.test") is None
    assert address("https://ghost.example.test/calendar") is None
    assert address("") is None


def test_each_user_keeps_their_own_watches_where_accounts_can_be_stored(tmp_path: Path) -> None:
    keyed = build_container(
        Settings(tmp_path / "keyed.db", master_key=CredentialCipher.generate_key())
    )
    unkeyed = build_container(Settings(tmp_path / "unkeyed.db"))

    assert keyed.for_user(USER).watch_upkeep is not None
    assert unkeyed.for_user(USER).watch_upkeep is None


def test_notice_readers_are_found_by_the_slug_in_their_address(tmp_path: Path) -> None:
    settings = Settings(
        tmp_path / "test.db", master_key=CredentialCipher.generate_key(), public_url=ADDRESS
    )

    container = build_container(settings)

    assert container.notice_readers
    for slug, (kind, _reader) in container.notice_readers.items():
        descriptor = container.providers.at(slug)
        assert descriptor is not None
        assert descriptor.kind is kind


class Looping:
    """A loop the service starts in its lifespan and cancels when it stops."""

    def __init__(self) -> None:
        self.started = False
        self.cancelled = False

    async def run_forever(self) -> None:
        self.started = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_the_service_starts_and_stops_instant_syncs_loops_beside_the_scheduler(
    tmp_path: Path,
) -> None:
    dispatcher, keeper = Looping(), Looping()
    container = replace(
        build_container(Settings(tmp_path / "test.db")),
        instant_dispatcher=cast(InstantSyncDispatcher, dispatcher),
        watch_keeper=cast(WatchKeeper, keeper),
    )

    with TestClient(create_app(container)) as client:
        client.get("/health")
        started = (dispatcher.started, keeper.started)

    assert started == (True, True)
    assert (dispatcher.cancelled, keeper.cancelled) == (True, True)
```

In `tests/application/test_user_deletion.py`, change `Installation.__init__` to also set, after `self.locks = RuleLocks()`:

```python
        self.stopped: list[tuple[UserId, bool]] = []
        """Whose watches were stopped, and whether the User still existed then."""
        self.stopping_fails = False
```

replace `Installation.owned` with:

```python
def owned(self, user_id: UserId) -> OwnedRules:
    units = self.database.for_user(user_id)
    return OwnedRules(
        units,
        RemoveSyncRule(units, self.deleter, _Authorizations(units), FixedClock(), self.locks),
        lambda: self._stop_watches(user_id),
    )


def _stop_watches(self, user_id: UserId) -> None:
    self.stopped.append((user_id, self.users.get(user_id) is not None))
    if self.stopping_fails:
        raise RuntimeError("synthetic provider outage")
```

and append:

```python
def test_deleting_a_user_stops_their_watches_before_their_records_go() -> None:
    installation = Installation()

    installation.delete_user().execute(ADMIN.id, MEMBER.id)

    assert installation.stopped == [(MEMBER.id, True)]
    assert installation.users.get(MEMBER.id) is None


def test_watches_that_cannot_be_stopped_never_hold_a_deletion_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    installation = Installation()
    installation.stopping_fails = True

    with caplog.at_level("ERROR", logger="calendar_sync.application.identity.administration"):
        result = installation.delete_own().execute(MEMBER.id, PASSWORD, ProjectionHandling.DELETE)

    assert result.rules == 1
    assert installation.stopped == [(MEMBER.id, True)]
    assert installation.users.get(MEMBER.id) is None
    assert "Could not stop the watches of a User being deleted" in caplog.text
```

In `tests/application/test_accounts.py`, append:

```python
def test_disconnecting_stops_the_accounts_watches_while_its_credentials_remain() -> None:
    affected = replace(_rule("affected", ACCOUNT.value), state=SyncRuleState.ENABLED)
    unit_of_work = _with_rules(affected)
    accounts = RecordingAccounts(_account())
    stopped: list[tuple[ConnectedAccountId, bool, SyncRuleState]] = []

    def stop(account_id: ConnectedAccountId) -> None:
        rule_state = unit_of_work.state.rules[affected.id].state
        stopped.append((account_id, accounts.is_connected(account_id), rule_state))

    DisconnectConnectedAccount(unit_of_work, accounts, RuleLocks(), stop).execute(ACCOUNT)

    # The rule stopped first, so upkeep wants no watch for it, and the account still connected.
    assert stopped == [(ACCOUNT, True, SyncRuleState.DEGRADED)]


def test_watches_that_cannot_be_stopped_never_hold_a_disconnection_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    accounts = RecordingAccounts(_account())

    def stop(_account_id: ConnectedAccountId) -> None:
        raise RuntimeError("synthetic provider outage")

    with caplog.at_level("ERROR", logger="calendar_sync.application.sync.accounts"):
        disconnected = DisconnectConnectedAccount(
            _with_rules(), accounts, RuleLocks(), stop
        ).execute(ACCOUNT)

    assert disconnected.account.state is ConnectedAccountState.DISCONNECTED
    assert "Could not stop the watches of a disconnecting account" in caplog.text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_loops.py tests/application/test_user_deletion.py tests/application/test_accounts.py -q`
Expected: FAIL (`ImportError: cannot import name 'InstantSyncDispatcher' from 'calendar_sync.infrastructure.scheduling'`; `TypeError: OwnedRules.__init__() takes 3 positional arguments but 4 were given`; `TypeError: DisconnectConnectedAccount.__init__() takes 4 positional arguments but 5 were given`)

- [ ] **Step 3: Implement the loops**

In `src/calendar_sync/infrastructure/scheduling.py`, change the module docstring and imports to:

```python
"""When scheduled passes, instant runs, and watch upkeep run, and how many at once; what each
does is application policy in `application/operations/scheduled_pass.py` and
`application/operations/instant_sync.py`."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Collection
from contextlib import suppress
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from calendar_sync.application.operations.installation_health import (
    InstallationIncidentWatch,
    InstallationNotifications,
)
from calendar_sync.application.operations.instant_sync import InstantRun
from calendar_sync.application.operations.ports import SchedulerHeartbeat, SchedulerProgress
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledRun
from calendar_sync.application.shared.ports import Clock
from calendar_sync.infrastructure.clock import SystemClock
```

and append at the end of the module:

```python
class InstantRuns(Protocol):
    """What the dispatcher asks of `InstantDispatch`."""

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]: ...

    def run(self, item: InstantRun) -> None: ...


class InstantSyncDispatcher:
    """Starts instant runs as Watch Notices make them due (ADR 0036).

    The notice route wakes it from its worker thread. Otherwise it looks again when the next
    pending request becomes due, and at least every `longest_sleep_seconds`. A rule it queued
    stays reserved until its run ends, so it never runs one rule twice at once, and at most
    `concurrency` runs go together, apart from the scheduler's. A run meeting a rule a scheduled
    or manual run holds waits for the rule's lock. Requests are durable: stopping loses none.
    """

    def __init__(
        self,
        dispatch: InstantRuns,
        concurrency: int = 2,
        clock: Clock | None = None,
        longest_sleep_seconds: float = 60.0,
    ) -> None:
        self._dispatch = dispatch
        self._concurrency = concurrency
        self._clock = clock or SystemClock()
        self._longest_sleep = longest_sleep_seconds
        self._reserved: set[str] = set()
        self._runs: set[asyncio.Task[None]] = set()
        # Set while the loop runs; wake() reads them from request threads.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._woken: asyncio.Event | None = None

    def wake(self) -> None:
        """Look for due runs now; safe from any thread. Before the loop starts there is nothing
        to wake: its first look finds every pending request."""
        loop, woken = self._loop, self._woken
        if loop is None or woken is None:
            return
        # The loop may close while the service stops; the request stays durable.
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(woken.set)

    async def run_forever(self) -> None:
        woken = asyncio.Event()
        self._woken, self._loop = woken, asyncio.get_running_loop()
        slots = asyncio.Semaphore(self._concurrency)
        try:
            while True:
                # Cleared before looking, so a wake during the look is not lost.
                woken.clear()
                delay = await self._start_due(slots)
                with suppress(TimeoutError):
                    await asyncio.wait_for(woken.wait(), delay)
        finally:
            self._woken, self._loop = None, None
            for task in self._runs:
                task.cancel()

    async def _start_due(self, slots: asyncio.Semaphore) -> float:
        """Start every due run; how long to wait before looking again."""
        try:
            runs, next_due = await asyncio.to_thread(self._dispatch.due, frozenset(self._reserved))
        except Exception:
            logger.exception("Choosing instant runs failed; looking again shortly")
            return self._longest_sleep
        for item in runs:
            rule_id = item.scheduled.scheduled.rule.id.value
            self._reserved.add(rule_id)
            task = asyncio.create_task(self._run(item, rule_id, slots))
            self._runs.add(task)
            task.add_done_callback(self._runs.discard)
        if next_due is None:
            return self._longest_sleep
        wait = (next_due - self._clock.now()).total_seconds()
        return min(max(wait, 0.0), self._longest_sleep)

    async def _run(self, item: InstantRun, rule_id: str, slots: asyncio.Semaphore) -> None:
        try:
            async with slots:
                await asyncio.to_thread(self._dispatch.run, item)
        except Exception:
            logger.exception(
                "Instant run of rule %s failed; Scheduled Sync runs it meanwhile", rule_id
            )
        finally:
            self._reserved.discard(rule_id)
            # A notice that came during the run may have made the rule due again.
            if self._woken is not None:
                self._woken.set()


class WatchCycle(Protocol):
    """One upkeep cycle across every User, as `WatchUpkeep.run` does it."""

    def run(self) -> None: ...


class WatchKeeper:
    """Runs watch upkeep every interval in a worker thread, so slow provider calls never delay a
    rule's run or the scheduler's heartbeat (ADR 0036)."""

    def __init__(self, upkeep: WatchCycle, interval_seconds: int = 300) -> None:
        self._upkeep = upkeep
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        while True:
            # As for the scheduler: a failed cycle must not end the loop, and cancellation,
            # a BaseException, still stops it.
            try:
                await asyncio.to_thread(self._upkeep.run)
            except Exception:
                logger.exception("Watch upkeep failed; trying again at the next interval")
            await asyncio.sleep(self._interval_seconds)
```

- [ ] **Step 4: Implement the stops before User Deletion and disconnection**

In `src/calendar_sync/application/identity/administration.py`, add `import logging` to the
standard-library imports, add after the imports:

```python
logger = logging.getLogger(__name__)
```

replace `OwnedRules` with:

```python
@dataclass(frozen=True, slots=True)
class OwnedRules:
    """What deleting a User needs of their own records: that User's units, Rule Removal, and
    stopping their Calendar Watches at the provider."""

    unit_of_work: UnitOfWorkFactory
    removal: RemoveSyncRule
    stop_watches: Callable[[], None] = lambda: None
    """Stops the User's watches, best effort; their rows go with the User."""
```

in `DeleteUser.execute`, replace

```python
result = _remove_rules(self.owned(user.id), ProjectionHandling.DELETE, keep_unreachable=True)
self.users.delete(user.id)
return result
```

with

```python
        owned = self.owned(user.id)
        result = _remove_rules(owned, ProjectionHandling.DELETE, keep_unreachable=True)
        _stop_watches(owned)
        self.users.delete(user.id)
        return result
```

in `DeleteOwnAccount.execute`, replace

```python
        result = _remove_rules(self.owned(user.id), handling, keep_unreachable=False)
        self.users.delete(user.id)
```

with

```python
        owned = self.owned(user.id)
        result = _remove_rules(owned, handling, keep_unreachable=False)
        _stop_watches(owned)
        self.users.delete(user.id)
```

and add before `def _remove_rules(`:

```python
def _stop_watches(owned: OwnedRules) -> None:
    """Stop the User's watches before their records go, so providers stop sending notices
    sooner; a watch that cannot be stopped expires at its provider, and holds nothing back."""
    try:
        owned.stop_watches()
    except Exception:
        logger.exception("Could not stop the watches of a User being deleted; they expire")
```

In `src/calendar_sync/application/sync/accounts.py`, change the imports to start with

```python
import logging
from collections.abc import Callable, Iterable, Sequence
```

add after the imports:

```python
logger = logging.getLogger(__name__)
```

replace `DisconnectConnectedAccount` with:

```python
@dataclass(slots=True)
class DisconnectConnectedAccount:
    """Discard an account's credentials after degrading every rule that could still write.

    Each rule stops in its own transaction, then the account disconnects, so an interruption can
    leave some rules stopped and the account still connected. That state is safe: a stopped rule
    writes nothing and restarts only through a preview, as it would after the disconnection the
    User asked for. The User sees the account still connected and retries, which stops the
    remaining rules and then disconnects it. So retrying completes it, and it is not made atomic
    as deletion is. The account's Calendar Watches stop just before, best effort, while the
    credentials that stopping them needs still exist.
    """

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    locks: RuleLocks
    stop_watches: Callable[[ConnectedAccountId], None] = lambda _account: None
    """Stops and removes the account's Calendar Watches, best effort."""

    def execute(self, account_id: ConnectedAccountId) -> ConnectedAccountSummary:
        if not any(account.id == account_id for account in self.accounts.list()):
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        with self.unit_of_work() as uow:
            affected = _affected_rules(uow.rules.list(), account_id)
        for rule_id in affected:
            # Waiting for an in-flight write means none happens with the account once degraded.
            with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
                rule = uow.rules.get(rule_id)
                stopped = rule.on_account_disconnected() if rule is not None else None
                if stopped is not None and stopped != rule:
                    uow.rules.save(stopped)
                    uow.commit()
        _stop_watches(self.stop_watches, account_id)
        account = self.accounts.disconnect(account_id)
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return _summary(account, rules)


def _stop_watches(
    stop: Callable[[ConnectedAccountId], None], account_id: ConnectedAccountId
) -> None:
    try:
        stop(account_id)
    except Exception:
        logger.exception("Could not stop the watches of a disconnecting account; they expire")
```

- [ ] **Step 5: Compose and start the loops**

In `src/calendar_sync/bootstrap/container.py`:

Change `from collections.abc import Callable, Sequence` to
`from collections.abc import Callable, Mapping, Sequence`, and add these imports in their
sorted places:

```python
from calendar_sync.application.operations.instant_sync import (
    InstantDispatch,
    InstantSyncStatus,
    WatchUpkeep,
)
from calendar_sync.application.operations.ports import WatchNoticeInbox
from calendar_sync.application.sync.instant_sync import (
    AccountBackoff,
    UpkeepWatches,
    WatchProviders,
)
from calendar_sync.application.sync.watch_ports import (
    DeliveryEvidenceLog,
    EveryUserInstant,
    NoticeReader,
    SyncCadencePolicy,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.watch_inbox import (
    SqliteDeliveryEvidenceLog,
    SqliteWatchNoticeInbox,
)
from calendar_sync.infrastructure.providers.routing import (
    RoutingAccountCalendars,
    RoutingCalendarProvider,
    RoutingCalendarWatcher,
)
from calendar_sync.infrastructure.scheduling import (
    InstantSyncDispatcher,
    SchedulerWatch,
    SyncScheduler,
    WatchKeeper,
)
```

(`WatchNoticeInbox` joins the existing `application.operations.ports` import; the
`routing` and `scheduling` imports replace the existing ones.)

In `UserServices`, after `lapsed_authorizations: LapsedAuthorizations`, add:

```python
    instant_sync_status: InstantSyncStatus
    """Whether Instant Sync is on for a User, and why each of their rules syncs as it does."""
    watch_upkeep: UpkeepWatches | None
    """Keeps this User's Calendar Watches; None where accounts cannot be stored."""
```

In `Container`, after `sends_email: bool` and its docstring, add:

```python
    instant_dispatcher: InstantSyncDispatcher | None
    """Starts rules' instant runs; None unless the installation can offer Instant Sync."""
    watch_keeper: WatchKeeper | None
    """Keeps every User's Calendar Watches; None unless the installation can offer Instant Sync."""
    watch_inbox: WatchNoticeInbox | None
    """Records Watch Notices; None unless the installation can offer Instant Sync, so the notice
    route answers as for an unknown path."""
    notice_readers: Mapping[str, tuple[ProviderKind, NoticeReader]]
    """Each provider's notice reader, by the slug in its notice address."""
    instant_sync_status: InstantSyncStatus
    instant_sync_address: str | None
    """The public https address providers deliver Watch Notices to; None when there is none."""
```

In `Adapters`, after `token_authentication: IntegrationTokenAuthentication`, add:

```python
    delivery_evidence: DeliveryEvidenceLog
    """Whether each provider's Watch Notices reach the installation's address."""
    watch_inbox: WatchNoticeInbox
```

and after `account_calendars: AccountCalendars | None = None` and its docstring, add:

```python
    watchers: RoutingCalendarWatcher | None = None
    """Each account's provider's Calendar Watcher, where accounts can be stored."""
    sync_cadence: SyncCadencePolicy = field(default_factory=EveryUserInstant)
    """Each User's Sync Cadence; every User may sync instantly while Plans are off (ADR 0028)."""
    watch_backoff: AccountBackoff = field(default_factory=AccountBackoff)
    """One per process: how long each account waits before upkeep asks its provider again,
    shared by every User's upkeep."""
```

In `build_adapters`, add to the `Adapters(...)` call, after `token_authentication=tokens,`:

```python
delivery_evidence = (SqliteDeliveryEvidenceLog(database),)
watch_inbox = (SqliteWatchNoticeInbox(database),)
```

and to the final `replace(...)`, after `calendar_provider=RoutingCalendarProvider.of(accounts, providers),`:

```python
watchers = (RoutingCalendarWatcher.of(accounts, providers),)
```

Replace `compose` with:

```python
def compose(settings: Settings, adapters: Adapters) -> Container:
    def user_services(user_id: UserId) -> UserServices:
        # Read when called, after the scheduler exists: every User's status reads its heartbeat.
        return _compose_user(user_id, adapters, scheduler, instant_status)

    scheduled_pass = ScheduledPass(
        adapters.installation_units,
        lambda owner: _scheduled_services(user_services(owner)),
        adapters.clock,
    )
    runs_rules = adapters.calendar_provider is not None and adapters.accounts is not None
    scheduler = SyncScheduler(scheduled_pass, clock=adapters.clock) if runs_rules else None
    cadence = adapters.sync_cadence
    address = instant_sync_address(settings) if runs_rules else None
    instant_status = InstantSyncStatus(
        adapters.users,
        adapters.unit_of_work,
        cadence,
        adapters.delivery_evidence,
        adapters.watchers.provider_of if adapters.watchers is not None else _no_provider,
        address,
        adapters.clock,
    )
    instant = (
        _instant_sync(adapters, scheduled_pass, user_services, cadence, address)
        if address is not None
        else _InstantSync()
    )
    # Installation Health counts the verdicts People shows, so the two never disagree.
    statuses = UserStatuses(adapters.installation_units, adapters.locks, adapters.clock, scheduler)
    return Container(
        secure_cookies=settings.secure_cookies,
        providers=adapters.providers,
        identity=_identity(adapters),
        administration=_administration(
            adapters, lambda owner: _owned_rules(owner, adapters, user_services(owner))
        ),
        token_authentication=adapters.token_authentication,
        storage=StorageAdministration(
            adapters.database_storage, adapters.locks, adapters.clock, adapters.log_files
        ),
        account_calendars=adapters.account_calendars,
        scheduler=scheduler,
        scheduler_watch=(
            SchedulerWatch(
                scheduler,
                adapters.installation_notifications,
                adapters.clock,
                incidents=InstallationIncidentWatch(adapters.providers.client_secrets),
            )
            if scheduler is not None and adapters.installation_notifications is not None
            else None
        ),
        installation_health=GetInstallationHealth(
            adapters.users,
            lambda users: {user: status.health for user, status in statuses.of(users).items()},
            scheduler,
            adapters.clock,
            _failure_causes(adapters.installation_units),
            adapters.providers.guides,
            adapters.providers.client_secrets,
        ),
        operator_overview=OperatorOverview(
            adapters.users, statuses, adapters.installation_units, adapters.clock
        ),
        sends_email=adapters.sends_email,
        instant_dispatcher=instant.dispatcher,
        watch_keeper=instant.keeper,
        watch_inbox=instant.inbox,
        notice_readers=_notice_readers(adapters.providers),
        instant_sync_status=instant_status,
        instant_sync_address=address,
        user_services=user_services,
    )


@dataclass(frozen=True, slots=True)
class _InstantSync:
    """Instant Sync's loops and notice intake; none unless the installation can offer it."""

    dispatcher: InstantSyncDispatcher | None = None
    keeper: WatchKeeper | None = None
    inbox: WatchNoticeInbox | None = None


def _instant_sync(
    adapters: Adapters,
    scheduled_pass: ScheduledPass,
    user_services: Callable[[UserId], UserServices],
    cadence: SyncCadencePolicy,
    address: str,
) -> _InstantSync:
    """Instant runs share the scheduled pass's path, each User's services, and rule locks."""
    upkeep = WatchUpkeep(
        adapters.installation_units,
        lambda owner: user_services(owner).watch_upkeep,
        cadence,
        address,
        adapters.clock,
    )
    dispatch = InstantDispatch(
        adapters.installation_units,
        scheduled_pass,
        adapters.unit_of_work,
        cadence,
        adapters.clock,
    )
    return _InstantSync(
        InstantSyncDispatcher(dispatch, clock=adapters.clock),
        WatchKeeper(upkeep),
        adapters.watch_inbox,
    )


def _notice_readers(
    providers: ProviderDirectory,
) -> Mapping[str, tuple[ProviderKind, NoticeReader]]:
    """Each provider's notice reader, by the slug in its notice address."""
    return {
        descriptor.guide.slug: (descriptor.kind, descriptor.notice_reader)
        for descriptor in providers.descriptors
        if descriptor.notice_reader is not None
    }


def _owned_rules(owner: UserId, adapters: Adapters, services: UserServices) -> OwnedRules:
    """What deleting `owner` needs: their units, Rule Removal, and stopping their watches."""
    upkeep = services.watch_upkeep
    return OwnedRules(
        adapters.unit_of_work(owner),
        services.remove_sync_rule,
        upkeep.stop_all if upkeep is not None else _no_watches,
    )


def _watch_upkeep(
    adapters: Adapters, unit_of_work: UnitOfWorkFactory, lapses: LapsedAuthorizations
) -> UpkeepWatches | None:
    """One User's watch upkeep, wherever accounts can be stored and so watched."""
    watchers = adapters.watchers
    if watchers is None:
        return None
    return UpkeepWatches(
        unit_of_work,
        WatchProviders(
            watchers,
            watchers.provider_of,
            adapters.providers.slug_of,
            backoff=adapters.watch_backoff,
        ),
        adapters.delivery_evidence,
        adapters.clock,
        lapses=lapses,
        call_stats=adapters.call_stats,
    )


def _account_watches(upkeep: UpkeepWatches | None) -> Callable[[ConnectedAccountId], None]:
    """Stops one account's watches before disconnecting it discards their credentials."""
    if upkeep is None:
        return _no_account_watches
    return upkeep.stop_all


def _no_watches() -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _no_account_watches(_account: ConnectedAccountId) -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _no_provider(_account: ConnectedAccountId) -> ProviderKind | None:
    """Without the master key no account is stored, so none has a provider."""
    return None
```

Change `_compose_user`'s signature to

```python
def _compose_user(
    user_id: UserId,
    adapters: Adapters,
    heartbeat: SchedulerHeartbeat | None,
    instant: InstantSyncStatus,
) -> UserServices:
```

after `call_stats = adapters.call_stats`, add:

```python
    watch_upkeep = _watch_upkeep(adapters, unit_of_work, rule_health.lapses)
```

in its `UserServices(...)` call, after `lapsed_authorizations=rule_health.lapses,`, add:

```python
instant_sync_status = (instant,)
watch_upkeep = (watch_upkeep,)
```

and replace the `disconnect_connected_account=` argument with:

```python
disconnect_connected_account = (
    (
        DisconnectConnectedAccount(unit_of_work, accounts, locks, _account_watches(watch_upkeep))
        if accounts
        else None
    ),
)
```

After `public_address`, add:

```python
def instant_sync_address(settings: Settings) -> str | None:
    """Where providers deliver Watch Notices: the public address, only when it is https, as
    providers deliver nowhere else (ADR 0036)."""
    address = public_address(settings)
    if address is None or urlsplit(address).scheme != "https":
        return None
    return address
```

In `src/calendar_sync/interfaces/api/app.py`, in `lifespan`, after the `scheduler_watch` task,
add:

```python
        if resolved.instant_dispatcher is not None:
            tasks.append(asyncio.create_task(resolved.instant_dispatcher.run_forever()))
        if resolved.watch_keeper is not None:
            tasks.append(asyncio.create_task(resolved.watch_keeper.run_forever()))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_loops.py tests/application/test_user_deletion.py tests/application/test_accounts.py tests/adapters/test_composition.py tests/adapters/test_scheduling.py tests/adapters/test_api_authorization.py tests/test_architecture.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/infrastructure/scheduling.py src/calendar_sync/application/identity/administration.py src/calendar_sync/application/sync/accounts.py src/calendar_sync/bootstrap/container.py src/calendar_sync/interfaces/api/app.py tests/adapters/test_instant_sync_loops.py tests/application/test_user_deletion.py tests/application/test_accounts.py
git commit -m "Run instant runs and watch upkeep beside the scheduler, and stop watches before deletion

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 17: The Watch Notice route, the Instant Sync switch, and each rule's Effective Cadence

**Files:**
- Create: `src/calendar_sync/interfaces/api/routes/watch_notices.py`
- Modify: `src/calendar_sync/interfaces/api/app.py` (route module in the flat list; `NoticeServices` in `ApiServices`)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (Literal aliases, `SignedInUserResponse`, rule summary and detail, `InstantSyncPreferenceRequest`)
- Modify: `src/calendar_sync/interfaces/api/routes/session.py` (`SignedInAnswers`; `signed_in` and `user_response` read availability)
- Modify: `src/calendar_sync/interfaces/api/routes/setup.py`, `routes/users.py` (pass the services to `signed_in`)
- Modify: `src/calendar_sync/interfaces/api/routes/account.py` (`PUT /api/v1/account/instant-sync`)
- Modify: `src/calendar_sync/interfaces/api/routes/rules.py` (cadence fields on list and detail)
- Modify: `src/calendar_sync/bootstrap/container.py` (`IdentityServices.set_instant_sync`)
- Modify: `src/calendar_sync/bootstrap/logs.py` (`NoticePathFilter` on Uvicorn's access log)
- Modify: `AGENTS.md` (public route list)
- Modify: `tests/adapters/test_api_authorization.py` (public route, record-route skip)
- Modify: `tests/adapters/test_schema_enums.py` (two mirrors)
- Modify: `tests/adapters/test_service_logging.py` (access log test)
- Modify: `web/openapi.json`, `web/src/lib/api-schema.ts` (generated)
- Modify: typed Web UI test fixtures (listed in Step 7)
- Test: `tests/adapters/test_instant_sync_api.py`

**Interfaces:**
- Consumes: `Container.watch_inbox`, `.notice_readers`, `.instant_dispatcher`, `.instant_sync_address`, `.instant_sync_status`, `UserServices.instant_sync_status`, `UserServices.user_id` (Task 16); `InstantSyncStatus.availability/cadences/poll_every` (Task 15); `WatchNoticeInbox.record(notices, provider, address_base, at) -> int`, `InboxBusy` (Task 9); `NoticeReader`, `NoticeRequest`, `MalformedNotice`, `NOTICE_PATH` (Task 3); `WatchRegistrationId`, `Availability`, `AVAILABILITY_ANCHORS`, `CadenceReason` (Tasks 1 and 2); `SetInstantSync` (Task 9).
- Produces: `POST /api/v1/watch-notices/{provider_slug}/{registration_id}` (public; `NOTICE_BODY_LIMIT = 65_536`, `VALIDATION_TOKEN_LIMIT = 1_024`); `PUT /api/v1/account/instant-sync`; `SignedInUserResponse.instant_sync: bool`, `.instant_sync_availability`, `.instant_sync_help: str | None`; `RuleSummaryResponse` and `RuleDetailResponse` `.effective_cadence`, `.poll_every_minutes: int`; `InstantSyncPreferenceRequest(instant_sync: bool)`; `bootstrap.logs.NoticePathFilter`.

- [ ] **Step 1: Write the failing tests**

`tests/adapters/test_instant_sync_api.py`:

```python
"""Instant Sync over the Web API: the public Watch Notice route, the User's switch, and each
rule's Effective Cadence (ADR 0036)."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.operations.ports import InboxBusy
from calendar_sync.application.sync.watch_ports import (
    MalformedNotice,
    NoticeKind,
    NoticeRequest,
    WatchNotice,
)
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.watches import WatchRegistrationId
from calendar_sync.infrastructure.scheduling import InstantSyncDispatcher
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.routes.watch_notices import (
    NOTICE_BODY_LIMIT,
    VALIDATION_TOKEN_LIMIT,
)
from tests.helpers import rule
from tests.users import first_user, sign_in, sqlite_units

ADDRESS = "https://ghost.example.test"
REGISTRATION = "0123456789abcdef0123456789abcdef"
TOKEN = "synthetic-watch-token"
NOTICE_PATH = f"/api/v1/watch-notices/google/{REGISTRATION}"


class Reader:
    """A provider's notice reader: a validationToken query asks for an echo, and the body
    b"garbled" is no notice."""

    def __init__(self) -> None:
        self.reads = 0

    def validation_token(self, request: NoticeRequest) -> str | None:
        return request.query.get("validationToken")

    def read(
        self, registration_id: WatchRegistrationId, request: NoticeRequest
    ) -> tuple[WatchNotice, ...]:
        self.reads += 1
        if request.body == b"garbled":
            raise MalformedNotice("synthetic unreadable notice")
        token = request.headers.get("x-watch-token", "")
        return (WatchNotice(registration_id, token, None, NoticeKind.CHANGED),)


class Inbox:
    """The Watch Notice inbox: how many rules each request asks for, or busy storage."""

    def __init__(self, requested: int = 1, *, busy: bool = False) -> None:
        self.requested, self.busy = requested, busy
        self.recorded: list[tuple[tuple[WatchNotice, ...], ProviderKind, str]] = []

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        if self.busy:
            raise InboxBusy("synthetic lock wait")
        self.recorded.append((tuple(notices), provider, address_base))
        return self.requested


class Dispatcher:
    def __init__(self) -> None:
        self.woken = 0

    def wake(self) -> None:
        self.woken += 1

    async def run_forever(self) -> None:
        return None


def _client(
    tmp_path: Path,
    inbox: Inbox,
    *,
    dispatcher: Dispatcher | None = None,
    reader: Reader | None = None,
    address: str | None = ADDRESS,
) -> TestClient:
    container = replace(
        build_container(Settings(tmp_path / "test.db")),
        watch_inbox=inbox,
        notice_readers={"google": (ProviderKind.GOOGLE, reader or Reader())},
        instant_dispatcher=cast(InstantSyncDispatcher, dispatcher or Dispatcher()),
        instant_sync_address=address,
    )
    return TestClient(create_app(container))


def _chunks(size: int, count: int) -> Iterator[bytes]:
    """A body sent in chunks, without a Content-Length."""
    for _ in range(count):
        yield b"x" * size


def test_an_unknown_provider_is_answered_as_any_unknown_api_path(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        unknown = client.post(f"/api/v1/watch-notices/nobody/{REGISTRATION}", content=b"{}")
        elsewhere = client.post("/api/v1/nothing-here", content=b"{}")

    assert unknown.status_code == elsewhere.status_code == 404
    assert unknown.json() == elsewhere.json()
    assert inbox.recorded == []


def test_without_a_public_https_address_no_notice_is_heard(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox, address=None) as client:
        answer = client.post(NOTICE_PATH, content=b"{}")

    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert inbox.recorded == []


def test_a_body_above_the_cap_is_refused_before_it_is_held_whole(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        declared = client.post(NOTICE_PATH, content=b"x" * (NOTICE_BODY_LIMIT + 1))
        streamed = client.post(NOTICE_PATH, content=_chunks(NOTICE_BODY_LIMIT // 2 + 1, 2))
        one_chunk = client.post(NOTICE_PATH, content=_chunks(NOTICE_BODY_LIMIT + 1, 1))
        at_the_cap = client.post(NOTICE_PATH, content=b"x" * NOTICE_BODY_LIMIT)

    assert (declared.status_code, declared.json()["code"]) == (413, "notice_too_large")
    assert (streamed.status_code, streamed.json()["code"]) == (413, "notice_too_large")
    assert (one_chunk.status_code, one_chunk.json()["code"]) == (413, "notice_too_large")
    assert at_the_cap.status_code == 202
    assert len(inbox.recorded) == 1


def test_a_validation_request_is_echoed_before_its_body_is_read(tmp_path: Path) -> None:
    inbox, dispatcher, reader = Inbox(), Dispatcher(), Reader()
    with _client(tmp_path, inbox, dispatcher=dispatcher, reader=reader) as client:
        echoed = client.post(
            NOTICE_PATH,
            params={"validationToken": "synthetic-validation"},
            content=b"x" * (NOTICE_BODY_LIMIT + 1),
            headers={"Content-Type": "text/plain"},
        )
        long = client.post(
            NOTICE_PATH, params={"validationToken": "v" * (VALIDATION_TOKEN_LIMIT + 50)}
        )

    assert echoed.status_code == 200
    assert echoed.headers["content-type"].startswith("text/plain")
    assert echoed.text == "synthetic-validation"
    assert long.text == "v" * VALIDATION_TOKEN_LIMIT
    assert (reader.reads, inbox.recorded, dispatcher.woken) == (0, [], 0)


def test_a_request_that_is_no_notice_is_refused(tmp_path: Path) -> None:
    inbox = Inbox()
    with _client(tmp_path, inbox) as client:
        answer = client.post(NOTICE_PATH, content=b"garbled")

    assert (answer.status_code, answer.json()["code"]) == (400, "malformed_notice")
    assert inbox.recorded == []


def test_busy_storage_asks_the_provider_to_retry(tmp_path: Path) -> None:
    with _client(tmp_path, Inbox(busy=True)) as client:
        answer = client.post(NOTICE_PATH, content=b"{}")

    assert (answer.status_code, answer.json()["code"]) == (503, "inbox_busy")


def test_known_unknown_and_refused_notices_are_answered_alike(tmp_path: Path) -> None:
    requesting, ignoring = Inbox(requested=2), Inbox(requested=0)
    woke, slept = Dispatcher(), Dispatcher()
    headers = {"X-Watch-Token": TOKEN}
    with _client(tmp_path, requesting, dispatcher=woke) as client:
        known = client.post(NOTICE_PATH, content=b"{}", headers=headers)
    with _client(tmp_path, ignoring, dispatcher=slept) as client:
        unknown = client.post(NOTICE_PATH, content=b"{}", headers=headers)
        blank = client.post("/api/v1/watch-notices/google/%20", content=b"{}", headers=headers)

    assert (known.status_code, known.content) == (202, b"")
    assert (unknown.status_code, unknown.content) == (202, b"")
    assert (blank.status_code, blank.content) == (202, b"")
    # Only a notice that requested a run wakes the dispatcher.
    assert (woke.woken, slept.woken) == (1, 0)
    assert requesting.recorded == [
        (
            (WatchNotice(WatchRegistrationId(REGISTRATION), TOKEN, None, NoticeKind.CHANGED),),
            ProviderKind.GOOGLE,
            ADDRESS,
        )
    ]
    assert len(ignoring.recorded) == 1


def test_no_log_line_names_a_notices_registration_token_or_body(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), _client(tmp_path, Inbox()) as client:
        for body in (b'{"value": "synthetic body"}', b"garbled"):
            client.post(NOTICE_PATH, content=body, headers={"X-Watch-Token": TOKEN})
    with caplog.at_level(logging.DEBUG), _client(tmp_path, Inbox(busy=True)) as client:
        client.post(NOTICE_PATH, content=b"{}", headers={"X-Watch-Token": TOKEN})

    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(("calendar_sync", "uvicorn", "fastapi"))
    )
    for secret in (REGISTRATION, TOKEN, "synthetic body"):
        assert secret not in ours


def _signed_in_app(tmp_path: Path, public_url: str) -> TestClient:
    settings = Settings(
        tmp_path / "test.db", master_key=CredentialCipher.generate_key(), public_url=public_url
    )
    container = replace(
        build_container(settings), scheduler=None, instant_dispatcher=None, watch_keeper=None
    )
    return TestClient(create_app(container))


def test_a_user_turns_instant_sync_off_and_on(tmp_path: Path) -> None:
    with _signed_in_app(tmp_path, ADDRESS) as client:
        sign_in(client)
        before = client.get("/api/v1/session").json()["user"]
        off = client.put("/api/v1/account/instant-sync", json={"instant_sync": False}).json()
        after = client.get("/api/v1/session").json()["user"]
        on = client.put("/api/v1/account/instant-sync", json={"instant_sync": True}).json()

    def switch(user: dict[str, object]) -> tuple[object, object, object]:
        return (
            user["instant_sync"],
            user["instant_sync_availability"],
            user["instant_sync_help"],
        )

    assert switch(before) == (True, "on", None)
    assert switch(off) == (False, "off_by_user", None)
    assert switch(after) == (False, "off_by_user", None)
    assert switch(on) == (True, "on", None)


def test_without_a_public_https_address_the_switch_says_why_and_links_the_fix(
    tmp_path: Path,
) -> None:
    with _signed_in_app(tmp_path, "http://ghost.example.test") as client:
        sign_in(client)
        user = client.get("/api/v1/session").json()["user"]

    assert (user["instant_sync_availability"], user["instant_sync_help"]) == (
        "no_public_address",
        "no-public-https-address",
    )


@pytest.mark.parametrize(
    ("public_url", "cadence"),
    [(ADDRESS, "not_watchable"), ("", "no_public_address")],
    ids=["https, nothing watched yet", "no public address"],
)
def test_each_rule_says_how_often_it_syncs(tmp_path: Path, public_url: str, cadence: str) -> None:
    database = tmp_path / "test.db"
    client = _signed_in_app(tmp_path, public_url)
    owner = first_user(database)
    with sqlite_units(database, user=owner)() as uow:
        uow.rules.add(rule())
        uow.commit()

    with client:
        sign_in(client)
        listed = client.get("/api/v1/rules").json()
        detail = client.get(f"/api/v1/rules/{rule().id.value}").json()

    assert [(item["effective_cadence"], item["poll_every_minutes"]) for item in listed] == [
        (cadence, 5)
    ]
    assert (detail["effective_cadence"], detail["poll_every_minutes"]) == (cadence, 5)
```

In `tests/adapters/test_service_logging.py`, add `from calendar_sync.bootstrap.logs import NoticePathFilter`
to the `bootstrap.logs` import (`HANDLER, LOGGER, NoticePathFilter, configure_logging`), and append:

```python
def _access_record(path: str) -> logging.LogRecord:
    """A line as Uvicorn's access logger writes it."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.9:443", "POST", path, "1.1", 202),
        None,
    )


def test_uvicorns_access_log_never_names_a_watch_notices_registration(
    service_logger: logging.Logger,
) -> None:
    registration = "0123456789abcdef0123456789abcdef"
    notice = _access_record(f"/api/v1/watch-notices/google/{registration}")
    validation = _access_record(
        f"/api/v1/watch-notices/microsoft/{registration}?validationToken=synthetic"
    )
    other = _access_record("/api/v1/rules")

    configure_logging("INFO")
    configure_logging("INFO")

    access = logging.getLogger("uvicorn.access")
    filters = [each for each in access.filters if isinstance(each, NoticePathFilter)]
    assert len(filters) == 1
    assert all(filters[0].filter(record) for record in (notice, validation, other))
    assert '"POST /api/v1/watch-notices/google/… HTTP/1.1" 202' in notice.getMessage()
    assert '"POST /api/v1/watch-notices/microsoft/… HTTP/1.1" 202' in validation.getMessage()
    assert registration not in notice.getMessage() + validation.getMessage()
    assert '"POST /api/v1/rules HTTP/1.1" 202' in other.getMessage()
```

In `tests/adapters/test_api_authorization.py`, change the comment above `PUBLIC_API_ROUTES` and
add the route:

```python
# AGENTS.md: only setup, sign-in, the token-protected Invitation and Password Reset Links, and the
# Watch Notice route providers call, which authenticates each notice by its registration's secret
# token (ADR 0036), are public under /api/, beside the session status and sign-out, which reveal or
# revoke nothing without a session.
PUBLIC_API_ROUTES = {
    ("GET", "/api/v1/setup"),
    ("POST", "/api/v1/setup/admin"),
    ("GET", "/api/v1/session"),
    ("POST", "/api/v1/session"),
    ("DELETE", "/api/v1/session"),
    ("POST", "/api/v1/invitations/check"),
    ("POST", "/api/v1/invitations/accept"),
    ("POST", "/api/v1/password-resets/check"),
    ("POST", "/api/v1/password-resets"),
    ("POST", "/api/v1/watch-notices/{provider_slug}/{registration_id}"),
}
```

and in `test_every_route_answers_another_users_record_as_not_found`, extend the skipped routes:

```python
            if (
                not isinstance(route, APIRoute)
                or not route.path.startswith("/api/")
                or "{" not in route.path
                # A connection flow names a provider, which is no User's record.
                or "{slug}" in route.path
                # A Watch Notice names a registration, which no session reads (ADR 0036).
                or "{registration_id}" in route.path
            ):
                continue
```

In `tests/adapters/test_schema_enums.py`, add the imports
`from calendar_sync.domain.watches import Availability, CadenceReason` and these entries to
`MIRRORS`:

```python
    "EffectiveCadenceValue": CadenceReason,
    "InstantSyncAvailabilityValue": Availability,
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_api.py tests/adapters/test_service_logging.py tests/adapters/test_api_authorization.py tests/adapters/test_schema_enums.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'calendar_sync.interfaces.api.routes.watch_notices'`; `ImportError: cannot import name 'NoticePathFilter'`; the authorization test misses the public route; `AttributeError: module 'calendar_sync.interfaces.api.schemas' has no attribute 'EffectiveCadenceValue'`)

- [ ] **Step 3: Implement the Watch Notice route**

`src/calendar_sync/interfaces/api/routes/watch_notices.py`:

```python
"""Watch Notices: where calendar providers say a watched calendar may have changed (ADR 0036).

The route is public, as providers cannot sign in. The inbox authenticates each notice by its
registration's secret token, and the answer is the same 202 for known, unknown, and refused
notices, so it shows no registration. Nothing here logs a token, handle, registration id, or body.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import PlainTextResponse

from calendar_sync.application.operations.ports import InboxBusy, WatchNoticeInbox
from calendar_sync.application.sync.watch_ports import (
    NOTICE_PATH,
    MalformedNotice,
    NoticeReader,
    NoticeRequest,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.watches import WatchRegistrationId
from calendar_sync.interfaces.api.dependencies import app_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem

NOTICE_BODY_LIMIT = 65_536
"""The largest notice body read; a provider's batch of notices is far smaller."""
VALIDATION_TOKEN_LIMIT = 1_024
"""The longest validation token echoed back."""


class Waking(Protocol):
    def wake(self) -> None: ...


class NoticeServices(Protocol):
    @property
    def watch_inbox(self) -> WatchNoticeInbox | None: ...
    @property
    def notice_readers(self) -> Mapping[str, tuple[ProviderKind, NoticeReader]]: ...
    @property
    def instant_dispatcher(self) -> Waking | None: ...
    @property
    def instant_sync_address(self) -> str | None: ...


Services = Annotated[NoticeServices, Depends(app_services)]
router = APIRouter()


@router.post(
    NOTICE_PATH + "/{provider_slug}/{registration_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    # Providers call it, not the Web UI, whose API types come from the schema.
    include_in_schema=False,
)
async def watch_notice(
    provider_slug: str, registration_id: str, request: Request, services: Services
) -> Response:
    """Record a provider's Watch Notices, so the rules they concern run soon."""
    inbox, address = services.watch_inbox, services.instant_sync_address
    found = services.notice_readers.get(provider_slug)
    if inbox is None or address is None or found is None:
        # As for any unknown API path: an installation that cannot hear notices has no route.
        raise problem(status.HTTP_404_NOT_FOUND, "not_found", "Not Found")
    provider, reader = found
    headers, query = dict(request.headers), dict(request.query_params)
    # A provider validating the address waits only seconds, and its body is never a notice.
    token = reader.validation_token(NoticeRequest(headers, query, b""))
    if token is not None:
        return PlainTextResponse(token[:VALIDATION_TOKEN_LIMIT])
    body = await _body(request)
    try:
        registration = WatchRegistrationId(registration_id)
    except DomainValidationError:
        # A blank identifier names no registration, so it is answered as an unknown one.
        return _accepted()
    try:
        notices = reader.read(registration, NoticeRequest(headers, query, body))
    except MalformedNotice:
        raise problem(
            status.HTTP_400_BAD_REQUEST, "malformed_notice", "not a notice this provider sends"
        ) from None
    try:
        requested = await asyncio.to_thread(
            inbox.record, notices, provider, address, datetime.now(UTC)
        )
    except InboxBusy:
        # Providers retry a 5xx answer, so the notice is not lost.
        raise problem(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "inbox_busy",
            "notices cannot be recorded right now; try again",
        ) from None
    if requested and services.instant_dispatcher is not None:
        services.instant_dispatcher.wake()
    return _accepted()


async def _body(request: Request) -> bytes:
    """The body, read only up to NOTICE_BODY_LIMIT, so a larger one is never held whole."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > NOTICE_BODY_LIMIT:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        # Checked before keeping the chunk, so one large chunk is never held.
        if len(body) + len(chunk) > NOTICE_BODY_LIMIT:
            raise _too_large()
        body.extend(chunk)
    return bytes(body)


def _too_large() -> ApiProblem:
    return problem(
        status.HTTP_413_CONTENT_TOO_LARGE, "notice_too_large", "a notice body is at most 64 KB"
    )


def _accepted() -> Response:
    return Response(status_code=status.HTTP_202_ACCEPTED)
```

In `src/calendar_sync/interfaces/api/app.py`, add `watch_notices` to the
`calendar_sync.interfaces.api.routes` import (after `users`), add `watch_notices.NoticeServices,`
to the bases of `ApiServices` (after `storage.StorageServices,`), and add `watch_notices,` to the
flat module tuple after `users,`.

In `src/calendar_sync/bootstrap/logs.py`, add the import
`from calendar_sync.application.sync.watch_ports import NOTICE_PATH`, the constant
`ACCESS_LOGGER = "uvicorn.access"` after `FORMAT`, this class after `_UtcFormatter`:

```python
class NoticePathFilter(logging.Filter):
    """Keeps registrations out of Uvicorn's access log. A Watch Notice's path names its
    registration, which no log line may (ADR 0036), so the line keeps only the provider's slug:
    `/api/v1/watch-notices/<slug>/…`, without the registration or a query."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2:
            path = str(args[2])
            if path.startswith(NOTICE_PATH + "/"):
                slug = path[len(NOTICE_PATH) + 1 :].split("/", 1)[0].split("?", 1)[0]
                record.args = (*args[:2], f"{NOTICE_PATH}/{slug}/…", *args[3:])
        return True
```

in `configure_logging`, before `attached = _write_to(logger, files)`, add:

```python
    _hide_notice_paths()
```

and after `configure_logging`, add:

```python
def _hide_notice_paths() -> None:
    """Filter Uvicorn's access log once, however often logging is configured."""
    access = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(each, NoticePathFilter) for each in access.filters):
        access.addFilter(NoticePathFilter())
```

Also extend the module docstring's second paragraph to: "Only the `calendar_sync` logger is
configured, apart from one filter that keeps Watch Notice paths out of Uvicorn's access log.
Uvicorn keeps its own access and error logging, and other libraries keep Python's defaults."

In `AGENTS.md`, replace

```text
`/api/v1/password-resets/check`, `/api/v1/password-resets`), static application files, and
`/health` are intentionally public;
```

with

```text
`/api/v1/password-resets/check`, `/api/v1/password-resets`), the Watch Notice route providers
call (`/api/v1/watch-notices/{provider_slug}/{registration_id}`, ADR 0036), which answers alike
for known and unknown registrations and logs no identifier, token, or body, static application
files, and `/health` are intentionally public;
```

- [ ] **Step 4: Implement the switch and the signed-in User's answers**

In `src/calendar_sync/interfaces/api/schemas.py`, after `HintKindValue`, add:

```python
InstantSyncAvailabilityValue = Literal[
    "on", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"
]
"""Whether Instant Sync is on for a User, or why not (ADR 0036)."""
EffectiveCadenceValue = Literal[
    "instant",
    "not_watchable",
    "waiting_for_provider",
    "off_by_user",
    "not_in_plan",
    "no_public_address",
    "not_reaching",
]
"""How a rule syncs: "instant", or why Scheduled Sync runs it instead."""
```

change `SignedInUserResponse` to:

```python
class SignedInUserResponse(ApiResponse):
    id: str
    email: str | None
    """None until the upgraded first User adds one, which they must do first."""
    role: Literal["installation_administrator", "user"]
    notify_by_email: bool
    language: str | None
    instant_sync: bool
    """Whether the User wants Instant Sync; it is on only while the availability is "on"."""
    instant_sync_availability: InstantSyncAvailabilityValue
    instant_sync_help: str | None
    """The section of docs/instant-sync.md that explains why it is unavailable, and the fix."""
```

add to `RuleSummaryResponse` and to `RuleDetailResponse`, after `destination`:

```python
    effective_cadence: EffectiveCadenceValue
    poll_every_minutes: int
    """How often Scheduled Sync runs the rule, as the User's Plan says."""
```

and after `NotificationPreferenceRequest`, add:

```python
class InstantSyncPreferenceRequest(BaseModel):
    instant_sync: bool
```

In `src/calendar_sync/interfaces/api/routes/session.py`, change the domain import to

```python
from calendar_sync.domain.access import User, UserId
from calendar_sync.domain.watches import AVAILABILITY_ANCHORS, Availability
```

replace `SessionServices` with:

```python
class InstantSyncReader(Protocol):
    def availability(self, user: UserId) -> Availability: ...


class SignedInAnswers(Protocol):
    """What every answer that names the signed-in User reads beside the User."""

    @property
    def sends_email(self) -> bool: ...
    @property
    def instant_sync_status(self) -> InstantSyncReader: ...


class SessionServices(SignedInAnswers, Protocol):
    @property
    def identity(self) -> SignInIdentity: ...
    @property
    def secure_cookies(self) -> bool: ...
```

change the two `signed_in(..., services.sends_email)` calls in this module to
`signed_in(..., services)`, and replace `signed_in` and `user_response` with:

```python
def signed_in(user: User | None, services: SignedInAnswers) -> SessionResponse:
    if user is None:
        return SessionResponse(authenticated=False)
    return SessionResponse(
        authenticated=True,
        user=user_response(user, services),
        installation_sends_email=services.sends_email,
    )


def user_response(user: User, services: SignedInAnswers) -> SignedInUserResponse:
    availability = services.instant_sync_status.availability(user.id)
    return SignedInUserResponse(
        id=user.id.value,
        email=user.email,
        role=user.role.value,
        notify_by_email=user.notify_by_email,
        language=user.language,
        instant_sync=user.instant_sync,
        instant_sync_availability=availability.value,
        instant_sync_help=AVAILABILITY_ANCHORS.get(availability),
    )
```

In `src/calendar_sync/interfaces/api/routes/setup.py`, import `SignedInAnswers` beside
`signed_in`, make `class SetupServices(SignedInAnswers, Protocol):` and drop its own
`sends_email` property, and change the last line of `set_up` to
`return signed_in(services.identity.users.get(session.user_id), services)`.

In `src/calendar_sync/interfaces/api/routes/users.py`, import `SignedInAnswers` beside
`signed_in`, make `class AdministrationServices(SignedInAnswers, Protocol):` and drop its own
`sends_email` property, and change the last line of `accept_invitation` to
`return signed_in(services.identity.users.get(session.user_id), services)`.

In `src/calendar_sync/interfaces/api/routes/account.py`: add `SetInstantSync` to the
`application.identity.sign_in` import, `SignedInAnswers` to the `routes.session` import, and
`InstantSyncPreferenceRequest` to the `schemas` import; add to `AccountIdentity`:

```python
    @property
    def set_instant_sync(self) -> SetInstantSync: ...
```

make `class OwnAccountServices(SignedInAnswers, Protocol):`; change `return user_response(changed)`
in `set_email` and `set_notifications` to `return user_response(changed, services)`; and add
after `set_notifications`:

```python
@router.put("/api/v1/account/instant-sync", response_model=SignedInUserResponse)
def set_instant_sync(
    payload: InstantSyncPreferenceRequest,
    services: Services,
    user_id: Annotated[UserId, Depends(current_user)],
) -> SignedInUserResponse:
    """Whether the User wants Instant Sync; it is on while their Plan and the installation allow
    it, and the answer says why not otherwise."""
    changed = services.identity.set_instant_sync.execute(user_id, payload.instant_sync)
    return user_response(changed, services)
```

In `src/calendar_sync/bootstrap/container.py`, add `SetInstantSync` to the
`application.identity.sign_in` import, add `set_instant_sync: SetInstantSync` to
`IdentityServices` after `set_notification_email`, and
`set_instant_sync=SetInstantSync(users),` to `_identity` after `set_notification_email=...`.

- [ ] **Step 5: Implement the rules' Effective Cadence**

In `src/calendar_sync/interfaces/api/routes/rules.py`: change the first imports to

```python
import asyncio
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Annotated, Any, Protocol
```

add the imports

```python
from calendar_sync.application.operations.instant_sync import InstantSyncStatus
from calendar_sync.domain.access import UserId
from calendar_sync.domain.watches import CadenceReason
```

add to `RuleServices`:

```python
    @property
    def user_id(self) -> UserId: ...
    @property
    def instant_sync_status(self) -> InstantSyncStatus: ...
```

replace `list_rules` with:

```python
@router.get(
    "/api/v1/rules",
    response_model=list[RuleSummaryResponse],
    dependencies=[Depends(current_user)],
)
def list_rules(services: Services) -> list[RuleSummaryResponse]:
    status_, user = services.instant_sync_status, services.user_id
    reasons, poll_every = status_.cadences(user), status_.poll_every(user)
    return [
        RuleSummaryResponse(
            **_named_rule_response(summary.rule, summary.names),
            **_cadence_fields(reasons.get(summary.rule.id), poll_every),
            last_sync=_outcome_response(summary.last_sync),
            latest_preview=_preview_response(summary.latest_preview),
            running=_work_response(summary.running),
        )
        for summary in services.list_sync_rules.execute()
    ]
```

in `rule_details`, after the `try`/`except` that reads `details`, add

```python
    status_, user = services.instant_sync_status, services.user_id
    reasons, poll_every = status_.cadences(user), status_.poll_every(user)
```

and add `**_cadence_fields(reasons.get(details.rule.id), poll_every),` to its
`RuleDetailResponse(...)` call after `**_named_rule_response(details.rule, details.names),`; and
add after `_named_rule_response`:

```python
def _cadence_fields(reason: CadenceReason | None, poll_every: timedelta) -> dict[str, Any]:
    """How the rule syncs; a rule created since the cadences were read is not watched yet."""
    return {
        "effective_cadence": (reason or CadenceReason.NOT_WATCHABLE).value,
        "poll_every_minutes": int(poll_every.total_seconds() // 60),
    }
```

(`status_` avoids shadowing the module's `fastapi.status` import.)

- [ ] **Step 6: Run the backend tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_instant_sync_api.py tests/adapters/test_service_logging.py tests/adapters/test_api_authorization.py tests/adapters/test_schema_enums.py tests/adapters/test_identity_api.py tests/adapters/test_api.py tests/adapters/test_mcp.py tests/test_provider_neutrality.py tests/test_no_em_dashes.py -q && .venv/bin/mypy && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/lint-imports`
Expected: PASS (`tests/test_openapi_contract.py` still fails until Step 7)

- [ ] **Step 7: Regenerate the API types and complete the typed Web UI fixtures**

Run: `.venv/bin/python scripts/export_openapi.py && (cd web && pnpm run api:types)`

The regenerated types make `instant_sync`, `instant_sync_availability`, `instant_sync_help`,
`effective_cadence`, and `poll_every_minutes` required. Add them to the typed test fixtures:

- After `notify_by_email: true,` (or `notify_by_email: true` before `language: null`) in each
  signed-in User fixture, add `instant_sync: true, instant_sync_availability: "on",
  instant_sync_help: null,`. The fixtures are in `web/src/app.test.tsx` (every one),
  `web/src/features/settings-own-account.test.tsx`, `web/src/features/person-page.test.tsx`,
  `web/src/features/people-page.test.tsx`, `web/src/features/settings.test.tsx`,
  `web/src/features/settings-administration.test.tsx`, and
  `web/src/features/invitation-page.test.tsx`.
- After `reprojection_required: false,` in each `RuleSummary` and `RuleDetail` fixture, add
  `effective_cadence: "instant", poll_every_minutes: 5,`. The fixtures are in
  `web/src/features/rules.test.tsx`, `web/src/features/activity.test.tsx`,
  `web/src/features/overview.test.tsx`, `web/src/features/rule-details.test.tsx`,
  `web/src/features/calendar-replacement.test.tsx`, and `web/src/features/rule-preview.test.tsx`.

Run the backend contract test and the complete frontend gate from AGENTS.md:

```sh
.venv/bin/pytest tests/test_openapi_contract.py -q
cd web
pnpm audit --audit-level=high
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
git status --short src/calendar_sync/interfaces/api/static/
```

Expected: PASS. If `typecheck` names another fixture typed `SignedInUser`, `SessionStatus`,
`RuleSummary`, or `RuleDetail`, add the same fields to it. `pnpm run build` regenerates
`src/calendar_sync/interfaces/api/static/` (AGENTS.md: after any change under `web/`).

Only test fixtures and erased types changed, so the bundle may differ only by the commit SHA it
embeds. Commit the static assets when the build changed anything else. Restore them with
`git checkout -- src/calendar_sync/interfaces/api/static/` when the only change is that SHA, as
the project keeps no SHA-only rebuild.

- [ ] **Step 8: Commit**

```bash
git add src/calendar_sync/interfaces/api/routes/watch_notices.py src/calendar_sync/interfaces/api/app.py src/calendar_sync/interfaces/api/schemas.py src/calendar_sync/interfaces/api/routes/session.py src/calendar_sync/interfaces/api/routes/setup.py src/calendar_sync/interfaces/api/routes/users.py src/calendar_sync/interfaces/api/routes/account.py src/calendar_sync/interfaces/api/routes/rules.py src/calendar_sync/bootstrap/container.py src/calendar_sync/bootstrap/logs.py AGENTS.md tests/adapters/test_instant_sync_api.py tests/adapters/test_service_logging.py tests/adapters/test_api_authorization.py tests/adapters/test_schema_enums.py web/openapi.json web/src/lib/api-schema.ts web/src/app.test.tsx web/src/features/settings-own-account.test.tsx web/src/features/person-page.test.tsx web/src/features/people-page.test.tsx web/src/features/settings.test.tsx web/src/features/settings-administration.test.tsx web/src/features/invitation-page.test.tsx web/src/features/rules.test.tsx web/src/features/activity.test.tsx web/src/features/overview.test.tsx web/src/features/rule-details.test.tsx web/src/features/calendar-replacement.test.tsx web/src/features/rule-preview.test.tsx
# Only when Step 7's build changed more than the embedded commit SHA:
git add src/calendar_sync/interfaces/api/static/
git commit -m "Hear Watch Notices at a public route, and say how each rule syncs and why

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 18: Web UI: the Instant sync switch and each rule's cadence

**Files:**
- Create: `web/src/lib/instant-sync.ts` (availability, help links, rule cadence)
- Create: `web/src/lib/instant-sync.test.ts`
- Create: `web/src/components/learn-why-link.tsx` ("Learn why", opening the Instant Sync guide)
- Create: `web/src/features/settings-instant-sync.tsx` (the switch)
- Modify: `web/src/lib/brand.ts` (the documentation base and `INSTANT_SYNC_HELP_URL`)
- Modify: `web/src/lib/api.ts` (`setInstantSync`)
- Modify: `web/src/features/settings-own-account.tsx` (render the switch after incident emails)
- Modify: `web/src/features/rule-details-facts.tsx` (`CadenceFact` in Latest runs)
- Modify: `web/src/i18n/locales/en/settings.json`, `web/src/i18n/locales/en/rule-details.json`, `web/src/i18n/locales/en/common.json`
- Modify: `web/src/i18n/catalog.test.ts` (`TEMPLATE_VALUES`)
- Modify: `web/src/index.css` (`.instant-sync-toggle`)
- Test: `web/src/features/settings-own-account.test.tsx`, `web/src/features/rule-details.test.tsx`, `web/src/lib/instant-sync.test.ts`
- Regenerate: `src/calendar_sync/interfaces/api/static/`

**Interfaces:**
- Consumes: `SignedInUserResponse.instant_sync: bool`, `.instant_sync_availability` (`"on"|"off_by_user"|"not_in_plan"|"no_public_address"|"not_reaching"`), `.instant_sync_help: str | None` (anchor in `docs/instant-sync.md`); rule responses `.effective_cadence` (`"instant"|"not_watchable"|"waiting_for_provider"|"off_by_user"|"not_in_plan"|"no_public_address"|"not_reaching"`) and `.poll_every_minutes: int`; `PUT /api/v1/account/instant-sync` with `{instant_sync: bool}` answering `SignedInUserResponse` (Task 17, regenerated types).
- Produces: `INSTANT_SYNC_HELP_URL = "https://calendarghost.com/docs/instant-sync"` (Task 20 registers that page); the rule page's anchors `this-calendar-cannot-be-watched`, `waiting-for-the-provider`, `not-in-your-plan`, `no-public-https-address`, `providers-cannot-reach-the-installation`, which Task 20's docs must hold.

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/instant-sync.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { instantSyncBlock, instantSyncHelpUrl, ruleCadence } from "./instant-sync"

const GUIDE = "https://calendarghost.com/docs/instant-sync"

describe("instantSyncBlock", () => {
  it("leaves the switch to the User when instant sync is on or they turned it off", () => {
    expect(instantSyncBlock("on")).toBeNull()
    expect(instantSyncBlock("off_by_user")).toBeNull()
  })

  it("names what keeps it from running otherwise, and a reason this version does not know as unknown", () => {
    expect(instantSyncBlock("not_in_plan")).toBe("not_in_plan")
    expect(instantSyncBlock("no_public_address")).toBe("no_public_address")
    expect(instantSyncBlock("not_reaching")).toBe("not_reaching")
    expect(instantSyncBlock("a_reason_from_a_later_server")).toBe("unknown")
  })
})

describe("instantSyncHelpUrl", () => {
  it("opens the guide's section the server names, and nothing without one", () => {
    expect(instantSyncHelpUrl("not-in-your-plan")).toBe(`${GUIDE}#not-in-your-plan`)
    expect(instantSyncHelpUrl(null)).toBeNull()
    expect(instantSyncHelpUrl(undefined)).toBeNull()
  })
})

describe("ruleCadence", () => {
  it("says a watched rule syncs instantly, and how often it also checks", () => {
    expect(ruleCadence({ effective_cadence: "instant", poll_every_minutes: 5 })).toEqual({
      instant: true,
      reason: null,
      minutes: 5,
      helpUrl: null,
    })
  })

  it("gives a rule on its schedule its reason and the guide's section on it", () => {
    expect(ruleCadence({ effective_cadence: "waiting_for_provider", poll_every_minutes: 5 })).toEqual({
      instant: false,
      reason: "waiting_for_provider",
      minutes: 5,
      helpUrl: `${GUIDE}#waiting-for-the-provider`,
    })
    const sections = (reason: string) => ruleCadence({ effective_cadence: reason, poll_every_minutes: 5 }).helpUrl
    expect(sections("not_watchable")).toBe(`${GUIDE}#this-calendar-cannot-be-watched`)
    expect(sections("not_in_plan")).toBe(`${GUIDE}#not-in-your-plan`)
    expect(sections("no_public_address")).toBe(`${GUIDE}#no-public-https-address`)
    expect(sections("not_reaching")).toBe(`${GUIDE}#providers-cannot-reach-the-installation`)
  })

  it("links nowhere for the User's own choice, or for a reason this version does not know", () => {
    expect(ruleCadence({ effective_cadence: "off_by_user", poll_every_minutes: 5 })).toEqual({
      instant: false,
      reason: "off_by_user",
      minutes: 5,
      helpUrl: null,
    })
    expect(ruleCadence({ effective_cadence: "a_reason_from_a_later_server", poll_every_minutes: 10 })).toEqual({
      instant: false,
      reason: null,
      minutes: 10,
      helpUrl: null,
    })
  })
})
```

In `web/src/features/settings-own-account.test.tsx`, make the `user` fixture read exactly as follows
(Task 17 may already have added the three `instant_sync` fields; keep one of each):

```tsx
const user: SignedInUser = {
  id: "user-robin",
  email: "robin@example.test",
  role: "user",
  notify_by_email: true,
  language: null,
  instant_sync: true,
  instant_sync_availability: "on",
  instant_sync_help: null,
}
```

Add one route to the `routes` object in `serve()`, after the `notifications` one:

```tsx
    "PUT /api/v1/account/instant-sync": jsonResponse({ ...user, instant_sync: false, instant_sync_availability: "off_by_user" }),
```

Add this helper after `incidentEmails()`:

```tsx
function instantSync(): HTMLElement {
  const heading = [...container.querySelectorAll("h3")].find((item) => item.textContent === "Instant sync")
  if (!heading) throw new Error("No instant sync item")
  return heading.closest<HTMLElement>(".setting-item")!
}
```

Add these tests inside `describe("OwnAccountSection", ...)`, after "tells an administrator how to set
up incident emails where the installation sends none":

```tsx
  it("turns instant sync off", async () => {
    await renderSection(testI18n())
    const toggle = field("own-instant-sync")
    expect(toggle.checked).toBe(true)
    expect(toggle.disabled).toBe(false)
    expect(container.querySelector("#own-instant-sync-reason")).toBeNull()
    await click(toggle)
    expect(sent("PUT", "/api/v1/account/instant-sync")).toEqual({ instant_sync: false })
    expect(status()).toBe("Your rules now sync on their schedule only.")
  })

  it("lets a User who turned instant sync off turn it on again", async () => {
    await renderSection(testI18n(), {
      signedIn: { ...user, instant_sync: false, instant_sync_availability: "off_by_user" },
      answers: { "PUT /api/v1/account/instant-sync": jsonResponse({ ...user, instant_sync: true }) },
    })
    const toggle = field("own-instant-sync")
    expect(toggle.checked).toBe(false)
    expect(toggle.disabled).toBe(false)
    await click(toggle)
    expect(sent("PUT", "/api/v1/account/instant-sync")).toEqual({ instant_sync: true })
    expect(status()).toBe("Your rules now sync soon after each change in their source calendars.")
  })

  it("disables instant sync where it cannot run, with the reason and where to learn why", async () => {
    await renderSection(testI18n(), {
      signedIn: { ...user, instant_sync_availability: "no_public_address", instant_sync_help: "no-public-https-address" },
    })
    const toggle = field("own-instant-sync")
    expect(toggle.disabled).toBe(true)
    expect(toggle.checked).toBe(false)
    expect(toggle.getAttribute("aria-describedby")).toBe("own-instant-sync-reason")
    expect(container.querySelector("#own-instant-sync-reason")?.textContent).toContain(
      "Instant sync needs this Calendar Ghost to have a public HTTPS address, so your rules sync on their schedule.",
    )
    const help = instantSync().querySelector("a")
    expect(help?.textContent).toBe("Learn why (opens in a new tab)")
    expect(help?.getAttribute("href")).toBe("https://calendarghost.com/docs/instant-sync#no-public-https-address")
    expect(help?.getAttribute("target")).toBe("_blank")
    expect(help?.getAttribute("rel")).toBe("noreferrer")
    await click(toggle)
    expect(sent("PUT", "/api/v1/account/instant-sync")).toBeUndefined()
  })

  it("says instant sync is unavailable for a reason this version does not know, without a link it cannot name", async () => {
    await renderSection(testI18n(), {
      signedIn: {
        ...user,
        instant_sync_availability: "a_reason_from_a_later_server" as SignedInUser["instant_sync_availability"],
        instant_sync_help: null,
      },
    })
    expect(field("own-instant-sync").disabled).toBe(true)
    expect(container.querySelector("#own-instant-sync-reason")?.textContent).toBe(
      "Instant sync is not available here right now, so your rules sync on their schedule. ",
    )
    expect(instantSync().querySelector("a")).toBeNull()
  })

  it("has no untranslated text for each reason instant sync cannot run", async () => {
    for (const [availability, help] of [
      ["not_in_plan", "not-in-your-plan"],
      ["no_public_address", "no-public-https-address"],
      ["not_reaching", "providers-cannot-reach-the-installation"],
    ] as const) {
      await renderSection(pseudoI18n(), {
        signedIn: { ...user, instant_sync_availability: availability, instant_sync_help: help },
      })
      expect(untranslatedText(container, [user.email!])).toEqual([])
      act(() => root?.unmount())
      root = null
    }
  })
```

In `web/src/features/rule-details.test.tsx`, make `enabledRule` carry the cadence (Task 17 may
already have added the two fields; keep one of each). Its last lines read:

```tsx
  latest_preview: null,
  running: null,
  effective_cadence: "instant",
  poll_every_minutes: 5,
}
```

Add these tests inside `describe("RuleDetailsView", ...)`, after "renders the rule's facts, runs, and
commands in English":

```tsx
  it("says how soon the rule syncs, and why it waits for its schedule", async () => {
    await renderDetails(testI18n(), enabledRule)
    const runs = () => container.querySelector<HTMLElement>("[aria-labelledby='rule-runs-title']")!
    expect(runs().textContent).toContain(
      "When it syncsSyncs instantlyRuns soon after a change in Family, and checks every 5 minutes as well.",
    )
    expect(runs().querySelector("a[href*='instant-sync']")).toBeNull()

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "waiting_for_provider" })
    expect(runs().textContent).toContain(
      "When it syncsSyncs every 5 minutesInstant sync starts once the calendar provider confirms it will report changes in Family.",
    )
    const help = runs().querySelector("a[href*='instant-sync']")
    expect(help?.textContent).toBe("Learn why (opens in a new tab)")
    expect(help?.getAttribute("href")).toBe("https://calendarghost.com/docs/instant-sync#waiting-for-the-provider")

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "off_by_user" })
    expect(runs().textContent).toContain("Syncs every 5 minutesYou turned instant sync off in Settings.")
    expect(runs().querySelector("a[href*='instant-sync']")).toBeNull()
  })

  it("says nothing about how soon a rule syncs until it is enabled", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "paused" })
    expect(container.textContent).not.toContain("When it syncs")
  })

  it("has no untranslated text for each reason a rule waits for its schedule", async () => {
    for (const reason of ["not_watchable", "waiting_for_provider", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"]) {
      await renderDetails(pseudoI18n(), { ...enabledRule, effective_cadence: reason as RuleDetail["effective_cadence"] })
      expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
      act(() => root?.unmount())
      root = null
    }
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && pnpm exec vitest run src/lib/instant-sync.test.ts src/features/settings-own-account.test.tsx src/features/rule-details.test.tsx`
Expected: FAIL (`./instant-sync` does not exist; no `#own-instant-sync` field; no "When it syncs" fact)

- [ ] **Step 3: Implement**

In `web/src/lib/brand.ts`, replace the `HELP_URL` lines:

```ts
/** The troubleshooting guide on the project site; it ends with where to ask for more help. */
export const HELP_URL = "https://calendarghost.com/docs/troubleshooting"
```

with:

```ts
/** The project site's pages built from the repository's docs/ (site/src/docs/pages.ts). */
const DOCS_URL = "https://calendarghost.com/docs"
/** The troubleshooting guide on the project site; it ends with where to ask for more help. */
export const HELP_URL = `${DOCS_URL}/troubleshooting`
/** The Instant Sync guide; its sections' anchors follow the headings in docs/instant-sync.md. */
export const INSTANT_SYNC_HELP_URL = `${DOCS_URL}/instant-sync`
```

Create `web/src/lib/instant-sync.ts`:

```ts
import { INSTANT_SYNC_HELP_URL } from "@/lib/brand"

/** Whether Instant Sync runs a User's rules, as the server decides it (`Availability` in domain/watches.py). */
type Availability = "on" | "off_by_user" | "not_in_plan" | "no_public_address" | "not_reaching"

const AVAILABILITIES: readonly Availability[] = ["on", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"]

/** What keeps the switch from working for the User; `unknown` for a reason a later server sends. */
type InstantSyncBlock = Exclude<Availability, "on" | "off_by_user"> | "unknown"

/** Why a rule syncs as it does, as the server names it (`CadenceReason` in domain/watches.py). */
type CadenceReason =
  | "instant"
  | "not_watchable"
  | "waiting_for_provider"
  | "off_by_user"
  | "not_in_plan"
  | "no_public_address"
  | "not_reaching"

const REASONS: readonly CadenceReason[] = [
  "instant",
  "not_watchable",
  "waiting_for_provider",
  "off_by_user",
  "not_in_plan",
  "no_public_address",
  "not_reaching",
]

/**
 * Each reason's section of docs/instant-sync.md; tests/test_instant_sync_docs.py checks that the
 * guide holds them. A reason the User chose needs no explanation, so it has none.
 */
const REASON_ANCHORS: Partial<Record<CadenceReason, string>> = {
  not_watchable: "this-calendar-cannot-be-watched",
  waiting_for_provider: "waiting-for-the-provider",
  not_in_plan: "not-in-your-plan",
  no_public_address: "no-public-https-address",
  not_reaching: "providers-cannot-reach-the-installation",
}

/** How soon an enabled rule syncs, as its page says it. */
type RuleCadence = {
  instant: boolean
  /** Why it syncs on its schedule; null when it syncs instantly or the reason is not known here. */
  reason: Exclude<CadenceReason, "instant"> | null
  minutes: number
  helpUrl: string | null
}

/** Why the Instant sync switch cannot be used, or null when it is the User's to turn on or off. */
export function instantSyncBlock(availability: string): InstantSyncBlock | null {
  const known = AVAILABILITIES.find((each) => each === availability)
  if (known === undefined) return "unknown"
  return known === "on" || known === "off_by_user" ? null : known
}

/** The Instant Sync guide's section on `anchor`; null without one. */
export function instantSyncHelpUrl(anchor: string | null | undefined): string | null {
  return anchor ? `${INSTANT_SYNC_HELP_URL}#${anchor}` : null
}

export function ruleCadence(detail: { effective_cadence: string; poll_every_minutes: number }): RuleCadence {
  const reason = REASONS.find((each) => each === detail.effective_cadence)
  const minutes = detail.poll_every_minutes
  if (reason === "instant") return { instant: true, reason: null, minutes, helpUrl: null }
  const anchor = reason === undefined ? undefined : REASON_ANCHORS[reason]
  return { instant: false, reason: reason ?? null, minutes, helpUrl: instantSyncHelpUrl(anchor) }
}
```

Create `web/src/components/learn-why-link.tsx`:

```tsx
import { ExternalLink } from "lucide-react"

import { useI18n } from "@/i18n/provider"

/** "Learn why", opening the section of the Instant Sync guide that explains a reason and its fix. */
export function LearnWhyLink({ href }: { href: string }) {
  const { t } = useI18n()
  return (
    <a className="text-link inline-link" href={href} target="_blank" rel="noreferrer">
      {t("common.learnWhy")}
      <ExternalLink aria-hidden="true" />
      <span className="sr-only">{t("common.opensInNewTab")}</span>
    </a>
  )
}
```

In `web/src/lib/api.ts`, add after `setIncidentEmails`:

```ts
  /** Whether the signed-in User's rules run soon after their provider reports a change. */
  setInstantSync: (instantSync: boolean) =>
    call("/api/v1/account/instant-sync", "put", { body: { instant_sync: instantSync } }),
```

Create `web/src/features/settings-instant-sync.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { LearnWhyLink } from "@/components/learn-why-link"
import { apiErrorMessage } from "@/i18n/api-errors"
import { useI18n } from "@/i18n/provider"
import { api, type SignedInUser } from "@/lib/api"
import { instantSyncBlock, instantSyncHelpUrl } from "@/lib/instant-sync"

/**
 * Whether the User's rules run soon after their provider reports a change (Instant Sync), beside
 * incident emails. Where it cannot run for them, the switch is disabled, says why, and links to
 * the section of the Instant Sync guide that explains the fix.
 */
export function InstantSyncItem({ user, onDone }: { user: SignedInUser; onDone: (message: string) => void }) {
  const i18n = useI18n()
  const { t } = i18n
  const { change, shown } = useInstantSyncChoice(user, onDone)
  const block = instantSyncBlock(shown.instant_sync_availability)
  const help = block ? instantSyncHelpUrl(shown.instant_sync_help) : null
  const checked = change.isPending ? change.variables : shown.instant_sync
  return (
    <div className="setting-item">
      <div className="setting-row">
        <div>
          <h3>{t("settings.ownAccount.instantSync.title")}</h3>
          <p>{t("settings.ownAccount.instantSync.body")}</p>
          {block && (
            <p id="own-instant-sync-reason">
              {t(`settings.ownAccount.instantSync.blocked.${block}`)}{" "}
              {help && <LearnWhyLink href={help} />}
            </p>
          )}
        </div>
        <label className="checkbox-row instant-sync-toggle" htmlFor="own-instant-sync">
          <input
            id="own-instant-sync"
            type="checkbox"
            checked={block === null && checked}
            disabled={block !== null || change.isPending}
            aria-describedby={block ? "own-instant-sync-reason" : undefined}
            onChange={(event) => change.mutate(event.target.checked)}
          />
          <span>
            <strong>{t("settings.ownAccount.instantSync.label")}</strong>
          </span>
        </label>
      </div>
      {change.error && (
        <p className="field-error" role="alert">
          {apiErrorMessage(i18n, change.error)}
        </p>
      )}
    </div>
  )
}

/** The choice as the last change answered it, or as the session says, and the change itself. */
function useInstantSyncChoice(user: SignedInUser, onDone: (message: string) => void) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (wanted: boolean) => api.setInstantSync(wanted),
    onSuccess: async (changed) => {
      onDone(changed.instant_sync ? t("settings.ownAccount.instantSync.on") : t("settings.ownAccount.instantSync.off"))
      await queryClient.invalidateQueries({ queryKey: ["session"] })
    },
  })
  return { change, shown: change.data ?? user }
}
```

In `web/src/features/settings-own-account.tsx`, add the import after `CurrentPasswordField`'s group,
keeping the alphabetical order:

```tsx
import { InstantSyncItem } from "@/features/settings-instant-sync"
import { SelfDeletionItem } from "@/features/settings-self-deletion"
```

and render it after the incident emails:

```tsx
        <IncidentEmailsItem user={user} sendsEmail={sendsEmail} onDone={setMessage} />
        <InstantSyncItem user={user} onDone={setMessage} />
        <SelfDeletionItem onOpenPeople={onOpenPeople} />
```

Change the section's docstring first line to:

```tsx
 * The signed-in User's own sign-in, incident emails, Instant Sync, and deletion; every User has it.
```

In `web/src/features/rule-details-facts.tsx`, add the imports:

```tsx
import { LearnWhyLink } from "@/components/learn-why-link"
import { useI18n } from "@/i18n/provider"
import type { RuleDetail, RunOutcome } from "@/lib/api"
import { ruleCadence } from "@/lib/instant-sync"
import { tentativeFact, unansweredFact } from "@/lib/invitation-responses"
```

In `RuleRuns`, put the cadence first in its list:

```tsx
      <dl className="rule-facts">
        <CadenceFact detail={detail} sourceName={sourceName} />
        <OutcomeFact
```

and add, after `RuleRuns`:

```tsx
/**
 * How soon an enabled rule syncs: soon after its provider reports a change in its source, or on its
 * schedule with the reason and, where the guide explains it, "Learn why".
 */
function CadenceFact({ detail, sourceName }: { detail: RuleDetail; sourceName: string }) {
  const { t } = useI18n()
  if (detail.state !== "enabled") return null
  const cadence = ruleCadence(detail)
  const words = { source: sourceName, count: cadence.minutes }
  return (
    <div>
      <dt>{t("ruleDetails.cadence.label")}</dt>
      <dd>
        {cadence.instant ? t("ruleDetails.cadence.instant") : t("ruleDetails.cadence.every", { count: cadence.minutes })}
        <span className="rule-fact-explanation">
          {cadence.instant && t("ruleDetails.cadence.instantExplanation", words)}
          {cadence.reason && t(`ruleDetails.cadence.reason.${cadence.reason}`, words)}
          {cadence.helpUrl && (
            <>
              {" "}
              <LearnWhyLink href={cadence.helpUrl} />
            </>
          )}
        </span>
      </dd>
    </div>
  )
}
```

In `web/src/i18n/locales/en/common.json`, add before `"opensInNewTab"`:

```json
  "learnWhy": "Learn why",
```

In `web/src/i18n/locales/en/settings.json`, replace the `ownAccount` `title` and `intro`:

```json
    "title": "Sign-in, email, and sync",
    "intro": "How you sign in to Calendar Ghost, the email it sends you, and how soon your rules sync.",
```

and add after the `notifications` group:

```json
    "instantSync": {
      "title": "Instant sync",
      "body": "Your rules sync soon after a change in their source calendar, instead of waiting for the next scheduled sync. Scheduled syncs still run.",
      "label": "Sync soon after each change",
      "on": "Your rules now sync soon after each change in their source calendars.",
      "off": "Your rules now sync on their schedule only.",
      "blocked": {
        "not_in_plan": "Your plan does not include instant sync, so your rules sync on their schedule.",
        "no_public_address": "Instant sync needs this Calendar Ghost to have a public HTTPS address, so your rules sync on their schedule.",
        "not_reaching": "Your calendar providers cannot reach this Calendar Ghost, so your rules sync on their schedule.",
        "unknown": "Instant sync is not available here right now, so your rules sync on their schedule."
      }
    },
```

In `web/src/i18n/locales/en/rule-details.json`, replace `runs.syncExplanation`:

```json
    "syncExplanation": "Applies changes made in {source} since the previous run.",
```

and add a `cadence` group after `runs`:

```json
  "cadence": {
    "label": "When it syncs",
    "instant": "Syncs instantly",
    "every": {
      "one": "Syncs every minute",
      "other": "Syncs every {count} minutes"
    },
    "instantExplanation": {
      "one": "Runs soon after a change in {source}, and checks every minute as well.",
      "other": "Runs soon after a change in {source}, and checks every {count} minutes as well."
    },
    "reason": {
      "not_watchable": "{source} cannot report its changes to Calendar Ghost, as with a calendar shared from another Microsoft mailbox.",
      "waiting_for_provider": "Instant sync starts once the calendar provider confirms it will report changes in {source}.",
      "off_by_user": "You turned instant sync off in Settings.",
      "not_in_plan": "Your plan does not include instant sync.",
      "no_public_address": "Instant sync needs this Calendar Ghost to have a public HTTPS address.",
      "not_reaching": "Calendar providers cannot reach this Calendar Ghost, so their change reports do not arrive."
    }
  },
```

In `web/src/i18n/catalog.test.ts`, add to `TEMPLATE_VALUES` after `"people.cause.*"`:

```ts
  "ruleDetails.cadence.reason.*": [
    "not_watchable",
    "waiting_for_provider",
    "off_by_user",
    "not_in_plan",
    "no_public_address",
    "not_reaching",
  ],
  "settings.ownAccount.instantSync.blocked.*": ["not_in_plan", "no_public_address", "not_reaching", "unknown"],
```

In `web/src/index.css`, make the incident-email toggle rule cover the new one:

```css
.incident-email-toggle,
.instant-sync-toggle {
  min-height: 0;
  padding: 0;
  background: transparent;
}
```

- [ ] **Step 4: Run the tests, and bring older fixtures up to the regenerated types**

Run: `cd web && pnpm exec vitest run src/lib/instant-sync.test.ts src/features/settings-own-account.test.tsx src/features/rule-details.test.tsx src/i18n/catalog.test.ts`
Expected: PASS

Run: `cd web && pnpm run typecheck`
Expected: PASS. If it reports `instant_sync`, `instant_sync_availability`, or `instant_sync_help`
missing from a `SignedInUser` fixture (`web/src/app.test.tsx`,
`web/src/features/settings-administration.test.tsx`, `web/src/features/settings.test.tsx`,
`web/src/features/person-page.test.tsx`, `web/src/features/people-page.test.tsx`,
`web/src/features/invitation-page.test.tsx`), add
`instant_sync: true, instant_sync_availability: "on", instant_sync_help: null,` after its
`language` field. If it reports `effective_cadence` or `poll_every_minutes` missing from a rule
fixture (`web/src/features/rule-preview.test.tsx`, `calendar-replacement.test.tsx`,
`activity.test.tsx`, `overview.test.tsx`, `rules.test.tsx`), add
`effective_cadence: "instant", poll_every_minutes: 5,` after its `running` (or last) field. Run
typecheck again until it passes.

- [ ] **Step 5: Run the complete frontend gate and build**

```sh
cd web
pnpm audit --audit-level=high
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
```

Expected: every command passes; `pnpm run build` rewrites `src/calendar_sync/interfaces/api/static/`.
Then run `.venv/bin/pytest tests/test_ubiquitous_language.py -q` (it searches `web/src`). Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/instant-sync.ts web/src/lib/instant-sync.test.ts web/src/components/learn-why-link.tsx \
  web/src/features/settings-instant-sync.tsx web/src/features/settings-own-account.tsx \
  web/src/features/settings-own-account.test.tsx web/src/features/rule-details-facts.tsx \
  web/src/features/rule-details.test.tsx web/src/lib/brand.ts web/src/lib/api.ts \
  web/src/i18n/locales/en/settings.json web/src/i18n/locales/en/rule-details.json \
  web/src/i18n/locales/en/common.json web/src/i18n/catalog.test.ts web/src/index.css \
  web/src src/calendar_sync/interfaces/api/static
git commit -m "Let each person turn Instant Sync off, and say on each rule how soon it syncs and why

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: Installation Health hints for Instant Sync

**Files:**
- Modify: `src/calendar_sync/application/operations/installation_hints.py` (two hint kinds, `InstantSyncSignals`, `instant_sync_signals`, `instant_sync_hints`; `cause` may be None)
- Modify: `src/calendar_sync/application/operations/installation_health.py` (`HintSources`; `GetInstallationHealth` reads it)
- Modify: `src/calendar_sync/bootstrap/container.py` (compose `HintSources` with `_instant_sync_signals`)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (`HintKindValue`, nullable `cause`)
- Modify: `src/calendar_sync/interfaces/api/status_payload.py` (serialize a hint without a Cause)
- Modify: `docs/troubleshooting.md` (two sections the hints link to)
- Modify: `CONTEXT.md` (Installation Hint entry)
- Modify: `web/src/lib/causes.ts`, `web/src/i18n/locales/en/people.json` (hint sentences)
- Regenerate: `web/openapi.json`, `web/src/lib/api-schema.ts`, `src/calendar_sync/interfaces/api/static/`
- Test: `tests/application/test_installation_hints.py`, `tests/application/test_installation_health.py`, `tests/test_troubleshooting_anchors.py`, `tests/adapters/test_installation_health_api.py`, `web/src/lib/causes.test.ts`

**Interfaces:**
- Consumes: `InstantSyncOwner(user, wanted, disabled, next_due)` and `InstallationUnitOfWork.instant_sync_owners()` (Task 9); `SyncCadencePolicy`, `EveryUserInstant`, `DeliveryEvidenceLog.evidence(address)` (Task 3); `DeliveryEvidence`, `DeliveryState` (Task 2); `SyncCadence`, `SCHEDULED_EVERY` (Task 1); `Adapters.delivery_evidence`, `Adapters.sync_cadence` (Task 16, names assumed); `public_address(settings)` (existing).
- Produces:
  - `HintKind.PLAIN_HTTP_ADDRESS = "plain_http_address"`, `HintKind.NOTICES_NOT_ARRIVING = "notices_not_arriving"`
  - `PLAIN_HTTP_ANCHOR = "instant-sync-needs-an-https-public-address"`, `NOT_ARRIVING_ANCHOR = "calendar-providers-cannot-reach-the-installation"`
  - `InstallationHint.cause: Cause | None`
  - `@dataclass(frozen=True, slots=True) class InstantSyncSignals: wanting: int = 0; plain_http: bool = False; failing: frozenset[ProviderKind] = frozenset()`
  - `instant_sync_signals(owners: Iterable[InstantSyncOwner], cadence: SyncCadencePolicy, address: str | None, evidence: Mapping[ProviderKind, DeliveryEvidence]) -> InstantSyncSignals`
  - `instant_sync_hints(signals: InstantSyncSignals, guides: Sequence[ProviderGuide]) -> tuple[InstallationHint, ...]`
  - `@dataclass(frozen=True, slots=True) class HintSources: sightings: Callable[[datetime], Sequence[CauseSighting]]; guides: Sequence[ProviderGuide]; instant_sync: Callable[[], InstantSyncSignals]`
  - `GetInstallationHealth(users, verdicts, scheduler, clock, hint_sources: HintSources = HintSources(), secrets: Sequence[ClientSecretExpiry] = ())`

- [ ] **Step 1: Write the failing tests**

In `tests/application/test_installation_hints.py`, merge these into the file's imports (the
existing `installation_hints` import gains the five new names):

```python
from dataclasses import dataclass

from calendar_sync.application.operations.installation_hints import (
    NOT_ARRIVING_ANCHOR,
    PLAIN_HTTP_ANCHOR,
    InstantSyncSignals,
    instant_sync_hints,
    instant_sync_signals,
)
from calendar_sync.application.operations.ports import InstantSyncOwner
from calendar_sync.application.sync.watch_ports import EveryUserInstant
from calendar_sync.domain.cadence import SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.watches import DeliveryEvidence
```

and append:

```python
HTTPS = "https://calendar.example.test"
KIM = UserId("kim")


@dataclass(frozen=True)
class Cadences:
    """A Sync Cadence Policy that gives Instant Sync to everyone but some Users."""

    without_instant: frozenset[UserId] = frozenset()

    def cadence(self, user: UserId) -> SyncCadence:
        return SyncCadence(instant=user not in self.without_instant, poll_every=SCHEDULED_EVERY)


def owner(user: UserId, *, wanted: bool = True, disabled: bool = False) -> InstantSyncOwner:
    return InstantSyncOwner(user, wanted, disabled, None)


EVERYONE = (owner(ROBIN), owner(SAM))


def evidence(provider: ProviderKind, *, failing: bool) -> DeliveryEvidence:
    earlier, later = NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    return DeliveryEvidence(
        provider,
        HTTPS,
        last_success_at=earlier if failing else later,
        last_failure_at=later if failing else earlier,
    )


def test_only_users_who_may_sign_in_want_it_and_may_use_it_count() -> None:
    owners = [owner(ROBIN), owner(SAM, disabled=True), owner(ALEX, wanted=False), owner(KIM)]

    signals = instant_sync_signals(owners, Cadences(frozenset({KIM})), HTTPS, {})

    assert signals == InstantSyncSignals(wanting=1)


@pytest.mark.parametrize(
    "address", ["http://calendar.example.test", "http://calendar.example.test:8000"]
)
def test_a_plain_http_address_the_internet_reaches_is_a_hint(address: str) -> None:
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), address, {})

    assert signals == InstantSyncSignals(wanting=2, plain_http=True)
    assert instant_sync_hints(signals, GUIDES) == (
        InstallationHint(HintKind.PLAIN_HTTP_ADDRESS, None, 2, PLAIN_HTTP_ANCHOR),
    )
    assert PLAIN_HTTP_ANCHOR == "instant-sync-needs-an-https-public-address"


@pytest.mark.parametrize(
    "address",
    [
        "http://localhost:8000",
        "http://192.168.1.50:8000",
        "http://10.0.0.2",
        "http://100.100.1.1",
        "http://calendar.local",
        "http://pi.home.arpa",
        "http://raspberrypi:8000",
        "http://[::1]:8000",
        "http://[fd00::1]",
    ],
)
def test_plain_http_on_this_machine_or_a_home_network_says_nothing(address: str) -> None:
    # The homelab norm; each person's switch already says Instant Sync needs a public address.
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), address, {})

    assert instant_sync_hints(signals, GUIDES) == ()


def test_each_provider_whose_delivery_is_failing_is_a_hint_in_the_guides_order() -> None:
    other = ProviderGuide(ProviderKind.OUTLOOK, "other", "Other", "Other Calendar", {})
    seen = {
        ProviderKind.OUTLOOK: evidence(ProviderKind.OUTLOOK, failing=True),
        PROVIDER: evidence(PROVIDER, failing=True),
    }

    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), HTTPS, seen)

    assert instant_sync_hints(signals, (GUIDE, other)) == (
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING, None, 2, NOT_ARRIVING_ANCHOR, provider=PROVIDER
        ),
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING,
            None,
            2,
            NOT_ARRIVING_ANCHOR,
            provider=ProviderKind.OUTLOOK,
        ),
    )
    assert NOT_ARRIVING_ANCHOR == "calendar-providers-cannot-reach-the-installation"


def test_working_or_unknown_delivery_is_no_hint() -> None:
    seen = {
        PROVIDER: evidence(PROVIDER, failing=False),
        ProviderKind.OUTLOOK: DeliveryEvidence(ProviderKind.OUTLOOK, HTTPS),
    }

    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), HTTPS, seen)

    assert signals == InstantSyncSignals(wanting=2)
    assert instant_sync_hints(signals, GUIDES) == ()


def test_nobody_wanting_instant_sync_is_no_hint_whatever_the_address_or_evidence() -> None:
    nobody = [owner(ROBIN, wanted=False), owner(SAM, disabled=True)]
    seen = {PROVIDER: evidence(PROVIDER, failing=True)}

    for address in ("http://calendar.example.test", HTTPS):
        signals = instant_sync_signals(nobody, EveryUserInstant(), address, seen)
        assert instant_sync_hints(signals, GUIDES) == ()


def test_without_a_public_address_there_is_no_hint() -> None:
    signals = instant_sync_signals(EVERYONE, EveryUserInstant(), None, {})

    assert signals == InstantSyncSignals(wanting=2)
    assert instant_sync_hints(signals, GUIDES) == ()


def test_a_failing_provider_without_a_guide_is_no_hint() -> None:
    signals = InstantSyncSignals(wanting=2, failing=frozenset({ProviderKind.OUTLOOK}))

    assert instant_sync_hints(signals, GUIDES) == ()
```

In `tests/application/test_installation_health.py`, import `HintSources` from
`installation_health`, and `HintKind` and `InstantSyncSignals` from `installation_hints`. Replace
each of the three constructions that pass `sightings`/`shared`/`quota` and `GUIDES` positionally,
for example:

```python
    lone = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.STOPPED),
        Heartbeat(TICKING),
        Clock(),
        HintSources(sightings, GUIDES),
    ).execute()
```

(likewise `HintSources(shared, GUIDES)` and `HintSources(quota, GUIDES)`), and append:

```python
def test_instant_sync_hints_follow_the_cause_hints_and_need_attention() -> None:
    users = _users(("a", UserState.ACTIVE))

    def api_off(_since: datetime) -> list[CauseSighting]:
        return [failure("user-0", Cause.API_DISABLED)]

    health = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.HEALTHY),
        Heartbeat(TICKING),
        Clock(),
        HintSources(api_off, GUIDES, lambda: InstantSyncSignals(wanting=1, plain_http=True)),
    ).execute()

    assert [hint.kind for hint in health.hints] == [
        HintKind.SHARED_CAUSE,
        HintKind.PLAIN_HTTP_ADDRESS,
    ]
    assert health.status is StatusVerdict.HEALTHY
    assert health.needs_attention


def test_nobody_wanting_instant_sync_adds_no_hint() -> None:
    users = _users(("a", UserState.ACTIVE))

    health = GetInstallationHealth(
        users,
        lambda ids: dict.fromkeys(ids, StatusVerdict.HEALTHY),
        Heartbeat(TICKING),
        Clock(),
        HintSources(instant_sync=lambda: InstantSyncSignals(plain_http=True)),
    ).execute()

    assert health.hints == ()
    assert not health.needs_attention
```

In `tests/test_troubleshooting_anchors.py`, import `NOT_ARRIVING_ANCHOR` and `PLAIN_HTTP_ANCHOR`
beside `UNRECOGNIZED_ANCHOR`, and append:

```python
def test_every_section_an_instant_sync_hint_links_to_is_in_the_guide() -> None:
    linked = {PLAIN_HTTP_ANCHOR, NOT_ARRIVING_ANCHOR}

    assert linked <= guide_anchors(), linked - guide_anchors()
```

In `tests/adapters/test_installation_health_api.py`, append (with imports of `datetime`, `UTC`,
`InstallationHealth`, `InstallationHint`, `HintKind`, `PLAIN_HTTP_ANCHOR`, `StatusVerdict`, and
`installation_health_response` from `calendar_sync.interfaces.api.status_payload`):

```python
def test_an_instant_sync_hint_names_no_cause_and_needs_the_administrator() -> None:
    health = InstallationHealth(
        status=StatusVerdict.HEALTHY,
        incidents=(),
        users={StatusVerdict.HEALTHY: 2},
        disabled_users=0,
        checked_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
        hints=(InstallationHint(HintKind.PLAIN_HTTP_ADDRESS, None, 2, PLAIN_HTTP_ANCHOR),),
    )

    body = installation_health_response(health).model_dump(mode="json")

    assert body["needs_attention"] is True
    assert body["hints"] == [
        {
            "kind": "plain_http_address",
            "cause": None,
            "users": 2,
            "anchor": "instant-sync-needs-an-https-public-address",
            "provider": None,
        }
    ]
```

Append to `describe("hintText", ...)` in `web/src/lib/causes.test.ts`:

```ts
  it("says what keeps instant sync from people, and which provider cannot reach the installation", () => {
    expect(hintText(i18n, { ...hint("plain_http_address", null), provider: null })).toBe(
      "3 people want instant sync, but calendar providers report changes only to an HTTPS address, and this installation's public address uses plain HTTP.",
    )
    expect(hintText(i18n, { ...hint("plain_http_address", null), provider: null, users: 1 })).toBe(
      "1 person wants instant sync, but calendar providers report changes only to an HTTPS address, and this installation's public address uses plain HTTP.",
    )
    expect(hintText(i18n, hint("notices_not_arriving", null))).toBe(
      "3 people want instant sync, but Google cannot reach this installation, so changes in Google Calendar wait for the next scheduled sync.",
    )
    expect(hintText(i18n, { ...hint("notices_not_arriving", null), provider: "outlook" })).toBe(
      "3 people want instant sync, but Microsoft cannot reach this installation, so changes in Outlook wait for the next scheduled sync.",
    )
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/application/test_installation_hints.py tests/application/test_installation_health.py tests/test_troubleshooting_anchors.py tests/adapters/test_installation_health_api.py -q`
Expected: FAIL (ImportError: `PLAIN_HTTP_ANCHOR`, `HintSources`, and the rest do not exist)

- [ ] **Step 3: Implement the hints**

Replace `src/calendar_sync/application/operations/installation_hints.py` with:

```python
"""Installation Hints: likely causes Installation Health suggests from patterns across Users.

A hint never comes from one User's content, and never for a Cause a User fixes themself: it names
its Cause and provider when it has them, how many Users show it, and where the troubleshooting
guide explains the fix (ADR 0031). Each provider's guide says which administrator's Causes it can
raise and any pattern only it explains. While any User wants Instant Sync, a public address the
providers cannot use, or a provider whose Delivery Evidence is failing, is a hint too (ADR 0036).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit

from calendar_sync.application.operations.ports import CauseSighting, InstantSyncOwner
from calendar_sync.application.sync.provider_descriptors import GrantLifetime, ProviderGuide
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import ADMINISTRATOR_CAUSES, Cause
from calendar_sync.domain.watches import DeliveryEvidence, DeliveryState

ADMINISTRATOR_CAUSE_USERS = 1
"""Only the administrator can fix their own Cause, so one User meeting it is enough to say so."""
HINTED_USERS = 2
"""How many Users must show a pattern, such as grants expiring together, before it is a hint
rather than one person's trouble."""
HINT_WINDOW = timedelta(hours=24)
"""How recent a failure must be to count, unless its Incident is still open."""
UNRECOGNIZED_ANCHOR = "reading-the-logs"
"""The service logs name a provider's reason Calendar Ghost does not recognize."""
PLAIN_HTTP_ANCHOR = "instant-sync-needs-an-https-public-address"
"""Providers send Watch Notices only to an https address."""
NOT_ARRIVING_ANCHOR = "calendar-providers-cannot-reach-the-installation"
"""A provider's notices do not reach the public address."""
LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa", ".internal")
"""Host names that only resolve on this machine or inside a home network."""


class HintKind(StrEnum):
    SHARED_CAUSE = "shared_cause"
    """The same administrator's Cause for several Users."""
    TESTING_MODE = "testing_mode"
    """Several grants refused about as long after they were given as the provider keeps grants
    to an app registration in some setting, such as one still being tested."""
    UNRECOGNIZED = "unrecognized"
    """Several Users failing for a reason Calendar Ghost does not recognize."""
    PLAIN_HTTP_ADDRESS = "plain_http_address"
    """Users want Instant Sync, but the public address the internet reaches is plain http, which
    no provider sends Watch Notices to."""
    NOTICES_NOT_ARRIVING = "notices_not_arriving"
    """Users want Instant Sync, but a provider's Delivery Evidence for the public address is
    failing."""


@dataclass(frozen=True, slots=True)
class InstallationHint:
    kind: HintKind
    cause: Cause | None
    """The administrator's Cause the pattern shows; None for a hint about Instant Sync, which no
    failed provider call explains."""
    users: int
    """How many Users show the pattern; never who."""
    anchor: str
    """The section of the troubleshooting guide that explains the fix."""
    provider: ProviderKind | None = None
    """The provider whose answers show the pattern."""


@dataclass(frozen=True, slots=True)
class InstantSyncSignals:
    """What Installation Hints read about Instant Sync, as a count and Provider Kinds only."""

    wanting: int = 0
    """Users who may sign in, want Instant Sync, and whose Sync Cadence allows it."""
    plain_http: bool = False
    """The public address is plain http at a host the internet reaches."""
    failing: frozenset[ProviderKind] = frozenset()
    """Providers whose Delivery Evidence for the public address is failing."""


def installation_hints(
    sightings: Iterable[CauseSighting], now: datetime, guides: Sequence[ProviderGuide]
) -> tuple[InstallationHint, ...]:
    """Hints from every User's recent failures, per provider in the guides' order.

    A failure of a provider without a guide, such as one a later release recorded, hints nothing.
    """
    current = [seen for seen in sightings if seen.open or now - seen.at <= HINT_WINDOW]
    hints: list[InstallationHint] = []
    for guide in guides:
        hints.extend(_provider_hints([s for s in current if s.provider is guide.kind], guide))
    return tuple(hints)


def instant_sync_signals(
    owners: Iterable[InstantSyncOwner],
    cadence: SyncCadencePolicy,
    address: str | None,
    evidence: Mapping[ProviderKind, DeliveryEvidence],
) -> InstantSyncSignals:
    """Who wants Instant Sync, and what keeps providers from the installation's public address.

    Plain http on this machine or a home network is the homelab norm and signals nothing: each
    User's switch already says Instant Sync needs a public address.
    """
    wanting = sum(1 for owner in owners if _wants_instant_sync(owner, cadence))
    if not wanting or address is None:
        return InstantSyncSignals(wanting)
    if urlsplit(address).scheme == "http":
        return InstantSyncSignals(wanting, plain_http=_internet_host(address))
    failing = frozenset(
        kind for kind, seen in evidence.items() if seen.state is DeliveryState.FAILING
    )
    return InstantSyncSignals(wanting, failing=failing)


def instant_sync_hints(
    signals: InstantSyncSignals, guides: Sequence[ProviderGuide]
) -> tuple[InstallationHint, ...]:
    """Hints about Instant Sync while anyone wants it: a plain http public address, or else each
    provider, in the guides' order, whose notices do not arrive."""
    if not signals.wanting:
        return ()
    if signals.plain_http:
        return (
            InstallationHint(HintKind.PLAIN_HTTP_ADDRESS, None, signals.wanting, PLAIN_HTTP_ANCHOR),
        )
    return tuple(
        InstallationHint(
            HintKind.NOTICES_NOT_ARRIVING, None, signals.wanting, NOT_ARRIVING_ANCHOR, guide.kind
        )
        for guide in guides
        if guide.kind in signals.failing
    )


def _wants_instant_sync(owner: InstantSyncOwner, cadence: SyncCadencePolicy) -> bool:
    return owner.wanted and not owner.disabled and cadence.cadence(owner.user).instant


def _internet_host(address: str) -> bool:
    """Whether the internet could reach the address's host: not this machine, not a name only a
    home network resolves, and not a private, shared, or local IP address."""
    host = (urlsplit(address).hostname or "").lower()
    local_name = host == "localhost" or ("." not in host and ":" not in host)
    if local_name or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _provider_hints(
    sightings: Sequence[CauseSighting], guide: ProviderGuide
) -> list[InstallationHint]:
    hints = [
        InstallationHint(HintKind.SHARED_CAUSE, cause, count, anchor, guide.kind)
        for cause in sorted(ADMINISTRATOR_CAUSES)
        if (anchor := guide.cause_anchors.get(cause)) is not None
        and (count := _users(seen for seen in sightings if seen.cause is cause))
        >= ADMINISTRATOR_CAUSE_USERS
    ]
    lifetime = guide.grant_lifetime
    if lifetime is not None:
        lapsed = _users(seen for seen in sightings if _lapsed_at_lifetime(seen, lifetime))
        if lapsed >= HINTED_USERS:
            hints.append(
                InstallationHint(
                    HintKind.TESTING_MODE, Cause.ACCESS_REVOKED, lapsed, lifetime.anchor, guide.kind
                )
            )
    unrecognized = _users(seen for seen in sightings if seen.cause is Cause.UNKNOWN)
    if unrecognized >= HINTED_USERS:
        hints.append(
            InstallationHint(
                HintKind.UNRECOGNIZED, Cause.UNKNOWN, unrecognized, UNRECOGNIZED_ANCHOR, guide.kind
            )
        )
    return hints


def _users(sightings: Iterable[CauseSighting]) -> int:
    distinct: set[UserId] = {seen.user for seen in sightings}
    return len(distinct)


def _lapsed_at_lifetime(seen: CauseSighting, lifetime: GrantLifetime) -> bool:
    """A grant still refused, and refused about when the provider's grant lifetime ends."""
    return (
        seen.open
        and seen.cause is Cause.ACCESS_REVOKED
        and seen.authorized_for is not None
        and abs(seen.authorized_for - lifetime.lifetime) <= lifetime.tolerance
    )
```

In `src/calendar_sync/application/operations/installation_health.py`, import the new names:

```python
from calendar_sync.application.operations.installation_hints import (
    HINT_WINDOW,
    InstallationHint,
    InstantSyncSignals,
    installation_hints,
    instant_sync_hints,
)
```

add before `GetInstallationHealth`:

```python
@dataclass(frozen=True, slots=True)
class HintSources:
    """What Installation Hints read, each at once for every User."""

    sightings: Callable[[datetime], Sequence[CauseSighting]] = lambda _since: ()
    """Every User's failures with a Cause from a time on."""
    guides: Sequence[ProviderGuide] = ()
    """Each provider's troubleshooting sections and patterns, which hints link to."""
    instant_sync: Callable[[], InstantSyncSignals] = InstantSyncSignals
    """Who wants Instant Sync, and what keeps providers from the public address (ADR 0036)."""
```

and replace `GetInstallationHealth`'s `sightings` and `guides` fields and the end of `execute`:

```python
@dataclass(slots=True)
class GetInstallationHealth:
    users: UserDirectory
    verdicts: Callable[[Sequence[UserId]], Mapping[UserId, StatusVerdict]]
    """The Users' Installation Status verdicts, as their own Overviews show them, read at once."""
    scheduler: SchedulerHeartbeat | None
    clock: Clock
    hint_sources: HintSources = field(default_factory=HintSources)
    """What Installation Hints read."""
    secrets: Sequence[ClientSecretExpiry] = ()
    """When each configured provider's client secret expires, where the administrator said."""

    def execute(self) -> InstallationHealth:
        now = self.clock.now()
        everyone = self.users.list()
        active = [user for user in everyone if user.state is UserState.ACTIVE]
        counts = Counter(self.verdicts([user.id for user in active]).values())
        incidents = installation_incidents(
            self.scheduler.progress() if self.scheduler is not None else None, now, self.secrets
        )
        stalled = any(i.kind is InstallationIncidentKind.SCHEDULER_STALLED for i in incidents)
        present = {*counts, *((StatusVerdict.STALLED,) if stalled else ())}
        status = next(
            (verdict for verdict in _PRECEDENCE if verdict in present), StatusVerdict.SETUP
        )
        return InstallationHealth(
            status=status,
            incidents=incidents,
            users=dict(counts),
            disabled_users=len(everyone) - len(active),
            checked_at=now,
            hints=self._hints(now, {user.id for user in active}),
        )

    def _hints(self, now: datetime, may_sign_in: set[UserId]) -> tuple[InstallationHint, ...]:
        sources = self.hint_sources
        seen = [seen for seen in sources.sightings(now - HINT_WINDOW) if seen.user in may_sign_in]
        return (
            *installation_hints(seen, now, sources.guides),
            *instant_sync_hints(sources.instant_sync(), sources.guides),
        )
```

In `src/calendar_sync/bootstrap/container.py`, import `HintSources` from
`calendar_sync.application.operations.installation_health` and `InstantSyncSignals` and
`instant_sync_signals` from `calendar_sync.application.operations.installation_hints`, compose:

```python
installation_health = (
    GetInstallationHealth(
        adapters.users,
        lambda users: {user: status.health for user, status in statuses.of(users).items()},
        scheduler,
        adapters.clock,
        HintSources(
            _failure_causes(adapters.installation_units),
            adapters.providers.guides,
            _instant_sync_signals(adapters, public_address(settings)),
        ),
        adapters.providers.client_secrets,
    ),
)
```

and add after `_failure_causes`:

```python
def _instant_sync_signals(
    adapters: Adapters, address: str | None
) -> Callable[[], InstantSyncSignals]:
    """Who wants Instant Sync and whether providers reach the public address, for Installation
    Hints."""

    def read() -> InstantSyncSignals:
        with adapters.installation_units() as reading:
            owners = reading.instant_sync_owners()
        evidence = adapters.delivery_evidence.evidence(address) if address else {}
        return instant_sync_signals(owners, adapters.sync_cadence, address, evidence)

    return read
```

In `src/calendar_sync/interfaces/api/schemas.py`:

```python
HintKindValue = Literal[
    "shared_cause", "testing_mode", "unrecognized", "plain_http_address", "notices_not_arriving"
]
```

and in `InstallationHintResponse`:

```python
    kind: HintKindValue
    cause: CauseValue | None
    """The administrator's Cause the pattern shows; null for a hint about Instant Sync."""
```

In `src/calendar_sync/interfaces/api/status_payload.py`, in `installation_health_response`:

```python
            InstallationHintResponse(
                kind=hint.kind.value,
                cause=hint.cause.value if hint.cause is not None else None,
                users=hint.users,
                anchor=hint.anchor,
                provider=hint.provider.value if hint.provider else None,
            )
```

- [ ] **Step 4: Write the troubleshooting sections and the glossary entry**

In `docs/troubleshooting.md`, add before `## Problems you fix yourself`:

````markdown
## Instant Sync cannot reach the installation

Instant Sync runs a rule soon after Google or Microsoft reports a change, and needs them to reach
this installation from the internet. While it cannot, rules sync on their schedule, every five
minutes, and nothing is lost. **Installation health** on **People** names the cause below as soon
as anyone wants Instant Sync, with **How to fix** linking here.

### Instant Sync needs an HTTPS public address

**Symptom.** Installation health says people want instant sync, but this installation's public
address uses plain HTTP. Each person's **Instant sync** switch under **Settings → Your account** is
off and says Calendar Ghost needs a public HTTPS address.

**Confirm.** `CALENDAR_SYNC_PUBLIC_URL` in `.env` starts with `http://` and names a host on the
internet. A plain HTTP address on this machine or your home network is never hinted: providers
cannot reach it, and people's switches already say so.

**Fix.** Google and Microsoft report changes only to an `https` address with a valid certificate.
Serve `/api/v1/watch-notices/` through HTTPS, for example with a reverse proxy or Cloudflare
Tunnel, set `CALENDAR_SYNC_PUBLIC_URL` to that `https` address, and run `docker compose up -d`.
Within five minutes, Calendar Ghost asks each provider to report changes there. If you do not want
Instant Sync, each person can turn **Instant sync** off, and the hint goes away.

### Calendar providers cannot reach the installation

**Symptom.** Installation health says people want instant sync, but Google or Microsoft cannot
reach this installation. When no provider a person uses reaches it, their **Instant sync** switch is
off and says so, and their rules say "Syncs every 5 minutes".

**Confirm.** From a machine outside your network, send a request shaped like Google's to an
unknown registration. It changes nothing:

```sh
curl -i -X POST https://calendar.example.com/api/v1/watch-notices/google/00000000000000000000000000000000 \
  -H 'X-Goog-Channel-ID: 00000000000000000000000000000000' \
  -H 'X-Goog-Channel-Token: reachability-check' \
  -H 'X-Goog-Resource-ID: reachability-check' \
  -H 'X-Goog-Resource-State: exists'
```

Calendar Ghost answers `202 Accepted`. A timeout, a `502` or `504`, a `403` from a firewall, or a
sign-in page means the proxy or tunnel stops the request before it reaches Calendar Ghost.

**Fix.** Make the proxy or tunnel forward `POST /api/v1/watch-notices/` with its query string,
headers, and body unchanged, and let it through any sign-in gate, such as Cloudflare Access, and any
bot challenge. The certificate must be valid for the public name: providers refuse a self-signed
one. Google's notices count again with the next change in a watched calendar; Microsoft is asked
again on Calendar Ghost's next try, which waits longer after each failure, at most a day.
````

In `CONTEXT.md`, replace the **Installation Hint** entry's body (keep its `_Avoid_` line) with:

```markdown
**Installation Hint**:
A likely cause Installation Health suggests to Installation Administrators, never from one User's
content: an administrator's Cause any User met within a day, since only the administrator can fix
it; as patterns across Users, Google refusing two or more Users' grants about 7 days after they
authorized, which an OAuth app in Testing mode does, or two or more Users failing within a day for
a reason Calendar Ghost does not recognize (`unknown`), which the service logs name by the
provider's reason code; and, while any User who may sign in wants Instant Sync, a public address
that uses plain `http` at a host the internet reaches, or a provider whose Delivery Evidence is
failing. Each hint names its provider when it concerns one, its Cause when a failed provider call
explains it, how many Users show it, and the troubleshooting section that explains the fix. It
names no User, rule, calendar, or account. Hints are what People flags; a User's own problems are
not flagged, and the administrator finds them, with what the User does, on that User's page.
```

- [ ] **Step 5: Teach the Web UI the two hints**

In `web/src/lib/causes.ts`, extend the `switch` in `hintText`:

```ts
    case "plain_http_address":
      return i18n.t("people.health.hints.plainHttpAddress", { count })
    case "notices_not_arriving":
      return i18n.t("people.health.hints.noticesNotArriving", { count, ...words })
```

In `web/src/i18n/locales/en/people.json`, add to `health.hints` before `howToFixLabel`:

```json
      "plainHttpAddress": {
        "one": "{count} person wants instant sync, but calendar providers report changes only to an HTTPS address, and this installation's public address uses plain HTTP.",
        "other": "{count} people want instant sync, but calendar providers report changes only to an HTTPS address, and this installation's public address uses plain HTTP."
      },
      "noticesNotArriving": {
        "one": "{count} person wants instant sync, but {provider} cannot reach this installation, so changes in {calendar} wait for the next scheduled sync.",
        "other": "{count} people want instant sync, but {provider} cannot reach this installation, so changes in {calendar} wait for the next scheduled sync."
      },
```

Regenerate the API types:

```sh
.venv/bin/python scripts/export_openapi.py
cd web && pnpm run api:types && cd ..
```

- [ ] **Step 6: Run the tests and gates to verify they pass**

Run: `.venv/bin/pytest tests/application/test_installation_hints.py tests/application/test_installation_health.py tests/test_troubleshooting_anchors.py tests/adapters/test_installation_health_api.py tests/adapters/test_schema_enums.py tests/adapters/test_operator_overview_api.py tests/test_architecture.py tests/test_ubiquitous_language.py -q`
Expected: PASS

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports`
Expected: PASS

Run the frontend gate and build:

```sh
cd web
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
```

Expected: PASS; the build rewrites `src/calendar_sync/interfaces/api/static/`.

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/application/operations/installation_hints.py \
  src/calendar_sync/application/operations/installation_health.py \
  src/calendar_sync/bootstrap/container.py src/calendar_sync/interfaces/api/schemas.py \
  src/calendar_sync/interfaces/api/status_payload.py docs/troubleshooting.md CONTEXT.md \
  tests/application/test_installation_hints.py tests/application/test_installation_health.py \
  tests/test_troubleshooting_anchors.py tests/adapters/test_installation_health_api.py \
  web/src/lib/causes.ts web/src/lib/causes.test.ts web/src/i18n/locales/en/people.json \
  web/openapi.json web/src/lib/api-schema.ts src/calendar_sync/interfaces/api/static
git commit -m "Tell administrators when providers cannot reach the installation for Instant Sync

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 20: Documentation, glossary, and ADR 0036

**Files:**
- Create: `docs/instant-sync.md`
- Create: `docs/adr/0036-instant-sync-through-provider-notices.md`
- Create: `tests/test_instant_sync_docs.py`
- Modify: `docs/adr/0029-isolate-users-in-one-sqlite-database.md` (amendment)
- Modify: `docs/superpowers/specs/2026-10-09-multi-user-design.md` (phase 3)
- Modify: `CONTEXT.md`, `tests/test_ubiquitous_language.py`, `AGENTS.md`
- Modify: `docs/deployment.md`, `docs/self-hosting.md`, `docs/sync-model.md`, `docs/troubleshooting.md`, `docs/architecture.md`, `docs/data-ownership.md`
- Modify: `README.md`, `CHANGELOG.md`
- Modify: `site/src/docs/pages.ts`, `site/src/i18n/en.ts` (render `/docs/instant-sync`)
- Test: `tests/test_instant_sync_docs.py`, `tests/test_ubiquitous_language.py`, the site's `pnpm test`, `pnpm run check`, `pnpm run build`, `pnpm run e2e`

**Interfaces:**
- Consumes: `AVAILABILITY_ANCHORS` (Task 2); the rule-page anchors in `web/src/lib/instant-sync.ts` and `INSTANT_SYNC_HELP_URL` (Task 18); `PLAIN_HTTP_ANCHOR`, `NOT_ARRIVING_ANCHOR` sections (Task 19).
- Produces: `docs/instant-sync.md` with sections `#not-in-your-plan`, `#no-public-https-address`, `#providers-cannot-reach-the-installation`, `#waiting-for-the-provider`, `#this-calendar-cannot-be-watched`, `#forward-the-notices-path`, `#check-that-it-works`, `#cost-per-run`; the site page `/docs/instant-sync`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_instant_sync_docs.py`:

```python
"""The Instant Sync guide holds every section the API and the Web UI link to, and the site
renders it where the Web UI opens it."""

import re
from pathlib import Path

from calendar_sync.domain.watches import AVAILABILITY_ANCHORS

REPOSITORY = Path(__file__).resolve().parents[1]
GUIDE = REPOSITORY / "docs" / "instant-sync.md"
# Each reason a rule may sync on its schedule that the guide explains.
SECTIONS = {
    "not-in-your-plan",
    "no-public-https-address",
    "providers-cannot-reach-the-installation",
    "waiting-for-the-provider",
    "this-calendar-cannot-be-watched",
}


def github_anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def guide_anchors() -> set[str]:
    return {
        github_anchor(line.lstrip("#"))
        for line in GUIDE.read_text().splitlines()
        if re.match(r"#{2,4} ", line)
    }


def test_every_reason_instant_sync_is_unavailable_has_its_section() -> None:
    assert SECTIONS <= guide_anchors(), SECTIONS - guide_anchors()


def test_the_api_links_only_to_sections_of_the_guide() -> None:
    assert set(AVAILABILITY_ANCHORS.values()) <= SECTIONS


def test_the_rule_page_links_only_to_sections_of_the_guide() -> None:
    source = (REPOSITORY / "web" / "src" / "lib" / "instant-sync.ts").read_text()
    named = set(re.findall(r'^\s+[a-z_]+: "([a-z0-9-]+)",$', source, re.MULTILINE))

    assert named == SECTIONS


def test_the_web_ui_opens_the_guide_where_the_site_renders_it() -> None:
    pages = (REPOSITORY / "site" / "src" / "docs" / "pages.ts").read_text()
    brand = (REPOSITORY / "web" / "src" / "lib" / "brand.ts").read_text()

    assert '{ slug: "instant-sync", source: "docs/instant-sync.md" }' in pages
    assert "`${DOCS_URL}/instant-sync`" in brand
```

In `tests/test_ubiquitous_language.py`, add two terms to `AVOIDED`, keeping its order:

```python
("parent mapping",)
("push sync",)
("real-time sync",)
("recurring master",)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_instant_sync_docs.py tests/test_ubiquitous_language.py -q`
Expected: FAIL (`docs/instant-sync.md` does not exist; `pages.ts` does not name it)

- [ ] **Step 3: Write the guide and render it on the site**

Create `docs/instant-sync.md`:

````markdown
# Instant Sync

Instant Sync runs a rule soon after Google or Microsoft reports that something changed in its
Source Calendar, instead of waiting for the next Scheduled Sync. It is optional. Without it, every
rule still syncs every five minutes, and nothing else changes.

## What it does, and what it does not promise

- When a provider reports a change, Calendar Ghost waits until 10 seconds pass without another
  report for the same rule, and at most 30 seconds after the first, then runs each rule whose
  Source Calendar the report may concern. The run is an ordinary sync: it reads both calendars'
  changes, writes only what differs, and records it in **Activity**.
- A rule runs from Instant Sync at most once every 30 seconds. Up to two such runs happen at once,
  beside the scheduler's four, so neither kind waits behind the other.
- There is no promise from the moment of your edit. Google usually reports within seconds.
  Microsoft does not publish how fast it reports. A report can be late, and Google drops a small
  share of them in normal operation.
- Scheduled Sync every five minutes and the daily full pass keep running. A lost report delays a
  change by at most five minutes, as before.
- Only Source Calendars are watched. An edit made directly in a Destination Calendar is still put
  back by the next Scheduled Sync.
- A rule whose last run failed waits for Scheduled Sync, which retries it with its own backoff,
  until a run succeeds.

## Requirements

- **A public `https` address with a valid certificate**, at the root of its host, set as
  `CALENDAR_SYNC_PUBLIC_URL`, such as `https://calendar.example.com`. Google and Microsoft send
  reports only to `https`. A plain `http` address, a self-signed certificate, or a name that only
  your network resolves cannot receive them.
- **Google and Microsoft must reach `POST /api/v1/watch-notices/` at that address from the
  internet.** Nothing else needs to be public: you may forward only this path and keep the rest of
  Calendar Ghost on your network.
- **A reverse proxy or tunnel that forwards that path unchanged**: its query string, headers, and
  body. Microsoft checks the address with a `validationToken` query parameter and sends JSON
  bodies; Google sends `X-Goog-*` headers. Calendar Ghost refuses bodies above 64 KB.
- **No sign-in gate or bot challenge on that path.** Providers cannot pass Cloudflare Access, a
  proxy's password prompt, or a browser check. Each report carries a secret token that Calendar
  Ghost checks; a request without a matching one changes nothing.

Tailscale Serve keeps a name inside your tailnet, so providers cannot reach it. Tailscale Funnel
publishes a name to the internet.

If you forward only the notices path and also use `CALENDAR_SYNC_PUBLIC_URL` for incident email
links, those links open only where that address reaches the whole Web UI, such as on your own
network.

### Forward the notices path

**Caddy** obtains and renews the certificate itself. To forward only the notices path:

```text
calendar.example.com {
	handle /api/v1/watch-notices/* {
		reverse_proxy 127.0.0.1:8000
	}
	respond 404
}
```

To serve the whole Web UI at the same name, use `reverse_proxy 127.0.0.1:8000` alone, and set
`CALENDAR_SYNC_SECURE_COOKIES=true`.

**nginx**, with a certificate from Let's Encrypt or another public authority:

```nginx
server {
    listen 443 ssl;
    server_name calendar.example.com;
    ssl_certificate     /etc/letsencrypt/live/calendar.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/calendar.example.com/privkey.pem;

    location /api/v1/watch-notices/ {
        # No path after the address, so nginx passes the path and query string unchanged.
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 64k;
    }

    location / {
        return 404;
    }
}
```

**Cloudflare Tunnel** needs no open port on your router, which suits a Raspberry Pi at home.
Create a named tunnel, route the name to it, and forward only the notices path in
`/etc/cloudflared/config.yml`:

```sh
cloudflared tunnel create calendar-ghost
cloudflared tunnel route dns calendar-ghost calendar.example.com
```

```yaml
tunnel: <tunnel-uuid>
credentials-file: /etc/cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: calendar.example.com
    path: ^/api/v1/watch-notices/
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Run it with `cloudflared tunnel run calendar-ghost`, or install it as a service with
`cloudflared service install`. If Cloudflare Access protects the name, add a Bypass policy for
`/api/v1/watch-notices/`. A quick tunnel (`cloudflared tunnel --url http://127.0.0.1:8000`) works
for a test, but its address changes each time it starts.

## Turn it on

1. Forward the notices path as above, and check it from outside your network (see
   [Providers cannot reach the installation](#providers-cannot-reach-the-installation)).
2. Set `CALENDAR_SYNC_PUBLIC_URL=https://calendar.example.com` in `.env` and run
   `docker compose up -d`.
3. Instant sync is on for each person by default, under **Settings → Your account**. Within five
   minutes, Calendar Ghost asks Google or Microsoft to report changes for the Source Calendar of
   each enabled rule.

There is no other setting. Changing the address later moves every watch to the new one within
five minutes; providers may still send a few reports to the old address until its registrations
expire, within about 7 days. Unsetting `CALENDAR_SYNC_PUBLIC_URL` stops Instant Sync, and incident
emails then come without a link.

## Check that it works

1. Open a rule. **When it syncs** says **Syncs instantly** once its provider confirmed it will
   report changes. Google confirms with its first report, usually within seconds; Microsoft
   confirms when it accepts the request. Until then it says **Syncs every 5 minutes** with
   [Waiting for the provider](#waiting-for-the-provider).
2. Edit an event in the rule's Source Calendar. **Activity** usually lists the change within a
   minute.
3. If the **Instant sync** switch under **Settings → Your account** is off with a reason, its
   **Learn why** link opens the matching section below. Administrators also see the cause on
   **People** under **Installation health**.

## When Instant Sync is unavailable

Each section below is the one the switch or a rule links to. Meanwhile rules sync every five
minutes, and nothing is lost.

### Not in your plan

When an administrator turns Plans on, each person's Plan decides whether it includes Instant Sync
and how often Scheduled Sync runs. Only an administrator can change your Plan. With Plans off,
which is the default, everyone has Instant Sync.

### No public HTTPS address

`CALENDAR_SYNC_PUBLIC_URL` is unset, is not at the root of its host, or uses plain `http`. Forward
the notices path through HTTPS as in [Requirements](#requirements), set the address, and restart.
An administrator sees the same on **People** when the address uses plain `http` at a host the
internet reaches ([troubleshooting](troubleshooting.md#instant-sync-needs-an-https-public-address)).

### Providers cannot reach the installation

Every provider your rules read from tried to report a change and failed: Google did not deliver
its first report within 2 minutes of a new watch, or Microsoft refused the address when Calendar
Ghost asked it to report changes. Check the path from a machine outside your network:

```sh
curl -i -X POST https://calendar.example.com/api/v1/watch-notices/google/00000000000000000000000000000000 \
  -H 'X-Goog-Channel-ID: 00000000000000000000000000000000' \
  -H 'X-Goog-Channel-Token: reachability-check' \
  -H 'X-Goog-Resource-ID: reachability-check' \
  -H 'X-Goog-Resource-State: exists'
```

Calendar Ghost answers `202 Accepted` and changes nothing, because no registration has that
identifier. Anything else comes from the proxy or tunnel: fix it as
[troubleshooting](troubleshooting.md#calendar-providers-cannot-reach-the-installation) explains.
Once a report arrives, the switch works again. An authenticated report always counts as proof that
delivery works, so a rule never waits on this check.

### Waiting for the provider

The rule's watch exists, but its provider has not confirmed it yet. This usually lasts seconds. It
lasts longer when:

- the provider is refusing or limiting requests for now: Calendar Ghost tries again later, waiting
  longer after each failure, at most a day;
- two people here connected the same Microsoft account: Microsoft lets one application watch a
  mailbox only once, so only one of them gets Instant Sync for it, and the other's rules sync on
  their schedule and are tried again daily; or
- the account needs reauthorization, which its rules already say.

### This calendar cannot be watched

Its provider cannot report changes in this calendar to Calendar Ghost. Microsoft reports changes
only for the signed-in person's own mailbox, so a calendar shared from another mailbox cannot be
watched. Its rules sync every five minutes. Every Google calendar can be watched.

### You turned it off

Turn **Instant sync** on again under **Settings → Your account**.

## Privacy

- Reports carry no event content. Google's says only which watch it concerns and that something
  changed. Microsoft's names the changed event's identifier, which Calendar Ghost ignores: it reads
  only which registration a report concerns, its secret token, and what kind of report it is, then
  runs the rule, which reads the calendars as any sync does.
- Calendar Ghost stores, per watch, the Connected Account, what it covers (one Google calendar or
  one Microsoft mailbox) and which Source Calendars it covers; per registration, the provider's
  handle, a SHA-256 hash of its secret token, the address it points at, its state, and its times;
  per rule, a counter of requested and handled runs; and per provider and public address, when a
  report last arrived and when delivery last failed.
- Logs never contain tokens, handles, registration identifiers, or report bodies.
- Google and Microsoft learn the public address, and which calendars or mailboxes Calendar Ghost
  watches, which they already know.
- The notices path takes no session, so anyone can send a request to it. Calendar Ghost answers
  every one alike and acts only on one whose registration and secret token match.

## Cost per run

A run from Instant Sync is an ordinary incremental run, so it costs what any run costs
([the synchronization model](sync-model.md#cost-of-a-run)): with nothing to do, one change listing
per calendar, and for each changed event the writes it needs. Instant Sync adds no run that would
not otherwise happen within five minutes; it moves runs earlier and, for Outlook, adds the wakes
described below. Keeping watches costs a few calls per account and calendar each week: Google
replaces each channel before it expires (one call to create it, one to stop the old one), and
Microsoft renews each subscription in place, at most every 7 days. Every call counts in each
person's provider calls on **People**.

To measure it on your installation:

1. Turn on debug logging only if you want each call listed (`CALENDAR_SYNC_LOG_LEVEL=DEBUG`); the
   count alone is on every run's closing line at `INFO`.
2. Edit one event in a watched Source Calendar and wait for **Activity** to list it.
3. Read the run's closing line, whose `provider_calls=` is the run's count:

   ```sh
   docker compose logs --since 3m app | grep "run finished"
   ```

4. Repeat three times for each provider pair and take the middle value. To measure an Outlook
   wake with nothing to do, edit an event in a calendar of the same mailbox that no rule reads.

## Outlook wakes every Source Calendar of its mailbox

Microsoft reports changes for a whole mailbox, never for one calendar. A change anywhere in it,
including an event Calendar Ghost wrote to another calendar of the same mailbox, wakes every rule
whose Source Calendar is in that mailbox. Such a run finds nothing to do and costs its listings.
It never runs a rule whose Source Calendar is elsewhere. When a rule writes into the mailbox its
own Source Calendar belongs to, its write wakes it once more; that run writes nothing, so it stops
there. Calendar Ghost keeps one subscription per Microsoft account, and Microsoft allows 1,000 per
mailbox across every application.

## Plans

Instant Sync asks one question of the installation: does this person's Sync Cadence allow it? With
Plans off, the default, every person's does, and Scheduled Sync runs every five minutes. When Plans
arrive, each Plan's shortest sync interval decides it, and its shortest value is "instant". There
is no separate administrator switch: each person can turn Instant Sync off for themselves
([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).
````

In `site/src/docs/pages.ts`, register it:

```ts
export const DOC_PAGES = [
  { slug: "self-hosting", source: "docs/self-hosting.md" },
  { slug: "troubleshooting", source: "docs/troubleshooting.md" },
  { slug: "instant-sync", source: "docs/instant-sync.md" },
] as const
```

In `site/src/i18n/en.ts`, add to `docs.pages` after `troubleshooting`:

```ts
      "instant-sync": {
        description:
          "Run rules soon after Google or Microsoft reports a change: the public HTTPS address it needs, reverse proxy and Cloudflare Tunnel examples, how to check it, and what it costs.",
      },
```

- [ ] **Step 4: Record the decision**

Create `docs/adr/0036-instant-sync-through-provider-notices.md`:

```markdown
# Run rules soon after their provider reports a change (Instant Sync)

Builds on [ADR 0022](0022-route-calendar-requests-by-provider.md) (amended with provider
descriptors), [ADR 0027](0027-lapsed-authorization-and-automatic-recovery.md),
[ADR 0028](0028-plans-apart-from-commercial-mode.md), and
[ADR 0033](0033-decide-an-incidents-next-step-in-the-domain.md). Amends
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md).

## Context

Every rule syncs every five minutes, so an edit can take five minutes to appear in the destination.
Polling faster multiplies provider calls for every rule, all day, against quotas that every User
of an installation shares.

Google and Microsoft can report changes to an `https` address instead. Google watches one calendar
per channel (`events.watch`); channels cannot be renewed, only replaced, and Google drops a small
share of reports in normal operation. Microsoft Graph documents event subscriptions only for a
whole mailbox (`/me/events`), refuses a second identical subscription with `409 Conflict`,
validates the address before it creates one, renews in place with `PATCH`, keeps one at most
10,080 minutes, and expects an answer to each report within 3 seconds.

A self-hosted installation often has no public address, and the Community Edition promises no
hosted coordinator. Plans, which come next, must be able to reserve fast synchronization for some
Users without a change of copy or schema.

## Decision

- **Instant Sync is optional and needs no new setting.** It is possible when
  `CALENDAR_SYNC_PUBLIC_URL` is an `https` address at the root of its host. It is on for every
  enabled rule of a User whose Sync Cadence allows it, unless the User turns it off
  (`users.instant_sync`, on by default).
- **Plans decide through one port.** `SyncCadencePolicy` returns each User's `SyncCadence`: whether
  Instant Sync is allowed, and how often Scheduled Sync runs. Until Plans exist, `EveryUserInstant`
  allows it for everyone with a five-minute Scheduled Sync, which is what "Plans off" means in
  ADR 0028.
- **The domain decides and explains availability**, in the style of ADR 0033:
  `instant_sync_availability` returns `on`, `off_by_user`, `not_in_plan`, `no_public_address`, or
  `not_reaching`, and each reason that is not the User's own names its section of
  `docs/instant-sync.md`. `effective_cadence` says per rule whether it syncs instantly or why not,
  adding `not_watchable` and `waiting_for_provider`.
- **Only Source Calendars are watched.** Each provider's adapter chooses a Watch Scope: one calendar
  for Google, the whole mailbox for Outlook. A Calendar Watch is one row per User, Connected
  Account, and scope, and records the Source Calendars it covers.
- **A Watch Registration carries its own identity.** Calendar Ghost chooses its identifier, which is
  part of the notice address, and a fresh secret token, whose SHA-256 hash it keeps. Its state
  (`creating`, `live`, `retiring`, `abandoned`) changes only through conditional updates from a
  named state, so a late receipt or notice changes nothing. A Graph `409` adopts only a
  subscription whose address holds this exact identifier, and never deletes one it cannot identify.
- **Notices become durable Instant Sync Requests.** The public route
  `POST /api/v1/watch-notices/{provider_slug}/{registration_id}` reads the request through the
  provider's `NoticeReader`, and the `WatchNoticeInbox` checks the token hash and provider handle in
  constant time, then raises a per-rule request for each enabled rule of the registration's User
  whose Source Calendar the watch covers. It makes one short write transaction and no provider call,
  and answers `202` alike for known, unknown, and refused notices, or `503` when storage stays
  locked for a second, so the provider retries.
- **An in-process dispatcher runs the requests** through the scheduler's own path. A rule runs once
  10 seconds pass without another notice for it, at most 30 seconds after the first, and at most
  once every 30 seconds. Its concurrency of 2 is apart from the scheduler's 4. After the run
  returns, succeeded or failed, the request is acknowledged up to the notice the run saw. A rule
  whose last run failed is left to Scheduled Sync until a run succeeds.
- **Watch upkeep runs beside the scheduler**, every five minutes with its own concurrency of 2 and a
  budget of 200 provider calls a cycle, in order of the earliest due work, so no User starves.
  `unauthorized` lapses the account through ADR 0027; any other failure retries with backoff capped
  at one day, and never lapses an account.
- **Delivery Evidence only explains.** One installation row per provider and public address records
  when delivery last succeeded and last failed. It informs the switch, each rule's reason, and
  Installation Health, and never removes a watch or blocks a run: an authenticated notice is itself
  proof that delivery works.
- **Descriptors gain `watcher` and `notice_reader`**, so no code outside a provider's package
  branches on its Provider Kind.
- Scheduled Sync every five minutes and the daily full pass do not change; they catch every missed
  or refused notice.

## Consequences

The installation gains its first public route that writes, and the `WatchNoticeInbox` is the one
public-route writer that crosses Users (ADR 0029, amended). Notices carry no event content and none
is logged. Operators who want Instant Sync must publish one path over HTTPS; the guide gives
reverse-proxy and tunnel examples, and Installation Health names an `http` public address or a
provider that cannot reach the installation. Outlook's whole-mailbox subscriptions wake every
source rule of the mailbox, including after the installation's own writes, which costs quiet runs
but never runs another rule. Migration 31 adds the owned tables and the installation's Delivery
Evidence. Rolling back leaves providers sending reports to a route that answers `404` until their
registrations expire, within about 7 days, while polling carries on. Phase 3 of the multi-user
design implements `SyncCadencePolicy` from Plans.

## Alternatives considered

- **Faster polling.** Rejected: one-minute polling makes five times the calls for every rule all day
  and is still not prompt; notices cost calls only when something changes.
- **A relay for installations without a public address.** Rejected: it would be a hosted
  coordinator the self-hosting promise rules out, and it would see which calendars change.
- **Watching Destination Calendars too.** Rejected: Drift is rare and Scheduled Sync repairs it, and
  watching destinations would double the registrations to keep alive.
- **An installation-wide reachability gate**, a test or setting before Instant Sync may start.
  Rejected: providers deliver independently and only to their own watches, so one test proves
  little; per-provider Delivery Evidence explains instead, and a notice proves delivery by itself.
- **One Graph subscription per calendar.** Rejected: Microsoft documents event subscriptions only for
  a whole mailbox, and a mailbox allows 1,000 subscriptions across every application.
- **Running the rule inside the notice request.** Rejected: Graph needs an answer within 3 seconds,
  and a run takes longer; a durable request also survives a crash.
```

Append to `docs/adr/0029-isolate-users-in-one-sqlite-database.md`:

```markdown

## Amendment: the Watch Notice inbox writes across Users (2026-10-14)

A provider sends a Watch Notice to a public route that has no session and names only a Watch
Registration ([ADR 0036](0036-instant-sync-through-provider-notices.md)). Finding the rules it
concerns means reading a registration before its User is known, so the `WatchNoticeInbox`
(`application/operations/ports.py`, `infrastructure/persistence/watch_inbox.py`) is the one
public-route writer that crosses Users. It is narrow: it reads and writes only Watch
Registrations, Instant Sync Requests, and Delivery Evidence, acts only after the notice's token
hash and provider handle match in constant time, and raises requests only for the enabled rules of
the registration's own User whose Source Calendar the watch covers. The isolation test's list of
installation-wide receivers names its module beside the scheduler, the Instant Sync loops, the
Operator Overview, and migrations.
```

In `docs/superpowers/specs/2026-10-09-multi-user-design.md`, replace phase 3:

```markdown
3. **Plans.** Plan definitions and assignment, the four limits, a per-User sync interval in the
   scheduler, and Plan Hold. Plans implement the `SyncCadencePolicy` port
   (`application/sync/watch_ports.py`) from each Plan's shortest sync interval, whose shortest value
   is "instant" ([ADR 0036](../../adr/0036-instant-sync-through-provider-notices.md)); until then,
   `EveryUserInstant` gives every User Instant Sync and a five-minute Scheduled Sync.
```

- [ ] **Step 5: Update the glossary and agent instructions**

In `CONTEXT.md`, replace the **Scheduled Sync** entry:

```markdown
**Scheduled Sync**:
An incremental sync requested by the local scheduler every five minutes, or as often as the User's
Sync Cadence sets. It needs no public address, and it catches every change Instant Sync missed.
_Avoid_: Cron sync, background sync
```

Add after the **Sync Now** entry, still under `## Synchronization Progress`:

```markdown
## Instant Sync

**Instant Sync**:
A sync of a Directional Sync Rule run soon after its Source Calendar's provider reports a change
that may concern it, instead of at the next Scheduled Sync. It runs through the same behavior as a
Scheduled Sync. It needs a public `https` address the providers reach, and runs for every enabled
rule of a User whose Sync Cadence allows it, unless the User turns it off. It promises no delivery
time: Scheduled Sync and the daily full pass still run and catch every missed report. Only Source
Calendars are watched, so Drift in a destination is still repaired by Scheduled Sync (ADR 0036).
_Avoid_: Real-time sync, push sync, live sync

**Sync Cadence**:
How a User's rules may synchronize: whether Instant Sync is allowed, and how often Scheduled Sync
runs. With Plans off, every User has Instant Sync and a five-minute Scheduled Sync; once Plans
exist, a Plan's shortest sync interval decides it, whose shortest value is "instant".
_Avoid_: Sync frequency, polling interval

**Calendar Watch**:
A provider's commitment to report changes in one Watch Scope of a User's Connected Account. It
records which Source Calendars it covers, so a report wakes only rules whose Source Calendar it
covers. A watch exists only while an enabled rule needs it.
_Avoid_: Subscription, webhook, channel

**Watch Scope**:
What one Calendar Watch covers, as its provider allows: one calendar for Google, and the whole
mailbox for Outlook, whose event reports cannot be limited to one calendar.
_Avoid_: Watch target, watched resource

**Watch Registration**:
One Google channel or Microsoft Graph subscription that carries a Calendar Watch. Its own
identifier is part of its notice address, and its secret token is kept only as a hash. It is
created, confirmed, renewed or replaced before it expires, and stopped once nothing needs it;
while one replaces another, notices on both count.
_Avoid_: Webhook, hook

**Watch Notice**:
One request a provider sends about a Watch Registration: that it started, that something in its
scope changed, that reports were missed, that it needs renewing, or that it was removed. It carries
no event content, and none is logged. A notice whose registration, token, or handle does not match
changes nothing.
_Avoid_: Push notification, webhook event, ping

**Instant Sync Request**:
The durable, per-rule record that a Watch Notice asked the rule to run soon. A run acknowledges
what it saw once it returns, succeeded or failed, and a notice during the run asks again. It
survives a restart.
_Avoid_: Wake-up flag, dirty flag

**Delivery Evidence**:
What the installation knows about whether one provider reaches its current public address: when a
notice last arrived or a registration proved delivery, and when delivery last failed. It belongs to
the installation, not a User. It only explains: it never removes a watch or blocks a run.
_Avoid_: Reachability check, health probe
```

Add a row to the Interface Wording table, after the **Reconciliation** row:

```markdown
| Instant Sync | "Instant sync" under Settings → Your account, a switch that is on by default; where it cannot run, it is disabled, says why, and offers "Learn why", opening that reason's section of the Instant Sync guide. On a rule, "Syncs instantly", or "Syncs every 5 minutes" with why |
```

In `AGENTS.md`, replace the sentence from "Users have shipped:" to "receive the installation-wide
`InstallationUnitOfWork`." with:

```markdown
Users have shipped: every record belongs to one User, use cases receive a unit of work scoped to
that User, and only the scheduler and the Instant Sync loops beside it, migrations, the Operator
Overview, and the Watch Notice inbox receive the installation-wide `InstallationUnitOfWork`; the
inbox is the one public-route writer that crosses Users (ADR 0029, amended, and ADR 0036).
```

and in the public routes sentence, replace "`/api/v1/password-resets`), static application files,
and `/health` are intentionally public;" with:

```markdown
`/api/v1/password-resets`), the providers' Watch Notice route
(`/api/v1/watch-notices/{provider_slug}/{registration_id}`, which acts only on a notice carrying
its registration's secret token, ADR 0036), static application files, and `/health` are
intentionally public;
```

- [ ] **Step 6: Update the reference and operational documents**

`docs/deployment.md`:

- Replace "Five-minute polling avoids a public Google webhook." in **Raspberry Pi** with:

  ```markdown
  Scheduled Sync every five minutes needs no public address, so a Pi on a home network works as
  it is. [Instant Sync](instant-sync.md) is optional: Google and Microsoft must reach the Pi at a
  public HTTPS address, which a home network usually gets through Cloudflare Tunnel rather than an
  open router port.
  ```

- Replace "Do not expose the service directly to the public internet." with:

  ```markdown
  Do not expose the service directly to the public internet. [Instant Sync](instant-sync.md) needs
  Google and Microsoft to reach only `/api/v1/watch-notices/`: forward that path through HTTPS and
  keep the rest on your network.
  ```

- After "A scheduler pass runs up to four different rules at once, so one rule waiting on its
  provider does not hold up the rest.", add: "Instant Sync runs up to two more at once, apart from
  the scheduler's, so at most six rules run together."
- After the Migration 30 paragraph (replacing a Migration 31 paragraph if Task 5 wrote one), add:

  ```markdown
  Migration 31 adds the owned tables `calendar_watches`, `watch_coverage`, `watch_registrations`,
  and `instant_sync_requests`, each with `user_id` and references that are removed with their
  account, rule, and User; the column `users.instant_sync` (default `1`, on); and the installation
  table `delivery_evidence` ([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)). Nothing
  is rewritten: watches appear at the first upkeep after start, within five minutes, and only when
  `CALENDAR_SYNC_PUBLIC_URL` is an `https` address. Rolling back works with the same database:
  earlier releases ignore the tables and column and no longer answer at `/api/v1/watch-notices/`,
  so Google and Microsoft receive `404` until their registrations expire, within about 7 days,
  while rules keep syncing every five minutes. Upgrading again keeps registrations that are still
  live, and deletes and creates again those that expired.
  ```

- In **Incident notifications**, after the sentence ending "otherwise email is sent without a
  link, as before.", add: "An `https` address also makes [Instant Sync](instant-sync.md) possible."

`docs/self-hosting.md`, in **5. Use a LAN host or HTTPS**, replace "Do not expose the service
directly to the public internet." with "Do not expose the service directly to the public internet;
Instant Sync below needs only one path to be public." and add before `## 6. Connect monitors and
agents`:

```markdown
### Turn on Instant Sync (optional)

Rules sync every five minutes without anything below. To have a rule run soon after its Source
Calendar changes, Google and Microsoft must reach this installation at a public HTTPS address:

1. Forward `/api/v1/watch-notices/` through HTTPS with a reverse proxy or Cloudflare Tunnel
   ([examples](instant-sync.md#forward-the-notices-path)). Tailscale Serve keeps a name inside your
   tailnet, which providers cannot reach.
2. Set `CALENDAR_SYNC_PUBLIC_URL` in `.env` to that address, such as
   `https://calendar.example.test`, and run `docker compose up -d`.
3. Open a rule. Within five minutes, **When it syncs** says **Syncs instantly**.
   [Check that it works](instant-sync.md#check-that-it-works) explains more.

Each person can turn **Instant sync** off under **Settings → Your account**.
```

`docs/sync-model.md`:

- In **Initial and incremental synchronization**, replace "Later runs request both change feeds
  every five minutes or through Sync Now." with "Later runs request both change feeds every five
  minutes, soon after a provider reports a change (Instant Sync), or through Sync Now."
- Add after **Cost of a run**:

  ```markdown
  ## Instant Sync

  When an installation has a public `https` address, a rule also runs soon after its Source
  Calendar's provider reports a change ([Instant Sync](instant-sync.md),
  [ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).

  - Upkeep keeps one Calendar Watch per User, Connected Account, and Watch Scope for the Source
    Calendars of enabled rules, every five minutes: it creates, confirms, renews or replaces, and
    stops Watch Registrations, and records which Source Calendars each watch covers.
  - A Watch Notice raises an Instant Sync Request for every enabled rule of the watch's User whose
    Source Calendar the watch covers. The request is durable, so a restart loses nothing.
  - The dispatcher runs a requested rule once 10 seconds pass without another notice for it, at
    most 30 seconds after the first, and at most once every 30 seconds per rule, up to two rules
    at once. A run takes the rule lock like any other, so scheduled, manual, and instant runs of one
    rule never overlap.
  - After the run returns, succeeded or failed, its request is acknowledged up to the notice it
    saw; a notice during the run asks for another. A failed run leaves the rule to Scheduled Sync's
    retries and backoff until a run succeeds. A crash before acknowledgement runs the rule again
    after restart.
  - A run from Instant Sync is an ordinary incremental run that reads both change feeds, so it
    costs what any run costs. Destination Drift is still repaired by the next Scheduled Sync,
    because only Source Calendars are watched. An Outlook watch covers the whole mailbox, so a
    change anywhere in it, including the installation's own writes there, wakes every source rule
    of that mailbox; such a run finds nothing to do and writes nothing.
  ```

`docs/troubleshooting.md`: end **Instant Sync needs an HTTPS public address** with "See
[Instant Sync](instant-sync.md#no-public-https-address) for the requirements and proxy examples."
and **Calendar providers cannot reach the installation** with "See
[Forward the notices path](instant-sync.md#forward-the-notices-path) for working proxy and tunnel
examples."

`docs/architecture.md`:

- In **Bounded contexts**, end the Synchronization bullet with "Calendar Watches of one User and
  their upkeep (`UpkeepWatches`) live here too." and the Operations bullet with "It also runs
  Instant Sync across Users: watch upkeep, the dispatch of Instant Sync Requests, and the Watch
  Notice inbox."
- In **Provider descriptors**, add a bullet after the calendar roles:

  ```markdown
  - when the provider can report changes, its `CalendarWatcher`, which chooses a Watch Scope and
    creates, extends, adopts, and stops Watch Registrations, and its `NoticeReader`, which turns a
    neutral `NoticeRequest` (headers, query, body) into Watch Notices, so no Starlette type crosses
    the descriptor ([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).
  ```

- Add after **Provider descriptors**:

  ```markdown
  ## Instant Sync loops

  Two asyncio loops start and stop with the scheduler in the FastAPI lifespan
  (`infrastructure/scheduling.py`):

  - `WatchKeeper` runs `WatchUpkeep` every five minutes, with its own concurrency of 2 and a budget
    of 200 provider calls a cycle, in order of each User's earliest due work. Slow provider calls
    never delay rule runs or the scheduler's heartbeat.
  - `InstantSyncDispatcher` wakes when the notice route sets its event from a worker thread, and on
    a timer for the earliest moment a pending request becomes due. It holds a reservation for each
    rule it queued, runs at most 2 at once apart from the scheduler's 4, and runs each through
    `ScheduledPass.run` before acknowledging its request.

  The public route `POST /api/v1/watch-notices/{provider_slug}/{registration_id}` streams at most
  64 KB, asks the provider's `NoticeReader` to read it, and hands the notices to the
  `WatchNoticeInbox`. The inbox is the one public-route writer that crosses Users (ADR 0029,
  amended): one short transaction on a connection that waits at most one second for SQLite's lock,
  touching only registrations, Instant Sync Requests, and Delivery Evidence, with no provider call.
  ```

- In **Persistence**, replace "only the scheduled pass, the Operator Overview, the migrations, and
  the composition root reach `InstallationUnitOfWork`" with "only the scheduled pass and the
  Instant Sync loops, the Watch Notice inbox, the Operator Overview, the migrations, and the
  composition root reach `InstallationUnitOfWork`".

`docs/data-ownership.md`:

- In **What the installation stores**, add after the provider call counts bullet:

  ```markdown
  - Instant Sync, when the installation has a public HTTPS address: each Calendar Watch's Connected
    Account, what it covers, and which Source Calendars; each Watch Registration's provider handle,
    a SHA-256 hash of its secret token, the address it points at, its state, and its times; per
    rule, a counter of requested and handled runs; and, for the installation, when each provider
    last reached the public address and last failed to. Reports from Google and Microsoft carry no
    event content and are never stored or logged ([Instant Sync](instant-sync.md#privacy)).
  ```

- In **What can leave the machine**, end item 1 with: "With Instant Sync, the installation also
  tells Google and Microsoft its public address so they can report that a watched calendar or
  mailbox changed; their reports carry no event content."

`README.md`:

- Replace the **Scheduling** row's behavior with: "Source and destination incremental polling every
  five minutes plus **Sync Now**; with a public HTTPS address, [Instant Sync](docs/instant-sync.md)
  runs a rule soon after Google or Microsoft reports a change"
- End the `CALENDAR_SYNC_PUBLIC_URL` row's purpose with: "An `https` address that Google and
  Microsoft reach also turns on [Instant Sync](docs/instant-sync.md)".

`CHANGELOG.md`, first entry under `## [Unreleased]` → `### Added`:

```markdown
- Instant Sync: with a public HTTPS address in `CALENDAR_SYNC_PUBLIC_URL` that Google and Microsoft
  reach at `/api/v1/watch-notices/`, a rule runs soon after its provider reports a change in its
  Source Calendar instead of waiting for the next five-minute sync. Scheduled syncs and the daily
  pass still run and catch any report that is lost. Each person can turn it off under
  **Settings → Your account**, where the switch says why when it cannot run and links to the guide.
  Each rule says "Syncs instantly" or "Syncs every 5 minutes" and why. Installation Health tells
  administrators when the public address uses plain HTTP or a provider cannot reach it. Migration
  31 adds the tables; see [Instant Sync](docs/instant-sync.md) for proxy and tunnel examples.
```

- [ ] **Step 7: Run the tests and the site's checks to verify they pass**

Run: `.venv/bin/pytest tests/test_instant_sync_docs.py tests/test_ubiquitous_language.py tests/test_troubleshooting_anchors.py -q`
Expected: PASS

Run the site's gate, which renders `docs/instant-sync.md` at `/docs/instant-sync`:

```sh
cd site
pnpm install --frozen-lockfile
pnpm run check
pnpm test
pnpm run build
pnpm run audit:dist
pnpm exec playwright install chromium
pnpm run e2e
cd ..
```

Expected: PASS. The e2e suite runs its `/docs/<slug>` tests for the new page: an `h1`, more than
three contents entries that land on headings, a Copy button per code block, 4.5:1 code contrast,
no sideways scroll at 320px, and only `/docs/` links to rendered pages.

- [ ] **Step 8: Commit**

```bash
git add docs/instant-sync.md docs/adr/0036-instant-sync-through-provider-notices.md \
  docs/adr/0029-isolate-users-in-one-sqlite-database.md \
  docs/superpowers/specs/2026-10-09-multi-user-design.md CONTEXT.md AGENTS.md \
  docs/deployment.md docs/self-hosting.md docs/sync-model.md docs/troubleshooting.md \
  docs/architecture.md docs/data-ownership.md README.md CHANGELOG.md \
  site/src/docs/pages.ts site/src/i18n/en.ts tests/test_instant_sync_docs.py \
  tests/test_ubiquitous_language.py
git commit -m "Document Instant Sync, its proxy setup, and the decision behind it

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 21: Final gate and manual verification against real providers

**Files:**
- Modify: `docs/instant-sync.md` (measured provider calls per run, in **Cost per run**)

**Interfaces:**
- Consumes: everything in Tasks 1-20.
- Produces: a release-ready branch; measured provider-call numbers in the guide.

- [ ] **Step 1: Run the complete backend gate**

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: every command passes, and coverage stays at or above 80%.

- [ ] **Step 2: Run the complete frontend and site gates**

```sh
cd web
pnpm audit --audit-level=high
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ../site
pnpm audit --audit-level=high
pnpm run check
pnpm test
pnpm run build
pnpm run audit:dist
pnpm run e2e
cd ..
git status --short src/calendar_sync/interfaces/api/static
```

Expected: every command passes. `git status` lists the bundle only when the rebuild changed nothing
but the embedded commit; such a rebuild is not committed, so restore it with
`git checkout -- src/calendar_sync/interfaces/api/static`. Any other difference means a web change
was committed without its build: rebuild and commit it.

- [ ] **Step 3: Scan for secrets and build the image**

```sh
gitleaks git .
docker compose build
```

Expected: gitleaks reports no leaks; the image builds.

- [ ] **Step 4: Manual verification with real accounts (NOT run in CI)**

This checklist needs real Google and Microsoft test accounts and a public tunnel, so CI never runs
it. Run it once before release. Use throwaway test calendars only, never personal data, and never
commit anything it prints.

Prerequisites: a Google test account and a personal Microsoft test account, each with two empty
test calendars; the Google Cloud OAuth client and the Entra application from the self-hosting
guide, configured in `.env`; `cloudflared` and `socat` installed on the host.

1. Start a breakable relay and a quick tunnel in two terminals:

   ```sh
   socat TCP-LISTEN:8081,fork,reuseaddr TCP:127.0.0.1:8000
   cloudflared tunnel --url http://127.0.0.1:8081
   ```

   Note the `https://<random>.trycloudflare.com` address cloudflared prints. Stopping `socat`
   later breaks delivery while the tunnel keeps its address.
2. Set `CALENDAR_SYNC_PUBLIC_URL=https://<random>.trycloudflare.com` in `.env`, then:

   ```sh
   docker compose up -d --build
   curl --fail http://localhost:8000/health
   ```

3. From a network outside the host (a phone hotspot is enough), send the Google-shaped `curl`
   probe from `docs/instant-sync.md`, section "Providers cannot reach the installation", to the
   tunnel address. Expected: `202 Accepted`.
4. Open `http://localhost:8000`, connect the Google and Microsoft accounts, and create, preview,
   and start three rules: Google calendar A → Google calendar B, Outlook calendar X → Outlook
   calendar Y (same mailbox), and Outlook calendar X → Google calendar B.
5. Within five minutes, confirm the registrations:

   ```sh
   docker compose exec -T app python - <<'PY'
   import sqlite3
   db = sqlite3.connect("file:/data/calendar-sync.db?mode=ro", uri=True)
   for state, confirmed, expires in db.execute(
       "SELECT state, confirmed_at IS NOT NULL, expires_at FROM watch_registrations ORDER BY created_at"
   ):
       print(state, "confirmed" if confirmed else "unconfirmed", expires)
   print("covered calendars:", db.execute("SELECT count(*) FROM watch_coverage").fetchone()[0])
   PY
   ```

   Expected: one `live confirmed` row for Google calendar A and one for the Microsoft account, and
   two covered calendars (A and X). Each rule page says **Syncs instantly**.
6. Confirm no log names a registration:

   ```sh
   docker compose exec -T app python - <<'PY' > /tmp/registration-ids.txt
   import sqlite3
   db = sqlite3.connect("file:/data/calendar-sync.db?mode=ro", uri=True)
   for (registration,) in db.execute("SELECT id FROM watch_registrations"):
       print(registration)
   PY
   docker compose logs app | grep -F -f /tmp/registration-ids.txt
   rm /tmp/registration-ids.txt
   ```

   Expected: `grep` prints nothing. If Uvicorn's access lines show the notice path with its
   identifier, report it against Task 17 before release.
7. Edit an event in Google calendar A and note the time. Expected: **Activity** lists the change,
   and the `run started` line for the rule (`docker compose logs --since 2m app | grep "run started"`)
   is less than 30 seconds after Google's notice, so within about 40 seconds of saving, well
   before the next five-minute boundary. Repeat with Outlook calendar X; both rules from X run.
8. Turn **Instant sync** off under **Settings → Your account**. Within five minutes the query from
   item 5 prints no rows, each rule says **Syncs every 5 minutes** with "You turned instant sync
   off in Settings.", and a new edit in A appears only at the next scheduled sync. Turn it on again
   and wait until the rows return confirmed.
9. Break delivery: stop `socat` (leave cloudflared running), turn **Instant sync** off, wait until
   the rows are gone, and turn it on again. Expected within five minutes for Microsoft (Graph
   refuses the address) and two more for Google (no first report): the switch is disabled with
   "Your calendar providers cannot reach this Calendar Ghost, so your rules sync on their
   schedule." and **Learn why** opens
   `https://calendarghost.com/docs/instant-sync#providers-cannot-reach-the-installation`. **People**
   → **Installation health** shows "Needs you" with one hint per provider, whose **How to fix**
   opens `https://calendarghost.com/docs/troubleshooting#calendar-providers-cannot-reach-the-installation`.
   An edit in A still appears within five minutes.
10. Restore: start `socat` again. Edit an event in A: Google's report arrives, and after a reload
    the switch works again. Within the next upkeep retries (minutes, growing after each failure),
    the Outlook rules say **Syncs instantly** again.
11. Plain HTTP: set `CALENDAR_SYNC_PUBLIC_URL=http://calendar.example.test` and run
    `docker compose up -d`. Expected: the switch is disabled with the public HTTPS address reason
    and its link to `#no-public-https-address`, and **Installation health** shows the plain HTTP
    hint linking to `#instant-sync-needs-an-https-public-address`. Set it to
    `http://192.168.1.50:8000`: the switch stays disabled, and the hint is gone. Set the tunnel
    address back and restart.
12. Measure provider calls per instant run. For each rule, edit one event in its Source Calendar,
    wait for **Activity**, then read `provider_calls=` on the rule's line from
    `docker compose logs --since 3m app | grep "run finished"`. Repeat three times and keep the
    middle value. Measure an Outlook wake with nothing to do by editing an event in a calendar of
    the same mailbox that no rule reads. Cross-check the day's totals:

    ```sh
    docker compose exec -T app python - <<'PY'
    import sqlite3
    db = sqlite3.connect("file:/data/calendar-sync.db?mode=ro", uri=True)
    for provider, calls in db.execute(
        "SELECT provider, calls FROM provider_calls WHERE day = date('now') ORDER BY provider"
    ):
        print(provider, calls)
    PY
    ```

13. Clean up: stop cloudflared and socat, unset `CALENDAR_SYNC_PUBLIC_URL`, run
    `docker compose up -d`, and remove the test rules, deleting their projections.

- [ ] **Step 5: Write the measured numbers into the guide**

In `docs/instant-sync.md`, at the end of **Cost per run** (after the measuring steps), add the
table with the middle values from item 12, the date measured, and the release:

```markdown
Measured on 2026-10-DD with Calendar Ghost 0.3.0, middle of three runs, each after one edited
event, and for Outlook also after an edit in a calendar no rule reads:

| Rule | One edited event | A wake with nothing to change |
| --- | --- | --- |
| Google → Google | N calls | not applicable: Google watches one calendar |
| Outlook → Outlook, same mailbox | N calls | N calls |
| Outlook → Google | N calls | N calls |
```

Replace `DD`, the release, and each `N` with what you measured; the commit must contain no letter
`N` standing for a number.

Run: `.venv/bin/pytest tests/test_instant_sync_docs.py tests/test_ubiquitous_language.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/instant-sync.md
git commit -m "Record how many provider calls an instant run makes on each provider

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

