"""Rules whose calendars belong to different providers: a Google source with an Outlook
destination, the reverse, and both at once without loops (ADR 0022, ADR 0032).

Each rule runs through the router to the real Google and Outlook adapters, against their fakes.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from calendar_sync.application.providers import ProviderKind
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    ConnectedAccountId,
    EventStatus,
    ManagedOrigin,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from calendar_sync.infrastructure.providers.routing import RoutingCalendarProvider
from tests.adapters.microsoft.test_calendar_provider_contract import MAILBOXES, outlook
from tests.fake_calendar import FixedClock
from tests.fake_google_calendar_api import FakeGoogleCalendarApi
from tests.fake_microsoft_graph_api import FakeMicrosoftGraph
from tests.helpers import NOW, endpoint
from tests.users import USER

GOOGLE_CALENDAR = endpoint("personal-account", "personal-calendar")
OUTLOOK_CALENDAR = endpoint("work-account", "work-calendar")
TO_OUTLOOK = SyncRule(
    SyncRuleId("google-to-outlook"), GOOGLE_CALENDAR, OUTLOOK_CALENDAR, state=SyncRuleState.ENABLED
)
TO_GOOGLE = SyncRule(
    SyncRuleId("outlook-to-google"), OUTLOOK_CALENDAR, GOOGLE_CALENDAR, state=SyncRuleState.ENABLED
)


@dataclass
class AccountKinds:
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        return {"personal-account": ProviderKind.GOOGLE, "work-account": ProviderKind.OUTLOOK}.get(
            account_id.value
        )


@dataclass
class Installation:
    google: FakeGoogleCalendarApi
    graph: FakeMicrosoftGraph
    factory: InMemoryUserUnitOfWorkFactory
    sync: ExecuteSyncRule

    def run(self, *rules: SyncRule) -> None:
        for rule in rules:
            self.sync.execute(rule.id)

    def outlook_events(self) -> list[Any]:
        return self.graph.events.in_calendar(MAILBOXES["work-account"][0], "work-calendar")

    def google_events(self) -> dict[str, Any]:
        return self.google.calendars.get(("personal-account", "personal-calendar"), {})


def _installation(*rules: SyncRule) -> Installation:
    google = FakeGoogleCalendarApi()
    outlook_provider, graph = outlook()
    router = RoutingCalendarProvider(
        AccountKinds(),
        {
            ProviderKind.GOOGLE: GoogleCalendarProvider(google.service_for),
            ProviderKind.OUTLOOK: outlook_provider,
        },
    )
    factory = InMemoryUnitOfWorkFactory().for_user(USER)
    with factory() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    fingerprinter = ProjectionFingerprinter()
    sync = ExecuteSyncRule(
        factory,
        router,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        UuidRunIdGenerator(),
    )
    return Installation(google, graph, factory, sync)


def _google_native(installation: Installation, event_id: str, title: str = "Dentist") -> None:
    installation.google.seed(
        GOOGLE_CALENDAR,
        {
            "id": event_id,
            "summary": title,
            "start": {"dateTime": NOW.isoformat()},
            "end": {"dateTime": (NOW + timedelta(hours=1)).isoformat()},
        },
    )


def _outlook_native(installation: Installation, title: str = "Planning") -> str:
    return installation.graph.events.seed(
        MAILBOXES["work-account"][0],
        "work-calendar",
        {
            "subject": title,
            "body": {"contentType": "text", "content": ""},
            "isAllDay": False,
            "start": {
                "dateTime": (NOW + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": (NOW + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "UTC",
            },
        },
    )


def _utc(moment: Any) -> dict[str, str]:
    return {"dateTime": moment.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}


def _origin(event: Any) -> ManagedOrigin | None:
    from calendar_sync.infrastructure.microsoft.translation import to_domain_event

    return to_domain_event({"id": event.id, **event.fields}, OUTLOOK_CALENDAR).managed_origin


def test_a_google_event_projects_into_an_outlook_calendar_as_busy() -> None:
    installation = _installation(TO_OUTLOOK)
    _google_native(installation, "google-dentist")

    installation.run(TO_OUTLOOK)

    (projection,) = installation.outlook_events()
    assert projection.fields["subject"] == "Busy"
    origin = _origin(projection)
    assert origin is not None
    assert (origin.rule_id, origin.source.calendar, origin.source.event_id.value) == (
        TO_OUTLOOK.id,
        GOOGLE_CALENDAR,
        "google-dentist",
    )
    assert installation.graph.events.mail == []


def test_an_outlook_event_projects_into_a_google_calendar_and_its_removal_follows() -> None:
    installation = _installation(TO_GOOGLE)
    native = _outlook_native(installation)

    installation.run(TO_GOOGLE)
    (projection,) = installation.google_events().values()
    installation.graph.events._delete(MAILBOXES["work-account"][0], "work-calendar", native)
    installation.run(TO_GOOGLE)

    assert projection["summary"] == "Busy"
    assert projection["extendedProperties"]["private"]["gcs_rule_id"] == TO_GOOGLE.id.value
    remaining = [e for e in installation.google_events().values() if e.get("status") != "cancelled"]
    assert remaining == []


def test_rules_in_both_directions_never_copy_each_others_projections() -> None:
    installation = _installation(TO_OUTLOOK, TO_GOOGLE)
    _google_native(installation, "google-dentist")
    _outlook_native(installation)

    installation.run(TO_OUTLOOK, TO_GOOGLE)
    outlook_after_first = len(installation.outlook_events())
    google_after_first = len(installation.google_events())
    writes = (len(installation.google.writes), len(installation.graph.events.writes))
    installation.run(TO_OUTLOOK, TO_GOOGLE, TO_OUTLOOK, TO_GOOGLE)

    # One native and one projection on each side, and nothing written again.
    assert (outlook_after_first, google_after_first) == (2, 2)
    assert len(installation.outlook_events()) == 2
    assert len(installation.google_events()) == 2
    assert (len(installation.google.writes), len(installation.graph.events.writes)) == writes
    mappings = installation.factory.state.mappings
    assert {rule for rule, _ in mappings} == {TO_OUTLOOK.id, TO_GOOGLE.id}
    assert len(mappings) == 2


def test_a_projection_edited_in_outlook_is_put_back_from_google() -> None:
    installation = _installation(TO_OUTLOOK)
    _google_native(installation, "google-dentist")
    installation.run(TO_OUTLOOK)
    (projection,) = installation.outlook_events()
    installation.graph.events._patch(
        MAILBOXES["work-account"][0], "work-calendar", projection.id, {"subject": "Edited"}
    )

    installation.run(TO_OUTLOOK)

    (repaired,) = installation.outlook_events()
    assert repaired.fields["subject"] == "Busy"


def test_a_native_outlook_event_is_never_touched_by_a_rule_writing_to_its_calendar() -> None:
    installation = _installation(TO_OUTLOOK)
    native = _outlook_native(installation)
    _google_native(installation, "google-dentist")

    installation.run(TO_OUTLOOK, TO_OUTLOOK)

    assert installation.graph.events.stored[native].fields["subject"] == "Planning"
    assert native not in {event_id for _, event_id, _ in installation.graph.events.writes}
    cancelled = [
        e for e in installation.factory.state.audit if e.reason and "removed" in e.reason.value
    ]
    assert cancelled == []
    mapped = installation.factory.state.mappings.values()
    projections = [installation.sync.provider.get_event(m.destination) for m in mapped]
    assert all(e is None or e.status is EventStatus.CONFIRMED for e in projections)
