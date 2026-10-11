# Self-host Calendar Ghost

This guide deploys the Calendar Ghost Community Edition on infrastructure you control. The
Community Edition is one service: one SQLite database, one scheduler, and one application process,
for you alone or for the people you invite, each with private calendars and rules. It does not
require a Calendar Ghost account, hosted coordinator, telemetry, or subscription.

For the data inventory and deletion rules, read [Data ownership and privacy](data-ownership.md).
For deployment details and the LAN redirect options, read [Deployment](deployment.md).

## 1. Prepare the host

You need:

- Docker with Compose v2;
- durable storage for the Compose data volume;
- a host with a synchronized clock; and
- one or more Google or Microsoft accounts whose calendars you want to connect.

The supplied image targets `linux/amd64` and `linux/arm64`. Keep the installation on a trusted
machine or place it behind HTTPS before exposing it beyond your local network.

## 2. Register Calendar Ghost with your calendar providers

Register Calendar Ghost with Google, with Microsoft, or with both, depending on whose calendars you
will connect. A provider you do not register is not offered.

### Create a Google Cloud application

Each self-hosted installation should use its own Google Cloud project and OAuth client. Do not
copy another operator's client secret into your installation.

1. Open the [Google Cloud Console](https://console.cloud.google.com/), create or select a project,
   and open **APIs & Services → Library**.
2. Enable **Google Calendar API**. Google documents the general process in [Enable and manage
   APIs](https://developers.google.com/workspace/guides/enable-apis).
3. Open **Google Auth Platform → Branding** and configure the application name, support email,
   and contact information. Choose the audience deliberately:
   - **Internal** is for accounts in one Google Workspace organization.
   - **External** is for personal Google accounts or accounts from multiple organizations.
4. If Google Auth Platform shows a **Data access** or scopes page, add the scopes used by this
   application:

   ```text
   https://www.googleapis.com/auth/calendar.events
   https://www.googleapis.com/auth/calendar.calendarlist.readonly
   openid
   https://www.googleapis.com/auth/userinfo.profile
   ```

   The first scope allows Calendar Ghost to read and manage events selected by a rule. The second
   lets it list calendars and their access roles. The profile scopes identify a Connected Account
   in the local UI; they are not used to read calendar content. See Google's [Calendar API
   authorization guide](https://developers.google.com/workspace/calendar/api/auth) for the scope
   descriptions.
5. For an **External** app in testing, add every Google identity you will connect under **Test
   users**. Accounts that are not listed there cannot complete consent while the app is in testing.
6. Open **Google Auth Platform → Clients → Create client**, choose **Web application**, and copy
   the client ID and client secret.
7. Add this exact authorized redirect URI to the client:

   ```text
   http://localhost:8000/api/v1/oauth/google/callback
   ```

   The URI must match the value used by the installation exactly, including scheme, host, port,
   path, and trailing slash. Google's [web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server)
   explains the client and redirect-URI requirements. Keep the client secret out of source
   control and out of screenshots.

#### External-app testing and verification

Testing is suitable for initial setup and short-lived development only. For a long-running
self-hosted installation, move the OAuth consent screen's publishing status to **In production**
before connecting calendars. Google says refresh tokens issued to an External app in **Testing**
expire after seven days unless the app requests only basic profile scopes; Calendar Ghost requests
Calendar scopes, so scheduled synchronization can stop after seven days until the account is
reauthorized. See Google's [refresh-token expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

While the app is in testing, every connected identity must be listed as a test user, and Google
may show a testing or unverified-app warning during consent. A future public hosted service is a
separate OAuth product and may need its own Google verification and production-audience process; do
not reuse one operator's self-hosted credentials for it.

### Register a Microsoft Entra application

Skip this if nobody will connect a Microsoft account. Each installation registers its own
application; do not copy another operator's client secret into your installation. Calendar Ghost
reaches Outlook calendars through Microsoft Graph, for Microsoft 365 work or school accounts and for
personal Outlook.com accounts.

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com/) with an account that
   may register applications in a directory, and open **Entra ID → App registrations → New
   registration**. Microsoft's [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
   quickstart explains who may register one.
2. Enter a name, such as `Calendar Ghost`, and choose **Supported account types**:
   - **Accounts in any organizational directory and personal Microsoft accounts** lets both work or
     school accounts and Outlook.com accounts connect. Keep `CALENDAR_SYNC_MICROSOFT_TENANT=common`.
   - **Accounts in this organizational directory only** lets only your organization's accounts
     connect. Set `CALENDAR_SYNC_MICROSOFT_TENANT` to the **Directory (tenant) ID** from the
     application's **Overview**.
   - **Personal Microsoft accounts only** lets only Outlook.com accounts connect. Set
     `CALENDAR_SYNC_MICROSOFT_TENANT=consumers`.
3. Under **Redirect URI**, choose the **Web** platform and enter this exact address, then choose
   **Register**:

   ```text
   http://localhost:8000/api/v1/oauth/microsoft/callback
   ```

   Like Google, Microsoft accepts plain HTTP only for `localhost`; for another host, register an
   HTTPS address ([5. Use a LAN host or HTTPS](#5-use-a-lan-host-or-https)). More addresses can be
   added later under **Authentication**.
4. On the application's **Overview**, copy the **Application (client) ID**.
5. Open **API permissions → Add a permission → Microsoft Graph → Delegated permissions** and add
   these, keeping **User.Read**, which is there already:

   ```text
   openid
   email
   offline_access
   User.Read
   Calendars.ReadWrite
   ```

   `Calendars.ReadWrite` lets Calendar Ghost read the events a rule selects and manage the events it
   writes; `offline_access` keeps synchronizing while nobody is signed in; the others identify the
   Connected Account. Add no application permissions and no `Calendars.ReadWrite.Shared`. None of
   these needs an administrator's consent, but an organization may allow only its IT administrator
   to approve applications: they then choose **Grant admin consent** on this page.
6. Open **Certificates & secrets → Client secrets → New client secret**, enter a description, and
   choose when it expires. The admin center recommends 180 days; the longest is 24 months. Copy the
   secret's **Value** at once, since it is shown only this one time, and not its **Secret ID**.
   Keep it out of source control and out of screenshots.
7. Write down the secret's **Expires** date and set yourself a reminder before it. Calendar Ghost
   cannot read the date, and does not warn you before the secret expires.

To rotate the secret before it expires:

1. Create a new client secret as in step 6, leaving the old one in place.
2. Put the new **Value** in `.env` as `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET` and run
   `docker compose up -d`.
3. Wait about two hours, so that every access token issued before the change has expired and has
   been renewed with the new secret. If **People** shows nothing that needs you, delete the old
   secret in **Certificates & secrets**.

Nobody needs to reauthorize: grants belong to the application, not to one secret. If a secret
expires first, every Microsoft account stops at once with the likely cause "Microsoft no longer
accepts this installation's OAuth client";
[the fix](troubleshooting.md#microsoft-no-longer-accepts-the-oauth-client) is the same rotation.

## 3. Configure the installation

From the Calendar Ghost checkout, copy the example environment file:

```sh
cp .env.example .env
```

Generate a fresh 256-bit installation master key:

```sh
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

Set these values in `.env`:

```dotenv
CALENDAR_SYNC_MASTER_KEY=PASTE_GENERATED_KEY_HERE
CALENDAR_SYNC_GOOGLE_CLIENT_ID=PASTE_GOOGLE_CLIENT_ID_HERE
CALENDAR_SYNC_GOOGLE_CLIENT_SECRET=PASTE_GOOGLE_CLIENT_SECRET_HERE
CALENDAR_SYNC_GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/oauth/google/callback
# Only if you registered a Microsoft Entra application:
CALENDAR_SYNC_MICROSOFT_CLIENT_ID=PASTE_APPLICATION_CLIENT_ID_HERE
CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET=PASTE_CLIENT_SECRET_VALUE_HERE
CALENDAR_SYNC_MICROSOFT_REDIRECT_URI=http://localhost:8000/api/v1/oauth/microsoft/callback
CALENDAR_SYNC_MICROSOFT_TENANT=common
# Optional: make the UI's Source link point to the exact checkout being built.
# CALENDAR_GHOST_SOURCE_URL=https://github.com/DannieBGoode/calendar-ghost/tree/<commit-or-tag>
```

Leave out the lines of a provider you did not register. The master key encrypts stored Google and
Microsoft credentials and seals sensitive event-history values. Back it
up separately from the database. Never commit `.env`, replace the master key on an existing
installation, or paste either secret into an issue. Losing the key makes encrypted credentials and
sealed history unreadable.

## 4. Start and complete first-run setup

Start the one-process service:

```sh
docker compose up -d --build
curl --fail http://localhost:8000/health
```

Open <http://localhost:8000> and create the administrator with your email and a password of at
least 12 characters. Then:

1. Connect each Google or Microsoft identity. The browser must be able to return to the configured
   redirect URI after the provider's consent.
2. Create a Directional Sync Rule with one Source Calendar and one Destination Calendar.
3. Keep the default Busy-Only Projection unless you have a reason to expose more detail.
4. Preview the rule, inspect the decisions, and enable it.
5. Check **Activity** after the first run and confirm that the destination contains only the
   projections you intended.

Check **Settings → Connections → Connected accounts** if a calendar is missing. The access check
uses read-only requests and reports which calendars can be used as destinations.

### Invite other people

A new installation is for you alone: its Registration Policy is **Only me**, so nobody else can
join and the app shows nothing about other people. To share it with your household:

1. Open **Settings → Administration → Who can join** and choose **Invitation only**. A **People**
   page appears in the main navigation.
2. On **People**, choose **Invite someone** and pass the link on yourself. It works once and expires
   after 7 days; the person chooses their own email and password.
3. Everyone's calendar accounts, rules, Activity, and tokens are their own. As the administrator you
   see each person's email, role, whether they may sign in, when they joined, and when they last
   signed in, never their calendars or events. Search by part of an email, filter by role or
   state, sort by email, joining, or last sign-in, and page through 50 people at a time; the
   address keeps your choices, so a reload or a shared link shows the same list.

From **People** you can also make someone an administrator, disable someone, which signs them out
and holds their rules until you enable them again, create a password reset link for someone who
forgot theirs, or delete someone. Deleting someone deletes their sign-in, rules, calendar connections,
tokens, and Activity, and the events their rules wrote wherever Calendar Ghost can still reach
them; their own events and their Google and Microsoft accounts stay as they are. While anyone else remains, the
installation keeps one administrator who can sign in, so the last administrator must make someone
else an administrator before deleting their own account. You may return to **Only me** once you are
the only person again. Anyone can change their own email and password, turn their incident emails
off, or delete their own account under **Settings → Your account**, choosing whether the events
their rules wrote are deleted too. When the last person deletes
their own account, Calendar Ghost returns to setup: the next person to open it creates the
administrator, as on a new installation, and the OAuth settings and master key in `.env`
stay as they were.

## 5. Use a LAN host or HTTPS

Google and Microsoft accept plain HTTP OAuth redirects for `localhost`, but not for a private LAN
IP or a `.local` hostname. For a Raspberry Pi or home server, use either:

- an SSH tunnel while connecting accounts, while keeping the default `localhost` redirect; or
- an HTTPS hostname, such as a private tailnet name or a domain behind a reverse proxy.

For HTTPS, register the exact URL and set matching values, for example:

```dotenv
CALENDAR_SYNC_GOOGLE_REDIRECT_URI=https://calendar.example.test/api/v1/oauth/google/callback
CALENDAR_SYNC_MICROSOFT_REDIRECT_URI=https://calendar.example.test/api/v1/oauth/microsoft/callback
CALENDAR_SYNC_SECURE_COOKIES=true
```

Do not expose the service directly to the public internet. See [Google OAuth redirect URI on a
LAN host](deployment.md#google-oauth-redirect-uri-on-a-lan-host) for the tunnel and reverse-proxy
options.

## 6. Connect monitors and agents

Installation Status is the authenticated counterpart to `/health`: it reports which of your rules
are running, which are stopped and why, whether the scheduler itself is still running passes, and
one overall verdict, through `GET /api/v1/status` and an MCP server at `/mcp`. Both require an
Integration Token, a credential you issue in **Settings → Connections → Integrations** for one
monitor, dashboard, or agent at a time. A token belongs to the person who issued it and reads only
their status.

As an administrator, you may also let a token read Installation Health at
`GET /api/v1/installation/health`: incidents about the installation itself, such as a stalled
scheduler, and how many people are in each status. It names no rule, calendar, or person, which
makes it the right answer for a monitor that watches the installation for everyone. Tick **Also
read Installation Health** when you issue the token; it stops working there if you stop being an
administrator.

A token only reads status, and plain HTTP on this machine or your home network is normal for a
homelab: anyone on that network could read a token sent to it, and nothing more. Before you use a
token from outside your home network, put the installation behind HTTPS (see
[5. Use a LAN host or HTTPS](#5-use-a-lan-host-or-https)), for example with Tailscale Serve or a
reverse proxy. Settings notes this in the Integrations group only when it is open at an address
that would carry a token across the internet unencrypted. A reverse proxy configured to log request headers will
record the token in its own logs the same as it would record a session cookie, so review a proxy's
logging configuration before relying on it.

To issue a token:

1. Open **Settings → Connections → Integrations** and choose **Show**. The group stays collapsed to
   one line, such as "2 tokens · last used 3 minutes ago", until you open it.
2. Under **Issue a token**, name the tool that will use it, for example "Uptime Kuma", and choose
   **Issue token**.
3. Copy the token, then choose **Done**. It is shown only once. If you lose it, issue a new one and
   revoke the old one.

Each token row says when it was issued and last used, so you can tell which ones are still in use.
**Revoke** cuts a token off immediately; revoked tokens move under one disclosure at the end of the
group. **Examples for monitors and AI assistants**, at the foot of the group, repeats the setups
below, filled in with the address you opened Settings at.

Check a token from any machine that will use it:

```sh
curl -H "Authorization: Bearer $CALENDAR_GHOST_TOKEN" https://ghost.example.lan/api/v1/status
```

A healthy installation answers like this (shortened):

```json
{
  "status": "healthy",
  "needs_attention": false,
  "summary": "2 rules running.",
  "last_synced_at": "2026-10-04T09:58:00+00:00",
  "scheduler": { "configured": true, "last_pass_completed_at": "2026-10-04T09:58:00+00:00", "current_pass_started_at": null },
  "counts": { "rules": 2, "running": 2, "stopped": 0, "paused": 0, "overdue": 0, "open_incidents": 0, "blocked_events": 0, "disconnected_accounts": 0 },
  "problems": [],
  "rules": [{ "id": "…", "name": "Work → Family", "state": "enabled", "last_succeeded_at": "…", "problem": null }],
  "incidents": []
}
```

- `status` is the one verdict, explained in the table below. Alert on `needs_attention`: it is
  `true` only for `stalled`, `stopped`, and `review`.
- `summary` is one sentence for a dashboard tile.
- `problems` lists every current problem, most urgent first, each with a `kind` (`stalled`,
  `stopped`, `review`, `overdue`, `blocked`, or `waiting`), the rule it concerns, and a summary.
  A problem that an Incident explains also has a `message`: the same summary as a stable `code`
  and `params`, such as `{"code": "provider_failure", "params": {"kind": "rate_limit",
  "provider": "google"}}`. Every other problem has `"message": null`. Match on `code`, not on the
  English summary, which can change between releases.
- `incidents` lists the open Incidents with their English `summary`; its entries carry no
  `message`.
- `rules` names each rule by its calendars. A calendar with no name, or whose name is an email
  address or its calendar ID, appears as "Unnamed calendar", so status never reveals one.
- The answer never contains event content, calendar IDs, account emails, or token data.

Use only the `Authorization` header. A token in the address, such as `?token=`, is refused, so it
never lands in browser history or access logs.

**Uptime Kuma.** Add an **HTTP(s) - Json Query** monitor:

```text
URL: https://ghost.example.lan/api/v1/status
Headers: {"Authorization": "Bearer <token>"}
Json Query: $.needs_attention
Expected Value: false
```

**Homepage.** Add a `customapi` widget to the Calendar Ghost service:

```yaml
widget:
  type: customapi
  url: https://ghost.example.lan/api/v1/status
  headers:
    Authorization: Bearer {{HOMEPAGE_VAR_CALENDAR_GHOST_TOKEN}}
  mappings:
    - field: status
      label: Status
    - field: summary
      label: Summary
```

**Claude Code.** Keep the token in an environment variable rather than typing it into a command
line:

```sh
export CALENDAR_GHOST_TOKEN=cgs_…   # from a password manager or shell profile
claude mcp add --transport http calendar-ghost https://ghost.example.lan/mcp \
  --header "Authorization: Bearer ${CALENDAR_GHOST_TOKEN}"
```

**Codex.** Add to `~/.codex/config.toml` and set `CALENDAR_GHOST_TOKEN` in the environment Codex
runs in:

```toml
[mcp_servers.calendar-ghost]
url = "https://ghost.example.lan/mcp"
bearer_token_env_var = "CALENDAR_GHOST_TOKEN"
```

The same entry can be added with one command:

```sh
codex mcp add calendar-ghost --url https://ghost.example.lan/mcp \
  --bearer-token-env-var CALENDAR_GHOST_TOKEN
```

**Claude Desktop and other apps.** Apps that only start MCP servers on your own computer connect
through the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge, which needs Node.js on
that computer. In Claude Desktop, open **Settings → Developer → Edit Config**, add this to
`claude_desktop_config.json`, and restart Claude Desktop:

```json
{
  "mcpServers": {
    "calendar-ghost": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://ghost.example.lan/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "Bearer <token>" }
    }
  }
}
```

Keep `Authorization:${AUTH_HEADER}` exactly as written, with no spaces around the colon;
`mcp-remote` fills in the token from `env`. If the address starts with `http://` and is not
`localhost`, add `"--allow-http"` after the address. Settings shows this example already filled in
for the address you opened it at. An app whose connector settings accept only an address, or only
an OAuth sign-in, cannot send a token directly; connect it through this bridge if it can run local
MCP servers.

Both `/api/v1/status` and `/mcp` answer the same verdict. Each status means:

| Status | What it means | What to do |
| --- | --- | --- |
| `stalled` | Rules are enabled, but the scheduler is not running passes | Restart the service |
| `stopped` | A rule is suspended, usually because a calendar account lost access | Reauthorize the account in Settings |
| `review` | An incident, blocked events, or a rule not synced in over a day needs a look | Open Activity or the named rule |
| `waiting` | A calendar provider is limiting or failing requests | Nothing yet; it retries by itself |
| `paused` | Rules exist and have synced before, but none is enabled | Nothing, unless you meant to resume one |
| `setup` | No account or rule yet, or none has synced | Finish connecting an account and creating a rule |
| `healthy` | Every enabled rule is running and up to date | Nothing |

**Other MCP clients.** Any client that speaks MCP over streamable HTTP and can send an
`Authorization: Bearer` header works: point it at `https://<your address>/mcp`. The server is
stateless and answers `POST` only. Calendar Ghost has no OAuth sign-in for MCP; a client that looks
for one gets `404` and should then use the token you configured. Claude Code, Codex, and Claude
Code through `mcp-remote` were each checked against a running installation with this release.

The MCP server offers three read-only tools, and explains each status to the agent itself:

- `get_status` returns the same answer as `/api/v1/status`.
- `get_rule` takes a rule id or its "Source → Destination" name and adds the rule's last
  synchronization and reconciliation outcome: when it ran, whether it succeeded, and how many events
  it created, updated, deleted, or found in conflict.
- `get_installation_health` returns the same answer as `/api/v1/installation/health`, for an
  administrator's token with Installation Health.

Ask the agent in plain words, for example "Is my calendar sync healthy?", "Why did Work → Family
stop?", or "When did each rule last sync?". Calendar Ghost never changes a rule or a calendar through
an Integration Token.

If a monitor or agent cannot connect, see [Troubleshooting](troubleshooting.md#a-monitor-or-agent-cannot-read-status).

## 7. Back up, upgrade, and recover

Before an upgrade or host migration:

- stop the service or use a snapshot that guarantees a consistent SQLite backup;
- back up the data volume, the installation master key, and the protected `.env` settings;
- record the image or source version; and
- keep the previous backup and version until the new installation passes `/health` and Activity
  checks.

For a checkout-based installation, update the source and rebuild:

Before building, set `CALENDAR_GHOST_SOURCE_URL` in `.env` to the immutable commit or release tag
URL for that checkout. Docker builds use that value to make the UI's **Source** link identify the
corresponding source; if it is unset, the link falls back to the upstream `main` tree.

```sh
docker compose up -d --build
```

Do not run `docker compose down -v` as an upgrade step: removing the named volume removes the local
database, mappings, and connected-account state. The full backup and restore procedure is in
[Data ownership and privacy](data-ownership.md#backups-and-recovery).

## 8. Troubleshooting

Inspect service status and logs without exposing secrets:

```sh
docker compose ps
docker compose logs --tail=100 app
curl --fail http://localhost:8000/health
```

- **`redirect_uri_mismatch`:** the URI in Google Cloud and `CALENDAR_SYNC_GOOGLE_REDIRECT_URI`
  differ. Compare scheme, hostname, port, path, and trailing slash character by character.
- **Test-user or access warning:** add the Google identity under the External app's **Test users**
  list, then restart the consent flow.
- **`AADSTS50011` or another `AADSTS` page from Microsoft:** see [Microsoft sign-in stops with an
  error](troubleshooting.md#microsoft-sign-in-stops-with-an-error).
- **The app cannot decrypt connected accounts:** restore the original installation master key;
  do not generate a replacement.
- **A LAN callback cannot load:** use the SSH tunnel or configure HTTPS as described above. The
  redirect is followed by the browser, so the callback address must reach the Calendar Ghost host
  from that browser.

If a synchronization decision is blocked, use the authenticated **Activity** view and the rule
details page before changing calendars or deleting data. Ownership checks are intentionally
conservative.
