# Decide an Incident's next step in the domain

Builds on [ADR 0031](0031-keep-the-providers-reason-as-a-cause.md) and
[ADR 0032](0032-bounded-contexts-as-application-packages.md).

## Context

ADR 0031 gives each Incident one next step for its owner and links the incident email to it. Two
places decided that step, with different rules. The email adapter read the Cause. The Web UI read
the Incident's category and, from the rules and accounts it had loaded, whether access was
renewed. They could disagree: a calendar the account may no longer use sent the email to the rule,
while Activity offered to reauthorize the account. A new category or Cause had to be taught to
both, and nothing failed when only one learned it.

The Incidents API also returned only the 100 most recent incidents, so an older one could not be
listed or opened, and Activity counted only what it had.

## Decision

- **The domain decides the step.** `domain/incidents.py` names each step (`IncidentStep`:
  reauthorize, recover the rule, review the rule, see blocked events, wait, the administrator's,
  see the rule's history) and decides it with `next_step` from what the Incident records and what
  its rule is now (`IncidentFacts`). The Cause comes first, as the provider gave it: an
  administrator's Cause is the administrator's step; a calendar the account may not use is the
  rule's to review; a Cause that fixes itself is a wait. Then the category: blocked events, a lost
  authorization (recover the rule once access is renewed, otherwise reauthorize), and otherwise a
  review of the rule. A resolved Incident leads to its rule's history. A step on the rule is
  offered only while the rule exists.
- **Both readers use it.** The Incidents API returns each Incident's `step`; the Web UI only words
  it and offers its one button. The email links to the page that holds the same step, deciding it
  as the Incident opens: its rule exists, having just run, and nobody has renewed access since. The
  link still names at most a rule's internal identifier. Blocked events now link to that rule's
  blocked events in Activity rather than to Activity.
- **What an administrator's Cause says depends on who reads it**, as ADR 0031 requires. The step is
  the same; the Web UI tells the administrator its likely Cause and how to fix it, and anyone else
  that Google Calendar is not available right now, with Check access to try again.
- **The Incidents API pages.** `GET /api/v1/incidents` lists one page, open incidents first, then
  resolved ones, each most recently updated first. Each incident carries an opaque `cursor`, its
  sort values as they were when read; passing the last one's as `before` goes on where that
  incident stood, so its refreshing or resolving since repeats or skips nothing.
  `GET /api/v1/incidents/{incident_id}` returns one incident, listed or not, and answers 404 for an
  incident another User owns, as for one that does not exist (ADR 0029).

## Alternatives considered

- **Keep the policy in the Web UI and copy it to the email.** Rejected: two copies drift, which is
  how the disagreement above began.
- **Return the step's page instead of the step.** Rejected: the Web UI and the email word and act
  on a step differently, and only the step is the domain's concern.
- **Return every incident, without pages.** Rejected: a long-running installation opens a new
  incident for each episode of a temporary failure, so the list grows without bound.

## Consequences

A new category or Cause is taught once, in the domain, and its tests show the step it gets. The
SQLite read model joins each Incident to its rule and the rule's accounts so the step weighs them
as they are now; Installation Status and the Operator Overview read the same facts. The Web UI no
longer needs the rules and accounts to decide a step, only to name the rule.
