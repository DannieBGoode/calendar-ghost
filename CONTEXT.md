# Calendar Synchronization

This glossary defines the shared language for describing provider-independent calendar synchronization.

## Product Boundary

Google Calendar is the only supported calendar provider today. Outlook and iCloud support are planned and
advertised as coming soon, with no release date promised. Other providers remain unsupported.

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
A named set of limits, such as how many rules a User may have or how often they synchronize, that
an Installation Administrator defines and assigns to Users. A Plan limits only how much a User
uses, never how a rule projects events or how a User sees and recovers from a problem. Plans are an installation setting that
is off by default; when off, every User has every feature with no limits (ADR 0028).
_Avoid_: Tier, subscription, quota

**Plan Hold**:
The pause of a User's Directional Sync Rules beyond their Plan's rule limit, applied after a 7-day
grace period. The User chooses which rules stay enabled; otherwise the most recently created are
held. A held rule keeps its mappings and projections, and resumes by itself without a new preview
once the User's limit allows it again.
_Avoid_: Suspension, plan pause, downgrade deletion

**Commercial Mode**:
The installation setting that lets a payment provider set a User's Plan. It is off by default and
requires Plans to be on. When it is off, no billing code runs or contacts a payment provider. The
Hosted Service turns it on.
_Avoid_: SaaS mode, billing mode

## Authorization

**Connected Account**:
A calendar-service identity authorized on this installation by one User, such as a Google account authorized through one OAuth grant. It belongs to exactly one Provider Kind and one User. Two Users may each connect the same calendar-service identity; each gets a Connected Account of their own, and neither learns of the other's. A sync rule may use different connected accounts, even of different providers, for its source and destination calendars, but both belong to the rule's User.
_Avoid_: Account, user, login

**Provider Kind**:
The calendar service a Connected Account belongs to, such as Google. It is recorded when the account is first connected and never changes. Every request about the account's calendars goes to that provider's adapter (ADR 0022).
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
when a Google grant expires or is revoked. The account stays connected, so its rules keep their
mappings and incremental positions. Any provider request that the provider refuses for
authentication or authorization marks it, whether a sync run, a preview, or an access check, and
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
The source-side removal or cancellation of an event. It causes deletion of the mapped destination projection; restoring the source causes the projection to be created again.
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

## Recurrence

A recurring source event projects as one recurring destination series, never as unrelated single
events. Moving, editing, or cancelling one source occurrence changes only the matching destination
occurrence, and deleting a source series deletes its destination series. Direct destination edits
to a series or one of its occurrences are repaired from the source.

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
The source-event range inspected when a rule is first enabled: events ending within the previous 30 days or later, with no future cutoff.
_Avoid_: History limit, retention period

**Incremental Sync**:
Synchronization of provider-reported changes after the initial sync window has completed successfully. Provider feeds report changes to events of any age; an unmapped single event that ended before the rolling window start is skipped, while mapped events stay current.
_Avoid_: Delta import, partial sync

**Scheduled Sync**:
An incremental sync requested by the local scheduler every five minutes. It does not require a public webhook.
_Avoid_: Real-time sync, push sync

**Sync Now**:
A user-requested synchronization that runs through the same behavior as a scheduled sync without waiting for the next interval.
_Avoid_: Force sync, manual import

## Health

**Degraded Rule**:
A rule whose synchronization is safely suspended because it currently requires recovery, such as reauthorizing a connected account. Its mappings and last successful incremental position remain intact, and no destination writes occur until recovery.
_Avoid_: Failed rule, disabled rule

**Reauthorization**:
Renewal of a connected or disconnected account's authorization after access is lost or removed. It clears Lapsed Authorization.
_Avoid_: Reconnect, log in again

**Incident**:
A persistent operational condition requiring attention, such as expired authorization or identity corruption. Repeated sync attempts update one incident rather than creating duplicate alerts. An incident resolves after a successful scheduled sync, when a daily pass finds nothing still blocked, or when its rule is removed, and records which. An incident for Lapsed Authorization belongs to the Connected Account instead of one rule: it names every rule the lapse stopped, sends one notification, and resolves when the lapse clears; one that opens again starts a new episode with its own opening time. Resolved incidents are kept as evidence until their Connected Account is deleted, but Activity leads only with open ones.
_Avoid_: Error message, failure log

**Incident Notification**:
A deduplicated notice sent when an incident opens or resolves. It goes to the User who owns the incident's rule or Connected Account, never to another User; the Web UI always retains the incident, and the User receives email too when the installation can send it, unless they turn it off. When the installation has a public address, the email links to the User's one next step for its Cause in the Web UI; the link names no calendar, account, or event. Incidents about the installation itself, such as a stalled scheduler, go to the Installation Administrators' SMTP recipient or generic JSON webhook.
_Avoid_: Error alert, retry notification

**Installation Status**:
The server's one verdict on the installation's health as it affects one User (stalled, stopped, review, waiting, paused, setup, or healthy) with every current problem, most urgent first. The Overview, the status API, and MCP all show it. It covers that User's rules and any installation problem that affects them, such as a stalled scheduler. It names rules by their calendars and never carries event content, calendar IDs, or account emails. A rule stopped by Lapsed Authorization is reported as stopped for that cause; the Web UI names the account from its own records, so monitors and agents learn only that a Google account needs reauthorization.
_Avoid_: Health check, status page

**Installation Health**:
The one verdict on the whole installation that Installation Administrators and their monitors read: installation incidents, how many Users are in each Installation Status verdict, and any Installation Hints. It names no rule, calendar, or User.
_Avoid_: Global status, admin status

**Cause**:
Why a provider call failed, as one of a closed set read from the provider's own reason code, never
from its message text. Each Cause has one owner, the Installation Administrator or the User, and an
Installation Administrator never contacts a User through Calendar Ghost about a problem: what a User
can fix, they fix from their own Overview, rule, or Settings. The administrator's Causes are those
only the installation's Google Cloud project can fix: the Calendar API is turned off
(`api_disabled`), the project's daily quota is used up (`quota_exceeded`), or Google no longer
accepts the installation's OAuth client (`oauth_client_invalid`). The User is told only that Google
Calendar is temporarily unavailable, never the Cause or who fixes it, so nobody is sent to the
administrator, who learns it on People. Every other Cause is the User's, with one next step from actions
that already exist: Google no longer accepts the account's grant (`access_revoked`), so they
reauthorize the account; the account may not change the calendar (`calendar_forbidden`) or the
calendar is gone (`calendar_not_found`), so they choose another calendar or remove the rule;
Google is limiting requests (`rate_limited`) or failed for now (`temporary`), which fixes itself, so
they are told when it was last tried and when it is tried again; and anything else is `unknown`,
whose problem keeps its usual next step, said honestly as trying again. A failure no provider answer
explains, such as one inside Calendar Ghost or one its adapter concludes itself, has no Cause. A Cause says who fixes a
failure; whether a rule retries, stops, or lapses its account still follows the failure itself
(ADR 0031). Incidents and run outcomes record it, and Installation Status shows it on each problem.
_Avoid_: Error reason, root cause, error message

**Installation Hint**:
A likely cause Installation Health suggests to Installation Administrators, never from one User's
content: an administrator's Cause any User met within a day, since only the administrator can fix
it; and, as patterns across Users, Google refusing two or more Users' grants about 7 days after they authorized, which an OAuth app
in Testing mode does; or two or more Users failing within a day for a reason Calendar Ghost does not
recognize (`unknown`), which the service logs name by Google's reason code. Each names its Cause, how
many Users show it, and the troubleshooting section that explains the fix. It names no User, rule,
calendar, or account. Hints are what People flags; a User's own problems are not flagged, and the
administrator finds them, with what the User does, on that User's page.
_Avoid_: Diagnosis, alert, recommendation

## Access

**User**:
A person who signs in to an installation. Every Connected Account, Directional Sync Rule, Integration Token, incident, and Audit Entry belongs to exactly one User, and no User sees another's. Calendar sharing between people stays in the calendar provider, not in Calendar Ghost.
_Avoid_: Tenant, customer, member, login

**Installation Administrator**:
A User who holds the role that operates the installation. The first User holds it, it may be given to other Users, and the last one cannot lose it while anyone else remains. When the last User deletes themself, the installation returns to setup. It grants installation-wide operational powers, never sight of another User's event content; an Installation Administrator's own rules and accounts are as private as anyone's.
_Avoid_: Owner, superuser, admin user

**Operator Overview**:
The Installation Administrator's view of every User's health: each User's Installation Status with calendars shown only by neutral labels ("Calendar 1", "Calendar 2", numbered per User in the order their rules were created), plus the User's email, role, last sign-in, state, and Resource Use. It is the same on every installation, never shows calendar names, calendar identifiers, account emails, or event content. What it shows and never shows is documented, so every User can know it; Settings does not repeat it to them (ADR 0030, amended).
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
A side-effect-free evaluation showing eligible source events, excluded events, destination projections, and planned actions. A new or materially changed rule must pass preview before it can be enabled. It writes nothing to Google; locally it records only the rule's validated state and the preview's counts, so enabling can restate what will be written.
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
A change of a rule's source or destination calendar, performed as a new draft rule with the same transformation policy followed by Rule Removal of the previous rule. The new draft is created first, so a duplicate relationship is rejected before anything is removed; if the removal is interrupted, the new draft remains and the previous rule's removal can be retried.
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
_Avoid_: Retry error, Google outage

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
| Rule Preview, then enable | "Preview rule", then "Start syncing" |
| Degraded Rule | "Stopped", with the cause and its one next step: "Reauthorize account" when an account it uses has Lapsed Authorization, otherwise "Preview to restart" |
| Reconciliation | "Reconcile now", always with its explanation: syncs in full, putting back events edited or deleted in the destination, then checks every event the rule wrote from the starting point onward and reports any that still differ; never "repaired" for what the check only reported |
| Connected Account | named by its Provider Kind: "Google account" or "Microsoft account"; "calendar account" where no one provider is meant. Its row in Settings says which ("Microsoft account · dana@contoso.example") |
| Lapsed Authorization | "Needs reauthorization", naming the account; its action is "Reauthorize account" |
| Initial Sync Window | "Starting point: includes events from the past 30 days onward" |
| Audit Entry, in Activity | one line per event: what was observed, then what Calendar Ghost did, such as "Cancelled in Work → removed from Family"; the run is only a time heading |
| Conflict | "Blocked", stating what is now different in the destination calendar and who acts: the User's step when one exists, otherwise that Calendar Ghost checks again daily |
| Drift | what was observed, never who caused it: "Edited in Family → changed back to match Work", "Missing from Family → put back"; a repeat of the previous run's repair says "again" |
| Operator Overview | "People", with a "Sync" status per person and "Installation health" above them |
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
