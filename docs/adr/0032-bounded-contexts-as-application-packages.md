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
  | `application/sync` | Directional Sync Rules, previews, Sync Runs, occurrences, reconciliation, Rule Removal, Connected Accounts and Lapsed Authorization, rule health and the Incidents it reports, the rule locks, and provider failures, retries, and call counts |
  | `application/identity` | Users, sign-in and sessions, administration, Invitations, Password Reset Links, and Integration Tokens |
  | `application/operations` | Activity, Installation Status, Installation Health and Installation Hints, the Operator Overview, and storage |
  | `application/shared` | The base application error and the clock and identifier ports, which every context uses |

  Each context declares the ports and errors that more than one of its modules use in its own
  `ports.py` and `errors.py`. A small port or error that one use case alone uses, such as the
  query protocols in `operations/activity.py` or the administration errors in
  `identity/administration.py`, stays beside that use case.

- **The contexts depend in one direction:** `operations`, then `identity`, then `sync`, then
  `shared`. An exhaustive `layers` contract in `pyproject.toml` makes `lint-imports` fail on an
  import against this direction, and on an application module outside every context. The order follows the code, not a preference: User Deletion removes a User's
  rules, so `identity` uses `sync`; the Operator Overview reads Users and their rules, so
  `operations` uses both.

- **Connected Accounts and rule health belong to `sync`.** The account use cases are mostly about
  rules: disconnecting an account degrades its rules, deleting it purges them, and a Lapsed
  Authorization stops and later resumes them. Rule health degrades rules when runs fail. Each of
  these reads and changes accounts and rules through the same unit of work, under the rule locks.
  Only deleting an account changes both in one transaction. Disconnection and Lapsed
  Authorization commit in steps, so an interruption between steps can leave them partly done, as
  before this decision. Moving accounts to a context of their own would put this coordination in two contexts that
  both need the other. Google authorization, credentials, and discovery stay in the Google adapter,
  as before.

- **Glossary concepts live in the domain.** `domain/accounts.py` holds the Connected Account and
  its Provider Kind, `domain/audit.py` the Audit Entry, `domain/incidents.py` the Incident report,
  `domain/runs.py` the Sync Run outcome, and `domain/causes.py` the Cause. Read models that only
  one view uses, such as an Incident summary for Activity, stay with that view's ports.

- **SQLite schema migrations are their own module**, `infrastructure/persistence/migrations.py`,
  and the installation-wide unit of work is `infrastructure/persistence/installation.py`, so
  `sqlite.py` holds one User's repositories and unit of work.

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
`UnitOfWork` still holds every repository of a User, so `sync/ports.py` is the largest ports
module; split it further when a context earns its own unit of work.
