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
- Pausing preserves mappings and projections. Resuming a paused or degraded rule begins with
  validation and reconciliation, except that a rule stopped only by Lapsed Authorization resumes on
  its own once its accounts are authorized again (ADR 0027), and a Plan Hold releases without a
  preview when its Allowance permits (ADR 0039). Production settlement runs before due-rule listing,
  with visible grace, keep choices, and held-rule recovery in the same release.
- Event content never reaches logs, incidents, or notifications. SQLite keeps only what Activity
  needs: each Audit Entry's source event title, time, recurrence, and cancellation (ADR 0014), and
  Source Observations and Source Change values (ADR 0017). Titles are plain text; descriptions,
  locations, guests, recurrence rules, and conferencing data are persisted only sealed with the
  History Cipher, and Source Change values are kept for 90 days.
- A Sync Run writes to the destination only when the projection derived from the source differs
  from the destination's content. A new source revision alone is never a reason to write.

The Community Edition is licensed under the GNU Affero General Public License, version 3 or later.
The future hosted service runs this same codebase with no closed components (ADR 0023). Multi-user
support, billing, and the Operator Overview belong in this repository. ADRs 0029 and 0030 settle
their persistence, isolation, and identity, and
`docs/superpowers/specs/2026-10-09-multi-user-design.md` orders the work. Users have shipped: every
record belongs to one User, use cases receive a unit of work scoped to that User, and only the
scheduler and the Instant Sync loops beside it, migrations, and the Operator Overview receive the
installation-wide `InstallationUnitOfWork`. The Watch Notice inbox is the one public-route writer
that crosses Users, through its own narrow port (ADR 0029, amended, and ADR 0036). A new owned
table carries `user_id` and refers to its parent by identifier and User together;
`tests/adapters/test_user_isolation_schema.py` fails otherwise.
Plan limits apply only when an administrator turns Plans on, and billing only when Commercial Mode
is also on; both are off by default, and with Plans off every user has every feature (ADR 0028).
Installation Administrators are never limited. A limit check reads the User's Allowance inside the
transaction it guards and fails closed. Your plan (`GET /api/v1/account/plan`, `ShowOwnPlan`) and
the administrator's Plans routes also fail the request when Plans cannot be read, rather than show
limits nobody read. Plan settlement changes nobody when its Allowance read fails; other reads of
Plans fail open, so a fault in Plans never stops synchronization, sign-in, or the rules API
(ADR 0038, ADR 0039).
Preserve the self-hosting promise that there is no mandatory Calendar Ghost account, telemetry, or
hosted coordinator.

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
- `src/calendar_sync/application/` coordinates use cases through protocols. It cannot import
  concrete Google, Microsoft, SQLite, scheduler, notification, or Web API adapters.
- The application has one package per bounded context (ADR 0032): `sync`, `identity`, and
  `operations`, with `shared` below them. Shared ports live in each context's `ports.py` or
  focused `*_ports.py` siblings; shared errors live in `errors.py`. Synchronization retains its
  single unit of work in `sync/ports.py`, with provider, account, record, health, plan, and run
  ports in focused siblings. A use-case module may declare ports and errors beside its use cases,
  and other modules import them from there. Contexts depend only downward, `operations` →
  `identity` → `sync` → `shared`, and `lint-imports` fails otherwise, or when an application
  module belongs to no context. Put a new use case in the context whose language it speaks; a
  glossary concept that several contexts name belongs in `domain/`.
- `src/calendar_sync/infrastructure/` owns Google and Microsoft Graph payload translation, OAuth,
  SQLite, scheduling, notifications, and cryptography. Each provider's package (`google/`,
  `microsoft/`) exposes calendar and sign-in descriptors to bootstrap; nothing outside it branches
  on its Provider Kind, and the two never import each other (`docs/architecture.md`, Provider descriptors).
- `src/calendar_sync/interfaces/` owns HTTP schemas, routes, sessions, and serving the compiled UI.
- `src/calendar_sync/bootstrap/` is the only dependency-composition boundary.
- `web/` contains the React source. Reuse the existing shadcn-style components and design tokens
  before adding UI primitives.
- Raw provider dictionaries must be translated at their adapter's boundary. Do not leak Google SDK
  types or `httpx` types into the application or domain.
- Prefer explicit constructor injection and small protocols. Do not introduce a dependency-injection
  framework, repository framework, event bus, or microservice boundary.
- `lint-imports` enforces these boundaries through the contracts in `pyproject.toml`. Its
  only `ignore_imports` entry lets the FastAPI factory in `interfaces/api/app.py` build the
  container, because it is the process entry point. Never add one to make a change pass.
- Ruff bounds function complexity and argument count. Split code instead of suppressing the
  rule: `tests/test_architecture.py` fails on a `noqa` for `C901`, `PLR0912`, `PLR0913`, or
  `PLR0915` in `src/`, and on an application dataclass with behavior whose constructor takes more
  than `max-args` fields. Its list of such dataclasses is debt that may only shrink.
- ESLint applies the same kind of bounds to `web/src`, and no frontend code is exempt. Split a
  component, hook, or module that reaches a bound into cohesive files (for example
  `features/rule-details.tsx` and its section files); never add an `eslint-disable` for these rules.
- In `web/src`, features compose components, components render `lib`, and `lib` imports neither;
  `components/ui` imports only other UI primitives. ESLint's `no-restricted-imports` enforces this
  for alias and relative imports.
- Call the API through `api` in `web/src/lib/api.ts`. Each method names its route and HTTP method,
  which select the generated path, query, body, and response types; never pass a type by hand.
- React Doctor (`pnpm run doctor` in `web/`) fails on any warning. Fix the code; change
  `web/doctor.config.ts` only for a documented false positive.

## Landing page

`site/` is the public landing page for `calendarghost.com`, an Astro site deployed by Cloudflare
Workers Builds. It is not part of the application: it has its own `package.json`, is excluded from
the Docker build context, and has its own `Site` workflow.

- It follows the Landing Page Register Rule in `DESIGN.md`: the ghost may play, explanations stay
  literal, and every decorative motion stops under reduced motion.
- All copy lives in `site/src/i18n/en.ts`; components contain no literal copy. Copy must stay true
  to `CONTEXT.md`; `tests/test_ubiquitous_language.py` searches it.
- The page contacts no host but its own: no third-party trackers, CDNs, remote fonts, or live
  GitHub requests. `pnpm run audit:dist` and the Playwright tests enforce this.
- Visits are counted with Umami Cloud, cookieless, only on `calendarghost.com`, and only when the
  Cloudflare build sets `PUBLIC_UMAMI_WEBSITE_ID`. The site's Worker (`site/worker/index.ts`)
  serves the tracker and forwards its events from the site's own origin
  (`site/src/lib/analytics.ts`). Click events go only on buttons and new-tab links: on a same-tab
  link, Umami's tracker holds the navigation until its event is sent. This covers the landing page
  only: the application, its Web UI, and self-hosted installations send no analytics or telemetry.
- Self-host commands must match the README's quick start; a unit test compares them.
- `/docs/<slug>` pages render repository documents at build time (`site/src/docs/pages.ts`), with
  Astro's own Markdown processor. Their headings keep GitHub's anchors; links between rendered
  documents stay on the site, and every other repository link goes to GitHub
  (`site/src/docs/repo-links.ts`). The site's links to the self-hosting guide point at these pages.
- The site is one landing page at `/` (`site/src/pages/index.astro`, one component per section in
  `site/src/sections/`), the `/docs/<slug>` pages, and the 404 page. Change the page in place; there
  are no alternative designs or iteration routes. Earlier designs are in git history.
- To add a language: add its code to `astro.config.mjs` `locales`, and add a module under
  `site/src/i18n/` that `satisfies Messages` and is registered in `LOCALES`. Then add its pages
  under `site/src/pages/<locale>/`.

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
- Open SQLite connections only through `infrastructure/persistence/connections.py`.

## Security and data handling

- Never commit `.env`, OAuth credentials, master keys, access tokens, personal calendar exports, or
  real provider responses. Fixtures must be synthetic.
- A secret-scan failure blocks merging; allowlist in `.gitleaks.toml` only synthetic values.
- Never print secrets or decrypted credentials. Keep notification payloads free of event content.
- Validate paths against resolved trusted roots before serving files.
- Keep every API route behind the signed-in User's session (`current_user` in
  `interfaces/api/dependencies.py`), and Installation Administrator routes behind `administrator`,
  which refuses other Users with 403 before anything is looked up. A route that names another
  User's record answers 404, never 403, so its existence is not revealed (ADR 0029); the Operator
  Overview's route for one User, `/api/v1/users/{user_id}/overview`, also answers 404 to anyone
  who does not administer, as for an unknown User. Only setup,
  sign-in, the session status and sign-out, the bounded provider sign-in routes
  (`GET /api/v1/sign-in/providers`, `POST /api/v1/sign-in/{slug}/start`,
  `GET /api/v1/sign-in/{slug}/callback`, `GET /api/v1/sign-in/pending`,
  `POST /api/v1/sign-in/confirm`), the bounded public verified registration routes
  (`/api/v1/registrations/request`, `/api/v1/registrations/check`, `/api/v1/registrations`),
  the bounded public Password Reset Link request
  (`/api/v1/password-resets/request`), the token-protected Invitation and Password Reset Link
  routes (`/api/v1/invitations/check`, `/api/v1/invitations/accept`,
  `/api/v1/password-resets/check`, `/api/v1/password-resets`), the Watch Notice route providers
  call (`/api/v1/watch-notices/{provider_slug}/{registration_id}`, ADR 0036), which answers alike
  for known and unknown registrations and logs no identifier, token, or body, static application
  files, and `/health` are intentionally public; `/health` is the only unauthenticated operational status
  route. The OAuth callback is session-and-state protected: it reads the session itself
  (`session_user`) to redirect rather than answer 401, and completes a flow only for the signed-in
  User who began it. `/api/v1/status`, `/api/v1/installation/health`, and
  `/mcp` are the only routes that accept an Integration Token, and `/mcp` accepts nothing else
  (ADR 0024). `tests/adapters/test_api_authorization.py` lists them; extend it with every route.
  Email-change verification requires the owning signed-in User's session, even to check a proof;
  an Integration Token never authorizes those routes. Provider linking resolves the owning session
  at both start and callback. Provider sign-in mutations require the configured Origin;
  Integration Tokens authorize none.
- Google writes use `sendUpdates=none`. Outlook writes are appointments with no attendees that ask
  for no responses, and never call `/cancel`, `/forward`, or a response action. A change that could
  email attendees or mutate source events is release-blocking.
- Preserve least-privilege OAuth scopes and encrypted credential storage.

## Development

Requirements are Python 3.12, Node.js 22 or later with pnpm 12 (`corepack enable` provides it; run pnpm from inside `web/` or `site/`, where Corepack reads its version), and Docker with Compose for container validation.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
(cd web && pnpm install --frozen-lockfile)
```

Run the integrated FastAPI service on port 8000:

```sh
.venv/bin/uvicorn calendar_sync.interfaces.api.app:create_app --factory --reload
```

For frontend development, run Vite on port 5173; it proxies `/api` and `/health` to FastAPI:

```sh
cd web && pnpm run dev
```

The production frontend is committed under `src/calendar_sync/interfaces/api/static/`. After any
change under `web/`, run the frontend build and include the regenerated static assets in the same
commit.

User-visible Web UI text lives in `web/src/i18n/locales/en/` and renders through `t()`; dates and
numbers go through `i18n.format`. `web/src/i18n/catalog.test.ts` fails on an English key no source
file names: delete a key with the code that used it, and give a key built from a template, such as
`people.overview.next.${step}.self`, its known values in that test's `TEMPLATE_VALUES`. Server text the UI shows carries a stable code: raise API errors
through `interfaces/api/problems.py` and give Incidents a message (ADR 0026). Under test, `t()`
throws on a parameter it was not given, and the Vitest setup (`web/src/test-setup.ts`) fails any
test whose page shows an unfilled `{placeholder}` or a raw catalog key; in production the
translator leaves a missing parameter out rather than show its braces, so a message built from
server data checks `i18n.fills(key, params)` before `t()` and otherwise shows the server's detail.
Never use em dashes.

## Testing

Tests use pytest with synthetic fixtures and fake providers. Test files mirror the domain,
application, and adapter boundaries under `tests/`. Add a regression test for every bug fix and
exercise both the allowed and blocked path when changing ownership, deletion, or recovery logic.
When the persistence ports or either unit of work change, extend `tests/contracts/persistence.py`
so the in-memory and SQLite units keep the same behavior.

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
cd web
pnpm audit --audit-level=high
pnpm run api:check
pnpm run typecheck
pnpm run lint
pnpm run doctor
pnpm run knip
pnpm run test
pnpm run build
cd ..
```

CI's `frontend` job runs the same commands. `lint` fails on any ESLint warning (`--max-warnings 0`):
fix the code, never disable a rule to pass. `knip` fails on an unused file, export, or dependency in
`web/src`: delete it. Add an exception to `web/knip.jsonc` only with a comment saying why.

The frontend's API types are generated from the backend's OpenAPI schema (ADR 0025). After changing
a response or request model in `interfaces/api/schemas/` or `interfaces/api/identity_schemas.py`, run
`.venv/bin/python scripts/export_openapi.py` and `cd web && pnpm run api:types`, and commit both
generated files. Never edit `web/openapi.json` or `web/src/lib/api-schema.ts` by hand.

Scan the repository for secrets with gitleaks (8.30.1, the version CI pins):

```sh
gitleaks git .
```

CI's `secrets` job runs the same scan on a pull request's commits and on each push to `main`.

For release-facing changes, also build the image for the supported architectures through CI or
`docker compose build`. Tests must not require a personal Google or Microsoft account.

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
src/calendar_sync/infrastructure/  Google, Microsoft, SQLite, security, scheduling, notifications
src/calendar_sync/interfaces/      FastAPI routes and compiled Web UI
src/calendar_sync/bootstrap/       Dependency composition
web/                               React, TypeScript, Vite, Tailwind, shadcn-style source
tests/                             Domain, application, and adapter tests
docs/                              Architecture, operations, domain references, and ADRs
```

When a directory later needs materially different instructions, add a nested `AGENTS.md` scoped to
that directory. Do not duplicate root guidance merely to restate it.

Offline restoration is a separate stopped-service terminal composition in `bootstrap/restore.py`.
Its Operations `RestoreStore` port narrowly crosses Users for inspection and conservative
preparation; it does not receive `InstallationUnitOfWork` or compose the API or runtime workers.
Keep diagnostics fixed and secret-free, require hidden confirmed password input, and preserve
this isolation when changing the operator command. See `docs/development.md`.
