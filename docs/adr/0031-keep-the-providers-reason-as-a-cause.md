# Keep the provider's reason for a failure as a closed Cause

Builds on [ADR 0026](0026-translate-the-web-ui-through-message-catalogs.md),
[ADR 0027](0027-lapsed-authorization-and-automatic-recovery.md), and
[ADR 0030](0030-users-administrators-and-registration.md).

## Context

Calendar Ghost records a failed provider call only by its kind: authentication, authorization,
rate limit, temporary, permanent, or infrastructure. The kind decides what happens next (retry,
stop the rule, or lapse the account), but not who can fix it. Google answers "403" both when one
person's account may not write to a calendar and when the Calendar API is turned off for the whole
installation's Google Cloud project. Both lapse the account, and both tell the User to reauthorize,
which cannot help in the second case. On an installation with several Users, every one of them is
told to act, and the Installation Administrator, who alone can fix it, is told nothing specific.

Google's error carries a reason code (`error.errors[].reason` on Calendar API answers, and the
OAuth `error` field on token refreshes) beside a message. The message is free text that can quote
the request, including calendar identifiers, and ADR 0030 promises that administrators never see a
User's calendars.

## Decision

- **A Cause is one of a closed set**, read from the provider's reason code: `api_disabled`,
  `quota_exceeded`, `oauth_client_invalid`, `access_revoked`, `calendar_forbidden`,
  `calendar_not_found`, `rate_limited`, `temporary`, and `unknown`. Anything the adapter does not
  recognize is `unknown`. The Google adapter translates reason codes at its boundary, citing
  Google's documentation for each, as it translates every other provider payload. Google's message
  text is never stored, logged, or returned as part of a Cause. For `unknown`, the adapter logs
  Google's reason code only when it is a short token (letters, digits, and underscores, at most 64
  characters), so an administrator can name it and a later release can map it.
- **Each Cause has one owner, the Installation Administrator or the User.** `api_disabled`,
  `quota_exceeded`, and `oauth_client_invalid` are the administrator's; every other Cause is the
  User's.
- **An administrator never contacts a User through Calendar Ghost about a problem.** A User fixes
  their own Cause from their own Overview, rule, or Settings, with one next step built from actions
  that already exist: Reauthorize account for `access_revoked`; open the rule to choose another
  calendar or remove it for `calendar_forbidden` and `calendar_not_found`; nothing for
  `rate_limited` and `temporary`, which fix themselves, with when the rule was last tried and when
  the scheduler tries again; and the problem's usual next step for `unknown`, said as trying again
  because the fix is not known. To the User, an administrator's Cause says only that Google
  Calendar is temporarily unavailable, never which Cause or that an administrator fixes it, so a
  Hosted Service with many Users is not flooded with messages about one outage; the administrator
  learns it on People. Where the Cause lapsed the account, the User is offered Check access to
  try again. To the administrator, a User's Cause says the User can fix it
  from their dashboard, or try again for `unknown`, and offers no action. Notes to copy, reminders,
  read receipts, and any other channel from administrator to User are not built.
- **Incident email links to that step.** When the installation sets `CALENDAR_SYNC_PUBLIC_URL`,
  the owner's incident email links to the Web UI page holding their next step. The link names a
  page and at most a rule's internal identifier, never a calendar, account, or event. Without the
  setting the email has no link, as before.
- **A Cause says who fixes a failure, not what Calendar Ghost does about it.** The failure kind
  still decides retrying, stopping, and Lapsed Authorization. Two reclassifications follow from
  the Cause, both 403s that earlier releases treated as an authorization refusal and so lapsed the
  whole account. Google's `dailyLimitExceeded` is now a rate limit, retried with backoff, because
  a quota resets by itself. `calendar_forbidden` (`requiredAccessLevel`, `forbidden`,
  `forbiddenForNonOrganizer`) is now a permanent failure of its rule, which stops for another
  calendar while the account and its other calendars keep working. Reauthorizing helped neither.
- **Installation Health needs attention when it has a hint**, as well as when a verdict needs it,
  so monitors hear of a Cause only the administrator can fix even while every rule merely waits.
- **Incidents and run outcomes record the Cause** where they already record the failure kind, in a
  nullable column. Rows recorded before this decision read as `unknown`. Installation Status shows
  each problem's Cause, and the status API returns it.
- **Installation Health derives Installation Hints from patterns across Users**, never from one
  User's content: an administrator's Cause that any User met within 24 hours, since only the
  administrator can fix it; and, as patterns, `unknown` for two or more Users within 24 hours and
  `access_revoked` about 7 days after authorizing for two or more Users, which is how Google expires
  grants of an OAuth app in Testing mode. Hints flag People and its navigation link; a User's own
  problems never do, and the administrator finds them, with what the User does if they ask for
  help, on that User's page. A hint carries
  its Cause, a count of Users, and an anchor in `docs/troubleshooting.md`. It names no User, rule,
  calendar, or account. The thresholds are named constants. Hints and their "How to fix" links are
  for administrators' Causes and these patterns only, never for one User's own Cause.

## Alternatives considered

- **Store Google's message.** It explains more, but it can quote calendar identifiers and request
  addresses, it is English only, and it would reach administrators through hints.
- **Store the raw reason code.** It is provider vocabulary in the application and an open set the
  Web UI cannot translate; mapping it to a closed set at the adapter keeps both honest. Logging a
  short unrecognized code gives administrators the same evidence without persisting it.
- **Let administrators nudge a User**, with a note to copy or a reminder. It turns the Operator
  Overview into a support channel and leaks the administrator's view into the User's inbox; a User
  whose dashboard names the one step needs no message.
- **A third owner, "nobody", for conditions that retry by themselves.** The User is the one who
  waits and the one who sees the rule recover, so it is theirs, with no step.
- **Change what an administrator's Cause does**, such as retrying an account the provider refuses
  because the Calendar API is off instead of lapsing it. That changes the recovery model of ADR
  0027 and is left for its own decision; until then a User whose account lapsed for an
  administrator's Cause is offered Check access to try again, which restarts their rules once the
  administrator has fixed it.

## Consequences

Migration 26 adds `incidents.cause` and `rule_run_outcomes.failure_cause`. Earlier releases ignore
both columns, so rolling back works with the same database. Adding a Cause later is a code change
in the adapter, the enum, the Web UI's catalogs, and the troubleshooting guide; an earlier Web UI
shows a Cause it does not know as unknown. A provider other than Google needs its own mapping, and
until it has one its failures are `unknown`. The scheduler reports when its next pass begins, so a
User waiting on Google can be told when it tries again.
