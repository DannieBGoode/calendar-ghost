# Record Lapsed Authorization on the account and resume its rules after Reauthorization

## Context

When Google stops accepting a Connected Account's credentials, Calendar Ghost records the failure
on the rule run, the Degraded Rule, and an Incident, but not on the account. The account stays
`connected`, so Settings shows it as healthy, Check access reports only a generic failure, and the
Rules page and Overview offer "Preview to restart". That preview reads with the same rejected
credentials and fails. Only Activity points the administrator to Settings.

After the administrator reauthorizes, every affected rule still needs a recovery preview and
"Start syncing" (domain model, Degraded Rule). The preview gate exists to show the privacy and
write consequences of a configuration. An expired grant changes neither.

## Decision

- **Lapsed Authorization is a condition of the Connected Account.** It is persisted on the
  account, set by any provider request refused for authentication or authorization (a sync run, a
  preview, an access check), and cleared by Reauthorization or by an access check the provider
  accepts. A false 401 during a provider outage therefore needs no OAuth round trip, while a
  refresh token the provider revoked can never pass a check. It is separate from the
  connected or disconnected state: the credentials stay stored and the rules keep their mappings
  and incremental positions. Settings, Rules, the Overview, Installation Status, and MCP read this
  one fact to choose the next step, which is "Reauthorize account" for the account that lapsed.
- **A rule stopped only by Lapsed Authorization resumes on its own.** The Degraded Rule records
  why it stopped. When every account it uses is authorized again, whether by Reauthorization or a
  passing access check, a rule whose only stop cause is
  Lapsed Authorization returns to Enabled. Its next scheduled run continues from its preserved
  incremental positions in both calendars, as enabling after a preview does, so changes made in
  either calendar while it was stopped are synchronized or repaired, and any ownership doubt
  becomes a Conflict.
- **One Incident per lapsed account.** An authentication or authorization failure opens or
  updates a single Incident keyed by the Connected Account rather than one per rule. It names every
  rule the lapse stopped, sends one Incident Notification, and resolves when the lapse clears.
  Other provider failures keep their per-rule Incidents, because their causes are per rule.
- **Installation Status keeps its privacy contract.** A rule stopped by Lapsed Authorization is a
  stopped problem with that cause. The status names no account (ADR 0024); the Web UI resolves the
  account from its own records to name it and link to its Settings row.
- **Every other stop still needs a recovery preview.** A disconnected account, a provider
  rejection other than authorization, an incomplete removal, or a Material Rule Change made while
  the rule was stopped keeps today's preview and "Start syncing" path.

## Alternatives considered

- Deriving the account's condition in each view from open Incidents needs no schema change, but
  it leaves each view to guess and gives Check access nowhere to record what it learned.
- Keeping the recovery preview after Reauthorization and listing the waiting rules on the OAuth
  return is stricter, but it asks the administrator to approve a configuration that did not change
  each time a Google grant expires.

## Consequences

The Degraded Rule gains a recorded stop cause. Check access is no longer read-only: a passing
check can restart rules, and its result says how many. `docs/domain-model.md` and `docs/troubleshooting.md`
describe the recovery preview as the only way back and change with the implementation. An Incident
for Lapsed Authorization names no rule, so Incident Notifications may carry a null `rule_id`.
Migration 20 marks accounts and rules that an open authorization Incident already stopped, so an
upgraded installation shows the account to reauthorize at once.
