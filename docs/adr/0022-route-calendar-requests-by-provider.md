# Route calendar requests by each account's provider

Amends [ADR 0005](0005-google-calendar-as-external-adapter.md), which kept Google as the only
adapter until a second provider was real.

## Context

Outlook (Microsoft 365), iCloud, and Fastmail are planned, and Proton or Tuta may follow. ADR 0005
kept Google behind a Calendar Provider port without building a provider framework. The domain and
the use cases are already provider-neutral: Calendar Events carry iCalendar recurrence lines,
cursors and revisions are opaque strings, failures use a neutral `ProviderFailureKind`, and the
provider port is split into the roles each use case needs. The test fake has already stood in for
Google across those roles.

The edges are still Google-shaped:

- Composition wires one `GoogleCalendarProvider` for every account, and nothing records which
  provider a Connected Account belongs to outside an SQL column that only allows `'google'`.
- The Google adapter decides which occurrences a rule projects and which ones are exceptions.
  Those are domain rules, and every new adapter would have to copy them.
- Calendar discovery passes Google's access roles (`owner`, `writer`) through the application to
  the Web UI.
- Incident summaries, error messages, and run log lines name Google in provider-neutral code.
- Call instrumentation lives in the Google package.
- Nothing checks that an adapter, or the test fake, honors the port beyond its docstrings.

## Decision

- **Provider Kind.** Every Connected Account records the calendar service it belongs to as a
  `ProviderKind`. It is set when the account is first connected and never changes. The database
  stores it as text without a CHECK constraint, and code validates it, so adding a provider needs
  no schema change. Reauthorization finds an account by provider and email together.
- **Routing at composition.** `RoutingCalendarProvider` and `RoutingAccountCalendars` implement
  the existing ports and send each request to the adapter of the account named in its endpoint.
  Use cases do not change, and a rule's source and destination may belong to different providers.
  An unknown account or an unconfigured provider fails the same way a provider failure does today.
- **Adapters translate; the domain decides.** Whether a policy projects an occurrence
  (`TransformationPolicy.projects`) and whether an occurrence departs from its series
  (`CalendarEvent.is_exception_of`) are domain predicates. Adapters call them and never restate
  them.
- **One package per adapter.** Each adapter lives in `infrastructure/<provider>/` and owns its
  SDK. An import-linter `protected` contract keeps that SDK inside its package, and an
  `independence` contract keeps adapter packages from importing each other once a second package
  exists. Shared adapter infrastructure, such as call instrumentation, lives outside any one
  provider's package.
- **The Calendar Provider contract.** A shared test suite states what every adapter must honor
  through the ports alone: created projections carry their Managed Origin, Operation Keys make
  creates idempotent, only a rule's own projections are listed, writes to an unowned projection
  raise `ProjectionOwnershipMismatch`, deleting twice is quiet, and full listings are complete. The
  test fake and every new adapter must pass it before being composed.
- **Safety invariants stay per adapter.** An adapter that writes must keep Managed Origin metadata
  in private provider storage that event owners do not see, write without notifying anyone, and
  treat not-found answers conservatively. A provider that cannot store private metadata cannot
  host a Destination Calendar.
- **Provider names come from the Provider Kind.** Provider-neutral code names a provider through
  its `ProviderKind`, which adapters attach to their `ProviderFailure`s. Code that does not know
  the provider says "the calendar provider".
- **Connection flows are namespaced per provider.** OAuth routes stay under
  `/api/v1/oauth/<provider>/`. `/api/v1/oauth/google/callback` is registered with Google by every
  installation and never changes.

How accounts connect without OAuth redirects (CalDAV app passwords, read-only feed URLs), and
which roles a provider can serve (Provider Capabilities, such as source-only), will be decided in
a later ADR, before the first such provider.

## Alternatives considered

- **A plugin system with entry points.** Rejected: the Community Edition ships as one image with
  no third-party code, and plugins would add loading, versioning, and trust questions without a
  use.
- **The provider on `CalendarEndpoint`.** Rejected: an endpoint is a domain value used across
  every mapping table. The provider can be derived from the account, and an account's provider
  never changes, so copying it would only migrate every table for nothing.
- **Keep Google as the only adapter until Outlook lands.** Rejected: routing, the migration, and
  moving domain rules out of the adapter carry the most risk. Doing them first behind the Google
  adapter alone means the Outlook change adds a package rather than reshaping the core.
- **One adapter per CalDAV service.** Rejected: iCloud and Fastmail speak the same protocol. One
  CalDAV adapter, configured per account, serves both. Their differences are connection details,
  not adapters.

## Consequences

Adding Outlook becomes: a `MICROSOFT` Provider Kind, an `infrastructure/microsoft/` package that
passes the Calendar Provider contract, its OAuth routes, and one entry in the routing map. The Web
UI still says "Google account" until a second provider can be connected. Changing that copy is
part of that provider's plan.

Migration 17 rebuilds `connected_accounts`. Rolling back past it means restoring a backup taken
before the upgrade. A release that stored another provider's account cannot be rolled back to one
that does not know that Provider Kind.

What the planned providers expose, as of this decision:

| Provider | Interface | Fit |
| --- | --- | --- |
| Outlook / Microsoft 365 | Microsoft Graph, OAuth | Full adapter. Extended properties can hold the Managed Origin and can be filtered on. |
| iCloud, Fastmail | CalDAV, app-specific passwords | One CalDAV adapter. Needs the connection-method ADR. Metadata lookups scan rather than filter. |
| Proton, Tuta | No public calendar API | At most Source Calendars through published feeds. Needs Provider Capabilities. |
| Notion | No calendar API; Notion Calendar sits on Google or Outlook | Not a Calendar Provider. |

## Amendment: provider descriptors (2026-10-11)

Preparing Outlook showed Google knowledge still in the core: the Google Cloud wording of
administrator Causes, the troubleshooting anchors and the Testing-mode pattern of Installation
Hints, the calendar name Google gives an unnamed calendar, Google's OAuth routes in the Web API,
and "Google account" in the Web UI. Each would have needed a branch on the Provider Kind once a
second provider existed.

- **One descriptor per provider.** Each provider's package gives bootstrap one
  `ProviderDescriptor` (`application/provider_descriptors.py`): its `ProviderGuide` (Provider
  Kind, the slug its connection flow lives under, its display and calendar names, the
  troubleshooting section for each Cause it can raise, and any Installation Hint only it explains,
  such as Google's 7-day grants in Testing mode), whether the installation configured it, its OAuth
  flow, and its calendar roles. `bootstrap/container.py` composes the descriptors in one place;
  routing, Installation Hints, and the Web API read them. Adding a provider adds its package and
  one line there.
- **Only Provider Kinds name providers in the core.** The domain, application, and interfaces name
  no provider, and nothing outside a provider's package names a Provider Kind member;
  `tests/test_provider_neutrality.py` fails otherwise. `ProviderKind` no longer carries a name:
  adapters label their failures with their calendar name for English summaries, and the Web UI
  names providers from its catalogs by Provider Kind. `GET /api/v1/google/configuration` stays as
  a compatibility alias, the one other place that names Google.
- **Shared mechanics are neutral infrastructure.** OAuth states bound to the signed-in User and
  PKCE (`infrastructure/oauth.py`), call tallying (`provider_calls.py`), Retry-After parsing
  (`retry_after.py`), and credential encryption (`security.py`) belong to no provider's package,
  and an import-linter contract keeps them from importing one.
- **Provider-parameterized connection.** `GET /api/v1/providers` lists the providers Users can
  connect and how. Flows run at `/api/v1/oauth/{slug}/start` and `/callback`, which keeps every
  Google address unchanged. Failures record the provider beside their Cause (migration 27), so
  hints and problems name it and link its own troubleshooting section.
- **Adapters report unnamed calendars.** A discovered calendar says whether its provider gave it a
  name of its own; one without is remembered without a name, instead of the core recognizing
  Google's habit of naming it by its identifier.
