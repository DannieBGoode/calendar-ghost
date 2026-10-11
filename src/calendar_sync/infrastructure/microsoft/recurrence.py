"""Outlook's patterned recurrence, its exact iCalendar form, and the dates a pattern defines.

A Graph `patternedRecurrence` has one value where iCalendar allows lists, so every Graph pattern
has an exact iCalendar line, while many iCalendar rules have no Graph pattern. Those raise
UnsupportedRecurrence and are never approximated (ADR 0032).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
"""Graph's day names, at their `date.weekday()` positions."""
ICAL_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
INDEXES = ("first", "second", "third", "fourth", "last")
POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}
# A day of the month from 29 on is moved, by Outlook, to a shorter month's last day.
LAST_FIXED_DAY = 28
MONDAY = 0
# Expansion stops after this many periods, so a malformed pattern cannot loop for long.
MAX_PERIODS = 100_000


class UnsupportedRecurrence(ValueError):
    """A recurrence Outlook cannot hold exactly, or one Graph answered that this release cannot
    read."""


@dataclass(frozen=True, slots=True)
class Pattern:
    """A Graph recurrence pattern, holding only the fields its type uses."""

    kind: str
    """daily, weekly, absoluteMonthly, relativeMonthly, absoluteYearly, or relativeYearly."""
    interval: int = 1
    days: tuple[int, ...] = ()
    """Weekdays, as `date.weekday()` numbers, in order."""
    day_of_month: int = 0
    month: int = 0
    index: str = "first"
    first_day: int = MONDAY
    """The day weeks start on; it changes which weeks a weekly pattern of more than one week
    meets, and nothing else."""


@dataclass(frozen=True, slots=True)
class RecurrenceRange:
    start: date
    end: date | None = None
    """The last day occurrences may fall on, inclusive."""
    count: int = 0
    """How many occurrences there are; 0 for no limit."""


@dataclass(frozen=True, slots=True)
class SeriesRule:
    pattern: Pattern
    range: RecurrenceRange


def _normalized(pattern: Pattern) -> Pattern:
    """Only the fields the pattern's type uses, so equal patterns compare equal."""
    kind = pattern.kind
    weekly_start = pattern.first_day if kind == "weekly" and pattern.interval > 1 else MONDAY
    return Pattern(
        kind,
        max(pattern.interval, 1),
        tuple(sorted(set(pattern.days))) if kind in _USES_DAYS else (),
        pattern.day_of_month if kind in {"absoluteMonthly", "absoluteYearly"} else 0,
        pattern.month if kind in {"absoluteYearly", "relativeYearly"} else 0,
        pattern.index if kind in {"relativeMonthly", "relativeYearly"} else "first",
        weekly_start,
    )


_USES_DAYS = frozenset({"weekly", "relativeMonthly", "relativeYearly"})
_KINDS = frozenset(
    {"daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"}
)


# Graph ---------------------------------------------------------------------------------------


def from_graph(recurrence: Mapping[str, Any]) -> SeriesRule:
    """A Graph `patternedRecurrence`, read as its pattern and range."""
    pattern, range_ = recurrence.get("pattern"), recurrence.get("range")
    if not isinstance(pattern, Mapping) or not isinstance(range_, Mapping):
        raise UnsupportedRecurrence("the recurrence has no pattern or range")
    kind = pattern.get("type")
    if kind not in _KINDS:
        raise UnsupportedRecurrence("Graph answered a pattern type this release does not know")
    days = pattern.get("daysOfWeek") or []
    first = pattern.get("firstDayOfWeek")
    read = Pattern(
        str(kind),
        _number(pattern.get("interval"), 1),
        tuple(DAYS.index(day) for day in days if day in DAYS),
        _number(pattern.get("dayOfMonth"), 0),
        _number(pattern.get("month"), 0),
        str(pattern.get("index") or "first"),
        DAYS.index(first) if first in DAYS else MONDAY,
    )
    start = date.fromisoformat(str(range_.get("startDate")))
    range_kind = range_.get("type")
    end = (
        date.fromisoformat(str(range_.get("endDate")))
        if range_kind == "endDate" and range_.get("endDate")
        else None
    )
    count = _number(range_.get("numberOfOccurrences"), 0) if range_kind == "numbered" else 0
    return SeriesRule(_normalized(read), RecurrenceRange(start, end, count))


def to_graph(rule: SeriesRule, zone: str) -> dict[str, Any]:
    """The `patternedRecurrence` to write, with only the fields its type uses, in a Windows zone."""
    pattern = rule.pattern
    written: dict[str, Any] = {"type": pattern.kind, "interval": pattern.interval}
    if pattern.kind in _USES_DAYS:
        written["daysOfWeek"] = [DAYS[day] for day in pattern.days]
    if pattern.kind == "weekly":
        written["firstDayOfWeek"] = DAYS[pattern.first_day]
    if pattern.kind in {"absoluteMonthly", "absoluteYearly"}:
        written["dayOfMonth"] = pattern.day_of_month
    if pattern.kind in {"absoluteYearly", "relativeYearly"}:
        written["month"] = pattern.month
    if pattern.kind in {"relativeMonthly", "relativeYearly"}:
        written["index"] = pattern.index
    range_: dict[str, Any] = {"type": "noEnd", "startDate": rule.range.start.isoformat()}
    if rule.range.count:
        range_ |= {"type": "numbered", "numberOfOccurrences": rule.range.count}
    elif rule.range.end is not None:
        range_ |= {"type": "endDate", "endDate": rule.range.end.isoformat()}
    range_["recurrenceTimeZone"] = zone
    return {"pattern": written, "range": range_}


# iCalendar -----------------------------------------------------------------------------------


def to_ical(rule: SeriesRule, start: datetime | date) -> tuple[str, ...]:
    """The exact RRULE line of a rule whose first occurrence begins at `start`, an aware local
    time for a timed series and a date for an all-day one."""
    pattern = rule.pattern
    parts = [f"FREQ={_FREQUENCIES[pattern.kind]}"]
    if pattern.interval > 1:
        parts.append(f"INTERVAL={pattern.interval}")
    if pattern.month:
        parts.append(f"BYMONTH={pattern.month}")
    parts.extend(_ical_days(pattern))
    if pattern.kind == "weekly" and pattern.interval > 1:
        parts.append(f"WKST={ICAL_DAYS[pattern.first_day]}")
    if rule.range.count:
        parts.append(f"COUNT={rule.range.count}")
    elif rule.range.end is not None:
        parts.append(f"UNTIL={_until(rule.range.end, start)}")
    return ("RRULE:" + ";".join(parts),)


_FREQUENCIES = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "absoluteMonthly": "MONTHLY",
    "relativeMonthly": "MONTHLY",
    "absoluteYearly": "YEARLY",
    "relativeYearly": "YEARLY",
}


def _ical_days(pattern: Pattern) -> list[str]:
    if pattern.kind in {"absoluteMonthly", "absoluteYearly"}:
        day = pattern.day_of_month
        if day <= LAST_FIXED_DAY:
            return [f"BYMONTHDAY={day}"]
        # Outlook's day 29 to 31 falls on a shorter month's last day.
        days = ",".join(str(each) for each in range(LAST_FIXED_DAY, day + 1))
        return [f"BYMONTHDAY={days}", "BYSETPOS=-1"]
    names = [ICAL_DAYS[day] for day in pattern.days]
    if pattern.kind == "weekly":
        return [f"BYDAY={','.join(names)}"]
    if pattern.kind == "daily":
        return []
    position = POSITIONS[pattern.index]
    if len(names) == 1:
        return [f"BYDAY={position}{names[0]}"]
    return [f"BYDAY={','.join(names)}", f"BYSETPOS={position}"]


def _until(end: date, start: datetime | date) -> str:
    """The end of the range's last day: a date for an all-day series, and the last second of that
    day in the series' zone, in UTC, for a timed one."""
    if not isinstance(start, datetime):
        return end.strftime("%Y%m%d")
    last = datetime.combine(end, time(23, 59, 59), tzinfo=start.tzinfo)
    return last.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def from_ical(lines: tuple[str, ...], start: datetime | date) -> SeriesRule:
    """The Graph rule that repeats exactly as `lines`, for a series beginning at `start`, an
    aware local time for a timed series and a date for an all-day one; UnsupportedRecurrence
    when Outlook has none."""
    if len(lines) != 1 or not lines[0].startswith("RRULE:"):
        raise UnsupportedRecurrence("Outlook holds one RRULE and no RDATE, EXDATE, or EXRULE")
    parts = _parts(lines[0].removeprefix("RRULE:"))
    first = start if not isinstance(start, datetime) else start.date()
    pattern = _pattern(parts, first)
    if "COUNT" in parts and "UNTIL" in parts:
        raise UnsupportedRecurrence("a recurrence cannot end by both COUNT and UNTIL")
    end = _range_end(parts["UNTIL"], start) if "UNTIL" in parts else None
    count = _positive(parts["COUNT"]) if "COUNT" in parts else 0
    return SeriesRule(_normalized(pattern), RecurrenceRange(first, end, count))


_ALLOWED = frozenset(
    {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"}
)


def _parts(rule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for part in rule.split(";"):
        name, _, value = part.partition("=")
        if name not in _ALLOWED or not value or name in parts:
            raise UnsupportedRecurrence(f"Outlook has no equivalent of {name or 'an empty part'}")
        parts[name] = value
    return parts


def _pattern(parts: Mapping[str, str], first: date) -> Pattern:
    frequency = parts.get("FREQ")
    interval = _positive(parts.get("INTERVAL", "1"))
    week_start = _weekday(parts.get("WKST", "MO"))
    if frequency == "DAILY":
        _only(parts, {"BYDAY"})
        if "BYDAY" not in parts:
            return Pattern("daily", interval)
        if interval != 1:
            raise UnsupportedRecurrence("Outlook repeats chosen weekdays only every week")
        return Pattern("weekly", 1, _plain_days(parts["BYDAY"]), first_day=week_start)
    if frequency == "WEEKLY":
        _only(parts, {"BYDAY"})
        days = _plain_days(parts["BYDAY"]) if "BYDAY" in parts else (first.weekday(),)
        return Pattern("weekly", interval, days, first_day=week_start)
    if frequency == "MONTHLY":
        _only(parts, {"BYDAY", "BYMONTHDAY", "BYSETPOS"})
        return _within_month("Monthly", parts, interval, first)
    if frequency == "YEARLY":
        _only(parts, {"BYDAY", "BYMONTHDAY", "BYSETPOS", "BYMONTH"})
        month = _positive(parts["BYMONTH"]) if "BYMONTH" in parts else first.month
        if month > 12:
            raise UnsupportedRecurrence("a month is from 1 to 12")
        return replace(_within_month("Yearly", parts, interval, first), month=month)
    raise UnsupportedRecurrence(f"Outlook does not repeat {frequency or 'without a frequency'}")


def _within_month(period: str, parts: Mapping[str, str], interval: int, first: date) -> Pattern:
    """A monthly or yearly pattern's day within its month."""
    if "BYDAY" in parts:
        if "BYMONTHDAY" in parts:
            raise UnsupportedRecurrence("Outlook does not combine weekdays and days of the month")
        days, position = _relative_days(parts["BYDAY"], parts.get("BYSETPOS"))
        index = next((name for name, value in POSITIONS.items() if value == position), None)
        if index is None:
            raise UnsupportedRecurrence("Outlook counts weekdays first to fourth, or last")
        return Pattern(f"relative{period}", interval, days, index=index)
    day = _day_of_month(parts.get("BYMONTHDAY"), parts.get("BYSETPOS"), first)
    return Pattern(f"absolute{period}", interval, day_of_month=day)


def _day_of_month(by_month_day: str | None, by_set_position: str | None, first: date) -> int:
    if by_month_day is None:
        if by_set_position is not None:
            raise UnsupportedRecurrence("BYSETPOS needs a set of days")
        return _fixed_day(first.day)
    days = [_signed(value) for value in by_month_day.split(",")]
    if len(days) == 1 and by_set_position is None:
        return _fixed_day(days[0])
    # The last of the 28th to the Nth is Outlook's day N, moved to a shorter month's last day.
    last = days[-1]
    if (
        by_set_position == "-1"
        and LAST_FIXED_DAY < last <= 31
        and days == list(range(LAST_FIXED_DAY, last + 1))
    ):
        return last
    raise UnsupportedRecurrence("Outlook repeats on one day of the month")


def _fixed_day(day: int) -> int:
    """A day of the month every month has; from 29 on, iCalendar skips shorter months, which
    Outlook would fill with their last day."""
    if not 1 <= day <= LAST_FIXED_DAY:
        raise UnsupportedRecurrence("Outlook moves days from the 29th to a shorter month's end")
    return day


def _relative_days(by_day: str, by_set_position: str | None) -> tuple[tuple[int, ...], int]:
    values = by_day.split(",")
    if len(values) == 1 and by_set_position is None:
        value = values[0]
        if len(value) < 3:
            raise UnsupportedRecurrence("Outlook repeats on one counted weekday of a month")
        return (_weekday(value[-2:]),), _signed(value[:-2])
    if by_set_position is None or "," in by_set_position:
        raise UnsupportedRecurrence("Outlook counts one position among several weekdays")
    return _plain_days(by_day), _signed(by_set_position)


def _plain_days(by_day: str) -> tuple[int, ...]:
    days = []
    for value in by_day.split(","):
        if len(value) != 2:
            raise UnsupportedRecurrence("Outlook counts no weekday in a weekly rule")
        days.append(_weekday(value))
    return tuple(sorted(set(days)))


def _weekday(value: str) -> int:
    if value not in ICAL_DAYS:
        raise UnsupportedRecurrence(f"{value} is no weekday")
    return ICAL_DAYS.index(value)


def _only(parts: Mapping[str, str], allowed: set[str]) -> None:
    extra = set(parts) - allowed - {"FREQ", "INTERVAL", "COUNT", "UNTIL", "WKST"}
    if extra:
        raise UnsupportedRecurrence(f"Outlook has no equivalent of {', '.join(sorted(extra))}")


def _range_end(until: str, start: datetime | date) -> date:
    """The last day an UNTIL lets an occurrence fall on, in the series' zone."""
    if len(until) == 8:
        return datetime.strptime(until, "%Y%m%d").replace(tzinfo=UTC).date()
    moment = datetime.strptime(until.removesuffix("Z"), "%Y%m%dT%H%M%S")
    if not isinstance(start, datetime):
        return moment.date()
    zone = start.tzinfo
    local = (
        moment.replace(tzinfo=UTC).astimezone(zone)
        if until.endswith("Z")
        else moment.replace(tzinfo=zone)
    )
    # An UNTIL before that day's occurrence leaves the day out.
    return local.date() if local.timetz() >= start.timetz() else local.date() - timedelta(days=1)


def _positive(value: str) -> int:
    number = _signed(value)
    if number < 1:
        raise UnsupportedRecurrence("a count, interval, or month is positive")
    return number


def _signed(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise UnsupportedRecurrence(f"{value} is no number") from error


def _number(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


# Expansion -----------------------------------------------------------------------------------


def occurrence_dates(rule: SeriesRule) -> Iterator[date]:
    """Every date the rule defines an occurrence on, from its start, in order; endless for a
    rule without an end."""
    for produced, day in enumerate(_candidates(rule.pattern, rule.range.start), start=1):
        if rule.range.end is not None and day > rule.range.end:
            return
        yield day
        if rule.range.count and produced >= rule.range.count:
            return


def _candidates(pattern: Pattern, first: date) -> Iterator[date]:
    for period in range(MAX_PERIODS):
        for day in sorted(_period_dates(pattern, first, period)):
            if day >= first:
                yield day


def _period_dates(pattern: Pattern, first: date, period: int) -> list[date]:
    step = pattern.interval * period
    if pattern.kind == "daily":
        return [first + timedelta(days=step)]
    if pattern.kind == "weekly":
        week = first - timedelta(days=(first.weekday() - pattern.first_day) % 7)
        week += timedelta(weeks=step)
        return [week + timedelta(days=(day - pattern.first_day) % 7) for day in pattern.days]
    if pattern.kind.endswith("Monthly"):
        months = first.year * 12 + first.month - 1 + step
        year, month = divmod(months, 12)
        return _in_month(pattern, year, month + 1)
    return _in_month(pattern, first.year + step, pattern.month)


def _in_month(pattern: Pattern, year: int, month: int) -> list[date]:
    if year > date.max.year:
        return []
    length = calendar.monthrange(year, month)[1]
    if pattern.kind.startswith("absolute"):
        return [date(year, month, min(pattern.day_of_month, length))]
    matching = [
        date(year, month, day)
        for day in range(1, length + 1)
        if date(year, month, day).weekday() in pattern.days
    ]
    position = POSITIONS[pattern.index]
    index = position - 1 if position > 0 else position
    return [matching[index]] if -len(matching) <= index < len(matching) else []


def period(pattern: Pattern) -> timedelta:
    """The longest time between two neighbouring occurrences of the pattern."""
    days = {"daily": 1, "weekly": 7}.get(pattern.kind)
    if days is None:
        days = 62 if pattern.kind.endswith("Monthly") else 366
    return timedelta(days=days * pattern.interval)
