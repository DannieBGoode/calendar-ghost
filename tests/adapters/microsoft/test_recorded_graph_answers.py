"""Microsoft Graph v1.0's real answers, recorded with a personal account on 2026-10-12 during
ADR 0034's release checks and made synthetic by `scripts/provider_fixtures.py`.

Each test pins how the adapter reads one of them, so a change that misreads Graph fails here, with
no account. Record new answers the same way when Graph's behavior is in doubt
(docs/development.md, Live provider checks).
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import AllDayRange, TimedInterval
from calendar_sync.infrastructure.microsoft.causes import cause_of
from calendar_sync.infrastructure.microsoft.graph import graph_refusal
from calendar_sync.infrastructure.microsoft.translation import (
    exceptions_have_attendees,
    to_domain_event,
)
from tests.helpers import endpoint

ANSWERS = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "providers" / "graph_answers.json").read_text()
)
CALENDAR = endpoint("personal-account", "test-calendar")


def answer(name: str) -> Any:
    return ANSWERS[name]["body"]


def refusal(name: str) -> httpx.Response:
    return httpx.Response(ANSWERS[name]["status"], json=answer(name))


def test_a_master_expanded_whole_lists_each_exception_with_its_attendees() -> None:
    # A series with one moved and one cancelled occurrence: the moved one is its exception.
    master = answer("master_expand_exceptions")

    assert len(master["exceptionOccurrences"]) == 1
    assert exceptions_have_attendees(master) is False


def test_a_master_read_with_any_select_lists_exceptions_without_attendees() -> None:
    # Why the guest check never selects fields (ADR 0034, #92): this answer proves nothing.
    master = answer("master_select_expand_exceptions")

    assert set(master["exceptionOccurrences"][0]) == {"@odata.etag", "id"}
    assert exceptions_have_attendees(master) is None


def test_an_all_day_event_reads_by_its_dates_under_utc() -> None:
    event = to_domain_event(answer("all_day_event"), CALENDAR)

    assert event.time == AllDayRange(date(2027, 3, 10), date(2027, 3, 11))


def test_an_event_that_ends_as_it_starts_reads_as_lasting_no_time() -> None:
    event = to_domain_event(answer("zero_length_event"), CALENDAR)

    assert isinstance(event.time, TimedInterval)
    assert event.time.starts_at == event.time.ends_at
    assert event.time.starts_at.replace(tzinfo=None) == datetime(2027, 3, 12, 9, 0)


def test_a_deleted_event_reaches_the_delta_round_as_removed() -> None:
    [removed] = answer("delta_after_delete")["value"]

    assert removed["@removed"] == {"reason": "deleted"}
    assert "@odata.deltaLink" in answer("delta_after_delete")


def test_a_stale_version_is_refused_as_a_conflict_to_read_again() -> None:
    refused = graph_refusal(refusal("patch_stale_version"))

    assert refused.status == 412
    assert refused.codes == ("ErrorIrresolvableConflict",)
    assert cause_of(refused, event_scoped=True) is Cause.TEMPORARY


def test_a_deleted_calendar_reads_as_not_found() -> None:
    refused = graph_refusal(refusal("deleted_calendar_listing"))

    assert (refused.status, refused.codes) == (404, ("ErrorItemNotFound",))
    assert cause_of(refused) is Cause.CALENDAR_NOT_FOUND
