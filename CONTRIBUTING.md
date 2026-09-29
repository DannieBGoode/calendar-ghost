# Contributing

Thank you for helping make self-hosted calendar synchronization safer.

## Before changing code

1. Read [CONTEXT.md](CONTEXT.md), [docs/domain-model.md](docs/domain-model.md), and the relevant ADRs.
2. Use the canonical domain terms in code, API payloads, UI copy, documentation, and tests.
3. Keep Google, FastAPI, SQLite, and React dependencies outside the domain.
4. Never add real credentials, account IDs, event details, or personal calendar fixtures.

## Development checks

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest
cd web && npm run typecheck && npm run lint && npm run test && npm run build
docker compose build
```

Domain tests must remain fast and independent of HTTP, SQLite, and Google. Application tests use in-memory ports. Adapter tests cover translation or persistence contracts separately.

## Pull requests

- Keep changes focused and describe observable behavior.
- Add or update tests for domain decisions and recovery paths.
- Add an ADR only for a hard-to-reverse, non-obvious trade-off.
- Update documentation when terminology, configuration, or operator behavior changes.
- Include screenshots for visible UI changes and verify keyboard and mobile behavior.

By contributing, you agree that your contribution is licensed under the MIT License.
