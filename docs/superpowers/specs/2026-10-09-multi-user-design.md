# Multi-user installations: design

Settled decisions are recorded in [ADR 0028](../../adr/0028-plans-apart-from-commercial-mode.md),
[ADR 0029](../../adr/0029-isolate-users-in-one-sqlite-database.md), and
[ADR 0030](../../adr/0030-users-administrators-and-registration.md); terms are in `CONTEXT.md`.
This document holds the delivery order.

## Goal

One installation serves a household on a home server and, with the same code, the Hosted Service.
Each User's rules stay private; an Installation Administrator can see whether everyone's
synchronization works, and can limit Users with Plans; billing can be added without changing the
model.

## Phases

Each phase can be released alone and keeps existing installations working.

0. **Groundwork.** SQLite in WAL mode; the scheduler runs a bounded number of rules at once, ordered
   fairly between Users.
1. **Users.**
   - **1a. Scoping, one User.** Email sign-in, the upgrade path from the single administrator,
     `user_id` on every owned table with composite references, the User-scoped and
     installation-wide units of work, and every isolation test. Invisible to existing installations.
   - **1b. A second User.** Invitations, Password Reset Links, the Installation Administrator role,
     Incident Notifications to the owning User, Integration Tokens per User with the
     `installation:read` scope and Installation Health, Disabled Users, and User Deletion.
2. **Operator Overview.** The administrator's view, each User's page showing what the overview shows
   about them, and provider calls and storage counted per User.
3. **Plans.** Plan definitions and assignment, the four limits, a per-User sync interval in the
   scheduler, and Plan Hold.
4. **Open registration.** The sign-up page, email verification, self-service password reset, sign-up
   rate limits, and continuous backup guidance for the Hosted Service.
5. **Billing.** Commercial Mode, a payment-provider port and one adapter, and webhooks that set a
   User's Plan.

## Deferred

- Users' own webhooks, until outbound requests can refuse private and loopback addresses.
- A record of administrator actions, until the Hosted Service has support staff.
- Export of a User's data.
- Sign-in through OIDC providers.
- Time-limited sharing of calendar names with an administrator, chosen by the User.
- A workspace above the User for teams.
