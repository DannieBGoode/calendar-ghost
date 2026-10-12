"""Google Calendar's real answers, recorded on 2026-10-12 during ADR 0034's release checks and
made synthetic by `scripts/provider_fixtures.py`. Each test pins how the adapter reads one of them,
so a change that misreads Google fails here, with no account."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from calendar_sync.domain.model import InvitationResponse, Recurrence
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService
from calendar_sync.infrastructure.google.translation import to_domain_event
from tests.helpers import endpoint

ANSWERS = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "providers" / "google_answers.json").read_text()
)
CALENDAR = endpoint("personal-account", "test-calendar")


def answer(name: str) -> Any:
    return ANSWERS[name]["body"]


def test_a_rule_google_reordered_is_the_rule_calendar_ghost_wrote() -> None:
    # Written from Outlook as FREQ, INTERVAL, BYDAY, WKST, COUNT; Google stores its own order.
    stored = to_domain_event(answer("projected_series_as_google_stores_it"), CALENDAR)
    assert stored.recurrence == Recurrence(
        ("RRULE:FREQ=WEEKLY;WKST=SU;COUNT=15;INTERVAL=2;BYDAY=FR",)
    )
    read = SyncDecisionService.as_projection(stored)
    written = replace(
        read, recurrence=Recurrence(("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;WKST=SU;COUNT=15",))
    )

    fingerprinter = ProjectionFingerprinter()
    assert fingerprinter.fingerprint(read) == fingerprinter.fingerprint(written)


@pytest.mark.parametrize(
    ("title", "response"),
    [
        ("CG invite accepted", InvitationResponse.ACCEPTED),
        ("CG invite tentative", InvitationResponse.TENTATIVE),
        ("CG invite declined", InvitationResponse.DECLINED),
        ("CG invite probe", InvitationResponse.AWAITING),
    ],
)
def test_the_invited_calendars_own_answer_is_its_invitation_response(
    title: str, response: InvitationResponse
) -> None:
    [item] = [
        item
        for item in answer("invitations_answered_by_the_calendar")["items"]
        if item["summary"] == title
    ]

    assert to_domain_event(item, CALENDAR).response is response
