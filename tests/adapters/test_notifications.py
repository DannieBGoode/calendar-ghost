from dataclasses import replace
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from calendar_sync.infrastructure.notifications import IncidentNotification, SmtpChannel


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
        host="smtp.example", port=587, sender="a@example.com", recipient="b@example.com"
    )

    channel.send(incident())

    (message,) = RecordingSmtp.sent
    assert message["Subject"].startswith("Calendar Ghost incident: ")
    assert "Open Calendar Ghost Activity for current status." in message.get_content()


def test_an_account_incident_email_names_no_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.sent = []
    monkeypatch.setattr("calendar_sync.infrastructure.notifications.smtplib.SMTP", RecordingSmtp)
    channel = SmtpChannel(
        host="smtp.example", port=587, sender="a@example.com", recipient="b@example.com"
    )

    channel.send(replace(incident(), rule_id=None, category="authentication"))

    (message,) = RecordingSmtp.sent
    assert "Rule:" not in message.get_content()
    assert "Category: authentication" in message.get_content()
