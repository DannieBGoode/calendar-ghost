from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.domain.model import (
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    InvitationResponse,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.google.provider import (
    OCCURRENCE_EXCEPTION_FIELDS,
    OCCURRENCE_PAGE_LIMIT,
    GoogleCalendarProvider,
)
from calendar_sync.infrastructure.google.translation import (
    RULE_PROPERTY,
    SOURCE_ACCOUNT_PROPERTY,
    SOURCE_CALENDAR_PROPERTY,
    SOURCE_EVENT_PROPERTY,
)
from tests.helpers import NOW, endpoint, event


class GoogleResponse(dict[str, str]):
    """Mirrors httplib2.Response: lower-cased headers plus an integer status."""

    def __init__(self, status: int, headers: dict[str, str]) -> None:
        super().__init__({key.lower(): value for key, value in headers.items()})
        self.status = status


class GoogleApiError(Exception):
    def __init__(
        self,
        status: int,
        *,
        reason: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"synthetic Google status {status}")
        self.resp = GoogleResponse(status, headers or {})
        self.content = (
            b""
            if reason is None
            else ('{"error":{"errors":[{"reason":"' + reason + '"}]}}').encode()
        )


def request_returning(payload: dict[str, object]) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = payload
    return request


def request_raising(
    status: int, *, reason: str | None = None, headers: dict[str, str] | None = None
) -> MagicMock:
    request = MagicMock()
    request.execute.side_effect = GoogleApiError(status, reason=reason, headers=headers)
    return request


def google_event_payload(event_id: str = "event-1") -> dict[str, object]:
    return {
        "id": event_id,
        "etag": f"etag-{event_id}",
        "summary": "Private appointment",
        "start": {"dateTime": "2026-08-30T10:00:00+00:00"},
        "end": {"dateTime": "2026-08-30T11:00:00+00:00"},
    }


@dataclass(frozen=True)
class FixedClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def provider_with_events_api(
    events_api: MagicMock, clock: FixedClock | None = None
) -> GoogleCalendarProvider:
    service = MagicMock()
    service.events.return_value = events_api
    return GoogleCalendarProvider(lambda _account_id: service, clock)


def test_changes_paginates_and_returns_the_final_sync_token() -> None:
    events_api = MagicMock()
    events_api.list.side_effect = [
        request_returning({"items": [google_event_payload("one")], "nextPageToken": "page-2"}),
        request_returning({"items": [google_event_payload("two")], "nextSyncToken": "cursor-2"}),
    ]
    provider = provider_with_events_api(events_api)

    result = provider.changes(
        endpoint("account", "calendar"),
        None,
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert [item.reference.event_id.value for item in result.events] == ["one", "two"]
    assert result.next_cursor == "cursor-2"
    assert result.complete
    first_parameters = events_api.list.call_args_list[0].kwargs
    second_parameters = events_api.list.call_args_list[1].kwargs
    assert first_parameters["timeMin"] == "2026-07-31T00:00:00+00:00"
    assert second_parameters["pageToken"] == "page-2"


def test_expired_google_sync_token_recovers_with_a_full_window_request() -> None:
    events_api = MagicMock()
    events_api.list.side_effect = [
        request_raising(410),
        request_returning({"items": [], "nextSyncToken": "replacement-cursor"}),
    ]
    provider = provider_with_events_api(events_api)

    result = provider.changes(
        endpoint("account", "calendar"),
        "expired-cursor",
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert result.next_cursor == "replacement-cursor"
    # The replacement is a full listing, so callers must not treat it as changes since a cursor.
    assert result.complete
    assert events_api.list.call_args_list[0].kwargs["syncToken"] == "expired-cursor"
    assert "syncToken" not in events_api.list.call_args_list[1].kwargs
    assert "timeMin" in events_api.list.call_args_list[1].kwargs


def test_incremental_changes_are_not_a_complete_listing() -> None:
    events_api = MagicMock()
    events_api.list.return_value = request_returning({"items": [], "nextSyncToken": "cursor-3"})
    provider = provider_with_events_api(events_api)

    result = provider.changes(
        endpoint("account", "calendar"), "cursor-2", datetime(2026, 7, 31, tzinfo=UTC)
    )

    assert not result.complete


def test_create_projection_reuses_an_existing_operation() -> None:
    events_api = MagicMock()
    events_api.list.return_value = request_returning(
        {"items": [google_event_payload("existing-projection")]}
    )
    provider = provider_with_events_api(events_api)
    projection = EventProjection(
        TimedInterval(
            datetime(2026, 8, 30, 10, tzinfo=UTC),
            datetime(2026, 8, 30, 11, tzinfo=UTC),
        ),
        "Busy",
    )

    created = provider.create_projection(
        endpoint("work", "destination"),
        event().reference,
        SyncRuleId("rule-1"),
        projection,
        "stable-operation-key",
    )

    assert created.destination_event.reference.event_id.value == "existing-projection"
    events_api.insert.assert_not_called()


def test_get_event_returns_none_for_google_not_found() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(404)
    provider = provider_with_events_api(events_api)

    assert provider.get_event(event().reference) is None


def test_google_rate_limit_is_classified_as_retryable() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(429)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as raised:
        provider.get_event(event().reference)

    assert raised.value.kind is ProviderFailureKind.RATE_LIMIT
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "7"}, 7),
        ({"Retry-After": "Mon, 28 Sep 2026 15:18:30 GMT"}, 30),
        ({"Retry-After": "Mon, 28 Sep 2026 15:17:00 GMT"}, 0),
        ({"Retry-After": "Mon, 28 Sep 2026 15:18:10 -0000"}, 10),
        ({"Retry-After": "3600"}, 60),
        ({"Retry-After": "soon"}, None),
        ({}, None),
    ],
)
def test_google_retry_after_hint_is_propagated_and_bounded(
    headers: dict[str, str], expected: int | None
) -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(429, headers=headers)
    provider = provider_with_events_api(
        events_api, FixedClock(datetime(2026, 9, 28, 15, 18, tzinfo=UTC))
    )

    with pytest.raises(ProviderFailure) as raised:
        provider.get_event(event().reference)

    assert raised.value.retry_after_seconds == expected


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [(timedelta(0), 45), (timedelta(seconds=0.5), 45), (timedelta(seconds=40), 5)],
)
def test_google_retry_after_date_counts_down_from_the_injected_clock(
    elapsed: timedelta, expected: int
) -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(
        503, headers={"Retry-After": "Wed, 30 Sep 2026 12:00:45 GMT"}
    )
    clock = FixedClock(datetime(2026, 9, 30, 12, 0, tzinfo=UTC) + elapsed)
    provider = provider_with_events_api(events_api, clock)

    with pytest.raises(ProviderFailure) as raised:
        provider.get_event(event().reference)

    # A partial second rounds up, so a retry never starts before the provider allows it.
    assert raised.value.retry_after_seconds == expected


def test_google_delete_failure_carries_the_retry_after_hint() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning(_managed_payload("managed", "source-event"))
    events_api.delete.return_value = request_raising(503, headers={"Retry-After": "5"})
    provider = provider_with_events_api(events_api)
    destination = event("managed", calendar=endpoint("work-account", "work-calendar")).reference

    with pytest.raises(ProviderFailure) as raised:
        provider.delete_projection(
            destination, event("source-event").reference, SyncRuleId("rule-1"), "operation"
        )

    assert (raised.value.kind, raised.value.retry_after_seconds) == (
        ProviderFailureKind.TEMPORARY,
        5,
    )


def test_google_403_quota_limit_is_retryable_but_permission_denial_is_not() -> None:
    rate_limited_api = MagicMock()
    rate_limited_api.get.return_value = request_raising(403, reason="userRateLimitExceeded")
    denied_api = MagicMock()
    denied_api.get.return_value = request_raising(403, reason="forbidden")

    with pytest.raises(ProviderFailure) as rate_limited:
        provider_with_events_api(rate_limited_api).get_event(event().reference)
    with pytest.raises(ProviderFailure) as denied:
        provider_with_events_api(denied_api).get_event(event().reference)

    assert rate_limited.value.kind is ProviderFailureKind.RATE_LIMIT
    assert rate_limited.value.retryable is True
    assert denied.value.kind is ProviderFailureKind.AUTHORIZATION
    assert denied.value.retryable is False


def test_managed_event_listing_paginates() -> None:
    events_api = MagicMock()
    events_api.list.side_effect = [
        request_returning(
            {"items": [google_event_payload("managed-one")], "nextPageToken": "page-2"}
        ),
        request_returning({"items": [google_event_payload("managed-two")]}),
    ]
    provider = provider_with_events_api(events_api)

    managed = provider.managed_events(
        endpoint("work", "destination"), SyncRuleId("rule-1"), NOW - timedelta(days=30)
    )

    assert [item.reference.event_id.value for item in managed] == [
        "managed-one",
        "managed-two",
    ]
    assert events_api.list.call_args_list[1].kwargs["pageToken"] == "page-2"
    # Only projections that reach the sync window are listed.
    assert events_api.list.call_args.kwargs["timeMin"] == (NOW - timedelta(days=30)).isoformat()


def test_window_listing_includes_cancellations_and_reads_no_sync_token() -> None:
    events_api = MagicMock()
    events_api.list.side_effect = [
        request_returning({"items": [google_event_payload("one")], "nextPageToken": "page-2"}),
        # A listing that never asks for a synchronization token need not receive one.
        request_returning({"items": [google_event_payload("two")]}),
    ]
    provider = provider_with_events_api(events_api)

    listed = provider.list_events(endpoint("personal", "source"), NOW - timedelta(days=30))

    assert [item.reference.event_id.value for item in listed] == ["one", "two"]
    first = events_api.list.call_args_list[0].kwargs
    assert first["showDeleted"] is True
    assert first["timeMin"] == (NOW - timedelta(days=30)).isoformat()
    assert "syncToken" not in first


def _managed_payload(event_id: str, source_event_id: str) -> dict[str, object]:
    source = event(source_event_id).reference
    return {
        **google_event_payload(event_id),
        "extendedProperties": {
            "private": {
                "gcs_rule_id": "rule-1",
                "gcs_source_account_id": source.calendar.connected_account_id.value,
                "gcs_source_calendar_id": source.calendar.calendar_id.value,
                "gcs_source_event_id": source.event_id.value,
            }
        },
    }


def test_deleting_a_projection_already_cancelled_in_google_is_a_no_op() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning({"id": "managed", "status": "cancelled"})
    provider = provider_with_events_api(events_api)
    destination = event("managed", calendar=endpoint("work-account", "work-calendar")).reference

    provider.delete_projection(
        destination, event("source-event").reference, SyncRuleId("rule-1"), "operation"
    )

    events_api.delete.assert_not_called()


def test_deleting_a_projection_that_google_reports_gone_is_a_no_op() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning(_managed_payload("managed", "source-event"))
    events_api.delete.return_value = request_raising(410)
    provider = provider_with_events_api(events_api)
    destination = event("managed", calendar=endpoint("work-account", "work-calendar")).reference

    provider.delete_projection(
        destination, event("source-event").reference, SyncRuleId("rule-1"), "operation"
    )

    events_api.delete.assert_called_once()


def test_deleting_a_projection_owned_by_another_source_is_refused() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning(_managed_payload("managed", "other-source"))
    provider = provider_with_events_api(events_api)
    destination = event("managed", calendar=endpoint("work-account", "work-calendar")).reference

    with pytest.raises(ProjectionOwnershipMismatch) as refused:
        provider.delete_projection(
            destination, event("source-event").reference, SyncRuleId("rule-1"), "operation"
        )
    assert refused.value.kind is ProviderFailureKind.PERMANENT
    events_api.delete.assert_not_called()


def test_deleting_a_native_event_is_refused_as_an_ownership_mismatch() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_returning(google_event_payload("native"))
    provider = provider_with_events_api(events_api)
    destination = event("native", calendar=endpoint("work-account", "work-calendar")).reference

    with pytest.raises(ProjectionOwnershipMismatch):
        provider.delete_projection(
            destination, event("source-event").reference, SyncRuleId("rule-1"), "operation"
        )
    events_api.delete.assert_not_called()


DESTINATION = endpoint("work-account", "work-calendar")
SERIES = EventRef(DESTINATION, EventId("projection-1"))
SOURCE_SERIES = EventRef(
    endpoint("personal-account", "personal-calendar"), EventId("source-series")
)
START = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)


def _owned(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "extendedProperties": {
            "private": {
                RULE_PROPERTY: "rule-1",
                SOURCE_ACCOUNT_PROPERTY: "personal-account",
                SOURCE_CALENDAR_PROPERTY: "personal-calendar",
                SOURCE_EVENT_PROPERTY: "source-series",
            }
        },
    }


def _instance(status: str = "confirmed") -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "projection-1_20260908T080000Z",
        "etag": "instance-etag",
        "status": status,
        "recurringEventId": "projection-1",
        "originalStartTime": {"dateTime": "2026-09-08T08:00:00Z"},
    }
    if status == "confirmed":
        payload |= {
            "summary": "Busy",
            "start": {"dateTime": "2026-09-08T08:00:00Z"},
            "end": {"dateTime": "2026-09-08T09:00:00Z"},
        }
    return payload


def _master() -> dict[str, object]:
    return _owned({**google_event_payload("projection-1"), "recurrence": ["RRULE:FREQ=WEEKLY"]})


def test_get_occurrence_resolves_through_instances_and_verifies_the_start() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    provider = provider_with_events_api(events_api)

    resolved = provider.get_occurrence(SERIES, START)

    assert resolved is not None
    assert resolved.occurrence is not None
    assert resolved.occurrence.original_start == START
    events_api.instances.assert_called_once_with(
        calendarId="work-calendar",
        eventId="projection-1",
        originalStart="2026-09-08T08:00:00Z",
        showDeleted=True,
    )


def _instance_at(start: str, *, series: str = "projection-1") -> dict[str, object]:
    return {
        **_instance(),
        "id": f"{series}_{start}",
        "recurringEventId": series,
        "originalStartTime": {"dateTime": start},
        "start": {"dateTime": start},
        "end": {"dateTime": start.replace("T08", "T09")},
    }


def test_list_occurrences_finds_the_requested_starts_in_one_bounded_listing() -> None:
    later = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    events_api = MagicMock()
    events_api.instances.return_value = request_returning(
        {
            "items": [
                _instance_at("2026-09-08T08:00:00Z"),
                _instance_at("2026-09-15T08:00:00Z"),
                {
                    **_instance("cancelled"),
                    "originalStartTime": {"dateTime": "2026-09-22T08:00:00Z"},
                },
                # Another series' instance never answers for this one.
                _instance_at("2026-09-29T08:00:00Z", series="other-series"),
            ]
        }
    )
    provider = provider_with_events_api(events_api)

    found = provider.list_occurrences(
        SERIES, [START, later, datetime(2026, 9, 29, 8, 0, tzinfo=UTC)]
    )

    assert set(found) == {START, later}
    assert found[later].status is EventStatus.CANCELLED
    events_api.instances.assert_called_once_with(
        calendarId="work-calendar",
        eventId="projection-1",
        showDeleted=True,
        maxResults=2500,
        fields=OCCURRENCE_EXCEPTION_FIELDS,
        # A month past the latest start, so an occurrence moved a little later is still listed.
        timeMax="2026-10-30T08:00:00+00:00",
    )


def test_list_occurrences_stops_paging_once_every_start_is_found() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [], "nextPageToken": "page-2"}),
        request_returning({"items": [_instance_at("2026-09-08T08:00:00Z")], "nextPageToken": "3"}),
    ]
    provider = provider_with_events_api(events_api)

    assert set(provider.list_occurrences(SERIES, [START])) == {START}
    assert events_api.instances.call_count == 2


def test_list_occurrences_of_a_series_google_cannot_expand_finds_nothing() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_raising(404)
    provider = provider_with_events_api(events_api)

    # Finding nothing proves nothing; each occurrence is then looked up on its own.
    assert provider.list_occurrences(SERIES, [START]) == {}


def test_list_occurrences_failures_are_classified() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_raising(503)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.list_occurrences(SERIES, [START])

    assert failure.value.kind is ProviderFailureKind.TEMPORARY


def test_list_occurrences_without_starts_asks_nothing() -> None:
    events_api = MagicMock()
    provider = provider_with_events_api(events_api)

    assert provider.list_occurrences(SERIES, []) == {}
    events_api.instances.assert_not_called()


def _moved_instance() -> dict[str, object]:
    return {
        **_instance(),
        "start": {"dateTime": "2026-09-10T07:00:00Z"},
        "end": {"dateTime": "2026-09-10T08:00:00Z"},
    }


def test_get_occurrence_finds_a_moved_occurrence_that_a_one_result_page_hides() -> None:
    # Observed in Google: with maxResults=1 a moved occurrence's originalStart lookup is empty.
    events_api = MagicMock()
    events_api.instances.side_effect = lambda **parameters: request_returning(
        {"items": [] if parameters.get("maxResults") == 1 else [_moved_instance()]}
    )
    provider = provider_with_events_api(events_api)

    resolved = provider.get_occurrence(SERIES, START)

    assert resolved is not None
    assert resolved.occurrence is not None
    assert resolved.occurrence.original_start == START


def test_get_occurrence_reads_past_empty_pages_before_reporting_absence() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [], "nextPageToken": "page-2"}),
        request_returning({"items": [_moved_instance()]}),
    ]
    provider = provider_with_events_api(events_api)

    assert provider.get_occurrence(SERIES, START) is not None
    assert events_api.instances.call_args.kwargs["pageToken"] == "page-2"


def test_get_occurrence_unanswered_within_the_page_limit_is_a_failure_not_an_absence() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [], "nextPageToken": "next"})
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.get_occurrence(SERIES, START)

    assert failure.value.kind is ProviderFailureKind.TEMPORARY
    assert events_api.instances.call_count == OCCURRENCE_PAGE_LIMIT


def test_get_occurrence_returns_none_only_when_the_series_has_no_such_occurrence() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    provider = provider_with_events_api(events_api)

    assert provider.get_occurrence(SERIES, datetime(2026, 9, 15, 8, 0, tzinfo=UTC)) is None


@pytest.mark.parametrize("status", [404, 410])
def test_get_occurrence_of_an_unreadable_series_is_a_failure_not_an_absence(status: int) -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_raising(status)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.get_occurrence(SERIES, START)

    assert failure.value.kind is ProviderFailureKind.TEMPORARY


def test_has_live_occurrences_lists_instances_without_cancelled_ones() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is True
    events_api.instances.assert_called_once_with(
        calendarId="work-calendar",
        eventId="projection-1",
        showDeleted=False,
        maxResults=250,
        fields="items(status,start),nextPageToken",
    )


def test_has_live_occurrences_never_counts_a_cancelled_instance() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance("cancelled")]})
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is False


def test_has_live_occurrences_skips_all_day_instances_a_rule_excludes() -> None:
    all_day = {**_instance(), "start": {"date": "2026-09-08"}, "end": {"date": "2026-09-09"}}
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [all_day]})
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=False) is False
    assert provider.has_live_occurrences(SERIES, include_all_day=True) is True


def test_has_live_occurrences_reads_past_empty_pages_before_answering() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [], "nextPageToken": "page-2"}),
        request_returning({"items": [_instance()]}),
    ]
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is True
    assert events_api.instances.call_args.kwargs["pageToken"] == "page-2"


def test_has_live_occurrences_is_false_only_when_every_page_is_empty() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": []})
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is False


@pytest.mark.parametrize("status", [400, 404, 410])
def test_has_live_occurrences_of_a_series_google_cannot_expand_counts_as_live(status: int) -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_raising(status)
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is True


def test_has_live_occurrences_stops_at_the_page_limit_without_proving_the_series_empty() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [], "nextPageToken": "next"})
    provider = provider_with_events_api(events_api)

    assert provider.has_live_occurrences(SERIES, include_all_day=True) is True
    assert events_api.instances.call_count == OCCURRENCE_PAGE_LIMIT


def _with_series_master(events_api: MagicMock) -> MagicMock:
    """The source master every unmodified instance repeats: Busy, 08:00-09:00 weekly."""
    master = {
        **_instance(),
        "id": "projection-1",
        "recurrence": ["RRULE:FREQ=WEEKLY"],
    }
    del master["recurringEventId"], master["originalStartTime"]
    events_api.get.return_value = request_returning(master)
    return events_api


def test_occurrence_exceptions_lists_cancelled_and_moved_instances_in_the_window() -> None:
    moved = {
        **_instance(),
        "id": "projection-1_20260915T080000Z",
        "originalStartTime": {"dateTime": "2026-09-15T08:00:00Z"},
        "start": {"dateTime": "2026-09-15T10:00:00Z"},
        "end": {"dateTime": "2026-09-15T11:00:00Z"},
    }
    cancelled = {
        **_instance("cancelled"),
        "id": "projection-1_20260922T080000Z",
        "originalStartTime": {"dateTime": "2026-09-22T08:00:00Z"},
    }
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_returning(
        {"items": [_instance(), moved, cancelled]}
    )
    provider = provider_with_events_api(events_api)
    window = datetime(2026, 8, 30, tzinfo=UTC)

    exceptions = provider.occurrence_exceptions(SERIES, window)

    assert [event.reference.event_id.value for event in exceptions] == [
        "projection-1_20260915T080000Z",
        "projection-1_20260922T080000Z",
    ]
    events_api.instances.assert_called_once_with(
        calendarId="work-calendar",
        eventId="projection-1",
        showDeleted=True,
        maxResults=2500,
        fields=OCCURRENCE_EXCEPTION_FIELDS,
    )


def test_occurrence_exceptions_counts_a_timed_occurrence_moved_to_all_day() -> None:
    all_day = {**_instance(), "start": {"date": "2026-09-08"}, "end": {"date": "2026-09-09"}}
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_returning({"items": [all_day]})
    provider = provider_with_events_api(events_api)

    exceptions = provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC))

    assert len(exceptions) == 1


@pytest.mark.parametrize("status", [400, 404, 410])
def test_occurrence_exceptions_of_a_series_google_cannot_expand_are_none(status: int) -> None:
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_raising(status)
    provider = provider_with_events_api(events_api)

    assert provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC)) == ()


def test_occurrence_exceptions_raise_other_failures() -> None:
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_raising(503)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC))

    assert failure.value.kind is ProviderFailureKind.TEMPORARY


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, ProviderFailureKind.AUTHENTICATION),
        (403, ProviderFailureKind.AUTHORIZATION),
        (429, ProviderFailureKind.RATE_LIMIT),
        (503, ProviderFailureKind.TEMPORARY),
    ],
)
def test_has_live_occurrences_classifies_other_failures_like_any_request(
    status: int, kind: ProviderFailureKind
) -> None:
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_raising(status)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.has_live_occurrences(SERIES, include_all_day=True)

    assert failure.value.kind is kind
    assert failure.value.account_id == DESTINATION.connected_account_id


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        # Google revoked the grant or it expired: only reauthorizing the account recovers.
        (
            RefreshError("invalid_grant: Token has been expired or revoked."),  # type: ignore[no-untyped-call]
            ProviderFailureKind.AUTHENTICATION,
        ),
        (
            RefreshError("token endpoint returned 503", retryable=True),  # type: ignore[no-untyped-call]
            ProviderFailureKind.TEMPORARY,
        ),
        (
            TransportError("connection reset"),  # type: ignore[no-untyped-call]
            ProviderFailureKind.TEMPORARY,
        ),
    ],
)
def test_access_token_refresh_failures_are_classified_without_a_status(
    error: Exception, kind: ProviderFailureKind
) -> None:
    request = MagicMock()
    request.execute.side_effect = error
    events_api = MagicMock()
    events_api.list.return_value = request
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.find_projection(DESTINATION, "operation-key")

    assert failure.value.kind is kind
    assert failure.value.account_id == DESTINATION.connected_account_id
    # The token endpoint's response is not repeated into incidents or logs.
    assert str(error) not in failure.value.detail


def test_a_refresh_failing_while_creating_a_projection_is_classified() -> None:
    # Credentials are refreshed as each request's service is made, before any request is sent.
    events_api = MagicMock()
    events_api.list.return_value = request_returning({"items": []})
    service = MagicMock()
    service.events.return_value = events_api
    services = iter((service,))

    def service_for(_account_id: object) -> MagicMock:
        try:
            return next(services)
        except StopIteration:
            raise RefreshError("invalid_grant") from None  # type: ignore[no-untyped-call]

    provider = GoogleCalendarProvider(service_for)
    projection = EventProjection(
        TimedInterval(
            datetime(2026, 8, 30, 10, tzinfo=UTC),
            datetime(2026, 8, 30, 11, tzinfo=UTC),
        ),
        "Busy",
    )

    with pytest.raises(ProviderFailure) as failure:
        provider.create_projection(
            DESTINATION, event().reference, SyncRuleId("rule-1"), projection, "operation-key"
        )

    assert failure.value.kind is ProviderFailureKind.AUTHENTICATION
    assert failure.value.account_id == DESTINATION.connected_account_id


def test_failures_name_the_account_whose_request_google_rejected() -> None:
    # A rule's calendars may belong to different accounts; only the rejected one needs renewing.
    source = endpoint("personal-account", "personal-calendar")
    events_api = MagicMock()
    events_api.list.return_value = request_raising(401)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as source_failure:
        provider.changes(source, None, NOW)
    with pytest.raises(ProviderFailure) as destination_failure:
        provider.find_projection(DESTINATION, "operation-key")

    assert source_failure.value.account_id == source.connected_account_id
    assert destination_failure.value.account_id == DESTINATION.connected_account_id


def test_occurrence_exceptions_count_changed_length_and_content_but_not_regular_instances() -> None:
    longer = {**_instance(), "end": {"dateTime": "2026-09-08T11:00:00Z"}}
    renamed = {**_instance(), "summary": "Dentist"}
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_returning({"items": [_instance(), longer, renamed]})
    provider = provider_with_events_api(events_api)

    exceptions = provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC))

    assert len(exceptions) == 2


def test_occurrence_exceptions_count_an_occurrence_answered_on_its_own() -> None:
    maybe = {
        **_instance(),
        "attendees": [{"email": "me@example.com", "self": True, "responseStatus": "tentative"}],
    }
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_returning({"items": [_instance(), maybe]})
    provider = provider_with_events_api(events_api)

    (exception,) = provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC))

    assert exception.response is InvitationResponse.TENTATIVE
    fields = events_api.instances.call_args.kwargs["fields"]
    assert "attendees(email,self,responseStatus)" in fields


def test_occurrence_exceptions_of_a_deleted_series_are_none() -> None:
    events_api = MagicMock()
    events_api.get.return_value = request_raising(404)
    provider = provider_with_events_api(events_api)

    assert provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC)) == ()
    events_api.instances.assert_not_called()


def test_write_occurrence_restores_a_cancelled_instance_without_notifications() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance("cancelled")]})
    events_api.get.return_value = request_returning(_master())
    events_api.patch.return_value = request_returning(_owned(_instance()))
    provider = provider_with_events_api(events_api)
    projection = EventProjection(
        TimedInterval(START, datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), "Busy"
    )

    written = provider.write_occurrence(
        SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), projection, "key"
    )

    kwargs = events_api.patch.call_args.kwargs
    assert kwargs["eventId"] == "projection-1_20260908T080000Z"
    assert kwargs["sendUpdates"] == "none"
    assert kwargs["body"]["status"] == "confirmed"
    assert written.status is EventStatus.CONFIRMED


def test_write_occurrence_refuses_a_series_owned_by_another_rule() -> None:
    events_api = MagicMock()
    events_api.instances.return_value = request_returning({"items": [_instance()]})
    foreign = _master()
    foreign["extendedProperties"]["private"][RULE_PROPERTY] = "other-rule"  # type: ignore[index]
    events_api.get.return_value = request_returning(foreign)
    provider = provider_with_events_api(events_api)

    with pytest.raises(ProviderFailure) as failure:
        provider.write_occurrence(
            SERIES,
            START,
            SOURCE_SERIES,
            SyncRuleId("rule-1"),
            EventProjection(TimedInterval(START, datetime(2026, 9, 8, 9, 0, tzinfo=UTC)), "Busy"),
            "key",
        )

    assert failure.value.kind is ProviderFailureKind.PERMANENT
    events_api.patch.assert_not_called()


def test_cancel_occurrence_deletes_only_the_instance_and_skips_cancelled_ones() -> None:
    events_api = MagicMock()
    events_api.instances.side_effect = [
        request_returning({"items": [_instance()]}),
        request_returning({"items": [_instance("cancelled")]}),
    ]
    events_api.get.return_value = request_returning(_master())
    events_api.delete.return_value = request_returning({})
    provider = provider_with_events_api(events_api)

    provider.cancel_occurrence(SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), "key")
    provider.cancel_occurrence(SERIES, START, SOURCE_SERIES, SyncRuleId("rule-1"), "key")

    events_api.delete.assert_called_once_with(
        calendarId="work-calendar", eventId="projection-1_20260908T080000Z", sendUpdates="none"
    )


def test_occurrence_exceptions_keep_occurrences_moved_out_of_the_window_but_not_older_ones() -> (
    None
):
    moved_out = {
        **_instance(),
        "id": "projection-1_20260915T080000Z",
        "originalStartTime": {"dateTime": "2026-09-15T08:00:00Z"},
        "start": {"dateTime": "2026-07-01T08:00:00Z"},
        "end": {"dateTime": "2026-07-01T09:00:00Z"},
    }
    older = {
        **_instance("cancelled"),
        "id": "projection-1_20260707T080000Z",
        "originalStartTime": {"dateTime": "2026-07-07T08:00:00Z"},
    }
    events_api = _with_series_master(MagicMock())
    events_api.instances.return_value = request_returning({"items": [moved_out, older]})
    provider = provider_with_events_api(events_api)

    exceptions = provider.occurrence_exceptions(SERIES, datetime(2026, 8, 30, tzinfo=UTC))

    assert [event.reference.event_id.value for event in exceptions] == [
        "projection-1_20260915T080000Z"
    ]
    assert "timeMin" not in events_api.instances.call_args.kwargs
