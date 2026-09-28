# Remove rules explicitly and replace calendars instead of editing them

## Context

Administrators need to change or retire Directional Sync Rules. A rule's Event Mappings and
Managed Origin metadata bind every projection to one source and one destination. Moving a rule to
another calendar in place would leave mappings pointing at calendars the rule no longer manages, and
stripping ownership from retained events would let a reverse rule treat them as Native Events.

## Decision

- Transformation policy and all-day eligibility are editable as a Material Rule Change that
  stops synchronization, requires a new Rule Preview, and reprojects every mapping on the next run.
- Source and destination calendars are never edited in place. A Rule Replacement validates the new
  relationship, performs Rule Removal, and creates a new draft with the same policy.
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
