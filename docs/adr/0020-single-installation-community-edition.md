# Keep the Community Edition single-installation

## Context

Calendar Ghost is intended to make self-hosted synchronization affordable and private. The current
deployment has one Installation Administrator, one SQLite database, one scheduler, and one process.
All persisted records therefore belong to one local installation without an explicit tenant column.

A future hosted service may serve many customers from managed infrastructure, but adding hosted
authentication, billing, quotas, or tenant routing to the self-hosted runtime would make the local
deployment harder to understand and harder to audit for data ownership.

## Decision

- The Community Edition remains a single-installation, single-administrator deployment backed by one
  SQLite database and one application process.
- Its public behavior, migrations, backup format, and operator documentation are installation-scoped.
- The Community Edition does not add tenant identifiers, billing, hosted accounts, a remote control
  plane, or SaaS-only feature flags.
- The future hosted service is a separate product and composition boundary. It may reuse provider-
  independent domain and application modules, but it must introduce an explicit customer boundary,
  authentication model, data isolation, job execution model, and operational controls before it
  serves more than one customer.
- The safest first hosted deployment is one isolated application and database per customer. A pooled
  multi-tenant design is a later decision that requires a separate persistence and security review.

## Consequences

Self-hosting stays inexpensive: an operator needs one container, one durable data volume, and no
hosted account. Privacy review remains tractable because every local record belongs to one
installation. The hosted service cannot be created by merely exposing this API to multiple
customers; it needs a deliberate isolation design.

The domain and application layers remain reusable because they already depend on provider and
persistence ports. Hosted-only policy belongs in the hosted composition boundary rather than in the
synchronization domain.

## Alternatives considered

- **Add `tenant_id` everywhere now.** Rejected: it adds complexity and a false sense of hosted
  isolation to a product whose local deployment has no customer boundary yet.
- **Make the Community Edition a hosted multi-tenant runtime.** Rejected: it conflicts with the
  self-hosted privacy model and the one-process SQLite deployment.
- **Create a second synchronization engine for the hosted service.** Rejected: provider-independent
  domain decisions and application ports should remain shared; only hosted composition and
  infrastructure need to differ.
