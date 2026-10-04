# Installation Status for monitors and agents

Date: 2026-10-03. Status: proposed; revised after an outside review the same day.

## Why

The administrator runs Calendar Ghost on a home server and wants other software to know whether it
is healthy:

- **AI agents** such as Claude Code, Codex, and Hermes, which should answer "is my calendar sync
  working, and if not, what do I do?"
- **Uptime monitors** such as Uptime Kuma, which should alert when synchronization needs attention.
- **Homelab dashboards** such as Homepage or Homarr, which show a tile per service.

Today `/health` reports only that the process is running, and everything else needs an
administrator session cookie that no monitor or agent can obtain. The Overview's detailed health is
computed in the browser, so no server API can give the same answer. Nothing at all notices a
scheduler that stopped running passes while the process stays up.

## Decisions taken while designing

- **A dedicated status endpoint, not tokens on the existing API.** The dashboard API returns
  calendar IDs (often email addresses), account details, and, under Activity, event titles. An
  integration contract that is narrower and stable is safer than an allowlist over routes built for
  the Web UI.
- **MCP served by the application over HTTP.** Agents run on other machines than the homelab
  server; a remote MCP endpoint needs nothing installed on them.
- **No status badge in v1.** Every listed consumer can send an `Authorization` header and reads
  JSON. A badge is useful only to image-only dashboards and is the one consumer that would require
  unauthenticated status or a token in a URL. It stays a possible later addition.
- **Public Health Status is unchanged.** `/health` stays the unauthenticated liveness probe used by
  the Docker `HEALTHCHECK`. It never reports rule health: returning 503 for a Degraded Rule would
  mark the container unhealthy and let orchestrators restart it over an expired authorization.
- **One token, one level of detail.** An Integration Token may read rule names and incident
  summaries. Calendar names can be revealing, but the administrator issues each token to their own
  tool knowingly; a second "summary only" scope would add a choice nobody has asked for.

## Integration Tokens

An **Integration Token** is a named credential the Installation Administrator issues so a monitor or
agent can read Installation Status. It is a delegated administrator credential, not public access.

- **Format.** `cgs_` followed by 43 characters of URL-safe base64 encoding 32 random bytes. The
  prefix makes a leaked token recognizable to secret scanners and people. The plaintext is shown
  once, when issued.
- **Storage.** Migration `0018_integration_tokens.sql` creates `integration_tokens`:

  | Column | Meaning |
  | --- | --- |
  | `id` | Random identifier used to revoke the token |
  | `name` | Administrator-chosen label, 1–80 printable characters, such as "Uptime Kuma" |
  | `token_hash` | SHA-256 of the token, computed as administrator sessions already are; unique and indexed |
  | `scope` | `status:read`, the only scope in v1 |
  | `created_at` | When it was issued |
  | `last_used_at` | Last successful use, or null |
  | `revoked_at` | When it was revoked, or null |

  The plaintext and any prefix of it are never stored. A fast hash is right here: the token carries
  256 bits of randomness, so it cannot be guessed, unlike a password. Upgrading adds the empty
  table; rolling back to an earlier release leaves an unused table behind and is safe.
- **Names.** Trimmed, 1–80 characters, with control characters rejected (422), so a name is safe to
  write to logs.
- **Lifetime.** Tokens do not expire. Monitors need long-lived credentials and silent expiry breaks
  them. Revocation refuses every request that starts after it; it cannot recall a response already
  sent.
- **Usage tracking.** `last_used_at` is written at most once every 5 minutes per token, so a monitor
  polling every 20 seconds does not cause a SQLite write per request.
- **Scope.** `status:read` only. Any future scope, such as one allowing agents to act on rules,
  needs its own design review and threat model, and existing tokens never gain it implicitly.

### Ports and adapters

- `application/ports.py` gains an `IntegrationTokens` protocol:
  - `issue(name) -> IssuedIntegrationToken` returns the summary and the plaintext once;
  - `list() -> Sequence[IntegrationTokenSummary]` returns id, name, scope, created, last used, and
    revoked times, never the hash;
  - `revoke(token_id) -> bool`;
  - `authorize(token, scope) -> IntegrationTokenSummary | None`.
- `SqliteIntegrationTokens` in `infrastructure/` implements it, with an in-memory implementation
  beside the existing memory persistence for tests.
- `bootstrap/container.py` composes it.

### Managing tokens

Only an administrator session manages tokens; a token can never list, issue, or revoke tokens.

| Route | Result |
| --- | --- |
| `GET /api/v1/integration-tokens` | Every token, newest first, revoked ones last |
| `POST /api/v1/integration-tokens` `{name}` | The new token, including its plaintext once |
| `DELETE /api/v1/integration-tokens/{id}` | 204; 404 for an unknown id |

**Settings → Integrations** lists tokens with their last use, issues one in a dialog that shows the
plaintext once with a copy button, and revokes one through the existing inline destructive
confirmation. Below the list it shows copy-ready examples for Uptime Kuma, Homepage, Claude Code,
and Codex. They use the address the browser is using, read the token from an environment variable
where the client allows it, and say plainly when that address is plain HTTP.

### Authentication

One function, `authorize_status_reader`, decides access for both `/api/v1/status` (as a FastAPI
dependency) and `/mcp` (from an ASGI wrapper):

1. **An `Authorization` header is present.** It must be `Bearer cgs_` followed by exactly 43
   URL-safe base64 characters. Anything else, or a well-formed token that is unknown or revoked,
   is refused, **even if a valid session cookie accompanies it**, so a broken monitor credential is
   never hidden by a browser session. The format check runs before hashing, and lookup is a single
   indexed query on the hash.
2. **No `Authorization` header.** `/api/v1/status` accepts a valid administrator session cookie, so
   the Web UI and a signed-in administrator can read it. `/mcp` accepts only bearer tokens; MCP
   clients do not hold browser sessions.

Refusals are 401 with `WWW-Authenticate: Bearer` and an identical body for every reason, so a
response never reveals whether a token exists. A valid token without the required scope is 403,
which is unreachable in v1. Both routes are reads with no side effects beyond `last_used_at`, so the
cookie path adds no cross-site write risk.

Tokens are accepted only in the `Authorization` header, never in a query string, which keeps them
out of browser history, `Referer` headers, and ordinary access logs. A reverse proxy configured to
log request headers would still record them; the self-hosting guide says so. Exceptions raised
while authorizing never include the header, and logs may name a token's `name` but never the token
or its hash.

## Installation Status

### One health verdict, owned by the server

`web/src/lib/overview-health.ts` currently decides the Overview's tone and the order of its
problems. That classification moves into a new application use case, `GetInstallationStatus` in
`application/status.py`. The Overview, `/api/v1/status`, and MCP then share one verdict. The
Overview renders the server's status and problem list as given, mapping each to its existing
headline, wording, and action, and no longer computes tone or ordering itself.

`GetInstallationStatus` reads, in one place:

- the rules, their latest run outcomes, and their running work;
- the state of every Connected Account each rule names, so a rule whose source or destination
  account is disconnected is stopped, as the Overview decides today;
- open incidents and open blocks, which the Overview treats separately;
- the scheduler heartbeat described below.

The statuses, most urgent first:

| Status | When | `needs_attention` |
| --- | --- | --- |
| `stalled` | Synchronization is enabled but the scheduler is not running passes | true |
| `stopped` | A rule is degraded or names a disconnected account, until the administrator acts | true |
| `review` | An open incident that is not provider waiting, open blocks, an overdue rule, or provider waiting that has lasted over 24 hours | true |
| `waiting` | The only problems are rate-limit or temporary provider incidents under 24 hours old, which retry by themselves | false |
| `paused` | Rules exist and have synced before, but none is enabled | false |
| `setup` | No account, no rule, no rule enabled yet, or every account needs reauthorization while no rule is stopped | false |
| `healthy` | Every enabled rule is running and up to date | false |

`problems` lists every current problem in this order, so one never hides another. A rule whose
removal is in progress (`REMOVING` with running removal work) is not counted as stopped, as
`withoutRunningRemovals` does in the browser today.

### Scheduler heartbeat

A hung scheduler is the failure an external monitor most needs to catch, and a per-rule freshness
check cannot tell it apart from a rule queued behind a long pass. The scheduler therefore reports
its own progress:

- A `SchedulerHeartbeat` port in `application/ports.py` exposes when the current pass started, if
  one is running, and when the last pass completed without an exception. `SyncScheduler` records
  both in memory; the process is single by design, and a dead process already fails `/health`.
- The status is `stalled` when any enabled rule exists and:
  - no pass is running and none has completed within the last 15 minutes (three scheduler
    intervals), counting from process start before the first pass; or
  - the running pass started more than 3 hours ago. A full pass has taken 40 minutes on a
    Raspberry Pi, so 3 hours is far beyond a slow pass.
- When composition has no scheduler while rules are enabled, the status is `stalled` too.
- A pass that raises, such as on a database held locked, does not count as completed, so repeated
  failing passes become `stalled` after 15 minutes.

### Overdue rules

Beneath a healthy scheduler, an enabled rule is **overdue** when it has succeeded before, has no
running work, was listed by the last completed pass, and its last successful Sync Run is more than
24 hours old. Every pass attempts every enabled rule, so a rule that keeps failing already opens an
incident; an overdue rule without one means something the incident rules do not cover, and it makes
the status `review`. Rules that have never succeeded are not overdue: their failures open incidents,
and no reliable start time exists to measure them from. A rule the last completed pass did not list,
such as one resumed or reauthorized since, is not overdue either: resuming only changes its state, so
its last success stays old until the next pass runs it. The heartbeat reports the ids of the rules
its last completed pass listed for this reason.

### Lasting provider waits

A rate-limit or temporary provider incident is `waiting` while it is under 24 hours old. After
that it is `review`, so a monitor alerts on an outage that is not clearing by itself.

### `GET /api/v1/status`

Always 200 for an authorized request, with `Cache-Control: no-store`. A failure status would read
as "the service is down", which `/health` already answers. During setup the status is `setup`,
never an error, so a monitor added early does not flap.

```json
{
  "status": "healthy",
  "needs_attention": false,
  "summary": "3 rules running, last sync 2 minutes ago",
  "version": "0.1.1",
  "checked_at": "2026-10-03T10:00:00Z",
  "last_synced_at": "2026-10-03T09:58:00Z",
  "scheduler": {
    "configured": true,
    "last_pass_completed_at": "2026-10-03T09:58:00Z",
    "current_pass_started_at": null
  },
  "counts": {
    "rules": 3,
    "running": 3,
    "stopped": 0,
    "paused": 0,
    "overdue": 0,
    "open_incidents": 0,
    "blocked_events": 0,
    "disconnected_accounts": 0
  },
  "problems": [],
  "rules": [
    {
      "id": "rule-id",
      "name": "Work → Personal",
      "state": "enabled",
      "source": { "calendar": "Work", "provider": "google" },
      "destination": { "calendar": "Personal", "provider": "google" },
      "projection": "busy_only",
      "last_succeeded_at": "2026-10-03T09:58:00Z",
      "running": null,
      "problem": null
    }
  ],
  "incidents": [
    {
      "rule_id": "rule-id",
      "category": "authentication",
      "summary": "Calendar provider authorization expired",
      "opened_at": "2026-10-03T08:00:00Z"
    }
  ]
}
```

- `summary` is one plain sentence describing the status, suitable for a dashboard tile.
- `scheduler.configured` says whether this installation runs a scheduler at all; `status` says
  whether it is keeping up.
- `counts.running` counts enabled rules that are not stopped, so `running` plus `stopped` never
  exceeds `rules`.
- `problems` lists `{ "kind", "rule_id", "summary" }` most urgent first; `kind` is one of `stalled`,
  `stopped`, `review`, `blocked`, `overdue`, or `waiting`, and `rule_id` is null for
  installation-wide problems.
- `rules[].name` is "source calendar → destination calendar" from the last known calendar names,
  falling back to "Unnamed calendar".
- `rules[].running` is the kind of running work (`preview`, `sync`, `reconciliation`, `removal`) or
  null.
- `rules[].problem` is the rule's most urgent entry from `problems`, or null.
- `provider` is the account's Provider Kind (ADR 0022). Text never assumes Google.
- `incidents` lists open incidents only.

**Deliberately absent:** calendar IDs, connected account IDs and emails, event titles or any other
event content, Activity entries, blocked-event details, and token data. A test seeds synthetic data
containing all of these and asserts none of their values appears anywhere in the serialized
response, not only that no field is named after them.

## MCP server

`interfaces/mcp/` serves the Model Context Protocol at `/mcp` with the official `mcp` Python SDK,
pinned to `mcp>=2.3,<3`:

- **Transport.** Streamable HTTP, stateless, with JSON responses, so there is no per-client session
  to keep in the single process. The implementation plan names the exact v2 server class,
  constructor arguments, and app factory after checking them against the pinned release; v2
  renamed parts of the v1 API.
- **Routing.** The SDK's app serves its own endpoint path, so the plan sets that path and mounts the
  app so the client URL is exactly `/mcp`, with no `/mcp/mcp`. It is registered before the API
  fallback and the Web UI catch-all and must not match any other path. Tests pin the exact URL,
  `/mcp/` behaviour, and that other paths still reach the Web UI.
- **Lifespan.** The existing `lifespan` in `create_app` enters the SDK's session manager beside the
  scheduler; a mounted app's own lifespan never runs.
- **Authentication.** An ASGI wrapper around the mounted app calls `authorize_status_reader` with
  cookies disabled and refuses before the SDK sees the request.
- **Host checks.** The SDK's DNS-rebinding protection restricts Host and Origin to localhost by
  default and would refuse `ghost.lan` with 421. That protection exists for unauthenticated local
  servers: a hostile page can rebind its domain to the LAN but cannot supply the bearer token. With
  every request authenticated, the allowlist is turned off and ADR 0023 records why.
- **Tools**, each annotated `readOnlyHint: true`:
  - `get_status`: the Installation Status, identical to `/api/v1/status`.
  - `get_rule(rule)`: one rule by id or by its "Work → Personal" name, adding the last Sync Run's
    counts (created, updated, deleted, conflicts, drift, failure kind), the last reconciliation,
    and the rule's open incident. An unknown or ambiguous name is a tool error that says so and
    points to `get_status`; it does not list rule names.
- **Instructions.** The server's instructions tell the agent what each status means, that
  Calendar Ghost is read-only through MCP, and what the administrator does for each problem:
  restart the service when stalled, reauthorize in Settings, review blocked events in Activity, or
  wait for provider limits to clear.

Client setup, also shown in Settings, with the token kept in an environment variable rather than
typed into a command line:

```sh
export CALENDAR_GHOST_TOKEN=cgs_…   # from a password manager or shell profile
claude mcp add --transport http calendar-ghost https://ghost.example.lan/mcp \
  --header "Authorization: Bearer ${CALENDAR_GHOST_TOKEN}"
```

```toml
# ~/.codex/config.toml
[mcp_servers.calendar-ghost]
url = "https://ghost.example.lan/mcp"
bearer_token_env_var = "CALENDAR_GHOST_TOKEN"
```

import-linter contracts gain `interfaces/mcp` with the same rules as `interfaces/api`, and the `mcp`
package may be imported only inside `interfaces/mcp`.

## Transport security

A token only reads status. Plain HTTP on this machine or a home network is the homelab norm, so
Settings says nothing there. When Settings is open at an address that would carry a token across
the internet unencrypted, a quiet note in the Integrations group's footer recommends HTTPS, for
example Tailscale Serve or a reverse proxy. (Revised 2026-10-04 after a design critique: the first
version showed a red warning on every plain-HTTP visit.)

## Testing

- **Application.**
  - Table tests for every status and the order of `problems`, ported from
    `overview-health.test.ts` and extended with mixed stopped, review, and waiting problems, an
    active removal, a disconnected account on either side of a rule, and open blocks.
  - Heartbeat: never started at 14 and 16 minutes, last completed pass at 14 and 16 minutes, a
    running pass at 2 h 59 min and 3 h 1 min, a failing pass not counted as completed, no
    scheduler with enabled rules, no enabled rules with a stalled scheduler.
  - Overdue at 23 and 25 hours, a running rule never overdue, a never-succeeded rule never
    overdue.
  - Provider waiting at 23 and 25 hours; `needs_attention` for each status.
- **Infrastructure.** SQLite tokens: issue, only the hash stored, authorize, revoke, malformed and
  oversized tokens refused before lookup, control characters in names refused, the 5-minute
  `last_used_at` throttle, and the migration applied to an existing database. The scheduler
  records pass start and completion, and not completion when a pass raises.
- **API.**
  - `test_api_authorization.py` keeps its route-wide session assertion with `/api/v1/status` as a
    named exception, and proves by request that a valid token is refused by every other API route.
    Token management requires the session.
  - Status with a cookie, with a token, with a revoked token, with a malformed header beside a
    valid cookie (refused), and with a token in the query string (refused).
  - The privacy test described above.
  - Logs captured during refused and accepted requests never contain the token.
- **MCP.** Requests to `/mcp` and `/mcp/` for each method with no credentials, a cookie only, a
  revoked token, and a valid token; tools listed and read-only; both tools return the expected data,
  `get_rule` by name, by id, and ambiguous; a `ghost.lan` Host header accepted with a token.
- **Frontend.** The Overview renders each server status and problem with its wording and action
  and no longer derives tone; Settings → Integrations issues, shows once, copies, revokes, and
  notes plain HTTP only for addresses outside this machine and the home network.

## Documentation

- **ADR 0023**, "Integration Tokens, Installation Status, and MCP": the access model, why the
  dashboard API is not exposed to tokens, why `/health` stays liveness only, why the MCP Host
  allowlist is off, why one token level is enough, and why the badge is deferred.
- **`CONTEXT.md`.** Add Integration Token and Installation Status under Access and Health; Public
  Health Status gains a sentence that Installation Status is the authenticated counterpart.
- **`docs/self-hosting.md`.** A "Monitoring and agents" section: HTTPS first, issuing a token,
  Uptime Kuma (JSON query `$.needs_attention` equals `false`), Homepage's custom API widget, Claude
  Code, and Codex, and what each status means.
- **`AGENTS.md`.** The security bullet names `/api/v1/status` and `/mcp` as the only routes that
  accept an Integration Token.
- **`CHANGELOG.md`.** One entry.

## Out of scope

- A status badge image.
- Scopes beyond `status:read`, and agent actions such as Sync Now or pausing a rule.
- Token expiry.
- Activity, event, or audit data through tokens or MCP.
