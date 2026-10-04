# Calendar Synchronization

This glossary defines the shared language for describing provider-independent calendar synchronization.

## Product Boundary

**Community Edition**:
The Calendar Ghost software in this repository, run on infrastructure the operator controls. Today
one Installation Administrator operates one SQLite database, one scheduler, and one application
process; ADR 0023 lets one installation serve many users later. It has no mandatory Calendar Ghost
account, telemetry, or hosted control plane. The Community Edition is intended to remain genuine
open-source software under the GNU Affero General Public License, version 3 or later; the name and
marks are governed separately.

**Hosted Service**:
A future commercial service where the project runs the Community Edition for people who do not want
to operate it themselves, with Commercial Mode on. It sells managed upgrades, backups, support, and
availability. It runs the same open code, with no closed components (ADR 0023).

**Commercial Mode**:
The installation setting that enables plans, plan limits, and billing. It is off by default. When it
is off, every user has every feature and no billing code contacts a payment provider. Only the
Hosted Service turns it on.

## Authorization

**Connected Account**:
A calendar-service identity authorized on this installation, such as a Google account authorized through one OAuth grant. It belongs to exactly one Provider Kind. A sync rule may use different connected accounts, even of different providers, for its source and destination calendars.
_Avoid_: Account, user, login

**Provider Kind**:
The calendar service a Connected Account belongs to, such as Google. It is recorded when the account is first connected and never changes. Every request about the account's calendars goes to that provider's adapter (ADR 0022).
_Avoid_: Account type, integration

**Disconnected Account**:
A previously connected identity whose stored credentials have been removed from the installation. It remains listed so the same identity can be reauthorized without losing rule mappings or incremental positions. Enabled rules that use it become degraded immediately.
_Avoid_: Deleted account, removed user

A Disconnected Account may instead be permanently deleted by the Installation Administrator. This
removes every affected Directional Sync Rule and its mappings, cursors, incidents, and audit
activity. Existing Managed Projections remain in their destination calendars and are no longer
managed because the installation no longer has the authorization or ownership records required to
change them.

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
Renewal of a connected or disconnected account's authorization after access is lost or removed. Affected rules reconcile before returning to scheduled synchronization.
_Avoid_: Reconnect, log in again

**Incident**:
A persistent operational condition requiring attention, such as expired authorization or identity corruption. Repeated sync attempts update one incident rather than creating duplicate alerts. An incident resolves after a successful scheduled sync, when a daily pass finds nothing still blocked, or when its rule is removed, and records which; one that opens again starts a new episode with its own opening time. Resolved incidents are kept as evidence until their Connected Account is deleted, but Activity leads only with open ones.
_Avoid_: Error message, failure log

**Incident Notification**:
A deduplicated notice sent when an incident opens or resolves. The Web UI always retains the incident; an installation may additionally configure SMTP email or a generic JSON webhook.
_Avoid_: Error alert, retry notification

## Access

**Installation Administrator**:
The single local identity authorized to configure the installation, connected accounts, rules, and incident delivery. The initial release does not have additional users or roles.
_Avoid_: User, owner, superuser

**Public Health Status**:
The minimal unauthenticated indication that the service is running. Calendar, account, rule, OAuth, audit, and incident details require an administrator session.
_Avoid_: Public dashboard, anonymous status page

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
Permanent removal of a rule after the administrator explicitly chooses to delete its mapped projections or keep them as detached ordinary events. Mapped projection deletion is the recommended default and requires an authorized destination account. An event whose ownership cannot be verified is a conflict for that event only: it is left in place and removal continues. A removal interrupted by a provider failure leaves the rule inert until it is retried; lost authorization also opens an incident.
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

The Web UI speaks to a household administrator, so its primary copy uses calendar language and
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
| Degraded Rule | "Stopped", with the cause and "Preview to restart" |
| Reconciliation | "Reconcile now", always with its explanation: syncs in full, putting back events edited or deleted in the destination, then checks every event the rule wrote from the starting point onward and reports any that still differ; never "repaired" for what the check only reported |
| Connected Account | "Google account" |
| Initial Sync Window | "Starting point: includes events from the past 30 days onward" |
| Audit Entry, in Activity | one line per event: what was observed, then what Calendar Ghost did, such as "Cancelled in Work → removed from Family"; the run is only a time heading |
| Conflict | "Blocked", stating what is now different in the destination calendar and who acts: the administrator's step when one exists, otherwise that Calendar Ghost checks again daily |
| Drift | what was observed, never who caused it: "Edited in Family → changed back to match Work", "Missing from Family → put back"; a repeat of the previous run's repair says "again" |

- The product is named **Calendar Ghost**. "Ghost" is brand language for the mark and tagline;
  the interface and documentation keep this glossary's terms, so a Managed Projection is never
  called a "ghost" in labels, explanations, or incidents.

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
An Operational Record of one synchronization decision worth explaining: a write, a block, a no-change check, or a skip that explains why an expected projection is absent. Loop-prevention and bookkeeping decisions are counted on the run instead. It carries the rule, run, source and destination event identities, the action, and a stable reason code explaining why. It also records the source event's title, time, recurrence, and cancellation as the run saw them, so Activity names events without asking the provider and can show renames. Entries recorded before that decision name no event. Activity keeps every entry until the administrator clears it: Settings → Storage clears entries older than a chosen age (30, 90, 180, or 365 days), keeping, per Directional Sync Rule and source event, the latest entry older than the cutoff and the latest that recorded a title.
_Avoid_: Event log, history item
