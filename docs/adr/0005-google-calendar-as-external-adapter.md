# Treat Google Calendar as an external adapter

Amended by [ADR 0022](0022-route-calendar-requests-by-provider.md), which routes requests to one
adapter per provider now that more providers are planned.

## Context

Google exposes provider-specific event dictionaries, ETags, sync tokens, recurrence conventions, private extended properties, scopes, and error responses. Those details are not synchronization policy.

## Decision

Translate Google representations into provider-neutral Calendar Events at the infrastructure boundary and translate Event Projections back into Google write payloads. Application use cases depend on a Calendar Provider port.

## Alternatives considered

- Passing Google dictionaries through the domain would reduce translation code but make the core dependent on one provider and harder to test.
- Designing a universal provider plugin system now would speculate beyond the real Google boundary.

## Consequences

The adapter owns unavoidable translation loss and provider metadata. Future providers can implement the proven port without changing fundamental decisions, but no unused provider framework is introduced.
