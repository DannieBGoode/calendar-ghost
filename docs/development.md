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
`/activity`, and `/rules`. Keep them synthetic when refreshing the media; never use a personal
calendar export or a real provider response in repository assets.
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
cd web && npm run typecheck && npm run lint && npm run test && npm run build
```

Fixtures in `tests/fixtures` are synthetic. Never copy provider responses from a personal account into the repository.

## Architecture rules

`lint-imports` checks the import boundaries below through the contracts in `pyproject.toml`, and
`tests/test_ubiquitous_language.py` checks that code and documentation avoid the terms `CONTEXT.md`
rules out.

- Domain code cannot import application, infrastructure, interfaces, or bootstrap modules.
- Application code cannot import concrete adapters.
- Provider dictionaries are translated at the Google adapter boundary.
- Use constructor injection and small protocols; do not introduce a dependency-injection framework.
