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

Open `http://127.0.0.1:8001/activity` and sign in as `preview@preview.com` with `preview`. The preview
seeds this short password itself; real installations keep their 12-character minimum. In `api-disabled` and
`access-revoked`, `robin@example.test` signs in with the same password as an ordinary User. The preview is for
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
| `api-disabled` | Sam and Robin both lost Google because the Calendar API is off; People suggests it and Robin is told an administrator must fix it |
| `access-revoked` | Sam and Robin both lost Google a week after connecting; each reauthorizes, and People suggests the OAuth app is in Testing mode |
The preview uses the generated local portraits in `web/public/avatars/`; production accounts use
the profile photo returned by Google when one is available. Its seed data models one fictional Sam
across three context-specific identities (`sam@personal.example`, `sam@family.example`, and
`sam@work.example`), keeping the screenshots recognizable while making each calendar's story clear.

## Landing page

The landing page in `site/` has its own toolchain:

```sh
npm ci --prefix site
npm --prefix site run dev          # http://localhost:4321
npm --prefix site run check        # astro check
npm --prefix site test             # unit tests
npm --prefix site run build && npm --prefix site run audit:dist
npm --prefix site run e2e          # Playwright; run `npx playwright install chromium` once
npm --prefix site run og-image     # regenerate public/og.png from a running `npm --prefix site run preview`
```

Cloudflare Workers Builds deploys it from `main`; other branches get preview URLs. The site also
reads files outside `site/`: it renders `docs/self-hosting.md` and `docs/troubleshooting.md` as
pages under `/docs`, imports screenshots from `docs/assets/`, and checks its commands against
`README.md`. In the Workers Builds settings, set the build watch paths to `site/**`, `docs/**`, and
`README.md`, so a documentation change also redeploys the site (the `Site` workflow uses the same
paths).

## Adding a language

1. Copy `web/src/i18n/locales/en/` to `web/src/i18n/locales/<tag>/` and translate the values.
   Keep every key, every `{placeholder}`, the literal "Calendar Ghost", and rich-text tags
   unchanged.
2. Give every plural message the forms `Intl.PluralRules("<tag>").resolvedOptions().pluralCategories`
   lists for that language. English only needs `one` and `other`; other languages may need more.
3. Register the language in `web/src/i18n/locales/index.ts`:
   `{ tag, load: () => import("./<tag>").then((module) => module.default) }`.
4. Run the frontend gate (`npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test`).
5. Open the app with `?locale=pseudo` in dev to check layouts take the longer pseudo-text, then
   open it with the new language and read every screen.

Translator notes: the glossary in `CONTEXT.md` lists the product's terms (Directional Sync Rule,
Source Calendar, Event Projection, Drift, Conflict, Incident, Activity). Translate each one
consistently and never mix two translations of the same term in one language. Keep sentences short
and plain, the same register as the English copy.

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
([ADR 0025](adr/0025-generate-web-api-types-from-openapi.md)):

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
