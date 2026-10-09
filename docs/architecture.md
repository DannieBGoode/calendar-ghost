# Architecture

Calendar Ghost is a modular monolith: one repository, one deployable application, one SQLite database, and one Docker Compose service. Conceptual bounded contexts remain explicit without becoming network services.

## Edition boundary

The Community Edition is intentionally a single-installation runtime: one Installation
Administrator, one SQLite database, one scheduler, and one application process. It has no tenant
identifier, hosted account, billing path, or remote control plane. This keeps the self-hosted data
boundary visible in the code and makes backups and ownership understandable to the operator.

The future hosted service runs this same codebase (ADR 0023). Multi-user support, billing, and an
operator overview will be added here, with plan limits behind the Plans setting and billing behind
Commercial Mode, both off by default (ADR 0028). ADR 0029 decides its persistence and per-User isolation and ADR 0030 its identity and
registration; build it in the phases of `docs/superpowers/specs/2026-10-09-multi-user-design.md`,
not piecemeal.

## Bounded contexts

- **Calendar Integration** owns provider authorization, discovery, change cursors, rate limits, provider errors, and translation. Google is the initial adapter.
- **Synchronization** owns directional rules, transformation, mappings, source authority, loop prevention, idempotent actions, and rule lifecycle.
- **Reconciliation** derives expected projections and proves provider state, independently of normal incremental synchronization.
- **Identity and Access** owns the installation administrator, sessions, connected-account authorization, and credential lifecycle.
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
 Google and SQLite adapters
 implement application ports
```

The domain imports only Python's standard library and provider-neutral domain modules. Application services depend on protocols. The composition root constructs concrete adapters explicitly.
`lint-imports` enforces this direction through the contracts in `pyproject.toml`.

Web API routes only parse input, call one use case or port, and map its result or application
error to HTTP. `bootstrap/container.py` composes in two steps: `build_adapters` makes the SQLite and
Google adapters from Settings, and `compose` wires the use cases from them into the `Container`
the routes call. The `Container` holds use cases, query ports, and the few configuration values a
route returns; never a concrete adapter, the unit of work, or the rule locks. Tests and the
development preview substitute adapters before `compose`, or use cases after it. `Adapters` holds
ports rather than concrete classes, so a substitute needs only to honor the port. Use cases that
need the installation master key are absent without it, and one route guard answers 503 for them.

Time and identifiers come through ports too. `build_adapters` makes one `SystemClock`, one
`UuidIdGenerator`, and one `UuidRunIdGenerator`, and passes them to each adapter and use case that
reads the time or makes an identifier: sessions, OAuth states, Connected Accounts, incidents, rule
removal, Google's Retry-After dates, and Sync Run identifiers. Only the schema migration
bookkeeping in `initialize_database` reads the system clock directly. Tests pass a fixed clock to
check expiry and retry waits without sleeping.

`interfaces/api/app.py` is only the factory: it installs the container, registers the routers, and
serves the compiled Web UI after checking each requested file against the resolved static root. The
routes live in one `APIRouter` module per resource under `interfaces/api/routes/` (session, setup,
accounts, rules, activity, incidents, storage, integrations, health). Each module declares a small protocol for the
container services it reads, since interfaces cannot import bootstrap, and the factory's typed
assignment lets mypy prove the container satisfies every one. `interfaces/api/dependencies.py` holds
the shared `require_admin` session guard and `require_status_reader`, which also accepts an
Integration Token; `tests/adapters/test_api_authorization.py` fails if any `/api/` route other than
setup, the session routes, the OAuth callback, and `GET /api/v1/status` lacks `require_admin`, and
sends a valid token to every other route to prove each one refuses it.

Google authorization is split the same way. `infrastructure/google/oauth.py` holds the
state-protected OAuth flow, Google credentials, and Google calendar discovery, configured by an
`OAuthClientConfig` value that bootstrap builds from Settings. Connected Accounts and their
credentials, encrypted by the `CredentialCipher` in
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
`SyncScheduler` implements in memory. `interfaces/access.py` holds the one access decision both
transports use: a present `Authorization` header decides alone, and only the status API also
accepts the administrator session. `interfaces/api/status_payload.py` translates a verdict into the
response both transports return. `interfaces/mcp/` serves the MCP SDK's stateless streamable HTTP
app as one exact `/mcp` route behind a gate that refuses a request before the SDK sees it, and
creates a fresh SDK server for each application lifespan. Only `interfaces/mcp` may import the
`mcp` package. Integration Tokens are stored by `infrastructure/integration_tokens.py` behind the
`IntegrationTokens` port, as SHA-256 hashes.

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

The test fake, the router, and every new adapter pass the Calendar Provider contract in
`tests/contracts/calendar_provider.py` before being composed. The contract states, through the
ports alone, the ownership, idempotency, and listing guarantees the use cases rely on. The Google
adapter predates the contract and does not run the suite; it is covered by
`tests/adapters/test_google_provider.py` instead.

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

Google and SQLite cannot share an atomic transaction. A Sync Run therefore uses stable operation
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

The in-memory unit of work that application tests use and the SQLite one both pass the persistence
contract in `tests/contracts/persistence.py`. It states, through the ports alone, the behavior use
cases rely on: writes are discarded until committed, rule removal takes a rule's records with it, a
record without its rule or series is refused, identities stay unique, and listings come back in a
fixed order. It does not make the two interchangeable in every respect; when a use case starts
relying on another storage behavior, add it to the contract.

## Public compatibility surfaces

Database migrations, environment configuration, HTTP API payloads, provider ownership metadata, and persisted domain states are compatibility surfaces. The `GET /api/v1/status` payload, the Integration Token format, and the MCP tool names and results are read by monitors, dashboards, and agents outside this repository, so a change to them must stay backward compatible or be announced as a breaking change. Releases must migrate them rather than asking operators to delete SQLite state.
