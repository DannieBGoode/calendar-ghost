from __future__ import annotations

import json
import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from urllib.request import Request, urlopen

from calendar_sync.application.ports import IncidentReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IncidentNotification:
    rule_id: str
    category: str
    summary: str
    occurred_at: str


class IncidentNotifier:
    """Best-effort, self-hosted delivery for newly opened incidents."""

    def __init__(self, channels: Sequence[NotificationChannel]) -> None:
        self._channels = tuple(channels)

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        self.notify(
            IncidentNotification(
                incident.rule_id.value, incident.category, incident.summary, at.isoformat()
            )
        )

    def notify(self, incident: IncidentNotification) -> None:
        for channel in self._channels:
            try:
                channel.send(incident)
            except Exception:
                logger.exception("Incident notification delivery failed")


class NotificationChannel:
    def send(self, incident: IncidentNotification) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class WebhookChannel(NotificationChannel):
    url: str

    def send(self, incident: IncidentNotification) -> None:
        body = json.dumps(
            {
                "type": "calendar_sync.incident.opened",
                "rule_id": incident.rule_id,
                "category": incident.category,
                "summary": incident.summary,
                "occurred_at": incident.occurred_at,
            }
        ).encode()
        # The installation administrator configures this URL.
        request = Request(  # noqa: S310
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10):  # noqa: S310
            pass


@dataclass(frozen=True, slots=True)
class SmtpChannel(NotificationChannel):
    host: str
    port: int
    sender: str
    recipient: str
    username: str = ""
    password: str = ""
    use_starttls: bool = True

    def send(self, incident: IncidentNotification) -> None:
        message = EmailMessage()
        message["Subject"] = f"Calendar Ghost incident: {incident.summary}"
        message["From"] = self.sender
        message["To"] = self.recipient
        message.set_content(
            "\n".join(
                (
                    incident.summary,
                    "",
                    f"Rule: {incident.rule_id}",
                    f"Category: {incident.category}",
                    f"Opened: {incident.occurred_at}",
                    "",
                    "Open Calendar Ghost Activity for current status.",
                )
            )
        )
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_starttls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)
