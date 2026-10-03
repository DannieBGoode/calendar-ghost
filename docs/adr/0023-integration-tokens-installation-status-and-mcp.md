# Integration Tokens, Installation Status, and MCP

## Context

`/health` reports only that the process is running. Everything else, including whether a rule is
stopped or an account needs reauthorization, requires the administrator session cookie that no
monitor or agent can obtain. The Overview computed its verdict in the browser from the dashboard
API, so no server endpoint gave the same answer, and nothing at all noticed a scheduler that had
stopped running passes while the process itself stayed up and kept answering `/health`.

Administrators asked for three things that share one answer: AI agents such as Claude Code and
Codex that should say whether synchronization is healthy and what to do if not; uptime monitors
such as Uptime Kuma that should alert when it needs attention; and homelab dashboards such as
Homepage that show one tile per service.

## Decision

- **Integration Tokens.** A named, delegated administrator credential: `cgs_` followed by 43
  characters of URL-safe base64 (32 random bytes). Only its SHA-256 hash is stored; the plaintext
  is shown once, when issued, and never again. It carries one scope, `status:read`, and does not
  expire: monitors need long-lived credentials, and silent expiry would break them unannounced.
  Tokens are accepted only in the `Authorization` header, as `Bearer cgs_…`, never in a query
  string, so they stay out of browser history, `Referer` headers, and ordinary access logs.
  Settings → Integrations issues and revokes them; only an administrator session can manage tokens,
  and a token can never list, issue, or revoke one.
- **One function decides access for both routes.** `status_access` in `interfaces/access.py` is
  the single place that decides whether `/api/v1/status` or `/mcp` may answer a request. When an
  `Authorization` header is present, it decides alone: a missing scheme, a malformed token, or an
  unknown or revoked one is refused even when a valid session cookie accompanies it, so a broken
  monitor credential is never hidden behind a browser session that happens to be open. Only when
  no header is present does a session cookie get a chance, and only for `/api/v1/status`; `/mcp`
  never accepts a cookie, because MCP clients do not hold browser sessions. Every refusal builds a
  fresh `HTTPException`, so repeated failures never share one growing traceback.
- **`GET /api/v1/status` as its own contract, not tokens on the dashboard API.** The dashboard API
  returns calendar IDs, which are often email addresses, account details, and event titles under
  Activity. A dedicated, narrower, and stable contract is safer than an allowlist over routes built
  for the Web UI. The response never includes calendar IDs, connected-account IDs or emails, event
  content, or token data; a calendar name that is missing, equal to its own calendar ID, or
  containing `@` is replaced with "Unnamed calendar", because Google stores `summary or id` as a
  calendar's name and a primary calendar's summary defaults to the account's email address.
- **The server owns the verdict.** `GetInstallationStatus` in `application/status.py` is the one
  place that classifies the installation's health from the rules, their latest run outcomes, open
  incidents, open blocks, connected-account state, and the scheduler heartbeat. The Overview,
  `/api/v1/status`, and MCP's `get_status` tool all render the same `InstallationStatus`; the
  Overview no longer derives tone or problem order from the dashboard payload itself. The Overview
  takes its tone from the server's status even when the client's own per-rule problem list has not
  caught up yet, such as between one dashboard poll and the next: a generic hero for that tone
  still tells the truth instead of contradicting it with healthy, paused, or setup copy.
- **The scheduler reports its own heartbeat.** `SchedulerHeartbeat` in `application/ports.py`
  exposes when the current pass started, if one is running, and when the last pass completed
  without raising. With enabled rules and no scheduler available at all, such as when no
  installation master key is configured, the status is `stalled`: a dead process already fails
  `/health`, so this is reserved for a live process whose scheduler is not doing its job. The status
  is also `stalled` when no pass has completed within 15 minutes (three scheduler intervals),
  counted from process start before the first pass, or when a running pass started more than 3
  hours ago; a full pass took 40 minutes on a Raspberry Pi, so 3 hours is far beyond a slow pass. A
  pass that raises does not count as completed, so repeated failing passes also become `stalled`
  within 15 minutes.
- **Overdue rules, at 24 hours.** Beneath a healthy scheduler, an enabled rule that has succeeded
  before, has no running work, and whose last successful run is more than 24 hours old is
  `overdue`. A rule is excluded from being counted overdue when it already has any other problem,
  such as a stopped or reviewed incident, because that problem already explains why it has not
  synced; a rule that has never succeeded is never overdue, since no reliable start time exists to
  measure it from.
- **Provider waits escalate after 24 hours.** A rate-limit or temporary provider incident is
  `waiting` while it is under 24 hours old, because it retries by itself and nothing needs doing.
  Past 24 hours it becomes `review`, so a monitor alerts on an outage that is not clearing on its
  own. When a rule has several open incidents, the one still worth reviewing outranks one that is
  merely waiting, regardless of which happened to open first. A blocked (conflict) incident is
  covered by a rule's `overdue`/`review`/`stopped` problem only when an open block already exists
  for that same rule; an incident in the `conflict` category with no matching open block is treated
  like any other.
- **MCP at `/mcp`, stateless JSON, POST only, bearer only.** `interfaces/mcp/server.py` builds the
  official `mcp` Python SDK's server once per application lifespan, inside the existing `lifespan`
  beside the scheduler, because the SDK's session manager runs only once and tests start the same
  app more than once; a mounted app's own lifespan never runs, so the application lifespan owns it
  instead. An ASGI wrapper, `McpGate`, calls the shared `status_access` function with cookies
  disabled before the SDK ever sees the request, and refuses with 401 for missing or invalid
  credentials and 403 for the wrong scope. Only `POST` is accepted; every other method on `/mcp`
  answers 405, because stateless mode has no stream to resume and a `GET` would hold one open. A
  path below `/mcp`, such as `/mcp/anything`, answers 404 rather than falling through to the Web
  UI's catch-all. The SDK's DNS-rebinding Host allowlist, which by default restricts requests to
  `localhost`, is turned off: that protection exists for unauthenticated local servers that a
  hostile page could redirect a browser to, but every request here carries a bearer token a
  rebinding page cannot supply, so the allowlist would only refuse a legitimate LAN hostname such as
  `ghost.lan` for no safety gain.
- **`/health` stays liveness only.** It is still the only unauthenticated operational status route,
  used by the Docker `HEALTHCHECK`. Teaching it to report rule health would make a container
  restart over an expired Google authorization, which fixes nothing.

## Alternatives considered

- **Tokens on the existing dashboard API.** Rejected: that API is shaped for the Web UI and already
  returns calendar IDs, account details, and event titles. Narrowing it with an allowlist would
  need constant vigilance as the dashboard grows; a dedicated contract is safer and more stable.
- **A status badge image.** Rejected for v1: every listed consumer can send an `Authorization`
  header and read JSON. A badge is useful only to image-only dashboards, and it is the one consumer
  that would need either unauthenticated status or a token carried in a URL, which this design
  otherwise avoids entirely. It stays a possible later addition.
- **A stdio MCP command.** Rejected: agents normally run on a different machine than the homelab
  server. A remote MCP endpoint over HTTP needs nothing installed on the agent's machine; a stdio
  command would need the binary, its dependencies, and network access to the installation
  replicated on every client.
- **A separate summary-only scope.** Rejected: an Integration Token may already read rule names and
  incident summaries, and the administrator issues each token to their own tool knowingly. A second,
  more restricted scope would add a choice nobody has asked for; any future scope, such as one
  letting an agent act on rules, needs its own design review and threat model, and existing tokens
  never gain it implicitly.
- **An in-memory heartbeat with no process-start baseline.** Rejected: without counting from process
  start, a freshly started service with enabled rules would read `stalled` until the first pass
  completed, which is correct, but a definition that instead treated "no pass yet" as healthy would
  hide a scheduler that failed to start at all. Counting from process start keeps both cases
  distinguishable.

## Consequences

- The application gains a new direct dependency, `mcp` (pinned `>=2.3,<3`), which in turn pulls in
  `httpx2`, `pyjwt`, and their own dependencies. `docker compose build` must install them, and the
  image grows accordingly.
- Any future scope beyond `status:read` needs its own design review and threat model before it
  ships; existing tokens never gain a new scope implicitly.
- A reverse proxy configured to log request headers will record Integration Tokens, the same as it
  would record a session cookie. The self-hosting guide says so, and recommends HTTPS before a
  token is issued.
- `import-linter` gains an `interfaces/mcp` contract mirroring `interfaces/api`, and the `mcp`
  package may be imported only inside `interfaces/mcp`, so the dependency cannot leak into
  provider-neutral or domain code.
