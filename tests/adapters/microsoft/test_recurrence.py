"""Outlook's patterned recurrence and iCalendar lines, translated exactly or not at all, and the
occurrences a pattern defines (ADR 0032)."""

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from calendar_sync.infrastructure.microsoft.recurrence import (
    SeriesRule,
    UnsupportedRecurrence,
    from_graph,
    from_ical,
    occurrence_dates,
    to_graph,
    to_ical,
)

MADRID = ZoneInfo("Europe/Madrid")
# A Monday, 09:00 in Madrid.
START = datetime(2026, 10, 12, 9, 0, tzinfo=MADRID)


def graph(pattern: dict[str, Any], **range_: Any) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "range": {"type": "noEnd", "startDate": "2026-10-12", **range_},
    }


# Each Graph pattern, as Graph returns it with its unused fields at their defaults, and its exact
# iCalendar line.
CASES: list[tuple[dict[str, Any], str]] = [
    (graph({"type": "daily", "interval": 1}), "RRULE:FREQ=DAILY"),
    (graph({"type": "daily", "interval": 3}), "RRULE:FREQ=DAILY;INTERVAL=3"),
    (
        graph(
            {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": ["wednesday", "monday"],
                "firstDayOfWeek": "sunday",
                "dayOfMonth": 0,
                "month": 0,
                "index": "first",
            }
        ),
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE",
    ),
    (
        graph(
            {"type": "weekly", "interval": 2, "daysOfWeek": ["monday"], "firstDayOfWeek": "sunday"}
        ),
        "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;WKST=SU",
    ),
    (
        graph({"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 12}),
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=12",
    ),
    # Outlook moves day 31 to a shorter month's last day.
    (
        graph({"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 31}),
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
    ),
    (
        graph(
            {"type": "relativeMonthly", "interval": 1, "daysOfWeek": ["monday"], "index": "second"}
        ),
        "RRULE:FREQ=MONTHLY;BYDAY=2MO",
    ),
    (
        graph(
            {"type": "relativeMonthly", "interval": 2, "daysOfWeek": ["friday"], "index": "last"}
        ),
        "RRULE:FREQ=MONTHLY;INTERVAL=2;BYDAY=-1FR",
    ),
    (
        graph(
            {
                "type": "relativeMonthly",
                "interval": 1,
                "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "index": "first",
            }
        ),
        "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
    ),
    (
        graph({"type": "absoluteYearly", "interval": 1, "dayOfMonth": 12, "month": 10}),
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYMONTHDAY=12",
    ),
    (
        graph({"type": "absoluteYearly", "interval": 1, "dayOfMonth": 29, "month": 2}),
        "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1",
    ),
    (
        graph(
            {
                "type": "relativeYearly",
                "interval": 1,
                "daysOfWeek": ["thursday"],
                "index": "fourth",
                "month": 11,
            }
        ),
        "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=4TH",
    ),
    (
        graph({"type": "daily", "interval": 1}, type="numbered", numberOfOccurrences=5),
        "RRULE:FREQ=DAILY;COUNT=5",
    ),
    # The last day of an end date, 23:59:59 in Madrid, is 21:59:59 UTC in summer.
    (
        graph({"type": "daily", "interval": 1}, type="endDate", endDate="2026-10-20"),
        "RRULE:FREQ=DAILY;UNTIL=20261020T215959Z",
    ),
]


@pytest.mark.parametrize(("recurrence", "line"), CASES, ids=[line for _, line in CASES])
def test_each_graph_pattern_has_one_exact_ical_line_and_reads_back(
    recurrence: dict[str, Any], line: str
) -> None:
    rule = from_graph(recurrence)

    assert to_ical(rule, START) == (line,)
    assert from_ical((line,), START) == rule


def test_writing_a_rule_sends_only_its_patterns_own_fields() -> None:
    rule = from_ical(("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE",), START)

    assert to_graph(rule, "Romance Standard Time") == {
        "pattern": {
            "type": "weekly",
            "interval": 2,
            "daysOfWeek": ["monday", "wednesday"],
            # iCalendar weeks start on Monday unless WKST says otherwise.
            "firstDayOfWeek": "monday",
        },
        "range": {
            "type": "noEnd",
            "startDate": "2026-10-12",
            "recurrenceTimeZone": "Romance Standard Time",
        },
    }


def test_daily_on_some_weekdays_is_weekly() -> None:
    assert from_ical(("RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR",), START) == from_ical(
        ("RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",), START
    )


def test_an_until_before_that_days_occurrence_ends_the_range_the_day_before() -> None:
    # 07:00 UTC on the 20th is 09:00 in Madrid: an UNTIL at the occurrence's own time includes it.
    included = from_ical(("RRULE:FREQ=DAILY;UNTIL=20261020T070000Z",), START)
    excluded = from_ical(("RRULE:FREQ=DAILY;UNTIL=20261020T065959Z",), START)

    assert included.range.end == date(2026, 10, 20)
    assert excluded.range.end == date(2026, 10, 19)


def test_an_all_day_series_ends_on_its_until_date() -> None:
    rule = from_ical(("RRULE:FREQ=WEEKLY;UNTIL=20261102",), date(2026, 10, 12))

    assert rule.range.end == date(2026, 11, 2)
    assert to_ical(rule, date(2026, 10, 12)) == ("RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261102",)


@pytest.mark.parametrize(
    "lines",
    [
        ("RRULE:FREQ=HOURLY",),
        ("RRULE:FREQ=MINUTELY;INTERVAL=15",),
        ("RRULE:FREQ=MONTHLY;BYMONTHDAY=31",),
        ("RRULE:FREQ=MONTHLY;BYMONTHDAY=-1",),
        ("RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15",),
        ("RRULE:FREQ=YEARLY;BYMONTH=1,7",),
        ("RRULE:FREQ=YEARLY;BYYEARDAY=100",),
        ("RRULE:FREQ=YEARLY;BYWEEKNO=20",),
        ("RRULE:FREQ=DAILY;BYHOUR=9,17",),
        ("RRULE:FREQ=MONTHLY;BYDAY=MO,TU;BYSETPOS=1,2",),
        ("RRULE:FREQ=MONTHLY;BYDAY=5MO",),
        ("RRULE:FREQ=MONTHLY;BYDAY=-2MO",),
        ("RRULE:FREQ=MONTHLY;BYDAY=1MO,3MO",),
        ("RRULE:FREQ=DAILY;COUNT=3;UNTIL=20261020T000000Z",),
        ("RRULE:FREQ=DAILY;INTERVAL=2;BYDAY=MO",),
        ("RRULE:FREQ=WEEKLY", "EXDATE:20261019T070000Z"),
        ("RRULE:FREQ=WEEKLY", "RDATE:20261021T070000Z"),
        ("EXRULE:FREQ=MONTHLY",),
        ("RRULE:FREQ=WEEKLY;BYSECOND=5",),
        ("RRULE:FREQ=WEEKLY;X-NAME=1",),
        ("RRULE:FREQ=MONTHLY",),
    ],
)
def test_what_outlook_cannot_repeat_exactly_is_never_approximated(lines: tuple[str, ...]) -> None:
    # A monthly rule on the 31st without a day leaves months out that Outlook would fill.
    start = START if lines != ("RRULE:FREQ=MONTHLY",) else datetime(2026, 10, 31, 9, tzinfo=MADRID)

    with pytest.raises(UnsupportedRecurrence):
        from_ical(lines, start)


def test_an_unknown_graph_pattern_is_unsupported() -> None:
    with pytest.raises(UnsupportedRecurrence):
        from_graph(graph({"type": "hourly", "interval": 1}))


def _dates(line: str, start: date, count: int) -> list[date]:
    rule: SeriesRule = from_ical((line,), start)
    dates = occurrence_dates(rule)
    return [next(dates) for _ in range(count)]


@pytest.mark.parametrize(
    ("line", "start", "expected"),
    [
        (
            "RRULE:FREQ=DAILY;INTERVAL=2",
            date(2026, 10, 12),
            ["2026-10-12", "2026-10-14", "2026-10-16"],
        ),
        (
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TH",
            date(2026, 10, 12),
            ["2026-10-12", "2026-10-15", "2026-10-19", "2026-10-22"],
        ),
        (
            "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=SU",
            date(2026, 10, 12),
            ["2026-10-12", "2026-10-25", "2026-10-26", "2026-11-08"],
        ),
        (
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
            date(2027, 1, 31),
            ["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30"],
        ),
        (
            "RRULE:FREQ=MONTHLY;BYDAY=-1FR",
            date(2026, 10, 30),
            ["2026-10-30", "2026-11-27", "2026-12-25"],
        ),
        (
            "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1",
            date(2026, 11, 2),
            ["2026-11-02", "2026-12-01", "2027-01-01", "2027-02-01"],
        ),
        (
            "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1",
            date(2028, 2, 29),
            ["2028-02-29", "2029-02-28", "2030-02-28"],
        ),
        (
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=4TH",
            date(2026, 11, 26),
            ["2026-11-26", "2027-11-25"],
        ),
    ],
)
def test_a_pattern_defines_its_occurrences(line: str, start: date, expected: list[str]) -> None:
    assert _dates(line, start, len(expected)) == [date.fromisoformat(day) for day in expected]


def test_a_range_ends_its_occurrences() -> None:
    counted = from_ical(("RRULE:FREQ=DAILY;COUNT=3",), date(2026, 10, 12))
    dated = from_ical(("RRULE:FREQ=WEEKLY;UNTIL=20261026",), date(2026, 10, 12))

    assert list(occurrence_dates(counted)) == [date(2026, 10, d) for d in (12, 13, 14)]
    assert list(occurrence_dates(dated)) == [date(2026, 10, d) for d in (12, 19, 26)]


def test_until_reads_in_the_series_zone_for_timed_series() -> None:
    utc_start = datetime(2026, 10, 12, 7, 0, tzinfo=UTC).astimezone(MADRID)

    assert to_ical(from_ical(("RRULE:FREQ=DAILY;COUNT=2",), utc_start), utc_start) == (
        "RRULE:FREQ=DAILY;COUNT=2",
    )
