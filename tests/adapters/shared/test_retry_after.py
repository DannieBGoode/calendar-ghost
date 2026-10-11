"""A provider's Retry-After hint, read the same way for every provider (RFC 9110 section 10.2.3)."""

from datetime import UTC, datetime

import pytest

from calendar_sync.infrastructure.retry_after import MAX_RETRY_AFTER_SECONDS, retry_after_seconds

NOW = datetime(2026, 9, 28, 15, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7", 7),
        (" 7 ", 7),
        ("Mon, 28 Sep 2026 15:18:30 GMT", 30),
        ("Mon, 28 Sep 2026 15:17:00 GMT", 0),
        ("Mon, 28 Sep 2026 15:18:10 -0000", 10),
        ("3600", MAX_RETRY_AFTER_SECONDS),
        ("soon", None),
        ("", None),
        (None, None),
    ],
)
def test_a_hint_in_seconds_or_as_a_date_counts_from_now_and_is_bounded(
    value: str | None, expected: int | None
) -> None:
    assert retry_after_seconds(value, NOW) == expected


def test_retries_wait_at_most_a_minute_while_holding_the_rule_lock() -> None:
    assert MAX_RETRY_AFTER_SECONDS == 60
