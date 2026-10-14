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
  `CALENDAR_SYNC_PUBLIC_URL` is an `https` address at the root of its host and the Installation
  Master Key exists. It is on for every enabled rule of a User whose Sync Cadence allows it, unless
  the User turns it off (`users.instant_sync`, on by default).
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
- **Watch upkeep runs beside the scheduler**, every five minutes in one worker thread, one User
  after another, with a budget of 200 provider calls a cycle. The Users a cycle did not reach go
  first in the next, then Users with nothing planned yet, then the rest in order of their earliest
  due work, so no User starves. `unauthorized` lapses the account through ADR 0027; any other
  failure retries with backoff capped at one day, and never lapses an account.
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
