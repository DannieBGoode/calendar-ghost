# Installation Status for monitors and agents

Date: 2026-10-03. Status: proposed.

## Why

The administrator runs Calendar Ghost on a home server and wants other software to know whether it
is healthy:

- **AI agents** such as Claude Code, Codex, and Hermes, which should answer "is my calendar sync
  working, and if not, what do I do?"
- **Uptime monitors** such as Uptime Kuma, which should alert when synchronization needs attention.
- **Homelab dashboards** such as Homepage or Homarr, which show a tile per service.

Today `/health` reports only that the process is running, and everything else needs an
administrator session cookie that no monitor or agent can obtain. The Overview's detailed health is
computed in the browser, so no server API can give the same answer.

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

## Integration Tokens

An **Integration Token** is a named credential the Installation Administrator issues so a monitor or
agent can read Installation Status. It is a delegated administrator credential, not public access.

- **Format.** `cgs_` followed by 32 random bytes, URL-safe base64. The prefix makes a leaked token
  recognizable to secret scanners and people. The plaintext is shown once, when issued.
- **Storage.** Migration `0018_integration_tokens.sql` creates `integration_tokens`:

  | Column | Meaning |
  | --- | --- |
  | `id` | Random identifier used to revoke the token |
  | `name` | Administrator-chosen label, 1–80 characters, such as "Uptime Kuma" |
  | `token_hash` | SHA-256 of the token, computed as administrator sessions already are; unique |
  | `scope` | `status:read`, the only scope in v1 |
  | `created_at` | When it was issued |
  | `last_used_at` | Last successful use, or null |
  | `revoked_at` | When it was revoked, or null |

  The plaintext and any prefix of it are never stored. Upgrading adds the empty table; rolling back
  to an earlier release leaves an unused table behind and is safe.
- **Lifetime.** Tokens do not expire. Monitors need long-lived credentials and silent expiry breaks
  them. Revocation is immediate.
- **Usage tracking.** `last_used_at` is written at most once every 5 minutes per token, so a monitor
  polling every 20 seconds does not cause a SQLite write per request.
- **Scope.** `status:read` only. The column exists so a later `rules:write` needs no migration.

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
confirmation. Below the list it shows copy-ready examples for Uptime Kuma, Homepage,
`claude mcp add`, and Codex, filled in with the address the browser is using.

### Authentication

A new dependency, `require_status_reader`, accepts either a valid administrator session cookie or
`Authorization: Bearer cgs_…` for a token with `status:read`. It guards only `/api/v1/status` and
`/mcp`; every other route keeps `require_admin`.

- A missing, malformed, unknown, or revoked token is 401 with `WWW-Authenticate: Bearer`, with the
  same body for each, so a response never reveals whether a token exists.
- A valid token without the required scope is 403. Unreachable in v1.
- Tokens are accepted only in the `Authorization` header, never in a query string, so they do not
  leak into access logs, browser history, or `Referer` headers.
- Logs may name the token's `name`; the token and its hash are never logged.

## Installation Status

### One health verdict, owned by the server

`web/src/lib/overview-health.ts` currently decides the Overview's tone. That classification moves
into a new application use case, `GetInstallationStatus` in `application/status.py`, which reads
`GetDashboard`, the rule summaries, and open incidents. The Overview, `/api/v1/status`, and MCP then
share one verdict. The Overview keeps its own headlines, wording, and actions and takes only the
`status` and the per-rule problems from the server, through a `status` field added to
`/api/v1/dashboard`.

The statuses, most urgent first, keep the Overview's existing meaning:

| Status | When | `needs_attention` |
| --- | --- | --- |
| `stopped` | A rule is degraded, or its account is disconnected, until the administrator acts | true |
| `review` | An open incident that is not provider waiting, events blocked, or a stale rule | true |
| `waiting` | The only problems are rate-limit or temporary provider incidents, which retry by themselves | false |
| `paused` | Rules exist and have synced before, but none is enabled | false |
| `setup` | No account, no rule, no rule enabled yet, or every account needs reauthorization while no rule is stopped | false |
| `healthy` | Every enabled rule is running and up to date | false |

A rule whose removal is in progress (`REMOVING` with running removal work) is not counted as
stopped, as `withoutRunningRemovals` does in the browser today.

### Stale rules

A hung scheduler currently looks healthy, which is the failure an external monitor exists to catch.
An enabled rule is **stale** when all of these hold:

- it has no running work;
- it has no open incident;
- its last successful Sync Run is more than 60 minutes ago. Rules do not record when they were
  enabled, so a rule that has never succeeded is measured from its latest Rule Preview, which
  enabling requires.

A stale rule makes the status `review` with the problem "not synced recently". The threshold is 12
scheduler intervals rather than a few because a scheduled pass runs rules one after another, and a
single full pass has taken 40 minutes on a Raspberry Pi, during which the rules behind it are idle
but not stuck. The Overview shows stale rules too, because the verdict is shared.

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
  "counts": {
    "rules": 3,
    "running": 3,
    "stopped": 0,
    "paused": 0,
    "stale": 0,
    "open_incidents": 0,
    "blocked_events": 0,
    "disconnected_accounts": 0
  },
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
- `rules[].name` is "source calendar → destination calendar" from the last known calendar names,
  falling back to "Unnamed calendar".
- `rules[].running` is the kind of running work (`preview`, `sync`, `reconciliation`, `removal`) or
  null.
- `rules[].problem` is null or `{ "kind": "stopped" | "review" | "waiting" | "stale", "summary" }`.
- `provider` is the account's Provider Kind (ADR 0022). Text never assumes Google.
- `incidents` lists open incidents only.

**Deliberately absent:** calendar IDs, connected account IDs and emails, event titles or any other
event content, Activity entries, blocked-event details, and token data. A test asserts the response
schema contains none of these fields.

## MCP server

`interfaces/mcp/` serves the Model Context Protocol at `/mcp` with the official `mcp` Python SDK:

- **Transport.** `FastMCP` streamable HTTP, stateless, with JSON responses. Stateless means no
  per-client session to keep in the single process.
- **Composition.** `create_app` mounts it before the API fallback and the Web UI catch-all, and the
  existing `lifespan` runs the SDK's session manager beside the scheduler. The MCP package calls
  `GetInstallationStatus` like the API does; it adds no port.
- **Authentication.** An ASGI wrapper applies the same bearer-token check as
  `require_status_reader`. Cookies are not accepted: MCP clients do not hold browser sessions. The
  SDK's OAuth authorization-server support is not used.
- **Tools**, each annotated `readOnlyHint: true`:
  - `get_status`: the Installation Status, identical to `/api/v1/status`.
  - `get_rule(rule)`: one rule by id or by its "Work → Personal" name, adding the last Sync Run's
    counts (created, updated, deleted, conflicts, drift, failure kind), the last reconciliation,
    and the rule's open incident. An unknown or ambiguous name is a tool error listing the rule
    names.
- **Instructions.** The server's instructions tell the agent what each status means, that
  Calendar Ghost is read-only through MCP, and what the administrator does for each problem:
  reauthorize in Settings, review blocked events in Activity, or wait for provider limits to clear.

Client setup, also shown in Settings:

```sh
claude mcp add --transport http calendar-ghost http://ghost.lan:8000/mcp \
  --header "Authorization: Bearer cgs_…"
```

```toml
# ~/.codex/config.toml
[mcp_servers.calendar-ghost]
url = "http://ghost.lan:8000/mcp"
bearer_token_env_var = "CALENDAR_GHOST_TOKEN"
```

The SDK is added to `dependencies` with a bounded version range. import-linter contracts gain
`interfaces/mcp` with the same rules as `interfaces/api`, and the `mcp` package may be imported
only inside `interfaces/mcp`.

## Testing

- **Application.** Table tests for every status, ported from `overview-health.test.ts`; stale at 59
  and 61 minutes, a running rule never stale, a rule with an open incident never stale, and a
  never-succeeded rule measured from its latest preview; `needs_attention` for each status; a running
  removal not counted as stopped.
- **Infrastructure.** SQLite tokens: issue, only the hash stored, authorize, revoke, the 5-minute
  `last_used_at` throttle, and the migration applied to an existing database.
- **API.**
  - `test_api_authorization.py` proves a valid token is refused by every route except
    `/api/v1/status`, and that token management requires the session.
  - Status with a cookie, with a token, with a revoked token, with a token in the query string.
  - The response contains no calendar ID, email, account ID, or event title for synthetic data
    that has all of them.
  - Logs captured during a request never contain the token.
- **MCP.** Through the SDK's client against the mounted app: tools listed and read-only, both tools
  return the expected data, `get_rule` by name and by id, unauthenticated and cookie-only requests
  rejected.
- **Frontend.** The Overview takes its tone from the server and still renders each tone's wording;
  Settings → Integrations issues, shows once, copies, and revokes.

## Documentation

- **ADR 0023**, "Integration Tokens, Installation Status, and MCP": the access model, why the
  dashboard API is not exposed to tokens, why `/health` stays liveness only, and why the badge is
  deferred.
- **`CONTEXT.md`.** Add Integration Token and Installation Status under Access and Health; Public
  Health Status gains a sentence that Installation Status is the authenticated counterpart.
- **`docs/self-hosting.md`.** A "Monitoring and agents" section: issuing a token, Uptime Kuma (JSON
  query `$.needs_attention` equals `false`), Homepage's custom API widget, Claude Code, and Codex.
- **`AGENTS.md`.** The security bullet names `/api/v1/status` and `/mcp` as the only routes that
  accept an Integration Token.
- **`CHANGELOG.md`.** One entry.

## Out of scope

- A status badge image.
- Write scopes and agent actions such as Sync Now or pausing a rule.
- Token expiry.
- Activity, event, or audit data through tokens or MCP.
