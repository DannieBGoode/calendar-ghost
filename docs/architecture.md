# Architecture

Google Calendar Sync is a modular monolith: one repository, one deployable application, one SQLite database, and one Docker Compose service. Conceptual bounded contexts remain explicit without becoming network services.

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

Read-only views follow the same direction. Activity and the dashboard ask the query protocols in
`application/activity.py`, which a SQLite adapter answers; the Web API maps their provider-neutral
results to HTTP payloads and never opens the database itself. The rule that sorts Audit Entries
into changed, unchanged, skipped, and blocked lives there once, and the adapter's SQL mirrors it
under a test that proves they agree.

## Transaction boundary

Google and SQLite cannot share an atomic transaction. A Sync Run therefore uses stable operation
keys, provider ownership metadata, and retry-safe writes. Acknowledged event operations commit
individually to keep SQLite write locks away from later network calls; source and destination
incremental cursors commit last, after both batches complete. If the process stops after a provider
write but before persistence commits, retrying the same operation key recovers the same managed
projection rather than creating a duplicate.

## Public compatibility surfaces

Database migrations, environment configuration, HTTP API payloads, provider ownership metadata, and persisted domain states are compatibility surfaces. Releases must migrate them rather than asking operators to delete SQLite state.
