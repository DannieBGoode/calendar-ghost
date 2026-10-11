# Architecture

Calendar Ghost is a modular monolith: one repository, one deployable application, one SQLite database, and one Docker Compose service. Conceptual bounded contexts remain explicit without becoming network services.

## Edition boundary

The Community Edition runs as one installation: one SQLite database, one scheduler, and one
application process, serving one or more Users. It has no hosted account, billing path, or remote
control plane. This keeps the self-hosted data boundary visible in the code and makes backups and
ownership understandable to the operator.

Every record belongs to one User, and no User sees another's ([ADR 0029](adr/0029-isolate-users-in-one-sqlite-database.md),
[ADR 0030](adr/0030-users-administrators-and-registration.md)). Users sign in with email and
password; an Installation Administrator is a User with a role, not a separate account. The
Registration Policy starts at Only Me, so a household installation that one person runs behaves as
before. The future hosted service runs this same codebase (ADR 0023). The Operator Overview shows
administrators every User's health without their calendars. Plans behind the Plans setting, and
billing behind Commercial Mode, both off by default (ADR 0028), follow in the phases of
`docs/superpowers/specs/2026-10-09-multi-user-design.md`.

## Bounded contexts

- **Calendar Integration** owns provider authorization, discovery, change cursors, rate limits, provider errors, and translation. Each provider is one adapter package behind the same ports.
- **Synchronization** owns directional rules, transformation, mappings, source authority, loop prevention, idempotent actions, and rule lifecycle.
- **Reconciliation** derives expected projections and proves provider state, independently of normal incremental synchronization.
- **Identity and Access** owns Users, their roles and sessions, the Registration Policy, Invitations and Password Reset Links, connected-account authorization, and credential lifecycle.
- **Operations** owns scheduling, retries, incidents, notifications, audit evidence, and health.

## Dependency direction

```text
React UI / FastAPI / Scheduler
              |
              v
      Application use cases
              |
              v
   Synchronization domain
              ^
              |
 Google, Microsoft, and SQLite
 adapters implement application ports
```

The domain imports only Python's standard library and provider-neutral domain modules. Application services depend on protocols. The composition root constructs concrete adapters explicitly.
`lint-imports` enforces this direction through the contracts in `pyproject.toml`.

Web API routes only parse input, call one use case or port, and map its result or application
error to HTTP. `bootstrap/container.py` composes in two steps: `build_adapters` makes the SQLite and
provider adapters from Settings, and `compose` wires the use cases from them into the `Container`
the routes call. The `Container` holds installation-wide services (identity, administration,
Installation Health, the Operator Overview, the scheduler) and `for_user`, which composes one User's use cases from
adapters made for that User: their unit of work, account store, Activity queries, incidents, and
Incident Notifications. A route resolves the signed-in User from the session and calls only that
User's use cases, so no use case can reach another User's records. The scheduler lists due rules
through the installation-wide `InstallationUnitOfWork` and runs each with its owner's use cases,
taking turns between Users. The `Container` holds no concrete adapter, unit of work, or rule
locks. Tests and the development preview substitute adapters before `compose`, or use cases after
it. `Adapters` holds ports, or functions that make a User's port, rather than concrete classes, so a
substitute needs only to honor the port. Use cases that need the installation master key are absent
without it, and one route guard answers 503 for them.

Time and identifiers come through ports too. `build_adapters` makes one `SystemClock`, one
`UuidIdGenerator`, and one `UuidRunIdGenerator`, and passes them to each adapter and use case that
reads the time or makes an identifier: sessions, OAuth states, Connected Accounts, incidents, rule
removal, providers' Retry-After dates, and Sync Run identifiers. Only the schema migration
bookkeeping in `initialize_database` reads the system clock directly. Tests pass a fixed clock to
check expiry and retry waits without sleeping.

`interfaces/api/app.py` is only the factory: it installs the container, registers the routers, and
serves the compiled Web UI after checking each requested file against the resolved static root. The
routes live in one `APIRouter` module per resource under `interfaces/api/routes/` (session, setup,
account, users, accounts, rules, activity, incidents, storage, integrations, health). Each module
declares a small protocol for the container services it reads, since interfaces cannot import
bootstrap, and the factory's typed assignment lets mypy prove the container satisfies every one.
`interfaces/api/dependencies.py` holds the guards: `current_user` resolves the signed-in User and,
until the upgraded first User adds an email, refuses everything but the add-email step;
`user_services` gives a route that User's use cases; `administrator` refuses anyone but an
Installation Administrator before anything is looked up; `status_reader` and `installation_reader`
also accept an Integration Token with the right scope. `tests/adapters/test_api_authorization.py`
fails if any `/api/` route other than the documented public ones lacks a guard, sends a valid token
to every other route to prove each one refuses it, walks every route that names a record with a
second User's session to prove each answers 404, and refuses a User who does not administer on
every administrator route.

Provider authorization is split the same way. Each provider's package holds its OAuth flow,
credentials, and calendar discovery, configured by an `OAuthClientConfig` value that bootstrap
builds from Settings, such as `infrastructure/google/oauth.py` and
`infrastructure/microsoft/oauth.py`. The mechanics every flow shares live in
`infrastructure/oauth.py`: single-use states bound to the session of the User who began the flow,
PKCE, one token refresh per account at a time, and connecting only for a User still active.
Connected Accounts and their credentials, encrypted by the `CredentialCipher` in
`infrastructure/security.py`, live in `infrastructure/persistence/accounts.py`, which implements the
`ConnectedAccountRepository` port. Deleting an account and its rules is the `DeleteConnectedAccount`
use case, which deletes both in one unit of work; the adapters only delete their own records.

Rule health follows the same direction. `application/health.py` holds the `RuleHealthPolicy`: which
failures require intervention and degrade the rule, the three-failure Provider Incident threshold,
and every incident key and summary. `RuleHealth` applies it through the `RuleHealthRecords`,
`IncidentRepository`, and `IncidentNotifications` ports and the `Clock`. Each use case reports to it
through a protocol of its own: the scheduler through `RunHealth` after every Sync Run, Reconcile Now
through `FullPassRecords` after its full pass, Rule Removal through `RemovalIncidents` when lost
authorization stops it, and a preview through `RecoveryIncidents` when it finds an account's
authorization lost. A provider failure names the Connected Account whose request failed. An
authorization failure marks that account's Lapsed Authorization through `LapsedAuthorizations` in
`application/lapsed_authorization.py`, which opens one Incident for the account rather than one per
rule; Reauthorization and a passing access check clear it and resume the rules it alone stopped
(ADR 0027). Scheduled runs and Rule Removal share one retry helper in
`application/retry.py`, which retries only temporary and rate-limited failures.

Installation Status follows the same direction ([ADR 0024](adr/0024-integration-tokens-installation-status-and-mcp.md)).
`application/status.py` decides the one verdict the Overview, `GET /api/v1/status`, and MCP share:
`assess_installation` is a pure function of the rule summaries, the operations overview, open
incidents, and the scheduler's `SchedulerProgress`, read through the `SchedulerHeartbeat` port that
`SyncScheduler` implements in memory. Each User's Installation Status covers their rules and the
installation problems that affect them. `application/installation_health.py` sums every User's
verdict into Installation Health for Installation Administrators, beside installation incidents,
such as a scheduler that stalled; `SchedulerWatch` reports that one to the installation's own
channels.

The Operator Overview, `application/operator_overview.py`, is the other reader across Users.
`UserStatuses` reads a page of Users' rules, last runs, previews, accounts, open incidents, and open
blocks through `InstallationUnitOfWork.status_records`, in the same few queries however many rules
they have, and computes each User's verdict with the same `assess_installation`. The records hold no
calendar or account name; each calendar is labelled "Calendar 1", "Calendar 2" in the order the
User's rules were created (`sync_rules.creation_order`), so `status_payload.py` renders the result
with the one privacy contract the status API already uses. Installation Health counts the verdicts
`UserStatuses` computes, so People and its summary agree. `OperatorOverview` adds each User's
Resource Use from `InstallationUnitOfWork.resource_use`: counts of rules, Connected Accounts, and
Activity entries, and the provider calls each Sync Run, reconciliation, and Rule Removal adds to its
User's `provider_calls` row for that provider and UTC day. The scheduler pass discards days older
than 30. `OperatorOverview.of` answers an administrator about one User, and `own` answers a User
about themself; both come from one function, so they cannot differ. `interfaces/access.py` holds the one access decision both transports use: a present
`Authorization` header decides alone and must carry the scope the route needs, and only the status
API also accepts a session. `interfaces/api/status_payload.py` translates a verdict into the
response both transports return. `interfaces/mcp/` serves the MCP SDK's stateless streamable HTTP
app as one exact `/mcp` route behind a gate that refuses a request before the SDK sees it, and
creates a fresh SDK server for each application lifespan. Only `interfaces/mcp` may import the
`mcp` package. Integration Tokens are stored by `infrastructure/integration_tokens.py` behind the
`IntegrationTokens` port, as SHA-256 hashes, each belonging to one User.

Read-only views follow the same direction. Activity and the dashboard ask the query protocols in
`application/activity.py`, which a SQLite adapter answers; the Web API maps their provider-neutral
results to HTTP payloads and never opens the database itself. The rule that sorts Audit Entries
into changed, unchanged, skipped, and blocked lives there once, and the adapter's SQL mirrors it
under a test that proves they agree.

## Calendar provider roles

`application/ports.py` splits the calendar provider port by role, and each use case receives only
the roles it calls:

| Role | Operations | Received by |
| --- | --- | --- |
| `CalendarReader` | change feeds, event and occurrence lookups, managed-event listing | Rule Preview, Full Reconciliation |
| `ProjectionDeleter` | delete an owned projection | Rule Removal |
| `ProjectionWriter` | create, update, and delete owned projections | Sync Run |
| `OccurrenceWriter` | write and cancel single occurrences of an owned series | Sync Run |

`CalendarProvider` combines every role for the Sync Run. Rule Preview is side-effect-free by type:
it holds a `CalendarReader`, which declares no write.

Each provider's adapter implements every role it can honor. `RoutingCalendarProvider` and
`RoutingAccountCalendars` in `infrastructure/providers/routing.py` implement the same ports and
send each request to the adapter of the Provider Kind its Connected Account belongs to, so a rule's
calendars may belong to different providers (ADR 0022). The use cases receive the routers and
never name a provider.

The test fake, the router, and every adapter pass the Calendar Provider contract in
`tests/contracts/calendar_provider.py` before being composed: the fake and the router in
`tests/adapters/test_calendar_provider_contract.py`, and each adapter, through a fake of its
provider's API, in its own test package: `tests/adapters/google/` against a fake Google Calendar API,
and `tests/adapters/microsoft/` against a fake Microsoft Graph (`tests/fake_microsoft_graph_api.py`).
Mechanics every provider shares are tested once, in `tests/adapters/shared/`, and
`tests/adapters/test_mixed_providers.py` runs rules between a Google and an Outlook calendar, in
both directions at once, to prove neither copies the other's projections. The contract states,
through the ports alone, the ownership, idempotency, and listing guarantees the use cases rely on.

## Provider descriptors

Each provider's package describes itself to bootstrap with one `ProviderDescriptor`
(`application/provider_descriptors.py`), and nothing outside that package knows anything else about
the provider ([ADR 0022](adr/0022-route-calendar-requests-by-provider.md), amended):

- its `ProviderGuide`: the Provider Kind, the slug its connection flow lives under
  (`/api/v1/oauth/{slug}/`), its display and calendar names, the troubleshooting section for each
  Cause it can raise, and any Installation Hint only it explains;
- whether the installation configured it, its OAuth flow (`AccountAuthorization`) and redirect URI;
- its calendar roles: `AccountCalendars` and `CalendarProvider`.

`calendar_providers` in `bootstrap/container.py` composes the descriptors into a
`ProviderDirectory`. Routing builds its adapter map from it, Installation Hints read the guides, and
the Web API lists the connectable providers at `GET /api/v1/providers` and runs their flows. Without
the installation master key, a descriptor offers only its guide.

Only a Provider Kind names a provider in the domain, application, and interfaces, and no module
outside a provider's package names a Provider Kind member: `tests/test_provider_neutrality.py`
fails otherwise. Its one exception is `interfaces/api/routes/compatibility.py`, which keeps
`GET /api/v1/google/configuration` for earlier clients. Import-linter (`pyproject.toml`) enforces
the rest, with no `ignore_imports` for any provider:

- the domain and application import no provider package, SDK, or HTTP client;
- the neutral infrastructure (`oauth`, `providers`, `provider_calls`, `retry_after`, persistence)
  imports neither `infrastructure.google` nor `infrastructure.microsoft`;
- `infrastructure.google` and `infrastructure.microsoft` never import each other;
- the Google client libraries stay in `infrastructure.google`, and `httpx`, which reaches Microsoft
  Graph, stays in `infrastructure.microsoft`.

`tests/adapters/microsoft/` also proves no Microsoft answer leaks: Graph's `message` and the
identity platform's `error_description` are never kept, logged, or returned. The privacy sentinels
in `tests/adapters/test_operator_overview_api.py` include a person with Microsoft accounts, whose
emails, calendars, events, and Microsoft's words never reach People, incidents, notifications, or
logs.

To add a provider:

1. Write an ADR on how its API meets the Calendar Provider contract, as ADR 0032 does for Graph.
2. Add its Provider Kind to `application/providers.py` and its settings to `bootstrap/config.py`.
3. Create `infrastructure/<provider>/` with its guide, adapter, translation, OAuth flow on the
   shared mechanics in `infrastructure/oauth.py`, Cause mapping, and `descriptor.py`.
4. Add one line to `calendar_providers` in `bootstrap/container.py`, and import-linter contracts
   that keep its SDK in its package and it independent of the other providers.
5. Give it a test package under `tests/adapters/<provider>/` that runs the Calendar Provider
   contract through a fake of its API, a table-driven Cause test, and a privacy leak test.
6. Write its sections of `docs/troubleshooting.md` under the anchors its guide names
   (`tests/test_troubleshooting_anchors.py` checks them), its setup in `docs/self-hosting.md`, and
   its Web UI catalog entries in `common.json`: `provider`, `providerName`, `providerAccount`,
   `providerApi`, `providerConsole`, and `providerStatus`.

## Logging

`service_container` configures the `calendar_sync` logger from `CALENDAR_SYNC_LOG_LEVEL` before
it composes anything; Uvicorn's loggers are left as Uvicorn configures them. The Sync Run,
reconciliation, and Rule Removal log their lifecycle with standard `logging`, naming rules and runs
by identifier only. Their closing lines include how the run's provider calls went, read from the
`ProviderCallStats` port: `measure()` returns a `ProviderCallTally` that the provider adds each
call to while the run is in progress. Each adapter sends every request through one helper that
times it, and `infrastructure/provider_calls.py` keeps each measured run's tally in a
context variable, so runs on different worker threads never share one; its `record_token_refresh()`
counts a renewed access token toward the current run. Use cases default to
`UntalliedProviderCalls`, so test fakes need nothing.

## Transaction boundary

A calendar provider and SQLite cannot share an atomic transaction. A Sync Run therefore uses stable operation
keys, provider ownership metadata, and retry-safe writes. Acknowledged event operations commit
individually to keep SQLite write locks away from later network calls; source and destination
incremental cursors commit last, after both batches complete. If the process stops after a provider
write but before persistence commits, retrying the same operation key recovers the same managed
projection rather than creating a duplicate.

## Persistence

Every SQLite connection in the application opens through
`infrastructure/persistence/connections.py`: foreign keys are enforced, rows are read by column
name, a writer waits up to five seconds for another's lock, and `transaction()` commits, rolls back,
and closes in one block. A test fails if any other module under `src/calendar_sync` calls
`sqlite3.connect`, so a setting added there applies to every adapter.

Every table holding a User's records carries `user_id`. A child refers to its parent by identifier
and User together, such as a mapping's `(rule_id, user_id)` to its rule's `(id, user_id)`, so SQLite
refuses a record whose User differs from its parent's, and a rule's accounts must be its own User's.
Each repository of a User's unit of work adds that User to every statement, and an upsert that meets
another User's record is refused rather than skipped. Deleting a User deletes everything they own
through these references. `tests/adapters/test_user_isolation_schema.py` checks the schema, and that
only the scheduler, the Operator Overview, the migrations, and the composition root reach
`InstallationUnitOfWork`.

The in-memory unit of work that application tests use and the SQLite one both pass the persistence
contract in `tests/contracts/persistence.py`. It states, through the ports alone, the behavior use
cases rely on: writes are discarded until committed, rule removal takes a rule's records with it, a
record without its rule or series is refused, identities stay unique, listings come back in a fixed
order, and a second User with the same calendar and event identifiers reads, changes, and deletes
nothing of the first User's. The in-memory store keeps each User's records in a partition of their
own. It does not make the two interchangeable in every respect; when a use case starts
relying on another storage behavior, add it to the contract.

## Public compatibility surfaces

Database migrations, environment configuration, HTTP API payloads, provider ownership metadata, and persisted domain states are compatibility surfaces. The `GET /api/v1/status` and `GET /api/v1/installation/health` payloads, the Integration Token format and scopes, and the MCP tool names and results are read by monitors, dashboards, and agents outside this repository, so a change to them must stay backward compatible or be announced as a breaking change. Releases must migrate them rather than asking operators to delete SQLite state.
