# Repository instructions for coding agents

This file is the canonical repository-wide instruction source for coding agents. Tool-specific
instruction files should point here instead of duplicating these rules. Keep all guidance specific
to Calendar Ghost; do not vendor general-purpose agent skills or personal agent configuration.

## Start here

Read documentation in this order before changing code:

1. `README.md` for the product, supported behavior, setup, and repository map.
2. `CONTEXT.md` for canonical domain terms and settled product decisions.
3. `docs/architecture.md` for dependency direction and runtime boundaries.
4. `docs/domain-model.md` and `docs/sync-model.md` before changing synchronization behavior.
5. The relevant record in `docs/adr/` before changing an architectural decision.
6. `docs/development.md` for the local workflow and `docs/deployment.md` for runtime constraints.

If documentation and implementation disagree, do not silently choose one. Verify the intended
behavior, fix the mismatch in the same change, and add an ADR when the decision is hard to reverse.

## Product invariants

- A Directional Sync Rule has exactly one Source Calendar and one Destination Calendar. They may
  belong to different Connected Accounts.
- The Source Calendar is authoritative. Direct edits or deletions of a Managed Projection are
  repaired from the source on the next synchronization or reconciliation run.
- Transformation and all-day eligibility are selected per rule, never per event.
- New rules default to Busy-Only Projection. Details Projection never copies attendees, organizer
  identity, conferencing data, attachments, or invitations.
- Only Native Events may become sources. Managed Projection metadata prevents synchronization
  loops.
- Update and deletion require a valid Event Mapping plus exact rule, source, destination, and
  Managed Origin ownership. Ambiguity is a Conflict, not permission to write.
- Recurring series project as series. Occurrence writes require a Series Mapping plus parent-series
  and Managed Origin ownership, and a destination occurrence is cancelled only when the source
  proves it cancelled or absent from an existing series. See ADR 0011.
- Preview is side-effect-free and required before enabling a new or materially changed rule.
- Pausing preserves mappings and projections. Reauthorization and resume begin with validation and
  reconciliation.
- Event content never reaches logs, incidents, or notifications. SQLite keeps only what Activity
  needs: each Audit Entry's source event title, time, recurrence, and cancellation (ADR 0014), and
  Source Observations and Source Change values (ADR 0017). Titles are plain text; descriptions,
  locations, guests, recurrence rules, and conferencing data are persisted only sealed with the
  History Cipher, and Source Change values are kept for 90 days.
- A Sync Run writes to the destination only when the projection derived from the source differs
  from the destination's content. A new source revision alone is never a reason to write.

The Community Edition is intentionally single-installation and licensed under the GNU Affero
General Public License, version 3 or later. Keep tenant routing, billing, hosted accounts, remote
control planes, and SaaS-only feature flags out of this runtime; the future hosted service is a
separate composition boundary. Preserve the self-hosting promise that there is no mandatory
Calendar Ghost account, telemetry, or hosted coordinator.

Use the exact terms defined in `CONTEXT.md`. In particular, do not use “sync pair,” “event copy,” or
“conflict” when Directional Sync Rule, Event Projection, or Drift is the intended concept.
`tests/test_ubiquitous_language.py` fails when code or documentation uses an avoided term that
always names the wrong concept; extend its list when the glossary gains another.

## Architecture boundaries

The application is a modular monolith using ports and adapters:

```text
web/ and interfaces/  ->  application/  ->  domain/
                               |
                               v
                         declared ports
                               ^
                               |
                    infrastructure adapters
```

- `src/calendar_sync/domain/` is provider- and framework-independent. It cannot import application,
  infrastructure, interfaces, or bootstrap modules.
- `src/calendar_sync/application/` coordinates use cases through protocols in `application/ports.py`.
  It cannot import concrete Google, SQLite, scheduler, notification, or Web API adapters.
- `src/calendar_sync/infrastructure/` owns Google payload translation, OAuth, SQLite, scheduling,
  notifications, and cryptography.
- `src/calendar_sync/interfaces/` owns HTTP schemas, routes, sessions, and serving the compiled UI.
- `src/calendar_sync/bootstrap/` is the only dependency-composition boundary.
- `web/` contains the React source. Reuse the existing shadcn-style components and design tokens
  before adding UI primitives.
- Raw provider dictionaries must be translated at the Google adapter boundary. Do not leak Google
  SDK types into the application or domain.
- Prefer explicit constructor injection and small protocols. Do not introduce a dependency-injection
  framework, repository framework, event bus, or microservice boundary.
- `lint-imports` enforces these boundaries through the contracts in `pyproject.toml`. Its
  only `ignore_imports` entry lets the FastAPI factory in `interfaces/api/app.py` build the
  container, because it is the process entry point. Never add one to make a change pass.
- Ruff bounds function complexity and argument count. Existing `# noqa: C901`, `PLR0912`,
  `PLR0913`, and `PLR0915` markers are debt to shrink, not a pattern to copy: split new code
  instead of suppressing the rule.
- ESLint applies the same kind of bounds to `web/src`. `web/eslint-suppressions.json` counts the
  violations that predate them; it is debt to shrink, never a file to grow. Prune it with
  `npx eslint . --prune-suppressions` after splitting a component. In `web/src`, features compose
  components, components render `lib`, and `lib` imports neither.
- React Doctor (`npm --prefix web run doctor`) fails on any warning. Fix the code; change
  `web/doctor.config.ts` only for a documented false positive.

## Synchronization and persistence safety

- Provider writes must use stable Operation Keys and private Managed Origin metadata.
- Advance source and destination cursors only after every change in the batch succeeds.
- Keep SQLite write transactions short; never hold a database write lock across provider network
  calls.
- Serialize execution of the same rule so scheduled and user-requested runs cannot race.
- Treat provider not-found responses conservatively. A source that cannot be verified during
  destination repair must not authorize deletion.
- Retry temporary and rate-limit failures with backoff. Authorization or ownership failures require
  intervention and must not be retried as ordinary transient errors.
- The shipped SQLite deployment supports one application process per database. Do not add multiple
  workers without a cross-process rule lock and a reviewed persistence design.
- Schema changes require an explicit migration strategy, SQLite-backed tests, and documentation of
  upgrade and rollback behavior.

## Security and data handling

- Never commit `.env`, OAuth credentials, master keys, access tokens, personal calendar exports, or
  real provider responses. Fixtures must be synthetic.
- Never print secrets or decrypted credentials. Keep notification payloads free of event content.
- Validate paths against resolved trusted roots before serving files.
- Keep administrator-only API routes behind the session dependency. Only setup, login, the
  state-protected OAuth callback, static application files, and `/health` are intentionally public;
  `/health` is the only unauthenticated operational status route.
- Google writes use `sendUpdates=none`. A change that could email attendees or mutate source events
  is release-blocking.
- Preserve least-privilege OAuth scopes and encrypted credential storage.

## Development

Requirements are Python 3.12, Node.js 22 or later, and Docker with Compose for container validation.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci --prefix web
```

Run the integrated FastAPI service on port 8000:

```sh
.venv/bin/uvicorn calendar_sync.interfaces.api.app:create_app --factory --reload
```

For frontend development, run Vite on port 5173; it proxies `/api` and `/health` to FastAPI:

```sh
npm --prefix web run dev
```

The production frontend is committed under `src/calendar_sync/interfaces/api/static/`. After any
change under `web/`, run the frontend build and include the regenerated static assets in the same
commit.

## Testing

Tests use pytest with synthetic fixtures and fake providers. Test files mirror the domain,
application, and adapter boundaries under `tests/`. Add a regression test for every bug fix and
exercise both the allowed and blocked path when changing ownership, deletion, or recovery logic.

Run the complete backend quality gate:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Run the complete frontend quality gate:

```sh
npm --prefix web run api:check
npm --prefix web run typecheck
npm --prefix web run lint
npm --prefix web run doctor
npm --prefix web run test
npm --prefix web run build
```

The frontend's API types are generated from the backend's OpenAPI schema (ADR 0023). After changing
a response or request model in `interfaces/api/schemas.py`, run
`.venv/bin/python scripts/export_openapi.py` and `npm --prefix web run api:types`, and commit both
generated files. Never edit `web/openapi.json` or `web/src/lib/api-schema.ts` by hand.

For release-facing changes, also build the image for the supported architectures through CI or
`docker compose build`. Tests must not require a personal Google account.

## Test Coverage

Minimum: 80%
Target: 80%

Coverage is a floor, not a substitute for behavioral assertions. Prioritize domain decisions,
ownership failures, retry classification, persistence boundaries, API authorization, and user
recovery flows over trivial line execution.

## Change expectations

- Keep changes focused and preserve unrelated work in the tree.
- Update `CONTEXT.md` when domain language or a settled product decision changes.
- Update relevant reference and operational docs when behavior, configuration, or failure recovery
  changes.
- Add or update an ADR for a hard-to-reverse architectural choice.
- Keep provider behavior in adapters and business decisions in the domain.
- Do not weaken the 80% coverage gate, branch protection, secret handling, or ownership checks to
  make a change pass.
- Before handing off, run every applicable quality gate and report any check that could not run.

## Repository map

```text
src/calendar_sync/domain/          Entities, value objects, policies, and decisions
src/calendar_sync/application/     Use cases and boundary protocols
src/calendar_sync/infrastructure/  Google, SQLite, security, scheduling, notifications
src/calendar_sync/interfaces/      FastAPI routes and compiled Web UI
src/calendar_sync/bootstrap/       Dependency composition
web/                               React, TypeScript, Vite, Tailwind, shadcn-style source
tests/                             Domain, application, and adapter tests
docs/                              Architecture, operations, domain references, and ADRs
```

When a directory later needs materially different instructions, add a nested `AGENTS.md` scoped to
that directory. Do not duplicate root guidance merely to restate it.
