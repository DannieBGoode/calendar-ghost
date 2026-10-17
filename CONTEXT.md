# Calendar Synchronization

This glossary defines the shared language for describing provider-independent calendar synchronization.

## Product Boundary

Google Calendar and Outlook (Microsoft 365 work or school accounts and personal Outlook.com
accounts, through Microsoft Graph) are the supported calendar providers. Outlook is verified with
personal Microsoft accounts; work or school accounts can connect but are not yet verified, and the
landing page, the documentation, and the Web UI's Connect menu say so until ADR 0034's checks pass
with one. iCloud support is planned
and advertised as coming soon, with no release date promised. Other providers, including CalDAV and
ICS feeds, remain unsupported.

**Community Edition**:
The Calendar Ghost software in this repository, run on infrastructure the operator controls. One
SQLite database, one scheduler, and one application process serve one or more Users, each with
private records, and an Installation Administrator operates it (ADR 0023, ADR 0030). It has no mandatory Calendar Ghost
account, telemetry, or hosted control plane. The Community Edition is intended to remain genuine
open-source software under the GNU Affero General Public License, version 3 or later; the name and
marks are governed separately.

**Hosted Service**:
A future commercial service where the project runs the Community Edition for people who do not want
to operate it themselves, with Commercial Mode on. It sells managed upgrades, backups, support, and
availability. It runs the same open code, with no closed components (ADR 0023).

**Plan**:
A named set of limits that an Installation Administrator defines and assigns to Users: how many
Active Rules, Connected Accounts, and Integration Tokens a User may have, and how soon their rules
sync. Each Plan has a stable key, made from its name and never changed, and a name that can change
but that no other Plan has, whatever its case; each count is a number or unlimited, and Integration
Tokens may also be none. Every Connected Account counts, Disconnected Accounts included, so a Plan
limits calendar accounts, never only "active" ones; every Integration Token not revoked counts too.
A Plan limits only how much a User uses, never how a rule projects events or how a User sees and
recovers from a problem. Plans are an installation setting that is off by default; when off, every
User has every feature with no limits (ADR 0028). An Installation Administrator is never limited.
A User's own Plan is set by an Installation Administrator, and later also by billing under
Commercial Mode, through one assignment that records who set it and when (ADR 0038).
_Avoid_: Tier, subscription, quota

**Active Rule**:
A Directional Sync Rule that counts toward its User's Plan: an enabled rule, a rule stopped only by
Lapsed Authorization, or a Rule Replacement's new draft that keeps its previous rule's place.
Drafts, previewed rules, paused rules, and rules stopped for any other reason are not active; nor,
once Plan Hold ships, are the rules it holds. A Plan's rule limit is a maximum of Active Rules,
checked at Start, so pausing a rule frees its place (ADR 0038). The code calls it
`SyncRule.counts_toward_plan`.
_Avoid_: Counted rule, rule that can sync

**Default Plan**:
The Plan an Installation Administrator marks as the default. Every User without a Plan of their own
has it, including Users who join later, so changing the default changes their limits at once.
Turning Plans on with no default makes an ordinary Plan named "No limits" ("No limits 2" when a Plan
already has that name), which limits nobody, the default, so turning Plans on changes nothing until
an administrator gives someone a smaller Plan. Plans are never on without a default: it cannot be
cleared while they are on, nor removed while it is the default. An administrator chooses it with
Make default on another Plan; "no default" is never offered as a choice. Billing will return a User
to it when a payment ends.
_Avoid_: Base plan, fallback plan

**Allowance**:
What one User may use now, decided in this order: no limits while Plans are off, none for an
Installation Administrator, otherwise their own Plan, or the Default Plan when they have none. It
decides every limit check and the User's Sync Cadence. A limit check that cannot read it refuses,
as for any database error, and Your plan says it could not load rather than show limits nobody
read; every other reader falls back to no limits, so a fault in Plans never stops synchronization
or sign-in (ADR 0038).
_Avoid_: Entitlement

**Plan Hold**:
The pause of a User's Directional Sync Rules beyond their Plan's rule limit, applied after a 7-day
grace period. Plan Hold is planned for a later release: until then a lowered rule limit only
refuses new Starts and stops nothing, so rules beyond it keep syncing (ADR 0038). Once it ships,
the User chooses which rules stay enabled; otherwise the most recently created are held. A held
rule keeps its mappings and projections, and resumes by itself without a new preview once the
User's limit allows it again.
_Avoid_: Suspension, plan pause, downgrade deletion

**Commercial Mode**:
The installation setting that lets a payment provider set a User's Plan. It is off by default and
requires Plans to be on. When it is off, no billing code runs or contacts a payment provider. The
Hosted Service turns it on.
_Avoid_: SaaS mode, billing mode

## Authorization

**Connected Account**:
A calendar-service identity authorized on this installation by one User, such as a Google account or a Microsoft account authorized through one OAuth grant. It belongs to exactly one Provider Kind and one User. Two Users may each connect the same calendar-service identity; each gets a Connected Account of their own, and neither learns of the other's. A sync rule may use different connected accounts, even of different providers, for its source and destination calendars, but both belong to the rule's User.
_Avoid_: Account, user, login, active account, active calendar account

**Provider Kind**:
The calendar service a Connected Account belongs to: `google` or `outlook` (a Microsoft account, whose calendars Outlook shows). It is recorded when the account is first connected and never changes. Every request about the account's calendars goes to that provider's adapter (ADR 0022, ADR 0034). The domain and application name a provider only by its Provider Kind; what a provider is called, how it connects, and how its reasons read as Causes live in its adapter's descriptor.
_Avoid_: Account type, integration

**Disconnected Account**:
A previously connected identity whose stored credentials have been removed from the installation. It remains listed so the same identity can be reauthorized without losing rule mappings or incremental positions. Enabled rules that use it become degraded immediately.
_Avoid_: Deleted account, removed user

A Disconnected Account may instead be permanently deleted by the User it belongs to. This
removes every affected Directional Sync Rule and its mappings, cursors, incidents, and audit
activity. Existing Managed Projections remain in their destination calendars and are no longer
managed because the installation no longer has the authorization or ownership records required to
change them.

**Lapsed Authorization**:
The condition of a Connected Account whose stored credentials its provider no longer accepts, as
when a Google or Microsoft grant expires or is revoked. The account stays connected, so its rules keep their
mappings and incremental positions. Any provider request that the provider refuses for
authentication or authorization marks it, whether a sync run, a preview, a calendar listing, or an access check, and
it stops every enabled rule of the account. Reauthorization clears it, and so does an access check the provider accepts. Once it clears and
every account a Degraded Rule uses is authorized, a rule stopped only by Lapsed Authorization
returns to scheduled synchronization on its own, continuing from its preserved incremental positions
so changes made in either calendar while it was stopped are synchronized or repaired; a rule
stopped for any other reason still needs a recovery preview (ADR 0027).
_Avoid_: Expired account, broken connection, disconnected

## Synchronization

**Directional Sync Rule**:
A one-way, one-to-one relationship from exactly one source calendar to exactly one destination calendar. Two rules are required to express synchronization in both directions.
_Avoid_: Calendar pair, sync pair, bidirectional rule

**Source Calendar**:
The single calendar whose events a directional sync rule observes.
_Avoid_: Origin calendar, upstream calendar

**Destination Calendar**:
The single calendar where a directional sync rule manages event projections. It may belong to a different connected account than the source calendar.
_Avoid_: Target calendar, downstream calendar

**Event Projection**:
The destination-facing representation derived from an authoritative source event by a transformation policy. Direct changes to a projection are overwritten during synchronization.
_Avoid_: Event copy, cloned event

**Drift**:
A difference between the expected event projection and its actual destination state. Drift includes direct edits or deletion of a managed projection and is repaired from the source during synchronization.
_Avoid_: Conflict, destination change

**Event Mapping**:
The durable identity link between one source event and the projection managed for it under one directional sync rule. A mapping is the proof of ownership required to update or delete a destination event.
_Avoid_: Event match, duplicate record

**Source Cancellation**:
The source-side removal or cancellation of an event. It causes deletion of the mapped destination projection; restoring the source causes the projection to be created again. It matters to a rule only through a projection: a cancelled event, series, or occurrence that no projection of the rule holds, or will hold once the rule writes its series, leaves nothing to delete and is no decision of the rule, so Activity records nothing for it and a Rule Preview does not list it. Deleting a series removes every occurrence with it.
_Avoid_: Destination deletion, unlinking

**Native Event**:
An event authored outside this application on the calendar where a directional sync rule observes it. Only native events are eligible to become sources.
_Avoid_: Original event, user event

**Managed Projection**:
An event projection owned by this application and marked with durable origin identity. Reverse rules ignore managed projections, preventing them from becoming sources and creating loops.
_Avoid_: Synced event, copied event

**Source Observation**:
The tracked details of a source event a rule last saw: title, time, description, location, guest addresses, recurrence, and conferencing links. It lets the next revision be described. Responses to invitations are not tracked.
_Avoid_: Cached event, event copy in the database

**Source Change**:
The tracked fields a new revision of a source event changed since its Source Observation, with their values before and after, recorded on that decision's Audit Entry. It never says who made the change. A revision that changed nothing a rule projects needs no destination write.
_Avoid_: Event diff, edit history

**Source Comparison**:
How a source event compared with the rule's Source Observation of it before its decision: changed, untracked (a new revision with no tracked field difference), same revision, cancelled, or no baseline. It decides whether a repeated skip is recorded and appears in an Audit Entry's details.
_Avoid_: Diff result, change check

## Recurrence

A recurring source event projects as one recurring destination series, never as unrelated single
events. Moving, editing, or cancelling one source occurrence changes only the matching destination
occurrence, and deleting a source series deletes its destination series. Direct destination edits
to a series or one of its occurrences are repaired from the source. An occurrence whose series its
calendar does not show, such as one meeting of a series someone invited the calendar to, projects
on its own as a single event until its series is shown (ADR 0011).

**Event Series**:
A recurring source event that defines a recurrence pattern shared by its occurrences. Its managed projection remains a recurring series rather than a collection of unrelated events.
_Avoid_: Recurring master, parent event

**Occurrence**:
One scheduled instance of an event series, identified within that series. An occurrence may be modified or cancelled independently while retaining its series identity.
_Avoid_: Child event, standalone event

**Occurrence Exception**:
A modification or cancellation that applies to one occurrence without changing the rest of its event series.
_Avoid_: Recurrence override, detached event

**Series Mapping**:
An Event Mapping whose source is an Event Series. It proves ownership of the destination series and every occurrence in it. When no occurrence of the source series remains that the rule would project, the Series Mapping stays dormant without a destination series, keeping its cancelled Occurrence Mappings until an occurrence is restored.
_Avoid_: Parent mapping, master mapping

**Occurrence Mapping**:
Ownership evidence for one destination occurrence the application wrote under a Series Mapping, identified by the occurrence's original start. Cancellations are retained so a recreated destination series cannot resurrect occurrences the source cancelled.
_Avoid_: Instance record, child event

## Event Time

**All-Day Event**:
An event spanning calendar dates rather than times of day. It remains distinct from a timed event so timezone conversion cannot shift its dates.
_Avoid_: Midnight event, untimed event

**All-Day Sync Policy**:
A directional sync rule setting that includes or excludes all-day source events from synchronization. New rules include all-day events unless the user opts out.
_Avoid_: All-day filter, skip all-day flag

**Birthday Policy**:
A directional sync rule setting that includes or excludes the birthdays a provider keeps among a calendar's events, such as the contacts' birthdays Google keeps in a primary calendar. New rules exclude them unless the user opts in.
_Avoid_: Birthday calendar

## Invitations

**Invitation Response**:
How the source calendar answered an event's invitation: accepted, tentative (shown as Maybe), declined, or awaiting a response. An event the source calendar was not invited to, such as one it organizes, counts as accepted. Only the source calendar's own response is read; other guests' responses never affect a projection.
_Avoid_: RSVP status, attendance

**Tentative Event Policy**:
A directional sync rule setting for events the source calendar answered Maybe to: project them marked as tentative, project them like accepted events, or skip them. New rules mark them, titling the projection "Busy (tentative)" under a Busy-Only Projection and "Maybe: " followed by the title under a Details Projection.
_Avoid_: Maybe filter

**Unanswered Invitation Policy**:
A directional sync rule setting for invitations the source calendar has not answered: treat them as answered Maybe, or project nothing until they are answered. New rules treat them as Maybe.
_Avoid_: Pending filter

Declined events are never projected.

## Transformation

**Transformation Policy**:
The rule-wide policy that determines the content of every event projection created by one directional sync rule. It is selected per rule, never per event.
_Avoid_: Event privacy setting, copy mode

**Busy-Only Projection**:
An event projection containing timing and recurrence with the title “Busy,” while omitting source details. It is the default transformation policy for a new rule.
_Avoid_: Private copy, redacted event

**Details Projection**:
An event projection containing source title, description, location, timing, and recurrence. It excludes attendees, organizer identity, conferencing links, and attachments, and never sends invitations.
_Avoid_: Full clone, exact copy

## Integrity

**Conflict**:
An ambiguous or corrupted identity relationship, such as two source events claiming the same managed projection. Content differences are drift, not conflicts. A conflict blocks writes to that one event and leaves the destination unchanged; the rest of the rule keeps synchronizing. A conflict that persists to the next daily full pass, or to a Reconcile Now, opens an Incident.
_Avoid_: Destination edit, synchronization difference

## Synchronization Progress

**Initial Sync Window**:
The source-event range inspected when a rule is first enabled: events ending within the previous 30 days or later, with no future cutoff. A series is in it while one of its occurrences the rule projects is.
_Avoid_: History limit, retention period

**Incremental Sync**:
Synchronization of provider-reported changes after the initial sync window has completed successfully. Provider feeds report changes to events of any age; an unmapped single event, or an unmapped series whose every occurrence the rule projects ended before the rolling window start, is skipped, while mapped events and series stay current.
_Avoid_: Delta import, partial sync

**Scheduled Sync**:
An incremental sync requested by the local scheduler every five minutes, or as often as the User's
Sync Cadence sets. It needs no public address, and it catches every change Instant Sync missed.
_Avoid_: Cron sync, background sync

**Sync Now**:
A user-requested synchronization that runs through the same behavior as a scheduled sync without waiting for the next interval.
_Avoid_: Force sync, manual import

## Instant Sync

**Instant Sync**:
A sync of a Directional Sync Rule run soon after its Source Calendar's provider reports a change
that may concern it, instead of at the next Scheduled Sync. It runs through the same behavior as a
Scheduled Sync. It needs a public `https` address the providers reach, and runs for every enabled
rule of a User whose Sync Cadence allows it, unless the User turns it off. It promises no delivery
time: Scheduled Sync and the daily full pass still run and catch every missed report. Only Source
Calendars are watched, so Drift in a destination is still repaired by Scheduled Sync (ADR 0036).
_Avoid_: Real-time sync, push sync, live sync

**Sync Cadence**:
How a User's rules may synchronize: whether Instant Sync is allowed, and how often Scheduled Sync
runs. The User's Allowance decides it from their Plan's sync interval, one of a fixed list:
instant, 5, 10, 15, 30, or 60 minutes, where instant means Instant Sync plus a five-minute
Scheduled Sync. With Plans off, and for an Installation Administrator, it is instant. An
administrator can choose instant or 5 minutes for now; until the longer intervals are offered,
every interval other than instant syncs every five minutes without Instant Sync. The User keeps
only their own choice to turn Instant Sync off.
_Avoid_: Sync frequency, polling interval

**Calendar Watch**:
A provider's commitment to report changes in one Watch Scope of a User's Connected Account. It
records which Source Calendars it covers, so a report wakes only rules whose Source Calendar it
covers. A watch exists only while an enabled rule needs it.
_Avoid_: Subscription, webhook, channel

**Watch Scope**:
What one Calendar Watch covers, as its provider allows: one calendar for Google, and the whole
mailbox for Outlook, whose event reports cannot be limited to one calendar.
_Avoid_: Watch target, watched resource

**Watch Registration**:
One Google channel or Microsoft Graph subscription that carries a Calendar Watch. Its own
identifier is part of its notice address, and its secret token is kept only as a hash. It is
created, confirmed, renewed or replaced before it expires, and stopped once nothing needs it;
while one replaces another, notices on both count.
_Avoid_: Webhook, hook

**Watch Notice**:
One request a provider sends about a Watch Registration: that it started, that something in its
scope changed, that reports were missed, that it needs renewing, or that it was removed. It carries
no event content, and none is logged. A notice whose registration, token, or handle does not match
changes nothing.
_Avoid_: Push notification, webhook event, ping

**Instant Sync Request**:
The durable, per-rule record that a Watch Notice asked the rule to run soon. A run acknowledges
what it saw once it returns, succeeded or failed, and a notice during the run asks again. It
survives a restart.
_Avoid_: Wake-up flag, dirty flag

**Delivery Evidence**:
What the installation knows about whether one provider reaches its current public address: when a
notice last arrived or a registration proved delivery, and when delivery last failed. It belongs to
the installation, not a User. It only explains: it never removes a watch or blocks a run.
_Avoid_: Reachability check, health probe

## Health

**Degraded Rule**:
A rule whose synchronization is safely suspended because it currently requires recovery, such as reauthorizing a connected account. Its mappings and last successful incremental position remain intact, and no destination writes occur until recovery.
_Avoid_: Failed rule, disabled rule

**Reauthorization**:
Renewal of a connected or disconnected account's authorization after access is lost or removed. It clears Lapsed Authorization.
_Avoid_: Reconnect, log in again

**Incident**:
A persistent operational condition requiring attention, such as expired authorization or identity corruption. Repeated sync attempts update one incident rather than creating duplicate alerts. An incident resolves after a successful scheduled sync, when a daily pass finds nothing still blocked, or when its rule is removed, and records which. An incident for Lapsed Authorization belongs to the Connected Account instead of one rule: it names every rule the lapse stopped, sends one notification, and resolves when the lapse clears; one that opens again starts a new episode with its own opening time. Each incident has one next step, decided from its Cause, its category, and its rule as it is now: reauthorize, recover or review the rule, see its blocked events, wait, leave it to the administrator, or, once resolved, see the rule's history; the Web UI and the email offer the same one (ADR 0033). Resolved incidents are kept as evidence until their Connected Account is deleted. While any incident is kept, Activity lists them under its own Incidents tab, open ones first, and that tab counts the open ones.
_Avoid_: Error message, failure log

**Incident Notification**:
A deduplicated notice sent when an incident opens or resolves. It goes to the User who owns the incident's rule or Connected Account, never to another User; the Web UI always retains the incident, and the User receives email too when the installation can send it, unless they turn it off. When the installation has a public address, the email links to the Web UI page holding the incident's one next step; the link names no calendar, account, or event. Incidents about the installation itself, such as a stalled scheduler, go to the Installation Administrators' SMTP recipient or generic JSON webhook.
_Avoid_: Error alert, retry notification

**Installation Status**:
The server's one verdict on the installation's health as it affects one User (stalled, stopped, review, waiting, paused, setup, or healthy) with every current problem, most urgent first. The Overview, the status API, and MCP all show it. It covers that User's rules and any installation problem that affects them, such as a stalled scheduler. It names rules by their calendars and never carries event content, calendar IDs, or account emails. A rule stopped by Lapsed Authorization is reported as stopped for that cause; the Web UI names the account from its own records, so monitors and agents learn only that a calendar account needs reauthorization.
_Avoid_: Health check, status page

**Installation Health**:
The one verdict on the whole installation that Installation Administrators and their monitors read: installation incidents, how many Users are in each Installation Status verdict, and any Installation Hints. It names no rule, calendar, or User.
_Avoid_: Global status, admin status

**Cause**:
Why a provider call failed, as one of a closed set read from the provider's own reason code, never
from its message text. Each Cause has one owner, the Installation Administrator or the User, and an
Installation Administrator never contacts a User through Calendar Ghost about a problem: what a User
can fix, they fix from their own Overview, rule, or Settings. The administrator's Causes are those
only the installation's registration with its provider can fix: the Google Calendar API is turned
off for the Google Cloud project (`api_disabled`), the project's daily quota is used up
(`quota_exceeded`), or the provider no longer accepts the installation's OAuth client
(`oauth_client_invalid`), as when a Microsoft client secret expired. The User is told only that their
calendar is temporarily unavailable, never the Cause or who fixes it, so nobody is sent to the
administrator, who learns it on People. Every other Cause is the User's, with one next step from actions
that already exist: the provider no longer accepts the account's grant (`access_revoked`), so they
reauthorize the account; the account may not change the calendar (`calendar_forbidden`) or the
calendar is gone (`calendar_not_found`), so they choose another calendar or remove the rule;
the provider is limiting requests (`rate_limited`) or failed for now (`temporary`), which fixes itself, so
they are told when it was last tried and when it is tried again; and anything else is `unknown`,
whose problem keeps its usual next step, said honestly as trying again. A failure no provider answer
explains, such as one inside Calendar Ghost or one its adapter concludes itself, has no Cause. A Cause says who fixes a
failure; whether a rule retries, stops, or lapses its account still follows the failure itself
(ADR 0031). Each provider's adapter maps its own reason codes to Causes; Microsoft never raises
`api_disabled` or `quota_exceeded` (ADR 0034). Incidents and run outcomes record it with the
Provider Kind that raised it, and Installation Status shows both on each problem.
_Avoid_: Error reason, root cause, error message

**Installation Hint**:
A likely cause Installation Health suggests to Installation Administrators, never from one User's
content: an administrator's Cause any User met within a day, since only the administrator can fix
it; as patterns across Users, Google refusing two or more Users' grants about 7 days after they
authorized, which an OAuth app in Testing mode does, or two or more Users failing within a day for
a reason Calendar Ghost does not recognize (`unknown`), which the service logs name by the
provider's reason code; and, while any User who may sign in wants Instant Sync, a public address
that uses plain `http` at a host the internet reaches, or a provider whose Delivery Evidence is
failing. Each hint names its provider when it concerns one, its Cause when a failed provider call
explains it, how many Users show it, and the troubleshooting section that explains the fix. It
names no User, rule, calendar, or account. Hints are what People flags; a User's own problems are
not flagged, and the administrator finds them, with what the User does, on that User's page.
_Avoid_: Diagnosis, alert, recommendation

## Access

**User**:
A person who signs in to an installation. Every Connected Account, Directional Sync Rule, Integration Token, incident, and Audit Entry belongs to exactly one User, and no User sees another's. Calendar sharing between people stays in the calendar provider, not in Calendar Ghost.
_Avoid_: Tenant, customer, member, login

**Installation Administrator**:
A User who holds the role that operates the installation. The first User holds it, it may be given to other Users, and the last one cannot lose it while anyone else remains. When the last User deletes themself, the installation returns to setup. It grants installation-wide operational powers, never sight of another User's event content; an Installation Administrator's own rules and accounts are as private as anyone's.
_Avoid_: Owner, superuser, admin user

**Operator Overview**:
The Installation Administrator's view of every User's health: each User's Installation Status with calendars shown only by neutral labels ("Calendar 1", "Calendar 2", numbered per User in the order their rules were created), plus the User's email, role, last sign-in, state, Resource Use, and, once any Plan exists, their Plan: who gave it to them and when, how many Active Rules, Connected Accounts, and Integration Tokens they have, as the Plan counts them, and each of its limits they have more of than it allows. For People's Plans tab it also counts, per Plan, how many of the people it limits have more than it allows, and, before an administrator gives people a Plan, which of its limits each of them would have more of. It is the same on every installation, never shows calendar names, calendar identifiers, account emails, or event content. What it shows and never shows is documented, so every User can know it; Settings does not repeat it to them (ADR 0030, amended).
_Avoid_: Admin dashboard, user management, support view

**Resource Use**:
How much of the installation one User uses, as counts only: their rules, Connected Accounts, and Activity entries, and, per calendar provider, the calls their runs made over the last 30 UTC days, how many the provider refused for its rate limit, and how many failed. It never says what a call asked for.
_Avoid_: Usage, consumption

**Disabled User**:
A User an Installation Administrator has stopped from signing in. Their rules are held and resume by themselves when the User is enabled again; nothing they own is removed.
_Avoid_: Suspended user, banned user

**User Deletion**:
The permanent removal of a User and everything they own. Their projections are deleted from their calendars by default; a User deleting themself may keep them as ordinary events instead, but an Installation Administrator deleting another User cannot. It removes them from the live database; a backup taken before it keeps their records until the backup rotates out.
_Avoid_: Account deletion, user removal

**Registration Policy**:
The installation setting that decides who may become a User: Only Me, the default, where nobody can join; Invitation Only; or Open, where anyone may sign up. Under Only Me the Web UI hides Users, Invitations, Plans, and the Operator Overview. An Installation Administrator may switch to Invitation Only or Open at any time, and back to Only Me only while no other User exists. Data is User-scoped under every policy; the policy decides only who may join and what the Web UI shows. Open requires the installation to send email, so new Users can verify their address and reset their own password; it arrives with sign-up, for the Hosted Service.
_Avoid_: Signup mode, public registration

**Invitation**:
A single-use, expiring link an Installation Administrator creates so one person can become a User and choose their own credentials. It works under Invitation Only and Open, never under Only Me, and expires after 7 days. A Password Reset Link is its counterpart for an existing User; neither lets the administrator see or set a password.
_Avoid_: Invite code, admin-created account

**Public Health Status**:
The minimal unauthenticated indication that the service is running. Calendar, account, rule, OAuth, audit, and incident details require the session of the User they belong to. Installation Status is its authenticated counterpart.
_Avoid_: Public dashboard, anonymous status page

**Integration Token**:
A named credential a User issues so a monitor or AI agent can read their Installation Status, and nothing else; an Installation Administrator's token may also read Installation Health. Only its hash is stored; it is shown once and can be revoked.
_Avoid_: API key, personal access token

**Installation Master Key**:
A secret stored separately from the application database and used to protect persisted provider credentials. Losing it requires reauthorizing connected accounts.
_Avoid_: OAuth secret, administrator password, database password

## Rule Lifecycle

**Rule Preview**:
A side-effect-free evaluation of every source event in the rule's Initial Sync Window, each beside the projection it would write and its planned action, or beside the reason the rule excludes it. It plans through the same decisions as a Sync Run, so each event it lists shows what the next run will do and record. A new or materially changed rule must pass preview before it can be enabled. It writes nothing to any calendar; locally it records only the rule's validated state and the preview's counts, so enabling can restate what will be written. The events it lists stay with the person who asked for it and are never stored.
_Avoid_: Test sync, simulation

**Material Rule Change**:
A change to a rule's transformation policy or event eligibility that invalidates its previous preview and requires a new one. Saving it stops synchronization immediately; after the rule is previewed and enabled again, the next run rewrites every mapped projection under the new policy. Calendars cannot change in place; that requires a Rule Replacement.
_Avoid_: Rule edit, configuration update

**Rule Topology**:
The set of directional relationships formed by enabled rules. One-to-many and many-to-one topologies are valid, but an exact source-calendar to destination-calendar relationship may exist only once.
_Avoid_: Calendar graph, sync network

**Paused Rule**:
A reversible rule state that suspends synchronization while leaving its managed projections and mappings intact. Resuming begins with reconciliation.
_Avoid_: Disabled rule, stopped rule

**Rule Removal**:
Permanent removal of a rule after its User explicitly chooses to delete its mapped projections or keep them as detached ordinary events. Mapped projection deletion is the recommended default and requires an authorized destination account. An event whose ownership cannot be verified is a conflict for that event only: it is left in place and removal continues. A removal interrupted by a provider failure leaves the rule inert until it is retried; lost authorization also opens an incident.
_Avoid_: Disable rule, pause rule

**Rule Replacement**:
A change of a rule's source or destination calendar, performed as a new draft rule with the same transformation policy followed by Rule Removal of the previous rule. The new draft is created in the step that begins the previous rule's removal, so a duplicate relationship is refused before anything is removed, and no draft exists without that removal. When the previous rule counted toward its User's rule limit, the new draft keeps its place until it starts or is removed. If the removal is interrupted, the new draft remains with its place, and the previous rule's removal can be retried.
_Avoid_: Calendar edit, rule move

**Detached Event**:
A former managed projection retained during rule removal after its mapping is removed. It keeps the removed rule's private origin metadata, so it is never updated again and never becomes a source for a reverse rule.
_Avoid_: Orphaned projection, preserved copy

## Reconciliation

**Touched Reconciliation**:
Verification of mappings affected by one synchronization run. It occurs before that run is considered complete.
_Avoid_: Sync verification, spot check

**Full Reconciliation**:
Read-only verification of every mapping under a rule whose source or projection reaches its Initial Sync Window, from the window's start onward, against its current source and the managed events in the destination. A series reaches the window while any of its occurrences does; an event that ended before the window is past and is neither checked nor reported. It reports the Drift still present and records each Conflict it finds as a blocked Audit Entry; it repairs nothing itself. A mapping outside the rule's relationship, a mapping whose source cannot be read, and a managed event with no mapping are Conflicts, never Drift.
_Avoid_: Full sync, rescan

**Reconcile Now**:
A user-requested full synchronization pass, which stands in for that day's daily pass and repairs the drift it reaches in the Initial Sync Window, followed by a Full Reconciliation. What the reconciliation still finds was left as it is; an event the pass already blocked is not reported again.
_Avoid_: Repair sync, force reconcile

## Execution

**Sync Run**:
One attempt to synchronize a directional sync rule from a known incremental position. Its position advances only after all changes and touched reconciliation complete successfully.
_Avoid_: Sync job, import run

**Operation Key**:
A stable identity assigned to an intended provider write so retrying a partial sync run cannot create a duplicate projection.
_Avoid_: Request ID, idempotency token

**Provider Incident**:
An incident opened after three consecutive scheduled sync runs fail because of a temporary or rate-limited provider condition. It resolves automatically after a successful scheduled run.
_Avoid_: Retry error, provider outage

**Rule Isolation**:
The guarantee that one rule's failed or degraded sync run does not block or roll back unrelated rules. Provider requests may still share connected-account rate limits.
_Avoid_: Independent deployment, separate worker

## Interface Wording

The Web UI speaks to each person in a household, so its primary copy uses calendar language and
keeps glossary terms for places that need their precision. Code, documentation, audit reasons, and
diagnostics keep the glossary terms above.

| Glossary term | Primary interface wording |
| --- | --- |
| Directional Sync Rule | rule, named "Source → Destination" |
| Event Projection, Managed Projection | projection where precision matters (removal, counts); "events this rule wrote to Family" otherwise; never "copied event" |
| Busy-Only Projection | "Busy only: titles, descriptions, and locations stay private" |
| Details Projection | "Copy title, description, and location" |
| Invitation Response | "you answered Maybe", "you declined", "you haven't answered"; "Your response" in a change |
| Material Rule Change | "A change stops the rule from writing until you preview it again" |
| Rule Preview, then enable | "Preview rule", then "Start syncing", which exists only on the preview page; a previewed rule reads "Ready to start" with "Review and start", or "Previewed" with the refusal and "See your plan" when its User's Plan would refuse its Start. Each previewed event "Will sync" (with Add, Update, Remove, or Already up to date) or "Not synced", with its reason ("Not synced: birthday") |
| Degraded Rule | "Stopped", with the cause and its one next step: "Reauthorize account" when an account it uses has Lapsed Authorization, otherwise "Preview to restart" |
| Reconciliation | "Reconcile now", always with its explanation: syncs in full, putting back events edited or deleted in the destination, then checks every event the rule wrote from the starting point onward and reports any that still differ; never "repaired" for what the check only reported |
| Instant Sync | "Instant sync" under Settings → Your account, a choice between "Instantly", the default, and "On schedule"; where it cannot run, it says why and offers "Learn why", opening that reason's section of the Instant Sync guide, and keeps the choice only while providers cannot reach the installation, so a person can stop the retries. On a rule, "Syncs instantly", or "Syncs every 5 minutes" with why |
| Connected Account | named by its Provider Kind: "Google account" or "Microsoft account"; "calendar account" where no one provider is meant. Its row in Settings says which ("Microsoft account · dana@contoso.example") |
| Lapsed Authorization | "Needs reauthorization", naming the account; its action is "Reauthorize with Google" or "Reauthorize with Microsoft" on the account's row, which opens the provider's consent, and "Reauthorize account" elsewhere, which opens that row |
| Initial Sync Window | "Starting point: includes events from the past 30 days onward" |
| Audit Entry, in Activity | one line per event: what was observed, then what Calendar Ghost did, such as "Cancelled in Work → removed from Family"; the run is only a time heading |
| Conflict | "Blocked", stating what is now different in the destination calendar and who acts: the User's step when one exists, otherwise that Calendar Ghost checks again daily |
| Drift | what was observed, never who caused it: "Edited in Family → changed back to match Work", "Missing from Family → put back"; a repeat of the previous run's repair says "again" |
| Operator Overview | "People", with a "Sync" status per person and "Installation health" above them; once a Plan exists, a "Plan" column per person, a "Plan" filter ("Any plan", each Plan, the default as "Free (default)"), and a "Limits" filter ("Anyone", "Over a limit"), and people can be selected to "Change plan" together |
| Plan | "plan" in lower case: "Your plan" under Settings → Your account, "Plans" as a tab of People, "New plan", and "Change plan" on a person's page, in each row's More actions on Everyone, and for the people selected there. The Plans tab leads with one switch, "Plans are on" or "Plans are off" with "On" or "Off" beside it, and one sentence on what Plans do now or would do: "Plans limit 2 people right now.", "Turning plans on limits 2 people right away, and 1 of them has more than their plan allows.", or, with no Plan, "Turning plans on adds a plan named No limits as the default, so nobody is limited until you give someone a smaller plan." Its facts are "Limited now" ("Would limit" while off), "Over a limit" ("Would be over a limit"), "Default plan", and "Never limited". A Plan's limits are "Maximum active rules", "Maximum calendar accounts", "Maximum Integration Tokens", and "Sync speed" in the editor, and "Active rules", "Calendar accounts", "Integration Tokens", and "Sync speed" in columns and usage. Each count is "No limit" or "Up to 3" in the editor, and "Unlimited" or the number elsewhere; Integration Tokens may also be "None", which Your plan and a person's page read as "Not included". Sync speed is "Instant" or "Every 5 minutes" ("Every 5 min" in a table cell), with "Longer intervals arrive in a later release." Cells and chips say nouns and numbers ("2 people", "1 over a limit"); sentences belong to hints, descriptions, and results. The Web UI never shows a Plan's key. A Plan's row menu holds Edit, Assign people, Make default, Duplicate, and Remove; Remove on a Plan someone has says who has it, the first three by email and then how many more, the count alone until the names arrive ("2 people have Free. Give them another plan first."). A name another Plan has, whatever its case, is refused under Name: "Another plan is named Free. Choose a different name." A limit typed lower says how many people it leaves with more: "1 person on Pro has more active rules than this. Their rules keep syncing, but they can't start another." Before anyone is given a Plan, each person says what they would be over ("Would be over: 3 active rules, Free allows 1"), administrators "Never limited, whatever plan they have", and the button names the effect ("Give Free to 2 people"). A result names it: "robin@example.test now has Free.", "2 people now have Pro." A person's Plan reads as its name with chips: "Default", "Over a limit" in Attention Ochre with an icon ("Would be over" and neutral while Plans are off), or "Not limited" for an administrator. On their page and on Your plan each limit reads "1 of 1" with "Limit reached", or "2 of 1" with "Over" and a sentence on what keeps working and how to make room: "robin@example.test has 2 calendar accounts and Free allows 1. Their accounts keep syncing, but they can't connect another until one is removed." Your plan says it in the person's words ("You have 2 calendar accounts and your plan allows 1. They keep syncing, but you can't connect another until you remove one in Connections."), says "To start another rule, pause one first." at the rule limit, and closes with "To change your plan, ask your administrator.", naming nobody. Invite someone says which Plan the person gets once one is the default: "They get the default plan, Free. You can change it after they join." "Create sync rule" notes the rule limit: "Your plan lets 5 rules sync at once." A refusal names the limit and one way to make room, with "See your plan"; a Plan that includes no Integration Tokens says so ("Your plan does not include Integration Tokens. To get one, ask your administrator."), never "0" |
| Active Rule | "active rules": "Maximum active rules" in the editor and "Active rules" in columns and usage, with what counts as the hint ("Running rules count, and rules waiting for an account to be reauthorized. Paused rules and drafts don't.") |
| Default Plan | "Default plan": a "Default" badge beside its name and the status card's "Default plan" fact on the Plans tab, and "Make default" on every other Plan, which says whom it moves ("People without a plan of their own (2 now) move to Free."); never "No default". Change plan offers it as "Follow the default plan", which names the Plan that is the default now ("No limits now. If the default changes, so does theirs."), and a filter names it "Free (default)". Remove on it says "Make another plan the default first." |
| Allowance | never named: Your plan says which Plan limits the person, or "You administer this installation, so no plan limits you." |
| Cause | "Likely cause:" and the cause in plain words, naming the provider that raised it, such as "the Google Calendar API is turned off for this installation" or "Microsoft no longer accepts this installation's OAuth client"; neutral words ("the calendar provider") when the server names none. To the User, an administrator's Cause says only "Temporarily unavailable", naming neither the cause nor the administrator, with Check access to try again when the account lapsed; their own Cause offers its one step ("Reauthorize account", or "Open the rule" to choose another calendar or remove it), or says it fixes itself with when it was last and will next be tried. To an administrator, a User's Cause says "{name} can fix this from their dashboard" ("{name} can try again from their dashboard" when `unknown`) and offers no action |
| Installation Hint, on People | the pattern in one sentence with how many people it affects, then "How to fix", linking to its troubleshooting section |
| Installation Status verdict, on People | "Not running" (stalled), "Stopped", "Needs a look" (review), "Waiting for the provider", "Paused", "Not set up" (setup), "Healthy" |
| User Deletion | "Delete your account" for oneself, naming what is deleted (sign-in, rules, calendar connections, tokens, Activity, and the events their rules wrote when chosen) and that their calendar accounts and own events stay; on People, "Delete" and "Delete {email} permanently?", naming the same and that the events their rules wrote are deleted. "Account deletion" stays out of domain and documentation language |

- The product is named **Calendar Ghost**. "Ghost" is brand language for the mark and tagline;
  the interface and documentation keep this glossary's terms, so a Managed Projection is never
  called a "ghost" in labels, explanations, or incidents.
- The Web UI's language follows the User's saved choice, then the browser's languages,
  then English. Diagnostics (provider error text, Audit Entry detail, Drift detail, and conflict
  detail) stay as recorded and are shown only under a translated diagnostic label, never
  translated or used as a primary sentence.

## Data Minimization

**Projection Fingerprint**:
A non-reversible digest of the normalized event projection used to compare expected and actual state without retaining source content.
_Avoid_: Event snapshot, content hash

**Operational Record**:
Persisted synchronization evidence limited to identities, revisions, recurrence relationships,
occurrence starts, operation state, timestamps, and projection fingerprints, plus the source event's
title and time on Audit Entries. Descriptions, locations, guest addresses, recurrence rules, and
conferencing data needed for Source Observations and Source Changes are sealed with a key derived
from the Installation Master Key and retained only for the configured history window. They are not
stored in plaintext, and event content is not included in incident notifications.
_Avoid_: Event history, cached event

**Audit Entry**:
An Operational Record of one synchronization decision worth explaining: a write, a block, a no-change check, or a skip that explains why an expected projection is absent. Loop-prevention and bookkeeping decisions are counted on the run instead. It carries the rule, run, source and destination event identities, the action, and a stable reason code explaining why. It also records the source event's title, time, recurrence, and cancellation as the run saw them, so Activity names events without asking the provider and can show renames. Entries recorded before that decision name no event. Activity keeps every entry until an Installation Administrator clears it: Settings → Administration → Storage clears every User's entries older than a chosen age (30, 90, 180, or 365 days), keeping, per Directional Sync Rule and source event, the latest entry older than the cutoff and the latest that recorded a title.
_Avoid_: Event log, history item
