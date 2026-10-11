# Connect Outlook through Microsoft Graph v1.0

Builds on [ADR 0011](0011-recurring-event-synchronization.md),
[ADR 0018](0018-project-by-invitation-response.md),
[ADR 0022](0022-route-calendar-requests-by-provider.md) (amended with provider descriptors), and
[ADR 0031](0031-keep-the-providers-reason-as-a-cause.md).

## Context

Outlook (Microsoft 365 work or school accounts, and personal Outlook.com accounts) is the second
calendar provider. Its calendars must serve as the source or destination of a Directional Sync
Rule, alone or beside Google, with every product invariant holding as it does for Google: series
project as series, writes notify nobody, a Managed Projection carries private Managed Origin
metadata and can be found again by it, and nothing is deleted on unproven evidence.

Microsoft Graph is the only supported API for these calendars. Its v1.0 documentation was read on
2026-10-11, and each finding below links the page it comes from. Graph `beta` is not supported for
production use ("Use of these APIs in production applications is not supported"), so only v1.0 is
used.

What Graph v1.0 offers, and what it does not:

- **Changes of one calendar.** v1.0 has only `calendarView/delta`
  ([event: delta](https://learn.microsoft.com/en-us/graph/api/event-delta?view=graph-rest-1.0)).
  It needs a fixed `startDateTime` and `endDateTime`, which its tokens keep; it returns single
  events, occurrences, and exceptions, but never a series master; it supports no `$select`,
  `$filter`, or `$expand`, so it carries no extended properties; deletions, and changes to events
  outside the window, arrive as `@removed` with only an id. The delta that returns series masters
  unexpanded (`/calendars/{id}/events/delta`) is "currently available only in the beta version".
- **Series.** `GET /me/calendars/{id}/events` lists single events and series masters, with
  OData query parameters. A master read by its id can return `recurrence`, `cancelledOccurrences`
  (`$select`), and `exceptionOccurrences` (`$expand`). `GET /events/{id}/instances` lists a
  series' occurrences and exceptions within a window, but not the cancelled ones.
- **Recurrence.** `patternedRecurrence` has six pattern types (daily, weekly, absolute and relative
  monthly, absolute and relative yearly), each with single values: one day of the month, one
  month, one week index. It has no hourly rules, no lists of positions, and no RDATE or EXDATE.
  An exception cannot be moved to or past the day of a neighbouring occurrence
  (`ErrorOccurrenceCrossingBoundary`).
- **Private metadata.** Single-value extended properties named in our own GUID namespace
  (`String {guid} Name x`) are written with the event, expanded when read, and filtered on
  ([extended properties](https://learn.microsoft.com/en-us/graph/api/singlevaluelegacyextendedproperty-get?view=graph-rest-1.0)).
  Open extensions are "not filterable", so projections could not be found again by them.
- **Mail.** Graph sends invitations when an event has attendees, and a cancellation when a meeting
  is deleted on its organizer's calendar or `/cancel` is called. An event without attendees is an
  appointment.
- **Errors.** Graph errors carry `error.code` and nested `innererror.code`, which clients should
  code against, never `message`. The identity platform's token errors carry the RFC 6749 `error`
  field "to react to errors" and AADSTS numbers in `error_codes`, which are "for diagnostics" and
  "subject to change". Throttling answers 429, or 503, with `Retry-After` in seconds.

## Decision

### Provider Kind, names, and settings

The Provider Kind is `outlook`. Its descriptor names the account "Microsoft account" and the
calendar service "Outlook", and its connection flow lives under `/api/v1/oauth/microsoft/`. The
installation registers one Microsoft Entra application and configures
`CALENDAR_SYNC_MICROSOFT_CLIENT_ID`, `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET`,
`CALENDAR_SYNC_MICROSOFT_REDIRECT_URI` (default
`http://localhost:8000/api/v1/oauth/microsoft/callback`), and `CALENDAR_SYNC_MICROSOFT_TENANT`
(default `common`). Without them nothing changes and `GET /api/v1/providers` lists no Microsoft
provider.

### Authorization and identity

- The authorization code flow with PKCE (S256) runs against
  `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/`, `common` by default, so personal and
  work or school accounts both connect. It uses the neutral OAuth mechanics: a single-use state
  bound to the signed-in, active User and to this provider, and nothing connects for a User
  disabled during the flow.
- Delegated scopes are least-privilege: `openid`, `email`, `offline_access`, `User.Read`, and
  `Calendars.ReadWrite`; none needs an administrator's consent. Calendars shared into another
  person's mailbox need `Calendars.ReadWrite.Shared` and are not requested: only calendars listed
  in the account's own mailbox are offered.
- The Connected Account's email is Graph's `/me` `mail`, else `userPrincipalName`, else the ID
  token's `email` or `preferred_username`. Microsoft documents these as mutable display values;
  reauthorization finds an account by Provider Kind and email, as it does for Google.
- Every token refresh stores the rotated refresh token Microsoft returns.

### Private metadata

Every write carries three single-value String extended properties in the Calendar Ghost namespace
`{8EF42533-0AD0-4C67-A411-7FD5CF9F109E}`: `CalendarGhostRule` (the rule), `CalendarGhostOperation`
(the Operation Key), and `CalendarGhostOrigin` (the source account, calendar, and event, and for
an occurrence its original start). Rule and Operation Key are separate so they can be filtered on:
`managed_events` filters on the rule and `find_projection` on the Operation Key. Every read
expands the three properties, so an event carrying them is a Managed Projection and is never a
source, exactly as Google's private extended properties work (ADR 0006).

### Change feed: rebuilding series from v1.0

The adapter keeps series as series without beta, from three documented reads:

1. **Full listing** (`cursor` absent, as on a rule's first run, the daily pass, or reprojection).
   It first starts a `calendarView/delta` round and follows it to its delta link, so no change made
   while listing is lost. It then lists `GET /me/calendars/{id}/events`: every single event and
   series master, with their Managed Origins. For each master whose occurrences reach the sync
   window, it reads the master's occurrences in the window with `instances` and reports every
   exception: an occurrence that differs from the master's regular one, and an occurrence the
   pattern defines that `instances` no longer returns, which is cancelled. The listing is
   complete.
2. **Incremental changes** (`cursor` present). The cursor keeps the delta link and when the last
   run began. The adapter lists the single events and masters changed since then
   (`lastModifiedDateTime`, with a margin), reports them, and rebuilds every listed master's
   exceptions as above. It follows the delta link and reads every reported id it has not already
   read: an event still there is reported (an occurrence or exception rebuilds its series); one
   answered not found is reported as cancelled, as Google reports a deleted event. A delta link
   Graph rejects (410, `syncStateNotFound`) is answered with a full listing.
3. **Cancelled occurrences.** Graph lists no cancelled instances and documents no format for a
   cancelled occurrence's identifier, so the adapter expands the master's own pattern, in the
   series' time zone, and an occurrence the pattern defines that `instances` does not return is
   cancelled. Exceptions cannot move to or past a neighbouring occurrence's day, so looking for an
   occurrence between its neighbouring slots finds it however it was moved.

What this cannot do, and what follows:

- An occurrence cancelled in Outlook may reach the destination only at the next daily full pass,
  if Outlook did not change its master's `lastModifiedDateTime` when it was cancelled.
- Exceptions are listed up to 730 days past the sync window's start, as Google's listing stops at
  a page limit: an exception of an endless series further ahead is applied once it comes within
  that horizon.
- A series whose time zone cannot be recognized (Outlook's legacy custom zones) cannot be
  expanded. It counts as live, its exceptions are applied only as Graph reports them, and looking
  up one of its occurrences that `instances` does not return is a temporary failure, never proof of
  absence. As a source it reads in UTC, which can move its projected occurrences by an hour across
  daylight saving; the service logs a warning naming the event when it reads one.

### Recurrence

The adapter translates `patternedRecurrence` to iCalendar lines and back, exactly or not at all:

| Graph | iCalendar |
| --- | --- |
| `daily`, interval n | `FREQ=DAILY;INTERVAL=n` |
| `weekly`, interval n, days, first day of week | `FREQ=WEEKLY;INTERVAL=n;BYDAY=...;WKST=...`; `FREQ=DAILY;BYDAY=...` reads as every week |
| `absoluteMonthly`, day d up to 28 | `FREQ=MONTHLY;BYMONTHDAY=d` |
| `absoluteMonthly`, day d from 29 | `FREQ=MONTHLY;BYMONTHDAY=28,...,d;BYSETPOS=-1`: Outlook moves day d to the month's last day when the month is shorter |
| `relativeMonthly`, index, one day | `FREQ=MONTHLY;BYDAY=2MO` (or `-1MO` for last) |
| `relativeMonthly`, index, several days | `FREQ=MONTHLY;BYDAY=MO,TU,...;BYSETPOS=n` |
| `absoluteYearly`, `relativeYearly` | `FREQ=YEARLY;BYMONTH=m` with the monthly forms above |
| range `endDate`, `numbered`, `noEnd` | `UNTIL` (the end of that day in the series' zone), `COUNT`, neither; an `UNTIL` before the day's occurrence ends the range the day before |

Anything else has no Graph equivalent and is never approximated: hourly or finer frequencies,
`BYMONTHDAY` from 29 without the last-day form, negative or several `BYMONTHDAY` values, several
`BYMONTH` values, `BYYEARDAY`, `BYWEEKNO`, `BYHOUR` and finer, `BYSETPOS` lists, a fifth weekday
(`5MO` or `-2MO`), `COUNT` with `UNTIL`, and `RDATE`, `EXDATE`, or `EXRULE` lines. Restoring an
occurrence Outlook cancelled has no Graph operation either, nor has moving an exception past a
neighbour. Each raises `UnsupportedProjection`, and the Sync Run records a **Conflict** for that one
event or occurrence (`projection_unsupported`), leaving the destination unchanged while the rest of
the rule keeps synchronizing; a Conflict still there at the daily pass opens the rule's blocked
Incident. Every Graph pattern has an exact iCalendar form, so an Outlook source never needs this. A series
projection keeps, in its private origin, the lines and zone it was written with, and reads back with
them while Outlook still holds exactly that rule, so an equivalent rule written differently is never
mistaken for Drift and rewritten on every run.

### Time zones and all-day events

Every read asks for UTC (`Prefer: outlook.timezone="UTC"`) and text bodies. A master's time zone
comes from its `originalStartTimeZone`, translated from Windows to IANA names with the Unicode CLDR
mapping, so series keep their local time across daylight saving. A series projection is written in
the Windows zone of its IANA zone; one whose zone has no Windows name is unsupported rather than
written in UTC, which would shift its occurrences. Single events and occurrences are written in
UTC. An all-day event is read by its dates and written from midnight to midnight with `isAllDay`,
so it stays all-day.

### No mail, ever

Projections never carry attendees, an online meeting, or a response request
(`responseRequested: false`, `allowNewTimeProposals: false`); they show as busy and with normal
sensitivity, and set no reminder. The adapter never calls `/cancel`, `/forward`, `/accept`,
`/decline`, or `/tentativelyAccept`. Deleting a projection or an occurrence uses `DELETE`, which
sends a cancellation only for a meeting with attendees, which a projection never is. A change that
could email anyone is release-blocking, as for Google.

### Reading source events

`type` (`singleInstance`, `seriesMaster`, `occurrence`, `exception`), `seriesMasterId`, and
`originalStart` give each event its series identity; `isCancelled` and `@removed` entries become
cancellations. The Source Calendar's own answer is `responseStatus.response`: `accepted` and
`organizer` are accepted, `tentativelyAccepted` is Maybe, `declined` is declined, `notResponded` is
awaiting an answer, and `none` or anything unknown counts as accepted, as ADR 0018 decides. `showAs`
and `sensitivity` are read as Google's transparency and visibility are, which is not at all: a rule
projects an event the source shows as free, and a Details Projection copies a private event's title,
as it does from Google. Attendee addresses and the online meeting's join address are read only to
describe Source Changes, never projected.

### Causes

`infrastructure/microsoft/causes.py` maps Graph's `error.code` and `innererror.code`, and the token
endpoint's `error` field, to the closed set of ADR 0031, citing Microsoft's documentation for each:

- `oauth_client_invalid`, the administrator's: `invalid_client` (a wrong or expired client secret)
  and `unauthorized_client` (an application deleted or not found in the directory).
- `access_revoked`, the User's: `invalid_grant` (an expired or revoked grant, a password reset, or
  a tenant whose administrator has not consented), `interaction_required`, `consent_required`, and
  Graph's `InvalidAuthenticationToken` and `Authorization_RequestDenied`. Its step, Reauthorize account, explains that a work account
  may need its organization's administrator to approve the application first.
- `calendar_forbidden`: `ErrorAccessDenied` on a calendar. `calendar_not_found`:
  `ErrorItemNotFound` or `ErrorFolderNotFound` on a calendar. `rate_limited`: 429 and `TooManyRequests`,
  `ApplicationThrottled`, `activityLimitReached`. `temporary`: 503, 504, and other 5xx answers, and
  `temporarily_unavailable`.

AADSTS numbers are logged, as short tokens, only to help an administrator name a failure; no
decision reads them, because Microsoft says they change. Microsoft's message text is never stored,
logged, or returned. Nothing Graph answers maps to `api_disabled` or `quota_exceeded`.

## Verify against a test tenant before release

The documentation leaves these unconfirmed; each has a synthetic fixture that mirrors the documented
shape, and each must be confirmed with a real personal account and a real work account before a
release that enables the provider:

1. `/me/calendars/{id}/calendarView/delta` on v1.0 (the v1.0 reference shows only the default
   calendar's path), and that changes outside the window arrive as `@removed`.
2. That cancelling one occurrence changes its master's `lastModifiedDateTime`.
3. `$filter` on `lastModifiedDateTime` and on extended properties under `/me/calendars/{id}/events`,
   and `$expand` of extended properties on `instances`.
4. How an all-day event reads under `Prefer: outlook.timezone="UTC"`.
5. That `PATCH` on an occurrence makes an exception and `DELETE` on one cancels only it.
6. That an attendee-less event sends no message on create, update, or delete.
7. Which `/me` field holds a personal account's address.
8. The Graph `error.code` values above, which Graph's error reference no longer lists.

## Alternatives considered

- **Beta `events/delta`.** It returns masters unexpanded without a window, the shape the domain
  wants, but beta is unsupported in production and may change without notice.
- **Flattening series into single events.** It fits `calendarView/delta` directly, but contradicts
  ADR 0011: it needs a horizon, multiplies writes, and loses series identity for Google
  destinations.
- **Parsing `cancelledOccurrences` identifiers.** Their format is documented only in beta, and
  ADR 0011 already rejected constructing identifiers from undocumented formats.
- **Open extensions for metadata.** Not filterable, so projections could not be found by rule or
  Operation Key.
- **The Microsoft Graph SDK or MSAL.** Two large dependencies for a handful of REST calls and one
  token exchange; the adapter uses `httpx`, which import-linter keeps inside its package.
- **Change notifications (webhooks).** They need a public address, which the Community Edition
  does not require (CONTEXT.md, Scheduled Sync).

## Consequences

Outlook calendars synchronize with the guarantees Google calendars have, at the cost of reading a
series' instances when its master changes and of expanding Outlook patterns in the adapter. The
CLDR zone mapping, the pattern translation table, and the extended property names become
compatibility surfaces. Occurrence cancellations made in Outlook may wait for the daily pass.
Recurrences that only Google can express, and restoring occurrences Outlook cancelled, are blocked
events rather than approximations. `httpx` becomes a runtime dependency. The items above must be
verified against a live tenant before release.
