# Architecture

Calendar Ghost is a modular monolith: one repository, one deployable application, one SQLite database, and one Docker Compose service. Conceptual bounded contexts remain explicit without becoming network services.

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
development preview substitute adapters before `compose`, or use cases after it. Use cases that
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
accounts, rules, activity, incidents, health). Each module declares a small protocol for the
container services it reads, since interfaces cannot import bootstrap, and the factory's typed
assignment lets mypy prove the container satisfies every one. `interfaces/api/dependencies.py` holds
the shared `require_admin` session guard; `tests/adapters/test_api_authorization.py` fails if any
`/api/` route other than setup, the session routes, and the OAuth callback lacks it.

Google authorization is split the same way. `infrastructure/google/oauth.py` holds only the
state-protected OAuth flow, configured by an `OAuthClientConfig` value that bootstrap builds from
Settings. Connected Accounts and their credentials, encrypted by the `CredentialCipher` in
`infrastructure/security.py`, live in `infrastructure/persistence/accounts.py`, which implements the
`ConnectedAccountRepository` port. Deleting an account and its rules is the `DeleteConnectedAccount`
use case, which deletes both in one unit of work; the adapters only delete their own records.

Rule health follows the same direction. `application/health.py` holds the `RuleHealthPolicy`: which
failures require intervention and degrade the rule, the three-failure Provider Incident threshold,
and every incident key and summary. `RuleHealth` applies it through the `RuleHealthRecords`,
`IncidentRepository`, and `IncidentNotifications` ports and the `Clock`. Each use case reports to it
through a protocol of its own: the scheduler through `RunHealth` after every Sync Run, Reconcile Now
through `FullPassRecords` after its full pass, Rule Removal through `RemovalIncidents` when lost
authorization stops it, and the preview that recovers a degraded rule through `RecoveryIncidents`
when it finds an account's authorization lost. A provider failure names the Connected Account whose
request failed, so an authorization Incident names the account to reauthorize. Scheduled runs and Rule Removal share one retry helper in
`application/retry.py`, which retries only temporary and rate-limited failures.

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
it holds a `CalendarReader`, which declares no write. The Google adapter implements every role.

## Logging

`service_container` configures the `calendar_sync` logger from `CALENDAR_SYNC_LOG_LEVEL` before
it composes anything; Uvicorn's loggers are left as Uvicorn configures them. The Sync Run,
reconciliation, and Rule Removal log their lifecycle with standard `logging`, naming rules and runs
by identifier only. Their closing lines include how the run's provider calls went, read from the
`ProviderCallStats` port: `measure()` returns a `ProviderCallTally` that the provider adds each
call to while the run is in progress. The Google adapter sends every request through one helper that
times it, and `infrastructure/google/instrumentation.py` keeps each measured run's tally in a
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

## Public compatibility surfaces

Database migrations, environment configuration, HTTP API payloads, provider ownership metadata, and persisted domain states are compatibility surfaces. Releases must migrate them rather than asking operators to delete SQLite state.
