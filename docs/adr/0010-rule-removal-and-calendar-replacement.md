# Remove rules explicitly and replace calendars instead of editing them

Amended by [ADR 0038](0038-plans-allowances-and-limits.md): a Rule Replacement's new draft is
created in the transaction that begins the previous rule's removal.

## Context

Administrators need to change or retire Directional Sync Rules. A rule's Event Mappings and
Managed Origin metadata bind every projection to one source and one destination. Moving a rule to
another calendar in place would leave mappings pointing at calendars the rule no longer manages, and
stripping ownership from retained events would let a reverse rule treat them as Native Events.

## Decision

- Transformation policy and all-day eligibility are editable as a Material Rule Change that
  stops synchronization, requires a new Rule Preview, and reprojects every mapping on the next run.
- Source and destination calendars are never edited in place. A Rule Replacement creates a new
  draft with the same policy first, which reserves the relationship through its uniqueness
  constraint, and only then performs Rule Removal of the previous rule. An interrupted removal
  leaves the new draft and a retryable previous rule.
- Rule Removal requires an explicit choice: delete mapped projections (recommended, requires an
  authorized destination) or keep them as Detached Events. Detached Events keep the removed rule's
  origin metadata and receive no provider write.
- Removal marks the rule Disabled first and commits per mapping, so a provider failure leaves a
  resumable, inert rule rather than a half-removed one.

## Alternatives considered

- In-place calendar edits would require re-homing or re-validating every mapping and invite
  ownership ambiguity.
- Stripping origin metadata from Detached Events makes them ordinary but lets `B -> A` rules copy
  them back as duplicates, and adds one provider write per event.
- Keeping an enabled rule running on its previous policy until re-enabled requires a second pending
  configuration per rule.

## Consequences

Replacement produces a new rule identity; its history starts fresh, while the removed rule's audit
entries remain. Detached Events can never be adopted by a later rule. Interrupted removals are
visible as "Removal incomplete" until retried.

## Amendment: the new draft is created when the removal begins (2026-10-15)

A Rule Replacement no longer creates its new draft first. It checks for a duplicate relationship,
then hands the draft to Rule Removal as the previous rule's successor. Once the removal has waited
for the previous rule's run, it inserts the draft, with the checks every new rule passes, in the
same transaction that moves the previous rule to Removing. If a check fails, such as a duplicate
relationship that appeared meanwhile or an account the User no longer has, the transaction rolls
back: the previous rule stays as it was, and no draft exists.

Before, the draft was visible while the removal waited, and a removal that then failed deleted it
without its locks, even after a client had started it. Now no client sees the draft before the
removal begins, and no cleanup path deletes it. The uniqueness constraint still reserves the
relationship before anything destructive happens, and an interrupted removal still leaves the new
draft and a retryable previous rule. When the previous rule counted toward its User's Plan, the
draft also keeps its place under the rule limit
([ADR 0038](0038-plans-allowances-and-limits.md)).
