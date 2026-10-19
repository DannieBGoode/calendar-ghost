# Separate Plans from Commercial Mode

Amends [ADR 0023](0023-hosted-service-runs-the-open-codebase.md). Amended by
[ADR 0038](0038-plans-allowances-and-limits.md), which records how Plans work.

## Context

ADR 0023 put plans, plan limits, and billing behind one switch, Commercial Mode, which only the
Hosted Service turns on. That leaves two needs unmet.

A household installation shared by several Users has finite resources: one small computer and one
Google project quota that every User draws from. Its Installation Administrator has no way to keep
one User's thirty rules from slowing everyone else.

The Hosted Service also needs plans before it needs billing. It should be able to open sign-up with
a free plan and move early or paying Users to a larger one by hand, then add a payment provider
later without changing the model.

## Decision

- **Plans** are an installation setting that any Installation Administrator may turn on. It is off
  by default. When it is off, every User has every feature with no limits, as before.
- When Plans are on, the Installation Administrator defines each Plan's limits and assigns a Plan to
  each User. A Plan only limits; it never hides a feature's existence or the Operator Overview.
- A Plan limits only resources: the number of Directional Sync Rules, the number of Connected
  Accounts, the shortest sync interval, and Integration Tokens. It never limits how a rule projects
  events (Busy-Only or Details Projection, all-day policy, invitation responses) or the tools a User
  needs to see and recover from a problem (Rule Preview, Reconcile Now, incidents, notifications,
  and Activity), so no privacy or safety feature is held back for payment. Manual runs are
  protected by a fixed rate limit for every User instead of a Plan limit.
- **Commercial Mode** now means billing only: it lets a payment provider set a User's Plan. It
  requires Plans to be on and a payment provider to be configured. When it is off, no billing code
  runs or contacts a payment provider.
- The self-hosting promise becomes: the project never limits an installation; only that
  installation's own administrator can, and only by choosing to turn Plans on.

## Consequences

Plans, their enforcement, and their tests are the same code on every installation, so self-hosters
can read exactly how the Hosted Service limits its free plan. Billing becomes a narrow adapter that
writes a User's Plan assignment, beside the administrator who can write the same assignment by hand.
Lowering a User's limits never deletes their rules or projections. Rules beyond the new limit keep
running for a 7-day grace period, then are held as Plan Holds, which keep their mappings and resume
by themselves, without a new preview, once the limit allows them again. This adds a second
self-resuming stop beside Lapsed Authorization (ADR 0027).

## Alternatives considered

- **Limits only in Commercial Mode (ADR 0023 unchanged).** Rejected: a household administrator could
  not protect shared resources, and the Hosted Service could not run plans before billing exists.
- **Installation-wide resource settings without plans.** Rejected: the Hosted Service needs plans
  anyway, so this would build two limit mechanisms.

## Amendment: what the design of Plans settled (2026-10-15)

The design of Plans ([ADR 0038](0038-plans-allowances-and-limits.md)) settled what this record left
open:

- **The Hosted Service drives Plans.** On the Hosted Service, Instant Sync may be only for Plans
  that cost more, and a free Plan may sync every 5 to 10 minutes. A self-hosted installation has
  every feature and no limits unless its own administrator turns Plans on.
- **A Default Plan.** The administrator marks one Plan as the default, which every User without a
  Plan of their own has, and billing will return a User to it when a payment ends. Turning Plans
  on with no default makes a Plan named "No limits" the default.
- **Installation Administrators are never limited.** Under Only Me the only User administers, so
  Plans have no effect there, and the Web UI hides them.
- **Sync intervals are a fixed list:** Instant, 5, 10, 15, 30, and 60 minutes, where Instant means
  Instant Sync plus a five-minute Scheduled Sync. The Plan decides the interval, in place of "the
  shortest sync interval" above, and the User keeps only their own choice to turn Instant Sync
  off. Plans offer all six intervals, as decided in
  [ADR 0038](0038-plans-allowances-and-limits.md#slice-2-each-rule-once-per-window-of-its-interval).
- **Manual runs are limited only for a User whose Plan limits anything,** in place of "a fixed
  rate limit for every User" above. Sync Now, Reconcile Now, and Rule Preview share 12 runs in any
  60 minutes, one every 5 minutes, the shortest sync interval, so a script pressing Sync Now polls
  no more often than the fastest Plan syncs. While Plans are off, for administrators, and on a Plan
  that limits nothing, such as No limits, nothing counts them. Every Plan that counts them has the
  same limit, so it is not a Plan limit, and its refusal never names a Plan
  ([ADR 0038](0038-plans-allowances-and-limits.md#slice-3-the-manual-run-limit)).

Until Plan Hold ships, a lowered rule limit refuses new Starts and stops nothing: rules beyond it
keep syncing, and no grace period starts.
