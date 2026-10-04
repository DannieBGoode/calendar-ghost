# Run the hosted service from the open codebase

Supersedes [ADR 0020](0020-single-installation-community-edition.md) and amends the hosted-service
decision in [ADR 0021](0021-community-edition-agpl.md).

## Context

ADR 0020 kept the Community Edition single-installation and placed multi-tenancy, billing, and
hosted operations in a separate hosted composition boundary. That boundary has two problems.

First, it does not scale cheaply. The safest form of it, one isolated application and database per
customer, costs one process for each customer and makes every upgrade and backup a fleet operation.

Second, it creates a license boundary that is hard to keep clean. Contributions arrive under the
AGPL with no CLA (ADR 0021). Closed hosted code that runs in the same process as contributed code
would be one combined work under the AGPL. Keeping hosted code closed would need either a CLA or a
strict separation into programs that only talk over the network, plus a legal review of that line.

[keeper.sh](https://github.com/ridafkih/keeper.sh), an AGPL calendar synchronization product, shows
a simpler model that self-hosting communities accept: one open codebase serves both self-hosted and
hosted users. Multi-user support, plan limits, and payment webhooks are all public, and a single
commercial-mode switch decides whether plan limits apply. When the switch is off, every user gets
every feature.

## Decision

- There is one codebase. The hosted service runs the same AGPL code as a self-hosted installation.
  It has no closed components and no private fork.
- One installation may serve many users. A new installation starts with one user, the Installation
  Administrator, so a single-person self-hosted deployment looks and behaves as it does today.
- Billing, plans, and payment-provider webhooks live in this repository behind **Commercial Mode**.
  Commercial Mode is off by default. When it is off, every user has every feature with no plan
  limits, and no billing code runs or contacts a payment provider.
- Plan limits apply only when Commercial Mode is on. The hosted service may offer a limited free
  plan; a self-hosted installation never has features removed, limited, or held back.
- The operator overview is an administrator role in this repository, not a separate tool. It shows
  operational data such as health, failing rules, and plan status. It never shows another user's
  event content, which keeps the existing rule that event content never reaches logs, incidents,
  or notifications.
- Payment-provider credentials and other hosted secrets are configuration, never code.
- Until the multi-user work lands, the runtime stays as it is today: one Installation
  Administrator, one SQLite database, and one application process. The persistence choice for
  many users (ADR 0004) and the per-user data isolation design each need their own ADR before
  implementation.

## Consequences

The hosted service needs no license boundary, no CLA, and no separate legal line between open and
closed code. Self-hosters can read every line the hosted service runs, including billing, and can
verify that Commercial Mode off means no limits. A competitor can run the same code, including the
billing path, so the business competes on operations, trust, support, and the Calendar Ghost name,
as ADR 0021 already accepted.

Multi-user support becomes a product feature for self-hosters too, for example a household or a
small team on one installation. In exchange, every persisted record and every query gains an owner
boundary. A missing ownership filter becomes a privacy defect between users, so the tenant boundary
needs the same contract-test discipline as Managed Origin ownership.

Documents that describe the current runtime as single-installation stay accurate until the
multi-user work ships, and change with that work. Documents that described the hosted service as a
separate composition boundary change now.

## Alternatives considered

- **One isolated application and database per customer, with a closed control plane.** Rejected as
  the long-term model: it keeps the core unchanged but costs one process per customer and turns
  upgrades, backups, and monitoring into fleet operations. It remains a possible stopgap if hosting
  starts before multi-user support is ready.
- **A private repository that imports this one and adds multi-tenancy and billing.** Rejected: with
  AGPL contributions and no CLA, the combined program falls under the AGPL, so the private code
  would not stay private without a CLA that self-hosting users distrust.
- **Open core with a commercially licensed `ee/` directory.** Rejected: it creates two licenses in
  one repository and invites the open-core distrust that ADR 0021 set out to avoid.
