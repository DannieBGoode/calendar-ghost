# Instant Sync

Instant Sync runs a rule soon after Google or Microsoft reports that something changed in its
Source Calendar, instead of waiting for the next Scheduled Sync. It is optional. Without it, every
rule still syncs every five minutes, and nothing else changes.

## What it does, and what it does not promise

- When a provider reports a change, Calendar Ghost waits until 10 seconds pass without another
  report for the same rule, and at most 30 seconds after the first, then runs each rule whose
  Source Calendar the report may concern. The run is an ordinary sync: it reads both calendars'
  changes, writes only what differs, and records it in **Activity**.
- A rule runs from Instant Sync at most once every 30 seconds. Up to two such runs happen at once,
  beside the scheduler's four, so neither kind waits behind the other.
- There is no promise from the moment of your edit. Google usually reports within seconds.
  Microsoft does not publish how fast it reports. A report can be late, and Google drops a small
  share of them in normal operation.
- Scheduled Sync every five minutes and the daily full pass keep running. A lost report delays a
  change by at most five minutes, as before.
- Only Source Calendars are watched. An edit made directly in a Destination Calendar is still put
  back by the next Scheduled Sync.
- A rule whose last run failed waits for Scheduled Sync, which retries it with its own backoff,
  until a run succeeds.

## Requirements

- **A public `https` address with a valid certificate**, at the root of its host, set as
  `CALENDAR_SYNC_PUBLIC_URL`, such as `https://calendar.example.com`. Google and Microsoft send
  reports only to `https`. A plain `http` address, a self-signed certificate, or a name that only
  your network resolves cannot receive them.
- **Google and Microsoft must reach `POST /api/v1/watch-notices/` at that address from the
  internet.** Nothing else needs to be public: you may forward only this path and keep the rest of
  Calendar Ghost on your network.
- **A reverse proxy or tunnel that forwards that path unchanged**: its query string, headers, and
  body. Microsoft checks the address with a `validationToken` query parameter and sends JSON
  bodies; Google sends `X-Goog-*` headers. Calendar Ghost refuses bodies above 64 KB.
- **No sign-in gate or bot challenge on that path.** Providers cannot pass Cloudflare Access, a
  proxy's password prompt, or a browser check. Each report carries a secret token that Calendar
  Ghost checks; a request without a matching one changes nothing.
- **The Installation Master Key**, which connecting calendar accounts already needs.

Tailscale Serve keeps a name inside your tailnet, so providers cannot reach it. Tailscale Funnel
publishes a name to the internet.

If you forward only the notices path and also use `CALENDAR_SYNC_PUBLIC_URL` for incident email
links, those links open only where that address reaches the whole Web UI, such as on your own
network.

### Forward the notices path

**Caddy** obtains and renews the certificate itself. To forward only the notices path:

```text
calendar.example.com {
	handle /api/v1/watch-notices/* {
		reverse_proxy 127.0.0.1:8000
	}
	respond 404
}
```

To serve the whole Web UI at the same name, use `reverse_proxy 127.0.0.1:8000` alone, and set
`CALENDAR_SYNC_SECURE_COOKIES=true`.

**nginx**, with a certificate from Let's Encrypt or another public authority:

```nginx
server {
    listen 443 ssl;
    server_name calendar.example.com;
    ssl_certificate     /etc/letsencrypt/live/calendar.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/calendar.example.com/privkey.pem;

    location /api/v1/watch-notices/ {
        # No path after the address, so nginx passes the path and query string unchanged.
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 64k;
    }

    location / {
        return 404;
    }
}
```

**Cloudflare Tunnel** needs no open port on your router, which suits a Raspberry Pi at home.
Create a named tunnel, route the name to it, and forward only the notices path in
`/etc/cloudflared/config.yml`:

```sh
cloudflared tunnel create calendar-ghost
cloudflared tunnel route dns calendar-ghost calendar.example.com
```

```yaml
tunnel: <tunnel-uuid>
credentials-file: /etc/cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: calendar.example.com
    path: ^/api/v1/watch-notices/
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Run it with `cloudflared tunnel run calendar-ghost`, or install it as a service with
`cloudflared service install`. If Cloudflare Access protects the name, add a Bypass policy for
`/api/v1/watch-notices/`. A quick tunnel (`cloudflared tunnel --url http://127.0.0.1:8000`) works
for a test, but its address changes each time it starts.

## Turn it on

1. Forward the notices path as above.
2. Set `CALENDAR_SYNC_PUBLIC_URL=https://calendar.example.com` in `.env` and run
   `docker compose up -d`.
3. Check the path from outside your network, as
   [Providers cannot reach the installation](#providers-cannot-reach-the-installation) shows.
4. Instant sync is on for each person by default, under **Settings → Your account**. Within five
   minutes, Calendar Ghost asks Google or Microsoft to report changes for the Source Calendar of
   each enabled rule.

There is no other setting. Changing the address later moves every watch to the new one within
five minutes: Calendar Ghost asks for new registrations at the new address and stops those at the
old one. A registration whose stop fails expires with its provider within about 7 days.

Unsetting `CALENDAR_SYNC_PUBLIC_URL`, or changing it to plain `http`, turns Instant Sync off, and
incident emails then come without a link (with plain `http`, they keep it). Calendar Ghost then
stops nothing: registrations already made expire with their providers within about 7 days, and
the reports they bring until then are answered `404` and change nothing.

## Check that it works

1. Open a rule. **When it syncs** says **Syncs instantly** once its provider confirmed it will
   report changes. Google confirms with its first report, usually within seconds; Microsoft
   confirms when it accepts the request, because it checks the address first. Until then it says
   **Syncs every 5 minutes** with [Waiting for the provider](#waiting-for-the-provider).
2. Edit an event in the rule's Source Calendar. **Activity** usually lists the change within a
   minute.
3. If the **Instant sync** switch under **Settings → Your account** is off with a reason, its
   **Learn why** link opens the matching section below. Administrators also see the cause on
   **People** under **Installation health**.

## When Instant Sync is unavailable

Each section below is the one the switch or a rule links to. Meanwhile rules sync every five
minutes, and nothing is lost.

### Not in your plan

Plans arrive in a later release. Once an administrator turns them on, each person's Plan decides
whether it includes Instant Sync and how often Scheduled Sync runs, and only an administrator can
change your Plan. With Plans off, which is the default, everyone has Instant Sync.

### No public HTTPS address

`CALENDAR_SYNC_PUBLIC_URL` is unset, is not at the root of its host, or uses plain `http`. Forward
the notices path through HTTPS as in [Requirements](#requirements), set the address, and restart.
An administrator sees the same on **People** when the address uses plain `http` at a host the
internet reaches ([troubleshooting](troubleshooting.md#instant-sync-needs-an-https-public-address)).

### Providers cannot reach the installation

Every provider your rules read from failed to reach the installation: Google did not deliver its
first report within 2 minutes of a new watch, or the provider refused the address when Calendar
Ghost asked it to report changes. Check the path from a machine outside your network:

```sh
curl -i -X POST https://calendar.example.com/api/v1/watch-notices/google/00000000000000000000000000000000 \
  -H 'X-Goog-Channel-ID: 00000000000000000000000000000000' \
  -H 'X-Goog-Channel-Token: reachability-check' \
  -H 'X-Goog-Resource-ID: reachability-check' \
  -H 'X-Goog-Resource-State: exists'
```

Calendar Ghost answers `202 Accepted` and changes nothing, because no registration has that
identifier. A `404` in JSON comes from Calendar Ghost when its `CALENDAR_SYNC_PUBLIC_URL` is not an
`https` address, as it then has no notices route. Anything else comes from the proxy or tunnel:
fix it as [troubleshooting](troubleshooting.md#calendar-providers-cannot-reach-the-installation)
explains. Once a report arrives, the switch works again. An authenticated report always counts as
proof that delivery works, so a rule never waits on this check.

### Waiting for the provider

The rule's watch exists, but its provider has not confirmed it yet. This usually lasts seconds. It
lasts longer when:

- the provider is refusing or limiting requests for now: Calendar Ghost tries again later, waiting
  longer after each failure, at most a day;
- Google will not watch the calendar, as with some calendars Google publishes itself: Calendar
  Ghost tries again later in the same way;
- two people here connected the same Microsoft account: Microsoft lets one application watch a
  mailbox only once, so only one of them gets Instant Sync for it, and the other's rules sync on
  their schedule and are tried again daily; or
- the account needs reauthorization, which its rules already say.

### This calendar cannot be watched

Its provider cannot report changes in this calendar to Calendar Ghost. Microsoft reports changes
only for the signed-in person's own mailbox, so a calendar shared from another mailbox cannot be
watched. Calendar Ghost asks again once a day. Its rules sync every five minutes.

### You turned it off

Turn **Instant sync** on again under **Settings → Your account**.

## Privacy

- Reports carry no event content. Google's says only which watch it concerns and that something
  changed. Microsoft's names the changed event's identifier, which Calendar Ghost ignores: it reads
  only which registration a report concerns, its secret token, and what kind of report it is, then
  runs the rule, which reads the calendars as any sync does.
- Calendar Ghost stores, per watch, the Connected Account, what it covers (one Google calendar or
  one Microsoft mailbox) and which Source Calendars it covers; per registration, the provider's
  handle, a SHA-256 hash of its secret token, the address it points at, its state, and its times;
  per rule, counters of requested and handled runs and when they happened; and per provider and
  public address, when a report last arrived and when delivery last failed.
- Logs never contain tokens, handles, registration identifiers, or report bodies. Uvicorn's request
  lines show the notices path without its registration or query.
- Google and Microsoft learn the public address, and which calendars or mailboxes Calendar Ghost
  watches, which they already know.
- The notices path takes no session, so anyone can send a request to it. Calendar Ghost answers
  every one alike and acts only on one whose registration and secret token match.

## Cost per run

A run from Instant Sync is an ordinary incremental run, so it costs what any run costs
([the synchronization model](sync-model.md#cost-of-a-run)): with nothing to do, the incremental
listings of both calendars, and for each changed event the reads and writes it needs. It comes on
top of Scheduled Sync, which still runs every rule every five minutes, so each burst of changes in
a Source Calendar costs one more run of each rule it wakes, at most one every 30 seconds per rule.
For Outlook, the wakes described below add runs with nothing to do. Keeping watches costs a few
calls per account and calendar each week: each registration lasts at most 7 days and is renewed in
the last third of its life. Google replaces each channel (one call to create the new one, one to
stop the old), and Microsoft renews each subscription in place. Every call counts among each
person's calls to calendar providers on **People**.

This guide gives no per-run numbers yet: they come from a manual measurement against real Google
and Microsoft accounts, which you can repeat on your own installation:

1. Turn on debug logging only if you want each call listed (`CALENDAR_SYNC_LOG_LEVEL=DEBUG`); the
   count alone is on every run's closing line at `INFO`.
2. Edit one event in a watched Source Calendar and wait for **Activity** to list it.
3. Read the run's closing line, whose `provider_calls=` is the run's count:

   ```sh
   docker compose logs --since 3m app | grep "run finished"
   ```

4. Repeat three times for each provider pair and take the middle value. To measure an Outlook
   wake with nothing to do, edit an event in a calendar of the same mailbox that no rule reads.

## Outlook wakes every Source Calendar of its mailbox

Microsoft reports changes for a whole mailbox, never for one calendar. A change anywhere in it,
including an event Calendar Ghost wrote to another calendar of the same mailbox, wakes every rule
whose Source Calendar is in that mailbox. Such a run finds nothing to do and costs its listings.
It never runs a rule whose Source Calendar is elsewhere. When a rule writes into the mailbox its
own Source Calendar belongs to, its write wakes it once more; that run writes nothing, so it stops
there. Calendar Ghost keeps one subscription per Microsoft account, and Microsoft allows 1,000 per
mailbox across every application.

## Plans

Instant Sync asks one question of the installation: does this person's Sync Cadence allow it? With
Plans off, the default, every person's does, and Scheduled Sync runs every five minutes. When Plans
arrive, each Plan's shortest sync interval decides it, and its shortest value is "instant". There
is no separate administrator switch: each person can turn Instant Sync off for themselves
([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)).
