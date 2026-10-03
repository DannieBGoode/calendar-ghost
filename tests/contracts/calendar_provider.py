"""What every Calendar Provider adapter must honor, asked only through the provider ports.

An adapter passes this suite before it is composed (ADR 0022). A subclass supplies a harness
that can place a Native Event in its backend, as the calendar's owner would.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest

from calendar_sync.application.errors import ProjectionOwnershipMismatch
from calendar_sync.application.ports import CalendarProvider
from calendar_sync.domain.model import (
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    SyncRuleId,
    TimedInterval,
)
from tests.helpers import NOW, endpoint, event

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
RULE_ID = SyncRuleId("rule-1")
OTHER_RULE_ID = SyncRuleId("rule-2")
WINDOW_START = NOW - timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ProviderHarness:
    provider: CalendarProvider
    seed: Callable[[CalendarEvent], object]
    """Place a Native Event in the provider, as the calendar's owner would create it."""


def _projection(title: str = "Busy") -> EventProjection:
    return EventProjection(time=TimedInterval(NOW, NOW + timedelta(hours=1)), title=title)


def _create(
    harness: ProviderHarness, key: str, rule_id: SyncRuleId = RULE_ID, source_id: str = "source"
) -> CalendarEvent:
    source = event(source_id, calendar=SOURCE).reference
    created = harness.provider.create_projection(DESTINATION, source, rule_id, _projection(), key)
    return created.destination_event


class CalendarProviderContract:
    @pytest.fixture
    def harness(self) -> ProviderHarness:
        raise NotImplementedError

    def test_a_created_projection_reads_back_owned_by_its_rule_and_source(
        self, harness: ProviderHarness
    ) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.get_event(created.reference)

        assert found is not None
        assert found.status is EventStatus.CONFIRMED
        assert found.title == "Busy"
        assert found.managed_origin == ManagedOrigin(
            RULE_ID, event("source", calendar=SOURCE).reference
        )

    def test_one_operation_key_creates_one_projection(self, harness: ProviderHarness) -> None:
        first = _create(harness, "key-1")
        second = _create(harness, "key-1")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert second.reference == first.reference
        assert [projection.reference for projection in listed] == [first.reference]

    def test_only_a_known_operation_key_finds_a_projection(self, harness: ProviderHarness) -> None:
        created = _create(harness, "key-1")

        found = harness.provider.find_projection(DESTINATION, "key-1")

        assert found is not None
        assert found.reference == created.reference
        assert harness.provider.find_projection(DESTINATION, "key-never-used") is None

    def test_managed_events_list_only_this_rules_projections(
        self, harness: ProviderHarness
    ) -> None:
        harness.seed(event("native-event", calendar=DESTINATION))
        mine = _create(harness, "key-1")
        _create(harness, "key-2", OTHER_RULE_ID, "other-source")

        listed = harness.provider.managed_events(DESTINATION, RULE_ID, WINDOW_START)

        assert [projection.reference for projection in listed] == [mine.reference]

    def test_an_event_that_never_existed_reads_as_none(self, harness: ProviderHarness) -> None:
        missing = EventRef(DESTINATION, EventId("never-existed"))

        assert harness.provider.get_event(missing) is None

    def test_deleting_a_projection_twice_is_quiet(self, harness: ProviderHarness) -> None:
        created = _create(harness, "key-1")
        source = event("source", calendar=SOURCE).reference

        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")
        harness.provider.delete_projection(created.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(created.reference)
        assert found is None or found.status is EventStatus.CANCELLED

    def test_another_rules_projection_is_never_updated_or_deleted(
        self, harness: ProviderHarness
    ) -> None:
        theirs = _create(harness, "key-1", OTHER_RULE_ID)
        source = event("source", calendar=SOURCE).reference

        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.update_projection(
                theirs.reference, source, RULE_ID, _projection("Changed"), "key-update"
            )
        with pytest.raises(ProjectionOwnershipMismatch):
            harness.provider.delete_projection(theirs.reference, source, RULE_ID, "key-delete")

        found = harness.provider.get_event(theirs.reference)
        assert found is not None
        assert found.title == "Busy"

    def test_a_full_listing_reports_native_events_without_a_managed_origin(
        self, harness: ProviderHarness
    ) -> None:
        native = event("native-event", calendar=SOURCE)
        harness.seed(native)

        listing = harness.provider.changes(SOURCE, None, WINDOW_START)

        reported = {item.reference: item for item in listing.events}
        assert listing.complete
        assert listing.next_cursor
        assert native.reference in reported
        assert reported[native.reference].managed_origin is None
