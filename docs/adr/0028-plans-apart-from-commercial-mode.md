# Separate Plans from Commercial Mode

Amends [ADR 0023](0023-hosted-service-runs-the-open-codebase.md).

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
