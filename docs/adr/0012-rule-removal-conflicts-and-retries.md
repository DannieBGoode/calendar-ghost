# Isolate removal conflicts and retry transient removal failures

## Context

[ADR 0010](0010-rule-removal-and-calendar-replacement.md) made Rule Removal resumable: the rule
becomes Disabled ("Removal incomplete"), each mapping commits individually, and the administrator
retries after an interruption. Three behaviors of that design leave removal harder to finish than
it needs to be:

- A mapped destination event whose Managed Origin metadata does not match the rule and source is
  reported by the Google adapter as an ordinary permanent provider failure. Removal stops on it,
  and every retry stops on the same event. The only way out is Detach, which also abandons every
  legitimate projection that remains.
- One temporary or rate-limited response interrupts the whole removal, although each deletion is
  idempotent and the scheduler already retries the same failures with backoff.
- An authentication or authorization failure during removal is visible only in the HTTP response.
  The rule stays inert with no Incident and no Incident Notification.

## Decision

- **Ownership mismatch is a Conflict for that event, not a removal failure.** The Google adapter
  raises a distinct ownership failure when a mapped destination event exists but lacks matching
  rule and source Managed Origin metadata. Rule Removal leaves that event untouched in Google,
  removes its Event Mapping, records a `blocked` audit entry without event content, and continues
  with the next mapping. The result reports how many events were left for this reason. The sync
  path keeps its current handling of the same failure.
- **Transient failures retry per deletion.** Temporary and rate-limited failures of one deletion
  retry up to three attempts with exponential backoff and jitter, honouring a provider retry-after
  hint. Only after the last attempt does removal stop as interrupted. The same stable Operation
  Key is used for every attempt. The rule lock is held while waiting, so synchronization cannot
  interleave with a removal in progress.
- **Authorization failures open an Incident.** An authentication or authorization failure during
  delete-mode removal stops immediately without retrying and opens one deduplicated Incident for
  the rule. The rule stays Disabled. The administrator either reauthorizes and retries, or retries
  with Detach. Completing the removal resolves the Incident through the existing rule cleanup.
- Detach remains available as shipped in ADR 0010.

## Alternatives considered

- Keeping the ownership mismatch fatal would preserve a strict stop, but a Conflict that the
  application cannot repair would block removal indefinitely. Leaving the event, like a Detached
  Event, is the conservative outcome: nothing unproven is deleted.
- Deleting a mismatched event because its mapping exists would violate the invariant that deletion
  requires both mapping and metadata ownership.
- Moving removal to a background task resumed by the scheduler would avoid long HTTP requests for
  very large rules. It is deferred: with per-deletion retries, a long request is an inconvenience
  rather than a correctness risk, and the scheduler resume path adds a second removal trigger.
- A provider-verified removal count before confirmation would report unmapped managed events and
  conflicts in advance, at the cost of listing the destination each time the confirmation opens.
  It is deferred; unmapped managed events are already never touched.

## Consequences

A removal can now finish while leaving some events in Google, so the result and the confirmation
copy distinguish deleted projections from events left because ownership could not be proven.
Removal requests can take longer while backing off. Removal gains a dependency on the incident
store through a narrow application port. Recurring projections are unaffected: a series is still
removed by deleting its destination master after the same ownership check.
