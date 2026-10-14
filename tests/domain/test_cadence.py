"""A Sync Cadence says how soon a User's rules run; with Plans off, everyone's is the default."""

from datetime import timedelta

import pytest

from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
from calendar_sync.domain.errors import DomainValidationError


def test_the_default_cadence_syncs_instantly_and_polls_every_five_minutes() -> None:
    assert (DEFAULT_CADENCE.instant, DEFAULT_CADENCE.poll_every) == (True, SCHEDULED_EVERY)
    assert timedelta(minutes=5) == SCHEDULED_EVERY


@pytest.mark.parametrize("poll_every", [timedelta(0), timedelta(minutes=-5)])
def test_a_cadence_must_poll_after_some_time(poll_every: timedelta) -> None:
    with pytest.raises(DomainValidationError):
        SyncCadence(instant=False, poll_every=poll_every)
