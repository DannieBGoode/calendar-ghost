from __future__ import annotations

from calendar_sync.domain.model import (
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionFingerprint,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import rule, week_start

SERIES = EventMapping(
    EventMappingId("series-mapping"),
    rule().id,
    EventRef(rule().source, EventId("source-series")),
    EventRef(rule().destination, EventId("projection-1")),
    "r-1",
    ProjectionFingerprint("f"),
)
OCCURRENCE = OccurrenceMapping(
    OccurrenceMappingId("o-1"),
    SERIES.id,
    week_start(1),
    EventRef(rule().source, EventId("source-series_1")),
    EventRef(rule().destination, EventId("projection-1_1")),
    OccurrenceState.CANCELLED,
    "r-1",
)


def _factory() -> InMemoryUnitOfWorkFactory:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(SERIES)
        uow.occurrences.save(OCCURRENCE)
        uow.commit()
    return factory


def test_memory_occurrences_cascade_with_their_series_mapping() -> None:
    factory = _factory()
    with factory() as uow:
        uow.mappings.delete(SERIES)
        uow.commit()

    assert factory.state.occurrences == {}


def test_memory_occurrences_cascade_with_rule_removal() -> None:
    factory = _factory()
    with factory() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    assert factory.state.occurrences == {}


def test_memory_occurrences_require_an_existing_series_mapping() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        try:
            uow.occurrences.save(OCCURRENCE)
        except KeyError:
            return
    raise AssertionError("an occurrence mapping without its series mapping was accepted")
