# Development

## Prerequisites

- Python 3.12
- Node.js 22 or later
- pnpm 12. With Node.js 22 to 24, `corepack enable` provides the version `web/package.json` and
  `site/package.json` name. Run pnpm from inside `web/` or `site/`, where Corepack reads it.
- Docker with Compose for container validation

## Setup

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd web && pnpm install --frozen-lockfile
```

Run FastAPI on port 8000 and Vite on port 5173. Vite proxies `/api` and `/health` to FastAPI.

```sh
FORWARDED_ALLOW_IPS= .venv/bin/uvicorn calendar_sync.interfaces.api.app:create_app --factory --reload --proxy-headers
```

An empty `FORWARDED_ALLOW_IPS` trusts no forwarded headers, including loopback peers. The packaged
entry point and container have this default explicitly; raw Uvicorn otherwise defaults to trusting
loopback. To test a real reverse proxy, set only its exact peer IPs or narrowly scoped networks;
see [proxy configuration](deployment.md#trusted-proxy-headers). Vite clients share its peer address
unless that proxy is explicitly trusted and overwrites forwarded headers.

Password recovery needs a Master Key, usable identity SMTP, and an HTTPS root
`CALENDAR_SYNC_PUBLIC_URL`; HTTP localhost or literal loopback is allowed for development. Use a
synthetic local SMTP relay and a disposable SQLite database. SMTP test acceptance is separate from
recovery availability. Tests in `tests/adapters/test_identity_proxy_limits.py` use the installed
Uvicorn middleware around the real app to exercise client limits and configured mail origin.
Reset passwords accept 12 to 1,024 characters; sign-in and all current-password confirmations
accept up to 1,024. Setup, Invitation, and ordinary new-password creation retain their 256-character
maximum. Verified email changes are available when identity email configuration is usable. Exercise them
with the synthetic SMTP capture and a disposable SQLite database; the request keeps the old
address until the signed-in owner completes the link with their current password. Open registration
also requires a matching successful administrator email test and explicit Open selection.
Verified-registration passwords accept 12 to 1,024 characters. Provider-only Users can set a first
password of 12 to 256 characters. The installed offline operator entry is documented below;
[the hosted backup drill](hosted-backups.md#reproduce-and-qualify) uses only synthetic data. See
[registration boundaries](architecture.md#verified-registration-boundary) and
[provider sign-in](architecture.md#provider-sign-in-boundary).

## Corresponding source link

The Web UI's **Source** link is injected at build time. A local Vite build uses the current Git
revision; CI and Docker builds should set `CALENDAR_GHOST_SOURCE_URL` to the immutable commit or
release tag URL for the source being built:

```sh
cd web && CALENDAR_GHOST_SOURCE_URL=https://github.com/DannieBGoode/calendar-ghost/tree/<commit-or-tag> \
  pnpm run build
```

Docker Compose passes the same variable as a build argument. Downstream forks can point the link at
their own corresponding source without changing the application code.

## Development preview

To see the Web UI with realistic data without a Google or Microsoft account, run:

```sh
.venv/bin/python scripts/dev_preview.py
```

Open `http://127.0.0.1:8001/activity` and sign in as `preview@preview.test` with `previewpreview`. In every scenario but `setup`,
`robin@example.test` signs in with the same password as an ordinary User, healthy unless the
scenario breaks their rule, so People is on. The preview is for
development only:

- It writes only to `dev-preview.db` in the repository root, which it marks as its own. It refuses
  to reset or seed any database it did not create, including the one `CALENDAR_SYNC_DATABASE_PATH`
  names, and recreates its own database with fresh synthetic data on every start.
- It never reads `.env` or the environment for settings, so no OAuth credentials, master key,
  notifications, or scheduler are loaded.
- Google and Microsoft are replaced by a read-only fake that answers event lookups from synthetic
  data and refuses every write. Both providers show as configured; Connect returns to Settings
  and connects nothing.
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
| `api-disabled` | Sam and Robin both lost Google because the Calendar API is off; People suggests it and Robin reads only that Google Calendar is temporarily unavailable |
| `access-revoked` | Sam and Robin both lost Google a week after connecting; each reauthorizes, and People suggests the OAuth app is in Testing mode |
| `outlook-client` | Sam and Robin both lost their Microsoft accounts because Microsoft no longer accepts the installation's client secret; People suggests it and Robin reads only that Outlook is temporarily unavailable |

The preview uses the generated local portraits in `web/public/avatars/`; production accounts use
the profile photo their provider returns when one is available. Its seed data models one fictional
Sam across three context-specific identities (`sam@personal.example` and `sam@family.example` are
Google accounts, and `sam@work.example` is a Microsoft account), keeping the screenshots
recognizable while making each calendar's story clear. Rules between Personal or Family and Work
cross providers. Robin's Personal account is Google's and their Work account is Microsoft's.

### Plan Hold preview

Layer an isolated synthetic fixture on the healthy scenario:

```sh
.venv/bin/python scripts/dev_preview.py --scenario healthy --plan-holds grace
```

`--plan-holds` accepts `grace`, `held`, `mixed`, or `reserved`. Sign in as ordinary User
`robin@example.test` with `previewpreview` to inspect Your plan, choose which rules sync,
and follow held-rule recovery links. Robin has a one-rule Plan and two eligible rules:

| Fixture | Plan state |
| --- | --- |
| `grace` | Two active rules, a future grace, and one predicted hold |
| `held` | Both rules held, with a successful history so Overview is paused |
| `mixed` | One active rule and one held rule at the limit |
| `reserved` | One active rule and one replacement draft, with a future reserved-place give-up |

Sam remains an exempt administrator. The all-held fixture represents the moment before a pass
releases one free place. The preview starts no scheduler, so that place stays open until an
explicit keep-choice save. It makes no provider writes or SMTP calls and reads no credentials or
environment settings for these fixtures. Omitting the flag keeps healthy preview data unchanged.
Inspect 1440px and 390px, light, Twilight, Midnight, `?locale=pseudo` through Vite, and 200% text.
Check keyboard access through the chooser, Preview, and recovery links. Keep scratch screenshots
under `.context/`. Selected synthetic review images are committed in the
[Plan Hold review gallery](assets/reviews/plan-hold/README.md) for PR review. Never use personal
calendar exports.

### Registration preview

Run the same isolated preview with a synthetic registration fixture:

```sh
.venv/bin/python scripts/dev_preview.py --scenario healthy --registration readyOpen
```

`--registration readyOpen` selects Open with matching synthetic readiness. `unavailable` keeps
Open selected without usable readiness, and `invitationOnly` exercises direct Invitations.
Omitting `--registration` keeps the normal preview unchanged. These fixtures use no SMTP,
environment settings, or public production fixture routes. Requests for synthetic addresses
exercise generic sent/resend states without sending mail or creating new proofs.

Open `http://127.0.0.1:8001/verify-email#preview-verification-proof` for a fixed 24-hour proof
bound to `new-user@example.test`. Completion with a synthetic password creates a real ordinary
User in the preview's SQLite database and signs in; the proof then becomes unusable. Restart
resets the fixture. `http://127.0.0.1:8001/invitation#preview-invitation` is a fixed seven-day
Invitation: verification under Open, direct joining under Invitation Only. Requests do not
consume the Invitation. The public proof is unusable under Invitation Only and temporarily
unavailable with the unavailable Open fixture.

The synthetic before/after registration screenshots in `docs/assets/reviews/open-registration/`
show sign-in, email-first joining, verification, and Administration at desktop and narrow widths.

## Landing page

The landing page in `site/` has its own toolchain:

```sh
cd site
pnpm install --frozen-lockfile
pnpm run dev          # http://localhost:4321
pnpm run check        # astro check
pnpm test             # unit tests
pnpm run build && pnpm run audit:dist
pnpm run e2e          # Playwright; run `pnpm exec playwright install chromium` once
pnpm run og-image     # regenerate public/og.png from a running `pnpm run preview`
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
4. Run the frontend gate (`cd web && pnpm run typecheck && pnpm run lint && pnpm run test`).
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
cd web && pnpm audit --audit-level=high && pnpm run api:check && pnpm run typecheck && pnpm run lint && pnpm run doctor && pnpm run knip && pnpm run test && pnpm run build
```

CI also scans each pull request's commits, and each push to `main`, for secrets with
[gitleaks](https://github.com/gitleaks/gitleaks) 8.30.1. Run `gitleaks git .` to scan the whole
history locally. A finding blocks merging; `.gitleaks.toml` may allowlist only synthetic values.

After changing an API response or request model, regenerate the frontend types in the same commit
([ADR 0025](adr/0025-generate-web-api-types-from-openapi.md)):

```sh
.venv/bin/python scripts/export_openapi.py
(cd web && pnpm run api:types)
```

Fixtures in `tests/fixtures` are synthetic. Never copy provider responses from a personal account into the repository; make them synthetic first ([Live provider checks](#live-provider-checks)).

A new calendar adapter adds a `CalendarProviderContract` subclass in its own test package, as
`tests/adapters/google/` and `tests/adapters/microsoft/` do. Its harness seeds and removes Native
Events in that adapter's backend, makes the backend refuse a calendar's cursors, ages a seeded
event if the backend re-reads events changed shortly before a cursor, and, if the backend cannot
expand a recurrence itself, tells it how the contract's series expands. The fake
of the provider's API must expand a daily series with a count, as the contract's series is.

## Live provider checks

Tests use fakes and never need a personal account. Some behavior only a real provider can show,
such as what Microsoft Graph accepts or how Google stores a rule, so `scripts/live_provider_checks.py`
runs ADR 0034's checks against real Google and Outlook calendars. Run it before a release that
touches a provider adapter, after a provider changes its API, and to verify a new kind of account,
such as a Microsoft work or school account. CI never runs it.

It needs:

- A local installation started with your `.env` (see [Setup](#setup)), signed in with an account
  you made for this, with exactly one Outlook and one Google account connected. Use test accounts
  if you can; it never reads or writes any other calendar of theirs.
- That account administers the installation, Plans are off, or its Plan limits nothing, as the No
  limits Plan does. One run starts more manual runs than the 12 an hour any other Plan allows, so
  the checks stop at once, before they make anything, when **Your plan** shows a limit for the
  account.
- Two empty Google calendars, `CG live source` and `CG live destination`, which you create: the
  installation's Google grant may not create calendars. `CALENDAR_GHOST_GOOGLE_SOURCE` and
  `CALENDAR_GHOST_GOOGLE_DESTINATION` name others.

```sh
set -a; . ./.env; set +a
CALENDAR_GHOST_URL=http://127.0.0.1:8000 CALENDAR_GHOST_EMAIL=you@example.test \
CALENDAR_GHOST_PASSWORD=... .venv/bin/python scripts/live_provider_checks.py
```

It creates its own Outlook calendars, named `CG live ...`, writes only to those and the two Google
calendars, and notifies nobody: invitations are imported with their answers rather than sent, and
every other write asks for no notification. Its events fall in the year after the run, so the
checks never age. Any error answer fails the check rather than reading as an empty calendar, and
it deletes everything it made, whatever the outcome, warning about anything it could not delete.
In about five minutes it prints one Markdown table:

- Graph v1.0: the behaviors ADR 0034 relies on, such as exceptions listed with their attendees,
  `If-Match` on PATCH, a repeated `transactionId`, and the extended-property filter.
- Outlook to Outlook, Google to Outlook, and Outlook to Google: every kind of event and series the
  checks found worth keeping, moves, cancellations, series changes, invitations and their answers,
  rule settings, edits made in the destination, an occurrence deleted in Outlook, blocked events
  with their reasons, an idle run that writes nothing, and Rule Removal.

It exits 1 if any check failed. A failure is a finding: reproduce it in a test before changing code.

When a provider's answer is in doubt, record it from the test calendars and keep it as a fixture.
`scripts/provider_fixtures.py RECORDED.json FIXTURE.json` keeps every key, type, date, status, and
recurrence rule, and replaces identifiers, version stamps, addresses, people's names, and links'
query strings with stable placeholders. Record synthetic test events only: event text is kept.
`tests/fixtures/providers/` holds the answers recorded on 2026-10-12, and
`tests/adapters/*/test_recorded_*_answers.py` pin how each adapter reads them.

## Architecture rules

`lint-imports` checks the import boundaries below through the contracts in `pyproject.toml`, and
`tests/test_ubiquitous_language.py` checks that code and documentation avoid the terms `CONTEXT.md`
rules out.

- Domain code cannot import application, infrastructure, interfaces, or bootstrap modules.
- Application code cannot import concrete adapters.
- Application contexts depend only downward: `operations`, then `identity`, then `sync`, then
  `shared` (ADR 0032).
- Provider dictionaries are translated at the Google adapter boundary.
- Use constructor injection and small protocols; do not introduce a dependency-injection framework.
- In `web/src`, features compose components, components render `lib`, and `lib` imports neither;
  `components/ui` imports only other UI primitives. ESLint's `no-restricted-imports` enforces this
  for alias (`@/features/x`) and relative (`../features/x`) imports.
- ESLint bounds complexity, nesting, parameters, and length, as Ruff does for the backend, and no
  frontend code is exempt. Split a component, hook, or module that reaches a bound; do not disable
  the rule.

### Provider sign-in preview

Production provider sign-in requires a Master Key, existing OAuth client ID/secret, trusted
`CALENDAR_SYNC_PUBLIC_URL`, the separate `/api/v1/sign-in/{slug}/callback` registered with each
provider, and explicit administrator enablement. Both providers are off by default. For local
provider checks use `http://localhost:<port>` consistently in the browser and configured origin;
provider POSTs require the exact configured Origin, so a Vite origin on a different port cannot
start that flow. Use the compiled UI on the callback origin or configure the development proxy
and registered callback consistently. See [setup](self-hosting.md#sign-in-with-google-or-microsoft).

Run `.venv/bin/python scripts/dev_preview.py --sign-in both` to show both identity buttons.
Google signs into the preview administrator through a synthetic loopback callback; Microsoft
opens the generic password-link form, which accepts the preview email and password above.
`--sign-in passwordless` removes that administrator's password: use Google to enter, then open
Settings, Your account to set a first password. `--sign-in disabled` preserves the Google binding
but turns both providers off, showing password recovery guidance after ordinary password sign-in.
The optional `--port` also sets the preview's callback origin. For the sign-up surface, combine
`--sign-in both --registration readyOpen`; Invitation uses the registration preview link above.

These fixtures use a fresh in-memory Master Key for identity proofs only, real temporary preview
storage, and synthetic local provider responses. They load no environment clients, make no
provider network calls, send no mail, and start no calendar synchronization. They add no routes
to the production application. On light and dark appearances, check the sign-in page at 390px
and desktop widths, then Your account, Administration, and the provider-link form.

The [synthetic review gallery](assets/reviews/provider-sign-in/README.md) compares sign-in in both
themes and viewport sizes, plus selected Your account and Administration views, and records the
source revision and limits of the live checks.

OIDC tests use synthetic signed tokens, fake transport, a fixed clock, and temporary SQLite
databases. They exercise issuer/audience/nonce/expiry checks, Microsoft tenant and JWK issuer
validation, admission/credential races, last-method protection, protocol privacy, and bounded
storage/network work without personal provider accounts. Synthetic preview results are not
live Google or Microsoft verification; the calendar checks above do not verify provider sign-in.

The implementation uses `Authlib>=1.9.1,<2` for code-flow/S256 PKCE mechanics,
`joserfc>=1.6.8,<2` for RS256/claims verification, and `requests>=2.32.5,<3` for bounded HTTP.
See [Authlib's client guidance](https://docs.authlib.org/en/latest/oauth2/client/web/)
and [joserfc's JWT API](https://jose.authlib.org/en/guide/jwt/). Provider-specific issuer policy
remains in each provider package. The local identity assets and their origins are recorded in
`web/src/assets/sign-in/README.md`; follow the official
[Google](https://developers.google.com/identity/branding-guidelines) and
[Microsoft](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-branding-in-apps)
button guidance, with comparable prominence and no runtime remote fonts or branding fetches.

## Offline restoration command

After installing the editable package, use the isolated terminal entry point:

```sh
.venv/bin/calendar-ghost-restore inspect --database /protected/restored.db
mkdir -m 700 /protected/before-change
.venv/bin/calendar-ghost-restore prepare --database /protected/restored.db \
  --backup /protected/before-change/before.db --administrator-id SELECTED_USER_ID \
  --acknowledge-services-stopped
```

Export the matching `CALENDAR_SYNC_MASTER_KEY` from your protected recovery store before either
command. No normal Settings, API, provider, scheduler, Instant Sync, or mail composition runs.
Inspection prints only schema and record counts. With no credentials to authenticate it reports
`key_unverified`; a syntactically valid key alone does not establish a match. Neither command
lists email addresses or credentials. Obtain the selected existing Installation Administrator's
identifier from a protected operator inventory, never from a public list. Preparation asks twice
for a hidden fresh password of 12 to 256 characters and refuses a terminal that cannot hide it.
Never put the password or Master Key in command arguments.

Keep traffic closed. Stop the application and backup replicator, then check their service status
and process inventory before acknowledging `--acknowledge-services-stopped`. The command cannot verify that
processes are stopped; a SQLite lock does not prove this. Keep every writer stopped throughout
inspection and preparation. Use the matching image and a new database path, preserve the original,
and keep the backup parent private, operator-owned, and free of symlinks. Preparation's
before-change backup does not replace the independent recovery backup.

For the container image, use the same installed command in a disposable interactive container,
with the restored directory mounted and secrets supplied through a protected environment file:

```sh
docker run --rm -it --network none --env-file /protected/recovery.env \
  -v /protected/restore:/restore --entrypoint calendar-ghost-restore MATCHING_IMAGE \
  inspect --database /restore/restored.db
docker run --rm -it --network none --env-file /protected/recovery.env \
  -v /protected/restore:/restore --entrypoint calendar-ghost-restore MATCHING_IMAGE \
  prepare --database /restore/restored.db --backup /restore/before-change/before.db \
  --administrator-id SELECTED_USER_ID --acknowledge-services-stopped
```

Create `/protected/restore/before-change` with mode 0700 and the container operator's ownership
first. Exit statuses are 0 for completion, 2 for usage, acknowledgement, or password input, and
1 for storage, schema, administrator selection, or key failures. Diagnostics use fixed safe codes.
