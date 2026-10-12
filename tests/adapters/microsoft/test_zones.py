"""Outlook's Windows time zone names and the IANA names the domain uses (ADR 0034)."""

import time
from datetime import UTC, datetime

import pytest

from calendar_sync.infrastructure.microsoft.zones import WINDOWS_ZONES, iana_zone, windows_zone


@pytest.mark.parametrize(
    ("windows", "iana"),
    [
        ("Pacific Standard Time", "America/Los_Angeles"),
        ("Romance Standard Time", "Europe/Paris"),
        ("W. Europe Standard Time", "Europe/Berlin"),
        ("GMT Standard Time", "Europe/London"),
        ("UTC", "Etc/UTC"),
        ("India Standard Time", "Asia/Calcutta"),
    ],
)
def test_a_windows_name_reads_as_its_cldr_zone_and_back(windows: str, iana: str) -> None:
    assert iana_zone(windows) == iana
    assert windows_zone(iana) == windows


def test_an_iana_name_reads_as_itself() -> None:
    assert iana_zone("Europe/Madrid") == "Europe/Madrid"


@pytest.mark.parametrize("name", ["tzone://Microsoft/Custom", "Mars Standard Time", "", None])
def test_a_zone_neither_table_knows_is_unrecognized(name: str | None) -> None:
    assert iana_zone(name) is None


def test_a_zone_cldr_names_for_another_territory_is_written_as_its_equivalent() -> None:
    # Madrid keeps Berlin's offsets and changes, so a Madrid series stays at its local time; the
    # first such zone in CLDR's order is the one written.
    assert windows_zone("Europe/Madrid") == "W. Europe Standard Time"
    assert windows_zone("America/Toronto") == "Eastern Standard Time"


def test_a_zone_no_windows_zone_matches_cannot_be_written() -> None:
    assert windows_zone("Not/AZone") is None


def test_every_mapped_zone_exists_and_lookups_stay_fast() -> None:
    started = time.monotonic()
    windows_zone("Europe/Madrid")
    assert all(iana_zone(name) == mapped for name, mapped in WINDOWS_ZONES.items())
    assert time.monotonic() - started < 5


def test_an_equivalent_zone_is_written_only_if_it_keeps_the_offsets_for_the_series_lifetime() -> (
    None
):
    # Madrid keeps Berlin's offsets today, but in 1976 Spain changed its clocks on dates no
    # Windows zone's did, so a series running through 1976 would move by an hour some weeks.
    in_1976 = (datetime(1976, 1, 2, tzinfo=UTC), datetime(1977, 1, 1, tzinfo=UTC))
    this_year = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))

    assert windows_zone("Europe/Madrid", during=in_1976) is None
    assert windows_zone("Europe/Madrid", during=this_year) == "W. Europe Standard Time"
