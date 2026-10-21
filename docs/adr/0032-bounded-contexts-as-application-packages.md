# Make the bounded contexts packages of the application layer

Builds on [ADR 0001](0001-use-modular-monolith.md) and
[ADR 0002](0002-use-domain-driven-design.md).

## Context

ADR 0001 promises bounded-context boundaries "in modules and dependency direction", and
`docs/architecture.md` names the contexts. The code did not show them. `application/` was one flat
package of 28 modules, and `application/ports.py` declared every port of every context in one
module of more than 1,300 lines. Each new feature added to the same files, and nothing stopped a
use case of one context from reaching into another. Some concepts in the glossary, such as
Connected Account, Audit Entry, Incident, and Cause, were declared as application types, so the
domain could not name them.

The project expects many more providers and features. A boundary that only the documentation
states will not hold while it grows.

## Decision

- **The application layer has one package for each context**, and a `shared` package below them:

  | Package | Owns |
  | --- | --- |
  | `application/sync` | Directional Sync Rules, previews, Sync Runs, occurrences, reconciliation, Rule Removal, Connected Accounts and Lapsed Authorization, applying rule health and reporting its Incidents, the rule locks, and provider failures, retries, and call counts |
  | `application/identity` | Users, sign-in and sessions, administration, Invitations, Password Reset Links, and Integration Tokens |
  | `application/operations` | Activity, Installation Status, Installation Health and Installation Hints, the Operator Overview, and storage |
  | `application/shared` | The base application error and the clock and identifier ports, which every context uses |

  Shared ports live in each context's `ports.py` or focused `*_ports.py` siblings, and shared
  errors in `errors.py`. Synchronization groups provider, account, record, health, plan, and run
  ports in focused siblings while keeping its single unit of work in `sync/ports.py`. A
  use-case module may also declare ports and errors of its own beside its use cases, such as the
  query protocols in `operations/activity.py` and the administration errors in
  `identity/administration.py`. Other modules, in the same context or one above it, import those
  from that module.

- **The contexts depend in one direction:** `operations`, then `identity`, then `sync`, then
  `shared`. An exhaustive `layers` contract in `pyproject.toml` makes `lint-imports` fail on an
  import against this direction, and on an application module outside every context. The order
  follows the code, not a preference: User Deletion removes a User's rules, so `identity` uses
  `sync`; the Operator Overview reads Users and their rules, so `operations` uses both.

- **Connected Accounts and rule health belong to `sync`.** The account use cases are mostly about
  rules: disconnecting an account degrades its rules, deleting it purges them, and a Lapsed
  Authorization stops and later resumes them. Rule health degrades rules when runs fail. The
  application coordinates rule health in `RuleHealth`, but the policy it applies, which failures
  stop a rule and when trouble opens an Incident, is a domain rule in `domain/health.py`. It reads a
  failure only through the domain's `ProviderFailureFacts`, so the domain names no application error
  (#104). Each of these use cases coordinates accounts and rules, but only deleting an account
  changes both in one transaction. Disconnection degrades each previewed or enabled rule that uses
  the account, and makes one awaiting reauthorization need a preview, each in its own transaction
  under that rule's lock, then disconnects the account in another. Lapsed Authorization records the
  lapse, then stops each enabled rule of the account, then opens its Incident, each committed
  separately. Restoring it clears the lapse, then resolves the Incident, then resumes each rule the
  lapse alone stopped once both of its accounts are authorized. Moving accounts to a context of
  their own would put this coordination in two contexts that both need the other. Google
  authorization, credentials, and discovery stay in the Google adapter, as before.

- **Glossary concepts live in the domain.** `domain/accounts.py` holds the Connected Account and its
  Provider Kind, `domain/audit.py` the Audit Entry, `domain/incidents.py` the Incident report,
  `domain/runs.py` the Sync Run outcome, `domain/causes.py` the Cause, and `domain/health.py` the
  rule health policy. Read models that only one view uses, such as an Incident summary for Activity,
  stay with that view's ports.

- **SQLite schema migrations are their own module**, `infrastructure/persistence/migrations.py`,
  and the installation-wide unit of work is `infrastructure/persistence/installation.py`, so
  `sqlite/unit_of_work.py` holds one User's unit of work. Its Synchronization repositories live
  in `sqlite/sync/accounts.py`, `sqlite/sync/rules.py`, `sqlite/sync/mappings.py`, and
  `sqlite/sync/records.py`, with shared ownership and time helpers in `sqlite/shared.py`. Existing
  identity and operations adapters stay in their focused persistence modules.

## Alternatives considered

- **A fourth context for Connected Accounts below `sync`.** Rejected: the account use cases change
  rules, so the dependency points from accounts to rules, not the other way.
- **One unit of work for each context.** This would let each context own its repositories alone.
  It is deferred: account deletion relies on one unit of work to remove an account and its rules
  atomically, and splitting it changes behavior, which this decision does not.
- **Keep the flat package and rely on the documentation.** Rejected for the reasons in the context.

## Consequences

A use case's module path names its context, and an import across contexts in the wrong direction
fails the build. Ports and errors grow inside their context instead of in one shared module. The
`UnitOfWork` still holds every repository of a User in `sync/ports.py`. Shared ports may split
into focused sibling modules without a new unit of work, as authorized by ADR 0040. The
Synchronization port split keeps the transaction boundary and the context dependency direction.
