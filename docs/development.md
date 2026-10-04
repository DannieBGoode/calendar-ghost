# Development

## Prerequisites

- Python 3.12
- Node.js 22 or later
- Docker with Compose for container validation

## Setup

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd web && npm ci
```

Run FastAPI on port 8000 and Vite on port 5173. Vite proxies `/api` and `/health` to FastAPI.

## Corresponding source link

The Web UI's **Source** link is injected at build time. A local Vite build uses the current Git
revision; CI and Docker builds should set `CALENDAR_GHOST_SOURCE_URL` to the immutable commit or
release tag URL for the source being built:

```sh
CALENDAR_GHOST_SOURCE_URL=https://github.com/DannieBGoode/calendar-ghost/tree/<commit-or-tag> \
  npm --prefix web run build
```

Docker Compose passes the same variable as a build argument. Downstream forks can point the link at
their own corresponding source without changing the application code.

## Development preview

To see the Web UI with realistic data without a Google account, run:

```sh
.venv/bin/python scripts/dev_preview.py
```

Open `http://127.0.0.1:8001/activity` and sign in with `preview-password`. The preview is for
development only:

- It writes only to `dev-preview.db` in the repository root, which it marks as its own. It refuses
  to reset or seed any database it did not create, including the one `CALENDAR_SYNC_DATABASE_PATH`
  names, and recreates its own database with fresh synthetic data on every start.
- It never reads `.env` or the environment for settings, so no OAuth credentials, master key,
  notifications, or scheduler are loaded.
- Google is replaced by a read-only fake that answers event lookups from synthetic data and refuses
  every write.
- It listens on `127.0.0.1` only, and `scripts/` is excluded from the Python package and the
  container image.

The README screenshots in `docs/assets/` are captured from this preview at `/overview`,
`/activity`, and `/rules`, at 1440 × 900 (the Overview at 1440 × 1240, so its recent changes show) in
both the light and the Twilight dark appearance
(`calendar-ghost-<view>-light.png` and `-dark.png`), with the preview started as
`--scenario healthy`. Keep them synthetic when refreshing the media; never use a personal calendar
export or a real provider response in repository assets.

`--scenario` starts the preview in each Overview health state:

| Scenario | Overview |
| --- | --- |
| `review` (default) | Blocked events, one persisting into an incident, while every rule keeps running |
| `stopped` | The Personal account's authorization expired, so both of its rules stopped |
| `waiting` | Google is limiting Family → Work's requests; the rule retries by itself |
| `several` | Stopped, waiting, and blocked at once, so the Overview lists every problem |
| `paused` | Every rule paused after earlier syncs |
| `setup` | A new installation with no Google account or rule |
| `healthy` | Every rule running and up to date |
The preview uses the generated local portraits in `web/public/avatars/`; production accounts use
the profile photo returned by Google when one is available. Its seed data models one fictional Sam
across three context-specific identities (`sam@personal.example`, `sam@family.example`, and
`sam@work.example`), keeping the screenshots recognizable while making each calendar's story clear.

## Quality checks

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov
cd web && npm audit --audit-level=high && npm run api:check && npm run typecheck && npm run lint && npm run doctor && npm run test && npm run build
```

After changing an API response or request model, regenerate the frontend types in the same commit
([ADR 0024](adr/0024-generate-web-api-types-from-openapi.md)):

```sh
.venv/bin/python scripts/export_openapi.py
npm --prefix web run api:types
```

Fixtures in `tests/fixtures` are synthetic. Never copy provider responses from a personal account into the repository.

A new calendar adapter adds a `CalendarProviderContract` subclass whose harness seeds Native Events
in that adapter's backend, next to `tests/adapters/test_calendar_provider_contract.py`.

## Architecture rules

`lint-imports` checks the import boundaries below through the contracts in `pyproject.toml`, and
`tests/test_ubiquitous_language.py` checks that code and documentation avoid the terms `CONTEXT.md`
rules out.

- Domain code cannot import application, infrastructure, interfaces, or bootstrap modules.
- Application code cannot import concrete adapters.
- Provider dictionaries are translated at the Google adapter boundary.
- Use constructor injection and small protocols; do not introduce a dependency-injection framework.
- In `web/src`, features compose components, components render `lib`, and `lib` imports neither;
  `components/ui` imports only other UI primitives. ESLint's `no-restricted-imports` enforces this
  for alias (`@/features/x`) and relative (`../features/x`) imports.
- ESLint bounds complexity, nesting, parameters, and length, as Ruff does for the backend, and no
  frontend code is exempt. Split a component, hook, or module that reaches a bound; do not disable
  the rule.
