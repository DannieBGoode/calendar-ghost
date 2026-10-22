# Isolate Users in one shared SQLite database

Extends [ADR 0004](0004-use-sqlite-for-initial-persistence.md) and answers the persistence and
isolation decisions [ADR 0023](0023-hosted-service-runs-the-open-codebase.md) requires before
multi-user work begins.

## Context

One installation will serve many Users, on a household computer and on the Hosted Service. A
record read or changed under the wrong User is a privacy defect between people, so isolation needs
more than a filter each query has to remember. The workload is small, short writes after slow
provider calls; a household must keep one container and one file.

## Decision

- All Users share one SQLite database. Every table holding a User's data carries that User's
  identifier, not only the tables at the root of each aggregate.
- Child tables reference their parent by the parent's identifier and User together, such as a
  mapping's rule and User, so the database refuses a record whose User differs from its parent's.
- Use cases receive a unit of work scoped to one User, and each of its repositories adds that User to
  every statement. Only the scheduler, the Operator Overview, and migrations receive a separate
  installation-wide unit of work, so reaching across Users is visible in a type.
- The persistence contract tests prove, for every repository, that one User can neither read,
  change, nor delete another's records.
- Tests guard the boundary from several sides: a schema test requires every owned table to carry
  its User and a composite reference to its parent; a check allows only the scheduler, the Operator
  Overview, and migrations to receive the installation-wide unit of work; every Web API route
  answers 404, never 403, for another User's resource, so an identifier's existence is not
  revealed; and seeded markers prove that no calendar name, email, or event title reaches the
  Operator Overview, Installation Health, administrator notifications, or logs.
- SQLite runs in WAL mode so readers do not wait for the scheduler's writes, and the scheduler runs
  a bounded number of rules at once, ordered fairly between Users. The Hosted Service backs the
  database up continuously.

## Consequences

The installation still runs as one process. A move to PostgreSQL is a new adapter behind the same
ports and contracts, warranted when a second process is needed for availability or capacity, when
write-lock waits appear, or when one machine's disk becomes an unacceptable business risk.
Deleting or exporting one User is a use case over the shared database, not a file operation.

## Alternatives considered

- **One SQLite file per User beside an installation database.** Physical isolation and simple
  per-User deletion, but the scheduler and Operator Overview would open every file, migrations would
  run once per User, and moving to PostgreSQL later would be a redesign rather than an adapter.
- **PostgreSQL now.** Greater write concurrency and row-level security, but it adds a database
  server to every household installation for a workload SQLite carries.

## Amendment: the Watch Notice inbox writes across Users (2026-10-14)

A provider sends a Watch Notice to a public route that has no session and names only a Watch
Registration ([ADR 0036](0036-instant-sync-through-provider-notices.md)). Finding the rules it
concerns means reading a registration before its User is known, so the `WatchNoticeInbox` port
(`application/operations/ports.py`), which `SqliteWatchNoticeInbox`
(`infrastructure/persistence/watch_inbox.py`) implements, is the one public-route writer that
crosses Users. It is narrow: it does not receive the installation-wide unit of work, but opens one
short write transaction of its own per request; it writes only Watch Registrations, Instant Sync
Requests, and Delivery Evidence, and besides those reads only Connected Accounts, Calendar Watches
and their coverage, and Directional Sync Rules; it acts only after the notice's token hash and
provider handle match in constant time; and it raises requests only for the enabled rules of the
registration's own User whose Source Calendar the watch covers. Instant Sync's watch upkeep and
dispatch run beside the scheduler and, like it, receive the installation-wide unit of work, so the
isolation test's list of its receivers names `application/operations/instant_sync.py` beside the
scheduled pass, the Operator Overview, and migrations.

## Amendment: stopped-service restoration (2026-10-22)

The offline `OfflineRestore` Operations service uses a dedicated `RestoreStore` port to inspect
and conservatively prepare a restored database across Users. It receives no installation-wide
unit of work and exposes no general repository access. This terminal-only composition runs with
all application and backup processes stopped, requires explicit acknowledgement, and starts no
API, provider, mail, scheduler, or Instant Sync worker. Preparation invalidates restored authority
and disconnects accounts while preserving mappings and rules; it enables only the selected
existing Installation Administrator with a fresh hidden-input password. Inspection discloses only
safe counts. This narrow operator port does not expand any online cross-User boundary.
