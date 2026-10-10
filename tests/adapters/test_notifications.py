from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.installation_health import (
    InstallationIncident,
    InstallationIncidentKind,
)
from calendar_sync.application.ports import IncidentReport
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose, public_address
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.infrastructure.notifications import (
    IncidentNotification,
    IncidentNotifier,
    NotificationChannel,
    OwnerNotifier,
    SmtpChannel,
    SmtpServer,
)
from tests.helpers import NOW
from tests.identity_fakes import MemoryUsers
from tests.users import ADMIN_EMAIL, administrator


class RecordingSmtp:
    sent: ClassVar[list[EmailMessage]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> "RecordingSmtp":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self) -> None:
        pass

    def login(self, *_args: str) -> None:
        pass

    def send_message(self, message: EmailMessage) -> None:
        RecordingSmtp.sent.append(message)


def incident() -> IncidentNotification:
    return IncidentNotification(
        rule_id="rule-1",
        category="sync_failed",
        summary="A rule needs attention",
        occurred_at="2026-10-02T12:00:00+00:00",
    )


def test_incident_email_names_the_product(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    channel = SmtpChannel(
        SmtpServer(host="smtp.example", port=587, sender="a@example.com"), recipient="b@example.com"
    )

    channel.send(incident())

    (message,) = RecordingSmtp.sent
    assert message["Subject"].startswith("Calendar Ghost incident: ")
    assert "Open Calendar Ghost Activity for current status." in message.get_content()


def test_an_account_incident_email_names_no_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    channel = SmtpChannel(
        SmtpServer(host="smtp.example", port=587, sender="a@example.com"), recipient="b@example.com"
    )

    channel.send(replace(incident(), rule_id=None, category="authentication"))

    (message,) = RecordingSmtp.sent
    assert "Rule:" not in message.get_content()
    assert "Category: authentication" in message.get_content()


def _server() -> SmtpServer:
    return SmtpServer(host="smtp.example", port=587, sender="ghost@example.test")


def _report() -> IncidentReport:
    return IncidentReport("provider:rule-1", SyncRuleId("rule-1"), "temporary", "Google is busy")


def _owner(**changes: Any) -> MemoryUsers:
    users = MemoryUsers()
    owner = User(UserId("owner"), "owner@example.test", Role.USER, UserState.ACTIVE, NOW)
    users.add(replace(owner, **changes), "hash")
    return users


def test_an_incident_is_emailed_to_the_user_who_owns_it(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)

    OwnerNotifier(_owner(), UserId("owner"), _server()).incident_opened(_report(), NOW)

    (message,) = RecordingSmtp.sent
    assert (message["To"], message["From"]) == ("owner@example.test", "ghost@example.test")
    assert "Google is busy" in message.get_content()


@pytest.mark.parametrize(
    "changes",
    [{"notify_by_email": False}, {"email": None}, {"state": UserState.DISABLED}],
)
def test_no_email_goes_to_a_user_who_turned_it_off_has_no_address_or_is_disabled(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)

    OwnerNotifier(_owner(**changes), UserId("owner"), _server()).incident_opened(_report(), NOW)

    assert RecordingSmtp.sent == []


def test_a_failed_email_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("unreachable")

    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", refuse)

    OwnerNotifier(_owner(), UserId("owner"), _server()).incident_opened(_report(), NOW)


def test_the_installation_channels_hear_of_a_stalled_scheduler() -> None:
    heard: list[IncidentNotification] = []

    class Recording(NotificationChannel):
        def send(self, incident: IncidentNotification) -> None:
            heard.append(incident)

    stalled = InstallationIncident(InstallationIncidentKind.SCHEDULER_STALLED, NOW)
    IncidentNotifier([Recording()]).installation_incident_opened(stalled)

    assert heard == [
        IncidentNotification(
            rule_id=None,
            category="scheduler_stalled",
            summary="Scheduled synchronization stopped running",
            occurred_at=NOW.isoformat(),
        )
    ]


def test_an_installation_emails_rule_incidents_to_their_owner_and_never_to_its_webhook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    RecordingSmtp.sent = []
    posted: list[object] = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    monkeypatch.setattr(
        "calendar_sync.infrastructure.notifications.urlopen", lambda *a, **k: posted.append(a)
    )
    settings = Settings(
        tmp_path / "test.db",
        incident_webhook_url="https://hooks.example.test/incident",
        smtp_host="smtp.example.test",
        smtp_sender="ghost@example.test",
        smtp_recipient="operator@example.test",
    )
    adapters = build_adapters(settings)
    owner = administrator(adapters)
    container = compose(settings, adapters)

    notifications = container.for_user(owner).rule_health.notifications
    assert notifications is not None
    notifications.incident_opened(_report(), NOW)

    (message,) = RecordingSmtp.sent
    assert message["To"] == ADMIN_EMAIL
    assert posted == []


@pytest.mark.parametrize(
    ("report", "link"),
    [
        # The User's own step: reauthorize, or the rule where they choose another calendar.
        (
            IncidentReport(
                "authorization:a",
                None,
                "authentication",
                "expired",
                account_id=ConnectedAccountId("a"),
                cause=Cause.ACCESS_REVOKED,
            ),
            "https://ghost.example.test/settings/connections",
        ),
        (
            IncidentReport(
                "provider:rule-1",
                SyncRuleId("rule-1"),
                "authorization",
                "denied",
                cause=Cause.CALENDAR_FORBIDDEN,
            ),
            "https://ghost.example.test/rules/rule-1",
        ),
        (
            IncidentReport(
                "provider:rule-1",
                SyncRuleId("rule-1"),
                "permanent",
                "rejected",
                cause=Cause.CALENDAR_NOT_FOUND,
            ),
            "https://ghost.example.test/rules/rule-1",
        ),
        (
            IncidentReport(
                "provider:rule-1",
                SyncRuleId("rule-1"),
                "permanent",
                "rejected",
                cause=Cause.UNKNOWN,
            ),
            "https://ghost.example.test/rules/rule-1",
        ),
        # Nothing for them to do: the Overview says it fixes itself, or who fixes it.
        (
            IncidentReport(
                "provider:rule-1",
                SyncRuleId("rule-1"),
                "rate_limit",
                "busy",
                cause=Cause.RATE_LIMITED,
            ),
            "https://ghost.example.test/",
        ),
        (
            IncidentReport(
                "authorization:a",
                None,
                "authorization",
                "denied",
                account_id=ConnectedAccountId("a"),
                cause=Cause.API_DISABLED,
            ),
            "https://ghost.example.test/",
        ),
        (
            IncidentReport("blocked:rule-1", SyncRuleId("rule-1"), "conflict", "blocked"),
            "https://ghost.example.test/activity",
        ),
    ],
)
def test_an_incident_email_links_to_the_owners_next_step(
    monkeypatch: pytest.MonkeyPatch, report: IncidentReport, link: str
) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)

    OwnerNotifier(
        _owner(), UserId("owner"), _server(), public_url="https://ghost.example.test"
    ).incident_opened(report, NOW)

    (message,) = RecordingSmtp.sent
    assert f"What to do next: {link}" in message.get_content()
    assert "Open Calendar Ghost Activity" not in message.get_content()


def test_without_a_public_address_an_incident_email_has_no_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)

    OwnerNotifier(_owner(), UserId("owner"), _server()).incident_opened(_report(), NOW)

    (message,) = RecordingSmtp.sent
    assert "http" not in message.get_content()
    assert "Open Calendar Ghost Activity for current status." in message.get_content()


@pytest.mark.parametrize(
    ("configured", "used"),
    [
        ("https://ghost.example.test", "https://ghost.example.test"),
        ("https://ghost.example.test/calendar/", "https://ghost.example.test/calendar"),
        ("http://192.168.1.50:8000", "http://192.168.1.50:8000"),
        ("", None),
        ("ghost.example.test", None),
        ("javascript:alert(1)", None),
        ("https://ghost.example.test/?q=1", None),
    ],
)
def test_only_an_http_address_is_used_as_the_public_address(
    tmp_path: Path, configured: str, used: str | None
) -> None:
    settings = Settings(tmp_path / "test.db", public_url=configured)

    assert public_address(settings) == used


def test_the_public_address_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_PUBLIC_URL", "https://ghost.example.test")

    assert Settings.from_environment().public_url == "https://ghost.example.test"
