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

## License and contributions

The Community Edition is licensed under the [GNU Affero General Public License, version 3 or later](LICENSE).
Contributions are welcome under that same license. Contributors retain copyright in their work and
must have the right to submit it under the Community Edition license.

The future hosted service may have separate commercial infrastructure and terms, but the project
will not quietly relicense community contributions into a proprietary product. Any future request
to reuse a contribution under separate commercial terms must be handled through a contributor
agreement that is published and reviewed before it is used for that purpose.

By contributing, you agree that your contribution may be distributed as part of the Community
Edition under the GNU Affero General Public License, version 3 or later.
